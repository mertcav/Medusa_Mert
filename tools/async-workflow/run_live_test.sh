#!/usr/bin/env bash
# run_live_test.sh — WBS 7.2.4 Asenkron uzun-işlem workflow (SAD §11.2 / FR-TOOL-011) kapısı
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik).
# Reconciliation mantığı vendor/transport-nötr (ADR-001/002); referans probe callback (inbound webhook)
# ve polling'i deterministik timeline ile MODELLER (gerçek webhook server/HTTP poll YOK; HMAC imza
# fixture-secret ile runtime'da hesaplanır, repoya yazılmaz). Canlı callback alıcı endpoint + status
# poll yalnız ${ASYNC_CALLBACK_ENDPOINT} / ${ASYNC_CALLBACK_SIGNING_KEY} ORTAM DEĞİŞKENİ verilirse not düşülür.
# Sır/credential ve gerçek PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/async_workflow_probe.py" validate
"$PY" "$HERE/async_workflow_probe.py" selftest
"$PY" "$HERE/tests/async_workflow_behavior_test.py"

echo "== sample reconciliation kapısı =="
# Not: expect_degraded fixture'ları KASITLI 🔴 döner (audit no-log redaksiyonunun gerçek kapı olduğunu
# kanıtlar). Elemesi BEKLENEN'dir; validate ayrıca zorlar. set -e'yi tetiklememeleri için tolere edilir.
for s in "$HERE"/samples/*.json; do
  if grep -q '"expect_degraded": *true' "$s"; then
    "$PY" "$HERE/async_workflow_probe.py" run "$s" || echo "  (yukarıdaki 🔴 BEKLENEN — anti-örnek)"
  else
    "$PY" "$HERE/async_workflow_probe.py" run "$s"
  fi
done

if [[ -n "${ASYNC_CALLBACK_ENDPOINT:-}" ]]; then
  echo "== canlı async kapısı (${ASYNC_CALLBACK_ENDPOINT}) =="
  echo "NOT: canlı doğrulama uzun-işlem dispatch'inden (7.2.1/7.2.2 connector → 202 Accepted) sonra"
  echo "     GERÇEK callback alıcı (HMAC \${ASYNC_CALLBACK_SIGNING_KEY} ile doğrular: imza+±300s+nonce)"
  echo "     ∨ GERÇEK status poll (bounded backoff) AYNI reconciliation mantığını uygular; terminal →"
  echo "     tool.async.completed(result_ref) yayını. INVARIANT (SR-TOOL-011): 'uzun işlem bloklamadan"
  echo "     callback/polling ile tamamlanır' — kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını"
  echo "     bildirir (\${ASYNC_CALLBACK_ENDPOINT}/\${ASYNC_CALLBACK_SIGNING_KEY}; repoya YAZILMAZ)."
else
  echo "== canlı async kapısı: SKIP (ASYNC_CALLBACK_ENDPOINT tanımsız) =="
fi
echo "== TAMAM =="
