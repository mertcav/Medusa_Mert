#!/usr/bin/env bash
# WBS 2.1.7 — Çağrı neden kodları statik + davranış kapısı.
# Sunucu/credential GEREKMEZ. ${REASON_CODES_API_URL} verilirse canlı not düşülür (yine de SKIP).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
rc=0

echo "── validate (R1..R13) ─────────────────────────────────────────"
"$PY" "$HERE/reason_codes_probe.py" validate || rc=1

echo "── selftest ───────────────────────────────────────────────────"
"$PY" "$HERE/reason_codes_probe.py" selftest || rc=1

echo "── classify samples ───────────────────────────────────────────"
for s in "$HERE"/samples/classify-*.json; do
  name="$(basename "$s")"
  if [[ "$name" == *degraded* ]]; then
    # degraded bilinçli eler (R4 fallback) → çıkış kodu 1 BEKLENEN
    if "$PY" "$HERE/reason_codes_probe.py" classify "$s" >/dev/null 2>&1; then
      echo "  ✗ $name beklenenin aksine GEÇTİ"; rc=1
    else
      echo "  ✓ $name beklendiği gibi ELENDİ (R4)"
    fi
  else
    "$PY" "$HERE/reason_codes_probe.py" classify "$s" >/dev/null && echo "  ✓ $name PASS" || { echo "  ✗ $name FAIL"; rc=1; }
  fi
done

echo "── behavior test (T1–T6) ──────────────────────────────────────"
"$PY" "$HERE/tests/reason_codes_behavior_test.py" || rc=1

if [[ -n "${REASON_CODES_API_URL:-}" ]]; then
  echo "NOT: canlı uç (${REASON_CODES_API_URL}) F1'de gerçek telefoni adaptörüyle doğrulanır."
else
  echo "SKIP: canlı uç yok (REASON_CODES_API_URL tanımsız) — statik+davranış kapısı yeterli."
fi

exit $rc
