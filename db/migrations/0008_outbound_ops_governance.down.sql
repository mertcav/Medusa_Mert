-- =============================================================================
-- Migration 0008 — DOWN. Önce 0006'da call'a eklenen campaign FK'sini, sonra
-- tabloları (partition'lılar partition'larıyla birlikte) FK bağımlılık sırasına
-- göre düşür. create_month_partition 0006'da tanımlı → BURADA düşürülmez.
-- =============================================================================

-- 0006'daki call'a eklenen gecikmeli FK önce kalkmalı (campaign drop'tan önce).
ALTER TABLE IF EXISTS call DROP CONSTRAINT IF EXISTS fk_call_campaign;

DROP TABLE IF EXISTS incident;
DROP TABLE IF EXISTS audit_log;           -- trigger + partition'lar dahil
DROP TABLE IF EXISTS usage_record;        -- partition'lar dahil
DROP TABLE IF EXISTS call_evaluation;
DROP TABLE IF EXISTS consent;             -- trigger dahil
DROP TABLE IF EXISTS contact;             -- campaign'den önce (FK)
DROP TABLE IF EXISTS campaign;
