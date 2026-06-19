#!/usr/bin/env python3
# WBS 13.4.13 — A-13 "QA Değerlendirme" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (skorkart/ağırlıklı skor/işaret/kalibrasyon/tone'lar/assertSafe) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (otomatik skor tutarlılık / kritik işaret / kalibrasyon / İKİ KATMAN guard)
#   schema    — QA değerlendirme görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/qa-eval.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a13-qa-eval-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "qa", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "qa-eval.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

DIRECTION_ORDER = ["inbound", "outbound"]
OUTCOME_ORDER = ["contained", "transferred", "abandoned", "voicemail", "failed"]
DIMENSION_ORDER = ["compliance", "accuracy", "resolution", "tooling", "communication", "safety"]
FLAG_ORDER = ["misinformation", "tool_error", "security_violation", "pii_exposure", "escalation_missed", "compliance_gap", "low_confidence"]
SEVERITY_ORDER = ["critical", "high", "medium", "info"]
REVIEW_ORDER = ["pending", "in_review", "scored"]
DISPOSITION_ORDER = ["approved", "coaching", "failed", "escalated"]
BAND_ORDER = ["pass", "borderline", "fail"]
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "info": 3}

DIMENSION_FLAG_THRESHOLD = 0.7
DEFAULT_THRESHOLDS = {"pass": 0.85, "fail": 0.6}
CALIBRATION_TOLERANCE = 0.1
AUTO_SCORE_TOLERANCE = 0.02
MASK_TOKEN = "[•••]"

FORBIDDEN_PII_KEYS = ["text", "transcripttext", "rawtext", "transcript", "utterance", "recording", "recordingbytes",
                      "audio", "audiobytes", "summary", "e164", "frome164", "toe164", "fromnumber", "tonumber",
                      "msisdn", "phonenumber", "callerid", "callernumber", "calleenumber", "customer", "customername",
                      "reviewername", "contact", "contactname", "email", "dob", "birthdate", "cardpan", "pan", "cvv",
                      "otp", "ssn", "iban", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token", "bearertoken", "accesstoken",
                         "credential", "password", "privatekey", "kmskey", "storageuri", "storageurl", "objecturi",
                         "objectkey", "signedurl", "downloadurl", "url", "baseurl", "uri", "bucket"]
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


# ── SAF çekirdek aynası (lib/tenant/qa-eval.ts ile birebir) ────────────────────────

def sorted_dimensions(ev):
    return sorted(ev["dimensions"], key=lambda d: DIMENSION_ORDER.index(d["key"]))


def sorted_flags(ev):
    return sorted(ev["flags"], key=lambda f: (SEVERITY_RANK[f["severity"]], f["flagRef"]))


def weighted_auto_score(dimensions):
    wsum = sum(d["weight"] for d in dimensions)
    if wsum <= 0:
        return 0.0
    return sum(d["score"] * d["weight"] for d in dimensions) / wsum


def weight_sum(dimensions):
    return sum(d["weight"] for d in dimensions)


def auto_score_consistent(ev, tol=AUTO_SCORE_TOLERANCE):
    return abs(ev["autoScore"] - weighted_auto_score(ev["dimensions"])) <= tol


def score_band(score, thresholds):
    if score >= thresholds["pass"]:
        return "pass"
    if score >= thresholds["fail"]:
        return "borderline"
    return "fail"


def flagged_dimensions(dimensions, threshold=DIMENSION_FLAG_THRESHOLD):
    return [d for d in dimensions if d["score"] < threshold]


def critical_flags(flags):
    return [f for f in flags if f["severity"] == "critical"]


def open_flags(flags):
    return [f for f in flags if not f["resolved"]]


def open_critical_flags(flags):
    return [f for f in flags if f["severity"] == "critical" and not f["resolved"]]


def auto_flags(flags):
    return [f for f in flags if f["auto"]]


def count_by_flag_type(flags):
    acc = {t: 0 for t in FLAG_ORDER}
    for f in flags:
        acc[f["type"]] += 1
    return acc


def count_by_severity(flags):
    acc = {s: 0 for s in SEVERITY_ORDER}
    for f in flags:
        acc[f["severity"]] += 1
    return acc


def critical_consistent(ev):
    return ev["critical"] == (len(critical_flags(ev["flags"])) > 0)


