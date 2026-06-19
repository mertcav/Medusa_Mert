# Call Metrics — teknik metrikler (packet loss/jitter/STT-LLM-TTS latency/token/...) (WBS 14.1.2)

Conversation Orchestrator (Çekirdek IP, SAD §6) gözlemlenebilirlik emisyon yolundaki **Call Metric
Extractor** sözleşmesi + deterministik referans hesaplayıcı. **SAD §17.1 'Metrics:' satırı + BRD §15
'saklanması gereken teknik metrikler'** runtime karşılığı: **14.1.1 (call-trace)** çağrı başına span ağacını
üretir ve 5 gecikmeyi (e2e/STT/LLM/TTS/tool) türetir; **14.1.2** ise BRD §15'in **TÜM teknik metrik
DEĞERLERİNİ** hesaplar (14.1.1'in ertelediği *metrik DEĞER hesaplama*) ve **0.4.7 observability-spec
`metrics.catalog`** ile **birebir** gözlem (observation) olarak yayar.

`runtime/call-trace/` (14.1.1) + `runtime/context-propagation/` (3.1.5) probe disipliniyle birebir:
vendor-neutral (ADR-002), credential-free, stdlib-only, deterministik (saf aritmetik, random YOK). Metrik
kataloğu (name/type/unit/labels) **0.4.7** ile, gecikme türetme tanımı **14.1.1** ile birebir tutulur
(probe `validate` çapraz-kontrol eder → tek kaynak doğruluk, probe-sabiti değil).

## Kapsanan BRD §15 teknik metrikleri (18 — DEĞER hesabı)
| # | Metrik | BRD §15 | Kaynak |
|---|--------|---------|--------|
| 1 | `voice_packet_loss_ratio` | packet loss | `lost/(received+lost)` (oran) |
| 2 | `voice_jitter_ms` | jitter | `mean(jitter samples)` |
| 3 | `voice_codec_info` | codec | `1` (codec etiketli) |
| 4 | `telephony_sip_response_total` | SIP response code | `+1` (sip_code etiketli) |
| 5 | `stt_latency_ms` | STT latency | trace: `speech_ended→stt_final` |
| 6 | `stt_word_confidence` | word confidence | `mean(word_confidences)` |
| 7 | `llm_latency_ms` | LLM latency | trace: `llm_request_started→llm_first_token` |
| 8 | `llm_tokens_total` | token kullanımı | `prompt+completion` |
| 9 | `tool_latency_ms` *(conditional)* | tool latency | trace: `tool_request→tool_response` |
| 10 | `tts_latency_ms` | TTS latency | trace: `tts_request→tts_first_audio` |
| 11 | `e2e_response_latency_ms` | end-to-end latency | trace: `speech_ended→tts_first_audio` |
| 12 | `barge_in_total` | barge-in sayısı | `barge_in_events` |
| 13 | `silence_duration_ms` | silence süresi | `sum(silence_segments)` |
| 14 | `retry_fallback_total` | retry/fallback | `retries+fallbacks` |
| 15 | `transfer_result_total` *(conditional)* | transfer sonucu | `+1` (outcome etiketli) |
| 16 | `call_termination_total` | çağrı sonlandırma nedeni | `+1` (outcome etiketli) |
| 17 | `provider_error_ratio` | provider hata oranı | `errors/requests` (kategori başına) |
| 18 | `cost_per_minute` | dakika başı maliyet | `amount/billable_minutes` |

**Kapsam dışı:** `call_cpu_seconds` / `call_memory_bytes` (per-call CPU/bellek) → **14.1.3** / **3.1.4**.

## Dosyalar
- `call-metrics-spec.json` — **kaynak doğruluk**: placement (from_trace), inputs, derived_from_trace
  (14.1.1 birebir), value_domains, catalog (18 metrik, 0.4.7 birebir), label_policy (kardinalite/PII),
  gates (G1–G7), error_taxonomy, invariants (G1–G10).
- `call_metrics_probe.py` — `validate` / `compute <sample>` / `selftest` / `schema`.
- `config/call-metrics-profiles.json` — 3 profil (eu/tr shared + dedicated-regulated); region pini `${ENV}`,
  async-sampled emisyon (FR-RES-012).
- `samples/` — `metrics-happy-path` (tool dahil 17 metrik) · `metrics-transfer` (transfer_result) ·
  `metrics-poor-quality` (kötü kalite ama doğru hesap, geçer) + `metrics-degraded` (bilinçli, çoklu kapı eler).
- `tests/call_metrics_behavior_test.py` — T1–T8 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${ORCHESTRATOR_URL}` varsa canlı not, yoksa SKIP.

## HARD kapılar (G1–G7)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | `required` (+özellik varsa `conditional`) BRD §15 metriklerinin hepsi hesaplanıp yayılır | BRD §15, SAD §17.1 |
| **G2** | Her gözlem **0.4.7 catalog** name+type+unit ile uyumlu (bilinmeyen metrik yok) | SAD §17.1, 0.4.7 |
| **G3** | Her **DEĞER** domain sınıfında (ratio∈[0,1], ms≥0+finite, sayaç int≥0, info=1) | BRD §15 |
| **G4** | Hiçbir metrik **yüksek-kardinalite kimliği** (`correlation_id`/`call_id`/...) LABEL taşımaz; yalnız exemplar | SAD §13.3, 0.4.7 |
| **G5** | Her metrik yalnız `catalog[].labels` (⊆ `metric_labels_allowed`) kullanır | 0.4.7 |
| **G6** | Hiçbir label **PII anahtarı** taşımaz | BRD §17.7, FR-REC-004 |
| **G7** | `ratio_derived` (packet_loss, provider_error_ratio) payda>0 ile + sonuç∈[0,1] | BRD §15 |

Ek: **G8** placement (orchestrator emisyon, `from_trace` — gecikmeyi yeniden ölçmez, bloklamaz) · **G9**
0.4.7 `metrics.catalog` + 14.1.1 `derived_latencies` ile **birebir** (tek kaynak doğruluk) · **G10** error
taxonomy (API §11.6) + spec/config/örneklerde sır/ham payload/PII DEĞERİ yok.

## Çalıştırma
```bash
python3 call_metrics_probe.py validate          # spec + config + 0.4.7/14.1.1 çapraz-tutarlılık statik kapı
python3 call_metrics_probe.py selftest          # kapı regresyon kanıtı
python3 call_metrics_probe.py compute samples/metrics-happy-path.json
python3 tests/call_metrics_behavior_test.py     # T1–T8
bash run_live_test.sh                            # hepsi + (varsa) canlı not
```

## Kapsam ayrımı
- Span üretimi + zaman damgası kaydı + gecikme **türetme** → **14.1.1** (call-trace; bu modülün girdisi).
- Metrik/alarm **kataloğu** + collector guard → **0.4.7** (gözlemlenebilirlik omurgası; bu modülün referansı).
- Per-call CPU/bellek/eşzamanlılık **DEĞERLERİ** → **14.1.3** / **3.1.4** (`call_cpu_seconds`/`call_memory_bytes`).
- Yapılandırılmış asenkron + örneklemeli loglama → **14.1.4**.
- **Alarm kuralları** (P95>1.5sn, hata artışı, ...) → **14.1.5** (bu metrikler onun girdisi).
- Aggregasyon / dashboard / raporlama → **0.4.7** + **A-14/A-15**.
- Bağlam (`tenant_id`/`correlation_id`) **İLİŞTİRME** + kardinalite/PII enforcement → **3.1.5**.

Burada **yalnız** çağrı başına **teknik metrik DEĞER hesabı** + katalog/kardinalite/etiket/PII disiplini.
Canlı sistemde Go/Rust async runtime + OpenTelemetry/Prometheus (ADR-003, SAD §11/§6.3/§17.1). Sır/
credential, ham ses payload'ı, transkript ve **PII DEĞERİ** spec/config/örneklerde tutulmaz (yalnız sayısal
sinyal + etiket/kimlik **anahtar adları** + sanal zaman).
