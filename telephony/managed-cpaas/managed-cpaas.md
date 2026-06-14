# Managed CPaaS Entegrasyonu (Media Streams / WebSocket) — WBS 2.1.3

> Kaynak doğruluk: `cpaas-spec.json` (makine-okunur). Çelişkide **SAD §7.2/§12.1, API §11.5/§12.1, BRD** esastır.
> Faz `F1` · `Must` · →FR-TEL-002. `db/`+`cache/`+`objstore/`+`eventstream/` disipliniyle aynı:
> **vendor-neutral (ADR-002)**, **credential-free**, statik probe + deterministik davranış simülatörü + opsiyonel canlı kapı.

## 1. Amaç ve kapsam

Bu dilim, telefoni soyutlamasının (SAD §7.2) **M1 — Managed CPaaS (WS)** modunu (vendor-eval 0.2.1)
fiziksel sözleşmeye çevirir: sağlayıcı (Twilio Media Streams / Telnyx Media Streaming) PSTN'i kendi
bulutunda sonlandırır ve sesi bize **WebSocket** üzerinden akıtır; biz bu sağlayıcıya-özel medya-WS
çerçevesini **normalize** edip orchestrator'ın gördüğü tek sözleşmeye (API §12.1) indirgeriz.

```
PSTN ──► Carrier ──► [Sağlayıcı medya köprüsü] ──WSS(media JSON)──► Managed CPaaS Adapter ──► Media Gateway ──► Orchestrator
                                                                    └── bu dilim: normalize + güvenlik + lifecycle ──┘
```

**Kapsam dahilinde:** medya-WS taşıma sözleşmesi (WSS/TLS), bağlantı doğrulama, `start/media/dtmf/stop`
ingress normalize eşlemesi, `play_audio/mark/barge_in_clear` egress eşlemesi, lifecycle durum makinesi,
barge-in `clear` (≤200 ms), DTMF normalize, 8 kHz μ-law çerçeveleme (no-transcode), bağlam (tenant/
correlation/call) bağlama, residency bölge pin, hata→ortak taksonomi, ≥2 sağlayıcı + fallback, reconnect.

**Kapsam dışı (bilinçli):** ham SIP trunk / BYOC (M2) → **2.1.4**; SBC → **2.1.1**; SIP App Server
call-control → **2.1.2**; CC entegrasyonu (M3) → F2; gerçek medya RTT/jitter ölçümü → tek ölçüm hattı
`vendor-eval/media_latency_probe.py` (0.2.1); RTP/jitter buffer + codec yönetimi → **2.2.1/2.2.2**;
edge VAD/endpointing → **2.2.3** (ADR-005). Medya işleme konumu **hibrit** kararı ADR-009'a tabidir.

## 2. Mimari konum ve SPI bağlama

Adapter, `TelephonyAdapter` SPI'sinin (API §11.5, SAD §8.1) **managed modu**dur. Orchestrator yalnız SPI'ye
bağlıdır (ADR-001); sağlayıcıya-özel JSON yalnız adapter sınırı içinde kalır. SPI her topolojide aynıdır
(API §11.5, "medya konumu edge/merkez ADR-009'a bağlı; SPI değişmez").

| SPI yüzeyi (API §11.5) | Managed CPaaS karşılığı |
|------------------------|-------------------------|
| `answer()` / `mediaStream()` | Sağlayıcı medya-WS bağlantısı + duplex frame akışı |
| `sendDtmf()` | normalize `dtmf` (FR-TEL-006) |
| `hangup(reasonCode)` | `stop` + neden kodu (FR-TEL-012) |
| `on(ANSWERED/HANGUP/DTMF/AMD)` | lifecycle olayları + normalize ingress |
| TTS `cancel()` (barge-in) | egress `barge_in_clear` (sağlayıcı `clear`) |

## 3. Normalizasyon sözleşmesi (vendor-neutral kalbi)

Sağlayıcı medya-WS olayları **eksiksiz** olarak normalize ingress kümesine eşlenir (invariant **I6**):

| Normalize ingress | Twilio Media Streams | Telnyx Media Streaming | Açıklama |
|-------------------|----------------------|------------------------|----------|
| (taşıma-içi) | `connected`, `mark` | `connected` | normalize edilmez (null eşleme) |
| `start` | `start` | `start` | bağlam + mediaFormat bağlanır |
| `media` | `media` | `media` | base64 μ-law/PCM 8 kHz/20 ms |
| `dtmf` | `dtmf` | `dtmf` | FR-TEL-006 |
| `stop` | `stop` | `stop` | lifecycle sonu |

Egress aksiyonları (orchestrator→sağlayıcı) da normalize edilir: `play_audio`→`media`, `mark`→`mark`,
**`barge_in_clear`→`clear`** (buffer flush). Yeni sağlayıcı eklemek = yalnız bir eşleme tablosu + bir
profil; orchestrator değişmez (ADR-002, ≥2 sağlayıcı + fallback — invariant **I7**).

## 4. Güvenlik ve bağlam (invariant I1–I3)

- **I1 — WSS/TLS zorunlu:** düz-metin WS reddedilir (NFR 10.6, SAD §12.1).
- **I2 — medya öncesi doğrulama:** bağlantı imzası (Twilio `X-Twilio-Signature` / Telnyx Ed25519) medya
  kabulünden **önce** doğrulanır; replay penceresi sonlu (anti-spoof, THREAT_MODEL TM-S). Secret yalnız `${ENV}`.
