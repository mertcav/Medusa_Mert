# Telekom Sağlayıcı Değerlendirmesi — Medya Streaming Gecikmesi

| Alan | Değer |
|------|-------|
| **WBS** | 0.2.1 |
| **Faz · Öncelik** | F0 · Must |
| **İz** | ADR-002; FR-TEL-001/002/003; FR-RTC-001/002; FR-RES-008; NFR 10.1; SAD §7.2, §20 |
| **Durum** | v1.0 — ölçüt + metodoloji + harness hazır; **canlı PoC ölçümü 0.3.x'te** |
| **Tarih** | 2026-06-13 |

> **Sağlayıcı-nötr (ADR-002):** Bu doküman bir sağlayıcı **seçmez**. Twilio / Telnyx / ham SIP'i
> *entegrasyon modu* olarak ölçüt ve metodoloji üzerinden ele alır. Nihai seçim **0.2.6** karar
> raporunda (gecikme + maliyet + residency + DPA + risk) bütünsel yapılır.

---

## 1. Kapsam ve amaç
Telefoni medyasının (ses) bizim **Media Gateway**'imize ulaşma yolundaki **streaming taşıma
gecikmesini** sağlayıcı/entegrasyon modu bazında ölçmek ve **SAD §20 gecikme bütçesi**ndeki
*Ağ/medya* kalemine (P95 **~50–100 ms**) göre kapı (gate) uygulamak. Bu kalem, uçtan uca
P95 ≤ 1.200 ms (NFR 10.1) hedefinin alt bileşenidir; medya taşıması bütçeyi aşarsa STT/LLM/TTS ne
kadar hızlı olursa olsun hedef tutmaz.

Kapsam **dışı** (ilgili ama ayrı görevler): STT/TTS/LLM gecikmesi (0.2.2–0.2.4), SBC güvenliği
(2.1.1), medya işleme konumu kararı (ADR-009 → 0.3.4), density (0.3.3).

## 2. Değerlendirilen entegrasyon modları
Telefoni soyutlaması (SAD §7.2) iki büyük mimari sınıf + bir hibrit tanır. Medya streaming
gecikmesi bu mimariye göre değişir:

| Mod | Açıklama | Medya taşıma | Tipik adaylar | İz |
|-----|----------|--------------|----------------|-----|
| **M1 — Managed CPaaS (WS)** | Sağlayıcı PSTN'i sonlandırır, sesi **WebSocket** (Media Streams / Media Streaming) ile bize akıtır; base64 μ-law/PCM "media" mesajları | Sağlayıcı bulutu → WS → bizim GW | Twilio Media Streams, Telnyx Media Streaming | FR-TEL-001 |
| **M2 — Ham SIP trunk + RTP (BYOC)** | Kendi SBC'miz SIP/RTP sonlandırır; medya doğrudan RTP | Trunk → SBC → RTP → bizim GW | BYOC SIP trunk sağlayıcıları | FR-TEL-002 |
| **M3 — CC entegrasyonu** | Avaya/Genesys/Cisco/Amazon Connect arkasından medya | Platforma bağlı | Mevcut müşteri CC'leri | FR-TEL-003 |

