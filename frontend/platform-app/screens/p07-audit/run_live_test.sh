#!/usr/bin/env bash
# WBS 13.2.7 — P-07 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /audit 200 + TR/EN locale + içerik öğeleri render + iş-içeriği route'u YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/platform-app
cd "$APP_DIR"

PORT="${PORT:-3207}"
# Sentetik platform oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
# platform realm: tenant_id YOK (L0 cross-tenant). exp uzak gelecek. Çerez adı 13.1.2 ile hizalı.
PAYLOAD='{"realm":"platform","sub":"owner@rmc.example","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_platform_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/p07_live.log 2>&1 &)
# hazır olana kadar yokla (foreground sleep'e güvenme)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/audit" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/audit")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/audit")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/audit")

check "/audit 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Platform Audit &amp; Güvenlik'"
check "EN başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Platform Audit &amp; Security'"
check "audit log bölümü" "echo \"\$BODY_TR\" | grep -q 'Audit Log'"
check "break-glass bölümü" "echo \"\$BODY_TR\" | grep -q 'Break-glass'"
check "güvenlik olayları bölümü" "echo \"\$BODY_TR\" | grep -q 'Güvenlik Olayları'"
check "WORM integrity durumu (FR-IAM-006)" "echo \"\$BODY_TR\" | grep -q 'WORM'"
check "yönetim/altın kural uyarısı" "echo \"\$BODY_TR\" | grep -q 'platform_owner'"
check "iş içeriği route'u YOK (A5)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/recordings)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
