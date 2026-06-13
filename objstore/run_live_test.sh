#!/usr/bin/env bash
# run_live_test.sh — WBS 1.1.6 canlı S3-uyumlu davranış kapısı koşucusu.
# minio + aws (veya mevcut S3-uyumlu endpoint) varsa: yerel MinIO başlatır, davranış
# testini koşar, teardown yapar. Yoksa SKIP (exit 0) — cache/run_live_test.sh deseniyle aynı.
# Credential/endpoint YALNIZCA ortam değişkeninden; sır repoya yazılmaz.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1) Halihazırda dışarıdan bir endpoint verildiyse doğrudan onu kullan.
if [ -n "${OBJSTORE_ENDPOINT:-}" ] && command -v aws >/dev/null 2>&1; then
  echo "objstore: dış endpoint kullanılıyor ($OBJSTORE_ENDPOINT)"
  python3 "$HERE/tests/objstore_behavior_test.py"
  RC=$?
  echo "=== run_live_test exit $RC ==="
  exit $RC
fi

# 2) Yerel MinIO + aws ile kendi endpoint'imizi ayağa kaldır.
if ! command -v minio >/dev/null 2>&1 || ! command -v aws >/dev/null 2>&1; then
  echo "SKIP: minio veya aws bulunamadı (CI'da S3-uyumlu endpoint ile koşar)."
  echo "      Çalışan davranış kapısı: python3 objstore/objstore_probe.py selftest"
  exit 0
fi

PORT="${OBJSTORE_PORT:-9100}"
TMPDIR_RUN="$(mktemp -d)"
# Test-yerel, ephemeral credential (repoda DEĞİL; yalnız bu kabuk oturumunda).
export MINIO_ROOT_USER="probe$(date +%s 2>/dev/null || echo 0)"
export MINIO_ROOT_PASSWORD="probe-$(head -c8 /dev/urandom | od -An -tx1 | tr -d ' \n')"
MPID=""

cleanup() {
  [ -n "$MPID" ] && kill "$MPID" 2>/dev/null
  wait 2>/dev/null
  rm -rf "$TMPDIR_RUN"
}
trap cleanup EXIT

minio server "$TMPDIR_RUN" --address "127.0.0.1:$PORT" >"$TMPDIR_RUN/minio.log" 2>&1 &
MPID=$!
sleep 2

export OBJSTORE_ENDPOINT="http://127.0.0.1:$PORT"
export AWS_ACCESS_KEY_ID="$MINIO_ROOT_USER"
export AWS_SECRET_ACCESS_KEY="$MINIO_ROOT_PASSWORD"
export AWS_DEFAULT_REGION="us-east-1"

echo "objstore: yerel MinIO 127.0.0.1:$PORT (pid $MPID)"
python3 "$HERE/tests/objstore_behavior_test.py"
RC=$?
echo "=== run_live_test exit $RC ==="
exit $RC
