#!/usr/bin/env bash
# WBS 9.3 — Whisper transfer statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik FSM + statik doğrulama (sunucu gerektirmez).
# Gerçek konferans INVITE/per-leg whisper karışım canlı testi F1/F2'de gerçek trunk + TelephonyAdapter (4.2.5) ile koşar.
# Vendor-neutral (ADR-002); sır/credential repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.3 whisper-transfer: validate (statik spec/config/kapsama) =="
python3 whisper_transfer_probe.py validate

echo
echo "== 9.3 whisper-transfer: selftest (FSM davranış invariant'ları) =="
python3 whisper_transfer_probe.py selftest

echo
echo "== 9.3 whisper-transfer: run (örnek senaryolar — pass + degrade) =="
python3 whisper_transfer_probe.py run samples

echo
echo "== 9.3 whisper-transfer: behavior test (T1–T8) =="
python3 tests/whisper_transfer_behavior_test.py

echo
echo "Tümü 🟢 — F1/F2 canlı konferans/per-leg whisper testi gerçek trunk/4.2.5 adapter ile (SKIP burada)."
