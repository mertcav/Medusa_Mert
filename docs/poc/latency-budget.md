# Gecikme Bütçesi Ölçümü — `latency-budget`

> **WBS 0.3.2** · `F0` · `Must` · →NFR 10.1 (BRD §10.1), SAD §20 · ADR-001/002/005
> Kaynak doğruluk: `docs/BRD.md` (§10.1), `docs/SAD.md` (§20/§6.1). Çelişkide dokümanlar esastır.

## 1. Amaç ve kapsam

0.3.1 E2E inbound PoC, akışın **bütünlüğünü** uçtan uca doğruladı ama gecikmeyi **sanal saat ile
tek-noktalı** (deterministik) ve **yumuşak** raporladı — orada P50=P95=P99 dejenere olur. Gerçek
bir sesli sistemde her bileşen (endpointing, STT, LLM, TTS, ağ, …) tur-tur **dağılır** ve insan
benzeri doğallık **kuyrukta** (P95/P99) kazanılır ya da kaybedilir. Bu görev, 0.3.1'in yumuşak
bıraktığı gecikme kapısını **HARD** kapıya çevirir:

- SAD §20 bütçe kalemlerini birer **dağılım** (sağ-çarpık lognormal) olarak modeller,
- **Monte-Carlo** örnekleme ile uç-uca **end-of-utterance → ilk agent sesi** gecikmesinin
  **P50/P95/P99**'unu üretir,
- **barge-in TTS kesme** gecikmesini ayrı bir dağılım olarak ölçer,
- sonucu **NFR 10.1** hedeflerine karşı **kapılar** (geçti/kaldı → çıkış kodu),
- bütçenin **neresinin yer kapladığını** (bileşen atfı + headroom) raporlar.

**Kapsam (0.3.2):** gecikme dağılımı + barge-in kesme + tool overhead kapısı. **Kapsam dışı (komşu
seam):** density/CPU/bellek (**0.3.3**, NFR 10.2/ADR-003), medya işleme konumu edge-vs-merkez deneyi
(**0.3.4 → ADR-009**), hot-path runtime dili (**0.3.5**, Go/Rust). Config yükleme ≤500 ms (NFR 10.1)
bir kontrol-düzlemi metriğidir; bu probe per-tur **ses** gecikmesini ölçer, onu kapsamaz.

> **Neden Monte-Carlo simülasyon?** 0.2.x/0.3.1 hattının disiplini: **vendor-neutral** (sağlayıcı
> seçme), **stdlib-only**, **credential-free**, **tekrarlanabilir**. Gerçek STT/TTS/LLM/telekom
> ölçümü sır gerektirir ve sağlayıcıya bağlar. Bunun yerine bileşen dağılımları SAD §20
> bantlarından türetilmiş **mühendislik profilleridir** (`samples/latency-*.json`). **Mimari/yöntem
> değeri** sahte/gerçek sayıda değil, **kapı mantığının** (percentile hesabı, NFR 10.1 eşikleri,
> bileşen atfı, headroom) doğru ve canlı ölçümle **değişmeden** kullanılabilir olmasındadır. Canlı
> PoC'ta (0.3.x) aynı profil yapısı gerçek provider telemetri ile doldurulur; kapı kodu değişmez.

## 2. Metrik tanımı (NFR 10.1 — yetkili)

**end-of-utterance → ilk agent sesi** = kullanıcının konuşmayı bıraktığı an → agent'ın ilk ses
paketinin çalındığı an. Bu metrik SAD §20 bütçe tablosunun **tüm kalemlerini** kapsar:

```
endpointing(VAD) + STT final + orchestrator + (RAG) + (tool) + LLM first token + TTS first byte + ağ/medya
```

**Endpointing dahildir:** kullanıcı durduktan sonra sistemin *durduğunu algılaması* da algılanan
yanıt süresinin parçasıdır; SAD §20 toplam satırı (~700 P50 / ≤1.200 P95) bu kalemi içerir.

