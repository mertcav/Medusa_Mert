#!/usr/bin/env bash
# WBS 13.1.1 — İki ayrı Next.js app (platform-app L0 internal-only + tenant-app L1+L2 public)
# (SAD §14.4.1 'Yönetim/panel uygulaması Next.js App Router ile AYRI deploy' / ADR-011 iki düzlemli panel
#  dağıtımı / FR-IAM-008 L0 ⟂ tenant / BRD §17 üç katmanlı panel). Statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fail-closed iki-app frontend ayrımı doğrulaması (iki ayrı app
# projesi + route group ayrımı + ekran kapsamı + platform-app'te YASAK tenant iş verisi route yokluğu [A5
# ÇEKİRDEK blast-radius] + ayrı origin/auth realm/exposure + cross-app import yok + sır/PII yok) → PASS|FAIL.
# Çalışma-anı oturum/tenant-scope middleware → 13.1.2; tasarım sistemi/i18n → 13.1.3; PII maskeleme → 13.1.4.
# Vendor-neutral (ADR-002/011); sır/credential (.env değeri/API anahtarı) ve ham içerik (PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 13.1.1 apps-separation: validate (statik spec + topology + ON-DISK iki-app iskelet) =="
python3 frontend_apps_probe.py validate

echo
echo "== 13.1.1 apps-separation: selftest (topoloji karar motoru invariant'ları A1–A12) =="
python3 frontend_apps_probe.py selftest

echo
echo "== 13.1.1 apps-separation: check (örnek senaryolar — 1 pass + 7 degrade) =="
python3 frontend_apps_probe.py check samples

echo
echo "== 13.1.1 apps-separation: behavior test (A1–A12; bağımsız on-disk) =="
python3 tests/frontend_apps_behavior_test.py

echo
if command -v npm >/dev/null 2>&1; then
  echo "npm mevcut: canlı 'next build' (her iki app ayrı build/deploy birimi) + tsc typecheck F1 CI'da (0.4.4)."
  echo "  Bağımlılık kurulu DEĞİLse (credential-free; node_modules repoda yok) build SKIP — burada NOT."
else
  echo "npm yok: canlı 'next build' SKIP."
fi

echo
echo "Tümü 🟢 — F1 canlı frontend CI 'next build' + topoloji testi (iki ayrı deploy birimi; ADR-011) ile (SKIP burada)."
