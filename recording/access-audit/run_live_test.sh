#!/usr/bin/env bash
# WBS 11.6 — Kayıt/transkript erişim audit'i
# (FR-REC-009 / SR-REC-009 / TC-REC-009 / FR-REC-008 / FR-IAM-006 WORM audit +
#  FR-IAM-008/009/010 L0 altın kural + break-glass / DB §27 audit_log)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed erişim-audit
# (yetki + ZORUNLU WORM audit hash chain + L0 Tier B break-glass) kararı motoru + statik doğrulama
# (sunucu gerektirmez). 11.1–11.4 İÇERİK ÜRETİM ZİNCİRİNİN aşağı akış ERİŞİM KAPISIDIR; her kayıt/
# transkript erişiminin yetkisini + audit'ini güvence altına alır. Gerçek audit_log (DB §27 WORM partition
# yazımı + hash chain depolama) + IAM (RBAC permission + break-glass router) + panel L2 (içerik sunumu)
# entegrasyonu F1'de gelir; bu modül onlara GRANTED|DENIED|BLOCK erişim KARARINI + WORM audit KAYDINI
# iletir (auditlenemeyen erişim YOK — K2/K5; yetkisiz GRANTED YOK — K4; hash chain bütünlük — K3).
# Vendor-neutral (ADR-001/002/011/012/013); sır/credential ve ham içerik (kayıt byte/transkript metni/PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 11.6 access-audit: validate (statik spec/config/kapsama) =="
python3 access_audit_probe.py validate

echo
echo "== 11.6 access-audit: selftest (erişim-audit motoru invariant'ları K1–K12) =="
python3 access_audit_probe.py selftest

echo
echo "== 11.6 access-audit: check (örnek senaryolar — 13 pass + 12 degrade) =="
python3 access_audit_probe.py check samples

echo
echo "== 11.6 access-audit: behavior test (K1–K12) =="
python3 tests/access_audit_behavior_test.py

echo
if [ -n "${ACCESS_AUDIT_URL:-}" ]; then
  echo "ACCESS_AUDIT_URL set: canlı erişim-audit karar çağrısı F1 entegrasyonunda (audit_log + IAM) — burada NOT."
else
  echo "Canlı erişim audit (DB §27 audit_log WORM partition yazımı + hash chain depolama + IAM RBAC/break-glass router FR-IAM-009 + panel L2 A-11/A-12/A-13 içerik sunumu + residency DB §8) SKIP — \${ACCESS_AUDIT_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı audit_log/IAM/panel testi gerçek entegrasyon (DB §27 / SAD §14.4 / SAD §10.2) ile (SKIP burada)."
