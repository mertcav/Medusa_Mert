# adapters/llm-fallback — WBS 4.3.3 LLM fallback (fallback model / deterministic flow)

Sağlayıcı Soyutlama Katmanı'nın **fallback ve degradation** dilimi (SAD §8.2/§8.3 + §9.1 [4]): LlmAdapter SPI
(SAD §8.1 / API §11.4) **arkasında** ortak fallback ANAHTARLAMA mantığı. Aktif (birincil) LLM modeli
hata/timeout (circuit-open) → **fallback modele** geçiş + tur isteğinin (messages/tools/system prompt)
**yeniden sunumu**; her iki model düşerse → deterministik akış (kural-tabanlı / insan aktarımı), **çağrı
düşmez**. LLM'e özgü iki güvenlik: **mid-stream** (ilk token sonrası çift konuşma yok) + **tool idempotency**
(yan etkili tool çift yürütme yok). Kaynak: FR-LLM-010, BRD §19 (1)/(4), SAD §8.3/§9.1, API §11.4.

## Dosyalar

| Dosya | Rol |
|-------|-----|
| `llm-fallback-spec.json` | Makine-okunur kaynak doğruluk: placement, SPI, gates (L1–L8), fallback zinciri, error_taxonomy, residency, pii, invariants (L1–L10) |
| `llm-fallback.md` | Tasarım: mimari konum, HARD kapılar, routing kararı, context resubmit, mid-stream/idempotency güvenliği, fallback≠routing, kapsam ayrımı, izlenebilirlik |
| `llm_fallback_probe.py` | stdlib-only: `validate` / `simulate <sample>` (deterministik switcher) / `selftest` / `schema` |
| `config/llm-fallback-profiles.json` | İllüstratif 2 SPI-uyumlu sağlayıcı + 1 elenen + 3 çalıştırma profili (primary+fallback+bölge+`deterministic_flow_id`); sır YOK |
| `samples/*.json` | failover-resubmit / no-failover-clean / both-fail-deterministic / midstream-tool-safe-degrade / selective-content-filter (geçer) + degraded (eler) |
| `tests/llm_fallback_behavior_test.py` | Davranış kapısı T1–T10 |
| `run_live_test.sh` | Statik + sample + (canlı SKIP/not) |

## Kapı durumu

- `validate`: **77/77** 🟢 (spec ↔ L1–L10 + config 2 sağlayıcı/3 profil + sır taraması)
- `selftest`: **87/87** 🟢 (happy + mid-stream/tool güvenliği + ≥2 sağlayıcı + both-fail + selective CONTENT_FILTERED/AUTH + QUOTA failover + 14 degraded negatif kapı + 11 olay reddi + 25 validate negatif kapısı)
- `behavior` (T1–T10): **28/28** 🟢
- `samples`: 5 pass + degraded L3/L4/L5 eler

## LLM'e özgü iki güvenlik (görev başlığının ötesi)

- **Mid-stream güvenliği (L3):** ilk token gittikten sonra birincil düşerse fallback'e **sessiz yeniden istek
  yok** → güvenli degrade (`double_speak=0`); ilk-token öncesi temiz failover.
- **Tool idempotency (L4):** yan etkili tool zaten yürütülmüşse failover'da **yeniden yürütülmez**
  (`double_tool_exec=0`; FR-TOOL-009).

## Fallback ≠ Routing

Model **routing/tiering** (5.1-5.3, SAD §9): en ucuz yeterli modeli **seçer**. **Fallback** (4.3.3): seçilen
model **düştüğünde** kurtarır. Bu motor model **seçmez**.

## İlkeler

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (olay-tetikli, sanal saat,
random YOK; gerçek LLM yok — sağlayıcı gecikme profili + akış/hata MODELİ). Canlı sistemde Go/Rust async
runtime (ADR-003) + gerçek LlmAdapter + 4.1.2 circuit breaker. Ham PROMPT/çıktı/token/PII/sır repoya
yazılmaz. Kapsam ayrımı `llm-fallback.md §6`. → `reports/4.3.3-llm-fallback-raporu.md`
