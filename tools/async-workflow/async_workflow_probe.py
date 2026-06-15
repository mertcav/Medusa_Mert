#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.4 — Asenkron uzun-işlem workflow (callback/polling) (SAD §11.2 / FR-TOOL-011) referans probe.

    LLM tool call ──► [1] schema ──► [2] authz ──► [3] policy ──► [4] idempotency
                  ──► [5] Integration GW {7.1.4 timeout+retry+breaker} ─► connector.upstream_call(dispatch)  [7.2.1/7.2.2]
                  ──► 202 Accepted + job_ref ─► 7.2.4 dispatch() → PENDING (NON-BLOCKING)  ◄── bu modül
                  ··· OUT-OF-BAND ··· callback ingest (HMAC doğrula) ∨ poll step (bounded) → terminal
                  ──► tool.async.completed (result_ref) + [7] correlation_id audit

Bu modül FR-TOOL-011'i gerçekler: orkestratör uzun işlemi BEKLEMEZ (SAD §11.2). Dispatch HEMEN
'pending' + execution_id döner (W1). Nihai sonuç İKİ mutabakat moduyla gelir:
  • CALLBACK (inbound webhook): HMAC-SHA256 imza + ±300s timestamp + nonce replay reddi (SEC-05/TM-S-05);
  • POLLING: bounded backoff+jitter+deadline (W5/W6).
Callback ∧ poll yarışı IDEMPOTENT exactly-once (W3); terminal-immutable (W2); tenant+correlation
binding (W7); result-by-reference (W8); idempotency-key köprüsü FR-TOOL-009 (W9); audit no-log (W11);
determinizm (W12).

INVARIANT (SR-TOOL-011 kabul ölçütü): 'Uzun işlem bloklamadan callback/polling ile tamamlanır'.

