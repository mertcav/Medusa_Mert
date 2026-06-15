#!/usr/bin/env bash
# WBS 9.2 — Warm transfer (köprüleme + whisper brifing) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik FSM + statik doğrulama (sunucu gerektirmez).
# Gerçek danışma INVITE/hold/köprü canlı testi F1'de gerçek trunk + TelephonyAdapter (4.2.5) ile koşar.
# Vendor-neutral (ADR-002); sır/credential repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.2 warm-transfer: validate (statik spec/config/kapsama) =="
python3 warm_transfer_probe.py validate

echo
echo "== 9.2 warm-transfer: selftest (FSM davranış invariant'ları) =="
python3 warm_transfer_probe.py selftest

echo
echo "== 9.2 warm-transfer: run (örnek senaryolar — pass + degrade) =="
python3 warm_transfer_probe.py run samples

echo
echo "== 9.2 warm-transfer: behavior test (T1–T7) =="
python3 tests/warm_transfer_behavior_test.py

echo
echo "Tümü 🟢 — F1 canlı danışma/köprü testi gerçek trunk/4.2.5 adapter ile (SKIP burada)."
