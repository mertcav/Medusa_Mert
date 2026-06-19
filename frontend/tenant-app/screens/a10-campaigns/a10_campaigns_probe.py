#!/usr/bin/env python3
# WBS 13.4.10 — A-10 "Outbound Kampanya Yönetimi" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countByStatus/aggregateContacts/aggregateDispositions/
#               consentCheckDisabled/suppressionDisabled/callingHoursMissing/capacityExceeded/tone'lar/assertNoPii) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (consent-kapalı/suppression-kapalı/saat-eksik/kapasite-aşımı/script-eksik yakalanır)
#   schema    — kampanya görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/campaigns.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a10-campaigns-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "campaigns", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "campaigns.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

CAMPAIGN_STATUS_ORDER = ["draft", "running", "paused", "stopped", "completed"]
DISPOSITION_ORDER = ["answered", "voicemail", "busy", "no_answer", "invalid_number", "failed"]
ACTIVE_STATUSES = ["running", "paused"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn", "phonenumber",
                      "e164", "dialednumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "contactname", "attributes", "externalref", "cdr", "cardpan",
                      "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "signingsecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential", "password",
                         "privatekey", "kmskey", "authheader", "scriptbody"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/campaigns.ts ile birebir) ────────────────────────────

def sorted_campaigns(campaigns):
    return sorted(campaigns, key=lambda c: c["campaignRef"])


def is_active(c):
    return c["status"] in ACTIVE_STATUSES


def count_by_status(campaigns):
    acc = {s: 0 for s in CAMPAIGN_STATUS_ORDER}
    for c in campaigns:
        acc[c["status"]] += 1
    return acc


def running_campaigns(campaigns):
    return [c for c in campaigns if c["status"] == "running"]


def active_campaigns(campaigns):
    return [c for c in campaigns if is_active(c)]


def ab_test_campaigns(campaigns):
    return [c for c in campaigns if c["abTest"]]


def aggregate_contacts(campaigns):
    acc = {"total": 0, "dnc": 0, "consentMissing": 0, "exhausted": 0}
    for c in campaigns:
        acc["total"] += c["contacts"]["total"]
        acc["dnc"] += c["contacts"]["dnc"]
        acc["consentMissing"] += c["contacts"]["consentMissing"]
        acc["exhausted"] += c["contacts"]["exhausted"]
    return acc


def reachable_contacts(campaigns):
    a = aggregate_contacts(campaigns)
    return max(0, a["total"] - a["dnc"] - a["consentMissing"])


def aggregate_dispositions(campaigns):
    acc = {d: 0 for d in DISPOSITION_ORDER}
    for c in campaigns:
        for d in DISPOSITION_ORDER:
            acc[d] += c["dispositions"].get(d, 0)
    return acc


def total_dispositions(campaigns):
    agg = aggregate_dispositions(campaigns)
    return sum(agg[d] for d in DISPOSITION_ORDER)


def consent_check_disabled(campaigns):
    return [c for c in campaigns if is_active(c) and not c["consentCheckEnabled"]]


def suppression_disabled(campaigns):
    return [c for c in campaigns if is_active(c) and not c["suppressionEnabled"]]


def calling_hours_missing(campaigns):
    return [c for c in campaigns if is_active(c) and not c["callingHoursConfigured"]]


def capacity_exceeded(campaigns):
    return [c for c in campaigns if c["capacityCap"] > c["capacityAvailable"]]


def missing_script_version(campaigns):
    return [c for c in campaigns if is_active(c) and c["scriptVersion"].strip() == ""]


def capacity_util_pct(campaigns):
    act = active_campaigns(campaigns)
    cap = sum(c["capacityCap"] for c in act)
    avail = sum(c["capacityAvailable"] for c in act)
    return round(cap / avail * 100) if avail > 0 else 0


def open_attention_count(campaigns):
    return (len(consent_check_disabled(campaigns))
            + len(suppression_disabled(campaigns))
            + len(calling_hours_missing(campaigns))
            + len(capacity_exceeded(campaigns))
            + len(missing_script_version(campaigns)))


