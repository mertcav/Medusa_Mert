# WBS 12.1.6 — SCIM provisioning + IdP grup→rol eşleme

**Faz:** F2 · **Öncelik:** Should · **İz:** BRD §17.2 → **FR-IAM-007** → SR-IAM-007 → TC-IAM-007 (T) · FR-IAM-008 (tenant IdP L0 rolü provision edemez) · FR-TEN-002 · SAD §14.4.4 (SCIM 2.0 provisioning; deprovision → erişim anında düşer; grup→rol eşleme) · ADR-011/012/002

12. workstream'in (IAM & Erişim) **kullanıcı/grup yaşam döngüsü senkron** modülü. Kurumsal IdP'den gelen
**SCIM 2.0 provisioning** operasyonunu (create/replace/patch/deactivate/delete; User + Group) **deterministik,
fail-closed** doğrular, IdP **grup/attribute**'unu [`12.1.1`](../rbac-model/README.md) RBAC rollerine **eşler**
(eşleme tablosu = [`12.1.4`](../sso/README.md) SSO ile **AYNI** yüzey: `idp_config.group_role_map`) ve **çıktı
olarak etkin erişim `effective_access[{role, scope}]` ATAMA** üretir — bu, [`12.1.3`](../scoped-assignment/README.md)
scoped-assignment'ın **tükettiği** atama yüzeyidir. Terminal: **`PROVISIONED` | `NO_ACCESS` | `DEPROVISIONED` | `REJECTED`**.

**Çekirdek ilke (FR-IAM-007 / SAD §14.4.4):** *Kurumsal IdP ──SCIM 2.0 provisioning (kullanıcı + grup senkronu)──►
Platform Provisioning; IdP grup/attribute ──► tenant bazında rol eşleme tablosu ──► RBAC rol(leri) ──► permission set;
**deprovision → erişim ANINDA düşer**.* Yalnız **kimliği doğrulanmış + güvenilir SCIM istemcisi** provision eder; tenant
SCIM **yalnız tenant-realm** rol provision edebilir, platform (L0) rolünü **asla** (FR-IAM-008; L0 ayrı dizinden, ADR-011).

## Karar zinciri (fail-closed)

```
ScimRequest ─malformed─► operation ─► auth ─► schema ─► tenant ─► version ─► lifecycle ─► karar
   ├─ alan eksik/biçimsiz ──────────────────────────────────────────────► REJECTED (malformed_request)
   ├─ operation ∉ desteklenen küme ────────────────────────────────────► REJECTED (unsupported_operation)
   ├─ ¬scim_client.authenticated | güvenilmez client ───────────────────► REJECTED (unauthenticated)      [S2]
   ├─ resource.schema ∉ desteklenen | resourceType ∉ {User, Group} ─────► REJECTED (unsupported_schema)
   ├─ scim_client.tenant_id ≠ request tenant_id ───────────────────────► REJECTED (cross_tenant)         [S7]
   ├─ prior_version ≠ null ∧ version ≤ prior_version ───────────────────► REJECTED (version_conflict)     [S6]
   │
   ├─ DEPROVISION (deactivate/delete | active=false) ──────────────────► DEPROVISIONED (erişim ANINDA ∅ + oturum iptali)  [S3 ÇEKİRDEK]
   │
   └─ PROVISION (create/replace/patch, active≠false):
        ├─ eşlenen rol realm ≠ scim_client.realm (tenant SCIM → L0 rolü) ► REJECTED (realm_escalation)    [S4]
        ├─ eşlenen rol 12.1.1 modelinde yok ────────────────────────────► REJECTED (unknown_role)
        ├─ ∃ grup → rol (tenant tablosu, union) ────────────────────────► PROVISIONED effective_access[{role,scope}]  [S5]
        └─ hiçbir grup eşleşmez ────────────────────────────────────────► NO_ACCESS (no_role_mapping; default-deny)  [S8]
```

- **Auth kapısı** (S2): yalnız `authenticated` + güvenilir `client_id` SCIM istemcisi provision eder (bearer/mTLS soyut sonucu).
- **Deprovision kuralı** (S3 — **ÇEKİRDEK**): deactivate/delete veya `active=false` → **erişim anında düşer**:
  `effective_access=∅` + `revoke_active_sessions=true` (mevcut oturum/token iptal); idempotent (tekrar = no-op).
- **Version kapısı** (S6): iyimser eşzamanlılık — `version > prior_version` olmalı; bayat/sıra-dışı/tekrarlı op
  **REJECTED `version_conflict`**; deprovision edilen subject **bayat op ile dirilmez**.
- **Eşleme kapısı** (S5): grup → tenant eşleme tablosu (`idp_config.group_role_map`); gruplar arası **UNION**;
  bilinmeyen grup **atlanır**; eşleme yoksa **NO_ACCESS** (default-deny — provision olur ama yetki yok).
- **Realm kuralı** (S4): tenant SCIM **yalnız tenant-realm** rol; eşlenen rol realm = `scim_client.realm` (FR-IAM-008).
- **Tenant izolasyonu** (S7): `scim_client.tenant_id` = request tenant_id; aksi → **REJECTED `cross_tenant`** (FR-TEN-002).

