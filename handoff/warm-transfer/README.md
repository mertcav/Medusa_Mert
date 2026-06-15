# handoff/warm-transfer — Warm Transfer (köprüleme + whisper brifing) · WBS 9.2

`F1` · `Must` · →FR-TEL-007 (warm), FR-HND-006 (whisper brifing), FR-HND-007 (fallback), FR-HND-008 (raporlama) · SAD §7.3.

İnsan temsilciye **warm (attended/danışmalı) transfer** (RFC 5589 + REFER/Replaces) deterministik durum
makinesi. AI müşteriyi bilgilendirip **hold**'a alır (BRD §14.2), CC hedefine **danışma çağrısı** kurar,
hedef yanıtlayınca **yalnız temsilciye** whisper brifing verir (müşteri duymaz, FR-HND-006), müşteri↔temsilci
**köprülenir** ve AI **köprü kurulduktan sonra** çıkar; başarısızlıkta **oturum düşmez**, müşteri hold'dan
geri alınıp 9.7 fallback'a devredilir (fail-safe).

```
INIT ─► ANNOUNCE ─► CONSULT_RINGING ─► WHISPER ─► BRIDGED ─► TRANSFERRED  (RELEASE_AI: A+B köprülü, AI çıkar)
   └──────────────── her aşamada başarısızlık ───────────────► FAILED      (FALLBACK: müşteri hold'dan geri, 9.7)
```

**Cold'dan (9.1) fark:** cold fire-and-forget (REFER, oturum kapanır, köprü yok); warm danışmalı köprüleme
(hold → danışma → whisper → köprü → AI çıkar, A-leg köprülü kalır).

## Dosyalar
- `warm-transfer-spec.json` — makine-okunur kaynak doğruluk (durum/geçiş/kapı/attended-transfer/invariant W1–W11).
- `warm-transfer.md` — tasarım (durum makinesi, RFC 5589/3891 eşlemesi, whisper privacy, kapsam ayrımı).
- `warm_transfer_probe.py` — stdlib-only: `validate` / `run <sample|dizin>` / `selftest` / `schema`.
- `config/warm-transfer-policies.json` — deadline/anons/whisper/köprü/fallback parametreleri (credential-free).
- `samples/*.json` — 4 pass (happy / consult-no-answer / consult-busy / deadline) + 5 degrade (blind-consult / cross-tenant / whisper-leak / exit-before-bridge / drop-on-failure).
- `tests/warm_transfer_behavior_test.py` — davranış kapısı T1–T7.
- `run_live_test.sh` — validate + selftest + run + behavior (sunucu gerektirmez).

## Çalıştırma
```bash
./run_live_test.sh                              # tümü
python3 warm_transfer_probe.py validate         # statik spec/config/kapsama → çıkış kodu
python3 warm_transfer_probe.py selftest         # FSM davranış invariant'ları
python3 warm_transfer_probe.py run samples      # örnek senaryolar (pass + degrade)
python3 warm_transfer_probe.py schema           # durum/olay/sonuç sözleşmesi
```

## Kapsam ayrımı
`transfer()` SPI + ham danışma/köprü → **4.2.5** (çağırır/tüketir); cold → **9.1**; salt-whisper → **9.3**;
tetikleyici → **9.4**; hedef seçimi → **9.5**; bağlam paketi → **9.6** (whisper özet referansı); fallback
motoru → **9.7**; raporlama → **9.8**. Vendor-neutral (ADR-002); sır/ham numara/brifing-metni/PII repoya yazılmaz.
