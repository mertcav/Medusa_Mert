# T-01 — Tenant Dashboard (WBS 13.3.1)

L1 Tenant Admin Console'un ilk ekranı (T-01..T-09 serisinin başı). Tenant'ın **kendi** toplulaştırılmış
KPI'larını, kullanımını, maliyetini ve **L0 tarafından atanan kaynak kotası tüketimini** gösterir (BRD §17.4).

## Tenant scope (FR-TEN-002) + dashboard hijyeni (BRD §17.7)
T-01 **yalnız oturum açan tenant'ın KENDİ** toplulaştırılmış verisini gösterir; scope çalışma-anında
middleware (13.1.2) + RLS (§13) ile sabitlenir. Panel yalnız **toplulaştırılmış metrik** gösterir; ham
son-müşteri iş içeriği (çağrı kaydı, transkript, müşteri/PII) panele **gömülmez** (bunlar L2 operasyon
ekranlarında — A-11/A-12 — ayrıca yetkiyle görülür). Veri katmanı (`lib/tenant/dashboard.ts`) tipleri
yapısal olarak PII taşımaz ve `assertNoPii` çalışma-anında doğrular. `tenantRef`/`tenantName` tenant'ın
**kendi** kimliğidir (L1'de izinli).

## Bileşenler
- `app/(tenant-admin)/admin/dashboard/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/dashboard`). Tüm metin `screen.t01.*` katalogundan (t()).
- `lib/tenant/dashboard.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`utilizationPct`/`headroom`/`budgetUsagePct`/`aggregateUsage`/`healthTone`/`utilTone`/`budgetTone`/
  `worstQuotaTone`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek kaynak F2 §14.1'de
  0.4.7 gözlemlenebilirlik omurgası + Billing & Usage + Resource Manager'dan tenant-scope beslenir.
- `i18n` (`screen.t01.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Görüntüle · `security_compliance_officer`=Görüntüle ·
`billing_viewer`=Görüntüle · `api_developer`=erişim yok. UI yalnız görsel kapı; nihai yetki backend'de
(12.2.x, SAD §14.4.1 A8) + RLS. Bu katmanda rol→permission kararı **yok**.

## Doğrulama
```
python3 t01_dashboard_probe.py validate   # ON-DISK invariant S1..S8
python3 t01_dashboard_probe.py check      # saf çekirdek senaryo + samples
python3 t01_dashboard_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t01_dashboard_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                      # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek metrik/billing/resource API bağlama (F2 §14.1); diğer L1 ekranları T-02..T-09 (13.3.2+);
PII maskeleme yardımcıları 13.1.4; backend yetki guard/RLS 12.2.x; L0 kota atama T-09/P-03;
operasyonel detay (canlı çağrı/kayıt/transkript) L2 (A-01..A-17, 13.4). Vendor-neutral (ADR-002);
sır/credential yok.
