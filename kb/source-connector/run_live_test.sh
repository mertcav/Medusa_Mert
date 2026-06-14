#!/usr/bin/env bash
# run_live_test.sh — WBS 6.1.2 SharePoint/Confluence connector kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; SharePoint/Confluence native snapshot'larını
# parse eder + 6.1.1 FormatExtractor'a devreder). Canlı kurumsal-kaynak senkronizasyonu yalnız
# ${KB_SOURCE_ENDPOINT} + ${KB_SOURCE_OAUTH_TOKEN} ORTAM DEĞİŞKENLERİ verilirse not düşülür; yoksa
# SKIP. Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/source_connector_probe.py" validate
"$PY" "$HERE/source_connector_probe.py" selftest
"$PY" "$HERE/tests/source_connector_behavior_test.py"

echo "== sample sync kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/source_connector_probe.py" sync "$s"
done

if [[ -n "${KB_SOURCE_ENDPOINT:-}" && -n "${KB_SOURCE_OAUTH_TOKEN:-}" ]]; then
  echo "== canlı kurumsal-kaynak senkron kapısı (${KB_SOURCE_ENDPOINT}) =="
  echo "NOT: canlı doğrulama Control/Analytics Plane senkron servisinde (SAD §10.1) koşulur: L1/L2"
  echo "     'POST /knowledge-bases/{id}/sources' ile bağlanan GERÇEK SharePoint site (Microsoft Graph"
  echo "     drive delta) / Confluence space (Cloud REST) → aynı EnterpriseSourceConnector SPI'si ile"
  echo "     enumerate + change-token delta + kaynak ACL eşleme; her doküman 6.1.1 FormatExtractor"
  echo "     registry'sine DEVREDİLİR (canlıda ağır PDF/Office kütüphanesi aynı SPI arkası, ADR-001/002);"
  echo "     NormalizedDocument 6.1.3 chunk→embed→index+versiyonlama hattına devredilir; tenant/kb"
  echo "     namespace + endpoint allowlist + SSRF + residency home-region + no_log + redaction_state="
  echo "     pending (FR-KB-010/NFR 10.7) zorlanır; metrikler (kb_source_sync_total{connector,status}/...)"
  echo "     observability 0.4.7'ye yayılır. Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını"
  echo "     bildirir (credential \${KB_SOURCE_OAUTH_TOKEN}; repoya YAZILMAZ)."
else
  echo "== canlı kurumsal-kaynak senkron kapısı: SKIP (KB_SOURCE_ENDPOINT/KB_SOURCE_OAUTH_TOKEN tanımsız) =="
fi
echo "OK"
