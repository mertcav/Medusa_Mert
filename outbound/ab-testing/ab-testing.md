# WBS 10.1.8 — A/B Test Kampanyaları (A/B Test Campaigns)

> **Faz:** F2 · **Öncelik:** Should · **İz:** FR-OUT-012 · SR-OUT-012 (yöntem **T**) · TC-OUT-012
> **Kaynak doğruluk:** `ab-testing-spec.json`. Çelişkide BRD/SAD/SRS/DB/API esastır.

## 1. Amaç ve kapsam

FR-OUT-012 ("A/B test kampanyaları desteklenmelidir") ve onun doğrulanabilir karşılığı SR-OUT-012
(yöntem **T — Test**: "A/B test kampanyaları desteklenir"; **kabul ölçütü: "Varyant dağıtımı ve
karşılaştırma yapılır"**) için **varyant dağıtım (allocation)** + **varyant karşılaştırma (comparison)**
motorunu sahipleniriz.

Bir kampanyaya **≥2 varyant** (A/B/C...) tanımlanır; her varyant bir **script/teklif versiyonuna**
(FR-OUT-009) bağlıdır ve bir **ağırlık** (allocation weight) taşır; ağırlıklar `1.0`'a (100%) toplanır.
Modül, API §A-10 `POST /campaigns` (yetki `campaign:manage`) yüzeyinin arkasındaki **deterministik
A/B motorudur**.

**Çekirdek davranış:** Operasyon yöneticisi / conversation_designer (`campaign:manage`) varyant setini
tanımlar → motor **yetkiyi** + **config geçerliliğini** doğrular → uygularsa (1) her contact'ı
**deterministik + sticky** hash ile ağırlıklara göre **tam bir varyanta dağıtır** → (2) disposition-
türevli outcomes'tan varyant başına dönüşümü hesaplar ve **iki-oran z-testi** ile **karşılaştırır**
(kazanan yalnız yeterli örneklem + anlamlılık ile beyan; aksi `inconclusive`) → terminal sonuç üretir.

## 2. Terminal sonuçlar

```
  ABExperimentRequest ──yetki(campaign:manage) + geçerli config──► APPLIED
       │                                                            ├─ allocation: her contact → varyant (C4)
       │                                                            └─ comparison: z-test → winner|inconclusive (C5)
       └──(yetkisiz / geçersiz config / cross-tenant)────────────► DENIED  (işlem yok — doğru reddetme, C2/C3/C7)
```

İki terminal sonuç da **geçerlidir**. `DENIED` ihlal değil, doğru reddetmedir (örn. yetkisiz aktör veya
tek varyant). Karşılaştırma **verdict**'i (`winner` | `inconclusive` | `not_evaluated`) `APPLIED` içinde
bir alandır, ayrı terminal değildir.

## 3. Varyant dağıtımı — SR-OUT-012 çekirdek (1/2)

Her contact, **deterministik sticky hash** ile dağıtılır:

- `u = hash(experiment_id : contact_key) ∈ [0,1)` (hashlib/SHA-256; **Date.now / gerçek-rastgele YOK**).
- Kümülatif ağırlık kovalarına göre **tam bir varyanta** düşer (50/50, 70/30, A/B/C ...).
- **Sticky:** aynı `(experiment_id, contact_key)` → her zaman aynı varyant (tekrar atama / churn yok).
- Gözlenen dağılım, yapılandırılan ağırlıkları **`weight_tolerance` (varsayılan 0.10)** içinde yansıtır;
  tolerans yalnız yeterli örneklemde (`≥50` contact) uygulanır (küçük N'de doğal sapma beklenir).
- Hash girdisi **yalnız yapısal kimlik** (`experiment_id` + `contact_key`) — **PII hash'lenmez**.

Bir contact **tanımsız** varyanta düşerse / `0` veya `>1` varyanta düşerse / tekrar **farklı** varyanta
düşerse → **C4 `misallocation` ihlali**.

## 4. Varyant karşılaştırması — SR-OUT-012 çekirdek (2/2)

disposition-türevli per-variant `outcomes {trials, conversions}` (10.1.5 üretir) → varyant başına
`conversion_rate = conversions / trials`:

- **Kontrol** varyantı = ilk varyant (A). Lider (en yüksek oran) kontrole karşı **iki-oran z-testi**
  (havuzlanmış, deterministik `math.erfc`) ile karşılaştırılır.
- **`winner`** yalnız (a) karşılaştırılan varyantların `trials ≥ min_sample` (varsayılan 100) **VE**
  (b) `|z| ≥ z(alpha)` (varsayılan `alpha=0.05` → `1.96`) ise beyan edilir.
- Aksi halde **`inconclusive`** — **yanlış kazanan beyan edilmez**. `outcomes` yoksa `not_evaluated`.

Anlamsız / yetersiz örneklemde kazanan beyan edilirse → **C5 `false_winner` ihlali**. Bu kapı, küçük
örneklemde gürültüyü "kazanan" sanmaya karşı **istatistiksel koruma**dır.

## 5. Uygunluk koruması (C8) — A/B suppression bypass aracı OLAMAZ

A/B deneyi **yalnızca** hangi script/teklif **varyantının** kullanılacağını seçer; bir contact'ın
**aranmaya uygun** olup olmadığını (`consent_ok ∧ dnc_ok ∧ hours_ok` — FR-OUT-003/006/004, 10.2/§19.1
**ön-kontrol sonucu**) **DEĞİŞTİRMEZ**. Uygun-olmayan contact deneye dahil edilse bile dialer onu
aramaz; A/B atama uygunluğu **override edemez**. Uygunsuz contact A/B atamasıyla "aranabilir" yapılırsa
→ **C8 `eligibility_bypass` ihlali**. Bu modül uygunluğu yeniden **hesaplamaz** — ön-kontrol sonucunu
**tüketir ve korur**.

## 6. Yetkilendirme (FR-IAM-011 / ADR-012)

A/B config/start `campaign:manage` yetkisi ister; yetki kararı **her zaman backend'de**. Yetkili roller
(immutable bundle): `operations_manager`, `conversation_designer` (script/teklif varyantını tasarlar),
`tenant_admin`, `tenant_owner`. Yetkisiz aktör (örn. `human_agent`, `qa_analyst`) → `DENIED`
(işlem yok). Yetkisiz config'in uygulanması **C2 `unauthorized` ihlali**.

## 7. Invariant'lar (C1–C12) ve HARD kapılar

| ID | Invariant | Sayaç (kapı eşiği = 0) |
|----|-----------|------------------------|
| C1 | Determinizm/tamlık — terminal {APPLIED\|DENIED}'e ulaşır | `stuck_state` |
| C2 | Yetki — yalnız `campaign:manage` (FR-IAM-011) | `unauthorized` |
| C3 | Config geçerliliği — ≥2 varyant, ağırlık Σ=1.0, benzersiz id, script_version | `invalid_config` |
| **C4** | **Varyant dağıtımı (SR-OUT-012 ÇEKİRDEK 1/2)** — deterministik+sticky, tolerans | `misallocation` |
| **C5** | **Varyant karşılaştırması (SR-OUT-012 ÇEKİRDEK 2/2)** — winner ancak anlamlılık+örneklem | `false_winner` |
| C6 | Idempotency — sticky tekrar, churn yok | `not_idempotent` |
| C7 | Tenant izolasyonu (FR-TEN-002) | `cross_tenant` |
| C8 | Uygunluk koruması — consent/DNC/saat atlanmaz (FR-OUT-003/006/004) | `eligibility_bypass` |
| C9 | Kanıt — experiment + variants + allocation + comparison + actor | `missing_evidence` |
| C10 | Audit — her sonuç audit'lenir (FR-IAM-006) | `missing_audit` |
| C11 | Gözlemlenebilirlik kardinalite (0.4.7) | (yapısal) |
| C12 | Sır/PII yok | `secret_or_pii` |

Tüm kapılar **0-ihlal** eşiklidir; `require_terminal` + `require_decision_record` (audit) zorunlu.

## 8. Gözlemlenebilirlik (0.4.7 hizalı)

`ab_experiment_total{tenant,result}` · `ab_variant_allocation_total{tenant,variant}` ·
`ab_comparison_verdict_total{tenant,verdict}` · `ab_experiment_denied_total{tenant,reason}` ·
`ab_eligibility_bypass_total` (C8 ihlal alarmı — **0 olmalı**).

`variant/verdict/result/reason` **düşük** kardinalite (label uygun); `experiment_id`/`contact_key`/
`campaign_id`/`correlation_id` **yüksek** kardinalite → yalnız trace/exemplar. Müşteri PII metrikte
**ve** log'da yok (FR-REC-004). `eligibility_bypass>0` → alarm **≤2 dk** (SAD §17.2, NFR 10.1).

## 9. Kapsam ayrımı (bilinçli — başka modül sahibi)

kampanya oluşturma → 10.1.1 · CRM liste → 10.1.2 · consent/suppression **ön-kontrol** → 10.2/§19.1
(sonucu **tüketir**) · arama saatleri → 10.1.4 · max deneme → 10.1.3 · disposition **üretimi** → 10.1.5
(outcomes'ı **tüketir**) · script/teklif versiyon **deposu** → 10.1.6 (variant→version **bağlar**) ·
durdurma → 10.1.7 · dialer **çevirme**/zamanlama → 10.1.x (variant **atar**, çevirmez) · audit **store**
→ 7.1.6/12.1.8 · rapor render → A-14/FR-ANA-* · panel UI render → L2 A-10 · gözlemlenebilirlik → 0.4.7.

## 10. Determinizm, vendor-neutrality, gizlilik

hashlib tabanlı sticky atama + `math.erfc` z-test; `Date.now`/gerçek-rastgele yok → **aynı girdi aynı
çıktı**. Stdlib-only. Vendor-neutral (ADR-001/002/012): varyant atama + karşılaştırma sözleşmesi
sağlayıcı bağımsız; canlı entegrasyonda (10.1.x dialer) aynı sözleşme arkasına gerçek dialer. Sır/
credential ve gerçek PII (müşteri adı/telefon/hesap no/ham transkript/OTP) repoya yazılmaz; varyant
hash girdisi yalnız yapısal kimlik (`experiment_id`+`contact_key`). Fixture sentetik (FR-TST-008).

## 11. Doğrulama durumu

`validate` **76/76** 🟢 · `selftest` **56/56** 🟢 · `run` **17/17** 🟢 (9 pass + 8 degrade beklendiği
gibi elendi) · `behavior` **46/46** 🟢. İskelet kapısı; F2 canlı dialer (10.1.x) + disposition (10.1.5)
+ audit store (12.x) entegrasyonu gerçek telemetri ile doldurur.
