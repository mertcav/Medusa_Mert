# Çağrı Düşmesinde Kontrollü Retry / Geri Arama (WBS 2.1.8)

> **İz:** FR-TEL-009 · SR-TEL-009 · FR-OUT-005 (maks. deneme + aralık) · FR-OUT-003 (consent) ·
> FR-TEL-013/FR-OUT-004 (arama saatleri) · FR-TEL-014/FR-OUT-006 (DNC/opt-out) ·
> FR-RES-014/FR-OUT-007 (kapasite/backpressure) · SR-TOOL-003 (backoff+jitter, kontrolsüz retry yok) ·
> DB.md §5.4 (`campaign.max_attempts`/`retry_interval_minutes`, `contact.attempts`/`do_not_call`, `consent`) ·
> SAD §15 (backpressure) / §18 (graceful drop + callback) · 2.1.7 reason-codes (`retryable`, `outbound_callback`).
> **Kaynak doğruluk:** `retry-callback-spec.json`. Bu belge tasarımı/gerekçeyi açıklar.

## 1. Amaç ve mimari konum

FR-TEL-009 bir çağrı düştüğünde (veya temas kurulamadığında) **kontrollü retry veya geri arama**
oluşturmayı ister. "Kontrollü" kelimesi bu dilimin tüm gerekçesidir: retry/callback **sınırlı**
(maks. deneme tavanı), **uyumlu** (DNC/consent/saat yeniden kontrol), **idempotent** (çift zamanlama
yok) ve **backoff+jitter**'li (retry fırtınası yok) olmalıdır — yani SR-TOOL-003'ün "kontrolsüz
retry yok" ilkesi telefoni düzlemine taşınır.

Bu dilim bir **karar motorudur**: bir çağrı bittiğinde 2.1.7'nin ürettiği kanonik kod + nitelikler
(`retryable`) ile contact'ın uyum/sayaç durumunu ve kapasite sinyalini alır, deterministik bir
**eylem** üretir.

```
  [reason-codes 2.1.7]            [retry-callback (bu dilim)]              [tüketici]
  end_reason + retryable ─┐
  contact.attempts/DNC/   ├─ uyum kapıları (DNC→consent→retryable→max→  ─→ action:
   consent/utc_offset      │   capacity) → uygunluk sınıfı (dropped/        retry   → dialer hemen çevirir
  capacity.available ──────┘   no_contact/capacity) → backoff+jitter +      callback→ geri arama kuyruğu (API §11.5)
                               arama-saati pencere → scheduled_at           suppress→ hiç arama yok (DNC/consent/tavan)
                                                                            no_action→ retry'a uygun değil
```

Bu **medya düzlemi değildir** (RTP/codec → 2.2.x), **numaralandırma değildir** (E.164/Caller ID →
2.1.5), **taksonomi değildir** (neden kodu → 2.1.7). Çağrı yaşam-döngüsünün **"sonra ne olacak"**
karar düzlemidir.

## 2. Karar akışı

Sıra önemlidir — **uyum kapıları her zaman zamanlamadan önce** (compliance-by-design):

1. **G1 — DNC / opt-out** (`do_not_call=true`) → `suppress`/`dnc_suppressed`. Kalıcı engel; retryable
   kod olsa bile asla zamanlanmaz (FR-TEL-014/FR-OUT-006, **C5**).
2. **G2 — Consent** (`consent_state != granted`) → `suppress`/`consent_withdrawn`. Yalnız `granted`
   yeniden aranabilir (FR-OUT-003, **C6**).
3. **G3 — Retryable** (2.1.7 `retryable=false`) → `no_action`/`non_retryable`. Normal kapanış,
   transfer, kalıcı red (rejected/no_route/auth) retry üretmez (2.1.7 R8, **C1**).
4. **G4 — Maks. deneme** (`attempts >= max_attempts`) → `suppress`/`max_attempts_exhausted`. Sert
   tavan; runaway yok (FR-OUT-005, **C2**).
5. **Uygunluk sınıfı** (dropped / no_contact / capacity) belirlenir (**C13**).
6. **G5 — Kapasite** (`capacity.available=false` veya `capacity` sınıfı) → `callback`/`capacity_deferred`.
   Backpressure'da retry fırtınası yerine kontrollü erteleme (FR-RES-014/FR-OUT-007, **C8**).
7. Aksi halde `retry` (mode=retry) / `callback` (mode=callback); **backoff + jitter** hesaplanır,
   **arama-saati penceresi** uygulanır (pencere dışıysa `rescheduled_calling_hours`, **C7**).

Her zamanlanan eylem `start_reason="outbound_callback"` taşır (**C9**) — böylece ortaya çıkan çağrı
2.1.7 ile yeniden sınıflanabilir; `idempotency_key` deterministiktir (**C10**) → aynı istek çift
zamanlama üretmez.

## 3. Uygunluk sınıfları (2.1.7'yi tüketir)

`retryable=true` olan 2.1.7 bitiş kodları üç sınıfa eşlenir (kaynak doğruluk yine 2.1.7'nin
`retryable` bayrağıdır; probe **C1/C13** ile çapraz-doğrular — boşluk = kapı eler):

