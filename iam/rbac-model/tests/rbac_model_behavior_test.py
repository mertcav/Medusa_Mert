#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.1 — RBAC modeli (rol→permission-key bundle, immutable) DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.x behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import rbac_model_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
MODEL = P._load(P.MODEL_PATH)
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "actor_user_id": "u-b", "actor_realm": "tenant", "actor_roles": ["qa_analyst"],
        "required_permission": "transcript:read", "ownership": "other",
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── K1 determinizm/terminal ──
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1: deterministik (aynı girdi→aynı çıktı)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
case("K1: terminal'e ulaşır", r1["terminal"] in P.TERMINAL and r1["violations"]["stuck_state"] == 0)

# ── K2 immutable bundle ──
case("K2: happy ihlalsiz GRANT", P.build(req(), SPEC)["terminal"] == "GRANT")
r = P.build(req(required_permission="campaign:manage"), SPEC, inject=["bundle_mutate"])
case("K2: bundle_mutate → bundle_mutated>0", r["violations"]["bundle_mutated"] > 0)
case("K2: bundle_mutate → kapı eler", gate(r) is False)
# model_hash her çağrıda aynı (frozen)
hs = {P.build(req(actor_roles=[ro], required_permission="quota:read"), SPEC)["model_hash"]
      for ro in ("tenant_admin", "billing_viewer", "tenant_owner")}
case("K2: model_hash tüm çağrılarda aynı (frozen)", len(hs) == 1)

# ── K3 bundle çözümü + backend authz ──
case("K3: GRANT ⟺ required ∈ effective", "transcript:read" in P.build(req(), SPEC)["effective_bundle"])
r = P.build(req(actor_roles=["qa_analyst", "conversation_designer"], required_permission="flow:edit"), SPEC)
case("K3: çoklu rol birleşimi GRANT", r["terminal"] == "GRANT")
r = P.build(req(required_permission="campaign:manage"), SPEC)
case("K3: yetki yok → DENY missing_permission", r["terminal"] == "DENY" and r["deny_reason"] == "missing_permission")
r = P.build(req(required_permission="campaign:manage"), SPEC, inject=["unauthorized_grant"])
case("K3: unauthorized_grant>0 + kapı eler", r["violations"]["unauthorized_grant"] > 0 and gate(r) is False)
case("K3: granted ⟺ authorized", all(P.build(req(actor_roles=[ro], required_permission="quota:read"), SPEC)["granted"]
                                     == P.build(req(actor_roles=[ro], required_permission="quota:read"), SPEC)["authorized"]
                                     for ro in ("tenant_admin", "qa_analyst")))

# ── K4 katman/realm bütünlüğü ──
r = P.build(req(actor_realm="platform", actor_roles=["qa_analyst"]), SPEC)
case("K4: tenant rol platform realm'de → BLOCK realm_layer_mismatch",
     r["terminal"] == "BLOCK" and r["block_reason"] == "realm_layer_mismatch")
case("K4: realm_mismatch>0 + kapı eler", r["violations"]["realm_mismatch"] > 0 and gate(r) is False)
r = P.build(req(actor_realm="platform", actor_roles=["platform_sre"], required_permission="incident:manage"), SPEC)
case("K4: L0 rol doğru realm'de → GRANT", r["terminal"] == "GRANT")
# tüm modelde rol realm = layer_realm haritası
lr = MODEL["layer_realm"]
case("K4: model rol realm↔layer tutarlı",
     all(MODEL["roles"][ro]["realm"] == lr[MODEL["roles"][ro]["layer"]] for ro in MODEL["roles"]))

# ── K5 katalog conformance (statik model) ──
universe = set()
for ks in MODEL["permission_key_universe"].values():
    universe.update(ks)
all_keys = [k for ro in MODEL["roles"].values() for k in ro["permissions"]]
case("K5: her bundle key'i kaynak:eylem biçiminde", all(P.PERM_KEY_RE.match(k) for k in all_keys))
case("K5: her bundle key'i katalog evreninde", all(k in universe for k in all_keys))

# ── K6 :own disiplini ──
r = P.build(req(actor_roles=["human_agent"], required_permission="calls:read", ownership="own"), SPEC)
case("K6: :own + ownership=own → GRANT", r["terminal"] == "GRANT")
r = P.build(req(actor_roles=["human_agent"], required_permission="calls:read", ownership="other"), SPEC)
case("K6: :own + ownership=other → DENY insufficient_scope",
     r["terminal"] == "DENY" and r["deny_reason"] == "insufficient_scope")
r = P.build(req(actor_roles=["operations_manager"], required_permission="calls:read", ownership="other"), SPEC)
case("K6: full key sahiplikten bağımsız → GRANT", r["terminal"] == "GRANT")
r = P.build(req(actor_roles=["human_agent"], required_permission="calls:read", ownership="other"), SPEC, inject=["ownership_bypass"])
case("K6: ownership_bypass>0 + kapı eler", r["violations"]["ownership_violation"] > 0 and gate(r) is False)

# ── K7 en az yetki / L0 altın kural ──
content = set(MODEL["tenant_content_keys"])
l0_roles = [ro for ro, s in MODEL["roles"].items() if s["realm"] == "platform"]
case("K7: hiçbir L0 rolü tenant içerik key'i taşımaz (altın kural)",
     all(not (set(MODEL["roles"][ro]["permissions"]) & content) for ro in l0_roles))
r = P.build(req(actor_realm="platform", actor_roles=["platform_sre"], required_permission="transcript:read"), SPEC, inject=["layer_leak"])
case("K7: layer_leak → layer_violation>0 + privilege_escalation>0",
     r["violations"]["layer_violation"] > 0 and r["violations"]["privilege_escalation"] > 0)
case("K7: layer_leak → kapı eler", gate(r) is False)

# ── K8 custom rol yok ──
r = P.build(req(actor_roles=["super_admin"], required_permission="tenant:provision"), SPEC)
case("K8: model dışı rol → BLOCK unknown_role", r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_role")
r = P.build(req(actor_roles=["super_admin"], required_permission="tenant:provision"), SPEC, inject=["custom_role"])
case("K8: custom_role inject>0 + kapı eler", r["violations"]["custom_role"] > 0 and gate(r) is False)
case("K8: model custom_permission_builder=false", MODEL["custom_permission_builder"] is False)

# ── K9 kanıt ──
r = P.build(req(), SPEC)
case("K9: kanıt request_id + actor_roles + required + model_hash taşır",
     all(r["evidence"].get(k) is not None for k in ("request_id", "actor_roles", "required_permission", "model_hash")))

# ── K10 model bütünlük manifesti ──
r = P.build(req(), SPEC, inject=["model_tamper"])
case("K10: model_tamper → model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and gate(r) is False)

# ── K12 sır/PII yok ──
case("K12: kanıt/karar ham PII alanı taşımaz",
     all(k not in json.dumps(P.build(req(), SPEC)) for k in ("customer_phone_value", "card_pan_value", "raw_value")))
case("K12: rol adı/permission-key sızıntı değil", P.scan_leaks('{"actor_roles":["operations_manager"],"required_permission":"transcript:read"}') == [])

# ── malformed ──
case("malformed: biçimsiz required → BLOCK", P.build(req(required_permission="calls"), SPEC)["block_reason"] == "malformed_request")
case("malformed: rol yok → BLOCK", P.build(req(actor_roles=[]), SPEC)["block_reason"] == "malformed_request")

# ── BRD §17.2 12 rol ──
case("model: 12 rol (BRD §17.2)", len(MODEL["roles"]) == 12)

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior test: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
