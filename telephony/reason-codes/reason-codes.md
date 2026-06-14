# Çağrı Başlangıç/Bitiş Neden Kodları — Standart Taksonomi (WBS 2.1.7)

> **İz:** FR-TEL-012 · DB.md §5.5 (`call.start_reason`/`call.end_reason`/`call.outcome`) ·
> API §6 (`Call.end_reason`) · API §10.2 (`call.completed`/`call.failed`/`call.transferred`) ·
> API §11.6 (ErrorTaxonomy) · OLAP 1.1.9 (`fct_call.end_reason` boyutu) · FR-ANA-002/003 (containment/outcome).
> **Kaynak doğruluk:** `reason-codes-spec.json`. Bu belge tasarımı/gerekçeyi açıklar.

## 1. Amaç ve mimari konum

FR-TEL-012 her çağrının **hem başlangıç hem bitiş nedenini standart kodla** kaydetmeyi
zorunlu kılar. Bu dilim, sağlayıcıdan bağımsız **kanonik bir neden taksonomisi** ve her
telefoni adaptörünün (M1 managed-cpaas / M2 byoc-sip / M3 CC) kendi yerel sinyalini bu
taksonomiye normalize ettiği bir **sınıflama sözleşmesi** tanımlar.

```
  [telefoni adaptörü]                 [reason-codes (bu dilim)]            [tüketiciler]
  SIP yanıt kodu      ┐
  Q.850 cause         ├─ signal_map → kanonik bitiş kodu + nitelikler ──┬→ call.end_reason  (DB §5.5)
  CPaaS durum dizesi  ┤                (category/status/outcome/party/   ├→ call.completed/failed/
  iç orkestratör olayı┘                 billable/retryable/event_type/   │   transferred event (API §10.2)
                                        error_taxonomy)                  ├→ fct_call boyutu (OLAP 1.1.9)
                                                                         └→ retry kararı (FR-TEL-009 / 2.1.8)
```

Bu **medya düzlemi değildir** (RTP/codec → 2.2.x), **numaralandırma düzlemi değildir**
(E.164/Caller ID → 2.1.5). Çağrı yaşam-döngüsü **olay/analitik düzlemidir**: kod üretir,
medya taşımaz.

## 2. Taksonomi tasarımı

### 2.1 Başlangıç nedenleri (`start_reasons`)
Çağrının neden başladığı — `direction` (inbound/outbound) + tetik kaynağı: `inbound_pstn`,
`inbound_did_routed` (2.1.5 DID→tenant), `outbound_campaign`, `outbound_api`,
`outbound_callback` (FR-TEL-009 retry/geri-arama). Çağrı kurulumunda yazılır, `call.started`
event'ine taşınır.

### 2.2 Bitiş nedenleri (`end_reasons`)
Her kanonik kod **tam bir nitelik kümesi** taşır (sınıflama tek bakışta tüm aşağı-akış
kararlarını besler):

| Nitelik | Anlamı | Kapalı küme |
|---|---|---|
| `category` | sınıf | normal · no_contact · failed · abandoned · compliance · system |
| `terminal_status` | `call.status` (API §6) | completed · transferred · failed |
| `outcome` | iş sonucu (FR-ANA-002/003) | contained · transferred · voicemail · no_contact · abandoned · failed · blocked |
| `party` | sonlandıran taraf | caller · callee · agent · system · network · none |
| `billable` | faturalanır mı | bool |
| `retryable` | retry/geri-arama tetikler mi (FR-TEL-009) | bool |
| `event_type` | webhook event (API §10.2) | call.completed · call.transferred · call.failed |
| `error_taxonomy` | teknik hata sınıfı (API §11.6) veya `null` | TIMEOUT · UNAVAILABLE · AUTH · … · null |

**6 kategori, ~25 bitiş kodu.** Öne çıkanlar:
- **normal** — `completed_caller_hangup`, `completed_agent_hangup`, `completed_goal_fulfilled`
  (containment, FR-ANA-002), `transfer_to_human` (FR-TEL-007), `max_duration_reached`.
- **no_contact** (outbound disposition) — `no_answer`, `busy`, `rejected`,
  `voicemail_machine_detected` (FR-TEL-010), `voicemail_left` (FR-TEL-011).
- **failed** (teknik) — `network_failure`, `provider_unavailable`, `timeout`, `no_route`,
  `media_failure`, `auth_failure`, `rate_limited`, `agent_error` → her biri API §11.6 ErrorTaxonomy taşır.
