# WBS 12.3.4 — Tier B break-glass: regüle tenant `require_tenant_approval` toggle + DPA bağı

**Faz:** F2 · **Öncelik:** Must · **İz:** **FR-IAM-010** (regüle tenant onay toggle + DPA) · BRD §17/§17.7 (*"Regüle tenant'lar (finans/sağlık): Tier B'de tenant onayı zorunlu toggle'ı; regulated compliance profile'da varsayılan açık. B2B2B'de veri controller'ı tenant, RMC processor'dür; bu kontrol DPA'ya bağlanır"*) · SAD §14.4.2 (*"Regüle tenant toggle: require_tenant_approval=true ise Tier B, tenant onayı olmadan açılmaz; regulated compliance profile'da varsayılan açık; DPA'ya bağlı (controller=tenant, processor=RMC)"*) · **FR-IAM-009** (üç katmanlı break-glass) · **FR-IAM-006/FR-REC-009** (break-glass erişimi audit) · FR-REC-004 (audit PII'siz) · FR-TEN-002 (onay tenant-binding) · SR-IAM-010 → TC-IAM-010 · ADR-013 (üç katmanlı break-glass + regüle onay toggle) · ADR-016 (audit hash-zincir) · DPIA §8 (most-restrictive-wins; tenant override yalnız-sıkılaştırır)

12. workstream'in (IAM & Erişim) **üç katmanlı break-glass'ın İÇERİK/PII katmanının (Tier B)** **regüle tenant onay** modülü. BRD §17 / SAD §14.4.2'nin Tier B kararının **regüle tenant koşulunu** sahiplenir: (1) **regüle compliance profile'da `require_tenant_approval` varsayılan AÇIK** (most-restrictive-wins), (2) toggle açıkken Tier B **tenant onayı olmadan AÇILMAZ** (controller=tenant) ve (3) bu kontrol **imzalı DPA'ya bağlıdır** (controller=tenant, processor=RMC). **Altın kural** (BRD §17): L0 (platform) tenant'ın iş içeriğini varsayılan göremez; Tier B yalnız bu **dar, süreli, onaylı, tam-audit'li** kapıyı açar — bu modül **regüle** tenant'ta o kapıyı EK olarak **tenant'ın kendi onayına** ve **DPA'ya** bağlar.

Bu modül **12.3.2'nin `access_decision` (`GRANT_TIER_B`/`PENDING`/`DENY`) çıktısını tüketir**; bir `BreakGlassTierBApprovalEvent` için **deterministik, fail-closed** bir karar verir. Terminal: **`ALLOW` | `HOLD` | `BLOCK`**.

## Karar akışı (gate)

```
BreakGlassTierBApprovalEvent ─malformed─► access_routing ─► regulated_toggle ─► dpa_binding ─► tenant_approval ─► audit/replay
      ├─ request_id / actor_role(L0) / target_tenant / tier≠B / access_decision tanınmaz ──► BLOCK (malformed)
      ├─ access_decision ∈ {PENDING, DENY} (12.3.2 grant etmedi) ─────────────────────────► HOLD (access_not_granted) [C1 doğru]
      ├─ require_tenant_approval=false (regüle değil + override yok) ─────────────────────► ALLOW (not_regulated) [C1 doğru]
      ├─ regüle + dpa_signed=false ──────────────────────────────────────────────────────► BLOCK (dpa_unbound) [C5 ÇEKİRDEK]
      ├─ prior_state çözülmüş (CONSUMED/REVOKED/EXPIRED) ────────────────────────────────► HOLD (already_resolved) [C8 doğru]
      ├─ geçerli tenant onayı yok ───────────────────────────────────────────────────────► HOLD (awaiting_tenant_approval) [C3 ÇEKİRDEK]
      └─ geçerli tenant onayı (tenant realm + target_tenant + break_glass_id) ───────────► ALLOW (tenant_approved)
```

## Regüle toggle çözümlemesi (ÇEKİRDEK — FR-IAM-010 "regulated profile'da varsayılan açık"; DPIA §8)

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `require_tenant_approval_default_when_regulated` | **true** | regulated profile (finance/health/regulated) → toggle **varsayılan AÇIK**; regüle tenant'ta kapalı → `regulated_toggle_off` |
| `default_when_unregulated` | **false** | regüle olmayan tenant'ta varsayılan kapalı; tenant **opt-in** ile sıkılaştırabilir |
| `most_restrictive_wins` / `override_tightens_only` | **true** | tenant override yalnız **sıkılaştırabilir** (kapalı→açık); regüle varsayılan-açık'ı kapatma (gevşetme) → `override_loosened` |

## Tenant onay yetkisi (ÇEKİRDEK — FR-IAM-010 "tenant onayı zorunlu"; controller=tenant)

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `require_tenant_approval_gate` | **true** | `require_tenant_approval=true` iken geçerli tenant onayı olmadan erişim **AÇILMAZ** (`HOLD`); açma → `tenant_approval_bypassed` |
| `approver_realm` / `approver_roles` | **`tenant`** / **`security_compliance_officer` + `tenant_owner`** | onay **tenant** realm rolünden (controller=tenant; 12.1.1 RESİPROKAL) |
| `no_platform_self_approval` | **true** | platform (L0) aktörü kendi erişimini onaylayamaz (cross-realm self-approval → `approval_authority_violation`) |
| `bind_break_glass_id` / `bind_target_tenant` | **true** | onay yalnız ilgili `break_glass_id` + `target_tenant` için geçerli; başka grant/tenant → `approval_misbinding` |

## DPA bağı (ÇEKİRDEK — FR-IAM-010 "DPA'ya bağlanmalıdır")

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `require_dpa_when_regulated` | **true** | regüle kontrol **imzalı DPA'ya** bağlı; DPA imzasız → `BLOCK (dpa_unbound)` (hukuki dayanak yok; fail-closed) |
| `controller_role` / `processor_role` | **`tenant`** / **`rmc`** | B2B2B veri koruma rol modeli — tenant controller, RMC processor; tenant onayı controller'ın talimatı |
| `bind_control_to_dpa` | **true** | regüle onay kontrolü DPA'ya bağlanır (contract-dpa-checklist **D-09**) |

## İnvariant'lar (C1–C12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| C1 | | Determinizm/terminal; varsayılan **BLOCK** (fail-closed); access routing (PENDING/DENY → HOLD access_not_granted); kanıt; `model_hash` sha256; `tick=dakika`; `stuck_state`/`missing_evidence=0` |
| **C2** | **FR-IAM-010** | **Regüle varsayılan açık:** regulated profile → `require_tenant_approval` default true; regüle tenant'ta toggle kapatma → `regulated_toggle_off=0` (most-restrictive-wins) |
| **C3** | **FR-IAM-010** | **Onaysız açılmaz:** `require_tenant_approval=true` iken geçerli tenant onayı olmadan erişim açılmaz → `HOLD`; açma → `tenant_approval_bypassed=0` |
| **C4** | **FR-IAM-010** | **Onay yetkisi:** onay tenant realm rolünden (`security_compliance_officer`/`tenant_owner`; controller=tenant); platform self-approval/cross-realm → `approval_authority_violation=0` |
| **C5** | **FR-IAM-010** | **DPA bağı:** regüle kontrol imzalı DPA'ya bağlı (controller=tenant/processor=RMC); DPA'sız → `BLOCK`; `dpa_unbound=0` |
| C6 | DPIA §8 | **Override yalnız-sıkılaştırır:** tenant override regüle default-on'u gevşetemez; `override_loosened=0` |
| C7 | FR-TEN-002 | **Onay binding:** onay yalnız `target_tenant` + `break_glass_id`'ye bağlı; cross-tenant/cross-grant → `approval_misbinding=0` |
| C8 | FR-IAM-010 | **Replay-safe/idempotent:** çözülmüş (CONSUMED/REVOKED/EXPIRED) onay yeniden kullanılamaz; `approval_replay=0` |
| C9 | FR-REC-009/ADR-016 | **Audit (WORM, PII/token-free, immutable):** her karar değişmez (WORM) audit (`break_glass_id` ile); `unaudited_decision`/`audit_pii`/`audit_mutable=0` (12.1.8 RESİPROKAL) |
| C10 | ADR-013 | Model bütünlük manifesti (`model_hash` sha256); regüle onay/DPA yüzeyi tahrifatı yakalanır; `model_tampered=0` |
| C11 | 0.4.7 | Gözlemlenebilirlik kardinalite: actor_role/decision/result/approver_role düşük-kard; break_glass_id/target_tenant_id trace-only; PII label'da yok |
| C12 | BRD §17.7 | Sır/içerik yok: yalnız rol + realm + sınıf + kaynak adı + tier/decision enum + bool + profil enum + tick + slug korelasyon + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.3.x deseniyle birebir: motor **doğru** regüle onay davranışını hesaplar, `inject` doğru davranışı **bozar** ve eşleşen ihlal sayacını artırır → kapı eler. 12 enjeksiyon: `disable_regulated_toggle`, `loosen_override`, `bypass_tenant_approval`, `platform_self_approve`, `cross_realm_approval`, `cross_tenant_approval`, `unbind_dpa`, `replay_approval`, `skip_audit`, `leak_pii`, `mutate_audit`, `model_tamper` (+ `secret_leak` tarayıcı).

**Anahtar çekirdek ispatı:** `disable_regulated_toggle` → regüle tenant'ta gate kapatma → `regulated_toggle_off>0`. `bypass_tenant_approval` → onaysız ALLOW → `tenant_approval_bypassed>0` ("tenant onayı olmadan açılmaz" çiğnendi). `platform_self_approve`/`cross_realm_approval` → yetkisiz onay → `approval_authority_violation>0`. `unbind_dpa` → DPA'sız ALLOW → `dpa_unbound>0`. `loosen_override` → override gevşetme → `override_loosened>0`.

## Dosyalar

- `config/tier-b-approval-model.json` — **frozen** model (`regulated_policy` [default_when_regulated + most_restrictive_wins + override_tightens_only] + `approval_policy` [require_gate + approver_realm=tenant + approver_roles=SCO+owner + no_platform_self_approval + binding; 12.1.1 RESİPROKAL] + `dpa_policy` [require_dpa_when_regulated + controller=tenant/processor=rmc + bind_to_dpa] + `concurrency_policy` [replay-safe] + `audit` [WORM; PII/token-free; 12.1.8 RESİPROKAL] + `actor_roles` [L0; 12.1.1 RESİPROKAL]).
- `tier-b-approval-spec.json` — makine-okunur spec (10 kural + karar + C1–C12 + 14 sıfır-eşik HARD kapı + gözlemlenebilirlik).
- `tier_b_approval_probe.py` — Tier B regüle onay + DPA motoru + `validate`/`check`/`selftest`/`schema`. 12.3.2 access_decision + 12.1.1 onaylayan/aktör rolleri + 12.1.8 WORM audit **resiprokal** bağlantılarını doğrular.
- `samples/` (23: 11 pass + 12 degrade) + `tests/` (42 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tier_b_approval_probe.py validate          # statik model + spec + 12.3.2/12.1.1/12.1.8 resiprokal
python3 tier_b_approval_probe.py selftest          # C1–C12 motoru
python3 tier_b_approval_probe.py check samples     # 11 pass + 12 degrade
python3 tests/tier_b_approval_behavior_test.py     # bağımsız C1–C12
./run_live_test.sh                                 # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| **Bu modül:** regüle tenant `require_tenant_approval` toggle (regüle varsayılan-açık + most-restrictive-wins + override-tightens-only) + tenant onay yetkisi (controller=tenant; platform self-approval yok) + DPA bağı (controller=tenant/processor=RMC) + WORM audit | **12.3.4** |
| **Tier B erişim-verme:** maker-checker (SoD) + time-boxed token (60/240/auto-expiry/no-standing) + token-binding + replay-safety | 12.3.2 (TÜKETİLİR) |
| **Tier B:** zorunlu gerekçe kodu semantiği + tenant `security_compliance_officer`/`tenant_owner` anlık bildirimi | 12.3.3 |
| Tier sınıflandırma (A/B/forbidden) + `ESCALATE_TIER_B` | 12.3.1 |
| Break-glass tam-audit router (ayrı, kısıtlı) | 12.3.5 (TÜKETİR) |
| `cp.*` compliance profile parametre çözümleme motoru (most-restrictive-wins) | DPIA.md + F2/F3 |
| rol→permission-key bundle + onaylayan/aktör rolleri | 12.1.1 / 12.1.2 / 12.1.3 |
| append-only/WORM audit + hash-zincir bütünlüğü | 12.1.8 (TÜKETİLİR) |

## Notlar

- **Vendor-neutral** (ADR-002/013); **stdlib-only**, **credential-free**, **deterministik** (Date.now/random yok; `tick=dakika` sanal-saat).
- **Sır/credential (break-glass/onay token DEĞERİ / DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz** — yalnız actor rol enum + onaylayan rol enum + realm enum (platform/tenant) + veri-sınıfı enum + resource_type adı + tier/decision enum + regulated/dpa/onay bool + profil enum (finance/health) + tick tamsayı + slug korelasyon/aktör kimliği (`req-`/`bg-`/`t-`) + sha256. Bu modül Tier B **regüle onay + DPA kararını** + **PII/token-free WORM audit kaydını** verir; ham satır içeriği (PII), ham token **akmaz**.
- Gerçek Tier B regüle enforcement (FastAPI break-glass router + **regüle toggle enforcement** + **tenant onay akışı** [tenant `security_compliance_officer`/`tenant_owner` onayı; controller=tenant] + **DPA bağı** [imzalı DPA kontrolü] + **WORM audit yazımı** [append-only, hash-zincir, `break_glass_id`]) **F1/F2 kod aşamasında**; bu modül onlara kararı + onay/DPA kanıtını + PII/token-free audit kaydını + model bütünlük manifestini iletir. Compliance profile parametre çözümleme (`cp.*`, most-restrictive-wins) **DPIA.md + F2/F3** motorunda; bu modül yalnız regüle **bayrağını** + toggle **kararını** tüketir.
