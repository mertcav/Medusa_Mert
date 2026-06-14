# SIP trunk / BYOC (Bring Your Own Carrier) — WBS 2.1.4

> Kaynak doğruluk: `byoc-spec.json` (makine-okunur). Çelişkide **SAD §7.2/§12.1, API §11.5/§12.1, BRD** esastır.
> Faz `F2` · `Must` · →FR-TEL-002. `db/`+`cache/`+`objstore/`+`eventstream/`+`managed-cpaas/` disipliniyle aynı:
> **vendor-neutral (ADR-002)**, **credential-free**, statik probe + deterministik davranış simülatörü + opsiyonel canlı kapı.

## 1. Amaç ve kapsam

Bu dilim, telefoni soyutlamasının (SAD §7.2) **M2 — Ham SIP trunk + RTP (BYOC)** modunu (vendor-eval 0.2.1
M2) fiziksel sözleşmeye çevirir: müşteri/operatör kendi SIP trunk'ını getirir, kendi **SBC**'miz SIP/RTP'yi
sonlandırır ve medya doğrudan RTP ile akar. Biz bu BYOC-özel **SIP sinyalleşme + SDP müzakere + RTP medya**
akışını **normalize** edip orchestrator'ın gördüğü tek sözleşmeye (API §12.1) indirgeriz. Bu sözleşme
**2.1.3 managed-cpaas (M1) ile birebir aynıdır** — orchestrator M1/M2 farkını görmez (ADR-001/ADR-002).

```
PSTN ──► BYOC Carrier ──SIP trunk──► SBC (TLS/SRTP) ──RTP──► BYOC SIP Adapter ──► Media Gateway ──► Orchestrator
                                                              └── bu dilim: SIP/SDP/RTP→normalize + güvenlik + diyalog SM ──┘
```

**Kapsam dahilinde:** SIP sinyalleşme (SIPS/TLS) + medya (SRTP) taşıma sözleşmesi, trunk peer doğrulama
(digest/IP-ACL/mTLS), SIP diyalog durum makinesi, SDP offer/answer codec müzakeresi (yalnız narrowband
G.711, transcode yok), `answer→start / rtp→media / dtmf→dtmf / bye→stop` normalize eşlemesi, egress
`play_audio/mark/barge_in_clear` (`rtp_playout_stop`), barge-in ≤200 ms, DTMF RFC2833/SIP-INFO normalize,
SIP REFER transfer, 8 kHz G.711 çerçeveleme (no-transcode), bağlam (DID→tenant) bağlama, residency bölge
pin, SIP yanıt kodu→ortak taksonomi, ≥2 trunk + çapraz-mod M1 fallback, re-INVITE reconnect.

**Kapsam dışı (bilinçli):** managed CPaaS (M1) → **2.1.3** (tamam); SBC kurulumu (SIP güvenlik/topoloji
gizleme/DDoS) → **2.1.1**; SIP App Server (call setup/teardown/routing detayı) → **2.1.2**; CC entegrasyonu
(M3) → F2/§3 (FR-TEL-003); E.164 normalizasyon + numara havuzu → **2.1.5**; gerçek medya RTT/jitter ölçümü
→ tek ölçüm hattı `vendor-eval/media_latency_probe.py` (0.2.1 M2); RTP/jitter buffer + codec yönetimi →
**2.2.1/2.2.2**; edge VAD/endpointing → **2.2.3** (ADR-005). Medya işleme konumu **hibrit** kararı ADR-009'a tabidir.

## 2. Mimari konum ve SPI bağlama

Adapter, `TelephonyAdapter` SPI'sinin (API §11.5, SAD §8.1) **BYOC modu**dur. Orchestrator yalnız SPI'ye
bağlıdır (ADR-001); SIP/SDP/RTP detayı yalnız adapter sınırı içinde kalır. SPI her topolojide aynıdır
(API §11.5, "medya konumu edge/merkez ADR-009'a bağlı; SPI değişmez") ve M1 ile özdeştir.

| SPI yüzeyi (API §11.5) | BYOC SIP karşılığı |
|------------------------|--------------------|
| `dial()` / `answer()` | SIP INVITE (outbound) / 200 OK + ACK (inbound) → normalize `start` |
| `mediaStream()` | SRTP duplex akış (RTP in / `rtp_out`) → normalize `media` |
| `sendDtmf()` | RFC 2833 (telephone-event) **veya** SIP INFO → normalize `dtmf` (FR-TEL-006) |
| `transfer(mode)` | SIP REFER (COLD/WARM/WHISPER) (FR-TEL-007, SAD §7.3) |
| `hangup(reasonCode)` | SIP BYE → normalize `stop` + neden kodu (FR-TEL-012) |
| `on(ANSWERED/HANGUP/DTMF/AMD)` | SIP diyalog olayları + normalize ingress |
| TTS `cancel()` (barge-in) | egress `barge_in_clear` (`rtp_playout_stop`) |

