#!/usr/bin/env bash
# WBS 11.2 — Tek/çift kanallı kayıt
# (FR-REC-003 / SR-REC-003 / TC-REC-003 / DB §22 recording.channels / SAD §10.2 Recording Pipeline)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed kanal-yerleşimi
# (MONO/DUAL) kararı motoru + statik doğrulama (sunucu gerektirmez). 11.1 (recording-policy) RECORD
# kararını + channels attribute'unu TÜKETİR; gerçek Recording Pipeline (SAD §10.2 byte yazımı / codec /
# nesne depolama / KMS) + DB §22 recording satırı yazımı + residency (DB §8) entegrasyonu F1'de gelir;
# bu modül onlara MONO|DUAL|NO_RECORD|BLOCK track planını iletir (upstream≠RECORD ⇒ no_media_captured=true
# garantisi — FR-REC-002/SR-REC-002 aşağı akış koruması).
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (müşteri adı/telefon/ham ses) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 11.2 channel-recording: validate (statik spec/config/kapsama) =="
python3 channel_recording_probe.py validate

echo
echo "== 11.2 channel-recording: selftest (Kanal-yerleşimi motoru invariant'ları K1–K12) =="
python3 channel_recording_probe.py selftest

echo
echo "== 11.2 channel-recording: check (örnek senaryolar — 11 pass + 11 degrade) =="
python3 channel_recording_probe.py check samples

echo
echo "== 11.2 channel-recording: behavior test (K1–K12) =="
python3 tests/channel_recording_behavior_test.py

echo
if [ -n "${CHANNEL_RECORDING_URL:-}" ]; then
  echo "CHANNEL_RECORDING_URL set: canlı kanal-yerleşimi karar çağrısı F1 entegrasyonunda (Recording Pipeline) — burada NOT."
else
  echo "Canlı kanal kaydı (Recording Pipeline SAD §10.2 byte yazımı/codec + DB §22 recording satırı + nesne depolama/residency DB §8 + PII redaction 11.4) SKIP — \${CHANNEL_RECORDING_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı Recording-Pipeline/depolama/redaction/audit testi gerçek entegrasyon (SAD §10.2/DB §22/§8) ile (SKIP burada)."
