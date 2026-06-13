# db/ — PostgreSQL şema migration'ları (Faz 1 implementasyon)

Bu dizin, `docs/DB.md` (WBS 0.1.3) tasarımının **fiziksel implementasyonudur**.
Dilimler:
- **WBS 1.1.1 — Tenant, Organisation Unit, User, Role (+ RLS)**
  (`F1` · Must · →BRD §16 (1–4), SAD §13.1, FR-TEN-002, FR-IAM-011, ADR-006).
- **WBS 1.1.2 — Agent, Agent Version, Prompt, Conversation Flow, Voice/Model/STT Profile (+ RLS)**
  (`F1` · Must · →BRD §16 (5–11), SAD §13.1, DB.md §5.2; agent_version **WORM** §6.5/FR-AGT-006).
- **WBS 1.1.3 — Call, Call Leg, Transcript (+ Segment), Recording, Event, Tool Execution (+ RLS)**
  (`F1` · Must · →BRD §16 (19–24), SAD §13.1, DB.md §5.5/§7.2; tümü **partition'lı** (RANGE
  created_at), tool_execution **WORM + idempotent** §6.5/§5.5/FR-TOOL-009).
- **WBS 1.1.4 — Campaign, Contact, Consent, Usage Record, Call Evaluation, Audit Log, Incident (+ RLS)**
  (`F2` · Must · →BRD §16 (16–18, 25–28), DB.md §5.4/§5.6; karışık platform+tenant RLS + WORM consent/audit_log).
- **WBS 1.1.7 — Knowledge Base, KB Document, KB Chunk / Vector Store namespace (+ RLS)**
  (`F1` · Must · →BRD §16 (12–14), FR-KB-004/005/008/010, SAD §10.2/§12.1, DB.md §5.3/§7.1/§12).
  Çekirdek: tenant+agent **namespace** izolasyonu (FR-KB-004) = tenant RLS (cross-tenant) +
  namespace/kb_id + **kompozit tenant-kapsamlı FK** (cross-agent, defense-in-depth). Vendor-neutral:
  pgvector kuruluysa `kb_chunk.embedding VECTOR(1536)` + HNSW koşullu eklenir; değilse **metadata-only**
  (OpenSearch yolu, DB.md §12).

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
    0006_call_interaction.{up,down}.sql     # call, call_leg, transcript(+segment), recording, call_event,
                                            #   tool_execution (WORM); RANGE partition + DEFAULT + create_month_partition()
    0007_rls_call_interaction.{up,down}.sql # 7 partition'lı tablo tenant_isolation RLS + grant; tool_execution WORM grant
    0008_outbound_ops_governance.{up,down}.sql # campaign, contact, consent (WORM), call_evaluation,
                                            #   usage_record/audit_log (WORM, partition'lı), incident; call→campaign FK ALTER
    0009_rls_outbound_ops_governance.{up,down}.sql # 5 standart + 2 karışık (platform+tenant) RLS; consent/audit_log WORM grant
    0010_knowledge_base.{up,down}.sql       # knowledge_base, kb_document, kb_chunk; tenant+agent namespace,
                                            #   kompozit tenant FK, pgvector koşullu embedding+HNSW (metadata-only fallback)
    0011_rls_knowledge_base.{up,down}.sql   # 3 KB tablo tenant_isolation RLS + grant (mutable, WORM yok)
  seeds/
    roles.sql                               # sabit global rol kümesi (FR-IAM-011, ADR-012)
  tests/
    rls_isolation.sql                       # canlı RLS davranış testi — Tenant/Org/User (CI)
    agent_config_isolation.sql              # canlı RLS + WORM davranış testi — Agent/Config (CI)
    call_interaction_isolation.sql          # canlı RLS + WORM + partition davranış testi — Çağrı/Etkileşim (CI)
    outbound_ops_governance_isolation.sql   # canlı RLS + WORM + partition + karışık-politika testi (CI)
    knowledge_base_isolation.sql            # canlı RLS + namespace izolasyon + kompozit FK testi — KB/Vector Store (CI)
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

Politikalar `NULLIF(current_setting('app.tenant_id', true), '')::uuid` kullanır: GUC yoksa `NULL`,
**veya** bağlantı havuzunda `SET LOCAL` sonrası placeholder boş-string'e (`''`) döndüğünde `NULLIF`
onu `NULL`'a çevirir → karşılaştırma `NULL` → **hiçbir satır görünmez** (fail-closed). Çıplak
`''::uuid` *hata* fırlatırdı (fail-error); `NULLIF(...,'')` her iki durumu da sessizce kapatır
(DB.md §6.2). Scope'u unutmak veriyi açmaz, kapatır.

## Kapılar

