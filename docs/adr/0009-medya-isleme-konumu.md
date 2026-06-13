---
adr: ADR-009
title: Medya işleme konumu (edge vs merkez)
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
consulted: Pilot/PoC ekibi
tags: [media, latency, density]
supersedes:
superseded-by:
iz: SAD §6.4/§20/§23; NFR 10.1, NFR 10.2; ADR-003, ADR-005; WBS 0.3.4
---

# ADR-009 — Medya işleme konumu (edge vs merkez)

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md). (Açık → Kabul; kapanış kriteri 0.3.4 ile karşılandı.)

## Bağlam ve Problem
RTP/medya sonlandırma, codec ve ön-işlemenin (VAD/endpointing, barge-in algılama) **edge'de mi yoksa
merkezde mi** yapılacağı, gecikme (NFR 10.1) ile density/kaynak (NFR 10.2) arasında doğrudan bir
ödünleşimdir. Edge gecikmeyi azaltır ama dağıtık karmaşıklık ve kaynak dağılımı getirir; merkez
basittir ama ek ağ gidiş-dönüşü ekler. Karar, **0.3.4 medya işleme konumu deneyi** çıktısına
bağlanmıştı (bkz. `docs/poc/media-placement.md`).

## Karar Sürücüleri
- Gecikme bütçesi (NFR 10.1) — özellikle **barge-in kesme ≤200ms** (ADR-005) — vs density/çağrı-başı
  kaynak (NFR 10.2); operasyonel basitlik, maliyet, residency esnekliği (NFR 10.7).

## Değerlendirilen Seçenekler
1. **Edge medya işleme.** Medya bölgesel POP'ta sonlandırılır; ayrı katman. En düşük gecikme; dağıtık
   operasyon, yüksek ops karmaşıklığı/maliyet, residency POP yayılımıyla zorlaşır.
2. **Merkezi medya işleme.** Tüm medya merkezde + orkestratöre eş-konumlu. Basit/ucuz operasyon; ama
   WAN gidiş-dönüşü **barge-in kesmeyi ≤200ms kapısının üstüne** çıkarır ve eş-konumlu medya CPU'su
   density'yi düşürür.
3. **Hibrit (VAD/endpointing + barge-in edge — ağır medya ayrı/eş-konumsuz katman).** ADR-005 ile
   uyumlu denge; barge-in hızlı, density korunur, ops karmaşıklığı edge'den düşük.

## Karar
**Seçenek 3 — Hibrit.** Gecikmeye-duyarlı hafif iş (VAD/endpointing + barge-in algılama) **edge'de**
yapılır (ADR-005 ile zaten zorunlu); ağır/durumlu medya işleme (transcode, kayıt tap, ağır gürültü/echo)
**ayrı bölgesel medya-gateway katmanında** tutulur — Conversation Orchestrator worker'ına **eş-konumlu
değil** (büyük medya tamponları Media Gateway'de; SAD §6/§13).

0.3.4 deneyi (`docs/poc/media_placement_probe.py`, illüstratif profiller) bu seçimi destekler:
**merkez** topoloji barge-in kesmeyi ~266ms'e çıkararak NFR 10.1 kapısından **elenir** (ADR-005'i
doğrular); **edge** ve **hibrit** her iki HARD kapıyı (NFR 10.1 + NFR 10.2) geçer, ancak **hibrit**
operasyonel basitlik + maliyet + residency boyutlarında üstün olduğundan ağırlıklı karar matrisinde
en yüksek skoru alır (hibrit 0.605 > edge 0.486).

## Sonuçlar
**Olumlu**
- Barge-in kesme ≤200ms (ADR-005) edge VAD ile garanti; e2e P95 ≤1200ms ve density ≥250–500 (medya
  ayrı katmanda → orkestratör density'si korunur) birlikte sağlanır.
- Ağır medya konsolidasyonu, full-edge'e göre operasyonel karmaşıklığı ve maliyeti azaltır; residency
  kontrolleri merkezi/bölgesel medya katmanında uygulanabilir (NFR 10.7).

**Olumsuz / Ödünleşim**
- Edge (hafif VAD) + ayrı medya katmanı iki bileşenli bir veri düzlemi gerektirir; full-merkez kadar
  basit değildir. Edge POP'un bölgesel kapsamı ve gerçek WAN barge-in gidiş-dönüşü **canlı pilotta**
  (0.3.5 + telemetri) doğrulanmalıdır; illüstratif profiller kapı/karar mantığını sabitler, mutlak
  sayıları değil.

## İzlenebilirlik
- **Kaynak gereksinim:** NFR 10.1/10.2; SAD §6.4/§20/§23; NFR 10.7.
- **Doğrulayan deney:** WBS 0.3.4 — `docs/poc/media-placement.md`, `docs/poc/media_placement_probe.py`,
  `docs/poc/samples/media-{edge,central,hybrid}.json`.
- **Etkilenen WBS:** 2.2.x (Real-time media gateway), 2.1.x (Telephony edge).
- **İlişkili ADR'ler:** ADR-003 (hot-path runtime), ADR-005 (edge VAD/endpointing), ADR-004 (plane ayrımı).

## Notlar
Karar değişirse (canlı pilot ölçümü farklı çıkarsa) bu kayıt değiştirilmez; yeni bir ADR açılır ve bu
ADR `superseded-by` ile işaretlenir (bkz. `docs/adr/README.md`).
