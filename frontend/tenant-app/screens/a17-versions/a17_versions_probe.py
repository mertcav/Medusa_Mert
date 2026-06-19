#!/usr/bin/env python3
# WBS 13.4.17 — A-17 "Sürüm Geçmişi (agent) + rollback" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (sürüm/aşama/rollback/bütünlük/tone'lar/assertSafe) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (rollback / bütünlük / WORM köken / İKİ KATMAN guard)
#   schema    — sürüm görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/agent-versions.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a17-versions-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "versions", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "agent-versions.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

STAGE_ORDER = ["draft", "test", "staging", "production", "archived"]
TEST_ORDER = ["passed", "failed", "not_run"]
STATUS_ORDER = ["active", "published", "draft"]
MASK_TOKEN = "[•••]"

FORBIDDEN_PII_KEYS = ["transcript", "transcripttext", "rawtext", "utterance", "recording", "recordingurl",
                      "recordingbytes", "audio", "audiobytes", "summary", "e164", "frome164", "toe164", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer", "customername",
                      "contact", "contactname", "email", "dob", "birthdate", "cdr", "cardpan", "pan", "cvv",
                      "otp", "ssn", "iban", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "token", "bearertoken",
                         "accesstoken", "refreshtoken", "credential", "password", "privatekey", "kmskey", "snapshot",
                         "prompttext", "promptbody", "flowdefinition", "flowbody", "body", "storageuri", "storageurl",
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


# ── SAF çekirdek aynası (lib/tenant/agent-versions.ts ile birebir) ─────────────────

def sorted_versions(h):
    return sorted(h["versions"], key=lambda v: -v["versionNo"])


def version_by_no(h, no):
    for v in h["versions"]:
        if v["versionNo"] == no:
            return v
    return None


def active_version(h):
    if h["activeVersionNo"] is None:
        return None
    return version_by_no(h, h["activeVersionNo"])


def latest_version(h):
    if not h["versions"]:
        return None
    best = h["versions"][0]
    for v in h["versions"]:
        if v["versionNo"] > best["versionNo"]:
            best = v
    return best


def count_by_stage(h):
    acc = {s: 0 for s in STAGE_ORDER}
    for v in h["versions"]:
        acc[v["stage"]] += 1
    return acc


def published_versions(h):
    return [v for v in h["versions"] if v["isPublished"]]


def draft_versions(h):
    return [v for v in h["versions"] if not v["isPublished"]]


def is_active(h, v):
    return h["activeVersionNo"] is not None and v["versionNo"] == h["activeVersionNo"]


def version_status(h, v):
    if is_active(h, v):
        return "active"
    if v["isPublished"]:
        return "published"
    return "draft"


def is_rollback(v):
    return v["rollbackOfNo"] is not None


def rollback_count(h):
    return sum(1 for v in h["versions"] if is_rollback(v))


def recallable_versions(h):
    return [v for v in h["versions"] if v["isPublished"] and not is_active(h, v)]


def previous_published_version(h):
    recallable = recallable_versions(h)
    if not recallable:
        return None
    active = h["activeVersionNo"]
    below = [] if active is None else [v for v in recallable if v["versionNo"] < active]
    pool = below if below else recallable
    best = pool[0]
    for v in pool:
        if v["versionNo"] > best["versionNo"]:
            best = v
    return best


def can_rollback(h):
    return h["activeVersionNo"] is not None and len(recallable_versions(h)) > 0


def has_pending_changes(h):
    latest = latest_version(h)
    if latest is None:
        return False
    if h["activeVersionNo"] is None:
        return True
    return latest["versionNo"] > h["activeVersionNo"]


def failed_test_versions(h):
    return [v for v in h["versions"] if v["stage"] != "archived" and v["testStatus"] == "failed"]


def duplicate_version_nos(h):
    seen, dup = set(), set()
    for v in h["versions"]:
        if v["versionNo"] in seen:
            dup.add(v["versionNo"])
        seen.add(v["versionNo"])
    return sorted(dup)


def duplicate_version_ids(h):
    seen, dup = set(), set()
    for v in h["versions"]:
        if v["versionId"] in seen:
            dup.add(v["versionId"])
        seen.add(v["versionId"])
    return sorted(dup)


def distinguishable(h):
    return len(duplicate_version_nos(h)) == 0 and len(duplicate_version_ids(h)) == 0


def missing_active_version(h):
    return h["activeVersionNo"] is not None and version_by_no(h, h["activeVersionNo"]) is None


def rollback_refs_resolve(h):
    for v in h["versions"]:
        if v["rollbackOfNo"] is None:
            continue
        if v["rollbackOfNo"] >= v["versionNo"]:
            return False
        if version_by_no(h, v["rollbackOfNo"]) is None:
            return False
    return True


def open_attention_count(h):
    return (len(duplicate_version_nos(h)) + len(duplicate_version_ids(h))
            + (1 if missing_active_version(h) else 0)
            + (0 if rollback_refs_resolve(h) else 1)
            + len(failed_test_versions(h)))


def stage_tone(s):
    return {"draft": "neutral", "test": "info", "staging": "warning", "production": "success", "archived": "neutral"}[s]


def status_tone(s):
    return {"active": "success", "published": "info", "draft": "warning"}[s]


def test_tone(t):
    return {"passed": "success", "failed": "danger", "not_run": "warning"}[t]


def assert_no_forbidden_keys(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/snapshot-gövdesi/URI alan adı bulursa (path) döndürür; yoksa None."""
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
    """agent-versions.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.17", "S0 spec.wbs=13.4.17")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/versions/page.tsx mevcut")
    chk('data-screen="A-17"' in page, 'S1 data-screen="A-17" işaretli')
    chk("İskelet ekran — A-17" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/agent-versions" in page, "S2 veri seam (lib/tenant/agent-versions) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    chk("formatNumber" in page and "formatDate" in page, "S2 formatNumber/formatDate (sayı/tarih locale-duyarlı)")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "EmptyState", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür ETİKET metni i18n'den (screen.a17.*); hardcoded TR/EN ETİKET cümlesi yok
    chk("screen.a17." in page, "S3 screen.a17.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded etiket metni yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı İKİ KATMAN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/agent-versions.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("RAW_PII_PATTERNS" in data, "S4 RAW_PII_PATTERNS (içerik redaction deseni) tanımlı")
    chk("assertNoForbiddenKeys" in data, "S4 assertNoForbiddenKeys (yapısal) guard tanımlı")
    chk("assertRedactionClean" in data, "S4 assertRedactionClean (içerik) guard tanımlı")
    chk(re.search(r"assertSafe\(view\)", data) is not None, "S4 getAgentVersionView assertSafe çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("snapshot", "prompttext", "flowdefinition", "body")), "S4 agent_version snapshot/prompt/flow GÖVDESİ yasak (yalnız sürüm META; DB §5.2 / NFR 10.6)")
    chk(all(s in [x.lower() for x in FORBIDDEN_PII_KEYS] for s in ("transcript", "recording", "msisdn", "customername", "cardpan")), "S4 transkript/ses kaydı/ham numara/müşteri/kart yasak (BRD §17.7)")
    leak = assert_no_forbidden_keys({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/snapshot-gövdesi/URI alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-AGT-* karşılanır
    a17 = tr.get("screen", {}).get("a17", {})
    sec = a17.get("section", {})
    for s in ("summary", "history", "stages", "rollback"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("recallableVersions" in data and "previousPublishedVersion" in data and "canRollback" in data and "isRollback" in data and "rollbackRefsResolve" in data, "S5 rollback kapıları (FR-AGT-006)")
    chk("sortedVersions" in data and "hasPendingChanges" in data and "distinguishable" in data, "S5 versiyonlama (FR-AGT-004)")
    chk("countByStage" in data and set(STAGE_ORDER).issubset(a17.get("stage", {}).keys()), "S5 aşama dağılımı (FR-AGT-005)")
    chk("failedTestVersions" in data and set(TEST_ORDER).issubset(a17.get("test", {}).keys()), "S5 test durumu (FR-AGT-010)")
    chk(all(x in a17.get("rollback", {}) for x in ("eligible", "not_eligible", "active", "no_active", "target")), "S5 rollback bölüm metinleri (FR-AGT-006)")
    chk(all(x in a17.get("badge", {}) for x in ("active", "rollback", "default_target")), "S5 rollback/aktif rozetleri")
    chk("missing_active" in a17.get("alert", {}) and "rollback_ref_broken" in a17.get("alert", {}) and "not_distinguishable" in a17.get("alert", {}), "S5 bütünlük/WORM köken uyarıları")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a17.{rk}"
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
        vt = resolve(tr, f"screen.a17.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedVersions", "versionByNo", "activeVersion", "latestVersion", "countByStage", "publishedVersions",
               "draftVersions", "isActive", "versionStatus", "isRollback", "rollbackCount", "recallableVersions",
               "previousPublishedVersion", "canRollback", "hasPendingChanges", "failedTestVersions",
               "duplicateVersionNos", "duplicateVersionIds", "distinguishable", "missingActiveVersion",
               "rollbackRefsResolve", "openAttentionCount", "stageTone", "statusTone", "testTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk(all(c in data for c in ("STAGE_ORDER", "TEST_ORDER", "STATUS_ORDER")), "S7 *_ORDER sabitleri tanımlı")
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

def _base_history():
    return {
        "agentRef": "AGT-117", "agentName": "Poliçe Yenileme Asistanı", "lifecycleState": "production",
        "activeVersionNo": 6,
        "versions": [
            {"versionNo": 7, "versionId": "AV-7f1a", "stage": "test", "isPublished": False, "testStatus": "passed", "publishedBy": "Derya Kaya", "publishedAt": "2026-06-17T14:20:00.000Z", "changeNote": "İade politikası adımı eklendi", "rollbackOfNo": None, "promptVersionNo": 8, "flowVersionNo": 4, "voiceProfile": "tr-Premium-Kadın", "modelProfile": "Büyük tier (kalite)", "sttProfile": "tr-8kHz-telefon"},
            {"versionNo": 6, "versionId": "AV-6c2b", "stage": "production", "isPublished": True, "testStatus": "passed", "publishedBy": "Derya Kaya", "publishedAt": "2026-06-10T09:05:00.000Z", "changeNote": "Karşılama ve yapay zekâ bildirimi netleştirildi", "rollbackOfNo": None, "promptVersionNo": 7, "flowVersionNo": 4, "voiceProfile": "tr-Premium-Kadın", "modelProfile": "Büyük tier (kalite)", "sttProfile": "tr-8kHz-telefon"},
            {"versionNo": 5, "versionId": "AV-5a9d", "stage": "archived", "isPublished": True, "testStatus": "passed", "publishedBy": "Mert Aydın", "publishedAt": "2026-05-28T16:40:00.000Z", "changeNote": "Model tier küçük→büyük güncellendi", "rollbackOfNo": None, "promptVersionNo": 6, "flowVersionNo": 3, "voiceProfile": "tr-Premium-Kadın", "modelProfile": "Büyük tier (kalite)", "sttProfile": "tr-8kHz-telefon"},
            {"versionNo": 4, "versionId": "AV-4b7e", "stage": "archived", "isPublished": True, "testStatus": "passed", "publishedBy": "Mert Aydın", "publishedAt": "2026-05-12T11:15:00.000Z", "changeNote": "v2 yapılandırmasına geri alındı (regresyon sonrası)", "rollbackOfNo": 2, "promptVersionNo": 4, "flowVersionNo": 2, "voiceProfile": "tr-Standart-Kadın", "modelProfile": "Küçük tier (hız)", "sttProfile": "tr-8kHz-telefon"},
            {"versionNo": 3, "versionId": "AV-3d4c", "stage": "archived", "isPublished": True, "testStatus": "passed", "publishedBy": "Derya Kaya", "publishedAt": "2026-04-30T08:00:00.000Z", "changeNote": "Flow tabanlı modele geçildi", "rollbackOfNo": None, "promptVersionNo": 5, "flowVersionNo": 3, "voiceProfile": "tr-Standart-Kadın", "modelProfile": "Küçük tier (hız)", "sttProfile": "tr-8kHz-telefon"},
            {"versionNo": 2, "versionId": "AV-2e8f", "stage": "archived", "isPublished": False, "testStatus": "passed", "publishedBy": "Derya Kaya", "publishedAt": "2026-04-22T10:30:00.000Z", "changeNote": "İlk taslak revizyonu", "rollbackOfNo": None, "promptVersionNo": 2, "flowVersionNo": None, "voiceProfile": "tr-Standart-Kadın", "modelProfile": "Küçük tier (hız)", "sttProfile": "tr-8kHz-telefon"},
            {"versionNo": 1, "versionId": "AV-1a3b", "stage": "archived", "isPublished": False, "testStatus": "not_run", "publishedBy": "Derya Kaya", "publishedAt": "2026-04-15T13:00:00.000Z", "changeNote": "İlk sürüm", "rollbackOfNo": None, "promptVersionNo": 1, "flowVersionNo": None, "voiceProfile": "tr-Standart-Kadın", "modelProfile": "Küçük tier (hız)", "sttProfile": "tr-8kHz-telefon"},
        ],
    }


def _hist_of(sample):
    return sample["agent"] if "agent" in sample else sample


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    h = _base_history()

    chk([v["versionNo"] for v in sorted_versions(h)] == [7, 6, 5, 4, 3, 2, 1], "sortedVersions AZALAN")
    chk(active_version(h)["versionNo"] == 6, "activeVersion=v6 (agent.active_version_id)")
    chk(latest_version(h)["versionNo"] == 7, "latestVersion=v7")
    chk(len(published_versions(h)) == 4, "publishedVersions=4 (v6/v5/v4/v3)")
    chk(len(draft_versions(h)) == 3, "draftVersions=3 (v7/v2/v1)")
    chk(count_by_stage(h) == {"draft": 0, "test": 1, "staging": 0, "production": 1, "archived": 5}, "countByStage (FR-AGT-005)")
    chk(version_status(h, version_by_no(h, 6)) == "active", "versionStatus v6=active")
    chk(version_status(h, version_by_no(h, 5)) == "published", "versionStatus v5=published")
    chk(version_status(h, version_by_no(h, 7)) == "draft", "versionStatus v7=draft (yayınlanmamış)")

    # rollback (FR-AGT-006)
    chk([v["versionNo"] for v in recallable_versions(h)] == [5, 4, 3], "recallableVersions=[5,4,3] (yayınlı + aktif değil)")
    chk(previous_published_version(h)["versionNo"] == 5, "previousPublishedVersion=v5 (aktiften düşük en yüksek; FR-AGT-006)")
    chk(can_rollback(h) is True, "canRollback=True")
    chk(is_rollback(version_by_no(h, 4)) is True, "isRollback v4=True (rollbackOfNo=2)")
    chk(is_rollback(version_by_no(h, 5)) is False, "isRollback v5=False")
    chk(rollback_count(h) == 1, "rollbackCount=1 (v4)")
    chk(rollback_refs_resolve(h) is True, "rollbackRefsResolve=True (v4→v2 mevcut + 2<4; WORM append-only)")

    # versiyonlama + bütünlük
    chk(has_pending_changes(h) is True, "hasPendingChanges=True (latest 7 > active 6; FR-AGT-004)")
    chk(distinguishable(h) is True, "distinguishable=True (versionNo+versionId benzersiz)")
    chk(missing_active_version(h) is False, "missingActiveVersion=False")
    chk(failed_test_versions(h) == [], "failedTestVersions=[] (healthy)")
    chk(open_attention_count(h) == 0, "openAttentionCount=0 (healthy)")

    # tone eşlemeleri
    chk(stage_tone("production") == "success" and stage_tone("test") == "info" and stage_tone("staging") == "warning", "stageTone")
    chk(status_tone("active") == "success" and status_tone("published") == "info" and status_tone("draft") == "warning", "statusTone")
    chk(test_tone("passed") == "success" and test_tone("failed") == "danger" and test_tone("not_run") == "warning", "testTone")

    # İKİ KATMAN guard — pozitif
    chk(assert_safe({"agent": h}) is None, "assertSafe sürüm META görünüm İZİNLİ")
    chk(assert_no_forbidden_keys({"x": {"snapshot": "..."}}) == "$.x.snapshot", "L1 agent_version snapshot GÖVDESİ yakalanır (DB §5.2)")
    chk(assert_no_forbidden_keys({"x": {"promptText": "..."}}) == "$.x.promptText", "L1 prompt gövdesi yakalanır")
    chk(assert_no_forbidden_keys({"x": {"customerName": "..."}}) == "$.x.customerName", "L1 müşteri adı yakalanır")
    chk(assert_no_forbidden_keys({"x": {"signedUrl": "..."}}) == "$.x.signedUrl", "L1 nesne-depo URI yakalanır (NFR 10.6)")
    chk(assert_redaction_clean({"changeNote": "müşteri 05321234567"}) is not None, "L2 ham telefon yakalanır (FR-REC-004)")
    chk(assert_redaction_clean({"publishedBy": "Derya Kaya"}) is None, "L2 yazar adı temiz")
    chk(assert_redaction_clean({"versionNo": 7}) is None, "L2 sürüm no SAYISI (number) taranmaz")

    # samples doğrulaması
    for name in ("versions-healthy.json", "versions-degraded.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        hh = _hist_of(snp)
        exp = snp.get("$expect", {})
        chk(len(hh["versions"]) == exp.get("versions"), f"{name} versions={exp.get('versions')}")
        chk((active_version(hh)["versionNo"] if active_version(hh) else None) == exp.get("active"), f"{name} active={exp.get('active')}")
        chk(len(recallable_versions(hh)) == exp.get("recallable"), f"{name} recallable={exp.get('recallable')}")
        chk((previous_published_version(hh)["versionNo"] if previous_published_version(hh) else None) == exp.get("rollback_target"), f"{name} rollback_target={exp.get('rollback_target')}")
        chk(can_rollback(hh) == exp.get("can_rollback"), f"{name} can_rollback={exp.get('can_rollback')}")
        chk(distinguishable(hh) == exp.get("distinguishable"), f"{name} distinguishable={exp.get('distinguishable')}")
        chk(rollback_refs_resolve(hh) == exp.get("rollback_refs_resolve"), f"{name} rollback_refs_resolve={exp.get('rollback_refs_resolve')}")
        chk(open_attention_count(hh) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
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

    h = _base_history()

    # pozitif (sağlıklı geçmiş)
    expect(can_rollback(h) is True, "pos geri alınabilir (FR-AGT-006)")
    expect(previous_published_version(h)["versionNo"] == 5, "pos varsayılan rollback hedefi v5")
    expect(distinguishable(h) is True, "pos sürümler ayırt edilebilir")
    expect(rollback_refs_resolve(h) is True, "pos rollback köken bütünlüğü (WORM append-only)")
    expect(open_attention_count(h) == 0, "pos açık dikkat yok")

    # sınır: boş geçmiş
    empty = dict(h, activeVersionNo=None, versions=[])
    expect(latest_version(empty) is None, "sınır boş geçmiş latest=None")
    expect(active_version(empty) is None, "sınır boş geçmiş active=None")
    expect(recallable_versions(empty) == [], "sınır boş geçmiş recallable=[]")
    expect(previous_published_version(empty) is None, "sınır boş geçmiş rollback hedefi=None")
    expect(can_rollback(empty) is False, "sınır boş geçmiş geri alınamaz")
    expect(has_pending_changes(empty) is False, "sınır boş geçmiş bekleyen yok")
    expect(rollback_refs_resolve(empty) is True, "sınır boş geçmiş köken bütünlüğü (boş=temiz)")

    # FR-AGT-006: aktif yok ama yayınlı sürüm var → geri alınamaz (aktif kaynak şart)
    no_active = dict(h, activeVersionNo=None)
    expect(can_rollback(no_active) is False, "aktif sürüm yoksa geri alınamaz (FR-AGT-006)")
    expect(has_pending_changes(no_active) is True, "aktif yok + sürüm var → bekleyen değişiklik")

    # FR-AGT-006: tek yayınlı + aktif → geri çağrılabilir yok
    single = dict(h, activeVersionNo=6, versions=[v for v in h["versions"] if v["versionNo"] == 6])
    expect(recallable_versions(single) == [], "tek aktif yayınlı sürüm → geri çağrılabilir yok")
    expect(can_rollback(single) is False, "tek sürüm → geri alınamaz")

    # rollback hedefi: aktiften düşük yoksa en yüksek recallable'a düşer
    high_active = dict(h, activeVersionNo=3, versions=[dict(v) for v in h["versions"]])
    # active=3; recallable = published & not active = v6,v5,v4 (hepsi >3) → below boş → pool=recallable → max=6
    expect(previous_published_version(high_active)["versionNo"] == 6, "aktiften düşük yoksa en yüksek recallable hedef (v6)")

    # bütünlük: yinelenen versionNo yakalanır
    dup = dict(h, versions=[dict(v) for v in h["versions"]])
    dup["versions"][1] = dict(dup["versions"][1], versionNo=7)  # v6→7 (yinelenen)
    expect(7 in duplicate_version_nos(dup), "yinelenen versionNo yakalanır")
    expect(distinguishable(dup) is False, "distinguishable=False (yinelenen no)")
    expect(open_attention_count(dup) >= 1, "yinelenen no → açık dikkat artar")

    dupid = dict(h, versions=[dict(v) for v in h["versions"]])
    dupid["versions"][1] = dict(dupid["versions"][1], versionId="AV-7f1a")  # v6 id = v7 id
    expect("AV-7f1a" in duplicate_version_ids(dupid), "yinelenen versionId yakalanır")
    expect(distinguishable(dupid) is False, "distinguishable=False (yinelenen id)")

    # bütünlük: kopuk aktif referans
    broken = dict(h, activeVersionNo=99)
    expect(missing_active_version(broken) is True, "kopuk aktif referans yakalanır")
    expect(active_version(broken) is None, "kopuk aktif → activeVersion None")

    # WORM köken ihlali: ileriye/var-olmayan rollback
    fwd = dict(h, versions=[dict(v) for v in h["versions"]])
    fwd["versions"][2] = dict(fwd["versions"][2], rollbackOfNo=9)  # v5.rollbackOf=9 (var değil)
    expect(rollback_refs_resolve(fwd) is False, "var olmayan rollback kökeni yakalanır (WORM; DB §6.5)")
    selfref = dict(h, versions=[dict(v) for v in h["versions"]])
    selfref["versions"][2] = dict(selfref["versions"][2], rollbackOfNo=5)  # v5.rollbackOf=5 (kendine)
    expect(rollback_refs_resolve(selfref) is False, "kendine/ileriye rollback yakalanır (append-only)")

    # FR-AGT-010: başarısız test (arşivlenmemiş) açık dikkat
    failed = dict(h, versions=[dict(v) for v in h["versions"]])
    failed["versions"][0] = dict(failed["versions"][0], testStatus="failed")  # v7 test (stage=test)
    expect(len(failed_test_versions(failed)) == 1, "başarısız test (arşivsiz) sayılır (FR-AGT-010)")
    expect(open_attention_count(failed) >= 1, "başarısız test → açık dikkat")
    # arşivlenmiş başarısız test sayılmaz
    arch_fail = dict(h, versions=[dict(v) for v in h["versions"]])
    arch_fail["versions"][6] = dict(arch_fail["versions"][6], testStatus="failed")  # v1 archived
    expect(len(failed_test_versions(arch_fail)) == 0, "arşivlenmiş başarısız test sayılmaz")

    # İKİ KATMAN guard — negatif
    expect(assert_no_forbidden_keys({"x": {"transcriptText": "..."}}) is not None, "L1 transkript metni yakalanır")
    expect(assert_no_forbidden_keys({"x": {"snapshot": {}}}) is not None, "L1 snapshot gövdesi yakalanır (DB §5.2)")
    expect(assert_no_forbidden_keys({"x": {"flowDefinition": "..."}}) is not None, "L1 flow tanımı gövdesi yakalanır")
    expect(assert_no_forbidden_keys({"x": {"e164": "..."}}) is not None, "L1 ham numara (e164) yakalanır")
    expect(assert_redaction_clean({"c": "TR12 3456"}) is not None, "L2 IBAN deseni yakalanır")
    expect(assert_redaction_clean({"c": "kart 4111 1111 1111"}) is not None, "L2 kart bloğu yakalanır (FR-REC-005)")
    expect(assert_redaction_clean({"c": "Maskeli [•••] sürüm notu"}) is None, "L2 maskeli not temiz")
    expect(assert_redaction_clean({"publishedBy": "iletisim: a@b.com"}) is not None, "L2 e-posta yakalanır")
    leaky = {"agent": {"versions": [{"changeNote": "ara: 05551234567"}]}}
    expect(assert_safe(leaky) is not None, "kritik ham telefon içeren not yakalanır (REDACTION ihlali)")

    # placeholder ayrıştırma
    expect(placeholders("hedef {target} ({id})") == {"target", "id"}, "placeholder parse çoklu")
    expect(placeholders("Prompt v{prompt} · Flow {flow} · {model} · {voice} · {stt}") == {"prompt", "flow", "model", "voice", "stt"}, "config_summary placeholder parse")

    # ISO zaman damgası redaction'ı tetiklemez (ardışık ≤4 rakam)
    expect(assert_redaction_clean({"publishedAt": "2026-06-17T14:20:00.000Z"}) is None, "ISO zaman damgası redaction temiz")
    expect(assert_redaction_clean({"versionId": "AV-7f1a"}) is None, "versionId redaction temiz")

    # spec tutarlılık
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 70, "spec ≥70 referans anahtar")
    expect(spec["stages"] == STAGE_ORDER, "spec stages = STAGE_ORDER")
    expect(spec["test_statuses"] == TEST_ORDER, "spec test_statuses = TEST_ORDER")
    expect(spec["version_statuses"] == STATUS_ORDER, "spec version_statuses = STATUS_ORDER")
    expect(spec["mask_token"] == MASK_TOKEN, "spec mask_token = MASK_TOKEN")
    expect(spec["rbac"]["conversation_designer"] == "manage" and spec["rbac"]["qa_analyst"] == "none", "spec RBAC A-17 (designer=Yönet · qa=—)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "AgentVersionView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "agent": {
                "agentRef": "str (tenant-içi)", "agentName": "str", "lifecycleState": "|".join(STAGE_ORDER) + " (FR-AGT-005)",
                "activeVersionNo": "int|null (agent.active_version_id — FR-AGT-006 rollback kaynağı)",
                "versions": [{
                    "versionNo": "int (DB version_no; UNIQUE)", "versionId": "str (ayırt edici)",
                    "stage": "|".join(STAGE_ORDER), "isPublished": "bool", "testStatus": "|".join(TEST_ORDER) + " (FR-AGT-010)",
                    "publishedBy": "str (DB published_by — izinli)", "publishedAt": "ISO-8601 (DB published_at)",
                    "changeNote": "str (tenant config — snapshot GÖVDESİ DEĞİL)",
                    "rollbackOfNo": "int|null (ROLLBACK kökeni — FR-AGT-006 / WORM DB §6.5)",
                    "promptVersionNo": "int", "flowVersionNo": "int|null", "voiceProfile": "str", "modelProfile": "str", "sttProfile": "str (bağlanan config — yalnız AD; snapshot JSONB gömülmez)"
                }]
            }
        },
        "stages": STAGE_ORDER, "test_statuses": TEST_ORDER, "version_statuses": STATUS_ORDER, "mask_token": MASK_TOKEN,
        "invariants": "sortedVersions: versionNo AZALAN. activeVersion: activeVersionNo→sürüm. recallableVersions: yayınlı ∧ aktif değil (FR-AGT-006 rollback adayları). previousPublishedVersion: aktiften düşük en yüksek yayınlı (tek-işlem varsayılan hedef; aksi en yüksek recallable). canRollback: aktif var ∧ recallable var. isRollback: rollbackOfNo≠null. rollbackRefsResolve: her rollbackOfNo MEVCUT ∧ < versionNo (WORM append-only; DB §6.5). distinguishable: versionNo+versionId benzersiz. hasPendingChanges: latest>active. failedTestVersions: arşivsiz ∧ testStatus=failed (FR-AGT-010). openAttentionCount: bütünlük ihlalleri + başarısız test.",
        "hijyen": "A-17 yalnız SÜRÜM META gösterir → break-glass GEREKMEZ; ham çağrı içeriği/transkript/PII + agent_version snapshot JSONB GÖVDESİ TAŞIMAZ. İKİ KATMAN guard: (1) assertNoForbiddenKeys — ham kimlik/iş-içeriği (transkript/ses/ham numara/müşteri) + snapshot/prompt/flow GÖVDESİ + sır/credential/nesne-depo URI alan ADI YOK. (2) assertRedactionClean — hiçbir STRING değer ham PII DESENİ taşımaz; sürüm no/sayılar taranmaz (FR-REC-004/005). Geri al/promote/yeni-sürüm derin aksiyon (agent:version:manage — API §8.1); tek-işlem rollback WORM append-only backend (SAD §14.4.1 / DB §6.5).",
        "rbac": "conversation_designer=Yönet · operations_manager=Görüntüle · qa_analyst=— · human_agent=— (BRD §17.6); tenant_owner kural 17.7 ile Yönet. Permission-key: agent:version:manage (API §8.1)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a17_versions_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
