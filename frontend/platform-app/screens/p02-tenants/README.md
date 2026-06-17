# P-02 — Tenant Yönetimi & Provisioning (WBS 13.2.2)

L0 Platform Admin Console'un ikinci ekranı. Tenant **oluşturma/askıya alma/silme**, **plan atama** ve
yaşam döngüsü **durumu**nu yönetir (BRD §17.3).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-02 **yalnız tenant kayıt/kaynak metadatası** gösterir: tenant org adı, plan, durum, bölge, oluşturma
tarihi, kullanıcı **sayısı**. Tenant **iş içeriği** (çağrı kaydı, transkript, son-müşteri/PII) **gösterilmez**.
Veri katmanı (`lib/platform/tenants.ts`) tipleri yapısal olarak iş-içeriği taşımaz ve `assertNoPii` çalışma-
anında doğrular (sızıntı → hata). NOT: tenant org *adı* tenant kimliğidir (RMC müşterisi) ve L0'da izinlidir;
yasaklanan, tenant'ın **son-müşteri** verisidir.

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**—** · `platform_billing`=**—** (yalnız owner erişimi). UI yalnız
görsel kapı; nihai yetki + provisioning **durum geçişi** backend'de (12.2.x, SAD §14.4.1 A8). Bu katmanda
rol→permission kararı **yok**.

## Bileşenler
- `app/(platform)/tenants/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`)
  + veri seam (`lib/platform/tenants`). Tüm metin `screen.p02.*` katalogundan (t()).
- `lib/platform/tenants.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`statusTone`/`countByStatus`/`lifecycleActions`/`provisioningProgress`/`isTerminal`) + `assertNoPii` guard.
  Yer tutucu deterministik snapshot; gerçek kaynak F2 §14.1'de Tenant/Provisioning servisi + Resource
  Manager + faturalandırma kayıtlarından beslenir.
- `i18n` (`screen.p02.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Provisioning durum makinesi (`lifecycleActions`)
`provisioning`/`deprovisioning` → süreçte, aksiyon yok · `active` → askıya al / plan ata / sil ·
`suspended` → devam ettir / plan ata / sil · `deleted` → terminal, aksiyon yok. UI bu kümeyi yalnız
**sunar**; geçişi backend zorlar.

## Doğrulama
```
python3 p02_tenants_probe.py validate   # ON-DISK invariant S1..S8
python3 p02_tenants_probe.py check      # saf çekirdek senaryo + samples
python3 p02_tenants_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p02_tenants_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                     # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Tenant/Provisioning API bağlama (F2 §14.1); diğer L0 ekranları P-03..P-09 (13.2.3+); provisioning
form/aksiyon istemci-tarafı submit + backend durum geçişi (12.2.x); PII maskeleme yardımcıları 13.1.4;
backend yetki guard/RLS 12.2.x. Vendor-neutral (ADR-002); sır/credential yok.
