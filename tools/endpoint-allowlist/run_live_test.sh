#!/usr/bin/env bash
# run_live_test.sh — WBS 7.2.3 Endpoint allowlist (SAD §11.2 / FR-TOOL-012 / ADR-014) kapısı
#
# Statik + selftest + behavior + sample kapısı her zaman koşar (credential-free, deterministik, saf karar).
# Egress karar mantığı vendor/transport-nötr (ADR-001/002); referans probe DNS çözümlemeyi deterministik
# resolved_ips ile MODELLER (gerçek DNS/ağ YOK). Ağ-katmanı egress proxy enforcement'ı (17.1.4) AYNI
# allowlist mantığını uygular — yalnız ${EGRESS_PROXY_ENDPOINT} ORTAM DEĞİŞKENİ verilirse not düşülür.
# Sır/credential ve gerçek PII repoya yazılmaz.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/endpoint_allowlist_probe.py" validate
"$PY" "$HERE/endpoint_allowlist_probe.py" selftest
"$PY" "$HERE/tests/endpoint_allowlist_behavior_test.py"

echo "== sample egress karar kapısı =="
# Not: expect_degraded fixture'ları KASITLI 🔴 döner (SSRF-floor'un gerçek kapı olduğunu kanıtlar);
# expect_invalid_policy fixture'ları policy kurulumda reddedilir. Bunların elemesi BEKLENEN'dir; statik
# kapı (validate) ayrıca zorlar. set -e'yi tetiklememeleri için çıkış kodları tolere edilir.
for s in "$HERE"/samples/*.json; do
  if grep -q '"expect_degraded": *true' "$s" || grep -q '"expect_invalid_policy": *true' "$s"; then
    "$PY" "$HERE/endpoint_allowlist_probe.py" decide "$s" || echo "  (yukarıdaki 🔴/red BEKLENEN — anti-örnek)"
  else
    "$PY" "$HERE/endpoint_allowlist_probe.py" decide "$s"
  fi
done

if [[ -n "${EGRESS_PROXY_ENDPOINT:-}" ]]; then
  echo "== canlı egress kapısı (${EGRESS_PROXY_ENDPOINT}) =="
  echo "NOT: canlı doğrulama Tool Yürütme Hattının (SAD §11.1) egress gate'i olarak koşar:"
  echo "     deterministik resolved_ips yerine GERÇEK DNS çözümleme + ağ-katmanı egress proxy (ADR-014)"
  echo "     AYNI allowlist karar mantığını her bağlantıda uygular (defense-in-depth). PERMIT → 7.1.4"
  echo "     (timeout/retry/breaker) connector'ı sarar; DENY → ENDPOINT_NOT_ALLOWED terminal (retry yok)."
  echo "     INVARIANT (SR-TOOL-012): 'Allowlist dışı endpoint çağrısı reddedilir' — kapı kodu DEĞİŞMEZ;"
  echo "     bu betik yalnız endpoint varlığını bildirir (\${EGRESS_PROXY_ENDPOINT}; repoya YAZILMAZ)."
else
  echo "== canlı egress kapısı: SKIP (EGRESS_PROXY_ENDPOINT tanımsız) =="
fi
echo "== TAMAM =="
