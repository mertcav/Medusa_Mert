-- =============================================================================
-- Migration 0001 — DOWN. Yardımcıları geri al (extension'lar başka migration'lar
-- için bırakılır; rol yalnız başka nesneye bağlı değilse düşürülür).
-- =============================================================================

DROP FUNCTION IF EXISTS raise_immutable_violation();
DROP FUNCTION IF EXISTS set_updated_at();
DROP FUNCTION IF EXISTS gen_uuid_v7();

-- app_rw'ye bağlı grant kalmadıysa düşür (aksi halde elle).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        DROP ROLE app_rw;
    END IF;
EXCEPTION WHEN dependent_objects_still_exist THEN
    RAISE NOTICE 'app_rw rolüne bağlı nesneler var; önce ilgili migration down çalıştırın.';
END;
$$;

-- citext / pgcrypto kasıtlı olarak bırakılır (başka şema bileşenleri kullanabilir).
