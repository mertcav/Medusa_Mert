#!/usr/bin/env bash
# run_live_test.sh — WBS 1.1.5 canlı Redis davranış kapısı koşucusu.
# redis-server varsa: iki örnek (session + cache pool) başlatır, davranış testini
# koşar, teardown yapar. Yoksa SKIP (exit 0) — db/run_live_test.sh deseniyle aynı.
# Credential-free (loopback, parolasız local). Sır/credential repoya yazılmaz.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v redis-server >/dev/null 2>&1; then
  echo "SKIP: redis-server bulunamadı (CI'da gerçek Redis ile koşar)."
  exit 0
fi

SESSION_PORT="${SESSION_PORT:-6701}"
CACHE_PORT="${CACHE_PORT:-6702}"
TMPDIR_RUN="$(mktemp -d)"
SPID=""; CPID=""

cleanup() {
  [ -n "$SPID" ] && kill "$SPID" 2>/dev/null
  [ -n "$CPID" ] && kill "$CPID" 2>/dev/null
  wait 2>/dev/null
  rm -rf "$TMPDIR_RUN"
}
trap cleanup EXIT

# Repo config + yalnız port/dir/log override (politikalar config'ten gelir).
redis-server "$HERE/config/redis-session.conf" \
  --port "$SESSION_PORT" --dir "$TMPDIR_RUN" \
  --logfile "$TMPDIR_RUN/session.log" --daemonize no &
SPID=$!
redis-server "$HERE/config/redis-cache.conf" \
  --port "$CACHE_PORT" --dir "$TMPDIR_RUN" \
  --logfile "$TMPDIR_RUN/cache.log" --daemonize no &
CPID=$!

echo "redis: session=127.0.0.1:$SESSION_PORT (pid $SPID) cache=127.0.0.1:$CACHE_PORT (pid $CPID)"
python3 "$HERE/tests/cache_behavior_test.py" "$SESSION_PORT" "$CACHE_PORT"
RC=$?
echo "=== run_live_test exit $RC ==="
exit $RC
