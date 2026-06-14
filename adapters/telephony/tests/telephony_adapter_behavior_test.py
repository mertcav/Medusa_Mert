#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telephony_adapter_behavior_test.py — WBS 4.2.5 davranış kapısı (T1–T8)

Deterministik TelephonyAdapter'ın (telephony_adapter_probe.TelephonyAdapterRuntime) iki somut sağlayıcı
(≥2/kategori — managed CPaaS + BYOC SIP trunk) arkasındaki SPI-uyum davranışını HARD kapılara (P1–P8)
karşı doğrular: taşıma-nötr normalize, E.164 + caller-ID, cold/warm/whisper transfer, DTMF/AMD olayları,
hangup neden kodu, 8kHz+SRTP+kurulum, metering + residency + hata normalizasyonu. Sunucu/credential
GEREKMEZ; stdlib-only. runtime/ + telephony/ + adapters/tts/ + adapters/llm/ davranış-testi disipliniyle aynı.

Koş: python3 tests/telephony_adapter_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import telephony_adapter_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
GATES = SPEC.get("gates", {})

results = []


def check(ok, label):
    results.append((bool(ok), label))
    print("  %s %s" % ("✓" if ok else "✗", label))


def gates_pass(m):
    return all(ok for ok, _ in P.evaluate(GATES, m))


print("T1 — taşıma-nötr normalize: managed/BYOC tek SPI sözleşmesi (P1, ADR-001/SAD §11.5)")
m = P._run([P._answer(0), P._media(700), P._hangup(5000)])
check(m["contract_divergence"] == 0, "managed taşıma orchestrator'a sızmaz (tek normalize sözleşme)")
m_div = P._run([P._answer(0), P._media(700), P._hangup(5000)], normalize_contract=False)
check(m_div["contract_divergence"] >= 1 and not gates_pass(m_div), "ham taşıma biçimi sızdı → P1 eler")

print("T2 — E.164 + caller-ID havuzu (P2, FR-TEL-004/005)")
m = P._run([P._dial(0, caller_id_pool="pool-1", e164_valid=True), P._media(740), P._hangup(5000)])
check(m["invalid_e164"] == 0 and m["missing_caller_id_pool"] == 0, "E.164 numara + outbound caller-ID havuzu referansı")
m_e = P._run([P._dial(0, e164_valid=False), P._media(740), P._hangup(5000)])
check(m_e["invalid_e164"] >= 1 and not gates_pass(m_e), "E.164 dışı numara → P2 eler")
m_p = P._run([P._dial(0, caller_id_pool=None), P._media(740), P._hangup(5000)])
check(m_p["missing_caller_id_pool"] >= 1 and not gates_pass(m_p), "outbound caller-ID havuzu yok → P2 eler")

print("T3 — cold/warm/whisper transfer (P3, FR-TEL-007/FR-HND-003)")
m = P._run([P._answer(0), P._media(700),
            P._xfer(1000, mode="COLD", target_type="QUEUE"),
            P._hangup(2000, reason_code="transfer_to_human")])
check(m["transfers_ok"] == 1 and m["unsupported_transfer"] == 0, "cold transfer kuyruğa desteklendi (SIP REFER)")
m_bad = P._run([P._answer(0), P._media(700), P._xfer(1000, mode="BLIND"),
                P._hangup(2000, reason_code="transfer_to_human")])
check(m_bad["unsupported_transfer"] >= 1 and not gates_pass(m_bad), "cold/warm/whisper dışı mode → P3 eler")

print("T4 — DTMF + AMD olayları yüzeye çıkar (P4, FR-TEL-006/010)")
m = P._run([P._answer(0), P._media(700), P._dtmf(900, transport="sip_info"),
            P._amd(1000, result="machine"), P._hangup(5000)])
check(m["dtmf_events"] == 1 and m["amd_events"] == 1 and m["dropped_event"] == 0,
      "DTMF (RFC 2833/SIP INFO) + AMD on(...) ile orchestrator'a çıkar")
m_drop = P._run([P._answer(0), P._media(700), P._dtmf(900), P._amd(1000), P._hangup(5000)], surface_events=False)
check(m_drop["dropped_event"] >= 1 and not gates_pass(m_drop), "olay yutuldu → P4 eler")

