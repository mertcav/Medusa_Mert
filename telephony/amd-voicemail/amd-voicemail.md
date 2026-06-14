# Answering Machine Detection (AMD) + Voicemail Bırakma (WBS 2.1.9)

> **İz:** FR-TEL-010 (AMD) · FR-TEL-011 (voicemail) · SR-TEL-010 (T — doğruluk eşiği) ·
> SR-TEL-011 (D — makine senaryosunda voicemail bırakılır) · API §11.5 `TelephonyAdapter.on(AMD)` ·
> BRD §8.1/§14.2 (AI ifşası) · SAD §6.1 (turn state machine, insan yolu) ·
> 2.1.7 reason-codes (`voicemail_machine_detected`, `voicemail_left`) · 2.1.8 retry (tüketici) ·
> FR-OUT-003 (consent) · FR-TEL-014/FR-OUT-006 (DNC).
> **Kaynak doğruluk:** `amd-voicemail-spec.json`. Bu belge tasarımı/gerekçeyi açıklar.

## 1. Amaç ve mimari konum

Outbound bir çağrı karşılandığında karşı taraf **canlı insan** mı yoksa **telesekreter/voicemail**
mi? FR-TEL-010 bunu ayırmayı (AMD), FR-TEL-011 ise makine ise **bip sonrası bir mesaj bırakmayı**
ister. Bu dilim iki sözleşmedir:

- **detection (AMD)** — karşılama sonrası sinyaller → deterministik `amd_class ∈ {human, machine, unknown}`.
- **drop (voicemail)** — `machine` algılandığında kontrollü, uyumlu, bip-sonrası mesaj bırakma.

```
  çağrı karşılandı
        │
        ▼
  [signals]  CPaaS AMD ipucu (2.1.3) ∨ medya heuristiği (greeting/beep/silence)
        │
        ▼
  classify ─→ human   ─→ proceed_human  ─→ normal konuşma turu (SAD §6.1)
            ├ unknown ─→ treat_as_human ─→ proceed_human (insan-güvenli, A3)
            └ machine ─→ drop:
                          uyum kapıları (policy→consent→DNC→ifşa→bip)
                            ├ left              ─→ voicemail_left (billable; 2.1.7)
                            └ not_left_*        ─→ voicemail_machine_detected (retryable → 2.1.8)
```

Bu **medya kodek/RTP düzlemi değildir** (→2.2.x). Çağrı karşılandıktan sonra **"kim/ne cevapladı +
ne yapmalı"** algılama+aksiyon düzlemidir. Üretilen kanonik kodlar 2.1.7 taksonomisine aittir ve
2.1.8 retry kararını besler (`voicemail_machine_detected` retryable=true).

## 2. AMD sınıflandırıcı (FR-TEL-010)

İki kaynak (vendor-neutral, ADR-002):

1. **managed CPaaS AMD ipucu** (2.1.3) — sağlayıcı bir AMD sonucu döndürürse (`human`/`machine`) ve
   güveni `min_confidence`'ı geçerse doğrudan kullanılır (`signal_source=cpaas_amd`).
2. **medya heuristiği** — aksi halde öznitelik skoru. Deterministik `p_machine ∈ [0,1]`:
   - **bip** (`feature_weights.beep`=0.45) — en güçlü makine işareti (voicemail bip tonu).
   - **karşılama süresi** (`greeting`=0.35) — `human_greeting_ms→machine_greeting_ms` lineer rampa;
     uzun monolog → makine, kısa "alo?" → insan.
   - **karşılama sonrası sessizlik** (`silence`=0.20) — ters rampa; insan dinlemek için duraklar,
     makine duraklamadan sürdürür.

   Ağırlıklar toplamı **1.0** → `p_machine` sınırlı (probe `validate` bunu doğrular).
   `machine ⇔ p_machine ≥ min_confidence`; `human ⇔ (1−p_machine) ≥ min_confidence`; aksi **unknown**.

**İnsan-güvenli tasarım (A2/A3):** Seçilen sınıfın güveni eşiği geçmedikçe `unknown` denir
(aşırı-iddia yok). `unknown → treat_as_human` — belirsizde **asla** voicemail bırakılmaz; gerçek
kişiye sessiz kalma/yanlış mesaj riski engellenir. Bu yüzden tek zayıf sinyal (ör. yalnız bip = 0.45)
`min_confidence`=0.80'i geçmez → makine ilan edilmez.

## 3. Doğruluk kapısı (SR-TEL-010, T yöntemi)

`accuracy` komutu etiketli (human/machine) sentetik küme (FR-TST-008) üzerinde sınıflandırıcıyı
koşturur ve iki eşik uygular:
- **doğruluk** ≥ `min_accuracy` (0.90) — genel insan/makine ayrımı.
- **false_machine_rate** ≤ `max_false_machine_rate` (0.05) — **kritik güvenlik metriği**: insanın
  makine sınıflandırılma oranı. Yanlış-makine, gerçek kişiye voicemail bırakma/sessiz kalmaya yol
  açtığından sıkı sınırlanır. `unknown→human` çözümü bu metriği korur (belirsizde insan sayılır).

Bu, STT WER / Vector recall kapılarıyla (0.2.2/0.2.5) aynı disiplindir; `T` (test) doğrulama yöntemi.

## 4. Voicemail bırakma (FR-TEL-011, SR-TEL-011 D yöntemi)

`machine` algılandığında `drop`, **bırakmadan önce** uyum/bip kapılarını sırayla uygular
(compliance-by-design; her engel açık bir `voicemail_outcome` üretir — sessiz düşürme yok, A13):

