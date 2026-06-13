# API Tasarım Dokümanı (API)
## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**OpenAPI 3.1 Sözleşmeleri (L0/L1/L2 + Public Developer API) · Adapter SPI Sözleşmeleri (STT/TTS/LLM/Telephony) · Webhooks · Real-time Interfaces**
SAD §8.1 (Adapter SPI) · §14.4 (Panel/AuthZ) → doğrulanabilir API sözleşmeleri

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Enterprise Voice AI Agent Platform — API Tasarım Dokümanı |
| Doküman Tipi | API & Interface Design Document (Interface Control Document, ICD) |
| Hedef Ürün | Multi-Tenant Enterprise Voice AI Agent Platform |
| Kaynak Dokümanlar | `docs/BRD.md` (v2.1) · `docs/SAD.md` (v1.1) · `docs/SRS.md` (v1.0) · `docs/DB.md` (v1.0) |
| Amaç | SAD §8.1 ve §14.4'ü makine-okunur API sözleşmelerine (OpenAPI 3.1) ve adapter SPI sözleşmelerine indirmek |
| Sürüm | 1.0 |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | İlk sürüm. Dört REST API yüzeyi (L0 Platform Control Plane, L1 Tenant Admin, L2 Operations, Public Developer API) OpenAPI 3.1 sözleşmesine; dört adapter kategorisi (STT/TTS/LLM/Telephony) SPI sözleşmesine; webhook event kataloğu + imzalama/retry; real-time medya/orchestrator/tool arayüzleri; ortak konvansiyonlar (versiyonlama, hata modeli RFC 9457, idempotency, pagination, rate limiting, AuthZ/permission-key eşlemesi). SAD §8.1/§8.2/§14.4 ile hizalı. WBS 0.1.4. |

---

## İçindekiler

