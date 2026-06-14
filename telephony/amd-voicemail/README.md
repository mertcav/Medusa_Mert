# telephony/amd-voicemail — Answering machine detection + voicemail bırakma (WBS 2.1.9)

Çağrı karşılandığında karşı tarafı **insan/makine/belirsiz** olarak deterministik sınıflandıran (AMD,
FR-TEL-010) ve makine ise **bip sonrası kontrollü voicemail** bırakan (FR-TEL-011) sağlayıcı-nötr
algılama+aksiyon motoru. 2.1.7 reason-codes'un `voicemail_machine_detected` / `voicemail_left`
kanonik kodlarını **üretir** (2.1.8 retry tüketir); consent (FR-OUT-003) / DNC (FR-TEL-014) / AI ifşası
(BRD §14.2) kapılarını uygular. Çağrı karşılandıktan sonra "kim/ne cevapladı + ne yapmalı" düzlemi
(medya kodek/RTP DEĞİL). `telephony/{managed-cpaas,byoc-sip,numbering,dtmf,reason-codes,retry-callback}`
disipliniyle birebir: vendor-neutral (ADR-002), credential-free, stdlib-only, deterministik.

## Dosyalar
- `amd-voicemail-spec.json` — kaynak doğruluk: enums + `detection_contract` + `drop_contract` +
  `amd_model` (feature_weights toplam 1.0 + eşikler + unknown_fallback) + `voicemail_model` +
  `compliance_gates` (G1 policy · G2 consent · G3 DNC · G4 ifşa · G5 bip) + `reason_code_map` (2.1.7) +
  `accuracy_gate` (SR-TEL-010 T) + residency/pii + invariant A1–A14.
- `amd-voicemail.md` — tasarım/gerekçe + sınıflandırıcı + doğruluk kapısı + bırakma + kapsam ayrımı.
- `amd_voicemail_probe.py` — `validate` · `classify <s>` · `drop <s>` · `accuracy <ds>` · `selftest` · `schema`.
- `config/amd-profiles.json` — ≥2 profil (campaign-voicemail / detect-only / high-confidence-voicemail);
  min_confidence + eşikler + bip/mesaj sınırları + ifşa; sır yok.
- `samples/classify-*.json` — human / machine-cpaas / machine-heuristic / unknown.
  `samples/drop-*.json` — voicemail-left / no-beep / policy-off / consent (+ degraded eler).
  `samples/accuracy-*.json` — labeled-set (geçer) + degraded (false_machine/accuracy kapısı eler).
- `tests/amd_voicemail_behavior_test.py` — algılama/bırakma mantığı kapısı (T1–T6).
- `run_live_test.sh` — validate + selftest + classify + drop + accuracy + behavior; canlı uç yoksa SKIP.

## Çalıştırma
```bash
python3 amd_voicemail_probe.py validate      # A1..A14 + 2.1.7 çapraz-tutarlılık → çıkış kodu
python3 amd_voicemail_probe.py selftest      # iyi/kötü spec kapı kanıtı
python3 amd_voicemail_probe.py classify samples/classify-machine-heuristic.json
python3 amd_voicemail_probe.py drop samples/drop-voicemail-left.json
python3 amd_voicemail_probe.py accuracy samples/accuracy-labeled-set.json   # SR-TEL-010 (T)
./run_live_test.sh                            # tüm kapı (credential-free)
```

## Kapsam dışı (bilinçli)
AMD DSP/sinyal işleme → F1 edge (ADR-009) · voicemail medya egress/TTS → 0.2.3 + 2.2.x · disposition
(FR-OUT-008) → 10.1.4/10.1.5 · consent/DNC kayıt & zorlama → DB.md §5.4 + FR-TEL-013/014 · retry
zamanlaması → 2.1.8 · neden taksonomisi → 2.1.7 · numara → 2.1.5 · medya/SIP/RTP → 2.1.3/2.1.4 ·
canlı AMD doğruluğu + bırakma → F1 gerçek CPaaS AMD + medya egress + örneklemli QA. Burada yalnız
**deterministik sınıflandırma + doğruluk kapısı + kontrollü bırakma kararı + uyum/bip garantileri**.
