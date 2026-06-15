# REST connector — tasarım (WBS 7.2.1)

> **Kaynak doğruluk:** `docs/BRD.md` (FR-TOOL-001), `docs/SAD.md` (§11.1/§11.2/§20). Çelişkide dokümanlar esastır.
> Bu modül **kaynak doğruluk** `rest-connector-spec.json`'dur; bu `.md` onu açıklar.

## 1. Amaç ve yerleşim

REST connector, **Integration Gateway**'in (SAD §11.2) REST/HTTP dilimidir ve `FR-TOOL-001` ("REST, SOAP,
GraphQL ve webhook entegrasyonları desteklenmelidir") gereksiniminin REST kısmını uygular.

Tool Yürütme Hattında (SAD §11.1) yeri **adım [5]'in altıdır** — 7.1.4 (timeout/retry/circuit breaker) bir SPI
noktası ilan etmişti:

```
LLM tool call ─► [1] input schema ─► [2] authz ─► [3] policy gate ─► [4] idempotency
              ─► [5] Integration GW { timeout + retry + breaker SARAR → upstream_call(req) }
                       │
                       └─► REST connector.upstream_call(req) ─► AttemptOutcome   ◄── BU MODÜL
              ─► [6] output schema + error normalization ─► [7] correlation_id audit
```

