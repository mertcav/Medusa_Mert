# `runtime/session-memory/` — WBS 3.2.1 Kısa süreli diyalog belleği + oturum sonu kalıcılaştırma

Conversation Orchestrator oturum aktöründe (SAD §6.2/§6.3) çalışan **Session Memory** bileşeni.
İki sorumluluk:

1. **Kısa süreli diyalog belleği** — turn'leri (caller/agent/human) **sınırlı** bir pencerede bellekte
   tutar (append-only · monoton seq · idempotent); pencere taşınca en eski turn'ler **özete katlanır**
   (fold) — düşürülmez. Çalışan kopya Redis `session_state`/`session_summary`'de (cache/ 1.1.5,
   `pii=true`, ephemeral, `delete_on_call_end`).
2. **Oturum sonu kalıcılaştırma** — çağrı her bitişte (normal/transfer/error/abandon) **durable** kayda
   yazılır: `transcript`+`transcript_segment` (PostgreSQL db/ 1.1.3, RLS, `redaction_state='pending'`
   FR-REC-004) + recording pointer (objstore/ 1.1.6) + `call.completed` olayı (eventstream/ 1.1.8).
   **Durable persist başarılı olmadan** ephemeral `session_state` **silinmez** (`persist_before_delete`)
   — sessiz veri kaybı yok; persist idempotent + at-least-once retry.

Vendor-neutral (ADR-002), stdlib-only, credential-free, deterministik (olay-tetikli, sanal saat,
random YOK).

## Dosyalar

| Dosya | Rol |
|-------|-----|
| `session-memory-spec.json` | **Kaynak doğruluk:** bellek modeli + persistence + cleanup + kapılar (M1–M10) |
| `session-memory.md` | Tasarım: bellek penceresi, katlama seam'i, oturum-sonu persist akışı, HARD kapılar |
| `session_memory_probe.py` | `validate` / `simulate <sample>` / `selftest` / `schema` — deterministik Session Memory |
| `config/session-memory-profiles.json` | 3 profil: pilot-default · enterprise-long-call · high-density-tight |
| `samples/mem-*.json` | happy / windowed-fold / idempotent-replay / end-transfer / degraded(fail) |
| `tests/session_memory_behavior_test.py` | T1–T8 davranış kapısı |
| `run_live_test.sh` | statik kapı + sample (+ canlı NOT, `ORCHESTRATOR_URL`) |

## Hızlı başlangıç

```bash
cd runtime/session-memory
python3 session_memory_probe.py validate       # 57/57 PASS
python3 session_memory_probe.py selftest       # 53/53 PASS
python3 tests/session_memory_behavior_test.py  # 26/26 PASS
./run_live_test.sh                             # hepsi + 5 sample
```

## Model özeti

```
turn = {turn_id, speaker∈{caller,agent,human}, seq (monoton), approx_tokens, t}
  pencere: append-only + idempotent (aynı turn_id → tek kayıt) + sınırlı (window_max_turns / token_soft_limit)
  taşma   → en eski turn'ler ÖZETE katlanır (fold → session_summary) ; DÜŞMEZ (içerik korunur)
  bitiş   → DURABLE persist (transcript+segment+recording+olay, redaction=pending) ; persisted == captured
  sıra    → persist BAŞARILI → ephemeral session_state SİL (persist_before_delete) ; başarısız → TUT (TTL retry)
```

**HARD kapılar:** M1 sınırlı-bellek · M2 sıra+idempotent · M3 oturum-sonu-persist (persist_before_delete) ·
M4 ephemeral-temizlik (kaçak=0) · M5 kayıpsız (persisted==captured) · M6 redaction (kart/OTP düz-metin=0,
`pending`) · M7 tenant-izolasyon.

Kapsam dışı: token-sınırı özetleme **motoru** → **3.2.2** (FR-LLM-005/FR-RES-010); versiyonlu prompt
enjeksiyonu → **3.2.3**; per-call bellek bütçe izleme/sınırlama → **3.1.4** (dialogue_memory'yi besler);
Redis keyspace/TTL → **1.1.5**; transcript şeması/RLS → **1.1.3**; PII redaction L7 motoru → **3.3.x**.
Sır/PII/ham metin/transkript repoya yazılmaz.
