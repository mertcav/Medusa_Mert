# WBS 11.7 — Çağrı özeti üretimi

**Faz:** F1 · **Öncelik:** Must · **İz:** BRD §8.1 (adım 9) → FR-ANA-002 → SR-ANA-002 → TC-ANA-002

11. workstream'in (Kayıt, Transkript & PII Redaction) **çağrı özeti üretimi** modülü. **BRD §8.1 adım 9**
(*"Çağrıyı özetler ve sonuçlandırır"*) + **FR-ANA-002** (*"Çağrı sonucu, intent, disposition ve completion
durumu çıkarılmalıdır"*) + DB §21 `transcript.summary` (*"çağrı özeti (BRD §8.1)"*) + DB §19 `call.outcome`
(*"containment/transfer (FR-ANA-002/003)"*) sahipliği.

**11.4 (pii-redaction)** transkripti **görüntülemeye-hazır** (PII-güvenli, `redaction_state ∈ {redacted,
not_required}`) hâle getirdikten **sonra**, bu modül **11.3** segmentlerini + **LLM özetleyici** aday özetini
(`{outcome, intent, disposition, completion, grounded_in, key_points}`) alır → **deterministik, fail-closed,
asenkron** bir **yapısal özet PLANI** (kapalı-sözlük alanlar + transkripte **dayanaklı** anahtar-noktalar)
üretir ve terminal karar verir: **`SUMMARIZED` | `NO_SUMMARY` | `NO_CONTENT` | `BLOCK`**.

Modül **Analytics Plane asenkron** çağrı-sonu post-processing'tir (SAD §10.1 özetleme; SAD §19.2; **FR-RES-011**
— hot-path değil; ADR-004/007). Özet bir **LLM çıktısıdır**; LLM-özgü risk **halüsinasyon/dayanaksızlık**'tır
— bu modül özet alanlarının transkripte **dayandığını** (grounding/faithfulness) zorlar. Özetin **görüntülenme**
yetkisi (`transcript:read`, FR-REC-008) **11.6**'da uygulanır.

## Karar akışı

```
CallSummaryRequest ─tenant─► içerik kapısı ─► PII-güvenli ─► async ─► sözlük ─► dayanak ─► no-leak ─► residency
      ├─ cross-tenant ───────────────────────────────────────────────────► BLOCK (cross_tenant)          [K12]
      ├─ upstream yok/geçersiz ─────────────────────────────────────────► BLOCK (no_upstream)
      ├─ içerik yok (upstream ∉ {REDACTED,NOT_REQUIRED}) ──────────────► NO_CONTENT (no summary)          [K6]
      ├─ redaction_state=pending (henüz-redakte-edilmemiş kaynak) ────► BLOCK (premature_summary)         [K4]
      ├─ 0 segment (boş transkript) ────────────────────────────────────► NO_SUMMARY (özetlenecek yok)
      ├─ sözlük-dışı / zorunlu eksik ───────────────────────────────────► BLOCK (invalid_summary_field)  [K3]
      └─ dolu transkript ────────────────────────────────────────────────► SUMMARIZED (dayanaklı yapısal) [K2/K5]
```

