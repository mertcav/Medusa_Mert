# Tehdit Modeli ve Güvenlik Tasarımı Derinleştirme (STRIDE)

## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**Threat Model & Security Design Deep-Dive (STRIDE)**
Multi-Tenant (B2B2B) · Vendor-Neutral · Real-Time Voice · Defense-in-Depth

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Enterprise Voice AI Agent Platform — Tehdit Modeli (STRIDE) |
| Doküman Tipi | Threat Model & Security Design (TM) |
| Bağlı Doküman | `docs/SAD.md` (Sürüm 1.1) §14, §24; `docs/BRD.md` (Sürüm 2.1) §10.6, §13, §14; `docs/DB.md` v1.0; `docs/API.md` v1.0 |
| Sürüm | 1.0 |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır — Karar Bekleyen Maddeler İşaretli |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar (güvenlik/uyum dağıtımı sınırlı) |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | SAD §24'teki "Threat model (STRIDE) + güvenlik tasarım derinleştirme" çıktısının ilk sürümü. Varlık envanteri, güven sınırları (TB-1..TB-9), DFD, STRIDE tehdit kataloğu (TM-S/T/R/I/D/E), risk derecelendirme (Likelihood×Impact), her tehdit için mevcut/yeni önlem eşlemesi, kalıntı risk; güvenlik tasarımı derinleştirme (SEC-01..SEC-20 kontrol önerileri), önerilen yeni ADR'ler (ADR-014..ADR-017), izlenebilirlik (FR/SR/SAD eşleme). |

---

## İçindekiler

1. Amaç, Kapsam ve Yöntem
2. Korunan Varlıklar (Asset Inventory)
3. Güven Sınırları ve Veri Akışı (DFD)
4. Tehdit Aktörleri ve Yetenekler
5. Risk Derecelendirme Yöntemi
6. STRIDE Tehdit Kataloğu
   - 6.1 Spoofing (Kimlik Sahteciliği)
   - 6.2 Tampering (Veri/İşlem Kurcalama)
   - 6.3 Repudiation (İnkâr)
   - 6.4 Information Disclosure (Bilgi İfşası)
   - 6.5 Denial of Service (Hizmet Engelleme)
   - 6.6 Elevation of Privilege (Yetki Yükseltme)
7. LLM/Voice'a Özgü Tehditler (genişletme)
8. Risk Isı Haritası ve Öncelikli Tehditler
9. Güvenlik Tasarımı Derinleştirme (SEC-01..SEC-20)
10. Önerilen Yeni Mimari Kararlar (ADR)
11. İzlenebilirlik (FR/SR/SAD ↔ Tehdit ↔ Önlem)
12. Güvenlik Doğrulama (test eşlemesi)
13. Açık Kararlar ve Sonraki Adımlar

---

## 1. Amaç, Kapsam ve Yöntem

Bu doküman, SAD §24'ün "Güvenlik & Uyum tasarım derinleştirme" maddesini karşılar: platformun **STRIDE** metodolojisiyle sistematik tehdit modelini, her tehdide karşılık gelen mimari önlemleri (mevcut + yeni), kalıntı riski ve güvenlik tasarımının derinleştirilmesini tanımlar. SAD §14 (IAM ve Güvenlik Mimarisi) ve §14.2'deki defense-in-depth tablosu burada tehdit-bazlı bir analizle doğrulanır ve genişletilir.

**Kapsam:** Tüm platform güven sınırları — telefoni edge, real-time medya, Conversation Orchestrator, provider adapter mesh, kurumsal entegrasyon, control/analytics plane, üç katmanlı panel (L0/L1/L2), public Developer API, webhook'lar ve veri depoları. Hem teknik tehditler hem de kurumsal/multi-tenant özgü tehditler (cross-tenant sızıntı, platform↔tenant güç ayrımı, break-glass kötüye kullanımı) ele alınır.

