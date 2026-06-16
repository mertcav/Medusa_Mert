#!/usr/bin/env bash
# WBS 12.1.1 — RBAC modeli (rol→permission-key bundle, immutable)
# (FR-IAM-001 RBAC + FR-IAM-011 immutable bundle / SR-IAM-001/011 / TC-IAM-001/011 /
#  FR-IAM-008 L0 ⟂ tenant / SAD §14.4.3 / ADR-012)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed RBAC yetki
# (rol→immutable bundle çözümü + permission değerlendirme + :own sahiplik + L0 altın kuralı) kararı motoru
# + statik model doğrulama (sunucu gerektirmez). BRD §17.2 rol seti + SAD §14.4.3 rol→permission-key
# haritasını FROZEN modele dönüştürür ve GRANT|DENY|BLOCK kararını üretir. Gerçek IAM (RBAC backend guard
# 12.2.x + scoped assignment 12.1.3 + IdP/SCIM rol eşleme 12.1.4/12.1.6 + break-glass 12.3.x + WORM audit
# 12.1.8) entegrasyonu F1'de gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini iletir
# (immutability — K2; backend authz — K3; L0 ⟂ tenant — K4/K7).
# Vendor-neutral (ADR-001/002/011/012); sır/credential ve ham içerik (PII değeri) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.1.1 rbac-model: validate (statik model/spec/kapsama) =="
python3 rbac_model_probe.py validate

echo
echo "== 12.1.1 rbac-model: selftest (RBAC yetki motoru invariant'ları K1–K12) =="
python3 rbac_model_probe.py selftest

echo
echo "== 12.1.1 rbac-model: check (örnek senaryolar — 10 pass + 8 degrade) =="
python3 rbac_model_probe.py check samples

echo
echo "== 12.1.1 rbac-model: behavior test (K1–K12) =="
python3 tests/rbac_model_behavior_test.py

echo
if [ -n "${RBAC_MODEL_URL:-}" ]; then
  echo "RBAC_MODEL_URL set: canlı RBAC yetki karar çağrısı F1 entegrasyonunda (backend guard + IAM) — burada NOT."
else
  echo "Canlı RBAC (12.2.x backend guard enforcement + 12.1.3 scoped assignment + IdP/SCIM rol eşleme + 12.3.x break-glass + 12.1.8 WORM audit) SKIP — \${RBAC_MODEL_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM testi gerçek entegrasyon (SAD §14.4 / ADR-012) ile (SKIP burada)."
