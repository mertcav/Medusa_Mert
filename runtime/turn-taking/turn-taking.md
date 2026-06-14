# WBS 3.1.3 — Turn-taking + Barge-in Koordinasyonu (Tasarım)

> **Faz/Öncelik:** F1 · Must · →**FR-RTC-002/003**, FR-RTC-007, FR-TTS-005
> **Katman:** Conversation Orchestrator → **Turn Manager** (SAD §6.2)
> **Kaynak doğruluk:** `turn-taking-spec.json` · çelişkide **BRD/SAD** esas.
> **İlkeler:** Vendor-neutral (ADR-002) · credential-free · stdlib-only · deterministik (olay-tetikli, sanal saat, random YOK)

## 1. Amaç ve kapsam

Conversation Orchestrator'ın (Çekirdek IP, SAD §6) **Turn Manager** alt bileşeni (SAD §6.2),
turn state machine'i (SAD §6.1) sürer ve **konuşma sırasının (turn-taking)** insan operatöre yakın
doğallıkta yönetilmesini sağlar. Bu görev, o koordinasyonu **orchestrator tarafında** birinci-sınıf,
deterministik bir kapıya çevirir:

- **Tek-zemin (floor) kuralı (C3):** her an konuşma sırası YALNIZ bir tarafta; agent kullanıcının
  üstüne konuşmaz (FR-RTC-003).
- **Barge-in koordinasyonu (C1/C2):** edge'den (2.2.3) gelen **onaylı** `barge_in` olayında orchestrator
  TTS akışını (SPEAK) veya in-flight üretimi (THINK/ACT) iptal eder ve CAPTURE'a geçer; karar+dispatch
  gecikmesi küçük bir alt-bütçe (FR-RTC-002).
- **Idempotent iptal (C5):** CAPTURE'da tekrar `barge_in` yeni cancel üretmez.
- **Gereksiz ara yanıt YOK (C3/C7):** kullanıcı zemini elinde tutarken (CAPTURE, endpoint öncesi)
  yanıt başlatılmaz; yalnız endpoint sonrası seslendirilir (FR-RTC-003).
- **Backchannel ayrımı (C4):** "evet / hı hı / bir dakika" gibi kısa geri-bildirim barge-in sayılmaz
  (FR-RTC-007 sınırı).
- **Legal geçişler (C6):** tüm durum geçişleri SAD §6.1 kümesinde.

### Kapsam ayrımı (bilinçli devir)
| Sorumluluk | Sahip |
|------------|-------|
| Edge VAD/endpointing + barge-in **ALGILAMA** (onset → onaylı olay) | **2.2.3** (upstream olay üreteci) |
| TTS **kesme** + egress buffer **flush** ≤200ms | **2.2.7** + 2.2.1 J11 |
| Turn state machine **tanımı** (durumlar/geçişler) | **3.1.2** (bu doküman tüketir) |
| Asenkron olay döngüsü / hafif oturum aktörü | **3.1.1** (bu doküman üstünde koşar) |
| **Orchestrator-tarafı turn-taking + barge-in KOORDİNASYONU** | **3.1.3 (bu)** |
| Native async runtime (Go/Rust) | SAD §6.3 + F1 kod |

## 2. Analiz (kaynak gereksinimler)

| Kaynak | Bulgu | Tasarıma etkisi |
|--------|-------|-----------------|
| **FR-RTC-002** | "Agent, barge-in'i algılayıp konuşmayı **durdurmalı**." | C1 (zemin bırak) + C2 (koordinasyon gecikme) + C5 (cancel tamlık) |
| **FR-RTC-003** | "Kullanıcı konuşurken **gereksiz ara yanıt vermemeli**." | C3 (zemin ihlali=0) + C7 (yalnız endpoint sonrası yanıt) |
| **SR-RTC-002** (T) | "Barge-in → TTS ≤200 ms durdurulur." | C2 orkestratör dilimi ≤50ms; composed e2e ≤200ms |
| **SR-RTC-003** (T) | "Kullanıcı konuşurken **false-trigger oranı eşik altı**." | C3: CAPTURE'da response_ready bastırılır (interim_suppressed) |
| **FR-RTC-007 / SR-RTC-007** | "'Evet/hı hı/bir dakika' doğru yorumlanır; **yanlış turn başlatmaz**." | C4: backchannel barge-in sayılmaz (default politika) |
| **SAD §6.1** | Turn state machine + "barge-in (cancel TTS)" SPEAK→CAPTURE | legal_transitions kümesi; C6 |
| **SAD §6.2** | "Turn Manager: state machine, turn-taking, barge-in koordinasyonu — tüm geçişler **olay-tetikli; bloklayan çağrı yok**." | C8 olay-tetikli/non-blocking; ham ses orchestrator'da yok |
| **SAD §6.3 / ADR-003** | Her oturum hafif async aktör; CPU-bound iş offload | C8: koordinasyon olay düzeyinde, bloklamaz |
| **SAD §20 / NFR 10.1** | Barge-in kesme ≤200ms (tam zincir) | C2 kompozisyon: edge(≈90) + orch(≤50) + egress(≈40) ≤200 |
| **ADR-005 / ADR-009 (hibrit)** | VAD/endpointing+barge-in **algılama edge'de** | Orchestrator yalnız onaylı olay tüketir (C8) |
| **BRD §15** | barge-in sayısı saklanır | `barge_in_count → barge_in_total` (C9 → 0.4.7) |

