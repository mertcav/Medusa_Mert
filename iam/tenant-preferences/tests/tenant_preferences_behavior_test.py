#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.4.4 — Tenant dil/saat dilimi/bölge/saklama tercihi (L1) davranış testi (R1–R11; bağımsız).

tenant_preferences_probe.build() motorunu DOĞRUDAN sürer; invariant'ları (FR-TEN-004 / DB.md §5.1/§9 / BRD §17 /
NFR 10.7 / DPIA §8 / FR-TEN-002 / FR-REC-006/010) bağımsız assertion'larla doğrular. selftest'ten ayrı ikinci bir
kanıt katmanıdır (12.1.x/12.2.x/12.4.x deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD_DIR = os.path.dirname(HERE)
sys.path.insert(0, MOD_DIR)

import tenant_preferences_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]


def lreq(**kw):
    d = {
        "request_id": "req-t", "op": "set", "actor_realm": "tenant",
        "plane": "tenant_application_plane", "actor_permissions": ["compliance:manage"],
        "tenant_id": "t-t", "category": "locale", "value": "tr-TR", "audit_emitted": True,
    }
    d.update(kw)
    return d


def rreq(**kw):
    d = {
        "request_id": "req-tr", "op": "set", "actor_realm": "tenant",
        "plane": "tenant_application_plane", "actor_permissions": ["compliance:manage"],
        "tenant_id": "t-t", "category": "residency", "value": "EU",
        "tenant_allowed_regions": ["EU", "UK"], "audit_emitted": True,
    }
    d.update(kw)
    return d


def rtreq(**kw):
    d = {
        "request_id": "req-trt", "op": "set", "actor_realm": "tenant",
        "plane": "tenant_application_plane", "actor_permissions": ["retention:manage"],
        "tenant_id": "t-t", "category": "retention", "value": 365,
        "data_class": "recording", "compliance_min_days": 180, "audit_emitted": True,
    }
    d.update(kw)
    return d


