#!/usr/bin/env bash
# run_live_test.sh — WBS 4.2.3 TTS adapter #1 + #2 (streaming, pronunciation dictionary, cancel) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir TTS sağlayıcısı
# uç noktası (${TTS_PROVIDER_URL}) + API anahtarı ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham SES/audio ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/tts_adapter_probe.py" validate
"$PY" "$HERE/tts_adapter_probe.py" selftest
"$PY" "$HERE/tests/tts_adapter_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/tts_adapter_probe.py" simulate "$s"
done

if [[ -n "${TTS_PROVIDER_URL:-}" ]]; then
  echo "== canlı TtsAdapter kapısı (${TTS_PROVIDER_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3/§8.1)"
  echo "     iki somut TtsAdapter ile koşulur: SPEAK durumunda LLM token akışı → synthesize(textIn, voice, opts)"
  echo "     → AsyncStream<AudioChunk>; ilk ses paketi gecikmesi (first-byte, SAD §20 TTS kalemi P95 ≤200ms),"
  echo "     barge-in'de cancel(streamId) → susma gecikmesi (FR-TTS-005/NFR 10.1 ≤200ms + kesme sonrası ses yok),"
  echo "     pronunciation dictionary (sayı/tarih/para/isim — FR-TTS-004), statik anons cache (FR-TTS-010),"
  echo "     8 kHz native (FR-RES-008), UsageRecord metering (FR-BIL-002) + ortak ErrorTaxonomy (API §11.6)"
  echo "     ölçülür; sentetik metin (FR-TST-008 — gerçek müşteri verisi yok) kullanılır; metrikler observability"
  echo "     0.4.7'ye yayılır; ≥2 sağlayıcı + eşdeğer-ses fallback (FR-TTS-008/009 → 4.3.2). Sağlayıcı seçimi"
  echo "     0.2.6/0.3.x (vendor-neutral, ADR-002). Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını"
  echo "     bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı TtsAdapter kapısı: SKIP (TTS_PROVIDER_URL tanımsız) =="
fi
echo "OK"
