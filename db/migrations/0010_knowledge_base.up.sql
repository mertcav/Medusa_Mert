-- =============================================================================
-- Migration 0010 — Bilgi Tabanı + Vector Store namespace (şema)
-- WBS 1.1.7 · F1 · Must · →BRD §16 (12–14), FR-KB-004/005/008/010, SAD §10.2/§12.1
--   · DB.md §5.3 (KB), §7.1 (HNSW), §12 (pgvector vs OpenSearch)
--
-- Kapsam (DB.md §4 varlık 12–14): knowledge_base · kb_document · kb_chunk.
-- Çekirdek invariant: tenant + agent bazında izole **namespace** (FR-KB-004) —
-- bir agent'ın retrieval'i başka agent/tenant namespace'ini GÖREMEZ. İki katman:
--   1) tenant_id NOT NULL + RLS (0011) — cross-tenant izolasyon (FR-TEN-002).
--   2) namespace + kb_id (agent'a bağlı) — cross-agent izolasyon (FR-KB-004).
-- Defense-in-depth: kb_document/kb_chunk → knowledge_base bağı **kompozit
-- tenant-kapsamlı FK** ile kurulur (tenant_id, kb_id) → (tenant_id, id); FK
-- doğrulaması RLS'i bypass ettiğinden, bu kompozit FK bir chunk'ın BAŞKA tenant'ın
-- KB'sine bağlanmasını yapısal olarak imkânsız kılar (FR-KB-004/FR-TEN-002).
--
-- Vendor-neutral (ADR-002, DB.md §12): pgvector kuruluysa kb_chunk.embedding
-- (vector) + HNSW ANN indeksi eklenir; değilse kb_chunk **metadata-only** kalır
-- (embedding harici vektör deposunda / OpenSearch yolu). Şema her iki modda da
-- geçerli; seçim 0.2.6 (provizyonel) + canlı PoC'a bağlı.
--
-- Bağımlı: 0001 (gen_uuid_v7), 0002 (tenant), 0004 (agent). RLS ayrı migration:
-- 0011_rls_knowledge_base.up.sql. İleri-yönlü ve idempotent (DB.md §10).
-- =============================================================================

-- pgvector: varsa etkinleştir; yoksa metadata-only fallback (DB.md §12). CREATE
-- EXTENSION ayrı bir alt-işlemde denenir; binary kurulu değilse migration düşmez.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
    RAISE NOTICE 'pgvector etkin: kb_chunk.embedding vector(1536) + HNSW ANN indeksi eklenecek.';
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector kurulu değil: kb_chunk metadata-only (harici vektör deposu / OpenSearch yolu, DB.md §12). embedding kolonu + HNSW atlanır.';
END;
$$;

-- 12) Knowledge Base — tenant+agent izolasyon namespace'i (FR-KB-004).
--     agent_id NULL => tenant geneli paylaşılan KB (agent'a bağlı değil).
--     namespace = retrieval kapsam anahtarı; konvansiyon: 't:<tenant_id>/a:<agent_id>'
--     veya 't:<tenant_id>/shared' (uygulama atar; UNIQUE (tenant_id, namespace) zorlar).
CREATE TABLE knowledge_base (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    agent_id    UUID REFERENCES agent(id) ON DELETE RESTRICT,    -- NULL => tenant-shared (FR-KB-004)
    name        TEXT NOT NULL,
    namespace   TEXT NOT NULL CHECK (length(namespace) > 0),     -- tenant+agent izolasyon namespace (FR-KB-004)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, namespace),
    UNIQUE (tenant_id, id)             -- kompozit tenant-kapsamlı FK hedefi (defense-in-depth)
);
COMMENT ON TABLE knowledge_base IS 'BRD §16 (12) Knowledge Base — tenant+agent izolasyon namespace. DB.md §5.3, FR-KB-004.';
COMMENT ON COLUMN knowledge_base.namespace IS 'Retrieval kapsam anahtarı (tenant+agent); cross-namespace sonuç yok (FR-KB-004/FR-TEN-002).';
CREATE INDEX ix_kb_tenant ON knowledge_base (tenant_id);
CREATE INDEX ix_kb_agent  ON knowledge_base (agent_id);

