# Warm Transfer (köprüleme + whisper brifing) — Tasarım (WBS 9.2)

> **İz:** FR-TEL-007 (warm) · FR-HND-006 (whisper brifing) · FR-HND-007 (fallback) · FR-HND-008 (raporlama) ·
> SR-TEL-007 · SR-HND-006 · TC-TEL-007 · TC-HND-006 · SAD §7.3 (Human Handoff Akışı) · BRD §9.12 / §14.2 / §19(6) ·
> ADR-001/002/005.
> **Faz:** F1 · **Öncelik:** Must. **Kaynak doğruluk** `warm-transfer-spec.json`; çelişkide BRD/SAD/API esastır.

## 1. Amaç ve kapsam

9. workstream'in (İnsan Temsilciye Aktarım) ikinci modülü ve **F1-Must aktarım çekirdeği**. FR-TEL-007 üç
transfer tipinden (**cold / warm / whisper**) **warm (attended/danışmalı)** transfer'i sahiplenir ve
FR-HND-006'yı (whisper brifing) uygular. SAD §7.3:

> WARM: agent köprülenir, AI temsilciye whisper ile özet verir, sonra çıkar.

**Cold'dan (9.1) farkı:** cold *fire-and-forget*'tir (SIP REFER, oturum kapanır, köprü **yok**); warm
**danışmalı köprüleme**dir. AI önce müşteriyi **beklemeye** alır (hold), CC hedefine **danışma çağrısı**
(consultation B-leg) kurar, hedef yanıtlayınca **yalnız temsilciye duyulan** whisper brifing verir (müşteri
beklemede, **duymaz**), sonra müşteri (A-leg) ile temsilci (B-leg) **köprülenir** ve AI medya yolundan çıkar.
Başarılı olursa müşteri↔temsilci doğrudan konuşur, orijinal A-leg **kapanmaz** (köprülü); başarısız olursa
**oturum düşmez** — müşteri hold'dan geri alınır ve 9.7 fallback (callback/voicemail/ticket) devreye girer.

Bu modül warm transfer'i bir **deterministik durum makinesi** (danışmalı/attended transfer yaşam döngüsü,
RFC 5589 + REFER/Replaces RFC 3891) olarak gerçekler. Gerçek danışma INVITE / re-INVITE hold / RTP köprüleme
`TelephonyAdapter.transfer()` (4.2.5) ve BYOC/managed trunk'tadır; bu modül o SPI'yi **çağırır** ve
leg/transfer-result olaylarını **tüketir**.

## 2. Durum makinesi

```
        G1 hedef       G2 anons+hold     G3 200 OK        G4 whisper       G5 köprü+çıkış
 INIT ─────────► ANNOUNCE ───────► CONSULT_RINGING ──► WHISPER ────► BRIDGED ────────► TRANSFERRED
  │ hedef yok/      │ (AI bildirimi,     │ yanıtsız/         │ temsilci    │ köprü ÖNCE      │ RELEASE_AI:
  │ cross-tenant    │  müşteri hold,     │ meşgul/red/       │ köprü       │ → AI çıkış      │  A+B köprülü kal,
  ▼                 │  BRD §14.2)        │ deadline          │ öncesi      │ (W4)            │  AI medya çekilir,
 FAILED ◄───────────┴────────────────────┴────ayrıldı───────┴─────────────┘ köprüsüz-çıkış   │  A-leg KAPANMAZ
  │                                                                          (W4)             │  (müşteri↔temsilci)
  └─► FALLBACK: oturum DÜŞMEZ, müşteri hold'dan geri alınır, 9.7 (callback/voicemail/ticket) ◄┘
```

