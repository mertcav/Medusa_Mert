#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.5 — MFA (çok faktörlü kimlik doğrulama) referans probe.

12. workstream'in (IAM & Erişim) MFA modülü ve F1-Must yeteneği. FR-IAM-003 ('Çok faktörlü kimlik doğrulama
(MFA) desteklenmelidir') + SR-IAM-003 ('Ayrıcalıklı roller için MFA zorunlu kılınabilir; MFA açıkken FAKTÖRSÜZ
erişim REDDEDİLİR') + ADR-017 ('Phishing-resistant MFA — WebAuthn/FIDO2 — L0 yöneticileri ve break-glass
onaylayıcıları için ZORUNLU; tenant için politika')'i sahiplenir. 12.1.1 RBAC modelini (rol→realm+layer, frozen)
TÜKETİR (ayrıcalık/AAL gereksinimini çözmek için) ve oturuma yansıyan rolden + actor_realm'den + break-glass
bağlamından + tenant politikasından gereken AAL'i MOST-RESTRICTIVE-WINS ile çözüp sunulan faktörü o seviyeye karşı
doğrular. MFA step-up, 12.1.4 SSO authenticate'in ÜSTÜNDE çalışır; tatmin edilmeden ayrıcalıklı oturum/eylem yok.

  MfaVerificationRequest ─malformed─► role ─► policy ─► lockout ─► factor-presence ─► verification ─► phishing ─► aal ─► temporal ─► karar
        │  ├─ alan eksik/biçimsiz ──────────────────────────────────────────────────────────────────► BLOCK (malformed_request)
        │  ├─ actor_role 12.1.1 modelinde yok ──────────────────────────────────────────────────────► BLOCK (unknown_role)
        │  ├─ gereken AAL = none (MFA gerekmiyor) ──────────────────────────────────────────────────► PASS  (mfa_not_required)
        │  ├─ failed_attempts ≥ max_failed ─────────────────────────────────────────────────────────► BLOCK (account_locked)         [S8]
        │  ├─ faktör yok ∧ kayıtlı faktör var ──────────────────────────────────────────────────────► CHALLENGE (step_up_required)
        │  ├─ faktör yok ∧ kayıtlı faktör yok ──────────────────────────────────────────────────────► DENY  (mfa_required)            [S2]
        │  ├─ factor.type ∉ katalog ────────────────────────────────────────────────────────────────► BLOCK (unsupported_factor)
        │  ├─ factor.tenant_id ≠ request tenant_id ─────────────────────────────────────────────────► BLOCK (cross_tenant)            [S7]
        │  ├─ challenge_id ∈ seen ──────────────────────────────────────────────────────────────────► BLOCK (challenge_replay)        [S8]
        │  ├─ ¬factor.verified ─────────────────────────────────────────────────────────────────────► DENY  (factor_failed)           [S2]
        │  ├─ phishing_required ∧ ¬factor.phishing_resistant ───────────────────────────────────────► DENY  (phishing_vulnerable_factor) [S4]
        │  ├─ factor.aal < required_aal ────────────────────────────────────────────────────────────► DENY  (insufficient_aal)        [S3]
        │  ├─ now > challenge_expires_at + skew ────────────────────────────────────────────────────► DENY  (challenge_expired)       [S6]
        │  └─ aksi ─────────────────────────────────────────────────────────────────────────────────► PASS  (factor_verified)

ÇEKİRDEK: (1) S2 FAKTÖR DOĞRULAMA BÜTÜNLÜĞÜ (FR-IAM-003/SR-IAM-003 ÇEKİRDEK) — MFA gerekliyken FAKTÖRSÜZ erişim
REDDEDİLİR (factorless_accepted=0); doğrulanmamış/sahte faktör ASLA geçmez (failed_factor_accepted=0); (2) S4
AYRICALIKTA PHISHING-DİRENCİ (ADR-017 ÇEKİRDEK) — L0/break-glass bağlamında yalnız WebAuthn/FIDO2; TOTP/SMS/push
ASLA (weak_factor_accepted=0); (3) S3 AAL YETERLİLİĞİ — faktör AAL'i ≥ gereken AAL (insufficient_aal_accepted=0);
(4) S5 POLİTİKA MOST-RESTRICTIVE-WINS — gereken AAL = max(zemin, tenant); tenant override yalnız-SIKILAŞTIRIR
(policy_downgraded=0); (5) S7 TENANT İZOLASYONU (FR-TEN-002) — faktör başka tenant oturumunda kullanılamaz
(cross_tenant=0); (6) S8 REPLAY + KİLİT — challenge_id tek kullanımlık + N başarısızlıkta kilit (replay_accepted=0,
lockout_bypassed=0). Motor DETERMİNİSTİK FAIL-CLOSED karar fonksiyonu (Date.now/random YOK; sanal-saat tamsayı;
model_hash sha256 deterministik). Her karar terminal (S1) + kanıt (S9) + model bütünlük manifesti (S10); metrik
düşük-kardinalite + ham PII yok (S11); model/spec/sample ham OTP/credential/faktör sırrı/PII tutmaz (S12).

SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): kriptografik faktör doğrulaması (WebAuthn attestation/assertion, TOTP HMAC,
OTP teslimi) bu modülde YAPILMAZ (credential-free) — factor.verified SOYUT doğrulama SONUCUDUR; faktör AAL/phishing-
direnci config/mfa-policy.json katalogundan TÜRETİLİR; canlı doğrulama F2/PoC entegrasyonunda.

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle çözümü (immutable) → 12.1.1 (bu modül
realm/layer'ı TÜKETİR); SSO authenticate (SAML2/OIDC) → 12.1.4 (MFA bunun üstünde step-up); backend panel guard
(oturum AAL → permission-key HTTP enforcement) → 12.2.x; break-glass akışı (Tier B onaylayıcı AAL3) → 12.3.x;
append-only WORM audit (MFA kararı kaydı) → 12.1.8; canlı kripto/WebAuthn/TOTP → F2/PoC.

Kullanım:
  mfa_probe.py validate          Statik model/spec/kapsama kapısı → çıkış kodu
  mfa_probe.py check <sample>     MFA karar motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  mfa_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  mfa_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK; sanal-saat tamsayı. Stdlib-only.
Sır/credential/faktör sırrı ve ham OTP/PII üretilmez/yazılmaz (fixture sentetik — yalnız faktör türü + rol/realm +
opak challenge/subject ref + enum; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "mfa-spec.json")
MFA_POLICY_PATH = os.path.join(HERE, "config", "mfa-policy.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["PASS", "CHALLENGE", "DENY", "BLOCK"]
TERMINAL = {"PASS", "CHALLENGE", "DENY", "BLOCK"}
SATISFIED_TERMINALS = {"PASS"}
RULES = ["factor_verification_integrity", "aal_sufficiency", "phishing_resistance_privileged",
         "policy_most_restrictive", "challenge_temporal_validity", "tenant_isolation",
         "replay_lockout_protection"]
PASS_REASONS = ["mfa_not_required", "factor_verified"]
CHALLENGE_REASONS = ["step_up_required"]
DENY_REASONS = ["mfa_required", "factor_failed", "phishing_vulnerable_factor", "insufficient_aal",
                "challenge_expired"]
BLOCK_REASONS = ["malformed_request", "unknown_role", "unsupported_factor", "challenge_replay",
                 "account_locked", "cross_tenant"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
AAL_LEVELS = ["none", "aal1", "aal2", "aal3"]
PHISHING_RESISTANT_FACTORS = {"webauthn", "fido2"}

# Degrade (inject) — DOĞRU faktör/AAL/phishing/politika/replay/kilit davranışını bozan müdahaleler.
INJECTIONS = {"accept_factorless", "accept_failed_factor", "accept_weak_factor", "accept_insufficient_aal",
              "downgrade_policy", "accept_replay", "bypass_lockout", "cross_tenant",
              "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "factorless_accepted", "failed_factor_accepted", "weak_factor_accepted", "insufficient_aal_accepted",
    "policy_downgraded", "replay_accepted", "lockout_bypassed", "cross_tenant", "model_tampered",
    "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.4/12.1.3 deseniyle) — ham OTP/faktör sırrı/PII yasak; faktör türü/rol/opak ref beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|private[_-]?key|credential|client[_-]?secret|totp[_-]?seed|shared[_-]?secret)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt_blob", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("pii_field", re.compile(r"(?i)\"(nameid_value|email_value|customer_phone_value|otp_code_value|totp_seed_value|password_value|customer_name_value|address_value|token_value|secret_value|private_key_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|ch-|idp-|sp-|sso-|mfa-|voiceai-|aal[0-3]|webauthn|fido2|totp|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham OTP/faktör sırrı/PII tarayıcı. Yorum/tarif satırı + faktör türü/rol/opak ref + maskeli token eler."""
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
    """Rol → realm + layer modeli = 12.1.1 config/rbac-roles.json (frozen, IMMUTABLE). TÜKETİLİR."""
    return _load(RBAC_MODEL_PATH)


def _mfa_policy():
    """MFA politika modeli = config/mfa-policy.json (frozen — AAL/faktör/rol/tenant/kilit/challenge)."""
    return _load(MFA_POLICY_PATH)


def _role_meta(role, rbac):
    """Bir rolün (realm, layer) bilgisi (12.1.1 frozen modelinden); rol yoksa (None, None)."""
    spec = rbac["roles"].get(role)
    if not spec:
        return (None, None)
    return (spec.get("realm"), spec.get("layer"))


def _aal_ord(level):
    """AAL ordinal (none=0 < aal1 < aal2 < aal3); bilinmeyen → -1."""
    return AAL_LEVELS.index(level) if level in AAL_LEVELS else -1


def resolve_policy(role, actor_realm, break_glass, tenant_policy, rbac, mfa_policy):
    """Gereken AAL + phishing-direnci gereksinimini MOST-RESTRICTIVE-WINS ile çöz → (required_aal, phishing, sources).

    Katkılar: (1) platform L0 (actor_realm=platform ∨ rol layer=L0) → AAL3 + phishing (ADR-017); (2) break-glass
    onaylayıcı → AAL3 + phishing (ADR-017); (3) ayrıcalıklı tenant rolü → AAL2 (SR-IAM-003); (4) tenant politikası
    (required_aal + phishing_resistant_required). Gereken AAL = max ordinal; phishing = ∃ katkı ister. Tenant
    override yalnız-SIKILAŞTIRIR (max zemini gevşetemez)."""
    rr = mfa_policy["role_requirements"]
    _realm, layer = _role_meta(role, rbac)
    contributors = []  # (aal, phishing_required, source)

    if actor_realm == "platform" or layer == "L0":
        contributors.append((rr.get("platform_l0_aal", "aal3"),
                             bool(rr.get("platform_l0_phishing_resistant", True)), "platform_l0"))
    if break_glass:
        contributors.append((rr.get("break_glass_aal", "aal3"),
                             bool(rr.get("break_glass_phishing_resistant", True)), "break_glass"))
    if role in rr.get("privileged_tenant_roles", []):
        contributors.append((rr.get("privileged_tenant_aal", "aal2"), False, "privileged_role"))

    tp = tenant_policy or {}
    tp_aal = tp.get("required_aal", mfa_policy.get("tenant_policy_model", {}).get("default_required_aal", "none"))
    tp_phish = bool(tp.get("phishing_resistant_required", False))
    if tp_aal != "none":
        contributors.append((tp_aal, tp_phish, "tenant_policy"))
    elif tp_phish:
        # phishing istenir ama AAL belirtilmemiş → en az AAL2 (phishing-dirençli faktör ≥ AAL2)
        contributors.append(("aal2", True, "tenant_policy"))

    if not contributors:
        return ("none", False, [])
    required_aal = max(contributors, key=lambda c: _aal_ord(c[0]))[0]
    phishing = any(c[1] for c in contributors)
    return (required_aal, phishing, [c[2] for c in contributors])


def build(sample, spec, inject=None, rbac=None, mfa_policy=None):
    """Tek MFA doğrulama senaryosunu yürüt → MfaDecision + ihlal sayaçları.

    Motor DOĞRU faktör/AAL/phishing/politika/tenant/replay/kilit davranışını hesaplar; inject (degrade) doğru
    davranışı bozar ve eşleşen ihlal sayacını artırır (12.1.4 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    rbac = rbac if rbac is not None else _rbac_model()
    mfa_policy = mfa_policy if mfa_policy is not None else _mfa_policy()

    request_id = sample.get("request_id")
    tenant_id = sample.get("tenant_id")
    actor_realm = sample.get("actor_realm")
    actor_role = sample.get("actor_role")
    break_glass = bool(sample.get("break_glass", False))
    tenant_policy = sample.get("tenant_policy", {})
    factor = sample.get("factor")  # dict | None
    has_enrolled = bool(sample.get("has_enrolled_factor", False))
    failed_attempts = sample.get("failed_attempts", 0)
    now = sample.get("now")
    seen = set(sample.get("seen_challenge_ids", []) or [])

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    pass_reason = None
    challenge_reason = None
    deny_reason = None
    block_reason = None
    required_aal = "none"
    phishing_required = False
    policy_sources = []
    factor_type = factor.get("type") if isinstance(factor, dict) else None
    satisfied = False

    catalog = mfa_policy.get("factor_catalog", {})
    skew = (tenant_policy or {}).get("clock_skew_seconds",
                                     mfa_policy.get("challenge_policy", {}).get("default_clock_skew_seconds", 0))
    max_failed = mfa_policy.get("lockout_policy", {}).get("max_failed_attempts", 5)

    # ── S10 model bütünlük manifesti (frozen mfa policy + 12.1.1 rol realm/layer) ──
    canonical_model = {
        "mfa": {"frozen": mfa_policy.get("frozen"), "aal_levels": mfa_policy.get("aal_levels"),
                "factor_catalog": mfa_policy.get("factor_catalog"),
                "role_requirements": mfa_policy.get("role_requirements"),
                "tenant_policy_model": mfa_policy.get("tenant_policy_model")},
        "rbac": {"frozen": rbac.get("frozen"),
                 "roles": {r: {"realm": s.get("realm"), "layer": s.get("layer")} for r, s in rbac.get("roles", {}).items()}},
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["mfa"]["factor_catalog"]["__tamper__"] = {"max_aal": "aal3", "phishing_resistant": False}
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not tenant_id or actor_realm not in REALMS or not actor_role
                 or not isinstance(now, int) or isinstance(now, bool)
                 or not isinstance(tenant_policy, dict)
                 or (factor is not None and not isinstance(factor, dict)))

    if malformed:
        terminal, block_reason = "BLOCK", "malformed_request"
    elif actor_role not in rbac.get("roles", {}):
        terminal, block_reason = "BLOCK", "unknown_role"
    else:
        # ── S5 politika çözümü (most-restrictive-wins) ──
        required_aal, phishing_required, policy_sources = resolve_policy(
            actor_role, actor_realm, break_glass, tenant_policy, rbac, mfa_policy)

        # ── S5 degrade: politikayı düşür (gereken AAL'i none'a indir) → most-restrictive ihlali ──
        if "downgrade_policy" in inject and _aal_ord(required_aal) > 0:
            v["policy_downgraded"] += 1
            required_aal, phishing_required = "none", False

        if _aal_ord(required_aal) == 0:
            terminal, pass_reason, satisfied = "PASS", "mfa_not_required", True
        else:
            # ── S8 kilit kapısı ──
            locked = isinstance(failed_attempts, int) and not isinstance(failed_attempts, bool) and failed_attempts >= max_failed
            if "bypass_lockout" in inject and locked:
                v["lockout_bypassed"] += 1
                locked = False

            if locked:
                terminal, block_reason = "BLOCK", "account_locked"
            elif not isinstance(factor, dict) or not factor:
                # ── faktör sunulmadı ──
                if "accept_factorless" in inject:
                    v["factorless_accepted"] += 1
                    terminal, pass_reason, satisfied = "PASS", "factor_verified", True
                elif has_enrolled:
                    terminal, challenge_reason = "CHALLENGE", "step_up_required"
                else:
                    terminal, deny_reason = "DENY", "mfa_required"
            else:
                fmeta = catalog.get(factor_type)
                f_tenant = factor.get("tenant_id")
                challenge_id = factor.get("challenge_id")
                ch_exp = factor.get("challenge_expires_at")
                verified = bool(factor.get("verified", False))

                # ── S7 tenant izolasyonu ──
                cross = f_tenant is not None and f_tenant != tenant_id
                if "cross_tenant" in inject:
                    if cross:
                        v["cross_tenant"] += 1
                    cross = False
                elif cross:
                    v["cross_tenant"] += 1

                # ── S8 challenge replay ──
                replayed = challenge_id is not None and challenge_id in seen
                if "accept_replay" in inject and replayed:
                    v["replay_accepted"] += 1
                    replayed = False

                if fmeta is None:
                    terminal, block_reason = "BLOCK", "unsupported_factor"
                elif cross:
                    terminal, block_reason = "BLOCK", "cross_tenant"
                elif replayed:
                    terminal, block_reason = "BLOCK", "challenge_replay"
                else:
                    f_aal = fmeta.get("max_aal", "aal1")
                    f_phish = bool(fmeta.get("phishing_resistant", False))

                    # ── S2 faktör doğrulama bütünlüğü ──
                    failed = not verified
                    if "accept_failed_factor" in inject and failed:
                        v["failed_factor_accepted"] += 1
                        failed = False

                    # ── S4 phishing-direnci (ayrıcalık; ADR-017) ──
                    weak = phishing_required and not f_phish
                    if "accept_weak_factor" in inject and weak:
                        v["weak_factor_accepted"] += 1
                        weak = False

                    # ── S3 AAL yeterliliği ──
                    insufficient = _aal_ord(f_aal) < _aal_ord(required_aal)
                    if "accept_insufficient_aal" in inject and insufficient:
                        v["insufficient_aal_accepted"] += 1
                        insufficient = False

                    # ── S6 challenge zaman geçerliliği ──
                    expired = isinstance(ch_exp, int) and now > ch_exp + skew

                    if failed:
                        terminal, deny_reason = "DENY", "factor_failed"
                    elif weak:
                        terminal, deny_reason = "DENY", "phishing_vulnerable_factor"
                    elif insufficient:
                        terminal, deny_reason = "DENY", "insufficient_aal"
                    elif expired:
                        terminal, deny_reason = "DENY", "challenge_expired"
                    else:
                        terminal, pass_reason, satisfied = "PASS", "factor_verified", True

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, tenant_id, actor_realm, actor_role, break_glass, required_aal,
                         phishing_required, policy_sources, factor_type, satisfied, terminal,
                         pass_reason, challenge_reason, deny_reason, block_reason, factor, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, pass_reason, challenge_reason, deny_reason, block_reason,
                 required_aal, phishing_required, policy_sources, factor_type, satisfied, actor_realm,
                 actor_role, model_hash, evidence)


def _evidence(request_id, tenant_id, actor_realm, actor_role, break_glass, required_aal, phishing_required,
              policy_sources, factor_type, satisfied, terminal, pass_reason, challenge_reason, deny_reason,
              block_reason, factor, model_hash):
    """Yapısal kanıt — ham OTP/faktör sırrı/NameID/e-posta YOK; yalnız faktör türü + opak challenge/subject ref."""
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "actor_realm": actor_realm,
        "actor_role": actor_role,
        "break_glass": break_glass,
        "required_aal": required_aal,
        "phishing_resistant_required": phishing_required,
        "policy_sources": policy_sources,
        "factor_type": factor_type,
        "challenge_id": factor.get("challenge_id") if isinstance(factor, dict) else None,
        "subject_ref": factor.get("subject_ref") if isinstance(factor, dict) else None,
        "satisfied": satisfied,
        "terminal": terminal,
        "pass_reason": pass_reason,
        "challenge_reason": challenge_reason,
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, pass_reason, challenge_reason, deny_reason, block_reason, required_aal,
          phishing_required, policy_sources, factor_type, satisfied, actor_realm, actor_role, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "pass_reason": pass_reason,
        "challenge_reason": challenge_reason,
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "required_aal": required_aal,
        "phishing_resistant_required": phishing_required,
        "policy_sources": policy_sources,
        "factor_type": factor_type,
        "satisfied": satisfied,
        "actor_realm": actor_realm,
        "actor_role": actor_role,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "factorless_accepted": "max_factorless_accepted",
        "failed_factor_accepted": "max_failed_factor_accepted",
        "weak_factor_accepted": "max_weak_factor_accepted",
        "insufficient_aal_accepted": "max_insufficient_aal_accepted",
        "policy_downgraded": "max_policy_downgraded",
        "replay_accepted": "max_replay_accepted",
        "lockout_bypassed": "max_lockout_bypassed",
        "cross_tenant": "max_cross_tenant",
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
        for key in ("terminal", "pass_reason", "challenge_reason", "deny_reason", "block_reason",
                    "required_aal", "satisfied"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s satisfied=%s required_aal=%s factor=%s reason=%s/%s/%s sources=%s"
              % (res["terminal"], res["satisfied"], res["required_aal"], res["factor_type"],
                 res["block_reason"], res["deny_reason"], res["challenge_reason"] or res["pass_reason"],
                 res["policy_sources"]))
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
    for f in ("wbs", "phase", "priority", "trace", "placement", "rules", "decision", "outcomes",
              "pass_reasons", "challenge_reasons", "deny_reasons", "block_reasons", "model",
              "verification", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.1.5", spec.get("wbs") == "12.1.5")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement credential_free=true (ADR-002)", spec.get("placement", {}).get("credential_free") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-003 izlenir (MFA — ÇEKİRDEK)", "FR-IAM-003" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-IAM-003 izlenir", "SR-IAM-003" in tr.get("srs", []))
    chk("TC-IAM-003 izlenir", "TC-IAM-003" in tr.get("rtm", []))
    chk("ADR-017 izlenir (phishing-resistant MFA)", any("ADR-017" in s for s in tr.get("adr", [])))
    chk("SAD §14.1 IAM/MFA izlenir", any("§14.1" in s for s in tr.get("sad", [])))
    chk("12.1.1 RBAC modeli TÜKETİLİR (consumes)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.4 SSO TÜKETİLİR (authenticate üstünde step-up)", any("12.1.4" in s for s in tr.get("consumes", [])))
    chk("12.2.x backend guard TÜKETİR (consumed_by)", any("12.2" in s for s in tr.get("consumed_by", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (verification/aal/phishing/policy/temporal/tenant/replay-lockout)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→role→policy→lockout→presence→verification→phishing→aal→temporal fail-closed",
        rz.get("evaluation") == "malformed_then_role_then_policy_then_lockout_then_factor_presence_then_verification_then_phishing_then_aal_then_temporal_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar PASS/CHALLENGE/DENY/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    chk("pass_reason taksonomisi (mfa_not_required/factor_verified)", set(spec["pass_reasons"].get("list", [])) == set(PASS_REASONS))
    chk("challenge_reason taksonomisi (step_up_required)", set(spec["challenge_reasons"].get("list", [])) == set(CHALLENGE_REASONS))
    chk("deny_reason taksonomisi tam (5)", set(spec["deny_reasons"].get("list", [])) == set(DENY_REASONS))
    chk("block_reason taksonomisi tam (6)", set(spec["block_reasons"].get("list", [])) == set(BLOCK_REASONS))

    # 6) Model — frozen + AAL + faktör + politika çözümü
    md = spec["model"]
    chk("model frozen=true", md.get("frozen") is True)
    chk("AAL seviyeleri none/aal1/aal2/aal3 ordinal", md.get("aal_levels") == AAL_LEVELS)
    chk("phishing-dirençli faktörler webauthn/fido2 (ADR-017)", set(md.get("phishing_resistant_factors", [])) == PHISHING_RESISTANT_FACTORS)
    chk("rbac_model 12.1.1'e referans", "12.1.1" in md.get("rbac_model", ""))
    chk("policy_resolution=most_restrictive_wins", md.get("policy_resolution") == "most_restrictive_wins")
    chk("override_only_tightens=true (tenant sıkılaştırır)", md.get("override_only_tightens") is True)

    # 7) Verification — kapılar + politika/tenant kuralı
    vz = spec["verification"]
    chk("presence_gate (faktörsüz → DENY mfa_required; SR-IAM-003)", "SR-IAM-003" in vz.get("presence_gate", "") and "mfa_required" in vz.get("presence_gate", ""))
    chk("integrity_gate (factor.verified → factor_failed)", "factor_failed" in vz.get("integrity_gate", ""))
    chk("phishing_gate (ADR-017 WebAuthn/FIDO2)", "ADR-017" in vz.get("phishing_gate", "") and "phishing_vulnerable_factor" in vz.get("phishing_gate", ""))
    chk("aal_gate (factor.aal ≥ required)", "insufficient_aal" in vz.get("aal_gate", ""))
    chk("temporal_gate (challenge_expires_at)", "challenge_expired" in vz.get("temporal_gate", ""))
    chk("replay_gate (challenge_id tek kullanımlık)", "challenge_id" in vz.get("replay_gate", ""))
    chk("lockout_gate (failed_attempts < max)", "account_locked" in vz.get("lockout_gate", ""))
    chk("policy_rule (max most-restrictive)", "max(" in vz.get("policy_rule", ""))
    chk("tenant_rule (cross-tenant BLOCK; FR-TEN-002)", "FR-TEN-002" in vz.get("tenant_rule", ""))
    chk("karar backend'de", vz.get("decision_at") == "backend")

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_factorless_accepted", "max_failed_factor_accepted", "max_weak_factor_accepted",
               "max_insufficient_aal_accepted", "max_policy_downgraded", "max_replay_accepted",
               "max_lockout_bypassed", "max_cross_tenant", "max_model_tampered", "max_missing_evidence",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("mfa_verification_total metrik", "mfa_verification_total" in obs.get("metrics", []))
    chk("mfa_policy_violation_total metrik (S2/S3/S4/S7/S8 alarm)", "mfa_policy_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/subject_ref/challenge_id YÜKSEK kard (label değil)",
        "request_id" in hi and "subject_ref" in hi and "challenge_id" in hi and "request_id" not in lo)
    chk("factor_type/result/required_aal DÜŞÜK kard (label uygun)",
        "factor_type" in lo and "result" in lo and "required_aal" in lo)
    chk("alarm factorless/failed/weak/insufficient/replay/lockout/cross ≤2dk",
        any(x in obs.get("alarm", "") for x in ("factorless_accepted", "weak_factor_accepted", "replay_accepted", "lockout_bypassed", "cross_tenant")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)

    # 11) MFA politika dosyası + içsel tutarlılık
    mp_ok = os.path.exists(MFA_POLICY_PATH)
    chk("config/mfa-policy.json var", mp_ok)
    if mp_ok:
        mp = _mfa_policy()
        chk("mfa policy frozen=true", mp.get("frozen") is True)
        chk("mfa policy fail_closed=true", mp.get("fail_closed") is True)
        chk("mfa policy AAL seviyeleri ordinal", mp.get("aal_levels") == AAL_LEVELS)
        cat = mp.get("factor_catalog", {})
        chk("faktör kataloğu webauthn AAL3 + phishing-dirençli (ADR-017)",
            cat.get("webauthn", {}).get("max_aal") == "aal3" and cat.get("webauthn", {}).get("phishing_resistant") is True)
        chk("faktör kataloğu totp AAL2 + phishing'e AÇIK",
            cat.get("totp", {}).get("max_aal") == "aal2" and cat.get("totp", {}).get("phishing_resistant") is False)
        chk("faktör kataloğu password AAL1 (tek faktör)", cat.get("password", {}).get("max_aal") == "aal1")
        rr = mp.get("role_requirements", {})
        chk("platform L0 → AAL3 + phishing zorunlu (ADR-017)",
            rr.get("platform_l0_aal") == "aal3" and rr.get("platform_l0_phishing_resistant") is True)
        chk("break-glass → AAL3 + phishing zorunlu (ADR-017)",
            rr.get("break_glass_aal") == "aal3" and rr.get("break_glass_phishing_resistant") is True)
        chk("ayrıcalıklı tenant rolleri AAL2 (SR-IAM-003)", rr.get("privileged_tenant_aal") == "aal2")
        chk("tenant override yalnız-sıkılaştırır", mp.get("tenant_policy_model", {}).get("override_only_tightens") is True)
        chk("kilit max_failed_attempts tanımlı", isinstance(mp.get("lockout_policy", {}).get("max_failed_attempts"), int))
        chk("challenge single_use=true", mp.get("challenge_policy", {}).get("single_use") is True)
        chk("privacy no_raw_otp_persisted=true", mp.get("privacy", {}).get("no_raw_otp_persisted") is True)

    # 12) 12.1.1 RBAC modeli erişilebilir (consumes) + realm/layer taşır
    rbac_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rbac_ok)
    if rbac_ok:
        rbac = _rbac_model()
        chk("12.1.1 rbac frozen=true (IMMUTABLE)", rbac.get("frozen") is True)
        chk("12.1.1 12 rol (BRD §17.2)", len(rbac.get("roles", {})) == 12)
        chk("platform_owner layer=L0 (AAL3 phishing zemini)", _role_meta("platform_owner", rbac)[1] == "L0")
        chk("operations_manager realm=tenant (tenant politikası)", _role_meta("operations_manager", rbac)[0] == "tenant")

    # 13) Sır/PII tarayıcı — spec + modeller + samples
    scan_files = [SPEC_PATH, MFA_POLICY_PATH] + (
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
    chk("hiç ham-OTP/faktör-sırrı/PII sızıntısı yok (S12)", total_leaks == 0)

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
        # Varsayılan: ayrıcalıklı tenant rolü (tenant_admin → AAL2 zorunlu); webauthn faktörü doğrulanmış → PASS.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_realm": "tenant", "actor_role": "tenant_admin", "break_glass": False,
            "now": 1000, "tenant_policy": {}, "has_enrolled_factor": True, "failed_attempts": 0,
            "factor": {
                "type": "webauthn", "verified": True, "challenge_id": "ch-1",
                "challenge_expires_at": 1300, "subject_ref": "u-1", "tenant_id": "t-acme",
            },
            "seen_challenge_ids": [],
        }
        for k, val in kw.items():
            if k in ("factor", "tenant_policy") and isinstance(val, dict) and isinstance(d.get(k), dict):
                merged = dict(d[k]); merged.update(val); d[k] = merged
            else:
                d[k] = val
        return d

    # 1) happy webauthn (AAL3) tenant_admin (AAL2 gereken) → PASS
    r = build(req(), spec)
    case("happy: PASS factor_verified", r["terminal"] == "PASS" and r["pass_reason"] == "factor_verified")
    case("happy: satisfied=true", r["satisfied"] is True)
    case("happy: required_aal=aal2 (ayrıcalıklı tenant rolü)", r["required_aal"] == "aal2")
    case("happy: model_hash var (S10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm + model_hash deterministik
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) MFA gerekmiyor (sade tenant rolü + politika yok) → PASS mfa_not_required
    r = build(req(actor_role="qa_analyst", factor=None), spec)
    case("not-required: PASS mfa_not_required", r["terminal"] == "PASS" and r["pass_reason"] == "mfa_not_required")
    case("not-required: required_aal=none", r["required_aal"] == "none")
    case("not-required: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 4) MFA gerekli, faktör yok ama kayıtlı → CHALLENGE step_up_required (meşru)
    r = build(req(factor=None, has_enrolled_factor=True), spec)
    case("step-up: CHALLENGE step_up_required", r["terminal"] == "CHALLENGE" and r["challenge_reason"] == "step_up_required")
    case("step-up: meşru → kapı geçer", _gate_eval(r, G)[0] is True and all(x == 0 for x in r["violations"].values()))

    # 5) S2 ÇEKİRDEK: MFA gerekli, faktör yok + kayıtlı faktör YOK → DENY mfa_required (faktörsüz reddi)
    r = build(req(factor=None, has_enrolled_factor=False), spec)
    case("factorless: DENY mfa_required (SR-IAM-003)", r["terminal"] == "DENY" and r["deny_reason"] == "mfa_required")
    case("factorless: meşru reddetme ihlal değil + kapı geçer", all(x == 0 for x in r["violations"].values()) and _gate_eval(r, G)[0])

    # 6) S2 ÇEKİRDEK: doğrulanmamış faktör → DENY factor_failed
    r = build(req(factor={"verified": False}), spec)
    case("failed: DENY factor_failed", r["terminal"] == "DENY" and r["deny_reason"] == "factor_failed")

    # 7) S4 ÇEKİRDEK (ADR-017): L0 (platform_owner) + TOTP → DENY phishing_vulnerable_factor
    r = build(req(actor_realm="platform", actor_role="platform_owner",
                  factor={"type": "totp", "challenge_expires_at": 5000}), spec)
    case("L0-weak: required_aal=aal3 + phishing", r["required_aal"] == "aal3" and r["phishing_resistant_required"] is True)
    case("L0-weak: DENY phishing_vulnerable_factor", r["terminal"] == "DENY" and r["deny_reason"] == "phishing_vulnerable_factor")
    # L0 + webauthn → PASS
    r = build(req(actor_realm="platform", actor_role="platform_owner",
                  factor={"type": "webauthn", "challenge_expires_at": 5000}), spec)
    case("L0-webauthn: PASS (AAL3 phishing-dirençli)", r["terminal"] == "PASS" and r["satisfied"] is True)

    # 8) break-glass onaylayıcı (tenant rol ama break_glass) + push → DENY phishing_vulnerable (ADR-017)
    r = build(req(break_glass=True, factor={"type": "push", "challenge_expires_at": 5000}), spec)
    case("break-glass-weak: required AAL3 phishing", r["required_aal"] == "aal3" and r["phishing_resistant_required"] is True)
    case("break-glass-weak: DENY phishing_vulnerable_factor", r["deny_reason"] == "phishing_vulnerable_factor")

    # 9) S3 AAL yeterliliği: tenant_admin (AAL2) + password (AAL1) → DENY insufficient_aal
    r = build(req(factor={"type": "password", "challenge_expires_at": 5000}), spec)
    case("insufficient: DENY insufficient_aal", r["terminal"] == "DENY" and r["deny_reason"] == "insufficient_aal")
    # AAL2 faktör (totp) tenant_admin için yeterli (phishing istenmez) → PASS
    r = build(req(factor={"type": "totp", "challenge_expires_at": 5000}), spec)
    case("aal2-ok: totp tenant_admin için PASS", r["terminal"] == "PASS")

    # 10) S5 politika most-restrictive: tenant politikası AAL3 phishing ister → tenant_admin + totp DENY phishing
    r = build(req(tenant_policy={"required_aal": "aal3", "phishing_resistant_required": True},
                  factor={"type": "totp", "challenge_expires_at": 5000}), spec)
    case("tenant-policy-tighten: required AAL3 phishing", r["required_aal"] == "aal3" and r["phishing_resistant_required"] is True)
    case("tenant-policy-tighten: DENY phishing_vulnerable_factor", r["deny_reason"] == "phishing_vulnerable_factor")
    # tenant politikası none → ayrıcalıklı rol zemini (AAL2) korunur (gevşetemez)
    r = build(req(tenant_policy={"required_aal": "none"}), spec)
    case("tenant-policy-cannot-loosen: zemin AAL2 korunur", r["required_aal"] == "aal2")

    # 11) S6 challenge süresi geçmiş → DENY challenge_expired
    r = build(req(now=1500, factor={"challenge_expires_at": 1300}), spec)  # skew=60 → 1500 > 1360
    case("expired: DENY challenge_expired", r["terminal"] == "DENY" and r["deny_reason"] == "challenge_expired")
    # skew toleransı içinde → PASS
    r = build(req(now=1340, factor={"challenge_expires_at": 1300}), spec)  # 1340 ≤ 1360
    case("skew: now>exp ama ≤ exp+skew → PASS", r["terminal"] == "PASS")

    # 12) S7 tenant izolasyonu: faktör başka tenant → BLOCK cross_tenant + violation
    r = build(req(factor={"tenant_id": "t-other"}), spec)
    case("cross-tenant: BLOCK cross_tenant", r["terminal"] == "BLOCK" and r["block_reason"] == "cross_tenant")
    case("cross-tenant: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) S8 replay: görülmüş challenge_id → BLOCK challenge_replay
    r = build(req(seen_challenge_ids=["ch-1"]), spec)
    case("replay: BLOCK challenge_replay", r["terminal"] == "BLOCK" and r["block_reason"] == "challenge_replay")

    # 14) S8 kilit: failed_attempts ≥ max → BLOCK account_locked
    r = build(req(failed_attempts=5), spec)
    case("lockout: BLOCK account_locked", r["terminal"] == "BLOCK" and r["block_reason"] == "account_locked")

    # 15) unsupported faktör → BLOCK unsupported_factor
    r = build(req(factor={"type": "magic_link"}), spec)
    case("unsupported: BLOCK unsupported_factor", r["terminal"] == "BLOCK" and r["block_reason"] == "unsupported_factor")

    # 16) unknown rol → BLOCK unknown_role
    r = build(req(actor_role="super_admin"), spec)
    case("unknown-role: BLOCK unknown_role", r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_role")

    # 17) malformed → BLOCK
    case("malformed-no-role: BLOCK", build(req(actor_role=None), spec)["block_reason"] == "malformed_request")
    case("malformed-no-now: BLOCK", build(req(now=None), spec)["block_reason"] == "malformed_request")
    case("malformed-bad-realm: BLOCK", build(req(actor_realm="root"), spec)["block_reason"] == "malformed_request")

    # 18) DEGRADE accept_factorless — faktörsüzü kabul et → factorless_accepted>0 + kapı eler
    r = build(req(factor=None, has_enrolled_factor=False), spec, inject=["accept_factorless"])
    case("accept-factorless: factorless_accepted>0", r["violations"]["factorless_accepted"] > 0)
    case("accept-factorless: PASS (yanlış) + kapı ELER", r["terminal"] == "PASS" and _gate_eval(r, G)[0] is False)

    # 19) DEGRADE accept_failed_factor
    r = build(req(factor={"verified": False}), spec, inject=["accept_failed_factor"])
    case("accept-failed: failed_factor_accepted>0 + kapı eler", r["violations"]["failed_factor_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) DEGRADE accept_weak_factor (ADR-017 ihlali) — phishing AAL2'de istenir, totp AAL2 yeter ama phishing'e açık
    r = build(req(tenant_policy={"required_aal": "aal2", "phishing_resistant_required": True},
                  factor={"type": "totp", "challenge_expires_at": 5000}), spec, inject=["accept_weak_factor"])
    case("accept-weak: weak_factor_accepted>0 + PASS (yanlış) + kapı eler",
         r["violations"]["weak_factor_accepted"] > 0 and r["terminal"] == "PASS" and _gate_eval(r, G)[0] is False)

    # 21) DEGRADE accept_insufficient_aal
    r = build(req(factor={"type": "password", "challenge_expires_at": 5000}), spec, inject=["accept_insufficient_aal"])
    case("accept-insufficient: insufficient_aal_accepted>0 + kapı eler", r["violations"]["insufficient_aal_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) DEGRADE downgrade_policy
    r = build(req(), spec, inject=["downgrade_policy"])
    case("downgrade-policy: policy_downgraded>0 + kapı eler", r["violations"]["policy_downgraded"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) DEGRADE accept_replay
    r = build(req(seen_challenge_ids=["ch-1"]), spec, inject=["accept_replay"])
    case("accept-replay: replay_accepted>0 + kapı eler", r["violations"]["replay_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 24) DEGRADE bypass_lockout
    r = build(req(failed_attempts=5), spec, inject=["bypass_lockout"])
    case("bypass-lockout: lockout_bypassed>0 + kapı eler", r["violations"]["lockout_bypassed"] > 0 and _gate_eval(r, G)[0] is False)

    # 25) DEGRADE cross_tenant
    r = build(req(factor={"tenant_id": "t-other"}), spec, inject=["cross_tenant"])
    case("cross-tenant-inject: cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 26) DEGRADE model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 27) kanıt (S9) yapısal, ham OTP/sır/PII yok
    r = build(req(), spec)
    case("evidence: request + required_aal + factor_type + model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "required_aal", "factor_type", "model_hash")))
    case("evidence: ham OTP/seed/token alanı yok",
         all(k not in json.dumps(r) for k in ("otp_code_value", "totp_seed_value", "token_value", "private_key_value")))

    # 28) sızıntı tarayıcı
    case("leak: faktör türü+rol temiz", scan_leaks('{"factor_type":"webauthn","actor_role":"tenant_admin","required_aal":"aal2"}') == [])
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
        "module": "mfa (WBS 12.1.5 — MFA çok faktörlü kimlik doğrulama; FR-IAM-003/SR-IAM-003/ADR-017)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "satisfied_terminals": sorted(SATISFIED_TERMINALS),
        "rules": RULES,
        "pass_reasons": PASS_REASONS,
        "challenge_reasons": CHALLENGE_REASONS,
        "deny_reasons": DENY_REASONS,
        "block_reasons": BLOCK_REASONS,
        "realms": sorted(REALMS),
        "aal_levels": AAL_LEVELS,
        "phishing_resistant_factors": sorted(PHISHING_RESISTANT_FACTORS),
        "decision": "malformed ⇒ BLOCK(malformed_request) → rol ∉ 12.1.1 ⇒ BLOCK(unknown_role) → gereken AAL=none ⇒ "
                    "PASS(mfa_not_required) → failed≥max ⇒ BLOCK(account_locked) → faktör yok ∧ kayıtlı ⇒ "
                    "CHALLENGE(step_up_required) → faktör yok ∧ kayıtsız ⇒ DENY(mfa_required) → tür ∉ katalog ⇒ "
                    "BLOCK(unsupported_factor) → factor.tenant ≠ tenant ⇒ BLOCK(cross_tenant) → challenge_id ∈ seen ⇒ "
                    "BLOCK(challenge_replay) → ¬verified ⇒ DENY(factor_failed) → phishing_req ∧ ¬phishing ⇒ "
                    "DENY(phishing_vulnerable_factor) → aal < required ⇒ DENY(insufficient_aal) → süresi geçmiş ⇒ "
                    "DENY(challenge_expired) → aksi ⇒ PASS(factor_verified)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK/DENY ⇒ MFA tatmin edilmez, ayrıcalıklı oturum/eylem açılmaz; faktörsüz/zayıf/geçersiz/tekrar/sınır ihlali ⇒ reddedilir",
        "core_guarantees": [
            "S2 faktör doğrulama bütünlüğü: MFA gerekliyken faktörsüz erişim reddedilir; doğrulanmamış faktör geçmez; factorless_accepted=0 ∧ failed_factor_accepted=0 (FR-IAM-003/SR-IAM-003)",
            "S4 ayrıcalıkta phishing-direnci: L0/break-glass yalnız WebAuthn/FIDO2; weak_factor_accepted=0 (ADR-017)",
            "S3 AAL yeterliliği: faktör AAL'i ≥ gereken AAL; insufficient_aal_accepted=0 (SR-IAM-003)",
            "S5 politika most-restrictive-wins: gereken AAL = max(zemin, tenant); tenant yalnız sıkılaştırır; policy_downgraded=0",
            "S7 tenant izolasyonu: faktör başka tenant oturumunda kullanılamaz; cross_tenant=0 (FR-TEN-002)",
            "S8 replay+kilit: challenge_id tek kullanımlık + N başarısızlıkta kilit; replay_accepted=0 ∧ lockout_bypassed=0",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "actor_realm(platform|tenant)",
                           "actor_role(12.1.1 rol)", "break_glass(bool)", "now(sanal-saat int)",
                           "tenant_policy{required_aal, phishing_resistant_required, clock_skew_seconds}",
                           "factor{type, verified, challenge_id, challenge_expires_at, subject_ref, tenant_id} | null",
                           "has_enrolled_factor(bool)", "failed_attempts(int)", "seen_challenge_ids[]",
                           "inject[]", "expect", "expected{}"],
        "policy_semantics": "gereken AAL = MOST-RESTRICTIVE-WINS(platform_l0[AAL3+phishing, ADR-017], "
                            "break_glass[AAL3+phishing, ADR-017], privileged_tenant_role[AAL2], tenant_policy); "
                            "phishing_required = ∃ katkı ister; tenant override yalnız-SIKILAŞTIRIR (zemini gevşetemez); "
                            "faktör AAL/phishing-direnci config/mfa-policy.json katalogundan TÜRETİLİR (credential-free)",
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "pass_reason", "challenge_reason", "deny_reason", "block_reason",
                            "required_aal", "phishing_resistant_required", "policy_sources", "factor_type",
                            "satisfied", "actor_realm", "actor_role", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/mfa-policy.json (frozen — AAL/faktör kataloğu/rol gereksinimi/tenant override/kilit/challenge/gizlilik) + "
                 "../rbac-model/config/rbac-roles.json (12.1.1 rol→realm+layer — ayrıcalık/AAL gereksinimi çözümü)",
        "consumes": "12.1.1 RBAC modeli (rol→realm+layer); 12.1.4 SSO (authenticate identity — MFA step-up üstünde); ADR-017 phishing-resistant",
        "consumed_by": "12.2.x backend panel guard (oturum AAL → permission-key enforcement) + "
                       "12.3.x break-glass (Tier B onaylayıcı AAL3 phishing-dirençli) + "
                       "12.1.8 WORM audit (MFA kararı) + 0.4.7 gözlemlenebilirlik (mfa_* metrikleri)",
        "credential_free": "Kriptografik faktör doğrulaması bu modülde YOK (factor.verified soyut sonuç); AAL/phishing-direnci katalogdan türetilir; canlı WebAuthn/TOTP/OTP F2/PoC'de. ADR-002.",
        "trace": "FR-IAM-003, FR-TEN-002, SR-IAM-003, TC-IAM-003, SAD §14.1, ADR-017, ADR-011, ADR-002",
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
            print("kullanım: mfa_probe.py check <sample.json|dizin>")
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
