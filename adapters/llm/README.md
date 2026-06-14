# adapters/llm — WBS 4.2.4 LLM adapter #1 + #2 (streaming token / tool call)

Sağlayıcı Soyutlama Katmanı'nda (Adapters; BRD §16, SAD §8) **iki somut `LlmAdapter` implementasyonunu**
(≥2/kategori — ADR-002, FR-LLM-001) ortak SPI (SAD §8.1 / API §11.4) arkasına bağlar. Orchestrator
(Çekirdek IP, SAD §6/§9; ADR-001) **yalnız** bu SPI'ye bağımlıdır; sağlayıcı arkada değişir. Turn state
machine'in (SAD §6.1) **THINK** durumunda çalışır: `complete(req) → AsyncStream<LlmChunk>`
(`LlmChunk = TokenChunk | ToolCallChunk`). Token akışı SPEAK'e (TTS) beslenir; `ToolCallChunk` ACT'e gider.

## Görev başlığındaki iki boyut

1. **Streaming token** — ilk token akış-önce (no full buffering — FR-RES-002) düşük gecikmeyle; first-token
   P95 ≤ SAD §20 (genel 400 ms) + `full_buffered=0` (**P1**, FR-LLM-004) + token-arası süreklilik
   (`token_stall=0` — **P3**, aksi halde TTS ölü hava FR-RES-009).
2. **Tool call** — kritik işlemler serbest metin yerine schema-**doğrulamalı** tool-call
   (`ToolCallChunk{toolName, argumentsJson, callId}`) ile; `unhandled_tool=0` (**P2**, FR-LLM-008).

## HARD kapılar (P1–P8)

| Kapı | İnvariant | Ölçüt |
|------|-----------|-------|
| **P1** | Streaming token first-token | `first_token_p95 ≤ 400` + `full_buffered=0` (FR-LLM-004/SAD §20) |
| **P2** | Schema-doğrulamalı tool-call | `unhandled_tool=0` (FR-LLM-008) |
| **P3** | Token süreklilik / stall yok | `token_stall=0` (stall eşiği 120 ms; FR-LLM-004/FR-RES-009) |
| **P4** | Model tiering | `min_tiers=2` + küçük-tier `first_token_p95 ≤ 200` (FR-LLM-013) |
| **P5** | ≥2 SPI-uyumlu sağlayıcı | required_features + noTrain + ≥2 tier (FR-LLM-001/ADR-002) |
| **P6** | No-train + no-log + residency | `no_train_violation=0` + `region_violation=0` (FR-LLM-012/FR-KB-010/NFR 10.7) |
| **P7** | System prompt değişmezliği | `system_prompt_mutation=0` (FR-LLM-006) |
| **P8** | Metering + model/ver + taksonomi | UsageRecord/req + model/version + ErrorTaxonomy |

`P9` (komşu seam) + `P10` (ErrorTaxonomy / sır+ham-prompt+PII yok) → `validate`.

## Dosyalar

```
llm-adapter-spec.json                 # kaynak doğruluk (P1–P10 invariant)
llm-adapter.md                        # tasarım dokümanı
llm_adapter_probe.py                  # validate / simulate / selftest / schema (deterministik)
config/llm-adapter-profiles.json      # 2 somut sağlayıcı (A bulut / B bölgesel) + 3 çalıştırma profili
samples/
  llm-happy-path.json                 # streaming token + tiering (A)
  llm-tool-call.json                  # 3 kritik tur → schema-doğrulamalı tool-call (P2)
  llm-tiering.json                    # küçük+büyük tier, küçük-tier payı %60 (B; P4)
  llm-no-train-residency.json         # noTrain + NONE + bölgesel pin + CONTENT_FILTERED (P6/P8)
  llm-fallback-secondary.json         # primary UNAVAILABLE → normalize + ikincil devam (P8/P9 sınır)
  llm-degraded.json                   # bilinçli bozuk: stream/tool/continuity/system kapalı → P1/P2/P3/P7 eler
tests/llm_adapter_behavior_test.py    # T1–T8 davranış kapısı
run_live_test.sh                      # statik + sample (+ canlı NOT)
```

