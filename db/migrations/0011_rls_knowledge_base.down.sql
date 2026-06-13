-- =============================================================================
-- Migration 0011 — DOWN. RLS politikalarını ve grant'leri geri al.
-- =============================================================================

DROP POLICY IF EXISTS tenant_isolation ON kb_chunk;
DROP POLICY IF EXISTS tenant_isolation ON kb_document;
DROP POLICY IF EXISTS tenant_isolation ON knowledge_base;

ALTER TABLE IF EXISTS kb_chunk       NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kb_chunk       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kb_document    NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS kb_document    DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS knowledge_base NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS knowledge_base DISABLE ROW LEVEL SECURITY;

REVOKE ALL ON knowledge_base, kb_document, kb_chunk FROM app_rw;
