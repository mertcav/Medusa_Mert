# Summarization Engine — Token-sınırı konuşma geçmişi özetleme (WBS 3.2.2)

> **Faz:** F1 · **Öncelik:** Must · **İz:** FR-LLM-005, FR-RES-010 · SAD §6.2/§9/§20
> **Çıktı:** `runtime/summarization/`
> Kaynak doğruluk: `docs/SAD.md` (§6.2/§9), `docs/BRD.md` (§8.1/§15), `docs/SRS.md` (SR-LLM-005/SR-RES-010). Çelişkide dokümanlar esastır.

## 1. Amaç ve konum

SAD §6.2 Session Memory'yi şöyle tanımlar: *"Kısa süreli diyalog belleği, özetleme — **Token
sınırına gelince özetler (FR-LLM-005)**; bellekte tutar, oturum sonunda kalıcılaştırılır."*

**3.2.1** (`runtime/session-memory/`) bu cümlenin **bellek + kalıcılaştırma** yarısını uyguladı ve
özetleme MOTORUNU `summarization_hook` (`fold_target=session_summary`, `engine_out_of_scope=3.2.2`)
ile **3.2.2'ye erteledi**. **Bu görev o motordur.**

Motor Conversation Orchestrator oturum aktöründe (SAD §6.3) Session Memory'nin bir alt-fonksiyonudur.
Konuşma geçmişinin LLM bağlamındaki payı = `rolling_summary_tokens + Σ(aktif pencere turn token)`.
Bu pay `history_token_budget`'ı aşınca, en eski turn'ler **yuvarlanan özete sıkıştırılır**.

## 2. Model

Bir **turn** = `{turn_id, speaker∈{caller,agent,human}, seq, approx_tokens, salient_units, t}`.
`salient_units` = turn'ün taşıdığı korunması gereken bilgi birimi **sayısı** (varlık/karar/taahhüt;
PII *değeri* değil — yalnız sayı).

```
history_tokens = summary_tokens + Σ window.approx_tokens
tetik (S1)   : history_tokens > history_token_budget  →  en eski turn'ü (FIFO) özete katla
                (tavan altında TETİKLEMEZ — spurious=0)  ; en az 1 turn pencerede kalır
sıkıştır(S4) : batch → özet katkısı = ceil(batch_tokens × compression_ratio)
                salient_kept += batch_salient × summary_retention   (KIRPMA DEĞİL)
yuvarla (S3) : summary_tokens + katkı > summary_token_cap  →  özyinelemeli RE-COMPRESS
                summary_tokens = cap  (TOKEN sıkışır; salient FACT'leri korunur)
azaltma (S2) : döngü sonunda  history_tokens ≤ history_token_budget   (token tüketimi düşer)
sıcak yol(S5): özetleme turlar ARASINDA, küçük tier'da, ASENKRON  →  yanıt turunu bloklamaz
```

### Özet ≠ kırpma (S4 — motorun kalbi)

