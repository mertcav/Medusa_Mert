# Çözüm Mimarisi Dokümanı (SAD)
## Kurumsal Sesli Yapay Zekâ Asistanı Platformu — Enterprise Voice AI Agent Platform

**Solution Architecture Document**
STT · LLM · TTS Gerçek Zamanlı Orkestrasyonu · Multi-Tenant · Vendor-Neutral · Lean Runtime

> RMC TECHNOLOGY & CONSULTANCY — rmctech.co.uk

---

## Doküman Bilgileri

| Alan | Değer |
|------|-------|
| Doküman Adı | Enterprise Voice AI Agent Platform — Çözüm Mimarisi Dokümanı |
| Doküman Tipi | Solution Architecture Document (SAD) |
| Bağlı Doküman | `docs/BRD.md` (Sürüm 2.1, 13.06.2026) |
| Sürüm | 1.1 (Panel Mimarisi & AuthZ) |
| Tarih | 13 Haziran 2026 |
| Durum | İncelemeye Hazır — Karar Bekleyen Maddeler İşaretli |
| Gizlilik | Gizli — Yalnızca yetkili paydaşlar |

### Sürüm Geçmişi

| Sürüm | Tarih | Açıklama |
|-------|-------|----------|
| 1.0 | 13.06.2026 | BRD v2.0'a dayalı ilk çözüm mimarisi: mantıksal/fiziksel mimari, bileşen tasarımı, teknoloji önerileri, ADR'ler, gecikme bütçesi. |
| 1.1 | 13.06.2026 | BRD v2.1 uyumu: §14.4 Panel Mimarisi ve Yetkilendirme (L0/L1/L2) eklendi — Next.js route group'ları, FastAPI panel+rol+tenant guard'ları, permission-key tabanlı RBAC, SSO/SCIM rol eşleme. İki düzlemli panel dağıtımı (L0 internal-only Control Plane / L1+L2 public), üç katmanlı break-glass ve scoped role assignment kararları işlendi. Yeni ADR'ler: ADR-011 (iki düzlemli dağıtım), ADR-012 (sabit rol bundle + scoped assignment), ADR-013 (üç katmanlı break-glass). Teknoloji yığını panel düzlemi için Next.js + FastAPI olarak netleştirildi. |

---

## İçindekiler

1. Giriş ve Amaç
2. Mimari Sürücüler ve Kısıtlar (BRD İzlenebilirliği)
3. Mimari Prensipler
4. Mimari Genel Görünüm (C4 — Bağlam ve Konteyner)
5. Mantıksal Mimari ve Katmanlar
6. Conversation Orchestrator (Çekirdek IP)
7. Gerçek Zamanlı Medya ve Telefoni Katmanı
8. Sağlayıcı Soyutlama Katmanı (Provider Adapters)
9. LLM Orkestrasyonu (Routing · Tiering · Semantic Cache)
10. Bilgi Tabanı ve RAG Mimarisi
11. Tool Yürütme ve Kurumsal Entegrasyon
12. Veri Mimarisi (Depolama · Veri Modeli · Yerleşim)
13. Çok Kiracılılık (Multi-Tenancy) ve İzolasyon
14. IAM ve Güvenlik Mimarisi (14.4 Panel Mimarisi & AuthZ — L0/L1/L2)
15. Kaynak Verimliliği Mimarisi (Lean Runtime · Resource Manager)
16. Ölçeklenebilirlik ve Dağıtım Topolojisi
17. Gözlemlenebilirlik ve İzlenebilirlik
18. Yüksek Erişilebilirlik ve Felaket Kurtarma
19. Uyumluluk Mimarisi
20. Gecikme Bütçesi (Latency Budget)
21. Teknoloji Yığını Önerileri
22. Mimari Karar Kayıtları (ADR)
23. BRD Açık Kararlarına Mimari Yanıtlar
24. Mimari Riskler ve Önlemler
25. Sonraki Adımlar

---

## 1. Giriş ve Amaç

Bu doküman, `docs/BRD.md`'de tanımlanan iş gereksinimlerini uygulanabilir bir çözüm mimarisine dönüştürür. SAD; sistemin mantıksal ve fiziksel yapısını, ana bileşenlerini, bunların sorumluluklarını ve etkileşimlerini, veri akışlarını, teknoloji seçimlerini ve kritik mimari kararları tanımlar.

**Kapsam:** Tüm platform — voice runtime, conversation orchestration, sağlayıcı soyutlama, kurumsal entegrasyon, güvenlik/uyumluluk, gözlemlenebilirlik ve operasyon.

**Hedef kitle:** Çözüm/yazılım mimarları, kıdemli geliştiriciler, DevOps/SRE, güvenlik ve uyum ekipleri, ürün yönetimi.

**SAD'ın yanıtladığı temel soru:** "BRD'deki iki mandayı — *insan benzeri düşük gecikme* ve *yüksek yoğunluklu düşük kaynak tüketimi* — aynı anda nasıl sağlarız?"

Mimarinin merkezi tezi BRD ile aynıdır: **STT/LLM/TTS servislerini doğrudan birbirine bağlamak yerine, bunların üzerinde bağımsız, asenkron ve sağlayıcıdan bağımsız bir Conversation Orchestrator inşa etmek.** Ürünün fikrî mülkiyeti buradadır.

---

## 2. Mimari Sürücüler ve Kısıtlar (BRD İzlenebilirliği)