| Sınıf | 2.1.7 kodları | Davranış | İz |
|---|---|---|---|
| `dropped` | `dropped_mid_call` | FR-TEL-009 **çekirdek** — bağlı çağrı düştü; `drop_grace` ile kısa kontrollü yeniden bağlanma | FR-TEL-009 |
| `no_contact` | `no_answer`, `busy`, `voicemail_machine_detected`, `timeout`, `network_failure`, `provider_unavailable`, `media_failure`, `rate_limited`, `agent_error` | Temas/teknik geçici hata — backoff ile yeniden dene | FR-OUT-008 |
| `capacity` | `abandoned_no_capacity`, `blocked_capacity`, `blocked_time_window` | Kapasite/pencere — callback kuyruğuna / sonraki pencereye | FR-TEL-015, FR-RES-014 |

## 4. Backoff, jitter, sınır (kontrol garantileri)

- **max_attempts (C2)** — FR-OUT-005 sert tavanı. `attempts >= max` → suppress. `simulate` komutu
  bir contact'ı tükenene kadar koşturup tavanın **asla aşılmadığını** gösterir (sonsuz retry yok).
- **Backoff (C3)** — `fixed` veya `exponential` (`base × multiplier^(n-1)`), **`max_interval_seconds`
  ile sınırlı**; deneme arttıkça monotonik ↑. `dropped` sınıfı `drop_grace_seconds` kısa lütuf
  gecikmesi alır (hızlı yeniden bağlanma ama yine sınırlı).
- **Jitter (C4)** — `idempotency_key`'den **deterministik** türetilir, `[0, jitter_cap_seconds]`
  aralığında, `jitter_cap > 0`. Eşzamanlı retry'ları desenkronize eder (thundering herd önleme).
  Cüzdan-saati rastlantısı yok → tekrarlanabilir.
- **Arama saati (C7)** — `scheduled_at` izinli pencere dışındaysa sonraki pencere açılışına
  ileri-sarılır (düşürülmez). `utc_offset_minutes` ile yerel saat (tam tz canlı adaptörde).

## 5. Değişmezler (invariants C1–C14)
`retry-callback-spec.json#invariants` kaynak doğruluğudur. Özet:
- **C1** — yalnız 2.1.7 `retryable=true` kodları retry/callback üretir; aksi `no_action`.
- **C2** — `attempt_number ≤ max_attempts`; tavanda suppress (runaway yok).
- **C3** — backoff monotonik + `max_interval` ile sınırlı; strateji ∈ {fixed, exponential}.
- **C4** — jitter deterministik (anahtardan), `[0, cap]`, `cap > 0`.
- **C5/C6** — DNC + consent **zamanlamadan önce** suppress (compliance-by-design).
- **C7** — pencere dışı aday ileri-sarılır (rescheduled), düşürülmez.
- **C8** — backpressure → kontrollü callback ertelemesi, retry fırtınası değil.
- **C9** — zamanlanan eylem `outbound_callback` taşır (2.1.7 linki).
- **C10** — `idempotency_key` deterministik; aynı istek → aynı karar (çift zamanlama yok).
- **C11** — karar/log PII içermez (numara/transkript yok; `contact_id` referansı); residency pin.
- **C12** — `reason_code` 2.1.7'de var + `retryable` taksonomiyle eşleşir (uyuşmazlık → kapı eler).
- **C13** — `dropped_mid_call` retry-uygun + `no_contact`'tan ayrı; 2.1.7 retryable kodları tam kapsanır.
- **C14** — config ≥2 politika; sonlu tavan/aralık + jitter_cap>0; literal sır yok.

## 6. Gözlemlenebilirlik / analitik bağlama
`decision_reason` düşük-kardinalite, PII'siz kanonik etikettir → metrik label'ı/OLAP boyutu olmaya
uygundur (0.4.7; OLAP 1.1.9 A4 `none`). Retry oranı, suppress dağılımı (dnc/consent/max), callback
kuyruk derinliği ve `rescheduled_calling_hours` payı bu kararlardan türetilir. `outbound_callback`
ile başlayan çağrılar 2.1.7 üzerinden tekrar sınıflanır → kapalı geri bildirim döngüsü.

## 7. Kapsam ayrımı (bilinçli)
- Retry/callback **planlama/scheduler altyapısı** (kalıcı kuyruk, zamanlayıcı, dialer tetikleme) →
  F1 voice runtime + 3.x orchestrator (burada yalnız **karar + zamanlama hesabı**).
- AMD **algoritması** + voicemail bırakma → 2.1.9 (burada yalnız `voicemail_machine_detected` sınıfı).
- Consent/DNC/saat **kayıt & zorlama** kaynağı → DB.md §5.4 + FR-TEL-013/014 dilimleri (burada bu
  durumlar **girdi** olarak okunur ve kapı uygulanır).
- Kapasite/backpressure **mekanizması** → FR-RES-014 dilimi + 0.4.8 yük testi (burada yalnız sinyal).
- Neden kodu taksonomisi → 2.1.7; numara/Caller ID → 2.1.5; medya/SIP/RTP → 2.1.3/2.1.4.
- Canlı dialer/scheduler doğrulaması → F1 gerçek telefoni adaptörü + 0.4.7 omurgası.

Vendor-neutral (ADR-002); credential-free; stdlib-only; deterministik (sanal saat + tohumlu jitter).
Numara/PII/sır repoya yazılmaz.
