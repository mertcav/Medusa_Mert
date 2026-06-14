# Kısa Süreli Diyalog Belleği + Oturum Sonu Kalıcılaştırma — `session-memory`

> **WBS 3.2.1** · `F1` · `Must` · →SAD §6.2 · FR-RES-010/FR-RES-016/FR-LLM-005/FR-REC-004/005
> Kaynak doğruluk: `docs/SAD.md` (§6.2 Session Memory, §6.3 eşzamanlılık, §12.1 depolar),
> `docs/BRD.md` (§8.1 çağrı özeti, §15 metrik, §16 Transcript/Recording varlıkları). Çelişkide
> dokümanlar esastır.

## 1. Amaç ve kapsam

SAD §6.2 (Alt Bileşenler) **Session Memory**'yi şöyle tanımlar:

> *"Kısa süreli diyalog belleği, özetleme — Token sınırına gelince özetler (FR-LLM-005); **bellekte
> tutar, oturum sonunda kalıcılaştırılır.**"*

Bu görev, Conversation Orchestrator oturum aktöründe (SAD §6.3) çalışan Session Memory bileşeninin
**iki çekirdek sorumluluğunun** sözleşmesini + deterministik bir referans simülatörü tanımlar:

1. **Kısa süreli diyalog belleği** — çağrı boyunca turn'leri **sınırlı** bir pencerede tutmak
   (append-only, monoton seq, idempotent); pencere/token tavanı aşılınca en eski turn'leri **özete
   katlamak** (fold) — düşürmeden.
2. **Oturum sonu kalıcılaştırma** — çağrı her bitişte konuşmayı **durable** depoya (PostgreSQL
   transcript) yazmak, sonra ephemeral çalışan kopyayı (Redis session_state) temizlemek.

**Kapsam (3.2.1):** oturum-içi bellek **modeli** + oturum-sonu **kalıcılaştırma** sözleşmesi.
**Kapsam dışı (komşu seam):**

| Konu | Nereye |
|------|--------|
| Token-sınırı **özetleme motoru** (LLM sıkıştırma, token sayımı, kalite) | **3.2.2** (FR-LLM-005/FR-RES-010) |
| Versiyonlu system prompt enjeksiyonu | **3.2.3** (FR-LLM-006) |
| Per-call bellek bütçe **izleme/sınırlama** | **3.1.4** (Session Memory `dialogue_memory` bileşenini **besler**) |
| Redis keyspace/TTL/`delete_on_call_end` | **1.1.5** (`cache/`) |
| `transcript`/`transcript_segment` şeması + RLS + partition | **1.1.3** (`db/`) |
| Nesne depo (recording) bucket/KMS/lifecycle | **1.1.6** (`objstore/`) |
| `call.completed`/transcript olay envelope | **1.1.8** (`eventstream/`) |
| PII redaction **L7 motoru** (kart/OTP gerçek redaksiyon) | **3.3.x** |
| correlation_id/tenant context propagation | **3.1.5** (`runtime/context-propagation/`) |

3.2.1 bu seam'leri **tüketir** (durable hedefler, ephemeral kaynak, redaction işareti), motorlarını
**uygulamaz**.

## 2. Mimari konum

```
        Conversation Orchestrator (oturum aktörü — SAD §6.3, asenkron task)
        ┌──────────────────────────────────────────────────────────────────┐
 STT ─► │ Turn Manager (3.1.x) ──turn──► SESSION MEMORY (3.2.1)             │
 final  │                                  │  • bounded pencere (append-only,│
        │                                  │    monoton seq, idempotent)     │
        │   Prompt Manager (3.2.3) ◄──oku──┤  • taşma → fold (→ summary)     │──► LLM (THINK)
        │                                  │  • dialogue_memory → 3.1.4 bütçe │
        │                                  ▼                                  │
        │                            Redis session_state / session_summary    │  (cache/ 1.1.5, ephemeral, pii)
        │                                  │  (her tur ayna; çalışan kopya)    │
        │   ── çağrı bitişi (end) ─────────┤                                  │
        │                                  ▼  OTURUM SONU KALICILAŞTIRMA       │
        │   transcript + transcript_segment (PostgreSQL db/ 1.1.3, RLS)        │  redaction_state='pending'
        │   + recording pointer (objstore/ 1.1.6) + call.completed (1.1.8)     │
        │                                  ▼  persist BAŞARILI →                │
        │                            session_state SİL (delete_on_call_end)     │
        └──────────────────────────────────────────────────────────────────┘
```

