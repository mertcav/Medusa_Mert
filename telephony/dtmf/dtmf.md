# DTMF Algılama/Üretme (RFC 2833 / SIP INFO) — WBS 2.1.6

> Kaynak doğruluk: **`dtmf-spec.json`**. Bu doküman tasarımı/gerekçeyi açıklar; çelişkide
> `docs/BRD.md` · `docs/SAD.md` · `docs/API.md` esastır. Vendor-neutral (ADR-002),
> credential-free, stdlib-only — `managed-cpaas/` (2.1.3) + `byoc-sip/` (2.1.4) +
> `numbering/` (2.1.5) disipliniyle aynı.

## 1. Kapsam ve mimari konum

Bu dilim **DTMF olay düzlemini** sabitler: TelephonyAdapter (SAD §11.5) içinde, hem managed
CPaaS (M1, 2.1.3) hem ham SIP trunk (M2, 2.1.4) için **DTMF algılama** (inbound) ve **üretme**
(outbound) sözleşmesi. 2.1.3/2.1.4 DTMF'i yalnız **yüzey-seviye** (mode + normalize `dtmf`
olayı) bildiriyordu; burada DTMF birinci-sınıf, **deterministik** bir sözleşmeye dönüşür
(FR-TEL-006, SR-TEL-006).

```
PSTN/SIP ──► SBC / SIP GW / Media GW ──► TelephonyAdapter ───────────────► Orchestrator (SAD §6.1)
   │  RFC 2833 telephone-event (RTP)          │  ALGILAMA: debounce + süre kapısı      turn state machine
   │  veya SIP INFO (application/dtmf*)        │  + kod→basamak  ────► normalize `dtmf` ─┘  (DTMF = turn girdisi;
   │                                           │                                            TTS sırasında barge-in)
   ◄── RFC 2833 / SIP INFO ◄── ÜRETME: sendDtmf(callId, digits) (API §11.5) ◄── aksiyon/IVR
```

**In-band (sesbandı tek-ton) algılama KULLANILMAZ** (invariant **D1**): platform 8 kHz G.711
no-transcode medya hattı çalışır (FR-RES-008, SAD §7.2); in-band ton tespiti bu hatta güvenilmez
ve STT'yi kirletir. Yalnız **out-of-band** iki standart yol desteklenir — bu da vendor-neutral
≥2-yol ilkesiyle (ADR-002) hizalıdır.

## 2. Algılama (inbound)

### 2.1 RFC 2833 / RFC 4733 — RTP telephone-event
Tek bir mantıksal basamak **birden çok RTP paketi** üretir: `marker` bit'li başlangıç paketi +
artan `duration`'lı ara paketler + **End-bit (E=1)** bitiş paketi(leri) (tipik 3 artık/redundant
kopya). Algılayıcı bunları **tam olarak bir** mantıksal basamağa **debounce** eder (**D2**):

- Yeni basamak: `marker` bit veya olay kodu değişimi.
- Sonlandırma: (i) End-bit paketinde, veya (ii) yeni marker/olay başladığında — bu ikincisi
  **kayıp-End-bit dayanıklılığı** sağlar.
- Artık (redundant) End paketleri ilk sonlandırmadan sonra **yutulur** (paket başına tekrar yok).

**Süre kapısı (D4):** nihai `duration` (timestamp birimi) → ms = `duration·1000/clock_rate`;
`< min_duration_ms` (varsayılan 40 ms) ise **sahte** sayılıp düşürülür.

**Kod → basamak (D3):** RFC 2833 olay kodu `0..15` → `0..9 * # A..D` kanonik eşleme;
aralık dışı (`>15`) **reddedilir** (`INVALID_REQUEST`).

### 2.2 SIP INFO (RFC 2976)
`application/dtmf-relay` (`Signal=<basamak>` + `Duration=<ms>`) veya `application/dtmf` (düz
basamak) gövdesi **tek basamağa** ayrıştırılır (**D5**). Süre verilmişse aynı süre kapısı
uygulanır.

### 2.3 Birleşik normalize olay
Her iki yol **aynı** `dtmf` olayına indirgenir (**D6**) — downstream mode-agnostik; 2.1.3/2.1.4
ingress `dtmf` sözleşmesiyle birebir. Olay `tenant_id`/`correlation_id`/`call_id` bağlamını
(SAD §13.3) taşıyarak turn-event akışına (API §12.2) girer.

## 3. Üretme (outbound) — `sendDtmf(callId, digits)`

