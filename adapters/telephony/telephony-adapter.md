# Telephony Adapter #1 + #2 — SIP Trunk + BYOC (WBS 4.2.5)

> **Faz:** F1/F2 · **Öncelik:** Must · **İz:** FR-TEL-002 (+ FR-TEL-001/004/005/006/007/010/012,
> FR-RES-008, FR-BIL-002, FR-TOOL-008, FR-HND-003, FR-TEN-002, NFR 10.1/10.6/10.7) ·
> SAD §6/§6.1/§7.1/§7.2/§8.1/§8.3/§11.5/§12.1/§20 · ADR-001/002/003/005/009 · API §11.1/§11.5/§11.6
>
> **Kaynak doğruluk:** [`telephony-adapter-spec.json`](./telephony-adapter-spec.json). Çelişkide BRD/SAD/API esastır.

## 1. Amaç ve mimari konum

Bu görev, **Sağlayıcı Soyutlama Katmanı**'nda (Adapters; BRD §16, SAD §8) **iki somut `TelephonyAdapter`
implementasyonunu** (≥2/kategori — ADR-002, FR-TEL-002) ortak SPI (SAD §8.1 / API §11.5 `TelephonyAdapter`)
arkasına bağlar. **Conversation Orchestrator** (Çekirdek IP; SAD §6, ADR-001) yalnız bu SPI'ye bağımlıdır —
somut **taşıma modu** arkada değişir, orchestrator etkilenmez. **FR-TEL-002:** *SIP trunk ve BYOC (Bring
Your Own Carrier) bağlantısı desteklenmelidir* — iki taşıma modu tek SPI arkasında değiştirilebilir.

```
                       ┌──────── Conversation Orchestrator (Go/Rust, ADR-003) ────────┐
   PSTN / SIP          │  Turn state machine (SAD §6.1): LISTEN→CAPTURE→THINK→ACT→SPEAK │
      │  ▲             │                         ▲ medya (RTP/SRTP 8kHz)                │
      ▼  │ SBC (2.1.1) │                         │ on(ANSWERED/HANGUP/DTMF/AMD)         │
   ┌─────────────┐     │            ┌──── TelephonyAdapter SPI (API §11.5) ────┐        │
   │ Media GW    │◄───►│            │  dial · answer · transfer · sendDtmf      │        │
   │ (edge/      │     │            │  hangup · mediaStream · on(event)         │        │
   │  hibrit     │     │            └──────┬───────────────────────┬───────────┘        │
   │  ADR-009)   │     └───────────────────┼───────────────────────┼────────────────────┘
   └─────────────┘                ┌────────┴────────┐     ┌─────────┴────────┐
                                  │ tel-managed-A   │     │ tel-byoc-B       │  (≥2 sağlayıcı, ADR-002)
                                  │ managed CPaaS   │     │ BYOC SIP trunk   │
                                  │ (M1 / 2.1.3)    │     │ (M2 / 2.1.4)     │
                                  │ Media Streams WS│     │ ham SIP + RTP    │
                                  └─────────────────┘     └──────────────────┘
```

İki taşıma modu (**managed CPaaS** Media Streams WebSocket — SAD §7.2 M1 / 2.1.3; **BYOC SIP trunk** ham
SIP+RTP — SAD §7.2 M2 / 2.1.4) sağlayıcıya-özel SIP/SDP/medya biçimini adapter'da **tek normalize SPI
sözleşmesine** indirger; orchestrator M1/M2 farkını **görmez** (**P1**, ADR-001). Medya işleme konumu
(edge/merkez) deployment'ı belirler ama SPI'yi değiştirmez (**ADR-009** hibrit).

## 2. SPI yüzeyi (API §11.5)

