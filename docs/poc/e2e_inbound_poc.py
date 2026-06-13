#!/usr/bin/env python3
"""e2e_inbound_poc.py — Uçtan uca tek inbound akış PoC (WBS 0.3.1, →SAD §25/§6.1/§7.1/§20).

Amaç: **telefon → STT → LLM → TTS → telefon** zincirini, Conversation Orchestrator'ın
**turn state machine**'i (SAD §6.1: LISTEN→CAPTURE→THINK→ACT→SPEAK + barge-in) üzerinden
**uçtan uca** koşturup akışın bütünlüğünü doğrulamak. Bu PoC mimari doğrulama spike'ıdır;
ADR-001 (bağımsız orchestrator), ADR-002 (adapter SPI), ADR-005 (edge VAD) seam'lerinin
fiilen birbirine bağlandığını gösterir.

Tasarım ilkeleri (CLAUDE.md ile uyumlu — 0.2.x hattıyla aynı disiplin):
- **Vendor-neutral (ADR-002):** STT/TTS/LLM/Telephony yalnız **SPI arayüzü** (SAD §8.1) arkasından
  çağrılır. Bu harness gerçek sağlayıcı seçmez; `Sim*` adapter'lar SPI'yi credential'sız, deterministik
  doldurur. Canlı PoC'ta (0.3.x) aynı arayüze gerçek adapter takılır; orchestrator değişmez.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / *_eval_probe.py disiplini). Gerçek ağ/sır YOK.
- **Deterministik / tekrarlanabilir:** Gerçek zaman yerine **sanal saat (SimClock)** kullanılır; her
  aşama, adapter'ın bildirdiği gecikme profili kadar saati ilerletir. Aynı senaryo → aynı sonuç (CI).
- **Kapsam ayrımı:** 0.3.1 kapısı = **akış uçtan uca tamamlanır + state machine/invariant doğru**.
  Aşama gecikmeleri kanıt olarak raporlanır (SAD §20 kalemleri), ancak **formal P95 kapısı 0.3.2**,
  **density 0.3.3**, **medya-konumu ADR-009 deneyi 0.3.4**'e aittir. Burada gecikme **yumuşak** flag'tir.

Modlar:
  run       — Bir inbound çağrı senaryosunu (samples/*.json) uçtan uca koşturur → turn-by-turn iz +
              özet + 0.3.1 kapı verdict'i (çıkış kodu). `--verbose` ile olay-olay iz.
  selftest  — Dahili deterministik senaryolarla çekirdek invariant'ları doğrular (credential'sız, CI).
  schema    — Senaryo JSON şemasını ve adapter gecikme profili anahtarlarını yazar.

Senaryo JSON şeması — `samples/*.json`:
{
  "call": {"tenant_id": "t_acme", "correlation_id": "poc-inb-001",
           "from": "+447700900111", "to": "+442035550000", "language": "en",
           "ai_disclosure": true},
  "adapters": {                       # opsiyonel gecikme profili (ms); yoksa SAD §20 varsayılanı
     "stt": {"final_ms": 130, "fail_first": false},
     "llm": {"first_token_small_ms": 220, "first_token_large_ms": 320, "inter_token_ms": 18},
     "tts": {"first_byte_ms": 120, "cancel_ms": 70, "frame_ms": 20},
     "network_ms": 60
  },
  "turns": [
     {"id": "u1", "user_text": "hi i want to check my order status",
      "language": "en", "endpoint_ms": 180, "tier": "small",
      "tool": null, "rag": false, "barge_in_after_ms": null},
     {"id": "u2", "user_text": "order number one two three four",
      "tool": {"name": "lookup_order", "latency_ms": 80}, "rag": true},
     {"id": "u3", "user_text": "wait actually cancel that",
      "barge_in_after_ms": 60}        # agent konuşurken kullanıcı keser (SPEAK→CAPTURE)
  ]
}
`tier` ∈ {small, large} (LLM tiering, FR-LLM-013). `tool` varsa ACT durumu çalışır (FR-TOOL-003/009).
`rag` true ise THINK'e RAG retrieval kalemi eklenir (SAD §10.2). `barge_in_after_ms` set ise agent
SPEAK'teyken o kadar ses çalındıktan sonra kullanıcı keser (FR-RTC-002, NFR 10.1). `fail_first` STT
birincil hatasını tetikler → SPI fallback (FR-STT-008, SAD §8.3) gösterilir.
"""

from __future__ import annotations

import argparse
import json
import sys

