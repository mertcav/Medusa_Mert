# T-02 — Organizasyon & Yapı (WBS 13.3.2)

L1 Tenant Admin Console'un ikinci ekranı (T-01..T-09 serisi). Tenant **altında** marka, departman, ülke
ve proje yapılarını gösterir ve yönetir (BRD §17.4 / FR-TEN-003). BRD §16 "Organisation Unit" = marka/
ülke/departman; proje org birimlerine bağlanan operasyonel gruplamadır.

## Tenant scope (FR-TEN-002) + hijyen (BRD §17.7) + RBAC scope bağı (FR-IAM-011)
T-02 **yalnız oturum açan tenant'ın KENDİ** organizasyon yapısını gösterir/yönetir; scope çalışma-anında
middleware (13.1.2) + RLS (§13) ile sabitlenir. Ekran yalnız **konfigürasyon metadatası** gösterir; ham
son-müşteri iş içeriği (çağrı kaydı, transkript, müşteri/PII) buraya **gömülmez**. Veri katmanı
(`lib/tenant/organization.ts`) tipleri yapısal olarak PII taşımaz ve `assertNoPii` çalışma-anında doğrular.
`tenantRef`/`tenantName` + org birim/proje `name`/`code` tenant'ın **kendi** konfigürasyonudur (izinli).
Burada tanımlanan **marka/departman**, kullanıcı rol atamalarının **kapsam (scope) filtresine** (FR-IAM-011:
departman/marka/kampanya) kaynaklık eder.

## Bileşenler
- `app/(tenant-admin)/admin/org/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/organization`). Tüm metin `screen.t02.*` katalogundan (t()).
  Bölümler: **Özet** (marka/departman/ülke/proje + aktif birim) · **Organizasyon Birimleri** (marka/
  departman/ülke + hiyerarşi + kullanıcı/agent/proje sayısı + durum) · **Projeler** (bağlı marka/departman/
  ülke + durum + öksüz-referans rozeti). Öksüz referans varsa uyarı.
- `lib/tenant/organization.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`countByType`/`countByStatus`/`childrenOf`/`rootUnits`/`projectsForUnit`/`orphanProjects`/
  `unitStatusTone`/`projectStatusTone`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek
  kaynak F2 §14.1'de Tenant/Org servisi + RLS'ten tenant-scope beslenir.
- `i18n` (`screen.t02.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Yönet · `security_compliance_officer`/`billing_viewer`/`api_developer`
=erişim yok. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8) + RLS. "Yeni birim/
proje" aksiyonları görsel kapıdır; oluşturma/düzenleme istemci submit + backend zorlama 12.2.x'te. Bu
katmanda rol→permission kararı **yok**.

## Doğrulama
```
python3 t02_organization_probe.py validate   # ON-DISK invariant S1..S8
python3 t02_organization_probe.py check      # saf çekirdek senaryo + samples
python3 t02_organization_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t02_organization_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                          # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek org/tenant servisi API bağlama (F2 §14.1); birim/proje oluşturma/düzenleme istemci submit + backend
zorlama (12.2.x); diğer L1 ekranları T-03..T-09 (13.3.3+); PII maskeleme yardımcıları (13.1.4); rol atama
scope filtresi uygulaması (T-03 + 12.2.x). Vendor-neutral (ADR-002); sır/credential repoya yazılmadı.
