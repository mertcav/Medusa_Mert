# WBS 6.2.1 — Vector search (top-k) + opsiyonel rerank (tasarım)

> Kaynak doğruluk: `retrieval-spec.json`. Çelişkide **BRD/SAD esastır** (özellikle **SAD §10.2**). Bu belge
> tasarım gerekçesini özetler. Faz **F1** · Öncelik **Must** · İz **SAD §10.2** (+ FR-KB-004/005/006/007/011).

## 1. Amaç ve konum

Bilgi Tabanı & RAG **online retrieval hattının** (SAD §10.2, **hot-path**) birinci aşaması. SAD §10.2:

```
Soru ──► embed ──► vector search (top-k) ──► reranking (opsiyonel) ──► trim (token budget)
                                                                          │
                                                                          ▼
                                                        LLM context (kaynak atıflı)
```

Bu motor **vector search (top-k) + opsiyonel rerank** kısmını uygular. Turn döngüsünün **THINK** aşamasında
(SAD §6.1: Policy pre-check → LLM Router → gerekirse **RAG**/Tool) çağrılır; çoğu turda **atlanır** (SAD §20:
"Top-k; çoğu turda atlanır"). Gerektiğinde ~100–200ms bütçe kalemi (hot-path retrieval P95 ≤200ms).

**Zincir (consume — yeniden üretmez):**
- **6.1.3 IndexPipeline** → AKTİF `IndexedChunk` (content + namespace + version + citation + access metadata).
  Referans probe `index_pipeline_probe`'u import eder (o da `ingest_connector_probe`'u) → **kod tekrarı yok**.
- **6.1.4 AccessGate** → ACL pre-filtre yüklemi (`PrefilterPredicate`). `access_control_probe` import edilir;
  retrieval bu yüklemi aday kümesine uygular = **FR-KB-005 enforcement at retrieval** ("yetkisiz dokümandan
  retrieval sonucu dönmez").

## 2. İki aşamalı retrieval

**STAGE 1 — vector search.** Aday küme = query namespaces (`tenant+kb_ids`) ∩ **AKTİF** chunk (6.1.3 C8) ∩
(enforce_acl ise) **6.1.4 ACL-admit**. Soru, chunk content ile **aynı** `EmbeddingAdapter` SPI ile embed edilir;
her aday `cosine(query, chunk)` ile skorlanır; **`min_score`** eşiği altı elenir (alaka filtresi → grounding);
kalanlar cosine desc + deterministik tie-break (`chunk_id`) ile sıralanır, top-`rerank_candidates` (n ≥ top_k).

**STAGE 2 — opsiyonel rerank.** `rerank.enabled` ise `RerankAdapter` aday alt-kümesini yeniden sıralar
(**yalnız sıralar** — küme değişmez, yeni doc eklenmez); sonra `top_k` alınır. Devre dışıysa cosine sıralaması
doğrudan `top_k` (SAD §10.2 "reranking (**opsiyonel**)").

`min_score`'u geçen aday **yoksa** → BOŞ + `grounded=false` + `NO_RELEVANT_SOURCE` (§5).

## 3. Vendor-neutral SPI'ler (ADR-001/002)

| SPI | İmza | Referans (deterministik) | Canlı |
|-----|------|--------------------------|-------|
| `EmbeddingAdapter` | `embed_batch(texts, ctx) → list[vector(dim)]` | signed **feature-hash bag-of-words** + L2-norm (cosine ~ lexical overlap → recall **test edilebilir**) | gerçek **semantik** model (OpenAI/Cohere/bge/yerel) |
| `RerankAdapter` (opsiyonel) | `rerank(query, candidates) → reordered` | **query-term coverage** + vec_score tie-break | gerçek **cross-encoder** |

Soru + chunk content **aynı uzay** (query-doc tutarlılığı). Referans embedder gerçek **değer** üretmez —
**sözleşme + akış + geometri** kanıtıdır; orchestrator yalnız `chunk+vektör+citation` sözleşmesine bağımlıdır
(ADR-001). Referans probe stored vektör yerine aday content'i aynı embedder ile **yeniden embed** eder (durable
vektör store → 1.1.7; canlıda **pgvector/OpenSearch ANN** top-k metadata-filtreli). **Ranking sözleşmesi aynı.**

