# LLM Adapter #1 + #2 — Streaming Token / Tool Call (WBS 4.2.4)

> **Faz:** F1 · **Öncelik:** Must · **İz:** FR-LLM-001/004 (+ FR-LLM-006/008/011/012/013, FR-RES-002/005,
> FR-BIL-002, FR-TOOL-008, FR-KB-010, NFR 10.1/10.7) · SAD §6/§6.1/§8.1/§8.3/§9/§20 · ADR-001/002/003 ·
> API §11.1/§11.4/§11.6
>
> **Kaynak doğruluk:** [`llm-adapter-spec.json`](./llm-adapter-spec.json). Çelişkide BRD/SAD esastır.

## 1. Amaç ve mimari konum

Bu görev, **Sağlayıcı Soyutlama Katmanı**'nda (Adapters; BRD §16, SAD §8) **iki somut `LlmAdapter`
implementasyonunu** (≥2/kategori — ADR-002, FR-LLM-001) ortak SPI (SAD §8.1 / API §11.4 `LlmAdapter`)
arkasına bağlar. **Conversation Orchestrator** (Çekirdek IP; SAD §6/§9, ADR-001) yalnız bu SPI'ye
bağımlıdır — somut sağlayıcı arkada değişir, orchestrator etkilenmez.

```
        ┌──────────────── Conversation Orchestrator (Go/Rust, ADR-003) ────────────────┐
STT ───►│  Turn state machine (SAD §6.1):  LISTEN → CAPTURE → THINK → ACT → SPEAK       │
final   │                                            │                                  │
        │                                  complete(req): LlmRequest                    │
        │                                            ▼                                  │
        │                                  ┌──── LlmAdapter SPI (API §11.4) ────┐        │
        │                                  │  AsyncStream<LlmChunk>             │        │
        │                                  │  = TokenChunk | ToolCallChunk      │        │
        │                                  └──────┬───────────────┬────────────┘        │
        │   TokenChunk{delta} ──► SPEAK (TTS)     │               │  ToolCallChunk ─► ACT │
        └─────────────────────────────────────────┼───────────────┼──────────────────────┘
                                       ┌───────────┴───┐   ┌───────┴────────┐
                                       │ llm-stream-A  │   │ llm-stream-B   │   (≥2 sağlayıcı, ADR-002)
                                       │ bulut multi-  │   │ bölgesel/self- │
                                       │ tier          │   │ host           │
                                       └───────────────┘   └────────────────┘
```

**THINK** durumunda: STT final transcript → diyalog yönetimi → `complete(req)` → token akışı **akış-önce**
(stream-first, FR-RES-002) SPEAK'e beslenir (ilk token gelir gelmez TTS başlar, tüm yanıt tamponlanmaz);
kritik işlem gerektiğinde `ToolCallChunk` ACT'e (tool yürütücü) gider. **Model routing/tiering + semantic
cache** orchestrator/router katmanındadır (SAD §9 — 5.1/5.4); adapter tek sağlayıcıyı temsil eder.

## 2. SPI yüzeyi (API §11.4)

```
interface LlmAdapter extends Adapter {
  complete(req: LlmRequest): AsyncStream<LlmChunk>     // stream token VEYA tool-call (FR-LLM-004/008)
}
type LlmRequest { messages[{role∈{system,user,assistant,tool}, content}], tools[ToolSchema],
                  model, maxTokens, temperature, noTrain }       // noTrain default true (FR-LLM-012)
type LlmChunk      = TokenChunk | ToolCallChunk
type TokenChunk    { delta }
type ToolCallChunk { toolName, argumentsJson, callId }           // serbest metin DEĞİL (FR-LLM-008)
```

Ortak `Adapter` yüzeyi (API §11.1): `capabilities()` / `health()` / `meter()` / `configure()` — yetenekler
4.1.x'te tüketilir. Bir sağlayıcının portföye girmesi için `capabilities()`'te `features ⊇ {streaming,
tool_call}`, `noTrain=true` ve **≥2 model tier** beyan etmesi gerekir (**P5**).

## 3. Görev başlığındaki iki boyut + invariant'lar

