#!/usr/bin/env bash
# WBS 13.4.8 — A-08 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/kb 200 + TR/EN locale + özet/bilgi-tabanları/dokümanlar/kaynak-türü/indeks
# render; PII/CDR/transkript içeriği + ham numara + sır + DOKÜMAN İÇERİĞİ/source_uri sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3248}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"designer@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a08_kb.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/kb" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/kb")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/kb")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/kb")

check "/workspace/kb 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Bilgi Tabanı'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Knowledge source upload and binding'"
check "Bilgi tabanı özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Bilgi Tabanı Özeti'"
check "Bilgi tabanları (FR-KB-004)" "echo \"\$BODY_TR\" | grep -q 'Bilgi Tabanları'"
check "Dokümanlar bölümü" "echo \"\$BODY_TR\" | grep -q 'Dokümanlar'"
check "Kaynak türü dağılımı (FR-KB-001)" "echo \"\$BODY_TR\" | grep -q 'Kaynak Türü Dağılımı'"
check "İndeksleme sağlığı (FR-KB-003)" "echo \"\$BODY_TR\" | grep -q 'İndeksleme Sağlığı'"
check "namespace render (FR-KB-004 izolasyon)" "echo \"\$BODY_TR\" | grep -q 'ten2048/'"
check "hassas doküman bayrağı (FR-KB-010)" "echo \"\$BODY_TR\" | grep -q 'Hassas'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham PII/CDR/transkript İÇERİĞİ + ham numara + DOKÜMAN İÇERİĞİ/source_uri sızıntısı YOK
check "Ham PII/recordingUrl/CDR/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|msisdn|callerNumber|cardPan|\"cdr\"'"
check "Sır/credential/doküman-içeriği/source_uri sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|apiKey|webhookSecret|chunkContent|sourceUri|embedding'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
