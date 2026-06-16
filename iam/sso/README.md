# WBS 12.1.4 — SSO: SAML 2.0 + OIDC

**Faz:** F2 · **Öncelik:** Must · **İz:** BRD §17.2 → **FR-IAM-002** → SR-IAM-002 → TC-IAM-002 (T) · FR-IAM-008 (tenant IdP L0 rolü atayamaz) · FR-TEN-002 · SAD §14.4.4 (grup→rol eşleme) · SAD §13.3 · ADR-011/012/002

12. workstream'in (IAM & Erişim) **kurumsal SSO federasyon** modülü. Kurumsal IdP'den (SAML 2.0 / OIDC) gelen
**assertion**'ı (SAML Response / OIDC ID token) **deterministik, fail-closed** doğrular, IdP **grup/attribute**'unu
[`12.1.1`](../rbac-model/README.md) RBAC rollerine **eşler** ve **çıktı olarak `{role, scope}` ATAMA** üretir —
bu, [`12.1.3`](../scoped-assignment/README.md) scoped-assignment'ın **tükettiği** atama yüzeyidir. Terminal:
**`GRANT` | `DENY` | `BLOCK`**.

**Çekirdek ilke (FR-IAM-002 / SAD §14.4.4):** *Kurumsal IdP (SAML 2.0/OIDC) ──login──► Platform AuthN; IdP
group/SAML attribute ──► tenant bazında rol eşleme tablosu ──► RBAC rol(leri) ──► permission set.* Yalnız
**imzası doğrulanmış + güvenilir issuer'lı + audience'ı bağlı + süresi geçerli + tekrarsız (replay'siz)**
assertion authenticate eder; tenant IdP **yalnız tenant-realm** rol assert edebilir, platform (L0) rolünü
**asla** (FR-IAM-008; L0 ayrı dizinden federe, ADR-011).

## Karar zinciri (fail-closed)

```
SsoLoginRequest ─malformed─► protocol ─► signature ─► issuer ─► audience ─► temporal ─► replay ─► tenant ─► realm ─► mapping ─► karar
   ├─ alan eksik/biçimsiz ──────────────────────────────────────────────► BLOCK (malformed_request)
   ├─ protocol ∉ {saml2, oidc} ────────────────────────────────────────► BLOCK (unsupported_protocol)
   ├─ signature_required ∧ ¬signature_valid ──────────────────────────► BLOCK (invalid_signature)    [S2]
   ├─ issuer ≠ trusted_issuer ─────────────────────────────────────────► BLOCK (untrusted_issuer)     [S2/S5]
   ├─ audience ≠ expected_audience ────────────────────────────────────► BLOCK (audience_mismatch)    [S5]
   ├─ now > exp+skew | now < nbf−skew | now−iat > max_age+skew ────────► BLOCK (assertion_expired)    [S6]
   ├─ assertion_id ∈ seen ─────────────────────────────────────────────► BLOCK (replay_detected)      [S8]
   ├─ idp_config.tenant_id ≠ request tenant_id ───────────────────────► BLOCK (cross_tenant)         [S7]
   ├─ eşlenen rol realm ≠ idp realm (tenant IdP → L0 rolü) ───────────► BLOCK (realm_escalation)     [S4]
   ├─ eşlenen rol 12.1.1 modelinde yok ───────────────────────────────► BLOCK (unknown_role)
   ├─ ∃ grup → rol (tenant tablosu, union) ───────────────────────────► GRANT assignments[{role,scope}]
   ├─ hiçbir grup eşleşmez ────────────────────────────────────────────► DENY  (no_role_mapping)
   └─ subject pasif (deprovision) ────────────────────────────────────► DENY  (account_disabled)
```

- **Güven kapısı** (S2/S5): imza + güvenilir issuer + audience bağı → assertion **kabulü**.
- **Zaman kapısı** (S6): `expires_at` / `not_before` / `max_age` (clock skew toleransıyla).
- **Replay kapısı** (S8): `assertion_id` (SAML AssertionID / OIDC `jti`) pencere içinde **tek kullanımlık**.
- **Eşleme kapısı** (S3): grup → tenant eşleme tablosu (`idp_config.group_role_map`); gruplar arası **UNION**;
  bilinmeyen grup **atlanır**; eşleme yoksa **DENY `no_role_mapping`** (authenticate olur ama yetki yok).
- **Realm kuralı** (S4): tenant IdP **yalnız tenant-realm** rol; eşlenen rol realm = `idp_config.realm`.

**GRANT** üretilen `assignments[{role, scope}]` = 12.1.3'ün tükettiği **scoped atama** (narrowing-only). Eşleme
tablosu yalnız **daraltır** — rolün immutable bundle'ına permission **ekleyemez** (12.1.1/12.1.2).

**Örnek (SAD §14.4.4):** grup `voiceai-ops-manager` → `operations_manager@scope=brand-x`. İmzalı/güvenilir/
geçerli assertion → **GRANT**; aynı tenant IdP `platform_owner` döndürürse → **BLOCK `realm_escalation`** (L0 ⟂ tenant).

## Model (`config/sso-model.json` — frozen)

- **Protokoller:** `saml2`, `oidc` (FR-IAM-002). Liste dışı → `unsupported_protocol`.
- **Güven gereksinimleri:** `signature_required`, `trusted_issuer_binding`, `audience_binding`, `replay_protection`.
- **Zaman:** `honor_expires_at/not_before/max_age` + `default_clock_skew_seconds` + `default_max_assertion_age_seconds`.
- **Eşleme:** `source=idp_config.group_role_map` (tenant bazında), `unknown_group_ignored`, `union_across_groups`,
  `default_deny`, `mapped_role_must_exist`, `scope_is_narrowing_only`.
- **Realm ayrımı (FR-IAM-008):** `tenant_idp_grants_only_tenant_roles`, `platform_idp_separate_directory`,
  `assert_role_realm_must_equal_idp_realm`.
- **Tenant izolasyonu (FR-TEN-002):** `idp_bound_to_tenant`, `tenant_boundary_above_federation`.
- **Gizlilik (BRD §17.7):** `no_raw_pii_in_session`, `no_raw_token_persisted`, `subject_reference_opaque`.

## İnvariant'lar (S1–S12)

Çekirdek: **S2** imza/güven bütünlüğü (`untrusted_accepted=0`), **S3** rol-eşleme doğruluğu
(`unmapped_role_granted=0`), **S4** realm/IdP sınırı (`realm_escalation=0`; FR-IAM-008), **S7** tenant izolasyonu
(`cross_tenant=0`; FR-TEN-002), **S8** replay koruması (`replay_accepted=0`). **S5** audience/issuer bağı, **S6**
zaman geçerliliği. Her karar terminal (S1) + yapısal kanıt (S9; ham token/PII yok) + model bütünlük manifesti
(S10, `model_hash` sha256) + düşük-kardinalite metrik (S11) + sızıntısız artifact (S12).

## Sağlayıcı-nötr / credential-free (ADR-002)

İmza/anahtar/JWKS doğrulaması bu modülde **yapılmaz** — `assertion.signature_valid` soyut doğrulama
**sonucudur**. Canlı XML-DSig (SAML) / JWS (OIDC) + IdP metadata/JWKS + bölgesel endpoint **F2/PoC**
entegrasyonunda. Fixture'lar sentetik: yalnız IdP id + grup/rol adı + kapsam boyut ID + opak subject ref +
assertion-id. **Sır/credential/anahtar ve ham token/PII (NameID/e-posta/imza) repoya yazılmaz.**

## Çalıştırma

```bash
python3 sso_probe.py validate          # statik sso/rbac model + spec + kapsama → çıkış kodu
python3 sso_probe.py check samples      # 10 pass + 11 degrade/güvenlik-olayı senaryo
python3 sso_probe.py selftest           # gömülü davranış kontrolleri (S1–S12)
python3 sso_probe.py schema             # karar sözleşmesi
./run_live_test.sh                      # tümü + (varsa) SSO_IDP_URL canlı NOT
```

| Komut | Sonuç |
|-------|-------|
| `validate` | 95/95 🟢 |
| `selftest` | 56/56 🟢 |
| `check samples` | 21/21 🟢 (10 pass + 11 fail) |
| `behavior test` | 36/36 🟢 |

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| rol→permission-key bundle çözümü (immutable; realm) | **12.1.1** (tüketilir) |
| permission-key gramer + tam kataloğu | **12.1.2** |
| rol+scope atama **kapsam** çözümü (kaynak attribute karşı) | **12.1.3** (bu modül atamayı **üretir**) |
| MFA (çok faktörlü doğrulama) | 12.1.5 (FR-IAM-003) |
| SCIM kullanıcı/grup yaşam döngüsü (provisioning/deprovision senkron) | 12.1.6 (FR-IAM-007) |
| Backend panel guard (oturum→permission-key HTTP enforcement) | 12.2.x |
| Append-only WORM audit (login kararı) | 12.1.8 |
| Canlı XML-DSig/JWS imza + IdP metadata/JWKS | F2 / PoC |
