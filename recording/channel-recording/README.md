# WBS 11.2 — Tek/çift kanallı kayıt

**Faz:** F1 · **Öncelik:** Must · **İz:** FR-REC-003 → SR-REC-003 → TC-REC-003

11. workstream'in (Kayıt, Transkript & PII Redaction) **kanal-yerleşimi (channel-recording)** modülü.
**11.1 (recording-policy)** RECORD kararını + `channels` attribute'unu (1/2) ÜRETTİKTEN **sonra** çalışır;
bu modül onun **aşağı akış tüketicisidir**. Kaydı yazacak Recording Pipeline'a (SAD §10.2) hangi **kanal
yerleşiminin** (mono/stereo) kurulacağını ve medya bacaklarının (caller/agent/human) hangi track'e
bağlanacağını çözer ve bir terminal karar verir: **`MONO` | `DUAL` | `NO_RECORD` | `BLOCK`**.

Çekirdek gereksinim:

- **FR-REC-003** — **Tek veya çift kanallı kayıt** desteklenmelidir.
  SR-REC-003 kabul ölçütü: *"Seçilen kanal modu üretilir."*
  - **MONO** (`channels=1`) — tek kanal, present **tüm** bacak (caller+agent+human) tek track'e *downmix*.
  - **DUAL** (`channels=2`) — çift/stereo kanal, **caller → ch0**, **agent/human → ch1** *ayrı* track'lerde.

Modül **deterministik, fail-closed** bir karar fonksiyonudur; **11.1'in tamamen-kapatma garantisini aşağı
akışta korur**: 11.1 RECORD demediyse hiçbir track yazılmaz.

## Karar akışı

```
ChannelRecordingRequest ─11.1 yetki doğrula─► channels {1,2} doğrula ─► layout çöz ─► bacak→kanal bağla
      ├─ cross-tenant ──────────────────────────────────────────────► BLOCK (cross_tenant)        [K12]
      ├─ upstream yok/geçersiz ─────────────────────────────────────► BLOCK (no_upstream)
      ├─ yetkisiz (11.1 upstream_decision ≠ RECORD) ───────────────► NO_RECORD (no media)          [K5]
      ├─ channels ∉ {1,2} ─────────────────────────────────────────► BLOCK (invalid_channel_count) [K2/K7]
      ├─ channels=1 ───────────────────────────────────────────────► MONO (1 track, tüm bacak)     [K4]
      └─ channels=2 ───────────────────────────────────────────────► DUAL (caller↔agent ayrı)      [K3]
```

**Çekirdek garanti (K5, FR-REC-002/SR-REC-002 aşağı akış):** `upstream ≠ RECORD ⇒ no_media_captured = true`.

### Kanal modu üretimi (K2, FR-REC-003)
`channels ∈ {1,2}` (DB §22 `recording.channels CHECK IN (1,2)`) → seçilen track yerleşimine **birebir** üretilir:
- `channels=1` ⇒ **MONO** (1 track) · `channels=2` ⇒ **DUAL** (2 track) · `track sayısı == channels`
- `channels ∉ {1,2}` ⇒ **BLOCK** `invalid_channel_count` (asla sessiz varsayılan kayıt)

### Bacak → kanal bağlama (`channel_side`)
| Bacak (leg) | MONO | DUAL |
|-------------|------|------|
| `caller` | ch0 (downmix) | **ch0** |
| `agent` | ch0 (downmix) | **ch1** |
| `human` (transfer sonrası) | ch0 (downmix) | **ch1** (agent tarafı) |

