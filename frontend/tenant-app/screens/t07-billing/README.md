# T-07 — Faturalandırma & Kullanım (WBS 13.3.7)

L1 Tenant Admin Console'un yedinci ekranı (T-01..T-09 serisi). Tenant'ın **faturalama ve kullanım
görünümünü** gösterir: **plan** (fiyat planı + faturalama modeli + minimum ücret + para birimi),
**kullanım** (dakika/saniye bazlı tüketim — FR-BIL-001), **maliyet kırılımı** (telekom/STT/TTS/LLM/platform
ayrı izleme — FR-BIL-002), **kota & overage** (kullanım kotası + aşım — FR-BIL-004), **bütçe alarmı**
(kullanım limiti + bütçe eşikleri — FR-BIL-006) ve **fatura aktarımı** (finans sistemine aktarım durumu —
FR-BIL-007). Dedicated altyapı ayrı faturalandırma bayrağı (FR-BIL-005). Fiyat/maliyet değerleri
**illüstratiftir** — bağlayıcı rate-card finans/billing motorundan (L0 P-05) beslenir; veriler yalnız
tenant-bütünü topluluk metriğidir.

## Tenant scope (FR-TEN-002) + hijyen (BRD §17.7) + güvenlik (NFR 10.6)
T-07 **yalnız oturum açan tenant'ın KENDİ** plan/kullanım/maliyet görünümünü gösterir; scope çalışma-anında
middleware (13.1.2) + RLS (§13) ile sabitlenir:
- Ham son-müşteri iş içeriği (çağrı kaydı, transkript, **çağrı-bazlı CDR satırı**, müşteri PII/numarası)
  buraya **gömülmez** — bunlar L2/data-plane'de tutulur; `FORBIDDEN_PII_KEYS` (`cdr` dahil) + `assertNoPii`
  ile çalışma-anında garanti. Maliyet/kullanım **yalnız tenant-bütünü TOPLULAŞTIRMADIR**.
- **SIR / FİNANSAL credential** (ödeme yöntemi token'ı, kart PAN'ı, IBAN/banka hesabı, finans sistemi API
  credential'ı) buraya **konmaz** — `FORBIDDEN_SECRET_KEYS` + `assertNoPii` ile garanti. Bütçe alarm kanalı
  ve fatura aktarım hedefi yalnız **ad** olarak gösterilir.

## Bileşenler
- `app/(tenant-admin)/admin/billing/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/billing`). Tüm metin `screen.t07.*` katalogundan (t()). Bölümler:
  **Özet** (plan/kullanım/maliyet/bütçe-tüketimi/açık-uyarı) · **Plan** (plan adı + katman + faturalama
  modeli + para birimi + minimum ücret + dönem + dedicated) · **Kullanım** (faturalanan dakika/saniye +
  kota + kota aşımı + çağrı adedi) · **Maliyet Kırılımı** (telekom/STT/TTS/LLM/platform tutar + pay +
  toplam, uzlaşı) · **Kota & Overage** (overage açık/ücret/dakika/maliyet + engellenme) · **Bütçe &
  Alarmlar** (bütçe/harcama/limit + alarm eşikleri/kanal/durum) · **Fatura Aktarımı** (durum + hedef + son
  aktarım). Uyarılar: bütçe aşımı / kullanım limiti aşımı / maliyet uzlaşı boşluğu / aktarım hatası /
  geçersiz plan → danger; bütçeye yaklaşma / overage engellenme / alarm boşluğu / aktarım yapılandırılmamış
  → warning.
- `lib/tenant/billing.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları (`costTotal`/`costShare`/
  `budgetRatio`/`overBudget`/`budgetApproaching`/`triggeredAlarms`/`unconfiguredAlarms`/`quotaOverageMinutes`/
  `overageBlocked`/`usageLimitExceeded`/`costMismatch`/`invalidPlan`/`invoiceExport*`/`openWarningCount`/
  tone'lar) + `assertNoPii` guard (PII/CDR **ve** ödeme sırrı). Yer tutucu deterministik snapshot; gerçek
  kaynak F2 §14.1'de Billing/Rating motoru + metering (kullanım toplulaştırma) + L0 P-05 rate-card'ından
  tenant-scope (RLS) beslenir.
- `i18n` (`screen.t07.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Görüntüle · `security_compliance_officer`=— · `billing_viewer`=Görüntüle ·
`api_developer`=—. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8) + RLS. "Planı
Değiştir" aksiyonu görsel kapıdır; plan değiştirme/bütçe alarmı kaydetme istemci submit + backend zorlama
12.2.x'te.

## Doğrulama
```
python3 t07_billing_probe.py validate   # ON-DISK invariant S1..S8
python3 t07_billing_probe.py check      # saf çekirdek senaryo + samples
python3 t07_billing_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t07_billing_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                    # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (bilinçli)
Gerçek Billing/Rating motoru + metering (kullanım toplulaştırma) + L0 P-05 rate-card API bağlama → F2 §14.1;
plan değiştirme/bütçe alarmı kaydetme istemci submit + backend zorlama → 12.2.x; finans sistemine canlı
fatura aktarımı (FR-BIL-007) yürütme → entegrasyon/billing servisi; çağrı-bazlı maliyet/CDR + operasyonel
kaynak tüketimi (A-15) → L2/data-plane. Fiyat/maliyet değerleri illüstratiftir; vendor-neutral (ADR-002);
sır/finansal credential repoya yazılmaz.
