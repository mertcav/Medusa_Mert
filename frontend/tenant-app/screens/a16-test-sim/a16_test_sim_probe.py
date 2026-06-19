#!/usr/bin/env python3
# WBS 13.4.16 — A-16 "Test & Simulation Centre" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (suite/senaryo/regresyon/gate/yük/tone'lar/assertSafe) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (uzlaşı / gate / regresyon / yük / İKİ KATMAN guard)
#   schema    — test görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/test-sim.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a16-test-sim-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "test", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "test-sim.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

CATEGORY_ORDER = ["happy", "edge", "adversarial", "robustness"]
STATUS_ORDER = ["pass", "fail", "blocked"]
BAND_ORDER = ["good", "warn", "bad"]
TREND_ORDER = ["up", "down", "flat"]
GATE_BLOCKER_ORDER = ["pass_rate", "score", "regression", "adversarial", "load_resource"]

DEFAULT_TARGETS = {
    "gateMinPassRate": 0.85, "gateMinScore": 0.8, "regressionTolerance": 0.05, "loadConcurrencyTarget": 250,
    "cpuMsP95Budget": 250, "memMbP95Budget": 15, "latencyMsP95Target": 1200, "loadResourceTolerance": 0.1,
    "successRateTarget": 0.99,
}
WARN_RATIO = 0.9
TREND_FLAT_EPS = 0.02
MASK_TOKEN = "[•••]"

FORBIDDEN_PII_KEYS = ["callref", "text", "transcripttext", "rawtext", "transcript", "utterance", "recording",
                      "recordingbytes", "audio", "audiobytes", "summary", "e164", "frome164", "toe164", "fromnumber",
                      "tonumber", "msisdn", "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "contact", "contactname", "email", "dob", "birthdate", "cardpan", "pan", "cvv",
                      "otp", "ssn", "iban", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token", "bearertoken", "accesstoken",
                         "credential", "password", "privatekey", "kmskey", "storageuri", "storageurl", "objecturi",
                         "objectkey", "signedurl", "downloadurl", "url", "baseurl", "uri", "bucket"]
RAW_PII_PATTERNS = [
    re.compile(r"\d{7,}"),
    re.compile(r"\+\d{6,}"),
    re.compile(r"\d{4}[\s-]\d{4}[\s-]\d{4}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\bTR\d{2}[\s]?\d"),
]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/test-sim.ts ile birebir) ──────────────────────

def sorted_suites(view):
    return sorted(view["suites"], key=lambda s: CATEGORY_ORDER.index(s["category"]))


def sorted_regression(view):
    return sorted(view["regression"], key=lambda r: CATEGORY_ORDER.index(r["category"]))


def scenarios_by_category(view, cat):
    return [s for s in view["scenarios"] if s["category"] == cat]


def total_scenarios(view):
    return len(view["scenarios"])


def status_count(view, status):
    return sum(1 for s in view["scenarios"] if s["status"] == status)


def passed_count(view):
    return status_count(view, "pass")


def failed_count(view):
    return status_count(view, "fail")


def blocked_count(view):
    return status_count(view, "blocked")


def overall_pass_rate(view):
    t = total_scenarios(view)
    return 0.0 if t <= 0 else passed_count(view) / t


def mean_score(view):
    t = total_scenarios(view)
    return 0.0 if t <= 0 else sum(s["score"] for s in view["scenarios"]) / t


def category_mean_score(view, cat):
    xs = scenarios_by_category(view, cat)
    return 0.0 if not xs else sum(s["score"] for s in xs) / len(xs)


def suite_pass_rate(s):
    return 0.0 if s["total"] <= 0 else s["passed"] / s["total"]


def adversarial_failures(view):
    return sum(1 for s in scenarios_by_category(view, "adversarial") if s["status"] != "pass")


def suite_totals_reconcile(view):
    if sum(s["total"] for s in view["suites"]) != total_scenarios(view):
        return False
    return all(s["total"] == len(scenarios_by_category(view, s["category"])) for s in view["suites"])


def suite_status_reconcile(view):
    for s in view["suites"]:
        xs = scenarios_by_category(view, s["category"])
        if not (s["passed"] == sum(1 for x in xs if x["status"] == "pass")
                and s["failed"] == sum(1 for x in xs if x["status"] == "fail")
                and s["blocked"] == sum(1 for x in xs if x["status"] == "blocked")
                and s["passed"] + s["failed"] + s["blocked"] == s["total"]):
            return False
    return True


def scenario_latency_within_target(s, target):
    return s["latencyMsP95"] <= target


def all_latencies_within_target(view, target=None):
    tgt = DEFAULT_TARGETS["latencyMsP95Target"] if target is None else target
    return all(scenario_latency_within_target(s, tgt) for s in view["scenarios"])


def regression_delta(item):
    return item["currentScore"] - item["baselineScore"]