```
interface TelephonyAdapter extends Adapter {
  dial(req: DialRequest): CallHandle                          // outbound (FR-TEL-001/002)
  answer(callId): MediaSession                                // inbound
  transfer(callId, target, mode∈{COLD,WARM,WHISPER})          // SIP REFER (FR-TEL-007)
  sendDtmf(callId, digits)                                    // RFC 2833 / SIP INFO (FR-TEL-006)
  hangup(callId, reasonCode)                                  // standart neden kodu (FR-TEL-012)
  mediaStream(callId): DuplexStream<AudioChunk>               // RTP/SRTP 8kHz (FR-RES-008/NFR 10.6)
  on(event∈{ANSWERED,HANGUP,DTMF,AMD}, handler)               // AMD telesekreter (FR-TEL-010)
}
type DialRequest    { from, to, callerIdPool?, trunk? }       // E.164 (FR-TEL-004/005)
type TransferTarget { type∈{QUEUE,SKILL,AGENT,NUMBER}, ref }  // (FR-HND-003)
```

Ortak `Adapter` yüzeyi (API §11.1): `capabilities()` / `health()` / `meter()` / `configure()` — yetenekler
4.1.x'te tüketilir. Bir sağlayıcının/trunk'ın portföye girmesi için `capabilities()`'te `features ⊇
{dtmf, amd, transfer}`, `transfer_modes ⊇ {COLD,WARM,WHISPER}`, `sample_rates ∋ 8000`,
`secure_transport=true` (SRTP/TLS) ve `directions ⊇ {inbound,outbound}` beyan etmesi gerekir (**P5**).

## 3. HARD kapılar + invariant'lar (P1–P10)

| # | İnvariant | Ölçüt (HARD) | İz |
|---|-----------|--------------|----|
| **P1** | Taşıma-nötr normalize | `contract_divergence=0` (managed/BYOC → tek SPI) | ADR-001, SAD §11.5 |
| **P2** | E.164 + caller-ID havuzu | `invalid_e164=0` + outbound `missing_caller_id_pool=0` | FR-TEL-004/005 |
| **P3** | Cold/warm/whisper transfer | `unsupported_transfer=0` (SIP REFER + hedef tipi) | FR-TEL-007, FR-HND-003 |
| **P4** | DTMF + AMD olayları | `dropped_event=0` (on(...) yüzeye çıkar) | FR-TEL-006/010 |
| **P5** | ≥2 SPI-uyumlu sağlayıcı/trunk | `min_providers=2` (managed + BYOC) | FR-TEL-002, ADR-002 |
| **P6** | Hangup standart neden kodu | `missing_reason_code=0` (taksonomi 2.1.7) | FR-TEL-012 |
| **P7** | Medya 8kHz + SRTP + kurulum | `non_8khz=0` + `insecure_media=0` + `setup_p95 ≤ 2000 ms` | FR-RES-008, NFR 10.6, SAD §20 |
| **P8** | Metering + residency + taksonomi | UsageRecord/çağrı (SECONDS) + `region_violation=0` + ErrorTaxonomy | FR-BIL-002, NFR 10.7, FR-TOOL-008 |
| **P9** | Komşu seam tüketimi | aşağıdaki seam'leri **uygulamaz**, tüketir | §5 |
| **P10** | ErrorTaxonomy + sır/ham-PII yok | SIP/Q.850 → API §11.6; ham numara/medya/PII yok | API §11.6, BRD §14 |

> **Kurulum gecikmesi (P7)** SAD §20'nin **medya transport** bütçesinden (tek-yön ≤100 ms — 0.2.1)
> **ayrıdır**: bu çağrı-kontrol **kurulum / post-dial delay** kalemidir. Eşik (P95 ≤ 2000 ms; yeşil
> 1000 ms) **mühendislik varsayılanı**; gerçek değerler 0.3.x canlı PoC + gerçek trunk'ta doğrulanır.

## 4. Çağrı kontrol modeli (deterministik)

`telephony_adapter_probe.py`'deki referans `TelephonyAdapterRuntime` çağrı-kontrol olay akışını işler
(olay-tetikli, sanal saat, **random YOK**; gerçek SIP/RTP yığını yok — sağlayıcı kurulum gecikme profili):

```
dial | answer  →  (media_ready | dtmf | amd | transfer)*  →  hangup
```

Her olay için: taşıma-nötr normalize (P1), E.164/caller-ID uygunluğu (P2), transfer mode/hedef (P3),
DTMF/AMD olay yüzeye çıkışı (P4), hangup neden kodu (P6), medya 8kHz+SRTP+kurulum gecikmesi (P7),
residency + UsageRecord (SECONDS) + hata normalizasyonu (P8) DETERMİNİSTİK hesaplanır. Out-of-order /
cross-tenant / geçersiz olay **reddedilir** (P10).

## 5. Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| SBC (SIP güvenlik / topoloji gizleme / DDoS) | **2.1.1** |
| Managed CPaaS medya çerçeve sözleşmesi (M1) | **2.1.3** (tüketilir) |
| BYOC SIP/SDP/RTP sözleşmesi (M2) | **2.1.4** (tüketilir) |
| E.164 normalize + caller-ID havuz **motoru** | **2.1.5** (bu adapter biçim **uygunluğunu** + havuz referansını doğrular) |
| DTMF detect/generate **motoru** | **2.1.6** (bu adapter olayı yüzeye çıkarır) |
| Çağrı neden kodu **taksonomisi** | **2.1.7** (hangup neden kodu buradan; eşleme tüketilir) |
| Kontrollü retry / geri-arama | **2.1.8** (FR-TEL-009) |
| AMD **motoru** (telesekreter sınıflandırma) | **2.1.9** (bu adapter AMD **olayını** yüzeye çıkarır) |
| RTP medya termination / jitter buffer | **2.2.1** |
| Codec yönetimi / 8kHz | **2.2.2** |
| Edge VAD / endpointing / barge-in | **2.2.3** (ADR-005) |
| İnsan aktarımı / handoff akışı (özet/bağlam) | **8.x** (FR-HND-004) |
| Outbound consent / arama-saati / DNC | **10.2** (FR-TEL-013/014, FR-OUT-*) |
| Telefoni fallback **anahtarlama** | **4.3.x** (FR-TEL-002; bu adapter ≥2 SPI-uyum + ErrorTaxonomy **varlığını** doğrular) |
| Ortak yetenekler (timeout/retry/breaker/health/pool) | **4.1.2 / 4.1.6** (SAD §8.2; tüketilir) |
| Usage metering / cost **motoru** | **4.1.3** (UsageRecord **üretimi** doğrulanır) |
| Region / retention **motoru** | **4.1.4** (NFR 10.7) |
| Telekom / sağlayıcı **seçimi** | **0.2.1 / 0.2.6 / 0.3.x** (vendor-neutral, ADR-002) |

## 6. İzlenebilirlik

`telephony_call_setup_ms` (→ observability `call_setup_ms`) · `telephony_active_calls` ·
`telephony_transfer_total` · `telephony_dtmf_total` · `telephony_amd_total` ·
`telephony_call_seconds_total` (→ `call_seconds_total`) · `telephony_hangup_total{reason_code}`
→ BRD §15 → 0.4.7. `provider_id`/`trunk`/`mode`/`reason_code` **düşük** kardinalite (label uygun);
`call_id`/`correlation_id` **yüksek** kardinalite → yalnız trace/exemplar (0.4.7 label_policy, 3.1.5).
Ham telefon numarası / çağrı içeriği / PII metriklerde **yok**.

```
İz: FR-TEL-002 → SR-TEL-002 → TC-TEL-002 (RTM'de WBS=4.2.5/2.1.4 eşli) + FR-TEL-004/005 (numbering 2.1.5),
FR-TEL-006 (DTMF 2.1.6), FR-TEL-007 (transfer; handoff 8.x), FR-TEL-010 (AMD 2.1.9), FR-TEL-012 (neden
kodu 2.1.7) — bu adapter'da SPI-uyum davranışı uygulanır. SRS/RTM değişikliği gerekmedi.
```
