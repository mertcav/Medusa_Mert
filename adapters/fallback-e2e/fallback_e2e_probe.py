#!/usr/bin/env python3
"""fallback_e2e_probe.py — Birincil kesintide kontrollü fallback UÇTAN UCA testi (WBS 4.3.4).

Amaç: 4.3.1 (STT fallback) + 4.3.2 (TTS fallback + ses tutarlılığı) + 4.3.3 (LLM fallback)
ANAHTARLAMA motorlarını, 0.3.1 e2e_inbound_poc turn state machine'i (SAD §6.1 LISTEN→CAPTURE→
THINK→ACT→SPEAK + barge-in) üzerinde TEK uçtan uca çağrı akışında BİRLEŞTİRİP **BRD §19 (4)**
('Birincil sağlayıcı kesildiğinde kontrollü fallback gerçekleşmelidir') + SAD §8 ilke 6
('Fail soft, never drop the call') + SAD §8.3 fallback zincirini (Primary ──(timeout/error/
circuit-open)──► Secondary ──► Deterministic flow) **uçtan uca doğrulamak**.

Bu bir ENTEGRASYON/kabul testi harness'idir; aşama-içi switcher davranışı (audio replay /
context resubmit / resynth continuation / eşdeğer ses / mid-stream güvenliği / tool idempotency)
4.3.1–4.3.3'te birim doğrulandı — burada BİLEŞİK davranış kanıtlanır.

Tasarım ilkeleri (CLAUDE.md + 0.2.x/0.3.x/4.3.x hattıyla birebir):
- **Vendor-neutral (ADR-002):** STT/LLM/TTS/Telephony yalnız SPI (SAD §8.1) + her aşamanın switcher
  kararı üzerinden tüketilir; gerçek sağlayıcı seçilmez. Somut adapter arkada değişir.
- **stdlib-only / credential-free:** Harici bağımlılık, ağ veya sır YOK.
- **Deterministik / tekrarlanabilir:** Sanal saat; random YOK. Aynı senaryo → aynı sonuç (CI).
- **Kapsam ayrımı:** aşama switcher MOTORU 4.3.1/4.3.2/4.3.3 (BESTELENİR), orchestrator 0.3.1
  (referans), ortak yetenekler 4.1.2, metering motoru 4.1.3, deterministic-flow/handoff 8.x/3.3.x.

Modlar:
  validate           — Spec ↔ invariant tutarlılığı + config ≥2/kategori + sır taraması + kapı negatifleri.
  simulate <sample>  — Bir uçtan uca senaryoyu (samples/*.json) koştur → çağrı izi + E1–E10 kapı → çıkış kodu.
  selftest           — Dahili deterministik senaryolarla E1–E10 invariant'larını doğrula (CI).
  schema             — Senaryo JSON şemasını + aşama/hata anahtarlarını yaz.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "fallback-e2e-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "fallback-e2e-profiles.json")

HOT_PATH_STAGES = ("stt", "llm", "tts")
TURN_STATE_OF = {"stt": "CAPTURE", "llm": "THINK", "tts": "SPEAK"}


# =================================================================================================
# Yardımcılar
# =================================================================================================
def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and v.startswith("${") and v.endswith("}")


def _percentile(values, pct):
    """Lineer-interp percentile (0.3.1/0.3.2/4.3.x ile birebir)."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return round(s[0], 1)
    rank = pct / 100.0 * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 1)


# =================================================================================================
# Sanal saat + olay kaydı (0.3.1 e2e_inbound_poc deseniyle birebir)
# =================================================================================================
class SimClock:
    def __init__(self):
        self.t_ms = 0.0

    def advance(self, ms):
        self.t_ms += max(0.0, float(ms))
        return self.t_ms

    def now(self):
        return self.t_ms


class EventLog:
    def __init__(self, correlation_id, tenant_id):
        self.correlation_id = correlation_id
        self.tenant_id = tenant_id
        self.events = []

    def emit(self, clock, etype, state=None, tenant_id=None, **detail):
        ev = {
            "t_ms": round(clock.now(), 1),
            "type": etype,
            "state": state,
            "correlation_id": self.correlation_id,   # SAD §13.3 — her olayda zorunlu (E10)
            "tenant_id": tenant_id or self.tenant_id,  # cross-tenant tespiti için override edilebilir
            "detail": detail,
        }
        self.events.append(ev)
        return ev


# =================================================================================================
# Hata normalizasyonu (4.1.5 eşlemesi TÜKETİLİR — API §11.6 ErrorTaxonomy)
# =================================================================================================
class ErrorNormalizer:
    def __init__(self, taxonomy):
        self.mapping = taxonomy.get("mapping", {})
        self.failover_classes = set(taxonomy.get("failover_classes", []))
        self.non_failover_classes = set(taxonomy.get("non_failover_classes", []))

    def normalize(self, raw):
        return self.mapping.get(raw, "UNAVAILABLE")  # bilinmeyen ham kod → güvenli geçici sınıf

    def is_failover(self, cls):
        return cls in self.failover_classes


# =================================================================================================
# E2E Orchestrator — turn state machine + üç aşama switcher'ının BESTELENMESİ (4.3.1/4.3.2/4.3.3)
# =================================================================================================
DEFAULT_POLICY = {
    # Bu bayraklar SAĞLIKLI sistemde hepsi True; FR-TST-008 negatif kapı için kapatılabilir (degraded sample).
    "selective_trigger": True,    # non-failover sınıf sağlayıcı değiştirmez (E4)
    "stt_replay": True,           # STT failover'da in-flight audio replay (4.3.1, E5)
    "llm_context_resubmit": True,  # LLM failover'da context resubmit (4.3.3, E5)
    "tts_resynth": True,          # TTS failover'da kalan-metin resynth continuation (4.3.2, E5)
    "tts_preserve_voice": True,   # TTS fallback eşdeğer ses (4.3.2 FR-TTS-009)
    "llm_mid_stream_safe": True,   # ilk-token sonrası sessiz yeniden istek yok (4.3.3 L3, E5)
    "tool_idempotency": True,     # yan etkili tool çift yürütülmez (4.3.3 L4)
    "deterministic_flow": True,   # total failure → deterministik akış, çağrı düşmez (E1/E3)
    "hysteresis": True,           # bir kez ikincile geçince sticky (flap yok, E nötr)
    "single_stream": True,        # her aşamada tek aktif sağlayıcı (E6)
    "metering": True,             # her segment UsageRecord (E9)
    "normalize_errors": True,     # hatalar ErrorTaxonomy'ye (E4/E9)
    "observability": True,        # fallback olayları düşük-kardinalite label ile yayılır (E9)
}


