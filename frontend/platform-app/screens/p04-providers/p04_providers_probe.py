#!/usr/bin/env python3
# WBS 13.2.4 — P-04 "Sağlayıcı & Entegrasyon Sağlığı" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (healthTone/circuitTone/errorRateTone/rollupHealth/categoryHealth/
#               redundancyOk/redundancyRisks/isFallbackActive/activeFallbackCount/openCircuitCount/
#               countByHealth/aggregateCost/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/providers.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p04-providers-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "providers", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "providers.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

ERROR_RATE_DANGER_PCT = 5
ERROR_RATE_WARNING_PCT = 1
MIN_OPERATIONAL_PROVIDERS = 2


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/providers.ts ile birebir) ───────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "pii", "email", "ssn"]

HEALTH_TONE = {"healthy": "success", "degraded": "warning", "down": "danger"}
CIRCUIT_TONE = {"closed": "success", "half_open": "warning", "open": "danger"}
HEALTH_RANK = {"healthy": 0, "degraded": 1, "down": 2}


def health_tone(s):
    return HEALTH_TONE[s]


def circuit_tone(s):
    return CIRCUIT_TONE[s]


def error_rate_tone(pct):
    if pct >= ERROR_RATE_DANGER_PCT:
        return "danger"
    if pct >= ERROR_RATE_WARNING_PCT:
        return "warning"
    return "success"


def rollup_health(states):
    worst = "healthy"
    for s in states:
        if HEALTH_RANK[s] > HEALTH_RANK[worst]:
            worst = s
    return worst


def category_adapters(adapters, category):
    return [a for a in adapters if a["category"] == category]


def category_health(adapters, category):
    return rollup_health([a["health"] for a in category_adapters(adapters, category)])


def redundancy_ok(adapters, category):
    operational = len([a for a in category_adapters(adapters, category) if a["health"] != "down"])
    return operational >= MIN_OPERATIONAL_PROVIDERS


def redundancy_risks(snap):
    return [c["category"] for c in snap["categories"] if not redundancy_ok(snap["adapters"], c["category"])]


def is_fallback_active(snap, category):
    routing = next((c for c in snap["categories"] if c["category"] == category), None)
    if routing is None:
        return False
    primary = next((a for a in snap["adapters"] if a["id"] == routing["primaryId"]), None)
    if primary is None:
        return True
    return primary["health"] == "down" or primary["circuit"] == "open"


def active_fallback_count(snap):
    return len([c for c in snap["categories"] if is_fallback_active(snap, c["category"])])


def open_circuit_count(adapters):
    return len([a for a in adapters if a["circuit"] == "open"])


def count_by_health(adapters):
    acc = {"healthy": 0, "degraded": 0, "down": 0}
    for a in adapters:
        acc[a["health"]] += 1
    return acc


def aggregate_cost(categories):
    today = sum(c["cost"]["today"] for c in categories)
    mtd = sum(c["cost"]["mtd"] for c in categories)
    return {"today": today, "mtd": mtd}


