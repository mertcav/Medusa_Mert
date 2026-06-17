#!/usr/bin/env python3
# WBS 13.2.7 — P-07 "Platform Audit & Güvenlik" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (auditOutcomeTone/breakGlassStatusTone/severityTone/
#               securityStatusTone/countByOutcome/wormGaps/makerCheckerViolations/standingAccessViolations/
#               tenantApprovalGaps/notificationGaps/breakGlassComplianceGaps/openSecurityEvents/
#               criticalOpenEvents/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/audit.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p07-audit-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "audit", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "audit.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"
MAX_BREAK_GLASS_MINUTES = 240


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/audit.ts ile birebir) ───────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "iban",
                      "pii", "email", "ssn"]

AUDIT_OUTCOME_TONE = {"success": "success", "denied": "warning", "error": "danger"}
BREAK_GLASS_STATUS_TONE = {"active": "warning", "pending_approval": "info", "expired": "neutral",
                           "revoked": "neutral", "denied": "neutral"}
SEVERITY_TONE = {"critical": "danger", "high": "danger", "medium": "warning", "low": "neutral"}
SECURITY_STATUS_TONE = {"open": "danger", "investigating": "warning", "resolved": "success"}

_BG_GRANTED = ("active", "expired", "revoked")  # erişim sağlamış (onay sürecini geçmiş) oturumlar


def audit_outcome_tone(o):
    return AUDIT_OUTCOME_TONE[o]


def break_glass_status_tone(s):
    return BREAK_GLASS_STATUS_TONE[s]


def severity_tone(s):
    return SEVERITY_TONE[s]


def security_status_tone(s):
    return SECURITY_STATUS_TONE[s]


def count_by_outcome(entries):
    acc = {"success": 0, "denied": 0, "error": 0}
    for e in entries:
        acc[e["outcome"]] += 1
    return acc


def worm_gaps(snap):
    return [e["id"] for e in snap["auditEntries"] if not e["wormAnchored"]]


def count_active_break_glass(sessions):
    return len([s for s in sessions if s["status"] == "active"])


def pending_approvals(sessions):
    return [s["id"] for s in sessions if s["status"] == "pending_approval"]


def maker_checker_violations(snap):
    return [s["id"] for s in snap["breakGlassSessions"]
            if s["tier"] == "B" and s["status"] in _BG_GRANTED
            and (not s["approvedBy"] or s["approvedBy"] == s["requestedBy"])]


def standing_access_violations(snap):
    return [s["id"] for s in snap["breakGlassSessions"]
            if s["tier"] == "B" and s["durationMin"] > MAX_BREAK_GLASS_MINUTES]


def tenant_approval_gaps(snap):
    return [s["id"] for s in snap["breakGlassSessions"]
            if s["status"] in _BG_GRANTED and s["tenantApprovalRequired"] and not s["tenantApproved"]]


def notification_gaps(snap):
    return [s["id"] for s in snap["breakGlassSessions"]
            if s["tier"] == "B" and s["status"] in _BG_GRANTED and not s["notified"]]


def break_glass_compliance_gaps(snap):
    s = set(maker_checker_violations(snap)) | set(standing_access_violations(snap)) \
        | set(tenant_approval_gaps(snap)) | set(notification_gaps(snap))
    return sorted(s)


def open_security_events(events):
    return [e["id"] for e in events if e["status"] != "resolved"]