Kapsam dışı (bilinçli): dispatch transport → 7.2.1/7.2.2 (bu modül AttemptOutcome'unu tüketir);
dispatch timeout/retry/breaker → 7.1.4; allowlist → 7.2.3; schema → 7.1.1; authz → 7.1.2;
idempotency ÜRETİMİ → 7.1.3; müşteri hata metni → 7.1.5; audit zenginleştirme → 7.1.6;
sonuç payload'ı nesne deposuna yazımı → 1.1.6 (bu modül result_ref TAŞIR); kritik-işlem teyidi → 7.3.

Kullanım:
  async_workflow_probe.py validate           Statik spec/config/şema kapısı → çıkış kodu
  async_workflow_probe.py run <sample>       Deterministik async akış(lar)ı: dispatch + timeline → kapı (W1–W12)
  async_workflow_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  async_workflow_probe.py schema             Durum makinesi/callback/sözleşmeleri yazdır

Determinizm: sanal saat (at_ms) + tohumlu jitter; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008; host'lar
example.com; imza fixture-secret yalnız runtime'da hesaplanır, repoya yazılmaz).
"""
import hashlib
import hmac
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "async-workflow-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "async-workflow-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# Fixture imza sırrı: YALNIZ referans probe/test için (gerçek credential DEĞİL, repoya "sır" olarak
# yazılmaz — kısa sabit dize; canlıda ${ASYNC_CALLBACK_SIGNING_KEY} kullanılır).
FIXTURE_SIGNING_SECRET = "chanteur-fixture-hmac-key"

# ── Durum makinesi (W2) ──────────────────────────────────────────────────────────
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED"}
NON_TERMINAL_STATES = {"PENDING", "RUNNING"}
ALL_STATES = TERMINAL_STATES | NON_TERMINAL_STATES

# ── Fault taksonomisi (7.1.4 ile BİREBİR hizalı; W10) ────────────────────────────
RETRYABLE_FAULTS = {"TIMEOUT", "UPSTREAM_5XX", "CONN_RESET", "CONN_REFUSED", "RATE_LIMITED", "DEADLINE_EXCEEDED"}
TERMINAL_FAULTS = {"UPSTREAM_4XX", "SCHEMA_INVALID", "AUTH_FAILED", "NOT_FOUND"}
ASYNC_GATE_FAULTS = {"ASYNC_DEADLINE_EXCEEDED", "CALLBACK_REJECTED"}

REJECT_REASONS = {"BAD_SIGNATURE", "MISSING_SIGNATURE", "TIMESTAMP_OUT_OF_WINDOW", "NONCE_REPLAYED",
                  "TENANT_MISMATCH", "CORRELATION_MISMATCH", "UNKNOWN_EXECUTION"}

ERROR_CLASSES = {"MISSING_WORKFLOW_CONFIG", "INVALID_WORKFLOW_SPEC", "MISSING_SIGNING_CONFIG",
                 "LITERAL_SECRET_IN_SPEC", "INVALID_INVOCATION", "UNKNOWN_EXECUTION",
                 "NON_MONOTONIC_CLOCK", "INTERNAL_ERROR"}

GATE_IDS = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10", "W11", "W12"]

ACCEPTED_DISPATCH_STATUSES = {200, 201, 202}
COMPLETED_EVENT_TYPE = "tool.async.completed"
COMPLETED_FIELDS = {"execution_id", "status", "result_ref"}
FORBIDDEN_INLINE = {"result", "payload", "body", "pii"}

PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
SECRET_KEY_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|"
    r"access[_-]?token|signing[_-]?key|hmac[_-]?key)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _strip_meta(d):
    return {k: v for k, v in d.items() if not k.startswith("$")}


class WorkflowError(Exception):
    def __init__(self, error_class, reason=""):
        super().__init__(reason)
        self.error_class = error_class
        self.reason = reason


def compute_signature(secret, ts, body):
    """HMAC-SHA256(secret, '<ts>.<body>') hex (API §10.1 v1=...)."""
    msg = ("%s.%s" % (ts, body)).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


# ── Async workflow engine (vendor-neutral; reconciliation mantığı transport'tan bağımsız) ─────
class AsyncWorkflowEngine:
    """Bir AsyncWorkflowSpec için dispatch + callback/poll reconciliation.

    Durum (execution registry, nonce seti, dedup) instance ömrü boyunca kalıcıdır.
    NON-BLOCKING dispatch (W1); idempotent exactly-once (W3); HMAC callback (W4);
    bounded poll (W5); deadline reaper (W6). Date.now/gerçek-rastgele YOK (W12).
    """

    def __init__(self, spec, redact_audit=True, signing_secret=FIXTURE_SIGNING_SECRET):
        self.spec = spec
        self.redact_audit = redact_audit  # default True; degraded fixture False ile W8/W11 gate'i sınar
        self.signing_secret = signing_secret
        self.clock_ms = 0
        self.executions = {}      # execution_id -> exec dict
        self._dedup = {}          # (tenant_id, idempotency_key) -> execution_id
        self._nonces = set()      # replay koruması (W4)
        self.audit = []
        self.emitted = []         # tool.async.completed envelope'ları
        self._validate_spec()

    # — spec doğrulama (W4 signing + sır referansla) —
    def _validate_spec(self):
        spec = self.spec
        for k in ("workflow_id", "mode"):
            if k not in spec:
                raise WorkflowError("INVALID_WORKFLOW_SPEC", "eksik alan: %s" % k)
        if spec["mode"] not in ("callback", "polling", "hybrid"):
            raise WorkflowError("INVALID_WORKFLOW_SPEC", "mode callback/polling/hybrid olmalı")
        cb = spec.get("callback") or {}
        # callback/hybrid → signing referansı zorunlu (W4); literal sır reddedilir
        if spec["mode"] in ("callback", "hybrid"):
            ref = cb.get("signing_ref", "")
            if not ref:
                raise WorkflowError("MISSING_SIGNING_CONFIG", "callback signing_ref zorunlu (HMAC)")
            if not _is_placeholder(ref):
                raise WorkflowError("LITERAL_SECRET_IN_SPEC", "callback.signing_ref placeholder ${ENV} olmalı")
        # polling/hybrid → bounded poll yapılandırması (W5)
        if spec["mode"] in ("polling", "hybrid"):
            poll = spec.get("poll") or {}
            if int(poll.get("max_attempts", 0)) <= 0:
                raise WorkflowError("INVALID_WORKFLOW_SPEC", "poll.max_attempts > 0 olmalı (bounded W5)")

    def _ts_tolerance_s(self):
        return int((self.spec.get("callback") or {}).get("ts_tolerance_s", 300))

    def _poll_cfg(self):
        p = self.spec.get("poll") or {}
        return (int(p.get("max_attempts", 5)), int(p.get("base_backoff_ms", 1000)),
                int(p.get("max_backoff_ms", 60000)), int(p.get("jitter_ms", 0)))

    @staticmethod
    def _final_disposition(status):
        return "ok" if status == "SUCCEEDED" else "fault"

    def _advance_clock(self, at_ms):
        if at_ms is None:
            return
        at = int(at_ms)
        if at < self.clock_ms:
            raise WorkflowError("NON_MONOTONIC_CLOCK", "at_ms < clock_ms")
        self.clock_ms = at

    # ── dispatch (W1 non-blocking, W9 idempotency dedup) ──────────────────────────
    def dispatch(self, req):
        if not isinstance(req, dict):
            raise WorkflowError("INVALID_INVOCATION", "dispatch req dict değil")
        for k in ("execution_id", "tenant_id", "correlation_id", "operation"):
            if k not in req:
                raise WorkflowError("INVALID_INVOCATION", "dispatch eksik alan: %s" % k)
        self._advance_clock(req.get("at_ms"))

        # W9: idempotency-key dedup → aynı execution (iki upstream iş YOK)
        idem = req.get("idempotency_key")
        if idem:
            dk = (req["tenant_id"], idem)
            if dk in self._dedup:
                exid = self._dedup[dk]
                self._audit(self.executions[exid], note="dispatch-dedup")
                return {"execution_id": exid, "status": self.executions[exid]["status"],
                        "non_blocking": True, "accepted": True, "deduped": True,
                        "endpoint": self.executions[exid]["endpoint"]}

        exid = req["execution_id"]
        # dispatch AttemptOutcome'unu TÜKET (7.2.1/7.2.2). Yoksa varsay 202 accepted.
        d = req.get("dispatch") or {"result": "ok", "status_code": 202}
        d_result = d.get("result", "ok")
        d_status = d.get("status_code")
        endpoint = req.get("endpoint", "POST %s" % req["operation"])

        ex = {
            "execution_id": exid, "tenant_id": req["tenant_id"],
            "correlation_id": req["correlation_id"], "operation": req["operation"],
            "endpoint": endpoint, "mode": self.spec["mode"],
            "status": "PENDING", "attempts": 0,
            "created_ms": self.clock_ms,
            "deadline_ms": self.clock_ms + int(req.get("deadline_ms", 60000)),
            "next_poll_ms": self.clock_ms + self._poll_cfg()[1] if self.spec["mode"] in ("polling", "hybrid") else None,
            "result_ref": None, "fault_class": None, "completed_emitted": False,
            "non_blocking": True,
        }

        # ex["status"] PENDING başlar; terminal dispatch fault'ları _complete ile geçişir
        # (W3 exactly-once emit; doğrudan FAILED set etmek emit'i bypass ederdi).
        terminal_dispatch = None
        if d_result == "ok" and (d_status is None or d_status in ACCEPTED_DISPATCH_STATUSES):
            pass  # PENDING (non-blocking; reconciliation bekler)
        elif d_result == "fault":
            fc = d.get("fault_class")
            if fc in TERMINAL_FAULTS:
                # terminal dispatch fault → async başlamaz, FAILED
                ex["fault_class"] = fc
                terminal_dispatch = "FAILED"
            # retryable dispatch fault → 7.1.4'e ait; nihai sonuç gelene dek PENDING bırakılır.
        else:
            # ok ama beklenmeyen status (accepted değil) → güvenli taraf: FAILED
            ex["fault_class"] = "UPSTREAM_4XX"
            terminal_dispatch = "FAILED"

        self.executions[exid] = ex
        if idem:
            self._dedup[(req["tenant_id"], idem)] = exid

        # terminal dispatch fault da exactly-once emit edilir (W3)
        if terminal_dispatch:
            self._complete(ex, terminal_dispatch, None, source="dispatch")
        self._audit(ex, note="dispatch")
        return {"execution_id": exid, "status": ex["status"], "non_blocking": True,
                "accepted": ex["status"] != "FAILED", "deduped": False, "endpoint": endpoint}

    # ── terminal geçiş + exactly-once emit (W2/W3/W8) ─────────────────────────────
    def _complete(self, ex, status, result_ref, source):
        if ex["status"] in TERMINAL_STATES:
            # W3: zaten terminal → idempotent no-op (ikinci emit YOK)
            return False
        if status not in TERMINAL_STATES:
            raise WorkflowError("INTERNAL_ERROR", "terminal olmayan complete: %s" % status)
        ex["status"] = status
        if result_ref is not None:
            ex["result_ref"] = result_ref
        # W8: tool.async.completed yalnız {execution_id, status, result_ref} — ham payload YOK
        if not ex["completed_emitted"]:
            self.emitted.append({
                "type": COMPLETED_EVENT_TYPE,
                "tenant_id": ex["tenant_id"], "correlation_id": ex["correlation_id"],
                "execution_id": ex["execution_id"], "status": status,
                "result_ref": ex["result_ref"],
            })
            ex["completed_emitted"] = True
        return True

    # ── callback ingest (W4 authenticity, W3 idempotent, W7 binding) ──────────────
    def ingest_callback(self, cb):
        self._advance_clock(cb.get("at_ms"))
        exid = cb.get("execution_id")
        ex = self.executions.get(exid)
        if ex is None:
            self._audit_reject(exid, cb.get("correlation_id", ""), "UNKNOWN_EXECUTION")
            return {"result": "rejected", "reject_reason": "UNKNOWN_EXECUTION", "fault_class": "CALLBACK_REJECTED"}

        # W7: tenant + correlation binding (imzadan ÖNCE — bilgi sızdırmaz, yalnız kod döner)
        if cb.get("tenant_id") != ex["tenant_id"]:
            self._audit_reject(exid, ex["correlation_id"], "TENANT_MISMATCH")
            return {"result": "rejected", "reject_reason": "TENANT_MISMATCH", "fault_class": "CALLBACK_REJECTED"}
        if cb.get("correlation_id") != ex["correlation_id"]:
            self._audit_reject(exid, ex["correlation_id"], "CORRELATION_MISMATCH")
            return {"result": "rejected", "reject_reason": "CORRELATION_MISMATCH", "fault_class": "CALLBACK_REJECTED"}

        # W4: HMAC imza + timestamp penceresi + nonce replay
        sig = cb.get("sig")
        ts = cb.get("ts")
        body = cb.get("body", "")
        if sig is None or ts is None:
            self._audit_reject(exid, ex["correlation_id"], "MISSING_SIGNATURE")
            return {"result": "rejected", "reject_reason": "MISSING_SIGNATURE", "fault_class": "CALLBACK_REJECTED"}
        expected = compute_signature(self.signing_secret, ts, body)
        if not hmac.compare_digest(expected, str(sig)):
            self._audit_reject(exid, ex["correlation_id"], "BAD_SIGNATURE")
            return {"result": "rejected", "reject_reason": "BAD_SIGNATURE", "fault_class": "CALLBACK_REJECTED"}
        # timestamp penceresi: |now_s - ts| ≤ tolerance
        now_s = self.clock_ms // 1000
        if abs(now_s - int(ts)) > self._ts_tolerance_s():
            self._audit_reject(exid, ex["correlation_id"], "TIMESTAMP_OUT_OF_WINDOW")
            return {"result": "rejected", "reject_reason": "TIMESTAMP_OUT_OF_WINDOW", "fault_class": "CALLBACK_REJECTED"}
        nonce = cb.get("nonce")
        if nonce is None or nonce in self._nonces:
            self._audit_reject(exid, ex["correlation_id"], "NONCE_REPLAYED")
            return {"result": "rejected", "reject_reason": "NONCE_REPLAYED", "fault_class": "CALLBACK_REJECTED"}
        self._nonces.add(nonce)

        # imza geçerli — terminal uygula (W3 idempotent; zaten terminal ise no-op)
        status = cb.get("status", "SUCCEEDED")
        if status not in TERMINAL_STATES:
            # callback yalnız terminal sonuç taşır; non-terminal → RUNNING güncelle
            if ex["status"] == "PENDING":
                ex["status"] = "RUNNING"
            self._audit(ex, note="callback-progress")
            return {"result": "accepted", "status": ex["status"], "completed": False}
        applied = self._complete(ex, status, cb.get("result_ref"), source="callback")
        self._audit(ex, note="callback-terminal" if applied else "callback-idempotent-noop")
        return {"result": "accepted", "status": ex["status"], "completed": applied,
                "disposition": self._final_disposition(ex["status"])}

    # ── poll step (W5 bounded, W6 deadline reaper) ────────────────────────────────
    def poll_step(self, at_ms, upstream):
        """Bir poll tetiği. upstream: {status, result_ref?} — referans deterministik upstream snapshot."""
        self._advance_clock(at_ms)
        ex_id = upstream.get("execution_id") if isinstance(upstream, dict) else None
        # tek-execution örneklerde execution_id zorunlu değil; ilk non-terminal'i bul
        ex = self.executions.get(ex_id) if ex_id else self._first_active()
        if ex is None:
            return {"result": "noop", "reason": "no-active-execution"}

        # W6: deadline reaper (poll due olmasa bile)
        if self.clock_ms >= ex["deadline_ms"] and ex["status"] not in TERMINAL_STATES:
            self._complete(ex, "TIMED_OUT", None, source="deadline")
            ex["fault_class"] = "ASYNC_DEADLINE_EXCEEDED"
            self._audit(ex, note="deadline-timeout")
            return {"result": "timed_out", "status": ex["status"], "fault_class": "ASYNC_DEADLINE_EXCEEDED"}

        if ex["status"] in TERMINAL_STATES:
            return {"result": "noop", "reason": "already-terminal", "status": ex["status"]}
        if ex["mode"] == "callback":
            return {"result": "noop", "reason": "callback-only-mode"}
        if ex["next_poll_ms"] is not None and self.clock_ms < ex["next_poll_ms"]:
            return {"result": "noop", "reason": "not-due"}

        max_attempts, base, cap, jitter = self._poll_cfg()
        ex["attempts"] += 1
        up_status = (upstream or {}).get("status", "RUNNING")
        if up_status in TERMINAL_STATES:
            self._complete(ex, up_status, (upstream or {}).get("result_ref"), source="poll")
            self._audit(ex, note="poll-terminal")
            return {"result": "terminal", "status": ex["status"], "attempts": ex["attempts"],
                    "disposition": self._final_disposition(ex["status"])}
        if up_status == "PENDING" and ex["status"] == "PENDING":
            pass  # henüz başlamadı
        else:
            ex["status"] = "RUNNING"
        # W5: bounded — attempt tükendi mi?
        if ex["attempts"] >= max_attempts:
            self._complete(ex, "TIMED_OUT", None, source="poll-exhausted")
            ex["fault_class"] = "ASYNC_DEADLINE_EXCEEDED"
            self._audit(ex, note="poll-exhausted")
            return {"result": "timed_out", "status": ex["status"], "attempts": ex["attempts"],
                    "fault_class": "ASYNC_DEADLINE_EXCEEDED"}
        # bir sonraki poll: exponential backoff (cap) + tohumlu jitter (deterministik)
        backoff = min(cap, base * (2 ** (ex["attempts"] - 1)))
        j = self._seeded_jitter(ex, jitter)
        ex["next_poll_ms"] = self.clock_ms + backoff + j
        self._audit(ex, note="poll-progress")
        return {"result": "progress", "status": ex["status"], "attempts": ex["attempts"],
                "next_poll_ms": ex["next_poll_ms"]}

    def _seeded_jitter(self, ex, jitter_ms):
        if jitter_ms <= 0:
            return 0
        # tohumlu deterministik jitter: execution_id + attempt hash (Date.now/random YOK — W12)
        h = hashlib.sha256(("%s:%d" % (ex["execution_id"], ex["attempts"])).encode("utf-8")).digest()
        return h[0] % (jitter_ms + 1)

    def _first_active(self):
        for ex in self.executions.values():
            if ex["status"] not in TERMINAL_STATES:
                return ex
        return None

    # ── audit (W11 no-log) ────────────────────────────────────────────────────────
    def _audit(self, ex, note=""):
        rec = {
            "execution_id": ex["execution_id"], "correlation_id": ex["correlation_id"],
            "status": ex["status"], "endpoint": ex["endpoint"], "attempts": ex["attempts"],
            "reject_reason": None, "no_log": True, "note": note,
        }
        if not self.redact_audit:
            # degraded knob: redaksiyon kapalı → ham result_ref/payload audit'e sızar (W8/W11 gate kanıtı)
            rec["raw_result"] = ex.get("_raw_result_for_degraded", "")
            rec["raw_result_ref"] = ex.get("result_ref")
        self.audit.append(rec)

    def _audit_reject(self, exid, corr, reason):
        rec = {
            "execution_id": exid, "correlation_id": corr, "status": "REJECTED",
            "endpoint": None, "attempts": None, "reject_reason": reason, "no_log": True,
            "note": "callback-reject",
        }
        self.audit.append(rec)


# ── sample yürütme ───────────────────────────────────────────────────────────────
def _resolve_spec(sample):
    if "workflow" in sample:
        return _strip_meta(sample["workflow"])
    cfg = _load(CONFIG_PATH)
    prof = sample.get("profile")
    if prof and prof in cfg["profiles"]:
        return _strip_meta(cfg["profiles"][prof])
    return None


def _sign_callback(secret, cb):
    """Sample deklaratif callback'ini gerçek HMAC ile imzala (referans). cb mutasyonları:
    sign:false → imza eksik; tamper_body → imza-sonrası gövde değiştir; bad_sig → imzayı boz."""
    out = dict(cb)
    body = cb.get("body", "")
    ts = cb.get("ts")
    if cb.get("sign", True) and ts is not None:
        sig = compute_signature(secret, ts, body)
        if cb.get("tamper_body"):
            out["body"] = body + "X"        # imza ESKİ gövdeye; yeni gövde uyuşmaz → BAD_SIGNATURE
        if cb.get("bad_sig"):
            sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        out["sig"] = sig
    else:
        out.pop("sig", None)
    return out


def _run_sample(sample):
    spec = _resolve_spec(sample)
    if spec is None:
        return {"error_class": "MISSING_WORKFLOW_CONFIG", "engine": None, "dispatch": None, "events": []}
    redact = sample.get("redact_audit", True)
    try:
        engine = AsyncWorkflowEngine(spec, redact_audit=redact)
    except WorkflowError as e:
        return {"error_class": e.error_class, "engine": None, "dispatch": None, "events": []}

    events_out = []
    try:
        disp = engine.dispatch(sample["dispatch_req"])
        # degraded: ham sonucu execution'a yapıştır (yalnız redact=False fixture)
        if not redact:
            ex = engine.executions[sample["dispatch_req"]["execution_id"]]
            ex["_raw_result_for_degraded"] = sample.get("_raw_result", "")
        for ev in sample.get("timeline", []):
            kind = ev.get("kind")
            if kind == "callback":
                cb = _sign_callback(engine.signing_secret, ev)
                r = engine.ingest_callback(cb)
            elif kind == "poll":
                r = engine.poll_step(ev.get("at_ms"), ev.get("upstream") or {})
            elif kind == "tick":
                engine._advance_clock(ev.get("at_ms"))
                # tick: deadline reaper'ı tetikle (poll-yok yolda zombie önleme W6)
                r = engine.poll_step(ev.get("at_ms"), {"status": "RUNNING"}) \
                    if spec["mode"] != "callback" else _reap_on_tick(engine, ev.get("at_ms"))
            else:
                r = {"result": "unknown-event"}
            events_out.append({"event": ev.get("name", kind), "result": r})
    except WorkflowError as e:
        return {"error_class": e.error_class, "engine": engine, "dispatch": None, "events": events_out}
    return {"error_class": None, "engine": engine, "dispatch": disp, "events": events_out}


def _reap_on_tick(engine, at_ms):
    """callback-only modda tick → deadline reaper (W6; poll yok)."""
    ex = engine._first_active()
    if ex is None:
        return {"result": "noop"}
    if engine.clock_ms >= ex["deadline_ms"] and ex["status"] not in TERMINAL_STATES:
        engine._complete(ex, "TIMED_OUT", None, source="deadline")
        ex["fault_class"] = "ASYNC_DEADLINE_EXCEEDED"
        engine._audit(ex, note="deadline-timeout")
        return {"result": "timed_out", "status": ex["status"], "fault_class": "ASYNC_DEADLINE_EXCEEDED"}
    return {"result": "noop"}


# ── kapı denetimi (W1–W12) ───────────────────────────────────────────────────────
def _check_gates(sample, run):
    lines = []
    ok = True
    if run["error_class"]:
        expect_err = sample.get("expect_error_class")
        if expect_err == run["error_class"]:
            lines.append("  ✓ beklenen hata: %s" % run["error_class"])
            return True, lines
        lines.append("  ✗ hata: %s (beklenen %s)" % (run["error_class"], expect_err))
        return False, lines

    eng = run["engine"]
    disp = run["dispatch"]
    exid = sample["dispatch_req"]["execution_id"]
    ex = eng.executions.get(exid)

    # W1: dispatch non-blocking
    if not (disp and disp.get("non_blocking") is True):
        ok = False
        lines.append("  ✗ W1 dispatch non-blocking değil")

    # W2: terminal-immutable durum + geçerli durum
    if ex and ex["status"] not in ALL_STATES:
        ok = False
        lines.append("  ✗ W2 geçersiz durum %r" % ex["status"])

    # W3: exactly-once — tool.async.completed en fazla 1 (terminal execution başına)
    emit_count = sum(1 for e in eng.emitted if e["execution_id"] == exid)
    if ex and ex["status"] in TERMINAL_STATES and emit_count > 1:
        ok = False
        lines.append("  ✗ W3 çift tool.async.completed (%d)" % emit_count)

    # W8: emitted envelope yalnız {execution_id,status,result_ref}+meta — yasak inline alan yok
    for e in eng.emitted:
        if e.get("type") != COMPLETED_EVENT_TYPE:
            continue
        for fk in FORBIDDEN_INLINE:
            if fk in e:
                ok = False
                lines.append("  ✗ W8 emitted'da yasak inline alan: %s" % fk)
        if not COMPLETED_FIELDS.issubset(set(e.keys())):
            ok = False
            lines.append("  ✗ W8 emitted eksik zorunlu alan")

    # W10: fault_class hizalama (varsa)
    if ex and ex.get("fault_class") is not None:
        fc = ex["fault_class"]
        if fc not in (RETRYABLE_FAULTS | TERMINAL_FAULTS | ASYNC_GATE_FAULTS):
            ok = False
            lines.append("  ✗ W10 hizasız fault_class %r" % fc)

    # sample-bazlı beklentiler
    exp = sample.get("expect", {})
    final_checks = {
        "final_status": (ex["status"] if ex else None),
        "dispatch_status": (disp.get("status") if disp else None),
        "non_blocking": (disp.get("non_blocking") if disp else None),
        "emitted_count": emit_count,
        "deduped": (disp.get("deduped") if disp else None),
        "fault_class": (ex.get("fault_class") if ex else None),
        "result_ref": (ex.get("result_ref") if ex else None),
        "attempts": (ex.get("attempts") if ex else None),
    }
    for k, want in exp.items():
        got = final_checks.get(k, "<?>")
        if got != want:
            ok = False
            lines.append("  ✗ %s = %r (beklenen %r)" % (k, got, want))
        else:
            lines.append("  ✓ %s = %r" % (k, want))

    # event-bazlı reject beklentileri
    for want in sample.get("expect_events", []):
        idx = want.get("index")
        if idx is None or idx >= len(run["events"]):
            ok = False
            lines.append("  ✗ event index %r yok" % idx)
            continue
        got = run["events"][idx]["result"]
        for kk, vv in want.get("result", {}).items():
            if got.get(kk) != vv:
                ok = False
                lines.append("  ✗ event[%d].%s = %r (beklenen %r)" % (idx, kk, got.get(kk), vv))
            else:
                lines.append("  ✓ event[%d].%s = %r" % (idx, kk, vv))

    # W11/W8: audit no-log — secret/PII/raw payload yok
    blob = json.dumps(eng.audit, ensure_ascii=False) + json.dumps(eng.emitted, ensure_ascii=False)
    leaks = []
    if SECRET_KEY_RE.search(blob):
        leaks.append("secret")
    if CREDIT_CARD_RE.search(blob):
        leaks.append("kart")
    for em in EMAIL_RE.findall(blob):
        if not em.endswith("example.com"):
            leaks.append("email:%s" % em)
    if '"raw_result"' in blob or '"raw_result_ref"' in blob:
        leaks.append("raw_result")
    # yasak sızıntı belirteci (degraded fixture'lar bunu sokar)
    for marker in sample.get("leak_markers", []):
        if marker in blob:
            leaks.append("marker:%s" % marker)
    if leaks:
        ok = False
        lines.append("  ✗ W11/W8 audit no-log ihlali: %s" % ", ".join(sorted(set(leaks))))
    if not all(a.get("no_log") for a in eng.audit):
        ok = False
        lines.append("  ✗ W11 audit no_log işareti eksik")

    return ok, lines


def run_cmd(path):
    sample = _load(path)
    run = _run_sample(sample)
    name = sample.get("name", os.path.basename(path))
    print("== run: %s ==" % name)
    if run["dispatch"]:
        d = run["dispatch"]
        print("  dispatch → status=%s non_blocking=%s accepted=%s deduped=%s" % (
            d.get("status"), d.get("non_blocking"), d.get("accepted"), d.get("deduped")))
    for e in run["events"]:
        print("  event %-22s → %s" % (e["event"], json.dumps(e["result"], ensure_ascii=False)))
    if run["engine"]:
        ex = run["engine"].executions.get(sample["dispatch_req"]["execution_id"])
        if ex:
            print("  FINAL execution: status=%s attempts=%s fault=%s result_ref=%s emit=%d" % (
                ex["status"], ex["attempts"], ex.get("fault_class"), ex.get("result_ref"),
                sum(1 for x in run["engine"].emitted if x["execution_id"] == ex["execution_id"])))
    if run["error_class"]:
        print("  error_class: %s" % run["error_class"])
    ok, lines = _check_gates(sample, run)
    for ln in lines:
        print(ln)
    print("KAPI: %s" % ("🟢 GEÇTI" if ok else "🔴 ELENDI"))
    return 0 if ok else 1


# ── validate (statik kapı) ───────────────────────────────────────────────────────
def validate():
    fails = []

    def expect(c, m):
        if not c:
            fails.append(m)

    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)

    expect(spec.get("wbs") == "7.2.4", "spec.wbs 7.2.4")
    expect("FR-TOOL-011" in spec["trace"]["fr"], "trace FR-TOOL-011")
    expect("SR-TOOL-011" in spec["trace"]["srs"], "trace SR-TOOL-011")
    expect("FR-TOOL-009" in spec["trace"]["fr"], "trace FR-TOOL-009 (idempotency köprüsü)")
    expect([inv["id"] for inv in spec["invariants"]] == GATE_IDS, "invariants W1–W12 sırası")

    # durum makinesi spec↔kod
    es = spec["execution_states"]
    expect(set(es["states"]) == ALL_STATES, "execution_states spec↔kod")
    expect(set(es["terminal"]) == TERMINAL_STATES, "terminal states spec↔kod")
    # fault taksonomi hizalama (7.1.4)
    al = spec["fault_taxonomy_alignment"]
    expect(set(al["retryable"]) == RETRYABLE_FAULTS, "retryable taksonomi spec↔kod (7.1.4 hizalı)")
    expect(set(al["terminal"]) == TERMINAL_FAULTS, "terminal taksonomi spec↔kod (7.1.4 hizalı)")
    expect(set(al["async_gate_faults"]) == ASYNC_GATE_FAULTS, "async gate fault spec↔kod")
    expect(set(spec["error_taxonomy"]["classes"]) == ERROR_CLASSES, "error taksonomi spec↔kod")
    expect(set(spec["callback_security"]["reject_reasons"]) == REJECT_REASONS, "reject_reasons spec↔kod")
    # result-by-reference sözleşmesi
    rr = spec["result_reference"]
    expect(rr["completed_event_type"] == COMPLETED_EVENT_TYPE, "completed event tipi")
    expect(set(rr["completed_payload_fields"]) == COMPLETED_FIELDS, "completed payload alanları")

    # her profil geçerli engine spec'e dönüşür
    for pname, prof in cfg["profiles"].items():
        try:
            AsyncWorkflowEngine(_strip_meta(prof))
        except WorkflowError as e:
            fails.append("profil %s geçerli engine değil (%s)" % (pname, e.error_class))

    # sır/PII taraması (spec/config/samples) — placeholder hariç literal sır yok
    scan_paths = [SPEC_PATH, CONFIG_PATH] + [os.path.join(SAMPLES_DIR, f)
                                             for f in sorted(os.listdir(SAMPLES_DIR)) if f.endswith(".json")]
    for sp in scan_paths:
        with open(sp, "r", encoding="utf-8") as f:
            txt = f.read()
        # yorum-tarif satırlarını ele (eventstream deseni): "# ..." / "// ..."
        scan_txt = "\n".join(ln for ln in txt.splitlines()
                             if not ln.strip().startswith("#") and not ln.strip().startswith("//"))
        if SECRET_KEY_RE.search(scan_txt):
            fails.append("sır sızıntısı: %s" % os.path.basename(sp))
        if CREDIT_CARD_RE.search(scan_txt):
            fails.append("kart no: %s" % os.path.basename(sp))
        for em in EMAIL_RE.findall(scan_txt):
            if not em.endswith("example.com"):
                fails.append("e-posta PII: %s (%s)" % (os.path.basename(sp), em))

    # her sample kapısı geçer (degraded KASITLI eler)
    for f in sorted(os.listdir(SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        sample = _load(os.path.join(SAMPLES_DIR, f))
        run = _run_sample(sample)
        ok, _ = _check_gates(sample, run)
        if sample.get("expect_degraded"):
            expect(not ok, "degraded sample KIRMIZI olmalı: %s" % f)
        else:
            expect(ok, "sample kapısı: %s" % f)

    print("validate: %d kontrol başarısız" % len(fails))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── selftest (gömülü davranış) ───────────────────────────────────────────────────
def _spec(mode="hybrid", **over):
    s = {
        "workflow_id": "test-async", "mode": mode,
        "callback": {"signing_ref": "${TEST_SIGNING_KEY}", "header": "X-Signature", "ts_tolerance_s": 300},
        "poll": {"max_attempts": 4, "base_backoff_ms": 1000, "max_backoff_ms": 8000, "jitter_ms": 0},
    }
    s.update(over)
    if mode == "polling":
        s.pop("callback", None)
    return s


def _disp_req(**over):
    r = {"execution_id": "ex-1", "tenant_id": "t-1", "correlation_id": "corr-1",
         "operation": "erp_job", "endpoint": "POST https://erp.example.com/jobs",
         "deadline_ms": 60000, "at_ms": 0, "dispatch": {"result": "ok", "status_code": 202}}
    r.update(over)
    return r


def _cb(eng, **over):
    """Geçerli imzalı callback üret (selftest yardımcı)."""
    cb = {"execution_id": "ex-1", "tenant_id": "t-1", "correlation_id": "corr-1",
          "status": "SUCCEEDED", "result_ref": "objref://t-1/ex-1/result",
          "body": '{"execution_id":"ex-1","status":"SUCCEEDED"}', "ts": 0, "nonce": "n1"}
    cb.update(over)
    cb["sig"] = compute_signature(eng.signing_secret, cb["ts"], cb["body"])
    return cb


def selftest():
    fails = []
    n = 0

    def expect(c, m):
        nonlocal n
        n += 1
        if not c:
            fails.append(m)

    # W1: dispatch non-blocking + PENDING + execution_id
    e = AsyncWorkflowEngine(_spec())
    d = e.dispatch(_disp_req())
    expect(d["non_blocking"] is True and d["status"] == "PENDING" and d["execution_id"] == "ex-1",
           "W1 dispatch non-blocking PENDING")

    # W4+W3: geçerli callback → SUCCEEDED + tam 1 emit
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req())
    r = e.ingest_callback(_cb(e, at_ms=1000, ts=1))
    expect(r["result"] == "accepted" and r["completed"] is True and e.executions["ex-1"]["status"] == "SUCCEEDED",
           "W4 geçerli callback → SUCCEEDED")
    expect(len([x for x in e.emitted if x["execution_id"] == "ex-1"]) == 1, "W3 tam 1 tool.async.completed")
    # W8: emitted yalnız result_ref, ham payload yok
    em = e.emitted[0]
    expect(em["result_ref"] == "objref://t-1/ex-1/result" and "result" not in em and "payload" not in em,
           "W8 emitted result-by-reference (ham payload yok)")

    # W3: çift callback (replay nonce) → ikinci no-op, emit hâlâ 1
    r2 = e.ingest_callback(_cb(e, at_ms=1100, ts=1, nonce="n1"))
    expect(r2["result"] == "rejected" and r2["reject_reason"] == "NONCE_REPLAYED", "W4 nonce replay reddi")
    expect(len([x for x in e.emitted if x["execution_id"] == "ex-1"]) == 1, "W3 replay sonrası emit hâlâ 1")

    # W4: kötü imza → reddedilir, execution PENDING kalır
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req())
    cb = _cb(e, at_ms=1000, ts=1)
    cb["sig"] = cb["sig"][:-1] + ("0" if cb["sig"][-1] != "0" else "1")
    r = e.ingest_callback(cb)
    expect(r["result"] == "rejected" and r["reject_reason"] == "BAD_SIGNATURE"
           and e.executions["ex-1"]["status"] == "PENDING", "W4 kötü imza reddi, PENDING korunur")
    expect(r["fault_class"] == "CALLBACK_REJECTED", "W4/W10 CALLBACK_REJECTED")

    # W4: timestamp penceresi dışı → reddedilir
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req())
    # now=400000ms→400s, ts=0 → |400-0|=400 > 300
    r = e.ingest_callback(_cb(e, at_ms=400000, ts=0, nonce="nX"))
    expect(r["reject_reason"] == "TIMESTAMP_OUT_OF_WINDOW", "W4 timestamp penceresi dışı reddi")

    # W7: tenant binding — başka tenant callback → reddedilir
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req())
    r = e.ingest_callback(_cb(e, at_ms=1000, ts=1, tenant_id="t-OTHER", nonce="n2"))
    expect(r["reject_reason"] == "TENANT_MISMATCH", "W7 cross-tenant callback reddi")
    # correlation binding
    r = e.ingest_callback(_cb(e, at_ms=1000, ts=1, correlation_id="corr-OTHER", nonce="n3"))
    expect(r["reject_reason"] == "CORRELATION_MISMATCH", "W7 correlation mismatch reddi")

    # W7: bilinmeyen execution → reddedilir
    r = e.ingest_callback(_cb(e, at_ms=1000, ts=1, execution_id="ex-NOPE", nonce="n4"))
    expect(r["reject_reason"] == "UNKNOWN_EXECUTION", "W7 bilinmeyen execution reddi")

    # W5: bounded polling — upstream hep RUNNING → max_attempts'te TIMED_OUT
    # (deadline çok büyük → W6 reaper KARIŞMAZ; saf attempt-tükenmesi yolu sınanır)
    e = AsyncWorkflowEngine(_spec(mode="polling"))
    e.dispatch(_disp_req(deadline_ms=10_000_000))
    last = None
    t = 0
    for i in range(10):
        t += 20000  # her tetik arası uzun → backoff her zaman geçilir
        last = e.poll_step(t, {"status": "RUNNING"})
        if e.executions["ex-1"]["status"] in TERMINAL_STATES:
            break
    expect(e.executions["ex-1"]["status"] == "TIMED_OUT" and e.executions["ex-1"]["attempts"] == 4,
           "W5 bounded poll → 4 attempt sonra TIMED_OUT")
    expect(e.executions["ex-1"]["fault_class"] == "ASYNC_DEADLINE_EXCEEDED", "W5/W10 ASYNC_DEADLINE_EXCEEDED")

    # W5: polling success — upstream terminal → SUCCEEDED
    e = AsyncWorkflowEngine(_spec(mode="polling"))
    e.dispatch(_disp_req())
    e.poll_step(1100, {"status": "RUNNING"})
    r = e.poll_step(5000, {"status": "SUCCEEDED", "result_ref": "objref://t-1/ex-1/r"})
    expect(r["result"] == "terminal" and e.executions["ex-1"]["status"] == "SUCCEEDED", "W5 poll success → SUCCEEDED")

    # W6: deadline reaper — poll hiç terminal vermese de deadline aşımında TIMED_OUT
    e = AsyncWorkflowEngine(_spec(mode="polling", poll={"max_attempts": 100, "base_backoff_ms": 1000,
                                                        "max_backoff_ms": 2000, "jitter_ms": 0}))
    e.dispatch(_disp_req(deadline_ms=5000))
    r = e.poll_step(6000, {"status": "RUNNING"})
    expect(r["result"] == "timed_out" and e.executions["ex-1"]["status"] == "TIMED_OUT", "W6 deadline reaper → TIMED_OUT")

    # W3 race: poll terminal SONRA callback → callback idempotent no-op, emit 1
    e = AsyncWorkflowEngine(_spec(mode="hybrid"))
    e.dispatch(_disp_req())
    e.poll_step(1100, {"status": "SUCCEEDED", "result_ref": "objref://t-1/ex-1/poll"})
    expect(e.executions["ex-1"]["status"] == "SUCCEEDED", "W3 poll terminal önce")
    r = e.ingest_callback(_cb(e, at_ms=1200, ts=1, nonce="nr"))
    expect(r["completed"] is False, "W3 poll-sonrası callback idempotent no-op")
    expect(len([x for x in e.emitted if x["execution_id"] == "ex-1"]) == 1, "W3 race → tam 1 emit")

    # W9: idempotency-key dedup — aynı key iki dispatch → tek execution
    e = AsyncWorkflowEngine(_spec())
    d1 = e.dispatch(_disp_req(execution_id="ex-A", idempotency_key="idem-1"))
    d2 = e.dispatch(_disp_req(execution_id="ex-B", idempotency_key="idem-1", at_ms=10))
    expect(d2["deduped"] is True and d2["execution_id"] == "ex-A" and len(e.executions) == 1,
           "W9 idempotency dedup → tek execution")

    # W2: terminal dispatch fault (4xx) → FAILED, async başlamaz, emit 1
    e = AsyncWorkflowEngine(_spec())
    d = e.dispatch(_disp_req(dispatch={"result": "fault", "fault_class": "AUTH_FAILED"}))
    expect(d["status"] == "FAILED" and d["accepted"] is False, "W2 terminal dispatch fault → FAILED")
    expect(e.executions["ex-1"]["fault_class"] == "AUTH_FAILED", "W10 dispatch fault_class korunur")

    # W12: determinizm — aynı seed+girdi iki kez aynı trace
    def trace():
        eng = AsyncWorkflowEngine(_spec(mode="polling", poll={"max_attempts": 5, "base_backoff_ms": 1000,
                                                              "max_backoff_ms": 8000, "jitter_ms": 50}))
        eng.dispatch(_disp_req())
        out = []
        t2 = 0
        for _ in range(5):
            t2 += 20000
            out.append(eng.poll_step(t2, {"status": "RUNNING"}))
        return out
    expect(trace() == trace(), "W12 determinizm birebir (tohumlu jitter)")

    # W2: terminal-immutable — terminal sonrası complete no-op
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req())
    e.ingest_callback(_cb(e, at_ms=1000, ts=1, nonce="z1"))
    before = e.executions["ex-1"]["status"]
    applied = e._complete(e.executions["ex-1"], "FAILED", None, source="x")
    expect(applied is False and e.executions["ex-1"]["status"] == before, "W2 terminal-immutable")

    # spec doğrulama: callback modunda signing_ref yok → MISSING_SIGNING_CONFIG
    try:
        AsyncWorkflowEngine({"workflow_id": "x", "mode": "callback"})
        expect(False, "MISSING_SIGNING_CONFIG bekleniyor")
    except WorkflowError as ex:
        expect(ex.error_class == "MISSING_SIGNING_CONFIG", "MISSING_SIGNING_CONFIG")
    # literal sır → reddedilir
    try:
        AsyncWorkflowEngine({"workflow_id": "x", "mode": "callback",
                             "callback": {"signing_ref": "whsec-ABCD1234ABCD1234ABCD"}})
        expect(False, "LITERAL_SECRET_IN_SPEC bekleniyor")
    except WorkflowError as ex:
        expect(ex.error_class == "LITERAL_SECRET_IN_SPEC", "LITERAL_SECRET_IN_SPEC")
    # unbounded poll reddi (W5)
    try:
        AsyncWorkflowEngine({"workflow_id": "x", "mode": "polling", "poll": {"max_attempts": 0}})
        expect(False, "INVALID_WORKFLOW_SPEC (unbounded poll) bekleniyor")
    except WorkflowError as ex:
        expect(ex.error_class == "INVALID_WORKFLOW_SPEC", "W5 unbounded poll reddi")

    # NON_MONOTONIC_CLOCK
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req(at_ms=100))
    try:
        e.ingest_callback(_cb(e, at_ms=50, ts=0, nonce="nm"))
        expect(False, "NON_MONOTONIC_CLOCK bekleniyor")
    except WorkflowError as ex:
        expect(ex.error_class == "NON_MONOTONIC_CLOCK", "NON_MONOTONIC_CLOCK")

    # W11: audit no-log — execution_id+status var, ham payload/secret yok
    e = AsyncWorkflowEngine(_spec())
    e.dispatch(_disp_req())
    e.ingest_callback(_cb(e, at_ms=1000, ts=1, nonce="na"))
    blob = json.dumps(e.audit)
    expect(all(a.get("no_log") for a in e.audit) and "result" not in json.loads(blob)[0], "W11 audit no_log")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


def schema_cmd():
    spec = _load(SPEC_PATH)
    print(json.dumps({
        "wbs": spec["wbs"],
        "states": spec["execution_states"]["states"],
        "terminal": spec["execution_states"]["terminal"],
        "modes": spec["reconciliation"]["modes"],
        "callback_verification_order": spec["reconciliation"]["callback_verification_order"],
        "callback_security": {"algo": spec["callback_security"]["algo"],
                              "reject_reasons": spec["callback_security"]["reject_reasons"]},
        "completed_event": {"type": spec["result_reference"]["completed_event_type"],
                            "fields": spec["result_reference"]["completed_payload_fields"]},
        "async_gate_faults": spec["fault_taxonomy_alignment"]["async_gate_faults"],
        "invariants": [i["id"] for i in spec["invariants"]],
        "error_classes": sorted(ERROR_CLASSES),
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "run":
        if len(argv) < 3:
            print("kullanım: async_workflow_probe.py run <sample.json>")
            return 2
        return run_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
