# STT Fallback (hata/timeout → ikincil) — WBS 4.3.1

> Sağlayıcı Soyutlama Katmanı'nın **fallback ve degradation** dilimi (SAD §8.2/§8.3). Birincil STT akışı
> hata/timeout (circuit-open) verdiğinde ikincil STT'ye geçer; mümkünse in-flight söz için son N saniye
> audio'yu ikincile yeniden gönderir (kısmi audio replay); her iki sağlayıcı düşerse deterministik akışa
> (insan temsilciye kontrollü aktarım) geçer — **çağrıyı düşürmez**. Kaynak: **FR-STT-008**, **BRD §19 (1)/(4)**,
> **SAD §8.3**, **API §11.2** (SttAdapter Fallback notu). Çelişkide BRD/SAD esastır.

## 1. Mimari konum

```
        CAPTURE durumu (SAD §6.1 turn state machine)
   8 kHz medya ──► [ STT Fallback Switcher ] ──► tek mantıksal Transcript akışı ──► THINK (LLM)
                        │  sarmalar
          ┌─────────────┴──────────────┐
          ▼                            ▼
   Primary SttAdapter          Secondary SttAdapter        (≥2/kategori — ADR-002 / BRD §19 (1))
   (4.2.1/4.2.2)               (4.2.1/4.2.2)
          │ hata/timeout/circuit-open (4.1.2)
          └──(TIMEOUT/UNAVAILABLE/RATE_LIMITED)──► Secondary ──(secondary de düşer)──► Deterministic flow
                                                                                       (8.x handoff / 3.3.x)
```

SAD §8.3 fallback zinciri: **Primary STT ──(timeout/error/circuit-open)──► Secondary STT ──► Deterministic flow.**
Orchestrator yalnız SttAdapter SPI'ye + switcher kararına bağımlıdır (ADR-001); somut sağlayıcı arkada
değişir (ADR-002). Switcher SttAdapter SPI'sini (SAD §8.1 / API §11.2 `stream()`) **değiştirmez — sarmalar**;
orchestrator'a **tek mantıksal stream** sunar (S4). LLM/TTS/Telephony adapter'larından `switching_owned_by
4.3.x` buraya delege edildi.

## 2. SPI yüzeyi (sarmalanan — SAD §8.1 / API §11.2)

`stream(audioIn: AsyncStream<AudioChunk>, opts: SttOptions): AsyncStream<Transcript>` — `Transcript{text,
isFinal, confidence, words, language}`. `SttOptions{language, sampleRate=8000, interimResults (partial —
FR-STT-001), phraseBoost (FR-STT-004/005), endpointing (FR-RTC-013)}`. Ortak Adapter: `capabilities()`/
`health()`/`meter()`/`configure()` (API §11.1). `capabilities()`: features ⊇ `{streaming}`, sample_rates ⊇
`{8000}`, regions (residency). Karşılamayan portföye giremez (S5).

## 3. HARD kapılar (S1–S8)

| Kapı | Ölçüt | İz |
|------|-------|----|
| **S1 FAILOVER** | geçici hata/timeout → ikincile geçiş, çağrı sürer (`utterance_lost=0`) | FR-STT-008, SAD §8.3, BRD §19 (4) |
| **S2 AUDIO REPLAY** | in-flight söz için son ≤`replay_window_ms` (5000) audio ikincile replay (`missing_replay=0` + `replay_window_exceeded=0`) | FR-STT-008, API §11.2 |
| **S3 SWITCH OVERHEAD** | anahtarlama gecikmesi (teardown+setup+replay) P95 ≤ 200 ms (yeşil 100) | NFR 10.1, SAD §20 |
| **S4 NO DUP / SINGLE STREAM** | `duplicate_final=0` + `concurrent_active ≤ 1` | FR-STT-002, SAD §8.1 |
| **S5 ≥2 SAĞLAYICI** | `min_providers=2`, primary≠secondary, her ikisi SPI-uyumlu | BRD §19 (1), ADR-002 |
| **S6 NEVER DROP** | her iki düşerse deterministik akış, `dropped_call=0` | SAD §8.3, BRD §19 (4) |
| **S7 SEÇİCİ TETİK + NORMALİZE** | yalnız geçici sınıf failover (`improper_failover=0`) + `errors_normalized=errors_seen` | FR-TOOL-008, API §11.6 |
| **S8 FLAP YOK + METERING + RESIDENCY** | `flap=0` (histerezis) + segment metering + 8 kHz + tenant izolasyon | FR-BIL-002, NFR 10.7 |

