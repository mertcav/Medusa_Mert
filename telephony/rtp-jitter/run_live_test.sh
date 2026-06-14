#!/usr/bin/env bash
# run_live_test.sh — WBS 2.2.1 RTP/medya sonlandırma + jitter buffer kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Media Gateway
# medya uç noktası (${MEDIA_GW_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve ham RTP ses payload'ı repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/rtp_jitter_probe.py" validate
"$PY" "$HERE/rtp_jitter_probe.py" selftest
"$PY" "$HERE/tests/jitter_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/rtp_jitter_probe.py" simulate "$s"
done

if [[ -n "${MEDIA_GW_URL:-}" ]]; then
  echo "== canlı jitter buffer kapısı (${MEDIA_GW_URL}) =="
  echo "NOT: canlı doğrulama gerçek RTP medya akışı (RFC 3550 telephone payload) üzerinden inbound"
  echo "     jitter buffer playout + kayıp/jitter telemetrisi (BRD §15 → observability 0.4.7) ile koşulur;"
  echo "     SBC/SIP App Server (2.1.1/2.1.2) + gerçek trunk + native Media Gateway (SAD §21) gerektirir."
  echo "     Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı jitter buffer kapısı: SKIP (MEDIA_GW_URL tanımsız) =="
fi
echo "OK"
