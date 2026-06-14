# WBS 6.1.2 — SharePoint/Confluence connector

`F2` · `Should` · →FR-KB-002 · SR-KB-002 · SAD §10.1 · ADR-001/002

Bilgi Tabanı & RAG **offline indeksleme** hattının (SAD §10.1) **ikinci** aşaması: **kurumsal kaynak
connector'ı**. 6.1.1 ingest connector tek doküman *alır* (upload/web); 6.1.2 kurumsal doküman
*sistemlerine* (**SharePoint, Confluence**, genel DMS) **bağlanır**, kapsamı senkronize eder ve her
dokümanı **6.1.1 FormatExtractor'a devreder** (ayıklamayı yeniden yazmaz). Çıktıyı **6.1.3**
(chunk→embed→index+versiyonlama) tüketir.

```
SharePoint site / Confluence space / generic DMS
   │ EnterpriseSourceConnector.connect()  → endpoint allowlist + SSRF guard + auth (${ENV})
   ▼
list_changes(cursor)  → enumerate (sayfalı) + change-token DELTA (upsert / deletion / new_cursor)
   ▼
map_acl(native)  → kaynak izinleri → classification + acl_ref + source_principals  (→6.1.4 ENFORCE)
   ▼
fetch_content(item) → ham bayt ──► (6.1.1 FormatExtractor.extract) ──► NormalizedDocument
   ▼
SyncResult { cursor_in/out, items[ NormalizedDocument + source_system/external_id/etag/last_modified/source_uri ], counts }
   │  (6.1.3 chunk→embed→index+versiyonlama · 6.1.4 ACL enforce · 6.1.5 TTL/bayatlama)
```

## Mimari konum
- **Offline** indeksleme hattı (Control/Analytics Plane, SAD §10.1) — **hot-path değil** (SAD §20 bütçesine
  tabi değil). L1/L2 `POST /knowledge-bases/{id}/sources` (kurumsal kaynak bağla) + zamanlanmış delta
  senkronizasyon ile tetiklenir.
- **Vendor-neutral (ADR-002):** SharePoint / Confluence / generic adapter'ları **tek
  `EnterpriseSourceConnector` SPI** arkasındadır; canlıda Microsoft Graph drive-delta / Confluence Cloud
  REST istemcisi aynı imza arkasına takılır. Orchestrator/RAG yalnız `NormalizedDocument` sözleşmesine
  bağımlıdır (ADR-001).
- **6.1.1 yeniden kullanılır (S5):** ayıklama/normalizasyon/dedup 6.1.1 `FormatExtractor` registry'sine
  **devredilir** — connector parse'ı yeniden yazmaz; yalnız bağlantı + enumerate + delta + ACL eşleme +
  kaynak metadata zenginleştirme katmanını ekler.
- **Credential-free:** kaynak endpoint + OAuth/token yalnız `${ENV}` (`KB_SOURCE_ENDPOINT` /
  `KB_SOURCE_OAUTH_TOKEN`); repoya **yazılmaz**. Snapshot içerikleri sentetik (FR-TST-008).

## İki SPI yüzeyi
| Yüzey | Sorumluluk |
|-------|-----------|
| **`EnterpriseSourceConnector`** | `connect(ctx)` [endpoint-allowlist + SSRF + auth] · `list_changes(cursor)→(upserts, deletions, new_cursor)` · `fetch_content(item)→bytes\|fault` · `map_acl(native)→{classification, principals, acl_ref}`. Impl: `SharePointConnector` / `ConfluenceConnector` / `GenericConnector` |
| **`FormatExtractor`** (6.1.1) | `extract(bytes, ctx)→NormalizedDocument\|IngestError` — **yeniden kullanılır**, connector kendi yazmaz |

## Connector eşlemeleri
| Connector | Kapsam | Değişiklik belirteci (delta) | Native ACL → classification |
|-----------|--------|------------------------------|------------------------------|
| **sharepoint** | site/drive | `eTag`/`lastModifiedDateTime` (delta token) | `sharingScope`: anonymous→public, organization→internal, specific→confidential (owner/fullControl→restricted) + `roleAssignments` principal'ları |
| **confluence** | space | `version.number` (lastModified delta) | content read restriction: kısıtsız→internal (space default), users/groups→confidential; `space_anonymous`→public |
| **generic** | collection | `version` int | `visibility` (public/internal/confidential/restricted) + `principals` |

