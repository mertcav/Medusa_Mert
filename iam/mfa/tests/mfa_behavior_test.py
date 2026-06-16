#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.5 — MFA (çok faktörlü kimlik doğrulama) DAVRANIŞ testi (S1–S12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (12.1.4/12.1.3 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import mfa_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
MFA = P._load(P.MFA_POLICY_PATH)
RBAC = P._load(P.RBAC_MODEL_PATH)
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "actor_realm": "tenant", "actor_role": "tenant_admin", "break_glass": False,
        "now": 1000, "tenant_policy": {}, "has_enrolled_factor": True, "failed_attempts": 0,
        "factor": {
            "type": "webauthn", "verified": True, "challenge_id": "ch-b",
            "challenge_expires_at": 1300, "subject_ref": "u-b", "tenant_id": "t-acme",
        },
        "seen_challenge_ids": [],
    }
    for k, val in kw.items():
        if k in ("factor", "tenant_policy") and isinstance(val, dict) and isinstance(d.get(k), dict):
            merged = dict(d[k]); merged.update(val); d[k] = merged
        else:
            d[k] = val
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── S1 determinizm/terminal ──
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("S1: deterministik (aynı girdi→aynı çıktı)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
case("S1: terminal'e ulaşır", r1["terminal"] in P.TERMINAL and r1["violations"]["stuck_state"] == 0)
case("S1: model_hash deterministik", r1["model_hash"] == r2["model_hash"])

# ── S2 faktör doğrulama bütünlüğü ÇEKİRDEK ──
case("S2: doğrulanmış faktör → PASS", P.build(req(), SPEC)["terminal"] == "PASS")
r = P.build(req(factor=None, has_enrolled_factor=False), SPEC)
case("S2: MFA gerekli + faktörsüz → DENY mfa_required (SR-IAM-003)", r["terminal"] == "DENY" and r["deny_reason"] == "mfa_required")
case("S2: meşru faktörsüz reddi ihlal değil (factorless_accepted=0)", r["violations"]["factorless_accepted"] == 0 and gate(r))
r = P.build(req(factor=None, has_enrolled_factor=False), SPEC, inject=["accept_factorless"])
case("S2: faktörsüz KABUL (degrade) → factorless_accepted>0 + kapı ELER", r["violations"]["factorless_accepted"] > 0 and not gate(r))
r = P.build(req(factor={"verified": False}), SPEC)
case("S2: doğrulanmamış faktör → DENY factor_failed", r["deny_reason"] == "factor_failed")
r = P.build(req(factor={"verified": False}), SPEC, inject=["accept_failed_factor"])
case("S2: başarısız faktör KABUL (degrade) → failed_factor_accepted>0 + kapı ELER", r["violations"]["failed_factor_accepted"] > 0 and not gate(r))

# ── S3 AAL yeterliliği ──
r = P.build(req(factor={"type": "password", "challenge_expires_at": 5000}), SPEC)
case("S3: tenant_admin (AAL2) + password (AAL1) → DENY insufficient_aal", r["deny_reason"] == "insufficient_aal")
r = P.build(req(factor={"type": "totp", "challenge_expires_at": 5000}), SPEC)
case("S3: totp (AAL2) tenant_admin (AAL2) için yeterli → PASS", r["terminal"] == "PASS")
r = P.build(req(factor={"type": "password", "challenge_expires_at": 5000}), SPEC, inject=["accept_insufficient_aal"])
case("S3: yetersiz AAL KABUL (degrade) → insufficient_aal_accepted>0 + kapı ELER", r["violations"]["insufficient_aal_accepted"] > 0 and not gate(r))

# ── S4 ayrıcalıkta phishing-direnci ÇEKİRDEK (ADR-017) ──
r = P.build(req(actor_realm="platform", actor_role="platform_owner", factor={"type": "webauthn", "challenge_expires_at": 5000}), SPEC)
case("S4: L0 + webauthn → PASS (AAL3 phishing-dirençli)", r["terminal"] == "PASS" and r["required_aal"] == "aal3")
r = P.build(req(actor_realm="platform", actor_role="platform_owner", factor={"type": "totp", "challenge_expires_at": 5000}), SPEC)
case("S4: L0 + totp → DENY phishing_vulnerable_factor (ADR-017)", r["deny_reason"] == "phishing_vulnerable_factor")
r = P.build(req(break_glass=True, factor={"type": "push", "challenge_expires_at": 5000}), SPEC)
case("S4: break-glass + push → DENY phishing_vulnerable_factor", r["deny_reason"] == "phishing_vulnerable_factor" and r["required_aal"] == "aal3")
r = P.build(req(tenant_policy={"required_aal": "aal2", "phishing_resistant_required": True},
                factor={"type": "totp", "challenge_expires_at": 5000}), SPEC, inject=["accept_weak_factor"])
case("S4: zayıf faktör KABUL (degrade) → weak_factor_accepted>0 + kapı ELER", r["violations"]["weak_factor_accepted"] > 0 and not gate(r))

# ── S5 politika most-restrictive-wins ──
r = P.build(req(tenant_policy={"required_aal": "aal3", "phishing_resistant_required": True},
                factor={"type": "totp", "challenge_expires_at": 5000}), SPEC)
case("S5: tenant politikası sıkılaştırır (AAL2→AAL3 phishing) → DENY phishing", r["required_aal"] == "aal3" and r["deny_reason"] == "phishing_vulnerable_factor")
r = P.build(req(tenant_policy={"required_aal": "none"}), SPEC)
case("S5: tenant 'none' zemini GEVŞETEMEZ (ayrıcalıklı rol AAL2 korunur)", r["required_aal"] == "aal2")
r = P.build(req(), SPEC, inject=["downgrade_policy"])
case("S5: politika düşürme (degrade) → policy_downgraded>0 + kapı ELER", r["violations"]["policy_downgraded"] > 0 and not gate(r))

# ── S6 challenge zaman geçerliliği ──
case("S6: süresi geçmiş challenge → DENY challenge_expired", P.build(req(now=1500, factor={"challenge_expires_at": 1300}), SPEC)["deny_reason"] == "challenge_expired")
case("S6: skew toleransı içinde → PASS", P.build(req(now=1340, factor={"challenge_expires_at": 1300}), SPEC)["terminal"] == "PASS")

# ── S7 tenant izolasyonu (FR-TEN-002) ──
r = P.build(req(factor={"tenant_id": "t-other"}), SPEC)
case("S7: faktör başka tenant → BLOCK cross_tenant", r["block_reason"] == "cross_tenant")
case("S7: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))
r = P.build(req(factor={"tenant_id": "t-other"}), SPEC, inject=["cross_tenant"])
case("S7: izolasyon atla (degrade) → cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))

# ── S8 replay + kilit koruması ──
r = P.build(req(seen_challenge_ids=["ch-b"]), SPEC)
case("S8: görülmüş challenge_id → BLOCK challenge_replay", r["block_reason"] == "challenge_replay")
r = P.build(req(seen_challenge_ids=["ch-b"]), SPEC, inject=["accept_replay"])
case("S8: replay KABUL (degrade) → replay_accepted>0 + kapı ELER", r["violations"]["replay_accepted"] > 0 and not gate(r))
r = P.build(req(failed_attempts=5), SPEC)
case("S8: 5 başarısız → BLOCK account_locked", r["block_reason"] == "account_locked")
r = P.build(req(failed_attempts=5), SPEC, inject=["bypass_lockout"])
case("S8: kilit atla (degrade) → lockout_bypassed>0 + kapı ELER", r["violations"]["lockout_bypassed"] > 0 and not gate(r))

# ── CHALLENGE (step-up) meşru ──
r = P.build(req(factor=None, has_enrolled_factor=True), SPEC)
case("step-up: CHALLENGE step_up_required (meşru) + kapı geçer", r["terminal"] == "CHALLENGE" and gate(r) and all(x == 0 for x in r["violations"].values()))

# ── S9 kanıt (ham OTP/sır/PII yok) ──
r = P.build(req(), SPEC)
case("S9: kanıt request+required_aal+factor_type+model_hash taşır",
     all(k in r["evidence"] for k in ("request_id", "required_aal", "factor_type", "model_hash")))
case("S9: ham OTP/seed/token alanı yok",
     all(k not in json.dumps(r) for k in ("otp_code_value", "totp_seed_value", "token_value", "private_key_value")))
case("S9: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

# ── S10 model bütünlük manifesti ──
r = P.build(req(), SPEC, inject=["model_tamper"])
case("S10: model tahrif → model_tampered>0 + kapı ELER", r["violations"]["model_tampered"] > 0 and not gate(r))

# ── S11/S12 gizlilik + sızıntı ──
case("S11/S12: faktör türü+rol+AAL temiz",
     P.scan_leaks('{"factor_type":"webauthn","actor_role":"tenant_admin","required_aal":"aal2","challenge_id":"ch-1"}') == [])
case("S12: e-posta yakalanır", len(P.scan_leaks('{"x":"jdoe@acme.co"}')) > 0)
case("S12: jwt blob yakalanır", len(P.scan_leaks('{"t":"eyJhbGciOiJ.eyJzdWIiOmF.abcdef"}')) > 0)

# ── unsupported faktör + unknown rol + malformed ──
case("unsupported faktör → BLOCK", P.build(req(factor={"type": "magic_link"}), SPEC)["block_reason"] == "unsupported_factor")
case("unknown rol → BLOCK", P.build(req(actor_role="super_admin"), SPEC)["block_reason"] == "unknown_role")
case("malformed (rol yok) → BLOCK", P.build(req(actor_role=None), SPEC)["block_reason"] == "malformed_request")
case("MFA gerekmiyor (qa_analyst) → PASS mfa_not_required", P.build(req(actor_role="qa_analyst", factor=None), SPEC)["pass_reason"] == "mfa_not_required")

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior test: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
