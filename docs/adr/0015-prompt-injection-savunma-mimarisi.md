---
adr: ADR-015
title: Prompt-injection savunma mimarisi (katmanlı)
status: Önerilen
date: 2026-06-13
deciders: Mimari ekip, Güvenlik
tags: [security, llm, prompt-injection]
supersedes:
superseded-by:
iz: THREAT_MODEL.md §10 (TM-T-02b, TM-I-05); FR-LLM-007, FR-LLM-009
---

# ADR-015 — Prompt-injection savunma mimarisi

> **Durum:** Önerilen · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Sesli agent, hem çağrı içeriği hem KB/tool çıktıları üzerinden prompt-injection / jailbreak
(TM-T-02b, TM-I-05) saldırılarına maruzdur. Tek bir guard yeterli değildir; ancak ek LLM-as-judge
guard gecikme/maliyet (NFR 10.1/10.2) bütçesini etkiler.

## Karar Sürücüleri
- Injection/jailbreak savunması (FR-LLM-007/009); gecikme/maliyet bütçesi; KB/tool kaynak güvenirliği.

## Değerlendirilen Seçenekler
1. **Tek output guard.** Basit; tek katman aşılırsa korumasız.
2. **Deterministik katmanlı guard** (input sınıflandırıcı + spotlighting + output guard).
3. **Katmanlı + LLM-as-judge guard.** En güçlü; ek gecikme/maliyet.

## Karar
**Seçenek 2/3 arası katmanlı mimari öneriliyor:** input sınıflandırıcı + spotlighting (kaynak/talimat
ayrımı) + output guard temel; **LLM-as-judge** guard'ın eklenip eklenmeyeceği **PoC ile** gecikme/maliyet
ölçülerek kararlaştırılır. Durum **Önerilen**.

## Sonuçlar
**Olumlu**
- Çok katmanlı savunma; tek nokta zafiyeti azalır.

**Olumsuz / Ödünleşim**
- Ek LLM guard NFR 10.1 gecikme bütçesini zorlayabilir; false-positive ile UX etkisi.

## İzlenebilirlik
- **Kaynak gereksinim:** THREAT_MODEL §10 (TM-T-02b, TM-I-05); FR-LLM-007/009.
- **Etkilenen WBS:** 3.3.1, 3.3.2, 0.3.x (PoC gecikme).
- **İlişkili ADR'ler:** ADR-008 (cache/guard), ADR-014.

## Notlar
**Kapanış kriteri:** 0.3.x PoC'ta ek-LLM guard'ın gecikme/maliyet etkisi NFR 10.1 bütçesine sığıyorsa
kapsama alınır; ölçüm sonrası durum `Kabul`'e geçer.