**Kapsam dışı:** Fiziksel veri merkezi güvenliği (managed cloud sağlayıcısının sorumluluğu, paylaşılan sorumluluk modeli ile devredilir), tedarikçi sağlayıcıların iç güvenliği (DPA/alt-işleyen denetimiyle 0.1.6'da ele alınır), son kullanıcı cihaz güvenliği.

**Yöntem:**
1. **Decompose** — Sistemi C4 konteyner diyagramı (SAD §4.2) üzerinden bileşenlere, veri akışlarına ve güven sınırlarına ayır (§2–§3).
2. **Identify** — Her güven sınırı ve veri deposu için STRIDE'ın altı kategorisinde tehditleri say (§6). Tehdit ID şeması: **`TM-<X>-NN`** (X = S/T/R/I/D/E STRIDE harfi).
3. **Rate** — Her tehdidi Likelihood × Impact ile derecelendir (§5).
4. **Mitigate** — Her tehdidi mevcut mimari kontrollere (SAD/BRD/FR) bağla; boşluk varsa yeni kontrol (**`SEC-NN`**) öner (§9). Kalıntı riski belirt.
5. **Validate** — Tehdit ve önlemleri SRS/RTM test case'lerine ve pentest kapsamına bağla (§12).

> **ID şeması notu:** Bu doküman FR/SR/TC dışında iki yeni ID ailesi tanıtır: tehditler için `TM-<X>-NN`, güvenlik kontrol önerileri için `SEC-NN`. Mevcut FR/SR/NFR/ADR numaralandırması **değiştirilmez**; yalnız referans verilir. Yeni önerilen ADR'ler mevcut son numaradan (ADR-013) devamla ADR-014+ olarak açılır.

---

## 2. Korunan Varlıklar (Asset Inventory)

| Varlık | Sınıf | Hassasiyet | Konum (SAD/DB ref) |
|--------|-------|------------|---------------------|
| A1 Ses medyası (canlı RTP/SRTP akışı) | Tenant iş verisi / PII | Çok yüksek | Media Gateway (geçici), data plane |
| A2 Çağrı kayıtları (recording) | Tenant iş verisi / PII | Çok yüksek | Nesne depolama (KMS, tenant prefix) — DB §Recording |
| A3 Transkript | Tenant iş verisi / PII | Çok yüksek | Transcript Store — DB §Transcript |
| A4 PII (müşteri kimlik/iletişim/finans) | Kişisel veri (KVKK/UK GDPR) | Çok yüksek | Çağrı verisi + CRM context |
| A5 Ödeme/kart verisi, OTP, parola | PCI / kimlik bilgisi | Kritik | Hiçbir kalıcı depoda olmamalı (redaction, BRD §8.5) |
| A6 Agent config / prompt / conversation flow | Tenant IP | Yüksek | Prompt/Flow Registry — DB §Agent/Prompt |
| A7 Bilgi tabanı (KB) içeriği | Tenant iş verisi | Yüksek | Vector store (tenant+agent namespace) |
| A8 Secrets / API key / KMS anahtarları / tenant DPA kredansiyelleri | Sır | Kritik | Secrets Manager / KMS (per-tenant key) |
| A9 Audit log (WORM) | Bütünlük-kritik kayıt | Yüksek | Append-only audit store — DB §Audit |
| A10 Tenant config / consent / suppression listeleri | Uyum verisi | Yüksek | Control plane — DB §Consent/Campaign |
| A11 RBAC oturum token'ları / break-glass grant'ları | Erişim kimlik bilgisi | Kritik | IAM, kısa ömürlü token |
| A12 Faturalama/kullanım kayıtları | Finans verisi | Orta-Yüksek | Billing/Usage — DB §UsageRecord |
| A13 Platform metrik/telemetri (tenant'a ait olmayan) | Operasyonel | Orta | Observability stack |
| A14 Telefon numara havuzu / Caller ID | İtibar/uyum varlığı | Orta-Yüksek | Telephony config |

**Altın kural varlık önceliği:** A1–A5 (içerik + PII) için en güçlü izolasyon. L0 platform rolleri bunları **varsayılan olarak görmez** (FR-IAM-008); yalnız A13'ü (metrik) görür. İçeriğe erişim yalnız üç katmanlı break-glass ile (FR-IAM-009/010).

---

## 3. Güven Sınırları ve Veri Akışı (DFD)

Aşağıdaki DFD, SAD §4.2 konteyner diyagramına güven sınırlarını (TB) ve numaralı veri akışlarını (→) ekler. Her `═══` çift çizgi bir güven sınırı geçişidir.

```
        Son Müşteri (telefon)            Yönetim Kullanıcısı (tarayıcı)      M2M İstemci (Public API)
              │ A1 ses                          │ panel oturumu                    │ API key/OAuth
   ══════════ TB-1 ══════════        ═══════════ TB-7 ═══════════        ═══════════ TB-8 ═══════════
              ▼                                  ▼                                  ▼
   ┌─────────────────────┐          ┌──────────────────────────┐        ┌────────────────────────┐
   │ Telephony Edge / SBC │          │  Tenant App Plane (L1/L2) │        │  Public Developer API   │
   │ (SIP/RTP terminasyon)│          │  Next.js + FastAPI guard  │        │  (S5, rate-limited)     │
   └──────────┬──────────┘          └─────────────┬────────────┘        └────────────┬───────────┘
              ▼                                    │                                  │
   ┌─────────────────────┐                        │  ════ TB-6 (plane sep.) ════     │
   │   Media Gateway      │              ┌─────────▼─────────┐  break-glass            │
   │ (VAD/echo/STT/TTS)   │              │ Platform Plane(L0) │◄── (Tier B grant) ─────┤
   └──────────┬──────────┘              │ internal-only      │                         │
              ▼                          └────────────────────┘                        │
   ┌──────────────────────────────────────────────────────────────────────────────────▼──┐
   │              Conversation Orchestrator  (Turn/Policy/LLM Router/Tool/Memory)           │
   │              ── her olay tenant_id + correlation_id taşır (TB-5 tenant izolasyonu) ──   │
   └───┬──────────────────────────────┬───────────────────────────────┬───────────────────┘
       │ ══ TB-2 ══                    │ ══ TB-3 ══                     │ (events, async)
       ▼ (provider adapter)            ▼ (integration GW)              ▼
 ┌──────────────┐              ┌──────────────────┐           ┌──────────────────────────────┐
 │ STT/TTS/LLM  │              │ Tenant Kurumsal   │           │  Analytics/Ops Plane (TB-4)   │
 │ Sağlayıcıları│              │ Sistemler(CRM/ERP)│           │  Kafka·Redaction·Audit·Billing│
 │ (3rd party)  │              │ + webhook (TB-8)  │           │  + Data Stores (A2/A3/A9)     │
 └──────────────┘              └──────────────────┘           └──────────────────────────────┘
```

### Güven sınırları tablosu

| TB | Sınır | Güven düşük taraf | Güven yüksek taraf | Birincil kontroller |
|----|-------|-------------------|--------------------|--------------------|
| **TB-1** | PSTN/SIP ↔ Telephony Edge | Çağıran (anonim, kontrolsüz) | SBC/platform | SBC topoloji gizleme, SIP rate limit, SRTP, anti-spoof |
| **TB-2** | Platform ↔ STT/TTS/LLM sağlayıcıları | Üçüncü taraf işleyen | Platform | mTLS, no-train/no-log, region pinning, PII minimizasyon |
| **TB-3** | Platform ↔ Tenant kurumsal sistemler | Karşılıklı (tool çağrısı) | Tenant sistemi | Endpoint allowlist, schema-validated tool, idempotency, scoped creds |
| **TB-4** | Data plane ↔ Analytics/Control plane | Plane'ler arası | — | Async event stream, en-az-yetki servis kimliği, network segment |
| **TB-5** | Tenant ↔ Tenant (mantıksal) | Bir tenant | Başka tenant | RLS + tenant context propagation + per-tenant KMS |
| **TB-6** | L1/L2 (tenant) ↔ L0 (platform) | Tenant düzlemi | Platform düzlemi | Ayrı deploy/realm (ADR-011), altın kural, üç katmanlı break-glass |
| **TB-7** | Tarayıcı/panel kullanıcı ↔ Backend | Kullanıcı oturumu | Backend | SSO/MFA, panel+rol+tenant guard, RLS çift kontrol, CSRF/CSP |
| **TB-8** | İnternet ↔ Public API & webhook | Dış istemci/alıcı | Platform | OAuth/API key, WAF, rate limit, HMAC webhook imza |
| **TB-9** | İşletim ↔ Üretim (yönetim/CI/CD) | İşletmen/pipeline | Üretim sistemleri | PAM, just-in-time access, imzalı artifact/SBOM, MFA |

---

## 4. Tehdit Aktörleri ve Yetenekler

| Aktör | Konum | Motivasyon | Yetenek |
|-------|-------|-----------|---------|
| TA-1 Dış saldırgan (anonim çağıran) | TB-1/TB-8 | Dolandırıcılık, veri hırsızlığı, hizmet kesme | Çağrı yapma, SIP/medya manipülasyonu, sosyal mühendislik, API fuzzing |
| TA-2 Kötü niyetli/uzlaşılmış tenant kullanıcısı | TB-5/TB-7 | Cross-tenant erişim, yetki yükseltme | Geçerli L1/L2 oturum, panel + public API erişimi |
| TA-3 Uzlaşılmış platform operatörü (insider) | TB-6/TB-9 | İçeriğe yetkisiz erişim | L0 erişimi, altyapı erişimi (PAM arkasında) |
| TA-4 Uzlaşılmış üçüncü taraf sağlayıcı | TB-2 | Veri sızdırma, prompt/yanıt manipülasyonu | Platformun gönderdiği veriye erişim, yanıt enjeksiyonu |
| TA-5 Kötü niyetli son müşteri / sosyal mühendis | TB-1 | Hesap ele geçirme, prompt injection | Konuşma içeriği üzerinden agent'ı manipülasyon |
| TA-6 Uzlaşılmış kurumsal sistem / tool endpoint | TB-3 | Veri zehirleme, SSRF köprüsü | Tool yanıtları, webhook payload |
| TA-7 Network man-in-the-middle | TB-1..TB-4/TB-8 | Dinleme, tampering | Ağ trafiğine erişim (zayıf TLS varsa) |

---

## 5. Risk Derecelendirme Yöntemi

Her tehdit **Likelihood (L)** × **Impact (I)** ile kalitatif derecelendirilir; her biri Düşük(1)/Orta(2)/Yüksek(3). Risk skoru = L×I → seviye:

| Skor | Seviye | Anlam |
|------|--------|-------|
| 6–9 | **Kritik/Yüksek** | Faz 1 öncesi/içinde önlem zorunlu (Must) |
| 3–4 | **Orta** | Faz 1–2'de planlı önlem |
| 1–2 | **Düşük** | Kabul edilebilir / izlenir |

**Impact**, BRD'nin "compliance by design" ve multi-tenant güç ayrımı önceliği nedeniyle, içerik/PII sızıntısı ve cross-tenant ihlalde her zaman Yüksek alınır. **Kalıntı risk (residual)** = önlemler uygulandıktan sonra beklenen seviye.

---

## 6. STRIDE Tehdit Kataloğu

Her tehdit: ID · sınır/varlık · L×I=Risk · mevcut önlem (FR/SAD ref) · yeni kontrol (SEC) · kalıntı.

### 6.1 Spoofing (Kimlik Sahteciliği)

| ID | Tehdit | TB/Varlık | L×I | Mevcut önlem | Yeni (SEC) | Kalıntı |
|----|--------|-----------|-----|--------------|-----------|---------|
| **TM-S-01** | Çağıran Caller ID spoof'layarak müşteri hesabı taklit eder (hassas işlem) | TB-1 / A4 | 3×3=9 | Caller ID zayıf sinyal sayılır; OTP/KBA/step-up zorunlu (FR-AUTH-001/002/003); başarısız deneme limiti (FR-AUTH-004) | SEC-01 | Düşük |
| **TM-S-02** | SIP kayıt/INVITE sahteciliği ile trunk taklidi, ücretsiz arama/toll fraud | TB-1 / A14 | 2×3=6 | SBC, SIP auth, BYOC trunk doğrulama (SAD §7, FR-TEL-002) | SEC-02 | Düşük |
| **TM-S-03** | Çalınmış panel kimlik bilgisi ile yetkili kullanıcı taklidi | TB-7 / A11 | 2×3=6 | SSO + MFA (FR-IAM-002/003); kısa ömürlü token | SEC-03 | Düşük |
| **TM-S-04** | Sahte/çalınmış API key veya OAuth client ile Public API erişimi | TB-8 / A11 | 2×3=6 | API key hash saklanır, OAuth scope (API.md §S5); rate limit | SEC-03, SEC-04 | Düşük |
| **TM-S-05** | Sahte webhook (platform taklidi) ile tenant sistemine zehirli event | TB-8 / A10 | 2×2=4 | HMAC imza (t+v1), ±300sn replay penceresi (API.md §10) | SEC-05 | Düşük |
| **TM-S-06** | Üçüncü taraf sağlayıcı taklidi (sahte STT/LLM endpoint) ile yanıt enjeksiyonu | TB-2 / A4 | 1×3=3 | mTLS/TLS pinning, sabit endpoint config (SAD §8) | SEC-06 | Düşük |
| **TM-S-07** | Ses klonlama ile temsilci/müşteri sesi taklidi (deepfake) | TB-1 / A4 | 2×2=4 | Ses biyometrisi tek başına yetersiz; çok faktör (FR-AUTH-006/007 opsiyonel); ses tek delil değil | SEC-01 | Orta |

### 6.2 Tampering (Veri/İşlem Kurcalama)

| ID | Tehdit | TB/Varlık | L×I | Mevcut önlem | Yeni (SEC) | Kalıntı |
|----|--------|-----------|-----|--------------|-----------|---------|
| **TM-T-01** | Cross-tenant veri yazma/değiştirme (tenant izolasyon atlatma) | TB-5 / A2-A7 | 2×3=6 | RLS her tablo `tenant_id`; tenant context propagation; çift kontrol (SAD §13, FR-TEN-002, DB RLS) | SEC-07 | Düşük |
| **TM-T-02** | LLM tool çağrısı parametre manipülasyonu (yetkisiz para/PII işlemi) | TB-3 / A4 | 2×3=6 | Schema-validated tool call (FR-LLM-008/FR-TOOL-002); deterministic workflow + teyit + audit (BRD §13) | SEC-08 | Düşük |
| **TM-T-02b** | Prompt injection ile policy/guard'ı atlayıp yasak işlem tetikleme | TB-1 / A4 | 3×3=9 | Input/output Policy Engine guard, sabit system prompt (SAD §6.2/§9.3, FR-LLM-007/009) | SEC-09 | Orta |
| **TM-T-03** | Audit log tahrifatı / silme (izlerin örtülmesi) | TB-4 / A9 | 1×3=3 | Append-only WORM + bütünlük (FR-IAM-006); retention/legal-hold (DB) | SEC-10 | Düşük |
| **TM-T-04** | Konfig/prompt deposunda yetkisiz değişiklik (canlı agent'a sızma) | TB-7 / A6 | 2×3=6 | Versiyonlama + maker-checker (FR-IAM-005), draft/test/staging/prod + rollback (FR-AGT-005/006); regression gate (FR-TST-004) | SEC-11 | Düşük |
| **TM-T-05** | Tedarik zinciri: zehirli bağımlılık/imaj ile kod tampering | TB-9 / tümü | 2×3=6 | SAST/DAST/dependency scan/SBOM (NFR 10.6) | SEC-12 | Orta |
| **TM-T-06** | KB/RAG içeriği zehirleme (yanlış kaynakla manipülatif yanıt) | TB-3 / A7 | 2×2=4 | Doküman erişim yetkisi + versiyonlama (FR-KB-003/005); kaynak atfı (FR-KB-006); anti-hallucination (FR-KB-007) | SEC-13 | Orta |
| **TM-T-07** | Network MITM ile medya/mesaj kurcalama | TB-1..TB-4 / A1 | 1×3=3 | TLS 1.2+ her yerde, SRTP medya (SAD §14.2) | SEC-06 | Düşük |

### 6.3 Repudiation (İnkâr)

| ID | Tehdit | TB/Varlık | L×I | Mevcut önlem | Yeni (SEC) | Kalıntı |
|----|--------|-----------|-----|--------------|-----------|---------|
| **TM-R-01** | Operatörün break-glass içerik erişimini inkârı | TB-6 / A2-A4 | 2×3=6 | Break-glass tam-audit router; gerekçe kodu + tenant bildirimi (FR-IAM-009/010, SAD §14.4.2) | SEC-10, SEC-14 | Düşük |
| **TM-R-02** | Kullanıcı kritik işlemi (ödeme/değişiklik) yaptığını inkâr eder | TB-3/TB-7 / A9 | 2×2=4 | Teyit + audit log (BRD §13 madde 3/4/6); correlation_id tool izleme (FR-TOOL-010) | SEC-10 | Düşük |
| **TM-R-03** | Müşteri çağrıda onay verdiğini inkâr eder (consent/işlem) | TB-1 / A2 | 2×2=4 | Kayıt + transkript + timeline (BRD §8.1); consent kaydı (FR-OUT-003) | SEC-14 | Düşük |
| **TM-R-04** | Outbound çağrıda izin (consent) kaydının inkârı/eksikliği | TB-3 / A10 | 2×3=6 | Consent Engine ön-kontrol + kaynak/tarih/kapsam kaydı (SAD §19.1, FR-OUT-003) | SEC-14 | Düşük |

### 6.4 Information Disclosure (Bilgi İfşası)

| ID | Tehdit | TB/Varlık | L×I | Mevcut önlem | Yeni (SEC) | Kalıntı |
|----|--------|-----------|-----|--------------|-----------|---------|
| **TM-I-01** | Cross-tenant veri okuma (en kritik multi-tenant tehdit) | TB-5 / A2-A7 | 2×3=6 | RLS + tenant context + per-tenant KMS key + izolasyon testi (SAD §13, BRD §19/8-9) | SEC-07, SEC-15 | Düşük |
| **TM-I-02** | L0 platform rolü tenant içeriğini (transkript/kayıt/PII) görür — altın kural ihlali | TB-6 / A2-A4 | 2×3=6 | Plane separation (ADR-011); L0 iş-verisi repo bağımsız (FR-IAM-008); Tier B break-glass (FR-IAM-009/010) | SEC-14, SEC-16 | Düşük |
| **TM-I-03** | PII/kart/OTP'nin kayıt veya transkripte sızması | TB-1 / A5 | 2×3=6 | PII redaction pipeline (async); kart/parola/OTP çıkarma (FR-REC-004/005); DTMF masking (PCI, BRD §8.5) | SEC-17 | Orta |
| **TM-I-04** | Hassas içeriğin LLM/STT sağlayıcı loglarına gitmesi (3rd party retention) | TB-2 / A4 | 2×3=6 | No-train default + no-log (FR-LLM-012/FR-KB-010); region pinning (NFR 10.7); adapter retention control (SAD §8) | SEC-06, SEC-18 | Orta |
| **TM-I-05** | Prompt injection ile system prompt / başka müşteri verisi sızdırma | TB-1 / A6 | 3×3=9 | Input guard prompt-injection tespiti (FR-LLM-007); output guard (FR-LLM-009); session izolasyon | SEC-09 | Orta |
| **TM-I-06** | Hata mesajı/stack trace ile iç detay sızıntısı | TB-7/TB-8 / A13 | 2×2=4 | RFC 9457 sızıntısız hata modeli + kararlı `code` (API.md §4, FR-TOOL-008) | SEC-19 | Düşük |
| **TM-I-07** | Secrets/API key/KMS anahtar sızıntısı (kod/log/config'te) | TB-9 / A8 | 2×3=6 | Secrets Manager, runtime kısa ömürlü token (SAD §14.2); CLAUDE.md: secret üretme/yazma yasağı | SEC-12, SEC-20 | Orta |
| **TM-I-08** | Panelde PII'nin yetkisiz görüntülenmesi (maskeleme eksikliği) | TB-7 / A4 | 2×2=4 | Panel görüntülemede redaction/maskeleme (BRD §17.7); `*:own` scope (SAD §14.4.3) | SEC-17 | Düşük |
| **TM-I-09** | Semantic/TTS cache üzerinden PII çapraz-sızıntısı | TB-4 / A4 | 1×3=3 | PII cache'lenmez; yalnız yan-etkisiz turlar (FR-LLM-014/FR-RES-004); cache tenant namespace | SEC-15 | Düşük |
| **TM-I-10** | Residency ihlali — veri yanlış bölgede işlenir/saklanır | TB-2 / A2-A4 | 1×3=3 | Home-region eşleme + bölge zorlama; adapter region selection (NFR 10.7, SAD §12.3) | SEC-18 | Düşük |

### 6.5 Denial of Service (Hizmet Engelleme)

| ID | Tehdit | TB/Varlık | L×I | Mevcut önlem | Yeni (SEC) | Kalıntı |
|----|--------|-----------|-----|--------------|-----------|---------|
| **TM-D-01** | SIP/RTP flood, telefoni edge DoS | TB-1 / A14 | 2×3=6 | SBC DDoS/SIP saldırı koruması (FR-TEL-002, NFR 10.6) | SEC-02 | Düşük |
| **TM-D-02** | Public API / panel volumetric DoS | TB-8 / A13 | 2×2=4 | WAF/DDoS + rate limit + IP allowlist + private endpoint (NFR 10.6); token-bucket (API.md §4) | SEC-04 | Düşük |
| **TM-D-03** | Noisy neighbor — bir tenant kaynakları tüketir, diğerlerini etkiler | TB-5 / A13 | 2×2=4 | Quota service (concurrency/CPS/vCPU); fair scheduling; backpressure/admission control (FR-TEN-006/007, FR-RES-014, NFR 10.3) | SEC-15 | Düşük |
| **TM-D-04** | Sağlayıcı kesintisi/latency spike ile hizmet bozulması | TB-2 / A1 | 2×2=4 | Adapter fallback + circuit breaker + deterministic flow (SAD §8.3, FR-STT-008/FR-TTS-008/FR-LLM-010) | — | Düşük |
| **TM-D-05** | LLM token/maliyet bombardımanı (uzun prompt/loop ile maliyet DoS) | TB-1 / A12 | 2×2=4 | Token trimming + özetleme (FR-KB-011/FR-LLM-005); per-call kaynak bütçesi (FR-RES-016); bütçe alarmı (FR-BIL-006) | SEC-08 | Orta |
| **TM-D-06** | Bölge arızasında çağrı kaybı | TB-1 / A1 | 1×3=3 | Multi-AZ + bölgesel DR failover + callback (SAD §18, NFR 10.5) | — | Düşük |
| **TM-D-07** | Redaction/analytics async kuyruğu doldurma (geri basınç) | TB-4 / A3 | 1×2=2 | Async batch + backpressure (FR-RES-011/014); Kafka replay (ADR-007) | — | Düşük |

### 6.6 Elevation of Privilege (Yetki Yükseltme)

| ID | Tehdit | TB/Varlık | L×I | Mevcut önlem | Yeni (SEC) | Kalıntı |
|----|--------|-----------|-----|--------------|-----------|---------|
| **TM-E-01** | L2 kullanıcısı L1/L0 yetkisine yükselir (panel sınırı atlama) | TB-6/TB-7 / A11 | 2×3=6 | Ayrı router ağaçları + ayrı OAuth scope + ayrı deploy (SAD §14.4.2, ADR-011); yetki kararı backend'de | SEC-16 | Düşük |
| **TM-E-02** | Scope atlatma — `operations_manager@brandX` başka markaya erişir | TB-5 / A2 | 2×2=4 | Scoped assignment guard; permission-key + scope kaynak attribute doğrulama (FR-IAM-011, ADR-012) | SEC-07 | Düşük |
| **TM-E-03** | `*:own` kontrolü atlatma (human_agent başkasının çağrısına erişir) | TB-7 / A3 | 2×2=4 | `*:own` sahiplik kontrolü backend'de (SAD §14.4.3) | SEC-16 | Düşük |
| **TM-E-04** | Tenant IdP'sinin L0 platform rolü ataması (federasyon sınırı) | TB-6 / A11 | 1×3=3 | L0 ayrı IdP/dizinden federe; tenant IdP L0 rolü atayamaz (FR-IAM-008, SAD §14.4.4) | SEC-16 | Düşük |
| **TM-E-05** | Break-glass token'ın süre/kapsam ötesi kullanımı (standing access) | TB-6 / A11 | 2×3=6 | Süreli token (60dk default, max 4sa, auto-expiry, standing access yok); maker-checker (FR-IAM-009) | SEC-14 | Düşük |
| **TM-E-06** | SSRF — tool/webhook ile iç ağ/metadata endpoint'e erişim | TB-3 / A8 | 2×3=6 | Endpoint allowlist (onaysız endpoint engelleme, FR-TOOL-012); Integration GW | SEC-06, SEC-20 | Orta |
| **TM-E-07** | LLM tool çağrısı ile yetki dışı tool tetikleme | TB-3 / A4 | 2×3=6 | Tool authorization (agent scope, read/write seviyesi, FR-TOOL-004/005) | SEC-08 | Düşük |
| **TM-E-08** | Container/runtime kaçışı ile yan-tenant erişimi | TB-5 / A2 | 1×3=3 | Namespace stratejisi; dedicated tenant opsiyonu (FR-TEN-005); en-az-yetki workload kimliği | SEC-15 | Orta |

---

## 7. LLM/Voice'a Özgü Tehditler (genişletme)

STRIDE'ı sesli LLM platformunun benzersiz risklerine bağlayan, OWASP LLM Top-10 ve OWASP ML ile hizalı genişletme. (Çoğu §6'da bir STRIDE girdisine eşlenir.)

| Tehdit | STRIDE eşlemesi | Ana önlem |
|--------|------------------|-----------|
| Prompt injection (direct/indirect) | TM-T-02b, TM-I-05 | Input/output Policy Engine (FR-LLM-007/009), sabit system prompt, KB içeriği güvensiz girdi sayılır |
| Insecure output handling (yanıt → eylem) | TM-T-02, TM-E-07 | Schema-validated tool call (FR-LLM-008); serbest metinle yan etki yok; deterministic workflow |
| Sensitive info disclosure (model yan kanal) | TM-I-04, TM-I-05 | No-train/no-log, redaction-before-send, session izolasyon |
| Training-data/model poisoning (3rd party) | TM-S-06, TM-T-06 | No-train default; managed model; KB versiyonlama + kaynak atfı |
| Hallucination → yanlış işlem | TM-T-02b | Anti-hallucination policy (FR-KB-007), RAG kaynak atfı, "uydurma yok → teyit/aktar/ticket" |
| Deceptive impersonation (AI gizleme) | TM-S-07, uyum | AI bildirimi zorlama (BRD §14.2); no-deceptive-impersonation policy |
| Excessive agency (aşırı tool yetkisi) | TM-E-07 | Tool scope + read/write seviyesi + step-up + insan onayı (BRD §13) |
| Deepfake/ses klonlama | TM-S-07 | Ses tek delil değil; çok faktörlü auth; onaylı ses kullanım kaydı (FR-TTS-006/007) |
| DTMF/sesle kart verisi yakalama | TM-I-03 | DTMF masking, PCI akışı (kart LLM/transkript/kayıt dışı, BRD §8.5) |

---

## 8. Risk Isı Haritası ve Öncelikli Tehditler

**Kritik/Yüksek (skor 6–9) — Faz 1 önlem zorunlu:**

| Tehdit | Skor | Konu |
|--------|------|------|
| TM-S-01 | 9 | Caller ID spoof → hesap ele geçirme |
| TM-T-02b | 9 | Prompt injection → policy atlatma |
| TM-I-05 | 9 | Prompt injection → veri sızıntısı |
| TM-S-02..06, TM-T-01/02/04/05, TM-R-01/04, TM-I-01/02/03/04/07, TM-D-01, TM-E-01/05/06/07 | 6 | Spoof/tamper/cross-tenant/içerik sızıntısı/SSRF/break-glass/yetki |

**Net gözlem:** En yüksek skorlu üç tehdit **prompt injection** ve **çağrı içi kimlik** etrafında yoğunlaşıyor — yani sesli LLM'in iki benzersiz saldırı yüzeyi. Bunlar Policy Engine (3.3) ve çağrı içi auth (8.x) WBS kalemlerinde Faz 1 `Must`. Multi-tenant izolasyon (TM-I-01/TM-T-01) ve altın kural (TM-I-02) ise platformun B2B2B güven modelinin temelidir; her ikisi de RLS+plane separation+break-glass ile çok katmanlı savunulur.

**Faz dağılımı:** §6 tehditlerinin önlemlerinin büyük kısmı F1'de aktif (auth, policy, RLS, redaction, fallback); break-glass tam akışı F2 (12.3); container izolasyon sertleştirme ve BYOK F3.

---

## 9. Güvenlik Tasarımı Derinleştirme (SEC-01..SEC-20)

SAD §14.2 defense-in-depth tablosunu tehdit-bazlı somut kontrollere indirir. Her kontrol mevcut bir mimari kararı **derinleştirir** veya yeni bir tasarım gereği ekler; ilgili WBS kalemine bağlanır. (Bunlar tasarım kontrolleridir; FR değildir — gerekirse BRD/SRS'e yeni FR olarak işlenmeleri 0.1.6 ve sonrası kararıdır.)

| ID | Kontrol (derinleştirme) | Karşıladığı tehdit | WBS / iz |
|----|--------------------------|--------------------|----------|
| **SEC-01** | Hassas işlem öncesi **zorunlu step-up + risk-bazlı eşik** (işlem tutarı/türüne göre); Caller ID asla tek delil; başarısız denemede progresif gecikme + kilit | TM-S-01/07 | 8.2/8.3/8.4 (FR-AUTH-*) |
| **SEC-02** | SBC'de **SIP rate limit + geo/ASN allowlist + anomaly tespiti**; toll-fraud için destinasyon allowlist + harcama eşiği alarmı | TM-S-02, TM-D-01 | 2.1.1 (FR-TEL-002) |
| **SEC-03** | Panel/API için **phishing-resistant MFA** (WebAuthn/FIDO2) önerisi; oturum binding (device/IP), kısa erişim + döner refresh token; anormal oturum sonlandırma | TM-S-03/04 | 12.1.5 (FR-IAM-003) |
| **SEC-04** | Public API'de **tenant+client bazlı kota + token-bucket + adaptive throttling**; key rotation politikası + scope-minimizasyon; key sızıntısı tespiti | TM-S-04, TM-D-02 | API.md §4; 7.x |
| **SEC-05** | Webhook **imza + timestamp + nonce replay reddi**; alıcı tarafta idempotent tüketim; imza anahtarı rotasyonu | TM-S-05 | API.md §10 (FR-TOOL-011) |
| **SEC-06** | Giden bağlantılarda **TLS pinning/mTLS + sertifika doğrulama**; egress yalnız allowlist üzerinden (egress proxy); iç metadata endpoint engeli | TM-S-06, TM-T-07, TM-I-04, TM-E-06 | 4.1.x; 17.1.1 (NFR 10.6) |
| **SEC-07** | **RLS + uygulama katmanı tenant guard çift kontrol** (defense in depth); negatif test (cross-tenant erişim reddi) CI'da zorunlu; scope attribute her sorguda | TM-T-01, TM-I-01, TM-E-02 | 1.2.1/12.2.3 (FR-TEN-002); 18.9 |
| **SEC-08** | Tool çağrısında **parametre allowlist + değer aralığı + tutar/limit policy**; yüksek-etkili işlemde deterministic workflow + insan onayı zorunlu; per-call token/maliyet tavanı | TM-T-02, TM-D-05, TM-E-07 | 7.1.1/7.3 (FR-TOOL-002/004/005, BRD §13) |
| **SEC-09** | **Çok katmanlı prompt-injection savunması**: input sınıflandırıcı + delimiter/spotlighting + KB/tool çıktısı "güvensiz" işaretleme + output guard + canary/leak tespiti; jailbreak regresyon test seti | TM-T-02b, TM-I-05 | 3.3.1/3.3.2 (FR-LLM-007/009); 18.8 |
| **SEC-10** | **Audit bütünlüğü**: WORM + hash zincirleme (tamper-evident) + ayrı erişim domeni; saat senkronu; audit'in kendisi de en-az-yetki | TM-T-03, TM-R-01/02 | 12.1.8 (FR-IAM-006) |
| **SEC-11** | Agent/prompt değişiminde **maker-checker + imzalı sürüm + otomatik regression gate + tek-tık rollback**; prod promotion için ayrı yetki | TM-T-04 | 20.1 (FR-AGT-005/006, FR-TST-004) |
| **SEC-12** | **Güvenli tedarik zinciri**: SBOM + imzalı artifact (provenance/SLSA), pinned dependency, imaj imzalama + admission control; secret scanning (pre-commit + CI) | TM-T-05, TM-I-07 | 0.4.4/17.1.5 (NFR 10.6) |
| **SEC-13** | KB ingest'te **kaynak güveni + içerik sanitizasyonu**; retrieval'da kaynak atfı zorunlu; KB içeriği prompt'a "veri" olarak (talimat değil) enjekte edilir | TM-T-06 | 6.1.x (FR-KB-003/005/006/007) |
| **SEC-14** | **Break-glass sertleştirme**: maker≠checker, time-boxed, gerekçe kodu, tenant bildirimi, oturum kaydı/ekran izleme, otomatik expiry + erişilen kayıt listesi audit'e; regüle tenant tenant-onay toggle | TM-R-01/03/04, TM-I-02, TM-E-05 | 12.3.x (FR-IAM-009/010, ADR-013) |
| **SEC-15** | **Tenant izolasyon sertleştirme**: per-tenant KMS key (crypto-shredding), cache/queue tenant namespace, workload identity, dedicated tenant opsiyonu; noisy-neighbor fair scheduling | TM-I-01/09, TM-D-03, TM-E-08 | 1.2.x/16.8 (FR-TEN-005/006/007) |
| **SEC-16** | **Plane/panel izolasyon zorlama**: L0 ayrı deploy/origin/realm; her endpoint panel+rol+tenant+scope guard; `*:own` sahiplik kontrolü; deny-by-default; L0↔tenant federasyon ayrımı | TM-I-02, TM-E-01/03/04 | 12.2.x (SAD §14.4.2, ADR-011) |
| **SEC-17** | **PII redaction sertleştirme**: gerçek zamanlı kart/OTP/parola maskeleme (kayıt/transkript öncesi), panel görüntülemede maskeleme + reveal audit; redaction doğrulama test seti; PCI DTMF masking | TM-I-03/08 | 11.4/11.5/13.1.4 (FR-REC-004/005, BRD §8.5/§17.7); 18.11 |
| **SEC-18** | **Residency + 3rd-party veri minimizasyon**: adapter region pinning + retention=0/no-log; gönderilen veri kaydı (DPA/alt-işleyen); hassas doküman sağlayıcı loguna gitmez | TM-I-04/10 | 4.1.4 (NFR 10.7, FR-LLM-012/FR-KB-010) |
| **SEC-19** | **Sızıntısız hata yüzeyi**: RFC 9457 + kararlı `code`; iç detay/stack trace yalnız korelasyon-id ile sunucu-taraf logda; müşteriye teknik detay yok | TM-I-06 | API.md §4 (FR-TOOL-008) |
| **SEC-20** | **Secrets yönetimi + en-az-yetki**: merkezi Secrets Manager/KMS, runtime kısa ömürlü token, otomatik rotasyon, BYOK iskeleti; workload başına minimum IAM; egress kontrol | TM-I-07, TM-E-06 | 0.4.5/17.1.2/17.1.3 (NFR 10.6) |

---

## 10. Önerilen Yeni Mimari Kararlar (ADR)

Tehdit modeli, mevcut ADR-001..013'e ek olarak aşağıdaki kararların açılmasını önerir (numaralandırma son ADR'den devam eder; **karar bekliyor**, ADR sürecinde — 0.1.8 — formelleştirilir):

| ADR | Konu | Tetikleyen tehdit | Önerilen yön |
|-----|------|--------------------|---------------|
| **ADR-014** | Zorunlu egress kontrol katmanı (egress proxy + allowlist) — tüm giden bağlantılar | TM-E-06 (SSRF), TM-I-04 | Tüm data plane egress'i denetimli proxy üzerinden; iç metadata/RFC1918 engeli varsayılan |
| **ADR-015** | Prompt-injection savunma mimarisi (katmanlı; LLM-as-judge guard opsiyonu vs deterministik) | TM-T-02b, TM-I-05 | Input sınıflandırıcı + spotlighting + output guard; ek-LLM guard maliyet/gecikme dengesi PoC'a tabi |
| **ADR-016** | Audit log tamper-evidence yöntemi (hash zinciri vs harici WORM/ledger) | TM-T-03 | Hash zincirleme + periyodik dış mühürleme; maliyet/uyum dengesi |
| **ADR-017** | Phishing-resistant MFA zorunluluğu (WebAuthn/FIDO2) — özellikle L0/break-glass | TM-S-03, TM-E-05 | L0 ve break-glass onaylayıcıları için zorunlu; tenant için politika-konfigüre |

> Bu öneriler `docs/SAD.md` §22 ADR tablosuna eklenmeden önce 0.1.8 ADR sürecinde değerlendirilir. SAD §24 risk tablosu bu tehdit modeline atıfla genişletilebilir.

---

## 11. İzlenebilirlik (FR/SR/SAD ↔ Tehdit ↔ Önlem)

Aşağıdaki tablo, en kritik gereksinim/mimari maddesini ilgili tehdit ve önleme bağlar. Tam FR↔SR↔TC↔WBS matrisi `docs/RTM.md`'dedir; bu tablo güvenlik kesitidir.

| Kaynak (FR/NFR/SAD/ADR) | İlgili tehdit | Önlem (mevcut + SEC) |
|--------------------------|---------------|----------------------|
| FR-AUTH-001/002/003/004 | TM-S-01/07 | Çağrı içi auth + step-up + limit · SEC-01 |
| FR-TEL-002, NFR 10.6 (SBC) | TM-S-02, TM-D-01 | SBC/anti-spoof/DDoS · SEC-02 |
| FR-IAM-002/003 (SSO/MFA) | TM-S-03 | SSO+MFA · SEC-03 |
| FR-IAM-006 (WORM audit) | TM-T-03, TM-R-* | Append-only audit · SEC-10 |
| FR-IAM-008 (L0 izolasyon) | TM-I-02, TM-E-04 | Plane separation · SEC-16 |
| FR-IAM-009/010, ADR-013 (break-glass) | TM-I-02, TM-R-01, TM-E-05 | Üç katmanlı break-glass · SEC-14 |
| FR-IAM-011, ADR-012 (scoped role) | TM-E-02, TM-E-03 | Scoped assignment guard · SEC-07/16 |
| FR-TEN-002 (RLS/tenant scope) | TM-T-01, TM-I-01 | RLS + çift kontrol · SEC-07/15 |
| FR-LLM-007/009 (policy guard) | TM-T-02b, TM-I-05 | Input/output guard · SEC-09 |
| FR-LLM-008/FR-TOOL-002 (schema tool) | TM-T-02, TM-E-07 | Schema-validated tool · SEC-08 |
| FR-LLM-012/FR-KB-010 (no-train/no-log) | TM-I-04 | 3rd-party veri minimizasyon · SEC-18 |
| FR-TOOL-012 (endpoint allowlist) | TM-E-06 | Allowlist + egress · SEC-06/20 |
| FR-REC-004/005, BRD §8.5 (redaction/PCI) | TM-I-03 | PII/kart redaction · SEC-17 |
| NFR 10.6 (SAST/DAST/SBOM) | TM-T-05, TM-I-07 | Tedarik zinciri · SEC-12/20 |
| NFR 10.7 (residency) | TM-I-10 | Region pinning · SEC-18 |
| ADR-011 (plane separation) | TM-E-01, TM-I-02 | Ayrı deploy/realm · SEC-16 |
| SAD §8.3 (fallback/circuit breaker) | TM-D-04 | Fallback + deterministic flow |
| NFR 10.5 (HA/DR) | TM-D-06 | Multi-AZ + failover |

---

## 12. Güvenlik Doğrulama (test eşlemesi)

Tehdit modeli, BRD §19 kabul kriterleri ve SRS/RTM test case'leriyle doğrulanır. Faz 1 kabul kapısı (todo Ek A) zaten kritik tehditleri kapsar:

| Doğrulama | Kapsadığı tehdit | Kaynak |
|-----------|-------------------|--------|
| Prompt injection / veri sızıntısı güvenlik testi | TM-T-02b, TM-I-05 | WBS 18.8, BRD §19(8) |
| Tenant izolasyon testi (cross-tenant yok) | TM-T-01, TM-I-01, TM-E-02 | WBS 18.9, BRD §19(9) |
| PII redaction testleri | TM-I-03/08 | WBS 18.11, BRD §19(13) |
| Outbound consent/opt-out doğrulama | TM-R-04 | WBS 18.12, BRD §19(14) |
| Düzenli penetration test (kritik bulgu yok kapısı) | tüm yüksek-skor | WBS 17.1.7, BRD §19(20) |
| Fallback uçtan uca testi | TM-D-04 | WBS 4.3.4, BRD §19(4) |
| SAST/DAST/dependency/SBOM (CI zorunlu) | TM-T-05, TM-I-07 | WBS 17.1.5/0.4.4 |

**Tehdit modeli bakım kuralı:** Yeni güven sınırı, yeni dış entegrasyon veya yeni veri akışı eklendiğinde bu doküman gözden geçirilir; yeni `TM-*` tehditleri ve gerekirse `SEC-*` kontrolleri eklenir (CLAUDE.md doküman bakım disiplini).

---

## 13. Açık Kararlar ve Sonraki Adımlar

**Açık kararlar (önlem detayını etkiler):**
- **ADR-014..017** (§10) — egress kontrol, prompt-injection mimarisi, audit tamper-evidence, MFA türü — 0.1.8 ADR sürecinde `docs/adr/`'de **Önerilen** durumla formelleştirildi (`0014`..`0017`); kabul süreci `docs/adr/README.md`.
- Prompt-injection için ek-LLM guard'ın gecikme/maliyet etkisi (ADR-015) → F0 PoC (0.3.x) girdisi; NFR 10.1 bütçesine sığmalı.
- BRD §22 açık kararları (PCI kapsamı, ilk sektör/ülke) → uygulanacak compliance profile ve sektörel kontroller (HIPAA/FCA/PCI) bu tehdit modelinin profil-özgü uzantısını belirler.
- BYOK/HSM kapsamı (F3) → SEC-15/SEC-20'nin nihai kripto-izolasyon modeli.

**Sonraki adımlar:**
1. **0.1.6 DPIA + compliance profile** — bu tehdit modeli DPIA'nın "riskler ve önlemler" bölümünün doğrudan girdisidir; profil parametreleri (TR/UK/EU/ME) tehditlerin yasal boyutunu (KVKK/UK GDPR/EU AI Act) bağlar.
2. **SAD güncellemesi** — §24 risk tablosuna bu dokümana atıf; §22'ye ADR-014..017 (kabul edilirse).
3. **Faz 1 güvenlik kontrollerinin uygulanması** — SEC-01..20'nin WBS kalemlerine (§9 iz sütunu) gömülmesi; CI'da negatif/güvenlik testleri (SEC-07/09/12).
4. **Threat model'i yaşayan belge tut** — her mimari değişiklikte gözden geçir (§12 bakım kuralı).

> Bu tehdit modeli, BRD'nin "compliance by design / observable by default / deterministic actions" prensiplerini saldırgan bakış açısıyla doğrular: en yüksek riskler **prompt injection**, **çağrı içi kimlik** ve **multi-tenant/altın kural izolasyonu** etrafında yoğunlaşır; her biri mevcut mimaride çok katmanlı savunulur ve §9'daki SEC kontrolleriyle derinleştirilir.
