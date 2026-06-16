# WBS 12.2.3 — Tenant scope + RLS çift kontrol (defense in depth)

**Faz:** F1 · **Öncelik:** Must · **İz:** DB.md §6 → **FR-TEN-002** (tenant izolasyonu) · SAD §14.4.2 (tenant scope RLS çift kontrol) · **FR-IAM-008** (L0 ⟂ tenant) · **FR-IAM-009** (break-glass) · SR-TEN-002 → TC-TEN-002 · ADR-011 · ADR-006

12. workstream'in (IAM & Erişim) **DB-seviyesi tenant izolasyon** modülü. SAD §14.4.2 + DB.md §6.1'in temel
kararını sahiplenir: *"İzolasyon iki katmanlıdır (P2, defense in depth): uygulama her isteğe `tenant_id`
scope'u uygular **ve** PostgreSQL RLS aynı `tenant_id`'yi **bağımsız** zorlar. Uygulama bug'ı tenant
sızıntısına dönüşmez."* Bir DB erişim isteği (`RlsAccessRequest`) için **deterministik, fail-closed** bir RLS
kararı verir. Terminal: **`PERMIT` | `DENY`**.

**Uygulama (app_level) katmanını [`12.2.1`](../backend-guard/README.md) `enforce_tenant_scope`'tan TÜKETİR**
(resiprokal: 12.2.1 `guard-model.json` → `tenant_double_check.rls_level = delegated_to_12.2.3`); üzerine
PostgreSQL **RLS bağımsız ikinci katmanını** ekler. Birleşim AND'tir: **`served ⟺ app_permit ∧ rls_permit`**.

## Kavramsal sözleşme (DB.md §6)

```sql
-- uygulama (12.2.1): enforce_tenant_scope(ctx, resource_tenant_of(id))   # HTTP cross-tenant reddi
-- DB (bu modül): SET LOCAL app.tenant_id = '<uuid>';  app_rw rolü (BYPASSRLS yok); FORCE ROW LEVEL SECURITY
CREATE POLICY tenant_isolation ON <tablo>
    USING       (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK  (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

## Karar akışı (gate)

```
RlsAccessRequest ─malformed─► RLS altyapı ─► policy coverage ─► GUC fail-closed ─► tablo-policy ─► çift-kontrol
      ├─ request_id/realm/table_class/operation/row eksik|geçersiz ──────────────► DENY (malformed)
      ├─ bypass rolü (superuser/BYPASSRLS) | RLS off | FORCE off | policy yok ───► rls_protected=false [R2/R3]
      ├─ eff = NULLIF(app.tenant_id,''); unset/empty → eff NULL ─────────────────► fail-closed (DENY)   [R4]
      ├─ tablo-sınıfı policy (USING/WITH CHECK + break_glass_read) ──────────────► rls_permit            [R5..R8]
      └─ served = app_permit ∧ rls_permit; cross-tenant ∧ served ───────────────► cross_tenant_leak/write[R5/R6]
