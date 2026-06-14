#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codec_behavior_test.py — WBS 2.2.2 Codec yönetimi davranış kapısı (T1–T6)

stdlib-only, bağımsız. codec_probe.py çekirdeğini import edip codec pazarlığı (narrowband-first) /
zincir analizi (resample/transcode hop) / minimal-DP / gereksiz dönüşüm tespiti / U-dönüşü /
stage-native tutarlılığı davranışlarını doğrular (jitter_behavior_test deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import codec_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CAT = P._catalog(SPEC)


def S(stage, codec, native=None):
    return {"stage": stage, "codec": codec, "native": native or [codec]}


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — pazarlık: ortak codec offer tercih sırası + narrowband-first (C2)
    check(P.negotiate(CAT, ["PCMU", "PCMA"], ["PCMA", "PCMU"]) == "PCMU",
          "T1 ortak codec offer tercih sırası (PCMU)")
    check(P.negotiate(CAT, ["OPUS_WB", "PCMU", "PCMA"], ["PCMU", "PCMA", "OPUS_WB"]) == "PCMU",
          "T1 narrowband-first: 16kHz Opus-WB yerine 8kHz PCMU (resample kaçınır)")
    check(P.negotiate(CAT, ["OPUS_NB", "PCMU"], ["OPUS_NB", "PCMU"]) == "OPUS_NB",
          "T1 Opus-NB 8kHz dar bant ortak → passthrough")

    # T2 — pazarlık reddetmeleri (C11): ortak yok + tanınmayan codec
    check(P._raises(lambda: P.negotiate(CAT, ["OPUS_WB"], ["PCMU"])),
          "T2 ortak codec yok → UNAVAILABLE")
    check(P._raises(lambda: P.negotiate(CAT, ["G729"], ["PCMU"])),
          "T2 tanınmayan codec → INVALID_REQUEST")

    # T3 — minimal-DP alt sınırları (uçlar pinned, iç native)
    allp = [["PCMU"], ["PCMU", "L16_8K"], ["PCMU"]]
    check(P._minimal(CAT, allp, "any") == 0, "T3 passthrough → minimal 0 dönüşüm")
    forced = [["PCMU"], ["PCMU", "L16_8K", "L16_16K"], ["L16_16K"]]
    check(P._minimal(CAT, forced, "resample") == 1, "T3 zorunlu 16kHz STT → minimal 1 resample")
    check(P._minimal(CAT, forced, "transcode") == 1, "T3 zorunlu L16 → minimal 1 transcode")

    # T4 — passthrough zincir: 0 dönüşüm, tüm kapılar geçer (C3/C4/C5)
    cp = P.analyze_chain(CAT, [
        S("pstn", "PCMU", ["PCMU", "PCMA"]),
        S("mgw", "PCMU", ["PCMU", "PCMA", "L16_8K"]),
        S("stt", "PCMU", ["PCMU", "L16_8K"]),
    ])
    check(cp["conversions"] == 0 and cp["resample_points"] == 0 and cp["transcode_hops"] == 0,
          "T4 passthrough 0 dönüşüm")
    check(cp["unnecessary_resamples"] == 0 and cp["unnecessary_transcodes"] == 0,
          "T4 passthrough gereksiz dönüşüm 0")
    check(all(ok for ok, _ in P.evaluate(SPEC, CAT, "PCMU", cp)), "T4 passthrough tüm kapıları geçer")

    # T4b — tek kontrollü resample (16kHz STT) geçer: gereksiz 0, resample_points 1 (C5)
    c1 = P.analyze_chain(CAT, [
        S("pstn", "PCMU", ["PCMU"]),
        S("mgw", "PCMU", ["PCMU", "L16_8K", "L16_16K"]),
        S("stt16", "L16_16K", ["L16_16K"]),
    ])
    check(c1["resample_points"] == 1 and c1["unnecessary_resamples"] == 0,
          "T4b tek kontrollü resample: 1 nokta, gereksiz 0")
    check(all(ok for ok, _ in P.evaluate(SPEC, CAT, "PCMU", c1)), "T4b tek-resample kapıları geçer")

    # T5 — gereksiz transcode (µ→A→µ U-dönüşü) tespit + kapı eler (C3/C6)
    cr = P.analyze_chain(CAT, [
        S("pstn", "PCMU", ["PCMU", "PCMA"]),
        S("sbc", "PCMA", ["PCMU", "PCMA"]),
        S("mgw", "PCMU", ["PCMU", "PCMA"]),
        S("stt", "PCMU", ["PCMU"]),
    ])
    check(cr["transcode_hops"] == 2 and cr["unnecessary_transcodes"] == 2,
          "T5 2 gereksiz transcode (minimal 0)")
    check(cr["encoding_uturn"], "T5 µ→A→µ encoding U-dönüşü")
    check(not all(ok for ok, _ in P.evaluate(SPEC, CAT, "PCMU", cr)), "T5 gereksiz transcode kapı eler")

    # T6 — çift/U-dönüşü resample tespit + kapı eler (C4/C5/C6)
    cd = P.analyze_chain(CAT, [
        S("pstn", "PCMU", ["PCMU"]),
        S("mgw", "L16_16K", ["PCMU", "L16_8K", "L16_16K"]),
        S("orch", "L16_8K", ["L16_8K", "L16_16K"]),
        S("stt16", "L16_16K", ["L16_16K"]),
    ])
    check(cd["resample_points"] == 3 and cd["rate_uturn"], "T6 3 resample + rate U-dönüşü")
    check(cd["unnecessary_resamples"] >= 2, "T6 gereksiz resample ≥2 (minimal 1)")
    check(not all(ok for ok, _ in P.evaluate(SPEC, CAT, "PCMU", cd)), "T6 çift-resample kapı eler")

    # T6b — stage-native tutarlılığı (C8): working codec native değilse reddet
    check(P._raises(lambda: P.analyze_chain(CAT, [
        S("a", "PCMU", ["PCMU"]),
        {"stage": "b", "codec": "L16_16K", "native": ["PCMU", "L16_8K"]}])),
        "T6b working codec native değil → reddedilir")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("codec_behavior: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
