#!/usr/bin/env bash
# WBS 13.3.8 — T-08 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /admin/audit 200 + TR/EN locale + özet/bütünlük/kategori/break-glass/kayıt içeriği
# render; PII/CDR/transkript-içeriği + sır sızıntısı yok. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3209}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"owner@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/t08_live.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/audit" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/admin/audit")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/admin/audit")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/admin/audit")

check "/admin/audit 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Audit Log'"
check "EN bölüm render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'Summary'"
check "Bütünlük bölümü (FR-IAM-006/ADR-016)" "echo \"\$BODY_TR\" | grep -q 'Bütünlük'"
check "WORM alanı render" "echo \"\$BODY_TR\" | grep -qi 'WORM'"
check "Kategori dağılımı bölümü" "echo \"\$BODY_TR\" | grep -qi 'Kategori'"
check "Break-glass bölümü (FR-IAM-009)" "echo \"\$BODY_TR\" | grep -qi 'Break-glass'"
check "Audit kayıt tablosu (FR-REC-009)" "echo \"\$BODY_TR\" | grep -qi 'Audit Kayıt'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'kendi tenant'"
# PII/CDR/transkript İÇERİĞİ sızıntısı YOK (alan adı/ham içerik hedefi). 'transcript:read' EYLEM ADI meşru.
check "Ham PII/recordingUrl/CDR içeriği sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|msisdn|callerNumber|cardPan|\"cdr\"'"
check "Sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'clientSecret|bearerToken|kmsKey|privateKey|apiKey'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
