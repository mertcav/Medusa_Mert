# LLM (Büyük Dil Modeli) Sağlayıcı Değerlendirmesi

| Alan | Değer |
|------|-------|
| **WBS** | 0.2.4 |
| **Faz · Öncelik** | F0 · Must |
| **İz** | FR-LLM-001..014; SR-LLM-001..014; FR-RES-005 (tiering density); FR-KB-010 (no-log); NFR 10.1/10.7; SAD §8.1 (LlmAdapter), §9 (LLM orkestrasyonu), §20 (gecikme bütçesi); ADR-001/002 |
| **Durum** | v1.0 — ölçüt + metodoloji + harness hazır; **canlı sağlayıcı ölçümü 0.3.x PoC'ta** |
| **Tarih** | 2026-06-13 |

> **Sağlayıcı-nötr (ADR-002):** Bu doküman bir LLM sağlayıcısı/modeli **seçmez**. Sağlayıcıları ölçüt +
> metodoloji üzerinden ele alır; nihai seçim **0.2.6** karar raporunda (kalite + gecikme + maliyet +
> residency + DPA/no-train + risk) bütünsel yapılır. ADR-002 gereği kategori başına **≥2 sağlayıcı +
> fallback** (FR-LLM-010) ve **küçük/büyük tier** (FR-LLM-013) korunur. SAD §21'deki teknoloji önerileri
> (örn. büyük model için bir sınıf, küçük/hızlı için başka) yalnız mimari öneridir; bu eval bağlayıcı
> değildir.

---

## 1. Kapsam ve amaç
LLM sağlayıcılarını gerçek-zamanlı sesli diyalog gerçeğine (streaming, düşük first-token, çift dil)
sadık, **sağlayıcı-nötr** ve **tekrarlanabilir** bir ölçüt setiyle değerlendirmek; özellikle görev
başlığındaki boyutlar:
- **First-token gecikmesi** (TTFT — FR-LLM-004) → **SAD §20** "LLM first token ~200–400 ms (P95)" kalemine
  kapı. Bu, uçtan uca gecikme bütçesinin (NFR 10.1: P95 ≤ 1.200 ms) **en büyük tek kalemidir**.
- **Küçük/büyük tier** (FR-LLM-013) → sağlayıcı hem küçük/hızlı hem büyük model sunmalı; **küçük tier daha
  hızlı** (SAD §20). Küçük-tier TTFT ayrı, daha sıkı kapıdan geçer.
- **"No-train" / no-log endpoint** (FR-LLM-012 / FR-KB-010) → tenant verisi eğitime kapalı varsayılan;
  regüle/AB/UK için **zorunlu** uygunluk kapısı.
- **Bölgesel endpoint / residency** (NFR 10.7) → veriyi tenant home-region'da işleyen bölgesel endpoint
  (region pinning) zorunlu uygunluk kapısı;

ayrıca destekleyici: **streaming token sürekliliği** (FR-LLM-004 — token stall ⇒ downstream TTS ölü hava),
**schema-doğrulamalı tool-call doğruluğu** (FR-LLM-008), **görev kalitesi** (yanıt doğruluğu, **en-kötü-dil**
EN+TR — FR-LLM-001/003), **fallback + ≥2 model** (FR-LLM-010/001).

Kapsam **dışı** (ilgili ama ayrı görevler): STT (0.2.2), TTS (0.2.3), telekom medya taşıma gecikmesi
(0.2.1); LLM Router/tiering **uygulaması** (5.1–5.3), semantic cache (5.4 / FR-LLM-014), prompt-injection
guard (3.3.1 / FR-LLM-007), output policy guard (3.3.2 / FR-LLM-009), context özetleme (3.2.2 / FR-LLM-005),
LLM fallback **uygulaması** (4.3.3). Bu görev **ölçüt + metodoloji + ölçüm hattı** üretir; **canlı sağlayıcı
ölçümü** kimlik bilgisi gerektirir ve **0.3.x PoC**'ta her aday için alınıp matrise işlenir.

## 2. LlmAdapter sözleşmesi (ölçülen yüzey)
Değerlendirme, SAD §8.1 / `API.md §11.4` **LlmAdapter** SPI'sine göre yapılır — sağlayıcıya özel biçimler
adapter arkasında normalize edilir (vendor-neutral):

