#!/usr/bin/env bash
# WBS 13.4.3 — A-03 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/agents 200 + TR/EN locale + özet/yaşam-döngüsü/dikkat/tüm-agent içeriği render;
# PII/CDR/transkript içeriği + ham numara + sır sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3243}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"ops@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a03_agents.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/agents" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/agents")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/agents")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/agents")

check "/workspace/agents 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Agent Listesi'"
check "EN başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Agent List'"
check "Özet bölümü" "echo \"\$BODY_TR\" | grep -q 'Özet'"
check "Yaşam döngüsü bölümü (FR-AGT-005)" "echo \"\$BODY_TR\" | grep -q 'Yaşam Döngüsü'"
check "Tüm agent tablosu (BRD §17.5)" "echo \"\$BODY_TR\" | grep -q 'Tüm Agent'"
check "Production durumu render" "echo \"\$BODY_TR\" | grep -q 'Production'"
check "Test kapısı göstergesi (FR-AGT-010)" "echo \"\$BODY_TR\" | grep -qi 'test'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant-scope'"
# Ham PII/CDR/transkript İÇERİĞİ + ham numara sızıntısı YOK
check "Ham PII/recordingUrl/CDR/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|msisdn|callerNumber|cardPan|\"cdr\"'"
check "Sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|apiKey|webhookSecret'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