## 3. Normalizasyon sözleşmesi (vendor-neutral kalbi)

BYOC SIP diyalog olayları normalize ingress kümesine eşlenir (invariant **I6**) — **2.1.3 ile aynı küme**:

| Normalize ingress | SIP karşılığı | Açıklama |
|-------------------|---------------|----------|
| (taşıma-içi) | `invite`, `ringing`, `progress` | SM'i sürer, normalize edilmez (null eşleme) |
| `start` | `answer` (200 OK + ACK) | bağlam + müzakere edilen codec bağlanır |
| `media` | `rtp` (SRTP payload) | G.711 μ-law/A-law 8 kHz/20 ms; early-media (183) dahil |
| `dtmf` | `dtmf` (RFC2833 / SIP INFO) | FR-TEL-006 |
| `stop` | `bye` | lifecycle sonu |

Egress aksiyonları da normalize edilir: `play_audio`→`rtp_out`, `mark`→`mark`, **`barge_in_clear`→
`rtp_playout_stop`** (jitter buffer flush + RTP gönderim durdurma). Yeni trunk eklemek = yalnız bir eşleme
tablosu + bir profil; orchestrator değişmez (ADR-002, ≥2 trunk + çapraz-mod M1 fallback — invariant **I7**).

## 4. Güvenlik ve bağlam (invariant I1–I3)

- **I1 — SIPS/TLS + SRTP zorunlu:** düz-metin SIP (UDP/TCP) ve şifrelenmemiş RTP reddedilir (NFR 10.6,
  SAD §7.2/§12.1). SBC önde durur: topoloji gizleme + SIP saldırı koruması (2.1.1, FR-TEL-002).
- **I2 — medya öncesi doğrulama:** trunk peer'ı (SIP digest / IP ACL allowlist / mTLS) medya kabulünden
  **önce** doğrulanır; replay penceresi sonlu (anti-spoof, THREAT_MODEL TM-S). Secret yalnız `${ENV}`.
- **I3 — bağlam bağlama:** `tenant_id + correlation_id + call_id`, çağrılan **DID→tenant eşlemesi** ve/veya
  SIP başlık (`X-Tenant-Id` / `P-Asserted-Identity`) üzerinden çözülüp **her** normalize olaya taşınır
  (SAD §13.3/§17.1, FR-TEN-002). Paylaşımlı trunk'ta DID→tenant eşlemesi deterministik ve çapraz-tenant
  sızdırmazdır. Tenant context downstream RLS + observability korelasyonunun temelidir.

## 5. Medya çerçeveleme ve SDP müzakeresi (invariant I4, I15 — FR-RES-008)

8 kHz, 20 ms (50 fps), G.711 μ-law (pt=0) / A-law (pt=8) (160 bayt/çerçeve) primary; PCM16 (L16) alternatif.
SDP offer/answer **kesişimi** yalnız izinli narrowband codec'i (PCMU/PCMA) seçer; wideband (G722, Opus,
Speex) reddedilir. **Ortak narrowband codec yoksa transcode değil — REDDET (SIP 488 Not Acceptable Here)**
(I15). RFC 2833 telephone-event (pt=101) DTMF için müzakere edilir. Gereksiz resample/transcode zincire
sokulmaz; en fazla **tek** kontrollü resample noktası. `tests/sdp_rtp_behavior_test.py` aritmetiği +
müzakereyi doğrular (160 bayt, 50 fps, 8000 bayt/sn, kesişim, 488 reddi).

## 6. SIP diyalog durum makinesi ve barge-in (invariant I9, I5)

```
INIT ─invite─► INVITE_RECEIVED ─ringing─► RINGING ─progress(early)─► EARLY_MEDIA ─answer─► ANSWERED ─rtp─► ESTABLISHED ─bye─► TERMINATING ─► TERMINATED
   └── her durumdan hata ──► FAILED        (RTP medya ANSWERED öncesi REDDEDİLİR — TEK istisna 183 EARLY_MEDIA — I9)
```

**RTP-before-answer (I9):** medya yalnız `EARLY_MEDIA` (183 Session Progress ile müzakere edilen erken
medya) veya `ANSWERED`/`ESTABLISHED` durumlarında kabul edilir; aksi halde reddedilir (RFC 3261). Geçişler
yalnız `valid_transitions`.

