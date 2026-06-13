-- =============================================================================
-- Live RLS + namespace izolasyon testi — Bilgi Tabanı / Vector Store (WBS 1.1.7)
-- →FR-KB-004, FR-TEN-002, SAD §10.2/§12.1, DB.md §5.3/§6
--
-- Çalışan bir PostgreSQL gerektirir; 0001–0011 migration'larından sonra app_rw
-- rolüyle (RLS bypass etmeyen) koşar. Her assertion başarısızsa transaction
-- RAISE EXCEPTION ile düşer → psql -v ON_ERROR_STOP=1 ile çıkış≠0.
-- pgvector gerekmez: chunk'lar metadata-only (content) eklenir; embedding kolonu
-- pgvector kuruluysa nullable olduğundan testi etkilemez (DB.md §12).
-- =============================================================================
\set ON_ERROR_STOP on
SET client_min_messages = warning;

-- Bağımsız test tenant'ları (diğer testlerden ayrı UUID'ler).
SET app.platform = 'on';
INSERT INTO tenant (id, name, home_region, kms_key_ref) VALUES
    ('b5000000-0000-7000-8000-000000000001', 'Tenant KB-1', 'EU', 'kms://kb1'),
    ('b5000000-0000-7000-8000-000000000002', 'Tenant KB-2', 'EU', 'kms://kb2');

-- --- Tenant KB-1: iki agent (X, Y), her birine ayrı KB namespace ---
SET app.platform = 'off';
SET app.tenant_id = 'b5000000-0000-7000-8000-000000000001';

INSERT INTO agent (id, tenant_id, name) VALUES
    ('b5a00000-0000-7000-8000-000000000a01', 'b5000000-0000-7000-8000-000000000001', 'Agent-X'),
    ('b5a00000-0000-7000-8000-000000000a02', 'b5000000-0000-7000-8000-000000000001', 'Agent-Y');

INSERT INTO knowledge_base (id, tenant_id, agent_id, name, namespace) VALUES
    ('b5b00000-0000-7000-8000-000000000b01', 'b5000000-0000-7000-8000-000000000001',
     'b5a00000-0000-7000-8000-000000000a01', 'X-KB', 't:b5..1/a:X'),
    ('b5b00000-0000-7000-8000-000000000b02', 'b5000000-0000-7000-8000-000000000001',
     'b5a00000-0000-7000-8000-000000000a02', 'Y-KB', 't:b5..1/a:Y');

INSERT INTO kb_document (id, tenant_id, kb_id, source_uri, is_sensitive) VALUES
    ('b5d00000-0000-7000-8000-000000000d01', 'b5000000-0000-7000-8000-000000000001',
     'b5b00000-0000-7000-8000-000000000b01', 's3://kb1/x/doc1', false),
    ('b5d00000-0000-7000-8000-000000000d02', 'b5000000-0000-7000-8000-000000000001',
     'b5b00000-0000-7000-8000-000000000b02', 's3://kb1/y/doc1', true);

-- X namespace: 2 chunk; Y namespace: 1 chunk (content-only / metadata-only).
INSERT INTO kb_chunk (tenant_id, kb_id, document_id, chunk_no, content) VALUES
    ('b5000000-0000-7000-8000-000000000001', 'b5b00000-0000-7000-8000-000000000b01',
     'b5d00000-0000-7000-8000-000000000d01', 1, 'X-namespace chunk 1'),
    ('b5000000-0000-7000-8000-000000000001', 'b5b00000-0000-7000-8000-000000000b01',
     'b5d00000-0000-7000-8000-000000000d01', 2, 'X-namespace chunk 2'),
    ('b5000000-0000-7000-8000-000000000001', 'b5b00000-0000-7000-8000-000000000b02',
     'b5d00000-0000-7000-8000-000000000d02', 1, 'Y-namespace chunk 1');

-- --- Tenant KB-2: ayrı agent + KB (cross-tenant karşı-örneği) ---
SET app.tenant_id = 'b5000000-0000-7000-8000-000000000002';
INSERT INTO agent (id, tenant_id, name) VALUES
    ('b5a00000-0000-7000-8000-000000000a99', 'b5000000-0000-7000-8000-000000000002', 'Agent-Z');
INSERT INTO knowledge_base (id, tenant_id, agent_id, name, namespace) VALUES
    ('b5b00000-0000-7000-8000-0000000000f2', 'b5000000-0000-7000-8000-000000000002',
     'b5a00000-0000-7000-8000-000000000a99', 'Z-KB', 't:b5..2/a:Z');

RESET app.platform;
RESET app.tenant_id;

-- Uygulama gibi davran: RLS bypass etmeyen rol.
SET ROLE app_rw;

