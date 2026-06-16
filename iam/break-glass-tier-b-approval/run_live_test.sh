#!/usr/bin/env bash
# WBS 12.3.4 — Tier B break-glass: regüle tenant require_tenant_approval toggle + DPA bağı
# (BRD §17/§17.7 'Regüle tenant'lar (finans/sağlık): Tier B'de tenant onayı zorunlu toggle'ı; regulated compliance
#  profile'da varsayılan açık. B2B2B'de veri controller'ı tenant, RMC processor'dür; bu kontrol DPA'ya bağlanır' /
#  FR-IAM-010 / SAD §14.4.2 'require_tenant_approval=true ise Tier B, tenant onayı olmadan açılmaz; regulated
#  profile'da varsayılan açık; DPA'ya bağlı [controller=tenant, processor=RMC]' / ADR-013 / DPIA §8 most-restrictive-wins).
# Statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed Tier B regüle onay motoru
# (access routing [yalnız GRANT_TIER_B regüle gate gerektirir] + REGÜLE VARSAYILAN-AÇIK [most-restrictive-wins] +
#  DPA BAĞI [regüle → imzalı DPA; yoksa BLOCK] + TENANT ONAY KAPISI [geçerli onay/yetki/binding; onaysız → HOLD] +
#  override-tightens-only + replay-safe + WORM audit) → ALLOW|HOLD|BLOCK. 12.3.2 access_decision'ı
# (GRANT_TIER_B/PENDING/DENY), 12.1.1 rbac-model SCO+owner onaylayan tenant rollerini + L0 aktör rollerini, 12.1.8
# worm-audit WORM/hash-zincirini RESİPROKAL TÜKETİR. Tier B erişim-verme (maker-checker + time-boxed token) 12.3.2'nin;
# gerekçe kodu + tenant bildirimi 12.3.3'ün; tam-audit router 12.3.5'in; cp.* compliance profile motoru DPIA.md +
# F2/F3'ün DELEGE. Gerçek FastAPI break-glass router + regüle toggle enforcement + tenant onay akışı + DPA bağı +
# WORM audit yazımı F1/F2 kod aşamasında gelir; bu modül onlara KARARI + onay/DPA kanıtını + PII/token-free WORM audit
# kaydını + model bütünlük manifestini iletir. Vendor-neutral (ADR-002/013); sır/credential (break-glass/onay token
# DEĞERİ/DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.3.4 break-glass-tier-b-approval: validate (statik model + spec + 12.3.2/12.1.1/12.1.8 resiprokal bağlantı) =="
python3 tier_b_approval_probe.py validate

echo
echo "== 12.3.4 break-glass-tier-b-approval: selftest (regüle onay motoru invariant'ları C1–C12) =="
python3 tier_b_approval_probe.py selftest

echo
echo "== 12.3.4 break-glass-tier-b-approval: check (örnek senaryolar — 11 pass + 12 degrade) =="
python3 tier_b_approval_probe.py check samples

echo
echo "== 12.3.4 break-glass-tier-b-approval: behavior test (C1–C12; bağımsız) =="
python3 tests/tier_b_approval_behavior_test.py

echo
if [ -n "${BREAK_GLASS_ROUTER_URL:-}" ]; then
  echo "BREAK_GLASS_ROUTER_URL set: canlı Tier B break-glass router (regüle toggle enforcement + tenant onay akışı [controller=tenant] + DPA bağı + WORM audit yazımı + hash-zincir) F1/F2 kod entegrasyonunda + 0.4.7 telemetri — burada NOT."
else
  echo "Canlı Tier B regüle onay (FastAPI break-glass router + tenant onay akışı + DPA bağı + WORM audit yazımı) SKIP — \${BREAK_GLASS_ROUTER_URL} yok (sır/token repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1/F2 canlı IAM testi gerçek break-glass router + regüle toggle + tenant onay akışı + DPA bağı + WORM audit (BRD §17 / FR-IAM-010 / SAD §14.4.2) ile (SKIP burada)."
