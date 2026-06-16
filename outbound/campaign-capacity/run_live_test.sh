#!/usr/bin/env bash
# WBS 10.2.6 — Kampanya kapasitesi ≤ agent+trunk kapasitesi (backpressure entegrasyonu)
# (FR-OUT-007 / SR-OUT-007 / FR-RES-014 / SAD §15.2 Resource Manager) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fail-closed / no-oversubscription kampanya-düzeyi admission +
# Little-sizing + backpressure kararı motoru + statik doğrulama (sunucu gerektirmez). Gerçek dialer pace
# (10.1.x), per-dial silent-call kapısı (10.2.4), runtime kapasite telemetri (0.4.7), tenant kota
# (FR-TEN-004/Quota Service) ve Resource Manager Backpressure Ctrl (SAD §15.2) entegrasyonu F2'de gelir;
# bu modül onlara kampanya-düzeyi ADMIT|PACE_DOWN|DEFER|BLOCK kararını + ceiling/design/effective/overflow'u
# iletir (effective ≤ ceiling garantisi + overflow muhasebeli graceful degrade).
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 10.2.6 campaign-capacity: validate (statik spec/config/kapsama) =="
python3 campaign_capacity_probe.py validate

echo
echo "== 10.2.6 campaign-capacity: selftest (Kampanya-kapasite motoru invariant'ları K1–K12) =="
python3 campaign_capacity_probe.py selftest

echo
echo "== 10.2.6 campaign-capacity: check (örnek senaryolar — 12 pass + 10 degrade) =="
python3 campaign_capacity_probe.py check samples

echo
echo "== 10.2.6 campaign-capacity: behavior test (K1–K12) =="
python3 tests/campaign_capacity_behavior_test.py

echo
if [ -n "${CAPACITY_PLANNER_URL:-}" ]; then
  echo "CAPACITY_PLANNER_URL set: canlı kampanya-kapasite admission çağrısı F2 entegrasyonunda (Resource Manager) — burada NOT."
else
  echo "Canlı kampanya-kapasite admission (runtime kapasite telemetri 0.4.7 + tenant kota Quota Service + Resource Manager Backpressure Ctrl + dialer 10.1.x + per-dial 10.2.4) SKIP — \${CAPACITY_PLANNER_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı Resource Manager/kapasite-telemetri/kota/dialer/per-dial/audit testi gerçek entegrasyon (SAD §15.2/0.4.7/10.1.x/10.2.4/12.x) ile (SKIP burada)."