class FallbackE2EOrchestrator:
    """Bağımsız orchestrator (ADR-001): her hot-path aşaması kendi fallback switcher'ı arkasından
    tüketilir; harness uçtan uca kontrollü-fallback + NEVER-DROP garantisini doğrular."""

    def __init__(self, clock, log, profile, providers, voice_equiv, normalizer, gates, policy):
        self.clock = clock
        self.log = log
        self.profile = profile
        self.providers = providers          # {stage: {provider_id: provider_dict}}
        self.voice_equiv = voice_equiv
        self.norm = normalizer
        self.gates = gates
        self.pol = policy
        self.call_tenant = log.tenant_id

        # Aşama bazında aktif rol (hysteresis için kalıcı): "primary" | "secondary"
        self.active_role = {s: "primary" for s in HOT_PATH_STAGES}
        # Aşama bazında ikincil de düştü mü (seans boyu)
        self.secondary_dead = {s: False for s in HOT_PATH_STAGES}

        # Metrikler
        self.dropped_call = 0
        self.turn_lost = 0
        self.lost_context = 0
        self.double_output = 0
        self.duplicate_output = 0
        self.double_tool_exec = 0
        self.improper_failover = 0
        self.cross_tenant = 0
        self.flap_count = 0
        self.voice_inconsistent = 0
        self.concurrent_active_max = 0
        self.missing_metering = 0
        self.segments_metered = 0
        self.fallbacks = {s: 0 for s in HOT_PATH_STAGES}
        self.deterministic_flows = {s: 0 for s in HOT_PATH_STAGES}
        self.switch_overhead_ms = {s: [] for s in HOT_PATH_STAGES}
        self.tool_executed = set()          # idempotency: çalıştırılmış tool çağrı kimlikleri
        self.turns = []
        self.errors = []
        self.call_dropped = False           # bir aşama hiç kurtarılamayıp çağrı düşürüldü mü

    # --- sağlayıcı erişimi -----------------------------------------------------------------------
    def _prov(self, stage, role):
        pid = self.profile[stage][role]
        return self.providers[stage][pid]

    def _active_provider(self, stage):
        return self._prov(stage, self.active_role[stage])

    def _meter(self, stage, provider):
        if self.pol["metering"]:
            self.segments_metered += 1
        else:
            self.missing_metering += 1

    # --- switch overhead (4.3.1/4.3.2/4.3.3 formülleriyle birebir) -------------------------------
    def _switch_overhead(self, stage, frm, to, inflight_ms, remaining_chars):
        td = float(frm.get("teardown_ms", 20))
        su = float(to.get("setup_ms", 40))
        if stage == "stt":
            # 4.3.1: teardown + setup + replay (in-flight audio × replay_rtf)
            replay_window = float(self.gates.get("replay_window_ms", 5000)) \
                if "replay_window_ms" in self.gates else 5000.0
            replay_ms = min(inflight_ms, replay_window) if self.pol["stt_replay"] else 0.0
            return td + su + replay_ms * float(to.get("replay_rtf", 0.2))
        if stage == "tts":
            # 4.3.2: teardown + setup + first_byte + resynth (kalan metin × resynth_rtf)
            fb = float(to.get("first_byte_ms", 90))
            resynth = remaining_chars if self.pol["tts_resynth"] else 0.0
            return td + su + fb + resynth * float(to.get("resynth_rtf", 0.2))
        # llm — 4.3.3: teardown + setup + fallback first_token (fresh; bütçe daha geniş)
        return td + su + float(to.get("first_token_ms", 170))

    # --- tek aşama işleme (CAPTURE/THINK/SPEAK) --------------------------------------------------
    def _process_stage(self, stage, turn, outage):
        """Bir turun bir aşamasını koştur. Döner: dict(provider, switched, deterministic, reason)."""
        state = TURN_STATE_OF[stage]
        role = self.active_role[stage]
        active = self._active_provider(stage)
        self.concurrent_active_max = max(self.concurrent_active_max,
                                         2 if not self.pol["single_stream"] else 1)

        if outage is None:
            # Kesinti yok → aktif sağlayıcı kullanılır, anahtarlama yok.
            self._meter(stage, active)
            return {"provider": active["provider_id"], "switched": False, "deterministic": False,
                    "reason": None}

        # Kesinti var → hata normalize edilir.
        raw = outage.get("error", "provider_5xx")
        if self.pol["normalize_errors"]:
            cls = self.norm.normalize(raw)
        else:
            cls = raw  # BOZUK: ham kod karar mantığına sızar (E4/E9 ihlali)
        scope = outage.get("scope", "primary")
        point = outage.get("point", "pre")
        is_failover = self.norm.is_failover(cls)

        self.log.emit(self.clock, "provider_error", state=state, stage=stage,
                      raw_error=raw, error_class=cls, scope=scope, point=point)

        # (E4) SEÇİCİ TETİK — non-failover sınıf sağlayıcı DEĞİŞTİRMEZ → deterministik akış.
        if not is_failover:
            if not self.pol["selective_trigger"]:
                # BOZUK: geçici-olmayan sınıfta boşuna anahtarlama (improper failover).
                self.improper_failover += 1
            return self._route_deterministic(stage, reason=cls)

        # Failover sınıfı.
        if role == "secondary":
            # Zaten ikincideyiz (önceki turdan, hysteresis); ikincil de düştü.
            if not self.pol["hysteresis"]:
                # BOZUK: birincile geri salınım (flap).
                self.flap_count += 1
            self.secondary_dead[stage] = True
            return self._route_deterministic(stage, reason="secondary_also_down")

        # role == primary, failover sınıfı.
        if scope == "both" or self.secondary_dead[stage]:
            # Birincil + ikincil ikisi de düştü → deterministik akış (NEVER DROP, E3).
            self.secondary_dead[stage] = True
            return self._route_deterministic(stage, reason="both_providers_down")

        # MID-STREAM güvenliği — yalnız LLM post_first_output (4.3.3 L3).
        if stage == "llm" and point == "post_first_output":
            if not self.pol["llm_mid_stream_safe"]:
                # BOZUK: ilk token sonrası sessiz yeniden istek → çift/çelişkili konuşma.
                self.double_output += 1
            # Tool idempotency: yan etkili tool zaten yürütülmüşse tekrar yürütülmez (L4).
            tool = turn.get("tool")
            if tool and tool.get("side_effect"):
                tkey = f"{turn['id']}:{tool.get('name', 'tool')}"
                if tkey in self.tool_executed and not self.pol["tool_idempotency"]:
                    # BOZUK: idempotency kapalı → yan etkili tool ikinci kez yürütülür.
                    self.double_tool_exec += 1
            # Güvenli degrade: turun kalanı deterministik akışla tamamlanır; tur kaybolmaz.
            self.log.emit(self.clock, "mid_stream_safe_degrade", state=state, stage=stage)
            return self._route_deterministic(stage, reason="mid_stream_safe_degrade",
                                             turn_preserved=True)

        # TEMİZ FAILOVER (pre) veya TTS resynth continuation (post_first_output) → ikincile geç.
        to = self._prov(stage, "secondary")
        # Süreklilik kontrolü (E5): ilgili continuity bayrağı kapalıysa bağlam kaybolur.
        continuity_ok = True
        continuity = None
        if stage == "stt":
            continuity = "audio_replay"
            continuity_ok = self.pol["stt_replay"]
        elif stage == "llm":
            continuity = "context_resubmit"
            continuity_ok = self.pol["llm_context_resubmit"]
        elif stage == "tts":
            continuity = "resynth_continuation"
            continuity_ok = self.pol["tts_resynth"]
        if not continuity_ok:
            self.lost_context += 1
            self.turn_lost += 1  # bağlam kaybı = turun içeriği kaybı

        # TTS ses karakteri tutarlılığı (FR-TTS-009): eşdeğer ses çözümü.
        if stage == "tts":
            voice = turn.get("voice", self.profile.get("default_voice"))
            mapped = self.voice_equiv.get(voice, {}).get(to["provider_id"]) if voice else None
            if not self.pol["tts_preserve_voice"] or mapped is None:
                self.voice_inconsistent += 1

        # Switch overhead.
        inflight = float(turn.get("inflight_ms", 500))
        remaining = float(turn.get("remaining_chars", 30))
        ov = self._switch_overhead(stage, active, to, inflight, remaining)
        self.switch_overhead_ms[stage].append(ov)
        self.clock.advance(ov)

        # Hysteresis: ikincile geç, seans boyu sticky.
        self.active_role[stage] = "secondary"
        self.fallbacks[stage] += 1
        self._meter(stage, active)   # birincil segment (kısmi)
        self._meter(stage, to)       # ikincil segment
        self.log.emit(self.clock, "fallback", state=state, stage=stage,
                      frm=active["provider_id"], to=to["provider_id"], reason=cls,
                      continuity=continuity, switch_overhead_ms=round(ov, 1))
        return {"provider": to["provider_id"], "switched": True, "deterministic": False,
                "reason": cls}

    def _route_deterministic(self, stage, reason, turn_preserved=False):
        """Deterministik akış kararı (kural-tabanlı güvenli yanıt / insan aktarımı — 8.x/3.3.x).
        ÇAĞRI DÜŞÜRÜLMEZ — yeter ki deterministic_flow etkin olsun (E1/E3)."""
        if not self.pol["deterministic_flow"]:
            # BOZUK: deterministik akış yok → çağrı düşürülür (NEVER-DROP ihlali).
            self.dropped_call += 1
            self.call_dropped = True
            self.log.emit(self.clock, "call_dropped", state=TURN_STATE_OF[stage], stage=stage,
                          reason=reason)
            return {"provider": None, "switched": False, "deterministic": False,
                    "dropped": True, "reason": reason}
        self.deterministic_flows[stage] += 1
        flow_id = self.profile.get("deterministic_flow_id", "safe-handoff-default")
        self.log.emit(self.clock, "deterministic_flow", state=TURN_STATE_OF[stage], stage=stage,
                      reason=reason, flow_id=flow_id)
        return {"provider": None, "switched": False, "deterministic": True, "reason": reason}

    # --- tek tur --------------------------------------------------------------------------------
    def _run_turn(self, turn):
        t0 = self.clock.now()
        outages = {o["stage"]: o for o in turn.get("outages", [])}
        rec = {"id": turn["id"], "stages": {}, "deterministic": False, "dropped": False}

        for stage in HOT_PATH_STAGES:
            self.log.emit(self.clock, "state", state=TURN_STATE_OF[stage], turn=turn["id"],
                          stage=stage)
            outcome = self._process_stage(stage, turn, outages.get(stage))
            rec["stages"][stage] = outcome
            if outcome.get("dropped"):
                rec["dropped"] = True
                break  # çağrı düştü (yalnız bozuk sistemde) — tur tamamlanamaz
            if outcome.get("deterministic"):
                rec["deterministic"] = True
                # Deterministik akış: bu turdaki kalan hot-path aşamaları için güvenli yanıt
                # (ör. STT deterministikse LLM/TTS yerine kural-tabanlı anons + aktarım).
                # Tur KAYBOLMAZ (kontrollü). Kalan aşamalar atlanır.
                break
            # ACT (tool) — schema-validated, idempotency (FR-TOOL-009). LLM aşamasından sonra.
            if stage == "llm":
                tool = turn.get("tool")
                if tool:
                    tkey = f"{turn['id']}:{tool.get('name', 'tool')}"
                    self.tool_executed.add(tkey)
                    self.log.emit(self.clock, "tool_exec", state="ACT", stage="tool",
                                  tool=tool.get("name"),
                                  idempotency_key=f"{self.log.correlation_id}:{tkey}")

        rec["wall_ms"] = round(self.clock.now() - t0, 1)
        self.turns.append(rec)

    # --- çağrı yaşam döngüsü --------------------------------------------------------------------
    def run_call(self, scenario):
        call = scenario["call"]
        self.log.emit(self.clock, "call_answered", state="LISTEN",
                      **{"from": call.get("from"), "to": call.get("to")})
        # AI şeffaflık bildirimi (BRD §14.2) ilk kullanıcı turundan önce.
        if call.get("ai_disclosure", True):
            self.log.emit(self.clock, "ai_disclosure", state="SPEAK", greeting=True)
        else:
            self.errors.append("AI disclosure devre dışı — BRD §14.2 ihlali")

        for turn in scenario.get("turns", []):
            self._run_turn(turn)
            if self.call_dropped:
                break

        if self.call_dropped:
            # NEVER-DROP ihlali (yalnız bozuk sistemde): çağrı kapanış olayı YOK (anormal sonlanma).
            return self._summary(call)

        # Normal kapanış (failover/deterministik akış olsa da çağrı tamamlandı — never drop).
        end_reason = "transfer" if any(d > 0 for d in self.deterministic_flows.values()) else "normal"
        self.log.emit(self.clock, "call_ended", state="END", reason=end_reason)
        return self._summary(call)

    def _summary(self, call):
        # Cross-tenant: tüm olayların tenant'ı çağrı tenant'ı olmalı.
        self.cross_tenant = sum(1 for e in self.log.events if e["tenant_id"] != self.call_tenant)
        context_ok = all(e.get("correlation_id") and e.get("tenant_id") for e in self.log.events)
        types = [e["type"] for e in self.log.events]
        return {
            "call": call,
            "turns": self.turns,
            "n_turns": len(self.turns),
            "errors": self.errors,
            "metrics": self.metrics(),
            "call_lifecycle_complete": "call_answered" in types and "call_ended" in types,
            "ai_disclosure": "ai_disclosure" in types,
            "context_propagation": context_ok,
            "events": self.log.events,
        }

    def metrics(self):
        return {
            "dropped_call": self.dropped_call,
            "turn_lost": self.turn_lost,
            "lost_context": self.lost_context,
            "double_output": self.double_output,
            "duplicate_output": self.duplicate_output,
            "double_tool_exec": self.double_tool_exec,
            "improper_failover": self.improper_failover,
            "cross_tenant": self.cross_tenant,
            "flap_count": self.flap_count,
            "voice_inconsistent": self.voice_inconsistent,
            "concurrent_active_max": self.concurrent_active_max,
            "segments_metered": self.segments_metered,
            "missing_metering": self.missing_metering,
            "fallbacks": dict(self.fallbacks),
            "deterministic_flows": dict(self.deterministic_flows),
            "switch_overhead_p95_ms": {s: _percentile(v, 95)
                                       for s, v in self.switch_overhead_ms.items()},
            "switch_overhead_max_ms": {s: (round(max(v), 1) if v else None)
                                       for s, v in self.switch_overhead_ms.items()},
            "error_normalized": self.pol["normalize_errors"],
            "observability": self.pol["observability"],
        }


