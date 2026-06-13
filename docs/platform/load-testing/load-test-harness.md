# Yük/Performans Test Ortamı — `load-test-harness`

> **WBS 0.4.8** · `F0` · `Should` · →FR-TST-006 (BRD §9.16) · NFR 10.3 (BRD §10.3), NFR 10.1, NFR 10.2 · FR-RES-014/013/016, FR-TST-009 · SAD §16/§20
> Kaynak doğruluk: `docs/BRD.md` (§9.16/§10.3/§19), `docs/SAD.md` (§16.2/§20). Çelişkide dokümanlar esastır.

## 1. Amaç ve kapsam

0.3.x PoC hattı **tek oturum** davranışını doğruladı: 0.3.2 tek-çağrı **gecikme** dağılımını (NFR 10.1),
0.3.3 worker-başı **density**'yi (NFR 10.2), 0.3.4 medya konumunu (ADR-009). Ama tasarım kapasitesinde
**çok-oturumlu sistem davranışı** — eş zamanlı binlerce çağrı, saniyede onlarca yeni çağrı (CPS), ani
trafik, autoscale gecikmesi, backpressure — tek-oturum ölçümlerinden **türetilemez**. Bu görev,
**FR-TST-006**'nın gerektirdiği **yük + eş zamanlı çağrı test ortamının** yürütülebilir iskeletini kurar:

- bir **sentetik çağrı üreteci** (call generator) ile tasarım yükünü (CPS + eş zamanlılık) üretir,
- sistemin (worker fleet + Resource Manager: autoscaler/warm pool/admission) bu yükü nasıl **emdiğini**
  kesikli-zaman simülasyonuyla izler,
- **kapasite** (NFR 10.3), **yük altında gecikme** (NFR 10.1), **yük altında çağrı-başı kaynak**
  (FR-TST-009/§19(21)), **backpressure/graceful degradation** (FR-RES-014) ve **2x ani trafik** (NFR 10.3)
  kapılarını **HARD** uygular (geçti/kaldı → çıkış kodu),
- senaryoları (`scenarios/load-*.json`) Faz hedeflerine (BRD §20: pilot 100–250 / enterprise 1.000–3.000
  / hyperscale 10.000+) eşler.

**Kapsam (0.4.8):** sentetik yük üreteci + sistem-seviyesi kapasite/CPS/backpressure + yük-altı
gecikme/kaynak **regresyonu**. **Kapsam dışı (komşu seam, girdi alınır):** tek-çağrı gecikme dağılımı
(**0.3.2**), oturum-başı density (**0.3.3**), medya konumu (**0.3.4**), hot-path runtime dili (**0.3.5**).
Bu probe onların **çıktısını parametre** alır (base gecikme/bellek/worker kapasitesi) ve bunların yük
altında nasıl **bozulduğunu** ölçer; onları yeniden ölçmez.

> **Neden simülasyon (gerçek call-generator değil)?** 0.2.x/0.3.x hattının disiplini: **vendor-neutral**
> (ADR-002), **stdlib-only**, **credential-free**, **tekrarlanabilir**. Gerçek yük testi telefoni trunk +
> STT/TTS/LLM kotası + canlı altyapı (ve sır) gerektirir. **Mimari/yöntem değeri** sahte/gerçek sayıda
> değil, **kapı mantığının** (Little yasası kapasite, Poisson geliş, admission/backpressure muhasebesi,
> percentile, NFR eşikleri) doğru ve **canlı testte değişmeden** kullanılabilir olmasındadır. Canlı testte
> (F1 §18.5) aynı senaryo yapısı gerçek call-generator telemetrisiyle doldurulur; kapı kodu değişmez.

## 2. Mimari eşleme — yük üreteci ↔ test edilen sistem

```
   ┌──────────────────────────┐         ┌──────────────────────────────────────────────┐
   │  SENTETİK ÇAĞRI ÜRETECİ   │         │        TEST EDİLEN SİSTEM (SUT)               │
   │  (load generator)         │ çağrı/sn│  Resource Manager (SAD §16)                  │
   │                           │────────▶│   ├─ Admission/Backpressure (FR-RES-014)     │
   │  • Poisson geliş cps(t)   │         │   ├─ Autoscaler + Warm Pool (FR-RES-013)     │
   │  • ramp→soak→burst profil │         │   └─ Quota Service (concurrency/CPS)         │
   │  • tutma süresi (lognorm) │         │  Worker Fleet (her worker = N oturum, 0.3.3) │
   │  • sentetik (FR-TST-008)  │ ◀───────│   └─ oturum = hafif task (ADR-003)           │
   └──────────────────────────┘ red/kabul└──────────────────────────────────────────────┘
                                          yük-altı gecikme (0.3.2) · yük-altı bellek (0.3.3)
```

