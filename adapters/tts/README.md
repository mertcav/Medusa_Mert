# adapters/tts — WBS 4.2.3 TTS adapter #1 + #2 (streaming, pronunciation dictionary, cancel)

Sağlayıcı Soyutlama Katmanı'nda (Adapters; BRD §16, SAD §8) **iki somut `TtsAdapter` implementasyonunu**
(≥2/kategori — ADR-002, FR-TTS-001) ortak SPI (SAD §8.1 / API §11.3) arkasına bağlar. Orchestrator
(Çekirdek IP, SAD §6; ADR-001) **yalnız** bu SPI'ye bağımlıdır; sağlayıcı arkada değişir. Turn state
machine'in (SAD §6.1) **SPEAK** durumunda çalışır: `synthesize(textIn, voice, opts) → AsyncStream<AudioChunk>`
+ `cancel(streamId)`.

## Görev başlığındaki üç boyut

1. **Streaming** — ilk ses paketi akış-önce (no full buffering — FR-RES-002) düşük gecikmeyle; first-byte
   P95 ≤ SAD §20 (200 ms) + `full_buffered=0` (**P1**, FR-TTS-002).
2. **Pronunciation dictionary** — sayı/tarih/para/isim yapısal alanları `pronunciationDictId` ile;
   `unhandled_structured=0` (**P3**, FR-TTS-004).
3. **Cancel (barge-in)** — `cancel(streamId)` → akış anında kesilir; cancel→susma P95 ≤ 200 ms + kesme
   sonrası ses yok (**P2**, FR-TTS-005/NFR 10.1).

## HARD kapılar (P1–P8)

| Kapı | İnvariant | Ölçüt |
|------|-----------|-------|
| **P1** | Streaming first-byte | `first_byte_p95 ≤ 200` + `full_buffered=0` (FR-TTS-002/SAD §20) |
| **P2** | Cancel (barge-in) | `cancel_p95 ≤ 200` + `chunk_after_cancel=0` (FR-TTS-005/NFR 10.1) |
| **P3** | Pronunciation dictionary | `unhandled_structured=0` (FR-TTS-004) |
| **P4** | Akış sürekliliği / ölü hava | `underrun=0` (RTF<1; FR-RES-009) |
| **P5** | ≥2 SPI-uyumlu sağlayıcı | required_features + 8 kHz (FR-TTS-001/ADR-002) |
| **P6** | Ses karakteri tutarlılığı | `voice_inconsistent=0` + `voice_switch_unmapped=0` (FR-TTS-009) |
| **P7** | Cache (statik anons) | `cache_first_byte ≤ 30` (FR-TTS-010) |
| **P8** | Metering+taksonomi+8kHz+no-log | UsageRecord/req + ErrorTaxonomy + 8 kHz + NONE/EPHEMERAL |

`P9` (komşu seam) + `P10` (ErrorTaxonomy / sır+ham-ses+PII yok) → `validate`.

## Dosyalar

```
tts-adapter-spec.json                 # kaynak doğruluk (P1–P10 invariant)
tts-adapter.md                        # tasarım dokümanı
tts_adapter_probe.py                  # validate / simulate / selftest / schema (deterministik)
config/tts-adapter-profiles.json      # 2 somut sağlayıcı (A bulut / B edge) + 3 çalıştırma profili + voice_equivalence
samples/
  tts-happy-path.json                 # streaming + pronunciation + barge-in (A)
  tts-pronunciation-dict.json         # 4 yapısal alan tipi sözlükle (P3)
  tts-barge-in-cancel.json            # ardışık cancel ≤200ms, kesme sonrası yok (B; P2)
  tts-cache-hit.json                  # statik anons cache-hit first-byte ~0 (P7)
  tts-voice-equivalent.json           # fallback eşdeğer-ses ile tutarlılık (P6/4.3.2 sınır)
  tts-degraded.json                   # bilinçli bozuk: stream/cancel/dict/realtime kapalı → P1/P2/P3/P4 eler
tests/tts_adapter_behavior_test.py    # T1–T8 davranış kapısı
run_live_test.sh                      # statik + sample (+ canlı NOT)
```

## Çalıştırma

```bash
python3 tts_adapter_probe.py validate              # spec → P1–P10 + config
python3 tts_adapter_probe.py selftest              # iyi/kötü spec+sample negatif kapı kanıtı
python3 tts_adapter_probe.py simulate samples/tts-happy-path.json
python3 tests/tts_adapter_behavior_test.py         # T1–T8
bash run_live_test.sh                              # hepsi + canlı NOT/SKIP
```

## İki somut sağlayıcı (illüstratif, vendor-neutral)

| Sağlayıcı | Tip | first-byte | cancel | 8 kHz | residency | retention |
|-----------|-----|-----------:|-------:|:-----:|-----------|-----------|
| `tts-stream-A` | bulut nöral | 120 ms | 70 ms | ✓ | EU/TR | NONE |
| `tts-stream-B` | edge/on-prem | 95 ms | 55 ms | ✓ | TR | EPHEMERAL |

Her ikisi de tüm kapıları geçer → ADR-002 portföy (≥2 + fallback FR-TTS-008). Gecikme değerleri
**mühendislik varsayılanı**; gerçek değerler 0.3.x canlı PoC'ta ölçülür.

## Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| TTS fallback **anahtarlama** + ses tutarlılığı | **4.3.2** (FR-TTS-008/009; bu motor ≥2 SPI-uyum + eşdeğer-ses haritası varlığını doğrular) |
| Ortak yetenekler (timeout/retry/breaker/health/pool) | **4.1.2 / 4.1.6** (SAD §8.2; tüketilir) |
| Usage metering / cost **motoru** | **4.1.3** (UsageRecord üretimi doğrulanır) |
| Region/retention **motoru** | **4.1.4** (NFR 10.7) |
| TTS **cache motoru** (statik anons deposu) | **16.1** (FR-RES-003; cache-hit yolu desteklenir) |
| **Dead-air önleme** (filler) | **orchestrator** (FR-RES-009; süreklilik beslenir) |
| **Barge-in olay** üretimi | **2.2.3 / 3.1.3** (BARGE_IN → cancel tüketilir) |
| Ses **klonlama izni** | **4.2.6** (FR-TTS-006/007; `clonedVoiceConsentRef` taşınır) |
| Sağlayıcı **seçimi** | **0.2.6 / 0.3.x** (vendor-neutral, ADR-002) |

Vendor-neutral (ADR-002); deterministik (olay-tetikli, sanal saat, **random YOK**; gerçek TTS/ses üretimi
yok — sağlayıcı gecikme profili + akış **modeli**). Sır/credential, ham **SES/audio**, sentezlenecek ham
**METİN** ve PII **değeri** repoya **yazılmadı** — yalnız sağlayıcı kimliği + gecikme/akış sayıları + alan
tipleri + voice kimlikleri + sanal zaman.

```
İz: FR-TTS-001 → SR-TTS-001 → TC-TTS-001; FR-TTS-004 → SR-TTS-004 → TC-TTS-004; FR-TTS-005 →
SR-TTS-005 → TC-TTS-005 (RTM'de WBS=4.2.3 zaten eşli) + FR-TTS-002 (streaming; RTM anchor 0.2.3, bu
adapter'da uygulanır) + FR-TTS-009/010 (sınır → 4.3.2 / 16.1). SRS/RTM değişikliği gerekmedi.
```
