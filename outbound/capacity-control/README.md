# 10.2.4 — Silent/abandoned call önleme (kapasite kontrolü)

**WBS:** 10.2.4 · **Faz:** F2 · **Öncelik:** Must · **İz:** →FR-TEL-015 · BRD §14.3 · BRD §15 ·
SAD §19.1 · SR-TEL-015 · TC-TEL-015

Outbound çağrı **başlatılmadan önce** zorunlu **kapasite/silent-call kararı**: bir contact'a dial
başlatmanın, çağrı cevaplanırsa müşteriyi **sessizlikle (silent/abandoned call)** karşılamayacağını
garanti edip etmediğine **dört konjonktif kuralda** karar verir — **rezerve headroom ∧ abandoned oranı
∧ over-dial cap ∧ trunk kanalı**. Deterministik, **fail-closed / all-pass** bir motordur: **kapasite
olmadan bir çağrı ASLA başlatılmaz** (SR-TEL-015 çekirdek; kapasite kontrolü atlanamaz = BRD §15 kritik
"silent call oluşması" alarmı). 10.2.1 Consent + 10.2.2 DNC + 10.2.3 arama saati modüllerinin
**kardeşidir** ve onlarla AND'lenir: `eligible = consent_ok AND dnc_ok AND hours_ok AND capacity_ok`.

```
CapacityCheckRequest ──kapasite profili çöz (threshold,overdial,reserve)──► kapasite durumu hesapla
      │                          │                                                   │
      │            free = total − active; over-dial in_flight'i sayar (K2)   reserve ∧ abandon ∧ overdial ∧ trunk
      │                          │                                                   │
      │           ├─ profil çözülemez ──────────────► BLOCK (unknown_profile, fail-closed)
      │           └─ all-pass ─────────────────────────────────────────────► ALLOW
      │           └─ any-fail ─────────────────────────────────────────────► BLOCK (block_reason)
```

## Dört kural (SR-TEL-015 / BRD §14.3)

| Kural | Alan | Invariant | BLOCK nedeni |
|---|---|---|---|
| **rezerve headroom** (boşta handler ≥ reserve_min) | `free_handlers = total_handlers − active_calls` | K3 | `no_capacity` |
| **abandoned oranı** (< silent_call_threshold) | `rolling_abandoned/rolling_connected` (veya `predicted_abandon_rate`) | K4 | `abandon_rate_exceeded` |
| **over-dial cap** (predictive pacing) | `in_flight_dials + 1 ≤ free × max_overdial_ratio` | K5 | `overdial_cap` |
| **trunk kanalı** (boş giden kanal) | `trunk_channels_active + 1 ≤ trunk_capacity` | K6 | `trunk_exhausted` |

**Konjonktif (all-pass):** ALLOW yalnız **dört kural da** geçerse; herhangi biri ihlal ederse BLOCK.
`block_precedence` yalnız hangi `block_reason`'ın raporlanacağını belirler (unknown_profile →
abandon_rate_exceeded → no_capacity → overdial_cap → trunk_exhausted). Profil çözülemezse **fail-closed**
`BLOCK unknown_profile` (K7).

## İki çekirdek invariant

