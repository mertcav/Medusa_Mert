# WBS 12.4.2 — Dedicated vs shared tenant (L0)

**Faz:** F2 · **Öncelik:** Should · **İz:** **FR-TEN-005** (Dedicated tenant ve shared tenant seçenekleri desteklenmelidir) · SAD §13.1 (izolasyon modeli) · ADR-006 (shared [RLS] varsayılan + dedicated opsiyon) · DB.md §5.1 (`tenant.isolation_mode` CHECK [shared/dedicated]) + §6 (dedicated modda da tenant RLS aynıdır) · NFR 10.6 (tenant başına ayrı KMS key) · NFR 10.7 (residency UK/EU/NA/ME) · FR-IAM-008 (L0 ⟂ tenant realm) · FR-BIL-005 (dedicated ayrı faturalama) · SR-TEN-005 → TC-TEN-005 · ADR-011/012

12. workstream'in (IAM & Erişim) **L0 tenant izolasyon-sınıfı** modülü. FR-TEN-005'i sahiplenir; **12.4.1**
(tenant CRUD/provisioning) izolasyon **sınıfının** seçimi/sağlanmasını **buraya DELEGE eder**. Tenant izolasyon
sınıfını **deterministik, fail-closed** bir **BAĞLAMA (binding) kararı** olarak yönetir. Bir `IsolationRequest`
için terminal: **`COMMIT` | `REJECT`**.

## İki izolasyon sınıfı (SAD §13.1, ADR-006)

| Sınıf | İzolasyon | Runtime yüzeyi | DB | KMS | Kullanım |
|-------|-----------|----------------|----|----|---------|
| **`shared`** (varsayılan) | Mantıksal | `shared_pool` (tek runtime havuzu) | RLS (tenant_id) | tenant başına ayrı key | Maliyet-etkin çoğunluk |
| **`dedicated`** | Fiziksel/ayrılmış | `dedicated_namespace` / `dedicated_cluster` | **RLS + ayrı altyapı** | tenant başına ayrı key | Regüle sektör / büyük müşteri (Faz 2/3); ayrı faturalanır (FR-BIL-005) |

> **Anahtar:** dedicated, RLS'i **KALDIRMAZ** — fiziksel ayrım RLS'in *yerine* geçmez, ona **eklenir** (DB.md §6
> "dedicated modda da tenant RLS … aynıdır"; savunma-derinliği). Tenant başına **ayrı KMS key** (NFR 10.6) ve
> **residency** (NFR 10.7) **her iki modda** korunur — izolasyon modu bu izolasyonların yerine geçmez.

## İşlemler

