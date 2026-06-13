-- =============================================================================
-- Migration 0007 — Row-Level Security (Çağrı ve Etkileşim)
-- WBS 1.1.3 / 1.2.1 · F1 · Must · →FR-TEN-002, SAD §13.1, ADR-006 · DB.md §6
--
-- Kapsamdaki 7 tablo da saf tenant-scoped (tenant_id NOT NULL) → standart
-- `tenant_isolation` politikası (DB.md §6.2/§6.3). İzolasyon iki katmanlı:
-- uygulama tenant scope uygular VE RLS aynı tenant_id'yi bağımsız zorlar.
--
-- Partition'lı tabloda RLS parent'ta ENABLE+FORCE edilir; politika tüm
-- partition'lara (DEFAULT + aylık) uygulama parent üzerinden erişildiğinde
-- zorlanır. Grant'ler de parent üzerinden propagate olur.
--
-- Oturum sözleşmesi (0003/0005 ile aynı): transaction başında
--   SET LOCAL app.tenant_id = '<uuid>';
-- NULLIF(current_setting('app.tenant_id', true), '')::uuid → GUC yoksa (NULL) VEYA
-- bağlantı havuzunda SET LOCAL sonrası placeholder boş-string'e ('') döndüğünde
-- karşılaştırma NULL → 0 satır (FAIL-CLOSED). Çıplak `::uuid` boş-string'i hata
-- fırlatarak değil, NULLIF ile sessizce kapatır (DB.md §6.2).
--
-- tool_execution ek olarak WORM/append-only (DB.md §6.5, P4): app_rw yalnız
-- INSERT+SELECT alır; UPDATE/DELETE grant düzeyinde de reddedilir (0006'daki
-- trigger yedek güvence).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Standart tenant izolasyonu — 7 tablo (DB.md §6.2).
-- -----------------------------------------------------------------------------
ALTER TABLE call               ENABLE ROW LEVEL SECURITY;
ALTER TABLE call               FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON call
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE call_leg           ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_leg           FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON call_leg
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE transcript         ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript         FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON transcript
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE transcript_segment ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcript_segment FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON transcript_segment
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE recording          ENABLE ROW LEVEL SECURITY;
ALTER TABLE recording          FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON recording
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE call_event         ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_event         FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON call_event
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE tool_execution     ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_execution     FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tool_execution
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- =============================================================================
-- Grant'ler (DB.md §6.1, §6.5)
-- =============================================================================

-- Mutable çağrı/etkileşim tabloları: app_rw CRUD; RLS satır görünürlüğünü sınırlar.
-- (Geri döndürülemez toplu silme retention motorunda DROP PARTITION ile — DB.md §9.)
GRANT SELECT, INSERT, UPDATE, DELETE ON call               TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON call_leg           TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON transcript         TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON transcript_segment TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON recording          TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON call_event         TO app_rw;

-- tool_execution: WORM/append-only (DB.md §6.5, P4). Yalnız INSERT+SELECT — işlem
-- kaydı yazıldıktan sonra değişmez. UPDATE/DELETE hem grant'te reddedilir hem
-- trigger'la (0006) yedeklenir.
REVOKE ALL            ON tool_execution FROM app_rw;
GRANT  SELECT, INSERT ON tool_execution TO   app_rw;
