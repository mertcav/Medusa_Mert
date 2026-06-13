# Density Ölçümü (Oturum/Worker) — `density`

> **WBS 0.3.3** · `F0` · `Must` · →NFR 10.2 (BRD §10.2), ADR-003 · SAD §15/§16.2
> Kaynak doğruluk: `docs/BRD.md` (§10.2), `docs/SAD.md` (§15.2/§16.2), `docs/adr/0003-*.md`.
> Çelişkide dokümanlar esastır.

## 1. Amaç ve kapsam

0.3.2 gecikme bütçesini **HARD** kapıya çevirdi (NFR 10.1). Bu görev, platformun ticari
farklılaşmasının diğer yarısını — **yoğunluk (density)** — aynı disiplinle HARD kapıya çevirir.
NFR 10.2 iki ölçülebilir hedef tanımlar:

1. **Oturum-başı bellek** (medya tamponları **hariç**) ≤ **~15 MB/oturum** (FR-RES-016).
2. **Referans worker (8 vCPU / 16 GB) başına eş zamanlı oturum** ≥ **250–500**
   (medya işleme konumuna göre).

Bu probe oturum bellek/CPU ayak izini birer **dağılım** (sağ-çarpık lognormal — uzun geçmişli /
büyük bağlamlı oturumlar daha çok tüketir) olarak modeller, **Monte-Carlo** ile oturum-başı bellek
**P50/P95/P99**'unu üretir, referans worker'a **bellek ∩ CPU** kapasitesini hesaplar ve density'yi
**NFR 10.2** hedeflerine karşı **kapılar** (geçti/kaldı → çıkış kodu).

**Kapsam (0.3.3):** oturum-başı bellek/CPU + worker density kapısı. **Kapsam dışı (komşu seam):**
gecikme dağılımı (**0.3.2**, NFR 10.1), medya işleme konumu edge-vs-merkez **kararı** (**0.3.4 →
ADR-009**), hot-path runtime dili Go/Rust doğrulaması (**0.3.5**, ADR-003). Bu probe density'yi
ölçer; gecikme ölçmez. Medya konumu burada bir **duyarlılık girdisidir** (density'yi nasıl
etkilediğini gösterir), **kararı 0.3.4'e bırakılır**.

> **Neden Monte-Carlo simülasyon?** 0.2.x/0.3.x hattının disiplini: **vendor-neutral** (sağlayıcı/dil
> seçmez), **stdlib-only**, **credential-free**, **tekrarlanabilir**. Gerçek RSS/heap ölçümü çalışan
> hot-path kodu (0.3.5 Go/Rust) ve canlı yük gerektirir. Bunun yerine bileşen dağılımları SAD §15/§20
> + ADR-003 lean-runtime hedeflerinden türetilmiş **mühendislik profilleridir** (`samples/density-*.json`).
> **Mimari/yöntem değeri** sahte/gerçek sayıda değil, **kapı mantığının** (percentile, bellek ∩ CPU
> kapasite hesabı, NFR 10.2 eşikleri, bileşen atfı) doğru ve canlı ölçümle **değişmeden**
> kullanılabilir olmasındadır. Canlı PoC'ta (0.3.5) aynı profil yapısı gerçek profiler telemetri ile
> doldurulur; kapı kodu değişmez.

## 2. Metrik tanımı (NFR 10.2 — yetkili)

**oturum-başı orkestratör belleği (medya hariç)** = bir aktif oturumun Conversation Orchestrator
worker'ında tuttuğu bellek:

```
session_state + dialogue_memory + prompt_context + (rag_context) + adapter_state + runtime_overhead
```

**Medya tamponları DAHİL DEĞİLDİR** (jitter buffer, RTP, ses frame). SAD §6/§13: *"büyük tamponlar
Media Gateway'de, ham veri Analytics Plane'de"*. 15 MB bütçesi (FR-RES-016) yalnız bu **medya-hariç**
orkestratör ayak izine uygulanır.

**density (worker başına eş zamanlı oturum)** = `min(bellek-kapasitesi, CPU-kapasitesi)`:

```
kullanılabilir bellek = (mem_gb·1024 − os_reserve_mb) · (1 − mem_headroom_pct)
CPU bütçesi (mcore)   = vcpu · 1000 · cpu_target_util
density               = min( kullanılabilir_bellek / oturum_bellek, CPU_bütçesi / oturum_CPU )
```

