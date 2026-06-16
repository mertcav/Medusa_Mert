# WBS 12.4.1 — Tenant CRUD + provisioning (L0)

**Faz:** F1 · **Öncelik:** Must · **İz:** **FR-TEN-001** (Platform birden fazla kurumsal müşteriyi tenant bazında yönetmelidir) · BRD §17 (tenant yaşam döngüsü işlemleri → Platform Admin Console L0) · DB.md §5.1 (tenant tablosu: `status`/`isolation_mode`/`home_region`/`kms_key_ref`) + §9 (geri döndürülemez silme) · NFR 10.6 (tenant başına ayrı KMS key) · NFR 10.7 (residency UK/EU/NA/ME) · FR-IAM-008 (L0 ⟂ tenant realm) · SR-TEN-001 → TC-TEN-001 · ADR-011/012/006

12. workstream'in (IAM & Erişim) **L0 tenant yaşam döngüsü** modülü. FR-TEN-001'i ve BRD §17'nin temel kararını
sahiplenir: *"Tenant yaşam döngüsü işlemleri — tenant oluşturma/askıya alma/silme, plan atama, kaynak kotası
tanımı — **Platform Admin Console (L0)** üzerinden yürütülür."* Tenant kök varlığını (DB.md §5.1) **deterministik,
fail-closed** bir **DURUM MAKİNESİ + admission kararı** olarak yönetir. Bir `TenantOpRequest` için terminal:
**`COMMIT` | `REJECT`**.

## Yaşam döngüsü durum makinesi (DB.md §5.1 `status` CHECK)

```
        create                activate              suspend
 (none) ───────► provisioning ─────────► active ◄──────────► suspended
                      │                    │  resume          │
                      │ terminate          │ terminate        │ terminate
                      └────────────────────┴──────────────────┘
                                           ▼
                                      terminated  (TERMİNAL — çıkış yok; DB.md §9 geri döndürülemez)
```

| İşlem | from → to | Gerekli permission-key | Mutasyon (WORM audit) |
|-------|-----------|------------------------|------------------------|
| `create` | none → provisioning | `tenant:provision` | ✓ |
| `activate` | provisioning → active | `tenant:provision` | ✓ |
| `suspend` | active → suspended | `tenant:suspend` | ✓ |
| `resume` | suspended → active | `tenant:suspend` | ✓ |
| `terminate` | {provisioning, active, suspended} → terminated | `tenant:provision` | ✓ |
| `update` | active/suspended → (korunur) | `tenant:provision` | ✓ |
| `read` | her durum → (korunur) | `tenant:provision` | — (mutasyon değil) |

Permission-key'ler **12.1.2 kataloğundan** alınır (yeni anahtar icat edilmez); ikisi de **`platform_owner`**
bundle'ında (12.1.1 / ADR-012).

## Karar akışı (gate)

```
TenantOpRequest ─malformed─► realm/plane ─► authz ─► transition ─► provisioning ─► kms ─► idempotency ─► term ─► audit
      ├─ request_id/op/realm/plane/current_status eksik|geçersiz ───────────────────────► REJECT (malformed)
      ├─ ¬(platform ∧ platform_control_plane) ──────────────► REJECT  [commit ⇒ cross_realm_op        R2]
      ├─ required_perm ∉ actor_permissions ────────────────► REJECT  [commit ⇒ unauthorized_op       R3]
      ├─ ¬valid_transition(op,current_status) ─────────────► REJECT  [commit ⇒ invalid_transition    R4]
      ├─ create ∧ ¬provisioning_complete ──────────────────► REJECT  [commit ⇒ incomplete_provisioning R5]
      ├─ create ∧ ¬kms_distinct ───────────────────────────► REJECT  [commit ⇒ shared_kms_key        R6]
      ├─ create ∧ tenant_exists ───────────────────────────► REJECT  [commit ⇒ duplicate_provision   R7]
      ├─ terminate ∧ ¬guarded ─────────────────────────────► REJECT  [commit ⇒ unguarded_termination R8]
      └─ mutating ∧ ¬audit ────────────────────────────────► REJECT  [commit ⇒ missing_audit         R9]
```

## Provisioning (create) zorunlu alanları (DB.md §5.1 NOT NULL + NFR 10.6/10.7 + FR-TEN-002)

