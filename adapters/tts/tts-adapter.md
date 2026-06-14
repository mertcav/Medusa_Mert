# TtsAdapter #1 + #2 — Streaming · Pronunciation Dictionary · Cancel (WBS 4.2.3)

> **Faz:** F1 · **Öncelik:** Must · **İz:** FR-TTS-001/002/004/005, FR-TTS-009/010, FR-RES-008/009 · NFR 10.1, SAD §8.1/§20
> Kaynak doğruluk: `docs/SAD.md` (§8.1/§8.2/§8.3/§20), `docs/API.md` (§11.1/§11.3/§11.6), `docs/BRD.md`
> (§9.7 FR-TTS, §15), `docs/vendor-eval/tts-eval.md` (0.2.3 ölçülen yüzey + kapı eşikleri). Çelişkide
> dokümanlar esastır.

## 1. Amaç ve mimari konum

Sağlayıcı Soyutlama Katmanı'nda (Adapters; BRD §16, SAD §8) **iki somut `TtsAdapter` implementasyonunu**
(≥2/kategori — ADR-002, FR-TTS-001) ortak SPI (SAD §8.1 / API §11.3) arkasına bağlar. Conversation
Orchestrator (Çekirdek IP, SAD §6; ADR-001) **yalnız** bu SPI'ye bağımlıdır — sağlayıcı değişimi
orchestrator'ı etkilemez. Adapter, turn state machine'in (SAD §6.1) **SPEAK** durumunda çalışır:

```
LLM token akışı → metin chunk akışı → synthesize(textIn, voice, opts) → AsyncStream<AudioChunk>
                                     → Media Gateway → RTP/SRTP → arayan
        barge-in (2.2.3/3.1.3 → BARGE_IN) → cancel(streamId) → SPEAK→CAPTURE
```

Görev başlığındaki **üç çekirdek boyut**:

1. **Streaming (P1, FR-TTS-002):** synthesize() ilk ses paketini **akış-önce** (stream-first; no full
   buffering — FR-RES-002) düşük gecikmeyle döndürür; ilk chunk **tüm sentez bitmeden** gelir
   (`full_buffered=0`). first-byte P95 ≤ **SAD §20 TTS kalemi** (200 ms; yeşil 100 ms).
2. **Pronunciation dictionary (P3, FR-TTS-004):** sayı/tarih/para/özel-isim **yapısal alanları**
   `VoiceProfile.pronunciationDictId` sözlüğüyle sentezlenir; hiçbir yapısal alan sözlüksüz kalmaz
   (`unhandled_structured=0`).
3. **Cancel (P2, FR-TTS-005/FR-RTC-002):** `cancel(streamId)` ile akış **anında** kesilir; cancel→susma
   P95 ≤ **200 ms** (NFR 10.1 / SAD §6.1) ve kesme **sonrası ses chunk'ı çıkmaz** (`chunk_after_cancel=0`
   — talk-over yok).

Ek (Must) boyutlar: ses karakteri tutarlılığı (P6 — FR-TTS-009), statik anons cache (P7 — FR-TTS-010),
8 kHz native + metering + hata normalizasyonu + no-log/residency (P8 — FR-RES-008/FR-BIL-002/FR-TOOL-008/
FR-KB-010/NFR 10.7).

