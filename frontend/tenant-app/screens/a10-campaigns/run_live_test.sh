#!/usr/bin/env bash
# WBS 13.4.10 — A-10 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/campaigns 200 + TR/EN locale + özet/kampanyalar/uyum/durum/disposition render;
# aranacak ham numara/e164 + müşteri PII/CDR + script gövdesi + sır sızıntısı YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3250}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"ops@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a10_campaigns.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/campaigns" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/campaigns")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/campaigns")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/campaigns")

check "/workspace/campaigns 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Outbound Kampanya Yönetimi'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'List, scheduling, consent/suppression'"
check "Kampanya özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Kampanya Özeti'"
check "Kampanyalar bölümü (FR-OUT-001/010)" "echo \"\$BODY_TR\" | grep -q 'Kampanyalar'"
check "Uyum & suppression sağlığı (FR-OUT-003/006)" "echo \"\$BODY_TR\" | grep -q 'Uyum'"
check "Durum dağılımı (FR-OUT-010)" "echo \"\$BODY_TR\" | grep -q 'Durum Dağılımı'"
check "Disposition dağılımı (FR-OUT-008/011)" "echo \"\$BODY_TR\" | grep -q 'Disposition Dağılımı'"
check "consent kapalı dikkati (FR-OUT-003)" "echo \"\$BODY_TR\" | grep -q 'consent'"
check "kapasite aşımı dikkati (FR-OUT-007)" "echo \"\$BODY_TR\" | grep -qi 'kapasite'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham PII/CDR/transkript + aranacak ham numara/e164 + script gövdesi + sır sızıntısı YOK
check "Ham PII/numara/e164/CDR sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|msisdn|\"e164\"|callerNumber|cardPan|\"cdr\"|externalRef'"
check "Sır/credential/script-gövdesi sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|apiKey|scriptBody'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
