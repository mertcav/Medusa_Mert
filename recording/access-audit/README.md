# WBS 11.6 — Kayıt/transkript erişim audit'i

**Faz:** F1 · **Öncelik:** Must · **İz:** BRD §9.14 → FR-REC-009 → SR-REC-009 → TC-REC-009 (A)

11. workstream'in (Kayıt, Transkript & PII Redaction) **erişim audit** modülü. Bir kayıt (`recording`)
veya transkript (`transcript`) erişim talebini alır → **deterministik, fail-closed** bir erişim-audit
**kararı** verir: tenant izolasyonu + audit-sink kapısı + **yetki** (RBAC permission + sahiplik + L0
Tier B break-glass) + **ZORUNLU WORM audit** (`prev_hash → row_hash` hash-chained, sha256) + residency.
Terminal karar: **`GRANTED` | `DENIED` | `BLOCK`**.

Modül **11.1–11.4 içerik üretim zincirinin aşağı akış ERİŞİM KAPISIDIR**: 11.4 PII redaction tamamlanıp
transkript görüntülemeye-hazır (`access_ready`) olduktan sonra, bu modül **bir erişim talebinin yetkili
olduğunu** (FR-REC-008) ve **her erişimin audit'lendiğini** (FR-REC-009) güvence altına alır. Audit
**içeriği değil ERİŞİMİ** kaydeder — ham kayıt byte / transkript metni / PII değeri hiçbir audit alanında
yoktur (BRD §17.7).

## Karar akışı

```
AccessAuditRequest ─tenant─► audit-sink ─► break-glass ─► yetki ─► WORM audit ─► residency
      ├─ cross-tenant (tenant realm) ─────────────────────────────► BLOCK (cross_tenant)       [K12]
      ├─ malformed (resource/action/realm) ──────────────────────► BLOCK (malformed_request)
      ├─ audit-sink yok ─────────────────────────────────────────► BLOCK (no_audit_sink)       [K2/K5]
      ├─ L0 Tier B break-glass yok/geçersiz ─────────────────────► DENIED (audited)             [K6]
      ├─ yetki yok / sahiplik dışı / raw yetki yok ──────────────► DENIED (audited)             [K4]
      └─ yetkili ─────────────────────────────────────────────────► GRANTED (audited)           [K2/K3]
```

**Çekirdek garanti (K2, FR-REC-009):** `access_granted ⇒ audit_written` — audit yazılmadan erişim verilemez;
audit-sink yoksa **fail-closed BLOCK** (auditlenemeyen erişim yok). `unaudited_access = 0`.
**Çekirdek garanti (K3, FR-IAM-006 / DB §27):** audit WORM (append-only) + `prev_hash → row_hash` hash-chained
(sha256); tahrifat (`audit_tampered`) / zincir kırılması (`chain_break`) yasak.
**Çekirdek garanti (K4, FR-REC-008):** `GRANTED ⇒ authorized` (permission + sahiplik + L0 break-glass);
yetkisiz GRANTED (`unauthorized_access`) yasak; **yetkisiz talep DENIED ama yine de audit'lenir** (başarısız
erişimler de denetlenir).
**Çekirdek garanti (K6, FR-IAM-009/010):** L0 platform Tier B erişimi maker≠checker + time-boxed (max 240dk,
standing access yok) + gerekçe kodu + tenant-kapsam ister; self-approval/expired/standing = `break_glass_violation`.

## İnvariant'lar (K1–K12)

| ID | Çekirdek | Açıklama |
|----|----------|----------|
| K1 | | Determinizm/terminal; `stuck_state=0` |
| **K2** | FR-REC-009 | Zorunlu audit: `access_granted ⇒ audit_written`; audit-sink yok ⇒ BLOCK; `unaudited_access=0` |
| **K3** | FR-IAM-006 / DB §27 | WORM/hash-chain: `prev_hash→row_hash`; `audit_tampered=0`, `chain_break=0` |
| **K4** | FR-REC-008 | Yetki kapısı: `GRANTED ⇒ authorized`; `unauthorized_access=0` |
| **K5** | SR-REC-009 | Atlanamaz: `skip_audit=0`; audit-sink yok ⇒ BLOCK (`failopen=0`); L0 altın kural |
| **K6** | FR-IAM-009/010 | Break-glass disiplini: maker≠checker + süreli + gerekçe + kapsam; `break_glass_violation=0` |
| K7 | NFR 10.7 | Residency: sunulan içerik home-region'da |
| **K8** | FR-REC-009 / BRD §17.7 | Ham içerik/PII yok: audit yalnız kimlik+enum+`break_glass_id`+hash; `pii_leak=0` |
| K9 / K10 | FR-IAM-006 | Kanıt + WORM audit (no_audit_sink dışında zorunlu) |
| K11 | FR-REC-009 | Gözlemlenebilirlik düşük-kardinalite + ham içerik/PII yok |
| K12 | FR-TEN-002 | Sır/ham-içerik yok + tenant izolasyonu |

## Yetki + break-glass

- **Kaynak → permission (SAD §14.4.3):** `recording → calls:read` (sahiplik `calls:read:own`),
  `transcript → transcript:read` (sahiplik `transcript:read:own`), **ham (raw) transkript → `transcript:manage`**
  (yükseltilmiş; maskelenmemiş erişim ayrı yetki + audit, API §6.x / FR-REC-009).