print("T5 — ≥2 SPI-uyumlu sağlayıcı/trunk (P5, FR-TEL-002/ADR-002)")
cfg = P._load(P.PROFILES_CFG)
conformant = [p for p in cfg.get("providers", []) if P._provider_conformant(p)]
check(len(conformant) >= 2, "config'te ≥2 uyumlu sağlayıcı (dtmf+amd+transfer + cold/warm/whisper + 8kHz + SRTP + in/out)")
modes = {p.get("mode") for p in conformant}
check({"managed", "byoc"} <= modes, "portföy hem managed CPaaS hem BYOC SIP trunk içerir (FR-TEL-002)")
pb = P._provider_by_id(cfg, "tel-byoc-B")
mb = P._run([P._answer(0), P._media(540), P._dtmf(900), P._hangup(5000)], provider=pb)
check(mb["provider_id"] == "tel-byoc-B" and mb["mode"] == "byoc" and gates_pass(mb),
      "ikinci adapter (BYOC SIP trunk B) de tüm kapıları geçer")

print("T6 — hangup standart neden kodu (P6, FR-TEL-012)")
m = P._run([P._answer(0), P._media(700), P._hangup(5000, reason_code="completed_caller_hangup")])
check(m["missing_reason_code"] == 0 and m["reason_codes"] == ["completed_caller_hangup"],
      "hangup standart neden kodu taşır (taksonomi 2.1.7)")
m_nr = P._run([P._answer(0), P._media(700), P._hangup(5000, reason_code=None)])
check(m_nr["missing_reason_code"] >= 1 and not gates_pass(m_nr), "neden kodu yok → P6 eler")

print("T7 — medya 8kHz + SRTP + kurulum bütçesi (P7, FR-RES-008/NFR 10.6/SAD §20)")
m = P._run([P._answer(0, secure=True, sr=8000), P._media(700), P._hangup(5000)])
check(m["insecure_media"] == 0 and m["non_8khz"] == 0 and m["setup_p95_ms"] <= GATES["setup_p95_ms"],
      "8kHz native + SRTP/TLS + kurulum/post-dial ≤ bütçe")
m_ins = P._run([P._answer(0, secure=False), P._media(700), P._hangup(5000)])
check(m_ins["insecure_media"] >= 1 and not gates_pass(m_ins), "düz-metin SIP/RTP → P7 eler")
m_slow = P._run([P._answer(0), P._media(2600), P._hangup(5000)], fast_setup=False)
check(m_slow["setup_max_ms"] > GATES["setup_p95_ms"] and not gates_pass(m_slow), "kurulum bütçe aşıldı → P7 eler")

print("T8 — metering (SECONDS) + residency + hata normalizasyonu + determinizm (P8/P10, FR-BIL-002/FR-TOOL-008)")
m = P._run([P._answer(0), P._media(700), P._hangup(60000, reason_code="completed_caller_hangup")])
check(m["usage_records"] == m["ended"] == 1 and m["call_seconds_total"] == 60,
      "her tamamlanan çağrı UsageRecord/CDR (unit=SECONDS, süre 60s)")
m_err = P._run([P._dial(0), P._media(700),
                P._hangup(800, reason_code="timeout", reason="error", tax="TIMEOUT")])
check(m_err["errors_normalized"] == m_err["errors_seen"] == 1, "SIP zaman aşımı → ErrorTaxonomy TIMEOUT (API §11.6)")
m_raw = P._run([P._dial(0), P._media(700),
                P._hangup(800, reason_code="timeout", reason="error", tax="raw-sip-408")], normalize_errors=False)
check(m_raw["errors_normalized"] == 0 and not gates_pass(m_raw), "ham SIP kodu normalize edilmedi → P8 eler")
m_reg = P._run([P._answer(0, region_pinned=False), P._media(700), P._hangup(5000)])
check(m_reg["region_violation"] >= 1 and not gates_pass(m_reg), "home-region pin yok → P8 eler")
seq = [P._answer(0), P._media(700), P._xfer(1000), P._hangup(5000, reason_code="transfer_to_human")]
check(P._run(seq) == P._run(seq), "determinizm: birebir aynı metrik (random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
print("\nbehavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
