# Bağlam paketi (özet + intent + toplanan alanlar + auth durumu) + screen-pop — Tasarım (WBS 9.6)

> 9. workstream'in (İnsan Temsilciye Aktarım) **altıncı** modülü · **F1 · Must** · →**FR-HND-004, FR-HND-005**.
> Kaynak doğruluk: [`context-package-spec.json`](context-package-spec.json). Çelişkide BRD/SAD/SRS esastır.

## 1. Amaç ve konum

Bir çağrı insan temsilciye aktarılırken, temsilcinin müşteriyi **sıfırdan dinlemeye başlaması**
gerekmemelidir. Bu modül, aktarım anında temsilciye gösterilecek **bağlam paketini** derler ve teslim
eder. SAD §7.3 akış diyagramındaki şu noktanın sahibidir:

```
Orchestrator (transfer kararı)
   │ bağlam paketi: özet + intent + toplanan alanlar + auth durumu
   ▼
Handoff Manager ──► hedef seçimi (departman/skill/kuyruk)
```

ve SAD §7.3'ün şu cümlesi:

> Bağlam paketi CC'ye hem ekran-pop (screen-pop) verisi (CTI/CRM üzerinden) hem de transkript özeti
> olarak iletilir (FR-HND-004/005).

Workstream içindeki rol ayrımı:

| Modül | Soru | Sahip |
|-------|------|-------|
| 9.4 | **Ne zaman / neden** aktarılmalı? | transfer-triggers |
| 9.5 | **Nereye** (departman/skill/kuyruk)? | target-selection |
| **9.6** | Temsilciye **ne gösterilecek** (bağlam paketi)? | **bu modül** |
| 9.1/9.2/9.3 | Aktarım **nasıl taşınacak** (cold/warm/whisper)? | mekanizma modülleri (paketi TÜKETİR) |

## 2. Dört zorunlu bileşen (FR-HND-004)

Paket **dört** bileşeni de taşır (P2 `missing_component=0`):

