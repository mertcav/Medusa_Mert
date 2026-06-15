#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.1.4 — Timeout/retry/circuit breaker (Integration GW) (SAD §11.1 adım [5] + §11.2 / FR-TOOL-003) referans probe.

    LLM tool call ──► [1] input schema ──► [2] authz ──► [3] policy gate ──► [4] idempotency
                  ──► [5] Integration GW: TIMEOUT + RETRY + CIRCUIT BREAKER  ◄── bu motor
                  ──► [6] output schema + error normalization ──► [7] correlation_id audit

Tool Yürütme Hattının (SAD §11.1) DAYANIKLILIK aşaması. Bir upstream bağımlılığına (REST/SOAP/GraphQL/
webhook — FR-TOOL-001) giden tool çağrısını sarar:
  • per-attempt TIMEOUT (R1) — deadline'ı aşan deneme TIMEOUT fault, gecikme kesilir (hung YOK);
  • sınırlı RETRY (R2) — attempts ≤ max_attempts ('kontrolsüz retry yok'); exponential backoff + tohumlu jitter (R3);
    yalnız RETRYABLE/geçici fault'lar (R4); WRITE yalnız idempotency_key varsa (R5, FR-TOOL-009 köprüsü);
  • endpoint-başına CIRCUIT BREAKER (R6/R7/R8) — eşik aşılınca CLOSED→OPEN; OPEN'da fail-fast kısa-devre
    (upstream'e değmez); cooldown sonrası HALF_OPEN probe → CLOSED/OPEN; endpoint izolasyonu (R9);
  • determinizm (R10), audit no-log (R11), yapısal fault taksonomisi (R12).

INVARIANT (SR-TOOL-003 kabul ölçütü): 'Bağımlılık hatasında devre açılır; KONTROLSÜZ RETRY YOK'.

Kapsam dışı (bilinçli): input/output schema → 7.1.1; authz → 7.1.2; idempotency key üretimi → 7.1.3 (bu motor
key VARLIĞINI tüketir); MÜŞTERİYE hata metni → 7.1.5 (burada yalnız fault_class); correlation_id audit
zenginleştirme → 7.1.6; allowlist → FR-TOOL-012; async workflow → FR-TOOL-011. Vendor-neutral (ADR-001/002):
upstream transport bir SPI noktası — referans deterministik 'attempts_script' (gerçek ağ/credential YOK);
canlıda gerçek transport + connection pool (FR-RES-006) AYNI imza arkasına.

Kullanım:
  integration_gw_probe.py validate          Statik spec/config/şema kapısı → çıkış kodu
  integration_gw_probe.py run <sample>      Deterministik resilience simülasyonu — çağrı dizisi → kapı (R1–R12)
  integration_gw_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  integration_gw_probe.py schema            SPI/CallResult/karar sözleşmesini yazdır

Determinizm: jitter tohumlu PRNG'den (seed sample'da); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008).
"""
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "integration-gw-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "integration-gw-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# ── Fault taksonomisi (spec ile tutarlı) ───────────────────────────────────────
RETRYABLE_FAULTS = {"TIMEOUT", "UPSTREAM_5XX", "CONN_RESET", "CONN_REFUSED", "RATE_LIMITED", "DEADLINE_EXCEEDED"}
TERMINAL_FAULTS = {"UPSTREAM_4XX", "SCHEMA_INVALID", "AUTH_FAILED", "NOT_FOUND"}
GATEWAY_FAULTS = {"CIRCUIT_OPEN", "RETRY_EXHAUSTED"}
ALL_FAULTS = RETRYABLE_FAULTS | TERMINAL_FAULTS | GATEWAY_FAULTS

GATE_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

ERROR_CLASSES = {"MISSING_POLICY_CONFIG", "INVALID_POLICY", "INVALID_CALL_INPUT", "NON_MONOTONIC_CLOCK", "INTERNAL_ERROR"}

STATE_CLOSED, STATE_OPEN, STATE_HALF = "CLOSED", "OPEN", "HALF_OPEN"

SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ── Circuit breaker (endpoint-başına, per-call gözlem) ──────────────────────────
class CircuitBreaker:
    """Tek endpoint için CLOSED/OPEN/HALF_OPEN devre kesici. Gözlem PER-CALL (R6/R7/R8)."""

    def __init__(self, cfg):
        self.failure_threshold = int(cfg.get("failure_threshold", 5))
        self.window_size = int(cfg.get("window_size", 20))
        self.min_calls = int(cfg.get("min_calls", 10))
        self.rate_threshold = float(cfg.get("rate_threshold", 0.5))
        self.cooldown_ms = int(cfg.get("cooldown_ms", 5000))
        self.half_open_max_probes = int(cfg.get("half_open_max_probes", 1))
        self.half_open_success_to_close = int(cfg.get("half_open_success_to_close", 1))
        self.state = STATE_CLOSED
        self.consecutive_failures = 0
        self.window = []  # son window_size sonuç (True=başarı)
        self.opened_at = None
        self.half_open_probes = 0
        self.half_open_successes = 0

    def _failure_rate(self):
        if not self.window:
            return 0.0
        return sum(1 for ok in self.window if not ok) / float(len(self.window))

    def allow(self, now_ms):
        """Çağrının upstream'e gitmesine izin var mı? OPEN→HALF_OPEN geçişini ve probe muhasebesini yapar."""
        if self.state == STATE_CLOSED:
            return True
        if self.state == STATE_OPEN:
            if self.opened_at is not None and (now_ms - self.opened_at) >= self.cooldown_ms:
                # cooldown doldu → HALF_OPEN, ilk probe'a izin
                self.state = STATE_HALF
                self.half_open_probes = 0
                self.half_open_successes = 0
                self.half_open_probes += 1
                return True
            return False  # fail-fast (R7)
        # HALF_OPEN
        if self.half_open_probes < self.half_open_max_probes:
            self.half_open_probes += 1
            return True
        return False  # probe kotası dolu → fail-fast

    def _trip_open(self, now_ms):
        self.state = STATE_OPEN
        self.opened_at = now_ms
        self.window = []
        self.consecutive_failures = 0

    def _close(self):
        self.state = STATE_CLOSED
        self.opened_at = None
        self.consecutive_failures = 0
        self.window = []
        self.half_open_probes = 0
        self.half_open_successes = 0

    def on_success(self, now_ms):
        if self.state == STATE_HALF:
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_success_to_close:
                self._close()
            return
        # CLOSED
        self.consecutive_failures = 0
        self.window.append(True)
        if len(self.window) > self.window_size:
            self.window.pop(0)

    def on_failure(self, now_ms):
        if self.state == STATE_HALF:
            # probe hatası → tekrar OPEN, cooldown yeniden (R8)
            self._trip_open(now_ms)
            return
        # CLOSED
        self.consecutive_failures += 1
        self.window.append(False)
        if len(self.window) > self.window_size:
            self.window.pop(0)
        if self.consecutive_failures >= self.failure_threshold:
            self._trip_open(now_ms)
            return
        if len(self.window) >= self.min_calls and self._failure_rate() >= self.rate_threshold:
            self._trip_open(now_ms)


