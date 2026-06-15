# Whisper Transfer (yalnız temsilciye duyulan brifing) — Tasarım (WBS 9.3)

> **İz:** FR-TEL-007 (whisper) · FR-HND-006 (whisper brifing ruhu) · FR-HND-007 (fallback) · FR-HND-008 (raporlama) ·
> SR-TEL-007 · TC-TEL-007 · SAD §7.3 (Human Handoff Akışı) · BRD §9.12 / §14.2 / §19(6) ·
> ADR-001/002/005.
> **Faz:** F2 · **Öncelik:** Must. **Kaynak doğruluk** `whisper-transfer-spec.json`; çelişkide BRD/SAD/API esastır.

## 1. Amaç ve kapsam

9. workstream'in (İnsan Temsilciye Aktarım) üçüncü modülü ve **F2-Must aktarım çekirdeği**. FR-TEL-007 üç
transfer tipinden (**cold / warm / whisper**) **whisper** transfer'i sahiplenir (cold → 9.1, warm → 9.2).
SAD §7.3:

> WHISPER: yalnız temsilciye duyulan brifing.

**Warm'dan (9.2) farkı:** warm **danışmalı köprüleme**dir — müşteri **HOLD**'a alınır, **ayrı bir danışma
B-leg** (consultation) kurulur, hedef yanıtlayınca whisper verilir, sonra A+B **köprülenir** ve AI çıkar;
warm'da whisper geçici bir aşamadır. Whisper transfer ise müşteriyi **HOLD'a ALMAZ** — temsilci **canlı
çağrıya** (konferans, RFC 4579 ad-hoc conferencing) eklenir, AI **per-leg (katılımcı-başına) seçici medya
karışımıyla** yalnız temsilciye brifingi iletir (müşteri leg'i whisper medyasını **almaz**, görüşme **canlı**
sürer), sonra AI medya yolundan çıkar → müşteri↔temsilci canlı çağrıda doğrudan devam eder.

Whisper'ı diğer iki tipten ayıran **çekirdek mekanizma**:
- **(a) müşteri asla bekletilmez** (canlı per-leg whisper, hold+danışma **değil** — H4);
- **(b) brifing per-leg karışımla yalnız temsilciye gider**, müşteri **canlı** çağrıda duymaz (H3 whisper
  privacy — warm'dan **daha keskin**: müşteri beklemede sessiz değil, **aktif dinliyor**, bu yüzden sızıntı
  kesin duyulur).

Bu modül whisper transfer'i bir **deterministik durum makinesi** (ad-hoc conferencing RFC 4579 +
per-katılımcı seçici medya / whisper-coach mix) olarak gerçekler. Gerçek konferans INVITE / per-leg whisper
karışımı `TelephonyAdapter.transfer()` (4.2.5) ve BYOC/managed media-server'dadır; bu modül o SPI'yi
**çağırır** ve join/whisper-medya/transfer-result olaylarını **tüketir**.

## 2. Durum makinesi

```
        G1 hedef       G2 anons(no-hold)   G3 200 OK         G4 per-leg whisper + AI çıkış
 INIT ─────────► ANNOUNCE ────────► AGENT_JOINING ──────► WHISPERING ──────────► HANDED_OFF
  │ hedef yok/      │ (AI bildirimi,      │ yanıtsız/          │ temsilci MEVCUT,    │ RELEASE_AI:
  │ cross-tenant    │  müşteri CANLI,     │ meşgul/red/        │ whisper iletildi    │  müşteri↔temsilci canlı,
  ▼                 │  hold YOK,          │ deadline           │ → AI çıkar (H7)     │  AI medya çekilir,
 FAILED ◄───────────┴──BRD §14.2─────────┴────ayrıldı/────────┴─────────────────────┘ temsilci-yokken-çıkış
  │                                            premature-exit (H7)                     (H7)
  └─► FALLBACK: oturum DÜŞMEZ, müşteri CANLI çağrıda kalır (AI ile), 9.7 (callback/voicemail/ticket) ◄┘
```