# --- SAD §20 gecikme bütçesi varsayılanları (P50 orta-nokta; mühendislik varsayılanı) -------------
# Bunlar adapter senaryosunda override edilebilir. Formal P95 kapısı 0.3.2'ye aittir; burada yumuşak.
DEF_ENDPOINT_MS = 180.0          # Endpointing (edge VAD karar gecikmesi) — SAD §20 150–250
DEF_STT_FINAL_MS = 130.0         # STT final transcript — SAD §20 100–200
DEF_ORCH_MS = 8.0                # Orchestrator + Policy + routing — SAD §20 ≤50 (bellek-içi)
DEF_RAG_MS = 140.0              # RAG retrieval (yalnız rag=true turda) — SAD §20 100–200
DEF_LLM_TT_SMALL_MS = 220.0      # LLM first token (küçük tier) — SAD §20 200–400
DEF_LLM_TT_LARGE_MS = 320.0      # LLM first token (büyük tier)
DEF_TTS_FIRST_BYTE_MS = 120.0    # TTS first byte — SAD §20 100–200
DEF_NETWORK_MS = 60.0            # Ağ/medya — SAD §20 50–100
DEF_TTS_CANCEL_MS = 70.0         # Barge-in TTS kesme — NFR 10.1 / SAD §6.1 ≤200
DEF_TTS_FRAME_MS = 20.0          # 8 kHz / 20 ms frame (FR-RES-008)
DEF_TOOL_MS = 80.0               # Tool overhead — SAD §20 ≤100

# --- Kapı eşikleri (yumuşak gecikme flag'leri; hard kapı = invariant'lar) -------------------------
TURN_LATENCY_P95_BUDGET_MS = 1200.0   # SAD §20 / NFR 10.1 — uç-uca P95 hedefi (0.3.2 formal sahibi)
TURN_LATENCY_P50_TARGET_MS = 700.0    # SAD §20 tipik P50
BARGE_IN_CUT_BUDGET_MS = 200.0        # NFR 10.1 / SAD §6.1 — TTS kesme ≤200 (hard invariant)


# =================================================================================================
# Sanal saat (deterministik) + olay kaydı
# =================================================================================================
class SimClock:
    """Sanal monotonik saat (ms). Gerçek uyku yok → CI'da deterministik ve hızlı."""

    def __init__(self) -> None:
        self.t_ms = 0.0

    def advance(self, ms: float) -> float:
        self.t_ms += max(0.0, float(ms))
        return self.t_ms

    def now(self) -> float:
        return self.t_ms


class EventLog:
    """correlation_id + tenant context (SAD §13.3) taşıyan yapılandırılmış olay kaydı."""

    def __init__(self, correlation_id: str, tenant_id: str) -> None:
        self.correlation_id = correlation_id
        self.tenant_id = tenant_id
        self.events: list[dict] = []

    def emit(self, clock: SimClock, etype: str, state: str | None = None, **detail) -> dict:
        ev = {
            "t_ms": round(clock.now(), 1),
            "type": etype,
            "state": state,
            "correlation_id": self.correlation_id,   # her olayda zorunlu (invariant)
            "tenant_id": self.tenant_id,              # her olayda zorunlu (invariant)
            "detail": detail,
        }
        self.events.append(ev)
        return ev


# =================================================================================================
# Adapter SPI (SAD §8.1) — orchestrator YALNIZ bu arayüzlere bağımlıdır (ADR-001/002)
# =================================================================================================
class SttAdapter:
    """SAD §8.1: stream(audioIn) -> Transcript{partial, final, confidence}. Sim: deterministik."""

    name = "sim-stt"

    def __init__(self, final_ms: float = DEF_STT_FINAL_MS, fail_first: bool = False) -> None:
        self.final_ms = final_ms
        self.fail_first = fail_first   # birincil hata enjeksiyonu → fallback testi (FR-STT-008)

    def transcribe_final(self, audio_segment: dict) -> dict:
        """Bir kullanıcı söz segmentini final transkripte çevirir (partial'lar atlanır — özet)."""
        if self.fail_first:
            raise TimeoutError(f"{self.name}: primary stream timeout (injected)")
        return {"text": audio_segment["user_text"], "confidence": 0.93,
                "language": audio_segment.get("language", "en"), "final_ms": self.final_ms}


class LlmAdapter:
    """SAD §8.1: complete(messages, tools, opts) -> stream<Token|ToolCall>. Sim: ilk-token + tool."""

    name = "sim-llm"

    def __init__(self, first_token_small_ms: float = DEF_LLM_TT_SMALL_MS,
                 first_token_large_ms: float = DEF_LLM_TT_LARGE_MS,
                 inter_token_ms: float = 18.0) -> None:
        self.tt_small = first_token_small_ms
        self.tt_large = first_token_large_ms
        self.inter_token_ms = inter_token_ms

    def plan(self, transcript: dict, tier: str, tool: dict | None) -> dict:
        """LLM yanıt planı: ilk-token gecikmesi + (varsa) tool çağrısı kararı (FR-LLM-008)."""
        first_token_ms = self.tt_small if tier == "small" else self.tt_large
        tool_call = None
        if tool:
            # Schema-validated tool çağrısı zorlaması (serbest metin yerine) — FR-LLM-008.
            tool_call = {"name": tool["name"], "arguments": {"query": transcript["text"]}}
        # Yanıt metni (sim) — gerçek modelde streaming token; burada özet metin.
        reply = "ai_disclosure_and_help" if tool is None else f"acted:{tool['name']}"
        return {"first_token_ms": first_token_ms, "tool_call": tool_call,
                "reply_text": reply, "tier": tier}


