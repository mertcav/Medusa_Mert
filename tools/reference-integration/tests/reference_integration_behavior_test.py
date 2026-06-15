#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.5 — CRM/Ticketing/ERP referans entegrasyonu davranış testi (BRD §6.1 / SR-TOOL-001).

Probe selftest'inden AYRI, kara-kutu davranış sözleşmelerini doğrular: SAD §11.1 zincir [1]→[7]
sıralama + fail-closed kompozisyon, read/write authz seviye ayrımı, kritik-işlem policy gate,
write idempotency, allowlist, fault→müşteri kategorisi delegasyonu (teknik detay sızmaz),
Tool Execution kaydı, audit no-log, connector-tipi (REST/GraphQL/SOAP) read+write kapsama, determinizm.
Stdlib-only; gerçek ağ/credential/PII YOK (FR-TST-008).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import reference_integration_probe as RI  # noqa: E402

SPEC = RI._load(RI.SPEC_PATH)
FAILS = []
N = 0


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)


def inv(**over):
    base = {"call_id": "x", "correlation_id": "corr", "tenant_id": "t-1", "granted_scopes": [], "at_ms": 0}
    base.update(over)
    return RI.execute_chain(SPEC, base)


# T1 — zincir sırası + kısa-devre: schema fail → sonraki adımlar çalışmaz (R1)
r = inv(tool="crm.get_customer", schema_valid=False, granted_scopes=["crm:read"], allowlist="PERMIT",
        attempt={"result": "ok"})
sv = dict(r["audit"]["step_verdicts"])
check(r["status"] == "rejected" and r["fault_class"] == "SCHEMA_INVALID", "T1 schema fail → rejected")
check("authorization" not in sv and "dispatch" not in sv, "T1 kısa-devre: downstream adım çalışmaz")

# T2 — fail-closed: allowlist kararı yok → DENY (R1)
r = inv(tool="crm.get_customer", granted_scopes=["crm:read"], attempt={"result": "ok"})
check(r["status"] == "rejected" and r["fault_class"] == "ENDPOINT_NOT_ALLOWED", "T2 allowlist eksik → fail-closed rejected")

