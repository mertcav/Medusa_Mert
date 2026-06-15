# WBS 6.1.5 — Bayatlama/işaretleme (content TTL) tasarımı (FR-KB-008)

> Kaynak doğruluk `content-ttl-spec.json`; çelişkide BRD/SAD esastır. Bu doküman tasarımı özetler.
> İz: **FR-KB-008** · SR-KB-008 · TC-KB-008 (T) · SAD §10.1 · DB.md §5.3 (`kb_document.content_ttl_at`).

## 1. Amaç ve konum
**FR-KB-008:** *"Güncelliğini yitirmiş içerik otomatik işaretlenebilmelidir."* Bu modül, indekslenmiş bilgi
tabanı dokümanlarının **tazeliğini** periyodik bir tarama ile değerlendirir ve güncelliğini yitirenleri
otomatik **`stale`/`expired`** işaretler.

- **Plane:** Control/Analytics (offline). **Hot-path DEĞİL** — voice runtime gecikme bütçesine (SAD §20)
  girmez. Tetik: scheduled/cron tarama · post-reindex (6.1.3 sonrası) · post-source-sync (6.1.2 delta sonrası).
- **Karar maliyeti:** metadata-only (zaman damgası karşılaştırması; içerik/embedding/ağ **yok**).
- **Vendor-neutral (ADR-001/002):** TTL policy + doküman metadata'sına dayanır; pgvector/OpenSearch fark etmez.

```
kb_document (6.1.3 indexed_at/version · 6.1.2 last_modified/eTag · DB.md content_ttl_at)
   │  periyodik/post-reindex tarama (now = sanal saat)
   ▼
[STALENESS MARKER: explicit-TTL · policy max_age · source-drift · hard-expiry · pinned]
   ▼
fresh | stale | expired | pinned   ──►  işaret (content_ttl_at + durum) ──► 6.2.1 retrieval bastırma/öncelik
                                                                        └─► 6.1.2/6.1.3 yeniden-ingest tetik
```

## 2. Tazelik metadata'sı (consumes)
| Alan | Kaynak | Rol |
|------|--------|-----|
| `indexed_at` | 6.1.3 IndexPipeline (son (re)index atası) | birincil tazelik referansı |
| `version_no` | 6.1.3 | provenance (aktif sürüm) |
| `classification` | 6.1.3 / 6.1.1 | policy `max_age`'i seçer |
| `source_last_modified` | 6.1.2 connector `last_modified`/eTag | drift sinyali |
| `content_ttl_at` | DB.md §5.3 `kb_document` (açık deadline) | policy'yi **ezer** (most-specific-wins) |
| `pinned` | operatör (no_expire) | otomatik bayatlamadan muaf |
| `prev_state` | mevcut işaret | geçiş tespiti |

Karar **yalnız** bu metadata + policy'den verilir (sağlayıcıdan bağımsız). `index_pipeline_probe` import
edilerek 6.1.3 aktif dokümanları gerçek pipeline'dan türetilir (kod tekrarı yok; o da 6.1.1'i tüketir).

## 3. TTL modeli ve karar algoritması
**Soft deadline** = `content_ttl_at` (varsa) **aksi** `indexed_at + max_age(classification)`.
**Hard deadline** = `soft + max_age*(expire_after_factor−1)` (yalnız gerçek genişletme varsa; `hard_expiry_enabled`).
**Source drift** = `respect_source_drift ∧ source_last_modified > indexed_at`.

Sıralı, **şiddet sırasına** göre (`pinned > expired > stale > missing > fresh`):
1. `pinned` → **pinned** / `PINNED_NO_EXPIRE` (G5).
2. `hard ≠ ∅ ∧ now ≥ hard` → **expired** / `HARD_EXPIRED` (G6).
3. `source_drift` → **stale** / `SOURCE_DRIFT` (G4).
4. `soft ≠ ∅ ∧ now ≥ soft+grace` → **stale** / `TTL_EXCEEDED` (policy) | `EXPLICIT_TTL_PASSED` (açık) (G1/G3).
5. `missing ∧ require_freshness` → **stale** / `MISSING_FRESHNESS` (G9 fail-closed).
6. `missing` → **fresh** / `NO_TTL_POLICY` (require kapalı — bilinçli).
7. aksi → **fresh** / `WITHIN_TTL` (G2).

`marked = state ∈ {stale, expired}` (otomatik `stale` işareti — SR-KB-008/TC-KB-008). Bozuk metadata hiçbir
exception kaçırmaz → muhafazakâr `stale` / `MALFORMED_METADATA` (G9/G10).

## 4. HARD kapılar (G1–G10)
| Kapı | Invariant |
|------|-----------|
| **G1** | **TTL EXCEEDED → STALE** (başlık): soft-deadline geçen / drift / missing+require → marked; bayat asla fresh kalmaz. `unmarked_overdue=0`. |
| **G2** | FRESH PRESERVED: deadline gelecekte + drift yok + missing değil → yanlışlıkla bayat işaretlenmez. `false_stale=0`. |
| **G3** | EXPLICIT PRECEDENCE: `content_ttl_at` policy'yi ezer (`soft==content_ttl_at`, `deadline_source=explicit`). |
| **G4** | SOURCE DRIFT: `source_last_modified > indexed_at` (pinned/expired değil) → `stale` `SOURCE_DRIFT`. |
| **G5** | PINNED NEVER EXPIRES: pinned → `state=pinned`, `marked=false` (yaştan/drift'ten bağımsız). |
| **G6** | HARD EXPIRY DISTINCT: hard geçen → `expired` (soft'tan ayrı; retrieval bastırır); monoton (expired ⇒ soft geçmiş). |
| **G7** | DETERMINISTIC: aynı set+now+policy → birebir aynı işaret (sanal saat). |
| **G8** | TENANT SCOPE: `tenant_filter` ile yalnız o tenant; kapsam dışı işaretlenmez (FR-TEN-002). |
| **G9** | FAIL-CLOSED UNKNOWN: missing+require → `stale` (asla sessiz fresh); MALFORMED → `stale`. |
| **G10** | AUDITABLE + SCOPE: kapsam içi her doküman bir kayıt; taksonomi geçerli; kayıt ham içerik/PII'sız. |

## 5. Kapsam sınırı (G10)
6.1.5 **yalnız işaretler.** İşaretin retrieval'e etkisi (bayat içeriği **bastırma/önceliklendirme**) → **6.2.1**;
yeniden-ingest tetikleme → **6.1.2/6.1.3**; fiziksel `content_ttl_at` kolonu + `ix_kbdoc_ttl` tarama indeksi →
**1.1.7** (migration 0010); chunk/embed/version → **6.1.3** (tüketir); hassas no-log → **6.2.4**.

## 6. Determinizm, sır ve PII
Sanal saat (epoch-sn tam sayı; `Date.now`/rastgele yok) → tarama tekrar koşturulabilir/denetlenebilir. TTL
kararı **metadata-only** (içeriğe hiç dokunmaz) → audit kaydı doğal PII'sız. Spec/config/sample'larda sır/
credential ve gerçek PII değeri yok (fixture sentetik — FR-TST-008). Metrikler 0.4.7 label politikasına uyar
(tenant/doc/kb yüksek kardinalite → yalnız trace/exemplar; PII label yasak).