def run():
    checks = []

    def ok(name, cond):
        checks.append((bool(cond), name))

    # R1 — determinizm + terminal + kanıt + default-REJECT
    r1 = P.build(rtreq(), SPEC)
    r2 = P.build(rtreq(), SPEC)
    ok("R1 determinizm (birebir)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    ok("R1 terminal COMMIT/REJECT", r1["terminal"] in P.TERMINAL)
    ok("R1 kanıt tam", all(k in r1["evidence"] for k in
                          ("request_id", "op", "actor_realm", "plane", "category", "model_hash")))
    ok("R1 default REJECT (malformed)", P.build(lreq(op="bogus"), SPEC)["terminal"] == "REJECT")
    ok("R1 model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # R2 — tenant izolasyonu (L1-only + kendi tenant self-row; FR-TEN-002)
    rct = P.build(lreq(), SPEC, inject=["cross_tenant"])
    ok("R2 cross_tenant → cross_tenant_op>0 + kapı eler",
       rct["violations"]["cross_tenant_op"] > 0 and P._gate_eval(rct, G)[0] is False)
    rwr = P.build(lreq(), SPEC, inject=["wrong_realm"])
    ok("R2 wrong_realm (platform L0) → cross_tenant_op>0 + kapı eler",
       rwr["violations"]["cross_tenant_op"] > 0 and P._gate_eval(rwr, G)[0] is False)
    ok("R2 cross-tenant DOĞRU REJECT (ihlal yok)",
       P.build(lreq(target_tenant_id="t-999"), SPEC)["terminal"] == "REJECT"
       and P.build(lreq(target_tenant_id="t-999"), SPEC)["violations"]["cross_tenant_op"] == 0)
    ok("R2 platform realm DOĞRU REJECT (ihlal yok)",
       P.build(lreq(actor_realm="platform", plane="platform_control_plane"), SPEC)["terminal"] == "REJECT")

    # R3 — yetkilendirme (kategori → compliance:manage/retention:manage)
    rdp = P.build(lreq(), SPEC, inject=["drop_permission"])
    ok("R3 drop_permission → unauthorized_op>0 + kapı eler",
       rdp["violations"]["unauthorized_op"] > 0 and P._gate_eval(rdp, G)[0] is False)
    ok("R3 yetkisiz DOĞRU REJECT (ihlal yok)",
       P.build(lreq(actor_permissions=[]), SPEC)["terminal"] == "REJECT"
       and P.build(lreq(actor_permissions=[]), SPEC)["violations"]["unauthorized_op"] == 0)
    ok("R3 retention yanlış key (compliance:manage) DOĞRU REJECT",
       P.build(rtreq(actor_permissions=["compliance:manage"]), SPEC)["terminal"] == "REJECT")
    ok("R3 retention doğru key (retention:manage) COMMIT",
       P.build(rtreq(), SPEC)["terminal"] == "COMMIT")

    # R4 — tercih geçerliliği (kategori + değer)
    riv = P.build(lreq(), SPEC, inject=["invalid_value"])
    ok("R4 invalid_value → invalid_preference>0 + kapı eler",
       riv["violations"]["invalid_preference"] > 0 and P._gate_eval(riv, G)[0] is False)
    for c, v in (("locale", "en-GB"), ("timezone", "Asia/Dubai")):
        ok("R4 geçerli %s COMMIT" % c, P.build(lreq(category=c, value=v), SPEC)["terminal"] == "COMMIT")
    ok("R4 geçersiz locale DOĞRU REJECT (ihlal yok)",
       P.build(lreq(value="zz-ZZ"), SPEC)["terminal"] == "REJECT"
       and P.build(lreq(value="zz-ZZ"), SPEC)["violations"]["invalid_preference"] == 0)
    ok("R4 geçersiz timezone DOĞRU REJECT",
       P.build(lreq(category="timezone", value="Nowhere/City"), SPEC)["terminal"] == "REJECT")
    ok("R4 geçersiz data_class DOĞRU REJECT",
       P.build(rtreq(data_class="screenshots"), SPEC)["terminal"] == "REJECT")
    ok("R4 retain_days ≤0 DOĞRU REJECT",
       P.build(rtreq(value=0, compliance_min_days=0), SPEC)["terminal"] == "REJECT")

    # R5 — residency (home_region tenant izinli; NFR 10.7; narrowing-only)
    rrd = P.build(rreq(), SPEC, inject=["residency_drift"])
    ok("R5 residency_drift → residency_violation>0 + kapı eler",
       rrd["violations"]["residency_violation"] > 0 and P._gate_eval(rrd, G)[0] is False)
    ok("R5 tenant izinli dışı region DOĞRU REJECT (ihlal yok)",
       P.build(rreq(value="NA", tenant_allowed_regions=["EU", "UK"]), SPEC)["terminal"] == "REJECT"
       and P.build(rreq(value="NA", tenant_allowed_regions=["EU", "UK"]), SPEC)["violations"]["residency_violation"] == 0)
    ok("R5 izinli region COMMIT", P.build(rreq(value="UK"), SPEC)["terminal"] == "COMMIT")

    # R6 — retention tabanı (retain_days ≥ compliance asgari; DPIA §8 tenant override yalnız sıkılaştırır)
    rrl = P.build(rtreq(), SPEC, inject=["retention_loosen"])
    ok("R6 retention_loosen → retention_violation>0 + kapı eler",
       rrl["violations"]["retention_violation"] > 0 and P._gate_eval(rrl, G)[0] is False)
    ok("R6 compliance asgari altı DOĞRU REJECT (ihlal yok)",
       P.build(rtreq(value=90, compliance_min_days=180), SPEC)["terminal"] == "REJECT"
       and P.build(rtreq(value=90, compliance_min_days=180), SPEC)["violations"]["retention_violation"] == 0)
    ok("R6 asgariye eşit (sınır) COMMIT", P.build(rtreq(value=180, compliance_min_days=180), SPEC)["terminal"] == "COMMIT")

    # R7 — değişim koruması (residency değişimi / retention kısaltma → confirm)
    ruc = P.build(rreq(value="UK", current_region="EU"), SPEC, inject=["unsafe_change"])
    ok("R7 unsafe_change → unsafe_change>0 + kapı eler",
       ruc["violations"]["unsafe_change"] > 0 and P._gate_eval(ruc, G)[0] is False)
    ok("R7 confirm'siz residency değişim DOĞRU REJECT",
       P.build(rreq(value="UK", current_region="EU", confirm=False), SPEC)["terminal"] == "REJECT")
    ok("R7 confirm'siz retention kısaltma DOĞRU REJECT",
       P.build(rtreq(value=200, current_retain_days=365, confirm=False), SPEC)["terminal"] == "REJECT")
    ok("R7 confirm'li residency değişim COMMIT",
       P.build(rreq(value="UK", current_region="EU", confirm=True), SPEC)["terminal"] == "COMMIT")
    ok("R7 confirm'li retention kısaltma COMMIT",
       P.build(rtreq(value=200, current_retain_days=365, confirm=True), SPEC)["terminal"] == "COMMIT")
    ok("R7 retention ARTIRMA confirm gerektirmez COMMIT",
       P.build(rtreq(value=400, current_retain_days=365), SPEC)["terminal"] == "COMMIT")
    ok("R7 aynı residency (değişim yok) confirm gerektirmez COMMIT",
       P.build(rreq(value="EU", current_region="EU"), SPEC)["terminal"] == "COMMIT")

    # R8 — WORM audit (her mutasyon)
    rsa = P.build(lreq(), SPEC, inject=["skip_audit"])
    ok("R8 skip_audit → missing_audit>0 + kapı eler",
       rsa["violations"]["missing_audit"] > 0 and P._gate_eval(rsa, G)[0] is False)
    ok("R8 read mutasyon değil (audit'siz read COMMIT)",
       P.build(lreq(op="read", value=None, audit_emitted=False), SPEC)["terminal"] == "COMMIT")

    # R9 — model bütünlük manifesti
    rmt = P.build(lreq(), SPEC, inject=["model_tamper"])
    ok("R9 model_tamper → model_tampered>0 + kapı eler",
       rmt["violations"]["model_tampered"] > 0 and P._gate_eval(rmt, G)[0] is False)

    # R10/R11 — kardinalite + sızıntı yok
    ok("R11 evidence ham PII yok",
       all(k not in json.dumps(r1) for k in ("customer_name_value", "transcript_text_value", "connection_string_value")))
    ok("R11 leak: op/category/realm/locale/region/slug temiz",
       P.scan_leaks('{"op":"set","category":"residency","actor_realm":"tenant","value":"EU","tenant_id":"t-001","data_class":"recording"}') == [])
    ok("R11 leak: connection_string_value yakalanır", len(P.scan_leaks('{"connection_string_value": "x"}')) > 0)

    npass = sum(1 for ok_, _ in checks if ok_)
    for ok_, name in checks:
        print(("  ✓ " if ok_ else "  ✗ ") + name)
    print("\nbehavior test: %d/%d %s" % (npass, len(checks), "🟢" if npass == len(checks) else "🔴"))
    return 0 if npass == len(checks) else 1


if __name__ == "__main__":
    sys.exit(run())
