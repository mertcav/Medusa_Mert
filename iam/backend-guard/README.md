# WBS 12.2.1 — Backend guard: panel + rol + tenant scope (FastAPI dependency)

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.2 → **FR-IAM-008** (panel-katman rol ayrımı) · **FR-TEN-002** (tenant izolasyonu) · **FR-IAM-011** (scoped assignment) · SR-IAM-008 → TC-IAM-008 · ADR-011 · ADR-012 · API.md (`x-required-permission`)

12. workstream'in (IAM & Erişim) **HTTP enforcement** modülü. SAD §14.4.2'nin temel kararını sahiplenir:
*"Her endpoint **üç boyutta** korunur: **panel + rol + tenant scope**. FastAPI dependency'leri (guard) ile
uygulanır."* Bir HTTP guard isteği (`HttpGuardRequest`) için **deterministik, fail-closed** bir karar verir.
Terminal: **`ALLOW`(200) | `DENY`(403) | `BLOCK`(401/403)**.

Kararı [`12.1.1`](../rbac-model/README.md) (rol→**IMMUTABLE** bundle + `layer`/`realm`) ve
[`12.1.3`](../scoped-assignment/README.md) (rol+scope) modüllerinden **tüketir/delege eder**; üzerine HTTP
guard'ın **üç boyutunu** ekler.

## Kavramsal sözleşme (SAD §14.4.2)

```python
@router.get("/calls/{id}", dependencies=[Depends(require(perm="calls:read", panel="L2"))])
async def get_call(id, ctx: AuthCtx = Depends(auth_ctx)):
    enforce_tenant_scope(ctx, resource_tenant_of(id))   # cross-tenant erişim reddi
```

## Üç boyut (gate)

```
HttpGuardRequest ─malformed─► authn ─► PANEL gate ─► TENANT scope gate ─► [DELEGE 12.1.3 rol+scope] ─► karar
      ├─ endpoint/panel/required eksik | required biçimsiz | atama yok | resource yok ─► BLOCK malformed_request
      ├─ doğrulanmış kimlik yok ──────────────────────────────────────────────────────► BLOCK unauthenticated (401)
      ├─ token realm ≠ panel realm (L0↔tenant) ──────────────────────────────────────► BLOCK panel_realm_mismatch [S2]
      ├─ token OAuth scope ≠ panel scope ────────────────────────────────────────────► BLOCK oauth_scope_mismatch [S2]
      ├─ hiçbir atama rol katmanı paneli kapsamaz ───────────────────────────────────► BLOCK panel_not_covered    [S2]
      ├─ resource.tenant_id ≠ session tenant (tenant paneli) ────────────────────────► BLOCK cross_tenant_resource[S5]
      ├─ DELEGE 12.1.3 = GRANT ──────────────────────────────────────────────────────► ALLOW  (handler çalışır)   [S4]
      ├─ DELEGE 12.1.3 = DENY  ──────────────────────────────────────────────────────► DENY   (403)               [S4]
      └─ DELEGE 12.1.3 = BLOCK ──────────────────────────────────────────────────────► BLOCK  (403)               [S4]
```

1. **PANEL gate** (S2 — bu modülün yeni çekirdeği): endpoint paneli (`L0`/`L1`/`L2`) için (a) token **realm**
   = panel realm (`L0`→platform, `L1`/`L2`→tenant); (b) token **OAuth scope** = panel scope (`panel:L0/L1/L2`);
   (c) **≥1 atama rol katmanı** (12.1.1 `layer`; `L1+L2` → `{L1,L2}`) paneli kapsar. **L0 ⟂ tenant**
   (FR-IAM-008/ADR-011): L0 endpoint'i tenant token'ıyla — veya tersi — **açılamaz**.
