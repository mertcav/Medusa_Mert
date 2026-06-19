#!/usr/bin/env bash
# run_live_test.sh — WBS 14.1.3 per-call CPU/bellek/eşzamanlılık ölçümü kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/call_resource_probe.py" validate
"$PY" "$HERE/call_resource_probe.py" selftest
"$PY" "$HERE/tests/call_resource_behavior_test.py"

echo "== sample measure kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/call_resource_probe.py" measure "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı kaynak ölçüm kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     cgroup/RSS/cpu-time accounting + OpenTelemetry/Prometheus (SAD §11/§17.1) emisyon hattıyla"
  echo "     koşulur: çağrı başına CPU saniyesi + orkestratör oturum belleği (MEDYA TAMPONLARI HARİÇ —"
  echo "     ADR-009 hibrit) + worker/tenant eşzamanlılık DEĞERLERİ 0.4.7 catalog'a uygun (call_cpu_seconds/"
  echo "     call_memory_bytes BİREBİR) gözlem olarak doğrulanır; bütçe (FR-RES-016 ≤15MB; 0.4.7"
  echo "     ResourceBudgetExceeded) + density (NFR 10.2 ≥250) + kardinalite (kimlik exemplar, label değil) +"
  echo "     izinli label + PII-yokluğu (FR-REC-004) ile ölçülür. Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı kaynak ölçüm kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
