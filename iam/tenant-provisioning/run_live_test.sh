#!/usr/bin/env bash
# WBS 12.4.1 — Tenant CRUD + provisioning (L0)
# (FR-TEN-001 'Platform birden fazla kurumsal müşteriyi tenant bazında yönetmelidir' /
#  BRD §17 'tenant oluşturma/askıya alma/silme, plan atama, kaynak kotası → Platform Admin Console (L0)' /
#  DB.md §5.1 tenant tablosu [status/isolation_mode/home_region/kms_key_ref] + §9 geri döndürülemez silme /
#  NFR 10.6 tenant başına ayrı KMS key / NFR 10.7 residency UK/EU/NA/ME / FR-IAM-008 L0⟂tenant realm /
#  ADR-011 iki düzlemli panel / ADR-012 sabit rol bundle)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed L0 tenant yaşam döngüsü
# karar motoru (durum makinesi [create→provisioning→activate→active→suspend↔resume→terminate→terminated] +
# realm izolasyonu [platform-only] + yetkilendirme [op→permission-key tenant:provision/tenant:suspend] +
# geçiş geçerliliği [terminated terminal] + provisioning tamlığı [zorunlu izolasyon/residency alanları +
# tenant başına KMS] + idempotency + geri döndürülemez terminate koruması + WORM audit) → COMMIT|REJECT.
# 12.1.2 permission-catalog (tenant:provision/tenant:suspend MEVCUT) + 12.1.1 rbac-model (platform_owner
# bundle) + 12.2.4 l0-repo-independence (tenant=platform sınıf; tenant_provisioning_repo PERMIT) + 12.1.8
# worm-audit RESİPROKAL bağlantılarını TÜKETİR. Gerçek L0 FastAPI tenant router + tenant tablosu repository +
# KMS key tahsisi + retention motoru bağı F1 kod aşamasında gelir; bu modül onlara KARARI + kanıtı + model
# bütünlük manifestini iletir. Vendor-neutral (ADR-002/011); sır/credential (KMS key materyali / DB şifresi /
# connection string) ve ham içerik (müşteri PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.4.1 tenant-provisioning: validate (statik model + spec + 12.1.1/12.1.2/12.2.4/12.1.8 resiprokal) =="
python3 tenant_provisioning_probe.py validate

echo
echo "== 12.4.1 tenant-provisioning: selftest (tenant yaşam döngüsü motoru invariant'ları R1–R12) =="
python3 tenant_provisioning_probe.py selftest

echo
echo "== 12.4.1 tenant-provisioning: check (örnek senaryolar — 11 pass + 10 degrade) =="
python3 tenant_provisioning_probe.py check samples

echo
echo "== 12.4.1 tenant-provisioning: behavior test (R1–R12; bağımsız) =="
python3 tests/tenant_provisioning_behavior_test.py

echo
if [ -n "${TENANT_API_URL:-}" ]; then
  echo "TENANT_API_URL set: canlı L0 tenant router doğrulaması (POST /tenants provision + lifecycle geçişleri + KMS tahsisi + WORM audit) F1 kod entegrasyonunda — burada NOT."
else
  echo "Canlı L0 tenant yaşam döngüsü (FastAPI tenant router + tenant repository + KMS tahsisi + retention motoru) SKIP — \${TENANT_API_URL} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM/DB testi gerçek L0 tenant router + tenant tablosu + KMS (FR-TEN-001 / BRD §17 / DB.md §5.1) ile (SKIP burada)."