## İnvariant'lar (K1–K12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| K1 | | Determinizm/terminal; `stuck_state=0` |
| **K2** | FR-REC-003 | Kanal modu üretimi: `channels∈{1,2}` → `track sayısı==channels`; `∉{1,2}`→BLOCK |
| **K3** | FR-REC-003 (çift) | DUAL ayrışma: caller→ch0, agent/human→ch1; karıştırma/yanlış-bağlama/boş-kanal yok |
| **K4** | FR-REC-003 (tek) | MONO tamlık: present **tüm** bacak tek track'e; bacak düşmez |
| **K5** | FR-REC-002/SR-REC-002 | Yalnız 11.1 RECORD iken kayıt: `upstream≠RECORD ⇒ no media` (over-capture yasak) |
| K6 | NFR 10.7 | Residency: kayıt home-region'da yazılır |
| K7 | | Fail-closed geçersiz kanal (sessiz varsayılan kayıt yok) |
| **K8** | SR-REC-003 | ATLANAMAZ: bypass = `layout_skip` = BRD §15 alarmı |
| K9 / K10 | FR-IAM-006 | Kanıt + audit (ham PII yok) |
| K11 | FR-REC-004 | Gözlemlenebilirlik düşük-kardinalite + PII yok |
| K12 | FR-TEN-002 | Sır/PII yok + tenant izolasyonu |

## Çalıştırma

```bash
./run_live_test.sh                                  # tüm kapılar (statik)
python3 channel_recording_probe.py validate         # statik spec/config/kapsama
python3 channel_recording_probe.py selftest         # gömülü davranış (K1–K12)
python3 channel_recording_probe.py check samples    # 11 pass + 11 degrade
python3 channel_recording_probe.py schema           # karar sözleşmesi
python3 tests/channel_recording_behavior_test.py    # bağımsız davranış testi
```

**Durum:** validate **85/85** 🟢 · selftest **70/70** 🟢 · check **22/22** 🟢 (11 degrade beklendiği gibi
elendi) · behavior **73/73** 🟢.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `channel-recording-spec.json` | Kaynak doğruluk: kurallar, karar, layouts, invariant'lar K1–K12, kapılar, izlenebilirlik |
| `channel_recording_probe.py` | stdlib-only motor: `validate` / `check` / `selftest` / `schema` |
| `config/channel-recording.json` | MONO/DUAL layout + `channel_side` bacak→kanal haritası + `valid_channels` {1,2} |
| `samples/*.json` | 11 pass + 11 degrade senaryo (FR-TST-008) |
| `tests/channel_recording_behavior_test.py` | Bağımsız davranış testi |
| `run_live_test.sh` | Statik + davranış kapısı koşucusu |

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| Kayıt-başlatma **kararı** + `channels` **üretimi** + consent + tamamen kapatma | 11.1 (recording-policy; **tüketilir**) |
| Kayıt **byte** yazımı / codec / nesne depolama / KMS | SAD §10.2 Recording Pipeline + DB §8 (layout **kararı** verilir, medya **yazılmaz**) |
| Transkript üretimi | 11.3 |
| PII redaction pipeline (FR-REC-004) | 11.4 (`redaction_required` taşınır; DUAL'da kanal-bazlı redaction mümkün) |
| Kart/parola/OTP çıkarma (FR-REC-005) | 11.5 |
| Kayıt/transkript erişim audit (FR-REC-009) | 11.6 (bu modül **karar** audit'ini üretir) |
| Retention / legal-hold / silme (FR-REC-006/007/010) | retention motoru |
| Residency depolama **uygulaması** | DB §8 / SAD §12.1 (residency **kararı** verilir) |

## Notlar

- **Vendor-neutral** (ADR-001/002/012); kayıt depolama + codec sağlayıcı bağımsız.
- **Sır/credential ve gerçek PII** (müşteri adı/telefon/ham ses/transkript) **repoya yazılmaz** —
  yalnız yapısal kimlikler + enum + kanal sayısı. Canlı kanal kaydı yalnız `${CHANNEL_RECORDING_URL}`.
- İskelet kapısı; canlı Recording Pipeline (SAD §10.2) byte yazımı + DB §22 `recording` satırı + nesne
  depolama/residency (DB §8) + PII redaction (11.4) entegrasyonu F1'de dolar.
- SRS/RTM/BRD değişmedi — RTM zaten `FR-REC-003 → SR-REC-003 → TC-REC-003 (I) → 11.2` eşler;
  yeni FR/SR eklenmedi.
