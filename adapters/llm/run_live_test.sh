#!/usr/bin/env bash
# run_live_test.sh — WBS 4.2.4 LLM adapter #1 + #2 (streaming token / tool call) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir LLM sağlayıcısı
# uç noktası (${LLM_PROVIDER_URL}) + API anahtarı ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham PROMPT/mesaj ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/llm_adapter_probe.py" validate
"$PY" "$HERE/llm_adapter_probe.py" selftest
"$PY" "$HERE/tests/llm_adapter_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/llm_adapter_probe.py" simulate "$s"
done

if [[ -n "${LLM_PROVIDER_URL:-}" ]]; then
  echo "== canlı LlmAdapter kapısı (${LLM_PROVIDER_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3/§8.1)"
  echo "     iki somut LlmAdapter ile koşulur: THINK durumunda STT final → complete(req) → AsyncStream<LlmChunk>;"
  echo "     ilk token gecikmesi (first-token, SAD §20 LLM kalemi genel P95 ≤400ms; küçük-tier ≤200ms),"
  echo "     token-arası süreklilik (stall=0 — FR-LLM-004; aksi halde TTS ölü hava FR-RES-009),"
  echo "     kritik işlemde schema-doğrulamalı tool-call (ToolCallChunk — FR-LLM-008), model tiering"
  echo "     (küçük/büyük — FR-LLM-013), no-train + no-log (noTrain + NONE/EPHEMERAL — FR-LLM-012/FR-KB-010),"
  echo "     bölgesel endpoint/residency (NFR 10.7), system prompt değişmezliği (FR-LLM-006),"
  echo "     UsageRecord metering + model/versiyon kaydı (FR-BIL-002/FR-LLM-011) + ortak ErrorTaxonomy"
  echo "     (API §11.6) ölçülür; sentetik prompt (FR-TST-008 — gerçek müşteri verisi yok) kullanılır;"
  echo "     metrikler observability 0.4.7'ye yayılır; ≥2 sağlayıcı + deterministic-flow fallback"
  echo "     (FR-LLM-010 → 4.3.3). Sağlayıcı seçimi 0.2.6/0.3.x (vendor-neutral, ADR-002). Kapı kodu"
  echo "     DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı LlmAdapter kapısı: SKIP (LLM_PROVIDER_URL tanımsız) =="
fi
echo "OK"
