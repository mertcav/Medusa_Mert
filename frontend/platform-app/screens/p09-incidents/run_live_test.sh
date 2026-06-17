#!/usr/bin/env bash
# WBS 13.2.9 — P-09 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /incidents 200 + TR/EN locale + içerik öğeleri render + iş-içeriği route'u YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/platform-app
cd "$APP_DIR"

PORT="${PORT:-3209}"
# Sentetik platform oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
# platform realm: tenant_id YOK (L0 cross-tenant). exp uzak gelecek. Çerez adı 13.1.2 ile hizalı.
PAYLOAD='{"realm":"platform","sub":"owner@rmc.example","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_platform_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/p09_live.log 2>&1 &)
# hazır olana kadar yokla (foreground sleep'e güvenme)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/incidents" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/incidents")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/incidents")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/incidents")

check "/incidents 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'Alarm &amp; Incident'"
check "EN alt başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'incident (SRE) management'"
check "platform alarmları bölümü" "echo \"\$BODY_TR\" | grep -q 'Platform Alarmları'"
check "incident bölümü" "echo \"\$BODY_TR\" | grep -q \"Incident'ler\""
check "incident olay akışı bölümü" "echo \"\$BODY_TR\" | grep -q 'Incident Olay Akışı'"
check "alarm kural adı (SAD §17.2 kataloğu) render" "echo \"\$BODY_TR\" | grep -q 'E2EP95LatencyHigh'"
check "vendor-nötr kapsam (scope) render" "echo \"\$BODY_TR\" | grep -q 'orchestrator/EU'"
check "yönetim/altın kural uyarısı" "echo \"\$BODY_TR\" | grep -q 'platform_sre'"
check "iş içeriği route'u YOK (A5)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/recordings)\" = 404 ]"
check "transkript/PII sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'transcript|msisdn|callerid|cardpan'"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
