# runtime/turn-taking — WBS 3.1.3 Turn-taking + Barge-in Koordinasyonu

Conversation Orchestrator **Turn Manager** (SAD §6.2) — orchestrator-tarafı **turn-taking + barge-in
koordinasyonu** sözleşmesi ve deterministik kapı simülatörü. `F1` · `Must` · →FR-RTC-002/003.

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only. `telephony/edge-vad/` (2.2.3) probe disipliniyle
birebir. **Kapsam:** orchestrator KOORDİNASYON — edge barge-in **algılama** 2.2.3, TTS **kesme/flush**
2.2.7, turn state machine **tanımı** 3.1.2.

## Dosyalar
- `turn-taking-spec.json` — **kaynak doğruluk**: placement, turn_state_machine (legal_transitions),
  floor_control, barge_in (koordinasyon bütçesi + kompozisyon), backchannel, no_spurious_interim,
  gates (C1–C6), metrics, error_taxonomy, residency, pii, invariants (C1–C10).
- `turn-taking.md` — tasarım: model, kapılar, izlenebilirlik.
- `turn_taking_probe.py` — `validate` | `simulate <sample>` | `selftest` | `schema`.
- `config/turn-taking-profiles.json` — managed-ws / byoc-rtp / low-latency (orch_dispatch_ms, bölge pini).
- `samples/*.json` — happy-path, barge-in-speak, barge-in-think, backchannel-ignored,
  no-spurious-interim, transfer (geçer) + degraded (bilinçli **fail**).
- `tests/turn_taking_behavior_test.py` — davranış kapısı T1–T8.
- `run_live_test.sh` — statik kapı + (varsa `ORCHESTRATOR_URL`) canlı not; yoksa SKIP.

## Çalıştırma
```bash
python3 turn_taking_probe.py validate      # spec + config invariant kapısı
python3 turn_taking_probe.py selftest      # iyi/kötü kanıt + negatif validate kapıları
python3 turn_taking_probe.py simulate samples/turn-barge-in-speak.json
python3 tests/turn_taking_behavior_test.py # T1–T8
bash run_live_test.sh                       # hepsi + canlı SKIP
```

## HARD kapılar
C1 işlenmeyen barge-in=0 · C2 koordinasyon P95 ≤50ms (green ≤20; composed e2e ≤200ms) ·
C3 zemin ihlali=0 · C4 backchannel-eylemi=0 · C5 cancel tamlık/idempotent · C6 illegal geçiş=0.

**Sır/credential, ham ses payload'ı, transkript ve PII repoya yazılmaz** — olaylar yalnız tip + sanal
zaman damgası taşır. Canlı sistemde aynı sözleşme Go/Rust async runtime'da (ADR-003, SAD §6.3) gerçek
edge turn-event akışıyla doldurulur.
