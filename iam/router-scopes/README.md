# WBS 12.2.2 — L0/L1/L2 ayrı router ağaçları + ayrı OAuth scope

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.2 → **FR-IAM-008** (panel-katman ayrımı) · **FR-TEN-002** (tenant izolasyonu) · ADR-011 (iki düzlemli panel dağıtımı) · API.md §2/§4.1 (yüzey ayrımı + base path'ler) · SR-IAM-008 → TC-IAM-008

12. workstream'in (IAM & Erişim) **router/scope TOPOLOJİSİ** modülü. SAD §14.4.2'nin yapısal kararını sahiplenir:
*"**Ayrı router/scopes + ayrı deploy:** L0 endpoint'leri ayrı bir servis (Platform Control Plane, internal-only)
ve ayrı auth realm'de; L1/L2 endpoint'leri Tenant Application Plane'de **ayrı router ağaçları ve OAuth scope'larında**
tanımlanır (ADR-011)."* Bir router senaryosu (`RouterScenario`: mounts + request) için **deterministik, fail-closed**
bir karar verir. Terminal: **`ADMIT`(200) | `REJECT`(401/403) | `MISCONFIG`(403)**.

Bu modül [`12.2.1`](../backend-guard/README.md) backend-guard'ın **per-request** üç-boyutlu kararının
**ÖNÜNDEKİ** yapısal/dağıtımsal katmandır: her panel (L0/L1/L2) **ayrı bir router ağacına** + **ayrı bir OAuth
scope'a** + bir **deploy düzlemine** bağlanır. `ADMIT` edilen istek 12.2.1'e **devredilir** (admission **gerekli
ama yeterli değil**). Scope/realm **tek kaynağı** 12.2.1 `guard-model.json`'dur (S6 — yeniden tanımlamaz).

## Kavramsal sözleşme (SAD §14.4.2 / ADR-011)

```python
# Platform Control Plane (internal-only, AYRI servis/origin/realm — ADR-011)
platform_router = APIRouter(prefix="/platform/v1",
                            dependencies=[Depends(require_scope("panel:L0"))])   # router-seviyesi OAuth scope

# Tenant Application Plane (public) — AYRI router ağaçları + AYRI OAuth scope
admin_router = APIRouter(prefix="/admin/v1", dependencies=[Depends(require_scope("panel:L1"))])
ops_router   = APIRouter(prefix="/ops/v1",   dependencies=[Depends(require_scope("panel:L2"))])
# admission sonrası endpoint'in require(perm, panel) guard'ı (12.2.1) çalışır — admission yeterli DEĞİL
```

## İki düzlem + üç ağaç (ADR-011)

```
Platform Control Plane (internal-only; VPN/allowlist/private-endpoint; realm=platform)
  └─ L0 ağacı  /platform/v1  scope=panel:L0
Tenant Application Plane (public; realm=tenant)
  ├─ L1 ağacı  /admin/v1     scope=panel:L1
  └─ L2 ağacı  /ops/v1       scope=panel:L2
L0 ağacı tenant düzlemine (veya tersi) ASLA mount edilemez (blast-radius izolasyonu).
```

## Karar akışı (gate)

```
RouterScenario ─malformed─► MOUNT integrity ─► [topoloji bütünlüğü] ─► REQUEST-time routing ─► karar
      ├─ request_id/mount eksik | mounted_tree yok ─────────────────────────► MISCONFIG malformed_topology
      ├─ endpoint paneli ≠ mount edilen ağaç paneli ───────────────────────► MISCONFIG panel_tree_mismatch [S2]
      ├─ aynı endpoint >1 ağaçta ──────────────────────────────────────────► MISCONFIG multi_tree_mount   [S2]
      ├─ doğrulanmış kimlik yok ───────────────────────────────────────────► REJECT unauthenticated (401)
      ├─ istek yanlış düzlem/origin'de (L0 ⟂ tenant) ──────────────────────► REJECT wrong_plane_origin    [S3]
      ├─ token realm ≠ ağaç realm ─────────────────────────────────────────► REJECT router_realm_mismatch [S5]
      ├─ token OAuth scope ≠ ağaç scope ───────────────────────────────────► REJECT router_scope_mismatch [S4]
      └─ hepsi geçer ──────────────────────────────────────────────────────► ADMIT → DEVREDİLİR 12.2.1    [S8]
```

1. **MOUNT bütünlüğü** (S2 — çekirdek): her endpoint **tam bir** panel ağacına mount; endpoint paneli = ağaç
   paneli (**cross-panel mount YOK**); bir endpoint birden çok ağaçta olamaz. Aksi → fail-closed `MISCONFIG`.
2. **DÜZLEM ayrımı** (S3 — çekirdek): L0 ağacı **ayrı internal-only** Platform Control Plane'de; **L0 ⟂ tenant**;
   request yanlış düzlem/origin'de gelirse `REJECT wrong_plane_origin` (ADR-011 blast-radius).
3. **AYRI/ANLAŞMAZ OAuth scope** (S4 — çekirdek): her ağaç **kendi** scope'unu (`panel:L0/L1/L2`) **router-seviyesi
   dependency** ile (handler'dan **önce**) zorlar; scope'lar pairwise disjoint; token scope ≠ ağaç scope → `REJECT`.
4. **router REALM** (S5): token realm = ağaç realm (L0→platform, L1/L2→tenant).
5. **12.2.1 TUTARLILIK** (S6): topoloji `oauth_scope`/`realm` = guard-model `panel_oauth_scope`/`panel_realm` (tek kaynak).
6. **DEVİR** (S8): `ADMIT` **gerekli ama yeterli değil** → 12.2.1 backend-guard'ın panel+rol+tenant kapısına devredilir.

## Reason taksonomileri

- **REJECT** (request-time, meşru): `unauthenticated`, `wrong_plane_origin`, `router_realm_mismatch`, `router_scope_mismatch`.
- **MISCONFIG** (deploy-time, fail-closed): `malformed_topology`, `panel_tree_mismatch`, `multi_tree_mount`,
  `plane_misplacement`, `scope_collision`, `missing_scope_dependency`, `consistency_mismatch`.
- **HTTP:** `ADMIT`→200, `REJECT`→ kimlik yoksa 401 aksi 403, `MISCONFIG`→403.

## İnvariant'lar (S1–S12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| S1 | | Determinizm/terminal; varsayılan **MISCONFIG** (fail-closed); `model_hash` sha256; `stuck_state=0` |
| **S2** | **FR-IAM-008 / ADR-011** | **Ayrı router ağaçları:** endpoint paneli = ağaç paneli; cross-panel mount YOK; tekil mount; `tree_mount_violation=0` |
| **S3** | **ADR-011** | **Düzlem/deploy ayrımı:** L0 ayrı internal-only Platform Control Plane; L0 ⟂ tenant; `plane_violation=0` |
| **S4** | **SAD §14.4.2** | **Ayrı/anlaşmaz OAuth scope:** router-seviyesi scope dependency; `panel:L0/L1/L2` disjoint; `scope_violation=0` |
| S5 | FR-IAM-008 | **Router realm:** token realm = ağaç realm; `realm_violation=0` |
| **S6** | **12.2.1** | **Tutarlılık:** topoloji scope/realm = guard-model (tek kaynak); `consistency_violation=0` |
| S7 | API.md §4.2 | **Scope dependency zorunlu:** her korumalı ağaç router-seviyesi scope dependency deklare etmeli; `missing_scope_dependency=0` |
| **S8** | **SAD §14.4.2** | **Devir:** router admission gerekli ama YETERLİ DEĞİL → 12.2.1'e devredilir; `delegation_violation=0` |
| S9 | FR-IAM-006 | Kanıt: mounts + target_tree + arrived_plane + token claim + terminal + http_status + delegated_to + model_hash; `missing_evidence=0` |
| S10 | ADR-011 | Model bütünlük manifesti (`model_hash` sha256; topoloji + 12.2.1 scope/realm); `model_tampered=0` |
| S11 | 0.4.7 | Gözlemlenebilirlik kardinalite: result/tree/plane düşük-kard; request_id/endpoint/origin metrikte yok |
| S12 | BRD §17.7 | Sır/içerik yok: yalnız panel/realm/scope enum + prefix + origin + yapısal kimlik + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.2.1 deseniyle birebir: motor **doğru** topoloji davranışını hesaplar, `inject` doğru davranışı **bozar** ve
eşleşen ihlal sayacını artırır → kapı eler. 10 enjeksiyon: `cross_panel_mount`, `plane_collapse`, `scope_reuse`,
`scope_bypass`, `realm_cross`, `scope_dep_drop`, `consistency_break`, `admit_sufficient`, `model_tamper`,
`secret_leak`.

## Dosyalar

- `config/router-topology.json` — **frozen** topoloji (planes + router_trees [prefix/plane/realm/oauth_scope/
  router_scope_dependency] + scope_disjoint + http_status).
- `router-scopes-spec.json` — makine-okunur spec (7 kural + karar + taksonomiler + S1–S12 + kapılar).
- `router_scopes_probe.py` — router/scope topoloji karar motoru + `validate`/`check`/`selftest`/`schema`. **12.2.1'i
  canlı devreder** (importlib; admission → guard-model tutarlılık [S6] + per-request kararı [S8]).
- `samples/` (19: 10 pass [4 ADMIT + 4 REJECT + 2 MISCONFIG] + 9 degrade) + `tests/` (S1–S12) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 router_scopes_probe.py validate          # statik topoloji + spec + 12.2.1 guard-model tutarlılığı + devir
python3 router_scopes_probe.py selftest          # S1–S12 motoru
python3 router_scopes_probe.py check samples     # 10 pass + 9 degrade
python3 tests/router_scopes_behavior_test.py     # bağımsız S1–S12 (12.2.1 canlı devir)
./run_live_test.sh                               # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| Per-request panel + rol + tenant guard kararı | **12.2.1** (devredilir) |
| rol→permission-key bundle (immutable) | 12.1.1 |
| rol+scope yetki kararı (department/brand/campaign narrowing) | 12.1.3 |
| Tenant scope **PostgreSQL RLS** çift kontrol (DB seviyesi) | 12.2.3 |
| L0 iş verisi repository bağımsızlığı | 12.2.4 |
| Break-glass (Tier B; ayrı kısıtlı router ailesi) | 12.3.x |
| WORM audit log | 12.1.8 |

## Notlar

- **Vendor-neutral** (ADR-001/002/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (bearer token DEĞERİ dahil) ve ham içerik (PII) repoya yazılmaz** — yalnız panel/realm/scope
  enum + router prefix + origin host + yapısal kimlik + sha256.
- Gerçek FastAPI enforcement (`APIRouter(prefix=...)` ağaçları + router-level `Depends(require_scope)` + iki
  düzlemli deploy + 12.2.1 guard wiring) **F1 kod aşamasında**; bu modül onlara topoloji kararını + kanıtı +
  model bütünlük manifestini iletir. Public Developer API (S4 — `/public/v1`) ayrı bir router ağacıdır ama
  panel değildir (kapsam dışı; API.md §2).
