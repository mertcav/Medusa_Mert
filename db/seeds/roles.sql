-- =============================================================================
-- Seed — Global immutable rol kümesi (sabit bundle)
-- WBS 1.1.1 · →FR-IAM-011, ADR-012 · CLAUDE.md "RBAC rol seti"
--
-- role GLOBAL/immutable'dır (tenant_id yok). Roller yalnız platform migration ile
-- yazılır (DB.md §6.3). Permission-key kataloğu + bundle eşlemesi WBS 12.1.2'de
-- doldurulur; burada yalnız sabit rol kodları ve panel seviyeleri tohumlanır.
-- Idempotent: ON CONFLICT DO NOTHING.
-- =============================================================================

INSERT INTO role (code, level, is_immutable) VALUES
    -- L0 — Platform Admin Console (RMC, cross-tenant)
    ('platform_owner',              'L0',   true),
    ('platform_sre',                'L0',   true),
    ('platform_billing',            'L0',   true),
    -- L1 — Tenant Admin Console
    ('tenant_owner',                'L1L2', true),   -- L1+L2 erişim
    ('tenant_admin',                'L1',   true),
    ('security_compliance_officer', 'L1',   true),
    ('billing_viewer',              'L1',   true),
    ('api_developer',               'L1L2', true),   -- L1+L2 erişim
    -- L2 — Operasyon / Uygulama Paneli
    ('operations_manager',          'L2',   true),
    ('conversation_designer',       'L2',   true),
    ('qa_analyst',                  'L2',   true),
    ('human_agent',                 'L2',   true)
ON CONFLICT (code) DO NOTHING;
