-- =============================================================================
-- Migration 0004 — Agent ve Yapılandırma (şema)
-- WBS 1.1.2 · F1 · Must · →BRD §16 (5–11), SAD §13.1 · DB.md §5.2
--
-- Kapsam (DB.md §4 varlık 5–11):
--   agent · agent_version (WORM) · prompt · conversation_flow ·
--   voice_profile · model_profile · stt_profile
-- RLS politikaları ayrı migration'da: 0005_rls_agent_config.up.sql (DB.md §10
-- "yeni iş verisi tablosu RLS olmadan merge edilemez" — aynı seride gelir).
--
-- Bağımlı: 0001 (gen_uuid_v7, set_updated_at, raise_immutable_violation),
-- 0002 (tenant, organisation_unit, app_user). İleri-yönlü ve idempotent (DB.md §10).
--
-- Yaratım sırası bağımlılığı: agent → (prompt, conversation_flow, voice/model/stt
-- profile) → agent_version (hepsine FK) → agent.active_version_id dairesel FK'si
-- ALTER ile en sona eklenir (DB.md §10 "dairesel FK").
-- =============================================================================

-- 5) Agent — voice AI agent tanımı (FR-AGT-001/002). active_version_id'nin FK'si
--    agent_version oluştuktan sonra ALTER ile eklenir (dairesel referans).
CREATE TABLE agent (
    id              UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id       UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    org_unit_id     UUID REFERENCES organisation_unit(id) ON DELETE RESTRICT,
    name            TEXT NOT NULL,
    purpose         TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'draft'
                      CHECK (lifecycle_state IN ('draft','test','staging','production','archived')), -- FR-AGT-005
    active_version_id UUID,                                                  -- -> agent_version(id) (ALTER, aşağıda)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ,
    row_version     INTEGER NOT NULL DEFAULT 1,
    deleted_at      TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);
COMMENT ON TABLE agent IS 'BRD §16 (5) Agent — voice AI agent tanımı. DB.md §5.2, FR-AGT-001/002.';
CREATE INDEX ix_agent_tenant  ON agent (tenant_id);
CREATE INDEX ix_agent_orgunit ON agent (org_unit_id);
CREATE INDEX ix_agent_state   ON agent (tenant_id, lifecycle_state) WHERE deleted_at IS NULL;  -- FR-AGT-005

CREATE TRIGGER trg_agent_updated_at
    BEFORE UPDATE ON agent
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 7) Prompt (FR-AGT-004, FR-LLM-006) — versiyonlu system prompt. agent_version
--    bunlara referans verdiğinden agent_version'dan ÖNCE oluşturulur.
CREATE TABLE prompt (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    agent_id     UUID REFERENCES agent(id) ON DELETE RESTRICT,
    version_no   INTEGER NOT NULL,
    body         TEXT NOT NULL,
    is_published BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no)
);
COMMENT ON TABLE prompt IS 'BRD §16 (7) Prompt — versiyonlu system prompt. DB.md §5.2, FR-AGT-004/FR-LLM-006.';
CREATE INDEX ix_prompt_tenant ON prompt (tenant_id);
CREATE INDEX ix_prompt_agent  ON prompt (agent_id);

-- 8) Conversation Flow (FR-AGT-003) — node/state grafiği jsonb. single_prompt
--    veya node_flow modeli (SAD §6.1, WBS 3.2.4).
CREATE TABLE conversation_flow (
    id           UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id    UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    agent_id     UUID REFERENCES agent(id) ON DELETE RESTRICT,
    version_no   INTEGER NOT NULL,
    mode         TEXT NOT NULL CHECK (mode IN ('single_prompt','node_flow')),
    graph        JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no)
);
COMMENT ON TABLE conversation_flow IS 'BRD §16 (8) Conversation Flow — node/flow grafiği. DB.md §5.2, FR-AGT-003.';
CREATE INDEX ix_flow_tenant ON conversation_flow (tenant_id);
CREATE INDEX ix_flow_agent  ON conversation_flow (agent_id);
CREATE INDEX ix_flow_graph  ON conversation_flow USING gin (graph jsonb_path_ops);  -- node arama (DB.md §7.1)