| Kapı | Koşul | Sonuç | İz |
|---|---|---|---|
| G1 | `policy.enabled=false` (detect-only) | `not_left_policy_off` | FR-TEL-011 |
| G2 | `consent != granted` | `not_left_compliance` | FR-OUT-003 |
| G3 | `do_not_call=true` | `not_left_compliance` | FR-TEL-014/FR-OUT-006 |
| G4 | `require_disclosure ∧ !disclosure_included` | `not_left_compliance` | BRD §14.2 |
| G5 | `beep_required ∧ bip yok/`geç | `not_left_no_beep` | FR-TEL-011, A4 |
| — | tümü geçti | `left` → **`voicemail_left`** (billable) | FR-TEL-011 |

**A4 — bip sonrası ilke:** `beep_required` iken mesaj **yalnız** bip sonrası başlar
(`message_started_after_beep=true`); karşılamanın/insanın üzerine konuşulmaz, yanlış tarafa kayıt
bırakılmaz. `max_beep_wait_ms` + `max_message_seconds` sonludur (kaçak bekleme/sonsuz mesaj yok, A10).

**2.1.7 köprüsü (A7):** bırakıldı → `voicemail_left` (billable=true, retryable=false); bırakılmadı →
`voicemail_machine_detected` (billable=false, retryable=true → 2.1.8 retry kararını besler). Eşleme
2.1.7 taksonomisiyle çapraz-doğrulanır (uyuşmazlık → `validate` eler).

**PII (A11):** voicemail mesajı `message_ref` (TTS şablon / kayıt id) ile referanslanır — **ham audio
değil**; karar numara/transkript/ad taşımaz; residency region pin.

## 5. Değişmezler (invariants A1–A14)
`amd-voicemail-spec.json#invariants` kaynak doğruluğudur. Özet:
- **A1** — `amd_class` kapalı küme; her zaman bir sınıf (sessiz null yok).
- **A2** — sınıf ∈ {human,machine} yalnız güven ≥ `min_confidence`; aksi unknown (aşırı-iddia yok).
- **A3** — unknown → treat_as_human; belirsizde voicemail bırakılmaz (insan-güvenli).
- **A4** — voicemail yalnız machine ∧ enabled ∧ bip sonrası; karşılamanın üzerine konuşulmaz.
- **A5** — `require_disclosure` ise mesaj AI ifşası taşır (BRD §14.2); yoksa `not_left_compliance`.
- **A6** — bırakma consent=granted ∧ !DNC gerektirir; aksi `not_left_compliance`.
- **A7** — bırakıldı→`voicemail_left` (billable), bırakılmadı→`voicemail_machine_detected` (retryable); 2.1.7 ile tutarlı.
- **A8** — sınıflandırma deterministik (aynı signals → aynı sonuç; random/cüzdan-saati yok).
- **A9** — doğruluk ≥ eşik ∧ false_machine_rate ≤ eşik (SR-TEL-010 T).
- **A10** — `max_beep_wait_ms` + `max_message_seconds` sonlu.
- **A11** — karar PII içermez (numara/transkript/ham-audio yok); `message_ref` referansı; residency pin.
- **A12** — human yolu normal tura devredilir (SAD §6.1); voicemail tek-yön egress (STT/barge-in yok).
- **A13** — `voicemail_outcome` kapalı küme; her `left` olmayan sonuç açık gerekçe taşır.
- **A14** — config ≥2 profil (detect-only + drop-enabled); sıralı eşikler + sonlu sınırlar; literal sır yok.

## 6. Gözlemlenebilirlik / analitik bağlama
`amd_class`, `voicemail_outcome`, `signal_source` düşük-kardinalite, PII'siz kanonik etiketlerdir →
metrik label'ı/OLAP boyutu olmaya uygun (0.4.7; OLAP 1.1.9 A4 `none`). AMD makine-oranı, false_machine
izlemesi (canlıda örneklemli insan doğrulamasıyla), voicemail bırakma/başarısızlık dağılımı bu
kararlardan türetilir. `voicemail_machine_detected` ile biten çağrılar 2.1.8 retry'a → 2.1.7'ye geri
beslenir (kapalı döngü).

## 7. Kapsam ayrımı (bilinçli)
- AMD **DSP/sinyal işleme** (gerçek ton/enerji analizi, VAD) → F1 voice runtime edge (ADR-009 hibrit);
  burada deterministik öznitelik-skoru **modeli + kapısı** (gerçek özniteliklerin yerini canlı DSP alır).
- Voicemail **medya egress/TTS oynatma** → 0.2.3 TTS + 2.2.x medya; burada yalnız **bırakma kararı +
  dizi + bip-sonrası garantisi** (mesaj `message_ref` ile referanslanır).
- **Disposition** (insan/voicemail/meşgul/geçersiz ayrımı, FR-OUT-008) → 10.1.4/10.1.5 (burada yalnız
  AMD ekseni + voicemail kodları).
- Consent/DNC **kayıt & zorlama** kaynağı → DB.md §5.4 + FR-TEL-013/014 (burada **girdi** olarak okunur).
- Retry zamanlaması → 2.1.8 (burada yalnız `voicemail_machine_detected` kodunu üretir).
- Neden kodu taksonomisi → 2.1.7; numara/Caller ID → 2.1.5; medya/SIP/RTP → 2.1.3/2.1.4.
- Canlı AMD doğruluğu + voicemail bırakma → F1 gerçek CPaaS AMD + medya egress + örneklemli QA.

Vendor-neutral (ADR-002); credential-free; stdlib-only; deterministik (sanal saat; random yok).
Numara/transkript/ham-audio/sır repoya yazılmaz.
