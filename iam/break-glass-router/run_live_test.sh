#!/usr/bin/env bash
# WBS 12.3.5 — Break-glass tam-audit router (ayrı, kısıtlı)
# (SAD §14.4.2 'maker-checker → süreli token → ... Erişim AYRI, KISITLI, TAM-AUDIT'li bir break-glass ROUTER'ı
#  üzerinden verilir' / BRD §17/§17.7 altın kural / FR-IAM-009 üç katmanlı break-glass / FR-IAM-008 L0 izolasyon /
#  FR-IAM-006/FR-REC-009 tüm erişim audit / FR-REC-004 PII'siz / ADR-011 Platform Control Plane internal-only +
#  ayrı router/scope / ADR-013).
# Statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed break-glass ROUTER ADMISSION
# motoru (router izolasyonu [AYRI — internal-only platform plane + dedicated break-glass scope] + KISITLI admission
# [sanction=ALLOW + geçerli time-boxed token; no standing access] + TAM-AUDIT [her istek WORM audit] + token
# doğrulama [unexpired/bound/replay-safe] + scope-limited routing) → ADMIT|REJECT. 12.3.4 sanction_decision'ı
# (ALLOW/HOLD/BLOCK; yalnız ALLOW ADMIT), 12.3.2 time-boxed token'ını (60/240/auto-expiry/no-standing + binding +
# resolved_states), 12.2.2 router topolojisini (platform plane internal_only + scope_disjoint — break-glass router
# AYRI/EK dördüncü ağaç), 12.1.8 worm-audit WORM/hash-zincirini, 12.1.1 L0 aktör rollerini RESİPROKAL TÜKETİR.
# Tier B erişim-verme + token ÜRETİMİ 12.3.2'nin; regüle onay + DPA 12.3.4'ün; gerekçe kodu + bildirim 12.3.3'ün;
# Tier sınıflandırma + ESCALATE 12.3.1'in; panel router topolojisi 12.2.2'nin DELEGE. Gerçek FastAPI break-glass
# router (ayrı router ağacı + internal-only Platform Control Plane mount + dedicated break-glass OAuth scope +
# admission + scope-limited routing + WORM audit yazımı + hash-zincir) F1/F2 kod aşamasında gelir; bu modül onlara
# ADMISSION KARARINI + scope kanıtını + PII/token-free WORM audit kaydını + model bütünlük manifestini iletir.
# Vendor-neutral (ADR-002/011/013); sır/credential (break-glass token DEĞERİ/DB şifresi) ve ham içerik
# (transcript/recording/contact PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.3.5 break-glass-router: validate (statik model + spec + 12.3.4/12.3.2/12.2.2/12.1.8/12.1.1 resiprokal bağlantı) =="
python3 break_glass_router_probe.py validate

echo
echo "== 12.3.5 break-glass-router: selftest (router admission motoru invariant'ları C1–C12) =="
python3 break_glass_router_probe.py selftest

echo
echo "== 12.3.5 break-glass-router: check (örnek senaryolar — 11 pass + 12 degrade) =="
python3 break_glass_router_probe.py check samples

echo
echo "== 12.3.5 break-glass-router: behavior test (C1–C12; bağımsız) =="
python3 tests/break_glass_router_behavior_test.py

echo
if [ -n "${BREAK_GLASS_ROUTER_URL:-}" ]; then
  echo "BREAK_GLASS_ROUTER_URL set: canlı break-glass router (ayrı router ağacı + internal-only Platform Control Plane mount + dedicated break-glass OAuth scope + admission [sanction+token] + scope-limited routing + WORM audit yazımı + hash-zincir) F1/F2 kod entegrasyonunda + 0.4.7 telemetri — burada NOT."
else
  echo "Canlı break-glass router (FastAPI ayrı router ağacı + mount + scope dependency + WORM audit yazımı) SKIP — \${BREAK_GLASS_ROUTER_URL} yok (sır/token repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1/F2 canlı IAM testi gerçek break-glass router + ayrı/internal-only mount + dedicated scope + admission + tam-audit (SAD §14.4.2 / FR-IAM-009 / BRD §17) ile (SKIP burada)."
