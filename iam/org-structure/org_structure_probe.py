#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.3 — ORG YAPISI (marka/departman/ülke/proje) (L1) referans probe.

12. workstream'in (IAM & Erişim) TENANT İÇİ ORG-YAPISI modülü ve F1-Must yeteneği. FR-TEN-003 ('Tenant altında
marka, departman, ülke ve proje yapıları oluşturulabilmelidir') + DB.md §5.1 (organisation_unit — self-ref
hiyerarşi; type CHECK IN brand/country/department/project; region residency override; UNIQUE (tenant_id,parent_id,
name)) + BRD §17 ('Tenant içi organizasyon yapısı (marka/departman/ülke/proje, FR-TEN-003) ... Tenant Admin
Console (L1) üzerinden yönetilir') + SAD §14.4 (scoped assignment scope {brand|department|campaign}) + SR-TEN-003
gereksinimlerini sahiplenir. ÇEKİRDEK FARK: bu L1 (tenant realm + tenant_application_plane) yüzeyidir — 12.4.1
(tenant CRUD) ve 12.4.2 (dedicated vs shared) L0 (platform) iken bu L1. Org-yapısını DETERMİNİSTİK, FAIL-CLOSED
bir BAĞLAMA (binding) kararı olarak modeller.

  OrgRequest ─malformed─► tenant_isolation ─► authz ─► type ─► hierarchy ─► uniqueness ─► residency ─► delete_guard ─► audit
        │       │              │               │        │          │             │             │            │           │
        │   ├─ request_id/op/realm/plane eksik|geçersiz | create'de name eksik ─────────────────► REJECT(malformed)
        │   ├─ ¬(tenant ∧ tenant_application_plane ∧ own_tenant) ─► REJECT [commit ⇒ cross_tenant_op       R2]
        │   ├─ org:manage ∉ actor_permissions ──────────────────► REJECT [commit ⇒ unauthorized_op        R3]
        │   ├─ type ∉ {brand,country,department,project} ───────► REJECT [commit ⇒ invalid_type           R4]
        │   ├─ ¬valid_hierarchy(parent,ancestors,depth) ───────► REJECT [commit ⇒ hierarchy_violation     R5]
        │   ├─ name ∈ sibling_names ────────────────────────────► REJECT [commit ⇒ duplicate_name          R6]
        │   ├─ region ∉ tenant_allowed ────────────────────────► REJECT [commit ⇒ residency_violation     R7]
        │   ├─ delete ∧ referenced ∧ ¬(cascade∧confirm) ───────► REJECT [commit ⇒ unsafe_delete           R8]
        │   └─ mutating ∧ ¬audit ──────────────────────────────► REJECT [commit ⇒ missing_audit           R9]
        └─ tümü geçer ─────────────────────────────────────────► COMMIT

ÇEKİRDEK: (1) R2 TENANT İZOLASYONU (FR-TEN-002) — org yönetimi YALNIZ tenant realm + tenant_application_plane (L1)
+ aktör kendi tenant'ı (cross_tenant_op=0); (2) R3 YETKİLENDİRME — op org:manage gerektirir (unauthorized_op=0);
(3) R4 TİP GEÇERLİLİĞİ — type ∈ {brand,country,department,project} (DB.md §5.1 CHECK; invalid_type=0); (4) R5
HİYERARŞİ BÜTÜNLÜĞÜ — döngüsüz + derinlik sınırlı (DB.md §5.1 self-ref; hierarchy_violation=0); (5) R6 KARDEŞ
BENZERSİZLİĞİ — UNIQUE (tenant_id,parent_id,name) (duplicate_name=0); (6) R7 RESIDENCY — region tenant izinli
bölgede (NFR 10.7; residency_violation=0); (7) R8 SİLME KORUMASI — çocuk/scope-referansı → cascade+confirm
(unsafe_delete=0); (8) R9 WORM AUDIT — her mutasyon audit_log'a (missing_audit=0). Motor DETERMİNİSTİK FAIL-CLOSED
(Date.now/random YOK; model_hash sha256). Her karar terminal (R1) + kanıt + model bütünlük manifesti (R10); metrik
düşük-kardinalite + ham PII yok (R11); model/spec/sample ham içerik/PII/credential tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): tenant CRUD + yaşam döngüsü → 12.4.1; dedicated vs shared izolasyon
sınıfı → 12.4.2; tenant tercih (L1) → 12.4.4; scoped role assignment ÇÖZÜMÜ → 12.1.3; RLS çalışma-anı çift-kontrol
→ 12.2.3; rol→permission-key bundle → 12.1.1; permission katalog → 12.1.2; WORM audit AKIŞI → 12.1.8; repo/grant
bağımsızlık → 12.2.4; gerçek cascade/yeniden-atama (delete yürütme) → F1 kod + ops runbook; L1 OpenAPI/UI → 13.3.2.
KAYNAK DOĞRULUK; çelişkide FR-TEN-003 / DB.md §5.1 / BRD §17 / SAD §14.4 esastır.

Kullanım:
  org_structure_probe.py validate          Statik model + spec + 12.1.3/12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 resiprokal → çıkış kodu
  org_structure_probe.py check <sample>     Org-yapısı karar motoru: senaryo(lar) → kapı (R1–R12)
  org_structure_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  org_structure_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve ham
