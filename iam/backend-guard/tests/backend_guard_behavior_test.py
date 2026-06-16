#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.1 — Backend guard davranış testi (S1–S12; SAD §14.4.2 panel + rol + tenant scope).

Bağımsız fixture'larla guard karar motorunu doğrular: panel izolasyonu (S2), deklarasyon zorunlu (S3),
delege doğruluğu (S4), tenant scope (S5), backend otoritesi (S6), fail-closed (S1), model bütünlük (S10),
kanıt (S9), sızıntı yok (S12). 12.1.3 scoped-assignment'ı CANLI DELEGE eder (gerçek kompozisyon). probe
selftest'inden BAĞIMSIZ ikinci doğrulama katmanı (12.1.x test deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import backend_guard_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def _req(**kw):
    d = {
        "request_id": "r-1", "tenant_id": "t-1", "actor_user_id": "u-9", "actor_realm": "tenant",
        "authenticated": True, "token": {"realm": "tenant", "panel_scope": "panel:L2"},
        "endpoint": {"panel": "L2", "required_permission": "calls:read"},
        "assignments": [{"role": "operations_manager", "scope": {"brand": ["b-1"]}}],
        "ownership": "other", "resource": {"tenant_id": "t-1", "brand": "b-1", "campaign": "c-1"},
    }
    d.update(kw)
    return d


