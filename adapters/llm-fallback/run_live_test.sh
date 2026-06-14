#!/usr/bin/env bash
# run_live_test.sh — WBS 4.3.3 LLM fallback (fallback model / deterministic flow) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız İKİ gerçek LLM sağlayıcısı
# uç noktası (${LLM_PRIMARY_URL} + ${LLM_SECONDARY_URL}) + API anahtarı ORTAM DEĞİŞKENİ verilirse
# not düşülür; yoksa SKIP. Sır/credential, ham PROMPT ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/llm_fallback_probe.py" validate
"$PY" "$HERE/llm_fallback_probe.py" selftest
"$PY" "$HERE/tests/llm_fallback_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/llm_fallback_probe.py" simulate "$s"
done

if [[ -n "${LLM_PRIMARY_URL:-}" && -n "${LLM_SECONDARY_URL:-}" ]]; then
  echo "== canlı LLM fallback kapısı (${LLM_PRIMARY_URL} → ${LLM_SECONDARY_URL}) =="
  echo "NOT: canlı doğrulama gerçek Conversation Orchestrator runtime'ında (Go/Rust async, ADR-003/SAD §6.3/§8.1)"
  echo "     iki somut LlmAdapter + 4.1.2 circuit breaker ile koşulur: THINK durumunda final transcript+context"
  echo "     birincil LlmAdapter.complete()'e gider; birincil hata/timeout (circuit-open) ENJEKTE edilir → switcher"
  echo "     fallback modele geçer + tur isteğini (messages/tools/system prompt) yeniden sunar (context resubmit);"
  echo "     ilk-token öncesi temiz (turn_lost=0), ilk-token/yan-etkili-tool sonrası MID-STREAM güvenli degrade"
  echo "     (double_speak=0/double_tool_exec=0, FR-TOOL-009); her iki model düşünce deterministik akışa (kural-"
  echo "     tabanlı/insan aktarımı — SAD §8.3/§9.1, BRD §19 (4)) geçiş + çağrı DÜŞMEZ; anahtarlama gecikmesi"
  echo "     (switch overhead, NFR 10.1/SAD §20 ≤500ms); UsageRecord segment metering + model/versiyon kaydı"
  echo "     (FR-BIL-002/FR-LLM-011) + ortak ErrorTaxonomy (API §11.6); sentetik prompt (FR-TST-008 — gerçek"
  echo "     müşteri verisi yok); metrikler observability 0.4.7'ye yayılır; ≥2 sağlayıcı (BRD §19 (1)). Sağlayıcı"
  echo "     seçimi 0.2.4/0.2.6/0.3.x (vendor-neutral, ADR-002). Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint"
  echo "     varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı LLM fallback kapısı: SKIP (LLM_PRIMARY_URL/LLM_SECONDARY_URL tanımsız) =="
fi
echo "OK"
