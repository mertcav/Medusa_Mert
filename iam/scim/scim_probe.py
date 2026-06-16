#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.6 — SCIM provisioning + IdP grup→rol eşleme referans probe.

12. workstream'in (IAM & Erişim) KULLANICI/GRUP YAŞAM DÖNGÜSÜ SENKRON modülü ve F2-Should yeteneği. FR-IAM-007
('SCIM üzerinden kullanıcı provisioning desteklenmelidir') + SAD §14.4.4 ('SCIM 2.0 provisioning [kullanıcı + grup
senkronu]; IdP grupları/attribute'ları tenant bazında RBAC rollerine eşlenir; DEPROVISION → ERİŞİM ANINDA DÜŞER;
platform rolleri [L0] ayrı bir IdP/dizinden federe edilir, tenant IdP'leri L0 rolü atayamaz — FR-IAM-008')'i
sahiplenir. 12.1.1 RBAC modelini (rol→IMMUTABLE bundle + realm, frozen) TÜKETİR ve grup→rol eşleme tablosunu
(idp_config.group_role_map — 12.1.4 SSO ile AYNI yüzey) kullanıcı/grup yaşam döngüsüyle birleştirir; ÇIKTI olarak
etkin erişim (effective_access = {role, scope} ATAMA) üretir — 12.1.3 scoped-assignment'ın TÜKETTİĞİ yüzey.

  ScimRequest ─malformed─► operation ─► auth ─► schema ─► tenant ─► version ─► lifecycle ─► karar
        │  ├─ alan eksik/biçimsiz ───────────────────────────────────────────────► REJECTED (malformed_request)
        │  ├─ operation ∉ desteklenen küme ─────────────────────────────────────► REJECTED (unsupported_operation)
        │  ├─ ¬scim_client.authenticated | güvenilmez client ────────────────────► REJECTED (unauthenticated)      [S2]
        │  ├─ resource.schema ∉ desteklenen | resourceType ∉ {User,Group} ───────► REJECTED (unsupported_schema)
        │  ├─ scim_client.tenant_id ≠ request tenant_id ────────────────────────► REJECTED (cross_tenant)         [S7]
        │  ├─ prior_version ≠ null ∧ version ≤ prior_version ────────────────────► REJECTED (version_conflict)     [S6]
        │  │
        │  ├─ DEPROVISION (deactivate/delete | active=false) ────────────────────► DEPROVISIONED (erişim ANINDA ∅ + oturum iptali)  [S3 ÇEKİRDEK]
        │  │
        │  └─ PROVISION (create/replace/patch, active≠false):
        │       ├─ eşlenen rol realm ≠ scim_client.realm (tenant SCIM → L0 rolü) ─► REJECTED (realm_escalation)    [S4]
        │       ├─ eşlenen rol 12.1.1 modelinde yok ─────────────────────────────► REJECTED (unknown_role)
        │       ├─ ∃ grup → rol (tenant tablosu, union) ──────────────────────────► PROVISIONED effective_access[{role,scope}]  [S5]
        │       └─ hiçbir grup eşleşmez ─────────────────────────────────────────► NO_ACCESS (no_role_mapping; default-deny)  [S8]

ÇEKİRDEK: (1) S3 DEPROVISION → ERİŞİM ANINDA DÜŞER (FR-IAM-007 / SAD §14.4.4 ÇEKİRDEK) — deactivate/delete edilen
subject HİÇBİR {role,scope} atamasını korumaz (effective_access=∅) + etkin oturum/token İPTAL edilir
(revoke_active_sessions); gecikmeli değil, karar anında (stale_access=0); (2) S2 SCIM İSTEMCİ AUTH BÜTÜNLÜĞÜ — yalnız
kimliği DOĞRULANMIŞ + GÜVENİLİR SCIM istemcisi provision eder (untrusted_accepted=0); (3) S4 REALM/IdP SINIRI
(FR-IAM-008) — tenant SCIM YALNIZ tenant-realm (L1/L2) rol provision eder; platform (L0) rolü ASLA
(realm_escalation=0); L0 ayrı dizinden (ADR-011); (4) S5 ROL-EŞLEME DOĞRULUĞU (SAD §14.4.4) — PROVISIONED rolleri ⟺
∃ grup tenant eşleme tablosunda; tabloda KARŞILIĞI olmayan rol ASLA verilmez (unmapped_role_granted=0); (5) S6
İDEMPOTENCY/SIRA GÜVENLİĞİ — bayat/sıra-dışı/tekrarlı op reddedilir (version ≤ prior); deprovision edilen subject
BAYAT op ile DİRİLTİLMEZ (conflict_accepted=0); (6) S7 TENANT İZOLASYONU (FR-TEN-002) — bir tenant SCIM istemcisi
başka tenant subject'ini senkronlayamaz (cross_tenant=0); (7) S8 LEAST-PRIVILEGE DEFAULT — hiç grup eşleşmezse
NO_ACCESS (default-deny; privilege_on_absence=0). Motor DETERMİNİSTİK FAIL-CLOSED karar fonksiyonu (Date.now/random
YOK; sanal-saat/version tamsayı; model_hash sha256 deterministik). Her karar terminal (S1) + kanıt (S9) + model
bütünlük manifesti (S10); metrik düşük-kardinalite + ham PII yok (S11); model/spec/sample ham token/credential/PII
tutmaz — yalnız SCIM istemci id + grup/rol adı + kapsam boyut anahtar/değeri + opak subject ref + version + enum (S12).

SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): bearer/mTLS doğrulaması bu modülde YAPILMAZ (credential-free) —
scim_client.authenticated SOYUT doğrulama SONUCUDUR; canlı SCIM endpoint/token doğrulaması F2/PoC entegrasyonunda.

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle çözümü (immutable, FR-IAM-001) → 12.1.1
(bu modül TÜKETİR — eşlenen rolü çözer/realm doğrular); permission-key gramer + katalog → 12.1.2; rol+scope atama
KAPSAM çözümü (kaynak attribute karşı) → 12.1.3 (bu modül atamayı ÜRETİR, scope kararını 12.1.3 verir); SSO login
assertion doğrulama (SAML2/OIDC) → 12.1.4 (grup→rol eşleme tablosu AYNI yüzey; deprovision edilen subject 12.1.4'te
login edemez); MFA → 12.1.5 (FR-IAM-003); backend panel guard (oturum→permission-key HTTP enforcement + deprovision
oturum iptali) → 12.2.x; append-only WORM audit (provisioning kaydı) → 12.1.8; canlı SCIM endpoint/token → F2/PoC.

