#!/usr/bin/env bash
# WBS 12.2.1 — Backend guard: panel + rol + tenant scope (FastAPI dependency)
# (SAD §14.4.2 panel+rol+tenant guard / FR-IAM-008 panel-katman ayrımı / FR-TEN-002 tenant izolasyonu /
#  FR-IAM-011 scoped assignment / ADR-011 iki düzlemli panel / ADR-012 sabit bundle + scoped assignment /
#  API.md x-required-permission)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed ÜÇ BOYUTLU HTTP guard
# karar motoru (panel gate [token realm + OAuth scope + rol-katman kapsama; L0 ⟂ tenant] + rol gate DELEGE
# [12.1.3 scoped-assignment → 12.1.1 immutable bundle] + tenant scope gate [HTTP enforce_tenant_scope; RLS
# çift kontrol 12.2.3]) → ALLOW|DENY|BLOCK + HTTP durum (200/401/403). 12.1.1 RBAC modelini TÜKETİR + 12.1.3
# rol+scope kararını CANLI DELEGE eder. Gerçek HTTP enforcement (FastAPI dependency wiring + ayrı router/scope
# 12.2.2 + RLS politikaları 12.2.3 + L0 repository bağımsızlığı 12.2.4 + break-glass 12.3.x + WORM audit 12.1.8)
# entegrasyonu F1 kod aşamasında gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini iletir
# (panel izolasyonu — S2; delege doğruluğu/fail-open yasak — S4; tenant scope — S5; backend otoritesi — S6).
# Vendor-neutral (ADR-001/002/011/012); sır/credential (bearer token DEĞERİ dahil) ve ham içerik (PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.2.1 backend-guard: validate (statik guard/rbac model + spec + 12.1.1/12.1.3 delege erişimi) =="
python3 backend_guard_probe.py validate

echo
echo "== 12.2.1 backend-guard: selftest (üç-boyutlu guard motoru invariant'ları S1–S12) =="
python3 backend_guard_probe.py selftest

echo
echo "== 12.2.1 backend-guard: check (örnek senaryolar — 12 pass + 9 degrade/güvenlik) =="
python3 backend_guard_probe.py check samples

echo
echo "== 12.2.1 backend-guard: behavior test (S1–S12; 12.1.3 canlı delege) =="
python3 tests/backend_guard_behavior_test.py

echo
if [ -n "${BACKEND_GUARD_URL:-}" ]; then
  echo "BACKEND_GUARD_URL set: canlı FastAPI guard dependency çağrısı F1 kod entegrasyonunda (require()/auth_ctx/enforce_tenant_scope) — burada NOT."
else
  echo "Canlı backend guard (FastAPI dependency wiring + ayrı router/scope 12.2.2 + RLS 12.2.3 + L0 repo bağımsızlığı 12.2.4 + break-glass 12.3.x + WORM audit 12.1.8) SKIP — \${BACKEND_GUARD_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM testi gerçek HTTP enforcement (SAD §14.4.2 / ADR-011 / ADR-012) ile (SKIP burada)."
