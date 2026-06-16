# WBS 12.1.1 — RBAC modeli (rol → permission-key bundle, immutable)

**Faz:** F1 · **Öncelik:** Must · **İz:** BRD §17.2 → **FR-IAM-001** + **FR-IAM-011** → SR-IAM-001 / SR-IAM-011 → TC-IAM-001 (T) / TC-IAM-011 (I) · SAD §14.4.3 · ADR-012

12. workstream'in (IAM & Erişim) **RBAC çekirdek modeli**. BRD §17.2 rol seti (12 rol) + SAD §14.4.3
rol→permission-key haritasını makine-okunur, **değişmez (frozen)** bir modele dönüştürür ve bir yetki
sorgusu (`RoleCheckRequest`) için **deterministik, fail-closed** bir yetki **kararı** verir: aktörün
rollerini frozen modelden çözer (**effective bundle = rol bundle'larının birleşimi**) → `required`
permission-key'i değerlendirir (`:own` sahiplik kuralıyla). Terminal karar: **`GRANT` | `DENY` | `BLOCK`**.

Roller **immutable permission bundle**'lardır (FR-IAM-011 / ADR-012): çalışma anında değiştirilemez,
v1'de **custom permission-builder yoktur**. Esneklik yalnız **atama scope filtresiyle** (departman/marka/
kampanya — **12.1.3**) sağlanır.

## Karar akışı

```
RoleCheckRequest ─malformed─► unknown_role ─► realm/katman ─► bundle çöz ─► authz (:own) ─► karar
      ├─ required/rol/kimlik eksik | required biçimsiz ──────────► BLOCK (malformed_request)
      ├─ rol modelde yok ───────────────────────────────────────► BLOCK (unknown_role)          [K8]
      ├─ rol realm ≠ actor_realm (L0 ⟂ tenant) ─────────────────► BLOCK (realm_layer_mismatch)   [K4]
      ├─ required ∉ effective bundle ───────────────────────────► DENY  (missing_permission)     [K3]
      ├─ yalnız :own + sahiplik=other ──────────────────────────► DENY  (insufficient_scope)     [K6]
      └─ required ∈ effective bundle (:own sahiplik tutar) ─────► GRANT                           [K3]
```

**Çekirdek garanti (K2, FR-IAM-011):** effective set **yalnız frozen modelden** çözülür; çalışma anında
bir role permission eklenip/çıkarılması (`bundle_mutated`) yasak; custom rol yok (`custom_role`). `model_hash`
sha256 her çağrıda aynı (immutable).
**Çekirdek garanti (K3, FR-IAM-001 / SR-IAM-001):** `effective = ∪ rol bundle`; `GRANT ⟺ required ∈ effective`;
yetkisiz GRANT (`unauthorized_grant`) yasak; karar **her zaman backend'de**.
**Çekirdek garanti (K4, FR-IAM-008):** her rol tanımlı katman/realm'e bağlı; **L0 (platform) ⟂ tenant**;
rol realm'i ≠ `actor_realm` → BLOCK (tenant IdP L0 rol atayamaz).
**Çekirdek garanti (K7, FR-IAM-008 L0 altın kuralı):** rol bundle'ı realm evrenini aşmaz; **L0 rolleri tenant
iş içeriği key'i** (`calls:read`/`transcript:read`/`transcript:manage`/`livecalls:*`) **taşımaz** —
platform tenant içeriğine yalnız break-glass ile (12.3.x).

