# WBS 12.1.7 — Maker-checker onay akışı

**Faz:** F2 · **Öncelik:** Should · **İz:** BRD §9.2 → **FR-IAM-005** → SR-IAM-005 → TC-IAM-005 (T) · FR-TEN-002 (tenant izolasyonu) · SAD §14.1 (Maker-checker: kritik değişikliklerde onay akışı) / §14.4.2 (maker-checker kritik mutasyonlarda pending→approved ile zorlanır) · ADR-011/012/002

12. workstream'in (IAM & Erişim) **kritik mutasyon onay** modülü. Kritik bir değişiklik talebini **deterministik,
fail-closed** bir onay durum makinesinden geçirir; **görevler ayrımını (SoD)** — *talep eden ≠ onaylayan* — zorlar,
**quorum** dolmadan commit'i engeller (*onaysız değişiklik canlıya çıkmaz*), **süreli** (time-boxed) onay penceresi ve
**zorunlu gerekçe** uygular. İzin/kapsam kararını [`12.1.2`](../permission-catalog/README.md) (permission-key) +
[`12.1.3`](../scoped-assignment/README.md) (scoped assignment) **soyut sonuç** olarak (`maker.authorized` /
`approval.authorized` / `approval.scope_ok`) **TÜKETİR**, rol/realm tutarlılığını [`12.1.1`](../rbac-model/README.md)
modelinden alır. Terminal: **`APPLIED` | `PENDING` | `REJECTED` | `DENIED`**.

**Çekirdek ilke (FR-IAM-005 / SR-IAM-005 / SAD §14.4.2):** *Kritik mutasyon ──maker talebi (pending)──► başka bir
yetkili checker onayı (talep eden ≠ onaylayan) ──quorum dolunca──► APPLIED (commit).* Maker **kendi talebini
onaylayamaz** (kendi onayı quorum'a **sayılmaz**); commit **yalnız** APPLIED durumunda (`PENDING`/`REJECTED`/`DENIED` →
commit **YOK**). Aynı maker-checker çekirdeği **break-glass Tier B**'nin (FR-IAM-009; talep eden ≠ onaylayan) tabanıdır.

## Karar zinciri (fail-closed)

```
ApprovalRequest ─malformed─► action ─► maker-auth ─► reason ─► tenant ─► timebox ─► approvals ─► durum
   ├─ alan eksik/biçimsiz ──────────────────────────────────────────────► DENIED (malformed_request)
   ├─ action ∉ kritik-aksiyon kataloğu ────────────────────────────────► DENIED (unsupported_action)
   ├─ ¬maker.authorized (submit yetkisi yok) ──────────────────────────► DENIED (maker_unauthorized)     [S2]
   ├─ reason_code yok/boş (zorunlu gerekçe) ───────────────────────────► DENIED (reason_code_missing)
   ├─ maker.tenant_id ≠ request tenant_id ─────────────────────────────► DENIED (cross_tenant)           [S7]
   ├─ now > expires_at (onay penceresi kapandı) ───────────────────────► DENIED (expired)                [S6]
   │
   └─ approvals değerlendir (SoD + quorum):
        ├─ ∃ yetkili in-tenant checker decision=reject ─────────────────► REJECTED (commit YOK)
        ├─ distinct yetkili onay (≠ maker, taze, in-tenant) ≥ quorum ───► APPLIED (committed=true)  [S5 ÇEKİRDEK]
        └─ aksi (yetersiz onay) ────────────────────────────────────────► PENDING (awaiting checker; commit YOK)
```

- **SoD kuralı** (S3 — **ÇEKİRDEK**): `approver_ref == maker.actor_ref` olan onay quorum'a **SAYILMAZ** (sessizce
  dışlanır → yeterli değilse `PENDING`). Maker'ın kendi onayını saymak `sod_violation` (talep eden = onaylayan).
- **Commit kuralı** (S5 — **ÇEKİRDEK**): commit **yalnız** APPLIED'da; APPLIED ⟺ distinct yetkili onay ≥ `quorum_required`
  (aksiyon kataloğu). `PENDING`/`REJECTED`/`DENIED` → `committed=false`. Quorum dolmadan commit `applied_without_quorum`.
