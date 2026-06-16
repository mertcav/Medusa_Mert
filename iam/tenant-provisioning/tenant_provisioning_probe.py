#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.1 — TENANT CRUD + PROVISIONING (L0) referans probe.

12. workstream'in (IAM & Erişim) TENANT YAŞAM DÖNGÜSÜ modülü ve F1-Must yeteneği. FR-TEN-001 ('Platform birden
fazla kurumsal müşteriyi tenant bazında yönetmelidir') + BRD §17 ('tenant oluşturma/askıya alma/silme, plan
atama, kaynak kotası tanımı → Platform Admin Console (L0)') + DB.md §5.1 (tenant tablosu status CHECK
[provisioning/active/suspended/terminated] + isolation_mode + home_region + kms_key_ref) + §9 (geri döndürülemez
silme) gereksinimlerini sahiplenir. Tenant yaşam döngüsünü DETERMİNİSTİK, FAIL-CLOSED bir DURUM MAKİNESİ +
admission kararı olarak modeller.

  TenantOpRequest ─malformed─► realm/plane ─► authz ─► transition ─► provisioning ─► kms ─► idempotency ─► term ─► audit
        │              │            │           │          │             │            │          │           │       │
        │   ├─ request_id/op/realm/plane/current_status eksik|geçersiz ───────────────────────────────► REJECT(malformed)
        │   ├─ ¬(platform ∧ platform_control_plane) ──────────────────► REJECT  [commit ⇒ cross_realm_op       R2]
        │   ├─ required_perm ∉ actor_permissions ────────────────────► REJECT  [commit ⇒ unauthorized_op      R3]
        │   ├─ ¬valid_transition(op,current_status) ─────────────────► REJECT  [commit ⇒ invalid_transition   R4]
        │   ├─ create ∧ ¬provisioning_complete ──────────────────────► REJECT  [commit ⇒ incomplete_provisioning R5]
        │   ├─ create ∧ ¬kms_distinct ───────────────────────────────► REJECT  [commit ⇒ shared_kms_key       R6]
        │   ├─ create ∧ tenant_exists ───────────────────────────────► REJECT  [commit ⇒ duplicate_provision  R7]
        │   ├─ terminate ∧ ¬guarded ─────────────────────────────────► REJECT  [commit ⇒ unguarded_termination R8]
        │   └─ mutating ∧ ¬audit ────────────────────────────────────► REJECT  [commit ⇒ missing_audit        R9]
        └─ tümü geçer ──────────────────────────────────────────────► COMMIT

ÇEKİRDEK: (1) R2 REALM İZOLASYONU (FR-IAM-008 altın kural) — tenant lifecycle YALNIZ platform realm +
platform_control_plane (cross_realm_op=0); (2) R3 YETKİLENDİRME — op gerekli permission-key gerektirir
(tenant:provision/tenant:suspend; unauthorized_op=0); (3) R4 GEÇERLİ GEÇİŞ — durum makinesi (terminated terminal;
invalid_transition=0); (4) R5 PROVISIONING TAMLIĞI — zorunlu izolasyon/residency alanları + ilk durum provisioning
(incomplete_provisioning=0); (5) R6 TENANT-BAŞINA KMS (NFR 10.6) — her tenant kendi anahtarı (shared_kms_key=0);
(6) R7 İDEMPOTENT PROVISION (duplicate_provision=0); (7) R8 GERİ DÖNDÜRÜLEMEZ TERMINATE KORUMASI
(unguarded_termination=0); (8) R9 WORM AUDIT — her mutasyon audit_log'a (missing_audit=0). Motor DETERMİNİSTİK
FAIL-CLOSED (Date.now/random YOK; model_hash sha256). Her karar terminal (R1) + kanıt + model bütünlük manifesti
(R10); metrik düşük-kardinalite + ham PII yok (R11); model/spec/sample ham içerik/PII/credential (kms key
materyali) tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): dedicated/shared izolasyon SINIFI sağlanması → 12.4.2; tenant içi org
(marka/departman/ülke/proje, L1) → 12.4.3; tenant dil/saat/bölge/saklama TERCİHİ (L1) → 12.4.4; HTTP/RLS
çalışma-anı guard → 12.2.1/12.2.3; rol→permission-key bundle → 12.1.1; permission-key kataloğu → 12.1.2; WORM audit
AKIŞI → 12.1.8; repo/grant bağımsızlık → 12.2.4; kaynak kotası → FR-TEN-006/007; plan/billing → WBS 15; gerçek veri
silme → WBS 1.2.3. KAYNAK DOĞRULUK; çelişkide FR-TEN-001 / BRD §17 / DB.md §5.1 esastır.

Kullanım:
  tenant_provisioning_probe.py validate          Statik model + spec + 12.1.1/12.1.2/12.2.4/12.1.8 resiprokal → çıkış kodu
  tenant_provisioning_probe.py check <sample>     Tenant yaşam döngüsü karar motoru: senaryo(lar) → kapı (R1–R12)
  tenant_provisioning_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  tenant_provisioning_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve ham