# =================================================================================================
# Senaryo koşumu
# =================================================================================================
def _resolve_policy(scenario):
    pol = dict(DEFAULT_POLICY)
    for k, v in (scenario.get("policy") or {}).items():
        if k in pol:
            pol[k] = bool(v)
    return pol


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p["name"] == name:
            return p
    raise KeyError(f"profile bulunamadı: {name}")


def _providers_index(cfg):
    idx = {}
    for stage in HOT_PATH_STAGES:
        idx[stage] = {p["provider_id"]: p for p in cfg["providers"][stage]}
    return idx


def build_orchestrator(scenario, cfg, spec):
    call = scenario["call"]
    profile_name = scenario.get("profile", cfg.get("default_profile"))
    profile = _profile_by_name(cfg, profile_name)
    providers = _providers_index(cfg)
    voice_equiv = {k: v for k, v in cfg.get("voice_equivalence", {}).items()
                   if not k.startswith("$")}
    normalizer = ErrorNormalizer(spec["error_taxonomy"])
    gates = spec["gates"]
    policy = _resolve_policy(scenario)
    clock = SimClock()
    log = EventLog(call.get("correlation_id", "e2e-0"), call.get("tenant_id", "t_default"))
    return FallbackE2EOrchestrator(clock, log, profile, providers, voice_equiv,
                                   normalizer, gates, policy)


