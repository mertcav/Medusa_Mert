# adapters/llm-fallback — WBS 4.3.3 LLM fallback (fallback model / deterministic flow)

> `F1` · `Must` · →FR-LLM-010 · SAD §8.2/§8.3/§9.1 · BRD §19 (1)/(4) · API §11.4

## 1. Amaç ve kapsam

Sağlayıcı Soyutlama Katmanı'nın **fallback ve degradation** dilimi: LlmAdapter SPI (SAD §8.1 / API §11.4)
**arkasında** ortak fallback ANAHTARLAMA mantığı. SAD §8.3 + §9.1 [4] zinciri:

```
Primary LLM ──(timeout/error/circuit-open)──► Fallback model ──► Deterministic flow
```

Çekirdek davranış (FR-LLM-010): aktif (birincil) LLM modeli geçici hata/timeout (circuit-open) verince
**fallback modele geçilir**; tur isteği (messages/tools/system prompt) fallback modele **yeniden gönderilir**
(context yeniden sunumu — ham audio replay'in LLM karşılığı); birincil + fallback de düşerse veya
yapılandırma/politika sınıfı hatalarda **deterministik akışa** (kural-tabanlı güvenli yanıt / insan temsilciye
kontrollü aktarım) geçilir — **çağrı düşürülmez** (SAD §8 ilke 6 "fail soft, never drop the call"; BRD §19 (4)).
Orchestrator yalnız LlmAdapter SPI'ye + switcher kararına bağımlıdır (ADR-001); somut model arkada değişir
(ADR-002). STT/TTS/Telephony adapter'larından (`switching_owned_by 4.3.x`) buraya delege edilen LLM dilimidir;
4.2.4 LlmAdapter bu görevin VARLIĞINI bekler.

### LLM'e özgü iki güvenlik invariant'ı (STT/TTS'te YOK)

LLM turu bir istek/yanıt akışıdır; token'lar **konuşulur** ve tool çağrıları **yan etki** yapar. Bu yüzden
fallback STT/TTS'ten iki ek güvenlik gerektirir:

- **Mid-stream güvenliği (L3):** Birincil model **ilk token** downstream'e (TTS) gittikten **sonra** düşerse,
  fallback modele **sessizce yeniden istek** yapmak **çift/çelişkili konuşma** üretir. Bu durumda switcher
  yeniden istek YAPMAZ → tur **güvenli degrade**'e (deterministik) gider (`double_speak=0`). İlk-token
  **öncesi** hatalar **temiz failover** (context yeniden sunumu).
- **Tool idempotency (L4):** Birincil modelin tetiklediği **yan etkili** tool çağrısı (ör. ödeme/rezervasyon)
  zaten yürütülmüşse, fallback'e geçişte bu tool **yeniden yürütülmez** (`double_tool_exec=0`; FR-TOOL-009 +
  FR-LLM-008). İdempotency anahtarı 7.x'te; switcher **tekrar-yürütmeme kararını** verir.

## 2. Üretilen artefaktlar (`adapters/llm-fallback/`)

| Dosya | Rol |
|-------|-----|
| `llm-fallback-spec.json` | Kaynak doğruluk: placement (THINK, SPI arkası), spi (sarmalanan complete()), gates (L1–L8), fallback zinciri, error_taxonomy (failover/non-failover + CONTENT_FILTERED), residency, pii, invariants L1–L10 |
| `llm-fallback.md` | Tasarım: mimari konum, HARD kapılar, routing kararı (seçici tetik), context yeniden sunumu, mid-stream/idempotency güvenliği, histerezis, kapsam ayrımı, izlenebilirlik |
| `llm_fallback_probe.py` | stdlib-only: `validate` / `simulate <sample>` (deterministik `LlmFallbackRuntime`) / `selftest` / `schema` |
| `config/llm-fallback-profiles.json` | İllüstratif 2 SPI-uyumlu sağlayıcı (`llm-cloud-A`/`-B`) + 1 elenen (`-C-degraded`) + 3 çalıştırma profili (primary+fallback+bölge+`deterministic_flow_id`); sır YOK |
| `samples/*.json` | failover-resubmit / no-failover-clean / both-fail-deterministic / midstream-tool-safe-degrade / selective-content-filter (geçer) + degraded (eler) |
| `tests/llm_fallback_behavior_test.py` | Davranış kapısı T1–T10 |
| `run_live_test.sh` | Statik + sample + (canlı SKIP/not; `${LLM_PRIMARY_URL}`/`${LLM_SECONDARY_URL}`) |
| `README.md` | Dizin özeti + kapı durumu |

