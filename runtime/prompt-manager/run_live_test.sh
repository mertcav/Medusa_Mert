#!/usr/bin/env bash
# run_live_test.sh — WBS 3.2.3 Prompt Manager: versiyonlu sabit system prompt enjeksiyonu kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham prompt/transkript ve PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/prompt_manager_probe.py" validate
"$PY" "$HERE/prompt_manager_probe.py" selftest
"$PY" "$HERE/tests/prompt_manager_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/prompt_manager_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı Prompt Manager kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     Prompt Manager ile koşulur: THINK durumunda yayımlanmış prompt versiyonu (DB 1.1.2 prompt tablosu,"
  echo "     home-region — NFR 10.7) çağrı başında sabitlenir + kullanılan versiyon çağrı kaydına yazılır"
  echo "     (FR-LLM-011). System segmenti pin'lenmiş gövdeyle bayt-bayt montajlanır (FR-LLM-006); caller/KB"
  echo "     (history 3.2.1+3.2.2, RAG) ayrı çitlenmiş segmentlerde; gerçek injection seti ile system'in"
  echo "     değişmezliği (SR-LLM-006 'prompt-override denemesi system prompt'u değiştirmez') doğrulanır;"
  echo "     metrikler observability 0.4.7'ye yayılır. Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint"
  echo "     varlığını bildirir (credential \${ENV})."
else
  echo "== canlı Prompt Manager kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
