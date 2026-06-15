#!/usr/bin/env bash
# run_live_test.sh — WBS 7.2.1 REST connector (SAD §11.2 / FR-TOOL-001) kapısı
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik). Upstream
# HTTP transport bir SPI arkasında (vendor-neutral, ADR-001/002); referans probe wire'ı deterministik
# wire_script ile MODELLER (gerçek ağ YOK). status→fault eşleme + request build transport'tan bağımsız.
# Canlı REST endpoint (gerçek HTTP client + keep-alive connection pool FR-RES-006) yalnız ${REST_CONNECTOR_ENDPOINT}
# ORTAM DEĞİŞKENİ verilirse not düşülür. Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/rest_connector_probe.py" validate
"$PY" "$HERE/rest_connector_probe.py" selftest
"$PY" "$HERE/tests/rest_connector_behavior_test.py"

echo "== sample REST çağrı kapısı =="
# Not: expect_degraded fixture'ları KASITLI 🔴 döner (C6 no-log gate'inin gerçek kapı olduğunu kanıtlar);
# bunların elemesi BEKLENEN'dir, statik kapı (validate) ayrıca zorlar. set -e'yi tetiklememeleri için
# çıkış kodları tolere edilir; diğer tüm sample'lar 🟢 olmalıdır.
for s in "$HERE"/samples/*.json; do
  if grep -q '"expect_degraded": *true' "$s"; then
    "$PY" "$HERE/rest_connector_probe.py" call "$s" || echo "  (yukarıdaki 🔴 BEKLENEN — degraded anti-örnek)"
  else
    "$PY" "$HERE/rest_connector_probe.py" call "$s"
  fi
done

if [[ -n "${REST_CONNECTOR_ENDPOINT:-}" ]]; then
  echo "== canlı REST kapısı (${REST_CONNECTOR_ENDPOINT}) =="
  echo "NOT: canlı doğrulama Tool Yürütme Hattının (SAD §11.1) adım [5]'i ALTINDA koşulur:"
  echo "     deterministik wire_script yerine AYNI transport SPI'sine (upstream_call(req)→AttemptOutcome)"
  echo "     gerçek HTTP client + keep-alive connection pool (FR-RES-006) takılır (ADR-001/002). Bu connector"
  echo "     7.1.4 (timeout/retry/circuit breaker) tarafından SARILIR; auth.ref ortam değişkeninden çözülür,"
  echo "     değer asla loglanmaz/audit'lenmez (C5/C6). INVARIANT (SR-TOOL-001): 'REST connector başarılı çağrı"
  echo "     yapar' + status→fault eşleme 7.1.4 ile hizalı — kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint"
  echo "     varlığını bildirir (\${REST_CONNECTOR_ENDPOINT}; repoya YAZILMAZ)."
else
  echo "== canlı REST kapısı: SKIP (REST_CONNECTOR_ENDPOINT tanımsız) =="
fi
echo "OK"