def critical_open_events(events):
    return [e["id"] for e in events if e["severity"] == "critical" and e["status"] != "resolved"]


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
    """audit.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.7", "S0 spec.wbs=13.2.7")
    chk(os.path.isfile(PAGE_PATH), "S1 audit/page.tsx mevcut")
    chk('data-screen="P-07"' in page, 'S1 data-screen="P-07" işaretli')
    chk("İskelet ekran — P-07" not in page and "İskelet" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/audit" in page, "S2 veri seam (lib/platform/audit) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p07.*); hardcoded TR/EN cümle yok
    chk("screen.p07." in page, "S3 screen.p07.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/audit.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getAudit assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")
    chk("tenantRef" in data, "S4 tenantRef (tenant KİMLİĞİ — izinli) alanı mevcut")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (audit log + break-glass erişim + güvenlik olayları)
    p07 = tr.get("screen", {}).get("p07", {})
    sec = p07.get("section", {})
    chk("audit" in sec and "audit_category" in p07 and "audit_outcome" in p07, "S5 audit log → section.audit + audit_category.* + audit_outcome.* (FR-IAM-006/REC-009)")
    chk("break_glass" in sec and "tier" in p07 and "break_glass_status" in p07, "S5 break-glass erişim → section.break_glass + tier.* + break_glass_status.* (FR-IAM-009/010)")
    chk("security" in sec and "severity" in p07 and "security_status" in p07, "S5 güvenlik olayları → section.security + severity.* + security_status.*")
    chk("worm_alert" in p07 and "worm_ok" in p07, "S5 WORM integrity uyarısı → worm_alert (FR-IAM-006)")
    chk("compliance_alert" in p07 and "compliance_ok" in p07, "S5 break-glass uyum uyarısı → compliance_alert (FR-IAM-005/009/010)")
    chk("critical_alert" in p07 and "critical_ok" in p07, "S5 kritik güvenlik uyarısı → critical_alert")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p07.{rk}"
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
        vt = resolve(tr, f"screen.p07.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("auditOutcomeTone", "breakGlassStatusTone", "severityTone", "securityStatusTone",
               "countByOutcome", "wormGaps", "countActiveBreakGlass", "pendingApprovals",
               "makerCheckerViolations", "standingAccessViolations", "tenantApprovalGaps",
               "notificationGaps", "breakGlassComplianceGaps", "openSecurityEvents", "criticalOpenEvents"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral (somut sağlayıcı/SIEM markası yok) + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "deepgram", "elevenlabs", "cartesia",
                         "telnyx", "splunk", "datadog", "gpt-", "claude-", "gemini", "llama",
                         "whisper", "api_key", "secret="]
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

    # auditOutcomeTone
    chk(audit_outcome_tone("success") == "success", "audit outcome success→success")
    chk(audit_outcome_tone("denied") == "warning", "audit outcome denied→warning")
    chk(audit_outcome_tone("error") == "danger", "audit outcome error→danger")
    # breakGlassStatusTone
    chk(break_glass_status_tone("active") == "warning", "break-glass active→warning (hassas, açık erişim)")
    chk(break_glass_status_tone("pending_approval") == "info", "break-glass pending→info")
    chk(break_glass_status_tone("expired") == "neutral", "break-glass expired→neutral")
    # severityTone
    chk(severity_tone("critical") == "danger", "severity critical→danger")
    chk(severity_tone("high") == "danger", "severity high→danger")
    chk(severity_tone("medium") == "warning", "severity medium→warning")
    chk(severity_tone("low") == "neutral", "severity low→neutral")
    # securityStatusTone
    chk(security_status_tone("open") == "danger", "security open→danger")
    chk(security_status_tone("investigating") == "warning", "security investigating→warning")
    chk(security_status_tone("resolved") == "success", "security resolved→success")
    # assertNoPii
    chk(assert_no_pii({"auditEntries": [{"tenantRef": "tenant-a", "action": "x"}]}) is None, "assertNoPii temiz snapshot OK (tenantRef izinli)")
    chk(assert_no_pii({"auditEntries": [{"transcript": "x"}]}) == "$.auditEntries[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"recording": "u"}) == "$.recording", "assertNoPii recording yakalar")

    # samples doğrulaması
    for name in ("audit-mixed.json", "audit-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(worm_gaps(snap) == exp["worm_gaps"], f"{name} worm_gaps={exp['worm_gaps']}")
        chk(maker_checker_violations(snap) == exp["maker_checker_violations"], f"{name} maker_checker_violations={exp['maker_checker_violations']}")
        chk(standing_access_violations(snap) == exp["standing_access_violations"], f"{name} standing_access_violations={exp['standing_access_violations']}")
        chk(tenant_approval_gaps(snap) == exp["tenant_approval_gaps"], f"{name} tenant_approval_gaps={exp['tenant_approval_gaps']}")
        chk(notification_gaps(snap) == exp["notification_gaps"], f"{name} notification_gaps={exp['notification_gaps']}")
        chk(break_glass_compliance_gaps(snap) == exp["break_glass_compliance_gaps"], f"{name} break_glass_compliance_gaps={exp['break_glass_compliance_gaps']}")
        chk(count_active_break_glass(snap["breakGlassSessions"]) == exp["active_break_glass"], f"{name} active_break_glass={exp['active_break_glass']}")
        chk(pending_approvals(snap["breakGlassSessions"]) == exp["pending_approvals"], f"{name} pending_approvals={exp['pending_approvals']}")
        chk(open_security_events(snap["securityEvents"]) == exp["open_security"], f"{name} open_security={exp['open_security']}")
        chk(critical_open_events(snap["securityEvents"]) == exp["critical_open"], f"{name} critical_open={exp['critical_open']}")
        chk(count_by_outcome(snap["auditEntries"]) == exp["count_by_outcome"], f"{name} count_by_outcome={exp['count_by_outcome']}")
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

    snap = {
        "auditEntries": [
            {"id": "a-1", "outcome": "success", "wormAnchored": True},
            {"id": "a-2", "outcome": "denied", "wormAnchored": True},
            {"id": "a-3", "outcome": "error", "wormAnchored": False},  # WORM boşluğu
        ],
        "breakGlassSessions": [
            # uyumlu Tier B (maker≠checker, onaylı, bildirimli, 60dk)
            {"id": "bg-1", "tier": "B", "status": "active", "requestedBy": "r1", "approvedBy": "c1",
             "durationMin": 60, "tenantApprovalRequired": True, "tenantApproved": True, "notified": True},
            # maker==checker → maker-checker ihlali + bildirim yok → notification gap
            {"id": "bg-2", "tier": "B", "status": "active", "requestedBy": "r2", "approvedBy": "r2",
             "durationMin": 60, "tenantApprovalRequired": False, "tenantApproved": False, "notified": False},
            # 5 saat > 4 saat → standing-access ihlali + tenant onayı gerekli ama alınmamış
            {"id": "bg-3", "tier": "B", "status": "expired", "requestedBy": "r3", "approvedBy": "c3",
             "durationMin": 300, "tenantApprovalRequired": True, "tenantApproved": False, "notified": True},
            # pending → onay süreci doğru işliyor; ihlal sayılmaz
            {"id": "bg-4", "tier": "B", "status": "pending_approval", "requestedBy": "r4", "approvedBy": None,
             "durationMin": 60, "tenantApprovalRequired": True, "tenantApproved": False, "notified": False},
            # Tier A: maker-checker/bildirim gerekmez
            {"id": "bg-5", "tier": "A", "status": "active", "requestedBy": "r5", "approvedBy": "r5",
             "durationMin": 60, "tenantApprovalRequired": False, "tenantApproved": False, "notified": False},
        ],
        "securityEvents": [
            {"id": "se-1", "severity": "critical", "status": "open"},
            {"id": "se-2", "severity": "high", "status": "investigating"},
            {"id": "se-3", "severity": "low", "status": "resolved"},
        ],
    }
    # pozitif — türetmeler
    expect(worm_gaps(snap) == ["a-3"], "pos WORM boşluğu = a-3")
    expect(count_by_outcome(snap["auditEntries"]) == {"success": 1, "denied": 1, "error": 1}, "pos audit sonuç sayımı")
    expect(count_active_break_glass(snap["breakGlassSessions"]) == 3, "pos aktif break-glass=3")
    expect(pending_approvals(snap["breakGlassSessions"]) == ["bg-4"], "pos onay bekleyen = bg-4")
    expect(maker_checker_violations(snap) == ["bg-2"], "pos maker-checker ihlali = bg-2 (Tier B, maker==checker)")
    expect(standing_access_violations(snap) == ["bg-3"], "pos standing-access ihlali = bg-3 (>4 saat)")
    expect(tenant_approval_gaps(snap) == ["bg-3"], "pos tenant onayı boşluğu = bg-3")
    expect(notification_gaps(snap) == ["bg-2"], "pos bildirim boşluğu = bg-2 (Tier B, bildirilmemiş)")
    expect(break_glass_compliance_gaps(snap) == ["bg-2", "bg-3"], "pos break-glass uyum boşluğu = {bg-2,bg-3} tekil")
    expect(open_security_events(snap["securityEvents"]) == ["se-1", "se-2"], "pos açık güvenlik olayı = se-1,se-2")
    expect(critical_open_events(snap["securityEvents"]) == ["se-1"], "pos kritik+açık = se-1")
    # negatif (degrade beklendiği gibi yakalanır)
    expect("bg-4" not in break_glass_compliance_gaps(snap), "neg pending oturum uyum ihlali sayılmaz")
    expect("bg-5" not in maker_checker_violations(snap), "neg Tier A maker-checker gerektirmez")
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"callerid": "x"}) is not None, "neg callerid yakalanır")
    # tam-sağlıklı snapshot → boşluk/ihlal yok
    healthy = {
        "auditEntries": [{"id": "a", "outcome": "success", "wormAnchored": True}],
        "breakGlassSessions": [{"id": "bg", "tier": "B", "status": "active", "requestedBy": "r", "approvedBy": "c",
                                "durationMin": 60, "tenantApprovalRequired": True, "tenantApproved": True, "notified": True}],
        "securityEvents": [{"id": "se", "severity": "low", "status": "resolved"}],
    }
    expect(worm_gaps(healthy) == [], "pos sağlıklı → WORM boşluğu yok")
    expect(break_glass_compliance_gaps(healthy) == [], "pos sağlıklı → break-glass uyum boşluğu yok")
    expect(critical_open_events(healthy["securityEvents"]) == [], "pos sağlıklı → kritik açık olay yok")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{remaining} / {total} min") == {"remaining", "total"}, "min_value placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 70, "spec ≥70 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "AuditSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "auditEntries": [{
                "id": "str", "occurredAt": "ISO-8601",
                "actorRole": "platform_owner|platform_sre|platform_billing",
                "action": "str (permission-key biçimi eylem — kod, çeviri değil)",
                "category": "auth|config_change|content_access|provisioning|security",
                "outcome": "success|denied|error",
                "tenantRef": "str (tenant KİMLİĞİ — izinli; iş içeriği DEĞİL)",
                "wormAnchored": "bool (FR-IAM-006 WORM integrity)", "mappedFr": "str (FR kodu)"
            }],
            "breakGlassSessions": [{
                "id": "str", "tier": "A|B", "status": "active|pending_approval|expired|revoked|denied",
                "tenantRef": "str", "reasonCode": "str (zorunlu gerekçe kodu)",
                "requestedBy": "str", "approvedBy": "str|null (maker ≠ checker)",
                "durationMin": "num (max 240 = 4 saat)", "remainingMin": "num",
                "tenantApprovalRequired": "bool (FR-IAM-010)", "tenantApproved": "bool",
                "notified": "bool (FR-IAM-009 tenant bildirimi)", "mappedFr": "str"
            }],
            "securityEvents": [{
                "id": "str", "type": "str (vendor-nötr olay tipi)",
                "severity": "critical|high|medium|low", "status": "open|investigating|resolved",
                "occurredAt": "ISO-8601", "mappedFr": "str"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. tenantRef (tenant kimliği) izinli.",
        "worm_gap": "auditEntry.wormAnchored == false (FR-IAM-006)",
        "maker_checker_violation": "Tier B & status in {active,expired,revoked} & (!approvedBy || approvedBy == requestedBy) (FR-IAM-005/009)",
        "standing_access_violation": "Tier B & durationMin > 240 (FR-IAM-009 max 4 saat, standing access yok)",
        "tenant_approval_gap": "status in {active,expired,revoked} & tenantApprovalRequired & !tenantApproved (FR-IAM-010)",
        "notification_gap": "Tier B & status in {active,expired,revoked} & !notified (FR-IAM-009)"
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p07_audit_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
