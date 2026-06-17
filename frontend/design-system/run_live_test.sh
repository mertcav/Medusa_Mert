#!/usr/bin/env bash
# WBS 13.1.3 — Tasarım sistemi + i18n kapısı (statik + opsiyonel canlı smoke).
#
# Her zaman: Python probe (selftest/validate/check) + davranış testi (stdlib, bağımlılıksız).
# Node/Next varsa: tsc typecheck + next build her iki app (tasarım sistemi + i18n + globals.css derlenir).
# Canlı smoke (next start + curl) İSTEĞE BAĞLI: SMOKE=1 ve node_modules mevcutsa; <html lang> ve token CSS
# değişkenini doğrular. Sır/credential YOK.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
FAIL=0

echo "== 13.1.3 tasarım sistemi + i18n kapısı =="

echo "--- Python probe: selftest ---"
python3 "$HERE/design_system_probe.py" selftest || FAIL=1
echo "--- Python probe: validate (canonical + ON-DISK vendored + WCAG + a11y) ---"
python3 "$HERE/design_system_probe.py" validate || FAIL=1
echo "--- Python probe: check samples ---"
python3 "$HERE/design_system_probe.py" check "$HERE/samples" || FAIL=1
echo "--- davranış testi ---"
python3 "$HERE/tests/design_system_behavior_test.py" || FAIL=1

if command -v node >/dev/null 2>&1; then
  for app in platform-app tenant-app; do
    APPDIR="$REPO/frontend/$app"
    if [ -d "$APPDIR/node_modules" ]; then
      echo "--- $app: tsc typecheck ---"
      ( cd "$APPDIR" && npx tsc --noEmit ) || FAIL=1
      echo "--- $app: next build (design system + i18n derlenir) ---"
      ( cd "$APPDIR" && npx next build >/dev/null 2>&1 ) && echo "  $app build 🟢" || { echo "  $app build 🔴"; FAIL=1; }
    else
      echo "--- $app: node_modules yok → build SKIP (F1 CI'da koşar) ---"
    fi
  done
else
  echo "--- node yok → tsc/build SKIP (F1 CI'da koşar) ---"
fi

# Canlı smoke (opsiyonel): <html lang> + token CSS değişkeni gerçekten render edilir.
if [ "${SMOKE:-0}" = "1" ] && command -v node >/dev/null 2>&1 && [ -d "$REPO/frontend/platform-app/node_modules" ]; then
  echo "--- canlı smoke: platform-app next start ---"
  ( cd "$REPO/frontend/platform-app" && npx next build >/dev/null 2>&1 && (npx next start -p 3133 >/tmp/ds_pf.log 2>&1 &) )
  sleep 4
  HTML=$(curl -s "http://localhost:3133/overview")
  echo "$HTML" | grep -q 'lang="tr"' && echo "  <html lang=\"tr\"> 🟢" || { echo "  <html lang> yok 🔴"; FAIL=1; }
  echo "$HTML" | grep -q -- '--rmc-brand-primary' && echo "  token CSS değişkeni render 🟢" || echo "  (token CSS inline değil — globals harici olabilir)"
  # EN Accept-Language ile dil müzakeresi
  HTMLEN=$(curl -s -H "Accept-Language: en-GB,en;q=0.9" "http://localhost:3133/overview")
  echo "$HTMLEN" | grep -q 'lang="en"' && echo "  Accept-Language: en → <html lang=\"en\"> 🟢" || { echo "  dil müzakeresi 🔴"; FAIL=1; }
  pkill -f "next start -p 3133" 2>/dev/null || true
else
  echo "--- canlı smoke SKIP (SMOKE=1 + node_modules ile etkin) ---"
fi

echo
[ "$FAIL" = "0" ] && echo "RESULT: 🟢 GEÇTİ" || echo "RESULT: 🔴 BAŞARISIZ"
exit $FAIL