# ── Integration Gateway (resilience motoru) ─────────────────────────────────────
class IntegrationGateway:
    def __init__(self, policy, seed=0):
        self.policy = policy
        self.rng = random.Random(seed)
        self.breakers = {}
        self.clock_ms = 0
        self.audit = []
        self._err = None

    # policy doğrulama
    def _validate_policy(self):
        p = self.policy
        if not isinstance(p, dict) or not p:
            return "MISSING_POLICY_CONFIG"
        req = ["timeout_ms", "max_attempts", "base_backoff_ms", "backoff_multiplier", "max_backoff_ms", "jitter"]
        for k in req:
            if k not in p:
                return "MISSING_POLICY_CONFIG"
        if p["timeout_ms"] <= 0 or p["max_attempts"] < 1 or p["base_backoff_ms"] < 0:
            return "INVALID_POLICY"
        if p["backoff_multiplier"] < 1.0 or p["max_backoff_ms"] < 0:
            return "INVALID_POLICY"
        if p["jitter"] not in ("full", "equal", "none"):
            return "INVALID_POLICY"
        if "breaker" not in p or not isinstance(p["breaker"], dict):
            return "MISSING_POLICY_CONFIG"
        return None

    def _breaker(self, endpoint):
        if endpoint not in self.breakers:
            self.breakers[endpoint] = CircuitBreaker(self.policy["breaker"])
        return self.breakers[endpoint]

    def _backoff(self, attempt_no):
        """attempt_no: kaç deneme YAPILDI (1 → ilk retry öncesi backoff). base×mult^(n-1), kapılı, + jitter."""
        p = self.policy
        base = p["base_backoff_ms"] * (p["backoff_multiplier"] ** (attempt_no - 1))
        base = min(base, p["max_backoff_ms"])
        mode = p["jitter"]
        if mode == "none":
            return base
        if mode == "equal":
            return base / 2.0 + self.rng.random() * (base / 2.0)
        return self.rng.random() * base  # full

    def _eval_attempt(self, outcome):
        """AttemptOutcome → (result, fault_class|None, effective_latency_ms). Timeout deadline'da kesilir (R1)."""
        timeout_ms = self.policy["timeout_ms"]
        res = outcome.get("result", "ok")
        lat = float(outcome.get("latency_ms", 0))
        if res == "timeout":
            return "fault", "TIMEOUT", float(timeout_ms)
        if res == "fault":
            fc = outcome.get("fault_class", "UPSTREAM_5XX")
            # fault da deadline'ı aşamaz (gecikme kesilir)
            return "fault", fc, min(lat, float(timeout_ms))
        # ok — ama deadline aşılırsa TIMEOUT'a dönüşür (R1)
        if lat > timeout_ms:
            return "fault", "TIMEOUT", float(timeout_ms)
        return "ok", None, lat

    def _scripted(self, call, idx):
        script = call.get("attempts_script", [])
        if not script:
            return {"result": "ok", "latency_ms": 10}
        if idx < len(script):
            return script[idx]
        return script[-1]  # kalıcı durum: son scripted sonucu tekrarla

    def _retryable(self, fault):
        retry_on = self.policy.get("retry_on")
        if retry_on is not None:
            return fault in set(retry_on)
        return fault in RETRYABLE_FAULTS

    def call(self, c):
        """Tek tool çağrısını resilience ile yürüt → CallResult."""
        endpoint = c.get("endpoint")
        op = c.get("operation_class", "read")
        idem = c.get("idempotency_key")
        corr = c.get("correlation_id", "")
        # clock: at_ms verilirse oraya atla (monoton olmalı), yoksa devam
        if "at_ms" in c:
            at = int(c["at_ms"])
            if at < self.clock_ms:
                self._err = ("NON_MONOTONIC_CLOCK", "at_ms < clock_ms")
                return None
            self.clock_ms = at

        br = self._breaker(endpoint)
        state_before = br.state

        # breaker kapısı (R7) — OPEN/HALF kotası dolu ise upstream'e DEĞME
        if not br.allow(self.clock_ms):
            result = {
                "call_id": c.get("call_id"), "correlation_id": corr, "endpoint": endpoint,
                "operation_class": op, "status": "short_circuited", "fault_class": "CIRCUIT_OPEN",
                "reason": "circuit_open_fail_fast", "attempts": 0, "retries": 0, "retried": False,
                "timed_out_attempts": 0, "short_circuited": True, "total_latency_ms": 0.0,
                "backoff_total_ms": 0.0, "breaker_state_before": state_before,
                "breaker_state_after": br.state,
            }
            self._audit(result)
            return result

        retry_allowed_for_op = (op != "write") or (not self.policy.get("retry_writes_require_idempotency", True)) or bool(idem)
        max_attempts = int(self.policy["max_attempts"])
        attempts = 0
        timed_out = 0
        latency_total = 0.0
        backoff_total = 0.0
        last_fault = None
        success = False

        while attempts < max_attempts:
            outcome = self._scripted(c, attempts)
            attempts += 1
            res, fault, lat = self._eval_attempt(outcome)
            latency_total += lat
            self.clock_ms += lat
            if res == "ok":
                success = True
                last_fault = None
                break
            last_fault = fault
            if fault == "TIMEOUT":
                timed_out += 1
            retryable = self._retryable(fault)
            can_retry = retryable and retry_allowed_for_op and attempts < max_attempts
            if not can_retry:
                break
            b = self._backoff(attempts)
            backoff_total += b
            self.clock_ms += b

        # breaker per-call gözlem
        if success:
            br.on_success(self.clock_ms)
            status, fault_class, reason = "success", None, ("retried_ok" if attempts > 1 else "ok")
        else:
            br.on_failure(self.clock_ms)
            status = "failed"
            fault_class = last_fault
            if attempts >= max_attempts and self._retryable(last_fault) and retry_allowed_for_op:
                reason = "retry_exhausted"
            elif last_fault in TERMINAL_FAULTS:
                reason = "terminal_fault"
            elif op == "write" and not retry_allowed_for_op:
                reason = "write_not_retried_no_idempotency"
            else:
                reason = "failed"

        result = {
            "call_id": c.get("call_id"), "correlation_id": corr, "endpoint": endpoint,
            "operation_class": op, "status": status, "fault_class": fault_class, "reason": reason,
            "attempts": attempts, "retries": max(0, attempts - 1), "retried": attempts > 1,
            "timed_out_attempts": timed_out, "short_circuited": False,
            "total_latency_ms": round(latency_total + backoff_total, 3),
            "backoff_total_ms": round(backoff_total, 3),
            "breaker_state_before": state_before, "breaker_state_after": br.state,
        }
        self._audit(result)
        return result

    def _audit(self, r):
        self.audit.append({
            "correlation_id": r["correlation_id"], "endpoint": r["endpoint"],
            "operation_class": r["operation_class"], "status": r["status"],
            "fault_class": r["fault_class"], "attempts": r["attempts"],
            "breaker_state_before": r["breaker_state_before"],
            "breaker_state_after": r["breaker_state_after"], "no_log": True,
        })


