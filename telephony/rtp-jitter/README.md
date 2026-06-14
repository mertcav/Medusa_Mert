# `telephony/rtp-jitter/` — WBS 2.2.1

RTP/medya sonlandırma + jitter buffer — Real-time **Media Gateway** ingress medya yolu (SAD §6/§7, L2).
Kaynak doğruluk: **`rtp-jitter-spec.json`**. Tasarım: **`rtp-jitter.md`**. Vendor-neutral (ADR-002),
credential-free, stdlib-only — `managed-cpaas/` (2.1.3) + `byoc-sip/` (2.1.4) + `dtmf/` (2.1.6)
disipliniyle aynı.

RTP paketlerini sonlandırır → sıra/zaman damgasına göre yeniden sıralar (reorder) → **adaptif jitter
buffer** ile ağ jitter'ını sönümler → kayıp/geç paketleri tespit edip concealment (PLC) uygular →
downstream'e (streaming STT 2.2.5) **düzgün 20ms/50fps kadans** verir.

## İçerik
| Dosya | Ne |
|-------|----|
| `rtp-jitter-spec.json` | Kaynak doğruluk: RTP sonlandırma + jitter buffer sözleşmesi, kapılar, metrikler, invariant J1–J14 |
| `rtp-jitter.md` | Tasarım dokümanı (sonlandırma, adaptif derinlik, reorder, concealment, kadans, loss↔latency gerilimi) |
| `rtp_jitter_probe.py` | stdlib-only kapı: `validate` / `simulate` / `selftest` / `schema` + deterministik jitter buffer simülatörü |
| `config/jitter-profiles.json` | İllüstratif jitter profilleri (managed-WS / BYOC-RTP / fixed; sır yok) |
| `samples/*.json` | Jitter buffer senaryoları (happy/adaptive/reorder/loss-concealed pass + degraded fail) |
| `tests/jitter_behavior_test.py` | Jitter buffer davranış kapısı (T1–T6) |
| `run_live_test.sh` | Statik kapı + (varsa) canlı endpoint notu; yoksa SKIP |

## Kullanım
```
python3 rtp_jitter_probe.py validate                                  # spec+config kapısı (J1–J14)
python3 rtp_jitter_probe.py simulate samples/jitter-happy-path.json   # temiz akış (geçer)
python3 rtp_jitter_probe.py simulate samples/jitter-reorder-absorbed.json  # out-of-order absorbe
python3 rtp_jitter_probe.py simulate samples/jitter-loss-concealed.json    # %4 kayıp → PLC (geçer)
python3 rtp_jitter_probe.py simulate samples/jitter-degraded.json     # aşırı kayıp+jitter (eler)
python3 rtp_jitter_probe.py selftest                                  # iyi/kötü kanıt
bash run_live_test.sh                                                 # uçtan uca statik kapı
```

## Kapılar (HARD)
- **J3** eklenen playout gecikmesi **P95 ≤ 80ms** (SAD §20 ~50–100ms medya bütçesinin jitter-buffer payı; yeşil ≤50ms).
- **J5** concealment (kayıp+geç gizleme) oranı **≤ 0.05**; aşılırsa hat-kalitesi degrade sinyali (FR-RTC-005).
- **J6** downstream kadansı **sürekli** (her slot bir çerçeve — gerçek veya concealed; stream-first).
- **J1** pencere içi **reorder absorbe** edilir.

## Durum
**validate 52/52 · selftest 41/41 · jitter_behavior 20/20** 🟢. 5 sample beklendiği gibi
(4 pass + `jitter-degraded` bilinçli fail). **Bulgu:** eklenen gecikme P95 ≈ nominal buffer derinliği
→ buffer'ın J2'de izin verilen 120ms'e büyümesi loss'u önler ama J3 latency bütçesini aşar
(**loss↔latency gerilimi**); degraded sample bunu gösterir (derinlik 120ms'e clamp + concealment %23).
Bağlar: sonlandırma → 2.1.3/2.1.4 taşıma; codec/8kHz → 2.2.2; VAD/endpointing → 2.2.3; barge-in flush → 2.2.7;
downstream → streaming STT 2.2.5; metrikler → observability 0.4.7 (`voice_jitter_ms`/`voice_packet_loss_ratio`).
İz: FR-RTC-001 → SR-RTC-001 → TC-RTC-001. Rapor: `reports/2.2.1-rtp-media-termination-jitter-buffer-raporu.md`.
