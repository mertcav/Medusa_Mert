# Event stream (Kafka) — Topic tasarımı + replay politikası (WBS 1.1.8)

**Faz:** F1 · **Öncelik:** Must · **İz:** ADR-007, FR-RES-011, SAD §4.2/§12.1/§13.1, BRD §15, API §10

> **Kaynak doğruluk:** makine-okunur `topic-spec.json`. Bu belge tasarımı açıklar; çelişkide
> `topic-spec.json` (ve üstünde ADR-007 / SAD / BRD) esastır. Sağlayıcı-nötr (ADR-002):
> "Kafka" referans implementasyondur; sözleşme bölgesel eşdeğerle (MSK/Redpanda/Confluent/
> Event Hubs-Kafka API/Pulsar-KoP) sağlanabilir.

## 1. Amaç ve mimari konum

ADR-007: transkripsiyon-sonrası analitik, QA, PII redaction, faturalama ve raporlama gibi
**gerçek zamanlı olmayan** işler hot path'te yapılırsa gecikme (NFR 10.1) ve density (NFR 10.2)
bozulur. Çözüm: çağrı olayları dayanıklı bir **event stream**'e (Kafka) yazılır; non-RT tüketiciler
**asenkron** çalışır ve gerekince **replay** edilir (FR-RES-011).

```
  DATA PLANE (hot path, Go/Rust)                ANALYTICS / OPS PLANE (async, batch)
  ┌───────────────────────────┐   events   ┌──────────────────────────────────────────┐
  │ Conversation Orchestrator ├──────────► │ Event Stream (Kafka)                      │
  │ (turn loop, ADR-003)      │  (async)   │   ├─ analytics-ingest → OLAP (1.1.9)      │
  └───────────────────────────┘            │   ├─ pii-redaction → redacted topic       │
                                           │   ├─ billing-aggregator → Usage/OLAP      │
                                           │   ├─ qa-eval → Call Evaluation            │
                                           │   ├─ webhook-dispatcher → tenant (API §10) │
                                           │   └─ audit-worm-sink → WORM + SIEM        │
                                           └──────────────────────────────────────────┘
```

Event stream **Analytics/Ops Plane**'dedir (RMC-operated). Tenant'lar Kafka'dan **doğrudan
tüketmez**; tenant-facing tek yüzey **webhook**'tur (API §10). Bu, plane ayrımıyla (ADR-004) hizalı.

## 2. Topic tasarım ilkeleri

| İlke | Karar | Gerekçe |
|------|-------|---------|
| **Granülerlik** | Domain/aggregate başına topic (tek dev topic değil) | Bağımsız retention/ACL/ölçek; tüketici izolasyonu |
| **Adlandırma** | `<domain>.<subject>.v<major>` (I1) | Kırıcı şema değişimi → yeni `.vN` topic (geriye-uyumsuz evrim topic adında) |
| **Partition anahtarı** | `call_id` (çağrı-akışı) veya `tenant_id` (tenant-akışı) — tenant-türetilebilir (I2) | Partition-içi **sıra** + cross-tenant etiketleme |
| **Partition sayısı** | Hacme göre (telemetri 48, lifecycle 24, kampanya 6) | Tüketici paralelliği; sıcak-partition'ı önler |
| **Dayanıklılık** | RF=3, `min.insync.replicas=2`, `acks=all`, idempotent producer, unclean-leader kapalı (I4) | ADR-007 "dayanıklı, kayıpsız"; tek-mesaj kaybı yok |
| **Cleanup** | Çoğunda `delete` (zaman-retention); `config.snapshot` `compact,delete` (son-durum) | Olay-log vs durum-log ayrımı |
| **PII tiering** | `raw` transkript kısa+kısıtlı; `redacted` uzun (I5/I6) | Veri minimizasyonu (FR-REC-004); ham PII webhook'a sızmaz |
| **Residency** | Her home-region için ayrı cluster (I8) | NFR 10.7; ham PII bölge-pinned |
| **DLQ** | Her topic → `platform.dlq.v1`; manuel replay (I9) | Poison mesaj hattı tıkamaz |

## 3. Topic kataloğu (13 topic)

| Topic | Anahtar | Part. | Retention | Cleanup | PII | Sınıf | Üretilen olaylar | Replay |
|-------|---------|------:|-----------|---------|-----|-------|------------------|--------|
| `voice.call.lifecycle.v1` | call_id | 24 | 7g | delete | low | std | call.started/completed/transferred/failed | open |
| `voice.turn.telemetry.v1` | call_id | 48 | 72s | delete | low | std | turn.metrics (gecikme/jitter/token) | open |
| `voice.transcript.raw.v1` | call_id | 24 | 24s | delete | **raw** | std | transcript.segment.raw | **restricted** |
| `voice.transcript.redacted.v1` | call_id | 24 | 30g | delete | redacted | std | transcript.ready | open |
| `voice.recording.events.v1` | call_id | 12 | 7g | delete | reference | std | recording.ready | open |
| `ops.tool.execution.v1` | tenant_id | 24 | 14g | delete | redacted | std | tool.async.completed | open |
| `billing.usage.v1` | tenant_id | 24 | 35g | delete | low | **no-loss** | usage.metered | open |
| `qa.evaluation.v1` | call_id | 12 | 30g | delete | redacted | std | qa.evaluation.completed | open |
| `governance.audit.v1` | tenant_id | 12 | 365g | delete | redacted | **no-loss** | audit.event | **restricted** |
| `campaign.events.v1` | tenant_id | 6 | 30g | delete | low | std | campaign.completed | open |
| `ops.quota.alerts.v1` | tenant_id | 6 | 7g | delete | none | std | quota.threshold | open |
| `config.snapshot.v1` | tenant_id | 6 | 90g+compact | compact,delete | none | std | agent.published, config.updated | open |
| `platform.dlq.v1` | tenant_id | 12 | 14g | delete | redacted | std | dlq.message | **manual** |

