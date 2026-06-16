#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.2 — DEDICATED vs SHARED TENANT (L0) referans probe.

12. workstream'in (IAM & Erişim) TENANT İZOLASYON-SINIFI modülü ve F2-Should yeteneği. FR-TEN-005 ('Dedicated
tenant ve shared tenant seçenekleri desteklenmelidir') + SAD §13.1 (izolasyon modeli — shared mantıksal [tek
havuz + RLS + tenant KMS] / dedicated fiziksel-ayrılmış [ayrı namespace/cluster/region]) + ADR-006 ('shared (RLS)
varsayılan + dedicated opsiyon') + DB.md §5.1 (tenant.isolation_mode CHECK [shared/dedicated]) + §6 ('dedicated
modda da tenant RLS ... aynıdır') gereksinimlerini sahiplenir. 12.4.1 (tenant CRUD/provisioning) izolasyon
SINIFININ seçimi/sağlanmasını BU modüle DELEGE eder. İzolasyon sınıfını DETERMİNİSTİK, FAIL-CLOSED bir BAĞLAMA
(binding) kararı olarak modeller.

  IsolationRequest ─malformed─► realm/plane ─► authz ─► mode_surface ─► dedicated_sep ─► rls ─► kms ─► residency ─► audit
        │              │            │             │             │           │        │          │           │       │
        │   ├─ request_id/op/realm/plane/isolation_mode eksik|geçersiz ──────────────────────────► REJECT(malformed)
        │   ├─ ¬(platform ∧ platform_control_plane) ───────────────► REJECT  [commit ⇒ cross_realm_op          R2]
        │   ├─ tenant:provision ∉ actor_permissions ──────────────► REJECT  [commit ⇒ unauthorized_op         R3]
        │   ├─ ¬valid_mode_surface(mode,placement,migrate) ───────► REJECT  [commit ⇒ mode_surface_mismatch   R4]
        │   ├─ dedicated ∧ placement=shared_pool ─────────────────► REJECT  [commit ⇒ dedicated_in_shared_pool R5]
        │   ├─ ¬rls_enabled ─────────────────────────────────────► REJECT  [commit ⇒ rls_waived              R6]
        │   ├─ ¬kms_distinct ────────────────────────────────────► REJECT  [commit ⇒ shared_kms_key          R7]
        │   ├─ surface_region≠home_region ───────────────────────► REJECT  [commit ⇒ residency_mismatch      R8]
        │   └─ mutating ∧ ¬audit ────────────────────────────────► REJECT  [commit ⇒ missing_audit           R9]
        └─ tümü geçer ──────────────────────────────────────────► COMMIT

ÇEKİRDEK: (1) R2 REALM İZOLASYONU (FR-IAM-008 altın kural) — izolasyon sınıfı seçimi YALNIZ platform realm +
platform_control_plane (cross_realm_op=0); (2) R3 YETKİLENDİRME — op tenant:provision gerektirir
(unauthorized_op=0); (3) R4 MOD→YÜZEY BAĞLAMASI — isolation_mode ∈{shared,dedicated} + yüzey moda eşlenir + migrate
korumalı (ADR-006, SAD §13.1; mode_surface_mismatch=0); (4) R5 DEDICATED AYRIM — dedicated shared havuza yerleşemez
(SAD §13.1; dedicated_in_shared_pool=0); (5) R6 RLS HER İKİ MODDA — dedicated RLS'i kaldırmaz (DB.md §6;
rls_waived=0); (6) R7 TENANT-BAŞINA KMS — her iki modda tenant kendi anahtarı (NFR 10.6; shared_kms_key=0); (7) R8
RESIDENCY TUTARLILIĞI — surface==home_region (NFR 10.7; residency_mismatch=0); (8) R9 WORM AUDIT — her mutasyon
audit_log'a (missing_audit=0). Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK; model_hash sha256). Her karar
terminal (R1) + kanıt + model bütünlük manifesti (R10); metrik düşük-kardinalite + ham PII yok (R11); model/spec/
sample ham içerik/PII/credential (kms key materyali) tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): tenant CRUD + yaşam döngüsü → 12.4.1; RLS çalışma-anı çift-kontrol →
12.2.3; tenant içi org (L1) → 12.4.3; tenant tercih (L1) → 12.4.4; rol→permission-key bundle → 12.1.1; permission
katalog → 12.1.2; WORM audit AKIŞI → 12.1.8; repo/grant bağımsızlık → 12.2.4; kaynak kotası → FR-TEN-006/007;
dedicated faturalama → WBS 15; migrate cutover/veri taşıma → F1 kod + ops runbook; IaC namespace/cluster sağlama →
0.4.2/0.4.3. KAYNAK DOĞRULUK; çelişkide FR-TEN-005 / SAD §13.1 / ADR-006 / DB.md §5.1 esastır.

Kullanım:
  tenant_isolation_probe.py validate          Statik model + spec + 12.4.1/12.2.3/12.1.1/12.1.2/12.2.4 resiprokal → çıkış kodu
  tenant_isolation_probe.py check <sample>     İzolasyon-sınıfı karar motoru: senaryo(lar) → kapı (R1–R12)
  tenant_isolation_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  tenant_isolation_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve ham
