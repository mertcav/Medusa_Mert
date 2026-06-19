# runtime/call-derivation — WBS 14.2.2 Intent/outcome/disposition/completion çıkarımı

> `F1`/`F2` · `Must` · →**FR-ANA-002** (+ FR-OUT-011) · SR-ANA-002 (A) · TC-ANA-002

Analytics/Ops Plane'deki (SAD §4.2, async batch — ADR-004/ADR-007) **çıkarım (derivation) motoru**.
Çağrı bittikten sonra event stream üzerinden (`voice.call.lifecycle.v1` [FR-ANA-002] +
`voice.transcript.redacted.v1` [redacted]) **PII-redaksiyonlu** sinyallerle çalışır, **HER UYGUN çağrı**
için (FR-ANA-002; SR-ANA-002 **%100 kapsam**) **DÖRT** kategorik alanı kapalı-sözlükten **deterministik**
türetir ve sonucu `call` (DB.md §5.5) + OLAP `fct_call` ile **BİREBİR** alanlarla doldurur.

**BİRİNCİL HARD kapı = %100 kapsam** — her uygun çağrı tam olarak bir çıkarım alır ve **DÖRT alanın hepsi
dolu** (`coverage_gap=0`). Sınıflanamayan ≠ atlama; sinyal eksik çağrı yine `degraded` olarak türetilir
(kapalı-sözlük **sentinel**'leriyle, null yok), aksi halde %100 bozulur.

## Türetilen DÖRT alan (kapalı-sözlük, düşük-kardinalite enum)

| Alan | Persist hedefi | Sözlük (örnek) | Sentinel |
|------|----------------|----------------|----------|
| `intent` | `fct_call.intent` (FR-ANA-002) | billing/payment/appointment/technical_support/… | `unknown` |
| `outcome` | `call.outcome` (DB §5.5, FR-ANA-002/003) | contained/transferred_to_human/abandoned/not_connected/unresolved | `unresolved` |
| `disposition` | `fct_call.disposition` (FR-ANA-002, FR-OUT-011) | resolved/escalated/callback_scheduled/voicemail_left/… | `no_action` |
| `completion_status` | `fct_call.completion_status` (FR-ANA-002) | completed/partial/abandoned/transferred/not_started | `partial` |

Türetim **sağlayıcı-nötr** (ADR-002) deterministik öncelik kurallarıdır (random YOK). `disposition`
`outcome`'a referansla türetilir → tuple **içsel-tutarlı**. LLM/NLU sınıflayıcı canlıda redaksiyonlu
`intent_signal`'i **üretir**; motor onu kapalı-sözlüğe **normalize** eder (zarf + kapılar değişmez).

`outcome`'un per-call etiketi 14.2.3'ün **containment/transfer ORAN** raporunun girdisidir (bu motor
etiketi üretir; oran kapısı 14.2.3).

## Cross-field tutarlılık (C1–C5)

- **C1** `outcome=transferred_to_human` ⟹ `completion=transferred`
- **C2** `outcome=abandoned` ⟹ `completion=abandoned`
- **C3** `outcome=not_connected` ⟹ `completion=not_started`
- **C4** `completion=completed` ⟹ `outcome ∈ {contained, unresolved}`
- **C5** `disposition=escalated` ⟹ `outcome=transferred_to_human`

Öncelik kurallarının C1–C5'i **tüm sinyal kombinasyonlarında** sağladığı `validate` içinde
**non-circular** kanıtlanır (motorla üret → ihlal say → 0 olmalı).

## HARD kapılar (G1–G9)

- **G1 kapsam (BİRİNCİL):** üretilen == uygun + DÖRT alan dolu (%100; FR-ANA-002/SR-ANA-002)
- **G2 katalog:** `intent`/`disposition`/`completion_status` OLAP `fct_call` FR-ANA-002 sütunlarıyla BİREBİR (non-circular)
- **G3 sözlük:** DÖRT alanın her değeri kapalı-sözlükte (düşük-kardinalite enum, serbest metin yok → PII taşıyamaz)
- **G4 tutarlılık:** cross-field C1–C5 (outcome↔completion↔disposition çelişmez)
- **G5 idempotent:** `(tenant_id,call_id,schema_version)` daraltılır; at-least-once çift satır üretmez (1.1.8 P3)
- **G6 async:** analytics plane non-blocking; çıkarım başarısızlığı canlı çağrıyı etkilemez (FR-RES-011)
- **G7 PII:** yalnız redaksiyonlu sinyal; ham transkript/ses/PII DEĞERİ yok (FR-REC-004)
- **G8 izolasyon:** her çıkarım `tenant_id` + cross-tenant yok + residency (FR-TEN-002/NFR 10.7)
- **G9 uygunluk:** uygun-olmayan statü açık `reason_code` taşır (sessiz atlama yok)

## Dosyalar

- `derivation-spec.json` — makine-okunur kaynak doğruluk (placement, coverage, eligibility, vocabularies, derivation, output_contract, idempotency, feature_policy, isolation, gates, invariants I1–I13)
- `derivation_probe.py` — stdlib-only `validate` / `derive <sample>` / `selftest` / `schema`
- `config/derivation-profiles.json` — deployment profilleri (eu/tr-standard + regulated-dedicated; region + schema_version)
- `samples/` — `derivation-happy-path` (4 uygun→4 çıkarım) · `derivation-degraded-input` (degraded yine türetilir) · `derivation-degraded` (bilinçli bozuk, çoklu kapı eler)
- `tests/derivation_behavior_test.py` — T1–T11 davranış kapısı
- `run_live_test.sh` — statik kapı + sample; `${DERIVATION_URL}` varsa canlı not, yoksa SKIP

## Çalıştırma

```bash
python3 derivation_probe.py validate              # 104/104 PASS
python3 derivation_probe.py selftest               # 55/55 PASS
python3 tests/derivation_behavior_test.py          # 22/22 PASS
python3 derivation_probe.py derive samples/derivation-happy-path.json
./run_live_test.sh
```

## Kapsam ayrımı

otomatik kalite skoru → 14.2.1 · containment/transfer **ORANI** → 14.2.3 (bu motorun `outcome`
etiketini agrege eder) · yanlış-bilgi/tool-hata/güvenlik **İŞARETİ** → 14.2.4 · kritik işaretleme →
14.2.5 · QA **MANUEL** skor → 14.2.6 · sürüm karşılaştırma → 14.2.7 · dashboard/export → 14.2.8.
Burada **yalnız** per-call DÖRT-alan deterministik çıkarımı + %100 kapsam.
**Sır/credential, ham ses payload, transkript METNİ, PII DEĞERİ repoya yazılmaz.**
