#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.8 Dashboard + ham veri export kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir analytics-plane
# export consumer'ı / OLAP + nesne-depo uç noktası (${DATA_EXPORT_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/export_probe.py" validate
"$PY" "$HERE/export_probe.py" selftest
"$PY" "$HERE/tests/export_behavior_test.py"

echo "== sample export kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/export_probe.py" export "$s"
done

if [[ -n "${DATA_EXPORT_URL:-}" ]]; then
  echo "== canlı export kapısı (${DATA_EXPORT_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1; ADR-007) koşulur:"
  echo "     mv_call_daily / mv_usage_daily / mv_agent_version_perf / fct_call (FR-ANA-011) kaynaklarından"
  echo "     dashboard agregatı OKUNUR ve ALTTAKİ redaksiyonlu satırlar bir EXPORT DOSYASINA (csv/jsonl/ndjson) yazılır."
  echo "     Doğrulanır: export satır sayısı == sorgulanan benzersiz satır (düşme=0/hayalet=0), deterministik sıralama +"
  echo "     sha256 checksum (aynı sorgu → aynı dosya — SR-ANA-011 'üretilir'), export satırlarının yeniden-agregasyonu"
  echo "     dashboard tile'larını YENİDEN ÜRETİR (SR-ANA-011 'TUTARLIDIR'), export YALNIZ redaksiyonlu/agregat sütun"
  echo "     (pii_class none/low/redacted; ham transkript/ses/kayıt URI/PII yok — FR-REC-004/005), export analytics:read"
  echo "     ister + karar backend'de + platform L0 altın kural (FR-IAM-008/011), tek tenant + home-region (FR-TEN-002/"
  echo "     NFR 10.7), her export → governance.audit.v1 (data_export) WORM izi (içerik/PII taşımaz), (tenant,report,"
  echo "     source,period,format,schema) idempotent. Export başarısızlığı CANLI çağrıyı etkilemez (non-blocking,"
  echo "     FR-RES-011). Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı export kapısı: SKIP (DATA_EXPORT_URL tanımsız) =="
fi
echo "OK"
