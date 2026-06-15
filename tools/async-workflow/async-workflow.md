# 7.2.4 — Asenkron uzun-işlem workflow (callback/polling)

> **WBS:** 7.2.4 · **Faz:** F2 · **Öncelik:** Should · **İz:** FR-TOOL-011 → SR-TOOL-011 → TC-TOOL-011
> **Modül:** `tools/async-workflow/` · **Kaynak:** SAD §11.1/§11.2 · API §10.1/§10.2 · THREAT_MODEL SEC-05/TM-S-05

## 1. Amaç ve konum

Bazı kurumsal işlemler (ödeme mutabakatı, ERP iş emri, belge üretimi) saniyeler–dakikalar sürer.
Voice runtime orkestratörü **hot-path**'tir (NFR 10.1 P95 ≤1.2 sn; NFR 10.2 density) — bu süre boyunca
**bloklanamaz**. SAD §11.2: *"Uzun işlemler için asenkron workflow (FR-TOOL-011) → orkestratör beklemez,
sonuç callback/polling ile döner; bu sırada agent kullanıcıyı bilgilendirir."*

Bu modül FR-TOOL-011'i gerçekler. Tool Yürütme Hattında (SAD §11.1) konum:

```
… [5] Integration GW {7.1.4 timeout/retry/breaker} ─► connector.upstream_call(dispatch)  [7.2.1/7.2.2]
                                                       └─► 202 Accepted + job_ref
   ─► 7.2.4 dispatch() → PENDING execution + tool result='pending'  (HEMEN, NON-BLOCKING — W1)
      (orkestratör turn'e devam eder; agent: "işleminiz başlatıldı, sonucu birazdan bildireceğim")

   ··· OUT-OF-BAND (turn dışı) ···
   callback ingest (inbound webhook, HMAC doğrula)  ∨  poll step (bounded backoff)
   ─► terminal ─► tool.async.completed(result_ref) yayını  [+ aktifse orkestratöre bildirim]  ─► [7] audit
```

**Sınır:** dispatch transport'unun kendisi 7.2.1/7.2.2'dir; bu modül dispatch'in `AttemptOutcome`'unu
**tüketir** ve mutabakatı (reconciliation) yürütür. Dispatch'in timeout/retry/breaker'ı 7.1.4'tür.

## 2. Async execution durum makinesi (W2)

```
PENDING ─► RUNNING ─► SUCCEEDED   (terminal, immutable)
   │          ├─────► FAILED      (terminal, immutable)
   │          ├─────► TIMED_OUT   (terminal, immutable — deadline/poll tükenmesi)
   └──────────┴─────► CANCELLED   (terminal, immutable)
```

Terminal durumlar **immutable** — bir kez terminal olan execution durum değiştirmez. Bu, `tool_execution`
WORM (DB.md §6.5, 1.1.3) ile hizalı ve **exactly-once completion**'ın (W3) temelidir.

## 3. İki mutabakat modu

### 3.1 Callback (inbound webhook) — W4
Upstream iş bitince platformun callback endpoint'ine `POST` eder. Platform **doğrular** (SEC-05/TM-S-05,
API §10.1):
1. **HMAC-SHA256** imza: `X-Signature: t=<unix>,v1=<hmac(secret, t + "." + body)>` — secret yalnız `${ENV}`.
2. **Timestamp penceresi**: `|now − t| ≤ ts_tolerance_s` (default 300 sn) — geç/erken callback reddi.
3. **Nonce replay reddi**: daha önce görülen nonce → reddedilir.

Herhangi biri başarısız → `CALLBACK_REJECTED`; execution **değişmez**, `tool.async.completed` **yayılmaz**.
Ayrıca **tenant + correlation binding** (W7): callback yalnız eşleşen execution'ı mutabık kılar.

### 3.2 Polling — W5/W6
Callback desteklemeyen sistemler için. **Bounded**: `max_attempts` + exponential backoff (cap) + tohumlu
jitter. Upstream status terminal dönerse → tamamlanır; `max_attempts` tükenir **veya** `deadline_ms` aşılırsa
→ `TIMED_OUT` (`ASYNC_DEADLINE_EXCEEDED`). **Asla unbounded değildir** — zombie execution yok (W6).

### 3.3 Hybrid + yarış (race) — W3
Callback hızlı yol, polling güvenlik-ağı (at-least-once dayanıklılık, ADR-007). İlk terminal sinyal kazanır;
ikinci (çift callback / poll-sonrası-callback) **idempotent no-op** — ikinci `tool.async.completed` **yok**.

## 4. Sonuç referansla döner (W8)

`tool.async.completed` envelope (API §10.2) yalnız `{execution_id, status, result_ref}` taşır. Ham sonuç
payload'ı / PII **webhook'a ve audit'e girmez** — `result_ref` nesne deposu (1.1.6) pointer'ıdır; tenant
sistemi kendi yetkisiyle çeker (residency/no-log NFR 10.7; FR-REC-004).

## 5. Idempotency-key köprüsü (W9, FR-TOOL-009)

Async **write** dispatch `idempotency_key` taşır. 7.1.4 retry'i dispatch'i tekrar gönderirse
`(tenant_id, idempotency_key)` dedup → **aynı** execution; iki upstream iş yaratılmaz.

## 6. HARD invariant'lar (W1–W12)

| ID | Invariant |
|----|-----------|
| W1 | Non-blocking dispatch (SR-TOOL-011 çekirdeği; turn bloklanmaz) |
| W2 | Durum makinesi + terminal-immutable |
| W3 | Idempotent exactly-once completion (callback∧poll yarışı) |
| W4 | Callback authenticity: HMAC + ±300s + nonce replay (SEC-05) |
| W5 | Bounded polling (max_attempts + backoff + jitter) |
| W6 | Deadline/TTL reaper (zombie yok) |
| W7 | Tenant + correlation binding (FR-TEN-002) |
| W8 | Result-by-reference (ham payload/PII webhook'a/audit'e girmez) |
| W9 | Idempotency-key dedup (FR-TOOL-009; iki upstream iş yok) |
| W10 | fault_class hizalama (7.1.4 + ASYNC_DEADLINE_EXCEEDED/CALLBACK_REJECTED) |
| W11 | Audit no-log (düşük kardinalite; payload/PII/secret yok) |
| W12 | Determinizm (tohumlu sanal saat + jitter) |

## 7. Kapsam dışı (bilinçli)

dispatch transport → 7.2.1/7.2.2 · dispatch timeout/retry/breaker → 7.1.4 · endpoint allowlist → 7.2.3 ·
input/output schema → 7.1.1 · authz → 7.1.2 · idempotency key üretimi/store → 7.1.3 (bu modül key'i
**kullanır**) · müşteri hata metni → 7.1.5 (`CALLBACK_REJECTED`/`ASYNC_DEADLINE_EXCEEDED` → TEMPORARY/
CANNOT_COMPLETE) · correlation_id audit zenginleştirme → 7.1.6 · sonuç payload'ının nesne deposuna yazımı →
1.1.6 (bu modül `result_ref` **taşır**) · giden webhook abonelik/imza-anahtar rotasyonu → API §10.1/ileri WBS ·
kritik-işlem teyit/insan-onay workflow'u → 7.3 (BRD §13).

Vendor-neutral (ADR-001/002); sır/credential ve gerçek PII repoya yazılmaz (host'lar `example.com`; imza
fixture-secret yalnız runtime'da hesaplanır).
