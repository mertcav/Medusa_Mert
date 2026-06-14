# `telephony/managed-cpaas/` — Managed CPaaS entegrasyonu (Media Streams/WebSocket) (WBS 2.1.3)

Telefoni soyutlamasının (SAD §7.2) **M1 — Managed CPaaS (WS)** modunun fiziksel sözleşmesi: sağlayıcı
(Twilio Media Streams / Telnyx Media Streaming) medya-WS çerçevesinin orchestrator'ın gördüğü tek
sözleşmeye (API §12.1, `TelephonyAdapter` SPI managed modu) **normalize** edilmesi. `db/`+`cache/`+
`objstore/`+`eventstream/` disipliniyle aynı: **vendor-neutral (ADR-002)**, **credential-free**, statik
probe + deterministik davranış simülatörü + opsiyonel canlı kapı.

> **Kaynak doğruluk:** `cpaas-spec.json` (makine-okunur). Çelişkide o, üstünde SAD §7.2/§12.1, API §11.5/§12.1, BRD esastır.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `cpaas-spec.json` | **Kaynak doğruluk:** medya profili + transport + auth + bağlam bağlama + normalize sözleşmesi + ≥2 sağlayıcı eşlemesi + lifecycle + barge-in + DTMF + reconnect + hata taksonomisi + invariant I1–I14 |
| `managed-cpaas.md` | Tasarım: mimari konum, SPI bağlama, normalize sözleşmesi, güvenlik/bağlam, çerçeveleme, lifecycle/barge-in, dayanıklılık, residency/PII, izlenebilirlik |
| `cpaas_probe.py` | stdlib-only kapı: `validate` / `normalize <sample>` (deterministik medya-WS normalize sim.) / `selftest` / `schema` |
| `config/providers.json` | Sağlayıcı bağlantı profilleri (spec türevi; endpoint/secret yalnız `${ENV}`; fallback sırası) |
| `samples/inbound-happy-path.json` | Twilio inbound: connected→start→media→dtmf→stop + egress (FR-TST-008) |
| `samples/barge-in.json` | Telnyx barge-in: `clear` 45 ms ≤200 ms (ADR-002 simetri) |
| `samples/degraded.json` | Bilinçli ELENEN: media-before-start + 16kHz + eksik bağlam + bölge uyumsuz |
| `tests/framing_behavior_test.py` | μ-law/8kHz/20ms çerçeveleme aritmetiği + base64 round-trip (T1–T5) |
| `run_live_test.sh` | Statik kapı + sample normalize; `${CPAAS_MEDIA_WS_URL}` varsa canlı not, yoksa SKIP |

## Çalıştırma

```bash
python3 telephony/managed-cpaas/cpaas_probe.py validate                                   # 56/56 PASS (çıkış 0)
python3 telephony/managed-cpaas/cpaas_probe.py selftest                                    # 15/15 PASS
python3 telephony/managed-cpaas/cpaas_probe.py normalize telephony/managed-cpaas/samples/inbound-happy-path.json
python3 telephony/managed-cpaas/tests/framing_behavior_test.py                             # 5/5 PASS
bash    telephony/managed-cpaas/run_live_test.sh                                           # canlı (varsa) / SKIP
```

## Özet kararlar

- **Normalize kalbi:** sağlayıcı medya-WS olayları (`start/media/dtmf/stop`) tek sözleşmeye indirgenir;
  egress `play_audio/mark/barge_in_clear`. Orchestrator yalnız SPI'ye bağlı (ADR-001); yeni sağlayıcı =
  bir eşleme tablosu + profil (ADR-002, ≥2 sağlayıcı + fallback).
- **Güvenlik:** WSS/TLS zorunlu (I1) + medya öncesi imza doğrulama (I2) + tenant/correlation/call bağlam
  bağlama her olaya (I3, SAD §13.3).
- **Medya:** 8 kHz μ-law 20 ms/50 fps, no-transcode (I4, FR-RES-008).
- **Barge-in:** `clear` flush ile agent sesi ≤200 ms kesilir (I5, FR-RTC-002, NFR 10.1); hibrit topoloji
  (edge barge-in, ADR-005/ADR-009).
- **Dayanıklılık:** hata→ortak `ErrorTaxonomy` (API §11.6) + fallback + sonlu reconnect penceresi (I8/I13).
- **Residency/PII:** sağlayıcı bölge home-region pin (I11, NFR 10.7); ham ses/PII spec/config'te yok (I14).

**Sır/credential repoya yazılmadı** — endpoint/token/secret yalnız `${ENV}`. Vendor-neutral (ADR-002).
Canlı medya RTT/jitter ölçümü tek ölçüm hattına (`vendor-eval/media_latency_probe.py`, 0.2.1) devredilir.
