-- =============================================================================
-- Migration 0011 — Row-Level Security (Bilgi Tabanı / Vector Store namespace)
-- WBS 1.1.7 / 1.2.1 · F1 · Must · →FR-KB-004, FR-TEN-002, ADR-006 · DB.md §6
--
-- Kapsamdaki 3 tablo da saf tenant-scoped (tenant_id NOT NULL) → standart
-- `tenant_isolation` politikası (DB.md §6.2). cross-tenant izolasyonu RLS, cross-agent
-- izolasyonu namespace/kb_id + kompozit FK (0010) zorlar — birlikte FR-KB-004.
--
-- Oturum sözleşmesi (0003/0005/0007 ile aynı): transaction başında
--   SET LOCAL app.tenant_id = '<uuid>';
-- NULLIF(current_setting(..., true), '')::uuid → GUC yoksa (NULL) VEYA havuzda
-- SET LOCAL sonrası placeholder '' döndüğünde → 0 satır (FAIL-CLOSED). DB.md §6.2.
--
-- KB içeriği WORM değildir: yeniden ingest sürüm üretir (FR-KB-003), bayatlayan
-- içerik silinir/işaretlenir (FR-KB-008) → app_rw tam CRUD. Platform realm KB
-- içeriğini varsayılan göremez (altın kural; saf tenant-scoped, platform OR'u yok).
-- =============================================================================

ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON knowledge_base
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE kb_document    ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_document    FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON kb_document
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE kb_chunk       ENABLE ROW LEVEL SECURITY;
ALTER TABLE kb_chunk       FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON kb_chunk
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- Grant'ler (DB.md §6.1): mutable KB tabloları app_rw CRUD; RLS satır görünürlüğünü
-- sınırlar. WORM yok (re-ingest/staleness silme gerektirir).
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_base TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON kb_document    TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON kb_chunk       TO app_rw;