def status_tone(s):
    return {"draft": "neutral", "running": "success", "paused": "warning", "stopped": "neutral", "completed": "info"}[s]


def disposition_tone(d):
    return {"answered": "success", "voicemail": "info", "busy": "warning", "no_answer": "warning",
            "invalid_number": "danger", "failed": "danger"}[d]


def list_source_tone(s):
    return {"upload": "neutral", "crm": "info"}[s]


def assert_no_pii(node, path="$"):
    """Yasak PII/müşteri-kontağı VEYA sır/credential/script-gövdesi alan adı bulursa (path) döndürür; yoksa None."""
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


def _extract_data_fields(ts):
    """campaigns.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.10", "S0 spec.wbs=13.4.10")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/campaigns/page.tsx mevcut")
    chk('data-screen="A-10"' in page, 'S1 data-screen="A-10" işaretli')
    chk("İskelet ekran — A-10" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/campaigns" in page, "S2 veri seam (lib/tenant/campaigns) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a10.*); hardcoded TR/EN cümle yok
    chk("screen.a10." in page, "S3 screen.a10.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/script-gövdesi-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/campaigns.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getOutboundCampaignView assertNoPii çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("e164", "msisdn", "attributes", "externalref")), "S4 aranacak ham numara/contact attributes/CRM kaydı yasak (BRD §17.7)")
    chk("scriptbody" in [s.lower() for s in FORBIDDEN_SECRET_KEYS], "S4 script/teklif gövdesi yasak (yalnız scriptVersion ETİKETİ; FR-OUT-009)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/script-gövdesi alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-OUT-001..012 karşılanır
    a10 = tr.get("screen", {}).get("a10", {})
    sec = a10.get("section", {})
    for s in ("summary", "campaigns", "compliance", "status", "dispositions"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk(set(["upload", "crm"]).issubset(a10.get("source", {}).keys()) and "listSource" in data, "S5 liste kaynağı yükleme/CRM (FR-OUT-001/002)")
    chk("consentCheckDisabled" in data and "consent_disabled" in a10.get("alert", {}), "S5 consent ön-kontrol (FR-OUT-003)")
    chk("callingHoursMissing" in data and "calling_hours_missing" in a10.get("alert", {}), "S5 arama saati (FR-OUT-004)")
    chk("maxAttempts" in data and "retryIntervalMinutes" in data and "attempts_fmt" in a10, "S5 maks deneme + yeniden arama aralığı (FR-OUT-005)")
    chk("suppressionDisabled" in data and "suppression_disabled" in a10.get("alert", {}), "S5 DNC/suppression (FR-OUT-006)")
    chk("capacityExceeded" in data and "capacity_exceeded" in a10.get("alert", {}), "S5 kapasite ≤ agent+trunk (FR-OUT-007)")
    chk(set(DISPOSITION_ORDER).issubset(a10.get("disposition", {}).keys()) and "aggregateDispositions" in data, "S5 disposition dağılımı (FR-OUT-008/011)")
    chk("missingScriptVersion" in data and "scriptVersion" in data, "S5 script/teklif versiyonu (FR-OUT-009)")
    chk(set(CAMPAIGN_STATUS_ORDER).issubset(a10.get("status", {}).keys()) and "action" in a10 and "stop" in a10["action"], "S5 durum + durdurma (FR-OUT-010)")
    chk("abTestCampaigns" in data and "ab_badge" in a10, "S5 A/B test (FR-OUT-012)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a10.{rk}"
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
        vt = resolve(tr, f"screen.a10.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedCampaigns", "countByStatus", "runningCampaigns", "activeCampaigns", "abTestCampaigns",
               "aggregateContacts", "reachableContacts", "aggregateDispositions", "totalDispositions",
               "consentCheckDisabled", "suppressionDisabled", "callingHoursMissing", "capacityExceeded",
               "missingScriptVersion", "capacityUtilPct", "openAttentionCount",
               "statusTone", "dispositionTone", "listSourceTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("CAMPAIGN_STATUS_ORDER" in data and "DISPOSITION_ORDER" in data and "ACTIVE_STATUSES" in data, "S7 CAMPAIGN_STATUS_ORDER + DISPOSITION_ORDER + ACTIVE_STATUSES sabitleri tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "salesforce.com", "datadog.com", "secret=", "splunk", "zendesk.com", "twilio.com", "telnyx.com"]
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

def _contacts(total, dnc, cm, ex):
    return {"total": total, "dnc": dnc, "consentMissing": cm, "exhausted": ex}


def _dispo(a, v, b, n, inv, f):
    return {"answered": a, "voicemail": v, "busy": b, "no_answer": n, "invalid_number": inv, "failed": f}


def _campaign(ref, status, source="upload", maxa=3, retry=240, script="v1", hours=True, consent=True,
              suppression=True, ab=False, cap=10, avail=20, contacts=None, dispo=None):
    return {"campaignRef": ref, "name": "Campaign " + ref, "agentRef": "AGT-" + ref, "agentName": "Agent " + ref,
            "status": status, "listSource": source, "maxAttempts": maxa, "retryIntervalMinutes": retry,
            "scriptVersion": script, "callingHoursConfigured": hours, "consentCheckEnabled": consent,
            "suppressionEnabled": suppression, "abTest": ab, "capacityCap": cap, "capacityAvailable": avail,
            "contacts": contacts or _contacts(0, 0, 0, 0), "dispositions": dispo or _dispo(0, 0, 0, 0, 0, 0)}


def _base_view():
    # 5 kampanya: CMP-02 consent-kapalı (FR-OUT-003); CMP-03 suppression+saat kapalı + kapasite aşımı + script
    # eksik (FR-OUT-006/004/007/009); CMP-05 draft kapasite aşımı (durumdan bağımsız) + draft consent/saat saymaz.
    return {"generatedAt": "2026-06-19T09:00:00.000Z", "tenantRef": "TEN-1", "tenantName": "T", "campaigns": [
        _campaign("CMP-01", "running", "crm", 3, 240, "v3.2", True, True, True, False, 20, 40,
                  _contacts(1200, 45, 0, 120), _dispo(420, 180, 90, 150, 24, 16)),
        _campaign("CMP-02", "running", "upload", 2, 1440, "v1.0", True, False, True, True, 10, 20,
                  _contacts(500, 12, 60, 30), _dispo(90, 40, 20, 35, 8, 4)),
        _campaign("CMP-03", "paused", "upload", 4, 720, "", False, True, False, False, 30, 20,
                  _contacts(800, 20, 0, 0), _dispo(0, 0, 0, 0, 0, 0)),
        _campaign("CMP-04", "completed", "crm", 3, 360, "v2.1", True, True, True, False, 0, 20,
                  _contacts(640, 30, 0, 600), _dispo(300, 120, 60, 110, 30, 20)),
        _campaign("CMP-05", "draft", "upload", 3, 480, "v0.1", False, False, False, False, 100, 20,
                  _contacts(0, 0, 0, 0), _dispo(0, 0, 0, 0, 0, 0)),
    ]}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    cs = v["campaigns"]
    chk([c["campaignRef"] for c in sorted_campaigns(cs)] == ["CMP-01", "CMP-02", "CMP-03", "CMP-04", "CMP-05"], "sortedCampaigns ASC")
    chk(count_by_status(cs) == {"draft": 1, "running": 2, "paused": 1, "stopped": 0, "completed": 1}, "countByStatus")
    chk([c["campaignRef"] for c in running_campaigns(cs)] == ["CMP-01", "CMP-02"], "runningCampaigns=[01,02]")
    chk([c["campaignRef"] for c in active_campaigns(cs)] == ["CMP-01", "CMP-02", "CMP-03"], "activeCampaigns=[01,02,03]")
    chk([c["campaignRef"] for c in ab_test_campaigns(cs)] == ["CMP-02"], "abTestCampaigns=[02] (FR-OUT-012)")
    chk(aggregate_contacts(cs) == {"total": 3140, "dnc": 107, "consentMissing": 60, "exhausted": 750}, "aggregateContacts")
    chk(reachable_contacts(cs) == 2973, "reachableContacts=2973 (total-dnc-consentMissing)")
    chk(aggregate_dispositions(cs) == {"answered": 810, "voicemail": 340, "busy": 170, "no_answer": 295, "invalid_number": 62, "failed": 40}, "aggregateDispositions (FR-OUT-008/011)")
    chk(total_dispositions(cs) == 1717, "totalDispositions=1717")
    chk([c["campaignRef"] for c in consent_check_disabled(cs)] == ["CMP-02"], "consentCheckDisabled=[02] (aktif & consent kapalı — FR-OUT-003)")
    chk([c["campaignRef"] for c in suppression_disabled(cs)] == ["CMP-03"], "suppressionDisabled=[03] (aktif & suppression kapalı — FR-OUT-006)")
    chk([c["campaignRef"] for c in calling_hours_missing(cs)] == ["CMP-03"], "callingHoursMissing=[03] (aktif & saat yok — FR-OUT-004)")
    chk([c["campaignRef"] for c in capacity_exceeded(cs)] == ["CMP-03", "CMP-05"], "capacityExceeded=[03,05] (cap>avail — FR-OUT-007)")
    chk([c["campaignRef"] for c in missing_script_version(cs)] == ["CMP-03"], "missingScriptVersion=[03] (aktif & script boş — FR-OUT-009)")
    chk(capacity_util_pct(cs) == 75, "capacityUtilPct=75 (aktif 60/80)")
    # attention = consent(1)+suppression(1)+hours(1)+capacity(2)+script(1) = 6
    chk(open_attention_count(cs) == 6, "openAttentionCount=6")

    # draft CMP-05 consent/suppression/saat KAPALI ama AKTİF değil → o kapılara saymaz (yalnız kapasite saydı)
    chk(all(c["campaignRef"] != "CMP-05" for c in consent_check_disabled(cs)), "draft consent-kapalı consentCheckDisabled'a saymaz")
    chk(all(c["campaignRef"] != "CMP-05" for c in calling_hours_missing(cs)), "draft saat-yok callingHoursMissing'e saymaz")
    chk(any(c["campaignRef"] == "CMP-05" for c in capacity_exceeded(cs)), "draft kapasite aşımı capacityExceeded'a sayar (durumdan bağımsız)")

    # tone eşlemeleri
    chk(status_tone("running") == "success" and status_tone("paused") == "warning" and status_tone("completed") == "info", "statusTone")
    chk(disposition_tone("answered") == "success" and disposition_tone("invalid_number") == "danger" and disposition_tone("busy") == "warning", "dispositionTone")
    chk(list_source_tone("crm") == "info" and list_source_tone("upload") == "neutral", "listSourceTone")

    # assertNoPii — KAMPANYA META İZİNLİ, ham müşteri kontağı + sır + script gövdesi YASAK
    chk(assert_no_pii({"a": _base_view()}) is None, "assertNoPii kampanya META İZİNLİ")
    chk(assert_no_pii({"x": {"e164": "+90..."}}) == "$.x.e164", "assertNoPii aranacak ham numara yakalar (ÇEKİRDEK)")
    chk(assert_no_pii({"x": {"customerName": "Ali"}}) == "$.x.customerName", "assertNoPii müşteri adı yakalar")
    chk(assert_no_pii({"x": {"attributes": {}}}) == "$.x.attributes", "assertNoPii contact attributes yakalar")
    chk(assert_no_pii({"x": {"externalRef": "CRM-1"}}) == "$.x.externalRef", "assertNoPii CRM kaydı yakalar (FR-OUT-002)")
    chk(assert_no_pii({"x": {"scriptBody": "..."}}) == "$.x.scriptBody", "assertNoPii script gövdesi yakalar (FR-OUT-009)")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii sır yakalar (NFR 10.6)")

    # samples doğrulaması
    for name in ("campaigns-clean.json", "campaigns-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        cc = snp["campaigns"]
        exp = snp.get("$expect", {})
        chk(len(cc) == exp.get("campaigns"), f"{name} campaigns={exp.get('campaigns')}")
        chk(len(running_campaigns(cc)) == exp.get("running"), f"{name} running={exp.get('running')}")
        chk(len(active_campaigns(cc)) == exp.get("active"), f"{name} active={exp.get('active')}")
        chk(len(ab_test_campaigns(cc)) == exp.get("ab_tests"), f"{name} ab_tests={exp.get('ab_tests')}")
        ac = aggregate_contacts(cc)
        chk(ac["total"] == exp.get("contacts_total"), f"{name} contacts_total={exp.get('contacts_total')}")
        chk(ac["dnc"] == exp.get("dnc"), f"{name} dnc={exp.get('dnc')}")
        chk(ac["consentMissing"] == exp.get("consent_missing"), f"{name} consent_missing={exp.get('consent_missing')}")
        chk(ac["exhausted"] == exp.get("exhausted"), f"{name} exhausted={exp.get('exhausted')}")
        chk(reachable_contacts(cc) == exp.get("reachable"), f"{name} reachable={exp.get('reachable')}")
        chk(total_dispositions(cc) == exp.get("dispositions_total"), f"{name} dispositions_total={exp.get('dispositions_total')}")
        chk(len(consent_check_disabled(cc)) == exp.get("consent_disabled"), f"{name} consent_disabled={exp.get('consent_disabled')}")
        chk(len(suppression_disabled(cc)) == exp.get("suppression_disabled"), f"{name} suppression_disabled={exp.get('suppression_disabled')}")
        chk(len(calling_hours_missing(cc)) == exp.get("hours_missing"), f"{name} hours_missing={exp.get('hours_missing')}")
        chk(len(capacity_exceeded(cc)) == exp.get("capacity_exceeded"), f"{name} capacity_exceeded={exp.get('capacity_exceeded')}")
        chk(len(missing_script_version(cc)) == exp.get("missing_script"), f"{name} missing_script={exp.get('missing_script')}")
        chk(open_attention_count(cc) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır/script-gövdesi-free (HİJYEN+GÜVENLİK)")

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

    # pozitif (sağlıklı: aktif kampanyalar consent+suppression+saat açık, kapasite ≤ available, script tanımlı)
    ok = {"campaigns": [
        _campaign("C1", "running", "crm", 3, 240, "v1", True, True, True, False, 10, 20,
                  _contacts(100, 5, 0, 10), _dispo(40, 10, 5, 8, 2, 1)),
        _campaign("C2", "paused", "upload", 2, 600, "v2", True, True, True, True, 5, 10,
                  _contacts(50, 2, 0, 0), _dispo(0, 0, 0, 0, 0, 0)),
    ]}
    cs = ok["campaigns"]
    expect(open_attention_count(cs) == 0, "pos açık dikkat=0")
    expect(len(consent_check_disabled(cs)) == 0, "pos consent kapalı yok")
    expect(len(suppression_disabled(cs)) == 0, "pos suppression kapalı yok")
    expect(len(calling_hours_missing(cs)) == 0, "pos arama saati eksik yok")
    expect(len(capacity_exceeded(cs)) == 0, "pos kapasite aşımı yok")
    expect(len(missing_script_version(cs)) == 0, "pos script eksik yok")

    # negatif (çok-sorunlu: consent-kapalı + suppression-kapalı + saat-eksik + kapasite-aşımı + script-eksik)
    bad = {"campaigns": [
        _campaign("C1", "running", "upload", 3, 240, "v1", True, False, True, False, 5, 10,
                  _contacts(200, 10, 30, 5), _dispo(50, 20, 10, 15, 3, 2)),   # consent kapalı (aktif)
        _campaign("C2", "paused", "upload", 2, 600, "", False, True, False, False, 50, 20,
                  _contacts(100, 5, 0, 0), _dispo(0, 0, 0, 0, 0, 0)),         # suppression+saat kapalı + kapasite aşımı + script eksik
        _campaign("C3", "draft", "upload", 3, 480, "v0", False, False, False, False, 80, 10,
                  _contacts(0, 0, 0, 0), _dispo(0, 0, 0, 0, 0, 0)),           # draft kapasite aşımı (config açığı)
    ]}
    bc = bad["campaigns"]
    expect([c["campaignRef"] for c in consent_check_disabled(bc)] == ["C1"], "neg consent kapalı=[C1] (FR-OUT-003)")
    expect([c["campaignRef"] for c in suppression_disabled(bc)] == ["C2"], "neg suppression kapalı=[C2] (FR-OUT-006)")
    expect([c["campaignRef"] for c in calling_hours_missing(bc)] == ["C2"], "neg arama saati eksik=[C2] (FR-OUT-004)")
    expect([c["campaignRef"] for c in capacity_exceeded(bc)] == ["C2", "C3"], "neg kapasite aşımı=[C2,C3] (FR-OUT-007)")
    expect([c["campaignRef"] for c in missing_script_version(bc)] == ["C2"], "neg script eksik=[C2] (FR-OUT-009)")
    # attention = consent(1)+suppression(1)+hours(1)+capacity(2)+script(1) = 6
    expect(open_attention_count(bc) == 6, "neg açık dikkat=6")
    # draft C3 consent/saat kapalı ama aktif değil → o kapılara saymaz
    expect(len(consent_check_disabled(bc)) == 1, "neg draft consent-kapalı consentCheckDisabled'a saymaz")
    expect(len(calling_hours_missing(bc)) == 1, "neg draft saat-yok callingHoursMissing'e saymaz")

    # sınır: boş envanter
    empty = {"campaigns": []}
    ec = empty["campaigns"]
    expect(aggregate_contacts(ec) == {"total": 0, "dnc": 0, "consentMissing": 0, "exhausted": 0}, "sınır boş envanter kontak 0")
    expect(open_attention_count(ec) == 0, "sınır boş envanter dikkat=0")
    expect(count_by_status(ec) == {s: 0 for s in CAMPAIGN_STATUS_ORDER}, "sınır boş durum dağılımı 0")
    expect(total_dispositions(ec) == 0, "sınır boş disposition 0")
    expect(capacity_util_pct(ec) == 0, "sınır boş kapasite kullanım 0 (available=0 guard)")

    # sınır: reachable negatif olmaz (clamp ≥0)
    over = {"campaigns": [_campaign("C1", "running", "upload", 3, 240, "v1", True, True, True, False, 5, 10,
                                    _contacts(10, 8, 5, 0), _dispo(0, 0, 0, 0, 0, 0))]}
    expect(reachable_contacts(over["campaigns"]) == 0, "sınır reachable negatif olmaz (max 0)")

    # sınır: stopped/completed kampanya consent kapalı olsa da aktif değil → saymaz
    done = {"campaigns": [_campaign("C1", "completed", "upload", 3, 240, "v1", False, False, False, False, 99, 1,
                                    _contacts(10, 0, 0, 10), _dispo(0, 0, 0, 0, 0, 0))]}
    dc = done["campaigns"]
    expect(len(consent_check_disabled(dc)) == 0, "sınır completed consent-kapalı saymaz")
    expect(len(capacity_exceeded(dc)) == 1, "sınır completed kapasite aşımı sayar (durumdan bağımsız)")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"phoneNumber": "1"}}) is not None, "neg phoneNumber yakalanır")
    expect(assert_no_pii({"s": [{"e164": "x"}]}) is not None, "neg e164 yakalanır (ÇEKİRDEK)")
    expect(assert_no_pii({"x": {"scriptBody": "..."}}) is not None, "neg script gövdesi yakalanır (FR-OUT-009)")
    expect(assert_no_pii({"x": {"bearerToken": "..."}}) is not None, "neg sır yakalanır (NFR 10.6)")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")

    # tone sınır
    expect(status_tone("running") == "success", "running → success")
    expect(disposition_tone("invalid_number") == "danger", "invalid_number → danger")
    expect(list_source_tone("crm") == "info", "crm → info")

    # placeholder ayrıştırma
    expect(placeholders("{count} sorun") == {"count"}, "placeholder parse")
    expect(placeholders("Maks {max} · {retry} dk") == {"max", "retry"}, "placeholder çoklu parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 80, "spec ≥80 referans anahtar")
    expect(spec["campaign_statuses"] == CAMPAIGN_STATUS_ORDER, "spec campaign_statuses = CAMPAIGN_STATUS_ORDER")
    expect(spec["dispositions"] == DISPOSITION_ORDER, "spec dispositions = DISPOSITION_ORDER")
    expect(spec["active_statuses"] == ACTIVE_STATUSES, "spec active_statuses = ACTIVE_STATUSES")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "OutboundCampaignView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "campaigns": [{
                "campaignRef": "str (Campaign Manager gösterim kimliği)",
                "name": "str (kurumsal kampanya adı — tenant config; PII değil)",
                "agentRef": "str (bağlı agent gösterim kimliği)",
                "agentName": "str (agent adı — tenant config; PII değil)",
                "status": "draft|running|paused|stopped|completed (DB §5.4; FR-OUT-010)",
                "listSource": "upload|crm (FR-OUT-001/002)",
                "maxAttempts": "int (FR-OUT-005 — maksimum deneme)",
                "retryIntervalMinutes": "int (FR-OUT-005 — yeniden arama aralığı)",
                "scriptVersion": "str (FR-OUT-009 — script/teklif versiyonu ETİKETİ; gövde gömülmez; boş=eksik)",
                "callingHoursConfigured": "bool (FR-OUT-004 — arama saati yapılandırıldı mı; JSONB gövdesi gömülmez)",
                "consentCheckEnabled": "bool (FR-OUT-003 — consent ön-kontrol açık mı)",
                "suppressionEnabled": "bool (FR-OUT-006 — DNC/suppression gerçek-zamanlı açık mı)",
                "abTest": "bool (FR-OUT-012 — A/B test; Should)",
                "capacityCap": "int (FR-OUT-007 — kampanya kapasite üst sınırı)",
                "capacityAvailable": "int (FR-OUT-007 — mevcut agent+trunk kapasitesi)",
                "contacts": {"total": "int", "dnc": "int (FR-OUT-006)", "consentMissing": "int (FR-OUT-003)", "exhausted": "int (FR-OUT-005)"},
                "dispositions": "Record<answered|voicemail|busy|no_answer|invalid_number|failed, int> (FR-OUT-008/011 — AGREGAT)"
            }]
        },
        "campaign_statuses": CAMPAIGN_STATUS_ORDER,
        "list_sources": ["upload", "crm"],
        "dispositions": DISPOSITION_ORDER,
        "active_statuses": ACTIVE_STATUSES,
        "invariants": "AKTİF (running|paused) kampanyada consentCheckDisabled (FR-OUT-003) + suppressionDisabled (FR-OUT-006) + callingHoursMissing (FR-OUT-004) + missingScriptVersion (FR-OUT-009) = sıfır olmalı; capacityExceeded (capacityCap>capacityAvailable — FR-OUT-007) durumdan bağımsız sıfır olmalı (sağlıklı).",
        "hijyen": "A-10 yalnız KAMPANYA META gösterir (durum/deneme/script-versiyonu ETİKETİ/arama-saati BAYRAĞI/consent BAYRAĞI/suppression BAYRAĞI/kapasite/A-B BAYRAĞI + AGREGAT kontak SAYILARI + per-disposition SAYILAR + kampanya/agent adı — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (aranacak ham numara/e164/müşteri adı/contact attributes/CRM external_ref/transkript/kayıt/CDR) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential + script/teklif GÖVDESİ (apiKey/token/secret/scriptBody) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Liste yükleme/CRM çekme/dialer derin aksiyon → API dilimi + Consent Engine backend (SAD §19.1). KONFİGÜRASYON ekranı; gerçek zamanlı DEĞİL."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a10_campaigns_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
