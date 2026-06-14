#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tts_fallback_behavior_test.py — WBS 4.3.2 davranış kapısı (T1–T10)

Deterministik TTS fallback switcher'ın (tts_fallback_probe.TtsFallbackRuntime) iki somut TTS sağlayıcı
(≥2/kategori) ÜZERİNDEKİ fallback ANAHTARLAMA + SES KARAKTERİ TUTARLILIĞI davranışını HARD kapılara
(T1–T10) karşı doğrular: failover + resynth continuation + eşdeğer ses + barge-in + deterministic flow +
seçici tetik + histerezis + metering. Sunucu/credential GEREKMEZ; stdlib-only.

Koş: python3 tests/tts_fallback_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tts_fallback_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — FAILOVER: geçici hata/timeout → ikincile geçiş, çağrı sürer (FR-TTS-008/SAD §8.3)")
m = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
            P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"), P._end(2000)])
check(m["failovers"] == 1 and m["utterance_lost"] == 0, "birincil timeout → 1 failover, in-flight söz kaybolmadı")
check(m["active_at_end"] == "secondary", "ikincil aktif kaldı (çağrı sürer)")
m_off = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
                P._end(2000)], failover=False)
check(m_off["utterance_lost"] >= 1 and not gates_pass(m_off), "failover kapalı → söz kaybı, T1 eler")

print("T2 — RESYNTH CONTINUATION: kalan metin ikincide yeniden sentezlenir, çalınmış tekrar yok (FR-TTS-008)")
m = P._run([P._start(0), P._speak(100, "u1", 35, 600, remaining=50), P._err(700, "provider_timeout", "u1"),
            P._speak(1000, "u1", 50, 820, voice="B-tr-f-warm"), P._complete(1900, "u1"), P._end(3000)])
check(m["resynth_chars_total"] == 50.0 and m["unspoken_lost"] == 0 and m["resynth_replayed_spoken"] == 0,
      "50 char kalan resynth + zaten çalınmış metin tekrar seslendirilmedi")
m_nr = P._run([P._start(0), P._speak(100, "u1", 35, 600, remaining=50), P._err(700, "provider_timeout", "u1"),
               P._end(2000)], resynth=False)
check(m_nr["unspoken_lost"] >= 1 and not gates_pass(m_nr), "resynth kapalı → kalan metin kaybı, T2 eler")
m_rs = P._run([P._start(0), P._speak(100, "u1", 35, 600, remaining=40), P._err(700, "provider_timeout", "u1"),
               P._speak(1000, "u1", 40, 700, voice="B-tr-f-warm"), P._complete(1700, "u1"), P._end(3000)],
              resume_from_boundary=False)
check(m_rs["resynth_replayed_spoken"] >= 35 and not gates_pass(m_rs),
      "kesme noktasından devam etmez → zaten çalınmış metin tekrar (kullanıcı baştan duyar), T2/T4 eler")

print("T3 — SWITCH OVERHEAD: anahtarlama gecikmesi sınırlı (NFR 10.1/SAD §20)")
m = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
            P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"), P._end(2000)])
check(m["switch_overhead_p95_ms"] is not None and m["switch_overhead_p95_ms"] <= GATES["switch_overhead_p95_ms"],
      "switch overhead P95 ≤ 200 ms (teardown+setup+first_byte+resynth)")
slow = {"provider_id": "tts-stream-C", "features": ["streaming"], "sample_rates": [8000],
        "data_retention": "NONE", "voices": ["C-x"],
        "setup_ms": 260, "teardown_ms": 90, "first_byte_ms": 300, "cancel_ms": 320, "resynth_rtf": 1.10}
m_slow = P._run([P._start(0), P._speak(100, "u1", 50, 900, remaining=60), P._err(700, "provider_timeout", "u1"),
                 P._speak(1100, "u1", 60, 1000), P._complete(2100, "u1"), P._end(3000)],
                secondary=slow, veq={"voice-tr-warm": {"tts-stream-A": "A-tr-f-warm", "tts-stream-C": "C-x"}})
