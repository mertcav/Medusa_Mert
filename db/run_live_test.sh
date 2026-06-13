#!/usr/bin/env bash
# =============================================================================
# Canlı RLS testi koşucusu — WBS 1.1.1 / 12.2.3
# Çalışan bir PostgreSQL'e migration'ları + seed'i + RLS testini uygular.
# Sunucu yoksa SKIP ile çıkar (CI'da gerçek sunucuyla koşar — DB.md §10).
#
# Bağlantı: standart PG* ortam değişkenleri (PGHOST/PGPORT/PGUSER/PGDATABASE).
# Credential repoya yazılmaz; yalnız ortamdan okunur (.gitignore).
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v psql >/dev/null 2>&1; then
    echo "SKIP: psql bulunamadı."; exit 0
fi
if ! pg_isready >/dev/null 2>&1; then
    echo "SKIP: çalışan PostgreSQL yok (pg_isready başarısız). Statik kapı: schema_probe.py validate."
    exit 0
fi

PSQL=(psql -v ON_ERROR_STOP=1 -q)

echo "==> Migration'lar uygulanıyor (up)"
"${PSQL[@]}" -f "$HERE/migrations/0001_extensions_helpers.up.sql"
"${PSQL[@]}" -f "$HERE/migrations/0002_tenant_org_iam.up.sql"
"${PSQL[@]}" -f "$HERE/migrations/0003_rls_tenant_org_iam.up.sql"
"${PSQL[@]}" -f "$HERE/migrations/0004_agent_config.up.sql"
"${PSQL[@]}" -f "$HERE/migrations/0005_rls_agent_config.up.sql"
"${PSQL[@]}" -f "$HERE/migrations/0006_call_interaction.up.sql"
"${PSQL[@]}" -f "$HERE/migrations/0007_rls_call_interaction.up.sql"

echo "==> Seed (roller)"
"${PSQL[@]}" -f "$HERE/seeds/roles.sql"

echo "==> RLS davranış testi (Tenant/Org/User)"
"${PSQL[@]}" -f "$HERE/tests/rls_isolation.sql"

echo "==> RLS + WORM davranış testi (Agent/Config)"
"${PSQL[@]}" -f "$HERE/tests/agent_config_isolation.sql"

echo "==> RLS + WORM + partition davranış testi (Çağrı/Etkileşim)"
"${PSQL[@]}" -f "$HERE/tests/call_interaction_isolation.sql"

echo "==> Temizlik (down)"
"${PSQL[@]}" -f "$HERE/migrations/0007_rls_call_interaction.down.sql"
"${PSQL[@]}" -f "$HERE/migrations/0006_call_interaction.down.sql"
"${PSQL[@]}" -f "$HERE/migrations/0005_rls_agent_config.down.sql"
"${PSQL[@]}" -f "$HERE/migrations/0004_agent_config.down.sql"
"${PSQL[@]}" -f "$HERE/migrations/0003_rls_tenant_org_iam.down.sql"
"${PSQL[@]}" -f "$HERE/migrations/0002_tenant_org_iam.down.sql"

echo "PASS: canlı RLS testi geçti."
