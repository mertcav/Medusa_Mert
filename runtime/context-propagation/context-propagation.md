# Context Propagation — correlation_id + tenant context (WBS 3.1.5)

> **Faz:** F1 · **Öncelik:** Must · **İz:** SAD §13.3, §17.1 · FR-TEN-002, FR-TOOL-010, FR-BIL-002,
> FR-RES-012, FR-REC-004 · NFR 10.1/10.7 · API §11.1/§11.6 · observability 0.4.7 · eventstream 1.1.8
>
> Kaynak doğruluk `context-propagation-spec.json`'dır; bu doküman tasarımı açıklar. Çelişkide BRD/SAD esastır.

## 1. Amaç ve kapsam

Conversation Orchestrator'ın (Çekirdek IP, SAD §6) **Context Propagator** bileşeni, **SAD §13.3**'ün
"`tenant_id` (+ `org_unit`, `agent_id`, `correlation_id`) her istekte, event'te, log'da ve trace
span'inde taşınır" gereksinimini ve **SAD §17.1**'in "her çağrı bir `correlation_id` ve OpenTelemetry
trace'i taşır" omurgasını **runtime'da somutlaştırır**.

Mekanizma: çağrı **ingress**'inde (`call_started`) bir **oturum bağlamı** **bir kez** kurulur ve oturum
aktörünün (her oturum hafif asenkron task — ADR-003, SAD §6.3) yaşam-döngüsü boyunca üretilen **her**
kayda **değişmez** biçimde iliştirilir.

**Kapsam ayrımı (bilinçli):**
- Kardinalite / PII / alarm **kataloğu** + OTel-collector guard → **0.4.7** (gözlemlenebilirlik omurgası).
- Event **envelope şeması** (Kafka) → **1.1.8** (eventstream).
- **Redaction motoru (L7)** → ileri WBS; burada PII yalnız **anahtar-adı** düzeyinde reddedilir (defense-in-depth).
- **RLS** veri-katmanı zorlaması → 1.1.x / 1.2.1.

Bu doküman **yalnız** orchestrator-tarafı **runtime propagasyon + enforcement**'ı tanımlar. Bu, 0.4.7
`label_policy`'sinin **producer** tarafıdır: 0.4.7 collector/katalog **tüketici** disiplinini, 3.1.5 ise
kayıtları **üreten** runtime disiplinini sağlar; iki taraf birebir hizalıdır (validate çapraz-doğrular).

## 2. Mimari konum

```
PSTN/SIP → SBC → Media Gateway ──(turn-event: correlationId+tenantId, API §12.2)──► Conversation Orchestrator
                                                                                       │  [INGRESS]
                                                                                       │  oturum bağlamı KURULUR (1 kez):
                                                                                       │  {tenant_id, org_unit, agent_id,
                                                                                       │   correlation_id, region,
                                                                                       │   call_id, session_id, trace_id}
                                                                                       ▼
                          ┌─────────────── Context Propagator (kayıt-tetikli, bloklamaz) ───────────────┐
                          │  event   → tenant_id+correlation_id (+full)        envelope (1.1.8)          │
                          │  log      → structured, sampled, async (FR-RES-012)                          │
                          │  span     → W3C traceparent; trace_id sabit; span/işlem (SAD §17.1)          │
                          │  metric   → YALNIZ bounded label + correlation_id EXEMPLAR (0.4.7)           │
                          │  adapter  → STT/TTS/LLM/Telephony: correlationId+tenantId+region (API §11.1) │
                          │  tool     → Integration GW: correlationId+tenantId+region (FR-TOOL-010)      │
                          └──────────────────────────────────────────────────────────────────────────┘
```

Bağlam **immutable**: `tenant_id`/`correlation_id`/`call_id` çağrı ortasında değiştirilemez (tenant
binding). Propagator hot-path'i **bloklamaz** — loglama sampling + asenkron (FR-RES-012).

## 3. Bağlam modeli (SAD §13.3)

| Küme | Alanlar | Rol |
|------|---------|-----|
| `required_keys` | `tenant_id`, `correlation_id` | **Her** event/log/span/adapter/tool kaydında zorunlu minimum (G1; §17.1 trace_log_required_keys) |
| `full_context` | `tenant_id`, `org_unit`, `agent_id`, `correlation_id`, `region`, `call_id`, `session_id`, `trace_id` | Ingress'te kurulan tam bağlam |
| `immutable_keys` | `tenant_id`, `correlation_id`, `call_id` | Çağrı boyu **değişmez** (G8 — cross-tenant önleme) |
| `adapter_call_required` | `correlation_id`, `tenant_id`, `region` | Giden adapter/tool çağrısının taşıdığı (G6; API §11.1 UsageRecord) |

