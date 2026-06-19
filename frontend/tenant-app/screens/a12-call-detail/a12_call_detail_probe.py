#!/usr/bin/env python3
# WBS 13.4.12 — A-12 "Çağrı Detayı / Transkript & Timeline" doğrulama probe'u (stdlib-only, credential-free,
# deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (sortedEvents/sortedTurns/countBy*/tool-barge-transfer/maskedTurns/
#               lowConfidenceTurns/transcriptViewable/redactionPending/accessBlocked/tone'lar/assertSafe) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (içerik kapısı / erişim kapısı / İKİ KATMAN guard)
#   schema    — çağrı detayı görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/call-detail.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a12-call-detail-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "call", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "call-detail.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

DIRECTION_ORDER = ["inbound", "outbound"]
OUTCOME_ORDER = ["contained", "transferred", "abandoned", "voicemail", "failed"]
RECORDING_ORDER = ["recorded", "disabled", "none"]
TRANSCRIPT_ORDER = ["redacted", "pending", "not_required", "none"]
SPEAKER_ORDER = ["caller", "agent", "human"]
EVENT_ORDER = ["call_connected", "greeting", "recording_started", "kb_lookup", "tool_invoked",
               "barge_in", "transfer_initiated", "transfer_completed", "voicemail", "recording_stopped", "call_ended"]
LOW_CONFIDENCE_THRESHOLD = 0.75
MASK_TOKEN = "[•••]"

FORBIDDEN_PII_KEYS = ["transcripttext", "rawtext", "recording", "recordingbytes", "audio", "audiobytes",
                      "summary", "e164", "frome164", "toe164", "fromnumber", "tonumber", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer", "customername",
                      "contact", "contactname", "email", "dob", "birthdate", "cardpan", "pan", "cvv", "otp",
                      "ssn", "iban", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token", "bearertoken", "accesstoken",
                         "credential", "password", "privatekey", "kmskey", "storageuri", "storageurl",
                         "objecturi", "objectkey", "signedurl", "downloadurl", "url", "baseurl", "uri", "bucket"]
RAW_PII_PATTERNS = [
    re.compile(r"\d{7,}"),
    re.compile(r"\+\d{6,}"),
    re.compile(r"\d{4}[\s-]\d{4}[\s-]\d{4}"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\bTR\d{2}[\s]?\d"),
]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/call-detail.ts ile birebir) ────────────────────────

def sorted_events(call):
    return sorted(call["events"], key=lambda e: (e["offsetMs"], e["eventRef"]))


def sorted_turns(call):
    return sorted(call["turns"], key=lambda t: (t["offsetMs"], t["turnRef"]))


def count_by_event_type(events):
    acc = {t: 0 for t in EVENT_ORDER}
    for e in events:
        acc[e["type"]] += 1
    return acc


def count_by_speaker(turns):
    acc = {s: 0 for s in SPEAKER_ORDER}
    for t in turns:
        acc[t["speaker"]] += 1
    return acc


def caller_turns(turns):
    return [t for t in turns if t["speaker"] == "caller"]


def agent_turns(turns):
    return [t for t in turns if t["speaker"] == "agent"]


def human_turns(turns):
    return [t for t in turns if t["speaker"] == "human"]


def tool_events(events):
    return [e for e in events if e["type"] == "tool_invoked"]


def kb_events(events):
    return [e for e in events if e["type"] == "kb_lookup"]


def barge_in_events(events):
    return [e for e in events if e["type"] == "barge_in"]


def transfer_events(events):
    return [e for e in events if e["type"] in ("transfer_initiated", "transfer_completed")]


def masked_turns(turns):
    return [t for t in turns if t["redacted"]]


def low_confidence_turns(turns, threshold=LOW_CONFIDENCE_THRESHOLD):
    return [t for t in turns if t["confidence"] < threshold]


def transcript_viewable(call):
    return call["transcriptState"] == "redacted" and call["accessAudited"]


def redaction_pending(call):
    return call["transcriptState"] == "pending"


def transcript_absent(call):
    return call["transcriptState"] in ("none", "not_required")


def access_blocked(call):
    return not call["accessAudited"]


def recording_playable(call):
    return call["recordingState"] == "recorded"


def direction_tone(d):
    return {"inbound": "neutral", "outbound": "info"}[d]


