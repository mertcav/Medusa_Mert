#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stt_fallback_behavior_test.py — WBS 4.3.1 davranış kapısı (T1–T8)

Deterministik STT fallback switcher'ın (stt_fallback_probe.SttFallbackRuntime) iki somut STT sağlayıcı
(≥2/kategori) ÜZERİNDEKİ fallback ANAHTARLAMA davranışını HARD kapılara (S1–S8) karşı doğrular:
failover + in-flight audio replay + deterministic flow + seçici tetik + histerezis + metering.
Sunucu/credential GEREKMEZ; stdlib-only. adapters/ + runtime/ davranış-testi disipliniyle aynı.

Koş: python3 tests/stt_fallback_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import stt_fallback_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — FAILOVER: geçici hata/timeout → ikincile geçiş, çağrı sürer (S1, FR-STT-008/SAD §8.3)")
m = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"),
            P._final(800, "u1"), P._end(2000)])
check(m["failovers"] == 1 and m["utterance_lost"] == 0, "birincil timeout → 1 failover, in-flight söz kaybolmadı")
check(m["active_at_end"] == "secondary", "ikincil aktif kaldı (çağrı sürer)")
m_off = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"), P._end(2000)],
               failover=False)
check(m_off["utterance_lost"] >= 1 and not gates_pass(m_off), "failover kapalı → söz kaybı, S1 eler")

print("T2 — AUDIO REPLAY: in-flight söz audio'su ikincile yeniden gönderilir (S2, API §11.2)")
m = P._run([P._start(0), P._audio(100, "u1", 400), P._audio(500, "u1", 400),
            P._err(900, "provider_timeout", "u1"), P._final(1300, "u1"), P._end(3000)])
check(m["audio_replayed_ms"] == 800.0 and m["missing_replay"] == 0, "800ms in-flight audio replay edildi")
m_nr = P._run([P._start(0), P._audio(100, "u1", 400), P._err(500, "provider_timeout", "u1"), P._end(2000)],
              replay=False)
check(m_nr["missing_replay"] >= 1 and not gates_pass(m_nr), "replay kapalı → in-flight söz kaybı, S2 eler")

print("T3 — SWITCH OVERHEAD: anahtarlama gecikmesi sınırlı (S3, NFR 10.1/SAD §20)")
m = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"),
            P._final(800, "u1"), P._end(2000)])
check(m["switch_overhead_p95_ms"] is not None and m["switch_overhead_p95_ms"] <= GATES["switch_overhead_p95_ms"],
      "switch overhead P95 ≤ 200 ms (teardown+setup+replay)")
slow = {"provider_id": "stt-stream-C", "features": ["streaming"], "sample_rates": [8000],
        "data_retention": "NONE", "final_ms": 240, "setup_ms": 260, "teardown_ms": 90, "replay_rtf": 1.10}
m_slow = P._run([P._start(0), P._audio(100, "u1", 500), P._err(700, "provider_timeout", "u1"),
                 P._final(1100, "u1"), P._end(3000)], secondary=slow)
check(m_slow["switch_overhead_max_ms"] > 200 and not gates_pass(m_slow), "yavaş ikincil → overhead>200ms, S3 eler")

print("T4 — NO DUPLICATION / SINGLE STREAM: tek aktif stream + dup-final yok (S4, FR-STT-002)")
m = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"),
            P._final(800, "u1"), P._end(2000)])
check(m["duplicate_final"] == 0 and m["concurrent_active_max"] == 1, "dup-final yok + her an tek aktif sağlayıcı")
m_dup = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"),
                P._final(800, "u1"), P._final(900, "u1"), P._end(2000)], dedup=False)
check(m_dup["duplicate_final"] >= 1 and not gates_pass(m_dup), "dedup kapalı → çift final, S4 eler")

print("T5 — ≥2 SPI-uyumlu STT sağlayıcı (S5, ADR-002 / BRD §19 (1))")
cfg = P._load(P.PROFILES_CFG)
conformant = [p for p in cfg.get("providers", []) if P._provider_conformant(p)]
check(len(conformant) >= GATES["min_providers"], "config ≥2 SPI-uyumlu sağlayıcı (streaming + 8 kHz)")
for prof in cfg.get("profiles", []):
    check(prof["primary_provider"] != prof["secondary_provider"],
          "profil %s primary≠secondary (bağımsız fallback)" % prof["name"])

print("T6 — DETERMINISTIC FLOW / NEVER DROP: her iki düşerse aktarım, çağrı düşmez (S6, BRD §19 (4))")
m = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"), P._final(800, "u1"),
            P._audio(2000, "u2", 300), P._err(2300, "provider_5xx", "u2"), P._end(4000, "transfer")])
check(m["deterministic_flow_count"] == 1 and m["dropped_call"] == 0, "ikincil de düştü → deterministik akış, çağrı düşmedi")
m_drop = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"), P._final(800, "u1"),
                 P._audio(2000, "u2", 300), P._err(2300, "provider_5xx", "u2"), P._end(4000)],
                deterministic_flow=False)
check(m_drop["dropped_call"] >= 1 and not gates_pass(m_drop), "deterministik akış kapalı → çağrı düştü, S6 eler")

print("T7 — SELECTIVE TRIGGER + ERROR NORMALIZED: yalnız geçici sınıf failover (S7, FR-TOOL-008)")
m = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "auth_failure", "u1"), P._end(2000, "transfer")])
check(m["failovers"] == 0 and m["improper_failover"] == 0, "AUTH geçici değil → failover yok (boşuna anahtarlama yok)")
check(m["deterministic_flow_count"] == 1, "AUTH → deterministik akış (güvenli degrade)")
m_imp = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "auth_failure", "u1"), P._final(800, "u1"), P._end(2000)],
               selective_trigger=False)
check(m_imp["improper_failover"] >= 1 and not gates_pass(m_imp), "seçici tetik kapalı → boşuna failover, S7 eler")

print("T8 — NO FLAP + METERING + RESIDENCY: histerezis + segment metering (S8, FR-BIL-002/NFR 10.7)")
m = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"), P._final(800, "u1"),
            P._audio(2000, "u2", 300), P._err(2300, "provider_5xx", "u2"), P._end(4000, "transfer")])
check(m["flap_count"] == 0, "histerezis: ikincile geçince geri salınım yok (sticky secondary)")
check(m["usage_records"] == m["provider_segments"] == 2, "her sağlayıcı segmenti UsageRecord üretti")
m_flap = P._run([P._start(0), P._audio(100, "u1", 300), P._err(400, "provider_timeout", "u1"), P._final(800, "u1"),
                 P._audio(2000, "u2", 300), P._err(2300, "provider_timeout", "u2"), P._final(2700, "u2"), P._end(4000)],
                hysteresis=False)
check(m_flap["flap_count"] >= 1 and not gates_pass(m_flap), "histerezis kapalı → flap, S8 eler")

print("T-determinizm — aynı olay-akışı birebir aynı metrik (random yok)")
ev = [P._start(0), P._audio(100, "u1", 300), P._err(400, "circuit_open", "u1"), P._final(800, "u1"), P._end(2000)]
check(P._run(ev) == P._run(ev), "deterministik: iki koşu birebir aynı")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nstt_fallback_behavior_test: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