1. **summary** — görüşme özeti (LLM/diyalog özetleme ÜRETİR; bu modül referans token'ı tüketir, ham transkript değil)
2. **intent** — müşteri niyeti (NLU ÜRETİR)
3. **collected_fields** — oturumda toplanan alanlar (slot-filling ÜRETİR) — **FR-HND-005**: bu alanlar
   pakette iletilir, böylece müşteri aynı bilgileri **tekrar vermek zorunda kalmaz**
4. **auth_status** — kimlik doğrulama **durumu** `{level, methods, step_up}` (auth modülü ÜRETİR) —
   temsilci doğrulama seviyesini bilir, gereksiz tekrar doğrulama yapmaz

## 3. Redaction — PII minimizasyonu (P4/P5, FR-AUTH-005)

Bağlam paketi müşteri verisi taşır; bu nedenle teslim **öncesi** iki kural uygulanır:

- **Hassas alan maskeleme (P5):** `sensitive=true` işaretli alanlar (hesap no, kart no, kimlik no)
  screen-pop'a **maskelenmiş** (son-4, ör. `****-4321`) gider; ham tam-değer ekranda **yoktur**.
- **Auth yalnız-statü (P4):** `auth_status` yalnız `level/methods/step_up` taşır. Ham doğrulama sırrı
  (`auth_secret_fields`: OTP kodu / parola / KBA cevabı / tam PAN / CVV / güvenlik cevabı / PIN)
  **pakete girmez**. FR-AUTH-005: "Hassas bilgiler sesli olarak tam biçimde tekrarlanmamalıdır" ilkesi
  ekran teslimine de uygulanır.

## 4. Teslim ve fail-safe (P6/P7/P8)

Paket **yalnız 9.5'in seçtiği hedefe** (`deliver_to = queue`) teslim edilir (P6 `mis_delivery=0`) ve
yalnız **bu tenant'ın** oturumundan kurulup bu tenant'ın hedefine gider (P7 `cross_tenant=0`,
FR-TEN-002). Teslim kanalları:

- **screen_pop** — CTI/CRM ekran-pop (yapısal alanlar)
- **transcript_summary** — transkript özeti
- **whisper** — warm/whisper transferde (9.2/9.3) temsilciye seslendirilen özet

**Fail-safe (P8):** screen-pop kanalı kullanılamazsa (CTI/CRM erişilemez) transfer **düşmez**;
`DEGRADED` durumuna geçilir ve minimal verbal(whisper)/transkript özeti fallback bağlam (özet+intent)
sağlanır. `DEGRADED` bir **ihlal değil** — geçerli bir fail-safe sonuçtur; oturum korunur.

## 5. Durum makinesi

```
ASSEMBLING ──► REDACTING ──► DELIVERING ──(screen-pop var)──► DELIVERED   (terminal)
                                          └─(screen-pop yok)─► DEGRADED    (terminal — fail-safe)
```

- **ASSEMBLING** — dört bileşeni oturum durumundan derle
- **REDACTING** — hassas alanları maskele + auth durumunu yalnız-statüye indirge (ham sır düşürülür)
- **DELIVERING** — hedef temsilciye (screen-pop + transkript özeti) teslim et
- **DELIVERED / DEGRADED** — terminal, IMMUTABLE; her ikisi de paket + audit üretir (P10)

## 6. İnvariant'lar (P1–P12)

| ID | Özet | İz |
|----|------|----|
| P1 | Paket tamlığı/determinizm; terminal'e ulaşır | SR-HND-004 |
| P2 | Dört zorunlu bileşen tam | FR-HND-004 |
| P3 | Toplanan alanlar pakette → tekrar-sormama | FR-HND-005 |
| P4 | Auth yalnız-statü; ham sır pakette yok | FR-AUTH-005/003 |
| P5 | Hassas alan maskeli (son-4) | FR-AUTH-005, BRD §14 |
| P6 | Yalnız 9.5 hedefine teslim | FR-HND-003/004 |
| P7 | Tenant izolasyonu | FR-TEN-002 |
| P8 | Screen-pop yoksa fail-safe verbal/transkript; oturum düşmez | SAD §14 |
| P9 | Her paket kanıt taşır | FR-IAM-006 |
| P10 | Her teslim audit'e yazılır | FR-IAM-006 |
| P11 | Gözlemlenebilirlik kardinalite; PII metrik/log'ta yok | FR-REC-004, 0.4.7 |
| P12 | Spec/config/sample sır/PII tutmaz | BRD §14 |

## 7. Kapsam ayrımı (bilinçli — başka modül sahibi)

- Aktarım **mekanizması** (cold SIP REFER → 9.1; warm köprüleme → 9.2; whisper konferans → 9.3) — bu
  modül paketi **üretir/teslim eder**, taşımayı değil; warm/whisper whisper brifing **metni** 9.2/9.3'te
  seslendirilir (bu modül whisper özet **bileşenini** sağlar)
- Tetikleme kararı → 9.4 · hedef seçimi → 9.5 (`target` TÜKETİLİR) · temsilci-yok fallback → 9.7
- Raporlama → 9.8 · özet **üretimi** → LLM özetleme (3.x/6.x) · intent **üretimi** → NLU (3.x)
- Alan toplama (slot-filling) → diyalog (3.x) · **kimlik doğrulama yürütme** (OTP/KBA/step-up) → auth
  modülü (FR-AUTH; bu modül auth **durumunu** tüketir, doğrulamayı yapmaz)
- Gerçek CTI/CRM screen-pop kanal entegrasyonu → CC entegrasyonu (11.x; bu modül teslim **sözleşmesini**
  üretir) · audit store → 7.1.6/12.1.8 · gözlemlenebilirlik omurgası → 0.4.7

## 8. Doğrulama

`./run_live_test.sh` → validate **73/73** 🟢 · selftest **42/42** 🟢 · run **13/13** 🟢
(6 pass + 7 degrade beklendiği gibi elendi) · behavior **27/27** 🟢. Vendor-neutral (ADR-001/002);
sır/credential ve gerçek PII (müşteri adı/telefon/hesap no tam değeri/ham transkript/OTP) tutulmaz (P12).
Canlı screen-pop testi F1/F2'de gerçek CTI/CRM + 9.1/9.2/9.3 ile koşar.