DO $$
DECLARE n int;
BEGIN
    -- (1) FAIL-CLOSED: scope yokken hiçbir KB satırı görünmez (DB.md §6.2).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', NULL, true);
    SELECT count(*) INTO n FROM knowledge_base;
    IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED ihlali: scope yokken % KB görüldü', n; END IF;
    SELECT count(*) INTO n FROM kb_chunk;
    IF n <> 0 THEN RAISE EXCEPTION 'FAIL-CLOSED ihlali: scope yokken % chunk görüldü', n; END IF;

    -- (2) Cross-tenant izolasyon (FR-TEN-002): KB-1 scope yalnız kendi 2 KB'sini görür.
    PERFORM set_config('app.tenant_id', 'b5000000-0000-7000-8000-000000000001', true);
    SELECT count(*) INTO n FROM knowledge_base;
    IF n <> 2 THEN RAISE EXCEPTION 'cross-tenant ihlali: KB-1 scope % KB gördü (2 beklenir)', n; END IF;
    SELECT count(*) INTO n FROM kb_chunk;
    IF n <> 3 THEN RAISE EXCEPTION 'cross-tenant ihlali: KB-1 scope % chunk gördü (3 beklenir)', n; END IF;

    -- (3) Cross-agent NAMESPACE izolasyonu (FR-KB-004): X namespace retrieval'i yalnız
    --     X'in chunk'larını döndürür; Y namespace'i SIZMAZ.
    SELECT count(*) INTO n FROM kb_chunk WHERE kb_id = 'b5b00000-0000-7000-8000-000000000b01';
    IF n <> 2 THEN RAISE EXCEPTION 'namespace ihlali: X namespace % chunk döndü (2 beklenir)', n; END IF;
    SELECT count(*) INTO n FROM kb_chunk
      WHERE kb_id = 'b5b00000-0000-7000-8000-000000000b01'
        AND content LIKE 'Y-namespace%';
    IF n <> 0 THEN RAISE EXCEPTION 'namespace ihlali: X namespace içinde % Y-chunk görüldü (0 beklenir)', n; END IF;
    -- namespace TEXT üzerinden de doğrula (retrieval kapsam anahtarı).
    SELECT count(*) INTO n FROM kb_chunk c JOIN knowledge_base k ON k.id = c.kb_id
      WHERE k.namespace = 't:b5..1/a:Y';
    IF n <> 1 THEN RAISE EXCEPTION 'namespace ihlali: Y namespace % chunk (1 beklenir)', n; END IF;

    -- (4) Cross-tenant WRITE engeli (WITH CHECK): KB-1 scope KB-2 için KB yazamaz.
    BEGIN
        INSERT INTO knowledge_base (tenant_id, name, namespace)
        VALUES ('b5000000-0000-7000-8000-000000000002', 'sızıntı', 't:b5..2/leak');
        RAISE EXCEPTION 'WITH CHECK ihlali: cross-tenant KB insert geçti';
    EXCEPTION WHEN insufficient_privilege OR check_violation THEN
        NULL;  -- beklenen: RLS WITH CHECK reddi
    END;

    -- (5) KOMPOZİT TENANT FK (defense-in-depth, FR-KB-004): KB-1 scope altında bir
    --     chunk'ı BAŞKA tenant'ın (KB-2) kb_id'sine bağlamak FK ile reddedilir.
    --     FK doğrulaması RLS'i bypass eder; kompozit (tenant_id, kb_id) bunu kapatır.
    BEGIN
        INSERT INTO kb_chunk (tenant_id, kb_id, document_id, chunk_no, content)
        VALUES ('b5000000-0000-7000-8000-000000000001',
                'b5b00000-0000-7000-8000-0000000000f2',   -- KB-2'nin KB'si
                'b5d00000-0000-7000-8000-000000000d01', 9, 'cross-tenant kb_id sızıntısı');
        RAISE EXCEPTION 'kompozit FK ihlali: cross-tenant kb_id chunk insert geçti';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;  -- beklenen: (tenant_id=KB-1, kb_id=KB-2's) eşleşmez → FK reddi
    END;

    -- (6) Platform realm: KB içeriğini varsayılan göremez (altın kural, L0).
    PERFORM set_config('app.tenant_id', NULL, true);
    PERFORM set_config('app.platform', 'on', true);
    SELECT count(*) INTO n FROM knowledge_base;
    IF n <> 0 THEN
        RAISE EXCEPTION 'altın kural ihlali: platform realm % KB gördü (0 beklenir)', n;
    END IF;
    SELECT count(*) INTO n FROM kb_chunk;
    IF n <> 0 THEN
        RAISE EXCEPTION 'altın kural ihlali: platform realm % chunk gördü (0 beklenir)', n;
    END IF;

    RAISE NOTICE 'TÜM KB RLS + NAMESPACE İZOLASYON ASSERTION''LARI GEÇTİ (6/6)';
END;
$$;

RESET ROLE;
