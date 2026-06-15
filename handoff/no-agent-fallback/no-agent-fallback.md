# WBS 9.7 — Temsilci yoksa callback / voicemail / ticket (FR-HND-007)

9. workstream'in (İnsan Temsilciye Aktarım) **yedinci** modülü · **F1 · Must** · →**FR-HND-007**.

SAD §7.3 Human Handoff akış diyagramının son dalının sahibi:

```
Handoff Manager ──► hedef seçimi (departman/skill/kuyruk)
   ├─ COLD / WARM / WHISPER
   └─ temsilci yoksa ──► callback / voicemail / ticket   (FR-HND-007)   ← 9.7
```

9.1 (cold C4) / 9.2 (warm W5) / 9.3 (whisper H5) fail-safe dalları ve 9.5 (hedef seçimi R10) UNRESOLVED
yükseltmesi bu modülü **tetikler**. Modül onların ürettiği *no-agent* durumunu (temsilci yok / kuyruk dolu /
transfer başarısız / hedef çözülemedi / mesai dışı) **tüketir** ve müşteriye **çağrıyı asla düşürmeden**
ertelenmiş bir hizmet yolu sunar.

## Durum makinesi (K1)

```
EVALUATING ──► OFFERING ──► CAPTURING ──(seçim + önkoşul OK)──► FULFILLED    (callback_id/voicemail_id/ticket_id)
                                       └─(red / yakalama hatası)─► SAFE_CLOSE  (fail-safe oto-ticket — asla sessiz düşme)
```

- **EVALUATING** — no-agent nedeni + bağlamdan **uygun seçenekler** (eligible) önceliğe göre hesaplanır;
  `ticket` **daima-mevcut son çaredir** → uygun küme asla boş kalmaz (K3).
- **OFFERING** — uygun seçenekler müşteriye **sunulur** (en az bir alternatif, K2).
- **CAPTURING** — seçim + gerekli veri yakalanır: callback → onaylı pencere; voicemail → kayıt onayı + AI ifşası;
  ticket → 9.6 bağlam özeti.
- **FULFILLED** — müşterinin seçtiği seçenek oluşturuldu (referans id).
- **SAFE_CLOSE** — müşteri reddetti / yanıt vermedi / yakalama başarısız → **bağlamdan oto-ticket** (fail-safe);
  çağrı kontrollü kapanır. SAFE_CLOSE **ihlal değil**, fail-safe sonuçtur.

## Üç fallback türü (FR-HND-007)

| Tür | Açıklama | Önkoşul | Sahiplik ayrımı |
|-----|----------|---------|------------------|
| `callback` | Müşteriye geri-arama **planlanır** | onaylı numara + pencere + kanal | çevirme → outbound dialer (10.x, FR-TEL-009/FR-OUT-005) |
| `voicemail` | Müşteri **mesaj bırakır** (inbound) | kayıt onayı + AI ifşası + kanal | kayıt depolama → 12.x; *giden* voicemail → 10.1.5/FR-TEL-011 |
| `ticket` | Asenkron destek kaydı (**son çare**) | kanal | gerçek ticket API → tool/entegrasyon (11.x) |

## Çekirdek invariant'lar (K1–K12)

- **K2** — temsilci yokken **daima** en az bir alternatif sunulur (FR-HND-007). `no_offer=0`.
- **K3** — uygun küme **asla boş kalmaz**; `ticket` daima-mevcut son çaredir. `empty_eligible=0`.
- **K4** — karşılanan seçeneğin önkoşulu sağlanır. `unmet_prerequisite=0`.
- **K5** — geri-arama/voicemail yalnız **onay + AI ifşası** ile (BRD §14.2/§14). `missing_consent=0`, `no_disclosure=0`.
- **K6** — fallback yalnız **gerçek no-agent** nedeniyle tetiklenir (temsilci varken değil). `invalid_trigger=0`.
- **K7** — fallback yalnız **bu tenant'ın** kuyruğu/ticket projesine bağlanır (FR-TEN-002). `cross_tenant=0`.
- **K8** — **fail-safe minimum**: red/hata olsa bile bağlamdan oto-ticket; **asla sessiz düşme**. `silent_drop=0`.
- **K9/K10** — her sonuç **kanıt** + **audit** taşır (FR-IAM-006).
- **K11/K12** — gözlemlenebilirlik düşük-kardinalite (PII metrikte/log'da yok); spec/config/sample ham PII/sır tutmaz.

## Fail-safe ilkesi (SAD §6 — "never drop the call")

Temsilci-yok bir hata değil, **planlı bir degrade durumudur**: çağrı çökmek yerine kontrollü olarak
ertelenmiş bir hizmet yoluna (callback/voicemail/ticket) yönlendirilir. Müşteri tüm seçenekleri
reddetse bile bağlamdan (9.6 context_ref) **oto-ticket** oluşturulur → hiçbir talep kaybolmaz.

## Kapsam ayrımı

Bu modül fallback'i **sunar/seçer/oluşturma sözleşmesini üretir**; gerçek dialer çevirme (10.x), ticket API
(11.x), kayıt depolama (12.x) ve AI ifşa metni üretimi (3.x) başka modüllerin sahipliğindedir. Aktarım
mekanizması (cold/warm/whisper) 9.1/9.2/9.3'tedir; bu modül onların **fail-safe dalını** sahiplenir.
Sonuç (FULFILLED/SAFE_CLOSE + bekleme) raporlama için 9.8'e iletilir.

## İzlenebilirlik
FR-HND-007 → SR-HND-007 → TC-HND-007 → WBS 9.7. SAD §7.3 (handoff akışı) + SAD §6 (fail-soft) + BRD §9.12.
Vendor-neutral (ADR-001/002).
