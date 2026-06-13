-- =============================================================================
-- Migration 0005 — Row-Level Security (Agent ve Yapılandırma)
-- WBS 1.1.2 / 1.2.1 · F1 · Must · →FR-TEN-002, SAD §13.1, ADR-006 · DB.md §6
--
-- Kapsamdaki 7 tablo da saf tenant-scoped (tenant_id NOT NULL) → standart
-- `tenant_isolation` politikası (DB.md §6.2/§6.3). İzolasyon iki katmanlı:
-- uygulama tenant scope uygular VE RLS aynı tenant_id'yi bağımsız zorlar.
--
-- Oturum sözleşmesi (0003 ile aynı): transaction başında
--   SET LOCAL app.tenant_id = '<uuid>';
-- current_setting(..., true) → GUC yoksa NULL → 0 satır (FAIL-CLOSED).
--
-- agent_version ek olarak WORM/append-only (DB.md §6.5): app_rw yalnız
-- INSERT+SELECT alır; UPDATE/DELETE grant düzeyinde de reddedilir (0004'teki
-- trigger yedek güvence).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Standart tenant izolasyonu — 7 tablo (DB.md §6.2).
-- -----------------------------------------------------------------------------
ALTER TABLE agent             ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent             FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agent
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE agent_version     ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_version     FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON agent_version
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE prompt            ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt            FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON prompt
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE conversation_flow ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_flow FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON conversation_flow
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE voice_profile     ENABLE ROW LEVEL SECURITY;
ALTER TABLE voice_profile     FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON voice_profile
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE model_profile     ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_profile     FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON model_profile
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

ALTER TABLE stt_profile       ENABLE ROW LEVEL SECURITY;
ALTER TABLE stt_profile       FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stt_profile
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- =============================================================================
-- Grant'ler (DB.md §6.1, §6.5)
-- =============================================================================

-- Mutable config tabloları: app_rw CRUD; RLS satır görünürlüğünü sınırlar.
GRANT SELECT, INSERT, UPDATE, DELETE ON agent             TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON prompt            TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON conversation_flow TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON voice_profile     TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON model_profile     TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON stt_profile       TO app_rw;

-- agent_version: WORM/append-only (DB.md §6.5). Yalnız INSERT+SELECT — rollback =
-- yeni satır. UPDATE/DELETE hem grant'te reddedilir hem trigger'la (0004) yedeklenir.
REVOKE ALL            ON agent_version FROM app_rw;
GRANT  SELECT, INSERT ON agent_version TO   app_rw;