**Rerank neden işe yarar (kanıt):** bi-encoder cosine yüzey term-frekansına aşırı ağırlık verebilir. `happy`
senaryosunda `iade-tekrar` tek terimi çok tekrarlar → cosine yüksek; `iade-sure` sorgunun **tüm** terimlerini
kapsar → coverage reranker onu #1'e taşır (cross-encoder stand-in bi-encoder'ın kaçırdığını düzeltir).

## 4. Kapılar (R1–R10, HARD)

| Kapı | İçerik | İz |
|------|--------|----|
| **R1** | ranking score-desc + deterministik tie-break; labeled `recall@k ≥ min_recall_at_k` | SAD §10.2, →6.2.5 |
| **R2** | `|results| ≤ top_k` + `min_score` eşiği | FR-KB-011, FR-RES-010 |
| **R3** | namespace izolasyonu — cross-namespace dönen = 0 | FR-KB-004, FR-TEN-002 |
| **R4** | ACL enforcement at retrieval — yetkisiz/deny dönen = 0 (6.1.4 pre-filtre) | FR-KB-005 |
| **R5** | active-only — supersede (eski sürüm) dönen = 0 | 6.1.3 C8 |
| **R6** | opsiyonel rerank **order-only** — result ⊆ vector-candidate; namespace/ACL leak yok; `rerank_top` #1 | SAD §10.2 |
| **R7** | citation — her sonuç doc_id+version+chunk_no+source_uri+content_hash+score+rank+token_estimate | FR-KB-006, →6.2.2/6.2.3 |
| **R8** | no-log/residency — home-region + no-train(hassas); audit ham soru/content/PII yazmaz | FR-KB-010, FR-LLM-012, NFR 10.7 |
| **R9** | grounding — aday yoksa `grounded=false` + `NO_RELEVANT_SOURCE` (uydurma yok) | FR-KB-007, →3.3.4 |
| **R10** | robust — structured `RetrievalError`, exception kaçmaz + kapsam sınırı | — |

## 5. Grounding (anti-hallucination kancası)

`min_score` eşiğini geçen aday yoksa (boş namespace / hepsi elendi / **ACL hepsini eler**) retrieval **boş**
sonuç + `grounded=false` + `reason=NO_RELEVANT_SOURCE` döndürür — **kaynak üretmez**. Orchestrator bu sinyali
"kontrol ediyorum / aktarıyorum / ticket açıyorum" davranışına çevirir (Policy Engine, **3.3.4** / FR-KB-007).
`acl-filter` senaryosunda yetkisiz ajan, korunan tek alakalı dokümanı göremez → **grounded=false** (sızıntı
yerine güvenli reddetme).

## 6. Hata taksonomisi

`MISSING_QUERY_CONTEXT` · `EMPTY_QUERY` · `INVALID_TOP_K` · `EMBED_PROVIDER_ERROR` · `EMBED_DIM_MISMATCH` ·
`NO_TRAIN_REQUIRED_VIOLATION` (hassas soru train-açık endpoint'e, fail-closed) · `REGION_VIOLATION` ·
`RERANK_PROVIDER_ERROR` (canlıda fallback = rerank'siz cosine, BRD §19) · `INTERNAL_ERROR` (catch-all, çökme yok).
Boş-alaka (`NO_RELEVANT_SOURCE`) bir **hata değil** → `grounded=false` sonuç.

## 7. Kapsam sınırı

**Yapar:** soru embed + vector search top-k + opsiyonel rerank + namespace/ACL/active filtre + citation +
grounding sinyali. **Yapmaz (consume/devret):** embedding/chunk/version üretimi → **6.1.3**; ACL metadata +
authoritative karar → **6.1.4**; token-trim (bağlam bütçesi) → **6.2.2**; kaynak-atfı sentezi → **6.2.3**;
no-log enforcement detay → **6.2.4**; KB Q&A benchmark/recall@k canlı → **6.2.5 / 0.2.5 vector-db-eval**;
fiziksel ANN store → **1.1.7**. Sır/credential üretmez (sentetik fixture, FR-TST-008).

## 8. Çıktılar

`retrieval-spec.json` · `retrieval_probe.py` (`validate`/`retrieve`/`selftest`/`schema`) ·
`config/retrieval-profiles.json` · `samples/*.json` (4 geçer + 1 negatif) ·
`tests/retrieval_behavior_test.py` (T1–T10) · `run_live_test.sh` · `README.md`.