`tenant_name` · `home_region` (∈ **UK/EU/NA/ME** — NFR 10.7) · `kms_key_ref` (tenant başına AYRI — NFR 10.6) ·
`isolation_mode` (∈ **shared/dedicated** — ADR-006/FR-TEN-005) · `compliance_profile` (BRD §14.4) ·
`default_locale` · `timezone`. İlk durum **`provisioning`** olmalı (doğrudan `active` değil — provisioning iş
akışı: KMS key tahsisi, region kurulumu). `retention_profile`/`plan_id` opsiyonel (12.4.4 / billing WBS 15).

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **REJECT** (fail-closed); kanıt; `model_hash` sha256; `stuck_state`/`missing_evidence=0` |
| **R2** | **FR-IAM-008** | **Realm izolasyonu:** tenant lifecycle YALNIZ `platform` realm + `platform_control_plane` (L0 altın kural; ADR-011); tenant realm yürütürse `cross_realm_op=0` |
| **R3** | **ADR-012** | **Yetkilendirme:** op gerekli permission-key gerektirir (`tenant:provision`/`tenant:suspend`); yetkisiz commit `unauthorized_op=0` |
| **R4** | **DB.md §5.1/§9** | **Geçiş geçerliliği:** durum makinesi geçişi geçerli olmalı; `terminated` TERMİNAL; `invalid_transition=0` |
| **R5** | **NFR 10.6/10.7** | **Provisioning tamlığı:** create zorunlu izolasyon/residency alanları + ilk durum `provisioning`; `incomplete_provisioning=0` |
| **R6** | **NFR 10.6** | **Tenant-başına KMS:** her tenant kendi `kms_key_ref`'ini alır (paylaşılamaz); `shared_kms_key=0` |
| R7 | FR-TEN-001 | **İdempotent provision:** var olan tenant için ikinci create yapılmaz; `duplicate_provision=0` |
| R8 | DB.md §9 | **Geri döndürülemez terminate koruması:** `confirm_irreversible` + `reason_code`; `unguarded_termination=0` |
| R9 | FR-REC-009 | **WORM audit:** her mutasyon `audit_log`'a (12.1.8); `missing_audit=0` |
| R10 | ADR-011 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi (realm zorunluluğu kaldırma / terminated'ı terminal-dışı yapma) yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: op/result/isolation_mode/target_status/actor_realm düşük-kard; tenant_id/request_id/kms_key_ref yalnız trace; PII metrikte yok |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız op/status/realm/plane enum + permission-key + region/isolation enum + slug kimlik + kms_key_ref **referansı** (materyal değil) + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x deseniyle birebir: motor **doğru** yaşam döngüsü kararını hesaplar, `inject` doğru davranışı
**bozar** (unsafe koşulu + commit zorlar) ve eşleşen ihlal sayacını artırır → kapı eler. 10 enjeksiyon:
`cross_realm`, `drop_permission`, `invalid_transition`, `skip_provisioning_field`, `direct_active`, `share_kms`,
`duplicate_provision`, `unguard_termination`, `skip_audit`, `model_tamper`.

**Anahtar ayrım:** yetkisiz/geçersiz-geçiş/eksik-provisioning op'unun **REJECT'i DOĞRU çıktıdır** (ihlal değil —
kapı geçer). İhlal sayacı YALNIZ unsafe koşul **+ commit** birlikte olunca artar (ör. `tp-pass-reject-*` =
motor doğru reddetti; `tp-degrade-*` = bozulup yine commit etti).

## Dosyalar

- `config/tenant-lifecycle-model.json` — **frozen** model (`statuses`[4; terminated terminal] + `operations`[7;
  mutating 6] + `op_permission` + `transitions`[durum makinesi] + `provisioning`[zorunlu alanlar; regions; isolation_modes]
  + `isolation`[tenant başına KMS] + `termination`[confirm+gerekçe] + `audit`[WORM] + `data_class`[tenant=platform, 12.2.4]).
- `tenant-provisioning-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + kapılar).
- `tenant_provisioning_probe.py` — tenant yaşam döngüsü karar motoru + `validate`/`check`/`selftest`/`schema`.
  12.1.2/12.1.1/12.2.4/12.1.8 **resiprokal** bağlantılarını doğrular.
- `samples/` (21: 11 pass + 10 degrade) + `tests/` (30 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tenant_provisioning_probe.py validate          # statik model + spec + 12.1.x/12.2.4 resiprokal
python3 tenant_provisioning_probe.py selftest          # R1–R12 motoru
python3 tenant_provisioning_probe.py check samples     # 11 pass + 10 degrade
python3 tests/tenant_provisioning_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                                     # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| Dedicated vs shared izolasyon **sınıfı** sağlanması (ADR-006) | 12.4.2 |
| Tenant içi org yapısı (marka/departman/ülke/proje, L1) | 12.4.3 |
| Tenant dil/saat dilimi/bölge/saklama **tercihi** (L1) | 12.4.4 |
| HTTP `enforce_panel/tenant_scope` (çalışma-anı guard) | 12.2.1 |
| PostgreSQL RLS çalışma-anı zorlama | 12.2.3 |
| rol→permission-key bundle | 12.1.1 |
| permission-key kataloğu | 12.1.2 |
| WORM / append-only audit **akışı** | 12.1.8 |
| L0 ⟂ tenant iş verisi repository bağımsızlığı (tenant tablosu=platform sınıf) | 12.2.4 |
| Kaynak kotası (vCPU/bellek/eşzamanlılık) | FR-TEN-006/007 (sonraki WBS) |
| Plan/billing (`plan_id` atama) | WBS 15 |
| Gerçek veri silme (retention/crypto-shred, legal-hold) | WBS 1.2.3 |

## Notlar

- **Vendor-neutral** (ADR-002/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (KMS key materyali / DB şifresi / connection string) ve ham içerik (müşteri PII) repoya
  yazılmaz** — yalnız op/status/realm/plane enum + permission-key + region/isolation enum + slug tenant/request
  kimlik + `kms_key_ref` **referansı** (anahtar kimliği, materyal değil) + sha256. Bu modül lifecycle **admission
  kararını** verir; ham satır içeriği / key materyali **akmaz**.
- Gerçek L0 tenant yaşam döngüsü enforcement (FastAPI tenant router + tenant tablosu repository + KMS key tahsisi
  + retention motoru bağı + L0 OpenAPI) **F1 kod aşamasında**; bu modül onlara kararı + kanıtı + model bütünlük
  manifestini iletir.
