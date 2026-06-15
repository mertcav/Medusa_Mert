#!/usr/bin/env bash
# run_live_test.sh — WBS 7.2.5 CRM/Ticketing/ERP referans entegrasyonu (pilot) kapısı (BRD §6.1)
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik).
# Bu modül yeni transport EKLEMEZ; SAD §11.1 Tool Yürütme Hattını ([1]→[7]) ORKESTRE eder — her adımın
# AĞIR mantığı ilgili modülde (7.1.x/7.2.x). Referans probe zinciri deterministik MODELLER (gerçek
# CRM/ticketing/ERP çağrısı YOK; AttemptOutcome/allowlist/schema kararları fixture). Canlı pilot
# entegrasyonu yalnız ${PILOT_CRM_ENDPOINT}/${PILOT_TICKETING_ENDPOINT}/${PILOT_ERP_ENDPOINT} ORTAM
# DEĞİŞKENLERİ verilirse not düşülür. Sır/credential ve gerçek PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/reference_integration_probe.py" validate
"$PY" "$HERE/reference_integration_probe.py" selftest
"$PY" "$HERE/tests/reference_integration_behavior_test.py"

echo "== sample zincir kapısı =="
# Not: degraded fixture KASITLI sızıntı içerir (R7/R8 tarayıcısının gerçek kapı olduğunu kanıtlar);
# expect_gate_fail=true olduğundan probe exit 0 döner (eleme BEKLENEN ve tüketildi).
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/reference_integration_probe.py" run "$s"
done

if [[ -n "${PILOT_CRM_ENDPOINT:-}${PILOT_TICKETING_ENDPOINT:-}${PILOT_ERP_ENDPOINT:-}" ]]; then
  echo "== canlı pilot kapısı =="
  echo "NOT: canlı doğrulamada AYNI zincir ([1]→[7]) gerçek connector (7.2.1 REST / 7.2.2 SOAP/GraphQL)"
  echo "     + gerçek allowlist (7.2.3) + GW (7.1.4) + error-norm (7.1.5) ile dolar; auth yalnız"
  echo "     \${PILOT_*_TOKEN} ortam değişkeninden çözülür (repoya YAZILMAZ). INVARIANT (SR-TOOL-001):"
  echo "     'Her connector tipi (REST/GraphQL/SOAP) başarılı çağrı yapar' + OBJ-07 gerçek işlem."
  echo "     Bağlayıcı vendor seçimi YOK (ADR-002; BRD §22 açık karar) — pilot referans/illüstratif."
else
  echo "== canlı pilot kapısı: SKIP (PILOT_*_ENDPOINT tanımsız) =="
fi
echo "== TAMAM =="
