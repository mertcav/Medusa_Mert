#!/usr/bin/env bash
# run_live_test.sh — WBS 2.2.2 Codec yönetimi (8kHz) + gereksiz resample/transcode önleme kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Media Gateway
# medya uç noktası (${MEDIA_GW_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve ham ses payload'ı repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/codec_probe.py" validate
"$PY" "$HERE/codec_probe.py" selftest
"$PY" "$HERE/tests/codec_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/codec_probe.py" simulate "$s"
done

if [[ -n "${MEDIA_GW_URL:-}" ]]; then
  echo "== canlı codec kapısı (${MEDIA_GW_URL}) =="
  echo "NOT: canlı doğrulama gerçek SDP offer/answer pazarlığı + medya zinciri (PSTN→SBC→MediaGW→STT/TTS)"
  echo "     boyunca aktif codec + resample/transcode hop sayımı (BRD §15 voice_codec_info → observability 0.4.7)"
  echo "     ile koşulur; SBC/SIP App Server (2.1.1/2.1.2) + gerçek trunk + native Media Gateway (SAD §21) gerektirir."
  echo "     Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı codec kapısı: SKIP (MEDIA_GW_URL tanımsız) =="
fi
echo "OK"
