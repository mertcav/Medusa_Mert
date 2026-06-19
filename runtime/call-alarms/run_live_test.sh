#!/usr/bin/env bash
# run_live_test.sh — WBS 14.1.5 Alarm kuralları (BRD §15) + ≤2dk üretim kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Prometheus/Alertmanager
# uç noktası (${ALERTMANAGER_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/call_alarms_probe.py" validate
"$PY" "$HERE/call_alarms_probe.py" selftest
"$PY" "$HERE/tests/call_alarms_behavior_test.py"

echo "== sample evaluate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/call_alarms_probe.py" evaluate "$s"
done

if [[ -n "${ALERTMANAGER_URL:-}" ]]; then
  echo "== canlı alarm üretim kapısı (${ALERTMANAGER_URL}) =="
  echo "NOT: canlı doğrulama gerçek Prometheus scrape/eval + Alertmanager (SAD §11/§17.2) ile koşulur:"
  echo "     BRD §15 kritik alarm kataloğunun 11 kuralı (0.4.7 alerts.yaml ile BİREBİR) gerçek metrik"
  echo "     sinyalleri (14.1.2 call-metrics + 14.1.3 call-resource + güvenlik/kapasite) üzerinde değerlendirilir;"
  echo "     uçtan-uca alarm üretim gecikmesi = scrape + eval + for + notify ölçülür ve her kural için ≤120s"
  echo "     (NFR 10.1 'alarm ≤2dk üretim') doğrulanır. Alarm etiketi DÜŞÜK kardinalite (correlation_id/call_id"
  echo "     LABEL DEĞİL — annotation/exemplar; 0.4.7 label_policy), etikette PII yok (FR-REC-004), scope=tenant"
  echo "     alarmı tenant_id taşır (izolasyon; tenant security_compliance_officer'a + RMC'ye yönlenir),"
  echo "     flap for ile bastırılır + (alertname,tenant_id) dedup + auto-resolve. Bu betik yalnız endpoint"
  echo "     varlığını bildirir."
else
  echo "== canlı alarm üretim kapısı: SKIP (ALERTMANAGER_URL tanımsız) =="
fi
echo "OK"
