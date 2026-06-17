#!/usr/bin/env python3
# WBS 13.3.1 — T-01 "Tenant Dashboard" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (utilizationPct/headroom/budgetUsagePct/aggregateUsage/
#               tone'lar/assertNoPii) + samples/* snapshot doğrulaması (totals/budget beklentisi + PII-free)
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/dashboard.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t01-dashboard-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "dashboard", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "dashboard.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/dashboard.ts ile birebir) ─────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "pii", "email", "ssn"]


def utilization_pct(used, limit):
    if limit <= 0:
        return 0.0
    pct = (used / limit) * 100.0
    return min(100.0, max(0.0, round(pct * 10) / 10))


def headroom(used, limit):
    return max(0, limit - used)


def budget_usage_pct(spent, budget):
    if budget <= 0:
        return 0.0
    return max(0.0, round((spent / budget) * 1000) / 10)


def health_tone(h):
    return {"healthy": "success", "degraded": "warning", "down": "danger"}[h]


def util_tone(pct):
    if pct >= 90:
        return "danger"
    if pct >= 75:
        return "warning"
    return "success"


def budget_tone(pct):
    if pct >= 100:
        return "danger"
    if pct >= 80:
        return "warning"
    return "success"


def aggregate_usage(usage):
    return {"calls": sum(u["calls"] for u in usage), "minutes": sum(u["minutes"] for u in usage)}


