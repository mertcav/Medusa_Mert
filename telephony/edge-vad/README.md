# `telephony/edge-vad/` — WBS 2.2.3

Edge VAD / endpointing (dinamik) — Real-time **Media Gateway** edge katmanı (SAD §6/§7, L2).
Kaynak doğruluk: **`edge-vad-spec.json`**. Tasarım: **`edge-vad.md`**. Vendor-neutral (ADR-002),
credential-free, stdlib-only — `rtp-jitter/` (2.2.1) + `codec/` (2.2.2) disipliniyle aynı.

2.2.1 jitter buffer'ın verdiği düzgün 20ms/50fps kadansı tüketir → **VAD** ile her çerçeveyi
konuşma/sessizlik sınıflar (adaptif gürültü tabanı + histerezis + hangover) → **dinamik endpointing**
ile söz sonunu bağlama göre değişen onay-sessizliğiyle tespit eder (tereddütte bekler, tamamlanmış
turda hızlı keser) → **barge-in** onset'ini ≤200ms algılar (echo guard'lı) → **ölü havayı** STT/LLM'e
göndermeyerek gereksiz çağrıları azaltır. **EDGE'de** (ADR-005 Kabul; ADR-009 hibrit).

## İçerik
| Dosya | Ne |
|-------|----|
| `edge-vad-spec.json` | Kaynak doğruluk: VAD + dinamik endpointer + barge-in + dead-air sözleşmesi, kapılar, metrikler, invariant V1–V14 |
| `edge-vad.md` | Tasarım dokümanı (VAD, dinamik onay-sessizliği, hesitation/completeness, barge-in echo guard, dead-air, gerilim) |
| `edge_vad_probe.py` | stdlib-only kapı: `validate` / `simulate` / `selftest` / `schema` + deterministik VAD/endpoint/barge-in simülatörü |
| `config/vad-profiles.json` | İllüstratif VAD/endpoint profilleri (managed-WS / BYOC-RTP / low-latency-quiet; sır yok) |
| `samples/*.json` | Senaryolar (happy/hesitation/completeness/barge-in/echo-guard/dead-air pass + degraded fail) |
| `tests/edge_vad_behavior_test.py` | Davranış kapısı (T1–T7) |
| `run_live_test.sh` | Statik kapı + (varsa) canlı endpoint notu; yoksa SKIP |

## Kullanım
```
python3 edge_vad_probe.py validate                                       # spec+config kapısı (V1–V14)
python3 edge_vad_probe.py simulate samples/edge-vad-happy-path.json      # iki söz, doğru endpoint (geçer)
python3 edge_vad_probe.py simulate samples/edge-vad-hesitation-held.json # tereddüt köprülenir (geçer)
python3 edge_vad_probe.py simulate samples/edge-vad-barge-in.json        # barge-in ≤200ms (geçer)
python3 edge_vad_probe.py simulate samples/edge-vad-degraded.json        # aşırı gürültü (eler)
python3 edge_vad_probe.py selftest                                       # iyi/kötü kanıt
bash run_live_test.sh                                                    # uçtan uca statik kapı
```

## Kapılar (HARD)
- **V5** gerçek söz-sonu → endpoint gecikmesi **P95 ≤ 250ms** (SAD §20 endpointing bandı ~150–250ms; yeşil ≤200ms).
- **V6** within-utterance (hesitation) duraklamada **erken kesme oranı ≤ 0.05** (dinamik T_confirm köprüler).
- **V7** gerçek söz sonu **kaçırılmaz/geç kesilmez** (missed ≤ 0.0).
- **V8** barge-in onset → algılama gecikmesi **P95 ≤ 200ms** (ADR-005/NFR 10.1; yeşil ≤100ms).
- **V9** echo/gürültüden **yanlış barge-in yok** (≤ 0.0).
- **V10** ölü hava (sessizlik) **STT'ye gönderilmez** (FR-RES-009/FR-RTC-013).

## Durum
**validate 56/56 · selftest 40/40 · edge_vad_behavior 17/17** 🟢. 7 sample beklendiği gibi
(6 pass + `edge-vad-degraded` bilinçli fail). **Bulgu — dinamik endpointing gerekliliği:** statik bir
onay-sessizliği eşiği erken/geç kesme gerilimini çözemez; dinamik T_confirm kısa/kesik sözde uzayıp
tereddüt duraklamasını köprüler (V6), uzun akıcı turda kısalıp gecikmeyi green'e çeker (V5). Echo
enerjisi noise floor'u yukarı çekip barge-in'i kaçırma riski **agent playout sırasında taban
dondurularak** çözüldü (bugfix). Bağlar: kadans → 2.2.1 jitter buffer; codec/8kHz → 2.2.2;
echo/AEC (tam) → 2.2.4; downstream → streaming STT 2.2.5; barge-in TTS kesme/flush → 2.2.7 + 2.2.1;
metrikler → observability 0.4.7 (`silence_duration_ms`/`barge_in_total`).
İz: FR-RTC-004/013, FR-RES-009 → SR-RTC-004/013, SR-RES-009 → TC-RTC-004/013; ADR-005. Rapor:
`reports/2.2.3-edge-vad-endpointing-raporu.md`.