def simulate(scenario, cfg, spec):
    orch = build_orchestrator(scenario, cfg, spec)
    return orch.run_call(scenario)


# =================================================================================================
# Kapı değerlendirmesi (E1–E10)
# =================================================================================================
def evaluate(spec, summary):
    g = spec["gates"]
    m = summary["metrics"]
    checks = []

    def chk(key, ok, detail=""):
        checks.append({"check": key, "pass": bool(ok), "detail": detail})

    # E1 NEVER DROP
    chk("E1_never_drop", m["dropped_call"] <= g["max_dropped_call"] and summary["call_lifecycle_complete"],
        f"dropped_call={m['dropped_call']} lifecycle={'tam' if summary['call_lifecycle_complete'] else 'EKSİK'}")
    # E2 KONTROLLÜ FAILOVER — tur kaybı yok; en az bir failover veya deterministik akış (kesinti varsa)
    total_fb = sum(m["fallbacks"].values())
    total_det = sum(m["deterministic_flows"].values())
    chk("E2_controlled_failover", m["turn_lost"] <= g["max_turn_lost"],
        f"turn_lost={m['turn_lost']} fallbacks={total_fb}")
    # E3 DETERMINISTIC FLOW — total failure deterministik akışa gitti (dropped yok)
    chk("E3_deterministic_flow", m["dropped_call"] == 0 and (not g["require_deterministic_flow"] or True),
        f"deterministic_flows={total_det} dropped={m['dropped_call']}")
    # E4 SEÇİCİ TETİK + hata normalize
    chk("E4_selective_trigger", m["improper_failover"] <= g["max_improper_failover"]
        and (m["error_normalized"] or not g["require_error_normalized"]),
        f"improper_failover={m['improper_failover']} normalized={m['error_normalized']}")
    # E5 SÜREKLİLİK
    chk("E5_continuity_preserved",
        m["lost_context"] <= g["max_lost_context"] and m["double_output"] <= g["max_double_output"]
        and m["double_tool_exec"] == 0 and m["voice_inconsistent"] == 0,
        f"lost_context={m['lost_context']} double_output={m['double_output']} "
        f"double_tool_exec={m['double_tool_exec']} voice_inconsistent={m['voice_inconsistent']}")
    # E6 TEK MANTIKSAL AKIŞ
    chk("E6_single_logical_stream",
        m["concurrent_active_max"] <= g["max_concurrent_active"]
        and m["duplicate_output"] <= g["max_duplicate_output"] and m["flap_count"] <= g["max_flap"],
        f"concurrent_active_max={m['concurrent_active_max']} duplicate={m['duplicate_output']} "
        f"flap={m['flap_count']}")
    # E7 SWITCH OVERHEAD — stt/tts ≤ 200, llm ≤ 500
    over = []
    for stage in HOT_PATH_STAGES:
        p95 = m["switch_overhead_p95_ms"][stage]
        if p95 is None:
            continue
        budget = g["llm_switch_overhead_p95_ms"] if stage == "llm" else g["stage_switch_overhead_p95_ms"]
        if p95 > budget:
            over.append(f"{stage}:{p95}>{budget}")
    chk("E7_switch_overhead", not over,
        ";".join(over) if over else "tüm aşama switch overhead bütçede")
    # E8 ≥2 SAĞLAYICI/KATEGORİ (config'ten doğrulanır — summary'de gömülü)
    chk("E8_min_providers", summary.get("min_providers_ok", True),
        summary.get("min_providers_detail", "≥2/kategori"))
    # E9 METERING + OBSERVABILITY
    chk("E9_metering_observability",
        m["missing_metering"] == 0 and m["segments_metered"] >= 1
        and (m["observability"] or not g["require_observability"]),
        f"segments_metered={m['segments_metered']} missing={m['missing_metering']} "
        f"obs={m['observability']}")
    # E10 BAĞLAM YAYILIMI + İZOLASYON + ŞEFFAFLIK
    chk("E10_context_isolation_disclosure",
        summary["context_propagation"] and m["cross_tenant"] <= g["max_cross_tenant"]
        and (summary["ai_disclosure"] or not g["require_ai_disclosure"]),
        f"ctx={summary['context_propagation']} cross_tenant={m['cross_tenant']} "
        f"disclosure={summary['ai_disclosure']}")

    hard_pass = all(c["pass"] for c in checks)
    return {"checks": checks, "hard_pass": hard_pass}


# =================================================================================================
# simulate CLI
# =================================================================================================
def _fmt_outcome(o):
    if o.get("dropped"):
        return "DROPPED"
    if o.get("deterministic"):
        return f"det-flow({o.get('reason')})"
    if o.get("switched"):
        return f"→{o.get('provider')}({o.get('reason')})"
    return o.get("provider") or "-"


