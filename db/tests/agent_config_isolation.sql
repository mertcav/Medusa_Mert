-- =============================================================================
-- Live RLS + WORM davranış testi — Agent ve Yapılandırma (WBS 1.1.2 / 12.2.3)
-- →FR-TEN-002, FR-AGT-006, SAD §13.1, DB.md §5.2/§6
--
-- Çalışan bir PostgreSQL gerektirir; 0001–0005 migration'ları uygulandıktan sonra
-- app_rw rolüyle (RLS bypass etmeyen) koşar. Her assertion başarısızsa transaction
-- RAISE EXCEPTION ile düşer → psql -v ON_ERROR_STOP=1 ile çıkış≠0.
-- Çalıştırma: db/run_live_test.sh (sunucu varsa). Statik kapı: schema_probe.py.
-- =============================================================================
\set ON_ERROR_STOP on
SET client_min_messages = warning;

-- Bağımsız test tenant'ları (rls_isolation.sql'den ayrı UUID'ler).
SET app.platform = 'on';
INSERT INTO tenant (id, name, home_region, kms_key_ref) VALUES
    ('33333333-3333-7333-8333-333333333333', 'Tenant C', 'EU', 'kms://c'),
    ('44444444-4444-7444-8444-444444444444', 'Tenant D', 'EU', 'kms://d');

-- Tenant C konfigürasyonu, C scope altında (FORCE RLS → WITH CHECK için GUC şart).
SET app.platform = 'off';
SET app.tenant_id = '33333333-3333-7333-8333-333333333333';

INSERT INTO agent (id, tenant_id, name, lifecycle_state) VALUES
    ('aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa',
     '33333333-3333-7333-8333-333333333333', 'C-Agent', 'draft');

INSERT INTO prompt (id, tenant_id, agent_id, version_no, body) VALUES
    ('bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb',
     '33333333-3333-7333-8333-333333333333',
     'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa', 1, 'Merhaba, size nasıl yardımcı olabilirim?');

INSERT INTO conversation_flow (id, tenant_id, agent_id, version_no, mode, graph) VALUES
    ('cccccccc-cccc-7ccc-8ccc-cccccccccccc',
     '33333333-3333-7333-8333-333333333333',
     'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa', 1, 'single_prompt', '{"nodes":[]}'::jsonb);

INSERT INTO voice_profile (id, tenant_id, name, settings) VALUES
    ('dddddddd-dddd-7ddd-8ddd-dddddddddddd',
     '33333333-3333-7333-8333-333333333333', 'C-Voice', '{"rate":1.0}'::jsonb);
INSERT INTO model_profile (id, tenant_id, name, tiering) VALUES
    ('eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee',
     '33333333-3333-7333-8333-333333333333', 'C-Model', '{"small":"x","large":"y"}'::jsonb);
INSERT INTO stt_profile (id, tenant_id, name, settings) VALUES
    ('ffffffff-ffff-7fff-8fff-ffffffffffff',
     '33333333-3333-7333-8333-333333333333', 'C-STT', '{"lang":["tr-TR","en-US"]}'::jsonb);

-- agent_version: tüm config'e FK + donmuş snapshot.
INSERT INTO agent_version
    (id, tenant_id, agent_id, version_no, prompt_id, flow_id,
     voice_profile_id, model_profile_id, stt_profile_id, snapshot) VALUES
    ('a1a1a1a1-a1a1-7a1a-8a1a-a1a1a1a1a1a1',
     '33333333-3333-7333-8333-333333333333',
     'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa', 1,
     'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb',
     'cccccccc-cccc-7ccc-8ccc-cccccccccccc',
     'dddddddd-dddd-7ddd-8ddd-dddddddddddd',
     'eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee',
     'ffffffff-ffff-7fff-8fff-ffffffffffff',
     '{"frozen":true}'::jsonb);

-- Dairesel FK: agent.active_version_id -> agent_version(id).
UPDATE agent SET active_version_id = 'a1a1a1a1-a1a1-7a1a-8a1a-a1a1a1a1a1a1'
 WHERE id = 'aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa';

-- Tenant D: tek agent (izolasyon karşı-örneği).
SET app.tenant_id = '44444444-4444-7444-8444-444444444444';
INSERT INTO agent (tenant_id, name) VALUES
    ('44444444-4444-7444-8444-444444444444', 'D-Agent');

