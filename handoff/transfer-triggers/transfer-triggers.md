# WBS 9.4 — Transfer Tetikleyiciler (kullanıcı isteği · düşük confidence · öfke · politika)

> **Faz:** F1 · **Öncelik:** Must · **İz:** FR-HND-001/002 · SR-HND-001/002 · TC-HND-001/002 · SAD §7.3 · BRD §9.12 · ADR-001/002
>
> 9. workstream'in (İnsan Temsilciye Aktarım) **dördüncü** modülü. 9.1 (cold) / 9.2 (warm) / 9.3 (whisper)
> mekanizma modüllerinin tümünün **"tetikleyici→9.4 (kararı TÜKETİR)"** dediği **karar üreticisi** budur.
> Kaynak doğruluk: `transfer-triggers-spec.json`. Çelişkide BRD/SAD/SRS esastır.

## 1. Amaç ve sınır

Bu modül **NE ZAMAN** ve **NEDEN** insan temsilciye aktarım yapılacağına karar verir; **NEREYE**
(9.5 hedef seçimi) ve **NASIL** (9.1/9.2/9.3 transfer mekanizması) değil. Konuşma sürerken her
tur üretilen sinyalleri izleyen **deterministik bir değerlendirme motorudur** ve bir `TransferDecision`
üretir. SAD §7.3'teki akış diyagramında **"Orchestrator (transfer kararı)"** noktasını sahiplenir:

```
Orchestrator turn döngüsü ──► [her tur sinyalleri: confidence · sentiment · intent · policy]
                                   │
                                   ▼
                         9.4 Tetik Değerlendirme Motoru
                                   │
              ┌────────────────────┼────────────────────┐
        niteleyen yok        bir kural niteledi      (LATCH + cooldown)
              │                     │
              ▼                     ▼
        NO_HANDOFF           TransferDecision{triggered, primary_reason, contributing[], evidence}
                                   │
                                   ▼  (EMIT)
                   9.1 cold / 9.2 warm / 9.3 whisper  ──► hedef seçimi 9.5 ──► bağlam paketi 9.6
                                   │ (temsilci yok)
                                   ▼
                            9.7 callback/voicemail/ticket
```

## 2. Dört tetikleyici sınıfı (FR-HND-001/002)

| Reason | Öncelik | FR | Sınıf | Tetik koşulu | Bastırılabilir? |
|--------|---------|----|-------|--------------|------------------|
| `USER_REQUEST` | 1 | FR-HND-001 | mandatory | Açık handoff niyeti (NLU `intent=handoff_request`) → **anında**, sürdürme gerekmez | **Hayır** (T2) |
| `POLICY` | 2 | FR-HND-002 | mandatory | Politika kuralı zorunlu handoff (uyumluluk / kapsam-dışı / maks-deneme / kısıtlı konu) → **anında** | **Hayır** (T5) |
| `ANGER` | 3 | FR-HND-002 | heuristic | Öfke skoru ≥ `anger_threshold` (0.7), ardışık ≥ `anger_sustain_turns` (2) sürdürülen | Evet (config) |
| `LOW_CONFIDENCE` | 4 | FR-HND-002 | heuristic | Füzyon ASR/NLU confidence ≤ `low_conf_threshold` (0.5), ardışık ≥ `low_conf_sustain_turns` (2) **debounce** | Evet (config) |

**Öncelik (precedence):** Çoklu tetik **aynı turda** nitelik kazanırsa, en yüksek öncelikli (en düşük
sayı) `primary_reason` olur; tüm niteleyenler `contributing[]` listesine kaydedilir (T6). Farklı
turlarda nitelik kazanırsa **ilk niteleyen tur** tetikler ve LATCH'ler (T8) — sonraki turlar yok sayılır.

## 3. Durum makinesi

```
MONITORING ──(end, niteleyen yok)──────────► NO_HANDOFF   (terminal — sağlıklı yol, T7)
     │
     └──(bir kural niteledi)──► TRIGGERED      (terminal — EMIT + LATCH + cooldown, T8)
```

- **MONITORING** (başlangıç): her tur sinyalleri değerlendiriliyor; öfke/düşük-conf **sürdürme
  sayaçları** biriktiriliyor. Eşiğin üstüne çıkan confidence sayacı **sıfırlar** (histerezis).
- **TRIGGERED** (terminal): bir kural niteledi → karar LATCH'lendi, mekanizma modülüne iletildi.
  Cooldown ek karar üretmez.
- **NO_HANDOFF** (terminal): konuşma tetik olmadan sona erdi — **uydurma handoff yok**.

## 4. Çekirdek invariant'lar (T1–T11)

