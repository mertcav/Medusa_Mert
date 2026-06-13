-- =============================================================================
-- Migration 0003 — Row-Level Security (Tenant, Org Unit, User, Role)
-- WBS 1.1.1 / 1.2.1 · F1 · Must · →FR-TEN-002, SAD §13.1, ADR-006 · DB.md §6
--
-- İzolasyon iki katmanlı (DB.md §6.1, P2 defense-in-depth): uygulama her isteğe
-- tenant scope uygular VE PostgreSQL RLS aynı tenant_id'yi bağımsız zorlar.
--
-- Oturum sözleşmesi (uygulama transaction başında set eder — DB.md §6.1):
--   SET LOCAL app.tenant_id = '<uuid>';   -- tenant realm (L1/L2)
--   SET LOCAL app.platform  = 'on';       -- platform realm (L0)
-- current_setting(..., true) → GUC yoksa NULL → karşılaştırma false →
-- HİÇBİR satır görünmez (FAIL-CLOSED). Scope'u unutmak veriyi açmaz, kapatır.
--
-- Uygulama RLS'i bypass etmeyen app_rw rolüyle bağlanır (0001). FORCE RLS ile
-- tablo sahibi de politikaya tabidir.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) tenant (Root) — tenant kullanıcısı yalnız kendi satırını görür; platform
--    tümünü görür. Yazım (provisioning) yalnız platform realm (DB.md §6.3).
-- -----------------------------------------------------------------------------
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_self ON tenant
    USING (
        id = current_setting('app.tenant_id', true)::uuid
        OR current_setting('app.platform', true) = 'on'
    )
    WITH CHECK (
        current_setting('app.platform', true) = 'on'   -- tenant CRUD = L0 provisioning (FR-TEN-001)
    );

-- -----------------------------------------------------------------------------
-- 2) organisation_unit — standart tenant izolasyonu (DB.md §6.2).
-- -----------------------------------------------------------------------------
ALTER TABLE organisation_unit ENABLE ROW LEVEL SECURITY;
ALTER TABLE organisation_unit FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON organisation_unit
    USING      (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- -----------------------------------------------------------------------------
-- 3) app_user — tenant kullanıcıları standart izolasyon; platform (tenant_id
--    NULL) kullanıcıları yalnız platform realm görür/yönetir (DB.md §6.3 karışık
--    desen — aksi halde NULL satırlar fail-closed altında kimseye görünmez ve L0
--    kullanıcı yönetimi kilitlenirdi).
-- -----------------------------------------------------------------------------
ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_user FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON app_user
    USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on')
    )
    WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on')
    );

-- -----------------------------------------------------------------------------
-- 4b) user_role_assignment — tenant atamaları izolasyon; platform atamaları
--     (tenant_id NULL) platform realm (app_user ile aynı karışık desen).
-- -----------------------------------------------------------------------------
ALTER TABLE user_role_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_role_assignment FORCE  ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON user_role_assignment
    USING (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on')
    )
    WITH CHECK (
        tenant_id = current_setting('app.tenant_id', true)::uuid
        OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on')
    );

-- =============================================================================
-- Grant'ler (DB.md §6.1, §6.3)
-- =============================================================================

-- İş verisi tabloları: app_rw CRUD yapar; RLS satır görünürlüğünü sınırlar.
GRANT SELECT, INSERT, UPDATE, DELETE ON tenant               TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON organisation_unit    TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON app_user             TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_role_assignment TO app_rw;

-- Global / referans tabloları (role, permission_key, role_permission): RLS YOK,
-- salt-okunur (DB.md §6.3). Yazım yalnız platform migration. app_rw write alamaz.
REVOKE ALL                  ON role            FROM app_rw;
REVOKE ALL                  ON permission_key  FROM app_rw;
REVOKE ALL                  ON role_permission FROM app_rw;
GRANT  SELECT               ON role            TO   app_rw;
GRANT  SELECT               ON permission_key  TO   app_rw;
GRANT  SELECT               ON role_permission TO   app_rw;
