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
| `samples/*.json` | İllüstratif profiller: telefoni gecikme (`managed-*`/`raw-*`) + STT test setleri (`stt-*`); PoC'ta gerçek ölçümle değişir | 0.2.1/0.2.2 |

> Sıradaki: `0.2.3` TTS, `0.2.4` LLM, `0.2.5` Vector DB eval → `0.2.6` karar raporu.

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
