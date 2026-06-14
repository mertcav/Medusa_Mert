# `telephony/dtmf/` — WBS 2.1.6

DTMF algılama/üretme (RFC 2833 / SIP INFO) — telefoni **DTMF olay düzlemi**.
Kaynak doğruluk: **`dtmf-spec.json`**. Tasarım: **`dtmf.md`**. Vendor-neutral (ADR-002),
credential-free, stdlib-only — `managed-cpaas/` (2.1.3) + `byoc-sip/` (2.1.4) + `numbering/` (2.1.5)
disipliniyle aynı.

## İçerik
| Dosya | Ne |
|-------|----|
| `dtmf-spec.json` | Kaynak doğruluk: DTMF sözleşmesi (algılama/üretme/maskeleme), kod eşlemesi, invariant D1–D12 |
| `dtmf.md` | Tasarım dokümanı (out-of-band ilkesi, RFC 2833 debounce, SIP INFO, PCI maskeleme, barge-in) |
| `dtmf_probe.py` | stdlib-only kapı: `validate` / `detect` / `generate` / `selftest` / `schema` |
| `config/dtmf-modes.json` | İllüstratif DTMF mod profilleri (M1/M2, rfc2833/sip_info; sır yok) |
| `samples/*.json` | Algılama + üretme senaryoları (pass/fail) |
| `tests/dtmf_behavior_test.py` | DTMF davranış kapısı (T1–T6) |
| `run_live_test.sh` | Statik kapı + (varsa) canlı endpoint notu; yoksa SKIP |

## Kullanım
```
python3 dtmf_probe.py validate                                  # spec+config kapısı (D1–D12)
python3 dtmf_probe.py detect   samples/detect-rfc2833-happy.json # RFC 2833 algılama (debounce)
python3 dtmf_probe.py detect   samples/detect-sip-info.json      # SIP INFO algılama
python3 dtmf_probe.py detect   samples/detect-pci-masked.json    # PCI maskeleme (BRD §8.5)
python3 dtmf_probe.py generate samples/generate-rfc2833.json     # sendDtmf üretme (API §11.5)
python3 dtmf_probe.py selftest                                  # iyi/kötü kanıt
bash run_live_test.sh                                           # uçtan uca statik kapı
```

## Durum
**validate 42/42 · selftest 38/38 · dtmf_behavior 30/30** 🟢. 6 sample beklendiği gibi
(4 pass + `detect-degraded`/`generate-degraded` bilinçli fail).
Bağlar: algılama/üretme → 2.1.3/2.1.4 ingress `dtmf` + API §11.5 `sendDtmf`/`on(DTMF)`;
normalize olay → API §12.2 TurnEvent + SAD §6.1; maskeleme → BRD §8.5 / 17.2.6 (F3).
İz: FR-TEL-006 → SR-TEL-006 → TC-TEL-006. Rapor: `reports/2.1.6-dtmf-detection-generation-raporu.md`.