| İşlem | Açıklama | Mutasyon (WORM audit) |
|-------|----------|------------------------|
| `assign` | Create sırasında mod ata (12.4.1'den delege) | ✓ |
| `provision_surface` | Somut izolasyon yüzeyini sağla (shared_pool+RLS / dedicated namespace/cluster) | ✓ |
| `migrate` | Modu değiştir (shared↔dedicated) — `migration_plan`+`confirm` gerektirir | ✓ |
| `read` | İzolasyon sınıfını oku | — (mutasyon değil) |

İzolasyon sınıfı seçimi/değişimi **yalnız** L0 (`platform` realm + `platform_control_plane`; FR-IAM-008/ADR-011)
ve **`tenant:provision`** permission-key (12.1.2 katalog; `platform_owner` bundle 12.1.1/ADR-012) ile yürütülür.

## Karar akışı (gate)

```
IsolationRequest ─malformed─► realm/plane ─► authz ─► mode_surface ─► dedicated_sep ─► rls ─► kms ─► residency ─► audit
      ├─ request_id/op/realm/plane/isolation_mode eksik|geçersiz ───────────────────────► REJECT (malformed)
      ├─ ¬(platform ∧ platform_control_plane) ──────────────► REJECT  [commit ⇒ cross_realm_op          R2]
      ├─ tenant:provision ∉ actor_permissions ─────────────► REJECT  [commit ⇒ unauthorized_op         R3]
      ├─ ¬valid_mode_surface(mode,placement,migrate) ──────► REJECT  [commit ⇒ mode_surface_mismatch   R4]
      ├─ dedicated ∧ placement=shared_pool ────────────────► REJECT  [commit ⇒ dedicated_in_shared_pool R5]
      ├─ ¬rls_enabled ─────────────────────────────────────► REJECT  [commit ⇒ rls_waived             R6]
      ├─ ¬kms_distinct ────────────────────────────────────► REJECT  [commit ⇒ shared_kms_key         R7]
      ├─ surface_region ≠ home_region ─────────────────────► REJECT  [commit ⇒ residency_mismatch     R8]
      └─ mutating ∧ ¬audit ────────────────────────────────► REJECT  [commit ⇒ missing_audit          R9]
```

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **REJECT** (fail-closed); kanıt; `model_hash` sha256; `stuck_state`/`missing_evidence=0` |
| **R2** | **FR-IAM-008** | **Realm izolasyonu:** izolasyon sınıfı seçimi YALNIZ `platform` realm + `platform_control_plane`; tenant realm değiştirirse `cross_realm_op=0` |
| **R3** | **ADR-012** | **Yetkilendirme:** op `tenant:provision` gerektirir; yetkisiz commit `unauthorized_op=0` |
| **R4** | **ADR-006/SAD §13.1** | **Mod→yüzey bağlaması:** `isolation_mode`∈{shared,dedicated} + yüzey moda eşlenir (shared⇒shared_pool / dedicated⇒namespace,cluster) + migrate korumalı; `mode_surface_mismatch=0` |
| **R5** | **SAD §13.1** | **Dedicated ayrım:** dedicated tenant `shared_pool`'a yerleşemez; `dedicated_in_shared_pool=0` |
| **R6** | **DB.md §6** | **RLS her iki modda:** dedicated RLS'i kaldırmaz (savunma-derinliği; 12.2.3); `rls_waived=0` |
| **R7** | **NFR 10.6** | **Tenant-başına KMS:** her iki modda tenant kendi `kms_key_ref`'ini alır; `shared_kms_key=0` |
| **R8** | **NFR 10.7** | **Residency tutarlılığı:** `surface_region == home_region`; `residency_mismatch=0` |
| R9 | FR-REC-009 | **WORM audit:** her mutasyon `audit_log`'a (12.1.8); `missing_audit=0` |
| R10 | ADR-006/011 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi (RLS'i opsiyonel yapma / dedicated'ı shared_pool'a izin verme) yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: op/result/isolation_mode/runtime_placement/actor_realm düşük-kard; tenant_id/request_id/kms_key_ref yalnız trace; PII metrikte yok |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız op/mode/placement/realm/plane enum + permission-key + region enum + slug kimlik + `kms_key_ref` **referansı** (materyal değil) + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.4.1 deseniyle birebir: motor **doğru** izolasyon-sınıfı kararını hesaplar, `inject` doğru
davranışı **bozar** (unsafe koşulu + commit zorlar) ve eşleşen ihlal sayacını artırır → kapı eler. 10 enjeksiyon:
`cross_realm`, `drop_permission`, `mode_mismatch`, `ungoverned_migration`, `dedicated_on_shared`, `waive_rls`,
`share_kms`, `residency_drift`, `skip_audit`, `model_tamper`.

**Anahtar ayrım:** uyumsuz-yüzey / dedicated-shared-havuzda / korumasız-migrate op'unun **REJECT'i DOĞRU
çıktıdır** (ihlal değil — kapı geçer). İhlal sayacı YALNIZ unsafe koşul **+ commit** birlikte olunca artar (ör.
`ic-pass-reject-*` = motor doğru reddetti; `ic-degrade-*` = bozulup yine commit etti).

## Dosyalar

- `config/isolation-class-model.json` — **frozen** model (`isolation_modes`[shared default/dedicated] +
  `operations`[4; mutating 3] + `op_permission` + `surface_binding`[shared⇒shared_pool / dedicated⇒namespace,cluster]
  + `rls`[her iki modda zorunlu] + `kms`[her iki modda tenant başına] + `residency`[surface==home_region; UK/EU/NA/ME]
  + `migration`[plan+confirm] + `audit`[WORM] + `billing`[dedicated ayrı] + `data_class`[isolation_mode=platform, 12.2.4]).
- `tenant-isolation-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + kapılar).
- `tenant_isolation_probe.py` — izolasyon-sınıfı karar motoru + `validate`/`check`/`selftest`/`schema`.
  12.4.1/12.2.3/12.1.2/12.1.1/12.2.4 **resiprokal** bağlantılarını doğrular.
- `samples/` (21: 11 pass + 10 degrade) + `tests/` (bağımsız R1–R12) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tenant_isolation_probe.py validate          # statik model + spec + 12.4.1/12.2.3/12.1.x/12.2.4 resiprokal
python3 tenant_isolation_probe.py selftest          # R1–R12 motoru
python3 tenant_isolation_probe.py check samples     # 11 pass + 10 degrade
python3 tests/tenant_isolation_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                                  # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| Tenant CRUD + yaşam döngüsü durum makinesi | 12.4.1 |
| PostgreSQL RLS çalışma-anı zorlama / çift-kontrol | 12.2.3 |
| Tenant içi org yapısı (marka/departman/ülke/proje, L1) | 12.4.3 |
| Tenant dil/saat dilimi/bölge/saklama **tercihi** (L1) | 12.4.4 |
| rol→permission-key bundle / permission katalog | 12.1.1 / 12.1.2 |
| WORM / append-only audit **akışı** | 12.1.8 |
| L0 ⟂ tenant iş verisi repository bağımsızlığı | 12.2.4 |
| Kaynak kotası (vCPU/bellek/eşzamanlılık) | FR-TEN-006/007 |
| Plan/billing (dedicated ayrı faturalama; FR-BIL-005) | WBS 15 |
| Gerçek IaC namespace/cluster sağlama | 0.4.2 / 0.4.3 |
| Gerçek veri taşıma/cutover (migrate yürütme) | F1 kod + ops runbook |

## Notlar

- **Vendor-neutral** (ADR-002/006/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (KMS key materyali / DB şifresi / connection string) ve ham içerik (müşteri PII) repoya
  yazılmaz** — yalnız op/mode/placement/realm/plane enum + permission-key + region enum + slug tenant/request
  kimlik + `kms_key_ref` **referansı** (anahtar kimliği, materyal değil) + sha256. Bu modül izolasyon-sınıfı
  **bağlama kararını** verir; ham satır içeriği / key materyali **akmaz**.
- Gerçek L0 izolasyon sağlama (IaC namespace/cluster + RLS politikaları + KMS tahsisi + migrate cutover + L0
  OpenAPI) **F1 kod aşamasında**; bu modül onlara kararı + kanıtı + model bütünlük manifestini iletir.