> **0.3.1 ile uyum notu:** 0.3.1 harness'ı `end_of_utterance`'ı endpointing *sonrasına* koyup
> gecikmeyi endpointing hariç **illüstratif** raporlamıştı (yumuşak kapı, kasıtlı). 0.3.2 yetkili
> NFR 10.1 metriğine hizalanmak için **tam zinciri** (endpointing dahil) ölçer. Bu, bütçenin
> gerçekte ne kadar dar olduğunu (özellikle endpointing + LLM first-token baskınlığı) ortaya koyar.

## 3. NFR 10.1 / SAD §20 hedefleri (HARD kapı)

| Kapı | Eşik | Kaynak |
|------|------|--------|
| `e2e_p50` | P50 ≤ **700 ms** | BRD §10.1 / SAD §20 |
| `e2e_p95` | P95 ≤ **1.200 ms** | BRD §10.1 / SAD §20 |
| `e2e_p99` | P99 ≤ **2.000 ms** | BRD §10.1 |
| `bargein_p95` | barge-in kesme P95 ≤ **200 ms** | BRD §10.1 / SAD §6.1, FR-RTC-002 |
| `tool_overhead_p95` | tool overhead P95 ≤ **100 ms** | BRD §10.1 (tool yoksa yumuşak) |

HARD kapı **çıkış kodunu** belirler (`measure`: 0=geçti, 1=kaldı). Ek olarak her bileşenin kendi
P95'i SAD §20 bandına karşı **yumuşak** flag'lenir (erken-uyarı/atıf; çıkış kodunu belirlemez).

## 4. Bileşen modeli (lognormal — median + p95)

Gecikme dağılımları **sağ-çarpıktır** (nadir ama uzun kuyruklar). Her bileşen `{p50, p95}` ile bir
lognormal'a kalibre edilir:

```
X = exp(mu + sigma·Z),  Z~N(0,1)
mu    = ln(p50)                              # median = exp(mu) = p50
sigma = (ln(p95) − ln(p50)) / 1.6448…        # p95 = exp(mu + z95·sigma)
```

`p50==p95` ise `sigma=0` → **sabit** (ör. cache hit, bellek-içi orchestrator). Tur kompozisyonu:

- **Tier mix (FR-LLM-013):** `small_tier_share` olasılıkla küçük-tier first-token, aksi büyük-tier.
- **TTS cache (FR-TTS-010):** `tts_cache_hit_prob` olasılıkla `tts_cached` (~0), aksi `tts_first_byte`.
- **RAG (SAD §20):** `rag_prob` olasılıkla RAG kalemi eklenir (çoğu turda atlanır).
- **Tool (FR-TOOL-003):** `tool_prob` olasılıkla ACT overhead'i eklenir; tool turları ayrıca
  tool-overhead kapısı için biriktirilir.
- **Barge-in:** ayrı dağılım; her örnek bir barge-in olayı (TTS cancel → ses durma gecikmesi).

**Determinizm:** örnekleme `random.Random(seed)` iledir; aynı profil + aynı seed → birebir aynı
percentile (CI). Percentile yöntemi 0.3.1 `e2e_inbound_poc._percentile` ile aynı lineer
interpolasyondur.

## 5. Profil JSON (`samples/latency-*.json`)

```jsonc
{
  "name": "green-baseline",
  "samples": 20000,            // Monte-Carlo tur sayısı
  "seed": 42,                  // determinizm tohumu
  "mix": { "small_tier_share": 0.70, "rag_prob": 0.25,
           "tool_prob": 0.20, "tts_cache_hit_prob": 0.50 },
  "components": {              // her kalem: lognormal(p50, p95) — ms
     "endpointing": {"p50":140,"p95":200}, "stt_final": {"p50":100,"p95":165},
     "orchestrator": {"p50":8,"p95":22},   "rag": {"p50":130,"p95":190},
     "llm_first_small": {"p50":190,"p95":330}, "llm_first_large": {"p50":290,"p95":385},
     "tts_first_byte": {"p50":100,"p95":170},  "tts_cached": {"p50":5,"p95":12},
     "network": {"p50":45,"p95":85}, "tool": {"p50":75,"p95":96},
     "barge_in_cut": {"p50":70,"p95":150}
  }
}
```
Eksik bileşen SAD §20 orta-nokta varsayılanını alır. **Değerler illüstratiftir** — gerçek ölçüm
değil; SAD §20 bantlarından türetilmiş mühendislik dağılımı (FR-TST-008, sentetik).

