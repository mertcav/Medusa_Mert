# STT (Konuşma Tanıma) Sağlayıcı Değerlendirmesi

| Alan | Değer |
|------|-------|
| **WBS** | 0.2.2 |
| **Faz · Öncelik** | F0 · Must |
| **İz** | FR-STT-001..008; SR-STT-001..008; FR-RES-008 (8 kHz); FR-RTC-013/ADR-005 (endpointing); FR-KB-010 (no-log); NFR 10.1/10.7; SAD §8.1 (SttAdapter), §20 (gecikme bütçesi); ADR-002 |
| **Durum** | v1.0 — ölçüt + metodoloji + harness hazır; **canlı sağlayıcı ölçümü 0.3.x PoC'ta** |
| **Tarih** | 2026-06-13 |

> **Sağlayıcı-nötr (ADR-002):** Bu doküman bir STT sağlayıcısı **seçmez**. Sağlayıcıları ölçüt +
> metodoloji üzerinden ele alır; nihai seçim **0.2.6** karar raporunda (doğruluk + gecikme + maliyet +
> residency + DPA/no-train + risk) bütünsel yapılır. ADR-002 gereği kategori başına **≥2 sağlayıcı +
> fallback** (FR-STT-008) korunur.

---

## 1. Kapsam ve amaç
STT sağlayıcılarını telefoni gerçeğine (8 kHz dar bant, gürültülü hat) sadık, **sağlayıcı-nötr** ve
**tekrarlanabilir** bir ölçüt setiyle değerlendirmek; özellikle:
- **Doğruluk** (WER — EN+TR ayrı; yapısal alanlarda CER — FR-STT-005),
- **Streaming partial/final** semantiği (FR-STT-002),
- **Final-transcript gecikmesi** → **SAD §20** "STT final transcript ~100–200 ms (P95)" kalemine kapı,
- **Confidence** üretimi + kalibrasyonu (FR-STT-006/007),
- **Dil/lehçe** kapsaması (en az EN+TR — FR-STT-003).

Kapsam **dışı** (ilgili ama ayrı görevler): TTS (0.2.3), LLM (0.2.4), telekom medya taşıma gecikmesi
(0.2.1), edge VAD/endpointing kararı (ADR-005 → 2.2.3), fallback uygulaması (4.3.1). Bu görev
**ölçüt + metodoloji + ölçüm hattı** üretir; **canlı sağlayıcı ölçümü** kimlik bilgisi gerektirir ve
**0.3.x PoC**'ta her aday için alınıp matrise işlenir.

## 2. SttAdapter sözleşmesi (ölçülen yüzey)
Değerlendirme, SAD §8.1 / `API.md §11.2` **SttAdapter** SPI'sine göre yapılır — sağlayıcıya özel
biçimler adapter arkasında normalize edilir (vendor-neutral):

```
stream(audioIn: AsyncStream<AudioChunk>, opts: SttOptions): AsyncStream<Transcript>
SttOptions { language; sampleRate(=8000); interimResults(=partial); phraseBoost[]; endpointing{} }
Transcript { text; isFinal; confidence; words[{w,startMs,endMs,confidence}]; language? }
```
Bir sağlayıcı eval'a girebilmek için bu sözleşmeyi (partial+final, segment confidence, 8 kHz,
dil/lehçe konfig, phrase boost) karşılamalıdır; karşılamayan yetenek ilgili ölçütte sıfır alır.

## 3. Değerlendirme ölçütleri ve ağırlıkları
Doğruluk ve gecikme birincil; karar için ağırlıklı rubrik:

| # | Ölçüt | Ağırlık | Nasıl ölçülür | İz |
|---|-------|--------:|----------------|-----|
| C1 | **Final-transcript gecikmesi** (P95) | 20% | harness `score` → SAD §20 kapısı | NFR 10.1, SAD §20 |
| C2 | **Doğruluk — WER** (EN+TR; en-kötü-dil) | 25% | harness WER (Levenshtein) | FR-STT-002/003 |
| C3 | **Yapısal alan doğruluğu — CER** (telefon/plaka/poliçe/referans) | 15% | harness CER | FR-STT-005 |
| C4 | **Streaming partial/final doğruluğu** | 10% | harness yapı kontrolü | FR-STT-002 |
| C5 | **Confidence kapsama + kalibrasyon** | 10% | harness (kapsama, ayrım, ECE) | FR-STT-006/007 |
| C6 | **Dil/lehçe kapsaması** (en az EN+TR) | 5% | config + WER per-dil | FR-STT-003 |
| C7 | **Phrase boosting / domain vocab** | 5% | yetenek + öncesi/sonrası | FR-STT-004 |
| C8 | **8 kHz native · residency · no-train** | 10% | config inceleme | FR-RES-008, NFR 10.7, FR-KB-010 |

> C1–C5 harness ile **sayısal** ölçülür; C6–C8 yetenek/uygunluk. Sayısal **knock-out kapıları**:
> C1 (gecikme), C2 (WER), C3 (CER) — herhangi biri **KIRMIZI** ise aday elenir. C4/C5 fail de eler.
> Maliyet/sözleşme ağırlığı **0.2.6**'da bütünsel uygulanır.

