#!/usr/bin/env python3
# WBS 13.4.11 — A-11 "Çağrı Kayıtları" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countBy*/redactionPending/retentionImminent/legalHoldConflict/
#               unaudited/openAttentionCount/tone'lar/assertNoPii) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (redaction-bekleyen/yasal-tutma-çelişkisi/auditsiz/silinmek-üzere)
#   schema    — çağrı kaydı görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/recordings.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a11-recordings-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "recordings", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "recordings.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

DIRECTION_ORDER = ["inbound", "outbound"]
OUTCOME_ORDER = ["contained", "transferred", "abandoned", "voicemail", "failed"]
RECORDING_ORDER = ["recorded", "disabled", "none"]
TRANSCRIPT_ORDER = ["redacted", "pending", "not_required", "none"]

FORBIDDEN_PII_KEYS = ["transcript", "transcripttext", "redactedtext", "recording", "recordingbytes",
                      "audio", "audiobytes", "segment", "segments", "summary", "text", "e164", "frome164",
                      "toe164", "fromnumber", "tonumber", "msisdn", "phonenumber", "callerid", "callernumber",
                      "calleenumber", "customer", "customername", "contact", "cardpan", "pan", "cvv", "otp",
                      "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token", "bearertoken", "accesstoken",
                         "credential", "password", "privatekey", "kmskey", "storageuri", "storageurl",
                         "objecturi", "objectkey", "signedurl", "downloadurl", "url", "baseurl", "uri", "bucket"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/recordings.ts ile birebir) ────────────────────────

def sorted_calls(view):
    return sorted(view["calls"], key=lambda c: (_neg(c["startedAt"]), c["callRef"]))


class _neg:
    # localeCompare DESC eşdeğeri: startedAt'i ters sıralamak için sarmalayıcı.
    __slots__ = ("s",)

    def __init__(self, s):
        self.s = s

    def __lt__(self, other):
        return self.s > other.s

    def __eq__(self, other):
        return self.s == other.s


def count_by_direction(calls):
    acc = {d: 0 for d in DIRECTION_ORDER}
    for c in calls:
        acc[c["direction"]] += 1
    return acc


def count_by_outcome(calls):
    acc = {o: 0 for o in OUTCOME_ORDER}
    for c in calls:
        acc[c["outcome"]] += 1
    return acc


def count_by_recording_state(calls):
    acc = {r: 0 for r in RECORDING_ORDER}
    for c in calls:
        acc[c["recordingState"]] += 1
    return acc


def recorded_calls(calls):
    return [c for c in calls if c["recordingState"] == "recorded"]


def recording_disabled_calls(calls):
    return [c for c in calls if c["recordingState"] == "disabled"]


def dual_channel_calls(calls):
    return [c for c in calls if c["channels"] == 2]


def transcript_calls(calls):
    return [c for c in calls if c["transcriptState"] != "none"]


def redaction_pending_calls(calls):
    return [c for c in calls if c["transcriptState"] == "pending"]


def redacted_calls(calls):
    return [c for c in calls if c["transcriptState"] == "redacted"]


def legal_hold_calls(calls):
    return [c for c in calls if c["legalHold"]]


def retention_imminent_calls(calls):
    return [c for c in calls if c["retentionImminent"] and not c["legalHold"]]


def legal_hold_conflict_calls(calls):
    return [c for c in calls if c["legalHold"] and c["retentionImminent"]]


def unaudited_calls(calls):
    return [c for c in calls if not c["accessAudited"]]


def own_calls(calls):
    return [c for c in calls if c["own"]]


def open_attention_count(view):
    calls = view["calls"]
    return (len(redaction_pending_calls(calls))
            + len(retention_imminent_calls(calls))
            + len(legal_hold_conflict_calls(calls))
            + len(unaudited_calls(calls)))


def direction_tone(d):
    return {"inbound": "neutral", "outbound": "info"}[d]