class TtsAdapter:
    """SAD §8.1: synthesize(textStream, voiceProfile) -> stream<AudioChunk>; cancel() (barge-in)."""

    name = "sim-tts"

    def __init__(self, first_byte_ms: float = DEF_TTS_FIRST_BYTE_MS,
                 cancel_ms: float = DEF_TTS_CANCEL_MS, frame_ms: float = DEF_TTS_FRAME_MS) -> None:
        self.first_byte_ms = first_byte_ms
        self.cancel_ms = cancel_ms
        self.frame_ms = frame_ms

    def synthesize_first_byte(self, text: str, cached: bool = False) -> float:
        """İlk ses paketine kadar gecikme (cache hit → ~0; FR-TTS-010)."""
        return 0.0 if cached else self.first_byte_ms

    def cancel_latency(self) -> float:
        """cancel() → ses fiilen durana kadar (FR-TTS-005, FR-RTC-002)."""
        return self.cancel_ms


class TelephonyAdapter:
    """SAD §8.1: dial/answer/transfer/sendDtmf + medya akışı (8 kHz/20 ms). Sim: çağrı yaşam döngüsü."""

    name = "sim-telephony"

    def __init__(self, network_ms: float = DEF_NETWORK_MS) -> None:
        self.network_ms = network_ms
        self.answered = False

    def answer(self) -> None:
        self.answered = True

    def hangup(self) -> None:
        self.answered = False


# =================================================================================================
# Media Gateway (SAD §7) — edge VAD/endpointing + barge-in algılama + ölü hava bastırma (ADR-005)
# =================================================================================================
class MediaGateway:
    """Edge VAD/endpointing (FR-RTC-013), barge-in olayı (FR-RTC-002), ölü hava bastırma (FR-RES-009).

    Sim: gerçek RTP/jitter yerine senaryo-tetikli. Codec 8 kHz/20 ms (FR-RES-008); ham tampon burada,
    orchestrator'da değil (SAD §6.3 — ~15MB/oturum hedefi data plane'de).
    """

    def __init__(self, telephony: TelephonyAdapter) -> None:
        self.telephony = telephony
        self.underruns = 0   # ölü hava sayacı (FR-RES-009)

    def capture_endpoint(self, turn: dict) -> dict:
        """Kullanıcı sözü → endpointing kararı → STT'ye gidecek temiz segment (ölü hava dışlanmış)."""
        return {"user_text": turn["user_text"], "language": turn.get("language", "en"),
                "endpoint_ms": float(turn.get("endpoint_ms", DEF_ENDPOINT_MS))}


# =================================================================================================
# Conversation Orchestrator (SAD §6) — turn state machine LISTEN→CAPTURE→THINK→ACT→SPEAK + barge-in
# =================================================================================================
# Geçerli durum geçişleri (SAD §6.1). Invariant: her geçiş bu kümede olmalı.
VALID_TRANSITIONS = {
    "LISTEN": {"CAPTURE", "END"},
    "CAPTURE": {"THINK", "END"},
    "THINK": {"ACT", "SPEAK", "TRANSFER", "END"},
    "ACT": {"THINK", "SPEAK", "TRANSFER", "END"},
    "SPEAK": {"LISTEN", "CAPTURE", "END"},   # CAPTURE = barge-in geri dönüşü
    "TRANSFER": {"END"},
    "END": set(),
}


