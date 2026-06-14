#!/usr/bin/env bash
# run_live_test.sh — WBS 4.2.5 Telephony adapter #1 + #2 (SIP trunk + BYOC) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir telekom/trunk
# uç noktası (${TELEPHONY_PROVIDER_URL}) + SIP/SBC kimlik bilgisi ORTAM DEĞİŞKENİ verilirse not
# düşülür; yoksa SKIP. Sır/credential, ham TELEFON NUMARASI ve çağrı medyası repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/telephony_adapter_probe.py" validate
"$PY" "$HERE/telephony_adapter_probe.py" selftest
"$PY" "$HERE/tests/telephony_adapter_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/telephony_adapter_probe.py" simulate "$s"
done

if [[ -n "${TELEPHONY_PROVIDER_URL:-}" ]]; then
  echo "== canlı TelephonyAdapter kapısı (${TELEPHONY_PROVIDER_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3/§8.1)"
  echo "     iki somut TelephonyAdapter ile koşulur: (#1) managed CPaaS (Media Streams WS, M1 / 2.1.3) +"
  echo "     (#2) BYOC SIP trunk (ham SIP+RTP, M2 / 2.1.4 — Bring Your Own Carrier). FR-TEL-002 SIP trunk + BYOC:"
  echo "     answer(inbound)/dial(outbound) → mediaStream RTP/SRTP 8kHz (FR-RES-008/NFR 10.6); taşıma-nötr"
  echo "     normalize (managed/BYOC → tek SPI sözleşmesi; orchestrator taşımayı görmez — ADR-001);"
  echo "     E.164 numara + caller-ID havuzu (FR-TEL-004/005); cold/warm/whisper transfer SIP REFER (FR-TEL-007);"
  echo "     sendDtmf RFC 2833 / SIP INFO (FR-TEL-006); on(ANSWERED/HANGUP/DTMF/AMD) — AMD telesekreter (FR-TEL-010);"
  echo "     hangup standart neden kodu (taksonomi 2.1.7 — FR-TEL-012); çağrı kurulum/post-dial gecikme bütçesi;"
  echo "     UsageRecord (unit=SECONDS, çağrı süresi — FR-BIL-002); home-region trunk + SRTP/TLS (NFR 10.7/10.6);"
  echo "     telekom/SIP hatası → ortak ErrorTaxonomy (API §11.6) + ≥2 trunk/sağlayıcı fallback (FR-TEL-002 → 4.3.x);"
  echo "     SBC (2.1.1) önde; sentetik çağrı (FR-TST-008 — gerçek müşteri verisi yok); metrikler observability"
  echo "     0.4.7'ye yayılır. Sağlayıcı/telekom seçimi 0.2.1/0.2.6/0.3.x (vendor-neutral, ADR-002). Kapı kodu"
  echo "     DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı TelephonyAdapter kapısı: SKIP (TELEPHONY_PROVIDER_URL tanımsız) =="
fi
echo "OK"
