#!/usr/bin/env python3
# WBS 13.2.5 — P-05 "Platform Faturalandırma & Rate-Card" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (marginPct/marginTone/budgetTone/billingStatusTone/planStatusTone/
#               overageMinutes/rateMarginPct/aggregateUsage/overBudgetTenants/planTenantCount/countByBillingStatus/
#               activePlanCount/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/billing.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p05-billing-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "billing", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "billing.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

BUDGET_DANGER_PCT = 100
BUDGET_WARNING_PCT = 80
MARGIN_HEALTHY_PCT = 30
MARGIN_WARNING_PCT = 15


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/billing.ts ile birebir) ─────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "iban",
                      "pii", "email", "ssn"]

BILLING_STATUS_TONE = {"current": "success", "over_budget": "warning", "suspended": "danger"}
PLAN_STATUS_TONE = {"active": "success", "deprecated": "neutral"}


def margin_pct(revenue, cost):
    if revenue <= 0:
        return 0.0
    return ((revenue - cost) / revenue) * 100


def margin_tone(pct):
    if pct >= MARGIN_HEALTHY_PCT:
        return "success"
    if pct >= MARGIN_WARNING_PCT:
        return "warning"
    return "danger"


def budget_tone(pct):
    if pct >= BUDGET_DANGER_PCT:
        return "danger"
    if pct >= BUDGET_WARNING_PCT:
        return "warning"
    return "success"


def billing_status_tone(s):
    return BILLING_STATUS_TONE[s]


def plan_status_tone(s):
    return PLAN_STATUS_TONE[s]


def overage_minutes(billed, included):
    return max(0, billed - included)


def rate_margin_pct(e):
    return margin_pct(e["unitRate"], e["unitCost"])


def aggregate_usage(tenants):
    billed = sum(t["billedMinutes"] for t in tenants)
    overage = sum(overage_minutes(t["billedMinutes"], t["includedMinutes"]) for t in tenants)
    return {"billedMinutes": billed, "overageMinutes": overage}


def over_budget_tenants(snap):
    return [t["tenantId"] for t in snap["tenants"] if t["budgetUsedPct"] >= BUDGET_DANGER_PCT]


def plan_tenant_count(plans, plan_id):
    p = next((p for p in plans if p["id"] == plan_id), None)
    return p["activeTenants"] if p else 0


def count_by_billing_status(tenants):
    acc = {"current": 0, "over_budget": 0, "suspended": 0}
    for t in tenants:
        acc[t["status"]] += 1
    return acc


def active_plan_count(plans):
    return len([p for p in plans if p["status"] == "active"])


