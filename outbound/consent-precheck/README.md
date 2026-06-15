# 10.2.1 — Consent Engine ön-kontrol

**WBS:** 10.2.1 · **Faz:** F2 · **Öncelik:** Must · **İz:** →FR-OUT-003, BRD §14.3, SAD §19.1
· SR-OUT-003 · TC-OUT-003

Outbound çağrı **öncesi** zorunlu **consent kararı**: bir contact'ın aranmaya **consent açısından**
uygun olup olmadığına **altı boyutta** karar verir — **amaç ∧ ülke ∧ birey/şirket ∧ kaynak ∧ tarih ∧
kapsam** (BRD §14.3). Deterministik, **fail-closed / deny-by-default** bir motordur: **geçerli bir rıza
yoksa çağrı BAŞLATILMAZ** (SR-OUT-003 çekirdek; ön-kontrol atlanamaz = BRD §15 kritik alarm).

```
ConsentCheckRequest ──ülke profili çöz──► consent_required = f(consent_model, subject_type, b2b)
      │                                         │
      │                                         ├─ opt_out | B2B-muaf ───────────────► ALLOW (basis)
      │                                         └─ rıza gerekli ─┬─ altı boyut geçer ► ALLOW (explicit/soft)
      │                                                          └─ herhangi boyut X ► BLOCK (block_reason)
      └──(ülke çözülemez / cross-tenant)─────────────────────────────────────────────► BLOCK (fail-closed)
```

## Altı boyut (SR-OUT-003 / BRD §14.3)

| Boyut | Alan | Invariant | BLOCK nedeni |
|---|---|---|---|
| **amaç** | `call_purpose` ∈ `consent.purposes` | K2 | `purpose_mismatch` |
| **ülke** | `country` → `cp.outbound.consent_model` | K3 | `unknown_country` |
| **birey/şirket** | `subject_type` + `b2b_exemption` | K4 | `consent_required_individual` |
| **kaynak** | `consent.source` ∈ `recognized_sources` | K5 | `invalid_source` |
| **tarih** | `granted_at` geçerli + süresi dolmamış | K6 | `expired_or_invalid_date` |
| **kapsam** | `consent.channels` (voice) + `categories` | K7 | `out_of_scope` |

Yokluk/belirsizlik → `no_consent` / fail-closed `BLOCK` (K8). ALLOW dayanağı (`basis`):
`explicit` · `soft_basis` (PECR soft opt-in) · `b2b_exempt` · `opt_out`.

## Consent modelleri (DPIA §5.3 `cp.outbound.consent_model`)

- **opt_in** (TR ETK/İYS): açık olumlu rıza **zorunlu**; yoksa BLOCK.
- **soft_opt_in** (UK PECR): açık rıza **veya** mevcut-müşteri `soft_basis` (kategori eşleşir).
- **opt_out** (illüstratif): önceden rıza **gerekmez**; engelleme yalnız DNC/suppression (10.2.2).

Ülke profilleri `config/consent-precheck-profiles.json` (PROFILE-TR/UK/EU + illüstratif US-OPTOUT);
değerler DPIA §5.3 `cp.outbound.*` türevi, **mühendislik varsayılanı**, counsel doğrulamasına tabi.

## Komutlar

```bash
python3 consent_precheck_probe.py validate          # statik spec/config/kapsama → çıkış kodu
python3 consent_precheck_probe.py check samples      # senaryolar (12 pass + 6 degrade) → kapı
python3 consent_precheck_probe.py selftest           # gömülü invariant kontrolleri (K1–K12)
python3 consent_precheck_probe.py schema             # karar sözleşmesini yazdır
bash run_live_test.sh                                # tümünü çalıştır (sunucusuz iskelet kapısı)
```

Sonuçlar: **validate 77/77** · **selftest 59/59** · **check 18/18** · **behavior 37/37** 🟢.

## İnvariant'lar (HARD kapı; 0-ihlal)

`K1` determinizm/terminal · `K2` amaç · `K3` ülke · `K4` birey/şirket · `K5` kaynak · `K6` tarih ·
`K7` kapsam · **`K8` fail-closed/ATLANAMAZ (çekirdek; consent_skip=0 = BRD §15 alarm)** · `K9` kanıt ·
`K10` audit · `K11` kardinalite/PII · `K12` tenant izolasyonu + sır/PII.

## Kapsam ve sınırlar

**Sahiplenir:** FR-OUT-003 **consent** boyutu (altı boyutlu fail-closed karar + audit).
**Tüketilir (consumed_by):** **10.2.2 DNC/suppression** — `consent_ok` (ALLOW) sonucu DNC kapısıyla
AND'lenir (`eligible = consent_ok AND dnc_ok AND hours_ok`); dialer (10.1.x); 10.1.8 A/B test eligibility.

**Kapsam dışı (bilinçli, başka modül sahibi):** DNC/suppression gerçek zamanlı → **10.2.2**
(FR-TEL-014/FR-OUT-006; birlikte SR-OUT-003 "consent ve suppression"); arama saati → 10.1.4
(FR-OUT-004); max deneme → 10.1.3; Caller ID → FR-TEL-004/005; açılış metni → §14.2; versiyon →
10.1.6; profile **çözümleme** (most-restrictive-wins) → DPIA §5/SAD §19.3 (değerleri tüketir); consent
**kaydı** yönetimi (opt-in toplama, İYS senkron) → `consent:manage` panel (okur, toplamaz); audit store
→ 7.1.6/12.x; dialer çevirme → 10.1.x; panel UI → L2 A-10.

Vendor-neutral (ADR-001/002/012): İYS/TPS registry sağlayıcı bağımsız; aynı karar sözleşmesi arkasına
gerçek adapter. Deterministik (sanal-saat `call_time`; Date.now/random yok), stdlib-only,
credential-free. Sır/credential ve gerçek PII (müşteri adı/telefon/hesap no) repoya yazılmaz —
yalnız yapısal kimlik + enum + göreli ISO tarih + bayrak (FR-TST-008 sentetik).
