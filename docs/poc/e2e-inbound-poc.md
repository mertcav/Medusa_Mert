# Uçtan Uca Tek Inbound Akış PoC — `e2e-inbound-poc`

> **WBS 0.3.1** · `F0` · `Must` · →SAD §25 (1), §6.1, §7.1, §20 · ADR-001/002/005
> Kaynak doğruluk: `docs/SAD.md` ve `docs/BRD.md`. Çelişkide dokümanlar esastır.

## 1. Amaç ve kapsam

Bu PoC, BRD/SAD'ın çekirdek mimari hipotezini — **bağımsız bir Conversation Orchestrator'ın
(ADR-001) sağlayıcı-nötr adapter SPI (ADR-002) arkasındaki STT/LLM/TTS/Telephony'yi bir turn
state machine (SAD §6.1) üzerinden uçtan uca orkestre edebileceğini** — çalışan, koşulabilir bir
spike ile gösterir. Doğrulanan akış:

```
PSTN ──► SBC ──► Media Gateway ──► STT ──► Conversation Orchestrator (LLM) ──► TTS ──► Media Gateway ──► PSTN
       (8 kHz/20 ms, edge VAD/endpointing, barge-in)        (LISTEN→CAPTURE→THINK→ACT→SPEAK)
```

**Kapsam (0.3.1):** Tek inbound çağrı; uçtan uca akışın **bütünlüğü** + state machine + invariant
doğruluğu. **Kapsam dışı (komşu görevlere ait seam):**
- **0.3.2** — Formal gecikme bütçesi (P50/P95/P99) ve barge-in kesme ölçümü → bu PoC gecikmeyi
  **yumuşak/illüstratif** raporlar (SAD §20 kalemleri); formal P95 kapısı 0.3.2'ye aittir.
- **0.3.3** — Density (oturum/worker, ~15MB/oturum, NFR 10.2/ADR-003).
- **0.3.4** — Medya işleme konumu (edge vs merkez) deneyi → **ADR-009 kararı**.
- **0.3.5** — Hot-path dil (Go/Rust async) doğrulaması → bu PoC mimari **referans** modelidir
  (Python/sanal saat); hot-path runtime seçimi 0.3.5'te ölçülür.

> **Neden simülasyon?** CLAUDE.md ve 0.2.x hattının disiplini: **vendor-neutral** (sağlayıcı seçme),
> **stdlib-only**, **credential-free**, **tekrarlanabilir**. Gerçek STT/TTS/LLM/telekom çağrısı sır
> gerektirir ve sağlayıcıya bağlar; bunun yerine `Sim*` adapter'lar SPI'yi deterministik doldurur.
> **Mimari değer**, akışın gerçek adapterla mı sahte adapterla mı koştuğunda değil; orchestrator'ın
> **yalnız SPI'ye bağlı kalıp** state machine'i, barge-in'i, fallback'i ve context propagation'ı doğru
> yürütmesindedir. Canlı PoC'ta (0.3.x — gerçek credential `--url`/ortam değişkeni ile) **aynı
> orchestrator** değişmeden gerçek adapter alır.

## 2. Mimari eşleme (SAD ↔ PoC)

| SAD bileşeni | SAD ref | PoC karşılığı (`e2e_inbound_poc.py`) |
|--------------|---------|--------------------------------------|
| Adapter SPI (Stt/Tts/Llm/Telephony) | §8.1 | `SttAdapter` / `TtsAdapter` / `LlmAdapter` / `TelephonyAdapter` |
| Media Gateway (edge VAD, barge-in, 8 kHz) | §7.1/§7.2 | `MediaGateway` (endpointing, barge-in, ölü hava sayacı) |
| Conversation Orchestrator (bağımsız) | §6, ADR-001 | `Orchestrator` — STT/LLM/TTS'e **doğrudan değil, SPI ile** bağlı |
| Turn State Machine (LISTEN→CAPTURE→THINK→ACT→SPEAK) | §6.1 | `VALID_TRANSITIONS` + `_run_turn` + `_speak` |
| Barge-in (SPEAK→CAPTURE, TTS cancel ≤200ms) | §6.1, FR-RTC-002, NFR 10.1 | `_speak(barge_in_after_ms=...)` → `tts.cancel_latency()` |
| Fallback (primary→secondary→deterministic) | §8.3, FR-STT-008 | `_stt_with_fallback` (TRANSFER = deterministic son çare) |
| Session memory (oturum sonu kalıcılaştırma) | §6.2 | `Orchestrator.session_memory` + `session_persist` olayı |
| Tenant context propagation (correlation_id) | §13.3, §17.1 | `EventLog` — her olayda `correlation_id`+`tenant_id` |
| Gecikme bütçesi (kalem kırılımı) | §20 | `budget` kalemleri (endpointing/stt/orch/rag/llm/tts/network/tool) |
| AI şeffaflık bildirimi (karşılama) | BRD §5/§14.2 | agent-greeting turu (`disclosure=True`, cache hit) |

## 3. Turn state machine

`VALID_TRANSITIONS` SAD §6.1 diyagramını kodlar; her geçiş bu kümede değilse `INVALID transition`
hatası kaydedilir (hard kapı bunu yakalar). Tipik bir kullanıcı turu:

```
LISTEN ──speech_start──► CAPTURE ──endpoint(VAD)──► (STT final) ──► THINK
   ▲                                                                  │
   │ speak_complete                                    tool? ──► ACT ─┘ (tool_exec, idempotency)
   │                                                                  │
 SPEAK ◄── response ready (LLM first token) ◄─────────────────────── THINK
   │
   └─ barge_in ──► (TTS cancel ≤200ms) ──► CAPTURE  (kullanıcıyı yeniden dinle)
```

