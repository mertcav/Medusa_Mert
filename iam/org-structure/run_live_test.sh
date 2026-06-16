#!/usr/bin/env bash
# WBS 12.4.3 — Org yapısı (marka/departman/ülke/proje) (L1)
# (FR-TEN-003 'Tenant altında marka, departman, ülke ve proje yapıları oluşturulabilmelidir' /
#  DB.md §5.1 organisation_unit [self-ref hiyerarşi; type CHECK IN brand/country/department/project;
#  region residency override; UNIQUE (tenant_id,parent_id,name)] /
#  BRD §17 'Tenant içi organizasyon yapısı ... Tenant Admin Console (L1) üzerinden yönetilir' /
#  SAD §14.4 scoped assignment scope {brand|department|campaign} / SR-TEN-003 /
#  NFR 10.7 residency UK/EU/NA/ME / FR-TEN-002 tenant izolasyonu / ADR-011 iki düzlemli panel /
#  ADR-012 sabit rol bundle [tenant_owner/tenant_admin org:manage])
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed L1 org-yapısı karar motoru
# (tenant izolasyonu [kendi tenant + ebeveyn aynı tenant] + yetkilendirme [org:manage] + tip geçerliliği
# [brand/country/department/project] + hiyerarşi bütünlüğü [döngüsüz + derinlik] + kardeş benzersizliği
# [UNIQUE name] + residency [region tenant izinli] + silme koruması [çocuk/scope → cascade+confirm] +
# WORM audit) → COMMIT|REJECT. 12.1.3 scoped-assignment (org birimleri kapsam boyutu) + 12.1.2
# permission-catalog (org:manage MEVCUT) + 12.1.1 rbac-model (tenant_owner/tenant_admin bundle) + 12.2.3
# rls-double-check (organisation_unit tenant-scoped RLS) + 12.4.1 tenant-provisioning (tenant izinli bölge)
# + 12.2.4 l0-repo-independence (organisation_unit=tenant_config sınıf) RESİPROKAL bağlantılarını TÜKETİR.
# Gerçek L1 org-yapısı sağlama (organisation_unit CRUD + cascade/yeniden-atama + L1 OpenAPI/UI [13.3.2])
# F1 kod aşamasında gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini iletir.
# Vendor-neutral (ADR-002/011); sır/credential (DB şifresi / connection string) ve ham içerik (müşteri PII)
# repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.4.3 org-structure: validate (statik model + spec + 12.1.3/12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 resiprokal) =="
python3 org_structure_probe.py validate

echo
echo "== 12.4.3 org-structure: selftest (org-yapısı motoru invariant'ları R1–R12) =="
python3 org_structure_probe.py selftest

echo
echo "== 12.4.3 org-structure: check (örnek senaryolar — 11 pass + 10 degrade) =="
python3 org_structure_probe.py check samples

echo
echo "== 12.4.3 org-structure: behavior test (R1–R12; bağımsız) =="
python3 tests/org_structure_behavior_test.py

echo
if [ -n "${TENANT_API_URL:-}" ]; then
  echo "TENANT_API_URL set: canlı L1 org-yapısı doğrulaması (organisation_unit CRUD + cascade/yeniden-atama + RLS) F1 kod entegrasyonunda — burada NOT."
else
  echo "Canlı L1 org-yapısı sağlama (organisation_unit CRUD + cascade/yeniden-atama + L1 OpenAPI/UI) SKIP — \${TENANT_API_URL} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı L1/DB testi gerçek organisation_unit CRUD + RLS + scoped assignment (FR-TEN-003 / DB.md §5.1 / BRD §17) ile (SKIP burada)."