içerik (PII) üretilmez/yazılmaz (fixture sentetik — yalnız op/type/realm/plane enum + permission-key + region enum
+ yapısal tenant/org_unit/request kimlik [slug] + sentetik org adı; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "org-structure-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "org-structure-model.json")
SCOPE_PATH = os.path.join(HERE, "..", "scoped-assignment", "config", "scope-model.json")
PERM_CATALOG_PATH = os.path.join(HERE, "..", "permission-catalog", "config", "permission-catalog.json")
RBAC_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
RLS_PATH = os.path.join(HERE, "..", "rls-double-check", "config", "rls-model.json")
LIFECYCLE_PATH = os.path.join(HERE, "..", "tenant-provisioning", "config", "tenant-lifecycle-model.json")
REPO_INDEP_PATH = os.path.join(HERE, "..", "l0-repo-independence", "config", "repo-independence-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"COMMIT", "REJECT"}
ORG_TYPES = ["brand", "country", "department", "project"]
OPERATIONS = ["create", "update", "move", "delete", "read"]
MUTATING_OPS = {"create", "update", "move", "delete"}
NAME_SETTING_OPS = {"create", "update", "move"}
PARENTING_OPS = {"create", "move"}
TYPE_OPS = {"create"}
REALMS = ["platform", "tenant"]
PLANES = ["platform_control_plane", "tenant_application_plane"]
REGIONS = ["UK", "EU", "NA", "ME"]
MAX_DEPTH = 8
REQUIRED_PERM = "org:manage"
OP_PERMISSION = {
    "create": REQUIRED_PERM, "update": REQUIRED_PERM, "move": REQUIRED_PERM,
    "delete": REQUIRED_PERM, "read": REQUIRED_PERM,
}
RULES = ["tenant_isolation", "authorization", "type_validity", "hierarchy_integrity",
         "sibling_uniqueness", "residency_consistency", "delete_guard", "worm_audit", "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU org-yapısı kararını bozan müdahaleler (her biri unsafe koşulu + commit zorlar).
INJECTIONS = {"cross_tenant", "wrong_realm", "drop_permission", "invalid_type", "hierarchy_cycle",
              "duplicate_name", "residency_drift", "unsafe_delete", "skip_audit", "model_tamper"}

VIOLATION_KEYS = [
    "cross_tenant_op", "unauthorized_op", "invalid_type", "hierarchy_violation",
    "duplicate_name", "residency_violation", "unsafe_delete", "missing_audit",
    "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.1.x/12.2.x/12.4.x deseniyle) — ham içerik/PII/sır yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string|key[_-]?material)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*(PRIVATE KEY|KEY MATERIAL)-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name_value|customer_phone_value|transcript_text_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|ou-|u-|corr-|mp-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|tenant|platform|brand|country|department|project|UK|EU|NA|ME)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + enum + slug kimlik + sentetik org adı eler."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 16):m.end() + 16]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line \
                        or '"note"' in line or '"rule"' in line or '"rationale"' in line.lower() \
                        or line.strip().startswith('"$'):
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _canon_hash(obj):
    """Model bütünlük manifesti: sha256(kanonik JSON) — deterministik (sort_keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model():
    return _load(MODEL_PATH)


def build(sample, spec, inject=None, model=None):
    """Tek OrgRequest senaryosunu yürüt → OrgDecision + ihlal sayaçları.

    Motor DOĞRU org-yapısı kararını hesaplar; inject (degrade) doğru davranışı bozar (unsafe koşulu + commit
    zorlar) ve eşleşen ihlal sayacını artırır (12.1.x/12.2.x/12.4.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    op = sample.get("op")
    actor_realm = sample.get("actor_realm", "tenant")
    plane = sample.get("plane", "tenant_application_plane")
    actor_permissions = list(sample.get("actor_permissions", []))
    tenant_id = sample.get("tenant_id")
    org_unit_id = sample.get("org_unit_id")
    org_unit_tenant_id = sample.get("org_unit_tenant_id", tenant_id)  # hedef birimin tenant'ı
    org_type = sample.get("type")
    name = sample.get("name")
    parent_id = sample.get("parent_id")
    parent_tenant_id = sample.get("parent_tenant_id", tenant_id)  # ebeveynin tenant'ı (parent_id varsa)
    ancestor_ids = set(sample.get("ancestor_ids", []))            # yeni ebeveynin ata zinciri
    sibling_names = set(sample.get("sibling_names", []))          # hedef ebeveyn altındaki kardeş adları (kendisi hariç)
    region = sample.get("region")                                 # residency override (opsiyonel)
    tenant_allowed_regions = set(sample.get("tenant_allowed_regions", list(REGIONS)))
    has_children = bool(sample.get("has_children", False))
    referenced_by_scope = bool(sample.get("referenced_by_scope", False))
    cascade = bool(sample.get("cascade", False))
    confirm = bool(sample.get("confirm", False))
    depth = sample.get("depth", 0)
    audit_emitted = bool(sample.get("audit_emitted", True))

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    admit = False

    # ── R10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "realm": model.get("realm"),
        "org_types": model.get("org_types"),
        "operations": model.get("operations"),
        "op_permission": model.get("op_permission"),
        "tenant_scope": model.get("tenant_scope"),
        "hierarchy": model.get("hierarchy"),
        "uniqueness": model.get("uniqueness"),
        "residency": model.get("residency"),
        "delete_guard": model.get("delete_guard"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["tenant_scope"] = dict(tampered["tenant_scope"])
        tampered["tenant_scope"]["parent_must_be_same_tenant"] = False   # cross-tenant ebeveyne izin (tahrifat)
        tampered["hierarchy"] = dict(tampered["hierarchy"])
        tampered["hierarchy"]["no_cycle"] = False                        # döngü kontrolü kapat (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    op_known = op in OPERATIONS
    realm_known = actor_realm in REALMS
    plane_known = plane in PLANES
    create_needs_name = (op == "create" and not name)
    malformed = (not request_id or not op_known or not realm_known or not plane_known or create_needs_name)

    if malformed:
        terminal, note, admit = "REJECT", "malformed", False
    else:
        required_perm = OP_PERMISSION.get(op)
        is_mutating = op in MUTATING_OPS

        # ── correct sub-evaluations (DOĞRU org-yapısı kararı) ──
        # R2 tenant izolasyonu: L1 realm/plane + kendi tenant'ı + ebeveyn aynı tenant
        realm_ok = (actor_realm == "tenant" and plane == "tenant_application_plane")
        target_same_tenant = (org_unit_tenant_id == tenant_id) if (op != "create") else True
        parent_same_tenant = True
        if op in PARENTING_OPS and parent_id is not None:
            parent_same_tenant = (parent_tenant_id == tenant_id)
        scope_ok = bool(tenant_id) and realm_ok and target_same_tenant and parent_same_tenant

        # R3 yetkilendirme
        authorized = (required_perm in actor_permissions)

        # R4 tip geçerliliği (create)
        type_ok = (op not in TYPE_OPS) or (org_type in ORG_TYPES)

        # R5 hiyerarşi bütünlüğü (create/move)
        hierarchy_ok = True
        if op in PARENTING_OPS and parent_id is not None:
            not_self = (parent_id != org_unit_id)
            no_cycle = (org_unit_id is None) or (org_unit_id not in ancestor_ids)
            depth_ok = (isinstance(depth, int) and depth <= MAX_DEPTH)
            hierarchy_ok = not_self and no_cycle and depth_ok

        # R6 kardeş benzersizliği (create/update/move)
        uniqueness_ok = (op not in NAME_SETTING_OPS) or (name is None) or (name not in sibling_names)

        # R7 residency (region override; tenant izinli kümede)
        if region is None:
            residency_ok = True
        else:
            residency_ok = (region in REGIONS) and (region in tenant_allowed_regions)

        # R8 silme koruması (delete; çocuk/scope-referansı → cascade+confirm)
        delete_guard_ok = True
        if op == "delete" and (has_children or referenced_by_scope):
            delete_guard_ok = cascade and confirm

        # R9 WORM audit (mutasyon)
        audit_ok = (not is_mutating) or audit_emitted

        # ── DOĞRU karar: tüm kapılar geçerse commit ──
        admit = (scope_ok and authorized and type_ok and hierarchy_ok and uniqueness_ok
                 and residency_ok and delete_guard_ok and audit_ok)

        # ── DEGRADE (inject) — unsafe koşulu + commit zorla; ihlali tetikle ──
        if "cross_tenant" in inject:
            org_unit_tenant_id = "t-other"                           # başka tenant'ın birimi
            scope_ok = False
            admit = True
        if "wrong_realm" in inject:
            actor_realm = "platform"                                 # L0 platform L1 org op'u deniyor
            plane = "platform_control_plane"
            realm_ok = False
            scope_ok = False
            admit = True
        if "drop_permission" in inject:
            if required_perm in actor_permissions:
                actor_permissions.remove(required_perm)              # gerekli key kaldır
            authorized = False
            admit = True
        if "invalid_type" in inject:
            org_type = "franchise"                                   # CHECK dışı tip
            type_ok = False
            admit = True
        if "hierarchy_cycle" in inject:
            hierarchy_ok = False                                     # döngü / derinlik aşımı
            admit = True
        if "duplicate_name" in inject:
            uniqueness_ok = False                                    # kardeş ad çakışması
            admit = True
        if "residency_drift" in inject:
            residency_ok = False                                     # region tenant izinli dışı
            admit = True
        if "unsafe_delete" in inject and op == "delete":
            has_children = True                                      # çocuğu var
            delete_guard_ok = False                                  # cascade/confirm yok
            admit = True
        if "skip_audit" in inject and is_mutating:
            audit_emitted = False                                    # WORM audit yazılmadı
            audit_ok = False
            admit = True

        terminal = "COMMIT" if admit else "REJECT"

        # ── R2 tenant izolasyonu: yanlış realm/plane VEYA cross-tenant commit ──
        if (not scope_ok) and admit:
            v["cross_tenant_op"] += 1
        # ── R3 yetkilendirme: gerekli key olmadan commit ──
        if (not authorized) and admit:
            v["unauthorized_op"] += 1
        # ── R4 tip geçerliliği: geçersiz tip commit ──
        if (not type_ok) and admit:
            v["invalid_type"] += 1
        # ── R5 hiyerarşi bütünlüğü: döngü/derinlik aşımı commit ──
        if (not hierarchy_ok) and admit:
            v["hierarchy_violation"] += 1
        # ── R6 kardeş benzersizliği: çakışan ad commit ──
        if (not uniqueness_ok) and admit:
            v["duplicate_name"] += 1
        # ── R7 residency: tenant izinli dışı region commit ──
        if (not residency_ok) and admit:
            v["residency_violation"] += 1
        # ── R8 silme koruması: korumasız silme commit ──
        if (not delete_guard_ok) and admit:
            v["unsafe_delete"] += 1
        # ── R9 WORM audit: audit'siz mutasyon commit ──
        if is_mutating and (not audit_ok) and admit:
            v["missing_audit"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, op, actor_realm, plane, org_type, terminal, note, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, admit, v, note, op, actor_realm, plane, org_type, model_hash, evidence)


def _evidence(request_id, op, actor_realm, plane, org_type, terminal, note, model_hash):
    return {
        "request_id": request_id,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "org_type": org_type,
        "terminal": terminal,
        "note": note,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, admit, v, note, op, actor_realm, plane, org_type, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "admit": admit,
        "note": note,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "org_type": org_type,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "cross_tenant_op": "max_cross_tenant_op",
        "unauthorized_op": "max_unauthorized_op",
        "invalid_type": "max_invalid_type",
        "hierarchy_violation": "max_hierarchy_violation",
        "duplicate_name": "max_duplicate_name",
        "residency_violation": "max_residency_violation",
        "unsafe_delete": "max_unsafe_delete",
        "missing_audit": "max_missing_audit",
        "model_tampered": "max_model_tampered",
        "missing_evidence": "max_missing_evidence",
        "stuck_state": "max_stuck_state",
        "secret_or_pii": "max_secret_or_pii",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def check_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = build(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "admit", "note", "org_type"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s admit=%s op=%s realm=%s type=%s note=%s"
              % (res["terminal"], res["admit"], res["op"], res["actor_realm"], res["org_type"], res["note"]))
        nz = {k: val for k, val in res["violations"].items() if val}
        if nz:
            print("   ihlaller: %s" % nz)
        if expect == "pass" and fails:
            print("   ✗ kapı eler (beklenen geçer): %s" % "; ".join(fails))
        if expect == "fail" and passed:
            print("   ✗ kapı GEÇTİ (beklenen eler — degrade senaryo)")
        if mism and expect == "pass":
            print("   ✗ karar uyuşmazlığı: %s" % "; ".join(mism))
        if expect == "fail" and not passed:
            print("   ✓ beklendiği gibi elendi: %s" % "; ".join(fails[:3]))

    print("\ncheck: %s" % ("🟢 TÜM SENARYOLAR BEKLENDİĞİ GİBİ" if all_ok else "🔴 EN AZ BİR SENARYO BEKLENMEDİK"))
    return 0 if all_ok else 1


# ════════════════════════════════════════════════════════════════════════════
def validate():
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    spec = _load(SPEC_PATH)

    # 1) Üst-düzey alanlar
    for f in ("wbs", "phase", "priority", "trace", "placement", "rules", "decision",
              "outcomes", "model", "enforcement", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.4.3", spec.get("wbs") == "12.4.3")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement deterministic=true", spec.get("placement", {}).get("deterministic") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEN-003 izlenir (ÇEKİRDEK — org yapısı)", "FR-TEN-003" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-011 izlenir (scoped assignment bağı)", "FR-IAM-011" in tr.get("fr", []))
    chk("SR-TEN-003 izlenir", "SR-TEN-003" in tr.get("srs", []))
    chk("TC-TEN-003 izlenir (RTM)", "TC-TEN-003" in tr.get("rtm", []))
    chk("DB.md §5.1 izlenir (organisation_unit)", "§5.1" in spec.get("placement", {}).get("trace", ""))
    chk("BRD §17 izlenir (org yapısı L1)", any("§17" in s for s in tr.get("brd", [])))
    chk("SAD §14.4 izlenir (scoped assignment / T-02)", any("§14.4" in s for s in tr.get("sad", [])))
    chk("ADR-011 izlenir (iki düzlemli panel — L1)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("12.1.3 scoped-assignment TÜKETİLİR (org birimleri kapsam boyutu — resiprokal)",
        any("12.1.3" in s for s in tr.get("consumes", [])))
    chk("12.1.2 permission-catalog TÜKETİLİR (org:manage — resiprokal)",
        any("12.1.2" in s for s in tr.get("consumes", [])))
    chk("12.1.1 rbac-model TÜKETİLİR (tenant_owner/tenant_admin — resiprokal)",
        any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.2.3 rls-double-check TÜKETİLİR (organisation_unit RLS — resiprokal)",
        any("12.2.3" in s for s in tr.get("consumes", [])))
    chk("12.4.1 tenant-provisioning TÜKETİLİR (tenant izinli bölge — resiprokal)",
        any("12.4.1" in s for s in tr.get("consumes", [])))
    chk("12.2.4 l0-repo-independence TÜKETİLİR (organisation_unit=tenant sınıf — resiprokal)",
        any("12.2.4" in s for s in tr.get("consumes", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→tenant→authz→type→hierarchy→uniqueness→residency→delete→audit",
        rz.get("evaluation") == "malformed_then_tenant_isolation_then_authorization_then_type_validity_then_hierarchy_integrity_then_sibling_uniqueness_then_residency_consistency_then_delete_guard_then_worm_audit")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=REJECT (fail-closed)", dec.get("default") == "REJECT")
    chk("fail_safe no op", "no op" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar COMMIT/REJECT", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — katmanlar
    en = spec["enforcement"]
    chk("tenant_layer tenant + tenant_application_plane + kendi tenant'ı",
        "tenant" in en.get("tenant_layer", "") and "tenant_application_plane" in en.get("tenant_layer", ""))
    chk("authz_layer op_permission (org:manage)", "org:manage" in en.get("authz_layer", ""))
    chk("type_layer brand/country/department/project",
        all(t in en.get("type_layer", "") for t in ORG_TYPES))
    chk("hierarchy_layer döngüsüz + derinlik",
        "ancestor_ids" in en.get("hierarchy_layer", "") and "depth" in en.get("hierarchy_layer", ""))
    chk("uniqueness_layer UNIQUE (tenant_id,parent_id,name)",
        "UNIQUE" in en.get("uniqueness_layer", ""))
    chk("residency_layer region tenant izinli (NFR 10.7)",
        "10.7" in en.get("residency_layer", ""))
    chk("delete_layer cascade+confirm (12.1.3)",
        "cascade" in en.get("delete_layer", "") and "confirm" in en.get("delete_layer", ""))
    chk("audit_layer WORM (12.1.8)", "WORM" in en.get("audit_layer", "") and "12.1.8" in en.get("audit_layer", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("org_types brand/country/department/project", set(md.get("org_types", [])) == set(ORG_TYPES))
    chk("operations tam (5)", set(md.get("operations", [])) == set(OPERATIONS))
    chk("mutating ops tam (4)", set(md.get("mutating_operations", [])) == MUTATING_OPS)
    chk("regions UK/EU/NA/ME (NFR 10.7)", set(md.get("regions", [])) == set(REGIONS))
    chk("max_depth=%d" % MAX_DEPTH, md.get("max_depth") == MAX_DEPTH)
    chk("required_actor_realm=tenant (L1)", md.get("required_actor_realm") == "tenant")
    chk("required_plane=tenant_application_plane (L1)", md.get("required_plane") == "tenant_application_plane")

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_cross_tenant_op", "max_unauthorized_op", "max_invalid_type",
               "max_hierarchy_violation", "max_duplicate_name", "max_residency_violation",
               "max_unsafe_delete", "max_missing_audit", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("org_decision_total metrik", "org_decision_total" in obs.get("metrics", []))
    chk("org_violation_total metrik (alarm)", "org_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("tenant_id/org_unit_id/parent_id/request_id YÜKSEK kard (label değil)",
        all(x in hi for x in ("tenant_id", "org_unit_id", "parent_id", "request_id"))
        and not any(x in lo for x in ("tenant_id", "org_unit_id", "parent_id", "request_id")))
    chk("op/result/org_type DÜŞÜK kard",
        all(x in lo for x in ("op", "result", "org_type")))
    chk("alarm cross_tenant_op/unauthorized_op/unsafe_delete ≤2dk",
        any(x in obs.get("alarm", "") for x in ("cross_tenant_op", "unauthorized_op", "unsafe_delete")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (FR-TEN-003 / DB.md §5.1)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/org-structure-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model org_types brand/country/department/project (DB.md §5.1 CHECK)",
            set(mm.get("org_types", {}).get("list", [])) == set(ORG_TYPES))
        chk("model operations tam (5)", set(mm.get("operations", {}).get("list", [])) == set(OPERATIONS))
        chk("model mutating ops (4)", set(mm.get("operations", {}).get("mutating", [])) == MUTATING_OPS)
        model_op_perm = {k: val for k, val in mm.get("op_permission", {}).items() if not k.startswith("$")}
        chk("model op_permission = OP_PERMISSION (org:manage)", model_op_perm == OP_PERMISSION)
        chk("model required_actor_realm=tenant (L1; BRD §17)",
            mm.get("realm", {}).get("required_actor_realm") == "tenant")
        chk("model required_plane=tenant_application_plane (L1; ADR-011)",
            mm.get("realm", {}).get("required_plane") == "tenant_application_plane")
        chk("model tenant_scope kendi tenant + ebeveyn aynı tenant (FR-TEN-002)",
            mm.get("tenant_scope", {}).get("actor_tenant_must_match_target") is True
            and mm.get("tenant_scope", {}).get("parent_must_be_same_tenant") is True)
        chk("model hierarchy döngüsüz + max_depth (self-ref)",
            mm.get("hierarchy", {}).get("no_cycle") is True
            and mm.get("hierarchy", {}).get("max_depth") == MAX_DEPTH)
        chk("model uniqueness sibling_name_unique (UNIQUE (tenant_id,parent_id,name))",
            mm.get("uniqueness", {}).get("sibling_name_unique") is True)
        chk("model residency region tenant izinli + UK/EU/NA/ME (NFR 10.7; yalnız-daraltır)",
            mm.get("residency", {}).get("region_must_be_in_tenant_allowed") is True
            and mm.get("residency", {}).get("narrowing_only") is True
            and set(mm.get("residency", {}).get("regions", [])) == set(REGIONS))
        chk("model delete_guard cascade+confirm (çocuk/scope-referansı)",
            mm.get("delete_guard", {}).get("requires_cascade_and_confirm_when_referenced") is True
            and "scoped_assignment" in mm.get("delete_guard", {}).get("blocking_references", []))
        chk("model audit mutasyon op'ları (WORM)",
            set(mm.get("audit", {}).get("required_for", [])) == MUTATING_OPS
            and mm.get("audit", {}).get("worm") is True)
        chk("model scoped_assignment_link dimensions department/brand/campaign (12.1.3 resiprokal)",
            set(mm.get("scoped_assignment_link", {}).get("scope_dimensions", [])) == {"department", "brand", "campaign"})
        chk("model organisation_unit data_class=tenant_config (12.2.4 resiprokal)",
            mm.get("data_class", {}).get("org_unit_table_class") == "tenant_config")

    # 12) 12.1.3 RESİPROKAL — scoped-assignment dimensions brand/department (org birimleri kapsam boyutu)
    sc_ok = os.path.exists(SCOPE_PATH)
    chk("12.1.3 ../scoped-assignment/config/scope-model.json var (TÜKETİLİR)", sc_ok)
    if sc_ok:
        sc = _load(SCOPE_PATH)
        dims = set(sc.get("dimensions", []))
        chk("12.1.3 dimensions brand + department (org birimleri kapsam boyutu — resiprokal R8)",
            "brand" in dims and "department" in dims)

    # 13) 12.1.2 RESİPROKAL — permission-catalog org:manage MEVCUT (L1 Tenant Admin Console)
    pc_ok = os.path.exists(PERM_CATALOG_PATH)
    chk("12.1.2 ../permission-catalog/config/permission-catalog.json var (TÜKETİLİR)", pc_ok)
    if pc_ok:
        pc_text = open(PERM_CATALOG_PATH, "r", encoding="utf-8").read()
        chk("12.1.2 org:manage permission-key kataloğda (resiprokal R3)", "org:manage" in pc_text)

    # 14) 12.1.1 RESİPROKAL — tenant_owner/tenant_admin bundle org:manage taşır (L1 realm=tenant)
    rb_ok = os.path.exists(RBAC_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rb_ok)
    if rb_ok:
        rb = _load(RBAC_PATH)
        ta = rb.get("roles", {}).get("tenant_admin", {})
        chk("12.1.1 tenant_admin org:manage taşır (resiprokal R3)",
            "org:manage" in ta.get("permissions", []))
        chk("12.1.1 tenant_admin L1 realm=tenant",
            ta.get("realm") == "tenant" or ta.get("layer", "").startswith("L1"))

    # 15) 12.2.3 RESİPROKAL — RLS modeli mevcut (organisation_unit tenant-scoped RLS)
    rls_ok = os.path.exists(RLS_PATH)
    chk("12.2.3 ../rls-double-check/config/rls-model.json var (organisation_unit RLS — TÜKETİLİR)", rls_ok)
    if rls_ok:
        rls = _load(RLS_PATH)
        chk("12.2.3 RLS defense_in_depth + fail_closed (resiprokal R2)",
            rls.get("defense_in_depth") is not None and rls.get("fail_closed") is True)

    # 16) 12.4.1 RESİPROKAL — tenant-lifecycle mevcut (org birimleri sağlanmış tenant içinde)
    lc_ok = os.path.exists(LIFECYCLE_PATH)
    chk("12.4.1 ../tenant-provisioning/config/tenant-lifecycle-model.json var (TÜKETİLİR)", lc_ok)

    # 17) 12.2.4 RESİPROKAL — organisation_unit tablosu = tenant sınıf
    ri_ok = os.path.exists(REPO_INDEP_PATH)
    chk("12.2.4 ../l0-repo-independence/config/repo-independence-model.json var (TÜKETİLİR)", ri_ok)
    if ri_ok:
        ri = _load(REPO_INDEP_PATH)
        chk("12.2.4 table_class_of.organisation_unit = tenant_config (resiprokal)",
            ri.get("table_class_of", {}).get("organisation_unit") == "tenant_config")

    # 18) Sır/PII tarayıcı — spec + model + samples
    scan_files = [SPEC_PATH, MODEL_PATH] + (
        [os.path.join(SAMPLES_DIR, f) for f in os.listdir(SAMPLES_DIR) if f.endswith(".json")]
        if os.path.isdir(SAMPLES_DIR) else [])
    total_leaks = 0
    for p in scan_files:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            hits = scan_leaks(fh.read())
        if hits:
            total_leaks += len(hits)
            chk("sızıntı yok: %s" % os.path.basename(p), False, str(hits[:2]))
    chk("hiç ham-içerik/PII/sır sızıntısı yok (R12)", total_leaks == 0)

    # 19) Samples — ≥1 pass + ≥1 fail
    if os.path.isdir(SAMPLES_DIR):
        sample_files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
        chk("≥1 pass + ≥1 fail örnek (degrade ispatı)", _has_both(sample_files))

    npass = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        line = ("  ✓ " if ok else "  ✗ ") + name
        if not ok and detail:
            line += "  → " + detail
        print(line)
    total = len(checks)
    print("\nvalidate: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


def _has_both(sample_files):
    have_pass = have_fail = False
    for f in sample_files:
        s = _load(os.path.join(SAMPLES_DIR, f))
        if s.get("expect", "pass") == "pass":
            have_pass = True
        else:
            have_fail = True
    return have_pass and have_fail


# ════════════════════════════════════════════════════════════════════════════
def selftest():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    spec = _load(SPEC_PATH)
    G = spec["gates"]

    def create_req(**kw):
        # Varsayılan: L1 tenant create brand (root, EU) → COMMIT, ihlal yok.
        d = {
            "request_id": "req-1", "op": "create", "actor_realm": "tenant",
            "plane": "tenant_application_plane", "actor_permissions": ["org:manage"],
            "tenant_id": "t-001", "org_unit_id": "ou-new", "type": "brand", "name": "Marka-A",
            "parent_id": None, "region": "EU", "tenant_allowed_regions": ["EU", "UK"],
            "audit_emitted": True,
        }
        d.update(kw)
        return d

    def child_req(**kw):
        # Departman, marka altında (parent var) → COMMIT.
        d = {
            "request_id": "req-c", "op": "create", "actor_realm": "tenant",
            "plane": "tenant_application_plane", "actor_permissions": ["org:manage"],
            "tenant_id": "t-001", "org_unit_id": "ou-dep", "type": "department", "name": "Satis",
            "parent_id": "ou-brand", "parent_tenant_id": "t-001", "ancestor_ids": ["ou-brand"],
            "sibling_names": ["Pazarlama"], "depth": 2, "region": "EU",
            "tenant_allowed_regions": ["EU", "UK"], "audit_emitted": True,
        }
        d.update(kw)
        return d

    # 1) happy — create brand → COMMIT, ihlal yok
    r = build(create_req(), spec)
    case("happy: create brand COMMIT", r["terminal"] == "COMMIT")
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) happy — create department (child) → COMMIT
    r = build(child_req(), spec)
    case("happy: create department (child) COMMIT", r["terminal"] == "COMMIT")
    case("happy: child ihlal yok + kapı geçer",
         all(x == 0 for x in r["violations"].values()) and _gate_eval(r, G)[0] is True)

    # 3) determinizm
    r1, r2 = build(create_req(), spec), build(create_req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 4) read (mutasyon değil; audit'siz) → COMMIT
    r = build(create_req(op="read", org_unit_id="ou-001", audit_emitted=False), spec)
    case("read: audit'siz COMMIT (mutasyon değil)", r["terminal"] == "COMMIT")

    # 5) tüm dört tip create → COMMIT
    for t in ORG_TYPES:
        r = build(create_req(type=t, name="N-%s" % t), spec)
        case("type %s create COMMIT" % t, r["terminal"] == "COMMIT")

    # 6) region opsiyonel (yok) → COMMIT
    r = build(create_req(region=None), spec)
    case("region yok (devralınır) COMMIT", r["terminal"] == "COMMIT")

    # 7) delete (çocuksuz/referanssız) → COMMIT
    r = build(create_req(op="delete", org_unit_id="ou-leaf", has_children=False, referenced_by_scope=False), spec)
    case("delete leaf (referanssız) COMMIT", r["terminal"] == "COMMIT")

    # 8) delete (çocuklu + cascade+confirm) → COMMIT
    r = build(create_req(op="delete", org_unit_id="ou-mid", has_children=True, cascade=True, confirm=True), spec)
    case("delete (çocuklu + cascade+confirm) COMMIT", r["terminal"] == "COMMIT")

    # 9) move (korumalı; döngüsüz) → COMMIT
    r = build(child_req(op="move", org_unit_id="ou-dep", parent_id="ou-other", ancestor_ids=["ou-other"], sibling_names=[]), spec)
    case("move (döngüsüz) COMMIT", r["terminal"] == "COMMIT")

    # ── DOĞRU REJECT'ler (ihlal yok — kapı geçer) ──

    # 10) R4 — geçersiz tip DOĞRU reddedilir
    r = build(create_req(type="franchise"), spec)
    case("type correct: geçersiz tip → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["invalid_type"] == 0 and _gate_eval(r, G)[0] is True)

    # 11) R5 — döngü DOĞRU reddedilir (birim yeni ebeveyninin atası)
    r = build(child_req(op="move", org_unit_id="ou-dep", parent_id="ou-child", ancestor_ids=["ou-dep", "ou-x"]), spec)
    case("hierarchy correct: döngü → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["hierarchy_violation"] == 0 and _gate_eval(r, G)[0] is True)

    # 12) R5 — derinlik aşımı DOĞRU reddedilir
    r = build(child_req(depth=MAX_DEPTH + 1), spec)
    case("hierarchy correct: derinlik aşımı → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["hierarchy_violation"] == 0 and _gate_eval(r, G)[0] is True)

    # 13) R6 — ad çakışması DOĞRU reddedilir
    r = build(child_req(name="Pazarlama"), spec)  # sibling_names'te var
    case("uniqueness correct: ad çakışması → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["duplicate_name"] == 0 and _gate_eval(r, G)[0] is True)

    # 14) R7 — tenant izinli dışı region DOĞRU reddedilir
    r = build(create_req(region="NA", tenant_allowed_regions=["EU", "UK"]), spec)
    case("residency correct: izinli dışı region → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["residency_violation"] == 0 and _gate_eval(r, G)[0] is True)

    # 15) R8 — korumasız silme (çocuklu) DOĞRU reddedilir
    r = build(create_req(op="delete", org_unit_id="ou-mid", has_children=True, cascade=False, confirm=False), spec)
    case("delete_guard correct: çocuklu korumasız → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unsafe_delete"] == 0 and _gate_eval(r, G)[0] is True)
    r = build(create_req(op="delete", org_unit_id="ou-ref", referenced_by_scope=True, cascade=False, confirm=False), spec)
    case("delete_guard correct: scope-referanslı korumasız → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unsafe_delete"] == 0 and _gate_eval(r, G)[0] is True)

    # 16) R3 — yetkisiz DOĞRU reddedilir
    r = build(create_req(actor_permissions=[]), spec)
    case("authz correct: yetkisiz → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unauthorized_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 17) R2 — cross-tenant DOĞRU reddedilir (update başka tenant'ın birimi)
    r = build(create_req(op="update", org_unit_id="ou-x", org_unit_tenant_id="t-999"), spec)
    case("tenant correct: cross-tenant → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_tenant_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 18) R2 — platform realm DOĞRU reddedilir (L0 L1 org op'u)
    r = build(create_req(actor_realm="platform", plane="platform_control_plane"), spec)
    case("realm correct: platform realm → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_tenant_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 19) R2 — cross-tenant ebeveyn DOĞRU reddedilir
    r = build(child_req(parent_tenant_id="t-999"), spec)
    case("tenant correct: cross-tenant ebeveyn → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_tenant_op"] == 0 and _gate_eval(r, G)[0] is True)

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 20) cross_tenant
    r = build(create_req(op="update", org_unit_id="ou-x"), spec, inject=["cross_tenant"])
    case("cross_tenant: cross_tenant_op>0 + kapı eler",
         r["violations"]["cross_tenant_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 21) wrong_realm
    r = build(create_req(), spec, inject=["wrong_realm"])
    case("wrong_realm: cross_tenant_op>0 + kapı eler",
         r["violations"]["cross_tenant_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) drop_permission
    r = build(create_req(), spec, inject=["drop_permission"])
    case("drop_permission: unauthorized_op>0 + kapı eler",
         r["violations"]["unauthorized_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) invalid_type
    r = build(create_req(), spec, inject=["invalid_type"])
    case("invalid_type: invalid_type>0 + kapı eler",
         r["violations"]["invalid_type"] > 0 and _gate_eval(r, G)[0] is False)

    # 24) hierarchy_cycle
    r = build(child_req(op="move"), spec, inject=["hierarchy_cycle"])
    case("hierarchy_cycle: hierarchy_violation>0 + kapı eler",
         r["violations"]["hierarchy_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 25) duplicate_name
    r = build(create_req(), spec, inject=["duplicate_name"])
    case("duplicate_name: duplicate_name>0 + kapı eler",
         r["violations"]["duplicate_name"] > 0 and _gate_eval(r, G)[0] is False)

    # 26) residency_drift
    r = build(create_req(), spec, inject=["residency_drift"])
    case("residency_drift: residency_violation>0 + kapı eler",
         r["violations"]["residency_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 27) unsafe_delete
    r = build(create_req(op="delete", org_unit_id="ou-mid"), spec, inject=["unsafe_delete"])
    case("unsafe_delete: unsafe_delete>0 + kapı eler",
         r["violations"]["unsafe_delete"] > 0 and _gate_eval(r, G)[0] is False)

    # 28) skip_audit
    r = build(create_req(), spec, inject=["skip_audit"])
    case("skip_audit: missing_audit>0 + kapı eler",
         r["violations"]["missing_audit"] > 0 and _gate_eval(r, G)[0] is False)

    # 29) model_tamper
    r = build(create_req(), spec, inject=["model_tamper"])
    case("model_tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 30) malformed → REJECT
    case("malformed-noreq: REJECT", build(create_req(request_id=None), spec)["note"] == "malformed")
    case("malformed-noop: REJECT", build(create_req(op="bogus"), spec)["note"] == "malformed")
    case("malformed-noname: REJECT (create name yok)", build(create_req(name=None), spec)["note"] == "malformed")

    # 31) evidence + leak
    r = build(child_req(), spec)
    case("evidence: request+op+realm+plane+type+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "op", "actor_realm", "plane", "org_type", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("customer_name_value", "transcript_text_value", "connection_string_value")))
    case("leak: op+type+realm+region+slug temiz",
         scan_leaks('{"op":"create","type":"department","actor_realm":"tenant","region":"EU","org_unit_id":"ou-001","name":"Satis"}') == [])
    case("leak: connection_string_value alanı yakalanır", len(scan_leaks('{"connection_string_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "org-structure (WBS 12.4.3 — Org yapısı marka/departman/ülke/proje L1; FR-TEN-003, DB.md §5.1, BRD §17, SAD §14.4)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "org_types": ORG_TYPES,
        "operations": OPERATIONS,
        "mutating_operations": sorted(MUTATING_OPS),
        "op_permission": OP_PERMISSION,
        "regions": REGIONS,
        "max_depth": MAX_DEPTH,
        "required_actor_realm": "tenant",
        "required_plane": "tenant_application_plane",
        "decision": "malformed ⇒ REJECT(malformed) → ¬(tenant ∧ tenant_application_plane ∧ own_tenant) ⇒ REJECT [commit ⇒ cross_tenant_op] → "
                    "org:manage ∉ actor_permissions ⇒ REJECT [commit ⇒ unauthorized_op] → "
                    "type ∉ {brand,country,department,project} ⇒ REJECT [commit ⇒ invalid_type] → "
                    "¬valid_hierarchy(parent,ancestors,depth) ⇒ REJECT [commit ⇒ hierarchy_violation] → "
                    "name ∈ sibling_names ⇒ REJECT [commit ⇒ duplicate_name] → "
                    "region ∉ tenant_allowed ⇒ REJECT [commit ⇒ residency_violation] → "
                    "delete ∧ referenced ∧ ¬(cascade∧confirm) ⇒ REJECT [commit ⇒ unsafe_delete] → "
                    "mutating ∧ ¬audit ⇒ REJECT [commit ⇒ missing_audit] → COMMIT",
        "default": "REJECT (fail-closed)",
        "fail_safe": "terminal=REJECT ⇒ org birimi oluşturulmaz/güncellenmez/taşınmaz/silinmez; malformed/cross-tenant/yetkisiz/geçersiz-tip/döngü/ad-çakışması/residency-dışı/korumasız-silme ⇒ REJECT",
        "core_guarantees": [
            "R2 tenant izolasyonu: org yönetimi YALNIZ tenant realm + tenant_application_plane (L1) + kendi tenant'ı (FR-TEN-002; 12.2.3); cross_tenant_op=0",
            "R3 yetkilendirme: op org:manage gerektirir (12.1.2; tenant_owner/tenant_admin 12.1.1); unauthorized_op=0",
            "R4 tip geçerliliği: type ∈ {brand,country,department,project} (DB.md §5.1 CHECK; FR-TEN-003); invalid_type=0",
            "R5 hiyerarşi bütünlüğü: döngüsüz + derinlik ≤ max_depth (DB.md §5.1 self-ref); hierarchy_violation=0",
            "R6 kardeş benzersizliği: UNIQUE (tenant_id,parent_id,name) (DB.md §5.1); duplicate_name=0",
            "R7 residency: region tenant izinli bölgede + UK/EU/NA/ME (NFR 10.7; yalnız-daraltır); residency_violation=0",
            "R8 silme koruması: çocuk/scope-referansı → cascade+confirm (12.1.3); unsafe_delete=0",
            "R9 WORM audit: her mutasyon audit_log'a (FR-REC-009/FR-IAM-006; 12.1.8); missing_audit=0",
        ],
        "request_fields": ["name", "request_id", "op(create|update|move|delete|read)",
                           "actor_realm(platform|tenant)", "plane(platform_control_plane|tenant_application_plane)",
                           "actor_permissions[]", "tenant_id", "org_unit_id", "org_unit_tenant_id",
                           "type(brand|country|department|project)", "parent_id", "parent_tenant_id",
                           "ancestor_ids[]", "sibling_names[]", "region(UK|EU|NA|ME)", "tenant_allowed_regions[]",
                           "has_children(bool)", "referenced_by_scope(bool)", "cascade(bool)", "confirm(bool)",
                           "depth(int)", "audit_emitted(bool)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(COMMIT|REJECT)", "admit", "note", "op", "actor_realm", "plane",
                            "org_type", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/org-structure-model.json (frozen — org_types[brand/country/department/project] + operations[5; mutating 4] "
                 "+ op_permission[org:manage] + tenant_scope[kendi tenant + ebeveyn aynı tenant] + hierarchy[döngüsüz + max_depth] "
                 "+ uniqueness[UNIQUE (tenant_id,parent_id,name)] + residency[region tenant izinli; UK/EU/NA/ME] "
                 "+ delete_guard[çocuk/scope → cascade+confirm] + audit[WORM])",
        "consumes": "12.1.3 scoped-assignment (dimensions brand/department — org birimleri kapsam boyutu — RESİPROKAL R8); "
                    "12.1.2 permission-catalog (org:manage MEVCUT — RESİPROKAL R3); "
                    "12.1.1 rbac-model (tenant_owner/tenant_admin bundle — RESİPROKAL); "
                    "12.2.3 rls-double-check (organisation_unit tenant-scoped RLS — RESİPROKAL R2); "
                    "12.4.1 tenant-provisioning (tenant izinli bölge — RESİPROKAL R7); "
                    "12.2.4 l0-repo-independence (organisation_unit=tenant sınıf — RESİPROKAL); "
                    "FR-TEN-003 + DB.md §5.1 + BRD §17 + SAD §14.4 (kaynak doğruluk)",
        "consumed_by": "13.3.2 T-02 Organizasyon & Yapı (L1 UI/OpenAPI) + F1 kod (organisation_unit CRUD + cascade/yeniden-atama); "
                       "12.1.3 scoped-assignment (org birimleri kapsam boyutu; SR-TEN-003); 12.4.4 tenant tercihleri (L1); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-TEN-003, FR-TEN-002, DB.md §5.1, BRD §17, SAD §14.4, NFR 10.7, FR-IAM-011, 12.4.1/12.2.3/12.1.1/12.1.2/12.1.3/12.2.4/12.1.8",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "check":
        if len(argv) < 3:
            print("kullanım: org_structure_probe.py check <sample.json|dizin>")
            return 2
        return check_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
