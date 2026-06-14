#!/usr/bin/env bash
# run_live_test.sh — WBS 2.1.6 DTMF algılama/üretme (RFC 2833 / SIP INFO) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir telefoni
# uç noktası / SIP App Server (${DTMF_API_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa
# SKIP. Sır/credential ve gerçek kart/PIN verisi repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/dtmf_probe.py" validate
"$PY" "$HERE/dtmf_probe.py" selftest
"$PY" "$HERE/tests/dtmf_behavior_test.py"

echo "== sample detect/generate kapısı =="
for s in "$HERE"/samples/*.json; do
  case "$s" in
    *detect*) "$PY" "$HERE/dtmf_probe.py" detect "$s" ;;
    *generate*) "$PY" "$HERE/dtmf_probe.py" generate "$s" ;;
  esac
done

if [[ -n "${DTMF_API_URL:-}" ]]; then
  echo "== canlı DTMF kapısı (${DTMF_API_URL}) =="
  echo "NOT: canlı doğrulama gerçek RFC 2833 telephone-event RTP + SIP INFO ile inbound algılama"
  echo "     ve sendDtmf üretme (API §11.5) üzerinden koşulur; SBC/SIP App Server (2.1.1/2.1.2) +"
  echo "     gerçek trunk gerektirir. Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı DTMF kapısı: SKIP (DTMF_API_URL tanımsız) =="
fi
echo "OK"
