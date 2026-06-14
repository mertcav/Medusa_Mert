# `telephony/numbering/` — WBS 2.1.5

E.164 normalizasyonu + Caller ID & numara havuzu yönetimi (numaralandırma düzlemi).
Kaynak doğruluk: **`numbering-spec.json`**. Tasarım: **`numbering.md`**. Vendor-neutral (ADR-002),
credential-free, stdlib-only — `managed-cpaas/` (2.1.3) + `byoc-sip/` (2.1.4) disipliniyle aynı.

## İçerik
| Dosya | Ne |
|-------|----|
| `numbering-spec.json` | Kaynak doğruluk: E.164 sözleşmesi, ülke metadata, havuz modeli, Caller ID politikası, invariant N1–N11 |
| `numbering.md` | Tasarım dokümanı (mimari konum, normalize çekirdeği, anti-spoof, residency/PII) |
| `numbering_probe.py` | stdlib-only kapı: `validate` / `normalize` / `select` / `resolve` / `selftest` / `schema` |
| `config/number-pool.json` | İllüstratif numara havuzu (ayrılmış aralıklar; sır yok) |
| `samples/*.json` | normalize + Caller ID seçim senaryoları (pass/fail) |
| `tests/e164_behavior_test.py` | E.164/Caller ID davranış kapısı (T1–T6) |
| `run_live_test.sh` | Statik kapı + (varsa) canlı endpoint notu; yoksa SKIP |

## Kullanım
```
python3 numbering_probe.py validate                                  # spec+config kapısı
python3 numbering_probe.py normalize samples/normalize-valid.json    # E.164 normalize (FR-TEL-004)
python3 numbering_probe.py select    samples/caller-id-local-presence.json  # Caller ID (FR-TEL-005)
python3 numbering_probe.py resolve   "+908500000123"                 # inbound DID → tenant+agent
python3 numbering_probe.py selftest                                  # iyi/kötü kanıt
bash run_live_test.sh                                                # uçtan uca statik kapı
```

## Durum
**validate 45/45 · selftest 32/32 · e164_behavior 12/12** 🟢. 5 sample beklendiği gibi.
Bağlar: inbound → 2.1.3/2.1.4 `context_binding.did_to_tenant_map`; outbound → API §11.5
`DialRequest.callerIdPool`; depo → DB §14 `phone_number`. Rapor: `reports/2.1.5-e164-caller-id-numara-havuzu-raporu.md`.
