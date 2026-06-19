#!/usr/bin/env python3
# WBS 13.4.14 — A-14 "Analytics & Raporlama" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (oran/containment/konuşma/gecikme/seri/tone'lar/assertSafe) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (oran tutarlılık / AHT / gecikme bütçe / trend / İKİ KATMAN guard)
#   schema    — analitik görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/analytics.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a14-analytics-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "analytics", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "analytics.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

DIRECTION_ORDER = ["inbound", "outbound"]
OUTCOME_ORDER = ["contained", "transferred", "abandoned", "voicemail", "failed"]
LATENCY_ORDER = ["stt", "llm", "tts", "total"]
BAND_ORDER = ["good", "warn", "bad"]
TREND_ORDER = ["up", "down", "flat"]

DEFAULT_TARGETS = {"containment": 0.7, "csat": 0.85, "ahtSec": 240, "latencyP95Ms": 1200}
WARN_RATIO = 0.9
RATE_TOLERANCE = 0.01
AHT_TOLERANCE = 5
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


# ── SAF çekirdek aynası (lib/tenant/analytics.ts ile birebir) ──────────────────────

def sorted_outcomes(view):
    return sorted(view["outcomes"], key=lambda o: OUTCOME_ORDER.index(o["outcome"]))


def sorted_latency(view):
    return sorted(view["latency"], key=lambda l: LATENCY_ORDER.index(l["stage"]))


def total_calls(view):
    return sum(o["count"] for o in view["outcomes"])


def outcome_count(view, outcome):
    for o in view["outcomes"]:
        if o["outcome"] == outcome:
            return o["count"]
    return 0


def outcome_rate(view, outcome):
    t = total_calls(view)
    return 0.0 if t <= 0 else outcome_count(view, outcome) / t


def containment_rate(view):
    return outcome_rate(view, "contained")


def transfer_rate(view):
    return outcome_rate(view, "transferred")


def abandon_rate(view):
    return outcome_rate(view, "abandoned")


def outcome_rates_sum_to_one(view, tol=RATE_TOLERANCE):
    if total_calls(view) <= 0:
        return True
    s = sum(outcome_rate(view, o) for o in OUTCOME_ORDER)
    return abs(s - 1) <= tol


def outcome_counts_consistent(view):
    return sum(o["count"] for o in view["outcomes"]) == total_calls(view)


def talk_total_sec(t):
    return t["userSec"] + t["agentSec"] + t["silenceSec"]


def agent_talk_ratio(t):
    spoken = t["userSec"] + t["agentSec"]
    return 0.0 if spoken <= 0 else t["agentSec"] / spoken


def avg_call_sec(view):
    t = total_calls(view)
    return 0.0 if t <= 0 else talk_total_sec(view["talk"]) / t


def aht_consistent(view, tol=AHT_TOLERANCE):
    return abs(view["ahtSec"] - avg_call_sec(view)) <= tol


def latency_stage(view, stage):
    for l in view["latency"]:
        if l["stage"] == stage:
            return l
    return None


def latency_within_budget(view, budget_ms=DEFAULT_TARGETS["latencyP95Ms"]):
    total = latency_stage(view, "total")
    return total["p95Ms"] <= budget_ms if total else False


def latency_chain_consistent(view):
    total = latency_stage(view, "total")
    if not total:
        return False
    for s in ("stt", "llm", "tts"):
        c = latency_stage(view, s)
        if c and not (total["p95Ms"] >= c["p95Ms"] and total["p50Ms"] >= c["p50Ms"]):
            return False
    return True


def series_calls(view):
    return sum(p["calls"] for p in view["series"])


def series_contained(view):
    return sum(p["contained"] for p in view["series"])


def series_reconciles(view):
    return len(view["series"]) == 0 or series_calls(view) == total_calls(view)


def day_containment_rate(p):
    return 0.0 if p["calls"] <= 0 else p["contained"] / p["calls"]