- **THINK:** policy pre-check (input guard) + LLM Router (tier seçimi) + gerekirse RAG retrieval.
- **ACT:** yalnız tool gerekiyorsa; schema-validated çağrı + idempotency key (FR-TOOL-003/009).
- **SPEAK:** TTS first-byte → ağ → ses. Barge-in olursa TTS iptal edilir, SPEAK→CAPTURE.
- **TRANSFER/END:** STT tamamen başarısız olursa deterministic son çare → TRANSFER (human handoff);
  çağrı bitince session memory kalıcılaştırılır → END.

## 4. Gecikme bütçesi (SAD §20) — yumuşak rapor

PoC, her turda **end-of-utterance → ilk agent sesi** gecikmesini SAD §20 kalemlerine ayırarak
raporlar (sanal saat; varsayılanlar §20 orta-noktası):

| Kalem | PoC varsayılan | SAD §20 P95 bandı |
|-------|----------------|--------------------|
| Endpointing (VAD) | 160–200 ms (senaryo) | 150–250 ms |
| STT final | 130 ms | 100–200 ms |
| Orchestrator+policy+routing | 8 ms | ≤50 ms |
| RAG retrieval (varsa) | 140 ms | 100–200 ms |
| LLM first token | 220 (küçük)/320 (büyük) | 200–400 ms |
| TTS first byte | 120 ms (cache hit ~0) | 100–200 ms |
| Ağ/medya | 60 ms | 50–100 ms |
| Tool overhead (varsa) | 80–95 ms | ≤100 ms |

İllüstratif happy-path koşumunda **P50 ≈ 578 ms / P95 ≈ 669 ms** (≤1.200 ms hedefi içinde, yeşil).
**Bu rakamlar mimari kanıttır, ölçüm değildir** — gerçek değerler 0.3.2 canlı PoC'ta toplanır.

## 5. 0.3.1 kabul kapısı (HARD invariant'lar)

Çıkış kodunu (`run`: 0=geçti, 1=kaldı) **yalnız bu invariant'lar** belirler; gecikme yumuşaktır.

| # | Kapı | Doğrulama |
|---|------|-----------|
| 1 | `call_lifecycle` | `call_answered` + `call_ended` olayları var |
| 2 | `turn_completed` | ≥1 kullanıcı turu SPEAK'e ulaştı |
| 3 | `state_machine_valid` | Geçersiz state geçişi yok (SAD §6.1) |
| 4 | `spi_seams_invoked` | Her tamamlanan turda STT+LLM+TTS+Telephony SPI çağrıldı |
| 5 | `ai_disclosure_first` | AI şeffaflık bildirimi ilk kullanıcı turundan önce (BRD §14.2) |
| 6 | `context_propagation` | Her olayda `correlation_id`+`tenant_id` (SAD §13.3) |
| 7 | `barge_in_cut` | Barge-in turunda TTS iptal + kesme ≤200ms (NFR 10.1) |
| 8 | `no_dead_air` | Underrun=0 (FR-RES-009) |
| 9 | `no_fatal_errors` | INVALID geçiş / NFR ihlali yok |

## 6. Çalıştırma

```bash
# Credential'sız self-test (CI) — 21 invariant kontrolü
python3 docs/poc/e2e_inbound_poc.py selftest

# Bir inbound senaryosunu uçtan uca koştur
python3 docs/poc/e2e_inbound_poc.py run --scenario docs/poc/samples/inbound-happy-path.json --verbose

# Barge-in / STT fallback senaryoları
python3 docs/poc/e2e_inbound_poc.py run --scenario docs/poc/samples/inbound-barge-in.json
python3 docs/poc/e2e_inbound_poc.py run --scenario docs/poc/samples/inbound-stt-fallback.json

# Makine-okunur çıktı (özet+olay+kapı)
python3 docs/poc/e2e_inbound_poc.py run --scenario .../inbound-happy-path.json --json-out /tmp/poc.json

# Senaryo şeması
python3 docs/poc/e2e_inbound_poc.py schema
```

Örnek senaryolar (`samples/`):
- `inbound-happy-path.json` — 4 turlu çağrı (intent → tool → RAG → kapanış), EN.
- `inbound-barge-in.json` — agent konuşurken kullanıcı keser (SPEAK→CAPTURE), TR + tool.
- `inbound-stt-fallback.json` — STT birincil hatası → ikincil STT, akış kesintisiz (FR-STT-008).

## 7. Bulgular ve sonraki adımlar

- ✅ **Mimari doğrulandı:** Bağımsız orchestrator + SPI seam + turn state machine + barge-in +
  fallback + context propagation **uçtan uca koşuyor**; üç senaryo da hard kapıdan geçti.
- ✅ **Gecikme bütçesi (illüstratif)** SAD §20 dağılımıyla tutarlı; tipik P95 < 1.200 ms.
- → **0.3.2** bu harness'ı temel alıp **gerçek/ölçülen** gecikme dağılımını (P50/P95/P99 + barge-in
  kesme) üretir; gecikme bu PoC'ta yumuşak bırakılan kapıyı **hard** yapar.
- → **0.3.3** density (oturum/worker) ölçer; **0.3.4** medya konumu deneyiyle **ADR-009**'u kapatır;
  **0.3.5** hot-path runtime (Go/Rust) dilini doğrular.
- → Canlı PoC'ta (gerçek credential) **0.2.6 provizyonel** sağlayıcı seçimi bağlanır; aynı SPI,
  gerçek adapter (DPA/alt-işleyen 17.2.2 ile birlikte).

> **Sır/credential repoya yazılmaz.** Gerçek sağlayıcı bağlantısı yalnız `--url`/ortam değişkeni ile
> (0.3.x canlı PoC). Bu harness ve senaryolar **sentetik** (FR-TST-008) — gerçek müşteri verisi yok.
