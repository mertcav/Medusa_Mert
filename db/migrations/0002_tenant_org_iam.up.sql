-- =============================================================================
-- Migration 0002 — Tenant, Organisation Unit, User, Role (şema)
-- WBS 1.1.1 · F1 · Must · →BRD §16 (1–4), SAD §13.1 · DB.md §5.1
--
-- Kapsam (DB.md §4 varlık 1–4 + türevleri):
--   tenant · organisation_unit · app_user · role · permission_key ·
--   role_permission · user_role_assignment
-- RLS politikaları ayrı migration'da: 0003_rls_tenant_org_iam.up.sql (DB.md §10
-- "yeni iş verisi tablosu RLS olmadan merge edilemez" — aynı seride gelir).
--
-- Ortak kolonlar DB.md §5: id (UUIDv7), tenant_id, created_at, updated_at,
-- row_version, deleted_at. Bağımlı: 0001 (gen_uuid_v7, set_updated_at, citext).
-- =============================================================================

-- 1) Tenant — kök varlık. Kendi id'si RLS'te self-row anahtarıdır (DB.md §6.3).
CREATE TABLE tenant (
    id                       UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    name                     TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'provisioning'
                               CHECK (status IN ('provisioning','active','suspended','terminated')),
    isolation_mode           TEXT NOT NULL DEFAULT 'shared'
                               CHECK (isolation_mode IN ('shared','dedicated')),     -- FR-TEN-005, ADR-006
    home_region              TEXT NOT NULL,                                          -- NFR 10.7
    default_locale           TEXT NOT NULL DEFAULT 'tr-TR',
    timezone                 TEXT NOT NULL DEFAULT 'Europe/Istanbul',
    retention_profile        TEXT,                                                   -- FR-TEN-004
    compliance_profile       TEXT,                                                   -- BRD §14.4
    require_tenant_approval   BOOLEAN NOT NULL DEFAULT false,                        -- FR-IAM-010 break-glass toggle
    kms_key_ref              TEXT NOT NULL,                                          -- tenant başına KMS key (NFR 10.6)
    plan_id                  UUID,                                                   -- -> pricing_plan(id) (WBS 15, FR-BIL-003)
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ,
    row_version              INTEGER NOT NULL DEFAULT 1
);
COMMENT ON TABLE tenant IS 'BRD §16 (1) Tenant — multi-tenant kök. DB.md §5.1.';

CREATE TRIGGER trg_tenant_updated_at
    BEFORE UPDATE ON tenant
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 2) Organisation Unit — marka/ülke/departman/proje (FR-TEN-003); self-ref hiyerarşi.
CREATE TABLE organisation_unit (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    parent_id   UUID REFERENCES organisation_unit(id) ON DELETE RESTRICT,
    type        TEXT NOT NULL CHECK (type IN ('brand','country','department','project')),
    name        TEXT NOT NULL,
    region      TEXT,                                                               -- residency override (NFR 10.7)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ,
    UNIQUE (tenant_id, parent_id, name)
);
COMMENT ON TABLE organisation_unit IS 'BRD §16 (2) Organisation Unit. DB.md §5.1, FR-TEN-003.';
CREATE INDEX ix_orgunit_tenant ON organisation_unit (tenant_id);
CREATE INDEX ix_orgunit_parent ON organisation_unit (parent_id);

