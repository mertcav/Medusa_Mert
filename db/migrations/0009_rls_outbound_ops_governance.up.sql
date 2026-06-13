-- =============================================================================
-- Migration 0009 — Row-Level Security (Outbound, Operasyon, Yönetişim)
-- WBS 1.1.4 / 1.2.1 · F2 · Must · →FR-TEN-002, SAD §13.1 · DB.md §6
--
-- İki politika sınıfı (DB.md §6.3):
--   • Saf tenant-scoped (tenant_id NOT NULL) → standart `tenant_isolation`:
--     campaign, contact, consent, call_evaluation, usage_record.
--   • "Platform + tenant karışık" (tenant_id NULL'lanabilir) → `tenant_or_platform`:
--     audit_log, incident. Tenant kendi satırını görür; platform realm yalnız
--     platform (tenant_id IS NULL) satırlarını görür → altın kural (L0 tenant iş
--     verisini varsayılan görmez) korunur.
--
-- Oturum sözleşmesi (0003/0005/0007 ile aynı): transaction başında
--   SET LOCAL app.tenant_id = '<uuid>';   (tenant realm)
--   SET LOCAL app.platform  = 'on';       (platform realm)
-- NULLIF(current_setting('app.tenant_id', true), '')::uuid → GUC yoksa (NULL) VEYA
-- bağlantı havuzunda SET LOCAL sonrası placeholder boş-string'e ('') döndüğünde
-- karşılaştırma NULL → 0 satır (FAIL-CLOSED, DB.md §6.2).
--
-- consent + audit_log WORM/append-only (DB.md §6.5, P4): app_rw yalnız INSERT+SELECT;
-- UPDATE/DELETE grant düzeyinde de reddedilir (0008'deki trigger yedek güvence).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Sınıf 1 — standart tenant izolasyonu (5 tablo, DB.md §6.2).
-- -----------------------------------------------------------------------------
ALTER TABLE campaign        ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign        FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON campaign
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE contact         ENABLE ROW LEVEL SECURITY;
ALTER TABLE contact         FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON contact
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE consent         ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent         FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON consent
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE call_evaluation ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_evaluation FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON call_evaluation
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE usage_record    ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_record    FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON usage_record
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- -----------------------------------------------------------------------------
-- Sınıf 2 — platform + tenant karışık (2 tablo, DB.md §6.3).
-- Tenant realm: kendi tenant_id'li satırlar. Platform realm: yalnız tenant_id IS
-- NULL (platform geneli) satırlar — tenant iş verisi varsayılan görünmez (altın kural).
-- WITH CHECK aynı koşulu insert/update'te zorlar (cross-tenant + sahte-platform write koruması).
-- -----------------------------------------------------------------------------
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_or_platform ON audit_log
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on'))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on'));

ALTER TABLE incident  ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident  FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_or_platform ON incident
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on'))
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                OR (tenant_id IS NULL AND current_setting('app.platform', true) = 'on'));

-- =============================================================================
-- Grant'ler (DB.md §6.1, §6.5)
-- =============================================================================

-- Mutable tablolar: app_rw CRUD; RLS satır görünürlüğünü sınırlar.
-- (usage_record geri döndürülemez toplu silme retention motorunda DROP PARTITION — DB.md §9.)
GRANT SELECT, INSERT, UPDATE, DELETE ON campaign        TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON contact         TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON call_evaluation TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON usage_record    TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON incident        TO app_rw;

-- WORM/append-only (DB.md §6.5, P4): consent + audit_log yalnız INSERT+SELECT —
-- yazıldıktan sonra değişmez. UPDATE/DELETE hem grant'te reddedilir hem trigger'la
-- (0008) yedeklenir. (consent: opt-out = yeni satır; audit_log: hash-chain bütünlük.)
REVOKE ALL            ON consent   FROM app_rw;
GRANT  SELECT, INSERT ON consent   TO   app_rw;
REVOKE ALL            ON audit_log FROM app_rw;
GRANT  SELECT, INSERT ON audit_log TO   app_rw;
