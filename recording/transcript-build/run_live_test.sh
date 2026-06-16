#!/usr/bin/env bash
# WBS 11.3 — Transkript üretimi + timeline
# (BRD §8.1 / FR-REC-008 / SR-REC-008 / TC-REC-008 / DB §21 transcript+transcript_segment /
#  DB §23 call_event / SAD §10.2 Transcript Store)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed transkript-üretim
# (zaman-sıralı + konuşmacı-atflı segment + birleşik timeline) kararı motoru + statik doğrulama (sunucu
# gerektirmez). 11.1 (recording-policy) içerik kararını + 11.2 (channel-recording) kanal/konuşmacı
# yerleşimini TÜKETİR; gerçek Transcript Store (SAD §10.2 ham metin byte yazımı / nesne depolama / KMS) +
# DB §21 transcript/transcript_segment satırı yazımı + PII redaction (11.4) + residency (DB §8) entegrasyonu
# F1'de gelir; bu modül onlara TRANSCRIPT|NO_TRANSCRIPT|BLOCK segment/timeline planını + redaction_state=
# pending'i iletir (upstream≠RECORD ⇒ no_content_persisted=true garantisi — FR-REC-002 aşağı akış koruması).
# Vendor-neutral (ADR-001/002/012); sır/credential ve gerçek PII (ham transkript metni/telefon/ham ses) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 11.3 transcript-build: validate (statik spec/config/kapsama) =="
python3 transcript_build_probe.py validate

echo
echo "== 11.3 transcript-build: selftest (Transkript-üretim motoru invariant'ları K1–K12) =="
python3 transcript_build_probe.py selftest

echo
echo "== 11.3 transcript-build: check (örnek senaryolar — 11 pass + 14 degrade) =="
python3 transcript_build_probe.py check samples

echo
echo "== 11.3 transcript-build: behavior test (K1–K12) =="
python3 tests/transcript_build_behavior_test.py

echo
if [ -n "${TRANSCRIPT_BUILD_URL:-}" ]; then
  echo "TRANSCRIPT_BUILD_URL set: canlı transkript-üretim karar çağrısı F1 entegrasyonunda (Transcript Store) — burada NOT."
else
  echo "Canlı transkript üretimi (Transcript Store SAD §10.2 ham metin byte yazımı + DB §21 transcript/segment satırı + nesne depolama/residency DB §8 + PII redaction 11.4) SKIP — \${TRANSCRIPT_BUILD_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı Transcript-Store/depolama/redaction/audit testi gerçek entegrasyon (SAD §10.2/DB §21/§23/§8) ile (SKIP burada)."