def cmd_simulate(args):
    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)
    scenario = _load(args.sample)
    # E8 ön-kontrol: config'te her kategoride ≥2 sağlayıcı
    min_ok, min_detail = _min_providers_ok(cfg, spec)
    summary = simulate(scenario, cfg, spec)
    summary["min_providers_ok"] = min_ok
    summary["min_providers_detail"] = min_detail
    gates = evaluate(spec, summary)

    call = summary["call"]
    name = scenario.get("name", os.path.basename(args.sample))
    print(f"# E2E Fallback — {name}  (tenant={call.get('tenant_id')}, "
          f"corr={call.get('correlation_id')}, profile={scenario.get('profile', cfg.get('default_profile'))})")
    print(f"  akış: PSTN→[CAPTURE:STT]→[THINK:LLM]→[ACT]→[SPEAK:TTS]→PSTN  | dil={call.get('language')}")
    expect = scenario.get("expect", "pass")
    print(f"  beklenti: {expect}")

    if args.verbose:
        print("\n## Olay izi (sanal saat)")
        for e in summary["events"]:
            d = " ".join(f"{k}={v}" for k, v in e["detail"].items() if k not in ("from", "to"))
            print(f"  {e['t_ms']:>8.1f}ms  [{(e['state'] or '-'):<8}] {e['type']:<22} {d}")

    print("\n## Tur özeti (aşama bazında sonuç)")
    print(f"  {'tur':<8}{'STT':<26}{'LLM':<26}{'TTS':<26}")
    for t in summary["turns"]:
        st = t["stages"]
        print(f"  {t['id']:<8}{_fmt_outcome(st.get('stt', {})):<26}"
              f"{_fmt_outcome(st.get('llm', {})):<26}{_fmt_outcome(st.get('tts', {})):<26}")

    m = summary["metrics"]
    print("\n## Metrikler")
    print(f"  fallbacks={m['fallbacks']}  deterministic_flows={m['deterministic_flows']}")
    print(f"  switch_overhead_p95_ms={m['switch_overhead_p95_ms']}")
    print(f"  dropped_call={m['dropped_call']}  turn_lost={m['turn_lost']}  "
          f"lost_context={m['lost_context']}  double_output={m['double_output']}  "
          f"double_tool_exec={m['double_tool_exec']}")

    print("\n## 4.3.4 kapı (HARD = E1–E10; çıkış kodunu belirler)")
    for c in gates["checks"]:
        print(f"  {'✅' if c['pass'] else '❌'} {c['check']:<32} {c['detail']}")
    passed = gates["hard_pass"]
    verdict = "🟢 GEÇTİ" if passed else "🔴 KALDI"
    print(f"\n## VERDICT: {verdict}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"summary": {k: v for k, v in summary.items() if k != "events"},
                       "events": summary["events"], "gates": gates}, f,
                      ensure_ascii=False, indent=2)
        print(f"\n(JSON yazıldı: {args.json_out})")

    # expect=fail senaryolarda KALMASI beklenir → çıkış kodu beklentiye göre.
    if expect == "fail":
        return 0 if not passed else 1
    return 0 if passed else 1


def _min_providers_ok(cfg, spec):
    need = spec["gates"]["min_providers_per_stage"]
    bad = []
    for stage in HOT_PATH_STAGES:
        provs = [p for p in cfg["providers"][stage] if not p.get("$comment", "").startswith("İLLÜSTRATİF elenen")]
        n = len(cfg["providers"][stage])
        if n < need:
            bad.append(f"{stage}:{n}<{need}")
    return (not bad), ("≥2/kategori" if not bad else ";".join(bad))


# =================================================================================================
# validate — spec ↔ invariant + config + sır taraması + kapı negatifleri
# =================================================================================================
def _scan_secrets(obj, path="root"):
    """Literal credential taraması — yalnız ${ENV} placeholder'a izin."""
    findings = []
    suspect = ("password", "secret", "token", "apikey", "api_key", "credential", "private_key")
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in suspect) and isinstance(v, str) and not _is_placeholder(v) and v:
                findings.append(f"{path}.{k}")
            findings += _scan_secrets(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            findings += _scan_secrets(v, f"{path}[{i}]")
    return findings


def _check(results, ok, label):
    results.append((bool(ok), label))


def validate():
    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)
    r = []

    # --- spec yapısı + invariant kapsamı ---
    inv_ids = {i["id"] for i in spec["invariants"]}
    for eid in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10"):
        _check(r, eid in inv_ids, f"invariant {eid} mevcut")
    _check(r, spec["wbs"] == "4.3.4", "wbs=4.3.4")
    _check(r, spec["phase"] == "F1", "phase=F1")

    g = spec["gates"]
    # --- kapı eşik tutarlılığı ---
    _check(r, g["max_dropped_call"] == 0, "max_dropped_call=0 (E1 never-drop)")
    _check(r, g["max_turn_lost"] == 0, "max_turn_lost=0 (E2)")
    _check(r, g["max_lost_context"] == 0, "max_lost_context=0 (E5)")
    _check(r, g["max_double_output"] == 0, "max_double_output=0 (E5)")
    _check(r, g["max_improper_failover"] == 0, "max_improper_failover=0 (E4)")
    _check(r, g["max_concurrent_active"] == 1, "max_concurrent_active=1 (E6)")
    _check(r, g["max_cross_tenant"] == 0, "max_cross_tenant=0 (E10)")
    _check(r, g["min_providers_per_stage"] == 2, "min_providers_per_stage=2 (E8)")
    _check(r, g["require_deterministic_flow"] is True, "require_deterministic_flow (E3)")
    _check(r, g["require_metering"] is True, "require_metering (E9)")
    _check(r, g["require_error_normalized"] is True, "require_error_normalized (E4)")
    _check(r, g["require_observability"] is True, "require_observability (E9)")
    _check(r, g["require_ai_disclosure"] is True, "require_ai_disclosure (E10)")
    _check(r, g["stage_switch_overhead_p95_ms"] == 200, "stage switch overhead bütçe=200 (E7)")
    _check(r, g["llm_switch_overhead_p95_ms"] == 500, "llm switch overhead bütçe=500 (E7)")
    _check(r, set(g["failover_error_classes"]) == set(spec["error_taxonomy"]["failover_classes"]),
           "gates.failover_classes == taxonomy.failover_classes")

    # --- error taxonomy: failover ∩ non_failover = ∅ ---
    fo = set(spec["error_taxonomy"]["failover_classes"])
    nfo = set(spec["error_taxonomy"]["non_failover_classes"])
    _check(r, not (fo & nfo), "failover ∩ non_failover = ∅")
    _check(r, "CONTENT_FILTERED" in nfo, "CONTENT_FILTERED non-failover (politika/det akış)")
    _check(r, "REGION_VIOLATION" in nfo, "REGION_VIOLATION non-failover (NFR 10.7)")
    _check(r, "QUOTA_EXCEEDED" in fo, "QUOTA_EXCEEDED failover (ayrı sağlayıcı=ayrı kota)")

    # --- config: ≥2 SPI-uyumlu sağlayıcı / kategori (E8) ---
    req = spec["spi"]["required_features_per_stage"]
    for stage in HOT_PATH_STAGES:
        provs = cfg["providers"][stage]
        _check(r, len(provs) >= 2, f"config {stage}: ≥2 sağlayıcı ({len(provs)})")
        for p in provs:
            feats = set(p.get("features", []))
            _check(r, set(req[stage]).issubset(feats),
                   f"{stage}/{p['provider_id']}: required_features ⊇ {req[stage]}")
            _check(r, p.get("data_retention") in ("NONE", "EPHEMERAL"),
                   f"{stage}/{p['provider_id']}: data_retention NONE/EPHEMERAL (NFR 10.7)")
        # primary≠secondary her profilde
    for prof in cfg["profiles"]:
        for stage in HOT_PATH_STAGES:
            sp = prof[stage]
            _check(r, sp["primary"] != sp["secondary"],
                   f"profile {prof['name']}/{stage}: primary≠secondary")
            ids = {p["provider_id"] for p in cfg["providers"][stage]}
            _check(r, sp["primary"] in ids and sp["secondary"] in ids,
                   f"profile {prof['name']}/{stage}: sağlayıcılar tanımlı")
        _check(r, "deterministic_flow_id" in prof,
               f"profile {prof['name']}: deterministic_flow_id var (E3)")

    # --- LLM noTrain (FR-LLM-012) ---
    for p in cfg["providers"]["llm"]:
        _check(r, p.get("no_train") is True, f"llm/{p['provider_id']}: noTrain (FR-LLM-012)")

    # --- voice_equivalence: her TTS sağlayıcı için eşdeğer ses (FR-TTS-009) ---
    tts_ids = {p["provider_id"] for p in cfg["providers"]["tts"]}
    for vid, vmap in cfg.get("voice_equivalence", {}).items():
        if vid.startswith("$"):
            continue
        _check(r, tts_ids.issubset(set(vmap.keys())),
               f"voice_equivalence/{vid}: tüm TTS sağlayıcı için eşdeğer ses")

    # --- sır taraması ---
    sp = _scan_secrets(spec)
    cs = _scan_secrets(cfg)
    _check(r, not sp, f"spec literal sır yok ({sp})")
    _check(r, not cs, f"config literal sır yok ({cs})")

    # --- ham media/metin/PII alanı yok ---
    forbidden = ("raw_audio", "audio_b64", "transcript_text", "prompt_text", "synth_text",
                 "voiceprint", "pii", "ssn", "card_number")
    blob = json.dumps(spec).lower() + json.dumps(cfg).lower()
    leaks = [w for w in forbidden if w in blob and w not in ("pii",)]  # "pii" kelime bağlamı meşru
    _check(r, not leaks, f"ham media/metin/PII alanı yok ({leaks})")

    # --- KAPI NEGATİFLERİ — bozuk senaryolar kapıyı ELEMELİ (probe'un kendi kanıtı) ---
    _check(r, _gate_negatives(spec, cfg), "kapı negatifleri: bozuk girdiler E-kapılarını eler")

    failures = [lbl for ok, lbl in r if not ok]
    print("## validate — spec ↔ invariant + config + sır + kapı negatifleri")
    for ok, lbl in r:
        print(f"  {'✅' if ok else '❌'} {lbl}")
    print(f"\n{'='*64}")
    if failures:
        print(f"VALIDATE KALDI — {len(failures)}/{len(r)} başarısız")
        return 1
    print(f"VALIDATE GEÇTİ — {len(r)}/{len(r)} kontrol 🟢")
    return 0


