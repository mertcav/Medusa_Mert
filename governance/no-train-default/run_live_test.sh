#!/usr/bin/env bash
# run_live_test.sh — WBS 5.8 "Tenant verisi eğitime kapalı" varsayılanı (no-train) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir DPA/alt-işleyen
# kayıt deposu uç noktası (${NO_TRAIN_DPA_REGISTRY_URL}) verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham PROMPT/transkript/audio ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/no_train_probe.py" validate
"$PY" "$HERE/no_train_probe.py" selftest
"$PY" "$HERE/tests/no_train_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/no_train_probe.py" simulate "$s"
done

if [[ -n "${NO_TRAIN_DPA_REGISTRY_URL:-}" ]]; then
  echo "== canlı no-train/alt-işleyen kapısı (${NO_TRAIN_DPA_REGISTRY_URL}) =="
  echo "NOT: canlı doğrulama gerçek control-plane'de koşulur: sağlayıcı (LLM/STT/TTS) alt-işleyen olarak"
  echo "     no-train YETENEĞİ + no-log retention (NONE/EPHEMERAL) + bölgesel pin + imzalı DPA ile kaydedilir."
  echo "     Adapter (4.2.4 LlmAdapter + STT/TTS) complete()/transcribe()/synthesize() ÖNCESİ"
  echo "     resolveTrainingDisposition()'ı çağırır; effective_no_train değeri AdapterConfig.noTrain/"
  echo "     dataRetention + LlmRequest.noTrain alanlarına yazılır ve sağlayıcı çağrısında UYGULANIR (FR-LLM-012/P6)."
  echo "     VARSAYILAN no-train (opt-in'siz); governed eğitim opt-in maker-checker + DPA + süre + kapsam ister,"
  echo "     regüle/yasaklı compliance profile'da EZİLİR (most-restrictive-wins). Tüm karar + yaşam döngüsü"
  echo "     audit_log'a (FR-IAM-006/FR-REC-009); kayıtlar home-region (NFR 10.7), ham içerik/PII saklanmaz (T12)."
  echo "     Kapı kodu DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı no-train/alt-işleyen kapısı: SKIP (NO_TRAIN_DPA_REGISTRY_URL tanımsız) =="
fi
echo "OK"
