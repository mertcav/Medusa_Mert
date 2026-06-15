# WBS 6.2.2 — Token trimming (bağlam maliyeti sınırı)

> **Faz** F1 · **Öncelik** Must · **İz** FR-KB-011, FR-RES-010 (+ FR-KB-006/007, NFR 10.1/10.7) ·
> **SAD** §10.2 (TRIM aşaması), §9 (context montajı), §6.2 (özetleme) · **Çıktı** `kb/context-trim/`

Bilgi Tabanı & RAG **online retrieval hattının** (SAD §10.2, hot-path) **TRIM aşaması**:

```
... 6.2.1 vector search top-k → rerank (opsiyonel) ──► [TRIM (token budget)] ──► LLM context (kaynak atıflı)
                                                              ▲
              reserved segmentler (3.2.3 prompt + 3.2.2 özet + 3.2.1 history + tool) token-sayılı OPAK girdi
```

6.2.1 `RetrievalEngine`'in ürettiği citation'lı **RankedResult**'ları TÜKETİR (retrieval/embed/rerank
yeniden YAPILMAZ — `retrieval_probe` import edilir); toplam LLM bağlam bütçesi içinde RAG'a kalan
alt-bütçeyi (`rag_available = min(rag_token_budget, context_token_budget − reserved_total)`) hesaplar;
RankedResult'ları **rank sırasıyla** (alaka-önce) greedy paketler; sığmayanı opsiyonel **prefix-truncate**
ile doldurur, geri kalanı düşürür. **INVARIANT (SR-KB-011):** toplam bağlam token'ı yapılandırılan tavanı
**aşmaz**.

## Kullanım
```
python3 context_trim_probe.py validate          # statik spec/config/şema kapısı → çıkış kodu
python3 context_trim_probe.py trim <sample>     # 6.2.1 retrieval → trim → kapı (B1–B10)
python3 context_trim_probe.py selftest          # gömülü davranış kontrolleri
python3 context_trim_probe.py schema            # SPI/TrimmedContext sözleşmesi
python3 tests/context_trim_behavior_test.py     # T1–T10 bağımsız regresyon
bash run_live_test.sh                            # statik + sample (+ canlı NOT)
```

## HARD kapılar (B1–B10)
| Kapı | İçerik |
|------|--------|
| B1 | BUDGET CAP — total_context_tokens ≤ context_token_budget; rag_used ≤ rag_available ≤ rag_token_budget (**SR-KB-011**) |
| B2 | RANK PREFIX — kept = girdinin contiguous rank prefix'i; dropped = suffix (alaka-önce) |
| B3 | CITATION INTEGRITY — her kept document_id+version+chunk_no+source_uri+content_hash taşır (→6.2.3) |
| B4 | TRUNCATION SAFE — truncate content orijinalin ÖN-EKİ; truncated=true; context_content_hash ayrı |
| B5 | NO-EXCEED — en üst chunk tek başına > bütçe olsa da tavan ASLA aşılmaz (truncate/drop) |
| B6 | DETERMINISM — aynı girdi → birebir aynı çıktı |
| B7 | GROUNDING — kept=0 & input vardı → grounded=false + BUDGET_EXHAUSTED (anti-hallucination) |
| B8 | NO-LOG / RESIDENCY — audit yapısal, ham content/soru/PII yok; sağlayıcı çağrısı yok |
| B9 | MONOTONICITY — rag bütçe↑ → kept token azalmaz; reserved↑ → rag_available↓ (FR-RES-010) |
| B10 | ROBUST + SCOPE — structured TrimError, exception kaçmaz; kapsam sınırı |

## FR-RES-010 köprüsü
`reserved_total` (3.2.2 özet + 3.2.1 history) **büyüdükçe** `rag_available` **daralır** → hem konuşma
geçmişi özetleme (3.2.2) hem retrieval token kısıtı (bu motor) token tüketimini düşürür; toplam bağlam
tavanı korunur. Bu, FR-RES-010'un iki yarısının (özetleme + retrieval kısıtı) **tek bütçe altında**
buluştuğu noktadır.

## Kapsam sınırı (bilinçli)
**Yapar:** RAG bağlam token bütçesi paketleme + prefix truncation + grounding düşüş + citation koruma.
**Devreder:** retrieval/embed/rerank → 6.2.1; kaynak-atfı sentezi → 6.2.3; history özetleme → 3.2.2;
versiyonlu system prompt → 3.2.3; per-call bellek bütçe → 3.1.4; gerçek tokenizer → adapter arkası (SPI).

## Vendor-neutral & güvenlik
Tokenizer bir SPI arkasında (ADR-001/002); referans yaklaşık `char//divisor` (6.1.3 ile AYNI) yerine
canlıda gerçek model-özgü tokenizer AYNI imza arkasına. Sır/credential/PII repoya yazılmaz (sentetik
fixture, FR-TST-008); canlı LLM context montajı yalnız `${KB_LLM_ENDPOINT}`.
