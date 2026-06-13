# Medya İşleme Konumu Deneyi — edge vs merkez → ADR-009 — `media-placement`

> **WBS 0.3.4** · `F0` · `Must` · →**ADR-009** (medya işleme konumu); NFR 10.1, NFR 10.2 · SAD §6.4/§20/§23
> Kaynak doğruluk: `docs/BRD.md` (§10.1/§10.2, §22-19), `docs/SAD.md` (§6.4/§20/§23),
> `docs/adr/0005-edge-vad-endpointing.md`, `docs/adr/0009-medya-isleme-konumu.md`. Çelişkide dokümanlar esastır.

## 1. Amaç ve kapsam

ADR-009 — *"RTP/medya sonlandırma + codec + VAD/endpointing + barge-in algılama **edge'de mi yoksa
merkezde mi**?"* — bilinçli olarak **AÇIK** bırakılmış, kapanışı bu deneye bağlanmıştı (SAD §23,
BRD §22-19). Bu görev, kararı **ölçüm temelli** kapatır: medya konumu gecikme (NFR 10.1) ile density
(NFR 10.2) arasında doğrudan bir ödünleşim olduğundan, **0.3.2 gecikme** ve **0.3.3 density** HARD
kapılarını **tek bir karar deneyinde** birleştirir, topoloji adaylarını her iki kapıya karşı ölçer,
ve HARD-geçen adaylar arasında ağırlıklı bir **karar matrisiyle** öneri üretir → **ADR-009 kararı**.

**Kapsam (0.3.4):** edge / merkez / hibrit topolojilerinin gecikme + density ölçümü + birleşik kapı +
ADR-009 önerisi. **Kapsam dışı (komşu seam):** hot-path runtime dili Go/Rust doğrulaması (**0.3.5**,
ADR-003); gecikme bütçesinin kendisi (**0.3.2**, NFR 10.1) ve density modelinin kendisi (**0.3.3**,
NFR 10.2) — bu probe onları **yeniden ölçmez**, topolojiye-bağlı kalemleri değiştirip **kapıyı
yeniden uygular**.

> **Neden Monte-Carlo, neden bu disiplin?** 0.2.x/0.3.x hattıyla aynı: **vendor/dil-nötr** (ADR-002/003),
> **stdlib-only**, **credential-free**, **deterministik**. `LogNormalComponent` + `percentile`
> 0.3.1/0.3.2/0.3.3 ile **birebir aynıdır**; yalnız topolojiye-bağlı girdiler (medya/ağ kalemi,
> barge-in kesme, medya eş-konumu) değişir. Gerçek değer sahte sayıda değil, **kapı + karar mantığının**
> (percentile, birleşik NFR 10.1/10.2 kapısı, ağırlıklı karar matrisi) canlı telemetri ile
> **değişmeden** kullanılabilir olmasındadır.

## 2. Karar problemi (ne değişir, ne değişmez)

Medya konumu **yalnız iki gecikme kalemini** ve **bir density girdisini** etkiler; zincirin geri
kalanı topolojiden bağımsızdır:

| Etkilenen | Nasıl | Kapı |
|-----------|-------|------|
| **medya/ağ kalemi** (SAD §20 ~50–100ms) | edge → çağrı girişine yakın sonlandırma, düşük; merkez → caller RTP'si merkeze WAN ile taşınır, yüksek | e2e P95 (NFR 10.1) |
| **barge-in kesme** (≤200ms) | edge VAD → yerel algılama, hızlı iptal; merkez → ses merkeze + iptal geri → gidiş-dönüş büyür | barge-in P95 (NFR 10.1, ADR-005) |
| **medya eş-konumu** (density) | medya orkestratör worker'ında eş-konumlu ise CPU/bellek overhead'i density'ye eklenir (15MB **bütçesine değil** — medya hariç) | density (NFR 10.2) |

**Değişmeyen** (topolojiden bağımsız, `rest_of_chain`): endpointing kararı + STT final flush +
orchestrator/policy/routing + LLM first-token + TTS first-byte. Bu, gecikme dağılımının çoğunu
oluşturur (0.3.2 bulgusu: bütçe dar, ~%36 LLM first-token + ~%22 endpointing) — medya konumu bu
büyük kalemleri **değiştirmez**, yalnız ince ama **kritik** kuyruğu (medya/ağ + barge-in) belirler.