## 4. Metrik tanımları
- **WER** (Word Error Rate) = kelime düzenleme mesafesi (Levenshtein: ekle/sil/değiştir) / referans
  kelime sayısı. Normalize: küçük harf + noktalama temizliği; **Türkçe-duyarlı** küçük harf (I→ı, İ→i).
  Kapı **en-kötü-dil** üzerinden (EN+TR zorunlu, SR-STT-003 — zayıf dili genel ortalama maskelemesin).
- **CER** (Character Error Rate) = karakter düzenleme mesafesi / referans karakter sayısı; yapısal
  alanlarda (telefon/plaka/poliçe/referans) boşluk/biçim-duyarsız (FR-STT-005, ör. `34 ABC 123 ≡ 34abc123`).
- **Final-transcript gecikmesi** = `final.t_ms − speech_end_ms` (end-of-utterance → final flush).
  SAD §20 STT kalemi.
- **Partial/final yapısı** = akışta ≥1 partial (isFinal=false), tek kararlı final (isFinal=true),
  partial final'dan önce, zaman damgaları monoton (FR-STT-002).
- **Confidence kalibrasyonu** = (i) **kapsama**: her segmentte confidence var mı (FR-STT-006); (ii)
  **ayrım**: doğru turların ortalama confidence'ı yanlışlardan yüksek mi (FR-STT-007 teyit temeli);
  (iii) **ECE** (Expected Calibration Error): |ortalama-confidence − doğruluk| bin-ağırlıklı.

## 5. Kabul kapıları (gate) — mühendislik varsayılanı
| Ölçüt | Kapı (pass) | Yeşil bant |
|-------|-------------|------------|
| C1 final-transcript P95 | **≤ 200 ms** (SAD §20 üst) | ≤ 100 ms |
| C2 WER (en-kötü-dil) | **≤ 0.15** | ≤ 0.08 |
| C3 yapısal CER | **≤ 0.05** | ≤ 0.02 |
| C4 partial/final | **%100 yapı geçer** | — |
| C5 confidence | **kapsama %100 + ayrım > 0** | — |

> Eşikler **mühendislik varsayılanı**; gerçek değerler **0.3.x PoC**'ta telefoni koşullarında (8 kHz,
> gürültü/aksan — 18.7 test seti) doğrulanır ve gerekirse use-case bazında sıkılaştırılır. `score`
> bütçe kapısı geçilmezse çıkış kodu `1` → CI/0.4.4 hattında gate.

## 6. Ölçüm metodolojisi (harness)
`stt_eval_probe.py` (stdlib-only) üç mod sunar:

| Mod | İş |
|-----|----|
| `score` | Bir sağlayıcı **utterance test setini** (referans+hipotez+olay akışı+confidence) puanlar: WER/CER, gecikme P50/P95/P99, partial/final yapı, confidence kalibrasyon + bütçe kapısı → çıkış kodu |
| `compare` | Çok sağlayıcılı `score` çıktısını markdown karşılaştırma matrisine indirir |
| `selftest` | Credential'sız çekirdek doğrulama (WER/CER/gecikme/kalibrasyon/partial-final birim kontrolleri) |

**Örnek (sample) şeması:** her sağlayıcı için bir test seti JSON — `utterances[]` (her biri:
`language`, `field_type ∈ {general,phone,plate,policy,reference}`, `reference`, `hypothesis`,
`confidence`, `speech_end_ms`, `events[]` partial/final akışı). Detaylı şema `stt_eval_probe.py`
başlığında.

**Canlı PoC akışı (credential gerektiğinde):** STT adapter, 8 kHz telefoni ses örneklerini (sentetik
test verisi — FR-TST-008, gerçek müşteri verisi yok) sağlayıcıya akıtır; dönen `Transcript` olayları
(partial/final + confidence + timestamp) yukarıdaki sample şemasına yazılır; `score` çalıştırılır.
Sağlayıcı API anahtarı **ortam değişkeni** ile geçilir, **dosyaya yazılmaz** (`.gitignore`: `.env*`,
`secrets/`).

## 7. Karşılaştırma matrisi (İLLÜSTRATİF profillerle)
Aşağıdaki tablo `samples/` altındaki **illüstratif** sağlayıcı profillerinden harness ile üretilmiştir.
**Bunlar gerçek sağlayıcı benchmark'ı değildir**; metodolojiyi ve kapıları göstermek içindir. Gerçek
değerler 0.3.x canlı PoC'ta her sağlayıcı için ölçülüp buraya işlenecektir.

| Sağlayıcı | WER EN | WER TR | CER yapısal | Final P95 (ms) | Conf ayrım | P/F ok% | Karar |
|---|---|---|---|---|---|---|---|
| stt-cloud-A | 0.0 | 0.0667 | 0.0 | 138.0 | 0.3238 | 100 | 🟡 SARI |
| stt-cloud-B | 0.0556 | 0.175 | 0.0505 | 188.0 | 0.0895 | 100 | 🔴 KIRMIZI |
| stt-cloud-C-degraded | 0.1111 | 0.125 | 0.1818 | 445.5 | 0.05 | 75 | 🔴 KIRMIZI |

