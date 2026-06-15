# handoff/cold-transfer — Cold Transfer (SIP REFER) · WBS 9.1

`F1` · `Must` · →FR-TEL-007 (cold), FR-HND-007 (fallback), FR-HND-008 (raporlama) · SAD §7.3.

İnsan temsilciye **cold/blind transfer** (SIP REFER, RFC 3515) deterministik durum makinesi. Agent
müşteriyi bilgilendirir (BRD §14.2), çağrıyı CC hedefine REFER ile yönlendirir ve **köprü kurmadan çıkar**
(fire-and-forget); başarısızlıkta **oturum düşmez**, 9.7 fallback'a devredilir (fail-safe).

```
INIT ─► ANNOUNCE ─► REFER_SENT ─► REFERRING ─► TRANSFERRED  (RELEASE: A-leg BYE, agent çıkar)
   └────────── her aşamada başarısızlık ──────────► FAILED  (FALLBACK: oturum korunur, 9.7)
```

## Dosyalar
- `cold-transfer-spec.json` — makine-okunur kaynak doğruluk (durum/geçiş/kapı/SIP REFER/invariant C1–C10).
- `cold-transfer.md` — tasarım (durum makinesi, RFC 3515 eşlemesi, kapsam ayrımı).
- `cold_transfer_probe.py` — stdlib-only: `validate` / `run <sample|dizin>` / `selftest` / `schema`.
- `config/cold-transfer-policies.json` — deadline/anons/fallback parametreleri (credential-free).
- `samples/*.json` — 4 pass (happy / refer-rejected / notify-busy / deadline) + 3 degrade (blind-refer / cross-tenant / drop-on-failure).
- `tests/cold_transfer_behavior_test.py` — davranış kapısı T1–T6.
- `run_live_test.sh` — validate + selftest + run + behavior (sunucu gerektirmez).

## Çalıştırma
```bash
./run_live_test.sh                              # tümü
python3 cold_transfer_probe.py validate         # statik spec/config/kapsama → çıkış kodu
python3 cold_transfer_probe.py selftest         # FSM davranış invariant'ları
python3 cold_transfer_probe.py run samples      # örnek senaryolar (pass + degrade)
python3 cold_transfer_probe.py schema           # durum/olay/sonuç sözleşmesi
```

## Kapsam ayrımı
`transfer()` SPI + ham SIP/RTP → **4.2.5** (çağırır/tüketir); warm → **9.2**; whisper → **9.3**;
tetikleyici → **9.4**; hedef seçimi → **9.5**; bağlam paketi → **9.6**; fallback motoru → **9.7**;
raporlama → **9.8**. Vendor-neutral (ADR-002); sır/ham numara/PII repoya yazılmaz.
