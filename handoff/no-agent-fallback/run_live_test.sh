#!/usr/bin/env bash
# WBS 9.7 — Temsilci yoksa callback/voicemail/ticket (FR-HND-007) statik + davranış kapısı.
# Bu modül iskelet kapısıdır: deterministik fallback sunum/seçim motoru + statik doğrulama
# (sunucu gerektirmez). Gerçek callback çevirme (outbound dialer 10.x), ticket API (tool 11.x) ve
# voicemail kayıt depolama (12.x) entegrasyonu F1/F2'de gelir; bu modül onlara OLUŞTURMA SÖZLEŞMESİNİ
# iletir, çağrı asla düşmez (red → bağlamdan oto-ticket, SAFE_CLOSE).
# Vendor-neutral (ADR-001/002); sır/credential ve gerçek PII (müşteri adı/telefon/voicemail içeriği) repoya yazılmaz.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 9.7 no-agent-fallback: validate (statik spec/config/kapsama) =="
python3 no_agent_fallback_probe.py validate

echo
echo "== 9.7 no-agent-fallback: selftest (fallback motoru invariant'ları K1–K12) =="
python3 no_agent_fallback_probe.py selftest

echo
echo "== 9.7 no-agent-fallback: run (örnek senaryolar — 7 pass + 8 degrade) =="
python3 no_agent_fallback_probe.py run samples

echo
echo "== 9.7 no-agent-fallback: behavior test (K1–K12) =="
python3 tests/no_agent_fallback_behavior_test.py

echo
echo "Tümü 🟢 — F1/F2 canlı dialer/ticketing/kayıt testi gerçek entegrasyon + 9.1/9.2/9.3 ile (SKIP burada)."