- **L0 altın kural (FR-IAM-008):** platform realm tenant içeriğine (recording/transcript) **varsayılan
  erişemez**; yalnız **geçerli break-glass grant** ile (Tier B).
- **Break-glass (FR-IAM-009/010; ADR-013):** maker≠checker + time-boxed (varsayılan 60dk, max 240dk,
  **standing access yok**) + zorunlu gerekçe kodu + tenant-kapsam. Regüle tenant `require_tenant_approval`
  toggle'ı (DPA bağlı). Bu modül grant'ı **doğrular** (üretmez — workflow + tenant bildirimi FR-IAM-009).

## WORM hash chain (DB §27)

Her erişim kararı (GRANTED/DENIED) bir audit kaydı üretir; kayıt `prev_hash` ile önceki kayda bağlanır ve
`row_hash = sha256(prev_hash + kanonik(record))` ile imzalanır. **Tahrifat** (kayıt değişip hash
güncellenmezse `recompute ≠ row_hash`) ve **zincir kırılması** (`prev_hash` koparsa) deterministik olarak
yakalanır. Fiziksel append-only WORM partition yazımı + retention **DB §27 / retention motoru**.

## Çalıştırma

```bash
./run_live_test.sh                                  # tüm kapılar (statik)
python3 access_audit_probe.py validate              # statik spec/config/kapsama
python3 access_audit_probe.py selftest              # gömülü davranış (K1–K12)
python3 access_audit_probe.py check samples         # 13 pass + 12 degrade
python3 access_audit_probe.py schema                # karar sözleşmesi
python3 tests/access_audit_behavior_test.py         # bağımsız davranış testi
```

**Durum:** validate **108/108** 🟢 · selftest **72/72** 🟢 · check **25/25** 🟢 (12 degrade beklendiği gibi
elendi) · behavior **79/79** 🟢.

## Dosyalar

| Dosya | İçerik |
|-------|--------|
| `access-audit-spec.json` | Kaynak doğruluk: kurallar, karar, resources, break_glass, audit_record, invariant'lar K1–K12, kapılar, izlenebilirlik |
| `access_audit_probe.py` | stdlib-only motor: `validate` / `check` / `selftest` / `schema` (WORM hash chain sha256) |
| `config/access-audit.json` | Kaynak→permission haritası + tier_b + break-glass disiplini + audit WORM/hash_chain |
| `samples/*.json` | 13 pass + 12 degrade senaryo (FR-TST-008) |
| `tests/access_audit_behavior_test.py` | Bağımsız davranış testi |
| `run_live_test.sh` | Statik + davranış kapısı koşucusu |

## Kapsam ayrımı (bilinçli — başka modül sahibi)

| Konu | Sahip |
|------|-------|
| Kayıt/içerik **kararı** + tamamen kapatma | 11.1 (recording-policy) |
| Kanal/track yerleşimi | 11.2 (channel-recording) |
| Transkript **üretimi** (FR-REC-008/BRD §8.1) | 11.3 (transcript-build) |
| PII redaction (maskeleme planı + `redaction_state` + `access_ready`) | 11.4 (pii-redaction; **tüketilir**) |
| Kart/parola/OTP **kayıttan** çıkarma (FR-REC-005) | 11.5 (secret-extraction) |
| Break-glass talep/onay **akışı** + grant **üretimi** + tenant bildirimi (FR-IAM-009) | API §6 break-glass router (grant **doğrulanır**) |
| `audit_log` **fiziksel** şema + WORM depolama + retention | DB §27 / retention motoru (audit **kaydı** + hash zinciri üretilir) |
| RBAC permission **atamaları** + rol bundle (FR-IAM-011) | ADR-012 (permission'lar **tüketilir**) |
| Ham içerik byte **sunumu** (recording stream / transcript view) | SAD §10.2 + panel L2 **A-11/A-12/A-13** (karar verilir, içerik **akmaz**) |
| Residency depolama **uygulaması** | DB §8 / SAD §12.1 (residency **kararı** verilir) |

## Notlar

- **Vendor-neutral** (ADR-001/002/011/012/013); audit sink + RBAC + break-glass router bağımsız; karar her
  zaman **backend'de** (ADR-012).
- **Sır/credential ve ham içerik** (kayıt byte/ses, transkript metni, telefon/kart/OTP/ad/adres/hesap no
  **değeri**) **repoya yazılmaz** — audit **içeriği değil ERİŞİMİ** kaydeder (yalnız kim/ne/ne zaman/sonuç +
  hash zinciri). Canlı erişim yalnız `${ACCESS_AUDIT_URL}`.
- İskelet kapısı; canlı **`audit_log`** (DB §27 WORM partition + hash chain depolama) + **IAM** (RBAC
  permission + break-glass router FR-IAM-009) + **panel L2** içerik sunumu + residency (DB §8) entegrasyonu
  F1'de dolar.
- SRS/RTM/BRD/SAD **değişmedi** — RTM zaten `FR-REC-009 → SR-REC-009 → TC-REC-009 (A) → 11.6` ve
  `FR-REC-008 → SR-REC-008 → TC-REC-008 → 11.6` eşler; yeni FR/SR **eklenmedi**.
