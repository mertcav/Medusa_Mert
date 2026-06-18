#!/usr/bin/env python3
# WBS 13.3.7 — T-07 "Faturalandırma & Kullanım" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (costTotal/budgetRatio/overBudget/budgetApproaching/triggeredAlarms/
#               unconfiguredAlarms/quotaOverageMinutes/overageBlocked/usageLimitExceeded/costMismatch/invalidPlan/
#               invoiceExport*/openWarningCount/tone'lar/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/billing.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t07-billing-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "billing", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "billing.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"
COST_RECONCILE_TOLERANCE = 0.5


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/billing.ts ile birebir) ──────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "customer", "cdr",
                      "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey", "iban", "bankaccount",
                         "paymentmethod", "paymenttoken"]


def cost_total(costs):
    return sum(c["amount"] for c in costs)


def cost_share(costs, category):
    total = cost_total(costs)
    if total <= 0:
        return 0.0
    part = sum(c["amount"] for c in costs if c["category"] == category)
    return part / total


def budget_ratio(b):
    if b["budgetAmount"] <= 0:
        return 0.0
    return b["spentAmount"] / b["budgetAmount"]


def over_budget(b):
    return b["budgetAmount"] > 0 and b["spentAmount"] > b["budgetAmount"]


def budget_approaching(b):
    r = budget_ratio(b)
    return 0.8 <= r <= 1.0


def triggered_alarms(b):
    pct = budget_ratio(b) * 100
    return [a["id"] for a in b["alarms"] if pct >= a["thresholdPct"]]


def unconfigured_alarms(b):
    return b["budgetAmount"] > 0 and len(b["alarms"]) == 0


def quota_overage_minutes(u):
    over = u["billedMinutes"] - u["includedMinutes"]
    return over if over > 0 else 0


def overage_blocked(u, o):
    return quota_overage_minutes(u) > 0 and not o["overageEnabled"]


def usage_limit_exceeded(u, b):
    return b["usageLimitMinutes"] > 0 and u["billedMinutes"] > b["usageLimitMinutes"]


def cost_mismatch(snap):
    return abs(cost_total(snap["costs"]) - snap["budget"]["spentAmount"]) > COST_RECONCILE_TOLERANCE


def invalid_plan(p):
    out = []
    if p["minimumCharge"] < 0:
        out.append("minimum_charge")
    if p["planName"].strip() == "":
        out.append("plan_name")
    return out


def invoice_export_failed(e):
    return e["status"] == "failed"


def invoice_export_unconfigured(e):
    return e["status"] == "not_configured"


def open_warning_count(snap):
    return ((1 if over_budget(snap["budget"]) else 0)
            + (1 if usage_limit_exceeded(snap["usage"], snap["budget"]) else 0)
            + (1 if budget_approaching(snap["budget"]) else 0)
            + (1 if unconfigured_alarms(snap["budget"]) else 0)
            + (1 if overage_blocked(snap["usage"], snap["overage"]) else 0)
            + (1 if cost_mismatch(snap) else 0)
            + (1 if invoice_export_failed(snap["invoiceExport"]) else 0)
            + (1 if invoice_export_unconfigured(snap["invoiceExport"]) else 0)
            + len(invalid_plan(snap["plan"])))


def budget_ratio_tone(ratio):
    if ratio > 1.0:
        return "danger"
    if ratio >= 0.8:
        return "warning"
    return "success"


def invoice_status_tone(s):
    return {"synced": "success", "pending": "warning", "failed": "danger", "not_configured": "neutral"}[s]


def tier_tone(t):
    return {"pilot": "neutral", "standard": "neutral", "enterprise": "info", "dedicated": "info"}[t]


def overage_tone(enabled):
    return "info" if enabled else "neutral"


