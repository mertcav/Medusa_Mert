#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edge_vad_behavior_test.py — WBS 2.2.3 Edge VAD/endpointing davranış kapısı (T1–T7)

stdlib-only, bağımsız. edge_vad_probe.py çekirdeğini import edip VAD sınıflama / hangover köprüsü /
DİNAMİK onay-sessizliği / hesitation köprüleme / söz-sonu gecikmesi / barge-in algılama + echo guard /
ölü hava bastırma davranışlarını doğrular (jitter_behavior_test deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import edge_vad_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
FRAME_MS = SPEC["media_profile"]["frame_ms"]
PAR = P._params_from(SPEC, {"name": "_t", "region": "${R}"})
SP, SI, EC = P.SPEECH_DBOV, P.SILENCE_DBOV, P.ECHO_DBOV


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — VAD konuşma/sessizlik sınıflama + adaptif eşik (V3)
    energy, runs = P._frames_from_script([("silence", 6), ("speech", 40), ("silence", 30)])
    sp = P.vad_classify(energy, PAR)
    check(not sp[0] and not sp[-1] and any(sp), "T1 VAD kenar sessizlik, ortada konuşma")
    check(sum(sp) >= 40, "T1 konuşma çerçeveleri iletilir (≥ koşu uzunluğu)")

    # T2 — hangover mikro-duraklama köprüsü (V4)
    e2, _ = P._frames_from_script([("speech", 18), ("silence", 2), ("speech", 18), ("silence", 20)])
    sp2 = P.vad_classify(e2, PAR)
    check(all(sp2[18:20]), "T2 2-çerçeve mikro-boşluk hangover ile köprülendi (kesilmez)")
    e3, _ = P._frames_from_script([("speech", 18), ("silence", 10), ("speech", 18), ("silence", 20)])
    sp3 = P.vad_classify(e3, PAR)
    check(not all(sp3[20:26]), "T2 10-çerçeve boşluk hangover'ı aşar → konuşma kesilir")

    # T3 — DİNAMİK onay-sessizliği: uzun<orta<kısa; tereddüt uzatır (V2)
    t_long = P.dynamic_confirm_ms(900, 0, PAR)
    t_med = P.dynamic_confirm_ms(500, 0, PAR)
    t_short = P.dynamic_confirm_ms(200, 0, PAR)
    check(t_long < t_med < t_short, "T3 dinamik T: uzun-söz < orta < kısa-söz")
    check(P.dynamic_confirm_ms(200, 1, PAR) > t_short, "T3 önceki duraklama kısa sözde T'yi uzatır")
    check(P.dynamic_confirm_ms(500, 1, PAR) == t_med, "T3 orta söz tamamlanmışsa tereddüt cezası uygulanmaz")
    check(P.dynamic_confirm_ms(9999, 0, PAR) >= PAR["min_confirm_ms"], "T3 T min'e clamp")

    # T4 — hesitation köprülenir, gerçek son yakalanır, erken kesme yok (V6/V7)
    eh, _ = P._frames_from_script([("silence", 4), ("speech", 15), ("silence", 12), ("speech", 20), ("silence", 28)])
    gt_h = [[[4, 19], [31, 51]]]
    mh = P.simulate({"energy_dbov": eh, "ground_truth": {"utterances": gt_h}}, SPEC, PAR)
    check(mh["false_early_cut_rate"] == 0.0, "T4 hesitation duraklamasında erken kesme yok")
    check(mh["missed_endpoint_rate"] == 0.0 and mh["utterances_emitted"] == 1, "T4 gerçek son yakalandı (1 söz)")

    # T5 — söz-sonu gecikmesi SAD §20 bütçesinde (uzun tur → green) (V5)
    el, rl = P._frames_from_script([("silence", 4), ("speech", 46), ("silence", 24)])
    ml = P.simulate({"energy_dbov": el, "ground_truth": {"utterances": [[rl[0]]]}}, SPEC, PAR)
    bud = SPEC["gates"]["endpoint_decision_latency_p95_ms"]
    green = SPEC["gates"]["green_endpoint_latency_ms"]
    check(ml["endpoint_latency_p95_ms"] <= bud, "T5 söz-sonu gecikmesi ≤ bütçe (250ms)")
    check(ml["endpoint_latency_p95_ms"] <= green, "T5 uzun akıcı tur → green bant (≤200ms)")

    # T6 — barge-in algılama + echo guard yanlış tetik bastırır (V8/V9)
    eb = [SI] * 10 + [EC] * 60 + [SI] * 10
    for i in range(30, 55):
        eb[i] = SP
    mb = P.simulate({"energy_dbov": eb, "agent_speech": {"from": 10, "to": 70}, "user_barge_onset": 30}, SPEC, PAR)
    check(mb["barge_in_count"] == 1 and mb["false_barge_in"] == 0, "T6 gerçek barge-in algılandı, yanlış tetik yok")
    check(mb["barge_in_latency_p95_ms"] <= SPEC["gates"]["barge_in_detection_latency_p95_ms"],
          "T6 barge-in gecikmesi ≤200ms (ADR-005/NFR 10.1)")
    me = P.simulate({"energy_dbov": [SI] * 10 + [EC] * 60 + [SI] * 10,
                     "agent_speech": {"from": 10, "to": 70}, "user_barge_onset": None}, SPEC, PAR)
    check(me["false_barge_in"] == 0 and me["barge_in_count"] == 0, "T6 echo-only → yanlış barge-in yok (V9)")

    # T7 — ölü hava bastırma + finalize yalnız endpoint'te (V10/V11)
    ed, rd = P._frames_from_script([("silence", 40), ("speech", 18), ("silence", 42)])
    md = P.simulate({"energy_dbov": ed, "ground_truth": {"utterances": [[rd[0]]]}}, SPEC, PAR)
    check(md["stt_suppressed"] > md["stt_forwarded"] and md["dead_air_ok"], "T7 ölü hava bastırıldı (STT'ye gitmez)")
    check(md["utterances_emitted"] == 1, "T7 finalize yalnız endpoint'te (1 söz → 1 emit)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("edge_vad_behavior: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
