# tools/integration-gw — Timeout / Retry / Circuit Breaker (WBS 7.1.4)

Tool Yürütme Hattının (SAD §11.1) **adım [5]** dayanıklılık motoru: per-attempt **timeout**, sınırlı
**retry** (exponential backoff + tohumlu jitter), endpoint-başına **circuit breaker** (CLOSED/OPEN/HALF_OPEN).
**İz:** FR-TOOL-003 (Must) · SR-TOOL-003 · TC-TOOL-003 · SAD §11.1/§11.2/§8.3 · ADR-001/002/003.

> İnvariant (SR-TOOL-003): *"Bağımlılık hatasında devre açılır; kontrolsüz retry yok."*
> `tools/` workstream'inin ilk modülü (7.x Tool Yürütme). Vendor-neutral, credential-free, stdlib-only,
> deterministik (seed'li). Üst bağlam: kök `CLAUDE.md` + `docs/SAD.md §11`.

## Dosyalar
| Dosya | Rol |
|-------|-----|
| `integration-gw-spec.json` | Makine-okunur **kaynak doğruluk** (trace, SPI, fault taksonomisi, R1–R12, audit) |
| `integration-gw.md` | Tasarım notu (timeout/retry/breaker state machine, izlenebilirlik) |
| `integration_gw_probe.py` | Referans probe: `validate` / `run <sample>` / `selftest` / `schema` |
| `config/integration-gw-profiles.json` | ResiliencePolicy preset'leri (rest-default / soap-conservative / flaky-tolerant / write-strict) |
| `samples/*.json` | Sentetik senaryolar (happy / retry / timeout / non-retryable / write-idempotency / circuit-trip / recovery / endpoint-isolation / degraded) |
| `tests/integration_gw_behavior_test.py` | Kara-kutu davranış testi |
| `run_live_test.sh` | Statik+sample kapısı; canlı transport yalnız `${TOOL_GW_ENDPOINT}` ile not düşülür |

## Çalıştırma
```bash
python3 integration_gw_probe.py validate          # statik kapı → çıkış kodu
python3 integration_gw_probe.py selftest          # 28 gömülü kontrol
python3 integration_gw_probe.py run samples/gw-circuit-trip.json
python3 integration_gw_probe.py schema            # sözleşmeleri yazdır
python3 tests/integration_gw_behavior_test.py     # davranış testi
bash run_live_test.sh                             # tüm kapı (credential-free)
```

## Kapılar (R1–R12)
`R1` timeout deadline kesimi · `R2` bounded retry (kontrolsüz retry yok) · `R3` exponential backoff +
sınırlı jitter · `R4` terminal fault retry edilmez · `R5` write retry yalnız idempotency_key ile
(FR-TOOL-009) · `R6` breaker bağımlılık hatasında OPEN · `R7` OPEN fail-fast (upstream'e değmez) ·
`R8` HALF_OPEN probe → CLOSED/OPEN · `R9` endpoint izolasyonu · `R10` determinizm · `R11` audit no-log ·
`R12` yapısal fault taksonomisi.

**Durum:** selftest 28/28 🟢 · validate 🟢 · behavior 13/13 🟢 · 9 sample 🟢.

## Sınırlar (kapsam dışı — sahip)
schema doğrulama → 7.1.1 · authz → 7.1.2 · idempotency key store → 7.1.3 (bu motor key **varlığını**
tüketir) · müşteriye hata metni → 7.1.5 · correlation_id audit → 7.1.6 · allowlist → FR-TOOL-012 ·
async workflow → FR-TOOL-011. Gerçek HTTP/SOAP/GraphQL transport + connection pool (FR-RES-006) canlıda
aynı SPI arkasına; sır/credential repoya **yazılmaz** (yalnız `${ENV}`).
