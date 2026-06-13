---
adr: ADR-001
title: Bağımsız Conversation Orchestrator (STT/LLM/TTS doğrudan bağlanmaz)
status: Kabul
date: 2026-06-13
deciders: Mimari ekip
tags: [orchestrator, vendor-neutral, core-ip]
supersedes:
superseded-by:
iz: BRD §11, §24; SAD §6; FR-RTC-*, FR-LLM-*
---

# ADR-001 — Bağımsız Conversation Orchestrator

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Sesli agent platformunda STT, LLM ve TTS gerçek zamanlı olarak orkestre edilmek zorundadır.
Bu üç yeteneği birbirine doğrudan zincirleyen (ör. STT çıktısını doğrudan LLM'e, onu doğrudan
TTS'e bağlayan) bir tasarım kısa vadede hızlıdır; ancak turn-taking, barge-in, politika denetimi,
tool çağrısı ve gözlemlenebilirlik gibi ürünün asıl değerini taşıyan mantığın **sağlayıcıya gömülü**
kalmasına yol açar ve vendor-neutrality'i imkânsızlaştırır.

## Karar Sürücüleri
- Vendor-neutrality (BRD §11) ve sağlayıcı değiştirilebilirliği.
- Tutarlı turn-taking/barge-in/policy/observability kontrolü (BRD §24).
- Ürünün fikrî mülkiyetinin (IP) platformda kalması.

## Değerlendirilen Seçenekler
1. **Doğrudan zincirleme (STT→LLM→TTS bağımlı).** Hızlı ama sağlayıcıya kilitler, kontrol zayıf.
2. **Sağlayıcının uçtan uca "voice agent" ürününü kullanmak.** En hızlı ama IP ve kontrol dışarıda.
3. **Bağımsız Conversation Orchestrator.** STT/LLM/TTS yalnız adapter SPI üzerinden bağlanır;
   tüm diyalog mantığı orchestrator'da.

## Karar
**Seçenek 3** kabul edildi. Conversation Orchestrator çekirdek IP'dir; STT/LLM/TTS'e doğrudan
bağlanmaz, yalnız adapter SPI'ları (bkz. ADR-002) üzerinden konuşur. Turn state machine, policy
engine, session memory ve tool yürütme orchestrator'da yaşar.

## Sonuçlar
**Olumlu**
- Vendor-neutrality ve kategori başına çoklu sağlayıcı mümkün olur.
- Politika/gözlemlenebilirlik/handoff tek noktada, tutarlı.

**Olumsuz / Ödünleşim**
- Daha fazla mühendislik; orchestrator hot path performansı kritik hale gelir (bkz. ADR-003).

## İzlenebilirlik
- **Kaynak gereksinim:** BRD §11, §24; SAD §6.
- **Etkilenen WBS:** 3.x (Conversation Orchestrator).
- **İlişkili ADR'ler:** ADR-002 (adapter SPI), ADR-003 (hot path dil), ADR-004 (plane ayrımı).

## Notlar
Çekirdek mimari ilke; CLAUDE.md "Mimari ilkeler" bölümünde sabit olarak korunur.
