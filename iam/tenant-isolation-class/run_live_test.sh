#!/usr/bin/env bash
# WBS 12.4.2 — Dedicated vs shared tenant (L0)
# (FR-TEN-005 'Dedicated tenant ve shared tenant seçenekleri desteklenmelidir' /
#  SAD §13.1 izolasyon modeli [shared mantıksal: tek havuz + RLS + tenant KMS / dedicated fiziksel-ayrılmış:
#  ayrı namespace/cluster/region] / ADR-006 'shared (RLS) varsayılan + dedicated opsiyon' /
#  DB.md §5.1 tenant.isolation_mode CHECK [shared/dedicated] + §6 'dedicated modda da tenant RLS aynıdır' /
#  NFR 10.6 tenant başına ayrı KMS key / NFR 10.7 residency UK/EU/NA/ME / FR-IAM-008 L0⟂tenant realm /
#  ADR-011 iki düzlemli panel / ADR-012 sabit rol bundle / FR-BIL-005 dedicated ayrı faturalama)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed L0 izolasyon-sınıfı karar
# motoru (mod→yüzey bağlaması [shared⇒shared_pool+RLS / dedicated⇒namespace,cluster] + dedicated ayrım
# [shared havuza yerleşemez] + RLS her iki modda + tenant başına KMS her iki modda + residency tutarlılığı +
# migrate koruması [plan+confirm] + realm izolasyonu [platform-only] + yetkilendirme [tenant:provision] +
# WORM audit) → COMMIT|REJECT. 12.4.1 tenant-provisioning (isolation_modes + tenant KMS; izolasyon sınıfı
# DELEGE) + 12.2.3 rls-double-check (RLS her iki modda) + 12.1.2 permission-catalog (tenant:provision MEVCUT)
# + 12.1.1 rbac-model (platform_owner bundle) + 12.2.4 l0-repo-independence (tenant=platform sınıf) RESİPROKAL
# bağlantılarını TÜKETİR. Gerçek L0 izolasyon sağlama (IaC namespace/cluster [0.4.2/0.4.3] + RLS politikaları +
# KMS tahsisi + migrate cutover) F1 kod aşamasında gelir; bu modül onlara KARARI + kanıtı + model bütünlük
# manifestini iletir. Vendor-neutral (ADR-002/006/011); sır/credential (KMS key materyali / DB şifresi /
# connection string) ve ham içerik (müşteri PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.4.2 tenant-isolation-class: validate (statik model + spec + 12.4.1/12.2.3/12.1.1/12.1.2/12.2.4 resiprokal) =="
python3 tenant_isolation_probe.py validate

echo
echo "== 12.4.2 tenant-isolation-class: selftest (izolasyon-sınıfı motoru invariant'ları R1–R12) =="
python3 tenant_isolation_probe.py selftest

echo
echo "== 12.4.2 tenant-isolation-class: check (örnek senaryolar — 11 pass + 10 degrade) =="
python3 tenant_isolation_probe.py check samples

echo
echo "== 12.4.2 tenant-isolation-class: behavior test (R1–R12; bağımsız) =="
python3 tests/tenant_isolation_behavior_test.py

echo
if [ -n "${TENANT_API_URL:-}" ]; then
  echo "TENANT_API_URL set: canlı L0 izolasyon-sınıfı doğrulaması (dedicated namespace/cluster sağlama + RLS politikaları + KMS tahsisi + migrate cutover) F1 kod entegrasyonunda — burada NOT."
else
  echo "Canlı L0 izolasyon sağlama (IaC namespace/cluster + RLS politikası + KMS tahsisi + migrate cutover) SKIP — \${TENANT_API_URL} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı IaC/IAM/DB testi gerçek dedicated cluster + RLS + KMS (FR-TEN-005 / SAD §13.1 / DB.md §5.1/§6) ile (SKIP burada)."
