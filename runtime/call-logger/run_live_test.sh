#!/usr/bin/env bash
# run_live_test.sh — WBS 14.1.4 yapılandırılmış asenkron + örneklemeli loglama kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir Conversation
# Orchestrator runtime uç noktası (${ORCHESTRATOR_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/call_logger_probe.py" validate
"$PY" "$HERE/call_logger_probe.py" selftest
"$PY" "$HERE/tests/call_logger_behavior_test.py"

echo "== sample emit kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/call_logger_probe.py" emit "$s"
done

if [[ -n "${ORCHESTRATOR_URL:-}" ]]; then
  echo "== canlı log üretim kapısı (${ORCHESTRATOR_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3)"
  echo "     bounded ring buffer + non-blocking enqueue + OpenTelemetry/Loki backend (SAD §11/§17.1) log"
  echo "     hattıyla koşulur: yapılandırılmış (structured JSON) kayıt required gövde anahtarları taşır"
  echo "     (tenant_id/correlation_id/level/event/ts; 0.4.7 trace_log_required_keys), HEAD-BASED örneklenir"
  echo "     (base_rate=0.2; 0.4.7 logs_base_rate) + logs_always (WARN+/security/audit) HER ZAMAN tutulur,"
  echo "     ASENKRON/non-blocking yazım hot-path'i BLOKLAMAZ (SR-RES-012; §20 gecikme bütçesi korunur),"
  echo "     stream label DÜŞÜK kardinalite (tenant_id/region/service/level; correlation_id/call_id GÖVDE"
  echo "     alanı — Loki 0.4.7), label/gövde PII yok (FR-REC-004) ve AUDIT (FR-IAM-006 WORM) ASLA örneklenmez"
  echo "     + AYRI WORM sink'e yönlenir. Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı log üretim kapısı: SKIP (ORCHESTRATOR_URL tanımsız) =="
fi
echo "OK"
