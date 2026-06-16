# WBS 11.3 — Transkript üretimi + timeline

**Faz:** F1 · **Öncelik:** Must · **İz:** BRD §8.1 → FR-REC-008 → SR-REC-008 → TC-REC-008

11. workstream'in (Kayıt, Transkript & PII Redaction) **transkript üretimi (transcript-build)** modülü.
**11.1 (recording-policy)** içerik/kayıt kararını + **11.2 (channel-recording)** kanal/konuşmacı yerleşimini
ÜRETTİKTEN **sonra**, çağrının canlı STT **final transcript turn**'lerini (SAD §6.1 turn state machine;
SAD §8.2 turn-event) ve sistem olaylarını (`call_event`, DB §23) alır → **deterministik, zaman-sıralı,
konuşmacı-atflı** bir transkript (DB §21 `transcript` + `transcript_segment`) + **birleşik timeline**
(segment ⊕ sistem olay; **A-12** Çağrı Detayı / Transkript & Timeline ekranı) üretir ve terminal karar verir:
**`TRANSCRIPT` | `NO_TRANSCRIPT` | `BLOCK`**.

Modül **Analytics Plane asenkron** post-processing'tir (SAD §10.1/§10.2 Transcript Store; FR-RES-011 —
hot-path değil). Üretilen transkript **`redaction_state=pending`** ile **11.4 PII redaction** + **11.5
kart/parola/OTP çıkarma** + **11.6 erişim audit/görüntüleme**'ye **aktarılır** — *bu modül redaction yapmaz*.

## Karar akışı

```
TranscriptBuildRequest ─tenant doğrula─► içerik kapısı ─► sırala+seq ─► konuşmacı atfı ─► timeline ─► redaction pending
      ├─ cross-tenant ──────────────────────────────────────────────► BLOCK (cross_tenant)         [K12]
      ├─ upstream yok/geçersiz ─────────────────────────────────────► BLOCK (no_upstream)
      ├─ yetkisiz (11.1 upstream_decision ≠ RECORD) ───────────────► NO_TRANSCRIPT (no content)     [K5]
      ├─ malformed turn (turn_id yok) ─────────────────────────────► BLOCK (invalid_turn_stream)    [K8]
      └─ yetkili ───────────────────────────────────────────────────► TRANSCRIPT (seq+atıf+timeline) [K2/K3/K4/K7]
```

**Çekirdek garanti (K5, FR-REC-002 aşağı akış):** `upstream ≠ RECORD ⇒ no_content_persisted = true`.
**Çekirdek garanti (K7, FR-REC-004/005 aşağı akış):** transkript `redaction_state ∈ {pending, not_required}` —
bu modül **asla** `redacted` üretmez (redaction'ı 11.4/11.5 yapar).

### Üretim (K2/K3/K4)
- **K2 zaman-sıralı:** segmentler `started_ms`'e göre **monoton artan** + `seq` **1..N bitişik** (kanonik
  sıra `(started_ms, turn_id)`; sırasız girdi deterministik sıralanır). Out-of-order / seq-gap yasak.
- **K3 konuşmacı atfı:** her segment `speaker ∈ {caller, agent, human}` (DB §21); DUAL kanalda (channels=2,
  11.2) konuşmacı-kanal tutarlı (caller→ch0, agent/human→ch1). Atıfsız / yanlış-atıf yasak.
- **K4 tamlık:** her final turn → **tam bir** segment (düşmez/çoğalmaz); timeline **TÜM** segment + **TÜM**
  sistem olayını içerir (event düşmez).

## İnvariant'lar (K1–K12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| K1 | | Determinizm/terminal; `stuck_state=0` |
| **K2** | BRD §8.1 | Zaman-sıralı üretim: `started_ms` monoton + `seq` 1..N bitişik; `ordering_violation=0` |
| **K3** | DB §21 | Konuşmacı atfı: speaker ∈ {caller,agent,human}; DUAL kanal tutarlı; `missing_speaker=0 ∧ speaker_mismatch=0` |
| **K4** | BRD §8.1 | Tamlık: her final turn → 1 segment; timeline TÜM segment+olay; `turn_dropped=0 ∧ turn_duplicated=0 ∧ event_dropped=0` |
| **K5** | FR-REC-002 | İçerik kapısı: `upstream≠RECORD ⇒ no content`; `over_capture=0` |
| K6 | NFR 10.7 | Residency: transkript home-region'da kalıcı |
| **K7** | FR-REC-004/005 | Redaction devri: `redaction_state ∈ {pending,not_required}`; ASLA `redacted`; `premature_redaction=0` |
| **K8** | SR-REC-008 | ATLANAMAZ: bypass=`assembly_skip`; malformed→BLOCK (`failopen=0`) = BRD §15 alarmı |
| K9 / K10 | FR-IAM-006 | Kanıt + audit (ham transkript metni/PII yok) |
| K11 | FR-REC-004 | Gözlemlenebilirlik düşük-kardinalite + PII yok |
| K12 | FR-TEN-002 | Sır/ham-transkript yok + tenant izolasyonu |