## 6. Sağlanan profiller

| Profil | Senaryo | Beklenen |
|--------|---------|----------|
| `latency-green-baseline.json` | Bölgesel edge + TTS cache + ağırlıklı küçük-tier | 🟢 tüm kapılar geçer |
| `latency-tail-heavy.json` | Median bütçede ama bileşen **kuyrukları ağır** | 🔴 P50 geçer, **P95 eler** (kuyruk riski) |
| `latency-red-degraded.json` | Merkezi medya + büyük-tier ağırlıklı + zayıf cache + yüksek ağ | 🔴 P50/P95/P99 + barge-in + tool **hepsi eler** |

`tail-heavy` özellikle öğreticidir: **median/ortalama "iyi" görünse de** gecikmeyi P95/P99 belirler;
0.3.1'in tek-noktalı bakışı bu kuyruk riskini gizlerdi.

## 7. Çalıştırma

```bash
# Self-test (credential'sız, CI) — kalibrasyon/kapı/determinizm invariant'ları
python3 docs/poc/latency_budget_probe.py selftest

# Bir profili ölç → P50/P95/P99 + barge-in + bileşen atfı + NFR 10.1 kapı verdict'i
python3 docs/poc/latency_budget_probe.py measure --profile docs/poc/samples/latency-green-baseline.json

# Profilleri tablo halinde karşılaştır
python3 docs/poc/latency_budget_probe.py compare docs/poc/samples/latency-*.json

# Makine-okunur çıktı + örnek/seed override
python3 docs/poc/latency_budget_probe.py measure --profile .../latency-green-baseline.json \
    --samples 50000 --seed 7 --json-out /tmp/lat.json

# Profil şeması
python3 docs/poc/latency_budget_probe.py schema
```

## 8. Bulgular ve sonraki adımlar

- ✅ **Yumuşak → HARD:** 0.3.1'in illüstratif gecikmesi artık dağılımsal (P50/P95/P99) ve NFR 10.1
  eşiklerine karşı kapılı; green profil tüm kapıları geçer, degrade profil eler.
- 📌 **Bütçe dar — baskın kalemler:** green profilde bile bütçenin ~**%36'sı LLM first-token**, ~**%22'si
  endpointing**. P50 ≤700 ms hedefi (endpointing dahil) **iyimser** varsayımlar gerektirir (edge
  endpointing + TTS cache + ağırlıklı küçük-tier). Bu, **0.3.4 (medya konumu/ADR-009)** ve
  **0.3.5 (hot-path runtime)** için doğrudan girdi: endpointing/ağ kaleminin edge'de tutulması ve
  düşük-gecikmeli runtime, P95/P99 headroom'unu belirler.
- 📌 **Kuyruk yönetimi kritik:** `tail-heavy` profili, median bütçede olsa bile ağır bileşen
  kuyruklarının **P95 kapısını eleyebileceğini** gösterir → LLM first-token varyansı + ağ jitter'ı
  hedeflenmeli (model tiering, bölgesel edge, streaming).
- → **Canlı PoC (0.3.x):** aynı profil yapısı gerçek provider telemetri ile doldurulur; **0.2.6
  provizyonel** sağlayıcı seçimi gerçek first-token/first-byte dağılımları ile bağlanır (kapı kodu
  değişmez). DPA/alt-işleyen (17.2.2) ile birlikte.

> **Sır/credential repoya yazılmaz.** Profiller sentetiktir (FR-TST-008); gerçek müşteri/provider
> verisi yok. Canlı ölçüm yalnız `--url`/ortam değişkeni ile (0.3.x canlı PoC).
