# WBS 5.8 — "Tenant verisi eğitime kapalı" varsayılanı (no-train)

`F1` · `Must` · →**FR-LLM-012** · SR-LLM-012 · TC-LLM-012

Platform-geneli **no-train varsayılan** yönetişim kapısı: tenant verisi bir **LLM/STT/TTS**
sağlayıcısına gönderilmeden **ÖNCE**, modelin **eğitiminde** kullanılmasına karşı **varsayılan
olarak kapalıdır** (`noTrain=true`, fail-closed). Bu varsayılan **sessizce gevşetilemez**; yalnız
**açık + maker-checker'lı + denetimli + süreli** bir governed training opt-in (compliance profile
izin veriyorsa) eğitime açar — **regüle/yasaklı profilde opt-in ezilir** (most-restrictive-wins;
tenant override **yalnız-sıkılaştırır**). Ayrıca sağlayıcının **no-train yeteneği** + **no-log
retention** (NONE/EPHEMERAL) + **bölgesel pin** + **imzalı DPA** doğrulanır; karşılamayan
sağlayıcıya tenant verisi **gönderilmez**.

Sağlayıcı-nötr (ADR-002), credential-free, deterministik karar motoru (`governance/voice-consent`
disipliniyle birebir). Ham prompt/transkript/audio veya PII **değeri saklanmaz** — yalnız opak
referanslar + kimlikler + sanal zaman.

## Yerleşim (SPI seam)
`resolveTrainingDisposition(tenantId, providerId, dataClass, optInRef?, t)` → `{decision:
ALLOW|DENY, effective_no_train: bool, deny_reason?}`. Adapter (4.2.4 `LlmAdapter` + STT/TTS)
`complete()`/`transcribe()`/`synthesize()` **öncesi** bu kararı çözer; `effective_no_train` değeri
`AdapterConfig.noTrain`/`dataRetention` + `LlmRequest.noTrain` alanlarına yazılır ve sağlayıcı
çağrısında **uygulanır** (FR-LLM-012/P6). Orchestrator yalnız **karara** bağımlıdır (ADR-001);
medya hot-path'i **değildir** (SAD §20 bütçesi dışı).

## HARD kapılar (P1–P8 ↔ T1–T12)
| Kapı | İçerik | İz |
|------|--------|----|
| **P1** | Varsayılan no-train (`train_without_optin=0`) + sessiz gevşetme yok (`loosening_override=0`) | T1/T3, FR-LLM-012 |
| **P2** | Sağlayıcı uygunluğu: no-train yetenek + no-log retention + DPA + bölge pin | T2/T11, FR-LLM-012/FR-KB-010/BRD §14.1/NFR 10.7 |
| **P3** | Opt-in süre dolumu + geri çekme → güvenli no-train | T5/T6 |
| **P4** | Opt-in kapsamı (tenant/data_class) | T7 |
| **P5** | Tenant izolasyonu | T8, FR-TEN-002 |
| **P6** | Profil en-kısıtlayıcı (regüle profil opt-in'i ezer) | T9, DPIA §D3/SAD §19 |
| **P7** | Audit + WORM | T10, FR-IAM-006/FR-REC-009 |
| **P8** | Maker-checker + no-PII | T4/T12, ADR-012/TM-I-09 |

Tüm sayaç kapıları `=0`; ihlal sayaçları **yalnız politika gevşetildiğinde** (degraded) >0 olur.

## Komutlar
```bash
python3 no_train_probe.py validate            # spec + config doğrulama (86/86)
python3 no_train_probe.py selftest            # iyi/kötü kapı kanıtı (59/59)
python3 no_train_probe.py simulate <sample>   # deterministik karar motoru → kapı → exit
python3 tests/no_train_behavior_test.py       # davranış kapısı T1–T12 (22/22)
./run_live_test.sh                            # statik kapı + tüm sample'lar (+ canlı SKIP)
```

## Sample senaryolar (`samples/`, sentetik FR-TST-008)
- `no-train-default-happy` — opt-in'siz 3 use → hepsi effective no-train (🟢).
- `no-train-governed-opt-in` — açık governed opt-in (maker-checker + DPA + süre + kapsam) → bir use
  eğitime **meşru** açık, kapsam dışı use güvenli no-train'e düşer (🟢).
- `no-train-regulated-forbids` — regüle profil geçerli opt-in'i **ezer** → no-train (🟢 most-restrictive).
- `no-train-provider-denied` — no-train'siz / log'layan / DPA'sız sağlayıcı → her use **DENY** (🟢).
- `no-train-degraded` — disiplin gevşetilmiş deployment → P1/P2/P6 **eler** (`expect=fail`, 🔴 beklenen).

## Kapsam ayrımı
Gerçek sağlayıcı çağrısında `noTrain` **uygulaması** → 4.2.4 `LlmAdapter` (P6) + STT/TTS adapter;
residency/retention **zorlama motoru** → 4.1.4/1.2.2; alt-işleyen/DPA **sözleşme listesi** →
0.2.6 `contract-dpa-checklist` (Ek-A); compliance profile `cp.*` **çözümleme** → DPIA; `audit_log`
fiziksel şeması → 1.1.4; sağlayıcı **seçimi** → 0.2.6/0.3.x (vendor-neutral). Burada **yalnız**
no-train varsayılan disposition + sağlayıcı uygunluk kararı.

## Notlar
- **Sır/credential repoya yazılmaz** — yalnız `${ENV}` placeholder (`dpa_registry`).
- `.md` source-of-truth değil; **kaynak doğruluk** `no-train-spec.json` + `docs/BRD.md`/`docs/SAD.md`.
  Çelişkide BRD/SAD esastır.