def regression_detected(item, tol=None):
    t = DEFAULT_TARGETS["regressionTolerance"] if tol is None else tol
    return regression_delta(item) < -t


def has_regression(view, tol=None):
    return any(regression_detected(it, tol) for it in view["regression"])


def worst_regression(view):
    best = None
    for it in sorted_regression(view):
        if best is None or regression_delta(it) < regression_delta(best):
            best = it
    return best


def regression_current_reconciles(view, eps=0.005):
    return all(abs(it["currentScore"] - category_mean_score(view, it["category"])) <= eps for it in view["regression"])


def load_concurrency_met(view):
    return view["load"]["achievedConcurrency"] >= view["load"]["targetConcurrency"]


def load_cpu_within_budget(view):
    return view["load"]["cpuMsP95"] <= view["targets"]["cpuMsP95Budget"]


def load_mem_within_budget(view):
    return view["load"]["memMbP95"] <= view["targets"]["memMbP95Budget"]


def load_cpu_regression_pct(view):
    b = view["load"]["baselineCpuMsP95"]
    return 0.0 if b <= 0 else view["load"]["cpuMsP95"] / b - 1


def load_mem_regression_pct(view):
    b = view["load"]["baselineMemMbP95"]
    return 0.0 if b <= 0 else view["load"]["memMbP95"] / b - 1


def load_resource_regression(view, tol=None):
    t = DEFAULT_TARGETS["loadResourceTolerance"] if tol is None else tol
    return load_cpu_regression_pct(view) > t or load_mem_regression_pct(view) > t


def load_success_met(view):
    return view["load"]["successRate"] >= view["targets"]["successRateTarget"]


def gate_pass_rate_met(view):
    return overall_pass_rate(view) >= view["targets"]["gateMinPassRate"]


def gate_score_met(view):
    return mean_score(view) >= view["targets"]["gateMinScore"]


def gate_blockers(view):
    out = []
    if not gate_pass_rate_met(view):
        out.append("pass_rate")
    if not gate_score_met(view):
        out.append("score")
    if has_regression(view):
        out.append("regression")
    if adversarial_failures(view) > 0:
        out.append("adversarial")
    if load_resource_regression(view):
        out.append("load_resource")
    return out


def gate_state(view):
    return "pass" if len(gate_blockers(view)) == 0 else "blocked"


def gate_passes(view):
    return gate_state(view) == "pass"


def ratio_band(value, target, warn_ratio=WARN_RATIO):
    if value >= target:
        return "good"
    if value >= target * warn_ratio:
        return "warn"
    return "bad"


def lower_better_band(value, target, warn_ratio=WARN_RATIO):
    if value <= target:
        return "good"
    if value <= target / warn_ratio:
        return "warn"
    return "bad"


def band_tone(b):
    return {"good": "success", "warn": "warning", "bad": "danger"}[b]


def ratio_tone(value, target):
    return band_tone(ratio_band(value, target))


def lower_better_tone(value, target):
    return band_tone(lower_better_band(value, target))


def status_tone(s):
    return {"pass": "success", "fail": "danger", "blocked": "warning"}[s]


def category_tone(c):
    return {"happy": "neutral", "edge": "info", "adversarial": "info", "robustness": "neutral"}[c]


def gate_tone(g):
    return "success" if g == "pass" else "danger"


def regression_tone(item, tol=None):
    if regression_detected(item, tol):
        return "danger"
    if regression_delta(item) < 0:
        return "warning"
    return "success"


def regression_dir(item):
    d = regression_delta(item)
    if d > TREND_FLAT_EPS:
        return "up"
    if d < -TREND_FLAT_EPS:
        return "down"
    return "flat"


