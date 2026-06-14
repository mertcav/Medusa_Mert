# RTP/Medya Sonlandırma + Jitter Buffer — Tasarım (WBS 2.2.1)

> Kaynak doğruluk: **`rtp-jitter-spec.json`** (makine-okunur). Bu doküman tasarımı/gerekçeyi anlatır.
> Çelişkide **BRD/SAD** esastır. İz: **FR-RTC-001** → SR-RTC-001 → TC-RTC-001.
> Vendor-neutral (ADR-002), credential-free, stdlib-only. Ham RTP ses payload'ı / PII repoya yazılmaz.

## 1. Mimari konum

Real-time **Media Gateway** (SAD §6 mimari diyagramı, §7.1 medya akışı, L2 katmanı), telefoni edge
ile Conversation Orchestrator arasındadır. 2.1.3 (managed CPaaS / M1) ve 2.1.4 (ham SIP RTP / M2)
adaptörleri **taşıma + normalize** sözleşmesini kurdu; bu dilim taşıma içindeki gerçek **medya
sonlandırma + jitter buffer** çekirdeğini birinci-sınıf, deterministik bir sözleşmeye çevirir.

```
PSTN ──SIP/RTP──► SBC ──► SIP App Server ──► [Media Gateway: RTP terminate + JITTER BUFFER] ──► Streaming STT (2.2.5)
                  (2.1.1)   (2.1.2)            └─ 2.2.1 (bu dilim)                                └─ partial/final
                                               codec 8kHz (2.2.2) · VAD/endpointing (2.2.3) · echo (2.2.4)
                                    egress ◄── [playout pace + barge-in FLUSH (2.2.7)] ◄── Streaming TTS (2.2.6)
```

**Ingress** (arayan→STT) jitter buffer bu dilimin çekirdeğidir. **Egress** (TTS→arayan) tarafında
yalnız barge-in **flush kancası** (≤200ms) tanımlanır; barge-in algılama edge'dedir (ADR-005, 2.2.7).

## 2. RTP sonlandırma (J1/J9 — RFC 3550)

Her RTP paketi: `sequence_number` (16-bit), `timestamp` (32-bit, örnek birimi), `ssrc` (32-bit kaynak),
`marker` (talk-spurt başı), `payload_type`. Sonlandırıcı:

- **Sıralama:** paketler `timestamp`/`sequence`'e göre sıralanır; geliş sırası ağ nedeniyle karışabilir
  (out-of-order). Sıralama **wraparound-güvenli** modüler farkla yapılır — 16-bit seq ve 32-bit ts
  sarması (RFC 1982 seri-sayı aritmetiği; `seq_diff`/`ts_diff`).
- **SSRC değişimi:** yeni kaynak görülürse buffer resetlenir (kaynak değişimi = yeni medya akışı).
- **Marker bit:** sessizlik sonrası ilk paket (talk-spurt başı) playout'u yeniden **primer** (buffer
  yeniden doldurulur) — sessizlik boyunca biriken sapma sıfırlanır.
- **Codec-agnostik:** sonlandırıcı ses payload'ını **yorumlamaz**; yalnız zamanlama/sıralama yönetir.
  Payload 8kHz/20ms olarak (FR-RES-008, 2.2.2 ile hizalı) downstream'e geçer — **transcode/resample yok**.

## 3. Adaptif jitter buffer (J2/J3/J4)

Ağ jitter'ı (paketlerin düzensiz varışı) downstream STT'ye düzgün bir akış olarak verilmelidir.
Jitter buffer, playout'u bir **hedef gecikme** kadar geciktirip varış düzensizliğini sönümler:

```
J        = RFC 3550 interarrival jitter tahmini (ms)            # voice_jitter_ms (BRD §15)
target_D = clamp(base_depth_ms + target_factor·J, min_depth_ms, max_depth_ms)
```

- **Adaptif:** jitter arttıkça derinlik büyür (daha çok paketi bekleyip absorbe eder), azaldıkça
  küçülür (gecikmeyi düşürür). `fixed` mod da desteklenir (sabit derinlik, referans/kararlı-ağ).
- **Sınırlı (J10):** derinlik `[min, max]` ile clamp'lenir → ne sınırsız büyüme (bellek, FR-RES-016)
  ne yetersiz sönümleme. Taşmada **en eski atılır** (`drop_oldest`, backpressure; FR-RES-014).
- **Geç paket (J4):** playout son tarihinden **sonra** gelen paket oynatılmaz, **atılır** ve sayılır
  (`late_discard`). O slot concealment ile doldurulur.

## 4. Kayıp tespiti + concealment + sürekli kadans (J5/J6)

