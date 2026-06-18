#!/usr/bin/env bash
# WBS 13.3.6 — T-06 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /admin/compliance 200 + TR/EN locale + consent/kayıt/residency/saklama/profil/İYS-DNC
# içeriği render; PII/sır sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3207}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"owner@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/t06_live.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/compliance" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/admin/compliance")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/admin/compliance")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/compliance")

check "/admin/compliance 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Compliance'"
check "EN bölüm render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Retention'"
check "Kayıt Politikası bölümü (FR-REC-001)" "echo \"\$BODY_TR\" | grep -q 'Kayıt Politikası'"
check "Veri Yerleşimi bölümü (NFR 10.7)" "echo \"\$BODY_TR\" | grep -q 'Veri Yerleşimi'"
check "Saklama bölümü (FR-REC-006)" "echo \"\$BODY_TR\" | grep -q 'Saklama'"
check "Outbound/İYS/DNC bölümü (FR-OUT-006)" "echo \"\$BODY_TR\" | grep -qi 'DNC'"
check "Compliance profile render (DPIA §6)" "echo \"\$BODY_TR\" | grep -q 'PROFILE-TR'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'kendi tenant'"
# PII/transkript İÇERİĞİ sızıntısı YOK (alan adı/ham içerik hedefi). 'recordingPolicy' politika parametresi → izinli.
check "PII/transkript içeriği sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'transcript[^.]|recordingUrl|msisdn|callerNumber|cardPan'"
check "Sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|\"secret\"'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
