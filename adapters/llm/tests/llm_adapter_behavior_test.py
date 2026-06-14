#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_adapter_behavior_test.py — WBS 4.2.4 davranış kapısı (T1–T8)

Deterministik LlmAdapter'ın (llm_adapter_probe.LlmAdapterRuntime) iki somut sağlayıcı (≥2/kategori)
arkasındaki SPI-uyum davranışını HARD kapılara (P1–P8) karşı doğrular: streaming token, schema-
doğrulamalı tool-call, token süreklilik + model tiering + no-train/residency + system prompt
değişmezliği + metering. Sunucu/credential GEREKMEZ; stdlib-only. runtime/ + telephony/ + adapters/tts/
davranış-testi disipliniyle aynı.

Koş: python3 tests/llm_adapter_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import llm_adapter_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — streaming token first-token + akış-önce (P1, FR-LLM-004/SAD §20)")
m = P._run([P._req(0, out_tok=80), P._end(50)])
check(m["full_buffered"] == 0, "ilk token tüm yanıt bitmeden akar (akış-önce)")
check(m["first_token_p95_ms"] <= GATES["first_token_p95_ms"], "first-token P95 ≤ 400 ms (SAD §20 LLM kalemi)")
m_buf = P._run([P._req(0, out_tok=90), P._end(20)], streaming=False)
check(m_buf["full_buffered"] >= 1 and not gates_pass(m_buf), "full-buffer → first-token=üretim süresi, P1 eler")

print("T2 — schema-doğrulamalı tool-call (P2, FR-LLM-008)")
m = P._run([P._req(0, expects_tool=True, tool_call=True), P._end(50)])
check(m["unhandled_tool"] == 0 and m["tool_calls_ok"] == 1, "kritik işlem schema-doğrulamalı tool-call ile (serbest metin değil)")
m_free = P._run([P._req(0, expects_tool=True, tool_call=False), P._end(50)])
check(m_free["unhandled_tool"] >= 1 and not gates_pass(m_free), "kritik tur serbest metinle → P2 eler")

print("T3 — token-arası süreklilik / stall yok (P3, FR-LLM-004/FR-RES-009)")
m = P._run([P._req(0), P._end(50)])
check(m["token_stall"] == 0, "token-arası boşluk eşik altında → akıcı (downstream TTS ölü hava yok)")
m_stall = P._run([P._req(0), P._end(50)], continuity=False)
check(m_stall["token_stall"] >= 1 and not gates_pass(m_stall), "token-arası boşluk eşik üstü → stall, P3 eler")

print("T4 — model tiering: ≥2 tier + küçük-tier sıkı kapı (P4, FR-LLM-013/SR-DEN-005)")
m = P._run([P._req(0, req_id="a", tier="small"), P._end(40, req_id="a"),
            P._req(100, req_id="b", tier="big"), P._end(140, req_id="b")])
check(len(m["tiers_seen"]) == 2 and m["small_tier_first_token_p95_ms"] <= GATES["small_tier_first_token_p95_ms"],
      "küçük+büyük tier; küçük-tier first-token ≤ 200 ms")
slow = dict(P.PROVIDER_A); slow["first_token_small_ms"] = 260
m_slow = P._run([P._req(0, tier="small"), P._end(40)], provider=slow)
check(m_slow["small_tier_first_token_p95_ms"] > 200 and not gates_pass(m_slow), "yavaş küçük-tier → P4 eler")

print("T5 — ≥2 SPI-uyumlu sağlayıcı (P5, FR-LLM-001/ADR-002)")
cfg = P._load(P.PROFILES_CFG)
conformant = [p for p in cfg.get("providers", []) if P._provider_conformant(p)]
check(len(conformant) >= 2, "config'te ≥2 uyumlu sağlayıcı (streaming+tool_call + noTrain + ≥2 tier)")
pb = P._provider_by_id(cfg, "llm-stream-B")
mb = P._run([P._req(0, tier="small"), P._req(100, req_id="r2", expects_tool=True, tool_call=True),
             P._end(60), P._end(160, req_id="r2")], provider=pb)
check(mb["provider_id"] == "llm-stream-B" and gates_pass(mb), "ikinci adapter (B) de tüm kapıları geçer")

print("T6 — no-train + no-log + residency (P6, FR-LLM-012/FR-KB-010/NFR 10.7)")
m = P._run([P._req(0, no_train=True, region_pinned=True, retention="NONE"), P._end(50)])
check(m["no_train_violation"] == 0 and m["region_violation"] == 0, "noTrain + NONE/EPHEMERAL + bölgesel pin uygun")
m_v = P._run([P._req(0, no_train=False), P._end(50)])
check(m_v["no_train_violation"] >= 1 and not gates_pass(m_v), "noTrain=false → eğitime açık, P6 eler")
m_r = P._run([P._req(0, region_pinned=False), P._end(50)])
check(m_r["region_violation"] >= 1 and not gates_pass(m_r), "bölgesel pin yok → P6 eler")

print("T7 — system prompt değişmezliği + metering/model-ver (P7/P8, FR-LLM-006/011/FR-BIL-002)")
m = P._run([P._req(0), P._end(50)])
check(m["system_prompt_mutation"] == 0, "system mesajı user/KB ile değiştirilmedi")
check(m["usage_records"] == m["model_version_recorded"] == m["requests_total"],
      "her complete UsageRecord (INPUT/OUTPUT_TOKENS) + model/versiyon kaydı")
m_mut = P._run([P._req(0, system_preserved=False), P._end(50)])
check(m_mut["system_prompt_mutation"] >= 1 and not gates_pass(m_mut), "system prompt değişti → P7 eler")

print("T8 — hata normalizasyonu + determinizm (P8/P10, FR-TOOL-008)")
m = P._run([P._req(0), P._end(50, reason="error", tax="CONTENT_FILTERED")])
check(m["errors_normalized"] == m["errors_seen"] == 1, "sağlayıcı içerik reddi → ErrorTaxonomy CONTENT_FILTERED (API §11.6)")
m_raw = P._run([P._req(0), P._end(50, reason="error", tax="raw-503")], normalize_errors=False)
check(m_raw["errors_normalized"] == 0 and not gates_pass(m_raw), "ham sağlayıcı kodu normalize edilmedi → P8 eler")
seq = [P._req(0, expects_tool=True, tool_call=True), P._end(50)]
check(P._run(seq) == P._run(seq), "determinizm: birebir aynı metrik (random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nbehavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
