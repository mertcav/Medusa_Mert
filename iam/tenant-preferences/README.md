# WBS 12.4.4 — Tenant dil/saat dilimi/bölge/saklama tercihi (L1)

**Faz:** F1 · **Öncelik:** Must · **İz:** **FR-TEN-004** (Tenant bazında dil, saat dilimi, veri bölgesi ve saklama politikası seçilebilmelidir) · DB.md §5.1 (`tenant` — `default_locale`/`timezone`/`home_region`/`retention_profile`) · DB.md §9 (`retention_policy` — tenant + `data_class` → `retain_days`; FR-REC-006/007/010) · BRD §17 (tenant'a özel dil/bölge/saklama tercihleri **L1 Tenant Admin Console**) · NFR 10.7 (residency UK/EU/NA/ME) · DPIA §5.4 (`cp.residency.*`) / §5.5 (`cp.retention.*`) / §8 (most-restrictive-wins + tenant-override-yalnız-sıkılaştırır) · FR-TEN-002 (tenant izolasyonu) · SR-TEN-004 → TC-TEN-004 · ADR-011/012

12. workstream'in (IAM & Erişim) **tenant tercih** modülü. FR-TEN-004'ü sahiplenir. **ÇEKİRDEK FARK:**
bu **L1** (Tenant Admin Console; `tenant` realm + `tenant_application_plane`) yüzeyidir — 12.4.1 (tenant CRUD) ve
12.4.2 (dedicated vs shared) **L0** (platform) iken bu **L1** (sibling 12.4.3 org yapısı gibi): tenant **kendi**
dil/saat dilimi/veri bölgesi/saklama tercihini uygular, L0 görmez (FR-IAM-008 altın kural). Tercihi
**deterministik, fail-closed** bir **BAĞLAMA (binding) kararı** olarak yönetir. Bir `PreferenceRequest` için
terminal: **`COMMIT` | `REJECT`**.

## Tercih kategorileri (FR-TEN-004)

| Kategori | TR | Hedef (DB.md) | Açıklama |
|----------|----|----|----|
| `locale` | dil | `tenant.default_locale` | BCP-47 dil etiketi (tr-TR, en-US, …) |
| `timezone` | saat dilimi | `tenant.timezone` | IANA tz adı (Europe/Istanbul, …) |
| `residency` | veri bölgesi | `tenant.home_region` | NFR 10.7 UK/EU/NA/ME (tenant izinli içinde) |
| `retention` | saklama politikası | `retention_policy.retain_days` / `tenant.retention_profile` | data_class başına saklama günü (compliance asgari üstü) |

## İşlemler

| İşlem | Açıklama | Mutasyon (WORM audit) |
|-------|----------|------------------------|
| `set` | Tercih değerini uygula (FR-TEN-004 "seçilebilmelidir"; SR-TEN-004 "runtime'a uygulanır") | ✓ |
| `read` | Tercihi oku | — (mutasyon değil) |

## Kategori → permission-key (12.1.2 katalog; yeni anahtar **icat edilmez**)

| Kategori | Permission-key | Gerekçe |
|----------|----------------|---------|
| `locale` | `compliance:manage` | Şeffaflık/AI-disclosure dili (DPIA `cp.transparency`) |
| `timezone` | `compliance:manage` | Outbound calling-hours yorumu (DPIA `cp.outbound`) |
| `residency` | `compliance:manage` | Veri bölgesi (DPIA `cp.residency` §5.4) |
| `retention` | `retention:manage` | Saklama politikası (DPIA `cp.retention` §5.5; FR-REC-006) |

> Tenant-genel tercihler yasal/uyumluluk etkili (disclosure dili, calling-hours, residency, saklama)
> olduğundan compliance-yetkili roller yönetir: `tenant_owner` ve `security_compliance_officer` her iki
> anahtarı da taşır (12.1.1/ADR-012). v1'de ayrı bir genel "settings:manage" anahtarı icat edilmez — mevcut
> kataloğun anahtarları kullanılır.

## Karar akışı (gate)

```
PreferenceRequest ─malformed─► tenant_isolation ─► authz ─► validity ─► residency ─► retention_floor ─► change_guard ─► audit
      ├─ request_id/op/realm/plane eksik|geçersiz | set'te category|value eksik ──────────► REJECT (malformed)
      ├─ ¬(tenant ∧ tenant_application_plane ∧ own_tenant) ─► REJECT  [commit ⇒ cross_tenant_op      R2]
      ├─ perm_of(category) ∉ actor_permissions ────────────► REJECT  [commit ⇒ unauthorized_op       R3]
      ├─ ¬valid_preference(category,value) ────────────────► REJECT  [commit ⇒ invalid_preference    R4]
      ├─ residency ∧ region ∉ tenant_allowed ──────────────► REJECT  [commit ⇒ residency_violation   R5]
      ├─ retention ∧ retain_days < compliance_min ─────────► REJECT  [commit ⇒ retention_violation   R6]
      ├─ heavy_change ∧ ¬confirm ──────────────────────────► REJECT  [commit ⇒ unsafe_change         R7]
      └─ mutating ∧ ¬audit ────────────────────────────────► REJECT  [commit ⇒ missing_audit         R8]
```

## İnvariant'lar (R1–R11)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **REJECT** (fail-closed); kanıt; `model_hash` sha256; `stuck_state`/`missing_evidence=0` |
| **R2** | **FR-TEN-002** | **Tenant izolasyonu:** tercih YALNIZ `tenant` realm + `tenant_application_plane` (L1) + aktör KENDİ tenant'ı (self-row; actor tenant_id == target_tenant_id); yanlış realm / cross-tenant `cross_tenant_op=0` (12.2.3 RLS resiprokal) |
| **R3** | **ADR-012** | **Yetkilendirme:** kategori permission-key gerektirir (locale/timezone/residency→`compliance:manage`, retention→`retention:manage`); yetkisiz commit `unauthorized_op=0` |
| **R4** | **DB.md §5.1/§9** | **Tercih geçerliliği:** `category` ∈ {locale,timezone,residency,retention} + değer geçerli (locale ∈ supported, timezone ∈ IANA, region ∈ UK/EU/NA/ME, retention data_class CHECK + retain_days int>0); geçersiz commit `invalid_preference=0` |
| **R5** | **NFR 10.7 / DPIA §8** | **Residency:** `home_region` tenant izinli bölge kümesinde + UK/EU/NA/ME (**yalnız-daraltır** — most-restrictive-wins); dışında commit `residency_violation=0` |
| **R6** | **DPIA §5.5/§8** | **Retention tabanı:** `retain_days` ≥ data_class için compliance asgari (tenant override **yalnız sıkılaştırır** — yasal asgarinin altına inemez; FR-REC-006); altında commit `retention_violation=0` |
| **R7** | **FR-REC-010 / SAD §12.3** | **Değişim koruması:** residency değişimi (veri taşıma) VEYA retention kısaltma (geri-döndürülemez silme) `confirm` gerektirir; korumasız commit `unsafe_change=0` |
| R8 | FR-REC-009 | **WORM audit:** her mutasyon `audit_log`'a (12.1.8); `missing_audit=0` |
| R9 | ADR-011 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi (residency narrowing kaldır / retention taban düşür / cross-tenant tercih) yakalanır; `model_tampered=0` |
| R10 | 0.4.7 | Gözlemlenebilirlik kardinalite: op/result/category düşük-kard; tenant_id/request_id yalnız trace; PII (tercih değeri) label değil |
| R11 | BRD §17.7 | Sır/içerik yok: yalnız op/category/realm/plane enum + permission-key + locale/tz/region/data_class enum + retain_days/min_days sayı + slug kimlik + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.4.x deseniyle birebir: motor **doğru** tercih kararını hesaplar, `inject` doğru davranışı
**bozar** (unsafe koşulu + commit zorlar) ve eşleşen ihlal sayacını artırır → kapı eler. 9 enjeksiyon:
`cross_tenant`, `wrong_realm`, `drop_permission`, `invalid_value`, `residency_drift`, `retention_loosen`,
`unsafe_change`, `skip_audit`, `model_tamper`.

**Anahtar ayrım:** geçersiz-değer / izinli-dışı-residency / asgari-altı-retention / korumasız-değişim op'unun
**REJECT'i DOĞRU çıktıdır** (ihlal değil — kapı geçer). İhlal sayacı YALNIZ unsafe koşul **+ commit** birlikte
olunca artar (ör. `tp-pass-reject-*` = motor doğru reddetti; `tp-degrade-*` = bozulup yine commit etti).

## Most-restrictive-wins (DPIA §8) bağı

- **Residency (R5):** `tenant_allowed_regions` tenant'ın etkin compliance profile çözümlemesinden gelen
  **izinli** bölge kümesidir (ülke profili ⊕ sektörel overlay ⊕ tenant override). Tenant bu set **içinde**
  seçer — set dışına çıkamaz (yalnız-daraltır).
- **Retention (R6):** `compliance_min_days` ilgili data_class için **yasal asgari** gündür (`cp.retention.*`).
  Tenant override **yalnız sıkılaştırır** — asgariyi gevşetemez (DPIA §8 "retention kısaltma yasal asgarinin
  altına engellenir").
- **Çözümleme (resolver)** DPIA/compliance-profile motorunun sahipliğindedir; bu modül **çözülmüş sınırı**
  (`tenant_allowed_regions` + `compliance_min_days`) **girdi** olarak tüketir.

## Dosyalar

- `config/tenant-preferences-model.json` — **frozen** model (`categories`[locale/timezone/residency/retention] +
  `operations`[set/read; mutating 1] + `op_permission.by_category`[compliance:manage/retention:manage] +
  `tenant_scope`[kendi tenant self-row] + `value_validity`[supported locale/IANA tz/UK-EU-NA-ME/retention data_class]
  + `residency`[home_region tenant izinli; UK/EU/NA/ME; narrowing-only] + `retention`[retain_days ≥ compliance asgari;
  tenant override yalnız sıkılaştırır] + `change_guard`[residency değişimi/retention kısaltma → confirm] +
  `audit`[WORM] + `compliance_profile_link`[DPIA §8 most-restrictive-wins] + `data_class`[retention_policy=tenant_config, 12.2.4]).
- `tenant-preferences-spec.json` — makine-okunur spec (8 kural + karar + R1–R11 + kapılar).
- `tenant_preferences_probe.py` — tercih karar motoru + `validate`/`check`/`selftest`/`schema`.
  12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 **resiprokal** bağlantılarını doğrular.
- `samples/` (22: 13 pass + 9 degrade) + `tests/` (bağımsız R1–R11) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tenant_preferences_probe.py validate          # statik model + spec + 12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 resiprokal
python3 tenant_preferences_probe.py selftest          # R1–R11 motoru
python3 tenant_preferences_probe.py check samples     # 13 pass + 9 degrade
python3 tests/tenant_preferences_behavior_test.py     # bağımsız R1–R11
./run_live_test.sh                                    # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| Tenant CRUD + yaşam döngüsü durum makinesi (home_region/locale/timezone **provisioning**) | 12.4.1 |
| Dedicated vs shared izolasyon sınıfı (L0) | 12.4.2 |
| Org yapısı (marka/departman/ülke/proje) (L1) | 12.4.3 |
| Compliance profile **çözümleme** (ülke ⊕ overlay ⊕ override; most-restrictive-wins) | DPIA / compliance-profile motoru |
| Retention motoru **gerçek silme** yürütme (FR-REC-010) | F1 kod (WBS 1.2.3) + ops runbook |
| Residency **veri migrasyonu** yürütme | F1 kod + ops runbook |
| PostgreSQL RLS çalışma-anı zorlama / çift-kontrol | 12.2.3 |
| rol→permission-key bundle / permission katalog | 12.1.1 / 12.1.2 |
| WORM / append-only audit **akışı** | 12.1.8 |
| L0 ⟂ tenant iş verisi repository bağımsızlığı | 12.2.4 |
| L1 OpenAPI/UI (T-01/T-02 Tenant Ayarları ekranı) | 13.3.x |

## Notlar

- **Vendor-neutral** (ADR-002/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (DB şifresi / connection string) ve ham içerik (müşteri PII) repoya yazılmaz** — yalnız
  op/category/realm/plane enum + permission-key + locale/tz/region/data_class enum + retain_days/min_days sayı +
  slug tenant/request kimlik + sha256.
- `tenant` tablosu repo-sınıfı=`platform` (L0 sağlar) **ama** tercih alt-kümesi (`default_locale`/`timezone`/
  `home_region`/`retention_profile`) tenant'ın **kendi self-row'unda** L1-düzenlenebilir (FR-TEN-002 self-row;
  RLS `tenant_id=id`); `retention_policy` tablosu veri-sınıfı=`tenant_config` (12.2.4 resiprokal).
- Gerçek L1 tercih sağlama (tenant tercih alanı + `retention_policy` CRUD + retention motoru + residency
  migrasyon + L1 OpenAPI/UI) **F1 kod / 13.3.x aşamasında**; bu modül onlara kararı + kanıtı + model bütünlük
  manifestini iletir.
