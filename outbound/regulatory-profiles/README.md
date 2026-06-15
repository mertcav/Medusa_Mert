# 10.2.5 — İYS/ETK (TR) + PECR/Ofcom (UK) profil parametreleri

**WBS:** 10.2.5 · **Faz:** F2 · **Öncelik:** Must · **İz:** →BRD §14.3, SAD §19/§19.3, DPIA §5.3/§6
· FR-OUT-003/004/006 · FR-TEL-013/014/015

BRD §14.3'te **adı geçen iki rejim** için (TR: **İYS** izin kaydı + **ETK**; UK: **PECR** + **Ofcom**)
outbound uyumluluk parametrelerinin **TAM/BİRLEŞİK setinin AUTHORITATIVE TEK kaynağı** + **sürüklenme
(drift) denetçisi**. 10.2.1 consent · 10.2.2 DNC · 10.2.3 arama saati · 10.2.4 kapasite modüllerinin
**TÜKETTİĞİ** `cp.outbound.*` değerlerinin master'ıdır.

```
                          ┌─ named-regime obligations (P2–P8) parametre değerleriyle KARŞILANIR
regulatory-profiles ──────┤      TR: İYS zorunlu (P2) ∧ ETK opt_in + B2B-dahil (P3)
  (master parametre seti) │      UK: PECR soft-opt-in (P4) ∧ TPS-CTPS (P5) ∧ Ofcom ≤%3 (P6) ∧ CLI (P7) ∧ ≤2sn (P8)
        │                 │
        ├─ crosscheck ────┴─ 10.2.1–10.2.4 config değerleri master ile SÜRÜKLENMEZ (P10)
        └─ tenant override ── yalnız-SIKILAŞTIRIR (monotonluk; gevşetme YASAK, P11)
```

> Bu modül **per-call dial kararı VERMEZ** (o 10.2.1–10.2.4'ün işi) ve **profile ÇÖZÜMLEME YAPMAZ**
> (most-restrictive-wins + tenant override uygulama = DPIA §5/SAD §19.3). Çözülecek **DEĞERLERİ** +
> **sıkılaştırma yönünü** + **drift/monotonluk garantisini** sağlar.

## İki rejim katmanı (BRD §14.3)

| Profil | data_protection_regime | marketing_regime | registry | Anahtar yükümlülükler |
|---|---|---|---|---|
| **PROFILE-TR** | KVKK | **ETK** | **İYS** | opt_in (P3) · B2B-dahil/b2b_exemption=false (P3) · İYS gerçek-zamanlı (P2) |
| **PROFILE-UK** | UK_GDPR | **PECR_OFCOM** | **TPS_CTPS** | soft_opt_in + soft_basis (P4) · TPS/CTPS (P5) · abandoned ≤%3 (P6) · CLI (P7) · ≤2sn mesaj (P8) |

`data_protection_regime` (veri koruma) ile `marketing_regime` (ticari ileti) **ayrı katman etiketidir**;
tüketici config'in `regime` alanı ikisinden **biriyle** eşleşmeli (crosscheck regime tutarlılığı). Değerler
DPIA §5.3 `cp.outbound.*` + §6 türevi, **mühendislik varsayılanı**, counsel doğrulamasına tabi.

## Tüketici eşlemesi (crosscheck — P10)

| Tüketici modül | Master'dan tükettiği alanlar |
|---|---|
| 10.2.1 consent | `consent.{consent_model, consent_registry, b2b_exemption, consent_validity_days, recognized_sources}` |
| 10.2.2 dnc | `suppression.{registry, required_sources}` |
| 10.2.3 calling_hours | `calling_hours.{timezone, utc_offset_minutes, allowed_window, allowed_weekdays}` |
| 10.2.4 capacity | `capacity.{silent_call_threshold, max_overdial_ratio, reserve_min}` |

`crosscheck` bu 4 config'in **named-regime (TR/UK)** değerlerini master ile karşılaştırır; eşleşmezse
`drift_detected` (= BRD §15 "uyumluluk parametre sürüklenmesi" kritik alarmı). **28 alan** kontrol edilir.

## Komutlar

```bash
python3 regulatory_profiles_probe.py validate       # statik spec/config/kapsama + crosscheck → çıkış kodu
python3 regulatory_profiles_probe.py check samples   # senaryolar (8 pass + 15 degrade) → kapı
python3 regulatory_profiles_probe.py crosscheck      # tüketici (10.2.1–10.2.4) sürüklenme denetimi (P10)
python3 regulatory_profiles_probe.py selftest        # gömülü invariant kontrolleri (P1–P12)
python3 regulatory_profiles_probe.py schema          # karar/parametre sözleşmesini yazdır
bash run_live_test.sh                                # tümünü çalıştır (sunucusuz iskelet kapısı)
```

Sonuçlar: **validate 81/81** · **selftest 58/58** · **crosscheck 28 alan 🟢** · **check 23/23** ·
**behavior 42/42** 🟢.

## İnvariant'lar (HARD kapı; 0-ihlal)

`P1` determinizm/tamlık · **`P2` İYS zorunlu (TR)** · **`P3` ETK opt_in + B2B-dahil (TR)** ·
**`P4` PECR soft-opt-in (UK)** · **`P5` TPS-CTPS (UK)** · **`P6` Ofcom abandoned ≤%3 (UK)** ·
**`P7` Ofcom CLI (UK)** · **`P8` Ofcom bilgilendirme ≤2sn (UK)** · `P9` düzenleyici köken (provenance) ·
**`P10` tüketici sürüklenmesi yok (crosscheck)** · **`P11` tenant override yalnız-sıkılaştırır** ·
`P12` sır/PII yok + audit + tenant izolasyonu.

## Kapsam ve sınırlar

**Sahiplenir:** BRD §14.3 adı geçen iki rejim parametre seti (TAM `cp.outbound.*` + regime-özgü
obligations + provenance + sıkılaştırma yönü) + tüketici drift denetimi + tenant override monotonluk denetimi.

**Tüketilir (consumed_by):** 10.2.1 consent · 10.2.2 dnc · 10.2.3 calling-hours · 10.2.4 capacity
(her biri master alt-kümesini okur); DPIA §5/SAD §19.3 profile çözümleme (değerleri + yönü tüketir).

**Kapsam dışı (bilinçli, başka modül sahibi):** per-call dial kararı → 10.2.1–10.2.4; profile **çözümleme**
(most-restrictive-wins + tenant override **uygulama**) → DPIA §5/SAD §19.3; İYS/TPS-CTPS gerçek **registry
senkron** → registry adapter (ADR-002); consent **kaydı** → consent:manage panel; residency/KMS → DB.md;
audit store → 7.1.6/12.x; kampanya kapasitesi ≤ agent+trunk → 10.2.6; panel UI → L1 T-06.

Vendor-neutral (ADR-001/002/012): İYS/TPS-CTPS registry + dialer sağlayıcı bağımsız; parametre seti
sağlayıcıdan bağımsız. Deterministik (config çözümü + parametre karşılaştırması; Date.now/random YOK),
stdlib-only, credential-free. Sır/credential ve gerçek PII (müşteri adı/telefon/MSISDN/hesap) repoya
yazılmaz — yalnız yapısal kimlik + enum + oran/saat/sayı + bayrak + düzenleyici köken referansı
(FR-TST-008 sentetik).
