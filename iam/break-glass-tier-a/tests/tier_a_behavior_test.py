#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.1 — Tier A (metrik/log, PII yok): break-glass'sız L0 + audit davranış testi (R1–R12; bağımsız).

tier_a_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (BRD §17.7 / SAD §14.4.2 / FR-IAM-009) bağımsız
assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tier_a_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def req(**kw):
    d = {
        "request_id": "req-t", "correlation_id": "corr-t", "actor_role": "platform_owner",
        "action": "read", "resource_type": "usage_record", "occurred_tick": 1,
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
    ok("R1 terminal {TIER_A_GRANT|ESCALATE_TIER_B|DENY}", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "actor_role", "data_class", "resource_type", "tier", "model_hash")))
    ok("R1 default DENY (malformed)", P.build(req(actor_role="bogus"), SPEC)["terminal"] == "DENY")

    # R2 — classification coverage fail-closed
    runc = P.build(req(resource_type="mystery", data_class=None), SPEC, inject=["unclassify"])
    ok("R2 unclassify → unclassified_access>0 + kapı eler",
       runc["violations"]["unclassified_access"] > 0 and P._gate_eval(runc, G)[0] is False)
    ok("R2 bilinmeyen sınıf inject'siz → DENY (fail-closed)",
       P.build(req(resource_type="mystery", data_class="bogus"), SPEC)["terminal"] == "DENY")

    # R3 — NO PII UNDER TIER A (ÇEKİRDEK altın kural)
    rgood = P.build(req(resource_type="transcript"), SPEC)
    ok("R3 transcript (PII) → ESCALATE_TIER_B (Tier A'da sunulmaz)", rgood["terminal"] == "ESCALATE_TIER_B")
    ok("R3 doğru escalate → pii_under_tier_a=0 + kapı geçer",
       rgood["violations"]["pii_under_tier_a"] == 0 and P._gate_eval(rgood, G)[0] is True)
    rbad = P.build(req(resource_type="transcript"), SPEC, inject=["grant_content_at_tier_a"])
    ok("R3 grant_content_at_tier_a → pii_under_tier_a>0 + kapı eler",
       rbad["violations"]["pii_under_tier_a"] > 0 and P._gate_eval(rbad, G)[0] is False)

    # R4 — AUDIT EMITTED (sessiz erişim yok)
    rA = P.build(req(), SPEC)
    ok("R4 TIER_A_GRANT audit_emitted=True + row_hash var",
       rA["audit_emitted"] is True and rA["audit_record"].get("row_hash") is not None)
    rskip = P.build(req(), SPEC, inject=["skip_audit"])
    ok("R4 skip_audit → unaudited_access>0 + kapı eler",
       rskip["violations"]["unaudited_access"] > 0 and P._gate_eval(rskip, G)[0] is False)
    ok("R4 ESCALATE/DENY de audit'lenir (her L0 erişim girişimi)",
       P.build(req(resource_type="transcript"), SPEC)["audit_emitted"] is True
       and P.build(req(resource_type="agent"), SPEC)["audit_emitted"] is True)

    # R5 — NO BREAK-GLASS BYPASS
    ok("R5 grant_content_at_tier_a → break_glass_bypass>0 + kapı eler",
       rbad["violations"]["break_glass_bypass"] > 0 and P._gate_eval(rbad, G)[0] is False)
    ok("R5 doğru escalate → break_glass_bypass=0", rgood["violations"]["break_glass_bypass"] == 0)

    # R6 — ESCALATION CORRECT
    rdrop = P.build(req(resource_type="contact"), SPEC, inject=["drop_escalation"])
    ok("R6 drop_escalation → escalation_error>0 + terminal=DENY + kapı eler",
       rdrop["violations"]["escalation_error"] > 0 and rdrop["terminal"] == "DENY"
       and P._gate_eval(rdrop, G)[0] is False)
    ok("R6 forbidden (agent) DENY → escalation_error=0 (içerik değil)",
       P.build(req(resource_type="agent"), SPEC)["violations"]["escalation_error"] == 0)

    # R7 — AUDIT PII-FREE
    rleak = P.build(req(), SPEC, inject=["leak_pii_in_audit"])
    ok("R7 leak_pii_in_audit → audit_pii>0 + kapı eler",
       rleak["violations"]["audit_pii"] > 0 and P._gate_eval(rleak, G)[0] is False)
    ok("R7 normal audit ham PII alanı yok",
       all(k not in json.dumps(rA) for k in ("transcript_text_value", "recording_audio_value", "contact_pii_value")))

    # R8 — AUDIT IMMUTABILITY (WORM)
    rmut = P.build(req(), SPEC, inject=["mutate_audit"])
    ok("R8 mutate_audit → audit_mutable>0 + kapı eler",
       rmut["violations"]["audit_mutable"] > 0 and P._gate_eval(rmut, G)[0] is False)
    ok("R8 normal kayıt row_hash tutarlı (audit_mutable=0)", rA["violations"]["audit_mutable"] == 0)

    # R9 — TIER SEPARATION
    rtc = P.build(req(justification_code="JC", break_glass_token=True), SPEC, inject=["tier_b_artifact_at_tier_a"])
    ok("R9 tier_b_artifact_at_tier_a → tier_confusion>0 + kapı eler",
       rtc["violations"]["tier_confusion"] > 0 and P._gate_eval(rtc, G)[0] is False)
    ok("R9 Tier A token taşısa da (işlenmeden) ihlal yok",
       P.build(req(break_glass_token=True), SPEC)["violations"]["tier_confusion"] == 0)

    # R10 — MODEL INTEGRITY
    rtam = P.build(req(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rtam["violations"]["model_tampered"] > 0 and P._gate_eval(rtam, G)[0] is False)
    ok("R10 model_hash deterministik", P.build(req(), SPEC)["model_hash"] == rA["model_hash"])

    # R11/R12 — kardinalite + sızıntı
    ok("R12 rol+action+sınıf+tier temiz",
       P.scan_leaks('{"actor_role":"platform_owner","action":"read","data_class":"platform","tier":"A","resource_type":"audit_log"}') == [])
    ok("R12 transcript_text_value yakalanır", len(P.scan_leaks('{"transcript_text_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
