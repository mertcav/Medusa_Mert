# WBS 12.1.3 — Scoped assignment (rol + departman/marka/kampanya filtresi)

**Faz:** F2 · **Öncelik:** Must · **İz:** BRD §17.2 → **FR-IAM-011** → SR-IAM-011 → TC-IAM-011 (I) · BRD §16 (Organisation Unit/Campaign) · FR-TEN-002 · SAD §14.4.2 · ADR-012

12. workstream'in (IAM & Erişim) **kapsam-daraltma** modülü. [`12.1.1`](../rbac-model/README.md) RBAC
modelini (rol→**IMMUTABLE** permission bundle, frozen) **tüketir** ve üzerine atamanın **kapsamını** ekler:
bir aktörün **atamaları** = `[(rol, scope)]` çiftleri; `scope` = `{department/brand/campaign → izinli değer
kümeleri}`. Bir kapsam-duyarlı yetki sorgusu (`ScopedCheckRequest`) için **deterministik, fail-closed** bir
karar verir. Terminal: **`GRANT` | `DENY` | `BLOCK`**.

**Çekirdek ilke (FR-IAM-011 / ADR-012):** Roller **sabit** (immutable bundle); esneklik, rol *atamasının*
bir **scope filtresiyle daraltılmasıyla** sağlanır. *"Bir `operations_manager` yalnız belirli departman/marka/
kampanya kapsamına atanabilir"* (BRD §17.2). Kapsam **yalnız daraltır (narrowing-only)** — scope, rolün yetki
yüzeyini **asla genişletemez** ve bundle'a **permission ekleyemez**.

## İki kapı

```
ScopedCheckRequest ─malformed─► unknown_role ─► realm ─► tenant ─► permission gate ─► scope gate ─► karar
      ├─ atama/required/resource/kimlik eksik | required biçimsiz ────► BLOCK (malformed_request)
      ├─ atama rolü 12.1.1 modelinde yok ─────────────────────────────► BLOCK (unknown_role)
      ├─ atama rol realm ≠ actor_realm (L0 ⟂ tenant) ─────────────────► BLOCK (realm_layer_mismatch)   [S4]
      ├─ resource.tenant_id ≠ actor tenant_id ───────────────────────► BLOCK (cross_tenant_resource)  [S7]
      ├─ ∃ atama: required ∈ bundle(rol) ∧ resource ∈ scope(atama) ───► GRANT                          [S3]
      ├─ permission var ∧ hiçbir scope kapsamıyor ───────────────────► DENY  (out_of_scope)            [S2]
      ├─ yalnız :own + sahiplik=other ───────────────────────────────► DENY  (insufficient_scope)
      └─ hiçbir atama permission taşımaz ────────────────────────────► DENY  (missing_permission)
```

