#!/usr/bin/env bash
# WBS 11.7 — Çağrı özeti üretimi
# (BRD §8.1 adım 9 'Çağrıyı özetler ve sonuçlandırır' / FR-ANA-002 / SR-ANA-002 / TC-ANA-002 /
#  DB §21 transcript.summary / DB §19 call.outcome / SAD §10.1 özetleme / SAD §10.2 Transcript Store /
#  SAD §19.2 async / FR-RES-011)
# statik + davranış kapısı. Bu modül iskelet kapısıdır: deterministik fail-closed, ASENKRON çağrı-özeti
# (dayanaklı kapalı-sözlük yapısal özet planı + transcript.summary/call.outcome kararı) motoru + statik
# doğrulama (sunucu gerektirmez). 11.4 (pii-redaction) GÖRÜNTÜLEMEYE-HAZIR (redakte/PII-güvenli) transkripti +
# 11.3 (transcript-build) segmentlerini + LLM özetleyici aday özetini TÜKETİR. Gerçek LLM özetleyici
# (SAD §10.1/§10.2 özet PROSE byte üretimi; ADR-001/002 sağlayıcı-soyut) + DB §21 transcript.summary +
# DB §19 call.outcome yazımı + residency (DB §8) entegrasyonu F1'de gelir; bu modül onlara
# SUMMARIZED|NO_SUMMARY|NO_CONTENT|BLOCK yapısal özet PLANINI + dayanak/sözlük/PII-güvenlik KARARINI iletir
# (upstream içerik yoksa NO_CONTENT garantisi — FR-REC-002 aşağı akış; pending kaynaktan özet YASAK — K4;
# dayanaksız özet YASAK — K2 halüsinasyon koruması).
# Vendor-neutral (ADR-001/002/004/007/012); sır/credential ve gerçek PII (telefon/kart/OTP/transkript metni/özet prose) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 11.7 call-summary: validate (statik spec/config/kapsama) =="
python3 call_summary_probe.py validate

echo
echo "== 11.7 call-summary: selftest (çağrı-özeti motoru invariant'ları K1–K12) =="
python3 call_summary_probe.py selftest

echo
echo "== 11.7 call-summary: check (örnek senaryolar — 13 pass + 13 degrade) =="
python3 call_summary_probe.py check samples

echo
echo "== 11.7 call-summary: behavior test (K1–K12) =="
python3 tests/call_summary_behavior_test.py

echo
if [ -n "${CALL_SUMMARY_URL:-}" ]; then
  echo "CALL_SUMMARY_URL set: canlı çağrı-özeti karar çağrısı F1 entegrasyonunda (LLM özetleyici/Analytics Plane) — burada NOT."
else
  echo "Canlı çağrı özeti (LLM özetleyici SAD §10.1/§10.2 özet PROSE byte üretimi + DB §21 transcript.summary + DB §19 call.outcome yazımı + residency DB §8) SKIP — \${CALL_SUMMARY_URL} yok."
fi

echo
echo "Tümü 🟢 — F1 canlı LLM-özetleyici/depolama/analitik testi gerçek entegrasyon (SAD §10.1/§10.2/§19.2/DB §21/§19) ile (SKIP burada)."
