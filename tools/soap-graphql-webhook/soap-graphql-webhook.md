# SOAP/GraphQL/webhook connector'lar — tasarım (WBS 7.2.2)

> **Kaynak doğruluk:** `docs/BRD.md` (FR-TOOL-001), `docs/SAD.md` (§11.1/§11.2/§20). Çelişkide dokümanlar esastır.
> Bu modülün **kaynak doğruluğu** `soap-graphql-webhook-spec.json`'dur; bu `.md` onu açıklar.

## 1. Amaç ve yerleşim

`FR-TOOL-001` ("REST, SOAP, GraphQL ve webhook entegrasyonları desteklenmelidir") SAD §11.2'de **Integration
Gateway** olarak yer alır. 7.2.1 (rest-connector) gereksinimin **REST** dilimini uyguladı; bu modül kalan
**SOAP / GraphQL / webhook** dilimlerini uygular. Üçü de 7.1.4'ün ilan ettiği AYNI transport SPI seam'inin
gerçeklemesidir:

```
LLM tool call ─► [1] input schema ─► [2] authz ─► [3] policy gate ─► [4] idempotency
              ─► [5] Integration GW { timeout + retry + breaker SARAR → upstream_call(req) }
                       │
                       └─► (soap|graphql|webhook) connector.upstream_call(req) ─► AttemptOutcome   ◄── BU MODÜL
              ─► [6] output schema + error normalization ─► [7] correlation_id audit
```

