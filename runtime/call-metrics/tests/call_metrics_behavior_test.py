#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_metrics_behavior_test.py — WBS 14.1.2 teknik metrikler davranış kapısı (T1–T8)

stdlib-only, bağımsız. call_metrics_probe.py çekirdeğini import edip kapsam (G1) / katalog uyumu (G2) /
değer domaini (G3) / kardinalite (G4) / etiket (G5) / PII (G6) / oran (G7) davranışlarını doğrular
(call_trace_behavior_test / context_propagation_behavior_test deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import call_metrics_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CONTEXT = P.CONTEXT
HAPPY = P.HAPPY_BUNDLE


def _run(bundle, context=None, must_cover=None, **pol):
    policy = P._full_pol()
    policy.update(pol)
    sample = {"bundle": bundle}
    if must_cover is not None:
        sample["must_cover"] = must_cover
    return P.compute_call(sample, SPEC, context or CONTEXT, policy)


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — kapsam: required BRD §15 metrikleri hesaplanıp yayılır (G1)
    m = _run(HAPPY)
    check(m["metric_missing"] == 0, "T1 kapsam: 16 required metrik hesaplandı (G1)")
    check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tam çağrı tüm kapıları geçer")
    m2 = _run(HAPPY, compute_all=False, drop_metrics=["voice_jitter_ms", "barge_in_total"])
    check(m2["metric_missing"] == 2, "T1 2 metrik düşerse → 2 eksik (G1 eler)")

    # T2 — katalog uyumu: yalnız 0.4.7 catalog name/type/unit (G2)
    check(m["catalog_violations"] == 0, "T2 happy: katalog uyumlu (G2)")
    mm = _run(HAPPY, conform_catalog=False)
    check(mm["catalog_violations"] >= 1, "T2 conform KAPALI: catalog dışı metrik → G2 eler")

    # T3 — değer domaini: ratio∈[0,1], ms≥0, sayaç int≥0 (G3)
    check(m["value_violations"] == 0, "T3 happy: değerler domain-içi (G3)")
    bad = json.loads(json.dumps(HAPPY))
    bad["trace"]["timestamps"]["tts_first_audio"] = 1700   # tts_request(1800) öncesi → negatif tts
    mt = _run(bad)
    check(mt["value_violations"] >= 1, "T3 negatif tts gecikmesi (trace) → domain dışı → G3 eler")

    # T4 — kardinalite: yüksek-kardinalite kimlik LABEL olmaz (G4)
    check(m["cardinality_violations"] == 0, "T4 happy: yüksek-kardinalite label yok (G4)")
    m4 = _run(HAPPY, enforce_cardinality=False)
    check(m4["cardinality_violations"] >= 1, "T4 enforce KAPALI: correlation_id label → G4 eler")

    # T5 — etiket: yalnız catalog[].labels ⊆ allowed (G5)
    check(m["label_violations"] == 0, "T5 happy: izinsiz label yok (G5)")
    m5 = _run(HAPPY, enforce_labels=False)
    check(m5["label_violations"] >= 1, "T5 enforce KAPALI: izinsiz boyut → G5 eler")

    # T6 — PII: label'da PII anahtarı yok (G6)
    check(m["pii_violations"] == 0, "T6 happy: PII label yok (G6)")
    m6 = _run(HAPPY, enforce_pii=False)
    check(m6["pii_violations"] >= 1, "T6 enforce KAPALI: phone_number label → G6 eler")

    # T7 — oran: ratio_derived payda>0 + ∈[0,1] (G7) + DEĞER doğruluğu
    v = m["values"]
    check(v["voice_packet_loss_ratio"] == 0.02 and v["llm_tokens_total"] == 400
          and v["silence_duration_ms"] == 350 and v["cost_per_minute"] == 0.02,
          "T7 hesaplanan DEĞERLER doğru (loss=0.02, tokens=400, silence=350, cost=0.02)")
    dl = m["derived_latencies"]
    check(dl["e2e_response_latency_ms"] == 750 and dl["llm_latency_ms"] == 200
          and dl["tts_latency_ms"] == 150 and dl["tool_latency_ms"] == 150,
          "T7 türetilen gecikmeler 14.1.1 ile birebir (e2e=750, llm=200, tts=150, tool=150)")
    zero = json.loads(json.dumps(HAPPY))
    zero["reliability"]["provider_requests"] = {"llm": 0}
    zero["reliability"]["provider_errors"] = {"llm": 1}
    mz = _run(zero, safe_ratio=False)
    check(mz["ratio_violations"] >= 1, "T7 payda=0 + safe_ratio KAPALI → sıfıra bölme → G7 eler")
    mzb = _run(zero)
    check(mzb["ratio_violations"] == 0, "T7 safe_ratio: payda=0 → tanımlı 0.0 (G7 geçer)")

    # T8 — reddetme (G10) + determinizm
    def raises(fn):
        try:
            fn(); return False
        except P.MetricError:
            return True
    check(raises(lambda: P.compute_call({"bundle": {"media": {}}}, SPEC, CONTEXT, P._full_pol())),
          "T8 trace.timestamps eksik → reddedilir")
    check(raises(lambda: P.CallMetricExtractor(SPEC, {"region": "eu"}, P._full_pol())),
          "T8 emisyon bağlamı (tenant_id) eksik → reddedilir")
    s1 = _run(HAPPY)
    s2 = _run(HAPPY)
    check(s1 == s2, "T8 determinizm: aynı demet aynı sonuç (saf aritmetik)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("call_metrics_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