```

## Çift kontrol (defense in depth — P2)

İzolasyon **iki bağımsız katmanda** zorlanır. Anahtar güvence: **RLS, uygulama kararını AYNALAMAZ** — ayrı
GUC + ayrı policy ile bağımsız değerlendirir. Bir uygulama bug'ı (scope unutma / yanlış tenant / guard bypass)
cross-tenant satırı yanlışlıkla geçirse bile RLS bağımsız olarak `DENY` döner → satır **servis edilmez**.

| Katman | Sahip | Mekanizma |
|--------|-------|-----------|
| **app_level** | 12.2.1 (TÜKETİLİR) | HTTP `enforce_tenant_scope` (resource.tenant_id = session tenant) |
| **rls_level** | **12.2.3 (bu modül)** | `SET LOCAL app.tenant_id` + `tenant_isolation` policy (USING/WITH CHECK) + `FORCE ROW LEVEL SECURITY` + `app_rw` (BYPASSRLS yok) |

## Tablo sınıfına göre politika matrisi (DB.md §6.3)

| Sınıf | Örnek | RLS politikası |
|-------|-------|----------------|
| `tenant_scoped` | call, transcript, contact, campaign (28+) | `tenant_isolation` USING/WITH CHECK = `tenant_id = eff` |
| `root_tenant` | tenant | `id = eff` OR platform realm |
| `global_reference` | role, permission_key | RLS yok (salt-okunur referans) |
| `platform_mixed` | audit_log, incident | `tenant_id = eff` OR (`tenant_id IS NULL` AND platform) |
| `platform_only` | break_glass_grant | yalnız platform realm |

`eff = NULLIF(current_setting('app.tenant_id', true), '')::uuid` — **fail-closed**: GUC set edilmemiş (NULL)
ya da havuzda-resetlenmiş (`''`) → `eff` NULL → hiçbir satır. Çıplak `''::uuid` *hata* fırlatırdı (fail-error).

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **DENY** (fail-closed); kanıt; `model_hash` sha256; `stuck_state`/`missing_evidence=0` |
| **R2** | **DB.md §6.1** | **RLS etkin+FORCE+bypass-etmeyen rol:** ENABLE+FORCE ROW LEVEL SECURITY + `app_rw` (superuser/BYPASSRLS yok); `rls_disabled`/`force_missing`/`bypass_role=0` |
| R3 | DB.md §6.3/§10 | **Policy coverage:** her iş verisi tablosunda `tenant_isolation`; RLS'siz tablo merge edilemez (0.4.4 CI); `missing_policy=0` |
| **R4** | **DB.md §6.2** | **GUC fail-closed NULLIF:** unset/empty GUC → hiçbir satır; `''::uuid` hata değil; `guc_fail_open`/`guc_fail_error=0` |
| **R5** | **FR-TEN-002** | **Çift kontrol / sızıntı yok:** RLS bağımsız zorlar; cross-tenant satır app izin verse bile DENY; uygulama bug'ı sızmaz; `cross_tenant_leak=0` |
| R6 | DB.md §6.2 | **WITH CHECK yazım koruması:** cross-tenant insert/update reddedilir; `cross_tenant_write=0` |
| R7 | FR-IAM-008/ADR-011 | **Platform scoping:** L0 ⟂ tenant business PII (break-glass hariç); `platform_overreach=0` |
| **R8** | **DB.md §6.4** | **Break-glass time-boxed:** Tier B okuma yalnız platform+geçerli grant+süre dolmamış; standing access yok; `bg_standing_access=0` |
| R9 | DB.md §6.1 | **SET LOCAL transaction-scoped:** havuz sızıntısı yok; `guc_pool_leak=0` |
| R10 | ADR-011 | Model bütünlük manifesti (`model_hash` sha256); çalışma-anı tahrifi (FORCE off / time-box kaldırma) yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: table_class/operation/result/actor_realm düşük-kard; row.tenant_id/PII metrikte yok |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız tablo adı + sınıf + GUC adı + policy adı + operation/realm enum + slug kimlik + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.1 deseniyle birebir: motor **doğru** RLS davranışını hesaplar, `inject` doğru davranışı **bozar**
ve eşleşen ihlal sayacını artırır → kapı eler. 13 enjeksiyon: `rls_disable`, `force_off`, `bypass_role`,
`missing_policy`, `guc_fail_open`, `bare_uuid_cast`, `pool_leak`, `app_only_trust`, `write_bypass`,
`platform_overreach`, `bg_standing`, `model_tamper`, `secret_leak`.

## Dosyalar

- `config/rls-model.json` — **frozen** RLS modeli (`guc` [NULLIF fail-closed; SET LOCAL] + `db_role` [app_rw;
  FORCE; BYPASSRLS=false] + `table_classes` [5] + `tenant_scoped_tables` + `break_glass` [time-boxed] + `double_check`).
- `rls-double-check-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + kapılar).
- `rls_double_check_probe.py` — RLS çift-kontrol karar motoru + `validate`/`check`/`selftest`/`schema`. 12.2.1
  guard-model'in **resiprokal** `rls_level → 12.2.3` bağlantısını doğrular (çift kontrol mutabakatı).
- `samples/` (24: 12 pass + 12 degrade/güvenlik) + `tests/` (32 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 rls_double_check_probe.py validate          # statik RLS model + spec + 12.2.1 resiprokal bağlantı
python3 rls_double_check_probe.py selftest          # R1–R12 motoru
python3 rls_double_check_probe.py check samples     # 12 pass + 12 degrade
python3 tests/rls_double_check_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                                  # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| HTTP `enforce_tenant_scope` (uygulama katmanı çift kontrol) | **12.2.1** (TÜKETİLİR/app_level) |
| rol→permission-key bundle + rol+scope yetki kararı | 12.1.1 / 12.1.3 |
| Ayrı router ağaçları + ayrı OAuth scope | 12.2.2 |
| L0 iş verisi repository bağımsızlığı | 12.2.4 |
| Break-glass akışı (maker-checker + bildirim + grant yaşam döngüsü) | 12.3.x |
| WORM / append-only **değişmezlik** (audit_log/consent/agent_version) | 12.1.8 / DB.md §6.5 |
| RLS migration CI (RLS'siz tablo merge edilemez) | 0.4.4 |

## Notlar

- **Vendor-neutral** (ADR-002/006/011); **stdlib-only**, **credential-free**, **deterministik**.
- **Sır/credential (DB şifresi/connection string) ve ham içerik (transcript/recording/contact PII) repoya
  yazılmaz** — yalnız tablo adı + tablo-sınıfı + GUC adı + policy adı + operation/realm enum + slug tenant/
  request kimlik + sha256. Tenant kimliği **yapısal slug** (`t-acme`) ile temsil edilir, gerçek uuid değil.
- Gerçek PostgreSQL RLS enforcement (DDL/policy + `SET LOCAL app.tenant_id` wiring + `app_rw` rolü +
  1.2.1 migration + 0.4.4 RLS CI + 12.3.x break-glass) **F1 kod aşamasında**; bu modül onlara kararı + kanıtı
  + model bütünlük manifestini iletir.
