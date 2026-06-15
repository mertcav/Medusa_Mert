#!/usr/bin/env bash
# run_live_test.sh — WBS 7.1.4 Timeout/retry/circuit breaker (Integration GW) (SAD §11.1 [5]) kapısı
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik). Upstream
# transport bir SPI arkasında (vendor-neutral, ADR-001/002); referans probe upstream'i deterministik
# attempts_script ile MODELLER (gerçek ağ YOK). Timeout/retry/breaker mantığı transport'tan bağımsız.
# Canlı upstream (gerçek REST/SOAP/GraphQL endpoint + connection pool) yalnız ${TOOL_GW_ENDPOINT} ORTAM
# DEĞİŞKENİ verilirse not düşülür. Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/integration_gw_probe.py" validate
"$PY" "$HERE/integration_gw_probe.py" selftest
"$PY" "$HERE/tests/integration_gw_behavior_test.py"

echo "== sample resilience kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/integration_gw_probe.py" run "$s"
done

if [[ -n "${TOOL_GW_ENDPOINT:-}" ]]; then
  echo "== canlı resilience kapısı (${TOOL_GW_ENDPOINT}) =="
  echo "NOT: canlı doğrulama Tool Yürütme Hattının (SAD §11.1) adım [5]'inde koşulur:"
  echo "     deterministik attempts_script yerine AYNI Tool Executor transport SPI'sine gerçek REST/SOAP/"
  echo "     GraphQL/webhook transport + connection pool (FR-RES-006) takılır (ADR-001/002). timeout_ms"
  echo "     gerçek endpoint SLA'sına; breaker eşikleri tenant/endpoint bazında ayarlanır. INVARIANT"
  echo "     (SR-TOOL-003): 'bağımlılık hatasında devre açılır; kontrolsüz retry yok' — kapı kodu DEĞİŞMEZ;"
  echo "     bu betik yalnız endpoint varlığını bildirir (\${TOOL_GW_ENDPOINT}; repoya YAZILMAZ)."
else
  echo "== canlı resilience kapısı: SKIP (TOOL_GW_ENDPOINT tanımsız) =="
fi
echo "OK"
