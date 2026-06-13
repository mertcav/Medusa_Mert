# `analytics/` — OLAP (ClickHouse/BigQuery) analitik şeması (WBS 1.1.9)

SAD §12.1 "Analytics — kolon-bazlı OLAP" yeteneğinin fiziksel şeması: dashboard & raporlama
(FR-ANA-*), faturalama agregasyonu (FR-BIL-*) için yıldız modeli (fact/dimension/rollup).
`db/`+`cache/`+`objstore/`+`eventstream/` disipliniyle aynı: **araç-nötr** (ADR-002),
**credential-free**, statik probe + opsiyonel canlı kapı.

> **Kaynak doğruluk:** `olap-spec.json` (makine-okunur). Çelişkide o; üstünde SAD/BRD esastır.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `olap-spec.json` | **Kaynak doğruluk:** 5 fact + 5 dimension + 4 rollup + engine/pii/retention/ingestion politikaları + invariant A1–A14 |
| `olap-schema.md` | Tasarım: mimari konum, sağlayıcı-nötrlük, yıldız modeli, PII, tenant izolasyon (4 katman), idempotent ingest, gereksinim kapsama |
| `olap_probe.py` | stdlib-only kapı: `validate` / `query` (deterministik izolasyon+agregasyon sim.) / `selftest` / `schema` |
| `ddl/clickhouse.sql` | ClickHouse DDL (ReplacingMergeTree + AggregatingMergeTree MV; `${OLAP_DB}` placeholder) |
| `ddl/bigquery.sql` | BigQuery DDL (PARTITION + CLUSTER + materialized view; `${OLAP_DS}` placeholder) |
| `ddl/row-policy.template.sql` | Defense-in-depth: ClickHouse ROW POLICY + BigQuery row-access-policy/authorized view şablonu (`${ENV}`) |
| `tests/aggregation_behavior_test.py` | Davranış kapısı T1–T5 (lineage/PII/maliyet/rollup/retention) |
| `run_live_test.sh` | Statik kapı + (clickhouse-client/bq + `${OLAP_DB}`/`${OLAP_DS}` varsa) canlı DDL uygula; yoksa SKIP |

## Çalıştırma

```bash
python3 analytics/olap_probe.py validate              # 434/434 PASS (çıkış 0)
python3 analytics/olap_probe.py query                 #   8/8 PASS
python3 analytics/olap_probe.py selftest              #  15/15 PASS
python3 analytics/tests/aggregation_behavior_test.py  #  12/12 PASS
bash    analytics/run_live_test.sh                     # canlı (varsa) / SKIP
```

## Özet kararlar

- **Yıldız modeli:** 5 fact (call/turn/usage/qa/campaign) + 5 dimension + 4 rollup MV.
- **Sağlayıcı-nötr:** her tablo hem ClickHouse hem BigQuery DDL'inde; mantıksal eş (probe A11 doğrular).
- **OLAP ham PII tutmaz:** her sütun pii_class ∈ {none, low, redacted}; transkript metni/ses/kart-OTP yok
  (FR-REC-004/005) — event stream I6 ile aynı doğrultu.
- **Tenant izolasyon (4 katman):** tenant_id ilk-anahtar + sorgu-katmanı zorunlu predicate (istemciye
  güvenilmez) + ROW POLICY/row-access-policy + per-region cluster (NFR 10.7).
- **İdempotent ingest:** dedup_key + ReplacingMergeTree/MERGE → at-least-once replay (1.1.8 P3) çift-saymaz.
- **Retention katmanı:** fct_turn 90g (yüksek hacim) → mv_turn_latency_daily 5y (quantileState); fct_usage
  2555g (no-loss fatura). TTL motor-tarafı zorlama (FR-REC-006/010, retention motoru 1.2.3 ile hizalı).
- **Lineage:** her fact bir 1.1.8 event stream topic'inden `analytics-ingest`/`olap-sink` ile beslenir.

**Sır/credential repoya yazılmadı** — endpoint/dataset/parola yalnız `${ENV}`. Vendor-neutral (ADR-002).
