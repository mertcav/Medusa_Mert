#!/usr/bin/env bash
# run_live_test.sh — WBS 6.2.2 Token trimming (bağlam maliyeti sınırı) (SAD §10.2 TRIM aşaması) kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; 6.2.1 RetrievalEngine'den gerçek RankedResult
# TÜRETİR — retrieval/embed/rerank YENİDEN YAPILMAZ; deterministik). Tokenizer bir SPI arkasında
# (vendor-neutral); referans yaklaşık char//divisor (6.1.3 token_estimate ile AYNI). Trim mantığı tokenizer'dan
# bağımsız. Canlı LLM Router context montajı yalnız ${KB_LLM_ENDPOINT} ORTAM DEĞİŞKENİ verilirse not düşülür.
# Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/context_trim_probe.py" validate
"$PY" "$HERE/context_trim_probe.py" selftest
"$PY" "$HERE/tests/context_trim_behavior_test.py"

echo "== sample trim kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/context_trim_probe.py" trim "$s"
done

if [[ -n "${KB_LLM_ENDPOINT:-}" ]]; then
  echo "== canlı trim kapısı (${KB_LLM_ENDPOINT}) =="
  echo "NOT: canlı doğrulama RAG hot-path'inde (SAD §10.2/§9) koşulur:"
  echo "     6.2.1 vector search→rerank→[TRIM bu motor: token bütçesi paketleme]→LLM Router context montajı."
  echo "     Referans yaklaşık tokenizer (char//divisor) yerine AYNI Tokenizer SPI'ye gerçek model-özgü"
  echo "     tokenizer (tiktoken/HF) takılır (ADR-001/002); reserved segment token sayıları 3.2.3 prompt +"
  echo "     3.2.2 özet + 3.2.1 history'den GERÇEK değerlerle gelir. Bütçe (context_token_budget) model"
  echo "     penceresi + ADR-008 tier'a göre ayarlanır. INVARIANT (SR-KB-011): toplam bağlam token'ı tavanı"
  echo "     aşmaz — kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (\${KB_LLM_ENDPOINT};"
  echo "     repoya YAZILMAZ)."
else
  echo "== canlı trim kapısı: SKIP (KB_LLM_ENDPOINT tanımsız) =="
fi
echo "OK"
