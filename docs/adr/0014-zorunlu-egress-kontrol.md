---
adr: ADR-014
title: Zorunlu egress kontrol katmanı (egress proxy + allowlist)
status: Önerilen
date: 2026-06-13
deciders: Mimari ekip, Güvenlik
tags: [security, egress, ssrf, network]
supersedes:
superseded-by:
iz: THREAT_MODEL.md §10 (TM-E-06, TM-I-04); NFR 10.6
---

# ADR-014 — Zorunlu egress kontrol katmanı

> **Durum:** Önerilen · **Tarih:** 2026-06-13 · **Karar verenler:** Mimari ekip, Güvenlik
> Süreç için bkz. [`docs/adr/README.md`](README.md).

## Bağlam ve Problem
Tool/Integration Gateway ve adapter'lar dış ağa çok sayıda giden bağlantı kurar. Kontrolsüz egress,
SSRF (TM-E-06) ve veri sızdırma (TM-I-04) için doğrudan bir yoldur; iç metadata servisleri (cloud
metadata) ve RFC1918 hedefleri özellikle risklidir.

## Karar Sürücüleri
- SSRF/exfiltration yüzeyini daraltmak; tenant-tanımlı endpoint'leri denetlemek (FR-TOOL-012 allowlist).

## Değerlendirilen Seçenekler
1. **Serbest egress.** Basit; SSRF/exfiltration'a açık.
2. **Yalnız uygulama-içi allowlist.** Kısmi; bypass ve tutarsızlık riski.
3. **Zorunlu egress proxy + merkezi allowlist** (tüm data plane egress'i denetimli proxy üzerinden).

## Karar
**Seçenek 3 öneriliyor.** Tüm data plane giden bağlantıları denetimli bir **egress proxy** üzerinden
geçer; varsayılan olarak iç metadata/RFC1918 hedefleri engellenir, yalnız allowlist'teki endpoint'lere
izin verilir. Durum **Önerilen** — kabul edilince SAD §14'e işlenir.

## Sonuçlar
**Olumlu**
- SSRF/exfiltration yüzeyi ciddi şekilde daralır; egress merkezi olarak audit edilir.

**Olumsuz / Ödünleşim**
- Proxy ek bileşen/gecikme; allowlist yönetimi operasyonel yük.

## İzlenebilirlik
- **Kaynak gereksinim:** THREAT_MODEL §10 (TM-E-06, TM-I-04); NFR 10.6; FR-TOOL-012.
- **Etkilenen WBS:** 7.2.3, 17.1.4.
- **İlişkili ADR'ler:** ADR-002 (adapters), ADR-015.

## Notlar
**Kapanış kriteri:** Güvenlik mimarisi gözden geçirip kabul edince; uygulama 0.4.x platform engineering
kapsamında. Kaynak: THREAT_MODEL.md SEC kontrolleri.
