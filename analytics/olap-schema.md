# OLAP Analitik Şeması — Tasarım (WBS 1.1.9)

> **Kaynak doğruluk:** `analytics/olap-spec.json` (makine-okunur). Çelişkide o; üstünde
> SAD §12.1 / BRD §15 / BRD §16 esastır. Bu belge tasarımı + gerekçeyi açıklar.
> Sağlayıcı-nötr (ADR-002), credential-free.

## 1. Amaç ve mimari konum

SAD §12.1'in **"Analytics — kolon-bazlı OLAP (ClickHouse / BigQuery)"** deposunu fiziksel şemaya
indirir: dashboard & raporlama (FR-ANA-*), faturalama agregasyonu (FR-BIL-*) ve gerçek-zamanlı
operasyon ekranı (FR-ANA-012) için sorgulanabilir agregat katmanı.

OLAP, **Analytics/Ops Plane**'dedir (SAD §4.2 "edge what's hot, centralize what's cold"). Data plane
(voice runtime) OLAP'a **doğrudan yazmaz**; event stream (WBS 1.1.8) tüketicileri (`analytics-ingest`,
`olap-sink`) olayları **asenkron** akıtır (FR-RES-011). OLAP hot-path'te değildir → SAD §20 gecikme
bütçesi dışında; tazelik hedefi ≤60s (FR-ANA-012, 0.4.7 panosu refresh ile hizalı).

```
data plane → event stream (1.1.8) → analytics-ingest/olap-sink → OLAP (fact/dim) → rollup (mv_*) → panolar/export
   (hot)         (async, durable)        (idempotent)            (kolon-depo)      (pre-agregat)   FR-ANA-*/FR-BIL-*
```

