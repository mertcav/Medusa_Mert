# adapters/stt-fallback — WBS 4.3.1 STT fallback (hata/timeout → ikincil)

Sağlayıcı Soyutlama Katmanı'nın **fallback ve degradation** dilimi (SAD §8.2/§8.3): SttAdapter SPI
(SAD §8.1 / API §11.2) **arkasında** ortak fallback ANAHTARLAMA mantığı. Birincil STT hata/timeout
(circuit-open) → ikincil STT + in-flight söz audio replay; her iki düşerse → deterministik akış
(insan aktarımı), **çağrı düşmez**. Kaynak: FR-STT-008, BRD §19 (1)/(4), SAD §8.3, API §11.2.

## Dosyalar

| Dosya | Rol |
|-------|-----|
| `stt-fallback-spec.json` | Makine-okunur kaynak doğruluk: placement, SPI, gates (S1–S8), fallback zinciri, error_taxonomy, residency, pii, invariants (S1–S10) |
| `stt-fallback.md` | Tasarım: mimari konum, HARD kapılar, routing kararı, replay, kapsam ayrımı, izlenebilirlik |
| `stt_fallback_probe.py` | stdlib-only: `validate` / `simulate <sample>` (deterministik switcher) / `selftest` / `schema` |
| `config/stt-fallback-profiles.json` | İllüstratif 2 SPI-uyumlu sağlayıcı + 3 çalıştırma profili (primary+secondary+bölge); sır YOK |
| `samples/*.json` | failover-replay / no-failover-clean / both-fail-deterministic / selective-auth-no-failover (geçer) + degraded (eler) |
| `tests/stt_fallback_behavior_test.py` | Davranış kapısı T1–T8 |
| `run_live_test.sh` | Statik + sample + (canlı SKIP/not) |

## Kapı durumu

- `validate`: **68/68** 🟢 (spec ↔ S1–S10 + config 2 sağlayıcı/profil uyum + sır taraması)
- `selftest`: **69/69** 🟢 (happy + ≥2 sağlayıcı + both-fail + selective + 12 degraded negatif kapı + 10 olay reddi + 19 validate negatif kapısı)
- `behavior` (T1–T8): **22/22** 🟢
- `samples`: 4 pass + degraded S1/S2/S6/S7 eler (3/7)

## İlkeler

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (olay-tetikli, sanal saat,
random YOK; gerçek STT yok — sağlayıcı gecikme profili + akış/hata MODELİ). Canlı sistemde Go/Rust async
runtime (ADR-003) + gerçek SttAdapter + 4.1.2 circuit breaker. Ham AUDIO/transkript/PII/sır repoya
yazılmaz. Kapsam ayrımı `stt-fallback.md §6`. → `reports/4.3.1-stt-fallback-raporu.md`