def needs_review(ev, thresholds=DEFAULT_THRESHOLDS):
    return ev["critical"] or len(open_critical_flags(ev["flags"])) > 0 or score_band(ev["autoScore"], thresholds) == "fail"


def review_complete(ev):
    return ev["review"]["status"] == "scored" and isinstance(ev["review"].get("score"), (int, float))


def review_pending(ev):
    return ev["review"]["status"] in ("pending", "in_review")


def calibration_delta(ev):
    if not review_complete(ev) or not isinstance(ev["review"].get("score"), (int, float)):
        return None
    return abs(ev["autoScore"] - ev["review"]["score"])


def calibration_agreement(ev, tol=CALIBRATION_TOLERANCE):
    d = calibration_delta(ev)
    return None if d is None else d <= tol


def access_blocked(ev):
    return not ev["accessAudited"]


def version_delta(b):
    return b["versionAvgScore"] - b["agentAvgScore"]


def direction_tone(d):
    return {"inbound": "neutral", "outbound": "info"}[d]


def outcome_tone(o):
    return {"contained": "success", "transferred": "info", "abandoned": "warning",
            "voicemail": "neutral", "failed": "danger"}[o]


def band_tone(b):
    return {"pass": "success", "borderline": "warning", "fail": "danger"}[b]


def score_tone(score, thresholds=DEFAULT_THRESHOLDS):
    return band_tone(score_band(score, thresholds))


def severity_tone(s):
    return {"critical": "danger", "high": "warning", "medium": "warning", "info": "info"}[s]


def review_tone(s):
    return {"pending": "warning", "in_review": "info", "scored": "success"}[s]


