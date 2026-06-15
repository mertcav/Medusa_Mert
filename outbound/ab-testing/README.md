# `outbound/ab-testing/` — WBS 10.1.8 A/B test kampanyaları

10. workstream'in (Outbound) Kampanya Yönetimi alt-bloğunun **A/B test** modülü ·
**F2 · Should** · →**FR-OUT-012** · SR-OUT-012 (yöntem **T**) · TC-OUT-012.

Bir kampanyaya **≥2 varyant** (A/B/C...) tanımlayan, her varyantı bir **script/teklif versiyonuna**
(FR-OUT-009) bağlayan ve her contact'ı **deterministik + sticky** olarak ağırlıklara göre bir varyanta
**dağıtan** (allocation), ardından disposition-türevli sonuçları **iki-oran z-testi** ile
**karşılaştıran** (comparison) deterministik motor. **Çekirdek kabul ölçütü (SR-OUT-012):** *"Varyant
dağıtımı ve karşılaştırma yapılır"* — dağıtım deterministik+sticky+tolerans içinde (C4), karşılaştırma
kazananı yalnız **yeterli örneklem + istatistiksel anlamlılık** ile beyan eder (C5; aksi `inconclusive`).

## Dosyalar
| Yol | Açıklama |
|-----|----------|
| `ab-testing-spec.json` | Makine-okunur **kaynak doğruluk**: dağıtım, karşılaştırma, uygunluk-koruması, yetki, kapılar, invariant C1–C12, izlenebilirlik |
| `ab-testing.md` | Tasarım dokümanı (sticky hash dağıtım, z-test karşılaştırma, uygunluk koruması, kapsam ayrımı) |
| `ab_testing_probe.py` | Stdlib-only **deterministik A/B motoru**: `validate`/`run`/`selftest`/`schema` |
| `config/ab-testing-policies.json` | Dağıtım yöntemi + ağırlık + z-test parametreleri + yetkili roller (credential-free) |
| `samples/*.json` | 9 pass + 8 degrade senaryo (sentetik, FR-TST-008) |
| `tests/ab_testing_behavior_test.py` | Bağımsız kara-kutu davranış kapısı (C1–C12) |
| `run_live_test.sh` | Tüm statik + davranış kapılarını koşar |

## Hızlı çalıştırma
```bash
cd outbound/ab-testing
./run_live_test.sh                          # tümü
python3 ab_testing_probe.py validate        # statik kapı
python3 ab_testing_probe.py run samples     # senaryolar
python3 ab_testing_probe.py selftest        # gömülü kontroller
```

## Çekirdek kavramlar
- **Varyant dağıtımı (C4):** `u = hash(experiment_id : contact_key) ∈ [0,1)` (SHA-256, **PII yok**) →
  kümülatif ağırlık kovası → tam bir varyant. **Sticky**: aynı contact tekrar → aynı varyant.
- **Varyant karşılaştırması (C5):** `conversion_rate = conversions/trials`; kontrol (A) vs lider iki-oran
  z-testi. `winner` ancak `trials ≥ min_sample` (100) **ve** `|z| ≥ z(alpha)` (1.96); aksi `inconclusive`.
- **Uygunluk koruması (C8):** A/B yalnız script/teklif seçer; `consent/DNC/saat` uygunluğunu **override
  etmez** — A/B suppression bypass aracı **olamaz**.

## Çekirdek invariant (SR-OUT-012)
**Dağıtım (C4)** deterministik+sticky, gözlenen dağılım ağırlıkları tolerans içinde yansıtır;
**karşılaştırma (C5)** kazananı yalnız örneklem+anlamlılık ile beyan eder (yanlış kazanan = ihlal). Bu
modül atamayı+sonucu **üretir**; gerçek dialer çevirme (10.1.x) varyantın script'iyle çevirir.

## Durum
validate **76/76** 🟢 · selftest **56/56** 🟢 · run **17/17** 🟢 (9 pass + 8 degrade beklendiği gibi
elendi) · behavior **46/46** 🟢. Vendor-neutral (ADR-001/002/012); sır/credential ve müşteri PII
(ad/telefon/hesap no) repoya yazılmaz (C12). Canlı dialer/disposition/audit testi F2'de gerçek
entegrasyon (10.1.x dialer + 10.1.5 disposition + 12.x audit store) ile koşar.

Rapor: [`reports/10.1.8-ab-test-kampanyalari-raporu.md`](../../reports/10.1.8-ab-test-kampanyalari-raporu.md)