- Okuma (prompt kurulumu) **non-blocking** — sıcak yola gecikme eklemez (NFR 10.1).
- Çalışan kopya bellekte **küçük** tutulur (SAD §6.3 ~15MB hedefi); büyük ham ses Media Gateway/objstore'da.
- **Durable kalıcılaştırma her turda DEĞİL, oturum SONUNDA** yapılır — sıcak yolu korur (her tur
  PostgreSQL yazımı gecikme/density'yi bozar). Çalışan kopya Redis'te ayna olduğundan kaza/çökme
  durumunda TTL penceresi içinde kurtarılabilir.

## 3. Kısa süreli diyalog belleği modeli

Bir **turn** = `{turn_id, speaker∈{caller,agent,human}, seq (monoton), approx_tokens, t}`.

- **Append-only + monoton seq (M2):** turn'ler geliş sırasında eklenir; seq monoton artar. Zaman
  geriye giderse (`t < son_t`) `order_guard` reddeder (`out_of_order=0`).
- **Idempotent (M2):** aynı `turn_id` ikinci kez gelirse (edge retry / olay tekrarı) **tek kayıt**
  sayılır (`duplicate_turn` izlenir, pencereye eklenmez).
- **Sınırlı pencere (M1):** pencere `window_max_turns` turn'ü veya `token_soft_limit` yaklaşık token'ı
  aşamaz. Aşınca en eski turn'ler **özete katlanır** (fold). Bellek **asla sınırsız büyümez** —
  SAD §6.3 ~15MB hedefi + 3.1.4 per-call bütçesi.
- **Katlama kayıpsız (M9):** katlanan turn'ler `session_summary`'ye özetlenir (içerik korunur); **prompt
  bağlamı** küçülür (token tüketimi düşer, FR-RES-010) ama orijinal turn'ler **kalıcı kayda yine de tam
  yazılır** (M5). Özetleme **motoru** 3.2.2; burada yalnız seam + "fold içerik kaybetmez" invariant'ı.
- **Bütçe katkısı (M8):** `dialogue_memory` bileşeni 3.1.4 per-call bütçesini besler ve mitigable'dır
  (özetleme küçültür) — 3.1.4 WARN bandında bu bileşeni kırpar.

## 4. Oturum sonu kalıcılaştırma

Çağrı **dört bitiş durumundan** (`normal` / `transfer` / `error` / `abandon`) herhangi biriyle
sonlandığında:

1. **Durable yazım (M3/M5):** tüm yakalanan turn'ler (aktif pencere + katlanan özet) →
   - `transcript` (PostgreSQL, `tenant_id` RLS, `summary` BRD §8.1, `redaction_state='pending'`),
   - `transcript_segment[]` (her turn → `seq`/`speaker`/`confidence`; ham metin redaction hattına),
   - `recording` pointer (objstore/ 1.1.6, KMS, retention FR-REC-006),
   - `call.completed`/transcript olayı (eventstream/ 1.1.8).
   `persisted_turns == captured_turns` — **kayıp yok**.
2. **İdempotent + at-least-once (M5):** persist `idempotency_key` taşır (`call_id`+attempt). Durable
   depo geçici erişilemezse (`UNAVAILABLE`) backoff ile **retry** edilir; çift yazım `idempotency_key`
   ile dedupe → **tek transcript**.
3. **Temizlik (M4) — `persist_before_delete`:** durable persist **başarılı olduktan SONRA** Redis
   `session_state`+`session_summary` **açıkça silinir** (`delete_on_call_end`, cache/ 1.1.5). Persist
   **başarısızsa** anahtar **tutulur** (sliding TTL içinde retry/recovery — kaçak oturum güvenlik ağı
   hard cap 4 sa). **Önce-sil-sonra-yaz YASAK** (sessiz kayıp riski).

### Redaction sınırı (M6)

Çalışan bellek + `session_state` PII **içerebilir** (working memory, cache/ 1.1.5 `pii=true`). Ama
durable transcript:
- `redaction_state='pending'` ile yazılır → redaction hattı (FR-REC-004, L7 motoru 3.3.x),
- **kart/parola/OTP düz-metin** durable'a **hiç** yazılmaz (FR-REC-005;
  `sensitive_cleartext_persisted=0`).

