# WBS 12.3.1 — Tier A (metrik/log, PII yok): break-glass'sız L0 erişimi + audit

**Faz:** F1 · **Öncelik:** Must · **İz:** **FR-IAM-009** (üç katmanlı break-glass) · BRD §17.7 (*"Tier A — metrik/log [PII yok]: Break-glass gerekmez; normal L0 erişimi + audit"*) · SAD §14.4.2 (aynı) · **FR-IAM-006/FR-REC-009** (tüm L0 erişimi audit) · **FR-IAM-008** (L0 ⟂ iş içeriği) · FR-REC-004 (audit PII'siz) · SR-IAM-009 → TC-IAM-009 · ADR-013 (üç katmanlı break-glass) · ADR-016 (audit hash-zincir)

12. workstream'in (IAM & Erişim) **üç katmanlı break-glass'ın EN DÜŞÜK katmanı (Tier A)** modülü. SAD §14.4.2 / BRD §17.7'nin temel kararını sahiplenir: *"Tier A (metrik/log, PII yok): break-glass gerekmez; normal L0 erişimi **+ audit**."* ve **altın kural** (BRD §17): *"L0 (platform) tenant'ın iş içeriğini (çağrı kaydı, transkript, müşteri/PII) varsayılan GÖREMEZ — yalnız metrik/kaynak verisi."* Bir `L0AccessRequest` için **deterministik, fail-closed** bir Tier kararı verir. Terminal: **`TIER_A_GRANT` | `ESCALATE_TIER_B` | `DENY`**.

Tier A, **break-glass GEREKTİRMEZ** ancak **her erişim DEĞİŞMEZ (WORM) audit kaydı üretir** — sessiz L0 erişimi yoktur. İçerik/PII (transcript/recording/contact) bu katmanda **sunulmaz**: break-glass gerekir → `ESCALATE_TIER_B` (akış 12.3.2/12.3.3/12.3.4'e **DELEGE**).

## Karar akışı (gate)

```
L0AccessRequest ─malformed─► classification ─► tier ─► admission ─► audit ─► (pii/bypass/escalation/...)
      ├─ request_id / actor_role(L0) / data_class+resource_type eksik|geçersiz ──► DENY (malformed)
      ├─ data_class bilinmiyor → fail-closed DENY; zorla kabul ──────────────────► unclassified_access [R2]
      ├─ tier A (metric/platform/reference) → TIER_A_GRANT (no break-glass + audit)
      ├─ tier B (tenant_content)            → ESCALATE_TIER_B (break-glass; 12.3.2/3/4'e delege)
      ├─ forbidden (tenant_config)          → DENY (L0 yolu yok; 12.2.4 forbidden_for_platform)
      ├─ TIER_A_GRANT ∧ data_class∈content ──────────────────────────────────────► pii_under_tier_a [R3 ÇEKİRDEK]
      ├─ content ∧ terminal=TIER_A_GRANT (break-glass atlandı) ───────────────────► break_glass_bypass [R5]
      ├─ content ∧ sessizce düşürüldü (escalate yerine DENY) ─────────────────────► escalation_error [R6]
      ├─ TIER_A_GRANT ∧ audit_emitted=False ─────────────────────────────────────► unaudited_access [R4 ÇEKİRDEK]
      ├─ audit kaydı ham PII taşır ──────────────────────────────────────────────► audit_pii [R7]
      └─ emitilen audit değiştirildi (row_hash uyumsuz) ─────────────────────────► audit_mutable [R8]
```

## Tier ↔ veri-sınıfı eşlemesi (12.2.4 RESİPROKAL)

| Tier | Veri-sınıfı | Örnek | L0 davranışı |
|------|-------------|-------|--------------|
| **A** | `tenant_metric` | usage_record (kullanım/kaynak) | **TIER_A_GRANT** — break-glass'sız + **audit** |
| **A** | `platform` | tenant, audit_log, incident, break_glass_grant | **TIER_A_GRANT** — break-glass'sız + **audit** |
| **A** | `global_reference` | role, permission_key, role_permission | **TIER_A_GRANT** — break-glass'sız + **audit** |
| **B** | `tenant_content` | transcript, recording, contact (PII/içerik) | **ESCALATE_TIER_B** — break-glass gerekir (delege 12.3.2/3/4) |
| — | `tenant_config` | agent, prompt, campaign | **DENY** — L0 yolu yok (tasarım izolasyonu) |

`tier_a_classes` (PII'siz) = 12.2.4 `allowed_for_platform`; `tier_b_content` sınıfı (`tenant_content`) = 12.2.4 `break_glass.content_tables` sınıfı (**RESİPROKAL**). Sınıflandırılamayan kaynak → **fail-closed DENY** (bilinmeyen = içerik/PII varsay).

## İnvariant'lar (R1–R12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| R1 | | Determinizm/terminal; varsayılan **DENY** (fail-closed); kanıt; `model_hash` sha256; audit `occurred_tick` sanal-saat; `stuck_state`/`missing_evidence=0` |
| R2 | | **Classification coverage:** her erişim sınıflandırılır; bilinmeyen → fail-closed DENY; `unclassified_access=0` |
| **R3** | **BRD §17.7** | **No PII under Tier A (ALTIN KURAL):** `TIER_A_GRANT` yalnız PII'siz sınıflar; içerik/PII Tier A'da ASLA sunulmaz; `pii_under_tier_a=0` (FR-IAM-008/009) |
| **R4** | **BRD §17.7** | **Audit emitted (sessiz erişim yok):** her `TIER_A_GRANT` (ve her L0 erişim kararı) DEĞİŞMEZ (WORM) audit üretir; `unaudited_access=0` (FR-IAM-006/FR-REC-009; 12.1.8 RESİPROKAL) |
| **R5** | FR-IAM-009 | **No break-glass bypass:** içerik/PII break-glass yolunu (12.3.2/3/4) atlayamaz; `break_glass_bypass=0` |
| R6 | SAD §14.4.2 | **Escalation correct:** içerik → `ESCALATE_TIER_B` (delege); sessiz düşürme/yanlış yön yok; `escalation_error=0` |
| R7 | FR-REC-004 | **Audit PII-free:** audit kaydı ham içerik/PII tutmaz; `audit_pii=0` |
| R8 | ADR-016 | **Audit immutability (WORM):** append-only; `row_hash` sha256; emitilen kayıt tahrifatı tespit (12.1.8 hash-zincir RESİPROKAL); `audit_mutable=0` |
| R9 | FR-IAM-009 | **Tier separation:** Tier A break-glass token/maker-checker/gerekçe GEREKTİRMEZ (bunlar Tier B; 12.3.2/3/4); `tier_confusion=0` |
| R10 | ADR-013 | Model bütünlük manifesti (`model_hash` sha256); tier-map/audit-zorunluluğu tahrifatı yakalanır; `model_tampered=0` |
| R11 | 0.4.7 | Gözlemlenebilirlik kardinalite: actor_role/data_class/tier/decision düşük-kard; correlation_id/resource_id/row_hash trace-only; PII label'da yok |
| R12 | BRD §17.7 | Sır/içerik yok: yalnız rol + action + sınıf + kaynak adı + tier/decision enum + slug korelasyon + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x deseniyle birebir: motor **doğru** Tier A davranışını hesaplar, `inject` doğru davranışı **bozar** ve eşleşen ihlal sayacını artırır → kapı eler. 9 enjeksiyon: `grant_content_at_tier_a`, `skip_audit`, `leak_pii_in_audit`, `mutate_audit`, `drop_escalation`, `tier_b_artifact_at_tier_a`, `unclassify`, `model_tamper`, `secret_leak`.

**Anahtar çekirdek ispatı:** `grant_content_at_tier_a` → içerik (transcript) Tier A'da sunulur → `pii_under_tier_a>0` **ve** `break_glass_bypass>0` (altın kural + break-glass iki invariant'la yakalanır). `skip_audit` → Tier A grant audit'siz → `unaudited_access>0` (sessiz erişim).

## Dosyalar

- `config/tier-a-model.json` — **frozen** model (`tiers` [A no-bg+audit / B bg-delege] + `tier_a_classes` [PII'siz] + `tier_b_content` [tenant_content] + `forbidden_classes` [tenant_config] + `table_class_of` [37 varlık; 12.2.4 RESİPROKAL] + `audit` [WORM; PII'siz; 12.1.8 RESİPROKAL] + `actor_roles` [L0; 12.1.1 RESİPROKAL]).
- `tier-a-spec.json` — makine-okunur spec (9 kural + karar + R1–R12 + kapılar).
- `tier_a_probe.py` — Tier A karar motoru + `validate`/`check`/`selftest`/`schema`. 12.2.4 veri-sınıfı + 12.1.8 WORM audit + 12.1.1 L0 rolleri **resiprokal** bağlantılarını doğrular.
- `samples/` (17: 9 pass + 8 degrade) + `tests/` (26 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tier_a_probe.py validate          # statik model + spec + 12.2.4/12.1.8/12.1.1 resiprokal
python3 tier_a_probe.py selftest          # R1–R12 motoru
python3 tier_a_probe.py check samples     # 9 pass + 8 degrade
python3 tests/tier_a_behavior_test.py     # bağımsız R1–R12
./run_live_test.sh                        # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| **Tier B akışı:** maker-checker + time-boxed token (60dk default/max 4sa/auto-expiry) | 12.3.2 |
| **Tier B akışı:** gerekçe kodu + tenant `security_compliance_officer`/`tenant_owner` bildirimi | 12.3.3 |
| **Tier B:** regüle tenant `require_tenant_approval` toggle + DPA bağı | 12.3.4 |
| rol→permission-key bundle + rol+scope yetki kararı | 12.1.1 / 12.1.3 |
| design-time L0 ⟂ tenant iş verisi repository/grant bağımsızlığı (veri-sınıfı taksonomisi TÜKETİLİR) | 12.2.4 |
| HTTP `enforce_tenant_scope` + RLS çalışma-anı | 12.2.1 / 12.2.3 |
| append-only/WORM audit + hash-zincir bütünlüğü (audit immutability TÜKETİLİR) | 12.1.8 |

## Notlar

- **Vendor-neutral** (ADR-002/013); **stdlib-only**, **credential-free**, **deterministik** (Date.now/random yok; audit `occurred_tick` sanal-saat).
- **Sır/credential (break-glass token/DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz** — yalnız actor rol enum + action + veri-sınıfı enum + resource_type adı + tier/decision enum + slug korelasyon kimliği + sha256. Bu modül Tier **admission kararını** + **PII'siz audit kaydını** verir; ham satır içeriği (PII) **akmaz**.
- Gerçek Tier A enforcement (FastAPI L0 erişimi + **WORM audit yazımı** [append-only, hash-zincir] + Tier B break-glass router) **F1 kod aşamasında**; bu modül onlara kararı + PII'siz audit kaydını + model bütünlük manifestini iletir.
