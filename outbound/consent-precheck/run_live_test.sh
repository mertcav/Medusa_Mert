#!/usr/bin/env bash
# WBS 10.2.1 — Consent Engine ön-kontrol (FR-OUT-003 / SR-OUT-003 / SAD §19.1) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fail-closed altı-boyutlu consent kararı motoru + statik
# doğrulama (sunucu gerektirmez). Gerçek dialer çevirme (10.1.x), DNC/suppression (10.2.2), İYS/TPS
# registry adapter ve audit store (12.x) entegrasyonu F2'de gelir; bu modül onlara per-contact ALLOW|BLOCK
# kararını + block_reason'ı + consent_ok bayrağını (10.2.2 DNC AND girdisi) iletir.
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.2.1 consent-precheck: validate (statik spec/config/kapsama) =="
python3 consent_precheck_probe.py validate

echo
echo "== 10.2.1 consent-precheck: selftest (Consent motoru invariant'ları K1–K12) =="
python3 consent_precheck_probe.py selftest

echo
echo "== 10.2.1 consent-precheck: check (örnek senaryolar — 12 pass + 6 degrade) =="
python3 consent_precheck_probe.py check samples

echo
echo "== 10.2.1 consent-precheck: behavior test (K1–K12) =="
python3 tests/consent_precheck_behavior_test.py

echo
if [ -n "${CONSENT_ENGINE_URL:-}" ]; then
  echo "CONSENT_ENGINE_URL set: canlı consent gate çağrısı F2 entegrasyonunda (İYS/TPS adapter) — burada NOT."
else
  echo "Canlı consent gate (İYS/TPS registry + dialer 10.1.x) SKIP — \${CONSENT_ENGINE_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı dialer/DNC/registry/audit testi gerçek entegrasyon (10.1.x/10.2.2/12.x) ile (SKIP burada)."