içerik (PII / KMS key materyali) üretilmez/yazılmaz (fixture sentetik — yalnız op/mode/placement/realm/plane enum +
permission-key + region enum + yapısal tenant/request kimlik [slug] + kms_key_ref REFERANSI; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tenant-isolation-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "isolation-class-model.json")
LIFECYCLE_PATH = os.path.join(HERE, "..", "tenant-provisioning", "config", "tenant-lifecycle-model.json")
RLS_PATH = os.path.join(HERE, "..", "rls-double-check", "config", "rls-model.json")
PERM_CATALOG_PATH = os.path.join(HERE, "..", "permission-catalog", "config", "permission-catalog.json")
RBAC_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
REPO_INDEP_PATH = os.path.join(HERE, "..", "l0-repo-independence", "config", "repo-independence-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"COMMIT", "REJECT"}
ISOLATION_MODES = ["shared", "dedicated"]
DEFAULT_MODE = "shared"
OPERATIONS = ["assign", "provision_surface", "migrate", "read"]
MUTATING_OPS = {"assign", "provision_surface", "migrate"}
MODE_CHANGING_OPS = {"migrate"}
REALMS = ["platform", "tenant"]
PLANES = ["platform_control_plane", "tenant_application_plane"]
REGIONS = ["UK", "EU", "NA", "ME"]
RUNTIME_PLACEMENTS = ["shared_pool", "dedicated_namespace", "dedicated_cluster"]
SHARED_POOL = "shared_pool"
DEDICATED_PLACEMENTS = {"dedicated_namespace", "dedicated_cluster"}
REQUIRED_PERM = "tenant:provision"
OP_PERMISSION = {
    "assign": REQUIRED_PERM, "provision_surface": REQUIRED_PERM,
    "migrate": REQUIRED_PERM, "read": REQUIRED_PERM,
}
RULES = ["realm_isolation", "authorization", "mode_surface_binding", "dedicated_separation",
         "rls_always_on", "per_tenant_kms", "residency_consistency", "worm_audit", "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU izolasyon-sınıfı kararını bozan müdahaleler (her biri unsafe koşulu + commit zorlar).
INJECTIONS = {"cross_realm", "drop_permission", "mode_mismatch", "ungoverned_migration",
              "dedicated_on_shared", "waive_rls", "share_kms", "residency_drift", "skip_audit",
              "model_tamper"}

VIOLATION_KEYS = [
    "cross_realm_op", "unauthorized_op", "mode_surface_mismatch", "dedicated_in_shared_pool",
    "rls_waived", "shared_kms_key", "residency_mismatch", "missing_audit",
    "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.1.x/12.2.x/12.4.1 deseniyle) — ham içerik/PII/KMS materyali/sır yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string|key[_-]?material)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*(PRIVATE KEY|KEY MATERIAL)-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name_value|customer_phone_value|transcript_text_value|kms_key_material_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|corr-|kms-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|tenant|platform|provision|shared|dedicated|UK|EU|NA|ME)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/KMS materyali/sır tarayıcı. Yorum/tarif satırı + enum + slug kimlik + key REFERANSI eler."""
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
    """Tek IsolationRequest senaryosunu yürüt → IsolationDecision + ihlal sayaçları.

    Motor DOĞRU izolasyon-sınıfı kararını hesaplar; inject (degrade) doğru davranışı bozar (unsafe koşulu + commit
    zorlar) ve eşleşen ihlal sayacını artırır (12.1.x/12.2.x/12.4.1 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    op = sample.get("op")
    actor_realm = sample.get("actor_realm", "platform")
    plane = sample.get("plane", "platform_control_plane")
    actor_permissions = list(sample.get("actor_permissions", []))
    tenant_id = sample.get("tenant_id")
    isolation_mode = sample.get("isolation_mode")
    current_mode = sample.get("current_mode")  # migrate için kaynak mod
    runtime_placement = sample.get("runtime_placement")
    rls_enabled = bool(sample.get("rls_enabled", True))
    kms_key_ref = sample.get("kms_key_ref")
    existing_kms_keys = set(sample.get("existing_kms_keys", []))
    surface_region = sample.get("surface_region")
    home_region = sample.get("home_region")
    migration_plan = sample.get("migration_plan")
    confirm = bool(sample.get("confirm", False))
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
        "isolation_modes": model.get("isolation_modes"),
        "operations": model.get("operations"),
        "op_permission": model.get("op_permission"),
        "surface_binding": model.get("surface_binding"),
        "rls": model.get("rls"),
        "kms": model.get("kms"),
        "residency": model.get("residency"),
        "migration": model.get("migration"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["rls"] = dict(tampered["rls"])
        tampered["rls"]["required_in_all_modes"] = False        # RLS'i opsiyonel yap (tahrifat)
        tampered["realm"] = dict(tampered["realm"])
        tampered["realm"]["required_actor_realm"] = "any"       # realm zorunluluğu kaldır (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    op_known = op in OPERATIONS
    realm_known = actor_realm in REALMS
    plane_known = plane in PLANES
    mode_known = isolation_mode in ISOLATION_MODES
    malformed = (not request_id or not op_known or not realm_known or not plane_known or not mode_known)

    if malformed:
        terminal, note, admit = "REJECT", "malformed", False
    else:
        required_perm = OP_PERMISSION.get(op)
        is_mutating = op in MUTATING_OPS
        is_migrate = (op == "migrate")

        # ── correct sub-evaluations (DOĞRU izolasyon-sınıfı kararı) ──
        realm_ok = (actor_realm == "platform" and plane == "platform_control_plane")
        authorized = (required_perm in actor_permissions)

        # mod→yüzey bağlaması (R4): yüzey moda eşlenmeli + migrate korumalı
        if isolation_mode == "shared":
            surface_binds = (runtime_placement == SHARED_POOL)
        elif isolation_mode == "dedicated":
            surface_binds = (runtime_placement in DEDICATED_PLACEMENTS)
        else:
            surface_binds = False
        # migrate (mod değişimi) migration_plan + confirm gerektirir
        migrate_guarded = True
        if is_migrate and (current_mode != isolation_mode):
            migrate_guarded = bool(migration_plan) and bool(confirm)
        mode_surface_ok = surface_binds and migrate_guarded

        # dedicated ayrım (R5): dedicated tenant shared havuzda olamaz
        dedicated_separated = True
        if isolation_mode == "dedicated":
            dedicated_separated = (runtime_placement != SHARED_POOL)

        # RLS her iki modda (R6)
        rls_ok = rls_enabled

        # tenant-başına KMS her iki modda (R7)
        kms_distinct = bool(kms_key_ref) and (kms_key_ref not in existing_kms_keys)

        # residency tutarlılığı (R8)
        residency_ok = bool(surface_region) and bool(home_region) and (surface_region == home_region)

        # WORM audit (mutasyon; R9)
        audit_ok = (not is_mutating) or audit_emitted

        # ── DOĞRU karar: tüm kapılar geçerse commit ──
        admit = (realm_ok and authorized and mode_surface_ok and dedicated_separated
                 and rls_ok and kms_distinct and residency_ok and audit_ok)

        # ── DEGRADE (inject) — unsafe koşulu + commit zorla; ihlali tetikle ──
        if "cross_realm" in inject:
            actor_realm = "tenant"                                  # tenant realm izolasyon sınıfı değiştiriyor
            realm_ok = False
            admit = True
        if "drop_permission" in inject:
            if required_perm in actor_permissions:
                actor_permissions.remove(required_perm)             # gerekli key kaldır
            authorized = False
            admit = True
        if "mode_mismatch" in inject:
            surface_binds = False                                   # yüzey moda eşlenmiyor
            mode_surface_ok = False
            admit = True
        if "ungoverned_migration" in inject and is_migrate:
            migrate_guarded = False                                 # plan/confirm yok sessiz flip
            mode_surface_ok = False
            admit = True
        if "dedicated_on_shared" in inject:
            isolation_mode = "dedicated"                            # dedicated mod
            runtime_placement = SHARED_POOL                         # ama shared havuzda
            dedicated_separated = False
            admit = True
        if "waive_rls" in inject:
            rls_enabled = False                                     # RLS kaldırıldı
            rls_ok = False
            admit = True
        if "share_kms" in inject:
            kms_distinct = False                                    # paylaşılan/çakışan key
            admit = True
        if "residency_drift" in inject:
            residency_ok = False                                    # surface_region ≠ home_region
            admit = True
        if "skip_audit" in inject and is_mutating:
            audit_emitted = False                                   # WORM audit yazılmadı
            audit_ok = False
            admit = True

        terminal = "COMMIT" if admit else "REJECT"

        # ── R2 realm izolasyonu: platform-dışı realm/plane commit ──
        if (not realm_ok) and admit:
            v["cross_realm_op"] += 1
        # ── R3 yetkilendirme: gerekli key olmadan commit ──
        if (not authorized) and admit:
            v["unauthorized_op"] += 1
        # ── R4 mod→yüzey bağlaması: geçersiz mod/yanlış yüzey/korumasız migrate commit ──
        if (not mode_surface_ok) and admit:
            v["mode_surface_mismatch"] += 1
        # ── R5 dedicated ayrım: dedicated shared havuzda commit ──
        if (not dedicated_separated) and admit:
            v["dedicated_in_shared_pool"] += 1
        # ── R6 RLS her iki modda: RLS kapalı commit ──
        if (not rls_ok) and admit:
            v["rls_waived"] += 1
        # ── R7 tenant-başına KMS: paylaşılan/boş key commit ──
        if (not kms_distinct) and admit:
            v["shared_kms_key"] += 1
        # ── R8 residency tutarlılığı: surface≠home_region commit ──
        if (not residency_ok) and admit:
            v["residency_mismatch"] += 1
        # ── R9 WORM audit: audit'siz mutasyon commit ──
        if is_mutating and (not audit_ok) and admit:
            v["missing_audit"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, op, actor_realm, plane, isolation_mode, runtime_placement,
                         terminal, note, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, admit, v, note, op, actor_realm, plane, isolation_mode,
                 runtime_placement, model_hash, evidence)


def _evidence(request_id, op, actor_realm, plane, isolation_mode, runtime_placement,
              terminal, note, model_hash):
    return {
        "request_id": request_id,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "isolation_mode": isolation_mode,
        "runtime_placement": runtime_placement,
        "terminal": terminal,
        "note": note,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, admit, v, note, op, actor_realm, plane, isolation_mode,
          runtime_placement, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "admit": admit,
        "note": note,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "isolation_mode": isolation_mode,
        "runtime_placement": runtime_placement,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "cross_realm_op": "max_cross_realm_op",
        "unauthorized_op": "max_unauthorized_op",
        "mode_surface_mismatch": "max_mode_surface_mismatch",
        "dedicated_in_shared_pool": "max_dedicated_in_shared_pool",
        "rls_waived": "max_rls_waived",
        "shared_kms_key": "max_shared_kms_key",
        "residency_mismatch": "max_residency_mismatch",
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
        for key in ("terminal", "admit", "note", "isolation_mode"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s admit=%s op=%s realm=%s mode=%s placement=%s note=%s"
              % (res["terminal"], res["admit"], res["op"], res["actor_realm"], res["isolation_mode"],
                 res["runtime_placement"], res["note"]))
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
    chk("wbs=12.4.2", spec.get("wbs") == "12.4.2")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Should", spec.get("priority") == "Should")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement deterministic=true", spec.get("placement", {}).get("deterministic") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEN-005 izlenir (ÇEKİRDEK — dedicated vs shared)", "FR-TEN-005" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (L0 altın kural — realm izolasyonu)", "FR-IAM-008" in tr.get("fr", []))
    chk("SR-TEN-005 izlenir", "SR-TEN-005" in tr.get("srs", []))
    chk("TC-TEN-005 izlenir (RTM)", "TC-TEN-005" in tr.get("rtm", []))
    chk("SAD §13.1 izlenir (izolasyon modeli)", any("§13.1" in s for s in tr.get("sad", [])))
    chk("ADR-006 izlenir (shared/dedicated izolasyon)", any(a.startswith("ADR-006") for a in tr.get("adr", [])))
    chk("ADR-011 izlenir (iki düzlemli panel)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("12.4.1 tenant-provisioning TÜKETİLİR (izolasyon sınıfı delege — resiprokal)",
        any("12.4.1" in s for s in tr.get("consumes", [])))
    chk("12.2.3 rls-double-check TÜKETİLİR (RLS her iki modda — resiprokal)",
        any("12.2.3" in s for s in tr.get("consumes", [])))
    chk("12.1.2 permission-catalog TÜKETİLİR (resiprokal)", any("12.1.2" in s for s in tr.get("consumes", [])))
    chk("12.1.1 rbac-model TÜKETİLİR (resiprokal)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.2.4 l0-repo-independence TÜKETİLİR (tenant=platform sınıf resiprokal)",
        any("12.2.4" in s for s in tr.get("consumes", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→realm→authz→mode_surface→dedicated→rls→kms→residency→audit",
        rz.get("evaluation") == "malformed_then_realm_isolation_then_authorization_then_mode_surface_binding_then_dedicated_separation_then_rls_always_on_then_per_tenant_kms_then_residency_consistency_then_worm_audit")
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
    chk("realm_layer platform + platform_control_plane",
        "platform" in en.get("realm_layer", "") and "platform_control_plane" in en.get("realm_layer", ""))
    chk("authz_layer op_permission (tenant:provision)", "tenant:provision" in en.get("authz_layer", ""))
    chk("binding_layer shared⇒shared_pool / dedicated⇒namespace,cluster",
        "shared_pool" in en.get("binding_layer", "") and "dedicated_cluster" in en.get("binding_layer", ""))
    chk("separation_layer dedicated shared havuza yerleşemez",
        "shared_pool" in en.get("separation_layer", ""))
    chk("rls_layer RLS her iki modda (DB.md §6)",
        "RLS" in en.get("rls_layer", "") and "§6" in en.get("rls_layer", ""))
    chk("kms_layer tenant başına KMS (NFR 10.6)",
        "KMS" in en.get("kms_layer", "") and "10.6" in en.get("kms_layer", ""))
    chk("residency_layer surface==home_region (NFR 10.7)", "10.7" in en.get("residency_layer", ""))
    chk("audit_layer WORM (12.1.8)", "WORM" in en.get("audit_layer", "") and "12.1.8" in en.get("audit_layer", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("isolation_modes shared/dedicated", set(md.get("isolation_modes", [])) == set(ISOLATION_MODES))
    chk("default_mode=shared (ADR-006)", md.get("default_mode") == DEFAULT_MODE)
    chk("operations tam (4)", set(md.get("operations", [])) == set(OPERATIONS))
    chk("mutating ops tam (3)", set(md.get("mutating_operations", [])) == MUTATING_OPS)
    chk("runtime_placements tam", set(md.get("valid_runtime_placements", [])) == set(RUNTIME_PLACEMENTS))
    chk("regions UK/EU/NA/ME (NFR 10.7)", set(md.get("regions", [])) == set(REGIONS))
    chk("required_actor_realm=platform", md.get("required_actor_realm") == "platform")
    chk("required_plane=platform_control_plane", md.get("required_plane") == "platform_control_plane")

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_cross_realm_op", "max_unauthorized_op", "max_mode_surface_mismatch",
               "max_dedicated_in_shared_pool", "max_rls_waived", "max_shared_kms_key",
               "max_residency_mismatch", "max_missing_audit", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("isolation_decision_total metrik", "isolation_decision_total" in obs.get("metrics", []))
    chk("isolation_violation_total metrik (alarm)", "isolation_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("tenant_id/request_id/kms_key_ref YÜKSEK kard (label değil)",
        all(x in hi for x in ("tenant_id", "request_id", "kms_key_ref"))
        and not any(x in lo for x in ("tenant_id", "request_id", "kms_key_ref")))
    chk("op/result/isolation_mode/runtime_placement DÜŞÜK kard",
        all(x in lo for x in ("op", "result", "isolation_mode", "runtime_placement")))
    chk("alarm dedicated_in_shared_pool/rls_waived/shared_kms_key ≤2dk",
        any(x in obs.get("alarm", "") for x in ("dedicated_in_shared_pool", "rls_waived", "shared_kms_key")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (FR-TEN-005 / SAD §13.1 / DB.md §5.1)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/isolation-class-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model isolation_modes shared/dedicated (DB.md §5.1 CHECK)",
            set(mm.get("isolation_modes", {}).get("list", [])) == set(ISOLATION_MODES))
        chk("model default mode=shared (ADR-006)", mm.get("isolation_modes", {}).get("default") == DEFAULT_MODE)
        chk("model operations tam (4)", set(mm.get("operations", {}).get("list", [])) == set(OPERATIONS))
        chk("model mutating ops (3)", set(mm.get("operations", {}).get("mutating", [])) == MUTATING_OPS)
        model_op_perm = {k: val for k, val in mm.get("op_permission", {}).items() if not k.startswith("$")}
        chk("model op_permission = OP_PERMISSION (tenant:provision)", model_op_perm == OP_PERMISSION)
        chk("model required_actor_realm=platform (FR-IAM-008)",
            mm.get("realm", {}).get("required_actor_realm") == "platform")
        chk("model required_plane=platform_control_plane (ADR-011)",
            mm.get("realm", {}).get("required_plane") == "platform_control_plane")
        sb = mm.get("surface_binding", {})
        chk("model surface_binding shared⇒shared_pool",
            sb.get("shared", {}).get("runtime") == ["shared_pool"])
        chk("model surface_binding dedicated⇒namespace/cluster",
            set(sb.get("dedicated", {}).get("runtime", [])) == DEDICATED_PLACEMENTS)
        chk("model shared rls_required + dedicated rls_required (DB.md §6)",
            sb.get("shared", {}).get("rls_required") is True and sb.get("dedicated", {}).get("rls_required") is True)
        chk("model RLS her iki modda zorunlu (DB.md §6)",
            mm.get("rls", {}).get("required_in_all_modes") is True)
        chk("model tenant başına KMS her iki modda (NFR 10.6)",
            mm.get("kms", {}).get("per_tenant_key_all_modes") is True)
        chk("model residency surface==home_region (NFR 10.7)",
            mm.get("residency", {}).get("surface_region_must_match_home_region") is True
            and set(mm.get("residency", {}).get("regions", [])) == set(REGIONS))
        chk("model migration plan+confirm (mod değişimi korumalı)",
            mm.get("migration", {}).get("requires_migration_plan") is True
            and mm.get("migration", {}).get("requires_confirm") is True)
        chk("model audit mutasyon op'ları (WORM)",
            set(mm.get("audit", {}).get("required_for", [])) == MUTATING_OPS
            and mm.get("audit", {}).get("worm") is True)
        chk("model dedicated ayrı faturalama (FR-BIL-005)",
            mm.get("billing", {}).get("dedicated_separately_billable") is True)
        chk("model isolation_mode data_class=platform (12.2.4 resiprokal)",
            mm.get("data_class", {}).get("isolation_class_table_class") == "platform")

    # 12) 12.4.1 RESİPROKAL — tenant-lifecycle-model isolation_modes shared/dedicated; izolasyon sınıfı delege
    lc_ok = os.path.exists(LIFECYCLE_PATH)
    chk("12.4.1 ../tenant-provisioning/config/tenant-lifecycle-model.json var (TÜKETİLİR)", lc_ok)
    if lc_ok:
        lc = _load(LIFECYCLE_PATH)
        chk("12.4.1 isolation_modes shared/dedicated (resiprokal)",
            set(lc.get("provisioning", {}).get("isolation_modes", [])) == set(ISOLATION_MODES))
        chk("12.4.1 tenant başına KMS (resiprokal R7)", lc.get("isolation", {}).get("per_tenant_kms_key") is True)

    # 13) 12.2.3 RESİPROKAL — RLS modeli mevcut (RLS her iki modda; dedicated RLS'i kaldırmaz)
    rls_ok = os.path.exists(RLS_PATH)
    chk("12.2.3 ../rls-double-check/config/rls-model.json var (RLS her iki modda — TÜKETİLİR)", rls_ok)
    if rls_ok:
        rls = _load(RLS_PATH)
        chk("12.2.3 RLS defense_in_depth + fail_closed (resiprokal R6)",
            rls.get("defense_in_depth") is not None and rls.get("fail_closed") is True)

    # 14) 12.1.2 RESİPROKAL — permission-catalog tenant:provision MEVCUT
    pc_ok = os.path.exists(PERM_CATALOG_PATH)
    chk("12.1.2 ../permission-catalog/config/permission-catalog.json var (TÜKETİLİR)", pc_ok)
    if pc_ok:
        pc_text = open(PERM_CATALOG_PATH, "r", encoding="utf-8").read()
        chk("12.1.2 tenant:provision permission-key kataloğda (resiprokal)", "tenant:provision" in pc_text)

    # 15) 12.1.1 RESİPROKAL — platform_owner bundle tenant:provision taşır
    rb_ok = os.path.exists(RBAC_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rb_ok)
    if rb_ok:
        rb = _load(RBAC_PATH)
        po = rb.get("roles", {}).get("platform_owner", {})
        chk("12.1.1 platform_owner L0 realm=platform", po.get("layer") == "L0" and po.get("realm") == "platform")
        chk("12.1.1 platform_owner tenant:provision taşır (resiprokal)",
            "tenant:provision" in po.get("permissions", []))

    # 16) 12.2.4 RESİPROKAL — tenant tablosu = platform sınıf
    ri_ok = os.path.exists(REPO_INDEP_PATH)
    chk("12.2.4 ../l0-repo-independence/config/repo-independence-model.json var (TÜKETİLİR)", ri_ok)
    if ri_ok:
        ri = _load(REPO_INDEP_PATH)
        chk("12.2.4 table_class_of.tenant = platform (resiprokal)",
            ri.get("table_class_of", {}).get("tenant") == "platform")

    # 17) Sır/PII tarayıcı — spec + model + samples
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

    # 18) Samples — ≥1 pass + ≥1 fail
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

    def shared_req(**kw):
        # Varsayılan: L0 platform shared assign (EU) → COMMIT, ihlal yok.
        d = {
            "request_id": "req-1", "op": "assign", "actor_realm": "platform",
            "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
            "tenant_id": "t-001", "isolation_mode": "shared", "runtime_placement": "shared_pool",
            "rls_enabled": True, "kms_key_ref": "kms-eu-001", "surface_region": "EU",
            "home_region": "EU", "audit_emitted": True,
        }
        d.update(kw)
        return d

    def dedicated_req(**kw):
        d = {
            "request_id": "req-d", "op": "provision_surface", "actor_realm": "platform",
            "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
            "tenant_id": "t-002", "isolation_mode": "dedicated", "runtime_placement": "dedicated_cluster",
            "rls_enabled": True, "kms_key_ref": "kms-me-014", "surface_region": "ME",
            "home_region": "ME", "audit_emitted": True,
        }
        d.update(kw)
        return d

    # 1) happy — shared assign → COMMIT, ihlal yok
    r = build(shared_req(), spec)
    case("happy: shared assign COMMIT", r["terminal"] == "COMMIT")
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) happy — dedicated provision → COMMIT
    r = build(dedicated_req(), spec)
    case("happy: dedicated provision COMMIT", r["terminal"] == "COMMIT")
    case("happy: dedicated ihlal yok + kapı geçer",
         all(x == 0 for x in r["violations"].values()) and _gate_eval(r, G)[0] is True)

    # 3) determinizm
    r1, r2 = build(shared_req(), spec), build(shared_req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 4) migrate happy (shared→dedicated; plan+confirm) → COMMIT
    r = build(dedicated_req(op="migrate", current_mode="shared", migration_plan="MP-001", confirm=True), spec)
    case("migrate happy: shared→dedicated (plan+confirm) COMMIT", r["terminal"] == "COMMIT")

    # 5) read (mutasyon değil; audit'siz) → COMMIT
    r = build(shared_req(op="read", audit_emitted=False), spec)
    case("read: audit'siz COMMIT (mutasyon değil)", r["terminal"] == "COMMIT")

    # ── DOĞRU REJECT'ler (ihlal yok — kapı geçer) ──

    # 6) R4 — shared modda dedicated yüzey DOĞRU reddedilir
    r = build(shared_req(runtime_placement="dedicated_cluster"), spec)
    case("mode_surface correct: shared+dedicated_cluster → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["mode_surface_mismatch"] == 0 and _gate_eval(r, G)[0] is True)

    # 7) R4 — korumasız migrate DOĞRU reddedilir
    r = build(dedicated_req(op="migrate", current_mode="shared", migration_plan=None, confirm=False), spec)
    case("migrate correct: plan/confirm yok → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["mode_surface_mismatch"] == 0 and _gate_eval(r, G)[0] is True)

    # 8) R5 — dedicated shared havuzda DOĞRU reddedilir
    r = build(dedicated_req(runtime_placement="shared_pool"), spec)
    case("dedicated_sep correct: dedicated+shared_pool → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["dedicated_in_shared_pool"] == 0 and _gate_eval(r, G)[0] is True)

    # 9) R6 — RLS kapalı DOĞRU reddedilir
    r = build(dedicated_req(rls_enabled=False), spec)
    case("rls correct: dedicated rls_enabled=false → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["rls_waived"] == 0 and _gate_eval(r, G)[0] is True)

    # 10) R8 — residency uyumsuz DOĞRU reddedilir
    r = build(shared_req(surface_region="NA", home_region="EU"), spec)
    case("residency correct: surface≠home → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["residency_mismatch"] == 0 and _gate_eval(r, G)[0] is True)

    # 11) R3 — yetkisiz DOĞRU reddedilir
    r = build(shared_req(actor_permissions=[]), spec)
    case("authz correct: yetkisiz → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unauthorized_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 12) R2 — tenant realm DOĞRU reddedilir
    r = build(shared_req(actor_realm="tenant", plane="tenant_application_plane"), spec)
    case("realm correct: tenant realm → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_realm_op"] == 0 and _gate_eval(r, G)[0] is True)

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 13) cross_realm
    r = build(shared_req(), spec, inject=["cross_realm"])
    case("cross_realm: cross_realm_op>0 + kapı eler",
         r["violations"]["cross_realm_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 14) drop_permission
    r = build(shared_req(), spec, inject=["drop_permission"])
    case("drop_permission: unauthorized_op>0 + kapı eler",
         r["violations"]["unauthorized_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 15) mode_mismatch
    r = build(shared_req(), spec, inject=["mode_mismatch"])
    case("mode_mismatch: mode_surface_mismatch>0 + kapı eler",
         r["violations"]["mode_surface_mismatch"] > 0 and _gate_eval(r, G)[0] is False)

    # 16) ungoverned_migration
    r = build(dedicated_req(op="migrate", current_mode="shared", migration_plan="MP", confirm=True), spec, inject=["ungoverned_migration"])
    case("ungoverned_migration: mode_surface_mismatch>0 + kapı eler",
         r["violations"]["mode_surface_mismatch"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) dedicated_on_shared
    r = build(dedicated_req(), spec, inject=["dedicated_on_shared"])
    case("dedicated_on_shared: dedicated_in_shared_pool>0 + kapı eler",
         r["violations"]["dedicated_in_shared_pool"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) waive_rls
    r = build(dedicated_req(), spec, inject=["waive_rls"])
    case("waive_rls: rls_waived>0 + kapı eler",
         r["violations"]["rls_waived"] > 0 and _gate_eval(r, G)[0] is False)

    # 19) share_kms
    r = build(shared_req(kms_key_ref="kms-shared", existing_kms_keys=["kms-shared"]), spec, inject=["share_kms"])
    case("share_kms: shared_kms_key>0 + kapı eler",
         r["violations"]["shared_kms_key"] > 0 and _gate_eval(r, G)[0] is False)
    # share_kms DOĞRU reddedilir (inject'siz çakışan key) — ihlal yok
    r = build(shared_req(kms_key_ref="kms-x", existing_kms_keys=["kms-x"]), spec)
    case("share_kms correct: çakışan key inject'siz → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["shared_kms_key"] == 0 and _gate_eval(r, G)[0] is True)

    # 20) residency_drift
    r = build(shared_req(), spec, inject=["residency_drift"])
    case("residency_drift: residency_mismatch>0 + kapı eler",
         r["violations"]["residency_mismatch"] > 0 and _gate_eval(r, G)[0] is False)

    # 21) skip_audit
    r = build(shared_req(), spec, inject=["skip_audit"])
    case("skip_audit: missing_audit>0 + kapı eler",
         r["violations"]["missing_audit"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) model_tamper
    r = build(shared_req(), spec, inject=["model_tamper"])
    case("model_tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) malformed → REJECT
    case("malformed-noreq: REJECT", build(shared_req(request_id=None), spec)["note"] == "malformed")
    case("malformed-noop: REJECT", build(shared_req(op="bogus"), spec)["note"] == "malformed")
    case("malformed-badmode: REJECT", build(shared_req(isolation_mode="hybrid"), spec)["note"] == "malformed")

    # 24) evidence + leak
    r = build(dedicated_req(), spec)
    case("evidence: request+op+realm+plane+mode+placement+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "op", "actor_realm", "plane", "isolation_mode",
                                          "runtime_placement", "model_hash")))
    case("evidence: ham PII/key materyali alanı yok",
         all(k not in json.dumps(r) for k in ("customer_name_value", "kms_key_material_value", "connection_string_value")))
    case("leak: op+mode+placement+realm+region+key-ref temiz",
         scan_leaks('{"op":"assign","isolation_mode":"dedicated","runtime_placement":"dedicated_cluster","actor_realm":"platform","surface_region":"ME","kms_key_ref":"kms-me-014"}') == [])
    case("leak: kms_key_material_value alanı yakalanır", len(scan_leaks('{"kms_key_material_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "tenant-isolation-class (WBS 12.4.2 — Dedicated vs shared tenant; FR-TEN-005, SAD §13.1, ADR-006, DB.md §5.1/§6)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "isolation_modes": ISOLATION_MODES,
        "default_mode": DEFAULT_MODE,
        "operations": OPERATIONS,
        "mutating_operations": sorted(MUTATING_OPS),
        "op_permission": OP_PERMISSION,
        "valid_runtime_placements": RUNTIME_PLACEMENTS,
        "regions": REGIONS,
        "decision": "malformed ⇒ REJECT(malformed) → ¬(platform ∧ platform_control_plane) ⇒ REJECT [commit ⇒ cross_realm_op] → "
                    "tenant:provision ∉ actor_permissions ⇒ REJECT [commit ⇒ unauthorized_op] → "
                    "¬valid_mode_surface(mode,placement,migrate) ⇒ REJECT [commit ⇒ mode_surface_mismatch] → "
                    "dedicated ∧ placement=shared_pool ⇒ REJECT [commit ⇒ dedicated_in_shared_pool] → "
                    "¬rls_enabled ⇒ REJECT [commit ⇒ rls_waived] → "
                    "¬kms_distinct ⇒ REJECT [commit ⇒ shared_kms_key] → "
                    "surface_region≠home_region ⇒ REJECT [commit ⇒ residency_mismatch] → "
                    "mutating ∧ ¬audit ⇒ REJECT [commit ⇒ missing_audit] → COMMIT",
        "default": "REJECT (fail-closed)",
        "fail_safe": "terminal=REJECT ⇒ izolasyon sınıfı atanmaz/sağlanmaz/değişmez; malformed/yetkisiz/uyumsuz-yüzey/RLS-kaldırma/residency-uyumsuz ⇒ REJECT",
        "core_guarantees": [
            "R2 realm izolasyonu: izolasyon sınıfı seçimi YALNIZ platform realm + platform_control_plane (FR-IAM-008; ADR-011); cross_realm_op=0",
            "R3 yetkilendirme: op tenant:provision gerektirir (12.1.2; platform_owner 12.1.1); unauthorized_op=0",
            "R4 mod→yüzey bağlaması: isolation_mode ∈{shared,dedicated} + yüzey moda eşlenir (shared⇒shared_pool / dedicated⇒namespace,cluster) + migrate korumalı (ADR-006, SAD §13.1); mode_surface_mismatch=0",
            "R5 dedicated ayrım: dedicated tenant shared havuza yerleşemez (SAD §13.1 fiziksel/ayrılmış); dedicated_in_shared_pool=0",
            "R6 RLS her iki modda: dedicated RLS'i kaldırmaz (DB.md §6; 12.2.3); rls_waived=0",
            "R7 tenant-başına KMS: her iki modda tenant kendi anahtarı (NFR 10.6; FR-TEN-002); shared_kms_key=0",
            "R8 residency tutarlılığı: surface_region == home_region (NFR 10.7); residency_mismatch=0",
            "R9 WORM audit: her mutasyon audit_log'a (FR-REC-009/FR-IAM-006; 12.1.8); missing_audit=0",
        ],
        "request_fields": ["name", "request_id", "op(assign|provision_surface|migrate|read)",
                           "actor_realm(platform|tenant)", "plane(platform_control_plane|tenant_application_plane)",
                           "actor_permissions[]", "tenant_id", "isolation_mode(shared|dedicated)", "current_mode",
                           "runtime_placement(shared_pool|dedicated_namespace|dedicated_cluster)", "rls_enabled(bool)",
                           "kms_key_ref", "existing_kms_keys[]", "surface_region(UK|EU|NA|ME)", "home_region(UK|EU|NA|ME)",
                           "migration_plan", "confirm(bool)", "audit_emitted(bool)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(COMMIT|REJECT)", "admit", "note", "op", "actor_realm", "plane",
                            "isolation_mode", "runtime_placement", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/isolation-class-model.json (frozen — isolation_modes[shared default/dedicated] + operations[4; mutating 3] "
                 "+ op_permission[tenant:provision] + surface_binding[shared⇒shared_pool+RLS / dedicated⇒namespace,cluster] "
                 "+ rls[her iki modda zorunlu] + kms[her iki modda tenant başına] + residency[surface==home_region; UK/EU/NA/ME] "
                 "+ migration[plan+confirm] + audit[WORM])",
        "consumes": "12.4.1 tenant-provisioning (isolation_modes + tenant KMS; izolasyon sınıfı delege — RESİPROKAL); "
                    "12.2.3 rls-double-check (RLS her iki modda — RESİPROKAL R6); "
                    "12.1.2 permission-catalog (tenant:provision MEVCUT — RESİPROKAL); "
                    "12.1.1 rbac-model (platform_owner bundle — RESİPROKAL); "
                    "12.2.4 l0-repo-independence (table_class_of.tenant=platform — RESİPROKAL); "
                    "FR-TEN-005 + SAD §13.1 + ADR-006 + DB.md §5.1/§6 (kaynak doğruluk)",
        "consumed_by": "1.x F1 kod (IaC namespace/cluster [0.4.2/0.4.3] + RLS politikası + KMS tahsisi + migrate cutover); "
                       "12.4.3 org yapısı (L1) + 12.4.4 tenant tercihleri (L1); WBS 15 billing (dedicated ayrı faturalama); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-TEN-005, FR-TEN-002, SAD §13.1, ADR-006, DB.md §5.1/§6, NFR 10.6/10.7, FR-BIL-005, 12.4.1/12.2.3/12.1.1/12.1.2/12.2.4/12.1.8",
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
            print("kullanım: tenant_isolation_probe.py check <sample.json|dizin>")
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
