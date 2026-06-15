#!/usr/bin/env bash
# run_live_test.sh — WBS 6.1.5 Bayatlama/işaretleme (content TTL, FR-KB-008) kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; tazelik atasını 6.1.3 index pipeline'dan TÜRETİR —
# o da 6.1.1'i import eder; deterministik sanal saat). Karar policy + doküman tazelik metadata'sına dayanır
# (vendor-neutral, ADR-001/002). Bayatlama taraması OFFLINE'dır (SAD §10.1) — hot-path'e girmez.
# Canlı kb_document store'u yalnız ${KB_VECTOR_DSN} ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/content_ttl_probe.py" validate
"$PY" "$HERE/content_ttl_probe.py" selftest
"$PY" "$HERE/tests/content_ttl_behavior_test.py"

echo "== sample mark kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/content_ttl_probe.py" mark "$s"
done

if [[ -n "${KB_VECTOR_DSN:-}" ]]; then
  echo "== canlı bayatlama kapısı (${KB_VECTOR_DSN}) =="
  echo "NOT: canlı bayatlama taraması OFFLINE (SAD §10.1, Control/Analytics Plane) koşar:"
  echo "     periyodik/post-reindex tarama kb_document.{indexed_at,content_ttl_at,source_last_modified}'ı okur,"
  echo "     'now'a göre durum hesaplar, fresh→stale/expired geçişlerini content_ttl_at + durum kolonuna İŞARETLER"
  echo "     (fiziksel şema 1.1.7 / migration 0010 + ix_kbdoc_ttl partial index). Retrieval-zamanı (6.2.1) bu"
  echo "     işaretleri TÜKETİR (bayat bastırma/önceliklendirme) ama TTL'i YENİDEN HESAPLAMAZ → hot-path'e yük yok."
  echo "     Karar metadata-only (içerik/embedding/ağ yok). Metrikler (kb_documents_marked_stale_total{reason}/...,"
  echo "     PII label YASAK) observability 0.4.7'ye yayılır. Kapı kodu DEĞİŞMEZ; bu betik yalnız DSN varlığını"
  echo "     bildirir (credential \${KB_VECTOR_DSN}; repoya YAZILMAZ)."
else
  echo "== canlı bayatlama kapısı: SKIP (KB_VECTOR_DSN tanımsız) =="
fi
echo "OK"