- **mean-packing** (birincil/kapı): N **bağımsız** oturumun toplam tüketimi yoğunlaşır (CLT) →
  ortalamaya yakınsar; headroom (bellek %15, CPU %30) toplam varyansı karşılar. İstatistiksel olarak
  doğru kapasite budur.
- **p95-packing** (yumuşak alt-sınır): her oturum p95'te varsayılır → muhafazakar, raporlanır.

> **Medya işleme konumu (→0.3.4/ADR-009):** Medya worker'da **eş-konumlu** ise oturum-başı medya
> bellek/CPU overhead'i density hesabına eklenir (ama 15 MB **bütçe kapısına eklenmez** — medya
> hariçtir). Bu, NFR 10.2'deki *"250–500 (medya işleme konumuna göre)"* aralığının nereden geldiğini
> gösterir: medya edge'de → üst uç; eş-konumlu → alt uç. **Karar 0.3.4'tedir; bu probe yalnız
> duyarlılığı ölçer.**

## 3. NFR 10.2 hedefleri (HARD kapı)

| Kapı | Eşik | Kaynak |
|------|------|--------|
| `mem_budget_p95` | oturum belleği (medya hariç) P95 ≤ **15 MB** | BRD §10.2 / FR-RES-016 |
| `density_min` | density (mean-packing) ≥ **250** oturum/worker | BRD §10.2 (alt sınır) |
| `density_target` | density ≥ **500** (stretch, **yumuşak**) | BRD §10.2 (üst sınır) |

HARD kapı **çıkış kodunu** belirler (`measure`: 0=geçti, 1=kaldı). `density_target` yumuşaktır
(stretch hedef; çıkış kodunu belirlemez — medya eş-konumlu dağıtımda alt uca düşmek meşrudur).

## 4. Bileşen modeli (lognormal — median + p95)

Bellek/CPU ayak izleri **sağ-çarpıktır** (uzun geçmişli oturumlar uzun kuyruk). Her bileşen `{p50,
p95}` ile bir lognormal'a kalibre edilir (0.3.2 ile **birebir aynı** `LogNormalComponent`):

```
X = exp(mu + sigma·Z),  Z~N(0,1);  mu=ln(p50);  sigma=(ln(p95)−ln(p50))/1.6448…
```

Oturum kompozisyonu (mix):
- **Uzun oturum (FR-RES-010):** `long_session_share` olasılıkla büyük `dialogue_long`, aksi
  `dialogue_memory`. Geçmiş özetlenmezse bellek büyür (FR-RES-010/SAD §6.2 özetleme bunu sınırlar).
- **RAG (FR-KB-011):** `rag_active_share` olasılıkla `rag_context` eklenir (trimmed; çoğu oturumda yok).
- **Adapter durumu (FR-RES-006):** pooled bağlantı durumu, oturum-başı amorti.
- **Medya eş-konumlu (0.3.4/ADR-009):** `media_colocated=true` ise medya bellek/CPU density'ye
  **ayrı RNG stream'inden** eklenir → 15 MB bütçe stream'ini **perturbe etmez** (bütçe medya
  konumundan bağımsız kalır).

**Determinizm:** örnekleme `random.Random(seed)` (bütçe/CPU) + `random.Random(seed+7)` (medya)
iledir; aynı profil + aynı seed → birebir aynı percentile (CI). Percentile yöntemi 0.3.1/0.3.2 ile
aynı lineer interpolasyondur.

## 5. Profil JSON (`samples/density-*.json`)

```jsonc
{
  "name": "green-baseline",
  "samples": 20000, "seed": 42,
  "worker": { "vcpu": 8, "mem_gb": 16, "os_reserve_mb": 1024,
              "mem_headroom_pct": 0.15, "cpu_target_util": 0.70 },
  "mix": { "rag_active_share": 0.30, "long_session_share": 0.20, "media_colocated": false },
  "components_mb": {                 // her kalem: lognormal(p50, p95) — MB
     "session_state": {"p50":1.2,"p95":1.8}, "dialogue_memory": {"p50":3.2,"p95":5.8},
     "dialogue_long": {"p50":6.5,"p95":10.0}, "prompt_context": {"p50":1.4,"p95":2.0},
     "rag_context": {"p50":1.8,"p95":3.2}, "adapter_state": {"p50":1.4,"p95":2.2},
     "runtime_overhead": {"p50":0.9,"p95":1.4}, "media_colocated": {"p50":7.0,"p95":10.0}
  },
  "components_mcore": {              // her kalem: lognormal(p50, p95) — millicore
     "cpu_session": {"p50":9.0,"p95":20.0}, "cpu_media": {"p50":5.0,"p95":11.0}
  }
}
```
Eksik bileşen lean-runtime varsayılanını alır. **Değerler illüstratiftir** — gerçek profiler değil;
SAD §15/§20 + ADR-003 hedeflerinden türetilmiş mühendislik dağılımı (FR-TST-008, sentetik).