içerik (PII / KMS key materyali) üretilmez/yazılmaz (fixture sentetik — yalnız op/status/realm/plane enum +
permission-key + region/isolation enum + yapısal tenant/request kimlik [slug] + kms_key_ref REFERANSI; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tenant-provisioning-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "tenant-lifecycle-model.json")
PERM_CATALOG_PATH = os.path.join(HERE, "..", "permission-catalog", "config", "permission-catalog.json")
RBAC_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
REPO_INDEP_PATH = os.path.join(HERE, "..", "l0-repo-independence", "config", "repo-independence-model.json")
WORM_PATH = os.path.join(HERE, "..", "worm-audit", "config", "worm-audit-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"COMMIT", "REJECT"}
STATUSES = ["provisioning", "active", "suspended", "terminated"]
TERMINAL_STATUSES = {"terminated"}
OPERATIONS = ["create", "read", "update", "activate", "suspend", "resume", "terminate"]
MUTATING_OPS = {"create", "update", "activate", "suspend", "resume", "terminate"}
IRREVERSIBLE_OPS = {"terminate"}
REALMS = ["platform", "tenant"]
PLANES = ["platform_control_plane", "tenant_application_plane"]
REGIONS = ["UK", "EU", "NA", "ME"]
ISOLATION_MODES = ["shared", "dedicated"]
REQUIRED_PROV_FIELDS = ["tenant_name", "home_region", "kms_key_ref", "isolation_mode",
                        "compliance_profile", "default_locale", "timezone"]
OP_PERMISSION = {
    "create": "tenant:provision", "read": "tenant:provision", "update": "tenant:provision",
    "activate": "tenant:provision", "terminate": "tenant:provision",
    "suspend": "tenant:suspend", "resume": "tenant:suspend",
}
RULES = ["realm_isolation", "authorization", "transition_validity", "provisioning_completeness",
         "per_tenant_kms", "idempotent_provision", "irreversible_termination_guard", "worm_audit",
         "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU yaşam döngüsü kararını bozan müdahaleler (her biri unsafe koşulu + commit zorlar).
INJECTIONS = {"cross_realm", "drop_permission", "invalid_transition", "skip_provisioning_field",
              "direct_active", "share_kms", "duplicate_provision", "unguard_termination", "skip_audit",
              "model_tamper"}

VIOLATION_KEYS = [
    "cross_realm_op", "unauthorized_op", "invalid_transition", "incomplete_provisioning",
    "shared_kms_key", "duplicate_provision", "unguarded_termination", "missing_audit",
    "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.1.x/12.2.x deseniyle) — ham içerik/PII/KMS materyali/sır yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string|key[_-]?material)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*(PRIVATE KEY|KEY MATERIAL)-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name_value|customer_phone_value|transcript_text_value|kms_key_material_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|corr-|kms-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|tenant|platform|provision|UK|EU|NA|ME)")


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


def _transition_index(model):
    """(op, from) → to lookup."""
    idx = {}
    for t in model.get("transitions", {}).get("list", []):
        idx[(t["op"], t["from"])] = t["to"]
    return idx


def build(sample, spec, inject=None, model=None):
    """Tek TenantOpRequest senaryosunu yürüt → TenantOpDecision + ihlal sayaçları.

    Motor DOĞRU yaşam döngüsü kararını hesaplar; inject (degrade) doğru davranışı bozar (unsafe koşulu + commit
    zorlar) ve eşleşen ihlal sayacını artırır (12.1.x/12.2.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    op = sample.get("op")
    actor_realm = sample.get("actor_realm", "platform")
    plane = sample.get("plane", "platform_control_plane")
    actor_permissions = list(sample.get("actor_permissions", []))
    current_status = sample.get("current_status")  # create için None
    tenant_id = sample.get("tenant_id")
    isolation_mode = sample.get("isolation_mode")
    kms_key_ref = sample.get("kms_key_ref")
    existing_kms_keys = set(sample.get("existing_kms_keys", []))
    tenant_exists = bool(sample.get("tenant_exists", False))
    initial_status = sample.get("initial_status", "provisioning")  # create ilk durum
    confirm_irreversible = bool(sample.get("confirm_irreversible", False))
    reason_code = sample.get("reason_code")
    audit_emitted = bool(sample.get("audit_emitted", True))

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    admit = False

    tidx = _transition_index(model)

    # ── R10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "realm": model.get("realm"),
        "statuses": model.get("statuses"),
        "operations": model.get("operations"),
        "op_permission": model.get("op_permission"),
        "transitions": model.get("transitions"),
        "provisioning": model.get("provisioning"),
        "isolation": model.get("isolation"),
        "termination": model.get("termination"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["realm"] = dict(tampered["realm"])
        tampered["realm"]["required_actor_realm"] = "any"          # realm zorunluluğu kaldır (tahrifat)
        tampered["statuses"] = dict(tampered["statuses"])
        tampered["statuses"]["terminal"] = []                      # terminated'ı terminal olmaktan çıkar (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    op_known = op in OPERATIONS
    realm_known = actor_realm in REALMS
    plane_known = plane in PLANES
    is_create = (op == "create")
    status_ok = (current_status is None) if is_create else (current_status in STATUSES)
    malformed = (not request_id or not op_known or not realm_known or not plane_known or not status_ok)

    if malformed:
        terminal, note, admit = "REJECT", "malformed", False
    else:
        required_perm = OP_PERMISSION.get(op)
        is_mutating = op in MUTATING_OPS

        # ── correct sub-evaluations (DOĞRU yaşam döngüsü kararı) ──
        realm_ok = (actor_realm == "platform" and plane == "platform_control_plane")
        authorized = (required_perm in actor_permissions)

        from_state = "none" if is_create else current_status
        target_status = tidx.get((op, from_state))
        transition_valid = target_status is not None

        # provisioning tamlığı (yalnız create)
        prov_complete = True
        if is_create:
            for f in REQUIRED_PROV_FIELDS:
                if not sample.get(f):
                    prov_complete = False
            if sample.get("home_region") not in REGIONS:
                prov_complete = False
            if isolation_mode not in ISOLATION_MODES:
                prov_complete = False
            if initial_status != model.get("provisioning", {}).get("initial_status_must_be", "provisioning"):
                prov_complete = False

        # tenant-başına KMS (yalnız create)
        kms_distinct = True
        if is_create:
            kms_distinct = bool(kms_key_ref) and (kms_key_ref not in existing_kms_keys)

        # idempotency (yalnız create)
        not_duplicate = not (is_create and tenant_exists)

        # geri döndürülemez terminate koruması
        term_guarded = True
        if op == "terminate":
            term_guarded = bool(confirm_irreversible) and bool(reason_code)

        # WORM audit (mutasyon)
        audit_ok = (not is_mutating) or audit_emitted

        # ── DOĞRU karar: tüm kapılar geçerse commit ──
        admit = (realm_ok and authorized and transition_valid and prov_complete
                 and kms_distinct and not_duplicate and term_guarded and audit_ok)

        # ── DEGRADE (inject) — unsafe koşulu + commit zorla; ihlali tetikle ──
        if "cross_realm" in inject:
            actor_realm = "tenant"                                 # tenant realm L0 lifecycle yürütüyor
            realm_ok = False
            admit = True
        if "drop_permission" in inject:
            if required_perm in actor_permissions:
                actor_permissions.remove(required_perm)            # gerekli key kaldır
            authorized = False
            admit = True
        if "invalid_transition" in inject:
            transition_valid = False                               # geçersiz geçiş zorla commit
            target_status = sample.get("forced_target", target_status)
            admit = True
        if "skip_provisioning_field" in inject and is_create:
            prov_complete = False                                  # zorunlu alan eksik
            admit = True
        if "direct_active" in inject and is_create:
            initial_status = "active"                              # provisioning iş akışını atla
            prov_complete = False
            admit = True
        if "share_kms" in inject and is_create:
            kms_distinct = False                                   # paylaşılan/çakışan key
            admit = True
        if "duplicate_provision" in inject and is_create:
            tenant_exists = True                                   # var olan tenant için ikinci create
            not_duplicate = False
            admit = True
        if "unguard_termination" in inject and op == "terminate":
            term_guarded = False                                   # confirm/gerekçe yok
            admit = True
        if "skip_audit" in inject and is_mutating:
            audit_emitted = False                                  # WORM audit yazılmadı
            audit_ok = False
            admit = True

        terminal = "COMMIT" if admit else "REJECT"

        # ── R2 realm izolasyonu: platform-dışı realm/plane lifecycle commit ──
        if (not realm_ok) and admit:
            v["cross_realm_op"] += 1
        # ── R3 yetkilendirme: gerekli key olmadan commit ──
        if (not authorized) and admit:
            v["unauthorized_op"] += 1
        # ── R4 geçiş geçerliliği: geçersiz durum geçişi commit ──
        if (not transition_valid) and admit:
            v["invalid_transition"] += 1
        # ── R5 provisioning tamlığı: eksik/doğrudan-active create commit ──
        if is_create and (not prov_complete) and admit:
            v["incomplete_provisioning"] += 1
        # ── R6 tenant-başına KMS: paylaşılan/boş key create commit ──
        if is_create and (not kms_distinct) and admit:
            v["shared_kms_key"] += 1
        # ── R7 idempotent provision: var olan tenant için create commit ──
        if is_create and (not not_duplicate) and admit:
            v["duplicate_provision"] += 1
        # ── R8 geri döndürülemez terminate koruması ──
        if op == "terminate" and (not term_guarded) and admit:
            v["unguarded_termination"] += 1
        # ── R9 WORM audit: audit'siz mutasyon commit ──
        if is_mutating and (not audit_ok) and admit:
            v["missing_audit"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── hedef durum (kanıt) ──
    if malformed:
        target_out = None
    elif op == "read" or op == "update":
        target_out = current_status
    elif is_create:
        target_out = initial_status if "direct_active" in inject else "provisioning"
    else:
        target_out = _transition_index(model).get((op, current_status))

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, op, actor_realm, plane, current_status, target_out,
                         isolation_mode, terminal, note, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, admit, v, note, op, actor_realm, plane, current_status,
                 target_out, isolation_mode, model_hash, evidence)


def _evidence(request_id, op, actor_realm, plane, current_status, target_status, isolation_mode,
              terminal, note, model_hash):
    return {
        "request_id": request_id,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "current_status": current_status,
        "target_status": target_status,
        "isolation_mode": isolation_mode,
        "terminal": terminal,
        "note": note,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, admit, v, note, op, actor_realm, plane, current_status, target_status,
          isolation_mode, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "admit": admit,
        "note": note,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "current_status": current_status,
        "target_status": target_status,
        "isolation_mode": isolation_mode,
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
        "invalid_transition": "max_invalid_transition",
        "incomplete_provisioning": "max_incomplete_provisioning",
        "shared_kms_key": "max_shared_kms_key",
        "duplicate_provision": "max_duplicate_provision",
        "unguarded_termination": "max_unguarded_termination",
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
        for key in ("terminal", "admit", "note", "target_status"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s admit=%s op=%s realm=%s cur=%s→tgt=%s note=%s"
              % (res["terminal"], res["admit"], res["op"], res["actor_realm"], res["current_status"],
                 res["target_status"], res["note"]))
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
    chk("wbs=12.4.1", spec.get("wbs") == "12.4.1")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement deterministic=true", spec.get("placement", {}).get("deterministic") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEN-001 izlenir (ÇEKİRDEK — tenant bazında yönetim)", "FR-TEN-001" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (L0 altın kural — realm izolasyonu)", "FR-IAM-008" in tr.get("fr", []))
    chk("BRD §17 izlenir (tenant lifecycle L0)", any("§17" in s for s in tr.get("brd", [])))
    chk("ADR-011 izlenir (iki düzlemli panel)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("ADR-012 izlenir (rol bundle)", any(a.startswith("ADR-012") for a in tr.get("adr", [])))
    chk("12.1.2 permission-catalog TÜKETİLİR (resiprokal)", any("12.1.2" in s for s in tr.get("consumes", [])))
    chk("12.1.1 rbac-model TÜKETİLİR (resiprokal)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.2.4 l0-repo-independence TÜKETİLİR (tenant=platform sınıf resiprokal)",
        any("12.2.4" in s for s in tr.get("consumes", [])))
    chk("12.1.8 worm-audit TÜKETİLİR (audit resiprokal)", any("12.1.8" in s for s in tr.get("consumes", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→realm→authz→transition→prov→kms→idempotency→term→audit",
        rz.get("evaluation") == "malformed_then_realm_isolation_then_authorization_then_transition_validity_then_provisioning_completeness_then_per_tenant_kms_then_idempotency_then_termination_guard_then_worm_audit")
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
    chk("authz_layer op_permission (tenant:provision/tenant:suspend)",
        "tenant:provision" in en.get("authz_layer", "") and "tenant:suspend" in en.get("authz_layer", ""))
    chk("fsm_layer terminated terminal", "terminated" in en.get("fsm_layer", ""))
    chk("provisioning_layer tenant başına KMS (NFR 10.6)",
        "KMS" in en.get("provisioning_layer", "") and "10.6" in en.get("provisioning_layer", ""))
    chk("termination_layer geri döndürülemez (DB.md §9)", "§9" in en.get("termination_layer", ""))
    chk("audit_layer WORM (12.1.8)", "WORM" in en.get("audit_layer", "") and "12.1.8" in en.get("audit_layer", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("statuses tam (4)", set(md.get("statuses", [])) == set(STATUSES))
    chk("terminated terminal status", set(md.get("terminal_statuses", [])) == TERMINAL_STATUSES)
    chk("operations tam (7)", set(md.get("operations", [])) == set(OPERATIONS))
    chk("mutating ops tam (6)", set(md.get("mutating_operations", [])) == MUTATING_OPS)
    chk("regions UK/EU/NA/ME (NFR 10.7)", set(md.get("regions", [])) == set(REGIONS))
    chk("isolation_modes shared/dedicated", set(md.get("isolation_modes", [])) == set(ISOLATION_MODES))
    chk("required_actor_realm=platform", md.get("required_actor_realm") == "platform")
    chk("required_plane=platform_control_plane", md.get("required_plane") == "platform_control_plane")

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_cross_realm_op", "max_unauthorized_op", "max_invalid_transition",
               "max_incomplete_provisioning", "max_shared_kms_key", "max_duplicate_provision",
               "max_unguarded_termination", "max_missing_audit", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("tenant_op_decision_total metrik", "tenant_op_decision_total" in obs.get("metrics", []))
    chk("tenant_lifecycle_violation_total metrik (alarm)", "tenant_lifecycle_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("tenant_id/request_id/kms_key_ref YÜKSEK kard (label değil)",
        all(x in hi for x in ("tenant_id", "request_id", "kms_key_ref"))
        and not any(x in lo for x in ("tenant_id", "request_id", "kms_key_ref")))
    chk("op/result/isolation_mode/target_status DÜŞÜK kard",
        all(x in lo for x in ("op", "result", "isolation_mode", "target_status")))
    chk("alarm cross_realm_op/unauthorized_op/shared_kms_key ≤2dk",
        any(x in obs.get("alarm", "") for x in ("cross_realm_op", "unauthorized_op", "shared_kms_key")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (FR-TEN-001 / DB.md §5.1)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/tenant-lifecycle-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model statuses = DB.md §5.1 CHECK (provisioning/active/suspended/terminated)",
            set(mm.get("statuses", {}).get("list", [])) == set(STATUSES))
        chk("model terminated terminal", mm.get("statuses", {}).get("terminal") == ["terminated"])
        chk("model operations tam (7)", set(mm.get("operations", {}).get("list", [])) == set(OPERATIONS))
        chk("model mutating ops (6)", set(mm.get("operations", {}).get("mutating", [])) == MUTATING_OPS)
        model_op_perm = {k: val for k, val in mm.get("op_permission", {}).items() if not k.startswith("$")}
        chk("model op_permission = OP_PERMISSION", model_op_perm == OP_PERMISSION)
        chk("model required_actor_realm=platform (FR-IAM-008)",
            mm.get("realm", {}).get("required_actor_realm") == "platform")
        chk("model required_plane=platform_control_plane (ADR-011)",
            mm.get("realm", {}).get("required_plane") == "platform_control_plane")
        chk("model required prov fields (DB.md §5.1 NOT NULL)",
            set(mm.get("provisioning", {}).get("required_fields", [])) == set(REQUIRED_PROV_FIELDS))
        chk("model regions UK/EU/NA/ME (NFR 10.7)",
            set(mm.get("provisioning", {}).get("regions", [])) == set(REGIONS))
        chk("model isolation_modes shared/dedicated (ADR-006)",
            set(mm.get("provisioning", {}).get("isolation_modes", [])) == set(ISOLATION_MODES))
        chk("model create ilk durum provisioning (doğrudan active değil)",
            mm.get("provisioning", {}).get("initial_status_must_be") == "provisioning")
        chk("model tenant başına KMS (NFR 10.6)", mm.get("isolation", {}).get("per_tenant_kms_key") is True)
        chk("model KMS paylaşımı yasak", mm.get("isolation", {}).get("kms_key_shared_forbidden") is True)
        chk("model terminate confirm + reason (DB.md §9)",
            mm.get("termination", {}).get("requires_confirm") is True
            and mm.get("termination", {}).get("requires_reason_code") is True)
        chk("model audit mutasyon op'ları (WORM)",
            set(mm.get("audit", {}).get("required_for", [])) == MUTATING_OPS
            and mm.get("audit", {}).get("worm") is True)
        chk("model tenant tablosu data_class=platform (12.2.4 resiprokal)",
            mm.get("data_class", {}).get("tenant_table_class") == "platform")
        # transition tablosu içsel tutarlılık
        tidx = _transition_index(mm)
        chk("transition create: none→provisioning", tidx.get(("create", "none")) == "provisioning")
        chk("transition activate: provisioning→active", tidx.get(("activate", "provisioning")) == "active")
        chk("transition suspend/resume: active↔suspended",
            tidx.get(("suspend", "active")) == "suspended" and tidx.get(("resume", "suspended")) == "active")
        chk("transition terminate: active/suspended/provisioning→terminated",
            all(tidx.get(("terminate", s)) == "terminated" for s in ("active", "suspended", "provisioning")))
        chk("transition terminated'dan çıkış YOK (terminal)",
            not any(k[1] == "terminated" and k[0] != "read" for k in tidx))

    # 12) 12.1.2 RESİPROKAL — permission-catalog tenant:provision + tenant:suspend MEVCUT
    pc_ok = os.path.exists(PERM_CATALOG_PATH)
    chk("12.1.2 ../permission-catalog/config/permission-catalog.json var (TÜKETİLİR)", pc_ok)
    if pc_ok:
        pc_text = open(PERM_CATALOG_PATH, "r", encoding="utf-8").read()
        chk("12.1.2 tenant:provision permission-key kataloğda (resiprokal)", "tenant:provision" in pc_text)
        chk("12.1.2 tenant:suspend permission-key kataloğda (resiprokal)", "tenant:suspend" in pc_text)

    # 13) 12.1.1 RESİPROKAL — platform_owner bundle tenant:provision + tenant:suspend taşır
    rb_ok = os.path.exists(RBAC_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rb_ok)
    if rb_ok:
        rb = _load(RBAC_PATH)
        po = rb.get("roles", {}).get("platform_owner", {})
        chk("12.1.1 platform_owner L0 realm=platform", po.get("layer") == "L0" and po.get("realm") == "platform")
        chk("12.1.1 platform_owner tenant:provision + tenant:suspend taşır (resiprokal)",
            "tenant:provision" in po.get("permissions", []) and "tenant:suspend" in po.get("permissions", []))

    # 14) 12.2.4 RESİPROKAL — tenant tablosu = platform sınıf; tenant_provisioning_repo PERMIT
    ri_ok = os.path.exists(REPO_INDEP_PATH)
    chk("12.2.4 ../l0-repo-independence/config/repo-independence-model.json var (TÜKETİLİR)", ri_ok)
    if ri_ok:
        ri = _load(REPO_INDEP_PATH)
        chk("12.2.4 table_class_of.tenant = platform (resiprokal)",
            ri.get("table_class_of", {}).get("tenant") == "platform")
        chk("12.2.4 tenant_provisioning_repo platform_control_plane (L0 yönetir)",
            ri.get("repositories", {}).get("tenant_provisioning_repo", {}).get("plane") == "platform_control_plane")

    # 15) 12.1.8 RESİPROKAL — worm-audit modeli mevcut (mutasyon → audit_log)
    wm_ok = os.path.exists(WORM_PATH)
    chk("12.1.8 ../worm-audit/config/worm-audit-model.json var (audit backstop — TÜKETİLİR)", wm_ok)

    # 16) Sır/PII tarayıcı — spec + model + samples
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

    # 17) Samples — ≥1 pass + ≥1 fail
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

    def req(**kw):
        # Varsayılan: L0 platform read (active tenant) → COMMIT, ihlal yok.
        d = {
            "request_id": "req-1", "op": "read", "actor_realm": "platform",
            "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
            "current_status": "active", "tenant_id": "t-001",
        }
        d.update(kw)
        return d

    def create_req(**kw):
        d = {
            "request_id": "req-c", "op": "create", "actor_realm": "platform",
            "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
            "current_status": None, "tenant_id": "t-new", "tenant_name": "Acme",
            "home_region": "EU", "kms_key_ref": "kms-eu-001", "isolation_mode": "shared",
            "compliance_profile": "PROFILE-EU", "default_locale": "tr-TR", "timezone": "Europe/Istanbul",
            "audit_emitted": True,
        }
        d.update(kw)
        return d

    # 1) happy — read → COMMIT, ihlal yok
    r = build(req(), spec)
    case("happy: read COMMIT (platform)", r["terminal"] == "COMMIT")
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) create happy → COMMIT (provisioning), ihlal yok
    r = build(create_req(), spec)
    case("create happy: COMMIT", r["terminal"] == "COMMIT")
    case("create happy: target_status=provisioning", r["target_status"] == "provisioning")
    case("create happy: ihlal yok + kapı geçer",
         all(x == 0 for x in r["violations"].values()) and _gate_eval(r, G)[0] is True)

    # 4) yaşam döngüsü geçişleri (happy)
    case("activate: provisioning→active COMMIT",
         build(req(op="activate", current_status="provisioning"), spec)["terminal"] == "COMMIT")
    case("suspend: active→suspended COMMIT (tenant:suspend)",
         build(req(op="suspend", current_status="active", actor_permissions=["tenant:suspend"]), spec)["terminal"] == "COMMIT")
    case("resume: suspended→active COMMIT (tenant:suspend)",
         build(req(op="resume", current_status="suspended", actor_permissions=["tenant:suspend"]), spec)["terminal"] == "COMMIT")
    r = build(req(op="terminate", current_status="active", confirm_irreversible=True, reason_code="RC-OFFBOARD"), spec)
    case("terminate: active→terminated COMMIT (confirm+reason)", r["terminal"] == "COMMIT" and r["target_status"] == "terminated")

    # 5) R4 — geçersiz geçiş DOĞRU reddedilir (ihlal yok)
    r = build(req(op="activate", current_status="active"), spec)
    case("invalid-transition correct: activate-on-active → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["invalid_transition"] == 0 and _gate_eval(r, G)[0] is True)
    r = build(req(op="resume", current_status="terminated"), spec)
    case("terminated terminal: resume-on-terminated → REJECT",
         r["terminal"] == "REJECT" and _gate_eval(r, G)[0] is True)

    # 6) R3 — yetkisiz DOĞRU reddedilir (ihlal yok)
    r = build(req(op="create", current_status=None, actor_permissions=[], tenant_name="X", home_region="EU",
                  kms_key_ref="kms-1", isolation_mode="shared", compliance_profile="P",
                  default_locale="tr-TR", timezone="Europe/Istanbul"), spec)
    case("authz correct: create yetkisiz → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unauthorized_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 7) R2 — tenant realm DOĞRU reddedilir (ihlal yok)
    r = build(req(actor_realm="tenant", plane="tenant_application_plane"), spec)
    case("realm correct: tenant realm read → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_realm_op"] == 0 and _gate_eval(r, G)[0] is True)

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 8) cross_realm
    r = build(req(), spec, inject=["cross_realm"])
    case("cross_realm: cross_realm_op>0 + kapı eler",
         r["violations"]["cross_realm_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 9) drop_permission
    r = build(create_req(), spec, inject=["drop_permission"])
    case("drop_permission: unauthorized_op>0 + kapı eler",
         r["violations"]["unauthorized_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 10) invalid_transition
    r = build(req(op="activate", current_status="terminated"), spec, inject=["invalid_transition"])
    case("invalid_transition: invalid_transition>0 + kapı eler",
         r["violations"]["invalid_transition"] > 0 and _gate_eval(r, G)[0] is False)

    # 11) skip_provisioning_field
    r = build(create_req(kms_key_ref=None), spec, inject=["skip_provisioning_field"])
    case("skip_provisioning_field: incomplete_provisioning>0 + kapı eler",
         r["violations"]["incomplete_provisioning"] > 0 and _gate_eval(r, G)[0] is False)

    # 12) direct_active (provisioning iş akışını atla)
    r = build(create_req(), spec, inject=["direct_active"])
    case("direct_active: incomplete_provisioning>0 + kapı eler",
         r["violations"]["incomplete_provisioning"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) share_kms (NFR 10.6 izolasyon)
    r = build(create_req(kms_key_ref="kms-shared", existing_kms_keys=["kms-shared"]), spec, inject=["share_kms"])
    case("share_kms: shared_kms_key>0 + kapı eler",
         r["violations"]["shared_kms_key"] > 0 and _gate_eval(r, G)[0] is False)
    # share_kms DOĞRU reddedilir (inject'siz çakışan key) — ihlal yok
    r = build(create_req(kms_key_ref="kms-x", existing_kms_keys=["kms-x"]), spec)
    case("share_kms correct: çakışan key inject'siz → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["shared_kms_key"] == 0 and _gate_eval(r, G)[0] is True)

    # 14) duplicate_provision
    r = build(create_req(), spec, inject=["duplicate_provision"])
    case("duplicate_provision: duplicate_provision>0 + kapı eler",
         r["violations"]["duplicate_provision"] > 0 and _gate_eval(r, G)[0] is False)

    # 15) unguard_termination
    r = build(req(op="terminate", current_status="active"), spec, inject=["unguard_termination"])
    case("unguard_termination: unguarded_termination>0 + kapı eler",
         r["violations"]["unguarded_termination"] > 0 and _gate_eval(r, G)[0] is False)
    # terminate confirm/gerekçe yok DOĞRU reddedilir — ihlal yok
    r = build(req(op="terminate", current_status="active", confirm_irreversible=False), spec)
    case("terminate correct: confirm yok → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unguarded_termination"] == 0 and _gate_eval(r, G)[0] is True)

    # 16) skip_audit
    r = build(create_req(), spec, inject=["skip_audit"])
    case("skip_audit: missing_audit>0 + kapı eler",
         r["violations"]["missing_audit"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model_tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) malformed → REJECT
    case("malformed-noreq: REJECT", build(req(request_id=None), spec)["note"] == "malformed")
    case("malformed-noop: REJECT", build(req(op="bogus"), spec)["note"] == "malformed")
    case("malformed-create-with-status: REJECT", build(create_req(current_status="active"), spec)["note"] == "malformed")

    # 19) evidence + leak
    r = build(create_req(), spec)
    case("evidence: request+op+realm+plane+target+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "op", "actor_realm", "plane", "target_status", "model_hash")))
    case("evidence: ham PII/key materyali alanı yok",
         all(k not in json.dumps(r) for k in ("customer_name_value", "kms_key_material_value", "connection_string_value")))
    case("leak: op+status+realm+region+key-ref temiz",
         scan_leaks('{"op":"create","current_status":"active","actor_realm":"platform","home_region":"EU","kms_key_ref":"kms-eu-001"}') == [])
    case("leak: kms_key_material_value alanı yakalanır", len(scan_leaks('{"kms_key_material_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "tenant-provisioning (WBS 12.4.1 — Tenant CRUD + provisioning [L0]; FR-TEN-001, BRD §17, DB.md §5.1/§9)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "statuses": STATUSES,
        "terminal_statuses": sorted(TERMINAL_STATUSES),
        "operations": OPERATIONS,
        "mutating_operations": sorted(MUTATING_OPS),
        "op_permission": OP_PERMISSION,
        "regions": REGIONS,
        "isolation_modes": ISOLATION_MODES,
        "required_provisioning_fields": REQUIRED_PROV_FIELDS,
        "decision": "malformed ⇒ REJECT(malformed) → ¬(platform ∧ platform_control_plane) ⇒ REJECT [commit ⇒ cross_realm_op] → "
                    "required_perm ∉ actor_permissions ⇒ REJECT [commit ⇒ unauthorized_op] → "
                    "¬valid_transition(op,current_status) ⇒ REJECT [commit ⇒ invalid_transition] → "
                    "create ∧ ¬provisioning_complete ⇒ REJECT [commit ⇒ incomplete_provisioning] → "
                    "create ∧ ¬kms_distinct ⇒ REJECT [commit ⇒ shared_kms_key] → "
                    "create ∧ tenant_exists ⇒ REJECT [commit ⇒ duplicate_provision] → "
                    "terminate ∧ ¬guarded ⇒ REJECT [commit ⇒ unguarded_termination] → "
                    "mutating ∧ ¬audit ⇒ REJECT [commit ⇒ missing_audit] → COMMIT",
        "default": "REJECT (fail-closed)",
        "fail_safe": "terminal=REJECT ⇒ işlem yürütülmez; malformed/yetkisiz/geçersiz-geçiş/eksik-provisioning ⇒ REJECT",
        "core_guarantees": [
            "R2 realm izolasyonu: tenant lifecycle YALNIZ platform realm + platform_control_plane (FR-IAM-008 altın kural; ADR-011); cross_realm_op=0",
            "R3 yetkilendirme: op gerekli permission-key gerektirir (tenant:provision/tenant:suspend; 12.1.2; platform_owner 12.1.1); unauthorized_op=0",
            "R4 geçiş geçerliliği: durum makinesi (create→provisioning→activate→active→suspend↔resume→terminate→terminated[terminal]); invalid_transition=0",
            "R5 provisioning tamlığı: create zorunlu izolasyon/residency alanları + ilk durum provisioning (NFR 10.6/10.7, DB.md §5.1); incomplete_provisioning=0",
            "R6 tenant-başına KMS: her tenant kendi kms_key_ref'ini alır (NFR 10.6; FR-TEN-002); shared_kms_key=0",
            "R7 idempotent provision: var olan tenant için ikinci create yapılmaz; duplicate_provision=0",
            "R8 geri döndürülemez terminate koruması: confirm + gerekçe (DB.md §9); unguarded_termination=0",
            "R9 WORM audit: her mutasyon audit_log'a (FR-REC-009/FR-IAM-006; 12.1.8); missing_audit=0",
        ],
        "request_fields": ["name", "request_id", "op(create|read|update|activate|suspend|resume|terminate)",
                           "actor_realm(platform|tenant)", "plane(platform_control_plane|tenant_application_plane)",
                           "actor_permissions[]", "current_status(null|provisioning|active|suspended|terminated)",
                           "tenant_id", "isolation_mode(shared|dedicated)", "home_region(UK|EU|NA|ME)", "kms_key_ref",
                           "existing_kms_keys[]", "tenant_exists(bool)", "initial_status", "confirm_irreversible(bool)",
                           "reason_code", "audit_emitted(bool)", "compliance_profile", "default_locale", "timezone",
                           "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(COMMIT|REJECT)", "admit", "note", "op", "actor_realm", "plane",
                            "current_status", "target_status", "isolation_mode", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/tenant-lifecycle-model.json (frozen — statuses[4; terminated terminal] + operations[7; mutating 6] "
                 "+ op_permission[tenant:provision/tenant:suspend] + transitions[durum makinesi] + provisioning[zorunlu alanlar; "
                 "regions UK/EU/NA/ME; isolation shared/dedicated] + isolation[tenant başına KMS] + termination[confirm+gerekçe] + audit[WORM])",
        "consumes": "12.1.2 permission-catalog (tenant:provision/tenant:suspend MEVCUT — RESİPROKAL); "
                    "12.1.1 rbac-model (platform_owner bundle — RESİPROKAL); "
                    "12.2.4 l0-repo-independence (table_class_of.tenant=platform; tenant_provisioning_repo PERMIT — RESİPROKAL); "
                    "12.1.8 worm-audit (mutasyon → audit_log — RESİPROKAL); FR-TEN-001 + BRD §17 + DB.md §5.1 (kaynak doğruluk)",
        "consumed_by": "12.4.2 dedicated/shared (isolation_mode sağlanması); 12.4.3 org yapısı (L1) + 12.4.4 tenant tercihleri (L1); "
                       "1.x F1 kod (FastAPI tenant router + tenant repository + KMS tahsisi + retention motoru); WBS 15 billing; 0.4.7 gözlemlenebilirlik",
        "trace": "FR-TEN-001, FR-TEN-002, BRD §17/§14.4, DB.md §5.1/§9, NFR 10.6/10.7, ADR-011/012, 12.1.1/12.1.2/12.2.4/12.1.8",
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
            print("kullanım: tenant_provisioning_probe.py check <sample.json|dizin>")
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