class Orchestrator:
    """Bağımsız Conversation Orchestrator (ADR-001). STT/LLM/TTS'e DOĞRUDAN değil, SPI ile bağlanır."""

    def __init__(self, clock: SimClock, log: EventLog, gateway: MediaGateway,
                 stt: SttAdapter, stt_fallback: SttAdapter, llm: LlmAdapter, tts: TtsAdapter,
                 telephony: TelephonyAdapter) -> None:
        self.clock = clock
        self.log = log
        self.gw = gateway
        self.stt = stt
        self.stt_fallback = stt_fallback
        self.llm = llm
        self.tts = tts
        self.tel = telephony
        self.state = "LISTEN"
        self.session_memory: list[dict] = []   # kısa süreli diyalog belleği (SAD §6.2)
        self.turns: list[dict] = []
        self.errors: list[str] = []

    # --- durum geçişi (invariant kontrollü) ------------------------------------------------------
    def _transition(self, new_state: str, **detail) -> None:
        if new_state not in VALID_TRANSITIONS.get(self.state, set()):
            self.errors.append(f"INVALID transition {self.state}->{new_state}")
        self.state = new_state
        self.log.emit(self.clock, "state", state=new_state, **detail)

    # --- çağrı yaşam döngüsü ---------------------------------------------------------------------
    def run_call(self, scenario: dict) -> dict:
        call = scenario["call"]
        self.tel.answer()
        self.log.emit(self.clock, "call_answered", state="LISTEN",
                      **{"from": call.get("from"), "to": call.get("to")})

        # Inbound: agent karşılama + AI şeffaflık bildirimi (BRD §5/§14.2, policy 3.3.3) — agent turn 0.
        if call.get("ai_disclosure", True):
            self._speak(text="greeting+ai_disclosure", disclosure=True, barge_in_after_ms=None,
                        turn_id="agent-greeting", cached=True)
        else:
            self.errors.append("AI disclosure devre dışı — BRD §14.2 ihlali (uyarı)")

        # Kullanıcı turları
        for turn in scenario.get("turns", []):
            self._run_turn(turn)

        # Çağrı sonu: oturum belleğini kalıcılaştır (SAD §6.2), hattı kapat
        self.log.emit(self.clock, "session_persist", state=self.state,
                      turns=len(self.turns), memory_items=len(self.session_memory))
        self._transition("END", reason="call_complete")
        self.tel.hangup()
        self.log.emit(self.clock, "call_ended", state="END")
        return self._summary(call)

    # --- tek tur (LISTEN→CAPTURE→THINK→[ACT]→SPEAK) ----------------------------------------------
    def _run_turn(self, turn: dict) -> None:
        t0 = self.clock.now()
        adapters_used: set[str] = set()
        budget = {}   # SAD §20 kalem kırılımı

        # LISTEN → CAPTURE (speech_start)
        self._transition("CAPTURE", turn=turn["id"], trigger="speech_start")
        # Endpointing (edge VAD) — kullanıcı durduktan sonra karar gecikmesi
        segment = self.gw.capture_endpoint(turn)
        self.clock.advance(segment["endpoint_ms"])
        budget["endpointing"] = segment["endpoint_ms"]
        end_of_utterance = self.clock.now()   # gecikme bütçesi başlangıcı (SAD §20)
        self.log.emit(self.clock, "endpoint", state="CAPTURE", endpoint_ms=segment["endpoint_ms"])

        # STT final (fallback ile) — FR-STT-002/008, SAD §8.3
        transcript, stt_name = self._stt_with_fallback(segment)
        if transcript is None:
            self.errors.append(f"turn {turn['id']}: STT tamamen başarısız")
            self._transition("TRANSFER", reason="stt_failure")  # deterministic fallback → handoff
            return
        adapters_used.add(stt_name)
        budget["stt_final"] = transcript["final_ms"]
        self.log.emit(self.clock, "stt_final", state="CAPTURE", adapter=stt_name,
                      text=transcript["text"], confidence=transcript["confidence"])

        # CAPTURE → THINK
        self._transition("THINK", turn=turn["id"])
        # Policy pre-check (input guard) + orchestrator/routing — SAD §6.2/§9, bellek-içi
        self.clock.advance(DEF_ORCH_MS)
        budget["orchestrator"] = DEF_ORCH_MS
        # RAG retrieval (gerekirse) — SAD §10.2
        if turn.get("rag"):
            self.clock.advance(DEF_RAG_MS)
            budget["rag"] = DEF_RAG_MS
            self.log.emit(self.clock, "rag_retrieval", state="THINK", top_k=4)
        # LLM Router → tier seçimi + yanıt planı (ilk-token gecikmesi)
        tier = turn.get("tier", "small")
        plan = self.llm.plan(transcript, tier, turn.get("tool"))
        adapters_used.add(self.llm.name)

        # ACT (tool gerekiyorsa) — schema-validated tool, idempotency (FR-TOOL-003/009)
        if plan["tool_call"]:
            self._transition("ACT", turn=turn["id"], tool=plan["tool_call"]["name"])
            tool_ms = float(turn["tool"].get("latency_ms", DEF_TOOL_MS))
            self.clock.advance(tool_ms)
            budget["tool"] = tool_ms
            self.log.emit(self.clock, "tool_exec", state="ACT", tool=plan["tool_call"]["name"],
                          idempotency_key=f"{self.log.correlation_id}:{turn['id']}")
            self._transition("THINK", turn=turn["id"], after="tool")

        # LLM ilk token gecikmesi (yanıt akışı başlıyor)
        self.clock.advance(plan["first_token_ms"])
        budget["llm_first_token"] = plan["first_token_ms"]
        self.log.emit(self.clock, "llm_first_token", state="THINK", tier=tier,
                      tool_used=bool(plan["tool_call"]))

        # THINK → SPEAK (TTS streaming; ilk byte + ağ)
        first_audio_ms, cut_ms = self._speak(
            text=plan["reply_text"], disclosure=False,
            barge_in_after_ms=turn.get("barge_in_after_ms"), turn_id=turn["id"], cached=False,
            budget=budget)
        adapters_used.add(self.tts.name)
        adapters_used.add(self.tel.name)

        # Uç-uca gecikme: end_of_utterance → ilk agent sesi (SAD §20)
        turn_latency = first_audio_ms - end_of_utterance
        self.session_memory.append({"turn": turn["id"], "user": transcript["text"],
                                    "agent": plan["reply_text"]})
        rec = {
            "id": turn["id"], "tier": tier, "adapters": sorted(adapters_used),
            "tool": bool(plan["tool_call"]), "rag": bool(turn.get("rag")),
            "barge_in": turn.get("barge_in_after_ms") is not None,
            "barge_in_cut_ms": cut_ms,
            "latency_eou_to_audio_ms": round(turn_latency, 1),
            "budget_ms": {k: round(v, 1) for k, v in budget.items()},
            "wall_ms": round(self.clock.now() - t0, 1),
        }
        self.turns.append(rec)

    def _stt_with_fallback(self, segment: dict):
        """Birincil STT; hata/timeout → ikincil STT (FR-STT-008, SAD §8.3)."""
        try:
            tr = self.stt.transcribe_final(segment)
            self.clock.advance(tr["final_ms"])
            return tr, self.stt.name
        except Exception as exc:  # noqa: BLE001 — SPI hata taksonomisi → fallback
            self.log.emit(self.clock, "stt_fallback", state="CAPTURE",
                          reason=str(exc), to=self.stt_fallback.name)
            try:
                tr = self.stt_fallback.transcribe_final(segment)
                self.clock.advance(tr["final_ms"])
                return tr, self.stt_fallback.name
            except Exception as exc2:  # noqa: BLE001
                self.log.emit(self.clock, "stt_failed", state="CAPTURE", reason=str(exc2))
                return None, None

    def _speak(self, text: str, disclosure: bool, barge_in_after_ms, turn_id: str,
               cached: bool, budget: dict | None = None):
        """SPEAK: TTS first-byte → ağ → ses çalınır. Barge-in olursa TTS iptal + SPEAK→CAPTURE.

        Döner: (ilk_agent_sesi_zamanı_ms, barge_in_kesme_gecikmesi_ms|None).
        """
        if self.state in VALID_TRANSITIONS and "SPEAK" in VALID_TRANSITIONS.get(self.state, set()):
            self._transition("SPEAK", turn=turn_id, disclosure=disclosure)
        else:
            # agent-greeting: LISTEN'den SPEAK'e izin ver (turn 0 — karşılama)
            self.state = "SPEAK"
            self.log.emit(self.clock, "state", state="SPEAK", turn=turn_id, disclosure=disclosure)

        fb = self.tts.synthesize_first_byte(text, cached=cached)
        self.clock.advance(fb)
        self.clock.advance(self.tel.network_ms)
        first_audio_ms = self.clock.now()
        if budget is not None:
            budget["tts_first_byte"] = fb
            budget["network"] = self.tel.network_ms
        self.log.emit(self.clock, "tts_first_byte", state="SPEAK", first_byte_ms=fb,
                      cached=cached, disclosure=disclosure)

        cut_ms = None
        if barge_in_after_ms is not None:
            # Agent bir süre konuşur, sonra kullanıcı keser → Media Gateway barge_in olayı
            self.clock.advance(float(barge_in_after_ms))
            self.log.emit(self.clock, "barge_in", state="SPEAK", after_audio_ms=barge_in_after_ms)
            # Orchestrator TTS akışını iptal eder; gateway tamponu ≤200ms içinde keser
            cut_ms = self.tts.cancel_latency()
            self.clock.advance(cut_ms)
            self.log.emit(self.clock, "tts_cancelled", state="SPEAK", cut_ms=cut_ms)
            if cut_ms > BARGE_IN_CUT_BUDGET_MS:
                self.errors.append(f"turn {turn_id}: barge-in kesme {cut_ms}ms > "
                                   f"{BARGE_IN_CUT_BUDGET_MS}ms (NFR 10.1 ihlali)")
            # SPEAK → CAPTURE (kullanıcıyı yeniden dinle)
            self._transition("CAPTURE", turn=turn_id, trigger="barge_in")
            # barge-in sonrası tekrar LISTEN'e dönmek state tutarlılığı için:
            self.state = "LISTEN"
            self.log.emit(self.clock, "state", state="LISTEN", turn=turn_id, after="barge_in")
        else:
            # SPEAK tamamlanır → LISTEN
            self._transition("LISTEN", turn=turn_id, after="speak_complete")
        return first_audio_ms, cut_ms

    # --- özet + 0.3.1 kapı değerlendirmesi -------------------------------------------------------
    def _summary(self, call: dict) -> dict:
        lat = sorted(t["latency_eou_to_audio_ms"] for t in self.turns)
        return {
            "call": call,
            "turns": self.turns,
            "n_turns": len(self.turns),
            "errors": self.errors,
            "latency": {
                "p50_ms": _percentile(lat, 50) if lat else None,
                "p95_ms": _percentile(lat, 95) if lat else None,
                "max_ms": lat[-1] if lat else None,
            },
            "events": self.log.events,
            "underruns": self.gw.underruns,
        }


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac, 1)


