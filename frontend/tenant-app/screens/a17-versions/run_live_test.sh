#!/usr/bin/env bash
# WBS 13.4.17 — A-17 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/versions 200 + TR/EN locale + özet/sürüm geçmişi/aşama/rollback render;
# sürüm META görünür; ham ses/ham transkript blob/transkript metni/agent_version snapshot gövdesi/ham numara/
# nesne-depo URI/sır sızıntısı YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3257}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"designer@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a17_versions.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/versions" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/versions")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/versions")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/versions")

check "/workspace/versions 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Sürüm Geçmişi'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Agent versions and rollback'"
check "Sürüm Özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Sürüm Özeti'"
check "Sürüm Geçmişi bölümü (DB §5.2 agent_version)" "echo \"\$BODY_TR\" | grep -q 'Sürüm Geçmişi'"
check "Aşama Dağılımı bölümü (FR-AGT-005)" "echo \"\$BODY_TR\" | grep -q 'Aşama Dağılımı'"
check "Rollback bölümü (FR-AGT-006)" "echo \"\$BODY_TR\" | grep -q 'Geri Alma'"
check "Aktif sürüm rozeti görünür" "echo \"\$BODY_TR\" | grep -q 'Aktif'"
check "Rollback köken rozeti görünür (WORM)" "echo \"\$BODY_TR\" | grep -q 'Geri alma'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham ses/ham transkript blob/transkript metni/snapshot gövdesi/ham numara + nesne-depo URI/sır sızıntısı YOK
check "Ham ses/transkript metni/snapshot gövdesi/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|audioBytes|transcriptText|rawText|\"snapshot\"|promptText|flowDefinition|msisdn|toE164|cardPan'"
check "Nesne-depo URI/sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'storageUri|signedUrl|downloadUrl|kmsKey|bearerToken|s3://|clientSecret'"
# Ham PII deseni (e-posta / +telefon) GÖRÜNÜR İÇERİKTE YOK (redaction kanıtı). <script>/<style> blokları çıkarılır.
VISIBLE_TR=$(printf '%s' "$BODY_TR" | perl -0777 -pe 's/<script.*?<\/script>//gs; s/<style.*?<\/style>//gs')
check "Ham PII deseni (e-posta/+telefon) görünür içerikte YOK" "! printf '%s' \"\$VISIBLE_TR\" | grep -qoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}|\\+[0-9]{6,}'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
