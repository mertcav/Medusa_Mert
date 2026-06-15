#!/usr/bin/env bash
# WBS 10.1.8 — A/B test kampanyaları (FR-OUT-012 / SR-OUT-012) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik varyant dağıtım + karşılaştırma motoru + statik doğrulama
# (sunucu gerektirmez). Gerçek dialer çevirme (10.1.x outbound dialer), disposition üretimi (10.1.5) ve
# audit store (12.x) entegrasyonu F2'de gelir; bu modül onlara PER-CONTACT VARYANT ATAMASINI
# (variant_id + script_version) ve KARŞILAŞTIRMA SONUCUNU (winner|inconclusive) iletir.
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.1.8 ab-testing: validate (statik spec/config/kapsama) =="
python3 ab_testing_probe.py validate

echo
echo "== 10.1.8 ab-testing: selftest (A/B motoru invariant'ları C1–C12) =="
python3 ab_testing_probe.py selftest

echo
echo "== 10.1.8 ab-testing: run (örnek senaryolar — 9 pass + 8 degrade) =="
python3 ab_testing_probe.py run samples

echo
echo "== 10.1.8 ab-testing: behavior test (C1–C12) =="
python3 tests/ab_testing_behavior_test.py

echo
echo "Tümü 🟢 — F2 canlı dialer/disposition/audit testi gerçek entegrasyon (10.1.x/10.1.5/12.x) ile (SKIP burada)."
