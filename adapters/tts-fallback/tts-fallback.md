# TTS Fallback + ses karakteri tutarlılığı — WBS 4.3.2

> Sağlayıcı Soyutlama Katmanı'nın **fallback ve degradation** dilimi (SAD §8.2/§8.3). Birincil TTS sentezi
> hata/timeout (circuit-open) verdiğinde ikincil TTS'ye geçer; in-flight sözün **kalan (çalınmamış) metnini**
> ikincide **eşdeğer ses** ile yeniden sentezler (zaten çalınmış metni tekrar etmez); her iki sağlayıcı düşerse
> deterministik akışa (insan temsilciye kontrollü aktarım) geçer — **çağrıyı düşürmez**. Çağrı boyu **ses
> karakteri tutarlı** kalır. Kaynak: **FR-TTS-008/009**, **BRD §19 (1)/(4)**, **SAD §8.3**, **API §11.3**
> (TtsAdapter Fallback notu). Çelişkide BRD/SAD esastır.

## 1. Mimari konum

```
        SPEAK durumu (SAD §6.1 turn state machine)
   LLM metin akışı ──► [ TTS Fallback Switcher ] ──► tek mantıksal ses akışı ──► Media Gateway ──► RTP
                            │  sarmalar  (voiceId çağrı boyu sabit)
              ┌─────────────┴──────────────┐
              ▼                            ▼
       Primary TtsAdapter          Secondary TtsAdapter        (≥2/kategori — ADR-002 / BRD §19 (1))
       (4.2.3)                     (4.2.3)                      eşdeğer ses: voice_equivalence
              │ hata/timeout/circuit-open (4.1.2)
              └──(TIMEOUT/UNAVAILABLE/RATE_LIMITED)──► Secondary ──(secondary de düşer)──► Deterministic flow
                                                       (eşdeğer ses + resynth)            (8.x handoff / 3.3.x)
```

SAD §8.3 fallback zinciri: **Primary TTS ──(timeout/error/circuit-open)──► Secondary TTS (eşdeğer ses) ──►
Deterministic flow.** Orchestrator yalnız TtsAdapter SPI'ye + switcher kararına bağımlıdır (ADR-001); somut
sağlayıcı arkada değişir (ADR-002). Switcher TtsAdapter SPI'sini (SAD §8.1 / API §11.3 `synthesize()`/`cancel()`)
**değiştirmez — sarmalar**; orchestrator'a **tek mantıksal ses akışı** sunar (T4) ve **voiceId'yi çağrı boyu sabit**
tutar (T8). TtsAdapter 4.2.3'ten `switching_owned_by 4.3.2` buraya delege edildi.

## 2. SPI yüzeyi (sarmalanan — SAD §8.1 / API §11.3)

`synthesize(textIn: AsyncStream<TextChunk>, voice: VoiceProfile, opts: TtsOptions): AsyncStream<AudioChunk>` +
`cancel(streamId)` (barge-in). `VoiceProfile{voiceId, language, pronunciationDictId?, rate?/pitch?/volume?,
clonedVoiceConsentRef?}`. `TtsOptions{sampleRate=8000, firstByteTargetMs}`. Ortak Adapter: `capabilities()`/
`health()`/`meter()`/`configure()` (API §11.1). `capabilities()`: features ⊇ `{streaming, barge_in_cancel,
pronunciation_dict}`, sample_rates ⊇ `{8000}`, **voices** (eşdeğer-ses haritası için), regions (residency).
Karşılamayan portföye giremez (T5).

## 3. HARD kapılar (T1–T10)

