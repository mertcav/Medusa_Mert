-- =====================================================================
-- analytics/ddl/bigquery.sql — WBS 1.1.9 OLAP analitik şeması (BigQuery)
-- Kaynak doğruluk: analytics/olap-spec.json. SAD §12.1 (Analytics — kolon-bazlı OLAP).
-- Sağlayıcı-nötr (ADR-002): ddl/clickhouse.sql ile MANTIKSAL EŞ; aynı tablo grain'i,
-- partition (event_date), kümeleme (tenant_id ilk) ve retention (partition_expiration_days).
--
-- Sır/credential YAZILMAZ: proje/dataset adı yalnız ${ENV}/placeholder. Dataset `${OLAP_DS}`
-- (deployment substitüsyonu). Residency (NFR 10.7): dataset bölgesi home-region'a sabitlenir
-- (CREATE SCHEMA ... OPTIONS(location='${OLAP_REGION}')), per-region ayrı dataset.
--
-- İzolasyon: tenant_id NOT NULL + CLUSTER BY tenant_id (ilk) → pruning + tenant kapsamı.
-- Sorgu-katmanı zorunlu tenant predicate + row-access-policy (ddl/row-policy.template.sql).
-- Dedup: streaming insert + periyodik MERGE upsert (dedup_key, ingested_at version) → at-least-once
-- event stream (WBS 1.1.8 P3) replay'inde çift-sayım yok.
-- Retention: partition_expiration_days (FR-REC-006/010, retention motoru WBS 1.2.3 ile hizalı).
-- =====================================================================

-- FACT: fct_call (kaynak voice.call.lifecycle.v1)
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.fct_call`
(
    tenant_id            STRING NOT NULL,
    call_id              STRING NOT NULL,
    correlation_id       STRING,
    agent_id             STRING,
    agent_version_id     STRING,
    campaign_id          STRING,
    direction            STRING,
    started_at           TIMESTAMP,
    ended_at             TIMESTAMP,
    event_date           DATE NOT NULL,
    home_region          STRING,
    language             STRING,
    duration_sec         INT64,
    talk_sec_user        INT64,
    talk_sec_agent       INT64,
    silence_sec          INT64,
    turns                INT64,
    barge_in_count       INT64,
    intent               STRING,
    disposition          STRING,
    completion_status    STRING,
    contained            BOOL,
    transferred          BOOL,
    transfer_result      STRING,
    end_reason           STRING,
    outbound_outcome     STRING,
    flag_misinformation  BOOL,
    flag_tool_error      BOOL,
    flag_security        BOOL,
    flag_critical        BOOL,
    e2e_latency_p50_ms   INT64,
    e2e_latency_p95_ms   INT64,
    cost_total_micro     NUMERIC,
    ingested_at          TIMESTAMP,
    schema_version       INT64
)
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, agent_id, started_at
OPTIONS (partition_expiration_days = 730);

-- FACT: fct_turn (YÜKSEK HACİM; voice.turn.telemetry.v1)
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.fct_turn`
(
    tenant_id            STRING NOT NULL,
    call_id              STRING NOT NULL,
    turn_seq             INT64,
    agent_id             STRING,
    agent_version_id     STRING,
    event_date           DATE NOT NULL,
    turn_ts              TIMESTAMP,
    stt_latency_ms       INT64,
    llm_first_token_ms   INT64,
    llm_total_ms         INT64,
    tts_first_byte_ms    INT64,
    e2e_latency_ms       INT64,
    llm_tokens_in        INT64,
    llm_tokens_out       INT64,
    stt_confidence       FLOAT64,
    jitter_ms            INT64,
    packet_loss_pct      FLOAT64,
    codec                STRING,
    sip_response_code    INT64,
    barge_in             BOOL,
    silence_ms           INT64,
    retry_count          INT64,
    fallback_used        BOOL,
    provider_stt         STRING,
    provider_llm         STRING,
    provider_tts         STRING,
    provider_error       BOOL,
    ingested_at          TIMESTAMP,
    schema_version       INT64
)
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, call_id, turn_seq
OPTIONS (partition_expiration_days = 90);

