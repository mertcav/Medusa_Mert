# WBS 12.3.5 — Break-glass tam-audit router (ayrı, kısıtlı)

**Faz:** F2 · **Öncelik:** Must · **İz:** **SAD §14.4.2** (*"maker-checker → süreli token → ... Erişim **ayrı, kısıtlı, tam-audit'li** bir break-glass router'ı üzerinden verilir"*) · **FR-IAM-009** (üç katmanlı break-glass) · **FR-IAM-008** (L0 iş verisine tasarımca bağlı değil; erişim yalnız break-glass akışıyla) · **FR-IAM-006/FR-REC-009** (tüm break-glass erişimi audit) · FR-REC-004 (audit PII'siz) · FR-TEN-002 (tenant binding) · BRD §17/§17.7 (altın kural) · SR-IAM-009 → TC-IAM-009 · **ADR-011** (Platform Control Plane internal-only + ayrı router ağaçları/scope) · ADR-013 (üç katmanlı break-glass) · ADR-016 (audit hash-zincir)

12. workstream'in (IAM & Erişim) **üç katmanlı break-glass'ın ROUTER/ADMISSION katmanı**. SAD §14.4.2'nin Tier B kararının son cümlesini sahiplenir: *"Erişim **ayrı, kısıtlı, tam-audit'li** bir break-glass router'ı üzerinden verilir."* **Altın kural** (BRD §17): L0 (platform) tenant iş içeriğini varsayılan göremez; Tier B içeriğine erişim **yalnız** bu router'dan geçer. Bu modül erişim-verme kararını **vermez** (12.3.2/12.3.4 verir) — verilen kararı + token'ı **kısıtlı** bir kapıdan (**ayrı** router/plane/scope) geçirir ve **her** isteği **tam-audit**'ler.

Bu modül **12.3.4'ün ALLOW/HOLD/BLOCK (`sanction_decision`) kararını** ve **12.3.2'nin time-boxed token'ını TÜKETİR**; bir `BreakGlassRouterRequest` için **deterministik, fail-closed** bir **router admission** kararı verir. Terminal: **`ADMIT` | `REJECT`** (varsayılan `REJECT`).

## Karar akışı (gate)

```
BreakGlassRouterRequest ─malformed─► router_isolation ─► restricted_admission ─► token ─► scope ─► full_audit
      ├─ request_id / actor_role(L0) / target_tenant / tier≠B / sanction tanınmaz / router_context yok ──► REJECT (malformed)
      ├─ router_id≠break_glass / plane≠platform_control_plane / internal_only≠true / scope≠break_glass ──► REJECT (router_isolation) [C2 ÇEKİRDEK]
      ├─ sanction_decision ≠ ALLOW (12.3.4 HOLD/BLOCK) ─────────────────────────────────────────────────► REJECT (not_sanctioned) [C3 ÇEKİRDEK]
      ├─ token yok / state resolved / access_tick>expires_at ──────────────────────────────────────────► REJECT (token_*) [C5/C8]
      ├─ token misbound (break_glass_id/target_tenant/tier) ───────────────────────────────────────────► REJECT (token_misbound) [C6]
      ├─ scope dışı (resource_type token.scope dışı / non-Tier-B) ─────────────────────────────────────► REJECT (out_of_scope) [C7]
      └─ hepsi geçer ─────────────────────────────────────────────────────────────────────────────────► ADMIT (routed)
                            (HER karar → DEĞİŞMEZ WORM audit; C4 ÇEKİRDEK tam-audit)
```

## Router izolasyonu — AYRI (ÇEKİRDEK — SAD §14.4.2 "ayrı"; ADR-011)

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `router_id` | **`break_glass`** | break-glass router AYRI/EK bir router ağacıdır (L0/L1/L2 üçlüsünden ayrı dördüncü ağaç) |
| `plane` / `internal_only` | **`platform_control_plane`** / **true** | YALNIZ internal-only Platform Control Plane'de mount (VPN/allowlist/private-endpoint; tenant düzlemine ASLA) |
| `oauth_scope` | **`panel:L0:break_glass`** | dedicated break-glass OAuth scope; `panel:L0/L1/L2`'den **disjoint** (daha kısıtlı) |
| `mount_planes` | **`[platform_control_plane]`** | tenant_application_plane'e (public) mount = blast-radius ihlali → `router_isolation_violation` |

## Kısıtlı admission — KISITLI (ÇEKİRDEK — SAD §14.4.2 "kısıtlı"; no standing access)

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `require_sanction_allow` | **true** | istek YALNIZ `sanction_decision=ALLOW` (12.3.4 regüle onay/DPA terminali) ile ADMIT; HOLD/BLOCK → `REJECT (not_sanctioned)` |
| `require_valid_token` | **true** | + GEÇERLİ time-boxed token (12.3.2; `state=ACTIVE` + unexpired + bound); token'sız → `REJECT (token_missing)` |
| `no_standing_access` | **true** | token tek, süreli grant'tır; sanction'sız/token'sız ADMIT = `unsanctioned_admission` (sessiz/standing erişim) |

## Tam-audit — TAM-AUDIT (ÇEKİRDEK — SAD §14.4.2 "tam-audit'li"; FR-IAM-006/FR-REC-009)

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `required_for_every_request` | **true** | break-glass router'dan geçen **HER** istek (ADMIT/REJECT/malformed — girişim dahil) DEĞİŞMEZ (WORM) audit üretir — router'dan hiçbir istek audit'siz geçemez (`unaudited_request`) |
| `worm` / `no_raw_pii` / `no_raw_token` | **true** | append-only/WORM (12.1.8 RESİPROKAL); ham PII + ham token DEĞERİ yazılmaz — yalnız `token_state` ENUM (FR-REC-004) |

## İnvariant'lar (C1–C12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| C1 | | Determinizm/terminal; varsayılan **REJECT** (fail-closed); kanıt; `model_hash` sha256; `tick=dakika`; `stuck_state`/`missing_evidence=0` |
| **C2** | **SAD §14.4.2 "ayrı"** | **Router izolasyonu:** break-glass router AYRI ağaç; yalnız internal-only platform plane + dedicated break-glass scope; yanlış router/plane/scope → REJECT; `router_isolation_violation=0` (ADR-011) |
| **C3** | **SAD §14.4.2 "kısıtlı"** | **Kısıtlı admission:** yalnız `sanction=ALLOW` (12.3.4) + geçerli token (12.3.2) ile ADMIT (no standing access); sanction'sız/token'sız ADMIT → `unsanctioned_admission=0` |
| **C4** | **SAD §14.4.2 "tam-audit"** | **Tam-audit:** HER router isteği (ADMIT/REJECT/malformed) DEĞİŞMEZ (WORM) audit üretir; audit'siz istek → `unaudited_request=0` (FR-IAM-006/FR-REC-009) |
| C5 | 12.3.2 | **Token expiry/auto-expiry:** `access_tick>expires_at` veya resolved state → REJECT; `expired_token_admission=0` |
| C6 | FR-TEN-002 | **Token binding:** token `break_glass_id`+`target_tenant`+`tier=B`'ye bağlı; cross-tenant/cross-grant → `token_misbinding=0` |
| C7 | FR-IAM-009 | **Scope-limited routing:** istenen resource_type token.scope içinde + `tenant_content` + Tier B; scope dışı → `out_of_scope_routing=0` |
| C8 | 12.3.2 | **Replay-safe:** çözülmüş (CONSUMED/REVOKED/EXPIRED) token yeniden kullanılamaz; `token_replay=0` |
| C9 | FR-REC-004/ADR-016 | **Audit PII/token-free + immutable (WORM):** ham PII/token yazılmaz (yalnız `token_state` enum); kayıt tahrifatı → `audit_pii`/`audit_mutable=0` (12.1.8 RESİPROKAL) |
| C10 | ADR-011/013 | Model bütünlük manifesti (`model_hash` sha256); router-izolasyon/admission/tam-audit yüzeyi tahrifatı yakalanır; `model_tampered=0` |
| C11 | 0.4.7 | Gözlemlenebilirlik kardinalite: actor_role/decision/result/plane düşük-kard; break_glass_id/target_tenant_id trace-only; PII label'da yok |
| C12 | BRD §17.7 | Sır/içerik yok: yalnız rol + realm + sınıf + kaynak + router/plane/scope enum + tier/decision enum + sanction/token_state enum + tick + slug korelasyon + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.3.x deseniyle birebir: motor **doğru** router admission davranışını hesaplar (her uygunsuz istek → REJECT), `inject` doğru davranışı **bozar** (uygunsuz isteği güvensiz ADMIT'e çevirir) ve eşleşen ihlal sayacını artırır → kapı eler. 12 enjeksiyon: `mount_on_tenant_plane`, `wrong_router_scope`, `admit_unsanctioned`, `admit_without_token`, `admit_expired_token`, `replay_token`, `admit_misbound_token`, `route_out_of_scope`, `skip_audit`, `leak_pii`, `mutate_audit`, `model_tamper` (+ `secret_leak` tarayıcı).

**Anahtar çekirdek ispatı:** `mount_on_tenant_plane`/`wrong_router_scope` → yanlış düzlem/scope servisi → `router_isolation_violation>0` ("ayrı" çiğnendi). `admit_unsanctioned`/`admit_without_token` → sanction'sız/token'sız ADMIT → `unsanctioned_admission>0` ("kısıtlı" çiğnendi). `skip_audit` → audit'siz erişim → `unaudited_request>0` ("tam-audit" çiğnendi).

## Dosyalar

- `config/break-glass-router-model.json` — **frozen** model (`router_policy` [router_id=break_glass + plane=platform_control_plane + internal_only + oauth_scope=panel:L0:break_glass + scope_disjoint + mount_planes] + `admission_policy` [require_sanction_allow + require_valid_token + no_standing_access] + `token_policy` [active/resolved_states + binding; 12.3.2 RESİPROKAL] + `scope_policy` [tier_b_only + content_class] + `concurrency_policy` [replay-safe] + `audit` [WORM; PII/token-free; 12.1.8 RESİPROKAL] + `actor_roles` [L0; 12.1.1 RESİPROKAL]).
- `break-glass-router-spec.json` — makine-okunur spec (9 kural + karar + C1–C12 + 13 sıfır-eşik HARD kapı + gözlemlenebilirlik).
- `break_glass_router_probe.py` — router admission motoru + `validate`/`check`/`selftest`/`schema`. 12.3.4 sanction_decision + 12.3.2 time-boxed token + 12.2.2 router topolojisi + 12.1.8 WORM audit + 12.1.1 aktör rolleri **resiprokal** bağlantılarını doğrular.
- `samples/` (23: 11 pass + 12 degrade) + `tests/` (C1–C12 bağımsız) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 break_glass_router_probe.py validate          # statik model + spec + 12.3.4/12.3.2/12.2.2/12.1.8/12.1.1 resiprokal
python3 break_glass_router_probe.py selftest          # C1–C12 motoru
python3 break_glass_router_probe.py check samples     # 11 pass + 12 degrade
python3 tests/break_glass_router_behavior_test.py     # bağımsız C1–C12
./run_live_test.sh                                    # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| **Bu modül:** break-glass ROUTER ADMISSION (router izolasyonu [ayrı] + kısıtlı admission [sanction+token] + tam-audit + scope-limited routing + token doğrulama [unexpired/bound/replay] + WORM audit) | **12.3.5** |
| **Tier B erişim-verme + time-boxed token ÜRETİMİ:** maker-checker (SoD) + token (60/240/auto-expiry/no-standing) | 12.3.2 (token TÜKETİLİR) |
| **Regüle tenant onay toggle + DPA** → `sanction_decision` (ALLOW/HOLD/BLOCK) | 12.3.4 (TÜKETİLİR) |
| Tier B gerekçe kodu + tenant `security_compliance_officer`/`tenant_owner` bildirimi | 12.3.3 |
| Tier sınıflandırma (A/B/forbidden) + `ESCALATE_TIER_B` | 12.3.1 |
| Panel router topolojisi (L0/L1/L2 ayrı ağaçlar/scope) — break-glass router AYRI/EK dördüncü ağaç | 12.2.2 (RESİPROKAL) |
| rol→permission-key bundle + scope | 12.1.2 / 12.1.3 |
| append-only/WORM audit + hash-zincir bütünlüğü | 12.1.8 (TÜKETİLİR) |

## Notlar

- **Vendor-neutral** (ADR-002/011/013); **stdlib-only**, **credential-free**, **deterministik** (Date.now/random yok; `tick=dakika` sanal-saat).
- **Sır/credential (break-glass token DEĞERİ / DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz** — yalnız actor rol enum + realm enum (platform) + veri-sınıfı enum (tenant_content) + resource_type adı + router/plane/scope enum (break_glass/platform_control_plane/panel:L0:break_glass) + tier/decision enum + sanction enum (ALLOW/HOLD/BLOCK) + token_state enum (ACTIVE/CONSUMED/...) + tick tamsayı + slug korelasyon/kimlik (`req-`/`bg-`/`t-`) + sha256. Token bu modülde YALNIZ `state` ENUM + bound slug kimlik olarak görünür; ham token DEĞERİ **akmaz**.
- Gerçek break-glass router enforcement (FastAPI **ayrı router ağacı** + **internal-only Platform Control Plane mount** + **dedicated break-glass OAuth scope dependency** + **admission** [sanction=ALLOW + geçerli token doğrulama] + **scope-limited routing** + **WORM audit yazımı** [append-only, hash-zincir, `break_glass_id`]) **F1/F2 kod aşamasında**; bu modül onlara ADMISSION kararını + scope kanıtını + PII/token-free WORM audit kaydını + model bütünlük manifestini iletir.
