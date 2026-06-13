---
adr: ADR-008
title: Model tiering + semantic cache zorunlu
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [llm, cost, tiering, cache]
supersedes:
superseded-by:
iz: NFR 10.2; FR-RES-005, FR-LLM-014, FR-RES-004
---

# ADR-008 — Model tiering + semantic cache zorunlu

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Her turda en büyük modeli çağırmak NFR 10.2 maliyet hedefini karşılamaz. Turların önemli kısmı
rutindir ve küçük modelle (veya cache ile) doğru cevaplanabilir.

## Karar Sürücüleri
- Çağrı-başı maliyet hedefi (NFR 10.2); gecikme; ≥%60 küçük-model tur hedefi (FR-RES-005).

## Değerlendirilen Seçenekler
1. **Tek (büyük) model.** Basit; pahalı, gereksiz yavaş.
2. **Tiering (küçük/büyük) + router.** Maliyet/gecikme optimize.
3. **Tiering + semantic cache.** Ek olarak yan-etkisiz/tekrar eden turlarda LLM atlanır.

## Karar
**Seçenek 3** kabul edildi. **Model tiering** (küçük/büyük + risk/karmaşıklık sınıflandırıcı) ve
**semantic cache** zorunludur. PII cache'lenmez; yalnız yan-etkisiz turlar cache'lenir (FR-RES-004).

## Sonuçlar
**Olumlu**
- Maliyet ve gecikme düşer; density hedefi desteklenir.

**Olumsuz / Ödünleşim**
- Yanlış yönlendirme (router) kalite riski; cache invalidation ve PII sızıntısı kontrolü gerekir.

## İzlenebilirlik
- **Kaynak gereksinim:** NFR 10.2; FR-RES-005, FR-LLM-014, FR-RES-004.
- **Etkilenen WBS:** 5.x (LLM orkestrasyon), 16.1.
- **İlişkili ADR'ler:** ADR-002, ADR-015 (prompt-injection — cache/guard etkileşimi).
