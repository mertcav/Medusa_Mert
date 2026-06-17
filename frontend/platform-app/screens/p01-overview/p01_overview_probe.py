#!/usr/bin/env python3
# WBS 13.2.1 — P-01 "Platform Genel Bakış" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (rollupHealth/utilizationPct/headroom/tone/assertNoPii) +
#               samples/* snapshot doğrulaması (overall/headroom beklentisi + PII-free)
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/overview.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "p01-overview-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "overview", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "overview.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/overview.ts ile birebir) ────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "pii", "email", "ssn"]


def rollup_health(regions):
    if any(r["health"] == "down" for r in regions):
        return "down"
    if any(r["health"] == "degraded" for r in regions):
        return "degraded"
    return "healthy"


def utilization_pct(used, capacity):
    if capacity <= 0:
        return 0.0
    pct = (used / capacity) * 100.0
    return min(100.0, max(0.0, round(pct * 10) / 10))


def headroom(used, capacity):
    return max(0, capacity - used)


def health_tone(h):
    return {"healthy": "success", "degraded": "warning", "down": "danger"}[h]


def severity_tone(s):
    return {"critical": "danger", "warning": "warning", "info": "info"}[s]


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği alan adı bulursa (path) döndürür; yoksa None."""
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

    # S1 — ekran sayfası mevcut + işaretli + iskelet değil
    chk(spec.get("wbs") == "13.2.1", "S0 spec.wbs=13.2.1")
    chk(os.path.isfile(PAGE_PATH), "S1 overview/page.tsx mevcut")
    chk('data-screen="P-01"' in page, 'S1 data-screen="P-01" işaretli')
    chk("İskelet ekran — P-01" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/overview" in page, "S2 veri seam (lib/platform/overview) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p01.*); hardcoded TR/EN cümle yok
    chk("screen.p01." in page, "S3 screen.p01.* anahtarları referans alınır")
    # JSX text node'larında düz cümle olmamalı (>Türkçe/İngilizce kelime<). t()/k() ile gelmeli.
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/overview.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getPlatformOverview assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/iş-içeriği alanı yok (sızıntı={leak})")

    # S5 — BRD §17.3 dört içerik öğesi karşılanır (bölüm anahtarları)
    sec = tr.get("screen", {}).get("p01", {}).get("section", {})
    chk("capacity" in sec, "S5 'toplam eşzamanlı çağrı' → section.capacity")
    chk("resources" in sec, "S5 'kaynak (CPU/bellek/density)' → section.resources")
    chk("cost" in sec, "S5 'platform maliyeti' → section.cost")
    chk("regions" in sec, "S5 'cross-tenant sağlık' → section.regions")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p01.{rk}"
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
        vt = resolve(tr, f"screen.p01.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("rollupHealth", "utilizationPct", "headroom", "healthTone", "severityTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    # yorum metnindeki "Date.now/rastgelelik içermez" açıklamasını eleme: çağrı-biçimini ara.
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "datadog.com", "api_key", "secret="]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def _extract_data_fields(ts):
    """overview.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # rollupHealth
    chk(rollup_health([{"health": "healthy"}, {"health": "healthy"}]) == "healthy", "rollup hepsi healthy → healthy")
    chk(rollup_health([{"health": "healthy"}, {"health": "degraded"}]) == "degraded", "rollup bir degraded → degraded")
    chk(rollup_health([{"health": "healthy"}, {"health": "down"}, {"health": "degraded"}]) == "down", "rollup down baskın")
    chk(rollup_health([]) == "healthy", "rollup boş → healthy")
    # utilizationPct
    chk(utilization_pct(6240, 10000) == 62.4, "util 6240/10000=62.4")
    chk(utilization_pct(5, 0) == 0.0, "util capacity=0 → 0")
    chk(utilization_pct(12000, 10000) == 100.0, "util kıstırma ≤100")
    chk(utilization_pct(-3, 10) == 0.0, "util kıstırma ≥0")
    # headroom
    chk(headroom(6240, 10000) == 3760, "headroom 3760")
    chk(headroom(12000, 10000) == 0, "headroom negatif olamaz")
    # tone eşlemeleri
    chk(health_tone("healthy") == "success" and health_tone("degraded") == "warning" and health_tone("down") == "danger", "health→tone")
    chk(severity_tone("critical") == "danger" and severity_tone("warning") == "warning" and severity_tone("info") == "info", "severity→tone")
    # assertNoPii
    chk(assert_no_pii({"kpis": {"concurrentCalls": 1}}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")

    # samples doğrulaması
    for name in ("overview-healthy.json", "overview-degraded.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(rollup_health(snap["regions"]) == exp.get("overall"), f"{name} overall={exp.get('overall')}")
        chk(headroom(snap["kpis"]["concurrentCalls"], snap["kpis"]["capacityConcurrent"]) == exp.get("headroom"),
            f"{name} headroom={exp.get('headroom')}")
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
    expect(rollup_health([{"health": "healthy"}]) == "healthy", "pos rollup")
    expect(utilization_pct(50, 100) == 50.0, "pos util")
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(rollup_health([{"health": "down"}]) == "down", "neg down yayılır")
    expect(utilization_pct(999, 100) == 100.0, "neg aşırı util kıstırılır")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 40, "spec ≥40 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "PlatformOverviewSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "kpis": {"concurrentCalls": "int", "callsPerSecond": "int", "capacityConcurrent": "int",
                     "cpuUtilizationPct": "float", "memoryUtilizationPct": "float", "workerDensity": "int",
                     "memPerSessionMb": "float", "activeTenants": "int"},
            "regions": [{"region": "uk|eu|na|me", "health": "healthy|degraded|down",
                         "concurrentCalls": "int", "utilizationPct": "float"}],
            "cost": {"currency": "str", "platformCostToday": "float", "platformCostMtd": "float",
                     "costPerMinute": "float"},
            "alerts": [{"id": "str", "key": "i18n key", "severity": "critical|warning|info",
                        "sinceMinutes": "int"}]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p01_overview_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