# ── sample yürütme ──────────────────────────────────────────────────────────────
def _resolve_policy(sample):
    cfg = _load(CONFIG_PATH)
    if "policy" in sample:
        return dict(sample["policy"])
    prof = sample.get("profile")
    if prof and prof in cfg["profiles"]:
        p = {k: v for k, v in cfg["profiles"][prof].items() if not k.startswith("$")}
        return p
    return None


def _run_sample(sample):
    policy = _resolve_policy(sample)
    seed = int(sample.get("seed", 0))
    gw = IntegrationGateway(policy or {}, seed=seed)
    perr = gw._validate_policy()
    if perr:
        return {"error_class": perr, "results": [], "gw": gw}
    results = []
    for c in sample.get("calls", []):
        if not isinstance(c, dict) or "endpoint" not in c or "attempts_script" not in c:
            return {"error_class": "INVALID_CALL_INPUT", "results": results, "gw": gw}
        r = gw.call(c)
        if r is None:
            ec = gw._err[0] if gw._err else "INTERNAL_ERROR"
            return {"error_class": ec, "results": results, "gw": gw}
        results.append(r)
    return {"error_class": None, "results": results, "gw": gw}


# ── kapı denetimi (R1–R12) ──────────────────────────────────────────────────────
def _check_gates(sample, run):
    """Sample'ın beklenen invariant'larını + genel R-kapılarını denetle → (ok, satırlar)."""
    lines = []
    ok = True
    if run["error_class"]:
        expect_err = sample.get("expect_error_class")
        if expect_err == run["error_class"]:
            lines.append("  ✓ beklenen hata: %s" % run["error_class"])
            return True, lines
        lines.append("  ✗ hata: %s" % run["error_class"])
        return False, lines

    policy = _resolve_policy(sample)
    max_attempts = int(policy["max_attempts"])
    timeout_ms = float(policy["timeout_ms"])
    results = run["results"]

    # R2: bounded retry (her zaman)
    for r in results:
        if r["attempts"] > max_attempts:
            ok = False
            lines.append("  ✗ R2 attempts %d > max %d (%s)" % (r["attempts"], max_attempts, r["call_id"]))

    # R4/R5: terminal / write-no-idem → attempts==1
    for r in results:
        if r["fault_class"] in TERMINAL_FAULTS and r["attempts"] != 1 and not r["short_circuited"]:
            ok = False
            lines.append("  ✗ R4 terminal fault retry edildi (%s)" % r["call_id"])

    # Sample-bazlı beklentiler
    exp = sample.get("expect", {})
    by_id = {r["call_id"]: r for r in results if r.get("call_id")}
    for cid, want in exp.items():
        r = by_id.get(cid)
        if r is None:
            ok = False
            lines.append("  ✗ beklenen çağrı sonucu yok: %s" % cid)
            continue
        for k, v in want.items():
            got = r.get(k)
            if got != v:
                ok = False
                lines.append("  ✗ %s.%s = %r (beklenen %r)" % (cid, k, got, v))
            else:
                lines.append("  ✓ %s.%s = %r" % (cid, k, v))

    # R12: terminal/short-circuit fault_class taksonomide
    for r in results:
        if r["status"] in ("failed", "short_circuited"):
            if r["fault_class"] not in ALL_FAULTS:
                ok = False
                lines.append("  ✗ R12 bilinmeyen fault_class %r (%s)" % (r["fault_class"], r["call_id"]))

    # R1: timeout — timed_out denemeli çağrıda total_latency tutarlı (deadline kesimi)
    for r in results:
        if r["timed_out_attempts"] > 0:
            # her timeout denemesi en fazla timeout_ms ekler; backoff hariç attempt latency ≤ attempts*timeout
            if r["total_latency_ms"] - r["backoff_total_ms"] > r["attempts"] * timeout_ms + 1e-6:
                ok = False
                lines.append("  ✗ R1 deadline aşıldı (%s)" % r["call_id"])

    # R11: audit no-log
    blob = json.dumps(run["gw"].audit, ensure_ascii=False)
    if SECRET_RE.search(blob) or CREDIT_CARD_RE.search(blob) or EMAIL_RE.search(blob):
        ok = False
        lines.append("  ✗ R11 audit'te secret/PII")
    if not all(a.get("no_log") for a in run["gw"].audit):
        ok = False
        lines.append("  ✗ R11 audit no_log işareti eksik")

    return ok, lines