CREATE TRIGGER trg_orgunit_updated_at
    BEFORE UPDATE ON organisation_unit
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 3) User — panel kullanıcısı. realm: L0 (platform) ayrı, L1/L2 tenant (FR-IAM-008).
CREATE TABLE app_user (
    id                    UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id             UUID REFERENCES tenant(id) ON DELETE RESTRICT,            -- NULL => platform (L0)
    realm                 TEXT NOT NULL CHECK (realm IN ('platform','tenant')),    -- FR-IAM-008
    external_idp_subject  TEXT,                                                     -- SSO subject (FR-IAM-002)
    email                 CITEXT NOT NULL,
    display_name          TEXT,
    status                TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','disabled','deprovisioned')),  -- SCIM, FR-IAM-007
    mfa_enrolled          BOOLEAN NOT NULL DEFAULT false,                           -- FR-IAM-003
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ,
    -- realm/tenant tutarlılığı: platform kullanıcısının tenant_id'si NULL,
    -- tenant kullanıcısının tenant_id'si zorunlu (FR-IAM-008 realm ayrımı).
    CONSTRAINT chk_user_realm_tenant CHECK (
        (realm = 'platform' AND tenant_id IS NULL)
        OR (realm = 'tenant' AND tenant_id IS NOT NULL)
    ),
    UNIQUE (realm, tenant_id, email)
);
COMMENT ON TABLE app_user IS 'BRD §16 (3) User. DB.md §5.1. L0 platform realm ayrı (FR-IAM-008).';
CREATE INDEX ix_user_tenant ON app_user (tenant_id) WHERE tenant_id IS NOT NULL;
CREATE INDEX ix_user_idp ON app_user (external_idp_subject);
-- Platform kullanıcılarında tenant_id NULL olduğundan (realm,tenant_id,email)
-- UNIQUE'i NULL'ları ayrı sayar; platform e-postasını benzersizleştirmek için
-- partial unique index (DB.md §5.1 niyeti: her platform kullanıcısı tek e-posta).
CREATE UNIQUE INDEX uq_user_platform_email ON app_user (email) WHERE tenant_id IS NULL;

CREATE TRIGGER trg_user_updated_at
    BEFORE UPDATE ON app_user
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 4) Role / permission — GLOBAL, immutable bundle (FR-IAM-011, ADR-012). tenant_id YOK.
CREATE TABLE role (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    code         TEXT NOT NULL UNIQUE,                                              -- 'tenant_owner', ...
    level        TEXT NOT NULL CHECK (level IN ('L0','L1','L2','L1L2')),
    is_immutable BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON TABLE role IS 'BRD §16 (4) Role — global immutable bundle. DB.md §5.1, FR-IAM-011, ADR-012.';

CREATE TABLE permission_key (
    key           TEXT PRIMARY KEY,                                                -- 'calls:read' (SAD §14.4.3)
    resource      TEXT NOT NULL,
    action        TEXT NOT NULL,
    is_own_scoped BOOLEAN NOT NULL DEFAULT false                                   -- '*:own' (BRD §17.7)
);
COMMENT ON TABLE permission_key IS 'Permission-key kataloğu (kaynak:eylem). SAD §14.4.3. Tam katalog: WBS 12.1.2.';

CREATE TABLE role_permission (
    role_id  UUID NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    perm_key TEXT NOT NULL REFERENCES permission_key(key) ON DELETE RESTRICT,
    PRIMARY KEY (role_id, perm_key)
);
COMMENT ON TABLE role_permission IS 'Role→permission-key bundle (immutable). DB.md §5.1.';

-- 4b) User Role Assignment — scoped (FR-IAM-011, ADR-012). Tenant-scoped + scope filtresi.
CREATE TABLE user_role_assignment (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID REFERENCES tenant(id) ON DELETE RESTRICT,                     -- NULL => platform atama
    user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_id     UUID NOT NULL REFERENCES role(id) ON DELETE RESTRICT,
    scope       JSONB NOT NULL DEFAULT '{}'::jsonb,                                -- {brand|department|campaign: [...]}
    assigned_by UUID REFERENCES app_user(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, user_id, role_id, scope)
);
COMMENT ON TABLE user_role_assignment IS 'Scoped role atama (rol + departman/marka/kampanya). DB.md §5.1, ADR-012.';
CREATE INDEX ix_ura_user ON user_role_assignment (user_id);
CREATE INDEX ix_ura_tenant ON user_role_assignment (tenant_id);
CREATE INDEX ix_ura_role ON user_role_assignment (role_id);
