#!/usr/bin/env bash
# WBS 13.3.4 — T-04 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /admin/numbers 200 + TR/EN locale + numara havuzu/SIP trunk/Caller ID içeriği render;
# PII/sır sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3205}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"owner@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/t04_live.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/numbers" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/admin/numbers")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/admin/numbers")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/numbers")

check "/admin/numbers 200" "[ \"$CODE\" = 200 ]"
# NOT: HTML çıktısında '&' → '&amp;' kaçışlanır; başlık kontrolleri '&' içermeyen ayırt edici alt-dizgi kullanır.
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Telefon Numarası'"
check "EN başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Phone Number'"
check "SIP Trunk bölümü (FR-TEL-002)" "echo \"\$BODY_TR\" | grep -q 'SIP Trunk'"
check "BYOC trunk türü render" "echo \"\$BODY_TR\" | grep -q 'BYOC'"
check "Numara Havuzu bölümü" "echo \"\$BODY_TR\" | grep -q 'Numara Havuzu'"
check "Caller ID bölümü (FR-TEL-005)" "echo \"\$BODY_TR\" | grep -q 'Caller ID'"
check "E.164 numara render (FR-TEL-004)" "echo \"\$BODY_TR\" | grep -q '+902123456789'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'kendi tenant'"
check "PII/transkript/arayan sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'transcript|recordingUrl|msisdn|callerNumber'"
check "SIP trunk sırrı sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'sipPassword|authToken|\"credential\"|privateKey'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
