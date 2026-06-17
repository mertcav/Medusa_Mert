# P-01 — Platform Genel Bakış (WBS 13.2.1)

L0 Platform Admin Console'un ilk ekranı. **Cross-tenant** platform sağlığı, toplam eşzamanlı çağrı,
kaynak kullanımı (CPU/bellek/density) ve platform maliyetini gösterir (BRD §17.3).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-01 **yalnız toplulaştırılmış metrik/kaynak verisi** gösterir. Tenant **iş içeriği** (çağrı kaydı,
transkript, müşteri/PII) **gösterilmez**. Veri katmanı (`lib/platform/overview.ts`) tipleri yapısal
olarak PII taşımaz ve `assertNoPii` çalışma-anında doğrular (sızıntı → hata).

## Bileşenler
- `app/(platform)/overview/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`)
  + veri seam (`lib/platform/overview`). Tüm metin `screen.p01.*` katalogundan (t()).
- `lib/platform/overview.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`rollupHealth`/`utilizationPct`/`headroom`/`healthTone`/`severityTone`) + `assertNoPii` guard.
  Yer tutucu deterministik snapshot; gerçek kaynak F2 §14.1'de 0.4.7 gözlemlenebilirlik omurgası +
  Resource Manager metriklerinden beslenir.
- `i18n` (`screen.p01.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored.

## RBAC (BRD §17.2)
`platform_owner`=Yönet · `platform_sre`=Görüntüle · `platform_billing`=Görüntüle. UI yalnız görsel
kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8). Bu katmanda rol→permission kararı **yok**.

## Doğrulama
```
python3 p01_overview_probe.py validate   # ON-DISK invariant S1..S8
python3 p01_overview_probe.py check      # saf çekirdek senaryo + samples
python3 p01_overview_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p01_overview_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                     # canlı smoke (next build+start+curl; credential-free)
```
Kapılar: validate 36/36 · check 21/21 · selftest 9/9 · behavior 3/3 · live 10/10 🟢.
`next build` (platform 10 route) + `tsc` 🟢; design-system probe regresyonsuz (validate 73/73).

## Kapsam dışı (sonraki dilimler)
Gerçek metrik API bağlama (F2 §14.1); diğer L0 ekranları P-02..P-09 (13.2.2+); PII maskeleme
yardımcıları 13.1.4; backend yetki guard/RLS 12.2.x. Vendor-neutral (ADR-002); sır/credential yok.
