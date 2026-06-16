#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.4 — SSO: SAML 2.0 + OIDC DAVRANIŞ testi (S1–S12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (12.1.3/12.1.1 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import sso_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
SSO = P._load(P.SSO_MODEL_PATH)
RBAC = P._load(P.RBAC_MODEL_PATH)
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "actor_realm": "tenant", "protocol": "saml2", "now": 1000,
        "assertion": {
            "issuer": "idp-acme", "audience": "sp-acme", "subject_ref": "u-b",
            "signature_valid": True, "issued_at": 950, "not_before": 950, "expires_at": 1300,
            "assertion_id": "aid-b", "groups": ["voiceai-ops-manager"],
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


def gate(r):
    return P._gate_eval(r, G)[0]


# ── S1 determinizm/terminal ──
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("S1: deterministik (aynı girdi→aynı çıktı)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
case("S1: terminal'e ulaşır", r1["terminal"] in P.TERMINAL and r1["violations"]["stuck_state"] == 0)
case("S1: model_hash deterministik", r1["model_hash"] == r2["model_hash"])

# ── S2 imza/güven bütünlüğü ÇEKİRDEK ──
case("S2: imzalı+güvenilir → GRANT (authenticate)", P.build(req(), SPEC)["terminal"] == "GRANT")
r = P.build(req(assertion={"signature_valid": False}), SPEC)
case("S2: imzasız → BLOCK invalid_signature (authenticate olmaz)", r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_signature")
case("S2: doğru reddetme ihlal değil (untrusted_accepted=0)", r["violations"]["untrusted_accepted"] == 0 and gate(r))
r = P.build(req(assertion={"signature_valid": False}), SPEC, inject=["accept_unsigned"])
case("S2: imzasız KABUL (degrade) → untrusted_accepted>0 + kapı ELER", r["violations"]["untrusted_accepted"] > 0 and not gate(r))
r = P.build(req(assertion={"issuer": "idp-evil"}), SPEC)
case("S2: güvenilmez issuer → BLOCK untrusted_issuer", r["block_reason"] == "untrusted_issuer")

# ── S3 rol-eşleme doğruluğu ÇEKİRDEK ──
r = P.build(req(), SPEC)
case("S3: grup → eşlenen rol (operations_manager)", r["assignments"][0]["role"] == "operations_manager")
case("S3: scope (brand-x) korunur — 12.1.3'e atama", r["assignments"][0]["scope"] == {"brand": ["brand-x"]})
r = P.build(req(assertion={"groups": ["voiceai-ops-manager", "voiceai-qa"]}), SPEC)
case("S3: gruplar arası UNION (iki rol)", sorted(a["role"] for a in r["assignments"]) == ["operations_manager", "qa_analyst"])
r = P.build(req(assertion={"groups": ["foreign-x"]}), SPEC)
case("S3: eşleme yok → DENY no_role_mapping (authenticate ama yetki yok)", r["terminal"] == "DENY" and r["deny_reason"] == "no_role_mapping")
r = P.build(req(), SPEC, inject=["unmapped_role_grant"])
case("S3: unmapped rol verilir (degrade) → unmapped_role_granted>0 + kapı ELER", r["violations"]["unmapped_role_granted"] > 0 and not gate(r))

# ── S4 realm/IdP sınırı (FR-IAM-008) ──
r = P.build(req(idp_config={"group_role_map": {"voiceai-ops-manager": [{"role": "platform_owner", "scope": {}}]}}), SPEC)
case("S4: tenant IdP platform rolü → BLOCK realm_escalation", r["block_reason"] == "realm_escalation")
case("S4: realm_escalation>0 + kapı ELER", r["violations"]["realm_escalation"] > 0 and not gate(r))
r = P.build(req(), SPEC, inject=["realm_escalation"])
case("S4: L0 rolü zorla (degrade) → realm_escalation>0 + kapı ELER", r["violations"]["realm_escalation"] > 0 and not gate(r))

# ── S5 audience/issuer bağı ──
r = P.build(req(assertion={"audience": "sp-other"}), SPEC)
case("S5: yanlış audience → BLOCK audience_mismatch", r["block_reason"] == "audience_mismatch")
r = P.build(req(assertion={"audience": "sp-other"}), SPEC, inject=["audience_bypass"])
case("S5: audience bypass (degrade) → audience_mismatch_accepted>0 + kapı ELER", r["violations"]["audience_mismatch_accepted"] > 0 and not gate(r))

# ── S6 zaman geçerliliği ──
case("S6: süresi geçmiş → BLOCK assertion_expired", P.build(req(now=1500), SPEC)["block_reason"] == "assertion_expired")
case("S6: not_before öncesi → BLOCK", P.build(req(now=800), SPEC)["block_reason"] == "assertion_expired")
case("S6: skew toleransı içinde → GRANT", P.build(req(now=1400, assertion={"issued_at": 1380, "not_before": 1380, "expires_at": 1350}), SPEC)["terminal"] == "GRANT")
r = P.build(req(now=1500), SPEC, inject=["expired_accept"])
case("S6: expired kabul (degrade) → expired_accepted>0 + kapı ELER", r["violations"]["expired_accepted"] > 0 and not gate(r))

# ── S7 tenant izolasyonu (FR-TEN-002) ──
r = P.build(req(idp_config={"tenant_id": "t-other"}), SPEC)
case("S7: idp tenant ≠ request tenant → BLOCK cross_tenant", r["block_reason"] == "cross_tenant")
case("S7: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))
r = P.build(req(idp_config={"tenant_id": "t-other"}), SPEC, inject=["cross_tenant"])
case("S7: izolasyon atla (degrade) → cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))

# ── S8 replay koruması ──
r = P.build(req(seen_assertion_ids=["aid-b"]), SPEC)
case("S8: görülmüş assertion_id → BLOCK replay_detected", r["block_reason"] == "replay_detected")
r = P.build(req(seen_assertion_ids=["aid-b"]), SPEC, inject=["replay_accept"])
case("S8: replay kabul (degrade) → replay_accepted>0 + kapı ELER", r["violations"]["replay_accepted"] > 0 and not gate(r))

# ── S9 kanıt (ham token/PII yok) ──
r = P.build(req(), SPEC)
case("S9: kanıt request+issuer+subject_ref+model_hash taşır",
     all(k in r["evidence"] for k in ("request_id", "issuer", "subject_ref", "model_hash")))
case("S9: ham NameID/e-posta/token alanı yok",
     all(k not in json.dumps(r) for k in ("nameid_value", "email_value", "token_value", "signature_bytes")))
case("S9: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

# ── S10 model bütünlük manifesti ──
r = P.build(req(), SPEC, inject=["model_tamper"])
case("S10: model tahrif → model_tampered>0 + kapı ELER", r["violations"]["model_tampered"] > 0 and not gate(r))

# ── S11/S12 gizlilik + sızıntı ──
case("S11/S12: IdP+grup+rol+kapsam temiz",
     P.scan_leaks('{"issuer":"idp-acme","groups":["voiceai-ops-manager"],"role":"operations_manager","scope":{"brand":["brand-x"]}}') == [])
case("S12: e-posta yakalanır", len(P.scan_leaks('{"x":"jdoe@acme.co"}')) > 0)
case("S12: jwt blob yakalanır", len(P.scan_leaks('{"t":"eyJhbGciOiJ.eyJzdWIiOmF.abcdef"}')) > 0)

# ── unsupported protocol + malformed ──
case("unsupported protokol → BLOCK", P.build(req(protocol="ldap"), SPEC)["block_reason"] == "unsupported_protocol")
case("malformed (issuer yok) → BLOCK", P.build(req(assertion={"issuer": None}), SPEC)["block_reason"] == "malformed_request")

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior test: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