def plan_name(plans, plan_id):
    p = next((p for p in plans if p["id"] == plan_id), None)
    return p["name"] if p else plan_id


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
    """billing.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.5", "S0 spec.wbs=13.2.5")
    chk(os.path.isfile(PAGE_PATH), "S1 billing/page.tsx mevcut")
    chk('data-screen="P-05"' in page, 'S1 data-screen="P-05" işaretli')
    chk("İskelet ekran — P-05" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/billing" in page, "S2 veri seam (lib/platform/billing) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p05.*); hardcoded TR/EN cümle yok
    chk("screen.p05." in page, "S3 screen.p05.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/billing.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getBilling assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")
    chk("tenantName" in data, "S4 tenantName (org adı = tenant kimliği) izinli alan mevcut")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (plan tanımları + rate-card + kullanım toplulaştırma)
    p05 = tr.get("screen", {}).get("p05", {})
    sec = p05.get("section", {})
    catg = p05.get("category", {})
    chk("plans" in sec and "tier" in p05 and "plan_status" in p05, "S5 plan tanımları → section.plans + tier.* + plan_status.*")
    chk("rate_card" in sec and all(x in catg for x in ("telephony", "stt", "tts", "llm", "platform")), "S5 rate-card → section.rate_card + category.* (FR-BIL-002)")
    chk("usage" in sec and "billing_status" in p05, "S5 kullanım toplulaştırma → section.usage + billing_status.*")
    chk("over_budget_alert" in p05 and "no_over_budget" in p05, "S5 bütçe alarmı → over_budget_alert (FR-BIL-006)")
    chk("export_action" in p05, "S5 finans dışa aktarım → export_action (FR-BIL-007)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p05.{rk}"
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
        vt = resolve(tr, f"screen.p05.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("marginPct", "marginTone", "budgetTone", "billingStatusTone", "planStatusTone",
               "overageMinutes", "rateMarginPct", "aggregateUsage", "overBudgetTenants",
               "planTenantCount", "countByBillingStatus", "activePlanCount", "planName"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral (somut sağlayıcı/ticari marka yok) + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "deepgram", "elevenlabs", "cartesia",
                         "telnyx", "stripe", "chargebee", "datadog.com", "api_key", "secret="]
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

    # marginPct / marginTone
    chk(round(margin_pct(100, 60), 1) == 40.0, "margin (100,60)→40%")
    chk(margin_pct(0, 0) == 0.0, "margin gelir 0 → 0")
    chk(margin_tone(40) == "success", "margin ≥30 success")
    chk(margin_tone(20) == "warning", "margin ≥15 warning")
    chk(margin_tone(10) == "danger", "margin <15 danger")
    # budgetTone (FR-BIL-006)
    chk(budget_tone(104) == "danger", "budget ≥100 danger")
    chk(budget_tone(92) == "warning", "budget ≥80 warning")
    chk(budget_tone(58) == "success", "budget <80 success")
    # status tonları
    chk(billing_status_tone("over_budget") == "warning", "billing over_budget→warning")
    chk(billing_status_tone("suspended") == "danger", "billing suspended→danger")
    chk(plan_status_tone("deprecated") == "neutral", "plan deprecated→neutral")
    # overageMinutes (FR-BIL-004)
    chk(overage_minutes(8200, 7500) == 700, "overage 8200/7500=700")
    chk(overage_minutes(1000, 1000) == 0, "overage kota tam=0")
    chk(overage_minutes(900, 1000) == 0, "overage kota altı=0")
    # assertNoPii
    chk(assert_no_pii({"tenants": [{"tenantName": "Kuzey Bank A.Ş.", "billedMinutes": 10}]}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"tenants": [{"transcript": "x"}]}) == "$.tenants[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"iban": "x"}) == "$.iban", "assertNoPii iban yakalar")

    # samples doğrulaması
    for name in ("billing-mixed.json", "billing-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        tenants = snap["tenants"]
        agg = aggregate_usage(tenants)
        chk(agg == exp["aggregate_usage"], f"{name} aggregate_usage={exp['aggregate_usage']}")
        chk(over_budget_tenants(snap) == exp["over_budget_tenants"], f"{name} over_budget_tenants={exp['over_budget_tenants']}")
        chk(count_by_billing_status(tenants) == exp["count_by_billing_status"], f"{name} count_by_billing_status={exp['count_by_billing_status']}")
        chk(active_plan_count(snap["plans"]) == exp["active_plans"], f"{name} active_plans={exp['active_plans']}")
        u = snap["usage"]
        chk(round(margin_pct(u["revenue"], u["providerCost"]), 1) == exp["margin_pct"], f"{name} margin_pct={exp['margin_pct']}")
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

    # pozitif — eşikler tam sınırda
    expect(budget_tone(100) == "danger", "pos bütçe tam 100→danger")
    expect(budget_tone(80) == "warning", "pos bütçe tam 80→warning")
    expect(margin_tone(30) == "success", "pos marj tam 30→success")
    expect(margin_tone(15) == "warning", "pos marj tam 15→warning")
    expect(assert_no_pii({"tenantName": "Meridyen Sigorta"}) is None, "pos no-pii (tenant org adı izinli)")
    # rate-card marjı
    expect(round(rate_margin_pct({"unitRate": 0.025, "unitCost": 0.011}), 1) == 56.0, "pos rate marj (0.025,0.011)→56%")
    expect(rate_margin_pct({"unitRate": 0.0, "unitCost": 0.0}) == 0.0, "pos rate marj satış 0→0")
    # toplulaştırma + bütçe
    snap = {
        "currency": "USD",
        "plans": [
            {"id": "growth", "name": "Büyüme", "activeTenants": 5, "status": "active"},
            {"id": "starter-legacy", "name": "Başlangıç (eski)", "activeTenants": 1, "status": "deprecated"},
        ],
        "usage": {"billedMinutes": 200, "revenue": 100.0, "providerCost": 40.0},
        "tenants": [
            {"tenantId": "t1", "tenantName": "A", "planId": "growth", "billedMinutes": 8200, "includedMinutes": 7500, "budgetUsedPct": 104, "status": "over_budget"},
            {"tenantId": "t2", "tenantName": "B", "planId": "growth", "billedMinutes": 6000, "includedMinutes": 7500, "budgetUsedPct": 60, "status": "current"},
            {"tenantId": "t3", "tenantName": "C", "planId": "starter-legacy", "billedMinutes": 0, "includedMinutes": 800, "budgetUsedPct": 0, "status": "suspended"},
        ],
    }
    expect(aggregate_usage(snap["tenants"]) == {"billedMinutes": 14200, "overageMinutes": 700}, "pos toplulaştırma billed+overage")
    expect(over_budget_tenants(snap) == ["t1"], "pos bütçe aşan tenant=t1")
    expect(count_by_billing_status(snap["tenants"]) == {"current": 1, "over_budget": 1, "suspended": 1}, "pos durum sayımı")
    expect(active_plan_count(snap["plans"]) == 1, "pos aktif plan=1 (deprecated hariç)")
    expect(plan_tenant_count(snap["plans"], "growth") == 5, "pos plan tenant sayısı=5")
    expect(plan_name(snap["plans"], "growth") == "Büyüme", "pos plan adı çözümleme")
    expect(plan_name(snap["plans"], "yok") == "yok", "pos bilinmeyen plan → id")
    expect(round(margin_pct(100, 40), 1) == 60.0, "pos usage marjı 60%")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(budget_tone(79) != budget_tone(80), "neg bütçe eşik kenarı farklı ton")
    expect(margin_tone(14.9) == "danger", "neg marj <15 danger")
    expect(overage_minutes(500, 1000) == 0, "neg kota altı overage 0")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{amount} / {unit}") == {"amount", "unit"}, "çoklu placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 55, "spec ≥55 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "BillingSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "currency": "USD|EUR|GBP|TRY (ISO 4217; vendor-nötr)",
            "rateCard": [{
                "category": "telephony|stt|tts|llm|platform (FR-BIL-002)", "unit": "minute|kchars|ktokens|session",
                "unitRate": "num (satış)", "unitCost": "num (sağlayıcı maliyeti)"
            }],
            "plans": [{
                "id": "str", "tier": "starter|growth|scale|enterprise", "name": "str (vendor-NÖTR plan adı)",
                "monthlyBase": "num (FR-BIL-004 taban)", "includedMinutes": "num (kota)",
                "overageRatePerMinute": "num (FR-BIL-004 overage)", "budgetAlertThresholdPct": "num (FR-BIL-006)",
                "activeTenants": "num (toplulaştırılmış sayım)", "status": "active|deprecated"
            }],
            "usage": {"billedMinutes": "num (FR-BIL-001)", "revenue": "num", "providerCost": "num (FR-BIL-002)"},
            "tenants": [{
                "tenantId": "str", "tenantName": "str (org adı = tenant kimliği — izinli)", "planId": "str",
                "region": "uk|eu|na|me", "billedMinutes": "num", "includedMinutes": "num",
                "budgetUsedPct": "num (FR-BIL-006)", "status": "current|over_budget|suspended"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. tenantName (org adı) izinli.",
        "budget_tone": {">=100": "danger", ">=80": "warning", "else": "success"},
        "margin_tone": {">=30": "success", ">=15": "warning", "else": "danger"},
        "overage": "max(0, billed - included)"
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p05_billing_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
