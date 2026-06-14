# `telephony/codec/` — WBS 2.2.2

Codec yönetimi (8kHz) + gereksiz resample/transcode önleme — Real-time **Media Gateway** medya yolu
codec seçimi + zincir format yönetimi (SAD §6/§7, L2). Kaynak doğruluk: **`codec-spec.json`**.
Tasarım: **`codec.md`**. Vendor-neutral (ADR-002), credential-free, stdlib-only — `rtp-jitter/`
(2.2.1) + `managed-cpaas/` (2.1.3) + `byoc-sip/` (2.1.4) disipliniyle aynı.

Telefoni **8 kHz dar bant** (G.711 µ/A-law, Opus-NB) native korunur → SDP offer/answer benzeri
**codec pazarlığı** (narrowband-first, passthrough tercih) → medya zinciri yürünür, her sınırda
**resample** (rate farkı) / **transcode** (encoding farkı) tespit edilir → **GEREKLİ** (kaçınılamaz)
ile **GEREKSİZ** (DP ile hesaplanan minimuma göre fazla) dönüşüm ayrılır → STT/TTS 16kHz isterse
**tek kontrollü resample noktası** (SAD §7.2). `FR-RES-008` = gereksiz resampling/transcoding önlenir.

## İçerik
| Dosya | Ne |
|-------|----|
| `codec-spec.json` | Kaynak doğruluk: codec kataloğu, pazarlık, zincir analizi sözleşmesi, kapılar C1–C6, metrikler, invariant C1–C14 |
| `codec.md` | Tasarım dokümanı (pazarlık, zincir analizi, minimal-DP, gereksiz dönüşüm, tek resample seam, 8kHz native) |
| `codec_probe.py` | stdlib-only kapı: `validate` / `simulate` / `selftest` / `schema` + deterministik pazarlık + zincir analizi motoru |
| `config/codec-profiles.json` | İllüstratif codec offer/answer profilleri (managed-WS G.711 / BYOC RTP / Opus-NB; sır yok) |
| `samples/*.json` | Codec zinciri senaryoları (passthrough/opus-transcode/tek-resample pass + redundant-transcode/double-resample fail) |
| `tests/codec_behavior_test.py` | Codec yönetimi davranış kapısı (T1–T6) |
| `run_live_test.sh` | Statik kapı + (varsa) canlı endpoint notu; yoksa SKIP |

## Kullanım
```
python3 codec_probe.py validate                                     # spec+config kapısı (C1–C14)
python3 codec_probe.py simulate samples/codec-passthrough-g711.json # G.711 passthrough (0 dönüşüm, geçer)
python3 codec_probe.py simulate samples/codec-single-resample-stt16k.json  # tek kontrollü resample (geçer)
python3 codec_probe.py simulate samples/codec-redundant-transcode.json     # gereksiz µ→A→µ (eler)
python3 codec_probe.py simulate samples/codec-double-resample.json         # çift resample U-dönüşü (eler)
python3 codec_probe.py selftest                                     # iyi/kötü kanıt
bash run_live_test.sh                                               # uçtan uca statik kapı
```

## Kapılar (HARD)
- **C1** telefoni transport codec **8 kHz dar bant** (G.711 µ/A-law veya Opus-NB; wire rate 8000).
- **C2** pazarlık **conversion-minimizing** ortak codec seçer (ortak 8kHz varsa narrowband-first passthrough).
- **C3** **gereksiz transcode = 0** (actual_transcodes == minimal_transcodes).
- **C4** **gereksiz resample = 0** (actual_resamples == minimal_resamples).
- **C5** yön başına **≤1 kontrollü resample noktası** (SAD §7.2 tek adaptör seam'i).
- **C6** rate/encoding **U-dönüşü YOK** (8k→16k→8k veya µ→A→µ israfı).

## Durum
**validate 46/46 · selftest 34/34 · codec_behavior 20/20** 🟢. 5 sample beklendiği gibi
(3 pass + `codec-redundant-transcode`/`codec-double-resample` bilinçli fail). **Yöntem:** gereksiz
dönüşüm, **uçları pinlenmiş (wire/adapter sabit) + iç stage'leri native üzerinde serbest** bir
zincirde **DP ile hesaplanan minimum dönüşüm** ile gerçek (actual) dönüşüm farkından çıkarılır →
`unnecessary = actual − minimal`; 0 ise israf yok. **Bulgu:** 8kHz dar bant passthrough (G.711/Opus-NB)
sıfır dönüşümle ideal; STT/TTS 16kHz isterse **tek** kontrollü resample seam'i C5 içinde kalır; çoklu
resample/encoding U-dönüşleri C4/C5/C6 ile yakalanır.
Bağlar: pazarlık/zincir → 2.1.3/2.1.4 taşıma; RTP sonlandırma (codec-agnostik) → 2.2.1; STT/TTS
8kHz native yeteneği → vendor-eval 0.2.2/0.2.3 (C8 8kHz ölçütü) + 2.2.5/2.2.6 connector; metrikler →
observability 0.4.7 (`voice_codec_info`). İz: FR-RES-008 → SR-RES-008 (A) → TC-RES-008.
Rapor: `reports/2.2.2-codec-management-8khz-raporu.md`.
