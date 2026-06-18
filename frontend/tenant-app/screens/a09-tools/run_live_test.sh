#!/usr/bin/env bash
# WBS 13.4.9 — A-09 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/tools 200 + TR/EN locale + özet/bağlar/katalog/protokol/sağlık render;
# PII/CDR/transkript içeriği + ham numara + sır + ENDPOINT URL/JSON schema gövdesi/payload sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3249}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"ops@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a09_tools.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/tools" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/tools")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/tools")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/tools")

check "/workspace/tools 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Tool/API Bağlama'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Bind defined tools to agents'"
check "Bağlama özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Bağlama Özeti'"
check "Agent başına bağlar (FR-TOOL-004)" "echo \"\$BODY_TR\" | grep -q 'Agent Başına Bağlar'"
check "Tool kataloğu bölümü" "echo \"\$BODY_TR\" | grep -q 'Tool Kataloğu'"
check "Protokol dağılımı (FR-TOOL-001)" "echo \"\$BODY_TR\" | grep -q 'Protokol Dağılımı'"
check "Güvenlik & uyum sağlığı" "echo \"\$BODY_TR\" | grep -q 'Güvenlik & Uyum Sağlığı'"
check "yetki yükseltme dikkati (FR-TOOL-005)" "echo \"\$BODY_TR\" | grep -q 'Yetki yükseltme'"
check "onaysız endpoint dikkati (FR-TOOL-012)" "echo \"\$BODY_TR\" | grep -q 'Engellendi'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham PII/CDR/transkript İÇERİĞİ + ham numara + ENDPOINT URL/schema gövdesi/payload sızıntısı YOK
check "Ham PII/recordingUrl/CDR/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|msisdn|callerNumber|cardPan|\"cdr\"'"
check "Sır/credential/endpoint/schema/payload sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|apiKey|webhookSecret|requestBody|schemaBody|\"endpoint\"'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
