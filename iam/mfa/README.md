# WBS 12.1.5 — MFA (Çok Faktörlü Kimlik Doğrulama)

**Faz:** F1 · **Öncelik:** Must · **İz:** BRD §9.2 → **FR-IAM-003** → SR-IAM-003 → TC-IAM-003 (T) · FR-TEN-002 (tenant izolasyonu) · SAD §14.1 (IAM/MFA) · **ADR-017** (phishing-resistant MFA WebAuthn/FIDO2) · ADR-011/002

12. workstream'in (IAM & Erişim) **MFA doğrulama** modülü. Oturuma yansıyan kimliği ([`12.1.4`](../sso/README.md)
SSO authenticate'in **üstünde** step-up), rolünü, `actor_realm`'ini, break-glass bağlamını ve tenant politikasını
girdi alır; gereken **AAL**'i (kimlik doğrulama güvence seviyesi) **most-restrictive-wins** ile çözer ve sunulan
**faktörü** o seviyeye karşı **deterministik, fail-closed** doğrular. Terminal:
**`PASS` | `CHALLENGE` | `DENY` | `BLOCK`**.

**Çekirdek ilke (FR-IAM-003 / SR-IAM-003 / ADR-017):** *MFA açıkken **faktörsüz erişim REDDEDİLİR**; doğrulanmamış/
sahte faktör authenticate etmez; ayrıcalıklı (L0/break-glass) bağlamda yalnız **WebAuthn/FIDO2** (phishing-dirençli)
kabul edilir, TOTP/SMS/push **asla**; faktör AAL'i gereken seviyenin **altında** olamaz.* Gereken AAL = max(platform/
rol zemini, tenant politikası); tenant override **yalnız-sıkılaştırır**.

## Karar zinciri (fail-closed)

```
MfaVerificationRequest ─malformed─► role ─► policy ─► lockout ─► factor-presence ─► verification ─► phishing ─► aal ─► temporal ─► karar
   ├─ alan eksik/biçimsiz ─────────────────────────────────────────────► BLOCK (malformed_request)
   ├─ actor_role 12.1.1 modelinde yok ────────────────────────────────► BLOCK (unknown_role)
   ├─ gereken AAL = none (MFA gerekmiyor) ────────────────────────────► PASS  (mfa_not_required)
   ├─ failed_attempts ≥ max_failed ───────────────────────────────────► BLOCK (account_locked)         [S8]
   ├─ faktör yok ∧ kayıtlı faktör var ────────────────────────────────► CHALLENGE (step_up_required)
   ├─ faktör yok ∧ kayıtlı faktör yok ────────────────────────────────► DENY  (mfa_required)           [S2]
   ├─ factor.type ∉ katalog ──────────────────────────────────────────► BLOCK (unsupported_factor)
   ├─ factor.tenant_id ≠ request tenant_id ──────────────────────────► BLOCK (cross_tenant)           [S7]
   ├─ challenge_id ∈ seen ────────────────────────────────────────────► BLOCK (challenge_replay)       [S8]
   ├─ ¬factor.verified ───────────────────────────────────────────────► DENY  (factor_failed)          [S2]
   ├─ phishing_required ∧ ¬factor.phishing_resistant ────────────────► DENY  (phishing_vulnerable_factor) [S4]
   ├─ factor.aal < required_aal ──────────────────────────────────────► DENY  (insufficient_aal)       [S3]
   ├─ now > challenge_expires_at + skew ──────────────────────────────► DENY  (challenge_expired)      [S6]
   └─ aksi ───────────────────────────────────────────────────────────► PASS  (factor_verified)
```

- **Politika kapısı** (S5): gereken AAL = **most-restrictive-wins**(platform_l0 [AAL3+phishing, ADR-017],
  break_glass [AAL3+phishing, ADR-017], privileged_tenant_role [AAL2], tenant_policy); tenant override **yalnız-sıkılaştırır**.
- **Faktör bütünlüğü** (S2): faktörsüz (kayıtsız) erişim → `mfa_required` DENY; doğrulanmamış faktör → `factor_failed` DENY.
- **Phishing-direnci** (S4; ADR-017): L0/break-glass yalnız WebAuthn/FIDO2; zayıf faktör → `phishing_vulnerable_factor` DENY.
- **AAL kapısı** (S3): faktör AAL'i ≥ gereken AAL (katalog türetimli); aksi `insufficient_aal` DENY.
- **Tenant kapısı** (S7): faktör tenant'a bağlı (`factor.tenant_id` = istek tenant); aksi `cross_tenant` BLOCK.
- **Replay/kilit kapısı** (S8): `challenge_id` tek kullanımlık + N başarısızlıkta `account_locked`.

**`PASS` = MFA tatmin** (faktör gereken AAL'de doğrulandı) ya da MFA gerekmiyor. **`CHALLENGE`** = step-up gerekli
(faktör kayıtlı, doğrulama bekleniyor — meşru). **`DENY`** = MFA gerekli ama tatmin edilemedi. **`BLOCK`** = istek/
güvenlik reddi. Karar **her zaman backend'de**; faktör doğrulanmadan ayrıcalıklı oturum/eylem yok (12.2.x guard'a iletilir).