**Barge-in (I5, ADR-009/ADR-005):** edge VAD kullanıcı sesini algılayınca orchestrator `BARGE_IN` üretir;
adapter `rtp_playout_stop` ile RTP gönderimini durdurur + jitter buffer'ı boşaltır → agent sesi **≤200 ms**
içinde kesilir (FR-RTC-002, NFR 10.1). M2'de ekstra bulut sıçraması olmadığından kesme overhead'i (trunk
`rtp_clear_overhead_ms`, ~20–25 ms) düşüktür — 0.3.4/ADR-009'un "merkez barge-in P95≈266 ms eler" bulgusunu
hibrit topoloji (edge barge-in) ile bütçede tutar. Probe `normalize`, her trunk profili için bu overhead'i
deterministik modelleyip 200 ms kapısına vurur (260 ms şişirilmiş overhead selftest'te eler).

## 7. Dayanıklılık ve fallback (invariant I7, I8, I13)

- **Hata→taksonomi (I8):** SIP yanıt kodu / transport / SBC hatası API §11.6 ortak `ErrorTaxonomy`'ye
  çevrilir (`sip_408_timeout→TIMEOUT`, `sip_503_unavailable→UNAVAILABLE`, `sip_401_403_auth→AUTH`,
  `sdp_no_common_codec→INVALID_REQUEST`, `region_mismatch→REGION_VIOLATION`, …). Routing yalnız taksonomiyle
  fallback verir; SIP-özel kod yalnız audit/log'da kalır (sızıntısız).
- **Fallback (I7):** `TIMEOUT/UNAVAILABLE/RATE_LIMITED` → ikincil BYOC trunk; trunk tükenirse **çapraz-mod
  M1 managed CPaaS** (2.1.3) fallback'i — en az 2 bağımsız yol (FR-TEL-002, ADR-002, BRD §19 1–4).
- **Reconnect (I13):** sonlu pencere (`reinvite_window_sec`) + `CSeq` takibi ile re-INVITE/yeniden müzakere;
  pencere aşılırsa çağrı kontrollü sonlandırılır + neden kodu (FR-TEL-012).

## 8. Residency ve PII (invariant I11, I14)

- **I11:** BYOC trunk/SBC bölgesi tenant home-region'a pinlenir (`${ENV}`); uyumsuzluk `REGION_VIOLATION` (NFR 10.7).
- **I14:** ses içeriği PII'dir; spec/config'te ham RTP payload veya kişisel veri tutulmaz. Medya yalnız oturum
  içinde akar; kalıcı yazımı `objstore/` + `eventstream/` (transcript tiering) sözleşmelerine tabidir (BRD §14).

## 9. Doğrulama kapısı

| Komut | İş | Sonuç |
|-------|----|-------|
| `validate` | spec invariant I1–I15 + config↔spec çapraz tutarlılık + literal-sır tarama | 73/73 🟢 |
| `normalize <sample>` | deterministik SIP/SDP/RTP normalize simülatörü → diyalog SM + invariant kapısı | happy/barge-in 🟢, degraded 🔴 (beklenen) |
| `selftest` | iyi/kötü spec+sample ile kapıların tetiklendiğini kanıtlar | 22/22 🟢 |
| `tests/sdp_rtp_behavior_test.py` | SDP müzakere + G.711/RTP çerçeveleme aritmetiği | 9/9 🟢 |

Canlı SIP/SBC doğrulaması (gerçek RTT/jitter, OPTIONS ping) SBC dilimi (2.1.1) + tek ölçüm hattı
(`vendor-eval/media_latency_probe.py`, 0.2.1 M2) ile koşar; bu dilim **sözleşme + normalize davranış**
kapısıdır. Sır/credential repoya yazılmaz.

## 10. İzlenebilirlik

| Karar | İz |
|-------|-----|
| BYOC ham SIP trunk + RTP (M2) normalize sözleşmesi (M1 ile birebir aynı) | FR-TEL-001/002, SAD §7.2/§12.1, vendor-eval 0.2.1 M2 |
| TelephonyAdapter SPI BYOC modu (orchestrator yalnız SPI) | API §11.5, SAD §8.1, ADR-001 |
| ≥2 trunk + çapraz-mod M1 fallback (vendor-neutral) | ADR-002, SAD §8.3, FR-TEL-002, BRD §19 |
| SIPS/TLS + SRTP + medya-öncesi auth + DID→tenant bağlam | NFR 10.6, SAD §13.3, THREAT_MODEL TM-S, FR-TEN-002 |
| 8 kHz G.711 no-transcode + SDP narrowband-only (488 reddi) | FR-RES-008, SAD §7.2 |
| SIP diyalog SM (RTP-before-answer reddi, early-media istisnası) | SAD §7.1, RFC 3261 |
| Barge-in `rtp_playout_stop` ≤200 ms (hibrit topoloji) | FR-RTC-002, NFR 10.1, ADR-005, ADR-009 |
| DTMF RFC2833 / SIP INFO normalize | FR-TEL-006, RFC 2833 |
| SIP REFER transfer (COLD/WARM/WHISPER) | FR-TEL-007, SAD §7.3 |
| Hata→ortak taksonomi + fallback | API §11.6, SAD §8.2/§8.3 |
| Residency bölge pin | NFR 10.7 |
| Neden kodu (re-INVITE aşımı / hangup) | FR-TEL-012 |
