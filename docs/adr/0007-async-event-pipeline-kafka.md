---
adr: ADR-007
title: Async event pipeline (Kafka) ile post-processing
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [eventing, kafka, async, analytics]
supersedes:
superseded-by:
iz: FR-RES-011; SAD §12.1; WBS 1.1.8
---

# ADR-007 — Async event pipeline (Kafka) ile post-processing

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Transkripsiyon sonrası analitik, QA değerlendirme, PII redaction, faturalama ölçümü ve raporlama
gibi işler gerçek zamanlı değildir ve hot path'te yapılırsa gecikme/density'i bozar.

## Karar Sürücüleri
- Hot path'i non-RT işlerden arındırmak (FR-RES-011); replay/dayanıklılık; düzlemler arası gevşek bağ.

## Değerlendirilen Seçenekler
1. **Senkron post-processing.** Basit; hot path'i ağırlaştırır, kayıp riski.
2. **Kuyruk (basit)** — replay yok.
3. **Event stream (Kafka) + replay.** Dayanıklı, yeniden işlenebilir, ölçeklenir.

## Karar
**Seçenek 3** kabul edildi. Çağrı olayları bir **event stream (Kafka)** topic tasarımına yazılır;
analitik/QA/redaction/billing tüketicileri async çalışır ve gerekince **replay** edilebilir.

## Sonuçlar
**Olumlu**
- Hot path hafif kalır; non-RT işler bağımsız ölçeklenir; replay ile yeniden işleme.

**Olumsuz / Ödünleşim**
- Eventual consistency; topic/şema yönetimi ve operasyonel altyapı maliyeti.

## İzlenebilirlik
- **Kaynak gereksinim:** FR-RES-011; SAD §12.1.
- **Etkilenen WBS:** 1.1.8, 14.x, 16.7.
- **İlişkili ADR'ler:** ADR-004 (plane ayrımı).