Aşağıdaki tablo, en kritik BRD gereksinimlerini onları karşılayan mimari mekanizmalara bağlar (tam izlenebilirlik SRS'te genişletilecektir).

| Mimari Sürücü | BRD Kaynağı | Karşılayan Mimari Mekanizma |
|---------------|-------------|------------------------------|
| Düşük gecikme (P95 ≤ 1.2 sn) | NFR 10.1, OBJ-14 | Uçtan uca streaming, edge VAD/endpointing, LLM/TTS first-token streaming, bölgesel edge, §20 gecikme bütçesi |
| Lean runtime / yüksek density | Prensip 5, FR-RES-*, NFR 10.2 | Asenkron olay-tabanlı runtime, oturum başına ~15MB hedefi, model tiering, TTS/semantic cache, scale-to-zero (§15) |
| Vendor-neutral | Prensip, OBJ-10, §12 | Provider Adapter SPI; STT/TTS/LLM/Telekom/VectorDB/CC adapter'ları (§8) |
| Multi-tenant izolasyon | FR-TEN-*, OBJ-12 | Tenant context propagation, veri/kota/anahtar izolasyonu, noisy-neighbor önleme (§13) |
| Human handoff by design | FR-HND-*, Prensip | Human Handoff Manager bileşeni + warm/cold/whisper transfer + bağlam aktarımı (§6.8, §7) |
| Deterministic actions | Prensip, FR-LLM-008, FR-TOOL-* | Policy Engine + schema-validated tool çağrıları + idempotency (§6.5, §11) |
| Observable by default | Prensip, §15 | correlation_id, OpenTelemetry trace/span, per-call metrik & maliyet (§17) |
| Graceful degradation | Prensip, FR-*-fallback | Adapter fallback, circuit breaker, deterministic flow fallback, backpressure (§8, §15) |
| Compliance by design | Prensip, §14 | Consent Engine, PII redaction pipeline, retention/legal hold, residency routing (§19) |
| Enterprise security | Prensip, NFR 10.6 | RBAC/SSO/MFA, BYOK, secrets manager, SBC, zero-trust ağ (§14) |

---

## 3. Mimari Prensipler

BRD Bölüm 5'teki ürün prensiplerini mimari prensiplere dönüştürüyoruz:

1. **Stream-first, buffer-never.** Hiçbir kritik yolda tam tampona alma yok. Tüm medya ve metin akışları parça parça (chunk) işlenir.
2. **Async, non-blocking, share-nothing-per-call.** Thread-per-call yasak. Oturumlar hafif asenkron görevler (async tasks / actors) olarak modellenir; tek bir worker binlerce oturumu I/O-bound olarak taşır.
3. **Orchestrator ortada, sağlayıcılar kenarda.** Orchestrator hiçbir somut sağlayıcıya bağımlı değildir; yalnızca adapter SPI'larına konuşur.
4. **Policy is code, actions are deterministic.** Para/PII/sözleşme etkileyen her işlem Policy Engine'den ve schema-doğrulamalı tool'dan geçer; serbest metinle yan etki üretilmez.
5. **Tenant is a first-class dimension.** Her istek, log, metrik ve veri satırı bir `tenant_id` taşır; izolasyon varsayılan, paylaşım istisnadır.
6. **Fail soft, never drop the call.** Her bağımlılığın fallback'i ve degrade modu vardır; çökme yerine kontrollü kalite düşüşü.
7. **Measure everything, cheaply.** Gözlemlenebilirlik birinci sınıf ama örneklemeli (sampling) ve asenkron — ölçüm kendisi runtime'ı yavaşlatmaz.
8. **Edge what's hot, centralize what's cold.** Gecikmeye duyarlı işler (VAD, echo, medya) edge'de; gerçek zamanlı olmayan işler (analitik, post-processing) merkezde batch.

---

## 4. Mimari Genel Görünüm (C4)

### 4.1 Sistem Bağlam Diyagramı (C4 — Level 1)

```
            ┌────────────────────────────────────────────────────────┐
   Son      │                                                        │
 Müşteri ──►│  PSTN / Mobil / SIP                                     │
 (telefon)  │         │                                              │
            │         ▼                                              │
            │   ┌──────────────────────────────────────────────┐    │
            │   │   ENTERPRISE VOICE AI AGENT PLATFORM          │    │
            │   │   (multi-tenant, multi-region)               │    │
   Yönetim  │   │                                              │    │
 Kullanıcı ►│   │   - Voice Runtime (inbound/outbound)         │    │
 (panel)    │   │   - Conversation Orchestrator                │    │
            │   │   - Management & Analytics Plane             │    │
   İnsan    │   │                                              │    │
 Temsilci ─►│   └──────────────────────────────────────────────┘    │
 (handoff)  │      │            │            │            │          │
            └──────┼────────────┼────────────┼────────────┼──────────┘
                   ▼            ▼            ▼            ▼
              Telekom      STT/TTS/LLM   Kurumsal      Contact
              Sağlayıcı    Sağlayıcılar  Sistemler     Centre
              (Twilio/SIP) (Deepgram/    (CRM/ERP/     (Genesys/
                          ElevenLabs/    Ödeme/Ticket) Avaya/Cisco)
                          OpenAI/...)
```

### 4.2 Konteyner Diyagramı (C4 — Level 2)

Platform üç ana **plane** (düzlem) etrafında yapılandırılır. Bu ayrım, gerçek zamanlı yolun (data plane) yönetim ve analitik yükünden izole edilmesini sağlar — lean runtime'ın temel mimari kararıdır.

```
┌──────────────────────────── DATA PLANE (gerçek zamanlı, lean) ───────────────────────────┐
│                                                                                          │
│  [Telephony Edge / SBC]  ──►  [Media Gateway]  ──►  [Conversation Orchestrator]           │
│        (SIP/RTP)              (VAD, echo,            (turn mgr, policy,                    │
│                               jitter, STT/TTS        LLM router, tools,                   │
│                               streaming, codec)      session memory)                      │
│                                     │                       │                            │
│                          [Provider Adapter Mesh]    [Tool Executor / Integration GW]      │
│                          (STT·TTS·LLM·Telekom)      (REST/SOAP/GraphQL/webhook)           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
        │ (events, async)                                   │ (sync, circuit-broken)
        ▼                                                   ▼
┌──────────────── CONTROL PLANE ────────────────┐   ┌──────── ENTERPRISE SYSTEMS ────────┐
│  Agent Config Service · Tenant Service ·       │   │  CRM · ERP · Ticketing · Payment · │
│  IAM/SSO · Prompt/Flow Registry · KB Service · │   │  Appointment · Customer DBs        │
│  Campaign Manager · Consent Engine ·           │   └────────────────────────────────────┘
│  Resource Manager (quota/autoscale/backpressure)│
└─────────────────────────────────────────────────┘
        │ (config pushed / pulled, cached at runtime)
        ▼
┌──────────────── ANALYTICS / OPS PLANE (async, batch) ───────────────┐
│  Event Stream (Kafka) · Stream Processor · Recording Pipeline ·     │
│  PII Redaction · Transcript Store · QA/Eval Engine · Analytics DB · │
│  Billing/Usage · Observability (OTel/Prometheus/Grafana) · Audit    │
└─────────────────────────────────────────────────────────────────────┘
```

**Tasarım kararı:** Data plane "hot path"tir ve mümkün olduğunca az iş yapar. Recording, transcription post-processing, analytics, QA, billing aggregation gibi her şey event stream üzerinden Analytics Plane'e iletilir ve **asenkron** işlenir (FR-RES-011). Bu, gerçek zamanlı yolu hafif tutar.

---

## 5. Mantıksal Mimari ve Katmanlar

BRD Bölüm 11'deki katmanlı modeli somut bileşenlere açıyoruz.

| Katman | Bileşenler | Sorumluluk | İlgili BRD FR |
|--------|-----------|-------------|----------------|
| L1 — Telephony Edge | SBC, SIP Gateway, Call Control | PSTN/SIP sonlandırma, çağrı kurulumu, DTMF, güvenlik (SIP saldırı) | FR-TEL-* |
| L2 — Media Gateway | VAD, Noise/Echo, Jitter Buffer, Streaming STT/TTS connector, TTS cache | Ses akışı işleme, edge VAD/endpointing, codec yönetimi | FR-RTC-*, FR-STT-*, FR-TTS-* |
| L3 — Conversation Orchestrator | Turn Manager, Session Memory, Policy Engine, LLM Router, Prompt Manager, RAG client, Tool Executor, Handoff Manager | Diyalog kontrolü, karar, orkestrasyon | FR-LLM-*, FR-KB-*, FR-TOOL-*, FR-HND-* |
| L4 — Provider Abstraction | STT/TTS/LLM/Telekom/VectorDB/CC adapter'ları | Sağlayıcı bağımsızlığı, fallback, metering | §12 BRD |
| L5 — Enterprise Integration | Integration Gateway, connector'lar | CRM/ERP/ödeme/ticket entegrasyonu | FR-TOOL-* |
| L6 — Control Plane | Tenant, Agent Config, IAM, Campaign, Consent, KB, Resource Manager | Konfigürasyon, yönetim, yetkilendirme, kota | FR-TEN-*, FR-IAM-*, FR-AGT-*, FR-OUT-* |
| L7 — Analytics/Ops | Event pipeline, Recording, Redaction, QA, Analytics, Billing, Observability, Audit | Raporlama, kalite, faturalama, denetim | FR-REC-*, FR-ANA-*, FR-BIL-* |
| X — Cross-cutting | Security, Audit, Config, Secrets, Service Mesh | Tüm katmanları keser | NFR 10.6 |

---

## 6. Conversation Orchestrator (Çekirdek IP)

Orchestrator, bir çağrı oturumunu (session) bir **durum makinesi (state machine) + olay döngüsü (event loop)** olarak yönetir. Her oturum hafif bir asenkron aktördür (örn. bir async task / lightweight actor) — kendi mailbox'ı vardır, paylaşılan kilit (lock) kullanmaz.

### 6.1 Oturum Yaşam Döngüsü (Turn State Machine)

```
        ┌─────────┐   speech_start    ┌──────────┐
   ┌───►│ LISTEN  │──────────────────►│ CAPTURE  │
   │    └─────────┘                   └────┬─────┘
   │         ▲                              │ endpoint (VAD)
   │  barge-in (cancel TTS)                 ▼
   │    ┌─────────┐   tts_chunk      ┌──────────┐  final transcript
   └────┤  SPEAK  │◄─────────────────┤  THINK   │◄─── STT final
        └─────────┘                  └────┬─────┘
              ▲                            │ tool needed
              │ response ready             ▼
              │                       ┌──────────┐
              └───────────────────────┤  ACT     │ (tool/RAG/policy)
                                      └──────────┘
   Her durumdan ──► TRANSFER / END (policy veya kullanıcı tetikli)
```

- **LISTEN:** STT partial'ları izlenir; agent konuşmuyor.
- **CAPTURE:** Kullanıcı konuşuyor; edge VAD endpointing'i bekler (FR-RTC-004). Ölü hava STT'ye gönderilmez (FR-RES-009).
- **THINK:** Final transcript → Policy pre-check → LLM Router → (gerekirse) RAG/Tool → yanıt planı.
- **ACT:** Schema-validated tool çağrısı, idempotency key ile (FR-TOOL-003/009).
- **SPEAK:** TTS streaming; ilk chunk gelir gelmez çalınır. **Barge-in** anında SPEAK→CAPTURE geçişi yapar ve TTS ≤200ms içinde kesilir (FR-RTC-002, NFR 10.1).

### 6.2 Alt Bileşenler

| Bileşen | Sorumluluk | Kritik tasarım notu |
|---------|-----------|---------------------|
| **Turn Manager** | Yukarıdaki state machine, turn-taking, barge-in koordinasyonu | Tüm geçişler olay-tetikli; bloklayan çağrı yok |
| **Session Memory** | Kısa süreli diyalog belleği, özetleme | Token sınırına gelince özetler (FR-LLM-005); bellekte tutar, oturum sonunda kalıcılaştırılır |
| **Policy Engine** | Davranış kuralları, yasak işlemler, prompt-injection guard, çıktı denetimi | Hem girişte (input guard) hem çıkışta (output guard) çalışır; deterministic, LLM-bağımsız (BRD §13) |
| **LLM Router** | Model tiering, cost/latency/risk routing, semantic cache, fallback | §9'da detaylı |
| **Prompt Manager** | Versiyonlu system prompt + flow node'ları enjekte eder | System prompt değişmezdir; kullanıcı içeriği prompt'u değiştiremez (FR-LLM-006) |
| **RAG Client** | KB Service'ten retrieval, top-k trimming | §10'da detaylı |
| **Tool Executor** | Schema validation, timeout/retry/circuit-breaker/idempotency | §11'de detaylı |
| **Handoff Manager** | Transfer kararı, hedef seçimi, bağlam paketi üretimi | §7'de detaylı |

### 6.3 Eşzamanlılık Modeli

- Her oturum = bir asenkron görev. Worker, bir olay döngüsü üzerinde N oturumu çoğullar (multiplex).
- CPU-bound iş (ör. yerel VAD, codec) ayrı thread pool / native koda offload edilir; orchestrator olay döngüsünü bloklamaz.
- Oturum durumu bellekte küçük tutulur (~15MB hedefi, FR-RES-016) — büyük tamponlar Media Gateway'de, ham veri Analytics Plane'de.

---

## 7. Gerçek Zamanlı Medya ve Telefoni Katmanı

### 7.1 Çağrı Kurulumu ve Medya Akışı

```
PSTN ──SIP/SDP──► SBC ──SIP──► SIP App Server ──► Media Gateway
                  (güvenlik,      (call control,    (RTP terminate,
                   topology hide)  routing)          codec, jitter)
                                                          │
                                          PCM/Opus frames │ (WebSocket / gRPC stream)
                                                          ▼
                                                  Streaming STT adapter
                                                          │ partial/final
                                                          ▼
                                                  Conversation Orchestrator
                                                          │ text response (stream)
                                                          ▼
                                                  Streaming TTS adapter (+cache)
                                                          │ audio chunks
                                                          ▼
                                                  Media Gateway ──RTP──► çağrı
```

### 7.2 Tasarım Kararları

- **Telefoni soyutlaması:** Hem managed CPaaS (Twilio/Telnyx — Media Streams / WebSocket) hem ham SIP trunk (BYOC) desteklenir. SBC, SIP saldırılarına (NFR 10.6) ve topoloji gizlemeye hizmet eder (FR-TEL-002/003).
- **Codec & sampling:** Telefoni 8 kHz (G.711/Opus narrowband). Gereksiz resampling/transcoding zincirden çıkarılır (FR-RES-008). STT/TTS adapter'ları mümkünse 8 kHz native çalışır; değilse tek bir kontrollü resample noktası.
- **Edge VAD/endpointing:** Media Gateway'de yapılır (FR-RTC-013, FR-RES-009). Ölü hava ve agent'ın kendi sesi (echo) STT'ye gönderilmez (FR-RTC-006).
- **Barge-in:** Media Gateway, kullanıcı sesi algıladığında orchestrator'a `barge_in` olayı gönderir; orchestrator TTS akışını iptal eder, gateway buffer'daki agent sesini ≤200ms içinde keser.
- **DTMF:** RFC 2833 / SIP INFO ile algılama ve üretim (FR-TEL-006).
- **Medya işleme konumu (AÇIK KARAR — ADR-009):** Edge'de mi merkezde mi? §23'te ele alındı.

### 7.3 Human Handoff Akışı

```
Orchestrator (transfer kararı)
   │ bağlam paketi: özet + intent + toplanan alanlar + auth durumu
   ▼
Handoff Manager ──► hedef seçimi (departman/skill/kuyruk)
   │
   ├─ COLD: SIP REFER → CC'ye yönlendir, oturum kapanır
   ├─ WARM: agent köprülenir, AI temsilciye whisper ile özet verir, sonra çıkar
   └─ WHISPER: yalnız temsilciye duyulan brifing
   │
   └─ temsilci yoksa ──► callback / voicemail / ticket (FR-HND-007)
```

Bağlam paketi CC'ye hem ekran-pop (screen-pop) verisi (CTI/CRM üzerinden) hem de transkript özeti olarak iletilir (FR-HND-004/005).

---

## 8. Sağlayıcı Soyutlama Katmanı (Provider Adapters)

### 8.1 Adapter SPI (Service Provider Interface)

Her kategori için ortak bir arayüz tanımlanır. Orchestrator yalnızca bu arayüze bağımlıdır.

```
interface SttAdapter {
   stream(audioIn): AsyncStream<Transcript{ partial, final, confidence, words }>
   capabilities(): { languages, sampleRates, features }
   health(): HealthStatus
   meter(): UsageRecord       // cost calculation, dakika/karakter/token
}
interface TtsAdapter {
   synthesize(textStream, voiceProfile): AsyncStream<AudioChunk>  // first-byte hızlı
   cancel()                                                       // barge-in
   ...
}
interface LlmAdapter {
   complete(messages, tools, opts): AsyncStream<Token | ToolCall>
   ...
}
interface TelephonyAdapter { dial(), answer(), transfer(), sendDtmf(), ... }
```

### 8.2 Adapter Ortak Yetenekleri (BRD §12 zorunlu)

Her adapter şunları sağlar: connection & auth, timeout, retry (backoff + jitter), **circuit breaker**, health check, usage metering, cost calculation, region selection, data retention control, **fallback**, ve **provider-specific error normalization** (sağlayıcı hatalarını ortak hata taksonomisine çevirir).

### 8.3 Fallback ve Routing Stratejisi

```
Primary adapter ──(timeout/error/circuit-open)──► Secondary adapter ──► Deterministic flow
```

- **STT fallback:** Birincil STT akışı hata/timeout verirse ikincil STT'ye geçiş; mümkünse kısmi audio tekrar gönderimi (FR-STT-008).
- **TTS fallback:** Sağlayıcı düşerse alternatif TTS; ses karakteri tutarlılığı için tenant başına önceden tanımlı eşdeğer ses (FR-TTS-008/009).
- **LLM fallback:** Fallback model veya deterministic flow (FR-LLM-010).
- **Kabul kriteri:** Her kategoride ≥2 sağlayıcı ve birincil kesintide kontrollü fallback (BRD §19, madde 1-4).

### 8.4 Önerilen İlk Sağlayıcılar (vendor eval'a tabi — ADR-002)

| Kategori | İlk öneri (Faz 1) | İkincil/fallback |
|----------|-------------------|------------------|
| Telekom | Twilio (Media Streams) | Telnyx / SIP trunk |
| STT | Deepgram (streaming, düşük gecikme) | Google / Azure |
| TTS | ElevenLabs (kalite) veya Cartesia (gecikme) | Azure TTS |
| LLM (büyük) | Anthropic Claude / OpenAI | Azure OpenAI |
| LLM (küçük/hızlı) | Haiku sınıfı / küçük model | self-hosted (Faz 3) |
| Vector DB | PostgreSQL + pgvector | OpenSearch |

> Not: LLM seçiminde son müşterinin veri yerleşimi ve "veri eğitime kapalı" gereksinimi (FR-LLM-012) belirleyicidir; AB/UK tenant'ları için bölgesel endpoint zorunlu.

---

## 9. LLM Orkestrasyonu (Routing · Tiering · Semantic Cache)

LLM Router, lean runtime'ın maliyet kalbidir. Her tur için en ucuz yeterli yolu seçer.

### 9.1 Karar Akışı

```
Final transcript + context
   │
   ▼
[1] Semantic Cache lookup (embedding benzerliği) ──hit──► cache'lenmiş yanıt (LLM yok)  [FR-RES-004]
   │ miss
   ▼
[2] Tur sınıflandırma (intent/complexity) ── basit ──► Küçük/hızlı model (Tier-1)  [FR-LLM-013]
   │ karmaşık / risk / tool-yoğun
   ▼
[3] Büyük model (Tier-2) ── stream tokens / tool calls
   │ hata
   ▼
[4] Fallback model veya deterministic flow  [FR-LLM-010]
   │
   ▼
[5] Policy Engine output guard ──► yanıt
```

### 9.2 Bileşenler

- **Tur sınıflandırıcı:** Küçük, hızlı bir model veya kural seti; turu "rutin/karmaşık/riskli" diye etiketler. Hedef: turların ≥%60'ı Tier-1'de karşılanır (NFR 10.2).
- **Semantic cache:** Embedding tabanlı; tenant/agent kapsamında izole. Yalnız *yan etkisiz, bilgilendirici* turlar cache'lenir (tool çağıran turlar asla). PII içeren yanıtlar cache'lenmez.
- **Routing girdileri:** maliyet, gecikme, dil, risk seviyesi (FR-LLM-003); tenant/use-case override (FR-LLM-002).
- **Context yönetimi:** Session Memory özetleme + RAG top-k trimming ile token tüketimi düşürülür (FR-RES-010).
- **Kayıt:** Her tur için seçilen model + versiyon + token kullanımı call event'ine yazılır (FR-LLM-011).

### 9.3 Güvenlik

- System prompt sabittir ve kullanıcı/KB içeriğiyle değiştirilemez (FR-LLM-006).
- Prompt-injection/jailbreak guard input tarafında (Policy Engine) çalışır (FR-LLM-007).
- Kritik işlemler serbest metinle değil, schema-validated tool call ile yapılır (FR-LLM-008).

---

## 10. Bilgi Tabanı ve RAG Mimarisi

### 10.1 İndeksleme (offline, Control/Analytics Plane)

```
Doküman (PDF/Word/HTML/CSV/web/SharePoint/Confluence)
   │ ingest connector
   ▼
Parse & normalize ──► Chunk ──► Embed ──► Vector Store (tenant+agent kapsamlı)
                                            + metadata (kaynak, versiyon, erişim yetkisi)
```

- Otomatik chunk + index + versiyon (FR-KB-003).
- Tenant/agent bazında ayrı namespace (FR-KB-004); doküman bazında erişim yetkisi metadata'da (FR-KB-005).
- Bayatlama: içerik TTL/işaretleme (FR-KB-008).

### 10.2 Retrieval (online, hot path)

```
Soru ──► embed ──► vector search (top-k) ──► reranking (opsiyonel) ──► trim (token budget)
                                                                          │
                                                                          ▼
                                                        LLM context (kaynak atıflı)
```

- Top-k ve trimming ile bağlam maliyeti sınırlanır (FR-KB-011, FR-RES-010).
- Yanıtın hangi kaynağa dayandığı izlenir (FR-KB-006).
- **Anti-hallucination:** Kaynak bulunamazsa agent uydurmaz; "kontrol ediyorum / aktarıyorum / ticket açıyorum" davranışı Policy Engine'de zorlanır (FR-KB-007, BRD §13).
- Hassas dokümanlar sağlayıcı loglarına gitmez (FR-KB-010) → "no-log/no-train" endpoint'leri (FR-LLM-012).
- KB kalitesi benchmark veri setiyle test edilir (FR-KB-009) → Test & Simulation Centre.

---

## 11. Tool Yürütme ve Kurumsal Entegrasyon

### 11.1 Tool Yürütme Hattı

```
LLM tool call (JSON) ──► [1] Schema validation (input)  [FR-TOOL-002]
                         [2] Authorization (agent scope, read/write level)  [FR-TOOL-004/005]
                         [3] Policy gate (kritik işlem → teyit/step-up)  [FR-TOOL-006/007]
                         [4] Idempotency key üret/kontrol  [FR-TOOL-009]
                         [5] Integration GW: timeout + retry + circuit breaker  [FR-TOOL-003]
                         [6] Schema validation (output) + error normalization  [FR-TOOL-008]
                         [7] correlation_id ile audit & trace  [FR-TOOL-010]
```

### 11.2 Integration Gateway

- Protokoller: REST, SOAP, GraphQL, webhook (FR-TOOL-001).
- Yalnız onaylı endpoint'lere (allowlist) erişim (FR-TOOL-012).
- Uzun işlemler için asenkron workflow (FR-TOOL-011) → orkestratör beklemez, sonuç callback/polling ile döner; bu sırada agent kullanıcıyı bilgilendirir.
- Connection pooling + kalıcı oturum (FR-RES-006) ile gecikme ve kaynak israfı azaltılır.

### 11.3 Deterministic Workflow Engine

Para/poliçe/PII değiştiren işlemler bir **workflow** ile yürütülür (BRD §13): kimlik doğrulama → kurallı adımlar → müşteriye özet → açık teyit → (gerekirse) insan onayı → audit. Bu workflow'lar LLM'in serbest kararına bırakılmaz; durum makinesi olarak tanımlıdır.

---

## 12. Veri Mimarisi

### 12.1 Depolama Seçimleri (polyglot persistence)

| Veri türü | Depo | Gerekçe |
|-----------|------|---------|
| Tenant/Agent/Config/IAM | PostgreSQL (ilişkisel, row-level security) | Tutarlılık, izolasyon, audit |
| Session memory (canlı) | Bellek + Redis (kısa TTL) | Düşük gecikme, geçici |
| Call/Transcript/Event (geçmiş) | PostgreSQL + nesne depolama (kayıtlar) | Sorgulanabilirlik + ucuz arşiv |
| Recording (ses) | Nesne depolama (S3 uyumlu), tenant-bazlı bucket/prefix + KMS | Maliyet, şifreleme, lifecycle |
| Vektörler (RAG) | pgvector / OpenSearch | RAG retrieval |
| Event stream | Kafka (veya bölgesel eşdeğeri) | Async pipeline, replay |
| Analytics | Kolon-bazlı OLAP (ClickHouse / BigQuery) | Dashboard & raporlama |
| Metrics/Logs/Traces | Prometheus + Loki/ELK + OTel backend | Gözlemlenebilirlik |
| Secrets/Keys | Secrets Manager + KMS (BYOK) | NFR 10.6 |

### 12.2 Veri Modeli Eşlemesi

BRD §16'daki tüm varlıklar (Tenant, Organisation Unit, User, Role, Agent, Agent Version, Prompt, Conversation Flow, Voice/Model/STT Profile, Knowledge Base, Tool, Phone Number, SIP Trunk, Campaign, Contact, Consent, Call, Call Leg, Transcript, Recording, Event, Tool Execution, Call Evaluation, Usage Record, Audit Log, Incident) ilişkisel + nesne + analitik depolara dağıtılır. Detaylı şema (PK/FK, indeksler) **veri tabanı tasarım dokümanında** netleştirilecektir (sonraki adım). Her tablo `tenant_id` taşır ve row-level security ile filtrelenir.

### 12.3 Veri Yerleşimi (Residency)

- Bölgesel deployment: UK, EU, North America, Middle East (NFR 10.7).
- Her tenant'a bağlı bir "home region"; ses kaydı, transkript, prompt, KB, analitik, audit, backup ve **sağlayıcıya gönderilen içerik** o bölgede kalır.
- Residency, adapter `region selection` özelliği ile sağlayıcı düzeyinde de zorlanır.
- Yönetim panelinde her veri türünün hangi bölgede tutulduğu gösterilir (NFR 10.7).

---

## 13. Çok Kiracılılık (Multi-Tenancy) ve İzolasyon

### 13.1 İzolasyon Modeli

- **Mantıksal izolasyon (varsayılan, shared tenant):** Tek runtime havuzu; her veri satırı/istek `tenant_id` ile etiketli; PostgreSQL row-level security; ayrı KMS key/tenant (FR-TEN-002, NFR 10.6).
- **Fiziksel/ayrılmış izolasyon (dedicated tenant):** Ayrı namespace/cluster/region; regüle sektörler ve büyük müşteriler için (FR-TEN-005, Faz 2/3).

### 13.2 Kota ve Noisy-Neighbor Önleme

Resource Manager (§15) her tenant için uygular:
- Eş zamanlı çağrı ve CPS kotası (FR-TEN-006).
- Kaynak kotası: vCPU/bellek/eşzamanlılık; aşım engellenir (FR-TEN-007).
- Tenant başına concurrency rezervasyonu + adil paylaşım (fair scheduling) ile bir tenant diğerini etkilemez (NFR 10.3).

### 13.3 Tenant Context Propagation

`tenant_id` (+ `org_unit`, `agent_id`, `correlation_id`) her istekte, event'te, log'da ve trace span'inde taşınır. Adapter çağrıları doğru tenant kimlik bilgileri ve region ile yapılır.

---

## 14. IAM ve Güvenlik Mimarisi

### 14.1 IAM

- **RBAC** (FR-IAM-001): rol → izin matrisi; agent oluşturma/yayınlama/canlı izleme yetkileri ayrı (FR-IAM-004).
- **SSO:** SAML 2.0 + OIDC (FR-IAM-002); kurumsal IdP federasyonu.
- **MFA** (FR-IAM-003), **SCIM** provisioning (FR-IAM-007).
- **Maker-checker:** kritik değişikliklerde onay akışı (FR-IAM-005).
- **Audit:** tüm kullanıcı/sistem işlemleri değiştirilemez (append-only / WORM) audit log (FR-IAM-006).

### 14.2 Güvenlik Katmanları (defense in depth)

| Katman | Kontrol |
|--------|---------|
| Ağ | Zero-trust, ağ segmentasyonu, private endpoint, IP allowlist, WAF, DDoS koruması, SIP için SBC |
| Aktarım | TLS 1.2+ her yerde; SRTP medya için |
| Depolama | AES-256; tenant başına KMS key; BYOK / customer-managed keys (Faz 3) |
| Sır yönetimi | Secrets Manager; runtime'da kısa ömürlü token |
| Uygulama | Rate limiting, input validation, schema doğrulama, prompt-injection guard |
| Kimlik (çağrı içi) | Caller ID tek başına yetersiz; OTP/KBA/step-up (FR-AUTH-*); ses biyometrisi opsiyonel ayrı modül (FR-AUTH-006/007) |
| Veri | PII redaction; kart/parola/OTP kayıt & transkriptten çıkarılır (FR-REC-004/005) |
| Tedarik zinciri | SAST, DAST, dependency scanning, SBOM (NFR 10.6) |
| Operasyon | PAM, incident response, düzenli pentest |

### 14.3 Çağrı İçi Kimlik Doğrulama

```
Caller ID (zayıf sinyal) ──► hesap eşleştirme
   │ hassas işlem talebi
   ▼
Step-up: OTP / müşteri no / KBA ──► başarısız deneme limiti  [FR-AUTH-004]
   │ başarılı
   ▼
İşlem yetkisi (sınırlı süre, sınırlı kapsam)
```

Hassas bilgiler sesli olarak tam tekrarlanmaz (FR-AUTH-005).

### 14.4 Panel Mimarisi ve Yetkilendirme (L0/L1/L2 · AuthZ)

BRD Bölüm 17'deki üç katmanlı panel mimarisi ve RBAC matrisi, bu bölümde teknik enforcement'a indirgenir. Üç panel **ayrı erişim sınırları** olarak ele alınır; izolasyon hem frontend route hem backend endpoint hem veri (RLS) seviyesinde zorlanır (defense in depth).

#### 14.4.1 Frontend (Next.js App Router)

Yönetim/panel uygulaması Next.js App Router ile üç ayrı **route group** olarak yapılandırılır; her group kendi `layout` ve auth guard'ına sahiptir:

```
# Platform Control Plane (L0) — AYRI deploy, internal-only (ADR-011)
platform-app/
  app/(platform)/    # L0 — Platform Admin Console (cross-tenant)
    layout.tsx       #   platform auth realm + platform rol guard
    overview/ tenants/ resources/ providers/ billing/ policy/ audit/ releases/ incidents/
  middleware.ts      #   VPN/allowlist/private endpoint; tenant iş verisi route'u yok

# Tenant Application Plane (L1+L2) — birlikte, multi-tenant, public
tenant-app/
  app/(tenant-admin)/  # L1 — Tenant Admin Console (tek tenant)
    layout.tsx         #   tenant oturumu + L1 rol guard; tenant scope middleware'de sabitlenir
    dashboard/ org/ users/ numbers/ integrations/ compliance/ billing/ audit/ quota/
  app/(workspace)/     # L2 — Operasyon / Uygulama Paneli (tek tenant)
    layout.tsx         #   tenant oturumu + L2 rol guard
    dashboard/ live-calls/ agents/ builder/ flows/ prompts/ voice/ kb/ tools/
    campaigns/ recordings/ call/ qa/ analytics/ cost/ test/ versions/
  middleware.ts        #   oturum doğrulama + tenant scope (L1/L2 tek tenant'a bağlı)
```

- **İki düzlemli dağıtım (ADR-011):** L0, ayrı ve **internal-only** bir *Platform Control Plane* olarak deploy edilir (ayrı origin, ayrı API servisi, ayrı auth realm, VPN/allowlist/private endpoint arkasında — public değil). L1+L2 birlikte, multi-tenant ve public bir *Tenant Application Plane* olarak çalışır. Üç ayrı deploy kaynak israfıdır; tek deploy + guard ise paylaşılan kod/middleware'de tek bir bug ile L0'ı açar (blast-radius riski). İki düzlem, güvenlik/maliyet dengesini ve lean runtime mandasını birlikte korur.
- **Tenant scope route/middleware seviyesinde zorlanır:** L1/L2 oturumları tek bir `tenant_id`'ye bağlıdır; cross-tenant gezinme mümkün değildir (FR-TEN-002, BRD §17.7).
- UI yalnız görsel kapıdır; **yetki kararı her zaman backend'de** verilir (frontend guard'ı yalnız UX içindir).

