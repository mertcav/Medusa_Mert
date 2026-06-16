#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.3 — Scoped assignment (rol + departman/marka/kampanya filtresi) referans probe.

12. workstream'in (IAM & Erişim) KAPSAM-DARALTMA modülü ve F2-Must yeteneği. FR-IAM-011 ('esneklik, rol
atamasının scope filtresiyle [departman/marka/kampanya kapsamı] daraltılmasıyla sağlanır') + SAD §14.4.2
('rol = sabit permission bundle; atama bir scope [departman/marka/kampanya] ile daraltılır; guard hem
permission-key'i hem assignment scope'unu kaynak attribute'larına karşı doğrular') + ADR-012 (sabit rol bundle
+ atama scope filtresi)'i sahiplenir. 12.1.1 RBAC modelini (rol→IMMUTABLE permission bundle, frozen) TÜKETİR
ve üzerine atamanın KAPSAMINI ekler.

  ScopedCheckRequest ─malformed─► unknown_role ─► realm ─► tenant ─► permission gate ─► scope gate ─► karar
        │             │              │            │           │              │
        │   ├─ atama/required/resource/kimlik eksik|biçimsiz ──────────────► BLOCK (malformed_request)
        │   ├─ atama rolü 12.1.1 modelinde yok ──────────────────────────► BLOCK (unknown_role)
        │   ├─ atama rol realm ≠ actor_realm (L0↔tenant) ────────────────► BLOCK (realm_layer_mismatch)  [S4]
        │   ├─ resource.tenant_id ≠ actor tenant_id ────────────────────► BLOCK (cross_tenant_resource)  [S7]
        │   ├─ ∃ atama: required ∈ bundle ∧ resource ∈ scope ────────────► GRANT                          [S3]
        │   ├─ permission var ∧ scope yok ──────────────────────────────► DENY (out_of_scope)             [S2]
        │   ├─ yalnız :own + sahiplik=other ────────────────────────────► DENY (insufficient_scope)
        │   └─ hiçbir atama permission taşımaz ─────────────────────────► DENY (missing_permission)