**Çekirdek garanti (K2, BRD §8.1 / FR-ANA-002):** özetteki **her** yapısal alan (`outcome/intent/disposition/
completion`) + **her** anahtar-nokta transkriptin en az bir segmentine (`seq`) **dayanmalı** (`grounded_in ⊆`
transkript seq'leri) — dayanaksız / uydurma içerik (LLM halüsinasyonu) = `ungrounded_claim = 0`.
**Çekirdek garanti (K3, FR-ANA-002 / DB §19 / FR-OUT-011):** `outcome/disposition/completion` bir **kapalı
sözlük**ten gelir (serbest LLM metni değil); `intent` tenant intent-kataloğundan; sözlük-dışı ⇒ fail-closed
`BLOCK invalid_summary_field` (`invalid_field = 0`).
**Çekirdek garanti (K4, FR-REC-004 aşağı akış / BRD §17.7):** özet **yalnız** PII-güvenli (`redacted/
not_required`) kaynaktan; `pending` kaynak ⇒ `BLOCK premature_summary`; özet ham PII değeri taşımaz
(`pii_leak = 0`).
**Çekirdek garanti (K5):** `SUMMARIZED ⇒ ungrounded_claim = 0` (dayanaksızla "tamamlandı" = `false_grounding`);
özet atlanamaz (`summary_skip = 0`).
**Çekirdek garanti (K6, FR-REC-002 aşağı akış):** `upstream ∉ {REDACTED,NOT_REQUIRED} ⇒ no_summary_persisted
= true` (`over_capture = 0`).

## Yapısal özet alanları (kapalı sözlük — `config/call-summary.json`)

| Alan | Sözlük (illüstratif) | İz |
|------|----------------------|----|
| `outcome` | contained / transferred / abandoned / voicemail / callback_scheduled / failed | DB §19 `call.outcome`, FR-ANA-002/003 |
| `disposition` | resolved / unresolved / follow_up_required / information_provided / transaction_completed / no_action | FR-OUT-011, FR-ANA-002 |
| `completion` | completed / partial / not_completed | FR-ANA-002 |
| `intent` | billing_inquiry / payment / … / **other** (katalog; "other" kuyruğu açık) | FR-ANA-002 |
| `key_points[]` | `{id, grounded_in[seq], token?}` — dayanaklı; yalnız maskeli token | BRD §8.1 |

LLM özetleyicinin serbest prose'u bu kapalı sözlüklere + dayanağa **bağlanır**. Özet **prose METİN byte**'ı
ÜRETİMİ + `transcript.summary` yazımı LLM özetleyici (SAD §10.1/§10.2) + DB §21'in işidir — bu modül yalnız
**yapısal plan + dayanak/sözlük kararını** verir (11.4'ün ham metin maskelemesini değil, maskeleme
**direktifini** vermesi gibi).

## İnvariant'lar (K1–K12)

`K1` determinizm/terminal · **`K2` dayanak/sadakat (ÇEKİRDEK)** · **`K3` kapalı sözlük (ÇEKİRDEK)** ·
**`K4` PII-güvenli kaynak + ham PII yok (ÇEKİRDEK)** · **`K5` atlanamaz/fail-closed (ÇEKİRDEK)** ·
**`K6` içerik kapısı (FR-REC-002 aşağı akış)** · `K7` residency (NFR 10.7) · `K8` asenkron/hot-path dışı
(FR-RES-011) · `K9` kanıt · `K10` audit · `K11` kardinalite + ham PII yok · `K12` sır/PII yok + tenant
izolasyonu.

## Çalıştırma

```bash
python3 call_summary_probe.py validate          # statik spec/config/kapsama kapısı
python3 call_summary_probe.py selftest          # motor invariant'ları (K1–K12)
python3 call_summary_probe.py check samples      # örnek senaryolar (13 pass + 13 degrade)
python3 call_summary_probe.py schema             # karar sözleşmesi
python3 tests/call_summary_behavior_test.py      # dışarıdan davranış doğrulaması
./run_live_test.sh                               # hepsi + (canlı LLM özetleyici SKIP)
```

**Durum:** validate **111/111** 🟢 · selftest **82/82** 🟢 · check **26/26** 🟢 (13 degrade beklendiği gibi
elendi) · behavior **86/86** 🟢.

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| İçerik/kayıt kararı + tamamen kapatma | 11.1 (FR-REC-001/002) |
| Kanal/track yerleşimi | 11.2 (FR-REC-003) |
| Transkript üretimi (segment/timeline) | 11.3 (FR-REC-008; **segment seq tüketilir**) |
| PII redaction + `redacted` + access_ready | 11.4 (FR-REC-004; **tüketilir — PII-güvenli kaynak**) |
| Kart/parola/OTP kayıttan çıkarma | 11.5 (FR-REC-005) |
| Erişim audit + görüntüleme yetkisi | 11.6 (FR-REC-008/009) |
| Özet **PROSE byte** üretimi + `transcript.summary` yazımı | SAD §10.1/§10.2 + DB §21 |
| intent sınıflandırma modeli + QA skorlama + containment **raporlama** | FR-ANA-001/003..013 (alanlar üretilir, raporlama değil) |
| Handoff bağlam paketi (gerçek-zamanlı özet) | 9.6 / FR-HND-004 (**ayrı** — bu modül çağrı-**sonu** asenkron özet) |
| Token özetlemesi (hot-path Session Memory) | FR-LLM-005 / FR-RES-010 (**ayrı**) |

## Notlar

- **Vendor-neutral** (ADR-001/002): LLM özetleyici sağlayıcı bağımsız; aynı yapısal özet sözleşmesi arkasına
  gerçek LLM adapter (SAD §8.4).
- **Sır/credential ve gerçek PII yok**: spec/config/sample yalnız yapısal kimlik + enum + dayanak `seq` +
  maskeli token tutar; ham PII değeri / transkript metni / **özet prose** repoya yazılmaz (sentetik fixture;
  FR-TST-008). Özet PII-güvenli redakte kaynaktan üretilir.
- **Determinizm**: kanonik `(field, seq)` dayanak sırası; `Date.now`/`random` yok → aynı girdi aynı karar.
- İskelet kapısı; **canlı LLM özetleyici + `transcript.summary`/`call.outcome` yazımı + residency** F1'de
  gerçek entegrasyonla dolar (`${CALL_SUMMARY_URL}`).
