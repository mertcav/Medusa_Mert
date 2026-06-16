# WBS 12.3.3 — Tier B break-glass: gerekçe kodu + tenant security_compliance_officer/tenant_owner bildirimi

**Faz:** F2 · **Öncelik:** Must · **İz:** **FR-IAM-009** (üç katmanlı break-glass) · BRD §17.7/§17 (*"Tier B — transkript/kayıt/PII: ... + **zorunlu gerekçe kodu** + tenant'ın `security_compliance_officer` ve `tenant_owner` rollerine **anlık bildirim**"*) · SAD §14.4.2 (aynı; *"→ zorunlu gerekçe kodu → tenant `security_compliance_officer` + `tenant_owner`'a anlık bildirim"*) · **FR-IAM-006/FR-REC-009** (break-glass erişimi audit) · FR-REC-004 (audit/bildirim PII'siz) · FR-TEN-002 (bildirim tenant-binding) · SR-IAM-009 → TC-IAM-009 · ADR-013 (üç katmanlı break-glass) · ADR-016 (audit hash-zincir)

12. workstream'in (IAM & Erişim) **üç katmanlı break-glass'ın İÇERİK/PII katmanının (Tier B)** gerekçe-kodu + bildirim modülü. BRD §17.7 / SAD §14.4.2'nin Tier B kararının **iki kalan koşulunu** sahiplenir: (1) **zorunlu gerekçe kodu** (semantik: kontrollü kelime dağarcığı) ve (2) tenant'ın `security_compliance_officer` + `tenant_owner` rollerine **anlık bildirim** — böylece tenant kendi içeriğine platform erişimini **derhal** öğrenir. **Altın kural** (BRD §17): L0 (platform) tenant'ın iş içeriğini varsayılan göremez; Tier B yalnız bu **dar, süreli, onaylı, tam-audit'li** kapıyı açar ve bu modül o kapıdan geçen her erişimi tenant'a **şeffaf** kılar (sessiz break-glass yok).

Bu modül **12.3.2'nin `access_decision` (`GRANT_TIER_B`/`PENDING`/`DENY`) çıktısını tüketir**; bir `BreakGlassTierBNotifyEvent` için **deterministik, fail-closed** bir karar verir. Terminal: **`NOTIFY` | `NO_NOTIFY` | `BLOCK`**.

## Karar akışı (gate)

```
BreakGlassTierBNotifyEvent ─malformed─► access_routing ─► reason_required ─► reason_semantics ─► notification ─► audit/replay
      ├─ request_id / actor_role(L0) / target_tenant / tier≠B / access_decision tanınmaz ──► BLOCK (malformed)
      ├─ access_decision ∈ {PENDING, DENY} (içerik okunmadı) ──────────────────────────────► NO_NOTIFY [N1 doğru]
      ├─ reason_code eksik ──────────────────────────────────────────────────────────────► BLOCK (missing_reason_code) [N2 ÇEKİRDEK]
      ├─ reason_code katalog dışı / serbest-metin ───────────────────────────────────────► BLOCK (invalid_reason_code) [N3 ÇEKİRDEK]
      ├─ prior_state çözülmüş (DELIVERED/ACKNOWLEDGED) ──────────────────────────────────► NO_NOTIFY (already_notified) [N9 doğru]
      ├─ eksik zorunlu alıcı rol (SCO veya owner yok) ───────────────────────────────────► incomplete_recipients [N4 ÇEKİRDEK]
      ├─ SLA dışı (geç) bildirim ────────────────────────────────────────────────────────► delayed_notification [N5 ÇEKİRDEK]
      ├─ teslim edilmemiş/düşürülmüş bildirim ile GRANT ─────────────────────────────────► notification_dropped [N6 ÇEKİRDEK]
      ├─ cross-tenant alıcı ─────────────────────────────────────────────────────────────► notification_misroute [N7]
      └─ NOTIFY audit'siz | audit/bildirim ham PII/token | emitilen audit tahrif ─────────► unaudited_notification / audit_pii / audit_mutable [N8]
```

## Gerekçe kodu semantiği (ÇEKİRDEK — FR-IAM-009 "zorunlu gerekçe kodu")

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `require_reason_code` | **true** | her Tier B GRANT bir `reason_code` taşımak zorunda; eksik → `BLOCK (missing_reason_code)` |
| `controlled_vocabulary` | **true** | `reason_code` serbest-metin değil; kontrollü `reason_code_catalog`'dan opak bir kod olmalı |
| `free_text_forbidden` | **true** | katalog dışı / serbest-metin gerekçe → `BLOCK (invalid_reason_code)` |
| `reason_code_catalog` | `rc-incident-debug`, `rc-quality-review`, `rc-security-investigation`, `rc-legal-hold`, `rc-data-subject-request`, `rc-compliance-audit`, `rc-customer-escalation` | opak kodlar (PII değil); mühendislik varsayılanı, tenant/compliance profili yalnız-ekleme genişletebilir (F1/F2) |

## Bildirim (ÇEKİRDEK — FR-IAM-009 "anlık bildirim")

| Parametre | Değer | Anlam |
|-----------|-------|-------|
| `required_recipient_roles` | **`security_compliance_officer` + `tenant_owner`** | bildirim **her iki** tenant rolüne gitmeli (12.1.1 RESİPROKAL; tenant realm L1) |
| `immediate` / `notify_sla_ticks` | **true** / **1** | bildirim erişim anından ≤1 tick (dakika) içinde teslim; SLA dışı = `delayed_notification` |
| `require_delivery` / `no_silent_access` | **true** | her GRANT **teslim edilen** bildirim üretir; sessiz/bastırılmış = `notification_dropped` (sessiz break-glass) |
| `tenant_bound` | **true** | alıcılar yalnız `target_tenant`; cross-tenant = `notification_misroute` |
| `pii_free` | **true** | bildirim yükü ham içerik/PII/token taşımaz |

`tick = dakika` (sanal-saat; Date.now yok).

## İnvariant'lar (N1–N12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| N1 | | Determinizm/terminal; varsayılan **BLOCK** (fail-closed); access routing (PENDING/DENY → NO_NOTIFY); kanıt; `model_hash` sha256; `tick=dakika`; `stuck_state`/`missing_evidence=0` |
| **N2** | **FR-IAM-009** | **Gerekçe kodu zorunlu:** GRANT gerekçe kodu olmadan ilerleyemez; eksik → `BLOCK`; `missing_reason_code=0` |
| **N3** | **FR-IAM-009** | **Gerekçe kodu semantiği:** `reason_code` kontrollü kataloğdan; serbest-metin/bilinmeyen → `BLOCK`; `invalid_reason_code=0` |
| **N4** | **FR-IAM-009** | **Her iki rol:** bildirim `security_compliance_officer` VE `tenant_owner`'a gider; eksik → `incomplete_recipients=0` (12.1.1 RESİPROKAL) |
| **N5** | **FR-IAM-009** | **Anlık:** bildirim `notify_sla_ticks` içinde teslim; SLA dışı → `delayed_notification=0` |
| **N6** | **BRD §17** | **Sessiz break-glass yok:** her GRANT teslim edilen bildirim üretir; düşürülmüş → `notification_dropped=0` |
| N7 | FR-TEN-002 | **Bildirim tenant-binding:** alıcılar yalnız `target_tenant`; cross-tenant = `notification_misroute=0` |
| N8 | FR-REC-009/ADR-016 | **Audit (WORM, PII/token-free, immutable):** her karar değişmez (WORM) audit (`break_glass_id` ile); `unaudited_notification`/`audit_pii`/`audit_mutable=0` (12.1.8 RESİPROKAL) |
| N9 | FR-IAM-009 | **Replay-safe/idempotent:** bir grant için tek bildirim; çözülmüş (DELIVERED/ACKNOWLEDGED) bildirim yeniden gönderilemez; `notify_replay=0` |
| N10 | ADR-013 | Model bütünlük manifesti (`model_hash` sha256); gerekçe/bildirim yüzeyi tahrifatı yakalanır; `model_tampered=0` |
| N11 | 0.4.7 | Gözlemlenebilirlik kardinalite: actor_role/decision/result/recipient_role düşük-kard; break_glass_id/target_tenant_id/reason_code trace-only; PII label'da yok |
| N12 | BRD §17.7 | Sır/içerik yok: yalnız rol + alıcı rol + sınıf + kaynak adı + tier/decision enum + reason_code enum + tick + slug korelasyon + hash; `secret_or_pii=0` |

## Degrade (inject) motoru

12.1.x/12.2.x/12.3.1/12.3.2 deseniyle birebir: motor **doğru** bildirim davranışını hesaplar, `inject` doğru davranışı **bozar** ve eşleşen ihlal sayacını artırır → kapı eler. 12 enjeksiyon: `omit_reason_code`, `freeform_reason`, `drop_sco_recipient`, `drop_owner_recipient`, `delayed_notification`, `suppress_notification`, `cross_tenant_recipient`, `notify_replay`, `skip_audit`, `leak_pii_in_notification`, `mutate_audit`, `model_tamper` (+ `secret_leak` tarayıcı).

**Anahtar çekirdek ispatı:** `omit_reason_code` → gerekçesiz GRANT → `missing_reason_code>0`. `freeform_reason` → katalog dışı gerekçe → `invalid_reason_code>0`. `drop_sco_recipient`/`drop_owner_recipient` → tek role bildirim → `incomplete_recipients>0`. `suppress_notification` → teslim edilmemiş bildirim → `notification_dropped>0` (sessiz break-glass). `delayed_notification` → SLA dışı → `delayed_notification>0`.

## Dosyalar

- `config/tier-b-notify-model.json` — **frozen** model (`reason_code_policy` [require + controlled_vocabulary + reason_code_catalog] + `notification_policy` [required_recipient_roles=SCO+owner + immediate/notify_sla_ticks + require_delivery + tenant_bound + pii_free; 12.1.1 RESİPROKAL] + `concurrency_policy` [replay-safe] + `audit` [WORM; PII/token-free; `break_glass_id`+`notified_roles`; 12.1.8 RESİPROKAL] + `actor_roles` [L0; 12.1.1 RESİPROKAL]).
- `tier-b-notify-spec.json` — makine-okunur spec (10 kural + karar + N1–N12 + 14 sıfır-eşik HARD kapı + gözlemlenebilirlik).
- `tier_b_notify_probe.py` — Tier B gerekçe-kodu + bildirim motoru + `validate`/`check`/`selftest`/`schema`. 12.3.2 access_decision + 12.1.1 alıcı/aktör rolleri + 12.1.8 WORM audit **resiprokal** bağlantılarını doğrular.
- `samples/` (23: 11 pass + 12 degrade) + `tests/` (37 kontrol) + `run_live_test.sh`.

## Çalıştırma

```bash
python3 tier_b_notify_probe.py validate          # statik model + spec + 12.3.2/12.1.1/12.1.8 resiprokal
python3 tier_b_notify_probe.py selftest          # N1–N12 motoru
python3 tier_b_notify_probe.py check samples     # 11 pass + 12 degrade
python3 tests/tier_b_notify_behavior_test.py     # bağımsız N1–N12
./run_live_test.sh                               # hepsi
```

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| **Bu modül:** Tier B gerekçe-kodu zorunluluğu + semantiği (kontrollü katalog) + tenant `security_compliance_officer`/`tenant_owner` anlık bildirimi (her iki rol + anlık + teslim + tenant-bound) + WORM audit | **12.3.3** |
| **Tier B erişim-verme:** maker-checker (SoD) + time-boxed token (60/240/auto-expiry/no-standing) + token-binding + replay-safety | 12.3.2 (TÜKETİLİR) |
| **Tier B:** regüle tenant `require_tenant_approval` toggle + DPA bağı | 12.3.4 |
| Tier sınıflandırma (A/B/forbidden) + `ESCALATE_TIER_B` | 12.3.1 |
| rol→permission-key bundle + alıcı/aktör rolleri | 12.1.1 / 12.1.2 / 12.1.3 |
| append-only/WORM audit + hash-zincir bütünlüğü | 12.1.8 (TÜKETİLİR) |

## Notlar

- **Vendor-neutral** (ADR-002/013); **stdlib-only**, **credential-free**, **deterministik** (Date.now/random yok; `tick=dakika` sanal-saat).
- **Sır/credential (break-glass token DEĞERİ / DB şifresi) ve ham içerik (transcript/recording/contact PII) repoya yazılmaz** — yalnız actor rol enum + alıcı rol enum + veri-sınıfı enum + resource_type adı + tier/decision enum + reason_code **opak** enum (`rc-*`; serbest-metin değil, PII değil) + tick tamsayı + slug korelasyon/aktör kimliği (`req-`/`bg-`/`t-`) + sha256. Bu modül Tier B **gerekçe-kodu + bildirim kararını** + **PII/token-free WORM audit kaydını** verir; ham satır içeriği (PII), ham token ve bildirim yükündeki PII **akmaz**.
- Gerçek Tier B enforcement (FastAPI break-glass router + **gerekçe-kodu enforcement** + **bildirim dispatch** [e-posta/webhook/in-app → tenant `security_compliance_officer`/`tenant_owner`] + **WORM audit yazımı** [append-only, hash-zincir, `break_glass_id`]) **F1/F2 kod aşamasında**; bu modül onlara kararı + bildirim kaydını + PII/token-free audit kaydını + model bütünlük manifestini iletir.
