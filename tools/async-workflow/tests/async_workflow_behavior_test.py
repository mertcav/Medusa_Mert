#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.2.4 — Asenkron uzun-işlem workflow davranış testi (FR-TOOL-011 / SR-TOOL-011).

Probe selftest'inden AYRI kara-kutu davranış sözleşmeleri: non-blocking dispatch, callback HMAC
authenticity (imza/timestamp/nonce), bounded polling, deadline reaper, callback∧poll exactly-once,
tenant+correlation binding, result-by-reference, idempotency-key dedup, audit no-log.
Stdlib-only; gerçek ağ/credential/PII YOK (FR-TST-008).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import async_workflow_probe as AW  # noqa: E402

FAILS = []
N = 0


def check(cond, msg):
    global N
    N += 1
    if not cond:
        FAILS.append(msg)


def engine(mode="hybrid", **over):
    return AW.AsyncWorkflowEngine(AW._spec(mode=mode, **over))


def disp(e, **over):
    return e.dispatch(AW._disp_req(**over))


def cb(e, **over):
    return AW._cb(e, **over)


# T1 — W1: dispatch non-blocking; turn beklemez
e = engine()
d = disp(e)
check(d["non_blocking"] is True, "T1 dispatch non_blocking")
check(d["status"] == "PENDING", "T1 dispatch PENDING (sonuç beklenmez)")
check(e.executions["ex-1"]["status"] == "PENDING", "T1 execution PENDING kaydı")

# T2 — W4: geçerli imzalı callback → SUCCEEDED
e = engine()
disp(e)
r = e.ingest_callback(cb(e, at_ms=1000, ts=1, nonce="t2"))
check(r["result"] == "accepted" and r["completed"] is True, "T2 geçerli callback accepted")
check(e.executions["ex-1"]["status"] == "SUCCEEDED", "T2 SUCCEEDED")

# T3 — W4: eksik imza → MISSING_SIGNATURE
e = engine()
disp(e)
bad = {"execution_id": "ex-1", "tenant_id": "t-1", "correlation_id": "corr-1",
       "status": "SUCCEEDED", "body": "{}", "ts": 1, "nonce": "t3", "at_ms": 1000}  # sig yok
r = e.ingest_callback(bad)
check(r["reject_reason"] == "MISSING_SIGNATURE", "T3 imzasız callback reddi")
check(e.executions["ex-1"]["status"] == "PENDING", "T3 imzasız → PENDING korunur")

# T4 — W4: kötü imza → BAD_SIGNATURE
e = engine()
disp(e)
c = cb(e, at_ms=1000, ts=1, nonce="t4")
c["sig"] = "deadbeef"
r = e.ingest_callback(c)
check(r["reject_reason"] == "BAD_SIGNATURE" and r["fault_class"] == "CALLBACK_REJECTED", "T4 kötü imza reddi")

# T5 — W4: timestamp penceresi dışı → TIMESTAMP_OUT_OF_WINDOW
e = engine()
disp(e)
r = e.ingest_callback(cb(e, at_ms=1000000, ts=0, nonce="t5"))  # 1000s vs 0 > 300
check(r["reject_reason"] == "TIMESTAMP_OUT_OF_WINDOW", "T5 timestamp penceresi reddi")

# T6 — W4: nonce replay → ikinci NONCE_REPLAYED, emit 1
e = engine()
disp(e)
e.ingest_callback(cb(e, at_ms=1000, ts=1, nonce="dup"))
r = e.ingest_callback(cb(e, at_ms=1100, ts=1, nonce="dup"))
check(r["reject_reason"] == "NONCE_REPLAYED", "T6 nonce replay reddi")
check(len([x for x in e.emitted if x["execution_id"] == "ex-1"]) == 1, "T6 replay sonrası tek emit")

# T7 — W7: cross-tenant + correlation mismatch
e = engine()
disp(e)
check(e.ingest_callback(cb(e, at_ms=1000, ts=1, tenant_id="other", nonce="t7a"))["reject_reason"] == "TENANT_MISMATCH",
      "T7 tenant mismatch")
check(e.ingest_callback(cb(e, at_ms=1000, ts=1, correlation_id="other", nonce="t7b"))["reject_reason"] == "CORRELATION_MISMATCH",
      "T7 correlation mismatch")

# T8 — W7: bilinmeyen execution
e = engine()
disp(e)
check(e.ingest_callback(cb(e, at_ms=1000, ts=1, execution_id="nope", nonce="t8"))["reject_reason"] == "UNKNOWN_EXECUTION",
      "T8 bilinmeyen execution reddi")

