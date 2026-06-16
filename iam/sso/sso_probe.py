#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.4 — SSO: SAML 2.0 + OIDC referans probe.

12. workstream'in (IAM & Erişim) KURUMSAL SSO FEDERASYON modülü ve F2-Must yeteneği. FR-IAM-002 ('SAML 2.0 ve
OpenID Connect ile kurumsal SSO desteklenmelidir') + SAD §14.4.4 ('Kurumsal IdP (SAML 2.0/OIDC) ──login──►
Platform AuthN; IdP group/SAML attribute ──► tenant bazında rol eşleme tablosu ──► RBAC rol(leri) ──► permission
set; platform rolleri (L0) ayrı bir IdP/dizinden federe edilir, tenant IdP'leri L0 rolü atayamaz — FR-IAM-008') +
SAD §13.3 (SSO: SAML 2.0 + OIDC; kurumsal IdP federasyonu)'i sahiplenir. 12.1.1 RBAC modelini (rol→IMMUTABLE
bundle + realm, frozen) TÜKETİR ve IdP grup/attribute'unu o roller'e eşler; ÇIKTI olarak {role, scope} ATAMA
üretir — 12.1.3 scoped-assignment'ın TÜKETTİĞİ yüzey.

  SsoLoginRequest ─malformed─► protocol ─► signature ─► issuer ─► audience ─► temporal ─► replay ─► tenant ─► realm ─► mapping ─► karar
        │            │            │           │           │          │          │           │         │          │
        │  ├─ alan eksik/biçimsiz ──────────────────────────────────────────────────────────────────► BLOCK (malformed_request)
        │  ├─ protocol ∉ {saml2, oidc} ────────────────────────────────────────────────────────────► BLOCK (unsupported_protocol)
        │  ├─ signature_required ∧ ¬signature_valid ──────────────────────────────────────────────► BLOCK (invalid_signature)     [S2]
        │  ├─ issuer ≠ trusted_issuer ────────────────────────────────────────────────────────────► BLOCK (untrusted_issuer)      [S2/S5]
        │  ├─ audience ≠ expected_audience ───────────────────────────────────────────────────────► BLOCK (audience_mismatch)     [S5]
        │  ├─ now > exp+skew | now < nbf−skew | now−iat > max_age+skew ───────────────────────────► BLOCK (assertion_expired)     [S6]
        │  ├─ assertion_id ∈ seen ────────────────────────────────────────────────────────────────► BLOCK (replay_detected)       [S8]
        │  ├─ idp_config.tenant_id ≠ request tenant_id ──────────────────────────────────────────► BLOCK (cross_tenant)          [S7]
        │  ├─ eşlenen rol realm ≠ idp_config.realm (tenant IdP → L0 rolü) ────────────────────────► BLOCK (realm_escalation)      [S4]
        │  ├─ eşlenen rol 12.1.1 modelinde yok ──────────────────────────────────────────────────► BLOCK (unknown_role)
        │  ├─ ∃ grup → rol (tenant tablosu, union) ∧ realm uyar ─────────────────────────────────► GRANT assignments[{role,scope}]
        │  ├─ hiçbir grup eşleşmez ──────────────────────────────────────────────────────────────► DENY (no_role_mapping)
        │  └─ subject pasif (deprovision) ───────────────────────────────────────────────────────► DENY (account_disabled)

ÇEKİRDEK: (1) S2 İMZA/GÜVEN BÜTÜNLÜĞÜ (FR-IAM-002 ÇEKİRDEK) — yalnız imzası DOĞRULANMIŞ + GÜVENİLİR issuer'lı +
audience'ı BAĞLI assertion authenticate eder; aksi BLOCK; güvenilmez assertion ASLA kabul edilmez (untrusted_
accepted=0); (2) S3 ROL-EŞLEME DOĞRULUĞU (SAD §14.4.4 ÇEKİRDEK) — GRANT rolleri ⟺ ∃ grup tenant eşleme
tablosunda; tabloda KARŞILIĞI olmayan rol ASLA verilmez (unmapped_role_granted=0); gruplar arası BİRLEŞİM; (3) S4
REALM/IdP SINIRI (FR-IAM-008) — tenant IdP federasyonu YALNIZ tenant-realm (L1/L2) rol assert eder; platform (L0)
rolü ASLA (realm_escalation=0); L0 ayrı dizinden federe (ADR-011); (4) S7 TENANT İZOLASYONU (FR-TEN-002) — bir
tenant'ın assertion'ı başka tenant'ta oturum açamaz (cross_tenant=0); (5) S8 REPLAY KORUMASI — assertion_id
pencere içinde tek kullanımlık (replay_accepted=0). Motor DETERMİNİSTİK FAIL-CLOSED karar fonksiyonu (Date.now/
random YOK; sanal-saat tamsayı; model_hash sha256 deterministik). Her karar terminal (S1) + kanıt (S9) + model
bütünlük manifesti (S10); metrik düşük-kardinalite + ham PII yok (S11); model/spec/sample ham token/credential/
PII tutmaz — yalnız IdP id + grup/rol adı + kapsam boyut anahtar/değeri + opak subject ref + assertion-id + enum (S12).

SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): imza/anahtar/JWKS doğrulaması bu modülde YAPILMAZ (credential-free) —
assertion.signature_valid SOYUT doğrulama SONUCUDUR; canlı XML-DSig/JWS + IdP metadata F2/PoC entegrasyonunda.

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle çözümü (immutable, FR-IAM-001) → 12.1.1
(bu modül TÜKETİR — eşlenen rolü çözer/realm doğrular); permission-key gramer + katalog → 12.1.2; rol+scope atama
KAPSAM çözümü (kaynak attribute karşı) → 12.1.3 (bu modül atamayı ÜRETİR, scope kararını 12.1.3 verir); SCIM
kullanıcı/grup yaşam döngüsü (provisioning/deprovision senkron) → 12.1.6 (FR-IAM-007); MFA → 12.1.5 (FR-IAM-003);
backend panel guard (oturum→permission-key HTTP enforcement) → 12.2.x; append-only WORM audit (login kaydı) →
12.1.8; canlı kripto/IdP metadata/JWKS → F2/PoC.

Kullanım:
  sso_probe.py validate          Statik model/spec/kapsama kapısı → çıkış kodu
  sso_probe.py check <sample>     Federasyon karar motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  sso_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  sso_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK; sanal-saat tamsayı. Stdlib-only.
