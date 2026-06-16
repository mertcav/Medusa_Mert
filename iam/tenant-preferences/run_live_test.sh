#!/usr/bin/env bash
# WBS 12.4.4 — Tenant dil/saat dilimi/bölge/saklama tercihi (L1)
# (FR-TEN-004 'Tenant bazında dil, saat dilimi, veri bölgesi ve saklama politikası seçilebilmelidir' /
#  DB.md §5.1 tenant [default_locale, timezone, home_region, retention_profile] + §9 retention_policy
#  [tenant + data_class → retain_days; FR-REC-006/007/010] /
#  BRD §17 'tenant'a özel dil/bölge/saklama tercihleri ... Tenant Admin Console (L1) üzerinden yönetilir' /
#  NFR 10.7 residency UK/EU/NA/ME / DPIA §5.4/§5.5/§8 cp.residency/cp.retention + most-restrictive-wins /
#  SR-TEN-004 / FR-TEN-002 tenant izolasyonu / ADR-011 iki düzlemli panel /
#  ADR-012 sabit rol bundle [tenant_owner/security_compliance_officer compliance:manage/retention:manage])
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed L1 tercih karar motoru
# (tenant izolasyonu [kendi tenant self-row] + yetkilendirme [kategori→compliance:manage/retention:manage] +
# tercih geçerliliği [locale/timezone/residency/retention + değer] + residency [home_region tenant izinli;
# narrowing-only] + retention tabanı [retain_days ≥ compliance asgari; tenant override yalnız sıkılaştırır] +
# değişim koruması [residency değişimi/retention kısaltma → confirm] + WORM audit) → COMMIT|REJECT. 12.1.2
# permission-catalog (compliance:manage/retention:manage MEVCUT) + 12.1.1 rbac-model (tenant_owner/
# security_compliance_officer bundle) + 12.2.3 rls-double-check (tenant/retention_policy tenant-scoped RLS) +
# 12.4.1 tenant-provisioning (home_region/locale/timezone sağlanır; tenant izinli bölge) + 12.2.4
# l0-repo-independence (retention_policy=tenant_config sınıf) + DPIA compliance profile (cp.residency/cp.retention;
# most-restrictive-wins; çözülmüş GİRDİ) RESİPROKAL bağlantılarını TÜKETİR.
# Gerçek L1 tercih sağlama (tenant tercih alanı + retention_policy CRUD + retention motoru 1.2.3 + residency
# migrasyon + L1 OpenAPI/UI [13.3.x]) F1 kod aşamasında gelir; bu modül onlara KARARI + kanıtı + model bütünlük
# manifestini iletir. Vendor-neutral (ADR-002/011); sır/credential (DB şifresi / connection string) ve ham
# içerik (müşteri PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.4.4 tenant-preferences: validate (statik model + spec + 12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 resiprokal) =="
python3 tenant_preferences_probe.py validate

echo
echo "== 12.4.4 tenant-preferences: selftest (tercih motoru invariant'ları R1–R11) =="
python3 tenant_preferences_probe.py selftest

echo
echo "== 12.4.4 tenant-preferences: check (örnek senaryolar — 13 pass + 9 degrade) =="
python3 tenant_preferences_probe.py check samples

echo
echo "== 12.4.4 tenant-preferences: behavior test (R1–R11; bağımsız) =="
python3 tests/tenant_preferences_behavior_test.py

echo
if [ -n "${TENANT_API_URL:-}" ]; then
  echo "TENANT_API_URL set: canlı L1 tercih doğrulaması (tenant tercih alanı + retention_policy CRUD + retention motoru + RLS) F1 kod entegrasyonunda — burada NOT."
else
  echo "Canlı L1 tercih sağlama (tenant tercih alanı + retention_policy CRUD + retention motoru + residency migrasyon + L1 OpenAPI/UI) SKIP — \${TENANT_API_URL} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı L1/DB testi gerçek tenant tercih alanı + retention_policy CRUD + RLS (FR-TEN-004 / DB.md §5.1/§9 / BRD §17 / DPIA §8) ile (SKIP burada)."