- **I3 — bağlam bağlama:** `tenant_id + correlation_id + call_id`, sağlayıcının `start.customParameters`
  (Twilio) / `start.client_state` (Telnyx) alanından okunup **her** normalize olaya taşınır (SAD §13.3/§17.1,
  FR-TEN-002). Tenant context downstream RLS + observability korelasyonunun temelidir.

## 5. Medya çerçeveleme (invariant I4 — FR-RES-008)

8 kHz, 20 ms (50 fps), μ-law (160 bayt/çerçeve) primary; PCM16 (L16) alternatif. Gereksiz resample/
transcode zincire sokulmaz; en fazla **tek** kontrollü resample noktası (STT/TTS 8 kHz native değilse).
`tests/framing_behavior_test.py` aritmetiği doğrular (160 bayt, 50 fps, 8000 bayt/sn, base64 round-trip).

## 6. Lifecycle ve barge-in (invariant I5, I9)

```
CONNECTING ──auth──► AUTHENTICATED ──start──► STARTED ──media──► STREAMING ──stop──► STOPPED
     └── her durumdan hata ──► FAILED                 (`start` öncesi media REDDEDİLİR — I9)
```

**Barge-in (I5, ADR-009/ADR-005):** edge VAD kullanıcı sesini algılayınca orchestrator `BARGE_IN` üretir;
adapter sağlayıcıya `clear` (flush) gönderir → buffer'daki agent sesi **≤200 ms** içinde kesilir (FR-RTC-002,
NFR 10.1). Managed modda kesme gecikmesi = adapter `barge_in_clear_overhead_ms` (sağlayıcı buffer derinliği).
0.3.4/ADR-009 bulgusu: medya merkezde işlenirse barge-in P95≈266 ms ile **eler**; bu yüzden hibrit topoloji
(edge barge-in) + managed sağlayıcı `clear` overhead'i 200 ms bütçesinde tutulur. Probe `normalize`, her
sağlayıcı profili için bu overhead'i deterministik modelleyip kapıyı uygular.

## 7. Dayanıklılık (invariant I8, I13)

- **Hata→taksonomi (I8):** transport/sağlayıcı hatası API §11.6 ortak `ErrorTaxonomy`'ye çevrilir
  (`ws_handshake_timeout→TIMEOUT`, `ws_closed_unexpected→UNAVAILABLE`, `auth_signature_invalid→AUTH`,
  `region_mismatch→REGION_VIOLATION`, …). Routing yalnız taksonomiyle fallback verir; sağlayıcı-özel kod
  yalnız audit/log'da kalır (sızıntısız).
- **Fallback:** `TIMEOUT/UNAVAILABLE/RATE_LIMITED` → ikincil managed sağlayıcı / trunk (FR-TEL-002, ADR-002).
- **Reconnect (I13):** sonlu pencere (`resume_window_sec`) + `seq` takibi ile medya kaybı sınırlanır;
  pencere aşılırsa çağrı kontrollü sonlandırılır + neden kodu (FR-TEL-012).

## 8. Residency ve PII (invariant I11, I14)

- **I11:** sağlayıcı edge/bölge tenant home-region'a pinlenir (`${ENV}`); uyumsuzluk `REGION_VIOLATION` (NFR 10.7).
- **I14:** ses içeriği PII'dir; spec/config'te ham payload veya kişisel veri tutulmaz. Medya yalnız oturum
  içinde akar; kalıcı yazımı `objstore/` + `eventstream/` (transcript tiering) sözleşmelerine tabidir (BRD §14).

## 9. Doğrulama kapısı

| Komut | İş | Sonuç |
|-------|----|-------|
| `validate` | spec invariant I1–I14 + config↔spec çapraz tutarlılık + literal-sır tarama | 56/56 🟢 |
| `normalize <sample>` | deterministik medya-WS normalize simülatörü → lifecycle + invariant kapısı | happy/barge-in 🟢, degraded 🔴 (beklenen) |
| `selftest` | iyi/kötü spec+sample ile kapıların tetiklendiğini kanıtlar | 15/15 🟢 |
| `tests/framing_behavior_test.py` | μ-law/8kHz çerçeveleme aritmetiği + base64 round-trip | 5/5 🟢 |

Canlı medya-WS doğrulaması (gerçek RTT/jitter) tek ölçüm hattına (`vendor-eval/media_latency_probe.py`,
0.2.1) devredilir; bu dilim **sözleşme + normalize davranış** kapısıdır. Sır/credential repoya yazılmaz.

## 10. İzlenebilirlik

| Karar | İz |
|-------|-----|
| Managed CPaaS medya-WS (M1) normalize sözleşmesi | FR-TEL-001/002, SAD §7.2/§12.1, vendor-eval 0.2.1 |
| TelephonyAdapter SPI managed modu (orchestrator yalnız SPI) | API §11.5, SAD §8.1, ADR-001 |
| ≥2 sağlayıcı + fallback (vendor-neutral) | ADR-002, SAD §8.3, FR-TEL-002 |
| WSS/TLS + medya-öncesi auth + bağlam bağlama | NFR 10.6, SAD §13.3, THREAT_MODEL TM-S |
| 8 kHz μ-law no-transcode | FR-RES-008, SAD §7.2 |
| Barge-in `clear` ≤200 ms (hibrit topoloji) | FR-RTC-002, NFR 10.1, ADR-005, ADR-009 |
| DTMF normalize | FR-TEL-006 |
| Hata→ortak taksonomi + fallback | API §11.6, SAD §8.2/§8.3 |
| Residency bölge pin | NFR 10.7 |
| Neden kodu (reconnect aşımı / hangup) | FR-TEL-012 |
