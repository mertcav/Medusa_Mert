#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.3 — Tenant scope + RLS çift kontrol davranış testi (R1–R12; bağımsız).

rls_double_check_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (DB.md §6 / SAD §14.4.2 / FR-TEN-002)
bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.1 deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import rls_double_check_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
SL = "SET LOCAL"


def req(**kw):
    d = {
        "request_id": "req-t", "actor_realm": "tenant", "actor_tenant_id": "t-acme",
        "table": "call", "table_class": "tenant_scoped", "operation": "select", "db_role": "app_rw",
        "session": {"tenant_guc": "t-acme", "platform": "off", "guc_scope": SL},
        "row": {"tenant_id": "t-acme"}, "app_layer": "ALLOW",
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt
    r1 = P.build(req(), SPEC)
    r2 = P.build(req(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal PERMIT/DENY", r1["terminal"] in P.RLS_TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "table_class", "operation", "row_tenant_id", "app_layer", "model_hash")))
    ok("R1 default DENY (malformed)", P.build(req(table_class="bogus"), SPEC)["terminal"] == "DENY")

    # R5 — ÇEKİRDEK çift kontrol / sızıntı yok: app bug ama RLS bağımsız kapatır
    r = P.build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC)
    ok("R5 app bug ALLOW cross → RLS DENY (served=false)", r["served"] is False and r["terminal"] == "DENY")
    ok("R5 cross_tenant_leak=0 (RLS bağımsız kurtardı)", r["violations"]["cross_tenant_leak"] == 0)
    ok("R5 kapı geçer (defense in depth)", P._gate_eval(r, G)[0] is True)
    # app_only_trust degrade → bağımsızlık kaybı → leak
    rd = P.build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC, inject=["app_only_trust"])
    ok("R5 app_only_trust → cross_tenant_leak>0 + kapı eler",
       rd["violations"]["cross_tenant_leak"] > 0 and P._gate_eval(rd, G)[0] is False)

    # R2 — RLS etkin + FORCE + bypass-etmeyen rol
    for inj, key in (("rls_disable", "rls_disabled"), ("force_off", "force_missing"), ("bypass_role", "bypass_role")):
        rr = P.build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC, inject=[inj])
        ok("R2 %s → %s>0 + leak + kapı eler" % (inj, key),
           rr["violations"][key] > 0 and rr["violations"]["cross_tenant_leak"] > 0 and P._gate_eval(rr, G)[0] is False)

    # R3 — policy coverage
    rr = P.build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC, inject=["missing_policy"])
    ok("R3 missing_policy>0 + leak + kapı eler",
       rr["violations"]["missing_policy"] > 0 and rr["violations"]["cross_tenant_leak"] > 0 and P._gate_eval(rr, G)[0] is False)

    # R4 — GUC fail-closed NULLIF: unset + empty → DENY; degrade fail-open / fail-error
    ok("R4 unset GUC → DENY (fail-closed)",
       P.build(req(session={"tenant_guc": None, "platform": "off", "guc_scope": SL}), SPEC)["terminal"] == "DENY")
    ok("R4 empty('') GUC → DENY (NULLIF)",
       P.build(req(session={"tenant_guc": "", "platform": "off", "guc_scope": SL}), SPEC)["terminal"] == "DENY")
    rfo = P.build(req(session={"tenant_guc": None, "platform": "off", "guc_scope": SL},
                      row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC, inject=["guc_fail_open"])
    ok("R4 guc_fail_open>0 + leak + kapı eler",
       rfo["violations"]["guc_fail_open"] > 0 and rfo["violations"]["cross_tenant_leak"] > 0 and P._gate_eval(rfo, G)[0] is False)
    rfe = P.build(req(session={"tenant_guc": "", "platform": "off", "guc_scope": SL}), SPEC, inject=["bare_uuid_cast"])
    ok("R4 bare_uuid_cast → guc_fail_error>0 + kapı eler",
       rfe["violations"]["guc_fail_error"] > 0 and P._gate_eval(rfe, G)[0] is False)

    # R6 — WITH CHECK yazım koruması
    ok("R6 cross insert → DENY (reddedilir)",
       P.build(req(operation="insert", row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC)["terminal"] == "DENY")
    rwb = P.build(req(operation="insert", row={"tenant_id": "t-other"}, app_layer="ALLOW"), SPEC, inject=["write_bypass"])
    ok("R6 write_bypass → cross_tenant_write>0 + kapı eler",
       rwb["violations"]["cross_tenant_write"] > 0 and P._gate_eval(rwb, G)[0] is False)
    ok("R6 same-tenant insert → PERMIT",
       P.build(req(operation="insert", row={"tenant_id": "t-acme"}), SPEC)["terminal"] == "PERMIT")

    # R7 — platform scoping (L0 ⟂ tenant business PII)
    base_pf = dict(actor_realm="platform", actor_tenant_id=None, table="transcript", table_class="tenant_scoped",
                   session={"tenant_guc": None, "platform": "on", "guc_scope": SL},
                   row={"tenant_id": "t-acme"}, app_layer="ALLOW")
    ok("R7 platform transcript break-glass'sız → DENY",
       P.build(req(**base_pf), SPEC)["terminal"] == "DENY")
    rov = P.build(req(**base_pf), SPEC, inject=["platform_overreach"])
    ok("R7 platform_overreach>0 + leak + kapı eler",
       rov["violations"]["platform_overreach"] > 0 and rov["violations"]["cross_tenant_leak"] > 0 and P._gate_eval(rov, G)[0] is False)
    # platform_mixed null-tenant → PERMIT (meşru)
    ok("R7 platform audit null-tenant → PERMIT",
       P.build(req(actor_realm="platform", actor_tenant_id=None, table="audit_log", table_class="platform_mixed",
                   session={"tenant_guc": None, "platform": "on", "guc_scope": SL},
                   row={"tenant_id": None}), SPEC)["terminal"] == "PERMIT")

    # R8 — break-glass time-boxed
    bg_valid = dict(actor_realm="platform", actor_tenant_id=None, table="recording", table_class="tenant_scoped",
                    session={"tenant_guc": None, "platform": "on", "bg_tenant": "t-acme", "bg_active": "on", "guc_scope": SL},
                    row={"tenant_id": "t-acme"}, app_layer="ALLOW")
    rbv = P.build(req(**bg_valid), SPEC)
    ok("R8 geçerli grant → PERMIT (meşru) + bg_standing=0",
       rbv["terminal"] == "PERMIT" and rbv["violations"]["bg_standing_access"] == 0)
    bg_exp = dict(bg_valid)
    bg_exp["session"] = {"tenant_guc": None, "platform": "on", "bg_tenant": "t-acme", "bg_active": "off", "guc_scope": SL}
    rbs = P.build(req(**bg_exp), SPEC, inject=["bg_standing"])
    ok("R8 bg_standing (süre dolmuş servis) → bg_standing_access>0 + kapı eler",
       rbs["violations"]["bg_standing_access"] > 0 and P._gate_eval(rbs, G)[0] is False)

    # R9 — SET LOCAL pool izolasyonu
    rpl = P.build(req(), SPEC, inject=["pool_leak"])
    ok("R9 pool_leak (SET) → guc_pool_leak>0 + kapı eler",
       rpl["violations"]["guc_pool_leak"] > 0 and P._gate_eval(rpl, G)[0] is False)
    ok("R9 SET LOCAL → guc_pool_leak=0", P.build(req(), SPEC)["violations"]["guc_pool_leak"] == 0)

    # R10 — model bütünlük
    rmt = P.build(req(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rmt["violations"]["model_tampered"] > 0 and P._gate_eval(rmt, G)[0] is False)
    ok("R10 model_hash deterministik", P.build(req(), SPEC)["model_hash"] == P.build(req(), SPEC)["model_hash"])

    # R11/R12 — gözlemlenebilirlik kardinalite + sır/PII yok
    ok("R11 row_tenant_id label değil (trace only)",
       "row_tenant_id" in SPEC["observability"]["high_cardinality_trace_only"]
       and "row_tenant_id" not in SPEC["observability"]["low_cardinality_labels"])
    ok("R12 tablo+sınıf+GUC+policy temiz (leak yok)",
       P.scan_leaks('{"table":"call","table_class":"tenant_scoped","guc":"app.tenant_id","policy":"tenant_isolation"}') == [])
    ok("R12 PII alanı yakalanır", len(P.scan_leaks('{"contact_pii_value": "x"}')) > 0)
    ok("R12 karar çıktısında ham PII alanı yok",
       all(k not in json.dumps(r1) for k in ("transcript_text_value", "recording_audio_value", "contact_pii_value")))

    npass = sum(1 for c, _ in checks if c)
    for c, name in checks:
        print(("  ✓ " if c else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