Eşikler **mühendislik varsayılanı** (NFR 10.1 + 0.2.2 stt-eval bandı SAD §20 final P95 ≤200ms); gerçek
değerler **0.3.x canlı PoC**'ta doğrulanır.

## 4. Routing kararı (S7 — seçici tetik)

Sağlayıcı hataları ortak **ErrorTaxonomy**'ye (API §11.6) çevrilir (eşleme motoru **4.1.5** — switcher tüketir):

| Ham | Taksonomi | Failover? |
|-----|-----------|-----------|
| timeout | `TIMEOUT` | ✅ ikincile geç + replay |
| 429 | `RATE_LIMITED` | ✅ |
| 5xx / bağlantı / circuit-open | `UNAVAILABLE` | ✅ |
| kimlik | `AUTH` | ❌ (ikincide de aynı; boşuna anahtarlama + ölü hava yok) → deterministik |
| geçersiz girdi | `INVALID_REQUEST` | ❌ |
| bölge | `REGION_VIOLATION` | ❌ |

**Histerezis (S8):** bir kez ikincile geçilince seans boyunca ikincil kalır (sticky secondary) — primary
"iyileşti" diye geri dönülmez (flap yok). İkincil de düşerse → deterministik akış.

## 5. Kısmi audio replay (S2)

Switcher in-flight söz için (son final'den bu yana) ham 8 kHz audio'yu **rolling tampon**da (≤`replay_window_ms`,
EPHEMERAL, no-log, home-region) tutar. Failover anında bu audio ikincile yeniden gönderilir → söz ikincide
tamamlanır, kaybolmaz. Söz `replay_window_ms`'ten uzunsa fazlası replay edilemez (`replay_window_exceeded`).
Tampon **durable değil** — seans/bellek içi, oturum sonu temizlenir (residency: `replay_buffer_ephemeral`).

## 6. Kapsam ayrımı (S9 — TÜKETİR, uygulamaz)

| Konu | Sahip |
|------|-------|
| SttAdapter implementasyonu (streaming/partial/final/confidence/phrase-boost) | 4.2.1 / 4.2.2 |
| timeout/retry/backoff/**circuit breaker**/health | 4.1.2 (circuit-open sinyali tüketilir) |
| hata normalizasyonu eşlemesi (ErrorTaxonomy) | 4.1.5 |
| connection pool | 4.1.6 |
| usage metering/cost **motoru** | 4.1.3 (UsageRecord üretimi doğrulanır) |
| residency/retention motoru | 4.1.4 |
| deterministic-flow / insan aktarımı **motoru** | 8.x handoff + 3.3.x (karar üretilir, akış değil) |
| STT sağlayıcı **seçimi** | 0.2.2 / 0.2.6 / 0.3.x (vendor-neutral) |
| TTS/LLM/Telephony fallback | 4.3.2 / 4.3.3 / (4.3.x) — kardeş görevler |
| birincil kesintide uçtan uca fallback testi | 4.3.4 |

Referans davranış: **0.3.1** `e2e_inbound_poc.py` `_stt_with_fallback` (SPI seam — bu motorun referansı).

## 7. Gözlemlenebilirlik (BRD §15 → 0.4.7)

`stt_fallback_total{from,to,reason}` (retry/fallback metriği SAD §17.1; reason = ErrorTaxonomy DÜŞÜK
kardinalite), `stt_switch_overhead_ms`, `stt_audio_replayed_ms`, `stt_deterministic_flow_total`,
`stt_final_total`. `call_id`/`utterance_id`/`correlation_id` YÜKSEK kardinalite → yalnız trace/exemplar
(0.4.7 label_policy, 3.1.5 producer). Ham AUDIO/transkript/PII metriklerde yok.

## 8. Çalıştırma

```
python3 stt_fallback_probe.py validate            # spec ↔ invariant (S1–S10) + config kapısı
python3 stt_fallback_probe.py simulate <sample>   # deterministik switcher → S1–S8 → çıkış kodu
python3 stt_fallback_probe.py selftest            # iyi/kötü kapı kanıtı
python3 tests/stt_fallback_behavior_test.py       # davranış kapısı (T1–T8)
./run_live_test.sh                                # statik + sample + (canlı SKIP/not)
```

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (olay-tetikli, sanal saat, random
YOK; gerçek STT/ses tanıma yok — sağlayıcı gecikme profili + akış/hata MODELİ). Ham AUDIO, transkript METNİ
veya PII DEĞERİ repoya yazılmaz.
