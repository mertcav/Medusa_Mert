#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detection_behavior_test.py — WBS 14.2.4 tespit motoru davranış kapısı (T1–T11).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: IssueDetectionEngine'in FR-ANA-004 yanlış-bilgi/tool-hata/
güvenlik tespitini — enjekte edilen (etiketli) her pozitif vakanın tespiti (recall, BİRİNCİL — SR-ANA-004 T) +
enjekte-temizde sahte işaret yok (precision) + işaret⟺reason tutarlılığı + kapalı-sözlük reason + OLAP flag_*
BİREBİR + her uygun çağrı ÜÇ kategoride kapsam + idempotency + tenant izolasyon + PII disiplinini gerçek
tespit senaryolarında uyguladığını doğrular. stdlib-only, credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import detection_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(calls, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.detect_calls({"calls": calls}, SPEC, dict(PROF), CTX, p)


def clean(cid, **sig):
    return P._clean(cid, **sig)


def inject(cid, cat, **sig):
    return P._inject(cid, cat, **sig)


# T1 — recall (BİRİNCİL): enjekte edilen her pozitif vaka tespit edilir
calls = [inject("m1", "misinformation"), inject("t1", "tool_error"),
         inject("s1", "security_violation"), clean("c1"), clean("c2")]
m = run(calls)
check(m["missed_detection"] == 0, "T1 enjekte 3 pozitif → missed_detection=0 (recall == 1.0, BİRİNCİL)")
check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tüm HARD kapı geçer")

# T2 — precision: enjekte-temizde sahte işaret yok
ft = m["derived"]["flag_totals"]
check(m["false_positive"] == 0 and ft["misinformation"] == 1 and ft["tool_error"] == 1 and ft["security_violation"] == 1,
      "T2 enjekte-temizde false_positive=0; her kategoride tam 1 işaret")

# T3 — her reason_code kendi sinyalini tespit eder (kapsayıcı recall)
for cat, sig in (("misinformation", {"kb_contradictions": 1}), ("misinformation", {"unverified_commitments": 1}),
                 ("tool_error", {"tool_errors": 1}), ("tool_error", {"tool_timeouts": 1}),
                 ("tool_error", {"provider_errors": 1}), ("security_violation", {"pii_disclosure_events": 1}),
                 ("security_violation", {"prompt_injection_detected": 1}),
                 ("security_violation", {"jailbreak_detected": 1}),
                 ("security_violation", {"unauthorized_actions": 1}),
                 ("security_violation", {"policy_violations": 1})):
    c = clean("x")
    c["injected"][cat] = True
    c.update(sig)
    mm = run([c])
    check(mm["missed_detection"] == 0 and mm["derived"]["flag_totals"][cat] == 1,
          "T3 %s/%s sinyali tespit edilir" % (cat, list(sig.keys())[0]))

# T4 — ungrounded_answer: grounded < total → misinformation
m4 = run([clean("u", grounded_answers=2, total_answers=5)])
# clean'de injected hepsi false → bu sahte işaret olur mu? grounded<total tetikler → enjekte=false ama flag=true → false_positive
check(m4["false_positive"] >= 1 and m4["derived"]["flag_totals"]["misinformation"] == 1,
      "T4 grounded<total → ungrounded_answer tespiti (etiketsiz tetik false_positive sayılır)")
# total=0 → dayanaksızlık yok (bölme yok)
m4b = run([clean("u0", grounded_answers=0, total_answers=0)])
check(m4b["derived"]["flag_totals"]["misinformation"] == 0, "T4 total_answers=0 → ungrounded tetiklenmez")

# T5 — apply_rules kapalı → enjekte pozitifler kaçar (G1 recall eler)
m5 = run(calls, apply_rules=False)
check(m5["missed_detection"] == 3 and not all(ok for ok, _ in P.evaluate(SPEC, m5)),
      "T5 apply_rules kapalı: 3 enjekte kaçar → G1 recall eler (BİRİNCİL)")

# T6 — overflag → enjekte-temizde sahte işaret (G2 precision eler)
m6 = run([clean("c1"), clean("c2")], overflag=True)
check(m6["false_positive"] >= 1, "T6 overflag: enjekte-temizde işaret fires → G2 precision eler")

# T7 — tutarlılık: enforce_consistency kapalı → fires ama reason boş (G3)
m7 = run([inject("m1", "misinformation")], enforce_consistency=False)
check(m7["consistency_violations"] >= 1, "T7 enforce_consistency kapalı: fires ama reason boş → G3 eler")

# T8 — sözlük: closed_taxonomy kapalı → serbest-metin reason (G4)
m8 = run([inject("t1", "tool_error")], closed_taxonomy=False)
check(m8["vocab_violations"] >= 1, "T8 closed_taxonomy kapalı: serbest-metin reason → G4 eler")

# T9 — kapsam: detect_all kapalı → security atlanır (G5) + atlanan enjeksiyon kaçar (G1)
m9 = run([clean("c1"), clean("c2")], detect_all=False)
check(m9["coverage_gap"] >= 1 and m9["derived"]["categories_produced"] == 4,
      "T9 detect_all kapalı: security atlanır → kapsam açığı (2×2=4 değerlendirme)")
m9b = run([inject("s1", "security_violation")], detect_all=False)
check(m9b["missed_detection"] >= 1 and m9b["coverage_gap"] >= 1,
      "T9 atlanan security enjeksiyonu → hem recall hem kapsam eler")

# T10 — idempotency + uygunluk
dup = [inject("m1", "misinformation"), inject("m1", "misinformation")]
m10 = run(dup)
check(m10["derived"]["eligible_count"] == 1 and m10["idempotency_violations"] == 0,
      "T10 replay daraltılır (1 değerlendirme)")
check(run(dup, idempotent=False)["idempotency_violations"] >= 1, "T10 idempotent kapalı → çift-üretim tespit")
ip = clean("ip"); ip["status"] = "in_progress"
m10b = run([inject("m1", "misinformation"), ip])
check(m10b["derived"]["eligible_count"] == 1 and m10b["coverage_gap"] == 0,
      "T10 in_progress dışlanır (eligible=1, kapsam korunur, sessiz filtre yok)")

# T11 — izolasyon + PII + determinizm + non-blocking
ct = clean("ct"); ct["tenant_id"] = "t_other"
m11 = run([inject("m1", "misinformation"), ct])
check(m11["isolation_violations"] >= 1 and m11["derived"]["eligible_count"] == 1,
      "T11 cross-tenant çağrı → G7 eler + değerlendirmeye karışmaz")
leak = clean("p"); leak["transcript_text"] = "ham"
check(run([leak])["pii_violations"] >= 1, "T11 transcript_text yasak girdi → G8 PII eler")
check(run(calls) == run(calls), "T11 determinizm: aynı sinyal aynı işaret (random yok)")
check(run([clean("c1")], non_blocking=False)["blocking_violations"] >= 1,
      "T11 non_blocking kapalı → G9 eler (FR-RES-011)")

# call_id eksik reddi
try:
    run([{"agent_id": "ag1"}])
    check(False, "call_id eksik reddedilmeli")
except P.DetectError:
    check(True, "call_id eksik girdi → reddedilir (INVALID_REQUEST)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
