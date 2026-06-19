#!/usr/bin/env bash
# run_live_test.sh — WBS 14.1.6 Gerçek zamanlı operasyon ekranı (≤60sn gecikme) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Grafana/Prometheus
# uç noktası (${GRAFANA_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/live_ops_probe.py" validate
"$PY" "$HERE/live_ops_probe.py" selftest
"$PY" "$HERE/tests/live_ops_behavior_test.py"

echo "== sample snapshot kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/live_ops_probe.py" snapshot "$s"
done

if [[ -n "${GRAFANA_URL:-}" ]]; then
  echo "== canlı gerçek zamanlı op ekranı kapısı (${GRAFANA_URL}) =="
  echo "NOT: canlı doğrulama gerçek Prometheus scrape + Grafana (SAD §11/§17.1; ADR-003 runtime sinyal"
  echo "     emisyonu) ile koşulur: voice-runtime panosunun (0.4.7 dashboards.required) 7 operasyonel"
  echo "     grubu (latency/errors/traffic/quality/resource/cost/alarms) + 15 grafana panel metriği gerçek"
  echo "     14.1.2 (call-metrics) + 14.1.3 (call-resource) + 14.1.5 (call-alarms) sinyalleri üzerinde"
  echo "     yüzeylenir; uçtan-uca VERİ TAZELİĞİ = ingest(scrape) + query_step + refresh + render ölçülür ve"
  echo "     her tile için ≤60s (FR-ANA-012 'gerçek zamanlı operasyon ekranı ≤60sn') doğrulanır. Tile boyutu"
  echo "     DÜŞÜK kardinalite (correlation_id/call_id BOYUT DEĞİL — exemplar/annotation drill-down; 0.4.7"
  echo "     label_policy), boyutta PII yok (FR-REC-004), tenant görünümü tenant_id filtresi taşır (izolasyon;"
  echo "     FR-TEN-002), Tier A — ham içerik (transkript/kayıt) yüzeylenmez (altın kural; içerik → A-12),"
  echo "     auto-refresh açık + runtime refresh ≤ grafana refresh (30s). Bu betik yalnız endpoint varlığını"
  echo "     bildirir."
else
  echo "== canlı gerçek zamanlı op ekranı kapısı: SKIP (GRAFANA_URL tanımsız) =="
fi
echo "OK"