1. **Permission gate** (12.1.1'den): atamanın rolü frozen bundle'dan çözülür; `required ∈ bundle` (`:own`
   sahiplik kuralıyla — 12.1.1'den **devralınır**).
2. **Scope gate** (bu modülün çekirdeği): atamanın `scope`'u kaynak attribute'larına (`department`/`brand`/
   `campaign`) karşı süzülür; **narrowing-only**.

`GRANT ⟺ ∃ atama HER İKİ kapıdan geçer` (atamalar arası **birleşim/union**).

**Örnek (SAD §14.4.2):** `operations_manager@scope=brand-x` → rol `campaign:manage` *taşır* ama scope
`brand-x`'e daraltır; `brand-y` kampanyası → **DENY `out_of_scope`** (rol permission'ı taşısa bile).

## Kapsam semantiği (`config/scope-model.json` — frozen)

- **Boyutlar:** `department`, `brand`, `campaign` (BRD §16 Organisation Unit + Campaign).
- **Eşleşme:** boyutlar arası **AND**, boyut içi **OR**, atamalar arası **UNION**.
- **Wildcard `*`** / atamada **listelenmeyen boyut** = o boyutta **kısıtsız**.
- **Boş/eksik scope** (`{}`) = **tenant-geneli** (v1 geriye-uyum: mevcut rol bundle davranışı).
- **Empty list `[]`** kısıtlı bir boyutta = **matches_nothing** (fail-closed; match-all *değil*).
- **Resource bir kısıtlı boyutu taşımıyorsa** = fail-closed (kapsamda olduğu kanıtlanamaz → `out_of_scope`).
- **Tenant sınırı kapsamın üstünde:** `resource.tenant_id ≠ actor tenant` → **BLOCK** (FR-TEN-002).

## İnvariant'lar (S1–S12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| S1 | | Determinizm/terminal; `model_hash` sha256 deterministik; `stuck_state=0` |
| **S2** | **FR-IAM-011 / ADR-012** | **Narrowing-only:** scope rolün immutable bundle'ını **yalnız daraltır**; scope dışı kaynak DENY `out_of_scope`; `scope_broadened=0` |
| **S3** | **FR-IAM-011** | **Scoped-grant doğruluğu:** `GRANT ⟺ ∃ atama (required∈bundle ∧ resource∈scope)`; `out_of_scope_grant=0`; granted⟺authorized |
| **S4** | **FR-IAM-008** | Realm/katman bütünlüğü (12.1.1'den): L0 ⟂ tenant; atama rol realm = actor_realm; `realm_mismatch=0` |
| S5 | BRD §16 | Boyut conformance: scope yalnız department/brand/campaign üzerinde; `unknown_dimension=0` |
| S6 | FR-IAM-011 | Wildcard disiplini: `*`/listelenmeyen = kısıtsız; `{}` = tenant-geneli; `[]` = matches_nothing (fail-closed) |
| **S7** | **FR-TEN-002** | **Tenant izolasyonu:** kapsam tenant içinde; cross-tenant kaynak → BLOCK; `cross_tenant=0` |
| **S8** | **FR-IAM-011 / ADR-012** | **Immutable bundle korunur:** scope permission **ekleyemez**; `permission_added=0` |
| S9 | FR-IAM-006 | Kanıt: request + atamalar(rol+scope) + required + resource + `matched_assignment` + `model_hash` |
| S10 | ADR-012 | Model bütünlük manifesti: `model_hash` sha256 (scope model + 12.1.1 bundle); `model_tampered=0` |
| S11 | BRD §17.7 | Gözlemlenebilirlik düşük-kardinalite + ham içerik/PII yok |
| S12 | BRD §17.7 | Sır/ham-içerik yok; yalnız rol adı + permission-key + kapsam boyut ID + enum + kimlik; `secret_or_pii=0` |

## Çalıştırma

```bash
python3 scoped_assignment_probe.py validate      # statik scope/rbac model + spec + kapsama kapısı
python3 scoped_assignment_probe.py selftest      # gömülü davranış (S1–S12)
python3 scoped_assignment_probe.py check samples # 10 pass + 10 degrade senaryo
python3 scoped_assignment_probe.py schema        # karar sözleşmesi
python3 tests/scoped_assignment_behavior_test.py # bağımsız davranış testi (S1–S12)
./run_live_test.sh                               # hepsi
```

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| rol→permission-key **bundle çözümü** (immutable; `:own`; L0 ⟂ tenant) | **12.1.1** (TÜKETİLİR; bu modül üstüne kapsam ekler) |
| permission-key **gramer + tam kataloğu** | **12.1.2** |
| **Backend guard** (FastAPI dependency: permission-key **+ scope kaynak attribute** + RLS çift kontrol) | **12.2.x** (karar **enforcement**; SAD §14.4.2) |
| rol+scope **atama üretimi** (IdP grup→rol+kapsam eşleme) | 12.1.4 / 12.1.6 (atama **üretilir**, bu modül çözer) |
| **Break-glass** (Tier B kapsam-üstü erişim) | 12.3.x (FR-IAM-009/010) |
| Append-only **WORM audit log** | 12.1.8 (karar **kaydı** üretilir; FR-IAM-006) |
| **Custom roller** (şablonlu, enterprise/dedicated) | Faz 3 (ADR-012; v1 kapsam dışı) |

Vendor-neutral (ADR-001/002/011/012); stdlib-only, credential-free, deterministik (`Date.now/random` YOK).
Model/spec/sample sır/credential ve ham içerik (PII değeri) tutmaz — yalnız rol adı + permission-key + kapsam
boyut ID (sentetik, ör. `brand-x`/`dept-sales`/`camp-1`) + enum + yapısal kimlik + sha256 hash (sentetik
fixture; FR-TST-008).
