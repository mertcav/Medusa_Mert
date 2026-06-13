-- =============================================================================
-- Migration 0004 — DOWN. Dairesel FK'yi kaldır, tabloları bağımlılık ters
-- sırasında düşür.
-- =============================================================================

-- Önce dairesel FK (aksi halde agent_version düşürülemez).
ALTER TABLE IF EXISTS agent DROP CONSTRAINT IF EXISTS fk_agent_active_version;

DROP TABLE IF EXISTS agent_version;       -- agent/prompt/flow/profile'lara FK
DROP TABLE IF EXISTS prompt;              -- agent'a FK
DROP TABLE IF EXISTS conversation_flow;   -- agent'a FK
DROP TABLE IF EXISTS voice_profile;
DROP TABLE IF EXISTS model_profile;
DROP TABLE IF EXISTS stt_profile;
DROP TABLE IF EXISTS agent;
