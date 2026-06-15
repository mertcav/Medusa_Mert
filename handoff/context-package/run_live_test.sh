#!/usr/bin/env bash
# WBS 9.6 — Bağlam paketi (özet + intent + toplanan alanlar + auth durumu) + screen-pop
# (FR-HND-004/FR-HND-005) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik paket derleyici/teslim motoru + statik doğrulama
# (sunucu gerektirmez). Gerçek CTI/CRM screen-pop kanal entegrasyonu F1/F2 CC entegrasyonunda (11.x)
# gelir; paket 9.1/9.2/9.3 mekanizma modüllerine iletilir, screen-pop yoksa verbal/transkript fallback.
# Vendor-neutral (ADR-001/002); sır/credential ve gerçek PII (müşteri adı/telefon/OTP) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.6 context-package: validate (statik spec/config/kapsama) =="
python3 context_package_probe.py validate

echo
echo "== 9.6 context-package: selftest (paket derleyici invariant'ları P1–P12) =="
python3 context_package_probe.py selftest

echo
echo "== 9.6 context-package: run (örnek senaryolar — 6 pass + 7 degrade) =="
python3 context_package_probe.py run samples

echo
echo "== 9.6 context-package: behavior test (P1–P12) =="
python3 tests/context_package_behavior_test.py

echo
echo "Tümü 🟢 — F1/F2 canlı screen-pop testi gerçek CTI/CRM + 9.1/9.2/9.3 ile (SKIP burada)."