1. [Amaç ve Kapsam](#1-amaç-ve-kapsam)
2. [API Yüzeyleri (Taxonomy)](#2-api-yüzeyleri-taxonomy)
3. [Tasarım İlkeleri](#3-tasarım-i̇lkeleri)
4. [Ortak Konvansiyonlar (REST)](#4-ortak-konvansiyonlar-rest)
   - 4.1 [Versiyonlama ve base path](#41-versiyonlama-ve-base-path)
   - 4.2 [Kimlik doğrulama ve yetkilendirme](#42-kimlik-doğrulama-ve-yetkilendirme)
   - 4.3 [Hata modeli (RFC 9457)](#43-hata-modeli-rfc-9457)
   - 4.4 [Idempotency, pagination, filtreleme, rate limiting](#44-idempotency-pagination-filtreleme-rate-limiting)
   - 4.5 [İzlenebilirlik başlıkları](#45-i̇zlenebilirlik-başlıkları)
5. [Ortak OpenAPI Bileşenleri (components)](#5-ortak-openapi-bileşenleri-components)
6. [L0 — Platform Control Plane API](#6-l0--platform-control-plane-api)
7. [L1 — Tenant Admin API](#7-l1--tenant-admin-api)
8. [L2 — Operations API](#8-l2--operations-api)
9. [Public Developer API](#9-public-developer-api)
10. [Webhooks (giden olay sözleşmeleri)](#10-webhooks-giden-olay-sözleşmeleri)
11. [Adapter SPI Sözleşmeleri](#11-adapter-spi-sözleşmeleri)
    - 11.1 [Ortak SPI tipleri ve cross-cutting](#111-ortak-spi-tipleri-ve-cross-cutting)
    - 11.2 [SttAdapter](#112-sttadapter)
    - 11.3 [TtsAdapter](#113-ttsadapter)
    - 11.4 [LlmAdapter](#114-llmadapter)
    - 11.5 [TelephonyAdapter](#115-telephonyadapter)
    - 11.6 [Fallback ve hata taksonomisi sözleşmesi](#116-fallback-ve-hata-taksonomisi-sözleşmesi)
12. [Real-time / Data-plane Arayüzleri](#12-real-time--data-plane-arayüzleri)
13. [Yetkilendirme Eşlemesi (permission-key → endpoint)](#13-yetkilendirme-eşlemesi-permission-key--endpoint)
14. [Versiyonlama, Deprecation ve Yaşam Döngüsü](#14-versiyonlama-deprecation-ve-yaşam-döngüsü)
15. [İzlenebilirlik (FR/SR Eşlemesi)](#15-i̇zlenebilirlik-frsr-eşlemesi)
16. [Açık Kararlar ve Sonraki Adımlar](#16-açık-kararlar-ve-sonraki-adımlar)

---

## 1. Amaç ve Kapsam

Bu doküman, platformun **dış (north-bound) REST API'lerini** ve **iç (south-bound) adapter SPI
sözleşmelerini** tanımlar. SAD §8.1'deki adapter arayüz taslağını ve §14.4'teki panel/AuthZ kararlarını,
implementasyona ve sözleşme testine hazır **makine-okunur sözleşmelere** indirir.

**Kapsam içi:**
- **Yönetim/kontrol API'leri** (senkron REST, OpenAPI 3.1): L0 Platform, L1 Tenant Admin, L2 Operations,
  Public Developer API — kaynaklar, metotlar, şemalar, hata modeli, AuthZ.
- **Adapter SPI'leri** (vendor-neutral, pluggable): STT, TTS, LLM, Telephony — metot imzaları, veri tipleri,
  ortak yetenekler (timeout/retry/circuit breaker/health/metering/region/retention/error-normalization), fallback.
- **Webhooks:** tenant sistemlerine giden olay sözleşmeleri (envelope, imzalama, retry, replay).
- **Real-time arayüzler (sözleşme düzeyinde):** medya WebSocket çerçevesi, orchestrator turn-event şeması,
  Integration Gateway tool-call sözleşmesi.

**Kapsam dışı (referansla işaret edilir):** Frontend route yapısı (SAD §14.4.1), fiziksel veri şeması
(`docs/DB.md`), telekom sağlayıcı seçimi (ADR-002, vendor eval), gRPC/protobuf IDL'lerin tam üretimi
(SPI burada dil-nötr tanımlanır; kod aşamasında Go interface + protobuf'a türetilir).

> **Source of truth:** Çelişki olursa `docs/BRD.md` ve `docs/SAD.md` esastır; bu doküman onlardan türer.
> Vendor seçimi yapılmaz (vendor-neutral, ADR-001/002). Secret/credential üretilmez; örneklerde yalnızca
> placeholder (`<token>`, `whsec_…`) kullanılır.

---

## 2. API Yüzeyleri (Taxonomy)

Platformun beş ayrı arayüz sınıfı vardır; her biri farklı güven sınırına, auth realm'ine ve değişim
hızına sahiptir (SAD §4.2, §14.4):

| # | Yüzey | Tip | Tüketici | Auth realm | Deploy | Kaynak |
|---|-------|-----|----------|-----------|--------|--------|
| S1 | **L0 Platform Control Plane API** | REST/JSON (OpenAPI 3.1) | RMC platform operatörü (cross-tenant) | Platform IdP (ayrı) | Internal-only (VPN/allowlist/private endpoint) | SAD §14.4.2, ADR-011 |
| S2 | **L1 Tenant Admin API** | REST/JSON (OpenAPI 3.1) | Tenant admini (tek tenant) | Tenant IdP (SSO) | Tenant Application Plane (public) | SAD §14.4.2 |
| S3 | **L2 Operations API** | REST/JSON (OpenAPI 3.1) | Tenant operasyon ekibi (tek tenant) | Tenant IdP (SSO) | Tenant Application Plane (public) | SAD §14.4.2 |
| S4 | **Public Developer API** | REST/JSON (OpenAPI 3.1) | Tenant'ın kurumsal sistemleri (M2M) | API key + HMAC imza | Tenant Application Plane (public) | BRD §6.1, `api_developer` |
| S5 | **Adapter SPI** | Dil-nötr interface (Go/protobuf'a türetilir) | Orchestrator → sağlayıcı adapter | mTLS / iç ağ | Data plane (internal) | SAD §8.1 |

Ek olarak iki **olay-tabanlı** yüzey (REST değil):
- **Webhooks (out):** platform → tenant sistemleri (bkz. §10).
- **Real-time medya/event akışları:** telekom ↔ media gateway ↔ orchestrator (bkz. §12).

> **Tasarım kararı:** S1 ayrı bir servis ve ayrı OpenAPI dokümanı olarak yayınlanır (blast-radius izolasyonu,
> ADR-011). S2/S3/S4 aynı *Tenant Application Plane*'de fakat ayrı router ağaçları + ayrı OAuth scope ile
> ayrışır. S4 (developer API), S2/S3'ün **kısıtlı, sözleşme-stabil bir alt kümesini** dışa açar; iç panel
> endpoint'leri public API garantisi vermez.

---

## 3. Tasarım İlkeleri

| İlke | Açıklama | İz |
|------|----------|-----|
| **Contract-first** | OpenAPI 3.1 + SPI sözleşmesi kaynak doğruluktur; sunucu/istemci stub'ları ve sözleşme testleri buradan üretilir | SAD §3 |
| **Vendor-neutral SPI** | Orchestrator yalnız SPI'ye bağımlı; sağlayıcı detayı adapter'da kapsüllenir; kategori başına ≥2 sağlayıcı + fallback | SAD §8.1, ADR-001 |
| **Plane separation** | L0 ayrı servis/realm; L0 tenant iş verisi repository'lerine bağlı değil (break-glass dışında) | SAD §14.4.2, FR-IAM-008 |
| **AuthZ her zaman backend'de** | UI yalnız görsel kapı; her endpoint panel+rol+tenant scope ile korunur | SAD §14.4.1/2 |
| **Tenant izolasyonu çift katmanlı** | Token'dan türeyen `tenant_id` + PostgreSQL RLS; cross-tenant erişim reddi | FR-TEN-002, DB §6 |
| **Stream-first hot path** | Gerçek zamanlı ses REST değil; WS/gRPC stream ile (no full buffering) | FR-RES-002, SAD §8.1 |
| **Deterministic & idempotent yazma** | Tüm POST/PATCH side-effect'leri `Idempotency-Key` ile tekrar-güvenli | FR-TOOL-009 |
| **Observable by default** | `correlation_id` her istekte propagate; usage metering her adapter çağrısında | SAD §13.3/§17.1, FR-BIL-002 |
| **Compliance by design** | PII redaction panel görüntülemede; hassas içerik sağlayıcı loglarına gitmez; residency adapter'da zorlanır | BRD §17.7, FR-KB-010, NFR 10.7 |
| **Backward-compatible evrim** | Additive değişiklik minor; breaking değişiklik yeni major path (`/v2`) + deprecation süreci | §14 |

---

## 4. Ortak Konvansiyonlar (REST)

S1–S4 yüzeyleri aşağıdaki ortak kuralları paylaşır.

### 4.1 Versiyonlama ve base path

Major sürüm URL path'inde taşınır; her yüzeyin ayrı base path'i vardır:

| Yüzey | Base URL (örnek) |
|-------|------------------|
| L0 Platform | `https://platform.internal.rmcvoice.io/platform/v1` |
| L1 Tenant Admin | `https://api.rmcvoice.io/admin/v1` |
| L2 Operations | `https://api.rmcvoice.io/ops/v1` |
| Public Developer | `https://api.rmcvoice.io/public/v1` |

- Host adları örnektir; gerçek bölge/host residency'ye göre belirlenir (NFR 10.7).
- L1/L2/L4'te tenant, **path'te taşınmaz**; oturum/anahtardan türetilir (tenant pinning, §4.2).
- Media-type: `application/json; charset=utf-8`. Hatalar `application/problem+json` (§4.3).

### 4.2 Kimlik doğrulama ve yetkilendirme

| Yüzey | AuthN | AuthZ |
|-------|-------|-------|
| L0 | OIDC bearer (platform IdP); mTLS opsiyonel; ağ private-endpoint arkasında | Platform rolleri (`platform_*`) + permission-key |
| L1/L2 | OIDC bearer (tenant SSO; SAML 2.0/OIDC federe — FR-IAM-002) | Tenant rolleri + scoped assignment (FR-IAM-011) |
| Public | `Authorization: ApiKey <key_id>:<...>` + `X-Signature: <hmac-sha256>` (request body + timestamp) | `api_developer` permission alt kümesi |

- Access token claim seti (kavramsal): `sub`, `tenant_id`, `panel` (`L0`/`L1`/`L2`), `roles[]`,
  `scopes[]` (departman/marka/kampanya filtresi), `exp`. Yetki kararı backend guard'da verilir (SAD §14.4.2).
- **Break-glass:** L0'ın Tier B (transkript/kayıt/PII) erişimi normal token ile **reddedilir**; ayrı,
  kısıtlı, tam-audit'li break-glass endpoint ailesi ve süreli (max 4 sa) `X-BreakGlass-Grant` token'ı
  gerektirir (§6, FR-IAM-009/010).
- API key güvenliği: imza zaman damgası ±300 sn pencereyle replay-korumalı; anahtar rotasyonu L1'de
  yönetilir (FR-IAM-011, T-05). Secret değer yalnız oluşturmada bir kez döner; sonra hash saklanır.

### 4.3 Hata modeli (RFC 9457)

Tüm hatalar `application/problem+json` (Problem Details) döner; sağlayıcıya özel teknik detay sızdırılmaz
(FR-TOOL-008). Ortak `Problem` şeması §5'tedir.

```json
{
  "type": "https://errors.rmcvoice.io/tenant-scope-violation",
  "title": "Cross-tenant access denied",
  "status": 403,
  "detail": "Resource belongs to a different tenant.",
  "instance": "/ops/v1/calls/01J...",
  "code": "AUTHZ_TENANT_SCOPE",
  "correlation_id": "01J9...ZK"
}
```

Standart HTTP eşlemesi: `400` doğrulama, `401` AuthN, `403` AuthZ/scope, `404` yok/tenant dışı (enumerasyon
sızıntısını önlemek için cross-tenant kaynak `404` da olabilir), `409` idempotency/çakışma, `422` semantik
doğrulama, `429` rate limit, `5xx` sunucu. Kararlı makine-okunur `code` alanı (enum) hata taksonomisini taşır.

### 4.4 Idempotency, pagination, filtreleme, rate limiting

- **Idempotency:** Yan etkili `POST` (ör. outbound çağrı başlat, kampanya oluştur) `Idempotency-Key`
  header'ı kabul eder; aynı anahtar + aynı gövde → aynı sonuç; farklı gövde → `409` (FR-TOOL-009).
- **Pagination:** Cursor tabanlı; `?limit=` (default 50, max 200) + `?cursor=`. Yanıt zarfı `Page<T>`
  (`items`, `next_cursor`, `has_more`). Offset paging yüksek hacimli tablolarda kullanılmaz (DB §7).
- **Filtreleme/sıralama:** Whitelist alanlar; `?filter[status]=completed&sort=-started_at`. Serbest sorgu yok.
- **Rate limiting:** Tenant + anahtar bazında token-bucket; `429` + `Retry-After` + `RateLimit-*` (RFC 9239
  taslak başlıkları). Public API kotaları tenant planına bağlı (FR-BIL-004); admission control backpressure
  ile uyumlu (FR-RES-014).

### 4.5 İzlenebilirlik başlıkları

| Header | Yön | Açıklama |
|--------|-----|----------|
| `X-Correlation-Id` | in/out | Yoksa üretilir; tüm log/trace/event span'lerine propagate (SAD §13.3/§17.1) |
| `Idempotency-Key` | in | Yan etkili POST için (§4.4) |
| `X-Signature` / `X-Signature-Timestamp` | in (S4) | HMAC imza (developer API) ve webhook doğrulaması (§10) |
| `RateLimit-Limit/Remaining/Reset` | out | Kota durumu |
| `Deprecation` / `Sunset` | out | Deprecation politikası (§14, RFC 8594) |

---

## 5. Ortak OpenAPI Bileşenleri (components)

Tüm yüzeyler aşağıdaki `components`'ı paylaşır (tek `commons.yaml`, `$ref` ile çekilir).

```yaml
openapi: 3.1.0
info:
  title: RMC Voice AI — Common Components
  version: "1.0"
components:
  securitySchemes:
    oidcAuth:
      type: openIdConnect
      openIdConnectUrl: https://idp.rmcvoice.io/.well-known/openid-configuration
    apiKeyAuth:                     # Public Developer API (S4)
      type: apiKey
      in: header
      name: Authorization          # "ApiKey <key_id>:<secret-ref>"; istek ayrıca X-Signature taşır
  parameters:
    Cursor:   { name: cursor, in: query, schema: { type: string }, description: Opaque sayfa imleci }
    Limit:    { name: limit,  in: query, schema: { type: integer, minimum: 1, maximum: 200, default: 50 } }
    CorrelationId:
      name: X-Correlation-Id
      in: header
      required: false
      schema: { type: string, maxLength: 64 }
    IdempotencyKey:
      name: Idempotency-Key
      in: header
      required: false
      schema: { type: string, maxLength: 128 }
  schemas:
    Problem:                        # RFC 9457
      type: object
      required: [title, status, code]
      properties:
        type:    { type: string, format: uri }
        title:   { type: string }
        status:  { type: integer }
        detail:  { type: string }
        instance:{ type: string }
        code:    { type: string, description: "Kararlı makine-okunur hata kodu (taksonomi)" }
        correlation_id: { type: string }
        errors:                     # alan-bazlı doğrulama
          type: array
          items:
            type: object
            properties:
              field:   { type: string }
              message: { type: string }
    PageMeta:
      type: object
      required: [has_more]
      properties:
        next_cursor: { type: string, nullable: true }
        has_more:    { type: boolean }
    Money:
      type: object
      properties:
        amount_minor: { type: integer, description: "Minor unit (kuruş/penny)" }
        currency:     { type: string, minLength: 3, maxLength: 3 }
    Region:
      type: string
      enum: [uk, eu, na, me]        # NFR 10.7 home-region
  responses:
    BadRequest:   { description: Geçersiz istek,    content: { application/problem+json: { schema: { $ref: '#/components/schemas/Problem' } } } }
    Unauthorized: { description: Kimlik doğrulanmadı, content: { application/problem+json: { schema: { $ref: '#/components/schemas/Problem' } } } }
    Forbidden:    { description: Yetki/scope reddi,  content: { application/problem+json: { schema: { $ref: '#/components/schemas/Problem' } } } }
    NotFound:     { description: Bulunamadı,         content: { application/problem+json: { schema: { $ref: '#/components/schemas/Problem' } } } }
    Conflict:     { description: Çakışma/idempotency,content: { application/problem+json: { schema: { $ref: '#/components/schemas/Problem' } } } }
    TooManyRequests:
      description: Rate limit
      headers: { Retry-After: { schema: { type: integer } } }
      content: { application/problem+json: { schema: { $ref: '#/components/schemas/Problem' } } }
```

> **ID konvansiyonu:** Tüm kaynak ID'leri UUIDv7 string (DB §3); `operationId` = `<area><Verb>` (ör.
> `tenantsCreate`, `callsGet`). Tüm zaman damgaları RFC 3339 / UTC.

---

## 6. L0 — Platform Control Plane API

**Internal-only** (ADR-011). Tenant iş verisine (call/transcript/PII) **erişmez**; yalnız metrik, kaynak,
provisioning ve yönetişim verisi. İçeriğe erişim yalnız üç katmanlı break-glass ile (FR-IAM-008/009/010).

### 6.1 Kaynak kataloğu (özet)

| Kaynak | Metot · Path | İzin (permission-key) | İz |
|--------|--------------|------------------------|-----|
| Tenants | `GET/POST /tenants`, `GET/PATCH /tenants/{id}`, `POST /tenants/{id}:suspend` | `tenant:provision`, `tenant:suspend` | FR-TEN-001/005, P-02 |
| Resource/Quota | `GET /tenants/{id}/quota`, `PUT /tenants/{id}/quota` | `resource:quota:manage` | FR-TEN-006/007, P-03 |
| Providers | `GET /providers`, `GET /providers/{id}/health`, `PUT /providers/{id}/routing` | `provider:health:read`, `provider:routing:manage` | SAD §8.3, P-04 |
| Platform billing | `GET /billing/usage`, `GET/PUT /billing/rate-cards/{id}` | `platform:billing:manage` | FR-BIL-002, P-05 |
| Global policy | `GET/PUT /policies/global` | `policy:global:manage` | FR-AGT-009, P-06 |
| Platform audit | `GET /audit` (yalnız platform olayları) | `platform:audit:read` | FR-IAM-006, P-07 |
| Releases | `GET/POST /releases`, `POST /releases/{id}:rollout` | `release:manage` | P-08 |
| Incidents | `GET/POST /incidents`, `PATCH /incidents/{id}` | `incident:manage` | BRD §15, P-09 |
| **Break-glass** | `POST /break-glass/requests`, `POST /break-glass/requests/{id}:approve`, `GET /break-glass/grants` | maker-checker; ayrı router | FR-IAM-009/010 |

### 6.2 Temsilî sözleşme — Tenants + Break-glass

```yaml
openapi: 3.1.0
info: { title: "RMC Voice AI — Platform Control Plane API (L0)", version: "1.0" }
servers: [{ url: https://platform.internal.rmcvoice.io/platform/v1 }]
security: [{ oidcAuth: [] }]
paths:
  /tenants:
    get:
      operationId: tenantsList
      x-required-permission: "tenant:provision"
      parameters:
        - $ref: 'commons.yaml#/components/parameters/Cursor'
        - $ref: 'commons.yaml#/components/parameters/Limit'
        - { name: "filter[status]", in: query, schema: { type: string, enum: [active, suspended, provisioning] } }
      responses:
        '200':
          description: Tenant listesi
          content:
            application/json:
              schema:
                type: object
                properties:
                  items: { type: array, items: { $ref: '#/components/schemas/Tenant' } }
                  meta:  { $ref: 'commons.yaml#/components/schemas/PageMeta' }
        '403': { $ref: 'commons.yaml#/components/responses/Forbidden' }
    post:
      operationId: tenantsCreate
      x-required-permission: "tenant:provision"
      parameters: [ { $ref: 'commons.yaml#/components/parameters/IdempotencyKey' } ]
      requestBody:
        required: true
        content: { application/json: { schema: { $ref: '#/components/schemas/TenantCreate' } } }
      responses:
        '201': { description: Oluşturuldu, content: { application/json: { schema: { $ref: '#/components/schemas/Tenant' } } } }
        '409': { $ref: 'commons.yaml#/components/responses/Conflict' }
  /tenants/{id}:suspend:
    post:
      operationId: tenantsSuspend
      x-required-permission: "tenant:suspend"
      parameters: [ { name: id, in: path, required: true, schema: { type: string } } ]
      requestBody:
        content: { application/json: { schema: { type: object, properties: { reason_code: { type: string } }, required: [reason_code] } } }
      responses: { '202': { description: Askıya alma kuyruğa alındı }, '404': { $ref: 'commons.yaml#/components/responses/NotFound' } }
  /break-glass/requests:
    post:
      operationId: breakGlassRequest
      description: >
        Tier B (transkript/kayıt/PII) erişimi için talep. maker-checker zorunlu (talep eden ≠ onaylayan).
        Onay sonrası süreli grant (default 60 dk, max 4 saat, otomatik expiry, standing access yok).
      x-required-permission: "platform:audit:read"          # talebi açma; erişim ayrı grant ile
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [tenant_id, scope, reason_code, ttl_minutes]
              properties:
                tenant_id:   { type: string }
                scope:       { type: string, enum: [transcript, recording, pii] }
                reason_code: { type: string }
                ttl_minutes: { type: integer, minimum: 1, maximum: 240, default: 60 }
      responses:
        '201': { description: Talep kaydı (pending), content: { application/json: { schema: { $ref: '#/components/schemas/BreakGlassRequest' } } } }
        '403':
          description: >
            Regüle tenant'ta require_tenant_approval=true ise tenant onayı olmadan reddedilir (FR-IAM-010).
          content: { application/problem+json: { schema: { $ref: 'commons.yaml#/components/schemas/Problem' } } }
components:
  schemas:
    Tenant:
      type: object
      properties:
        id:            { type: string }
        name:          { type: string }
        status:        { type: string, enum: [active, suspended, provisioning] }
        home_region:   { $ref: 'commons.yaml#/components/schemas/Region' }
        isolation:     { type: string, enum: [shared, dedicated] }          # FR-TEN-005
        regulated_profile: { type: boolean }                                # FR-IAM-010 default toggle
        created_at:    { type: string, format: date-time }
    TenantCreate:
      type: object
      required: [name, home_region]
      properties:
        name:        { type: string }
        home_region: { $ref: 'commons.yaml#/components/schemas/Region' }
        isolation:   { type: string, enum: [shared, dedicated], default: shared }
        regulated_profile: { type: boolean, default: false }
    BreakGlassRequest:
      type: object
      properties:
        id:          { type: string }
        tenant_id:   { type: string }
        scope:       { type: string }
        state:       { type: string, enum: [pending, approved, rejected, expired] }
        requested_by:{ type: string }
        approved_by: { type: string, nullable: true }
        expires_at:  { type: string, format: date-time, nullable: true }
```

> **Not (FR-IAM-008):** L0 OpenAPI'sinde `GET /calls`, `GET /transcripts` gibi iş-verisi endpoint'i
> **bulunmaz**. İçerik yalnız onaylı break-glass grant ile, ayrı bir kısıtlı router üzerinden erişilir;
> her erişim WORM audit'e yazılır (DB §6, FR-REC-009).

---

## 7. L1 — Tenant Admin API

Tek tenant; tenant SSO realm. Organizasyon, kullanıcı/rol, numara, entegrasyon, **API key/webhook**,
compliance/retention/consent, faturalama, audit, kota.

### 7.1 Kaynak kataloğu (özet)

| Kaynak | Metot · Path | İzin | İz |
|--------|--------------|------|-----|
| Org units | `GET/POST/PATCH /org-units` | `org:manage` | FR-TEN-003, T-02 |
| Users | `GET/POST/PATCH/DELETE /users` | `user:manage` | FR-IAM-007, T-03 |
| Role assignments | `GET/POST/DELETE /role-assignments` (rol + scope) | `role:assign` | FR-IAM-011, ADR-012 |
| Phone numbers / SIP | `GET/POST /numbers`, `GET/POST /sip-trunks` | `number:manage` | FR-TEL-004/005, T-04 |
| Integrations | `GET/POST/PATCH /integrations` (CRM/ERP/ticketing) | `integration:manage` | BRD §6.1, T-05 |
| **API keys** | `GET/POST /api-keys`, `POST /api-keys/{id}:rotate`, `DELETE /api-keys/{id}` | `apikey:manage` | T-05, S4 |
| **Webhooks** | `GET/POST/PATCH/DELETE /webhooks`, `POST /webhooks/{id}:test` | `integration:manage` | §10, T-05 |
| Compliance | `GET/PUT /compliance/profile`, `GET/PUT /retention/policies`, `GET/POST /consent` | `compliance:manage`, `retention:manage`, `consent:manage` | §14, T-06 |
| Billing (read) | `GET /billing/usage`, `GET /billing/invoices` | `tenant:billing:read` | FR-BIL-001, T-07 |
| Audit (tenant) | `GET /audit` | `tenant:audit:read` | FR-IAM-006, T-08 |
| Quota (read) | `GET /quota` | `quota:read` | FR-TEN-006/007, T-09 |

### 7.2 Temsilî sözleşme — API key + Webhook + Role assignment

```yaml
paths:
  /api-keys:
    post:
      operationId: apiKeysCreate
      x-required-permission: "apikey:manage"
      requestBody:
        required: true
        content: { application/json: { schema: { type: object, required: [name, scopes], properties: {
          name: { type: string }, scopes: { type: array, items: { type: string } } } } } }
      responses:
        '201':
          description: >
            Oluşturuldu. `secret` alanı YALNIZ bir kez döner; sunucu yalnız hash saklar.
          content: { application/json: { schema: { $ref: '#/components/schemas/ApiKeyCreated' } } }
  /webhooks:
    post:
      operationId: webhooksCreate
      x-required-permission: "integration:manage"
      requestBody:
        required: true
        content: { application/json: { schema: { $ref: '#/components/schemas/WebhookEndpoint' } } }
      responses:
        '201': { description: Oluşturuldu, content: { application/json: { schema: { $ref: '#/components/schemas/WebhookEndpointCreated' } } } }
  /role-assignments:
    post:
      operationId: roleAssignmentsCreate
      x-required-permission: "role:assign"
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [user_id, role]
              properties:
                user_id: { type: string }
                role:    { type: string, enum: [tenant_admin, security_compliance_officer, billing_viewer,
                                                operations_manager, conversation_designer, qa_analyst,
                                                human_agent, api_developer] }
                scope:   { type: object, description: "departman/marka/kampanya filtresi (FR-IAM-011)",
                           properties: { org_unit_id: {type: string}, brand: {type: string}, campaign_id: {type: string} } }
      responses: { '201': { description: Atandı } }
components:
  schemas:
    ApiKeyCreated:
      allOf:
        - { type: object, properties: { id: {type: string}, name: {type: string}, scopes: {type: array, items: {type: string}}, created_at: {type: string, format: date-time} } }
        - { type: object, properties: { secret: { type: string, description: "Bir kez döner; saklanmaz" } } }
    WebhookEndpoint:
      type: object
      required: [url, events]
      properties:
        url:    { type: string, format: uri, description: "HTTPS zorunlu" }
        events: { type: array, items: { type: string }, description: "Abone olunan event tipleri (§10.2)" }
        active: { type: boolean, default: true }
    WebhookEndpointCreated:
      allOf:
        - { $ref: '#/components/schemas/WebhookEndpoint' }
        - { type: object, properties: { id: {type: string}, signing_secret: { type: string, description: "whsec_… — imza doğrulama; bir kez döner" } } }
```

---

## 8. L2 — Operations API

Günlük operasyon: agent yaşam döngüsü, flow/prompt/voice/model, KB, tool binding, kampanya, çağrı kayıt/
transkript, QA, analitik, maliyet, test, canlı çağrı. `*:own` izinleri kaynak sahipliğiyle sınırlı (human_agent).

### 8.1 Kaynak kataloğu (özet)

| Kaynak | Metot · Path | İzin | İz |
|--------|--------------|------|-----|
| Agents | `GET/POST/PATCH /agents` | `agent:read`, `agent:build` | FR-AGT-001, A-03/04 |
| Agent versions | `GET/POST /agents/{id}/versions`, `POST /agents/{id}/versions/{v}:promote`, `:rollback` | `agent:version:manage` | FR-AGT-005/006, A-17 |
| Flows | `GET/PUT /agents/{id}/flow` | `flow:edit` | FR-AGT-003, A-05 |
| Prompts | `GET/POST /agents/{id}/prompts` (versiyonlu) | `prompt:edit` | FR-AGT-004, FR-LLM-006, A-06 |
| Voice/Model | `GET/PUT /agents/{id}/voice`, `/agents/{id}/model` | `voice:edit` | FR-AGT-002, A-07 |
| Knowledge base | `GET/POST /knowledge-bases`, `POST /knowledge-bases/{id}/documents` | `kb:manage` | FR-KB-001/003, A-08 |
| Tools | `GET/POST /tools`, `POST /agents/{id}/tools:bind` | `tool:bind` | FR-TOOL-001/002, A-09 |
| Campaigns | `GET/POST/PATCH /campaigns`, `POST /campaigns/{id}:stop` | `campaign:manage` | FR-OUT-001/010, A-10 |
| Calls | `GET /calls`, `GET /calls/{id}` | `calls:read` / `calls:read:own` | BRD §8.1, A-11 |
| Transcript | `GET /calls/{id}/transcript`, `GET /calls/{id}/recording` | `transcript:read`, `transcript:manage` | FR-REC-003/004/009, A-12 |
| Live calls | `GET /live-calls`, `POST /live-calls/{id}:transfer`, `:listen` | `livecalls:manage` | FR-ANA-012, FR-HND-*, A-02 |
| QA | `GET/POST /calls/{id}/evaluations` | `qa:score` | FR-ANA-009, A-13 |
| Analytics | `GET /analytics/{report}` | `analytics:read` | FR-ANA-001..011, A-14 |
| Cost | `GET /analytics/cost` | `cost:read` | FR-ANA-007/013, A-15 |
| Test | `POST /test/simulations`, `GET /test/simulations/{id}` | `test:run` | FR-TST-001/002, A-16 |

### 8.2 Temsilî sözleşme — Agent version promote + Call/Transcript (PII maskeli)

```yaml
paths:
  /agents/{id}/versions/{v}:promote:
    post:
      operationId: agentVersionPromote
      description: "draft→test→staging→production geçişi; regression geçmeden production engellenir (FR-TST-004/005, FR-AGT-010)"
      x-required-permission: "agent:version:manage"
      parameters:
        - { name: id, in: path, required: true, schema: { type: string } }
        - { name: v,  in: path, required: true, schema: { type: string } }
      requestBody:
        content: { application/json: { schema: { type: object, required: [target_env], properties: {
          target_env: { type: string, enum: [test, staging, production] } } } } }
      responses:
        '202': { description: Promotion kuyruğa alındı }
        '409': { description: "Regression/gate başarısız → yayın engellendi", content: { application/problem+json: { schema: { $ref: 'commons.yaml#/components/schemas/Problem' } } } }
  /calls/{id}:
    get:
      operationId: callsGet
      x-required-permission: "calls:read"          # human_agent için calls:read:own (sahiplik kontrolü)
      parameters: [ { name: id, in: path, required: true, schema: { type: string } } ]
      responses:
        '200': { description: Çağrı detayı, content: { application/json: { schema: { $ref: '#/components/schemas/Call' } } } }
        '403': { $ref: 'commons.yaml#/components/responses/Forbidden' }
  /calls/{id}/transcript:
    get:
      operationId: callsGetTranscript
      description: "PII varsayılan maskeli döner (BRD §17.7); ham erişim ayrı yetki + audit gerektirir (FR-REC-009)"
      x-required-permission: "transcript:read"
      parameters:
        - { name: id, in: path, required: true, schema: { type: string } }
        - { name: redaction, in: query, schema: { type: string, enum: [masked, raw], default: masked } }
      responses:
        '200': { description: Transkript, content: { application/json: { schema: { $ref: '#/components/schemas/Transcript' } } } }
components:
  schemas:
    Call:
      type: object
      properties:
        id:          { type: string }
        direction:   { type: string, enum: [inbound, outbound] }
        agent_id:    { type: string }
        status:      { type: string, enum: [ringing, in_progress, completed, transferred, failed] }
        from:        { type: string, description: "E.164; panelde maskeli görünebilir" }
        to:          { type: string }
        started_at:  { type: string, format: date-time }
        ended_at:    { type: string, format: date-time, nullable: true }
        end_reason:  { type: string, description: "Standart neden kodu (FR-TEL-012)" }
        outcome:     { type: string, nullable: true }     # FR-ANA-002
        cost:        { $ref: 'commons.yaml#/components/schemas/Money' }
    Transcript:
      type: object
      properties:
        call_id:  { type: string }
        redaction: { type: string, enum: [masked, raw] }
        segments:
          type: array
          items:
            type: object
            properties:
              ts:        { type: number, description: "Çağrı başından saniye" }
              speaker:   { type: string, enum: [agent, caller] }
              text:      { type: string }
              source_refs: { type: array, items: { type: string }, description: "Kaynak atfı (FR-KB-006)" }
```

---

## 9. Public Developer API

`api_developer` rolü; M2M (API key + HMAC). L2/L1'in **sözleşme-stabil bir alt kümesini** dışa açar:
programatik outbound çağrı tetikleme, çağrı/transkript okuma, agent okuma, webhook yönetimi. İç panel
endpoint'lerinin tümü public garantisi vermez; yalnız bu yüzeyde yayınlananlar SemVer garantisi taşır (§14).

### 9.1 Kaynak kataloğu

| Kaynak | Metot · Path | Not | İz |
|--------|--------------|-----|-----|
| Outbound call | `POST /calls` | Consent Engine ön-kontrolünden geçer; geçmezse `422` | FR-OUT-003, §14.3 |
| Call read | `GET /calls`, `GET /calls/{id}`, `GET /calls/{id}/transcript` | PII maskeli default | BRD §8.1 |
| Agents (read) | `GET /agents`, `GET /agents/{id}` | salt-okunur | FR-AGT-001 |
| Knowledge ingest | `POST /knowledge-bases/{id}/documents` | async indexleme | FR-KB-001/003 |
| Webhooks | `GET/POST/DELETE /webhooks` | L1 ile aynı model (§10) | §10 |

### 9.2 Temsilî sözleşme — Outbound call (consent gate + idempotency)

```yaml
servers: [{ url: https://api.rmcvoice.io/public/v1 }]
security: [{ apiKeyAuth: [] }]
paths:
  /calls:
    post:
      operationId: publicCallsCreate
      description: >
        Outbound çağrı tetikler. Consent Engine ön-kontrolü (amaç/ülke/birey-şirket/kaynak/tarih/kapsam),
        do-not-call/suppression, arama saati ve kapasite (backpressure) kontrolünden geçer.
      parameters:
        - $ref: 'commons.yaml#/components/parameters/IdempotencyKey'
        - $ref: 'commons.yaml#/components/parameters/CorrelationId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [agent_id, to, consent_ref]
              properties:
                agent_id:    { type: string }
                to:          { type: string, description: "E.164" }
                consent_ref: { type: string, description: "Doğrulanabilir consent kaydı referansı (FR-OUT-003)" }
                variables:   { type: object, additionalProperties: true, description: "Agent'a verilecek bağlam" }
      responses:
        '202':
          description: Çağrı kuyruğa alındı
          content: { application/json: { schema: { type: object, properties: { call_id: {type: string}, status: {type: string, enum: [queued]} } } } }
        '422':
          description: >
            Consent/suppression/arama-saati reddi veya kapasite limiti (FR-OUT-004/006/007, FR-TEL-013/014/015).
          content: { application/problem+json: { schema: { $ref: 'commons.yaml#/components/schemas/Problem' } } }
        '429': { $ref: 'commons.yaml#/components/responses/TooManyRequests' }
```

> **Compliance gate (zorunlu):** `POST /calls` consent doğrulaması başarısızsa çağrı **başlatılmaz**;
> red nedeni `code` ile döner (`CONSENT_MISSING`, `SUPPRESSED`, `CALLING_HOURS`, `CAPACITY_LIMIT`).
> Bu kontrol istemciye bırakılmaz; sunucuda zorlanır (SAD §19.1).

---

## 10. Webhooks (giden olay sözleşmeleri)

Platform, çağrı yaşam döngüsü ve uzun-işlem sonuçlarını tenant sistemlerine **webhook** ile iletir
(BRD §6.1; Integration Gateway async sonuç, FR-TOOL-011). Tüm webhook'lar §7.1/§9.1'deki endpoint
kaynaklarıyla yönetilir.

### 10.1 Envelope ve teslimat

```json
{
  "id": "evt_01J9...",
  "type": "call.completed",
  "api_version": "v1",
  "created_at": "2026-06-13T10:00:00Z",
  "tenant_id": "01J...",
  "correlation_id": "01J9...ZK",
  "data": { "call_id": "01J...", "status": "completed", "outcome": "resolved", "duration_sec": 142 }
}
```

- **İmzalama:** `X-Signature: t=<unix>,v1=<hmac-sha256(secret, t + "." + body)>`; alıcı imzayı doğrular,
  zaman penceresi ±300 sn (replay koruması). `signing_secret` webhook oluşturmada bir kez döner (§7.2).
- **Teslimat garantisi:** at-least-once; tüketici idempotent olmalı (`id` ile dedup). `2xx` = teslim alındı.
- **Retry:** Üstel backoff + jitter (ör. 1m,5m,30m,2h,6h; ~24 saat); kalıcı başarısızlıkta endpoint
  otomatik `disabled` + L1 alarm. Replay/manuel yeniden gönderim T-05/A-09'dan tetiklenebilir.
- **Sıralama:** Garanti edilmez; `created_at` + sıra alanına göre tüketicide sıralanır.

### 10.2 Event kataloğu (çekirdek)

| Event tipi | Tetik | Payload özeti | İz |
|------------|-------|----------------|-----|
| `call.started` | Çağrı bağlandı | call_id, direction, from/to, agent_id | BRD §15 |
| `call.completed` | Çağrı bitti | call_id, outcome, duration, end_reason, cost | FR-ANA-002, FR-TEL-012 |
| `call.transferred` | İnsan temsilciye aktarım | call_id, target, mode (cold/warm/whisper) | FR-HND-004/008 |
| `call.failed` | Başarısız/düştü | call_id, end_reason | FR-TEL-009 |
| `transcript.ready` | Transkript + redaction hazır | call_id, transcript_url (maskeli) | FR-REC-004 |
| `recording.ready` | Kayıt hazır | call_id, recording_url, channels | FR-REC-003 |
| `tool.async.completed` | Uzun-işlem tool callback | execution_id, status, result_ref | FR-TOOL-011 |
| `campaign.completed` | Kampanya bitti | campaign_id, stats | FR-OUT-008 |
| `quota.threshold` | Kota/bütçe eşiği | metric, usage, limit | FR-BIL-006 |
| `agent.published` | Agent versiyon production | agent_id, version, env | FR-AGT-005/006 |

---

## 11. Adapter SPI Sözleşmeleri

SAD §8.1'in vendor-neutral interface'lerini sözleşme düzeyine indirir. SPI dil-nötr tanımlanır; data plane
implementasyonu Go interface'lerine (hot path) ve gerektiğinde gRPC/protobuf'a (out-of-process adapter)
türetilir (ADR-003). Orchestrator **yalnız** bu SPI'ye bağımlıdır; sağlayıcı değişimi orchestrator'ı etkilemez
(ADR-001). Her kategoride **≥2 sağlayıcı + fallback** zorunludur (BRD §19).

### 11.1 Ortak SPI tipleri ve cross-cutting

Her adapter, kategori-özel metotlarına ek olarak BRD §12'nin zorunlu ortak yeteneklerini sağlar (SAD §8.2).

```
// ---- Ortak değer tipleri ----
type Capabilities {
  providerId:  string
  category:    enum { STT, TTS, LLM, TELEPHONY }
  languages:   []string         // BCP-47
  sampleRates: []int            // STT/TTS; telefon için 8000 birincil (FR-RES-008)
  features:    []string         // ör. "partial", "confidence", "phrase_boost", "barge_in_cancel", "tool_call"
  regions:     []Region         // residency (NFR 10.7)
  noTrain:     bool             // "veri eğitime kapalı" endpoint (FR-LLM-012)
}

type HealthStatus { state: enum {UP, DEGRADED, DOWN}; latencyP95Ms: int; detail: string; checkedAt: timestamp }

type UsageRecord {                // metering + cost (FR-BIL-002, FR-LLM-011)
  providerId: string; region: Region
  unit: enum { SECONDS, CHARACTERS, INPUT_TOKENS, OUTPUT_TOKENS, REQUESTS }
  quantity: number; model: string?; costMinor: int?; currency: string?
  correlationId: string; tenantId: string; callId: string
}

type AdapterError {               // normalize edilmiş hata (FR-TOOL-008, §11.6)
  taxonomy: ErrorTaxonomy         // ortak enum (§11.6)
  retriable: bool
  providerCode: string            // ham sağlayıcı kodu (yalnız log/audit; müşteriye sızmaz)
  message: string
}

// ---- Ortak cross-cutting sözleşme (her adapter) ----
interface Adapter {
  capabilities(): Capabilities
  health(): HealthStatus                  // periyodik; circuit breaker beslenir
  meter(): []UsageRecord                  // son çağrıların usage/cost kayıtları
  configure(cfg: AdapterConfig): void     // timeout, retry, breaker, region, retention
}

type AdapterConfig {
  timeoutMs:        int
  retry:            { maxAttempts: int, baseDelayMs: int, jitter: bool }   // backoff + jitter
  circuitBreaker:   { failureThreshold: int, windowSec: int, cooldownSec: int }
  region:           Region                 // residency zorlaması (adapter düzeyi, NFR 10.7)
  dataRetention:    enum { NONE, EPHEMERAL, PROVIDER_DEFAULT }  // sağlayıcı tarafı saklama kontrolü
  noTrain:          bool                    // FR-LLM-012 default true (regüle/AB/UK zorunlu)
}
```

### 11.2 SttAdapter

```
interface SttAdapter extends Adapter {
  // Çift yönlü stream: audio chunk girer, partial/final transcript çıkar (no full buffering — FR-RES-002)
  stream(audioIn: AsyncStream<AudioChunk>, opts: SttOptions): AsyncStream<Transcript>
}

type SttOptions {
  language: string; sampleRate: int                 // 8kHz telefon (FR-RES-008)
  interimResults: bool                              // partial (FR-STT-001)
  phraseBoost: []string                             // alan terimleri: telefon no/plaka/poliçe (FR-STT-004/005)
  endpointing: { mode: enum {SERVER, CLIENT_VAD}, silenceMs: int }   // dinamik endpointing (FR-RTC-013, ADR-005)
}
type Transcript {
  text: string; isFinal: bool; confidence: number   // confidence (FR-STT-006)
  words: [{ w: string, startMs: int, endMs: int, confidence: number }]
  language: string?
}
```
- **Fallback (FR-STT-008):** Stream hata/timeout → secondary STT; mümkünse son N saniye audio yeniden gönderilir.
- **No-log:** Hassas içerik sağlayıcı loglarına yazılmaz; `dataRetention=NONE/EPHEMERAL` (FR-KB-010).

### 11.3 TtsAdapter

```
interface TtsAdapter extends Adapter {
  synthesize(textIn: AsyncStream<TextChunk>, voice: VoiceProfile, opts: TtsOptions): AsyncStream<AudioChunk>
  cancel(streamId: string): void                    // barge-in kesme ≤200ms (FR-TTS-005, FR-RTC-002, NFR 10.1)
}
type VoiceProfile {
  voiceId: string; language: string
  pronunciationDictId: string?                      // telaffuz sözlüğü (FR-TTS-004)
  rate: number?; pitch: number?; volume: number?    // konuşma hızı/ses (FR-RTC-008)
  clonedVoiceConsentRef: string?                    // ses klonlama izin kaydı (FR-TTS-006/007)
}
type TtsOptions { sampleRate: int; firstByteTargetMs: int }   // first-byte hızlı (SAD §20)
```
- **Fallback (FR-TTS-008/009):** Sağlayıcı düşerse alternatif TTS; tenant başına önceden tanımlı **eşdeğer
  ses** ile karakter tutarlılığı korunur. Dead-air önleme orchestrator tarafında (FR-RES-009).

### 11.4 LlmAdapter

```
interface LlmAdapter extends Adapter {
  // Stream token VEYA tool-call; schema-validated tool çağrısı zorunlu (FR-LLM-008)
  complete(req: LlmRequest): AsyncStream<LlmChunk>
}
type LlmRequest {
  messages: [{ role: enum {system, user, assistant, tool}, content: string }]
  tools: [ToolSchema]                               // JSON Schema tanımlı (FR-TOOL-002)
  model: string                                     // router seçer (FR-LLM-003); tenant override (FR-LLM-002)
  maxTokens: int; temperature: number
  noTrain: bool                                     // FR-LLM-012
}
type LlmChunk = TokenChunk | ToolCallChunk
type TokenChunk    { delta: string }
type ToolCallChunk { toolName: string, argumentsJson: string, callId: string }   // serbest metin değil
```
- **Tiering/cache orchestrator'da (SAD §9):** Router küçük/büyük model seçer; semantic cache LLM çağrısını
  atlayabilir (yan-etkisiz, PII'siz turlar). Adapter yalnız tek sağlayıcıyı temsil eder.
- **Fallback (FR-LLM-010):** Hata → fallback model veya deterministic flow. Model+versiyon+token UsageRecord'a
  yazılır (FR-LLM-011).
- **System prompt değişmezliği:** Adapter sözleşmesi system mesajını user/KB içeriğiyle değiştirmez (FR-LLM-006);
  enforcement Prompt Manager + Policy Engine'de.

### 11.5 TelephonyAdapter

```
interface TelephonyAdapter extends Adapter {
  dial(req: DialRequest): CallHandle                     // outbound (FR-TEL-002)
  answer(callId: string): MediaSession                   // inbound
  transfer(callId: string, target: TransferTarget, mode: enum {COLD, WARM, WHISPER}): void  // SIP REFER (FR-TEL-007)
  sendDtmf(callId: string, digits: string): void         // RFC 2833 / SIP INFO (FR-TEL-006)
  hangup(callId: string, reasonCode: string): void       // neden kodu (FR-TEL-012)
  mediaStream(callId: string): DuplexStream<AudioChunk>  // RTP/medya; SRTP (NFR 10.6)
  on(event: enum {ANSWERED, HANGUP, DTMF, AMD}, handler): void   // AMD: answering machine (FR-TEL-010)
}
type DialRequest { from: string, to: string, callerIdPool: string?, trunk: string? }   // E.164 (FR-TEL-004/005)
type TransferTarget { type: enum {QUEUE, SKILL, AGENT, NUMBER}, ref: string }           // FR-HND-003
```
- **Medya konumu:** edge vs merkez kararı ADR-009'a bağlı; SPI her iki topolojide aynı kalır.
- **Fallback:** Birincil telekom düşerse ikincil trunk/sağlayıcı (FR-TEL-002, ≥2 sağlayıcı).

### 11.6 Fallback ve hata taksonomisi sözleşmesi

Tüm adapter'lar sağlayıcı hatasını ortak `ErrorTaxonomy` enum'una çevirir (FR-TOOL-008, SAD §8.2). Routing
katmanı yalnız bu taksonomiye göre fallback kararı verir; sağlayıcıya özel kod yalnız audit/log'da kalır.

| `ErrorTaxonomy` | Anlam | `retriable` | Routing davranışı |
|-----------------|-------|-------------|-------------------|
| `TIMEOUT` | Süre aşımı | evet | retry (backoff+jitter) → secondary |
| `RATE_LIMITED` | Sağlayıcı 429 | evet | backoff → secondary |
| `UNAVAILABLE` | 5xx / bağlantı | evet | circuit-open → secondary |
| `AUTH` | Kimlik/yetki | hayır | alarm; secondary |
| `INVALID_REQUEST` | Geçersiz girdi | hayır | hata yüzeyle (fallback yok) |
| `CONTENT_FILTERED` | Sağlayıcı içerik reddi | hayır | policy/deterministic flow |
| `QUOTA_EXCEEDED` | Sağlayıcı kotası | hayır | secondary |
| `REGION_VIOLATION` | Residency ihlali | hayır | reddet (NFR 10.7) |

```
Primary adapter ──(TIMEOUT/UNAVAILABLE/RATE_LIMITED, circuit-open)──► Secondary adapter ──► Deterministic flow
```

- **Circuit breaker:** `failureThreshold`/`windowSec` aşılınca primary `OPEN`; `cooldownSec` sonra `HALF_OPEN`
  deneme. Health check breaker'ı besler.
- **Kabul kriteri:** Her kategoride birincil kesintide kontrollü fallback uçtan uca test edilir (BRD §19, 1-4).

---

## 12. Real-time / Data-plane Arayüzleri

Hot path REST **değildir** (FR-RES-002, stream-first). Sözleşmeler:

### 12.1 Telekom ↔ Media Gateway (medya WebSocket / RTP)
- Telekom sağlayıcı Media Streams/WebSocket çerçevesi: ikili (binary) audio frame (μ-law/PCM 8kHz) +
  kontrol mesajları (`start`, `media`, `dtmf`, `stop`). SRTP/TLS zorunlu (NFR 10.6). Adapter normalize eder.

### 12.2 Media Gateway ↔ Orchestrator (turn-event akışı)
SAD §6.1 turn state machine (LISTEN→CAPTURE→THINK→ACT→SPEAK) olay sözleşmesi (iç; gRPC stream / Kafka):

```
event TurnEvent {
  callId, tenantId, correlationId, turnId
  type: enum { TRANSCRIPT_PARTIAL, TRANSCRIPT_FINAL, BARGE_IN, LLM_TOKEN, TOOL_CALL, TTS_CHUNK, STATE_CHANGE }
  payload: ...                    // tipe göre
  tsMs: int
}
```
- `BARGE_IN` → TTS `cancel()` ≤200ms (FR-RTC-002, NFR 10.1). Her event `correlation_id` + `tenant_id` taşır.

### 12.3 Orchestrator ↔ Integration Gateway (tool-call sözleşmesi)
SAD §11.1 hattı: schema validation (in) → authorization → policy gate → idempotency → GW (timeout/retry/
breaker) → schema validation (out) + error normalization → audit. Tool I/O JSON Schema ile doğrulanır
(FR-TOOL-002); yalnız allowlist endpoint (FR-TOOL-012); idempotency key (FR-TOOL-009).

---

## 13. Yetkilendirme Eşlemesi (permission-key → endpoint)

Her endpoint OpenAPI'de `x-required-permission` extension taşır; backend guard bunu token rolü + scope ile
doğrular (SAD §14.4.2/3). Özet eşleme (tam liste OpenAPI dosyalarında):

| permission-key | Örnek endpoint(ler) | Panel | Rol(ler) |
|----------------|---------------------|-------|----------|
| `tenant:provision` | `POST /platform/v1/tenants` | L0 | `platform_owner` |
| `resource:quota:manage` | `PUT /platform/v1/tenants/{id}/quota` | L0 | `platform_owner`, `platform_sre` |
| `provider:routing:manage` | `PUT /platform/v1/providers/{id}/routing` | L0 | `platform_owner`, `platform_sre` |
| `role:assign` | `POST /admin/v1/role-assignments` | L1 | `tenant_owner`, `tenant_admin` |
| `apikey:manage` | `POST /admin/v1/api-keys` | L1 | `tenant_admin`, `api_developer` |
| `agent:version:manage` | `POST /ops/v1/agents/{id}/versions/{v}:promote` | L2 | `conversation_designer` |
| `calls:read` / `calls:read:own` | `GET /ops/v1/calls/{id}` | L2 | `operations_manager` / `human_agent` (sahiplik) |
| `transcript:read` | `GET /ops/v1/calls/{id}/transcript` | L2 | `qa_analyst`, `security_compliance_officer` |
| `campaign:manage` | `POST /ops/v1/campaigns` | L2 | `operations_manager` |

- **Scoped assignment (FR-IAM-011):** Guard, permission-key'e ek olarak assignment scope'unu (departman/
  marka/kampanya) kaynak attribute'larına karşı doğrular (ör. `operations_manager@brand=X` yalnız X).
- **`*:own`:** Kaynak sahipliği (çağrının atandığı temsilci) ile sınırlı (BRD §17.7).
- **Tenant scope:** Tüm L1/L2/S4 isteklerinde `tenant_id` token'dan türetilir + RLS ile çift kontrol (FR-TEN-002).

---

## 14. Versiyonlama, Deprecation ve Yaşam Döngüsü

- **SemVer (yüzey bazında):** Additive (yeni opsiyonel alan/endpoint) = minor, geriye dönük uyumlu. Breaking
  değişiklik = yeni major path (`/v2`) + eski sürüm en az **12 ay** desteklenir (public API).
- **Deprecation:** `Deprecation: true` + `Sunset: <tarih>` header'ları (RFC 8594); changelog + L1 panel
  bildirimi. Webhook payload'larında `api_version`.
- **İç SPI versiyonlama:** SPI değişiklikleri adapter `Capabilities.features` ile capability-negotiation;
  yeni feature opt-in. Orchestrator eksik feature'ı graceful degrade eder (ör. phrase_boost yoksa atlar).
- **Public ≠ internal:** L0/L1/L2 internal panel API'leri frontend ile birlikte evrilir (daha hızlı);
  yalnız Public Developer API (S4) sözleşme garantisi taşır.
- **Sözleşme testi:** OpenAPI + SPI sözleşmeleri CI'da provider/consumer contract test ile doğrulanır
  (breaking-change linter; SR-TST kapsamı).

---

## 15. İzlenebilirlik (FR/SR Eşlemesi)

Bu doküman BRD/SAD'den türer; tam FR↔SR↔TC↔WBS matrisi `docs/RTM.md`'dedir. API tasarım kararlarının ana izi:

| API kararı | İz (FR/NFR · SAD · WBS) |
|------------|--------------------------|
| Beş yüzeyli taxonomy + plane separation | SAD §4.2/§14.4.2, ADR-011 · 0.4.1 |
| L0 iş verisine erişmez; break-glass endpoint ailesi | FR-IAM-008/009/010 · 12.3 |
| Permission-key → endpoint guard (`x-required-permission`) | FR-IAM-001/011, ADR-012 · 12.2 |
| Tenant scope token'dan + RLS çift kontrol | FR-TEN-002 · 12.2.3, DB §6 |
| Idempotency-Key (yan etkili POST) | FR-TOOL-009 · 7.1.3 |
| Hata modeli RFC 9457 + ortak taksonomi (sızıntısız) | FR-TOOL-008 · 7.1.5, 4.1.5 |
| Adapter SPI (STT/TTS/LLM/Telephony) + ortak yetenekler | SAD §8.1/§8.2, ADR-001 · 4.1.1/4.1.2 |
| Fallback + circuit breaker + hata taksonomisi | SAD §8.3, FR-STT-008/FR-TTS-008/FR-LLM-010/FR-TEL-002 · 4.3 |
| Usage metering + cost (her adapter çağrısı) | FR-BIL-002, FR-LLM-011 · 4.1.3 |
| Residency adapter `region` + `Region` enum | NFR 10.7 · 4.1.4 |
| no-train / no-log endpoint kontrolü | FR-LLM-012, FR-KB-010 · 5.8, 6.2.4 |
| Outbound public API consent gate | FR-OUT-003/004/006/007, §14.3 · 10.2 |
| Webhook imzalama + retry + at-least-once | FR-TOOL-011, BRD §6.1 · 7.2.4 |
| Real-time turn-event + barge-in cancel ≤200ms | FR-RTC-002, NFR 10.1 · 2.2.7, 3.1.2 |
| Schema-validated tool call (serbest metin değil) | FR-LLM-008, FR-TOOL-002 · 5.6, 7.1.1 |

---

## 16. Açık Kararlar ve Sonraki Adımlar

**Açık kararlar (netleşince güncellenir):**
- Out-of-process adapter taşıması (gRPC/protobuf vs in-process Go interface) — ADR-003/PoC density sonucu (0.3.x).
- Medya işleme konumu (edge/merkez) telephony SPI'yi etkilemez ama deployment'ı belirler — **ADR-009**.
- Public API rate-limit/kota değerleri — tenant fiyat planı parametreleriyle (FR-BIL-004) birlikte.
- Webhook retry zaman çizelgesi ve max yaş — operasyonel ayar (P-09 runbook).
- gRPC mi REST mi (iç servisler arası) — control plane FastAPI; data plane iç akış SAD §6/§12.2.

**Sonraki adımlar (WBS):**
- **0.1.5** Threat model (STRIDE) bu API yüzeylerini ve auth realm'lerini girdi alır.
- **4.1.1** Adapter SPI implementasyonu (Go interface + ortak cross-cutting 4.1.2).
- **12.2.x** Panel AuthZ guard (`x-required-permission` enforcement) + 12.2.3 tenant scope/RLS.
- **7.x** Tool yürütme hattı + Integration Gateway (§12.3 sözleşmesi).
- OpenAPI YAML dosyalarının repo'da `api/` altında ayrıştırılması (commons + 4 yüzey) ve CI sözleşme testi.
- `.docx` artifact: `docs/build-docx.sh` ile bu doküman markalı çıktıya dönüştürülür (0.1.7).
