# governance/voice-consent — WBS 4.2.6

Ses klonlama **izin (consent)** + **kullanım kaydı (usage record)** yönetişim kapısı — **onaylı sesler**
(FR-TTS-006) + ses sahibinin açık izni + kullanım kaydı (FR-TTS-007). Sağlayıcı-nötr (ADR-002),
credential-free, stdlib-only, deterministik. TtsAdapter (4.2.3) `VoiceProfile.clonedVoiceConsentRef`'i
synthesize() öncesi bu deftere çözer; karar `ALLOW` değilse ses üretilmez (ADR-001).

## Dosyalar
- `voice-consent-spec.json` — makine-okunur kaynak doğruluk (placement, SPI, kapılar P1–P8, error
  taxonomy, residency, pii, invariant V1–V12).
- `voice-consent.md` — tasarım: mimari konum, SPI yüzeyi, HARD kapılar, WORM/PII/residency, tehdit izi,
  kapsam ayrımı, izlenebilirlik.
- `voice_consent_probe.py` — `validate` | `simulate <sample>` | `selftest` | `schema`. Deterministik
  karar motoru (yaşam döngüsü + `use` → ALLOW/DENY + usage record + audit → kapılar → çıkış kodu).
- `config/voice-consent-profiles.json` — çalıştırma profilleri (pilot / regulated-tr / enterprise-eu);
  residency + retention + maker-checker/tenant-isolation/audit. Sır yok (`${ENV}`).
- `samples/` — `happy-path` (onaylı klon + izin + kullanım kaydı), `custom-approved` (izin gerektirmez),
  `expiry-revoke` (süre/iptal zorlama), `scope-tenant` (kapsam + izolasyon), `degraded` (bilinçli bozuk,
  P1–P8 eler).
- `tests/voice_consent_behavior_test.py` — T1–T8 davranış kapısı.
- `run_live_test.sh` — statik + sample + (varsa `${VOICE_CONSENT_EVIDENCE_STORE_URL}`) canlı not.

## Koşum
```bash
python3 voice_consent_probe.py validate      # statik kapı
python3 voice_consent_probe.py selftest      # iyi/kötü kanıt
python3 tests/voice_consent_behavior_test.py # T1–T8
bash run_live_test.sh
```

## Durum
`validate` 70/70 🟢 · `selftest` 52/52 🟢 · `behavior` 22/22 🟢 · 5 sample beklendiği gibi (4 pass +
degraded P3–P8 eler). Vendor-neutral; ham ses/voiceprint/biyometrik/PII repoya yazılmadı.

Kapsam ayrımı: gerçek sentez → 4.2.3 · eşdeğer-ses → 4.3.2 · ses biyometrisi → FR-AUTH-006/007 ·
politika motoru → 3.3.3 · audit_log şeması → 1.1.4 · retention → 1.2.3 · sağlayıcı seçimi → 0.2.6/0.3.x.
