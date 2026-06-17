#!/usr/bin/env bash
# WBS 13.3.5 — T-05 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /admin/integrations 200 + TR/EN locale + entegrasyon/tool/API anahtarı/webhook içeriği
# render; PII/sır sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3206}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"owner@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/t05_live.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/integrations" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/admin/integrations")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/admin/integrations")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/integrations")

check "/admin/integrations 200" "[ \"$CODE\" = 200 ]"
# NOT: HTML çıktısında '&' → '&amp;' kaçışlanır; başlık kontrolleri '&' içermeyen ayırt edici alt-dizgi kullanır.
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Entegrasyon'"
check "EN başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Integration'"
check "Entegrasyonlar bölümü" "echo \"\$BODY_TR\" | grep -q 'Entegrasyonlar'"
check "Tool bölümü (FR-TOOL-001)" "echo \"\$BODY_TR\" | grep -q 'GraphQL'"
check "API Anahtarları bölümü (API.md §7)" "echo \"\$BODY_TR\" | grep -q 'Anahtar'"
check "Webhook bölümü (API.md §10)" "echo \"\$BODY_TR\" | grep -qi 'webhook'"
check "HTTPS webhook URL render" "echo \"\$BODY_TR\" | grep -q 'https://erp.kuzey.example'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'kendi tenant'"
# NOT: `transcript.ready` MEŞRU bir webhook event tipidir (API.md §10.2) — event ADI, transkript İÇERİĞİ değil.
# Leak kontrolü transkript İÇERİĞİ/alanını hedefler: `transcript` + dot-OLMAYAN karakter (event adı `.ready`
# elenir). Yapısal PII garantisi zaten assertNoPii (probe) ile sağlanır.
check "PII/transkript içeriği sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'transcript[^.]|recordingUrl|msisdn|callerNumber'"
check "API key/webhook/credential sırrı sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'signingSecret|clientSecret|bearerToken|\"secret\"|privateKey'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
