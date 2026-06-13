-- =============================================================================
-- Live RLS + WORM + partition + karışık-politika davranış testi —
-- Outbound/Operasyon/Yönetişim (WBS 1.1.4 / 12.2.3)
-- →FR-TEN-002, FR-OUT-003, FR-IAM-006, FR-REC-009, SAD §13.1, DB.md §5.4/§5.6/§6/§7.2
--
-- Çalışan bir PostgreSQL gerektirir; 0001–0009 migration'ları uygulandıktan sonra
-- app_rw rolüyle (RLS bypass etmeyen) koşar. Her assertion başarısızsa transaction
-- RAISE EXCEPTION ile düşer → psql -v ON_ERROR_STOP=1 ile çıkış≠0.
-- Çalıştırma: db/run_live_test.sh (sunucu varsa). Statik kapı: schema_probe.py.
-- =============================================================================
\set ON_ERROR_STOP on
SET client_min_messages = warning;

-- Bağımsız test tenant'ları (önceki test dosyalarından ayrı UUID'ler).
SET app.platform = 'on';
INSERT INTO tenant (id, name, home_region, kms_key_ref) VALUES
    ('77777777-7777-7777-8777-777777777777', 'Tenant G', 'EU', 'kms://g'),
    ('88888888-8888-7888-8888-888888888888', 'Tenant H', 'EU', 'kms://h');

-- Aylık partition önceden açma (DB.md §7.2) — routing testi anlamlı olsun diye
-- DEFAULT'a düşmeden önce açılır. create_month_partition idempotent (0006).
SELECT create_month_partition('usage_record', DATE '2026-06-01');
SELECT create_month_partition('audit_log',    DATE '2026-06-01');
SELECT create_month_partition('call',         DATE '2026-06-01');

-- Platform realm: platform-geneli (tenant_id IS NULL) audit + incident kayıtları.
INSERT INTO audit_log
    (tenant_id, actor_realm, action, resource_type, row_hash, occurred_at, created_at) VALUES
    (NULL, 'platform', 'tenant:provision', 'tenant', '\x00'::bytea,
     TIMESTAMPTZ '2026-06-15 09:00:00+00', TIMESTAMPTZ '2026-06-15 09:00:00+00');
INSERT INTO incident (tenant_id, severity, title) VALUES
    (NULL, 'sev2', 'Region-wide latency blip');

SET app.platform = 'off';

-- ---------------------------------------------------------------------------
-- Tenant G: kampanya + bağlı kayıtlar, G scope altında.
-- ---------------------------------------------------------------------------
SET app.tenant_id = '77777777-7777-7777-8777-777777777777';

INSERT INTO campaign (id, tenant_id, name, status) VALUES
    ('a1000000-0000-7000-8000-000000000001',
     '77777777-7777-7777-8777-777777777777', 'Yaz Kampanyası', 'running');

INSERT INTO contact (id, tenant_id, campaign_id, e164, party_type) VALUES
    ('b1000000-0000-7000-8000-000000000001',
     '77777777-7777-7777-8777-777777777777',
     'a1000000-0000-7000-8000-000000000001', '+905551112233', 'individual');

INSERT INTO consent (tenant_id, contact_id, e164, purpose, country, state) VALUES
    ('77777777-7777-7777-8777-777777777777',
     'b1000000-0000-7000-8000-000000000001', '+905551112233', 'satış', 'TR', 'granted');

-- call referencing campaign G1 → yeni FK (0008 ALTER) + partition routing.
INSERT INTO call (id, tenant_id, correlation_id, campaign_id, direction, region, created_at) VALUES
    ('c1000000-0000-7000-8000-000000000001',
     '77777777-7777-7777-8777-777777777777',
     'cabc0000-0000-7000-8000-0000000000a1',
     'a1000000-0000-7000-8000-000000000001', 'outbound', 'EU',
     TIMESTAMPTZ '2026-06-15 10:00:00+00');

INSERT INTO call_evaluation (tenant_id, call_id, eval_type, scores) VALUES
    ('77777777-7777-7777-8777-777777777777',
     'c1000000-0000-7000-8000-000000000001', 'automatic', '{"csat":0.9}'::jsonb);

