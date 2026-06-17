#!/usr/bin/env python3
# WBS 13.2.3 — P-03 "Kaynak & Kapasite Yönetimi" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (utilizationPct/headroomPct/utilizationTone/aggregateQuota/
#               regionConcurrencyUsed/isolationTone/scaleStateTone/noisyNeighborRisks/assertNoPii)
#               + samples/* snapshot doğrulaması (kota toplamı + noisy-neighbor + PII-free)
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/resources.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p03-resources-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "resources", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "resources.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

NOISY_NEIGHBOR_UTIL_PCT = 85


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/resources.ts ile birebir) ───────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "pii", "email", "ssn"]

ISOLATION_TONE = {"reserved": "success", "shared": "warning"}
SCALE_STATE_TONE = {"active": "success", "idle": "info", "scaled_to_zero": "neutral"}
QUOTA_FIELDS = ["concurrency", "cps", "vcpu", "memoryGb"]


def utilization_pct(used, limit):
    if limit <= 0:
        return 0.0
    pct = (used / limit) * 100.0
    return max(0.0, round(pct * 10) / 10)


def headroom_pct(used, limit):
    h = 100.0 - utilization_pct(used, limit)
    return min(100.0, max(0.0, round(h * 10) / 10))


def utilization_tone(pct):
    if pct >= 90:
        return "danger"
    if pct >= 75:
        return "warning"
    return "success"


def isolation_tone(mode):
    return ISOLATION_TONE[mode]


def scale_state_tone(s):
    return SCALE_STATE_TONE[s]


def aggregate_quota(tenants, field):
    acc = {"limit": 0, "used": 0}
    for t in tenants:
        acc["limit"] += t[field]["limit"]
        acc["used"] += t[field]["used"]
    return acc


def region_concurrency_used(tenants, region):
    return sum(t["concurrency"]["used"] for t in tenants if t["region"] == region)


