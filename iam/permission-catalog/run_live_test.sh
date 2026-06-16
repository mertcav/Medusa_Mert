#!/usr/bin/env bash
# WBS 12.1.2 — Permission-key kataloğu statik + davranış kapısı koşucusu.
# Canlı IAM entegrasyonu (12.2.x backend guard / x-required-permission enforcement) SKIP — ${PERMISSION_CATALOG_URL}.
# Sır/credential repoya yazılmaz; yalnız ortam değişkeni/--url.
set -euo pipefail
cd "$(dirname "$0")"

echo "== validate (katalog + cross-doc conformance) =="
python3 permission_catalog_probe.py validate

echo "== check (samples) =="
python3 permission_catalog_probe.py check samples

echo "== selftest (G1–G12) =="
python3 permission_catalog_probe.py selftest

echo "== bağımsız davranış testi =="
python3 tests/permission_catalog_behavior_test.py

if [[ -n "${PERMISSION_CATALOG_URL:-}" ]]; then
  echo "== canlı conformance ($PERMISSION_CATALOG_URL) =="
  echo "TODO 12.2.x: canlı backend guard x-required-permission → katalog conformance"
else
  echo "(canlı IAM entegrasyonu SKIP — \${PERMISSION_CATALOG_URL} tanımlı değil)"
fi
echo "🟢 tüm kapılar geçti"
