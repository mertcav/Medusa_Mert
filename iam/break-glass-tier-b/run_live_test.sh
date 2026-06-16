#!/usr/bin/env bash
# WBS 12.3.2 — Tier B break-glass: maker-checker (talep eden ≠ onaylayan) + time-boxed token
# (60dk default, max 4sa, auto-expiry, standing access yok)
# (BRD §17.7/§17 'Tier B — transkript/kayıt/PII: Maker-checker zorunlu + time-boxed [varsayılan 60 dk, max 4 saat,
#  otomatik sonlanma, STANDING ACCESS YOK]' / SAD §14.4.2 aynı / FR-IAM-009 üç katmanlı break-glass Tier B /
#  FR-IAM-006/FR-REC-009 tüm break-glass erişimi audit). Statik + davranış kapısı. Bu modül iskelet kapısıdır:
# deterministik fail-closed Tier B erişim-verme motoru (Tier B scope [yalnız tenant_content] + maker-checker
# [SoD: talep eden ≠ onaylayan + distinct quorum] + admission [quorum→token / yetersiz→PENDING] + TIME-BOX
# [default 60 / max 240 / require_expiry / reddet ttl>max] + STANDING-YOK + AUTO-EXPIRY [pencere dışı reddedilir] +
# token-binding + WORM audit + replay-safe) → GRANT_TIER_B|PENDING|DENY. 12.3.1 ESCALATE_TIER_B + tenant_content
# sınıfını, 12.1.7 maker-checker SoD+timebox+breakglass.tier_b'yi, 12.1.8 worm-audit WORM/hash-zincirini ve
# 12.1.1 rbac-model L0 rollerini RESİPROKAL TÜKETİR. Gerekçe kodu semantiği + tenant bildirimi 12.3.3'e; regüle
# tenant require_tenant_approval toggle + DPA 12.3.4'e DELEGE. Gerçek FastAPI break-glass router + time-boxed
# token verme/iptal + WORM audit yazımı F1/F2 kod aşamasında gelir; bu modül onlara KARARI + token yaşam-döngüsü
# parametrelerini + PII/token-free WORM audit kaydını + model bütünlük manifestini iletir. Vendor-neutral
# (ADR-002/013); sır/credential (break-glass token DEĞERİ/DB şifresi) ve ham içerik (transcript/recording/contact
# PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.3.2 break-glass-tier-b: validate (statik model + spec + 12.3.1/12.1.7/12.1.8/12.1.1 resiprokal bağlantı) =="
python3 tier_b_probe.py validate

echo
echo "== 12.3.2 break-glass-tier-b: selftest (Tier B motoru invariant'ları R1–R12) =="
python3 tier_b_probe.py selftest

echo
echo "== 12.3.2 break-glass-tier-b: check (örnek senaryolar — 11 pass + 12 degrade) =="
python3 tier_b_probe.py check samples

echo
echo "== 12.3.2 break-glass-tier-b: behavior test (R1–R12; bağımsız) =="
python3 tests/tier_b_behavior_test.py

echo
if [ -n "${BREAK_GLASS_ROUTER_URL:-}" ]; then
  echo "BREAK_GLASS_ROUTER_URL set: canlı Tier B break-glass router (maker-checker onay UI + time-boxed token verme/iptal + WORM audit yazımı + hash-zincir) F1/F2 kod entegrasyonunda + 0.4.7 telemetri — burada NOT."
else
  echo "Canlı Tier B (FastAPI break-glass router + time-boxed token verme + WORM audit yazımı) SKIP — \${BREAK_GLASS_ROUTER_URL} yok (sır/token repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1/F2 canlı IAM testi gerçek break-glass router + time-boxed token + WORM audit (BRD §17.7 / SAD §14.4.2 / FR-IAM-009) ile (SKIP burada)."