- **abandoned** — `dropped_mid_call` (FR-TEL-009 retry tetiği), `abandoned_no_capacity`
  (silent/abandoned call, FR-TEL-015 — ölçülebilir ayrı kod).
- **compliance** — `blocked_dnc` (FR-TEL-014), `blocked_consent_missing`,
  `blocked_time_window` (FR-TEL-013), `blocked_capacity` (FR-RES-014).
- **system** — `unknown` (eşlenmeyen sinyal fallback'ı; alarm + eşleme eklenmesini tetikler).

## 3. Sinyal → kanonik kod eşlemesi (`signal_map`)
Dört kaynak, vendor-neutral (ADR-002):
- **`sip`** — SIP yanıt kodları (200/BYE→normal, 486→busy, 480/408→no_answer/timeout,
  603→rejected, 503/5xx→provider_unavailable, 401/403→auth, 404/484→no_route, 488→media, 429→rate).
- **`q850`** — ITU-T Q.850 cause kodları (#16 normal, #17 busy, #19 no_answer, #21 rejected,
  #1/#3 no_route, #34/#38 unavailable/network, #102 timeout).
- **`cpaas`** — Managed CPaaS durum dizeleri (completed/busy/no-answer/failed/canceled);
  büyük-küçük harf duyarsız. `config/provider-reason-map.json` sağlayıcı-özel örtüşmeleri
  (Twilio/Telnyx) verir — taban eşlemeyi genişletir, çelişmez.
- **`internal`** — orkestratör olayları (goal_fulfilled, transfer_initiated, dnc_hit,
  consent_absent, outside_hours, no_agent_capacity, amd_machine, voicemail_dropped, …).

**Eşlenmeyen sinyal → `unknown` fallback + flag (R4).** Sessiz yutma yok: `unknown` bir
taksonomi boşluğudur; gözlemlenebilirlikte alarm üretir ve eşlemeye eklenmesi gerekir.

## 4. Değişmezler (invariants R1–R13)
`reason-codes-spec.json#invariants` kaynak doğruluğudur. Özet:
- **R1–R3** — her kod kapalı enum kümelerinde, tam nitelik seti.
- **R4** — signal_map her hedefi tanımlı koda çözülür; `unknown` fallback flag'li.
- **R5–R6** — compliance kodları faturalanmaz + `blocked`; dnc/consent kalıcı (retryable=false),
  time_window yeniden-zamanlanabilir (retryable=true).
- **R7** — failed/blocked/busy/… API §11.6 ErrorTaxonomy taşır; normal/voicemail `null`.
- **R8** — retryable yalnız geçici/temassız/kapasite; normal kapanış + transfer asla retryable değil (FR-TEL-009).
- **R9** — voicemail semantiği (FR-TEL-010/011).
- **R10** — silent/abandoned için ölçülebilir kod (FR-TEL-015).
- **R11** — her kod bir webhook event_type'a eşlenir; status↔event tutarlı (API §10.2).
- **R12** — kod adları append-only/kararlı (regex + tekil), `taxonomy_version` (OLAP boyut kararlılığı).
- **R13** — neden kodu PII içermez; residency region pin; literal sır yok.

## 5. Gözlemlenebilirlik / analitik bağlama
`end_reason` düşük-kardinalite, PII'siz kanonik etikettir → metrik label'ı ve OLAP boyutu
olmaya uygundur (0.4.7 kardinalite politikası; OLAP 1.1.9 A4 PII sınıfı `none`). Containment
oranı (FR-ANA-002) = `outcome=contained` / toplam; silent-call oranı (FR-TEL-015) =
`abandoned_no_capacity` / outbound. `retryable=true` kodları 2.1.8 retry motorunun girdisidir.

## 6. Kapsam ayrımı (bilinçli)
- Retry/geri-arama **politikası ve zamanlaması** → 2.1.8 (burada yalnız `retryable` bayrağı + `outbound_callback` start kodu).
- AMD **algoritması** + voicemail bırakma akışı → 2.1.9 (burada yalnız `voicemail_*` kodları).
- Consent/DNC/saat **zorlaması** → FR-TEL-013/014 dilimleri (burada yalnız `blocked_*` kodları).
- Medya/SIP/RTP normalize → 2.1.3/2.1.4; numara → 2.1.5; DTMF → 2.1.6.
- Faturalandırma motoru (usage_record) → FR-BIL dilimleri (burada yalnız `billable` bayrağı).
- Canlı telemetri/event yayını → F1 gerçek telefoni adaptörü + 0.4.7 omurgası.

Vendor-neutral (ADR-002); credential-free; stdlib-only. Numara/PII/sır repoya yazılmaz.
