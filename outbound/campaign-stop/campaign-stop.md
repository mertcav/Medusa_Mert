# WBS 10.1.7 — Kampanya Durdurma Düğmesi (Campaign Stop Button)

> **Faz:** F2 · **Öncelik:** Must · **İz:** FR-OUT-010 · SR-OUT-010 (yöntem **D**) · TC-OUT-010
> **Kaynak doğruluk:** `campaign-stop-spec.json`. Çelişkide BRD/SAD/SRS/DB/API esastır.

## 1. Amaç ve kapsam

FR-OUT-010 ("Kampanya durdurma düğmesi bulunmalıdır") ve onun doğrulanabilir karşılığı SR-OUT-010
(yöntem **D — Demonstration**: "Kampanya durdurma düğmesi çağrıları derhal durdurur"; **kabul ölçütü:
"Durdurma sonrası yeni çağrı başlatılmaz"**) için **kampanya kontrol durum makinesini** ve **dialer
admission kapısını** sahipleniriz.

Modül, API §A-10 `POST /campaigns/{id}:stop` (yetki `campaign:manage`, FR-OUT-001/010) kontrol
yüzeyinin arkasındaki **deterministik kontrol motorudur**. `DB.md` `campaign.status` CHECK
(`draft`/`running`/`paused`/`stopped`/`completed`, FR-OUT-010) yaşam döngüsünü uygular.

**Çekirdek davranış:** Operasyon yöneticisi (`campaign:manage`) bir komut verir →
motor **yetkiyi** + **geçiş geçerliliğini** doğrular → uygularsa kampanya durumunu geçirir ve
**dialer admission kapısını** ayarlar (`stop`/`pause`/`complete` → **KAPALI**: yeni çağrı başlatılmaz;
`start`/`resume` → **AÇIK**) → devam eden (in-flight) çağrıları **graceful DRAIN** eder (asla abruptly
düşürmez, SAD §6) → terminal sonuç üretir.

## 2. Kontrol durum makinesi

```
                       command (yetkili campaign:manage + geçerli geçiş)
   (current_status) ───────────────────────────────────────────► APPLIED   (durum geçti + dialer kapısı ayarlandı, C4)
                    ├─(idempotent tekrar — zaten hedef durumda)──► NOOP      (yan-etkisiz, C6)
                    └─(yetkisiz / geçersiz geçiş / cross-tenant)─► DENIED    (durum DEĞİŞMEZ — doğru reddetme, C2/C3/C7)
```