| # | İlke | İhlal sayacı |
|---|------|--------------|
| **T1** | Karar tamlığı/determinizm — her değerlendirme terminal'e ulaşır; aynı girdi → aynı çıktı | `stuck_state=0` |
| **T2** | Kullanıcı isteği **daima** onurlandırılır (FR-HND-001); bastırılamaz | `user_request_ignored=0` |
| **T3** | Düşük-confidence **debounce** — tek geçici tur tetiklemez (anti-flapping histerezis) | `false_trigger=0` |
| **T4** | Öfke eşik + sürdürme — tek hafif negatif tetiklemez | `false_trigger=0` |
| **T5** | Politika **zorunlu** — agent confidence ile bastırılamaz | `policy_ignored=0` |
| **T6** | Deterministik öncelik — çoklu tetikte tek `primary_reason` | `wrong_precedence=0` |
| **T7** | Sağlıklıda **spurious tetik yok** | `false_trigger=0` |
| **T8** | İlk-niteleyen LATCH + cooldown — tek karar | `duplicate_decision=0` |
| **T9** | Her tetik **kanıt + reason** taşır | `missing_evidence=0` |
| **T10** | Her karar (tetik veya değil) **audit**'e yazılır (FR-IAM-006) | `missing_audit=0` |
| **T11** | Sır/PII yok — ham transkript/müşteri sözleri spec/config/sample'da yok | `secret_or_pii=0` |

Tüm kapılar **0-ihlal eşikli** (HARD); bir senaryoda ihlal varsa probe çıkış kodu ≠ 0.

## 5. Anti-flapping (debounce/histerezis) — T3/T4

Düşük confidence ve öfke **gürültülü** sinyallerdir; tek bir turdaki geçici düşüş/sıçrama gerçek bir
sorun değildir. Motor **ardışık sürdürme penceresi** (`sustain_turns`) uygular: bir tur eşiği aşsa da,
sonraki tur normale dönerse sayaç **sıfırlanır** ve tetik oluşmaz. Bu, müşteriyi gereksiz yere
aktararak deneyimi bozan **spurious handoff**'u önler (T3/T7). `USER_REQUEST` ve `POLICY` ise kesin
sinyallerdir → **anında** tetikler, sürdürme gerekmez.

> **Tasarım kararı:** `LOW_CONFIDENCE` debounce penceresi ≥2 zorunlu (spec `validate` kapısı). Tek-tur
> tetik (`sustain=1`) flapping üretir; bu yüzden `inject no_debounce` degrade senaryosu kapıyı **eler**.

## 6. Kapsam ayrımı

| Konu | Sahip | Bu modülün rolü |
|------|-------|------------------|
| Aktarım mekanizması (SIP REFER / köprü / konferans) | 9.1 / 9.2 / 9.3 | Kararı **ÜRETİR**, taşımayı değil |
| Kuyruk/skill/departman hedef seçimi | 9.5 | `primary_reason`'ı yönlendirme ipucu olarak iletir |
| Bağlam paketi + screen-pop | 9.6 | — |
| Temsilci-yok fallback motoru | 9.7 | Karar handoff'u başlatır; fallback 9.7'de |
| Aktarım başarısı/bekleme raporlama | 9.8 | Tetik `reason` dağılımını besler |
| Confidence **üretimi** | STT adapter (4.x, FR-STT-006/007) | Skoru **TÜKETİR** |
| Sentiment/öfke **üretimi** | NLU/duygu analizi | Skoru **TÜKETİR** |
| Intent (`handoff_request`) **üretimi** | Diyalog/NLU (3.x) | Niyeti **TÜKETİR** |
| Audit store | 7.1.6 / 12.1.8 | Karar kaydını **ÜRETİR** |

## 7. Gözlemlenebilirlik (0.4.7)

- **Metrikler:** `handoff_trigger_total{tenant,reason,triggered}`, `handoff_trigger_eval_total`,
  `handoff_trigger_confidence_breach_total` (STT degradasyonu **erken uyarı**), `handoff_trigger_anger_total`.
- **Düşük kardinalite label:** `tenant_id`, `reason`, `trigger_class`, `triggered`.
- **Yüksek kardinalite (yalnız trace/exemplar):** `call_id`, `correlation_id`, `turn_index`.
- **Alarm:** düşük-confidence/öfke tetik oranı ani artışı → ≤2 dk (SAD §17.2, NFR 10.1). Düşük-confidence
  tetik dalgalanması STT kalite düşüşünün erken sinyalidir.
- Ham transkript/müşteri sözleri/skor-üreten metin metriklerde **yok** (T11).

## 8. Probe (referans uygulama)

```
transfer_triggers_probe.py validate    # statik spec/config/kapsama + sızıntı kapısı → çıkış kodu
transfer_triggers_probe.py run samples # 6 pass + 6 degrade senaryo → kapı (T1–T11)
transfer_triggers_probe.py selftest    # 37 gömülü davranış kontrolü → çıkış kodu
transfer_triggers_probe.py schema      # durum/sinyal/karar sözleşmesi
```

`tests/transfer_triggers_behavior_test.py` — selftest'ten bağımsız kara-kutu davranış kapısı (T1–T9).
`run_live_test.sh` — tüm kapıları sırayla koşar. Determinizm: sanal zaman + tur indeksi; `Date.now`/
gerçek-rastgele yok; stdlib-only; credential-free. Canlı tetik testi F1'de gerçek STT/NLU/sentiment
sinyalleri + 9.1/9.2/9.3 ile koşar.