## HARD kapılar (S1–S10)
| ID | Kapı |
|----|------|
| **S1** | CONNECTOR COVERAGE — ≥2 connector tek SPI arkasında; her biri kapsamı enumerate + ≥1 doküman senkronize (SR-KB-002) |
| **S2** | ENUMERATION + PAGINATION — sayfalı liste, `page_size ≤ max_page_size`, öğe sayısı `≤ max_items_per_sync` (DoS guard) |
| **S3** | INCREMENTAL DELTA — change-token/cursor artımsal; aynı cursor + mutasyonsuz → 0 değişiklik (idempotent); silme tombstone; cursor monoton |
| **S4** | SOURCE ACL MAPPING — kaynak izinleri → classification + acl_ref + source_principals (→6.1.4); kısıtlı kaynak asla `public` değil; connector **eşler, enforce etmez** |
| **S5** | EXTRACTION DELEGATION — 6.1.1 FormatExtractor'a devir → kanonik NormalizedDocument; çıktı kaynak-sistem metadata ile zenginleştirilir |
| **S6** | TENANT/KB ISOLATION — her doc tenant+kb namespace; tenant context yoksa fail-closed; cross-tenant sızıntı=0; izole dedup uzayı |
| **S7** | RESIDENCY + ENDPOINT ALLOWLIST + SSRF + NO-LOG — endpoint host allowlist'te; özel/iç/loopback IP SSRF reddi; home-region + no_log + redaction pending; credential sızıntısı=0 |
| **S8** | ROBUST + TAXONOMY + THROTTLE — yapısal hata taksonomisi + retryable bayrağı (geçici↔kalıcı); throttle backoff; bir kötü öğe senkronu durdurmaz; never-crash |
| **S9** | SYNC STATE / CURSOR — cursor_in/out monoton + kalıcı (devam edilebilir); counts mutabakatı `total = synced + deleted + failed` |
| **S10** | SCOPE BOUNDARY — embedding/vektör/chunk/erişim-kararı/credential alanı YOK; chunk/embed→6.1.3, ACL enforce→6.1.4, TTL→6.1.5 |

## Hata taksonomisi
- **Bağlantı (kalıcı):** `AUTH_FAILED` · `FORBIDDEN` · `NOT_FOUND` · `ENDPOINT_NOT_ALLOWED` · `SSRF_BLOCKED`
  · `REGION_VIOLATION` · `MISSING_TENANT_CONTEXT` · `INVALID_CURSOR` · `UNSUPPORTED_CONNECTOR`.
- **Bağlantı (geçici / `retryable=true`):** `THROTTLED` · `TIMEOUT` · `UNAVAILABLE` (backoff + yeniden dene).
- **Devralınan ayıklama (6.1.1):** `UNSUPPORTED_FORMAT`/`FORMAT_MISMATCH`/`TOO_LARGE`/`CORRUPT`/`ENCRYPTED`/
  `NEEDS_OCR`/... — bir öğenin ayıklama hatası senkronu durdurmaz (S8).

## Kapsam ayrımı (S10 — bilinçli sınır)
chunk/embed/index/versiyonlama → **6.1.3** · doküman-bazı erişim **ENFORCEMENT** → **6.1.4** (connector
yalnız metadata **eşler**) · içerik TTL/bayatlama → **6.1.5** (last_modified/etag tüketir) · vector store
namespace fiziksel → **1.1.7** · retrieval/rerank/trim → **6.2.x**. Bu motor embedding/vektör **üretmez**,
erişim **kararı** (granted/denied) **üretmez**, credential **üretmez**.

## İzlenebilirlik
FR-KB-002 ↔ SR-KB-002 ↔ TC-KB-002 ↔ WBS 6.1.2 (RTM zaten eşli — değişmedi). Ek: FR-KB-004 (tenant/kb
namespace), FR-KB-005 (ACL metadata kancası → 6.1.4), FR-KB-010 + NFR 10.7 (residency/no-log), FR-TST-008
(sentetik). Metrikler `kb_source_sync_total{connector,status}` / `kb_source_items{change_type}` /
`kb_source_failed_total{error_class}` / `kb_source_throttle_total` / `kb_source_cursor_lag` → BRD §15 →
0.4.7 (tenant_id/external_id/source_uri/endpoint **yüksek kardinalite** → yalnız trace/exemplar).
