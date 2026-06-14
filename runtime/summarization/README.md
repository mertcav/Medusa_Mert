# runtime/summarization — WBS 3.2.2 Token sınırına göre konuşma geçmişi özetleme

Conversation Orchestrator (Çekirdek IP, SAD §6) oturum aktöründe (SAD §6.3) çalışan **Session
Memory**'nin (SAD §6.2: *"Token sınırına gelince özetler — FR-LLM-005"*) **özetleme motoru**.

Bu görev, **3.2.1**'in (`runtime/session-memory/`) `summarization_hook` SEAM'inin **ERTELEDİĞİ**
motoru uygular: 3.2.1 pencere taşınca en eski turn'leri `session_summary`'ye **katlar** (fold) ama
özetleme **MOTORUNU** 3.2.2'ye bırakır. **3.2.2 = o motor.**

## Sorumluluk

Konuşma geçmişinin (yuvarlanan özet + aktif turn penceresi) toplam token'ı yapılandırılan **tavanı**
(`history_token_budget`) aşınca, en eski turn'leri **yuvarlanan bir özete SIKIŞTIRARAK** (LLM tabanlı,
LlmAdapter SPI **küçük tier** — SAD §9/ADR-008) token tüketimini **düşürmek** (FR-RES-010), ama
bağlamı/anlamı **korumak** (FR-LLM-005 — *kırpma değil*).

## HARD kapılar (S1–S8)

| Kapı | İnvariant | Ölçüt |
|------|-----------|-------|
| **S1** | Token-sınırı tetikleme | `spurious_summarize=0` — yalnız tavan aşımında (SR-LLM-005) |
| **S2** | Token azaltma | `history ≤ history_token_budget` + `budget_exceeded_after=0` (FR-RES-010/SR-RES-010) |
| **S3** | Sınırlı yuvarlanan özet | `summary ≤ summary_token_cap` + `summary_overflow=0` (re-compress) |
| **S4** | Özet ≠ kırpma | `uncovered_fold=0` + `coverage ≥ coverage_floor` + `summarized==folded` (SR-LLM-005) |
| **S5** | Sıcak yol korunur | `blocking_summarize=0` + `summarize_latency ≤ budget` (asenkron, küçük tier — NFR 10.1) |
| **S6** | İdempotent/deterministik | `double_summarize=0` + `out_of_order=0` |
| **S7** | Tenant izolasyon | `cross_tenant=0` + adapter no-train/bölgesel (FR-TEN-002/FR-LLM-012) |
| **S8** | Redaction sınırı | `sensitive_cleartext_summarized=0` + durable `redaction_state='pending'` (FR-REC-004/005) |

## Dosyalar

```
summarization-spec.json              # kaynak doğruluk (S1–S10 invariant)
summarization.md                     # tasarım dokümanı
summarization_probe.py               # validate / simulate / selftest / schema (deterministik)
config/summarization-profiles.json   # 3 profil (pilot / enterprise-long / high-density)
samples/
  sum-happy-path.json                # tavan altında → özetleme yok
  sum-token-triggered.json           # tavan aşılır → özetle, history düşer
  sum-rolling-recompress.json        # uzun çağrı → yuvarlanan özet ≤ cap (re-compress)
  sum-budget-mitigation.json         # 3.1.4 WARN-bandı 'özetle' mitigasyon bağlantısı
  sum-degraded.json                  # bilinçli bozuk: kırpma → S4 eler (expect: fail)
tests/summarization_behavior_test.py # T1–T8 davranış kapısı
run_live_test.sh                     # statik + sample (+ canlı NOT)
```

## Çalıştırma

```bash
python3 summarization_probe.py validate          # spec → S1–S10 + config
python3 summarization_probe.py selftest          # iyi/kötü spec+sample negatif kapı kanıtı
python3 summarization_probe.py simulate samples/sum-token-triggered.json
python3 tests/summarization_behavior_test.py     # T1–T8
bash run_live_test.sh                            # hepsi + canlı NOT/SKIP
```

## Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| Pencere/append/fold-tetiği/oturum-sonu persist/temizlik | **3.2.1** (`session-memory/`; bu motor hook'una bağlanır) |
| LLM model tiering / cost-routing / semantic-cache / fallback | **SAD §9 LLM Router** (küçük tier'ı SPI ile kullanır) |
| RAG retrieval top-k / token trimming (FR-RES-010'un diğer yarısı) | **RAG Client SAD §10.2** (SR-KB-011) |
| Versiyonlu system prompt enjeksiyonu | **3.2.3** |
| Per-call bellek bütçe izleme/sınırlama | **3.1.4** (3.2.2 = WARN-bandı 'özetle' mitigasyon motoru) |
| Gerçek tokenizer / token sayımı | adapter arkasında (motor `approx_tokens` kullanır) |
| PII redaction L7 motoru | **3.3.x** |

Vendor-neutral (ADR-002); deterministik (olay-tetikli, sanal saat, **random YOK**; gerçek LLM çağrısı
yok — token-muhasebe + sıkıştırma **modeli**). Sır/credential, ham metin/transkript **metni** ve PII
**değeri** repoya **yazılmadı** — yalnız token + salient-birim **sayıları** + sanal zaman.
```
İz: FR-LLM-005/FR-RES-010 → SR-LLM-005/SR-RES-010 → TC-LLM-005/TC-RES-010 (RTM'de WBS=3.2.2 zaten eşli).
```
