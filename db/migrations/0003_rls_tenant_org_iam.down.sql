-- =============================================================================
-- Migration 0003 — DOWN. RLS politikalarını ve grant'leri geri al.
-- =============================================================================

DROP POLICY IF EXISTS tenant_isolation ON user_role_assignment;
DROP POLICY IF EXISTS tenant_isolation ON app_user;
DROP POLICY IF EXISTS tenant_isolation ON organisation_unit;
DROP POLICY IF EXISTS tenant_self      ON tenant;

ALTER TABLE IF EXISTS user_role_assignment NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS user_role_assignment DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS app_user            NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS app_user            DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS organisation_unit   NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS organisation_unit   DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS tenant              NO FORCE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS tenant              DISABLE ROW LEVEL SECURITY;

REVOKE ALL ON tenant, organisation_unit, app_user, user_role_assignment,
              role, permission_key, role_permission FROM app_rw;
