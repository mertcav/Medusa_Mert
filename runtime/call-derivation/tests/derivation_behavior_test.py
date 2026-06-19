#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
derivation_behavior_test.py — WBS 14.2.2 çıkarım motoru davranış kapısı (T1–T11).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: CallDerivationEngine'in FR-ANA-002 %100 kapsam +
deterministik kapalı-sözlük çıkarımı (intent/outcome/disposition/completion_status) + cross-field
tutarlılık + idempotency + PII redaksiyon + tenant izolasyon + uygunluk disiplinini gerçek çağrı
senaryolarında uyguladığını doğrular. stdlib-only, credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import derivation_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "batch_interval_s": 30}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(calls, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.derive_calls({"calls": calls}, SPEC, PROF, CTX, p)


C = lambda cid, **f: {"call_id": cid, "status": "completed", "features": f}

# T1 — kapsam %100: her uygun (completed) çağrı çıkarılır (FR-ANA-002/SR-ANA-002)
m = run([C("a", intent_signal="billing", resolved=True, flow_completed=True),
         C("b", intent_signal="sales", transferred=True),
         {"call_id": "c", "status": "test_call", "reason": "test_call"}])
check(m["derived"]["eligible"] == 2 and m["derived"]["produced"] == 2, "T1 2 uygun → 2 çıkarım (%100)")
check(m["coverage_gap"] == 0 and m["derived"]["coverage_ratio"] == 1.0, "T1 coverage_gap=0, ratio=1.0")

# T2 — DÖRT alan her satırda dolu (intent/outcome/disposition/completion_status)
for r in m["derivations"]:
    check(all(r.get(f) is not None for f in ("intent", "outcome", "disposition", "completion_status")),
          "T2 %s DÖRT alan dolu" % r["call_id"])

# T3 — degraded çağrı atlanmaz: sinyal yok ama yine çıkarılır (sentinel)
m3 = run([C("d")])
d = m3["derivations"][0]
check(m3["produced"] == 1 and m3["derived"]["degraded"] == 1, "T3 sinyal yok → degraded ama üretilir (atlanmaz)")
check(d["intent"] == "unknown" and d["outcome"] == "unresolved" and d["disposition"] == "no_action"
      and d["completion_status"] == "partial", "T3 sentinel'ler (unknown/unresolved/no_action/partial)")
check(m3["coverage_gap"] == 0, "T3 degraded çağrı kapsam açığı yaratmaz")

# T4 — outcome öncelik: not_connected > abandoned > transferred > contained > unresolved
check(run([C("x", not_connected_reason="busy", transferred=True)])["derivations"][0]["outcome"] == "not_connected",
      "T4 not_connected_reason en yüksek öncelik (outbound)")
check(run([C("x", caller_abandoned=True, transferred=True)])["derivations"][0]["outcome"] == "abandoned",
      "T4 caller_abandoned transferred'ten önce")
check(run([C("x", resolved=True)])["derivations"][0]["outcome"] == "contained",
      "T4 resolved → contained (containment kaynağı, 14.2.3)")

# T5 — kapalı-sözlük: tüm değerler vocab'da (G3); vocab-dışı intent_signal → unknown
m5 = run([C("v", intent_signal="this_is_not_a_known_intent", resolved=True, flow_completed=True)])
check(m5["derivations"][0]["intent"] == "unknown" and m5["vocab_violations"] == 0,
      "T5 vocab-dışı intent → unknown sentinel (kapalı-sözlük korunur)")

# T6 — cross-field tutarlılık (C1–C5): aktarım tuple'ı içsel-tutarlı
m6 = run([C("t", intent_signal="billing", transferred=True)])
t = m6["derivations"][0]
check(t["outcome"] == "transferred_to_human" and t["completion_status"] == "transferred"
      and t["disposition"] == "escalated" and m6["consistency_violations"] == 0,
      "T6 transferred → tutarlı tuple (C1/C5), 0 ihlal")
# enforce_consistency kapalı → desenkronize
m6b = run([C("t2", intent_signal="billing", transferred=True, flow_completed=True)], enforce_consistency=False)
check(m6b["consistency_violations"] >= 1, "T6 enforce_consistency kapalı → completion desenkronize → ihlal")

# T7 — idempotency: replay (aynı call_id) daraltılır
dup = [C("x", intent_signal="billing", resolved=True, flow_completed=True),
       C("x", intent_signal="billing", resolved=True, flow_completed=True)]
m7 = run(dup)
check(m7["produced"] == 1 and m7["idempotency_violations"] == 0, "T7 replay daraltılır (1 çıkarım)")
check(run(dup, idempotent=False)["idempotency_violations"] >= 1, "T7 idempotent kapalı → çift çıkarım tespit edilir")

# T8 — PII redaksiyon: ham transkript sinyali reddedilir
m8 = run([C("y", transcript_text="ham", resolved=True, flow_completed=True)])
check(m8["pii_violations"] >= 1, "T8 transcript_text yasak sinyal → PII ihlali")

# T9 — tenant izolasyon: cross-tenant + tenant_id eksikliği
m9 = run([{"call_id": "z", "status": "completed", "tenant_id": "t_other",
           "features": {"intent_signal": "billing", "resolved": True, "flow_completed": True}}])
check(m9["isolation_violations"] >= 1, "T9 cross-tenant çağrı → izolasyon ihlali")
check(run([C("z2", intent_signal="billing", resolved=True)], isolate_tenant=False)["isolation_violations"] >= 1,
      "T9 tenant_id yok → izolasyon ihlali")

# T10 — uygunluk: uygun-olmayan statü reason taşımalı; bilinmeyen statü reddedilir
check(run([{"call_id": "ab", "status": "abandoned_pre_connect"}])["eligibility_reason_missing"] >= 1,
      "T10 reason'sız uygun-olmayan statü → uygunluk ihlali")
try:
    run([{"call_id": "u", "status": "martian"}])
    check(False, "T10 bilinmeyen statü reddedilmeli")
except P.DerivationError:
    check(True, "T10 bilinmeyen statü → reddedilir (INVALID_REQUEST)")

# T11 — determinizm + non-blocking
check(run([C("k", intent_signal="payment", resolved=True)]) == run([C("k", intent_signal="payment", resolved=True)]),
      "T11 determinizm: aynı çağrı aynı sonuç (random yok)")
check(run([C("k", intent_signal="payment", resolved=True)], non_blocking=False)["blocking_violations"] >= 1,
      "T11 non_blocking kapalı → blocking ihlali (FR-RES-011)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
