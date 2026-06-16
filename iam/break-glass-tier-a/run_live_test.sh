#!/usr/bin/env bash
# WBS 12.3.1 — Tier A (metrik/log, PII yok): break-glass'sız L0 erişimi + audit
# (BRD §17.7 'Tier A — metrik/log [PII yok]: Break-glass gerekmez; normal L0 erişimi + audit' /
#  SAD §14.4.2 aynı / FR-IAM-009 üç katmanlı break-glass / FR-IAM-006/FR-REC-009 tüm L0 erişimi audit)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed Tier A karar motoru
# (classification coverage [fail-closed] + Tier sınıflandırma [A=PII'siz / B=içerik / forbidden=tenant_config] +
# admission [A→TIER_A_GRANT no-bg+audit / B→ESCALATE_TIER_B delege / forbidden→DENY] + NO PII UNDER TIER A
# [altın kural] + AUDIT EMITTED [sessiz erişim yok] + NO BREAK-GLASS BYPASS + escalation correct + audit PII-free
# + audit immutability [WORM] + tier separation) → TIER_A_GRANT|ESCALATE_TIER_B|DENY. 12.2.4 repo-independence
# veri-sınıfı taksonomisini (tier_a_classes = allowed_for_platform) + 12.1.8 worm-audit WORM/hash-zincirini +
# 12.1.1 rbac-model L0 rollerini RESİPROKAL TÜKETİR. Tier B AKIŞI (maker-checker + time-boxed token + gerekçe +
# bildirim + regüle toggle) 12.3.2/12.3.3/12.3.4'e DELEGE. Gerçek FastAPI L0 erişimi + WORM audit yazımı F1 kod
# aşamasında gelir; bu modül onlara KARARI + PII'siz audit kaydını + model bütünlük manifestini iletir.
# Vendor-neutral (ADR-002/013); sır/credential (break-glass token/DB şifresi) ve ham içerik
# (transcript/recording/contact PII) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 12.3.1 break-glass-tier-a: validate (statik model + spec + 12.2.4/12.1.8/12.1.1 resiprokal bağlantı) =="
python3 tier_a_probe.py validate

echo
echo "== 12.3.1 break-glass-tier-a: selftest (Tier A motoru invariant'ları R1–R12) =="
python3 tier_a_probe.py selftest

echo
echo "== 12.3.1 break-glass-tier-a: check (örnek senaryolar — 9 pass + 8 degrade) =="
python3 tier_a_probe.py check samples

echo
echo "== 12.3.1 break-glass-tier-a: behavior test (R1–R12; bağımsız) =="
python3 tests/tier_a_behavior_test.py

echo
if [ -n "${L0_AUDIT_SINK:-}" ]; then
  echo "L0_AUDIT_SINK set: canlı L0 erişimi + WORM audit yazımı (Tier A karar + append-only audit + hash-zincir) F1 kod entegrasyonunda + 0.4.7 telemetri — burada NOT."
else
  echo "Canlı Tier A (FastAPI L0 erişimi + WORM audit yazımı + Tier B break-glass router) SKIP — \${L0_AUDIT_SINK} yok (sır repoya yazılmaz; yalnız ortam değişkeni)."
fi

echo
echo "Tümü 🟢 — F1 canlı IAM testi gerçek L0 erişimi + WORM audit (BRD §17.7 / SAD §14.4.2 / FR-IAM-009) ile (SKIP burada)."
