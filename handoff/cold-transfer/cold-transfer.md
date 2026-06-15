# Cold Transfer (SIP REFER) — Tasarım (WBS 9.1)

> **İz:** FR-TEL-007 (cold transfer) · FR-HND-007 (fallback) · FR-HND-008 (raporlama) · SR-TEL-007 · TC-TEL-007 ·
> SAD §7.3 (Human Handoff Akışı) · BRD §9.12 / §14.2 / §19(6) · ADR-001/002.
> **Faz:** F1 · **Öncelik:** Must. **Kaynak doğruluk** `cold-transfer-spec.json`; çelişkide BRD/SAD/API esastır.

## 1. Amaç ve kapsam

9. workstream'in (İnsan Temsilciye Aktarım) ilk modülü ve **F1-Must aktarım çekirdeği**. FR-TEL-007 üç
transfer tipinden (**cold / warm / whisper**) **cold/blind transfer**'i sahiplenir. SAD §7.3:

> COLD: SIP REFER → CC'ye yönlendir, **oturum kapanır**.

Cold transfer **fire-and-forget**'tir: agent müşteriyi nazikçe bilgilendirir, çağrıyı CC hedefine
(kuyruk/skill/temsilci) **SIP REFER** ile yönlendirir ve **köprü kurmadan çıkar**. Başarılı olursa orijinal
müşteri leg'i serbest bırakılır (BYE); başarısız olursa **oturum düşmez** — müşteri elde tutulur ve
9.7 fallback (callback/voicemail/ticket) devreye girer.

Bu modül cold transfer'i bir **deterministik durum makinesi** (SIP REFER yaşam döngüsü, RFC 3515) olarak
gerçekler. Gerçek SIP/RTP taşıması `TelephonyAdapter.transfer()` (4.2.5) ve BYOC/managed trunk'tadır;
bu modül o SPI'yi **çağırır** ve transfer-result olaylarını **tüketir**.

## 2. Durum makinesi

```
                    G1 hedef                G2 anons              G3 202            G4 final NOTIFY 200
   INIT ──────────► ANNOUNCE ─────────────► REFER_SENT ─────────► REFERRING ──────────► TRANSFERRED
    │ hedef yok/        │ (AI bildirimi,         │ REFER reddi          │ NOTIFY≥300                │ RELEASE:
    │ cross-tenant      │  BRD §14.2)            │ (4xx/5xx/6xx)        │ / deadline                │  A-leg BYE,
    ▼                   ▼                        ▼                      ▼                            │  agent çıkar,
   FAILED ◄────────────┴────────────────────────┴──────────────────────┘                           │  oturum kapanır
    │                                                                                               │  (fire-and-forget)
    └─► FALLBACK: oturum DÜŞMEZ, A-leg korunur, 9.7 (callback/voicemail/ticket)   ◄─────────────────┘
```

| Durum | Anlam |
|-------|-------|
| `INIT` | Aktarım kararı geldi (tetik 9.4 dışarıda); cold transfer başlatıldı. |
| `ANNOUNCE` | AI müşteriye aktarım bildirimi yapar (BRD §14.2 — aldatıcı taklit yok). |
| `REFER_SENT` | `transfer(callId, target, COLD)` çağrıldı; SIP REFER gönderildi, **202 Accepted** bekleniyor. |
| `REFERRING` | 202 alındı; NOTIFY sipfrag ilerleme (100 Trying / 180 Ringing) izleniyor. |
| `TRANSFERRED` *(terminal-başarı)* | final NOTIFY **200 OK** → orijinal A-leg BYE ile serbest, agent çıkar, oturum kapanır. |
| `FAILED` *(terminal-başarısızlık)* | REFER reddi / NOTIFY ≥300 / deadline → oturum düşmez, fallback (9.7). |

**Fail-safe her aşamada:** Hedef geçersiz (INIT), REFER reddi (REFER_SENT), NOTIFY hatası veya deadline
(REFERRING) — her başarısızlık **tek bir `FAILED` terminaline** gider ve fallback tetikler; asla
tanımsız/stuck durumda kalınmaz (C1).

## 3. SIP REFER eşlemesi (RFC 3515)

| Rol | Aktör |
|-----|-------|
| transferor | Platform (handoff manager) — A-leg sahibi, REFER'i gönderir |
| transferee | Müşteri (A-leg) |
| referred-to | CC hedefi (`QUEUE`/`SKILL`/`AGENT`/`NUMBER`) |

