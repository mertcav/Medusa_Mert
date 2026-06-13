-- =============================================================================
-- Live RLS + WORM + partition davranış testi — Çağrı ve Etkileşim (WBS 1.1.3 / 12.2.3)
-- →FR-TEN-002, FR-TOOL-009, SAD §13.1, DB.md §5.5/§6/§7.2
--
-- Çalışan bir PostgreSQL gerektirir; 0001–0007 migration'ları uygulandıktan sonra
-- app_rw rolüyle (RLS bypass etmeyen) koşar. Her assertion başarısızsa transaction
-- RAISE EXCEPTION ile düşer → psql -v ON_ERROR_STOP=1 ile çıkış≠0.
-- Çalıştırma: db/run_live_test.sh (sunucu varsa). Statik kapı: schema_probe.py.
-- =============================================================================
\set ON_ERROR_STOP on
SET client_min_messages = warning;

-- Bağımsız test tenant'ları (önceki test dosyalarından ayrı UUID'ler).
SET app.platform = 'on';
INSERT INTO tenant (id, name, home_region, kms_key_ref) VALUES
    ('55555555-5555-7555-8555-555555555555', 'Tenant E', 'EU', 'kms://e'),
    ('66666666-6666-7666-8666-666666666666', 'Tenant F', 'EU', 'kms://f');

-- Aylık partition önceden açma (DB.md §7.2). DEFAULT partition'a düşmeden önce
-- açıldığından routing testi anlamlıdır.
SELECT create_month_partition('call', DATE '2026-06-01');

SET app.platform = 'off';

-- Tenant E: bir çağrı + bağlı etkileşim kayıtları, E scope altında.
SET app.tenant_id = '55555555-5555-7555-8555-555555555555';

-- created_at'i Haziran 2026'ya sabitle → aylık partition'a (call_p202606) düşmeli.
INSERT INTO call (id, tenant_id, correlation_id, direction, region, created_at) VALUES
    ('c0000000-0000-7000-8000-000000000001',
     '55555555-5555-7555-8555-555555555555',
     'cabc0000-0000-7000-8000-000000000001', 'inbound', 'EU', TIMESTAMPTZ '2026-06-15 10:00:00+00');

INSERT INTO call_leg (tenant_id, call_id, leg_type, created_at) VALUES
    ('55555555-5555-7555-8555-555555555555',
     'c0000000-0000-7000-8000-000000000001', 'agent', TIMESTAMPTZ '2026-06-15 10:00:05+00');

INSERT INTO transcript (id, tenant_id, call_id, redaction_state, created_at) VALUES
    ('70000000-0000-7000-8000-000000000001',
     '55555555-5555-7555-8555-555555555555',
     'c0000000-0000-7000-8000-000000000001', 'pending', TIMESTAMPTZ '2026-06-15 10:01:00+00');

INSERT INTO transcript_segment (tenant_id, transcript_id, seq, speaker, text, confidence, created_at) VALUES
    ('55555555-5555-7555-8555-555555555555',
     '70000000-0000-7000-8000-000000000001', 1, 'caller', 'Merhaba', 0.987,
     TIMESTAMPTZ '2026-06-15 10:01:01+00');

INSERT INTO recording (tenant_id, call_id, storage_uri, channels, created_at) VALUES
    ('55555555-5555-7555-8555-555555555555',
     'c0000000-0000-7000-8000-000000000001', 's3://e/rec1', 2, TIMESTAMPTZ '2026-06-15 10:02:00+00');

INSERT INTO call_event (tenant_id, call_id, correlation_id, event_type, payload, occurred_at, created_at) VALUES
    ('55555555-5555-7555-8555-555555555555',
     'c0000000-0000-7000-8000-000000000001',
     'cabc0000-0000-7000-8000-000000000001', 'stt.final', '{"latency_ms":180}'::jsonb,
     TIMESTAMPTZ '2026-06-15 10:00:10+00', TIMESTAMPTZ '2026-06-15 10:00:10+00');

INSERT INTO tool_execution
    (id, tenant_id, call_id, correlation_id, idempotency_key, status, latency_ms, created_at) VALUES
    ('e0000000-0000-7000-8000-000000000001',
     '55555555-5555-7555-8555-555555555555',
     'c0000000-0000-7000-8000-000000000001',
     'cabc0000-0000-7000-8000-000000000001', 'idem-1', 'success', 95,
     TIMESTAMPTZ '2026-06-15 10:00:20+00');

-- Tenant F: tek çağrı (izolasyon karşı-örneği).
SET app.tenant_id = '66666666-6666-7666-8666-666666666666';
INSERT INTO call (tenant_id, correlation_id, direction, region) VALUES
    ('66666666-6666-7666-8666-666666666666',
     'cabc0000-0000-7000-8000-000000000002', 'outbound', 'EU');

RESET app.platform;
RESET app.tenant_id;

-- Uygulama gibi davran: RLS bypass etmeyen rol.
SET ROLE app_rw;

