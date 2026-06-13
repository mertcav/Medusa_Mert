---
adr: ADR-003
title: Hot path'te async, düşük-bellekli dil (Go/Rust)
status: Önerilen
date: 2026-06-13
deciders: Mimari ekip
tags: [runtime, density, performance, data-plane]
supersedes:
superseded-by:
iz: NFR 10.1, NFR 10.2; SAD §21; FR-RES-001, FR-RES-016
---

# ADR-003 — Hot path'te async, düşük-bellekli dil (Go/Rust)

> **Durum:** Önerilen · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Platformun merkezi farklılaşması "oturum başına ~15MB ve worker başına 250–500 eş zamanlı oturum"
yoğunluğudur (NFR 10.2). Aynı anda P95 ≤ 1.2 sn gecikme (NFR 10.1) gerekir. GC-ağır veya
thread-per-call runtime'lar bu density'yi sağlayamaz.

## Karar Sürücüleri
- Density (NFR 10.2) ve gecikme bütçesi (NFR 10.1) birlikte.
- Async/non-blocking, stream-first, düşük ve öngörülebilir bellek.

## Değerlendirilen Seçenekler
1. **Python/Node (panel düzleminde uygun).** Hızlı geliştirme; hot path'te GC/bellek yoğunluğu yetersiz.
2. **JVM (Go-rutinsiz).** Olgun ama bellek ayak izi ve GC duraklamaları density'i zorlar.
3. **Go veya Rust (async, düşük-bellekli).** Density + öngörülebilir gecikme.

## Karar
**Seçenek 3 öneriliyor:** data plane (voice runtime / Conversation Orchestrator) hot path'i **Go veya
Rust** ile yazılır. Bu bir mimari **gerekliliktir**, tercih değil. Nihai Go/Rust seçimi 0.3.5 hot-path
dil doğrulaması (PoC) ile kesinleşeceğinden durum **Önerilen**'dir.

## Sonuçlar
**Olumlu**
- Density ve gecikme hedefleri ulaşılabilir; per-call kaynak bütçesi (~15MB) izlenebilir.

**Olumsuz / Ödünleşim**
- Panel düzleminden (Next.js + FastAPI) farklı dil → ekip beceri çeşitliliği ve iki yığın bakımı.

## İzlenebilirlik
- **Kaynak gereksinim:** NFR 10.1/10.2; FR-RES-001, FR-RES-016; SAD §21.
- **Etkilenen WBS:** 0.3.5, 3.1.x, 16.x.
- **İlişkili ADR'ler:** ADR-001, ADR-004.

## Notlar
**Açık doğrulama:** Go vs Rust nihai kararı 0.3.x PoC density/gecikme ölçümüne bağlı; ölçüm sonrası
durum `Kabul`'e geçirilir.