Yani çağrı zinciri: **7.1.4 gateway → (her deneme) → REST connector → AttemptOutcome → 7.1.4 kararı (retry/breaker)**.
Connector tek bir denemenin sonucunu üretir; **retry/breaker ORKESTRE ETMEZ** (C4 — o 7.1.4'ün işi).

Vendor-neutral (ADR-001/002): gerçek HTTP transport (keep-alive pool'lu client) bir **SPI noktasıdır**
(`upstream_call(req) → AttemptOutcome`). Referans probe wire'ı deterministik `wire_script` ile **modeller**
(gerçek ağ/credential YOK); canlıda **AYNI imza** arkasına gerçek HTTP client + connection pool (FR-RES-006) takılır.

## 2. Sorumluluk: ne yapar, ne yapmaz

**Yapar:**
1. Bildirimsel `RestConnectorSpec` + `RestInvocation`'tan **kanonik HTTP isteği kurar** (method · url · query · header · body; C1).
2. İsteği **vendor-neutral wire SPI** üzerinden yürütür (C12).
3. HTTP yanıtını **AttemptOutcome**'a eşler: **HTTP status → fault_class** (C2), **HTTP method → operation_class** (C3).
4. **Connection pooling** (FR-RES-006; C7): warm-reuse vs cold-connect.
5. **Bağlam taşır** (C8): `correlation_id` daima, `idempotency_key` varsa write'ta header olarak iletir (üretmez).
6. **Yapısal audit** üretir (no-log; C6).

**Yapmaz (kapsam dışı, bilinçli):**

| Sorumluluk | Sahip WBS | Köprü |
|---|---|---|
| timeout/retry/circuit breaker **orkestrasyonu** | 7.1.4 (FR-TOOL-003) | bu connector'ın AttemptOutcome'unu tüketir |
| endpoint allowlist (onaysız endpoint engelleme) | 7.2.3 (FR-TOOL-012) | connector kanonik `endpoint` üretir; gate karar verir |
| SOAP / GraphQL / webhook connector'lar | 7.2.2 | AYNI SPI, farklı protokol mapper |
| input/output JSON schema doğrulama | 7.1.1 (FR-TOOL-002) | connector doğrulanmış argümanı bağlar |
| tool authz / scope | 7.1.2 (FR-TOOL-004/005) | connector çağrıyı yetkili varsayar |
| idempotency key **üretimi**/store | 7.1.3 (FR-TOOL-009) | connector key'i **varsa iletir** |
| müşteriye dönen hata **metni** | 7.1.5 (FR-TOOL-008) | connector yalnız **fault_class** üretir |
| correlation_id audit/trace zenginleştirme | 7.1.6 (FR-TOOL-010) | connector yapısal audit kaydını sağlar |
| asenkron uzun-işlem (callback/polling) | 7.2.4 (FR-TOOL-011) | — |

## 3. SPI sözleşmesi

`upstream_call(invocation) → AttemptOutcome` (7.1.4 seam'iyle birebir uyumlu).

- **RestConnectorSpec** (bildirimsel): `{connector_id, base_url, auth{type,ref,header?,scheme?}, default_headers?,
  pool{max_per_host,keepalive_ms,connect_overhead_ms}, operations{<op>:{method,path,query?,body_template?,
  success_codes?,timeout_ms?,content_type?,accept?}}}`.
- **RestInvocation**: `{call_id, correlation_id, tenant_id, operation, path_params?, query_params?, body?,
  idempotency_key?, wire_script[]}`.
- **AttemptOutcome** (7.1.4 tüketir): `{result: ok|timeout|fault, latency_ms, fault_class?, status_code?,
  operation_class, endpoint, retryable, pooled, request_meta{method, header_names[], idempotency_forwarded}}`.
- **WireResponse** (referans): `{result: ok|status|timeout|conn_reset|conn_refused, status_code?, latency_ms?}`.

## 4. status → fault_class eşlemesi (C2; 7.1.4 ile hizalı)

| HTTP / wire | fault_class | sınıf | retryable |
|---|---|---|---|
| 2xx (∨ `success_codes`) | — (result=ok) | — | — |
| 408 Request Timeout | `TIMEOUT` | retryable | ✓ |
| 429 Too Many Requests | `RATE_LIMITED` | retryable | ✓ |
| 5xx | `UPSTREAM_5XX` | retryable | ✓ |
| 401 / 403 | `AUTH_FAILED` | terminal | ✗ |
| 404 | `NOT_FOUND` | terminal | ✗ |
| 422 | `SCHEMA_INVALID` | terminal | ✗ |
| diğer 4xx | `UPSTREAM_4XX` | terminal | ✗ |
| wire `timeout` | `TIMEOUT` | retryable | ✓ |
| wire `conn_reset` | `CONN_RESET` | retryable | ✓ |
| wire `conn_refused` | `CONN_REFUSED` | retryable | ✓ |

Her emitted `fault_class ∈ retryable ∪ terminal`; connector **gateway-üretimi** sınıfları (`CIRCUIT_OPEN`,
`RETRY_EXHAUSTED`) **asla üretmez** — onlar 7.1.4'e aittir. `operation_class`: GET/HEAD/OPTIONS → **read**;
POST/PUT/PATCH/DELETE → **write** (C3; 7.1.4 write-retry/idempotency köprüsü).

## 5. İnvariantlar (C1–C12)

| # | İnvariant |
|---|---|
| C1 | Bildirimsel deterministik istek kurulumu — aynı spec+invocation → birebir aynı kanonik istek. |
| C2 | HTTP status → fault_class TOPLAM eşleme, 7.1.4 fault_taxonomy ile hizalı. |
| C3 | HTTP method → operation_class (read/write); 7.1.4 write-retry / idempotency köprüsü. |
| C4 | AttemptOutcome SPI sözleşmesi; connector retry/breaker **orkestre etmez** (tek deneme). |
| C5 | Sır yalnız referansla (`${ENV}`/secret_ref); literal sır → reddedilir; değer asla loglanmaz. |
| C6 | Audit no-log — yalnız correlation_id+endpoint+method+status_code+fault_class+pooled. |
| C7 | Connection pooling (FR-RES-006) — scheme+host+port anahtarlı; warm-reuse vs cold-connect. |
| C8 | Bağlam taşıma — correlation_id daima; idempotency_key varsa write'ta header (üretmez). |
| C9 | Determinizm — sanal saat; Date.now/gerçek-rastgele YOK. |
| C10 | Enjeksiyon güvenli — CRLF/kontrol karakteri → `INJECTION_REJECTED`, istek gönderilmez. |
| C11 | Kanonik endpoint kimliği — interpolesiz path **template** (düşük kardinalite breaker anahtarı). |
| C12 | Vendor-neutral transport SPI — wire bir seam; mantık transport'tan bağımsız. |

## 6. Connection pooling (FR-RES-006; C7)

Havuz `scheme://host:port` ile anahtarlanır. İlk çağrı **cold**'dur (`pooled=false`, `+connect_overhead_ms`
TLS handshake gecikmesi). `keepalive_ms` içindeki ardışık çağrılar **warm**'dur (`pooled=true`, connect 0ms).
`max_per_host` eşzamanlı bağlantı tavanını verir. Bu, SAD §11.2'nin "connection pooling + kalıcı oturum ile
gecikme ve kaynak israfı azaltılır" hedefini gerçekler. Per-attempt **TIMEOUT** deadline: `connect + transfer >
timeout_ms` ise `TIMEOUT` fault + etkin gecikme deadline'da kesilir (hung yok).

## 7. Güvenlik

- **Sır yönetimi (C5):** `auth.ref` yalnız `${ENV}` placeholder; literal token spec doğrulamasında
  `LITERAL_SECRET_IN_SPEC` ile reddedilir. Çözülen değer audit'e/log'a sızmaz.
- **Audit no-log (C6):** yapısal kayıt ham URL query / body / header değeri / PII içermez (BRD §17.7, NFR 10.7).
- **Enjeksiyon (C10):** CRLF header injection / path traversal vektörleri istek kurulumunda reddedilir.
- **Düşük kardinalite (C11):** `endpoint` interpole değil → breaker keying (7.1.4) + gözlemlenebilirlik label
  politikası (0.4.7) stabil; müşteri/PII kimliği endpoint'e sızmaz.

## 8. Doğrulama

`rest_connector_probe.py`: `validate` (statik spec/config/şema + taksonomi hizalama + sır/PII tarama),
`call <sample>` (deterministik çağrı + C1–C12 kapısı), `selftest` (gömülü davranış), `schema` (sözleşme).
`tests/rest_connector_behavior_test.py` kara-kutu davranış sözleşmeleri. Tümü stdlib-only, credential-free,
deterministik. Canlı transport `run_live_test.sh` + `${REST_CONNECTOR_ENDPOINT}` ile (repoya yazılmaz).

## 9. İzlenebilirlik

FR-TOOL-001 · FR-RES-006 · FR-TOOL-009 (köprü) · FR-TST-008 · SR-TOOL-001 · TC-TOOL-001 ·
SAD §11.1/§11.2/§20 · ADR-001/002/003 · NFR 10.1 (latency soft) / 10.7 (residency/no-log) ·
tüketen: 7.1.4 · 7.2.3 · 7.1.5 · 7.1.6.
