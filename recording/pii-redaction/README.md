# WBS 11.4 — PII redaction pipeline (async)

**Faz:** F1 · **Öncelik:** Must · **İz:** BRD §9.14 → FR-REC-004 → SR-REC-004 → TC-REC-004

11. workstream'in (Kayıt, Transkript & PII Redaction) **PII redaction pipeline** modülü.
**11.3 (transcript-build)** transkripti (zaman-sıralı/konuşmacı-atflı segmentler + `redaction_state ∈
{pending, not_required}`) ÜRETTİKTEN **sonra**, bu modül sezilen **PII span**'lerini (kategori + segment-içi
offset; **ham değer YOK** — STT/PII-dedektör sağlar) alır → **deterministik, fail-closed, asenkron** bir
**redaction PLANI** (her span için maskeleme direktifi `{seq, category, start, length, masked_token,
delegated_to}`) üretir + transkript **`redaction_state` pending→redacted** geçişini yönetir ve terminal
karar verir: **`REDACTED` | `NOT_REQUIRED` | `NO_CONTENT` | `BLOCK`**.

Modül **Analytics Plane asenkron** post-processing'tir (SAD §10.1/§10.2 PII Redaction; SAD §19.2 *"PII
redaction pipeline (Analytics Plane, async)"*; **FR-RES-011** — hot-path değil; ADR-004/007). **Kart/parola/
OTP** gizli-değer kategorilerini (`card_pan/cvv/otp/password`) **maskeler** ve **11.5**'e (FR-REC-005)
**devreder** (`delegated_to=11.5`: kayıttan çıkarma + dedeksiyon kuralları 11.5'in). Redaction tamamlanınca
transkript **görüntülemeye-hazır** (`access_ready`) olur — görüntüleme **yetkisi** (`transcript:read`,
FR-REC-008) **11.6**'da.

## Karar akışı

```
PiiRedactionRequest ─tenant─► içerik kapısı ─► input_state ─► async ─► maskele ─► no-leak ─► pending→redacted
      ├─ cross-tenant ─────────────────────────────────────────────────► BLOCK (cross_tenant)          [K12]
      ├─ upstream yok/geçersiz ───────────────────────────────────────► BLOCK (no_upstream)
      ├─ içerik yok (upstream ≠ TRANSCRIPT) ─────────────────────────► NO_CONTENT (no content)          [K6]
      ├─ redacted girdi / not_required+span / malformed span ────────► BLOCK (invalid_redaction_input)  [K5]
      ├─ not_required ∧ span yok ─────────────────────────────────────► NOT_REQUIRED (maskeleme gerekmez)
      └─ pending ──────────────────────────────────────────────────────► REDACTED (tüm span maskeli)   [K2/K3/K4]
```

**Çekirdek garanti (K2, FR-REC-004):** sezilen **her** PII span maskeleme direktifi alır — `unredacted_pii = 0`.
**Çekirdek garanti (K3):** `redaction_state_out == 'redacted' ⇒ unredacted_pii = 0` (residüel PII varken
`redacted` = `false_redacted`); geri-düşme (`state_regression`) yasak.
**Çekirdek garanti (K4, BRD §17.7):** plan/audit/metrik **yalnız** maskeli token (`[CATEGORY]`) + kategori +
offset taşır — **ham PII değeri** hiçbir alanda yok (`pii_leak = 0`).
**Çekirdek garanti (K6, FR-REC-002 aşağı akış):** `upstream ≠ TRANSCRIPT ⇒ no_content_persisted = true`.

## İnvariant'lar (K1–K12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| K1 | | Determinizm/terminal; `stuck_state=0` |
| **K2** | FR-REC-004 | Redaction tamlığı: her PII span maskeleme direktifi alır; `unredacted_pii=0` |
| **K3** | DB §21 | Durum geçişi: `redacted ⇒ unredacted_pii=0` (`false_redacted=0`); geri-düşme `state_regression=0` |
| **K4** | FR-REC-004 / BRD §17.7 | Ham PII yok: plan/audit/metrik yalnız maskeli token+kategori+offset; `pii_leak=0` |
| **K5** | SR-REC-004 | ATLANAMAZ: bypass=`redaction_skip`; pending access-ready değil; malformed→BLOCK (`failopen=0`) |
| **K6** | FR-REC-002 | İçerik kapısı: `upstream≠TRANSCRIPT ⇒ no content`; `over_capture=0` |
| K7 | NFR 10.7 | Residency: redaksiyonlu transkript home-region'da |
| **K8** | FR-RES-011 | Asenkron / hot-path dışı: `execution_plane=analytics_async`; `hotpath_violation=0` |
| K9 / K10 | FR-IAM-006 | Kanıt + audit (ham PII değeri yok) |
| K11 | FR-REC-004 | Gözlemlenebilirlik düşük-kardinalite + ham PII yok |
| K12 | FR-TEN-002 | Sır/ham-PII yok + tenant izolasyonu |

## PII kategorileri

- **Genel (owner 11.4 — maskeler + `redacted` üretir):** `phone`, `email`, `national_id`, `iban`,
  `account_number`, `person_name`, `address`, `dob`, `plate`.
- **Gizli-değer (owner 11.5 — FR-REC-005; bu modül **maskeler** + **devreder** `delegated_to=11.5`):**
  `card_pan`, `cvv`, `otp`, `password`.
- Her kategori kanonik **bracket-token** ile maskelenir (`[PHONE]`, `[CARD]`, …); `masked_token`
  deseni `^\[[A-Z0-9_]+\]$`. Partial reveal (last4) **display** katmanı işidir (DB §8).

## Çalıştırma

```bash
./run_live_test.sh                                  # tüm kapılar (statik)
python3 pii_redaction_probe.py validate             # statik spec/config/kapsama
python3 pii_redaction_probe.py selftest             # gömülü davranış (K1–K12)
python3 pii_redaction_probe.py check samples        # 12 pass + 11 degrade
python3 pii_redaction_probe.py schema               # karar sözleşmesi
python3 tests/pii_redaction_behavior_test.py        # bağımsız davranış testi
```

**Durum:** validate **105/105** 🟢 · selftest **83/83** 🟢 · check **23/23** 🟢 (11 degrade beklendiği gibi
elendi) · behavior **75/75** 🟢.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `pii-redaction-spec.json` | Kaynak doğruluk: kurallar, karar, pii_categories, redaction_states, execution, invariant'lar K1–K12, kapılar, izlenebilirlik |
| `pii_redaction_probe.py` | stdlib-only motor: `validate` / `check` / `selftest` / `schema` |
| `config/pii-redaction.json` | PII kategori→maskeli token + owner/devir (11.5) + accepted/producible redaction_states + execution_plane |
| `samples/*.json` | 12 pass + 11 degrade senaryo (FR-TST-008) |
| `tests/pii_redaction_behavior_test.py` | Bağımsız davranış testi |
| `run_live_test.sh` | Statik + davranış kapısı koşucusu |

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| Kayıt/içerik **kararı** + consent + tamamen kapatma | 11.1 (recording-policy) |
| Kanal/track yerleşimi + `channels` + konuşmacı-kanal | 11.2 (channel-recording) |
| Transkript **üretimi** (segment/timeline/sıralama/atıf) + `redaction_state=pending` işareti | 11.3 (transcript-build; **tüketilir**) |
| **Kart/parola/OTP** gizli-değer **dedeksiyon kuralları** + **kayıttan** çıkarma (FR-REC-005) | 11.5 (transkript span'leri **maskelenir** + **devredilir** `delegated_to=11.5`) |
| PII **dedeksiyon** (NER/regex span çıkarımı) | STT/PII-dedektör (sezilen span **tüketilir**; ADR-002 sağlayıcı-soyut) |
| Ham transkript **METİN byte**'ına maskeleme **uygulaması** + `storage_uri` yazımı | SAD §10.2 PII Redaction + DB §21 (redaction **planı** + state **kararı** verilir, ham metin **yazılmaz/görülmez**) |
| Kayıt/transkript erişim audit + dinleme/**görüntüleme** yetkisi (FR-REC-008/009) | 11.6 (`transcript:read`; `access_ready` + **karar** audit'i bu modülden) |
| Retention / legal-hold / silme (FR-REC-006/007/010) | retention motoru |
| Residency depolama **uygulaması** | DB §8 / SAD §12.1 (residency **kararı** verilir) |
| Panel **maskeli sunum** | L2 **A-12 / A-13** (PII redaction panel görüntülemede de uygulanır, BRD §17) |

## Notlar

- **Vendor-neutral** (ADR-001/002/004/007/012); PII dedektör + STT + transkript depolama bağımsız;
  redaction Analytics Plane'de **asenkron** (ADR-004 plane ayrımı, FR-RES-011).
- **Sır/credential ve gerçek PII** (telefon/kart/OTP/parola/ad/adres/hesap no **değeri** / transkript
  metni / ham ses) **repoya yazılmaz** — yalnız kategori **enum** + **offset** + **maskeli token** +
  yapısal kimlikler. **Redaction'ın amacı tam olarak budur.** Canlı redaction yalnız `${PII_REDACTION_URL}`.
- İskelet kapısı; canlı **PII Redaction pipeline** (SAD §10.2) ham metin byte maskeleme + DB §21
  `redaction_state` yazımı + PII-dedektör span çıkarımı + nesne depolama/residency (DB §8) + 11.5 kart/
  parola/OTP devri entegrasyonu F1'de dolar.
- SRS/RTM/BRD/SAD değişmedi — RTM zaten `FR-REC-004 → SR-REC-004 → TC-REC-004 → 11.4` eşler; yeni FR/SR
  eklenmedi. Bu modül **transkript PII redaction** boyutunu (FR-REC-004) sahiplenir; kart/parola/OTP
  gizli-değer dedeksiyon+kayıttan-çıkarmayı (FR-REC-005) **11.5** tamamlar.
