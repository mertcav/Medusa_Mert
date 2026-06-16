#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.2 — Dedicated vs shared tenant (L0) davranış testi (R1–R12; bağımsız).

tenant_isolation_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (FR-TEN-005 / SAD §13.1 / ADR-006 /
DB.md §5.1/§6 / NFR 10.6/10.7) bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır
(12.1.x/12.2.x/12.4.1 deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tenant_isolation_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def sreq(**kw):
    d = {
        "request_id": "req-t", "op": "assign", "actor_realm": "platform",
        "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
        "tenant_id": "t-t", "isolation_mode": "shared", "runtime_placement": "shared_pool",
        "rls_enabled": True, "kms_key_ref": "kms-eu-t", "surface_region": "EU", "home_region": "EU",
        "audit_emitted": True,
    }
    d.update(kw)
    return d


def dreq(**kw):
    d = {
        "request_id": "req-td", "op": "provision_surface", "actor_realm": "platform",
        "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
        "tenant_id": "t-td", "isolation_mode": "dedicated", "runtime_placement": "dedicated_cluster",
        "rls_enabled": True, "kms_key_ref": "kms-me-td", "surface_region": "ME", "home_region": "ME",
        "audit_emitted": True,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt + default-REJECT
    r1 = P.build(dreq(), SPEC)
    r2 = P.build(dreq(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal COMMIT/REJECT", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "op", "actor_realm", "plane", "isolation_mode", "runtime_placement", "model_hash")))
    ok("R1 default REJECT (malformed)", P.build(sreq(op="bogus"), SPEC)["terminal"] == "REJECT")
    ok("R1 model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # R2 — realm izolasyonu (L0-only; FR-IAM-008)
    rcr = P.build(sreq(), SPEC, inject=["cross_realm"])
    ok("R2 cross_realm → cross_realm_op>0 + kapı eler",
       rcr["violations"]["cross_realm_op"] > 0 and P._gate_eval(rcr, G)[0] is False)
    ok("R2 tenant realm DOĞRU REJECT (ihlal yok)",
       P.build(sreq(actor_realm="tenant", plane="tenant_application_plane"), SPEC)["terminal"] == "REJECT"
       and P.build(sreq(actor_realm="tenant", plane="tenant_application_plane"), SPEC)["violations"]["cross_realm_op"] == 0)

    # R3 — yetkilendirme (op→tenant:provision)
    rdp = P.build(sreq(), SPEC, inject=["drop_permission"])
    ok("R3 drop_permission → unauthorized_op>0 + kapı eler",
       rdp["violations"]["unauthorized_op"] > 0 and P._gate_eval(rdp, G)[0] is False)
    ok("R3 yetkisiz DOĞRU REJECT (ihlal yok)",
       P.build(sreq(actor_permissions=[]), SPEC)["terminal"] == "REJECT"
       and P.build(sreq(actor_permissions=[]), SPEC)["violations"]["unauthorized_op"] == 0)

    # R4 — mod→yüzey bağlaması (shared⇒shared_pool / dedicated⇒namespace,cluster + migrate korumalı)
    rmm = P.build(sreq(), SPEC, inject=["mode_mismatch"])
    ok("R4 mode_mismatch → mode_surface_mismatch>0 + kapı eler",
       rmm["violations"]["mode_surface_mismatch"] > 0 and P._gate_eval(rmm, G)[0] is False)
    ok("R4 shared+dedicated yüzey DOĞRU REJECT (ihlal yok)",
       P.build(sreq(runtime_placement="dedicated_cluster"), SPEC)["terminal"] == "REJECT"
       and P.build(sreq(runtime_placement="dedicated_cluster"), SPEC)["violations"]["mode_surface_mismatch"] == 0)
    rug = P.build(dreq(op="migrate", current_mode="shared", migration_plan="MP", confirm=True), SPEC, inject=["ungoverned_migration"])
    ok("R4 ungoverned_migration → mode_surface_mismatch>0 + kapı eler",
       rug["violations"]["mode_surface_mismatch"] > 0 and P._gate_eval(rug, G)[0] is False)
    ok("R4 korumasız migrate (plan/confirm yok) DOĞRU REJECT",
       P.build(dreq(op="migrate", current_mode="shared", confirm=False), SPEC)["terminal"] == "REJECT")
    ok("R4 korumalı migrate (plan+confirm) COMMIT",
       P.build(dreq(op="migrate", current_mode="shared", migration_plan="MP", confirm=True), SPEC)["terminal"] == "COMMIT")
    ok("R4 geçersiz mod (malformed) REJECT", P.build(sreq(isolation_mode="hybrid"), SPEC)["terminal"] == "REJECT")

    # R5 — dedicated ayrım (shared havuza yerleşemez; SAD §13.1)
    rds = P.build(dreq(), SPEC, inject=["dedicated_on_shared"])
    ok("R5 dedicated_on_shared → dedicated_in_shared_pool>0 + kapı eler",
       rds["violations"]["dedicated_in_shared_pool"] > 0 and P._gate_eval(rds, G)[0] is False)
    ok("R5 dedicated+shared_pool DOĞRU REJECT (ihlal yok)",
       P.build(dreq(runtime_placement="shared_pool"), SPEC)["terminal"] == "REJECT"
       and P.build(dreq(runtime_placement="shared_pool"), SPEC)["violations"]["dedicated_in_shared_pool"] == 0)

    # R6 — RLS her iki modda (DB.md §6; dedicated RLS'i kaldırmaz)
    rwr = P.build(dreq(), SPEC, inject=["waive_rls"])
    ok("R6 waive_rls → rls_waived>0 + kapı eler",
       rwr["violations"]["rls_waived"] > 0 and P._gate_eval(rwr, G)[0] is False)
    ok("R6 shared modda RLS kapalı DOĞRU REJECT", P.build(sreq(rls_enabled=False), SPEC)["terminal"] == "REJECT")
    ok("R6 dedicated modda RLS kapalı DOĞRU REJECT", P.build(dreq(rls_enabled=False), SPEC)["terminal"] == "REJECT")

    # R7 — tenant başına KMS her iki modda (NFR 10.6)
    rsk = P.build(sreq(kms_key_ref="kms-dup", existing_kms_keys=["kms-dup"]), SPEC, inject=["share_kms"])
    ok("R7 share_kms → shared_kms_key>0 + kapı eler",
       rsk["violations"]["shared_kms_key"] > 0 and P._gate_eval(rsk, G)[0] is False)
    ok("R7 çakışan key inject'siz DOĞRU REJECT (ihlal yok)",
       P.build(dreq(kms_key_ref="kms-x", existing_kms_keys=["kms-x"]), SPEC)["terminal"] == "REJECT"
       and P.build(dreq(kms_key_ref="kms-x", existing_kms_keys=["kms-x"]), SPEC)["violations"]["shared_kms_key"] == 0)

    # R8 — residency tutarlılığı (surface==home_region; NFR 10.7)
    rrd = P.build(sreq(), SPEC, inject=["residency_drift"])
    ok("R8 residency_drift → residency_mismatch>0 + kapı eler",
       rrd["violations"]["residency_mismatch"] > 0 and P._gate_eval(rrd, G)[0] is False)
    ok("R8 surface≠home DOĞRU REJECT (ihlal yok)",
       P.build(dreq(surface_region="NA", home_region="EU"), SPEC)["terminal"] == "REJECT"
       and P.build(dreq(surface_region="NA", home_region="EU"), SPEC)["violations"]["residency_mismatch"] == 0)

    # R9 — WORM audit (her mutasyon)
    rsa = P.build(sreq(), SPEC, inject=["skip_audit"])
    ok("R9 skip_audit → missing_audit>0 + kapı eler",
       rsa["violations"]["missing_audit"] > 0 and P._gate_eval(rsa, G)[0] is False)
    ok("R9 read mutasyon değil (audit'siz read COMMIT)",
       P.build(sreq(op="read", audit_emitted=False), SPEC)["terminal"] == "COMMIT")

    # R10 — model bütünlük manifesti
    rmt = P.build(sreq(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rmt["violations"]["model_tampered"] > 0 and P._gate_eval(rmt, G)[0] is False)

    # R11/R12 — kardinalite + sızıntı yok
    ok("R12 evidence ham PII/key materyali yok",
       all(k not in json.dumps(r1) for k in ("customer_name_value", "kms_key_material_value", "connection_string_value")))
    ok("R12 leak: op/mode/placement/realm/region/key-ref temiz",
       P.scan_leaks('{"op":"provision_surface","isolation_mode":"dedicated","runtime_placement":"dedicated_cluster","actor_realm":"platform","surface_region":"ME","kms_key_ref":"kms-me-014"}') == [])
    ok("R12 leak: connection_string_value yakalanır", len(P.scan_leaks('{"connection_string_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