Yaşam döngüsü: `REFER (Refer-To: hedef)` → `202 Accepted` → implicit subscription `NOTIFY` (sipfrag
`SIP/2.0 100/180/200`) → **final NOTIFY** (`200`=başarı, `≥300`=başarısız) → başarıda transferor `BYE`.
Ham SIP/Q.850 kodları **yalnız audit/log**'ta; müşteriye sızmaz (C10).

## 4. İnvariant'lar (HARD kapılar)

| # | İnvariant | Kapı |
|---|-----------|------|
| **C1** | FSM tamlığı: her senaryo bir terminal'e ulaşır; stuck yok. | `stuck_state=0`, `require_terminal` |
| **C2** | REFER yalnız anons sonrası (blind-REFER yok; BRD §14.2). | `blind_refer=0` |
| **C3** | Başarıda orijinal A-leg serbest (orphaned/çift-faturalı leg yok). | `orphaned_leg=0` |
| **C4** | Başarısızlıkta fail-safe: oturum düşmez + fallback (FR-HND-007). | `dropped_on_failure=0` |
| **C5** | Cold = fire-and-forget; köprü yok (warm/whisper'dan ayrım). | `bridged_on_cold=0` |
| **C6** | Hedef çözülmüş + geçerli tip; yoksa REFER gönderilmez. | `unresolved_target=0` |
| **C7** | Her terminal outcome + audit (FR-HND-008 → 9.8, FR-IAM-006). | `missing_audit=0`, `require_outcome_report` |
| **C8** | Deadline guard: aşımda → FAILED (sonsuz hang yok). | `hung_transfer=0`, `refer_deadline_ms` |
| **C9** | Tenant izolasyonu: cross-tenant hedef reddedilir (FR-TEN-002). | `cross_tenant_target=0` |
| **C10** | Sır/PII yok: hedef referansı kimlik; ham numara/içerik yok. | `secret_or_pii=0` |

## 5. Gözlemlenebilirlik (0.4.7)

`handoff_transfer_total{mode=cold,outcome}` · `handoff_wait_seconds` (anons→terminal, FR-HND-008) ·
`handoff_refer_duration_ms` · `handoff_fallback_total`. `mode`/`outcome`/`target_type`/`failure_class`/`tenant_id`
**düşük kardinalite** (label uygun); `call_id`/`correlation_id`/`refer_to_ref` **yüksek kardinalite** →
yalnız trace/exemplar. Aktarım başarısızlığı oranı artışı → **alarm ≤2dk** (SAD §17.2, NFR 10.1).

## 6. Kapsam ayrımı (başka modül sahibi)

| Konu | Sahip |
|------|-------|
| `transfer()` SPI + ham SIP REFER/RTP taşıması | **4.2.5** (bu modül çağırır/tüketir) |
| Warm köprüleme + whisper | **9.2** (FR-HND-006) |
| Whisper brifing | **9.3** |
| Aktarım tetikleyicileri (istek/confidence/öfke/politika) | **9.4** (kararı tüketir) |
| Kuyruk/skill/departman hedef seçimi | **9.5** (çözülmüş hedefi tüketir) |
| Bağlam paketi (özet+intent+alan+auth) + screen-pop | **9.6** (FR-HND-004/005) |
| Temsilci-yok callback/voicemail/ticket motoru | **9.7** (fallback'i tetikler) |
| Aktarım başarısı + bekleme süresi raporlama toplama | **9.8** (outcome kaydını üretir) |
| Audit store / correlation zenginleştirme | 7.1.6 / 12.1.8 |

## 7. Vendor-neutrality & determinizm

Çekirdek minimal + deterministik (sanal saat `t`, random yok; gerçek SIP yığını yok — REFER yaşam döngüsü
**modeli**). Canlı sistemde Go/Rust async runtime (ADR-003) + gerçek `TelephonyAdapter` + SBC/trunk; aynı
transfer-result olay sözleşmesi arkasına managed CPaaS veya BYOC trunk takılır (ADR-002). Spec/config/örneklerde
sır/credential, ham telefon numarası değeri veya PII **yok** — yalnız hedef tip/referans kimlikleri + sanal
zaman + sayılar + SIP/sipfrag kodu + uygunluk bayrakları.

## 8. Doğrulama

`./run_live_test.sh` → `validate` (63/63) + `selftest` (42/42) + `run samples` (7/7) + `behavior` (T1–T6).
Canlı SIP REFER/NOTIFY testi F1'de gerçek trunk + 4.2.5 adapter ile koşar.
