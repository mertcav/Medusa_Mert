#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.3.1 — Kritik işlem workflow durum makinesi (BRD §13) referans probe.

7.3 'Deterministic workflow engine' workstream'inin İLK modülü. BRD §13 kritik işlemler için
6 ZORUNLU adımı bir DETERMINISTIK DURUM MAKİNESİ olarak gerçekler:

  INIT ─► AUTH(1) ─► RULE(2) ─► SUMMARY(3) ─► CONFIRM(4) ─► APPROVAL(5) ─► EXECUTE ─► AUDIT(6)
            │           │                        │              │             │
            ▼           ▼                        ▼              ▼             ▼
          DENIED      DENIED                  ABORTED         DENIED        FAILED  ──► AUDIT ─► terminal
         (auth)    (kural/risk)            (teyit yok)    (onay/maker)   (dispatch)

7.2.5 (reference-integration) tek-atımlık 'policy_gate' (confirmation∧step_up boolean) YERİNE bu
modül kritik-işlem akışının TAM çok-adımlı stateful FSM'ini SAHİPLENİR (7.2.5 'kritik-işlem TAM
durum makinesi→7.3.1/7.3.2' diye erteledi). FSM EXECUTE'a ulaşınca gerçek tool eylemini 7.2.x'e
DELEGE eder; bu modül o zincirin tükettiği teyit/step-up/onay KARARLARINI üretir.

ÇEKİRDEK INVARIANT (BRD §13 + SR-TOOL-006/007): her gerekli kapı geçilmeden EXECUTE'a ULAŞILAMAZ
(K1 fail-closed); teyit alınmadan kritik işlem yürütülmez (K5); para/sözleşme/PII → step-up zorunlu
(K7); gerekli insan onayı maker-checker (talep≠onay) gelmeden yürütülmez (K6); her terminal sonuç
değiştirilemez audit'e yazılır (K10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): auth MEKANİZMASI→8.x (seviyeyi TÜKETİR); teyit/ek-doğrulama
AYRINTISI→7.3.2; tool dispatch/transport→7.2.x; idempotency/allowlist/schema→7.1.x/7.2.3; müşteri hata
METNİ→7.1.5; audit STORE→7.1.6/12.1.8; maker-checker UI→12.1.7; output guard→3.3.x.

Kullanım:
  critical_workflow_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  critical_workflow_probe.py run <sample>      FSM-yürütücü: workflow(lar)ı çalıştır → kapı (K1–K12)
  critical_workflow_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  critical_workflow_probe.py schema            Durum/olay/sonuç sözleşmesini yazdır

Determinizm: sanal saat (at_ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "critical-workflow-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "workflow-policies.json")

STEP_STATES = ["AUTH", "RULE", "SUMMARY", "CONFIRM", "APPROVAL", "EXECUTE", "AUDIT"]
TERMINAL = {"COMMITTED", "FAILED", "DENIED", "ABORTED", "EXPIRED", "ERROR"}
WAITING = {"AUTH", "CONFIRM", "APPROVAL"}
AUTH_RANK = {"none": 0, "basic": 1, "strong": 2}
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
ERROR_CLASSES = {"MISSING_POLICY_CONFIG", "INVALID_POLICY", "INVALID_REQUEST",
                 "NOT_CRITICAL", "NON_MONOTONIC_CLOCK", "INTERNAL_ERROR"}
DENY_REASONS = {"AUTH_INSUFFICIENT", "STEP_UP_REQUIRED", "UNKNOWN_RISK_CLASS", "RULE_BLOCKED",
                "APPROVAL_REQUIRED", "APPROVAL_REJECTED", "MAKER_CHECKER_VIOLATION"}
ABORT_REASONS = {"CUSTOMER_DECLINED", "CONFIRMATION_NOT_OBTAINED"}

# ── Sızıntı tarayıcı (K10/K11; 7.1.5/7.2.5 deseniyle) — müşteri özeti / audit'te ham hassas yasak ─
LEAK_PATTERNS = [
    ("ip", re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")),
    ("url", re.compile(r"https?://|\.example\.com|/graphql|/soap/")),
    ("path", re.compile(r"/(?:var|usr|etc|opt|home)/|[a-z0-9_]+\.(?:py|java|go|rb|js|sql)\b")),
    ("stack", re.compile(r"(?i)\b(exception|traceback|stacktrace|nullpointer|segfault|panic)\b")),
    ("vendor", re.compile(r"(?i)\b(salesforce|zendesk|servicenow|sap\s|hubspot|jira|nginx|apache)\b")),
]
PII_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # IBAN (2 harf + 2 hane + ≥10 alnum) ve ≥10 haneli ham dizi (kart 16 / telefon 10+ / hesap / kimlik).
    # Eşik 10: meşru tutar (≤9 hane) müşteri özetinde maskesiz GÖSTERİLEBİLİR, kimlik dizisi GÖSTERİLEMEZ.
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,}\b")),
    ("long_digits", re.compile(r"\d{10,}")),
    ("secret", re.compile(r"(?i)\b(bearer\s+\S+|password|client[_-]?secret|api[_-]?key\s*[:=])")),
]


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _no_meta(d):
    """Meta anahtarlarını ($comment/trace) iterasyondan ele (eventstream/7.2.5 deseni)."""
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if not k.startswith("$") and k != "trace"}
    return d


