#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
turn_taking_behavior_test.py — WBS 3.1.3 Turn-taking + barge-in koordinasyonu davranış kapısı (T1–T8)

stdlib-only, bağımsız. turn_taking_probe.py çekirdeğini import edip turn state machine geçişleri /
tek-zemin (floor) kuralı / barge-in koordinasyonu (SPEAK + THINK) / idempotent iptal / backchannel
ayrımı / gereksiz ara yanıt bastırma / legal geçiş + handoff davranışlarını doğrular
(edge_vad_behavior_test deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import turn_taking_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _ev(t, ty):
    return {"t": t, "type": ty}


def _run(events, dispatch=12, **pol):
    params = {"orch_dispatch_ms": dispatch}
    policy = {"coordinate_barge_in": True, "floor_guard": True, "backchannel_yields_floor": False}
    policy.update(pol)
    return P.simulate({"events": events}, SPEC, params, policy)


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — tam tur döngüsü + tek-zemin korunur (C3/C6)
    happy = [_ev(0, "speech_start"), _ev(900, "endpoint"), _ev(1000, "response_ready"),
             _ev(1030, "tts_first_chunk"), _ev(1900, "tts_complete")]
    m = _run(happy)
    check(m["turn_total"] == 1 and m["illegal_transitions"] == 0, "T1 tam tur: 1 turn, illegal geçiş yok")
    check(m["final_state"] == "LISTEN" and m["floor_violation"] == 0, "T1 final LISTEN, zemin ihlali yok")

    # T2 — barge-in SPEAK: cancel + SPEAK→CAPTURE, koordinasyon ≤ bütçe (C1/C2)
    bs = [_ev(0, "speech_start"), _ev(700, "endpoint"), _ev(800, "response_ready"),
          _ev(830, "tts_first_chunk"), _ev(1500, "barge_in")]
    mb = _run(bs, dispatch=12)
    check(mb["cancels"] == 1 and mb["unhandled_barge_in"] == 0, "T2 barge-in SPEAK: 1 cancel, işlenmeyen yok")
    check(mb["final_state"] == "CAPTURE" and mb["final_floor"] == "user", "T2 SPEAK→CAPTURE, zemin kullanıcıya")
    bud = SPEC["gates"]["coordination_p95_budget_ms"]
    green = SPEC["gates"]["green_coordination_ms"]
    check(mb["coordination_p95_ms"] <= bud, "T2 koordinasyon ≤ bütçe (50ms)")
    check(mb["coordination_p95_ms"] <= green, "T2 managed dispatch → green (≤20ms)")
    check(mb["composed_e2e_p95_ms"] <= SPEC["barge_in"]["composition"]["total_budget_ms"],
          "T2 composed e2e (edge+orch+egress) ≤200ms")

    # T3 — barge-in THINK: in-flight üretim iptal, zemin bırakılır (C1)
    bt = [_ev(0, "speech_start"), _ev(700, "endpoint"), _ev(800, "barge_in")]
    mt = _run(bt)
    check(mt["cancels"] == 1 and mt["final_state"] == "CAPTURE", "T3 barge-in THINK: üretim iptal → CAPTURE")
    check(mt["missed_cancels"] == 0, "T3 THINK barge-in cancel kaçmaz")

    # T4 — idempotent iptal: SPEAK barge_in + CAPTURE'da tekrar barge_in → tek cancel (C5)
    idem = [_ev(0, "speech_start"), _ev(700, "endpoint"), _ev(800, "response_ready"),
            _ev(1400, "barge_in"), _ev(1450, "barge_in"), _ev(1500, "barge_in")]
    mi = _run(idem)
    check(mi["cancels"] == 1, "T4 üç barge_in → tek cancel (idempotent)")
    check(mi["duplicate_barge_in"] == 2 and mi["spurious_cancels"] == 0, "T4 CAPTURE'da tekrarlar yoksayıldı")

    # T5 — backchannel ayrımı: 'evet' agent'ı kesmez (C4)
    bch = [_ev(0, "speech_start"), _ev(600, "endpoint"), _ev(700, "response_ready"),
           _ev(730, "tts_first_chunk"), _ev(1100, "backchannel"), _ev(1800, "tts_complete")]
    mc = _run(bch)
    check(mc["backchannel_ignored"] == 1 and mc["backchannel_action"] == 0, "T5 backchannel yoksayıldı (cancel/zemin yok)")
    check(mc["cancels"] == 0 and mc["final_state"] == "LISTEN", "T5 agent kesilmeden bitirdi")
    # ters politika (yields_floor=true) → backchannel barge-in gibi davranır → C4 eler
    mcw = _run(bch, backchannel_yields_floor=True)
    check(mcw["backchannel_action"] == 1 and not all(ok for ok, _ in P.evaluate(SPEC, mcw)),
          "T5 yields_floor=true → backchannel-eylemi C4 kapısını eler")

    # T6 — gereksiz ara yanıt bastırılır (C3/C7)
    spur = [_ev(0, "speech_start"), _ev(300, "response_ready"), _ev(900, "endpoint"),
            _ev(1000, "response_ready"), _ev(1030, "tts_first_chunk"), _ev(1800, "tts_complete")]
    ms = _run(spur)
    check(ms["interim_suppressed"] == 1 and ms["floor_violation"] == 0, "T6 erken yanıt bastırıldı, zemin ihlali yok")
    check(ms["turn_total"] == 1 and ms["illegal_transitions"] == 0, "T6 endpoint sonrası yanıt verildi (legal)")

    # T7 — legal geçiş + handoff (her durumdan TRANSFER/END)
    tr = [_ev(0, "speech_start"), _ev(800, "endpoint"), _ev(900, "response_ready"),
          _ev(930, "tts_first_chunk"), _ev(1500, "transfer")]
    mtr = _run(tr)
    check(mtr["final_state"] == "TRANSFER" and mtr["illegal_transitions"] == 0, "T7 SPEAK→TRANSFER legal (handoff)")
    en = [_ev(0, "speech_start"), _ev(500, "hangup")]
    men = _run(en)
    check(men["final_state"] == "END" and men["illegal_transitions"] == 0, "T7 CAPTURE→END legal (hangup)")

    # T8 — degrade: floor_guard+coordinate kapalı → çoklu kapı eler (regresyon yakalanır)
    deg = [_ev(0, "speech_start"), _ev(300, "response_ready"), _ev(900, "endpoint"),
           _ev(1000, "response_ready"), _ev(1030, "tts_first_chunk"), _ev(1600, "barge_in")]
    md = _run(deg, dispatch=80, coordinate_barge_in=False, floor_guard=False)
    check(md["floor_violation"] >= 1 and md["unhandled_barge_in"] >= 1, "T8 degrade: zemin ihlali + işlenmeyen barge-in")
    check(not all(ok for ok, _ in P.evaluate(SPEC, md)), "T8 degrade en az bir kapıyı eler")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("turn_taking_behavior: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
