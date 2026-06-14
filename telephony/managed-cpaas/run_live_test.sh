#!/usr/bin/env bash
# run_live_test.sh — WBS 2.1.3 Managed CPaaS entegrasyonu kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı medya-WS doğrulaması yalnız
# bir managed CPaaS WS köprü endpoint'i (${CPAAS_MEDIA_WS_URL}) + token (${CPAAS_AUTH_TOKEN})
# ORTAM DEĞİŞKENİ olarak verilirse koşar; yoksa SKIP. Sır repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/cpaas_probe.py" validate
"$PY" "$HERE/cpaas_probe.py" selftest
"$PY" "$HERE/tests/framing_behavior_test.py"

echo "== sample normalize kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/cpaas_probe.py" normalize "$s"
done

if [[ -n "${CPAAS_MEDIA_WS_URL:-}" ]]; then
  echo "== canlı medya-WS kapısı (${CPAAS_MEDIA_WS_URL}) =="
  echo "NOT: canlı köprü doğrulaması vendor-eval/media_latency_probe.py 'probe' ile koşulur;"
  echo "     bu betik yalnız endpoint varlığını/erişilebilirliğini bildirir (credential ${ENV})."
  # Gerçek medya RTT/jitter ölçümü 0.2.1 harness'ına devredilir (tek ölçüm hattı).
else
  echo "== canlı medya-WS kapısı: SKIP (CPAAS_MEDIA_WS_URL tanımsız) =="
fi
echo "OK"
