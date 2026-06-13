---
adr: ADR-009
title: Medya işleme konumu (edge vs merkez)
status: Açık
date: 2026-06-13
deciders: Mimari ekip
consulted: Pilot/PoC ekibi
tags: [media, latency, density, open-decision]
supersedes:
superseded-by:
iz: SAD §23; NFR 10.1, NFR 10.2; ADR-003, ADR-005
---

# ADR-009 — Medya işleme konumu (edge vs merkez)

> **Durum:** Açık · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
RTP/medya sonlandırma, codec ve ön-işlemenin **edge'de mi yoksa merkezde mi** yapılacağı, gecikme
(NFR 10.1) ile density/kaynak (NFR 10.2) arasında doğrudan bir ödünleşimdir. Edge gecikmeyi azaltır
ama dağıtık karmaşıklık ve kaynak dağılımı getirir; merkez basittir ama ek ağ gidiş-dönüşü ekler.

## Karar Sürücüleri
- Gecikme bütçesi (NFR 10.1) vs density/çağrı-başı kaynak (NFR 10.2); operasyonel basitlik.

## Değerlendirilen Seçenekler
1. **Edge medya işleme.** En düşük gecikme; dağıtık operasyon, kaynak dağılımı.
2. **Merkezi medya işleme.** Basit operasyon; ek gecikme.
3. **Hibrit (VAD/endpointing edge — ağır işleme merkez).** ADR-005 ile uyumlu denge.

## Karar
**AÇIK.** Karar bilinçli olarak ertelendi. Seçim, **0.3.4 medya işleme konumu deneyi** (PoC)
çıktısındaki ölçülen gecikme/density dengesine göre verilecektir.

## Sonuçlar
**Olumlu (karar verilince)**
- Gecikme ve density hedefleri ölçüm temelli optimize edilir.

**Olumsuz / Ödünleşim**
- Karar netleşmeden bağımlı görevler (2.2.x medya gateway detayları) kısmen bloke.

## İzlenebilirlik
- **Kaynak gereksinim:** NFR 10.1/10.2; SAD §23.
- **Etkilenen WBS:** 0.3.4 (karar girdisi), 2.2.x.
- **İlişkili ADR'ler:** ADR-003, ADR-005.

## Notlar
**Kapanış kriteri:** 0.3.4 PoC P50/P95/P99 gecikme + oturum/worker density ölçümü tamamlanınca
durum `Kabul`'e geçer ve seçilen seçenek bu kayıtta dondurulur (veya yeni ADR ile değiştirilir).
