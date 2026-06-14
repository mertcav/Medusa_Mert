#!/usr/bin/env bash
# run_live_test.sh — WBS 2.1.5 E.164 normalizasyonu + Caller ID & numara havuzu kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız bir numara
# yönetim API'si / SIP App Server (${NUMBERING_API_URL}) ORTAM DEĞİŞKENİ verilirse not
# düşülür; yoksa SKIP. Sır repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/numbering_probe.py" validate
"$PY" "$HERE/numbering_probe.py" selftest
"$PY" "$HERE/tests/e164_behavior_test.py"

echo "== sample normalize/select kapısı =="
for s in "$HERE"/samples/*.json; do
  case "$s" in
    *normalize*) "$PY" "$HERE/numbering_probe.py" normalize "$s" ;;
    *) "$PY" "$HERE/numbering_probe.py" select "$s" ;;
  esac
done

echo "== inbound DID→tenant çözüm örneği =="
"$PY" "$HERE/numbering_probe.py" resolve "+908500000123" || true

if [[ -n "${NUMBERING_API_URL:-}" ]]; then
  echo "== canlı numara yönetim kapısı (${NUMBERING_API_URL}) =="
  echo "NOT: canlı havuz CRUD + DID→tenant çözüm + outbound Caller ID atama gerçek"
  echo "     phone_number tablosu (DB §14) + SIP App Server (2.1.2) ile koşulur; bu betik"
  echo "     yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı numara yönetim kapısı: SKIP (NUMBERING_API_URL tanımsız) =="
fi
echo "OK"