## 3. HARD kapılar (L1–L8)

| Kapı | Ölçüt | İz |
|------|-------|----|
| **L1 FAILOVER** | geçici hata/timeout → fallback modele geçiş, çağrı sürer (`turn_lost=0`) | FR-LLM-010, SAD §8.3/§9.1, BRD §19 (4) |
| **L2 CONTEXT RESUBMIT** | ilk-token öncesi failover'da istek fallback'e yeniden sunulur (`missing_context=0` + `system_prompt_mutation=0`) | FR-LLM-010, FR-LLM-006 |
| **L3 MID-STREAM SAFE / DUP YOK** | ilk token sonrası sessiz yeniden istek yok (`double_speak=0`) + `duplicate_response=0` + `concurrent_active≤1` | FR-RES-009, FR-LLM-004 |
| **L4 TOOL IDEMPOTENCY** | yan etkili tool yeniden yürütülmez (`double_tool_exec=0`) | FR-TOOL-009, FR-LLM-008 |
| **L5 SWITCH OVERHEAD + ≥2 SAĞLAYICI** | anahtarlama (teardown+fallback setup+fallback ilk token) P95 ≤ 500 ms (yeşil 300) + `min_providers=2`, primary≠fallback | NFR 10.1, SAD §20, BRD §19 (1), ADR-002 |
| **L6 NEVER DROP** | birincil+fallback düşerse deterministik akış, `dropped_call=0` | SAD §8.3/§9.1, BRD §19 (4) |
| **L7 SEÇİCİ TETİK + NORMALİZE** | yalnız geçici/kota sınıfı failover (`improper_failover=0`) + `errors_normalized=errors_seen` | FR-TOOL-008, API §11.6 |
| **L8 FLAP YOK + METERING + MODEL/VER + RESIDENCY** | `flap=0` (histerezis) + segment metering + model/versiyon kaydı + noTrain/region | FR-BIL-002, FR-LLM-011/012, NFR 10.7 |

L9 (komşu SEAM tüketimi) + L10 (ErrorTaxonomy + sır/ham-prompt/PII yok) sınır invariant'ları. Eşikler
**mühendislik varsayılanı** (NFR 10.1 + 0.2.4 llm-eval SAD §20 LLM first-token bandı); gerçek değerler 0.3.x
canlı PoC'ta.

> **Switch overhead neden STT/TTS'ten geniş (500 vs 200)?** LLM failover'ında fallback **fresh first-token**
> üretmek zorundadır (turu yeniden çalıştırır); switch overhead = `primary.teardown + fallback.setup +
> fallback.first_token`. STT/TTS failover'ında ise akışın yalnızca kalanı devralınır (replay/resynth).
> Canlı sistemde bu ölü hava filler audio ("bir saniye...") ile maskelenebilir.

### Routing kararı (L7 — seçici tetik)

