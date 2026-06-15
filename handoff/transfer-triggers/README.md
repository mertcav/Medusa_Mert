# `handoff/transfer-triggers/` — WBS 9.4 Transfer Tetikleyiciler

9. workstream'in (İnsan Temsilciye Aktarım) **dördüncü** modülü · **F1 · Must** · →**FR-HND-001/002**.

Transfer **karar üreticisi**: konuşma sinyallerini (kullanıcı isteği · düşük confidence · öfke · politika)
değerlendirip insan temsilciye aktarımın **ne zaman/neden** tetikleneceğine karar verir. Kararı
9.1 (cold) / 9.2 (warm) / 9.3 (whisper) mekanizma modülleri **tüketir**.

## Dosyalar
| Yol | Açıklama |
|-----|----------|
| `transfer-triggers-spec.json` | Makine-okunur **kaynak doğruluk**: durumlar, tetik sınıfları + öncelik, eşikler, kapılar, invariant T1–T11, izlenebilirlik |
| `transfer-triggers.md` | Tasarım dokümanı (durum makinesi, dört tetik sınıfı, anti-flapping, kapsam ayrımı) |
| `transfer_triggers_probe.py` | Stdlib-only **deterministik değerlendirme motoru**: `validate`/`run`/`selftest`/`schema` |
| `config/transfer-trigger-policies.json` | Eşik/histerezis/öncelik/mandatory-reason/emit-hedef parametreleri (credential-free) |
| `samples/*.json` | 6 pass + 6 degrade senaryo (sentetik, FR-TST-008) |
| `tests/transfer_triggers_behavior_test.py` | Bağımsız kara-kutu davranış kapısı (T1–T9) |
| `run_live_test.sh` | Tüm statik + davranış kapılarını koşar |

## Hızlı çalıştırma
```bash
cd handoff/transfer-triggers
./run_live_test.sh                              # tümü
python3 transfer_triggers_probe.py validate     # statik kapı
python3 transfer_triggers_probe.py run samples  # senaryolar
python3 transfer_triggers_probe.py selftest     # gömülü kontroller
```

## Tetik sınıfları (öncelik sırası)
1. `USER_REQUEST` (FR-HND-001, mandatory, bastırılamaz) — açık handoff niyeti → anında
2. `POLICY` (FR-HND-002, mandatory, bastırılamaz) — uyumluluk/kapsam-dışı/maks-deneme → anında
3. `ANGER` (FR-HND-002, heuristic) — öfke ≥ eşik, sürdürülen
4. `LOW_CONFIDENCE` (FR-HND-002, heuristic) — confidence ≤ eşik, sürdürülen (**debounce**)

## Durum
selftest **37/37** 🟢 · validate **70/70** 🟢 · run **12/12** 🟢 (6 pass + 6 degrade beklendiği gibi
elendi) · behavior **15/15** 🟢. Vendor-neutral (ADR-001/002); sır/credential repoya yazılmaz; ham
transkript/müşteri sözleri tutulmaz (T11). Canlı tetik testi F1'de gerçek STT/NLU/sentiment + 9.1/9.2/9.3.

Rapor: [`reports/9.4-transfer-tetikleyiciler-raporu.md`](../../reports/9.4-transfer-tetikleyiciler-raporu.md)