ÇEKİRDEK: (1) S2 NARROWING-ONLY (FR-IAM-011/ADR-012 ÇEKİRDEK) — atama scope'u (department/brand/campaign)
rolün IMMUTABLE bundle'ının yetki yüzeyini YALNIZ DARALTIR; scope dışı kaynakta, rol bundle'ı permission'ı
taşısa bile, erişim YOK (DENY out_of_scope); scope ASLA genişletemez (scope_broadened); (2) S3 SCOPED-GRANT
DOĞRULUĞU (FR-IAM-011 ÇEKİRDEK) — GRANT ⟺ ∃ atama (required ∈ bundle(rol) ∧ resource ∈ scope(atama));
kapsam-dışı GRANT (out_of_scope_grant) yasak; granted ⟺ authorized; atamalar arası BİRLEŞİM; (3) S7 TENANT
İZOLASYONU (FR-TEN-002, BRD §17.7) — kapsam tenant İÇİNDE; resource.tenant_id ≠ actor tenant → BLOCK
cross_tenant_resource (tenant sınırı kapsamın ÜSTÜNDE); (4) S8 IMMUTABLE BUNDLE KORUNUR (FR-IAM-011/ADR-012)
— scope filtresi rol bundle'ına permission EKLEYEMEZ (permission_added; esneklik yalnız DARALTMADA, yetki
sabit). S4 realm/katman (L0 ⟂ tenant) + ':own' disiplini 12.1.1'den DEVRALINIR. Motor DETERMİNİSTİK FAIL-CLOSED
karar fonksiyonu (Date.now/random YOK; model_hash sha256 deterministik). Her karar terminal (S1) + kanıt (S9) +
model bütünlük manifesti (S10); metrik düşük-kardinalite + ham PII yok (S11); model/spec/sample ham içerik/PII/
credential tutmaz — yalnız rol adı + permission-key + kapsam boyut anahtar/değeri + enum + yapısal kimlik (S12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle çözümü (immutable, FR-IAM-001/011) →
12.1.1 (bu modül TÜKETİR/üstüne kapsam ekler); permission-key GRAMER + TAM KATALOĞU → 12.1.2; backend guard
(FastAPI dependency: permission-key + scope kaynak attribute + RLS çift kontrol) → 12.2.x (SAD §14.4.2; bu
modül KARARI üretir, HTTP enforcement orada); break-glass (Tier B kapsam-üstü erişim) → 12.3.x; SSO/SCIM IdP
grup→rol+scope atama → 12.1.4/12.1.6 (atama ÜRETİLİR, bu modül çözer); append-only WORM audit → 12.1.8 (karar
KAYDI); custom roller (şablonlu, enterprise/dedicated) → Faz 3 (ADR-012; v1 kapsam dışı).

Kullanım:
  scoped_assignment_probe.py validate          Statik model/spec/kapsama kapısı → çıkış kodu
  scoped_assignment_probe.py check <sample>     Kapsam-duyarlı karar motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  scoped_assignment_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  scoped_assignment_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız rol adı + permission-key + kapsam boyut
ID + enum + kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "scoped-assignment-spec.json")
SCOPE_MODEL_PATH = os.path.join(HERE, "config", "scope-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["GRANT", "DENY", "BLOCK"]
TERMINAL = {"GRANT", "DENY", "BLOCK"}
GRANT_TERMINALS = {"GRANT"}
RULES = ["scope_narrowing_only", "scoped_grant_correctness", "realm_layer_inherited", "dimension_conformance",
         "wildcard_discipline", "tenant_isolation", "immutable_bundle_preserved"]
DENY_REASONS = ["missing_permission", "insufficient_scope", "out_of_scope"]
BLOCK_REASONS = ["malformed_request", "unknown_role", "realm_layer_mismatch", "cross_tenant_resource"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
OWNERSHIP = {"own", "other"}
DIMENSIONS = ["department", "brand", "campaign"]
WILDCARD = "*"
PERM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$")

# Degrade (inject) — DOĞRU narrowing/scope/tenant/immutable davranışını bozan müdahaleler.
INJECTIONS = {"scope_broaden", "out_of_scope_grant", "unknown_dimension", "cross_tenant", "permission_inject",
              "realm_cross", "wildcard_abuse", "ownership_bypass", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "scope_broadened", "out_of_scope_grant", "unknown_dimension", "cross_tenant", "permission_added",
    "realm_mismatch", "ownership_violation", "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.1/11.x deseniyle) — ham içerik/PII/sır yasak; rol/permission-key/kapsam ID beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|apikey:manage|api_developer|api key/webhook|API key)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + rol adı/permission-key/kapsam ID + maskeli token eler (12.1.1 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line or line.strip().startswith('"$'):
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


def _rbac_model():
    """Rol bundle modeli = 12.1.1 config/rbac-roles.json (frozen, IMMUTABLE — permission gate). TÜKETİLİR."""
    return _load(RBAC_MODEL_PATH)


def _scope_model():
    """Kapsam modeli = config/scope-model.json (frozen — narrowing-only)."""
    return _load(SCOPE_MODEL_PATH)


def _resolve_bundle(role, rbac):
    """Tek rolün IMMUTABLE permission bundle'ı (12.1.1 frozen modelinden). Atama tek rol taşır."""
    spec = rbac["roles"].get(role)
    return set(spec.get("permissions", [])) if spec else set()


def _authz(required, bundle, ownership):
    """required permission-key'i rol bundle'ına karşı değerlendir (':own' sahiplik; 12.1.1'den devralınır).

    Döner: (authorized: bool, deny_reason: str|None) — missing_permission | insufficient_scope | None.
    """
    if required in bundle:
        if required.endswith(":own") and ownership != "own":
            return (False, "insufficient_scope")
        return (True, None)
    own_variant = required + ":own"
    if own_variant in bundle:
        if ownership == "own":
            return (True, None)
        return (False, "insufficient_scope")
    return (False, "missing_permission")


def _unknown_dims(scope):
    """Scope'taki boyut-dışı anahtarlar (S5 — department/brand/campaign dışı)."""
    return [d for d in (scope or {}) if d not in DIMENSIONS]


def scope_covers(scope, resource, inject=None):
    """Atama scope'u kaynağı kapsıyor mu? (narrowing-only; S2/S5/S6).

    Her kısıtlı boyut (department/brand/campaign) için resource değeri izinli kümede olmalı:
      - izinli = wildcard '*' içerir VEYA boyut atamada YOK → KISITSIZ, geçer
      - izinli boş liste [] → HİÇBİR ŞEYE uymaz (fail-closed) — abuse 'wildcard_abuse' bunu match-all'a çevirir
      - aksi → resource[boyut] ∈ izinli (resource o boyutu taşımıyorsa fail-closed: kapsamda kanıtlanamaz)
    Boyutlar arası VE (AND). 'wildcard_abuse' inject: empty/malformed kısıtı sessizce match-all'a çevirir.
    """
    inject = inject or set()
    scope = scope or {}
    for dim in DIMENSIONS:
        if dim not in scope:
            continue  # listelenmeyen boyut → kısıtsız (S6)
        allowed = scope[dim]
        if not isinstance(allowed, list):
            return False  # biçimsiz → fail-closed
        if WILDCARD in allowed:
            continue  # kısıtsız (S6)
        if not allowed:
            # empty list = matches_nothing (fail-closed). 'wildcard_abuse' degrade → match-all.
            if "wildcard_abuse" in inject:
                continue
            return False
        rv = resource.get(dim)
        if rv is None or rv not in allowed:
            return False  # kısıtlı ama resource uymuyor/taşımıyor → fail-closed
    return True


def build(sample, spec, inject=None, rbac=None, scope_model=None):
    """Tek kapsam-duyarlı yetki-sorgusu senaryosunu yürüt → ScopedCheckDecision + ihlal sayaçları.

    Motor DOĞRU narrowing/scope/tenant/immutable davranışını hesaplar; inject (degrade) doğru davranışı bozar ve
    eşleşen ihlal sayacını artırır (12.1.1 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    rbac = rbac if rbac is not None else _rbac_model()
    scope_model = scope_model if scope_model is not None else _scope_model()

    request_id = sample.get("request_id")
    tenant_id = sample.get("tenant_id")
    actor_user_id = sample.get("actor_user_id")
    actor_realm = sample.get("actor_realm")
    assignments = list(sample.get("assignments", []) or [])
    required = sample.get("required_permission")
    resource = dict(sample.get("resource", {}) or {})
    ownership = sample.get("ownership", "other")

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    block_reason = None
    deny_reason = None
    authorized = False
    granted = False
    matched_assignment = None

    # ── S10 model bütünlük manifesti (frozen scope model + 12.1.1 rol bundle) ──
    canonical_model = {
        "scope": {"frozen": scope_model.get("frozen"), "narrowing_only": scope_model.get("narrowing_only"),
                  "dimensions": scope_model.get("dimensions"), "wildcard": scope_model.get("wildcard")},
        "rbac": {"frozen": rbac.get("frozen"), "roles": rbac.get("roles")},
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        # Çalışma anında modeli tahrif et (bir boyut ekle) — hash güncellenmez.
        tampered = json.loads(json.dumps(canonical_model))
        tampered["scope"]["dimensions"] = list(tampered["scope"]["dimensions"]) + ["__tamper__"]
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    roles = [a.get("role") for a in assignments]

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not actor_user_id or actor_realm not in REALMS
                 or not assignments or not all(a.get("role") for a in assignments)
                 or not required or not isinstance(required, str) or not PERM_KEY_RE.match(required)
                 or not isinstance(resource, dict) or not resource)

    if malformed:
        terminal, block_reason = "BLOCK", "malformed_request"
    else:
        # ── unknown_role: atama rolü 12.1.1 modelinde yok → fail-closed BLOCK ──
        unknown = [r for r in roles if r not in rbac["roles"]]
        if unknown:
            terminal, block_reason = "BLOCK", "unknown_role"
        else:
            # ── S4 realm/katman bütünlüğü: atama rol realm = actor_realm (L0 ⟂ tenant; 12.1.1'den) ──
            role_realms = {rbac["roles"][r]["realm"] for r in roles}
            realm_mismatch = any(rr != actor_realm for rr in role_realms) or len(role_realms) > 1
            if "realm_cross" in inject:
                realm_mismatch = True
                v["realm_mismatch"] += 1
            if realm_mismatch and "realm_cross" not in inject:
                v["realm_mismatch"] += 1

            if realm_mismatch:
                terminal, block_reason = "BLOCK", "realm_layer_mismatch"
            else:
                # ── S7 tenant izolasyonu: resource.tenant_id = actor tenant_id (FR-TEN-002) ──
                res_tenant = resource.get("tenant_id")
                cross_tenant = res_tenant is not None and res_tenant != tenant_id
                if "cross_tenant" in inject:
                    # cross-tenant kaynağı yine de değerlendir (degrade: izolasyon atlanır).
                    if cross_tenant or res_tenant is None:
                        v["cross_tenant"] += 1
                    cross_tenant = False  # izolasyonu atla (GRANT yoluna devam)
                elif cross_tenant:
                    v["cross_tenant"] += 1

                if cross_tenant:
                    terminal, block_reason = "BLOCK", "cross_tenant_resource"
                else:
                    # ── İki kapı: permission gate (12.1.1 bundle) + scope gate (narrowing) ──
                    permission_anywhere = False    # ∃ atama: required ∈ bundle (':own' tutar)
                    own_only_block = False          # permission var ama yalnız :own + other
                    permit = False                  # ∃ atama: permission ∧ scope
                    for a in assignments:
                        bundle = _resolve_bundle(a.get("role"), rbac)
                        # ── S8 degrade: scope bundle'a permission ekler (immutable ihlali) ──
                        if "permission_inject" in inject and required not in bundle:
                            bundle = set(bundle)
                            bundle.add(required)
                            v["permission_added"] += 1
                        eff_ownership = "own" if "ownership_bypass" in inject else ownership
                        authd, dreason = _authz(required, bundle, eff_ownership)
                        if "ownership_bypass" in inject and ownership != "own":
                            own_variant = required + ":own"
                            if (required in bundle and required.endswith(":own")) or own_variant in bundle:
                                v["ownership_violation"] += 1
                        if authd:
                            permission_anywhere = True
                            scope = a.get("scope", {})
                            # ── S5 boyut conformance: boyut-dışı anahtar → defekt (fail-closed) ──
                            ud = _unknown_dims(scope)
                            if ud:
                                v["unknown_dimension"] += len(ud)
                                if "unknown_dimension" not in inject:
                                    # doğru engine: defektli atama kapsamayan sayılır (fail-closed)
                                    continue
                            # ── S2/S6 scope gate (narrowing-only) ──
                            covered = scope_covers(scope, resource, inject)
                            # ── S6 degrade: wildcard_abuse empty-list'i match-all'a çevirdi (broadening) ──
                            if "wildcard_abuse" in inject and covered and not scope_covers(scope, resource, set()):
                                v["scope_broadened"] += 1
                            # ── S2 degrade: scope dışı kaynağı kapsa (broadening) ──
                            if "scope_broaden" in inject and not covered:
                                v["scope_broadened"] += 1
                                covered = True
                            if covered:
                                permit = True
                                matched_assignment = {"role": a.get("role"), "scope": scope}
                                break
                        elif dreason == "insufficient_scope":
                            own_only_block = True

                    authorized = permit
                    # ── S3 degrade: kapsam-dışı/yetkisizken GRANT ──
                    if "out_of_scope_grant" in inject and not permit:
                        v["out_of_scope_grant"] += 1
                        authorized = True

                    if authorized:
                        terminal, granted = "GRANT", True
                    else:
                        terminal = "DENY"
                        if permission_anywhere:
                            deny_reason = "out_of_scope"
                        elif own_only_block:
                            deny_reason = "insufficient_scope"
                        else:
                            deny_reason = "missing_permission"

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, actor_realm, assignments, required, resource, ownership, authorized,
                         granted, matched_assignment, deny_reason, block_reason, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, block_reason, deny_reason, authorized, granted, assignments, required,
                 resource, ownership, actor_realm, matched_assignment, model_hash, evidence)


def _evidence(request_id, actor_realm, assignments, required, resource, ownership, authorized, granted,
              matched_assignment, deny_reason, block_reason, model_hash):
    return {
        "request_id": request_id,
        "actor_realm": actor_realm,
        "assignments": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in assignments],
        "required_permission": required,
        "resource": resource,
        "ownership": ownership,
        "authorized": authorized,
        "granted": granted,
        "matched_assignment": matched_assignment,
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, block_reason, deny_reason, authorized, granted, assignments, required,
          resource, ownership, actor_realm, matched_assignment, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "block_reason": block_reason,
        "deny_reason": deny_reason,
        "authorized": authorized,
        "granted": granted,
        "assignments": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in assignments],
        "required_permission": required,
        "resource": resource,
        "ownership": ownership,
        "actor_realm": actor_realm,
        "matched_assignment": matched_assignment,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "scope_broadened": "max_scope_broadened",
        "out_of_scope_grant": "max_out_of_scope_grant",
        "unknown_dimension": "max_unknown_dimension",
        "cross_tenant": "max_cross_tenant",
        "permission_added": "max_permission_added",
        "realm_mismatch": "max_realm_mismatch",
        "ownership_violation": "max_ownership_violation",
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
        for key in ("terminal", "block_reason", "deny_reason", "authorized", "granted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        ma = res["matched_assignment"]
        print("   terminal=%s authorized=%s granted=%s reason=%s/%s required=%s own=%s matched=%s"
              % (res["terminal"], res["authorized"], res["granted"], res["block_reason"],
                 res["deny_reason"], res["required_permission"], res["ownership"],
                 (ma["role"] if ma else None)))
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
              "block_reasons", "deny_reasons", "outcomes", "model", "authorization", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.1.3", spec.get("wbs") == "12.1.3")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement narrowing_only=true", spec.get("placement", {}).get("narrowing_only") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-011 izlenir (scoped assignment — ÇEKİRDEK)", "FR-IAM-011" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (panel-katman rol ayrımı)", "FR-IAM-008" in tr.get("fr", []))
    chk("SR-IAM-011 izlenir", "SR-IAM-011" in tr.get("srs", []))
    chk("TC-IAM-011 izlenir", "TC-IAM-011" in tr.get("rtm", []))
    chk("ADR-012 izlenir (sabit rol bundle + scoped assignment)",
        any(a.startswith("ADR-012") for a in tr.get("adr", [])))
    chk("SAD §14.4.2 scoped assignment izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("BRD §17.2 rol seti + scope filtresi izlenir", any("§17.2" in s for s in tr.get("brd", [])))
    chk("BRD §16 Organisation Unit/Campaign (boyutlar) izlenir", any("§16" in s for s in tr.get("brd", [])))
    chk("12.1.1 RBAC modeli TÜKETİLİR (consumes)", any("12.1.1" in s for s in tr.get("consumes", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (narrowing/grant/realm/dimension/wildcard/tenant/immutable)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→unknown_role→realm→tenant→permission→scope fail-closed",
        rz.get("evaluation") == "malformed_then_unknown_role_then_realm_then_tenant_then_permission_then_scope_union_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar GRANT/DENY/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi (malformed/unknown_role/realm/cross_tenant)", br == set(BLOCK_REASONS))
    dr = set(spec["deny_reasons"].get("list", []))
    chk("deny_reason taksonomisi (missing_permission/insufficient_scope/out_of_scope)", dr == set(DENY_REASONS))

    # 6) Model — frozen + narrowing-only + boyutlar
    md = spec["model"]
    chk("model frozen=true", md.get("frozen") is True)
    chk("model narrowing_only=true (FR-IAM-011/ADR-012)", md.get("narrowing_only") is True)
    chk("custom_permission_builder=false (v1; SR-IAM-011)", md.get("custom_permission_builder") is False)
    chk("boyutlar department/brand/campaign", set(md.get("dimensions", [])) == set(DIMENSIONS))
    chk("wildcard=*", md.get("wildcard") == WILDCARD)
    chk("rbac_model 12.1.1'e referans", "12.1.1" in md.get("rbac_model", ""))
    chk("atamalar arası UNION", md.get("across_assignments") == "UNION")

    # 7) Yetki — iki kapı + ADR-012
    az = spec["authorization"]
    chk("permission_gate (12.1.1 bundle)", "bundle" in az.get("permission_gate", "").lower())
    chk("scope_gate (department/brand/campaign)",
        all(d in az.get("scope_gate", "") for d in DIMENSIONS))
    chk("karar backend'de (decision_at)", az.get("decision_at") == "backend")
    chk("narrowing_rule (yalnız daraltır)",
        "daralt" in az.get("narrowing_rule", "").lower())
    chk("tenant_rule (cross-tenant BLOCK)", "cross_tenant" in az.get("tenant_rule", "").lower()
        or "cross-tenant" in az.get("tenant_rule", "").lower())

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_scope_broadened", "max_out_of_scope_grant", "max_unknown_dimension", "max_cross_tenant",
               "max_permission_added", "max_realm_mismatch", "max_ownership_violation", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("scoped_decision_total metrik", "scoped_decision_total" in obs.get("metrics", []))
    chk("scope_integrity_violation_total metrik (S2/S3/S7/S8 alarm)",
        "scope_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/scope_values YÜKSEK kard (label değil)",
        "request_id" in hi and "scope_values" in hi and "request_id" not in lo)
    chk("result/actor_realm DÜŞÜK kard (label uygun)", "result" in lo and "actor_realm" in lo)
    chk("alarm scope_broadened/out_of_scope_grant/cross_tenant ≤2dk",
        any(x in obs.get("alarm", "") for x in ("scope_broadened", "out_of_scope_grant", "cross_tenant")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)

    # 11) Scope modeli dosyası + içsel tutarlılık
    sm_ok = os.path.exists(SCOPE_MODEL_PATH)
    chk("config/scope-model.json var", sm_ok)
    if sm_ok:
        sm = _scope_model()
        chk("scope model frozen=true", sm.get("frozen") is True)
        chk("scope model narrowing_only=true", sm.get("narrowing_only") is True)
        chk("scope model custom_permission_builder=false", sm.get("custom_permission_builder") is False)
        chk("scope model boyutlar = department/brand/campaign", set(sm.get("dimensions", [])) == set(DIMENSIONS))
        chk("scope model wildcard=*", sm.get("wildcard") == WILDCARD)
        chk("scope model narrowing_rules.scope_can_broaden=false",
            sm.get("narrowing_rules", {}).get("scope_can_broaden") is False)
        chk("scope model narrowing_rules.scope_can_add_permission=false",
            sm.get("narrowing_rules", {}).get("scope_can_add_permission") is False)
        mp = sm.get("match_policy", {})
        chk("match_policy boyutlar arası AND", mp.get("across_dimensions") == "AND")
        chk("match_policy atamalar arası UNION", mp.get("across_assignments") == "UNION")
        chk("match_policy empty_list fail-closed",
            "fail_closed" in mp.get("empty_list_means", "") or "nothing" in mp.get("empty_list_means", ""))

    # 12) 12.1.1 RBAC modeli erişilebilir (consumes) + içsel tutarlılık
    rbac_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rbac_ok)
    if rbac_ok:
        rbac = _rbac_model()
        chk("12.1.1 rbac frozen=true (IMMUTABLE)", rbac.get("frozen") is True)
        chk("12.1.1 12 rol (BRD §17.2)", len(rbac.get("roles", {})) == 12)
        chk("operations_manager campaign:manage taşır (SAD §14.4.2 örneği)",
            "campaign:manage" in rbac.get("roles", {}).get("operations_manager", {}).get("permissions", []))

    # 13) Sır/PII tarayıcı — spec + modeller + samples
    scan_files = [SPEC_PATH, SCOPE_MODEL_PATH] + (
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
    chk("hiç ham-içerik/PII/sır sızıntısı yok (S12)", total_leaks == 0)

    # 14) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
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
        # Varsayılan: operations_manager@scope=brand-x, brand-x kampanyasını yönet → GRANT (SAD §14.4.2 örneği).
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_user_id": "u-1", "actor_realm": "tenant",
            "assignments": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
            "required_permission": "campaign:manage", "ownership": "other",
            "resource": {"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-1"},
        }
        d.update(kw)
        return d

    # 1) happy — kapsam içi → GRANT
    r = build(req(), spec)
    case("happy: GRANT", r["terminal"] == "GRANT")
    case("happy: authorized=true", r["authorized"] is True)
    case("happy: granted=true", r["granted"] is True)
    case("happy: matched_assignment operations_manager", r["matched_assignment"]["role"] == "operations_manager")
    case("happy: model_hash var (S10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm + model_hash deterministik
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) S2 ÇEKİRDEK narrowing — kapsam dışı marka → DENY out_of_scope (rol campaign:manage taşısa bile)
    r = build(req(resource={"tenant_id": "t-acme", "brand": "brand-y", "campaign": "camp-9"}), spec)
    case("out-of-scope: DENY", r["terminal"] == "DENY")
    case("out-of-scope: deny_reason=out_of_scope", r["deny_reason"] == "out_of_scope")
    case("out-of-scope: granted=false", r["granted"] is False)
    case("out-of-scope: ihlal yok (meşru DENY)", all(x == 0 for x in r["violations"].values()))
    case("out-of-scope: kapı geçer (DENY meşru terminal)", _gate_eval(r, G)[0] is True)

    # 3b) çok-boyutlu kapsam (brand AND campaign) — kampanya uymazsa out_of_scope
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": ["brand-x"], "campaign": ["camp-1"]}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-2"}), spec)
    case("multi-dim: brand uyar campaign uymaz → DENY out_of_scope", r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope")
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": ["brand-x"], "campaign": ["camp-1"]}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-1"}), spec)
    case("multi-dim: her iki boyut uyar → GRANT", r["terminal"] == "GRANT")

    # 4) tenant-geneli atama (kapsamsız scope) = v1 geriye-uyum → GRANT (her kaynak)
    r = build(req(assignments=[{"role": "operations_manager", "scope": {}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-z", "campaign": "camp-7"}), spec)
    case("tenant-wide: kapsamsız scope → GRANT (her kaynak)", r["terminal"] == "GRANT")
    # wildcard da kısıtsız
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": ["*"]}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-q"}), spec)
    case("wildcard: brand=* → GRANT (kısıtsız)", r["terminal"] == "GRANT")

    # 4b) çoklu marka kümesi (boyut içi OR)
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": ["brand-x", "brand-y"]}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-y"}), spec)
    case("within-dim OR: brand∈{x,y} resource=y → GRANT", r["terminal"] == "GRANT")

    # 4c) atamalar arası birleşim (union)
    r = build(req(assignments=[{"role": "qa_analyst", "scope": {"brand": ["brand-x"]}},
                               {"role": "operations_manager", "scope": {"brand": ["brand-y"]}}],
                  required_permission="campaign:manage",
                  resource={"tenant_id": "t-acme", "brand": "brand-y"}), spec)
    case("union: ikinci atama (ops@brand-y) GRANT verir", r["terminal"] == "GRANT" and r["matched_assignment"]["role"] == "operations_manager")

    # 5) permission yok → DENY missing_permission (scope'tan bağımsız)
    r = build(req(required_permission="tenant:provision"), spec)
    case("no-perm: DENY missing_permission", r["terminal"] == "DENY" and r["deny_reason"] == "missing_permission")

    # 6) :own disiplini devralınır (insufficient_scope)
    r = build(req(assignments=[{"role": "human_agent", "scope": {}}], required_permission="calls:read",
                  ownership="own", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), spec)
    case("own-own: GRANT", r["terminal"] == "GRANT")
    r = build(req(assignments=[{"role": "human_agent", "scope": {}}], required_permission="calls:read",
                  ownership="other", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), spec)
    case("own-other: DENY insufficient_scope", r["terminal"] == "DENY" and r["deny_reason"] == "insufficient_scope")

    # 7) S7 tenant izolasyonu — cross-tenant kaynak → BLOCK cross_tenant_resource
    r = build(req(resource={"tenant_id": "t-other", "brand": "brand-x", "campaign": "camp-1"}), spec)
    case("cross-tenant: BLOCK cross_tenant_resource", r["terminal"] == "BLOCK" and r["block_reason"] == "cross_tenant_resource")
    case("cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    case("cross-tenant: kapı ELER", _gate_eval(r, G)[0] is False)

    # 8) S4 realm/katman — tenant rolü platform realm'de → BLOCK
    r = build(req(actor_realm="platform"), spec)
    case("realm-cross: BLOCK realm_layer_mismatch", r["terminal"] == "BLOCK" and r["block_reason"] == "realm_layer_mismatch")
    case("realm-cross: realm_mismatch>0 + kapı eler", r["violations"]["realm_mismatch"] > 0 and _gate_eval(r, G)[0] is False)

    # 9) unknown_role → BLOCK
    r = build(req(assignments=[{"role": "super_admin", "scope": {}}]), spec)
    case("unknown-role: BLOCK unknown_role", r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_role")

    # 10) malformed → BLOCK
    case("malformed-noassign: BLOCK", build(req(assignments=[]), spec)["block_reason"] == "malformed_request")
    case("malformed-noresource: BLOCK", build(req(resource={}), spec)["block_reason"] == "malformed_request")
    case("malformed-perm: BLOCK", build(req(required_permission="calls"), spec)["block_reason"] == "malformed_request")

    # 11) S2 degrade scope_broaden — kapsam dışı kaynağı kapsa
    r = build(req(resource={"tenant_id": "t-acme", "brand": "brand-y"}), spec, inject=["scope_broaden"])
    case("scope-broaden: scope_broadened>0", r["violations"]["scope_broadened"] > 0)
    case("scope-broaden: GRANT (yanlış)", r["terminal"] == "GRANT")
    case("scope-broaden: kapı ELER", _gate_eval(r, G)[0] is False)

    # 12) S3 degrade out_of_scope_grant — kapsam-dışıyken GRANT zorla
    r = build(req(resource={"tenant_id": "t-acme", "brand": "brand-y"}), spec, inject=["out_of_scope_grant"])
    case("oos-grant: out_of_scope_grant>0 + kapı eler", r["violations"]["out_of_scope_grant"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) S8 degrade permission_inject — scope bundle'a permission ekler
    r = build(req(required_permission="tenant:provision"), spec, inject=["permission_inject"])
    case("perm-inject: permission_added>0", r["violations"]["permission_added"] > 0)
    case("perm-inject: kapı ELER", _gate_eval(r, G)[0] is False)

    # 14) S5 degrade unknown_dimension — boyut-dışı anahtar honor edilir
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"region": ["eu"]}}]), spec, inject=["unknown_dimension"])
    case("unknown-dim: unknown_dimension>0 + kapı eler", r["violations"]["unknown_dimension"] > 0 and _gate_eval(r, G)[0] is False)
    # doğru engine: boyut-dışı anahtar → defekt (fail-closed), yine unknown_dimension>0
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"region": ["eu"]}}]), spec)
    case("unknown-dim correct: defekt fail-closed (unknown_dimension>0)", r["violations"]["unknown_dimension"] > 0)

    # 15) S7 degrade cross_tenant inject — izolasyonu atla
    r = build(req(resource={"tenant_id": "t-other", "brand": "brand-x"}), spec, inject=["cross_tenant"])
    case("cross-tenant-inject: cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 16) S6 wildcard_abuse — empty list'i match-all'a çevir
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": []}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-x"}), spec, inject=["wildcard_abuse"])
    case("wildcard-abuse: scope_broadened>0 + kapı eler", r["violations"]["scope_broadened"] > 0 and _gate_eval(r, G)[0] is False)
    # doğru engine: empty list → matches_nothing (fail-closed) → out_of_scope
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": []}}],
                  resource={"tenant_id": "t-acme", "brand": "brand-x"}), spec)
    case("empty-list correct: matches_nothing → DENY out_of_scope", r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope")

    # 17) S6/12.1.1 ownership_bypass devralınır
    r = build(req(assignments=[{"role": "human_agent", "scope": {}}], required_permission="calls:read",
                  ownership="other", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), spec, inject=["ownership_bypass"])
    case("own-bypass: ownership_violation>0 + kapı eler", r["violations"]["ownership_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) S10 model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 19) fail-closed: resource boyut taşımıyor ama scope kısıtlı → out_of_scope
    r = build(req(assignments=[{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
                  resource={"tenant_id": "t-acme", "campaign": "camp-1"}), spec)
    case("fail-closed: resource brand taşımıyor + scope brand kısıtlı → DENY out_of_scope",
         r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope")

    # 20) kanıt (S9) yapısal, PII yok
    r = build(req(), spec)
    case("evidence: request + assignments + resource + model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "assignments", "resource", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("customer_phone_value", "card_pan_value", "raw_value")))

    # 21) sızıntı tarayıcı
    case("leak: rol+kapsam ID temiz", scan_leaks('{"role":"operations_manager","scope":{"brand":["brand-x"]}}') == [])
    case("leak: permission-key temiz", scan_leaks('{"required_permission": "campaign:manage"}') == [])
    case("leak: card_pan_value alanı yakalanır", len(scan_leaks('{"card_pan_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "scoped-assignment (WBS 12.1.3 — rol + departman/marka/kampanya filtresi; FR-IAM-011/ADR-012)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "grant_terminals": sorted(GRANT_TERMINALS),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "deny_reasons": DENY_REASONS,
        "realms": sorted(REALMS),
        "ownership": sorted(OWNERSHIP),
        "dimensions": DIMENSIONS,
        "wildcard": WILDCARD,
        "decision": "malformed ⇒ BLOCK(malformed_request) → atama rolü modelde yok ⇒ BLOCK(unknown_role) → "
                    "rol realm ≠ actor_realm ⇒ BLOCK(realm_layer_mismatch) → resource.tenant_id ≠ actor tenant ⇒ "
                    "BLOCK(cross_tenant_resource) → ∀ atama: permit = (required ∈ bundle(rol), :own) ∧ "
                    "scope_covers(scope, resource) → ∃ permit ⇒ GRANT | DENY(out_of_scope|insufficient_scope|missing_permission)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ granted=false; malformed/unknown_role/realm/tenant mismatch ⇒ BLOCK; scope dışı ⇒ DENY out_of_scope",
        "core_guarantees": [
            "S2 narrowing-only: atama scope'u rolün immutable bundle'ını YALNIZ daraltır; scope dışı kaynak DENY out_of_scope; scope_broadened=0 (FR-IAM-011/ADR-012)",
            "S3 scoped-grant doğruluğu: GRANT ⟺ ∃ atama (required ∈ bundle ∧ resource ∈ scope); out_of_scope_grant=0 (FR-IAM-011)",
            "S4 realm/katman bütünlüğü: L0 ⟂ tenant; atama rol realm=actor_realm; realm_mismatch=0 (FR-IAM-008; 12.1.1'den devralınır)",
            "S7 tenant izolasyonu: kapsam tenant içinde; resource.tenant_id ≠ actor tenant ⇒ BLOCK; cross_tenant=0 (FR-TEN-002)",
            "S8 immutable bundle korunur: scope permission EKLEYEMEZ; permission_added=0 (FR-IAM-011/ADR-012)",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "actor_user_id",
                           "actor_realm(platform|tenant)", "assignments[{role, scope{department/brand/campaign→[değer]}}]",
                           "required_permission(kaynak:eylem)", "resource{tenant_id, department, brand, campaign}",
                           "ownership(own|other)", "inject[]", "expect", "expected{}"],
        "scope_semantics": "boyutlar arası AND, boyut içi OR, atamalar arası UNION; wildcard '*'/listelenmeyen boyut = kısıtsız; "
                           "boş/eksik scope = tenant-geneli (v1 geriye-uyum); empty list [] = matches_nothing (fail-closed); "
                           "resource attribute eksik + boyut kısıtlı = fail-closed (out_of_scope)",
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "block_reason", "deny_reason", "authorized", "granted",
                            "assignments", "required_permission", "resource", "ownership", "actor_realm",
                            "matched_assignment", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/scope-model.json (frozen, narrowing-only — boyutlar department/brand/campaign + wildcard + "
                 "match_policy) + ../rbac-model/config/rbac-roles.json (12.1.1 rol→IMMUTABLE bundle — permission gate)",
        "consumes": "12.1.1 RBAC modeli (rol→immutable bundle) — permission gate + ':own' + L0 ⟂ tenant realm; "
                    "FR-IAM-011/ADR-012 narrowing-only ilkesi; BRD §16 Organisation Unit/Campaign (boyutlar)",
        "consumed_by": "12.2.x backend guard (permission-key + scope kaynak attribute + RLS enforcement) + "
                       "12.1.4/12.1.6 SSO/SCIM (rol+scope atama üretir) + 12.3.x break-glass (kapsam-üstü erişim) + "
                       "12.1.8 WORM audit (karar kaydı) + 0.4.7 gözlemlenebilirlik (scoped_* metrikleri)",
        "trace": "FR-IAM-011, FR-IAM-008, FR-TEN-002, SR-IAM-011, TC-IAM-011, BRD §17.2, BRD §16, SAD §14.4.2, ADR-011, ADR-012",
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
            print("kullanım: scoped_assignment_probe.py check <sample.json|dizin>")
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