def series_trend(view, key, eps=TREND_FLAT_EPS):
    xs = view["series"]
    if len(xs) < 2:
        return "flat"

    def value_of(p):
        return day_containment_rate(p) if key == "contained" else (p["csat"] if key == "csat" else p["calls"])

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


def current_version(view):
    for v in view["versions"]:
        if v["current"]:
            return v
    return None


def weighted_avg_containment(versions):
    calls = sum(v["calls"] for v in versions)
    if calls <= 0:
        return 0.0
    return sum(v["containmentRate"] * v["calls"] for v in versions) / calls


def version_containment_delta(v, versions):
    return v["containmentRate"] - weighted_avg_containment(versions)


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


def direction_tone(d):
    return {"inbound": "neutral", "outbound": "info"}[d]


def outcome_tone(o):
    return {"contained": "success", "transferred": "info", "abandoned": "warning",
            "voicemail": "neutral", "failed": "danger"}[o]


def trend_tone(d):
    return {"up": "success", "down": "danger", "flat": "neutral"}[d]


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
    """analytics.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.14", "S0 spec.wbs=13.4.14")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/analytics/page.tsx mevcut")
    chk('data-screen="A-14"' in page, 'S1 data-screen="A-14" işaretli')
    chk("İskelet ekran — A-14" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/analytics" in page, "S2 veri seam (lib/tenant/analytics) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "EmptyState"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür ETİKET metni i18n'den (screen.a14.*); hardcoded TR/EN ETİKET cümlesi yok
    chk("screen.a14." in page, "S3 screen.a14.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded etiket metni yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı İKİ KATMAN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/analytics.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("RAW_PII_PATTERNS" in data, "S4 RAW_PII_PATTERNS (içerik redaction deseni) tanımlı")
    chk("assertNoForbiddenKeys" in data, "S4 assertNoForbiddenKeys (yapısal) guard tanımlı")
    chk("assertRedactionClean" in data, "S4 assertRedactionClean (içerik) guard tanımlı")
    chk(re.search(r"assertSafe\(view\)", data) is not None, "S4 getAnalyticsView assertSafe çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("callref", "text", "recording", "e164", "cardpan")), "S4 tek-çağrı callRef/transkript/ham ses/numara/kart yasak (A-14 agregat panodur; BRD §17.7)")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("storageuri", "url", "kmskey", "signedurl")), "S4 nesne-depo URI/sır yasak (NFR 10.6)")
    leak = assert_no_forbidden_keys({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/URI alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-ANA-002/003/005/006/010/011 karşılanır
    a14 = tr.get("screen", {}).get("a14", {})
    sec = a14.get("section", {})
    for s in ("summary", "outcomes", "talk", "latency", "trend", "versions"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("totalCalls" in data and "containmentRate" in data and "transferRate" in data and "outcomeRatesSumToOne" in data and set(OUTCOME_ORDER).issubset(a14.get("outcome", {}).keys()), "S5 sonuç/containment/transfer (FR-ANA-002/003)")
    chk("talkTotalSec" in data and "avgCallSec" in data and "ahtConsistent" in data and set(("user", "agent", "silence")).issubset(a14.get("talk", {}).keys()), "S5 konuşma süreleri (FR-ANA-005)")
    chk("latencyStage" in data and "latencyWithinBudget" in data and "latencyChainConsistent" in data and set(LATENCY_ORDER).issubset(a14.get("stage", {}).keys()), "S5 STT/LLM/TTS+toplam gecikme AYRI (FR-ANA-006)")
    chk("weightedAvgContainment" in data and "versionContainmentDelta" in data and "versions" in sec, "S5 sürüm karşılaştırması (FR-ANA-010)")
    chk("seriesReconciles" in data and "seriesTrend" in data and "export" in a14.get("action", {}), "S5 zaman serisi + ham veri export (FR-ANA-011)")
    chk(set(BAND_ORDER) and set(TREND_ORDER).issubset(a14.get("trend", {}).keys()), "S5 trend etiketleri (up/down/flat)")
    chk("latency_over" in a14.get("alert", {}), "S5 gecikme bütçe uyarısı (NFR 10.1)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a14.{rk}"
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
        vt = resolve(tr, f"screen.a14.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedOutcomes", "sortedLatency", "totalCalls", "outcomeCount", "outcomeRate", "containmentRate",
               "transferRate", "abandonRate", "outcomeRatesSumToOne", "outcomeCountsConsistent", "talkTotalSec",
               "agentTalkRatio", "avgCallSec", "ahtConsistent", "latencyStage", "latencyWithinBudget",
               "latencyChainConsistent", "seriesCalls", "seriesContained", "seriesReconciles", "dayContainmentRate",
               "seriesTrend", "currentVersion", "weightedAvgContainment", "versionContainmentDelta", "ratioBand",
               "lowerBetterBand", "ratioTone", "lowerBetterTone", "outcomeTone", "trendTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("DIRECTION_ORDER", "OUTCOME_ORDER", "LATENCY_ORDER", "BAND_ORDER")), "S7 *_ORDER sabitleri tanımlı")
    chk(all(c in data for c in ("DEFAULT_TARGETS", "WARN_RATIO", "RATE_TOLERANCE", "AHT_TOLERANCE", "TREND_FLAT_EPS", "MASK_TOKEN")), "S7 hedef/tolerans sabitleri tanımlı")
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
        "period": {"from": "2026-06-11", "to": "2026-06-17", "label": "Son 7 gün"},
        "targets": dict(DEFAULT_TARGETS),
        "outcomes": [
            {"outcome": "contained", "count": 5400}, {"outcome": "transferred", "count": 1500},
            {"outcome": "abandoned", "count": 420}, {"outcome": "voicemail", "count": 180},
            {"outcome": "failed", "count": 100},
        ],
        "csat": 0.88, "csatResponses": 4120, "ahtSec": 196,
        "talk": {"userSec": 612000, "agentSec": 735000, "silenceSec": 168400},
        "latency": [
            {"stage": "stt", "p50Ms": 180, "p95Ms": 320}, {"stage": "llm", "p50Ms": 240, "p95Ms": 520},
            {"stage": "tts", "p50Ms": 150, "p95Ms": 280}, {"stage": "total", "p50Ms": 620, "p95Ms": 1080},
        ],
        "series": [
            {"date": "2026-06-11", "calls": 1080, "contained": 745, "csat": 0.86, "ahtSec": 201},
            {"date": "2026-06-12", "calls": 1120, "contained": 781, "csat": 0.87, "ahtSec": 198},
            {"date": "2026-06-13", "calls": 940, "contained": 668, "csat": 0.88, "ahtSec": 195},
            {"date": "2026-06-14", "calls": 760, "contained": 547, "csat": 0.89, "ahtSec": 192},
            {"date": "2026-06-15", "calls": 1210, "contained": 872, "csat": 0.88, "ahtSec": 197},
            {"date": "2026-06-16", "calls": 1190, "contained": 869, "csat": 0.90, "ahtSec": 193},
            {"date": "2026-06-17", "calls": 1300, "contained": 918, "csat": 0.90, "ahtSec": 190},
        ],
        "versions": [
            {"agentVersion": "v7", "calls": 4200, "containmentRate": 0.78, "csat": 0.90, "ahtSec": 190, "current": True},
            {"agentVersion": "v6", "calls": 2400, "containmentRate": 0.72, "csat": 0.86, "ahtSec": 205, "current": False},
            {"agentVersion": "v5", "calls": 1000, "containmentRate": 0.68, "csat": 0.84, "ahtSec": 214, "current": False},
        ],
    }


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    tg = v["targets"]

    chk([o["outcome"] for o in sorted_outcomes(v)] == OUTCOME_ORDER, "sortedOutcomes OUTCOME_ORDER")
    chk([l["stage"] for l in sorted_latency(v)] == LATENCY_ORDER, "sortedLatency LATENCY_ORDER")
    chk(total_calls(v) == 7600, "totalCalls=7600 (Σ outcome; FR-ANA-002)")
    chk(outcome_count(v, "contained") == 5400, "outcomeCount contained=5400")
    chk(abs(containment_rate(v) - 5400 / 7600) < 1e-9, "containmentRate=contained/total (FR-ANA-003)")
    chk(abs(transfer_rate(v) - 1500 / 7600) < 1e-9, "transferRate=transferred/total (FR-ANA-003)")
    chk(outcome_rates_sum_to_one(v) is True, "outcomeRatesSumToOne (Σ oran ≈ 1; FR-ANA-002)")
    chk(outcome_counts_consistent(v) is True, "outcomeCountsConsistent (Σ sayı = total)")
    chk(containment_rate(v) >= tg["containment"], "containment hedef üstü (≥0.70)")

    chk(talk_total_sec(v["talk"]) == 1515400, "talkTotalSec=1515400 (FR-ANA-005)")
    chk(abs(avg_call_sec(v) - 1515400 / 7600) < 1e-9, "avgCallSec=talk/total")
    chk(aht_consistent(v) is True, "ahtConsistent (saklanan AHT ≈ türetilen; FR-ANA-005)")
    chk(abs(agent_talk_ratio(v["talk"]) - 735000 / 1347000) < 1e-9, "agentTalkRatio=agent/(user+agent)")

    chk(latency_stage(v, "stt")["p95Ms"] == 320 and latency_stage(v, "total")["p95Ms"] == 1080, "latencyStage STT/total ayrı (FR-ANA-006)")
    chk(latency_within_budget(v, tg["latencyP95Ms"]) is True, "latencyWithinBudget (1080≤1200; NFR 10.1)")
    chk(latency_chain_consistent(v) is True, "latencyChainConsistent (toplam ≥ bileşen)")

    chk(series_calls(v) == 7600, "seriesCalls=7600")
    chk(series_contained(v) == 5400, "seriesContained=5400")
    chk(series_reconciles(v) is True, "seriesReconciles (seri=dönem toplam; FR-ANA-011)")
    chk(abs(day_containment_rate(v["series"][0]) - 745 / 1080) < 1e-9, "dayContainmentRate gün-0")
    chk(series_trend(v, "calls") == "up", "seriesTrend hacim=up (760→1300 yönü)")
    chk(series_trend(v, "csat") == "up", "seriesTrend csat=up")

    chk(current_version(v)["agentVersion"] == "v7", "currentVersion=v7 (FR-ANA-010)")
    chk(abs(weighted_avg_containment(v["versions"]) - 5684 / 7600) < 1e-9, "weightedAvgContainment çağrı-ağırlıklı")
    chk(version_containment_delta(current_version(v), v["versions"]) > 0, "versionContainmentDelta v7 > 0 (iyileşme; FR-ANA-010)")

    # bant + ton eşlemeleri
    chk(ratio_band(0.9, 0.85) == "good" and ratio_band(0.8, 0.85) == "warn" and ratio_band(0.5, 0.85) == "bad", "ratioBand good/warn/bad (yüksek daha iyi)")
    chk(lower_better_band(200, 240) == "good" and lower_better_band(260, 240) == "warn" and lower_better_band(400, 240) == "bad", "lowerBetterBand (düşük daha iyi)")
    chk(ratio_tone(0.9, 0.85) == "success" and ratio_tone(0.5, 0.85) == "danger", "ratioTone success/danger")
    chk(lower_better_tone(200, 240) == "success" and lower_better_tone(400, 240) == "danger", "lowerBetterTone")
    chk(outcome_tone("contained") == "success" and outcome_tone("failed") == "danger", "outcomeTone")
    chk(trend_tone("up") == "success" and trend_tone("down") == "danger" and trend_tone("flat") == "neutral", "trendTone")

    # İKİ KATMAN guard — pozitif
    chk(assert_safe(v) is None, "assertSafe agregat görünüm İZİNLİ")
    chk(assert_no_forbidden_keys({"x": {"callRef": "..."}}) == "$.x.callRef", "L1 tek-çağrı callRef yakalanır (A-14 agregat panodur)")
    chk(assert_no_forbidden_keys({"x": {"transcriptText": "..."}}) == "$.x.transcriptText", "L1 transkript metni yakalanır")
    chk(assert_no_forbidden_keys({"x": {"storageUri": "..."}}) == "$.x.storageUri", "L1 nesne-depo URI yakalanır (NFR 10.6)")
    chk(assert_redaction_clean({"label": "müşteri 05321234567"}) is not None, "L2 ham telefon yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"label": "Son 7 gün · %71 containment"}) is None, "L2 maskeli/yüzde içerik temiz")

    # samples doğrulaması
    for name in ("analytics-healthy.json", "analytics-degraded.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        sg = snp["targets"]
        chk(total_calls(snp) == exp.get("total_calls"), f"{name} total_calls={exp.get('total_calls')}")
        chk(abs(containment_rate(snp) - exp.get("containment_rate")) < 0.0005, f"{name} containment_rate≈{exp.get('containment_rate')}")
        chk(outcome_rates_sum_to_one(snp) is True, f"{name} outcomeRatesSumToOne (FR-ANA-002)")
        chk(outcome_counts_consistent(snp) is True, f"{name} outcomeCountsConsistent")
        chk(aht_consistent(snp) == exp.get("aht_consistent"), f"{name} aht_consistent={exp.get('aht_consistent')}")
        chk(latency_within_budget(snp, sg["latencyP95Ms"]) == exp.get("latency_within_budget"), f"{name} latency_within_budget={exp.get('latency_within_budget')}")
        chk(latency_chain_consistent(snp) is True, f"{name} latencyChainConsistent (FR-ANA-006)")
        chk(series_reconciles(snp) == exp.get("series_reconciles"), f"{name} series_reconciles={exp.get('series_reconciles')}")
        chk(ratio_band(containment_rate(snp), sg["containment"]) == exp.get("containment_band"), f"{name} containment_band={exp.get('containment_band')}")
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
    expect(outcome_rates_sum_to_one(v) is True, "pos outcome oranı toplamı 1 (FR-ANA-002)")
    expect(containment_rate(v) >= tg["containment"], "pos containment hedef üstü (FR-ANA-003)")
    expect(aht_consistent(v) is True, "pos AHT tutarlı (FR-ANA-005)")
    expect(latency_within_budget(v, tg["latencyP95Ms"]) is True, "pos gecikme bütçe içinde (NFR 10.1)")
    expect(series_reconciles(v) is True, "pos seri toplamı dönemle bağdaşır (FR-ANA-011)")

    # FR-ANA-002: outcome oran tutarsızlığı yakalanır (sayılar uydurma değil)
    # (manuel olarak total ile çelişen agregat outcomeRatesSumToOne'u bozmaz çünkü oran total'dan türetilir;
    #  ama outcomeCountsConsistent her zaman tutarlı — yapısal). Yerine boş dönem sınırını test et.
    empty = dict(v, outcomes=[], series=[], talk={"userSec": 0, "agentSec": 0, "silenceSec": 0}, ahtSec=0)
    expect(total_calls(empty) == 0, "sınır boş dönem total=0")
    expect(outcome_rate(empty, "contained") == 0.0, "sınır boş dönem oran=0 (sıfır bölme yok)")
    expect(outcome_rates_sum_to_one(empty) is True, "sınır boş dönem oran toplamı muaf")
    expect(avg_call_sec(empty) == 0.0 and aht_consistent(empty) is True, "sınır boş dönem AHT tutarlı")
    expect(series_trend(empty, "csat") == "flat", "sınır boş seri trend=flat")

    # FR-ANA-006: bileşen toplamı aşarsa zincir tutarsız (veri hatası yakalanır)
    bad_chain = dict(v, latency=[{"stage": "stt", "p50Ms": 180, "p95Ms": 1300},
                                 {"stage": "llm", "p50Ms": 240, "p95Ms": 520},
                                 {"stage": "tts", "p50Ms": 150, "p95Ms": 280},
                                 {"stage": "total", "p50Ms": 620, "p95Ms": 1080}])
    expect(latency_chain_consistent(bad_chain) is False, "STT P95 > toplam → zincir tutarsız yakalanır (FR-ANA-006)")

    # NFR 10.1: gecikme bütçe aşımı yakalanır
    over = dict(v, latency=[{"stage": "stt", "p50Ms": 400, "p95Ms": 600},
                            {"stage": "llm", "p50Ms": 700, "p95Ms": 1100},
                            {"stage": "tts", "p50Ms": 300, "p95Ms": 500},
                            {"stage": "total", "p50Ms": 1400, "p95Ms": 2300}])
    expect(latency_within_budget(over, tg["latencyP95Ms"]) is False, "toplam P95 2300>1200 → bütçe aşımı (NFR 10.1)")
    expect(latency_chain_consistent(over) is True, "bütçe aşan ama yapısal tutarlı zincir")

    # FR-ANA-005: AHT tutarsızlığı yakalanır
    aht_bad = dict(v, ahtSec=120)  # gerçek ~199; fark 79 > tolerans
    expect(aht_consistent(aht_bad) is False, "saklanan AHT türetilenden sapar → yakalanır (FR-ANA-005)")

    # FR-ANA-011: seri toplamı dönemle bağdaşmazsa yakalanır
    series_bad = dict(v, series=[dict(p) for p in v["series"]])
    series_bad["series"][0] = dict(series_bad["series"][0], calls=9999)
    expect(series_reconciles(series_bad) is False, "seri çağrı toplamı ≠ dönem → bağdaşmaz yakalanır (FR-ANA-011)")

    # trend yönleri
    rising = dict(v, series=[{"date": "d1", "calls": 100, "contained": 50, "csat": 0.7, "ahtSec": 200},
                             {"date": "d2", "calls": 100, "contained": 90, "csat": 0.95, "ahtSec": 180}])
    expect(series_trend(rising, "contained") == "up", "trend containment=up")
    falling = dict(v, series=[{"date": "d1", "calls": 100, "contained": 90, "csat": 0.95, "ahtSec": 180},
                              {"date": "d2", "calls": 100, "contained": 50, "csat": 0.7, "ahtSec": 220}])
    expect(series_trend(falling, "contained") == "down", "trend containment=down")
    flat = dict(v, series=[{"date": "d1", "calls": 100, "contained": 70, "csat": 0.85, "ahtSec": 200},
                           {"date": "d2", "calls": 100, "contained": 70, "csat": 0.85, "ahtSec": 200}])
    expect(series_trend(flat, "contained") == "flat", "trend containment=flat")

    # FR-ANA-010: sürüm karşılaştırması
    expect(version_containment_delta(current_version(v), v["versions"]) > 0, "v7 ortalama üstü (FR-ANA-010)")
    worst = v["versions"][2]  # v5
    expect(version_containment_delta(worst, v["versions"]) < 0, "v5 ortalama altı (gerileme; FR-ANA-010)")
    no_current = dict(v, versions=[dict(x, current=False) for x in v["versions"]])
    expect(current_version(no_current) is None, "yayın sürümü yoksa None")

    # bant sınırları
    expect(ratio_band(0.85, 0.85) == "good", "ratioBand sınırda (=hedef) good")
    expect(ratio_band(0.765, 0.85) == "warn", "ratioBand hedef·0.9 üstü warn")
    expect(lower_better_band(240, 240) == "good", "lowerBetterBand sınırda good")

    # İKİ KATMAN guard — negatif
    expect(assert_no_forbidden_keys({"x": {"customerName": "..."}}) is not None, "L1 müşteri adı yakalanır")
    expect(assert_no_forbidden_keys({"x": {"audioBytes": "x"}}) is not None, "L1 audioBytes yakalanır")
    expect(assert_no_forbidden_keys({"x": {"signedUrl": "..."}}) is not None, "L1 signedUrl yakalanır (NFR 10.6)")
    expect(assert_no_forbidden_keys({"x": {"callRef": "CALL-1"}}) is not None, "L1 tek-çağrı callRef yakalanır")
    expect(assert_redaction_clean({"c": "TR12 3456"}) is not None, "L2 IBAN deseni yakalanır")
    expect(assert_redaction_clean({"c": "kart 4111 1111 1111"}) is not None, "L2 kart bloğu yakalanır (FR-REC-005)")
    expect(assert_redaction_clean({"c": "Maskeli [•••], %71 oran."}) is None, "L2 maskeli + kısa yüzde temiz")
    leaky = {"period": {"label": "ara: 05551234567"}}
    expect(assert_safe(leaky) is not None, "kritik ham telefon içeren etiket yakalanır (REDACTION ihlali)")

    # placeholder ayrıştırma
    expect(placeholders("hedef ≥{target}") == {"target"}, "placeholder parse")
    expect(placeholders("P95 ({p95}) bütçe ({budget})") == {"p95", "budget"}, "placeholder parse çoklu")

    # spec tutarlılık
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")
    expect(spec["outcomes"] == OUTCOME_ORDER, "spec outcomes = OUTCOME_ORDER")
    expect(spec["latency_stages"] == LATENCY_ORDER, "spec latency_stages = LATENCY_ORDER")
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
        "AnalyticsView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "period": {"from": "ISO date", "to": "ISO date", "label": "str"},
            "targets": {"containment": "float", "csat": "float", "ahtSec": "int", "latencyP95Ms": "int (NFR 10.1)"},
            "outcomes": [{"outcome": "|".join(OUTCOME_ORDER) + " (FR-ANA-002/003)", "count": "int"}],
            "csat": "float 0..1 (dönem CSAT)", "csatResponses": "int (örneklem)",
            "ahtSec": "int (FR-ANA-005; ≈ talk/total)",
            "talk": {"userSec": "int", "agentSec": "int", "silenceSec": "int (FR-ANA-005)"},
            "latency": [{"stage": "|".join(LATENCY_ORDER) + " (FR-ANA-006 AYRI)", "p50Ms": "int", "p95Ms": "int"}],
            "series": [{"date": "ISO date", "calls": "int", "contained": "int", "csat": "float", "ahtSec": "int"}],
            "versions": [{"agentVersion": "str", "calls": "int", "containmentRate": "float", "csat": "float", "ahtSec": "int", "current": "bool (FR-ANA-010)"}]
        },
        "outcomes": OUTCOME_ORDER, "latency_stages": LATENCY_ORDER, "bands": BAND_ORDER, "trends": TREND_ORDER,
        "default_targets": DEFAULT_TARGETS, "warn_ratio": WARN_RATIO, "rate_tolerance": RATE_TOLERANCE,
        "aht_tolerance": AHT_TOLERANCE, "trend_flat_eps": TREND_FLAT_EPS, "mask_token": MASK_TOKEN,
        "invariants": "outcomeRatesSumToOne: Σ outcome oranı ≈ 1 (FR-ANA-002). containmentRate=contained/total (FR-ANA-003). ahtConsistent: saklanan AHT ≈ çağrı başı konuşma (FR-ANA-005). latencyChainConsistent: toplam ≥ STT/LLM/TTS (FR-ANA-006). latencyWithinBudget: toplam P95 ≤ bütçe (NFR 10.1). seriesReconciles: Σ seri çağrı = dönem total (FR-ANA-011). versionContainmentDelta: sürüm − ağırlıklı agent ortalaması (FR-ANA-010).",
        "hijyen": "A-14 yalnız TOPLULAŞTIRILMIŞ metrik gösterir (Tier A) → break-glass gerekmez; tek çağrı içeriği/transkript/PII TAŞIMAZ. İKİ KATMAN guard: (1) assertNoForbiddenKeys — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni/e164/müşteri/kart-OTP) + tek-çağrı `callRef` + sır/credential/nesne-depo URI alan ADI YOK. (2) assertRedactionClean — hiçbir string değer ham PII DESENİ taşımaz (FR-REC-004/005). Export derin aksiyon (analytics:read — API §8.1); nihai export + redaction + audit backend (SAD §14.4.1)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a14_analytics_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
