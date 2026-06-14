#!/usr/bin/env bash
# run_live_test.sh — WBS 3.1.5 correlation_id + tenant context propagation kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/context_propagation_probe.py" validate
"$PY" "$HERE/context_propagation_probe.py" selftest
"$PY" "$HERE/tests/context_propagation_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/context_propagation_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı context propagation kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     OpenTelemetry W3C traceparent + yapılandırılmış log + Prometheus exemplar hattıyla koşulur:"
  echo "     ingress'te kurulan oturum bağlamı (tenant_id+correlation_id+region) tüm span/log/event/adapter"
  echo "     çağrılarında doğrulanır; metrik label kardinalitesi (0.4.7 label_policy) + PII yokluğu denetlenir;"
  echo "     cross-tenant + region telemetrisi (SAD §13.3/§17.1) ile ölçülür. Bu betik yalnız endpoint"
  echo "     varlığını bildirir (credential \${ENV})."
else
  echo "== canlı context propagation kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