## 5. HARD kapılar

| Kapı | İnvariant | Ölçüt |
|------|-----------|-------|
| **M1** | Sınırlı bellek | `unbounded_memory=0` + pencere-tepe ≤ `window_max_turns` (taşma katlanır) |
| **M2** | Sıra + idempotent | `out_of_order=0` + `duplicate_turn` dedupe (tek kayıt) |
| **M3** | Oturum-sonu persist | `unpersisted_on_end=0` + `persisted=true` + `persist_before_delete_ok=true` |
| **M4** | Ephemeral temizlik | `leaked_session_key=0` (durable sonrası session_state silinir) |
| **M5** | Kayıpsız | `dropped_turn=0` + `persisted_turns == captured_turns` |
| **M6** | Redaction sınırı | `sensitive_cleartext_persisted=0` + `redaction_state='pending'` |
| **M7** | Tenant izolasyon | `cross_tenant=0` (`{tenant,call}` anahtarı) |

## 6. Referans simülatör (`session_memory_probe.py`)

Vendor-neutral (ADR-002), stdlib-only, credential-free, **deterministik** (olay-tetikli, sanal saat,
random YOK). `validate` (spec → M1–M10 + config), `simulate <sample>` (olay-akışı → bellek penceresi +
katlama + persist + temizlik + HARD kapı → çıkış kodu), `selftest`, `schema`.

Canlı sistemde Conversation Orchestrator runtime'ı (Go/Rust async, ADR-003/SAD §6.3) aynı sözleşmeyi
gerçek Redis (`session_state`) + PostgreSQL (`transcript`) + S3 (`recording`) + Kafka (`call.completed`)
ile uygular; **kapı kodu değişmez**, profiller gerçek token-sayacı/context-window ile doldurulur.

## 7. İzlenebilirlik

- **FR-RES-010** (geçmiş özetleme + retrieval kısıtlama → token ↓) — katlama seam'i + dialogue_memory
  mitigable.
- **FR-RES-016** (çağrı-başı kaynak bütçesi) — sınırlı pencere → 3.1.4 bütçesini besler.
- **FR-LLM-005** (token-sınırı özetleme) — fold tetiği; motoru 3.2.2.
- **FR-REC-004/005** (transkript PII redaction + kart/OTP çıkarma) — durable `redaction_state='pending'`
  + düz-metin yasağı.
- **FR-REC-006** (saklama süresi) — recording retention pointer.
- **FR-TEN-002** (tenant izolasyon) — `{tenant,call}` anahtarı + RLS durable yazım.
- **FR-LLM-011** (model/versiyon çağrı-bazlı kayıt) + **BRD §8.1** (çağrı özeti) — transcript.summary.
- **SAD §6.2** (Session Memory), **§6.3** (eşzamanlılık), **§12.1** (depolar).
- **SR** eşlemesi: SR-RES-010 / SR-RES-016 / SR-LLM-005 / SR-TEN-002 (RTM'de zaten eşli → TC-*).
- **Komşu modüller:** `runtime/resource-budget/` (3.1.4), `runtime/turn-taking/` (3.1.3),
  `runtime/context-propagation/` (3.1.5); `cache/` (1.1.5), `db/` (1.1.3), `objstore/` (1.1.6),
  `eventstream/` (1.1.8); observability 0.4.7.
