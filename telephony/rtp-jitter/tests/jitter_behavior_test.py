#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jitter_behavior_test.py — WBS 2.2.1 RTP/jitter buffer davranış kapısı (T1–T6)

stdlib-only, bağımsız. rtp_jitter_probe.py çekirdeğini import edip wrap-güvenli RTP aritmetiği /
adaptif derinlik / reorder absorbe / kayıp concealment / geç-paket atma / kadans sürekliliği
davranışlarını doğrular (dtmf_behavior_test deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rtp_jitter_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CLOCK = SPEC["media_profile"]["sample_rate_hz"]
FRAME_MS = SPEC["media_profile"]["frame_ms"]
ADAPT = {"mode": "adaptive", "base_depth_ms": 40, "target_factor": 2.0,
         "min_depth_ms": 20, "max_depth_ms": 120, "rfc3550_jitter_gain": 0.0625}


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — wrap-güvenli RTP seri-sayı/timestamp aritmetiği (J9)
    check(P.seq_diff(0, 65535) == 1, "T1 seq 65535→0 farkı +1 (wrap)")
    check(P.seq_diff(65535, 0) == -1, "T1 seq 0→65535 farkı -1 (wrap)")
    check(P.ts_diff(160, (1 << 32) - 160) == 320, "T1 ts wrap +320 örnek")
    for d in (1, 100, 16000):
        check(P.seq_diff((d) % (1 << 16), 0) == d if d < (1 << 15) else True, "T1 seq fark %d" % d)

    # T2 — RFC 3550 jitter: temiz akış≈0, dalgalı akış>0; monotonik artış (J7)
    clean = P._stream(20)
    check(P.rfc3550_jitter(clean, CLOCK) < 1e-3, "T2 temiz akış jitter≈0")
    j_small = P.rfc3550_jitter(P._stream(20, jitter_fn=lambda i: 5.0 if i % 2 else 0.0), CLOCK)
    j_big = P.rfc3550_jitter(P._stream(20, jitter_fn=lambda i: 20.0 if i % 2 else 0.0), CLOCK)
    check(0 < j_small < j_big, "T2 jitter dalgalanmayla artar (5ms<20ms)")

    # T3 — adaptif derinlik: base'ten büyür, [min,max] clamp (J2)
    m0 = P.simulate_jitter_buffer(clean, ADAPT, CLOCK, FRAME_MS)
    check(abs(m0["nominal_depth_ms"] - 40.0) < 0.5, "T3 düşük jitter → derinlik≈base 40ms")
    m_hi = P.simulate_jitter_buffer(P._stream(30, jitter_fn=lambda i: (i % 5) * 50.0), ADAPT, CLOCK, FRAME_MS)
    check(m_hi["nominal_depth_ms"] == 120.0, "T3 aşırı jitter → derinlik max 120ms'e clamp")
    fixed = dict(ADAPT, mode="fixed", base_depth_ms=30)
    m_fx = P.simulate_jitter_buffer(P._stream(20, jitter_fn=lambda i: 30.0 if i % 2 else 0.0), fixed, CLOCK, FRAME_MS)
    check(m_fx["nominal_depth_ms"] == 30.0, "T3 fixed mod jitter'a tepki vermez (sabit 30ms)")

    # T4 — reorder absorbe: komşu takas derinlik içinde doğru sırada oynatılır (J1)
    ro = P.simulate_jitter_buffer(P._stream(20, reorder_swaps=[(7, 8)]), ADAPT, CLOCK, FRAME_MS)
    check(ro["reordered"] >= 1 and ro["reorder_absorbed"], "T4 komşu reorder sayıldı + absorbe")
    check(ro["lost"] == 0 and ro["late_discarded"] == 0, "T4 reorder'da kayıp/geç yok")

    # T5 — kayıp tespiti + concealment + kadans sürekliliği (J5/J6)
    loss = P.simulate_jitter_buffer(P._stream(40, drop=(5, 15, 25)), ADAPT, CLOCK, FRAME_MS)
    check(loss["lost"] == 3 and loss["total_slots"] == 40, "T5 3 kayıp slot tespit edildi")
    check(abs(loss["concealment_ratio"] - 0.075) < 1e-9, "T5 concealment oranı 3/40=%7.5")
    check(loss["played"] + loss["concealed"] == loss["total_slots"], "T5 oynat+gizlenen = toplam slot")
    check(loss["cadence_continuous"], "T6 kayıpta kadans sürekli (her slot bir çerçeve)")

    # T6 — geç paket atılır; sığ fixed buffer jitter'ı sönümleyemez ama kadans sürekli (J4/J6)
    late = P.simulate_jitter_buffer(
        P._stream(30, jitter_fn=lambda i: 70.0 if i % 3 == 1 else 0.0),
        dict(ADAPT, mode="fixed", base_depth_ms=20), CLOCK, FRAME_MS)
    check(late["late_discarded"] > 0, "T6 sığ buffer'da geç paketler atılır (J4)")
    check(late["cadence_continuous"], "T6 geç atımda bile kadans sürekli (J6)")
    # geç atılan = concealed'a dahil → loss_rate ayrı, concealment birleşik
    check(late["concealed"] == late["lost"] + late["late_discarded"], "T6 concealed = kayıp + geç-atma")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("jitter_behavior: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
