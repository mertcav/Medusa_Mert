#!/usr/bin/env python3
# WBS 13.2.2 — P-02 "Tenant Yönetimi & Provisioning" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (statusTone/countByStatus/lifecycleActions/provisioningProgress/
#               isTerminal/assertNoPii) + samples/* snapshot doğrulaması (durum sayımı + lifecycle + PII-free)
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/tenants.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p02-tenants-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "tenants", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "tenants.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/tenants.ts ile birebir) ─────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "pii", "email", "ssn"]

ALL_STATUSES = ["provisioning", "active", "suspended", "deprovisioning", "deleted"]

STATUS_TONE = {
    "active": "success",
    "suspended": "warning",
    "provisioning": "info",
    "deprovisioning": "warning",
    "deleted": "danger",
}

LIFECYCLE_ACTIONS = {
    "provisioning": [],
    "active": ["suspend", "assign_plan", "delete"],
    "suspended": ["resume", "assign_plan", "delete"],
    "deprovisioning": [],
    "deleted": [],
}


def status_tone(s):
    return STATUS_TONE[s]


def count_by_status(tenants):
    counts = {s: 0 for s in ALL_STATUSES}
    for t in tenants:
        counts[t["status"]] += 1
    return counts


def lifecycle_actions(status):
    return list(LIFECYCLE_ACTIONS[status])


def is_terminal(status):
    return status == "deleted"


def provisioning_progress(step, total):
    if total <= 0:
        return 0.0
    pct = (step / total) * 100.0
    return min(100.0, max(0.0, round(pct * 10) / 10))


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
    """tenants.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.2", "S0 spec.wbs=13.2.2")
    chk(os.path.isfile(PAGE_PATH), "S1 tenants/page.tsx mevcut")
    chk('data-screen="P-02"' in page, 'S1 data-screen="P-02" işaretli')
    chk("İskelet ekran — P-02" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/tenants" in page, "S2 veri seam (lib/platform/tenants) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p02.*); hardcoded TR/EN cümle yok
    chk("screen.p02." in page, "S3 screen.p02.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/tenants.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getTenants assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (provisioning aksiyonları + durum)
    act = tr.get("screen", {}).get("p02", {}).get("action", {})
    chk("create" in act, "S5 'tenant oluşturma' → action.create")
    chk("suspend" in act, "S5 'tenant askıya alma' → action.suspend")
    chk("delete" in act, "S5 'tenant silme' → action.delete")
    chk("assign_plan" in act, "S5 'plan atama' → action.assign_plan")
    st = tr.get("screen", {}).get("p02", {}).get("status", {})
    chk(all(s in st for s in ALL_STATUSES), "S5 'durum' → tüm yaşam döngüsü durumları")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p02.{rk}"
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
        vt = resolve(tr, f"screen.p02.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("statusTone", "countByStatus", "lifecycleActions", "provisioningProgress", "isTerminal"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "datadog.com", "api_key", "secret="]
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

    # statusTone
    chk(status_tone("active") == "success", "tone active→success")
    chk(status_tone("suspended") == "warning", "tone suspended→warning")
    chk(status_tone("provisioning") == "info", "tone provisioning→info")
    chk(status_tone("deprovisioning") == "warning", "tone deprovisioning→warning")
    chk(status_tone("deleted") == "danger", "tone deleted→danger")
    # lifecycleActions (durum makinesi)
    chk(lifecycle_actions("active") == ["suspend", "assign_plan", "delete"], "active → suspend/assign/delete")
    chk(lifecycle_actions("suspended") == ["resume", "assign_plan", "delete"], "suspended → resume/assign/delete")
    chk(lifecycle_actions("provisioning") == [], "provisioning → aksiyon yok")
    chk(lifecycle_actions("deprovisioning") == [], "deprovisioning → aksiyon yok")
    chk(lifecycle_actions("deleted") == [], "deleted (terminal) → aksiyon yok")
    chk("suspend" not in lifecycle_actions("suspended"), "askıya alınmış tekrar askıya alınamaz")
    chk("resume" not in lifecycle_actions("active"), "aktif devam-ettirilemez")
    # isTerminal
    chk(is_terminal("deleted") is True, "deleted terminal")
    chk(is_terminal("active") is False, "active terminal değil")
    # provisioningProgress
    chk(provisioning_progress(3, 6) == 50.0, "progress 3/6=50.0")
    chk(provisioning_progress(0, 0) == 0.0, "progress total=0 → 0")
    chk(provisioning_progress(9, 6) == 100.0, "progress kıstırma ≤100")
    chk(provisioning_progress(-1, 6) == 0.0, "progress kıstırma ≥0")
    # countByStatus
    cb = count_by_status([{"status": "active"}, {"status": "active"}, {"status": "suspended"}])
    chk(cb == {"provisioning": 0, "active": 2, "suspended": 1, "deprovisioning": 0, "deleted": 0}, "countByStatus doğru")
    # assertNoPii
    chk(assert_no_pii({"tenants": [{"name": "Acme", "plan": "growth"}]}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"tenants": [{"transcript": "x"}]}) == "$.tenants[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")

    # samples doğrulaması
    for name in ("tenants-mixed.json", "tenants-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(count_by_status(snap["tenants"]) == exp.get("counts"), f"{name} counts={exp.get('counts')}")
        chk(len(snap["tenants"]) == exp.get("total"), f"{name} total={exp.get('total')}")
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

    # pozitif
    expect(status_tone("active") == "success", "pos tone")
    expect(provisioning_progress(1, 4) == 25.0, "pos progress")
    expect(assert_no_pii({"name": "Acme"}) is None, "pos no-pii (tenant adı izinli)")
    expect(lifecycle_actions("active") != [], "pos active aksiyon sunar")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(lifecycle_actions("deleted") == [], "neg terminal aksiyon sunmaz")
    expect(provisioning_progress(99, 6) == 100.0, "neg aşırı progress kıstırılır")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{step}/{total} adım") == {"step", "total"}, "çoklu placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 39, "spec ≥39 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "TenantsSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenants": [{
                "id": "str", "name": "str (tenant org adı — izinli; son-müşteri PII değil)",
                "plan": "starter|growth|enterprise|dedicated",
                "status": "provisioning|active|suspended|deprovisioning|deleted",
                "region": "uk|eu|na|me", "createdAt": "ISO-8601 string",
                "activeUsers": "int (yalnız sayı)",
                "provisioningStep?": "int", "provisioningTotalSteps?": "int"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular.",
        "lifecycle": LIFECYCLE_ACTIONS
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p02_tenants_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