```
complete(req: LlmRequest): AsyncStream<LlmChunk>   // stream token VEYA tool-call (FR-LLM-004/008)
LlmRequest { messages[]; tools[]; model; maxTokens; temperature; noTrain }   // noTrain=FR-LLM-012
LlmChunk   = TokenChunk{delta} | ToolCallChunk{toolName, argumentsJson, callId}   // serbest metin değil
AdapterConfig { region; dataRetention∈{NONE,EPHEMERAL,PROVIDER_DEFAULT}; noTrain(default true); ... }
```
Bir sağlayıcı eval'a girebilmek için bu sözleşmeyi (streaming first-token, schema-doğrulamalı tool-call,
`noTrain` + `dataRetention=NONE/EPHEMERAL`, bölgesel `region` pinning, **küçük + büyük model**)
karşılamalıdır; karşılamayan yetenek ilgili ölçütte sıfır alır. Tiering/cache/fallback **orchestrator**
tarafındadır (SAD §9); adapter tek sağlayıcıyı temsil eder — ama eval, sağlayıcının **iki tier sunup
sunmadığını** ve her tier'ın TTFT'sini ölçer.

## 3. Değerlendirme ölçütleri ve ağırlıkları
First-token (genel + küçük-tier) ve uygunluk (no-train + bölgesel) birincil; karar için ağırlıklı rubrik:

| # | Ölçüt | Ağırlık | Nasıl ölçülür | İz |
|---|-------|--------:|----------------|-----|
| C1 | **First-token gecikmesi** (TTFT genel, P95) | 18% | harness `score` → SAD §20 kapısı | FR-LLM-004, NFR 10.1, SAD §20 |
| C2 | **Küçük-tier first-token** (P95) | 12% | harness (tier=small TTFT) → tiering kapısı | FR-LLM-013, FR-RES-005, SAD §20 |
| C3 | **Görev kalitesi** (EN+TR; en-kötü-dil) | 18% | harness (kalite dış girdi) | FR-LLM-001/003 |
| C4 | **No-train / no-log endpoint** | 12% | config inceleme (knock-out) | FR-LLM-012, FR-KB-010 |
| C5 | **Bölgesel endpoint / residency** | 12% | config inceleme (knock-out) | NFR 10.7 |
| C6 | **Streaming token sürekliliği** (stall) | 10% | harness (inter-token, stall) | FR-LLM-004 |
| C7 | **Tool-call doğruluğu** (schema-validated) | 12% | harness (geçerli tool-call oranı) | FR-LLM-008 |
| C8 | **≥2 model tier + fallback** | 6% | yetenek + taksonomi | FR-LLM-001/010 |

