# Context Propagation — correlation_id + tenant context (WBS 3.1.5)

Conversation Orchestrator (Çekirdek IP, SAD §6) içindeki **Context Propagator** sözleşmesi +
deterministik referans simülatörü. **SAD §13.3 (Tenant Context Propagation)** + **SAD §17.1 (İzleme
Omurgası)** runtime karşılığı. Çağrı **ingress**'inde bir oturum bağlamı **bir kez** kurulur ve
üretilen **her** kayda (olay/log/trace span/metrik exemplar/giden adapter·tool çağrısı) **değişmez**
biçimde taşınır.

`runtime/turn-taking/` (3.1.3) + `runtime/resource-budget/` (3.1.4) probe disipliniyle birebir:
vendor-neutral (ADR-002), credential-free, stdlib-only, deterministik (kayıt-tetikli, sanal saat,
random YOK). Bu, **0.4.7 gözlemlenebilirlik omurgası** `label_policy`'sinin **producer** tarafı ve
**1.1.8 event-envelope** zorunlu `tenant_id`+`correlation_id` alanlarının runtime üreticisidir.

## Dosyalar
- `context-propagation-spec.json` — **kaynak doğruluk**: placement, context_model, propagation_surfaces,
  cardinality_policy (0.4.7 ile birebir), pii_policy, trace_propagation (W3C traceparent), residency,
  gates (G1–G8), metrics, error_taxonomy, invariants (G1–G10).
- `context_propagation_probe.py` — `validate` / `simulate <sample>` / `selftest` / `schema`.
- `config/context-propagation-profiles.json` — 3 profil (eu/tr shared + dedicated-regulated); region pini `${ENV}`.
- `samples/` — `ctx-happy-path` · `ctx-cardinality-exemplar` · `ctx-adapter-region-pin` (geçer) +
  `ctx-degraded` (bilinçli, çoklu kapı eler).
- `tests/context_propagation_behavior_test.py` — T1–T8 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${ORCHESTRATOR_URL}` varsa canlı not, yoksa SKIP.

## HARD kapılar (G1–G8)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | Her event/log/span/adapter required_keys (`tenant_id`+`correlation_id`) taşır | SAD §13.3/§17.1 |
| **G2** | Yüksek-kardinalite kimlik (`correlation_id`/`call_id`/`session_id`) metrik **label olmaz** → exemplar | observability 0.4.7 |
| **G3** | PII anahtarı (`phone_number`/`customer_name`/`card`/`otp`/`token`...) bağlam/label/attribute'ta yok | BRD §17.7, FR-REC-004 |
| **G4** | Hiçbir kayıt oturum `tenant_id`'sinden farklı taşımaz (cross-tenant=0) | FR-TEN-002 |
| **G5** | Çağrı başına **tek** `correlation_id` (distinct=1) | SAD §17.1 |
| **G6** | Her giden STT/TTS/LLM/Telephony/tool çağrısı `correlation_id`+`tenant_id`+`region` taşır | API §11.1, FR-BIL-002/FR-TOOL-010 |
| **G7** | Adapter çağrıları home-region'a **pinli** (uyumsuzluk → REGION_VIOLATION) | NFR 10.7 |
| **G8** | `tenant_id`/`correlation_id`/`call_id` çağrı ortasında **değişmez** (immutable binding) | FR-TEN-002 |

## Çalıştırma
```bash
python3 context_propagation_probe.py validate          # spec + config statik kapı
python3 context_propagation_probe.py selftest          # kapı regresyon kanıtı
python3 context_propagation_probe.py simulate samples/ctx-happy-path.json
python3 tests/context_propagation_behavior_test.py     # T1–T8
bash run_live_test.sh                                  # hepsi + (varsa) canlı not
```

## Kapsam ayrımı
- Kardinalite/PII/alarm **kataloğu** + collector guard → **0.4.7** (gözlemlenebilirlik omurgası).
- Event **envelope şeması** → **1.1.8** (eventstream).
- **Redaction motoru (L7)** → ileri WBS; burada PII yalnız anahtar-adı düzeyinde **reddedilir**.
- **RLS** veri-katmanı zorlaması → 1.1.x / 1.2.1 (defense-in-depth — bu doküman runtime üretim tarafı).

Burada **yalnız** orchestrator-tarafı **runtime propagasyon + enforcement**. Canlı sistemde Go/Rust async
runtime + OpenTelemetry W3C traceparent (ADR-003, SAD §6.3/§17.1). Sır/credential, ham ses payload'ı,
transkript ve **PII DEĞERİ** spec/config/örneklerde tutulmaz (yalnız kimlik **anahtar adları** + sanal zaman).
