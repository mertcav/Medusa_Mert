#!/usr/bin/env bash
# run_live_test.sh — WBS 6.2.1 Vector search (top-k) + opsiyonel rerank (SAD §10.2) kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; AKTİF IndexedChunk'ı 6.1.3 index pipeline'dan
# TÜRETİR, ACL pre-filtreyi 6.1.4'ten TÜKETİR — deterministik). Embedding/rerank birer SPI arkasında
# (vendor-neutral); referans deterministik feature-hash BoW embedder + coverage reranker.
# Canlı ANN store (pgvector/OpenSearch) yalnız ${KB_VECTOR_DSN} ORTAM DEĞİŞKENİ verilirse not düşülür.
# Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/retrieval_probe.py" validate
"$PY" "$HERE/retrieval_probe.py" selftest
"$PY" "$HERE/tests/retrieval_behavior_test.py"

echo "== sample retrieve kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/retrieval_probe.py" retrieve "$s"
done

if [[ -n "${KB_VECTOR_DSN:-}" ]]; then
  echo "== canlı retrieval kapısı (${KB_VECTOR_DSN}) =="
  echo "NOT: canlı doğrulama RAG hot-path'inde (SAD §10.2) koşulur:"
  echo "     soru→embed (SPI)→vector search ANN top-k→[6.1.4 ACL pre-filtre metadata-query'ye push]→rerank"
  echo "     (opsiyonel SPI)→trim (6.2.2)→LLM context (kaynak atıflı 6.2.3). Referans probe'taki AYNI SPI'ye"
  echo "     gerçek semantik embedding + cross-encoder reranker takılır (ADR-001/002); aday store'da"
  echo "     pgvector/OpenSearch ANN (HNSW) + namespace/ACL metadata filtre + 1.1.7 RLS ile çekilir."
  echo "     Kapılar (recall@k ≥0.95 / retrieval P95 ≤200ms SAD §20) 0.2.5 vector-db-eval + canlı PoC'ta"
  echo "     ölçülür. Kapı kodu DEĞİŞMEZ; bu betik yalnız DSN varlığını bildirir (credential \${KB_VECTOR_DSN};"
  echo "     repoya YAZILMAZ)."
else
  echo "== canlı retrieval kapısı: SKIP (KB_VECTOR_DSN tanımsız) =="
fi
echo "OK"
