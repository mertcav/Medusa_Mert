# adapters/telephony — WBS 4.2.5 Telephony adapter #1 + #2 (SIP trunk + BYOC)

Sağlayıcı Soyutlama Katmanı'nda (Adapters; BRD §16, SAD §8) **iki somut `TelephonyAdapter` implementasyonunu**
(≥2/kategori — ADR-002, FR-TEL-002) ortak SPI (SAD §8.1 / API §11.5) arkasına bağlar. Orchestrator (Çekirdek
IP, SAD §6; ADR-001) **yalnız** bu SPI'ye bağımlıdır; somut **taşıma modu** arkada değişir. **FR-TEL-002:**
*SIP trunk ve BYOC (Bring Your Own Carrier) bağlantısı desteklenmelidir* — iki taşıma modu tek SPI arkasında:
**managed CPaaS** (Media Streams WS, M1 / 2.1.3) + **BYOC SIP trunk** (ham SIP+RTP, M2 / 2.1.4).

## SPI yüzeyi (API §11.5)

`dial` (outbound) · `answer` (inbound) · `transfer` (cold/warm/whisper, SIP REFER) · `sendDtmf`
(RFC 2833 / SIP INFO) · `hangup` (standart neden kodu) · `mediaStream` (RTP/SRTP 8kHz) ·
`on(ANSWERED/HANGUP/DTMF/AMD)`. İki taşıma modu **tek normalize sözleşmeye** indirgenir — orchestrator
M1/M2 farkını görmez (**P1**, ADR-001).

## HARD kapılar (P1–P8)

| Kapı | İnvariant | Ölçüt |
|------|-----------|-------|
| **P1** | Taşıma-nötr normalize | `contract_divergence=0` (managed/BYOC → tek SPI; ADR-001) |
| **P2** | E.164 + caller-ID havuzu | `invalid_e164=0` + `missing_caller_id_pool=0` (FR-TEL-004/005) |
| **P3** | Cold/warm/whisper transfer | `unsupported_transfer=0` (FR-TEL-007) |
| **P4** | DTMF + AMD olayları | `dropped_event=0` (FR-TEL-006/010) |
| **P5** | ≥2 SPI-uyumlu sağlayıcı/trunk | managed + BYOC (FR-TEL-002/ADR-002) |
| **P6** | Hangup standart neden kodu | `missing_reason_code=0` (taksonomi 2.1.7; FR-TEL-012) |
| **P7** | Medya 8kHz + SRTP + kurulum | `non_8khz=0` + `insecure_media=0` + `setup_p95 ≤ 2000 ms` (FR-RES-008/NFR 10.6) |
| **P8** | Metering + residency + taksonomi | UsageRecord/çağrı (SECONDS) + `region_violation=0` + ErrorTaxonomy |

`P9` (komşu seam) + `P10` (ErrorTaxonomy / sır+ham-numara+PII yok) → `validate`. **Kurulum gecikmesi**
(P7) SAD §20 medya transport bütçesinden (0.2.1) **ayrıdır** — bu post-dial/kurulum kalemidir.

## Dosyalar

```
telephony-adapter-spec.json                    # kaynak doğruluk (P1–P10 invariant)
telephony-adapter.md                           # tasarım dokümanı
telephony_adapter_probe.py                     # validate / simulate / selftest / schema (deterministik)
config/telephony-adapter-profiles.json         # 2 somut sağlayıcı (managed CPaaS / BYOC SIP trunk) + 3 profil
samples/
  telephony-inbound-happy-path.json            # answer → media → DTMF/AMD → hangup (A; P1–P8)
  telephony-outbound-dial.json                 # dial + E.164 + caller-ID havuzu (A; P2)
  telephony-transfer-modes.json                # cold/warm/whisper transfer (B; P3)
  telephony-dtmf-amd.json                      # DTMF (RFC 2833 + SIP INFO) + AMD telesekreter (A; P4)
  telephony-byoc-fallback-secondary.json       # SIP 503 → UNAVAILABLE normalize + ikincil trunk (B; P8/P9)
  telephony-degraded.json                      # bilinçli bozuk: normalize/event/setup/secure/reason kapalı → P1/P4/P6/P7 eler
tests/telephony_adapter_behavior_test.py       # T1–T8 davranış kapısı
run_live_test.sh                               # statik + sample (+ canlı NOT)
```

