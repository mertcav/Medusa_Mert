#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.4 — TENANT DİL/SAAT DİLİMİ/BÖLGE/SAKLAMA TERCİHİ (L1) referans probe.

12. workstream'in (IAM & Erişim) TENANT TERCİH modülü ve F1-Must yeteneği. FR-TEN-004 ('Tenant bazında dil,
saat dilimi, veri bölgesi ve saklama politikası seçilebilmelidir') + DB.md §5.1 (tenant — default_locale,
timezone, home_region, retention_profile) + §9 (retention_policy — tenant + data_class → retain_days;
FR-REC-006/007/010) + BRD §17 ('tenant'a özel dil/bölge/saklama tercihleri ... Tenant Admin Console (L1)
üzerinden yönetilir') + NFR 10.7 (residency UK/EU/NA/ME) + DPIA §5.4/§5.5/§8 (cp.residency/cp.retention;
most-restrictive-wins; tenant override yalnız sıkılaştırır) + SR-TEN-004 gereksinimlerini sahiplenir. ÇEKİRDEK
FARK: bu L1 (tenant realm + tenant_application_plane) yüzeyidir — 12.4.1 (tenant CRUD) ve 12.4.2 (dedicated vs
shared) L0 (platform) iken bu L1 (sibling 12.4.3 org yapısı gibi). Tercihi DETERMİNİSTİK, FAIL-CLOSED bir
BAĞLAMA (binding) kararı olarak modeller.

  PreferenceRequest ─malformed─► tenant_isolation ─► authz ─► validity ─► residency ─► retention_floor ─► change_guard ─► audit
        │       │              │               │          │           │                 │               │           │
        │   ├─ request_id/op/realm/plane eksik|geçersiz | set'te category|value eksik ──────────────────► REJECT(malformed)
        │   ├─ ¬(tenant ∧ tenant_application_plane ∧ own_tenant) ─► REJECT [commit ⇒ cross_tenant_op        R2]
        │   ├─ perm_of(category) ∉ actor_permissions ───────────► REJECT [commit ⇒ unauthorized_op         R3]
        │   ├─ ¬valid_preference(category,value) ───────────────► REJECT [commit ⇒ invalid_preference      R4]
        │   ├─ residency ∧ region ∉ tenant_allowed ─────────────► REJECT [commit ⇒ residency_violation     R5]
        │   ├─ retention ∧ retain_days < compliance_min ────────► REJECT [commit ⇒ retention_violation     R6]
        │   ├─ heavy_change ∧ ¬confirm ─────────────────────────► REJECT [commit ⇒ unsafe_change           R7]
        │   └─ mutating ∧ ¬audit ───────────────────────────────► REJECT [commit ⇒ missing_audit           R8]
        └─ tümü geçer ─────────────────────────────────────────► COMMIT

ÇEKİRDEK: (1) R2 TENANT İZOLASYONU (FR-TEN-002) — tercih YALNIZ tenant realm + tenant_application_plane (L1) +
aktör kendi tenant'ı self-row (cross_tenant_op=0); (2) R3 YETKİLENDİRME — kategori permission-key gerektirir
(compliance:manage/retention:manage; unauthorized_op=0); (3) R4 TERCİH GEÇERLİLİĞİ — category + değer geçerli
(invalid_preference=0); (4) R5 RESIDENCY — home_region tenant izinli bölgede (NFR 10.7; YALNIZ-DARALTIR;
residency_violation=0); (5) R6 RETENTION TABANI — retain_days ≥ compliance asgari (DPIA §8 tenant-override-yalnız-
sıkılaştırır; retention_violation=0); (6) R7 DEĞİŞİM KORUMASI — residency değişimi/retention kısaltma → confirm
(unsafe_change=0); (7) R8 WORM AUDIT — her mutasyon audit_log'a (missing_audit=0). Motor DETERMİNİSTİK FAIL-CLOSED
(Date.now/random YOK; model_hash sha256). Her karar terminal (R1) + kanıt + model bütünlük manifesti (R9); metrik
düşük-kardinalite + ham PII yok (R10); model/spec/sample ham içerik/PII/credential tutmaz (R11).

Kapsam dışı (bilinçli, başka modül SAHİBİ): tenant CRUD + yaşam döngüsü → 12.4.1; dedicated vs shared izolasyon
sınıfı → 12.4.2; org yapısı → 12.4.3; compliance profile ÇÖZÜMLEME (resolver) → DPIA/compliance-profile motoru;
retention gerçek silme + residency migrasyon yürütme → F1 kod (1.2.3) + ops runbook; RLS çalışma-anı çift-kontrol
→ 12.2.3; rol→permission-key bundle → 12.1.1; permission katalog → 12.1.2; WORM audit AKIŞI → 12.1.8; repo/grant
bağımsızlık → 12.2.4; L1 OpenAPI/UI → 13.3.x. KAYNAK DOĞRULUK; çelişkide FR-TEN-004 / DB.md §5.1/§9 / BRD §17 /
NFR 10.7 / DPIA §8 esastır.

Kullanım:
  tenant_preferences_probe.py validate          Statik model + spec + 12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 resiprokal → çıkış kodu
  tenant_preferences_probe.py check <sample>     Tercih karar motoru: senaryo(lar) → kapı (R1–R11)
  tenant_preferences_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  tenant_preferences_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve ham
