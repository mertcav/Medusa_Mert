# Vendor Evaluation — `docs/vendor-eval/`

Bu klasör, WBS **0.2 (Vendor değerlendirme)** görevlerinin kaynak doğruluğudur. Her sağlayıcı
kategorisi için **ölçüt-tabanlı, sağlayıcı-nötr ve tekrarlanabilir** değerlendirme dokümanları,
ölçüm hattı (harness) ve örnek profilleri burada tutulur.

## İlkeler (CLAUDE.md ile uyumlu)
- **Vendor-neutral (ADR-002):** Bu dokümanlar **sağlayıcı seçmez**. Ölçüt + ölçüm üretir; nihai
  seçim **0.2.6 Vendor karar raporu**'nda bütünsel (gecikme + maliyet + residency + DPA + risk) yapılır.
- **Tekrarlanabilir:** Ölçümler stdlib-only harness ile, sabit metodoloji altında alınır; gerçek
  sağlayıcı bağlantısı yalnız `--url`/ortam değişkeni ile dışarıdan verilir. **Sır/credential repoya yazılmaz.**
- **Türetilen artefakt ayrımı:** `samples/*.json` = ham/illüstratif girdi; özet+karşılaştırma çıktıları türetilir.

## İçerik
| Dosya | Kapsam | WBS · İz |
|-------|--------|----------|
| `telephony-media-latency.md` | Telekom sağlayıcı eval — medya streaming gecikmesi | 0.2.1 · ADR-002, FR-TEL-002, FR-RTC-001, NFR 10.1, SAD §20 |
| `media_latency_probe.py` | Medya-streaming gecikme ölçüm hattı (serve/probe/stats/compare) | 0.2.1 |
| `stt-eval.md` | STT sağlayıcı eval — WER/CER (EN+TR), partial/final, confidence, final-gecikme, 8 kHz | 0.2.2 · FR-STT-001..008, FR-RES-008, NFR 10.1, SAD §8.1/§20 |
| `stt_eval_probe.py` | STT değerlendirme hattı (score/compare/selftest; WER/CER/gecikme/kalibrasyon + kapı) | 0.2.2 |
| `tts-eval.md` | TTS sağlayıcı eval — first-byte, barge-in kesme, ses kalitesi (MOS EN+TR), ölü hava, telaffuz, 8 kHz | 0.2.3 · FR-TTS-001..010, FR-RTC-002, FR-RES-008/009, NFR 10.1, SAD §6.1/§8.1/§20 |
| `tts_eval_probe.py` | TTS değerlendirme hattı (score/compare/selftest; TTFB/barge-in/MOS/ölü-hava/telaffuz + kapı) | 0.2.3 |
| `llm-eval.md` | LLM sağlayıcı eval — first-token (genel+küçük/büyük tier), no-train/no-log, bölgesel endpoint, kalite (EN+TR), tool-call, stall | 0.2.4 · FR-LLM-001..014, FR-RES-005, FR-KB-010, NFR 10.1/10.7, SAD §8.1/§9/§20 |
| `llm_eval_probe.py` | LLM değerlendirme hattı (score/compare/selftest; TTFT/tier/kalite/no-train/bölge/stall/tool-call + kapı) | 0.2.4 |
| `vector-db-eval.md` | Vector DB eval (pgvector vs OpenSearch) — RAG retrieval recall@k (en-kötü sorgu sınıfı), retrieval gecikme, tenant namespace izolasyon, metadata/ACL filtre, residency/no-log | 0.2.5 · SAD §12.1/§10/§20, FR-KB-003..011, FR-TEN-002, NFR 10.7 |
| `vector_db_eval_probe.py` | Vector DB değerlendirme hattı (score/compare/selftest; recall@k/retrieval-gecikme/cross-tenant+ACL leak/residency + kapı) | 0.2.5 |
| `vendor-decision.md` | **Vendor karar raporu** — 0.2.1–0.2.5 kapı roll-up + ticari/uyumluluk/risk boyutları + ADR-002 portföy kapısı + karar kayıtları (provizyonel) | 0.2.6 · SAD §8.1/§8.4, ADR-002, BRD §19 |
| `contract-dpa-checklist.md` | **Sözleşme/DPA/alt-işleyen taslağı** — RMC↔sağlayıcı + tenant↔RMC checklist'i + alt-işleyen kayıt (Ek-A) iskeleti + sağlayıcıya giden veri kaydı | 0.2.6 (+17.2.2) · BRD §14.1, DPIA §2/§5, NFR 10.7, FR-LLM-012/FR-KB-010 |
| `vendor_decision_probe.py` | Vendor karar birleştirme hattı (rollup/register/selftest; 0.2.x score/stats JSON → karar matrisi + portföy kapısı + Ek-A iskeleti) | 0.2.6 |
| `samples/*.json` | İllüstratif profiller: telefoni gecikme (`managed-*`/`raw-*`) + STT (`stt-*`) + TTS (`tts-*`) + LLM (`llm-*`) + Vector DB (`vdb-*`) test setleri; PoC'ta gerçek ölçümle değişir | 0.2.1/0.2.2/0.2.3/0.2.4/0.2.5 |

> 0.2.x tamam → **0.3.x PoC** (canlı ölçüm) + **17.2.2** (DPA/alt-işleyen implementasyonu). Bağlayıcı
> sağlayıcı seçimi `vendor-decision.md`'de **provizyonel**; 0.3.x canlı ölçüm + DPA imzasında netleşir.

