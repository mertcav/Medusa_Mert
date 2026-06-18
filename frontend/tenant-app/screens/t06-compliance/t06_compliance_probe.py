#!/usr/bin/env python3
# WBS 13.3.6 — T-06 "Compliance & Retention" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (disclosureGaps/recordingGaps/residencyGaps/outboundGaps/
#               loosenOverrides/invalidRetention/dpiaPending/openWarningCount/tone'lar/assertNoPii) +
#               samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/compliance.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t06-compliance-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "compliance", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "compliance.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/compliance.ts ile birebir) ──────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "customer", "cardpan",
                      "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "signingsecret", "clientsecret",
                         "token", "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey"]


def disclosure_gaps(t):
    out = []
    if t["aiDisclosureRequired"] and not t["aiDisclosureConfigured"]:
        out.append("ai_disclosure")
    if t["recordingNoticeRequired"] and not t["recordingNoticeConfigured"]:
        out.append("recording_notice")
    return out


def recording_gaps(r):
    out = []
    if r["channelMode"] == "off":
        return out
    if not r["piiRedaction"]:
        out.append("pii_redaction")
    if not r["cardOtpMasking"]:
        out.append("card_otp")
    return out


def residency_gaps(res):
    out = []
    if res["inRegionStorageRequired"] and not res["providerRegionPinning"]:
        out.append("provider_pinning")
    if not res["inRegionStorageRequired"] and res["crossBorderMechanism"] == "none":
        out.append("cross_border")
    return out


def outbound_gaps(o):
    out = []
    needs_consent = o["consentModel"] in ("opt_in", "soft_opt_in")
    if not needs_consent:
        return out
    if o["consentRegistry"].strip() == "" or o["consentRegistry"].lower() == "none":
        out.append("consent_registry")
    if len(o["dncLists"]) == 0:
        out.append("dnc")
    return out


def loosen_overrides(overrides):
    return [o["id"] for o in overrides if o["direction"] == "loosen"]


def invalid_retention(r):
    out = []
    if r["recordingDays"] <= 0:
        out.append("recording")
    if r["transcriptDays"] <= 0:
        out.append("transcript")
    if r["auditDays"] <= 0:
        out.append("audit")
    return out


def dpia_pending(d):
    return d["status"] in ("required", "in_progress")


def open_warning_count(snap):
    return (len(disclosure_gaps(snap["transparency"]))
            + len(recording_gaps(snap["recordingPolicy"]))
            + len(residency_gaps(snap["residency"]))
            + len(outbound_gaps(snap["outbound"]))
            + len(loosen_overrides(snap["overrides"]))
            + len(invalid_retention(snap["retention"]))
            + (1 if dpia_pending(snap["dpia"]) else 0))


def dpia_status_tone(s):
    return {"not_required": "neutral", "required": "danger", "in_progress": "warning", "completed": "success"}[s]


def override_direction_tone(d):
    return {"tighten": "success", "equal": "neutral", "loosen": "danger"}[d]


def cross_border_tone(m):
    return {"scc": "success", "adequacy": "success", "explicit_consent": "warning", "none": "neutral"}[m]


def consent_model_tone(m):
    return {"opt_in": "success", "soft_opt_in": "info", "opt_out": "warning"}[m]


def channel_mode_tone(m):
    return {"off": "neutral", "single": "info", "dual": "info"}[m]


def required_flag_tone(required, satisfied):
    if not required:
        return "neutral"
    return "success" if satisfied else "danger"