> C1–C3, C6 harness ile **sayısal** ölçülür; C4/C5 config uygunluk; C7 sayısal-soft; C8 yetenek. Sayısal/
> uygunluk **knock-out kapıları**: C1 (TTFT), C2 (küçük-tier), C3 (kalite en-kötü-dil), C4 (no-train),
> C5 (bölgesel), C6 (stall=0) — herhangi biri **KIRMIZI/fail** ise aday elenir. **C2 ayrıca tiering
> varlığını da zorlar**: sağlayıcı küçük+büyük model sunmazsa (FR-LLM-013 ihlali) C2 doğrudan KIRMIZI.
> C7 (tool-call) **soft** uyarı eşiğidir (0.2.6'da bütünsel). Maliyet/sözleşme ağırlığı **0.2.6**'da.

## 4. Metrik tanımları
- **First-token gecikmesi (TTFT)** = `first_token.t_ms − complete_request.t_ms`. **Genel** (tüm turlar) +
  **per-tier** (küçük/büyük) ayrı raporlanır. SAD §20 LLM kalemi: genel P95 ≤ 400 ms (yeşil ≤ 200); küçük
  tier daha hızlı beklenir → ayrı kapı P95 ≤ 200 ms (yeşil ≤ 120). Streaming başlangıç gecikmesi algılanan
  duraklamayı belirler; tam yanıt beklenmez (FR-LLM-004).
- **Model tiering (FR-LLM-013)** = sağlayıcının küçük + büyük model birlikte sunması (config) + her tier'ın
  TTFT'si. **Küçük-modelle karşılanan tur oranı ≥ %60** (SR-DEN-005) bir **router/runtime** hedefidir (5.3);
  burada `small_tier_share` olarak **raporlanır** (kapı değil — sağlayıcı değil router belirler).
- **Görev kalitesi** = yanıt doğruluğu / görev başarısı (0–1); **dış girdi** (kalibre değerlendirme seti ya
  da LLM-judge skoru — vendor-neutral + tekrarlanabilirlik). Kapı **en-kötü-dil** üzerinden (EN+TR zorunlu —
  zayıf dili genel ortalama maskelemesin; STT WER / TTS MOS ile aynı disiplin).
- **No-train / no-log** = `noTrain=true` **ve** `dataRetention ∈ {NONE, EPHEMERAL}`. İkisi birden gerekli:
  no-train tenant verisinin eğitime gitmemesini (FR-LLM-012), retention=NONE/EPHEMERAL hassas içeriğin
  sağlayıcı loglarında kalmamasını (FR-KB-010) sağlar.
- **Bölgesel endpoint / residency** = `region_pinned=true` **ve** pin'lenen `region` sunulan bölgeler
  arasında. Beklenen bölge kapsamı (EU/UK/TR) bilgilendirici raporlanır; AB/UK tenant'ı için bölgesel
  endpoint zorunludur (NFR 10.7, SAD §8 notu).
- **Streaming token sürekliliği** = token-arası boşluk (inter-token latency). Boşluk eşiği aşarsa (stall,
  varsayılan > 250 ms) downstream TTS aç kalır → **ölü hava** (TTS dead-air'in FR-RES-009 LLM analoğu).
  Stall sayısı + max boşluk + ortalama inter-token + tokens/sn.
- **Tool-call doğruluğu (FR-LLM-008)** = kritik işlem gereken turlarda **schema-doğrulamalı tool-call**
  (serbest metin değil) üretme oranı; soft eşik (0.2.6'da bütünsel + 7.1.1 ile çapraz).

## 5. Kabul kapıları (gate) — mühendislik varsayılanı
| Ölçüt | Kapı (pass) | Yeşil bant |
|-------|-------------|------------|
| C1 first-token P95 (genel) | **≤ 400 ms** (SAD §20 üst) | ≤ 200 ms |
| C2 küçük-tier first-token P95 | **≤ 200 ms** (SAD §20, küçük model) | ≤ 120 ms |
| C3 görev kalitesi (en-kötü-dil) | **≥ 0.85** | ≥ 0.92 |
| C4 no-train / no-log | **uygun** (noTrain + NONE/EPHEMERAL) | — |
| C5 bölgesel endpoint | **uygun** (region pinning) | — |
| C6 token stall | **= 0** | — |
| C7 tool-call doğruluğu | **≥ 0.95** (soft) | — |

> Eşikler **mühendislik varsayılanı**; gerçek değerler **0.3.x PoC**'ta sesli diyalog koşullarında
> (streaming, EN+TR, tool senaryoları — 18.2 persona seti) doğrulanır ve gerekirse use-case bazında
> sıkılaştırılır. `score` bütçe/kalite/uygunluk kapısı geçilmezse çıkış kodu `1` → CI/0.4.4 hattında gate.

## 6. Ölçüm metodolojisi (harness)
`llm_eval_probe.py` (stdlib-only) üç mod sunar:

| Mod | İş |
|-----|----|
| `score` | Bir sağlayıcı **turn test setini** (TTFT + tier + kalite + tool-call + token akışı + uygunluk) puanlar: TTFT genel/küçük-tier P50/P95/P99, kalite en-kötü-dil, stall, küçük-tier payı, tool-call oranı, no-train + bölgesel uygunluk + kapı → çıkış kodu |
| `compare` | Çok sağlayıcılı `score` çıktısını markdown karşılaştırma matrisine indirir |
| `selftest` | Credential'sız çekirdek doğrulama (TTFT/tier/kalite/no-train/bölge/stall/percentile birim kontrolleri) |

**Örnek (sample) şeması:** her sağlayıcı için bir test seti JSON — `config` (`model_small`, `model_large`,
`no_train`, `data_retention`, `region`, `region_pinned`, `available_regions`, `streaming`,
`fallback_supported`) + `turns[]` (her biri: `language`, `tier ∈ {small,large}`, `turn_class ∈
{routine,complex,risky}`, `first_token_ms`, `quality`, `requires_tool`, `tool_call_valid`, `tokens[{t_ms}]`).
Detaylı şema `llm_eval_probe.py` başlığında.

**Canlı PoC akışı (credential gerektiğinde):** LLM adapter, sentetik diyalog senaryolarını (FR-TST-002/008 —
gerçek müşteri verisi yok) bölgesel + no-train endpoint'e akıtır; ilk token zaman damgası (TTFT), token
varışları (süreklilik/stall), tool-call yapısı (FR-LLM-008) ve tier yukarıdaki sample şemasına yazılır;
görev kalitesi bir kalibre set/LLM-judge ile eklenir; `score` çalıştırılır. Sağlayıcı API anahtarı **ortam
değişkeni** ile geçilir, **dosyaya yazılmaz** (`.gitignore`: `.env*`, `secrets/`).

## 7. Karşılaştırma matrisi (İLLÜSTRATİF profillerle)
Aşağıdaki tablo `samples/` altındaki **illüstratif** sağlayıcı profillerinden harness ile üretilmiştir.
**Bunlar gerçek sağlayıcı benchmark'ı değildir**; metodolojiyi ve kapıları göstermek içindir. Gerçek
değerler 0.3.x canlı PoC'ta her sağlayıcı için ölçülüp buraya işlenecektir.

| Sağlayıcı | TTFT P95 (ms) | Küçük-tier P95 (ms) | Kalite EN | Kalite TR | no-train | Bölgesel | Stall | Karar |
|---|---|---|---|---|---|---|---|---|
| llm-cloud-A | 356.0 | 188.0 | 0.955 | 0.908 | evet | evet | yok | 🟡 SARI |
| llm-cloud-B | 340.5 | 182.75 | 0.9533 | 0.815 | evet | evet | yok | 🔴 KIRMIZI |
| llm-cloud-C-degraded | 511.0 | 263.75 | 0.945 | 0.89 | HAYIR | HAYIR | 4 stall | 🔴 KIRMIZI |

> Kapılar: LLM first-token P95 ≤ 400 ms (SAD §20, yeşil ≤ 200); küçük-tier P95 ≤ 200 ms (yeşil ≤ 120,
> FR-LLM-013); kalite (en-kötü-dil) ≥ 0.85 (yeşil ≥ 0.92); no-train (FR-LLM-012) + bölgesel endpoint
> (NFR 10.7) + stall = 0 zorunlu. Yeniden üret:
> `python3 docs/vendor-eval/llm_eval_probe.py score samples/<x>.json --out /tmp/<x>.json` → `compare`.

**Matrisin gösterdiği** (illüstratif): **A** tüm kapıları geçer (TTFT genel 356 ms < 400 sarı bantta,
küçük-tier 188 ms < 200 → küçük model fiilen hızlı, kalite EN+TR ≥ 0.90, no-train + bölgesel uygun, stall
yok → bütünsel SARI); **B** EN kalite güçlü (0.953) ama **TR kalite 0.815 < 0.85** → en-kötü-dil kapısında
elenir (genel ortalama ~0.88 maskelemez) — EN güçlü TR zayıf adayı kapı yakalar; **C** yalnız ABD bölgesi
(**bölgesel/residency yok → NFR 10.7 ihlali**), **no-train kapalı** (PROVIDER_DEFAULT retention → FR-LLM-012
ihlali), **TTFT 511 ms > 400** (bütçe aşımı) + küçük-tier 264 ms > 200 + **token stall** (akışta uzun boşluk
→ downstream TTS ölü hava) + tool-call 0.0 → çoklu KIRMIZI.

## 8. Bulgular ve öneri (sağlayıcı-nötr)
1. **First-token, gecikme bütçesinin en ağır kalemidir** (SAD §20: ~200–400 ms). Küçük tier daha hızlı
   olmalı (FR-LLM-013); bu nedenle TTFT **genel + küçük-tier ayrı** ölçülür — büyük modelin yavaşlığı
   küçük-tier'ı maskelememeli. Routing'in (5.1–5.3) değer üretebilmesi için sağlayıcı **iki tier sunmalı**.
2. **No-train + no-log + bölgesel endpoint birer uygunluk kapısıdır, kalite değil** (FR-LLM-012/FR-KB-010/
   NFR 10.7): regüle/AB/UK tenant'ı için bunlar olmadan sağlayıcı, kalite/gecikme ne olursa olsun **elenir**.
   SAD §8 notu: "AB/UK tenant'ları için bölgesel endpoint zorunlu". DPA/alt-işleyen kaydı 0.2.6'da.
3. **Görev kalitesi dile göre bağımsız ölçülmeli:** Çoğu model EN'de güçlüdür; TR doğruluğu ayrı doğrulanmazsa
   kalite yanıltıcı görünür. Kapı **en-kötü-dil** üzerinden (EN+TR) — STT WER / TTS MOS ile aynı disiplin.
4. **Streaming token sürekliliği** (FR-LLM-004) ayrı risktir: ilk token hızlı gelip sonra akış stall ederse
   (token-arası uzun boşluk) downstream TTS aç kalır → **ölü hava** (FR-RES-009 zinciri). Stall ile ölçülür.
5. **Tool-call doğruluğu** (FR-LLM-008) kritik işlemler için belirleyici: kritik aksiyon serbest metinle
   değil **schema-doğrulamalı tool-call** ile yapılmalı. Soft kapı; 7.1.1 (tool schema doğrulama) + 0.2.6'da
   bütünsel.
6. **ADR-002/ADR-001 gereği ≥2 sağlayıcı + fallback (FR-LLM-010) + küçük/büyük tier (FR-LLM-013):** en az
   iki kapı-geçen aday; biri birincil, diğeri fallback (4.3.3) ve her sağlayıcı küçük+büyük tier sunar.
   **no-train / dataRetention=NONE + bölgesel endpoint** ön koşul.
7. **Karar 0.2.6'ya bırakılır** (vendor-neutral): bu görev ölçüt + metodoloji + kapıyı sağladı; sayısal
   sıralama canlı PoC ölçümleri (kalite kalibre set + telefoni streaming) + maliyet/token + DPA gelince netleşir.

## 9. Açık konular / sonraki adımlar
- [ ] Canlı PoC: her aday için bölgesel + no-train endpoint'e sentetik diyalog senaryolarıyla (FR-TST-002/008)
      gerçek TTFT (genel + küçük/büyük tier), token akışı/stall, tool-call yapısı ölç (0.3.1/0.3.2 ile birlikte);
      görev kalitesini kalibre set/LLM-judge ile ekle (EN+TR).
- [ ] Maliyet/token: girdi/çıktı token başı fiyat + tipik tur token profili → çağrı-başı LLM maliyeti (FR-BIL-002,
      FR-LLM-011) — 0.2.6 karar raporu girdisi.
- [ ] Tiering (5.3): küçük-modelle karşılanan tur oranı ≥ %60 hedefi (SR-DEN-005) router'da doğrulanır; sağlayıcı
      küçük-tier kalite/gecikme yeterliliği PoC'ta nicelenir.
- [ ] Fallback (4.3.3): birincil → ikincil (model veya deterministic flow) geçişte hata taksonomisi (API.md §11.6)
      ile uçtan uca test; ≥2 sağlayıcı eşleştirmesi.
- [ ] no-train/no-log + bölgesel endpoint sözleşmesel doğrulama: DPA + alt-işleyen listesi (0.2.6 / 17.2.2).
- [ ] `score` gate'ini 0.4.4 CI hattına bağla (regresyon: model/versiyon değişiminde TTFT/kalite kaymasını yakala).

## 10. İzlenebilirlik
- **Kaynak:** ADR-001 (bağımsız orchestrator; STT/LLM/TTS doğrudan bağlanmaz), ADR-002 (vendor-neutral, ≥2
  sağlayıcı + fallback); SAD §8.1 (LlmAdapter SPI), §9 (LLM orkestrasyonu — routing/tiering/cache), §20 (gecikme bütçesi).
- **FR:** FR-LLM-001..014 (≥2 sağlayıcı/model, tenant override, routing, streaming, özetleme, system prompt
  değişmezliği, injection guard, tool-call, output guard, fallback, kayıt, **no-train**, **tiering**, cache);
  FR-RES-005 (tiering density), FR-KB-010 (no-log).
- **SR:** SR-LLM-001..014 (SRS §4.8); SR-DEN-005 (küçük-model tur oranı ≥ %60).
- **NFR:** 10.1 (P95 ≤ 1.200 ms; LLM first-token ~200–400 ms alt-kalemi), 10.7 (residency / bölgesel endpoint).
- **WBS:** 0.2.4 (bu); girdi → 0.2.6 (karar), 0.3.1/0.3.2 (PoC ölçüm), 4.2.4 (LLM adapter uygulaması),
  4.3.3 (LLM fallback), 5.1–5.3 (Router/tiering), 5.7/5.8 (model+token kaydı + no-train), 7.1.1 (tool schema doğrulama).
