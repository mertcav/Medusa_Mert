---
adr: ADR-006
title: Tenant izolasyonu — shared (RLS) + dedicated opsiyon
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [multi-tenancy, isolation, security]
supersedes:
superseded-by:
iz: FR-TEN-002, FR-TEN-005; SAD §13.1; DB.md (RLS)
---

# ADR-006 — Tenant izolasyonu: shared (RLS) + dedicated opsiyon

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
B2B2B platformda çoğu tenant maliyet-etkin paylaşımlı altyapı ister; bazı regüle/yüksek-hacimli
tenant'lar ise fiziksel/mantıksal ayrıştırma (residency, performans, uyum) talep eder.

## Karar Sürücüleri
- Cross-tenant veri sızıntısının önlenmesi (FR-TEN-002); maliyet-etkinlik; regüle tenant ihtiyacı.

## Değerlendirilen Seçenekler
1. **Yalnız shared (RLS).** Ucuz; regüle/dedicated taleplerini karşılamaz.
2. **Yalnız dedicated.** Güçlü izolasyon; maliyet ve operasyon ağır.
3. **Shared (RLS) varsayılan + dedicated opsiyon.** İki ihtiyaç birlikte.

## Karar
**Seçenek 3** kabul edildi. Varsayılan **shared** model her tabloda `tenant_id` + **Row-Level Security**
ile izole edilir; talebe göre **dedicated** (ayrı şema/altyapı) sunulur (FR-TEN-005).

## Sonuçlar
**Olumlu**
- Maliyet-etkin ölçek + regüle tenant için güçlü izolasyon seçeneği.

**Olumsuz / Ödünleşim**
- İki dağıtım modelini desteklemek operasyonel karmaşıklık; RLS politikaları her tabloda titizlik ister.

## İzlenebilirlik
- **Kaynak gereksinim:** FR-TEN-002/005; SAD §13.1; DB.md RLS politikaları.
- **Etkilenen WBS:** 1.1.1, 1.2.1, 12.4.2.
- **İlişkili ADR'ler:** ADR-011 (panel/plane), ADR-013 (break-glass).