Çağrı zinciri: **7.1.4 gateway → (her deneme) → connector → AttemptOutcome → 7.1.4 kararı (retry/breaker)**.
Connector tek bir denemenin sonucunu üretir; **retry/breaker ORKESTRE ETMEZ** (C4 — o 7.1.4'ün işi).

Vendor-neutral (ADR-001/002): gerçek SOAP/GraphQL/webhook transport bir **SPI noktasıdır**. Referans probe
wire'ı deterministik `wire_script` ile **modeller** (gerçek ağ/credential YOK); canlıda **AYNI imza** arkasına
gerçek protokol client + connection pool (FR-RES-006) takılır.

## 2. 7.2.1 (REST) ile ortaklık ve fark

| Boyut | 7.2.1 REST | 7.2.2 SOAP/GraphQL/webhook |
|---|---|---|
| SPI / AttemptOutcome | aynı | **aynı** (+ `protocol` alanı) |
| fault_taxonomy (7.1.4 hizalı) | aynı | **aynı** |
| transport status→fault tablosu | C2 | **aynı (C2)** |
| connection pooling (C7) | var | **aynı** |
| sır referansla (C5), audit no-log (C6), enjeksiyon (C10), kanonik endpoint (C11) | var | **aynı (+ imza/XML/parametreli variables)** |
| HTTP method | spec'ten | hep **POST** |
| **protokol-farkında fault tespiti** | — | **C13 (yeni)** |

## 3. Protokol-farkında fault tespiti (C13) — bu modülün ek değeri

Transport HTTP status'u **tek başına** yanıltıcı olabilir; protokol gövdesi nihai sınıfı belirler.

### 3.1 SOAP — `<soap:Fault>` rolü status'u ezer
| Gövde | fault_class | sınıf | retryable |
|---|---|---|---|
| HTTP 200, fault yok | — (ok) | — | — |
| HTTP 500, fault `Sender`/`Client` | `UPSTREAM_4XX` | terminal | ✗ |
| HTTP 500, fault `Receiver`/`Server` | `UPSTREAM_5XX` | retryable | ✓ |
| HTTP 500, fault bilinmeyen rol | `UPSTREAM_4XX` | terminal | ✗ (güvenli) |
| HTTP 4xx/5xx, fault yok | transport eşleme (C2) | | |

**Neden:** naif "HTTP 500 → UPSTREAM_5XX retryable" bir **Sender** (istemci) hatasında futile retry'a yol
açar. SOAP rolü istemci/sunucu ayrımını taşır → doğru retryability.

### 3.2 GraphQL — HTTP 200 + `errors[]` → fault
`extensions.code` → fault_class: `UNAUTHENTICATED`/`FORBIDDEN`→`AUTH_FAILED`;
`BAD_USER_INPUT`/`GRAPHQL_VALIDATION_FAILED`/`GRAPHQL_PARSE_FAILED`→`SCHEMA_INVALID`;
`INTERNAL_SERVER_ERROR`→`UPSTREAM_5XX`; `RATE_LIMITED`/`THROTTLED`→`RATE_LIMITED`; **bilinmeyen kod→`UPSTREAM_4XX`**
(terminal, güvenli — anlamadığımız hatayı kör retry etmeyiz → mutation duplicate önleme).

**Neden:** GraphQL hataları HTTP 200 içinde döner; naif "200→ok" hatayı maskeler.

### 3.3 Webhook — HMAC imza zorunlu
`signing.ref` (`${ENV}`) olmadan teslimat denenmez → `MISSING_SIGNING_CONFIG`. İmza değeri gövdeden+secret'tan
türetilir, **audit'lenmez/loglanmaz** (yalnız `signed=true`). Teslimat at-least-once; status REST-benzeri
eşlenir. API §10.1 webhook envelope imza desenine hizalı.

## 4. operation_class (C3; 7.1.4 write-retry/idempotency köprüsü FR-TOOL-009)
- **SOAP:** operation `side_effect` (default `write` — RPC POST).
- **GraphQL:** `op_type` query→**read** / mutation→**write**.
- **Webhook:** daima **write** (teslimat yan-etkili bildirim).

## 5. İnvariantlar (C1–C13)

| # | İnvariant |
|---|---|
| C1 | Bildirimsel deterministik istek kurulumu. |
| C2 | Transport HTTP status → fault_class TOPLAM eşleme, 7.1.4 hizalı (7.2.1 ile aynı tablo). |
| C3 | operation_class: SOAP side_effect / GraphQL query→read·mutation→write / webhook→write. |
| C4 | AttemptOutcome SPI; connector retry/breaker **orkestre etmez** (tek deneme). |
| C5 | Sır + webhook imza yalnız referansla (`${ENV}`); literal → reddedilir; değer asla loglanmaz. |
| C6 | Audit no-log — yalnız correlation_id+endpoint+protocol+method+status_code+fault_class+pooled+signed. |
| C7 | Connection pooling (FR-RES-006) — scheme+host+port anahtarlı; warm-reuse vs cold-connect. |
| C8 | Bağlam taşıma — correlation_id daima; idempotency_key varsa write'ta (üretmez). |
| C9 | Determinizm — sanal saat; Date.now/gerçek-rastgele YOK. |
| C10 | Enjeksiyon güvenli — header CRLF→`INJECTION_REJECTED`; SOAP gövde XML-escape; GraphQL parametreli variables. |
| C11 | Kanonik endpoint kimliği — interpolesiz düşük-kardinalite (soapAction / operationName / event-type). |
| C12 | Vendor-neutral transport SPI — wire bir seam; mantık transport'tan bağımsız. |
| C13 | **Protokol-farkında fault tespiti** — SOAP rol / GraphQL errors[] / webhook imza. |

## 6. Enjeksiyon güvenliği (C10) — protokole göre
- **Header'a bağlanan değerler** (correlation_id, soap_action, auth/signature header adı): CRLF/kontrol
  karakteri → `INJECTION_REJECTED`, istek WIRE'a gitmez.
- **SOAP gövde alanları:** XML-escape (`< > & " '`) → tag enjeksiyonu nötralize (escape, reddetme değil).
- **GraphQL değişkenleri:** JSON `variables` olarak iletilir, query **statik template** → kullanıcı değeri
  query string'e enterpole edilmez (yapısal injection-güvenli).
- **Webhook payload:** JSON serileştirme ile kaçışlanır.

## 7. Doğrulama
`protocol_connector_probe.py`: `validate` (statik spec/config/şema + taksonomi + protocol_override hizalama +
sır/PII tarama), `call <sample>` (deterministik çağrı + C1–C13 kapısı), `selftest` (gömülü davranış), `schema`.
`tests/protocol_connector_behavior_test.py` kara-kutu davranış sözleşmeleri. Tümü stdlib-only, credential-free,
deterministik. Canlı transport `run_live_test.sh` + `${SGW_CONNECTOR_ENDPOINT}` ile (repoya yazılmaz).

## 8. İzlenebilirlik
FR-TOOL-001 · FR-RES-006 · FR-TOOL-009 (köprü) · FR-TST-008 · SR-TOOL-001 · TC-TOOL-001 ·
SAD §11.1/§11.2/§20 · API §10.1 (webhook imza) / §11.6 (fault taksonomi) · ADR-001/002/003 ·
NFR 10.1 (latency soft) / 10.7 (residency/no-log) · sibling 7.2.1 (REST) · tüketen: 7.1.4 · 7.2.3 · 7.1.5 · 7.1.6.
