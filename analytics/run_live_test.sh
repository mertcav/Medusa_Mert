#!/usr/bin/env bash
# run_live_test.sh — WBS 1.1.9 OLAP şema canlı uygulama/doğrulama kapısı koşucusu.
# Statik kapı (probe) HER ZAMAN koşar (sunucu gerekmez). Canlı kapı opsiyonel:
#   - ClickHouse: clickhouse-client + ${CLICKHOUSE_DSN}/${OLAP_DB} varsa ddl/clickhouse.sql uygular.
#   - BigQuery:   bq + ${OLAP_DS} varsa ddl/bigquery.sql uygular.
# Yoksa SKIP (exit 0) — db/cache/objstore/eventstream run_live_test.sh deseniyle aynı.
# Sır/credential repoya YAZILMAZ — yalnız ${ENV}. Asıl deterministik kapı:
#   python3 olap_probe.py validate|query|selftest
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "== statik kapı (probe) =="
python3 "$HERE/olap_probe.py" validate || exit 1
python3 "$HERE/olap_probe.py" query    || exit 1
python3 "$HERE/olap_probe.py" selftest || exit 1
python3 "$HERE/tests/aggregation_behavior_test.py" || exit 1

RAN_LIVE=0

# --- ClickHouse (opsiyonel) ---
if command -v clickhouse-client >/dev/null 2>&1 && [ -n "${OLAP_DB:-}" ]; then
  echo "== canlı kapı: ClickHouse (db=${OLAP_DB}) =="
  # ${OLAP_DB} substitüsyonu ile DDL'i uygula (DSN/host/parola yalnız ${ENV}).
  sed "s/\${OLAP_DB}/${OLAP_DB}/g" "$HERE/ddl/clickhouse.sql" \
    | clickhouse-client ${CLICKHOUSE_DSN:+--multiquery} --multiquery && RAN_LIVE=1 \
    || { echo "FAIL: ClickHouse DDL uygulanamadı"; exit 1; }
else
  echo "SKIP: clickhouse-client/OLAP_DB yok (CI'da gerçek cluster ile koşar)."
fi

# --- BigQuery (opsiyonel) ---
if command -v bq >/dev/null 2>&1 && [ -n "${OLAP_DS:-}" ]; then
  echo "== canlı kapı: BigQuery (ds=${OLAP_DS}) =="
  sed "s/\${OLAP_DS}/${OLAP_DS}/g" "$HERE/ddl/bigquery.sql" \
    | bq query --use_legacy_sql=false && RAN_LIVE=1 \
    || { echo "FAIL: BigQuery DDL uygulanamadı"; exit 1; }
else
  echo "SKIP: bq/OLAP_DS yok (CI'da gerçek dataset ile koşar)."
fi

[ "$RAN_LIVE" -eq 0 ] && echo "Canlı motor yok → yalnız statik kapı koştu (SKIP, exit 0)."
exit 0
