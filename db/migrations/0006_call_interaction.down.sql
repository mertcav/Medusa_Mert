-- =============================================================================
-- Migration 0006 — DOWN. Partition'lı tabloları (partition'larıyla birlikte) ve
-- partition yardımcısını düşür. DROP TABLE partition'lı parent'ı + tüm
-- partition'larını (DEFAULT + aylık) birlikte düşürür.
-- =============================================================================

DROP TABLE IF EXISTS tool_execution;       -- trigger + partition'lar dahil
DROP TABLE IF EXISTS call_event;
DROP TABLE IF EXISTS recording;
DROP TABLE IF EXISTS transcript_segment;
DROP TABLE IF EXISTS transcript;
DROP TABLE IF EXISTS call_leg;
DROP TABLE IF EXISTS call;

DROP FUNCTION IF EXISTS create_month_partition(text, date);
