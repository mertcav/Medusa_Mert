#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WBS 7.3.1 — Kritik işlem workflow durum makinesi davranış testi (BRD §13).

Probe'un FSM davranışını bağımsız olarak doğrular (T1–T16). Stdlib-only, credential-free,
deterministik. probe selftest ile örtüşür ama AYRI bir kapı yüzeyidir (regresyon ağı).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import critical_workflow_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
POL = P._load(P.CONFIG_PATH)

_results = []


def chk(name, cond):
    _results.append((bool(cond), name))


def auth(level="strong", methods=None, step_up=True, at_ms=0):
    return {"type": "auth", "level": level, "methods": methods or ["otp"], "step_up": step_up, "at_ms": at_ms}


def req(risk_class, events, **over):
    r = {"workflow_id": "w", "correlation_id": "c", "tenant_id": "t", "call_id": "cl",
         "initiator": "agent",
         "operation": {"name": "op", "risk_class": risk_class, "critical": True, "params": over.pop("params", {})},
         "events": events}
    r.update(over)
    return r


def run(risk_class, events, **over):
    return P.run_workflow(SPEC, POL, req(risk_class, events, **over))


# T1 — BRD §13 6-adım sırası mutlu yolda eksiksiz işler → COMMITTED
r = run("bank_account_change", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                {"type": "execute", "outcome": "ok", "at_ms": 2000}])
sv = dict(r["step_verdicts"])
chk("T1 mutlu yol COMMITTED", r["final_state"] == "COMMITTED")
chk("T1 sıra auth→rule→summary→confirm→execute→audit hepsi pass",
    all(sv.get(s) == "pass" for s in ("AUTH", "RULE", "SUMMARY", "CONFIRM", "EXECUTE", "AUDIT")))

# T2 — auth atlanamaz: yetersiz auth EXECUTE'a ulaşamaz (K1/K2)
r = run("bank_account_change", [auth(level="basic"), {"type": "confirm", "value": "yes", "at_ms": 1},
                                {"type": "execute", "outcome": "ok", "at_ms": 2}])
chk("T2 yetersiz auth → DENIED", r["final_state"] == "DENIED")
chk("T2 red → EXECUTE çalışmadı", "EXECUTE" not in dict(r["step_verdicts"]))

# T3 — caller_id tek başına güçlü değil (FR-AUTH-001)
r = run("bank_account_change", [auth(level="strong", methods=["caller_id"])])
chk("T3 caller_id-only → DENIED AUTH_INSUFFICIENT", r["final_state"] == "DENIED" and r["reason"] == "AUTH_INSUFFICIENT")

# T4 — step-up zorunluluğu (FR-TOOL-007/K7)
r = run("contact_info_change", [auth(step_up=False)])
chk("T4 step_up yok → DENIED STEP_UP_REQUIRED", r["reason"] == "STEP_UP_REQUIRED")

# T5 — teyit alınmadan yürütülmez (SR-TOOL-006/K5)
r = run("bank_account_change", [auth(), {"type": "confirm", "value": "no", "at_ms": 1000},
                                {"type": "execute", "outcome": "ok", "at_ms": 2000}])
chk("T5 teyit no → ABORTED", r["final_state"] == "ABORTED" and r["reason"] == "CUSTOMER_DECLINED")
chk("T5 abort → execute yok", "EXECUTE" not in dict(r["step_verdicts"]))

# T6 — teyit eksik → ABORTED (fail-closed)
r = run("bank_account_change", [auth()])
chk("T6 teyit yok → ABORTED NOT_OBTAINED", r["reason"] == "CONFIRMATION_NOT_OBTAINED")

# T7 — maker-checker: farklı aktör onayı → COMMITTED (FR-IAM-005/K6)
r = run("contract_cancellation", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                  {"type": "approval", "decision": "approved", "actor": "sup-1", "at_ms": 2000},
                                  {"type": "execute", "outcome": "ok", "at_ms": 3000}])
chk("T7 maker-checker onaylı → COMMITTED", r["final_state"] == "COMMITTED" and r["approver"] == "sup-1")

# T8 — aynı aktör onayı reddedilir (K6)
r = run("contract_cancellation", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                  {"type": "approval", "decision": "approved", "actor": "agent", "at_ms": 2000}],
        initiator="agent")
