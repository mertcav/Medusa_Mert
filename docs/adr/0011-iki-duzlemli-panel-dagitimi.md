---
adr: ADR-011
title: İki düzlemli panel dağıtımı (L0 ayrı internal-only; L1+L2 birlikte public)
status: Kabul
date: 2026-06-13
deciders: Mimari ekip, Güvenlik
tags: [panel, deployment, security, blast-radius]
supersedes:
superseded-by:
iz: SAD §14.4.1; BRD §17.7; FR-IAM-008
---

# ADR-011 — İki düzlemli panel dağıtımı

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Üç panel katmanı vardır: L0 (Platform Admin, cross-tenant), L1 (Tenant Admin), L2 (Operasyon).
L0'ın yanlış yapılandırılması cross-tenant veriye erişim (blast-radius) demektir. Dağıtım topolojisi
güvenlik ile maliyet arasında bir seçim gerektirir.

## Karar Sürücüleri
- Blast-radius azaltımı (L0 cross-tenant yetkili); lean runtime/maliyet; paylaşılan kod riski.

## Değerlendirilen Seçenekler
1. **Tek deploy + guard (üç panel aynı serviste).** Ucuz; paylaşılan middleware'deki tek bug L0'ı açar.
2. **Üç ayrı deploy (L0/L1/L2 ayrı).** En izole; kaynak israfı.
3. **İki düzlem: L0 ayrı internal-only Control Plane + L1+L2 birlikte public Tenant Application Plane.**

## Karar
**Seçenek 3** kabul edildi. **L0**, ayrı ve **internal-only** bir *Platform Control Plane* olarak
(ayrı origin/API/auth realm, VPN/allowlist/private endpoint arkasında) deploy edilir. **L1+L2** birlikte,
multi-tenant ve public bir *Tenant Application Plane* olarak çalışır.

## Sonuçlar
**Olumlu**
- L0'a maruz kalan yüzey en aza iner; tek-bug-açar riski ortadan kalkar; üç-deploy israfından kaçınılır.

**Olumsuz / Ödünleşim**
- İki ayrı dağıtım hattı/operasyon; L0 erişimi yalnız iç ağdan (kullanım kısıtı).

## İzlenebilirlik
- **Kaynak gereksinim:** SAD §14.4.1; BRD §17.7; FR-IAM-008.
- **Etkilenen WBS:** 13.1.1, 12.2.2.
- **İlişkili ADR'ler:** ADR-004 (plane ayrımı), ADR-013 (break-glass).