def alarm_triggered_tone(triggered):
    return "warning" if triggered else "neutral"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/finansal credential alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_pii(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            low = k.lower()
            if low in FORBIDDEN_PII_KEYS or low in FORBIDDEN_SECRET_KEYS:
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
    chk(spec.get("wbs") == "13.3.7", "S0 spec.wbs=13.3.7")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/billing/page.tsx mevcut")
    chk('data-screen="T-07"' in page, 'S1 data-screen="T-07" işaretli')
    chk("İskelet ekran — T-07" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/billing" in page, "S2 veri seam (lib/tenant/billing) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t07.*); hardcoded TR/EN cümle yok
    chk("screen.t07." in page, "S3 screen.t07.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/billing.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getBilling assertNoPii çağırır")
    chk("cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 çağrı-bazlı CDR yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 içerik öğeleri + FR-BIL-001..007 karşılanır
    t07 = tr.get("screen", {}).get("t07", {})
    sec = t07.get("section", {})
    for s in ("plan", "usage", "cost", "overage", "budget", "export"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.4 / FR-BIL içerik öğesi)")
    chk(set(["per_minute", "per_second", "tiered", "flat"]).issubset(t07.get("billing_model", {}).keys()), "S5 faturalama modeli dakika/saniye (FR-BIL-001)")
    chk(set(["telecom", "stt", "tts", "llm", "platform"]).issubset(t07.get("category", {}).keys()), "S5 maliyet bileşenleri ayrı (FR-BIL-002)")
    chk("plan_name" in t07.get("field", {}) and "tier" in t07.get("field", {}), "S5 tenant fiyat planı (FR-BIL-003)")
    chk(set(["minimum_charge", "included_minutes", "quota_overage"]).issubset(t07.get("field", {}).keys()), "S5 minimum/kota/overage (FR-BIL-004)")
    chk("dedicated_infra" in t07.get("field", {}), "S5 dedicated altyapı ayrı faturalandırma (FR-BIL-005)")
    chk(set(["usage_limit", "budget_amount", "spent_amount"]).issubset(t07.get("field", {}).keys()), "S5 kullanım limiti + bütçe alarmı (FR-BIL-006)")
    chk(set(["synced", "pending", "failed", "not_configured"]).issubset(t07.get("export_status", {}).keys()), "S5 finans sistemine fatura aktarımı (FR-BIL-007)")
    chk("budgetRatio" in data and "costMismatch" in data and "triggeredAlarms" in data, "S5 bütçe/uzlaşı/alarm türetmeleri")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t07.{rk}"
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
        vt = resolve(tr, f"screen.t07.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("costTotal", "costShare", "budgetRatio", "overBudget", "budgetApproaching", "triggeredAlarms",
               "unconfiguredAlarms", "quotaOverageMinutes", "overageBlocked", "usageLimitExceeded",
               "costMismatch", "invalidPlan", "invoiceExportFailed", "invoiceExportUnconfigured",
               "openWarningCount", "budgetRatioTone", "invoiceStatusTone", "tierTone", "overageTone",
               "alarmTriggeredTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + illüstratif + sır yok
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "salesforce", "hubspot", "twilio.com", "stripe.com"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")
    chk("illüstratif" in (page + data).lower() or "illustrative" in json.dumps(t07, ensure_ascii=False).lower(), "S8 illüstratif/rate-card notu (FR-BIL-003 değerleri örnektir)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def _extract_data_fields(ts):
    """billing.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    costs = [{"category": "telecom", "amount": 100.0}, {"category": "stt", "amount": 40.0},
             {"category": "tts", "amount": 30.0}, {"category": "llm", "amount": 20.0},
             {"category": "platform", "amount": 10.0}]
    usage = {"billedMinutes": 600, "billedSeconds": 0, "includedMinutes": 500, "callCount": 10}
    overage_off = {"overageEnabled": False, "overageRate": 0, "overageMinutes": 0, "overageAmount": 0}
    overage_on = {"overageEnabled": True, "overageRate": 1.2, "overageMinutes": 100, "overageAmount": 120}
    budget = {"budgetAmount": 200.0, "spentAmount": 210.0, "usageLimitMinutes": 550,
              "alarms": [{"id": "A", "thresholdPct": 80, "channel": "x"}, {"id": "B", "thresholdPct": 110, "channel": "y"}]}
    plan = {"planName": "", "tier": "standard", "billingModel": "per_minute", "currency": "EUR",
            "minimumCharge": -1, "billingPeriod": "monthly", "dedicatedInfra": False}

    chk(cost_total(costs) == 200.0, "costTotal=200")
    chk(abs(cost_share(costs, "telecom") - 0.5) < 1e-9, "costShare telecom=0.5")
    chk(cost_share([], "telecom") == 0.0, "costShare boş=0")
    chk(abs(budget_ratio(budget) - 1.05) < 1e-9, "budgetRatio=1.05")
    chk(budget_ratio({"budgetAmount": 0, "spentAmount": 5, "alarms": []}) == 0.0, "budgetRatio bütçe yok=0")
    chk(over_budget(budget) is True, "overBudget=True (210>200)")
    chk(over_budget({"budgetAmount": 200, "spentAmount": 200, "alarms": []}) is False, "overBudget eşit=False")
    chk(budget_approaching({"budgetAmount": 100, "spentAmount": 90, "alarms": []}) is True, "budgetApproaching 0.9=True")
    chk(budget_approaching({"budgetAmount": 100, "spentAmount": 70, "alarms": []}) is False, "budgetApproaching 0.7=False")
    chk(budget_approaching(budget) is False, "budgetApproaching 1.05=False (aştı)")
    chk(triggered_alarms(budget) == ["A"], "triggeredAlarms=[A] (105%≥80, <110)")
    chk(unconfigured_alarms({"budgetAmount": 100, "spentAmount": 1, "alarms": []}) is True, "unconfiguredAlarms=True")
    chk(unconfigured_alarms(budget) is False, "unconfiguredAlarms alarmlı=False")
    chk(quota_overage_minutes(usage) == 100, "quotaOverageMinutes=100")
    chk(quota_overage_minutes({"billedMinutes": 400, "includedMinutes": 500}) == 0, "quotaOverageMinutes kota içi=0")
    chk(overage_blocked(usage, overage_off) is True, "overageBlocked=True (kota aşımı + overage kapalı)")
    chk(overage_blocked(usage, overage_on) is False, "overageBlocked=False (overage açık)")
    chk(usage_limit_exceeded(usage, budget) is True, "usageLimitExceeded=True (600>550)")
    chk(usage_limit_exceeded(usage, {"usageLimitMinutes": 0, "budgetAmount": 1, "spentAmount": 1, "alarms": []}) is False, "usageLimitExceeded limit yok=False")
    chk(cost_mismatch({"costs": costs, "budget": {"spentAmount": 250.0}}) is True, "costMismatch=True (200≠250)")
    chk(cost_mismatch({"costs": costs, "budget": {"spentAmount": 200.0}}) is False, "costMismatch=False (200=200)")
    chk(invalid_plan(plan) == ["minimum_charge", "plan_name"], "invalidPlan=[minimum_charge,plan_name]")
    chk(invoice_export_failed({"status": "failed"}) is True and invoice_export_failed({"status": "synced"}) is False, "invoiceExportFailed")
    chk(invoice_export_unconfigured({"status": "not_configured"}) is True, "invoiceExportUnconfigured")
    # tone eşlemeleri
    chk(budget_ratio_tone(1.2) == "danger" and budget_ratio_tone(0.9) == "warning" and budget_ratio_tone(0.5) == "success", "budgetRatioTone")
    chk(invoice_status_tone("synced") == "success" and invoice_status_tone("failed") == "danger" and invoice_status_tone("not_configured") == "neutral", "invoiceStatusTone")
    chk(tier_tone("enterprise") == "info" and tier_tone("standard") == "neutral", "tierTone")
    chk(overage_tone(True) == "info" and overage_tone(False) == "neutral", "overageTone")
    chk(alarm_triggered_tone(True) == "warning" and alarm_triggered_tone(False) == "neutral", "alarmTriggeredTone")
    # assertNoPii — kendi plan/kullanım İZİNLİ, son-müşteri PII + ödeme sırrı YASAK
    chk(assert_no_pii({"plan": {"planName": "Enterprise", "minimumCharge": 5000}}) is None, "assertNoPii plan/planName İZİNLİ")
    chk(assert_no_pii({"usage": {"billedMinutes": 100, "callCount": 5}}) is None, "assertNoPii kullanım topluluğu İZİNLİ")
    chk(assert_no_pii({"x": {"cdr": [1]}}) == "$.x.cdr", "assertNoPii çağrı-bazlı CDR yakalar")
    chk(assert_no_pii({"x": {"recording": "u"}}) == "$.x.recording", "assertNoPii ham recording yakalar")
    chk(assert_no_pii({"pay": {"paymentToken": "x"}}) == "$.pay.paymentToken", "assertNoPii ödeme token yakalar (NFR 10.6)")
    chk(assert_no_pii({"b": {"iban": "x"}}) == "$.b.iban", "assertNoPii IBAN yakalar")

    # samples doğrulaması
    for name in ("billing-clean.json", "billing-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(over_budget(snap["budget"]) == exp.get("over_budget"), f"{name} over_budget={exp.get('over_budget')}")
        chk(usage_limit_exceeded(snap["usage"], snap["budget"]) == exp.get("usage_limit_exceeded"), f"{name} usage_limit={exp.get('usage_limit_exceeded')}")
        chk(quota_overage_minutes(snap["usage"]) == exp.get("quota_overage"), f"{name} quota_overage={exp.get('quota_overage')}")
        chk(overage_blocked(snap["usage"], snap["overage"]) == exp.get("overage_blocked"), f"{name} overage_blocked={exp.get('overage_blocked')}")
        chk(cost_mismatch(snap) == exp.get("cost_mismatch"), f"{name} cost_mismatch={exp.get('cost_mismatch')}")
        chk(invalid_plan(snap["plan"]) == exp.get("invalid_plan"), f"{name} invalid_plan={exp.get('invalid_plan')}")
        chk(invoice_export_failed(snap["invoiceExport"]) == exp.get("export_failed"), f"{name} export_failed={exp.get('export_failed')}")
        chk(open_warning_count(snap) == exp.get("open_warnings"), f"{name} open_warnings={exp.get('open_warnings')}")
        chk(assert_no_pii(snap) is None, f"{name} PII/ödeme-sırrı-free (HİJYEN+GÜVENLİK)")

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

    clean_costs = [{"category": "telecom", "amount": 50.0}, {"category": "platform", "amount": 50.0}]
    clean_usage = {"billedMinutes": 400, "billedSeconds": 0, "includedMinutes": 500, "callCount": 8}
    clean_overage = {"overageEnabled": True, "overageRate": 1.0, "overageMinutes": 0, "overageAmount": 0}
    clean_budget = {"budgetAmount": 200.0, "spentAmount": 100.0, "usageLimitMinutes": 500,
                    "alarms": [{"id": "A", "thresholdPct": 80, "channel": "x"}]}
    clean_plan = {"planName": "Standart", "tier": "standard", "billingModel": "per_minute", "currency": "TRY",
                  "minimumCharge": 1000, "billingPeriod": "monthly", "dedicatedInfra": False}
    clean_export = {"status": "synced", "target": "ERP-GL", "lastSync": "2026-06-01T00:00:00.000Z"}
    # pozitif (temiz → boş)
    expect(over_budget(clean_budget) is False, "pos bütçe içinde")
    expect(budget_approaching(clean_budget) is False, "pos yaklaşma yok (0.5)")
    expect(triggered_alarms(clean_budget) == [], "pos alarm tetiklenmedi (50%<80)")
    expect(unconfigured_alarms(clean_budget) is False, "pos alarm tanımlı")
    expect(quota_overage_minutes(clean_usage) == 0, "pos kota içi")
    expect(overage_blocked(clean_usage, clean_overage) is False, "pos overage engellenmedi")
    expect(usage_limit_exceeded(clean_usage, clean_budget) is False, "pos limit aşılmadı")
    expect(cost_mismatch({"costs": clean_costs, "budget": {"spentAmount": 100.0}}) is False, "pos maliyet uzlaşır")
    expect(invalid_plan(clean_plan) == [], "pos plan geçerli")
    expect(invoice_export_failed(clean_export) is False, "pos aktarım başarılı")
    snap_clean = {"plan": clean_plan, "usage": clean_usage, "costs": clean_costs, "overage": clean_overage,
                  "budget": clean_budget, "invoiceExport": clean_export}
    expect(open_warning_count(snap_clean) == 0, "pos openWarningCount=0")
    # negatif (degrade beklendiği gibi yakalanır)
    over_b = {"budgetAmount": 100.0, "spentAmount": 130.0, "usageLimitMinutes": 0, "alarms": []}
    expect(over_budget(over_b) is True, "neg bütçe aşıldı")
    expect(unconfigured_alarms(over_b) is True, "neg alarm yok")
    expect(budget_approaching({"budgetAmount": 100.0, "spentAmount": 85.0, "alarms": []}) is True, "neg bütçeye yaklaşıyor (0.85)")
    over_usage = {"billedMinutes": 700, "billedSeconds": 0, "includedMinutes": 500, "callCount": 9}
    expect(quota_overage_minutes(over_usage) == 200, "neg kota aşımı=200")
    expect(overage_blocked(over_usage, {"overageEnabled": False}) is True, "neg overage engellendi")
    expect(usage_limit_exceeded(over_usage, {"usageLimitMinutes": 600, "budgetAmount": 1, "spentAmount": 1, "alarms": []}) is True, "neg kullanım limiti aşıldı")
    expect(cost_mismatch({"costs": clean_costs, "budget": {"spentAmount": 999.0}}) is True, "neg maliyet uzlaşmaz")
    expect(invalid_plan({"planName": "", "minimumCharge": -5}) == ["minimum_charge", "plan_name"], "neg plan tutarsız")
    expect(invoice_export_failed({"status": "failed"}) is True, "neg aktarım başarısız")
    expect(invoice_export_unconfigured({"status": "not_configured"}) is True, "neg aktarım yapılandırılmamış")
    # openWarningCount toplamı (over_budget + usage_limit + no_alarms + overage_blocked + cost_mismatch + export_failed + invalid_plan)
    snap_bad = {"plan": {"planName": "", "tier": "standard", "minimumCharge": -1, "billingModel": "per_minute", "currency": "EUR", "billingPeriod": "m", "dedicatedInfra": False},
                "usage": {"billedMinutes": 700, "billedSeconds": 0, "includedMinutes": 500, "callCount": 9},
                "costs": clean_costs,
                "overage": {"overageEnabled": False, "overageRate": 0, "overageMinutes": 0, "overageAmount": 0},
                "budget": {"budgetAmount": 100.0, "spentAmount": 130.0, "usageLimitMinutes": 600, "alarms": []},
                "invoiceExport": {"status": "failed", "target": "ERP", "lastSync": "x"}}
    # over_budget1 + usage_limit1 + approaching0 + no_alarms1 + overage_blocked1 + cost_mismatch1 + export_failed1 + export_unconfigured0 + invalid_plan2 = 8
    expect(open_warning_count(snap_bad) == 8, "neg openWarningCount toplamı=8")
    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"bankAccount": "x"}]}) is not None, "neg banka hesabı yakalanır")
    # tone sınır
    expect(budget_ratio_tone(1.0) == "warning", "neg oran 1.0 → warning")
    expect(budget_ratio_tone(0.7999) == "success", "neg oran <0.8 → success")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")

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
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "plan": {"planName": "str (plan ADI)", "tier": "pilot|standard|enterprise|dedicated", "billingModel": "per_minute|per_second|tiered|flat (FR-BIL-001)",
                     "currency": "TRY|USD|EUR|GBP", "minimumCharge": "num (FR-BIL-004)", "billingPeriod": "str", "dedicatedInfra": "bool (FR-BIL-005)"},
            "usage": {"periodLabel": "str", "billedMinutes": "int", "billedSeconds": "int (FR-BIL-001 saniye)", "includedMinutes": "int (FR-BIL-004 kota)", "callCount": "int (topluluk)"},
            "costs": [{"category": "telecom|stt|tts|llm|platform (FR-BIL-002 ayrı izleme)", "amount": "num"}],
            "overage": {"overageEnabled": "bool (FR-BIL-004)", "overageRate": "num", "overageMinutes": "int", "overageAmount": "num"},
            "budget": {"budgetAmount": "num (FR-BIL-006)", "spentAmount": "num (topluluk)", "usageLimitMinutes": "int (0=limit yok)",
                       "alarms": [{"id": "str", "thresholdPct": "num", "channel": "str (kanal ADI — sır DEĞİL)"}]},
            "invoiceExport": {"status": "synced|pending|failed|not_configured (FR-BIL-007)", "target": "str (finans sistemi ADI — sır DEĞİL)", "lastSync": "ISO/etiket"}
        },
        "hijyen": "FORBIDDEN_PII_KEYS dışı son-müşteri alanı/çağrı-bazlı CDR yok (BRD §17.7); FORBIDDEN_SECRET_KEYS dışı sır/finansal credential (ödeme yöntemi/kart/IBAN/finans API) yok (NFR 10.6); assertNoPii çalışma-anında doğrular. Maliyet/kullanım YALNIZ tenant-bütünü TOPLULAŞTIRMADIR. Fiyat/maliyet değerleri illüstratiftir; rate-card finans/billing motorundan (L0 P-05) beslenir."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t07_billing_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