Sır/credential/anahtar ve ham token/PII (NameID/e-posta/imza) üretilmez/yazılmaz (fixture sentetik — yalnız IdP
id + grup/rol adı + kapsam boyut ID + opak ref + enum + assertion-id; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "sso-spec.json")
SSO_MODEL_PATH = os.path.join(HERE, "config", "sso-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["GRANT", "DENY", "BLOCK"]
TERMINAL = {"GRANT", "DENY", "BLOCK"}
GRANT_TERMINALS = {"GRANT"}
RULES = ["signature_trust_integrity", "role_mapping_correctness", "realm_idp_boundary",
         "audience_issuer_binding", "temporal_validity", "tenant_isolation", "replay_protection"]
BLOCK_REASONS = ["malformed_request", "unsupported_protocol", "invalid_signature", "untrusted_issuer",
                 "audience_mismatch", "assertion_expired", "replay_detected", "cross_tenant",
                 "realm_escalation", "unknown_role"]
DENY_REASONS = ["no_role_mapping", "account_disabled"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
PROTOCOLS = {"saml2", "oidc"}
DIMENSIONS = ["department", "brand", "campaign"]
WILDCARD = "*"

# Degrade (inject) — DOĞRU güven/eşleme/realm/zaman/replay davranışını bozan müdahaleler.
INJECTIONS = {"accept_unsigned", "untrusted_issuer_accept", "audience_bypass", "expired_accept",
              "replay_accept", "unmapped_role_grant", "realm_escalation", "cross_tenant",
              "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "untrusted_accepted", "unmapped_role_granted", "realm_escalation", "audience_mismatch_accepted",
    "expired_accepted", "cross_tenant", "replay_accepted", "model_tampered", "missing_evidence",
    "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.1/12.1.3/11.x deseniyle) — ham token/PII/sır yasak; IdP/grup/rol/kapsam ID beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|private[_-]?key|credential|client[_-]?secret)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt_blob", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("pii_field", re.compile(r"(?i)\"(nameid_value|email_value|customer_phone_value|card_pan_value|otp_code_value|password_value|customer_name_value|address_value|token_value|signature_bytes|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|aid-|idp-|sp-|g-|sso-|voiceai-|saml2?|oidc|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham token/PII/sır tarayıcı. Yorum/tarif satırı + IdP/grup/rol/kapsam ID + maskeli token eler (12.1.3 deseni)."""
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


def _sso_model():
    """Federasyon modeli = config/sso-model.json (frozen — güven/zaman/eşleme/realm)."""
    return _load(SSO_MODEL_PATH)


def _role_realm(role, rbac):
    """Bir rolün realm'i (12.1.1 frozen modelinden); rol yoksa None."""
    spec = rbac["roles"].get(role)
    return spec.get("realm") if spec else None


def _resolve_mapping(groups, group_role_map):
    """assertion.groups'u tenant eşleme tablosuna karşı çöz → (assignments, mapped_groups, unknown_groups).

    Her bilinen grup için tablo girdisinin {role, scope} atamaları toplanır (gruplar arası UNION); tabloda
    olmayan grup SESSİZCE atlanır (unknown_group_ignored). Atama yapısı = 12.1.3'ün TÜKETTİĞİ {role, scope}.
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


def build(sample, spec, inject=None, rbac=None, sso_model=None):
    """Tek SSO login senaryosunu yürüt → SsoDecision + ihlal sayaçları.

    Motor DOĞRU güven/zaman/eşleme/realm/tenant/replay davranışını hesaplar; inject (degrade) doğru davranışı
    bozar ve eşleşen ihlal sayacını artırır (12.1.3 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    rbac = rbac if rbac is not None else _rbac_model()
    sso_model = sso_model if sso_model is not None else _sso_model()

    request_id = sample.get("request_id")
    tenant_id = sample.get("tenant_id")
    actor_realm = sample.get("actor_realm")
    protocol = sample.get("protocol")
    assertion = dict(sample.get("assertion", {}) or {})
    idp = dict(sample.get("idp_config", {}) or {})
    now = sample.get("now")
    seen = set(sample.get("seen_assertion_ids", []) or [])

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    block_reason = None
    deny_reason = None
    authenticated = False
    granted = False
    resolved_assignments = []
    matched_groups = []

    # ── S10 model bütünlük manifesti (frozen sso model + 12.1.1 rol bundle/realm) ──
    canonical_model = {
        "sso": {"frozen": sso_model.get("frozen"), "protocols": sso_model.get("protocols"),
                "trust_requirements": sso_model.get("trust_requirements"),
                "realm_separation": sso_model.get("realm_separation")},
        "rbac": {"frozen": rbac.get("frozen"), "roles": rbac.get("roles")},
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["sso"]["protocols"] = list(tampered["sso"]["protocols"]) + ["__tamper__"]
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    groups = assertion.get("groups", [])

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not tenant_id or actor_realm not in REALMS
                 or protocol is None or not isinstance(assertion, dict) or not assertion
                 or not isinstance(idp, dict) or not idp
                 or not isinstance(now, int) or isinstance(now, bool)
                 or not isinstance(groups, list)
                 or not assertion.get("issuer") or not assertion.get("audience"))

    if malformed:
        terminal, block_reason = "BLOCK", "malformed_request"
    elif protocol not in PROTOCOLS:
        terminal, block_reason = "BLOCK", "unsupported_protocol"
    else:
        sig_required = idp.get("signature_required", sso_model.get("trust_requirements", {}).get("signature_required", True))
        sig_valid = bool(assertion.get("signature_valid", False))
        issuer = assertion.get("issuer")
        audience = assertion.get("audience")
        trusted_issuer = idp.get("trusted_issuer")
        expected_audience = idp.get("expected_audience")
        skew = idp.get("clock_skew_seconds", sso_model.get("temporal_policy", {}).get("default_clock_skew_seconds", 0))
        max_age = idp.get("max_assertion_age_seconds", sso_model.get("temporal_policy", {}).get("default_max_assertion_age_seconds"))
        exp = assertion.get("expires_at")
        nbf = assertion.get("not_before")
        iat = assertion.get("issued_at")
        assertion_id = assertion.get("assertion_id")

        # ── S2 imza ──
        sig_block = sig_required and not sig_valid
        if "accept_unsigned" in inject and sig_block:
            v["untrusted_accepted"] += 1
            sig_block = False  # güvenilmez imzayı kabul et (degrade)

        # ── S2/S5 güvenilir issuer ──
        issuer_block = trusted_issuer is not None and issuer != trusted_issuer
        if "untrusted_issuer_accept" in inject and issuer_block:
            v["untrusted_accepted"] += 1
            issuer_block = False

        # ── S5 audience bağı ──
        aud_block = expected_audience is not None and audience != expected_audience
        if "audience_bypass" in inject and aud_block:
            v["audience_mismatch_accepted"] += 1
            aud_block = False

        # ── S6 zaman ──
        expired = False
        if isinstance(exp, int) and now > exp + skew:
            expired = True
        if isinstance(nbf, int) and now < nbf - skew:
            expired = True
        if isinstance(max_age, int) and isinstance(iat, int) and (now - iat) > max_age + skew:
            expired = True
        if "expired_accept" in inject and expired:
            v["expired_accepted"] += 1
            expired = False

        # ── S8 replay ──
        replayed = assertion_id is not None and assertion_id in seen
        if "replay_accept" in inject and replayed:
            v["replay_accepted"] += 1
            replayed = False

        # ── S7 tenant izolasyonu (FR-TEN-002): idp_config.tenant_id = request tenant_id ──
        idp_tenant = idp.get("tenant_id")
        cross_tenant = idp_tenant is not None and idp_tenant != tenant_id
        if "cross_tenant" in inject:
            if cross_tenant:
                v["cross_tenant"] += 1
            cross_tenant = False  # izolasyonu atla (degrade)
        elif cross_tenant:
            v["cross_tenant"] += 1

        if sig_block:
            terminal, block_reason = "BLOCK", "invalid_signature"
        elif issuer_block:
            terminal, block_reason = "BLOCK", "untrusted_issuer"
        elif aud_block:
            terminal, block_reason = "BLOCK", "audience_mismatch"
        elif expired:
            terminal, block_reason = "BLOCK", "assertion_expired"
        elif replayed:
            terminal, block_reason = "BLOCK", "replay_detected"
        elif cross_tenant:
            terminal, block_reason = "BLOCK", "cross_tenant"
        else:
            # ── authenticate edildi: grup → rol eşleme (SAD §14.4.4) ──
            authenticated = True
            idp_realm = idp.get("realm", actor_realm)
            group_role_map = idp.get("group_role_map", {}) or {}
            assignments, matched_groups, _unknown = _resolve_mapping(groups, group_role_map)

            # ── S3 degrade: eşleme tablosunda OLMAYAN rol ekle (unmapped grant) ──
            if "unmapped_role_grant" in inject:
                injected_role = "tenant_admin" if idp_realm == "tenant" else "platform_owner"
                assignments = list(assignments) + [{"role": injected_role, "scope": {}, "_unmapped": True}]
                v["unmapped_role_granted"] += 1

            # ── S4 degrade: tenant IdP'ye platform (L0) rolü assert ettir (realm escalation) ──
            if "realm_escalation" in inject and idp_realm == "tenant":
                assignments = list(assignments) + [{"role": "platform_owner", "scope": {}, "_escalated": True}]
                v["realm_escalation"] += 1

            # ── eşlenen rolleri doğrula: var mı + realm uyar mı ──
            unknown_role = None
            realm_bad = None
            for a in assignments:
                role = a.get("role")
                rr = _role_realm(role, rbac)
                if rr is None:
                    unknown_role = role
                    break
                # tenant IdP yalnız tenant-realm rol; eşlenen rol realm = idp_realm (FR-IAM-008)
                if rr != idp_realm and not a.get("_escalated") and "realm_escalation" not in inject:
                    realm_bad = role
                    v["realm_escalation"] += 1
                    break

            if unknown_role is not None:
                terminal, block_reason = "BLOCK", "unknown_role"
                authenticated = True
            elif realm_bad is not None:
                terminal, block_reason = "BLOCK", "realm_escalation"
            elif "realm_escalation" in inject and idp_realm == "tenant":
                # degrade: izolasyon atlanmış sayılır → yanlışlıkla GRANT (kapı eler)
                terminal, granted = "GRANT", True
                resolved_assignments = assignments
            elif assertion.get("subject_disabled"):
                terminal, deny_reason = "DENY", "account_disabled"
            elif not assignments:
                terminal, deny_reason = "DENY", "no_role_mapping"
            else:
                terminal, granted = "GRANT", True
                resolved_assignments = assignments

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, tenant_id, actor_realm, protocol, assertion, idp, authenticated,
                         granted, resolved_assignments, matched_groups, deny_reason, block_reason, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, block_reason, deny_reason, authenticated, granted, protocol,
                 actor_realm, resolved_assignments, matched_groups, model_hash, evidence)


def _evidence(request_id, tenant_id, actor_realm, protocol, assertion, idp, authenticated, granted,
              resolved_assignments, matched_groups, deny_reason, block_reason, model_hash):
    """Yapısal kanıt — ham token/NameID/e-posta/imza YOK; yalnız IdP id + opak subject ref + grup/rol adı."""
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "actor_realm": actor_realm,
        "protocol": protocol,
        "issuer": assertion.get("issuer"),
        "audience": assertion.get("audience"),
        "subject_ref": assertion.get("subject_ref"),
        "assertion_id": assertion.get("assertion_id"),
        "idp_realm": idp.get("realm"),
        "matched_groups": matched_groups,
        "authenticated": authenticated,
        "granted": granted,
        "assignments": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in resolved_assignments],
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, block_reason, deny_reason, authenticated, granted, protocol, actor_realm,
          resolved_assignments, matched_groups, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "block_reason": block_reason,
        "deny_reason": deny_reason,
        "authenticated": authenticated,
        "granted": granted,
        "protocol": protocol,
        "actor_realm": actor_realm,
        "assignments": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in resolved_assignments],
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
        "unmapped_role_granted": "max_unmapped_role_granted",
        "realm_escalation": "max_realm_escalation",
        "audience_mismatch_accepted": "max_audience_mismatch_accepted",
        "expired_accepted": "max_expired_accepted",
        "cross_tenant": "max_cross_tenant",
        "replay_accepted": "max_replay_accepted",
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
        for key in ("terminal", "block_reason", "deny_reason", "authenticated", "granted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s authn=%s granted=%s reason=%s/%s protocol=%s roles=%s groups=%s"
              % (res["terminal"], res["authenticated"], res["granted"], res["block_reason"],
                 res["deny_reason"], res["protocol"], [a["role"] for a in res["assignments"]],
                 res["matched_groups"]))
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
              "block_reasons", "deny_reasons", "outcomes", "model", "authentication", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.1.4", spec.get("wbs") == "12.1.4")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement credential_free=true (ADR-002)", spec.get("placement", {}).get("credential_free") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-002 izlenir (SSO SAML/OIDC — ÇEKİRDEK)", "FR-IAM-002" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (tenant IdP L0 rolü atayamaz)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-IAM-002 izlenir", "SR-IAM-002" in tr.get("srs", []))
    chk("TC-IAM-002 izlenir", "TC-IAM-002" in tr.get("rtm", []))
    chk("SAD §14.4.4 SSO/SCIM rol eşleme izlenir", any("§14.4.4" in s for s in tr.get("sad", [])))
    chk("SAD §13.3 SSO SAML/OIDC izlenir", any("§13.3" in s for s in tr.get("sad", [])))
    chk("12.1.1 RBAC modeli TÜKETİLİR (consumes)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.3 scoped assignment TÜKETİR (consumed_by — atama üretilir)",
        any("12.1.3" in s for s in tr.get("consumed_by", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (signature/mapping/realm/audience/temporal/tenant/replay)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→protocol→signature→issuer→audience→temporal→replay→tenant→realm→mapping fail-closed",
        rz.get("evaluation") == "malformed_then_protocol_then_signature_then_issuer_then_audience_then_temporal_then_replay_then_tenant_then_realm_then_mapping_fail_closed")
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
    chk("block_reason taksonomisi tam (10)", br == set(BLOCK_REASONS))
    dr = set(spec["deny_reasons"].get("list", []))
    chk("deny_reason taksonomisi (no_role_mapping/account_disabled)", dr == set(DENY_REASONS))

    # 6) Model — frozen + protokoller + güven
    md = spec["model"]
    chk("model frozen=true", md.get("frozen") is True)
    chk("protokoller saml2 + oidc (FR-IAM-002)", set(md.get("protocols", [])) == PROTOCOLS)
    chk("güven gereksinimleri (signature/issuer/audience/replay)",
        set(md.get("trust_requirements", [])) == {"signature_required", "trusted_issuer_binding", "audience_binding", "replay_protection"})
    chk("rbac_model 12.1.1'e referans", "12.1.1" in md.get("rbac_model", ""))
    chk("gruplar arası UNION", md.get("union_across_groups") == "UNION")
    chk("scope narrowing-only (12.1.3'e bağ)", md.get("scope_is_narrowing_only") is True)

    # 7) Authentication — kapılar + realm/tenant kuralı
    az = spec["authentication"]
    chk("trust_gate (signature/issuer/audience)",
        all(x in az.get("trust_gate", "").lower() for x in ("signature", "issuer", "audience")))
    chk("temporal_gate (expires/not_before/max_age)",
        all(x in az.get("temporal_gate", "") for x in ("expires_at", "not_before", "max_age")))
    chk("replay_gate (assertion_id tek kullanımlık)", "assertion_id" in az.get("replay_gate", ""))
    chk("mapping_gate (grup→rol union)", "grup" in az.get("mapping_gate", "").lower() and "union" in az.get("mapping_gate", "").lower())
    chk("realm_rule (tenant IdP yalnız tenant-realm; FR-IAM-008)", "FR-IAM-008" in az.get("realm_rule", ""))
    chk("tenant_rule (cross-tenant BLOCK; FR-TEN-002)", "FR-TEN-002" in az.get("tenant_rule", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")
    chk("produces {role, scope} atama (12.1.3'e)", "12.1.3" in az.get("produces", ""))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_untrusted_accepted", "max_unmapped_role_granted", "max_realm_escalation",
               "max_audience_mismatch_accepted", "max_expired_accepted", "max_cross_tenant",
               "max_replay_accepted", "max_model_tampered", "max_missing_evidence", "max_stuck_state",
               "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("sso_login_total metrik", "sso_login_total" in obs.get("metrics", []))
    chk("sso_federation_violation_total metrik (S2/S3/S4/S7/S8 alarm)",
        "sso_federation_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/subject_ref/assertion_id YÜKSEK kard (label değil)",
        "request_id" in hi and "subject_ref" in hi and "assertion_id" in hi and "request_id" not in lo)
    chk("protocol/result/actor_realm DÜŞÜK kard (label uygun)",
        "protocol" in lo and "result" in lo and "actor_realm" in lo)
    chk("alarm untrusted/unmapped/realm/replay/cross_tenant ≤2dk",
        any(x in obs.get("alarm", "") for x in ("untrusted_accepted", "unmapped_role_granted", "realm_escalation", "replay_accepted", "cross_tenant")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)

    # 11) SSO modeli dosyası + içsel tutarlılık
    sm_ok = os.path.exists(SSO_MODEL_PATH)
    chk("config/sso-model.json var", sm_ok)
    if sm_ok:
        sm = _sso_model()
        chk("sso model frozen=true", sm.get("frozen") is True)
        chk("sso model fail_closed=true", sm.get("fail_closed") is True)
        chk("sso model protokoller saml2/oidc", set(sm.get("protocols", [])) == PROTOCOLS)
        tr_req = sm.get("trust_requirements", {})
        chk("sso model signature_required=true", tr_req.get("signature_required") is True)
        chk("sso model replay_protection=true", tr_req.get("replay_protection") is True)
        rs = sm.get("realm_separation", {})
        chk("sso model tenant_idp_grants_only_tenant_roles=true (FR-IAM-008)",
            rs.get("tenant_idp_grants_only_tenant_roles") is True)
        chk("sso model platform_idp_separate_directory=true (ADR-011)",
            rs.get("platform_idp_separate_directory") is True)
        mp = sm.get("mapping_policy", {})
        chk("sso model mapping default_deny=true", mp.get("default_deny") is True)
        chk("sso model mapping unknown_group_ignored=true", mp.get("unknown_group_ignored") is True)
        chk("sso model mapping scope_is_narrowing_only=true", mp.get("scope_is_narrowing_only") is True)
        chk("sso model privacy no_raw_token_persisted=true", sm.get("privacy", {}).get("no_raw_token_persisted") is True)

    # 12) 12.1.1 RBAC modeli erişilebilir (consumes) + realm taşır
    rbac_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rbac_ok)
    if rbac_ok:
        rbac = _rbac_model()
        chk("12.1.1 rbac frozen=true (IMMUTABLE)", rbac.get("frozen") is True)
        chk("12.1.1 12 rol (BRD §17.2)", len(rbac.get("roles", {})) == 12)
        chk("operations_manager realm=tenant (eşleme hedefi)",
            _role_realm("operations_manager", rbac) == "tenant")
        chk("platform_owner realm=platform (tenant IdP assert EDEMEZ; FR-IAM-008)",
            _role_realm("platform_owner", rbac) == "platform")

    # 13) Sır/PII tarayıcı — spec + modeller + samples
    scan_files = [SPEC_PATH, SSO_MODEL_PATH] + (
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
        # Varsayılan: SAML2, güvenilir/imzalı/geçerli assertion; grup voiceai-ops-manager → operations_manager@brand-x → GRANT (SAD §14.4.4).
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_realm": "tenant", "protocol": "saml2", "now": 1000,
            "assertion": {
                "issuer": "idp-acme", "audience": "sp-acme", "subject_ref": "u-1",
                "signature_valid": True, "issued_at": 950, "not_before": 950, "expires_at": 1300,
                "assertion_id": "aid-1", "groups": ["voiceai-ops-manager"],
            },
            "idp_config": {
                "tenant_id": "t-acme", "realm": "tenant", "trusted_issuer": "idp-acme",
                "expected_audience": "sp-acme", "signature_required": True,
                "clock_skew_seconds": 120, "max_assertion_age_seconds": 300,
                "group_role_map": {
                    "voiceai-ops-manager": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
                    "voiceai-qa": [{"role": "qa_analyst", "scope": {}}],
                },
            },
            "seen_assertion_ids": [],
        }
        for k, val in kw.items():
            if k in ("assertion", "idp_config") and isinstance(val, dict):
                merged = dict(d[k]); merged.update(val); d[k] = merged
            else:
                d[k] = val
        return d

    # 1) happy SAML2 → GRANT
    r = build(req(), spec)
    case("happy-saml2: GRANT", r["terminal"] == "GRANT")
    case("happy-saml2: authenticated=true", r["authenticated"] is True)
    case("happy-saml2: granted=true", r["granted"] is True)
    case("happy-saml2: ops rol çözüldü", r["assignments"][0]["role"] == "operations_manager")
    case("happy-saml2: scope brand-x korunur (12.1.3'e)", r["assignments"][0]["scope"] == {"brand": ["brand-x"]})
    case("happy-saml2: model_hash var (S10)", r["model_hash"] is not None)
    case("happy-saml2: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy-saml2: kapı geçer", _gate_eval(r, G)[0] is True)

    # 1b) OIDC happy → GRANT
    r = build(req(protocol="oidc"), spec)
    case("happy-oidc: GRANT", r["terminal"] == "GRANT" and r["protocol"] == "oidc")

    # 2) determinizm + model_hash deterministik
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) gruplar arası UNION → iki rol
    r = build(req(assertion={"groups": ["voiceai-ops-manager", "voiceai-qa"]}), spec)
    roles = sorted(a["role"] for a in r["assignments"])
    case("union: iki grup → operations_manager + qa_analyst", roles == ["operations_manager", "qa_analyst"])

    # 3b) unknown grup atlanır, bilinen biri map'ler → GRANT
    r = build(req(assertion={"groups": ["voiceai-ops-manager", "foreign-group-x"]}), spec)
    case("unknown-group: atlanır, GRANT", r["terminal"] == "GRANT" and r["matched_groups"] == ["voiceai-ops-manager"])

    # 4) hiç grup eşleşmez → DENY no_role_mapping (authenticate ama yetki yok)
    r = build(req(assertion={"groups": ["foreign-group-x"]}), spec)
    case("no-mapping: DENY no_role_mapping", r["terminal"] == "DENY" and r["deny_reason"] == "no_role_mapping")
    case("no-mapping: authenticated=true (login oldu)", r["authenticated"] is True)
    case("no-mapping: ihlal yok (meşru DENY)", all(x == 0 for x in r["violations"].values()))
    case("no-mapping: kapı geçer", _gate_eval(r, G)[0] is True)

    # 4b) hesap pasif → DENY account_disabled
    r = build(req(assertion={"subject_disabled": True}), spec)
    case("disabled: DENY account_disabled", r["terminal"] == "DENY" and r["deny_reason"] == "account_disabled")

    # 5) S2 imza — imzasız + signature_required → BLOCK invalid_signature (meşru güvenlik reddi)
    r = build(req(assertion={"signature_valid": False}), spec)
    case("unsigned: BLOCK invalid_signature", r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_signature")
    case("unsigned: authenticated=false", r["authenticated"] is False)
    case("unsigned: ihlal yok (doğru reddedildi)", all(x == 0 for x in r["violations"].values()))
    case("unsigned: kapı geçer (BLOCK meşru)", _gate_eval(r, G)[0] is True)

    # 5b) güvenilmez issuer → BLOCK untrusted_issuer
    r = build(req(assertion={"issuer": "idp-evil"}), spec)
    case("untrusted-issuer: BLOCK untrusted_issuer", r["terminal"] == "BLOCK" and r["block_reason"] == "untrusted_issuer")

    # 6) S5 audience — yanlış audience → BLOCK audience_mismatch
    r = build(req(assertion={"audience": "sp-other"}), spec)
    case("audience: BLOCK audience_mismatch", r["terminal"] == "BLOCK" and r["block_reason"] == "audience_mismatch")

    # 7) S6 temporal — süresi geçmiş (now > exp+skew) → BLOCK assertion_expired
    r = build(req(now=1500), spec)  # exp=1300, skew=120 → 1500 > 1420
    case("expired: BLOCK assertion_expired", r["terminal"] == "BLOCK" and r["block_reason"] == "assertion_expired")
    # skew içinde → hâlâ geçerli (exp aşıldı ama skew toleransında; max_age da uyar)
    r = build(req(now=1400, assertion={"issued_at": 1380, "not_before": 1380, "expires_at": 1350}), spec)  # now-exp=50 ≤ skew=120; age=20
    case("skew: now>exp ama ≤ exp+skew → GRANT", r["terminal"] == "GRANT")
    # not_before öncesi → BLOCK
    r = build(req(now=800, assertion={"not_before": 950}), spec)  # 800 < 950-120=830
    case("not-before: BLOCK assertion_expired", r["terminal"] == "BLOCK" and r["block_reason"] == "assertion_expired")
    # çok eski (max_age aşımı) → BLOCK
    r = build(req(now=1290, assertion={"issued_at": 950, "expires_at": 2000}), spec)  # 1290-950=340 > 300+120? no 420; not expired. use bigger
    case("max-age within: GRANT", r["terminal"] == "GRANT")
    r = build(req(now=1500, assertion={"issued_at": 950, "expires_at": 5000}), spec)  # 550 > 420 → too old
    case("max-age exceeded: BLOCK assertion_expired", r["terminal"] == "BLOCK" and r["block_reason"] == "assertion_expired")

    # 8) S8 replay — assertion_id görülmüş → BLOCK replay_detected
    r = build(req(seen_assertion_ids=["aid-1"]), spec)
    case("replay: BLOCK replay_detected", r["terminal"] == "BLOCK" and r["block_reason"] == "replay_detected")

    # 9) S7 tenant izolasyonu — idp tenant ≠ request tenant → BLOCK cross_tenant + violation (güvenlik olayı)
    r = build(req(idp_config={"tenant_id": "t-other"}), spec)
    case("cross-tenant: BLOCK cross_tenant", r["terminal"] == "BLOCK" and r["block_reason"] == "cross_tenant")
    case("cross-tenant: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 10) S4 realm — eşleme platform rol döndürse (tenant IdP) → BLOCK realm_escalation + violation
    r = build(req(idp_config={"group_role_map": {"voiceai-ops-manager": [{"role": "platform_owner", "scope": {}}]}}), spec)
    case("realm-bad: BLOCK realm_escalation", r["terminal"] == "BLOCK" and r["block_reason"] == "realm_escalation")
    case("realm-bad: realm_escalation>0 + kapı ELER", r["violations"]["realm_escalation"] > 0 and _gate_eval(r, G)[0] is False)

    # 11) unknown_role (eşleme bilinmeyen rol) → BLOCK unknown_role
    r = build(req(idp_config={"group_role_map": {"voiceai-ops-manager": [{"role": "super_admin", "scope": {}}]}}), spec)
    case("unknown-role: BLOCK unknown_role", r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_role")

    # 12) unsupported protocol → BLOCK
    r = build(req(protocol="ldap"), spec)
    case("unsupported: BLOCK unsupported_protocol", r["terminal"] == "BLOCK" and r["block_reason"] == "unsupported_protocol")

    # 13) malformed → BLOCK
    case("malformed-no-issuer: BLOCK", build(req(assertion={"issuer": None}), spec)["block_reason"] == "malformed_request")
    case("malformed-no-now: BLOCK", build(req(now=None), spec)["block_reason"] == "malformed_request")
    case("malformed-bad-realm: BLOCK", build(req(actor_realm="root"), spec)["block_reason"] == "malformed_request")

    # 14) DEGRADE accept_unsigned — imzasızı kabul et → untrusted_accepted>0 + kapı eler
    r = build(req(assertion={"signature_valid": False}), spec, inject=["accept_unsigned"])
    case("accept-unsigned: untrusted_accepted>0", r["violations"]["untrusted_accepted"] > 0)
    case("accept-unsigned: GRANT (yanlış)", r["terminal"] == "GRANT")
    case("accept-unsigned: kapı ELER", _gate_eval(r, G)[0] is False)

    # 15) DEGRADE untrusted_issuer_accept
    r = build(req(assertion={"issuer": "idp-evil"}), spec, inject=["untrusted_issuer_accept"])
    case("untrusted-issuer-accept: untrusted_accepted>0 + kapı eler", r["violations"]["untrusted_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 16) DEGRADE audience_bypass
    r = build(req(assertion={"audience": "sp-other"}), spec, inject=["audience_bypass"])
    case("audience-bypass: audience_mismatch_accepted>0 + kapı eler", r["violations"]["audience_mismatch_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) DEGRADE expired_accept
    r = build(req(now=1500), spec, inject=["expired_accept"])
    case("expired-accept: expired_accepted>0 + kapı eler", r["violations"]["expired_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) DEGRADE replay_accept
    r = build(req(seen_assertion_ids=["aid-1"]), spec, inject=["replay_accept"])
    case("replay-accept: replay_accepted>0 + kapı eler", r["violations"]["replay_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 19) DEGRADE unmapped_role_grant — eşlemede olmayan rol ver
    r = build(req(), spec, inject=["unmapped_role_grant"])
    case("unmapped-grant: unmapped_role_granted>0 + kapı eler", r["violations"]["unmapped_role_granted"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) DEGRADE realm_escalation — tenant IdP'ye L0 rolü ver
    r = build(req(), spec, inject=["realm_escalation"])
    case("realm-escalation-inject: realm_escalation>0", r["violations"]["realm_escalation"] > 0)
    case("realm-escalation-inject: GRANT (yanlış) + kapı eler", r["terminal"] == "GRANT" and _gate_eval(r, G)[0] is False)

    # 21) DEGRADE cross_tenant inject — izolasyonu atla
    r = build(req(idp_config={"tenant_id": "t-other"}), spec, inject=["cross_tenant"])
    case("cross-tenant-inject: cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) DEGRADE model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) kanıt (S9) yapısal, ham token/PII yok
    r = build(req(), spec)
    case("evidence: request + issuer + subject_ref + model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "issuer", "subject_ref", "model_hash")))
    case("evidence: ham NameID/e-posta/token alanı yok",
         all(k not in json.dumps(r) for k in ("nameid_value", "email_value", "token_value", "signature_bytes")))

    # 24) sızıntı tarayıcı
    case("leak: IdP+grup+rol temiz", scan_leaks('{"issuer":"idp-acme","groups":["voiceai-ops-manager"],"role":"operations_manager"}') == [])
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
        "module": "sso (WBS 12.1.4 — SSO: SAML 2.0 + OIDC; FR-IAM-002/SAD §14.4.4)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "grant_terminals": sorted(GRANT_TERMINALS),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "deny_reasons": DENY_REASONS,
        "realms": sorted(REALMS),
        "protocols": sorted(PROTOCOLS),
        "decision": "malformed ⇒ BLOCK(malformed_request) → protocol ∉ {saml2,oidc} ⇒ BLOCK(unsupported_protocol) → "
                    "¬signature_valid ⇒ BLOCK(invalid_signature) → issuer ≠ trusted ⇒ BLOCK(untrusted_issuer) → "
                    "audience ≠ expected ⇒ BLOCK(audience_mismatch) → temporal dışı ⇒ BLOCK(assertion_expired) → "
                    "assertion_id ∈ seen ⇒ BLOCK(replay_detected) → idp.tenant ≠ tenant ⇒ BLOCK(cross_tenant) → "
                    "eşlenen rol realm ≠ idp realm ⇒ BLOCK(realm_escalation) → rol modelde yok ⇒ BLOCK(unknown_role) → "
                    "∃ grup→rol ⇒ GRANT assignments[{role,scope}] | hiç eşleşme ⇒ DENY(no_role_mapping) | pasif ⇒ DENY(account_disabled)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ authenticate olmaz, oturum açılmaz; güvenilmez/geçersiz/tekrar/sınır ihlali ⇒ BLOCK",
        "core_guarantees": [
            "S2 imza/güven bütünlüğü: yalnız imzalı+güvenilir+audience-bağlı assertion authenticate eder; untrusted_accepted=0 (FR-IAM-002)",
            "S3 rol-eşleme doğruluğu: GRANT rolleri ⟺ tenant eşleme tablosunda; unmapped_role_granted=0 (SAD §14.4.4)",
            "S4 realm/IdP sınırı: tenant IdP yalnız tenant-realm rol, L0 ASLA; realm_escalation=0 (FR-IAM-008)",
            "S7 tenant izolasyonu: assertion başka tenant'ta oturum açamaz; cross_tenant=0 (FR-TEN-002)",
            "S8 replay koruması: assertion_id tek kullanımlık; replay_accepted=0",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "actor_realm(platform|tenant)",
                           "protocol(saml2|oidc)", "now(sanal-saat int)",
                           "assertion{issuer, audience, subject_ref, signature_valid, issued_at, not_before, expires_at, assertion_id, groups[], subject_disabled}",
                           "idp_config{tenant_id, realm, trusted_issuer, expected_audience, signature_required, clock_skew_seconds, max_assertion_age_seconds, group_role_map{group→[{role,scope}]}}",
                           "seen_assertion_ids[]", "inject[]", "expect", "expected{}"],
        "mapping_semantics": "grup → tenant eşleme tablosu (idp_config.group_role_map); gruplar arası UNION; bilinmeyen grup atlanır; "
                             "eşleme yoksa DENY no_role_mapping; eşlenen rol 12.1.1 modelinde olmalı + realm=idp_config.realm; "
                             "üretilen {role, scope} = 12.1.3'ün TÜKETTİĞİ scoped atama (narrowing-only)",
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "block_reason", "deny_reason", "authenticated", "granted", "protocol",
                            "actor_realm", "assignments", "matched_groups", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/sso-model.json (frozen — protokoller saml2/oidc + güven/zaman/eşleme/realm/tenant/gizlilik) + "
                 "../rbac-model/config/rbac-roles.json (12.1.1 rol→IMMUTABLE bundle + realm — eşlenen rolü çözer/doğrular)",
        "consumes": "12.1.1 RBAC modeli (rol→immutable bundle + realm); SAD §14.4.4 grup→rol eşleme; FR-IAM-008 realm ayrımı",
        "consumed_by": "12.1.3 scoped assignment (üretilen {role, scope} atamayı kaynak attribute'larına karşı çözer) + "
                       "12.1.6 SCIM (kullanıcı/grup yaşam döngüsü) + 12.2.x backend panel guard (oturum→permission-key) + "
                       "12.1.8 WORM audit (login kararı) + 0.4.7 gözlemlenebilirlik (sso_* metrikleri)",
        "credential_free": "İmza/anahtar/JWKS doğrulaması bu modülde YOK (signature_valid soyut sonuç); canlı kripto F2/PoC'de. ADR-002.",
        "trace": "FR-IAM-002, FR-IAM-008, FR-TEN-002, SR-IAM-002, TC-IAM-002, SAD §14.4.4, SAD §13.3, ADR-011, ADR-012",
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
            print("kullanım: sso_probe.py check <sample.json|dizin>")
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
