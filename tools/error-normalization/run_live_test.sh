#!/usr/bin/env bash
# WBS 7.1.5 — Hata normalizasyonu statik + davranış kapısı koşucusu.
# Bu motor SAF eşlemedir (I/O yok) → canlı bağımlılık gerektirmez; statik kapı tam doğrular.
# Vendor-neutral (ADR-002); sır/credential gerekmez ve yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PY="${PYTHON:-python3}"
rc=0

echo "== validate (statik spec/config/katalog/şema kapısı) =="
$PY error_normalization_probe.py validate || rc=1

echo "== selftest (gömülü davranış N1–N12) =="
$PY error_normalization_probe.py selftest || rc=1

echo "== behavior test (sızıntı tarayıcısı + müşteri/audit ayrımı) =="
$PY tests/leak_behavior_test.py || rc=1

echo "== samples (normalize kapısı; degraded BEKLENEN 🔴) =="
for s in samples/*.json; do
  echo "-- $s --"
  if $PY error_normalization_probe.py normalize "$s" >/dev/null 2>&1; then
    sres="🟢 GEÇTI"
  else
    sres="🔴 ELENDI"
  fi
  # degraded kasıtlı eler; gerçek başarı validate'te (expect_fail) doğrulanır
  echo "   $sres"
done

if [ "$rc" -eq 0 ]; then
  echo "SONUÇ: 🟢 tüm statik+davranış kapıları geçti"
else
  echo "SONUÇ: 🔴 kapı(lar) başarısız"
fi
exit $rc