## 3. Değerlendirilen topolojiler

| Topoloji | Tanım | Gecikme | Density | Operasyon |
|----------|-------|---------|---------|-----------|
| **edge** | Medya bölgesel POP'ta (çağrı girişine yakın) sonlandırılır; ayrı medya katmanı (orkestratöre eş-konumlu **değil**) | En düşük medya/ağ + hızlı barge-in | Yüksek (medya ayrı) | **Yüksek karmaşıklık** — her POP'ta tam dağıtık medya; residency POP yayılımıyla zorlaşır |
| **merkez (central)** | Tüm medya merkezi bölgede; caller RTP'si merkeze WAN ile taşınır; orkestratöre eş-konumlu | Yüksek medya/ağ + **barge-in ≤200ms riski** | Düşük (eş-konumlu medya CPU) | En basit/ucuz |
| **hibrit** | Hafif iş (VAD/endpointing + barge-in algılama) **edge'de** (ADR-005); ağır medya ayrı bölgesel medya-gateway katmanında (eş-konumlu **değil**) | Hızlı barge-in + orta medya/ağ | Yüksek (medya ayrı) | Orta — yalnız hafif VAD edge'de, ağır medya konsolide |

> Hibrit, **ADR-005 (edge VAD/endpointing) ile zaten uyumludur**: barge-in algılaması zaten edge'de
> yapılmak zorundadır (≤200ms). Hibrit bunu doğal sonucuna taşır — *latency-kritik hafif işi edge'e,
> ağır/durumlu işi ayrı (eş-konumsuz) merkezi/bölgesel medya katmanına* (SAD §4.2 plane ayrımı).

## 4. Birleşik kapı (NFR 10.1 + NFR 10.2 — HARD = çıkış kodu)

| Kapı | Eşik | Kaynak |
|------|------|--------|
| `e2e_p50` | end-of-utterance→ilk ses P50 ≤ **700 ms** | NFR 10.1 |
| `e2e_p95` | P95 ≤ **1200 ms** | NFR 10.1 |
| `e2e_p99` | P99 ≤ **2000 ms** | NFR 10.1 |
| `bargein_p95` | barge-in kesme P95 ≤ **200 ms** | NFR 10.1, ADR-005, FR-RTC-002 |
| `mem_budget_p95` | oturum belleği (medya hariç) P95 ≤ **15 MB** | NFR 10.2, FR-RES-016 |
| `density_min` | density ≥ **250** oturum/worker | NFR 10.2 (alt sınır) |
| `density_target` | density ≥ **500** (stretch, **yumuşak**) | NFR 10.2 (üst sınır) |

Bir topoloji **her iki HARD kapıyı** (NFR 10.1 + NFR 10.2) geçmezse karar dışı kalır (`evaluate`
çıkış kodu 1). `density_target` yumuşaktır (çıkış kodunu belirlemez).

## 5. Karar matrisi (ADR-009 — ağırlıklı; toplam 1.0)

HARD-geçen adaylar arasında öneri = en yüksek ağırlıklı skor. **Ölçülen** boyutlar simülasyondan;
**nitel** boyutlar profilde beyan edilir (mühendislik yargısı; 0.2.x rubrik soft-ölçüt disiplini).

