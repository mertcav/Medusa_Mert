#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_fallback_behavior_test.py — WBS 4.3.3 davranış kapısı (T1–T10)

Deterministik LLM fallback switcher'ın (llm_fallback_probe.LlmFallbackRuntime) iki somut LLM sağlayıcı
(≥2/kategori) ÜZERİNDEKİ fallback ANAHTARLAMA davranışını HARD kapılara (L1–L8) karşı doğrular: failover +
context yeniden sunumu + mid-stream güvenli degrade + tool idempotency + deterministic flow + seçici tetik +
histerezis + metering + model/versiyon kaydı. Sunucu/credential GEREKMEZ; stdlib-only.

Koş: python3 tests/llm_fallback_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import llm_fallback_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — FAILOVER: geçici hata/timeout → fallback modele geçiş, çağrı sürer (L1, FR-LLM-010/SAD §9.1)")
m = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"),
            P._ft(550, "u1"), P._tc(900, "u1"), P._end(2000)])
check(m["failovers"] == 1 and m["turn_lost"] == 0, "birincil timeout → 1 failover, tur kaybolmadı")
check(m["active_at_end"] == "fallback", "fallback aktif kaldı (çağrı sürer)")
m_off = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"), P._end(2000)],
               failover=False)
check(m_off["turn_lost"] >= 1 and not gates_pass(m_off), "failover kapalı → tur kaybı, L1 eler")

print("T2 — CONTEXT RESUBMIT: ilk-token öncesi failover'da istek fallback'e yeniden sunulur (L2, FR-LLM-006)")
m = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"),
            P._ft(550, "u1"), P._tc(900, "u1"), P._end(2000)])
check(m["missing_context"] == 0 and m["system_prompt_mutation"] == 0, "context kaybı yok + system prompt korundu")
m_nr = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"), P._end(2000)],
              context_resubmission=False)
check(m_nr["missing_context"] >= 1 and not gates_pass(m_nr), "resubmit kapalı → context kaybı, L2 eler")
m_mut = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"),
                P._ft(550, "u1"), P._tc(900, "u1"), P._end(2000)], preserve_system_prompt=False)
check(m_mut["system_prompt_mutation"] >= 1 and not gates_pass(m_mut), "system prompt korunmadı → L2 eler (FR-LLM-006)")

print("T3 — MID-STREAM GÜVENLİĞİ: ilk token sonrası hata → sessiz yeniden istek yok (L3, FR-RES-009)")
m = P._run([P._start(0), P._ts(100, "u1"), P._ft(300, "u1"), P._err(450, "provider_5xx", "u1"),
            P._end(2000, "transfer")])
check(m["double_speak"] == 0 and m["mid_stream_degrade"] == 1, "ilk token sonrası → güvenli degrade, çift konuşma yok")
m_ds = P._run([P._start(0), P._ts(100, "u1"), P._ft(300, "u1"), P._err(450, "provider_5xx", "u1"),
               P._ft(700, "u1"), P._tc(1000, "u1"), P._end(2000)], mid_stream_safe=False)
check(m_ds["double_speak"] >= 1 and not gates_pass(m_ds), "mid-stream güvenlik kapalı → çift konuşma, L3 eler")

print("T4 — TOOL IDEMPOTENCY: yan etkili tool sonrası hata → yeniden yürütme yok (L4, FR-TOOL-009)")
m = P._run([P._start(0), P._ts(100, "u1"), P._tool(300, "u1", side=True), P._err(450, "provider_timeout", "u1"),
            P._end(2000, "transfer")])
check(m["double_tool_exec"] == 0 and m["mid_stream_degrade"] == 1, "yan etkili tool yeniden yürütülmedi")
m_dt = P._run([P._start(0), P._ts(100, "u1"), P._tool(300, "u1", side=True), P._err(450, "provider_timeout", "u1"),
               P._ft(700, "u1"), P._tc(1000, "u1"), P._end(2000)], tool_idempotency=False)
check(m_dt["double_tool_exec"] >= 1 and not gates_pass(m_dt), "idempotency kapalı → çift yan-etki, L4 eler")

print("T5 — SWITCH OVERHEAD + ≥2 SAĞLAYICI (L5, NFR 10.1/SAD §20, ADR-002)")
m = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"),
            P._ft(550, "u1"), P._tc(900, "u1"), P._end(2000)])
check(m["switch_overhead_p95_ms"] is not None and m["switch_overhead_p95_ms"] <= GATES["switch_overhead_p95_ms"],
      "switch overhead P95 ≤ 500 ms (teardown+fallback setup+ilk token)")
slow = {"provider_id": "llm-cloud-C", "features": ["streaming"], "no_train": False,
        "data_retention": "NONE", "setup_ms": 260, "teardown_ms": 90, "first_token_ms": 520}
m_slow = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"),
                 P._ft(900, "u1"), P._tc(1300, "u1"), P._end(3000)], secondary=slow)