**Gecikme açısından beklenti (PoC'ta doğrulanacak):**
- **M2 (ham RTP)** genelde **en düşük** taşıma gecikmesini verir (ekstra bulut sıçraması yok), fakat
  medya hattı + SBC operasyon yükü **bizde**dir ve medya işleme konumu (ADR-009) kararını etkiler.
- **M1 (WS)** entegrasyon hızını ve operasyon kolaylığını artırır; ek bir bulut sıçraması ve WS
  framing yükü getirir. Aynı-bölge seçimi ve persistent WS bağlantısı ile bütçe içinde kalması beklenir.
- **M3** platforma bağımlıdır; F2 kapsamı.

## 3. Medya gecikmesinin bileşenleri
```
PSTN ──► Carrier ──► [Sağlayıcı medya köprüsü] ──► (WS / RTP taşıma) ──► Media Gateway ──► Orchestrator
                                                     └── bu görevin ölçtüğü kalem ──┘
```
Ölçülen büyüklük: bir medya çerçevesinin **bizim GW'imize varış** gecikmesi (tek-yön, P95) ve
gidiş-dönüş (RTT, çift-yön bağlantıda). Telefoni gerçeğine sadık çerçeveleme: **8 kHz, 20 ms
çerçeve (50 fps), G.711 μ-law (160 bayt/çerçeve)** — gereksiz resample/transcode zincire sokulmaz
(FR-RES-008). Barge-in (FR-RTC-002) çift-yönlü, düşük-jitter medya gerektirdiğinden jitter ve
paket kaybı da ölçülür.

## 4. Değerlendirme ölçütleri ve ağırlıkları
Gecikme birincil ama tek ölçüt değil. Karar için ağırlıklı rubrik:

| # | Ölçüt | Ağırlık | Nasıl ölçülür | İz |
|---|-------|--------:|----------------|-----|
| C1 | **Medya taşıma gecikmesi** (tek-yön P95) | 30% | harness `probe`/`stats` → SAD §20 kapısı | NFR 10.1, SAD §20 |
| C2 | **Jitter & paket kaybı** | 15% | harness (jitter ms, loss %) | FR-RTC-001 |
| C3 | **Barge-in / çift-yön streaming** (cancel, ≤200ms kesme yeteneği) | 15% | mod yeteneği + PoC | FR-RTC-002 |
| C4 | **8 kHz native / transcode kaçınma** | 10% | codec inceleme | FR-RES-008 |
| C5 | **BYOC / SIP trunk esnekliği** | 10% | mod yeteneği | FR-TEL-002 |
| C6 | **Bölgesel / residency uygunluk** | 10% | bölge listesi | NFR 10.7 |
| C7 | **Dayanıklılık** (reconnect, fallback, DTMF RFC2833/INFO) | 5% | mod yeteneği + PoC | FR-TEL-006, ADR-002 |
| C8 | **Maliyet modeli & gözlemlenebilirlik** | 5% | rate-card + metrik kancaları | FR-BIL-002, SAD §17 |

> C3–C8 yetenek/uygunluk; C1–C2 sayısal ölçüm. Sayısal kapı **C1**'dir: aşan aday eler (knock-out),
> kalanlar ağırlıklı skorla sıralanır. Maliyet/sözleşme ağırlığı **0.2.6**'da bütünsel uygulanır.

## 5. Ölçüm metodolojisi (harness)
`media_latency_probe.py` (stdlib-only) dört mod sunar:

| Mod | İş |
|-----|----|
| `serve` | Yerel WebSocket **echo** sunucusu — credential olmadan loopback self-test / PoC köprüsü taklidi. `--delay-ms` ile sabit tek-yön gecikme senaryosu |
| `probe` | WS ucuna 8 kHz/20 ms (50 fps) medya akıtır; frame'i seq ile etiketler, **frame-RTT** ölçer |
| `stats` | Ham RTT örneklerinden P50/P95/P99, jitter, kayıp, **MOS-vekil**, bütçe kapısı türetir |
| `compare` | Çok sağlayıcılı sonuçları markdown karşılaştırma matrisine indirir |

**Mesaj biçimi** Twilio/Telnyx Media Streams "media" JSON'unu taklit eder (`event:"media"`,
`media.payload` base64). `binary` modu ham RTP-benzeri çerçeve.

**Canlı PoC akışı (credential gerektiğinde):** sağlayıcı çağrıyı bizim **WS köprümüze** bağlar;
köprü gelen medya mesajını işaretleyip echo eder; `probe` köprü ucuna bağlanıp ölçer. Sağlayıcı
auth token'ı **ortam değişkeni** ile geçilir, dosyaya yazılmaz (`.gitignore`: `.env*`, `secrets/`).

**Kabul kapısı (gate):**
- C1 **tek-yön medya P95 ≤ 100 ms** → geçer (kapı). **≤ 50 ms** → yeşil bant.
- Hedef: paket kaybı **< %1**, jitter **< 30 ms** (barge-in kalitesi için).
- `probe`/`stats` çıkış kodu kapı geçilmezse `1` → CI/0.4.4 hattında gate.

