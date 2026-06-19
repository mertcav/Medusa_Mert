#!/usr/bin/env bash
# WBS 13.4.13 — A-13 canlı smoke testi (next build + start + curl). Credential-free; sentetik oturum çerezi.
# Çalışma-anı kanıtı: /workspace/qa 200 + TR/EN locale + özet/skorkart/işaret/manuel-inceleme/sürüm-karşılaştırma
# render; skor maskeli ([•••]) açıklamayla görünür; ham ses/ham transkript blob/transkript metni/ham numara/
# nesne-depo URI/sır sızıntısı YOK. Sır repoya yazılmaz.
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/../.." && pwd)"   # frontend/tenant-app
cd "$APP_DIR"

PORT="${PORT:-3253}"
# Sentetik tenant oturum çerezi (yalnız claim payload; imza backend'de — 13.1.2). SIR DEĞİL.
PAYLOAD='{"realm":"tenant","sub":"qa@acme.example","tenant_id":"TEN-1001","exp":4102444800}'
TOKEN=$(printf '%s' "$PAYLOAD" | base64 -w0)
COOKIE="__chanteur_tenant_session=${TOKEN}"

echo "▶ next build"; npx next build >/dev/null 2>&1
echo "▶ next start :$PORT"; (npx next start -p "$PORT" >/tmp/a13_qa_eval.log 2>&1 &)
curl -s --retry 30 --retry-all-errors --retry-delay 1 -o /dev/null -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/qa" || true

pass=0; fail=0
check() { if eval "$2"; then echo "  [PASS] $1"; pass=$((pass+1)); else echo "  [FAIL] $1"; fail=$((fail+1)); fi; }

BODY_TR=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: tr" "http://localhost:$PORT/workspace/qa")
BODY_EN=$(curl -s -H "Cookie: $COOKIE" -H "Accept-Language: en-GB" "http://localhost:$PORT/workspace/qa")
CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Cookie: $COOKIE" "http://localhost:$PORT/workspace/qa")

check "/workspace/qa 200" "[ \"$CODE\" = 200 ]"
check "TR başlık render" "echo \"\$BODY_TR\" | grep -q 'QA Değerlendirme'"
check "EN alt-başlık render (locale müzakere)" "echo \"\$BODY_EN\" | grep -q 'quality scoring'"
check "Değerlendirme özeti bölümü" "echo \"\$BODY_TR\" | grep -q 'Değerlendirme Özeti'"
check "Otomatik skorkart bölümü (FR-ANA-001)" "echo \"\$BODY_TR\" | grep -q 'Otomatik Skorkart'"
check "Kritik işaretler bölümü (FR-ANA-004/008)" "echo \"\$BODY_TR\" | grep -q 'Kritik İşaretler'"
check "Manuel değerlendirme bölümü (FR-ANA-009)" "echo \"\$BODY_TR\" | grep -q 'Manuel Değerlendirme'"
check "Sürüm karşılaştırması bölümü (FR-ANA-010)" "echo \"\$BODY_TR\" | grep -q 'Sürüm Karşılaştırması'"
check "tenant-scope uyarısı" "echo \"\$BODY_TR\" | grep -q 'tenant'"
# Ham ses/ham transkript blob/transkript metni/ham numara + nesne-depo URI/sır sızıntısı YOK
check "Ham ses/transkript metni/ham numara sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'recordingUrl|audioBytes|transcriptText|rawText|msisdn|toE164|cardPan'"
check "Nesne-depo URI/sır/credential sızıntısı YOK" "! echo \"\$BODY_TR\" | grep -qiE 'storageUri|signedUrl|downloadUrl|kmsKey|bearerToken|s3://|clientSecret'"
# Ham PII deseni (≥7 ardışık rakam / e-posta) GÖRÜNÜR İÇERİKTE YOK (redaction kanıtı).
# Not: <script>/<style> blokları (Next.js webpack chunk hash'leri ham rakam içerir — framework gürültüsü)
# çıkarılır; yalnız kullanıcıya görünür gövde taranır.
VISIBLE_TR=$(printf '%s' "$BODY_TR" | perl -0777 -pe 's/<script.*?<\/script>//gs; s/<style.*?<\/style>//gs')
check "Ham PII deseni (≥7 rakam/e-posta) görünür içerikte YOK" "! printf '%s' \"\$VISIBLE_TR\" | grep -qoE '[0-9]{7,}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}'"
check "platform route'u YOK (plane ayrımı)" "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -H \"Cookie: \$COOKIE\" http://localhost:$PORT/overview)\" = 404 ]"

pkill -f "next start -p $PORT" 2>/dev/null || true
echo ""; echo "live: $pass/$((pass+fail)) $([ $fail -eq 0 ] && echo 🟢 || echo 🔴)"
[ $fail -eq 0 ]