def outcome_tone(o):
    return {"contained": "success", "transferred": "info", "abandoned": "warning",
            "voicemail": "neutral", "failed": "danger"}[o]


def recording_tone(r):
    return {"recorded": "success", "disabled": "neutral", "none": "neutral"}[r]


def transcript_tone(t):
    return {"redacted": "success", "pending": "warning", "not_required": "neutral", "none": "neutral"}[t]


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/nesne-depo URI alan adı bulursa (path) döndürür; yoksa None."""
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
    """recordings.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.11", "S0 spec.wbs=13.4.11")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/recordings/page.tsx mevcut")
    chk('data-screen="A-11"' in page, 'S1 data-screen="A-11" işaretli')
    chk("İskelet ekran — A-11" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/recordings" in page, "S2 veri seam (lib/tenant/recordings) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a11.*); hardcoded TR/EN cümle yok
    chk("screen.a11." in page, "S3 screen.a11.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/URI-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/recordings.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getCallRecordsView assertNoPii çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("transcript", "recording", "e164", "summary")), "S4 ham ses/transkript/numara/özet yasak (BRD §17.7 / FR-REC-004/005)")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("storageuri", "url", "kmskey")), "S4 nesne-depo URI/sır yasak (NFR 10.6)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/URI alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-REC-001..010 + FR-ANA-002/003 karşılanır
    a11 = tr.get("screen", {}).get("a11", {})
    sec = a11.get("section", {})
    for s in ("summary", "records", "outcomes", "recording_states", "retention", "access"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("countByRecordingState" in data and set(RECORDING_ORDER).issubset(a11.get("recording", {}).keys()), "S5 kayıt durumu recorded/disabled/none (FR-REC-001/002)")
    chk("dualChannelCalls" in data and "dual_channel" in a11.get("kpi", {}), "S5 tek/çift kanal (FR-REC-003)")
    chk("redactionPendingCalls" in data and set(TRANSCRIPT_ORDER).issubset(a11.get("transcript", {}).keys()) and "redaction_pending" in a11.get("alert", {}), "S5 transkript redaction durumu (FR-REC-004)")
    chk("scrub" in a11.get("access", {}), "S5 kart/parola/OTP gizleme (FR-REC-005)")
    chk("retentionImminentCalls" in data and "retention_imminent" in a11.get("alert", {}), "S5 saklama süresi + geri döndürülemez silme (FR-REC-006/010)")
    chk("legalHoldCalls" in data and "legalHoldConflictCalls" in data and "legal_hold_conflict" in a11.get("alert", {}), "S5 legal hold + çelişki (FR-REC-007)")
    chk("accessAudited" in data and "unauditedCalls" in data and "audit" in a11.get("access", {}), "S5 yetkili erişim + erişim audit (FR-REC-008/009)")
    chk("countByOutcome" in data and set(OUTCOME_ORDER).issubset(a11.get("outcome", {}).keys()), "S5 sonuç/outcome dağılımı (FR-ANA-002/003)")
    chk("ownCalls" in data and "own" in data and "own_badge" in a11, "S5 sahiplik (human_agent kendi — BRD §17.6/§17.7)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a11.{rk}"
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
        vt = resolve(tr, f"screen.a11.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedCalls", "countByDirection", "countByOutcome", "countByRecordingState",
               "recordedCalls", "recordingDisabledCalls", "dualChannelCalls", "transcriptCalls",
               "redactionPendingCalls", "redactedCalls", "legalHoldCalls", "retentionImminentCalls",
               "legalHoldConflictCalls", "unauditedCalls", "ownCalls", "openAttentionCount",
               "directionTone", "outcomeTone", "recordingTone", "transcriptTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("DIRECTION_ORDER", "OUTCOME_ORDER", "RECORDING_ORDER", "TRANSCRIPT_ORDER")), "S7 *_ORDER sabitleri tanımlı")
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

def _call(ref, started, direction="inbound", outcome="contained", rec="recorded", channels=2,
          transcript="redacted", retention=False, hold=False, audited=True, own=False):
    return {"callRef": ref, "direction": direction, "agentRef": "AGT-1", "agentName": "A",
            "startedAt": started, "durationSec": 100, "outcome": outcome, "recordingState": rec,
            "channels": channels, "transcriptState": transcript, "retentionImminent": retention,
            "legalHold": hold, "accessAudited": audited, "own": own}


def _base_view():
    # 6 çağrı: c05 redaction-bekliyor; c03 kayıt-kapalı; c02 silinmek-üzere; c01 yasal-tutma; c04 voicemail/kayıtsız.
    return {"generatedAt": "2026-06-18T09:00:00.000Z", "tenantRef": "TEN-1", "tenantName": "T", "calls": [
        _call("CALL-1006", "2026-06-18T08:55:00.000Z", "inbound", "contained", "recorded", 2, "redacted"),
        _call("CALL-1005", "2026-06-18T08:40:00.000Z", "inbound", "transferred", "recorded", 2, "pending", own=True),
        _call("CALL-1004", "2026-06-18T08:25:00.000Z", "outbound", "voicemail", "none", 0, "none"),
        _call("CALL-1003", "2026-06-18T08:10:00.000Z", "outbound", "contained", "disabled", 0, "not_required"),
        _call("CALL-1002", "2026-06-18T07:50:00.000Z", "inbound", "abandoned", "recorded", 1, "redacted", retention=True),
        _call("CALL-1001", "2026-06-18T07:30:00.000Z", "inbound", "transferred", "recorded", 2, "redacted", hold=True),
    ]}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    calls = v["calls"]
    chk([c["callRef"] for c in sorted_calls(v)] == ["CALL-1006", "CALL-1005", "CALL-1004", "CALL-1003", "CALL-1002", "CALL-1001"], "sortedCalls DESC (en yeni önce)")
    chk(count_by_direction(calls) == {"inbound": 4, "outbound": 2}, "countByDirection")
    chk(count_by_outcome(calls) == {"contained": 2, "transferred": 2, "abandoned": 1, "voicemail": 1, "failed": 0}, "countByOutcome")
    chk(count_by_recording_state(calls) == {"recorded": 4, "disabled": 1, "none": 1}, "countByRecordingState")
    chk(len(recorded_calls(calls)) == 4, "recordedCalls=4 (FR-REC-001)")
    chk([c["callRef"] for c in recording_disabled_calls(calls)] == ["CALL-1003"], "recordingDisabledCalls=[1003] (FR-REC-002)")
    chk([c["callRef"] for c in dual_channel_calls(calls)] == ["CALL-1006", "CALL-1005", "CALL-1001"], "dualChannelCalls (FR-REC-003)")
    chk(len(transcript_calls(calls)) == 5, "transcriptCalls=5 (none hariç)")
    chk([c["callRef"] for c in redaction_pending_calls(calls)] == ["CALL-1005"], "redactionPendingCalls=[1005] (FR-REC-004)")
    chk(len(redacted_calls(calls)) == 3, "redactedCalls=3 (FR-REC-004)")
    chk([c["callRef"] for c in legal_hold_calls(calls)] == ["CALL-1001"], "legalHoldCalls=[1001] (FR-REC-007)")
    chk([c["callRef"] for c in retention_imminent_calls(calls)] == ["CALL-1002"], "retentionImminentCalls=[1002] (FR-REC-006/010)")
    chk(legal_hold_conflict_calls(calls) == [], "legalHoldConflictCalls=[] (sağlıklı; FR-REC-007)")
    chk(unaudited_calls(calls) == [], "unauditedCalls=[] (sağlıklı; FR-REC-009)")
    chk([c["callRef"] for c in own_calls(calls)] == ["CALL-1005"], "ownCalls=[1005] (human_agent kapsamı)")
    # attention = redaction_pending(1)+retention_imminent(1)+conflict(0)+unaudited(0) = 2
    chk(open_attention_count(v) == 2, "openAttentionCount=2")

    # tone eşlemeleri
    chk(direction_tone("inbound") == "neutral" and direction_tone("outbound") == "info", "directionTone")
    chk(outcome_tone("contained") == "success" and outcome_tone("failed") == "danger" and outcome_tone("abandoned") == "warning", "outcomeTone")
    chk(recording_tone("recorded") == "success" and recording_tone("disabled") == "neutral", "recordingTone")
    chk(transcript_tone("pending") == "warning" and transcript_tone("redacted") == "success", "transcriptTone")

    # assertNoPii — ÇAĞRI META İZİNLİ, ham içerik + sır + URI YASAK
    chk(assert_no_pii({"a": _base_view()}) is None, "assertNoPii çağrı META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript metni yakalar (FR-REC-004)")
    chk(assert_no_pii({"x": {"recording": "..."}}) == "$.x.recording", "assertNoPii ham ses kaydı yakalar (FR-REC-002)")
    chk(assert_no_pii({"x": {"toE164": "+90..."}}) == "$.x.toE164", "assertNoPii ham numara yakalar (BRD §17.7)")
    chk(assert_no_pii({"x": {"storageUri": "s3://..."}}) == "$.x.storageUri", "assertNoPii nesne-depo URI yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"summary": "..."}}) == "$.x.summary", "assertNoPii çağrı özeti yakalar")
    chk(assert_no_pii({"x": {"cardPan": "4111"}}) == "$.x.cardPan", "assertNoPii kart PAN yakalar (FR-REC-005)")

    # samples doğrulaması
    for name in ("records-clean.json", "records-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        cs = snp["calls"]
        chk(len(cs) == exp.get("calls"), f"{name} calls={exp.get('calls')}")
        chk(len(recorded_calls(cs)) == exp.get("recorded"), f"{name} recorded={exp.get('recorded')}")
        chk(len(recording_disabled_calls(cs)) == exp.get("recording_disabled"), f"{name} recording_disabled={exp.get('recording_disabled')}")
        chk(len(redaction_pending_calls(cs)) == exp.get("redaction_pending"), f"{name} redaction_pending={exp.get('redaction_pending')}")
        chk(len(legal_hold_calls(cs)) == exp.get("legal_hold"), f"{name} legal_hold={exp.get('legal_hold')}")
        chk(len(retention_imminent_calls(cs)) == exp.get("retention_imminent"), f"{name} retention_imminent={exp.get('retention_imminent')}")
        chk(len(legal_hold_conflict_calls(cs)) == exp.get("legal_hold_conflict"), f"{name} legal_hold_conflict={exp.get('legal_hold_conflict')}")
        chk(len(unaudited_calls(cs)) == exp.get("unaudited"), f"{name} unaudited={exp.get('unaudited')}")
        chk(open_attention_count(snp) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır/URI-free (HİJYEN+GÜVENLİK)")

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

    # pozitif (sağlıklı: redaction tamam + audit'li + yasal-tutma çelişkisiz + silinmek-üzere yok)
    ok = {"calls": [
        _call("C1", "2026-06-18T08:00:00.000Z", "inbound", "contained", "recorded", 2, "redacted"),
        _call("C2", "2026-06-18T07:00:00.000Z", "outbound", "transferred", "recorded", 1, "not_required"),
    ]}
    expect(open_attention_count(ok) == 0, "pos açık dikkat=0")
    expect(len(redaction_pending_calls(ok["calls"])) == 0, "pos redaction bekleyen yok")
    expect(len(legal_hold_conflict_calls(ok["calls"])) == 0, "pos yasal-tutma çelişkisi yok")
    expect(len(unaudited_calls(ok["calls"])) == 0, "pos auditsiz erişim yok")
    expect(len(retention_imminent_calls(ok["calls"])) == 0, "pos silinmek-üzere yok")

    # negatif (çok-sorunlu: redaction-bekleyen + yasal-tutma-çelişkisi + auditsiz + silinmek-üzere)
    bad = {"calls": [
        _call("C1", "2026-06-18T08:00:00.000Z", "inbound", "contained", "recorded", 2, "pending"),         # redaction bekliyor
        _call("C2", "2026-06-18T07:30:00.000Z", "inbound", "abandoned", "recorded", 1, "redacted", retention=True, hold=True),  # çelişki (hold+imminent)
        _call("C3", "2026-06-18T07:00:00.000Z", "outbound", "failed", "recorded", 2, "redacted", audited=False),  # auditsiz
        _call("C4", "2026-06-18T06:30:00.000Z", "inbound", "contained", "recorded", 1, "redacted", retention=True),  # silinmek üzere
    ]}
    expect([c["callRef"] for c in redaction_pending_calls(bad["calls"])] == ["C1"], "neg redaction-bekleyen=[C1] (FR-REC-004)")
    expect([c["callRef"] for c in legal_hold_conflict_calls(bad["calls"])] == ["C2"], "neg yasal-tutma çelişkisi=[C2] (FR-REC-007)")
    expect([c["callRef"] for c in unaudited_calls(bad["calls"])] == ["C3"], "neg auditsiz=[C3] (FR-REC-009)")
    expect([c["callRef"] for c in retention_imminent_calls(bad["calls"])] == ["C4"], "neg silinmek-üzere=[C4] (FR-REC-006/010)")
    # C2 hem hold hem imminent → retentionImminent SAYMAZ (yasal tutma askıya alır) ama conflict SAYAR
    expect(len(retention_imminent_calls(bad["calls"])) == 1, "neg yasal-tutma retention'ı askıya alır (imminent yalnız C4)")
    # attention = redaction_pending(1)+retention_imminent(1: C4)+conflict(1: C2)+unaudited(1: C3) = 4
    expect(open_attention_count(bad) == 4, "neg açık dikkat=4")

    # sınır: boş envanter
    empty = {"calls": []}
    expect(sorted_calls(empty) == [], "sınır boş envanter çağrı yok")
    expect(open_attention_count(empty) == 0, "sınır boş envanter dikkat=0")
    expect(count_by_outcome([]) == {o: 0 for o in OUTCOME_ORDER}, "sınır boş outcome dağılımı 0")

    # sınır: yasal tutma TEK BAŞINA (imminent değil) çelişki DEĞİL + retentionImminent saymaz
    held = {"calls": [_call("C1", "2026-06-18T08:00:00.000Z", hold=True)]}
    expect(len(legal_hold_conflict_calls(held["calls"])) == 0, "sınır yalnız yasal-tutma çelişki değil")
    expect(len(retention_imminent_calls(held["calls"])) == 0, "sınır yasal-tutma silinmek-üzere saymaz")
    expect(len(legal_hold_calls(held["calls"])) == 1, "sınır yasal-tutma=1")

    # sınır: kayıtsız çağrı transkriptsiz + çift-kanal saymaz
    nr = {"calls": [_call("C1", "2026-06-18T08:00:00.000Z", rec="none", channels=0, transcript="none")]}
    expect(len(transcript_calls(nr["calls"])) == 0, "sınır kayıtsız transkriptsiz")
    expect(len(dual_channel_calls(nr["calls"])) == 0, "sınır kayıtsız çift-kanal saymaz")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"phoneNumber": "1"}}) is not None, "neg phoneNumber yakalanır")
    expect(assert_no_pii({"s": [{"audioBytes": "x"}]}) is not None, "neg audioBytes yakalanır (FR-REC-002)")
    expect(assert_no_pii({"x": {"downloadUrl": "..."}}) is not None, "neg downloadUrl yakalanır (NFR 10.6)")
    expect(assert_no_pii({"x": {"otp": "123"}}) is not None, "neg otp yakalanır (FR-REC-005)")

    # tone sınır
    expect(outcome_tone("failed") == "danger", "failed → danger")
    expect(transcript_tone("pending") == "warning", "pending → warning")
    expect(direction_tone("outbound") == "info", "outbound → info")

    # placeholder ayrıştırma
    expect(placeholders("{count} kayıt") == {"count"}, "placeholder parse")
    expect(placeholders("{min} dk {sec} sn") == {"min", "sec"}, "placeholder çoklu parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 80, "spec ≥80 referans anahtar")
    expect(spec["outcomes"] == OUTCOME_ORDER, "spec outcomes = OUTCOME_ORDER")
    expect(spec["recording_states"] == RECORDING_ORDER, "spec recording_states = RECORDING_ORDER")
    expect(spec["transcript_states"] == TRANSCRIPT_ORDER, "spec transcript_states = TRANSCRIPT_ORDER")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "CallRecordsView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "calls": [{
                "callRef": "str (çağrı VEKİL kimliği — telefon numarası DEĞİL)",
                "direction": "inbound|outbound (DB §19)",
                "agentRef": "str (agent kimliği)",
                "agentName": "str (agent adı — tenant config; PII değil)",
                "startedAt": "ISO-8601 (sabit yer tutucu)",
                "durationSec": "int (çağrı süresi sn)",
                "outcome": "contained|transferred|abandoned|voicemail|failed (FR-ANA-002/003 + FR-OUT-008)",
                "recordingState": "recorded|disabled|none (FR-REC-001/002; yalnız DURUM — ham ses gömülmez)",
                "channels": "0|1|2 (FR-REC-003 — tek/çift kanal; kayıtsızda 0)",
                "transcriptState": "redacted|pending|not_required|none (FR-REC-004; yalnız DURUM — metin gömülmez)",
                "retentionImminent": "bool (FR-REC-006/010 — saklama süresi dolmak üzere)",
                "legalHold": "bool (FR-REC-007 — silmeye karşı korunur; retention'ı askıya alır)",
                "accessAudited": "bool (FR-REC-009 — erişim-audit yolu işaretli; INVARIANT: true)",
                "own": "bool (BRD §17.6/§17.7 — human_agent kapsamı; bu çağrı kullanıcıya aktarıldı mı)"
            }]
        },
        "directions": DIRECTION_ORDER,
        "outcomes": OUTCOME_ORDER,
        "recording_states": RECORDING_ORDER,
        "transcript_states": TRANSCRIPT_ORDER,
        "invariants": "redactionPendingCalls (transkript pending — FR-REC-004) + retentionImminentCalls (saklama dolan & !legalHold — FR-REC-006/010) + legalHoldConflictCalls (legalHold & retentionImminent — FR-REC-007 ihlali) + unauditedCalls (!accessAudited — FR-REC-009 ihlali) = dikkat kalemleri; conflict + unaudited SIFIR olmalı (sağlıklı).",
        "hijyen": "A-11 yalnız ÇAĞRI META gösterir (yön/agent/sonuç/süre/kayıt-transkript-saklama-yasal-tutma-erişim BAYRAKLARI/kanal/sahiplik + agent adı — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (ham ses kaydı/transkript metni/ham numara e164/müşteri/kart-OTP/çağrı özeti) YOK (BRD §17.7 + §17.6 + FR-REC-004/005); FORBIDDEN_SECRET_KEYS dışı sır/credential + nesne-depo URI'si (storageUri/url/signedUrl/kmsKey) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Çağrıyı dinleme/transkripti görme derin aksiyon → A-12 + FR-REC-008/009 yetki + audit (görsel kapı). ARAMA/FİLTRELEME ekranı (FR-REC-001..010 + FR-ANA-002/003); gerçek zamanlı DEĞİL."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a11_recordings_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