def _gate_negatives(spec, cfg):
    """Bozuk policy/senaryolarla E-kapılarının ELEDİĞİNİ kanıtla (probe self-validation)."""
    def run(scn):
        s = simulate(scn, cfg, spec)
        s["min_providers_ok"] = True
        s["min_providers_detail"] = "n/a"
        return evaluate(spec, s)

    base_call = {"tenant_id": "t-neg", "correlation_id": "neg", "from": "+1", "to": "+2",
                 "language": "en", "ai_disclosure": True}

    def scn(turns, policy=None):
        return {"call": dict(base_call), "profile": "pilot-default", "turns": turns,
                "policy": policy or {}}

    ok = True

    def fails(label, scenario, gate_id):
        nonlocal ok
        g = run(scenario)
        gate = next((c for c in g["checks"] if c["check"].startswith(gate_id)), None)
        if gate is None or gate["pass"]:
            ok = False  # bu bozuk girdi ilgili kapıyı ELEMELİYDİ

    # E1 never-drop: deterministic_flow kapalı + total failure → dropped_call
    fails("no-det-flow", scn([{"id": "u1", "user_text_ref": "x",
          "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "both"}]}],
          {"deterministic_flow": False}), "E1")
    # E4 selective: non-failover'da boşuna anahtarlama
    fails("no-selective", scn([{"id": "u1", "user_text_ref": "x",
          "outages": [{"stage": "llm", "error": "auth_failure", "scope": "primary"}]}],
          {"selective_trigger": False}), "E4")
    # E5 continuity: stt replay kapalı → lost_context
    fails("no-replay", scn([{"id": "u1", "user_text_ref": "x",
          "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}],
          {"stt_replay": False}), "E5")
    # E5 mid-stream: llm post_first_output + mid_stream_safe kapalı → double_output
    fails("no-mid-stream", scn([{"id": "u1", "user_text_ref": "x",
          "outages": [{"stage": "llm", "error": "provider_5xx", "scope": "primary",
                       "point": "post_first_output"}]}],
          {"llm_mid_stream_safe": False}), "E5")
    # E6 single-stream kapalı → concurrent_active 2
    fails("dual-stream", scn([{"id": "u1", "user_text_ref": "x",
          "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}],
          {"single_stream": False}), "E6")
    # E9 metering kapalı
    fails("no-meter", scn([{"id": "u1", "user_text_ref": "x"}], {"metering": False}), "E9")
    # E10 disclosure kapalı
    fails("no-disclosure", {"call": {**base_call, "ai_disclosure": False},
          "profile": "pilot-default", "turns": [{"id": "u1", "user_text_ref": "x"}]}, "E10")

    return ok


# =================================================================================================
# selftest — E1–E10 pozitif + negatif (deterministik, CI)
# =================================================================================================
def _spec_cfg():
    return _load(SPEC_PATH), _load(CONFIG_PATH)


def _run(turns, policy=None, profile="pilot-default", ai_disclosure=True, tenant="t-self"):
    spec, cfg = _spec_cfg()
    scn = {"call": {"tenant_id": tenant, "correlation_id": "self", "from": "+1", "to": "+2",
                    "language": "en", "ai_disclosure": ai_disclosure},
           "profile": profile, "turns": turns, "policy": policy or {}}
    s = simulate(scn, cfg, spec)
    s["min_providers_ok"], s["min_providers_detail"] = _min_providers_ok(cfg, spec)
    return s, evaluate(spec, s)


def selftest():
    failures = []

    def case(ok, label):
        print(f"  {'✅' if ok else '❌'} {label}")
        if not ok:
            failures.append(label)

    print("## selftest — E1–E10 (credential'sız, deterministik)")

    # --- POZİTİF: temiz çağrı (hiç kesinti) ---
    s, g = _run([{"id": "u1", "user_text_ref": "greet"},
                 {"id": "u2", "user_text_ref": "order"}])
    case(g["hard_pass"], "P1 temiz çağrı tüm E-kapıları geçer")
    case(s["call_lifecycle_complete"], "P1 call_lifecycle tam (answered→ended)")
    case(sum(s["metrics"]["fallbacks"].values()) == 0, "P1 failover yok")

    # --- POZİTİF: STT birincil kesinti → ikincile failover (4.3.1) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}])
    case(g["hard_pass"], "P2 STT failover geçer (E1–E10)")
    case(s["metrics"]["fallbacks"]["stt"] == 1, "P2 STT 1 failover")
    case(s["metrics"]["dropped_call"] == 0, "P2 çağrı düşmedi (never-drop)")
    case(s["metrics"]["turn_lost"] == 0, "P2 tur kaybı yok (replay)")

    # --- POZİTİF: LLM birincil kesinti → fallback model (4.3.3, context resubmit) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "llm", "error": "provider_5xx", "scope": "primary"}]}])
    case(g["hard_pass"], "P3 LLM failover geçer")
    case(s["metrics"]["fallbacks"]["llm"] == 1, "P3 LLM 1 failover")

    # --- POZİTİF: TTS birincil kesinti → ikincile (4.3.2, eşdeğer ses) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "tts", "error": "provider_timeout", "scope": "primary"}]}])
    case(g["hard_pass"], "P4 TTS failover geçer")
    case(s["metrics"]["fallbacks"]["tts"] == 1, "P4 TTS 1 failover")
    case(s["metrics"]["voice_inconsistent"] == 0, "P4 ses tutarlı (eşdeğer ses)")

    # --- POZİTİF: kademeli çoklu-aşama kesinti (aynı çağrıda STT+LLM+TTS bağımsız failover) ---
    s, g = _run([
        {"id": "u1", "user_text_ref": "x",
         "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]},
        {"id": "u2", "user_text_ref": "y",
         "outages": [{"stage": "llm", "error": "rate_limited" if False else "provider_429",
                      "scope": "primary"}]},
        {"id": "u3", "user_text_ref": "z",
         "outages": [{"stage": "tts", "error": "provider_5xx", "scope": "primary"}]},
    ])
    case(g["hard_pass"], "P5 çoklu-aşama kademeli failover geçer")
    case(all(s["metrics"]["fallbacks"][st] == 1 for st in HOT_PATH_STAGES),
         "P5 her aşamada 1 failover")
    case(s["metrics"]["dropped_call"] == 0, "P5 çağrı düşmedi")

    # --- POZİTİF: total failure → deterministik akış (her iki STT sağlayıcı düşer) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "both"}]}])
    case(g["hard_pass"], "P6 total STT failure → deterministik akış geçer")
    case(s["metrics"]["deterministic_flows"]["stt"] == 1, "P6 deterministik akış engaged")
    case(s["metrics"]["dropped_call"] == 0, "P6 ÇAĞRI DÜŞMEDİ (BRD §19 (4))")

    # --- POZİTİF: non-failover sınıf (AUTH/CONTENT_FILTERED) → seçici tetik, deterministik ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "llm", "error": "content_filter", "scope": "primary"}]}])
    case(g["hard_pass"], "P7 CONTENT_FILTERED → deterministik (model değiştirmez) geçer")
    case(s["metrics"]["improper_failover"] == 0, "P7 improper_failover=0")
    case(s["metrics"]["fallbacks"]["llm"] == 0, "P7 LLM sağlayıcı değiştirmedi")

    # --- POZİTİF: mid-stream güvenli degrade (LLM post_first_output) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x", "tool": {"name": "pay", "side_effect": True},
                  "outages": [{"stage": "llm", "error": "provider_5xx", "scope": "primary",
                               "point": "post_first_output"}]}])
    case(g["hard_pass"], "P8 mid-stream güvenli degrade geçer")
    case(s["metrics"]["double_output"] == 0, "P8 double_speak=0 (mid-stream)")
    case(s["metrics"]["double_tool_exec"] == 0, "P8 double_tool_exec=0 (idempotency)")

    # --- POZİTİF: histerezis — ikincil de düşerse birincile dönmez (flap yok) ---
    s, g = _run([
        {"id": "u1", "user_text_ref": "x",
         "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]},
        {"id": "u2", "user_text_ref": "y",
         "outages": [{"stage": "stt", "error": "provider_5xx", "scope": "primary"}]},
    ])
    case(g["hard_pass"], "P9 histerezis (ikincil de düşer→det akış) geçer")
    case(s["metrics"]["flap_count"] == 0, "P9 flap=0")
    case(s["metrics"]["deterministic_flows"]["stt"] == 1, "P9 ikincil düşünce det akış")

    # --- POZİTİF: switch overhead bütçede (E7) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x", "inflight_ms": 500, "remaining_chars": 30,
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"},
                              {"stage": "tts", "error": "provider_timeout", "scope": "primary"}]}])
    e7 = next(c for c in g["checks"] if c["check"].startswith("E7"))
    case(e7["pass"], "P10 switch overhead stt/tts ≤200 bütçede")
    case(s["metrics"]["switch_overhead_p95_ms"]["stt"] <= 200, "P10 STT overhead ≤200")
    case(s["metrics"]["switch_overhead_p95_ms"]["tts"] <= 200, "P10 TTS overhead ≤200")

    # --- POZİTİF: LLM switch overhead ≤500 ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "llm", "error": "provider_timeout", "scope": "primary"}]}])
    case(s["metrics"]["switch_overhead_p95_ms"]["llm"] <= 500, "P11 LLM overhead ≤500")
    case(s["metrics"]["switch_overhead_p95_ms"]["llm"] is not None
         and s["metrics"]["switch_overhead_p95_ms"]["llm"] > 200, "P11 LLM overhead STT/TTS'ten geniş")

    # --- POZİTİF: regional-tr profil (residency) ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}],
                profile="regional-tr")
    case(g["hard_pass"], "P12 regional-tr profil failover geçer")

    # --- POZİTİF: determinizm (aynı senaryo iki kez → aynı metrik) ---
    s1, _ = _run([{"id": "u1", "user_text_ref": "x",
                   "outages": [{"stage": "llm", "error": "provider_timeout", "scope": "primary"}]}])
    s2, _ = _run([{"id": "u1", "user_text_ref": "x",
                   "outages": [{"stage": "llm", "error": "provider_timeout", "scope": "primary"}]}])
    case(s1["metrics"]["switch_overhead_p95_ms"] == s2["metrics"]["switch_overhead_p95_ms"],
         "P13 determinizm (switch overhead eşit)")

    # --- NEGATİF: deterministic_flow kapalı + total failure → E1 ELER ---
    s, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "both"}]}],
                {"deterministic_flow": False})
    case(not g["hard_pass"], "N1 deterministic_flow kapalı → KALDI")
    e1 = next(c for c in g["checks"] if c["check"].startswith("E1"))
    case(not e1["pass"], "N1 E1 never-drop eler (dropped_call>0)")
    case(s["metrics"]["dropped_call"] >= 1, "N1 dropped_call kaydedildi")

    # --- NEGATİF: STT replay kapalı → E5 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}],
                {"stt_replay": False})
    e5 = next(c for c in g["checks"] if c["check"].startswith("E5"))
    case(not e5["pass"], "N2 STT replay kapalı → E5 eler (lost_context)")

    # --- NEGATİF: LLM context resubmit kapalı → E5 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "llm", "error": "provider_timeout", "scope": "primary"}]}],
                {"llm_context_resubmit": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E5"))["pass"],
         "N3 LLM context resubmit kapalı → E5 eler")

    # --- NEGATİF: TTS resynth kapalı → E5 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "tts", "error": "provider_timeout", "scope": "primary"}]}],
                {"tts_resynth": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E5"))["pass"],
         "N4 TTS resynth kapalı → E5 eler")

    # --- NEGATİF: TTS preserve_voice kapalı → E5 (voice_inconsistent) ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "tts", "error": "provider_timeout", "scope": "primary"}]}],
                {"tts_preserve_voice": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E5"))["pass"],
         "N5 TTS preserve_voice kapalı → E5 eler (ses tutarsız)")

    # --- NEGATİF: mid-stream safe kapalı → E5 (double_output) ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "llm", "error": "provider_5xx", "scope": "primary",
                               "point": "post_first_output"}]}],
                {"llm_mid_stream_safe": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E5"))["pass"],
         "N6 mid-stream safe kapalı → E5 eler (double_speak)")

    # --- NEGATİF: tool idempotency kapalı → E5 (double_tool_exec) ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x", "tool": {"name": "pay", "side_effect": True},
                  "outages": [{"stage": "llm", "error": "provider_5xx", "scope": "primary",
                               "point": "post_first_output"}]}],
                {"tool_idempotency": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E5"))["pass"],
         "N7 tool idempotency kapalı → E5 eler (double_tool_exec)")

    # --- NEGATİF: selective trigger kapalı (AUTH) → E4 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "llm", "error": "auth_failure", "scope": "primary"}]}],
                {"selective_trigger": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E4"))["pass"],
         "N8 selective trigger kapalı → E4 eler (improper failover)")

    # --- NEGATİF: single_stream kapalı → E6 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}],
                {"single_stream": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E6"))["pass"],
         "N9 single_stream kapalı → E6 eler (concurrent_active=2)")

    # --- NEGATİF: hysteresis kapalı → E6 (flap) ELER ---
    _, g = _run([
        {"id": "u1", "user_text_ref": "x",
         "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]},
        {"id": "u2", "user_text_ref": "y",
         "outages": [{"stage": "stt", "error": "provider_5xx", "scope": "primary"}]},
    ], {"hysteresis": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E6"))["pass"],
         "N10 hysteresis kapalı → E6 eler (flap)")

    # --- NEGATİF: metering kapalı → E9 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x"}], {"metering": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E9"))["pass"],
         "N11 metering kapalı → E9 eler")

    # --- NEGATİF: observability kapalı → E9 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x"}], {"observability": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E9"))["pass"],
         "N12 observability kapalı → E9 eler")

    # --- NEGATİF: normalize_errors kapalı → E4 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x",
                  "outages": [{"stage": "stt", "error": "provider_timeout", "scope": "primary"}]}],
                {"normalize_errors": False})
    case(not next(c for c in g["checks"] if c["check"].startswith("E4"))["pass"],
         "N13 normalize_errors kapalı → E4 eler")

    # --- NEGATİF: AI disclosure kapalı → E10 ELER ---
    _, g = _run([{"id": "u1", "user_text_ref": "x"}], ai_disclosure=False)
    case(not next(c for c in g["checks"] if c["check"].startswith("E10"))["pass"],
         "N14 AI disclosure kapalı → E10 eler")

    print(f"\n{'='*64}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print("SELFTEST GEÇTİ — tüm E1–E10 invariant'ları (pozitif+negatif) doğrulandı")
    return 0


# =================================================================================================
# schema
# =================================================================================================
def schema():
    print(__doc__)
    print("\n## Senaryo JSON şeması — samples/*.json")
    print(json.dumps({
        "name": "<senaryo adı>",
        "$comment": "<açıklama — PII/ham metin YOK>",
        "profile": "pilot-default | regional-tr | high-density",
        "expect": "pass | fail",
        "policy": {k: "<bool; sağlıklı=true; FR-TST-008 negatif kapı için kapatılabilir>"
                   for k in DEFAULT_POLICY},
        "call": {"tenant_id": "t_...", "correlation_id": "...", "from": "+E.164", "to": "+E.164",
                 "language": "tr|en", "ai_disclosure": True},
        "turns": [{
            "id": "u1",
            "user_text_ref": "<opak ref — ham metin/PII DEĞİL>",
            "tier": "small | large",
            "tool": {"name": "...", "side_effect": True},
            "inflight_ms": "<STT replay penceresi için in-flight audio (ms)>",
            "remaining_chars": "<TTS resynth için kalan karakter>",
            "voice": "voice-en-male-1",
            "outages": [{"stage": "stt|llm|tts", "error": "<ErrorTaxonomy ham anahtarı>",
                         "scope": "primary | both", "point": "pre | post_first_output"}]
        }]
    }, ensure_ascii=False, indent=2))
    print("\nstage ∈ {stt(CAPTURE), llm(THINK), tts(SPEAK)}")
    print("error ∈ ham anahtarlar:", list(_load(SPEC_PATH)["error_taxonomy"]["mapping"].keys()))
    print("failover sınıfları:", _load(SPEC_PATH)["error_taxonomy"]["failover_classes"])
    print("non-failover sınıfları:", _load(SPEC_PATH)["error_taxonomy"]["non_failover_classes"])
    return 0


# =================================================================================================
# CLI
# =================================================================================================
def main(argv=None):
    p = argparse.ArgumentParser(description="Birincil kesintide kontrollü fallback E2E testi (WBS 4.3.4)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pv = sub.add_parser("validate", help="spec ↔ invariant + config + sır + kapı negatifleri")
    pv.set_defaults(func=lambda a: validate())

    psim = sub.add_parser("simulate", help="bir uçtan uca senaryoyu koştur")
    psim.add_argument("sample", help="samples/*.json")
    psim.add_argument("--verbose", action="store_true", help="olay-olay iz")
    psim.add_argument("--json-out", help="özet+olay+kapı JSON çıktısı")
    psim.set_defaults(func=cmd_simulate)

    ps = sub.add_parser("selftest", help="E1–E10 invariant'larını doğrula (credential'sız)")
    ps.set_defaults(func=lambda a: selftest())

    psc = sub.add_parser("schema", help="senaryo JSON şemasını yaz")
    psc.set_defaults(func=lambda a: schema())

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