# T9 — W5: bounded poll → TIMED_OUT (attempt tükenmesi; deadline çok büyük)
e = engine(mode="polling")
e.dispatch(AW._disp_req(deadline_ms=10**9))
t = 0
for _ in range(10):
    t += 20000
    e.poll_step(t, {"status": "RUNNING"})
    if e.executions["ex-1"]["status"] in AW.TERMINAL_STATES:
        break
check(e.executions["ex-1"]["status"] == "TIMED_OUT", "T9 bounded poll → TIMED_OUT")
check(e.executions["ex-1"]["attempts"] == 4, "T9 max_attempts=4 sonra durur (unbounded değil)")

# T10 — W5: poll success
e = engine(mode="polling")
disp(e)
e.poll_step(20000, {"status": "RUNNING"})
r = e.poll_step(40000, {"status": "SUCCEEDED", "result_ref": "objref://t-1/ex-1/r"})
check(r["result"] == "terminal" and e.executions["ex-1"]["status"] == "SUCCEEDED", "T10 poll success")

# T11 — W6: deadline reaper (poll terminal vermez ama deadline aşılır)
e = engine(mode="polling", poll={"max_attempts": 100, "base_backoff_ms": 1000, "max_backoff_ms": 2000, "jitter_ms": 0})
e.dispatch(AW._disp_req(deadline_ms=5000))
r = e.poll_step(6000, {"status": "RUNNING"})
check(r["result"] == "timed_out" and e.executions["ex-1"]["status"] == "TIMED_OUT", "T11 deadline reaper")

# T12 — W3: poll terminal sonra callback → idempotent no-op, emit 1
e = engine(mode="hybrid")
disp(e)
e.poll_step(20000, {"status": "SUCCEEDED", "result_ref": "objref://t-1/ex-1/p"})
r = e.ingest_callback(cb(e, at_ms=30000, ts=30, nonce="t12"))
check(r["completed"] is False, "T12 poll-sonrası callback no-op")
check(len([x for x in e.emitted if x["execution_id"] == "ex-1"]) == 1, "T12 race → tek emit")

# T13 — W8: emitted yalnız result_ref; ham payload yok
e = engine()
disp(e)
e.ingest_callback(cb(e, at_ms=1000, ts=1, nonce="t13"))
em = e.emitted[0]
check(em["type"] == "tool.async.completed" and "result_ref" in em, "T13 tool.async.completed result_ref")
check(all(k not in em for k in ("result", "payload", "body", "pii")), "T13 emitted'da ham payload yok")

# T14 — W9: idempotency dedup → tek execution
e = engine()
e.dispatch(AW._disp_req(execution_id="A", idempotency_key="k1"))
d2 = e.dispatch(AW._disp_req(execution_id="B", idempotency_key="k1", at_ms=10))
check(d2["deduped"] is True and d2["execution_id"] == "A", "T14 idempotency dedup aynı execution")
check(len(e.executions) == 1, "T14 iki upstream iş YOK")

# T15 — W2: terminal dispatch fault → FAILED + emit 1
e = engine()
d = e.dispatch(AW._disp_req(dispatch={"result": "fault", "fault_class": "AUTH_FAILED"}))
check(d["status"] == "FAILED" and d["accepted"] is False, "T15 terminal dispatch fault FAILED")
check(len([x for x in e.emitted if x["execution_id"] == "ex-1"]) == 1, "T15 FAILED de exactly-once emit")

# T16 — W11: audit no-log + secret/PII yok
e = engine()
disp(e)
e.ingest_callback(cb(e, at_ms=1000, ts=1, nonce="t16"))
import json as _json
blob = _json.dumps(e.audit) + _json.dumps(e.emitted)
check(all(a.get("no_log") for a in e.audit), "T16 audit no_log işaretli")
check("chanteur-fixture-hmac-key" not in blob and "deadbeef" not in blob, "T16 imza/secret audit'te yok")

# T17 — W12: determinizm (tohumlu jitter)
def trace():
    eng = engine(mode="polling", poll={"max_attempts": 5, "base_backoff_ms": 1000, "max_backoff_ms": 8000, "jitter_ms": 50})
    eng.dispatch(AW._disp_req())
    out = []
    tt = 0
    for _ in range(5):
        tt += 20000
        out.append(eng.poll_step(tt, {"status": "RUNNING"}))
    return out
check(trace() == trace(), "T17 determinizm birebir")


print("behavior: %d kontrol, %d başarısız" % (N, len(FAILS)))
for m in FAILS:
    print("  ✗ %s" % m)
sys.exit(0 if not FAILS else 1)