## 3. Model (deterministik Turn Manager)

```
Durum:    state ∈ {LISTEN,CAPTURE,THINK,ACT,SPEAK,TRANSFER,END};  floor = floor_by_state[state]
Geçiş:    _to(new): (state,new) ∈ legal_transitions ∨ new∈{TRANSFER,END} değilse → illegal++ (C6)
Olaylar (onaylı turn-event, edge + internal):
  speech_start : LISTEN→CAPTURE (zemin user). SPEAK/THINK/ACT'ta ham onset TEK BAŞINA kesmez
                 (onaylı barge_in beklenir — 2.2.3 debounce).
  barge_in     : SPEAK/THINK/ACT → cancel emit (dispatch=orch_dispatch_ms) + →CAPTURE (C1/C2);
                 CAPTURE → idempotent yoksay (duplicate++, yeni cancel YOK) (C5)
  backchannel  : default → yoksay (cancel/zemin değişimi YOK) (C4);  (non-default) → barge-in gibi
  endpoint     : CAPTURE→THINK (turn++); yanıt ancak bundan SONRA (C7)
  response_ready: THINK/ACT→SPEAK;  CAPTURE → floor_guard ? bastır (interim_suppressed) : ihlal (C3)
  tool_needed/tool_done : THINK↔ACT
  tts_complete : SPEAK→LISTEN (agent zemini bıraktı)
  transfer/hangup : →TRANSFER / →END (her durumdan)
Koordinasyon gecikmesi = barge_in olayı → cancel dispatch = orch_dispatch_ms (sanal, deterministik)
composed_e2e = edge_detect_nominal + coordination_p95 + egress_flush_nominal   (bilgilendirici ≤200ms)
```

`percentile` 0.3.x / 2.2.x ile birebir lineer-interpolasyon. Olaylar **stabil** zaman sıralamasıyla
işlenir (eşit `t` → giriş sırası korunur) — determinizm.

## 4. HARD kapılar

| Kapı | Ölçüt | Kaynak |
|------|-------|--------|
| **C1** işlenmeyen barge-in | `unhandled_barge_in = 0` (SPEAK/THINK/ACT→cancel+CAPTURE) | FR-RTC-002 |
| **C2** koordinasyon gecikmesi | `coordination_p95 ≤ 50ms` (green ≤20ms); composed e2e ≤200ms | NFR 10.1, SAD §6.1/§20 |
| **C3** zemin ihlali | `floor_violation = 0` (agent kullanıcı zeminindeyken konuşmaz) | FR-RTC-003 |
| **C4** backchannel ayrımı | `backchannel_action = 0` (default politika) | FR-RTC-007 |
| **C5** cancel tamlık/idempotent | `missed_cancels = 0 ∧ spurious_cancels = 0` | FR-RTC-002, FR-TTS-005 |
| **C6** legal geçişler | `illegal_transitions = 0` (SAD §6.1) | SAD §6.1 |

C2'de **yalnız orkestratör dilimi** HARD ölçülür; edge algılama (2.2.3) + egress flush (2.2.7) dilimleri
bilgilendirici kompozisyonla toplanır (sahipleri ayrı). C7 (yalnız endpoint sonrası yanıt) ve
C8 (olay-tetikli/ham-ses-yok) yapısal invariant'lar `validate` ile sabitlenir.

## 5. Çıktılar
`turn-taking-spec.json` (kaynak doğruluk) · `turn-taking.md` (bu) · `turn_taking_probe.py`
(validate/simulate/selftest/schema) · `config/turn-taking-profiles.json` (managed/byoc/low-latency) ·
`samples/` (6: happy-path, barge-in-speak, barge-in-think, backchannel-ignored, no-spurious-interim,
transfer, +degraded) · `tests/turn_taking_behavior_test.py` (T1–T8) · `run_live_test.sh` · `README.md`.

## 6. İzlenebilirlik
`FR-RTC-002` → `SR-RTC-002` (T) → `TC-RTC-002`; `FR-RTC-003` → `SR-RTC-003` (T) → `TC-RTC-003`;
`FR-RTC-007` → `SR-RTC-007` (T) → `TC-RTC-007` → **WBS 3.1.3** (RTM'de eşli; SRS/RTM değişikliği gerekmedi).
Metrikler → `observability-spec.json` (0.4.7) `barge_in_total`. Mimari: SAD §6/§6.1/§6.2/§6.3/§20/§23,
ADR-001/002/003/005/009.
