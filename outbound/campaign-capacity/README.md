# 10.2.6 — Kampanya kapasitesi ≤ agent+trunk kapasitesi (backpressure entegrasyonu)

**WBS:** 10.2.6 · **Faz:** F2 · **Öncelik:** Must · **İz:** →FR-OUT-007 · SR-OUT-007 · TC-OUT-007 ·
FR-RES-014/SR-RES-014 · BRD §9.13 · BRD §10.3 · SAD §15.2 (Resource Manager) · SAD §16 · SAD §20 (Little)

Bir outbound **kampanyanın** hız/eş zamanlılık planının (target_concurrency veya target_cps × tutma)
mevcut **agent (AI worker/handler) + trunk kanalı + tenant kota** kapasitesini **aşmadığını** garanti
eden, aşarsa **çökme yerine kontrollü degrade** (backpressure, FR-RES-014) eden **kampanya-düzeyi
admission + sizing** motoru. Deterministik, **fail-closed / no-oversubscription**: kampanya kapasiteyi
**ASLA aşmaz** (FR-OUT-007 çekirdek); kapasite üstü yük **muhasebeli** olarak callback'e alınır
(graceful, FR-RES-014). 10.2.4 **per-dial** silent-call kapısının **kampanya-düzeyi tamamlayıcısıdır**
(10.2.4'ün BLOCK çıktısı bu modülün pace-down girdisidir).

```
CampaignCapacityRequest ──politika çöz (util_threshold)──► ceiling ──► design (Little) ──► admission
      │                          │                            │              │                │
      │   ceiling = ⌊min(agent_avail, trunk_avail, quota_avail) × util⌋   design = max(conc, ⌈cps×hold⌉)
      │                          │                            │              │                │
      │           ├─ profil çözülemez ──────────────────────────────────► BLOCK (unknown_profile)
      │           ├─ cross-tenant ─────────────────────────────────────► BLOCK (cross_tenant)
      │           ├─ design ≤ ceiling ──────────────────► ADMIT      (effective=design, overflow=0)
      │           ├─ ceiling > 0 ──────────────────────► PACE_DOWN  (effective=ceiling, overflow→callback)
      │           └─ ceiling ≤ 0 ──────────────────────► DEFER      (effective=0, overflow→callback)
```

## Kapasite tavanı (ceiling) ve sizing (design)

```
agent_avail = agent_handlers_total − agent_handlers_active − reserved_inbound_handlers   (K6 rezerve)
trunk_avail = trunk_channels_total − trunk_channels_active
quota_avail = tenant_quota_concurrency − tenant_concurrency_active
ceiling     = max(0, ⌊min(agent_avail, trunk_avail, quota_avail) × util_threshold⌋)      (K2 çekirdek)
design      = max(target_concurrency, ⌈target_cps × mean_call_seconds⌉)                   (K3 Little; SAD §20)
```

- **`util_threshold` < 1.0** = backpressure headroom: admission kapasite **%100'e dolmadan** PACE_DOWN'a
  geçer (FR-RES-014 graceful; 0.4.8 `backpressure_graceful` util<1.0 semantiğiyle hizalı).
- **Üç bileşenin minimumu** = en kısıtlayıcı kaynak (agent **veya** trunk **veya** kota).
- **Little yasası** (SAD §20): kararlı durumda eş zamanlılık = CPS × tutma süresi.

## Dört terminal sonuç

| Sonuç | Koşul | effective | overflow |
|---|---|---|---|
| **ADMIT** | design ≤ ceiling | design | 0 |
| **PACE_DOWN** (backpressure) | design > ceiling ∧ ceiling > 0 | ceiling | design − ceiling → callback |
| **DEFER** (backpressure) | ceiling ≤ 0 | 0 | design → callback |
| **BLOCK** (fail-closed) | profil çözülemez / cross-tenant | — | — |

PACE_DOWN/DEFER **ihlal değildir** — FR-RES-014 graceful degrade'in doğru sonucudur (çökme yerine
kontrollü sınırlama; overflow **sessizce düşürülmez**, callback kuyruğuna muhasebelenir).

## Beş çekirdek invariant (FR-OUT-007 + FR-RES-014)

- **K2 — doğru kapasite tavanı (FR-OUT-007):** ceiling üç bileşenin (agent ∧ trunk ∧ kota) minimumu ×
  util_threshold; bir bileşeni atlamak = yanlış (yüksek) tavan = over-subscription (`capacity_error`).
- **K3 — Little sizing (SAD §20):** design = max(conc, ⌈cps×hold⌉); CPS/tutma atlamak = under-size = gizli
  over-subscription (`sizing_error`).
- **K4 — no over-subscription (FR-OUT-007 çekirdek):** effective ≤ ceiling **HER ZAMAN**; aşmak = kapasite
  üstü çağrı = silent/dropped call (`over_subscription` = BRD §15 alarm).
- **K5 — graceful backpressure (FR-RES-014):** overflow = design − effective **muhasebelenir** ve callback'e
  alınır; sessiz düşüş/çökme = `backpressure_fail`.
- **K6 — rezerve inbound korunur:** agent_avail'den reserved_inbound_handlers düşülür (inbound aç bırakılmaz).

