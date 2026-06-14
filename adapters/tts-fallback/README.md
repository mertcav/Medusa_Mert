# adapters/tts-fallback — WBS 4.3.2 TTS fallback + ses karakteri tutarlılığı

Sağlayıcı Soyutlama Katmanı'nın **fallback ve degradation** dilimi (SAD §8.2/§8.3): TtsAdapter SPI
(SAD §8.1 / API §11.3) **arkasında** ortak fallback ANAHTARLAMA + **ses karakteri tutarlılığı** mantığı.
Birincil TTS hata/timeout (circuit-open) → ikincil TTS + in-flight sözün **kalan metni eşdeğer ses ile
yeniden sentezlenir** (çalınmış metin tekrar edilmez); her iki düşerse → deterministik akış (insan
aktarımı), **çağrı düşmez**. Ses karakteri çağrı boyu **tutarlı** kalır. Kaynak: FR-TTS-008/009,
BRD §19 (1)/(4), SAD §8.3, API §11.3.

## Dosyalar

| Dosya | Rol |
|-------|-----|
| `tts-fallback-spec.json` | Makine-okunur kaynak doğruluk: placement, SPI, gates (T1–T10), fallback zinciri, voice_consistency, error_taxonomy, residency, pii, invariants (T1–T11) |
| `tts-fallback.md` | Tasarım: mimari konum, HARD kapılar, routing kararı, resynth continuation, eşdeğer ses, kapsam ayrımı, izlenebilirlik |
| `tts_fallback_probe.py` | stdlib-only: `validate` / `simulate <sample>` (deterministik switcher) / `selftest` / `schema` |
| `config/tts-fallback-profiles.json` | İllüstratif 2 SPI-uyumlu sağlayıcı + 3 çalıştırma profili (primary+secondary+bölge+**voice_equivalence**); sır YOK |
| `samples/*.json` | failover-resynth / no-failover-clean / both-fail-deterministic / selective-auth-no-failover / bargein-during-fallback (geçer) + degraded (eler) |
| `tests/tts_fallback_behavior_test.py` | Davranış kapısı T1–T10 |
| `run_live_test.sh` | Statik + sample + (canlı SKIP/not) |

## Kapı durumu

- `validate`: **83/83** 🟢 (spec ↔ T1–T11 + config 2 sağlayıcı/3 profil + eşdeğer-ses haritası uyum + sır taraması)
- `selftest`: **94/94** 🟢 (happy + barge-in + ≥2 sağlayıcı + both-fail + selective + 17 degraded negatif kapı + 11 olay reddi + 28 validate negatif kapısı)
- `behavior` (T1–T10): **33/33** 🟢
- `samples`: 5 pass + degraded T3/T8 eler (7/9)

## Ses karakteri tutarlılığı (FR-TTS-009) — görev başlığının ikinci boyutu

İki katman: (a) **aynı sağlayıcıda** voiceId çağrı boyu sabit (mid-call drift yok; cache'ten sunulan statik
anonslar da aynı voiceId), (b) sağlayıcı **fallback'inde** ikincil, tenant logical voiceId'sine karşılık
gelen önceden tanımlı **eşdeğer fiziksel sesi** (`voice_equivalence` haritası) kullanır → karakter çağrı boyu
tutarlı. Eşdeğer ses tanımsız/yok sayılırsa karakter kırılır (T8 eler).

## İlkeler

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (olay-tetikli, sanal saat,
random YOK; gerçek TTS yok — sağlayıcı gecikme profili + akış/hata MODELİ). Canlı sistemde Go/Rust async
runtime (ADR-003) + gerçek TtsAdapter + 4.1.2 circuit breaker. Ham SES/metin/PII/sır repoya yazılmaz.
Kapsam ayrımı `tts-fallback.md §6`. → `reports/4.3.2-tts-fallback-voice-consistency-raporu.md`
