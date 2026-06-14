#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
summarization_behavior_test.py — WBS 3.2.2 davranış kapısı (T1–T8)

Deterministik Summarization Engine'in (summarization_probe.SummarizationEngine) token-sınırı
özetleme davranışını HARD kapılara (S1–S8) karşı doğrular. Sunucu/credential GEREKMEZ; stdlib-only.
3.2.1 (session_memory_behavior_test) + 3.1.4 (resource_budget_behavior_test) disipliniyle aynı.

Koş: python3 tests/summarization_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import summarization_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

# Sıkı parametreler (kapıları kolay tetiklemek için): budget 1000, cap 200
PARAMS = dict(P.DEFAULT_PARAMS)

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


def long_call(n, tok=200, sal=1, **turn_kw):
    ev = [P._turn(i * 100, "t%d" % i, "caller" if i % 2 == 0 else "agent", tokens=tok, salient=sal)
          for i in range(n)]
    ev.append(P._end(n * 100 + 100))
    return ev


print("T1 — under-budget: tavan altında özetleme YOK (S1)")
m = P._run([P._turn(0, "u1", tokens=200), P._turn(1000, "a1", "agent", tokens=200),
            P._turn(2000, "u2", tokens=200), P._end(3000)], PARAMS)
check(m["summarize_ops"] == 0, "300 tok ≤ 1000 → summarize_ops=0")
check(m["spurious_summarize"] == 0, "spurious_summarize=0")
check(gates_pass(m), "tüm kapılar geçer")

print("T2 — token-triggered: tavan aşılır → tetik + history ≤ tavan (S1/S2)")
m = P._run(long_call(12), PARAMS)
check(m["summarize_ops"] >= 1 and m["folded_turns"] >= 1, "özetleme tetiklendi")
check(m["history_tokens_final"] <= PARAMS["history_token_budget"], "history ≤ tavan (S2/FR-RES-010)")
check(m["budget_exceeded_after"] == 0, "budget_exceeded_after=0")
check(m["tokens_saved"] > 0, "token tasarrufu > 0 (FR-RES-010 kanıtı)")
check(gates_pass(m), "tüm kapılar geçer")

print("T3 — bounded rolling summary: özet ≤ cap (re-compress) (S3)")
m = P._run(long_call(40), PARAMS)
check(m["peak_summary_tokens"] <= PARAMS["summary_token_cap"], "peak özet ≤ cap 200")
check(m["summary_overflow"] == 0, "summary_overflow=0")
check(m["recompress_events"] >= 1, "re-compress tetiklendi (yuvarlanan özet)")
check(gates_pass(m), "tüm kapılar geçer")

print("T4 — coverage: özet ≠ kırpma, bilgi korunur (S4)")
m = P._run(long_call(12), PARAMS)
check(m["uncovered_fold"] == 0, "katlanan her turn özete girer (uncovered=0)")
check(m["summarized_turns"] == m["folded_turns"], "summarized == folded")
check(m["coverage"] >= GATES.get("coverage_floor", 0.9), "coverage ≥ floor (bağlam korunur)")

print("T5 — truncate degrade: kırpma bilgi kaybeder (S4 eler)")
m = P._run(long_call(12), PARAMS, truncate_instead=True)
check(m["uncovered_fold"] >= 1, "katlanan turn özete girmez (uncovered>0)")
check(m["coverage"] < GATES.get("coverage_floor", 0.9), "coverage < floor (kayıp)")
check(not gates_pass(m), "S4 eler")

print("T6 — latency off-path: özetleme turu bloklamaz (S5)")
m = P._run(long_call(12), PARAMS)
check(m["blocking_summarize"] == 0 and m["turn_latency_added"] == 0, "blocking=0 (asenkron)")
check(m["summarize_latency_max"] <= GATES.get("summarize_latency_budget_ms", 200), "gecikme ≤ budget (küçük tier)")
m2 = P._run(long_call(12), PARAMS, blocks_turn=True)
check(m2["blocking_summarize"] >= 1 and not gates_pass(m2), "blocks_turn=true → S5 eler")

print("T7 — redaction + sensitive: kart/OTP özete düz-metin GİRMEZ (S8)")
sev = [P._turn(i * 100, "s%d" % i, "caller", tokens=200, sensitive=(2 if i == 0 else 0)) for i in range(12)]
sev.append(P._end(2000))
m = P._run(sev, PARAMS)
check(m["sensitive_seen"] == 2 and m["sensitive_cleartext_summarized"] == 0, "sensitive görüldü, özete düz-metin=0")
check(m["redaction_state"] == "pending", "durable redaction_state=pending (FR-REC-004)")
m2 = P._run(sev, PARAMS, strip_card_otp=False)
check(m2["sensitive_cleartext_summarized"] >= 1 and not gates_pass(m2), "strip kapalı → S8 eler")

print("T8 — determinizm + reddetme (S6/S10)")
check(P._run(long_call(40), PARAMS) == P._run(long_call(40), PARAMS), "aynı akış → birebir aynı metrik")
check(P._raises(lambda: P._run([P._turn(0, "u1", speaker="x"), P._end(1)], PARAMS)), "geçersiz speaker → reddedilir")
check(P._raises(lambda: P._run([P._turn(0, "u1", tokens=10)], PARAMS)), "'end' yok → reddedilir")
check(P._raises(lambda: P._run([P._turn(1000, "u1"), P._turn(0, "u2"), P._end(2)], PARAMS)), "out-of-order → reddedilir")
check(P._raises(lambda: P._run([P._turn(0, "u1"), P._turn(100, "x1", tenant="t-other"), P._end(2)], PARAMS)),
      "cross-tenant (izolasyon açık) → reddedilir")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nsummarization_behavior_test: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
