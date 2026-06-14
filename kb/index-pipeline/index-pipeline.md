# WBS 6.1.3 — Parse→chunk→embed→index + versiyonlama

> **Faz** F1 · **Öncelik** Must · **İz** FR-KB-003 (→FR-KB-004/005/006/010, FR-LLM-012, NFR 10.7)
> **Kaynak doğruluk** `index-pipeline-spec.json`. Çelişkide `docs/BRD.md` / `docs/SAD.md` esastır.

## 1. Amaç ve konum

Bilgi Tabanı & RAG **offline indeksleme hattının** (SAD §10.1) üçüncü ve son offline aşaması. Hat:

```
Doküman ──[6.1.1 ingest / 6.1.2 kurumsal kaynak]──► NormalizedDocument
                                                          │  (bu aşama: 6.1.3)
        ┌─────────────────────────────────────────────────┘
        ▼
   [chunk] ──► [embed (EmbeddingAdapter SPI)] ──► [index (tenant+kb namespace)] ──► [version]
        │            │                                  │                              │
   yapı-duyarlı   vendor-neutral                  1.1.7 kb_chunk                yeniden ingest
   C1 kapsam      ADR-001/002 · no-train/no-log   FR-KB-004 izolasyon          → sürüm (FR-KB-003)
```

**Parse, bu aşamada YENİDEN YAPILMAZ.** 6.1.1 ingest connector parse+normalize işini bitirmiş, kanonik
`NormalizedDocument`'ı üretmiştir; 6.1.3 bu sözleşmeyi **tüketir** (referans probe, NormalizedDocument'ı
6.1.1 fixture'larından türetmek için `ingest_connector_probe`'u **import eder** — kod tekrarı yok, tıpkı
6.1.2'nin ayıklamayı devralması gibi). FR-KB-003'ün çekirdek değeri: *"Bilgi kaynakları otomatik
parçalanmalı, indekslenmeli ve versiyonlanmalıdır."* (SR-KB-003: *"Chunk/index üretilir; yeniden ingest
sürüm üretir."*)

**Offline (Control/Analytics Plane)** — hot-path değil; SAD §20 gecikme bütçesine tabi değil. Yine de
bounded (chunk/embed batch sınırları). L1/L2 panel `POST /knowledge-bases/{id}/documents` (async) veya
kurumsal kaynak senkronu (6.1.2) NormalizedDocument üretince tetiklenir.

## 2. SPI yüzeyleri (vendor-neutral, ADR-001/002)

| SPI | Yöntem | Sözleşme |
|-----|--------|----------|
| **EmbeddingAdapter** | `embed_batch(texts, ctx) -> list[vector(dim)]` | Sabit `embedding_dim` vektör; `ctx` residency/no_train/no_log/sensitive taşır; **fail-closed** hassas+train-açık → `NO_TRAIN_REQUIRED_VIOLATION`. Referans deterministik embedder yerine canlıda **gerçek model** (OpenAI/Cohere/bge/yerel) aynı imza arkası. |
| **VectorIndexWriter** | `upsert(namespace, records)` / `supersede(namespace, doc, prev_version)` | tenant+kb namespace'e yazar (1.1.7 `kb_chunk`); cross-namespace yazım yapısal olarak imkânsız (fail-closed). |

Orchestrator/RAG client yalnız **IndexedChunk** sözleşmesine (chunk + vektör + citation) bağımlıdır
(ADR-001). `embedding_model` bir **etikettir**, sağlayıcı adı değil — BRD vendor seçmez.

## 3. Chunking (C1 — yapı-duyarlı, deterministik)

- `NormalizedDocument.blocks` (heading/paragraph/table_row/…) **birim** alınır; ardışık bloklar
  `target_chars`'a kadar paketlenir. **Blok sınırı korunur** — bir blok bölünmez; tek başına `target`'ı
  aşarsa `overlap`'lı pencerelere bölünür.
