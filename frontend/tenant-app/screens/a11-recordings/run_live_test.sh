#!/usr/bin/env bash
# WBS 13.4.11 — A-11 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/recordings 200 + TR/EN locale + özet/kayıtlar/sonuç/kayıt-durumu/saklama/erişim render;
# ham PII/ses kaydı/transkript metni + ham numara + nesne-depo URI/sır sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3251}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"ops@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a11_recordings.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/recordings" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/recordings")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/recordings")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/recordings")

check "/workspace/recordings 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Çağrı Kayıtları'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Record search'"
check "Kayıt özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Kayıt Özeti'"
check "Çağrı kayıtları tablosu (arama/filtreleme)" "echo \"\$BODY_TR\" | grep -q 'Çağrı Kayıtları'"
check "Sonuç dağılımı (FR-ANA-002/003)" "echo \"\$BODY_TR\" | grep -q 'Sonuç Dağılımı'"
check "Kayıt durumu dağılımı (FR-REC-001/002/003)" "echo \"\$BODY_TR\" | grep -q 'Kayıt Durumu Dağılımı'"
check "Saklama & yasal tutma sağlığı (FR-REC-006/007/010)" "echo \"\$BODY_TR\" | grep -q 'Yasal Tutma Sağlığı'"
check "Erişim & redaction sağlığı (FR-REC-004/005/009)" "echo \"\$BODY_TR\" | grep -q 'Redaction Sağlığı'"
check "redaction-bekleyen dikkati (FR-REC-004)" "echo \"\$BODY_TR\" | grep -qi 'redaction'"
check "silinmek-üzere dikkati (FR-REC-006/010)" "echo \"\$BODY_TR\" | grep -q 'Silinmek'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham PII/ses/transkript İÇERİĞİ + ham numara + nesne-depo URI/sır sızıntısı YOK
check "Ham ses/transkript metni/ham numara/CDR sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|audioBytes|transcriptText|msisdn|callerNumber|toE164|cardPan'"
check "Nesne-depo URI/sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'storageUri|signedUrl|downloadUrl|kmsKey|bearerToken|s3://|clientSecret'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
