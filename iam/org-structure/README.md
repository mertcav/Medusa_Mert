# WBS 12.4.3 — Org yapısı (marka/departman/ülke/proje) (L1)

**Faz:** F1 · **Öncelik:** Must · **İz:** **FR-TEN-003** (Tenant altında marka, departman, ülke ve proje yapıları oluşturulabilmelidir) · DB.md §5.1 (`organisation_unit` — self-ref hiyerarşi; `type` CHECK [brand/country/department/project]; `region` residency override; UNIQUE (tenant_id,parent_id,name)) · BRD §17 (org yapısı **L1 Tenant Admin Console**) · SAD §14.4 (scoped assignment scope {brand|department|campaign}) · NFR 10.7 (residency UK/EU/NA/ME) · FR-TEN-002 (tenant izolasyonu) · FR-IAM-011 (scoped assignment) · SR-TEN-003 → TC-TEN-003 · ADR-011/012

12. workstream'in (IAM & Erişim) **tenant içi org-yapısı** modülü. FR-TEN-003'ü sahiplenir. **ÇEKİRDEK FARK:**
bu **L1** (Tenant Admin Console; `tenant` realm + `tenant_application_plane`) yüzeyidir — 12.4.1 (tenant CRUD) ve
12.4.2 (dedicated vs shared) **L0** (platform) iken bu **L1**: tenant **kendi** org yapısını yönetir, L0 görmez
(FR-IAM-008 altın kural). Org birimini **deterministik, fail-closed** bir **BAĞLAMA (binding) kararı** olarak
yönetir. Bir `OrgRequest` için terminal: **`COMMIT` | `REJECT`**.

## Org birimi tipleri (DB.md §5.1 CHECK)

| Tip | TR | Açıklama |
|-----|----|----|
| `brand` | marka | Tenant altındaki marka birimi |
| `country` | ülke | Ülke/bölge birimi (residency override taşıyabilir) |
| `department` | departman | Departman birimi (scoped assignment boyutu) |
| `project` | proje | Proje birimi |

> `organisation_unit` **self-ref hiyerarşi** (`parent_id` → `organisation_unit`); tenant-scoped + RLS (12.2.3).
> `brand`/`department` birimleri **scoped role assignment** kapsam boyutudur (FR-IAM-011; 12.1.3) — agent/kampanya
> bu birimlere atanır (SR-TEN-003).

## İşlemler

| İşlem | Açıklama | Mutasyon (WORM audit) |
|-------|----------|------------------------|
| `create` | Yeni org birimi oluştur (tip + ad + ebeveyn) | ✓ |
| `update` | Ad/region güncelle (tip immutable) | ✓ |
| `move` | Ebeveyn değiştir (reparent; döngü yasak) | ✓ |
| `delete` | Birim sil (çocuk/scope-referansı → cascade+confirm) | ✓ |
| `read` | Org birimini oku | — (mutasyon değil) |

Org yapısı yönetimi **yalnız** L1 (`tenant` realm + `tenant_application_plane`; BRD §17) ve **`org:manage`**
permission-key (12.1.2 katalog; `tenant_owner`/`tenant_admin` bundle 12.1.1/ADR-012) ile yürütülür.

## Karar akışı (gate)

```
OrgRequest ─malformed─► tenant_isolation ─► authz ─► type ─► hierarchy ─► uniqueness ─► residency ─► delete_guard ─► audit
      ├─ request_id/op/realm/plane eksik|geçersiz | create'de name eksik ──────────────────► REJECT (malformed)
      ├─ ¬(tenant ∧ tenant_application_plane ∧ own_tenant) ──► REJECT  [commit ⇒ cross_tenant_op      R2]
      ├─ org:manage ∉ actor_permissions ───────────────────► REJECT  [commit ⇒ unauthorized_op        R3]
      ├─ type ∉ {brand,country,department,project} ────────► REJECT  [commit ⇒ invalid_type           R4]
      ├─ ¬valid_hierarchy(parent,ancestors,depth) ────────► REJECT  [commit ⇒ hierarchy_violation     R5]
      ├─ name ∈ sibling_names ──────────────────────────────► REJECT  [commit ⇒ duplicate_name          R6]
      ├─ region ∉ tenant_allowed ──────────────────────────► REJECT  [commit ⇒ residency_violation     R7]
      ├─ delete ∧ referenced ∧ ¬(cascade∧confirm) ────────► REJECT  [commit ⇒ unsafe_delete           R8]
      └─ mutating ∧ ¬audit ────────────────────────────────► REJECT  [commit ⇒ missing_audit           R9]
```

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **REJECT** (fail-closed); kanıt; `model_hash` sha256; `stuck_state`/`missing_evidence=0` |
| **R2** | **FR-TEN-002** | **Tenant izolasyonu:** org yönetimi YALNIZ `tenant` realm + `tenant_application_plane` (L1) + aktör KENDİ tenant'ı (hedef + ebeveyn aynı tenant); yanlış realm / cross-tenant `cross_tenant_op=0` (12.2.3 RLS resiprokal) |
| **R3** | **ADR-012** | **Yetkilendirme:** op `org:manage` gerektirir; yetkisiz commit `unauthorized_op=0` |
| **R4** | **DB.md §5.1** | **Tip geçerliliği:** `type` ∈ {brand,country,department,project} (CHECK); geçersiz commit `invalid_type=0` |
| **R5** | **DB.md §5.1** | **Hiyerarşi bütünlüğü:** self-ref döngüsüz (`org_unit_id ∉ ancestor_ids`) + ebeveyn ≠ kendisi + derinlik ≤ `max_depth`; ihlal `hierarchy_violation=0` |
| **R6** | **DB.md §5.1** | **Kardeş benzersizliği:** UNIQUE (tenant_id,parent_id,name); çakışan ad commit `duplicate_name=0` |
| **R7** | **NFR 10.7** | **Residency:** `region` (override) tenant izinli bölge kümesinde + UK/EU/NA/ME (yalnız-daraltır); dışında commit `residency_violation=0` |
| **R8** | **FR-IAM-011** | **Silme koruması:** çocuğu/scope-referansı (12.1.3) olan birim silme `cascade`+`confirm` gerektirir; korumasız `unsafe_delete=0` |
| R9 | FR-REC-009 | **WORM audit:** her mutasyon `audit_log`'a (12.1.8); `missing_audit=0` |
| R10 | ADR-011 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi (cross-tenant ebeveyne izin / döngü kontrolünü kapatma) yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: op/result/org_type düşük-kard; tenant_id/org_unit_id/parent_id/request_id yalnız trace; PII (org adı değeri) label değil |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız op/type/realm/plane enum + permission-key + region enum + slug kimlik + sentetik org adı + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.4.x deseniyle birebir: motor **doğru** org-yapısı kararını hesaplar, `inject` doğru davranışı
**bozar** (unsafe koşulu + commit zorlar) ve eşleşen ihlal sayacını artırır → kapı eler. 10 enjeksiyon:
`cross_tenant`, `wrong_realm`, `drop_permission`, `invalid_type`, `hierarchy_cycle`, `duplicate_name`,
`residency_drift`, `unsafe_delete`, `skip_audit`, `model_tamper`.