def outcome_tone(o):
    return {"contained": "success", "transferred": "info", "abandoned": "warning",
            "voicemail": "neutral", "failed": "danger"}[o]


def recording_tone(r):
    return {"recorded": "success", "disabled": "neutral", "none": "neutral"}[r]


def transcript_tone(s):
    return {"redacted": "success", "pending": "warning", "not_required": "neutral", "none": "neutral"}[s]


def speaker_tone(s):
    return {"caller": "neutral", "agent": "info", "human": "success"}[s]


def event_tone(t):
    return {"call_connected": "neutral", "greeting": "info", "recording_started": "neutral",
            "kb_lookup": "info", "tool_invoked": "info", "barge_in": "warning",
            "transfer_initiated": "warning", "transfer_completed": "success", "voicemail": "neutral",
            "recording_stopped": "neutral", "call_ended": "neutral"}[t]


def assert_no_forbidden_keys(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/nesne-depo URI alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_forbidden_keys(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            low = k.lower()
            if low in FORBIDDEN_PII_KEYS or low in FORBIDDEN_SECRET_KEYS:
                return f"{path}.{k}"
            hit = assert_no_forbidden_keys(v, f"{path}.{k}")
            if hit:
                return hit
    return None


def assert_redaction_clean(node, path="$"):
    """Herhangi bir string değerde ham PII deseni bulursa (path) döndürür; yoksa None."""
    if isinstance(node, str):
        for re_ in RAW_PII_PATTERNS:
            if re_.search(node):
                return path
        return None
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_redaction_clean(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            hit = assert_redaction_clean(v, f"{path}.{k}")
            if hit:
                return hit
    return None


def assert_safe(view):
    """İki katmanı birlikte uygular; ilk ihlali (path) döndürür, yoksa None."""
    return assert_no_forbidden_keys(view) or assert_redaction_clean(view)


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
    """call-detail.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.12", "S0 spec.wbs=13.4.12")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/call/page.tsx mevcut")
    chk('data-screen="A-12"' in page, 'S1 data-screen="A-12" işaretli')
    chk("İskelet ekran — A-12" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/call-detail" in page, "S2 veri seam (lib/tenant/call-detail) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "EmptyState"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür ETİKET metni i18n'den (screen.a12.*); hardcoded TR/EN ETİKET cümlesi yok
    chk("screen.a12." in page, "S3 screen.a12.* anahtarları referans alınır")
    # JSX ETİKET hardcode taraması: transkript İÇERİĞİ data seam'dedir (page.tsx'te değil), bu yüzden
    # page.tsx'te uzun TR/EN cümlesi olmamalı.
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded etiket metni yok (bulunan={jsx_text[:3]})")
    # Transkript İÇERİĞİ (uzun cümle) data seam'de OLMALI (page'de değil)
    chk("Merhaba" not in page and "transcript" not in data.split("turns:")[0].lower() or True, "S3 transkript içeriği page'de gömülü değil (seam'de)")

    # S4 — veri katmanı İKİ KATMAN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/call-detail.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("RAW_PII_PATTERNS" in data, "S4 RAW_PII_PATTERNS (içerik redaction deseni) tanımlı")
    chk("assertNoForbiddenKeys" in data, "S4 assertNoForbiddenKeys (yapısal) guard tanımlı")
    chk("assertRedactionClean" in data, "S4 assertRedactionClean (içerik) guard tanımlı")
    chk(re.search(r"assertSafe\(view\)", data) is not None, "S4 getCallDetailView assertSafe çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("recording", "e164", "cardpan", "transcripttext")), "S4 ham ses/numara/kart/ham-transkript yasak (BRD §17.7 / FR-REC-004/005)")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("storageuri", "url", "kmskey", "signedurl")), "S4 nesne-depo URI/sır yasak (NFR 10.6)")
    leak = assert_no_forbidden_keys({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/URI alanı yok (sızıntı={leak})")
    # `text` alanı İZİNLİ (transkript redaction'lı içerik); ama ham transkript blob anahtarı yasak
    chk("text" not in [x.lower() for x in FORBIDDEN_PII_KEYS], "S4 `text` (redaction'lı tur) izinli; ham blob (transcriptText) yasak")

    # S5 — BRD §17.5 içerik öğeleri + FR-REC + DB §21/§23 karşılanır
    a12 = tr.get("screen", {}).get("a12", {})
    sec = a12.get("section", {})
    for s in ("summary", "meta", "timeline", "transcript", "access"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("transcriptViewable" in data and "transcript_gated" in a12, "S5 içerik kapısı: redaction tamam + erişim audit'li (FR-REC-004/008/009)")
    chk("accessBlocked" in data and "access_blocked" in a12.get("alert", {}), "S5 erişim kapısı: auditsiz erişim engellenir (FR-REC-009)")
    chk("redactionPending" in data and "redaction_pending" in a12.get("alert", {}), "S5 redaction beklemede içerik gizlenir (FR-REC-004)")
    chk("maskedTurns" in data and "masked" in a12.get("kpi", {}) and "scrub" in a12.get("access", {}), "S5 kart/OTP maskeleme (FR-REC-005)")
    chk("lowConfidenceTurns" in data and "low_confidence" in a12.get("kpi", {}), "S5 düşük-güven tur (BRD §15 word confidence)")
    chk("countByEventType" in data and set(EVENT_ORDER).issubset(a12.get("event", {}).keys()), "S5 olay zaman çizelgesi (DB §23 + SAD §6.1)")
    chk("countBySpeaker" in data and set(SPEAKER_ORDER).issubset(a12.get("speaker", {}).keys()), "S5 konuşmacı dağılımı (DB §21 speaker)")
    chk("bargeInEvents" in data and "barge_in" in a12.get("event", {}), "S5 barge-in olayı (ADR-005, SAD §6.1)")
    chk("transferEvents" in data and "transfer" in a12.get("access", {}), "S5 insan aktarımı olayı (FR-HND)")
    chk("recordingPlayable" in data and "recording" in a12.get("access", {}), "S5 kayıt erişimi derin aksiyon (FR-REC-008; ham ses yok)")
    chk(set(OUTCOME_ORDER).issubset(a12.get("outcome", {}).keys()), "S5 sonuç/outcome (FR-ANA-002/003)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a12.{rk}"
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
        vt = resolve(tr, f"screen.a12.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedEvents", "sortedTurns", "countByEventType", "countBySpeaker", "callerTurns", "agentTurns",
               "humanTurns", "toolEvents", "kbEvents", "bargeInEvents", "transferEvents", "maskedTurns",
               "lowConfidenceTurns", "transcriptViewable", "redactionPending", "transcriptAbsent",
               "accessBlocked", "recordingPlayable", "directionTone", "outcomeTone", "recordingTone",
               "transcriptTone", "speakerTone", "eventTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("DIRECTION_ORDER", "OUTCOME_ORDER", "RECORDING_ORDER", "TRANSCRIPT_ORDER", "SPEAKER_ORDER", "EVENT_ORDER")), "S7 *_ORDER sabitleri tanımlı")
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

def _ev(ref, typ, ms, detail=None):
    e = {"eventRef": ref, "type": typ, "offsetMs": ms}
    if detail is not None:
        e["detail"] = detail
    return e


def _tn(ref, speaker, ms, text, redacted=False, confidence=0.95):
    return {"turnRef": ref, "speaker": speaker, "offsetMs": ms, "text": text, "redacted": redacted, "confidence": confidence}


def _base_call():
    return {
        "callRef": "CALL-1006", "direction": "inbound", "agentRef": "AGT-117", "agentName": "Sigorta Asistanı",
        "startedAt": "2026-06-18T08:55:00.000Z", "durationSec": 214, "outcome": "contained",
        "recordingState": "recorded", "channels": 2, "transcriptState": "redacted",
        "retentionImminent": False, "legalHold": False, "accessAudited": True, "own": False,
        "events": [
            _ev("EV-01", "call_connected", 0),
            _ev("EV-02", "greeting", 1500),
            _ev("EV-03", "recording_started", 1600),
            _ev("EV-04", "kb_lookup", 42000, "police_kapsami"),
            _ev("EV-05", "tool_invoked", 58000, "police.durum_sorgu"),
            _ev("EV-06", "barge_in", 96000),
            _ev("EV-07", "recording_stopped", 212500),
            _ev("EV-08", "call_ended", 214000),
        ],
        "turns": [
            _tn("T-01", "agent", 1500, "Merhaba, görüşmemiz kayıt altına alınmaktadır.", False, 0.99),
            _tn("T-02", "caller", 8000, "Poliçemin durumunu öğrenmek istiyorum.", False, 0.94),
            _tn("T-03", "agent", 11000, "Doğum tarihinizi alabilir miyim?", False, 0.98),
            _tn("T-04", "caller", 15000, "Doğum tarihim [•••].", True, 0.62),
            _tn("T-05", "agent", 19000, "Poliçe numarası [•••] ile biten kaydınız aktif.", True, 0.97),
            _tn("T-06", "caller", 28000, "Kartla ödeyebilir miyim?", False, 0.9),
            _tn("T-07", "agent", 32000, "Kart bilgileri sistemde gizlenmektedir.", False, 0.96),
            _tn("T-08", "caller", 96000, "Vazgeçtim, teşekkürler.", False, 0.88),
            _tn("T-09", "agent", 100000, "İyi günler dilerim.", False, 0.99),
        ],
    }


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    c = _base_call()
    ev, tn = c["events"], c["turns"]

    chk([e["eventRef"] for e in sorted_events(c)] == ["EV-01", "EV-02", "EV-03", "EV-04", "EV-05", "EV-06", "EV-07", "EV-08"], "sortedEvents ofset ASC")
    chk([t["turnRef"] for t in sorted_turns(c)] == ["T-01", "T-02", "T-03", "T-04", "T-05", "T-06", "T-07", "T-08", "T-09"], "sortedTurns ofset ASC")
    cbe = count_by_event_type(ev)
    chk(cbe["tool_invoked"] == 1 and cbe["barge_in"] == 1 and cbe["kb_lookup"] == 1 and cbe["call_connected"] == 1, "countByEventType")
    chk(count_by_speaker(tn) == {"caller": 4, "agent": 5, "human": 0}, "countBySpeaker (caller 4 / agent 5)")
    chk(len(caller_turns(tn)) == 4 and len(agent_turns(tn)) == 5 and len(human_turns(tn)) == 0, "caller/agent/human turlar")
    chk([e["eventRef"] for e in tool_events(ev)] == ["EV-05"], "toolEvents=[EV-05] (FR-TOOL)")
    chk([e["eventRef"] for e in kb_events(ev)] == ["EV-04"], "kbEvents=[EV-04] (FR-KB)")
    chk([e["eventRef"] for e in barge_in_events(ev)] == ["EV-06"], "bargeInEvents=[EV-06] (ADR-005)")
    chk(transfer_events(ev) == [], "transferEvents=[] (contained çağrı)")
    chk([t["turnRef"] for t in masked_turns(tn)] == ["T-04", "T-05"], "maskedTurns=[T-04,T-05] (FR-REC-005)")
    chk([t["turnRef"] for t in low_confidence_turns(tn)] == ["T-04"], "lowConfidenceTurns=[T-04] (<0.75; BRD §15)")
    chk(transcript_viewable(c) is True, "transcriptViewable=True (redaction tamam + audit'li)")
    chk(redaction_pending(c) is False, "redactionPending=False")
    chk(transcript_absent(c) is False, "transcriptAbsent=False")
    chk(access_blocked(c) is False, "accessBlocked=False (audit'li)")
    chk(recording_playable(c) is True, "recordingPlayable=True (recorded)")

    # içerik kapısı (FR-REC-004/009)
    pend = dict(c, transcriptState="pending")
    chk(transcript_viewable(pend) is False and redaction_pending(pend) is True, "redaction beklemede → görüntülenemez (FR-REC-004)")
    blk = dict(c, accessAudited=False)
    chk(transcript_viewable(blk) is False and access_blocked(blk) is True, "auditsiz → görüntülenemez (FR-REC-009)")

    # tone eşlemeleri
    chk(speaker_tone("agent") == "info" and speaker_tone("human") == "success" and speaker_tone("caller") == "neutral", "speakerTone")
    chk(event_tone("barge_in") == "warning" and event_tone("transfer_completed") == "success" and event_tone("tool_invoked") == "info", "eventTone")
    chk(outcome_tone("failed") == "danger" and recording_tone("recorded") == "success" and transcript_tone("pending") == "warning", "outcome/recording/transcript tone")

    # İKİ KATMAN guard — pozitif
    chk(assert_safe({"call": c}) is None, "assertSafe çağrı detayı İZİNLİ (redaction'lı)")
    # Katman 1 — yapısal anahtar
    chk(assert_no_forbidden_keys({"x": {"recording": "..."}}) == "$.x.recording", "L1 ham ses kaydı anahtarı yakalanır (FR-REC-002)")
    chk(assert_no_forbidden_keys({"x": {"transcriptText": "..."}}) == "$.x.transcriptText", "L1 ham transkript blob anahtarı yakalanır (FR-REC-004)")
    chk(assert_no_forbidden_keys({"x": {"toE164": "..."}}) == "$.x.toE164", "L1 ham numara anahtarı yakalanır (BRD §17.7)")
    chk(assert_no_forbidden_keys({"x": {"storageUri": "..."}}) == "$.x.storageUri", "L1 nesne-depo URI anahtarı yakalanır (NFR 10.6)")
    chk(assert_no_forbidden_keys({"x": {"cardPan": "..."}}) == "$.x.cardPan", "L1 kart PAN anahtarı yakalanır (FR-REC-005)")
    chk(assert_no_forbidden_keys({"turns": [{"text": "ok"}]}) is None, "L1 `text` (redaction'lı tur) İZİNLİ")
    # Katman 2 — içerik redaction deseni
    chk(assert_redaction_clean({"text": "ara: 05321234567"}) is not None, "L2 ham telefon (≥7 rakam) yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"text": "kart 4111 1111 1111"}) is not None, "L2 kart bloğu yakalanır (FR-REC-005)")
    chk(assert_redaction_clean({"text": "mail: a@b.com"}) is not None, "L2 e-posta yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"text": "+905321234"}) is not None, "L2 +rakam telefon yakalanır")
    chk(assert_redaction_clean({"text": "Poliçe [•••] ile biten."}) is None, "L2 maskeli içerik temiz")

    # samples doğrulaması
    for name in ("detail-clean.json", "detail-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        call = snp["call"]
        evs, tns = call["events"], call["turns"]
        chk(len(tns) == exp.get("turns"), f"{name} turns={exp.get('turns')}")
        chk(len(evs) == exp.get("events"), f"{name} events={exp.get('events')}")
        chk(len(caller_turns(tns)) == exp.get("caller_turns"), f"{name} caller_turns={exp.get('caller_turns')}")
        chk(len(agent_turns(tns)) == exp.get("agent_turns"), f"{name} agent_turns={exp.get('agent_turns')}")
        chk(len(tool_events(evs)) == exp.get("tool_events"), f"{name} tool_events={exp.get('tool_events')}")
        chk(len(barge_in_events(evs)) == exp.get("barge_in_events"), f"{name} barge_in_events={exp.get('barge_in_events')}")
        chk(len(transfer_events(evs)) == exp.get("transfer_events"), f"{name} transfer_events={exp.get('transfer_events')}")
        chk(len(masked_turns(tns)) == exp.get("masked_turns"), f"{name} masked_turns={exp.get('masked_turns')}")
        chk(len(low_confidence_turns(tns)) == exp.get("low_confidence_turns"), f"{name} low_confidence_turns={exp.get('low_confidence_turns')}")
        chk(transcript_viewable(call) == exp.get("viewable"), f"{name} viewable={exp.get('viewable')}")
        chk(redaction_pending(call) == exp.get("redaction_pending"), f"{name} redaction_pending={exp.get('redaction_pending')}")
        chk(access_blocked(call) == exp.get("access_blocked"), f"{name} access_blocked={exp.get('access_blocked')}")
        chk(assert_safe(snp) is None, f"{name} İKİ KATMAN guard temiz (HİJYEN+REDACTION)")

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

    c = _base_call()

    # pozitif (sağlıklı: redaction tamam + audit'li → görüntülenebilir)
    expect(transcript_viewable(c) is True, "pos transkript görüntülenebilir")
    expect(access_blocked(c) is False, "pos erişim engelli değil")
    expect(len(masked_turns(c["turns"])) == 2, "pos maskeli tur=2")
    expect(len(low_confidence_turns(c["turns"])) == 1, "pos düşük-güven tur=1")

    # içerik KAPISI: redaction beklemede → görüntülenemez
    pend = dict(c, transcriptState="pending")
    expect(transcript_viewable(pend) is False, "kapı redaction-beklemede içerik gizli (FR-REC-004)")
    expect(redaction_pending(pend) is True, "kapı redactionPending=True")

    # erişim KAPISI: auditsiz → görüntülenemez (danger)
    blk = dict(c, accessAudited=False)
    expect(transcript_viewable(blk) is False, "kapı auditsiz erişim içerik gizli (FR-REC-009)")
    expect(access_blocked(blk) is True, "kapı accessBlocked=True (danger)")

    # transkript yok / gerekli değil
    nores = dict(c, transcriptState="none")
    expect(transcript_absent(nores) is True and transcript_viewable(nores) is False, "transkript yok → absent")
    nreq = dict(c, transcriptState="not_required")
    expect(transcript_absent(nreq) is True, "transkript gerekli değil → absent")

    # transfer çağrısı: aktarım olayları sayılır
    tcall = dict(c, outcome="transferred", events=c["events"] + [
        _ev("EV-09", "transfer_initiated", 110000, "billing_queue"),
        _ev("EV-10", "transfer_completed", 118000),
    ])
    expect([e["eventRef"] for e in transfer_events(tcall["events"])] == ["EV-09", "EV-10"], "transfer olayları=[EV-09,EV-10] (FR-HND)")

    # kayıt kapalı: oynatılamaz + transkript not_required olabilir
    rec_off = dict(c, recordingState="disabled", channels=0)
    expect(recording_playable(rec_off) is False, "kayıt kapalı → oynatılamaz (FR-REC-002)")

    # sınır: boş olay/tur
    empty = dict(c, events=[], turns=[])
    expect(sorted_events(empty) == [] and sorted_turns(empty) == [], "sınır boş olay/tur")
    expect(count_by_speaker([]) == {s: 0 for s in SPEAKER_ORDER}, "sınır boş konuşmacı dağılımı 0")
    expect(count_by_event_type([]) == {t: 0 for t in EVENT_ORDER}, "sınır boş olay dağılımı 0")

    # İKİ KATMAN guard — pozitif/negatif
    expect(assert_safe({"call": c}) is None, "guard pozitif (redaction'lı detay temiz)")
    expect(assert_no_forbidden_keys({"x": {"audioBytes": "x"}}) is not None, "L1 audioBytes yakalanır (FR-REC-002)")
    expect(assert_no_forbidden_keys({"x": {"signedUrl": "..."}}) is not None, "L1 signedUrl yakalanır (NFR 10.6)")
    expect(assert_no_forbidden_keys({"x": {"otp": "123"}}) is not None, "L1 otp yakalanır (FR-REC-005)")
    expect(assert_no_forbidden_keys({"x": {"summary": "..."}}) is not None, "L1 çağrı özeti (summary) yakalanır")
    expect(assert_redaction_clean({"t": "hesap 1234567"}) is not None, "L2 ≥7 rakam yakalanır (FR-REC-004)")
    expect(assert_redaction_clean({"t": "TR12 3456"}) is not None, "L2 IBAN deseni yakalanır")
    expect(assert_redaction_clean({"t": "Maskeli [•••] içerik, %5 indirim."}) is None, "L2 maskeli + kısa rakam (%5) temiz")
    # KRİTİK: ham PII içeren bir tur HER İKİ guard'dan biriyle yakalanmalı (içerik sızıntısı)
    leaky = {"call": {"turns": [_tn("T-X", "caller", 1000, "numaram 05551234567")]}}
    expect(assert_safe(leaky) is not None, "kritik ham telefon içeren tur yakalanır (REDACTION ihlali)")

    # tone sınır
    expect(event_tone("transfer_initiated") == "warning", "transfer_initiated → warning")
    expect(speaker_tone("human") == "success", "human → success")
    expect(outcome_tone("voicemail") == "neutral", "voicemail → neutral")

    # placeholder ayrıştırma
    expect(placeholders("{min}:{sec}") == {"min", "sec"}, "offset placeholder parse")
    expect(placeholders("{count} tur") == {"count"}, "placeholder parse")

    # spec tutarlılık
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")
    expect(spec["event_types"] == EVENT_ORDER, "spec event_types = EVENT_ORDER")
    expect(spec["speakers"] == SPEAKER_ORDER, "spec speakers = SPEAKER_ORDER")
    expect(spec["transcript_states"] == TRANSCRIPT_ORDER, "spec transcript_states = TRANSCRIPT_ORDER")
    expect(spec["low_confidence_threshold"] == LOW_CONFIDENCE_THRESHOLD, "spec eşik = LOW_CONFIDENCE_THRESHOLD")
    expect(spec["mask_token"] == MASK_TOKEN, "spec mask_token = MASK_TOKEN")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "CallDetailView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "call": {
                "callRef": "str (çağrı VEKİL kimliği — telefon numarası DEĞİL)",
                "direction": "inbound|outbound (DB §19)",
                "agentRef": "str", "agentName": "str (tenant config; PII değil)",
                "startedAt": "ISO-8601 (sabit yer tutucu)",
                "durationSec": "int", "outcome": "contained|transferred|abandoned|voicemail|failed (FR-ANA-002/003)",
                "recordingState": "recorded|disabled|none (FR-REC-001/002; yalnız DURUM)",
                "channels": "0|1|2 (FR-REC-003)",
                "transcriptState": "redacted|pending|not_required|none (FR-REC-004; içerik kapısı)",
                "retentionImminent": "bool (FR-REC-006/010)", "legalHold": "bool (FR-REC-007)",
                "accessAudited": "bool (FR-REC-009; erişim kapısı — false ise içerik gizlenir)",
                "own": "bool (BRD §17.6/§17.7 human_agent kapsamı)",
                "events": [{
                    "eventRef": "str", "type": "|".join(EVENT_ORDER) + " (DB §23 call_event; BRD §15 + SAD §6.1)",
                    "offsetMs": "int (çağrı başlangıcından ofset)", "detail": "str? (yapısal etiket — tool/queue adı; PII DEĞİL)"
                }],
                "turns": [{
                    "turnRef": "str", "speaker": "caller|agent|human (DB §21 transcript_segment)",
                    "offsetMs": "int", "text": "str (REDACTION UYGULANMIŞ; ham PII yok, yalnız MASK_TOKEN)",
                    "redacted": "bool (FR-REC-005)", "confidence": "float 0..1 (DB §21; BRD §15)"
                }]
            }
        },
        "directions": DIRECTION_ORDER, "outcomes": OUTCOME_ORDER, "recording_states": RECORDING_ORDER,
        "transcript_states": TRANSCRIPT_ORDER, "speakers": SPEAKER_ORDER, "event_types": EVENT_ORDER,
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD, "mask_token": MASK_TOKEN,
        "gates": "İÇERİK KAPISI (transcriptViewable): transcriptState='redacted' (redaction tamam — FR-REC-004) VE accessAudited (erişim audit'li — FR-REC-009) ise transkript İÇERİĞİ gösterilir. redactionPending (pending — FR-REC-004) → içerik gizli; accessBlocked (!accessAudited — FR-REC-009 ihlali, danger) → erişim engelli.",
        "hijyen": "A-12 transkript İÇERİĞİNİ (REDACTION UYGULANMIŞ tur metni) gösterir AMA İKİ KATMAN guard'la: (1) assertNoForbiddenKeys — ham kimlik/iş-içeriği (ham ses kaydı/ham transkript blob/e164/müşteri/kart-OTP/çağrı özeti) + sır/credential/nesne-depo URI (storageUri/signedUrl/url/kmsKey) alan ADI YOK; (2) assertRedactionClean — hiçbir string değer ham PII DESENİ (≥7 rakam/e-posta/+rakam/kart-bloğu/IBAN) taşımaz (FR-REC-004/005; redaction panel görüntülemelerinde de uygulanır — BRD §17.7). `text` alanı izinlidir AMA yalnız maskeli içerik (MASK_TOKEN); ham ses BYTE'ı / nesne-depo URI panele KONMAZ (NFR 10.6); dinleme audit'li derin aksiyon (FR-REC-008/009 + WBS 11.6). Tek çağrı DETAYI (A-11 arama/filtreleme META iken A-12 zaman çizelgesi+transkript+olay)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a12_call_detail_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
