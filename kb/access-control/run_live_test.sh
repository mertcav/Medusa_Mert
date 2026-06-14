#!/usr/bin/env bash
# run_live_test.sh — WBS 6.1.4 Doküman bazında erişim yetkisi (FR-KB-005) kapısı
#
# Statik + sample kapısı her zaman koşar (credential-free; IndexedChunk'ı 6.1.3 index pipeline'dan TÜRETİR —
# o da 6.1.1'i import eder; deterministik). Karar policy + doküman metadata'sına dayanır (vendor-neutral).
# Canlı retrieval store'u yalnız ${KB_VECTOR_DSN} ORTAM DEĞİŞKENİ verilirse not düşülür; yoksa SKIP.
# Sır/credential ve gerçek PII repoya yazılmaz (yalnız ${ENV}).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "== statik kapı =="
"$PY" "$HERE/access_control_probe.py" validate
"$PY" "$HERE/access_control_probe.py" selftest
"$PY" "$HERE/tests/access_control_behavior_test.py"

echo "== sample enforce kapısı =="
for s in "$HERE"/samples/*.json; do
  "$PY" "$HERE/access_control_probe.py" enforce "$s"
done

if [[ -n "${KB_VECTOR_DSN:-}" ]]; then
  echo "== canlı erişim kapısı (${KB_VECTOR_DSN}) =="
  echo "NOT: canlı doğrulama RETRIEVAL hot-path'inde (SAD §10.2) koşulur:"
  echo "     soru→embed→vector search → [6.1.4 ACCESS GATE] → rerank/trim → LLM context. İki nokta:"
  echo "     (1) STORE PRE-FİLTRE — namespace+classification+ACL token yüklemi vector search query'sine"
  echo "     (pgvector/OpenSearch metadata filtre + 1.1.7 RLS) push edilir; yetkisiz aday HİÇ çekilmez."
  echo "     (2) AUTHORITATIVE POST-FİLTRE — dönen her chunk yetki kararından yeniden geçer (store"
  echo "     filtresine güvenilmez). Karar metadata-only (embedding/ağ yok) → gecikme bütçesine (SAD §20)"
  echo "     anlamlı ek yüklemez. Metrikler (kb_access_decisions_total{decision,reason}/..., PII label YASAK)"
  echo "     observability 0.4.7'ye yayılır. Kapı kodu DEĞİŞMEZ; bu betik yalnız DSN varlığını bildirir"
  echo "     (credential \${KB_VECTOR_DSN}; repoya YAZILMAZ)."
else
  echo "== canlı erişim kapısı: SKIP (KB_VECTOR_DSN tanımsız) =="
fi
echo "OK"
