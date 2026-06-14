#!/usr/bin/env bash
# run_live_test.sh — WBS 2.1.4 SIP trunk / BYOC kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı SIP/SBC doğrulaması yalnız
# bir BYOC trunk/SBC peer (${BYOC_SBC_HOST}) + SIP URI (${BYOC_SIP_URI}) ORTAM DEĞİŞKENİ
# olarak verilirse not düşülür; yoksa SKIP. Sır repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/byoc_probe.py" validate
"$PY" "$HERE/byoc_probe.py" selftest
"$PY" "$HERE/tests/sdp_rtp_behavior_test.py"

echo "== sample normalize kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/byoc_probe.py" normalize "$s"
done

if [[ -n "${BYOC_SBC_HOST:-}" ]]; then
  echo "== canlı SIP/SBC kapısı (${BYOC_SBC_HOST}) =="
  echo "NOT: canlı trunk/SBC SIP OPTIONS ping + medya RTT/jitter ölçümü SBC (2.1.1) +"
  echo "     vendor-eval/media_latency_probe.py 'probe' (M2) ile koşulur; bu betik yalnız"
  echo "     endpoint varlığını bildirir (credential ${ENV}). Gerçek RTP ölçümü 0.2.1'e devredilir."
else
  echo "== canlı SIP/SBC kapısı: SKIP (BYOC_SBC_HOST tanımsız) =="
fi
echo "OK"
