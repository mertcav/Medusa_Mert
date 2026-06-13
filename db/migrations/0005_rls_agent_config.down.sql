-- =============================================================================
-- Migration 0005 — DOWN. RLS politikalarını ve grant'leri geri al.
-- =============================================================================

DROP POLICY IF EXISTS tenant_isolation ON stt_profile;
DROP POLICY IF EXISTS tenant_isolation ON model_profile;
DROP POLICY IF EXISTS tenant_isolation ON voice_profile;
DROP POLICY IF EXISTS tenant_isolation ON conversation_flow;
DROP POLICY IF EXISTS tenant_isolation ON prompt;
DROP POLICY IF EXISTS tenant_isolation ON agent_version;
DROP POLICY IF EXISTS tenant_isolation ON agent;

ALTER TABLE IF EXISTS stt_profile       NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS stt_profile       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS model_profile     NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS model_profile     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS voice_profile     NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS voice_profile     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS conversation_flow NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS conversation_flow DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS prompt            NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS prompt            DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS agent_version     NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS agent_version     DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS agent             NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS agent             DISABLE ROW LEVEL SECURITY;

REVOKE ALL ON agent, agent_version, prompt, conversation_flow,
              voice_profile, model_profile, stt_profile FROM app_rw;