#### 14.4.2 Backend (FastAPI)

Her endpoint üç boyutta korunur: **panel + rol + tenant scope**. FastAPI dependency'leri (guard) ile uygulanır:

```python
# kavramsal — sözleşme; gerçek isimlendirme SRS/kod aşamasında netleşir
@router.get("/calls/{id}", dependencies=[Depends(require(perm="calls:read", panel="L2"))])
async def get_call(id, ctx: AuthCtx = Depends(auth_ctx)):
    enforce_tenant_scope(ctx, resource_tenant_of(id))   # cross-tenant erişim reddi
    ...
```

- **Ayrı router/scopes + ayrı deploy:** L0 endpoint'leri ayrı bir servis (Platform Control Plane, internal-only) ve ayrı auth realm'de; L1/L2 endpoint'leri Tenant Application Plane'de ayrı router ağaçları ve OAuth scope'larında tanımlanır (ADR-011).
- **L0 iş verisine erişemez:** Platform endpoint'leri tasarım gereği tenant iş verisi (call/transcript/PII) repository'lerine bağlı değildir; erişim yalnız break-glass akışıyla açılır (FR-IAM-008/009).
- **Üç katmanlı break-glass (FR-IAM-009/010):**
  - **Tier A** (metrik/log, PII yok): break-glass gerekmez; normal L0 erişimi + audit.
  - **Tier B** (transkript/kayıt/PII): maker-checker (talep eden ≠ onaylayan) → süreli token (varsayılan 60 dk, max 4 saat, otomatik expiry, standing access yok) → zorunlu gerekçe kodu → tenant `security_compliance_officer` + `tenant_owner`'a anlık bildirim. Erişim ayrı, kısıtlı, tam-audit'li bir break-glass router'ı üzerinden verilir.
  - **Regüle tenant toggle:** `require_tenant_approval=true` ise Tier B, tenant onayı olmadan açılmaz; regulated compliance profile'da varsayılan açık; DPA'ya bağlı (controller=tenant, processor=RMC).
