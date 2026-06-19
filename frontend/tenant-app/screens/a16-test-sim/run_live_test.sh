#!/usr/bin/env bash
# WBS 13.4.16 — A-16 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/test 200 + TR/EN locale + özet/suite/senaryo/regresyon/gate/yük render;
# sentetik test/simülasyon metriği görünür; ham ses/ham transkript blob/transkript metni/gerçek-çağrı callRef/
# ham numara/nesne-depo URI/sır sızıntısı YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3256}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"designer@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a16_test.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/test" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/test")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/test")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/test")

check "/workspace/test 200" "[ \"$CODE\" = 200 ]"
# Not: başlık 'Test & Simülasyon Merkezi'; '&' HTML'de &amp; olarak kodlanır → TR'ye özgü 'Simülasyon Merkezi' aranır.
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Simülasyon Merkezi'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'persona/scenario simulation'"
check "Özet KPI bölümü" "echo \"\$BODY_TR\" | grep -q 'Özet KPI'"
check "Suite/kategori kırılımı bölümü (FR-TST-003)" "echo \"\$BODY_TR\" | grep -q 'Suite'"
check "Senaryo sonuçları bölümü (FR-TST-001/002)" "echo \"\$BODY_TR\" | grep -q 'Senaryo Sonuçları'"
check "Regresyon bölümü (FR-TST-004)" "echo \"\$BODY_TR\" | grep -q 'Regresyon'"
check "Promotion gate bölümü (FR-TST-005)" "echo \"\$BODY_TR\" | grep -q 'Promotion Gate'"
check "Yük testi bölümü (FR-TST-006/009)" "echo \"\$BODY_TR\" | grep -q 'Yük Testi'"
check "Adversarial kategori görünür (FR-TST-003)" "echo \"\$BODY_TR\" | grep -q 'Adversarial'"
check "Sentetik veri rozeti görünür (FR-TST-008)" "echo \"\$BODY_TR\" | grep -q 'Sentetik'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham ses/ham transkript blob/transkript metni/gerçek-çağrı callRef/ham numara + nesne-depo URI/sır sızıntısı YOK
check "Ham ses/transkript metni/gerçek-çağrı callRef/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|audioBytes|transcriptText|rawText|callRef|msisdn|toE164|cardPan'"
check "Nesne-depo URI/sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'storageUri|signedUrl|downloadUrl|kmsKey|bearerToken|s3://|clientSecret'"
# Ham PII deseni (e-posta / +telefon) GÖRÜNÜR İÇERİKTE YOK (redaction kanıtı). <script>/<style> blokları çıkarılır.
VISIBLE_TR=$(printf '%s' "$BODY_TR" | perl -0777 -pe 's/<script.*?<\/script>//gs; s/<style.*?<\/style>//gs')
check "Ham PII deseni (e-posta/+telefon) görünür içerikte YOK" "! printf '%s' \"\$VISIBLE_TR\" | grep -qoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}|\\+[0-9]{6,}'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