| Kapı | Ölçüt | İz |
|------|-------|----|
| **T1 FAILOVER** | geçici hata/timeout → ikincile geçiş, çağrı sürer (`utterance_lost=0`) | FR-TTS-008, SAD §8.3, BRD §19 (4) |
| **T2 RESYNTH CONTINUATION** | in-flight sözün kalan metni ikincide yeniden sentezlenir (`unspoken_lost=0`) + çalınmış metin tekrar edilmez (`resynth_replayed_spoken=0`) | FR-TTS-008/009, API §11.3 |
| **T3 SWITCH OVERHEAD** | anahtarlama gecikmesi (teardown+setup+first_byte+resynth) P95 ≤ 200 ms (yeşil 100) | NFR 10.1, SAD §20 |
| **T4 NO DUP / SINGLE STREAM** | `duplicate_speech=0` + `concurrent_active ≤ 1` | FR-TTS-002, SAD §8.1 |
| **T5 ≥2 SAĞLAYICI + EŞDEĞER SES** | `min_providers=2`, primary≠secondary, SPI-uyumlu + her profilde eşdeğer ses tanımlı | BRD §19 (1), ADR-002, FR-TTS-009 |
| **T6 NEVER DROP** | her iki düşerse deterministik akış, `dropped_call=0` | SAD §8.3, BRD §19 (4) |
| **T7 SEÇİCİ TETİK + NORMALİZE** | yalnız geçici sınıf failover (`improper_failover=0`) + `errors_normalized=errors_seen` | FR-TOOL-008, API §11.6 |
| **T8 SES KARAKTERİ TUTARLILIĞI** | voiceId çağrı boyu sabit (`voice_inconsistent=0`) + fallback eşdeğer ses (`voice_switch_unmapped=0`) | **FR-TTS-009**, SAD §8.3 |
| **T9 BARGE-IN PRESERVED** | anahtarlama sırasında/sonrasında cancel P95 ≤ 200 ms + kesme sonrası ses yok (`chunk_after_cancel=0`) | FR-TTS-005, NFR 10.1, SAD §6.1 |
| **T10 FLAP YOK + METERING + RESIDENCY** | `flap=0` (histerezis) + segment metering (CHARACTERS) + 8 kHz + tenant izolasyon | FR-BIL-002, NFR 10.7 |

Eşikler **mühendislik varsayılanı** (NFR 10.1 + 0.2.3 tts-eval bandı SAD §20 TTS first-byte ≤200ms / barge-in
≤200ms); gerçek değerler **0.3.x canlı PoC**'ta doğrulanır.

## 4. Routing kararı (T7 — seçici tetik)

Sağlayıcı hataları ortak **ErrorTaxonomy**'ye (API §11.6) çevrilir (eşleme motoru **4.1.5** — switcher tüketir):

| Ham | Taksonomi | Failover? |
|-----|-----------|-----------|
| timeout | `TIMEOUT` | ✅ ikincile geç + eşdeğer ses + resynth |
| 429 | `RATE_LIMITED` | ✅ |
| 5xx / bağlantı / circuit-open | `UNAVAILABLE` | ✅ |
| kimlik | `AUTH` | ❌ (ikincide de aynı; boşuna anahtarlama + ölü hava yok) → deterministik |
| geçersiz girdi | `INVALID_REQUEST` | ❌ |
| bölge | `REGION_VIOLATION` | ❌ |

**Histerezis (T10):** bir kez ikincile geçilince seans boyunca ikincil kalır (sticky secondary) — primary
"iyileşti" diye geri dönülmez (flap yok). İkincil de düşerse → deterministik akış.

## 5. Resynth continuation + ses karakteri tutarlılığı (T2 + T8 — görev başlığı)

**Resynth continuation (T2):** STT'deki "audio replay"in TTS karşılığı. Switcher in-flight söz için **çalınmış
karakter** (spoken) ile **çalınmamış kalan** (remaining) sınırını izler. Failover anında **yalnız kalan metin**
ikincide yeniden sentezlenir — kesme noktasından devam edilir; **zaten çalınmış metin tekrar seslendirilmez**
(kullanıcı cümleyi baştan duymaz). Kesme noktası gözetilmezse (baştan sentez) çalınmış metin tekrar edilir
(`resynth_replayed_spoken` — T2/T4 eler). Resynth tamponu yalnız in-flight sözün kalan metnidir; **durable
değil** — seans/bellek içi, EPHEMERAL + no-log + home-region (`resynth_buffer_ephemeral`).

**Ses karakteri tutarlılığı (T8 / FR-TTS-009):** İki katman:
- **(a) Aynı sağlayıcıda** voiceId çağrı boyu **sabit** — mid-call drift yok; cache'ten sunulan statik
  anonslar da aynı voiceId'yi taşır (FR-TTS-010 cache voiceId-anahtarlı).
