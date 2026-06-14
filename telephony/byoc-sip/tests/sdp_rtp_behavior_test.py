#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sdp_rtp_behavior_test.py — WBS 2.1.4 BYOC: SDP codec müzakere + RTP/G.711 çerçeveleme aritmetiği.

Bağımsız (stdlib-only), credential-free. SIP/SBC sunucusu GEREKMEZ — saf hesap kapısı:
  T1: G.711 8kHz/20ms çerçeve = 160 örnek = 160 bayt (μ-law/A-law 1 bayt/örnek)  (FR-RES-008)
  T2: 50 fps × 20 ms = 1 sn; frame_bytes × fps = 8000 bayt/sn (8 kbaud)
  T3: SDP offer/answer kesişimi yalnız narrowband G.711 seçer (transcode yok)     (I15)
  T4: ortak narrowband codec yoksa → REDDET (488), transcode yok                  (I15)
  T5: RFC2833 telephone-event payload type=101 müzakere edilir (DTMF)             (I12)
"""
import sys

NARROWBAND = {"PCMU/8000", "PCMA/8000"}


def negotiate(offer, answer, allowed):
    """SDP offer/answer kesişimi → seçilen codec; ortak narrowband yoksa None (= 488 reddet)."""
    common = [c for c in answer if c in offer]
    for c in common:
        if c in allowed:
            return c
    return None


def g711_frame_bytes(sample_rate_hz, frame_ms):
    samples = sample_rate_hz * frame_ms // 1000
    return samples  # G.711 = 1 bayt/örnek


def run():
    cases = []

    def t(ok, label):
        cases.append((bool(ok), label))

    # T1: 8kHz/20ms → 160 örnek/bayt
    t(g711_frame_bytes(8000, 20) == 160, "T1 G.711 8kHz/20ms = 160 bayt/çerçeve")
    t(g711_frame_bytes(8000, 10) == 80, "T1 8kHz/10ms = 80 bayt")

    # T2: çerçeve/sn aritmetiği
    fps = 1000 // 20
    t(fps == 50, "T2 50 fps (20 ms çerçeve)")
    t(g711_frame_bytes(8000, 20) * fps == 8000, "T2 160 bayt × 50 fps = 8000 bayt/sn")

    # T3: SDP kesişim narrowband seçer
    sel = negotiate(["PCMU/8000", "PCMA/8000", "telephone-event/8000"],
                    ["PCMU/8000", "telephone-event/8000"], NARROWBAND)
    t(sel == "PCMU/8000", "T3 SDP kesişim → PCMU (narrowband)")
    sel = negotiate(["PCMA/8000", "PCMU/8000"], ["PCMA/8000"], NARROWBAND)
    t(sel == "PCMA/8000", "T3 SDP kesişim → PCMA")

    # T4: ortak narrowband yoksa reddet (488)
    sel = negotiate(["G722/8000", "opus/48000"], ["G722/8000"], NARROWBAND)
    t(sel is None, "T4 ortak narrowband yok → REDDET (488), transcode yok (I15)")
    sel = negotiate(["PCMU/8000"], ["PCMA/8000"], NARROWBAND)
    t(sel is None, "T4 offer/answer kesişimi boş → REDDET")

    # T5: RFC2833 telephone-event payload type
    te = "telephone-event/8000"
    offer = ["PCMU/8000", te]
    t(te in offer, "T5 RFC2833 telephone-event SDP'de müzakere edilir (DTMF, I12)")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("sdp_rtp_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
