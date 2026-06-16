#!/usr/bin/env bash
# WBS 12.1.6 — SCIM provisioning + IdP grup→rol eşleme
# (FR-IAM-007 SCIM kullanıcı/grup provisioning / SR-IAM-007 / TC-IAM-007 / FR-IAM-008 tenant IdP L0 rolü provision
#  edemez / FR-TEN-002 tenant izolasyonu / SAD §14.4.4 SCIM 2.0 provisioning + deprovision → erişim anında düşer /
#  ADR-011/012/002)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed PROVISIONING karar motoru
# (auth + şema + tenant + version gate → lifecycle → DEPROVISION[erişim ANINDA ∅ + oturum iptali] | grup→rol eşleme
# → PROVISIONED|NO_ACCESS|REJECTED) + statik model doğrulama (sunucu gerektirmez). 12.1.1 RBAC modelini (rol→immutable
# bundle + realm) TÜKETİR; grup→rol eşleme tablosunu (idp_config.group_role_map) 12.1.4 SSO ile AYNI yüzey olarak
# kullanır ve kullanıcı/grup YAŞAM DÖNGÜSÜYLE birleştirir; ÇIKTI olarak etkin erişim ({role,scope} ATAMA) üretir —
# 12.1.3'ün TÜKETTİĞİ scoped atama yüzeyi. SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): bearer/mTLS doğrulaması burada
# YAPILMAZ (scim_client.authenticated soyut sonuç); canlı SCIM 2.0 endpoint (RFC 7644) + token + IdP senkronu +
# backend panel guard (12.2.x; deprovision → oturum iptali) + WORM audit (12.1.8) F2 entegrasyonunda gelir; bu modül
# onlara KARARI + kanıtı + model bütünlük manifestini iletir (auth — S2; deprovision — S3 ÇEKİRDEK; realm sınırı — S4;
# eşleme — S5; idempotency — S6; tenant izolasyonu — S7). Sır/credential/anahtar ve ham token/PII (bearer/NameID/e-posta) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.1.6 scim: validate (statik scim/rbac model + spec + kapsama) =="
python3 scim_probe.py validate

echo
echo "== 12.1.6 scim: selftest (provisioning karar motoru invariant'ları S1–S12) =="
python3 scim_probe.py selftest

echo
echo "== 12.1.6 scim: check (örnek senaryolar — 15 pass + 10 degrade/güvenlik-olayı) =="
python3 scim_probe.py check samples

echo
echo "== 12.1.6 scim: behavior test (S1–S12) =="
python3 tests/scim_behavior_test.py

echo
if [ -n "${SCIM_ENDPOINT_URL:-}" ]; then
  echo "SCIM_ENDPOINT_URL set: canlı SCIM 2.0 (RFC 7644) provisioning + bearer/mTLS token doğrulaması + IdP senkronu F2 entegrasyonunda (kurumsal IdP) — burada NOT."
else
  echo "Canlı SCIM (canlı SCIM 2.0 endpoint + bearer/mTLS token + IdP kullanıcı/grup senkronu + backend panel guard 12.2.x deprovision oturum iptali + WORM audit 12.1.8) SKIP — \${SCIM_ENDPOINT_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı SCIM testi gerçek IdP provisioning (SAD §14.4.4 / ADR-011) ile (SKIP burada)."