INSERT INTO usage_record (tenant_id, call_id, category, quantity, unit, cost, currency, created_at) VALUES
    ('77777777-7777-7777-8777-777777777777',
     'c1000000-0000-7000-8000-000000000001', 'llm', 1200, 'token', 0.004800, 'USD',
     TIMESTAMPTZ '2026-06-15 10:00:30+00');

-- Tenant-scoped audit (tenant_id = G) — karışık tabloya tenant satırı.
INSERT INTO audit_log
    (tenant_id, actor_realm, action, resource_type, row_hash, occurred_at, created_at) VALUES
    ('77777777-7777-7777-8777-777777777777', 'tenant', 'consent:withdraw', 'consent',
     '\x01'::bytea, TIMESTAMPTZ '2026-06-15 10:01:00+00', TIMESTAMPTZ '2026-06-15 10:01:00+00');

INSERT INTO incident (tenant_id, severity, title) VALUES
    ('77777777-7777-7777-8777-777777777777', 'sev3', 'Tenant CRM connector flaky');

-- Tenant H: tek kampanya (izolasyon karşı-örneği).
SET app.tenant_id = '88888888-8888-7888-8888-888888888888';
INSERT INTO campaign (tenant_id, name) VALUES
    ('88888888-8888-7888-8888-888888888888', 'H Kampanyası');

RESET app.platform;
RESET app.tenant_id;

-- Uygulama gibi davran: RLS bypass etmeyen rol.
SET ROLE app_rw;

