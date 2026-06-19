#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.6 QA manuel skor + açıklama kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir L2 panel / analytics-plane
# uç noktası (${MANUAL_QA_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ, AÇIKLAMA METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/manual_qa_probe.py" validate
"$PY" "$HERE/manual_qa_probe.py" selftest
"$PY" "$HERE/tests/manual_qa_behavior_test.py"

echo "== sample score kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/manual_qa_probe.py" score "$s"
done

if [[ -n "${MANUAL_QA_URL:-}" ]]; then
  echo "== canlı manuel skorlama kapısı (${MANUAL_QA_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1/§14.4; ADR-007) koşulur:"
  echo "     L2 paneli (qa_analyst/operations_manager, permission qa:score — backend kararı) tamamlanmış bir"
  echo "     çağrıya human_score (1–5) + açıklama ekler; call_evaluation (eval_type='manual', evaluator_id,"
  echo "     comment, scores JSONB; DB.md §5.6) + qa.evaluation.v1 (manual) + governance.audit.v1 (audit.event)"
  echo "     → analytics-ingest → fct_qa_evaluation (human_score [0,1], human_comment_present, evaluator_role)."
  echo "     Doğrulanır: yalnız qa:score izni olan ekler (yetkisiz/L0/cross-tenant → AUTH, BİRİNCİL), skor [1,5]"
  echo "     zorunlu + [0,1] normalize, eval_type='manual' otomatik (auto_score) ile COEXIST (overwrite yok),"
  echo "     AÇIKLAMA METNİ tenant düzleminde kalır (OLAP/event/platform yalnız human_comment_present — FR-REC-004,"
  echo "     altın kural), her kabul KAYIPSIZ WORM audit izi (append-only), (tenant,call,evaluator,schema) sürümlü,"
  echo "     tek tenant + home-region (FR-TEN-002/NFR 10.7). Skorlama CANLI çağrıyı etkilemez (non-blocking, FR-RES-011)."
  echo "     Bu betik yalnız endpoint varlığını bildirir."
else
  echo "== canlı manuel skorlama kapısı: SKIP (MANUAL_QA_URL tanımsız) =="
fi
echo "OK"