- **Tenant scope:** Her tenant-kapsamlı istek `tenant_id` taşır ve PostgreSQL row-level security ile çift kontrol edilir (§13).
- **Scoped assignment (FR-IAM-011):** Rol = sabit permission bundle; atama bir `scope` (departman/marka/kampanya) ile daraltılır. Guard, hem permission-key'i hem assignment scope'unu kaynak attribute'larına karşı doğrular (örn. `operations_manager@scope=brandX` yalnız brandX kampanyalarını yönetir).
- **maker-checker** (FR-IAM-005) kritik mutasyonlarda onay durumu (pending→approved) ile zorlanır.

#### 14.4.3 RBAC Rolleri ve İzin (Permission) Anahtarları

BRD §17.6 matrisi, `kaynak:eylem` formatında permission-key'lere indirgenir. Roller bu key kümeleriyle tanımlanır.

| Alan | Örnek permission-key'ler |
|------|--------------------------|
| Platform (L0) | `tenant:provision`, `tenant:suspend`, `resource:quota:manage`, `provider:health:read`, `provider:routing:manage`, `platform:billing:manage`, `policy:global:manage`, `platform:audit:read`, `release:manage`, `incident:manage` |
| Tenant Admin (L1) | `tenant:dashboard:read`, `org:manage`, `user:manage`, `role:assign`, `number:manage`, `integration:manage`, `apikey:manage`, `compliance:manage`, `retention:manage`, `consent:manage`, `tenant:billing:read`, `tenant:audit:read`, `quota:read` |
| Operasyon (L2) | `agent:read`, `agent:build`, `flow:edit`, `prompt:edit`, `voice:edit`, `kb:manage`, `tool:bind`, `campaign:manage`, `calls:read`, `calls:read:own`, `transcript:read`, `transcript:manage`, `qa:score`, `analytics:read`, `cost:read`, `test:run`, `agent:version:manage`, `livecalls:manage` |