-- 13) KB Document — kaynak doküman pointer + doküman-bazında erişim/bayatlama/hassaslık.
--     Kompozit FK (tenant_id, kb_id) => chunk/doc aynı tenant'ın KB'sine bağlı kalır.
CREATE TABLE kb_document (
    id             UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    kb_id          UUID NOT NULL,
    source_uri     TEXT,                            -- nesne depo pointer (objstore, WBS 1.1.6)
    access_scope   JSONB,                           -- doküman bazında erişim yetkisi (FR-KB-005)
    version_no     INTEGER NOT NULL DEFAULT 1,      -- yeniden ingest sürüm üretir (FR-KB-003)
    content_ttl_at TIMESTAMPTZ,                     -- bayatlama / içerik TTL (FR-KB-008)
    is_sensitive   BOOLEAN NOT NULL DEFAULT false,  -- sağlayıcı loguna gitmez (FR-KB-010)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, id),            -- kb_chunk kompozit FK hedefi
    FOREIGN KEY (tenant_id, kb_id) REFERENCES knowledge_base (tenant_id, id) ON DELETE RESTRICT
);
COMMENT ON TABLE kb_document IS 'BRD §16 (13) KB Document — kaynak doküman + ACL/TTL/hassaslık. DB.md §5.3, FR-KB-005/008/010.';
CREATE INDEX ix_kbdoc_kb        ON kb_document (tenant_id, kb_id);
CREATE INDEX ix_kbdoc_ttl       ON kb_document (content_ttl_at) WHERE content_ttl_at IS NOT NULL;  -- bayatlama taraması (FR-KB-008)
CREATE INDEX ix_kbdoc_sensitive ON kb_document (tenant_id) WHERE is_sensitive = true;               -- no-log filtre (FR-KB-010)

-- 14) KB Chunk — parçalanmış içerik + (pgvector varsa) embedding. kb_id denormalize
--     (hızlı namespace filtresi); document_id + kb_id ikisi de tenant-kompozit FK'li.
CREATE TABLE kb_chunk (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    kb_id        UUID NOT NULL,
    document_id  UUID NOT NULL,
    chunk_no     INTEGER NOT NULL,
    content      TEXT NOT NULL,
    -- embedding vector(1536): pgvector varsa aşağıdaki DO bloğunda eklenir (metadata-only fallback).
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, document_id, chunk_no),
    FOREIGN KEY (tenant_id, kb_id)       REFERENCES knowledge_base (tenant_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (tenant_id, document_id) REFERENCES kb_document    (tenant_id, id) ON DELETE RESTRICT
);
COMMENT ON TABLE kb_chunk IS 'BRD §16 (14) KB Chunk — parça + embedding (pgvector). DB.md §5.3/§7.1, FR-KB-003/004; SAD §10.2.';
CREATE INDEX ix_kbchunk_kb  ON kb_chunk (tenant_id, kb_id);        -- namespace filtreli retrieval (FR-KB-004)
CREATE INDEX ix_kbchunk_doc ON kb_chunk (tenant_id, document_id); -- doküman silme/yeniden indeksleme (FR-KB-003/008)

-- pgvector koşullu: embedding kolonu (vector(1536)) + HNSW ANN indeksi (top-k retrieval,
-- SAD §10.2/§20). Boyut model-bağımlı referans değer 1536 (DB.md §12, 0.2.5 vendor eval).
-- pgvector yoksa kb_chunk metadata-only kalır (embedding harici depo / OpenSearch yolu).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        EXECUTE 'ALTER TABLE kb_chunk ADD COLUMN IF NOT EXISTS embedding vector(1536)';
        EXECUTE 'CREATE INDEX IF NOT EXISTS ix_kbchunk_ann ON kb_chunk '
             || 'USING hnsw (embedding vector_cosine_ops)';  -- cosine ANN (SAD §10.2)
        RAISE NOTICE 'kb_chunk.embedding vector(1536) + ix_kbchunk_ann (HNSW) eklendi.';
    END IF;
END;
$$;
