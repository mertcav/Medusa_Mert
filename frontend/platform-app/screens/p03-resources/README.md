# P-03 — Kaynak & Kapasite Yönetimi (WBS 13.2.3)

L0 Platform Admin Console'un üçüncü ekranı. **vCPU/bellek/eşzamanlılık/CPS kotaları**, **autoscale
politikası**, **scale-to-zero** ve **noisy-neighbor koruması**nı yönetir (BRD §17.3). Kaynak doğruluk
Resource Manager bileşeni (SAD §15.2: Quota Service · Autoscaler · Scale-to-zero Ctrl · Backpressure Ctrl
· Cost/Resource Meter) ve ölçek hedefleri (SAD §16, NFR 10.2/10.3).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-03 **yalnız kaynak/kapasite metadatası** gösterir: tenant org adı, plan, bölge, kotalar
(eşzamanlılık/CPS/vCPU/bellek), rezerve concurrency, izolasyon modu, scale-to-zero durumu. Tenant **iş
içeriği** (çağrı kaydı, transkript, son-müşteri/PII) **gösterilmez**. Veri katmanı
(`lib/platform/resources.ts`) tipleri yapısal olarak iş-içeriği taşımaz ve `assertNoPii` çalışma-anında
doğrular (sızıntı → hata). NOT: tenant org *adı* tenant kimliğidir ve L0'da izinlidir; yasaklanan,
tenant'ın **son-müşteri** verisidir.

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**Yönet** · `platform_billing`=**—**. UI yalnız görsel kapı;
nihai yetki + kota/politika **zorlaması** backend'de Resource Manager Quota Service'te (12.2.x, SAD
§14.4.1 A8). Bu katmanda rol→permission kararı **yok**.

## Bileşenler
- `app/(platform)/resources/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`)
  + veri seam (`lib/platform/resources`). Tüm metin `screen.p03.*` katalogundan (t()). Bölümler: platform
  kapasite özeti (KPI), noisy-neighbor uyarısı, autoscale & scale-to-zero politikası, bölge kapasitesi,
  tenant kaynak kotaları (dizin).
- `lib/platform/resources.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`utilizationPct`/`headroomPct`/`utilizationTone`/`aggregateQuota`/`regionConcurrencyUsed`/
  `isolationTone`/`scaleStateTone`/`noisyNeighborRisks`) + `assertNoPii` guard. Yer tutucu deterministik
  snapshot; gerçek kaynak F2 §14.1'de Resource Manager + 0.4.7 gözlemlenebilirlik omurgasından beslenir.
- `i18n` (`screen.p03.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Kullanım tonu** (`utilizationTone`): ≥90% danger (kritik) · ≥75% warning (yüksek) · aksi success.
- **Noisy-neighbor riski** (`noisyNeighborRisks`): izolasyon=`shared` **ve** eş-zamanlı kullanım ≥%85
  (`NOISY_NEIGHBOR_UTIL_PCT`). Rezerve concurrency'li tenant korumalıdır (risk dışı).
- **Scale-to-zero** (FR-RES-007): `active`/`idle`/`scaled_to_zero` durum tonları.

## Doğrulama
```
python3 p03_resources_probe.py validate   # ON-DISK invariant S1..S8
python3 p03_resources_probe.py check      # saf çekirdek senaryo + samples (kota toplamı + noisy-neighbor)
python3 p03_resources_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p03_resources_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                       # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Resource Manager/Quota API bağlama (F2 §14.1); kota/politika form istemci submit + backend zorlama
(12.2.x); diğer L0 ekranları P-04..P-09 (13.2.4+); PII maskeleme yardımcıları 13.1.4; backpressure/admission
canlı davranışı (0.4.8 yük testi + F1 §18.5). Vendor-neutral (ADR-002); sır/credential yok.