- **Kayıp (J5):** sequence/timestamp boşluğu = kayıp paket. Kayıp + geç-atılan slotlar **PLC
  (packet loss concealment) fill** ile doldurulur. `concealment_ratio = (kayıp + geç) / toplam_slot`.
  Kapı **≤ 0.05**; aşılırsa **hat-kalitesi degrade sinyali** (FR-RTC-005) — yukarı katmana bildirilir.
- **Sürekli kadans (J6):** downstream **her slot için tam olarak bir çerçeve** alır — gerçek veya
  concealed; **boşluk yok**. Bu "stream-first, buffer-never" ilkesidir (SAD §6 ilke 1): kritik yolda
  tam-tampona-alma yoktur, çerçeveler sürekli akar. STT bağlantısı (2.2.5) kesintisiz beslenir.

## 5. Gecikme bütçesi ve loss↔latency gerilimi (J3)

SAD §20 medya bütçesi tek-yön **~50–100ms**. Jitter buffer'ın **eklediği** playout gecikmesi bu
bütçenin payıdır: **P95 ≤ 80ms** (yeşil ≤50ms). Eklenen gecikme P95'i pratikte ≈ nominal buffer
derinliğine eşittir (erken gelen paket ~derinlik kadar bekler).

**Temel gerilim:** buffer'ın J2'de izin verilen **120ms**'e büyümesi kaybı önler (daha çok geç paketi
yakalar) **ama** J3 latency bütçesini (80ms) **aşar**. Yani aşırı jitter altında sistem ya kayba
(concealment↑) ya gecikmeye (latency↑) razı olur — ikisi birden iyi olamaz. `jitter-degraded` örneği
bunu gösterir: derinlik 120ms'e clamp'lenir (kayıp kaçınma önceliği) ama hem J3 hem J5 elenir →
**degrade sinyali**. Bu, edge medya yerleşimi (ADR-009 hibrit) ve bölgesel düşük-jitter ağların
neden gerekli olduğunu doğrular.

## 6. Metrikler → gözlemlenebilirlik (J7)

Her oturum BRD §15 medya metriklerini hesaplar ve 0.4.7 omurgasına yayar:

| Metrik | BRD §15 | Observability metrik |
|--------|---------|----------------------|
| `jitter_ms` | jitter | `voice_jitter_ms` (histogram) |
| `packet_loss_rate` | packet loss | `voice_packet_loss_ratio` (gauge) |
| `concealment_ratio`, `late_discard_rate`, `added_latency_p95_ms`, `nominal_depth_ms`, `reordered` | — | dahili medya metrikleri |

Yüksek-kardinalite kimlik (`call_id`) **metrik label'ı olmaz** (yalnız trace/exemplar; 0.4.7
`label_policy`). Ham payload metriklerde yer almaz.

## 7. Dayanıklılık, residency, PII

- **Residency (J13):** medya home-region'da sonlandırılır; bölge uyumsuzluğu `REGION_VIOLATION`
  (NFR 10.7). ADR-009 hibrit: ağır medya işleme ayrı bölgesel katmanda.
- **Bağlam:** tenant_id/correlation_id/call_id medya oturumuna bağlanır, metriklere taşınır (SAD §13.3).
- **Hata taksonomisi (J12):** bozuk RTP → `INVALID_REQUEST`; taşıma kopması → `UNAVAILABLE`;
  bölge → `REGION_VIOLATION` (API §11.6). Aşırı kayıp bir hata değil, **degrade sinyali**dir.
- **PII (J14):** RTP ses payload'ı kişisel veridir; spec/config/örneklerde **ham payload veya
  transkript tutulmaz**; paketler yalnız zamanlama metadata'sı taşır.

## 8. Kapsam ayrımı (bilinçli)

| Konu | Nerede |
|------|--------|
| Codec yönetimi (8kHz, resample/transcode önleme) | **2.2.2** (bu dilim profili korur, dokunmaz) |
| Edge VAD / endpointing (dinamik) | **2.2.3** |
| Gürültü/echo + agent kendi sesini transkribe etmeme | **2.2.4** |
| Streaming STT connector (gateway↔orchestrator) | **2.2.5** (downstream tüketici) |
| Streaming TTS + ölü hava | **2.2.6** (egress kaynağı) |
| Barge-in olay üretimi + TTS kesme ≤200ms | **2.2.7** (burada yalnız flush kancası) |
| SBC / SIP App Server | **2.1.1 / 2.1.2** |
| Taşıma/normalize (managed WS / ham SIP RTP) | **2.1.3 / 2.1.4** |
| Gerçek RTT/jitter ölçümü (sağlayıcı eval) | **vendor-eval 0.2.1** |
| Native medya yığını (C/C++/Rust, WebRTC) | **SAD §21**, F1 canlı kod |

Canlı sistemde aynı sözleşme native Media Gateway'de (SAD §21) gerçek RTP/WebRTC yığınıyla doldurulur;
bu dilim sözleşmeyi + deterministik kapı simülatörünü sağlar.