| Durum | Anlam |
|-------|-------|
| `INIT` | Aktarım kararı geldi (tetik 9.4 dışarıda); warm transfer başlatıldı. |
| `ANNOUNCE` | AI müşteriye aktarım bildirimi yapar + müşteri **hold**'a alınır (BRD §14.2). |
| `CONSULT_RINGING` | `transfer(callId, target, WARM)` çağrıldı; danışma B-leg INVITE gönderildi, **200 OK** (temsilci yanıtı) bekleniyor; müşteri hold'da. |
| `WHISPER` | Temsilci yanıtladı (danışma kuruldu); AI **yalnız temsilciye** whisper brifing verir (müşteri hold'da, duymaz; FR-HND-006). |
| `BRIDGED` | Müşteri (A-leg) ile temsilci (B-leg) medyası birleşti; AI çıkmak üzere. |
| `TRANSFERRED` *(terminal-başarı)* | Köprü kuruldu + AI çıktı → müşteri↔temsilci doğrudan; A-leg **kapanmaz** (köprülü), agent (AI) medyası durur. |
| `FAILED` *(terminal-başarısızlık)* | Danışma yanıtsız/meşgul/red / deadline → oturum düşmez, müşteri hold'dan geri alınır, fallback (9.7). |

**Fail-safe her aşamada:** Hedef geçersiz (INIT), danışma reddi (CONSULT_RINGING), whisper/köprü hatası
(WHISPER/BRIDGED) veya deadline — her başarısızlık **tek bir `FAILED` terminaline** gider, müşteriyi hold'dan
geri alır ve fallback tetikler; asla tanımsız/stuck durumda kalınmaz (W1).

## 3. Attended-transfer eşlemesi (RFC 5589 / 3515 / 3891)

| Rol | Aktör |
|-----|-------|
| transferor | Platform (handoff manager, AI) — A-leg sahibi |
| transferee | Müşteri (A-leg, **hold**'da) |
| consultation target | CC hedefi (`QUEUE`/`SKILL`/`AGENT`/`NUMBER`, B-leg) |

Yaşam döngüsü: `re-INVITE` (müşteri hold, sendonly) → `INVITE` (danışma B-leg → hedef) → `200 OK`
(temsilci yanıt) → **whisper medya** (AI↔temsilci, müşteri sızmaz) → `REFER + Replaces` (A+B köprü, B2BUA
medya join) → AI çıkış (transferor medya çekilir). Ham SIP/Q.850 kodları **yalnız audit/log**'ta; müşteriye
sızmaz (W11). Whisper brifing **içeriği** 9.6 bağlam paketi **özet referansıdır** (özet+intent+alanlar+auth);
ham metin/PII bu katmanda **yok**.

## 4. İnvariant'lar (HARD kapılar)

| # | İnvariant | Kapı |
|---|-----------|------|
| **W1** | FSM tamlığı: her senaryo bir terminal'e ulaşır; stuck yok. | `stuck_state=0`, `require_terminal` |
| **W2** | Anons + hold önce; anonssuz/sessiz danışma yok (BRD §14.2). | `blind_consult=0` |
| **W3** | Whisper privacy: brifing yalnız temsilciye; müşteri (hold'da) duymaz (FR-HND-006). | `whisper_leaked=0` |
| **W4** | Köprü önce, çıkış sonra; köprüsüz AI çıkışı yasak (müşteri ortada bırakılmaz). | `unbridged_exit=0`, `require_bridge_on_success` |
| **W5** | Fail-safe: danışma başarısızlığında oturum düşmez + fallback (FR-HND-007). | `dropped_on_failure=0` |
| **W6** | Warm köprüleme whisper brifing içerir (FR-HND-006 Must). | `missing_whisper=0` |
| **W7** | Hedef çözülmüş + geçerli tip; yoksa danışma kurulmaz. | `unresolved_target=0` |
| **W8** | Her terminal outcome + audit (FR-HND-008 → 9.8, FR-IAM-006). | `missing_audit=0`, `require_outcome_report` |
| **W9** | Deadline guard: aşımda → FAILED (sonsuz hold/hang yok). | `hung_transfer=0`, `consult_deadline_ms` |
| **W10** | Tenant izolasyonu: cross-tenant hedef reddedilir (FR-TEN-002). | `cross_tenant_target=0` |
| **W11** | Sır/PII yok: hedef referansı kimlik; ham numara/içerik/brifing metni yok. | `secret_or_pii=0` |

## 5. Gözlemlenebilirlik (0.4.7)

`handoff_transfer_total{mode=warm,outcome}` · `handoff_wait_seconds` (anons→terminal, FR-HND-008) ·
`handoff_consult_duration_ms` (danışma INVITE→200 OK, temsilci zil) · `handoff_whisper_total{outcome}`
(FR-HND-006) · `handoff_fallback_total`. `mode`/`outcome`/`target_type`/`failure_class`/`tenant_id`
**düşük kardinalite** (label uygun); `call_id`/`correlation_id`/`consult_leg_ref`/`context_package_ref`
**yüksek kardinalite** → yalnız trace/exemplar. Aktarım başarısızlığı oranı artışı → **alarm ≤2dk**
(SAD §17.2, NFR 10.1).

## 6. Kapsam ayrımı (başka modül sahibi)

| Konu | Sahip |
|------|-------|
| `transfer()` SPI + ham danışma INVITE/hold/RTP köprüleme | **4.2.5** (bu modül çağırır/tüketir) |
| Cold transfer (SIP REFER, fire-and-forget) | **9.1** |
| Salt-whisper brifing (köprüsüz, yalnız temsilciye) | **9.3** |
| Aktarım tetikleyicileri (istek/confidence/öfke/politika) | **9.4** (kararı tüketir) |
| Kuyruk/skill/departman hedef seçimi | **9.5** (çözülmüş hedefi tüketir) |
| Bağlam paketi (özet+intent+alan+auth) + screen-pop | **9.6** (whisper özet referansını tüketir) |
| Temsilci-yok callback/voicemail/ticket motoru | **9.7** (fallback'i tetikler) |
| Aktarım başarısı + bekleme süresi raporlama toplama | **9.8** (outcome kaydını üretir) |
| Audit store / correlation zenginleştirme | 7.1.6 / 12.1.8 |

## 7. Vendor-neutrality & determinizm

Çekirdek minimal + deterministik (sanal saat `t`, random yok; gerçek SIP/medya yığını yok — danışmalı
transfer yaşam döngüsü **modeli**). Canlı sistemde Go/Rust async runtime (ADR-003) + gerçek
`TelephonyAdapter` + SBC/B2BUA; aynı leg/transfer-result olay sözleşmesi arkasına managed CPaaS
attended-transfer veya BYOC trunk takılır (ADR-002). Müşteri hold medyası + whisper/köprü medya yolu edge'de
(ADR-005/009). Spec/config/örneklerde sır/credential, ham telefon numarası değeri, whisper brifing metni veya
PII **yok** — yalnız hedef tip/referans kimlikleri + brifing özet referansı + sanal zaman + sayılar + SIP
kodu + uygunluk bayrakları.

## 8. Doğrulama

`./run_live_test.sh` → `validate` + `selftest` + `run samples` (4 pass + 5 degrade) + `behavior` (T1–T7).
Canlı danışma/köprü testi F1'de gerçek trunk + 4.2.5 adapter ile koşar.
