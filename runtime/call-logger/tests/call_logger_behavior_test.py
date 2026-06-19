#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_logger_behavior_test.py — WBS 14.1.4 yapılandırılmış asenkron örneklemeli log davranış kapısı (T1–T8)

stdlib-only, bağımsız. call_logger_probe.py çekirdeğini import edip yapı (G1) / taksonomi (G2) /
örnekleme (G3, head-based + logs_always) / asenkron-non-blocking + overflow (G4, SR-RES-012) /
stream-label kardinalite (G5) / label+gövde PII (G6, FR-REC-004) / audit ayrımı (G7, FR-IAM-006)
davranışlarını doğrular (call_resource_behavior_test deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import call_logger_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CONTEXT = P.CONTEXT
RECORDS = P.RECORDS


def _run(records, context=None, base_rate=None, queue_capacity=None, **pol):
    policy = P._full_pol()
    policy.update(pol)
    sample = {"records": records}
    if base_rate is not None:
        sample["sampling"] = {"base_rate": base_rate}
    if queue_capacity is not None:
        sample["async_buffer"] = {"queue_capacity": queue_capacity}
    return P.emit_call(sample, SPEC, context or CONTEXT, policy)


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — yapı: yayılan her kayıt required_body_keys taşır (G1)
    m = _run(RECORDS, base_rate=1.0)
    check(m["structure_missing"] == 0, "T1 yapı: yayılan kayıtlar required_body_keys taşır (G1)")
    check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tam akış tüm kapıları geçer")
    m1 = _run(RECORDS, base_rate=1.0, structure_keys=False)
    check(m1["structure_missing"] >= 1, "T1 structure_keys KAPALI: tenant_id gövdeden düşer → G1 eler")

    # T2 — taksonomi: level∈levels + kind∈kinds (G2)
    check(m["level_violations"] == 0, "T2 happy: taksonomi uyumlu (G2)")
    bad = json.loads(json.dumps(RECORDS)); bad[1]["level"] = "VERBOSE"
    m2 = _run(bad, base_rate=1.0, conform_levels=False)
    check(m2["level_violations"] >= 1, "T2 conform KAPALI: bilinmeyen level geçer → G2 eler")

    def raises(fn):
        try:
            fn(); return False
        except P.LoggerError:
            return True
    check(raises(lambda: _run(bad, base_rate=1.0)), "T2 conform AÇIK: bilinmeyen level → reddedilir (G10)")

    # T3 — örnekleme: head-based + logs_always her zaman tutulur (G3)
    check(m["sampling_violations"] == 0, "T3 happy: örnekleme ihlali yok (G3)")
    ms = _run(RECORDS, base_rate=0.0)   # sampled-out
    check(ms["derived"]["call_sampled_in"] is False and ms["sampling_violations"] == 0,
          "T3 sampled-out: normal düşer ama logs_always korunur (G3 geçer)")
    check(ms["emitted"] == 4 and ms["sampled_out"] == 4,
          "T3 sampled-out: 4 garantili yayıldı, 4 normal örneklendi")
    m3 = _run(RECORDS, base_rate=0.0, honor_always=False)
    check(m3["sampling_violations"] >= 1, "T3 honor_always KAPALI + sampled-out: WARN/audit düşer → G3 eler")
    # tutarlılık: aynı correlation_id aynı karar
    check(_run(RECORDS, base_rate=0.0)["derived"]["sample_fraction"]
          == ms["derived"]["sample_fraction"], "T3 tutarlı: aynı correlation_id aynı sample_fraction")

    # T4 — asenkron non-blocking + overflow (G4, SR-RES-012)
    check(m["blocking_violations"] == 0 and m["overflow_violations"] == 0, "T4 happy: non-blocking, overflow yok (G4)")
    m4b = _run(RECORDS, base_rate=1.0, non_blocking=False)
    check(m4b["blocking_violations"] >= 1, "T4 non_blocking KAPALI: senkron yazım hot-path'i bloklar → G4 eler")
    m4o = _run(RECORDS, base_rate=1.0, queue_capacity=5)
    check(m4o["dropped_overflow"] == 3 and m4o["overflow_violations"] == 0,
          "T4 küçük buffer (cap=5): 3 sampleable düşer, garantili korunur (G4 geçer)")
    m4g = _run(RECORDS, base_rate=1.0, queue_capacity=2)
    check(m4g["overflow_violations"] >= 1, "T4 buffer (cap=2) < garantili(4): garantili kayıp → G4 eler")

    # T5 — stream-label kardinalite + label (G5)
    check(m["cardinality_violations"] == 0 and m["label_violations"] == 0, "T5 happy: stream-label disiplinli (G5)")
    m5c = _run(RECORDS, base_rate=1.0, enforce_cardinality=False)
    check(m5c["cardinality_violations"] >= 1, "T5 cardinality KAPALI: correlation_id stream label → G5 eler")
    m5l = _run(RECORDS, base_rate=1.0, enforce_labels=False)
    check(m5l["label_violations"] >= 1, "T5 label KAPALI: sınırsız stream label → G5 eler")

    # T6 — label PII + gövde redaction (G6, FR-REC-004)
    check(m["pii_violations"] == 0 and m["redaction_violations"] == 0, "T6 happy: PII/redaction temiz (G6)")
    m6p = _run(RECORDS, base_rate=1.0, enforce_pii=False)
    check(m6p["pii_violations"] >= 1, "T6 pii KAPALI: phone_number stream label → G6 eler")
    leak = json.loads(json.dumps(RECORDS)); leak[0]["fields"]["note"] = "ara 05551234567"
    check(_run(leak, base_rate=1.0)["redaction_violations"] == 0,
          "T6 redaction AÇIK: ham telefon gövdede redakte edilir → G6 geçer")
    check(_run(leak, base_rate=1.0, redact_body=False)["redaction_violations"] >= 1,
          "T6 redaction KAPALI: ham telefon gövdede → G6 eler")
    check(m["redaction_violations"] == 0, "T6 kimlik (correlation_id/trace_id) PII yanlış-pozitif değil")

    # T7 — audit ayrımı (G7, FR-IAM-006)
    check(m["audit_violations"] == 0 and m["derived"]["worm_sink_records"] == 1,
          "T7 happy: audit ayrımı doğru (1 audit → WORM sink) (G7)")
    m7 = _run(RECORDS, base_rate=1.0, separate_audit=False)
    check(m7["audit_violations"] >= 1 and m7["derived"]["worm_sink_records"] == 0,
          "T7 separate_audit KAPALI: audit telemetri sink → G7 eler")

    # T8 — reddetme (G10) + determinizm + sink dağılımı
    check(raises(lambda: P.emit_call({"records": []}, SPEC, CONTEXT, P._full_pol())),
          "T8 boş records → reddedilir")
    check(raises(lambda: P.emit_call({"records": [{"level": "INFO"}]}, SPEC, CONTEXT, P._full_pol())),
          "T8 kayıtta event/kind eksik → reddedilir")
    check(raises(lambda: P.StructuredAsyncLogger(SPEC, {"tenant_id": "t"}, P._full_pol())),
          "T8 emisyon bağlamı (correlation_id) eksik → reddedilir")
    check(m["derived"]["worm_sink_records"] == 1 and m["derived"]["telemetry_sink_records"] == 7,
          "T8 sink dağılımı doğru (worm=1 audit, telemetri=7)")
    s1 = _run(RECORDS, base_rate=1.0)
    s2 = _run(RECORDS, base_rate=1.0)
    check(s1 == s2, "T8 determinizm: aynı akış aynı sonuç (saf; sabit hash)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("call_logger_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
