---
adr: ADR-010
title: Self-hosted LLM + GPU kapsamı
status: Açık
date: 2026-06-13
deciders: Mimari ekip
tags: [llm, gpu, cost, open-decision, phase-3]
supersedes:
superseded-by:
iz: FR-RES-015; SAD §23; NFR 10.2
---

# ADR-010 — Self-hosted LLM + GPU kapsamı

> **Durum:** Açık · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Self-hosted LLM (kendi GPU'larımızda) belirli residency/uyum veya maliyet senaryolarında gerekebilir;
ancak GPU CAPEX/OPEX ve operasyon yükü yüksektir. Varsayılan CPU/serverless yaklaşımı density mandasıyla
daha uyumludur.

## Karar Sürücüleri
- Residency/uyum gereksinimleri; maliyet (NFR 10.2); operasyonel yük; Faz 3 kapsamı.

## Değerlendirilen Seçenekler
1. **Hiç self-hosted LLM yok (yalnız managed).** Basit; bazı uyum senaryolarını karşılamaz.
2. **Gerekçeli durumda self-hosted + GPU (Faz 3).** Yalnız ihtiyaç kanıtlanınca.
3. **Geniş self-hosted varsayılan.** Maliyet/operasyon ağır, density'e ters.

## Karar
**AÇIK.** Self-hosted LLM + GPU, yalnız **gerekçeli durumda** ve **Faz 3** kapsamında değerlendirilecek
(FR-RES-015). GPU varsayılan değildir; aksi halde CPU/serverless.

## Sonuçlar
**Olumlu (karar verilince)**
- İhtiyaç kanıtlandığında residency/uyum/maliyet için seçenek açık kalır.

**Olumsuz / Ödünleşim**
- Erken yatırım israf riski; karar Faz 3'e ertelendiği için belirsizlik.

## İzlenebilirlik
- **Kaynak gereksinim:** FR-RES-015; NFR 10.2; SAD §23.
- **Etkilenen WBS:** 16.9 (GPU yalnız gerekince).
- **İlişkili ADR'ler:** ADR-008 (tiering/cache — maliyet hedefi).

## Notlar
**Kapanış kriteri:** Faz 3 girişinde somut bir tenant/uyum gereksinimi + maliyet modeli ile
yeniden değerlendirilir.
