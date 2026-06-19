#!/usr/bin/env bash
# run_live_test.sh — WBS 14.2.7 Agent sürümleri performans karşılaştırma kapısı
#
# Statik kapı her zaman koşar (credential-free). Canlı doğrulama yalnız gerçek bir analytics-plane
# karşılaştırma consumer'ı / OLAP uç noktası (${VERSION_COMPARE_URL}) ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential, ham ses payload'ı/transkript METNİ ve PII DEĞERİ repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/version_compare_probe.py" validate
"$PY" "$HERE/version_compare_probe.py" selftest
"$PY" "$HERE/tests/version_compare_behavior_test.py"

echo "== sample compare kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/version_compare_probe.py" compare "$s"
done

if [[ -n "${VERSION_COMPARE_URL:-}" ]]; then
  echo "== canlı sürüm karşılaştırma kapısı (${VERSION_COMPARE_URL}) =="
  echo "NOT: canlı doğrulama gerçek Analytics/Ops Plane'de (SAD §4.2/§12.1; ADR-007) koşulur:"
  echo "     mv_agent_version_perf{calls, containment_rate, transfer_rate, critical_rate} (FR-ANA-010) +"
  echo "     fct_qa_evaluation.auto_score (FR-ANA-001) consumer'ı sürüm-başı agregatı tüketir ve AYNI agent'ın"
  echo "     baseline ↔ candidate sürümlerini metrik-metrik KARŞILAŞTIRIR (yeniden hesaplamaz)."
  echo "     Doğrulanır: kollar AYNI agent_id+tenant+period+metrik (apples-to-apples; cross-agent/period/tenant/metrik"
  echo "     YASAK), delta=candidate−baseline + yön-duyarlı iyileşme (higher/lower_is_better), improved/regressed YALNIZ"
  echo "     |z|≥z_critical(confidence) VE her iki kol ≥min_sample_n (gürültüden kazanan YOK — iki-oran z-testi / ortalama"
  echo "     normal yaklaşım), kol örneği<min_sample_n bastırılır (k-anon), (tenant,agent,baseline,candidate,period,schema)"
  echo "     idempotent, her karşılaştırma tek tenant + home-region, yayımlanan karşılaştırma per-call kimlik/PII taşımaz"
  echo "     (FR-REC-004). Karşılaştırma başarısızlığı CANLI çağrıyı etkilemez (non-blocking, FR-RES-011). Bu betik yalnız"
  echo "     endpoint varlığını bildirir."
else
  echo "== canlı sürüm karşılaştırma kapısı: SKIP (VERSION_COMPARE_URL tanımsız) =="
fi
echo "OK"
