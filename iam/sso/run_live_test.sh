#!/usr/bin/env bash
# WBS 12.1.4 — SSO: SAML 2.0 + OIDC
# (FR-IAM-002 SAML 2.0 + OIDC kurumsal SSO / SR-IAM-002 / TC-IAM-002 / FR-IAM-008 tenant IdP L0 rolü atayamaz /
#  FR-TEN-002 tenant izolasyonu / SAD §14.4.4 grup→rol eşleme / SAD §13.3 / ADR-011/012/002)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed FEDERASYON karar motoru
# (imza/güven + audience + zaman + replay + tenant + realm gate → authenticate → grup→rol eşleme → GRANT|DENY|
# BLOCK) + statik model doğrulama (sunucu gerektirmez). 12.1.1 RBAC modelini (rol→immutable bundle + realm)
# TÜKETİR ve IdP grup/attribute'unu o roller'e eşler; ÇIKTI olarak {role, scope} ATAMA üretir — 12.1.3'ün
# TÜKETTİĞİ scoped atama yüzeyi. SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): imza/anahtar/JWKS doğrulaması burada
# YAPILMAZ (signature_valid soyut sonuç); canlı XML-DSig/JWS + IdP metadata + SCIM (12.1.6) + MFA (12.1.5) +
# backend panel guard (12.2.x) + WORM audit (12.1.8) F2 entegrasyonunda gelir; bu modül onlara KARARI + kanıtı +
# model bütünlük manifestini iletir (güven — S2; eşleme — S3; realm sınırı — S4; tenant izolasyonu — S7; replay — S8).
# Sır/credential/anahtar ve ham token/PII (NameID/e-posta/imza) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.1.4 sso: validate (statik sso/rbac model + spec + kapsama) =="
python3 sso_probe.py validate

echo
echo "== 12.1.4 sso: selftest (federasyon karar motoru invariant'ları S1–S12) =="
python3 sso_probe.py selftest

echo
echo "== 12.1.4 sso: check (örnek senaryolar — 10 pass + 11 degrade/güvenlik-olayı) =="
python3 sso_probe.py check samples

echo
echo "== 12.1.4 sso: behavior test (S1–S12) =="
python3 tests/sso_behavior_test.py

echo
if [ -n "${SSO_IDP_URL:-}" ]; then
  echo "SSO_IDP_URL set: canlı SAML2/OIDC login + XML-DSig/JWS + JWKS doğrulaması F2 entegrasyonunda (kurumsal IdP) — burada NOT."
else
  echo "Canlı SSO (canlı XML-DSig/JWS imza + IdP metadata/JWKS + SCIM 12.1.6 + backend panel guard 12.2.x + WORM audit 12.1.8) SKIP — \${SSO_IDP_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı SSO testi gerçek IdP federasyonu (SAD §14.4.4 / ADR-011) ile (SKIP burada)."
