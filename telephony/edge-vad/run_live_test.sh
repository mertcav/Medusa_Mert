#!/usr/bin/env bash
# run_live_test.sh — WBS 2.2.3 Edge VAD / endpointing (dinamik) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Media Gateway
# medya uç noktası (${MEDIA_GW_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve ham ses payload'ı/transkript repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/edge_vad_probe.py" validate
"$PY" "$HERE/edge_vad_probe.py" selftest
"$PY" "$HERE/tests/edge_vad_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/edge_vad_probe.py" simulate "$s"
done

if [[ -n "${MEDIA_GW_URL:-}" ]]; then
  echo "== canlı edge VAD/endpointing kapısı (${MEDIA_GW_URL}) =="
  echo "NOT: canlı doğrulama gerçek ses akışı (8kHz/20ms telephone medya) üzerinden edge VAD/endpointing"
  echo "     + barge-in + ölü hava bastırma; söz-sonu/barge-in gecikme + sessizlik telemetrisi"
  echo "     (BRD §15 silence_duration_ms / barge_in_total → observability 0.4.7) ile koşulur;"
  echo "     SBC/SIP App Server (2.1.1/2.1.2) + 2.2.1 jitter buffer + native Media Gateway (SAD §21) gerektirir."
  echo "     Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı edge VAD/endpointing kapısı: SKIP (MEDIA_GW_URL tanımsız) =="
fi
echo "OK"