| Boyut | Ağırlık | Kaynak | Tip |
|-------|---------|--------|-----|
| `latency` | 0.20 | e2e P95 headroom (1200ms'e pay) | ölçülen |
| `bargein` | 0.15 | barge-in P95 headroom (200ms'e pay) — ADR-005 | ölçülen |
| `density` | 0.20 | density / stretch hedef (500) | ölçülen |
| `ops` | 0.20 | operasyonel basitlik (dağıtık ↔ konsolide) | beyan |
| `cost` | 0.10 | altyapı maliyeti | beyan |
| `residency` | 0.15 | veri-yerleşim/residency esnekliği (NFR 10.7) | beyan |

## 6. Sağlanan profiller (`samples/media-*.json`)

| Profil | Senaryo | Beklenen |
|--------|---------|----------|
| `media-edge.json` | Medya bölgesel edge POP'ta; ayrı katman | 🟢 her iki kapı geçer; karar skoru ops/cost/residency cezasıyla **düşük** |
| `media-central.json` | Tüm medya merkezde + eş-konumlu | 🔴 **barge-in P95 > 200ms eler** (ADR-005); density stretch'i de ıskalar |
| `media-hybrid.json` | Edge VAD/barge-in (ADR-005) + ayrı medya katmanı | 🟢 her iki kapı geçer; **en yüksek karar skoru → ADR-009 önerisi** |

İllüstratif değerler (FR-TST-008, sentetik); SAD §20/§15 + ADR-003/005 hedeflerinden türetilmiş
mühendislik dağılımı — gerçek telemetri değil.

## 7. Çalıştırma

```bash
# Self-test (credential'sız, CI) — kalibrasyon/kapı/karar/determinizm invariant'ları
python3 docs/poc/media_placement_probe.py selftest

# Bir topolojiyi ölç → gecikme + barge-in + density + birleşik NFR 10.1/10.2 kapı verdict'i
python3 docs/poc/media_placement_probe.py evaluate --profile docs/poc/samples/media-hybrid.json

# Topolojileri karşılaştır + ADR-009 ÖNERİSİ üret
python3 docs/poc/media_placement_probe.py compare docs/poc/samples/media-*.json

# Profil şeması + karar ağırlıkları
python3 docs/poc/media_placement_probe.py schema
```

## 8. Bulgular ve ADR-009 kararı

İllüstratif profillerle ölçüm (N=20000, seed=42):

| Topoloji | e2e P95 | barge-in P95 | density | karar skoru | verdict |
|----------|---------|--------------|---------|-------------|---------|
| edge | ~1018 ms | ~166 ms | ~554 | 0.486 | 🟢 geçer |
| central | ~1079 ms | **~266 ms** | ~354 | 0.552 | 🔴 **barge-in eler** |
| hybrid | ~1034 ms | ~171 ms | ~554 | **0.605** | 🟢 **önerilen** |

- ✅ **Merkez topoloji barge-in kapısından elenir.** Tüm medyayı merkeze taşımak barge-in kesme
  sinyalini ~266ms'e çıkarır (≤200ms eler) — bu, **ADR-005'in (edge VAD/endpointing) neden zaten bir
  mimari gereklilik** olduğunu doğrular: barge-in algılaması edge'de olmak **zorundadır**. Merkez ayrıca
  eş-konumlu medya CPU'suyla density'yi ~554→354'e düşürür (stretch 500'ü ıskalar).
- ✅ **edge ve hibrit her iki HARD kapıyı geçer**, ama **hibrit en yüksek karar skoruna** sahiptir:
  barge-in/gecikme/density'de edge'e çok yakın, fakat operasyonel basitlik + maliyet + residency
  boyutlarında belirgin üstün (edge her POP'ta tam dağıtık medya işleme gerektirir; hibrit yalnız
  hafif VAD'ı edge'de tutar, ağır medyayı konsolide eder).
- 📌 **Density CPU-bağlı kalır** (0.3.3 bulgusuyla tutarlı): geçen topolojilerde 15MB bütçe
  ~1345 oturuma yer verir, tavanı **CPU** koyar (bottleneck=cpu). Medya konumu density'yi yalnız
  eş-konumlu CPU overhead'i üzerinden etkiler → ayrı katman (edge/hibrit) density'yi korur.
- → **ADR-009 KARARI: Hibrit (Seçenek 3).** *Edge VAD/endpointing + barge-in algılama (ADR-005); ağır
  medya işleme ayrı bölgesel medya-gateway katmanında — orkestratör worker'ına eş-konumlu değil.*
  ADR-009 durumu `Açık`→`Kabul`'e geçer; seçilen seçenek kayıtta dondurulur. Bağımlı görevler
  (2.2.x medya gateway) bu kararla çözülür.
- → **Canlı PoC (0.3.5 + telemetri):** aynı profil yapısı gerçek medya/ağ + barge-in + RSS/CPU
  telemetri ile doldurulur; kapı + karar mantığı değişmez. Edge POP'un bölgesel kapsamı (NFR 10.7
  residency) ve barge-in'in gerçek WAN gidiş-dönüşü canlı pilotta doğrulanır.

> **Sır/credential repoya yazılmaz.** Profiller sentetiktir (FR-TST-008); gerçek müşteri/provider
> verisi yok. Canlı ölçüm yalnız çalışan hot-path + telemetri ile (0.3.5).
