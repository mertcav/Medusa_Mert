#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.2 — Tier B break-glass: maker-checker + time-boxed token davranış testi (R1–R12; bağımsız).

tier_b_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (BRD §17.7 / SAD §14.4.2 / FR-IAM-009) bağımsız
assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x/12.3.1 deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tier_b_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def req(**kw):
    d = {
        "request_id": "req-t", "correlation_id": "corr-t", "actor_role": "platform_owner", "action": "read",
        "target_tenant_id": "t-acme", "resource_type": "transcript", "reason_code": "rc-incident-debug", "now": 100,
        "maker": {"actor_ref": "mk-1", "role": "platform_sre", "authorized": True, "realm": "platform"},
        "approvals": [{"approver_ref": "ck-1", "decision": "approve", "authorized": True, "realm": "platform", "at": 101}],
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt + default-DENY
    r1 = P.build(req(), SPEC)
    r2 = P.build(req(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal {GRANT_TIER_B|PENDING|DENY}", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "actor_role", "target_tenant_id", "reason_code", "ttl_minutes", "expires_at", "model_hash")))
    ok("R1 default DENY (malformed)", P.build(req(actor_role="bogus"), SPEC)["terminal"] == "DENY")

    # R2 — Tier B scope (yalnız tenant_content)
    ok("R2 transcript (tenant_content) → Tier B akışına girer", P.build(req(), SPEC)["data_class"] == "tenant_content")
    ok("R2 usage_record (tenant_metric) → DENY not_tier_b (break-glass gerekmez)",
       P.build(req(resource_type="usage_record"), SPEC)["note"] == "not_tier_b")
    ok("R2 agent (tenant_config) → DENY not_tier_b (L0 yolu yok)",
       P.build(req(resource_type="agent"), SPEC)["note"] == "not_tier_b")

    # R3 — ÇEKİRDEK SoD (talep eden ≠ onaylayan)
    rself = P.build(req(approvals=[{"approver_ref": "mk-1", "decision": "approve", "authorized": True, "realm": "platform", "at": 101}]), SPEC)
    ok("R3 maker kendi onayı (mk-1) dışlanır → PENDING (token YOK)", rself["terminal"] == "PENDING")
    ok("R3 doğru → sod_violation=0 + kapı geçer",
       rself["violations"]["sod_violation"] == 0 and P._gate_eval(rself, G)[0] is True)
    rsv = P.build(req(approvals=[{"approver_ref": "mk-1", "decision": "approve", "authorized": True, "realm": "platform", "at": 101}]),
                  SPEC, inject=["self_approval"])
    ok("R3 self_approval → sod_violation>0 + kapı eler",
       rsv["violations"]["sod_violation"] > 0 and P._gate_eval(rsv, G)[0] is False)

    # R4 — ÇEKİRDEK onaysız token yok
    rgood = P.build(req(), SPEC)
    ok("R4 maker≠checker + quorum → GRANT_TIER_B", rgood["terminal"] == "GRANT_TIER_B")
    rpend = P.build(req(approvals=[]), SPEC)
    ok("R4 onay yok → PENDING (token YOK) + kapı geçer",
       rpend["terminal"] == "PENDING" and P._gate_eval(rpend, G)[0] is True)
    rgwq = P.build(req(approvals=[]), SPEC, inject=["grant_without_quorum"])
    ok("R4 grant_without_quorum → GRANT + granted_without_approval>0 + kapı eler",
       rgwq["terminal"] == "GRANT_TIER_B" and rgwq["violations"]["granted_without_approval"] > 0
       and P._gate_eval(rgwq, G)[0] is False)

    # R5 — ÇEKİRDEK time-box 60/240
    ok("R5 ttl belirtilmedi → default 60dk + expires=now+60", rgood["ttl_minutes"] == 60 and rgood["expires_at"] == 160)
    ok("R5 ttl=240 (4sa tam) → GRANT (sınırda)", P.build(req(ttl_minutes=240), SPEC)["terminal"] == "GRANT_TIER_B")
    rmax = P.build(req(ttl_minutes=300), SPEC)
    ok("R5 ttl=300 (>240) → DENY ttl_over_max (reddedilir) + kapı geçer",
       rmax["terminal"] == "DENY" and rmax["note"] == "ttl_over_max" and P._gate_eval(rmax, G)[0] is True)
    rtte = P.build(req(ttl_minutes=300), SPEC, inject=["ttl_exceeds_max"])
    ok("R5 ttl_exceeds_max → GRANT ttl=300 + ttl_exceeds_max>0 + kapı eler",
       rtte["violations"]["ttl_exceeds_max"] > 0 and P._gate_eval(rtte, G)[0] is False)
    runb = P.build(req(), SPEC, inject=["unbounded_token"])
    ok("R5 unbounded_token → expires=None + unbounded_token>0 + kapı eler",
       runb["expires_at"] is None and runb["violations"]["unbounded_token"] > 0 and P._gate_eval(runb, G)[0] is False)

    # R6 — ÇEKİRDEK standing access yok + auto-expiry
    rexp = P.build(req(access={"tenant_id": "t-acme", "at": 500}), SPEC)
    ok("R6 access_at=500 > expires=160 → DENY token_expired (auto-expiry) + kapı geçer",
       rexp["terminal"] == "DENY" and rexp["note"] == "token_expired" and P._gate_eval(rexp, G)[0] is True)
    ruae = P.build(req(access={"tenant_id": "t-acme", "at": 500}), SPEC, inject=["use_after_expiry"])
    ok("R6 use_after_expiry → GRANT + expired_token_access>0 + kapı eler",
       ruae["terminal"] == "GRANT_TIER_B" and ruae["violations"]["expired_token_access"] > 0
       and P._gate_eval(ruae, G)[0] is False)
    rst = P.build(req(), SPEC, inject=["standing_access"])
    ok("R6 standing_access → standing_access>0 + expires=None + kapı eler",
       rst["violations"]["standing_access"] > 0 and rst["expires_at"] is None and P._gate_eval(rst, G)[0] is False)

    # R7 — token binding
    rxt = P.build(req(access={"tenant_id": "t-other", "at": 150}), SPEC)
    ok("R7 cross-tenant access → DENY token_binding + kapı geçer",
       rxt["terminal"] == "DENY" and rxt["note"] == "token_binding" and P._gate_eval(rxt, G)[0] is True)
    rxti = P.build(req(access={"tenant_id": "t-other", "at": 150}), SPEC, inject=["cross_tenant_token"])
    ok("R7 cross_tenant_token → GRANT + token_binding_violation>0 + kapı eler",
       rxti["violations"]["token_binding_violation"] > 0 and P._gate_eval(rxti, G)[0] is False)

    # R8 — audit emitted/PII-free/immutable (WORM)
    ok("R8 GRANT audit_emitted=True + row_hash + break_glass_id var",
       rgood["audit_emitted"] is True and rgood["audit_record"].get("row_hash") is not None
       and rgood["audit_record"].get("break_glass_id") is not None)
    ok("R8 PENDING/DENY de audit'lenir (her break-glass girişimi)",
       rpend["audit_emitted"] is True and P.build(req(resource_type="agent"), SPEC)["audit_emitted"] is True)
    rsk = P.build(req(), SPEC, inject=["skip_audit"])
    ok("R8 skip_audit → unaudited_grant>0 + kapı eler",
       rsk["violations"]["unaudited_grant"] > 0 and P._gate_eval(rsk, G)[0] is False)
    rpii = P.build(req(), SPEC, inject=["leak_pii_in_audit"])
    ok("R8 leak_pii_in_audit → audit_pii>0 + kapı eler",
       rpii["violations"]["audit_pii"] > 0 and P._gate_eval(rpii, G)[0] is False)
    rmut = P.build(req(), SPEC, inject=["mutate_audit"])
    ok("R8 mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
       rmut["violations"]["audit_mutable"] > 0 and P._gate_eval(rmut, G)[0] is False)
    ok("R8 normal audit ham PII/token alanı yok",
       all(k not in json.dumps(rgood) for k in ("transcript_text_value", "recording_audio_value", "break_glass_token_value")))

    # R9 — replay-safe
    rrep = P.build(req(prior_state="EXPIRED"), SPEC)
    ok("R9 prior_state=EXPIRED → DENY replay_blocked + kapı geçer",
       rrep["terminal"] == "DENY" and rrep["note"] == "replay_blocked" and P._gate_eval(rrep, G)[0] is True)
    rrepi = P.build(req(prior_state="EXPIRED"), SPEC, inject=["replay_grant"])
    ok("R9 replay_grant → GRANT + replay_reuse>0 + kapı eler",
       rrepi["violations"]["replay_reuse"] > 0 and P._gate_eval(rrepi, G)[0] is False)

    # R10 — model integrity
    rtam = P.build(req(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rtam["violations"]["model_tampered"] > 0 and P._gate_eval(rtam, G)[0] is False)
    ok("R10 model_hash deterministik", P.build(req(), SPEC)["model_hash"] == rgood["model_hash"])

    # R11/R12 — kardinalite + sızıntı
    ok("R12 rol+action+sınıf+tier+reason temiz",
       P.scan_leaks('{"actor_role":"platform_owner","action":"read","data_class":"tenant_content","tier":"B","reason_code":"rc-incident-debug"}') == [])
    ok("R12 break_glass_token_value yakalanır", len(P.scan_leaks('{"break_glass_token_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