## Çalıştırma

```bash
./run_live_test.sh                                  # tüm kapılar (statik)
python3 transcript_build_probe.py validate          # statik spec/config/kapsama
python3 transcript_build_probe.py selftest          # gömülü davranış (K1–K12)
python3 transcript_build_probe.py check samples     # 11 pass + 14 degrade
python3 transcript_build_probe.py schema            # karar sözleşmesi
python3 tests/transcript_build_behavior_test.py     # bağımsız davranış testi
```

**Durum:** validate **100/100** 🟢 · selftest **83/83** 🟢 · check **25/25** 🟢 (14 degrade beklendiği gibi
elendi) · behavior **85/85** 🟢.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `transcript-build-spec.json` | Kaynak doğruluk: kurallar, karar, speakers, timeline, redaction_states, invariant'lar K1–K12, kapılar, izlenebilirlik |
| `transcript_build_probe.py` | stdlib-only motor: `validate` / `check` / `selftest` / `schema` |
| `config/transcript-build.json` | valid_speakers + channel_side (11.2) + order_key + producible redaction_states + timeline event türleri |
| `samples/*.json` | 11 pass + 14 degrade senaryo (FR-TST-008) |
| `tests/transcript_build_behavior_test.py` | Bağımsız davranış testi |
| `run_live_test.sh` | Statik + davranış kapısı koşucusu |

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| Kayıt/içerik **kararı** + consent + tamamen kapatma | 11.1 (recording-policy; `upstream_decision` **tüketilir**) |
| Kanal/track yerleşimi + `channels` + konuşmacı-kanal | 11.2 (channel-recording; **tüketilir**) |
| Ham transkript **METİN byte** üretimi (STT) + nesne depo yazımı | SAD §6.1/§10.2 Transcript Store + DB §21 `storage_uri` (sıralama/atıf/timeline **kararı** verilir, ham metin **yazılmaz**) |
| PII redaction (FR-REC-004) | 11.4 (`redaction_state=pending` **taşınır**; DUAL'da kanal-bazlı redaction) |
| Kart/parola/OTP çıkarma (FR-REC-005) | 11.5 (`redaction_required` **taşınır**) |
| Kayıt/transkript erişim audit + dinleme/**görüntüleme** yetkisi (FR-REC-008/009) | 11.6 (`transcript:read`; bu modül **karar** audit'ini üretir) |
| Çağrı **özeti** (summary) LLM üretimi | özetleyici (DB §21 `transcript.summary` **taşınır**, doldurulmaz) |
| Retention / legal-hold / silme (FR-REC-006/007/010) | retention motoru |
| Residency depolama **uygulaması** | DB §8 / SAD §12.1 (residency **kararı** verilir) |
| Panel UI | L2 **A-12** (Çağrı Detayı / Transkript & Timeline) |

## Notlar

- **Vendor-neutral** (ADR-001/002/012); STT sağlayıcı + transkript depolama bağımsız.
- **Sır/credential ve gerçek PII** (ham transkript metni / müşteri adı/telefon / ham ses / OTP) **repoya
  yazılmaz** — yalnız yapısal kimlikler + enum + sayı/offset (`turn_id`/`speaker`/`started_ms`/`seq`).
  Canlı transkript üretimi yalnız `${TRANSCRIPT_BUILD_URL}`.
- İskelet kapısı; canlı Transcript Store (SAD §10.2) ham metin byte yazımı + DB §21 `transcript`/
  `transcript_segment` satırı + nesne depolama/residency (DB §8) + PII redaction (11.4) entegrasyonu F1'de dolar.
- SRS/RTM/BRD değişmedi — RTM zaten `FR-REC-008 → SR-REC-008 → TC-REC-008` eşler; yeni FR/SR eklenmedi.
  Bu modül **transkript+timeline üretimini** (BRD §8.1) sahiplenir; **görüntüleme yetkisini** (FR-REC-008
  testedilebilir yüzeyi) 11.6 tamamlar.
