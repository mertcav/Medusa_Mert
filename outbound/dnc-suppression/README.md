# 10.2.2 — Do-not-call / suppression gerçek zamanlı kontrol

**WBS:** 10.2.2 · **Faz:** F2 · **Öncelik:** Must · **İz:** →FR-TEL-014, FR-OUT-006 · BRD §14.3 ·
SAD §19.1 · SR-TEL-014 · SR-OUT-006 · TC-TEL-014 · TC-OUT-006

Outbound çağrı **anında** zorunlu **suppression/DNC kararı**: bir contact'ın herhangi bir bastırma
(suppression) listesine düşüp düşmediğine **beş kaynakta gerçek zamanlı** karar verir — **opt-out ∨
ulusal registry ∨ tenant DNC ∨ kampanya suppression ∨ global suppression**. Deterministik,
**fail-closed / any-hit** bir motordur: **bastırılmış bir numara ASLA çevrilmez** (%100 bloklama,
SR-TEL-014 çekirdek; DNC kontrolü atlanamaz = BRD §15 kritik "suppression atlama" alarmı). 10.2.1
Consent ön-kontrolünün **kardeşidir** ve onunla AND'lenir: `eligible = consent_ok AND dnc_ok AND
hours_ok` (SR-OUT-003 "consent VE suppression" iki kapıdır).

```
SuppressionCheckRequest ──ülke profili çöz (required_sources,registry)──► beş kaynağı değerlendir
      │                                                                          │
      │                                       opt-out ∨ ulusal ∨ tenant ∨ kampanya ∨ global
      │                                                                          │
      │                                       ├─ any-hit ─────────────────────► BLOCK (block_reason)
      │                                       ├─ required unavailable ─────────► BLOCK (registry_unavailable, fail-closed)
      │                                       └─ hiçbiri vurmaz ──────────────► ALLOW (suppress yok)
```

## Beş kaynak (SR-TEL-014 / SR-OUT-006 / BRD §14.3)

| Kaynak | Alan | Invariant | BLOCK nedeni |
|---|---|---|---|
| **opt-out** (FR-OUT-006 anında) | `opt_out{effective_at,scope}` | K2 | `opt_out` |
| **ulusal registry** (İYS/TPS/CTPS) | `national_registry{status}` | K3 | `national_registry` |
| **tenant DNC** | `tenant_dnc` | K4 | `tenant_dnc` |
| **kampanya suppression** | `campaign_suppression` | K5 | `campaign_suppression` |
| **global suppression** | `global_suppression` | K6 | `global_suppression` |

Zorunlu kaynak (`required_sources`) doğrulanamazsa **fail-closed** `BLOCK registry_unavailable` (K7).
**Any-hit:** kaynaklardan **herhangi biri** vurursa BLOCK; `block_precedence` yalnız hangi
`block_reason`'ın raporlanacağını belirler (opt_out → national_registry → registry_unavailable →
tenant_dnc → campaign_suppression → global_suppression).

## İki çekirdek invariant

- **K8 — %100 bloklama / ATLANAMAZ (SR-TEL-014):** bastırılmış numara çevrilmez; bypass = `dnc_skip`
  = BRD §15 kritik "suppression atlama" alarmı (≤2dk).
- **K2 — opt-out ANINDA (FR-OUT-006):** `effective_at ≤ call_time` olan opt-out **propagasyon
  gecikmesi olmadan** bloklar; stale cache / batch propagasyonu = `optout_not_applied` ihlali.

DB §5.4 ile hizalı: opt-out = `consent.state='withdrawn'` (append-only, anında yeni satır) +
`contact.do_not_call=true` (`ix_contact_dnc` partial index); bu modül kaydı **okur**, yazmaz.

## Ülke profilleri (`config/dnc-suppression-policies.json`)

`PROFILE-TR` (registry IYS, national **zorunlu**) · `PROFILE-UK` (TPS_CTPS, **zorunlu**) ·
`PROFILE-EU` (merkezi AB DNC yok → national zorunlu **değil**) · illüstratif `PROFILE-US-DNC`. İç
kaynaklar (opt_out/tenant_dnc/campaign/global) **ülkeden bağımsız her zaman** değerlendirilir;
`required_sources` yalnız dış ulusal registry'nin fail-closed zorunluluğunu belirler. Değerler DPIA
§5.3 `cp.outbound.*` türevi, **mühendislik varsayılanı**, counsel doğrulamasına tabi.

## Komutlar

```bash
python3 dnc_suppression_probe.py validate          # statik spec/config/kapsama → çıkış kodu
python3 dnc_suppression_probe.py check samples      # senaryolar (12 pass + 8 degrade) → kapı
python3 dnc_suppression_probe.py selftest           # gömülü invariant kontrolleri (K1–K12)
python3 dnc_suppression_probe.py schema             # karar sözleşmesini yazdır
bash run_live_test.sh                                # tümünü çalıştır (sunucusuz iskelet kapısı)
```

Sonuçlar: **validate 77/77** · **selftest 61/61** · **check 20/20** · **behavior 39/39** 🟢.

## İnvariant'lar (HARD kapı; 0-ihlal)

`K1` determinizm/terminal · **`K2` opt-out anında (çekirdek; optout_not_applied=0 = FR-OUT-006)** ·
`K3` ulusal registry · `K4` tenant DNC · `K5` kampanya · `K6` global · `K7` fail-closed zorunlu kaynak ·
**`K8` %100 bloklama/ATLANAMAZ (çekirdek; dnc_skip=0 = BRD §15 alarm)** · `K9` kanıt · `K10` audit ·
`K11` kardinalite/PII · `K12` tenant izolasyonu + sır/PII.

## Kapsam ve sınırlar

**Sahiplenir:** FR-TEL-014 + FR-OUT-006 **suppression/DNC** boyutu (beş-kaynaklı fail-closed any-hit
gerçek zamanlı karar + audit; opt-out anında uygulanır).
**Tüketilir (consumed_by):** **10.2.1 Consent ön-kontrol** — `dnc_ok` (ALLOW) sonucu `consent_ok` ile
AND'lenir; dialer (10.1.x); 10.1.8 A/B test eligibility.

**Kapsam dışı (bilinçli, başka modül sahibi):** arama öncesi **consent** kararı (amaç/ülke/birey-şirket/
kaynak/tarih/kapsam) → **10.2.1** (FR-OUT-003; AND'lenir, çözülmez); arama saati → 10.1.4 (FR-OUT-004);
max deneme → 10.1.3; Caller ID → FR-TEL-004/005; açılış metni → §14.2; versiyon → 10.1.6; profile
**çözümleme** (most-restrictive-wins) → DPIA §5/SAD §19.3 (değerleri tüketir); opt-out **kaydı yazımı**
(consent.state=withdrawn / contact.do_not_call=true) → 10.1.5 disposition / `consent:manage` panel
(okur, yazmaz); İYS/TPS registry **senkronu** → registry adapter (ADR-002; tüketir, senkronlamaz);
audit store → 7.1.6/12.x; dialer çevirme → 10.1.x; panel UI → L2 A-10.

Vendor-neutral (ADR-001/002/012): İYS/TPS registry sağlayıcı bağımsız; aynı karar sözleşmesi arkasına
gerçek adapter. Deterministik (sanal-saat `call_time`; Date.now/random yok), stdlib-only,
credential-free. Sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya yazılmaz —
yalnız yapısal kimlik + **opak `suppression_key`** + enum + göreli ISO tarih + bayrak (FR-TST-008
sentetik).