**PROVISIONED** üretilen `effective_access[{role, scope}]` = 12.1.3'ün tükettiği **scoped atama** (narrowing-only). Eşleme
tablosu yalnız **daraltır** — rolün immutable bundle'ına permission **ekleyemez** (12.1.1/12.1.2).

**Örnek (SAD §14.4.4):** `user.create` + grup `voiceai-ops-manager` → `operations_manager@scope=brand-x` → **PROVISIONED**;
aynı subject `user.deactivate` → **DEPROVISIONED** (erişim anında ∅ + oturum iptali); tenant SCIM `platform_owner`
eşlerse → **REJECTED `realm_escalation`** (L0 ⟂ tenant).

## Model (`config/scim-model.json` — frozen)

- **Protokol:** SCIM 2.0 (RFC 7643 şema + RFC 7644 protokol); resourceType ∈ {User, Group}.
- **Operasyonlar:** provision = `user.create/replace/patch`, `group.create/replace/patch`; deprovision =
  `user.deactivate/delete`, `group.delete` (veya `active=false`).
- **Auth:** `auth_required`, `trusted_client_binding` (S2).
- **Deprovision (ÇEKİRDEK):** `drop_access_immediately`, `revoke_active_sessions`, `idempotent`, `propagation_immediate`.
- **Eşleme:** `source=idp_config.group_role_map` (12.1.4 SSO ile AYNI), `unknown_group_ignored`, `union_across_groups`,
  `default_deny`, `mapped_role_must_exist`, `scope_is_narrowing_only`.
- **Eşzamanlılık:** `idempotent_operations`, `optimistic_concurrency`, `require_monotonic_version`,
  `no_resurrect_deprovisioned_by_stale_op` (S6).
- **Realm ayrımı (FR-IAM-008):** `tenant_idp_grants_only_tenant_roles`, `platform_idp_separate_directory`.
- **Tenant izolasyonu (FR-TEN-002):** `client_bound_to_tenant`, `tenant_boundary_above_provisioning`.
- **Gizlilik (BRD §17.7):** `no_raw_pii_in_record`, `no_raw_token_persisted`, `subject_reference_opaque`.

## İnvariant'lar (S1–S12)

Çekirdek: **S3** deprovision → erişim anında düşer (`stale_access=0`; FR-IAM-007 ÇEKİRDEK), **S2** SCIM istemci auth
bütünlüğü (`untrusted_accepted=0`), **S4** realm/IdP sınırı (`realm_escalation=0`; FR-IAM-008), **S5** rol-eşleme
doğruluğu (`unmapped_role_granted=0`; SAD §14.4.4), **S7** tenant izolasyonu (`cross_tenant=0`; FR-TEN-002). **S6**
idempotency/sıra güvenliği (`conflict_accepted=0`), **S8** least-privilege default (`privilege_on_absence=0`). Her karar
terminal (S1) + yapısal kanıt (S9; ham token/PII yok) + model bütünlük manifesti (S10, `model_hash` sha256) +
düşük-kardinalite metrik (S11) + sızıntısız artifact (S12).

## Sağlayıcı-nötr / credential-free (ADR-002)

Bearer/mTLS doğrulaması bu modülde **yapılmaz** — `scim_client.authenticated` soyut doğrulama **sonucudur**. Canlı
SCIM 2.0 endpoint (RFC 7644) + token doğrulaması + IdP kullanıcı/grup senkronu **F2/PoC** entegrasyonunda. Fixture'lar
sentetik: yalnız SCIM istemci id + grup/rol adı + kapsam boyut ID + opak subject ref + version. **Sır/credential/
anahtar ve ham token/PII (bearer/NameID/e-posta/ad) repoya yazılmaz.**

## Çalıştırma

```bash
python3 scim_probe.py validate          # statik scim/rbac model + spec + kapsama → çıkış kodu
python3 scim_probe.py check samples      # 15 pass + 10 degrade/güvenlik-olayı senaryo
python3 scim_probe.py selftest           # gömülü davranış kontrolleri (S1–S12)
python3 scim_probe.py schema             # karar sözleşmesi
./run_live_test.sh                       # tümü + (varsa) SCIM_ENDPOINT_URL canlı NOT
```

| Komut | Sonuç |
|-------|-------|
| `validate` | 103/103 🟢 |
| `selftest` | 62/62 🟢 |
| `check samples` | 25/25 🟢 (15 pass + 10 fail) |
| `behavior test` | 45/45 🟢 |

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| rol→permission-key bundle çözümü (immutable; realm) | **12.1.1** (tüketilir) |
| permission-key gramer + tam kataloğu | **12.1.2** |
| rol+scope atama **kapsam** çözümü (kaynak attribute karşı) | **12.1.3** (bu modül atamayı **üretir**) |
| SSO login assertion doğrulama (SAML2/OIDC) | **12.1.4** (grup→rol eşleme tablosu **AYNI** yüzey) |
| MFA (çok faktörlü doğrulama) | 12.1.5 (FR-IAM-003) |
| Backend panel guard (oturum→permission-key HTTP enforcement; deprovision → oturum iptali) | 12.2.x |
| Append-only WORM audit (provisioning kararı) | 12.1.8 |
| Canlı SCIM 2.0 endpoint + bearer/mTLS token + IdP senkronu | F2 / PoC |
