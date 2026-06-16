# WBS 12.2.4 — L0 iş verisi repository bağımsızlığı (tasarımsal/design-time izolasyon)

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.2 → **FR-IAM-008** (L0 ⟂ tenant iş verisi) · DB.md P3 (repository/grant düzeyinde bağlı değil) · **FR-IAM-009** (break-glass) · API.md (L0 OpenAPI iş-verisi endpoint'i yok) · SR-IAM-008 → TC-IAM-008 · ADR-011

12. workstream'in (IAM & Erişim) **tasarım-zamanı (design-time) L0 ⟂ tenant izolasyon** modülü. SAD §14.4.2'nin
temel kararını sahiplenir: *"Platform endpoint'leri **tasarım gereği** tenant iş verisi (call/transcript/PII)
repository'lerine **bağlı değildir**; erişim yalnız break-glass akışıyla açılır."* ve DB.md P3: *"Platform (L0)
rolleri tenant iş verisi tablolarına **repository/grant düzeyinde bağlı değildir**."* Bir `RepoBindingRequest`
için **deterministik, fail-closed** bir kompozisyon admission kararı verir. Terminal: **`PERMIT` | `FORBID`**.

Bu katman **12.2.1 (HTTP guard)** ve **12.2.3 (RLS)** *çalışma-anı* kararlarından **ÖNCE** gelir: L0 platform
plane'inin tenant iş verisine erişimi **kompozisyon (wiring)** ve **DB grant** seviyesinde tasarımca **dışlanır**
— çalışma-anı guard regrese olsa bile L0 kodu tenant iş verisi tablosuna **ulaşamaz** (repository binding +
grant yok).

## İki bağımsız tasarım katmanı (defense in depth — P2)

İzolasyon **iki bağımsız tasarım katmanında** zorlanır. Birleşim AND'tir:
**`data_reachable ⟺ wired_forbidden_repo ∧ grant_present`** — tenant iş verisi L0'dan **ancak her iki katman da
regrese olursa** erişilebilir; tek katman hatası (yanlış wire **veya** stray grant) veriyi açmaz.

| Katman | Sahip | Mekanizma |
|--------|-------|-----------|
| **(A) wiring/kompozisyon** | **12.2.4 (bu modül)** | `platform_control_plane` (L0 internal-only, ADR-011) kompozisyon kökü `tenant_content`/`tenant_config` repo'su **wire etmez**; yalnız `platform`+`tenant_metric`+`global_reference` |
| **(B) DB grant** | **12.2.4 (bu modül)** | `platform_ro` DB rolü tenant iş verisi tablolarında **GRANT tutmaz** (REVOKE/hiç GRANT; DB.md P3) |
| **(C) RLS çalışma-anı backstop** | 12.2.3 (TÜKETİLİR) | platform realm `tenant_scoped` satırları break-glass'sız göremez (R7 `platform_overreach=0`) |

**Resiprokal:** 12.2.1 `guard-model.json` → `l0_business_data.delegated_to = "12.2.4 (repository bağımsızlığı)"`
(bu modül o delegasyonu karşılar); 12.2.3 `rls-model.json` `break_glass.tables` ↔ bu modül
`break_glass.content_tables` (eşleşir).

## Karar akışı (gate)

```
RepoBindingRequest ─malformed─► plane sep. ─► classification ─► wiring ─► grant ─► reachability ─► endpoint/bg
      ├─ request_id/plane/data_class+table/db_role eksik|geçersiz ───────────────► FORBID (malformed)
      ├─ platform default deploy_isolation kaybı ───────────────────────────────► plane_coupling  [R2]
      ├─ data_class bilinmiyor → fail-closed; zorla kabul ──────────────────────► unclassified_binding [R3]
      ├─ admit (platform: ¬forbidden; break_glass: content ∧ grant_gated; tenant: tenant-sınıf)
      ├─ platform_default ∧ forbidden ∧ admit ──────────────────────────────────► wired_forbidden_repo [R4]
      ├─ platform_role ∧ forbidden ∧ grant_present ─────────────────────────────► grant_on_content   [R5]
      └─ data_reachable = wired_forbidden_repo ∧ grant_present ──────────────────► (R6 ÇEKİRDEK)
```

## Veri-sınıfı taksonomisi (DB.md §6.3 / BRD §16)

| Sınıf | Örnek | Platform (L0) erişimi |
|-------|-------|-----------------------|
| `tenant_content` | call, transcript, recording, contact, consent (10) | **Forbidden** (yalnız break-glass; FR-IAM-008 PII/içerik) |
| `tenant_config` | agent, prompt, campaign, kb_document (19) | **Forbidden** (L0 tenant işini yönetmez) |
| `tenant_metric` | usage_record (1) | **Allowed** (L0 metrik/kaynak verisi görür) |
| `platform` | tenant, audit_log, incident, break_glass_grant (4) | **Allowed** (L0 yönetişim verisi) |
| `global_reference` | role, permission_key, role_permission (3) | **Allowed** (salt-okunur referans) |

`forbidden_for_platform = tenant_content ∪ tenant_config`. İçeriğe (PII) erişim **yalnız** ayrı, kısıtlı
`break_glass_plane` (grant-gated, time-boxed; 12.3.x). L0 OpenAPI'sinde `GET /calls`, `GET /transcripts` gibi
iş-verisi endpoint'i **bulunmaz** (API.md FR-IAM-008).

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **FORBID** (fail-closed); kanıt; `model_hash` sha256; `stuck_state`/`missing_evidence=0` |
| R2 | ADR-011 | **Plane separation:** `platform_control_plane` internal-only, ayrı deploy; co-deploy/public → `plane_coupling=0` |
| R3 | DB.md P3 | **Classification coverage:** her repo/table sınıflandırılır; bilinmeyen → fail-closed FORBID; `unclassified_binding=0` |
| **R4** | **SAD §14.4.2** | **Wiring bağımsızlığı:** L0 default plane tenant iş verisi repo'su **wire etmez**; `wired_forbidden_repo=0` |
| **R5** | **DB.md P3** | **Grant bağımsızlığı:** `platform_ro` tenant iş verisi tablosunda **grant tutmaz**; `grant_on_content=0` |
| **R6** | **FR-IAM-008** | **Birleşik defense in depth:** `data_reachable ⟺ wired_forbidden_repo ∧ grant_present`; tek katman regresyonu veriyi açmaz; RLS (12.2.3) backstop; `data_reachable=0` |
| R7 | API.md | **Endpoint yüzey bağımsızlığı:** L0 OpenAPI iş-verisi endpoint'i (GET /calls, /transcripts) yok; `l0_business_endpoint=0` |
| R8 | DB.md §6.4 | **Break-glass plane ayrımı:** content repo yalnız ayrı `break_glass_plane`'de, default'ta değil; `bg_in_default=0` |
| R9 | FR-IAM-009 | **Break-glass grant-gated:** content admission geçerli grant gerektirir (time-boxed; standing yok); `bg_standing_binding=0` |
| R10 | ADR-011 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi (forbidden sınıf boşaltma / grant-gated kaldırma) yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: plane/data_class/db_role/result düşük-kard; repository/table/PII metrikte yok |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız repo adı + tablo adı + sınıf + plane + rol enum + slug kimlik + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x deseniyle birebir: motor **doğru** design-time bağımsızlığı hesaplar, `inject` doğru davranışı
**bozar** ve eşleşen ihlal sayacını artırır → kapı eler. 10 enjeksiyon: `wire_content_in_platform`,
`wire_config_in_platform`, `grant_content_to_platform`, `expose_business_endpoint`, `bg_in_default_plane`,
`bg_standing`, `couple_planes`, `unclassify`, `model_tamper`, `secret_leak`.

**Anahtar defense-in-depth ispatı:** `wire_content_in_platform` tek başına (grant yok) →
`wired_forbidden_repo>0` **fakat** `data_reachable=0` (grant katmanı bağımsız tuttu). İki katman da regrese
(wire + grant) → `data_reachable>0`, kapı eler. (12.2.3 `app-bug-but-RLS-holds` ile aynı desen.)

## Dosyalar

- `config/repo-independence-model.json` — **frozen** model (`planes` [3] + `data_classes` [forbidden =
  tenant_content ∪ tenant_config] + `table_class_of` [37 varlık] + `repositories` [kayıt defteri] + `db_roles`
  [platform_ro grant'siz] + `break_glass` [ayrı plane; time-boxed]).
- `repo-independence-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + kapılar).
- `repo_independence_probe.py` — repo bağımsızlık karar motoru + `validate`/`check`/`selftest`/`schema`. 12.2.1
  `l0_business_data.delegated_to → 12.2.4` ve 12.2.3 RLS backstop **resiprokal** bağlantılarını doğrular.
- `samples/` (21: 12 pass + 9 degrade) + `tests/` (27 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 repo_independence_probe.py validate          # statik model + spec + 12.2.1/12.2.3 resiprokal
python3 repo_independence_probe.py selftest          # R1–R12 motoru
python3 repo_independence_probe.py check samples     # 12 pass + 9 degrade
python3 tests/repo_independence_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                                   # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| HTTP `enforce_tenant_scope` (çalışma-anı tenant scope) | 12.2.1 |
| PostgreSQL RLS çalışma-anı zorlama (**bu modülün backstop'u**) | 12.2.3 (TÜKETİLİR) |
| rol→permission-key bundle + rol+scope yetki kararı | 12.1.1 / 12.1.3 |
| Ayrı router ağaçları + ayrı OAuth scope | 12.2.2 |
| Break-glass **akışı** (maker-checker + bildirim + grant yaşam döngüsü) | 12.3.x |
| WORM / append-only audit | 12.1.8 |
| Repo/grant bağımsızlık CI (L0 import grafiği + grant manifesti) | 0.4.4 |

## Notlar

- **Vendor-neutral** (ADR-002/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (DB şifresi/connection string) ve ham içerik (transcript/recording/contact PII) repoya
  yazılmaz** — yalnız repository adı + tablo adı + veri-sınıfı + plane + db_role enum + slug request kimlik +
  sha256. Bu modül binding **admission kararını** verir; ham satır içeriği (PII) **akmaz**.
- Gerçek L0⟂tenant bağımsızlık enforcement (FastAPI kompozisyon kökü [L0 ayrı app] + `GRANT`/`REVOKE` DDL
  [`platform_ro`] + L0 OpenAPI [iş-verisi endpoint'i yok] + 0.4.4 repo/grant CI) **F1 kod aşamasında**; bu
  modül onlara kararı + kanıtı + model bütünlük manifestini iletir.
