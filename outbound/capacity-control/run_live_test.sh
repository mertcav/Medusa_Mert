#!/usr/bin/env bash
# WBS 10.2.4 — Silent/abandoned call önleme (kapasite kontrolü) (FR-TEL-015 /
# SR-TEL-015 / SAD §19.1) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fail-closed konjonktif dört-kural per-dial kapasite/silent-call
# kararı motoru + statik doğrulama (sunucu gerektirmez). Gerçek dialer çevirme (10.1.x), consent ön-kontrol
# (10.2.1) + DNC/suppression (10.2.2) + arama saati (10.2.3) AND'lenir, runtime kapasite telemetri (0.4.7/0.4.8)
# ve kampanya-düzeyi backpressure (10.2.6) entegrasyonu F2'de gelir; bu modül onlara per-contact ALLOW|BLOCK
# kararını + block_reason'ı + capacity_ok bayrağını (eligible = consent_ok AND dnc_ok AND hours_ok AND capacity_ok)
# iletir.
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.2.4 capacity-control: validate (statik spec/config/kapsama) =="
python3 capacity_control_probe.py validate

echo
echo "== 10.2.4 capacity-control: selftest (Kapasite motoru invariant'ları K1–K12) =="
python3 capacity_control_probe.py selftest

echo
echo "== 10.2.4 capacity-control: check (örnek senaryolar — 12 pass + 9 degrade) =="
python3 capacity_control_probe.py check samples

echo
echo "== 10.2.4 capacity-control: behavior test (K1–K12) =="
python3 tests/capacity_control_behavior_test.py

echo
if [ -n "${CAPACITY_ENGINE_URL:-}" ]; then
  echo "CAPACITY_ENGINE_URL set: canlı kapasite gate çağrısı F2 entegrasyonunda (runtime telemetri) — burada NOT."
else
  echo "Canlı kapasite gate (runtime kapasite telemetri 0.4.7/0.4.8 + dialer 10.1.x + 10.2.6 backpressure) SKIP — \${CAPACITY_ENGINE_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı dialer/consent/DNC/arama-saati/kapasite-telemetri/audit testi gerçek entegrasyon (10.1.x/10.2.1/10.2.2/10.2.3/10.2.6/12.x) ile (SKIP burada)."