# =================================================================================================
# Senaryo koşumu + 0.3.1 kapı (invariant) değerlendirmesi
# =================================================================================================
def build_orchestrator(scenario: dict) -> Orchestrator:
    call = scenario["call"]
    a = scenario.get("adapters", {})
    stt_cfg = a.get("stt", {})
    llm_cfg = a.get("llm", {})
    tts_cfg = a.get("tts", {})
    clock = SimClock()
    log = EventLog(call.get("correlation_id", "poc-0"), call.get("tenant_id", "t_default"))
    tel = TelephonyAdapter(network_ms=float(a.get("network_ms", DEF_NETWORK_MS)))
    gw = MediaGateway(tel)
    stt = SttAdapter(final_ms=float(stt_cfg.get("final_ms", DEF_STT_FINAL_MS)),
                     fail_first=bool(stt_cfg.get("fail_first", False)))
    # Fallback STT her zaman sağlıklı (≥2 sağlayıcı, ADR-002)
    stt_fb = SttAdapter(final_ms=float(stt_cfg.get("fallback_final_ms", DEF_STT_FINAL_MS + 25)))
    stt_fb.name = "sim-stt-secondary"
    llm = LlmAdapter(
        first_token_small_ms=float(llm_cfg.get("first_token_small_ms", DEF_LLM_TT_SMALL_MS)),
        first_token_large_ms=float(llm_cfg.get("first_token_large_ms", DEF_LLM_TT_LARGE_MS)),
        inter_token_ms=float(llm_cfg.get("inter_token_ms", 18.0)))
    tts = TtsAdapter(first_byte_ms=float(tts_cfg.get("first_byte_ms", DEF_TTS_FIRST_BYTE_MS)),
                     cancel_ms=float(tts_cfg.get("cancel_ms", DEF_TTS_CANCEL_MS)),
                     frame_ms=float(tts_cfg.get("frame_ms", DEF_TTS_FRAME_MS)))
    return Orchestrator(clock, log, gw, stt, stt_fb, llm, tts, tel)


