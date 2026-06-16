#!/usr/bin/env bash
# WBS 11.4 — PII redaction pipeline (async)
# (FR-REC-004 / SR-REC-004 / TC-REC-004 / DB §21 transcript.redaction_state /
#  SAD §10.2 PII Redaction / SAD §19.2 'Analytics Plane, async' / FR-RES-011)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed, ASENKRON PII-redaction
# (redaction planı + redaction_state pending→redacted geçiş) kararı motoru + statik doğrulama (sunucu
# gerektirmez). 11.3 (transcript-build) ÜRETİLMİŞ transkripti + redaction_state=pending'i TÜKETİR; kart/
# parola/OTP gizli-değer kategorilerini MASKELER + 11.5'e (FR-REC-005) DEVREDER. Gerçek PII Redaction
# pipeline (SAD §10.2 ham metin byte maskeleme / nesne depolama / KMS) + DB §21 redaction_state yazımı +
# PII-dedektör (NER/regex span çıkarımı) + residency (DB §8) entegrasyonu F1'de gelir; bu modül onlara
# REDACTED|NOT_REQUIRED|NO_CONTENT|BLOCK redaction PLANINI + state KARARINI iletir (upstream içerik yoksa
# NO_CONTENT garantisi — FR-REC-002 aşağı akış koruması; residüel PII varken redacted YASAK — K3).
# Vendor-neutral (ADR-001/002/004/007/012); sır/credential ve gerçek PII (telefon/kart/OTP/transkript metni) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 11.4 pii-redaction: validate (statik spec/config/kapsama) =="
python3 pii_redaction_probe.py validate

echo
echo "== 11.4 pii-redaction: selftest (PII-redaction motoru invariant'ları K1–K12) =="
python3 pii_redaction_probe.py selftest

echo
echo "== 11.4 pii-redaction: check (örnek senaryolar — 12 pass + 11 degrade) =="
python3 pii_redaction_probe.py check samples

echo
echo "== 11.4 pii-redaction: behavior test (K1–K12) =="
python3 tests/pii_redaction_behavior_test.py

echo
if [ -n "${PII_REDACTION_URL:-}" ]; then
  echo "PII_REDACTION_URL set: canlı PII-redaction karar çağrısı F1 entegrasyonunda (PII Redaction pipeline) — burada NOT."
else
  echo "Canlı PII redaction (PII Redaction pipeline SAD §10.2 ham metin byte maskeleme + DB §21 redaction_state yazımı + PII-dedektör span çıkarımı + nesne depolama/residency DB §8 + 11.5 kart/parola/OTP devri) SKIP — \${PII_REDACTION_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı PII-Redaction/depolama/dedektör/audit testi gerçek entegrasyon (SAD §10.2/§19.2/DB §21/§8) ile (SKIP burada)."