check(m_slow["switch_overhead_max_ms"] > 200 and not gates_pass(m_slow), "yavaş ikincil → overhead>200ms, T3 eler")

print("T4 — NO DUPLICATION / SINGLE STREAM: tek aktif stream + dup-speech yok (FR-TTS-002)")
m = P._run([P._start(0), P._speak(100, "u1", 40, 700, remaining=0), P._complete(800, "u1"), P._end(2000)])
check(m["duplicate_speech"] == 0 and m["concurrent_active_max"] == 1, "dup-speech yok + her an tek aktif sağlayıcı")
m_dup = P._run([P._start(0), P._speak(100, "u1", 40, 700, remaining=0), P._complete(800, "u1"),
                P._complete(900, "u1"), P._end(2000)], dedup=False)
check(m_dup["duplicate_speech"] >= 1 and not gates_pass(m_dup), "dedup kapalı → çift seslendirme, T4 eler")

print("T5 — ≥2 SPI-uyumlu TTS sağlayıcı + EŞDEĞER ses (ADR-002 / BRD §19 (1) / FR-TTS-009)")
cfg = P._load(P.PROFILES_CFG)
conformant = [p for p in cfg.get("providers", []) if P._provider_conformant(p)]
check(len(conformant) >= GATES["min_providers"],
      "config ≥2 SPI-uyumlu sağlayıcı (streaming+barge_in_cancel+pronunciation_dict + 8 kHz)")
for prof in cfg.get("profiles", []):
    check(prof["primary_provider"] != prof["secondary_provider"],
          "profil %s primary≠secondary (bağımsız fallback)" % prof["name"])
    dv = prof.get("default_voice")
    entry = prof.get("voice_equivalence", {}).get(dv, {})
    check(entry.get(prof["primary_provider"]) and entry.get(prof["secondary_provider"]),
          "profil %s default_voice eşdeğer ses primary+secondary'de tanımlı (FR-TTS-009)" % prof["name"])

print("T6 — DETERMINISTIC FLOW / NEVER DROP: her iki düşerse aktarım, çağrı düşmez (BRD §19 (4))")
m = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
            P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"),
            P._speak(2000, "u2", 30, 500, remaining=20), P._err(2300, "provider_5xx", "u2"), P._end(4000, "transfer")])
check(m["deterministic_flow_count"] == 1 and m["dropped_call"] == 0, "ikincil de düştü → deterministik akış, çağrı düşmedi")
m_drop = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
                 P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"),
                 P._speak(2000, "u2", 30, 500, remaining=20), P._err(2300, "provider_5xx", "u2"), P._end(4000)],
                deterministic_flow=False)
check(m_drop["dropped_call"] >= 1 and not gates_pass(m_drop), "deterministik akış kapalı → çağrı düştü, T6 eler")

print("T7 — SELECTIVE TRIGGER + ERROR NORMALIZED: yalnız geçici sınıf failover (FR-TOOL-008)")
m = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "auth_failure", "u1"),
            P._end(2000, "transfer")])
check(m["failovers"] == 0 and m["improper_failover"] == 0, "AUTH geçici değil → failover yok (boşuna anahtarlama yok)")
check(m["deterministic_flow_count"] == 1, "AUTH → deterministik akış (güvenli degrade)")
m_imp = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "auth_failure", "u1"),
                P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"), P._end(2000)],
               selective_trigger=False)
check(m_imp["improper_failover"] >= 1 and not gates_pass(m_imp), "seçici tetik kapalı → boşuna failover, T7 eler")

print("T8 — VOICE CONSISTENCY: voiceId sabit + fallback eşdeğer ses (FR-TTS-009) — görev başlığı")
m = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
            P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"), P._end(2000)])