def _scan(text, patterns):
    hits = []
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    for name, rx in patterns:
        if rx.search(text):
            hits.append(name)
    return hits


def _mask_last_n(val, n=4):
    """Hassas değeri son n hane hariç maskeler (K11 / FR-AUTH-005)."""
    s = str(val)
    digits = re.sub(r"\D", "", s)
    if len(digits) <= n:
        return "*" * len(digits)
    return "*" * (len(digits) - n) + digits[-n:]


class WorkflowError(Exception):
    def __init__(self, error_class, msg=""):
        super().__init__("%s: %s" % (error_class, msg))
        self.error_class = error_class


# ════════════════════════════════════════════════════════════════════════════
#  FSM — kritik işlem durum makinesi (BRD §13: auth→kural→özet→teyit→onay→audit)
# ════════════════════════════════════════════════════════════════════════════
def run_workflow(spec, policies, req):
    """Bir kritik-işlem isteğini FSM boyunca yürütür → WorkflowResult.

    req alanları: workflow_id, correlation_id, tenant_id, call_id, initiator (talep eden aktör),
      operation{name, risk_class, critical(bool, default True), params{amount?, currency?, masked{}}},
      events[] (auth/confirm/approval/execute; her biri at_ms ile), deadline_ms?,
      unsafe_summary(degraded), unsafe_audit_detail(degraded).
    """
    rc_table = _no_meta(policies["risk_classes"])
    defaults = _no_meta(policies.get("defaults", {}))

    for f in ("workflow_id", "correlation_id", "tenant_id", "initiator"):
        if not req.get(f):
            raise WorkflowError("INVALID_REQUEST", "eksik %s" % f)
    op = req.get("operation") or {}
    if op.get("critical") is False:
        raise WorkflowError("NOT_CRITICAL", "bu motor yalnız kritik işlemler içindir")
    risk_class = op.get("risk_class")
    if not risk_class:
        raise WorkflowError("INVALID_REQUEST", "operation.risk_class eksik")

    events = list(req.get("events", []))
    # monoton sanal saat doğrulaması (K12)
    last = -1
    for ev in events:
        a = ev.get("at_ms", 0)
        if a < last:
            raise WorkflowError("NON_MONOTONIC_CLOCK", "at_ms %s < %s" % (a, last))
        last = a
    start_ms = events[0].get("at_ms", 0) if events else 0
    deadline_ms = req.get("deadline_ms", defaults.get("deadline_ms", 120000))

    verdicts = []                    # [(state, verdict)] düşük kardinalite (K10)
    state = "AUTH"
    final = None                     # terminal sonuç
    reason = None
    approver = None
    result_ref = None
    summary_text = None
    summary_emitted = False
    requirements = None
    ev_idx = 0

    def mark(s, ok):
        verdicts.append((s, "pass" if ok else "fail"))

    def expired_if_late(at_ms):
        """K9 — bekleyen durumda deadline aşıldı mı?"""
        return (at_ms - start_ms) > deadline_ms

    def next_event(kind):
        nonlocal ev_idx
        while ev_idx < len(events):
            ev = events[ev_idx]
            ev_idx += 1
            return ev
        return None

    # ── [1] AUTH (K2) ────────────────────────────────────────────────────────
    # risk-class tabanı (RULE'da etkin set kesinleşir; auth tabanı statik floor)
    rc = rc_table.get(risk_class)
    min_auth = (rc or {}).get("min_auth_level", defaults.get("min_auth_level", "strong"))
    base_step_up = (rc or {}).get("requires_step_up", defaults.get("requires_step_up", True))
    ev = next_event("auth")
    if ev is None or ev.get("type") != "auth":
        mark("AUTH", False)
        state, final, reason = "DENIED", "DENIED", "AUTH_INSUFFICIENT"
    elif expired_if_late(ev.get("at_ms", 0)):
        mark("AUTH", False)
        state, final, reason = "EXPIRED", "EXPIRED", None
    else:
        level = ev.get("level", "none")
        methods = ev.get("methods", [])
        # FR-AUTH-001: caller_id TEK BAŞINA güçlü değil → basic'e sabitle
        if methods == ["caller_id"] and AUTH_RANK.get(level, 0) > AUTH_RANK["basic"]:
            level = "basic"
        step_up_ok = bool(ev.get("step_up"))
        auth_ok = AUTH_RANK.get(level, 0) >= AUTH_RANK.get(min_auth, 2)
        if not auth_ok:
            mark("AUTH", False)
            state, final, reason = "DENIED", "DENIED", "AUTH_INSUFFICIENT"
        elif base_step_up and not step_up_ok:
            # K7 — para/sözleşme/PII ek doğrulama (step-up) zorunlu (FR-TOOL-007/FR-AUTH-003)
            mark("AUTH", False)
            state, final, reason = "DENIED", "DENIED", "STEP_UP_REQUIRED"
        else:
            mark("AUTH", True)
            state = "RULE"
            _auth_level, _step_up = level, step_up_ok

    # ── [2] RULE (K3) — kural tablosundan etkin gereksinim seti ───────────────
    if state == "RULE":
        if rc is None:
            mark("RULE", False)
            state, final, reason = "DENIED", "DENIED", "UNKNOWN_RISK_CLASS"
        elif rc.get("disallowed"):
            mark("RULE", False)
            state, final, reason = "DENIED", "DENIED", "RULE_BLOCKED"
        else:
            requirements = {
                "min_auth_level": rc.get("min_auth_level", "strong"),
                "requires_step_up": bool(rc.get("requires_step_up", True)),
                "requires_confirmation": bool(rc.get("requires_confirmation", True)),
                "requires_human_approval": bool(rc.get("requires_human_approval", False)),
            }
            # dinamik eskalasyon (a) forbidden_autonomous → insan onayı zorlanır (BRD §13)
            if rc.get("forbidden_autonomous"):
                requirements["requires_human_approval"] = True
            # (b) tutar eşiği üstü → insan onayı (yüksek tutarlı ödeme / limit üstü)
            thr = rc.get("amount_threshold")
            params = op.get("params", {})
            amount = params.get("amount")
            if thr and rc.get("escalate_human_above_threshold") and isinstance(amount, (int, float)):
                if amount > thr.get("value", float("inf")):
                    requirements["requires_human_approval"] = True
            mark("RULE", True)
            state = "SUMMARY"

    # ── [3] SUMMARY (K11) — müşteriye maskeli özet ────────────────────────────
    if state == "SUMMARY":
        params = op.get("params", {})
        masked = []
        for k, v in (params.get("masked") or {}).items():
            masked.append("%s ...%s" % (k, _mask_last_n(v, spec["summary_masking"]["mask_last_n"])))
        amt = ""
        if isinstance(params.get("amount"), (int, float)):
            amt = " tutar %s %s" % (params["amount"], params.get("currency", ""))
        summary_text = req.get("unsafe_summary") or (
            "İşlem: %s.%s%s Onaylıyor musunuz?"
            % (op.get("name", risk_class), amt, (" " + ", ".join(masked)) if masked else ""))
        summary_emitted = True
        mark("SUMMARY", True)
        # K4 — özet emit edildi; teyit kapısı ön-koşulu sağlandı
        state = "CONFIRM" if requirements["requires_confirmation"] else (
            "APPROVAL" if requirements["requires_human_approval"] else "EXECUTE")

    # ── [4] CONFIRM (K4/K5) — açık olumlu teyit ───────────────────────────────
    if state == "CONFIRM":
        if not summary_emitted:                       # K4 koruması (yapısal olarak doğru)
            state, final, reason = "ERROR", "ERROR", None
        else:
            ev = next_event("confirm")
            if ev is None or ev.get("type") != "confirm":
                mark("CONFIRM", False)
                state, final, reason = "ABORTED", "ABORTED", "CONFIRMATION_NOT_OBTAINED"
            elif expired_if_late(ev.get("at_ms", 0)):
                mark("CONFIRM", False)
                state, final, reason = "EXPIRED", "EXPIRED", None
            else:
                val = ev.get("value")
                if val == "yes":
                    mark("CONFIRM", True)
                    state = "APPROVAL" if requirements["requires_human_approval"] else "EXECUTE"
                elif val == "no":
                    mark("CONFIRM", False)
                    state, final, reason = "ABORTED", "ABORTED", "CUSTOMER_DECLINED"
                else:
                    mark("CONFIRM", False)
                    state, final, reason = "ABORTED", "ABORTED", "CONFIRMATION_NOT_OBTAINED"

    # ── [5] APPROVAL (K6) — gerekirse insan onayı (maker-checker) ──────────────
    if state == "APPROVAL":
        ev = next_event("approval")
        if ev is None or ev.get("type") != "approval":
            mark("APPROVAL", False)
            state, final, reason = "DENIED", "DENIED", "APPROVAL_REQUIRED"
        elif expired_if_late(ev.get("at_ms", 0)):
            mark("APPROVAL", False)
            state, final, reason = "EXPIRED", "EXPIRED", None
        else:
            decision = ev.get("decision")
            actor = ev.get("actor")
            if decision != "approved":
                mark("APPROVAL", False)
                state, final, reason = "DENIED", "DENIED", "APPROVAL_REJECTED"
            elif not actor or actor == req["initiator"]:
                # FR-IAM-005: talep eden ≠ onaylayan
                mark("APPROVAL", False)
                state, final, reason = "DENIED", "DENIED", "MAKER_CHECKER_VIOLATION"
            else:
                approver = actor
                mark("APPROVAL", True)
                state = "EXECUTE"

    # ── EXECUTE — gerçek eylem 7.2.x'e delege (K1 tüm kapılar geçti) ───────────
    if state == "EXECUTE":
        ev = next_event("execute")
        if ev is None or ev.get("type") != "execute":
            # gerekli kapılar geçti ama eylem sonucu yok → fail-closed ERROR (yürütülmedi)
            mark("EXECUTE", False)
            state, final, reason = "ERROR", "ERROR", "EXECUTE_OUTCOME_MISSING"
        else:
            outcome = ev.get("outcome")
            if outcome == "ok":
                mark("EXECUTE", True)
                result_ref = ev.get("result_ref")
                state, final = "AUDIT", "COMMITTED"
            else:
                mark("EXECUTE", False)
                reason = ev.get("fault_class") or "INTERNAL_ERROR"
                state, final = "AUDIT", "FAILED"

    # ── [6] AUDIT (K10) — her terminal sonuç değiştirilemez audit'e yazılır ────
    # final henüz set değilse (yalnızca AUDIT'e normal akışla geldik): COMMITTED/FAILED yukarıda set.
    if final is None:
        final = "ERROR"
        reason = reason or "INTERNAL_ERROR"
    mark("AUDIT", True)

    audit = {
        "workflow_id": req["workflow_id"],
        "correlation_id": req["correlation_id"],
        "tenant_id": req["tenant_id"],
        "operation": op.get("name", risk_class),
        "risk_class": risk_class,
        "requirements": requirements,
        "step_verdicts": verdicts,
        "final_state": final,
        "reason": reason,
        "approver": approver,
        "result_ref": result_ref,
        "no_log": True,
    }
    if req.get("unsafe_audit_detail"):              # degraded: ham PII/secret audit'e sızar (K10 yakalar)
        audit["_unsafe"] = req["unsafe_audit_detail"]

    # K8 — terminal-immutable: kalan olaylar yok sayılır (FSM bir daha geçiş yapmaz)
    return {
        "workflow_id": req["workflow_id"],
        "operation": op.get("name", risk_class),
        "risk_class": risk_class,
        "requirements": requirements,
        "final_state": final,
        "reason": reason,
        "approver": approver,
        "result_ref": result_ref,
        "summary_text": summary_text,
        "summary_emitted": summary_emitted,
        "step_verdicts": verdicts,
        "audit": audit,
    }


