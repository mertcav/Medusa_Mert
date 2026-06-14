#!/usr/bin/env bash
# run_live_test.sh — WBS 6.1.3 Parse→chunk→embed→index + versiyonlama kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; NormalizedDocument'ı 6.1.1 ingest connector'dan
# TÜRETİR — parse'ı yeniden yazmaz; deterministik referans embedder + sanal saat). Canlı embedding
# sağlayıcısı yalnız ${KB_EMBED_ENDPOINT} ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP. Sır/credential
# ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/index_pipeline_probe.py" validate
"$PY" "$HERE/index_pipeline_probe.py" selftest
"$PY" "$HERE/tests/index_pipeline_behavior_test.py"

echo "== sample index kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/index_pipeline_probe.py" index "$s"
done

if [[ -n "${KB_EMBED_ENDPOINT:-}" ]]; then
  echo "== canlı embedding kapısı (${KB_EMBED_ENDPOINT}) =="
  echo "NOT: canlı doğrulama Control/Analytics Plane offline indeksleme servisinde (SAD §10.1) koşulur:"
  echo "     6.1.1/6.1.2 NormalizedDocument → yapı-duyarlı chunk → GERÇEK embedding modeli (OpenAI/Cohere/"
  echo "     bge/yerel) AYNI EmbeddingAdapter SPI arkasına takılır (ADR-001/002, referans embedder yerine) →"
  echo "     tenant+kb namespace'e (1.1.7 kb_chunk / pgvector HNSW) index → version_no (FR-KB-003). Embedding"
  echo "     çağrısı yalnız no-train/no-log endpoint'e + home-region'a gider (FR-LLM-012/FR-KB-010/NFR 10.7);"
  echo "     hassas doküman için no-train ZORUNLU (fail-closed). Metrikler (kb_index_total{stage,status}/"
  echo "     kb_chunks_emitted/kb_index_versions_total{action}/...) observability 0.4.7'ye yayılır. Kapı kodu"
  echo "     DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (credential \${KB_EMBED_ENDPOINT}; repoya"
  echo "     YAZILMAZ)."
else
  echo "== canlı embedding kapısı: SKIP (KB_EMBED_ENDPOINT tanımsız) =="
fi
echo "OK"
