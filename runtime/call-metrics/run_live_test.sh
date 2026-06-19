#!/usr/bin/env bash
# run_live_test.sh — WBS 14.1.2 teknik metrikler (packet loss/jitter/STT-LLM-TTS latency/token/...) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/call_metrics_probe.py" validate
"$PY" "$HERE/call_metrics_probe.py" selftest
"$PY" "$HERE/tests/call_metrics_behavior_test.py"

echo "== sample compute kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/call_metrics_probe.py" compute "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı teknik metrik kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     OpenTelemetry/Prometheus (SAD §11/§17.1) emisyon hattıyla koşulur: 14.1.1 trace zaman"
  echo "     damgalarından türetilen e2e/STT/LLM/TTS gecikmeleri + medya gateway RTP/RTCP'den packet"
  echo "     loss/jitter/codec/SIP + STT word confidence + LLM token + barge-in/silence + retry/fallback +"
  echo "     transfer/termination + provider error ratio + dakika maliyeti DEĞERLERİ 0.4.7 catalog'a uygun"
  echo "     gözlem olarak doğrulanır; kardinalite (kimlik exemplar, label değil) + izinli label + PII-yokluğu"
  echo "     (FR-REC-004) ile ölçülür. Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı teknik metrik kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
