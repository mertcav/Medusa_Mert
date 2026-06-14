#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
framing_behavior_test.py — WBS 2.1.3 medya çerçeveleme davranış kapısı (T1–T5)

stdlib-only, credential-free. Managed CPaaS μ-law/8kHz çerçeveleme aritmetiğini ve
base64 medya payload round-trip'ini doğrular (FR-RES-008). Sağlayıcı/sunucu gerektirmez.
"""
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = json.load(open(os.path.join(HERE, "..", "cpaas-spec.json"), encoding="utf-8"))


def run():
    R = []

    def t(ok, label):
        R.append((bool(ok), label))

    mp = SPEC["media_profile"]
    sr = mp["sample_rate_hz"]
    fm = mp["frame_ms"]

    # T1: μ-law 8kHz/20ms çerçeve = 160 bayt (8000 * 0.020 * 1 bayt)
    expected = int(sr * (fm / 1000.0))
    t(expected == 160 and mp["frame_bytes_mulaw"] == 160, "T1 μ-law 8kHz/20ms = 160 bayt")

    # T2: 50 fps = 1000/20
    t(mp["frames_per_sec"] == 1000 // fm == 50, "T2 50 fps (1000/20)")

    # T3: base64 medya payload round-trip (sağlayıcı 'media' biçimi)
    raw = bytes([0xFF] * 160)  # μ-law sessizlik vekili
    payload = base64.b64encode(raw).decode("ascii")
    back = base64.b64decode(payload)
    t(back == raw and len(back) == 160, "T3 base64 payload round-trip 160 bayt")

    # T4: transcode kaçınma — STT/TTS 8kHz native varsayımı, ≤1 resample noktası
    t(mp["no_transcode"] is True and mp["resample_points_max"] <= 1,
      "T4 no-transcode + ≤1 resample (FR-RES-008)")

    # T5: 1 sn ses = 50 çerçeve = 8000 bayt (μ-law)
    one_sec_frames = mp["frames_per_sec"]
    one_sec_bytes = one_sec_frames * mp["frame_bytes_mulaw"]
    t(one_sec_frames == 50 and one_sec_bytes == 8000, "T5 1 sn = 50 çerçeve = 8000 bayt")

    passed = sum(1 for ok, _ in R if ok)
    for ok, label in R:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("framing_behavior_test: %d/%d PASS" % (passed, len(R)))
    return 0 if passed == len(R) else 1


if __name__ == "__main__":
    sys.exit(run())