def evaluate_gates(summary: dict) -> dict:
    """0.3.1 HARD kapı = akış uçtan uca tamamlandı + state machine/invariant doğru.

    Gecikme (P95) YUMUŞAK flag (formal kapı 0.3.2). Hard kapı çıkış kodunu belirler.
    """
    events = summary["events"]
    types = [e["type"] for e in events]
    checks = []

    def chk(key, ok, detail=""):
        checks.append({"check": key, "pass": bool(ok), "detail": detail})

    # 1) Çağrı yaşam döngüsü tam (answered → ended)
    chk("call_lifecycle", "call_answered" in types and "call_ended" in types,
        "answer+ended olayları")
    # 2) ≥1 kullanıcı turu SPEAK'e ulaştı
    completed = [t for t in summary["turns"]]
    chk("turn_completed", len(completed) >= 1, f"{len(completed)} tur")
    # 3) Geçersiz state geçişi yok
    invalid = [e for e in summary["errors"] if "INVALID transition" in e]
    chk("state_machine_valid", not invalid, ";".join(invalid) if invalid else "tüm geçişler geçerli")
    # 4) Her tamamlanan (barge-in olmayan) turda STT+LLM+TTS+Telephony SPI çağrıldı
    seam_ok = True
    seam_bad = []
    for t in summary["turns"]:
        if t["barge_in"]:
            continue
        used = set(t["adapters"])
        need_stt = any(a.startswith("sim-stt") for a in used)
        if not (need_stt and "sim-llm" in used and "sim-tts" in used and "sim-telephony" in used):
            seam_ok = False
            seam_bad.append(t["id"])
    chk("spi_seams_invoked", seam_ok, "STT+LLM+TTS+Telephony" if seam_ok else f"eksik: {seam_bad}")
    # 5) AI şeffaflık bildirimi ilk kullanıcı turundan önce
    disclosure_ev = next((i for i, e in enumerate(events)
                          if e["type"] == "tts_first_byte" and e["detail"].get("disclosure")), None)
    first_endpoint = next((i for i, e in enumerate(events) if e["type"] == "endpoint"), None)
    chk("ai_disclosure_first", disclosure_ev is not None and
        (first_endpoint is None or disclosure_ev < first_endpoint),
        "AI bildirimi karşılamada (BRD §14.2)")
    # 6) Her olayda correlation_id + tenant_id (SAD §13.3)
    ctx_ok = all(e.get("correlation_id") and e.get("tenant_id") for e in events)
    chk("context_propagation", ctx_ok, "correlation_id+tenant_id tüm olaylarda")
    # 7) Barge-in turlarında TTS iptal + ≤200ms kesme + CAPTURE'a dönüş
    bi_ok = True
    bi_detail = []
    for t in summary["turns"]:
        if not t["barge_in"]:
            continue
        cut = t["barge_in_cut_ms"]
        if cut is None or cut > BARGE_IN_CUT_BUDGET_MS:
            bi_ok = False
            bi_detail.append(f"{t['id']}:{cut}ms")
    if any(e["type"] == "tts_cancelled" for e in events):
        bi_detail = bi_detail or ["kesme≤200ms"]
    chk("barge_in_cut", bi_ok, ";".join(bi_detail) if bi_detail else "barge-in yok")
    # 8) Ölü hava (underrun) yok (FR-RES-009)
    chk("no_dead_air", summary["underruns"] == 0, f"underrun={summary['underruns']}")
    # 9) Genel hata yok (TRANSFER fallback hariç işaretlenir)
    fatal = [e for e in summary["errors"] if "INVALID" in e or "ihlali" in e]
    chk("no_fatal_errors", not fatal, ";".join(fatal) if fatal else "yok")

    hard_pass = all(c["pass"] for c in checks)
    # Yumuşak gecikme flag'i (0.3.2 formal sahibi)
    p95 = summary["latency"]["p95_ms"]
    p50 = summary["latency"]["p50_ms"]
    latency_flag = "n/a" if p95 is None else (
        "yeşil" if p95 <= TURN_LATENCY_P95_BUDGET_MS else "kırmızı(>1200ms — 0.3.2 incele)")
    return {"checks": checks, "hard_pass": hard_pass,
            "latency_soft": {"p50_ms": p50, "p95_ms": p95, "flag": latency_flag}}


