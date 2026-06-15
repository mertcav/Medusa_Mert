#!/usr/bin/env bash
# WBS 10.2.2 — Do-not-call / suppression gerçek zamanlı kontrol (FR-TEL-014 + FR-OUT-006 /
# SR-TEL-014 + SR-OUT-006 / SAD §19.1) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fail-closed beş-kaynak any-hit suppression kararı motoru
# + statik doğrulama (sunucu gerektirmez). Gerçek dialer çevirme (10.1.x), consent ön-kontrol (10.2.1
# AND'lenir), İYS/TPS registry adapter ve audit store (12.x) entegrasyonu F2'de gelir; bu modül onlara
# per-contact ALLOW|BLOCK kararını + block_reason'ı + dnc_ok bayrağını (10.2.1 consent AND girdisi) iletir.
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.2.2 dnc-suppression: validate (statik spec/config/kapsama) =="
python3 dnc_suppression_probe.py validate

echo
echo "== 10.2.2 dnc-suppression: selftest (Suppression motoru invariant'ları K1–K12) =="
python3 dnc_suppression_probe.py selftest

echo
echo "== 10.2.2 dnc-suppression: check (örnek senaryolar — 12 pass + 8 degrade) =="
python3 dnc_suppression_probe.py check samples

echo
echo "== 10.2.2 dnc-suppression: behavior test (K1–K12) =="
python3 tests/dnc_suppression_behavior_test.py

echo
if [ -n "${DNC_ENGINE_URL:-}" ]; then
  echo "DNC_ENGINE_URL set: canlı suppression gate çağrısı F2 entegrasyonunda (İYS/TPS adapter) — burada NOT."
else
  echo "Canlı suppression gate (İYS/TPS registry + dialer 10.1.x) SKIP — \${DNC_ENGINE_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı dialer/consent/registry/audit testi gerçek entegrasyon (10.1.x/10.2.1/12.x) ile (SKIP burada)."
