-- =============================================================================
-- Migration 0009 — DOWN. RLS politikalarını ve grant'leri geri al.
-- =============================================================================

DROP POLICY IF EXISTS tenant_or_platform ON incident;
DROP POLICY IF EXISTS tenant_or_platform ON audit_log;
DROP POLICY IF EXISTS tenant_isolation   ON usage_record;
DROP POLICY IF EXISTS tenant_isolation   ON call_evaluation;
DROP POLICY IF EXISTS tenant_isolation   ON consent;
DROP POLICY IF EXISTS tenant_isolation   ON contact;
DROP POLICY IF EXISTS tenant_isolation   ON campaign;

ALTER TABLE IF EXISTS incident        NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS incident        DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS audit_log       NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS audit_log       DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS usage_record    NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS usage_record    DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call_evaluation NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS call_evaluation DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS consent         NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS consent         DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS contact         NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS contact         DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS campaign        NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS campaign        DISABLE ROW LEVEL SECURITY;

REVOKE ALL ON campaign, contact, consent, call_evaluation,
              usage_record, audit_log, incident FROM app_rw;