def guard_flag_tone(on):
    return "success" if on else "danger"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential alan adı bulursa (path) döndürür; yoksa None."""
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
    chk(spec.get("wbs") == "13.3.6", "S0 spec.wbs=13.3.6")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/compliance/page.tsx mevcut")
    chk('data-screen="T-06"' in page, 'S1 data-screen="T-06" işaretli')
    chk("İskelet ekran — T-06" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/compliance" in page, "S2 veri seam (lib/tenant/compliance) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t06.*); hardcoded TR/EN cümle yok
    chk("screen.t06." in page, "S3 screen.t06.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/compliance.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getCompliance assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 altı içerik öğesi + FR-REC + FR-OUT + cp.* + DPIA + override karşılanır
    t06 = tr.get("screen", {}).get("t06", {})
    sec = t06.get("section", {})
    for s in ("profile", "recording", "residency", "retention", "outbound", "overrides"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.4 içerik öğesi)")
    chk("transparency" in sec and "dsr" in sec, "S5 şeffaflık + DSR bölümleri")
    chk(set(["off", "single", "dual"]).issubset(t06.get("channel", {}).keys()), "S5 kayıt kanal modları (FR-REC-002/003)")
    chk("pii_redaction" in t06.get("field", {}) and "card_otp" in t06.get("field", {}), "S5 PII redaction + kart/OTP (FR-REC-004/005)")
    chk(set(["opt_in", "soft_opt_in", "opt_out"]).issubset(t06.get("consent", {}).keys()), "S5 consent modelleri (FR-OUT-003)")
    chk("dnc_lists" in t06.get("field", {}), "S5 DNC/İYS kaynakları (FR-OUT-006)")
    chk(set(["scc", "adequacy", "explicit_consent", "none"]).issubset(t06.get("cross_border", {}).keys()), "S5 residency sınır-ötesi mekanizma (NFR 10.7)")
    chk(set(["recording", "transcript", "audit"]).issubset(t06.get("data_class", {}).keys()), "S5 saklama veri sınıfları (FR-REC-006/010)")
    chk(set(["not_required", "required", "in_progress", "completed"]).issubset(t06.get("dpia_status", {}).keys()), "S5 DPIA durumları (DPIA §3)")
    chk(set(["tighten", "equal", "loosen"]).issubset(t06.get("direction", {}).keys()), "S5 override yön (most-restrictive-wins, DPIA §8)")
    chk("loosenOverrides" in data and "residencyGaps" in data, "S5 override/residency türetmeleri")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t06.{rk}"
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
        vt = resolve(tr, f"screen.t06.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("disclosureGaps", "recordingGaps", "residencyGaps", "outboundGaps", "loosenOverrides",
               "invalidRetention", "dpiaPending", "openWarningCount", "dpiaStatusTone",
               "overrideDirectionTone", "crossBorderTone", "consentModelTone", "channelModeTone",
               "requiredFlagTone", "guardFlagTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + counsel-tabi + sır yok
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "salesforce", "hubspot", "twilio.com"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")
    chk("counsel" in (page + data).lower() or "counsel" in json.dumps(t06, ensure_ascii=False).lower(), "S8 counsel doğrulama notu (mühendislik varsayılanı, DPIA §12)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def _extract_data_fields(ts):
    """compliance.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    transparency = {"aiDisclosureRequired": True, "aiDisclosureConfigured": False,
                    "recordingNoticeRequired": False, "recordingNoticeConfigured": False,
                    "noDeceptiveImpersonation": True}
    recording = {"channelMode": "single", "recordingConsentModel": "notice", "piiRedaction": False, "cardOtpMasking": True}
    residency = {"homeRegion": "EU", "inRegionStorageRequired": True, "providerRegionPinning": False, "crossBorderMechanism": "scc"}
    outbound = {"consentModel": "opt_in", "consentRegistry": "none", "dncLists": [], "callingHoursLocal": "09:00–20:00",
                "cliPresentationRequired": True, "b2bExemption": False}
    retention = {"recordingDays": 0, "transcriptDays": 365, "auditDays": 730, "legalHoldSupported": True, "legalHoldActive": 1}
    overrides = [{"id": "A", "key": "cp.x", "baseline": "1", "value": "2", "direction": "tighten"},
                 {"id": "B", "key": "cp.y", "baseline": "1", "value": "2", "direction": "loosen"}]

    chk(disclosure_gaps(transparency) == ["ai_disclosure"], "disclosureGaps=[ai_disclosure]")
    chk(recording_gaps(recording) == ["pii_redaction"], "recordingGaps=[pii_redaction]")
    chk(residency_gaps(residency) == ["provider_pinning"], "residencyGaps=[provider_pinning]")
    chk(outbound_gaps(outbound) == ["consent_registry", "dnc"], "outboundGaps=[consent_registry,dnc]")
    chk(loosen_overrides(overrides) == ["B"], "loosenOverrides=[B]")
    chk(invalid_retention(retention) == ["recording"], "invalidRetention=[recording]")
    chk(dpia_pending({"status": "required"}) is True and dpia_pending({"status": "completed"}) is False, "dpiaPending")
    # kapalı kayıt → recording gap yok
    chk(recording_gaps({"channelMode": "off", "piiRedaction": False, "cardOtpMasking": False}) == [], "recordingGaps off=[]")
    # cross-border branch (in-region zorunlu DEĞİL + none)
    chk(residency_gaps({"inRegionStorageRequired": False, "providerRegionPinning": False, "crossBorderMechanism": "none"}) == ["cross_border"], "residencyGaps cross_border")
    # opt_out → outbound gap yok
    chk(outbound_gaps({"consentModel": "opt_out", "consentRegistry": "none", "dncLists": []}) == [], "outboundGaps opt_out=[]")
    # tone eşlemeleri
    chk(dpia_status_tone("required") == "danger" and dpia_status_tone("completed") == "success", "dpiaStatusTone")
    chk(override_direction_tone("loosen") == "danger" and override_direction_tone("tighten") == "success", "overrideDirectionTone")
    chk(cross_border_tone("scc") == "success" and cross_border_tone("none") == "neutral", "crossBorderTone")
    chk(consent_model_tone("opt_in") == "success" and consent_model_tone("opt_out") == "warning", "consentModelTone")
    chk(channel_mode_tone("off") == "neutral" and channel_mode_tone("dual") == "info", "channelModeTone")
    chk(required_flag_tone(True, False) == "danger" and required_flag_tone(True, True) == "success" and required_flag_tone(False, False) == "neutral", "requiredFlagTone")
    chk(guard_flag_tone(True) == "success" and guard_flag_tone(False) == "danger", "guardFlagTone")
    # assertNoPii — kendi konfigürasyon İZİNLİ, son-müşteri PII + sır YASAK
    chk(assert_no_pii({"recordingPolicy": {"piiRedaction": True, "channelMode": "dual"}}) is None, "assertNoPii recordingPolicy/piiRedaction İZİNLİ")
    chk(assert_no_pii({"outbound": {"dncLists": ["IYS_ret"], "consentRegistry": "IYS"}}) is None, "assertNoPii DNC kaynak adı İZİNLİ")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"x": {"recording": "u"}}) == "$.x.recording", "assertNoPii ham recording yakalar")
    chk(assert_no_pii({"int": {"credential": "x"}}) == "$.int.credential", "assertNoPii credential yakalar (NFR 10.6)")
    chk(assert_no_pii({"k": {"kmsKey": "x"}}) == "$.k.kmsKey", "assertNoPii KMS anahtarı yakalar")

    # samples doğrulaması
    for name in ("compliance-clean.json", "compliance-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(disclosure_gaps(snap["transparency"]) == exp.get("disclosure_gaps"), f"{name} disclosure_gaps={exp.get('disclosure_gaps')}")
        chk(recording_gaps(snap["recordingPolicy"]) == exp.get("recording_gaps"), f"{name} recording_gaps={exp.get('recording_gaps')}")
        chk(residency_gaps(snap["residency"]) == exp.get("residency_gaps"), f"{name} residency_gaps={exp.get('residency_gaps')}")
        chk(outbound_gaps(snap["outbound"]) == exp.get("outbound_gaps"), f"{name} outbound_gaps={exp.get('outbound_gaps')}")
        chk(loosen_overrides(snap["overrides"]) == exp.get("loosen"), f"{name} loosen={exp.get('loosen')}")
        chk(invalid_retention(snap["retention"]) == exp.get("invalid_retention"), f"{name} invalid_retention={exp.get('invalid_retention')}")
        chk(dpia_pending(snap["dpia"]) == exp.get("dpia_pending"), f"{name} dpia_pending={exp.get('dpia_pending')}")
        chk(open_warning_count(snap) == exp.get("open_warnings"), f"{name} open_warnings={exp.get('open_warnings')}")
        chk(assert_no_pii(snap) is None, f"{name} PII/sır-free (HİJYEN+GÜVENLİK)")

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

    clean_t = {"aiDisclosureRequired": True, "aiDisclosureConfigured": True,
               "recordingNoticeRequired": True, "recordingNoticeConfigured": True, "noDeceptiveImpersonation": True}
    clean_r = {"channelMode": "dual", "piiRedaction": True, "cardOtpMasking": True}
    clean_res = {"inRegionStorageRequired": True, "providerRegionPinning": True, "crossBorderMechanism": "scc"}
    clean_out = {"consentModel": "opt_in", "consentRegistry": "IYS", "dncLists": ["IYS_ret"]}
    clean_ret = {"recordingDays": 180, "transcriptDays": 365, "auditDays": 730, "legalHoldSupported": True, "legalHoldActive": 0}
    # pozitif (temiz → boş)
    expect(disclosure_gaps(clean_t) == [], "pos disclosure boş")
    expect(recording_gaps(clean_r) == [], "pos recording boş")
    expect(residency_gaps(clean_res) == [], "pos residency boş")
    expect(outbound_gaps(clean_out) == [], "pos outbound boş")
    expect(invalid_retention(clean_ret) == [], "pos retention geçerli")
    expect(loosen_overrides([{"id": "A", "direction": "tighten"}]) == [], "pos sıkılaştır → ihlal yok")
    expect(dpia_pending({"status": "not_required"}) is False, "pos dpia gerekli değil")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(disclosure_gaps({"aiDisclosureRequired": True, "aiDisclosureConfigured": False, "recordingNoticeRequired": True, "recordingNoticeConfigured": False}) == ["ai_disclosure", "recording_notice"], "neg her iki bildirim eksik")
    expect(recording_gaps({"channelMode": "single", "piiRedaction": False, "cardOtpMasking": False}) == ["pii_redaction", "card_otp"], "neg kayıt korumaları eksik")
    expect(residency_gaps({"inRegionStorageRequired": True, "providerRegionPinning": False, "crossBorderMechanism": "scc"}) == ["provider_pinning"], "neg provider pinning eksik")
    expect(outbound_gaps({"consentModel": "soft_opt_in", "consentRegistry": "", "dncLists": []}) == ["consent_registry", "dnc"], "neg soft opt-in boşluk")
    expect(invalid_retention({"recordingDays": -1, "transcriptDays": 0, "auditDays": 730}) == ["recording", "transcript"], "neg geçersiz saklama")
    expect(loosen_overrides([{"id": "Z", "direction": "loosen"}]) == ["Z"], "neg gevşeten override yakalanır")
    expect(dpia_pending({"status": "in_progress"}) is True, "neg dpia devam ediyor → bekliyor")
    # openWarningCount toplamı
    snap = {"transparency": {"aiDisclosureRequired": True, "aiDisclosureConfigured": False, "recordingNoticeRequired": False, "recordingNoticeConfigured": False},
            "recordingPolicy": {"channelMode": "single", "piiRedaction": False, "cardOtpMasking": True},
            "residency": {"inRegionStorageRequired": True, "providerRegionPinning": False, "crossBorderMechanism": "scc"},
            "outbound": {"consentModel": "opt_in", "consentRegistry": "IYS", "dncLists": ["x"]},
            "retention": {"recordingDays": 1, "transcriptDays": 1, "auditDays": 1},
            "overrides": [{"id": "L", "direction": "loosen"}],
            "dpia": {"status": "required"}}
    expect(open_warning_count(snap) == 1 + 1 + 1 + 0 + 1 + 0 + 1, "neg openWarningCount toplamı=5")
    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerId": "1"}}) is not None, "neg callerId yakalanır")
    expect(assert_no_pii({"s": [{"privateKey": "x"}]}) is not None, "neg private key yakalanır")
    # tone sınır
    expect(override_direction_tone("equal") == "neutral", "neg eşit → neutral")
    expect(required_flag_tone(False, True) == "neutral", "neg gerekli değil → neutral")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 100, "spec ≥100 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "ComplianceSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "profile": {"countryProfile": "PROFILE-TR|UK|EU|ME", "regime": "KVKK|UK_GDPR|EU_GDPR|ME",
                        "sectorOverlays": "str[] (overlay adı)", "lawfulBasisDefault": "str (öneri)", "dpaRequired": "bool"},
            "recordingPolicy": {"channelMode": "off|single|dual (FR-REC-002/003)", "recordingConsentModel": "notice|explicit_optin|all_party",
                                "piiRedaction": "bool (FR-REC-004)", "cardOtpMasking": "bool (FR-REC-005)"},
            "transparency": {"aiDisclosureRequired": "bool", "aiDisclosureConfigured": "bool",
                             "recordingNoticeRequired": "bool", "recordingNoticeConfigured": "bool", "noDeceptiveImpersonation": "bool"},
            "residency": {"homeRegion": "UK|EU|NA|ME (NFR 10.7)", "inRegionStorageRequired": "bool",
                          "providerRegionPinning": "bool", "crossBorderMechanism": "scc|adequacy|explicit_consent|none"},
            "retention": {"recordingDays": "int", "transcriptDays": "int", "auditDays": "int (≥ yasal asgari)",
                          "legalHoldSupported": "bool (FR-REC-007)", "legalHoldActive": "int (adet metadatası)"},
            "outbound": {"consentModel": "opt_in|soft_opt_in|opt_out (FR-OUT-003)", "consentRegistry": "str (kayıt ADI)",
                         "dncLists": "str[] (kaynak ADLARI — birey numarası DEĞİL, FR-OUT-006)", "callingHoursLocal": "str",
                         "cliPresentationRequired": "bool", "b2bExemption": "bool"},
            "dsr": {"accessSlaDays": "int", "erasureSlaDays": "int (FR-REC-010)", "rectificationSupported": "bool", "portabilitySupported": "bool"},
            "breach": {"authority": "str (makam ADI)", "authorityDeadlineHours": "int", "dataSubjectNotice": "high_risk|always"},
            "dpia": {"status": "not_required|required|in_progress|completed (DPIA §3)", "triggers": "str[] (DPIA-T-NN kod ADI)"},
            "overrides": [{"id": "str", "key": "cp.* yolu — izinli", "baseline": "str", "value": "str", "direction": "tighten|equal|loosen (DPIA §8)"}]
        },
        "hijyen": "FORBIDDEN_PII_KEYS dışı son-müşteri alanı yok (BRD §17.7); FORBIDDEN_SECRET_KEYS dışı sır/credential yok (NFR 10.6); assertNoPii çalışma-anında doğrular. Politika alan adları (recordingPolicy/piiRedaction) politika parametresidir → izinli. Bireysel rıza/DNC kaydı + ham kayıt/transkript L2/data-plane'de tutulur. Değerler mühendislik varsayılanı; counsel doğrulamasına tabi (DPIA §12)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t06_compliance_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