## 6. Sağlanan profiller

| Profil | Senaryo | Beklenen |
|--------|---------|----------|
| `density-green-baseline.json` | Lean async orkestratör + medya **edge'de** | 🟢 bütçe + density (≥500 stretch dahil) geçer |
| `density-media-colocated.json` | Aynı orkestratör; medya **eş-konumlu** | 🟢 HARD geçer (density≥250) ama **stretch 500'ü ıskalar** |
| `density-red-degraded.json` | thread-per-call / GC-ağır + özetsiz geçmiş (**ADR-003 ihlali**) | 🔴 bütçe>15 + density<250 |

`media-colocated` özellikle öğreticidir: 15 MB bütçe **değişmez** (medya hariç) ama density CPU-bağlı
~%35 düşer → NFR 10.2 "250–500" aralığının alt ucu. `red-degraded`, **ADR-003'ün neden bir mimari
gereklilik** olduğunu gösterir.

## 7. Çalıştırma

```bash
# Self-test (credential'sız, CI) — kalibrasyon/kapı/determinizm/medya-hariç invariant'ları
python3 docs/poc/density_probe.py selftest

# Bir profili ölç → bellek P50/P95/P99 + CPU + density + bileşen atfı + NFR 10.2 kapı verdict'i
python3 docs/poc/density_probe.py measure --profile docs/poc/samples/density-green-baseline.json

# Profilleri tablo halinde karşılaştır
python3 docs/poc/density_probe.py compare docs/poc/samples/density-*.json

# Makine-okunur çıktı + örnek/seed override
python3 docs/poc/density_probe.py measure --profile .../density-green-baseline.json \
    --samples 50000 --seed 7 --json-out /tmp/density.json

# Profil şeması
python3 docs/poc/density_probe.py schema
```

## 8. Bulgular ve sonraki adımlar

- ✅ **HARD kapı:** Oturum-başı bellek (medya hariç) P95 ≤ 15 MB ve worker density ≥ 250 artık
  dağılımsal ve NFR 10.2'ye karşı kapılı; green profil tüm kapıları (≥500 stretch dahil) geçer,
  degrade profil eler.
- 📌 **Density CPU-bağlıdır, bellek-bağlı değil:** Referans 16 GB worker'da 15 MB/oturum bütçe ~1300
  oturuma yer verir; gerçek tavanı **CPU** koyar (green ≈552, bottleneck=CPU). Yani 250–500 hedefini
  belleğin değil **per-oturum CPU verimliliğinin** belirlediği gösterilir → doğrudan **0.3.5 (hot-path
  Go/Rust, ADR-003)** girdisi: async, düşük-CPU runtime density'yi belirler.
- 📌 **Medya konumu density'yi ~%35 keser (bütçeyi DEĞİL):** `media-colocated` profilinde 15 MB bütçe
  değişmeden density 552→355'e düşer. Bu, NFR 10.2 "250–500" aralığını **medya işleme konumunun**
  açıkladığını doğrular → doğrudan **0.3.4 (edge-vs-merkez → ADR-009)** girdisi.
- 📌 **Diyalog belleği baskın kalem:** green profilde bütçenin ~**%42'si diyalog belleği**. Özetleme
  (FR-RES-010/SAD §6.2) ve uzun-oturum payı 15 MB'ı belirleyen başlıca kaldıraçtır; `red-degraded`
  özetsiz büyümenin bütçeyi nasıl deldiğini gösterir.
- → **Canlı PoC (0.3.5):** aynı profil yapısı gerçek Go/Rust profiler (RSS/heap + CPU) telemetri ile
  doldurulur; ADR-003 durumu `Önerilen`→`Kabul`'e ölçümle bağlanır (kapı kodu değişmez).

> **Sır/credential repoya yazılmaz.** Profiller sentetiktir (FR-TST-008); gerçek müşteri/provider
> verisi yok. Canlı ölçüm yalnız çalışan hot-path + profiler ile (0.3.5).
