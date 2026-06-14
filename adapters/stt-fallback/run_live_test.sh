#!/usr/bin/env bash
# run_live_test.sh — WBS 4.3.1 STT fallback (hata/timeout → ikincil) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız İKİ gerçek STT sağlayıcısı
# uç noktası (${STT_PRIMARY_URL} + ${STT_SECONDARY_URL}) + API anahtarı ORTAM DEĞİŞKENİ verilirse
# not düşülür; yoksa SKIP. Sır/credential, ham AUDIO ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/stt_fallback_probe.py" validate
"$PY" "$HERE/stt_fallback_probe.py" selftest
"$PY" "$HERE/tests/stt_fallback_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/stt_fallback_probe.py" simulate "$s"
done

if [[ -n "${STT_PRIMARY_URL:-}" && -n "${STT_SECONDARY_URL:-}" ]]; then
  echo "== canlı STT fallback kapısı (${STT_PRIMARY_URL} → ${STT_SECONDARY_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3/§8.1)"
  echo "     iki somut SttAdapter + 4.1.2 circuit breaker ile koşulur: CAPTURE durumunda 8 kHz medya birincil"
  echo "     SttAdapter.stream()'e akar; birincil hata/timeout (circuit-open) ENJEKTE edilir → switcher ikincile"
  echo "     geçer + in-flight söz için son N saniye audio ikincile replay edilir (FR-STT-008/API §11.2); söz"
  echo "     ikincide tamamlanır (utterance_lost=0), anahtarlama gecikmesi (switch overhead, NFR 10.1 ≤200ms),"
  echo "     her iki sağlayıcı düşünce deterministik akışa (insan aktarımı — SAD §8.3, BRD §19 (4)) geçiş + çağrı"
  echo "     DÜŞMEZ; UsageRecord segment metering (FR-BIL-002) + ortak ErrorTaxonomy (API §11.6) ölçülür; sentetik"
  echo "     audio (FR-TST-008 — gerçek müşteri verisi yok) kullanılır; metrikler observability 0.4.7'ye yayılır;"
  echo "     ≥2 sağlayıcı (BRD §19 (1)). Sağlayıcı seçimi 0.2.2/0.2.6/0.3.x (vendor-neutral, ADR-002). Kapı kodu"
  echo "     DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı STT fallback kapısı: SKIP (STT_PRIMARY_URL/STT_SECONDARY_URL tanımsız) =="
fi
echo "OK"