```bash
# Statik kapı (sunucu gerekmez) — tasarım invariant doğrulaması
python3 db/schema_probe.py validate     # 380/380 kontrol (1.1.1 + 1.1.2 + 1.1.3 + 1.1.4 + 1.1.7), çıkış 0
python3 db/schema_probe.py selftest     # 33/33 predikat testi, çıkış 0
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
**1.1.3 ek:** 7 çağrı/etkileşim tablosunun **RANGE (created_at) partition'lı** olması + `(id, created_at)`
kompozit PK + tenant_id NOT NULL gerçek FK; call_id/transcript_id'nin **mantıksal FK** (partition'lı
parent'a REFERENCES yok — DB.md §7.2); call'da agent/agent_version gerçek FK'leri; her tablo RLS/WITH
CHECK; `tool_execution` WORM (immutable trigger + INSERT+SELECT grant) + idempotency UNIQUE; DEFAULT
partition + `create_month_partition()` aylık yardımcı; call_event GIN + recording retention partial
index. **Çapraz (tüm seriler):** politikaların `NULLIF(current_setting(...),'')::uuid` ile
boş-string-güvenli (havuz fail-closed) olması.
**1.1.7 ek:** 3 KB tablosu + UUIDv7 PK + tenant_id NOT NULL FK + RLS/WITH CHECK; `knowledge_base`
**namespace** (FR-KB-004) NOT NULL + `CHECK (length>0)` + UNIQUE (tenant_id, namespace) + nullable
`agent_id` (tenant-shared); **kompozit tenant-kapsamlı FK** (`(tenant_id, kb_id)`/`(tenant_id, document_id)`
→ parent `(tenant_id, id)`) ile cross-tenant kb_id bağının yapısal reddi; **pgvector koşullu**
embedding `VECTOR(1536)` + HNSW (`pg_extension` kontrolü) ve embedding'in CREATE TABLE gövdesinde
**olmaması** (metadata-only fallback, DB.md §12); KB'nin WORM olmaması (app_rw tam CRUD; immutable
trigger yok); content_ttl/sensitive partial indeksleri (FR-KB-008/010).

`run_live_test.sh` (CI'da gerçek sunucuyla) doğrular: fail-closed (scope yokken 0 satır), tenant
izolasyonu, tenant Root self-policy, cross-tenant insert reddi, platform realm tam görünürlük,
global rol tablosuna `app_rw` yazım reddi, UUIDv7 bit kontrolü. **1.1.2 ek
(`agent_config_isolation.sql`):** agent/config tenant izolasyonu, cross-tenant write reddi, dairesel
FK çözümü, `agent_version` UPDATE/DELETE reddi (WORM), platform realm'in iş config'ini görmemesi
(altın kural). **1.1.7 ek (`knowledge_base_isolation.sql`):** KB tenant izolasyonu (cross-tenant RLS),
**cross-agent namespace izolasyonu** (X namespace retrieval'i yalnız X chunk'larını döndürür, Y
sızmaz — FR-KB-004), cross-tenant write reddi (WITH CHECK), **kompozit tenant FK** ile cross-tenant
kb_id chunk insert reddi (FK doğrulaması RLS'i bypass etse de tenant tutarlılığı zorlanır), platform
realm'in KB içeriğini görmemesi (altın kural). Chunk'lar metadata-only eklenir → pgvector'sız da koşar.
**1.1.3 ek (`call_interaction_isolation.sql`):** çağrı/etkileşim tenant izolasyonu,
partition routing (Haziran 2026 çağrısı `call_p202606`'ya düşer — `tableoid` ile doğrulanır),
cross-tenant write reddi, `tool_execution` idempotency (duplicate insert reddi) + UPDATE/DELETE reddi
(WORM), mutable `call` UPDATE'in geçmesi, platform realm'in transcript görmemesi (altın kural).
Not: `set_config(...,NULL,...)` placeholder'ı boş-string'e (`''`) düşürür; politikadaki
`NULLIF(...,'')::uuid` bunu fail-closed'a çevirir (havuz davranışı testte birebir doğrulanır).

## Sonraki adımlar

- WBS 1.1.4 / 1.1.7 — **tamamlandı** (yukarıda). BRD §16'nın 28 varlığı + KB/vector store namespace fiziksel.
  Açık FK kapamaları: `tool_execution.tool_id` FK'si tool tablosu (WBS 7.x) gelince ALTER ile eklenir.
- WBS 1.1.8 — Event stream (Kafka) topic tasarımı (ADR-007); WBS 1.1.9 — OLAP analitik şema.
- WBS 12.1.2 — permission-key kataloğu + role→permission bundle eşlemesi (seed genişler).
- WBS 0.4.4 / 12.2.3 — `run_live_test.sh` CI hattına bağlanır (tenant izolasyon test kapısı).