| # | Boyut | İnvariant | Ölçüt (HARD) |
|---|-------|-----------|--------------|
| (a) | **Streaming token** | **P1** akış-önce first-token | `first_token_p95 ≤ 400` ms (SAD §20; yeşil 200) + `full_buffered=0` |
| | | **P3** token süreklilik | `token_stall=0` (boşluk eşiği 120 ms; aksi halde TTS ölü hava FR-RES-009) |
| (b) | **Tool call** | **P2** schema-doğrulamalı tool-call | `unhandled_tool=0` (kritik tur serbest metinle bırakılmaz; FR-LLM-008) |

**Ek (Must) boyutlar:** **P4** model tiering (≥2 tier; küçük-tier `first_token_p95 ≤ 200` — FR-LLM-013/
FR-RES-005), **P5** ≥2 SPI-uyumlu sağlayıcı (FR-LLM-001), **P6** no-train + no-log + residency (FR-LLM-012/
FR-KB-010/NFR 10.7), **P7** system prompt değişmezliği (FR-LLM-006), **P8** metering + model/versiyon kaydı
+ hata normalizasyonu (FR-BIL-002/FR-LLM-011/FR-TOOL-008). **P9** komşu seam tüketimi, **P10** ErrorTaxonomy
+ sır/ham-prompt/PII yok.

### Gecikme kapıları (SAD §20 LLM kalemi, 0.2.4 llm-eval eşikleri)

| Metrik | Kapı (P95) | Yeşil | İz |
|--------|-----------:|------:|----|
| First-token (genel) | ≤ 400 ms | ≤ 200 ms | FR-LLM-004, NFR 10.1, SAD §20 |
| First-token (küçük-tier) | ≤ 200 ms | ≤ 120 ms | FR-LLM-013, SAD §20 |
| Token-arası boşluk (stall eşiği) | ≤ 120 ms (stall=0) | — | FR-LLM-004, FR-RES-009 |

