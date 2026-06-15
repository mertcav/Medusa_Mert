# 10.2.3 — Ülke/bölge arama saati kuralları

**WBS:** 10.2.3 · **Faz:** F2 · **Öncelik:** Must · **İz:** →FR-TEL-013, FR-OUT-004 · BRD §14.3 ·
SAD §19.1 · SR-TEL-013 · SR-OUT-004 · TC-TEL-013 · TC-OUT-004

Outbound çağrı **anında** zorunlu **arama saati kararı**: bir contact'ın çağrı anının (`call_time`,
mutlak instant) contact'ın **bölgesine göre yerel saate** çevrilip izin verilen arama saatleri
penceresine düşüp düşmediğine **dört konjonktif kuralda** karar verir — **günlük pencere ∧ haftanın
günü ∧ blackout/tatil ∧ müşteri penceresi**. Deterministik, **fail-closed / all-pass** bir motordur:
**izin verilen saat dışı bir çağrı ASLA başlatılmaz** (SR-TEL-013 çekirdek; arama saati kontrolü
atlanamaz = BRD §15 kritik "arama saati kontrolü atlama" alarmı). 10.2.1 Consent + 10.2.2 DNC
modüllerinin **kardeşidir** ve onlarla AND'lenir: `eligible = consent_ok AND dnc_ok AND hours_ok`.

```
CallingHoursCheckRequest ──ülke/bölge profili çöz (tz,window,weekdays,blackout)──► YEREL saate çevir
      │                          │                                                       │
      │              bölge → utc_offset_minutes (FR-OUT-004)            blackout ∧ weekday ∧ window ∧ müşteri
      │                          │                                                       │
      │           ├─ bölge çözülemez ──────────────► BLOCK (unknown_region, fail-closed) │
      │           └─ all-pass ─────────────────────────────────────────────────────────► ALLOW
      │           └─ any-fail ─────────────────────────────────────────────────────────► BLOCK (block_reason)
```

## Dört kural (SR-TEL-013 / SR-OUT-004 / BRD §14.3)

| Kural | Alan | Invariant | BLOCK nedeni |
|---|---|---|---|
| **günlük pencere** (yerel saat [start,end)) | `allowed_window{start,end}` | K3 | `outside_window` |
| **haftanın günü** | `allowed_weekdays[]` | K4 | `weekday_blocked` |
| **blackout/tatil** | `blackout_dates[]` | K5 | `blackout_date` |
| **müşteri penceresi** (FR-TEL-013 müşteri bazında) | `customer_window{start,end,weekdays}` | K6 | `customer_window` |

**Konjonktif (all-pass):** ALLOW yalnız **dört kural da** geçerse; herhangi biri ihlal ederse BLOCK.
`block_precedence` yalnız hangi `block_reason`'ın raporlanacağını belirler (unknown_region →
blackout_date → weekday_blocked → outside_window → customer_window). Bölge/saat dilimi
çözümlenemezse **fail-closed** `BLOCK unknown_region` (K7).

## İki çekirdek invariant

- **K2 — yerel saat (FR-OUT-004 "ülke ve BÖLGEYE göre"):** değerlendirme **her zaman** contact'ın
  bölgesine göre çözülmüş **yerel** saatinde yapılır (`call_time` → UTC normalize →
  `utc_offset_minutes` uygula); sunucu/UTC saatiyle değerlendirme = `tz_error` ihlali. Aynı mutlak
  an, farklı bölgede (US-NY vs US-CA) **farklı** karara yol açar — bu modülün varlık nedeni.
- **K8 — %100 / ATLANAMAZ (SR-TEL-013):** izinli saat dışı bir çağrı başlatılmaz; bypass =
  `hours_skip` = BRD §15 kritik "arama saati kontrolü atlama" alarmı (≤2dk).

## Ülke/bölge profilleri (`config/calling-hours-policies.json`)