RESET app.platform;
RESET app.tenant_id;

-- Uygulama gibi davran: RLS bypass etmeyen rol.
SET ROLE app_rw;

DO $$
DECLARE n int; av uuid;
BEGIN
    -- (1) FAIL-CLOSED: scope yokken hiçbir agent görünmez. GUC'lar NULL'a
    --     resetlenir ('' DEĞİL — ''::uuid hata fırlatır; NULL::uuid → false → 0 satır).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', NULL, true);
    SELECT count(*) INTO n FROM agent;
    IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED ihlali: scope yokken % agent görüldü', n; END IF;

    -- (2) Tenant izolasyonu: C scope yalnız C config'ini görür.
    PERFORM set_config('app.tenant_id', '33333333-3333-7333-8333-333333333333', true);
    SELECT count(*) INTO n FROM agent;
    IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon ihlali: C scope % agent gördü (1 beklenir)', n; END IF;
    SELECT count(*) INTO n FROM prompt;            IF n <> 1 THEN RAISE EXCEPTION 'C scope % prompt gördü', n; END IF;
    SELECT count(*) INTO n FROM conversation_flow; IF n <> 1 THEN RAISE EXCEPTION 'C scope % flow gördü', n; END IF;
    SELECT count(*) INTO n FROM voice_profile;     IF n <> 1 THEN RAISE EXCEPTION 'C scope % voice gördü', n; END IF;
    SELECT count(*) INTO n FROM model_profile;     IF n <> 1 THEN RAISE EXCEPTION 'C scope % model gördü', n; END IF;
    SELECT count(*) INTO n FROM stt_profile;       IF n <> 1 THEN RAISE EXCEPTION 'C scope % stt gördü', n; END IF;
    SELECT count(*) INTO n FROM agent_version;     IF n <> 1 THEN RAISE EXCEPTION 'C scope % agent_version gördü', n; END IF;

    -- (3) Dairesel FK çözüldü: active_version_id dolu ve doğru sürümü gösterir.
    SELECT active_version_id INTO av FROM agent WHERE name = 'C-Agent';
    IF av IS DISTINCT FROM 'a1a1a1a1-a1a1-7a1a-8a1a-a1a1a1a1a1a1' THEN
        RAISE EXCEPTION 'dairesel FK ihlali: active_version_id = %', av;
    END IF;

    -- (4) Cross-tenant WRITE engeli (WITH CHECK): C scope D agent'ı yazamaz.
    BEGIN
        INSERT INTO agent (tenant_id, name)
        VALUES ('44444444-4444-7444-8444-444444444444', 'sızıntı');
        RAISE EXCEPTION 'WITH CHECK ihlali: cross-tenant agent insert geçti';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: RLS WITH CHECK reddi
    END;

    -- (5) WORM (agent_version): UPDATE reddedilir (grant yok + trigger backstop).
    BEGIN
        UPDATE agent_version SET version_no = 99
         WHERE id = 'a1a1a1a1-a1a1-7a1a-8a1a-a1a1a1a1a1a1';
        RAISE EXCEPTION 'WORM ihlali: agent_version UPDATE geçti';
    EXCEPTION WHEN insufficient_privilege OR integrity_constraint_violation THEN
        NULL;  -- beklenen: append-only (UPDATE yok)
    END;

    -- (6) WORM (agent_version): DELETE reddedilir.
    BEGIN
        DELETE FROM agent_version WHERE id = 'a1a1a1a1-a1a1-7a1a-8a1a-a1a1a1a1a1a1';
        RAISE EXCEPTION 'WORM ihlali: agent_version DELETE geçti';
    EXCEPTION WHEN insufficient_privilege OR integrity_constraint_violation THEN
        NULL;  -- beklenen: append-only (DELETE yok)
    END;

    -- (7) Platform realm: iş config'ini varsayılan göremez (yalnız tenant scope).
    --     Platform GUC ile agent görünmez (agent saf tenant-scoped, platform OR'u yok).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', 'on', true);
    SELECT count(*) INTO n FROM agent;
    IF n <> 0 THEN
        RAISE EXCEPTION 'altın kural ihlali: platform realm % agent gördü (0 beklenir, L0 iş verisi görmez)', n;
    END IF;

    RAISE NOTICE 'TÜM AGENT/CONFIG RLS+WORM ASSERTION''LARI GEÇTİ (7/7)';
END;
$$;

RESET ROLE;