Üç terminal sonuç da **geçerlidir**. `DENIED` ihlal değil, doğru reddetmedir (örn. yetkisiz aktör
veya `stopped`'dan `resume`).

### 2.1 Yaşam döngüsü ve izinli geçişler (`DB.md` `campaign.status` CHECK)

| from | command | to | tür | not |
|------|---------|----|-----|-----|
| draft | start | running | apply | dialing başlar (kapı AÇIK) |
| running | pause | paused | apply | **resumable**, kapı KAPALI |
| paused | resume | running | apply | kapı AÇIK |
| running | **stop** | **stopped** | apply | **FR-OUT-010 düğmesi** — TERMİNAL, kapı KAPALI |
| paused | stop | stopped | apply | TERMİNAL, kapı KAPALI |
| running | complete | completed | apply | doğal bitiş, kapı KAPALI |
| stopped | stop | stopped | **noop** | idempotent (C6) |
| paused | pause | paused | noop | idempotent |
| running | resume / start | running | noop | zaten çalışıyor |

Listelenmeyen `(current, command)` çifti **geçersiz** → `DENIED` (örn. `stopped`+`resume`:
**stop TERMİNAL**, yeniden çalıştırma kampanya klonu gerektirir — C8).

## 3. Dialer admission kapısı (SR-OUT-010 çekirdek)

SR-OUT-010 yöntemi **D**: durdurma sonrası **yeni çağrı başlatılmaz**. Motor bu kabul ölçütünü
`dialer_gate` çıktısı + `new_calls_admitted_after` sayacıyla **doğrulanabilir** kılar:

- `stop`/`pause`/`complete` uygulanınca → `dialer_gate = closed`, `new_calls_admitted_after = 0`.
- `start`/`resume` → `dialer_gate = open` (dialer yeni çağrı admit edebilir).
- Kapı kapalıyken bir yeni çağrı admit edilirse → **C4 `new_call_after_stop` ihlali** → kapı eler.

Bu modül kapıyı **ayarlar**; gerçek dialer çevirme/zamanlama (10.1.x outbound dialer) kapıya **uyar**
(kapalıyken yeni çağrı başlatmaz). Admission, SAD §15 backpressure/admission düzlemiyle aynı kapı
ailesidir (FR-RES-014/FR-OUT-007); bu modül **stop/pause** admission'ını sahiplenir, kapasite-bazlı
rate-limit'i değil.

## 4. In-flight çağrılar — graceful drain (SAD §6 never-drop)

Durdurma yalnız **yeni-çağrı** admission'ını kapatır; devam eden (in-flight) çağrılar abruptly
**düşürülmez** — `drain` ile doğal biter (aktif konuşma tamamlanır). In-flight'ı zorla düşürmek
(`force_drop`) müşteri deneyimini bozar → **C5 `hard_drop_inflight` ihlali**. (Acil/operasyonel
hard-stop ayrı yetki/komut gerektirir; v1 kapsamı dışı.)

## 5. Yetkilendirme (FR-IAM-011 / ADR-012)

Kontrol komutu `campaign:manage` yetkisi ister; yetki kararı **her zaman backend'de**. Yetkili roller
(immutable bundle): `operations_manager` (L2 supervisor seti, SAD §27), `tenant_admin`, `tenant_owner`.
Yetkisiz aktör (örn. `human_agent`, `qa_analyst`) → `DENIED` (durum değişmez). Yetkisiz komutun
uygulanması **C2 `unauthorized` ihlali**.

## 6. Invariant'lar (C1–C12) ve HARD kapılar

| ID | Invariant | Sayaç (kapı eşiği = 0) |
|----|-----------|------------------------|
| C1 | FSM tamlığı/determinizm — terminal {APPLIED\|NOOP\|DENIED}'e ulaşır | `stuck_state` |
| C2 | Yetki — yalnız `campaign:manage` (FR-IAM-011) | `unauthorized` |
| C3 | Geçerli geçiş — `DB.md` status CHECK | `invalid_transition` |
| **C4** | **Durdurma derhal yeni çağrıyı durdurur (SR-OUT-010 ÇEKİRDEK)** | `new_call_after_stop` |
| C5 | In-flight graceful drain (SAD §6) | `hard_drop_inflight` |
| C6 | Idempotency — tekrar = yan-etkisiz NOOP | `not_idempotent` |
| C7 | Tenant izolasyonu (FR-TEN-002) | `cross_tenant` |
| C8 | Stop terminal / pause resumable | (C3 ile zorlanır) |
| C9 | Kanıt — command + from→to + actor + kapı + idempotency | `missing_evidence` |
| C10 | Audit — her sonuç audit'lenir (FR-IAM-006) | `missing_audit` |
| C11 | Gözlemlenebilirlik kardinalite (0.4.7) | (yapısal) |
| C12 | Sır/PII yok | `secret_or_pii` |

Tüm kapılar **0-ihlal** eşiklidir; `require_terminal` + `require_decision_record` (audit) zorunlu.

## 7. Gözlemlenebilirlik (0.4.7 hizalı)

`campaign_control_total{tenant,command,result}` · `campaign_status_gauge{tenant,status}` ·
`campaign_control_denied_total{tenant,reason}` (yetki erken-uyarı) ·
`campaign_new_call_after_stop_total` (SR-OUT-010 ihlal alarmı — **0 olmalı**).

`command/result/status/reason` **düşük** kardinalite (label uygun); `campaign_id`/`call_id`/
`correlation_id`/`actor_id` **yüksek** kardinalite → yalnız trace/exemplar. Müşteri PII metrikte
**ve** log'da yok (FR-REC-004). `new_call_after_stop>0` → alarm **≤2 dk** (SAD §17.2, NFR 10.1).

## 8. Kapsam ayrımı (bilinçli — başka modül sahibi)

dialer **çevirme**/zamanlama → 10.1.x dialer çekirdeği (kapıyı **ayarlar**, çevirmez) ·
kampanya oluşturma → 10.1.1 · CRM liste → 10.1.2 · max deneme → 10.1.3 · disposition → 10.1.5 ·
script versiyon → 10.1.6 · A/B → 10.1.8 · kapasite rate-limit → FR-RES-014/FR-OUT-007 ·
consent ön-kontrol → 10.2/§19.1 · audit **store** → 7.1.6/12.1.8 · panel UI render → L2 A-10 ·
gözlemlenebilirlik omurgası → 0.4.7.

## 9. Determinizm, vendor-neutrality, gizlilik

Sanal zaman + yapısal kimlikler; `Date.now`/gerçek-rastgele yok → aynı girdi aynı çıktı. Stdlib-only.
Vendor-neutral (ADR-001/002/012): admission kapısı sözleşmesi sağlayıcı bağımsız; canlı entegrasyonda
(10.1.x dialer) aynı sözleşme arkasına gerçek dialer. Sır/credential ve gerçek PII (müşteri adı/telefon/
hesap no/ham transkript/OTP) repoya yazılmaz; fixture sentetik (FR-TST-008).

## 10. Doğrulama durumu

`validate` **82/82** 🟢 · `selftest` **57/57** 🟢 · `run` **16/16** 🟢 (9 pass + 7 degrade beklendiği
gibi elendi) · `behavior` **49/49** 🟢. İskelet kapısı; F2 canlı dialer (10.1.x) + audit store (12.x)
entegrasyonu gerçek telemetri ile doldurur.
