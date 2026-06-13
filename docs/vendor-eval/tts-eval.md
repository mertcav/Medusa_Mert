# TTS (Ses Sentezi) Sağlayıcı Değerlendirmesi

| Alan | Değer |
|------|-------|
| **WBS** | 0.2.3 |
| **Faz · Öncelik** | F0 · Must |
| **İz** | FR-TTS-001..010; SR-TTS-001..010; FR-RTC-002 (barge-in); FR-RES-008 (8 kHz); FR-RES-009 (dead air); FR-KB-010 (no-log); NFR 10.1/10.7; SAD §6.1 (barge-in kesme), §8.1 (TtsAdapter), §20 (gecikme bütçesi); ADR-002 |
| **Durum** | v1.0 — ölçüt + metodoloji + harness hazır; **canlı sağlayıcı ölçümü 0.3.x PoC'ta** |
| **Tarih** | 2026-06-13 |

> **Sağlayıcı-nötr (ADR-002):** Bu doküman bir TTS sağlayıcısı **seçmez**. Sağlayıcıları ölçüt +
> metodoloji üzerinden ele alır; nihai seçim **0.2.6** karar raporunda (kalite + gecikme + maliyet +
> residency + DPA/no-train + risk) bütünsel yapılır. ADR-002 gereği kategori başına **≥2 sağlayıcı +
> fallback** (FR-TTS-008) ve **ses karakteri tutarlılığı** (FR-TTS-009) korunur.

---

## 1. Kapsam ve amaç
TTS sağlayıcılarını telefoni gerçeğine (8 kHz dar bant, gerçek-zamanlı çift yönlü konuşma) sadık,
**sağlayıcı-nötr** ve **tekrarlanabilir** bir ölçüt setiyle değerlendirmek; özellikle görev başlığındaki
üç boyut:
- **First-byte gecikmesi** (TTFB — FR-TTS-002) → **SAD §20** "TTS first byte ~100–200 ms (P95)" kalemine kapı,
- **Barge-in kesme** gecikmesi (FR-TTS-005 / FR-RTC-002) → **NFR 10.1 / SAD §6.1** "TTS kesme ≤ 200 ms" kapısı,
- **Ses kalitesi** (FR-TTS-001/003) — MOS (doğallık), **en-kötü-dil** (EN+TR) üzerinden;

ayrıca destekleyici: **streaming sürekliliği / ölü hava** (FR-RES-009), **telaffuz doğruluğu**
(pronunciation dictionary — FR-TTS-004), **ses karakteri tutarlılığı** (FR-TTS-009), **cache** (statik
anonslar — FR-TTS-010/FR-RES-003), **8 kHz native · residency · no-train** (FR-RES-008/NFR 10.7/FR-KB-010).

Kapsam **dışı** (ilgili ama ayrı görevler): STT (0.2.2), LLM (0.2.4), telekom medya taşıma gecikmesi
(0.2.1), barge-in olay üretimi uygulaması (2.2.7), TTS fallback uygulaması (4.3.2), ses klonlama izni
(4.2.6). Bu görev **ölçüt + metodoloji + ölçüm hattı** üretir; **canlı sağlayıcı ölçümü** kimlik bilgisi
gerektirir ve **0.3.x PoC**'ta her aday için alınıp matrise işlenir.

## 2. TtsAdapter sözleşmesi (ölçülen yüzey)
Değerlendirme, SAD §8.1 / `API.md §11.3` **TtsAdapter** SPI'sine göre yapılır — sağlayıcıya özel
biçimler adapter arkasında normalize edilir (vendor-neutral):

```
synthesize(textIn: AsyncStream<TextChunk>, voice: VoiceProfile, opts: TtsOptions): AsyncStream<AudioChunk>
cancel(streamId): void   // barge-in kesme ≤200ms (FR-TTS-005, FR-RTC-002, NFR 10.1)
VoiceProfile { voiceId; language; pronunciationDictId?; rate?; pitch?; volume?; clonedVoiceConsentRef? }
TtsOptions  { sampleRate(=8000); firstByteTargetMs }
AudioChunk  { t_ms; dur_ms; ... }   // ilk chunk = first-byte; chunk akışı = süreklilik
```
Bir sağlayıcı eval'a girebilmek için bu sözleşmeyi (streaming first-byte, `cancel()` ile anında kesme,
8 kHz, dil/voice konfig, pronunciation dictionary) karşılamalıdır; karşılamayan yetenek ilgili ölçütte
sıfır alır.