**Tek `correlation_id` / çağrı** (G5): trace + log + event + maliyet kayıtları tek bir kimlikle birleşir
(FR-BIL-002 maliyet ayrımı, FR-TOOL-010 tool audit izi).

## 4. Kardinalite disiplini (G2 — 0.4.7 ile birebir)

Prometheus metrik label'ları **bounded** olmalı; aksi takdirde TSDB cardinality patlar. Bu yüzden
yüksek-kardinalite kimlikler metrik **label** olamaz — yalnız **trace/log alanı** + metrik **exemplar**:

| | Anahtarlar |
|---|---|
| `metric_labels_allowed` (bounded) | `tenant_id`, `org_unit`, `agent_id`, `region`, `provider`, `category`, `sip_code`, `codec`, `outcome` |
| `metric_labels_forbidden` (yüksek-kardinalite) | `correlation_id`, `call_id`, `customer_id`, `phone_number`, `token`, `session_id` |
| `exemplar_keys` | `correlation_id`, `trace_id` |

Propagator, bir emitter yüksek-kardinalite kimliği metrik label olarak koymaya çalışırsa onu **label'dan
çıkarır** ve (exemplar_keys ise) **exemplar** olarak bağlar. `validate`, bu üç listeyi 0.4.7
`observability-spec.json`'dan okuyup **birebir** eşleştirir (çapraz-tutarlılık kapısı).

## 5. PII yasağı (G3 — BRD §17.7, FR-REC-004)

PII anahtarı (`phone_number`, `customer_name`, `card_number`, `otp`, `token`, `national_id`, ...)
**bağlam**, **metrik label** veya **span attribute** olamaz. Redaction asıl L7'de yapılır; Context
Propagator bir **defense-in-depth** katmanıdır: PII anahtar-adını label/attribute'tan çıkarır.
PII listesinin izinli metrik label'larıyla kesişmemesi `validate`'te zorlanır.

## 6. Residency (G7 — NFR 10.7)

Bağlam `region`'ı oturumun **home-region**'ıdır. Giden adapter çağrıları bu region'a **pinlenir**
(SAD §13.3 "Adapter çağrıları doğru tenant kimlik bilgileri ve region ile yapılır"). Bir adapter farklı
bölgeye yönlendirilmeye çalışılırsa → **REGION_VIOLATION** (API §11.6).

## 7. HARD kapılar

| Kapı | Metrik | Eşik | İz |
|------|--------|------|-----|
| G1 | `missing_context` | =0 | SAD §13.3/§17.1 |
| G2 | `cardinality_violations` | =0 | observability 0.4.7 |
| G3 | `pii_violations` | =0 | BRD §17.7, FR-REC-004 |
| G4 | `cross_tenant_violations` | =0 | FR-TEN-002 |
| G5 | `correlation_discontinuity` | =0 | SAD §17.1 |
| G6 | `adapter_context_missing` | =0 | API §11.1, FR-BIL-002/TOOL-010 |
| G7 | `region_violations` | =0 | NFR 10.7 |
| G8 | `illegal_context_mutations` | =0 | FR-TEN-002 |

`simulate`, deterministik bir `ContextPropagator` ile oturum bağlamını emisyon akışına iliştirir,
enforcement uygular ve bu kapıları çıkış koduna çevirir. `policy` bayrakları (`attach_context`,
`enforce_cardinality`, `enforce_pii`, `bind_tenant`, `pin_region`) buggy bir propagator'ı simüle ederek
kapıların gerçek regresyonu yakaladığını kanıtlar (`ctx-degraded` örneği + selftest negatif kanıtları).

## 8. İzlenebilirlik

- **FR-TEN-002 / SR-TEN-002 / TC-TEN-002** — tenant binding + cross-tenant=0 (G4/G8).
- **FR-TOOL-010 / SR-TOOL-010 / TC-TOOL-010** — tool çağrıları correlation_id ile izlenir (G5/G6).
- **FR-BIL-002 / SR-BIL-002 / TC-BIL-002** — adapter UsageRecord correlation/tenant/region taşır (G6).
- **FR-RES-012 / SR-RES-012 / TC-RES-012** — sampling + asenkron log, hot-path bloklamaz (G9).
- **FR-REC-004** — PII label/attribute'ta yok (G3).
- **SAD §13.3 / §17.1** — bağlam her kayıtta + W3C traceparent trace omurgası.
- **observability 0.4.7** — `label_policy` producer tarafı (G2 birebir hizalı).
- **eventstream 1.1.8** — envelope `tenant_id`+`correlation_id` zorunlu alanlarının üreticisi.

RTM'de ilgili FR↔SR↔TC çiftleri **zaten eşli**; SRS/RTM değişikliği gerekmedi (3.1.3/3.1.4 ile tutarlı).
Yeni metrikler (`context_missing_total`, `cardinality_violation_total`, ...) 0.4.7 kataloğuna **önerilen**
eklemelerdir.