chk("T8 aynı aktör → MAKER_CHECKER_VIOLATION", r["reason"] == "MAKER_CHECKER_VIOLATION")

# T9 — onay reddi → DENIED
r = run("contract_cancellation", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                  {"type": "approval", "decision": "rejected", "actor": "sup-1", "at_ms": 2000}])
chk("T9 onay reddi → DENIED APPROVAL_REJECTED", r["reason"] == "APPROVAL_REJECTED")

# T10 — forbidden_autonomous → insan onayı zorlanır (BRD §13/K3)
r = run("legal_advice", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000}])
chk("T10 forbidden → onay zorlanır", r["requirements"]["requires_human_approval"] is True)
chk("T10 forbidden onaysız → DENIED", r["reason"] == "APPROVAL_REQUIRED")

# T11 — bilinmeyen risk_class fail-closed (K3)
r = run("nonexistent_class", [auth()])
chk("T11 bilinmeyen risk_class → DENIED UNKNOWN_RISK_CLASS", r["reason"] == "UNKNOWN_RISK_CLASS")

# T12 — tutar eşiği eskalasyonu (K3)
r_hi = run("high_value_payment", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000}],
           params={"amount": 99999, "currency": "TRY"})
r_lo = run("high_value_payment", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                  {"type": "execute", "outcome": "ok", "at_ms": 2000}],
           params={"amount": 100, "currency": "TRY"})
chk("T12 eşik üstü → onay zorlanır → DENIED", r_hi["reason"] == "APPROVAL_REQUIRED")
chk("T12 eşik altı → COMMITTED", r_lo["final_state"] == "COMMITTED")

# T13 — deadline → EXPIRED, zombie yok (K9)
r = run("contract_cancellation", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                  {"type": "approval", "decision": "approved", "actor": "sup-1", "at_ms": 999999}],
        deadline_ms=120000)
chk("T13 deadline → EXPIRED", r["final_state"] == "EXPIRED")
chk("T13 EXPIRED → execute yok", "EXECUTE" not in dict(r["step_verdicts"]))

# T14 — execute fault → FAILED + audit (K10)
r = run("bank_account_change", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                {"type": "execute", "outcome": "fault", "fault_class": "TIMEOUT", "at_ms": 2000}])
chk("T14 execute fault → FAILED", r["final_state"] == "FAILED" and r["reason"] == "TIMEOUT")
chk("T14 FAILED → audit yazıldı", dict(r["step_verdicts"]).get("AUDIT") == "pass")

# T15 — özet maskeleme (FR-AUTH-005/K11): ham kimlik dizisi özette yok
r = run("bank_account_change", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1000},
                                {"type": "execute", "outcome": "ok", "at_ms": 2000}],
        params={"masked": {"iban": "TR330006100519786457841326"}})
chk("T15 özet ham kimlik içermez", not P._scan(r["summary_text"], P.PII_PATTERNS))
chk("T15 audit no-log temiz", not P._scan(json.dumps(r["audit"], ensure_ascii=False), P.PII_PATTERNS))

# T16 — her terminal sonuç audit üretir (K10) + terminal-immutable (K8)
for rc, evs, exp in [
    ("bank_account_change", [auth(), {"type": "confirm", "value": "yes", "at_ms": 1},
                             {"type": "execute", "outcome": "ok", "at_ms": 2}], "COMMITTED"),
    ("bank_account_change", [auth(level="none")], "DENIED"),
    ("bank_account_change", [auth(), {"type": "confirm", "value": "no", "at_ms": 1}], "ABORTED"),
]:
    rr = run(rc, evs)
    chk("T16 %s → audit pass" % exp, rr["final_state"] == exp and dict(rr["step_verdicts"]).get("AUDIT") == "pass")
# K8: ABORTED sonrası kalan execute olayı yok sayılır
rr = run("bank_account_change", [auth(), {"type": "confirm", "value": "no", "at_ms": 1},
                                 {"type": "execute", "outcome": "ok", "at_ms": 2}])
chk("T16 K8 terminal-immutable (abort sonrası execute yok)", "EXECUTE" not in dict(rr["step_verdicts"]))


npass = sum(1 for ok, _ in _results if ok)
for ok, name in _results:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("behavior: %d/%d %s" % (npass, len(_results), "🟢" if npass == len(_results) else "🔴"))
sys.exit(0 if npass == len(_results) else 1)
