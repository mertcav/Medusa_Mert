#!/usr/bin/env bash
# run_live_test.sh — WBS 6.1.1 Ingest connector (PDF/Word/HTML/metin/CSV/web) kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; gerçek fixture dosyalarını gerçek
# ayıklayıcılarla parse eder). Canlı web-fetch doğrulaması yalnız ${KB_WEB_FETCH_BASE_URL}
# ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP. Sır/credential ve gerçek PII repoya
# yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/ingest_connector_probe.py" validate
"$PY" "$HERE/ingest_connector_probe.py" selftest
"$PY" "$HERE/tests/ingest_connector_behavior_test.py"

echo "== sample ingest kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/ingest_connector_probe.py" ingest "$s"
done

if [[ -n "${KB_WEB_FETCH_BASE_URL:-}" ]]; then
  echo "== canlı web-fetch ingest kapısı (${KB_WEB_FETCH_BASE_URL}) =="
  echo "NOT: canlı doğrulama Control/Analytics Plane ingest servisinde (SAD §10.1) koşulur: L1/L2"
  echo "     'POST /knowledge-bases/{id}/documents' (async) ile yüklenen GERÇEK PDF/Word/HTML/CSV/metin"
  echo "     dosyaları + SSRF-guard'lı web URL fetch → aynı IngestConnector SPI'si (FormatExtractor"
  echo "     registry) ile parse+normalize edilir; canlıda referans stdlib ayıklayıcı yerine ağır"
  echo "     PDF/Office kütüphanesi AYNI SPI arkasına takılır (ADR-001/002). NormalizedDocument 6.1.3"
  echo "     chunk→embed→index+versiyonlama hattına devredilir; tenant/kb namespace + residency"
  echo "     home-region + no_log + redaction_state=pending (FR-KB-010/NFR 10.7) zorlanır; metrikler"
  echo "     (kb_ingest_total{format,status}/...) observability 0.4.7'ye yayılır. Sentetik içerik"
  echo "     (FR-TST-008). Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir"
  echo "     (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı web-fetch ingest kapısı: SKIP (KB_WEB_FETCH_BASE_URL tanımsız) =="
fi
echo "OK"