**Transkript iki-aşaması (PII tiering).** `…transcript.raw.v1` (24s, kısıtlı ACL, tek tüketici
`pii-redaction`) → maskelenip `…transcript.redacted.v1` (30g) üretilir. QA/analitik/webhook/
transcript-store **yalnız** redacted'ı tüketir. Böylece ham PII'nin ömrü minimize edilir (FR-REC-004)
ve tenant-facing yüzeye **asla** ham PII sızmaz (I6).

**no-loss sınıfı.** `billing.usage` ve `governance.audit` fatura/denetim doğruluğu için kritik:
RF=3 + `min.insync.replicas=2` + `acks=all` + idempotent tüketici (çift-saymaz) + retention ≥30g
(mutabakat penceresi, I10).

**Compacted state topic.** `config.snapshot.v1` log-compaction ile **key başına son-durum**'u
kalıcı tutar → runtime config cache'i (SAD §4 "config cached at runtime") bundan materyalize edilir;
`agent.published` gibi yaşam döngüsü olayları da burada (webhook'a köprülenir).

## 4. Envelope sözleşmesi

`schemas/event-envelope.schema.json` — API §10.1 webhook envelope'unun **üst kümesi**. Zorunlu:
`id, type, api_version, schema_version, created_at, event_time, tenant_id, correlation_id,
idempotency_key, partition_key, pii_class, producer, data`.

- **`id`** — olay tekilliği; tüketici **dedup** anahtarı (at-least-once → idempotent).
- **`idempotency_key`** — üretici-tarafı tekillik (call_id+seq, execution_id); çift yan-etki önler.
- **`correlation_id`** — çağrı boyu izleme; trace/log/event'i bağlar (BRD §15, SAD §17.1).
- **`pii_class`** — topic pii_class'ı ile tutarlı olmalı (üretim-tarafı kontrol, I5).
- **webhook indirgemesi** — `webhook-dispatcher`, envelope'tan **yalnız** tenant-facing alanları
  (`id/type/api_version/created_at/tenant_id/correlation_id/data`) bırakır; iç alanlar (idempotency_key,
  partition_key, producer) **sızmaz** (`tests/envelope_behavior_test.py` T4).

**Şema evrimi.** schema-registry uyumluluğu **BACKWARD** (envelope/billing/audit **FULL**):
opsiyonel-alan ekleme güvenli; kırıcı değişim BACKWARD'ı geçemez → yeni `.vN` topic + dual-write.

## 5. Teslimat & sıra semantiği

- **Üretici:** idempotent producer + `acks=all` + `max.in.flight=5` (idempotence ile sıra korunur).
- **Teslimat:** **at-least-once**; tüketici **idempotent** (envelope.id dedup) — exactly-once *etki*
  uygulama katmanında (upsert/ON CONFLICT), broker-tarafı EOS'a bağımlı değil (sağlayıcı-nötr).
- **Sıra:** yalnız **partition-içi** garanti (anahtar=call_id/tenant_id). Cross-partition global sıra
  garanti edilmez — API §10.1 ile tutarlı; tüketici `created_at`/seq ile sıralar.

## 6. Replay politikası (ADR-007 çekirdeği)

`topic-spec.json → global_replay_policy` (P1–P8). Özet:

1. **P1 — Canlı offset dokunulmaz.** Replay ayrı, geçici grup (`replay-<consumer>-<window>`) ile;
   canlı işlemeyi etkilemez.
2. **P2 — Pencere retention ile sınırlı.** Daha eskisi (örn. 90g öncesi fatura mutabakatı)
   **tiered/cold** depodan (nesne depolama / OLAP / PostgreSQL) rehydrate edilir — Kafka log'undan değil.
3. **P3 — İdempotent tüketici.** at-least-once + envelope.id dedup → replay **çift yan-etki üretmez**
   (FR-TOOL-009 deseni). `eventstream_probe.py replay` bunu deterministik kanıtlar (duplicate e3 → 1 etki).
4. **P4 — PII gate.** `raw|sensitive` topic replay'i **yetkilendirme + audit** gerektirir (break-glass-
   hizalı, FR-IAM-008/009); replay tenant-facing webhook'a **yeniden export edilmez**, redaction yeniden koşar.