-- FACT: fct_usage (NO-LOSS; billing.usage.v1)
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.fct_usage`
(
    tenant_id            STRING NOT NULL,
    call_id              STRING NOT NULL,
    agent_id             STRING,
    campaign_id          STRING,
    event_date           DATE NOT NULL,
    idempotency_key      STRING,
    plan_id              STRING,
    billed_seconds       INT64,
    billed_minutes       FLOAT64,
    cost_telecom_micro   NUMERIC,
    cost_stt_micro       NUMERIC,
    cost_tts_micro       NUMERIC,
    cost_llm_micro       NUMERIC,
    cost_platform_micro  NUMERIC,
    cost_total_micro     NUMERIC,
    provider_telecom     STRING,
    provider_stt         STRING,
    provider_tts         STRING,
    provider_llm         STRING,
    cpu_ms               INT64,
    mem_peak_mb          INT64,
    concurrency_peak     INT64,
    ingested_at          TIMESTAMP,
    schema_version       INT64
)
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, agent_id, event_date
OPTIONS (partition_expiration_days = 2555);

-- FACT: fct_qa_evaluation (qa.evaluation.v1)
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.fct_qa_evaluation`
(
    tenant_id             STRING NOT NULL,
    evaluation_id         STRING NOT NULL,
    call_id               STRING NOT NULL,
    agent_id              STRING,
    agent_version_id      STRING,
    event_date            DATE NOT NULL,
    evaluated_at          TIMESTAMP,
    auto_score            FLOAT64,
    score_accuracy        FLOAT64,
    score_compliance      FLOAT64,
    score_helpfulness     FLOAT64,
    critical_flag         BOOL,
    flag_misinformation   BOOL,
    flag_tool_error       BOOL,
    flag_security         BOOL,
    human_score           FLOAT64,
    human_comment_present  BOOL,
    evaluator_role        STRING,
    ingested_at           TIMESTAMP,
    schema_version        INT64
)
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, agent_id, event_date
OPTIONS (partition_expiration_days = 730);

-- FACT: fct_campaign_daily (campaign.events.v1)
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.fct_campaign_daily`
(
    tenant_id            STRING NOT NULL,
    campaign_id          STRING NOT NULL,
    agent_id             STRING,
    event_date           DATE NOT NULL,
    dials                INT64,
    connects             INT64,
    voicemails           INT64,
    busy                 INT64,
    no_answer            INT64,
    invalid              INT64,
    completed            INT64,
    transfers            INT64,
    avg_duration_sec     INT64,
    cost_total_micro     NUMERIC,
    ingested_at          TIMESTAMP,
    schema_version       INT64
)
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, campaign_id, event_date
OPTIONS (partition_expiration_days = 730);

-- DIMENSIONS (config plane aynası; SCD-2)
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.dim_tenant`
(
    tenant_id    STRING NOT NULL,
    name         STRING,
    plan_id      STRING,
    home_region  STRING,
    sector       STRING,
    status       STRING,
    valid_from   TIMESTAMP,
    valid_to     TIMESTAMP
)
CLUSTER BY tenant_id;

CREATE TABLE IF NOT EXISTS `${OLAP_DS}.dim_agent`
(
    tenant_id         STRING NOT NULL,
    agent_id          STRING,
    agent_version_id  STRING,
    name              STRING,
    agent_type        STRING,
    version_label     STRING,
    published_at      TIMESTAMP,
    valid_from        TIMESTAMP,
    valid_to          TIMESTAMP
)
CLUSTER BY tenant_id, agent_id;

CREATE TABLE IF NOT EXISTS `${OLAP_DS}.dim_campaign`
(
    tenant_id      STRING NOT NULL,
    campaign_id    STRING,
    name           STRING,
    campaign_type  STRING,
    status         STRING
)
CLUSTER BY tenant_id, campaign_id;

-- dim_provider / dim_date: tenant-bağımsız referans boyut (A1 istisnası).
CREATE TABLE IF NOT EXISTS `${OLAP_DS}.dim_provider`
(
    provider      STRING NOT NULL,
    category      STRING,
    display_name  STRING,
    region        STRING
)
CLUSTER BY category, provider;

CREATE TABLE IF NOT EXISTS `${OLAP_DS}.dim_date`
(
    date         DATE NOT NULL,
    year         INT64,
    month        INT64,
    week         INT64,
    day_of_week  INT64
)
CLUSTER BY date;

