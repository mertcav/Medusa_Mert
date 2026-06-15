# Integration GW — Timeout / Retry / Circuit Breaker (WBS 7.1.4)

> **Kaynak doğruluk:** `integration-gw-spec.json` (makine-okunur) + bu tasarım notu.
> Çelişkide `docs/BRD.md` / `docs/SAD.md` esastır. Bu motor SAD §11.1 adım **[5]**'i uygular.
>
> **İz:** FR-TOOL-003 (Must) · SR-TOOL-003 · TC-TOOL-003 · SAD §11.1/§11.2/§8.3 · ADR-001/002/003

## 1. Kapsam

Tool Yürütme Hattının (SAD §11.1) **dayanıklılık (resilience)** aşaması. Bir upstream bağımlılığına
(REST/SOAP/GraphQL/webhook — FR-TOOL-001) giden tek bir tool çağrısını üç kontrolle sarar:

```
LLM tool call ─► [1] input schema ─► [2] authz ─► [3] policy gate ─► [4] idempotency
              ─► [5] Integration GW: TIMEOUT + RETRY + CIRCUIT BREAKER   ◄── bu motor
              ─► [6] output schema + error normalization ─► [7] correlation_id audit
```

**INVARIANT (SR-TOOL-003 kabul ölçütü):** *"Bağımlılık hatasında devre açılır; **kontrolsüz retry yok**."*

### Kapsam dışı (bilinçli sınır)
| Konu | Sahip | Not |
|------|-------|-----|
| Input/output JSON schema doğrulama | 7.1.1 (FR-TOOL-002) | Bu motor doğrulanmış çağrıyı alır |
| Tool authz / agent scope | 7.1.2 (FR-TOOL-004/005) | — |
| Idempotency key üretimi/store | 7.1.3 (FR-TOOL-009) | Bu motor key'in **varlığını** tüketir, üretmez |
| Müşteriye dönen hata **metni** | 7.1.5 (FR-TOOL-008) | Burada yalnız yapısal `fault_class` |
| correlation_id audit/trace zenginleştirme | 7.1.6 (FR-TOOL-010) | Bu motor no-log audit kaydı bırakır |
| Endpoint allowlist | FR-TOOL-012 | — |
| Asenkron uzun-işlem workflow | FR-TOOL-011 | — |

## 2. Mimari yerleşim

- **Düzlem:** voice-runtime (orchestrator **Tool Executor**, ACT durumu — SAD §6.1). Araç çağrıları
  çoğu turda yoktur (THINK→SPEAK); ACT yalnız tool gerektiğinde çalışır → hot-path ama seyrek.
- **Non-blocking (ADR-003):** timeout bir async deadline; breaker OPEN fail-fast bloklamaz.
- **Vendor-neutral (ADR-001/002):** gerçek HTTP/SOAP/GraphQL transport bir **SPI noktasıdır**
  (`upstream_call(req) → AttemptOutcome`). Referans probe upstream'i deterministik `attempts_script`
  ile **modeller** (gerçek ağ/credential yok); canlıda aynı imza arkasına gerçek transport +
  **connection pool** (FR-RES-006) takılır. Timeout/retry/breaker mantığı transport'tan bağımsızdır.
- **Gecikme:** retry + backoff toplam tur gecikmesine katkı yapar → SAD §20 **tool overhead** bütçe
  kalemi (P95 ≤100ms) bağlamında **SOFT**; HARD kapı 0.3.2 `latency-budget`'tedir.

## 3. Timeout (R1)

Her deneme bir `timeout_ms` deadline'ına tabidir. Bir denemenin ölçülen gecikmesi deadline'ı aşarsa
(`result=="timeout"` **veya** `latency_ms > timeout_ms`) → **TIMEOUT** fault üretilir ve etkin gecikme
deadline'da **kesilir** (hung / sonsuz bekleme yok). TIMEOUT **retryable** bir faulttur. Bu, SAD §8.3
adapter timeout→fallback deseninin tool-tarafı karşılığıdır.

## 4. Retry — bounded, backoff + jitter (R2/R3/R4/R5)

- **Sınırlı (R2):** upstream denemeleri `≤ max_attempts` (ilk deneme dahil). Yapılandırılan tavanı
  **asla** aşmaz — *"kontrolsüz retry yok"*.
- **Yalnız retryable (R4):** sadece **geçici (transient)** fault'lar yeniden denenir. **Terminal**
  fault'lar (4xx client error, schema invalid, auth, not-found) tekrarda da başarısız olur + kaynak
  israfı yapar → **retry edilmez** (`attempts==1`).
- **Backoff (R3):** `min(max_backoff_ms, base_backoff_ms × multiplier^(deneme-1))`. **Jitter** thundering-herd'i
  kırar: `full` → `[0, backoff]`, `equal` → `[backoff/2, backoff]`, `none` → `backoff`. Jitter **tohumlu
  PRNG**'den (determinizm, R10).
