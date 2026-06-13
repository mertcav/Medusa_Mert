---
adr: ADR-004
title: Data / Control / Analytics plane ayrımı
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [architecture, planes, scalability]
supersedes:
superseded-by:
iz: SAD §4.2; FR-RES-011
---

# ADR-004 — Data / Control / Analytics plane ayrımı

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Gerçek zamanlı voice runtime (hot path) ile yönetim/analitik iş yükleri çok farklı gecikme ve ölçek
profiline sahiptir. Bunları aynı süreçte/serviste karıştırmak hot path'i ağırlaştırır ve density'i bozar.

## Karar Sürücüleri
- Hot path'i hafif tutmak (FR-RES-011); bağımsız ölçeklenme; hata izolasyonu.

## Değerlendirilen Seçenekler
1. **Monolit (tek düzlem).** Basit ama hot path analitik/yönetim yüküyle çakışır.
2. **Data + Control/Analytics plane ayrımı.** Gerçek zamanlı işler ayrı; non-RT işler async.

## Karar
**Seçenek 2** kabul edildi. **Data plane** (voice runtime), **Control plane** (yönetim/panel backend)
ve **Analytics plane** (post-processing/raporlama) ayrılır. Non-RT işler async pipeline'a (bkz. ADR-007)
itilir; hot path yalnız gerçek zamanlı görevleri taşır.

## Sonuçlar
**Olumlu**
- Bağımsız ölçekleme; hot path density korunur; blast-radius daralır.

**Olumsuz / Ödünleşim**
- Daha fazla servis/operasyonel yüzey; düzlemler arası sözleşme ve veri akışı yönetimi gerekir.

## İzlenebilirlik
- **Kaynak gereksinim:** SAD §4.2; FR-RES-011.
- **Etkilenen WBS:** 0.4.1 (repo yapısı), 3.x, 14.x.
- **İlişkili ADR'ler:** ADR-003, ADR-007, ADR-011 (panel düzlemi ayrımıyla uyumlu).