API §11.5 `sendDtmf` **müzakere edilen modu** kullanır (**D7**):
- **rfc2833:** her basamak için `marker`'lı başlangıç + ara + `end_redundancy` adet End-bit
  artık paket; basamaklar arası `inter_digit_gap_ms` boşluk.
- **sip_info:** her basamak için bir INFO isteği.

Gönderilecek tüm basamaklar **gönderim öncesi** `digit_set`'e karşı doğrulanır; geçersiz basamak
**hiç gönderilmeden** reddedilir (`INVALID_REQUEST`). Üretilen DTMF kendi ses-bandına yazılmaz.

## 4. PCI / hassas maskeleme (BRD §8.5, SEC-17, TM-I-03)

Ödeme/kart/PIN/OTP toplama penceresinde (`sensitive`) DTMF basamakları **kart verisi** taşıyabilir.
Bu pencerede (**D8**):
- Basamak değeri **yalnız aksiyon kanalına** (deterministik IVR/ödeme hattı) gider.
- Transkript / kayıt / LLM bağlamı / gözlemlenebilirlik **MASK_TOKEN** (`•`) görür.
- Maskeli DTMF **asla** açık-metin loglanmaz (FR-REC-004/005).

Pencere oturum politikasıyla (`cp.sector.pci_in_scope`, DPIA) açılır. Bu dilim **sözleşmeyi/kancayı**
tanımlar; tam PCI ödeme akışı (kart verisi LLM/transkript/kayıt dışı, aktarım) **17.2.6'da (F3)**
derinleşir.

## 5. Turn entegrasyonu

DTMF bir **turn girdisidir**; TTS oynatımı sırasında geldiğinde **barge-in benzeri** kesme
tetikleyebilir (kullanıcı tuşa basarak agent'ı keser) — orchestrator TTS akışını ≤200 ms içinde
iptal eder (**D9**, FR-RTC-002, NFR 10.1, ADR-005/009). DTMF out-of-band olduğundan medya hattını
kirletmez.

## 6. Hata taksonomisi, residency, PII

- **Hata (D10):** geçersiz basamak/kod/süre → `INVALID_REQUEST`; desteklenmeyen/müzakere edilmemiş
  mod → `UNAVAILABLE`; bölge uyumsuzluğu → `REGION_VIOLATION` (API §11.6).
- **Residency (D11):** DTMF olayları home-region'da işlenir (NFR 10.7).
- **PII (D12):** spec/config/örneklerde ham RTP payload, gerçek kart/PIN veya müşteri girdisi
  **yok**; basamaklar illüstratif.

## 7. Doğrulama

`dtmf_probe.py` (stdlib-only):
- `validate` — spec + config invariant kapısı (D1–D12) → çıkış kodu.
- `detect <sample>` — deterministik algılama simülatörü (RFC 2833 debounce + SIP INFO + süre kapısı
  + maskeleme).
- `generate <sample>` — deterministik üretme simülatörü (mod + basamak doğrulama + dizi + boşluk).
- `selftest` / `schema`.

**Durum:** `validate 42/42 · selftest 38/38 · dtmf_behavior 30/30` 🟢; 6 sample (4 pass + 2
bilinçli fail) beklendiği gibi. Canlı DTMF kapısı F1'de gerçek RFC 2833 RTP + SIP INFO trunk ile
(`DTMF_API_URL`) koşar.

## 8. İzlenebilirlik

| Invariant | Gereksinim |
|-----------|-----------|
| D1 out-of-band only | FR-TEL-006, FR-RES-008, SAD §7.2 |
| D2 debounce | FR-TEL-006, RFC 2833/4733 |
| D3 kod→basamak | FR-TEL-006, API §11.6 |
| D4 süre kapısı | FR-TEL-006 |
| D5 SIP INFO | FR-TEL-006, RFC 2976 |
| D6 birleşik normalize | API §12.1/§12.2, ADR-001, SAD §8.1 |
| D7 üretme | FR-TEL-006, API §11.5 |
| D8 PCI maskeleme | BRD §8.5, FR-REC-004/005, SEC-17, TM-I-03 |
| D9 barge-in | FR-RTC-002, NFR 10.1, ADR-005/009 |
| D10 hata taksonomi | API §11.6 |
| D11 residency | NFR 10.7 |
| D12 sır/PII yok | CLAUDE.md, BRD §14/§8.5, TM-I-03 |

Kaynak: FR-TEL-006 → SR-TEL-006 → TC-TEL-006 (RTM). Kapsam dışı (bilinçli): tam PCI ödeme akışı
→ 17.2.6 (F3); SBC/SIP App Server → 2.1.1/2.1.2; medya/RTP jitter buffer → 2.2.x; AMD/voicemail →
2.1.x ileri.
