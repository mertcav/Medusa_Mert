-- =============================================================================
-- Migration 0006 — Çağrı ve Etkileşim (şema, yüksek hacim / partitioned)
-- WBS 1.1.3 · F1 · Must · →BRD §16 (19–24), SAD §13.1 · DB.md §5.5/§7.2
--
-- Kapsam (DB.md §4 varlık 19–24):
--   call · call_leg · transcript · transcript_segment · recording ·
--   call_event · tool_execution (WORM)
-- (call_evaluation = varlık 25 → WBS 1.1.4 kapsamında; burada DEĞİL.)
-- RLS politikaları ayrı migration'da: 0007_rls_call_interaction.up.sql (DB.md §10
-- "yeni iş verisi tablosu RLS olmadan merge edilemez" — aynı seride gelir).
--
-- Bağımlı: 0001 (gen_uuid_v7, raise_immutable_violation), 0002 (tenant),
-- 0004 (agent, agent_version). İleri-yönlü ve idempotent (DB.md §10).
--
-- Tasarım kararları (DB.md §5.5/§7.2):
--   • Tümü RANGE partition (created_at, aylık). PK partition anahtarını içerir →
--     PRIMARY KEY (id, created_at). UNIQUE kısıtları da created_at'i içerir.
--   • Partition'lı tabloya gelen FK kısıtı PostgreSQL'de sınırlıdır: call_id /
--     transcript_id MANTIKSAL FK'dir (REFERENCES yok); bütünlük servis katmanı +
--     indekslerle. tenant_id / agent_id / agent_version_id ise normal tablolara
--     işaret ettiğinden GERÇEK FK'dir.
--   • campaign_id şimdilik mantıksal kolon: campaign tablosu WBS 1.1.4'te gelir,
--     FK o seride ALTER ile eklenir (ileri-yönlü). tool_id de aynı (tool tablosu
--     henüz yok) — mantıksal kolon + indeks.
--   • Partition yönetimi şema migration'dan bağımsız operasyonel iştir (DB.md
--     §7.2). Bu migration her tablo için bir DEFAULT partition (güvenlik ağı —
--     insert daima bir yere düşer) kurar; aylık partition'lar create_month_
--     partition() yardımcısıyla önceden açılır (pg_partman benzeri job).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Aylık RANGE partition yardımcısı (DB.md §7.2). Operasyonel job çağırır;
-- idempotent. Şema migration determinizmi için burada CURRENT tarihle ÇAĞRILMAZ.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION create_month_partition(p_parent text, p_month date)
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
    v_start date := date_trunc('month', p_month)::date;
    v_end   date := (date_trunc('month', p_month) + interval '1 month')::date;
    v_child text := format('%s_p%s', p_parent, to_char(v_start, 'YYYYMM'));
BEGIN
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        v_child, p_parent, v_start, v_end);
    RETURN v_child;
END;
$$;
COMMENT ON FUNCTION create_month_partition(text, date) IS
    'Aylık RANGE partition önceden açma (DB.md §7.2). Operasyonel; idempotent.';

