#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qa_eval_behavior_test.py — WBS 14.2.1 QA/Eval Engine davranış kapısı (T1–T10).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: QaEvalEngine'in FR-ANA-001 %100 kapsam +
deterministik skorkart + idempotency + skor-alanı + PII redaksiyon + tenant izolasyon +
uygunluk disiplinini gerçek çağrı senaryolarında uyguladığını doğrular. stdlib-only,
credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import qa_eval_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "batch_interval_s": 30}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(calls, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.evaluate_call({"calls": calls}, SPEC, PROF, CTX, p)


COMPLETED = lambda cid, **f: {"call_id": cid, "status": "completed", "features": f}

# T1 — kapsam %100: her uygun (completed) çağrı değerlendirilir (FR-ANA-001/SR-ANA-001)
m = run([COMPLETED("a", grounded_answers=2, total_answers=2, resolved=True, disclosure_given=True),
         COMPLETED("b", grounded_answers=1, total_answers=2, resolved=False, disclosure_given=True),
         {"call_id": "c", "status": "test_call", "reason": "test_call"}])
check(m["derived"]["eligible"] == 2 and m["derived"]["produced"] == 2, "T1 2 uygun → 2 değerlendirme (%100)")
check(m["coverage_gap"] == 0 and m["derived"]["coverage_ratio"] == 1.0, "T1 coverage_gap=0, ratio=1.0")

# T2 — degraded çağrı atlanmaz: öznitelik yok ama yine değerlendirilir (kapsam korunur)
m2 = run([COMPLETED("d")])
check(m2["produced"] == 1 and m2["derived"]["degraded"] == 1, "T2 öznitelik yok → degraded ama üretilir (atlanmaz)")
check(m2["coverage_gap"] == 0, "T2 degraded çağrı kapsam açığı yaratmaz")

# T3 — skor aritmetiği: groundedness + composite ağırlıklı toplam
m3 = run([COMPLETED("e", grounded_answers=3, total_answers=4, disclosure_given=True, resolved=True,
                    barge_in_respected=2, barge_in_total=2)])
ev = m3["evaluations"][0]
# accuracy=3/4=0.75; compliance=1.0; helpfulness=1.0; auto=0.35·0.75+0.35·1+0.30·1=0.2625+0.35+0.30=0.9125
check(abs(ev["score_accuracy"] - 0.75) < 1e-9, "T3 accuracy = 3/4 = 0.75 (groundedness)")
check(abs(ev["auto_score"] - 0.9125) < 1e-9, "T3 auto_score = 0.2625+0.35+0.30 = 0.9125 (ağırlıklı toplam)")

# T4 — composite tüm boyutların ağırlıklı toplamı (her satır için)
total_ok = True
for ev in m["evaluations"]:
    expect = 0.35 * ev["score_accuracy"] + 0.35 * ev["score_compliance"] + 0.30 * ev["score_helpfulness"]
    if abs(round(expect, 6) - ev["auto_score"]) > 1e-6:
        total_ok = False
check(total_ok, "T4 her satırda auto_score = Σ ağırlık·boyut (aritmetik birebir)")

# T5 — skorlar daima [0,1] (en kötü çağrı bile)
worst = run([COMPLETED("w", disclosure_given=False, consent_required=True, consent_verified=False,
                       policy_violations=9, grounded_answers=0, total_answers=5, resolved=False,
                       dead_air_events=10, barge_in_respected=0, barge_in_total=3)])
wev = worst["evaluations"][0]
check(all(0.0 <= wev[k] <= 1.0 for k in ("auto_score", "score_accuracy", "score_compliance", "score_helpfulness")),
      "T5 en kötü çağrı bile skorlar [0,1]'e sıkışır")
check(worst["score_domain_violations"] == 0, "T5 skor-alanı ihlali yok")

# T6 — idempotency: replay (aynı call_id) daraltılır
dup = [COMPLETED("x", grounded_answers=1, total_answers=1, resolved=True, disclosure_given=True),
       COMPLETED("x", grounded_answers=1, total_answers=1, resolved=True, disclosure_given=True)]
m6 = run(dup)
check(m6["produced"] == 1 and m6["idempotency_violations"] == 0, "T6 replay daraltılır (1 değerlendirme)")
m6b = run(dup, idempotent=False)
check(m6b["idempotency_violations"] >= 1, "T6 idempotent kapalı → çift değerlendirme tespit edilir")

# T7 — PII redaksiyon: ham transkript özniteliği reddedilir
m7 = run([COMPLETED("y", transcript_text="ham", grounded_answers=1, total_answers=1, resolved=True, disclosure_given=True)])
check(m7["pii_violations"] >= 1, "T7 transcript_text yasak öznitelik → PII ihlali")

# T8 — tenant izolasyon: cross-tenant + tenant_id eksikliği
m8 = run([{"call_id": "z", "status": "completed", "tenant_id": "t_other",
           "features": {"grounded_answers": 1, "total_answers": 1, "resolved": True, "disclosure_given": True}}])
check(m8["isolation_violations"] >= 1, "T8 cross-tenant çağrı → izolasyon ihlali")
m8b = run([COMPLETED("z2", grounded_answers=1, total_answers=1, resolved=True, disclosure_given=True)], isolate_tenant=False)
check(m8b["isolation_violations"] >= 1, "T8 tenant_id yok → izolasyon ihlali")

# T9 — uygunluk: uygun-olmayan statü reason taşımalı; bilinmeyen statü reddedilir
m9 = run([{"call_id": "ab", "status": "abandoned_pre_connect"}])   # reason yok
check(m9["eligibility_reason_missing"] >= 1, "T9 reason'sız uygun-olmayan statü → uygunluk ihlali")
try:
    run([{"call_id": "u", "status": "martian"}])
    check(False, "T9 bilinmeyen statü reddedilmeli")
except P.QaEvalError:
    check(True, "T9 bilinmeyen statü → reddedilir (INVALID_REQUEST)")

# T10 — determinizm + non-blocking
check(run([COMPLETED("k", grounded_answers=1, total_answers=2, resolved=True, disclosure_given=True)]) ==
      run([COMPLETED("k", grounded_answers=1, total_answers=2, resolved=True, disclosure_given=True)]),
      "T10 determinizm: aynı çağrı aynı sonuç (random yok)")
m10 = run([COMPLETED("k", grounded_answers=1, total_answers=1, resolved=True, disclosure_given=True)], non_blocking=False)
check(m10["blocking_violations"] >= 1, "T10 non_blocking kapalı → blocking ihlali (FR-RES-011)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