Kullanım:
  scim_probe.py validate          Statik model/spec/kapsama kapısı → çıkış kodu
  scim_probe.py check <sample>     Provisioning karar motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  scim_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  scim_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK; sanal-saat/version tamsayı. Stdlib-only.
Sır/credential/anahtar ve ham token/PII (bearer token, NameID/e-posta/ad) üretilmez/yazılmaz (fixture sentetik —
yalnız SCIM istemci id + grup/rol adı + kapsam boyut ID + opak ref + version + enum; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "scim-spec.json")
SCIM_MODEL_PATH = os.path.join(HERE, "config", "scim-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["PROVISIONED", "NO_ACCESS", "DEPROVISIONED", "REJECTED"]
TERMINAL = {"PROVISIONED", "NO_ACCESS", "DEPROVISIONED", "REJECTED"}
GRANT_TERMINALS = {"PROVISIONED"}
RULES = ["scim_client_auth_integrity", "deprovision_drops_access", "realm_idp_boundary",
         "role_mapping_correctness", "idempotency_ordering_safety", "tenant_isolation",
         "least_privilege_default"]
REJECT_REASONS = ["malformed_request", "unsupported_operation", "unauthenticated", "unsupported_schema",
                  "cross_tenant", "version_conflict", "realm_escalation", "unknown_role"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
RESOURCE_TYPES = {"User", "Group"}
PROVISION_OPS = {"user.create", "user.replace", "user.patch", "group.create", "group.replace", "group.patch"}
DEPROVISION_OPS = {"user.deactivate", "user.delete", "group.delete"}
ALL_OPS = PROVISION_OPS | DEPROVISION_OPS
DIMENSIONS = ["department", "brand", "campaign"]

# Degrade (inject) — DOĞRU auth/deprovision/eşleme/realm/version/tenant davranışını bozan müdahaleler.
INJECTIONS = {"accept_untrusted_client", "stale_access_after_deprovision", "unmapped_role_grant",
              "realm_escalation", "cross_tenant", "conflict_accept", "grant_on_absence",
              "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "untrusted_accepted", "stale_access", "realm_escalation", "unmapped_role_granted",
    "conflict_accepted", "cross_tenant", "privilege_on_absence", "model_tampered",
    "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.1/12.1.3/12.1.4 deseniyle) — ham token/PII/sır yasak; SCIM/grup/rol/kapsam ID beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|private[_-]?key|credential|client[_-]?secret)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt_blob", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("pii_field", re.compile(r"(?i)\"(nameid_value|email_value|customer_phone_value|card_pan_value|otp_code_value|password_value|customer_name_value|display_name_value|address_value|token_value|bearer_value|signature_bytes|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|sub-|grp-|sc-|scim-|idp-|sp-|g-|voiceai-|saml2?|oidc|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham token/PII/sır tarayıcı. Yorum/tarif satırı + SCIM/grup/rol/kapsam ID + maskeli token eler (12.1.4 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 16):m.end() + 16]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line or '"$note"' in line or line.strip().startswith('"$'):
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
    """Rol bundle + realm modeli = 12.1.1 config/rbac-roles.json (frozen, IMMUTABLE). TÜKETİLİR."""
    return _load(RBAC_MODEL_PATH)


def _scim_model():
    """Provisioning modeli = config/scim-model.json (frozen — auth/deprovision/eşleme/realm/version)."""
    return _load(SCIM_MODEL_PATH)


def _role_realm(role, rbac):
    """Bir rolün realm'i (12.1.1 frozen modelinden); rol yoksa None."""
    spec = rbac["roles"].get(role)
    return spec.get("realm") if spec else None


def _candidate_groups(resource):
    """Aday IdP grup(lar)ı: User → resource.groups; Group → resource.group_name (tekil liste)."""
    rtype = resource.get("type")
    if rtype == "Group":
        gn = resource.get("group_name")
        return [gn] if gn else []
    return resource.get("groups", []) or []


def _resolve_mapping(groups, group_role_map):
    """Aday grupları tenant eşleme tablosuna karşı çöz → (assignments, mapped_groups, unknown_groups).

    Her bilinen grup için tablo girdisinin {role, scope} atamaları toplanır (gruplar arası UNION); tabloda
    olmayan grup SESSİZCE atlanır (unknown_group_ignored). Atama yapısı = 12.1.3'ün TÜKETTİĞİ {role, scope}
    + 12.1.4 SSO ile AYNI yüzey.
    """
    assignments = []
    mapped_groups = []
    unknown_groups = []
    for g in groups:
        entry = group_role_map.get(g)
        if entry is None:
            unknown_groups.append(g)
            continue
        mapped_groups.append(g)
        for a in entry:
            assignments.append({"role": a.get("role"), "scope": a.get("scope", {})})
    return assignments, mapped_groups, unknown_groups


def build(sample, spec, inject=None, rbac=None, scim_model=None):
    """Tek SCIM provisioning senaryosunu yürüt → ScimDecision + ihlal sayaçları.

    Motor DOĞRU auth/deprovision/eşleme/realm/tenant/version davranışını hesaplar; inject (degrade) doğru
    davranışı bozar ve eşleşen ihlal sayacını artırır (12.1.4 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    rbac = rbac if rbac is not None else _rbac_model()
    scim_model = scim_model if scim_model is not None else _scim_model()

    request_id = sample.get("request_id")
    tenant_id = sample.get("tenant_id")
    actor_realm = sample.get("actor_realm")
    operation = sample.get("operation")
    resource = dict(sample.get("resource", {}) or {})
    client = dict(sample.get("scim_client", {}) or {})
    idp = dict(sample.get("idp_config", {}) or {})
    prior_version = sample.get("prior_version")

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    reject_reason = None
    deny_reason = None          # NO_ACCESS gerekçesi (no_role_mapping)
    provisioned = False
    deprovisioned = False
    sessions_revoked = False
    effective_access = []
    matched_groups = []

    # ── S10 model bütünlük manifesti (frozen scim model + 12.1.1 rol bundle/realm) ──
    canonical_model = {
        "scim": {"frozen": scim_model.get("frozen"), "scim_version": scim_model.get("scim_version"),
                 "operations": scim_model.get("operations"),
                 "deprovision_policy": scim_model.get("deprovision_policy"),
                 "realm_separation": scim_model.get("realm_separation")},
        "rbac": {"frozen": rbac.get("frozen"), "roles": rbac.get("roles")},
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["scim"]["deprovision_policy"]["drop_access_immediately"] = False
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    version = resource.get("version")
    active = resource.get("active", True)

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not tenant_id or actor_realm not in REALMS
                 or operation is None or not isinstance(resource, dict) or not resource
                 or not isinstance(client, dict) or not client
                 or not isinstance(version, int) or isinstance(version, bool)
                 or not resource.get("type") or not resource.get("subject_ref")
                 or not isinstance(active, bool))

    if malformed:
        terminal, reject_reason = "REJECTED", "malformed_request"
    elif operation not in ALL_OPS:
        terminal, reject_reason = "REJECTED", "unsupported_operation"
    else:
        client_authn = bool(client.get("authenticated", False))
        trusted_client = idp.get("trusted_client_id")
        client_id = client.get("client_id")
        client_tenant = client.get("tenant_id")
        client_realm = client.get("realm", actor_realm)
        schema = resource.get("schema")
        rtype = resource.get("type")
        supported_schemas = set(scim_model.get("supported_schemas", []))

        # ── S2 auth: kimliği doğrulanmamış/güvenilmez istemci ──
        auth_block = (not client_authn) or (trusted_client is not None and client_id != trusted_client)
        if "accept_untrusted_client" in inject and auth_block:
            v["untrusted_accepted"] += 1
            auth_block = False  # güvenilmez istemciyi kabul et (degrade)

        # ── şema/resourceType ──
        schema_block = (rtype not in RESOURCE_TYPES) or (schema is not None and schema not in supported_schemas)

        # ── S7 tenant izolasyonu (FR-TEN-002): scim_client.tenant_id = request tenant_id ──
        cross_tenant = client_tenant is not None and client_tenant != tenant_id
        if "cross_tenant" in inject:
            if cross_tenant:
                v["cross_tenant"] += 1
            cross_tenant = False  # izolasyonu atla (degrade)
        elif cross_tenant:
            v["cross_tenant"] += 1

        # ── S6 version (iyimser eşzamanlılık): bayat/sıra-dışı/tekrarlı op ──
        conflict = isinstance(prior_version, int) and not isinstance(prior_version, bool) and version <= prior_version
        if "conflict_accept" in inject and conflict:
            v["conflict_accepted"] += 1
            conflict = False  # bayat op'u uygula (degrade — deprovision'ı diriltebilir)

        if auth_block:
            terminal, reject_reason = "REJECTED", "unauthenticated"
        elif schema_block:
            terminal, reject_reason = "REJECTED", "unsupported_schema"
        elif cross_tenant:
            terminal, reject_reason = "REJECTED", "cross_tenant"
        elif conflict:
            terminal, reject_reason = "REJECTED", "version_conflict"
        else:
            is_deprovision = (operation in DEPROVISION_OPS) or (active is False)
            groups = _candidate_groups(resource)
            group_role_map = idp.get("group_role_map", {}) or {}
            assignments, matched_groups, _unknown = _resolve_mapping(groups, group_role_map)

            if is_deprovision:
                # ── S3 ÇEKİRDEK: deprovision → erişim ANINDA ∅ + oturum iptali ──
                deprovisioned = True
                if "stale_access_after_deprovision" in inject:
                    # degrade: erişim DÜŞMEZ — atamalar korunur + oturum iptal edilmez (ÇEKİRDEK ihlal)
                    effective_access = assignments
                    sessions_revoked = False
                    v["stale_access"] += 1
                else:
                    effective_access = []
                    sessions_revoked = True
                terminal = "DEPROVISIONED"
            else:
                # ── PROVISION: grup → rol eşleme (SAD §14.4.4) ──
                # ── S5 degrade: eşleme tablosunda OLMAYAN rol ekle (unmapped grant) ──
                if "unmapped_role_grant" in inject:
                    injected_role = "tenant_admin" if client_realm == "tenant" else "platform_owner"
                    assignments = list(assignments) + [{"role": injected_role, "scope": {}, "_unmapped": True}]
                    v["unmapped_role_granted"] += 1

                # ── S4 degrade: tenant SCIM'e platform (L0) rolü provision ettir (realm escalation) ──
                if "realm_escalation" in inject and client_realm == "tenant":
                    assignments = list(assignments) + [{"role": "platform_owner", "scope": {}, "_escalated": True}]
                    v["realm_escalation"] += 1

                # ── S8 degrade: hiç grup eşleşmese bile yetki ver (yokluğa dayalı) ──
                if "grant_on_absence" in inject and not matched_groups:
                    assignments = list(assignments) + [{"role": "operations_manager", "scope": {}, "_on_absence": True}]
                    v["privilege_on_absence"] += 1

                # ── eşlenen rolleri doğrula: var mı + realm uyar mı ──
                unknown_role = None
                realm_bad = None
                for a in assignments:
                    role = a.get("role")
                    rr = _role_realm(role, rbac)
                    if rr is None:
                        unknown_role = role
                        break
                    if rr != client_realm and not a.get("_escalated") and "realm_escalation" not in inject:
                        realm_bad = role
                        v["realm_escalation"] += 1
                        break

                if unknown_role is not None:
                    terminal, reject_reason = "REJECTED", "unknown_role"
                elif realm_bad is not None:
                    terminal, reject_reason = "REJECTED", "realm_escalation"
                elif "realm_escalation" in inject and client_realm == "tenant":
                    # degrade: L0 rolü zorlanmış → yanlışlıkla PROVISIONED (kapı eler)
                    terminal, provisioned = "PROVISIONED", True
                    effective_access = assignments
                elif "grant_on_absence" in inject and not matched_groups:
                    # degrade: yokluğa dayalı yetki → yanlışlıkla PROVISIONED (kapı eler)
                    terminal, provisioned = "PROVISIONED", True
                    effective_access = assignments
                elif not assignments:
                    terminal, deny_reason = "NO_ACCESS", "no_role_mapping"
                else:
                    terminal, provisioned = "PROVISIONED", True
                    effective_access = assignments

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, tenant_id, actor_realm, operation, resource, client, provisioned,
                         deprovisioned, sessions_revoked, effective_access, matched_groups, deny_reason,
                         reject_reason, version, prior_version, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, reject_reason, deny_reason, provisioned, deprovisioned,
                 sessions_revoked, operation, actor_realm, effective_access, matched_groups,
                 resource.get("type"), model_hash, evidence)


def _evidence(request_id, tenant_id, actor_realm, operation, resource, client, provisioned, deprovisioned,
              sessions_revoked, effective_access, matched_groups, deny_reason, reject_reason, version,
              prior_version, model_hash):
    """Yapısal kanıt — ham token/bearer/NameID/e-posta YOK; yalnız SCIM istemci id + opak subject ref + grup/rol adı."""
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "actor_realm": actor_realm,
        "operation": operation,
        "resource_type": resource.get("type"),
        "subject_ref": resource.get("subject_ref"),
        "scim_client_id": client.get("client_id"),
        "version": version,
        "prior_version": prior_version,
        "matched_groups": matched_groups,
        "provisioned": provisioned,
        "deprovisioned": deprovisioned,
        "sessions_revoked": sessions_revoked,
        "effective_access": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in effective_access],
        "deny_reason": deny_reason,
        "reject_reason": reject_reason,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, reject_reason, deny_reason, provisioned, deprovisioned, sessions_revoked,
          operation, actor_realm, effective_access, matched_groups, resource_type, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "reject_reason": reject_reason,
        "deny_reason": deny_reason,
        "provisioned": provisioned,
        "deprovisioned": deprovisioned,
        "sessions_revoked": sessions_revoked,
        "operation": operation,
        "actor_realm": actor_realm,
        "resource_type": resource_type,
        "effective_access": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in effective_access],
        "matched_groups": matched_groups,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "untrusted_accepted": "max_untrusted_accepted",
        "stale_access": "max_stale_access",
        "realm_escalation": "max_realm_escalation",
        "unmapped_role_granted": "max_unmapped_role_granted",
        "conflict_accepted": "max_conflict_accepted",
        "cross_tenant": "max_cross_tenant",
        "privilege_on_absence": "max_privilege_on_absence",
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
        for key in ("terminal", "reject_reason", "deny_reason", "provisioned", "deprovisioned", "sessions_revoked"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s prov=%s deprov=%s revoke=%s reason=%s/%s op=%s roles=%s groups=%s"
              % (res["terminal"], res["provisioned"], res["deprovisioned"], res["sessions_revoked"],
                 res["reject_reason"], res["deny_reason"], res["operation"],
                 [a["role"] for a in res["effective_access"]], res["matched_groups"]))
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
              "reject_reasons", "outcomes", "model", "provisioning", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.1.6", spec.get("wbs") == "12.1.6")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Should", spec.get("priority") == "Should")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement credential_free=true (ADR-002)", spec.get("placement", {}).get("credential_free") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-007 izlenir (SCIM provisioning — ÇEKİRDEK)", "FR-IAM-007" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (tenant IdP L0 rolü provision edemez)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-IAM-007 izlenir", "SR-IAM-007" in tr.get("srs", []))
    chk("TC-IAM-007 izlenir", "TC-IAM-007" in tr.get("rtm", []))
    chk("SAD §14.4.4 SSO/SCIM rol eşleme izlenir", any("§14.4.4" in s for s in tr.get("sad", [])))
    chk("12.1.1 RBAC modeli TÜKETİLİR (consumes)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.4 SSO eşleme tablosu yüzeyi TÜKETİLİR (consumes — AYNI tablo)",
        any("12.1.4" in s for s in tr.get("consumes", [])))
    chk("12.1.3 scoped assignment TÜKETİR (consumed_by — atama üretilir)",
        any("12.1.3" in s for s in tr.get("consumed_by", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (auth/deprovision/realm/mapping/idempotency/tenant/least-privilege)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→operation→auth→schema→tenant→version→lifecycle fail-closed",
        rz.get("evaluation") == "malformed_then_operation_then_auth_then_schema_then_tenant_then_version_then_lifecycle_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)
    chk("deprovision_drops_access kuralı S3 ÇEKİRDEK (FR-IAM-007)",
        any(d["id"] == "deprovision_drops_access" and d.get("invariant") == "S3" for d in rz.get("list", [])))

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=REJECTED (fail-closed)", dec.get("default") == "REJECTED")
    chk("fail_safe no access/provisioning", "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar PROVISIONED/NO_ACCESS/DEPROVISIONED/REJECTED", set(oc.get("list", [])) == set(OUTCOMES))
    rr = set(spec["reject_reasons"].get("list", []))
    chk("reject_reason taksonomisi tam (8)", rr == set(REJECT_REASONS))

    # 6) Model — frozen + scim + deprovision
    md = spec["model"]
    chk("model frozen=true", md.get("frozen") is True)
    chk("scim_version=2.0 (FR-IAM-007)", md.get("scim_version") == "2.0")
    chk("resource_types User+Group (kullanıcı+grup senkronu)", set(md.get("resource_types", [])) == RESOURCE_TYPES)
    chk("rbac_model 12.1.1'e referans", "12.1.1" in md.get("rbac_model", ""))
    chk("mapping_source 12.1.4 SSO ile AYNI yüzey", "12.1.4" in md.get("mapping_source", ""))
    chk("gruplar arası UNION", md.get("union_across_groups") == "UNION")
    chk("scope narrowing-only (12.1.3'e bağ)", md.get("scope_is_narrowing_only") is True)
    chk("deprovision_drops_access_immediately=true (FR-IAM-007 ÇEKİRDEK)",
        md.get("deprovision_drops_access_immediately") is True)

    # 7) Provisioning — kapılar + deprovision/realm/tenant kuralı
    pz = spec["provisioning"]
    chk("auth_gate (authenticated/trusted)",
        all(x in pz.get("auth_gate", "").lower() for x in ("authenticated", "trusted")))
    chk("tenant_gate (cross-tenant REJECTED; FR-TEN-002)", "FR-TEN-002" in pz.get("tenant_gate", ""))
    chk("version_gate (prior_version/version conflict — idempotency)",
        all(x in pz.get("version_gate", "") for x in ("prior_version", "version")))
    chk("deprovision_rule (erişim ANINDA ∅ + revoke; FR-IAM-007 ÇEKİRDEK)",
        "FR-IAM-007" in pz.get("deprovision_rule", "") and "revoke_active_sessions" in pz.get("deprovision_rule", ""))
    chk("mapping_gate (grup→rol union; eşleme yoksa NO_ACCESS)",
        "grup" in pz.get("mapping_gate", "").lower() and "union" in pz.get("mapping_gate", "").lower())
    chk("realm_rule (tenant SCIM yalnız tenant-realm; FR-IAM-008)", "FR-IAM-008" in pz.get("realm_rule", ""))
    chk("karar backend'de", pz.get("decision_at") == "backend")
    chk("produces {role, scope} etkin erişim (12.1.3'e) + deprovision ∅",
        "12.1.3" in pz.get("produces", "") and "DEPROVISIONED" in pz.get("produces", ""))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_untrusted_accepted", "max_stale_access", "max_realm_escalation",
               "max_unmapped_role_granted", "max_conflict_accepted", "max_cross_tenant",
               "max_privilege_on_absence", "max_model_tampered", "max_missing_evidence",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("scim_provisioning_total metrik", "scim_provisioning_total" in obs.get("metrics", []))
    chk("scim_deprovision_total metrik (deprovision olayı)", "scim_deprovision_total" in obs.get("metrics", []))
    chk("scim_federation_violation_total metrik (S2/S3/S4/S5/S7 alarm)",
        "scim_federation_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/subject_ref/group_name YÜKSEK kard (label değil)",
        "request_id" in hi and "subject_ref" in hi and "group_name" in hi and "request_id" not in lo)
    chk("operation_class/result/actor_realm DÜŞÜK kard (label uygun)",
        "operation_class" in lo and "result" in lo and "actor_realm" in lo)
    chk("alarm stale_access/untrusted/unmapped/realm/cross_tenant ≤2dk",
        any(x in obs.get("alarm", "") for x in ("stale_access", "untrusted_accepted", "unmapped_role_granted", "realm_escalation", "cross_tenant")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)
    chk("S3 deprovision çekirdek invariant'ı (erişim anında düşer)",
        any(i["id"] == "S3" and "ANINDA" in i.get("claim", "") for i in spec["invariants"]))

    # 11) SCIM modeli dosyası + içsel tutarlılık
    sm_ok = os.path.exists(SCIM_MODEL_PATH)
    chk("config/scim-model.json var", sm_ok)
    if sm_ok:
        sm = _scim_model()
        chk("scim model frozen=true", sm.get("frozen") is True)
        chk("scim model fail_closed=true", sm.get("fail_closed") is True)
        chk("scim model scim_version=2.0", sm.get("scim_version") == "2.0")
        chk("scim model resource_types User/Group", set(sm.get("resource_types", [])) == RESOURCE_TYPES)
        au = sm.get("auth_requirements", {})
        chk("scim model auth_required=true (S2)", au.get("auth_required") is True)
        dp = sm.get("deprovision_policy", {})
        chk("scim model deprovision drop_access_immediately=true (S3 ÇEKİRDEK)", dp.get("drop_access_immediately") is True)
        chk("scim model deprovision revoke_active_sessions=true (S3)", dp.get("revoke_active_sessions") is True)
        chk("scim model deprovision idempotent=true (S6)", dp.get("idempotent") is True)
        rs = sm.get("realm_separation", {})
        chk("scim model tenant_idp_grants_only_tenant_roles=true (FR-IAM-008)",
            rs.get("tenant_idp_grants_only_tenant_roles") is True)
        chk("scim model platform_idp_separate_directory=true (ADR-011)",
            rs.get("platform_idp_separate_directory") is True)
        mp = sm.get("mapping_policy", {})
        chk("scim model mapping default_deny=true (S8)", mp.get("default_deny") is True)
        chk("scim model mapping unknown_group_ignored=true", mp.get("unknown_group_ignored") is True)
        chk("scim model mapping scope_is_narrowing_only=true", mp.get("scope_is_narrowing_only") is True)
        cc = sm.get("concurrency_policy", {})
        chk("scim model concurrency require_monotonic_version=true (S6)", cc.get("require_monotonic_version") is True)
        chk("scim model no_resurrect_deprovisioned_by_stale_op=true (S6)",
            cc.get("no_resurrect_deprovisioned_by_stale_op") is True)
        chk("scim model privacy no_raw_token_persisted=true", sm.get("privacy", {}).get("no_raw_token_persisted") is True)

    # 12) 12.1.1 RBAC modeli erişilebilir (consumes) + realm taşır
    rbac_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rbac_ok)
    if rbac_ok:
        rbac = _rbac_model()
        chk("12.1.1 rbac frozen=true (IMMUTABLE)", rbac.get("frozen") is True)
        chk("12.1.1 12 rol (BRD §17.2)", len(rbac.get("roles", {})) == 12)
        chk("operations_manager realm=tenant (eşleme hedefi)",
            _role_realm("operations_manager", rbac) == "tenant")
        chk("platform_owner realm=platform (tenant SCIM provision EDEMEZ; FR-IAM-008)",
            _role_realm("platform_owner", rbac) == "platform")

    # 13) Sır/PII tarayıcı — spec + modeller + samples
    scan_files = [SPEC_PATH, SCIM_MODEL_PATH] + (
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
    chk("hiç ham-token/PII/sır sızıntısı yok (S12)", total_leaks == 0)

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
        # Varsayılan: kimliği doğrulanmış+güvenilir tenant SCIM istemcisi; user.create; grup voiceai-ops-manager →
        # operations_manager@brand-x → PROVISIONED (SAD §14.4.4). version=5, prior=null (yeni subject).
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_realm": "tenant", "operation": "user.create", "prior_version": None,
            "resource": {
                "type": "User", "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
                "subject_ref": "sub-1", "version": 5, "active": True,
                "groups": ["voiceai-ops-manager"],
            },
            "scim_client": {
                "authenticated": True, "client_id": "sc-acme", "tenant_id": "t-acme", "realm": "tenant",
            },
            "idp_config": {
                "trusted_client_id": "sc-acme",
                "group_role_map": {
                    "voiceai-ops-manager": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
                    "voiceai-qa": [{"role": "qa_analyst", "scope": {}}],
                },
            },
        }
        for k, val in kw.items():
            if k in ("resource", "scim_client", "idp_config") and isinstance(val, dict):
                merged = dict(d[k]); merged.update(val); d[k] = merged
            else:
                d[k] = val
        return d

    # 1) happy provision → PROVISIONED
    r = build(req(), spec)
    case("happy: PROVISIONED", r["terminal"] == "PROVISIONED")
    case("happy: provisioned=true", r["provisioned"] is True)
    case("happy: ops rol çözüldü", r["effective_access"][0]["role"] == "operations_manager")
    case("happy: scope brand-x korunur (12.1.3'e)", r["effective_access"][0]["scope"] == {"brand": ["brand-x"]})
    case("happy: model_hash var (S10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm + model_hash deterministik
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) gruplar arası UNION → iki rol
    r = build(req(resource={"groups": ["voiceai-ops-manager", "voiceai-qa"]}), spec)
    roles = sorted(a["role"] for a in r["effective_access"])
    case("union: iki grup → operations_manager + qa_analyst", roles == ["operations_manager", "qa_analyst"])

    # 3b) unknown grup atlanır, bilinen biri map'ler → PROVISIONED
    r = build(req(resource={"groups": ["voiceai-ops-manager", "foreign-group-x"]}), spec)
    case("unknown-group: atlanır, PROVISIONED", r["terminal"] == "PROVISIONED" and r["matched_groups"] == ["voiceai-ops-manager"])

    # 4) hiç grup eşleşmez → NO_ACCESS (provision oldu, yetki yok — default-deny)
    r = build(req(resource={"groups": ["foreign-group-x"]}), spec)
    case("no-mapping: NO_ACCESS no_role_mapping", r["terminal"] == "NO_ACCESS" and r["deny_reason"] == "no_role_mapping")
    case("no-mapping: etkin erişim ∅", r["effective_access"] == [])
    case("no-mapping: ihlal yok (meşru default-deny)", all(x == 0 for x in r["violations"].values()))
    case("no-mapping: kapı geçer", _gate_eval(r, G)[0] is True)

    # 5) S3 ÇEKİRDEK deprovision (deactivate) → DEPROVISIONED, erişim ANINDA ∅ + oturum iptali
    r = build(req(operation="user.deactivate", resource={"active": False, "version": 6}, prior_version=5), spec)
    case("deactivate: DEPROVISIONED", r["terminal"] == "DEPROVISIONED")
    case("deactivate: deprovisioned=true", r["deprovisioned"] is True)
    case("deactivate: etkin erişim ANINDA ∅", r["effective_access"] == [])
    case("deactivate: oturum iptal (revoke=true)", r["sessions_revoked"] is True)
    case("deactivate: stale_access=0 + kapı geçer", r["violations"]["stale_access"] == 0 and _gate_eval(r, G)[0] is True)

    # 5b) delete → DEPROVISIONED
    r = build(req(operation="user.delete", resource={"version": 6}, prior_version=5), spec)
    case("delete: DEPROVISIONED + erişim ∅", r["terminal"] == "DEPROVISIONED" and r["effective_access"] == [])

    # 5c) replace active=false → DEPROVISIONED (deactivation via update)
    r = build(req(operation="user.replace", resource={"active": False, "version": 6}, prior_version=5), spec)
    case("replace active=false: DEPROVISIONED", r["terminal"] == "DEPROVISIONED" and r["sessions_revoked"] is True)

    # 5d) idempotent re-deprovision (zaten pasif tekrar deactivate) → DEPROVISIONED no-op
    r = build(req(operation="user.deactivate", resource={"active": False, "version": 7}, prior_version=6), spec)
    case("idempotent re-deprovision: DEPROVISIONED", r["terminal"] == "DEPROVISIONED" and r["violations"]["stale_access"] == 0)

    # 6) S2 auth — kimliği doğrulanmamış istemci → REJECTED unauthenticated
    r = build(req(scim_client={"authenticated": False}), spec)
    case("unauthn: REJECTED unauthenticated", r["terminal"] == "REJECTED" and r["reject_reason"] == "unauthenticated")
    case("unauthn: ihlal yok (doğru reddedildi)", all(x == 0 for x in r["violations"].values()))
    case("unauthn: kapı geçer (REJECTED meşru)", _gate_eval(r, G)[0] is True)

    # 6b) güvenilmez client_id → REJECTED unauthenticated
    r = build(req(scim_client={"client_id": "sc-evil"}), spec)
    case("untrusted-client: REJECTED unauthenticated", r["terminal"] == "REJECTED" and r["reject_reason"] == "unauthenticated")

    # 7) unsupported schema/resourceType → REJECTED unsupported_schema
    r = build(req(resource={"type": "Device"}), spec)
    case("bad-resourcetype: REJECTED unsupported_schema", r["reject_reason"] == "unsupported_schema")
    r = build(req(resource={"schema": "urn:bad:schema"}), spec)
    case("bad-schema: REJECTED unsupported_schema", r["reject_reason"] == "unsupported_schema")

    # 8) unsupported operation → REJECTED
    r = build(req(operation="user.merge"), spec)
    case("unsupported-op: REJECTED unsupported_operation", r["reject_reason"] == "unsupported_operation")

    # 9) S7 tenant izolasyonu — client tenant ≠ request tenant → REJECTED cross_tenant + violation
    r = build(req(scim_client={"tenant_id": "t-other"}), spec)
    case("cross-tenant: REJECTED cross_tenant", r["terminal"] == "REJECTED" and r["reject_reason"] == "cross_tenant")
    case("cross-tenant: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 10) S6 version conflict — bayat op (version ≤ prior) → REJECTED version_conflict
    r = build(req(operation="user.replace", resource={"version": 4}, prior_version=5), spec)
    case("stale-version: REJECTED version_conflict", r["terminal"] == "REJECTED" and r["reject_reason"] == "version_conflict")
    # eşit version (tekrar) → conflict
    r = build(req(operation="user.replace", resource={"version": 5}, prior_version=5), spec)
    case("equal-version (replay): REJECTED version_conflict", r["reject_reason"] == "version_conflict")
    # ileri version → uygulanır (PROVISIONED)
    r = build(req(operation="user.replace", resource={"version": 6}, prior_version=5), spec)
    case("forward-version: PROVISIONED", r["terminal"] == "PROVISIONED")

    # 11) S4 realm — eşleme platform rol döndürse (tenant SCIM) → REJECTED realm_escalation + violation
    r = build(req(idp_config={"group_role_map": {"voiceai-ops-manager": [{"role": "platform_owner", "scope": {}}]}}), spec)
    case("realm-bad: REJECTED realm_escalation", r["terminal"] == "REJECTED" and r["reject_reason"] == "realm_escalation")
    case("realm-bad: realm_escalation>0 + kapı ELER", r["violations"]["realm_escalation"] > 0 and _gate_eval(r, G)[0] is False)

    # 12) unknown_role (eşleme bilinmeyen rol) → REJECTED unknown_role
    r = build(req(idp_config={"group_role_map": {"voiceai-ops-manager": [{"role": "super_admin", "scope": {}}]}}), spec)
    case("unknown-role: REJECTED unknown_role", r["reject_reason"] == "unknown_role")

    # 13) Group resource provision → PROVISIONED (grup→rol bağı)
    r = build(req(operation="group.create",
                  resource={"type": "Group", "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
                            "group_name": "voiceai-qa", "subject_ref": "grp-1", "version": 1, "active": True,
                            "groups": None}), spec)
    case("group-provision: PROVISIONED qa_analyst", r["terminal"] == "PROVISIONED" and r["effective_access"][0]["role"] == "qa_analyst")

    # 13b) Group delete → DEPROVISIONED (binding kalkar, üyeler rol kaybeder)
    r = build(req(operation="group.delete",
                  resource={"type": "Group", "group_name": "voiceai-qa", "subject_ref": "grp-1",
                            "version": 2, "active": True, "groups": None}, prior_version=1), spec)
    case("group-delete: DEPROVISIONED + erişim ∅", r["terminal"] == "DEPROVISIONED" and r["effective_access"] == [])

    # 14) malformed → REJECTED
    case("malformed-no-subject: REJECTED", build(req(resource={"subject_ref": None}), spec)["reject_reason"] == "malformed_request")
    case("malformed-no-version: REJECTED", build(req(resource={"version": None}), spec)["reject_reason"] == "malformed_request")
    case("malformed-bad-realm: REJECTED", build(req(actor_realm="root"), spec)["reject_reason"] == "malformed_request")

    # 15) DEGRADE accept_untrusted_client — güvenilmezi kabul et → untrusted_accepted>0 + kapı eler
    r = build(req(scim_client={"authenticated": False}), spec, inject=["accept_untrusted_client"])
    case("accept-untrusted: untrusted_accepted>0", r["violations"]["untrusted_accepted"] > 0)
    case("accept-untrusted: PROVISIONED (yanlış)", r["terminal"] == "PROVISIONED")
    case("accept-untrusted: kapı ELER", _gate_eval(r, G)[0] is False)

    # 16) DEGRADE stale_access_after_deprovision — ÇEKİRDEK: deprovision erişim DÜŞMEZ → stale_access>0 + kapı eler
    r = build(req(operation="user.deactivate", resource={"active": False, "version": 6}, prior_version=5),
              spec, inject=["stale_access_after_deprovision"])
    case("stale-access: stale_access>0 (ÇEKİRDEK)", r["violations"]["stale_access"] > 0)
    case("stale-access: erişim DÜŞMEDİ (effective_access dolu)", r["effective_access"] != [])
    case("stale-access: oturum iptal EDİLMEDİ (revoke=false)", r["sessions_revoked"] is False)
    case("stale-access: kapı ELER", _gate_eval(r, G)[0] is False)

    # 17) DEGRADE unmapped_role_grant — eşlemede olmayan rol ver
    r = build(req(), spec, inject=["unmapped_role_grant"])
    case("unmapped-grant: unmapped_role_granted>0 + kapı eler", r["violations"]["unmapped_role_granted"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) DEGRADE realm_escalation — tenant SCIM'e L0 rolü ver
    r = build(req(), spec, inject=["realm_escalation"])
    case("realm-escalation-inject: realm_escalation>0", r["violations"]["realm_escalation"] > 0)
    case("realm-escalation-inject: PROVISIONED (yanlış) + kapı eler", r["terminal"] == "PROVISIONED" and _gate_eval(r, G)[0] is False)

    # 19) DEGRADE cross_tenant inject — izolasyonu atla
    r = build(req(scim_client={"tenant_id": "t-other"}), spec, inject=["cross_tenant"])
    case("cross-tenant-inject: cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) DEGRADE conflict_accept — bayat op'u uygula (deprovision'ı diriltir)
    r = build(req(operation="user.replace", resource={"version": 3, "active": True}, prior_version=5),
              spec, inject=["conflict_accept"])
    case("conflict-accept: conflict_accepted>0 + kapı eler", r["violations"]["conflict_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 21) DEGRADE grant_on_absence — hiç grup eşleşmese de yetki ver
    r = build(req(resource={"groups": ["foreign-group-x"]}), spec, inject=["grant_on_absence"])
    case("grant-on-absence: privilege_on_absence>0 + kapı eler", r["violations"]["privilege_on_absence"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) DEGRADE model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) kanıt (S9) yapısal, ham token/PII yok
    r = build(req(), spec)
    case("evidence: request + subject_ref + scim_client_id + model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "subject_ref", "scim_client_id", "model_hash")))
    case("evidence: ham NameID/e-posta/token alanı yok",
         all(k not in json.dumps(r) for k in ("nameid_value", "email_value", "token_value", "bearer_value")))

    # 24) sızıntı tarayıcı
    case("leak: SCIM+grup+rol temiz", scan_leaks('{"scim_client_id":"sc-acme","group_name":"voiceai-ops-manager","role":"operations_manager"}') == [])
    case("leak: e-posta yakalanır", len(scan_leaks('{"x": "jdoe@acme.co"}')) > 0)
    case("leak: jwt blob yakalanır", len(scan_leaks('{"t": "eyJhbGciOiJ.eyJzdWIiOmF.abcdef"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "scim (WBS 12.1.6 — SCIM provisioning + IdP grup→rol eşleme; FR-IAM-007/SAD §14.4.4)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "grant_terminals": sorted(GRANT_TERMINALS),
        "rules": RULES,
        "reject_reasons": REJECT_REASONS,
        "realms": sorted(REALMS),
        "resource_types": sorted(RESOURCE_TYPES),
        "operations": {"provision": sorted(PROVISION_OPS), "deprovision": sorted(DEPROVISION_OPS)},
        "decision": "malformed ⇒ REJECTED(malformed_request) → op ∉ desteklenen ⇒ REJECTED(unsupported_operation) → "
                    "¬authenticated|güvenilmez ⇒ REJECTED(unauthenticated) → şema/resourceType ∉ desteklenen ⇒ "
                    "REJECTED(unsupported_schema) → client.tenant ≠ tenant ⇒ REJECTED(cross_tenant) → "
                    "version ≤ prior ⇒ REJECTED(version_conflict) → "
                    "deactivate/delete|active=false ⇒ DEPROVISIONED(erişim ANINDA ∅ + oturum iptali) | "
                    "eşlenen rol realm ≠ client realm ⇒ REJECTED(realm_escalation) | rol modelde yok ⇒ "
                    "REJECTED(unknown_role) | ∃ grup→rol ⇒ PROVISIONED effective_access[{role,scope}] | "
                    "hiç eşleşme ⇒ NO_ACCESS(no_role_mapping; default-deny)",
        "default": "REJECTED (fail-closed)",
        "fail_safe": "terminal=REJECTED ⇒ provisioning yok; DEPROVISIONED/NO_ACCESS ⇒ erişim yok",
        "core_guarantees": [
            "S3 deprovision → erişim ANINDA düşer (ÇEKİRDEK): deactivate/delete → effective_access=∅ + oturum iptali; stale_access=0 (FR-IAM-007 / SAD §14.4.4)",
            "S2 SCIM istemci auth bütünlüğü: yalnız authenticated+trusted istemci provision eder; untrusted_accepted=0 (FR-IAM-007)",
            "S4 realm/IdP sınırı: tenant SCIM yalnız tenant-realm rol, L0 ASLA; realm_escalation=0 (FR-IAM-008)",
            "S5 rol-eşleme doğruluğu: PROVISIONED rolleri ⟺ tenant eşleme tablosunda; unmapped_role_granted=0 (SAD §14.4.4)",
            "S6 idempotency/sıra güvenliği: bayat/sıra-dışı op reddedilir; deprovision dirilmez; conflict_accepted=0",
            "S7 tenant izolasyonu: istemci başka tenant subject'ini senkronlayamaz; cross_tenant=0 (FR-TEN-002)",
            "S8 least-privilege default: hiç grup eşleşmezse NO_ACCESS; privilege_on_absence=0",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "actor_realm(platform|tenant)",
                           "operation(user.create|user.replace|user.patch|user.deactivate|user.delete|group.create|group.replace|group.patch|group.delete)",
                           "prior_version(son uygulanan seq | null)",
                           "resource{type(User|Group), schema, subject_ref(opak), version(monoton seq int), active(bool), groups[](User), group_name(Group)}",
                           "scim_client{authenticated(soyut bearer/mTLS sonucu), client_id, tenant_id, realm}",
                           "idp_config{trusted_client_id, group_role_map{group→[{role,scope}]}}",
                           "inject[]", "expect", "expected{}"],
        "mapping_semantics": "grup → tenant eşleme tablosu (idp_config.group_role_map; 12.1.4 SSO ile AYNI yüzey); gruplar arası UNION; "
                             "bilinmeyen grup atlanır; eşleme yoksa NO_ACCESS (default-deny); eşlenen rol 12.1.1 modelinde olmalı + "
                             "realm=scim_client.realm; üretilen {role, scope} = 12.1.3'ün TÜKETTİĞİ scoped atama (narrowing-only)",
        "deprovision_semantics": "deactivate/delete VEYA active=false → DEPROVISIONED; effective_access=∅ + revoke_active_sessions=true; "
                                 "ANINDA (gecikmesiz); idempotent (tekrar no-op); bayat op deprovision'ı DİRİLTEMEZ (version gate)",
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "reject_reason", "deny_reason", "provisioned", "deprovisioned",
                            "sessions_revoked", "operation", "actor_realm", "resource_type", "effective_access",
                            "matched_groups", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/scim-model.json (frozen — SCIM 2.0 + auth/deprovision/eşleme/realm/version/tenant/gizlilik) + "
                 "../rbac-model/config/rbac-roles.json (12.1.1 rol→IMMUTABLE bundle + realm — eşlenen rolü çözer/doğrular)",
        "consumes": "12.1.1 RBAC modeli (rol→immutable bundle + realm); 12.1.4 SSO grup→rol eşleme tablosu yüzeyi (AYNI); "
                    "SAD §14.4.4 grup→rol eşleme; FR-IAM-008 realm ayrımı",
        "consumed_by": "12.1.3 scoped assignment (üretilen {role, scope} etkin erişimi kaynak attribute'larına karşı çözer) + "
                       "12.1.4 SSO (deprovision edilen subject login edemez) + 12.2.x backend panel guard "
                       "(oturum→permission-key; deprovision → oturum iptali) + 12.1.8 WORM audit (provisioning kararı) + "
                       "0.4.7 gözlemlenebilirlik (scim_* metrikleri)",
        "credential_free": "Bearer/mTLS doğrulaması bu modülde YOK (scim_client.authenticated soyut sonuç); canlı SCIM endpoint/token F2/PoC'de. ADR-002.",
        "trace": "FR-IAM-007, FR-IAM-008, FR-TEN-002, SR-IAM-007, TC-IAM-007, SAD §14.4.4, ADR-011, ADR-012",
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
            print("kullanım: scim_probe.py check <sample.json|dizin>")
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
