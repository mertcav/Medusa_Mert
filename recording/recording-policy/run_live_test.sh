#!/usr/bin/env bash
# WBS 11.1 — Kayıt politikası (tenant/ülke/use-case) + tamamen kapatma
# (FR-REC-001 / FR-REC-002 / SR-REC-001 / SR-REC-002 / SAD §10.2 Recording Pipeline / §19.3 compliance profile)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed / privacy-safe (NO-RECORD)
# kayıt-başlatma kararı motoru + statik doğrulama (sunucu gerektirmez). Gerçek Recording Pipeline (SAD §10.2),
# compliance profile çözümleme (DPIA §5/SAD §19.3), consent kaydı (consent:manage + 10.2.1), bildirim çalma
# (BRD §14.2 orchestrator), nesne depolama/residency (DB §8) entegrasyonu F1'de gelir; bu modül onlara
# kayıt-başlatma RECORD|DISABLED|NO_CONSENT|BLOCK kararını + no_media_captured/channels/residency/retention'u
# iletir (terminal≠RECORD ⇒ no_media_captured=true garantisi — FR-REC-002 tamamen kapatma).
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/ham ses) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 11.1 recording-policy: validate (statik spec/config/kapsama) =="
python3 recording_policy_probe.py validate

echo
echo "== 11.1 recording-policy: selftest (Kayıt-politikası motoru invariant'ları K1–K12) =="
python3 recording_policy_probe.py selftest

echo
echo "== 11.1 recording-policy: check (örnek senaryolar — 12 pass + 11 degrade) =="
python3 recording_policy_probe.py check samples

echo
echo "== 11.1 recording-policy: behavior test (K1–K12) =="
python3 tests/recording_policy_behavior_test.py

echo
if [ -n "${RECORDING_POLICY_URL:-}" ]; then
  echo "RECORDING_POLICY_URL set: canlı kayıt-başlatma karar çağrısı F1 entegrasyonunda (Recording Pipeline) — burada NOT."
else
  echo "Canlı kayıt-başlatma kararı (Recording Pipeline SAD §10.2 + compliance profile DPIA §5/SAD §19.3 + consent:manage/10.2.1 + bildirim çalma BRD §14.2 + nesne depolama/residency DB §8) SKIP — \${RECORDING_POLICY_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı Recording-Pipeline/compliance-profile/consent/bildirim/depolama/audit testi gerçek entegrasyon (SAD §10.2/§19.3/14.2/DB §8/12.x) ile (SKIP burada)."
