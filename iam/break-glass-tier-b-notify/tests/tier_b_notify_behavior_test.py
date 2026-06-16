#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.3 — Tier B break-glass: gerekçe kodu + tenant bildirimi davranış testi (N1–N12; bağımsız).

tier_b_notify_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (BRD §17.7 / SAD §14.4.2 / FR-IAM-009)
bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x/12.3.1/12.3.2 deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tier_b_notify_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def ev(**kw):
    d = {
        "request_id": "req-t", "correlation_id": "corr-t", "break_glass_id": "bg-t",
        "actor_role": "platform_owner", "target_tenant_id": "t-acme", "tier": "B",
        "resource_type": "transcript", "data_class": "tenant_content",
        "access_decision": "GRANT_TIER_B", "reason_code": "rc-incident-debug", "now": 100,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # N1 — determinizm + terminal + kanıt + default-BLOCK + access routing
    r1 = P.build(ev(), SPEC)
    r2 = P.build(ev(), SPEC)
    ok("N1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("N1 terminal {NOTIFY|NO_NOTIFY|BLOCK}", r1["terminal"] in P.TERMINAL)
    ok("N1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "actor_role", "target_tenant_id", "access_decision", "reason_code",
                           "tier", "notified_roles", "delivered", "model_hash")))
    ok("N1 default BLOCK (malformed)", P.build(ev(actor_role="bogus"), SPEC)["terminal"] == "BLOCK")
    ok("N1 access routing: PENDING → NO_NOTIFY (içerik okunmadı) + kapı geçer",
       P.build(ev(access_decision="PENDING"), SPEC)["terminal"] == "NO_NOTIFY"
       and P._gate_eval(P.build(ev(access_decision="PENDING"), SPEC), G)[0] is True)
    ok("N1 access routing: DENY → NO_NOTIFY", P.build(ev(access_decision="DENY"), SPEC)["terminal"] == "NO_NOTIFY")

    # N2 — ÇEKİRDEK gerekçe kodu zorunlu
    rmiss = P.build(ev(reason_code=None), SPEC)
    ok("N2 reason_code yok → BLOCK missing_reason_code + kapı geçer",
       rmiss["terminal"] == "BLOCK" and rmiss["note"] == "missing_reason_code" and P._gate_eval(rmiss, G)[0] is True)
    romit = P.build(ev(reason_code=None), SPEC, inject=["omit_reason_code"])
    ok("N2 omit_reason_code → NOTIFY + missing_reason_code>0 + kapı eler",
       romit["terminal"] == "NOTIFY" and romit["violations"]["missing_reason_code"] > 0
       and P._gate_eval(romit, G)[0] is False)

    # N3 — ÇEKİRDEK gerekçe kodu semantiği (kontrollü katalog)
    rinv = P.build(ev(reason_code="freeform-text"), SPEC)
    ok("N3 katalog dışı → BLOCK invalid_reason_code + kapı geçer",
       rinv["terminal"] == "BLOCK" and rinv["note"] == "invalid_reason_code" and P._gate_eval(rinv, G)[0] is True)
    ok("N3 katalogdaki kod (rc-legal-hold) → NOTIFY",
       P.build(ev(reason_code="rc-legal-hold"), SPEC)["terminal"] == "NOTIFY")
    rfree = P.build(ev(reason_code="freeform-text"), SPEC, inject=["freeform_reason"])
    ok("N3 freeform_reason → NOTIFY + invalid_reason_code>0 + kapı eler",
       rfree["terminal"] == "NOTIFY" and rfree["violations"]["invalid_reason_code"] > 0
       and P._gate_eval(rfree, G)[0] is False)

    # N4 — ÇEKİRDEK her iki alıcı rol
    rgood = P.build(ev(), SPEC)
    ok("N4 doğru → her iki rol (SCO+owner) bildirildi + incomplete_recipients=0 + kapı geçer",
       set(rgood["notified_roles"]) == set(P.RECIPIENT_ROLES)
       and rgood["violations"]["incomplete_recipients"] == 0 and P._gate_eval(rgood, G)[0] is True)
    rdsco = P.build(ev(), SPEC, inject=["drop_sco_recipient"])
    ok("N4 drop_sco_recipient → incomplete_recipients>0 + kapı eler",
       rdsco["violations"]["incomplete_recipients"] > 0 and P._gate_eval(rdsco, G)[0] is False)
    rdown = P.build(ev(), SPEC, inject=["drop_owner_recipient"])
    ok("N4 drop_owner_recipient → incomplete_recipients>0 + kapı eler",
       rdown["violations"]["incomplete_recipients"] > 0 and P._gate_eval(rdown, G)[0] is False)

    # N5 — ÇEKİRDEK anlık bildirim
    ok("N5 doğru (SLA içinde) → delayed_notification=0", rgood["violations"]["delayed_notification"] == 0)
    rdelay = P.build(ev(), SPEC, inject=["delayed_notification"])
    ok("N5 delayed_notification → delayed_notification>0 + kapı eler",
       rdelay["violations"]["delayed_notification"] > 0 and P._gate_eval(rdelay, G)[0] is False)

    # N6 — ÇEKİRDEK sessiz break-glass yok (teslim)
    ok("N6 doğru → delivered=True + notification_dropped=0", rgood["delivered"] is True
       and rgood["violations"]["notification_dropped"] == 0)
    rsupp = P.build(ev(), SPEC, inject=["suppress_notification"])
    ok("N6 suppress_notification → notification_dropped>0 + delivered=False + kapı eler",
       rsupp["violations"]["notification_dropped"] > 0 and rsupp["delivered"] is False
       and P._gate_eval(rsupp, G)[0] is False)

    # N7 — bildirim tenant-binding
    ok("N7 doğru → notification_misroute=0", rgood["violations"]["notification_misroute"] == 0)
    rxt = P.build(ev(), SPEC, inject=["cross_tenant_recipient"])
    ok("N7 cross_tenant_recipient → notification_misroute>0 + kapı eler",
       rxt["violations"]["notification_misroute"] > 0 and P._gate_eval(rxt, G)[0] is False)

    # N8 — audit emitted/PII-free/immutable (WORM)
    ok("N8 NOTIFY audit_emitted=True + row_hash + break_glass_id var",
       rgood["audit_emitted"] is True and rgood["audit_record"].get("row_hash") is not None
       and rgood["audit_record"].get("break_glass_id") is not None)
    ok("N8 NO_NOTIFY/BLOCK de audit'lenir (her break-glass girişimi)",
       P.build(ev(access_decision="DENY"), SPEC)["audit_emitted"] is True
       and P.build(ev(reason_code=None), SPEC)["audit_emitted"] is True)
    rsk = P.build(ev(), SPEC, inject=["skip_audit"])
    ok("N8 skip_audit → unaudited_notification>0 + kapı eler",
       rsk["violations"]["unaudited_notification"] > 0 and P._gate_eval(rsk, G)[0] is False)
    rpii = P.build(ev(), SPEC, inject=["leak_pii_in_notification"])
    ok("N8 leak_pii_in_notification → audit_pii>0 + kapı eler",
       rpii["violations"]["audit_pii"] > 0 and P._gate_eval(rpii, G)[0] is False)
    rmut = P.build(ev(), SPEC, inject=["mutate_audit"])
    ok("N8 mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
       rmut["violations"]["audit_mutable"] > 0 and P._gate_eval(rmut, G)[0] is False)
    ok("N8 normal audit/bildirim ham PII/token alanı yok",
       all(k not in json.dumps(rgood) for k in ("transcript_text_value", "recording_audio_value", "break_glass_token_value")))

    # N9 — replay-safe / idempotent
    rrep = P.build(ev(prior_state="DELIVERED"), SPEC)
    ok("N9 prior_state=DELIVERED → NO_NOTIFY already_notified + kapı geçer",
       rrep["terminal"] == "NO_NOTIFY" and rrep["note"] == "already_notified" and P._gate_eval(rrep, G)[0] is True)
    rrepi = P.build(ev(prior_state="DELIVERED"), SPEC, inject=["notify_replay"])
    ok("N9 notify_replay → NOTIFY + notify_replay>0 + kapı eler",
       rrepi["violations"]["notify_replay"] > 0 and P._gate_eval(rrepi, G)[0] is False)

    # N10 — model integrity
    rtam = P.build(ev(), SPEC, inject=["model_tamper"])
    ok("N10 model_tamper → model_tampered>0 + kapı eler",
       rtam["violations"]["model_tampered"] > 0 and P._gate_eval(rtam, G)[0] is False)
    ok("N10 model_hash deterministik", P.build(ev(), SPEC)["model_hash"] == rgood["model_hash"])

    # N11/N12 — kardinalite + sızıntı
    ok("N12 rol+sınıf+tier+reason+alıcı-rol temiz",
       P.scan_leaks('{"actor_role":"platform_owner","data_class":"tenant_content","tier":"B","reason_code":"rc-incident-debug","notified_roles":["security_compliance_officer","tenant_owner"]}') == [])
    ok("N12 break_glass_token_value yakalanır", len(P.scan_leaks('{"break_glass_token_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
