# Edge VAD / Endpointing (Dinamik) — Tasarım (WBS 2.2.3)

> Kaynak doğruluk: **`edge-vad-spec.json`** (makine-okunur). Bu doküman tasarımı/gerekçeyi anlatır.
> Çelişkide **BRD/SAD** esastır. İz: **FR-RTC-004/013**, **FR-RES-009** → SR-RTC-004/013, SR-RES-009
> → TC-RTC-004/013; **ADR-005**. Vendor-neutral (ADR-002), credential-free, stdlib-only.
> Ham ses payload'ı / transkript / PII repoya yazılmaz (çerçeveler yalnız enerji metadata'sı).

## 1. Mimari konum

Real-time **Media Gateway** (SAD §6/§7.1/§7.2, L2 **edge** katmanı), 2.2.1 jitter buffer ile streaming
STT (2.2.5) arasındadır. VAD/endpointing + barge-in algılama **edge'de** yapılır (ADR-005 Kabul;
ADR-009 hibrit — edge VAD/barge-in + ayrı bölgesel ağır-medya katmanı):

```
PSTN ─► SBC ─► SIP App ─► [Jitter Buffer 2.2.1] ─► [EDGE VAD + DİNAMİK ENDPOINTING + BARGE-IN] ─► Streaming STT (2.2.5)
       (2.1.1) (2.1.2)     düzgün 20ms/50fps         └─ 2.2.3 (bu dilim)                            └─ finalize YALNIZ endpoint'te
                            kadans                       • ölü hava STT'ye GÖNDERİLMEZ (FR-RES-009)
        egress ◄── [TTS playout + barge-in FLUSH ≤200ms (2.2.7+2.2.1 J11)] ◄── Streaming TTS (2.2.6)
                            ▲ barge_in olayı (edge'de algılanır → orchestrator TTS iptal)
```

