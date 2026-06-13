-- =============================================================================
-- Migration 0007 — DOWN. RLS politikalarını ve grant'leri geri al.
-- =============================================================================

DROP POLICY IF EXISTS tenant_isolation ON tool_execution;
DROP POLICY IF EXISTS tenant_isolation ON call_event;
DROP POLICY IF EXISTS tenant_isolation ON recording;
DROP POLICY IF EXISTS tenant_isolation ON transcript_segment;
DROP POLICY IF EXISTS tenant_isolation ON transcript;
DROP POLICY IF EXISTS tenant_isolation ON call_leg;
DROP POLICY IF EXISTS tenant_isolation ON call;

ALTER TABLE IF EXISTS tool_execution     NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS tool_execution     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call_event         NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call_event         DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS recording          NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS recording          DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS transcript_segment NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS transcript_segment DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS transcript         NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS transcript         DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call_leg           NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call_leg           DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call               NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call               DISABLE ROW LEVEL SECURITY;

REVOKE ALL ON call, call_leg, transcript, transcript_segment,
              recording, call_event, tool_execution FROM app_rw;
