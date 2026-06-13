# `docs/platform/load-testing/` — Yük/performans test ortamı (WBS 0.4.8)

Sentetik çağrı üreteci (call generator) + sistem-seviyesi yük/kapasite simülasyonu. Tasarım kapasitesinde
(NFR 10.3) yük + eş zamanlı çağrı testini (FR-TST-006) yürütülebilir kılan iskelet. Kaynak doğruluk:
tasarım `load-test-harness.md`. →FR-TST-006, NFR 10.3/10.1/10.2, FR-RES-014/013/016, FR-TST-009, SAD §16/§20.

0.3.x PoC hattıyla aynı disiplin: **vendor-neutral (ADR-002), stdlib-only, credential-free, deterministik,
sentetik veri (FR-TST-008)**. 0.3.2 (gecikme) + 0.3.3 (density) + 0.3.4 (hibrit medya) çıktısını **girdi**
alır ve yük altında nasıl bozulduğunu ölçer.

## İçerik
- `load-test-harness.md` — tasarım: yük üreteci↔SUT mimari eşleme, Little/Poisson kapasite modeli, admission/backpressure, kapılar, senaryolar, izlenebilirlik.
- `load_test_probe.py` — stdlib-only sentetik çağrı üreteci + kesikli-zaman simülasyon (`run`/`compare`/`selftest`/`schema`).
- `scenarios/` — illüstratif yük senaryoları (FR-TST-008, sentetik): `load-pilot` (F1) · `load-enterprise` (F2) · `load-hyperscale` (F3, NFR 10.3 tavanı) · `load-burst-2x` (2x ani trafik) · `load-overload-degraded` (🔴 eler).

## Komutlar
```bash
python3 load_test_probe.py selftest                                  # Little/Poisson/kapı/determinizm (12/12)
python3 load_test_probe.py run --scenario scenarios/load-hyperscale.json   # kapasite/CPS/gecikme/kaynak + kapı → çıkış kodu
python3 load_test_probe.py compare scenarios/load-*.json             # senaryo tablosu
python3 load_test_probe.py schema                                    # senaryo JSON şeması
```

## Notlar
- **Vendor/dil-nötr · credential-free:** gerçek call-generator/telemetri yalnız `--url`/ortam değişkeni ile (repoya sır yazılmaz).
- İskelet kapısıdır; canlı yük testi (F1 §18.5) aynı senaryo yapısını gerçek telefoni trunk + sentetik medya ile doldurur.
- **2x burst** mutlak region tavanında emilemez (graceful shed) — 2x absorpsiyon `workers_max ≥ 2×steady` planlaması gerektirir (BRD §10.3 notu); `load-burst-2x` headroom'lu absorpsiyonu izole gösterir.
- F1'de WBS §18.5/§18.6 görevleri bu iskeleti gerçek yük testiyle doldurur.