-- 19) Call — çağrı üst kaydı. RANGE partition (created_at, aylık).
CREATE TABLE call (
    id               UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id        UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    correlation_id   UUID NOT NULL,                         -- BRD §15, SAD §13.3/§17.1
    agent_id         UUID REFERENCES agent(id) ON DELETE RESTRICT,
    agent_version_id UUID REFERENCES agent_version(id) ON DELETE RESTRICT,
    campaign_id      UUID,                                  -- mantıksal: FK 1.1.4'te (campaign yok)
    direction        TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    from_e164        TEXT,
    to_e164          TEXT,
    started_at       TIMESTAMPTZ,
    ended_at         TIMESTAMPTZ,
    end_reason       TEXT,                                  -- standart taksonomi (FR-TEL-012)
    outcome          TEXT,                                  -- containment/transfer (FR-ANA-002/003)
    region           TEXT NOT NULL,                         -- residency (NFR 10.7)
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE call IS 'BRD §16 (19) Call — çağrı üst kaydı (partitioned). DB.md §5.5, FR-TEL-012.';
CREATE INDEX ix_call_tenant_time  ON call (tenant_id, created_at DESC);
CREATE INDEX ix_call_correlation  ON call (correlation_id);
CREATE INDEX ix_call_agent        ON call (tenant_id, agent_id, created_at DESC);
CREATE INDEX ix_call_agentver     ON call (agent_version_id);
CREATE INDEX ix_call_campaign     ON call (tenant_id, campaign_id);
CREATE TABLE IF NOT EXISTS call_default PARTITION OF call DEFAULT;

-- 20) Call Leg — transfer dahil bacak (FR-TEL-007, handoff §9).
CREATE TABLE call_leg (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id       UUID NOT NULL,                            -- mantıksal FK → call (partition'lı; DB.md §7.2)
    leg_type      TEXT NOT NULL CHECK (leg_type IN ('agent','transfer_cold','transfer_warm','transfer_whisper','voicemail')),
    target        TEXT,                                     -- kuyruk/skill/temsilci
    started_at    TIMESTAMPTZ,
    ended_at      TIMESTAMPTZ,
    result        TEXT,                                     -- transfer sonucu (FR-HND-008)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE call_leg IS 'BRD §16 (20) Call Leg — çağrı bacağı/transfer (partitioned). DB.md §5.5, FR-TEL-007.';
CREATE INDEX ix_leg_call ON call_leg (tenant_id, call_id);
CREATE TABLE IF NOT EXISTS call_leg_default PARTITION OF call_leg DEFAULT;

-- 21) Transcript (+ segment). Tam metin nesne depoda; DB metadata + segment timeline (P6).
CREATE TABLE transcript (
    id              UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id         UUID NOT NULL,                          -- mantıksal FK → call
    storage_uri     TEXT,                                   -- nesne depo pointer (P6)
    redaction_state TEXT NOT NULL DEFAULT 'pending'
                      CHECK (redaction_state IN ('pending','redacted','not_required')),  -- FR-REC-004
    summary         TEXT,                                   -- çağrı özeti (BRD §8.1)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE transcript IS 'BRD §16 (21) Transcript — metadata + pointer (partitioned, PII). DB.md §5.5/P6, FR-REC-004.';
CREATE INDEX ix_transcript_call ON transcript (tenant_id, call_id);
CREATE TABLE IF NOT EXISTS transcript_default PARTITION OF transcript DEFAULT;

CREATE TABLE transcript_segment (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    transcript_id UUID NOT NULL,                            -- mantıksal FK → transcript (partition'lı)
    seq           INTEGER NOT NULL,
    speaker       TEXT CHECK (speaker IN ('caller','agent','human')),
    text          TEXT,                                     -- kart/parola/OTP çıkarılmış (FR-REC-005)
    confidence    NUMERIC(4,3),                             -- word confidence (BRD §15)
    started_ms    INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE transcript_segment IS 'BRD §16 (21) Transcript Segment — konuşma satırı (partitioned, PII). DB.md §5.5, FR-REC-005.';
CREATE INDEX ix_tsegment_transcript ON transcript_segment (tenant_id, transcript_id, seq);
CREATE TABLE IF NOT EXISTS transcript_segment_default PARTITION OF transcript_segment DEFAULT;

-- 22) Recording — ses metadata; ham ses nesne depoda + KMS (P6, SAD §12.1).
CREATE TABLE recording (
    id              UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id         UUID NOT NULL,                          -- mantıksal FK → call
    storage_uri     TEXT NOT NULL,                          -- tenant bucket/prefix + KMS (SAD §12.1)
    channels        SMALLINT CHECK (channels IN (1,2)),     -- tek/çift kanal (FR-REC-003)
    duration_ms     INTEGER,
    redaction_state TEXT NOT NULL DEFAULT 'pending'
                      CHECK (redaction_state IN ('pending','redacted','not_required')),  -- FR-REC-004
    retain_until    TIMESTAMPTZ,                            -- retention (FR-REC-006)
    legal_hold      BOOLEAN NOT NULL DEFAULT false,         -- FR-REC-007
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE recording IS 'BRD §16 (22) Recording — ses metadata + pointer (partitioned, PII). DB.md §5.5/P6, FR-REC-003/006/007.';
CREATE INDEX ix_recording_call      ON recording (tenant_id, call_id);
CREATE INDEX ix_recording_retention ON recording (retain_until) WHERE legal_hold = false;  -- retention (DB.md §9)
CREATE TABLE IF NOT EXISTS recording_default PARTITION OF recording DEFAULT;

-- 23) Event — gerçek zamanlı çağrı olayı (kalıcı form; replay Kafka'da, ADR-007).
CREATE TABLE call_event (
    id             UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id      UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id        UUID NOT NULL,                           -- mantıksal FK → call
    correlation_id UUID NOT NULL,                           -- BRD §15, SAD §13.3/§17.1
    event_type     TEXT NOT NULL,                           -- BRD §15 zaman damgaları taksonomisi
    payload        JSONB,                                   -- jitter/latency/token vb. metrikler
    occurred_at    TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE call_event IS 'BRD §16 (23) Event — çağrı olayı kalıcı formu (partitioned). DB.md §5.5, BRD §15.';
CREATE INDEX ix_event_call    ON call_event (tenant_id, call_id, occurred_at);
CREATE INDEX ix_event_payload ON call_event USING gin (payload jsonb_path_ops);  -- metrik sorgusu (DB.md §7.1)
CREATE TABLE IF NOT EXISTS call_event_default PARTITION OF call_event DEFAULT;

-- 24) Tool Execution — API işlem kaydı; idempotent + WORM (FR-TOOL-009/010, P4/P8).
--     idempotency_key (tenant + created_at ile) benzersiz: partition'lı UNIQUE
--     kısıtı partition anahtarını içermek zorundadır (DB.md §5.5).
CREATE TABLE tool_execution (
    id              UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id         UUID,                                   -- mantıksal FK → call (nullable: çağrı dışı işlem)
    correlation_id  UUID NOT NULL,                          -- FR-TOOL-010
    tool_id         UUID,                                   -- mantıksal: tool tablosu henüz yok (FK sonra)
    idempotency_key TEXT NOT NULL,                          -- duplicate işlem önleme (FR-TOOL-009)
    request         JSONB,
    response        JSONB,
    status          TEXT NOT NULL CHECK (status IN ('success','error','timeout')),
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at),
    UNIQUE (tenant_id, idempotency_key, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE tool_execution IS 'BRD §16 (24) Tool Execution — idempotent + WORM işlem kaydı (partitioned). DB.md §5.5/§6.5, FR-TOOL-009/010.';
CREATE INDEX ix_toolexec_call ON tool_execution (tenant_id, call_id);
CREATE TABLE IF NOT EXISTS tool_execution_default PARTITION OF tool_execution DEFAULT;

-- WORM zorlama (DB.md §6.5, P4): tool_execution append-only. UPDATE/DELETE reddi.
-- Grant düzeyi koruması (yalnız INSERT+SELECT) 0007'de; bu trigger yedek güvence.
CREATE TRIGGER trg_toolexec_immutable
    BEFORE UPDATE OR DELETE ON tool_execution
    FOR EACH ROW EXECUTE FUNCTION raise_immutable_violation();