**Neden edge?** (FR-RTC-013, ADR-005): (1) barge-in tepkisi ağ gidiş-dönüşü olmadan hızlanır;
(2) ölü hava (dead air) merkeze taşınmadan edge'de elenir → gereksiz STT akışı + LLM çağrısı azalır
(FR-RES-009, NFR 10.2). Merkezi endpointing 0.3.4 deneyinde **barge-in P95 ≈266ms** ile bütçeyi
eler (ADR-005'i doğrular); bu dilim kararı kod sözleşmesine indirir.

## 2. VAD — çerçeve aktivite tespiti (V3/V4)

Her 20ms çerçevenin enerjisi (dBov) üzerinden konuşma/sessizlik kararı (codec-agnostik; ham payload
**yorumlanmaz**):

- **Adaptif gürültü tabanı (noise floor):** sessiz çerçevelerden yavaşça (`noise_adapt`) güncellenir;
  aktif eşik = `noise_floor + speech_margin_db`. Böylece hat gürültüsü değişse de VAD uyum sağlar.
- **Histerezis:** onset (`+onset_hysteresis_db`) ve offset (`−offset_hysteresis_db`) ayrı eşikler →
  eşik sınırındaki titreme (chattering) önlenir.
- **Hangover (V4):** konuşma sonrası `hangover_frames` çerçeve "konuşma" sayılır → kelime-içi mikro
  duraklamalar (nefes/ünsüz boşluğu) köprülenir; STT'ye trailing bağlam korunur, kelime kesilmez.
- **Echo guard (V3/V9):** agent konuşurken (TTS playout) eşik `barge_in_echo_guard_db` kadar yükselir;
  ayrıca **noise floor o aralıkta dondurulur** (echo enerjisi tabanı yukarı çekip gerçek barge-in'i
  kaçırmasın — bkz. §6 bugfix). Tam akustik echo cancellation 2.2.4'tedir; burada debounce/guard kancası.

## 3. Dinamik endpointing (V2/V5/V6/V7) — çekirdek

Söz sonu (end-of-utterance), konuşma bittikten sonra bir **onay-sessizliği** `T_confirm` beklenerek
onaylanır. Bu süre **statik değil, bağlama göre dinamiktir** (FR-RTC-004):

```
T_confirm = clamp(
    base_confirm_ms
    + (seg_ms < short_speech_ms ? hesitation_extra_ms : 0)            # kısa/kesik söz → tereddüt
    + (seg_ms < short_speech_ms AND önceki_duraklama ? hesitation_extra_ms : 0)  # hâlâ kısa + duraklamış
    − (seg_ms ≥ long_speech_ms ? completeness_discount_ms : 0),       # uzun akıcı tur → tamamlandı
    min_confirm_ms, max_confirm_ms)
```

- **Tereddüt (hesitation):** kısa/kesik bir parça veya turda önceden duraklamış kullanıcı → muhtemelen
  düşünüyor → `T_confirm` **uzar** → söz-içi duraklama köprülenir, **erken kesilmez** (V6).
- **Tamamlanma (completeness):** uzun akıcı bir cümle → tamamlanmış olası → `T_confirm` **kısalır** →
  söz-sonu gecikmesi düşer, **green** banda çekilir (V5).
- **Orta uzunluk:** `base` — kullanıcı duraklamadan sonra dolu bir cümle bitirdiyse tereddüt cezası
  uygulanmaz (gerçek söz sonu gecikmesi SAD §20 bütçesinde kalır).

Durum makinesi: `IDLE → SPEAKING → PENDING(T_confirm) → endpoint | SPEAKING(bridged)`. `T_confirm`
dolmadan konuşma dönerse duraklama köprülenir (within-utterance pause); dolarsa **söz sonu olayı**
üretilir → STT/LLM **finalize** tetiklenir.

**Neden dinamik?** Statik bir eşik şu gerilimi çözemez (SR-RTC-004 "erken/geç kesme oranı sınırlı"):
kısa eşik → tereddütte erken keser (V6 elenir); uzun eşik → her turda yavaş (V5 elenir). Dinamik
`T_confirm` ikisini **bağlamla** ayırır.

## 4. Söz-sonu puanlama (ground-truth karşısında)

Sample'lar gerçek söz yapısını `ground_truth.utterances` ile verir: her söz = konuşma koşusu (run)
listesi. Ardışık koşular arası boşluk = **within-utterance (hesitation) duraklaması** (endpoint
**ateşlenmemeli**); sözün son koşusundan sonraki sessizlik = **gerçek tur sonu** (endpoint
**ateşlenmeli**, gecikme = `(fire − gerçek_son)·frame_ms`).

- **Erken kesme (V6):** endpoint bir hesitation boşluğunda ve devam koşusundan önce ateşlerse sayılır.
- **Gecikme (V5):** her gerçek son için endpoint gecikmesi P95 ≤ 250ms (SAD §20).
- **Kaçırma (V7):** gerçek son max pencerede yakalanmazsa sayılır.

## 5. Barge-in algılama (V8/V9)

Kullanıcı agent konuşurken (SPEAK) araya girerse: edge VAD, agent playout aralığında **echo guard'lı**
eşikle yalnız gerçek kullanıcı sesini arar; `min_speech_frames` ardışık konuşma çerçevesiyle **debounce**
edilir (anlık gürültü/echo tetiklemez). Onset onaylanınca orchestrator'a `barge_in` olayı gider →
TTS iptal + egress buffer **flush** (2.2.1 J11, ≤200ms). **Algılama** edge'dedir; algılama gecikmesi
NFR 10.1/ADR-005 barge-in ≤200ms bütçesinin edge payı (green ≤100ms). Echo-only akışta yanlış
barge-in üretilmez (V9).

## 6. Gecikme bütçesi ve gerilimler

| Kalem | Bütçe | Not |
|-------|-------|-----|
| **Söz-sonu gecikmesi** (V5) | P95 ≤ 250ms (green ≤200) | SAD §20 "Endpointing (VAD karar gecikmesi) ~150–250ms, Edge'de; dinamik" |
| **Barge-in algılama** (V8) | P95 ≤ 200ms (green ≤100) | ADR-005/NFR 10.1 barge-in ≤200ms edge payı |

**Gerilim 1 — erken vs geç kesme (V5↔V6):** kısa `T_confirm` gecikmeyi düşürür ama hesitation'ı keser;
uzun `T_confirm` keser ama yavaşlar. Dinamik endpointing bunu bağlamla çözer (§3). Gecikme ≈
`hangover + T_confirm`; uzun akıcı turda T kısalır → green, tereddütte T uzar ama gecikme **gerçek
son** üzerinde ölçülür (köprülenen duraklama gecikme sayılmaz).

**Gerilim 2 — echo vs barge-in (bugfix bulgusu):** echo enerjisi sessizlik gibi görünüp noise floor'u
yukarı çekerse guard'lı eşik o kadar yükselir ki gerçek barge-in (kullanıcı sesi) **kaçırılır**. Çözüm:
agent playout sırasında **noise floor dondurulur**; böylece echo guard yalnız sabit tabana eklenir,
gerçek kullanıcı sesi (echo'dan belirgin yüksek) güvenilir tetikler.

## 7. Ölü hava (dead air) ve kaynak kazancı (V10/V11)

- **Bastırma (V10):** sessiz çerçeveler (VAD=silence, hangover dışı) STT'ye **gönderilmez** → gereksiz
  STT akışı + LLM çağrısı azalır (FR-RES-009, FR-RTC-013). İletilen çerçeve ⊆ konuşma + hangover.
- **Finalize yalnız endpoint'te (V11):** STT/LLM finalize sürekli değil, **yalnız söz sonunda**
  tetiklenir → `utterances_emitted` = endpoint sayısı → çağrı sayısı düşer (NFR 10.2 kaynak kazancı).

## 8. Metrikler → gözlemlenebilirlik (V13)

| Metrik | BRD §15 | Observability metrik |
|--------|---------|----------------------|
| `silence_total_ms` | silence süresi | `silence_duration_ms` (histogram) |
| `barge_in_count` | barge-in sayısı | `barge_in_total` (counter) |
| `endpoint_latency_p95_ms`, `false_early_cut_rate`, `missed_endpoint_rate`, `barge_in_latency_p95_ms`, `stt_suppression_ratio` | — | dahili edge metrikleri |

Yüksek-kardinalite kimlik (`call_id`) **metrik label'ı olmaz** (yalnız trace/exemplar; 0.4.7
`label_policy`). Ham payload/transkript metriklerde yer almaz.

## 9. Dayanıklılık, residency, PII

- **Residency (V14):** VAD/endpointing medya home-region'da (edge) yapılır; bölge uyumsuzluğu
  `REGION_VIOLATION` (NFR 10.7). ADR-009 hibrit.
- **Hata taksonomisi (V14):** bozuk çerçeve (enerji yok/sayısal değil) → `INVALID_REQUEST`; taşıma
  kopması → `UNAVAILABLE`; bölge → `REGION_VIOLATION` (API §11.6). Düşük SNR / yüksek erken-kesme bir
  hata değil, **degrade sinyali**dir (kapılar).
- **PII (V14):** ses payload'ı/transkript kişisel veridir; spec/config/örneklerde **ham payload veya
  transkript tutulmaz**; çerçeveler yalnız illüstratif enerji (dBov) + ground-truth frame indeksleri taşır.

## 10. Kapsam ayrımı (bilinçli)

| Konu | Nerede |
|------|--------|
| RTP sonlandırma + jitter buffer (düzgün kadans girdisi) | **2.2.1** (upstream) |
| Codec yönetimi (8kHz, resample/transcode önleme) | **2.2.2** (profil korunur) |
| **Edge VAD / endpointing (dinamik)** | **2.2.3** (bu dilim) |
| Gürültü/echo (tam AEC) + agent kendi sesini transkribe etmeme | **2.2.4** (burada yalnız echo guard kancası) |
| Streaming STT connector (gateway↔orchestrator) | **2.2.5** (downstream tüketici) |
| Streaming TTS + ölü hava (egress) | **2.2.6** |
| Barge-in TTS kesme ≤200ms + egress flush | **2.2.7** (+ 2.2.1 J11; burada yalnız ALGILAMA) |
| Native medya yığını (C/C++/Rust, WebRTC VAD) | **SAD §21**, F1 canlı kod |

Canlı sistemde aynı sözleşme native Media Gateway'de (SAD §21) gerçek WebRTC VAD / DSP yığınıyla
doldurulur; bu dilim sözleşmeyi + deterministik kapı simülatörünü sağlar.
