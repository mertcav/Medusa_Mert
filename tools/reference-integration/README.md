# tools/reference-integration — CRM/Ticketing/ERP referans entegrasyonu (pilot) (WBS 7.2.5)

7.x tool hattının **pilot kapstonu**: yeni transport eklemez; SAD §11.1 Tool Yürütme Hattını ([1]→[7])
**orkestre ederek** temsilci CRM/Ticketing/ERP sistemlerine karşı uçtan uca gerçek işlem (read+write)
gösterir. BRD §6.1 · OBJ-07 · SAD §11.1/§11.2/§11.3 · FR-TOOL-001..012.

## Dosyalar
- `reference-integration-spec.json` — makine-okunur kaynak doğruluk (zincir adımları + pilot paketleri +
  referans tool tanımları + fault→kategori + R1–R12 + audit).
- `reference-integration.md` — tasarım (zincir sahipliği, paketler, invariant'lar, kapsam dışı).
- `reference_integration_probe.py` — stdlib-only probe: `validate` / `run <sample>` / `selftest` / `schema`.
- `config/reference-packs.json` — pilot connector paketleri (sır yalnız `${ENV}`).
- `samples/*.json` — sentetik uçtan-uca senaryolar (FR-TST-008).
- `tests/reference_integration_behavior_test.py` — kara-kutu davranış (T1–T13).
- `run_live_test.sh` — tüm kapılar + (varsa) canlı pilot endpoint notu.

## Çalıştırma
```bash
python3 reference_integration_probe.py validate     # statik + pack + kapsama kapısı
python3 reference_integration_probe.py selftest     # gömülü davranış (R1–R12)
python3 reference_integration_probe.py run samples/crm-create-case-committed.json
python3 tests/reference_integration_behavior_test.py
./run_live_test.sh                                  # hepsi + canlı SKIP/not
```

## Çekirdek invariant (SR-TOOL-001 + OBJ-07)
> *Pilot paketleri REST (CRM/ticketing) + GraphQL (ticketing) + SOAP (ERP) tiplerinin her birinde
> başarılı uçtan-uca çağrı yapar; Tool Yürütme Hattını [1]→[7] fail-closed yürütür.*

Zincir: schema (7.1.1) → authz (7.1.2) → kritik policy gate (7.3 bağ) → idempotency (7.1.3) → allowlist
(7.2.3) + GW (7.1.4) → connector (7.2.1/7.2.2) → error-norm (7.1.5) → audit + Tool Execution (7.1.6/BRD §16).
Vendor-neutral (ADR-001/002); bağlayıcı vendor seçimi yok (BRD §22); sır/PII repoya yazılmaz.
