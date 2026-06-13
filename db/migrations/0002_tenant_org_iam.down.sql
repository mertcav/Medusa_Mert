-- =============================================================================
-- Migration 0002 — DOWN. Tabloları bağımlılık ters sırasında düşür.
-- =============================================================================

DROP TABLE IF EXISTS user_role_assignment;
DROP TABLE IF EXISTS role_permission;
DROP TABLE IF EXISTS permission_key;
DROP TABLE IF EXISTS role;
DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS organisation_unit;
DROP TABLE IF EXISTS tenant;