içerik (PII) üretilmez/yazılmaz (fixture sentetik — yalnız op/category/realm/plane enum + permission-key +
locale/tz/region enum + retain_days/min_days sayı + yapısal tenant/request kimlik [slug]; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tenant-preferences-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "tenant-preferences-model.json")
PERM_CATALOG_PATH = os.path.join(HERE, "..", "permission-catalog", "config", "permission-catalog.json")
RBAC_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
RLS_PATH = os.path.join(HERE, "..", "rls-double-check", "config", "rls-model.json")
LIFECYCLE_PATH = os.path.join(HERE, "..", "tenant-provisioning", "config", "tenant-lifecycle-model.json")
REPO_INDEP_PATH = os.path.join(HERE, "..", "l0-repo-independence", "config", "repo-independence-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"COMMIT", "REJECT"}
CATEGORIES = ["locale", "timezone", "residency", "retention"]
OPERATIONS = ["set", "read"]
MUTATING_OPS = {"set"}
REALMS = ["platform", "tenant"]
PLANES = ["platform_control_plane", "tenant_application_plane"]
REGIONS = ["UK", "EU", "NA", "ME"]
RETENTION_DATA_CLASSES = ["recording", "transcript", "call_meta", "usage", "audit"]
SUPPORTED_LOCALES = ["tr-TR", "en-US", "en-GB", "de-DE", "fr-FR", "ar-SA", "nl-NL", "es-ES"]
SUPPORTED_TIMEZONES = ["Europe/Istanbul", "Europe/London", "Europe/Berlin", "Europe/Paris",
                       "Europe/Amsterdam", "America/New_York", "America/Chicago", "Asia/Dubai",
                       "Asia/Riyadh", "UTC"]
# kategori → gerekli permission-key (12.1.2 katalog; yeni anahtar İCAT EDİLMEZ)
CATEGORY_PERMISSION = {
    "locale": "compliance:manage",
    "timezone": "compliance:manage",
    "residency": "compliance:manage",
    "retention": "retention:manage",
}
RULES = ["tenant_isolation", "authorization", "preference_validity", "residency_consistency",
         "retention_floor", "change_guard", "worm_audit", "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11"]

# Degrade (inject) — DOĞRU tercih kararını bozan müdahaleler (her biri unsafe koşulu + commit zorlar).
INJECTIONS = {"cross_tenant", "wrong_realm", "drop_permission", "invalid_value", "residency_drift",
              "retention_loosen", "unsafe_change", "skip_audit", "model_tamper"}

VIOLATION_KEYS = [
    "cross_tenant_op", "unauthorized_op", "invalid_preference", "residency_violation",
    "retention_violation", "unsafe_change", "missing_audit", "model_tampered",
    "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R11; 12.1.x/12.2.x/12.4.x deseniyle) — ham içerik/PII/sır yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string|key[_-]?material)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*(PRIVATE KEY|KEY MATERIAL)-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name_value|customer_phone_value|transcript_text_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|corr-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|tenant|platform|locale|timezone|residency|retention|recording|transcript|call_meta|usage|audit|UK|EU|NA|ME|tr-TR|en-US|en-GB|de-DE|fr-FR|ar-SA|nl-NL|es-ES|Europe|America|Asia|UTC|retain|days)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + enum + slug kimlik + retain_days sayısı eler."""
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


def _value_valid(category, value, data_class):
    """R4 tercih değeri intrinsik geçerlilik (kategori bazında enum/tip)."""
    if category == "locale":
        return value in SUPPORTED_LOCALES
    if category == "timezone":
        return value in SUPPORTED_TIMEZONES
    if category == "residency":
        return value in REGIONS
    if category == "retention":
        return (data_class in RETENTION_DATA_CLASSES) and isinstance(value, int) and (not isinstance(value, bool)) and value > 0
    return False


def build(sample, spec, inject=None, model=None):
    """Tek PreferenceRequest senaryosunu yürüt → PreferenceDecision + ihlal sayaçları.

    Motor DOĞRU tercih kararını hesaplar; inject (degrade) doğru davranışı bozar (unsafe koşulu + commit
    zorlar) ve eşleşen ihlal sayacını artırır (12.1.x/12.2.x/12.4.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    op = sample.get("op")
    actor_realm = sample.get("actor_realm", "tenant")
    plane = sample.get("plane", "tenant_application_plane")
    actor_permissions = list(sample.get("actor_permissions", []))
    tenant_id = sample.get("tenant_id")
    target_tenant_id = sample.get("target_tenant_id", tenant_id)  # tercih hedefi tenant (self-row)
    category = sample.get("category")
    value = sample.get("value")
    tenant_allowed_regions = set(sample.get("tenant_allowed_regions", list(REGIONS)))
    data_class = sample.get("data_class")                          # retention için
    compliance_min_days = sample.get("compliance_min_days", 0)     # cp.retention.* asgari (girdi)
    current_region = sample.get("current_region")                 # residency değişim tespiti
    current_retain_days = sample.get("current_retain_days")       # retention kısaltma tespiti
    confirm = bool(sample.get("confirm", False))
    audit_emitted = bool(sample.get("audit_emitted", True))

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    admit = False

    # ── R9 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "realm": model.get("realm"),
        "categories": model.get("categories"),
        "operations": model.get("operations"),
        "op_permission": model.get("op_permission"),
        "tenant_scope": model.get("tenant_scope"),
        "value_validity": model.get("value_validity"),
        "residency": model.get("residency"),
        "retention": model.get("retention"),
        "change_guard": model.get("change_guard"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["residency"] = dict(tampered["residency"])
        tampered["residency"]["narrowing_only"] = False             # residency narrowing'i kaldır (tahrifat)
        tampered["retention"] = dict(tampered["retention"])
        tampered["retention"]["retain_days_floor_from_compliance"] = False  # retention tabanını kaldır (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    op_known = op in OPERATIONS
    realm_known = actor_realm in REALMS
    plane_known = plane in PLANES
    set_needs_cat_val = (op == "set" and (not category or value is None))
    malformed = (not request_id or not op_known or not realm_known or not plane_known or set_needs_cat_val)

    if malformed:
        terminal, note, admit = "REJECT", "malformed", False
    else:
        required_perm = CATEGORY_PERMISSION.get(category)
        is_mutating = op in MUTATING_OPS

        # ── correct sub-evaluations (DOĞRU tercih kararı) ──
        # R2 tenant izolasyonu: L1 realm/plane + kendi tenant'ı (self-row)
        realm_ok = (actor_realm == "tenant" and plane == "tenant_application_plane")
        target_same_tenant = (target_tenant_id == tenant_id)
        scope_ok = bool(tenant_id) and realm_ok and target_same_tenant

        # R3 yetkilendirme (kategori permission-key)
        authorized = (required_perm is not None) and (required_perm in actor_permissions)

        # R4 tercih geçerliliği (kategori + değer)
        category_ok = (category in CATEGORIES)
        if op == "set":
            value_ok = category_ok and _value_valid(category, value, data_class)
        else:
            value_ok = category_ok
        validity_ok = value_ok

        # R5 residency (home_region tenant izinli kümede)
        if op == "set" and category == "residency":
            residency_ok = (value in REGIONS) and (value in tenant_allowed_regions)
        else:
            residency_ok = True

        # R6 retention tabanı (retain_days ≥ compliance asgari)
        if op == "set" and category == "retention" and isinstance(value, int) and not isinstance(value, bool):
            retention_ok = (value >= compliance_min_days)
        else:
            retention_ok = True

        # R7 değişim koruması (residency değişimi / retention kısaltma → confirm)
        heavy_change = False
        if op == "set" and category == "residency" and current_region is not None and value != current_region:
            heavy_change = True
        if op == "set" and category == "retention" and isinstance(value, int) and not isinstance(value, bool) \
                and current_retain_days is not None and value < current_retain_days:
            heavy_change = True
        change_guard_ok = (not heavy_change) or confirm

        # R8 WORM audit (mutasyon)
        audit_ok = (not is_mutating) or audit_emitted

        # ── DOĞRU karar: tüm kapılar geçerse commit ──
        admit = (scope_ok and authorized and validity_ok and residency_ok and retention_ok
                 and change_guard_ok and audit_ok)

        # ── DEGRADE (inject) — unsafe koşulu + commit zorla; ihlali tetikle ──
        if "cross_tenant" in inject:
            target_tenant_id = "t-other"                            # başka tenant'ın tercihi
            scope_ok = False
            admit = True
        if "wrong_realm" in inject:
            actor_realm = "platform"                                # L0 platform L1 tercih op'u deniyor
            plane = "platform_control_plane"
            realm_ok = False
            scope_ok = False
            admit = True
        if "drop_permission" in inject:
            if required_perm in actor_permissions:
                actor_permissions.remove(required_perm)             # gerekli key kaldır
            authorized = False
            admit = True
        if "invalid_value" in inject:
            validity_ok = False                                     # küme dışı değer
            admit = True
        if "residency_drift" in inject:
            residency_ok = False                                    # home_region tenant izinli dışı
            admit = True
        if "retention_loosen" in inject:
            retention_ok = False                                    # retain_days asgari altı (gevşetme)
            admit = True
        if "unsafe_change" in inject:
            heavy_change = True                                     # ağır değişim
            change_guard_ok = False                                 # confirm yok
            admit = True
        if "skip_audit" in inject and is_mutating:
            audit_emitted = False                                   # WORM audit yazılmadı
            audit_ok = False
            admit = True

        terminal = "COMMIT" if admit else "REJECT"

        # ── R2 tenant izolasyonu: yanlış realm/plane VEYA cross-tenant commit ──
        if (not scope_ok) and admit:
            v["cross_tenant_op"] += 1
        # ── R3 yetkilendirme: gerekli key olmadan commit ──
        if (not authorized) and admit:
            v["unauthorized_op"] += 1
        # ── R4 tercih geçerliliği: geçersiz kategori/değer commit ──
        if (not validity_ok) and admit:
            v["invalid_preference"] += 1
        # ── R5 residency: tenant izinli dışı home_region commit ──
        if (not residency_ok) and admit:
            v["residency_violation"] += 1
        # ── R6 retention tabanı: compliance asgari altı retain_days commit ──
        if (not retention_ok) and admit:
            v["retention_violation"] += 1
        # ── R7 değişim koruması: confirm'siz ağır değişim commit ──
        if (not change_guard_ok) and admit:
            v["unsafe_change"] += 1
        # ── R8 WORM audit: audit'siz mutasyon commit ──
        if is_mutating and (not audit_ok) and admit:
            v["missing_audit"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, op, actor_realm, plane, category, terminal, note, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, admit, v, note, op, actor_realm, plane, category, model_hash, evidence)


def _evidence(request_id, op, actor_realm, plane, category, terminal, note, model_hash):
    return {
        "request_id": request_id,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "category": category,
        "terminal": terminal,
        "note": note,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, admit, v, note, op, actor_realm, plane, category, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "admit": admit,
        "note": note,
        "op": op,
        "actor_realm": actor_realm,
        "plane": plane,
        "category": category,
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
        "invalid_preference": "max_invalid_preference",
        "residency_violation": "max_residency_violation",
        "retention_violation": "max_retention_violation",
        "unsafe_change": "max_unsafe_change",
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
        for key in ("terminal", "admit", "note", "category"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s admit=%s op=%s realm=%s category=%s note=%s"
              % (res["terminal"], res["admit"], res["op"], res["actor_realm"], res["category"], res["note"]))
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
    chk("wbs=12.4.4", spec.get("wbs") == "12.4.4")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement deterministic=true", spec.get("placement", {}).get("deterministic") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEN-004 izlenir (ÇEKİRDEK — tenant tercih)", "FR-TEN-004" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-006 izlenir (retention)", "FR-REC-006" in tr.get("fr", []))
    chk("SR-TEN-004 izlenir", "SR-TEN-004" in tr.get("srs", []))
    chk("TC-TEN-004 izlenir (RTM)", "TC-TEN-004" in tr.get("rtm", []))
    chk("DB.md §5.1/§9 izlenir (tenant + retention_policy)", "§5.1" in spec.get("placement", {}).get("trace", ""))
    chk("BRD §17 izlenir (tercih L1)", any("§17" in s for s in tr.get("brd", [])))
    chk("DPIA §8 izlenir (most-restrictive-wins)", any("§8" in s for s in tr.get("dpia", [])))
    chk("ADR-011 izlenir (iki düzlemli panel — L1)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("12.1.2 permission-catalog TÜKETİLİR (compliance:manage/retention:manage — resiprokal)",
        any("12.1.2" in s for s in tr.get("consumes", [])))
    chk("12.1.1 rbac-model TÜKETİLİR (tenant_owner/security_compliance_officer — resiprokal)",
        any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.2.3 rls-double-check TÜKETİLİR (tenant/retention_policy RLS — resiprokal)",
        any("12.2.3" in s for s in tr.get("consumes", [])))
    chk("12.4.1 tenant-provisioning TÜKETİLİR (tenant izinli bölge — resiprokal)",
        any("12.4.1" in s for s in tr.get("consumes", [])))
    chk("12.2.4 l0-repo-independence TÜKETİLİR (retention_policy=tenant_config — resiprokal)",
        any("12.2.4" in s for s in tr.get("consumes", [])))
    chk("DPIA compliance profile TÜKETİLİR (tenant_allowed_regions + compliance_min_days — resiprokal)",
        any("DPIA" in s for s in tr.get("consumes", [])))

    # 3) Sekiz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("sekiz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→tenant→authz→validity→residency→retention→change→audit",
        rz.get("evaluation") == "malformed_then_tenant_isolation_then_authorization_then_preference_validity_then_residency_consistency_then_retention_floor_then_change_guard_then_worm_audit")
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
    chk("tenant_layer tenant + tenant_application_plane + self-row",
        "tenant" in en.get("tenant_layer", "") and "tenant_application_plane" in en.get("tenant_layer", ""))
    chk("authz_layer kategori permission-key (compliance/retention:manage)",
        "compliance:manage" in en.get("authz_layer", "") and "retention:manage" in en.get("authz_layer", ""))
    chk("validity_layer locale/timezone/residency/retention",
        all(c in en.get("validity_layer", "") for c in CATEGORIES))
    chk("residency_layer home_region tenant izinli (NFR 10.7; narrowing)",
        "10.7" in en.get("residency_layer", "") and "narrowing" in en.get("residency_layer", ""))
    chk("retention_layer compliance asgari (DPIA §8; tenant override yalnız sıkılaştırır)",
        "compliance_min_days" in en.get("retention_layer", "") and "sıkılaştır" in en.get("retention_layer", ""))
    chk("change_layer confirm (residency değişimi / retention kısaltma)",
        "confirm" in en.get("change_layer", ""))
    chk("audit_layer WORM (12.1.8)", "WORM" in en.get("audit_layer", "") and "12.1.8" in en.get("audit_layer", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("categories locale/timezone/residency/retention", set(md.get("categories", [])) == set(CATEGORIES))
    chk("operations tam (2)", set(md.get("operations", [])) == set(OPERATIONS))
    chk("mutating ops tam (1: set)", set(md.get("mutating_operations", [])) == MUTATING_OPS)
    chk("regions UK/EU/NA/ME (NFR 10.7)", set(md.get("regions", [])) == set(REGIONS))
    chk("retention_data_classes tam (5)", set(md.get("retention_data_classes", [])) == set(RETENTION_DATA_CLASSES))
    chk("required_actor_realm=tenant (L1)", md.get("required_actor_realm") == "tenant")
    chk("required_plane=tenant_application_plane (L1)", md.get("required_plane") == "tenant_application_plane")

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_cross_tenant_op", "max_unauthorized_op", "max_invalid_preference",
               "max_residency_violation", "max_retention_violation", "max_unsafe_change",
               "max_missing_audit", "max_model_tampered", "max_missing_evidence",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("pref_decision_total metrik", "pref_decision_total" in obs.get("metrics", []))
    chk("pref_violation_total metrik (alarm)", "pref_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("tenant_id/request_id YÜKSEK kard (label değil)",
        all(x in hi for x in ("tenant_id", "request_id"))
        and not any(x in lo for x in ("tenant_id", "request_id")))
    chk("op/result/category DÜŞÜK kard",
        all(x in lo for x in ("op", "result", "category")))
    chk("alarm cross_tenant_op/unauthorized_op/residency/retention ≤2dk",
        any(x in obs.get("alarm", "") for x in ("cross_tenant_op", "unauthorized_op", "residency_violation", "retention_violation")))

    # 10) İnvariant'lar R1–R11
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R11 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (FR-TEN-004 / DB.md §5.1/§9)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/tenant-preferences-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model categories locale/timezone/residency/retention (FR-TEN-004)",
            set(mm.get("categories", {}).get("list", [])) == set(CATEGORIES))
        chk("model operations tam (2)", set(mm.get("operations", {}).get("list", [])) == set(OPERATIONS))
        chk("model mutating ops (1: set)", set(mm.get("operations", {}).get("mutating", [])) == MUTATING_OPS)
        model_op_perm = mm.get("op_permission", {}).get("by_category", {})
        chk("model op_permission.by_category = CATEGORY_PERMISSION (compliance/retention:manage)",
            model_op_perm == CATEGORY_PERMISSION)
        chk("model required_actor_realm=tenant (L1; BRD §17)",
            mm.get("realm", {}).get("required_actor_realm") == "tenant")
        chk("model required_plane=tenant_application_plane (L1; ADR-011)",
            mm.get("realm", {}).get("required_plane") == "tenant_application_plane")
        chk("model tenant_scope self-row (FR-TEN-002)",
            mm.get("tenant_scope", {}).get("actor_tenant_must_match_target") is True)
        chk("model value_validity supported_locales (BCP-47)",
            set(mm.get("value_validity", {}).get("supported_locales", [])) == set(SUPPORTED_LOCALES))
        chk("model value_validity supported_timezones (IANA)",
            set(mm.get("value_validity", {}).get("supported_timezones", [])) == set(SUPPORTED_TIMEZONES))
        chk("model value_validity regions UK/EU/NA/ME",
            set(mm.get("value_validity", {}).get("regions", [])) == set(REGIONS))
        chk("model value_validity retention_data_classes (DB.md §9 CHECK)",
            set(mm.get("value_validity", {}).get("retention_data_classes", [])) == set(RETENTION_DATA_CLASSES))
        chk("model residency tenant izinli + UK/EU/NA/ME + narrowing-only (NFR 10.7; DPIA §8)",
            mm.get("residency", {}).get("region_must_be_in_tenant_allowed") is True
            and mm.get("residency", {}).get("narrowing_only") is True
            and set(mm.get("residency", {}).get("regions", [])) == set(REGIONS))
        chk("model retention floor-from-compliance + tenant override yalnız sıkılaştırır (DPIA §8)",
            mm.get("retention", {}).get("retain_days_floor_from_compliance") is True
            and mm.get("retention", {}).get("tenant_override_tightens_only") is True)
        chk("model change_guard residency değişimi + retention kısaltma → confirm (FR-REC-010)",
            mm.get("change_guard", {}).get("residency_region_change_requires_confirm") is True
            and mm.get("change_guard", {}).get("retention_reduction_requires_confirm") is True)
        chk("model audit mutasyon (set) WORM",
            set(mm.get("audit", {}).get("required_for", [])) == MUTATING_OPS
            and mm.get("audit", {}).get("worm") is True)
        chk("model compliance_profile_link most-restrictive-wins (DPIA §8 resiprokal)",
            "most-restrictive" in mm.get("compliance_profile_link", {}).get("resolution", ""))
        chk("model retention_policy data_class=tenant_config (12.2.4 resiprokal)",
            mm.get("data_class", {}).get("retention_policy_table_class") == "tenant_config")

    # 12) 12.1.2 RESİPROKAL — permission-catalog compliance:manage + retention:manage MEVCUT (L1)
    pc_ok = os.path.exists(PERM_CATALOG_PATH)
    chk("12.1.2 ../permission-catalog/config/permission-catalog.json var (TÜKETİLİR)", pc_ok)
    if pc_ok:
        pc_text = open(PERM_CATALOG_PATH, "r", encoding="utf-8").read()
        chk("12.1.2 compliance:manage permission-key kataloğda (resiprokal R3)", "compliance:manage" in pc_text)
        chk("12.1.2 retention:manage permission-key kataloğda (resiprokal R3)", "retention:manage" in pc_text)

    # 13) 12.1.1 RESİPROKAL — tenant_owner/security_compliance_officer compliance:manage/retention:manage (L1)
    rb_ok = os.path.exists(RBAC_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rb_ok)
    if rb_ok:
        rb = _load(RBAC_PATH)
        sco = rb.get("roles", {}).get("security_compliance_officer", {})
        chk("12.1.1 security_compliance_officer compliance:manage + retention:manage taşır (resiprokal R3)",
            "compliance:manage" in sco.get("permissions", []) and "retention:manage" in sco.get("permissions", []))
        chk("12.1.1 security_compliance_officer L1 realm=tenant",
            sco.get("realm") == "tenant" or sco.get("layer", "").startswith("L1"))
        to = rb.get("roles", {}).get("tenant_owner", {})
        chk("12.1.1 tenant_owner compliance:manage + retention:manage taşır (resiprokal R3)",
            "compliance:manage" in to.get("permissions", []) and "retention:manage" in to.get("permissions", []))

    # 14) 12.2.3 RESİPROKAL — RLS modeli mevcut (tenant/retention_policy tenant-scoped RLS)
    rls_ok = os.path.exists(RLS_PATH)
    chk("12.2.3 ../rls-double-check/config/rls-model.json var (tenant/retention_policy RLS — TÜKETİLİR)", rls_ok)
    if rls_ok:
        rls = _load(RLS_PATH)
        chk("12.2.3 RLS defense_in_depth + fail_closed (resiprokal R2)",
            rls.get("defense_in_depth") is not None and rls.get("fail_closed") is True)

    # 15) 12.4.1 RESİPROKAL — tenant-lifecycle home_region/locale/timezone sağlanır; retention_profile = 12.4.4
    lc_ok = os.path.exists(LIFECYCLE_PATH)
    chk("12.4.1 ../tenant-provisioning/config/tenant-lifecycle-model.json var (TÜKETİLİR)", lc_ok)
    if lc_ok:
        lc = _load(LIFECYCLE_PATH)
        prov = lc.get("provisioning", {})
        req_f = set(prov.get("required_fields", []))
        chk("12.4.1 provisioning home_region/default_locale/timezone sağlar (resiprokal — tercih başlangıcı)",
            {"home_region", "default_locale", "timezone"}.issubset(req_f))
        chk("12.4.1 regions UK/EU/NA/ME (resiprokal R5 tenant izinli bölge)",
            set(prov.get("regions", [])) == set(REGIONS))

    # 16) 12.2.4 RESİPROKAL — retention_policy tablosu = tenant_config sınıf
    ri_ok = os.path.exists(REPO_INDEP_PATH)
    chk("12.2.4 ../l0-repo-independence/config/repo-independence-model.json var (TÜKETİLİR)", ri_ok)
    if ri_ok:
        ri = _load(REPO_INDEP_PATH)
        chk("12.2.4 table_class_of.retention_policy = tenant_config (resiprokal)",
            ri.get("table_class_of", {}).get("retention_policy") == "tenant_config")

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
    chk("hiç ham-içerik/PII/sır sızıntısı yok (R11)", total_leaks == 0)

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

    def locale_req(**kw):
        # Varsayılan: L1 tenant set locale tr-TR → COMMIT, ihlal yok.
        d = {
            "request_id": "req-1", "op": "set", "actor_realm": "tenant",
            "plane": "tenant_application_plane", "actor_permissions": ["compliance:manage"],
            "tenant_id": "t-001", "category": "locale", "value": "tr-TR",
            "audit_emitted": True,
        }
        d.update(kw)
        return d

    def residency_req(**kw):
        d = {
            "request_id": "req-r", "op": "set", "actor_realm": "tenant",
            "plane": "tenant_application_plane", "actor_permissions": ["compliance:manage"],
            "tenant_id": "t-001", "category": "residency", "value": "EU",
            "tenant_allowed_regions": ["EU", "UK"], "audit_emitted": True,
        }
        d.update(kw)
        return d

    def retention_req(**kw):
        d = {
            "request_id": "req-rt", "op": "set", "actor_realm": "tenant",
            "plane": "tenant_application_plane", "actor_permissions": ["retention:manage"],
            "tenant_id": "t-001", "category": "retention", "value": 365,
            "data_class": "recording", "compliance_min_days": 180, "audit_emitted": True,
        }
        d.update(kw)
        return d

    # 1) happy — set locale → COMMIT, ihlal yok
    r = build(locale_req(), spec)
    case("happy: set locale COMMIT", r["terminal"] == "COMMIT")
    case("happy: model_hash var (R9)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) happy — set timezone → COMMIT
    r = build(locale_req(category="timezone", value="Europe/Istanbul"), spec)
    case("happy: set timezone COMMIT", r["terminal"] == "COMMIT")

    # 3) happy — set residency (tenant izinli) → COMMIT
    r = build(residency_req(), spec)
    case("happy: set residency (izinli) COMMIT", r["terminal"] == "COMMIT")

    # 4) happy — set retention (asgari üstü) → COMMIT
    r = build(retention_req(), spec)
    case("happy: set retention (asgari üstü) COMMIT + ihlal yok",
         r["terminal"] == "COMMIT" and all(x == 0 for x in r["violations"].values()) and _gate_eval(r, G)[0] is True)

    # 5) determinizm
    r1, r2 = build(retention_req(), spec), build(retention_req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 6) read (mutasyon değil; audit'siz) → COMMIT
    r = build(locale_req(op="read", value=None, audit_emitted=False), spec)
    case("read: audit'siz COMMIT (mutasyon değil)", r["terminal"] == "COMMIT")

    # 7) tüm dört kategori geçerli set → COMMIT
    case("kategori locale COMMIT", build(locale_req(value="en-US"), spec)["terminal"] == "COMMIT")
    case("kategori timezone COMMIT", build(locale_req(category="timezone", value="UTC"), spec)["terminal"] == "COMMIT")
    case("kategori residency COMMIT", build(residency_req(value="UK"), spec)["terminal"] == "COMMIT")
    case("kategori retention COMMIT", build(retention_req(value=200), spec)["terminal"] == "COMMIT")

    # 8) retention reduction (kısaltma) + confirm → COMMIT
    r = build(retention_req(value=200, current_retain_days=365, confirm=True), spec)
    case("retention kısaltma + confirm COMMIT", r["terminal"] == "COMMIT")

    # 9) residency değişim + confirm → COMMIT
    r = build(residency_req(value="UK", current_region="EU", confirm=True), spec)
    case("residency değişim + confirm COMMIT", r["terminal"] == "COMMIT")

    # ── DOĞRU REJECT'ler (ihlal yok — kapı geçer) ──

    # 10) R4 — geçersiz locale DOĞRU reddedilir
    r = build(locale_req(value="xx-XX"), spec)
    case("validity correct: geçersiz locale → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["invalid_preference"] == 0 and _gate_eval(r, G)[0] is True)

    # 11) R4 — geçersiz timezone DOĞRU reddedilir
    r = build(locale_req(category="timezone", value="Mars/Phobos"), spec)
    case("validity correct: geçersiz timezone → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["invalid_preference"] == 0 and _gate_eval(r, G)[0] is True)

    # 12) R4 — geçersiz retention data_class DOĞRU reddedilir
    r = build(retention_req(data_class="screenshots"), spec)
    case("validity correct: geçersiz data_class → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["invalid_preference"] == 0 and _gate_eval(r, G)[0] is True)

    # 13) R5 — tenant izinli dışı residency DOĞRU reddedilir
    r = build(residency_req(value="NA", tenant_allowed_regions=["EU", "UK"]), spec)
    case("residency correct: izinli dışı → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["residency_violation"] == 0 and _gate_eval(r, G)[0] is True)

    # 14) R6 — compliance asgari altı retention DOĞRU reddedilir
    r = build(retention_req(value=90, compliance_min_days=180), spec)
    case("retention correct: asgari altı → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["retention_violation"] == 0 and _gate_eval(r, G)[0] is True)

    # 15) R7 — confirm'siz residency değişimi DOĞRU reddedilir
    r = build(residency_req(value="UK", current_region="EU", confirm=False), spec)
    case("change_guard correct: confirm'siz residency değişim → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unsafe_change"] == 0 and _gate_eval(r, G)[0] is True)

    # 16) R7 — confirm'siz retention kısaltma DOĞRU reddedilir
    r = build(retention_req(value=200, current_retain_days=365, confirm=False), spec)
    case("change_guard correct: confirm'siz retention kısaltma → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unsafe_change"] == 0 and _gate_eval(r, G)[0] is True)

    # 17) R3 — yetkisiz DOĞRU reddedilir
    r = build(locale_req(actor_permissions=[]), spec)
    case("authz correct: yetkisiz → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unauthorized_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 18) R3 — yanlış kategori key DOĞRU reddedilir (retention için compliance:manage)
    r = build(retention_req(actor_permissions=["compliance:manage"]), spec)
    case("authz correct: retention compliance:manage ile (yanlış key) → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["unauthorized_op"] == 0)

    # 19) R2 — cross-tenant DOĞRU reddedilir
    r = build(locale_req(target_tenant_id="t-999"), spec)
    case("tenant correct: cross-tenant → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_tenant_op"] == 0 and _gate_eval(r, G)[0] is True)

    # 20) R2 — platform realm DOĞRU reddedilir (L0 L1 tercih op'u)
    r = build(locale_req(actor_realm="platform", plane="platform_control_plane"), spec)
    case("realm correct: platform realm → REJECT (ihlal yok)",
         r["terminal"] == "REJECT" and r["violations"]["cross_tenant_op"] == 0 and _gate_eval(r, G)[0] is True)

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 21) cross_tenant
    r = build(locale_req(), spec, inject=["cross_tenant"])
    case("cross_tenant: cross_tenant_op>0 + kapı eler",
         r["violations"]["cross_tenant_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) wrong_realm
    r = build(locale_req(), spec, inject=["wrong_realm"])
    case("wrong_realm: cross_tenant_op>0 + kapı eler",
         r["violations"]["cross_tenant_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) drop_permission
    r = build(locale_req(), spec, inject=["drop_permission"])
    case("drop_permission: unauthorized_op>0 + kapı eler",
         r["violations"]["unauthorized_op"] > 0 and _gate_eval(r, G)[0] is False)

    # 24) invalid_value
    r = build(locale_req(), spec, inject=["invalid_value"])
    case("invalid_value: invalid_preference>0 + kapı eler",
         r["violations"]["invalid_preference"] > 0 and _gate_eval(r, G)[0] is False)

    # 25) residency_drift
    r = build(residency_req(), spec, inject=["residency_drift"])
    case("residency_drift: residency_violation>0 + kapı eler",
         r["violations"]["residency_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 26) retention_loosen
    r = build(retention_req(), spec, inject=["retention_loosen"])
    case("retention_loosen: retention_violation>0 + kapı eler",
         r["violations"]["retention_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 27) unsafe_change
    r = build(residency_req(value="UK", current_region="EU"), spec, inject=["unsafe_change"])
    case("unsafe_change: unsafe_change>0 + kapı eler",
         r["violations"]["unsafe_change"] > 0 and _gate_eval(r, G)[0] is False)

    # 28) skip_audit
    r = build(locale_req(), spec, inject=["skip_audit"])
    case("skip_audit: missing_audit>0 + kapı eler",
         r["violations"]["missing_audit"] > 0 and _gate_eval(r, G)[0] is False)

    # 29) model_tamper
    r = build(locale_req(), spec, inject=["model_tamper"])
    case("model_tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 30) malformed → REJECT
    case("malformed-noreq: REJECT", build(locale_req(request_id=None), spec)["note"] == "malformed")
    case("malformed-noop: REJECT", build(locale_req(op="bogus"), spec)["note"] == "malformed")
    case("malformed-nocat: REJECT (set category yok)", build(locale_req(category=None), spec)["note"] == "malformed")
    case("malformed-noval: REJECT (set value yok)", build(locale_req(value=None), spec)["note"] == "malformed")

    # 31) evidence + leak
    r = build(retention_req(), spec)
    case("evidence: request+op+realm+plane+category+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "op", "actor_realm", "plane", "category", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("customer_name_value", "transcript_text_value", "connection_string_value")))
    case("leak: op+category+realm+locale+region+slug temiz",
         scan_leaks('{"op":"set","category":"residency","actor_realm":"tenant","value":"EU","tenant_id":"t-001","data_class":"recording"}') == [])
    case("leak: connection_string_value alanı yakalanır", len(scan_leaks('{"connection_string_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "tenant-preferences (WBS 12.4.4 — Tenant dil/saat dilimi/bölge/saklama tercihi L1; FR-TEN-004, DB.md §5.1/§9, BRD §17, NFR 10.7, DPIA §8)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "categories": CATEGORIES,
        "operations": OPERATIONS,
        "mutating_operations": sorted(MUTATING_OPS),
        "category_permission": CATEGORY_PERMISSION,
        "supported_locales": SUPPORTED_LOCALES,
        "supported_timezones": SUPPORTED_TIMEZONES,
        "regions": REGIONS,
        "retention_data_classes": RETENTION_DATA_CLASSES,
        "required_actor_realm": "tenant",
        "required_plane": "tenant_application_plane",
        "decision": "malformed ⇒ REJECT(malformed) → ¬(tenant ∧ tenant_application_plane ∧ own_tenant) ⇒ REJECT [commit ⇒ cross_tenant_op] → "
                    "perm_of(category) ∉ actor_permissions ⇒ REJECT [commit ⇒ unauthorized_op] → "
                    "¬valid_preference(category,value) ⇒ REJECT [commit ⇒ invalid_preference] → "
                    "residency ∧ region ∉ tenant_allowed ⇒ REJECT [commit ⇒ residency_violation] → "
                    "retention ∧ retain_days < compliance_min ⇒ REJECT [commit ⇒ retention_violation] → "
                    "heavy_change ∧ ¬confirm ⇒ REJECT [commit ⇒ unsafe_change] → "
                    "mutating ∧ ¬audit ⇒ REJECT [commit ⇒ missing_audit] → COMMIT",
        "default": "REJECT (fail-closed)",
        "fail_safe": "terminal=REJECT ⇒ tercih uygulanmaz; malformed/cross-tenant/yetkisiz/geçersiz-değer/residency-dışı/retention-altı/korumasız-değişim ⇒ REJECT",
        "core_guarantees": [
            "R2 tenant izolasyonu: tercih YALNIZ tenant realm + tenant_application_plane (L1) + kendi tenant'ı self-row (FR-TEN-002; 12.2.3); cross_tenant_op=0",
            "R3 yetkilendirme: kategori permission-key (compliance:manage/retention:manage; 12.1.2; tenant_owner/security_compliance_officer 12.1.1); unauthorized_op=0",
            "R4 tercih geçerliliği: category ∈ {locale,timezone,residency,retention} + değer geçerli (DB.md §5.1/§9); invalid_preference=0",
            "R5 residency: home_region tenant izinli bölgede + UK/EU/NA/ME (NFR 10.7; YALNIZ-DARALTIR; DPIA §8); residency_violation=0",
            "R6 retention tabanı: retain_days ≥ compliance asgari (DPIA §5.5/§8; tenant override yalnız sıkılaştırır; FR-REC-006); retention_violation=0",
            "R7 değişim koruması: residency değişimi/retention kısaltma → confirm (FR-REC-010); unsafe_change=0",
            "R8 WORM audit: her mutasyon audit_log'a (FR-REC-009/FR-IAM-006; 12.1.8); missing_audit=0",
        ],
        "request_fields": ["name", "request_id", "op(set|read)",
                           "actor_realm(platform|tenant)", "plane(platform_control_plane|tenant_application_plane)",
                           "actor_permissions[]", "tenant_id", "target_tenant_id",
                           "category(locale|timezone|residency|retention)", "value(locale|tz|region|retain_days)",
                           "tenant_allowed_regions[]", "data_class(recording|transcript|call_meta|usage|audit)",
                           "compliance_min_days(int)", "current_region(UK|EU|NA|ME)", "current_retain_days(int)",
                           "confirm(bool)", "audit_emitted(bool)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(COMMIT|REJECT)", "admit", "note", "op", "actor_realm", "plane",
                            "category", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/tenant-preferences-model.json (frozen — categories[locale/timezone/residency/retention] + operations[2; mutating 1] "
                 "+ op_permission[locale/timezone/residency→compliance:manage, retention→retention:manage] + tenant_scope[kendi tenant self-row] "
                 "+ value_validity[supported locale/IANA tz/UK-EU-NA-ME/retention data_class] + residency[home_region tenant izinli; UK/EU/NA/ME; narrowing-only] "
                 "+ retention[retain_days ≥ compliance asgari; tenant override yalnız sıkılaştırır] + change_guard[residency değişimi/retention kısaltma → confirm] + audit[WORM])",
        "consumes": "12.1.2 permission-catalog (compliance:manage/retention:manage MEVCUT — RESİPROKAL R3); "
                    "12.1.1 rbac-model (tenant_owner/security_compliance_officer bundle — RESİPROKAL R3); "
                    "12.2.3 rls-double-check (tenant/retention_policy tenant-scoped RLS — RESİPROKAL R2); "
                    "12.4.1 tenant-provisioning (home_region/locale/timezone sağlanır; tenant izinli bölge — RESİPROKAL R5); "
                    "12.2.4 l0-repo-independence (retention_policy=tenant_config sınıf — RESİPROKAL); "
                    "DPIA compliance profile (cp.residency/cp.retention; most-restrictive-wins; tenant_allowed_regions + compliance_min_days GİRDİ — RESİPROKAL R5/R6); "
                    "FR-TEN-004 + DB.md §5.1/§9 + BRD §17 + NFR 10.7 + DPIA §8 (kaynak doğruluk)",
        "consumed_by": "13.3.x T-01/T-02 Tenant Ayarları (L1 UI/OpenAPI) + F1 kod (tenant tercih alanı + retention_policy CRUD + retention motoru 1.2.3 + residency migrasyon); "
                       "SR-TEN-004 (runtime'a uygulanır; SR-LOC-001/SR-REC-006); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-TEN-004, FR-TEN-002, DB.md §5.1/§9, BRD §17, NFR 10.7, DPIA §5.4/§5.5/§8, FR-REC-006/007/010, 12.4.1/12.2.3/12.1.1/12.1.2/12.2.4/12.1.8",
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
            print("kullanım: tenant_preferences_probe.py check <sample.json|dizin>")
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
