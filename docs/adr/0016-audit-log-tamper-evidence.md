---
adr: ADR-016
title: Audit log tamper-evidence yöntemi (hash zinciri + dış mühürleme)
status: Önerilen
date: 2026-06-13
deciders: Mimari ekip, Güvenlik, Uyum
tags: [security, audit, integrity, worm]
supersedes:
superseded-by:
iz: THREAT_MODEL.md §10 (TM-T-03); FR-IAM-006
---

# ADR-016 — Audit log tamper-evidence yöntemi

> **Durum:** Önerilen · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik, Uyum
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
WORM/append-only audit log (FR-IAM-006) yalnız "yazılabilir" olması yetmez; **kurcalanmadığının
kanıtlanabilir** olması gerekir (TM-T-03). İç tehdit veya ihlalde audit'in bütünlüğü ispatlanmalıdır.

## Karar Sürücüleri
- Tamper-evidence; uyum/denetim ispatı; maliyet ve operasyonel basitlik.

## Değerlendirilen Seçenekler
1. **Yalnız append-only DB (WORM).** Basit; iç-yetkili kurcalamasına kanıt zayıf.
2. **Hash zinciri (her kayıt öncekinin hash'ini içerir).** Kurcalama tespit edilebilir.
3. **Hash zinciri + periyodik harici mühürleme (WORM/ledger/üçüncü taraf).** En güçlü ispat.

## Karar
**Seçenek 3 öneriliyor:** audit kayıtları **hash zincirleme** ile bağlanır ve periyodik olarak **dış
WORM/ledger**'a mühürlenir. Maliyet/uyum dengesine göre dış mühürleme sıklığı ayarlanır. Durum **Önerilen**.

## Sonuçlar
**Olumlu**
- Audit bütünlüğü kriptografik olarak ispatlanır; iç tehdit kurcalaması tespit edilir.

**Olumsuz / Ödünleşim**
- Hash zinciri + dış mühürleme ek altyapı/maliyet ve operasyon.

## İzlenebilirlik
- **Kaynak gereksinim:** THREAT_MODEL §10 (TM-T-03); FR-IAM-006.
- **Etkilenen WBS:** 12.1.8 (WORM audit).
- **İlişkili ADR'ler:** ADR-013 (break-glass audit).

## Notlar
**Kapanış kriteri:** Uyum gereksinimleri (ISO/SOC2/DORA) ile dış mühürleme sıklığı/sağlayıcısı
netleşince durum `Kabul`'e geçer.
