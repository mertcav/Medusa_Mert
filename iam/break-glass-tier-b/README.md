# WBS 12.3.2 — Tier B break-glass: maker-checker + time-boxed token (60dk default, max 4sa, auto-expiry)

**Faz:** F2 · **Öncelik:** Must · **İz:** **FR-IAM-009** (üç katmanlı break-glass) · BRD §17.7/§17 (*"Tier B — transkript/kayıt/PII: Maker-checker zorunlu [talep eden ≠ onaylayan] + time-boxed [varsayılan 60 dk, max 4 saat, otomatik sonlanma, **standing access yok**] + ..."*) · SAD §14.4.2 (aynı; *"süreli token ... Erişim ayrı, kısıtlı, **tam-audit**'li bir break-glass router'ı üzerinden"*) · **FR-IAM-005** (maker-checker) · **FR-IAM-006/FR-REC-009** (break-glass erişimi audit) · FR-REC-004 (audit PII'siz) · FR-TEN-002 (token-binding) · SR-IAM-009 → TC-IAM-009 · ADR-013 (üç katmanlı break-glass) · ADR-016 (audit hash-zincir)

12. workstream'in (IAM & Erişim) **üç katmanlı break-glass'ın İÇERİK/PII katmanı (Tier B)** erişim-verme modülü. BRD §17.7 / SAD §14.4.2'nin temel kararını sahiplenir: *"Tier B (transkript/kayıt/PII): maker-checker (talep eden ≠ onaylayan) → süreli token (varsayılan 60 dk, max 4 saat, otomatik expiry, standing access yok) → ... tam-audit'li bir break-glass router'ı üzerinden."* ve **altın kural** (BRD §17): L0 (platform) tenant'ın iş içeriğini varsayılan göremez — Tier B yalnız bu **dar, süreli, onaylı, tam-audit'li** kapıyı açar.

Bu modül **12.3.1'in `ESCALATE_TIER_B` çıktısını tüketir**; bir `BreakGlassTierBRequest` için **deterministik, fail-closed** bir karar verir. Terminal: **`GRANT_TIER_B` | `PENDING` | `DENY`**.

## Karar akışı (gate)

```
BreakGlassTierBRequest ─malformed─► scope ─► maker-checker ─► timebox ─► standing/expiry ─► binding ─► audit/replay
      ├─ request_id / actor_role(L0) / target_tenant / data_class eksik|geçersiz ──► DENY (malformed)
      ├─ data_class ≠ tenant_content (break-glass gerekmez / L0 yolu yok) ─────────► DENY (not_tier_b) [R2]
      ├─ maker yetkisiz ──────────────────────────────────────────────────────────► DENY (maker_unauthorized)
      ├─ FARKLI yetkili onay (self hariç) < quorum ───────────────────────────────► PENDING (token YOK) [R4]
      ├─ maker kendi onayını sayar (self-approval) ───────────────────────────────► sod_violation [R3 ÇEKİRDEK]
      ├─ quorum'suz GRANT ───────────────────────────────────────────────────────► granted_without_approval [R4 ÇEKİRDEK]
      ├─ ttl > 240 (4sa) talebi ─────────────────────────────────────────────────► DENY (ttl_over_max) [R5]
      ├─ ttl>max ile GRANT | expires_at'siz token ───────────────────────────────► ttl_exceeds_max / unbounded_token [R5 ÇEKİRDEK]
      ├─ access_at > expires_at (pencere dışı) ──────────────────────────────────► DENY (token_expired; auto-expiry) [R6]
      ├─ pencere dışı erişim VERİLDİ | kalıcı/standing token ─────────────────────► expired_token_access / standing_access [R6 ÇEKİRDEK]
      ├─ access.tenant ≠ target (cross-tenant) ile GRANT ────────────────────────► token_binding_violation [R7]
      ├─ çözülmüş grant (expired/revoked/consumed) yeniden GRANT ─────────────────► replay_reuse [R9]
      └─ GRANT audit'siz | audit ham PII/token | emitilen audit tahrif ───────────► unaudited_grant / audit_pii / audit_mutable [R8]
```

## Time-box (ÇEKİRDEK — FR-IAM-009 / BRD §17.7)

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `default_ttl_minutes` | **60** | ttl belirtilmezse token 60dk sürer |
| `max_ttl_minutes` | **240** (4sa) | ttl>240 talebi **reddedilir** (`DENY ttl_over_max`); 4sa'tan uzun token verilmez |
| `require_expiry` | **true** | her token `expires_at=granted_at+ttl` taşır (unbounded token yok) |
| `auto_expiry` | **true** | `expires_at` sonrası token geçersiz — pencere dışı erişim reddedilir |
| `no_standing_access` | **true** | token tek, süreli grant; kalıcı/yenilenerek-standing yetki yok |

`tick = dakika` (sanal-saat; Date.now yok). `expires_at = now + ttl`. `access_at > expires_at` → `DENY (token_expired)`.

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **DENY** (fail-closed); kanıt; `model_hash` sha256; `tick=dakika` sanal-saat; `stuck_state`/`missing_evidence=0` |
| R2 | 12.3.1 | **Tier B scope:** yalnız `tenant_content` (transcript/recording/contact) Tier B'ye girer; non-content → `DENY (not_tier_b)` |
| **R3** | **FR-IAM-009** | **SoD (talep eden ≠ onaylayan):** maker kendi talebini onaylayamaz; self-approval quorum'a sayılmaz; `sod_violation=0` (12.1.7 RESİPROKAL) |
| **R4** | **FR-IAM-009** | **No grant without approval:** `GRANT_TIER_B` yalnız FARKLI yetkili onay (quorum) toplandığında; yetersiz → `PENDING`; `granted_without_approval=0` (fail-closed) |
| **R5** | **BRD §17.7** | **Time-box 60/240:** token `expires_at` taşır (`unbounded_token=0`); ttl default 60dk, max 240dk (4sa); ttl>max GRANT = `ttl_exceeds_max=0` |
| **R6** | **BRD §17.7** | **No standing + auto-expiry:** `expires_at` sonrası erişim reddedilir (`expired_token_access=0`); kalıcı/standing token `standing_access=0` |
| R7 | FR-TEN-002 | **Token binding:** token `target_tenant` + tier B + scope'a bağlı; cross-tenant/tier-dışı = `token_binding_violation=0` |
| R8 | FR-REC-009/ADR-016 | **Audit (WORM, PII/token-free, immutable):** her karar değişmez (WORM) audit (`break_glass_id` ile); `unaudited_grant`/`audit_pii`/`audit_mutable=0` (12.1.8 RESİPROKAL) |
| R9 | FR-IAM-009 | **Replay-safe:** çözülmüş grant (expired/revoked/consumed) yeniden kullanılamaz; `replay_reuse=0` (12.1.7 RESİPROKAL) |
| R10 | ADR-013 | Model bütünlük manifesti (`model_hash` sha256); time-box/SoD yüzeyi tahrifatı yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: actor_role/decision/result düşük-kard; break_glass_id/target_tenant_id/token_ref trace-only; PII/token label'da yok |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız rol + action + sınıf + kaynak adı + tier/decision enum + reason_code + ttl/tick + slug korelasyon + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.3.1 deseniyle birebir: motor **doğru** Tier B davranışını hesaplar, `inject` doğru davranışı **bozar** ve eşleşen ihlal sayacını artırır → kapı eler. 12 enjeksiyon: `self_approval`, `grant_without_quorum`, `unbounded_token`, `ttl_exceeds_max`, `standing_access`, `use_after_expiry`, `cross_tenant_token`, `replay_grant`, `skip_audit`, `leak_pii_in_audit`, `mutate_audit`, `model_tamper` (+ `secret_leak` tarayıcı).

**Anahtar çekirdek ispatı:** `self_approval` → maker kendi onayını sayar → `sod_violation>0` (talep eden = onaylayan). `grant_without_quorum` → onaysız token → `granted_without_approval>0`. `ttl_exceeds_max` → 4sa'tan uzun token → `ttl_exceeds_max>0`. `use_after_expiry` → pencere dışı erişim → `expired_token_access>0` (auto-expiry ihlali). `standing_access` → kalıcı yetki → `standing_access>0`.

## Dosyalar

- `config/tier-b-model.json` — **frozen** model (`separation_of_duties` [talep eden ≠ onaylayan; 12.1.7 RESİPROKAL] + `quorum_policy` [distinct; breakglass.tier_b 12.1.7 RESİPROKAL] + `timebox_policy` [60/240/require_expiry/auto_expiry/no_standing] + `token_binding` + `concurrency_policy` [replay-safe] + `audit` [WORM; PII/token-free; `break_glass_id`; 12.1.8 RESİPROKAL] + `actor_roles` [L0; 12.1.1 RESİPROKAL] + `table_class_of` [37 varlık; 12.3.1 RESİPROKAL]).
- `tier-b-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + 15 sıfır-eşik HARD kapı + gözlemlenebilirlik).
- `tier_b_probe.py` — Tier B erişim-verme motoru + `validate`/`check`/`selftest`/`schema`. 12.3.1 ESCALATE + 12.1.7 SoD/timebox + 12.1.8 WORM audit + 12.1.1 L0 rolleri **resiprokal** bağlantılarını doğrular.
- `samples/` (23: 11 pass + 12 degrade) + `tests/` (35 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tier_b_probe.py validate          # statik model + spec + 12.3.1/12.1.7/12.1.8/12.1.1 resiprokal
python3 tier_b_probe.py selftest          # R1–R12 motoru
python3 tier_b_probe.py check samples     # 11 pass + 12 degrade
python3 tests/tier_b_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                        # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| **Bu modül:** Tier B maker-checker (SoD) + time-boxed token (60/240/auto-expiry/no-standing) + token-binding + replay-safety + WORM audit | **12.3.2** |
| **Tier B akışı:** gerekçe kodu semantiği + tenant `security_compliance_officer`/`tenant_owner` bildirimi | 12.3.3 |
| **Tier B:** regüle tenant `require_tenant_approval` toggle + DPA bağı | 12.3.4 |
| Tier sınıflandırma (A/B/forbidden) + `ESCALATE_TIER_B` (içerik/PII → break-glass) | 12.3.1 (TÜKETİLİR) |
| maker-checker SoD + timebox ÇEKİRDEĞİ + `breakglass.tier_b` aksiyonu | 12.1.7 (TÜKETİLİR) |
| rol→permission-key bundle + rol+scope yetki kararı | 12.1.2 / 12.1.3 |
| append-only/WORM audit + hash-zincir bütünlüğü | 12.1.8 (TÜKETİLİR) |

## Notlar

- **Vendor-neutral** (ADR-002/013); **stdlib-only**, **credential-free**, **deterministik** (Date.now/random yok; `tick=dakika` sanal-saat).
- **Sır/credential (break-glass token DEĞERİ / DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz** — yalnız actor rol enum + action + veri-sınıfı enum + resource_type adı + tier/decision enum + reason_code enum + ttl/tick tamsayı + slug korelasyon/aktör kimliği (`req-`/`mk-`/`ck-`/`t-`) + sha256. Bu modül Tier B **erişim-verme kararını** + token yaşam-döngüsü parametrelerini + **PII/token-free WORM audit kaydını** verir; ham satır içeriği (PII) ve ham token **akmaz**.
- Gerçek Tier B enforcement (FastAPI break-glass router + maker-checker onay UI + **time-boxed token verme/iptal** + **WORM audit yazımı** [append-only, hash-zincir, `break_glass_id`]) **F1/F2 kod aşamasında**; bu modül onlara kararı + token parametrelerini + PII/token-free audit kaydını + model bütünlük manifestini iletir.
