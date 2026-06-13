---
adr: ADR-NNNN
title: <Kısa, emir kipi karar başlığı>
status: Önerilen
date: YYYY-AA-GG
deciders: <karar veren rol(ler)/kişiler>
consulted: <danışılan paydaşlar (ops.)>
tags: [<alan-etiketi>, ...]
supersedes:
superseded-by:
iz: <BRD/SAD §, FR-/NFR-/SR- referansları>
---

# ADR-NNNN — <Karar Başlığı>

> **Durum:** Önerilen · **Tarih:** YYYY-AA-GG · **Karar verenler:** <...>
> Durum yaşam döngüsü ve süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem (Context)
<Hangi mimari/iş sorunu çözülüyor? Hangi kısıtlar (BRD/SAD/NFR), hangi tetikleyici?
Kararın *neden* şimdi verildiğini açıkla. 1–3 paragraf.>

## Karar Sürücüleri (Decision Drivers)
- <ölçütü/gereksinim, ör. NFR 10.1 gecikme bütçesi>
- <vendor-neutrality, maliyet, güvenlik, operasyonel basitlik, ...>

## Değerlendirilen Seçenekler (Options)
1. **<Seçenek A>** — <kısa tanım>.
2. **<Seçenek B>** — <kısa tanım>.
3. **<Seçenek C>** — <kısa tanım>.

## Karar (Decision)
<Seçilen yön. Tek cümlelik öz + gerekçe. "X seçildi, çünkü …".>

## Sonuçlar (Consequences)
**Olumlu**
- <kazanım>

**Olumsuz / Ödünleşim (trade-off)**
- <maliyet, risk, teknik borç, gelecekte yeniden değerlendirme tetikleyicisi>

## İzlenebilirlik (Traceability)
- **Kaynak gereksinim:** <FR-*/NFR */BRD §/SAD §>
- **Etkilenen WBS:** <docs/todo_list.md ID(ler)i>
- **İlişkili ADR'ler:** <ADR-XXX (supersedes/superseded-by/ilgili)>

## Notlar
<PoC/eval bağı, açık sorular, yeniden değerlendirme koşulu. Açık (Open) kararlar için
kararın hangi çıktıyla netleşeceği yazılır.>
