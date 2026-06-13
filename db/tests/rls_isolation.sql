-- =============================================================================
-- Live RLS davranış testi — Tenant, Org Unit, User (WBS 1.1.1 / 12.2.3)
-- →FR-TEN-002, SAD §13.1, DB.md §6
--
-- Çalışan bir PostgreSQL gerektirir; migration'lar + seed uygulandıktan sonra
-- app_rw rolüyle koşar (RLS bypass etmeyen rol). Her assertion başarısızsa
-- transaction RAISE EXCEPTION ile düşer → psql -v ON_ERROR_STOP=1 ile çıkış≠0.
-- Çalıştırma: db/run_live_test.sh (sunucu varsa). Statik kapı: schema_probe.py.
-- =============================================================================
\set ON_ERROR_STOP on
SET client_min_messages = warning;

-- Test verisi kurulumu. FORCE RLS owner'a da uygulandığından (ve superuser
-- dışında) her insert WITH CHECK'e uyacak GUC bağlamında yazılır. (Superuser
-- koşumunda RLS zaten bypass; aşağıdaki bağlam her iki durumda da doğrudur.)
SET app.platform = 'on';
INSERT INTO tenant (id, name, home_region, kms_key_ref) VALUES
    ('11111111-1111-7111-8111-111111111111', 'Tenant A', 'EU', 'kms://a'),
    ('22222222-2222-7222-8222-222222222222', 'Tenant B', 'EU', 'kms://b');
-- Platform (L0) kullanıcısı: tenant_id NULL + platform realm.
INSERT INTO app_user (tenant_id, realm, email) VALUES
    (NULL, 'platform', 'root@rmctech.co.uk');

-- Tenant A satırları, A scope altında.
SET app.platform = 'off';
SET app.tenant_id = '11111111-1111-7111-8111-111111111111';
INSERT INTO organisation_unit (tenant_id, type, name) VALUES
    ('11111111-1111-7111-8111-111111111111', 'department', 'A-Ops');
INSERT INTO app_user (tenant_id, realm, email) VALUES
    ('11111111-1111-7111-8111-111111111111', 'tenant', 'a@example.com');

-- Tenant B satırları, B scope altında.
SET app.tenant_id = '22222222-2222-7222-8222-222222222222';
INSERT INTO organisation_unit (tenant_id, type, name) VALUES
    ('22222222-2222-7222-8222-222222222222', 'department', 'B-Ops');
INSERT INTO app_user (tenant_id, realm, email) VALUES
    ('22222222-2222-7222-8222-222222222222', 'tenant', 'b@example.com');

RESET app.platform;
RESET app.tenant_id;

-- Uygulama gibi davran: RLS bypass etmeyen rol.
SET ROLE app_rw;

DO $$
DECLARE n int;
BEGIN
    -- (1) FAIL-CLOSED: hiçbir GUC yok → hiçbir satır görünmez.
    PERFORM set_config('app.tenant_id', '', true);
    PERFORM set_config('app.platform', '', true);
    SELECT count(*) INTO n FROM organisation_unit;
    IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED ihlali: scope yokken % satır görüldü', n; END IF;

    -- (2) Tenant izolasyonu: A scope'u yalnız A satırını görür.
    PERFORM set_config('app.tenant_id', '11111111-1111-7111-8111-111111111111', true);
    SELECT count(*) INTO n FROM organisation_unit;
    IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon ihlali: A scope % org_unit gördü (1 beklenir)', n; END IF;
    SELECT count(*) INTO n FROM app_user;
    IF n <> 1 THEN RAISE EXCEPTION 'İzolasyon ihlali: A scope % app_user gördü (1 beklenir)', n; END IF;

    -- (3) tenant Root politikası: A yalnız kendi tenant satırını görür.
    SELECT count(*) INTO n FROM tenant;
    IF n <> 1 THEN RAISE EXCEPTION 'tenant self ihlali: A scope % tenant gördü', n; END IF;

    -- (4) Cross-tenant WRITE engeli (WITH CHECK): A scope'u B satırı yazamaz.
    BEGIN
        INSERT INTO organisation_unit (tenant_id, type, name)
        VALUES ('22222222-2222-7222-8222-222222222222', 'brand', 'x');
        RAISE EXCEPTION 'WITH CHECK ihlali: cross-tenant insert geçti';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: RLS WITH CHECK reddi
    END;

    -- (5) Platform realm tümünü görür.
    PERFORM set_config('app.tenant_id', '', true);
    PERFORM set_config('app.platform', 'on', true);
    SELECT count(*) INTO n FROM tenant;
    IF n <> 2 THEN RAISE EXCEPTION 'platform görünürlük ihlali: % tenant (2 beklenir)', n; END IF;
    SELECT count(*) INTO n FROM app_user WHERE tenant_id IS NULL;
    IF n <> 1 THEN RAISE EXCEPTION 'platform app_user görünürlük ihlali: %', n; END IF;

    -- (6) Global rol tablosu app_rw'ye salt-okunur: yazım reddedilir.
    BEGIN
        INSERT INTO role (code, level) VALUES ('hacker_role', 'L0');
        RAISE EXCEPTION 'role write engeli ihlali: app_rw role yazabildi';
    EXCEPTION WHEN insufficient_privilege THEN
        NULL;  -- beklenen: GRANT yalnız SELECT
    END;

    RAISE NOTICE 'TÜM RLS ASSERTION''LARI GEÇTİ (6/6)';
END;
$$;

RESET ROLE;

-- (7) gen_uuid_v7 sürüm/variant bitleri doğru mu?
DO $$
DECLARE u uuid; s text;
BEGIN
    u := gen_uuid_v7();
    s := replace(u::text, '-', '');
    IF substr(s, 13, 1) <> '7' THEN
        RAISE EXCEPTION 'UUIDv7 sürüm nibble hatalı: %', substr(s,13,1);
    END IF;
    IF position(substr(s, 17, 1) IN '89ab') = 0 THEN
        RAISE EXCEPTION 'UUIDv7 variant nibble hatalı: %', substr(s,17,1);
    END IF;
    RAISE NOTICE 'UUIDv7 bit kontrolü GEÇTİ';
END;
$$;