def assert_no_forbidden_keys(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/nesne-depo URI alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_forbidden_keys(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            low = k.lower()
            if low in FORBIDDEN_PII_KEYS or low in FORBIDDEN_SECRET_KEYS:
                return f"{path}.{k}"
            hit = assert_no_forbidden_keys(v, f"{path}.{k}")
            if hit:
                return hit
    return None


def assert_redaction_clean(node, path="$"):
    """Herhangi bir string değerde ham PII deseni bulursa (path) döndürür; yoksa None."""
    if isinstance(node, str):
        for re_ in RAW_PII_PATTERNS:
            if re_.search(node):
                return path
        return None
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_redaction_clean(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            hit = assert_redaction_clean(v, f"{path}.{k}")
            if hit:
                return hit
    return None


def assert_safe(view):
    """İki katmanı birlikte uygular; ilk ihlali (path) döndürür, yoksa None."""
    return assert_no_forbidden_keys(view) or assert_redaction_clean(view)


# ── i18n yardımcıları ─────────────────────────────────────────────────────────────

def resolve(cat, dotted):
    cur = cat
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return None
    return cur if isinstance(cur, str) else None


def placeholders(s):
    return set(re.findall(r"\{(\w+)\}", s or ""))


def _extract_data_fields(ts):
    """test-sim.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── validate ───────────────────────────────────────────────────────────────────────

def cmd_validate():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    spec = load_json(SPEC_PATH)
    page = read_text(PAGE_PATH) if os.path.isfile(PAGE_PATH) else ""
    data = read_text(DATA_PATH) if os.path.isfile(DATA_PATH) else ""
    tr = load_json(TR_PATH)
    en = load_json(EN_PATH)

    # S0/S1 — ekran sayfası mevcut + işaretli + iskelet değil
    chk(spec.get("wbs") == "13.4.16", "S0 spec.wbs=13.4.16")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/test/page.tsx mevcut")
    chk('data-screen="A-16"' in page, 'S1 data-screen="A-16" işaretli')
    chk("İskelet ekran — A-16" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/test-sim" in page, "S2 veri seam (lib/tenant/test-sim) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    chk("formatNumber" in page, "S2 formatNumber (sayı locale-duyarlı)")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "EmptyState"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür ETİKET metni i18n'den (screen.a16.*); hardcoded TR/EN ETİKET cümlesi yok
    chk("screen.a16." in page, "S3 screen.a16.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded etiket metni yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı İKİ KATMAN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/test-sim.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("RAW_PII_PATTERNS" in data, "S4 RAW_PII_PATTERNS (içerik redaction deseni) tanımlı")
    chk("assertNoForbiddenKeys" in data, "S4 assertNoForbiddenKeys (yapısal) guard tanımlı")
    chk("assertRedactionClean" in data, "S4 assertRedactionClean (içerik) guard tanımlı")
    chk(re.search(r"assertSafe\(view\)", data) is not None, "S4 getTestView assertSafe çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("callref", "text", "recording", "e164", "cardpan")), "S4 gerçek-çağrı callRef/transkript/ham ses/numara/kart yasak (A-16 sentetik panodur; BRD §17.7)")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("storageuri", "url", "kmskey", "signedurl")), "S4 nesne-depo URI/sır yasak (NFR 10.6)")
    leak = assert_no_forbidden_keys({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/URI alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-TST-* karşılanır
    a16 = tr.get("screen", {}).get("a16", {})
    sec = a16.get("section", {})
    for s in ("summary", "suites", "scenarios", "regression", "gate", "load"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("sortedSuites" in data and "suitePassRate" in data and "suiteTotalsReconcile" in data and "suiteStatusReconcile" in data and set(CATEGORY_ORDER).issubset(a16.get("category", {}).keys()), "S5 suite/kategori kırılımı (FR-TST-003/007)")
    chk("overallPassRate" in data and "meanScore" in data and "scenariosByCategory" in data and "statusCount" in data, "S5 senaryo/persona simülasyonu (FR-TST-001/002)")
    chk("regressionDelta" in data and "regressionDetected" in data and "hasRegression" in data and "regressionCurrentReconciles" in data, "S5 regresyon aday vs baseline (FR-TST-004 / FR-ANA-010)")
    chk("gateBlockers" in data and "gateState" in data and "gatePasses" in data and all(b in a16.get("blocker", {}) for b in GATE_BLOCKER_ORDER), "S5 promotion gate (FR-TST-005)")
    chk("loadConcurrencyMet" in data and "loadCpuWithinBudget" in data and "loadMemWithinBudget" in data and "loadResourceRegression" in data and all(x in a16.get("load_kpi", {}) for x in ("concurrency", "cpu", "mem", "success")), "S5 yük testi + yük altı kaynak (FR-TST-006/009)")
    chk("syntheticData" in data and "synthetic" in a16, "S5 sentetik test verisi (FR-TST-008)")
    chk(set(TREND_ORDER).issubset(a16.get("trend", {}).keys()), "S5 trend/regresyon yön etiketleri (up/down/flat)")
    chk("gate_blocked" in a16.get("alert", {}) and "regression" in a16.get("alert", {}) and "load_resource" in a16.get("alert", {}), "S5 gate/regresyon/kaynak uyarıları (FR-TST-005/004/009)")
    chk("robustness" in a16.get("category", {}) and "adversarial" in a16.get("category", {}), "S5 robustness (FR-TST-007) + adversarial (FR-TST-003) kategorileri")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a16.{rk}"
        vt, ve = resolve(tr, full), resolve(en, full)
        if vt is None:
            missing_tr.append(rk)
        elif not vt.strip():
            empty.append(("tr", rk))
        if ve is None:
            missing_en.append(rk)
        elif not ve.strip():
            empty.append(("en", rk))
        if vt is not None and ve is not None and placeholders(vt) != placeholders(ve):
            ph_mismatch.append(rk)
    chk(not missing_tr, f"S6 TR referans anahtarları tam (eksik={missing_tr})")
    chk(not missing_en, f"S6 EN referans anahtarları tam (eksik={missing_en})")
    chk(not empty, f"S6 boş değer yok (boş={empty})")
    chk(not ph_mismatch, f"S6 TR↔EN placeholder parity (uyumsuz={ph_mismatch})")
    for key, phs in spec.get("placeholders", {}).items():
        vt = resolve(tr, f"screen.a16.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedSuites", "sortedRegression", "suitePassRate", "totalScenarios", "passedCount", "failedCount",
               "blockedCount", "overallPassRate", "meanScore", "categoryMeanScore", "adversarialFailures",
               "suiteTotalsReconcile", "suiteStatusReconcile", "scenarioLatencyWithinTarget", "allLatenciesWithinTarget",
               "regressionDelta", "regressionDetected", "hasRegression", "worstRegression", "regressionCurrentReconciles",
               "loadConcurrencyMet", "loadCpuWithinBudget", "loadMemWithinBudget", "loadCpuRegressionPct",
               "loadMemRegressionPct", "loadResourceRegression", "loadSuccessMet", "gatePassRateMet", "gateScoreMet",
               "gateBlockers", "gateState", "gatePasses", "ratioBand", "lowerBetterBand", "ratioTone", "lowerBetterTone",
               "statusTone", "categoryTone", "gateTone", "regressionTone", "regressionDir"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("CATEGORY_ORDER", "STATUS_ORDER", "BAND_ORDER", "TREND_ORDER", "GATE_BLOCKER_ORDER")), "S7 *_ORDER sabitleri tanımlı")
    chk(all(c in data for c in ("DEFAULT_TARGETS", "WARN_RATIO", "TREND_FLAT_EPS", "MASK_TOKEN")), "S7 hedef/tolerans sabitleri tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "twilio.com", "telnyx.com", "datadog.com", "secret=", "splunk", "s3.amazonaws.com"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── check ────────────────────────────────────────────────────────────────────────

def _base_view():
    return {
        "generatedAt": "2026-06-18T09:00:00.000Z", "tenantRef": "TEN-2048", "tenantName": "Kuzey Sigorta A.Ş.",
        "agentRef": "AG-CALL", "agentName": "Tahsilat Asistanı", "candidateVersion": "v7-draft", "baselineVersion": "v6",
        "environment": "staging", "syntheticData": True,
        "targets": dict(DEFAULT_TARGETS),
        "suites": [
            {"category": "happy", "total": 3, "passed": 3, "failed": 0, "blocked": 0},
            {"category": "edge", "total": 2, "passed": 1, "failed": 1, "blocked": 0},
            {"category": "adversarial", "total": 2, "passed": 2, "failed": 0, "blocked": 0},
            {"category": "robustness", "total": 2, "passed": 2, "failed": 0, "blocked": 0},
        ],
        "scenarios": [
            {"scenarioRef": "SC-H1", "name": "Bakiye sorgulama", "category": "happy", "persona": "Sabırlı müşteri", "status": "pass", "score": 0.96, "turns": 6, "latencyMsP95": 980},
            {"scenarioRef": "SC-H2", "name": "Randevu oluşturma", "category": "happy", "persona": "Net talepli müşteri", "status": "pass", "score": 0.93, "turns": 8, "latencyMsP95": 1040},
            {"scenarioRef": "SC-H3", "name": "Genel bilgi", "category": "happy", "persona": "Bilgi arayan", "status": "pass", "score": 0.95, "turns": 5, "latencyMsP95": 920},
            {"scenarioRef": "SC-E1", "name": "Eksik bilgi / sessizlik", "category": "edge", "persona": "Kararsız müşteri", "status": "pass", "score": 0.88, "turns": 9, "latencyMsP95": 1120},
            {"scenarioRef": "SC-E2", "name": "Çoklu niyet tek turda", "category": "edge", "persona": "Aceleci müşteri", "status": "fail", "score": 0.62, "turns": 11, "latencyMsP95": 1180},
            {"scenarioRef": "SC-A1", "name": "Prompt injection denemesi", "category": "adversarial", "persona": "Saldırgan kullanıcı", "status": "pass", "score": 0.9, "turns": 7, "latencyMsP95": 1010},
            {"scenarioRef": "SC-A2", "name": "Sosyal mühendislik (veri çıkarma)", "category": "adversarial", "persona": "Manipülatif kullanıcı", "status": "pass", "score": 0.86, "turns": 8, "latencyMsP95": 1090},
            {"scenarioRef": "SC-R1", "name": "Arka plan gürültüsü", "category": "robustness", "persona": "Gürültülü ortam", "status": "pass", "score": 0.84, "turns": 7, "latencyMsP95": 1130},
            {"scenarioRef": "SC-R2", "name": "Aksan + kesinti (barge-in)", "category": "robustness", "persona": "Aksanlı / sözünü kesen", "status": "pass", "score": 0.82, "turns": 8, "latencyMsP95": 1150},
        ],
        "regression": [
            {"category": "happy", "baselineScore": 0.95, "currentScore": 0.947},
            {"category": "edge", "baselineScore": 0.78, "currentScore": 0.75},
            {"category": "adversarial", "baselineScore": 0.85, "currentScore": 0.88},
            {"category": "robustness", "baselineScore": 0.8, "currentScore": 0.83},
        ],
        "load": {
            "targetConcurrency": 250, "achievedConcurrency": 250, "cps": 25, "successRate": 0.998,
            "cpuMsP95": 185, "memMbP95": 13.6, "baselineCpuMsP95": 180, "baselineMemMbP95": 13.4,
        },
    }


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    tg = v["targets"]

    chk([s["category"] for s in sorted_suites(v)] == CATEGORY_ORDER, "sortedSuites CATEGORY_ORDER")
    chk([r["category"] for r in sorted_regression(v)] == CATEGORY_ORDER, "sortedRegression CATEGORY_ORDER")
    chk(total_scenarios(v) == 9, "totalScenarios=9")
    chk(passed_count(v) == 8 and failed_count(v) == 1 and blocked_count(v) == 0, "pass/fail/blocked = 8/1/0")
    chk(abs(overall_pass_rate(v) - 8 / 9) < 1e-9, "overallPassRate=8/9≈0.889")
    chk(abs(mean_score(v) - 7.76 / 9) < 1e-9, "meanScore=7.76/9≈0.862")
    chk(abs(category_mean_score(v, "happy") - 2.84 / 3) < 1e-9, "categoryMeanScore happy")

    chk(suite_totals_reconcile(v) is True, "suiteTotalsReconcile (Σ suite.total = senaryo; FR-TST-003)")
    chk(suite_status_reconcile(v) is True, "suiteStatusReconcile (passed/failed/blocked = kategori sayımı)")
    chk(abs(suite_pass_rate(v["suites"][0]) - 1.0) < 1e-9, "suitePassRate happy=1.0")
    chk(adversarial_failures(v) == 0, "adversarialFailures=0 (healthy)")
    chk(all_latencies_within_target(v) is True, "allLatenciesWithinTarget (≤1200; NFR 10.1)")

    chk(abs(regression_delta(v["regression"][1]) - (0.75 - 0.78)) < 1e-9, "regressionDelta edge=-0.03")
    chk(regression_detected(v["regression"][1]) is False, "regressionDetected edge=False (−0.03 > −0.05 tolerans)")
    chk(has_regression(v) is False, "hasRegression=False (healthy; FR-TST-004)")
    chk(worst_regression(v)["category"] == "edge", "worstRegression=edge (en negatif delta)")
    chk(regression_current_reconciles(v) is True, "regressionCurrentReconciles (current≈kategori ortalaması; FR-ANA-010)")

    chk(load_concurrency_met(v) is True, "loadConcurrencyMet (250≥250; FR-TST-006)")
    chk(load_cpu_within_budget(v) is True, "loadCpuWithinBudget (185≤250)")
    chk(load_mem_within_budget(v) is True, "loadMemWithinBudget (13.6≤15; FR-RES-016/NFR 10.2)")
    chk(load_resource_regression(v) is False, "loadResourceRegression=False (FR-TST-009)")
    chk(load_success_met(v) is True, "loadSuccessMet (0.998≥0.99)")

    chk(gate_pass_rate_met(v) is True, "gatePassRateMet (0.889≥0.85)")
    chk(gate_score_met(v) is True, "gateScoreMet (0.862≥0.8)")
    chk(gate_blockers(v) == [], "gateBlockers=[] (healthy)")
    chk(gate_state(v) == "pass", "gateState=pass (FR-TST-005)")
    chk(gate_passes(v) is True, "gatePasses=True")

    # bant + ton eşlemeleri
    chk(ratio_band(0.889, 0.85) == "good" and ratio_band(0.78, 0.85) == "warn" and ratio_band(0.5, 0.85) == "bad", "ratioBand pass-rate (yüksek daha iyi)")
    chk(lower_better_band(185, 250) == "good" and lower_better_band(260, 250) == "warn" and lower_better_band(340, 250) == "bad", "lowerBetterBand CPU (düşük daha iyi)")
    chk(status_tone("pass") == "success" and status_tone("fail") == "danger" and status_tone("blocked") == "warning", "statusTone")
    chk(category_tone("adversarial") == "info" and category_tone("happy") == "neutral", "categoryTone")
    chk(gate_tone("pass") == "success" and gate_tone("blocked") == "danger", "gateTone")
    chk(regression_tone(v["regression"][1]) == "warning" and regression_tone(v["regression"][2]) == "success", "regressionTone (küçük düşüş=warning / iyileşme=success)")
    chk(regression_dir(v["regression"][2]) == "up" and regression_dir(v["regression"][1]) == "down", "regressionDir (iyileşme=up / gerileme=down)")

    # İKİ KATMAN guard — pozitif
    chk(assert_safe(v) is None, "assertSafe sentetik görünüm İZİNLİ")
    chk(assert_no_forbidden_keys({"x": {"callRef": "..."}}) == "$.x.callRef", "L1 gerçek-çağrı callRef yakalanır (A-16 sentetik panodur)")
    chk(assert_no_forbidden_keys({"x": {"customerName": "..."}}) == "$.x.customerName", "L1 müşteri adı yakalanır")
    chk(assert_no_forbidden_keys({"x": {"storageUri": "..."}}) == "$.x.storageUri", "L1 nesne-depo URI yakalanır (NFR 10.6)")
    chk(assert_redaction_clean({"persona": "müşteri 05321234567"}) is not None, "L2 ham telefon yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"persona": "Aksanlı / sözünü kesen"}) is None, "L2 sentetik persona etiketi temiz")
    chk(assert_redaction_clean({"score": 0.86}) is None, "L2 skor SAYISI (number) taranmaz")

    # samples doğrulaması
    for name in ("test-healthy.json", "test-degraded.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        chk(total_scenarios(snp) == exp.get("total_scenarios"), f"{name} total_scenarios={exp.get('total_scenarios')}")
        chk(abs(overall_pass_rate(snp) - exp.get("pass_rate")) < 0.01, f"{name} pass_rate≈{exp.get('pass_rate')}")
        chk(suite_totals_reconcile(snp) is True, f"{name} suiteTotalsReconcile (FR-TST-003)")
        chk(suite_status_reconcile(snp) is True, f"{name} suiteStatusReconcile")
        chk(regression_current_reconciles(snp) is True, f"{name} regressionCurrentReconciles (FR-ANA-010)")
        chk(has_regression(snp) == exp.get("has_regression"), f"{name} has_regression={exp.get('has_regression')}")
        chk(load_resource_regression(snp) == exp.get("load_resource_regression"), f"{name} load_resource_regression={exp.get('load_resource_regression')}")
        chk(gate_state(snp) == exp.get("gate_state"), f"{name} gate_state={exp.get('gate_state')}")
        chk(sorted(gate_blockers(snp)) == sorted(exp.get("gate_blockers", [])), f"{name} gate_blockers={exp.get('gate_blockers')}")
        chk(assert_safe(snp) is None, f"{name} İKİ KATMAN guard temiz (HİJYEN+REDACTION)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\ncheck: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── selftest ────────────────────────────────────────────────────────────────────

def cmd_selftest():
    results = []

    def expect(cond, label):
        results.append((bool(cond), label))

    v = _base_view()

    # pozitif (sağlıklı koşu)
    expect(suite_totals_reconcile(v) is True, "pos suite toplamı uzlaşır (FR-TST-003)")
    expect(suite_status_reconcile(v) is True, "pos suite durum sayımı uzlaşır")
    expect(has_regression(v) is False, "pos regresyon yok (FR-TST-004)")
    expect(gate_passes(v) is True, "pos promotion gate geçer (FR-TST-005)")
    expect(load_resource_regression(v) is False, "pos yük altı kaynak regresyonu yok (FR-TST-009)")
    expect(all_latencies_within_target(v) is True, "pos tüm senaryo gecikmesi hedef içinde (NFR 10.1)")

    # sınır: boş koşu
    empty = dict(v, suites=[], scenarios=[], regression=[])
    expect(total_scenarios(empty) == 0, "sınır boş koşu senaryo=0")
    expect(overall_pass_rate(empty) == 0.0, "sınır boş koşu geçme oranı=0 (sıfır bölme yok)")
    expect(mean_score(empty) == 0.0, "sınır boş koşu ortalama skor=0")
    expect(has_regression(empty) is False, "sınır boş koşu regresyon yok")
    expect(worst_regression(empty) is None, "sınır boş regresyon worst=None")
    expect(suite_totals_reconcile(empty) is True, "sınır boş koşu suite uzlaşır (0=0)")

    # FR-TST-003: suite toplamı senaryo sayımıyla çelişirse yakalanır
    suite_bad = dict(v, suites=[dict(s) for s in v["suites"]])
    suite_bad["suites"][0] = dict(suite_bad["suites"][0], total=9)
    expect(suite_totals_reconcile(suite_bad) is False, "suite.total ≠ kategori sayımı → uzlaşmaz yakalanır (FR-TST-003)")
    status_bad = dict(v, suites=[dict(s) for s in v["suites"]])
    status_bad["suites"][1] = dict(status_bad["suites"][1], passed=2, failed=0)
    expect(suite_status_reconcile(status_bad) is False, "suite passed/failed ≠ senaryo → uzlaşmaz yakalanır")

    # FR-TST-005: düşük geçme oranı / skor gate'i engeller
    low_pass = dict(v, scenarios=[dict(s) for s in v["scenarios"]])
    low_pass["scenarios"] = [dict(s, status="fail", score=0.4) for s in low_pass["scenarios"][:6]] + low_pass["scenarios"][6:]
    expect(gate_pass_rate_met(low_pass) is False, "geçme oranı eşik altı yakalanır (FR-TST-005)")
    expect(gate_state(low_pass) == "blocked", "düşük geçme oranı → gate blocked")
    expect("pass_rate" in gate_blockers(low_pass), "blocker.pass_rate listelenir")

    # FR-TST-005: adversarial başarısızlığı kritik blocker
    adv_fail = dict(v, scenarios=[dict(s) for s in v["scenarios"]])
    adv_fail["scenarios"] = [dict(s, status="fail") if s["category"] == "adversarial" and s["scenarioRef"] == "SC-A2" else s for s in adv_fail["scenarios"]]
    expect(adversarial_failures(adv_fail) == 1, "adversarial başarısızlığı sayılır")
    expect("adversarial" in gate_blockers(adv_fail), "adversarial fail → kritik blocker (FR-TST-005)")
    expect(gate_state(adv_fail) == "blocked", "adversarial fail → gate blocked")

    # FR-TST-004: regresyon toleransı aşan düşüş gate'i engeller
    regr = dict(v, regression=[dict(r) for r in v["regression"]])
    regr["regression"][1] = dict(regr["regression"][1], currentScore=0.6)  # 0.6-0.78=-0.18 < -0.05
    expect(regression_detected(regr["regression"][1]) is True, "toleransı aşan düşüş → regresyon (FR-TST-004)")
    expect(has_regression(regr) is True, "hasRegression yakalanır")
    expect("regression" in gate_blockers(regr), "regression → gate blocker (FR-TST-005)")

    # FR-TST-009: yük altı kaynak regresyonu blocker
    load_regr = dict(v, load=dict(v["load"], cpuMsP95=230))  # 230/180-1=0.278 > 0.1
    expect(load_cpu_regression_pct(load_regr) > 0.1, "CPU baseline'ı tolerans üstünde aşar")
    expect(load_resource_regression(load_regr) is True, "loadResourceRegression yakalanır (FR-TST-009)")
    expect("load_resource" in gate_blockers(load_regr), "load_resource → gate blocker")

    # FR-TST-006: yük bütçe/eş zamanlılık aşımı
    low_conc = dict(v, load=dict(v["load"], achievedConcurrency=190))
    expect(load_concurrency_met(low_conc) is False, "hedef eş zamanlılığa ulaşılamaz yakalanır (FR-TST-006)")
    mem_over = dict(v, load=dict(v["load"], memMbP95=18.5))
    expect(load_mem_within_budget(mem_over) is False, "yük altı bellek 18.5>15 → bütçe aşımı (FR-RES-016/NFR 10.2)")

    # bant sınırları
    expect(ratio_band(0.85, 0.85) == "good", "ratioBand sınırda (=hedef) good")
    expect(lower_better_band(250, 250) == "good", "lowerBetterBand sınırda (=hedef) good")
    expect(ratio_band(0.77, 0.85) == "warn", "ratioBand hedef·0.9 üstü warn")

    # İKİ KATMAN guard — negatif
    expect(assert_no_forbidden_keys({"x": {"transcriptText": "..."}}) is not None, "L1 transkript metni yakalanır")
    expect(assert_no_forbidden_keys({"x": {"audioBytes": "x"}}) is not None, "L1 audioBytes yakalanır")
    expect(assert_no_forbidden_keys({"x": {"signedUrl": "..."}}) is not None, "L1 signedUrl yakalanır (NFR 10.6)")
    expect(assert_no_forbidden_keys({"x": {"e164": "..."}}) is not None, "L1 ham numara (e164) yakalanır")
    expect(assert_redaction_clean({"c": "TR12 3456"}) is not None, "L2 IBAN deseni yakalanır")
    expect(assert_redaction_clean({"c": "kart 4111 1111 1111"}) is not None, "L2 kart bloğu yakalanır (FR-REC-005)")
    expect(assert_redaction_clean({"c": "Maskeli [•••], %71 oran."}) is None, "L2 maskeli + kısa yüzde temiz")
    leaky = {"scenarios": [{"persona": "ara: 05551234567"}]}
    expect(assert_safe(leaky) is not None, "kritik ham telefon içeren persona yakalanır (REDACTION ihlali)")

    # placeholder ayrıştırma
    expect(placeholders("hedef ≥%{target}") == {"target"}, "placeholder parse")
    expect(placeholders("{passed} geçti · {failed} kaldı · {blocked} bloke") == {"passed", "failed", "blocked"}, "placeholder parse çoklu")

    # spec tutarlılık
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")
    expect(spec["categories"] == CATEGORY_ORDER, "spec categories = CATEGORY_ORDER")
    expect(spec["statuses"] == STATUS_ORDER, "spec statuses = STATUS_ORDER")
    expect(spec["gate_blockers"] == GATE_BLOCKER_ORDER, "spec gate_blockers = GATE_BLOCKER_ORDER")
    expect(spec["bands"] == BAND_ORDER, "spec bands = BAND_ORDER")
    expect(spec["trends"] == TREND_ORDER, "spec trends = TREND_ORDER")
    expect(spec["default_targets"] == DEFAULT_TARGETS, "spec default_targets = DEFAULT_TARGETS")
    expect(spec["warn_ratio"] == WARN_RATIO, "spec warn_ratio")
    expect(spec["mask_token"] == MASK_TOKEN, "spec mask_token = MASK_TOKEN")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "TestView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "agentRef": "str (test edilen agent — tenant-içi)",
            "agentName": "str (agent görünen adı)",
            "candidateVersion": "str (aday sürüm)", "baselineVersion": "str (baseline sürüm)",
            "environment": "str (draft/test/staging — FR-AGT-005)", "syntheticData": "bool (FR-TST-008)",
            "targets": {"gateMinPassRate": "float", "gateMinScore": "float", "regressionTolerance": "float", "loadConcurrencyTarget": "int", "cpuMsP95Budget": "int", "memMbP95Budget": "int (NFR 10.2/FR-RES-016)", "latencyMsP95Target": "int (NFR 10.1)", "loadResourceTolerance": "float", "successRateTarget": "float"},
            "suites": [{"category": "|".join(CATEGORY_ORDER) + " (FR-TST-003/007)", "total": "int", "passed": "int", "failed": "int", "blocked": "int"}],
            "scenarios": [{"scenarioRef": "str", "name": "str", "category": "|".join(CATEGORY_ORDER), "persona": "str (sentetik etiket — FR-TST-002)", "status": "|".join(STATUS_ORDER), "score": "float (0..1)", "turns": "int", "latencyMsP95": "num (ms)"}],
            "regression": [{"category": "|".join(CATEGORY_ORDER), "baselineScore": "float", "currentScore": "float (FR-TST-004/FR-ANA-010)"}],
            "load": {"targetConcurrency": "int", "achievedConcurrency": "int", "cps": "num", "successRate": "float", "cpuMsP95": "num", "memMbP95": "num", "baselineCpuMsP95": "num", "baselineMemMbP95": "num (FR-TST-006/009)"}
        },
        "categories": CATEGORY_ORDER, "statuses": STATUS_ORDER, "gate_blockers": GATE_BLOCKER_ORDER,
        "bands": BAND_ORDER, "trends": TREND_ORDER,
        "default_targets": DEFAULT_TARGETS, "warn_ratio": WARN_RATIO, "trend_flat_eps": TREND_FLAT_EPS, "mask_token": MASK_TOKEN,
        "invariants": "suiteTotalsReconcile: Σ suite.total = senaryo adedi + suite.total = kategori sayımı (FR-TST-003). suiteStatusReconcile: passed/failed/blocked = kategori durum sayımı. overallPassRate=pass/total; meanScore=Σ score/total. hasRegression: herhangi kategoride currentScore-baselineScore < -tolerans (FR-TST-004). regressionCurrentReconciles: currentScore ≈ kategori senaryo ortalaması (FR-ANA-010). loadResourceRegression: cpu/mem baseline'ı tolerans üstünde aşar (FR-TST-009). gateState=pass ⇔ gateBlockers boş (pass_rate/score/regression/adversarial/load_resource — FR-TST-005).",
        "hijyen": "A-16 yalnız SENTETİK test/simülasyon metriği gösterir (Tier A) → break-glass gerekmez; gerçek çağrı içeriği/transkript/PII TAŞIMAZ (FR-TST-008). İKİ KATMAN guard: (1) assertNoForbiddenKeys — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni/e164/müşteri/kart-OTP) + gerçek-çağrı `callRef` + sır/credential/nesne-depo URI alan ADI YOK. (2) assertRedactionClean — hiçbir STRING değer ham PII DESENİ taşımaz (persona dahil); skor/kaynak SAYILARI taranmaz (FR-REC-004/005). Koşu/promote derin aksiyon (test:run / agent:version:manage — API §8.1); nihai çalıştırma + yetki + audit backend (SAD §14.4.1).",
        "rbac": "operations_manager=Düzenle · conversation_designer=Yönet · qa_analyst=Görüntüle · human_agent=— (BRD §17.6); tenant_owner kural 17.7 ile Yönet. Permission-key: test:run (API §8.1)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a16_test_sim_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
