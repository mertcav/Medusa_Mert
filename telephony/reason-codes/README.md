# telephony/reason-codes — Çağrı başlangıç/bitiş neden kodları (WBS 2.1.7)

Standart, sağlayıcı-nötr çağrı **neden taksonomisi** (FR-TEL-012) + sağlayıcı/protokol
sinyali → kanonik kod **sınıflama** sözleşmesi. Çağrı yaşam-döngüsü olay/analitik düzlemi
(medya/numaralandırma DEĞİL). `telephony/{managed-cpaas,byoc-sip,numbering,dtmf}` disipliniyle
birebir: vendor-neutral (ADR-002), credential-free, stdlib-only.

## Dosyalar
- `reason-codes-spec.json` — kaynak doğruluk: enums + `start_reasons` + `end_reasons` (tam nitelik
  kümeli ~25 kod) + `signal_map` (sip/q850/cpaas/internal) + residency/pii + invariant R1–R13.
- `reason-codes.md` — tasarım/gerekçe + kapsam ayrımı.
- `reason_codes_probe.py` — `validate` · `classify <sample>` · `lookup <code>` · `selftest` · `schema`.
- `config/provider-reason-map.json` — ≥2 sağlayıcı (Twilio/Telnyx M1) + ham SIP (M2) örtüşmeleri; sır yok.
- `samples/classify-*.json` — sınıflama senaryoları (5 geçer + transfer/voicemail/abandoned + 1 degraded eler).
- `tests/reason_codes_behavior_test.py` — taksonomi mantığı kapısı (T1–T6).
- `run_live_test.sh` — statik + sample + behavior; canlı uç yoksa SKIP.

## Çalıştırma
```bash
python3 reason_codes_probe.py validate      # R1..R13 + config → çıkış kodu
python3 reason_codes_probe.py selftest       # iyi/kötü spec kapı kanıtı
python3 reason_codes_probe.py classify samples/classify-busy-sip.json
python3 reason_codes_probe.py lookup transfer_to_human
./run_live_test.sh                           # tüm kapı (credential-free)
```

## Kapsam dışı (bilinçli)
Retry zamanlaması → 2.1.8 · AMD/voicemail akışı → 2.1.9 · consent/DNC/saat zorlaması →
FR-TEL-013/014 · medya/SIP/RTP → 2.1.3/2.1.4 · DTMF → 2.1.6 · faturalandırma motoru → FR-BIL ·
canlı event yayını → F1 + 0.4.7. Burada yalnız **kanonik kod + sınıflama + bayraklar**.