def run_cmd(path):
    sample = _load(path)
    run = _run_sample(sample)
    name = sample.get("name", os.path.basename(path))
    print("== run: %s ==" % name)
    for r in run["results"]:
        print("  [%s] %s op=%s → %s fault=%s attempts=%d retried=%s timeout=%d sc=%s br:%s→%s lat=%.0fms" % (
            r["call_id"], r["endpoint"], r["operation_class"], r["status"], r["fault_class"],
            r["attempts"], r["retried"], r["timed_out_attempts"], r["short_circuited"],
            r["breaker_state_before"], r["breaker_state_after"], r["total_latency_ms"]))
    if run["error_class"]:
        print("  error_class: %s" % run["error_class"])
    ok, lines = _check_gates(sample, run)
    for ln in lines:
        print(ln)
    print("KAPI: %s" % ("🟢 GEÇTI" if ok else "🔴 ELENDI"))
    return 0 if ok else 1


# ── validate (statik kapı) ──────────────────────────────────────────────────────
def validate():
    fails = []

    def expect(c, m):
        if not c:
            fails.append(m)

    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)

    expect(spec.get("wbs") == "7.1.4", "spec.wbs 7.1.4")
    expect("FR-TOOL-003" in spec["trace"]["fr"], "trace FR-TOOL-003")
    expect("SR-TOOL-003" in spec["trace"]["srs"], "trace SR-TOOL-003")
    expect("FR-TOOL-009" in spec["trace"]["fr"], "trace FR-TOOL-009 (write retry köprüsü)")
    expect([inv["id"] for inv in spec["invariants"]] == GATE_IDS, "invariants R1–R12 sırası")

    # fault taksonomi tutarlılığı spec↔kod
    st = spec["fault_taxonomy"]
    expect(set(st["retryable"]) == RETRYABLE_FAULTS, "retryable taksonomi spec↔kod")
    expect(set(st["terminal"]) == TERMINAL_FAULTS, "terminal taksonomi spec↔kod")
    expect(set(st["gateway"]) == GATEWAY_FAULTS, "gateway taksonomi spec↔kod")
    expect(set(spec["error_taxonomy"]["classes"]) == ERROR_CLASSES, "error taksonomi spec↔kod")

    # profil bütünlüğü + her profil geçerli policy
    for pname, prof in cfg["profiles"].items():
        p = {k: v for k, v in prof.items() if not k.startswith("$")}
        gw = IntegrationGateway(p, seed=0)
        err = gw._validate_policy()
        expect(err is None, "profil %s geçerli policy (%s)" % (pname, err))

    # sır/PII taraması (spec/config/samples)
    scan_paths = [SPEC_PATH, CONFIG_PATH] + [os.path.join(SAMPLES_DIR, f)
                                             for f in sorted(os.listdir(SAMPLES_DIR)) if f.endswith(".json")]
    for sp in scan_paths:
        with open(sp, "r", encoding="utf-8") as f:
            txt = f.read()
        if SECRET_RE.search(txt):
            fails.append("sır sızıntısı: %s" % os.path.basename(sp))
        if CREDIT_CARD_RE.search(txt):
            fails.append("kart no: %s" % os.path.basename(sp))
        for em in EMAIL_RE.findall(txt):
            if not em.endswith("example.com"):
                fails.append("e-posta PII: %s (%s)" % (os.path.basename(sp), em))

    # her sample kapısı geçer
    for f in sorted(os.listdir(SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        sample = _load(os.path.join(SAMPLES_DIR, f))
        run = _run_sample(sample)
        ok, _ = _check_gates(sample, run)
        expect(ok, "sample kapısı: %s" % f)

    print("validate: %d kontrol başarısız" % len(fails))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── selftest (gömülü davranış) ──────────────────────────────────────────────────
def _pol(**kw):
    base = {
        "timeout_ms": 500, "max_attempts": 3, "base_backoff_ms": 50, "backoff_multiplier": 2.0,
        "max_backoff_ms": 2000, "jitter": "full", "retry_writes_require_idempotency": True,
        "breaker": {"failure_threshold": 3, "window_size": 10, "min_calls": 4, "rate_threshold": 0.5,
                    "cooldown_ms": 5000, "half_open_max_probes": 1, "half_open_success_to_close": 1},
    }
    base.update(kw)
    return base


def selftest():
    fails = []
    n = 0

    def expect(c, m):
        nonlocal n
        n += 1
        if not c:
            fails.append(m)

    F = {"result": "fault", "fault_class": "UPSTREAM_5XX", "latency_ms": 20}
    OK = {"result": "ok", "latency_ms": 30}
    T = {"result": "timeout"}

    # R1: timeout deadline kesimi — ok ama latency>timeout → TIMEOUT
    gw = IntegrationGateway(_pol(), seed=1)
    r = gw.call({"call_id": "c", "endpoint": "e", "operation_class": "read",
                 "attempts_script": [{"result": "ok", "latency_ms": 9999}, OK]})
    expect(r["timed_out_attempts"] >= 1 and r["status"] == "success", "R1 deadline aşan ok → TIMEOUT + retry")

    # R2: bounded retry — hepsi transient → attempts == max_attempts, status failed
    gw = IntegrationGateway(_pol(max_attempts=3), seed=1)
    r = gw.call({"call_id": "c", "endpoint": "e", "operation_class": "read",
                 "attempts_script": [F, F, F, F, F]})
    expect(r["attempts"] == 3 and r["status"] == "failed", "R2 attempts==max (kontrolsüz retry yok)")
    expect(r["reason"] == "retry_exhausted", "R2 reason retry_exhausted")

    # R3: backoff exponential + jitter sınırlı (full → [0,base])
    gw = IntegrationGateway(_pol(jitter="none", base_backoff_ms=50, backoff_multiplier=2.0, max_backoff_ms=1000), seed=1)
    b1 = gw._backoff(1)
    b2 = gw._backoff(2)
    b3 = gw._backoff(3)
    expect(abs(b1 - 50) < 1e-9 and abs(b2 - 100) < 1e-9 and abs(b3 - 200) < 1e-9, "R3 exponential none")
    gw2 = IntegrationGateway(_pol(jitter="full", base_backoff_ms=100, max_backoff_ms=100), seed=5)
    samples_b = [gw2._backoff(1) for _ in range(50)]
    expect(all(0 <= b <= 100 + 1e-9 for b in samples_b), "R3 full jitter ∈ [0,base]")
    gw3 = IntegrationGateway(_pol(jitter="equal", base_backoff_ms=100, max_backoff_ms=100), seed=5)
    samples_e = [gw3._backoff(1) for _ in range(50)]
    expect(all(50 - 1e-9 <= b <= 100 + 1e-9 for b in samples_e), "R3 equal jitter ∈ [base/2,base]")
    gw4 = IntegrationGateway(_pol(jitter="none", base_backoff_ms=500, backoff_multiplier=4.0, max_backoff_ms=600), seed=1)
    expect(gw4._backoff(3) == 600, "R3 max_backoff kapılı")

    # R4: terminal fault → attempts==1 (retry yok)
    gw = IntegrationGateway(_pol(), seed=1)
    r = gw.call({"call_id": "c", "endpoint": "e", "operation_class": "read",
                 "attempts_script": [{"result": "fault", "fault_class": "UPSTREAM_4XX", "latency_ms": 10}, OK]})
    expect(r["attempts"] == 1 and r["status"] == "failed" and r["fault_class"] == "UPSTREAM_4XX", "R4 terminal tek deneme")

    # R5: write without idempotency → attempts==1; with key → retry
    gw = IntegrationGateway(_pol(), seed=1)
    r_no = gw.call({"call_id": "w", "endpoint": "e", "operation_class": "write",
                    "attempts_script": [F, OK]})
    expect(r_no["attempts"] == 1 and r_no["reason"] == "write_not_retried_no_idempotency",
           "R5 write no-idem tek deneme")
    gw = IntegrationGateway(_pol(), seed=1)
    r_yes = gw.call({"call_id": "w2", "endpoint": "e", "operation_class": "write", "idempotency_key": "k-1",
                     "attempts_script": [F, OK]})
    expect(r_yes["attempts"] == 2 and r_yes["status"] == "success", "R5 write idem retry edilir")

    # R6: breaker trips OPEN on consecutive failures (per-call)
    gw = IntegrationGateway(_pol(max_attempts=1), seed=1)  # tek deneme → her çağrı bir gözlem
    for i in range(3):
        gw.call({"call_id": "c%d" % i, "endpoint": "dep", "operation_class": "read", "attempts_script": [F]})
    expect(gw.breakers["dep"].state == STATE_OPEN, "R6 ardışık hata → OPEN")

    # R6b: failure-rate trip
    gwr = IntegrationGateway(_pol(max_attempts=1, breaker={"failure_threshold": 99, "window_size": 10,
            "min_calls": 4, "rate_threshold": 0.5, "cooldown_ms": 5000, "half_open_max_probes": 1,
            "half_open_success_to_close": 1}), seed=1)
    seq = [OK, F, F, F]  # 4 çağrı, 3 hata → oran 0.75 ≥ 0.5
    for i, o in enumerate(seq):
        gwr.call({"call_id": "r%d" % i, "endpoint": "dep", "operation_class": "read", "attempts_script": [o]})
    expect(gwr.breakers["dep"].state == STATE_OPEN, "R6b hata oranı → OPEN")

    # R7: OPEN → fail-fast (attempts==0, CIRCUIT_OPEN)
    r_sc = gw.call({"call_id": "sc", "endpoint": "dep", "operation_class": "read", "attempts_script": [OK]})
    expect(r_sc["short_circuited"] and r_sc["attempts"] == 0 and r_sc["fault_class"] == "CIRCUIT_OPEN",
           "R7 OPEN fail-fast upstream'e değmez")

    # R8: HALF_OPEN recovery — cooldown sonrası probe başarısı → CLOSED
    gw_rec = IntegrationGateway(_pol(max_attempts=1, breaker={"failure_threshold": 2, "window_size": 10,
            "min_calls": 4, "rate_threshold": 0.9, "cooldown_ms": 1000, "half_open_max_probes": 1,
            "half_open_success_to_close": 1}), seed=1)
    gw_rec.call({"call_id": "f1", "endpoint": "d", "operation_class": "read", "at_ms": 0, "attempts_script": [F]})
    gw_rec.call({"call_id": "f2", "endpoint": "d", "operation_class": "read", "attempts_script": [F]})
    expect(gw_rec.breakers["d"].state == STATE_OPEN, "R8 önce OPEN")
    # cooldown içinde → hâlâ fail-fast
    r_in = gw_rec.call({"call_id": "in", "endpoint": "d", "operation_class": "read", "at_ms": 500, "attempts_script": [OK]})
    expect(r_in["short_circuited"], "R8 cooldown içinde fail-fast")
    # cooldown sonrası probe başarı → CLOSED
    r_probe = gw_rec.call({"call_id": "probe", "endpoint": "d", "operation_class": "read", "at_ms": 2000, "attempts_script": [OK]})
    expect(not r_probe["short_circuited"] and gw_rec.breakers["d"].state == STATE_CLOSED, "R8 probe başarı → CLOSED")

    # R8b: HALF_OPEN probe hatası → tekrar OPEN
    gw_rf = IntegrationGateway(_pol(max_attempts=1, breaker={"failure_threshold": 2, "window_size": 10,
            "min_calls": 4, "rate_threshold": 0.9, "cooldown_ms": 1000, "half_open_max_probes": 1,
            "half_open_success_to_close": 1}), seed=1)
    gw_rf.call({"call_id": "f1", "endpoint": "d", "operation_class": "read", "at_ms": 0, "attempts_script": [F]})
    gw_rf.call({"call_id": "f2", "endpoint": "d", "operation_class": "read", "attempts_script": [F]})
    r_pf = gw_rf.call({"call_id": "pf", "endpoint": "d", "operation_class": "read", "at_ms": 2000, "attempts_script": [F]})
    expect(gw_rf.breakers["d"].state == STATE_OPEN and not r_pf["short_circuited"], "R8b probe hatası → OPEN")

    # R9: endpoint isolation — dep OPEN ama healthy endpoint geçer
    gw_iso = IntegrationGateway(_pol(max_attempts=1), seed=1)
    for i in range(3):
        gw_iso.call({"call_id": "x%d" % i, "endpoint": "bad", "operation_class": "read", "attempts_script": [F]})
    expect(gw_iso.breakers["bad"].state == STATE_OPEN, "R9 bad OPEN")
    r_good = gw_iso.call({"call_id": "g", "endpoint": "good", "operation_class": "read", "attempts_script": [OK]})
    expect(r_good["status"] == "success" and not r_good["short_circuited"], "R9 good endpoint izole — kısa-devre yok")

    # R10: determinism — aynı seed → birebir
    def run_once(seed):
        g = IntegrationGateway(_pol(jitter="full"), seed=seed)
        return g.call({"call_id": "c", "endpoint": "e", "operation_class": "read",
                       "attempts_script": [F, F, OK]})
    a = run_once(42)
    b = run_once(42)
    c2 = run_once(7)
    expect(a["total_latency_ms"] == b["total_latency_ms"], "R10 aynı seed → aynı gecikme")
    expect(a["total_latency_ms"] != c2["total_latency_ms"], "R10 farklı seed → farklı jitter")

    # R11: audit no-log
    gw_a = IntegrationGateway(_pol(), seed=1)
    gw_a.call({"call_id": "c", "correlation_id": "corr-xyz", "endpoint": "e", "operation_class": "read",
               "attempts_script": [OK]})
    blob = json.dumps(gw_a.audit, ensure_ascii=False)
    expect("attempts_script" not in blob and all(a.get("no_log") for a in gw_a.audit) and "corr-xyz" in blob,
           "R11 audit no-log + correlation_id var")

    # R12: gateway fault taksonomide
    expect("CIRCUIT_OPEN" in ALL_FAULTS and "RETRY_EXHAUSTED" in ALL_FAULTS, "R12 gateway fault taksonomide")

    # success-on-retry path
    gw_s = IntegrationGateway(_pol(), seed=1)
    r = gw_s.call({"call_id": "c", "endpoint": "e", "operation_class": "read", "attempts_script": [F, OK]})
    expect(r["status"] == "success" and r["retried"] and r["attempts"] == 2 and r["reason"] == "retried_ok",
           "success-on-retry")

    # policy hata sınıfları
    bad = IntegrationGateway({}, seed=0)
    expect(bad._validate_policy() == "MISSING_POLICY_CONFIG", "MISSING_POLICY_CONFIG")
    bad2 = IntegrationGateway(_pol(jitter="weird"), seed=0)
    expect(bad2._validate_policy() == "INVALID_POLICY", "INVALID_POLICY jitter")

    # non-monotonic clock
    gw_m = IntegrationGateway(_pol(), seed=0)
    gw_m.call({"call_id": "a", "endpoint": "e", "operation_class": "read", "at_ms": 1000, "attempts_script": [OK]})
    r_back = gw_m.call({"call_id": "b", "endpoint": "e", "operation_class": "read", "at_ms": 10, "attempts_script": [OK]})
    expect(r_back is None and gw_m._err[0] == "NON_MONOTONIC_CLOCK", "NON_MONOTONIC_CLOCK")

    rc_v = validate()
    expect(rc_v == 0, "validate() çıkış 0")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── schema ──────────────────────────────────────────────────────────────────────
def schema():
    spec = _load(SPEC_PATH)
    print("# WBS 7.1.4 — Timeout/retry/circuit breaker (Integration GW) (SAD §11.1 [5]) sözleşmeleri\n")
    print("Akış: tool call + ResiliencePolicy → [TIMEOUT + RETRY(backoff+jitter) + CIRCUIT BREAKER] → CallResult\n")
    print("ResiliencePolicy: {%s}" % ", ".join(spec["spi"]["policy_fields"]))
    print("Breaker: {%s}\n" % ", ".join(spec["spi"]["breaker_fields"]))
    print("Transport SPI (vendor-neutral): %s\n" % spec["spi"]["transport_method"])
    print("CallResult: " + ", ".join(spec["spi"]["call_result_fields"]))
    print("\nFault taksonomisi:")
    print("  retryable (geçici, retry): " + ", ".join(spec["fault_taxonomy"]["retryable"]))
    print("  terminal  (kalıcı, retry YOK): " + ", ".join(spec["fault_taxonomy"]["terminal"]))
    print("  gateway   (motor üretir): " + ", ".join(spec["fault_taxonomy"]["gateway"]))
    print("\nWrite retry güvenliği (FR-TOOL-009): operation_class=='write' → yalnız idempotency_key varsa retry")
    print("Breaker durumları: " + " → ".join(spec["circuit_breaker"]["states"]) + " (per-endpoint, per-call gözlem)")
    print("\nKapılar (R1–R12):")
    for inv in spec["invariants"]:
        print("  %s — %s" % (inv["id"], inv["desc"][:96]))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    if cmd == "run":
        if len(argv) < 3:
            print("kullanım: integration_gw_probe.py run <sample.json>")
            return 2
        return run_cmd(argv[2])
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