## 2. Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| TTS **fallback anahtarlama** (sağlayıcı düşünce ikincile geçiş + ses tutarlılığı) | **4.3.2** (FR-TTS-008/009; bu motor ≥2 SPI-uyum + **eşdeğer-ses haritasının** varlığını doğrular) |
| Ortak adapter yetenekleri (timeout/retry/breaker/health/**connection pool**) | **4.1.2 / 4.1.6** (SAD §8.2; tüketilir) |
| Usage metering / cost **motoru** | **4.1.3** (bu motor UsageRecord **üretimini** doğrular) |
| Region selection / data retention **motoru** | **4.1.4** (NFR 10.7) |
| TTS **cache motoru** (statik anons deposu, hit ≥%80) | **16.1** (FR-RES-003; bu motor cache-hit **yolunu** destekler) |
| **Dead-air önleme** (filler / erken ses) | **orchestrator** (FR-RES-009; bu motor akış sürekliliğini **besler**) |
| **Barge-in olay** üretimi (VAD / turn-taking) | **2.2.3 / 3.1.3** (bu motor `BARGE_IN` olayını **tüketir** → `cancel()`) |
| Ses **klonlama izni** + kullanım kaydı | **4.2.6** (FR-TTS-006/007; bu motor `clonedVoiceConsentRef` alanını **taşır**) |
| Sağlayıcı **seçimi** | **0.2.6 / 0.3.x** (vendor-neutral, ADR-002) |
| Gerçek ses üretimi / MOS / telefoni ölçümü | adapter arkasında (motor sağlayıcı **gecikme profili** + akış modeli kullanır) |

Bu görev **yalnız** iki somut adapter'ın SPI-uyum **davranışını** (streaming/pronunciation/cancel) +
deterministik bir referans adapter üretir. `runtime/` ve `telephony/` ile aynı disiplin: **vendor-neutral**
(ADR-002), **credential-free**, **stdlib-only**, **deterministik** (olay-tetikli, sanal saat, random YOK;
gerçek TTS/ses üretimi yok — sağlayıcı gecikme profili + akış **modeli**).

## 3. SPI yüzeyi (SAD §8.1 / API §11.3)

```
synthesize(textIn: AsyncStream<TextChunk>, voice: VoiceProfile, opts: TtsOptions): AsyncStream<AudioChunk>
cancel(streamId: string): void                    // barge-in kesme ≤200ms (FR-TTS-005)
VoiceProfile { voiceId; language; pronunciationDictId?; rate?; pitch?; volume?; clonedVoiceConsentRef? }
TtsOptions  { sampleRate(=8000 — FR-RES-008); firstByteTargetMs (SAD §20) }
AudioChunk  { t_ms; dur_ms }                       // ilk chunk = first-byte; chunk akışı = süreklilik
```

Ortak `Adapter` (API §11.1): `capabilities()` / `health()` / `meter()` / `configure()` — yetenek
gerçeklemesi 4.1.x'te. Bir sağlayıcının portföye girmesi için `required_features =
{streaming, barge_in_cancel, pronunciation_dict}` + 8 kHz (`sample_rates ⊇ {8000}`) beyan etmesi gerekir (P5).

## 4. HARD kapılar (P1–P8) + katalog (P9/P10)

| Kapı | İnvariant | Metrik ölçütü |
|------|-----------|---------------|
| **P1** | Streaming first-byte | `first_byte_p95 ≤ 200 ms` + `full_buffered=0` (akış-önce; FR-TTS-002/SAD §20) |
| **P2** | Cancel (barge-in) | `cancel_p95 ≤ 200 ms` + `chunk_after_cancel=0` (FR-TTS-005/NFR 10.1) |
| **P3** | Pronunciation dictionary | `unhandled_structured=0` (FR-TTS-004) |
| **P4** | Akış sürekliliği / ölü hava | `underrun=0` (RTF<1; FR-RES-009) |
| **P5** | ≥2 SPI-uyumlu sağlayıcı | config'te ≥2 sağlayıcı + required_features + 8 kHz (FR-TTS-001/ADR-002) |
| **P6** | Ses karakteri tutarlılığı | `voice_inconsistent=0` + `voice_switch_unmapped=0` (FR-TTS-009) |
| **P7** | Cache (statik anons) | `cache_first_byte ≤ 30 ms` (FR-TTS-010) |
| **P8** | Metering+taksonomi+8kHz+no-log | UsageRecord/req + ErrorTaxonomy + 8 kHz + NONE/EPHEMERAL (FR-BIL-002/FR-TOOL-008/FR-RES-008/FR-KB-010) |

`P9` (komşu seam tüketimi) ve `P10` (ErrorTaxonomy / sır+ham-ses+PII yok) katalog invariant'ları
`validate` ile zorlanır. Eşikler **mühendislik varsayılanı** (0.2.3 tts-eval kapıları); gerçek değerler
**0.3.x canlı PoC**'ta telefoni (8 kHz, gürültü/aksan — 18.7 test seti) koşullarında doğrulanır.

## 5. Referans adapter modeli

`tts_adapter_probe.py` deterministik bir `TtsAdapterRuntime` sürücüsüdür: olay-akışını
(`request → (cancel?) → end`) işler. Her `request` için **sağlayıcı gecikme profilinden** (config
`providers`) streaming first-byte, akış sürekliliği (RTF/underrun), pronunciation dictionary uygulaması,
cancel→susma gecikmesi, cache-hit, ses tutarlılığı ve UsageRecord **deterministik** hesaplanır (random
YOK; sanal saat = `event.t`). Canlı sistemde Go/Rust async runtime (ADR-003, SAD §6.3/§8.1) + gerçek
`TtsAdapter` ile koşar.

```
validate   spec → P1–P10 + config sağlayıcı/profilleri (≥2 uyumlu sağlayıcı, gecikme bütçesi)
simulate   olay-akışı → streaming/pronunciation/cancel/cache/voice/metering → P1–P8 → çıkış kodu
selftest   iyi/kötü spec+sample negatif kapı kanıtı (izole degrade'ler P1/P2/P3/P4/P6/P8)
schema     beklenen spec şekli
```

İki somut sağlayıcı (illüstratif, vendor-neutral): `tts-stream-A` (bulut nöral) + `tts-stream-B`
(edge/on-prem). Her ikisi de tüm kapıları geçer → ADR-002 portföy gerekliliği (≥2 + fallback).

## 6. İzlenebilirlik

| Gereksinim | SR | TC | WBS |
|-----------|----|----|-----|
| FR-TTS-001 (≥2 sağlayıcı) | SR-TTS-001 | TC-TTS-001 | **4.2.3** (RTM'de eşli) |
| FR-TTS-004 (pronunciation dictionary) | SR-TTS-004 | TC-TTS-004 | **4.2.3** (RTM'de eşli) |
| FR-TTS-005 (barge-in cancel) | SR-TTS-005 | TC-TTS-005 | **4.2.3** (RTM'de eşli) |
| FR-TTS-002 (streaming first-byte — **uygulanır**) | SR-TTS-002 | TC-TTS-002 | RTM anchor **0.2.3**; bu adapter'da uygulanır |
| FR-TTS-009 (ses tutarlılığı — **sınır**) | — | — | 4.2.3 / **4.3.2** |
| FR-TTS-010 (statik anons cache — **sınır**) | — | — | 4.2.3 / **16.1** |

ADR-001 (bağımsız Orchestrator), ADR-002 (vendor-neutral + ≥2/kategori), ADR-003 (Go/Rust runtime).
Metrikler gözlemlenebilirliğe (0.4.7) yayılır; `tts_underrun_total` (ölü hava) ve `tts_barge_in_cancel_ms`
(>200ms) **alarm** sinyalleridir (FR-RES-009 / NFR 10.1 ihlali).
