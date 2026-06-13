-- =============================================================================
-- Migration 0008 — Outbound, Operasyon, Faturalama ve Yönetişim (şema)
-- WBS 1.1.4 · F2 · Must · →BRD §16 (16–18, 25–28), SAD §13.1 · DB.md §5.4/§5.6
--
-- Kapsam (DB.md §4 varlık 16–18, 25–28):
--   campaign · contact · consent (WORM) · call_evaluation · usage_record (part.) ·
--   audit_log (WORM, part., platform+tenant) · incident (platform+tenant)
-- RLS politikaları ayrı migration'da: 0009_rls_outbound_ops_governance.up.sql
-- (DB.md §10 "yeni iş verisi tablosu RLS olmadan merge edilemez" — aynı seride gelir).
--
-- Bağımlı: 0001 (gen_uuid_v7, raise_immutable_violation, app_rw), 0002 (tenant,
-- organisation_unit, app_user), 0004 (agent), 0006 (call [partition'lı], +
-- create_month_partition). İleri-yönlü; her up/down re-runnable (down→up).
--
-- Tasarım kararları (DB.md §5.4/§5.6/§6.5/§7.2):
--   • campaign/contact/consent/call_evaluation/incident NON-partition (orta hacim);
--     usage_record + audit_log RANGE (created_at) partition'lı (yüksek hacim §7.2).
--   • consent + audit_log WORM/append-only (DB.md §6.5, P4): BEFORE UPDATE OR DELETE
--     → raise_immutable_violation trigger; grant düzeyi koruması 0009'da.
--   • audit_log WORM bağımsızlığı: tenant_id/actor_user_id FK YOK (audit, işaret
--     ettiği satır silinse de korunur — DB.md §5.6). tenant_id NULL => platform işlemi.
--   • audit_log + incident "platform + tenant karışık" (tenant_id NULL'lanabilir) →
--     0009'da karışık RLS politikası (DB.md §6.3).
--   • call_id call_evaluation/usage_record'da MANTIKSAL FK (partition'lı call'a
--     REFERENCES yok, DB.md §7.2); bütünlük servis katmanı + indeks.
--   • 0006'da mantıksal bırakılan call.campaign_id artık GERÇEK FK: campaign tablosu
--     bu seride geldiğinden ALTER ile eklenir (0006 ileri-yönlü notu).
-- =============================================================================

-- 16) Campaign — outbound kampanya (FR-OUT-*).
CREATE TABLE campaign (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    org_unit_id   UUID REFERENCES organisation_unit(id) ON DELETE RESTRICT,
    name          TEXT NOT NULL,
    agent_id      UUID REFERENCES agent(id) ON DELETE RESTRICT,
    status        TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','running','paused','stopped','completed')),  -- FR-OUT-010
    max_attempts  INTEGER NOT NULL DEFAULT 3,             -- FR-OUT-005
    retry_interval_minutes INTEGER,
    script_version TEXT,                                  -- FR-OUT-009
    calling_hours JSONB,                                  -- ülke/bölge arama saati (FR-OUT-004)
    capacity_cap  INTEGER,                                -- ≤ agent+trunk kapasitesi (FR-OUT-007)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, name)
);
COMMENT ON TABLE campaign IS 'BRD §16 (16) Campaign — outbound kampanya. DB.md §5.4, FR-OUT-004/005/007/010.';
CREATE INDEX ix_campaign_tenant_status ON campaign (tenant_id, status);
CREATE INDEX ix_campaign_orgunit       ON campaign (org_unit_id);
CREATE INDEX ix_campaign_agent         ON campaign (agent_id);

