#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_trace_behavior_test.py — WBS 14.1.1 çağrı trace span'leri davranış kapısı (T1–T8)

stdlib-only, bağımsız. call_trace_probe.py çekirdeğini import edip kapsam (G1) / span eşleme (G2) /
nedensel sıra (G3) / ağaç iyi-biçimlilik (G4) / kimlik (G5) / attribute disiplini (G6) / gecikme
türetme (G7) davranışlarını doğrular (context_propagation_behavior_test deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import call_trace_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
SESSION = {
    "tenant_id": "t_acme", "org_unit": "ou_sales", "agent_id": "ag_1",
    "correlation_id": "corr-001", "region": "eu-west-1", "call_id": "call-001", "trace_id": "tr-001",
}
HAPPY = P.HAPPY_EVENTS
COVER = P.HAPPY_COVER


def _run(events, session=None, must_cover=None, **pol):
    policy = {"record_all": True, "correct_mapping": True, "nest_spans": True,
              "attach_identity": True, "enforce_attr": True, "drop_ts": []}
    policy.update(pol)
    sample = {"events": events}
    if must_cover is not None:
        sample["must_cover"] = must_cover
    return P.simulate(sample, SPEC, session or SESSION, policy)


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — kapsam: BRD §15 zaman damgaları span event olarak kaydedilir (G1)
    m = _run(HAPPY, must_cover=COVER)
    check(m["coverage_missing"] == 0 and m["recorded_count"] == 14, "T1 kapsam: 14/14 zaman damgası kaydedildi (G1)")
    check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tam çağrı tüm kapıları geçer")
    m2 = _run(HAPPY, must_cover=COVER, record_all=False, drop_ts=["audio_played", "stt_final"])
    check(m2["coverage_missing"] == 2, "T1 2 zaman damgası düşerse → 2 eksik (G1 eler)")

    # T2 — span eşleme: her zaman damgası doğru span KINDine (G2)
    check(m["mapping_violations"] == 0, "T2 happy: doğru span eşlemesi (G2)")
    mm = _run(HAPPY, must_cover=COVER, correct_mapping=False)
    check(mm["mapping_violations"] >= 1, "T2 mapping KAPALI: alt-span'lar root'a → G2 eler")
    # span sayısı: call+turn+stt+llm+tool+tts = 6 (doğru eşleme)
    check(m["spans_total"] == 6, "T2 happy: 6 span (call/turn/stt/llm/tool/tts)")

    # T3 — nedensel sıra: causal_order çiftleri monoton (G3)
    check(m["ordering_violations"] == 0, "T3 happy: nedensel sıra korundu (G3)")
    bad = [dict(e) for e in HAPPY]
    for e in bad:
        if e["ts"] == "tts_first_audio":
            e["t"] = 1700   # tts_request(1800) öncesi → ters
    mo = _run(bad, must_cover=COVER)
    check(mo["ordering_violations"] >= 1, "T3 tts_first_audio < tts_request → G3 eler")

    # T4 — ağaç iyi-biçimlilik: tek root + nesting + end≥start (G4)
    check(m["tree_violations"] == 0, "T4 happy: ağaç iyi-biçimli (G4)")
    over = [dict(e) for e in HAPPY]
    for e in over:
        if e["ts"] == "audio_played":
            e["t"] = 5500   # call_ended(5000) sonrası → turn span call kökünü taşar
    mt = _run(over, must_cover=COVER)
    check(mt["tree_violations"] >= 1, "T4 audio_played call_ended sonrası → kök sınırı taşar (G4 eler)")

    # T5 — kimlik: çağrı başına tek trace_id + tek correlation_id, her span taşır (G5)
    check(m["distinct_trace_ids"] == 1 and m["distinct_correlation_ids"] == 1 and m["identity_violations"] == 0,
          "T5 tek trace_id + tek correlation_id (G5)")
    mi = _run(HAPPY, must_cover=COVER, attach_identity=False)
    check(mi["identity_violations"] >= 1, "T5 attach KAPALI: span trace_id taşımıyor → G5 eler")

    # T6 — attribute disiplini: PII/ham payload span'da yok (G6)
    pii = [dict(e) for e in HAPPY]
    pii[3] = dict(pii[3]); pii[3]["attrs"] = ["agent_id", "card_number"]
    pii[5] = dict(pii[5]); pii[5]["attrs"] = ["transcript_text", "provider"]
    mp = _run(pii, must_cover=COVER)
    check(mp["attribute_violations"] == 0, "T6 enforce açıkken PII/transkript çıkarıldı (G6)")
    mp2 = _run(pii, must_cover=COVER, enforce_attr=False)
    check(mp2["attribute_violations"] == 2, "T6 enforce KAPALI: card_number + transcript_text → 2 (G6 eler)")

    # T7 — gecikme türetme: BRD §15 gecikmeleri non-negative + doğru (G7)
    dl = m["derived_latencies"]
    check(dl["e2e_response_latency_ms"] == 750 and dl["llm_latency_ms"] == 200
          and dl["tts_latency_ms"] == 150 and dl["tool_latency_ms"] == 150,
          "T7 türetilen gecikmeler doğru (e2e=750, llm=200, tts=150, tool=150)")
    neg = [dict(e) for e in HAPPY]
    for e in neg:
        if e["ts"] == "llm_first_token":
            e["t"] = 1100   # request(1360) öncesi → negatif llm gecikmesi
    mn = _run(neg, must_cover=COVER)
    check(mn["derivation_violations"] >= 1, "T7 negatif llm gecikmesi → G7 eler")

    # T8 — reddetme (G10) + determinizm + karışık sıra
    def raises(fn):
        try:
            fn(); return False
        except P.TraceError:
            return True
    check(raises(lambda: P.simulate({"events": [{"t": 0, "ts": "bogus_ts"}]}, SPEC, SESSION, P._full_pol())),
          "T8 bilinmeyen zaman damgası reddedilir")
    check(raises(lambda: P.simulate({"events": [{"t": 0, "ts": "call_connected"}]}, SPEC,
                                    {"tenant_id": "t1", "correlation_id": "c1"}, P._full_pol())),
          "T8 ingress trace_id eksik reddedilir")
    s1 = _run(HAPPY, must_cover=COVER)
    s2 = _run(list(reversed(HAPPY)), must_cover=COVER)
    check(s1 == s2, "T8 determinizm: karışık olay sırası aynı sonuç")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("call_trace_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
