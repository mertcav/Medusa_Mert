#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dtmf_behavior_test.py — WBS 2.1.6 DTMF davranış kapısı (T1–T6)

stdlib-only, bağımsız. dtmf_probe.py çekirdeğini import edip RFC 2833 debounce / SIP INFO
ayrıştırma / süre kapısı / üretme / maskeleme davranışlarını doğrular (numbering e164_behavior deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dtmf_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CM = P._code_map(SPEC)
DS = P._digit_set(SPEC)
CLOCK = SPEC["dtmf"]["rfc2833_clock_rate"]


def _digit(code, dur, n_end=3):
    pk = [{"event": code, "marker": True, "duration": dur // 2, "e": False},
          {"event": code, "duration": dur, "e": False}]
    pk += [{"event": code, "duration": dur, "e": True} for _ in range(n_end)]
    return pk


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — RFC 2833 çok-paketli olay tek basamağa debounce (D2); paket sayısından bağımsız
    for n_end in (1, 3, 8):
        digs = P.detect_rfc2833(_digit(6, 1280, n_end), CLOCK, 40, CM)
        check(digs == [("6", 160.0)], "T1 %d End paketi → tek '6' (debounce)" % n_end)

    # T2 — süre kapısı: kapı aritmetiği (dur_samples/clock*1000 ≥ min) (D4)
    for ms, expect_keep in ((40, True), (39, False), (80, True), (10, False)):
        samples = int(ms * CLOCK / 1000)
        digs = P.detect_rfc2833(_digit(2, samples), CLOCK, 40, CM)
        kept = (len(digs) == 1)
        check(kept == expect_keep, "T2 %dms olay → %s" % (ms, "tutulur" if expect_keep else "düşürülür"))

    # T3 — olay kodu → basamak eşleme sınırları (D3): 0..15 kabul, 16 reddedilir
    for code in range(16):
        try:
            P.map_event_code(code, CM)
            ok = True
        except P.DtmfError:
            ok = False
        check(ok, "T3 kod %d kabul" % code)
    try:
        P.map_event_code(16, CM)
        ok16 = False
    except P.DtmfError:
        ok16 = True
    check(ok16, "T3 kod 16 reddedilir (aralık dışı)")

    # T4 — SIP INFO ayrıştırma çeşitleri (D5)
    r = P.detect_sip_info("application/dtmf-relay", "Signal=*\r\nDuration=160", 40, CM, DS)
    check(r is not None and r[0] == "*", "T4 dtmf-relay Signal=* → '*'")
    r = P.detect_sip_info("application/dtmf", "C", 40, CM, DS)
    check(r is not None and r[0] == "C", "T4 application/dtmf 'C' → 'C'")
    r = P.detect_sip_info("application/dtmf-relay", "Signal=2\r\nDuration=30", 40, CM, DS)
    check(r is None, "T4 30ms SIP INFO → süre-altı düşürülür")

    # T5 — üretme aritmetiği (D7): rfc2833 paket sayısı = 2 + end_redundancy; sip_info = 1 INFO/basamak
    prof = {"name": "x", "dtmf_mode": "rfc2833", "end_redundancy": 3, "inter_digit_gap_ms": 40, "region": "r"}
    recs, _ = P.generate_dtmf(SPEC, prof, "12*")
    check(all(r["packets"] == 5 for r in recs), "T5 rfc2833 her basamak 5 paket (2+3)")
    check(sum(r["info_requests"] for r in P.generate_dtmf(
        SPEC, {"name": "y", "dtmf_mode": "sip_info", "inter_digit_gap_ms": 40, "region": "r"}, "12*")[0]) == 3,
        "T5 sip_info 3 basamak → 3 INFO")

    # T6 — maskeleme: hassas pencerede transkript değeri basamağı SIZDIRMAZ (D8)
    sample = {"sensitive": True, "expected_digits": "78",
              "events": [{"type": "rfc2833", "packets": _digit(7, 1280)},
                         {"type": "rfc2833", "packets": _digit(8, 1280)}]}
    detected, F = P.evaluate_detection(SPEC, sample)
    leak = any(d["transcript_value"] in ("7", "8") for d in detected)
    check(not leak and all(d["digit"] in ("7", "8") for d in detected) and all(ok for ok, _ in F),
          "T6 maskeli pencere: transkript sızmaz, aksiyon değeri korunur")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("dtmf_behavior: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