- Ardışık chunk'lar arası `overlap_chars` örtüşme (bağlam sürekliliği → retrieval recall, 6.2.x).
- **Kapsam invariant'ı:** `join(chunk.core_text) == join(blok metinleri)` — metin **düşmez/çoğalmaz**
  (overlap ayrı `content` prefix'inde tutulur, kapsam çift saymaz).
- Her chunk **citation metadata** taşır: `document_id + doc_logical_key + version_no + chunk_no +
  source_uri + block_span + content_hash` → **FR-KB-006** "yanıtın hangi kaynağa dayandığı izlenebilir".
  `char_count`/`token_estimate` (≈char/4) bütçe girdisi (FR-RES-010 / 6.2.2).
- `max_chunks` aşımı → `CHUNK_LIMIT_EXCEEDED` (DoS/maliyet guard).

## 4. Embedding (C3/C4)

- **BATCH** embedding (gecikme/maliyet). Referans embedder deterministiktir
  (`sha256(model+text)`-tohumlu LCG → `dim` float, **L2-normalize**) — gerçek değer değil, sözleşme/akış
  kanıtı. `embedding_dim` model-bağımlı referans **1536** (DB.md §12 / 0.2.5 vendor eval).
- **Residency + no-log/no-train (C4):** embedding çağrısı home-region (NFR 10.7) + `no_log` (FR-KB-010);
  **hassas doküman yalnız no-train endpoint'e** (FR-LLM-012) — aksi `NO_TRAIN_REQUIRED_VIOLATION`
  **fail-closed**. Bölge uyumsuz → `REGION_VIOLATION`. Ham vektör çıktıya **gömülmez** (fingerprint:
  ilk-4-boyut + L2-norm + dim).

## 5. Versiyonlama (C6/C7/C8 — FR-KB-003 çekirdeği)

Mantıksal doküman kimliği = `(tenant_id, kb_id, doc_logical_key)`; `doc_logical_key` kaynaktan gelir
(`source_uri`/external_id). `content_hash` (6.1.1'den) değişimi belirler:

| Durum | Davranış | Kapı |
|-------|----------|------|
| İlk indeks | `version_no = 1`, chunk+embed+index | — |
| İçerik **değişti** (hash farklı) | `version_no + 1`, **yeni chunk seti** + embed + index; eski sürüm **supersede** (`active=false`), atomik aktivasyon | **C6** |
| İçerik **değişmedi** (hash aynı) | **idempotent no-op** — yeni sürüm yok, mevcut chunk/embedding **yeniden kullanılır** (maliyet tasarrufu); `duplicate_of` (6.1.1 dedup) bu yolu besler | **C7** |

- **Tek aktif sürüm** her mantıksal doküman için; yalnız aktif sürüm retrieval'e (6.2.x) görünür.
- **Geçmiş korunur** (rollback/audit) — eski sürüm chunk'ları silinmez, `active=false` (**C8**).
- DB karşılığı: `kb_document.version_no` (FR-KB-003) + `kb_chunk` aktif/supersede (1.1.7 / migration 0010).

## 6. HARD kapılar (C1–C10)

| # | Kapı | Özet |
|---|------|------|
| C1 | Chunk coverage | core birleşim == kaynak (kapsam-kaybı=0); blok sınırı; bounded; `max_chunks` |
| C2 | Citation metadata | her chunk doc_id+version+chunk_no+source_uri+block_span+hash (FR-KB-006) |
| C3 | Embed vendor-neutral SPI | sabit dim vektör + model + batch (ADR-001/002); dim/provider hatası yapısal |
| C4 | No-train/no-log/residency | hassas→no-train (FR-LLM-012); home-region (NFR 10.7); no_log (FR-KB-010) |
| C5 | Namespace isolation | chunk yalnız kendi tenant+kb namespace'i; cross=0 (FR-KB-004); tenant'sız fail-closed |
| C6 | New version on change | içerik değişti → version_no+1 + yeni chunk seti (SR-KB-003) |
| C7 | Idempotent no-op | içerik değişmedi → yeni sürüm yok, yeniden kullan |
| C8 | Atomic activation + history | tek aktif sürüm; supersede; geçmiş korunur (rollback) |
| C9 | Access metadata propagation | classification/acl_ref/redaction_state/sensitive → chunk (→6.1.4) |
| C10 | Robust + scope boundary | yapısal hata taksonomisi, çökme yok, batch dayanıklı; kapsam sınırı |

## 7. Hata taksonomisi (API §11.6 ruhu)

`EMPTY_DOCUMENT` · `CHUNK_LIMIT_EXCEEDED` · `EMBED_PROVIDER_ERROR` · `EMBED_DIM_MISMATCH` ·
`NO_TRAIN_REQUIRED_VIOLATION` · `REGION_VIOLATION` · `MISSING_TENANT_CONTEXT` · `INDEX_WRITE_ERROR` ·
`INVALID_INPUT_DOC`. Deterministik + müşteriye sızmaz; bir kötü doc batch'i durdurmaz (C10).

## 8. Kapsam sınırı (bilinçli, C10)

| Konu | Nereye |
|------|--------|
| Parse / format ayıklama | **6.1.1** (TÜKETİR, yeniden yapmaz) |
| Kurumsal kaynak (SharePoint/Confluence) | **6.1.2** |
| Doküman-bazı erişim **ENFORCEMENT** | **6.1.4** (pipeline yalnız metadata **taşır**) |
| İçerik TTL / bayatlama | **6.1.5** (version/last_indexed tüketir) |
| Fiziksel `kb_chunk` store | **1.1.7** (migration 0010/0011) |
| Retrieval / rerank / top-k | **6.2.1** |
| Token-trim (bağlam bütçesi) | **6.2.2** |
| Benchmark (Q&A kalitesi) | **6.2.5** |

## 9. Determinizm & güvenlik

- Sanal saat (`Date.now`/rastgele **yok**) + tohumlu deterministik embedder → tekrarlanabilir kapı.
- Sır/credential ve gerçek PII değeri **üretilmez/yazılmaz** (fixture içerikleri sentetik — FR-TST-008);
  embedding endpoint/anahtar yalnız `${ENV}`. Doküman içeriği runtime'da PII içerebilir (meşru) →
  `no_log=true` + `redaction_state` (NormalizedDocument'tan) taşınır; redaction uygulaması 6.1.4.

## 10. İzlenebilirlik

FR-KB-003 ↔ SR-KB-003 ↔ TC-KB-003 (RTM) zaten eşli — SRS/RTM değişmedi. Gözlemlenebilirlik (0.4.7):
`kb_index_total{stage,status}` / `kb_chunks_emitted` / `kb_embed_batch_total` /
`kb_index_versions_total{action}` / `kb_index_reuse_total` / `kb_index_rejected_total{error_class}`
(tenant_id/doc_id/kb_id yüksek kardinalite → yalnız trace/exemplar, BRD §15).
