#!/usr/bin/env bash
# WBS 13.3.7 — T-07 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /admin/billing 200 + TR/EN locale + plan/kullanım/maliyet/kota-overage/bütçe/aktarım
# içeriği render; PII/CDR/ödeme-sırrı sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3208}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"owner@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/t07_live.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/billing" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/admin/billing")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/admin/billing")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/billing")

check "/admin/billing 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Faturalandırma'"
check "EN bölüm render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Billing'"
check "Plan bölümü (FR-BIL-003)" "echo \"\$BODY_TR\" | grep -q 'Plan'"
check "Kullanım bölümü (FR-BIL-001)" "echo \"\$BODY_TR\" | grep -q 'Kullanım'"
check "Maliyet kırılımı (FR-BIL-002)" "echo \"\$BODY_TR\" | grep -q 'Maliyet'"
check "Telekom/STT/TTS/LLM bileşeni render" "echo \"\$BODY_TR\" | grep -qi 'Telekom'"
check "Kota & Overage bölümü (FR-BIL-004)" "echo \"\$BODY_TR\" | grep -qi 'Overage'"
check "Bütçe & Alarmlar bölümü (FR-BIL-006)" "echo \"\$BODY_TR\" | grep -qi 'Bütçe'"
check "Fatura Aktarımı bölümü (FR-BIL-007)" "echo \"\$BODY_TR\" | grep -qi 'Aktarım'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'kendi tenant'"
# PII/CDR/transkript İÇERİĞİ sızıntısı YOK (alan adı/ham içerik hedefi).
check "PII/CDR/transkript içeriği sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'transcript[^.]|recordingUrl|msisdn|callerNumber|cardPan|\"cdr\"'"
check "Ödeme sırrı/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|paymentToken|\"iban\"'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
