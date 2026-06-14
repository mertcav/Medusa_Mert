#!/usr/bin/env bash
# run_live_test.sh — WBS 3.2.2 Token sınırına göre konuşma geçmişi özetleme kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham metin/transkript ve PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/summarization_probe.py" validate
"$PY" "$HERE/summarization_probe.py" selftest
"$PY" "$HERE/tests/summarization_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/summarization_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı özetleme motoru kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     Session Memory özetleme motoru ile koşulur: history token tavanı aşımında en eski turn'ler"
  echo "     gerçek LlmAdapter (küçük tier — SAD §9/ADR-008, no-train/bölgesel FR-LLM-012/NFR 10.7) ile"
  echo "     yuvarlanan session_summary'ye (Redis — cache/ 1.1.5) sıkıştırılır. Gerçek tokenizer + LLM"
  echo "     context-window ile token azaltma (FR-RES-010), coverage (SR-LLM-005 'bağlam korunur') ve"
  echo "     off-path gecikme (NFR 10.1) doğrulanır; metrikler observability 0.4.7'ye yayılır."
  echo "     Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı özetleme motoru kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
