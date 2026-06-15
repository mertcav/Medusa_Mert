#!/usr/bin/env bash
# run_live_test.sh — WBS 7.2.2 SOAP/GraphQL/webhook connector'lar (SAD §11.2 / FR-TOOL-001) kapısı
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik). Upstream
# SOAP/GraphQL/webhook transport bir SPI arkasında (vendor-neutral, ADR-001/002); referans probe wire'ı
# deterministik wire_script ile MODELLER (gerçek ağ YOK). status→fault eşleme + protokol-farkında fault tespiti
# (C13) + request build transport'tan bağımsız. Canlı endpoint (gerçek protokol client + keep-alive pool
# FR-RES-006) yalnız ${SGW_CONNECTOR_ENDPOINT} ORTAM DEĞİŞKENİ verilirse not düşülür. Sır/credential/imza-anahtarı
# ve gerçek PII repoya yazılmaz (auth.ref/signing.ref yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/protocol_connector_probe.py" validate
"$PY" "$HERE/protocol_connector_probe.py" selftest
"$PY" "$HERE/tests/protocol_connector_behavior_test.py"

echo "== sample SOAP/GraphQL/webhook çağrı kapısı =="
# Not: expect_degraded fixture'ları KASITLI 🔴 döner (C6 no-log gate'inin gerçek kapı olduğunu kanıtlar);
# bunların elemesi BEKLENEN'dir, statik kapı (validate) ayrıca zorlar. set -e'yi tetiklememeleri için
# çıkış kodları tolere edilir; diğer tüm sample'lar 🟢 olmalıdır.
for s in "$HERE"/samples/*.json; do
  if grep -q '"expect_degraded": *true' "$s"; then
    "$PY" "$HERE/protocol_connector_probe.py" call "$s" || echo "  (yukarıdaki 🔴 BEKLENEN — degraded anti-örnek)"
  else
    "$PY" "$HERE/protocol_connector_probe.py" call "$s"
  fi
done

if [[ -n "${SGW_CONNECTOR_ENDPOINT:-}" ]]; then
  echo "== canlı SOAP/GraphQL/webhook kapısı (${SGW_CONNECTOR_ENDPOINT}) =="
  echo "NOT: canlı doğrulama Tool Yürütme Hattının (SAD §11.1) adım [5]'i ALTINDA koşulur:"
  echo "     deterministik wire_script yerine AYNI transport SPI'sine (upstream_call(req)→AttemptOutcome)"
  echo "     gerçek SOAP/GraphQL/webhook client + keep-alive connection pool (FR-RES-006) takılır (ADR-001/002)."
  echo "     Bu connector'lar 7.1.4 (timeout/retry/circuit breaker) tarafından SARILIR; auth.ref/signing.ref"
  echo "     ortam değişkeninden çözülür, değer asla loglanmaz/audit'lenmez (C5/C6). INVARIANT (SR-TOOL-001):"
  echo "     'Her connector tipi başarılı çağrı yapar' + protokol-farkında fault tespiti (C13) — kapı kodu"
  echo "     DEĞİŞMEZ; bu betik yalnız endpoint varlığını bildirir (\${SGW_CONNECTOR_ENDPOINT}; repoya YAZILMAZ)."
else
  echo "== canlı SOAP/GraphQL/webhook kapısı: SKIP (SGW_CONNECTOR_ENDPOINT tanımsız) =="
fi
echo "OK"