check(m["voice_inconsistent"] == 0 and m["voice_switch_unmapped"] == 0 and m["voice_switches_mapped"] == 1,
      "fallback'te eşdeğer ses (A-tr-f-warm→B-tr-f-warm) → karakter tutarlı")
check(m["effective_voice_at_end"] == "B-tr-f-warm", "ikincil eşdeğer fiziksel ses aktif (karakter korundu)")
m_nv = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
               P._speak(700, "u1", 20, 320), P._complete(1000, "u1"), P._end(2000)], preserve_voice=False)
check(m_nv["voice_switch_unmapped"] >= 1 and not gates_pass(m_nv),
      "eşdeğer ses yok sayıldı → fallback'te farklı ses → karakter kırıldı, T8 eler")
m_drift = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=0, voice="A-tr-m-other"),
                  P._complete(700, "u1"), P._end(2000)])
check(m_drift["voice_inconsistent"] >= 1 and not gates_pass(m_drift),
      "aynı sağlayıcıda mid-call voiceId drift → karakter tutarsız, T8 eler")

print("T9 — BARGE-IN PRESERVED: anahtarlama sırasında/sonrasında cancel ≤200ms + kesme sonrası ses yok (FR-TTS-005)")
m = P._run([P._start(0), P._speak(100, "u1", 40, 800, remaining=30), P._barge(400, "u1"),
            P._speak(500, "u1", 30, 400), P._end(2000)])
check(m["barge_in_cancel_p95_ms"] is not None and m["barge_in_cancel_p95_ms"] <= GATES["barge_in_cancel_p95_ms"]
      and m["chunk_after_cancel"] == 0, "barge-in cancel ≤200ms + kesme sonrası ses chunk'ı yok")
m_bf = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=40), P._err(400, "provider_timeout", "u1"),
               P._speak(700, "u1", 40, 700, voice="B-tr-f-warm"), P._barge(900, "u1"), P._end(2000)])
check(m_bf["failovers"] == 1 and m_bf["barge_in_cancel_max_ms"] == 60.0,
      "failover sonrası ikincil sağlayıcıda da barge-in kesilir (cancel_ms=60)")
m_nc = P._run([P._start(0), P._speak(100, "u1", 40, 800, remaining=30), P._barge(400, "u1"),
               P._speak(500, "u1", 30, 400), P._end(2000)], honor_cancel=False)
check(m_nc["chunk_after_cancel"] >= 1 and not gates_pass(m_nc), "kesme onurlanmadı → talk-over, T9 eler")

print("T10 — NO FLAP + METERING + RESIDENCY: histerezis + segment metering (FR-BIL-002/NFR 10.7)")
m = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
            P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"),
            P._speak(2000, "u2", 30, 500, remaining=20), P._err(2300, "provider_5xx", "u2"), P._end(4000, "transfer")])
check(m["flap_count"] == 0, "histerezis: ikincile geçince geri salınım yok (sticky secondary)")
check(m["usage_records"] == m["provider_segments"] == 2, "her sağlayıcı segmenti UsageRecord (CHARACTERS) üretti")
m_flap = P._run([P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "provider_timeout", "u1"),
                 P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"),
                 P._speak(2000, "u2", 30, 500, remaining=20), P._err(2300, "provider_timeout", "u2"),
                 P._complete(2700, "u2"), P._end(4000)], hysteresis=False)
check(m_flap["flap_count"] >= 1 and not gates_pass(m_flap), "histerezis kapalı → flap, T10 eler")

print("T-determinizm — aynı olay-akışı birebir aynı metrik (random yok)")
ev = [P._start(0), P._speak(100, "u1", 30, 500, remaining=20), P._err(400, "circuit_open", "u1"),
      P._speak(700, "u1", 20, 320, voice="B-tr-f-warm"), P._complete(1000, "u1"), P._end(2000)]
check(P._run(ev) == P._run(ev), "deterministik: iki koşu birebir aynı")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\ntts_fallback_behavior_test: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