-- ROLLUPS — BigQuery materialized view (incremental refresh).
-- NOT: ClickHouse'un quantileState'i yerine BigQuery yaklaşık quantile için APPROX_QUANTILES
-- kullanır; MV içinde non-deterministik agregat sınırlı olduğundan p95'ler scheduled query ile
-- yenilenen tablolarda tutulabilir. Buradaki MV'ler toplam/oran metriklerini materialize eder.
CREATE MATERIALIZED VIEW IF NOT EXISTS `${OLAP_DS}.mv_call_daily`
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, agent_id
OPTIONS (partition_expiration_days = 1825) AS
SELECT
    tenant_id, agent_id, agent_version_id, event_date,
    COUNT(1)                              AS calls,
    COUNTIF(contained)                    AS contained_calls,
    COUNTIF(transferred)                  AS transferred_calls,
    COUNTIF(flag_critical)                AS critical_calls,
    SUM(cost_total_micro)                 AS cost_total_micro
FROM `${OLAP_DS}.fct_call`
GROUP BY tenant_id, agent_id, agent_version_id, event_date;

CREATE MATERIALIZED VIEW IF NOT EXISTS `${OLAP_DS}.mv_turn_latency_daily`
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, agent_id
OPTIONS (partition_expiration_days = 1825) AS
SELECT
    tenant_id, agent_id, event_date,
    COUNT(1)                AS turns,
    SUM(llm_tokens_in)      AS tokens_in_sum,
    SUM(llm_tokens_out)     AS tokens_out_sum,
    COUNTIF(provider_error) AS provider_error_sum
FROM `${OLAP_DS}.fct_turn`
GROUP BY tenant_id, agent_id, event_date;

CREATE MATERIALIZED VIEW IF NOT EXISTS `${OLAP_DS}.mv_usage_daily`
PARTITION BY DATE_TRUNC(event_date, MONTH)
CLUSTER BY tenant_id, agent_id
OPTIONS (partition_expiration_days = 1825) AS
SELECT
    tenant_id, agent_id, provider_llm AS provider, event_date,
    SUM(billed_seconds)      AS billed_seconds_sum,
    SUM(cost_telecom_micro)  AS cost_telecom_sum,
    SUM(cost_stt_micro)      AS cost_stt_sum,
    SUM(cost_tts_micro)      AS cost_tts_sum,
    SUM(cost_llm_micro)      AS cost_llm_sum,
    SUM(cost_platform_micro) AS cost_platform_sum,
    SUM(cost_total_micro)    AS cost_total_sum,
    SUM(cpu_ms)              AS cpu_ms_sum,
    MAX(mem_peak_mb)         AS mem_peak_max
FROM `${OLAP_DS}.fct_usage`
GROUP BY tenant_id, agent_id, provider, event_date;

CREATE MATERIALIZED VIEW IF NOT EXISTS `${OLAP_DS}.mv_agent_version_perf`
CLUSTER BY tenant_id, agent_id
OPTIONS (partition_expiration_days = 1825) AS
SELECT
    tenant_id, agent_id, agent_version_id,
    COUNT(1)               AS calls,
    COUNTIF(contained)     AS contained_calls,
    COUNTIF(transferred)   AS transferred_calls,
    COUNTIF(flag_critical) AS critical_calls
FROM `${OLAP_DS}.fct_call`
GROUP BY tenant_id, agent_id, agent_version_id;

-- DOWN (geri alma): DROP MATERIALIZED VIEW önce, sonra fact/dimension tabloları.
-- DROP MATERIALIZED VIEW IF EXISTS `${OLAP_DS}.mv_agent_version_perf`;
-- DROP MATERIALIZED VIEW IF EXISTS `${OLAP_DS}.mv_usage_daily`;
-- DROP MATERIALIZED VIEW IF EXISTS `${OLAP_DS}.mv_turn_latency_daily`;
-- DROP MATERIALIZED VIEW IF EXISTS `${OLAP_DS}.mv_call_daily`;
-- DROP TABLE IF EXISTS `${OLAP_DS}.fct_campaign_daily`; DROP TABLE IF EXISTS `${OLAP_DS}.fct_qa_evaluation`;
-- DROP TABLE IF EXISTS `${OLAP_DS}.fct_usage`; DROP TABLE IF EXISTS `${OLAP_DS}.fct_turn`; DROP TABLE IF EXISTS `${OLAP_DS}.fct_call`;
-- DROP TABLE IF EXISTS `${OLAP_DS}.dim_date`; DROP TABLE IF EXISTS `${OLAP_DS}.dim_provider`;
-- DROP TABLE IF EXISTS `${OLAP_DS}.dim_campaign`; DROP TABLE IF EXISTS `${OLAP_DS}.dim_agent`; DROP TABLE IF EXISTS `${OLAP_DS}.dim_tenant`;