| Üreteç / sistem öğesi | Model (probe) | SAD/BRD dayanağı |
|------------------------|---------------|------------------|
| Geliş süreci (yeni çağrı/sn) | Poisson(cps(t)·Δt), tohumlu | NFR 10.3 (100 CPS) |
| Yük profili | ramp → soak → burst (2x) | NFR 10.3, SAD §16.2 |
| Tutma süresi | lognormal(ort, p95) | çağrı süresi dağılımı |
| Eş zamanlılık | Little: conc = cps × tutma | NFR 10.3 |
| Worker kapasitesi | oturum/worker (density) | 0.3.3/0.3.4, NFR 10.2 |
| Autoscale + warm pool | gecikmeli ölçek + tampon | FR-RES-013, SAD §16.1 |
| Admission/backpressure | util eşiği + CPS tavanı → graceful red | FR-RES-014, SAD §16 |
| Yük-altı gecikme | base e2e (0.3.2) × f(util) | NFR 10.1 |
| Yük-altı kaynak | base bellek (0.3.3) × (1+büyüme·util) | FR-TST-009/§19(21), FR-RES-016 |

## 3. Yük & kapasite modeli

**Little yasası (kapasite kapısının temeli):** kararlı durumda ortalama eş zamanlı oturum sayısı =
geliş hızı × ortalama tutma süresi. Senaryo **tasarım eş zamanlılığı**:

```
design_concurrency = max(target_concurrency, ⌈target_cps × mean_call_seconds⌉)
```

Fleet azami kapasite = `workers_max × worker_capacity`. **Kapasite kapısı:** kapasite ≥ tasarım
eş zamanlılık (headroom raporlanır). Bu, "tasarım kapasitesinde yük testi tamamlanabilir mi?" (FR-TST-006,
BRD §19 (11)) sorusunun nicel karşılığıdır.

**Geliş + emilim (kesikli-zaman, Δt=1 sn):** her adımda (1) tutma süresi dolan oturumlar ayrılır,
(2) autoscaler talebe göre worker sağlar (warm pool tamponu + `scale_step/scale_up_seconds` tepki
gecikmesi), (3) Poisson geliş üretilir, (4) admission `util_threshold·kapasite` ve `max_cps` tavanına
kadar kabul eder; fazlası **graceful reddedilir ve muhasebelenir** (sessiz düşüş yok — FR-RES-014),
(5) kabul edilen her oturuma tutma + yük-altı gecikme/bellek örneklenir.

