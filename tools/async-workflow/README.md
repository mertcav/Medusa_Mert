# tools/async-workflow — Asenkron uzun-işlem workflow (WBS 7.2.4)

Integration Gateway'in uzun-işlem (FR-TOOL-011) dilimi: orkestratör **beklemeden** (non-blocking)
uzun süren tool işlemlerini başlatır; sonuç **callback (imzalı inbound webhook)** ∨ **polling (bounded)**
ile mutabık kılınır. SAD §11.2 · API §10.1/§10.2 · THREAT_MODEL SEC-05/TM-S-05.

## Dosyalar
- `async-workflow-spec.json` — makine-okunur kaynak doğruluk (durum makinesi, reconciliation, callback
  güvenliği, result-by-reference, W1–W12, fault hizalama, audit).
- `async-workflow.md` — tasarım (konum, durum makinesi, iki mutabakat modu, invariant'lar, kapsam dışı).
- `async_workflow_probe.py` — stdlib-only probe: `validate` / `run <sample>` / `selftest` / `schema`.
- `config/async-workflow-profiles.json` — `callback-primary` / `polling-only` / `hybrid` preset (sır yok).
- `samples/*.json` — sentetik senaryolar (FR-TST-008).
- `tests/async_workflow_behavior_test.py` — kara-kutu davranış (T1–T17).
- `run_live_test.sh` — tüm kapılar + (varsa) canlı callback/poll endpoint notu.

## Çalıştırma
```bash
python3 async_workflow_probe.py validate     # statik + sample kapısı
python3 async_workflow_probe.py selftest     # gömülü davranış (W1–W12)
python3 async_workflow_probe.py run samples/callback-success.json
python3 tests/async_workflow_behavior_test.py
./run_live_test.sh                           # hepsi + canlı SKIP/not
```

## Çekirdek invariant (SR-TOOL-011)
> *"Uzun işlem bloklamadan callback/polling ile tamamlanır."*

Dispatch HEMEN `pending` + `execution_id` döner (W1); nihai sonuç callback (HMAC+±300s+nonce, W4) ∨
bounded poll (W5) ile gelir; callback∧poll yarışı **exactly-once** (W3); sonuç **referansla** (`result_ref`,
W8). Vendor-neutral (ADR-001/002); sır/PII repoya yazılmaz.