> Kapılar: final P95 ≤ 200 ms (SAD §20, yeşil ≤ 100); WER ≤ 0.15 (yeşil ≤ 0.08); yapısal CER ≤ 0.05
> (yeşil ≤ 0.02). Yeniden üret:
> `python3 docs/vendor-eval/stt_eval_probe.py score samples/<x>.json --out /tmp/<x>.json` → `compare`.

**Matrisin gösterdiği** (illüstratif): **A** tüm kapıları geçer (gecikme sarı bantta → bütünsel SARI);
**B** TR WER (0.175 > 0.15) ve yapısal CER (0.0505 > 0.05) kapısında elenir — EN güçlü ama **TR zayıf**,
en-kötü-dil kapısı bunu yakalar; **C** dar-bant-zayıf (8 kHz desteği yok → yüksek WER), final-flush
gecikmesi bütçeyi aşar, yapısal CER kötü ve bir utterance'ta **partial yok** (FR-STT-002 ihlali).

## 8. Bulgular ve öneri (sağlayıcı-nötr)
1. STT, uçtan uca gecikme bütçesinin (NFR 10.1: P95 ≤ 1.200 ms) ve **doğruluğun** kritik bileşenidir;
   yanlış transkript → yanlış intent/işlem (BRD §11 risk tablosu). Bu yüzden ölçüt seti **gecikme +
   doğruluk + confidence kalibrasyonu**nu birlikte kapsar.
2. **TR performansı bağımsız ölçülmeli:** Çoğu sağlayıcı EN'de güçlüdür; TR (ve telefoni 8 kHz) ayrı
   doğrulanmazsa kalite yanıltıcı görünür. Kapı **en-kötü-dil** üzerinden uygulanır (SR-STT-003).
3. **Yapısal alanlar (telefon/plaka/poliçe/referans)** ayrı CER ile ölçülür (FR-STT-005); phrase
   boosting (FR-STT-004) öncesi/sonrası etkisi PoC'ta nicelenir.
4. **Confidence yalnız üretilmeli değil, ayırt edici olmalı** (FR-STT-006 → FR-STT-007): düşük
   confidence hataları öngörmüyorsa teyit turu tetikleyici güvenilmez. Kalibrasyon (ayrım + ECE) ölçülür.
5. **ADR-002 gereği ≥2 sağlayıcı + fallback (FR-STT-008):** en az iki kapı-geçen aday hedeflenir;
   biri birincil, diğeri fallback (4.3.1). **no-train / dataRetention=NONE** (FR-KB-010) ön koşul.
6. **Karar 0.2.6'ya bırakılır** (vendor-neutral): bu görev ölçüt + metodoloji + kapıyı sağladı;
   sayısal sıralama canlı PoC ölçümleri gelince netleşir.

## 9. Açık konular / sonraki adımlar
- [ ] Canlı PoC: her aday için 8 kHz telefoni sentetik test setiyle (FR-TST-008) gerçek WER/CER/gecikme
      ölç (0.3.1/0.3.2 ile birlikte); 18.7 gürültü/aksan/düşük-hat seti dahil.
- [ ] Phrase boosting (FR-STT-004) öncesi/sonrası WER farkını niceleyen A/B ölçümü ekle.
- [ ] Lehçe (en-GB, en-US, tr-TR) ve kod-değişimi (FR-RTC-012) senaryolarını test setine ekle.
- [ ] `score` gate'ini 0.4.4 CI hattına bağla (regresyon: prompt/profil değişiminde WER kaymasını yakala).
- [ ] Sonuçları 0.2.6 karar raporu girdisine (maliyet + residency + DPA/no-train) bağla; fallback
      eşleştirmesini (4.3.1) belirle.

## 10. İzlenebilirlik
- **Kaynak:** ADR-002 (vendor-neutral, ≥2 sağlayıcı + fallback); SAD §8.1 (SttAdapter SPI), §20 (gecikme bütçesi).
- **FR:** FR-STT-001..008 (sağlayıcı, partial/final, dil/lehçe, phrase boost, yapısal alan, confidence, teyit, fallback), FR-RES-008 (8 kHz/transcode kaçınma), FR-KB-010 (no-log), FR-RTC-013/ADR-005 (endpointing).
- **SR:** SR-STT-001..008 (SRS §4.6).
- **NFR:** 10.1 (P95 ≤ 1.200 ms; STT final alt-kalem ~100–200 ms), 10.7 (residency).
- **WBS:** 0.2.2 (bu); girdi → 0.2.6 (karar), 0.3.1/0.3.2 (PoC ölçüm), 4.2.1/4.2.2 (STT adapter uygulaması), 4.3.1 (fallback), 18.7 (gürültü/aksan test seti).
