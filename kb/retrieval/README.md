# kb/retrieval — WBS 6.2.1 (Vector search top-k + opsiyonel rerank)

Bilgi Tabanı & RAG **online retrieval hattının** (SAD §10.2, hot-path) birinci aşaması:
`Soru ──► embed ──► vector search (top-k) ──► reranking (opsiyonel) ──► trim → LLM context (kaynak atıflı)`.
6.1.3 AKTİF `IndexedChunk`'ları **chunk/embed/version'u yeniden yapmadan** TÜKETİR (`index_pipeline_probe`'u
import eder, o da `ingest_connector_probe`'u); 6.1.4 ACL pre-filtre yüklemini TÜKETİR (`access_control_probe`).
Soruyu **aynı vendor-neutral EmbeddingAdapter SPI** ile embed eder, cosine top-k seçer, **opsiyonel**
RerankAdapter SPI ile yeniden sıralar, **citation'lı** `RankedResult` döndürür. Çekirdek: **SAD §10.2**
(+ FR-KB-004 namespace · FR-KB-005 ACL · FR-KB-006 citation · FR-KB-007 grounding · FR-KB-011 top-k).

## Dosyalar
- `retrieval-spec.json` — kaynak doğruluk (SPI, two-stage retrieval, embedding/rerank, grounding, gates R1–R10, taksonomi).
- `retrieval.md` — tasarım.
- `retrieval_probe.py` — stdlib-only probe (`validate` / `retrieve <sample>` / `selftest` / `schema`).
- `config/retrieval-profiles.json` — profiller (pilot-default/regulated-tr/enterprise-eu/no-rerank + degraded negatif). Sır YOK (`${ENV}`).
- `samples/*.json` — `happy-topk-rerank` · `tenant-isolation` · `acl-filter` · `versioning-grounding` (geçer) + `degraded` (expect_gate=fail).
- `tests/retrieval_behavior_test.py` — T1–T10 davranış kapısı.
- `run_live_test.sh` — statik + sample her zaman; canlı ANN store `${KB_VECTOR_DSN}` varsa not, yoksa SKIP.

## Çalıştırma
```bash
python3 retrieval_probe.py validate                       # statik spec/config/şema kapısı
python3 retrieval_probe.py selftest                       # gömülü davranış kontrolleri
python3 retrieval_probe.py retrieve samples/retrieve-happy-topk-rerank.json
python3 retrieval_probe.py schema                         # SPI/RankedResult sözleşmesi
python3 tests/retrieval_behavior_test.py                  # T1–T10
./run_live_test.sh                                        # tümü + canlı SKIP raporu
```

## Kapılar (R1–R10)
R1 ranking+recall@k · R2 top-k+min_score · R3 namespace-izolasyon · R4 ACL-enforcement-at-retrieval ·
R5 active-only · R6 opsiyonel-rerank-order-only · R7 citation · R8 no-log/residency ·
R9 grounding (anti-hallucination kancası) · R10 robust+kapsam-sınırı.

## Tasarım notları (vendor-neutral & güvenlik)
- **İki aşama:** (1) vector search — aday = query namespace ∩ aktif ∩ 6.1.4 ACL-admit; cosine + min_score
  eşiği + top-n. (2) **opsiyonel** rerank — RerankAdapter aday alt-kümesini yeniden sıralar (**yalnız sırlar**,
  küme değişmez), top-k. Reranker DEVRE DIŞI yol da geçerli (SAD §10.2 "reranking (opsiyonel)").
- **Vendor-neutral (ADR-001/002):** embedding + rerank birer SPI arkasında. Referans deterministik
  **feature-hash bag-of-words** embedder (cosine ~ lexical overlap → recall **test edilebilir**) + **coverage**
  reranker (cross-encoder stand-in) yerine canlıda gerçek **semantik model + cross-encoder** AYNI imza arkasına.
  Referans probe stored vektör yerine aday content'i aynı embedder ile yeniden embed eder (durable store 1.1.7;
  canlıda pgvector/OpenSearch ANN top-k metadata-filtreli). Ranking sözleşmesi AYNI.
- **Grounding (FR-KB-007 → 3.3.4):** min_score eşiğini geçen aday yoksa BOŞ + `grounded=false` +
  `NO_RELEVANT_SOURCE` — **uydurma yok**. (ACL tüm alakalı dokümanı elerse de grounded=false.)
- **No-log/residency:** soru embedding'i home-region + no-train(hassas)/no-log; audit **yapısal** —
  ham soru/content/PII yazılmaz (`query_digest`/`principal_digest` sha256). Detay no-log enforcement → 6.2.4.
- **Hot-path:** SAD §20 RAG retrieval ~100–200ms (P95 ≤200ms); formal recall/latency ölçümü **0.2.5
  vector-db-eval** + canlı PoC (referans probe deterministik — gecikme SOFT). Determinizm: tohumlu
  embedder/reranker. Sır/credential/PII repoya yazılmaz (sentetik fixture, FR-TST-008).
- **Kapsam dışı:** token-trim → 6.2.2, kaynak-atfı sentezi → 6.2.3, no-log detay → 6.2.4, benchmark → 6.2.5,
  embedding/chunk üretimi → 6.1.3, ACL metadata/authoritative karar → 6.1.4, fiziksel ANN store → 1.1.7.