2. **ROL gate** (S4 — **delege**): required permission-key + assignment scope → **12.1.3 scoped-assignment**
   (o da 12.1.1 immutable bundle'ı + `:own` + department/brand/campaign narrowing çözer). `ALLOW ⟺ GRANT`;
   guard **asla fail-open yapmaz**.
3. **TENANT SCOPE gate** (S5): tenant panellerinde session tek `tenant_id`'ye bağlı; `resource.tenant_id ≠
   session tenant` → **BLOCK** (HTTP `enforce_tenant_scope`); PostgreSQL **RLS çift kontrol** → 12.2.3 delege.

**Karar her zaman backend'de** (`decision_at=backend`); yetki **yalnız doğrulanmış token'dan**
(`trust_source=verified_token_only`) — client-supplied iddia güvenilmez (S6); UI yalnız görsel kapı.

## Reason taksonomileri

- **BLOCK:** `malformed_request`, `unauthenticated`, `panel_realm_mismatch`, `oauth_scope_mismatch`,
  `panel_not_covered`, `cross_tenant_resource`, `unknown_role`/`realm_layer_mismatch` (12.1.3 delege'den).
- **DENY** (12.1.3'ten devralınır): `missing_permission`, `insufficient_scope`, `out_of_scope`.
- **HTTP:** `ALLOW`→200, `DENY`→403, `BLOCK`→ kimlik yoksa 401, aksi 403.

## İnvariant'lar (S1–S12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| S1 | | Determinizm/terminal; varsayılan **BLOCK** (fail-closed); `model_hash` sha256; `stuck_state=0` |
| **S2** | **FR-IAM-008 / ADR-011** | **Panel izolasyonu:** token realm + OAuth scope + rol-katman kapsama; L0 ⟂ tenant; `panel_violation`/`scope_violation`/`realm_violation=0` |
| S3 | API.md | **Deklarasyon zorunlu:** endpoint geçerli `x-required-permission` deklare etmeli; eksikse fail-closed; `undeclared_endpoint=0` |
| **S4** | **SAD §14.4.2** | **Delege doğruluğu:** `ALLOW ⟺ 12.1.3 GRANT`; guard fail-open yapmaz; `fail_open_grant=0` |
| **S5** | **FR-TEN-002** | **Tenant scope:** `resource.tenant_id = session tenant` (HTTP enforce + RLS çift kontrol 12.2.3); `cross_tenant=0` |
| **S6** | **SAD §14.4.2** | **Backend otoritesi:** yetki yalnız doğrulanmış token'dan; client iddia güvenilmez; `client_trust_violation=0` |
| S7 | FR-IAM-008 | L0 ⟂ tenant iş verisi (repo bağımsızlığı 12.2.4'e; break-glass 12.3.x'e delege; S2 ile geçiş engellenir) |
| S8 | FR-IAM-011 | Immutable bundle korunur (12.1.1/12.1.3'ten); guard yalnız enforcement, yetki yüzeyini değiştirmez |
| S9 | FR-IAM-006 | Kanıt: request + panel + assignments + resource + http_status + delegated_terminal + model_hash; `missing_evidence=0` |
| S10 | ADR-011/012 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi yakalanır; `model_tampered=0` |
| S11 | 0.4.7 | Gözlemlenebilirlik kardinalite: result/panel/actor_realm düşük-kard; request_id/PII metrikte yok |
| S12 | BRD §17.7 | Sır/içerik yok: yalnız rol/permission-key/panel/scope enum + kapsam ID + kimlik + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x deseniyle birebir: motor **doğru** davranışı hesaplar, `inject` doğru davranışı **bozar** ve eşleşen
ihlal sayacını artırır → kapı eler. 9 enjeksiyon: `panel_bypass`, `oauth_scope_bypass`, `realm_cross`,
`tenant_bypass`, `fail_open`, `client_claim_trust`, `missing_perm_decl`, `model_tamper`, `secret_leak`.

## Dosyalar

- `config/guard-model.json` — **frozen** guard modeli (panels + `panel_realm` + `panel_oauth_scope` +
  `layer_covers` + `http_status` + `fail_closed` + `trust_source`).
- `backend-guard-spec.json` — makine-okunur spec (7 kural + karar + taksonomiler + S1–S12 + kapılar).
- `backend_guard_probe.py` — üç-gate karar motoru + `validate`/`check`/`selftest`/`schema`. **12.1.3'ü canlı
  delege eder** (importlib; tek kaynak doğruluk — rol+scope mantığı çoğaltılmaz).
- `samples/` (21: 12 pass + 9 degrade/güvenlik) + `tests/` (32 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 backend_guard_probe.py validate          # statik guard/rbac model + spec + delege erişimi
python3 backend_guard_probe.py selftest          # S1–S12 motoru
python3 backend_guard_probe.py check samples     # 12 pass + 9 degrade
python3 tests/backend_guard_behavior_test.py     # bağımsız S1–S12 (12.1.3 canlı delege)
./run_live_test.sh                               # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| rol→permission-key bundle çözümü (immutable; `:own`; `layer`/`realm`) | **12.1.1** (tüketilir) |
| rol+scope yetki kararı (department/brand/campaign narrowing) | **12.1.3** (delege) |
| permission-key gramer + tam kataloğu | 12.1.2 |
| Ayrı router ağaçları + ayrı OAuth scope + ayrı deploy | **12.2.2** |
| Tenant scope **PostgreSQL RLS** çift kontrol (DB seviyesi) | **12.2.3** |
| L0 iş verisi repository bağımsızlığı | 12.2.4 |
| Break-glass (Tier B kapsam-üstü erişim) | 12.3.x |
| WORM audit log | 12.1.8 |

## Notlar

- **Vendor-neutral** (ADR-001/002/011/012); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (bearer token DEĞERİ dahil) ve ham içerik (PII) repoya yazılmaz** — yalnız rol adı +
  permission-key + panel/realm/scope enum + kapsam boyut ID + yapısal kimlik + sha256.
- Gerçek FastAPI enforcement (`require()`/`auth_ctx`/`enforce_tenant_scope` wiring) **F1 kod aşamasında**;
  bu modül onlara kararı + kanıtı + model bütünlük manifestini iletir.