**Anahtar ayrım:** geçersiz-tip / döngülü-hiyerarşi / çakışan-ad / korumasız-silme op'unun **REJECT'i DOĞRU
çıktıdır** (ihlal değil — kapı geçer). İhlal sayacı YALNIZ unsafe koşul **+ commit** birlikte olunca artar (ör.
`os-pass-reject-*` = motor doğru reddetti; `os-degrade-*` = bozulup yine commit etti).

## Dosyalar

- `config/org-structure-model.json` — **frozen** model (`org_types`[brand/country/department/project] +
  `operations`[5; mutating 4] + `op_permission`[org:manage] + `tenant_scope`[kendi tenant + ebeveyn aynı tenant]
  + `hierarchy`[döngüsüz + `max_depth`] + `uniqueness`[UNIQUE (tenant_id,parent_id,name)] + `residency`[region
  tenant izinli; UK/EU/NA/ME] + `delete_guard`[çocuk/scope → cascade+confirm] + `audit`[WORM] +
  `scoped_assignment_link`[12.1.3 boyutları] + `data_class`[organisation_unit=tenant_config, 12.2.4]).
- `org-structure-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + kapılar).
- `org_structure_probe.py` — org-yapısı karar motoru + `validate`/`check`/`selftest`/`schema`.
  12.1.3/12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 **resiprokal** bağlantılarını doğrular.
- `samples/` (21: 11 pass + 10 degrade) + `tests/` (bağımsız R1–R12) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 org_structure_probe.py validate          # statik model + spec + 12.1.3/12.1.2/12.1.1/12.2.3/12.4.1/12.2.4 resiprokal
python3 org_structure_probe.py selftest          # R1–R12 motoru
python3 org_structure_probe.py check samples     # 11 pass + 10 degrade
python3 tests/org_structure_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                               # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| Tenant CRUD + yaşam döngüsü durum makinesi | 12.4.1 |
| Dedicated vs shared izolasyon sınıfı (L0) | 12.4.2 |
| Tenant dil/saat dilimi/bölge/saklama **tercihi** (L1) | 12.4.4 |
| Scoped role assignment **çözümü** (org birimi → scope) | 12.1.3 |
| PostgreSQL RLS çalışma-anı zorlama / çift-kontrol | 12.2.3 |
| rol→permission-key bundle / permission katalog | 12.1.1 / 12.1.2 |
| WORM / append-only audit **akışı** | 12.1.8 |
| L0 ⟂ tenant iş verisi repository bağımsızlığı | 12.2.4 |
| L1 OpenAPI/UI (T-02 Organizasyon & Yapı ekranı) | 13.3.2 |
| Gerçek `organisation_unit` CRUD + cascade/yeniden-atama (delete yürütme) | F1 kod + ops runbook |

## Notlar

- **Vendor-neutral** (ADR-002/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (DB şifresi / connection string) ve ham içerik (müşteri PII) repoya yazılmaz** — yalnız
  op/type/realm/plane enum + permission-key + region enum + slug tenant/org_unit/request kimlik + sentetik org
  adı (yapısal etiket) + sha256. Org birimi adı **müşteri-tanımlı** olabilir → metrik label DEĞİL, yalnız trace.
- Gerçek L1 org sağlama (`organisation_unit` CRUD + RLS + cascade/yeniden-atama + L1 OpenAPI/UI) **F1 kod /
  13.3.2 aşamasında**; bu modül onlara kararı + kanıtı + model bütünlük manifestini iletir.
