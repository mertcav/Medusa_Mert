#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.5 — Break-glass tam-audit router (ayrı, kısıtlı) davranış testi (C1–C12; bağımsız).

break_glass_router_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (SAD §14.4.2 'ayrı, kısıtlı,
tam-audit'li break-glass router' / FR-IAM-009 / BRD §17 / ADR-011) bağımsız assertion'larla doğrular.
selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x/12.3.x deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import break_glass_router_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def rctx(**kw):
    d = {"router_id": "break_glass", "plane": "platform_control_plane",
         "internal_only": True, "oauth_scope": "panel:L0:break_glass"}
    d.update(kw)
    return d


def tok(**kw):
    d = {"break_glass_id": "bg-t", "target_tenant_id": "t-acme", "tier": "B",
         "scope": ["transcript"], "granted_at": 100, "expires_at": 160, "state": "ACTIVE"}
    d.update(kw)
    return d


def ev(**kw):
    d = {
        "request_id": "req-t", "correlation_id": "corr-t", "break_glass_id": "bg-t",
        "actor_role": "platform_owner", "target_tenant_id": "t-acme", "tier": "B",
        "resource_type": "transcript", "data_class": "tenant_content",
        "router_context": rctx(), "sanction_decision": "ALLOW", "token": tok(), "access_tick": 120,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    def gate_ok(r):
        return P._gate_eval(r, G)[0]

    # ── C1 — determinizm + terminal + fail-closed + kanıt ──
    r = P.build(ev(), SPEC)
    ok("C1 happy ADMIT (routed)", r["terminal"] == "ADMIT" and r["note"] == "routed")
    ok("C1 terminal ADMIT/REJECT", r["terminal"] in P.TERMINAL)
    ok("C1 determinizm birebir", json.dumps(P.build(ev(), SPEC), sort_keys=True) == json.dumps(r, sort_keys=True))
    ok("C1 kanıt tam (model_hash + sanction + token_state + router_id)",
       r["model_hash"] and r["evidence"]["sanction_decision"] == "ALLOW"
       and r["evidence"]["token_state"] == "active" and r["evidence"]["router_id"] == "break_glass")
    ok("C1 stuck_state=0 + missing_evidence=0", r["violations"]["stuck_state"] == 0 and r["violations"]["missing_evidence"] == 0)
    ok("C1 default REJECT (fail-closed) — malformed", P.build(ev(request_id=None), SPEC)["terminal"] == "REJECT")
    ok("C1 happy ihlal yok + kapı geçer", all(x == 0 for x in r["violations"].values()) and gate_ok(r))

    # ── C2 ÇEKİRDEK — AYRI router izolasyonu (internal-only platform plane + dedicated scope) ──
    ok("C2 tenant düzlemi → REJECT", P.build(ev(router_context=rctx(plane="tenant_application_plane")), SPEC)["note"] == "router_isolation")
    ok("C2 internal_only=false → REJECT", P.build(ev(router_context=rctx(internal_only=False)), SPEC)["note"] == "router_isolation")
    ok("C2 yanlış router_id → REJECT", P.build(ev(router_context=rctx(router_id="L0")), SPEC)["note"] == "router_isolation")
    ok("C2 yanlış scope → REJECT", P.build(ev(router_context=rctx(oauth_scope="panel:L0")), SPEC)["note"] == "router_isolation")
    rmount = P.build(ev(router_context=rctx(plane="tenant_application_plane")), SPEC, inject=["mount_on_tenant_plane"])
    ok("C2 degrade mount_on_tenant_plane → router_isolation_violation>0 + kapı eler",
       rmount["violations"]["router_isolation_violation"] > 0 and not gate_ok(rmount))
    ok("C2 doğru → router_isolation_violation=0",
       P.build(ev(router_context=rctx(plane="tenant_application_plane")), SPEC)["violations"]["router_isolation_violation"] == 0)

    # ── C3 ÇEKİRDEK — KISITLI admission (sanction=ALLOW + geçerli token; no standing access) ──
    ok("C3 sanction=HOLD → REJECT (not_sanctioned)", P.build(ev(sanction_decision="HOLD"), SPEC)["note"] == "not_sanctioned")
    ok("C3 sanction=BLOCK → REJECT", P.build(ev(sanction_decision="BLOCK"), SPEC)["terminal"] == "REJECT")
    ok("C3 token yok → REJECT (token_missing)", P.build(ev(token=None), SPEC)["note"] == "token_missing")
    runs = P.build(ev(sanction_decision="HOLD"), SPEC, inject=["admit_unsanctioned"])
    ok("C3 degrade admit_unsanctioned → ADMIT + unsanctioned_admission>0 + kapı eler",
       runs["terminal"] == "ADMIT" and runs["violations"]["unsanctioned_admission"] > 0 and not gate_ok(runs))
    rntk = P.build(ev(token=None), SPEC, inject=["admit_without_token"])
    ok("C3 degrade admit_without_token → unsanctioned_admission>0 + kapı eler",
       rntk["violations"]["unsanctioned_admission"] > 0 and not gate_ok(rntk))

    # ── C4 ÇEKİRDEK — TAM-AUDIT (her istek WORM audit; sessiz erişim yok) ──
    ok("C4 ADMIT audit'li + row_hash", r["audit_emitted"] and r["audit_record"]["row_hash"])
    ok("C4 REJECT (not_sanctioned) de audit'li", P.build(ev(sanction_decision="HOLD"), SPEC)["audit_emitted"] is True)
    ok("C4 malformed da audit'li", P.build(ev(actor_role="x"), SPEC)["audit_emitted"] is True)
    rskip = P.build(ev(), SPEC, inject=["skip_audit"])
    ok("C4 degrade skip_audit → unaudited_request>0 + kapı eler",
       rskip["violations"]["unaudited_request"] > 0 and not gate_ok(rskip))
    ok("C4 audit token_state ENUM (DEĞER değil) + break_glass_id",
       r["audit_record"]["token_state"] == "active" and r["audit_record"]["break_glass_id"]
       and "token_value" not in r["audit_record"])

    # ── C5 — token expiry / auto-expiry (12.3.2 RESİPROKAL) ──
    ok("C5 access_tick>expires_at → REJECT (token_expired)", P.build(ev(access_tick=200), SPEC)["note"] == "token_expired")
    ok("C5 sınır access_tick==expires_at → geçerli (ADMIT)", P.build(ev(access_tick=160), SPEC)["terminal"] == "ADMIT")
    rexp = P.build(ev(access_tick=200), SPEC, inject=["admit_expired_token"])
    ok("C5 degrade admit_expired_token → expired_token_admission>0 + kapı eler",
       rexp["violations"]["expired_token_admission"] > 0 and not gate_ok(rexp))

    # ── C6 — token binding (least-privilege; FR-TEN-002) ──
    ok("C6 cross-tenant token → REJECT (token_misbound)", P.build(ev(token=tok(target_tenant_id="t-other")), SPEC)["note"] == "token_misbound")
    ok("C6 cross-grant token → REJECT", P.build(ev(token=tok(break_glass_id="bg-other")), SPEC)["note"] == "token_misbound")
    ok("C6 non-Tier-B token → REJECT", P.build(ev(token=tok(tier="A")), SPEC)["note"] == "token_misbound")
    rmis = P.build(ev(token=tok(target_tenant_id="t-other")), SPEC, inject=["admit_misbound_token"])
    ok("C6 degrade admit_misbound_token → token_misbinding>0 + kapı eler",
       rmis["violations"]["token_misbinding"] > 0 and not gate_ok(rmis))

    # ── C7 — scope-limited routing ──
    ok("C7 scope dışı resource → REJECT (out_of_scope)", P.build(ev(resource_type="recording"), SPEC)["note"] == "out_of_scope")
    ok("C7 non-Tier-B data_class → REJECT (out_of_scope)", P.build(ev(data_class="tenant_metric"), SPEC)["note"] == "out_of_scope")
    roos = P.build(ev(resource_type="recording"), SPEC, inject=["route_out_of_scope"])
    ok("C7 degrade route_out_of_scope → out_of_scope_routing>0 + kapı eler",
       roos["violations"]["out_of_scope_routing"] > 0 and not gate_ok(roos))

    # ── C8 — replay-safe (çözülmüş token) ──
    for st in ("CONSUMED", "REVOKED", "EXPIRED"):
        ok("C8 %s token → REJECT (token_resolved)" % st, P.build(ev(token=tok(state=st)), SPEC)["note"] == "token_resolved")
    rrep = P.build(ev(token=tok(state="CONSUMED")), SPEC, inject=["replay_token"])
    ok("C8 degrade replay_token → token_replay>0 + kapı eler",
       rrep["violations"]["token_replay"] > 0 and not gate_ok(rrep))

    # ── C9 — audit PII-free + immutable (WORM) ──
    rleak = P.build(ev(), SPEC, inject=["leak_pii"])
    ok("C9 degrade leak_pii → audit_pii>0 + kapı eler", rleak["violations"]["audit_pii"] > 0 and not gate_ok(rleak))
    rmut = P.build(ev(), SPEC, inject=["mutate_audit"])
    ok("C9 degrade mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
       rmut["violations"]["audit_mutable"] > 0 and not gate_ok(rmut))
    ok("C9 happy audit_pii=0 + audit_mutable=0", r["violations"]["audit_pii"] == 0 and r["violations"]["audit_mutable"] == 0)

    # ── C10 — model integrity manifesti ──
    rtam = P.build(ev(), SPEC, inject=["model_tamper"])
    ok("C10 degrade model_tamper → model_tampered>0 + kapı eler", rtam["violations"]["model_tampered"] > 0 and not gate_ok(rtam))
    ok("C10 happy model_tampered=0 + model_hash sabit", r["violations"]["model_tampered"] == 0
       and r["model_hash"] == P.build(ev(), SPEC)["model_hash"])

    # ── C12 — sızıntı tarayıcı temiz ──
    ok("C12 scan_leaks temiz metinde 0", len(P.scan_leaks('{"router_id":"break_glass","actor_role":"platform_owner"}')) == 0)

    npass = sum(1 for c, _ in checks if c)
    for c, name in checks:
        print(("  ✓ " if c else "  ✗ ") + name)
    total = len(checks)
    print("\nbehavior test: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


if __name__ == "__main__":
    sys.exit(run())
