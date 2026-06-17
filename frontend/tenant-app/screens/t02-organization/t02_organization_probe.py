#!/usr/bin/env python3
# WBS 13.3.2 — T-02 "Organizasyon & Yapı" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countByType/countByStatus/childrenOf/rootUnits/projectsForUnit/
#               orphanProjects/tone'lar/assertNoPii) + samples/* snapshot doğrulaması (beklenti + PII-free)
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/organization.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t02-organization-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "org", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "organization.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/organization.ts ile birebir) ──────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "pii", "email", "ssn"]


def count_by_type(units):
    out = {"brand": 0, "department": 0, "country": 0}
    for u in units:
        out[u["type"]] += 1
    return out


def count_by_status(units):
    out = {"active": 0, "inactive": 0, "archived": 0}
    for u in units:
        out[u["status"]] += 1
    return out


def unit_status_tone(s):
    return {"active": "success", "inactive": "warning", "archived": "neutral"}[s]


def project_status_tone(s):
    return {"active": "success", "paused": "warning", "archived": "neutral"}[s]


def children_of(units, parent_id):
    return [u for u in units if u["parentId"] == parent_id]


def root_units(units):
    return [u for u in units if u["parentId"] is None]


def projects_for_unit(projects, unit_id):
    return sum(
        1 for p in projects
        if p["brandRef"] == unit_id or p["departmentRef"] == unit_id or p["countryRef"] == unit_id
    )


