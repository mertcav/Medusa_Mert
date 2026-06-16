#!/usr/bin/env bash
# WBS 12.1.5 — MFA (çok faktörlü kimlik doğrulama)
# (FR-IAM-003 MFA / SR-IAM-003 ayrıcalıklı roller için MFA zorunlu, faktörsüz erişim reddi / TC-IAM-003 /
#  FR-TEN-002 tenant izolasyonu / ADR-017 phishing-resistant MFA WebAuthn/FIDO2 L0+break-glass / SAD §14.1 / ADR-011/002)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed MFA DOĞRULAMA karar motoru
# (politika çözümü most-restrictive-wins → kilit → faktör-varlığı → doğrulama → phishing → AAL → zaman gate →
# PASS|CHALLENGE|DENY|BLOCK) + statik model doğrulama (sunucu gerektirmez). 12.1.1 RBAC modelini (rol→realm+layer)
# TÜKETİR (ayrıcalık/AAL gereksinimini çözmek için) ve 12.1.4 SSO authenticate'in ÜSTÜNDE step-up uygular.
# SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): kriptografik faktör doğrulaması (WebAuthn attestation/assertion,
# TOTP HMAC, OTP teslimi) burada YAPILMAZ (factor.verified soyut sonuç; AAL/phishing-direnci katalogdan türetilir);
# canlı WebAuthn/TOTP/OTP + backend panel guard (12.2.x) + break-glass (12.3.x) + WORM audit (12.1.8) F2
# entegrasyonunda gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini iletir (faktör bütünlüğü — S2;
# phishing-direnci — S4; AAL — S3; politika — S5; tenant izolasyonu — S7; replay/kilit — S8).
# Sır/credential/faktör sırrı (TOTP seed, WebAuthn key) ve ham OTP/PII (NameID/e-posta) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.1.5 mfa: validate (statik mfa/rbac model + spec + kapsama) =="
python3 mfa_probe.py validate

echo
echo "== 12.1.5 mfa: selftest (MFA karar motoru invariant'ları S1–S12) =="
python3 mfa_probe.py selftest

echo
echo "== 12.1.5 mfa: check (örnek senaryolar — 10 pass + 10 degrade/güvenlik-olayı) =="
python3 mfa_probe.py check samples

echo
echo "== 12.1.5 mfa: behavior test (S1–S12) =="
python3 tests/mfa_behavior_test.py

echo
if [ -n "${MFA_IDP_URL:-}" ]; then
  echo "MFA_IDP_URL set: canlı WebAuthn/FIDO2 attestation + TOTP/OTP doğrulaması F2 entegrasyonunda (kurumsal IdP/authenticator) — burada NOT."
else
  echo "Canlı MFA (canlı WebAuthn/FIDO2 + TOTP/OTP doğrulaması + backend panel guard 12.2.x + break-glass 12.3.x + WORM audit 12.1.8) SKIP — \${MFA_IDP_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı MFA testi gerçek authenticator (WebAuthn/FIDO2 — ADR-017) ile (SKIP burada)."
