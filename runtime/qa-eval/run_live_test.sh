#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.1 Otomatik kalite değerlendirme (tüm çağrılar) kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir analytics-plane
# QA/Eval consumer / OLAP uç noktası (${QA_EVAL_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/qa_eval_probe.py" validate
"$PY" "$HERE/qa_eval_probe.py" selftest
"$PY" "$HERE/tests/qa_eval_behavior_test.py"

echo "== sample evaluate kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/qa_eval_probe.py" evaluate "$s"
done

if [[ -n "${QA_EVAL_URL:-}" ]]; then
  echo "== canlı QA/Eval kapısı (${QA_EVAL_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1; ADR-007) koşulur:"
  echo "     qa.evaluation.v1 consumer (eventstream) çağrı bittikten sonra PII-REDAKSİYONLU içerikle"
  echo "     çalışır, TÜM uygun çağrılara (FR-ANA-001; SR-ANA-001 %100) deterministik rubric uygular ve"
  echo "     sonucu call_evaluation (DB.md §5.6, eval_type='automatic') + OLAP fct_qa_evaluation'a yazar."
  echo "     Doğrulanır: üretilen == uygun (coverage_gap=0, %100 kapsam), skorlar [0,1] + composite=ağırlıklı"
  echo "     toplam, (tenant_id,call_id,schema_version) idempotent (replay çift skor üretmez), her satır"
  echo "     tenant_id taşır + home-region (residency), ham transkript/ses/PII DEĞERİ skorda yok (FR-REC-004)."
  echo "     QA başarısızlığı CANLI çağrıyı etkilemez (non-blocking). Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı QA/Eval kapısı: SKIP (QA_EVAL_URL tanımsız) =="
fi
echo "OK"