def noisy_neighbor_risks(tenants):
    return [t["id"] for t in tenants
            if t["isolation"] == "shared"
            and utilization_pct(t["concurrency"]["used"], t["concurrency"]["limit"]) >= NOISY_NEIGHBOR_UTIL_PCT]


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
    """resources.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.3", "S0 spec.wbs=13.2.3")
    chk(os.path.isfile(PAGE_PATH), "S1 resources/page.tsx mevcut")
    chk('data-screen="P-03"' in page, 'S1 data-screen="P-03" işaretli')
    chk("İskelet ekran — P-03" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/resources" in page, "S2 veri seam (lib/platform/resources) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p03.*); hardcoded TR/EN cümle yok
    chk("screen.p03." in page, "S3 screen.p03.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/resources.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getResources assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (kotalar + autoscale + scale-to-zero + noisy-neighbor)
    p03 = tr.get("screen", {}).get("p03", {})
    kpi = p03.get("kpi", {})
    chk(all(x in kpi for x in ("concurrency", "cps", "vcpu", "memory")), "S5 eşzamanlılık/CPS/vCPU/bellek kotası → kpi.*")
    chk("autoscale" in p03.get("section", {}), "S5 autoscale politikası → section.autoscale")
    chk("scale_to_zero" in p03.get("col", {}) and "s2z" in p03, "S5 scale-to-zero → s2z.* + col.scale_to_zero")
    chk("isolation" in p03 and "noisy_neighbor_alert" in p03, "S5 noisy-neighbor koruması → isolation.* + noisy_neighbor_alert")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p03.{rk}"
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
        vt = resolve(tr, f"screen.p03.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("utilizationPct", "headroomPct", "utilizationTone", "aggregateQuota",
               "regionConcurrencyUsed", "isolationTone", "scaleStateTone", "noisyNeighborRisks"):
        chk(fn in data, f"S7 {fn} tanımlı")
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


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # utilizationPct
    chk(utilization_pct(1090, 1200) == 90.8, "util 1090/1200=90.8")
    chk(utilization_pct(0, 0) == 0.0, "util limit=0 → 0")
    chk(utilization_pct(0, 150) == 0.0, "util used=0 → 0")
    chk(utilization_pct(150, 100) == 150.0, "util aşım görünür (150)")
    # headroomPct
    chk(headroom_pct(90, 100) == 10.0, "headroom 90/100=10")
    chk(headroom_pct(150, 100) == 0.0, "headroom aşımda 0'a kıstırılır")
    # utilizationTone
    chk(utilization_tone(90.8) == "danger", "tone ≥90 danger")
    chk(utilization_tone(80) == "warning", "tone ≥75 warning")
    chk(utilization_tone(60) == "success", "tone <75 success")
    # isolation/scale tones
    chk(isolation_tone("reserved") == "success", "reserved→success")
    chk(isolation_tone("shared") == "warning", "shared→warning")
    chk(scale_state_tone("active") == "success", "s2z active→success")
    chk(scale_state_tone("idle") == "info", "s2z idle→info")
    chk(scale_state_tone("scaled_to_zero") == "neutral", "s2z scaled_to_zero→neutral")
    # assertNoPii
    chk(assert_no_pii({"tenants": [{"name": "Acme", "plan": "growth"}]}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"tenants": [{"transcript": "x"}]}) == "$.tenants[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")

    # samples doğrulaması
    for name in ("resources-mixed.json", "resources-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        tenants = snap["tenants"]
        for f in QUOTA_FIELDS:
            agg = aggregate_quota(tenants, f)
            chk(agg == exp["aggregate"][f], f"{name} aggregate.{f}={exp['aggregate'][f]}")
        chk(noisy_neighbor_risks(tenants) == exp["noisy_neighbor"], f"{name} noisy_neighbor={exp['noisy_neighbor']}")
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
    expect(utilization_pct(372, 400) == 93.0, "pos util 372/400=93")
    expect(utilization_tone(93.0) == "danger", "pos kritik tone")
    expect(assert_no_pii({"name": "Acme"}) is None, "pos no-pii (tenant adı izinli)")
    expect(aggregate_quota([{"cps": {"limit": 10, "used": 4}}, {"cps": {"limit": 5, "used": 1}}], "cps") == {"limit": 15, "used": 5}, "pos aggregate toplar")
    expect(region_concurrency_used([{"region": "eu", "concurrency": {"used": 100, "limit": 1}}, {"region": "uk", "concurrency": {"used": 50, "limit": 1}}], "eu") == 100, "pos region kullanımı filtreler")
    # noisy-neighbor: shared + ≥85% → risk
    nn = noisy_neighbor_risks([
        {"id": "a", "isolation": "shared", "concurrency": {"used": 372, "limit": 400}},   # 93% → risk
        {"id": "b", "isolation": "reserved", "concurrency": {"used": 400, "limit": 400}},  # reserved → risk YOK
        {"id": "c", "isolation": "shared", "concurrency": {"used": 96, "limit": 300}},     # 32% → risk YOK
    ])
    expect(nn == ["a"], "pos noisy-neighbor yalnız shared+yüksek")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(utilization_pct(50, 100) != utilization_pct(90, 100), "neg farklı kullanım farklı yüzde")
    expect(noisy_neighbor_risks([{"id": "r", "isolation": "reserved", "concurrency": {"used": 999, "limit": 100}}]) == [], "neg rezerve tenant noisy-neighbor değil")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{used} / {limit}") == {"used", "limit"}, "çoklu placeholder parse")
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
        "ResourcesSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "autoscale": {
                "minWorkers": "int", "maxWorkers": "int", "targetUtilizationPct": "int",
                "warmPool": "int (FR-RES-013)", "scaleToZeroIdleSeconds": "int (FR-RES-007)",
                "burstMultiplier": "int (NFR 10.3 2x)"
            },
            "regions": [{
                "region": "uk|eu|na|me", "concurrencyCapacity": "int", "cpsCapacity": "int",
                "activeWorkers": "int", "maxWorkers": "int"
            }],
            "tenants": [{
                "id": "str", "name": "str (tenant org adı — izinli; son-müşteri PII değil)",
                "plan": "starter|growth|enterprise|dedicated", "region": "uk|eu|na|me",
                "concurrency": "{limit,used}", "cps": "{limit,used}",
                "vcpu": "{limit,used}", "memoryGb": "{limit,used}",
                "reservedConcurrency": "int (noisy-neighbor koruması, SAD §16.2)",
                "isolation": "reserved|shared", "scaleToZero": "active|idle|scaled_to_zero"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular.",
        "noisy_neighbor_util_pct": NOISY_NEIGHBOR_UTIL_PCT,
        "util_tone": {">=90": "danger", ">=75": "warning", "else": "success"}
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p03_resources_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
