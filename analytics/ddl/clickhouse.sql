-- =====================================================================
-- analytics/ddl/clickhouse.sql — WBS 1.1.9 OLAP analitik şeması (ClickHouse)
-- Kaynak doğruluk: analytics/olap-spec.json. SAD §12.1 (Analytics — kolon-bazlı OLAP).
-- Sağlayıcı-nötr (ADR-002): mantıksal eşi ddl/bigquery.sql. Credential-free.
--
-- Sır/credential YAZILMAZ: database/cluster adı, endpoint, kullanıcı/parola yalnız
-- ${ENV}/placeholder. Veritabanı adı `${OLAP_DB}` (deployment'ta substitüsyon).
-- Residency (NFR 10.7): her home-region için AYRI cluster/replica; bu DDL per-region uygulanır.
--
-- İzolasyon: tenant_id her fact/dimension tablosunda NOT NULL ve ORDER BY'ın İLK elemanı
-- (partition pruning + tenant kapsamı). Sorgu-katmanı zorunlu tenant predicate + ROW POLICY
-- (ddl/row-policy.template.sql) ile defense-in-depth.
-- Dedup: ReplacingMergeTree(ingested_at) + ORDER BY dedup anahtarı → at-least-once event
-- stream (WBS 1.1.8 P3) replay'inde çift-sayım yok.
-- =====================================================================

-- ---------------------------------------------------------------------
-- FACT: fct_call  (grain: tamamlanan tek çağrı; kaynak voice.call.lifecycle.v1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.fct_call
(
    tenant_id            UUID,
    call_id              UUID,
    correlation_id       String,
    agent_id             UUID,
    agent_version_id     UUID,
    campaign_id          Nullable(UUID),
    direction            LowCardinality(String),
    started_at           DateTime64(3),
    ended_at             DateTime64(3),
    event_date           Date,
    home_region          LowCardinality(String),
    language             LowCardinality(String),
    duration_sec         UInt32,
    talk_sec_user        UInt32,
    talk_sec_agent       UInt32,
    silence_sec          UInt32,
    turns                UInt16,
    barge_in_count       UInt16,
    intent               LowCardinality(String),
    disposition          LowCardinality(String),
    completion_status    LowCardinality(String),
    contained            UInt8,
    transferred          UInt8,
    transfer_result      LowCardinality(String),
    end_reason           LowCardinality(String),
    outbound_outcome     LowCardinality(String),
    flag_misinformation  UInt8,
    flag_tool_error      UInt8,
    flag_security        UInt8,
    flag_critical        UInt8,
    e2e_latency_p50_ms   UInt32,
    e2e_latency_p95_ms   UInt32,
    cost_total_micro     Decimal(18, 6),
    ingested_at          DateTime64(3),
    schema_version       UInt16
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, agent_id, started_at, call_id)
TTL event_date + INTERVAL 730 DAY
SETTINGS index_granularity = 8192;

-- ---------------------------------------------------------------------
-- FACT: fct_turn  (grain: tek tur; YÜKSEK HACİM, yalnız teknik metrik; voice.turn.telemetry.v1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.fct_turn
(
    tenant_id            UUID,
    call_id              UUID,
    turn_seq             UInt16,
    agent_id             UUID,
    agent_version_id     UUID,
    event_date           Date,
    turn_ts              DateTime64(3),
    stt_latency_ms       UInt32,
    llm_first_token_ms   UInt32,
    llm_total_ms         UInt32,
    tts_first_byte_ms    UInt32,
    e2e_latency_ms       UInt32,
    llm_tokens_in        UInt32,
    llm_tokens_out       UInt32,
    stt_confidence       Float32,
    jitter_ms            UInt32,
    packet_loss_pct      Float32,
    codec                LowCardinality(String),
    sip_response_code    UInt16,
    barge_in             UInt8,
    silence_ms           UInt32,
    retry_count          UInt16,
    fallback_used        UInt8,
    provider_stt         LowCardinality(String),
    provider_llm         LowCardinality(String),
    provider_tts         LowCardinality(String),
    provider_error       UInt8,
    ingested_at          DateTime64(3),
    schema_version       UInt16
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, call_id, turn_seq)
TTL event_date + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

-- ---------------------------------------------------------------------
-- FACT: fct_usage  (grain: kullanım/maliyet kalemi; NO-LOSS; billing.usage.v1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.fct_usage
(
    tenant_id            UUID,
    call_id              UUID,
    agent_id             UUID,
    campaign_id          Nullable(UUID),
    event_date           Date,
    idempotency_key      String,
    plan_id              UUID,
    billed_seconds       UInt32,
    billed_minutes       Float32,
    cost_telecom_micro   Decimal(18, 6),
    cost_stt_micro       Decimal(18, 6),
    cost_tts_micro       Decimal(18, 6),
    cost_llm_micro       Decimal(18, 6),
    cost_platform_micro  Decimal(18, 6),
    cost_total_micro     Decimal(18, 6),
    provider_telecom     LowCardinality(String),
    provider_stt         LowCardinality(String),
    provider_tts         LowCardinality(String),
    provider_llm         LowCardinality(String),
    cpu_ms               UInt64,
    mem_peak_mb          UInt32,
    concurrency_peak     UInt16,
    ingested_at          DateTime64(3),
    schema_version       UInt16
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, agent_id, event_date, call_id)
TTL event_date + INTERVAL 2555 DAY
SETTINGS index_granularity = 8192;

-- ---------------------------------------------------------------------
-- FACT: fct_qa_evaluation  (grain: çağrı kalite değerlendirmesi; qa.evaluation.v1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.fct_qa_evaluation
(
    tenant_id            UUID,
    evaluation_id        UUID,
    call_id              UUID,
    agent_id             UUID,
    agent_version_id     UUID,
    event_date           Date,
    evaluated_at         DateTime64(3),
    auto_score           Float32,
    score_accuracy       Float32,
    score_compliance     Float32,
    score_helpfulness    Float32,
    critical_flag        UInt8,
    flag_misinformation  UInt8,
    flag_tool_error      UInt8,
    flag_security        UInt8,
    human_score          Nullable(Float32),
    human_comment_present UInt8,
    evaluator_role       LowCardinality(String),
    ingested_at          DateTime64(3),
    schema_version       UInt16
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, agent_id, event_date, call_id)
TTL event_date + INTERVAL 730 DAY
SETTINGS index_granularity = 8192;

-- ---------------------------------------------------------------------
-- FACT: fct_campaign_daily  (grain: kampanya × gün; campaign.events.v1)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.fct_campaign_daily
(
    tenant_id            UUID,
    campaign_id          UUID,
    agent_id             UUID,
    event_date           Date,
    dials                UInt32,
    connects             UInt32,
    voicemails           UInt32,
    busy                 UInt32,
    no_answer            UInt32,
    invalid              UInt32,
    completed            UInt32,
    transfers            UInt32,
    avg_duration_sec     UInt32,
    cost_total_micro     Decimal(18, 6),
    ingested_at          DateTime64(3),
    schema_version       UInt16
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, campaign_id, event_date)
TTL event_date + INTERVAL 730 DAY
SETTINGS index_granularity = 8192;

-- ---------------------------------------------------------------------
-- DIMENSIONS  (config plane aynası; düşük hacim. SCD-2 valid_from/to.)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.dim_tenant
(
    tenant_id    UUID,
    name         LowCardinality(String),
    plan_id      UUID,
    home_region  LowCardinality(String),
    sector       LowCardinality(String),
    status       LowCardinality(String),
    valid_from   DateTime64(3),
    valid_to     DateTime64(3)
)
ENGINE = ReplacingMergeTree(valid_from)
ORDER BY (tenant_id, valid_from);

CREATE TABLE IF NOT EXISTS ${OLAP_DB}.dim_agent
(
    tenant_id         UUID,
    agent_id          UUID,
    agent_version_id  UUID,
    name              LowCardinality(String),
    agent_type        LowCardinality(String),
    version_label     LowCardinality(String),
    published_at      DateTime64(3),
    valid_from        DateTime64(3),
    valid_to          DateTime64(3)
)
ENGINE = ReplacingMergeTree(valid_from)
ORDER BY (tenant_id, agent_id, agent_version_id);

CREATE TABLE IF NOT EXISTS ${OLAP_DB}.dim_campaign
(
    tenant_id      UUID,
    campaign_id    UUID,
    name           LowCardinality(String),
    campaign_type  LowCardinality(String),
    status         LowCardinality(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (tenant_id, campaign_id);

-- dim_provider / dim_date: tenant-bağımsız referans boyut (A1 istisnası).
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.dim_provider
(
    provider      LowCardinality(String),
    category      LowCardinality(String),
    display_name  LowCardinality(String),
    region        LowCardinality(String)
)
ENGINE = ReplacingMergeTree
ORDER BY (category, provider);

CREATE TABLE IF NOT EXISTS ${OLAP_DB}.dim_date
(
    date         Date,
    year         UInt16,
    month        UInt16,
    week         UInt16,
    day_of_week  UInt16
)
ENGINE = ReplacingMergeTree
ORDER BY (date);

-- ---------------------------------------------------------------------
-- ROLLUPS (AggregatingMergeTree + MATERIALIZED VIEW; -State agregatları).
-- fct_turn kısa TTL (90g) → latency percentile quantileState ile agregata taşınır.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ${OLAP_DB}.mv_call_daily
(
    tenant_id           UUID,
    agent_id            UUID,
    agent_version_id    UUID,
    event_date          Date,
    calls               AggregateFunction(count, UInt8),
    contained_calls     AggregateFunction(sum, UInt8),
    transferred_calls   AggregateFunction(sum, UInt8),
    critical_calls      AggregateFunction(sum, UInt8),
    e2e_p95_state       AggregateFunction(quantile(0.95), UInt32),
    cost_total_micro    AggregateFunction(sum, Decimal(18, 6))
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, agent_id, agent_version_id, event_date)
TTL event_date + INTERVAL 1825 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS ${OLAP_DB}.mvw_call_daily TO ${OLAP_DB}.mv_call_daily AS
SELECT
    tenant_id, agent_id, agent_version_id, event_date,
    countState(toUInt8(1))                  AS calls,
    sumState(contained)                     AS contained_calls,
    sumState(transferred)                   AS transferred_calls,
    sumState(flag_critical)                 AS critical_calls,
    quantileState(0.95)(e2e_latency_p95_ms) AS e2e_p95_state,
    sumState(cost_total_micro)              AS cost_total_micro
FROM ${OLAP_DB}.fct_call
GROUP BY tenant_id, agent_id, agent_version_id, event_date;

CREATE TABLE IF NOT EXISTS ${OLAP_DB}.mv_turn_latency_daily
(
    tenant_id              UUID,
    agent_id               UUID,
    event_date             Date,
    turns                  AggregateFunction(count, UInt8),
    stt_latency_state      AggregateFunction(quantile(0.95), UInt32),
    llm_first_token_state  AggregateFunction(quantile(0.95), UInt32),
    tts_first_byte_state   AggregateFunction(quantile(0.95), UInt32),
    e2e_latency_state      AggregateFunction(quantile(0.95), UInt32),
    tokens_in_sum          AggregateFunction(sum, UInt32),
    tokens_out_sum         AggregateFunction(sum, UInt32),
    provider_error_sum     AggregateFunction(sum, UInt8)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, agent_id, event_date)
TTL event_date + INTERVAL 1825 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS ${OLAP_DB}.mvw_turn_latency_daily TO ${OLAP_DB}.mv_turn_latency_daily AS
SELECT
    tenant_id, agent_id, event_date,
    countState(toUInt8(1))                     AS turns,
    quantileState(0.95)(stt_latency_ms)        AS stt_latency_state,
    quantileState(0.95)(llm_first_token_ms)    AS llm_first_token_state,
    quantileState(0.95)(tts_first_byte_ms)     AS tts_first_byte_state,
    quantileState(0.95)(e2e_latency_ms)        AS e2e_latency_state,
    sumState(llm_tokens_in)                    AS tokens_in_sum,
    sumState(llm_tokens_out)                   AS tokens_out_sum,
    sumState(provider_error)                   AS provider_error_sum
FROM ${OLAP_DB}.fct_turn
GROUP BY tenant_id, agent_id, event_date;

CREATE TABLE IF NOT EXISTS ${OLAP_DB}.mv_usage_daily
(
    tenant_id          UUID,
    agent_id           UUID,
    provider           LowCardinality(String),
    event_date         Date,
    billed_seconds_sum AggregateFunction(sum, UInt32),
    cost_telecom_sum   AggregateFunction(sum, Decimal(18, 6)),
    cost_stt_sum       AggregateFunction(sum, Decimal(18, 6)),
    cost_tts_sum       AggregateFunction(sum, Decimal(18, 6)),
    cost_llm_sum       AggregateFunction(sum, Decimal(18, 6)),
    cost_platform_sum  AggregateFunction(sum, Decimal(18, 6)),
    cost_total_sum     AggregateFunction(sum, Decimal(18, 6)),
    cpu_ms_sum         AggregateFunction(sum, UInt64),
    mem_peak_max       AggregateFunction(max, UInt32)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, agent_id, provider, event_date)
TTL event_date + INTERVAL 1825 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS ${OLAP_DB}.mvw_usage_daily TO ${OLAP_DB}.mv_usage_daily AS
SELECT
    tenant_id, agent_id, provider_llm AS provider, event_date,
    sumState(billed_seconds)      AS billed_seconds_sum,
    sumState(cost_telecom_micro)  AS cost_telecom_sum,
    sumState(cost_stt_micro)      AS cost_stt_sum,
    sumState(cost_tts_micro)      AS cost_tts_sum,
    sumState(cost_llm_micro)      AS cost_llm_sum,
    sumState(cost_platform_micro) AS cost_platform_sum,
    sumState(cost_total_micro)    AS cost_total_sum,
    sumState(cpu_ms)              AS cpu_ms_sum,
    maxState(mem_peak_mb)         AS mem_peak_max
FROM ${OLAP_DB}.fct_usage
GROUP BY tenant_id, agent_id, provider, event_date;

CREATE TABLE IF NOT EXISTS ${OLAP_DB}.mv_agent_version_perf
(
    tenant_id           UUID,
    agent_id            UUID,
    agent_version_id    UUID,
    calls               AggregateFunction(count, UInt8),
    contained_calls     AggregateFunction(sum, UInt8),
    transferred_calls   AggregateFunction(sum, UInt8),
    critical_calls      AggregateFunction(sum, UInt8),
    e2e_p95_state       AggregateFunction(quantile(0.95), UInt32)
)
ENGINE = AggregatingMergeTree
ORDER BY (tenant_id, agent_id, agent_version_id)
TTL toDate(now()) + INTERVAL 1825 DAY;

CREATE MATERIALIZED VIEW IF NOT EXISTS ${OLAP_DB}.mvw_agent_version_perf TO ${OLAP_DB}.mv_agent_version_perf AS
SELECT
    tenant_id, agent_id, agent_version_id,
    countState(toUInt8(1))                  AS calls,
    sumState(contained)                     AS contained_calls,
    sumState(transferred)                   AS transferred_calls,
    sumState(flag_critical)                 AS critical_calls,
    quantileState(0.95)(e2e_latency_p95_ms) AS e2e_p95_state
FROM ${OLAP_DB}.fct_call
GROUP BY tenant_id, agent_id, agent_version_id;

-- DOWN (geri alma): bağımlılık sırası — MV → rollup tablo → fact → dimension.
-- DROP VIEW IF EXISTS ${OLAP_DB}.mvw_agent_version_perf; DROP TABLE IF EXISTS ${OLAP_DB}.mv_agent_version_perf;
-- DROP VIEW IF EXISTS ${OLAP_DB}.mvw_usage_daily;        DROP TABLE IF EXISTS ${OLAP_DB}.mv_usage_daily;
-- DROP VIEW IF EXISTS ${OLAP_DB}.mvw_turn_latency_daily; DROP TABLE IF EXISTS ${OLAP_DB}.mv_turn_latency_daily;
-- DROP VIEW IF EXISTS ${OLAP_DB}.mvw_call_daily;         DROP TABLE IF EXISTS ${OLAP_DB}.mv_call_daily;
-- DROP TABLE IF EXISTS ${OLAP_DB}.fct_campaign_daily; DROP TABLE IF EXISTS ${OLAP_DB}.fct_qa_evaluation;
-- DROP TABLE IF EXISTS ${OLAP_DB}.fct_usage; DROP TABLE IF EXISTS ${OLAP_DB}.fct_turn; DROP TABLE IF EXISTS ${OLAP_DB}.fct_call;
-- DROP TABLE IF EXISTS ${OLAP_DB}.dim_date; DROP TABLE IF EXISTS ${OLAP_DB}.dim_provider;
-- DROP TABLE IF EXISTS ${OLAP_DB}.dim_campaign; DROP TABLE IF EXISTS ${OLAP_DB}.dim_agent; DROP TABLE IF EXISTS ${OLAP_DB}.dim_tenant;