def worst_quota_tone(quota):
    worst = "success"
    for q in quota:
        tone = util_tone(utilization_pct(q["used"], q["limit"]))
        if tone == "danger":
            return "danger"
        if tone == "warning":
            worst = "warning"
    return worst


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

    # S0/S1 — ekran sayfası mevcut + işaretli + iskelet değil
    chk(spec.get("wbs") == "13.3.1", "S0 spec.wbs=13.3.1")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/dashboard/page.tsx mevcut")
    chk('data-screen="T-01"' in page, 'S1 data-screen="T-01" işaretli')
    chk("İskelet ekran — T-01" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/dashboard" in page, "S2 veri seam (lib/tenant/dashboard) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t01.*); hardcoded TR/EN cümle yok
    chk("screen.t01." in page, "S3 screen.t01.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + DASHBOARD HİJYENİ guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/dashboard.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getTenantDashboard assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/iş-içeriği alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 dört içerik öğesi karşılanır (bölüm anahtarları)
    sec = tr.get("screen", {}).get("t01", {}).get("section", {})
    chk("kpis" in sec, "S5 'tenant KPI'ları' → section.kpis")
    chk("usage" in sec, "S5 'kullanım' → section.usage")
    chk("cost" in sec, "S5 'maliyet' → section.cost")
    chk("quota" in sec, "S5 'atanan kaynak kotası tüketimi' → section.quota")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t01.{rk}"
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
        vt = resolve(tr, f"screen.t01.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("utilizationPct", "headroom", "budgetUsagePct", "aggregateUsage",
               "healthTone", "utilTone", "budgetTone", "worstQuotaTone"):
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


def _extract_data_fields(ts):
    """dashboard.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # utilizationPct
    chk(utilization_pct(180, 300) == 60.0, "util 180/300=60.0")
    chk(utilization_pct(5, 0) == 0.0, "util limit=0 → 0")
    chk(utilization_pct(400, 300) == 100.0, "util kıstırma ≤100")
    chk(utilization_pct(-3, 10) == 0.0, "util kıstırma ≥0")
    # headroom
    chk(headroom(180, 300) == 120, "headroom 120")
    chk(headroom(400, 300) == 0, "headroom negatif olamaz")
    # budgetUsagePct (üst sınır YOK — aşım görünür)
    chk(budget_usage_pct(6840.75, 9000.0) == 76.0, "budget 6840.75/9000=76.0")
    chk(budget_usage_pct(9900, 9000) == 110.0, "budget aşım 110.0 (üst sınır yok)")
    chk(budget_usage_pct(5, 0) == 0.0, "budget budget=0 → 0")
    # tone eşlemeleri
    chk(health_tone("healthy") == "success" and health_tone("degraded") == "warning" and health_tone("down") == "danger", "health→tone")
    chk(util_tone(60) == "success" and util_tone(80) == "warning" and util_tone(95) == "danger", "util→tone eşik")
    chk(budget_tone(76) == "success" and budget_tone(85) == "warning" and budget_tone(110) == "danger", "budget→tone eşik")
    # aggregateUsage
    chk(aggregate_usage([{"calls": 1420, "minutes": 4380}, {"calls": 420, "minutes": 1190}]) == {"calls": 1840, "minutes": 5570}, "aggregate toplam")
    chk(aggregate_usage([]) == {"calls": 0, "minutes": 0}, "aggregate boş → 0")
    # worstQuotaTone
    chk(worst_quota_tone([{"used": 1, "limit": 10}, {"used": 9, "limit": 10}]) == "danger", "worstQuota danger baskın")
    chk(worst_quota_tone([{"used": 1, "limit": 10}, {"used": 8, "limit": 10}]) == "warning", "worstQuota warning")
    chk(worst_quota_tone([{"used": 1, "limit": 10}]) == "success", "worstQuota success")
    # assertNoPii
    chk(assert_no_pii({"kpis": {"callsToday": 1}}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"tenantName": "Acme", "tenantRef": "TEN-1"}) is None, "assertNoPii tenant kimliği İZİNLİ")

    # samples doğrulaması
    for name in ("dashboard-healthy.json", "dashboard-degraded.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        tot = aggregate_usage(snap["usage"])
        chk(tot["calls"] == exp.get("total_calls"), f"{name} total_calls={exp.get('total_calls')}")
        chk(tot["minutes"] == exp.get("total_minutes"), f"{name} total_minutes={exp.get('total_minutes')}")
        bp = budget_usage_pct(snap["cost"]["spentMtd"], snap["cost"]["budgetMtd"])
        chk(bp == exp.get("budget_pct"), f"{name} budget_pct={exp.get('budget_pct')}")
        chk(budget_tone(bp) == exp.get("budget_tone"), f"{name} budget_tone={exp.get('budget_tone')}")
        chk(worst_quota_tone(snap["quota"]) == exp.get("worst_quota_tone"), f"{name} worst_quota_tone={exp.get('worst_quota_tone')}")
        chk(assert_no_pii(snap) is None, f"{name} PII-free (DASHBOARD HİJYENİ)")

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
    expect(utilization_pct(50, 100) == 50.0, "pos util")
    expect(budget_usage_pct(50, 100) == 50.0, "pos budget")
    expect(aggregate_usage([{"calls": 1, "minutes": 2}]) == {"calls": 1, "minutes": 2}, "pos aggregate")
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(worst_quota_tone([]) == "success", "pos worstQuota boş → success")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(assert_no_pii({"calls": [{"callerId": "x"}]}) is not None, "neg callerId yakalanır")
    expect(util_tone(95) == "danger", "neg yüksek util danger")
    expect(budget_tone(120) == "danger", "neg bütçe aşımı danger")
    expect(utilization_pct(999, 100) == 100.0, "neg aşırı util kıstırılır")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 45, "spec ≥45 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "TenantDashboardSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "plan": "starter|scale|enterprise", "region": "uk|eu|na|me", "health": "healthy|degraded|down",
            "kpis": {"callsToday": "int", "callsMtd": "int", "containmentPct": "float",
                     "avgHandleSeconds": "int", "csat": "float", "successRatePct": "float", "activeAgents": "int"},
            "usage": [{"channel": "inbound|outbound", "calls": "int", "minutes": "int"}],
            "cost": {"currency": "str", "costToday": "float", "costMtd": "float", "costPerMinute": "float",
                     "budgetMtd": "float", "spentMtd": "float"},
            "quota": [{"resource": "concurrent_calls|cps|compute_vcpu|compute_memory_gb",
                       "used": "int", "limit": "int", "unit": "str"}]
        },
        "dashboard_hijyeni": "FORBIDDEN_PII_KEYS dışı alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. tenantRef/tenantName izinli."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t01_dashboard_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