- **Maker yetkisi** (S2): yalnız `authorized` (submit izni — 12.1.2 soyut sonuç) maker talep açar; aksi `DENIED`.
- **Onaylayan kuralı** (S4): onay quorum'a **sayılır** ⟺ `decision=approve ∧ authorized ∧ scope_ok` (12.1.3) `∧ aynı
  tenant/realm ∧ ≠ maker ∧ taze (at ≤ expires_at)`. Yetkisiz/kapsam-dışı onay **sayılmaz** (`unauthorized_approval`).
- **Time-box** (S6): `now > expires_at` → talep `DENIED expired`; bayat onay (`at > expires_at`) sayılmaz. Break-glass
  Tier B time-box'ının (FR-IAM-009; 60dk/4sa) onay-akışı tarafı.
- **Tenant izolasyonu** (S7): `maker.tenant_id = request tenant_id`; aksi `DENIED cross_tenant` (FR-TEN-002).
- **Quorum bütünlüğü** (S8): quorum **FARKLI** (distinct, `actor_ref`'e göre tekil) onaylayanla dolar; aynı kişi tek
  sayılır (`quorum_tampered` = duplicate'i saymak).

**APPLIED** ⇒ `committed=true` (kritik mutasyon canlıya çıkar) + onay kanıtı (maker_ref ≠ approver_ref'ler, reason_code)
→ **WORM audit** ([`12.1.8`](#)). Karar **her zaman backend'de**.

**Örnek (SR-IAM-005):** `conversation_designer` (mk-1) `agent.publish` talep eder (pending); farklı yetkili checker
(ck-1) onaylar → **APPLIED**; mk-1 kendi talebini onaylasa → **PENDING** (sayılmaz); onaysız → **PENDING** (canlıya
çıkmaz); checker reddederse → **REJECTED**; `compliance_profile.update` (quorum=2) iki distinct onay ister.

## Model (`config/maker-checker-model.json` — frozen)

- **SoD (ÇEKİRDEK):** `require_distinct_maker_checker`, `self_approval_counts_to_quorum=false`, `maker_excluded_from_approvers` (S3).
- **Commit (ÇEKİRDEK):** `commit_only_on_applied`, `apply_requires_quorum`, `default_quorum=1`, `no_commit_on_{pending,rejected,denied}` (S5).
- **Time-box:** `request_has_expiry`, `expired_request_denied`, `stale_approval_not_counted` (S6).
- **Gerekçe:** `reason_code_required`.
- **Tenant (FR-TEN-002):** `maker_bound_to_tenant`, `approver_bound_to_tenant`, `tenant_boundary_above_approval` (S7).
- **Quorum:** `require_distinct_approvers`, `dedupe_by_actor_ref` (S8).
- **Kritik-aksiyon kataloğu:** `agent.publish` · `role.assign` · `tenant.provision` · `breakglass.tier_b` ·
  `data.bulk_export` (quorum 1); `compliance_profile.update` · `retention.policy.update` · `tenant.delete` (quorum 2).
  Katalog dışı aksiyon → `unsupported_action` (fail-closed). Temsilî — canlı katalog 12.2.x panel guard ile genişler.
- **İdempotency:** `idempotent_decision`, `no_resurrect_resolved_request`.
- **Gizlilik (BRD §17.7):** `no_raw_pii_in_record`, `no_raw_token_persisted`, `actor_reference_opaque`.

## İnvariant'lar (S1–S12)

Çekirdek: **S3** görevler ayrımı (`sod_violation=0`; talep eden ≠ onaylayan; FR-IAM-005/SR-IAM-005 ÇEKİRDEK), **S5**
onaysız canlıya çıkmaz (`applied_without_quorum=0`; commit yalnız APPLIED; SR-IAM-005 ÇEKİRDEK), **S2** maker yetkisi
(`unauthorized_maker_accepted=0`), **S4** onaylayan yetkisi/kapsamı (`unauthorized_approval=0`; 12.1.3), **S6** time-box
(`stale_approval_applied=0`), **S7** tenant izolasyonu (`cross_tenant=0`; FR-TEN-002), **S8** quorum bütünlüğü
(`quorum_tampered=0`). Her karar terminal (S1) + yapısal kanıt (S9; ham token/PII yok) + model bütünlük manifesti (S10,
`model_hash` sha256) + düşük-kardinalite metrik (S11) + sızıntısız artifact (S12).

## Sağlayıcı-nötr / credential-free (ADR-002)

İzin/kapsam doğrulaması bu modülde **yapılmaz** — `maker.authorized` / `approval.authorized` / `approval.scope_ok`
soyut doğrulama **sonuçlarıdır** (12.1.2/12.1.3'ten). Canlı onay UI + bildirim + backend panel guard (12.2.x) + WORM
audit (12.1.8) **F2** entegrasyonunda. Fixture'lar sentetik: yalnız opak `actor_ref` + aksiyon/rol adı + kapsam boyut
ID + `reason_code` (opak kod) + sanal-saat tick. **Sır/credential/anahtar ve ham token/PII (kullanıcı adı/e-posta/
token) repoya yazılmaz.**

## Çalıştırma

```bash
python3 maker_checker_probe.py validate          # statik maker-checker/rbac model + spec + kapsama → çıkış kodu
python3 maker_checker_probe.py check samples      # 14 pass + 11 degrade/güvenlik-olayı senaryo
python3 maker_checker_probe.py selftest           # gömülü davranış kontrolleri (S1–S12)
python3 maker_checker_probe.py schema             # karar sözleşmesi
./run_live_test.sh                                # tümü + (varsa) MAKERCHECKER_ENDPOINT_URL canlı NOT
```

| Komut | Sonuç |
|-------|-------|
| `validate` | 108/108 🟢 |
| `selftest` | 52/52 🟢 |
| `check samples` | 25/25 🟢 (14 pass + 11 fail) |
| `behavior test` | 39/39 🟢 |

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| rol→permission-key bundle çözümü (immutable; realm) | **12.1.1** (tüketilir) |
| permission-key gramer + katalog + aksiyon→izin çözümü (`maker.authorized`) | **12.1.2** (soyut sonuç tüketilir) |
| rol+scope **kapsam** çözümü (kaynak attribute karşı; `approval.scope_ok`) | **12.1.3** (soyut sonuç tüketilir) |
| SSO login assertion doğrulama | 12.1.4 |
| MFA (çok faktörlü doğrulama) | 12.1.5 (FR-IAM-003) |
| SCIM provisioning + grup→rol eşleme | 12.1.6 (FR-IAM-007) |
| Append-only (WORM) audit log (onay kararı + reason_code kaydı) | **12.1.8** |
| Backend panel guard (kritik mutasyon → onay durumu enforcement; oturum→permission-key) | 12.2.x |
| Break-glass Tier B time-box/bildirim (AYNI maker-checker çekirdeğini tüketir) | FR-IAM-009 (12.x) |
| Canlı onay UI + bildirim + entegrasyon | F2 |
