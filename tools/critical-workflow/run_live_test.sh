#!/usr/bin/env bash
# run_live_test.sh — WBS 7.3.1 Kritik işlem workflow durum makinesi kapısı (BRD §13)
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik).
# Bu modül DETERMINISTIK bir DURUM MAKİNESİDİR (saf karar/orkestrasyon) — dış transport YOK; auth/teyit/
# onay/execute sinyalleri fixture OLAY'larıyla modellenir. Canlıda AYNI FSM gerçek auth (8.x), teyit/
# ek-doğrulama (7.3.2), tool dispatch (7.2.x) ve audit store (7.1.6/12.1.8) sinyalleriyle beslenir;
# kapı mantığı (BRD §13 6 adım) DEĞİŞMEZ. Sır/credential ve gerçek PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/critical_workflow_probe.py" validate
"$PY" "$HERE/critical_workflow_probe.py" selftest
"$PY" "$HERE/tests/critical_workflow_behavior_test.py"

echo "== sample FSM kapısı =="
# Not: degraded fixture KASITLI sızıntı içerir (K11/K10 tarayıcısının gerçek kapı olduğunu kanıtlar);
# expect_gate_fail=true olduğundan probe exit 0 döner (eleme BEKLENEN ve tüketildi).
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/critical_workflow_probe.py" run "$s"
done

echo "== canlı entegrasyon notu =="
echo "NOT: canlıda kritik-işlem FSM'i AYNI 6-adım kapı sırasını (auth→kural→özet→teyit→onay→audit)"
echo "     gerçek sinyallerle yürütür: auth seviyesi 8.x'ten (FR-AUTH-001..005), teyit/ek-doğrulama"
echo "     7.3.2'den (FR-TOOL-006/007), EXECUTE 7.2.x tool zincirinden (committed/failed), audit kaydı"
echo "     7.1.6/12.1.8 store'a (WORM, FR-IAM-006). INVARIANT (BRD §13): her gerekli kapı geçilmeden"
echo "     EXECUTE'a ulaşılmaz; teyit alınmadan kritik işlem yürütülmez; gerekli insan onayı (maker-checker)"
echo "     gelmeden yürütülmez; her terminal sonuç değiştirilemez audit'e yazılır. Vendor-neutral (ADR-002)."
echo "== TAMAM =="
