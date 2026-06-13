# db/ — PostgreSQL şema migration'ları (Faz 1 implementasyon)

Bu dizin, `docs/DB.md` (WBS 0.1.3) tasarımının **fiziksel implementasyonudur**.
Dilimler:
- **WBS 1.1.1 — Tenant, Organisation Unit, User, Role (+ RLS)**
  (`F1` · Must · →BRD §16 (1–4), SAD §13.1, FR-TEN-002, FR-IAM-011, ADR-006).
- **WBS 1.1.2 — Agent, Agent Version, Prompt, Conversation Flow, Voice/Model/STT Profile (+ RLS)**
  (`F1` · Must · →BRD §16 (5–11), SAD §13.1, DB.md §5.2; agent_version **WORM** §6.5/FR-AGT-006).

> **Source of truth `docs/DB.md`'dir.** Çelişki olursa DB.md (ve onun üstünde BRD/SAD) esastır.
> Vendor-neutral: PostgreSQL "ilişkisel + RLS" yeteneği için referans (SAD §12.1, ADR-006).
> **Sır/credential repoya yazılmaz** (bağlantı yalnız PG* ortam değişkenleriyle).

## Yapı

```
db/
  migrations/
    0001_extensions_helpers.{up,down}.sql   # citext/pgcrypto, gen_uuid_v7(), trigger fn'ler, app_rw rolü
    0002_tenant_org_iam.{up,down}.sql       # tenant, organisation_unit, app_user, role,
                                            #   permission_key, role_permission, user_role_assignment
    0003_rls_tenant_org_iam.{up,down}.sql   # RLS enable/force + politikalar + grant'ler
    0004_agent_config.{up,down}.sql         # agent, agent_version (WORM), prompt, conversation_flow,
                                            #   voice/model/stt_profile; dairesel FK (ALTER)
    0005_rls_agent_config.{up,down}.sql     # 7 tablo tenant_isolation RLS + grant; agent_version WORM grant
  seeds/
    roles.sql                               # sabit global rol kümesi (FR-IAM-011, ADR-012)
  tests/
    rls_isolation.sql                       # canlı RLS davranış testi — Tenant/Org/User (CI)
    agent_config_isolation.sql              # canlı RLS + WORM davranış testi — Agent/Config (CI)
  run_live_test.sh                          # sunucu varsa migration+seed+test koşar; yoksa SKIP
  schema_probe.py                           # stdlib-only statik kapı (validate/selftest/schema)
```

Migration'lar **ileri-yönlü ve idempotent** (DB.md §10); her `up` için bir `down` vardır.
RLS, oluşturulduğu tabloyla **aynı seride** gelir (DB.md §10: "yeni iş verisi tablosu RLS olmadan merge edilemez").

## Oturum sözleşmesi (uygulama ↔ RLS — DB.md §6.1)

Uygulama, RLS'i **bypass etmeyen** `app_rw` rolüyle bağlanır ve her transaction başında:

```sql
SET LOCAL app.tenant_id = '<uuid>';   -- tenant realm (L1/L2)
-- veya
SET LOCAL app.platform  = 'on';       -- platform realm (L0)
```

`current_setting('app.tenant_id', true)` iki-argümanlı kullanılır: GUC yoksa `NULL` →
karşılaştırma `false` → **hiçbir satır görünmez** (fail-closed). Scope'u unutmak veriyi açmaz, kapatır.

## Kapılar

```bash
# Statik kapı (sunucu gerekmez) — tasarım invariant doğrulaması
python3 db/schema_probe.py validate     # 140/140 kontrol (1.1.1 + 1.1.2), çıkış 0
python3 db/schema_probe.py selftest     # 20/20 predikat testi, çıkış 0
python3 db/schema_probe.py schema       # beklenen nesneler/sözleşme (JSON)

# Canlı kapı (CI / çalışan PostgreSQL) — gerçek RLS davranışı
bash db/run_live_test.sh                 # PG* ortamı ile; sunucu yoksa SKIP
```

`schema_probe.py` doğrular: UUIDv7 PK + sürüm/variant bitleri; her tenant-scoped tabloda
`tenant_id` + RLS (ENABLE+FORCE+POLICY); fail-closed `current_setting(...,true)`; cross-tenant
write koruması (WITH CHECK); global rol tablolarının RLS-dışı + `app_rw`'ye salt-okunur olması;
FK indeksleri; down migration'ların nesneleri düşürmesi; seed'in 12 sabit rolü; DB.md izlenebilirlik.
**1.1.2 ek:** 7 agent-config tablosu + UUIDv7 PK + tenant_id NOT NULL + RLS/WITH CHECK; `agent_version`
WORM (immutable trigger + `app_rw`'ye yalnız INSERT+SELECT, UPDATE/DELETE grant yok); dairesel
FK'nin (agent.active_version_id → agent_version) inline değil ALTER ile eklenmesi; conversation_flow
GIN indeksi.

`run_live_test.sh` (CI'da gerçek sunucuyla) doğrular: fail-closed (scope yokken 0 satır), tenant
izolasyonu, tenant Root self-policy, cross-tenant insert reddi, platform realm tam görünürlük,
global rol tablosuna `app_rw` yazım reddi, UUIDv7 bit kontrolü. **1.1.2 ek
(`agent_config_isolation.sql`):** agent/config tenant izolasyonu, cross-tenant write reddi, dairesel
FK çözümü, `agent_version` UPDATE/DELETE reddi (WORM), platform realm'in iş config'ini görmemesi
(altın kural). Not: fail-closed için GUC'lar **NULL'a** resetlenir (`''::uuid` hata fırlatacağından
boş-string kullanılmaz).

## Sonraki adımlar

- WBS 1.1.3/1.1.4 — kalan BRD §16 varlıkları (Call…, Campaign…) aynı desende.
- WBS 12.1.2 — permission-key kataloğu + role→permission bundle eşlemesi (seed genişler).
- WBS 0.4.4 / 12.2.3 — `run_live_test.sh` CI hattına bağlanır (tenant izolasyon test kapısı).