## 3. Değerlendirme ölçütleri ve ağırlıkları
Gecikme (first-byte + barge-in) ve ses kalitesi birincil; karar için ağırlıklı rubrik:

| # | Ölçüt | Ağırlık | Nasıl ölçülür | İz |
|---|-------|--------:|----------------|-----|
| C1 | **First-byte gecikmesi** (TTFB, P95) | 20% | harness `score` → SAD §20 kapısı | FR-TTS-002, NFR 10.1, SAD §20 |
| C2 | **Barge-in kesme gecikmesi** (P95) | 20% | harness (cancel→stop) → NFR 10.1 kapısı | FR-TTS-005, FR-RTC-002, SAD §6.1 |
| C3 | **Ses kalitesi — MOS** (EN+TR; en-kötü-dil) | 25% | harness (MOS dış girdi) | FR-TTS-001/003 |
| C4 | **Streaming sürekliliği / ölü hava** | 10% | harness (underrun, RTF) | FR-RES-009 |
| C5 | **Telaffuz doğruluğu** (sayı/tarih/para/isim) | 10% | harness (pronunciation oranı) | FR-TTS-004 |
| C6 | **Ses karakteri tutarlılığı** | 5% | config + voiceId sabitliği | FR-TTS-009 |
| C7 | **Cache (statik anons)** | 5% | yetenek + cache-hit first-byte | FR-TTS-010, FR-RES-003 |
| C8 | **8 kHz native · residency · no-train** | 5% | config inceleme | FR-RES-008, NFR 10.7, FR-KB-010 |