## İnvariant'lar (K1–K12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| K1 | | Determinizm/terminal; `model_hash` sha256 deterministik; `stuck_state=0` |
| **K2** | **FR-IAM-011 / SR-IAM-011** | Immutable bundle: effective set yalnız frozen modelden; `bundle_mutated=0`, `custom_role=0` |
| **K3** | **FR-IAM-001 / SR-IAM-001** | Bundle çözümü + backend authz: `effective=∪ bundle`; `GRANT⟺required∈effective`; `unauthorized_grant=0` |
| **K4** | **FR-IAM-008** | Katman/realm bütünlüğü: L0 ⟂ tenant; rol realm = actor_realm; `realm_mismatch=0` |
| K5 | SAD §14.4.3 | Katalog conformance: her bundle key'i `kaynak:eylem` + bilinen evrende; `unknown_permission=0` |
| **K6** | BRD §17.7 | `:own` disiplini: `:own` yalnız sahiplik=own; `ownership_violation=0` |
| **K7** | **FR-IAM-008** | En az yetki: bundle ⊆ realm evreni; L0 tenant içerik key'i taşımaz; `privilege_escalation=0`, `layer_violation=0` |
| **K8** | SR-IAM-011 | Custom rol yok: model dışı rol → BLOCK; v1'de custom-builder yok; `custom_role=0` |
| K9 | FR-IAM-006 | Kanıt: request + actor_roles + required + `effective_bundle_hash` + `model_hash` |
| K10 | FR-IAM-011 / ADR-012 | Model bütünlük manifesti: `model_hash` sha256; çalışma-anı tahrifi yakalanır; `model_tampered=0` |
| K11 | BRD §17.7 | Gözlemlenebilirlik düşük-kardinalite + ham içerik/PII yok |
| K12 | BRD §17.7 | Sır/ham-içerik yok; yalnız rol adı + permission-key + enum + kimlik; `secret_or_pii=0` |

## Model (`config/rbac-roles.json` — frozen)

12 rol (BRD §17.2) × **immutable** permission bundle (SAD §14.4.3). Her rol: `layer` (L0/L1/L2/L1+L2) +
`realm` (platform/tenant) + `permissions[]`.

| Katman | Realm | Roller |
|--------|-------|--------|
| L0 | platform | `platform_owner`, `platform_sre`, `platform_billing` |
| L1 | tenant | `tenant_admin`, `security_compliance_officer`, `billing_viewer` |
| L1+L2 | tenant | `tenant_owner`, `api_developer` |
| L2 | tenant | `operations_manager`, `conversation_designer`, `qa_analyst`, `human_agent` |

- **permission-key formatı:** `kaynak:eylem` (ör. `transcript:read`, `campaign:manage`, `tenant:provision`);
  `:own` son ekli key'ler sahiplikle sınırlı (`calls:read:own`).
- **L0 altın kuralı (FR-IAM-008):** L0 bundle'ları `tenant_content_keys`'i (kayıt/transkript/canlı çağrı)
  **taşımaz** — `platform_sre` yalnız kapasite/sağlayıcı/incident key'leri taşır, iş içeriği görmez.

## Çalıştırma

```bash
python3 rbac_model_probe.py validate      # statik model/spec/kapsama kapısı (91 kontrol)
python3 rbac_model_probe.py selftest      # gömülü davranış (K1–K12, 56 kontrol)
python3 rbac_model_probe.py check samples # 10 pass + 8 degrade senaryo
python3 rbac_model_probe.py schema        # karar sözleşmesi
python3 tests/rbac_model_behavior_test.py # bağımsız davranış testi (34 kontrol)
./run_live_test.sh                        # hepsi
```

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| permission-key **grameri + tam kataloğu** (`kaynak:eylem`, `:own` semantiği) | **12.1.2** (key'ler conform edilir) |
| **Scoped assignment** (rol + departman/marka/kampanya filtresi) | **12.1.3** (rol çözülür, kapsam orada daraltır; ADR-012) |
| **Backend guard** (FastAPI dependency + router + tenant scope + RLS) | **12.2.x** (karar **enforcement**) |
| **Break-glass** (L0 Tier B maker-checker + time-boxed) | **12.3.x** (rol→bundle çözülür; FR-IAM-009/010) |
| SSO/SCIM IdP **grup→rol eşleme** | 12.1.4 / 12.1.6 (rol **atanır**, bu modül çözer) |
| Append-only **WORM audit log** + bütünlük | 12.1.8 (karar **kaydı** üretilir; FR-IAM-006) |
| **Custom roller** (şablonlu, enterprise/dedicated) | Faz 3 (ADR-012; v1 kapsam dışı) |

Vendor-neutral (ADR-001/002/011/012); stdlib-only, credential-free, deterministik (`Date.now/random` YOK).
Model/spec/sample sır/credential ve ham içerik (PII değeri) tutmaz — yalnız rol adı + permission-key + enum +
yapısal kimlik + sha256 hash (sentetik fixture; FR-TST-008).
