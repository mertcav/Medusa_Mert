#!/usr/bin/env bash
# WBS 10.2.3 — Ülke/bölge arama saati kuralları (FR-TEL-013 + FR-OUT-004 /
# SR-TEL-013 + SR-OUT-004 / SAD §19.1) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fail-closed konjonktif dört-kural yerel-saat arama saati
# kararı motoru + statik doğrulama (sunucu gerektirmez). Gerçek dialer çevirme (10.1.x), consent ön-kontrol
# (10.2.1) + DNC/suppression (10.2.2) AND'lenir, saat dilimi/DST adapter (ADR-002) ve audit store (12.x)
# entegrasyonu F2'de gelir; bu modül onlara per-contact ALLOW|BLOCK kararını + block_reason'ı + hours_ok
# bayrağını (eligible = consent_ok AND dnc_ok AND hours_ok) iletir.
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.2.3 calling-hours: validate (statik spec/config/kapsama) =="
python3 calling_hours_probe.py validate

echo
echo "== 10.2.3 calling-hours: selftest (Arama saati motoru invariant'ları K1–K12) =="
python3 calling_hours_probe.py selftest

echo
echo "== 10.2.3 calling-hours: check (örnek senaryolar — 12 pass + 9 degrade) =="
python3 calling_hours_probe.py check samples

echo
echo "== 10.2.3 calling-hours: behavior test (K1–K12) =="
python3 tests/calling_hours_behavior_test.py

echo
if [ -n "${HOURS_ENGINE_URL:-}" ]; then
  echo "HOURS_ENGINE_URL set: canlı arama saati gate çağrısı F2 entegrasyonunda (tz/DST adapter) — burada NOT."
else
  echo "Canlı arama saati gate (tz/DST adapter + dialer 10.1.x) SKIP — \${HOURS_ENGINE_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı dialer/consent/DNC/tz-adapter/audit testi gerçek entegrasyon (10.1.x/10.2.1/10.2.2/12.x) ile (SKIP burada)."
