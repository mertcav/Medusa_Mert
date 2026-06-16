#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.4 — Tier B break-glass: regüle tenant require_tenant_approval toggle + DPA bağı davranış testi
(C1–C12; bağımsız).

tier_b_approval_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (BRD §17 / FR-IAM-010 / SAD §14.4.2)
bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x/12.3.x deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tier_b_approval_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def appr(role="security_compliance_officer", tid="t-acme", bg="bg-t", realm="tenant"):
    return {"role": role, "realm": realm, "tenant_id": tid, "break_glass_id": bg}


def ev(**kw):
    d = {
        "request_id": "req-t", "correlation_id": "corr-t", "break_glass_id": "bg-t",
        "actor_role": "platform_owner", "target_tenant_id": "t-acme", "tier": "B",
        "resource_type": "transcript", "data_class": "tenant_content",
        "access_decision": "GRANT_TIER_B", "regulated": True, "dpa_signed": True,
        "tenant_approval": appr(), "now": 100,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # C1 — determinizm + terminal + kanıt + default-BLOCK + access routing
    r = P.build(ev(), SPEC)
    ok("C1 happy ALLOW (tenant_approved)", r["terminal"] == "ALLOW" and r["note"] == "tenant_approved")
    ok("C1 determinizm birebir", json.dumps(P.build(ev(), SPEC), sort_keys=True) == json.dumps(r, sort_keys=True))
    ok("C1 terminal resolved", r["resolved"] is True and r["terminal"] in P.TERMINAL)
    ok("C1 routing PENDING → HOLD(access_not_granted)",
       P.build(ev(access_decision="PENDING"), SPEC)["note"] == "access_not_granted")
    ok("C1 routing DENY → HOLD", P.build(ev(access_decision="DENY"), SPEC)["terminal"] == "HOLD")
    ok("C1 stuck_state/missing_evidence=0", r["violations"]["stuck_state"] == 0 and r["violations"]["missing_evidence"] == 0)
    ok("C1 evidence taşır", all(k in r["evidence"] for k in
       ("request_id", "actor_role", "target_tenant_id", "access_decision", "regulated", "require_tenant_approval",
        "dpa_bound", "tenant_approved", "model_hash")))

    # C2 — regüle varsayılan açık (most-restrictive-wins)
    ok("C2 regüle → require_tenant_approval=true", P.build(ev(), SPEC)["require_tenant_approval"] is True)
    ok("C2 regüle değil → require_tenant_approval=false",
       P.build(ev(regulated=False, tenant_approval=None, dpa_signed=False), SPEC)["require_tenant_approval"] is False)
    rdis = P.build(ev(tenant_approval=None), SPEC, inject=["disable_regulated_toggle"])
    ok("C2 disable_regulated_toggle → regulated_toggle_off>0 + ALLOW + kapı eler",
       rdis["violations"]["regulated_toggle_off"] > 0 and rdis["terminal"] == "ALLOW" and P._gate_eval(rdis, G)[0] is False)

    # C3 — onaysız açılmaz
    rno = P.build(ev(tenant_approval=None), SPEC)
    ok("C3 onay yok → HOLD(awaiting_tenant_approval)", rno["terminal"] == "HOLD" and rno["note"] == "awaiting_tenant_approval")
    ok("C3 doğru → tenant_approval_bypassed=0 + kapı geçer",
       rno["violations"]["tenant_approval_bypassed"] == 0 and P._gate_eval(rno, G)[0] is True)
    rbyp = P.build(ev(tenant_approval=None), SPEC, inject=["bypass_tenant_approval"])
    ok("C3 bypass → ALLOW + tenant_approval_bypassed>0 + kapı eler",
       rbyp["terminal"] == "ALLOW" and rbyp["violations"]["tenant_approval_bypassed"] > 0 and P._gate_eval(rbyp, G)[0] is False)

    # C4 — onay yetkisi (tenant realm; controller=tenant; platform self-approval yok)
    ok("C4 onaylayan SCO (tenant realm) → ALLOW", P.build(ev(), SPEC)["tenant_approved"] is True)
    ok("C4 realm=platform onay geçersiz → HOLD",
       P.build(ev(tenant_approval=appr(realm="platform")), SPEC)["terminal"] == "HOLD")
    rself = P.build(ev(tenant_approval=None), SPEC, inject=["platform_self_approve"])
    ok("C4 platform_self_approve → approval_authority_violation>0 + kapı eler",
       rself["violations"]["approval_authority_violation"] > 0 and P._gate_eval(rself, G)[0] is False)
    rxr = P.build(ev(tenant_approval=appr(realm="platform")), SPEC, inject=["cross_realm_approval"])
    ok("C4 cross_realm_approval → approval_authority_violation>0 + kapı eler",
       rxr["violations"]["approval_authority_violation"] > 0 and P._gate_eval(rxr, G)[0] is False)

    # C5 — DPA bağı
    rnodpa = P.build(ev(dpa_signed=False), SPEC)
    ok("C5 regüle + DPA imzasız → BLOCK(dpa_unbound)", rnodpa["terminal"] == "BLOCK" and rnodpa["note"] == "dpa_unbound")
    ok("C5 doğru → dpa_unbound=0 + kapı geçer", rnodpa["violations"]["dpa_unbound"] == 0 and P._gate_eval(rnodpa, G)[0] is True)
    runb = P.build(ev(dpa_signed=False), SPEC, inject=["unbind_dpa"])
    ok("C5 unbind_dpa → dpa_unbound>0 + ALLOW + kapı eler",
       runb["violations"]["dpa_unbound"] > 0 and runb["terminal"] == "ALLOW" and P._gate_eval(runb, G)[0] is False)

    # C6 — override yalnız-sıkılaştırır
    ok("C6 non-regüle + override=on → require_tenant_approval=true (tighten)",
       P.build(ev(regulated=False, tenant_override="on", tenant_approval=None), SPEC)["require_tenant_approval"] is True)
    ok("C6 regüle + override=off (gevşetme uygulanmaz) → require_tenant_approval=true",
       P.build(ev(tenant_override="off", tenant_approval=None), SPEC)["require_tenant_approval"] is True)
    rl = P.build(ev(tenant_override="off", tenant_approval=None), SPEC, inject=["loosen_override"])
    ok("C6 loosen_override → override_loosened>0 + ALLOW + kapı eler",
       rl["violations"]["override_loosened"] > 0 and rl["terminal"] == "ALLOW" and P._gate_eval(rl, G)[0] is False)

    # C7 — onay binding
    ok("C7 cross-tenant onay geçersiz → HOLD",
       P.build(ev(tenant_approval=appr(tid="t-other")), SPEC)["terminal"] == "HOLD")
    rxt = P.build(ev(tenant_approval=appr(tid="t-other")), SPEC, inject=["cross_tenant_approval"])
    ok("C7 cross_tenant_approval → approval_misbinding>0 + kapı eler",
       rxt["violations"]["approval_misbinding"] > 0 and P._gate_eval(rxt, G)[0] is False)

    # C8 — replay-safe
    rr = P.build(ev(prior_state="CONSUMED"), SPEC)
    ok("C8 prior_state=CONSUMED → HOLD(already_resolved)", rr["terminal"] == "HOLD" and rr["note"] == "already_resolved")
    rri = P.build(ev(prior_state="CONSUMED"), SPEC, inject=["replay_approval"])
    ok("C8 replay_approval → ALLOW + approval_replay>0 + kapı eler",
       rri["terminal"] == "ALLOW" and rri["violations"]["approval_replay"] > 0 and P._gate_eval(rri, G)[0] is False)

    # C9 — audit WORM/PII-free/immutable
    ok("C9 ALLOW audit'lenir + row_hash var", r["audit_emitted"] is True and r["audit_record"].get("row_hash") is not None)
    ok("C9 HOLD/BLOCK de audit'lenir",
       P.build(ev(access_decision="DENY"), SPEC)["audit_emitted"] is True and P.build(ev(dpa_signed=False), SPEC)["audit_emitted"] is True)
    ok("C9 audit break_glass_id + tenant_approved + dpa_bound alanları",
       all(k in r["audit_record"] for k in ("break_glass_id", "tenant_approved", "dpa_bound")))
    rsk = P.build(ev(), SPEC, inject=["skip_audit"])
    ok("C9 skip_audit → unaudited_decision>0 + kapı eler",
       rsk["violations"]["unaudited_decision"] > 0 and P._gate_eval(rsk, G)[0] is False)
    rpii = P.build(ev(), SPEC, inject=["leak_pii"])
    ok("C9 leak_pii → audit_pii>0 + kapı eler", rpii["violations"]["audit_pii"] > 0 and P._gate_eval(rpii, G)[0] is False)
    rmut = P.build(ev(), SPEC, inject=["mutate_audit"])
    ok("C9 mutate_audit → audit_mutable>0 (WORM) + kapı eler",
       rmut["violations"]["audit_mutable"] > 0 and P._gate_eval(rmut, G)[0] is False)
    ok("C9 ham PII/token alanı yok",
       all(k not in json.dumps(r) for k in ("transcript_text_value", "break_glass_token_value", "approval_token_value")))

    # C10 — model integrity
    ok("C10 model_hash deterministik", P.build(ev(), SPEC)["model_hash"] == r["model_hash"])
    rt = P.build(ev(), SPEC, inject=["model_tamper"])
    ok("C10 model_tamper → model_tampered>0 + kapı eler",
       rt["violations"]["model_tampered"] > 0 and P._gate_eval(rt, G)[0] is False)

    # malformed → BLOCK
    ok("malformed-noreq → BLOCK", P.build(ev(request_id=None), SPEC)["note"] == "malformed")
    ok("malformed-tenantrole → BLOCK (L0 değil)", P.build(ev(actor_role="tenant_owner"), SPEC)["note"] == "malformed")
    ok("malformed-badtier → BLOCK", P.build(ev(tier="A"), SPEC)["note"] == "malformed")
    ok("malformed-badaccess → BLOCK", P.build(ev(access_decision="X"), SPEC)["note"] == "malformed")

    # C12 — leak tarayıcı
    ok("C12 rol/realm/sınıf/tier/profil temiz",
       P.scan_leaks('{"actor_role":"platform_owner","approver_role":"tenant_owner","realm":"tenant","tier":"B","regulated":true}') == [])
    ok("C12 approval_token_value yakalanır", len(P.scan_leaks('{"approval_token_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior_test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
