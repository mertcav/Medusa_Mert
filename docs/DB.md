# Veri Tabanı Tasarım Dokümanı (DB)
## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**Multi-Tenant · Row-Level Security · Polyglot Persistence**
BRD §16 (Ana Varlıklar) → PK/FK · İndeks · RLS politikaları

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Enterprise Voice AI Agent Platform — Veri Tabanı Tasarım Dokümanı |
| Doküman Tipi | Database Design Document (DDD) |
| Hedef Ürün | Multi-Tenant Enterprise Voice AI Agent Platform |
| Kaynak Dokümanlar | `docs/BRD.md` (v2.1) · `docs/SAD.md` (v1.1) · `docs/SRS.md` (v1.0) |
| Amaç | BRD §16 varlıklarını ilişkisel şemaya (PK/FK, indeks, RLS) indirgemek |
| Sürüm | 1.0 |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | İlk sürüm. BRD §16'daki 28 ana varlık PostgreSQL ilişkisel şemasına indirildi: tablo başına PK/FK, indeks ve RLS politikaları; tenancy sınıflandırması; partition stratejisi; residency + şifreleme; WORM audit; retention/legal-hold. SAD §12/§13/§14.4 ile hizalı. WBS 0.1.3. |

---

## İçindekiler

1. [Amaç ve Kapsam](#1-amaç-ve-kapsam)
2. [Tasarım İlkeleri](#2-tasarım-i̇lkeleri)
3. [Konvansiyonlar](#3-konvansiyonlar)
4. [Depolama Eşlemesi ve Tenancy Sınıflandırması](#4-depolama-eşlemesi-ve-tenancy-sınıflandırması)
5. [Varlık Şemaları (BRD §16)](#5-varlık-şemaları-brd-16)
   - 5.1 [Tenant, Organizasyon ve IAM](#51-tenant-organizasyon-ve-iam)
   - 5.2 [Agent ve Yapılandırma](#52-agent-ve-yapılandırma)
   - 5.3 [Telefoni](#53-telefoni)
   - 5.4 [Outbound, Contact ve Consent](#54-outbound-contact-ve-consent)
   - 5.5 [Çağrı ve Etkileşim (yüksek hacim)](#55-çağrı-ve-etkileşim-yüksek-hacim)
   - 5.6 [Operasyon, Faturalama ve Yönetişim](#56-operasyon-faturalama-ve-yönetişim)
6. [Row-Level Security (RLS) Politikaları](#6-row-level-security-rls-politikaları)
7. [İndeks ve Partition Stratejisi](#7-i̇ndeks-ve-partition-stratejisi)
8. [Veri Yerleşimi (Residency) ve Şifreleme](#8-veri-yerleşimi-residency-ve-şifreleme)
9. [Retention, Legal Hold ve Geri Döndürülemez Silme](#9-retention-legal-hold-ve-geri-döndürülemez-silme)
10. [Migration ve Şema Versiyonlama](#10-migration-ve-şema-versiyonlama)
11. [İzlenebilirlik (FR/SR Eşlemesi)](#11-i̇zlenebilirlik-frsr-eşlemesi)
12. [Açık Kararlar ve Sonraki Adımlar](#12-açık-kararlar-ve-sonraki-adımlar)

---

## 1. Amaç ve Kapsam

Bu doküman, BRD §16'da iş seviyesinde listelenen 28 ana varlığın **fiziksel veri tabanı tasarımını**
tanımlar: birincil/yabancı anahtarlar (PK/FK), indeksler ve **row-level security (RLS)** politikaları.
SAD §12 (Veri Mimarisi), §13 (Çok Kiracılılık) ve §14.4 (Panel/AuthZ) kararlarını şema seviyesine indirir.

**Kapsam içi:** Operasyonel (OLTP) ilişkisel şema — PostgreSQL (+ pgvector). Tenancy izolasyonu, PK/FK
bütünlüğü, indeks/partition stratejisi, residency, şifreleme, WORM audit, retention/silme.

**Kapsam dışı (referansla işaret edilir):** Redis session-memory anahtar şeması (WBS 1.1.5), nesne
depolama bucket/prefix düzeni (WBS 1.1.6), OLAP analitik şema (WBS 1.1.9), Kafka topic tasarımı
(WBS 1.1.8). Bu doküman ilişkisel kaynak şemayı tanımlar; analitik depolar bundan türetilir.

> **Source of truth:** Çelişki olursa `docs/BRD.md` ve `docs/SAD.md` esastır. Bu doküman onlardan türer.
> Vendor seçimi yapılmaz; PostgreSQL "ilişkisel + RLS + pgvector" yeteneği için referans alınır (SAD §12.1, ADR-006).

---

## 2. Tasarım İlkeleri

| # | İlke | Karşılık |
|---|------|----------|
| P1 | **Tenant her satırda birinci sınıf boyut.** İş verisi tablolarının tümü `tenant_id` taşır; izolasyon varsayılan. | SAD §13.1, FR-TEN-002, NFR 10.6 |
| P2 | **Defense in depth.** Tenant izolasyonu hem uygulama scope'unda hem DB RLS'inde çift kontrol edilir. | SAD §14.4.2 §13 |
| P3 | **L0 iş verisini görmez.** Platform (L0) rolleri tenant iş verisi tablolarına repository/grant düzeyinde bağlı değildir; erişim yalnız break-glass ile. | FR-IAM-008/009/010, ADR-011 |
| P4 | **Immutability where it matters.** Agent Version, Audit Log, Consent ve Tool Execution append-only/WORM; geçmiş değiştirilemez. | FR-AGT-006, FR-IAM-006 |
| P5 | **Residency by design.** Veri home-region'da kalır; cross-region replikasyon yalnız aynı residency sınıfında. | NFR 10.7, SAD §12.3 |
| P6 | **PII en aza indir, ayrıştır, şifrele.** Ham ses/transkript nesne depoda; DB yalnız pointer + metadata + redaction durumu tutar. | FR-REC-004/005, BRD §14.1 |
| P7 | **Yüksek hacmi partition'la.** Call/Event/Transcript/Usage/Audit zaman+tenant ekseninde bölümlenir; sıcak/soğuk ayrımı retention'ı kolaylaştırır. | NFR 10.3/10.5 |
| P8 | **Deterministik ve idempotent.** Kritik işlem kayıtları (Tool Execution) idempotency anahtarıyla benzersiz. | FR-TOOL-009 |

---

## 3. Konvansiyonlar

- **İsimlendirme:** `snake_case`; tablo adları tekil isim (`call`, `agent`); junction tablolar `<a>_<b>`
  (`role_permission`). Boolean alanlar `is_`/`has_` öneki; zaman alanları `_at` son eki.
- **PK:** Her tabloda `id UUID PRIMARY KEY DEFAULT gen_uuid_v7()` — **UUIDv7** (zaman-sıralı): index
  fragmentasyonunu azaltır, dağıtık üretime ve sıralı insert localitysine uygun. Doğal/iş anahtarları
  (`e164`, `idempotency_key`) ayrıca **UNIQUE** kısıt alır.
- **FK:** `<varlık>_id` (ör. `agent_id`, `call_id`). FK'ler `ON DELETE` davranışı tabloda belirtilir
  (genelde `RESTRICT`; gerçek silme retention motoruyla yapılır, bkz. §9).
- **Tenant kolonu:** İş verisi tablolarında `tenant_id UUID NOT NULL REFERENCES tenant(id)`. Birleşik
  FK'ler (`tenant_id`+yabancı PK) ile cross-tenant referans DB seviyesinde de engellenir (P2).
- **Zaman damgaları:** `created_at timestamptz NOT NULL DEFAULT now()`, `updated_at timestamptz`
  (trigger ile güncellenir). Tüm zamanlar `timestamptz` (UTC).
- **Soft vs hard delete:** Config varlıklarında `deleted_at` (soft delete + audit). PII/iş kaydı
  varlıklarında **hard delete** retention motoruyla, geri döndürülemez (FR-REC-010, §9).
- **Optimistic locking:** Mutable config tablolarında `row_version INTEGER` (artımlı).
- **Para/kullanım:** `numeric(18,6)` (maliyet), `numeric` (token/saniye); para birimi `currency CHAR(3)`.
- **JSON:** Esnek/şemasız yapı için `jsonb` (ör. flow grafiği, tool I/O schema, scope filtresi). Sorgulanan
  jsonb alanlarına GIN indeks.
- **Enum:** Sabit kümeler için PostgreSQL `ENUM` ya da `text` + `CHECK`; v1'de kontrollü genişleme için
  `text + CHECK` tercih (ALTER TYPE kısıtını aşmak için).

---

## 4. Depolama Eşlemesi ve Tenancy Sınıflandırması

BRD §16'daki 28 varlığın deposu ve tenancy sınıfı (SAD §12.1 ile hizalı):

| # | Varlık | Tablo | Depo | Tenancy sınıfı |
|---|--------|-------|------|----------------|
| 1 | Tenant | `tenant` | PostgreSQL | **Root** (kendi `id`'si) |
| 2 | Organisation Unit | `organisation_unit` | PostgreSQL | Tenant-scoped |
| 3 | User | `app_user` | PostgreSQL | Tenant-scoped (L0 kullanıcıları ayrı realm) |
| 4 | Role | `role`, `role_permission`, `permission_key` | PostgreSQL | **Global** (immutable bundle) |
| 5 | Agent | `agent` | PostgreSQL | Tenant-scoped |
| 6 | Agent Version | `agent_version` | PostgreSQL | Tenant-scoped, **WORM** |
| 7 | Prompt | `prompt` | PostgreSQL | Tenant-scoped, versiyonlu |
| 8 | Conversation Flow | `conversation_flow` | PostgreSQL (`jsonb` grafik) | Tenant-scoped, versiyonlu |
| 9 | Voice Profile | `voice_profile` | PostgreSQL | Tenant-scoped |
| 10 | Model Profile | `model_profile` | PostgreSQL | Tenant-scoped |
| 11 | STT Profile | `stt_profile` | PostgreSQL | Tenant-scoped |
| 12 | Knowledge Base | `knowledge_base`, `kb_document`, `kb_chunk` | PostgreSQL + pgvector + nesne depo | Tenant-scoped |
| 13 | Tool | `tool` | PostgreSQL | Tenant-scoped |
| 14 | Phone Number | `phone_number` | PostgreSQL | Tenant-scoped |
| 15 | SIP Trunk | `sip_trunk` | PostgreSQL | Tenant-scoped |
| 16 | Campaign | `campaign` | PostgreSQL | Tenant-scoped |
| 17 | Contact | `contact` | PostgreSQL (PII) | Tenant-scoped |
| 18 | Consent | `consent` | PostgreSQL, **append-only** | Tenant-scoped |
| 19 | Call | `call` | PostgreSQL (**partitioned**) | Tenant-scoped |
| 20 | Call Leg | `call_leg` | PostgreSQL (**partitioned**) | Tenant-scoped |
| 21 | Transcript | `transcript`, `transcript_segment` | PostgreSQL (**partitioned**) + nesne depo | Tenant-scoped (PII) |
| 22 | Recording | `recording` | PostgreSQL (metadata) + nesne depo (ses) | Tenant-scoped (PII) |
| 23 | Event | `call_event` | PostgreSQL (**partitioned**) / Kafka | Tenant-scoped |
| 24 | Tool Execution | `tool_execution` | PostgreSQL (**partitioned**) | Tenant-scoped, idempotent |
| 25 | Call Evaluation | `call_evaluation` | PostgreSQL | Tenant-scoped |
| 26 | Usage Record | `usage_record` | PostgreSQL (**partitioned**) → OLAP | Tenant-scoped |
| 27 | Audit Log | `audit_log` | PostgreSQL (**WORM, partitioned**) | Tenant-scoped + platform |
| 28 | Incident | `incident` | PostgreSQL | Platform / Tenant-scoped |

**Yardımcı tablolar (BRD §16 türevleri, yönetişim için):** `user_role_assignment` (scoped assignment,
ADR-012), `break_glass_grant` (FR-IAM-009/010), `retention_policy` + `legal_hold` (FR-REC-006/007/010),
`api_key` (FR-IAM/T-05), `idp_role_mapping` (FR-IAM-002/007).

> **Not:** "Event" iki yerde yaşar: gerçek zamanlı düzlemde Kafka (ADR-007, replay), kalıcı/sorgulanabilir
> düzlemde `call_event` (partitioned). Bu doküman kalıcı ilişkisel formu tanımlar.

---

## 5. Varlık Şemaları (BRD §16)

Aşağıdaki DDL **referans/kavramsal**tır (kesin tip ve isimlendirme migration aşamasında — §10 —
netleşir). Her grup için ortak kolonlar (`id`, `tenant_id`, `created_at`, `updated_at`, `row_version`,
`deleted_at`) tekrar yazılmaz; yalnız ilk örnekte gösterilir.

### 5.1 Tenant, Organizasyon ve IAM

```sql
-- 1) Tenant — kök. Kendi tenant_id'si = id (RLS'te self-row).
CREATE TABLE tenant (
    id              UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                       CHECK (status IN ('provisioning','active','suspended','terminated')),
    isolation_mode  TEXT NOT NULL DEFAULT 'shared'
                       CHECK (isolation_mode IN ('shared','dedicated')),   -- FR-TEN-005, ADR-006
    home_region     TEXT NOT NULL,                       -- NFR 10.7 (UK/EU/NA/ME)
    default_locale  TEXT NOT NULL DEFAULT 'tr-TR',
    timezone        TEXT NOT NULL DEFAULT 'Europe/Istanbul',
    retention_profile TEXT,                              -- FR-TEN-004 → retention_policy
    compliance_profile TEXT,                             -- BRD §14.4 (TR/UK/EU/ME + sektörel)
    require_tenant_approval BOOLEAN NOT NULL DEFAULT false, -- FR-IAM-010 break-glass toggle
    kms_key_ref     TEXT NOT NULL,                       -- tenant başına KMS key (NFR 10.6)
    plan_id         UUID,                                -- -> pricing_plan(id), billing modülü (WBS 15, FR-BIL-003)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ,
    row_version     INTEGER NOT NULL DEFAULT 1
);

-- 2) Organisation Unit — marka/ülke/departman/proje (FR-TEN-003); self-ref hiyerarşi.
CREATE TABLE organisation_unit (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    parent_id   UUID REFERENCES organisation_unit(id),
    type        TEXT NOT NULL CHECK (type IN ('brand','country','department','project')),
    name        TEXT NOT NULL,
    region      TEXT,                                    -- residency override (NFR 10.7)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ,
    UNIQUE (tenant_id, parent_id, name)
);
CREATE INDEX ix_orgunit_tenant ON organisation_unit (tenant_id);
CREATE INDEX ix_orgunit_parent ON organisation_unit (parent_id);

-- 3) User — panel kullanıcısı. realm: L0 (platform) ayrı, L1/L2 tenant.
CREATE TABLE app_user (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID REFERENCES tenant(id),            -- NULL => platform (L0) kullanıcısı
    realm         TEXT NOT NULL CHECK (realm IN ('platform','tenant')),  -- FR-IAM-008
    external_idp_subject TEXT,                           -- SSO subject (SAML/OIDC), FR-IAM-002
    email         CITEXT NOT NULL,
    display_name  TEXT,
    status        TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active','disabled','deprovisioned')),  -- SCIM, FR-IAM-007
    mfa_enrolled  BOOLEAN NOT NULL DEFAULT false,        -- FR-IAM-003
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ,
    UNIQUE (realm, tenant_id, email)
);
CREATE INDEX ix_user_tenant ON app_user (tenant_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX ix_user_idp ON app_user (external_idp_subject);

-- 4) Role / permission — GLOBAL, immutable bundle (FR-IAM-011, ADR-012). tenant_id YOK.
CREATE TABLE role (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    code        TEXT NOT NULL UNIQUE,                    -- 'tenant_owner','operations_manager',...
    level       TEXT NOT NULL CHECK (level IN ('L0','L1','L2','L1L2')),
    is_immutable BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE permission_key (
    key         TEXT PRIMARY KEY,                        -- 'calls:read', 'tenant:provision' (SAD §14.4.3)
    resource    TEXT NOT NULL,
    action      TEXT NOT NULL,
    is_own_scoped BOOLEAN NOT NULL DEFAULT false         -- '*:own' (BRD §17.7)
);
CREATE TABLE role_permission (
    role_id     UUID NOT NULL REFERENCES role(id),
    perm_key    TEXT NOT NULL REFERENCES permission_key(key),
    PRIMARY KEY (role_id, perm_key)
);

-- 4b) User Role Assignment — scoped (FR-IAM-011, ADR-012). Tenant-scoped + scope filtresi.
CREATE TABLE user_role_assignment (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID REFERENCES tenant(id),              -- NULL => platform atama
    user_id     UUID NOT NULL REFERENCES app_user(id),
    role_id     UUID NOT NULL REFERENCES role(id),
    scope       JSONB NOT NULL DEFAULT '{}'::jsonb,      -- {brand|department|campaign: [...]}
    assigned_by UUID REFERENCES app_user(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id, role_id, scope)
);
CREATE INDEX ix_ura_user ON user_role_assignment (user_id);
CREATE INDEX ix_ura_tenant ON user_role_assignment (tenant_id);
```

### 5.2 Agent ve Yapılandırma

```sql
-- 5) Agent — voice AI agent tanımı (FR-AGT-001/002).
CREATE TABLE agent (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    org_unit_id   UUID REFERENCES organisation_unit(id),
    name          TEXT NOT NULL,
    purpose       TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'draft'
                     CHECK (lifecycle_state IN ('draft','test','staging','production','archived')), -- FR-AGT-005
    active_version_id UUID,                              -- -> agent_version (production sürüm)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ,
    row_version   INTEGER NOT NULL DEFAULT 1,
    deleted_at    TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);
CREATE INDEX ix_agent_tenant ON agent (tenant_id);
CREATE INDEX ix_agent_state ON agent (tenant_id, lifecycle_state) WHERE deleted_at IS NULL;

-- 6) Agent Version — DEĞİŞMEZ snapshot (FR-AGT-006, P4 WORM). rollback için.
CREATE TABLE agent_version (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    agent_id      UUID NOT NULL REFERENCES agent(id),
    version_no    INTEGER NOT NULL,
    prompt_id     UUID REFERENCES prompt(id),
    flow_id       UUID REFERENCES conversation_flow(id),
    voice_profile_id UUID REFERENCES voice_profile(id),
    model_profile_id UUID REFERENCES model_profile(id),
    stt_profile_id   UUID REFERENCES stt_profile(id),
    snapshot      JSONB NOT NULL,                        -- bağlanan tüm config'in donmuş kopyası
    published_by  UUID REFERENCES app_user(id),
    published_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no)
);
CREATE INDEX ix_agentver_agent ON agent_version (tenant_id, agent_id, version_no DESC);
-- agent.active_version_id -> agent_version(id) (FK migration sonrası eklenir; dairesel referans)

-- 7) Prompt (FR-AGT-004, FR-LLM-006) — versiyonlu, immutable system prompt.
CREATE TABLE prompt (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id),
    agent_id     UUID REFERENCES agent(id),
    version_no   INTEGER NOT NULL,
    body         TEXT NOT NULL,
    is_published BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no)
);

-- 8) Conversation Flow (FR-AGT-003) — node/state grafiği jsonb.
CREATE TABLE conversation_flow (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id),
    agent_id     UUID REFERENCES agent(id),
    version_no   INTEGER NOT NULL,
    mode         TEXT NOT NULL CHECK (mode IN ('single_prompt','node_flow')),
    graph        JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no)
);
CREATE INDEX ix_flow_graph ON conversation_flow USING gin (graph jsonb_path_ops);

-- 9/10/11) Voice / Model / STT Profile — yapı benzer (tenant-scoped config).
CREATE TABLE voice_profile (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    name        TEXT NOT NULL,
    settings    JSONB NOT NULL,        -- TTS provider-neutral ayarları, hız/ses/pronunciation dict
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE TABLE model_profile (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    name        TEXT NOT NULL,
    tiering     JSONB NOT NULL,        -- küçük/büyük model tier eşlemesi (FR-LLM-002/013, FR-RES-005)
    no_train    BOOLEAN NOT NULL DEFAULT true,  -- "tenant verisi eğitime kapalı" (FR-LLM-012)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE TABLE stt_profile (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    name        TEXT NOT NULL,
    settings    JSONB NOT NULL,        -- dil, phrase boosting, alan optimizasyonu (FR-STT-005)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);

-- 12) Knowledge Base + doküman + chunk (pgvector). FR-KB-*. WBS 1.1.7.
-- namespace = tenant+agent retrieval kapsamı (FR-KB-004); agent_id NULL => tenant-shared.
-- kb_document/kb_chunk → knowledge_base bağı KOMPOZİT tenant-kapsamlı FK ile kurulur
-- (tenant_id, kb_id) → (tenant_id, id): FK doğrulaması RLS'i bypass ettiğinden, bu desen
-- bir chunk'ın BAŞKA tenant'ın KB'sine bağlanmasını yapısal olarak imkânsız kılar
-- (FR-KB-004/FR-TEN-002, defense-in-depth). Bu yüzden her parent UNIQUE (tenant_id, id) taşır.
CREATE TABLE knowledge_base (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    agent_id    UUID REFERENCES agent(id) ON DELETE RESTRICT,    -- NULL => tenant-shared KB (FR-KB-004)
    name        TEXT NOT NULL,
    namespace   TEXT NOT NULL CHECK (length(namespace) > 0),     -- tenant+agent izolasyon namespace (FR-KB-004)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, namespace),
    UNIQUE (tenant_id, id)             -- kompozit tenant-kapsamlı FK hedefi
);
CREATE TABLE kb_document (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    kb_id         UUID NOT NULL,
    source_uri    TEXT,                -- nesne depo pointer (objstore, WBS 1.1.6)
    access_scope  JSONB,               -- doküman bazında erişim yetkisi (FR-KB-005)
    version_no    INTEGER NOT NULL DEFAULT 1,       -- yeniden ingest sürüm üretir (FR-KB-003)
    content_ttl_at TIMESTAMPTZ,        -- bayatlama (FR-KB-008)
    is_sensitive  BOOLEAN NOT NULL DEFAULT false,  -- sağlayıcı loguna gitmez (FR-KB-010)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, kb_id) REFERENCES knowledge_base (tenant_id, id) ON DELETE RESTRICT
);
CREATE TABLE kb_chunk (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    kb_id        UUID NOT NULL,        -- denormalize (hızlı namespace filtresi)
    document_id  UUID NOT NULL,
    chunk_no     INTEGER NOT NULL,
    content      TEXT NOT NULL,
    -- embedding VECTOR(1536): pgvector kuruluysa koşullu ALTER ile eklenir; yoksa
    -- kb_chunk metadata-only (embedding harici vektör deposu / OpenSearch yolu, §12).
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, document_id, chunk_no),
    FOREIGN KEY (tenant_id, kb_id)       REFERENCES knowledge_base (tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, document_id) REFERENCES kb_document    (tenant_id, id) ON DELETE RESTRICT
);
-- pgvector koşullu (vendor-neutral, §12): IF EXISTS pg_extension('vector') THEN
--   ALTER TABLE kb_chunk ADD COLUMN embedding VECTOR(1536);
--   CREATE INDEX ix_kbchunk_ann ON kb_chunk USING hnsw (embedding vector_cosine_ops); -- top-k (SAD §10.2)
CREATE INDEX ix_kbchunk_kb  ON kb_chunk (tenant_id, kb_id);        -- namespace filtreli retrieval (FR-KB-004)
CREATE INDEX ix_kbchunk_doc ON kb_chunk (tenant_id, document_id); -- doküman silme/yeniden indeksleme

-- 13) Tool — kurumsal sistem fonksiyonu (FR-TOOL-*).
CREATE TABLE tool (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    name          TEXT NOT NULL,
    connector_type TEXT NOT NULL CHECK (connector_type IN ('rest','soap','graphql','webhook')),
    endpoint_url  TEXT NOT NULL,
    input_schema  JSONB NOT NULL,       -- JSON schema (FR-TOOL-002)
    output_schema JSONB NOT NULL,
    auth_level    TEXT NOT NULL CHECK (auth_level IN ('read','write')),  -- FR-TOOL-004/005
    is_critical   BOOLEAN NOT NULL DEFAULT false,  -- deterministic workflow gerekli (BRD §13)
    allowlisted   BOOLEAN NOT NULL DEFAULT false,  -- endpoint allowlist (FR-TOOL-012)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
```

### 5.3 Telefoni

```sql
-- 14) Phone Number (FR-TEL-004/005). E.164 global benzersiz.
CREATE TABLE phone_number (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    e164        TEXT NOT NULL,                          -- E.164 normalize
    direction   TEXT NOT NULL CHECK (direction IN ('inbound','outbound','both')),
    sip_trunk_id UUID REFERENCES sip_trunk(id),
    agent_id    UUID REFERENCES agent(id),              -- inbound yönlendirme
    region      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (e164)                                       -- numara havuzu çakışmaz
);
CREATE INDEX ix_phone_tenant ON phone_number (tenant_id);

-- 15) SIP Trunk (FR-TEL-002, BYOC).
CREATE TABLE sip_trunk (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id),
    name        TEXT NOT NULL,
    provider    TEXT,                                   -- vendor-neutral; adapter ile çözülür
    config      JSONB NOT NULL,                         -- credential REF (secret store), endpoint
    region      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
```

### 5.4 Outbound, Contact ve Consent

```sql
-- 16) Campaign (FR-OUT-*).
CREATE TABLE campaign (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    org_unit_id   UUID REFERENCES organisation_unit(id),
    name          TEXT NOT NULL,
    agent_id      UUID REFERENCES agent(id),
    status        TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','running','paused','stopped','completed')), -- FR-OUT-010
    max_attempts  INTEGER NOT NULL DEFAULT 3,           -- FR-OUT-005
    retry_interval_minutes INTEGER,
    script_version TEXT,                                -- FR-OUT-009
    calling_hours JSONB,                                -- ülke/bölge arama saati (FR-OUT-004)
    capacity_cap  INTEGER,                              -- ≤ agent+trunk kapasitesi (FR-OUT-007)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX ix_campaign_tenant_status ON campaign (tenant_id, status);

-- 17) Contact — aranacak müşteri (PII).
CREATE TABLE contact (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    campaign_id   UUID REFERENCES campaign(id),
    e164          TEXT NOT NULL,
    party_type    TEXT CHECK (party_type IN ('individual','company')),  -- consent kuralı (§14.3)
    external_ref  TEXT,                                 -- CRM kaydı (FR-OUT-002)
    attributes    JSONB,                                -- maskeli görüntülenir (BRD §17.7)
    do_not_call   BOOLEAN NOT NULL DEFAULT false,       -- DNC/suppression (FR-TEL-014, FR-OUT-006)
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_call_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, campaign_id, e164)
);
CREATE INDEX ix_contact_campaign ON contact (tenant_id, campaign_id);
CREATE INDEX ix_contact_dnc ON contact (tenant_id, e164) WHERE do_not_call = true;

-- 18) Consent — APPEND-ONLY izin kaydı (FR-OUT-003, §14.3). Opt-out anında yeni satır.
CREATE TABLE consent (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    contact_id    UUID REFERENCES contact(id),
    e164          TEXT NOT NULL,
    purpose       TEXT NOT NULL,                        -- arama amacı
    country       TEXT NOT NULL,
    consent_source TEXT,                                -- consent kaynağı
    consent_date  TIMESTAMPTZ,                          -- consent tarihi
    scope         JSONB,                                -- kapsam
    legal_basis   TEXT,                                 -- hukuki dayanak (BRD §14.1)
    iys_ref       TEXT,                                 -- TR İYS izin kaydı (§14.3)
    state         TEXT NOT NULL CHECK (state IN ('granted','withdrawn')),  -- opt-out = withdrawn
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_consent_lookup ON consent (tenant_id, e164, recorded_at DESC);  -- son durum
```

### 5.5 Çağrı ve Etkileşim (yüksek hacim)

> Bu grup partition'lıdır (§7). PK, partition anahtarı `created_at`'i içermek zorundadır:
> birincil anahtar `(id, created_at)` ya da kompozit `(tenant_id, id, created_at)`.

```sql
-- 19) Call — çağrı üst kaydı. RANGE partition (created_at, aylık).
CREATE TABLE call (
    id              UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    correlation_id  UUID NOT NULL,                      -- BRD §15, SAD §13.3/§17.1
    agent_id        UUID REFERENCES agent(id),
    agent_version_id UUID REFERENCES agent_version(id),
    campaign_id     UUID REFERENCES campaign(id),       -- outbound ise
    direction       TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    from_e164       TEXT,
    to_e164         TEXT,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    end_reason      TEXT,                                -- standart taksonomi (FR-TEL-012)
    outcome         TEXT,                                -- containment/transfer (FR-ANA-002/003)
    region          TEXT NOT NULL,                       -- residency
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_call_tenant_time ON call (tenant_id, created_at DESC);
CREATE INDEX ix_call_correlation ON call (correlation_id);
CREATE INDEX ix_call_agent ON call (tenant_id, agent_id, created_at DESC);

-- 20) Call Leg — transfer dahil bacak (FR-TEL-007, handoff §9).
CREATE TABLE call_leg (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    call_id       UUID NOT NULL,                         -- (call_id, created_at) mantıksal FK
    leg_type      TEXT NOT NULL CHECK (leg_type IN ('agent','transfer_cold','transfer_warm','transfer_whisper','voicemail')),
    target        TEXT,                                  -- kuyruk/skill/temsilci
    started_at    TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ,
    result        TEXT,                                  -- transfer sonucu (FR-HND-008)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_leg_call ON call_leg (tenant_id, call_id);

-- 21) Transcript (+ segment). Tam metin nesne depoda; DB metadata + segment timeline.
CREATE TABLE transcript (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    call_id       UUID NOT NULL,
    storage_uri   TEXT,                                  -- nesne depo pointer (P6)
    redaction_state TEXT NOT NULL DEFAULT 'pending'
                     CHECK (redaction_state IN ('pending','redacted','not_required')), -- FR-REC-004
    summary       TEXT,                                  -- çağrı özeti (BRD §8.1)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_transcript_call ON transcript (tenant_id, call_id);

CREATE TABLE transcript_segment (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    transcript_id UUID NOT NULL,
    seq           INTEGER NOT NULL,
    speaker       TEXT CHECK (speaker IN ('caller','agent','human')),
    text          TEXT,                                  -- kart/parola/OTP çıkarılmış (FR-REC-005)
    confidence    NUMERIC(4,3),                          -- word confidence (BRD §15)
    started_ms    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 22) Recording — ses metadata; ham ses nesne depoda + KMS.
CREATE TABLE recording (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    call_id       UUID NOT NULL,
    storage_uri   TEXT NOT NULL,                         -- tenant bucket/prefix + KMS (SAD §12.1)
    channels      SMALLINT CHECK (channels IN (1,2)),    -- tek/çift kanal (FR-REC-003)
    duration_ms   INTEGER,
    redaction_state TEXT NOT NULL DEFAULT 'pending',
    retain_until  TIMESTAMPTZ,                           -- retention (FR-REC-006)
    legal_hold    BOOLEAN NOT NULL DEFAULT false,        -- FR-REC-007
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_recording_retention ON recording (retain_until) WHERE legal_hold = false;

-- 23) Event — gerçek zamanlı çağrı olayı (kalıcı form; replay Kafka'da).
CREATE TABLE call_event (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    call_id       UUID NOT NULL,
    correlation_id UUID NOT NULL,
    event_type    TEXT NOT NULL,                         -- BRD §15 zaman damgaları taksonomisi
    payload       JSONB,                                 -- jitter/latency/token vb. metrikler
    occurred_at   TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_event_call ON call_event (tenant_id, call_id, occurred_at);

-- 24) Tool Execution — API işlem kaydı; idempotent (FR-TOOL-009/010).
CREATE TABLE tool_execution (
    id              UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id),
    call_id         UUID,
    correlation_id  UUID NOT NULL,
    tool_id         UUID REFERENCES tool(id),
    idempotency_key TEXT NOT NULL,                       -- duplicate işlem önleme (FR-TOOL-009)
    request         JSONB,
    response        JSONB,
    status          TEXT NOT NULL CHECK (status IN ('success','error','timeout')),
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at),
    UNIQUE (tenant_id, idempotency_key, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_toolexec_call ON tool_execution (tenant_id, call_id);

-- 25) Call Evaluation — otomatik/manuel QA (FR-ANA-001/009).
CREATE TABLE call_evaluation (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    call_id       UUID NOT NULL,
    eval_type     TEXT NOT NULL CHECK (eval_type IN ('automatic','manual')),
    scores        JSONB,
    flags         JSONB,                                 -- kritik konuşma işaretleme (FR-ANA-008)
    evaluator_id  UUID REFERENCES app_user(id),          -- manuel ise
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_eval_call ON call_evaluation (tenant_id, call_id);
```

### 5.6 Operasyon, Faturalama ve Yönetişim

```sql
-- 26) Usage Record — maliyet/kullanım/kaynak (FR-BIL-001/002, FR-ANA-013).
CREATE TABLE usage_record (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    call_id       UUID,
    category      TEXT NOT NULL CHECK (category IN ('telephony','stt','tts','llm','platform','compute')),
    provider      TEXT,
    quantity      NUMERIC,                               -- saniye/dakika/token (FR-BIL-001)
    unit          TEXT,
    cost          NUMERIC(18,6),
    currency      CHAR(3),
    cpu_ms        NUMERIC,                               -- per-call kaynak (FR-RES-016)
    mem_mb_peak   NUMERIC,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_usage_tenant_time ON usage_record (tenant_id, recorded_at DESC);
CREATE INDEX ix_usage_call ON usage_record (tenant_id, call_id);

-- 27) Audit Log — WORM append-only + hash chain bütünlük (FR-IAM-006, FR-REC-009).
CREATE TABLE audit_log (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID,                                  -- NULL => platform işlemi
    actor_user_id UUID,                                  -- app_user(id) (FK YOK: WORM bağımsızlık)
    actor_realm   TEXT NOT NULL,
    action        TEXT NOT NULL,                         -- 'consent:withdraw','transcript:read',...
    resource_type TEXT,
    resource_id   UUID,
    break_glass_id UUID,                                 -- break_glass_grant referansı (FR-IAM-009)
    detail        JSONB,
    prev_hash     BYTEA,                                 -- önceki kaydın hash'i (chain)
    row_hash      BYTEA NOT NULL,                        -- bu kaydın hash'i (bütünlük)
    occurred_at   TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE INDEX ix_audit_tenant_time ON audit_log (tenant_id, occurred_at DESC);
CREATE INDEX ix_audit_resource ON audit_log (resource_type, resource_id);

-- 28) Incident — operasyon olayı (P-09 / SRE; platform veya tenant).
CREATE TABLE incident (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID REFERENCES tenant(id),            -- NULL => platform geneli
    severity      TEXT NOT NULL CHECK (severity IN ('sev1','sev2','sev3','sev4')),
    status        TEXT NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open','mitigating','resolved','closed')),
    title         TEXT NOT NULL,
    detail        JSONB,
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);
CREATE INDEX ix_incident_status ON incident (status, severity);

-- Yardımcı) Break-glass grant (FR-IAM-009/010, SAD §14.4.2 Tier B).
CREATE TABLE break_glass_grant (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    target_tenant_id UUID NOT NULL REFERENCES tenant(id),
    requested_by  UUID NOT NULL REFERENCES app_user(id),
    approved_by   UUID REFERENCES app_user(id),          -- maker-checker (talep eden ≠ onaylayan)
    tier          TEXT NOT NULL CHECK (tier IN ('B')),   -- Tier A grant gerektirmez
    reason_code   TEXT NOT NULL,                         -- zorunlu gerekçe kodu
    scope         JSONB,
    granted_at    TIMESTAMPTZ,
    expires_at    TIMESTAMPTZ,                           -- default 60 dk, max 4 sa (auto-expiry)
    revoked_at    TIMESTAMPTZ,
    tenant_approved BOOLEAN,                             -- require_tenant_approval ise
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_bg_active ON break_glass_grant (target_tenant_id, expires_at)
    WHERE revoked_at IS NULL;

-- Yardımcı) Retention policy + legal hold (FR-REC-006/007/010, FR-TEN-004).
CREATE TABLE retention_policy (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    data_class    TEXT NOT NULL CHECK (data_class IN ('recording','transcript','call_meta','usage','audit')),
    retain_days   INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, data_class)
);
CREATE TABLE legal_hold (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id),
    resource_type TEXT NOT NULL,
    resource_id   UUID NOT NULL,
    reason        TEXT,
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 6. Row-Level Security (RLS) Politikaları

### 6.1 İlke

İzolasyon iki katmanlıdır (P2, defense in depth): uygulama her isteğe `tenant_id` scope'u uygular **ve**
PostgreSQL RLS aynı `tenant_id`'yi bağımsız zorlar. Uygulama bug'ı tenant sızıntısına dönüşmez.

- Her oturum başında uygulama, doğrulanmış tenant kimliğini bir GUC'a yazar:
  `SET LOCAL app.tenant_id = '<uuid>';` (transaction-scoped, `SET LOCAL` — bağlantı havuzunda sızmaz).
- Uygulama, RLS'i **bypass etmeyen** bir DB rolü (`app_rw`) ile bağlanır; superuser/`BYPASSRLS` kullanılmaz.
- Tüm iş verisi tablolarında `FORCE ROW LEVEL SECURITY` (tablo sahibi de RLS'e tabi olur).

### 6.2 Standart tenant izolasyon politikası (her iş verisi tablosu)

```sql
ALTER TABLE <tablo> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <tablo> FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON <tablo>
    USING       (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK  (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

- `USING` → okuma/güncelleme/silmede satır görünürlüğü; `WITH CHECK` → insert/update'te yanlış
  `tenant_id` yazılmasını engeller (cross-tenant write koruması).
- `current_setting(..., true)` ikinci argümanı `true`: GUC set edilmemişse hata yerine NULL döndürür.
- **`NULLIF(..., '')` neden gerekli:** bağlantı havuzunda `SET LOCAL app.tenant_id` transaction
  sonunda geri alınır, ancak placeholder GUC oturumda tanımlı kaldığından `current_setting(...,true)`
  bir sonraki (scope set etmeyen) transaction'da **boş string `''` döndürür, NULL değil**. Çıplak
  `''::uuid` *hata* fırlatırdı (fail-closed değil, fail-error). `NULLIF(...,'')` boş string'i NULL'a
  çevirir → karşılaştırma NULL → **hiçbir satır görünmez** (gerçek fail-closed). Hem set-edilmemiş
  (NULL) hem havuzda-resetlenmiş (`''`) durum tek desende kapanır. Scope unutmak veri açmaz, kapatır.

### 6.3 Tablo sınıfına göre politika matrisi

| Sınıf | Tablolar | RLS politikası |
|-------|----------|----------------|
| **Tenant-scoped** | organisation_unit, app_user(tenant), agent, agent_version, prompt, conversation_flow, voice/model/stt_profile, knowledge_base, kb_document, kb_chunk, tool, phone_number, sip_trunk, campaign, contact, consent, call, call_leg, transcript, transcript_segment, recording, call_event, tool_execution, call_evaluation, usage_record, retention_policy, legal_hold, user_role_assignment | §6.2 standart `tenant_isolation` |
| **Root** | tenant | Tenant kullanıcısı yalnız kendi satırını görür: `USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)`. Platform realm (`app.platform = on`) tümünü görür. |
| **Global / reference** | role, permission_key, role_permission | RLS yok (salt-okunur referans; yazım yalnız platform migration). |
| **Platform + tenant karışık** | audit_log, incident | `USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on'))`. Audit **append-only**: ayrıca §6.5. |
| **Platform-only** | break_glass_grant | Yalnız platform realm; tenant'a görünmez (ama Tier B bildirimi tenant'a gider, app katmanında). |

### 6.4 Break-glass ile koşullu erişim (Tier B)

L0, varsayılan olarak tenant iş verisi tablolarına bağlı değildir (P3, ayrı servis/grant — ADR-011).
Tier B erişimi açıldığında, ayrı **break-glass router** geçerli bir grant'i GUC'a yansıtarak okuma açar:

```sql
-- break-glass okuma politikası (yalnız transcript/recording/contact gibi Tier B PII tablolarında, ek policy)
CREATE POLICY break_glass_read ON transcript
    FOR SELECT
    USING (
        current_setting('app.platform', true) = 'on'
        AND tenant_id = NULLIF(current_setting('app.bg_tenant_id', true), '')::uuid
        AND current_setting('app.bg_active', true) = 'on'   -- grant doğrulandı + süre dolmadı
    );
```

- Grant'in `expires_at`'i geçtiğinde uygulama `app.bg_active`'i set etmez → policy false → erişim kapanır
  (time-boxed, standing access yok).
- Her break-glass okuması `audit_log`'a `break_glass_id` ile yazılır; tenant `security_compliance_officer`
  + `tenant_owner`'a bildirim (FR-IAM-009, app katmanı).

### 6.5 WORM / append-only zorlama (audit_log, consent, agent_version)

RLS satır görünürlüğünü; WORM ise **değişmezliği** zorlar. İki mekanizma birlikte:

```sql
-- DB grant düzeyi: app rolüne yalnız INSERT+SELECT; UPDATE/DELETE yok.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM app_rw;
GRANT  INSERT, SELECT          ON audit_log TO   app_rw;

-- Ek güvence: trigger ile UPDATE/DELETE reddi (rol yanlış yapılandırılsa bile).
CREATE TRIGGER trg_audit_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION raise_immutable_violation();
```

- `audit_log` ayrıca `prev_hash`/`row_hash` zinciriyle bütünlük; geçmişe müdahale tespit edilir.
- `consent` ve `agent_version` aynı desenle append-only (opt-out/rollback = yeni satır, eski satır
  değişmez — FR-AGT-006, §14.3).

---

## 7. İndeks ve Partition Stratejisi

### 7.1 İndeks ilkeleri

- **Tenant-öncelikli kompozit:** Tüm yüksek-kardinalite sorgu indekslerinde `tenant_id` ilk kolon
  (`(tenant_id, created_at DESC)`) — RLS filtresi + listeleme bir indeksle karşılanır.
- **FK indeksleri:** Her FK kolonu indekslenir (join + `ON DELETE` kontrol performansı).
- **Partial index:** Filtreli sorgular için (ör. `WHERE deleted_at IS NULL`, `WHERE do_not_call = true`,
  retention için `WHERE legal_hold = false`).
- **GIN:** `jsonb` (flow graph, scope, payload) ve `citext` arama alanları.
- **HNSW (pgvector):** `kb_chunk.embedding` ANN retrieval (top-k, SAD §10.2).
- **BRIN:** Çok büyük, zaman-sıralı partition'larda (`created_at`) düşük maliyetli alternatif.

### 7.2 Partitioning

Yüksek hacimli tablolar **RANGE partition (`created_at`, aylık)**:

| Tablo | Partition | Gerekçe |
|-------|-----------|---------|
| call, call_leg, transcript, transcript_segment, recording | aylık RANGE | sorgu sıcak-pencere; retention `DETACH/DROP PARTITION` ile ucuz silme (§9) |
| call_event, tool_execution | aylık RANGE | en yüksek yazım hacmi; eski partition arşive |
| usage_record | aylık RANGE | OLAP'a aktarım sonrası eski partition drop |
| audit_log | aylık RANGE | WORM; retention süresi sonuna kadar tutulur, sonra partition drop |

- **PK + partition anahtarı:** Partition'lı tablolarda PK partition kolonunu içerir: `(id, created_at)`.
  FK'ler (ör. `transcript.call_id → call`) uygulama/mantıksal düzeyde tutulur (PostgreSQL partition'lı
  tabloya gelen FK'lerde kısıt var); referans bütünlüğü servis katmanında + `call_id` indeksleriyle.
- **Dedicated tenant:** Çok büyük tek tenant için partition altında **LIST/HASH (tenant_id)** alt-bölümleme
  (sub-partition) opsiyonu — noisy-neighbor I/O izolasyonu (ADR-006, NFR 10.3).
- **Otomasyon:** Gelecek partition'lar `pg_partman` benzeri job ile önceden oluşturulur; eskiler retention
  motoru tarafından `DROP`/arşivlenir.

---

## 8. Veri Yerleşimi (Residency) ve Şifreleme

- **Home-region (NFR 10.7, SAD §12.3):** `tenant.home_region`; tenant'ın ses kaydı, transkript, prompt,
  KB, analitik, audit, backup ve sağlayıcıya gönderilen içerik o bölgede kalır. Bölgesel olarak ayrı
  PostgreSQL cluster'ları; cross-region replikasyon yalnız aynı residency sınıfında (DR, §19).
- **Region kolonu:** `call.region`, `organisation_unit.region`, `sip_trunk.region`, `phone_number.region`
  ile satır seviyesinde residency izlenir; panelde gösterilir (NFR 10.7).
- **Şifreleme at rest:** Depolama AES-256; **tenant başına KMS key** (`tenant.kms_key_ref`, NFR 10.6).
  BYOK/customer-managed key Faz 3 (ADR / NFR 10.6).
- **PII ayrıştırma (P6):** Ham ses (`recording`) ve tam transkript metni nesne depoda (tenant bucket/prefix
  + KMS); DB yalnız `storage_uri` + metadata + `redaction_state` tutar. Kart/parola/OTP DB'ye hiç yazılmaz
  (FR-REC-005). Hassas DB kolonları için gerekirse `pgcrypto` ile kolon şifreleme.
- **Maskeleme:** Panel görüntülemesinde PII maskelenir (BRD §17.7); `contact.attributes`,
  `transcript_segment.text` view/uygulama katmanında maskelenmiş sunulur.

---

## 9. Retention, Legal Hold ve Geri Döndürülemez Silme

- **Politika kaynağı:** `retention_policy` (tenant + data_class → `retain_days`), `tenant.retention_profile`
  / `compliance_profile` ile beslenir (FR-TEN-004, FR-REC-006).
- **Geri döndürülemez silme (FR-REC-010):** Retention motoru (WBS 1.2.3) süresi dolan veriyi siler:
  - Partition'lı tablolarda `DETACH` + `DROP PARTITION` (toplu, ucuz, geri dönüşsüz).
  - Nesne depo objeleri (ses/transkript) lifecycle + crypto-shredding (KMS key sürümü iptali).
- **Legal hold (FR-REC-007):** `legal_hold.active = true` ya da `recording.legal_hold = true` olan kayıt
  retention'dan muaftır; silme job'u `WHERE legal_hold = false` partial index'iyle bunları atlar.
- **Audit (FR-REC-009):** Her silme/erişim `audit_log`'a yazılır (WORM); silme işlemi de denetlenebilir.
- **WORM saklama:** `audit_log` ve `consent` retention süresi boyunca değişmez; süre sonunda yalnız
  yasal saklama bittiğinde partition drop.

---

## 10. Migration ve Şema Versiyonlama

- **Araç:** Versiyonlu, ileri-yönlü migration (ör. Alembic/sqitch sınıfı; vendor-neutral). Her migration
  idempotent ve geri-alınabilir (down script).
- **Dairesel FK:** `agent.active_version_id ↔ agent_version.agent_id` dairesel referans; tablolar önce
  FK'siz oluşturulur, FK ayrı migration adımında `ALTER TABLE ... ADD CONSTRAINT` ile eklenir.
- **RLS migration:** Tablo + politika + grant aynı migration'da; yeni iş verisi tablosu **RLS olmadan
  merge edilemez** (CI kontrolü — WBS 0.4.4 / 12.2.3 tenant izolasyon testi).
- **Partition bakımı:** Partition oluşturma/drop ayrı operasyonel job; şema migration'dan bağımsız.
- **Genişletmeler:** `uuid`/UUIDv7 üreteci, `pgvector`, `citext`, `pgcrypto` extension'ları baz migration'da.

---

## 11. İzlenebilirlik (FR/SR Eşlemesi)

| Tasarım kararı | Kaynak |
|----------------|--------|
| Her iş verisi tablosunda `tenant_id` + RLS | FR-TEN-002, SAD §13.1, RTM `SR-TEN-*` |
| L0 iş verisi izolasyonu + üç katmanlı break-glass | FR-IAM-008/009/010, SAD §14.4.2 |
| RBAC immutable bundle + scoped assignment | FR-IAM-001/011, ADR-012, SAD §14.4.3 |
| WORM audit log + bütünlük | FR-IAM-006, FR-REC-009 |
| Agent Version immutability + rollback | FR-AGT-005/006 |
| Consent alanları (amaç/ülke/kaynak/tarih/kapsam/İYS) | FR-OUT-003, BRD §14.3 |
| DNC/suppression | FR-TEL-014, FR-OUT-006 |
| Recording/Transcript pointer + redaction state | FR-REC-003/004/005 |
| Retention + legal hold + geri döndürülemez silme | FR-REC-006/007/010 |
| Tool Execution idempotency + correlation | FR-TOOL-009/010 |
| correlation_id her çağrı/olay | BRD §15, SAD §13.3/§17.1 |
| Usage/Resource per-call ölçümü | FR-BIL-001/002, FR-RES-016, FR-ANA-013 |
| Residency (home-region) + tenant KMS key | NFR 10.6/10.7, SAD §12.3 |
| pgvector KB namespace (tenant+agent) | FR-KB-004/005/010 |
| Partition ile retention + density | NFR 10.3/10.5 |

> Tam FR↔SR↔TC↔WBS izlenebilirliği `docs/RTM.md`'dedir; bu doküman WBS **0.1.3** çıktısıdır ve
> WBS 1.1.1–1.1.4 (fiziksel şema implementasyonu) için tasarım temelidir.

---

## 12. Açık Kararlar ve Sonraki Adımlar

**Açık kararlar (kaynak doküman netleşince güncellenir):**
- **Embedding boyutu** (`kb_chunk.embedding VECTOR(n)`): seçilen embedding modeline bağlı (WBS 0.2.5 vendor
  eval + ADR). Şu an 1536 referans değer.
- **Vector store:** pgvector vs OpenSearch (SAD §12.1, WBS 0.2.5); pgvector ise bu şema, OpenSearch ise
  `kb_chunk` yalnız metadata tutar. **WBS 1.1.7** (migration 0010/0011) bu ikiliği tek şemada uygular:
  pgvector kuruluysa `kb_chunk.embedding VECTOR(1536)` + HNSW ANN koşullu eklenir; değilse `kb_chunk`
  metadata-only kalır (embedding harici depo / OpenSearch yolu). Namespace izolasyonu (FR-KB-004) her iki
  modda da tenant RLS + namespace/kb_id + kompozit tenant FK ile aynıdır.
- **Retention süreleri** (BRD §22 açık karar): `retention_policy.retain_days` varsayılanları compliance
  profile başına netleşecek.
- **Partition periyodu** (aylık vs haftalık): hacim ölçümüne göre (WBS 0.3.3 density PoC sonrası).

**Sonraki adımlar:**
- **0.1.4** API tasarım dokümanı (OpenAPI + adapter SPI) — bu şemayı sözleşmelere bağlar.
- **WBS 1.1.1–1.1.4 + 1.1.7** — bu tasarımın migration'larla fiziksel implementasyonu (KB/vector store: 0010/0011).
- **WBS 1.2.1** RLS politikalarının her tabloya uygulanması + **12.2.3** tenant izolasyon testi.
- **WBS 1.1.9** OLAP analitik şema bu OLTP şemadan türetilir.

---

*Bu doküman `docs/BRD.md` (v2.1), `docs/SAD.md` (v1.1) ve `docs/SRS.md` (v1.0) ile birlikte okunmalıdır.
Çelişkide BRD/SAD esastır.*