-- 17) Contact — aranacak müşteri (PII; Tier B break-glass kapsamı, §6.4).
CREATE TABLE contact (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    campaign_id   UUID REFERENCES campaign(id) ON DELETE RESTRICT,
    e164          TEXT NOT NULL,
    party_type    TEXT CHECK (party_type IN ('individual','company')),  -- consent kuralı (§14.3)
    external_ref  TEXT,                                   -- CRM kaydı (FR-OUT-002)
    attributes    JSONB,                                  -- maskeli görüntülenir (BRD §17.7)
    do_not_call   BOOLEAN NOT NULL DEFAULT false,         -- DNC/suppression (FR-TEL-014, FR-OUT-006)
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_call_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, campaign_id, e164)
);
COMMENT ON TABLE contact IS 'BRD §16 (17) Contact — aranacak müşteri (PII). DB.md §5.4, FR-OUT-002/006, FR-TEL-014.';
CREATE INDEX ix_contact_campaign ON contact (tenant_id, campaign_id);
CREATE INDEX ix_contact_dnc      ON contact (tenant_id, e164) WHERE do_not_call = true;  -- DNC (DB.md §7.1)

-- 18) Consent — APPEND-ONLY izin kaydı (FR-OUT-003, §14.3). Opt-out = yeni satır (WORM).
CREATE TABLE consent (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    contact_id    UUID REFERENCES contact(id) ON DELETE RESTRICT,
    e164          TEXT NOT NULL,
    purpose       TEXT NOT NULL,                          -- arama amacı
    country       TEXT NOT NULL,
    consent_source TEXT,                                  -- consent kaynağı
    consent_date  TIMESTAMPTZ,                            -- consent tarihi
    scope         JSONB,                                  -- kapsam
    legal_basis   TEXT,                                   -- hukuki dayanak (BRD §14.1)
    iys_ref       TEXT,                                   -- TR İYS izin kaydı (§14.3)
    state         TEXT NOT NULL CHECK (state IN ('granted','withdrawn')),  -- opt-out = withdrawn
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE consent IS 'BRD §16 (18) Consent — append-only/WORM izin kaydı. DB.md §5.4/§6.5, FR-OUT-003, §14.3.';
CREATE INDEX ix_consent_lookup  ON consent (tenant_id, e164, recorded_at DESC);  -- son durum
CREATE INDEX ix_consent_contact ON consent (tenant_id, contact_id);

-- WORM zorlama (DB.md §6.5, P4): consent append-only. UPDATE/DELETE reddi.
-- Grant düzeyi koruması (yalnız INSERT+SELECT) 0009'da; bu trigger yedek güvence.
CREATE TRIGGER trg_consent_immutable
    BEFORE UPDATE OR DELETE ON consent
    FOR EACH ROW EXECUTE FUNCTION raise_immutable_violation();

-- 25) Call Evaluation — otomatik/manuel QA (FR-ANA-001/009). NON-partition.
--     call_id MANTIKSAL FK (partition'lı call'a REFERENCES yok — DB.md §7.2).
CREATE TABLE call_evaluation (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id       UUID NOT NULL,                          -- mantıksal FK → call (partition'lı)
    eval_type     TEXT NOT NULL CHECK (eval_type IN ('automatic','manual')),
    scores        JSONB,
    flags         JSONB,                                  -- kritik konuşma işaretleme (FR-ANA-008)
    evaluator_id  UUID REFERENCES app_user(id) ON DELETE RESTRICT,  -- manuel ise
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE call_evaluation IS 'BRD §16 (25) Call Evaluation — otomatik/manuel QA. DB.md §5.5, FR-ANA-001/008/009.';
CREATE INDEX ix_eval_call      ON call_evaluation (tenant_id, call_id);
CREATE INDEX ix_eval_evaluator ON call_evaluation (evaluator_id);

-- 26) Usage Record — maliyet/kullanım/kaynak (FR-BIL-001/002, FR-ANA-013).
--     RANGE partition (created_at, aylık) — OLAP'a aktarım sonrası eski partition drop.
CREATE TABLE usage_record (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    call_id       UUID,                                   -- mantıksal FK → call (nullable: platform kalemi)
    category      TEXT NOT NULL CHECK (category IN ('telephony','stt','tts','llm','platform','compute')),
    provider      TEXT,
    quantity      NUMERIC,                                -- saniye/dakika/token (FR-BIL-001)
    unit          TEXT,
    cost          NUMERIC(18,6),
    currency      CHAR(3),
    cpu_ms        NUMERIC,                                -- per-call kaynak (FR-RES-016)
    mem_mb_peak   NUMERIC,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE usage_record IS 'BRD §16 (26) Usage Record — maliyet/kullanım (partitioned). DB.md §5.6/§7.2, FR-BIL-001/002.';
CREATE INDEX ix_usage_tenant_time ON usage_record (tenant_id, recorded_at DESC);
CREATE INDEX ix_usage_call        ON usage_record (tenant_id, call_id);
CREATE TABLE IF NOT EXISTS usage_record_default PARTITION OF usage_record DEFAULT;

-- 27) Audit Log — WORM append-only + hash chain bütünlük (FR-IAM-006, FR-REC-009).
--     RANGE partition (created_at, aylık). tenant_id NULL => platform işlemi (karışık RLS).
--     WORM bağımsızlık: tenant_id/actor_user_id FK YOK (işaret edilen satır silinse de
--     audit korunur — DB.md §5.6).
CREATE TABLE audit_log (
    id            UUID NOT NULL DEFAULT gen_uuid_v7(),
    tenant_id     UUID,                                   -- NULL => platform işlemi (FK YOK: WORM bağımsızlık)
    actor_user_id UUID,                                   -- app_user(id) (FK YOK: WORM bağımsızlık)
    actor_realm   TEXT NOT NULL,
    action        TEXT NOT NULL,                          -- 'consent:withdraw','transcript:read',...
    resource_type TEXT,
    resource_id   UUID,
    break_glass_id UUID,                                  -- break_glass_grant referansı (FR-IAM-009)
    detail        JSONB,
    prev_hash     BYTEA,                                  -- önceki kaydın hash'i (chain)
    row_hash      BYTEA NOT NULL,                         -- bu kaydın hash'i (bütünlük)
    occurred_at   TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
COMMENT ON TABLE audit_log IS 'BRD §16 (27) Audit Log — WORM append-only + hash chain (partitioned). DB.md §5.6/§6.5, FR-IAM-006, FR-REC-009.';
CREATE INDEX ix_audit_tenant_time ON audit_log (tenant_id, occurred_at DESC);
CREATE INDEX ix_audit_resource    ON audit_log (resource_type, resource_id);
CREATE TABLE IF NOT EXISTS audit_log_default PARTITION OF audit_log DEFAULT;

-- WORM zorlama (DB.md §6.5, P4): audit_log append-only. UPDATE/DELETE reddi.
-- Grant düzeyi koruması (yalnız INSERT+SELECT) 0009'da; bu trigger yedek güvence.
CREATE TRIGGER trg_audit_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION raise_immutable_violation();

-- 28) Incident — operasyon olayı (P-09 / SRE). NON-partition; platform veya tenant
--     (tenant_id NULL => platform geneli → karışık RLS, DB.md §6.3).
CREATE TABLE incident (
    id            UUID PRIMARY KEY DEFAULT gen_uuid_v7(),
    tenant_id     UUID REFERENCES tenant(id) ON DELETE RESTRICT,  -- NULL => platform geneli
    severity      TEXT NOT NULL CHECK (severity IN ('sev1','sev2','sev3','sev4')),
    status        TEXT NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open','mitigating','resolved','closed')),
    title         TEXT NOT NULL,
    detail        JSONB,
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);
COMMENT ON TABLE incident IS 'BRD §16 (28) Incident — operasyon olayı (platform/tenant). DB.md §5.6, P-09/SRE.';
CREATE INDEX ix_incident_status ON incident (status, severity);
CREATE INDEX ix_incident_tenant ON incident (tenant_id);

-- -----------------------------------------------------------------------------
-- Gecikmeli (deferred) FK: 0006'da mantıksal bırakılan call.campaign_id artık
-- campaign tablosu geldiğinden GERÇEK FK olur (0006 ileri-yönlü notu, DB.md §5.5).
-- call partition'lı (referencing taraf) → campaign normal tablo (referenced):
-- PostgreSQL partition'lı tablonun FK referans VERMESİNİ destekler. İndeks
-- (ix_call_campaign) 0006'da mevcut. Down'da DROP CONSTRAINT ile geri alınır.
-- -----------------------------------------------------------------------------
ALTER TABLE call
    ADD CONSTRAINT fk_call_campaign
    FOREIGN KEY (campaign_id) REFERENCES campaign(id) ON DELETE RESTRICT;
