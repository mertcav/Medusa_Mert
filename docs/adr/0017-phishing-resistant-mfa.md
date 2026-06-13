---
adr: ADR-017
title: Phishing-resistant MFA zorunluluğu (WebAuthn/FIDO2)
status: Önerilen
date: 2026-06-13
deciders: Mimari ekip, Güvenlik
tags: [security, mfa, iam, webauthn]
supersedes:
superseded-by:
iz: THREAT_MODEL.md §10 (TM-S-03, TM-E-05); FR-IAM-003
---

# ADR-017 — Phishing-resistant MFA zorunluluğu (WebAuthn/FIDO2)

> **Durum:** Önerilen · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
L0 ve break-glass onaylayıcıları en yüksek ayrıcalıklı kimliklerdir; OTP/SMS gibi phishing'e açık
MFA türleri bu hesaplar için yetersizdir (TM-S-03 hesap ele geçirme, TM-E-05 ayrıcalık yükseltme).

## Karar Sürücüleri
- Hesap ele geçirme/ayrıcalık yükseltme riskini düşürmek; en yüksek ayrıcalıkta phishing direnci.

## Değerlendirilen Seçenekler
1. **OTP/SMS MFA (her yerde).** Yaygın; phishing/SIM-swap'e açık.
2. **TOTP authenticator.** Daha iyi; yine phishing'e açık.
3. **Phishing-resistant MFA (WebAuthn/FIDO2)** — L0/break-glass için zorunlu, tenant için politika.

## Karar
**Seçenek 3 öneriliyor.** **WebAuthn/FIDO2** L0 yöneticileri ve break-glass onaylayıcıları için
**zorunlu**; tenant kullanıcıları için politika ile yapılandırılabilir (tenant profili). Durum **Önerilen**.

## Sonuçlar
**Olumlu**
- En yüksek ayrıcalıklı hesaplarda phishing/SIM-swap riski büyük ölçüde kapanır.

**Olumsuz / Ödünleşim**
- Donanım/platform authenticator gereksinimi; kurtarma (recovery) akışı tasarımı gerekir.

## İzlenebilirlik
- **Kaynak gereksinim:** THREAT_MODEL §10 (TM-S-03, TM-E-05); FR-IAM-003.
- **Etkilenen WBS:** 12.1.5 (MFA), 12.3.x (break-glass).
- **İlişkili ADR'ler:** ADR-011, ADR-013.

## Notlar
**Kapanış kriteri:** IdP/WebAuthn desteği ve recovery süreci doğrulanınca durum `Kabul`'e geçer.
