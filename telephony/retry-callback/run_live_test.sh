#!/usr/bin/env bash
# WBS 2.1.8 — Kontrollü retry/geri arama statik + karar kapısı.
# Sunucu/credential GEREKMEZ. ${RETRY_CALLBACK_API_URL} verilirse canlı not düşülür (yine de SKIP).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
rc=0

echo "── validate (C1..C14 + 2.1.7 çapraz-tutarlılık) ───────────────"
"$PY" "$HERE/retry_callback_probe.py" validate || rc=1

echo "── selftest ───────────────────────────────────────────────────"
"$PY" "$HERE/retry_callback_probe.py" selftest || rc=1

echo "── decide samples ─────────────────────────────────────────────"
for s in "$HERE"/samples/decide-*.json; do
  name="$(basename "$s")"
  if [[ "$name" == *degraded* ]]; then
    # degraded bilinçli eler (C12 uyuşmazlık) → çıkış kodu 1 BEKLENEN
    if "$PY" "$HERE/retry_callback_probe.py" decide "$s" >/dev/null 2>&1; then
      echo "  ✗ $name beklenenin aksine GEÇTİ"; rc=1
    else
      echo "  ✓ $name beklendiği gibi ELENDİ (C12)"
    fi
  else
    "$PY" "$HERE/retry_callback_probe.py" decide "$s" >/dev/null && echo "  ✓ $name PASS" || { echo "  ✗ $name FAIL"; rc=1; }
  fi
done

echo "── simulate (C2 tavan) ────────────────────────────────────────"
"$PY" "$HERE/retry_callback_probe.py" simulate "$HERE/samples/simulate-exhaustion.json" || rc=1

echo "── behavior test (T1–T6) ──────────────────────────────────────"
"$PY" "$HERE/tests/retry_callback_behavior_test.py" || rc=1

if [[ -n "${RETRY_CALLBACK_API_URL:-}" ]]; then
  echo "NOT: canlı uç (${RETRY_CALLBACK_API_URL}) F1'de gerçek dialer + scheduler ile doğrulanır."
else
  echo "SKIP: canlı uç yok (RETRY_CALLBACK_API_URL tanımsız) — statik+karar kapısı yeterli."
fi

exit $rc