First-token, uçtan uca gecikme bütçesinin (NFR 10.1: P95 ≤ 1.200 ms) **en büyük tek kalemidir** (latency
budget 0.3.2 bulgusu: green'de bile ~%36 LLM first-token). Küçük-tier daha hızlı → tiering density+gecikme
için kritik.

## 4. Deterministik referans adapter (`llm_adapter_probe.py`)

`LlmAdapterRuntime` olay-akışını (`request → end`) işler; her `request` (complete çağrısı) için sağlayıcı
**gecikme profilinden** (config providers) streaming first-token, token-arası süreklilik (stall), tool-call
işleme, tier first-token, no-train/residency uygunluğu, system prompt değişmezliği ve usage metering
**deterministik** hesaplanır (**random YOK**; sanal saat = `event.t`). Gerçek LLM çıkarımı **yapılmaz** —
sağlayıcı gecikme profili + akış **modeli** (canlı sistemde Go/Rust async runtime + gerçek `LlmAdapter`,
ADR-003/SAD §6.3/§8.1).

- **P1:** `streaming` açık → first-token = sağlayıcı `first_token_ms` (tier'a göre `first_token_small_ms`);
  kapalı → `output_tokens × per_token_gen_ms` (tüm yanıt tamponlanır → `full_buffered++`, FR-RES-002 ihlali).
- **P3:** `continuity` açık → `inter_token_ms`; kapalı → `inter_token_ms_degraded` (> 120 eşiği → `token_stall++`).
- **P2:** `expects_tool` olan tur `tool_call=true` ise `tool_calls_ok++`, aksi halde `unhandled_tool++`.
- **P4:** tier başına first-token + küçük-tier payı (SR-DEN-005 raporu, kapı değil — router belirler).
- **P6:** `noTrain=false` **veya** retention ∉ {NONE, EPHEMERAL} → `no_train_violation++`; pin yok → `region_violation++`.
- **P7:** `system_preserved=false` → `system_prompt_mutation++`.
- **P8:** her `complete` → `UsageRecord` (INPUT/OUTPUT_TOKENS) + model/versiyon; hata → ErrorTaxonomy.

`_percentile` (lineer-interpolasyon) `media_latency` / `tts_eval` / `latency_budget` probe ile **birebir**.
Geçersiz/sıra-dışı/cross-tenant olaylar **reddedilir** (P10) — sessiz kabul yok.

## 5. İki somut sağlayıcı (illüstratif, vendor-neutral)

| Sağlayıcı | Tip | first-token | küçük-tier | inter-token | tier | no-train | residency | retention |
|-----------|-----|------------:|-----------:|------------:|:----:|:--------:|-----------|-----------|
| `llm-stream-A` | bulut çoklu-tier | 280 ms | 150 ms | 32 ms | küçük/büyük | ✓ | EU/TR | NONE |
| `llm-stream-B` | bölgesel/self-host | 240 ms | 120 ms | 28 ms | küçük/büyük | ✓ | TR | EPHEMERAL |

Her ikisi de tüm kapıları geçer → **ADR-002 portföy** (≥2 + fallback FR-LLM-010). Değerler **mühendislik
varsayılanı** (0.2.4 llm-eval kapılarına uyumlu); gerçek değerler **0.3.x** canlı PoC'ta ölçülür.

## 6. Kapsam ayrımı

Bu görev SPI-uyum **davranışını** (streaming token / tool-call / süreklilik) üretir; komşu **motorları
uygulamaz**, sınırda durur (**P9**):

- **Model router / tiering motoru** (küçük↔büyük seçim, ≥%60 küçük-tier hedefi SR-DEN-005) → **5.1/5.2/5.3**
  (SAD §9). Bu motor sağlayıcının iki tier **sunduğunu** + her tier first-token'ını **doğrular**, router
  **kararını** değil.
- **Semantic cache** (FR-LLM-014) → **5.4**; **prompt-injection** (FR-LLM-007) → **3.3.1**; **policy engine**
  (FR-LLM-009) → **3.3.2**; **LLM fallback anahtarlama** (FR-LLM-010) → **4.3.3** (bu motor ≥2 SPI-uyum +
  ErrorTaxonomy **varlığını** doğrular).
- **Ortak yetenekler** (timeout/retry/breaker/health/pool) → **4.1.2/4.1.6**; **metering motoru** → **4.1.3**
  (UsageRecord üretimi doğrulanır); **residency/retention** → **4.1.4**; **sağlayıcı seçimi** → **0.2.6/0.3.x**.

## 7. Gözlemlenebilirlik (0.4.7)

`complete` başına yayılan metrikler (BRD §15 → observability spec): `llm_first_token_ms` (→ `llm_latency_ms`),
`llm_inter_token_ms`, `llm_token_stall_total`, `llm_tool_call_total`, `llm_input_tokens_total` /
`llm_output_tokens_total` (→ `llm_tokens_total`). `provider_id`/`model`/`tier` **düşük kardinalite** (label
uygun); `request_id`/`call_id`/`correlation_id` **yüksek kardinalite** → yalnız trace/exemplar (0.4.7
`label_policy`, 3.1.5 producer). Ham prompt/çıktı/token değeri/PII metriklerde **yok**.

## 8. İzlenebilirlik

| FR/NFR | SR | TC | Bu görevde |
|--------|----|----|-----------|
| FR-LLM-001 (≥2 sağlayıcı) | SR-LLM-001 | TC-LLM-001 | **P5** (RTM'de WBS=4.2.4 eşli) |
| FR-LLM-004 (streaming token) | SR-LLM-004 | TC-LLM-004 | **P1/P3** (RTM'de WBS=4.2.4 eşli) |
| FR-LLM-008 (tool-call) | SR-LLM-008 | TC-LLM-008 | **P2** (uygulanır; RTM anchor 5.6) |
| FR-LLM-013 (tiering) | SR-LLM-013 | TC-LLM-013 | **P4** (uygulanır; RTM anchor 5.2) |
| FR-LLM-012 (no-train) | SR-LLM-012 | TC-LLM-012 | **P6** (uygulanır; RTM anchor 0.2.4/5.8) |
| FR-LLM-011 (model/ver kaydı) | SR-LLM-011 | TC-LLM-011 | **P8** (uygulanır; RTM anchor 5.7) |
| FR-LLM-006 (system prompt) | SR-LLM-006 | TC-LLM-006 | **P7** (adapter mutasyon yapmaz; RTM anchor 3.2.3) |
| FR-TOOL-008 (hata taksonomisi) | — | — | **P8/P10** (API §11.6) |
| NFR 10.7 (residency) | SR-LOC-* | — | **P6** |

SRS/RTM değişikliği gerekmedi (FR-LLM-001/004 ↔ 4.2.4 zaten eşli; diğer FR'ler SPI-uyum davranışı olarak
uygulanır, asıl motor anchor'ları kendi WBS'lerinde kalır).