5. **P5 — Sıra korunur** (partition-içi); replay pencere-içi olayları sırayla işler.
6. **P6 — Tenant-filtreli** hedefli replay (tek tenant/çağrı); kör tüm-topic replay yalnız bakım penceresinde.
7. **P7 — Webhook yeniden teslimat ayrıdır** (API §10.1 manuel resend, T-05/A-09) — iç Kafka replay'i değil.
8. **P8 — Poison → DLQ** (`platform.dlq.v1`); manuel triyaj + düzeltme sonrası kontrollü replay.

**Replay tetikleyiciler (örnek):** yeni analitik/QA modeli geriye-dönük skorlama; redaction kuralı
güncellemesi → raw'dan yeniden maskeleme; tüketici hata düzeltmesi sonrası yeniden işleme; OLAP
şema migrasyonu (1.1.9) için yeniden besleme.

## 7. Cross-tenant izolasyon (FR-TEN-002, NFR 10.7)

Kafka topic'leri tenant'lar arası **paylaşılır** (Analytics Plane RMC-operated). İzolasyon üç katmanla:

1. **Residency** — her home-region için **ayrı cluster** (NFR 10.7); ham PII bölge-pinned;
   cross-region replikasyon (MirrorMaker2) **yalnız** agregat/redacted whitelisted topic seti için.
2. **ACL** — yalnız yetkili **platform servis principal**'ları (`config/acl.template.json`,
   least-privilege); ham PII'ye erişen **tek** consumer `pii-redaction`. Tenant principal'ı **yok**.
3. **Envelope `tenant_id` + downstream RLS** — at-rest izolasyon DB/OLAP/nesne-depolama katmanında
   RLS ile (DB.md §6; 1.1.x dilimleri) zorlanır; partition anahtarı tenant-türetilebilir.

## 8. Doğrulama (kapılar)

**Statik (sunucu gerekmez):**
```
python3 eventstream_probe.py validate   → 236/236 PASS  (I1..I15 + spec↔config + envelope + secret)
python3 eventstream_probe.py replay     → 9/9 PASS       (P1..P8 deterministik replay simülasyonu)
python3 eventstream_probe.py route      → same-key→same-partition + dağılım
python3 eventstream_probe.py selftest   → 18/18 PASS     (iyi/kötü spec ile kapı tetiklenmesi)
python3 tests/envelope_behavior_test.py → 6/6 PASS       (T1..T4 envelope + webhook indirgemesi)
```

**Canlı (opsiyonel, gerçek cluster):**
```
bash run_live_test.sh   → statik kapı + (rpk/kafka-topics + ${KAFKA_BOOTSTRAP_SERVERS} varsa)
                          declarative manifest uygula + topic/retention/cleanup doğrula; yoksa SKIP
```

## 9. İzlenebilirlik

| Gereksinim | Karşılanma |
|------------|-----------|
| ADR-007 (async pipeline + replay) | 13 topic + global_replay_policy P1–P8 + replay simülatörü |
| FR-RES-011 (non-RT batch/async) | data plane → event stream → async tüketiciler (hot path arınmış) |
| FR-REC-004 (PII redaction) | raw→redacted iki-aşama, raw kısa+kısıtlı, webhook'a ham PII yok (I5/I6) |
| FR-BIL-001/002, FR-ANA-007 (metering) | `billing.usage.v1` no-loss + idempotent agregasyon |
| FR-TOOL-009/011 (idempotent tool) | `ops.tool.execution.v1` + envelope idempotency_key |
| FR-IAM-008/009 (break-glass) | PII/audit topic replay gate (P4) + `governance.audit.v1` 365g WORM-mirror |
| BRD §15 (gözlemlenebilirlik) | turn.telemetry → observability-bridge (0.4.7); correlation_id propagation |
| API §10.2 (webhook kataloğu) | 10 webhook tipinin tamamı bir topic'te üretilir + webhook-dispatcher (I11) |
| NFR 10.7 (residency) | per-region cluster + ham PII pinned |
| ADR-004 (plane ayrımı) | event stream Analytics Plane; tenant doğrudan tüketmez |

## 10. Sınırlar / sonraki adımlar

- **Bağlayıcı sağlayıcı seçimi** (Kafka vs eşdeğer) provizyonel (0.2.6/0.3.x); tasarım vendor-neutral.
- **Partition sayıları** illüstratif kapasite tahminidir; canlı yük (0.4.8 / F1 §18.5) ile kalibre edilir.
- **OLAP sink** (`analytics-ingest`/`olap-sink`) hedef şeması WBS **1.1.9**'da.
- **Redaction motoru** implementasyonu (FR-REC-004) ileri WBS'te; bu tasarım topic kontratını verir.
- **Tiered/cold replay** (retention ötesi) nesne-depolama (1.1.6) + OLAP (1.1.9) ile bağlanır.
- **Schema-registry** seçimi (Confluent/Apicurio/Redpanda SR) deployment kararı; uyumluluk politikası sabit.

---
**Sır/credential repoya yazılmadı** — bootstrap/SASL/TLS yalnız `${ENV}`. Vendor-neutral (ADR-002).