check(m_slow["switch_overhead_max_ms"] > 500 and not gates_pass(m_slow), "yavaş fallback → overhead>500ms, L5 eler")
cfg = P._load(P.PROFILES_CFG)
conformant = [p for p in cfg.get("providers", []) if P._provider_conformant(p)]
check(len(conformant) >= GATES["min_providers"], "config ≥2 SPI-uyumlu sağlayıcı (streaming+tool_call+noTrain)")
for prof in cfg.get("profiles", []):
    check(prof["primary_provider"] != prof["secondary_provider"],
          "profil %s primary≠fallback (bağımsız fallback)" % prof["name"])

print("T6 — DETERMINISTIC FLOW / NEVER DROP: her iki düşerse aktarım, çağrı düşmez (L6, BRD §19 (4))")
m = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"), P._ft(550, "u1"), P._tc(900, "u1"),
            P._ts(2000, "u2"), P._err(2100, "provider_5xx", "u2"), P._end(4000, "transfer")])
check(m["deterministic_flow_count"] == 1 and m["dropped_call"] == 0, "fallback de düştü → deterministik akış, çağrı düşmedi")
m_drop = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"), P._ft(550, "u1"), P._tc(900, "u1"),
                 P._ts(2000, "u2"), P._err(2100, "provider_5xx", "u2"), P._end(4000)],
                deterministic_flow=False)
check(m_drop["dropped_call"] >= 1 and not gates_pass(m_drop), "deterministik akış kapalı → çağrı düştü, L6 eler")

print("T7 — SELECTIVE TRIGGER + ERROR NORMALIZED: yalnız geçici sınıf failover (L7, FR-TOOL-008)")
m = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "content_filter", "u1"), P._end(2000, "transfer")])
check(m["failovers"] == 0 and m["improper_failover"] == 0, "CONTENT_FILTERED model değiştirmez (politika/deterministik)")
m_q = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "quota_exceeded", "u1"), P._ft(550, "u1"), P._tc(900, "u1"), P._end(2000)])
check(m_q["failovers"] == 1, "QUOTA_EXCEEDED → fallback (ayrı sağlayıcı/ayrı kota)")
m_imp = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "auth_failure", "u1"), P._ft(550, "u1"), P._tc(900, "u1"), P._end(2000)],
               selective_trigger=False)
check(m_imp["improper_failover"] >= 1 and not gates_pass(m_imp), "seçici tetik kapalı → boşuna failover, L7 eler")

print("T8 — NO FLAP + METERING + MODEL/VERSİYON KAYDI (L8, FR-BIL-002/FR-LLM-011/NFR 10.7)")
m = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"), P._ft(550, "u1"), P._tc(900, "u1"),
            P._ts(2000, "u2"), P._err(2100, "provider_5xx", "u2"), P._end(4000, "transfer")])
check(m["flap_count"] == 0, "histerezis: fallback'e geçince geri salınım yok (sticky fallback)")
check(m["usage_records"] == m["provider_segments"] == 2 and m["model_versions_recorded"] == 2,
      "her model segmenti UsageRecord + model/versiyon kaydı üretti")
m_flap = P._run([P._start(0), P._ts(100, "u1"), P._err(200, "provider_timeout", "u1"), P._ft(550, "u1"), P._tc(900, "u1"),
                 P._ts(2000, "u2"), P._err(2100, "provider_timeout", "u2"), P._end(4000)],
                hysteresis=False)
check(m_flap["flap_count"] >= 1 and not gates_pass(m_flap), "histerezis kapalı → flap, L8 eler")
m_mv = P._run([P._start(0), P._ts(100, "u1"), P._ft(250, "u1"), P._tc(600, "u1"), P._end(1000)], record_model_version=False)
check(m_mv["model_versions_recorded"] == 0 and not gates_pass(m_mv), "model/versiyon kaydı kapalı → L8 eler (FR-LLM-011)")

print("T9 — ROUTING'TEN AYRI: fallback model seçmez, seçilen model düşünce kurtarır (L9, SAD §9)")
check(SPEC["placement"].get("routing_owned_by", "").startswith("5.1"),
      "routing/tiering 5.1-5.3'te; fallback (4.3.3) ondan ayrı (seam)")
check(SPEC["fallback"].get("switching_owned_by", "").startswith("4.3.3"),
      "fallback anahtarlama bu görevde; LlmAdapter (4.2.4) VARLIĞINI bekler")

print("T10 — determinizm: aynı olay-akışı birebir aynı metrik (random yok)")
ev = [P._start(0), P._ts(100, "u1"), P._err(200, "circuit_open", "u1"), P._ft(500, "u1"), P._tc(800, "u1"), P._end(2000)]
check(P._run(ev) == P._run(ev), "deterministik: iki koşu birebir aynı")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nllm_fallback_behavior_test: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