# ════════════════════════════════════════════════════════════════════════════
#  run <sample> — FSM + kapı (K1–K12)
# ════════════════════════════════════════════════════════════════════════════
def _check_result_gates(res):
    fails = []
    sv = dict(res["step_verdicts"])
    fstate = res["final_state"]
    reqs = res["requirements"] or {}

    # K1 — EXECUTE/COMMITTED yalnız önceki gerekli kapılar 'pass' ise
    reached_execute = "EXECUTE" in sv
    if fstate == "COMMITTED":
        if sv.get("EXECUTE") != "pass":
            fails.append("K1 COMMITTED ama EXECUTE pass değil")
        for s in ("AUTH", "RULE", "SUMMARY"):
            if sv.get(s) != "pass":
                fails.append("K1 COMMITTED ama %s geçilmemiş" % s)
        if reqs.get("requires_confirmation") and sv.get("CONFIRM") != "pass":
            fails.append("K5 COMMITTED ama teyit (CONFIRM) geçilmemiş")
        if reqs.get("requires_human_approval") and sv.get("APPROVAL") != "pass":
            fails.append("K6 COMMITTED ama insan onayı (APPROVAL) geçilmemiş")
    # K1/K5 — teyitsiz/red durumda EXECUTE çalışmamalı (kısa devre)
    if fstate in ("DENIED", "ABORTED", "EXPIRED") and reached_execute:
        fails.append("K1 terminal-red sonrası EXECUTE çalıştı (kısa-devre ihlali)")
    # K8 — terminal sonra AUDIT hep var
    if sv.get("AUDIT") != "pass":
        fails.append("K10 terminalde audit yazılmadı")
    # K9 — EXPIRED EXECUTE'a dönmemeli
    if fstate == "EXPIRED" and sv.get("EXECUTE") == "pass":
        fails.append("K9 EXPIRED ama EXECUTE geçti")
    # K11 — müşteri özetinde ham hassas sızıntı yok
    if res.get("summary_text"):
        hits = _scan(res["summary_text"], LEAK_PATTERNS) + _scan(res["summary_text"], PII_PATTERNS)
        if hits:
            fails.append("K11 özet sızıntısı: %s" % ",".join(hits))
    # K10 — audit no-log: ham PII/secret yok
    a_hits = _scan(json.dumps(res["audit"], ensure_ascii=False), PII_PATTERNS)
    if a_hits:
        fails.append("K10 audit no-log sızıntı: %s" % ",".join(a_hits))
    # tutarlılık: reason terminal sınıfıyla uyumlu
    if fstate == "DENIED" and res["reason"] not in DENY_REASONS:
        fails.append("DENIED reason taksonomisi dışı: %s" % res["reason"])
    if fstate == "ABORTED" and res["reason"] not in ABORT_REASONS:
        fails.append("ABORTED reason taksonomisi dışı: %s" % res["reason"])
    return fails