# T3 — read/write authz seviye ayrımı (R3): write tool read scope ile → AUTH_FAILED
r = inv(tool="crm.create_case", granted_scopes=["crm:read"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok"})
check(r["status"] == "rejected" and r["fault_class"] == "AUTH_FAILED", "T3 write+read-scope → AUTH_FAILED")
check("dispatch" not in dict(r["audit"]["step_verdicts"]), "T3 authz red → dispatch yok")

# T4 — kritik policy gate (R4): teyit/step-up varyantları
crit = dict(tool="crm.update_contact", granted_scopes=["crm:write:pii"], idempotency_key="k",
            allowlist="PERMIT", attempt={"result": "ok"})
check(inv(**crit, confirmation=False, step_up=False)["status"] == "blocked", "T4 kritik teyitsiz → blocked")
check(inv(**crit, confirmation=True, step_up=False)["status"] == "blocked", "T4 kritik step-up eksik → blocked")
check(inv(**crit, confirmation=False, step_up=True)["status"] == "blocked", "T4 kritik teyit eksik → blocked")
check(inv(**crit, confirmation=True, step_up=True)["status"] == "committed", "T4 kritik teyit+stepup → committed")

# T5 — non-kritik write teyit gerektirmez
r = inv(tool="crm.create_case", granted_scopes=["crm:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok"})
check(r["status"] == "committed" and not r["critical"], "T5 non-kritik write teyitsiz committed")

# T6 — write idempotency zorunlu (R5)
r = inv(tool="ticketing.add_comment", granted_scopes=["ticketing:write"], allowlist="PERMIT",
        attempt={"result": "ok"})
check(r["status"] == "rejected" and r["fault_class"] == "IDEMPOTENCY_REQUIRED", "T6 write key yok → rejected")
# read idempotency gerektirmez
r = inv(tool="ticketing.get_ticket", granted_scopes=["ticketing:read"], allowlist="PERMIT",
        attempt={"result": "ok"})
check(r["status"] == "succeeded", "T6 read key gerektirmez")

# T7 — allowlist DENY (R6)
r = inv(tool="erp.get_invoice", granted_scopes=["erp:read"], allowlist="DENY", attempt={"result": "ok"})
check(r["status"] == "rejected" and r["fault_class"] == "ENDPOINT_NOT_ALLOWED", "T7 allowlist DENY → rejected")
check(r["customer_category"] == "NOT_PERMITTED", "T7 DENY → müşteri NOT_PERMITTED")

# T8 — fault → müşteri kategorisi DELEGE (7.1.5 hizalı), her sınıf
cases = {"UPSTREAM_5XX": "TEMPORARY", "TIMEOUT": "TEMPORARY", "RATE_LIMITED": "BUSY",
         "UPSTREAM_4XX": "CANNOT_COMPLETE", "NOT_FOUND": "NOT_FOUND", "AUTH_FAILED": "NOT_PERMITTED"}
for fc, cat in cases.items():
    r = inv(tool="crm.get_customer", granted_scopes=["crm:read"], allowlist="PERMIT",
            attempt={"result": "fault", "fault_class": fc})
    check(r["status"] == "failed" and r["customer_category"] == cat, "T8 %s → %s" % (fc, cat))
    check(not (RI._scan(r["customer_message"], RI.LEAK_PATTERNS) + RI._scan(r["customer_message"], RI.PII_PATTERNS)),
          "T8 %s müşteri mesajı sızıntısız (R7)" % fc)

# T9 — Tool Execution kaydı yalnız committed write (R9)
r = inv(tool="crm.create_case", granted_scopes=["crm:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok"})
check(r["tool_execution_recorded"], "T9 committed write → tool_execution")
r = inv(tool="crm.get_customer", granted_scopes=["crm:read"], allowlist="PERMIT", attempt={"result": "ok"})
check(not r["tool_execution_recorded"], "T9 read başarısı → tool_execution YOK")
r = inv(tool="erp.create_appointment", granted_scopes=["erp:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "accepted"})
check(not r["tool_execution_recorded"] and r["status"] == "pending", "T9 async pending → committed kaydı yok")

# T10 — audit no-log: temiz audit'te PII/secret yok; düşük kardinalite (R8)
r = inv(tool="crm.create_case", granted_scopes=["crm:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok", "result_ref": "case://r"})
blob = json.dumps(r["audit"], ensure_ascii=False)
check(not RI._scan(blob, RI.PII_PATTERNS), "T10 temiz audit PII'siz")
check("status_code" not in r["audit"] and r["audit"]["idempotency_present"] is True, "T10 audit yalnız yapısal alanlar")

# T11 — connector-tipi (REST/GraphQL/SOAP) read+write başarılı çağrı (R2 / SR-TOOL-001)
coverage = {
    ("rest", "read"): ("crm.get_customer", ["crm:read"], None),
    ("rest", "write"): ("crm.create_case", ["crm:write"], "k"),
    ("graphql", "read"): ("ticketing.get_ticket", ["ticketing:read"], None),
    ("graphql", "write"): ("ticketing.create_ticket", ["ticketing:write"], "k"),
    ("soap", "read"): ("erp.get_order", ["erp:read"], None),
    ("soap", "write"): ("erp.create_appointment", ["erp:write"], "k"),
}
for (ct, oc), (tool, scopes, key) in coverage.items():
    kw = dict(tool=tool, granted_scopes=scopes, allowlist="PERMIT", attempt={"result": "ok"})
    if key:
        kw["idempotency_key"] = key
    r = inv(**kw)
    ok = r["connector_type"] == ct and r["operation_class"] == oc and r["status"] in ("succeeded", "committed")
    check(ok, "T11 %s/%s başarılı çağrı" % (ct, oc))

# T12 — determinizm (R10)
a = inv(tool="crm.create_case", granted_scopes=["crm:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok"})
b = inv(tool="crm.create_case", granted_scopes=["crm:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok"})
check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "T12 determinizm birebir")

# T13 — degraded sızıntı tarayıcısı (R7/R8 gerçek kapı)
r = inv(tool="crm.get_customer", granted_scopes=["crm:read"], allowlist="PERMIT",
        attempt={"result": "fault", "fault_class": "UPSTREAM_5XX"},
        unsafe_customer_message="Traceback 500 at crm.example.com")
check(bool(RI._scan(r["customer_message"], RI.LEAK_PATTERNS)), "T13 kirli müşteri mesajı yakalanır")
r = inv(tool="crm.create_case", granted_scopes=["crm:write"], idempotency_key="k", allowlist="PERMIT",
        attempt={"result": "ok"}, unsafe_audit_detail="user@example.com 4111111111111111")
check(bool(RI._scan(json.dumps(r["audit"], ensure_ascii=False), RI.PII_PATTERNS)), "T13 kirli audit yakalanır")

print("behavior: %d/%d %s" % (N - len(FAILS), N, "🟢" if not FAILS else "🔴"))
for f in FAILS:
    print("  ✗ %s" % f)
sys.exit(0 if not FAILS else 1)