def run():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    # ── S1 determinizm + terminal + fail-closed default ──
    a, b = P.build(_req(), SPEC), P.build(_req(), SPEC)
    case("S1: deterministik (birebir)", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))
    case("S1: terminal ∈ {ALLOW,DENY,BLOCK}", a["terminal"] in P.TERMINAL)
    case("S1: stuck_state=0", a["violations"]["stuck_state"] == 0)
    case("S1: malformed → BLOCK (fail-closed)", P.build(_req(endpoint={"panel": "L2"}), SPEC)["terminal"] == "BLOCK")
    case("S1: happy ALLOW + http 200", a["terminal"] == "ALLOW" and a["http_status"] == 200)

    # ── S2 panel izolasyonu (ÇEKİRDEK) ──
    r = P.build(_req(endpoint={"panel": "L0", "required_permission": "tenant:provision"}, resource={"tenant_id": "t-1"}), SPEC)
    case("S2: tenant token L0 panel → BLOCK panel_realm_mismatch", r["block_reason"] == "panel_realm_mismatch")
    r = P.build(_req(token={"realm": "tenant", "panel_scope": "panel:L1"}), SPEC)
    case("S2: yanlış OAuth scope → BLOCK oauth_scope_mismatch", r["block_reason"] == "oauth_scope_mismatch")
    r = P.build(_req(assignments=[{"role": "billing_viewer", "scope": {}}]), SPEC)
    case("S2: L1 rolü L2 panel → BLOCK panel_not_covered", r["block_reason"] == "panel_not_covered")
    r = P.build(_req(endpoint={"panel": "L0", "required_permission": "tenant:provision"}, resource={"tenant_id": "t-1"}), SPEC, inject=["panel_bypass"])
    case("S2: panel_bypass → panel_violation>0 + kapı eler", r["violations"]["panel_violation"] > 0 and not P._gate_eval(r, G)[0])
    r = P.build(_req(token={"realm": "tenant", "panel_scope": "panel:L1"}), SPEC, inject=["oauth_scope_bypass"])
    case("S2: oauth_scope_bypass → scope_violation>0 + kapı eler", r["violations"]["scope_violation"] > 0 and not P._gate_eval(r, G)[0])
    r = P.build(_req(endpoint={"panel": "L0", "required_permission": "tenant:provision"}, resource={"tenant_id": "t-1"}), SPEC, inject=["realm_cross"])
    case("S2: realm_cross → realm_violation>0 + kapı eler", r["violations"]["realm_violation"] > 0 and not P._gate_eval(r, G)[0])
    # L1+L2 rolü her iki paneli kapsar
    r1 = P.build(_req(assignments=[{"role": "tenant_owner", "scope": {}}]), SPEC)
    r2 = P.build(_req(token={"realm": "tenant", "panel_scope": "panel:L1"},
                      endpoint={"panel": "L1", "required_permission": "calls:read"},
                      assignments=[{"role": "tenant_owner", "scope": {}}], resource={"tenant_id": "t-1"}), SPEC)
    case("S2: tenant_owner (L1+L2) hem L2 hem L1 panelini kapsar", r1["terminal"] == "ALLOW" and r2["terminal"] == "ALLOW")

    # ── S3 deklarasyon zorunlu ──
    case("S3: required eksik → BLOCK malformed_request", P.build(_req(endpoint={"panel": "L2"}), SPEC)["block_reason"] == "malformed_request")
    case("S3: required biçimsiz → BLOCK malformed_request", P.build(_req(endpoint={"panel": "L2", "required_permission": "calls"}), SPEC)["block_reason"] == "malformed_request")
    r = P.build(_req(endpoint={"panel": "L2"}), SPEC, inject=["missing_perm_decl"])
    case("S3: missing_perm_decl → undeclared_endpoint>0 + kapı eler", r["violations"]["undeclared_endpoint"] > 0 and not P._gate_eval(r, G)[0])

    # ── S4 delege doğruluğu (ÇEKİRDEK) ──
    case("S4: ALLOW ⟺ delege GRANT", a["allowed"] is True and a["delegated_terminal"] == "GRANT")
    r = P.build(_req(resource={"tenant_id": "t-1", "brand": "b-2"}), SPEC)
    case("S4: kapsam dışı → DENY out_of_scope + delege DENY + 403", r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope" and r["delegated_terminal"] == "DENY" and r["http_status"] == 403)
    r = P.build(_req(endpoint={"panel": "L2", "required_permission": "campaign:manage"}, assignments=[{"role": "qa_analyst", "scope": {}}], resource={"tenant_id": "t-1"}), SPEC)
    case("S4: permission yok → DENY missing_permission", r["terminal"] == "DENY" and r["deny_reason"] == "missing_permission")
    r = P.build(_req(resource={"tenant_id": "t-1", "brand": "b-2"}), SPEC, inject=["fail_open"])
    case("S4: fail_open → fail_open_grant>0 + ALLOW (yanlış) + kapı eler", r["violations"]["fail_open_grant"] > 0 and r["terminal"] == "ALLOW" and not P._gate_eval(r, G)[0])

    # ── S5 tenant scope (ÇEKİRDEK) ──
    r = P.build(_req(resource={"tenant_id": "t-other", "brand": "b-1"}), SPEC)
    case("S5: cross-tenant → BLOCK cross_tenant_resource + cross_tenant>0", r["block_reason"] == "cross_tenant_resource" and r["violations"]["cross_tenant"] > 0)
    case("S5: cross-tenant kapı ELER (güvenlik alarmı)", not P._gate_eval(r, G)[0])
    r = P.build(_req(resource={"tenant_id": "t-other", "brand": "b-1"}), SPEC, inject=["tenant_bypass"])
    case("S5: tenant_bypass → cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and not P._gate_eval(r, G)[0])

    # ── S6 backend otoritesi (ÇEKİRDEK) ──
    r = P.build(_req(client_claims={"assignments": [{"role": "tenant_owner", "scope": {}}], "required_permission_override": "tenant:provision"}), SPEC)
    case("S6: client_claims yoksayılır (inject yok) → ihlal yok + token kararı", all(x == 0 for x in r["violations"].values()))
    r = P.build(_req(endpoint={"panel": "L2", "required_permission": "campaign:manage"}, assignments=[{"role": "qa_analyst", "scope": {}}], resource={"tenant_id": "t-1"}, client_claims={"assignments": [{"role": "operations_manager", "scope": {}}]}), SPEC, inject=["client_claim_trust"])
    case("S6: client_claim_trust → client_trust_violation>0 + kapı eler", r["violations"]["client_trust_violation"] > 0 and not P._gate_eval(r, G)[0])

    # ── authn ──
    r = P.build(_req(authenticated=False), SPEC)
    case("authn: BLOCK unauthenticated + http 401", r["block_reason"] == "unauthenticated" and r["http_status"] == 401)

    # ── S9 kanıt ──
    case("S9: kanıt request+panel+assignments+resource+model_hash + delegated_terminal", all(k in a["evidence"] for k in ("request_id", "endpoint_panel", "assignments", "resource", "model_hash", "delegated_terminal")))
    case("S9: missing_evidence=0", a["violations"]["missing_evidence"] == 0)

    # ── S10 model bütünlük ──
    r = P.build(_req(), SPEC, inject=["model_tamper"])
    case("S10: model_tamper → model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and not P._gate_eval(r, G)[0])
    case("S10: model_hash deterministik", a["model_hash"] == b["model_hash"])

    # ── S12 sızıntı yok ──
    case("S12: rol+permission+panel-scope temiz", P.scan_leaks('{"role":"operations_manager","required_permission":"calls:read","panel_scope":"panel:L2","realm":"tenant"}') == [])
    case("S12: card_pan_value yakalanır", len(P.scan_leaks('{"card_pan_value":"x"}')) > 0)
    case("S12: ham PII alanı kararda yok", all(k not in json.dumps(a) for k in ("customer_phone_value", "card_pan_value", "raw_value")))

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
