#!/usr/bin/env bash
# WBS 12.2.4 — L0 iş verisi repository bağımsızlığı (tasarımsal/design-time izolasyon)
# (SAD §14.4.2 'Platform endpoint'leri TASARIM GEREĞİ tenant iş verisi repository'lerine BAĞLI DEĞİLDİR' /
#  DB.md P3 'repository/grant düzeyinde bağlı değildir' / FR-IAM-008 L0 ⟂ tenant / FR-IAM-009 break-glass /
#  ADR-011 iki düzlemli panel / API.md L0 OpenAPI iş-verisi endpoint'i yok)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed design-time repository
# bağımsızlık karar motoru (plane separation [ADR-011 internal-only] + classification coverage [fail-closed] +
# WIRING bağımsızlığı [platform default tenant iş verisi repo'su wire etmez] + GRANT bağımsızlığı [platform_ro
# tenant iş verisi tablosunda grant tutmaz; DB.md P3] + birleşik defense-in-depth [data_reachable ⟺
# wired_forbidden_repo ∧ grant_present] + endpoint yüzey bağımsızlığı + break-glass plane ayrımı/grant-gated)
# → PERMIT|FORBID. 12.2.1 backend guard l0_business_data delegasyonunu (delegated_to → 12.2.4) KARŞILAR
# (resiprokal) + 12.2.3 RLS'i çalışma-anı BACKSTOP olarak TÜKETİR (resiprokal: break_glass.tables eşleşmesi).
# Gerçek FastAPI kompozisyon kökü (L0 ayrı app) + DB GRANT/REVOKE DDL (platform_ro) + L0 OpenAPI (iş-verisi
# endpoint'i yok) + 0.4.4 repo/grant bağımsızlık CI F1 kod aşamasında gelir; bu modül onlara KARARI + kanıtı +
# model bütünlük manifestini iletir (wiring bağımsızlığı — R4; grant bağımsızlığı — R5; defense in depth — R6;
# endpoint yüzey — R7; break-glass ayrım/grant-gated — R8/R9). Vendor-neutral (ADR-002/011); sır/credential
# (DB şifresi/connection string) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.2.4 l0-repo-independence: validate (statik model + spec + 12.2.1/12.2.3 resiprokal bağlantı) =="
python3 repo_independence_probe.py validate

echo
echo "== 12.2.4 l0-repo-independence: selftest (repo bağımsızlık motoru invariant'ları R1–R12) =="
python3 repo_independence_probe.py selftest

echo
echo "== 12.2.4 l0-repo-independence: check (örnek senaryolar — 12 pass + 9 degrade) =="
python3 repo_independence_probe.py check samples

echo
echo "== 12.2.4 l0-repo-independence: behavior test (R1–R12; bağımsız) =="
python3 tests/repo_independence_behavior_test.py

echo
if [ -n "${L0_APP_MANIFEST:-}" ]; then
  echo "L0_APP_MANIFEST set: canlı L0 kompozisyon grafiği + DB grant manifesti doğrulaması (platform_ro grant'leri + FastAPI import grafiği) F1 kod entegrasyonunda + 0.4.4 CI — burada NOT."
else
  echo "Canlı L0 bağımsızlık (FastAPI kompozisyon kökü + GRANT/REVOKE DDL + L0 OpenAPI + 0.4.4 CI) SKIP — \${L0_APP_MANIFEST} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM/DB testi gerçek L0 kompozisyon + DB grant (SAD §14.4.2 / DB.md P3 / FR-IAM-008) ile (SKIP burada)."