def run_cmd(path):
    spec = _load(SPEC_PATH)
    policies = _load(CONFIG_PATH)
    sample = _load(path)
    name = sample.get("name", os.path.basename(path))
    cases = sample.get("workflows", [])
    expect = sample.get("expect", {})
    expect_fail = bool(sample.get("expect_gate_fail"))
    print("▶ %s" % name)
    if sample.get("$comment"):
        print("  %s" % sample["$comment"])

    all_fails = []
    results = {}
    for req in cases:
        wid = req.get("workflow_id")
        try:
            res = run_workflow(spec, policies, req)
        except WorkflowError as e:
            # bazı sample'lar bilinçli hata bekler (expect[wid].error)
            exp = expect.get(wid, {})
            if exp.get("error") == e.error_class:
                print("  ✓ %s → beklenen WorkflowError %s" % (wid, e.error_class))
            else:
                print("  ✗ %s → WorkflowError %s" % (wid, e.error_class))
                all_fails.append("%s WorkflowError %s" % (wid, e.error_class))
            continue
        results[wid] = res
        gate_fails = _check_result_gates(res)
        all_fails += ["%s: %s" % (wid, f) for f in gate_fails]
        mark = "✓" if not gate_fails else "✗"
        print("  %s %s [%s] → %s reason=%s%s%s"
              % (mark, wid, res["risk_class"], res["final_state"], res["reason"],
                 (" approver=" + res["approver"]) if res["approver"] else "",
                 (" GATE:" + ";".join(gate_fails)) if gate_fails else ""))
        exp = expect.get(wid)
        if exp:
            for k, v in exp.items():
                if k == "error":
                    continue
                got = res.get(k)
                if got != v:
                    all_fails.append("%s beklenen %s=%r ama %r" % (wid, k, v, got))
                    print("      ✗ beklenen %s=%r ama %r" % (k, v, got))

    # determinizm (K12): ikinci kez çalıştır, birebir aynı
    for req in cases:
        try:
            r2 = run_workflow(spec, policies, req)
        except WorkflowError:
            continue
        wid = r2["workflow_id"]
        if wid in results and json.dumps(r2, sort_keys=True, ensure_ascii=False) != json.dumps(results[wid], sort_keys=True, ensure_ascii=False):
            all_fails.append("K12 determinizm ihlali: %s" % wid)

    if expect_fail:
        if all_fails:
            print("  ✓ BEKLENEN ELEME (degraded): %d kapı tetiklendi → %s" % (len(all_fails), all_fails[0]))
            return 0
        print("  ✗ degraded sample geçmemeliydi ama tüm kapılar geçti")
        return 1
    if all_fails:
        print("  🔴 %d kapı eler" % len(all_fails))
        for f in all_fails:
            print("     - %s" % f)
        return 1
    print("  🟢 GEÇTİ (%d workflow)" % len(cases))
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  validate — statik spec/config/kapsama kapısı
# ════════════════════════════════════════════════════════════════════════════
def validate():
    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)
    checks = []

    def ck(cond, label):
        checks.append((bool(cond), label))

    ck(spec.get("wbs") == "7.3.1", "spec.wbs == 7.3.1")
    ck(spec.get("phase") == "F1", "spec.phase == F1")
    ck(spec.get("priority") == "Must", "spec.priority == Must")
    for fr in ("FR-TOOL-006", "FR-TOOL-007", "FR-IAM-005", "FR-IAM-006", "FR-AUTH-003"):
        ck(fr in spec["trace"]["fr"], "trace %s" % fr)
    for sr in ("SR-TOOL-006", "SR-TOOL-007"):
        ck(sr in spec["trace"]["srs"], "trace %s" % sr)
    ck(any("§13" in b for b in spec["trace"]["brd"]), "trace BRD §13")

    # durum makinesi bütünlüğü
    st = spec["states"]
    ck(st["step_states"] == STEP_STATES, "step_states BRD §13 sırasıyla auth→...→audit")
    ck(set(st["terminal"]) == TERMINAL, "terminal durum kümesi tam")
    ck(set(st["waiting_states"]) == WAITING, "waiting_states = AUTH/CONFIRM/APPROVAL")
    # her step_state brd13_step_map'te
    for s in STEP_STATES:
        ck(s in st["brd13_step_map"], "brd13_step_map kapsar %s" % s)
    # geçiş grafiği: terminal'ler çıkışsız (K8), AUDIT terminallere gider
    for t in TERMINAL:
        ck(st["transitions"].get(t) == [], "terminal %s çıkışsız (K8)" % t)
    ck(set(st["transitions"]["AUDIT"]) <= TERMINAL, "AUDIT yalnız terminallere geçer")
    ck("EXECUTE" not in st["transitions"]["AUTH"], "AUTH'tan EXECUTE'a DOĞRUDAN geçiş yok (K1)")

    # invariant + auth + deadline
    inv_ids = [i["id"] for i in spec["invariants"]]
    ck(inv_ids == INVARIANT_IDS, "invariants K1–K12 tam ve sıralı")
    ck(spec["auth_levels"]["rank"] == AUTH_RANK, "auth rank none<basic<strong")
    ck(spec["auth_levels"]["caller_id_only_cap"] == "basic", "caller_id-only cap basic (FR-AUTH-001)")
    ck(spec["audit"].get("no_log") is True, "audit no_log=true")
    ck(spec["audit"].get("immutable") is True, "audit immutable=true (K10/WORM)")
    ck(set(spec["outcomes"]["values"]) == TERMINAL, "outcomes = terminal kümesi")
    ck(set(spec["outcomes"]["deny_reasons"]) == DENY_REASONS, "deny_reasons tam")
    ck(set(spec["outcomes"]["abort_reasons"]) == ABORT_REASONS, "abort_reasons tam")

    # config kural tablosu — BRD §13 9 maddenin tümü kapsanır
    rc = _no_meta(cfg["risk_classes"])
    ck(len(rc) >= 9, "≥9 risk_class (BRD §13 listesi)")
    brd13_required = {
        "Banka hesabı", "Yüksek tutarlı ödeme", "Limit üstü", "iletişim",
        "Hassas kişisel veri", "Sözleşme iptali", "Kredi", "Sağlık", "Hukuki",
    }
    brd13_seen = " ".join(v.get("brd13", "") for v in rc.values())
    for needle in brd13_required:
        ck(needle in brd13_seen, "BRD §13 maddesi kapsanır: %s" % needle)
    # forbidden_autonomous → requires_human_approval true (yapısal tutarlılık)
    for name, r in rc.items():
        ck(r.get("min_auth_level") in AUTH_RANK, "%s min_auth_level geçerli" % name)
        ck(isinstance(r.get("requires_step_up"), bool), "%s requires_step_up bool" % name)
        if r.get("forbidden_autonomous"):
            ck(r.get("requires_human_approval") is True, "%s forbidden_autonomous→insan onayı" % name)
        thr = r.get("amount_threshold")
        if thr is not None:
            ck("value" in thr and "currency" in thr, "%s amount_threshold value+currency" % name)
    # ≥3 risk_class forbidden_autonomous (kredi/sağlık/hukuk)
    fa = sum(1 for r in rc.values() if r.get("forbidden_autonomous"))
    ck(fa >= 3, "≥3 forbidden_autonomous risk_class (kredi/sağlık/hukuk)")
    # ≥3 risk_class requires_human_approval
    ha = sum(1 for r in rc.values() if r.get("requires_human_approval"))
    ck(ha >= 3, "≥3 requires_human_approval risk_class")

    # literal sır taraması
    blob = json.dumps(spec, ensure_ascii=False) + json.dumps(cfg, ensure_ascii=False)
    stripped = re.sub(r"\$\{[A-Z0-9_]+\}", "", blob)
    secret_like = re.findall(r"(?i)(?:bearer\s+|sk-)[A-Za-z0-9/\+_\-]{20,}", stripped)
    ck(not secret_like, "literal sır yok (spec+config)")

    npass = sum(1 for ok, _ in checks if ok)
    ntot = len(checks)
    for ok, label in checks:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d %s" % (npass, ntot, "🟢" if npass == ntot else "🔴"))
    return 0 if npass == ntot else 1