DO $$
DECLARE n int; r text;
BEGIN
    -- (1) FAIL-CLOSED: scope yokken hiçbir çağrı görünmez. set_config(...,NULL,...)
    --     placeholder'ı boş-string'e ('') düşürür; politikadaki NULLIF(...,'')::uuid
    --     bunu NULL'a çevirir → 0 satır, hata değil (DB.md §6.2).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', NULL, true);
    SELECT count(*) INTO n FROM call;
    IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED ihlali: scope yokken % call görüldü', n; END IF;

    -- (2) Tenant izolasyonu: E scope yalnız kendi kayıtlarını görür.
    PERFORM set_config('app.tenant_id', '55555555-5555-7555-8555-555555555555', true);
    SELECT count(*) INTO n FROM call;               IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % call gördü', n; END IF;
    SELECT count(*) INTO n FROM call_leg;           IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % call_leg gördü', n; END IF;
    SELECT count(*) INTO n FROM transcript;         IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % transcript gördü', n; END IF;
    SELECT count(*) INTO n FROM transcript_segment; IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % segment gördü', n; END IF;
    SELECT count(*) INTO n FROM recording;          IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % recording gördü', n; END IF;
    SELECT count(*) INTO n FROM call_event;         IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % call_event gördü', n; END IF;
    SELECT count(*) INTO n FROM tool_execution;     IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: E % tool_execution gördü', n; END IF;

    -- (3) Partition routing: Haziran 2026 çağrısı aylık partition'a (call_p202606)
    --     düştü — DEFAULT'a değil. tableoid ile RLS scope içinde doğrulanır
    --     (partition'a doğrudan erişime gerek yok).
    SELECT tableoid::regclass::text INTO r FROM call
     WHERE id = 'c0000000-0000-7000-8000-000000000001';
    IF r <> 'call_p202606' THEN
        RAISE EXCEPTION 'Partition routing ihlali: E çağrısı % partition''ında (call_p202606 beklenir)', r;
    END IF;

    -- (4) Cross-tenant WRITE engeli (WITH CHECK): E scope F çağrısı yazamaz.
    BEGIN
        INSERT INTO call (tenant_id, correlation_id, direction, region)
        VALUES ('66666666-6666-7666-8666-666666666666',
                'cabc0000-0000-7000-8000-0000000000ff', 'inbound', 'EU');
        RAISE EXCEPTION 'WITH CHECK ihlali: cross-tenant call insert geçti';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: RLS WITH CHECK reddi
    END;

    -- (5) İdempotency: aynı (tenant_id, idempotency_key, created_at) ikinci insert reddedilir.
    BEGIN
        INSERT INTO tool_execution
            (tenant_id, correlation_id, idempotency_key, status, created_at)
        VALUES ('55555555-5555-7555-8555-555555555555',
                'cabc0000-0000-7000-8000-000000000001', 'idem-1', 'success',
                TIMESTAMPTZ '2026-06-15 10:00:20+00');
        RAISE EXCEPTION 'İdempotency ihlali: duplicate tool_execution geçti';
    EXCEPTION WHEN unique_violation THEN
        NULL;  -- beklenen: UNIQUE (tenant_id, idempotency_key, created_at)
    END;

    -- (6) WORM (tool_execution): UPDATE reddedilir (grant yok + trigger backstop).
    BEGIN
        UPDATE tool_execution SET status = 'error'
         WHERE id = 'e0000000-0000-7000-8000-000000000001';
        RAISE EXCEPTION 'WORM ihlali: tool_execution UPDATE geçti';
    EXCEPTION WHEN insufficient_privilege OR integrity_constraint_violation THEN
        NULL;  -- beklenen: append-only (UPDATE yok)
    END;

    -- (7) WORM (tool_execution): DELETE reddedilir.
    BEGIN
        DELETE FROM tool_execution WHERE id = 'e0000000-0000-7000-8000-000000000001';
        RAISE EXCEPTION 'WORM ihlali: tool_execution DELETE geçti';
    EXCEPTION WHEN insufficient_privilege OR integrity_constraint_violation THEN
        NULL;  -- beklenen: append-only (DELETE yok)
    END;

    -- (8) Mutable çağrı kaydı GÜNCELLENEBİLİR: call.ended_at set edilir (WORM değil).
    UPDATE call SET ended_at = TIMESTAMPTZ '2026-06-15 10:05:00+00', end_reason = 'completed'
     WHERE id = 'c0000000-0000-7000-8000-000000000001';
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN RAISE EXCEPTION 'Mutable call UPDATE beklenen 1 satır, % oldu', n; END IF;

    -- (9) Platform realm: çağrı iş verisini varsayılan göremez (altın kural — L0 görmez).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', 'on', true);
    SELECT count(*) INTO n FROM transcript;
    IF n <> 0 THEN
        RAISE EXCEPTION 'altın kural ihlali: platform realm % transcript gördü (0 beklenir)', n;
    END IF;

    RAISE NOTICE 'TÜM ÇAĞRI/ETKİLEŞİM RLS+WORM+PARTITION ASSERTION''LARI GEÇTİ (9/9)';
END;
$$;

RESET ROLE;