## 6. Karşılaştırma matrisi (İLLÜSTRATİF profillerle)
Aşağıdaki tablo `samples/` altındaki **illüstratif** entegrasyon-modu profillerinden harness ile
üretilmiştir. **Bunlar gerçek sağlayıcı benchmark'ı değildir**; metodolojiyi ve kapıyı göstermek
içindir. Gerçek değerler 0.3.x canlı PoC'ta her sağlayıcı için ölçülüp buraya işlenecektir.

| Sağlayıcı / mod | RTT P50 | RTT P95 | RTT P99 | Tek-yön P95 | Jitter | Kayıp % | MOS-vekil | Kapı |
|---|---|---|---|---|---|---|---|---|
| managed-cpaas-ws-A (M1) | 47.0 | 51.0 | 52.51 | 25.5 | 1.18 | 0.0 | 4.4 | 🟢 YEŞİL |
| managed-cpaas-ws-B (M1) | 65.0 | 74.6 | 79.04 | 37.3 | 3.03 | 2.0 | 3.64 | 🟢 YEŞİL |
| raw-sip-rtp-byoc (M2) | 31.0 | 36.0 | 39.02 | 18.0 | 1.52 | 0.0 | 4.4 | 🟢 YEŞİL |

> Kapı: tek-yön P95 ≤ 100 ms (SAD §20); yeşil bant ≤ 50 ms. Yeniden üret:
> `python3 docs/vendor-eval/media_latency_probe.py stats samples/<x>.json` → `compare`.

## 7. Bulgular ve öneri (sağlayıcı-nötr)
1. **Üç entegrasyon modu da** illüstratif aynı-bölge koşullarında medya taşıma bütçesini (C1) rahat
   geçiyor; bu kalem genelde uçtan uca bütçenin (1.200 ms) küçük bir dilimidir. Asıl bütçe baskısı
   STT+LLM+TTS'tedir (0.2.2–0.2.4).
2. **M2 (ham SIP/RTP)** en düşük taşıma gecikmesini vaat eder; bedeli SBC + medya hattı operasyon
   yükü ve **ADR-009 (medya işleme konumu)** ile sıkı bağ. **M1 (managed WS)** entegrasyon hızı +
   düşük operasyon yükü verir, küçük ek gecikme/WS framing maliyetiyle.
3. **ADR-002 gereği ≥2 sağlayıcı + fallback** korunmalı: pratikte **en az bir M1 (managed) + M2
   (BYOC) yeteneği** birlikte hedeflenir (ticari pazarlık + residency + kesinti dayanıklılığı).
4. **Karar 0.2.6'ya bırakılır** (vendor-neutral): bu görev ölçüt + metodoloji + kapıyı sağladı;
   sayısal sıralama canlı PoC ölçümleri gelince netleşir.

## 8. Açık konular / sonraki adımlar
- [ ] Canlı PoC: her aday için gerçek WS/RTP köprüsüyle C1/C2 ölç (0.3.1/0.3.2 ile birlikte).
- [ ] `wss://` (TLS) için harness'e proxy/TLS desteği (PoC köprüsü TLS sonlandırır; mevcut araç `ws://` loopback).
- [ ] Bölgeler-arası (cross-region) senaryo ölçümü (residency kısıtı olan tenant'lar için).
- [ ] Sonuçları **ADR-009** girdisi olarak medya işleme konumu deneyine (0.3.4) bağla.
- [ ] C3–C8 yetenek matrisini sağlayıcı dokümanlarından doldur (0.2.6 karar raporu girdisi).

## 9. İzlenebilirlik
- **Kaynak:** ADR-002 (vendor-neutral, ≥2 sağlayıcı + fallback); SAD §7.2 (telefoni soyutlaması), §20 (gecikme bütçesi).
- **FR:** FR-TEL-001/002/003 (PSTN, BYOC, CC), FR-RTC-001/002 (streaming, barge-in), FR-RES-008 (transcode kaçınma).
- **NFR:** 10.1 (P95 ≤ 1.200 ms; medya alt-kalem ≤ 100 ms), 10.7 (residency).
- **WBS:** 0.2.1 (bu); girdi → 0.2.6 (karar), 0.3.1/0.3.2 (PoC ölçüm), 0.3.4/ADR-009 (medya konumu), 2.1.3/2.2.x (uygulama).
