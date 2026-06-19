#!/usr/bin/env bash
# WBS 13.4.12 — A-12 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/call 200 + TR/EN locale + özet/künye/olay-çizelgesi/transkript/erişim render;
# transkript redaction'lı (maskeli [•••]) görünür; ham ses/ham transkript blob/ham numara/nesne-depo URI/sır
# sızıntısı YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3252}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"ops@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a12_call_detail.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/call" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/call")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/call")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/call")

check "/workspace/call 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Transkript'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Call timeline'"
check "Çağrı özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Çağrı Özeti'"
check "Çağrı künyesi bölümü" "echo \"\$BODY_TR\" | grep -q 'Çağrı Künyesi'"
check "Olay zaman çizelgesi (DB §23/SAD §6.1)" "echo \"\$BODY_TR\" | grep -q 'Olay Zaman'"
check "Transkript bölümü" "echo \"\$BODY_TR\" | grep -q 'Transkript'"
check "Erişim & redaction sağlığı (FR-REC-004/005/009)" "echo \"\$BODY_TR\" | grep -q 'Redaction Sağlığı'"
check "Maskeli içerik render (redaction)" "echo \"\$BODY_TR\" | grep -q '•••'"
check "Barge-in olayı (ADR-005)" "echo \"\$BODY_TR\" | grep -qi 'Barge-in'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham ses/ham transkript blob/ham numara + nesne-depo URI/sır sızıntısı YOK
check "Ham ses/ham transkript blob/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|audioBytes|transcriptText|rawText|msisdn|toE164|cardPan'"
check "Nesne-depo URI/sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'storageUri|signedUrl|downloadUrl|kmsKey|bearerToken|s3://|clientSecret'"
# Ham PII deseni (≥7 ardışık rakam / e-posta) GÖRÜNÜR İÇERİKTE YOK (redaction kanıtı).
# Not: <script>/<style> blokları (Next.js webpack chunk hash'leri ham rakam içerir — framework gürültüsü)
# çıkarılır; yalnız kullanıcıya görünür gövde taranır.
VISIBLE_TR=$(printf '%s' "$BODY_TR" | perl -0777 -pe 's/<script.*?<\/script>//gs; s/<style.*?<\/style>//gs')
check "Ham PII deseni (≥7 rakam/e-posta) görünür içerikte YOK" "! printf '%s' \"\$VISIBLE_TR\" | grep -qoE '[0-9]{7,}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
