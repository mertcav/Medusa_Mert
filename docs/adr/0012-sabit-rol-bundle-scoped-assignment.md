---
adr: ADR-012
title: Sabit rol bundle + scoped assignment; custom roller Faz 3
status: Kabul
date: 2026-06-13
deciders: Mimari ekip, Güvenlik
tags: [rbac, iam, security]
supersedes:
superseded-by:
iz: FR-IAM-011; SAD §14.4.3
---

# ADR-012 — Sabit rol bundle + scoped assignment

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Serbest "custom permission builder" güçlü ama kombinatoryal bir saldırı/yanlış-yapılandırma yüzeyi
yaratır ve audit'i zorlaştırır. Yine de tenant'ların departman/marka/kampanya bazlı esnekliğe ihtiyacı var.

## Karar Sürücüleri
- Yetki kombinasyonu/güvenlik riskini sınırlamak; audit edilebilirlik; tenant esnekliği.

## Değerlendirilen Seçenekler
1. **Tam custom permission builder (v1).** Esnek; kombinatoryal güvenlik/audit riski.
2. **Sabit immutable rol bundle'ları + atama scope filtresi.** Esneklik atamada, yetki sabit.

## Karar
**Seçenek 2** kabul edildi. Roller **immutable permission bundle**'dır; v1'de custom permission-builder
**yoktur**. Esneklik, atamadaki **scope filtresi** (departman/marka/kampanya) ile sağlanır. Tam custom
roller **Faz 3** (enterprise/dedicated, şablonla). Yetki kararı **her zaman backend'de**.

## Sonuçlar
**Olumlu**
- Öngörülebilir, audit edilebilir yetki yüzeyi; yanlış-yapılandırma riski düşük.

**Olumsuz / Ödünleşim**
- Bazı tenant'lar v1'de tam custom rol isteyebilir → Faz 3'e ertelenir.

## İzlenebilirlik
- **Kaynak gereksinim:** FR-IAM-011; SAD §14.4.3.
- **Etkilenen WBS:** 12.1.1, 12.1.3.
- **İlişkili ADR'ler:** ADR-011, ADR-013.