**Sınır (kritik):** OLAP **ham PII / transkript metni / ses TUTMAZ** — yalnız redacted/türetilmiş/
agregat metrik. Ham transkript+kayıt PostgreSQL (DB.md §5.5) + nesne depolama (1.1.6); bu, event
stream I6 (webhook'a ham PII yok) ile aynı doğrultuda — OLAP da tenant-facing rapor yüzeyidir.

## 2. Sağlayıcı-nötrlük (ADR-002)

ClickHouse **referans** implementasyondur (sütun-depo, partition'lı, agregasyon-optimize). Aynı
mantıksal şema BigQuery ile sağlanır; her tablo **hem** `ddl/clickhouse.sql` **hem** `ddl/bigquery.sql`
içinde tanımlıdır (probe A11 birebir doğrular). Eşleme:

| Kavram | ClickHouse | BigQuery |
|--------|-----------|----------|
| Partition | `PARTITION BY toYYYYMM(event_date)` | `PARTITION BY DATE_TRUNC(event_date, MONTH)` |
| Sıralama/pruning | `ORDER BY (tenant_id, …)` | `CLUSTER BY tenant_id, …` |
| Retention | `TTL event_date + INTERVAL n DAY` | `partition_expiration_days = n` |
| Dedup | `ReplacingMergeTree(ingested_at)` | streaming insert + periyodik `MERGE` |
| Rollup | `AggregatingMergeTree` + `MATERIALIZED VIEW` (`-State`) | `MATERIALIZED VIEW` (incremental) |

Tip eşlemesi `engine_neutral.type_mapping`'tedir (UUID↔STRING, LowCardinality↔STRING, Decimal↔NUMERIC…).

## 3. Şema (yıldız modeli)

**5 fact + 5 dimension + 4 rollup.**

### Fact tabloları

| Tablo | Grain | Kaynak topic | Sınıf | Partition | ORDER/CLUSTER (ilk=tenant) | TTL | Dedup |
|-------|-------|--------------|-------|-----------|----------------------------|-----|-------|
| `fct_call` | tamamlanan çağrı | voice.call.lifecycle.v1 | std | event_date | tenant_id, agent_id, started_at, call_id | 730g | call_id |
| `fct_turn` | tek tur (yüksek hacim) | voice.turn.telemetry.v1 | std | event_date | tenant_id, call_id, turn_seq | 90g | call_id+turn_seq |
| `fct_usage` | kullanım/maliyet | billing.usage.v1 | **no-loss** | event_date | tenant_id, agent_id, event_date, call_id | 2555g | idempotency_key |
| `fct_qa_evaluation` | çağrı QA | qa.evaluation.v1 | std | event_date | tenant_id, agent_id, event_date, call_id | 730g | evaluation_id |
| `fct_campaign_daily` | kampanya×gün | campaign.events.v1 | std | event_date | tenant_id, campaign_id, event_date | 730g | campaign_id+event_date |

### Dimension tabloları (config plane aynası, SCD-2)

`dim_tenant`, `dim_agent` (agent_version_id ile — FR-ANA-010 karşılaştırma boyutu), `dim_campaign`,
`dim_provider` ve `dim_date`. `dim_provider`/`dim_date` **tenant-bağımsız referans** boyuttur (A1 istisnası).

### Rollup'lar (materialized view / pre-agregat)

| Rollup | Kaynak | Grain | Pano FR |
|--------|--------|-------|---------|
| `mv_call_daily` | fct_call | tenant+agent+version+gün | FR-ANA-003/010/012 |
| `mv_turn_latency_daily` | fct_turn | tenant+agent+gün | FR-ANA-006/012 |
| `mv_usage_daily` | fct_usage | tenant+agent+provider+gün | FR-ANA-007/011/013, FR-BIL-002/007 |
| `mv_agent_version_perf` | fct_call | tenant+agent+version | FR-ANA-010 |

`mv_turn_latency_daily`, `fct_turn`'ün **kısa TTL'ini (90g)** telafi eder: latency percentile'ları
ClickHouse `quantileState` ile agregata taşınır (5y), ham tur metriği erir. Bu, yüksek-hacim ham
veri + uzun-ömür analiz dengesi.

## 4. PII politikası (A4 — FR-REC-004/005)

OLAP'taki **her sütun** `pii_class ∈ {none, low, redacted}`; `raw`/`sensitive` **yasak**. Probe her
sütunu tek tek doğrular. Tasarım kararları:
- Türetilmiş kategorikler (intent, disposition, end_reason, outbound_outcome) **düşük-kardinalite enum**,
  serbest metin değil → `low`.
- İnsan QA yorumu **metni** OLAP'a girmez; yalnız `human_comment_present` bayrağı + skor; metin
  PostgreSQL `call_evaluation`'da (DB.md §5.6).
- `tenant_id`/`call_id`/`agent_id` opak kimlik → `none` (kişisel veri değil; izolasyon anahtarı).

## 5. Tenant izolasyonu (A1/A7 — FR-TEN-002, NFR 10.7)

OLAP motorları PostgreSQL-tarzı FORCE RLS taşımaz; izolasyon **dört katman**:

1. **Şema:** `tenant_id` her fact/dim'de NOT NULL ve ORDER BY/CLUSTER **ilk anahtar** → predicate'siz
   tam-tarama engellenir + partition pruning.
2. **Sorgu katmanı (BİRİNCİL):** Analytics API (FastAPI control plane) her sorguya zorunlu
   `WHERE tenant_id = :ctx` enjekte eder — **istemciye güvenilmez** (DB.md §6 GUC/RLS deseninin OLAP eşi).
3. **Defense-in-depth:** ClickHouse `ROW POLICY` / BigQuery `row-access-policy` + authorized view
   (`ddl/row-policy.template.sql`), rol-başına tenant filtresi; `getSetting('SQL_tenant_id')` boşsa
   0 satır (fail-closed).
4. **Residency:** her home-region için **ayrı cluster/dataset** (NFR 10.7); cross-region yalnız
   agregat/anonim whitelisted.

**Altın kural:** Platform (L0) realm rollup/agregat metriği görür ama tenant iş içeriğini (transkript/PII)
göremez — OLAP zaten ham PII tutmadığından **yapısal** olarak desteklenir; ham fact erişimi break-glass'a
tabidir (FR-IAM-008).

## 6. İdempotent ingest & retention

- **İdempotent (A6, 1.1.8 P3):** her fact `dedup_key` taşır; ReplacingMergeTree(ingested_at) /
  MERGE upsert → event stream **at-least-once** replay'inde çift-sayım yok. `fct_usage` no-loss →
  `idempotency_key` ile fatura çift-saymaz (FR-BIL).
- **Retention (A3, FR-REC-006/010):** TTL/partition_expiration motoru zorlar; süre sonunda
  geri-döndürülemez silme retention motoru (WBS 1.2.3) + crypto-shred (1.1.6) ile. Gün değerleri
  **mühendislik varsayılanı** (BRD §22 açık karar); `cp.retention.*` yalnız **sıkılaştırır** (DPIA
  most-restrictive-wins).

## 7. Gereksinim kapsama (BRD §15 / FR-ANA / FR-BIL)

| Gereksinim | Karşılanma |
|------------|-----------|
| FR-ANA-002 (sonuç/intent/disposition) | `fct_call.intent/disposition/completion_status` |
| FR-ANA-003 (containment/transfer) | `fct_call.contained/transferred` → `mv_call_daily` oranlar |
| FR-ANA-004 (yanlış bilgi/tool/güvenlik) | `fct_call.flag_*`, `fct_qa_evaluation.flag_*` |
| FR-ANA-005 (konuşma süreleri) | `fct_call.talk_sec_user/talk_sec_agent/silence_sec` |
| FR-ANA-006 (STT/LLM/TTS/toplam gecikme) | `fct_turn.{stt,llm_first_token,tts_first_byte,e2e}_latency` → `mv_turn_latency_daily` |
| FR-ANA-007 (maliyet call/agent/tenant/provider) | `fct_usage.cost_*_micro` + `provider_*` → `mv_usage_daily` |
| FR-ANA-008 (kritik işaretleme) | `fct_call.flag_critical`, `fct_qa_evaluation.critical_flag` |
| FR-ANA-009 (QA skor/açıklama) | `fct_qa_evaluation.human_score/human_comment_present` |
| FR-ANA-010 (sürüm karşılaştırma) | `agent_version_id` (call/turn/qa) → `mv_agent_version_perf` |
| FR-ANA-011 (export) | rollup + authorized view export |
| FR-ANA-012 (gerçek-zamanlı ekran) | ≤60s tazelik + `mv_call_daily`/`mv_turn_latency_daily` |
| FR-ANA-013 (çağrı başı kaynak) | `fct_usage.cpu_ms/mem_peak_mb/concurrency_peak` |
| FR-BIL-001/002 (kullanım/maliyet kalemleri) | `fct_usage.billed_seconds/billed_minutes/cost_*_micro` |
| FR-BIL-007 (finans aktarımı) | `mv_usage_daily` export |
| FR-OUT-008 (voicemail/busy/no-answer/invalid) | `fct_call.outbound_outcome`, `fct_campaign_daily.*` |
| BRD §15 (teknik metrik) | `fct_turn` (jitter/loss/codec/SIP/token/confidence/retry/provider hata) |
| FR-TEN-002 | tenant_id ilk-anahtar + sorgu predicate + row-policy |
| NFR 10.7 | per-region cluster/dataset; home-region residency |

## 8. Doğrulama (kapılar)

```
python3 analytics/olap_probe.py validate              # 434/434 PASS (A1–A14 + DDL + sır)
python3 analytics/olap_probe.py query                 #   8/8 PASS (izolasyon + rollup doğruluğu + PII reddi)
python3 analytics/olap_probe.py selftest              #  15/15 PASS (her kapı kötü-spec ile tetiklenir)
python3 analytics/tests/aggregation_behavior_test.py  #  12/12 PASS (T1–T5 lineage/PII/maliyet/rollup/retention)
bash    analytics/run_live_test.sh                     # statik + (clickhouse-client/bq varsa) canlı / SKIP
```

`query`, gerçek motor yerine **deterministik in-memory** simülasyondur (objstore access-decision
deseni): predicate'siz sorgu fail-closed reddedilir, tenant izolasyonu cross-tenant sızıntı=0,
`mv_call_daily` agregasyonu elle hesapla birebir (containment_rate=0.75), PII projeksiyonu reddedilir,
at-least-once duplicate dedup_key ile tek sayılır.

## 9. Sınırlar / sonraki adımlar

- Bağlayıcı motor seçimi (ClickHouse vs BigQuery) **provizyonel** (0.2.6/0.3.x); tasarım vendor-neutral.
- Partition/granularity değerleri illüstratif; canlı hacim (0.4.8 / F1) ile kalibre edilir.
- BigQuery'de p95 percentile: MV non-deterministik agregat sınırı nedeniyle `APPROX_QUANTILES` scheduled
  query ile yenilenen tabloda; ClickHouse `quantileState` MV içinde doğrudan.
- Retention motoru (1.2.3) + residency zorlama (1.2.2) bu TTL/per-region sözleşmesini tüketir.
- Redaction motoru implementasyonu (FR-REC-004) ileri WBS; OLAP yalnız redacted girdi alır (sözleşme).

---
**Sır/credential repoya yazılmadı** — endpoint/dataset/parola yalnız `${ENV}`. Vendor-neutral (ADR-002).
