# Call Trace — çağrı trace span'leri (BRD §15 tüm zaman damgaları) (WBS 14.1.1)

Conversation Orchestrator (Çekirdek IP, SAD §6) içindeki **Call Tracer** sözleşmesi + deterministik
referans simülatörü. **SAD §17.1 (İzleme Omurgası)** runtime karşılığı: her çağrı bir `correlation_id` +
OpenTelemetry `trace_id` taşır; **BRD §15'in 15 zaman damgasının HEPSİ** bir span ağacında **span event**
olarak kaydedilir (call connected → first audio → speech start/end → STT partial/final → LLM
request/first token → tool req/resp → TTS req/first audio → audio played → transfer → end).

`runtime/context-propagation/` (3.1.5) + `runtime/turn-taking/` (3.1.3) probe disipliniyle birebir:
vendor-neutral (ADR-002), credential-free, stdlib-only, deterministik (olay-tetikli, sanal saat, random
YOK). Bu modül **span AĞACINI ÜRETİR** + zaman damgalarını **doğru span'a + doğru nedensel sırada +
iyi-biçimli hiyerarşide** kaydeder ve trace'ten **BRD §15 gecikme metriklerini** (e2e/STT/LLM/TTS/tool)
**türetir** (14.1.2 girdisi). Timestamp/metrik kataloğu **0.4.7 gözlemlenebilirlik omurgası** ile birebir.

## Dosyalar
- `call-trace-spec.json` — **kaynak doğruluk**: placement, span_model (call→turn→{stt,llm,tool,tts};
  transfer→call), timestamps (15 BRD §15 + span_of eşleme), causal_order, derived_latencies,
  identity (W3C traceparent), attribute_policy, gates (G1–G7), error_taxonomy, invariants (G1–G10).
- `call_trace_probe.py` — `validate` / `simulate <sample>` / `selftest` / `schema`.
- `config/call-trace-profiles.json` — 3 profil (eu/tr shared + dedicated-regulated); region pini `${ENV}`,
  tail-based sampling (0.4.7).
- `samples/` — `trace-happy-path` (tool dahil 14 zaman damgası) · `trace-multi-turn` (2 turn) ·
  `trace-transfer` (call_transferred + transfer span) geçer + `trace-degraded` (bilinçli, çoklu kapı eler).
- `tests/call_trace_behavior_test.py` — T1–T8 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${ORCHESTRATOR_URL}` varsa canlı not, yoksa SKIP.

## HARD kapılar (G1–G7)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | Senaryonun `must_cover` BRD §15 zaman damgalarının hepsi span event olarak kaydedilir | BRD §15, SAD §17.1 |
| **G2** | Her zaman damgası **doğru span KINDine** (stt_*→stt, llm_*→llm, tool_*→tool, tts_*/audio_played→tts, speech_*→turn, call_*→call, transferred→transfer) | SAD §17.1 |
| **G3** | Nedensel çiftler **monoton** (t[önce] ≤ t[sonra]; yanlış sıra → negatif gecikme) | BRD §15, SAD §20 |
| **G4** | Ağaç **iyi-biçimli**: tek root `call` + geçerli ebeveyn + çocuk aralığı ebeveyne sığar + end≥start | SAD §17.1 |
| **G5** | Çağrı başına **tek** `trace_id` + **tek** `correlation_id`; her span ikisini + `tenant_id` taşır | SAD §17.1 |
| **G6** | Span attribute'unda **PII / ham payload / transkript yok** | BRD §17.7, FR-REC-004 |
| **G7** | Türetilen BRD §15 gecikmeleri (e2e/STT/LLM/TTS/tool) **non-negative + finite** | SAD §17.1/§20, BRD §15 |

Ek: **G8** placement (orchestrator, ingress, olay-tetikli, bloklamaz) · **G9** 0.4.7
observability-spec ile **birebir** timestamp/metrik tutarlılığı (tek kaynak doğruluk, probe-sabiti değil)
· **G10** error taxonomy (API §11.6) + spec/config/örneklerde sır/ham payload/PII DEĞERİ yok.

## Türetilen gecikmeler (trace → BRD §15 metrik)
| Metrik | Tanım (zaman damgası farkı) | İz |
|--------|------------------------------|-----|
| `e2e_response_latency_ms` | `speech_ended` → `tts_first_audio` (end-of-utterance → ilk agent sesi) | SAD §20, NFR 10.1, 0.3.2 |
| `stt_latency_ms` | `speech_ended` → `stt_final` | BRD §15 |
| `llm_latency_ms` (TTFT) | `llm_request_started` → `llm_first_token` | BRD §15 |
| `tts_latency_ms` (first-byte) | `tts_request` → `tts_first_audio` | BRD §15 |
| `tool_latency_ms` | `tool_request` → `tool_response` | BRD §15 |

Her ad **0.4.7 `metrics.catalog`'da mevcut** (probe `validate` çapraz-kontrol eder). Metrik **DEĞER
hesaplama/aggregasyon** → 14.1.2.

## Çalıştırma
```bash
python3 call_trace_probe.py validate          # spec + config + 0.4.7 çapraz-tutarlılık statik kapı
python3 call_trace_probe.py selftest          # kapı regresyon kanıtı
python3 call_trace_probe.py simulate samples/trace-happy-path.json
python3 tests/call_trace_behavior_test.py     # T1–T8
bash run_live_test.sh                          # hepsi + (varsa) canlı not
```

## Kapsam ayrımı
- Bağlam (`tenant_id`/`correlation_id`) **İLİŞTİRME** + kardinalite/PII enforcement → **3.1.5** (context-propagation).
- Metrik/alarm **kataloğu** + collector guard → **0.4.7** (gözlemlenebilirlik omurgası).
- Teknik metrik **DEĞER** hesaplama (packet loss/jitter/...) → **14.1.2**.
- Per-call CPU/bellek/eşzamanlılık → **14.1.3** / **3.1.4**.
- Yapılandırılmış asenkron + örneklemeli loglama → **14.1.4**.
- **Redaction motoru (L7)** → ileri WBS; burada PII yalnız anahtar-adı düzeyinde **reddedilir/çıkarılır**.

Burada **yalnız** orchestrator-tarafı **runtime span üretimi** (span tree + timestamp recording +
ordering + latency derivation). Canlı sistemde Go/Rust async runtime + OpenTelemetry W3C traceparent
(ADR-003, SAD §6.3/§17.1). Sır/credential, ham ses payload'ı, transkript ve **PII DEĞERİ**
spec/config/örneklerde tutulmaz (yalnız zaman damgası + kimlik **anahtar adları** + sanal zaman).