- **K2 — doğru kapasite muhasebesi (FR-TEL-015):** meşgul handler free'den düşülür (`free = total −
  active`) **ve** in_flight dial'lar over-dial bound'una sayılır; bunları atlamak / eski (stale) snapshot
  kullanmak = under-reserve / over-dial = silent call (`capacity_error`).
- **K8 — %100 / ATLANAMAZ (SR-TEL-015):** kapasite olmadan bir çağrı başlatılmaz; bypass =
  `capacity_skip` = BRD §15 kritik "silent call oluşması" alarmı (≤2dk). Sıfır kapasiteye çevirme
  (`no_capacity_leak`) de aynı alarmı tetikler.

## Kapasite profilleri (`config/capacity-policies.json`)

`PROFILE-TR` (threshold 0.03, over-dial 3.0, reserve 1) · `PROFILE-UK` (**Ofcom** — abandoned ≤%3 +
sıkı pacing 2.5) · `PROFILE-EU` (daha sıkı 0.02 / 2.0) · illüstratif `PROFILE-US-CALL` (TCPA demo 0.03).
Eşikler DPIA §5.3 `cp.outbound.silent_call_threshold` türevi, **mühendislik varsayılanı**, counsel
doğrulamasına tabi. Canlı kapasite **snapshot** (handler/trunk/rolling sayımlar) runtime telemetri
(0.4.7/0.4.8) tarafından sağlanır; config yalnız **eşikleri** taşır.

## Komutlar

```bash
python3 capacity_control_probe.py validate          # statik spec/config/kapsama → çıkış kodu
python3 capacity_control_probe.py check samples      # senaryolar (12 pass + 9 degrade) → kapı
python3 capacity_control_probe.py selftest           # gömülü invariant kontrolleri (K1–K12)
python3 capacity_control_probe.py schema             # karar sözleşmesini yazdır
bash run_live_test.sh                                # tümünü çalıştır (sunucusuz iskelet kapısı)
```

Sonuçlar: **validate 73/73** · **selftest 57/57** · **check 21/21** (12 pass + 9 degrade) ·
**behavior 43/43** 🟢.

## İnvariant'lar (HARD kapı; 0-ihlal)

`K1` determinizm/terminal · **`K2` doğru kapasite muhasebesi (çekirdek; capacity_error=0)** · `K3`
rezerve headroom (no_capacity_leak=0 = silent call) · `K4` abandoned oranı eşiği · `K5` over-dial cap ·
`K6` trunk kanalı · `K7` fail-closed bilinmeyen profil · **`K8` %100/ATLANAMAZ (çekirdek;
capacity_skip=0 = BRD §15 silent call alarmı)** · `K9` kanıt · `K10` audit · `K11` kardinalite/PII ·
`K12` tenant izolasyonu + sır/PII.

## Kapsam ve sınırlar

**Sahiplenir:** FR-TEL-015 **kapasite/silent-call** boyutu (dört-kuralli fail-closed all-pass per-dial
karar + audit; rezerve headroom → abandoned oranı → over-dial → trunk).
**Tüketilir (consumed_by):** **10.2.1 Consent + 10.2.2 DNC + 10.2.3 arama saati** — `capacity_ok`
(ALLOW) sonucu `consent_ok` + `dnc_ok` + `hours_ok` ile AND'lenir; **10.2.6 kampanya kapasitesi ≤
agent+trunk + backpressure** — bu modülün BLOCK çıktısı kampanya-düzeyi pace-down/backpressure girdisi;
dialer (10.1.x); **2.1.8 retry/geri-arama** — `no_capacity`/`overdial_cap` BLOCK sonucu çağrıyı
callback'e/pace-down'a alır.

**Kapsam dışı (bilinçli, başka modül sahibi):** arama öncesi **consent** → **10.2.1** (FR-OUT-003;
AND'lenir); DNC/suppression → **10.2.2** (FR-TEL-014; AND'lenir); arama saati → **10.2.3** (FR-TEL-013;
AND'lenir); **kampanya-düzeyi kapasite ≤ agent+trunk + backpressure entegrasyonu** → **10.2.6**
(FR-OUT-007; bu modül per-dial kapı, BLOCK pace girdisi); admission/graceful degradation → FR-RES-014 +
0.4.8 (sistem-düzeyi); **AMD** (insan/makine) → FR-TEL-010; voicemail → FR-TEL-011; retry/callback →
2.1.8 (karar döndürür, zamanlamaz); kampanya durdurma → 10.1.7; profile **çözümleme**
(most-restrictive-wins) → DPIA §5/SAD §19.3 (değerleri tüketir); kapasite **snapshot** → runtime
telemetri 0.4.7/0.4.8 (okur, üretmez); audit store → 7.1.6/12.x; panel UI → L2 A-10.

Vendor-neutral (ADR-001/002/012): kapasite snapshot kaynağı sağlayıcı bağımsız; aynı karar sözleşmesi
arkasına gerçek runtime telemetri. Deterministik (sanal snapshot + tamsayı/oran muhasebesi; Date.now/
random yok), stdlib-only, credential-free. Sır/credential ve gerçek PII (müşteri adı/telefon/ham numara)
repoya yazılmaz — yalnız yapısal kimlik + enum (country/campaign_category) + kapasite sayısı + oran +
bayrak (FR-TST-008 sentetik).
