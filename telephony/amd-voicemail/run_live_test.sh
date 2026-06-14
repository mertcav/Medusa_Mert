#!/usr/bin/env bash
# WBS 2.1.9 — AMD + voicemail bırakma statik + karar kapısı.
# Sunucu/credential GEREKMEZ. ${AMD_API_URL} verilirse canlı not düşülür (yine de SKIP).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
rc=0

echo "── validate (A1..A14 + 2.1.7 çapraz-tutarlılık) ───────────────"
"$PY" "$HERE/amd_voicemail_probe.py" validate || rc=1

echo "── selftest ───────────────────────────────────────────────────"
"$PY" "$HERE/amd_voicemail_probe.py" selftest || rc=1

echo "── classify samples ───────────────────────────────────────────"
for s in "$HERE"/samples/classify-*.json; do
  name="$(basename "$s")"
  "$PY" "$HERE/amd_voicemail_probe.py" classify "$s" >/dev/null && echo "  ✓ $name PASS" || { echo "  ✗ $name FAIL"; rc=1; }
done

echo "── drop samples ───────────────────────────────────────────────"
for s in "$HERE"/samples/drop-*.json; do
  name="$(basename "$s")"
  if [[ "$name" == *degraded* ]]; then
    # degraded bilinçli eler (insan → drop hatası, A12) → çıkış kodu 1 BEKLENEN
    if "$PY" "$HERE/amd_voicemail_probe.py" drop "$s" >/dev/null 2>&1; then
      echo "  ✗ $name beklenenin aksine GEÇTİ"; rc=1
    else
      echo "  ✓ $name beklendiği gibi ELENDİ (A12)"
    fi
  else
    "$PY" "$HERE/amd_voicemail_probe.py" drop "$s" >/dev/null && echo "  ✓ $name PASS" || { echo "  ✗ $name FAIL"; rc=1; }
  fi
done

echo "── accuracy (SR-TEL-010 T) ────────────────────────────────────"
"$PY" "$HERE/amd_voicemail_probe.py" accuracy "$HERE/samples/accuracy-labeled-set.json" || rc=1
# degraded küme accuracy_gate'i ELEMELİ (çıkış kodu 1 BEKLENEN)
if "$PY" "$HERE/amd_voicemail_probe.py" accuracy "$HERE/samples/accuracy-degraded.json" >/dev/null 2>&1; then
  echo "  ✗ accuracy-degraded beklenenin aksine GEÇTİ"; rc=1
else
  echo "  ✓ accuracy-degraded beklendiği gibi ELENDİ (false_machine/accuracy kapısı)"
fi

echo "── behavior test (T1–T6) ──────────────────────────────────────"
"$PY" "$HERE/tests/amd_voicemail_behavior_test.py" || rc=1

if [[ -n "${AMD_API_URL:-}" ]]; then
  echo "NOT: canlı uç (${AMD_API_URL}) F1'de gerçek CPaaS AMD + medya egress (voicemail) ile doğrulanır."
else
  echo "SKIP: canlı uç yok (AMD_API_URL tanımsız) — statik+karar kapısı yeterli."
fi

exit $rc
