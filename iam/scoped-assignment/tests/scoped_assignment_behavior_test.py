#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.3 — Scoped assignment (rol + departman/marka/kampanya filtresi) DAVRANIŞ testi (S1–S12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (12.1.1/11.x behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import scoped_assignment_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
SCOPE = P._load(P.SCOPE_MODEL_PATH)
RBAC = P._load(P.RBAC_MODEL_PATH)
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "actor_user_id": "u-b", "actor_realm": "tenant",
        "assignments": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
        "required_permission": "campaign:manage", "ownership": "other",
        "resource": {"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-1"},
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── S1 determinizm/terminal ──
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("S1: deterministik (aynı girdi→aynı çıktı)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
case("S1: terminal'e ulaşır", r1["terminal"] in P.TERMINAL and r1["violations"]["stuck_state"] == 0)
case("S1: model_hash deterministik", r1["model_hash"] == r2["model_hash"])

# ── S2 narrowing-only ÇEKİRDEK ──
case("S2: kapsam içi → GRANT", P.build(req(), SPEC)["terminal"] == "GRANT")
r = P.build(req(resource={"tenant_id": "t-acme", "brand": "brand-y", "campaign": "camp-9"}), SPEC)
case("S2: kapsam dışı → DENY out_of_scope (rol permission taşısa bile)",
     r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope")
case("S2: kapsam dışı DENY ihlal değil (meşru)", all(x == 0 for x in r["violations"].values()))
r = P.build(req(resource={"tenant_id": "t-acme", "brand": "brand-y"}), SPEC, inject=["scope_broaden"])
case("S2: scope_broaden → scope_broadened>0 + kapı eler", r["violations"]["scope_broadened"] > 0 and gate(r) is False)
case("S2: scope model narrowing_only=true", SCOPE["narrowing_only"] is True)
case("S2: narrowing_rules.scope_can_broaden=false", SCOPE["narrowing_rules"]["scope_can_broaden"] is False)

# ── S3 scoped-grant doğruluğu ÇEKİRDEK ──
case("S3: GRANT ⟺ ∃ atama (permission ∧ scope) → matched var", P.build(req(), SPEC)["matched_assignment"] is not None)
r = P.build(req(assignments=[{"role": "qa_analyst", "scope": {"brand": ["brand-x"]}},
                             {"role": "operations_manager", "scope": {"brand": ["brand-y"]}}],
                resource={"tenant_id": "t-acme", "brand": "brand-y"}), SPEC)
case("S3: atamalar arası birleşim (union) GRANT", r["terminal"] == "GRANT" and r["matched_assignment"]["role"] == "operations_manager")
r = P.build(req(resource={"tenant_id": "t-acme", "brand": "brand-y"}), SPEC, inject=["out_of_scope_grant"])
case("S3: out_of_scope_grant>0 + kapı eler", r["violations"]["out_of_scope_grant"] > 0 and gate(r) is False)
case("S3: granted ⟺ authorized",
     all(P.build(req(**k), SPEC)["granted"] == P.build(req(**k), SPEC)["authorized"]
         for k in ({}, {"resource": {"tenant_id": "t-acme", "brand": "brand-y"}})))

# ── S4 realm/katman bütünlüğü (12.1.1'den devralınır) ──
r = P.build(req(actor_realm="platform"), SPEC)
case("S4: tenant rol platform realm'de → BLOCK realm_layer_mismatch",
     r["terminal"] == "BLOCK" and r["block_reason"] == "realm_layer_mismatch")
case("S4: realm_mismatch>0 + kapı eler", r["violations"]["realm_mismatch"] > 0 and gate(r) is False)

# ── S5 boyut conformance ──
case("S5: scope model boyutlar = department/brand/campaign", set(SCOPE["dimensions"]) == set(P.DIMENSIONS))
r = P.build(req(assignments=[{"role": "operations_manager", "scope": {"region": ["eu"]}}]), SPEC, inject=["unknown_dimension"])
case("S5: unknown_dimension honor → unknown_dimension>0 + kapı eler", r["violations"]["unknown_dimension"] > 0 and gate(r) is False)
r = P.build(req(assignments=[{"role": "operations_manager", "scope": {"region": ["eu"]}}]), SPEC)
case("S5: boyut-dışı anahtar → defekt fail-closed (unknown_dimension>0)", r["violations"]["unknown_dimension"] > 0)

# ── S6 wildcard disiplini ──
r = P.build(req(assignments=[{"role": "operations_manager", "scope": {}}],
                resource={"tenant_id": "t-acme", "brand": "brand-z", "campaign": "camp-7"}), SPEC)
case("S6: kapsamsız scope = tenant-geneli → GRANT", r["terminal"] == "GRANT")
r = P.build(req(assignments=[{"role": "operations_manager", "scope": {"brand": ["*"]}}],
                resource={"tenant_id": "t-acme", "brand": "brand-q"}), SPEC)
case("S6: wildcard '*' → kısıtsız GRANT", r["terminal"] == "GRANT")
r = P.build(req(assignments=[{"role": "operations_manager", "scope": {"brand": []}}],
                resource={"tenant_id": "t-acme", "brand": "brand-x"}), SPEC)
case("S6: empty list [] = matches_nothing → DENY out_of_scope", r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope")
r = P.build(req(assignments=[{"role": "operations_manager", "scope": {"brand": []}}],
                resource={"tenant_id": "t-acme", "brand": "brand-x"}), SPEC, inject=["wildcard_abuse"])
case("S6: wildcard_abuse → scope_broadened>0 + kapı eler", r["violations"]["scope_broadened"] > 0 and gate(r) is False)

# ── S7 tenant izolasyonu ÇEKİRDEK ──
r = P.build(req(resource={"tenant_id": "t-other", "brand": "brand-x"}), SPEC)
case("S7: cross-tenant kaynak → BLOCK cross_tenant_resource",
     r["terminal"] == "BLOCK" and r["block_reason"] == "cross_tenant_resource")
case("S7: cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and gate(r) is False)
r = P.build(req(resource={"tenant_id": "t-other", "brand": "brand-x"}), SPEC, inject=["cross_tenant"])
case("S7: cross_tenant inject (izolasyon atla) → cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and gate(r) is False)

# ── S8 immutable bundle korunur ──
r = P.build(req(assignments=[{"role": "qa_analyst", "scope": {"brand": ["brand-x"]}}]), SPEC, inject=["permission_inject"])
case("S8: permission_inject → permission_added>0 + kapı eler", r["violations"]["permission_added"] > 0 and gate(r) is False)
case("S8: scope model scope_can_add_permission=false", SCOPE["narrowing_rules"]["scope_can_add_permission"] is False)
case("S8: scope model custom_permission_builder=false", SCOPE["custom_permission_builder"] is False)

# ── S9 kanıt ──
r = P.build(req(), SPEC)
case("S9: kanıt request + assignments + resource + model_hash taşır",
     all(r["evidence"].get(k) is not None for k in ("request_id", "assignments", "resource", "model_hash")))

# ── S10 model bütünlük manifesti ──
r = P.build(req(), SPEC, inject=["model_tamper"])
case("S10: model_tamper → model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and gate(r) is False)

# ── S12 sır/PII yok ──
case("S12: kanıt/karar ham PII alanı taşımaz",
     all(k not in json.dumps(P.build(req(), SPEC)) for k in ("customer_phone_value", "card_pan_value", "raw_value")))
case("S12: rol/kapsam ID sızıntı değil",
     P.scan_leaks('{"role":"operations_manager","scope":{"brand":["brand-x"],"campaign":["camp-1"]}}') == [])

# ── permission gate önce (scope'tan bağımsız) ──
r = P.build(req(required_permission="tenant:provision"), SPEC)
case("permission önce: rol permission taşımaz → DENY missing_permission", r["terminal"] == "DENY" and r["deny_reason"] == "missing_permission")

# ── ':own' disiplini devralınır ──
r = P.build(req(assignments=[{"role": "human_agent", "scope": {}}], required_permission="calls:read",
                ownership="own", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), SPEC)
case("own: :own + ownership=own → GRANT", r["terminal"] == "GRANT")
r = P.build(req(assignments=[{"role": "human_agent", "scope": {}}], required_permission="calls:read",
                ownership="other", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), SPEC)
case("own: :own + ownership=other → DENY insufficient_scope", r["terminal"] == "DENY" and r["deny_reason"] == "insufficient_scope")

# ── malformed ──
case("malformed: atama yok → BLOCK", P.build(req(assignments=[]), SPEC)["block_reason"] == "malformed_request")
case("malformed: resource yok → BLOCK", P.build(req(resource={}), SPEC)["block_reason"] == "malformed_request")
case("malformed: biçimsiz required → BLOCK", P.build(req(required_permission="calls"), SPEC)["block_reason"] == "malformed_request")

# ── 12.1.1 modeli TÜKETİLİR (consumes) ──
case("consume: 12.1.1 rbac frozen + 12 rol", RBAC["frozen"] is True and len(RBAC["roles"]) == 12)
case("consume: SAD §14.4.2 örneği operations_manager campaign:manage taşır",
     "campaign:manage" in RBAC["roles"]["operations_manager"]["permissions"])

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior test: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
