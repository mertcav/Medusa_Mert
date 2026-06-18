#!/usr/bin/env python3
# WBS 13.4.6 — A-06 "Prompt Editor (versiyonlama)" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (sortedVersions/activeVersion/latestVersion/countByStage/
#               publishedVersions/draftVersions/recallableVersions/canRollback/hasPendingChanges/
#               failedTestVersions/duplicateVersionNos/duplicateVersionIds/distinguishable/
#               missingActiveVersion/openAttentionCount/versionStatus/tone'lar/assertNoPii) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (bütünlük/test-bloklu/bekleyen sürüm beklendiği gibi yakalanır)
#   schema    — prompt sürüm görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/prompts.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a06-prompts-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "prompts", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "prompts.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

STAGE_ORDER = ["draft", "test", "staging", "production", "archived"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey", "prompttext", "promptbody", "body"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/prompts.ts ile birebir) ───────────────────────

def sorted_versions(history):
    return sorted(history["versions"], key=lambda v: v["versionNo"], reverse=True)


def version_by_no(history, no):
    for v in history["versions"]:
        if v["versionNo"] == no:
            return v
    return None


def active_version(history):
    if history["activeVersionNo"] is None:
        return None
    return version_by_no(history, history["activeVersionNo"])


def latest_version(history):
    if not history["versions"]:
        return None
    best = history["versions"][0]
    for v in history["versions"][1:]:
        if v["versionNo"] > best["versionNo"]:
            best = v
    return best


def count_by_stage(history):
    acc = {s: 0 for s in STAGE_ORDER}
    for v in history["versions"]:
        acc[v["stage"]] += 1
    return acc


def published_versions(history):
    return [v for v in history["versions"] if v["isPublished"]]


def draft_versions(history):
    return [v for v in history["versions"] if not v["isPublished"]]


def is_active(history, v):
    return history["activeVersionNo"] is not None and v["versionNo"] == history["activeVersionNo"]


def version_status(history, v):
    if is_active(history, v):
        return "active"
    if v["isPublished"]:
        return "published"
    return "draft"


def recallable_versions(history):
    return [v for v in history["versions"] if v["isPublished"] and not is_active(history, v)]


def can_rollback(history):
    return history["activeVersionNo"] is not None and len(recallable_versions(history)) > 0


def has_pending_changes(history):
    latest = latest_version(history)
    if latest is None:
        return False
    if history["activeVersionNo"] is None:
        return True
    return latest["versionNo"] > history["activeVersionNo"]


def failed_test_versions(history):
    return [v for v in history["versions"] if v["stage"] != "archived" and v["testStatus"] == "failed"]


def duplicate_version_nos(history):
    seen, dup = set(), set()
    for v in history["versions"]:
        if v["versionNo"] in seen:
            dup.add(v["versionNo"])
        seen.add(v["versionNo"])
    return sorted(dup)


def duplicate_version_ids(history):
    seen, dup = set(), set()
    for v in history["versions"]:
        if v["versionId"] in seen:
            dup.add(v["versionId"])
        seen.add(v["versionId"])
    return sorted(dup)


def distinguishable(history):
    return len(duplicate_version_nos(history)) == 0 and len(duplicate_version_ids(history)) == 0


def missing_active_version(history):
    return history["activeVersionNo"] is not None and version_by_no(history, history["activeVersionNo"]) is None


def open_attention_count(history):
    return (len(duplicate_version_nos(history))
            + len(duplicate_version_ids(history))
            + (1 if missing_active_version(history) else 0)
            + len(failed_test_versions(history)))


def stage_tone(s):
    return {"draft": "neutral", "test": "info", "staging": "warning",
            "production": "success", "archived": "neutral"}[s]


def status_tone(s):
    return {"active": "success", "published": "info", "draft": "warning"}[s]


def test_tone(t):
    return {"passed": "success", "failed": "danger", "not_run": "warning"}[t]


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/prompt-gövdesi alan adı bulursa (path) döndürür; yoksa None."""
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
    """prompts.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.6", "S0 spec.wbs=13.4.6")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/prompts/page.tsx mevcut")
    chk('data-screen="A-06"' in page, 'S1 data-screen="A-06" işaretli')
    chk("İskelet ekran — A-06" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/prompts" in page, "S2 veri seam (lib/tenant/prompts) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a06.*); hardcoded TR/EN cümle yok
    chk("screen.a06." in page, "S3 screen.a06.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/prompt-gövdesi-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/prompts.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getPromptView assertNoPii çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("prompttext", "promptbody", "body")), "S4 prompt GÖVDESİ (promptText/promptBody/body) yasak (NFR 10.6)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-AGT-004/005/006/010 + SR-AGT-004 karşılanır
    a06 = tr.get("screen", {}).get("a06", {})
    sec = a06.get("section", {})
    for s in ("summary", "history", "stages", "rollback"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("versionId" in data and "distinguishable" in data, "S5 ayırt edici sürüm kimliği (SR-AGT-004)")
    chk(set(STAGE_ORDER).issubset(a06.get("stage", {}).keys()), "S5 aşamalar (draft/test/staging/production/archived — FR-AGT-005)")
    chk("recallableVersions" in data and "canRollback" in data and "rollback" in sec, "S5 geri alma / rollback (FR-AGT-006)")
    chk("failedTestVersions" in data and "test_blocked" in a06.get("kpi", {}), "S5 test kapısı (FR-AGT-010)")
    chk(set(["passed", "failed", "not_run"]).issubset(a06.get("test", {}).keys()), "S5 test durumları")
    chk(set(["active", "published", "draft"]).issubset(a06.get("status", {}).keys()), "S5 sürüm durumları")
    chk("hasPendingChanges" in data and "pending_changes" in a06.get("alert", {}), "S5 bekleyen değişiklik (FR-AGT-004)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a06.{rk}"
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
        vt = resolve(tr, f"screen.a06.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedVersions", "versionByNo", "activeVersion", "latestVersion", "countByStage",
               "publishedVersions", "draftVersions", "isActive", "versionStatus", "recallableVersions",
               "canRollback", "hasPendingChanges", "failedTestVersions", "duplicateVersionNos",
               "duplicateVersionIds", "distinguishable", "missingActiveVersion", "openAttentionCount",
               "stageTone", "statusTone", "testTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("STAGE_ORDER" in data, "S7 STAGE_ORDER sabiti tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "splunk", "sumologic", "twilio.com", "telnyx.com"]
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

def _v(no, vid, stage="archived", published=True, test="passed"):
    return {"versionNo": no, "versionId": vid, "stage": stage, "isPublished": published,
            "testStatus": test, "createdAt": "2026-01-01T00:00:00.000Z", "author": "A",
            "changeNote": "n", "charCount": 100 * no, "variableCount": no}


def _history(active, versions):
    return {"promptRef": "P", "agentRef": "AG", "agentName": "Agent", "activeVersionNo": active, "versions": versions}


def _base_history():
    # v5 aktif (production), v6 test'i geçen bekleyen, v4/v3 yayınlı arşiv (geri çağrılabilir), v2/v1 taslak arşiv
    return _history(5, [
        _v(6, "PV-6", "test", False, "passed"),
        _v(5, "PV-5", "production", True, "passed"),
        _v(4, "PV-4", "archived", True, "passed"),
        _v(3, "PV-3", "archived", True, "passed"),
        _v(2, "PV-2", "archived", False, "passed"),
        _v(1, "PV-1", "archived", False, "not_run"),
    ])


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    h = _base_history()
    chk([v["versionNo"] for v in sorted_versions(h)] == [6, 5, 4, 3, 2, 1], "sortedVersions DESC")
    chk(active_version(h)["versionNo"] == 5, "activeVersion=v5")
    chk(latest_version(h)["versionNo"] == 6, "latestVersion=v6")
    chk(count_by_stage(h) == {"draft": 0, "test": 1, "staging": 0, "production": 1, "archived": 4}, "countByStage")
    chk([v["versionNo"] for v in published_versions(h)] == [5, 4, 3], "publishedVersions=[5,4,3]")
    chk([v["versionNo"] for v in draft_versions(h)] == [6, 2, 1], "draftVersions=[6,2,1]")
    chk(version_status(h, version_by_no(h, 5)) == "active", "versionStatus(v5)=active")
    chk(version_status(h, version_by_no(h, 4)) == "published", "versionStatus(v4)=published")
    chk(version_status(h, version_by_no(h, 6)) == "draft", "versionStatus(v6)=draft (yayınlanmamış)")
    chk([v["versionNo"] for v in recallable_versions(h)] == [4, 3], "recallableVersions=[4,3] (yayınlı, aktif değil)")
    chk(can_rollback(h) is True, "canRollback=True")
    chk(has_pending_changes(h) is True, "hasPendingChanges=True (v6>v5)")
    chk(failed_test_versions(h) == [], "failedTestVersions=[]")
    chk(duplicate_version_nos(h) == [], "duplicateVersionNos=[]")
    chk(duplicate_version_ids(h) == [], "duplicateVersionIds=[]")
    chk(distinguishable(h) is True, "distinguishable=True")
    chk(missing_active_version(h) is False, "missingActiveVersion=False")
    chk(open_attention_count(h) == 0, "openAttentionCount=0")

    # yinelenen versionNo / versionId → ayırt edilemez
    dupn = _history(1, [_v(1, "PV-1"), _v(1, "PV-9"), _v(2, "PV-2")])
    chk(duplicate_version_nos(dupn) == [1], "duplicateVersionNos=[1]")
    chk(distinguishable(dupn) is False, "distinguishable=False (yinelenen no)")
    dupi = _history(1, [_v(1, "PV-X"), _v(2, "PV-X")])
    chk(duplicate_version_ids(dupi) == ["PV-X"], "duplicateVersionIds=[PV-X]")
    chk(distinguishable(dupi) is False, "distinguishable=False (yinelenen id)")

    # kopuk aktif referans
    miss = _history(9, [_v(1, "PV-1"), _v(2, "PV-2")])
    chk(active_version(miss) is None, "activeVersion=None (kopuk)")
    chk(missing_active_version(miss) is True, "missingActiveVersion=True")
    chk(open_attention_count(miss) == 1, "openAttentionCount=1 (kopuk aktif)")

    # başarısız test (arşiv hariç)
    ft = _history(2, [_v(1, "PV-1", "production", True, "passed"),
                      _v(2, "PV-2", "test", False, "failed"),
                      _v(3, "PV-3", "archived", True, "failed")])  # arşiv başarısızı sayılmaz
    chk([v["versionNo"] for v in failed_test_versions(ft)] == [2], "failedTestVersions=[2] (arşiv hariç)")
    chk(open_attention_count(ft) == 1, "openAttentionCount=1 (başarısız test)")

    # hiç aktif yok → bekleyen, rollback yok
    na = _history(None, [_v(1, "PV-1", "draft", False, "not_run")])
    chk(active_version(na) is None, "activeVersion=None (aktif yok)")
    chk(has_pending_changes(na) is True, "hasPendingChanges=True (aktif yok)")
    chk(can_rollback(na) is False, "canRollback=False (aktif yok)")

    # aktif = en son → bekleyen yok
    no_pending = _history(3, [_v(1, "PV-1", "archived", True), _v(2, "PV-2", "archived", True), _v(3, "PV-3", "production", True)])
    chk(has_pending_changes(no_pending) is False, "hasPendingChanges=False (aktif=en son)")

    # tone eşlemeleri
    chk(stage_tone("production") == "success" and stage_tone("test") == "info" and stage_tone("staging") == "warning", "stageTone")
    chk(status_tone("active") == "success" and status_tone("published") == "info" and status_tone("draft") == "warning", "statusTone")
    chk(test_tone("passed") == "success" and test_tone("failed") == "danger" and test_tone("not_run") == "warning", "testTone")

    # assertNoPii — sürüm META İZİNLİ, ham içerik + sır + prompt-gövdesi YASAK
    chk(assert_no_pii({"a": _base_history()}) is None, "assertNoPii sürüm META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii tool sırrı yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"promptBody": "..."}}) == "$.x.promptBody", "assertNoPii prompt gövdesi yakalar")
    chk(assert_no_pii({"x": {"body": "..."}}) == "$.x.body", "assertNoPii prompt.body yakalar (DB §5.2)")

    # samples doğrulaması
    for name in ("prompt-clean.json", "prompt-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        h2 = snp["prompt"]
        av = active_version(h2)
        chk(len(h2["versions"]) == exp.get("versions"), f"{name} versions={exp.get('versions')}")
        chk((av["versionNo"] if av else None) == exp.get("active"), f"{name} active={exp.get('active')}")
        chk(len(published_versions(h2)) == exp.get("published"), f"{name} published={exp.get('published')}")
        chk(len(draft_versions(h2)) == exp.get("draft"), f"{name} draft={exp.get('draft')}")
        chk(len(recallable_versions(h2)) == exp.get("recallable"), f"{name} recallable={exp.get('recallable')}")
        chk(can_rollback(h2) == exp.get("can_rollback"), f"{name} can_rollback={exp.get('can_rollback')}")
        chk(has_pending_changes(h2) == exp.get("pending"), f"{name} pending={exp.get('pending')}")
        chk(len(failed_test_versions(h2)) == exp.get("failed_test"), f"{name} failed_test={exp.get('failed_test')}")
        chk(distinguishable(h2) == exp.get("distinguishable"), f"{name} distinguishable={exp.get('distinguishable')}")
        chk(missing_active_version(h2) == exp.get("missing_active"), f"{name} missing_active={exp.get('missing_active')}")
        chk(open_attention_count(h2) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır-free (HİJYEN+GÜVENLİK)")

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

    # pozitif (sağlıklı sürüm geçmişi)
    ok = _base_history()
    expect(distinguishable(ok) is True, "pos ayırt edilebilir")
    expect(missing_active_version(ok) is False, "pos aktif referansı sağlam")
    expect(failed_test_versions(ok) == [], "pos başarısız test yok")
    expect(open_attention_count(ok) == 0, "pos açık dikkat=0")
    expect(can_rollback(ok) is True, "pos geri alınabilir")

    # negatif (çok-sorunlu: yinelenen no + yinelenen id + kopuk aktif + başarısız test)
    bad = _history(99, [
        _v(1, "PV-DUP", "production", True, "passed"),
        _v(1, "PV-DUP", "test", False, "failed"),   # yinelenen no + yinelenen id + başarısız test
        _v(2, "PV-2", "test", False, "failed"),       # başarısız test
    ])
    expect(duplicate_version_nos(bad) == [1], "neg yinelenen no=[1]")
    expect(duplicate_version_ids(bad) == ["PV-DUP"], "neg yinelenen id=[PV-DUP]")
    expect(distinguishable(bad) is False, "neg ayırt edilemez")
    expect(missing_active_version(bad) is True, "neg kopuk aktif (99 yok)")
    expect(len(failed_test_versions(bad)) == 2, "neg başarısız test=2")
    expect(active_version(bad) is None, "neg aktif sürüm bulunamaz")
    # attention = dup_no(1) + dup_id(1) + missing_active(1) + failed(2) = 5
    expect(open_attention_count(bad) == 5, "neg açık dikkat=5")

    # sınır: tek sürüm, hiç yayınlanmamış → bekleyen, rollback yok, aktif yok
    one = _history(None, [_v(1, "PV-1", "draft", False, "not_run")])
    expect(has_pending_changes(one) is True, "sınır tek taslak → bekleyen")
    expect(can_rollback(one) is False, "sınır rollback yok (yayın yok)")
    expect(active_version(one) is None, "sınır aktif yok")

    # sınır: boş geçmiş
    empty = _history(None, [])
    expect(latest_version(empty) is None, "sınır boş geçmiş latest=None")
    expect(has_pending_changes(empty) is False, "sınır boş geçmiş bekleyen yok")
    expect(can_rollback(empty) is False, "sınır boş geçmiş rollback yok")
    expect(open_attention_count(empty) == 0, "sınır boş geçmiş dikkat=0")

    # sınır: aktif=en son → bekleyen yok ama önceki yayın → rollback var
    cur = _history(2, [_v(1, "PV-1", "archived", True, "passed"), _v(2, "PV-2", "production", True, "passed")])
    expect(has_pending_changes(cur) is False, "sınır aktif=en son → bekleyen yok")
    expect(can_rollback(cur) is True, "sınır önceki yayın → rollback var")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"webhookSecret": "x"}]}) is not None, "neg webhookSecret yakalanır")
    expect(assert_no_pii({"x": {"promptText": "..."}}) is not None, "neg promptText yakalanır")
    expect(assert_no_pii({"x": {"body": "..."}}) is not None, "neg prompt.body yakalanır (DB §5.2)")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")

    # tone sınır
    expect(status_tone("draft") == "warning", "taslak → warning")
    expect(test_tone("failed") == "danger", "başarısız test → danger")
    expect(stage_tone("archived") == "neutral", "arşiv → neutral")

    # placeholder ayrıştırma
    expect(placeholders("{count} sorun") == {"count"}, "placeholder parse")
    expect(placeholders("{version} ({id})") == {"version", "id"}, "placeholder çoklu parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 70, "spec ≥70 referans anahtar")
    expect(spec["stages"] == STAGE_ORDER, "spec stages = STAGE_ORDER")
    expect(spec["test_statuses"] == ["passed", "failed", "not_run"], "spec test_statuses tutarlı")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "PromptView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "prompt": {
                "promptRef": "str (DB §5.2 prompt gösterim kimliği)",
                "agentRef": "str (sürümleri görüntülenen agent — tenant config)",
                "agentName": "str (agent adı — tenant config; PII değil)",
                "activeVersionNo": "int|null (agent.active_version_id — production; FR-AGT-006 hedefi)",
                "versions": [{"versionNo": "int (DB §5.2 version_no)",
                              "versionId": "str (ayırt edici kimlik — SR-AGT-004)",
                              "stage": "draft|test|staging|production|archived (FR-AGT-005)",
                              "isPublished": "bool (DB §5.2 is_published)",
                              "testStatus": "passed|failed|not_run (FR-AGT-010)",
                              "createdAt": "ISO-8601 (sürüm META)",
                              "author": "str (tenant kullanıcı — izinli)",
                              "changeNote": "str (tenant config; GÖVDE DEĞİL)",
                              "charCount": "int (gövde boyutu — yalnız SAYI)",
                              "variableCount": "int (şablon değişkeni — yalnız SAYI)"}]
            }
        },
        "stages": STAGE_ORDER,
        "version_statuses": ["active", "published", "draft"],
        "test_statuses": ["passed", "failed", "not_run"],
        "hijyen": "A-06 yalnız SÜRÜM META gösterir (sürüm no/kimliği/aşama/durum/test/boyut SAYISI/değişiklik notu — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR/müşteri) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential + PROMPT GÖVDESİ (apiKey/webhookSecret/token/promptText/promptBody/body) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Prompt gövdesi düzenleme (editör alanı) derin aksiyon → client island (görsel kapı). VERSİYONLAMA ekranı (FR-AGT-004 / SR-AGT-004); gerçek zamanlı DEĞİL (FR-ANA-012 dışı)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a06_prompts_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
