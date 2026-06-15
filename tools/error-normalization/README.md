# tools/error-normalization — WBS 7.1.5

**Hata normalizasyonu (müşteriye teknik detay yok)** — `F1` · `Must` · →FR-TOOL-008
SAD §11.1 adım [6] · API §4.3/§5/§11.6. `tools/` workstream'inin ikinci modülü (7.1.4'ten sonra).

Tool Yürütme Hattının sunum aşaması: 7.1.4 Integration GW'nin ürettiği yapısal `fault_class`'ı
(veya bir adapter API §11.6 `ErrorTaxonomy` hatasını) **iki disjonkt yüzeye** böler:

- **customer** — müşteriye/arayana güvenli, **teknik-detaysız** mesaj (voice: doğal konuşma;
  api: RFC 9457 `application/problem+json`).
- **audit** — ham teknik detay (provider kodu, stack, endpoint, internal mesaj) — **müşteriye gitmez**.

Çekirdek garanti (SR-TOOL-008): *müşteriye dönen mesajda stack/teknik detay yok* — bağımsız
**sızıntı tarayıcısıyla** doğrulanır (N1/N10).

## Dosyalar
| Dosya | Rol |
|-------|-----|
| `error-normalization-spec.json` | Kaynak doğruluk: kategoriler, fault→kategori eşleme, sızıntı taksonomisi, N1–N12 |
| `config/error-catalog.json` | Müşteri mesaj kataloğu (tr-TR/en-US, voice/title/detail) + tarayıcı denylist'leri |
| `error_normalization_probe.py` | stdlib-only: `validate` / `normalize <sample>` / `selftest` / `schema` |
| `samples/*.json` | Sentetik senaryolar (FR-TST-008); `norm-degraded` kasıtlı 🔴 (tarayıcı kanıtı) |
| `tests/leak_behavior_test.py` | Sızıntı tarayıcısı + müşteri/audit ayrımı (T1–T6) |
| `run_live_test.sh` | validate + selftest + behavior + samples (saf eşleme → canlı bağımlılık gerekmez) |
| `error-normalization.md` | Tasarım |

## Hızlı başlangıç
```bash
python3 error_normalization_probe.py validate
python3 error_normalization_probe.py selftest
python3 error_normalization_probe.py normalize samples/norm-nasty-internal-redacted.json
python3 error_normalization_probe.py schema
./run_live_test.sh
```

## Durum
validate 🟢 · selftest 25/25 🟢 · behavior 38/38 🟢 · 7 sample 🟢 + degraded 🔴 (beklenen eleme).

## Kapsam ayrımı
fault_class üretimi → 7.1.4 · output schema → 7.1.1 · authz → 7.1.2 · idempotency → 7.1.3 ·
correlation_id audit/trace + audit deposunda PII redaction → 7.1.6 · insan aktarımı → FR-HND
(yalnız `suggest_handoff` önerilir). Vendor-neutral (ADR-002); sır/credential repoya yazılmaz.
