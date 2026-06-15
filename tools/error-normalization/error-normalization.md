# WBS 7.1.5 — Hata Normalizasyonu (müşteriye teknik detay yok)

> `F1` · `Must` · →FR-TOOL-008 · SAD §11.1 adım [6] · API §4.3/§5/§11.6
> Kaynak doğruluk: `error-normalization-spec.json`. Çelişkide BRD/SAD/API esastır.

## 1. Amaç ve kapsam

Tool Yürütme Hattının (SAD §11.1) **sunum** aşaması. Önceki adımda (7.1.4 Integration GW)
üretilen **yapısal `fault_class`** — ya da bir adapter'ın API §11.6 `ErrorTaxonomy` hatası — bu
motorda **iki disjonkt yüzeye** ayrılır:

```
                                  ┌─► customer  (MÜŞTERİ/arayan)  — güvenli, teknik-detaysız
fault_class ──► [normalize] ──────┤      • voice: doğal konuşma (TTS) · api: RFC 9457 Problem
 (7.1.4 ∪ API §11.6)              │
                                  └─► audit    (yalnız LOG)       — ham teknik detay (provider kodu,
                                         stack, endpoint, internal mesaj) — MÜŞTERİYE GİTMEZ
```

**Çekirdek invariant (SR-TOOL-008 / FR-TOOL-008):** *"Müşteriye dönen mesajda stack/teknik detay
yok."* Müşteri-görünür metin (voice mesajı + RFC 9457 `title`/`detail`) provider adı, stack izi,
SQL, dosya yolu, iç URL/host, IP, ham kod veya PII **içermez** — bağımsız bir **sızıntı
tarayıcısıyla doğrulanır** (N1).

**Bu motorun sahibi olduğu tek şey müşteriye dönen metindir.** 7.1.4 yalnız yapısal `fault_class`
üretir; müşteri metni üretmez (kasıtlı kapsam ayrımı).