# ════════════════════════════════════════════════════════════════════════════
#  selftest — gömülü davranış (K1–K12)
# ════════════════════════════════════════════════════════════════════════════
def _ctx():
    return _load(SPEC_PATH), _load(CONFIG_PATH)


def _req(risk_class, events, **over):
    r = {"workflow_id": "wf-1", "correlation_id": "corr-1", "tenant_id": "t-1",
         "call_id": "call-1", "initiator": "agent",
         "operation": {"name": "op", "risk_class": risk_class, "critical": True, "params": {}},
         "events": events}
    if "params" in over:
        r["operation"]["params"] = over.pop("params")
    if "operation_name" in over:
        r["operation"]["name"] = over.pop("operation_name")
    r.update(over)
    return r


def _ev_auth(level="strong", methods=None, step_up=True, at_ms=0):
    return {"type": "auth", "level": level, "methods": methods or ["otp"], "step_up": step_up, "at_ms": at_ms}


def selftest():
    spec, pol = _ctx()
    results = []

    def t(name, cond):
        results.append((bool(cond), name))

    # 1. Happy path — bank_account_change, strong+step_up, confirm yes → COMMITTED
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "result_ref": "ref://1", "at_ms": 2000}]))
    t("happy bank_account_change → COMMITTED", r["final_state"] == "COMMITTED")
    t("happy → result_ref taşınır", r["result_ref"] == "ref://1")
    t("happy → audit yazıldı", dict(r["step_verdicts"]).get("AUDIT") == "pass")

    # 2. K2 — auth yetersiz (basic) → DENIED AUTH_INSUFFICIENT, EXECUTE yok
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(level="basic", at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 100},
         {"type": "execute", "outcome": "ok", "at_ms": 200}]))
    t("K2 basic auth → DENIED AUTH_INSUFFICIENT", r["final_state"] == "DENIED" and r["reason"] == "AUTH_INSUFFICIENT")
    t("K2 red → EXECUTE çalışmaz", "EXECUTE" not in dict(r["step_verdicts"]))

    # 2b. K2 — caller_id TEK BAŞINA güçlü değil → basic'e sabitlenir → DENIED
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(level="strong", methods=["caller_id"], at_ms=0)]))
    t("K2 caller_id-only → güçlü sayılmaz → DENIED", r["final_state"] == "DENIED" and r["reason"] == "AUTH_INSUFFICIENT")

    # 3. K7 — step_up yok (para/PII) → DENIED STEP_UP_REQUIRED
    r = run_workflow(spec, pol, _req("contact_info_change",
        [_ev_auth(step_up=False, at_ms=0)]))
    t("K7 step_up yok → DENIED STEP_UP_REQUIRED", r["final_state"] == "DENIED" and r["reason"] == "STEP_UP_REQUIRED")

    # 4. K5 — teyit 'no' → ABORTED CUSTOMER_DECLINED, EXECUTE yok
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "no", "at_ms": 1000}]))
    t("K5 teyit no → ABORTED CUSTOMER_DECLINED", r["final_state"] == "ABORTED" and r["reason"] == "CUSTOMER_DECLINED")
    t("K5 abort → EXECUTE yok", "EXECUTE" not in dict(r["step_verdicts"]))

    # 4b. K5 — teyit belirsiz → ABORTED CONFIRMATION_NOT_OBTAINED
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "ambiguous", "at_ms": 1000}]))
    t("K5 belirsiz teyit → ABORTED NOT_OBTAINED", r["final_state"] == "ABORTED" and r["reason"] == "CONFIRMATION_NOT_OBTAINED")

    # 4c. K5 — teyit olayı hiç yok → ABORTED NOT_OBTAINED
    r = run_workflow(spec, pol, _req("bank_account_change", [_ev_auth(at_ms=0)]))
    t("K5 teyit olayı yok → ABORTED NOT_OBTAINED", r["final_state"] == "ABORTED" and r["reason"] == "CONFIRMATION_NOT_OBTAINED")

    # 5. K6 — insan onayı gereken op (contract_cancellation), onaylı + farklı aktör → COMMITTED
    r = run_workflow(spec, pol, _req("contract_cancellation",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "approval", "decision": "approved", "actor": "supervisor-7", "at_ms": 2000},
         {"type": "execute", "outcome": "ok", "at_ms": 3000}]))
    t("K6 onaylı maker-checker → COMMITTED", r["final_state"] == "COMMITTED" and r["approver"] == "supervisor-7")
    t("K6 requires_human_approval=true hesaplandı", r["requirements"]["requires_human_approval"] is True)

    # 5b. K6 — onay reddi → DENIED APPROVAL_REJECTED
    r = run_workflow(spec, pol, _req("contract_cancellation",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "approval", "decision": "rejected", "actor": "supervisor-7", "at_ms": 2000}]))
    t("K6 onay reddi → DENIED APPROVAL_REJECTED", r["final_state"] == "DENIED" and r["reason"] == "APPROVAL_REJECTED")

    # 5c. K6 — onaylayan == talep eden → MAKER_CHECKER_VIOLATION
    r = run_workflow(spec, pol, _req("contract_cancellation",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "approval", "decision": "approved", "actor": "agent", "at_ms": 2000}],
        initiator="agent"))
    t("K6 aynı aktör → MAKER_CHECKER_VIOLATION", r["final_state"] == "DENIED" and r["reason"] == "MAKER_CHECKER_VIOLATION")

    # 5d. K6 — onay gerekli ama olay yok → DENIED APPROVAL_REQUIRED
    r = run_workflow(spec, pol, _req("contract_cancellation",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000}]))
    t("K6 onay olayı yok → DENIED APPROVAL_REQUIRED", r["final_state"] == "DENIED" and r["reason"] == "APPROVAL_REQUIRED")

    # 6. K3 — forbidden_autonomous (health_diagnosis) → insan onayı ZORLANIR
    r = run_workflow(spec, pol, _req("health_diagnosis",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000}]))
    t("K3 forbidden_autonomous → insan onayı zorlanır", r["requirements"]["requires_human_approval"] is True)
    t("K3 forbidden onaysız → DENIED APPROVAL_REQUIRED", r["final_state"] == "DENIED" and r["reason"] == "APPROVAL_REQUIRED")

    # 6b. K3 — bilinmeyen risk_class → DENIED UNKNOWN_RISK_CLASS (fail-closed)
    r = run_workflow(spec, pol, _req("made_up_class", [_ev_auth(at_ms=0)]))
    t("K3 bilinmeyen risk_class → DENIED UNKNOWN_RISK_CLASS", r["final_state"] == "DENIED" and r["reason"] == "UNKNOWN_RISK_CLASS")

    # 6c. K3 — tutar eşiği üstü → insan onayına eskalasyon
    r = run_workflow(spec, pol, _req("high_value_payment",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000}],
        params={"amount": 50000, "currency": "TRY"}))
    t("K3 tutar eşik üstü → onay zorlanır", r["requirements"]["requires_human_approval"] is True)
    # eşik altı → onay gerekmez, COMMITTED
    r = run_workflow(spec, pol, _req("high_value_payment",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}],
        params={"amount": 500, "currency": "TRY"}))
    t("K3 tutar eşik altı → onaysız COMMITTED", r["final_state"] == "COMMITTED" and r["requirements"]["requires_human_approval"] is False)

    # 7. K9 — confirm deadline aşımı → EXPIRED
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 500000}],
        deadline_ms=120000))
    t("K9 deadline aşımı → EXPIRED", r["final_state"] == "EXPIRED")
    t("K9 EXPIRED → EXECUTE yok", "EXECUTE" not in dict(r["step_verdicts"]))

    # 8. EXECUTE fault → FAILED + audit
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "fault", "fault_class": "UPSTREAM_5XX", "at_ms": 2000}]))
    t("EXECUTE fault → FAILED", r["final_state"] == "FAILED" and r["reason"] == "UPSTREAM_5XX")
    t("FAILED → audit yazıldı", dict(r["step_verdicts"]).get("AUDIT") == "pass")

    # 9. K11 — özet maskeleme: ham hesap no sızmaz
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}],
        params={"masked": {"hesap": "TR330006100519786457841326"}}))
    t("K11 özet ham hesap no içermez", not _scan(r["summary_text"], PII_PATTERNS))
    t("K11 özet son-4 maskeli", "1326" in r["summary_text"] and "786457841326" not in r["summary_text"])

    # 9b. K11 — degraded: unsafe_summary ham PII → tarayıcı yakalar
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}],
        unsafe_summary="Hesabınız TR330006100519786457841326 olarak güncellenecek"))
    t("K11 kirli özet → tarayıcı tetiklenir", bool(_scan(r["summary_text"], PII_PATTERNS)))

    # 10. K10 — temiz audit PII'siz / kirli audit yakalanır
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}]))
    t("K10 temiz audit PII'siz", not _scan(json.dumps(r["audit"], ensure_ascii=False), PII_PATTERNS))
    r2 = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}],
        unsafe_audit_detail="customer john.doe@example.com card 4111111111111111"))
    t("K10 kirli audit → tarayıcı tetiklenir", bool(_scan(json.dumps(r2["audit"], ensure_ascii=False), PII_PATTERNS)))

    # 11. K8 — terminal sonrası kalan olaylar yok sayılır (ABORTED'tan sonra execute olayı)
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "no", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}]))
    t("K8 ABORTED sonrası execute yok sayılır", r["final_state"] == "ABORTED" and "EXECUTE" not in dict(r["step_verdicts"]))

    # 12. K1 — sıra: COMMITTED varsa AUTH/RULE/SUMMARY/CONFIRM hepsi pass
    r = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}]))
    sv = dict(r["step_verdicts"])
    t("K1 COMMITTED → tüm kapılar pass", all(sv.get(s) == "pass" for s in ("AUTH", "RULE", "SUMMARY", "CONFIRM", "EXECUTE", "AUDIT")))

    # 13. K12 — determinizm birebir
    a = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}]))
    b = run_workflow(spec, pol, _req("bank_account_change",
        [_ev_auth(at_ms=0), {"type": "confirm", "value": "yes", "at_ms": 1000},
         {"type": "execute", "outcome": "ok", "at_ms": 2000}]))
    t("K12 determinizm birebir", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))

    # 14. NOT_CRITICAL → WorkflowError
    try:
        run_workflow(spec, pol, _req("bank_account_change", [_ev_auth(at_ms=0)],
                                     operation={"name": "x", "risk_class": "bank_account_change", "critical": False}))
        t("non-critical → WorkflowError", False)
    except WorkflowError as e:
        t("non-critical → WorkflowError NOT_CRITICAL", e.error_class == "NOT_CRITICAL")

    # 15. INVALID_REQUEST (eksik initiator)
    try:
        run_workflow(spec, pol, {"workflow_id": "w", "correlation_id": "c", "tenant_id": "t",
                                 "operation": {"risk_class": "bank_account_change"}, "events": []})
        t("eksik initiator → WorkflowError", False)
    except WorkflowError as e:
        t("eksik initiator → WorkflowError INVALID_REQUEST", e.error_class == "INVALID_REQUEST")

    # 16. NON_MONOTONIC_CLOCK
    try:
        run_workflow(spec, pol, _req("bank_account_change",
            [_ev_auth(at_ms=1000), {"type": "confirm", "value": "yes", "at_ms": 500}]))
        t("geri saat → WorkflowError", False)
    except WorkflowError as e:
        t("geri saat → WorkflowError NON_MONOTONIC_CLOCK", e.error_class == "NON_MONOTONIC_CLOCK")

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("selftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "critical-workflow (WBS 7.3.1)",
        "brd13_steps": ["AUTH(1)", "RULE(2)", "SUMMARY(3)", "CONFIRM(4)", "APPROVAL(5)", "EXECUTE→7.2.x", "AUDIT(6)"],
        "states": ["INIT"] + STEP_STATES + sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "event_types": ["auth", "confirm", "approval", "execute"],
        "request_fields": ["workflow_id", "correlation_id", "tenant_id", "call_id", "initiator",
                           "operation{name,risk_class,critical,params}", "events[]", "deadline_ms"],
        "result_fields": ["final_state", "reason", "approver", "result_ref", "summary_text",
                          "requirements", "step_verdicts", "audit"],
        "deny_reasons": sorted(DENY_REASONS),
        "abort_reasons": sorted(ABORT_REASONS),
        "invariants": INVARIANT_IDS,
        "trace": "BRD §13, FR-TOOL-006/007, FR-IAM-005/006, FR-AUTH-003, SAD §11.1/§11.3, ADR-001/002/012",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
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
            print("kullanım: critical_workflow_probe.py run <sample.json>")
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