DO $$
DECLARE n int; r text;
BEGIN
    -- (1) FAIL-CLOSED: scope yokken hiçbir satır görünmez (karışık tablolar dahil).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', NULL, true);
    SELECT count(*) INTO n FROM campaign;     IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED: % campaign', n; END IF;
    SELECT count(*) INTO n FROM audit_log;    IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED: % audit_log', n; END IF;
    SELECT count(*) INTO n FROM incident;     IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED: % incident', n; END IF;
    SELECT count(*) INTO n FROM usage_record; IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED: % usage_record', n; END IF;

    -- (2) Tenant G izolasyonu: yalnız kendi satırları (+ karışık tablolarda yalnız G).
    PERFORM set_config('app.tenant_id', '77777777-7777-7777-8777-777777777777', true);
    SELECT count(*) INTO n FROM campaign;        IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % campaign', n; END IF;
    SELECT count(*) INTO n FROM contact;         IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % contact', n; END IF;
    SELECT count(*) INTO n FROM consent;         IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % consent', n; END IF;
    SELECT count(*) INTO n FROM call_evaluation; IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % call_evaluation', n; END IF;
    SELECT count(*) INTO n FROM usage_record;    IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % usage_record', n; END IF;
    -- karışık tablolarda tenant realm platform (NULL) satırı GÖRMEZ → yalnız 1 (kendi).
    SELECT count(*) INTO n FROM audit_log;       IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % audit_log (1 beklenir, platform satırı görünmemeli)', n; END IF;
    SELECT count(*) INTO n FROM incident;        IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon: G % incident (1 beklenir)', n; END IF;

    -- (3) Partition routing: Haziran 2026 satırları aylık partition'a düştü (DEFAULT değil).
    SELECT tableoid::regclass::text INTO r FROM usage_record
     WHERE call_id = 'c1000000-0000-7000-8000-000000000001';
    IF r <> 'usage_record_p202606' THEN
        RAISE EXCEPTION 'Partition routing: usage_record % (usage_record_p202606 beklenir)', r;
    END IF;
    SELECT tableoid::regclass::text INTO r FROM audit_log WHERE action = 'consent:withdraw';
    IF r <> 'audit_log_p202606' THEN
        RAISE EXCEPTION 'Partition routing: audit_log % (audit_log_p202606 beklenir)', r;
    END IF;

    -- (4) Yeni FK (call.campaign_id → campaign): geçersiz kampanya reddedilir.
    BEGIN
        INSERT INTO call (tenant_id, correlation_id, campaign_id, direction, region)
        VALUES ('77777777-7777-7777-8777-777777777777',
                'cabc0000-0000-7000-8000-0000000000ee',
                'a1000000-0000-7000-8000-0000000000ff', 'outbound', 'EU');  -- yok
        RAISE EXCEPTION 'FK ihlali: geçersiz campaign_id call insert geçti';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;  -- beklenen: fk_call_campaign
    END;

    -- (5) Cross-tenant WRITE engeli (WITH CHECK): G scope H kampanyası yazamaz.
    BEGIN
        INSERT INTO campaign (tenant_id, name)
        VALUES ('88888888-8888-7888-8888-888888888888', 'sahte');
        RAISE EXCEPTION 'WITH CHECK ihlali: cross-tenant campaign insert geçti';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: RLS WITH CHECK reddi
    END;

    -- (6) WORM (consent): UPDATE reddedilir (grant yok + trigger backstop).
    BEGIN
        UPDATE consent SET state = 'withdrawn'
         WHERE contact_id = 'b1000000-0000-7000-8000-000000000001';
        RAISE EXCEPTION 'WORM ihlali: consent UPDATE geçti';
    EXCEPTION WHEN insufficient_privilege OR integrity_constraint_violation THEN
        NULL;  -- beklenen: append-only (opt-out = yeni satır)
    END;

    -- (7) WORM (audit_log): DELETE reddedilir.
    BEGIN
        DELETE FROM audit_log WHERE action = 'consent:withdraw';
        RAISE EXCEPTION 'WORM ihlali: audit_log DELETE geçti';
    EXCEPTION WHEN insufficient_privilege OR integrity_constraint_violation THEN
        NULL;  -- beklenen: WORM (hash-chain bütünlük)
    END;

    -- (8) Mutable tablo (incident): G kendi incident'ini GÜNCELLEYEBİLİR.
    UPDATE incident SET status = 'resolved', resolved_at = now()
     WHERE tenant_id = '77777777-7777-7777-8777-777777777777';
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN RAISE EXCEPTION 'Mutable incident UPDATE beklenen 1 satır, % oldu', n; END IF;

    -- (9) Tenant realm karışık tabloya SAHTE-platform (tenant_id NULL) yazamaz.
    BEGIN
        INSERT INTO incident (tenant_id, severity, title) VALUES (NULL, 'sev4', 'sahte-platform');
        RAISE EXCEPTION 'WITH CHECK ihlali: tenant realm platform(NULL) incident yazdı';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: ikinci kol yalnız platform realm'de doğru
    END;

    -- (10) Platform realm (altın kural): tenant iş verisini görmez; karışık tabloda
    --      YALNIZ platform (tenant_id IS NULL) satırlarını görür.
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', 'on', true);
    SELECT count(*) INTO n FROM contact;   IF n <> 0 THEN RAISE EXCEPTION 'altın kural: platform % contact gördü', n; END IF;
    SELECT count(*) INTO n FROM campaign;  IF n <> 0 THEN RAISE EXCEPTION 'altın kural: platform % campaign gördü', n; END IF;
    SELECT count(*) INTO n FROM audit_log; IF n <> 1 THEN RAISE EXCEPTION 'karışık RLS: platform % audit_log gördü (1 platform satırı beklenir, tenant satırı görünmemeli)', n; END IF;
    SELECT count(*) INTO n FROM incident;  IF n <> 1 THEN RAISE EXCEPTION 'karışık RLS: platform % incident gördü (1 beklenir)', n; END IF;

    -- (11) Platform realm tenant-spesifik satır YAZAMAZ (WITH CHECK ikinci kol NULL şartı).
    BEGIN
        INSERT INTO incident (tenant_id, severity, title)
        VALUES ('77777777-7777-7777-8777-777777777777', 'sev4', 'platform→tenant sahte');
        RAISE EXCEPTION 'WITH CHECK ihlali: platform realm tenant-spesifik incident yazdı';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: platform yalnız tenant_id IS NULL yazar
    END;

    RAISE NOTICE 'TÜM OUTBOUND/OPERASYON/YÖNETİŞİM RLS+WORM+PARTITION+KARIŞIK ASSERTION''LARI GEÇTİ (11/11)';
END;
$$;

RESET ROLE;
