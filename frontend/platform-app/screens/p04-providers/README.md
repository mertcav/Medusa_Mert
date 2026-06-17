# P-04 — Sağlayıcı & Entegrasyon Sağlığı (WBS 13.2.4)

L0 Platform Admin Console'un dördüncü ekranı. **STT/TTS/LLM/telekom adapter durumu**, **fallback/routing
varsayılanları** ve **sağlayıcı maliyeti**ni gösterir (BRD §17.3). Kaynak doğruluk Provider Adapter SPI
(SAD §8.1: `health()`/`meter()`; §8.2 circuit breaker; §8.3 fallback/routing) ve gözlemlenebilirlik
omurgası (SAD §17: provider error rate / latency / dakika maliyeti).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-04 **yalnız sağlayıcı/adapter sağlık + yönlendirme + maliyet metadatası** gösterir: kategori, rol,
sağlık durumu, circuit breaker, hata oranı, p95 gecikme, fallback sırası, kategori maliyeti. Tenant **iş
içeriği** (çağrı kaydı, transkript, son-müşteri/PII) **gösterilmez**. Veri katmanı
(`lib/platform/providers.ts`) tipleri yapısal olarak iş-içeriği taşımaz ve `assertNoPii` çalışma-anında
doğrular (sızıntı → hata). NOT: adapter *adı* vendor-nötr iç etikettir (RMC); somut sağlayıcı markası
bağlanmaz (ADR-002 / BRD §19).

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**Yönet** · `platform_billing`=**Görüntüle**. UI yalnız görsel
kapı; nihai yetki + yönlendirme/fallback **zorlaması** backend'de adapter SPI üzerinden (12.2.x;
permission-key `provider:health:read` + `provider:routing:manage`, SAD §7 · §14.4.1 A8). Bu katmanda
rol→permission kararı **yok**.

## Bileşenler
- `app/(platform)/providers/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`)
  + veri seam (`lib/platform/providers`). Tüm metin `screen.p04.*` katalogundan (t()). Bölümler: genel
  sağlık özeti (KPI: sağlıklı/degrade/down adapter, açık circuit, aktif fallback, maliyet), dayanıklılık
  uyarısı (BRD §19), fallback & yönlendirme varsayılanları (kategori), adapter durumu (dizin), sağlayıcı
  maliyeti (kategori).
- `lib/platform/providers.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`healthTone`/`circuitTone`/`errorRateTone`/`rollupHealth`/`categoryHealth`/`redundancyOk`/
  `redundancyRisks`/`isFallbackActive`/`activeFallbackCount`/`openCircuitCount`/`countByHealth`/
  `aggregateCost`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek kaynak F2 §14.1'de
  Provider Adapter SPI + 0.4.7 gözlemlenebilirlik omurgasından beslenir.
- `i18n` (`screen.p04.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Sağlık tonu** (`healthTone`): healthy→success · degraded→warning · down→danger.
- **Circuit tonu** (`circuitTone`): closed→success · half_open→warning · open→danger.
- **Hata oranı tonu** (`errorRateTone`): ≥%5 danger · ≥%1 warning · aksi success.
- **Fallback aktif** (`isFallbackActive`): birincil adapter `down` **veya** circuit `open` → trafik
  secondary'ye gider (SAD §8.3).
- **Dayanıklılık** (`redundancyOk` / `redundancyRisks`): kategoride ≥`MIN_OPERATIONAL_PROVIDERS` (2) çalışır
  (down olmayan) sağlayıcı → BRD §19 kuralı. Aksi → danger uyarısı.

## Doğrulama
```
python3 p04_providers_probe.py validate   # ON-DISK invariant S1..S8
python3 p04_providers_probe.py check      # saf çekirdek senaryo + samples (sağlık sayımı + fallback + maliyet)
python3 p04_providers_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p04_providers_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                       # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Provider Adapter SPI/health/meter API bağlama (F2 §14.1); yönlendirme/fallback varsayılanı form
istemci submit + backend zorlama (12.2.x); diğer L0 ekranları P-05..P-09 (13.2.5+); PII maskeleme
yardımcıları 13.1.4; canlı vendor değerlendirme/seçim (0.2.x/0.3.x). Vendor-neutral (ADR-002; somut
sağlayıcı markası bağlanmaz); sır/credential yok.
