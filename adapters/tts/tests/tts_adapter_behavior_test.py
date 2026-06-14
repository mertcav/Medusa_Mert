#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_adapter_behavior_test.py — WBS 4.2.3 davranış kapısı (T1–T8)

Deterministik TtsAdapter'ın (tts_adapter_probe.TtsAdapterRuntime) iki somut sağlayıcı (≥2/kategori)
arkasındaki SPI-uyum davranışını HARD kapılara (P1–P8) karşı doğrular: streaming, pronunciation
dictionary, cancel (barge-in) + ses tutarlılığı + cache + metering. Sunucu/credential GEREKMEZ;
stdlib-only. runtime/ + telephony/ davranış-testi disipliniyle aynı.

Koş: python3 tests/tts_adapter_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tts_adapter_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — streaming first-byte + akış-önce (P1, FR-TTS-002/SAD §20)")
m = P._run([P._req(0, chars=60), P._end(50)])
check(m["full_buffered"] == 0, "ilk ses paketi tüm sentez bitmeden akar (akış-önce)")
check(m["first_byte_p95_ms"] <= GATES["first_byte_p95_ms"], "first-byte P95 ≤ 200 ms (SAD §20 TTS kalemi)")
m_buf = P._run([P._req(0, chars=80), P._end(20)], streaming=False)
check(m_buf["full_buffered"] >= 1 and not gates_pass(m_buf), "full-buffer → first-byte=sentez süresi, P1 eler")

print("T2 — cancel / barge-in ≤200ms + kesme sonrası ses yok (P2, FR-TTS-005/NFR 10.1)")
m = P._run([P._req(0), P._cancel(40), P._end(50, reason="cancelled")])
check(m["cancel_p95_ms"] <= GATES["barge_in_cancel_p95_ms"], "cancel→susma P95 ≤ 200 ms")
check(m["chunk_after_cancel"] == 0, "kesme sonrası ses chunk'ı yok (talk-over yok)")
m_slow = P._run([P._req(0), P._cancel(40), P._end(50, reason="cancelled")], cancel_responsive=False)
check(m_slow["chunk_after_cancel"] >= 1 and not gates_pass(m_slow), "yavaş cancel → kesme sonrası ses, P2 eler")

print("T3 — pronunciation dictionary yapısal alanlara uygulanır (P3, FR-TTS-004)")
fields = [{"type": "number", "chars": 11}, {"type": "date", "chars": 10},
          {"type": "currency", "chars": 9}, {"type": "name", "chars": 12}]
m = P._run([P._req(0, fields=fields, dict_id="pd-tr-1"), P._end(80)])
check(m["structured_total"] == 4 and m["pronunciation_applied"] == 4, "4 yapısal alan sözlükle sentezlendi")
check(m["unhandled_structured"] == 0, "hiçbir yapısal alan sözlüksüz kalmadı")
m_nd = P._run([P._req(0, fields=fields, dict_id=None), P._end(80)])
check(m_nd["unhandled_structured"] >= 4 and not gates_pass(m_nd), "pronunciationDictId yok → P3 eler")

print("T4 — akış sürekliliği / ölü hava yok (P4, FR-RES-009)")
m = P._run([P._req(0, chars=60), P._end(60)])
check(m["underrun"] == 0, "RTF<1 → tampon boşalmaz, ölü hava yok")
m_dead = P._run([P._req(0, chars=60), P._end(60)], realtime=False)
check(m_dead["underrun"] >= 1 and not gates_pass(m_dead), "RTF≥1 → ölü hava, P4 eler")

print("T5 — ≥2 SPI-uyumlu sağlayıcı (P5, FR-TTS-001/ADR-002)")
cfg = P._load(P.PROFILES_CFG)
conformant = [p for p in cfg.get("providers", []) if P._provider_conformant(p)]
check(len(conformant) >= 2, "config'te ≥2 uyumlu sağlayıcı (streaming+barge_in_cancel+pronunciation_dict + 8 kHz)")
pb = P._provider_by_id(cfg, "tts-stream-B")
mb = P._run([P._req(0, voice="B-tr-f-07"), P._cancel(40), P._end(50, reason="cancelled")], provider=pb)
check(mb["provider_id"] == "tts-stream-B" and gates_pass(mb), "ikinci adapter (B) de tüm kapıları geçer")

print("T6 — ses karakteri tutarlılığı + fallback eşdeğer-ses (P6, FR-TTS-009)")
m = P._run([P._req(0, req_id="a", voice="A-tr-f-01"), P._end(50, req_id="a"),
            P._req(100, req_id="b", voice="B-tr-f-07", provider="tts-stream-B", equiv=True), P._end(150, req_id="b")])
check(m["voice_inconsistent"] == 0, "haritalı eşdeğer ses ile karakter korunur (4.3.2 sınır)")
m_drift = P._run([P._req(0, req_id="a", voice="A-tr-f-01"), P._end(50, req_id="a"),
                  P._req(100, req_id="b", voice="A-tr-m-02", provider="tts-stream-B"), P._end(150, req_id="b")])
check(m_drift["voice_inconsistent"] >= 1 and not gates_pass(m_drift), "haritasız ses değişimi → P6 eler")

print("T7 — cache (statik anons) + metering + 8 kHz (P7/P8, FR-TTS-010/FR-BIL-002/FR-RES-008)")
m = P._run([P._req(0, req_id="c", cached=True), P._end(50, req_id="c")])
check(m["cache_hits"] == 1 and m["cache_first_byte_max_ms"] <= GATES["cache_first_byte_max_ms"],
      "cache-hit first-byte ~0 (yeniden sentez yok)")
check(m["usage_records"] == m["requests_total"], "her synthesize UsageRecord (CHARACTERS) üretir")
m_sr = P._run([P._req(0, sr=16000), P._end(50)])
check(m_sr["sample_rate_mismatch"] >= 1 and not gates_pass(m_sr), "8 kHz dışı sample rate → P8 eler")

print("T8 — hata normalizasyonu + determinizm (P8/P10, FR-TOOL-008)")
m = P._run([P._req(0), P._end(50, reason="error", tax="UNAVAILABLE")])
check(m["errors_normalized"] == m["errors_seen"] == 1, "provider_5xx → ErrorTaxonomy UNAVAILABLE (API §11.6)")
m_raw = P._run([P._req(0), P._end(50, reason="error", tax="raw-503")], normalize_errors=False)
check(m_raw["errors_normalized"] == 0 and not gates_pass(m_raw), "ham sağlayıcı kodu normalize edilmedi → P8 eler")
seq = [P._req(0, fields=fields), P._cancel(40), P._end(50, reason="cancelled")]
check(P._run(seq) == P._run(seq), "determinizm: birebir aynı metrik (random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nbehavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