**Örnek (ADR-017):** `platform_owner` (L0) → AAL3 + phishing zorunlu; `webauthn` → **PASS**; `totp` →
**DENY `phishing_vulnerable_factor`**. `tenant_admin` (ayrıcalıklı tenant rolü) → AAL2; `totp` yeter → **PASS**.

## Model (`config/mfa-policy.json` — frozen)

- **AAL seviyeleri:** `none < aal1 < aal2 < aal3` (ordinal; NIST 800-63B ruhu).
- **Faktör kataloğu:** her tür → `{max_aal, phishing_resistant}`. `webauthn`/`fido2` (AAL3, phishing-**dirençli**);
  `totp`/`push`/`sms_otp`/`email_otp`/`recovery_code` (AAL2, phishing'e **açık**); `password` (AAL1). AAL/phishing-
  direnci **katalogdan türetilir** (istek alanı değil — credential-free).
- **Rol/bağlam gereksinimi:** platform L0 + break-glass → AAL3 + phishing (ADR-017); ayrıcalıklı tenant rolleri
  (`tenant_owner`/`tenant_admin`/`security_compliance_officer`/`api_developer`) → AAL2 (SR-IAM-003).
- **Tenant politikası:** `required_aal` + `phishing_resistant_required` (T-03'ten konfigüre); **override_only_tightens**.
- **Kilit:** `max_failed_attempts` (5) → `account_locked`. **Challenge:** `single_use` + `honor_expires_at` (skew toleransı).
- **Gizlilik (BRD §17.7):** `no_raw_otp_persisted`, `no_factor_secret_persisted`, `subject_reference_opaque`.

## İnvariant'lar (S1–S12)

Çekirdek: **S2** faktör doğrulama bütünlüğü (`factorless_accepted=0` ∧ `failed_factor_accepted=0`; FR-IAM-003/
SR-IAM-003), **S4** ayrıcalıkta phishing-direnci (`weak_factor_accepted=0`; ADR-017), **S3** AAL yeterliliği
(`insufficient_aal_accepted=0`), **S5** politika most-restrictive-wins (`policy_downgraded=0`), **S7** tenant
izolasyonu (`cross_tenant=0`; FR-TEN-002), **S8** replay+kilit (`replay_accepted=0` ∧ `lockout_bypassed=0`). **S6**
challenge zaman geçerliliği. Her karar terminal (S1) + yapısal kanıt (S9; ham OTP/sır/PII yok) + model bütünlük
manifesti (S10, `model_hash` sha256) + düşük-kardinalite metrik (S11) + sızıntısız artifact (S12).

## Sağlayıcı-nötr / credential-free (ADR-002)

Kriptografik faktör doğrulaması bu modülde **yapılmaz** — `factor.verified` soyut doğrulama **sonucudur**; faktör
AAL/phishing-direnci `config/mfa-policy.json` katalogundan **türetilir**. Canlı WebAuthn/FIDO2 attestation/assertion
+ TOTP HMAC + OTP teslimi + authenticator recovery akışı **F2/PoC** entegrasyonunda. Fixture'lar sentetik: yalnız
faktör türü + rol/realm + opak challenge/subject ref + enum + sanal-saat tamsayı. **Sır/credential/faktör sırrı
(TOTP seed, WebAuthn private key) ve ham OTP/PII (NameID/e-posta) repoya yazılmaz.**

## Çalıştırma

```bash
python3 mfa_probe.py validate          # statik mfa/rbac model + spec + kapsama → çıkış kodu
python3 mfa_probe.py check samples      # 10 pass + 10 degrade/güvenlik-olayı senaryo
python3 mfa_probe.py selftest           # gömülü davranış kontrolleri (S1–S12)
python3 mfa_probe.py schema             # karar sözleşmesi
./run_live_test.sh                      # tümü + (varsa) MFA_IDP_URL canlı NOT
```

| Komut | Sonuç |
|-------|-------|
| `validate` | 104/104 🟢 |
| `selftest` | 52/52 🟢 |
| `check samples` | 20/20 🟢 (10 pass + 10 fail) |
| `behavior test` | 40/40 🟢 |

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| rol→permission-key bundle çözümü (immutable; realm/layer) | **12.1.1** (tüketilir — ayrıcalık çözümü) |
| permission-key gramer + tam kataloğu | **12.1.2** |
| rol+scope atama kapsam çözümü | **12.1.3** |
| SSO authenticate (SAML2/OIDC) — MFA step-up bunun üstünde | **12.1.4** (tüketilir) |
| Backend panel guard (oturum AAL → permission-key HTTP enforcement) | 12.2.x |
| Break-glass akışı (Tier B onaylayıcı AAL3 phishing-dirençli — ADR-017) | 12.3.x |
| Append-only WORM audit (MFA kararı) | 12.1.8 |
| Çağrı-tarafı arayan kimlik doğrulama (OTP/KBA/step-up) | 8.2/8.3/8.4 (ayrı, müşteri tarafı) |
| Canlı WebAuthn/FIDO2 + TOTP/OTP kriptografik doğrulama + recovery | F2 / PoC |