## Harness hızlı başvuru
```bash
# 1) Self-test (gerçek credential olmadan): loopback echo + probe
python3 docs/vendor-eval/media_latency_probe.py serve --once --port 8765 &
python3 docs/vendor-eval/media_latency_probe.py probe --url ws://127.0.0.1:8765/media \
    --frames 500 --payload-mode twilio-json --out /tmp/loopback.json

# 2) Ham örnekten özet + bütçe kapısı
python3 docs/vendor-eval/media_latency_probe.py stats docs/vendor-eval/samples/managed-cpaas-ws-A.json

# 3) Çok sağlayıcılı karşılaştırma matrisi
python3 docs/vendor-eval/media_latency_probe.py compare /tmp/*.json --out /tmp/compare.md
```
Çıkış kodu: bütçe kapısı geçerse `0`, geçmezse `1` (CI gate olarak kullanılabilir).

### STT eval (0.2.2)
```bash
# 1) Self-test (credential'sız): WER/CER/gecikme/kalibrasyon çekirdek doğrulama
python3 docs/vendor-eval/stt_eval_probe.py selftest

# 2) Bir sağlayıcı test setini puanla + kapı (WER en-kötü-dil, CER, final P95, partial/final, confidence)
python3 docs/vendor-eval/stt_eval_probe.py score docs/vendor-eval/samples/stt-cloud-A.json --out /tmp/stt-A.json

# 3) Çok sağlayıcılı karşılaştırma matrisi
python3 docs/vendor-eval/stt_eval_probe.py compare /tmp/stt-*.json --out /tmp/stt-compare.md
```
Çıkış kodu: tüm kapılar geçerse `0`, biri elerse `1`. Sağlayıcı API anahtarı yalnız ortam değişkeniyle (canlı PoC); **repoya yazılmaz**.

### TTS eval (0.2.3)
```bash
# 1) Self-test (credential'sız): TTFB/barge-in/MOS/ölü-hava çekirdek doğrulama
python3 docs/vendor-eval/tts_eval_probe.py selftest

# 2) Bir sağlayıcı test setini puanla + kapı (first-byte P95, barge-in P95, MOS en-kötü-dil, ölü hava)
python3 docs/vendor-eval/tts_eval_probe.py score docs/vendor-eval/samples/tts-cloud-A.json --out /tmp/tts-A.json

# 3) Çok sağlayıcılı karşılaştırma matrisi
python3 docs/vendor-eval/tts_eval_probe.py compare /tmp/tts-*.json --out /tmp/tts-compare.md
```
Çıkış kodu: tüm kapılar geçerse `0`, biri elerse `1`. MOS dış girdidir (panel/kalibre vekil); credential yalnız ortam değişkeniyle, **repoya yazılmaz**.

### LLM eval (0.2.4)
```bash
# 1) Self-test (credential'sız): TTFT/tier/kalite/no-train/bölge/stall çekirdek doğrulama
python3 docs/vendor-eval/llm_eval_probe.py selftest

# 2) Bir sağlayıcı turn test setini puanla + kapı (TTFT genel+küçük-tier, kalite en-kötü-dil, no-train, bölgesel, stall)
python3 docs/vendor-eval/llm_eval_probe.py score docs/vendor-eval/samples/llm-cloud-A.json --out /tmp/llm-A.json

# 3) Çok sağlayıcılı karşılaştırma matrisi
python3 docs/vendor-eval/llm_eval_probe.py compare /tmp/llm-*.json --out /tmp/llm-compare.md
```
Çıkış kodu: tüm kapılar geçerse `0`, biri elerse `1`. Görev kalitesi dış girdidir (kalibre set / LLM-judge); credential yalnız ortam değişkeniyle, **repoya yazılmaz**.

### Vector DB eval (0.2.5)
```bash
# 1) Self-test (credential'sız): recall@k/leak/residency/percentile çekirdek doğrulama
python3 docs/vendor-eval/vector_db_eval_probe.py selftest

# 2) Bir aday sorgu test setini puanla + kapı (recall en-kötü sınıf, retrieval P95, izolasyon/ACL sızıntı, residency)
python3 docs/vendor-eval/vector_db_eval_probe.py score docs/vendor-eval/samples/vdb-pgvector.json --out /tmp/vdb-pgvector.json

# 3) Çok adaylı karşılaştırma matrisi (pgvector vs OpenSearch vs ...)
python3 docs/vendor-eval/vector_db_eval_probe.py compare /tmp/vdb-*.json --out /tmp/vdb-compare.md
```
Çıkış kodu: tüm kapılar geçerse `0`, biri elerse `1`. `relevant_ids` = exact-kNN ground-truth (dış girdi); managed dış DB credential'ı yalnız ortam değişkeniyle, **repoya yazılmaz**.

### Vendor karar birleştirme (0.2.6)
```bash
# 1) Self-test (credential'sız): kategori çıkarımı, verdict normalizasyonu, portföy kapısı
python3 docs/vendor-eval/vendor_decision_probe.py selftest

# 2) 0.2.x score/stats JSON'larını birleştir → karar matrisi + ADR-002 portföy kapısı
python3 docs/vendor-eval/vendor_decision_probe.py rollup /tmp/tel-*.json /tmp/stt-*.json \
    /tmp/tts-*.json /tmp/llm-*.json /tmp/vdb-*.json --out /tmp/decision-matrix.md

# 3) Alt-işleyen kayıt iskeleti (DPA Ek-A) üret
python3 docs/vendor-eval/vendor_decision_probe.py register /tmp/*.json --out /tmp/subprocessors.md
```
Çıkış kodu (`rollup`): her hot-path kategoride ≥2 farklı geçen aday (ADR-002 portföy kapısı) varsa `0`,
eksikse `1` (CI/0.4.4 gate). Bu hat **yeniden ölçmez**; 0.2.x probe çıktısını birleştirir. **Seçim yapmaz**
(vendor-neutral); bağlayıcı seçim 0.3.x PoC + DPA. Detay: `vendor-decision.md` / `contract-dpa-checklist.md`.
