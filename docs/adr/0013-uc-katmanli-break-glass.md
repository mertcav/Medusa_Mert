---
adr: ADR-013
title: Üç katmanlı break-glass + regüle tenant onay toggle'ı
status: Kabul
date: 2026-06-13
deciders: Mimari ekip, Güvenlik, Hukuk
tags: [break-glass, privacy, iam, compliance]
supersedes:
superseded-by:
iz: FR-IAM-009, FR-IAM-010; SAD §14.4.2; DPIA.md
---

# ADR-013 — Üç katmanlı break-glass + regüle tenant onay toggle'ı

> **Durum:** Kabul · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik, Hukuk
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
L0 (platform/RMC) varsayılan olarak tenant iş içeriğini (kayıt/transkript/PII) görmemelidir
(KVKK/GDPR controller-processor ayrımı). Ancak destek/incident için kontrollü, denetlenebilir
istisnai erişim gerekebilir.

## Karar Sürücüleri
- "Altın kural": L0 içeriği varsayılan göremez; istisna kontrollü/denetlenebilir olmalı; DPA bağı.

## Değerlendirilen Seçenekler
1. **Standing L0 erişimi.** Operasyonel kolay; gizlilik/uyum açısından kabul edilemez.
2. **Tümüyle erişim yok.** En güvenli; gerçek destek/incident'i imkânsızlaştırır.
3. **Üç katmanlı break-glass** (Tier A metrik/log → break-glass'sız; Tier B transkript/PII → maker-checker
   + time-boxed + gerekçe + bildirim) **+ regüle tenant için zorunlu onay toggle'ı.**

## Karar
**Seçenek 3** kabul edildi. **Tier A** (metrik/log, PII yok) break-glass gerektirmez. **Tier B**
(transkript/kayıt/PII) maker-checker + time-boxed (60 dk default, max 4 sa, standing access yok) +
gerekçe kodu + tenant `security_compliance_officer`/`tenant_owner`'a bildirim ister. Regüle tenant'larda
`require_tenant_approval` toggle'ı (regulated profile'da default açık), DPA'ya bağlı.

## Sonuçlar
**Olumlu**
- Gizlilik/uyum (controller-processor) korunur; istisnai erişim tam audit'li ve süreli.

**Olumsuz / Ödünleşim**
- Acil durumda ek onay adımı gecikme yaratabilir; maker-checker iş akışı altyapısı gerekir.

## İzlenebilirlik
- **Kaynak gereksinim:** FR-IAM-009/010; SAD §14.4.2; DPIA.md.
- **Etkilenen WBS:** 12.3.x (break-glass).
- **İlişkili ADR'ler:** ADR-011, ADR-012, ADR-016 (audit tamper-evidence), ADR-017 (MFA).
