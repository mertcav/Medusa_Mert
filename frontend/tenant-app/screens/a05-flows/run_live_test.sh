#!/usr/bin/env bash
# WBS 13.4.5 — A-05 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/flows 200 + TR/EN locale + özet/doğrulama/düğüm türü/düğümler/geçişler render;
# PII/CDR/transkript içeriği + ham numara + sır + prompt-gövdesi sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3245}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"designer@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a05_flows.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/flows" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/flows")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/flows")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/flows")

check "/workspace/flows 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Conversation Flow Editor'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Node/flow based process design'"
check "Akış özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Akış Özeti'"
check "Doğrulama & sağlık kapısı (FR-AGT-010)" "echo \"\$BODY_TR\" | grep -q 'Doğrulama ve Sağlık'"
check "Düğüm türü dağılımı" "echo \"\$BODY_TR\" | grep -q 'Düğüm Türü Dağılımı'"
check "Düğümler bölümü" "echo \"\$BODY_TR\" | grep -q 'Düğümler'"
check "Geçişler bölümü" "echo \"\$BODY_TR\" | grep -q 'Geçişler'"
check "Node/flow modu göstergesi (FR-AGT-003)" "echo \"\$BODY_TR\" | grep -qi 'Akış (node)'"
check "İnsan aktarımı düğümü (handoff)" "echo \"\$BODY_TR\" | grep -q 'İnsan Aktarımı'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham PII/CDR/transkript İÇERİĞİ + ham numara + prompt-gövdesi sızıntısı YOK
check "Ham PII/recordingUrl/CDR/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|msisdn|callerNumber|cardPan|\"cdr\"'"
check "Sır/credential/prompt-gövdesi sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|apiKey|webhookSecret|promptText|promptBody'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