-- 9/10/11) Voice / Model / STT Profile — tenant-scoped, sağlayıcı-nötr config
--    (ADR-002; ayarlar adapter SPI tarafından yorumlanır, SAD §8.1).
CREATE TABLE voice_profile (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    name        TEXT NOT NULL,
    settings    JSONB NOT NULL,        -- TTS sağlayıcı-nötr ayarları: hız/ses/pronunciation dict (FR-TTS-004, FR-RTC-008)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
COMMENT ON TABLE voice_profile IS 'BRD §16 (9) Voice Profile — TTS config. DB.md §5.2, FR-AGT-002.';
CREATE INDEX ix_voiceprofile_tenant ON voice_profile (tenant_id);

CREATE TABLE model_profile (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    name        TEXT NOT NULL,
    tiering     JSONB NOT NULL,        -- küçük/büyük model tier eşlemesi (FR-LLM-002/013, FR-RES-005)
    no_train    BOOLEAN NOT NULL DEFAULT true,  -- "tenant verisi eğitime kapalı" varsayılanı (FR-LLM-012)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
COMMENT ON TABLE model_profile IS 'BRD §16 (10) Model Profile — LLM tiering config. DB.md §5.2, FR-LLM-002/012/013.';
CREATE INDEX ix_modelprofile_tenant ON model_profile (tenant_id);

CREATE TABLE stt_profile (
    id          UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id   UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    name        TEXT NOT NULL,
    settings    JSONB NOT NULL,        -- dil, phrase boosting, alan optimizasyonu (FR-STT-004/005)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
COMMENT ON TABLE stt_profile IS 'BRD §16 (11) STT Profile — STT config. DB.md §5.2, FR-STT-004/005.';
CREATE INDEX ix_sttprofile_tenant ON stt_profile (tenant_id);

-- 6) Agent Version — DEĞİŞMEZ snapshot (FR-AGT-006). WORM/append-only (DB.md §6.5):
--    rollback = yeni satır; eski satır UPDATE/DELETE edilmez. Tüm config'e FK +
--    donmuş snapshot JSONB. prompt/flow/profile tablolarından SONRA gelir.
CREATE TABLE agent_version (
    id               UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id        UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    agent_id         UUID NOT NULL REFERENCES agent(id) ON DELETE RESTRICT,
    version_no       INTEGER NOT NULL,
    prompt_id        UUID REFERENCES prompt(id) ON DELETE RESTRICT,
    flow_id          UUID REFERENCES conversation_flow(id) ON DELETE RESTRICT,
    voice_profile_id UUID REFERENCES voice_profile(id) ON DELETE RESTRICT,
    model_profile_id UUID REFERENCES model_profile(id) ON DELETE RESTRICT,
    stt_profile_id   UUID REFERENCES stt_profile(id) ON DELETE RESTRICT,
    snapshot         JSONB NOT NULL,                                        -- bağlanan tüm config'in donmuş kopyası
    published_by     UUID REFERENCES app_user(id) ON DELETE SET NULL,
    published_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, agent_id, version_no)
);
COMMENT ON TABLE agent_version IS 'BRD §16 (6) Agent Version — WORM snapshot (rollback). DB.md §5.2/§6.5, FR-AGT-006.';
CREATE INDEX ix_agentver_agent  ON agent_version (tenant_id, agent_id, version_no DESC);  -- son sürüm sorgusu
CREATE INDEX ix_agentver_prompt ON agent_version (prompt_id);
CREATE INDEX ix_agentver_flow   ON agent_version (flow_id);
CREATE INDEX ix_agentver_voice  ON agent_version (voice_profile_id);
CREATE INDEX ix_agentver_model  ON agent_version (model_profile_id);
CREATE INDEX ix_agentver_stt    ON agent_version (stt_profile_id);

-- WORM zorlama (DB.md §6.5): UPDATE/DELETE reddi. Grant düzeyi koruması (yalnız
-- INSERT+SELECT) 0005'te; bu trigger rol yanlış yapılandırılsa bile yedek güvence.
CREATE TRIGGER trg_agentver_immutable
    BEFORE UPDATE OR DELETE ON agent_version
    FOR EACH ROW EXECUTE FUNCTION raise_immutable_violation();

-- Dairesel FK: agent.active_version_id -> agent_version(id) (DB.md §10). Her iki
-- tablo da var olduktan sonra eklenir. ON DELETE RESTRICT: aktif sürüm silinemez.
ALTER TABLE agent
    ADD CONSTRAINT fk_agent_active_version
    FOREIGN KEY (active_version_id) REFERENCES agent_version(id) ON DELETE RESTRICT;
CREATE INDEX ix_agent_active_version ON agent (active_version_id);
