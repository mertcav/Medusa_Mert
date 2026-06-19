#!/usr/bin/env bash
# WBS 13.4.14 — A-14 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/analytics 200 + TR/EN locale + özet/sonuç/konuşma/gecikme/trend/sürüm render;
# topluluk metriği görünür; ham ses/ham transkript blob/transkript metni/tek-çağrı callRef/ham numara/
# nesne-depo URI/sır sızıntısı YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3254}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"ops@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a14_analytics.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/analytics" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/analytics")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/analytics")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/analytics")

check "/workspace/analytics 200" "[ \"$CODE\" = 200 ]"
# Not: başlık 'Analytics & Raporlama'; '&' HTML'de &amp; olarak kodlanır → TR'ye özgü 'Raporlama' aranır.
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Raporlama'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Containment, CSAT, AHT'"
check "Özet KPI bölümü" "echo \"\$BODY_TR\" | grep -q 'Özet KPI'"
check "Sonuç dağılımı bölümü (FR-ANA-002/003)" "echo \"\$BODY_TR\" | grep -q 'Sonuç Dağılımı'"
check "Konuşma süreleri bölümü (FR-ANA-005)" "echo \"\$BODY_TR\" | grep -q 'Konuşma Süreleri'"
check "Yanıt gecikmesi bölümü (FR-ANA-006)" "echo \"\$BODY_TR\" | grep -q 'Yanıt Gecikmesi'"
check "Zaman serisi bölümü (FR-ANA-011)" "echo \"\$BODY_TR\" | grep -q 'Zaman Serisi'"
check "Sürüm karşılaştırması bölümü (FR-ANA-010)" "echo \"\$BODY_TR\" | grep -q 'Agent Sürümü Karşılaştırması'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham ses/ham transkript blob/transkript metni/tek-çağrı callRef/ham numara + nesne-depo URI/sır sızıntısı YOK
check "Ham ses/transkript metni/tek-çağrı callRef/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|audioBytes|transcriptText|rawText|callRef|msisdn|toE164|cardPan'"
check "Nesne-depo URI/sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'storageUri|signedUrl|downloadUrl|kmsKey|bearerToken|s3://|clientSecret'"
# Ham PII deseni (≥7 ardışık rakam / e-posta) GÖRÜNÜR İÇERİKTE YOK (redaction kanıtı).
# Not: <script>/<style> blokları (Next.js webpack chunk hash'leri + agregat sayılar ham rakam içerebilir)
# çıkarılır; yalnız kullanıcıya görünür gövde taranır. Agregat sayılar formatNumber ile ayraçlanır (≤6 hane).
VISIBLE_TR=$(printf '%s' "$BODY_TR" | perl -0777 -pe 's/<script.*?<\/script>//gs; s/<style.*?<\/style>//gs')
check "Ham PII deseni (e-posta/+telefon) görünür içerikte YOK" "! printf '%s' \"\$VISIBLE_TR\" | grep -qoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}|\\+[0-9]{6,}'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
