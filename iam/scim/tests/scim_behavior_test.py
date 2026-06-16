#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.6 — SCIM provisioning + IdP grup→rol eşleme DAVRANIŞ testi (S1–S12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (12.1.4/12.1.3/12.1.1 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import scim_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
SCIM = P._load(P.SCIM_MODEL_PATH)
RBAC = P._load(P.RBAC_MODEL_PATH)
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "actor_realm": "tenant", "operation": "user.create", "prior_version": None,
        "resource": {
            "type": "User", "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
            "subject_ref": "sub-b", "version": 5, "active": True,
            "groups": ["voiceai-ops-manager"],
        },
        "scim_client": {"authenticated": True, "client_id": "sc-acme", "tenant_id": "t-acme", "realm": "tenant"},
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


def gate(r):
    return P._gate_eval(r, G)[0]


# ── S1 determinizm/terminal ──
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("S1: deterministik (aynı girdi→aynı çıktı)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
case("S1: terminal'e ulaşır", r1["terminal"] in P.TERMINAL and r1["violations"]["stuck_state"] == 0)
case("S1: model_hash deterministik", r1["model_hash"] == r2["model_hash"])

# ── S2 SCIM istemci auth bütünlüğü ──
case("S2: authenticated+trusted → PROVISIONED", P.build(req(), SPEC)["terminal"] == "PROVISIONED")
r = P.build(req(scim_client={"authenticated": False}), SPEC)
case("S2: kimliği doğrulanmamış → REJECTED unauthenticated", r["terminal"] == "REJECTED" and r["reject_reason"] == "unauthenticated")
case("S2: doğru reddetme ihlal değil (untrusted_accepted=0)", r["violations"]["untrusted_accepted"] == 0 and gate(r))
r = P.build(req(scim_client={"authenticated": False}), SPEC, inject=["accept_untrusted_client"])
case("S2: güvenilmez KABUL (degrade) → untrusted_accepted>0 + kapı ELER", r["violations"]["untrusted_accepted"] > 0 and not gate(r))
r = P.build(req(scim_client={"client_id": "sc-evil"}), SPEC)
case("S2: güvenilmez client_id → REJECTED unauthenticated", r["reject_reason"] == "unauthenticated")

# ── S3 DEPROVISION → ERİŞİM ANINDA DÜŞER (ÇEKİRDEK; FR-IAM-007) ──
r = P.build(req(operation="user.deactivate", prior_version=5, resource={"active": False, "version": 6}), SPEC)
case("S3: deactivate → DEPROVISIONED", r["terminal"] == "DEPROVISIONED" and r["deprovisioned"] is True)
case("S3: etkin erişim ANINDA ∅ (rol korunmaz)", r["effective_access"] == [])
case("S3: etkin oturum/token İPTAL (revoke=true)", r["sessions_revoked"] is True)
case("S3: meşru deprovision ihlal değil (stale_access=0)", r["violations"]["stale_access"] == 0 and gate(r))
r = P.build(req(operation="user.delete", prior_version=5, resource={"version": 6}), SPEC)
case("S3: delete → DEPROVISIONED + erişim ∅", r["terminal"] == "DEPROVISIONED" and r["effective_access"] == [])
r = P.build(req(operation="user.replace", prior_version=5, resource={"active": False, "version": 6}), SPEC)
case("S3: replace active=false → DEPROVISIONED (update ile deaktivasyon)", r["terminal"] == "DEPROVISIONED")
r = P.build(req(operation="user.deactivate", prior_version=5, resource={"active": False, "version": 6}), SPEC,
            inject=["stale_access_after_deprovision"])
case("S3 ÇEKİRDEK: deprovision erişim DÜŞÜRMEZ (degrade) → stale_access>0 + kapı ELER", r["violations"]["stale_access"] > 0 and not gate(r))
case("S3 ÇEKİRDEK: degrade'de erişim/oturum bırakılır (kanıt)", r["effective_access"] != [] and r["sessions_revoked"] is False)

# ── S4 realm/IdP sınırı (FR-IAM-008) ──
r = P.build(req(idp_config={"group_role_map": {"voiceai-ops-manager": [{"role": "platform_owner", "scope": {}}]}}), SPEC)
case("S4: tenant SCIM L0 rolü → REJECTED realm_escalation", r["reject_reason"] == "realm_escalation")
case("S4: realm_escalation>0 + kapı ELER", r["violations"]["realm_escalation"] > 0 and not gate(r))
r = P.build(req(), SPEC, inject=["realm_escalation"])
case("S4: L0 rolü zorla (degrade) → realm_escalation>0 + kapı ELER", r["violations"]["realm_escalation"] > 0 and not gate(r))

# ── S5 rol-eşleme doğruluğu ──
r = P.build(req(), SPEC)
case("S5: grup → eşlenen rol (operations_manager)", r["effective_access"][0]["role"] == "operations_manager")
case("S5: scope (brand-x) korunur — 12.1.3'e atama", r["effective_access"][0]["scope"] == {"brand": ["brand-x"]})
r = P.build(req(resource={"groups": ["voiceai-ops-manager", "voiceai-qa"]}), SPEC)
case("S5: gruplar arası UNION (iki rol)", sorted(a["role"] for a in r["effective_access"]) == ["operations_manager", "qa_analyst"])
r = P.build(req(), SPEC, inject=["unmapped_role_grant"])
case("S5: unmapped rol verilir (degrade) → unmapped_role_granted>0 + kapı ELER", r["violations"]["unmapped_role_granted"] > 0 and not gate(r))

# ── S6 idempotency/sıra güvenliği ──
r = P.build(req(operation="user.replace", prior_version=5, resource={"version": 4}), SPEC)
case("S6: bayat op (version ≤ prior) → REJECTED version_conflict", r["reject_reason"] == "version_conflict")
r = P.build(req(operation="user.replace", prior_version=5, resource={"version": 5}), SPEC)
case("S6: eşit version (replay) → REJECTED version_conflict", r["reject_reason"] == "version_conflict")
r = P.build(req(operation="user.replace", prior_version=5, resource={"version": 6}), SPEC)
case("S6: ileri version → uygulanır (PROVISIONED)", r["terminal"] == "PROVISIONED")
r = P.build(req(operation="user.replace", prior_version=5, resource={"version": 3, "active": True}), SPEC, inject=["conflict_accept"])
case("S6: bayat op uygulanır (degrade — diriltir) → conflict_accepted>0 + kapı ELER", r["violations"]["conflict_accepted"] > 0 and not gate(r))

# ── S7 tenant izolasyonu (FR-TEN-002) ──
r = P.build(req(scim_client={"tenant_id": "t-other"}), SPEC)
case("S7: client tenant ≠ request tenant → REJECTED cross_tenant", r["reject_reason"] == "cross_tenant")
case("S7: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))
r = P.build(req(scim_client={"tenant_id": "t-other"}), SPEC, inject=["cross_tenant"])
case("S7: izolasyon atla (degrade) → cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))

# ── S8 least-privilege default ──
r = P.build(req(resource={"groups": ["foreign-x"]}), SPEC)
case("S8: hiç grup eşleşmez → NO_ACCESS (default-deny)", r["terminal"] == "NO_ACCESS" and r["deny_reason"] == "no_role_mapping")
case("S8: NO_ACCESS etkin erişim ∅ + ihlal yok", r["effective_access"] == [] and gate(r))
r = P.build(req(resource={"groups": ["foreign-x"]}), SPEC, inject=["grant_on_absence"])
case("S8: yokluğa dayalı yetki (degrade) → privilege_on_absence>0 + kapı ELER", r["violations"]["privilege_on_absence"] > 0 and not gate(r))

# ── Group resource yaşam döngüsü (kullanıcı+grup senkronu, FR-IAM-007) ──
r = P.build(req(operation="group.create",
                resource={"type": "Group", "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
                          "group_name": "voiceai-qa", "subject_ref": "grp-1", "version": 1, "groups": None}), SPEC)
case("Group: group.create → PROVISIONED qa_analyst bağı", r["terminal"] == "PROVISIONED" and r["effective_access"][0]["role"] == "qa_analyst")
r = P.build(req(operation="group.delete", prior_version=1,
                resource={"type": "Group", "group_name": "voiceai-qa", "subject_ref": "grp-1", "version": 2, "groups": None}), SPEC)
case("Group: group.delete → DEPROVISIONED + erişim ∅", r["terminal"] == "DEPROVISIONED" and r["effective_access"] == [])

# ── S9 kanıt (ham token/PII yok) ──
r = P.build(req(), SPEC)
case("S9: kanıt request+subject_ref+scim_client_id+model_hash taşır",
     all(k in r["evidence"] for k in ("request_id", "subject_ref", "scim_client_id", "model_hash")))
case("S9: ham NameID/e-posta/bearer-token alanı yok",
     all(k not in json.dumps(r) for k in ("nameid_value", "email_value", "token_value", "bearer_value")))
case("S9: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

# ── S10 model bütünlük manifesti ──
r = P.build(req(), SPEC, inject=["model_tamper"])
case("S10: model tahrif → model_tampered>0 + kapı ELER", r["violations"]["model_tampered"] > 0 and not gate(r))

# ── S11/S12 gizlilik + sızıntı ──
case("S11/S12: SCIM+grup+rol+kapsam temiz",
     P.scan_leaks('{"scim_client_id":"sc-acme","group_name":"voiceai-ops-manager","role":"operations_manager","scope":{"brand":["brand-x"]}}') == [])
case("S12: e-posta yakalanır", len(P.scan_leaks('{"x":"jdoe@acme.co"}')) > 0)
case("S12: jwt blob yakalanır", len(P.scan_leaks('{"t":"eyJhbGciOiJ.eyJzdWIiOmF.abcdef"}')) > 0)

# ── unsupported schema/operation + malformed ──
case("unsupported resourceType → REJECTED", P.build(req(resource={"type": "Device"}), SPEC)["reject_reason"] == "unsupported_schema")
case("unsupported operation → REJECTED", P.build(req(operation="user.merge"), SPEC)["reject_reason"] == "unsupported_operation")
case("malformed (subject_ref yok) → REJECTED", P.build(req(resource={"subject_ref": None}), SPEC)["reject_reason"] == "malformed_request")

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior test: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
