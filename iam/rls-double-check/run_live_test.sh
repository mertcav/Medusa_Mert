#!/usr/bin/env bash
# WBS 12.2.3 — Tenant scope + RLS çift kontrol (defense in depth)
# (DB.md §6 RLS politikaları / SAD §14.4.2 tenant scope RLS çift kontrol / FR-TEN-002 tenant izolasyonu /
#  FR-IAM-008 L0 ⟂ tenant / FR-IAM-009 break-glass / ADR-011 iki düzlemli panel / ADR-006 PostgreSQL RLS)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed RLS çift-kontrol karar
# motoru (RLS altyapı [ENABLE+FORCE ROW LEVEL SECURITY + app_rw BYPASS-etmeyen rol] + policy coverage +
# GUC fail-closed NULLIF + tablo-sınıfı policy [USING/WITH CHECK] + break-glass time-boxed + çift-kontrol
# birleşim [served ⟺ app_permit ∧ rls_permit]) → PERMIT|DENY. 12.2.1 backend guard enforce_tenant_scope'u
# (app_level) TÜKETİR (resiprokal: guard-model tenant_double_check.rls_level → 12.2.3). Gerçek RLS DDL/policy
# + GUC wiring (SET LOCAL app.tenant_id) + 1.2.1 migration + 0.4.4 RLS CI + 12.3.x break-glass akışı F1 kod
# aşamasında gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini iletir (çift kontrol/sızıntı
# yok — R5; RLS etkin+FORCE+bypass-etmeyen rol — R2; GUC fail-closed — R4; WITH CHECK — R6; break-glass
# time-boxed — R8). Vendor-neutral (ADR-002/006/011); sır/credential (DB şifresi/connection string) ve ham
# içerik (transcript/recording/contact PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.2.3 rls-double-check: validate (statik RLS model + spec + 12.2.1 resiprokal bağlantı) =="
python3 rls_double_check_probe.py validate

echo
echo "== 12.2.3 rls-double-check: selftest (RLS çift-kontrol motoru invariant'ları R1–R12) =="
python3 rls_double_check_probe.py selftest

echo
echo "== 12.2.3 rls-double-check: check (örnek senaryolar — 12 pass + 12 degrade/güvenlik) =="
python3 rls_double_check_probe.py check samples

echo
echo "== 12.2.3 rls-double-check: behavior test (R1–R12; bağımsız) =="
python3 tests/rls_double_check_behavior_test.py

echo
if [ -n "${RLS_DB_URL:-}" ]; then
  echo "RLS_DB_URL set: canlı PostgreSQL RLS doğrulaması (SET LOCAL app.tenant_id + tenant_isolation policy + FORCE + app_rw) F1 kod entegrasyonunda + 1.2.1 migration — burada NOT."
else
  echo "Canlı RLS (PostgreSQL DDL/policy + GUC SET LOCAL wiring + 1.2.1 migration + 0.4.4 RLS CI + 12.3.x break-glass) SKIP — \${RLS_DB_URL} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM/DB testi gerçek PostgreSQL RLS (DB.md §6 / SAD §14.4.2 / FR-TEN-002) ile (SKIP burada)."
