# Codec Yönetimi (8kHz) + Gereksiz Resample/Transcode Önleme — Tasarım (WBS 2.2.2)

> Kaynak doğruluk: **`codec-spec.json`** (makine-okunur). Bu doküman tasarımı/gerekçeyi anlatır.
> Çelişkide **BRD/SAD** esastır. İz: **FR-RES-008** → SR-RES-008 (A) → TC-RES-008.
> Vendor-neutral (ADR-002), credential-free, stdlib-only. Ham ses payload'ı / PII / transkript repoya yazılmaz.

## 1. Mimari konum

Real-time **Media Gateway** (SAD §6 mimari, §7.1 medya akışı, L2 katmanı) içinde codec yönetimi,
telefoni edge ile Conversation Orchestrator/STT-TTS arasındadır. 2.1.3 (managed CPaaS / M1) ve 2.1.4
(ham SIP RTP / M2) **taşıma + normalize**, 2.2.1 **RTP sonlandırma + jitter buffer** (codec-agnostik,
payload'a dokunmaz) sözleşmelerini kurdu; bu dilim zincirdeki **FORMAT (codec/örnekleme) yönetimini**
birinci-sınıf, deterministik bir sözleşmeye çevirir.

```
PSTN ─SIP/RTP─► SBC ─► SIP App Server ─► [Media Gateway: CODEC pazarlık + zincir format yönetimi] ─► STT (2.2.5)
                (2.1.1) (2.1.2)           └─ 2.2.2 (bu dilim): 8kHz native, ≤1 kontrollü resample seam
                                          RTP terminate/jitter (2.2.1, codec-agnostik) · VAD (2.2.3)
                              egress ◄── [aynı codec disiplini] ◄── Streaming TTS (2.2.6)
```

**FR-RES-008:** "Telefoni codec ve örnekleme (8 kHz) zincirinde gereksiz resampling/transcoding
önlenmelidir." **SAD §7.2:** "Telefoni 8 kHz (G.711/Opus narrowband). Gereksiz resampling/transcoding
zincirden çıkarılır. STT/TTS adapter'ları mümkünse 8 kHz native çalışır; değilse **tek bir kontrollü
resample noktası**." Bu dilim bu iki cümleyi ölçülebilir bir kapıya dönüştürür.

## 2. Codec kataloğu (C1)

Vendor-neutral katalog (`codec_catalog.codecs`). Her codec iki ortogonal boyut taşır:

| Codec | encoding | rate_hz | telephony 8kHz dar bant |
|-------|----------|---------|--------------------------|
| `PCMU` (G.711 µ-law) | g711u | 8000 | ✓ |
| `PCMA` (G.711 A-law) | g711a | 8000 | ✓ |
| `OPUS_NB` (Opus narrowband) | opus | 8000 | ✓ |
| `OPUS_WB` (Opus wideband) | opus | 16000 | — |
| `L16_8K` (linear PCM) | l16 | 8000 | — |
| `L16_16K` (linear PCM) | l16 | 16000 | — |

İki format birimi → iki dönüşüm türü:
- **transcode** = `encoding` farkı (decode + re-encode; ör. PCMU↔PCMA, g711↔opus, g711↔l16).
- **resample** = `rate_hz` farkı (örnekleme oranı dönüşümü; ör. 8000↔16000).

Bir sınır ikisini birden değiştirebilir (ör. `PCMU`@8k → `L16_16K`@16k = transcode **ve** resample).

## 3. Codec pazarlığı (C2 — SDP offer/answer benzeri)

`negotiate(offer, answer)` (RFC 3264 ruhu): `offer` uzak uç (telefoni) tercih sıralı codec listesi,
`answer` bizim desteklediklerimiz. Seçim:

```
common = [c for c in offer if c in answer]            # offer tercih sırasıyla
if not common: → UNAVAILABLE (media kurulamaz)
narrowband = [c in common if rate(c) == 8000]
return narrowband[0] if narrowband else common[0]     # NARROWBAND-FIRST
```

**Neden narrowband-first:** ortak bir 8kHz dar bant codec varsa onu seçmek wire'ı 8kHz tutar ve
downstream'de **resample ihtiyacını sıfırlar**. Uzak uç `OPUS_WB` (16kHz) sunsa bile, ortak bir
8kHz codec (G.711) varsa o seçilir — gereksiz 16kHz→8kHz resample baştan engellenir. Bu, gereksiz
dönüşümü **kaynağında** (pazarlıkta) önlemenin birinci hattıdır.

## 4. Zincir analizi + minimal-DP (C3/C4 — gereksiz dönüşümün tanımı)

Medya zinciri ordered stage dizisidir; her stage bir **working codec** (stage'den çıkan format) ve
bir **native** kümesi (dönüşümsüz işleyebildiği codec'ler) taşır. Sınır (i→i+1) codec farkı = dönüşüm.

**Gereksiz** dönüşümü tanımlamak için "aynı uçlarla en az kaç dönüşüm zorunluydu?" sorusunu yanıtlarız:

```
allowed[i] = {working_codec}            # uç stage'ler (telefoni wire / terminal adaptör) PINNED
           = native[i]                  # iç stage'ler native kümesinden serbest
minimal_X  = DP ile allowed üzerinde min sınır-dönüşüm (X ∈ {any, resample, transcode})
unnecessary_X = actual_X − minimal_X    # ≥ 0;  0 ise israf yok
```

DP, uçları sabit tutup iç stage'lere en az format değişimi yaptıran atamayı bulur (klasik en-az-değişim
yol problemi). **Gereksiz dönüşüm = gerçek zincirin optimumdan fazlası.** Bu, yöntem **A (analiz)**
ile SR-RES-008'i doğrular: optimumla aynıysa zincirde gereksiz dönüşüm yoktur.

**Örnek:** uçlar `PCMU`@8k (PSTN) ve `L16_16K`@16k (yalnız-16kHz STT). Minimal: encoding bir kez
g711→l16 (1 transcode) + rate bir kez 8k→16k (1 resample) = kaçınılmaz **tek seam**. Gerçek zincir de
1+1 yaparsa gereksiz 0 → geçer (`codec-single-resample-stt16k`).

## 5. Tek kontrollü resample noktası (C5) + U-dönüşü (C6)

- **C5:** SAD §7.2 "tek bir kontrollü resample noktası" → `resample_points ≤ 1` (yön başına). STT/TTS
  16kHz isterse resample **yalnız o adaptör seam'inde** yapılır; başka yerde rate oynanmaz.
- **C6 (U-dönüşü):** bir örnekleme/encoding ayrılıp **tekrar girilirse** (rate `8k→16k→8k`, encoding
  `µ→A→µ`) bu tanım gereği israftır — `unnecessary > 0` zaten yakalar, ama U-dönüşü açık ve okunur
  bir teşhis sinyalidir (rate/encoding dizisinde ardışık-tekrar collapse sonrası bir değerin >1 kez
  görünmesi). `codec-double-resample` (rate U) ve `codec-redundant-transcode` (encoding U) bunu gösterir.

## 6. Kapı seti (HARD)

| Kapı | Ölçüt | İz |
|------|-------|-----|
| **C1** | wire codec 8kHz dar bant (telephony, rate=8000) | FR-RES-008, SAD §7.2 |
| **C2** | pazarlık conversion-minimizing (narrowband-first passthrough) | FR-RES-008, RFC 3264 |
| **C3** | `unnecessary_transcodes == 0` | FR-RES-008, SR-RES-008 |
| **C4** | `unnecessary_resamples == 0` | FR-RES-008, SR-RES-008 |
| **C5** | `resample_points ≤ 1` | SAD §7.2 |
| **C6** | rate + encoding U-dönüşü yok | FR-RES-008 |

## 7. Metrikler → gözlemlenebilirlik (C10)

Her oturum codec metriğini ve dönüşüm sayaçlarını 0.4.7 omurgasına yayar:

| Metrik | BRD §15 | Observability |
|--------|---------|----------------|
| `active_codec` | codec | `voice_codec_info` (gauge, `codec` label) |
| `resample_points`, `transcode_hops`, `unnecessary_resamples`, `unnecessary_transcodes`, `conversions` | — | dahili dönüşüm sayaçları (regresyon/degrade sinyali) |

`codec` **düşük-kardinalite enum** olduğundan metrik label'ı uygundur (0.4.7 `metric_labels_allowed`
içinde). Yüksek-kardinalite kimlik (`call_id`) metrik label'ı **olmaz** (yalnız trace/exemplar). Ham
payload metriklerde yer almaz.

## 8. Dayanıklılık, residency, PII

- **Residency (C12):** codec dönüşümü home-region'da yapılır; bölge uyumsuzluğu `REGION_VIOLATION`
  (NFR 10.7). ADR-009 hibrit: ağır medya/codec işleme ayrı bölgesel katmanda.
- **Hata taksonomisi (C11):** desteklenmeyen codec → `INVALID_REQUEST`; ortak codec yok →
  `UNAVAILABLE`; non-native stage → `INVALID_REQUEST`; bölge → `REGION_VIOLATION` (API §11.6).
  Gereksiz dönüşüm bir **hata değil**, kapı elemesi + degrade sinyalidir.
- **PII (C13):** ses payload'ı kişisel veridir; spec/config/örneklerde **ham payload veya transkript
  tutulmaz**; codec yalnız format metadata'sı (`encoding`/`rate`/`payload_type`) taşır. Codec yöneticisi
  içeriği yorumlamaz (yalnız format); içerik downstream STT'ye akar.

## 9. Kapsam ayrımı (bilinçli)

| Konu | Nerede |
|------|--------|
| RTP sonlandırma + jitter buffer (codec-agnostik) | **2.2.1** (bu dilime payload akıtır) |
| Edge VAD / endpointing (dinamik) | **2.2.3** |
| Gürültü/echo + agent kendi sesini transkribe etmeme | **2.2.4** |
| Streaming STT connector (8kHz native tüketimi) | **2.2.5** (downstream) |
| Streaming TTS + ölü hava (8kHz native üretim) | **2.2.6** (egress kaynağı) |
| Taşıma/normalize (managed WS / ham SIP RTP) | **2.1.3 / 2.1.4** |
| STT/TTS sağlayıcı 8kHz native yeteneği ölçümü | **vendor-eval 0.2.2 (C8) / 0.2.3 (C8)** |
| Native medya/codec yığını (C/C++/Rust, libopus, G.711) | **SAD §21**, F1 canlı kod |

Canlı sistemde aynı sözleşme native Media Gateway'de (SAD §21) gerçek codec yığını (G.711/libopus,
SDP pazarlık) ile doldurulur; bu dilim sözleşmeyi + deterministik analiz kapısını sağlar.