| Taksonomi (API §11.6) | Failover? |
|-----------------------|-----------|
| `TIMEOUT` / `RATE_LIMITED` / `UNAVAILABLE` (5xx/circuit-open) | ✅ fallback modele geç + context yeniden sun |
| `QUOTA_EXCEEDED` | ✅ fallback modele geç (**ayrı sağlayıcı = ayrı kota**) |
| `AUTH` / `INVALID_REQUEST` / `REGION_VIOLATION` | ❌ fallback'te de aynı sonuç → deterministik akış |
| `CONTENT_FILTERED` | ❌ **politika** sonucu — başka model de reddeder → politika motoru/deterministik akış (3.3.2) |

**Histerezis (L8):** bir kez fallback'e geçilince seans boyunca fallback kalır (sticky fallback); primary
"iyileşti" diye geri dönülmez (flap yok).

## 4. Fallback ≠ Routing (kritik kapsam ayrımı)

Model **routing/tiering** (SAD §9 — 5.1/5.2/5.3): router her tur için **en ucuz yeterli modeli** seçer
(küçük↔büyük tier, ≥%60 küçük-tier hedefi SR-DEN-005). **Fallback** (4.3.3): seçilen model **düştüğünde**
kurtarır. İkisi ayrı katmandır — bu motor model **seçmez**; router'ın seçtiği model hata verince devreye
girer. (STT 4.3.1'in 4.2.x'ten, TTS 4.3.2'nin 4.2.3'ten ayrıldığı gibi.)

## 5. İlkeler

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (olay-tetikli, sanal saat,
random YOK; gerçek LLM çıkarımı yok — sağlayıcı gecikme profili + akış/hata MODELİ). Canlı sistemde Go/Rust
async runtime (ADR-003) + gerçek LlmAdapter + 4.1.2 circuit breaker. Ham PROMPT/çıktı/token/PII/sır repoya
yazılmaz (yalnız sağlayıcı/model kimliği + sayılar + tur/tool kimlikleri + sanal zaman + normalize hata sınıfı).

## 6. Kapsam ayrımı (TÜKETİR / SINIRDA durur — L9)

| Komşu | İlişki |
|-------|--------|
| 4.2.4 LlmAdapter (streaming token/tool-call) | **Sarmalar**, uygulamaz; LlmAdapter bu görevin varlığını bekler |
| 4.1.2 ortak yetenekler (timeout/retry/breaker/health) | circuit-open sinyali **tüketilir** |
| 4.1.5 hata normalizasyonu (ErrorTaxonomy eşlemesi) | **tüketilir** (routing yalnız normalize enum'a göre) |
| 4.1.3 metering motoru | UsageRecord + model/versiyon **üretimi doğrulanır** |
| 4.1.4 residency/retention · 4.1.6 connection pool | **tüketilir** |
| 5.1-5.3 model router/tiering · 5.4 semantic cache | **ayrı katman** (fallback model seçmez) |
| 3.3.2 policy engine (CONTENT_FILTERED yanıtı) | **kararı delege edilir** |
| 7.x tool yürütücü + idempotency anahtarı (FR-TOOL-009) | tekrar-yürütmeme **kararı** üretilir, anahtar 7.x'te |
| 8.x handoff + 3.3.x deterministic flow motoru | **kararı** üretilir, aktarım/yanıt akışı değil |
| 0.2.4/0.2.6/0.3.x LLM sağlayıcı seçimi | vendor-neutral; bu motor **seçmez** |

## 7. İzlenebilirlik

`llm_fallback_total{from,to,reason}` (SAD §17.1 retry/fallback), `llm_switch_overhead_ms`,
`llm_deterministic_flow_total`, `llm_turn_total`, `llm_double_speak_total` / `llm_double_tool_exec_total`
(L3/L4 güvenlik alarmı — sağlıklı=0) → observability 0.4.7. `provider_id`/`model`/`reason` düşük kardinalite
(label uygun); `call_id`/`turn_id`/`correlation_id` yüksek kardinalite → yalnız trace/exemplar (0.4.7
label_policy, 3.1.5 producer). Ham prompt/çıktı/token/PII metriklerde yok. → `reports/4.3.3-llm-fallback-raporu.md`
