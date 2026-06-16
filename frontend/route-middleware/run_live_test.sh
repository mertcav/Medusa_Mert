#!/usr/bin/env bash
# WBS 13.1.2 — Route-group middleware kapısı (statik + opsiyonel canlı smoke).
#
# Her zaman: Python probe (selftest/validate/check) + davranış testi (stdlib, bağımlılıksız).
# Node/Next varsa: tsc typecheck + next build her iki app (middleware derlenir).
# Canlı smoke (next start + curl) İSTEĞE BAĞLI: SMOKE=1 ve node_modules mevcutsa koşar; yoksa SKIP.
#
# Sır/credential YOK: oturum token'ı sentetik (base64url payload); imza doğrulanmaz (backend doğrular — A8).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
FAIL=0

echo "== 13.1.2 route-group middleware kapısı =="

echo "--- Python probe: selftest ---"
python3 "$HERE/route_middleware_probe.py" selftest || FAIL=1
echo "--- Python probe: validate (ON-DISK) ---"
python3 "$HERE/route_middleware_probe.py" validate || FAIL=1
echo "--- Python probe: check samples ---"
python3 "$HERE/route_middleware_probe.py" check "$HERE/samples" || FAIL=1
echo "--- davranış testi ---"
python3 "$HERE/tests/middleware_behavior_test.py" || FAIL=1

if command -v node >/dev/null 2>&1; then
  for app in platform-app tenant-app; do
    APPDIR="$REPO/frontend/$app"
    if [ -d "$APPDIR/node_modules" ]; then
      echo "--- $app: tsc typecheck ---"
      ( cd "$APPDIR" && npx tsc --noEmit ) || FAIL=1
      echo "--- $app: next build (middleware derlenir) ---"
      ( cd "$APPDIR" && npx next build >/dev/null 2>&1 ) && echo "  $app build 🟢" || { echo "  $app build 🔴"; FAIL=1; }
    else
      echo "--- $app: node_modules yok → build SKIP (F1 CI'da koşar) ---"
    fi
  done
else
  echo "--- node yok → tsc/build SKIP (F1 CI'da koşar) ---"
fi

# Canlı smoke (opsiyonel): middleware'in gerçek redirect/forbid davranışı.
if [ "${SMOKE:-0}" = "1" ] && command -v node >/dev/null 2>&1 && [ -d "$REPO/frontend/tenant-app/node_modules" ]; then
  echo "--- canlı smoke: tenant-app next start ---"
  ( cd "$REPO/frontend/tenant-app" && npx next build >/dev/null 2>&1 && (npx next start -p 3122 >/tmp/mw_tn.log 2>&1 &) )
  sleep 4
  # oturumsuz korumalı path → 307 redirect (login)
  CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:3122/admin/users")
  echo "  /admin/users (oturumsuz) → HTTP $CODE (beklenen 307 redirect)"
  [ "$CODE" = "307" ] || [ "$CODE" = "302" ] || FAIL=1
  pkill -f "next start -p 3122" 2>/dev/null || true
else
  echo "--- canlı smoke SKIP (SMOKE=1 + node_modules ile etkin) ---"
fi

echo
[ "$FAIL" = "0" ] && echo "RESULT: 🟢 GEÇTİ" || echo "RESULT: 🔴 BAŞARISIZ"
exit $FAIL