## Çalıştırma

```bash
python3 llm_adapter_probe.py validate              # spec → P1–P10 + config
python3 llm_adapter_probe.py selftest              # iyi/kötü spec+sample negatif kapı kanıtı
python3 llm_adapter_probe.py simulate samples/llm-tool-call.json
python3 tests/llm_adapter_behavior_test.py         # T1–T8
bash run_live_test.sh                              # hepsi + canlı NOT/SKIP
```

## İki somut sağlayıcı (illüstratif, vendor-neutral)

| Sağlayıcı | Tip | first-token (büyük) | küçük-tier | tier | no-train | residency | retention |
|-----------|-----|--------------------:|-----------:|:----:|:--------:|-----------|-----------|
| `llm-stream-A` | bulut çoklu-tier | 280 ms | 150 ms | küçük/büyük | ✓ | EU/TR | NONE |
| `llm-stream-B` | bölgesel/self-host | 240 ms | 120 ms | küçük/büyük | ✓ | TR | EPHEMERAL |

Her ikisi de tüm kapıları geçer → ADR-002 portföy (≥2 + fallback FR-LLM-010). Gecikme değerleri
**mühendislik varsayılanı**; gerçek değerler 0.3.x canlı PoC'ta ölçülür.

## Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| Model **router / tiering motoru** (küçük↔büyük seçim, ≥%60 hedef) | **5.1 / 5.2 / 5.3** (SAD §9; bu motor ≥2 tier sunumu + küçük-tier first-token doğrular, router kararını değil) |
| Semantic cache (tekrarlayan turda LLM atlama) | **5.4** (FR-LLM-014; orchestrator katmanı) |
| Prompt-injection / jailbreak kontrolü | **3.3.1** (FR-LLM-007) |
| Politika motoru (model çıktısı policy gate) | **3.3.2** (FR-LLM-009) |
| LLM fallback **anahtarlama** + deterministic flow | **4.3.3** (FR-LLM-010; bu motor ≥2 SPI-uyum + ErrorTaxonomy varlığını doğrular) |
| Ortak yetenekler (timeout/retry/breaker/health/pool) | **4.1.2 / 4.1.6** (SAD §8.2; tüketilir) |
| Usage metering / cost **motoru** | **4.1.3** (UsageRecord üretimi doğrulanır) |
| Region/retention **motoru** | **4.1.4** (NFR 10.7) |
| Tenant/use-case model seçimi | **5.5 / 5.1** (FR-LLM-002/003) |
| Sağlayıcı **seçimi** | **0.2.6 / 0.3.x** (vendor-neutral, ADR-002) |

Vendor-neutral (ADR-002); deterministik (olay-tetikli, sanal saat, **random YOK**; gerçek LLM çıkarımı
yok — sağlayıcı gecikme profili + akış **modeli**). Sır/credential, ham **PROMPT/mesaj**, model **çıktısı**
ve PII **değeri** repoya **yazılmadı** — yalnız sağlayıcı kimliği + gecikme/akış/token sayıları + model/
tier/tool kimlikleri + sanal zaman.

```
İz: FR-LLM-001 → SR-LLM-001 → TC-LLM-001 (RTM'de WBS=4.2.4 zaten eşli); FR-LLM-004 → SR-LLM-004 →
TC-LLM-004 (WBS=4.2.4 eşli) + FR-LLM-008 (tool-call; RTM anchor 5.6), FR-LLM-013 (tiering; 5.2),
FR-LLM-012 (no-train; 0.2.4/5.8), FR-LLM-011 (metering; 5.7) — bu adapter'da SPI-uyum davranışı uygulanır.
SRS/RTM değişikliği gerekmedi.
```
