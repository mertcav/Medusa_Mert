#!/usr/bin/env bash
# WBS 12.1.3 — Scoped assignment (rol + departman/marka/kampanya filtresi)
# (FR-IAM-011 sabit bundle + scope filtresi / SR-IAM-011 / TC-IAM-011 / FR-TEN-002 tenant izolasyonu /
#  FR-IAM-008 L0 ⟂ tenant / SAD §14.4.2 / ADR-012)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed KAPSAM-DARALTMA karar
# motoru (12.1.1 rol→immutable bundle permission gate + department/brand/campaign scope gate; narrowing-only)
# + statik model doğrulama (sunucu gerektirmez). 12.1.1 RBAC modelini TÜKETİR ve atamanın KAPSAMINI kaynak
# attribute'larına karşı süzer → GRANT|DENY|BLOCK. Gerçek IAM (scoped backend guard 12.2.x: permission-key +
# scope kaynak attribute + RLS çift kontrol + IdP/SCIM rol+scope atama 12.1.4/12.1.6 + break-glass 12.3.x +
# WORM audit 12.1.8) entegrasyonu F2'de gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini
# iletir (narrowing-only — S2; tenant izolasyonu — S7; immutable bundle korunur — S8).
# Vendor-neutral (ADR-001/002/011/012); sır/credential ve ham içerik (PII değeri) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.1.3 scoped-assignment: validate (statik scope/rbac model + spec + kapsama) =="
python3 scoped_assignment_probe.py validate

echo
echo "== 12.1.3 scoped-assignment: selftest (kapsam-daraltma motoru invariant'ları S1–S12) =="
python3 scoped_assignment_probe.py selftest

echo
echo "== 12.1.3 scoped-assignment: check (örnek senaryolar — 10 pass + 10 degrade) =="
python3 scoped_assignment_probe.py check samples

echo
echo "== 12.1.3 scoped-assignment: behavior test (S1–S12) =="
python3 tests/scoped_assignment_behavior_test.py

echo
if [ -n "${SCOPED_ASSIGNMENT_URL:-}" ]; then
  echo "SCOPED_ASSIGNMENT_URL set: canlı kapsam-duyarlı yetki karar çağrısı F2 entegrasyonunda (scoped guard + IAM) — burada NOT."
else
  echo "Canlı scoped assignment (12.2.x scoped backend guard enforcement + IdP/SCIM rol+scope atama + 12.3.x break-glass + 12.1.8 WORM audit) SKIP — \${SCOPED_ASSIGNMENT_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı IAM testi gerçek entegrasyon (SAD §14.4.2 / ADR-012) ile (SKIP burada)."
