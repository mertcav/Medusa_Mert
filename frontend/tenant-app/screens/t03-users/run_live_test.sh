#!/usr/bin/env bash
# WBS 13.3.3 — T-03 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /admin/users 200 + TR/EN locale + RBAC/SSO/SCIM içeriği render; PII/sır sızıntısı yok.
# Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3204}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"owner@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/t03_live.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/users" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/admin/users")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/admin/users")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/users")

check "/admin/users 200" "[ \"$CODE\" = 200 ]"
# NOT: HTML çıktısında '&' → '&amp;' kaçışlanır; başlık kontrolleri '&' içermeyen ayırt edici alt-dizgi kullanır.
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Rol Yönetimi'"
check "EN başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Role Management'"
check "Kullanıcılar bölümü" "echo \"\$BODY_TR\" | grep -q 'Kullanıcılar'"
check "Roller bölümü" "echo \"\$BODY_TR\" | grep -q 'Roller'"
check "SSO/SCIM bölümü (federation)" "echo \"\$BODY_TR\" | grep -q 'SCIM Provisioning'"
check "immutable rol bundle (FR-IAM-011)" "echo \"\$BODY_TR\" | grep -q 'tenant_owner'"
check "SSO protokol render (FR-IAM-002)" "echo \"\$BODY_TR\" | grep -q 'OpenID Connect'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'kendi tenant'"
check "PII/transkript sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'transcript|recordingUrl|callerId'"
check "SSO/SCIM sırrı sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'bearerToken|clientSecret|privateKey|metadataXml'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
