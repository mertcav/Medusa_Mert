#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.3 — Org yapısı (marka/departman/ülke/proje) (L1) davranış testi (R1–R12; bağımsız).

org_structure_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (FR-TEN-003 / DB.md §5.1 / BRD §17 /
SAD §14.4 / FR-TEN-002 / NFR 10.7) bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir kanıt
katmanıdır (12.1.x/12.2.x/12.4.x deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import org_structure_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def creq(**kw):
    d = {
        "request_id": "req-t", "op": "create", "actor_realm": "tenant",
        "plane": "tenant_application_plane", "actor_permissions": ["org:manage"],
        "tenant_id": "t-t", "org_unit_id": "ou-t", "type": "brand", "name": "Marka-T",
        "parent_id": None, "region": "EU", "tenant_allowed_regions": ["EU", "UK"],
        "audit_emitted": True,
    }
    d.update(kw)
    return d


def childreq(**kw):
    d = {
        "request_id": "req-tc", "op": "create", "actor_realm": "tenant",
        "plane": "tenant_application_plane", "actor_permissions": ["org:manage"],
        "tenant_id": "t-t", "org_unit_id": "ou-tc", "type": "department", "name": "Satis-T",
        "parent_id": "ou-tb", "parent_tenant_id": "t-t", "ancestor_ids": ["ou-tb"],
        "sibling_names": ["Pazarlama"], "depth": 2, "region": "EU",
        "tenant_allowed_regions": ["EU", "UK"], "audit_emitted": True,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt + default-REJECT
    r1 = P.build(childreq(), SPEC)
    r2 = P.build(childreq(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal COMMIT/REJECT", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "op", "actor_realm", "plane", "org_type", "model_hash")))
    ok("R1 default REJECT (malformed)", P.build(creq(op="bogus"), SPEC)["terminal"] == "REJECT")
    ok("R1 model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # R2 — tenant izolasyonu (L1-only + kendi tenant; FR-TEN-002)
    rct = P.build(creq(op="update", org_unit_id="ou-x"), SPEC, inject=["cross_tenant"])
    ok("R2 cross_tenant → cross_tenant_op>0 + kapı eler",
       rct["violations"]["cross_tenant_op"] > 0 and P._gate_eval(rct, G)[0] is False)
    rwr = P.build(creq(), SPEC, inject=["wrong_realm"])
    ok("R2 wrong_realm (platform L0) → cross_tenant_op>0 + kapı eler",
       rwr["violations"]["cross_tenant_op"] > 0 and P._gate_eval(rwr, G)[0] is False)
    ok("R2 cross-tenant DOĞRU REJECT (ihlal yok)",
       P.build(creq(op="update", org_unit_id="ou-x", org_unit_tenant_id="t-999"), SPEC)["terminal"] == "REJECT"
       and P.build(creq(op="update", org_unit_id="ou-x", org_unit_tenant_id="t-999"), SPEC)["violations"]["cross_tenant_op"] == 0)
    ok("R2 cross-tenant ebeveyn DOĞRU REJECT (ihlal yok)",
       P.build(childreq(parent_tenant_id="t-999"), SPEC)["terminal"] == "REJECT"
       and P.build(childreq(parent_tenant_id="t-999"), SPEC)["violations"]["cross_tenant_op"] == 0)
    ok("R2 platform realm DOĞRU REJECT (ihlal yok)",
       P.build(creq(actor_realm="platform", plane="platform_control_plane"), SPEC)["terminal"] == "REJECT")

    # R3 — yetkilendirme (op→org:manage)
    rdp = P.build(creq(), SPEC, inject=["drop_permission"])
    ok("R3 drop_permission → unauthorized_op>0 + kapı eler",
       rdp["violations"]["unauthorized_op"] > 0 and P._gate_eval(rdp, G)[0] is False)
    ok("R3 yetkisiz DOĞRU REJECT (ihlal yok)",
       P.build(creq(actor_permissions=[]), SPEC)["terminal"] == "REJECT"
       and P.build(creq(actor_permissions=[]), SPEC)["violations"]["unauthorized_op"] == 0)

    # R4 — tip geçerliliği (brand/country/department/project; DB.md §5.1 CHECK)
    rit = P.build(creq(), SPEC, inject=["invalid_type"])
    ok("R4 invalid_type → invalid_type>0 + kapı eler",
       rit["violations"]["invalid_type"] > 0 and P._gate_eval(rit, G)[0] is False)
    for t in P.ORG_TYPES:
        ok("R4 geçerli tip %s COMMIT" % t, P.build(creq(type=t, name="N-%s" % t), SPEC)["terminal"] == "COMMIT")
    ok("R4 geçersiz tip DOĞRU REJECT (ihlal yok)",
       P.build(creq(type="franchise"), SPEC)["terminal"] == "REJECT"
       and P.build(creq(type="franchise"), SPEC)["violations"]["invalid_type"] == 0)

    # R5 — hiyerarşi bütünlüğü (döngüsüz + derinlik; DB.md §5.1 self-ref)
    rhc = P.build(childreq(op="move"), SPEC, inject=["hierarchy_cycle"])
    ok("R5 hierarchy_cycle → hierarchy_violation>0 + kapı eler",
       rhc["violations"]["hierarchy_violation"] > 0 and P._gate_eval(rhc, G)[0] is False)
    ok("R5 döngü DOĞRU REJECT (org_unit_id ∈ ancestor_ids)",
       P.build(childreq(op="move", org_unit_id="ou-tc", parent_id="ou-z", ancestor_ids=["ou-tc"]), SPEC)["terminal"] == "REJECT"
       and P.build(childreq(op="move", org_unit_id="ou-tc", parent_id="ou-z", ancestor_ids=["ou-tc"]), SPEC)["violations"]["hierarchy_violation"] == 0)
    ok("R5 derinlik aşımı DOĞRU REJECT", P.build(childreq(depth=P.MAX_DEPTH + 1), SPEC)["terminal"] == "REJECT")
    ok("R5 ebeveyn kendisi DOĞRU REJECT",
       P.build(childreq(op="move", org_unit_id="ou-self", parent_id="ou-self"), SPEC)["terminal"] == "REJECT")

    # R6 — kardeş benzersizliği (UNIQUE (tenant_id,parent_id,name))
    rdn = P.build(creq(), SPEC, inject=["duplicate_name"])
    ok("R6 duplicate_name → duplicate_name>0 + kapı eler",
       rdn["violations"]["duplicate_name"] > 0 and P._gate_eval(rdn, G)[0] is False)
    ok("R6 ad çakışması DOĞRU REJECT (ihlal yok)",
       P.build(childreq(name="Pazarlama"), SPEC)["terminal"] == "REJECT"
       and P.build(childreq(name="Pazarlama"), SPEC)["violations"]["duplicate_name"] == 0)

    # R7 — residency (region tenant izinli; NFR 10.7)
    rrd = P.build(creq(), SPEC, inject=["residency_drift"])
    ok("R7 residency_drift → residency_violation>0 + kapı eler",
       rrd["violations"]["residency_violation"] > 0 and P._gate_eval(rrd, G)[0] is False)
    ok("R7 tenant izinli dışı region DOĞRU REJECT (ihlal yok)",
       P.build(creq(region="NA", tenant_allowed_regions=["EU", "UK"]), SPEC)["terminal"] == "REJECT"
       and P.build(creq(region="NA", tenant_allowed_regions=["EU", "UK"]), SPEC)["violations"]["residency_violation"] == 0)
    ok("R7 region yok (devralınır) COMMIT", P.build(creq(region=None), SPEC)["terminal"] == "COMMIT")

    # R8 — silme koruması (çocuk/scope-referansı → cascade+confirm)
    rud = P.build(creq(op="delete", org_unit_id="ou-mid"), SPEC, inject=["unsafe_delete"])
    ok("R8 unsafe_delete → unsafe_delete>0 + kapı eler",
       rud["violations"]["unsafe_delete"] > 0 and P._gate_eval(rud, G)[0] is False)
    ok("R8 çocuklu korumasız silme DOĞRU REJECT",
       P.build(creq(op="delete", org_unit_id="ou-m", has_children=True), SPEC)["terminal"] == "REJECT")
    ok("R8 scope-referanslı korumasız silme DOĞRU REJECT",
       P.build(creq(op="delete", org_unit_id="ou-m", referenced_by_scope=True), SPEC)["terminal"] == "REJECT")
    ok("R8 çocuklu + cascade+confirm COMMIT",
       P.build(creq(op="delete", org_unit_id="ou-m", has_children=True, cascade=True, confirm=True), SPEC)["terminal"] == "COMMIT")
    ok("R8 yaprak (referanssız) silme COMMIT",
       P.build(creq(op="delete", org_unit_id="ou-leaf"), SPEC)["terminal"] == "COMMIT")

    # R9 — WORM audit (her mutasyon)
    rsa = P.build(creq(), SPEC, inject=["skip_audit"])
    ok("R9 skip_audit → missing_audit>0 + kapı eler",
       rsa["violations"]["missing_audit"] > 0 and P._gate_eval(rsa, G)[0] is False)
    ok("R9 read mutasyon değil (audit'siz read COMMIT)",
       P.build(creq(op="read", org_unit_id="ou-1", audit_emitted=False), SPEC)["terminal"] == "COMMIT")

    # R10 — model bütünlük manifesti
    rmt = P.build(creq(), SPEC, inject=["model_tamper"])
    ok("R10 model_tamper → model_tampered>0 + kapı eler",
       rmt["violations"]["model_tampered"] > 0 and P._gate_eval(rmt, G)[0] is False)

    # R11/R12 — kardinalite + sızıntı yok
    ok("R12 evidence ham PII yok",
       all(k not in json.dumps(r1) for k in ("customer_name_value", "transcript_text_value", "connection_string_value")))
    ok("R12 leak: op/type/realm/region/slug temiz",
       P.scan_leaks('{"op":"create","type":"department","actor_realm":"tenant","region":"EU","org_unit_id":"ou-001","name":"Satis"}') == [])
    ok("R12 leak: connection_string_value yakalanır", len(P.scan_leaks('{"connection_string_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
