# WBS 11.1 — Kayıt politikası (tenant/ülke/use-case) + tamamen kapatma

**Faz:** F1 · **Öncelik:** Must · **İz:** FR-REC-001, FR-REC-002 → SR-REC-001, SR-REC-002 → TC-REC-001, TC-REC-002

11. workstream'in (Kayıt, Transkript & PII Redaction) **kayıt politikası (recording-policy)** modülü.
Bir çağrı kaydı başlatılırken (inbound/outbound) **etkin kayıt politikasını üç katmanda çözer**
(ülke compliance profili × tenant override × use-case overlay — *most-restrictive-wins*) ve bir terminal
karar verir: **`RECORD` | `DISABLED` | `NO_CONSENT` | `BLOCK`**.

İki çekirdek gereksinim:

- **FR-REC-001** — Kayıt politikası **tenant, ülke ve use-case** bazında belirlenir (üç katman).
- **FR-REC-002** — Ses kaydı **tamamen kapatılabilir**: herhangi bir katman `recording_enabled=false`
  ⇒ `DISABLED` ve **hiçbir medya yakalanmaz/saklanmaz** (`no_media_captured=true`).
  SR-REC-002 kabul ölçütü: *"Kayıt kapalıyken hiçbir medya saklanmaz."*

Modül **deterministik, fail-closed / privacy-safe (NO-RECORD)** bir karar fonksiyonudur — belirsizlikte
kayıt YAPILMAZ.

## Karar akışı

```
RecordingPolicyRequest ─ülke profil çöz─► üç-katman most-restrictive ─► killswitch ─► consent kapısı
      ├─ profil çözülemez ──────────────────────────────────────────► BLOCK (unknown_profile)   [K7]
      ├─ cross-tenant ──────────────────────────────────────────────► BLOCK (cross_tenant)       [K12]
      ├─ recording_enabled=false (herhangi katman) ────────────────► DISABLED (no media)         [K3]
      ├─ consent/notice kapısı geçilemedi ─────────────────────────► NO_CONSENT (no media)        [K4]
      └─ etkin ∧ kapı geçildi ──────────────────────────────────────► RECORD (recording_allowed)
```

**Çekirdek garanti (K5, SR-REC-002):** `terminal ≠ RECORD ⇒ no_media_captured = true`.

### Üç-katman çözüm (most-restrictive-wins, K2)
`effective = most_restrictive(country_profile, use_case_overlay, tenant_override)`:
- `recording_enabled = AND` (herhangi katman kapatırsa → kapalı)
- `consent_model = max(notice < explicit_optin < all_party)` (en katı)
- `notice_required = OR`, `in_region_storage_required = OR`
- Tenant override **yalnız sıkılaştırır**; gevşetme (`loosen_consent_model`) yasaktır.

### Kayıt-başlatma consent/notice kapısı (K4, DPIA §5.2)
- `notice` → kayıt bildirimi çalınmalı (`recording_notice_played`)
- `explicit_optin` → açık rıza (`consent_state == granted`)
- `all_party` → tüm taraflar rıza (`all_party_consent ∧ granted`)
- + `notice_required ⇒ notice_played`

## İnvariant'lar (K1–K12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| K1 | | Determinizm/terminal; stuck_state=0 |
| **K2** | FR-REC-001 | Üç-katman most-restrictive politika çözümü (ülke × tenant × use-case) |
| **K3** | FR-REC-002 | Tamamen kapatma: `recording_enabled=false ⇒ DISABLED ∧ no media` |
| **K4** | DPIA §5.2 | Kayıt-başlatma consent kapısı (notice/explicit_optin/all_party); gevşetme yasak |
| **K5** | SR-REC-002 | Kapalıyken medya yok: `terminal≠RECORD ⇒ no_media_captured=true` |
| K6 | NFR 10.7 | Residency: RECORD home-region'da saklanır |
| K7 | | Fail-closed bilinmeyen profil (privacy-safe NO-RECORD) |
| **K8** | SR-REC-001/002 | ATLANAMAZ: bypass = `policy_skip` = BRD §15 alarmı |
| K9 / K10 | FR-IAM-006 | Kanıt + audit (ham PII yok) |
| K11 | FR-REC-004 | Gözlemlenebilirlik düşük-kardinalite + PII yok |
| K12 | FR-TEN-002 | Sır/PII yok + tenant izolasyonu |

## Çalıştırma

```bash
./run_live_test.sh                              # tüm kapılar (statik)
python3 recording_policy_probe.py validate      # statik spec/config/kapsama
python3 recording_policy_probe.py selftest       # gömülü davranış (K1–K12)
python3 recording_policy_probe.py check samples  # 12 pass + 11 degrade
python3 recording_policy_probe.py schema         # karar sözleşmesi
python3 tests/recording_policy_behavior_test.py  # bağımsız davranış testi
```

**Durum:** validate **80/80** 🟢 · selftest **75/75** 🟢 · check **23/23** 🟢 (11 degrade beklendiği gibi
elendi) · behavior **74/74** 🟢.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `recording-policy-spec.json` | Kaynak doğruluk: kurallar, karar, invariant'lar K1–K12, kapılar, izlenebilirlik |
| `recording_policy_probe.py` | stdlib-only motor: `validate` / `check` / `selftest` / `schema` |
| `config/recording-policies.json` | Ülke profilleri (TR/UK/EU/US) + use_case overlay'leri (mühendislik varsayılanı) |
| `samples/*.json` | 12 pass + 11 degrade senaryo (FR-TST-008) |
| `tests/recording_policy_behavior_test.py` | Bağımsız davranış testi |
| `run_live_test.sh` | Statik + davranış kapısı koşucusu |

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| Tek/çift kanallı kayıt **üretimi** (FR-REC-003) | 11.2 (`channels` attribute taşınır) |
| Transkript üretimi | 11.3 |
| PII redaction pipeline (FR-REC-004) | 11.4 (`redaction_required` işaretlenir) |
| Kart/parola/OTP çıkarma (FR-REC-005) | 11.5 |
| Kayıt/transkript erişim audit (FR-REC-009) | 11.6 (bu modül **karar** audit'ini üretir) |
| Retention / legal-hold / silme (FR-REC-006/007/010) | retention motoru (`retention_days` taşınır) |
| Compliance profile **çözümleme** motoru | DPIA §5 / SAD §19.3 (değerleri **tüketir**) |
| Consent **kaydı** | consent:manage + 10.2.1 (`consent_state` **okunur**) |
| Kayıt bildirimi **çalma** (BRD §14.2) | orchestrator açılış turu (`notice_played` **okunur**) |
| Recording Pipeline kayıt yazımı / depolama / KMS | SAD §10.2 / DB §8 (karar verilir, yazılmaz) |

## Notlar

- **Vendor-neutral** (ADR-001/002/012); kayıt depolama + residency sağlayıcı bağımsız.
- **Sır/credential ve gerçek PII** (müşteri adı/telefon/ham ses/transkript) **repoya yazılmaz** —
  yalnız yapısal kimlikler + enum + bayrak. Canlı kayıt-başlatma çağrısı yalnız `${RECORDING_POLICY_URL}`.
- Config değerleri **mühendislik varsayılanı**; counsel onayına + pilot tenant + compliance profile (F1)
  ile kalibre edilir.
- İskelet kapısı; canlı Recording Pipeline + compliance profile + consent/bildirim entegrasyonu F1'de dolar.