**Tıkanma (congestion) modeli:** doluluk arttıkça kuyruk/çekişme gecikmesi büyür:
`f(util) = 1 + k · util/(1−util)` (util→1'de patlamayı önlemek için tabanlı/tavanlı). Yük-altı e2e =
base_e2e (0.3.2 profilinden) × f(util). Yük-altı bellek = base_bellek (0.3.3) × (1 + büyüme·util).

## 4. Kapılar (HARD = çıkış kodunu belirler)

| Kapı | Eşik | Kaynak |
|------|------|--------|
| `capacity_adequate` | fleet kapasite ≥ tasarım eş zamanlılık | NFR 10.3 / FR-TST-006 |
| `cps_sustained` | admission_cps ≥ target_cps **ve** steady soak red ≤ bütçe (≤%1) | NFR 10.3 / FR-RES-014 |
| `latency_under_load` | yük-altı e2e **P95 ≤ 1.200 ms** ve **P99 ≤ 2.000 ms** | NFR 10.1 |
| `resource_under_load` | yük-altı çağrı-başı bellek **P95 ≤ 15 MB** | FR-TST-009 / FR-RES-016 / §19(21) |
| `backpressure_graceful` | admission `util_threshold < 1.0` **ve** gözlenen `max_util ≤ 1.02` (çökme yok, red muhasebeli) | FR-RES-014 |
| `burst_2x_absorbed` | burst penceresinde red ≤ bütçe (≤%5) ve util ≤ 1.02 (burst yoksa yumuşak) | NFR 10.3 |

**Yumuşak (bilgilendirici):** `generator_reached_load` — ulaşılan peak eş zamanlılık ≥ tasarımın %85'i
(üretecin tasarım yükünü gerçekten sürebildiğini gösterir; fill dinamiği nedeniyle çıkış kodunu belirlemez).

> **Backpressure semantiği (FR-RES-014):** "graceful" = aşırı yükte kaynak **çökmek** yerine yeni çağrı
> **kontrollü reddedilir/kuyruğa alınır** ve red **muhasebelenir**. Kapı bunu iki koşulla doğrular:
> admission eşiği 1.0'ın altında (yani kapasite tam dolmadan kabul durur) **ve** gözlenen doluluk ~1.0'ı
> aşmaz (oversaturation/çökme yok). `util_threshold ≥ 1.0` bir konfigürasyon hatasıdır: sistem doyana
> kadar kabul eder → gecikme patlar → kapı eler.

## 5. Senaryolar (`scenarios/load-*.json`)

| Senaryo | Faz / hedef | Beklenen | Gösterdiği |
|---------|-------------|----------|------------|
| `load-pilot` | F1 pilot, 250 conc / 3 CPS | 🟢 geçer | Geniş headroom; pilot yük testi güvenli |
| `load-enterprise` | F2, 3.000 conc / 30 CPS | 🟢 geçer | Autoscale + warm pool + 2x burst emilimi |
| `load-hyperscale` | F3 region tavanı, 10.000 conc / 100 CPS (steady) | 🟢 geçer | NFR 10.3 başlık tasarım noktası |
| `load-burst-2x` | 2x ani trafik (NFR 10.3) | 🟢 geçer | Warm pool + autoscale ile 2x burst absorpsiyonu |
| `load-overload-degraded` | yetersiz ortam/sistem | 🔴 eler | Kapasite + backpressure + gecikme + kaynak kapılarının fiilen elemesi |

**Önemli bulgu (kapasite planlaması — BRD §10.3 notu):** NFR 10.3 "2x kısa süreli ani trafik" hedefi
**normal işletim yükü** içindir; **mutlak region tavanında** (10.000) 2x burst, fleet 10.000'e göre
boyutlandıysa **emilemez** — yalnızca admission ile **graceful shed** edilir. 2x absorpsiyon için
`workers_max`'in 2×steady'e ölçeklenmesi gerekir (planlama girdisi). Bu yüzden `load-hyperscale` steady
tavanı ölçer (`burst_seconds=0`); 2x absorpsiyon headroom'lu `load-burst-2x` senaryosunda izole doğrulanır.

## 6. Kullanım

```bash
# Self-test (credential'sız, CI) — Little/Poisson/kapı/determinizm invariant'ları
python3 docs/platform/load-testing/load_test_probe.py selftest

# Bir senaryoyu çalıştır (kapasite/CPS/gecikme/kaynak/backpressure + kapı verdict'i)
python3 docs/platform/load-testing/load_test_probe.py run --scenario docs/platform/load-testing/scenarios/load-hyperscale.json

# Senaryoları karşılaştır (tablo)
python3 docs/platform/load-testing/load_test_probe.py compare docs/platform/load-testing/scenarios/load-*.json

# Senaryo JSON şeması
python3 docs/platform/load-testing/load_test_probe.py schema
```

Çıkış kodu: `run` HARD kapı geçerse 0, kalırsa 1 (CI kapısı). `compare`/`schema`/`selftest` bilgilendirici
(selftest invariant başarısızsa 1).

## 7. İzlenebilirlik

| Gereksinim | Bu görevdeki karşılık |
|-----------|------------------------|
| FR-TST-006 (yük + eş zamanlı çağrı testi) | Sentetik çağrı üreteci + kapasite kapısı; tüm senaryolar |
| FR-TST-008 (sentetik test verisi, PII yok) | Tüm yük Poisson-üretilmiş sentetik; gerçek müşteri verisi yok |
| FR-TST-009 / §19(21) (yük-altı çağrı-başı kaynak + regresyon) | `resource_under_load` kapısı (P95 ≤ 15MB) + base'e karşı büyüme |
| NFR 10.3 (10.000 conc, 100 CPS, 2x burst) | `capacity_adequate` + `cps_sustained` + `burst_2x_absorbed` |
| NFR 10.1 (P95 ≤ 1.200) | `latency_under_load` (yük altında doğrulanır) |
| NFR 10.2 / FR-RES-016 (~15MB/oturum) | `resource_under_load`; worker_capacity 0.3.3/0.3.4'ten |
| FR-RES-014 (backpressure / graceful degradation) | `backpressure_graceful` kapısı (admission muhasebeli red) |
| FR-RES-013 (warm pool / cold-start) | Fleet modelinde warm pool tamponu + autoscale gecikmesi |
| SAD §16.2 (ölçek hedefleri) · §20 (gecikme bütçesi) | Kapasite/CPS/burst modeli · base gecikme girdisi |
| BRD §19 (11) (tasarım kapasitesinde yük testi tamamlanır) | `run` verdict'i = FR-TST-006 kabul ölçütü |

> **Sır/credential repoya yazılmaz.** Senaryolar sentetiktir (FR-TST-008); gerçek müşteri/provider verisi
> yoktur. Canlı yük testinde (F1 §18.5) gerçek call-generator/telemetri yalnız ortam değişkeni/`--url` ile
> bağlanır. Bu iskelet, kapasite planlamasını (BRD §10.3 notu) **kapı mantığı + senaryo şablonuyla** kurar.