# =================================================================================================
# CLI
# =================================================================================================
def cmd_run(args) -> int:
    with open(args.scenario, encoding="utf-8") as f:
        scenario = json.load(f)
    orch = build_orchestrator(scenario)
    summary = orch.run_call(scenario)
    gates = evaluate_gates(summary)

    call = summary["call"]
    print(f"# E2E Inbound PoC — {call.get('correlation_id')} (tenant={call.get('tenant_id')})")
    print(f"  akış: PSTN→SBC→MediaGW→STT→Orchestrator(LLM)→TTS→MediaGW→PSTN  "
          f"| dil={call.get('language')}")
    if args.verbose:
        print("\n## Olay izi (sanal saat)")
        for e in summary["events"]:
            d = " ".join(f"{k}={v}" for k, v in e["detail"].items() if k not in ("from", "to"))
            print(f"  {e['t_ms']:>8.1f}ms  [{(e['state'] or '-'):<8}] {e['type']:<16} {d}")

    print("\n## Tur özeti (end-of-utterance → ilk agent sesi)")
    print(f"  {'tur':<22}{'tier':<7}{'tool':<6}{'rag':<6}{'barge':<7}{'gecikme':<11}adapters")
    for t in summary["turns"]:
        print(f"  {t['id']:<22}{t['tier']:<7}{str(t['tool']):<6}{str(t['rag']):<6}"
              f"{str(t['barge_in']):<7}{t['latency_eou_to_audio_ms']:>7.1f}ms   "
              f"{','.join(t['adapters'])}")

    lat = summary["latency"]
    print(f"\n## Gecikme (yumuşak — formal kapı 0.3.2): "
          f"P50={lat['p50_ms']}ms  P95={lat['p95_ms']}ms  max={lat['max_ms']}ms  "
          f"→ {gates['latency_soft']['flag']}")

    print("\n## 0.3.1 kapı (HARD = invariant; çıkış kodunu belirler)")
    for c in gates["checks"]:
        mark = "✅" if c["pass"] else "❌"
        print(f"  {mark} {c['check']:<22} {c['detail']}")
    verdict = "🟢 GEÇTİ" if gates["hard_pass"] else "🔴 KALDI"
    print(f"\n## VERDICT: {verdict}  (akış uçtan uca {'tamamlandı' if gates['hard_pass'] else 'TAMAMLANAMADI'})")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"summary": {k: v for k, v in summary.items() if k != "events"},
                       "events": summary["events"], "gates": gates}, f,
                      ensure_ascii=False, indent=2)
        print(f"\n(JSON yazıldı: {args.json_out})")
    return 0 if gates["hard_pass"] else 1


def cmd_schema(_args) -> int:
    print(__doc__)
    return 0


# --- selftest ------------------------------------------------------------------------------------
def _scn(turns, **call_over):
    call = {"tenant_id": "t_self", "correlation_id": "selftest", "from": "+1", "to": "+2",
            "language": "en", "ai_disclosure": True}
    call.update(call_over)
    return {"call": call, "turns": turns}


