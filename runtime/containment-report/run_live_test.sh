#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.3 Containment/transfer oranı raporu kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir analytics-plane
# oran-rapor consumer'ı / OLAP uç noktası (${CONTAINMENT_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/containment_report_probe.py" validate
"$PY" "$HERE/containment_report_probe.py" selftest
"$PY" "$HERE/tests/containment_report_behavior_test.py"

echo "== sample report kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/containment_report_probe.py" report "$s"
done

if [[ -n "${CONTAINMENT_URL:-}" ]]; then
  echo "== canlı oran-rapor kapısı (${CONTAINMENT_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1; ADR-007) koşulur:"
  echo "     fct_call.contained/transferred (FR-ANA-003) + call.outcome (14.2.2 etiketi) consumer'ı"
  echo "     per-call outcome etiketini AGREGE eder ve mv_call_daily{containment_rate, transfer_rate}"
  echo "     metriklerini tenant_id + agent_id + agent_version_id + period boyutuna göre + genel üretir."
  echo "     Doğrulanır: outcome kovaları girdiyi TAM partisyonlar (partition_gap=0; çift/düşme yok),"
  echo "     containment=contained/handled + transfer=transferred/handled (not_connected handled paydadan"
  echo "     HARİÇ), her oran ∈ [0,1] + 4 partisyon toplamı == 1.0, (tenant_id,call_id) idempotent (replay"
  echo "     çift-saymaz), payda<min_group_n grup oranı bastırılır (k-anon), her rapor tek tenant + home-region,"
  echo "     yayımlanan agregat per-call kimlik/PII taşımaz (FR-REC-004). Rapor başarısızlığı CANLI çağrıyı"
  echo "     etkilemez (non-blocking, FR-RES-011). Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı oran-rapor kapısı: SKIP (CONTAINMENT_URL tanımsız) =="
fi
echo "OK"