- **(b) Fallback'te** ikincil, tenant'ın logical voiceId'sine karşılık gelen önceden tanımlı **eşdeğer
  fiziksel sesi** kullanır. `voice_equivalence`: logical voiceId → `{ provider_id: physical_voice_id }`;
  her profilde **primary VE secondary** için tanımlı olmalı (`require_equivalent_voice`). Eşdeğer tanımsız
  ya da yok sayılırsa karakter kırılır (`voice_switch_unmapped` — T8 eler).

Bu, vendor-neutral mimaride (ADR-002) farklı sağlayıcıların seslerinin **birbirinin eşdeğeri** olarak
haritalanmasıyla çözülür — bağlayıcı ses eşleştirme 0.2.3/0.3.x ses kalitesi/tutarlılığı eval'inde.

## 6. Kapsam ayrımı (T11 — TÜKETİR, uygulamaz)

| Konu | Sahip |
|------|-------|
| TtsAdapter implementasyonu (streaming/pronunciation/cancel) | 4.2.3 |
| timeout/retry/backoff/**circuit breaker**/health | 4.1.2 (circuit-open sinyali tüketilir) |
| hata normalizasyonu eşlemesi (ErrorTaxonomy) | 4.1.5 |
| connection pool | 4.1.6 |
| usage metering/cost **motoru** | 4.1.3 (UsageRecord üretimi doğrulanır) |
| residency/retention motoru | 4.1.4 |
| TTS cache motoru (statik anons) | 16.1 (cache-hit voiceId tutarlılığı tüketilir) |
| barge-in **olay** üretimi (VAD/turn-taking) | 2.2.3 / 3.1.3 (BARGE_IN → cancel tüketilir) |
| ses klonlama izni + kullanım kaydı | 4.2.6 (`clonedVoiceConsentRef` taşınır) |
| deterministic-flow / insan aktarımı **motoru** | 8.x handoff + 3.3.x (karar üretilir, akış değil) |
| TTS sağlayıcı **seçimi** | 0.2.3 / 0.2.6 / 0.3.x (vendor-neutral) |
| STT/LLM/Telephony fallback | 4.3.1 / 4.3.3 / (4.3.x) — kardeş görevler |
| birincil kesintide uçtan uca fallback testi | 4.3.4 |

Referans davranış: **0.3.1** `e2e_inbound_poc.py` (SPI seam — fallback referans deseni); **4.3.1** STT
fallback ile **kardeş** (aynı switcher disiplini, STT-audio-replay ↔ TTS-resynth-continuation).

## 7. Gözlemlenebilirlik (BRD §15 → 0.4.7)

`tts_fallback_total{from,to,reason}` (retry/fallback metriği SAD §17.1; reason = ErrorTaxonomy DÜŞÜK
kardinalite), `tts_switch_overhead_ms`, `tts_resynth_chars_total`, `tts_voice_switch_total{mapped}`,
`tts_barge_in_cancel_ms`, `tts_deterministic_flow_total`, `tts_speak_complete_total`. `provider_id`/`voice_id`/
`reason`/`mapped` DÜŞÜK kardinalite (label uygun); `call_id`/`stream_id`/`correlation_id` YÜKSEK kardinalite →
yalnız trace/exemplar (0.4.7 label_policy, 3.1.5 producer). Ham SES/metin/PII metriklerde yok.

## 8. Çalıştırma

```
python3 tts_fallback_probe.py validate            # spec ↔ invariant (T1–T11) + config + eşdeğer-ses kapısı
python3 tts_fallback_probe.py simulate <sample>   # deterministik switcher → T1–T10 → çıkış kodu
python3 tts_fallback_probe.py selftest            # iyi/kötü kapı kanıtı
python3 tests/tts_fallback_behavior_test.py       # davranış kapısı (T1–T10)
./run_live_test.sh                                # statik + sample + (canlı SKIP/not)
```

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (olay-tetikli, sanal saat, random
YOK; gerçek TTS/ses üretimi yok — sağlayıcı gecikme profili + akış/hata MODELİ). Ham SES, sentez METNİ veya
PII DEĞERİ repoya yazılmaz.
