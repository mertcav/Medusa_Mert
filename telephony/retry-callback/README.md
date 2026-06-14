# telephony/retry-callback — Çağrı düşmesinde kontrollü retry/geri arama (WBS 2.1.8)

Çağrı düştüğünde/temas kurulamadığında **kontrollü retry veya geri arama** kararı üreten
sağlayıcı-nötr karar motoru (FR-TEL-009). 2.1.7 reason-codes'un `retryable` bayrağını +
`outbound_callback` start kodunu **tüketir**; FR-OUT-005 (maks. deneme), FR-OUT-003 (consent),
FR-TEL-013/014 (saat/DNC), FR-RES-014 (backpressure) kapılarını uygular. Çağrı yaşam-döngüsü
"sonra ne olacak" karar düzlemi (medya/numaralandırma/taksonomi DEĞİL).
`telephony/{managed-cpaas,byoc-sip,numbering,dtmf,reason-codes}` disipliniyle birebir:
vendor-neutral (ADR-002), credential-free, stdlib-only, deterministik (sanal saat + tohumlu jitter).

## Dosyalar
- `retry-callback-spec.json` — kaynak doğruluk: enums + `decision_contract` + `policy_model` +
  `eligibility.classes` (dropped/no_contact/capacity, 2.1.7'ye eşlenir) + `compliance_gates`
  (G1 DNC · G2 consent · G3 non-retryable · G4 max · G5 capacity) + residency/pii + invariant C1–C14.
- `retry-callback.md` — tasarım/gerekçe + karar akışı + kapsam ayrımı.
- `retry_callback_probe.py` — `validate` · `decide <sample>` · `simulate <sample>` · `selftest` · `schema`.
- `config/retry-policies.json` — ≥2 politika (campaign-default / transactional-callback /
  high-priority-reconnect); maks. deneme + backoff + jitter + arama saati; sır yok.
- `samples/decide-*.json` — karar senaryoları (drop/no-answer/max/dnc/consent/outside-hours/
  capacity/non-retryable geçer + 1 degraded eler) + `simulate-exhaustion.json` (tavan kanıtı).
- `tests/retry_callback_behavior_test.py` — karar mantığı kapısı (T1–T6).
- `run_live_test.sh` — statik + decide + simulate + behavior; canlı uç yoksa SKIP.

## Çalıştırma
```bash
python3 retry_callback_probe.py validate        # C1..C14 + 2.1.7 çapraz-tutarlılık → çıkış kodu
python3 retry_callback_probe.py selftest         # iyi/kötü spec kapı kanıtı
python3 retry_callback_probe.py decide samples/decide-drop-retry.json
python3 retry_callback_probe.py simulate samples/simulate-exhaustion.json
./run_live_test.sh                               # tüm kapı (credential-free)
```

## Kapsam dışı (bilinçli)
Scheduler/dialer altyapısı → F1 + 3.x · AMD/voicemail → 2.1.9 · consent/DNC/saat kayıt & zorlama
kaynağı → DB.md §5.4 + FR-TEL-013/014 · backpressure mekanizması → FR-RES-014 + 0.4.8 · neden
taksonomisi → 2.1.7 · numara → 2.1.5 · medya/SIP/RTP → 2.1.3/2.1.4 · canlı dialer → F1 + 0.4.7.
Burada yalnız **kontrollü karar + zamanlama hesabı + sınır/uyum kapıları**.
