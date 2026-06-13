-- =============================================================================
-- Migration 0001 — Extensions, helper functions, DB roles (baz migration)
-- WBS 1.1.1 · F1 · →BRD §16, SAD §13.1 · DB.md §3, §6, §10
--
-- Bu migration, sonraki şema migration'larının dayandığı ortak zemini kurar:
--   - extension'lar (citext, pgcrypto) — DB.md §10
--   - gen_uuid_v7() — UUIDv7 (zaman-sıralı) PK üreteci (DB.md §3 "Konvansiyonlar")
--     PostgreSQL 16'da native uuidv7() yoktur; vendor-neutral plpgsql ile sağlanır.
--   - set_updated_at() — updated_at trigger fonksiyonu
--   - raise_immutable_violation() — WORM/append-only zorlama (DB.md §6.5)
--   - app_rw — RLS'i BYPASS ETMEYEN uygulama rolü (DB.md §6.1)
--
-- İleri-yönlü ve idempotent (DB.md §10). Geri alma: 0001_extensions_helpers.down.sql
-- =============================================================================

-- pgvector (kb_chunk, WBS 1.1.2/1.1.7) bu görevin kapsamı dışında; burada kurulmaz.
CREATE EXTENSION IF NOT EXISTS citext;     -- app_user.email (DB.md §5.1)
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_bytes() (gen_uuid_v7 için)

-- -----------------------------------------------------------------------------
-- gen_uuid_v7(): RFC 9562 UUIDv7 — 48-bit big-endian unix-ms zaman öneki +
-- 74-bit rastlantı; sürüm nibble = 0x7, variant üst bitleri = 0b10.
-- Zaman-sıralı olduğundan B-tree index fragmentasyonunu azaltır (DB.md §3).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gen_uuid_v7()
RETURNS uuid
LANGUAGE plpgsql
VOLATILE
PARALLEL SAFE
AS $$
DECLARE
    v_bytes bytea;
BEGIN
    -- 16 rastgele bayt ile başla
    v_bytes := gen_random_bytes(16);
    -- İlk 6 baytı 48-bit big-endian milisaniye zaman damgasıyla bindir.
    -- int8send 8 bayt döndürür; ilk 2 baytı atıp (substring ... from 3) 6 bayt alınır.
    v_bytes := overlay(
        v_bytes
        placing substring(
            int8send((extract(epoch from clock_timestamp()) * 1000)::bigint)
            from 3 for 6
        )
        from 1 for 6
    );
    -- Bayt 6 (0-index): yüksek nibble = sürüm 7 (0x70), düşük nibble korunur.
    v_bytes := set_byte(v_bytes, 6, ((get_byte(v_bytes, 6) & 15) | 112));
    -- Bayt 8 (0-index): üst iki bit = variant 0b10 (0x80), kalan bitler korunur.
    v_bytes := set_byte(v_bytes, 8, ((get_byte(v_bytes, 8) & 63) | 128));
    RETURN encode(v_bytes, 'hex')::uuid;
END;
$$;

COMMENT ON FUNCTION gen_uuid_v7() IS
    'RFC 9562 UUIDv7 (zaman-sıralı PK üreteci). DB.md §3. PG16 native uuidv7() yokluğunda vendor-neutral karşılık.';

-- -----------------------------------------------------------------------------
-- set_updated_at(): updated_at kolonunu otomatik güncelleyen trigger (DB.md §3).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- raise_immutable_violation(): WORM / append-only tablolarda UPDATE/DELETE reddi
-- (DB.md §6.5). Bu görevde global referans tablolarının (role/*) yazımını
-- engellemekte yedek güvence olarak da kullanılır.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION raise_immutable_violation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'immutable_row: "%" append-only/WORM; % reddedildi (DB.md §6.5)',
        TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

-- -----------------------------------------------------------------------------
-- Uygulama DB rolü: app_rw. RLS'i BYPASS ETMEZ (DB.md §6.1, P2 defense-in-depth).
-- Superuser/BYPASSRLS uygulama yolunda kullanılmaz. LOGIN/parola burada verilmez
-- (secret store; .gitignore — credential repoya yazılmaz).
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
        CREATE ROLE app_rw NOLOGIN;
    END IF;
END;
$$;
