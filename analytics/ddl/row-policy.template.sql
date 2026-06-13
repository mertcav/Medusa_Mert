-- =====================================================================
-- analytics/ddl/row-policy.template.sql — WBS 1.1.9 tenant izolasyonu (defense-in-depth)
-- Kaynak doğruluk: analytics/olap-spec.json isolation_model. FR-TEN-002, NFR 10.7.
--
-- ÖNEMLİ — katman sırası (isolation_model):
--   (1) tenant_id NOT NULL + ORDER BY/CLUSTER ilk anahtar  → ddl/{clickhouse,bigquery}.sql
--   (2) BİRİNCİL kontrol: sorgu katmanı (Analytics API / FastAPI control plane) HER sorguya
--       zorunlu `WHERE tenant_id = :ctx` enjekte eder — istemciye GÜVENİLMEZ (DB.md §6 GUC/RLS eşi).
--   (3) BU DOSYA = defense-in-depth: motor-seviyesi ROW POLICY / row-access-policy.
--   (4) residency: per-region cluster/dataset (NFR 10.7).
--
-- Sır/credential YAZILMAZ: rol/principal/tenant değerleri yalnız ${ENV}/${PLACEHOLDER}.
-- Bu bir ŞABLONDUR: deployment, tenant↔rol eşlemesini secret/IaC'tan üretir (statik tenant listesi
-- repoya yazılmaz).

-- ---------------------------------------------------------------------
-- A) ClickHouse ROW POLICY (her tenant-kapsamlı tablo)
-- Oturum, tenant kapsamını bir SETTING ile taşır (control plane set eder, kullanıcı override edemez):
--   SET SQL_tenant_id = '<ctx-tenant-uuid>';   -- readonly profilde sabitlenir
-- Politika, satırı yalnız oturum tenant'ı ile eşleşince gösterir. Eşleşme yoksa 0 satır (fail-closed).
-- ${OLAP_DB}: veritabanı adı (env). ${APP_RO_ROLE}: analitik salt-okunur rol (env).
-- ---------------------------------------------------------------------
-- NOT: getSetting('SQL_tenant_id') boş ise eşleşme olmaz → fail-closed (tenant predicate zorunlu).

CREATE ROW POLICY IF NOT EXISTS rp_tenant_fct_call ON ${OLAP_DB}.fct_call
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_fct_turn ON ${OLAP_DB}.fct_turn
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_fct_usage ON ${OLAP_DB}.fct_usage
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_fct_qa_evaluation ON ${OLAP_DB}.fct_qa_evaluation
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_fct_campaign_daily ON ${OLAP_DB}.fct_campaign_daily
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_dim_tenant ON ${OLAP_DB}.dim_tenant
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_dim_agent ON ${OLAP_DB}.dim_agent
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

CREATE ROW POLICY IF NOT EXISTS rp_tenant_dim_campaign ON ${OLAP_DB}.dim_campaign
    FOR SELECT USING tenant_id = toUUIDOrZero(getSetting('SQL_tenant_id'))
    TO ${APP_RO_ROLE};

-- Platform (L0) salt-okunur rolü ${PLATFORM_RO_ROLE}: rollup/agregat metriği görür ama
-- tenant iş içeriği (transkript/PII) YOK — OLAP zaten ham PII tutmaz (altın kural yapısal).
-- Platform rolüne fact tablolarında satır politikası UYGULANMAZ (cross-tenant agregat için),
-- yalnız mv_* rollup'lara erişim verilir; ham fact erişimi break-glass'a tabidir (FR-IAM-008).

-- ---------------------------------------------------------------------
-- B) BigQuery row-access-policy (mantıksal eş)
-- Tenant↔grup eşlemesi IAM grubuyla (her tenant'a bir grup) yapılır; SESSION_USER()/grup üyeliği
-- ile filtre. Aşağıdaki şablon deployment'ta tenant başına üretilir (${TENANT_ID}/${TENANT_GROUP}).
-- ---------------------------------------------------------------------
-- CREATE ROW ACCESS POLICY rap_${TENANT_SLUG}_fct_call
--   ON `${OLAP_DS}.fct_call`
--   GRANT TO ('group:${TENANT_GROUP}')
--   FILTER USING (tenant_id = '${TENANT_ID}');
-- (fct_turn / fct_usage / fct_qa_evaluation / fct_campaign_daily / dim_* için tekrarlanır.)

-- Alternatif: authorized view — tenant-spesifik view yalnız kendi tenant_id'sini seçer ve
-- temel tabloya authorized erişir; tüketici yalnız view'i görür (ham tabloya erişimi yok).
-- CREATE VIEW `${OLAP_DS}.v_${TENANT_SLUG}_fct_call` AS
--   SELECT * FROM `${OLAP_DS}.fct_call` WHERE tenant_id = '${TENANT_ID}';

-- DOWN: DROP ROW POLICY rp_tenant_* ON ${OLAP_DB}.* ; (BigQuery) DROP ALL ROW ACCESS POLICIES ON ...