Token-sınırı naif olarak en eski turn'leri **düşürerek** (truncate) de karşılanabilir — ama bu **bilgi
kaybıdır**; FR-LLM-005 *özetleme* ister (SR-LLM-005: *"sınır aşımında özetleme tetiklenir; **bağlam
korunur**"*). İki kapı bunu zorlar:

1. **Kapsama:** katlanan **her** turn özete girer (`summarized_turns == folded_turns`, `uncovered_fold=0`).
2. **Koruma:** salient bilgi `coverage_floor` üstünde korunur (`coverage = korunan_salient/toplam ≥ floor`).

Naif `truncate_instead` → `uncovered_fold>0` + `coverage<floor` → **S4 eler** (degraded sample bunu kanıtlar).

### Yuvarlanan özet kayıpsızlığı (S3 ↔ 3.2.1 M5)

Re-compress **token'ı** sıkıştırır ama salient **fact**'leri korur — coverage kaybı yalnız tek-seferlik
turn→özet çıkarımından (`summary_retention`) gelir, özyineleme derinliğinden **değil**. Dahası,
**dayanıklı kayıt** kaynak doğruluktur, özet değil: 3.2.1'in `persisted_turns == captured_turns`
invariant'ı (M5/M9) **tüm** turn'leri oturum sonunda durable kayda **tam** yazar. Özet yalnız **prompt
bağlamını** küçültür (token tüketimi) — geçmişin kaynağı transcript'tir.

## 3. Mimari yerleşim ve sıcak yol (S5)

Özetleme LLM çağrısı **küçük tier**'da (SAD §9 model tiering, ADR-008; FR-RES-005 *"turların ≥%60'ı
küçük modelde"*) LlmAdapter SPI üzerinden, **turlar arasında / arka planda asenkron** yapılır → yanıt
turunu (THINK→SPEAK ilk-ses, NFR 10.1) **bloklamaz**. Bloklayan özetleme (`blocks_turn`) e2e tur
gecikmesine eklenir → **S5 eler**. Özet bir sonraki THINK gerekmeden hazır olur.

## 4. Komşu seam'ler (tüketilir, uygulanmaz)

| Seam | Sağlayan | 3.2.2 ilişkisi |
|------|----------|-----------------|
| `summarization_hook` (fold_target=session_summary) | **3.2.1** | bu motor o hook'a **bağlanır** |
| per-call bütçe WARN-bandı 'özetle' mitigasyonu (`summarize_factor`) | **3.1.4** | 3.2.2 = o mitigasyonun **motoru** |
| küçük tier / LlmAdapter / no-train / bölgesel | **SAD §9 / 0.2.4** | motor **kullanır** (routing'i uygulamaz) |
| RAG top-k / token trimming (FR-RES-010 diğer yarısı) | **RAG Client SAD §10.2** | kardeş kol (SR-KB-011) |

## 5. HARD kapı tablosu

| Kapı | İnvariant | Ölçüt | İz |
|------|-----------|-------|-----|
| **S1** | Tetik doğruluğu | `spurious_summarize=0` | FR-LLM-005, SR-LLM-005 |
| **S2** | Token azaltma | `history ≤ budget`, `budget_exceeded_after=0` | FR-RES-010, SR-RES-010 |
| **S3** | Sınırlı özet | `peak_summary ≤ cap`, `summary_overflow=0` | FR-RES-010, NFR 10.2 |
| **S4** | Özet ≠ kırpma | `uncovered_fold=0`, `coverage ≥ floor`, `summarized==folded` | FR-LLM-005, SR-LLM-005 |
| **S5** | Sıcak yol | `blocking_summarize=0`, `summarize_latency ≤ budget` | NFR 10.1, SAD §9/§20 |
| **S6** | İdempotent/det. | `double_summarize=0`, `out_of_order=0` | SAD §6.3, ADR-002 |
| **S7** | İzolasyon | `cross_tenant=0`, adapter no-train/bölgesel | FR-TEN-002, FR-LLM-012, NFR 10.7 |
| **S8** | Redaction | `sensitive_cleartext_summarized=0`, durable `pending` | FR-REC-004/005 |

## 6. Doğrulama

| Kapı | Sonuç |
|------|-------|
| `validate` (spec → S1–S10 + config + sır) | **63/63** 🟢 |
| `selftest` (iyi/kötü spec+sample; negatif kapı kanıtı) | **55/55** 🟢 |
| `tests/summarization_behavior_test.py` (T1–T8) | **29/29** 🟢 |
| 5 sample simulate | 4 pass + `sum-degraded` eler (beklenen) 🟢 |
| `run_live_test.sh` | exit 0; canlı SKIP (`ORCHESTRATOR_URL` yok) |

**Örnek (sum-rolling-recompress, high-density-tight):** 18 turn × 300 token = 5400 → 13 turn katlandı,
yuvarlanan özet **6 kez re-compress** ile 400/400 token'da sabit (overflow=0), history 1900/2000 ≤ tavan,
**3198 token tasarruf**, coverage **0.957** ≥ 0.88 — token düşer, bağlam korunur.

**Negatif kapı kanıtı:** `truncate_instead` → uncovered_fold>0 + coverage 0.75 (S4 eler); `summarize=false`
→ history tavanı aşar (S2 eler); `bound_summary=false` → özet cap'i aşar (S3 eler); `eager_summarize`
→ tavan altında özetleme (S1 eler); `blocks_turn` → sıcak yola gecikme (S5 eler); `strip_card_otp=false`
→ kart/OTP özete düz-metin (S8 eler); cross-tenant turn (S7 eler).

## 7. Sınırlar / sonraki adımlar

- **İskelet/sözleşme + deterministik referans motor**dur; canlı sistemde Go/Rust async runtime
  (ADR-003/SAD §6.3) gerçek **LlmAdapter** (küçük tier, no-train/bölgesel) + gerçek tokenizer + LLM
  context-window ile koşar — **kapı kodu değişmez**.
- Gerçek özetleme **kalite/maliyet** (sıkıştırma oranı, LLM prompt'u, dil duyarlılığı) canlı PoC'ta
  ölçülür; bu görev token-bütçe **sözleşmesini** + "özet ≠ kırpma" invariant'ını sabitler.
- Vendor-neutral (ADR-002); sır/PII/ham metin/transkript repoya **yazılmadı**.
