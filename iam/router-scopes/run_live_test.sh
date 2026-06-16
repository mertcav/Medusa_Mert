#!/usr/bin/env bash
# WBS 12.2.2 — L0/L1/L2 ayrı router ağaçları + ayrı OAuth scope
# (SAD §14.4.2 ayrı router/scopes + ayrı deploy / FR-IAM-008 panel ayrımı / FR-TEN-002 tenant izolasyonu /
#  ADR-011 iki düzlemli panel dağıtımı / API.md §2/§4.1 yüzey ayrımı + base path'ler)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed ROUTER/SCOPE topoloji karar
# motoru (mount bütünlüğü [endpoint paneli = ağaç paneli; cross-panel mount YOK; tekil mount] + düzlem ayrımı
# [L0 AYRI internal-only Platform Control Plane; L0 ⟂ tenant] + ayrı/anlaşmaz OAuth scope [router-seviyesi
# dependency; panel:L0/L1/L2] + router realm + 12.2.1 tutarlılık + scope dependency zorunlu + DEVİR) →
# ADMIT|REJECT|MISCONFIG + HTTP durum (200/401/403). 12.2.1 backend-guard guard-model'ini TÜKETİR (scope/realm
# tek kaynak — S6) + per-request panel+rol+tenant kararını CANLI DEVREDER (S8; admission GEREKLİ ama YETERLİ
# DEĞİL). Gerçek FastAPI enforcement (APIRouter(prefix=...) ağaçları + router-level Depends(require_scope) +
# iki düzlemli deploy + RLS 12.2.3 + L0 repository bağımsızlığı 12.2.4 + break-glass ayrı router 12.3.x)
# entegrasyonu F1 kod aşamasında gelir; bu modül onlara TOPOLOJİ KARARINI + kanıtı + model bütünlük manifestini
# iletir (ayrı router ağaçları — S2; düzlem ayrımı — S3; ayrı OAuth scope — S4; devir — S8).
# Vendor-neutral (ADR-001/002/011); sır/credential (bearer token DEĞERİ dahil) ve ham içerik (PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.2.2 router-scopes: validate (statik topoloji + spec + 12.2.1 guard-model tutarlılığı + devir erişimi) =="
python3 router_scopes_probe.py validate

echo
echo "== 12.2.2 router-scopes: selftest (router/scope topoloji motoru invariant'ları S1–S12) =="
python3 router_scopes_probe.py selftest

echo
echo "== 12.2.2 router-scopes: check (örnek senaryolar — 10 pass + 9 degrade) =="
python3 router_scopes_probe.py check samples

echo
echo "== 12.2.2 router-scopes: behavior test (S1–S12; 12.2.1 canlı devir) =="
python3 tests/router_scopes_behavior_test.py

echo
if [ -n "${ROUTER_SCOPES_URL:-}" ]; then
  echo "ROUTER_SCOPES_URL set: canlı FastAPI APIRouter mount + router-level scope dependency çağrısı F1 kod entegrasyonunda — burada NOT."
else
  echo "Canlı router/scope topolojisi (FastAPI APIRouter(prefix) ağaçları + router-level Depends(require_scope) + iki düzlemli deploy + 12.2.1 guard wiring) SKIP — \${ROUTER_SCOPES_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM testi gerçek FastAPI router/scope topolojisi (SAD §14.4.2 / ADR-011) ile (SKIP burada)."
