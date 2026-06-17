# P-05 — Platform Faturalandırma & Rate-Card (WBS 13.2.5)

L0 Platform Admin Console'un beşinci ekranı. **Plan tanımları**, **fiyatlandırma (rate-card)** ve
**cross-tenant kullanım toplulaştırma**yı gösterir (BRD §17.3). Kaynak doğruluk Billing & Usage servisi
(FR-BIL-001 dakika/saniye ölçüm; FR-BIL-002 telekom/STT/TTS/LLM/platform ayrı maliyet; FR-BIL-003 fiyat
planı; FR-BIL-004 minimum/kota/overage; FR-BIL-006 bütçe alarmı; FR-BIL-007 finans dışa aktarım) +
Cost-Resource Meter (SAD §8.1 `meter()` / §15.2) + gözlemlenebilirlik omurgası (SAD §17).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-05 **yalnız faturalandırma/plan/rate-card + TOPLULAŞTIRILMIŞ kullanım metadatası** gösterir: birim ücret,
maliyet, marj, plan kotası/overage/bütçe eşiği, tenant başına faturalanan dakika/bütçe kullanımı/durum.
Tenant **iş içeriği** (çağrı kaydı, transkript, son-müşteri/PII) **gösterilmez**. Veri katmanı
(`lib/platform/billing.ts`) tipleri yapısal olarak iş-içeriği taşımaz ve `assertNoPii` çalışma-anında
doğrular (sızıntı → hata). NOT: `tenantName` (org adı) **tenant kimliğidir** (izinli); yasaklanan
**son-müşteri** verisidir.

## RBAC (BRD §17.6)
`platform_owner`=**Görüntüle** · `platform_sre`=**erişim yok** · `platform_billing`=**Yönet**. UI yalnız
görsel kapı; nihai yetki + rate-card/plan/export **zorlaması** backend'de (12.2.x; permission-key
`billing:read` + `billing:rate_card:manage` + `billing:plan:manage` + `billing:export`, SAD §7 · §14.4.1
A8). Bu katmanda rol→permission kararı **yok**.

## Bileşenler
- `app/(platform)/billing/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`) +
  veri seam (`lib/platform/billing`). Tüm metin `screen.p05.*` katalogundan (t()). Bölümler: kullanım &
  gelir özeti (KPI: faturalanan dakika, gelir, sağlayıcı maliyeti, marj, aktif plan, bütçe aşan tenant),
  bütçe alarmı uyarısı (FR-BIL-006), rate-card (kategori birim ücreti + maliyet + marj; FR-BIL-002), plan
  tanımları (taban/kota/overage/bütçe eşiği; FR-BIL-003/004), tenant kullanım toplulaştırma (dakika +
  overage + bütçe + durum; FR-BIL-001).
- `lib/platform/billing.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`marginPct`/`marginTone`/`budgetTone`/`billingStatusTone`/`planStatusTone`/`overageMinutes`/
  `rateMarginPct`/`aggregateUsage`/`overBudgetTenants`/`planTenantCount`/`countByBillingStatus`/
  `activePlanCount`/`planName`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek kaynak
  F2 §14.1 / WBS 15.x'te Billing & Usage servisi + Cost-Resource Meter'dan beslenir.
- `i18n` (`screen.p05.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Marj** (`marginPct` / `marginTone`): (gelir−maliyet)/gelir; ≥%30 success · ≥%15 warning · aksi danger.
- **Bütçe tonu** (`budgetTone`, FR-BIL-006): ≥%100 danger (aşıldı) · ≥%80 warning (yaklaşıyor) · aksi success.
- **Overage** (`overageMinutes`, FR-BIL-004): max(0, faturalanan − dahil kota).
- **Bütçe aşan tenant** (`overBudgetTenants`): `budgetUsedPct ≥ %100` (bütçe alarmı tetiği).
- **Aktif plan** (`activePlanCount`): `status=active` (deprecated planlar yeni atamaya kapalı).

## Doğrulama
```
python3 p05_billing_probe.py validate   # ON-DISK invariant S1..S8
python3 p05_billing_probe.py check      # saf çekirdek senaryo + samples (toplulaştırma + bütçe + marj)
python3 p05_billing_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p05_billing_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                     # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Billing & Usage / Cost-Resource Meter API bağlama (F2 §14.1 / WBS 15.x: 15.1 dakika ölçüm, 15.2
maliyet izleme, 15.3 plan tanımı, 15.4 minimum/kota/overage, 15.5 bütçe alarmı, 15.7 finans aktarım);
rate-card/plan düzenleme + finans dışa aktarım form istemci submit + backend zorlama (12.2.x); diğer L0
ekranları P-06..P-09 (13.2.6+); dedicated altyapı ayrı faturalandırma FR-BIL-005 (WBS 15.6, F3); PII
maskeleme yardımcıları 13.1.4; tenant tarafı faturalandırma T-07 (13.3.7). Vendor-neutral (ADR-002; somut
sağlayıcı/ticari marka bağlanmaz); sır/credential yok.