def orphan_projects(projects, units):
    ids = {u["id"] for u in units}
    out = []
    for p in projects:
        refs = [r for r in (p["brandRef"], p["departmentRef"], p["countryRef"]) if r is not None]
        if any(r not in ids for r in refs):
            out.append(p["id"])
    return out


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği alan adı bulursa (path) döndürür; yoksa None."""
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
    chk(spec.get("wbs") == "13.3.2", "S0 spec.wbs=13.3.2")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/org/page.tsx mevcut")
    chk('data-screen="T-02"' in page, 'S1 data-screen="T-02" işaretli')
    chk("İskelet ekran — T-02" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/organization" in page, "S2 veri seam (lib/tenant/organization) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t02.*); hardcoded TR/EN cümle yok
    chk("screen.t02." in page, "S3 screen.t02.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + HİJYEN guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/organization.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getOrgStructure assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/iş-içeriği alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 dört içerik öğesi karşılanır (tür + bölüm anahtarları)
    ty = tr.get("screen", {}).get("t02", {}).get("type", {})
    chk("brand" in ty, "S5 'marka' → type.brand")
    chk("department" in ty, "S5 'departman' → type.department")
    chk("country" in ty, "S5 'ülke' → type.country")
    sec = tr.get("screen", {}).get("t02", {}).get("section", {})
    chk("projects" in sec, "S5 'proje' → section.projects")
    chk("units" in sec, "S5 organizasyon birimleri → section.units")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t02.{rk}"
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
        vt = resolve(tr, f"screen.t02.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("countByType", "countByStatus", "childrenOf", "rootUnits", "projectsForUnit",
               "orphanProjects", "unitStatusTone", "projectStatusTone"):
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


def _extract_data_fields(ts):
    """organization.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    units = [
        {"id": "BR-1", "type": "brand", "parentId": None, "status": "active"},
        {"id": "BR-2", "type": "brand", "parentId": None, "status": "archived"},
        {"id": "DP-1", "type": "department", "parentId": "BR-1", "status": "active"},
        {"id": "DP-2", "type": "department", "parentId": "BR-1", "status": "inactive"},
        {"id": "CN-1", "type": "country", "parentId": None, "status": "active"},
    ]
    projects = [
        {"id": "P-1", "brandRef": "BR-1", "departmentRef": "DP-1", "countryRef": "CN-1", "status": "active"},
        {"id": "P-2", "brandRef": "BR-2", "departmentRef": None, "countryRef": None, "status": "paused"},
        {"id": "P-3", "brandRef": "BR-9", "departmentRef": None, "countryRef": None, "status": "active"},  # öksüz
    ]

    # countByType / countByStatus
    chk(count_by_type(units) == {"brand": 2, "department": 2, "country": 1}, "countByType")
    chk(count_by_status(units) == {"active": 3, "inactive": 1, "archived": 1}, "countByStatus")
    # tone eşlemeleri
    chk(unit_status_tone("active") == "success" and unit_status_tone("inactive") == "warning" and unit_status_tone("archived") == "neutral", "unitStatusTone")
    chk(project_status_tone("active") == "success" and project_status_tone("paused") == "warning" and project_status_tone("archived") == "neutral", "projectStatusTone")
    # hiyerarşi
    chk([u["id"] for u in children_of(units, "BR-1")] == ["DP-1", "DP-2"], "childrenOf BR-1")
    chk([u["id"] for u in root_units(units)] == ["BR-1", "BR-2", "CN-1"], "rootUnits")
    # projects per unit
    chk(projects_for_unit(projects, "BR-1") == 1, "projectsForUnit BR-1=1")
    chk(projects_for_unit(projects, "DP-1") == 1, "projectsForUnit DP-1=1")
    chk(projects_for_unit(projects, "CN-1") == 1, "projectsForUnit CN-1=1")
    chk(projects_for_unit(projects, "BR-2") == 1, "projectsForUnit BR-2=1")
    # orphan referans
    chk(orphan_projects(projects, units) == ["P-3"], "orphanProjects P-3")
    chk(orphan_projects(projects[:2], units) == [], "orphanProjects temiz → boş")
    # assertNoPii
    chk(assert_no_pii({"units": [{"name": "Perakende", "code": "BR-1"}]}) is None, "assertNoPii temiz yapı OK")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"tenantName": "Acme", "tenantRef": "TEN-1"}) is None, "assertNoPii tenant kimliği İZİNLİ")

    # samples doğrulaması
    for name in ("org-clean.json", "org-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        bt = count_by_type(snap["units"])
        chk([bt["brand"], bt["department"], bt["country"]] == exp.get("by_type"), f"{name} by_type={exp.get('by_type')}")
        chk(count_by_status(snap["units"])["active"] == exp.get("active_units"), f"{name} active_units={exp.get('active_units')}")
        chk(orphan_projects(snap["projects"], snap["units"]) == exp.get("orphans"), f"{name} orphans={exp.get('orphans')}")
        chk(assert_no_pii(snap) is None, f"{name} PII-free (HİJYEN)")

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

    units = [{"id": "A", "type": "brand", "parentId": None, "status": "active"}]
    # pozitif
    expect(count_by_type(units) == {"brand": 1, "department": 0, "country": 0}, "pos countByType")
    expect(count_by_status(units) == {"active": 1, "inactive": 0, "archived": 0}, "pos countByStatus")
    expect(root_units(units)[0]["id"] == "A", "pos rootUnits")
    expect(children_of(units, "A") == [], "pos childrenOf boş")
    expect(orphan_projects([], units) == [], "pos orphan boş → []")
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(assert_no_pii({"projects": [{"callerId": "x"}]}) is not None, "neg callerId yakalanır")
    expect(orphan_projects([{"id": "Z", "brandRef": "NO", "departmentRef": None, "countryRef": None}], units) == ["Z"], "neg öksüz yakalanır")
    expect(unit_status_tone("archived") == "neutral", "neg arşivli → neutral")
    expect(project_status_tone("paused") == "warning", "neg duraklatıldı → warning")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 40, "spec ≥40 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "OrgStructureSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "units": [{"id": "str", "code": "str", "name": "str (tenant KENDİ org birimi — izinli)",
                       "type": "brand|department|country", "parentId": "str|null",
                       "status": "active|inactive|archived", "userCount": "int", "agentCount": "int"}],
            "projects": [{"id": "str", "code": "str", "name": "str",
                          "brandRef": "str|null", "departmentRef": "str|null", "countryRef": "str|null",
                          "status": "active|paused|archived", "agentCount": "int"}]
        },
        "hijyen": "FORBIDDEN_PII_KEYS dışı alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. tenantRef/tenantName + org birim/proje name/code izinli (tenant KENDİ konfigürasyonu)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t02_organization_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
