-- =============================================================================
-- Migration 0010 — DOWN. KB tablolarını bağımlılık ters sırasında düşür.
-- kb_chunk → kb_document → knowledge_base (FK zinciri). HNSW indeksi + embedding
-- kolonu tablo ile birlikte düşer. pgvector extension'ı BIRAKILIR (başka şema
-- kullanabilir; 0001 deseni gibi extension'lar down'da düşürülmez).
-- =============================================================================

DROP TABLE IF EXISTS kb_chunk;        -- knowledge_base + kb_document'a kompozit FK
DROP TABLE IF EXISTS kb_document;     -- knowledge_base'e kompozit FK
DROP TABLE IF EXISTS knowledge_base;  -- tenant + agent'a FK
