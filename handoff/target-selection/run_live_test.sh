#!/usr/bin/env bash
# WBS 9.5 — Kuyruk/skill/departman bazlı hedef seçimi (FR-TEL-008/FR-HND-003) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik hedef seçim motoru + statik doğrulama (sunucu gerektirmez).
# Gerçek kuyruk/skill/departman envanteri + canlı temsilci uygunluk F2 CC entegrasyonunda (11.x) gelir;
# seçilen hedef 9.1/9.2/9.3 mekanizma modüllerine iletilir, UNRESOLVED 9.7'ye yükselir.
# Vendor-neutral (ADR-001/002); sır/credential repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.5 target-selection: validate (statik spec/config/kapsama) =="
python3 target_selection_probe.py validate

echo
echo "== 9.5 target-selection: selftest (seçim motoru invariant'ları R1–R11) =="
python3 target_selection_probe.py selftest

echo
echo "== 9.5 target-selection: run (örnek senaryolar — 6 pass + 6 degrade) =="
python3 target_selection_probe.py run samples

echo
echo "== 9.5 target-selection: behavior test (R1–R10) =="
python3 tests/target_selection_behavior_test.py

echo
echo "Tümü 🟢 — F2 canlı hedef seçim testi gerçek CC skill-based routing + 9.1/9.2/9.3 ile (SKIP burada)."
