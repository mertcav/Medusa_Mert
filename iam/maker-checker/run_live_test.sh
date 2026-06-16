#!/usr/bin/env bash
# WBS 12.1.7 — Maker-checker onay akışı
# (FR-IAM-005 kritik değişikliklerde maker-checker / onay / SR-IAM-005 talep eden ≠ onaylayan + onaysız değişiklik
#  canlıya çıkmaz / TC-IAM-005 / FR-TEN-002 tenant izolasyonu / SAD §14.1/§14.4.2 maker-checker kritik mutasyonlarda
#  pending→approved ile zorlanır / ADR-011/012/002)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed ONAY karar motoru
# (malformed + action + maker-auth + reason + tenant + timebox gate → SoD/quorum değerlendirme →
# APPLIED[commit] | PENDING | REJECTED | DENIED) + statik model doğrulama (sunucu gerektirmez). 12.1.1 RBAC modelini
# (rol→immutable bundle + realm) TÜKETİR; izin/kapsam kararını 12.1.2 (permission-key) + 12.1.3 (scoped assignment)
# SOYUT sonuç (maker.authorized / approval.authorized / approval.scope_ok) olarak TÜKETİR; ÇIKTI olarak onay durum
# kararını üretir. AYNI maker-checker çekirdeği break-glass Tier B'nin (FR-IAM-009; talep eden ≠ onaylayan) tabanıdır.
# SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): izin/kapsam doğrulaması burada YAPILMAZ (authorized/scope_ok soyut sonuç);
# canlı onay UI + bildirim + backend panel guard (12.2.x; kritik mutasyon → onay enforcement) + WORM audit (12.1.8;
# onay kararı + reason_code) F2 entegrasyonunda gelir; bu modül onlara KARARI + kanıtı + model bütünlük manifestini
# iletir (SoD — S3 ÇEKİRDEK; onaysız canlıya çıkmaz — S5 ÇEKİRDEK; maker yetkisi — S2; onaylayan yetkisi — S4;
# time-box — S6; tenant izolasyonu — S7; quorum — S8). Sır/credential/anahtar ve ham token/PII repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.1.7 maker-checker: validate (statik maker-checker/rbac model + spec + kapsama) =="
python3 maker_checker_probe.py validate

echo
echo "== 12.1.7 maker-checker: selftest (onay karar motoru invariant'ları S1–S12) =="
python3 maker_checker_probe.py selftest

echo
echo "== 12.1.7 maker-checker: check (örnek senaryolar — 14 pass + 11 degrade/güvenlik-olayı) =="
python3 maker_checker_probe.py check samples

echo
echo "== 12.1.7 maker-checker: behavior test (S1–S12) =="
python3 tests/maker_checker_behavior_test.py

echo
if [ -n "${MAKERCHECKER_ENDPOINT_URL:-}" ]; then
  echo "MAKERCHECKER_ENDPOINT_URL set: canlı onay UI + backend panel guard (12.2.x; kritik mutasyon → pending→approved) + bildirim + WORM audit (12.1.8) F2 entegrasyonunda — burada NOT."
else
  echo "Canlı onay akışı (onay UI + backend panel guard 12.2.x + bildirim + WORM audit 12.1.8 + break-glass Tier B FR-IAM-009) SKIP — \${MAKERCHECKER_ENDPOINT_URL} yok."
fi

echo
echo "Tümü 🟢 — F2 canlı maker-checker testi gerçek onay UI + guard (SAD §14.4.2) ile (SKIP burada)."
