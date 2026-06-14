# Ses Klonlama İzin + Kullanım Kaydı (Onaylı Sesler) — WBS 4.2.6

> `F2` · `Should`/`Must` · →**FR-TTS-006** (onaylı özel/klonlanmış sesler) · **FR-TTS-007** (ses sahibi
> açık izni + kullanım kaydı). Kaynak doğruluk: `voice-consent-spec.json` (makine-okunur) + bu tasarım.
> Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only, **deterministik** karar motoru.

## 1. Amaç ve mimari konum

Bu modül, TTS sesleri için bir **yönetişim kapısıdır** — bir medya/hot-path bileşeni değil. İki BRD
gereksinimini karşılar:

- **FR-TTS-006 (Should):** Yalnız **onaylı** özel (custom) veya **klonlanmış** (cloned) sesler
  kullanılabilir.
- **FR-TTS-007 (Must):** Ses **klonlama** için ses sahibinin **açık izni (consent)** ve her kullanım
  için **kullanım kaydı (usage record)** tutulur.

```
   conversation_designer            security_compliance_officer        (farklı) approver
        │ register_voice                  │ grant_consent                   │ approve_voice
        ▼ (status=pending)                ▼ (subject_ref+evidence_ref,      ▼ (maker-checker → approved)
   ┌──────────────────────────────────────  scope, expires_at)  ───────────────────────────┐
   │              VOICE CONSENT REGISTRY (governance / control-plane)                        │
   │   voices{kind,tenant,status,created_by}   consents{voice,tenant,scope,expires,state}    │
   └───────────────────────────────────────────┬────────────────────────────────────────────┘
                                                │ resolveVoiceUse(voiceId, clonedVoiceConsentRef,
   ┌──────────────────────┐  synthesize() ÖNCESİ│                 tenantId, agentId, purpose)
   │  4.2.3 TtsAdapter     │ ───────────────────►│ → ALLOW | DENY{reason}
   │  (SPEAK durumu)       │ ◄───────────────────┘   ALLOW ⇒ usage_record (append-only) + audit
   └──────────────────────┘   karar ALLOW değilse ses ÜRETİLMEZ (ADR-001)
```

TtsAdapter'ın (4.2.3) `VoiceProfile.clonedVoiceConsentRef` alanı (API §11.3) bu kayıt defterindeki bir
`consent_id`'ye işaret eder. Orchestrator yalnız **karara** bağımlıdır (ADR-001); karar ALLOW değilse
synthesize **çağrılmaz**. Karar synthesize **öncesi tek seferlik** verilir (çağrı içi tekrar maliyeti
yok) → SAD §20 medya gecikme bütçesine **girmez** (`media_path=false`).

## 2. SPI yüzeyi

| Yöntem | Açıklama |
|--------|----------|
| `registerVoice(voiceId, voiceKind, tenant, createdBy, ownerSubjectRef?)` | Ses kaydı (custom/cloned), `status=pending`. |
| `grantConsent(consentId, voiceId, subjectRef, evidenceRef, tenant, scope, expiresAt, grantedBy)` | Ses sahibinin açık izni (yalnız **opak ref**; ham ses/voiceprint **değil**). |
| `approveVoice(voiceId, approvedBy)` | **Maker-checker** onay → `status=approved` (onaylayan ≠ oluşturan). |
| `revokeConsent(consentId)` | İzin geri çekme = **yeni durum** (`withdrawn`); WORM mutasyon değil. |
| `suspendVoice/revokeVoice(voiceId)` | Onay durumu geri alma. |
| `resolveVoiceUse(voiceId, consentRef?, tenant, agentId, purpose)` | **Karar:** `ALLOW` \| `DENY{reason}`. |

**Ses durum yaşam döngüsü:** `draft → pending → approved → (suspended\|revoked)`. Yalnız `approved`
kullanılabilir. **İzin durumu:** `granted → withdrawn` (append-only).

## 3. HARD kapılar (P1–P8)