| Durum | Anlam |
|-------|-------|
| `INIT` | Aktarım kararı geldi (tetik 9.4 dışarıda); whisper transfer başlatıldı. |
| `ANNOUNCE` | AI müşteriye katılım/aktarım bildirimi yapar; müşteri **CANLI** kalır — **hold YOK** (BRD §14.2; warm'dan ayrım, H4). |
| `AGENT_JOINING` | `transfer(callId, target, WHISPER)` çağrıldı; temsilci **canlı konferansa** eklendi (join INVITE), **200 OK** bekleniyor; müşteri canlı. |
| `WHISPERING` | Temsilci katıldı; AI **yalnız temsilciye** per-leg whisper brifing verir (müşteri canlı, whisper medyasını **almaz**; FR-HND-006). |
| `HANDED_OFF` *(terminal-başarı)* | Whisper iletildi + temsilci **mevcut** + AI çıktı → müşteri↔temsilci canlı çağrıda doğrudan; müşteri leg'i **kapanmaz**, AI medyası durur. |
| `FAILED` *(terminal-başarısızlık)* | Temsilci yanıtsız/meşgul/red / deadline / temsilci-yokken-AI-çıkışı → oturum düşmez, müşteri canlı çağrıda kalır, fallback (9.7). |

**Fail-safe her aşamada:** Hedef geçersiz (INIT), temsilci reddi (AGENT_JOINING), whisper hatası /
premature-exit (WHISPERING) veya deadline — her başarısızlık **tek bir `FAILED` terminaline** gider,
müşteriyi canlı çağrıda tutar ve fallback tetikler; asla tanımsız/stuck durumda kalınmaz (H1).

## 3. Konferans + per-leg whisper eşlemesi (RFC 4579 + whisper/coach mix)

| Rol | Aktör |
|-----|-------|
| conference focus | Platform (handoff manager, AI) — mevcut çağrı focus'a yükseltilir |
| customer | Müşteri (**canlı** katılımcı, **hold YOK**) |
| agent | CC hedefi (`QUEUE`/`SKILL`/`AGENT`/`NUMBER`, eklenen katılımcı) |

Yaşam döngüsü: **focus yükselt** (müşteri↔AI çağrısı → konferans, müşteri canlı) → `INVITE` (temsilci →
konferansa ekle) → `200 OK` (temsilci katıldı) → **per-leg whisper** (AI→temsilci; mikser müşteri leg'ine
whisper medyasını **karıştırmaz** — müşteri canlı görüşmeyi duymaya devam eder) → AI çıkış (focus medya
çekilir, müşteri↔temsilci konferansta kalır). Ham SIP/Q.850 kodları **yalnız audit/log**'ta; müşteriye
sızmaz (H12). Whisper brifing **içeriği** 9.6 bağlam paketi **özet referansıdır**; ham metin/PII bu
katmanda **yok**.

**Warm ile media-plane farkı:** warm `re-INVITE` ile müşteriyi **hold** (sendonly) yapıp **ayrı** danışma
B-leg açar; whisper **hold yapmaz** — tek konferans + **per-katılımcı seçici karışım** (whisper temsilci
leg'ine, müşteri leg'ine değil). Privacy bu yüzden warm'dan daha kritik (müşteri aktif dinliyor).

## 4. İnvariant'lar (HARD kapılar)

| # | İnvariant | Kapı |
|---|-----------|------|
| **H1** | FSM tamlığı: her senaryo bir terminal'e ulaşır; stuck yok. | `stuck_state=0`, `require_terminal` |
| **H2** | Anons önce; anonssuz/sessiz temsilci enjeksiyonu yok (BRD §14.2). | `blind_join=0` |
| **H3** | Whisper privacy: brifing yalnız temsilciye per-leg; müşteri (canlı) duymaz (FR-HND-006). | `whisper_leaked=0` |
| **H4** | Müşteri bekletilmez (no-hold): canlı per-leg whisper (warm'dan ayrım). | `customer_held=0`, `require_live_customer` |
| **H5** | Fail-safe: temsilci-katılım başarısızlığında oturum düşmez + fallback (FR-HND-007). | `dropped_on_failure=0` |
| **H6** | Whisper transfer brifing içerir (whisper'sız = whisper transfer değil; FR-HND-006). | `missing_whisper=0` |
| **H7** | Temsilci mevcutken çıkış; temsilci-yokken AI çıkışı yasak (müşteri tek başına bırakılmaz). | `premature_exit=0`, `require_agent_present_on_success` |
| **H8** | Hedef çözülmüş + geçerli tip; yoksa temsilci eklenmez. | `unresolved_target=0` |
| **H9** | Deadline guard: aşımda → FAILED (sonsuz hang yok). | `hung_transfer=0`, `join_deadline_ms` |
| **H10** | Tenant izolasyonu: cross-tenant hedef reddedilir (FR-TEN-002). | `cross_tenant_target=0` |
| **H11** | Her terminal outcome + audit (FR-HND-008 → 9.8, FR-IAM-006). | `missing_audit=0`, `require_outcome_report` |
| **H12** | Sır/PII yok: hedef referansı kimlik; ham numara/içerik/brifing metni yok. | `secret_or_pii=0` |

## 5. Gözlemlenebilirlik (0.4.7)

`handoff_transfer_total{mode=whisper,outcome}` · `handoff_wait_seconds` (anons→terminal, FR-HND-008) ·
`handoff_join_duration_ms` (temsilci join INVITE→200 OK, temsilci zil) · `handoff_whisper_total{outcome}`
(FR-HND-006) · `handoff_fallback_total`. `mode`/`outcome`/`target_type`/`failure_class`/`tenant_id`
**düşük kardinalite** (label uygun); `call_id`/`correlation_id`/`agent_leg_ref`/`context_package_ref`
**yüksek kardinalite** → yalnız trace/exemplar. Aktarım başarısızlığı oranı artışı → **alarm ≤2dk**
(SAD §17.2, NFR 10.1).

## 6. Kapsam ayrımı (başka modül sahibi)

| Konu | Sahip |
|------|-------|
| `transfer()` SPI + ham konferans INVITE/per-leg whisper karışımı | **4.2.5** (bu modül çağırır/tüketir) |
| Cold transfer (SIP REFER, fire-and-forget) | **9.1** |
| Warm transfer (danışmalı köprüleme + hold) | **9.2** |
| Aktarım tetikleyicileri (istek/confidence/öfke/politika) | **9.4** (kararı tüketir) |
| Kuyruk/skill/departman hedef seçimi | **9.5** (çözülmüş hedefi tüketir) |
| Bağlam paketi (özet+intent+alan+auth) + screen-pop | **9.6** (whisper özet referansını tüketir) |
| Temsilci-yok callback/voicemail/ticket motoru | **9.7** (fallback'i tetikler) |
| Aktarım başarısı + bekleme süresi raporlama toplama | **9.8** (outcome kaydını üretir) |
| Audit store / correlation zenginleştirme | 7.1.6 / 12.1.8 |

## 7. Vendor-neutrality & determinizm

Çekirdek minimal + deterministik (sanal saat `t`, random yok; gerçek SIP/medya yığını yok — konferans +
per-leg whisper yaşam döngüsü **modeli**). Canlı sistemde Go/Rust async runtime (ADR-003) + gerçek
`TelephonyAdapter` + media-server selective mix; aynı join/whisper-medya/transfer-result olay sözleşmesi
arkasına managed CPaaS conference-coach veya BYOC media-server takılır (ADR-002). Müşteri canlı medyası +
per-leg whisper karışım medya yolu edge'de (ADR-005/009). Spec/config/örneklerde sır/credential, ham telefon
numarası değeri, whisper brifing metni veya PII **yok** — yalnız hedef tip/referans kimlikleri + brifing özet
referansı + sanal zaman + sayılar + SIP kodu + uygunluk bayrakları.

## 8. Doğrulama

`./run_live_test.sh` → `validate` + `selftest` + `run samples` (4 pass + 6 degrade) + `behavior` (T1–T8).
Canlı konferans/per-leg whisper testi F1/F2'de gerçek trunk + 4.2.5 adapter ile koşar.