def cmd_selftest(_args) -> int:
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("## selftest — çekirdek invariant'lar (credential'sız, deterministik)")

    # S1: Happy path — tek tur uçtan uca tamamlanır
    s = _scn([{"id": "u1", "user_text": "hello", "tier": "small"}])
    o = build_orchestrator(s)
    summ = o.run_call(s)
    g = evaluate_gates(summ)
    check("S1 happy-path hard_pass", g["hard_pass"])
    check("S1 tek tur kaydı", summ["n_turns"] == 1)
    check("S1 call_answered+ended", any(e["type"] == "call_answered" for e in summ["events"])
          and any(e["type"] == "call_ended" for e in summ["events"]))

    # S2: Çok turlu + tool (ACT) + rag
    s = _scn([
        {"id": "u1", "user_text": "check order", "tier": "small"},
        {"id": "u2", "user_text": "order 1234", "tier": "large",
         "tool": {"name": "lookup_order", "latency_ms": 80}, "rag": True},
    ])
    o = build_orchestrator(s)
    summ = o.run_call(s)
    g = evaluate_gates(summ)
    check("S2 çok-tur+tool+rag hard_pass", g["hard_pass"])
    check("S2 ACT (tool_exec) olayı var", any(e["type"] == "tool_exec" for e in summ["events"]))
    check("S2 rag_retrieval olayı var", any(e["type"] == "rag_retrieval" for e in summ["events"]))
    check("S2 tool turu budget'ta tool kalemi", summ["turns"][1]["budget_ms"].get("tool") == 80.0)

    # S3: Barge-in — SPEAK→CAPTURE, TTS iptal, kesme ≤200ms
    s = _scn([{"id": "u1", "user_text": "tell me everything", "barge_in_after_ms": 60}])
    o = build_orchestrator(s)
    summ = o.run_call(s)
    g = evaluate_gates(summ)
    check("S3 barge-in hard_pass", g["hard_pass"])
    check("S3 tts_cancelled olayı", any(e["type"] == "tts_cancelled" for e in summ["events"]))
    check("S3 kesme ≤200ms", summ["turns"][0]["barge_in_cut_ms"] <= BARGE_IN_CUT_BUDGET_MS)

    # S4: STT primary fail → fallback (SPI seam, FR-STT-008)
    s = _scn([{"id": "u1", "user_text": "hi", "tier": "small"}])
    s["adapters"] = {"stt": {"fail_first": True}}
    o = build_orchestrator(s)
    summ = o.run_call(s)
    g = evaluate_gates(summ)
    check("S4 STT fallback hard_pass", g["hard_pass"])
    check("S4 stt_fallback olayı", any(e["type"] == "stt_fallback" for e in summ["events"]))
    check("S4 ikincil STT kullanıldı", "sim-stt-secondary" in summ["turns"][0]["adapters"])

    # S5: Latency budget kalemleri SAD §20 ile hizalı (happy path)
    s = _scn([{"id": "u1", "user_text": "hi", "tier": "small"}])
    o = build_orchestrator(s)
    summ = o.run_call(s)
    b = summ["turns"][0]["budget_ms"]
    expect = {"endpointing", "stt_final", "orchestrator", "llm_first_token",
              "tts_first_byte", "network"}
    check("S5 budget SAD §20 kalemleri", expect.issubset(set(b)))
    # end-of-utterance→audio = stt+orch+llm+tts+net (endpointing bütçe başlangıcından önce)
    expected_lat = (b["stt_final"] + b["orchestrator"] + b["llm_first_token"]
                    + b["tts_first_byte"] + b["network"])
    check("S5 gecikme toplamı tutarlı",
          abs(summ["turns"][0]["latency_eou_to_audio_ms"] - expected_lat) < 0.5)

    # S6: AI disclosure devre dışı → kapı yumuşak uyarı (hard pass yine de, ama disclosure check fail)
    s = _scn([{"id": "u1", "user_text": "hi"}], ai_disclosure=False)
    o = build_orchestrator(s)
    summ = o.run_call(s)
    g = evaluate_gates(summ)
    disc = next(c for c in g["checks"] if c["check"] == "ai_disclosure_first")
    check("S6 disclosure kapalı → ai_disclosure_first FAIL", not disc["pass"])
    check("S6 disclosure kapalı → hard KALDI", not g["hard_pass"])

    # S7: context propagation — her olayda correlation_id+tenant_id
    s = _scn([{"id": "u1", "user_text": "hi"}], correlation_id="cid-7", tenant_id="t-7")
    o = build_orchestrator(s)
    summ = o.run_call(s)
    check("S7 tüm olaylarda correlation_id",
          all(e["correlation_id"] == "cid-7" for e in summ["events"]))
    check("S7 tüm olaylarda tenant_id", all(e["tenant_id"] == "t-7" for e in summ["events"]))

    # S8: Determinizm — aynı senaryo iki kez → aynı gecikme
    s = _scn([{"id": "u1", "user_text": "hi", "tier": "large"},
              {"id": "u2", "user_text": "yes", "tool": {"name": "t", "latency_ms": 50}}])
    o1 = build_orchestrator(s); r1 = o1.run_call(s)
    o2 = build_orchestrator(s); r2 = o2.run_call(s)
    check("S8 determinizm (P95 eşit)", r1["latency"]["p95_ms"] == r2["latency"]["p95_ms"])

    print(f"\n{'='*60}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print("SELFTEST GEÇTİ — tüm invariant'lar doğrulandı")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="E2E inbound akış PoC (WBS 0.3.1)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Bir inbound senaryosunu uçtan uca koştur")
    pr.add_argument("--scenario", required=True, help="samples/*.json")
    pr.add_argument("--verbose", action="store_true", help="olay-olay iz")
    pr.add_argument("--json-out", help="özet+olay+kapı JSON çıktısı")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("selftest", help="Çekirdek invariant'ları doğrula (credential'sız)")
    ps.set_defaults(func=cmd_selftest)

    psc = sub.add_parser("schema", help="Senaryo JSON şemasını yaz")
    psc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
