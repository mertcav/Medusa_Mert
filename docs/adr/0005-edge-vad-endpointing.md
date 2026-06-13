---
adr: ADR-005
title: Edge VAD / endpointing
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [media, latency, vad]
supersedes:
superseded-by:
iz: FR-RTC-013, FR-RTC-004, FR-RES-009; NFR 10.1
---

# ADR-005 — Edge VAD / endpointing

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Konuşma sınırlarının (söz başı/sonu) ne zaman ve nerede algılanacağı hem gecikmeyi hem kaynak
tüketimini doğrudan etkiler. Endpointing'i merkezde yapmak ağ gidiş-dönüşü ekler ve gereksiz medya
akışı (ölü hava dahil) taşır.

## Karar Sürücüleri
- Gecikme bütçesi (NFR 10.1, barge-in ≤200ms); gereksiz STT/ağ kaynağını azaltma (FR-RES-009).

## Değerlendirilen Seçenekler
1. **Merkezi VAD/endpointing.** Basit dağıtım; ek gecikme, fazla akış.
2. **Edge VAD/endpointing.** Sınır tespiti medya kenarında; sessizlik erken kesilir.

## Karar
**Seçenek 2** kabul edildi. VAD/endpointing **edge'de** (media gateway yakınında) ve dinamik yapılır;
böylece barge-in tepkisi hızlanır ve STT'ye gönderilen gereksiz medya azalır.

## Sonuçlar
**Olumlu**
- Düşük gecikme; daha az STT/ağ tüketimi; daha iyi barge-in.

**Olumsuz / Ödünleşim**
- Edge bileşeninde ek karmaşıklık; medya işleme konumu (ADR-009) ile etkileşir.

## İzlenebilirlik
- **Kaynak gereksinim:** FR-RTC-013/004, FR-RES-009; NFR 10.1.
- **Etkilenen WBS:** 2.2.3, 2.2.7.
- **İlişkili ADR'ler:** ADR-009 (medya işleme konumu — açık).
