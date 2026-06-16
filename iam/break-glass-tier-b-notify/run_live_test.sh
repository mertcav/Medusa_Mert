#!/usr/bin/env bash
# WBS 12.3.3 — Tier B break-glass: zorunlu gerekçe kodu (reason code) semantiği + tenant
# security_compliance_officer/tenant_owner anlık bildirimi
# (BRD §17.7/§17 'Tier B — transkript/kayıt/PII: ... + zorunlu gerekçe kodu + tenant'ın security_compliance_officer
#  ve tenant_owner rollerine anlık bildirim' / SAD §14.4.2 aynı / FR-IAM-009 üç katmanlı break-glass Tier B /
#  FR-IAM-006/FR-REC-009 tüm break-glass erişimi audit). Statik + davranış kapısı. Bu modül iskelet kapısıdır:
# deterministik fail-closed Tier B gerekçe-kodu + bildirim motoru (access routing [yalnız GRANT_TIER_B bildirim
# gerektirir] + GEREKÇE-KODU ZORUNLULUĞU [eksik→BLOCK] + GEREKÇE-KODU SEMANTİĞİ [katalog dışı→BLOCK] + BİLDİRİM
# [her iki tenant rolü SCO+owner + anlık + teslim + tenant-bound] + WORM audit + replay-safe) →
# NOTIFY|NO_NOTIFY|BLOCK. 12.3.2 access_decision'ı (GRANT_TIER_B/PENDING/DENY) + reason_code taşımasını, 12.1.1
# rbac-model SCO+owner alıcı tenant rollerini + L0 aktör rollerini, 12.1.8 worm-audit WORM/hash-zincirini RESİPROKAL
# TÜKETİR. Tier B erişim-verme (maker-checker + time-boxed token) 12.3.2'nin; regüle tenant require_tenant_approval
# toggle + DPA 12.3.4'e DELEGE. Gerçek FastAPI break-glass router + bildirim dispatch (e-posta/webhook/in-app) +
# WORM audit yazımı F1/F2 kod aşamasında gelir; bu modül onlara KARARI + bildirim kaydını + PII/token-free WORM
# audit kaydını + model bütünlük manifestini iletir. Vendor-neutral (ADR-002/013); sır/credential (break-glass
# token DEĞERİ/DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.3.3 break-glass-tier-b-notify: validate (statik model + spec + 12.3.2/12.1.1/12.1.8 resiprokal bağlantı) =="
python3 tier_b_notify_probe.py validate

echo
echo "== 12.3.3 break-glass-tier-b-notify: selftest (bildirim motoru invariant'ları N1–N12) =="
python3 tier_b_notify_probe.py selftest

echo
echo "== 12.3.3 break-glass-tier-b-notify: check (örnek senaryolar — 11 pass + 12 degrade) =="
python3 tier_b_notify_probe.py check samples

echo
echo "== 12.3.3 break-glass-tier-b-notify: behavior test (N1–N12; bağımsız) =="
python3 tests/tier_b_notify_behavior_test.py

echo
if [ -n "${BREAK_GLASS_ROUTER_URL:-}" ]; then
  echo "BREAK_GLASS_ROUTER_URL set: canlı Tier B break-glass router (gerekçe-kodu enforcement + bildirim dispatch [SCO+owner] + WORM audit yazımı + hash-zincir) F1/F2 kod entegrasyonunda + 0.4.7 telemetri — burada NOT."
else
  echo "Canlı Tier B (FastAPI break-glass router + bildirim dispatch + WORM audit yazımı) SKIP — \${BREAK_GLASS_ROUTER_URL} yok (sır/token repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1/F2 canlı IAM testi gerçek break-glass router + bildirim dispatch + WORM audit (BRD §17.7 / SAD §14.4.2 / FR-IAM-009) ile (SKIP burada)."
