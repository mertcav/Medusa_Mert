#!/usr/bin/env bash
# run_live_test.sh — WBS 4.2.6 Ses klonlama izin + kullanım kaydı (onaylı sesler) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir consent/evidence
# deposu uç noktası (${VOICE_CONSENT_EVIDENCE_STORE_URL}) verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham SES/voiceprint/biyometrik ve PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/voice_consent_probe.py" validate
"$PY" "$HERE/voice_consent_probe.py" selftest
"$PY" "$HERE/tests/voice_consent_behavior_test.py"

echo "== sample simulate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/voice_consent_probe.py" simulate "$s"
done

if [[ -n "${VOICE_CONSENT_EVIDENCE_STORE_URL:-}" ]]; then
  echo "== canlı izin/kullanım kaydı kapısı (${VOICE_CONSENT_EVIDENCE_STORE_URL}) =="
  echo "NOT: canlı doğrulama gerçek control-plane'de koşulur: ses kaydı (custom/cloned) → ses sahibinin"
  echo "     AÇIK izni (consent) + opak evidence_ref (kayıt/imza deposu) → maker-checker onay → status=approved."
  echo "     TtsAdapter (4.2.3) synthesize() ÖNCESİ VoiceProfile.clonedVoiceConsentRef'i bu deftere çözer;"
  echo "     karar ALLOW değilse ses ÜRETİLMEZ (ADR-001). İzin verilen her klon kullanımı bir usage record"
  echo "     (FR-TTS-007 kullanım kaydı, no-loss) + tüm yaşam döngüsü/karar audit_log'a (FR-IAM-006/FR-REC-009)."
  echo "     Consent/usage kaydı home-region (NFR 10.7); ham ses/voiceprint/biyometrik DEĞER saklanmaz (V11);"
  echo "     ses biyometrisi (kimlik) ayrı modül (FR-AUTH-006/007). DPIA-T-08 ses klonlama tetiği regüle"
  echo "     tenant'ta tenant onayı zorunlu. metrikler observability 0.4.7'ye yayılır. Kapı kodu DEĞİŞMEZ;"
  echo "     bu betik yalnız endpoint varlığını bildirir (credential \${ENV}; repoya yazılmaz)."
else
  echo "== canlı izin/kullanım kaydı kapısı: SKIP (VOICE_CONSENT_EVIDENCE_STORE_URL tanımsız) =="
fi
echo "OK"
