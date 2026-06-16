#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.2 — Router/scope topolojisi davranış testi (S1–S12; SAD §14.4.2 ayrı router/scopes + ayrı deploy).

Bağımsız fixture'larla router/scope topolojisi motorunu doğrular: ayrı router ağaçları (S2), düzlem/deploy
ayrımı (S3), ayrı/anlaşmaz OAuth scope (S4), router realm (S5), 12.2.1 tutarlılık (S6), scope dependency
zorunlu (S7), devir doğruluğu (S8), fail-closed (S1), model bütünlük (S10), kanıt (S9), sızıntı yok (S12).
12.2.1 backend-guard'ı CANLI DEVREDER (gerçek kompozisyon — router admission GEREKLİ ama YETERLİ DEĞİL).
probe selftest'inden BAĞIMSIZ ikinci doğrulama katmanı (12.1.x/12.2.1 test deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import router_scopes_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def _scn(**kw):
    d = {
        "request_id": "r-1",
        "mounts": [{"endpoint": "GET /ops/v1/calls/{id}", "declared_panel": "L2", "mounted_tree": "L2"}],
        "request": {"target_tree": "L2", "arrived_plane": "tenant_application_plane",
                    "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                    "token": {"realm": "tenant", "panel_scope": "panel:L2"}},
    }
    d.update(kw)
    return d


def _l0(**kw):
    d = {
        "request_id": "r-2",
        "mounts": [{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L0"}],
        "request": {"target_tree": "L0", "arrived_plane": "platform_control_plane",
                    "arrived_origin": "platform.internal.rmcvoice.io", "authenticated": True,
                    "token": {"realm": "platform", "panel_scope": "panel:L0"}},
    }
    d.update(kw)
    return d


def run():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    # ── S1 determinizm + terminal + fail-closed default ──
    a, b = P.build(_scn(), SPEC), P.build(_scn(), SPEC)
    case("S1: deterministik (birebir)", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))
    case("S1: terminal ∈ {ADMIT,REJECT,MISCONFIG}", a["terminal"] in P.TERMINAL)
    case("S1: stuck_state=0", a["violations"]["stuck_state"] == 0)
    case("S1: malformed → fail-closed MISCONFIG", P.build(_scn(request_id=None), SPEC)["terminal"] == "MISCONFIG")
    case("S1: model_hash deterministik", a["model_hash"] == b["model_hash"])

    # ── S2 ayrı router ağaçları ──
    case("S2: doğru panel mount → ADMIT", P.build(_scn(), SPEC)["terminal"] == "ADMIT")
    r = P.build(_scn(mounts=[{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L2"}]), SPEC)
    case("S2: cross-panel mount → MISCONFIG panel_tree_mismatch (deploy yakalanır)",
         r["terminal"] == "MISCONFIG" and r["misconfig_reason"] == "panel_tree_mismatch")
    case("S2: meşru MISCONFIG ihlal değil (gate geçer)", P._gate_eval(r, G)[0] is True)
    r = P.build(_scn(mounts=[{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L2"}]), SPEC, inject=["cross_panel_mount"])
    case("S2: cross_panel_mount inject → tree_mount_violation + gate ELER",
         r["violations"]["tree_mount_violation"] > 0 and P._gate_eval(r, G)[0] is False)
    r = P.build(_scn(mounts=[{"endpoint": "GET /x", "declared_panel": "L1", "mounted_tree": "L1"},
                             {"endpoint": "GET /x", "declared_panel": "L2", "mounted_tree": "L2"}]), SPEC)
    case("S2: aynı endpoint 2 ağaçta → MISCONFIG multi_tree_mount", r["misconfig_reason"] == "multi_tree_mount")

    # ── S3 düzlem/deploy ayrımı ──
    case("S3: L0 isteği doğru internal-only düzlemde → ADMIT", P.build(_l0(), SPEC)["terminal"] == "ADMIT")
    r = P.build(_l0(request={"target_tree": "L0", "arrived_plane": "tenant_application_plane",
                             "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                             "token": {"realm": "platform", "panel_scope": "panel:L0"}}), SPEC)
    case("S3: L0 isteği public düzlemde → REJECT wrong_plane_origin", r["reject_reason"] == "wrong_plane_origin")
    r = P.build(_scn(), SPEC, inject=["plane_collapse"])
    case("S3: plane_collapse inject → plane_violation + gate ELER",
         r["violations"]["plane_violation"] > 0 and P._gate_eval(r, G)[0] is False)

    # ── S4 ayrı/anlaşmaz OAuth scope ──
    r = P.build(_scn(request={"target_tree": "L2", "arrived_plane": "tenant_application_plane",
                              "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                              "token": {"realm": "tenant", "panel_scope": "panel:L1"}}), SPEC)
    case("S4: yanlış panel scope → REJECT router_scope_mismatch", r["reject_reason"] == "router_scope_mismatch")
    case("S4: meşru REJECT ihlal değil (gate geçer)", P._gate_eval(r, G)[0] is True)
    r = P.build(_scn(), SPEC, inject=["scope_reuse"])
    case("S4: scope_reuse inject (çakışma) → scope_violation + gate ELER",
         r["violations"]["scope_violation"] > 0 and P._gate_eval(r, G)[0] is False)
    r = P.build(_scn(request={"target_tree": "L2", "arrived_plane": "tenant_application_plane",
                              "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                              "token": {"realm": "tenant", "panel_scope": "panel:L1"}}), SPEC, inject=["scope_bypass"])
    case("S4: scope_bypass inject → scope_violation + ADMIT(yanlış) + gate ELER",
         r["violations"]["scope_violation"] > 0 and r["terminal"] == "ADMIT" and P._gate_eval(r, G)[0] is False)

    # ── S5 router realm ──
    r = P.build(_l0(request={"target_tree": "L0", "arrived_plane": "platform_control_plane",
                             "arrived_origin": "platform.internal.rmcvoice.io", "authenticated": True,
                             "token": {"realm": "tenant", "panel_scope": "panel:L0"}}), SPEC)
    case("S5: L0 ağacına tenant realm → REJECT router_realm_mismatch", r["reject_reason"] == "router_realm_mismatch")
    r = P.build(_l0(request={"target_tree": "L0", "arrived_plane": "platform_control_plane",
                             "arrived_origin": "platform.internal.rmcvoice.io", "authenticated": True,
                             "token": {"realm": "tenant", "panel_scope": "panel:L0"}}), SPEC, inject=["realm_cross"])
    case("S5: realm_cross inject → realm_violation + gate ELER",
         r["violations"]["realm_violation"] > 0 and P._gate_eval(r, G)[0] is False)

    # ── S6 12.2.1 tutarlılık (tek kaynak) ──
    topo = P._topology()
    gm = P._guard_model()
    case("S6: topoloji oauth_scope = guard-model panel_oauth_scope",
         all(topo["router_trees"][k]["oauth_scope"] == gm["panel_oauth_scope"][k] for k in ("L0", "L1", "L2")))
    case("S6: topoloji realm = guard-model panel_realm",
         all(topo["router_trees"][k]["realm"] == gm["panel_realm"][k] for k in ("L0", "L1", "L2")))
    r = P.build(_scn(), SPEC, inject=["consistency_break"])
    case("S6: consistency_break inject → consistency_violation + gate ELER",
         r["violations"]["consistency_violation"] > 0 and P._gate_eval(r, G)[0] is False)

    # ── S7 scope dependency zorunlu ──
    case("S7: tüm ağaçlar router_scope_dependency=true",
         all(topo["router_trees"][k]["router_scope_dependency"] is True for k in ("L0", "L1", "L2")))
    r = P.build(_scn(), SPEC, inject=["scope_dep_drop"])
    case("S7: scope_dep_drop inject → missing_scope_dependency + gate ELER",
         r["violations"]["missing_scope_dependency"] > 0 and P._gate_eval(r, G)[0] is False)

    # ── S8 devir doğruluğu (12.2.1 CANLI kompozisyon) ──
    r = P.build(_scn(), SPEC)
    case("S8: ADMIT → 12.2.1'e devredilir (necessary_not_sufficient)",
         r["terminal"] == "ADMIT" and "12.2.1" in (r["delegated_to"] or "")
         and r["evidence"]["router_admission"] == "necessary_not_sufficient")
    bg = P._guard_module()
    gd = bg.build({"request_id": "r-1", "tenant_id": "t-acme", "actor_user_id": "u-1", "actor_realm": "tenant",
                   "authenticated": True, "token": {"realm": "tenant", "panel_scope": "panel:L2"},
                   "endpoint": {"panel": "L2", "required_permission": "campaign:manage"},
                   "assignments": [{"role": "qa_analyst", "scope": {}}], "ownership": "other",
                   "resource": {"tenant_id": "t-acme", "campaign": "c-1"}}, bg._load(bg.SPEC_PATH))
    case("S8: aynı L2 ADMIT ama yetkisiz permission → 12.2.1 DENY (admission yeterli değil)", gd["terminal"] == "DENY")
    r = P.build(_scn(), SPEC, inject=["admit_sufficient"])
    case("S8: admit_sufficient inject → delegation_violation + gate ELER",
         r["violations"]["delegation_violation"] > 0 and P._gate_eval(r, G)[0] is False)

    # ── S9 kanıt ──
    r = P.build(_scn(), SPEC)
    case("S9: kanıt request+mounts+target+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "mounts", "target_tree", "model_hash")))
    case("S9: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # ── S10 model bütünlük ──
    r = P.build(_scn(), SPEC, inject=["model_tamper"])
    case("S10: model_tamper inject → model_tampered + gate ELER",
         r["violations"]["model_tampered"] > 0 and P._gate_eval(r, G)[0] is False)

    # ── S12 sızıntı yok ──
    case("S12: panel/scope/prefix/origin temiz",
         P.scan_leaks('{"panel":"L2","oauth_scope":"panel:L2","prefix":"/ops/v1","origin":"api.rmcvoice.io"}') == [])
    case("S12: card_pan_value yakalanır", len(P.scan_leaks('{"card_pan_value":"x"}')) > 0)
    case("S12: sonuç ham PII alanı taşımaz",
         all(k not in json.dumps(r) for k in ("customer_phone_value", "card_pan_value", "raw_value")))

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nrouter_scopes_behavior_test: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