## Kapasite profilleri (`config/campaign-capacity-policies.json`)

`PROFILE-TR` (util 0.8) · `PROFILE-UK` (util 0.75 — Ofcom sıkı pacing tamponu) · `PROFILE-EU` (util 0.7) ·
illüstratif `PROFILE-US-CALL` (util 0.8). `util_threshold` + `overflow_policy=callback_queue` taşır.
Değerler **mühendislik varsayılanı**, pilot tenant + runtime telemetri (F2) ile kalibre edilir. Canlı
kapasite **snapshot** (agent/trunk/quota/concurrency + reserved_inbound) runtime telemetri (0.4.7)
tarafından, tenant kota (`tenant_quota_concurrency`) Quota Service (FR-TEN-004) tarafından sağlanır.

## Komutlar

```bash
python3 campaign_capacity_probe.py validate          # statik spec/config/kapsama → çıkış kodu
python3 campaign_capacity_probe.py check samples      # senaryolar (12 pass + 10 degrade) → kapı
python3 campaign_capacity_probe.py selftest           # gömülü invariant kontrolleri (K1–K12)
python3 campaign_capacity_probe.py schema             # karar sözleşmesini yazdır
bash run_live_test.sh                                # tümünü çalıştır (sunucusuz iskelet kapısı)
```

Sonuçlar: **validate 75/75** · **selftest 75/75** · **check 22/22** (12 pass + 10 degrade) ·
**behavior 54/54** 🟢.

## İnvariant'lar (HARD kapı; 0-ihlal)

`K1` determinizm/terminal · **`K2` doğru kapasite tavanı (çekirdek; capacity_error=0)** · **`K3` Little
sizing (çekirdek; sizing_error=0)** · **`K4` no over-subscription (çekirdek; over_subscription=0 =
FR-OUT-007)** · **`K5` graceful backpressure (çekirdek; backpressure_fail=0 = FR-RES-014)** · `K6` rezerve
inbound (reserve_violation=0) · `K7` fail-closed bilinmeyen profil · **`K8` %100/ATLANAMAZ (capacity_skip=0
= BRD §15 'kapasite aşımı' alarmı)** · `K9` kanıt · `K10` audit · `K11` kardinalite/PII · `K12` tenant
izolasyonu + sır/PII.

## Kapsam ve sınırlar

**Sahiplenir:** FR-OUT-007/SR-OUT-007 + FR-RES-014/SR-RES-014 **kampanya-düzeyi** boyutu (kapasite tavanı
hesabı + Little-sizing + admission kararı {ADMIT|PACE_DOWN|DEFER|BLOCK} + effective ≤ ceiling garantisi +
overflow muhasebeli graceful degrade + audit).

**Tüketir (consumes):** runtime kapasite **snapshot** (agent/trunk/quota/concurrency + reserved_inbound) →
0.4.7; **Little/admission/worker_capacity modeli** → 0.4.8; tenant **kota** → FR-TEN-004/Quota Service;
10.2.4 per-dial **BLOCK** pace-down sinyali; kampanya **hız planı** → 10.1.1.

**Tüketilir (consumed_by):** **10.1.x dialer** — ADMIT tam hız / PACE_DOWN düşük hız / DEFER çevirmez;
**2.1.8 retry/callback** — overflow callback kuyruğuna; **10.2.4** — kampanya-düzeyi effective hız per-dial
kapının üst sınırı; **SAD §15.2 Backpressure Ctrl** — admission kararını runtime mekaniğine; **0.4.7** —
metrikler (over_subscription/backpressure alarmı).

**Kapsam dışı (bilinçli, başka modül sahibi):** **per-dial** silent/abandoned call kapısı → **10.2.4**
(FR-TEL-015; BLOCK pace girdisi); consent → 10.2.1; DNC → 10.2.2; arama saati → 10.2.3; **sistem-düzeyi**
yük/kapasite simülasyonu (Little/Poisson/autoscale yük testi) → **0.4.8** (modelini tüketir, yeniden
ölçmez); autoscale/warm pool **gerçek** uygulama → SAD §15.2 Autoscaler (FR-RES-013); admission **runtime**
kuyruk/red mekaniği → SAD §15.2 Backpressure Ctrl; kapasite **snapshot** → runtime telemetri 0.4.7 (okur,
üretmez); tenant kota **tanımı** → FR-TEN-004/Quota Service (değeri tüketir); retry/callback **zamanlama**
→ 2.1.8 (karar döndürür, zamanlamaz); kampanya durdurma → 10.1.7; profile **çözümleme** →
DPIA §5/SAD §19.3; audit store → 7.1.6/12.x; panel UI → L2 A-10.

Vendor-neutral (ADR-001/002/012): kapasite snapshot + trunk kaynağı sağlayıcı bağımsız; aynı karar
sözleşmesi arkasına gerçek runtime telemetri + Resource Manager. Deterministik (sanal snapshot +
tamsayı/oran muhasebesi + Little tamsayı tavan-bölme; Date.now/random yok), stdlib-only, credential-free.
Sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) repoya yazılmaz — yalnız yapısal kimlik +
enum (country/campaign_category) + kapasite sayısı + oran (util_threshold) + süre (mean_call_seconds) +
bayrak (FR-TST-008 sentetik).