### Kapsam dışı (bilinçli)
| Konu | Sahip |
|------|-------|
| timeout/retry/circuit breaker (fault_class üretimi) | 7.1.4 (FR-TOOL-003) — bu motor fault_class'ı **tüketir** |
| output schema doğrulama (adım [6]'nın diğer yarısı) | 7.1.1 (FR-TOOL-002) |
| tool authorization | 7.1.2 (FR-TOOL-004/005) |
| idempotency | 7.1.3 (FR-TOOL-009) |
| correlation_id audit/trace zenginleştirme + audit deposunda PII redaction (FR-REC-004) | 7.1.6 (FR-TOOL-010) — bu motor audit kaydını **üretir**, kalıcılaştırmaz |
| insan aktarımı orkestrasyonu | FR-HND — bu motor yalnız `suggest_handoff` **önerir** |

## 2. Müşteri kategorileri (ham fault'ları daraltma)

Onlarca ham `fault_class`, müşterinin ihtiyaç duymadığı teknik ayrımı gizleyerek **küçük** bir
güvenli kümeye daraltılır:

| Kategori | code | HTTP (RFC 9457) | retriable_hint | suggest_handoff | severity |
|----------|------|------|------|------|------|
| `TEMPORARY` | `TOOL_TEMPORARY` | 503 | ✔ | ✔ | warn |
| `BUSY` | `TOOL_BUSY` | 429 | ✔ | ✔ | warn |
| `CANNOT_COMPLETE` | `TOOL_FAILED` | 502 | ✘ | ✔ | warn |
| `NOT_FOUND` | `RECORD_NOT_FOUND` | 404 | ✘ | ✘ | info |
| `NOT_PERMITTED` | `NOT_PERMITTED` | 403 | ✘ | ✔ | high |
| `UNKNOWN` | `UNEXPECTED` | 500 | ✘ | ✔ | high |

### fault_class → kategori (toplam eşleme, N2)
İki girdi yüzeyi kabul edilir: **(1)** 7.1.4 `fault_taxonomy` (retryable∪terminal∪gateway) ve
**(2)** API §11.6 `ErrorTaxonomy` (adapter). **Güvenlik kararı:** `AUTH`/`AUTH_FAILED`,
`REGION_VIOLATION`, `CONTENT_FILTERED` → **jenerik** kategoriye düşürülür; nedeni (kimlik
doğrulama, residency, içerik filtresi) müşteriye **açılmaz** (sızıntı önleme). Bilinmeyen/yeni bir
`fault_class` → güvenli `UNKNOWN` (asla ham passthrough).

- retryable/temporary → `TEMPORARY`; `RATE_LIMITED`/`QUOTA_EXCEEDED` → `BUSY`
- `UPSTREAM_4XX`/`SCHEMA_INVALID`/`INVALID_REQUEST`/`CONTENT_FILTERED`/`INTERNAL_ERROR` → `CANNOT_COMPLETE`
- `NOT_FOUND` → `NOT_FOUND`; `AUTH*`/`REGION_VIOLATION` → `NOT_PERMITTED`

## 3. İki yüzey

### 3.1 Müşteri (voice + api)
- **voice:** Arayana TTS ile okunan **doğal** cümle (locale: tr-TR / en-US). **Rakam veya iç-yapı
  terimi içermez** (N10) — arayan "503", "circuit breaker", "attempt 3" duymaz.
- **api:** Public Developer API hata yanıtı — **RFC 9457 `application/problem+json`** (API §4.3):
  `type` (dokümantasyon URI), `title`, `status`, `detail` (jenerik), `code`, `correlation_id`.

Mesajlar **statik katalog şablonlarıdır** (`config/error-catalog.json`). İstek girdisi (ham mesaj,
PII, provider kodu) müşteri metnine **enterpole edilmez** (N7) → reflected-PII / mesaj enjeksiyonu
imkânsız.

### 3.2 Audit (yalnız log)
`customer_safe=false` işaretli yapısal kayıt: `correlation_id`, `fault_class`, `category`,
`severity`, `provider_code` (ham), `internal_message` (ham; **kart/OTP maskeli — FR-REC-005**),
`endpoint`, `tenant_id`, `operation_class`. Müşteri yüzeyi ile **disjonkt** (N4). 7.1.6 bu kaydı
trace'e bağlar ve audit deposunda ek FR-REC-004 redaction uygular.

## 4. Sızıntı tarayıcısı (N1/N10 — güvenliğin kalbi)

Müşteri-görünür metni yasak desen sınıflarına karşı tarar; **hit=0 zorunlu**:

| Sınıf | Örnek yakalanan |
|-------|------|
| `vendor_name` | twilio, telnyx, openai, postgres, redis, … (kelime-sınırı) |
| `stack_trace` | `Traceback`, `at com.foo.Bar(`, `File.py:42` |
| `exception_class` | `NullPointerException`, `ValueError` (CamelCase yapışık) |
| `sql_fragment` | `SELECT … FROM` (BÜYÜK harf — lowercase İngilizce yanlış-pozitifi yok) |
| `file_path` | `/var/log/…`, `C:\`, `main.go` |
| `internal_url_host` | `https://`, `*.internal`, `*.svc` |
| `ip_address` | `10.20.30.40` |
| `raw_code_hex_uuid` | `0x…`, UUID, uzun hex |
| `pii_email` / `pii_card` / `pii_phone` | sentetik PII |
| **voice ek (N10):** `digit`, `internal_structure_term` | rakam; circuit/breaker/upstream/attempt/gateway/… |

**RFC 9457 `type` (URI) ve `correlation_id` yapısal alanlardır** — taranmaz (müşteriye okunan
serbest metin değil; kendi `errors.rmcvoice.io` dokümantasyon alanımız).

### Tenant özel mesaj (override) — fail-safe
Conversation-designer / tenant özel hata metni sağlayabilir. Bu metin de **taranır**: temizse
kullanılır; **kirliyse reddedilip güvenli kataloğa düşülür** (`override_rejected=true`). Böylece
FR-TOOL-008 garantisi özel metinlerde de korunur. (`failsafe=false` yalnız regresyon/`degraded`
testinde tarayıcının gerçek bir kapı olduğunu kanıtlamak için kullanılır → N1 eler.)

## 5. Invariant'lar (N1–N12)

`error-normalization-spec.json › invariants`. Özet: **N1** sızıntı=0 · **N2** toplam fault eşleme
(bilinmeyen→UNKNOWN) · **N3** toplam yerelleştirme (eksik locale→default) · **N4** ham izolasyon ·
**N5** RFC 9457 uyumu · **N6** correlation_id köprü (audit+api; voice'a gömülmez) · **N7**
enterpolasyon yok · **N8** retriability tutarlı · **N9** determinizm · **N10** voice iç-yapı/rakam
sızıntısı yok · **N11** sır/PII literal yok (kart/OTP audit'te de maskeli) · **N12** audit eksiksiz.

## 6. İzlenebilirlik

| Gereksinim | Karşılanma |
|------------|-----------|
| FR-TOOL-008 | Müşteri yüzeyi teknik-detaysız (N1/N10); ham detay audit'te (N4) |
| SR-TOOL-008 | "Müşteriye dönen mesajda stack/teknik detay yok" → N1 sızıntı kapısı + behavior T1–T4 |
| SAD §11.1 [6] | Hata normalizasyonu (output schema yarısı 7.1.1) |
| API §4.3/§5 | RFC 9457 Problem (N5) |
| API §11.6 | `ErrorTaxonomy` ikinci girdi yüzeyi (`AdapterError.providerCode` yalnız audit) |
| FR-REC-005 | Kart/OTP audit `internal_message`'ta da maskeli |
| FR-TOOL-010 → 7.1.6 | `customer_safe=false` audit kaydı (N12) trace girdisi |
| FR-HND | `suggest_handoff` önerisi |
| ADR-001/002 | Sunum katmanı, vendor-neutral katalog, transport'tan bağımsız |

## 7. Doğrulama

```bash
python3 error_normalization_probe.py validate      # statik spec/config/katalog/şema kapısı
python3 error_normalization_probe.py selftest      # gömülü davranış (N1–N12)
python3 error_normalization_probe.py normalize samples/<x>.json
python3 tests/leak_behavior_test.py                # sızıntı tarayıcısı + müşteri/audit ayrımı
./run_live_test.sh                                 # hepsi (saf eşleme → canlı bağımlılık gerekmez)
```

Sonuç: **validate 🟢 · selftest 25/25 🟢 · behavior 38/38 🟢 · 7 sample 🟢 + degraded 🔴 (beklenen)**.
