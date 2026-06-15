#!/usr/bin/env bash
# WBS 9.4 — Transfer tetikleyiciler (FR-HND-001/002) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik değerlendirme motoru + statik doğrulama (sunucu gerektirmez).
# Gerçek confidence/sentiment/intent sinyalleri F1 canlı PoC'ta STT/NLU/duygu modüllerinden gelir;
# tetik kararı 9.1/9.2/9.3 mekanizma modüllerine iletilir.
# Vendor-neutral (ADR-001/002); sır/credential repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.4 transfer-triggers: validate (statik spec/config/kapsama) =="
python3 transfer_triggers_probe.py validate

echo
echo "== 9.4 transfer-triggers: selftest (değerlendirme motoru invariant'ları T1–T11) =="
python3 transfer_triggers_probe.py selftest

echo
echo "== 9.4 transfer-triggers: run (örnek senaryolar — 6 pass + 6 degrade) =="
python3 transfer_triggers_probe.py run samples

echo
echo "== 9.4 transfer-triggers: behavior test (T1–T9) =="
python3 tests/transfer_triggers_behavior_test.py

echo
echo "Tümü 🟢 — F1 canlı tetik testi gerçek STT/NLU/sentiment sinyalleri + 9.1/9.2/9.3 ile (SKIP burada)."