| Kapı | İnvariant | Ölçüt | İz |
|------|-----------|-------|-----|
| **P1** | V1 | `unapproved_use_allowed = 0` (yalnız `approved` ses) | FR-TTS-006 |
| **P2** | V2 | `cloned_without_consent_allowed = 0` (klon → geçerli izin) | FR-TTS-007 |
| **P3** | V3/V4 | `use_after_expiry = 0` + `use_after_revoke = 0` | FR-TTS-007 |
| **P4** | V5 | `out_of_scope_allowed = 0` (tenant/agent/purpose kapsamı) | FR-TTS-007 |
| **P5** | V6 | `cross_tenant_allowed = 0` | FR-TEN-002 |
| **P6** | V7 | `missing_usage_record = 0` (izin verilen her klon kullanım → 1 kayıt) | FR-TTS-007 |
| **P7** | V8 | `unaudited_event = 0` (tüm yaşam döngüsü + karar audit'li) | FR-IAM-006/FR-REC-009 |
| **P8** | V9/V10/V11 | `self_approval = 0` + `mutable_record = 0` + `pii_in_record = 0` | ADR-012/FR-REC-009/TM-S-07 |

Karar reddi (`DENY`) SPI'ye yüzeyletildiğinde API §11.6 ErrorTaxonomy'ye eşlenir: `NO_CONSENT`/
`NOT_APPROVED`/`CONSENT_EXPIRED`/`CONSENT_WITHDRAWN`→`CONTENT_FILTERED`; `OUT_OF_SCOPE`/`CROSS_TENANT`
→`AUTH`; `UNKNOWN_VOICE`/`UNKNOWN_CONSENT`→`INVALID_REQUEST`; bölge uyuşmazlığı→`REGION_VIOLATION`.

## 4. Mahremiyet, WORM ve residency

- **Ham ses / voiceprint / biyometrik şablon / PII DEĞERİ saklanmaz** (V11). Kayıtlar yalnız **opak
  referanslar** tutar (`subject_ref`, `evidence_ref` → kayıt/imza/onay deposuna işaret). Ses biyometrisi
  (kimlik doğrulama amaçlı) BRD §16/§14.448 uyarınca **özel kategori** → ayrı modül (FR-AUTH-006/007);
  burada **değer** tutulmaz. Yasak anahtarlar: `voiceprint`, `raw_audio`, `biometric_template`,
  `pii_value`, `voice_sample_b64`.
- **WORM / append-only** (V10): consent kaydı ve usage record mutasyona kapalı; opt-out = **yeni satır**
  (`consent` tablosu deseni, DB.md §5.4/§6.5). `mutate_record` olayı reddedilir.
- **Residency** (V12, NFR 10.7): consent + usage record **home-region**'da; sağlayıcıya giden ham ses
  içeriği **no-train + no-log** (`NONE`/`EPHEMERAL`).
- **Kullanım kaydı saklama:** uyumluluk delili → **no-loss / uzun saklama** (FR-REC-006); legal-hold
  duyarlı.

## 5. Tehdit / uyumluluk izi

- **THREAT_MODEL TM-S-07** (deepfake/ses klonlama ile taklit): onaylı ses kullanım kaydı + açık izin +
  maker-checker; ses tek delil değil (SEC-01). "No deceptive impersonation" politikası → 3.3.3.
- **DPIA-T-08** (ses klonlama / sentetik ses): regüle/finans tenant'ta **tenant onayı zorunlu** toggle
  (config `regulated-tr` profili), her zaman DPIA.

## 6. Kapsam ayrımı (bilinçli)

- Gerçek ses klonlama/sentez → **4.2.3 TtsAdapter** (`clonedVoiceConsentRef` tüketilir; bu modül kararı
  üretir, ses üretmez).
- Eşdeğer-ses / karakter tutarlılığı → **4.3.2** / FR-TTS-009.
- Ses **biyometrisi** (kimlik doğrulama) → **FR-AUTH-006/007** (ayrı modül; burada değer yok).
- "No deceptive impersonation" politika motoru → **3.3.3**.
- `audit_log` fiziksel şeması → **1.1.4** (burada audit bütünlüğü davranışı doğrulanır).
- Retention motoru → **1.2.3**; residency zorlama → **1.2.2** (bu modül TTL/region sözleşmesini sunar).
- Sağlayıcı **seçimi** → **0.2.6/0.3.x** (vendor-neutral, ADR-002).

## 7. İzlenebilirlik

`FR-TTS-006` ↔ `SR-TTS-006` ↔ `TC-TTS-006` (D) ↔ **4.2.6**; `FR-TTS-007` ↔ `SR-TTS-007` ↔ `TC-TTS-007`
(I) ↔ **4.2.6** (RTM v1.0; bu görevle değişmedi). Metrikler (`voice_usage_total`,
`voice_consent_denied_total{deny_reason}`, `voice_consent_active`, ...) BRD §15 → observability 0.4.7'ye
yayılır; yüksek-kardinalite kimlikler (`consent_id`/`voice_id`/`subject_ref`/`usage_id`) **metrik label
olamaz** (kardinalite disiplini).

## 8. Çalıştırma

```bash
python3 voice_consent_probe.py validate          # spec + config statik kapı (V1–V12)
python3 voice_consent_probe.py simulate samples/voice-consent-happy-path.json
python3 voice_consent_probe.py selftest          # iyi/kötü kanıt (kapı tetikleme)
python3 tests/voice_consent_behavior_test.py     # T1–T8 davranış kapısı
bash run_live_test.sh                            # statik + sample + (varsa) canlı not
```
