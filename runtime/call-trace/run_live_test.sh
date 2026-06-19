#!/usr/bin/env bash
# run_live_test.sh — WBS 14.1.1 çağrı trace span'leri (BRD §15 tüm zaman damgaları) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/call_trace_probe.py" validate
"$PY" "$HERE/call_trace_probe.py" selftest
"$PY" "$HERE/tests/call_trace_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/call_trace_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı call trace kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     OpenTelemetry W3C traceparent (SAD §17.1) + tail-based sampling hattıyla koşulur:"
  echo "     ingress'te açılan root 'call' span + trace_id altında BRD §15'in 15 zaman damgası span event"
  echo "     olarak doğrulanır; span eşlemesi (stt/llm/tool/tts) + nedensel sıra + ağaç nesting + tek"
  echo "     trace_id/correlation_id + PII-yokluğu (FR-REC-004) + türetilen e2e/STT/LLM/TTS gecikmeleri"
  echo "     (SAD §17.1/§20) ile ölçülür. Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı call trace kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
