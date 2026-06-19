#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.4 Yanlış bilgi/tool hatası/güvenlik ihlali tespiti kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir analytics-plane
# tespit consumer'ı / OLAP uç noktası (${DETECTION_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/detection_probe.py" validate
"$PY" "$HERE/detection_probe.py" selftest
"$PY" "$HERE/tests/detection_behavior_test.py"

echo "== sample detect kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/detection_probe.py" detect "$s"
done

if [[ -n "${DETECTION_URL:-}" ]]; then
  echo "== canlı tespit kapısı (${DETECTION_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1; ADR-007) koşulur:"
  echo "     qa.evaluation.v1 (FR-ANA-004) + ops.tool.execution.v1 (tool status) + governance.audit.v1"
  echo "     (policy/güvenlik) consumer'ı redaksiyonlu sinyalden ÜÇ ikili işaret (flag_misinformation/"
  echo "     flag_tool_error/flag_security) türetir ve OLAP fct_call/fct_qa_evaluation flag_* + "
  echo "     call_evaluation.flags JSONB'ye yazar. Doğrulanır: ENJEKTE edilen her pozitif vaka tespit"
  echo "     edilir (missed_detection=0, yanlış-negatif yok — SR-ANA-004 T, BİRİNCİL), enjekte-temizde sahte"
  echo "     işaret yok (false_positive=0), işaret⟺reason_code tutarlı, reason_code kapalı-sözlük + flag_*"
  echo "     OLAP ile BİREBİR, her uygun çağrı ÜÇ kategoride değerlendirilir (kapsam tam), (tenant,call,schema)"
  echo "     idempotent (replay çift-üretmez), her değerlendirme tek tenant + home-region, çıktı PII/serbest-metin"
  echo "     reason taşımaz (FR-REC-004). Tespit başarısızlığı CANLI çağrıyı etkilemez (non-blocking, FR-RES-011)."
  echo "     Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı tespit kapısı: SKIP (DETECTION_URL tanımsız) =="
fi
echo "OK"
