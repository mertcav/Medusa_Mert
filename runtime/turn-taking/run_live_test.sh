#!/usr/bin/env bash
# run_live_test.sh — WBS 3.1.3 Turn-taking + barge-in koordinasyonu kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve ham ses payload'ı/transkript repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/turn_taking_probe.py" validate
"$PY" "$HERE/turn_taking_probe.py" selftest
"$PY" "$HERE/tests/turn_taking_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/turn_taking_probe.py" simulate "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı turn-taking/barge-in koordinasyon kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     edge'den (2.2.3) gelen onaylı turn-event akışıyla koşulur; barge_in→cancel koordinasyon gecikmesi"
  echo "     + zemin ihlali + backchannel ayrımı + legal geçiş telemetrisi (BRD §15 barge_in_total →"
  echo "     observability 0.4.7) ile ölçülür; 2.2.3 edge VAD + 2.2.7 TTS kesme/egress flush gerektirir."
  echo "     Bu betik yalnız endpoint varlığını bildirir (credential \${ENV})."
else
  echo "== canlı turn-taking/barge-in koordinasyon kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
