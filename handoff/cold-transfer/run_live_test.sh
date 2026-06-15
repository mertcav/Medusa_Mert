#!/usr/bin/env bash
# WBS 9.1 — Cold transfer (SIP REFER) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik FSM + statik doğrulama (sunucu gerektirmez).
# Gerçek SIP REFER/NOTIFY canlı testi F1'de gerçek trunk + TelephonyAdapter (4.2.5) ile koşar.
# Vendor-neutral (ADR-002); sır/credential repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.1 cold-transfer: validate (statik spec/config/kapsama) =="
python3 cold_transfer_probe.py validate

echo
echo "== 9.1 cold-transfer: selftest (FSM davranış invariant'ları) =="
python3 cold_transfer_probe.py selftest

echo
echo "== 9.1 cold-transfer: run (örnek senaryolar — pass + degrade) =="
python3 cold_transfer_probe.py run samples

echo
echo "== 9.1 cold-transfer: behavior test (T1–T6) =="
python3 tests/cold_transfer_behavior_test.py

echo
echo "Tümü 🟢 — F1 canlı SIP REFER testi gerçek trunk/4.2.5 adapter ile (SKIP burada)."