Rol → permission-key eşlemesi (özet; tam matris SRS izlenebilirlik tablosunda):

| Rol | Temsilî permission set |
|-----|------------------------|
| `platform_owner` | tüm L0 key'leri (Yönet) |
| `platform_sre` | `resource:quota:manage`, `provider:*:manage`, `release:*`, `incident:manage`, `platform:audit:read` (iş verisi key'i yok) |
| `platform_billing` | `platform:billing:manage`, `provider:health:read` |
| `tenant_owner` | tüm L1 + tüm L2 key'leri |
| `tenant_admin` | `org:manage`, `user:manage`, `role:assign`, `number:manage`, `integration:manage`, `apikey:manage`, `quota:read` |
| `security_compliance_officer` | `compliance:manage`, `retention:manage`, `consent:manage`, `tenant:audit:read`, `transcript:read` (PII denetimi) |
| `billing_viewer` | `tenant:billing:read`, `quota:read`, `tenant:dashboard:read` |
| `operations_manager` | L2 supervisor seti (`campaign:manage`, `calls:read`, `transcript:manage`, `qa:score`, `analytics:read`, `livecalls:manage`, `cost:read`) |
| `conversation_designer` | `agent:build`, `flow:edit`, `prompt:edit`, `voice:edit`, `kb:manage`, `tool:bind`, `test:run`, `agent:version:manage` |
| `qa_analyst` | `calls:read`, `transcript:read`, `qa:score`, `analytics:read` |
| `human_agent` | `calls:read:own`, `transcript:read:own`, `livecalls:read:own` |
| `api_developer` | `apikey:manage`, `integration:manage`, `tool:bind`, `number:read` |

`*:own` son ekli key'ler kaynak sahipliği (ör. çağrının atandığı temsilci) ile sınırlıdır (BRD §17.7 `human_agent` kuralı).

#### 14.4.4 SSO / SCIM Rol Eşleme

```
Kurumsal IdP (SAML 2.0 / OIDC)  ──login──►  Platform AuthN
   │ IdP group / SAML attribute (ör. "voiceai-ops-manager")
   ▼
Rol eşleme tablosu (tenant bazında konfigüre)  ──►  RBAC rol(leri)  ──►  permission set
   ▲
   │ SCIM 2.0 provisioning (kullanıcı + grup senkronu, FR-IAM-007)
Kurumsal IdP
```

- IdP grupları/attribute'ları tenant bazında RBAC rollerine eşlenir (FR-IAM-002).
- SCIM ile kullanıcı/grup yaşam döngüsü senkronize edilir (FR-IAM-007); deprovision → erişim anında düşer.
- Platform rolleri (L0) ayrı bir IdP/dizinden federe edilir; tenant IdP'leri L0 rolü atayamaz (FR-IAM-008).
- Tüm panel erişimleri ve hassas görüntülemeler (özellikle break-glass) audit log'a yazılır (FR-IAM-006, FR-REC-009).

---

## 15. Kaynak Verimliliği Mimarisi (Lean Runtime · Resource Manager)

Bu, ürünün ticari farklılaşmasının mimari temelidir. Tüm FR-RES-* ve NFR 10.2 burada toplanır.

### 15.1 Runtime Tasarımı

| Mekanizma | FR | Nasıl |
|-----------|-----|-------|
| Async/non-blocking runtime | FR-RES-001 | Olay döngüsü, oturum = hafif async task; thread-per-call yok |
| Stream-everywhere | FR-RES-002 | Hiçbir hot-path'te full buffering yok |
| TTS cache | FR-RES-003 | Statik anonslar (karşılama/onay/IVR) önceden sentezlenir, hit ≥%80 hedefi |
| Semantic cache | FR-RES-004 | Tekrar sorular için LLM atlanır |
| Model tiering | FR-RES-005 | Turların ≥%60'ı küçük modelde |
| Connection pooling | FR-RES-006 | Sağlayıcı bağlantıları kalıcı |
| Scale-to-zero | FR-RES-007 | Boşta tenant/worker minimuma iner |
| Codec optimizasyonu | FR-RES-008 | Gereksiz resample/transcode yok |
| Edge VAD | FR-RES-009 | Ölü hava işlenmez |
| Context küçültme | FR-RES-010 | Özetleme + retrieval trimming |
| Async non-RT işler | FR-RES-011 | Analitik/redaction/raporlama batch |
| Log sampling | FR-RES-012 | Örneklemeli + asenkron yazım |
| Warm pool | FR-RES-013 | Cold-start gecikmesi azaltılır |
| Backpressure | FR-RES-014 | Aşırı yükte kontrollü sınırlama |
| GPU yalnız gerekince | FR-RES-015 | Tercih CPU/serverless çıkarım |
| Per-call kaynak bütçesi | FR-RES-016 | ~15MB/oturum, izlenir |

### 15.2 Resource Manager Bileşeni

Control Plane'de bir denetleyici (controller) olarak çalışır:

```
Resource Manager
 ├─ Quota Service        : tenant kota tanımı/zorlama (concurrency, CPS, vCPU/mem)
 ├─ Autoscaler           : metrik-tabanlı yatay ölçekleme + warm pool yönetimi
 ├─ Scale-to-zero Ctrl   : boşta tenant/worker'ı küçültme
 ├─ Backpressure Ctrl    : kabul kontrolü (admission); aşırı yükte yeni çağrı reddi/kuyruk
 └─ Cost/Resource Meter  : per-call CPU/mem/eşzamanlılık ölçümü → Analytics & Billing
```

- **Backpressure örneği:** Kapasite eşiğine yaklaşınca yeni outbound dialer hızı düşürülür ve/veya overflow çağrıları callback'e alınır — çökme yerine kontrollü degrade (FR-RES-014, FR-OUT-007).
- **Density hedefi:** Referans 8 vCPU/16 GB worker'da ≥250–500 eş zamanlı oturum (medya işleme konumuna bağlı, NFR 10.2).

---

## 16. Ölçeklenebilirlik ve Dağıtım Topolojisi

### 16.1 Çalışma Zamanı Platformu

- **Konteyner + orkestrasyon:** Kubernetes (bölge başına cluster).
- **Stateless servisler:** Orchestrator worker'ları, adapter'lar, API'ler — yatay ölçeklenir.
- **Stateful:** PostgreSQL (HA, read replica), Kafka, nesne depolama, vector store — managed servis tercih edilir.
- **Autoscaling:** CPU/eşzamanlılık/kuyruk derinliği metrikleriyle HPA + Resource Manager warm pool.

### 16.2 Ölçek Hedefleri (NFR 10.3)

| Hedef | Değer | Mekanizma |
|-------|-------|-----------|
| Region başına eş zamanlı çağrı | 10.000 (ön hedef) | Yatay worker ölçekleme |
| CPS | 100 | Stateless call setup + kuyruk |
| Ani trafik | 2x kısa süreli | Warm pool + autoscale |
| Tenant izolasyonu | Rezerve concurrency | Resource Manager kotaları |

### 16.3 Dağıtım Seçenekleri (BRD)

- SaaS (shared), dedicated cloud, private cloud, on-premise/hybrid.
- Faz 1: tek bölge, SaaS, pilot. Faz 2: multi-region + dedicated. Faz 3: active-active + on-prem/hybrid.
- **Panel düzlemi ayrımı (ADR-011):** Her dağıtımda L0 *Platform Control Plane* ayrı, internal-only bir servis olarak (VPN/private endpoint arkasında) konuşlanır; L1+L2 *Tenant Application Plane* multi-tenant ve public servis olarak. Bu ayrım data plane (voice runtime) ↔ control/analytics plane ayrımıyla (§4.2) uyumludur.

---

## 17. Gözlemlenebilirlik ve İzlenebilirlik

### 17.1 İzleme Omurgası

- **Trace:** Her çağrı bir `correlation_id` ve OpenTelemetry trace'i taşır; BRD §15'teki tüm zaman damgaları span olarak kaydedilir (call connected → first audio → speech start/end → STT partial/final → LLM request/first token → tool req/resp → TTS req/first audio → audio played → transfer → end).
- **Metrics:** Prometheus; BRD §15 teknik metrikleri (packet loss, jitter, codec, SIP code, STT/LLM/TTS latency, token, tool latency, e2e latency, barge-in, silence, retry/fallback, transfer sonucu, provider error rate, dakika maliyeti, **per-call CPU/mem**).
- **Logs:** Yapılandırılmış, örneklemeli, asenkron (FR-RES-012).
- **Visualization:** Grafana dashboard'ları; gerçek zamanlı operasyon ekranı (FR-ANA-012, ≤60sn gecikme).

### 17.2 Alarm (BRD §15)

P95 > 1.5sn, STT hata artışı, LLM sağlayıcı hata artışı, handoff başarısızlığı, tool hata artışı, silent call, consent atlama, bilgi sızıntısı, tenant kapasitesi %80, harcama limiti aşımı, kaynak bütçesi aşımı → alarm ≤2dk (NFR 10.1).

### 17.3 Maliyet & Kaynak Gözlemlenebilirliği

Cost/Resource Meter, çağrı/agent/tenant/sağlayıcı bazında maliyeti ve per-call kaynağı raporlar (FR-ANA-007/013, FR-BIL-002). Bu, lean runtime hedefinin sürekli doğrulanmasını sağlar.

---

## 18. Yüksek Erişilebilirlik ve Felaket Kurtarma

| Boyut | Tasarım | BRD |
|-------|---------|-----|
| Multi-AZ | Zorunlu; tüm stateful servisler AZ-redundant | NFR 10.5 |
| Bölgesel DR | Faz 1-2: active-passive; Faz 3: active-active | NFR 10.5 |
| Yeni çağrı yönlendirme | Bölge arızasında sağlıklı bölgeye otomatik yönlendirme (DNS/anycast + telekom failover) | NFR 10.5 |
| Aktif çağrı | Bölge arızasında tam korunma garanti edilmez; graceful drop + callback | NFR 10.5 not |
| RPO | Config ≤5dk, analitik ≤15dk | NFR 10.5 |
| RTO | Voice runtime ≤15dk, yönetim ≤4sa | NFR 10.5 |
| DR testi | Yılda ≥2 | NFR 10.5 |
| Uptime | Voice runtime/telephony/API %99,99; panel/analitik %99,9 | NFR 10.4 |

---

## 19. Uyumluluk Mimarisi

### 19.1 Consent Engine (outbound)

Outbound çağrı **öncesi** zorunlu kontrol (BRD §14.3, FR-OUT-003):

```
Çağrı talebi ──► Consent Engine
   ├─ arama amacı, ülke kodu, birey/şirket
   ├─ consent kaynağı/tarih/kapsam
   ├─ do-not-call / suppression listesi (gerçek zamanlı)  [FR-TEL-014]
   ├─ izin verilen saat (ülke/bölge)  [FR-TEL-013, FR-OUT-004]
   ├─ son arama / max deneme  [FR-OUT-005]
   ├─ Caller ID, kampanya/teklif versiyonu, zorunlu açılış metni
   └─ silent/abandoned call önleme (kapasite kontrolü)  [FR-TEL-015]
   │ tüm kontroller geçerse
   ▼
Dial
```

TR: İYS + ETK; UK: PECR/Ofcom. Country compliance profiles ile parametrelenir.

### 19.2 Veri Koruma & PII

- PII redaction pipeline (Analytics Plane, async): transkript ve kayıttan kart/parola/OTP çıkarılır (FR-REC-004/005).
- Retention otomatik uygulanır; süre sonunda geri döndürülemez silme (FR-REC-006/010); legal hold (FR-REC-007).
- Veri sahibi hakları (erişim/düzeltme/silme), DPA, alt işleyen listesi, DPIA şablonu, ihlal bildirimi (BRD §14.1).
- Sağlayıcıya gönderilen verinin kaydı + "no-train" varsayılan (FR-LLM-012, FR-KB-010).

### 19.3 AI Şeffaflığı

Çağrı başında yapılandırılabilir AI/kayıt bildirimi (FR — BRD §14.2). EU AI Act şeffaflık yükümlülüğü 2 Ağustos 2026 — AB tenant'ları için baştan açık. "No deceptive impersonation" prensibi Policy Engine'de zorlanır.

### 19.4 Sektörel Profiller

Tenant'ın ülke+sektörüne göre compliance profile seçilir: PCI DSS, FCA, HIPAA, NHS DSP Toolkit, SOC 2, ISO 27001/27701, DORA, NIS2 (BRD §14.4). PCI için kart verisi LLM/transkript/kayıt dışında tutulur; ödeme PCI-uyumlu kanala (DTMF masking / aktarım) yönlendirilir (BRD §8.5).

---

## 20. Gecikme Bütçesi (Latency Budget)

End-of-utterance → ilk agent sesi için P95 ≤ 1.200 ms hedefinin bileşen dağılımı (ön tasarım; pilotta doğrulanacak):

| Aşama | Bütçe (P95) | Not |
|-------|-------------|-----|
| Endpointing (VAD karar gecikmesi) | ~150–250 ms | Edge'de; dinamik |
| STT final transcript | ~100–200 ms | Streaming; final flush |
| Orchestrator + Policy + routing | ≤ 50 ms | Bellek-içi, async |
| RAG retrieval (gerekirse) | ~100–200 ms | Top-k; çoğu turda atlanır |
| LLM first token | ~200–400 ms | Tier'a göre; küçük model daha hızlı |
| TTS first byte | ~100–200 ms | Streaming; cache hit'te ~0 |
| Ağ/medya | ~50–100 ms | Bölgesel edge ile düşürülür |
| **Toplam (tipik)** | **~700 ms P50 / ≤1.200 ms P95** | NFR 10.1 |

Barge-in TTS kesme ≤200ms; tool overhead ≤100ms; config yükleme ≤500ms (NFR 10.1). Optimizasyonlar gecikmeyi bozmadan kaynağı azaltır (NFR 10.2 notu).

---

## 21. Teknoloji Yığını Önerileri

> Bunlar mimari öneridir; nihai seçim vendor eval ve PoC sonrası kesinleşir (ADR-001/002).

| Alan | Öneri | Gerekçe |
|------|-------|---------|
| Runtime dili (orchestrator) | **Go** veya **Rust** (hot path) + Python (ML/araç) | Yüksek eşzamanlılık, düşük bellek, lean runtime hedefi (FR-RES-001/016) |
| Async model | Go goroutine / Rust async-tokio | Oturum başına hafif görev |
| Medya | C/C++/Rust native (WebRTC stack, VAD) | Düşük gecikmeli ses işleme |
| Panel/Yönetim API (Control & Analytics plane) | **FastAPI (Python)** — üç panel için ayrı router ağaçları/scope'lar | Hızlı geliştirme, panel + rol + tenant guard'ları (§14.4.2) |
| Yönetim panelleri (L0/L1/L2) | **Next.js (App Router, TypeScript)** — panel başına route group | BRD §17 ekranları; route/middleware seviyesinde tenant scope (§14.4.1) |
| Mesajlaşma | Kafka | Async pipeline, replay |
| İlişkisel DB | PostgreSQL (+ pgvector, RLS) | İzolasyon, RAG, audit |
| Cache | Redis | Session memory, semantic cache, TTS cache index |
| OLAP | ClickHouse / BigQuery | Analytics |
| Nesne depolama | S3-uyumlu + KMS | Kayıtlar, residency |
| Orkestrasyon | Kubernetes | Autoscale, multi-region |
| Gözlemlenebilirlik | OpenTelemetry + Prometheus + Grafana + Loki | BRD §15 |
| Secrets | Vault / cloud Secrets Manager + KMS | BYOK |
| SBC | OpenSIPS/Kamailio veya managed SBC | SIP güvenlik |

**Neden Go/Rust hot path'te:** BRD'nin merkezi farklılaşması "oturum başına ~15MB ve worker başına 250–500 oturum". GC-ağır veya thread-per-call runtime'lar bu yoğunluğu sağlayamaz. Async, düşük-bellekli bir dil bu yüzden bir mimari gerekliliktir, tercih değil (ADR-003).

**İki düzlemli yığın ayrımı:** Gerçek zamanlı **data plane** (voice runtime / orchestrator) Go/Rust kalır; gecikme ve density bunu zorunlu kılar. Buna karşılık **panel/yönetim düzlemi** (Control & Analytics plane — L0/L1/L2 panelleri ve API'leri) **Next.js + FastAPI** ile geliştirilir; bu düzlem gerçek zamanlı hot path'te değildir, geliştirme hızı ve zengin yönetim ekranları önceliklidir. İki düzlem ayrı servislerdir ve §4.2'deki plane ayrımıyla uyumludur.

---

## 22. Mimari Karar Kayıtları (ADR)

| ADR | Karar | Durum | Gerekçe / Sonuç |
|-----|-------|-------|------------------|
| ADR-001 | Bağımsız Conversation Orchestrator (STT/LLM/TTS doğrudan bağlanmaz) | **Kabul** | Ürünün IP'si; vendor-neutral, kontrol, gözlemlenebilirlik (BRD §11/§24) |
| ADR-002 | Provider Adapter SPI + kategori başına ≥2 sağlayıcı | **Kabul** | OBJ-10, BRD §19 kabul kriterleri |
| ADR-003 | Hot path'te async, düşük-bellekli dil (Go/Rust) | **Öneri** | Lean runtime/density hedefleri (NFR 10.2) |
| ADR-004 | Data/Control/Analytics plane ayrımı | **Kabul** | Hot path'i hafif tutmak (FR-RES-011) |
| ADR-005 | Edge VAD/endpointing | **Kabul** | Gecikme + kaynak (FR-RTC-013, FR-RES-009) |
| ADR-006 | Tenant izolasyonu: shared (RLS) + dedicated opsiyon | **Kabul** | FR-TEN-002/005 |
| ADR-007 | Async event pipeline (Kafka) ile post-processing | **Kabul** | FR-RES-011 |
| ADR-008 | Model tiering + semantic cache zorunlu | **Kabul** | NFR 10.2 maliyet hedefi |
| ADR-009 | Medya işleme konumu (edge vs merkez) | **AÇIK** | §23; pilot ile karar (kaynak/gecikme dengesi) |
| ADR-010 | Self-hosted LLM + GPU kapsamı | **AÇIK** | Faz 3; yalnız gerekçeli durumda (FR-RES-015) |
| ADR-011 | İki düzlemli panel dağıtımı: L0 ayrı internal-only Control Plane; L1+L2 birlikte public | **Kabul** | Blast-radius azaltımı; tek-deploy+guard riskli, üç-deploy israf (§14.4.1, BRD §17.7) |
| ADR-012 | Sabit rol bundle + scoped assignment; custom roller Faz 3 | **Kabul** | Combinatorial/güvenlik riskini önler (FR-IAM-011) |
| ADR-013 | Üç katmanlı break-glass + regüle tenant onay toggle'ı | **Kabul** | KVKK/GDPR controller-processor; DPA bağlı (FR-IAM-009/010) |

---

## 23. BRD Açık Kararlarına Mimari Yanıtlar

BRD §22'deki açık kararlar için mimari öneri/etki (nihai karar paydaşlarda):

| BRD Açık Karar | Mimari Öneri / Not | Bağımlılık |
|----------------|--------------------|------------|
| İlk hedef ülke/sektör | UK veya TR; düşük-riskli use-case (randevu/genel müşteri hizmetleri) | Compliance profile, dil |
| İlk pilot use-case | Inbound müşteri hizmetleri (containment ölçümü kolay) | Faz 1 kapsamı |
| Eş zamanlı çağrı | Pilot 100–250 (BRD Faz 1) | Tek bölge yeterli |
| Inbound/outbound oranı | Faz 1 inbound ağırlıklı | Outbound Faz 2 |
| Telekom sağlayıcı | Twilio (hız) + SIP fallback | ADR-002 |
| SIP vs managed | Faz 1 managed; BYOC Faz 2 | FR-TEL-002 |
| İlk diller | EN + TR | STT/TTS adapter dil kapsamı |
| Private vs SaaS | Faz 1 SaaS pilot | Faz 2 dedicated |
| Retention süreleri | Tenant/ülke bazlı; varsayılan muhafazakâr | FR-REC-006 |
| Özel ses kullanımı | İzin + kayıt zorunlu (FR-TTS-007) | Faz 2+ |
| PCI kapsamı | Faz 1 dışı; Faz 3 PCI ödeme | BRD §8.5 |
| İlk CC entegrasyonu | Genesys veya Amazon Connect | Faz 2 |
| Temsilci desktop | Screen-pop (CRM/CTI); tam desktop kapsam dışı | FR-HND-004 |
| Fiyatlandırma | Dakika + plan + overage (FR-BIL-*) | Billing |
| AI disclosure | Açık, yapılandırılabilir, AB'de zorunlu | §19.3 |
| LLM veri gönderimi | "No-train" varsayılan; bölgesel endpoint | FR-LLM-012 |
| Model logları | Hassas tenant'ta kapalı | FR-KB-010 |
| Max işlem risk seviyesi | Düşük-orta; yüksek risk insan onaylı | BRD §13 |
| **Medya işleme konumu** | **ADR-009 — pilotta ölç** | Density/gecikme |
| **Self-hosted/GPU** | **ADR-010 — Faz 3** | Maliyet/uyum |

---

## 24. Mimari Riskler ve Önlemler

| Risk | Mimari Önlem |
|------|--------------|
| Gecikme bütçesinin aşılması | Bölgesel edge, streaming, model tiering, gecikme bütçesi izleme (§20) ve alarm |
| Density hedefinin tutturulamaması | Async/düşük-bellekli runtime (ADR-003), per-call kaynak bütçesi izleme, yük testinde regresyon (FR-TST-009) |
| Sağlayıcı kesintisi | Adapter fallback + circuit breaker + deterministic flow (§8.3) |
| Tenant veri sızıntısı | RLS + ayrı KMS key + tenant context propagation + izolasyon testi (BRD §19 madde 8/9) |
| Idempotent olmayan tool çağrıları | Idempotency key + Integration GW (§11) |
| Prompt injection / jailbreak | Input/output Policy Engine guard, sabit system prompt (§6.2, §9.3) |
| Hallucination | RAG kaynak atfı + "uydurma yok" policy + deterministic workflow (§10.2) |
| Outbound izin ihlali | Consent Engine ön-kontrol, gerçek zamanlı suppression (§19.1) |
| Maliyet kayması | Cost/Resource Meter + model routing + cache + bütçe alarmı (§17.3) |
| Bölge arızasında çağrı kaybı | Yeni çağrı failover + callback; aktif çağrı için graceful drop (§18) |

---

## 25. Sonraki Adımlar

1. **PoC / Spike (2-4 hafta):** Tek inbound akış üzerinde uçtan uca gecikme bütçesini (§20) ve density'yi (NFR 10.2) ölçmek; ADR-003 ve ADR-009'u doğrulamak.
2. **Vendor eval:** STT/TTS/LLM/telekom adapter'ları için ≥2'şer sağlayıcı PoC (ADR-002).
3. **SRS (System Requirements Specification):** Bu SAD'a bağlı, FR/NFR'lerin test edilebilir sistem gereksinimlerine dönüştürülmesi; tam izlenebilirlik matrisi.
4. **Veri Tabanı ve API Tasarımı:** BRD §16 varlıklarının detaylı şeması (PK/FK, indeks, RLS politikaları) + adapter SPI ve kamu API sözleşmeleri (OpenAPI).
5. **Güvenlik & Uyum tasarım derinleştirme:** Threat model (STRIDE), DPIA şablonu, compliance profile parametreleri.
6. **Faz 1 yapı planı:** BRD §20 Faz 1 kapsamına göre iş kırılımı (WBS) ve pilot kabul kriterleri.

> Bu SAD, BRD v2.0'ın iki mandasını — düşük gecikme ve düşük kaynak tüketimi — tek bir mimaride birleştirir: **bağımsız bir asenkron Conversation Orchestrator, sağlayıcıdan bağımsız adapter mesh, plane ayrımı ve Resource Manager.** Sonraki dokümanlar bu temeli uygulanabilir spesifikasyonlara indirger.
```
