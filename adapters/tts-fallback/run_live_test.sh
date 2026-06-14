#!/usr/bin/env bash
# run_live_test.sh — WBS 4.3.2 TTS fallback + ses karakteri tutarlılığı kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız İKİ gerçek TTS sağlayıcısı
# uç noktası (${TTS_PRIMARY_URL} + ${TTS_SECONDARY_URL}) + API anahtarı ORTAM DEĞİŞKENİ verilirse
# not düşülür; yoksa SKIP. Sır/credential, ham SES ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/tts_fallback_probe.py" validate
"$PY" "$HERE/tts_fallback_probe.py" selftest
"$PY" "$HERE/tests/tts_fallback_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/tts_fallback_probe.py" simulate "$s"
done

if [[ -n "${TTS_PRIMARY_URL:-}" && -n "${TTS_SECONDARY_URL:-}" ]]; then
  echo "== canlı TTS fallback kapısı (${TTS_PRIMARY_URL} → ${TTS_SECONDARY_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3/§8.1)"
  echo "     iki somut TtsAdapter + 4.1.2 circuit breaker ile koşulur: SPEAK durumunda LLM metni birincil"
  echo "     TtsAdapter.synthesize()'a akar; birincil hata/timeout (circuit-open) ENJEKTE edilir → switcher"
  echo "     ikincile geçer + in-flight sözün KALAN metnini EŞDEĞER ses ile yeniden sentezler (resynth"
  echo "     continuation; FR-TTS-008/009) — zaten çalınmış metin tekrar seslendirilmez; söz ikincide"
  echo "     tamamlanır (utterance_lost=0); SES KARAKTERİ TUTARLI kalır (voice_equivalence haritası,"
  echo "     FR-TTS-009); anahtarlama gecikmesi (switch overhead, NFR 10.1 ≤200ms); anahtarlama sırasında"
  echo "     barge-in cancel ≤200ms (talk-over yok); her iki sağlayıcı düşünce deterministik akışa (insan"
  echo "     aktarımı — SAD §8.3, BRD §19 (4)) geçiş + çağrı DÜŞMEZ; UsageRecord segment metering"
  echo "     (CHARACTERS, FR-BIL-002) + ortak ErrorTaxonomy (API §11.6) ölçülür; sentetik metin (FR-TST-008"
  echo "     — gerçek müşteri verisi yok) kullanılır; metrikler observability 0.4.7'ye yayılır; ≥2 sağlayıcı"
  echo "     (BRD §19 (1)). Sağlayıcı seçimi 0.2.3/0.2.6/0.3.x (vendor-neutral, ADR-002). Kapı kodu DEĞİŞMEZ;"
  echo "     bu betik yalnız endpoint varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı TTS fallback kapısı: SKIP (TTS_PRIMARY_URL/TTS_SECONDARY_URL tanımsız) =="
fi
echo "OK"
