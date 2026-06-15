# handoff/whisper-transfer — Whisper Transfer (yalnız temsilciye duyulan brifing) · WBS 9.3

`F2` · `Must` · →FR-TEL-007 (whisper), FR-HND-006 (whisper brifing ruhu), FR-HND-007 (fallback), FR-HND-008 (raporlama) · SAD §7.3.

İnsan temsilciye **whisper transfer** (ad-hoc conferencing RFC 4579 + per-katılımcı seçici medya /
whisper-coach mix) deterministik durum makinesi. AI müşteriyi **bilgilendirir** ama **HOLD'a ALMAZ**
(müşteri CANLI kalır — BRD §14.2), temsilci **canlı konferansa** eklenir, temsilci katılınca AI
**yalnız temsilciye** per-leg whisper brifing iletir (müşteri canlı çağrıda, **duymaz**, FR-HND-006),
sonra AI **temsilci mevcutken** çıkar → müşteri↔temsilci canlı çağrıda devam eder; başarısızlıkta
**oturum düşmez**, müşteri canlı çağrıda kalıp 9.7 fallback'a devredilir (fail-safe).

```
INIT ─► ANNOUNCE ─► AGENT_JOINING ─► WHISPERING ─► HANDED_OFF  (RELEASE_AI: müşteri↔temsilci canlı, AI çıkar)
   └──────────── her aşamada başarısızlık ─────────────► FAILED  (FALLBACK: müşteri canlı korunur, 9.7)
```

**Warm'dan (9.2) fark:** warm müşteriyi **HOLD**'a alır + **ayrı danışma B-leg** kurar + sonra
A+B **köprüler**; whisper müşteriyi **HOLD'a ALMAZ** — temsilci **canlı konferansa** eklenir, AI
**per-leg seçici karışımla** yalnız temsilciye brifing iletir (müşteri canlı, aktif dinliyor). Bu
yüzden whisper privacy ihlali (H3) warm'dan **daha keskin** ve müşteri-hold (H4) bir ihlaldir.

## Dosyalar
- `whisper-transfer-spec.json` — makine-okunur kaynak doğruluk (durum/geçiş/kapı/konferans-transfer/invariant H1–H12).
- `whisper-transfer.md` — tasarım (durum makinesi, RFC 4579 + per-leg karışım eşlemesi, whisper privacy, warm'dan fark, kapsam ayrımı).
- `whisper_transfer_probe.py` — stdlib-only: `validate` / `run <sample|dizin>` / `selftest` / `schema`.
- `config/whisper-transfer-policies.json` — deadline/anons(no-hold)/whisper/release/fallback parametreleri (credential-free).
- `samples/*.json` — 4 pass (happy / join-no-answer / join-busy / deadline) + 6 degrade (blind-join / cross-tenant / leak / customer-held / premature-exit / drop-on-failure).
- `tests/whisper_transfer_behavior_test.py` — davranış kapısı T1–T8.
- `run_live_test.sh` — validate + selftest + run + behavior (sunucu gerektirmez).

## Çalıştırma
```bash
./run_live_test.sh                                 # tümü
python3 whisper_transfer_probe.py validate         # statik spec/config/kapsama → çıkış kodu
python3 whisper_transfer_probe.py selftest         # FSM davranış invariant'ları
python3 whisper_transfer_probe.py run samples      # örnek senaryolar (pass + degrade)
python3 whisper_transfer_probe.py schema           # durum/olay/sonuç sözleşmesi
```

## Kapsam ayrımı
`transfer()` SPI + ham konferans/per-leg whisper karışımı → **4.2.5** (çağırır/tüketir); cold → **9.1**;
warm → **9.2**; tetikleyici → **9.4**; hedef seçimi → **9.5**; bağlam paketi → **9.6** (whisper özet
referansı); fallback motoru → **9.7**; raporlama → **9.8**. Vendor-neutral (ADR-002); sır/ham
numara/brifing-metni/PII repoya yazılmaz.
