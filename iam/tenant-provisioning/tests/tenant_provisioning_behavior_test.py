#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.1 — Tenant CRUD + provisioning (L0) davranış testi (R1–R12; bağımsız).

tenant_provisioning_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (FR-TEN-001 / BRD §17 / DB.md §5.1/§9 /
NFR 10.6/10.7) bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt katmanıdır (12.1.x/12.2.x
deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tenant_provisioning_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def req(**kw):
    d = {
        "request_id": "req-t", "op": "read", "actor_realm": "platform",
        "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
        "current_status": "active", "tenant_id": "t-t",
    }
    d.update(kw)
    return d


def creq(**kw):
    d = {
        "request_id": "req-tc", "op": "create", "actor_realm": "platform",
        "plane": "platform_control_plane", "actor_permissions": ["tenant:provision"],
        "current_status": None, "tenant_id": "t-tn", "tenant_name": "T",
        "home_region": "EU", "kms_key_ref": "kms-eu-t", "isolation_mode": "shared",
        "compliance_profile": "PROFILE-EU", "default_locale": "tr-TR", "timezone": "Europe/Istanbul",
        "audit_emitted": True,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt + default-REJECT
    r1 = P.build(creq(), SPEC)
    r2 = P.build(creq(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal COMMIT/REJECT", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "op", "actor_realm", "plane", "target_status", "model_hash")))
    ok("R1 default REJECT (malformed)", P.build(req(op="bogus"), SPEC)["terminal"] == "REJECT")
    ok("R1 model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # R2 — realm izolasyonu (L0-only; FR-IAM-008)
    rcr = P.build(req(), SPEC, inject=["cross_realm"])
    ok("R2 cross_realm → cross_realm_op>0 + kapı eler",
       rcr["violations"]["cross_realm_op"] > 0 and P._gate_eval(rcr, G)[0] is False)
    ok("R2 tenant realm DOĞRU REJECT (ihlal yok)",
       P.build(req(actor_realm="tenant", plane="tenant_application_plane"), SPEC)["terminal"] == "REJECT"
       and P.build(req(actor_realm="tenant", plane="tenant_application_plane"), SPEC)["violations"]["cross_realm_op"] == 0)

    # R3 — yetkilendirme (op→permission-key)
    rdp = P.build(creq(), SPEC, inject=["drop_permission"])
    ok("R3 drop_permission → unauthorized_op>0 + kapı eler",
       rdp["violations"]["unauthorized_op"] > 0 and P._gate_eval(rdp, G)[0] is False)
    ok("R3 yetkisiz create DOĞRU REJECT (ihlal yok)",
       P.build(creq(actor_permissions=[]), SPEC)["terminal"] == "REJECT"
       and P.build(creq(actor_permissions=[]), SPEC)["violations"]["unauthorized_op"] == 0)
    ok("R3 suspend tenant:suspend gerektirir (tenant:provision yetmez)",
       P.build(req(op="suspend", current_status="active", actor_permissions=["tenant:provision"]), SPEC)["terminal"] == "REJECT")

    # R4 — geçiş geçerliliği (durum makinesi; terminated terminal)
    rit = P.build(req(op="activate", current_status="terminated"), SPEC, inject=["invalid_transition"])
    ok("R4 invalid_transition → invalid_transition>0 + kapı eler",
       rit["violations"]["invalid_transition"] > 0 and P._gate_eval(rit, G)[0] is False)
    ok("R4 terminated terminal: resume-on-terminated DOĞRU REJECT",
       P.build(req(op="resume", current_status="terminated"), SPEC)["terminal"] == "REJECT")
    ok("R4 activate-on-active DOĞRU REJECT (ihlal yok)",
       P.build(req(op="activate", current_status="active"), SPEC)["terminal"] == "REJECT"
       and P.build(req(op="activate", current_status="active"), SPEC)["violations"]["invalid_transition"] == 0)
    ok("R4 create happy → provisioning",
       P.build(creq(), SPEC)["target_status"] == "provisioning")

    # R5 — provisioning tamlığı (zorunlu izolasyon/residency alanları + ilk durum provisioning)
    rsp = P.build(creq(kms_key_ref=None), SPEC, inject=["skip_provisioning_field"])
    ok("R5 skip_provisioning_field → incomplete_provisioning>0 + kapı eler",
       rsp["violations"]["incomplete_provisioning"] > 0 and P._gate_eval(rsp, G)[0] is False)
    rda = P.build(creq(), SPEC, inject=["direct_active"])
    ok("R5 direct_active (provisioning atla) → incomplete_provisioning>0 + kapı eler",
       rda["violations"]["incomplete_provisioning"] > 0 and P._gate_eval(rda, G)[0] is False)
    ok("R5 geçersiz region DOĞRU REJECT", P.build(creq(home_region="XX"), SPEC)["terminal"] == "REJECT")
    ok("R5 geçersiz isolation_mode DOĞRU REJECT", P.build(creq(isolation_mode="bogus"), SPEC)["terminal"] == "REJECT")

    # R6 — tenant başına KMS (NFR 10.6)
    rsk = P.build(creq(kms_key_ref="kms-dup", existing_kms_keys=["kms-dup"]), SPEC, inject=["share_kms"])
    ok("R6 share_kms → shared_kms_key>0 + kapı eler",
       rsk["violations"]["shared_kms_key"] > 0 and P._gate_eval(rsk, G)[0] is False)
    ok("R6 çakışan key inject'siz DOĞRU REJECT (ihlal yok)",
       P.build(creq(kms_key_ref="kms-x", existing_kms_keys=["kms-x"]), SPEC)["terminal"] == "REJECT"
       and P.build(creq(kms_key_ref="kms-x", existing_kms_keys=["kms-x"]), SPEC)["violations"]["shared_kms_key"] == 0)

    # R7 — idempotent provision
    rdup = P.build(creq(tenant_exists=True), SPEC, inject=["duplicate_provision"])
    ok("R7 duplicate_provision → duplicate_provision>0 + kapı eler",
       rdup["violations"]["duplicate_provision"] > 0 and P._gate_eval(rdup, G)[0] is False)

    # R8 — geri döndürülemez terminate koruması (DB.md §9)
    rut = P.build(req(op="terminate", current_status="active"), SPEC, inject=["unguard_termination"])
    ok("R8 unguard_termination → unguarded_termination>0 + kapı eler",
       rut["violations"]["unguarded_termination"] > 0 and P._gate_eval(rut, G)[0] is False)
    ok("R8 confirm/gerekçe yok terminate DOĞRU REJECT",
       P.build(req(op="terminate", current_status="active", confirm_irreversible=False), SPEC)["terminal"] == "REJECT")
    ok("R8 confirm+gerekçe terminate COMMIT",
       P.build(req(op="terminate", current_status="active", confirm_irreversible=True, reason_code="RC-1"), SPEC)["terminal"] == "COMMIT")

    # R9 — WORM audit (her mutasyon)
    rsa = P.build(creq(audit_emitted=False), SPEC, inject=["skip_audit"])
    ok("R9 skip_audit → missing_audit>0 + kapı eler",
       rsa["violations"]["missing_audit"] > 0 and P._gate_eval(rsa, G)[0] is False)
    ok("R9 read mutasyon değil (audit'siz read COMMIT)",
       P.build(req(op="read", current_status="active", audit_emitted=False), SPEC)["terminal"] == "COMMIT")

    # R10 — model bütünlük manifesti
    rmt = P.build(req(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rmt["violations"]["model_tampered"] > 0 and P._gate_eval(rmt, G)[0] is False)

    # R11/R12 — kardinalite + sızıntı yok
    ok("R12 evidence ham PII/key materyali yok",
       all(k not in json.dumps(r1) for k in ("customer_name_value", "kms_key_material_value", "connection_string_value")))
    ok("R12 leak: op/status/realm/region/key-ref temiz",
       P.scan_leaks('{"op":"create","current_status":"provisioning","actor_realm":"platform","home_region":"ME","kms_key_ref":"kms-me-014"}') == [])
    ok("R12 leak: connection_string_value yakalanır", len(P.scan_leaks('{"connection_string_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
