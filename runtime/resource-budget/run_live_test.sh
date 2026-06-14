#!/usr/bin/env bash
# run_live_test.sh — WBS 3.1.4 Per-call kaynak bütçesi (~15MB) izleme + sınırlama kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve ham ses payload'ı/transkript repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/resource_budget_probe.py" validate
"$PY" "$HERE/resource_budget_probe.py" selftest
"$PY" "$HERE/tests/resource_budget_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/resource_budget_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı per-call kaynak bütçesi kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     oturum aktörü Guard'ı ile koşulur; oturum-başı RSS/heap (medya hariç) + CPU profiler telemetrisi"
  echo "     (BRD §15 'çağrı başına kaynak tüketimi CPU/bellek') → bant/aşım + özetleme (FR-RES-010) +"
  echo "     kontrollü shed (FR-RES-014) ölçülür; aşım observability 0.4.7'ye yayılır + alarmlanır."
  echo "     0.3.3 density profil yapısı gerçek profiler verisiyle doldurulur; kapı kodu DEĞİŞMEZ."
  echo "     Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı per-call kaynak bütçesi kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
