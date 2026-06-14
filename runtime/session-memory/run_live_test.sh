#!/usr/bin/env bash
# run_live_test.sh — WBS 3.2.1 Kısa süreli diyalog belleği + oturum sonu kalıcılaştırma kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham metin/transkript ve PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/session_memory_probe.py" validate
"$PY" "$HERE/session_memory_probe.py" selftest
"$PY" "$HERE/tests/session_memory_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/session_memory_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı session memory kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     oturum aktörü Session Memory bileşeni ile koşulur: kısa diyalog belleği penceresi (Redis"
  echo "     session_state/session_summary — cache/ 1.1.5, delete_on_call_end) + oturum-sonu durable"
  echo "     kalıcılaştırma (transcript+segment PostgreSQL — db/ 1.1.3, redaction_state='pending'"
  echo "     FR-REC-004 + recording objstore/ 1.1.6 + call.completed eventstream/ 1.1.8). persist_before_delete,"
  echo "     at-least-once idempotent persist ve kart/OTP strip (FR-REC-005) gerçek depolarla doğrulanır;"
  echo "     metrikler observability 0.4.7'ye yayılır. Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint"
  echo "     varlığını bildirir (credential \${ENV})."
else
  echo "== canlı session memory kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