def assert_no_pii(node, path="$"):
    """Yasak iş-içeriği/son-müşteri PII alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_pii(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            if k.lower() in FORBIDDEN_PII_KEYS:
                return f"{path}.{k}"
            hit = assert_no_pii(v, f"{path}.{k}")
            if hit:
                return hit
    return None


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
    """providers.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.4", "S0 spec.wbs=13.2.4")
    chk(os.path.isfile(PAGE_PATH), "S1 providers/page.tsx mevcut")
    chk('data-screen="P-04"' in page, 'S1 data-screen="P-04" işaretli')
    chk("İskelet ekran — P-04" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/providers" in page, "S2 veri seam (lib/platform/providers) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p04.*); hardcoded TR/EN cümle yok
    chk("screen.p04." in page, "S3 screen.p04.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/providers.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getProviders assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (adapter durumu + fallback/routing + sağlayıcı maliyeti)
    p04 = tr.get("screen", {}).get("p04", {})
    catg = p04.get("category", {})
    chk(all(x in catg for x in ("stt", "tts", "llm", "telephony")), "S5 STT/TTS/LLM/telekom → category.*")
    chk("health" in p04 and "circuit" in p04, "S5 adapter durumu → health.* + circuit.*")
    chk("routing" in p04.get("section", {}) and "fallback_chain" in p04.get("col", {}), "S5 fallback/routing → section.routing + col.fallback_chain")
    chk("cost" in p04.get("section", {}) and "unit" in p04, "S5 sağlayıcı maliyeti → section.cost + unit.*")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p04.{rk}"
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
        vt = resolve(tr, f"screen.p04.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("healthTone", "circuitTone", "errorRateTone", "rollupHealth", "categoryHealth",
               "redundancyOk", "redundancyRisks", "isFallbackActive", "activeFallbackCount",
               "openCircuitCount", "countByHealth", "aggregateCost"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral (somut sağlayıcı markası yok) + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "deepgram", "elevenlabs", "cartesia",
                         "telnyx", "datadog.com", "api_key", "secret="]
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

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # healthTone / circuitTone
    chk(health_tone("healthy") == "success", "health healthy→success")
    chk(health_tone("degraded") == "warning", "health degraded→warning")
    chk(health_tone("down") == "danger", "health down→danger")
    chk(circuit_tone("closed") == "success", "circuit closed→success")
    chk(circuit_tone("half_open") == "warning", "circuit half_open→warning")
    chk(circuit_tone("open") == "danger", "circuit open→danger")
    # errorRateTone
    chk(error_rate_tone(14.8) == "danger", "error ≥5 danger")
    chk(error_rate_tone(2.4) == "warning", "error ≥1 warning")
    chk(error_rate_tone(0.6) == "success", "error <1 success")
    # rollupHealth (worst-of)
    chk(rollup_health(["healthy", "degraded", "down"]) == "down", "rollup worst=down")
    chk(rollup_health(["healthy", "degraded"]) == "degraded", "rollup worst=degraded")
    chk(rollup_health([]) == "healthy", "rollup boş→healthy")
    # assertNoPii
    chk(assert_no_pii({"adapters": [{"name": "STT Sağlayıcı A", "health": "healthy"}]}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"adapters": [{"transcript": "x"}]}) == "$.adapters[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")

    # samples doğrulaması
    for name in ("providers-mixed.json", "providers-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        adapters = snap["adapters"]
        chk(count_by_health(adapters) == exp["count_by_health"], f"{name} count_by_health={exp['count_by_health']}")
        chk(open_circuit_count(adapters) == exp["open_circuits"], f"{name} open_circuits={exp['open_circuits']}")
        chk(active_fallback_count(snap) == exp["active_fallbacks"], f"{name} active_fallbacks={exp['active_fallbacks']}")
        chk(redundancy_risks(snap) == exp["redundancy_risks"], f"{name} redundancy_risks={exp['redundancy_risks']}")
        agg = aggregate_cost(snap["categories"])
        chk(round(agg["today"], 2) == exp["cost"]["today"], f"{name} cost.today={exp['cost']['today']}")
        chk(round(agg["mtd"], 2) == exp["cost"]["mtd"], f"{name} cost.mtd={exp['cost']['mtd']}")
        chk(assert_no_pii(snap) is None, f"{name} PII-free (ALTIN KURAL)")

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

    # pozitif
    expect(error_rate_tone(5.0) == "danger", "pos eşik tam 5→danger")
    expect(error_rate_tone(1.0) == "warning", "pos eşik tam 1→warning")
    expect(health_tone("down") == "danger", "pos down kritik tone")
    expect(assert_no_pii({"name": "Telekom Sağlayıcı A"}) is None, "pos no-pii (adapter adı izinli)")
    # fallback aktif: birincil down/open → aktif
    snap = {
        "categories": [
            {"category": "llm", "primaryId": "llm-a", "fallbackOrder": ["llm-b"], "deterministicFallback": True, "cost": {"today": 1.0, "mtd": 2.0, "unit": "ktokens", "unitCost": 0.001}},
            {"category": "stt", "primaryId": "stt-a", "fallbackOrder": ["stt-b"], "deterministicFallback": False, "cost": {"today": 1.0, "mtd": 2.0, "unit": "minute", "unitCost": 0.01}},
        ],
        "adapters": [
            {"id": "llm-a", "category": "llm", "health": "down", "circuit": "open"},
            {"id": "llm-b", "category": "llm", "health": "healthy", "circuit": "closed"},
            {"id": "stt-a", "category": "stt", "health": "healthy", "circuit": "closed"},
            {"id": "stt-b", "category": "stt", "health": "healthy", "circuit": "closed"},
        ],
    }
    expect(is_fallback_active(snap, "llm") is True, "pos birincil down→fallback aktif")
    expect(is_fallback_active(snap, "stt") is False, "pos birincil sağlıklı→fallback beklemede")
    expect(active_fallback_count(snap) == 1, "pos aktif fallback sayısı=1")
    # dayanıklılık: stt 2 çalışır → ok; llm yalnız 1 çalışır (a down) → risk
    expect(redundancy_ok(snap["adapters"], "stt") is True, "pos stt 2 çalışır→dayanıklı")
    expect(redundancy_ok(snap["adapters"], "llm") is False, "pos llm yalnız 1 çalışır→dayanıklı DEĞİL")
    expect(redundancy_risks(snap) == ["llm"], "pos dayanıklılık riski=llm")
    expect(open_circuit_count(snap["adapters"]) == 1, "pos açık circuit=1")
    expect(aggregate_cost(snap["categories"]) == {"today": 2.0, "mtd": 4.0}, "pos maliyet toplamı")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(error_rate_tone(0.9) != error_rate_tone(2.4), "neg farklı hata oranı farklı ton")
    expect(rollup_health(["healthy", "healthy"]) != "down", "neg tüm sağlıklı rollup down değil")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{cost} / {unit}") == {"cost", "unit"}, "çoklu placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 50, "spec ≥50 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "ProvidersSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "categories": [{
                "category": "stt|tts|llm|telephony", "primaryId": "str",
                "fallbackOrder": "str[] (adapter id)", "deterministicFallback": "bool (FR-LLM-010/SAD §8.3)",
                "cost": {"today": "num", "mtd": "num", "unit": "minute|kchars|ktokens", "unitCost": "num"}
            }],
            "adapters": [{
                "id": "str", "category": "stt|tts|llm|telephony", "role": "primary|secondary",
                "name": "str (vendor-NÖTR iç etiket — somut marka DEĞİL)", "region": "uk|eu|na|me",
                "health": "healthy|degraded|down (SAD §8.1)", "circuit": "closed|half_open|open (SAD §8.2)",
                "errorRatePct": "num [0,100]", "p95LatencyMs": "num"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular.",
        "error_rate_tone": {">=5": "danger", ">=1": "warning", "else": "success"},
        "min_operational_providers": MIN_OPERATIONAL_PROVIDERS,
        "fallback_active": "birincil adapter health=down VEYA circuit=open"
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p04_providers_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