def disposition_tone(d):
    return {"approved": "success", "coaching": "warning", "failed": "danger", "escalated": "warning"}[d]


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
    """qa-eval.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.13", "S0 spec.wbs=13.4.13")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/qa/page.tsx mevcut")
    chk('data-screen="A-13"' in page, 'S1 data-screen="A-13" işaretli')
    chk("İskelet ekran — A-13" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/qa-eval" in page, "S2 veri seam (lib/tenant/qa-eval) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "EmptyState"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür ETİKET metni i18n'den (screen.a13.*); hardcoded TR/EN ETİKET cümlesi yok
    chk("screen.a13." in page, "S3 screen.a13.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded etiket metni yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı İKİ KATMAN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/qa-eval.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("RAW_PII_PATTERNS" in data, "S4 RAW_PII_PATTERNS (içerik redaction deseni) tanımlı")
    chk("assertNoForbiddenKeys" in data, "S4 assertNoForbiddenKeys (yapısal) guard tanımlı")
    chk("assertRedactionClean" in data, "S4 assertRedactionClean (içerik) guard tanımlı")
    chk(re.search(r"assertSafe\(view\)", data) is not None, "S4 getQaEvaluationView assertSafe çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("text", "transcripttext", "recording", "e164", "cardpan")), "S4 transkript metni/ham ses/numara/kart yasak (A-13 içerik göstermez; BRD §17.7)")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("storageuri", "url", "kmskey", "signedurl")), "S4 nesne-depo URI/sır yasak (NFR 10.6)")
    leak = assert_no_forbidden_keys({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/URI alanı yok (sızıntı={leak})")
    # comment/note (QA açıklaması) alan adları İZİNLİ; ama redaction'lı tutulur (Katman 2)
    chk("comment" not in [x.lower() for x in FORBIDDEN_PII_KEYS] and "note" not in [x.lower() for x in FORBIDDEN_PII_KEYS], "S4 `comment`/`note` (redaction'lı QA açıklaması) izinli")

    # S5 — BRD §17.5 içerik öğeleri + FR-ANA-001/004/008/009/010 + FR-REC-009 karşılanır
    a13 = tr.get("screen", {}).get("a13", {})
    sec = a13.get("section", {})
    for s in ("summary", "scorecard", "flags", "review", "benchmark"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("weightedAutoScore" in data and "autoScoreConsistent" in data and set(DIMENSION_ORDER).issubset(a13.get("dimension", {}).keys()), "S5 otomatik skorkart (FR-ANA-001)")
    chk("countByFlagType" in data and set(FLAG_ORDER).issubset(a13.get("flag", {}).keys()), "S5 kritik işaret tipleri (FR-ANA-004)")
    chk("criticalFlags" in data and "criticalConsistent" in data and "needsReview" in data and "critical" in a13.get("alert", {}), "S5 kritik konuşma otomatik işaretleme (FR-ANA-008)")
    chk("reviewComplete" in data and "calibrationDelta" in data and "calibrationAgreement" in data and "review" in a13, "S5 manuel değerlendirme + kalibrasyon (FR-ANA-009)")
    chk("versionDelta" in data and "benchmark" in a13, "S5 sürüm karşılaştırması (FR-ANA-010)")
    chk("accessBlocked" in data and "access_blocked" in a13.get("alert", {}), "S5 erişim sağlığı (FR-REC-009)")
    chk(set(OUTCOME_ORDER).issubset(a13.get("outcome", {}).keys()), "S5 sonuç/outcome (FR-ANA-002/003)")
    chk(set(BAND_ORDER).issubset(a13.get("band", {}).keys()) and set(SEVERITY_ORDER).issubset(a13.get("severity", {}).keys()), "S5 band + şiddet etiketleri")
    chk(set(REVIEW_ORDER).issubset(a13.get("review_status", {}).keys()) and set(DISPOSITION_ORDER).issubset(a13.get("disposition", {}).keys()), "S5 inceleme durumu + disposition etiketleri")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a13.{rk}"
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
        vt = resolve(tr, f"screen.a13.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedDimensions", "sortedFlags", "weightedAutoScore", "weightSum", "autoScoreConsistent", "scoreBand",
               "flaggedDimensions", "criticalFlags", "openFlags", "openCriticalFlags", "autoFlags", "countByFlagType",
               "countBySeverity", "criticalConsistent", "needsReview", "reviewComplete", "reviewPending",
               "calibrationDelta", "calibrationAgreement", "accessBlocked", "versionDelta", "directionTone",
               "outcomeTone", "bandTone", "scoreTone", "severityTone", "reviewTone", "dispositionTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("DIRECTION_ORDER", "OUTCOME_ORDER", "DIMENSION_ORDER", "FLAG_ORDER", "SEVERITY_ORDER", "REVIEW_ORDER", "DISPOSITION_ORDER", "BAND_ORDER")), "S7 *_ORDER sabitleri tanımlı")
    chk(all(c in data for c in ("DEFAULT_THRESHOLDS", "DIMENSION_FLAG_THRESHOLD", "CALIBRATION_TOLERANCE", "AUTO_SCORE_TOLERANCE", "MASK_TOKEN")), "S7 eşik sabitleri tanımlı")
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

def _dim(key, score, weight):
    return {"key": key, "score": score, "weight": weight}


def _flag(ref, typ, sev, auto=True, turn=None, resolved=False, note=None):
    f = {"flagRef": ref, "type": typ, "severity": sev, "auto": auto, "resolved": resolved}
    if turn is not None:
        f["turnRef"] = turn
    if note is not None:
        f["note"] = note
    return f


def _base_eval():
    return {
        "callRef": "CALL-1006", "direction": "inbound", "agentRef": "AGT-117", "agentName": "Sigorta Asistanı",
        "agentVersion": "v7", "outcome": "contained", "startedAt": "2026-06-18T08:55:00.000Z", "durationSec": 214,
        "autoScore": 0.92,
        "dimensions": [
            _dim("compliance", 0.95, 0.2), _dim("accuracy", 0.92, 0.2), _dim("resolution", 0.90, 0.2),
            _dim("tooling", 0.88, 0.15), _dim("communication", 0.90, 0.1), _dim("safety", 0.94, 0.15),
        ],
        "flags": [_flag("FL-01", "low_confidence", "info", True, "T-04", False, "kimlik turunda STT güveni eşik altı")],
        "critical": False,
        "review": {"status": "scored", "score": 0.88, "reviewerRef": "USR-QA-009", "disposition": "approved",
                   "comment": "Karşılama eksiksiz; kart bilgisi istenmedi.", "scoredAt": "2026-06-18T10:15:00.000Z"},
        "accessAudited": True,
    }


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    ev = _base_eval()
    thr = DEFAULT_THRESHOLDS

    chk([d["key"] for d in sorted_dimensions(ev)] == DIMENSION_ORDER, "sortedDimensions DIMENSION_ORDER")
    chk(abs(weight_sum(ev["dimensions"]) - 1.0) < 1e-9, "weightSum ≈ 1.0")
    chk(abs(weighted_auto_score(ev["dimensions"]) - 0.917) < 0.01, "weightedAutoScore ≈ 0.917 (FR-ANA-001)")
    chk(auto_score_consistent(ev) is True, "autoScoreConsistent (saklanan ≈ türetilen)")
    chk(score_band(ev["autoScore"], thr) == "pass", "scoreBand(0.92)=pass")
    chk(score_band(0.7, thr) == "borderline" and score_band(0.5, thr) == "fail", "scoreBand sınırda/kalır")
    chk(flagged_dimensions(ev["dimensions"]) == [], "flaggedDimensions=[] (hepsi ≥0.7)")
    chk(critical_flags(ev["flags"]) == [], "criticalFlags=[] (yalnız info)")
    chk([f["flagRef"] for f in open_flags(ev["flags"])] == ["FL-01"], "openFlags=[FL-01]")
    chk([f["flagRef"] for f in auto_flags(ev["flags"])] == ["FL-01"], "autoFlags=[FL-01] (FR-ANA-008)")
    chk(count_by_flag_type(ev["flags"])["low_confidence"] == 1, "countByFlagType low_confidence=1")
    chk(count_by_severity(ev["flags"])["info"] == 1 and count_by_severity(ev["flags"])["critical"] == 0, "countBySeverity info=1")
    chk(critical_consistent(ev) is True, "criticalConsistent (False ↔ kritik işaret yok)")
    chk(needs_review(ev, thr) is False, "needsReview=False (kritik yok + pass)")
    chk(review_complete(ev) is True, "reviewComplete=True (scored + skor)")
    chk(review_pending(ev) is False, "reviewPending=False")
    chk(abs(calibration_delta(ev) - 0.04) < 1e-9, "calibrationDelta=0.04 (|0.92-0.88|)")
    chk(calibration_agreement(ev) is True, "calibrationAgreement=True (≤0.1; FR-ANA-009)")
    chk(access_blocked(ev) is False, "accessBlocked=False (audit'li)")

    # sürüm karşılaştırması (FR-ANA-010)
    b = {"agentAvgScore": 0.87, "versionAvgScore": 0.90, "sampleSize": 1240}
    chk(abs(version_delta(b) - 0.03) < 1e-9, "versionDelta=+0.03 (iyileşme; FR-ANA-010)")

    # tone eşlemeleri
    chk(score_tone(0.92, thr) == "success" and score_tone(0.5, thr) == "danger", "scoreTone success/danger")
    chk(severity_tone("critical") == "danger" and severity_tone("info") == "info", "severityTone")
    chk(review_tone("scored") == "success" and review_tone("pending") == "warning", "reviewTone")
    chk(disposition_tone("failed") == "danger" and disposition_tone("approved") == "success", "dispositionTone")
    chk(band_tone("fail") == "danger" and outcome_tone("contained") == "success", "band/outcome tone")

    # İKİ KATMAN guard — pozitif
    chk(assert_safe({"evaluation": ev}) is None, "assertSafe değerlendirme İZİNLİ (redaction'lı)")
    # Katman 1 — yapısal anahtar
    chk(assert_no_forbidden_keys({"x": {"text": "..."}}) == "$.x.text", "L1 transkript metni anahtarı yakalanır (A-13 göstermez)")
    chk(assert_no_forbidden_keys({"x": {"recording": "..."}}) == "$.x.recording", "L1 ham ses kaydı anahtarı yakalanır")
    chk(assert_no_forbidden_keys({"x": {"reviewerName": "..."}}) == "$.x.reviewerName", "L1 değerlendiren ADI yakalanır (yalnız reviewerRef izinli)")
    chk(assert_no_forbidden_keys({"x": {"storageUri": "..."}}) == "$.x.storageUri", "L1 nesne-depo URI yakalanır (NFR 10.6)")
    chk(assert_no_forbidden_keys({"review": {"comment": "ok"}}) is None, "L1 `comment` (QA açıklaması) İZİNLİ")
    # Katman 2 — içerik redaction deseni
    chk(assert_redaction_clean({"comment": "müşteri no 05321234567"}) is not None, "L2 ham telefon yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"comment": "kart 4111 1111 1111"}) is not None, "L2 kart bloğu yakalanır (FR-REC-005)")
    chk(assert_redaction_clean({"note": "mail a@b.com"}) is not None, "L2 e-posta yakalanır")
    chk(assert_redaction_clean({"comment": "Skor %88; düşük güven [•••] teyit edildi."}) is None, "L2 maskeli/yüzde içerik temiz")

    # samples doğrulaması
    for name in ("eval-clean.json", "eval-flagged.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        e = snp["evaluation"]
        chk(len(e["dimensions"]) == exp.get("dimensions"), f"{name} dimensions={exp.get('dimensions')}")
        chk(len(e["flags"]) == exp.get("flags"), f"{name} flags={exp.get('flags')}")
        chk(len(critical_flags(e["flags"])) == exp.get("critical_flags"), f"{name} critical_flags={exp.get('critical_flags')}")
        chk(len(open_flags(e["flags"])) == exp.get("open_flags"), f"{name} open_flags={exp.get('open_flags')}")
        chk(len(flagged_dimensions(e["dimensions"])) == exp.get("weak_dimensions"), f"{name} weak_dimensions={exp.get('weak_dimensions')}")
        chk(score_band(e["autoScore"], snp.get("thresholds", DEFAULT_THRESHOLDS)) == exp.get("band"), f"{name} band={exp.get('band')}")
        chk(auto_score_consistent(e) is True, f"{name} autoScoreConsistent (FR-ANA-001)")
        chk(critical_consistent(e) is True, f"{name} criticalConsistent (FR-ANA-008)")
        chk(needs_review(e, snp.get("thresholds", DEFAULT_THRESHOLDS)) == exp.get("needs_review"), f"{name} needs_review={exp.get('needs_review')}")
        chk(review_complete(e) == exp.get("review_complete"), f"{name} review_complete={exp.get('review_complete')}")
        chk(access_blocked(e) == exp.get("access_blocked"), f"{name} access_blocked={exp.get('access_blocked')}")
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

    ev = _base_eval()
    thr = DEFAULT_THRESHOLDS

    # pozitif (sağlıklı: yüksek otomatik skor + tutarlı + kalibre + audit'li)
    expect(auto_score_consistent(ev) is True, "pos autoScore tutarlı (FR-ANA-001)")
    expect(score_band(ev["autoScore"], thr) == "pass", "pos band=pass")
    expect(needs_review(ev, thr) is False, "pos manuel inceleme zorunlu değil")
    expect(calibration_agreement(ev) is True, "pos kalibrasyon uyumlu (FR-ANA-009)")
    expect(access_blocked(ev) is False, "pos erişim engelli değil")

    # FR-ANA-008: kritik işaret → kritik bayrak + manuel inceleme zorunlu
    crit_ev = dict(ev, critical=True, flags=ev["flags"] + [_flag("FL-99", "security_violation", "critical", True, "T-07")])
    expect(len(critical_flags(crit_ev["flags"])) == 1, "kritik işaret=1 (security_violation)")
    expect(critical_consistent(crit_ev) is True, "criticalConsistent (True ↔ kritik işaret var)")
    expect(needs_review(crit_ev, thr) is True, "kritik → manuel inceleme ZORUNLU (FR-ANA-008)")

    # tutarsızlık yakalama: critical=False ama kritik işaret VAR → criticalConsistent False
    inconsistent = dict(ev, critical=False, flags=[_flag("FL-X", "misinformation", "critical")])
    expect(critical_consistent(inconsistent) is False, "tutarsız kritik bayrağı yakalanır (FR-ANA-008)")

    # düşük otomatik skor → fail band → manuel inceleme zorunlu (kritik işaret olmasa bile)
    low = dict(ev, autoScore=0.5,
               dimensions=[_dim("compliance", 0.5, 0.2), _dim("accuracy", 0.5, 0.2), _dim("resolution", 0.5, 0.2),
                           _dim("tooling", 0.5, 0.15), _dim("communication", 0.5, 0.1), _dim("safety", 0.5, 0.15)])
    expect(score_band(low["autoScore"], thr) == "fail", "düşük skor → fail band")
    expect(auto_score_consistent(low) is True, "düşük skor tutarlı (0.5)")
    expect(needs_review(low, thr) is True, "düşük skor → manuel inceleme zorunlu (FR-ANA-008)")
    expect(len(flagged_dimensions(low["dimensions"])) == 6, "tüm boyutlar zayıf (6)")

    # FR-ANA-009 kalibrasyon sapması: manuel ile otomatik fark > tolerans
    diverge = dict(ev, review=dict(ev["review"], score=0.6))
    expect(abs(calibration_delta(diverge) - 0.32) < 1e-9, "kalibrasyon farkı=0.32")
    expect(calibration_agreement(diverge) is False, "kalibrasyon sapması yakalanır (FR-ANA-009)")

    # inceleme beklemede: skor yok → kalibrasyon N/A
    pend = dict(ev, review={"status": "pending"})
    expect(review_pending(pend) is True and review_complete(pend) is False, "inceleme beklemede")
    expect(calibration_delta(pend) is None and calibration_agreement(pend) is None, "skorsuz → kalibrasyon N/A")

    # erişim engeli (FR-REC-009)
    blocked = dict(ev, accessAudited=False)
    expect(access_blocked(blocked) is True, "auditsiz erişim → danger (FR-REC-009)")

    # sıralama: kritik işaret üstte
    multi = dict(ev, flags=[_flag("FL-3", "low_confidence", "info"), _flag("FL-1", "misinformation", "critical"), _flag("FL-2", "tool_error", "high")])
    expect([f["flagRef"] for f in sorted_flags(multi)] == ["FL-1", "FL-2", "FL-3"], "sortedFlags şiddet sırası (kritik üstte)")

    # sınır: boş işaret/boyut
    empty = dict(ev, flags=[], dimensions=[])
    expect(count_by_flag_type([]) == {t: 0 for t in FLAG_ORDER}, "sınır boş işaret dağılımı 0")
    expect(count_by_severity([]) == {s: 0 for s in SEVERITY_ORDER}, "sınır boş şiddet dağılımı 0")
    expect(weighted_auto_score([]) == 0.0, "sınır boş boyut → 0 (sıfır bölme yok)")

    # İKİ KATMAN guard — negatif
    expect(assert_no_forbidden_keys({"x": {"transcriptText": "x"}}) is not None, "L1 ham transkript blob yakalanır")
    expect(assert_no_forbidden_keys({"x": {"audioBytes": "x"}}) is not None, "L1 audioBytes yakalanır")
    expect(assert_no_forbidden_keys({"x": {"signedUrl": "..."}}) is not None, "L1 signedUrl yakalanır (NFR 10.6)")
    expect(assert_no_forbidden_keys({"x": {"customerName": "..."}}) is not None, "L1 müşteri adı yakalanır")
    expect(assert_redaction_clean({"c": "TR12 3456"}) is not None, "L2 IBAN deseni yakalanır")
    expect(assert_redaction_clean({"c": "Maskeli [•••], %5 puan."}) is None, "L2 maskeli + kısa rakam (%5) temiz")
    # KRİTİK: ham PII içeren bir QA açıklaması yakalanmalı (içerik sızıntısı)
    leaky = {"evaluation": {"review": {"comment": "geri ara 05551234567"}}}
    expect(assert_safe(leaky) is not None, "kritik ham telefon içeren açıklama yakalanır (REDACTION ihlali)")

    # placeholder ayrıştırma
    expect(placeholders("Geçer ≥{pass} · Sınırda ≥{fail}") == {"pass", "fail"}, "placeholder parse")
    expect(placeholders("{count} kritik işaret") == {"count"}, "placeholder parse")

    # spec tutarlılık
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 100, "spec ≥100 referans anahtar")
    expect(spec["dimensions"] == DIMENSION_ORDER, "spec dimensions = DIMENSION_ORDER")
    expect(spec["flag_types"] == FLAG_ORDER, "spec flag_types = FLAG_ORDER")
    expect(spec["severities"] == SEVERITY_ORDER, "spec severities = SEVERITY_ORDER")
    expect(spec["bands"] == BAND_ORDER, "spec bands = BAND_ORDER")
    expect(spec["default_thresholds"] == DEFAULT_THRESHOLDS, "spec default_thresholds = DEFAULT_THRESHOLDS")
    expect(spec["calibration_tolerance"] == CALIBRATION_TOLERANCE, "spec calibration_tolerance")
    expect(spec["mask_token"] == MASK_TOKEN, "spec mask_token = MASK_TOKEN")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "QaEvaluationView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "thresholds": {"pass": "float", "fail": "float"},
            "evaluation": {
                "callRef": "str (çağrı VEKİL kimliği — telefon numarası DEĞİL)",
                "direction": "inbound|outbound (DB §19)",
                "agentRef": "str", "agentName": "str (tenant config; PII değil)", "agentVersion": "str (FR-ANA-010)",
                "outcome": "|".join(OUTCOME_ORDER) + " (FR-ANA-002/003)",
                "startedAt": "ISO-8601 (sabit yer tutucu)", "durationSec": "int",
                "autoScore": "float 0..1 (FR-ANA-001; ≈ ağırlıklı boyut skoru)",
                "dimensions": [{"key": "|".join(DIMENSION_ORDER), "score": "float 0..1", "weight": "float 0..1 (toplam ≈1)"}],
                "flags": [{
                    "flagRef": "str", "type": "|".join(FLAG_ORDER) + " (FR-ANA-004)",
                    "severity": "|".join(SEVERITY_ORDER), "auto": "bool (FR-ANA-008 otomatik tespit)",
                    "turnRef": "str? (yapısal kanıt VEKİLİ — ham metin DEĞİL)", "resolved": "bool",
                    "note": "str? (REDACTION'LI yapısal not)"
                }],
                "critical": "bool (FR-ANA-008; ≈ kritik-şiddetli işaret varlığı)",
                "review": {
                    "status": "|".join(REVIEW_ORDER) + " (FR-ANA-009)", "score": "float? 0..1",
                    "reviewerRef": "str? (vekil — ad/PII DEĞİL)", "disposition": "|".join(DISPOSITION_ORDER) + "?",
                    "comment": "str? (REDACTION'LI QA açıklaması; ham PII yok)", "scoredAt": "ISO-8601?"
                },
                "accessAudited": "bool (FR-REC-009; false ise erişim engelli/danger)"
            },
            "benchmark": {"agentAvgScore": "float", "versionAvgScore": "float", "sampleSize": "int (FR-ANA-010)"}
        },
        "dimensions": DIMENSION_ORDER, "flag_types": FLAG_ORDER, "severities": SEVERITY_ORDER,
        "review_statuses": REVIEW_ORDER, "dispositions": DISPOSITION_ORDER, "bands": BAND_ORDER,
        "default_thresholds": DEFAULT_THRESHOLDS, "calibration_tolerance": CALIBRATION_TOLERANCE,
        "auto_score_tolerance": AUTO_SCORE_TOLERANCE, "mask_token": MASK_TOKEN,
        "invariants": "autoScoreConsistent: saklanan autoScore ≈ ağırlıklı boyut skoru (FR-ANA-001). criticalConsistent: critical bayrağı ≈ kritik-şiddetli işaret varlığı (FR-ANA-008). needsReview: kritik VEYA açık kritik işaret VEYA fail band → manuel inceleme zorunlu. calibrationAgreement: |autoScore − manualScore| ≤ tolerans (FR-ANA-009).",
        "hijyen": "A-13 SKOR/İŞARET/AÇIKLAMA gösterir (Tier A); transkript İÇERİĞİNİ taşımaz (içerik A-12'de). İKİ KATMAN guard: (1) assertNoForbiddenKeys — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni `text`/e164/müşteri/kart-OTP/değerlendiren-adı) + sır/credential/nesne-depo URI alan ADI YOK; A-12'den farkı: `text` BURADA YASAK. (2) assertRedactionClean — hiçbir string değer (özellikle QA `comment`/`note`) ham PII DESENİ taşımaz (FR-REC-004/005). Kanıt yapısaldır (turnRef vekili — ham metin DEĞİL). Skorlama derin aksiyon (qa:score — API §8.1); nihai yetki + işlem + audit backend (FR-REC-009 + SAD §14.4.1)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a13_qa_eval_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
