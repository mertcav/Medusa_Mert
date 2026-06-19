#!/usr/bin/env python3
# WBS 13.4.15 — A-15 "Maliyet & Kaynak Tüketimi" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (maliyet/agent/kaynak/density/seri/tone'lar/assertSafe) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (uzlaşı / bütçe / density / trend / İKİ KATMAN guard)
#   schema    — maliyet görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/cost.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a15-cost-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "cost", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "cost.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

COMPONENT_ORDER = ["stt", "llm", "tts", "telephony", "compute"]
RESOURCE_ORDER = ["cpuMs", "memMb"]
BAND_ORDER = ["good", "warn", "bad"]
TREND_ORDER = ["up", "down", "flat"]

DEFAULT_TARGETS = {
    "costPerCallMinor": 1200, "cpuMsP95": 250, "memMbP95": 15, "densityMin": 250,
    "densityStretch": 500, "cacheHit": 0.6, "smallModelRatio": 0.5, "idleReclaim": 0.6,
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


# ── SAF çekirdek aynası (lib/tenant/cost.ts ile birebir) ──────────────────────────

def sorted_components(view):
    return sorted(view["components"], key=lambda c: COMPONENT_ORDER.index(c["component"]))


def sorted_resources(view):
    return sorted(view["resources"], key=lambda r: RESOURCE_ORDER.index(r["metric"]))


def total_cost_minor(view):
    return sum(c["amountMinor"] for c in view["components"])


def component_amount(view, key):
    for c in view["components"]:
        if c["component"] == key:
            return c["amountMinor"]
    return 0


def component_share(view, key):
    t = total_cost_minor(view)
    return 0.0 if t <= 0 else component_amount(view, key) / t


def dominant_component(view):
    best = None
    for c in sorted_components(view):
        if best is None or c["amountMinor"] > best["amountMinor"]:
            best = c
    return best["component"] if best else None


def agent_total_minor(view):
    return sum(g["amountMinor"] for g in view["agents"])


def agent_calls_total(view):
    return sum(g["calls"] for g in view["agents"])


def agent_cost_reconciles(view):
    return agent_total_minor(view) == total_cost_minor(view)


def agent_calls_reconcile(view):
    return agent_calls_total(view) == view["totalCalls"]


def agent_cost_share(g, view):
    t = total_cost_minor(view)
    return 0.0 if t <= 0 else g["amountMinor"] / t


def agent_cost_per_call_minor(g):
    return 0.0 if g["calls"] <= 0 else g["amountMinor"] / g["calls"]


def cost_per_call_minor(view):
    return 0.0 if view["totalCalls"] <= 0 else total_cost_minor(view) / view["totalCalls"]


def cost_per_resolved_minor(view):
    return 0.0 if view["resolvedCalls"] <= 0 else total_cost_minor(view) / view["resolvedCalls"]


def cost_per_minute_minor(view):
    return 0.0 if view["billedMinutes"] <= 0 else total_cost_minor(view) / view["billedMinutes"]


def resolved_consistent(view):
    return view["resolvedCalls"] > 0 and view["resolvedCalls"] <= view["totalCalls"]


def resource_stat(view, metric):
    for r in view["resources"]:
        if r["metric"] == metric:
            return r
    return None


def resource_within_budget(view, metric):
    r = resource_stat(view, metric)
    return r["p95"] <= r["budget"] if r else False


def mem_within_budget(view):
    return resource_within_budget(view, "memMb")


def cpu_within_budget(view):
    return resource_within_budget(view, "cpuMs")


def resource_percentiles_consistent(view):
    return all(r["p95"] >= r["p50"] for r in view["resources"])


def density_meets_target(view, min_=None):
    return view["efficiency"]["density"] >= (DEFAULT_TARGETS["densityMin"] if min_ is None else min_)


def density_meets_stretch(view, stretch=None):
    return view["efficiency"]["density"] >= (DEFAULT_TARGETS["densityStretch"] if stretch is None else stretch)


def series_calls(view):
    return sum(p["calls"] for p in view["series"])


def series_cost_minor(view):
    return sum(p["amountMinor"] for p in view["series"])


def series_reconciles_calls(view):
    return len(view["series"]) == 0 or series_calls(view) == view["totalCalls"]


def series_reconciles_cost(view):
    return len(view["series"]) == 0 or series_cost_minor(view) == total_cost_minor(view)


def day_cost_per_call_minor(p):
    return 0.0 if p["calls"] <= 0 else p["amountMinor"] / p["calls"]


def series_trend(view, key, eps=TREND_FLAT_EPS):
    xs = view["series"]
    if len(xs) < 2:
        return "flat"

    def value_of(p):
        if key == "cost":
            return day_cost_per_call_minor(p)
        if key == "calls":
            return p["calls"]
        if key == "cpu":
            return p["cpuMsP95"]
        return p["memMbP95"]

    mid = len(xs) // 2
    first = xs[:mid]
    second = xs[len(xs) - mid:]

    def avg(arr):
        return 0.0 if not arr else sum(value_of(p) for p in arr) / len(arr)

    a, b = avg(first), avg(second)
    if a == 0:
        return "up" if b > 0 else "flat"
    rel = (b - a) / abs(a)
    if rel > eps:
        return "up"
    if rel < -eps:
        return "down"
    return "flat"


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


def component_tone(c):
    return {"stt": "info", "llm": "info", "tts": "info", "telephony": "neutral", "compute": "neutral"}[c]


def cost_trend_tone(d):
    return {"up": "danger", "down": "success", "flat": "neutral"}[d]


def volume_trend_tone(d):
    return {"up": "info", "down": "info", "flat": "neutral"}[d]


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
    """cost.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.15", "S0 spec.wbs=13.4.15")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/cost/page.tsx mevcut")
    chk('data-screen="A-15"' in page, 'S1 data-screen="A-15" işaretli')
    chk("İskelet ekran — A-15" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/cost" in page, "S2 veri seam (lib/tenant/cost) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    chk("formatCurrency" in page, "S2 formatCurrency (para birimi locale-duyarlı)")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "EmptyState"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür ETİKET metni i18n'den (screen.a15.*); hardcoded TR/EN ETİKET cümlesi yok
    chk("screen.a15." in page, "S3 screen.a15.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded etiket metni yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı İKİ KATMAN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/cost.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("RAW_PII_PATTERNS" in data, "S4 RAW_PII_PATTERNS (içerik redaction deseni) tanımlı")
    chk("assertNoForbiddenKeys" in data, "S4 assertNoForbiddenKeys (yapısal) guard tanımlı")
    chk("assertRedactionClean" in data, "S4 assertRedactionClean (içerik) guard tanımlı")
    chk(re.search(r"assertSafe\(view\)", data) is not None, "S4 getCostView assertSafe çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("callref", "text", "recording", "e164", "cardpan")), "S4 tek-çağrı callRef/transkript/ham ses/numara/kart yasak (A-15 agregat panodur; BRD §17.7)")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("storageuri", "url", "kmskey", "signedurl")), "S4 nesne-depo URI/sır yasak (NFR 10.6)")
    leak = assert_no_forbidden_keys({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/URI alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-ANA-007/013/011 karşılanır
    a15 = tr.get("screen", {}).get("a15", {})
    sec = a15.get("section", {})
    for s in ("summary", "components", "agents", "resources", "efficiency", "trend"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("totalCostMinor" in data and "componentShare" in data and "dominantComponent" in data and set(COMPONENT_ORDER).issubset(a15.get("component", {}).keys()), "S5 maliyet dağılımı bileşen/sağlayıcı (FR-ANA-007)")
    chk("agentCostReconciles" in data and "agentCallsReconcile" in data and "agentCostPerCallMinor" in data and "agents" in sec, "S5 agent bazında maliyet (FR-ANA-007)")
    chk("costPerCallMinor" in data and "costPerResolvedMinor" in data and "costPerMinuteMinor" in data, "S5 çağrı/çözülen/dakika başına maliyet (FR-ANA-007 + §18.1/18.2)")
    chk("resourceStat" in data and "resourceWithinBudget" in data and "memWithinBudget" in data and "cpuWithinBudget" in data and "densityMeetsTarget" in data and set(RESOURCE_ORDER).issubset(a15.get("metric", {}).keys()) and "concurrency" in a15.get("metric", {}), "S5 çağrı başına CPU/bellek/eşzamanlılık (FR-ANA-013)")
    chk(all(x in a15.get("eff", {}) for x in ("density", "cache", "small_model", "idle")), "S5 verimlilik/lean-runtime (density/cache/küçük-model/idle; NFR 10.2 / §18.2)")
    chk("seriesReconcilesCost" in data and "seriesReconcilesCalls" in data and "seriesTrend" in data and "export" in a15.get("action", {}), "S5 zaman serisi + ham veri export (FR-ANA-011)")
    chk(set(TREND_ORDER).issubset(a15.get("trend", {}).keys()), "S5 trend etiketleri (up/down/flat)")
    chk("cost_over" in a15.get("alert", {}) and "mem_over" in a15.get("alert", {}) and "density_low" in a15.get("alert", {}), "S5 maliyet/bellek/density uyarıları (BRD §18.2 / NFR 10.2)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a15.{rk}"
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
        vt = resolve(tr, f"screen.a15.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedComponents", "sortedResources", "totalCostMinor", "componentAmount", "componentShare",
               "dominantComponent", "agentTotalMinor", "agentCallsTotal", "agentCostReconciles", "agentCallsReconcile",
               "agentCostShare", "agentCostPerCallMinor", "costPerCallMinor", "costPerResolvedMinor",
               "costPerMinuteMinor", "resolvedConsistent", "resourceStat", "resourceWithinBudget", "memWithinBudget",
               "cpuWithinBudget", "resourcePercentilesConsistent", "densityMeetsTarget", "densityMeetsStretch",
               "seriesCalls", "seriesCostMinor", "seriesReconcilesCalls", "seriesReconcilesCost", "dayCostPerCallMinor",
               "seriesTrend", "ratioBand", "lowerBetterBand", "ratioTone", "lowerBetterTone", "componentTone",
               "costTrendTone", "volumeTrendTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("COMPONENT_ORDER", "RESOURCE_ORDER", "BAND_ORDER", "TREND_ORDER")), "S7 *_ORDER sabitleri tanımlı")
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
        "currency": "TRY",
        "period": {"from": "2026-06-11", "to": "2026-06-17", "label": "Son 7 gün"},
        "targets": dict(DEFAULT_TARGETS),
        "totalCalls": 7600, "resolvedCalls": 5400, "billedMinutes": 22450,
        "components": [
            {"component": "stt", "amountMinor": 1560000}, {"component": "llm", "amountMinor": 3150000},
            {"component": "tts", "amountMinor": 1320000}, {"component": "telephony", "amountMinor": 2010000},
            {"component": "compute", "amountMinor": 700000},
        ],
        "agents": [
            {"agentRef": "AG-CALL", "agentName": "Tahsilat Asistanı", "calls": 4200, "amountMinor": 4830000},
            {"agentRef": "AG-APPT", "agentName": "Randevu Botu", "calls": 2400, "amountMinor": 2510000},
            {"agentRef": "AG-INFO", "agentName": "Bilgi Hattı", "calls": 1000, "amountMinor": 1400000},
        ],
        "resources": [
            {"metric": "cpuMs", "p50": 95, "p95": 180, "budget": 250},
            {"metric": "memMb", "p50": 9, "p95": 13.4, "budget": 15},
        ],
        "efficiency": {"density": 540, "cacheHitRatio": 0.64, "smallModelTurnRatio": 0.58, "idleReclaimRatio": 0.72},
        "series": [
            {"date": "2026-06-11", "calls": 1080, "amountMinor": 1242000, "cpuMsP95": 175, "memMbP95": 13.2},
            {"date": "2026-06-12", "calls": 1120, "amountMinor": 1288000, "cpuMsP95": 178, "memMbP95": 13.4},
            {"date": "2026-06-13", "calls": 940, "amountMinor": 1081000, "cpuMsP95": 180, "memMbP95": 13.1},
            {"date": "2026-06-14", "calls": 760, "amountMinor": 874000, "cpuMsP95": 176, "memMbP95": 12.9},
            {"date": "2026-06-15", "calls": 1210, "amountMinor": 1391000, "cpuMsP95": 182, "memMbP95": 13.5},
            {"date": "2026-06-16", "calls": 1190, "amountMinor": 1369000, "cpuMsP95": 179, "memMbP95": 13.3},
            {"date": "2026-06-17", "calls": 1300, "amountMinor": 1495000, "cpuMsP95": 180, "memMbP95": 13.4},
        ],
    }


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    tg = v["targets"]

    chk([c["component"] for c in sorted_components(v)] == COMPONENT_ORDER, "sortedComponents COMPONENT_ORDER")
    chk([r["metric"] for r in sorted_resources(v)] == RESOURCE_ORDER, "sortedResources RESOURCE_ORDER")
    chk(total_cost_minor(v) == 8740000, "totalCostMinor=8.740.000 (Σ bileşen; FR-ANA-007)")
    chk(component_amount(v, "llm") == 3150000, "componentAmount llm=3.150.000")
    chk(abs(component_share(v, "llm") - 3150000 / 8740000) < 1e-9, "componentShare llm=amount/total")
    chk(dominant_component(v) == "llm", "dominantComponent=llm (en büyük sürücü)")

    chk(agent_total_minor(v) == 8740000, "agentTotalMinor=8.740.000")
    chk(agent_calls_total(v) == 7600, "agentCallsTotal=7600")
    chk(agent_cost_reconciles(v) is True, "agentCostReconciles (agent toplamı = dönem; FR-ANA-007)")
    chk(agent_calls_reconcile(v) is True, "agentCallsReconcile (agent çağrı toplamı = totalCalls)")
    chk(abs(agent_cost_per_call_minor(v["agents"][0]) - 4830000 / 4200) < 1e-9, "agentCostPerCallMinor AG-CALL")

    chk(abs(cost_per_call_minor(v) - 8740000 / 7600) < 1e-9, "costPerCallMinor=total/calls (≈1150)")
    chk(abs(cost_per_resolved_minor(v) - 8740000 / 5400) < 1e-9, "costPerResolvedMinor=total/resolved (§18.1)")
    chk(abs(cost_per_minute_minor(v) - 8740000 / 22450) < 1e-9, "costPerMinuteMinor=total/minutes (§18.2)")
    chk(cost_per_resolved_minor(v) > cost_per_call_minor(v), "çözülen-başı > çağrı-başı (resolved ≤ total)")
    chk(resolved_consistent(v) is True, "resolvedConsistent (0 < resolved ≤ total)")
    chk(cost_per_call_minor(v) <= tg["costPerCallMinor"], "çağrı başına maliyet hedef içinde (≤1200)")

    chk(resource_stat(v, "memMb")["p95"] == 13.4 and resource_stat(v, "cpuMs")["p95"] == 180, "resourceStat CPU/bellek ayrı (FR-ANA-013)")
    chk(mem_within_budget(v) is True, "memWithinBudget (13.4≤15; FR-RES-016/NFR 10.2)")
    chk(cpu_within_budget(v) is True, "cpuWithinBudget (180≤250)")
    chk(resource_percentiles_consistent(v) is True, "resourcePercentilesConsistent (P95≥P50)")
    chk(density_meets_target(v) is True, "densityMeetsTarget (540≥250; NFR 10.2)")
    chk(density_meets_stretch(v) is True, "densityMeetsStretch (540≥500)")

    chk(series_calls(v) == 7600, "seriesCalls=7600")
    chk(series_cost_minor(v) == 8740000, "seriesCostMinor=8.740.000")
    chk(series_reconciles_calls(v) is True, "seriesReconcilesCalls (seri çağrı=dönem; FR-ANA-011)")
    chk(series_reconciles_cost(v) is True, "seriesReconcilesCost (seri maliyet=dönem; FR-ANA-011)")
    chk(abs(day_cost_per_call_minor(v["series"][0]) - 1242000 / 1080) < 1e-9, "dayCostPerCallMinor gün-0")
    chk(series_trend(v, "cost") == "flat", "seriesTrend maliyet=flat (verimlilik kararlı)")
    chk(series_trend(v, "calls") == "up", "seriesTrend hacim=up")

    # bant + ton eşlemeleri
    chk(lower_better_band(1100, 1200) == "good" and lower_better_band(1300, 1200) == "warn" and lower_better_band(1500, 1200) == "bad", "lowerBetterBand maliyet (düşük daha iyi)")
    chk(ratio_band(540, 250) == "good" and ratio_band(230, 250) == "warn" and ratio_band(180, 250) == "bad", "ratioBand density (yüksek daha iyi)")
    chk(lower_better_tone(1100, 1200) == "success" and lower_better_tone(1500, 1200) == "danger", "lowerBetterTone")
    chk(ratio_tone(540, 250) == "success" and ratio_tone(180, 250) == "danger", "ratioTone")
    chk(component_tone("llm") == "info" and component_tone("telephony") == "neutral", "componentTone")
    chk(cost_trend_tone("down") == "success" and cost_trend_tone("up") == "danger" and cost_trend_tone("flat") == "neutral", "costTrendTone (düşük daha iyi → down=success)")
    chk(volume_trend_tone("up") == "info" and volume_trend_tone("flat") == "neutral", "volumeTrendTone")

    # İKİ KATMAN guard — pozitif
    chk(assert_safe(v) is None, "assertSafe agregat görünüm İZİNLİ")
    chk(assert_no_forbidden_keys({"x": {"callRef": "..."}}) == "$.x.callRef", "L1 tek-çağrı callRef yakalanır (A-15 agregat panodur)")
    chk(assert_no_forbidden_keys({"x": {"customerName": "..."}}) == "$.x.customerName", "L1 müşteri adı yakalanır")
    chk(assert_no_forbidden_keys({"x": {"storageUri": "..."}}) == "$.x.storageUri", "L1 nesne-depo URI yakalanır (NFR 10.6)")
    chk(assert_redaction_clean({"label": "müşteri 05321234567"}) is not None, "L2 ham telefon yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"label": "Son 7 gün · %71 containment"}) is None, "L2 maskeli/yüzde içerik temiz")
    # Maliyet SAYILARI (büyük tamsayı) redaction'ı tetiklemez — yalnız STRING taranır
    chk(assert_redaction_clean({"amountMinor": 8740000}) is None, "L2 maliyet SAYISI (number) taranmaz (agregat tutar izinli)")

    # samples doğrulaması
    for name in ("cost-healthy.json", "cost-degraded.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        chk(total_cost_minor(snp) == exp.get("total_cost_minor"), f"{name} total_cost_minor={exp.get('total_cost_minor')}")
        chk(abs(cost_per_call_minor(snp) - exp.get("cost_per_call_minor")) < 0.5, f"{name} cost_per_call_minor≈{exp.get('cost_per_call_minor')}")
        chk(agent_cost_reconciles(snp) is True, f"{name} agentCostReconciles (FR-ANA-007)")
        chk(agent_calls_reconcile(snp) is True, f"{name} agentCallsReconcile")
        chk(mem_within_budget(snp) == exp.get("mem_within_budget"), f"{name} mem_within_budget={exp.get('mem_within_budget')}")
        chk(cpu_within_budget(snp) == exp.get("cpu_within_budget"), f"{name} cpu_within_budget={exp.get('cpu_within_budget')}")
        chk(density_meets_target(snp) == exp.get("density_meets"), f"{name} density_meets={exp.get('density_meets')}")
        chk(resource_percentiles_consistent(snp) is True, f"{name} resourcePercentilesConsistent (FR-ANA-013)")
        chk(series_reconciles_cost(snp) is True and series_reconciles_calls(snp) is True, f"{name} seriesReconciles (cost+calls; FR-ANA-011)")
        chk(lower_better_band(cost_per_call_minor(snp), snp["targets"]["costPerCallMinor"]) == exp.get("cost_band"), f"{name} cost_band={exp.get('cost_band')}")
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
    tg = v["targets"]

    # pozitif (sağlıklı dönem)
    expect(agent_cost_reconciles(v) is True, "pos agent maliyet uzlaşır (FR-ANA-007)")
    expect(agent_calls_reconcile(v) is True, "pos agent çağrı uzlaşır (FR-ANA-007)")
    expect(mem_within_budget(v) is True, "pos bellek bütçe içinde (FR-RES-016/NFR 10.2)")
    expect(density_meets_target(v) is True, "pos density hedef üstü (NFR 10.2)")
    expect(series_reconciles_cost(v) is True and series_reconciles_calls(v) is True, "pos seri toplamları dönemle bağdaşır (FR-ANA-011)")
    expect(cost_per_call_minor(v) <= tg["costPerCallMinor"], "pos çağrı başına maliyet hedef içinde")

    # sınır: boş dönem
    empty = dict(v, components=[], agents=[], series=[], totalCalls=0, resolvedCalls=0, billedMinutes=0)
    expect(total_cost_minor(empty) == 0, "sınır boş dönem total=0")
    expect(cost_per_call_minor(empty) == 0.0, "sınır boş dönem çağrı-başı=0 (sıfır bölme yok)")
    expect(cost_per_resolved_minor(empty) == 0.0, "sınır boş dönem çözülen-başı=0")
    expect(component_share(empty, "llm") == 0.0, "sınır boş dönem pay=0")
    expect(resolved_consistent(empty) is False, "sınır boş dönem resolvedConsistent=False (resolved=0)")
    expect(series_trend(empty, "cost") == "flat", "sınır boş seri trend=flat")
    expect(dominant_component(empty) is None, "sınır boş bileşen dominant=None")

    # FR-ANA-007: agent maliyet toplamı dönemle çelişirse yakalanır
    agent_bad = dict(v, agents=[dict(g) for g in v["agents"]])
    agent_bad["agents"][0] = dict(agent_bad["agents"][0], amountMinor=9999999)
    expect(agent_cost_reconciles(agent_bad) is False, "agent maliyet toplamı ≠ dönem → uzlaşmaz yakalanır (FR-ANA-007)")
    agent_calls_bad = dict(v, agents=[dict(g) for g in v["agents"]])
    agent_calls_bad["agents"][0] = dict(agent_calls_bad["agents"][0], calls=99)
    expect(agent_calls_reconcile(agent_calls_bad) is False, "agent çağrı toplamı ≠ totalCalls → uzlaşmaz yakalanır")

    # FR-RES-016/NFR 10.2: bellek bütçe aşımı yakalanır
    mem_over = dict(v, resources=[{"metric": "cpuMs", "p50": 95, "p95": 180, "budget": 250},
                                  {"metric": "memMb", "p50": 14, "p95": 18.5, "budget": 15}])
    expect(mem_within_budget(mem_over) is False, "bellek P95 18.5>15 → bütçe aşımı (FR-RES-016/NFR 10.2)")
    expect(resource_percentiles_consistent(mem_over) is True, "bütçe aşan ama P95≥P50 tutarlı")

    # FR-ANA-013: percentile monotonluğu (P95<P50 veri hatası) yakalanır
    pct_bad = dict(v, resources=[{"metric": "cpuMs", "p50": 200, "p95": 120, "budget": 250},
                                 {"metric": "memMb", "p50": 9, "p95": 13.4, "budget": 15}])
    expect(resource_percentiles_consistent(pct_bad) is False, "P95<P50 → percentile tutarsız yakalanır (FR-ANA-013)")

    # NFR 10.2: density hedef altı yakalanır
    low_dens = dict(v, efficiency=dict(v["efficiency"], density=180))
    expect(density_meets_target(low_dens) is False, "density 180<250 → hedef altı yakalanır (NFR 10.2)")
    expect(density_meets_stretch(low_dens) is False, "density 180<500 → stretch altı")

    # FR-ANA-011: seri maliyet/çağrı toplamı dönemle bağdaşmazsa yakalanır
    series_cost_bad = dict(v, series=[dict(p) for p in v["series"]])
    series_cost_bad["series"][0] = dict(series_cost_bad["series"][0], amountMinor=9999999)
    expect(series_reconciles_cost(series_cost_bad) is False, "seri maliyet ≠ dönem → bağdaşmaz yakalanır (FR-ANA-011)")
    series_calls_bad = dict(v, series=[dict(p) for p in v["series"]])
    series_calls_bad["series"][0] = dict(series_calls_bad["series"][0], calls=9999)
    expect(series_reconciles_calls(series_calls_bad) is False, "seri çağrı ≠ dönem → bağdaşmaz yakalanır (FR-ANA-011)")

    # maliyet trend yönleri (düşük daha iyi)
    rising_cost = dict(v, series=[{"date": "d1", "calls": 100, "amountMinor": 100000, "cpuMsP95": 170, "memMbP95": 13},
                                  {"date": "d2", "calls": 100, "amountMinor": 150000, "cpuMsP95": 200, "memMbP95": 14}])
    expect(series_trend(rising_cost, "cost") == "up", "trend maliyet=up (kötüleşme)")
    expect(cost_trend_tone(series_trend(rising_cost, "cost")) == "danger", "artan maliyet trendi danger")
    falling_cost = dict(v, series=[{"date": "d1", "calls": 100, "amountMinor": 150000, "cpuMsP95": 200, "memMbP95": 14},
                                   {"date": "d2", "calls": 100, "amountMinor": 100000, "cpuMsP95": 170, "memMbP95": 13}])
    expect(series_trend(falling_cost, "cost") == "down", "trend maliyet=down (iyileşme)")
    expect(cost_trend_tone(series_trend(falling_cost, "cost")) == "success", "azalan maliyet trendi success")

    # verimlilik bantları
    expect(ratio_band(v["efficiency"]["cacheHitRatio"], tg["cacheHit"]) == "good", "cache hit hedef üstü good")
    expect(ratio_band(v["efficiency"]["smallModelTurnRatio"], tg["smallModelRatio"]) == "good", "küçük-model oranı hedef üstü good")
    expect(ratio_band(0.3, tg["cacheHit"]) == "bad", "düşük cache hit bad")

    # bant sınırları
    expect(lower_better_band(1200, 1200) == "good", "lowerBetterBand sınırda (=hedef) good")
    expect(ratio_band(250, 250) == "good", "ratioBand sınırda (=hedef) good")
    expect(ratio_band(225, 250) == "warn", "ratioBand hedef·0.9 üstü warn")

    # İKİ KATMAN guard — negatif
    expect(assert_no_forbidden_keys({"x": {"transcriptText": "..."}}) is not None, "L1 transkript metni yakalanır")
    expect(assert_no_forbidden_keys({"x": {"audioBytes": "x"}}) is not None, "L1 audioBytes yakalanır")
    expect(assert_no_forbidden_keys({"x": {"signedUrl": "..."}}) is not None, "L1 signedUrl yakalanır (NFR 10.6)")
    expect(assert_no_forbidden_keys({"x": {"e164": "..."}}) is not None, "L1 ham numara (e164) yakalanır")
    expect(assert_redaction_clean({"c": "TR12 3456"}) is not None, "L2 IBAN deseni yakalanır")
    expect(assert_redaction_clean({"c": "kart 4111 1111 1111"}) is not None, "L2 kart bloğu yakalanır (FR-REC-005)")
    expect(assert_redaction_clean({"c": "Maskeli [•••], %71 oran."}) is None, "L2 maskeli + kısa yüzde temiz")
    leaky = {"period": {"label": "ara: 05551234567"}}
    expect(assert_safe(leaky) is not None, "kritik ham telefon içeren etiket yakalanır (REDACTION ihlali)")

    # placeholder ayrıştırma
    expect(placeholders("hedef ≤{target}") == {"target"}, "placeholder parse")
    expect(placeholders("≥{min} (stretch ≥{stretch})") == {"min", "stretch"}, "placeholder parse çoklu")

    # spec tutarlılık
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")
    expect(spec["components"] == COMPONENT_ORDER, "spec components = COMPONENT_ORDER")
    expect(spec["resource_metrics"] == RESOURCE_ORDER, "spec resource_metrics = RESOURCE_ORDER")
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
        "CostView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "currency": "str (ISO-4217, ör. TRY)",
            "period": {"from": "ISO date", "to": "ISO date", "label": "str"},
            "targets": {"costPerCallMinor": "int (minor)", "cpuMsP95": "int", "memMbP95": "int (NFR 10.2/FR-RES-016)", "densityMin": "int (NFR 10.2)", "densityStretch": "int", "cacheHit": "float", "smallModelRatio": "float", "idleReclaim": "float"},
            "totalCalls": "int", "resolvedCalls": "int (§18.1 cost per resolved)", "billedMinutes": "int (§18.2)",
            "components": [{"component": "|".join(COMPONENT_ORDER) + " (FR-ANA-007)", "amountMinor": "int (minor)"}],
            "agents": [{"agentRef": "str", "agentName": "str", "calls": "int", "amountMinor": "int (FR-ANA-007)"}],
            "resources": [{"metric": "|".join(RESOURCE_ORDER) + " (FR-ANA-013)", "p50": "num", "p95": "num", "budget": "num"}],
            "efficiency": {"density": "int (NFR 10.2 eşzamanlılık)", "cacheHitRatio": "float (FR-TTS-010)", "smallModelTurnRatio": "float (SR-DEN-005)", "idleReclaimRatio": "float (FR-RES-014)"},
            "series": [{"date": "ISO date", "calls": "int", "amountMinor": "int", "cpuMsP95": "num", "memMbP95": "num"}]
        },
        "components": COMPONENT_ORDER, "resource_metrics": RESOURCE_ORDER, "bands": BAND_ORDER, "trends": TREND_ORDER,
        "default_targets": DEFAULT_TARGETS, "warn_ratio": WARN_RATIO, "trend_flat_eps": TREND_FLAT_EPS, "mask_token": MASK_TOKEN,
        "money": "Tüm maliyetler MINOR birim (kuruş/cent) TAM SAYI (amountMinor); Σ bileşen = toplam TAM eşitlik (float drift yok). Görüntüleme minor/100 → formatCurrency.",
        "invariants": "totalCostMinor=Σ bileşen (FR-ANA-007). agentCostReconciles: Σ agent maliyet = toplam (FR-ANA-007). agentCallsReconcile: Σ agent çağrı = totalCalls. costPerCallMinor=total/calls; costPerResolvedMinor=total/resolved (§18.1); costPerMinuteMinor=total/minutes (§18.2). memWithinBudget/cpuWithinBudget: per-call P95 ≤ bütçe (FR-ANA-013/FR-RES-016/NFR 10.2). densityMeetsTarget: density ≥ 250 (NFR 10.2). seriesReconcilesCost/Calls: Σ seri = dönem (FR-ANA-011). resourcePercentilesConsistent: P95≥P50.",
        "hijyen": "A-15 yalnız TOPLULAŞTIRILMIŞ maliyet/kaynak metriği gösterir (Tier A) → break-glass gerekmez; tek çağrı içeriği/transkript/PII TAŞIMAZ. İKİ KATMAN guard: (1) assertNoForbiddenKeys — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni/e164/müşteri/kart-OTP) + tek-çağrı `callRef` + sır/credential/nesne-depo URI alan ADI YOK. (2) assertRedactionClean — hiçbir STRING değer ham PII DESENİ taşımaz; maliyet/kaynak SAYILARI taranmaz (FR-REC-004/005). Export derin aksiyon (cost:read — API §8.1); nihai export + redaction + audit backend (SAD §14.4.1).",
        "rbac": "operations_manager=Görüntüle · conversation_designer=— · qa_analyst=— · human_agent=— (BRD §17.6); tenant_owner kural 17.7 ile Yönet. Permission-key: cost:read (SAD §13.3)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a15_cost_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