> C1–C5 harness ile **sayısal** ölçülür; C6–C8 yetenek/uygunluk. Sayısal **knock-out kapıları**:
> C1 (TTFB), C2 (barge-in), C3 (MOS), C4 (ölü hava) — herhangi biri **KIRMIZI/fail** ise aday elenir.
> C5 (telaffuz) **soft** uyarı eşiğidir (0.2.6'da bütünsel). Maliyet/sözleşme ağırlığı **0.2.6**'da uygulanır.

## 4. Metrik tanımları
- **First-byte gecikmesi (TTFB)** = `first_audio_chunk.t_ms − synthesize_request.t_ms`. Cache hit'i
  (FR-TTS-010) ayrı tutulur (hit'te ~0); kapı **cold (gerçek sentez)** TTFB üzerinden. SAD §20 TTS kalemi.
- **Barge-in kesme gecikmesi** = `audio_stopped_ms − cancel_req_ms` (kullanıcı sözü kesti → `cancel()` →
  ses fiilen sustu). Kesilemeyen/yavaş kesilen TTS üst üste konuşmaya (talk-over) yol açar. NFR 10.1.
- **MOS (Mean Opinion Score)** = algısal doğallık (1–5); **dış girdi** (panel dinleme skoru ya da
  kalibre objektif vekil — vendor-neutral + tekrarlanabilirlik). Kapı **en-kötü-dil** üzerinden
  (EN+TR zorunlu — zayıf dili genel ortalama maskelemesin; STT WER ile aynı disiplin).
- **Streaming sürekliliği / ölü hava** = playout ilk chunk'ta başlar; chunk *i* geldiğinde o ana dek
  üretilmiş ses süresi geçen süreden kısaysa **tampon boşalmıştır → ölü hava (underrun)**. Sağlıklı akış
  gerçek-zamandan hızlı üretir (**RTF = teslim süresi / ses süresi < 1**), tampon büyür. FR-RES-009.
- **Telaffuz doğruluğu** = yapısal alanlarda (sayı/tarih/para/özel-isim) doğru-sentez oranı; pronunciation
  dictionary (FR-TTS-004) öncesi/sonrası etkisi PoC'ta nicelenir.

## 5. Kabul kapıları (gate) — mühendislik varsayılanı
| Ölçüt | Kapı (pass) | Yeşil bant |
|-------|-------------|------------|
| C1 first-byte P95 | **≤ 200 ms** (SAD §20 üst) | ≤ 100 ms |
| C2 barge-in kesme P95 | **≤ 200 ms** (NFR 10.1) | ≤ 100 ms |
| C3 MOS (en-kötü-dil) | **≥ 4.0** | ≥ 4.3 |
| C4 ölü hava (underrun) | **= 0** (RTF < 1) | — |
| C5 telaffuz oranı | **≥ 0.90** (soft) | — |

> Eşikler **mühendislik varsayılanı**; gerçek değerler **0.3.x PoC**'ta telefoni koşullarında (8 kHz,
> gürültü/aksan — 18.7 test seti) doğrulanır ve gerekirse use-case bazında sıkılaştırılır. `score`
> bütçe/kalite kapısı geçilmezse çıkış kodu `1` → CI/0.4.4 hattında gate.

## 6. Ölçüm metodolojisi (harness)
`tts_eval_probe.py` (stdlib-only) üç mod sunar:

| Mod | İş |
|-----|----|
| `score` | Bir sağlayıcı **utterance test setini** (MOS + first-byte + barge-in + chunk akışı + telaffuz) puanlar: TTFB/barge-in P50/P95/P99, MOS en-kötü-dil, ölü hava (underrun/RTF), telaffuz oranı + kapı → çıkış kodu |
| `compare` | Çok sağlayıcılı `score` çıktısını markdown karşılaştırma matrisine indirir |
| `selftest` | Credential'sız çekirdek doğrulama (TTFB/barge-in/MOS/ölü-hava/percentile birim kontrolleri) |

**Örnek (sample) şeması:** her sağlayıcı için bir test seti JSON — `utterances[]` (her biri:
`language`, `field_type ∈ {general,number,date,currency,name}`, `text`, `mos`, `first_byte_ms`,
`cached`, `pronunciation_ok`, `barge_in{cancel_req_ms,audio_stopped_ms}`, `chunks[{t_ms,dur_ms}]`).
Detaylı şema `tts_eval_probe.py` başlığında.

**Canlı PoC akışı (credential gerektiğinde):** TTS adapter, sentetik metinleri (FR-TST-008 — gerçek
müşteri verisi yok) sağlayıcıya akıtır; ilk chunk zaman damgası (TTFB), `cancel()` sonrası susma anı
(barge-in), chunk akışı (süreklilik) ve 8 kHz çıktı yukarıdaki sample şemasına yazılır; MOS bir panel/
kalibre araç ile eklenir; `score` çalıştırılır. Sağlayıcı API anahtarı **ortam değişkeni** ile geçilir,
**dosyaya yazılmaz** (`.gitignore`: `.env*`, `secrets/`).

## 7. Karşılaştırma matrisi (İLLÜSTRATİF profillerle)
Aşağıdaki tablo `samples/` altındaki **illüstratif** sağlayıcı profillerinden harness ile üretilmiştir.
**Bunlar gerçek sağlayıcı benchmark'ı değildir**; metodolojiyi ve kapıları göstermek içindir. Gerçek
değerler 0.3.x canlı PoC'ta her sağlayıcı için ölçülüp buraya işlenecektir.

| Sağlayıcı | MOS EN | MOS TR | TTFB P95 (ms) | Barge-in P95 (ms) | Ölü hava | Telaffuz | Karar |
|---|---|---|---|---|---|---|---|
| tts-cloud-A | 4.3 | 4.2333 | 131.3 | 100.6 | yok | 1.0 | 🟡 SARI |
| tts-cloud-B | 4.3333 | 3.625 | 126.2 | 140.95 | yok | 0.6667 | 🔴 KIRMIZI |
| tts-cloud-C-degraded | 4.15 | 3.9 | 342.0 | 392.75 | 16 underrun | 0.0 | 🔴 KIRMIZI |

> Kapılar: first-byte P95 ≤ 200 ms (SAD §20, yeşil ≤ 100); barge-in kesme P95 ≤ 200 ms (NFR 10.1, yeşil
> ≤ 100); MOS en-kötü-dil ≥ 4.0 (yeşil ≥ 4.3); ölü hava = 0. Yeniden üret:
> `python3 docs/vendor-eval/tts_eval_probe.py score samples/<x>.json --out /tmp/<x>.json` → `compare`.

**Matrisin gösterdiği** (illüstratif): **A** tüm kapıları geçer (gecikmeler sarı bantta, ölü hava yok,
telaffuz tam → bütünsel SARI); **B** EN MOS güçlü (4.33) ama **TR MOS 3.625 < 4.0** → en-kötü-dil
kapısında elenir (genel ortalama ~3.98 maskelemez) — EN güçlü TR zayıf adayı kapı yakalar; **C**
wideband-only (8 kHz native yok → ekstra resample → **TTFB 342 ms** bütçeyi aşar), **barge-in 393 ms**
(kullanıcıyı kesemez), streaming gerçek-zamana ayak uyduramaz (**ölü hava/underrun**), telaffuz 0 →
çoklu KIRMIZI.

## 8. Bulgular ve öneri (sağlayıcı-nötr)
1. TTS, uçtan uca gecikme bütçesinin (NFR 10.1: P95 ≤ 1.200 ms) **iki ucundadır**: yanıtın başlaması
   (first-byte) ve kullanıcı araya girdiğinde **anında durması** (barge-in). İkisi de ayrı ölçülür;
   first-byte iyi olup barge-in yavaş olan bir sağlayıcı konuşmayı doğal hissettirmez (talk-over).
2. **Ses kalitesi (MOS) dile göre bağımsız ölçülmeli:** Çoğu sağlayıcı EN'de güçlüdür; TR doğallığı
   (prozodi/vurgu) ayrı doğrulanmazsa kalite yanıltıcı görünür. Kapı **en-kötü-dil** üzerinden (EN+TR).
3. **Ölü hava (dead air) ayrı bir risktir** (FR-RES-009): TTS gerçek-zamandan yavaş üretirse (RTF ≥ 1)
   tampon boşalır, kullanıcı kopuk/duraklamalı ses duyar. Streaming sürekliliği underrun ile ölçülür.
4. **Telaffuz (sayı/tarih/para/isim)** kritik iş alanlarıdır (bakiye, tarih, müşteri adı); pronunciation
   dictionary (FR-TTS-004) etkisi PoC'ta öncesi/sonrası nicelenir. Soft kapı; 0.2.6'da bütünsel.
5. **ADR-002 gereği ≥2 sağlayıcı + fallback (FR-TTS-008) + ses karakteri tutarlılığı (FR-TTS-009):** en
   az iki kapı-geçen aday; biri birincil, diğeri fallback (4.3.2) ve tenant başına **eşdeğer ses**.
   **no-train / dataRetention=NONE** (FR-KB-010) ön koşul.
6. **Karar 0.2.6'ya bırakılır** (vendor-neutral): bu görev ölçüt + metodoloji + kapıyı sağladı; sayısal
   sıralama canlı PoC ölçümleri (MOS panel + telefoni 8 kHz) gelince netleşir.

## 9. Açık konular / sonraki adımlar
- [ ] Canlı PoC: her aday için 8 kHz telefoni sentetik metinlerle (FR-TST-008) gerçek TTFB/barge-in/ölü-hava
      ölç (0.3.1/0.3.2 ile birlikte); MOS'u panel/kalibre araçla ekle; 18.7 gürültü/düşük-hat seti dahil.
- [ ] Pronunciation dictionary (FR-TTS-004) öncesi/sonrası telaffuz oranı farkını niceleyen A/B ölçümü.
- [ ] Fallback (4.3.2): birincil → ikincil geçişte **ses karakteri tutarlılığı** (FR-TTS-009) testi (tenant eşdeğer ses).
- [ ] Cache (FR-TTS-010/FR-RES-003): statik anons hit oranı ≥ %80 (16.1) + cache-hit TTFB ~0 doğrulaması.
- [ ] `score` gate'ini 0.4.4 CI hattına bağla (regresyon: voice/profil değişiminde MOS/gecikme kaymasını yakala).
- [ ] Sonuçları 0.2.6 karar raporu girdisine (maliyet + residency + DPA/no-train) bağla; fallback eşleştirmesini (4.3.2) belirle.

## 10. İzlenebilirlik
- **Kaynak:** ADR-002 (vendor-neutral, ≥2 sağlayıcı + fallback); SAD §6.1 (barge-in kesme), §8.1 (TtsAdapter SPI), §20 (gecikme bütçesi).
- **FR:** FR-TTS-001..010 (sağlayıcı, first-byte streaming, dil/aksan/hız, pronunciation dict, barge-in kesme, ses klonlama, fallback, ses tutarlılığı, cache), FR-RTC-002 (barge-in algı), FR-RES-008 (8 kHz), FR-RES-009 (dead air), FR-KB-010 (no-log).
- **SR:** SR-TTS-001..010 (SRS §4.7).
- **NFR:** 10.1 (P95 ≤ 1.200 ms; TTS first-byte ~100–200 ms + barge-in kesme ≤ 200 ms alt-kalemleri), 10.7 (residency).
- **WBS:** 0.2.3 (bu); girdi → 0.2.6 (karar), 0.3.1/0.3.2 (PoC ölçüm), 4.2.3 (TTS adapter uygulaması), 4.3.2 (fallback), 2.2.6/2.2.7 (streaming TTS connector + barge-in kesme), 16.1 (TTS cache), 18.7 (gürültü/düşük-hat test seti).
