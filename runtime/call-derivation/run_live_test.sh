#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.2 Intent/outcome/disposition/completion çıkarımı kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir analytics-plane
# çıkarım consumer'ı / OLAP uç noktası (${DERIVATION_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/derivation_probe.py" validate
"$PY" "$HERE/derivation_probe.py" selftest
"$PY" "$HERE/tests/derivation_behavior_test.py"

echo "== sample derive kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/derivation_probe.py" derive "$s"
done

if [[ -n "${DERIVATION_URL:-}" ]]; then
  echo "== canlı çıkarım kapısı (${DERIVATION_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1; ADR-007) koşulur:"
  echo "     voice.call.lifecycle.v1 (FR-ANA-002) + voice.transcript.redacted.v1 (redacted) consumer'ı"
  echo "     çağrı bittikten sonra PII-REDAKSİYONLU sinyallerle çalışır, HER UYGUN çağrı için DÖRT alanı"
  echo "     (intent/outcome/disposition/completion_status) kapalı-sözlükten deterministik türetir ve"
  echo "     sonucu call (DB.md §5.5) + OLAP fct_call (intent/disposition/completion_status) ile doldurur."
  echo "     Doğrulanır: üretilen == uygun (coverage_gap=0, %100 kapsam, DÖRT alan dolu), her değer kapalı-"
  echo "     sözlükte (düşük-kardinalite enum), cross-field tutarlı (C1–C5), (tenant_id,call_id,schema_version)"
  echo "     idempotent (replay çift satır üretmez), her satır tenant_id + home-region, ham transkript/ses/PII"
  echo "     DEĞERİ çıktıda yok (FR-REC-004). Çıkarım başarısızlığı CANLI çağrıyı etkilemez (non-blocking)."
  echo "     Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı çıkarım kapısı: SKIP (DERIVATION_URL tanımsız) =="
fi
echo "OK"
