#!/usr/bin/env bash
# WBS 10.1.7 — Kampanya durdurma düğmesi (FR-OUT-010 / SR-OUT-010) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik kampanya kontrol durum makinesi + dialer admission
# kapısı + statik doğrulama (sunucu gerektirmez). Gerçek dialer çevirme (10.1.x outbound dialer)
# ve audit store (12.x) entegrasyonu F2'de gelir; bu modül onlara DIALER ADMISSION KAPISI
# sözleşmesini iletir (stop/pause → kapalı = yeni çağrı başlatılmaz, SR-OUT-010).
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.1.7 campaign-stop: validate (statik spec/config/kapsama) =="
python3 campaign_stop_probe.py validate

echo
echo "== 10.1.7 campaign-stop: selftest (kontrol motoru invariant'ları C1–C12) =="
python3 campaign_stop_probe.py selftest

echo
echo "== 10.1.7 campaign-stop: run (örnek senaryolar — 9 pass + 7 degrade) =="
python3 campaign_stop_probe.py run samples

echo
echo "== 10.1.7 campaign-stop: behavior test (C1–C12) =="
python3 tests/campaign_stop_behavior_test.py

echo
echo "Tümü 🟢 — F2 canlı dialer/audit testi gerçek entegrasyon (10.1.x/12.x) ile (SKIP burada)."