## Çalıştırma

```bash
python3 telephony_adapter_probe.py validate                       # spec → P1–P10 + config
python3 telephony_adapter_probe.py selftest                       # iyi/kötü spec+sample negatif kapı kanıtı
python3 telephony_adapter_probe.py simulate samples/telephony-transfer-modes.json
python3 tests/telephony_adapter_behavior_test.py                  # T1–T8
bash run_live_test.sh                                              # hepsi + canlı NOT/SKIP
```

## İki somut sağlayıcı (illüstratif, vendor-neutral)

| Sağlayıcı | Tip / mod | yön | transfer | DTMF | AMD | 8kHz/SRTP | residency | kurulum |
|-----------|-----------|-----|----------|------|-----|-----------|-----------|--------:|
| `tel-managed-A` | managed CPaaS (M1) | in+out | cold/warm/whisper | rfc2833/sip_info | ✓ | ✓ | EU/TR (NONE) | 720 ms |
| `tel-byoc-B` | BYOC SIP trunk (M2) | in+out | cold/warm/whisper | rfc2833/sip_info | ✓ | ✓ | TR (EPHEMERAL) | 540 ms |

Her ikisi de tüm kapıları geçer → ADR-002 portföy (managed + BYOC = **≥2 + fallback** FR-TEL-002).
Kurulum değerleri **mühendislik varsayılanı**; gerçek değerler 0.3.x canlı PoC + gerçek trunk'ta ölçülür.

## Kapsam ayrımı (seam'leri tüketir, motorları uygulamaz)

| Konu | Nereye |
|------|--------|
| SBC (SIP güvenlik/topoloji/DDoS) | **2.1.1** |
| Managed çerçeve (M1) / BYOC SIP-RTP (M2) | **2.1.3 / 2.1.4** (tüketilir) |
| E.164 normalize + caller-ID havuz **motoru** | **2.1.5** (biçim uygunluğu doğrulanır) |
| DTMF detect/generate **motoru** | **2.1.6** (olay yüzeye çıkarılır) |
| Çağrı neden kodu **taksonomisi** | **2.1.7** (hangup neden kodu tüketilir) |
| Retry/geri-arama · AMD **motoru** | **2.1.8 / 2.1.9** (FR-TEL-009/010) |
| RTP/jitter · codec · edge VAD/barge-in | **2.2.1 / 2.2.2 / 2.2.3** (ADR-005) |
| Handoff akışı · outbound consent | **8.x / 10.2** (FR-HND, FR-TEL-013/014) |
| Telefoni fallback **anahtarlama** | **4.3.x** (FR-TEL-002; ≥2 SPI-uyum + ErrorTaxonomy varlığı doğrulanır) |
| Ortak yetenekler · metering · region motoru | **4.1.2/4.1.6 / 4.1.3 / 4.1.4** |
| Telekom/sağlayıcı **seçimi** | **0.2.1 / 0.2.6 / 0.3.x** (vendor-neutral, ADR-002) |

Vendor-neutral (ADR-002); deterministik (olay-tetikli, sanal saat, **random YOK**; gerçek SIP/RTP yığını
yok — sağlayıcı kurulum gecikme profili + çağrı kontrol **modeli**). Sır/credential, ham **telefon
numarası**, çağrı **medyası** ve PII **değeri** repoya **yazılmadı** — yalnız sağlayıcı/trunk kimliği +
gecikme/çağrı sayıları + mod/yön/transfer/neden-kodu kimlikleri + uygunluk bayrakları + sanal zaman.