`PROFILE-TR` (UTC+180, 09:00–18:00, Pzt–Cmt, resmî tatil blackout) · `PROFILE-UK` (UTC+0,
08:00–20:00) · `PROFILE-EU` (UTC+60, hafta içi) · illüstratif `PROFILE-US-CALL`
(**`requires_region=true`** → bölge zorunlu; `US-NY`=UTC-300, `US-CA`=UTC-480 → bölge saat dilimini
çözer, FR-OUT-004 kanıtı). IANA/DST çözümlemesi vendor-neutral **tz adapter**'dadır (ADR-002); config
deterministik **fixed-offset** taşır. Değerler DPIA §5.3 `cp.outbound.calling_hours` türevi,
**mühendislik varsayılanı**, counsel doğrulamasına tabi.

## Komutlar

```bash
python3 calling_hours_probe.py validate          # statik spec/config/kapsama → çıkış kodu
python3 calling_hours_probe.py check samples      # senaryolar (12 pass + 9 degrade) → kapı
python3 calling_hours_probe.py selftest           # gömülü invariant kontrolleri (K1–K12)
python3 calling_hours_probe.py schema             # karar sözleşmesini yazdır
bash run_live_test.sh                              # tümünü çalıştır (sunucusuz iskelet kapısı)
```

Sonuçlar: **validate 74/74** · **selftest 60/60** · **check 21/21** (12 pass + 9 degrade) ·
**behavior 43/43** 🟢.

## İnvariant'lar (HARD kapı; 0-ihlal)

`K1` determinizm/terminal · **`K2` yerel saat (çekirdek; tz_error=0 = FR-OUT-004)** · `K3` günlük
pencere · `K4` haftanın günü · `K5` blackout · `K6` müşteri penceresi (FR-TEL-013) · `K7` fail-closed
bilinmeyen bölge · **`K8` %100/ATLANAMAZ (çekirdek; hours_skip=0 = BRD §15 alarm)** · `K9` kanıt ·
`K10` audit · `K11` kardinalite/PII · `K12` tenant izolasyonu + sır/PII.

## Kapsam ve sınırlar

**Sahiplenir:** FR-TEL-013 + FR-OUT-004 **arama saati** boyutu (dört-kuralli fail-closed all-pass
yerel-saat karar + audit; bölge → saat dilimi → yerel saat).
**Tüketilir (consumed_by):** **10.2.1 Consent + 10.2.2 DNC** — `hours_ok` (ALLOW) sonucu `consent_ok`
+ `dnc_ok` ile AND'lenir; dialer (10.1.x); **2.1.8 retry/geri-arama** — `outside_window`/`weekday_blocked`
BLOCK sonucu çağrıyı `calling_hours` penceresine yeniden zamanlamayı tetikler; 10.1.8 A/B test eligibility.

**Kapsam dışı (bilinçli, başka modül sahibi):** arama öncesi **consent** kararı → **10.2.1**
(FR-OUT-003; AND'lenir); DNC/suppression → **10.2.2** (FR-TEL-014; AND'lenir); max deneme → 10.1.3;
Caller ID → FR-TEL-004/005; açılış metni → §14.2; versiyon → 10.1.6; kapasite/abandoned → 10.2.4
(FR-TEL-015); profile **çözümleme** (most-restrictive-wins) → DPIA §5/SAD §19.3 (değerleri tüketir);
**IANA/DST** çözümleme → vendor-neutral tz adapter (ADR-002; çözülmüş `utc_offset_minutes`'i tüketir);
contact **region/timezone kaydı** → DB §5.4 (okur, yazmaz); audit store → 7.1.6/12.x; dialer çevirme
ve **yeniden zamanlama** → 10.1.x + 2.1.8 (karar döndürür, çevirmez/ileri-sarmaz); panel UI → L2 A-10.

Vendor-neutral (ADR-001/002/012): saat dilimi/DST çözümleme sağlayıcı bağımsız; aynı karar sözleşmesi
arkasına gerçek tz adapter. Deterministik (sanal-saat `call_time` + fixed-offset; Date.now/random yok),
stdlib-only, credential-free. Sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya
yazılmaz — yalnız yapısal kimlik + enum (country/region) + göreli ISO tarih-saat + saat penceresi
(HH:MM) + offset/weekday sayısı + bayrak (FR-TST-008 sentetik).
