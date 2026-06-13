---
adr: ADR-002
title: Provider Adapter SPI + kategori başına ≥2 sağlayıcı
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [adapter, vendor-neutral, fallback]
supersedes:
superseded-by:
iz: BRD §19; SAD §8.1, §8.2; FR-STT-008, FR-TTS-008, FR-LLM-010, FR-TEL-002
---

# ADR-002 — Provider Adapter SPI + kategori başına ≥2 sağlayıcı

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
STT/TTS/LLM/Telephony sağlayıcıları fiyat, kapsama, gecikme ve bölgesel uygunluk açısından farklılaşır
ve zamanla değişir. Tek sağlayıcıya bağlı kalmak hem ticari hem operasyonel (kesinti) risktir.

## Karar Sürücüleri
- Vendor-neutrality (OBJ-10), tedarikçi pazarlık gücü, bölgesel/residency esnekliği.
- BRD §19 kabul kriteri: kategori başına ≥2 sağlayıcı + fallback.

## Değerlendirilen Seçenekler
1. **Tek sağlayıcı/kategori.** Basit; kilitlenme ve kesinti riski.
2. **Her sağlayıcı için ayrı entegrasyon kodu (SPI yok).** Çoğulluk var ama bakım/kod tekrarı yüksek.
3. **Ortak Adapter SPI + kategori başına ≥2 somut adapter.** Tek sözleşme, fallback standart.

## Karar
**Seçenek 3** kabul edildi. Her kategori için ortak bir **Adapter SPI** tanımlanır; STT/TTS/LLM/Telephony
için en az iki somut adapter ve fallback (bkz. SAD §8.2) zorunludur. Belirli sağlayıcı **seçilmez**
(vendor eval'a tabi).

## Sonuçlar
**Olumlu**
- Sağlayıcı değiştirme/fallback maliyeti düşer; tek hata-noktası ortadan kalkar.
- Ortak yetenekler (timeout/retry/circuit breaker/metering) tek yerde.

**Olumsuz / Ödünleşim**
- SPI, en düşük ortak payda riski taşır; sağlayıcıya özgü ileri özellikler kapsülleme gerektirir.

## İzlenebilirlik
- **Kaynak gereksinim:** BRD §19; SAD §8.1/§8.2; FR-STT-008, FR-TTS-008, FR-LLM-010.
- **Etkilenen WBS:** 4.x (Adapters), 0.2.x (vendor eval).
- **İlişkili ADR'ler:** ADR-001, ADR-008 (tiering/cache).

## Notlar
İlk sağlayıcı önerileri SAD §8.4'te yalnız **örnek**tir; karar 0.2.x vendor eval + PoC ile kesinleşir.