- **Write güvenliği (R5, FR-TOOL-009 köprüsü):** `operation_class=="write"` ve
  `retry_writes_require_idempotency` ise yazma **yalnız** `idempotency_key` varsa yeniden denenir —
  aksi tek deneme (idempotent olmayan yazmanın retry'ı **duplicate yan-etki** riski taşır; idempotency
  store 7.1.3'tedir). Read her zaman retry-uygundur.
- Başarı kalan denemeleri kısa-keser. Call-içinde breaker OPEN olursa retry durur (fail-fast).

## 5. Circuit breaker — per-endpoint (R6/R7/R8/R9)

Her **endpoint** (bağımlılık) için ayrı bir devre kesici tutulur. Gözlem granülaritesi **per-call**
(gateway çağrısının nihai başarı/başarısızlığı breaker penceresine yazılır; call-içi retry'lar
`max_attempts` ile ayrı sınırlıdır).

```
        ┌─────────┐  ardışık hata ≥ failure_threshold                ┌──────┐
        │ CLOSED  │  VEYA pencere dolu ∧ hata oranı ≥ rate_threshold │ OPEN │
        │ (normal)│ ───────────────────────────────────────────────►│(fail-│
        └─────────┘                                                  │ fast)│
             ▲                                                       └──┬───┘
             │ probe başarı ≥ half_open_success_to_close                │ cooldown_ms doldu
             │                          ┌───────────┐                   ▼
             └──────────────────────────│ HALF_OPEN │◄──── ilk probe ───┘
               probe hatası → OPEN      │  (probe)  │
                                        └───────────┘
```

- **Trip (R6):** `ardışık_hata ≥ failure_threshold` **veya** (`pencere ≥ min_calls` ∧
  `hata_oranı ≥ rate_threshold`) → CLOSED→OPEN. *"Bağımlılık hatasında devre açılır."*
- **OPEN fail-fast (R7):** `opened_at + cooldown_ms`'e kadar çağrılar upstream'e **değmeden**
  `CIRCUIT_OPEN` ile kısa-devre edilir (`attempts==0`, `status=short_circuited`). Bağımlılığa yük
  bindirmez, hızlı başarısız olur (fallback'e — SAD §8.3 — hızlı geçiş).
- **Kurtarma (R8):** cooldown sonrası ilk çağrı OPEN→HALF_OPEN geçişidir (probe). `half_open_max_probes`
  kadar probe'a izin verilir; başarı `half_open_success_to_close`'a ulaşınca CLOSED; herhangi probe
  hatası → tekrar OPEN (cooldown yeniden).
- **İzolasyon (R9, bulkhead):** breaker endpoint-başına olduğundan bir bağımlılığın açık devresi
  sağlıklı başka bir bağımlılığı kısa-devre **etmez**.

## 6. Fault taksonomisi (R12)

| Sınıf | Üyeler | Davranış |
|-------|--------|----------|
| **retryable** (geçici) | TIMEOUT, UPSTREAM_5XX, CONN_RESET, CONN_REFUSED, RATE_LIMITED, DEADLINE_EXCEEDED | backoff ile retry |
| **terminal** (kalıcı) | UPSTREAM_4XX, SCHEMA_INVALID, AUTH_FAILED, NOT_FOUND | retry yok |
| **gateway** (motor üretir) | CIRCUIT_OPEN, RETRY_EXHAUSTED | kısa-devre / tükenmiş retry |

Müşteriye dönen **metin** burada üretilmez (7.1.5 / FR-TOOL-008); burada yalnız yapısal sınıf.

## 7. Determinizm, audit, hata (R10/R11)

- **Determinizm (R10):** jitter tohumlu `random.Random(seed)`'den; `Date.now`/gerçek-rastgele yok →
  aynı `seed` + girdi → birebir aynı sonuç (CI tekrarlanabilirliği, FR-TST-008).
- **Audit no-log (R11):** çağrı başına yapısal kayıt `correlation_id + endpoint + operation_class +
  status + fault_class + attempts + breaker geçişleri` taşır; **ham payload/secret/PII yok**
  (7.1.6 audit'e köprü; BRD §17.7).
- **Girdi/config hataları:** `MISSING_POLICY_CONFIG`, `INVALID_POLICY`, `INVALID_CALL_INPUT`,
  `NON_MONOTONIC_CLOCK`, `INTERNAL_ERROR` (fault_class'tan ayrı yapısal hata sınıfları).

## 8. Doğrulama (`integration_gw_probe.py`)

| Komut | İş |
|-------|----|
| `validate` | Statik spec/config/şema kapısı + sır/PII taraması + her sample kapısı → çıkış kodu |
| `run <sample>` | Deterministik resilience simülasyonu; çağrı dizisi → R1–R12 kapısı → çıkış kodu |
| `selftest` | 28 gömülü davranış kontrolü → çıkış kodu |
| `schema` | SPI/CallResult/karar sözleşmesini yazdır |

**Kapı sonucu:** `selftest` 28/28 🟢 · `validate` 🟢 · `tests/` 13/13 🟢 · 9 sample 🟢.

## 9. İzlenebilirlik

| Gereksinim | Karşılanış |
|-----------|------------|
| FR-TOOL-003 (timeout/retry/circuit breaker) | R1 (timeout) · R2/R3/R4 (bounded retry+backoff+jitter) · R6/R7/R8/R9 (breaker) |
| SR-TOOL-003 ("devre açılır; kontrolsüz retry yok") | R6 (devre açılır) · R2 (bounded) · R4 (yalnız retryable) |
| FR-TOOL-009 (duplicate önleme — write retry güvenliği) | R5 (write yalnız idempotency_key ile retry) |
| FR-RES-006 (connection pooling) | Transport SPI canlıda pool ile (referans modellemez) |
| FR-TOOL-010 (correlation_id izleme) | R11 audit kaydı (zenginleştirme 7.1.6) |
| SAD §8.3 (fallback) | breaker OPEN/timeout → secondary/deterministic flow tetiği |
| FR-TST-008 (sentetik test) | seed'li deterministik fixture'lar; gerçek PII yok |
