# A-02 — Canlı Çağrılar (Live Calls) · WBS 13.4.2

L2 Operasyon / Uygulama Paneli'nin (A-01..A-17) ikinci ekranı — **L2 serisinin ilk implemente edilen
ekranı**. Tenant'ın **o anda aktif** çağrılarının **gerçek zamanlı** operasyon görünümü: özet (KPI),
durum dağılımı (çağrı + tur durumu), dikkat gerektiren çağrılar ve aktif çağrı tablosu.

## Kaynak gereksinimler
- **FR-ANA-012** — Gerçek zamanlı operasyon ekranı bulunmalıdır (izlenebilirlik birincil hedefi).
- **SR-ANA-012 / SR-PERF-007** — Operasyon ekranı metrik gecikmesi **≤60 sn**.
- **FR-ANA-008** — Kritik konuşmalar otomatik işaretlenmelidir (`flagged`).
- **FR-ANA-006** — STT/LLM/TTS + toplam yanıt gecikmesi ayrı gösterilmelidir (`sttMs/llmMs/ttsMs/liveLatencyMs`).
- **NFR 10.1** — Uçtan-uca yanıt P95 ≤1200ms (canlı gecikme ihlali eşiği).
- **SAD §6.1** — Turn state machine (LISTEN/CAPTURE/THINK/SPEAK) → `turnState`.
- **FR-TEN-002** — Tenant scope: yalnız kendi tenant'ın aktif çağrıları (RLS + middleware).
- **BRD §17.5** A-02 "Aktif çağrı izleme" · **§17.6** RBAC · **§17.7** hijyen + PII redaction · **NFR 10.6** sır.

## RBAC (BRD §17.6 — L2)
`operations_manager`=Yönet · `conversation_designer`=— · `qa_analyst`=Görüntüle · `human_agent`=Görüntüle
(**kendi**). UI yalnız görsel kapı; nihai yetki backend'de (12.2.x) + RLS. `human_agent` yalnız KENDİ
atanmış çağrılarını görür (`callsAssignedTo`; backend zorlar). İzleme/canlı dinleme/aktarma aksiyonları
görsel kapıdır (A8). Permission-key: `calls:monitor` + `calls:read` (SAD §7/§17.2).

## Çekirdek altın kural — hijyen + güvenlik
A-02 **aggregate canlı listesi** yalnız **OPERASYONEL META** gösterir (çağrı REFERANSI · durum/tur ·
canlı gecikme · agent · MASKELENMİŞ taraf). Ham son-müşteri içeriği (transkript/ses kaydı, ham telefon
numarası/callerId, kart/CVV, CDR) **gömülmez**; taraf yalnız `maskedParty` ile (zaten redакte). Canlı
dinleme/transkript derin aksiyondur → **A-12 Çağrı Detayı** (görsel kapı + backend). `getLiveCalls` her
dönüşte `assertNoPii` çağırır → `FORBIDDEN_PII_KEYS` (transcript/recording/msisdn/phoneNumber/customer/
cdr/...) **ve** `FORBIDDEN_SECRET_KEYS` (secret/apiKey/token/privateKey/kmsKey/...) taraması → ihlalde
hata. NOT: `agentName`/`tenantName` tenant'ın KENDİ yapılandırmasıdır (L2'de izinli).

## Gerçek zamanlılık (FR-ANA-012 / SR-ANA-012)
Snapshot `dataAgeSeconds` taşır; `staleSnapshot` **60 sn** tazelik bütçesini (`FRESHNESS_BUDGET_SEC`)
aşan veriyi işaretler (danger). Panel periyodik (≤60 sn, `refreshIntervalSec`) yenilenir. Gerçek besleme
(F1 §14.1) Conversation Orchestrator canlı oturum durumu + gözlemlenebilirlik omurgası (0.4.7)
telemetrisinden tenant-scope (RLS) ile gelir.

## Dosyalar
- `app/(workspace)/workspace/live-calls/page.tsx` — ekran (RSC, async). Tasarım sistemi + i18n + veri seam.
- `lib/tenant/live-calls.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları + `assertNoPii`.
- `lib/i18n/{tr,en}.json` — `screen.a02.*` (3 app'e vendored, hash-eşit; TR↔EN parity).
- `a02-live-calls-spec.json` — S1..S8 invariant + referans anahtar + placeholder + bütçeler.
- `a02_live_calls_probe.py` — stdlib-only `validate`/`check`/`selftest`/`schema` (TS saf yardımcı Python aynası).
- `samples/live-{clean,issues}.json` · `tests/a02_live_calls_test.py` · `run_live_test.sh`.

## Saf türetme yardımcıları (deterministik, Python aynalı)
`countByState` · `countByDirection` · `countByTurnState` · `flaggedCalls` (FR-ANA-008) · `handoffPending` ·
`latencyBreaches` (NFR 10.1, eşik 1200ms) · `negativeSentimentCalls` · `callsAssignedTo` (view-own scope) ·
`concurrencyUtilPct` · `staleSnapshot` (FR-ANA-012, 60 sn) · `attentionCalls` · `openAttentionCount`.
Tonlar: `stateTone`/`turnTone`/`directionTone`/`sentimentTone`/`latencyTone`/`handoffTone`/`flagTone`/
`utilTone`/`freshnessTone`. Sabitler: `FRESHNESS_BUDGET_SEC=60` · `LIVE_LATENCY_BUDGET_MS=1200`.

## Doğrulama
```
python3 a02_live_calls_probe.py validate    # ON-DISK S1..S8 (75/75)
python3 a02_live_calls_probe.py check       # saf senaryo + samples (46/46)
python3 a02_live_calls_probe.py selftest    # pozitif/negatif (24/24)
python3 tests/a02_live_calls_test.py        # üç kapı çıkış kodu (3/3)
PORT=3242 ./run_live_test.sh                # next build+start+curl (credential-free; 12/12)
```

## Kapsam dışı (bilinçli)
Gerçek canlı besleme (Conversation Orchestrator oturum durumu + 0.4.7 telemetri) bağlama → F1 §14.1;
canlı dinleme/izleme/aktarma istemci submit + backend zorlama (`calls:monitor`/`calls:read`) → 12.2.x;
çağrı detayı/transkript/timeline → A-12 (13.4.12); WebSocket/SSE push + istemci auto-refresh → ilgili
runtime dilimi (şimdilik sunucu RSC + `refreshIntervalSec` sözleşmesi). SRS/RTM değişmedi (FR-ANA-012 ↔
SR-ANA-012 ↔ TC-ANA-012 ↔ WBS 13.4.2 RTM'de zaten eşli; BRD §17.5 ekran implementasyonu). Sır repoya yazılmadı.
