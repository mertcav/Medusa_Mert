#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_fallback_probe.py — WBS 4.3.3 LLM fallback (fallback model / deterministic flow)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı. `adapters/` (4.2.x,
4.3.1/4.3.2 fallback) disipliniyle aynı; burada LlmAdapter SPI (SAD §8.1 / API §11.4) ARKASINDA ortak
FALLBACK ANAHTARLAMA mantığını sürükleyen DETERMİNİSTİK bir referans switcher (olay-tetikli, sanal saat,
random YOK; gerçek LLM çıkarımı YOK — sağlayıcı gecikme profili + akış/hata MODELİ). SAD §8.3 + §9.1 [4]:
  Primary LLM ──(timeout/error/circuit-open)──► Fallback model ──► Deterministic flow

Görev başlığındaki çekirdek davranış (FR-LLM-010, BRD §19 (4), SAD §9.1):
  • FAILOVER:         birincil model geçici hata/timeout (circuit-open) verince fallback modele geçilir;
                      çağrı kesintisiz sürer (L1 — turn_lost=0).
  • CONTEXT RESUBMIT: ilk-token öncesi failover'da tur isteği (messages/tools/system prompt) fallback
                      modele yeniden gönderilir (ham audio replay'in LLM karşılığı — L2; FR-LLM-006).
  • MID-STREAM SAFE:  birincil İLK TOKEN gittikten sonra düşerse sessiz yeniden istek YOK (çift konuşma
                      olur) → güvenli degrade (L3 — double_speak=0).
  • TOOL IDEMPOTENCY: yan etkili tool zaten yürütülmüşse failover'da YENİDEN yürütülmez (L4 —
                      double_tool_exec=0; FR-TOOL-009).
  • DETERMINISTIC:    birincil+fallback düşerse deterministik akışa (kural-tabanlı / insan aktarımı)
                      geçilir — ÇAĞRI DÜŞÜRÜLMEZ (L6 — dropped_call=0; "fail soft, never drop the call").
Ek (Must): anahtarlama gecikmesi sınırlı + ≥2 sağlayıcı (L5), seçici tetik + hata normalizasyonu (L7),
histerezis/flap yok + metering + model/versiyon kaydı + residency (L8).

KAPSAM AYRIMI: LlmAdapter implementasyonu (streaming token/tool-call/süreklilik) → 4.2.4 (bu motor
SARMALAR, uygulamaz); ortak yetenekler (timeout/retry/backoff/circuit-breaker/health) → 4.1.2 (circuit-open
sinyali TÜKETİLİR); hata normalizasyonu eşlemesi → 4.1.5 (TÜKETİLİR); connection pool → 4.1.6; metering
motoru → 4.1.3 (UsageRecord ÜRETİMİ doğrulanır); residency/retention → 4.1.4; model ROUTING/tiering motoru
→ 5.1-5.3 (fallback'ten AYRI); semantic cache → 5.4; policy engine/CONTENT_FILTERED → 3.3.2; tool yürütücü/
idempotency anahtarı → 7.x (FR-TOOL-009; tekrar-yürütmeme KARARI üretilir); deterministik akış/insan aktarımı
MOTORU → 8.x/3.3.x (KARARI üretilir, aktarım akışı değil); LLM sağlayıcı SEÇİMİ → 0.2.4/0.2.6/0.3.x.

Komutlar:
  validate              llm-fallback-spec.json'ı invariant'lara (L1–L10) + config sağlayıcı/profillerine doğrular.
  simulate <sample>     Deterministik switcher — olay-akışı (start + turn_start + first_token + tool_exec +
                        turn_complete + provider_error + end) → failover/deterministic-flow metrikleri →
                        HARD kapılar (L1–L8) → çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek LLM yerine sağlayıcı gecikme profili (config providers) + akış/
hata MODELİ kullanır (canlı sistemde Go/Rust async runtime + gerçek LlmAdapter + 4.1.2 circuit breaker,
ADR-003/SAD §6.3/§8.1). Ham PROMPT/mesaj METNİ, model çıktısı METNİ veya PII DEĞERİ YOK — yalnız sağlayıcı/
model kimliği + gecikme/akış/token SAYILARI + tur/tool kimlikleri + normalize edilmiş hata sınıfı + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "llm-fallback-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "llm-fallback-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

REQUIRED_FEATURES = {"streaming", "tool_call"}
ALLOWED_RETENTION = {"NONE", "EPHEMERAL"}
FAILOVER_CLASSES = {"TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "QUOTA_EXCEEDED"}
NON_FAILOVER_CLASSES = {"AUTH", "INVALID_REQUEST", "CONTENT_FILTERED", "REGION_VIOLATION"}
END_REASONS = {"normal", "transfer", "error", "abandon"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _percentile(values, pct):
    """Lineer-interpolasyonlu yüzdelik (stt/tts_fallback / llm_adapter probe ile birebir)."""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    rank = (pct / 100.0) * (len(xs) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    frac = rank - lo
    return float(xs[lo] + (xs[hi] - xs[lo]) * frac)


class LlmFallbackError(Exception):
    """Geçersiz/desteklenmeyen olay veya yetki/izolasyon ihlali — sessizce kabul yok, reddet (L10)."""


# ─────────────────────────────────────────────────────────────────────────────
# LLM fallback switcher referans sürücüsü (deterministik, tur-tabanlı)
# ─────────────────────────────────────────────────────────────────────────────
class LlmFallbackRuntime:
    """SAD §8.3 + §9.1 [4] LLM fallback switcher. Tek çağrının tur-akışını işler:
        start → (turn_start → (first_token | tool_exec | provider_error)* → turn_complete)* → end
    Aktif (birincil) LlmAdapter izlenir; geçici hata/timeout → fallback modele geçiş + tur isteği yeniden
    sunumu (ilk-token öncesi temiz; sonrası mid-stream güvenli degrade); birincil+fallback düşerse
    deterministik akış. Tüm gecikmeler sağlayıcı PROFİLİNDEN deterministik (random YOK; sanal saat = event.t).

    Olaylar:
      {kind:'start', t, tenant_id?}
      {kind:'turn_start', t, turn_id, tier?, critical?}        # yeni diyalog turu (complete() çağrısı)
      {kind:'first_token', t, turn_id}                          # aktif model ilk token'ı downstream'e (TTS)
      {kind:'tool_exec', t, turn_id, tool_id, side_effecting?}  # tool çağrısı yürütüldü (yan etki olabilir)
      {kind:'turn_complete', t, turn_id}                        # tur yanıtı tamamlandı
      {kind:'provider_error', t, turn_id?, raw_error}           # aktif model hatası → routing kararı
      {kind:'end', t, reason∈{normal,transfer,error,abandon}}
    """

    def __init__(self, primary, secondary, policy, gates, error_taxonomy, tenant_id="t-self"):
        self.primary = primary
        self.secondary = secondary
        self.pol = policy
        self.g = gates
        self.tax_map = (error_taxonomy or {}).get("mapping", {})
        self.tenant_id = tenant_id
        self.failover_classes = set(gates.get("failover_error_classes", list(FAILOVER_CLASSES)))

        self._last_t = None
        self.active = "primary"            # primary | fallback | deterministic | dropped
        self.active_provider = primary
        self.switched = False              # seans-seviyesi: bir kez fallback'e geçince sticky (histerezis)
        self.segments = 0                  # aktif model stint sayısı (metering)
        self.model_versions_recorded = 0   # FR-LLM-011
        self.turns = {}                    # turn_id -> {started, first_token, side_effect, completed, degraded}
        self.current_turn = None

        # ölçüm dizileri
        self.switch_overhead_ms = []
        # sayaçlar / metrikler
        self.turn_starts = 0
        self.turns_completed = 0
        self.failovers = 0                 # gerçekleşen model geçişi (llm_fallback_total)
        self.turn_lost = 0                 # L1
        self.missing_context = 0           # L2
        self.system_prompt_mutation = 0    # L2
        self.double_speak = 0              # L3
        self.duplicate_response = 0        # L3
        self.concurrent_active_max = 1     # L3
        self.double_tool_exec = 0          # L4
        self.dropped_call = 0              # L6
        self.deterministic_flow_count = 0  # L6
        self.mid_stream_degrade = 0        # L3 güvenli degrade (sağlıklı yol)
        self.improper_failover = 0         # L7
        self.flap_count = 0                # L8
        self.errors_seen = 0               # L7
        self.errors_normalized = 0         # L7
        self.cross_tenant = 0
        self.started = False
        self.ended = False

    # ── ortak guard'lar ───────────────────────────────────────────────────────
    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise LlmFallbackError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            if self.pol.get("order_guard", True):
                raise LlmFallbackError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        if tt != self.tenant_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise LlmFallbackError("cross-tenant erişim reddedildi → AUTH")

    def _activate(self, provider):
        """Bir modeli aktif et + metering segmenti + model/versiyon kaydı aç (L8)."""
        self.active_provider = provider
        if self.pol.get("meter", True):
            self.segments += 1
            if self.pol.get("record_model_version", True):
                self.model_versions_recorded += 1

    def _turn(self, turn_id):
        if turn_id is None:
            turn_id = self.current_turn
        if turn_id is None:
            raise LlmFallbackError("turn_id yok (aktif tur belirsiz) → INVALID_REQUEST")
        return turn_id

    # ── start ─────────────────────────────────────────────────────────────────
    def start(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if self.started:
            raise LlmFallbackError("start tekrar → INVALID_REQUEST")
        self.started = True
        self.active = "primary"
        self.switched = False
        self._activate(self.primary)

    # ── turn_start ──────────────────────────────────────────────────────────────
    def turn_start(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise LlmFallbackError("start'tan önce turn_start → INVALID_REQUEST")
        u = ev.get("turn_id")
        if not isinstance(u, str) or not u:
            raise LlmFallbackError("turn_id yok/boş → INVALID_REQUEST")
        if u in self.turns and self.turns[u]["started"]:
            raise LlmFallbackError("aynı turn_id tekrar başlatıldı → INVALID_REQUEST")
        self.turns[u] = {"started": True, "first_token": False, "side_effect": False,
                         "completed": False, "degraded": False}
        self.current_turn = u
        self.turn_starts += 1

    # ── first_token: aktif model ilk token'ı downstream'e gönderdi ──────────────
    def first_token(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        u = self._turn(ev.get("turn_id"))
        if u not in self.turns:
            raise LlmFallbackError("first_token bilinmeyen tur → INVALID_REQUEST")
        if self.active in ("deterministic", "dropped"):
            return  # deterministik akışta model token'ı beklenmez (güvenli degrade)
        self.turns[u]["first_token"] = True

    # ── tool_exec: bir tool çağrısı yürütüldü (yan etki olabilir) ────────────────
    def tool_exec(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        u = self._turn(ev.get("turn_id"))
        if u not in self.turns:
            raise LlmFallbackError("tool_exec bilinmeyen tur → INVALID_REQUEST")
        if self.active in ("deterministic", "dropped"):
            return
        if ev.get("side_effecting", False):
            self.turns[u]["side_effect"] = True

    # ── turn_complete: aktif model bir turu tamamladı ───────────────────────────
    def turn_complete(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if self.active in ("deterministic", "dropped"):
            return  # deterministik akışta model tamamlaması beklenmez
        u = self._turn(ev.get("turn_id"))
        if u not in self.turns:
            raise LlmFallbackError("turn_complete bilinmeyen tur → INVALID_REQUEST")
        if self.turns[u]["completed"]:
            # aynı tur ikinci kez tamamlandı → dedup kararı (L3)
            if self.pol.get("dedup", True):
                return  # doğru: çift tamamlama bastırılır (failover sonrası tek yanıt)
            self.duplicate_response += 1
            return
        self.turns[u]["completed"] = True
        self.turns_completed += 1

    # ── provider_error: routing kararı (L1/L2/L3/L4/L6/L7) ──────────────────────
    def provider_error(self, ev):
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if not self.started:
            raise LlmFallbackError("start'tan önce hata → INVALID_REQUEST")
        raw = ev.get("raw_error")
        if raw is None:
            raise LlmFallbackError("provider_error raw_error yok → INVALID_REQUEST")
        self.errors_seen += 1
        tax = self._normalize(raw) if self.pol.get("normalize_errors", True) else None
        if tax is not None:
            self.errors_normalized += 1
        eff_tax = tax if tax is not None else "UNAVAILABLE"   # normalize edilmese de routing devam (L7 ayrı eler)
        transient = eff_tax in self.failover_classes

        if self.active in ("deterministic", "dropped"):
            return  # zaten degrade

        u = ev.get("turn_id", self.current_turn)
        st = self.turns.get(u) if u is not None else None
        first_tok = bool(st and st["first_token"] and not st["completed"])
        side_fx = bool(st and st["side_effect"] and not st["completed"])
        already_done = bool(st and st["completed"])

        if transient:
            if not self.pol.get("failover", True):
                # BOZUK: failover kapalı → tur kurtarılamaz, kaybolur (L1 ihlali)
                if st is not None and not already_done:
                    self.turn_lost += 1
                return
            if self.switched:
                # fallback de düştü → her iki model gitti
                if self.pol.get("hysteresis", True):
                    self._route_deterministic(eff_tax)   # doğru: geri dönme yok → deterministik akış
                else:
                    # BOZUK: birincile geri salınım (flap; L8 ihlali)
                    self.flap_count += 1
                    self.switched = False
                    self.active = "primary"
                    overhead = float(self.secondary.get("teardown_ms", 20)) \
                        + float(self.primary.get("setup_ms", 60)) + float(self.primary.get("first_token_ms", 150))
                    self.switch_overhead_ms.append(overhead)
                    self._activate(self.primary)
                return

            # ilk failover (birincil → fallback)
            if already_done:
                return  # tur zaten tamamlandı, hata geç geldi → yok say (kurtarma gereksiz)
            if first_tok or side_fx:
                # mid-stream / yan-etki sonrası: temiz yeniden istek MÜMKÜN DEĞİL
                safe = (not first_tok or self.pol.get("mid_stream_safe", True)) \
                    and (not side_fx or self.pol.get("tool_idempotency", True))
                if safe:
                    # doğru: sessiz yeniden istek yok → güvenli degrade (deterministik)
                    self.mid_stream_degrade += 1
                    if st is not None:
                        st["degraded"] = True
                    self._route_deterministic(eff_tax, count_det=False)
                else:
                    # BOZUK: yeniden istek → çift konuşma ve/veya çift yan-etki
                    if first_tok and not self.pol.get("mid_stream_safe", True):
                        self.double_speak += 1
                    if side_fx and not self.pol.get("tool_idempotency", True):
                        self.double_tool_exec += 1
                    self._failover(eff_tax)
            else:
                # temiz pre-first-token failover: context yeniden sunumu
                if self.pol.get("context_resubmission", True):
                    if not self.pol.get("preserve_system_prompt", True):
                        self.system_prompt_mutation += 1   # BOZUK: system prompt korunmadı (FR-LLM-006)
                    self._failover(eff_tax)
                else:
                    # BOZUK: context yeniden sunulmadı → tur kaybolur (L2/L1 ihlali)
                    self.missing_context += 1
                    if st is not None and not already_done:
                        self.turn_lost += 1
        else:
            # geçici OLMAYAN sınıf (AUTH/INVALID_REQUEST/REGION_VIOLATION/CONTENT_FILTERED)
            if not self.pol.get("selective_trigger", True):
                # BOZUK: seçici tetik kapalı → boşuna model değişimi (L7 ihlali)
                self.improper_failover += 1
                self._failover(eff_tax)
            else:
                # doğru: model değiştirme yok → politika/deterministik akış (güvenli degrade)
                self._route_deterministic(eff_tax)

    def _failover(self, reason):
        """Birincil → fallback model geçişi (context yeniden sunumu + switch overhead)."""
        target = self.secondary
        if not self.pol.get("single_active", True):
            self.concurrent_active_max = max(self.concurrent_active_max, 2)
        overhead = float(self.primary.get("teardown_ms", 20)) \
            + float(target.get("setup_ms", 40)) + float(target.get("first_token_ms", 170))
        self.switch_overhead_ms.append(overhead)
        self.failovers += 1
        self.switched = True
        self.active = "fallback"
        self._activate(target)

    def _route_deterministic(self, reason, count_det=True):
        if self.active in ("deterministic", "dropped"):
            return
        if self.pol.get("deterministic_flow", True):
            if count_det:
                self.deterministic_flow_count += 1
            self.active = "deterministic"
        else:
            # BOZUK: deterministik akış yok → çağrı düşürülür (L6 ihlali)
            self.dropped_call += 1
            self.active = "dropped"

    def _normalize(self, raw):
        if raw in ERROR_TAXONOMY:
            return raw
        return self.tax_map.get(raw)

    def end(self, ev):
        self._check_time(ev.get("t"))
        if self.ended:
            raise LlmFallbackError("end tekrar → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_REASONS:
            raise LlmFallbackError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True

    def metrics(self):
        scenario = []
        if self.failovers:
            scenario.append("failover" if self.turn_lost == 0 else "turn-lost")
        if self.mid_stream_degrade:
            scenario.append("mid-stream-degrade")
        if self.deterministic_flow_count:
            scenario.append("deterministic-flow")
        if self.dropped_call:
            scenario.append("dropped-call")
        if self.double_speak:
            scenario.append("double-speak")
        if self.double_tool_exec:
            scenario.append("double-tool-exec")
        if self.improper_failover:
            scenario.append("improper-failover")
        if self.flap_count:
            scenario.append("flap")
        if not scenario:
            scenario.append("no-failover" if self.turns_completed else "empty")
        usage_records = self.segments  # _activate yalnız meter açıkken artırır
        return {
            "primary_id": self.primary.get("provider_id"),
            "secondary_id": self.secondary.get("provider_id"),
            "active_at_end": self.active,
            "turn_starts": self.turn_starts,
            "turns_completed": self.turns_completed,
            "failovers": self.failovers,
            "switch_overhead_p95_ms": _percentile(self.switch_overhead_ms, 95),
            "switch_overhead_p50_ms": _percentile(self.switch_overhead_ms, 50),
            "switch_overhead_max_ms": max(self.switch_overhead_ms) if self.switch_overhead_ms else None,
            "turn_lost": self.turn_lost,
            "missing_context": self.missing_context,
            "system_prompt_mutation": self.system_prompt_mutation,
            "double_speak": self.double_speak,
            "duplicate_response": self.duplicate_response,
            "concurrent_active_max": self.concurrent_active_max,
            "double_tool_exec": self.double_tool_exec,
            "dropped_call": self.dropped_call,
            "deterministic_flow_count": self.deterministic_flow_count,
            "mid_stream_degrade": self.mid_stream_degrade,
            "improper_failover": self.improper_failover,
            "flap_count": self.flap_count,
            "errors_seen": self.errors_seen,
            "errors_normalized": self.errors_normalized,
            "provider_segments": self.segments,
            "usage_records": usage_records,
            "model_versions_recorded": self.model_versions_recorded,
            "cross_tenant": self.cross_tenant,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, primary, secondary, policy, gates, error_taxonomy):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise LlmFallbackError("boş/geçersiz olay akışı → INVALID_REQUEST")
    rt = LlmFallbackRuntime(primary, secondary, policy, gates, error_taxonomy,
                            tenant_id=sample.get("tenant_id", "t-self"))
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise LlmFallbackError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "start":
            rt.start(ev)
        elif kind == "turn_start":
            rt.turn_start(ev)
        elif kind == "first_token":
            rt.first_token(ev)
        elif kind == "tool_exec":
            rt.tool_exec(ev)
        elif kind == "turn_complete":
            rt.turn_complete(ev)
        elif kind == "provider_error":
            rt.provider_error(ev)
        elif kind == "end":
            rt.end(ev)
            saw_end = True
        else:
            raise LlmFallbackError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not rt.started:
        raise LlmFallbackError("olay akışında 'start' yok → INVALID_REQUEST")
    if not saw_end:
        raise LlmFallbackError("olay akışında 'end' yok → INVALID_REQUEST")
    return rt.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (L1–L8 davranışsal) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── L1: FAILOVER — tur kaybı yok
    F.append((m.get("turn_lost", 0) <= gates.get("max_turn_lost", 0),
              "L1 failover: turn_lost %d ≤ %d (%d failover; çağrı sürer — FR-LLM-010)"
              % (m.get("turn_lost", 0), gates.get("max_turn_lost", 0), m.get("failovers", 0))))

    # ── L2: CONTEXT RESUBMIT — context kaybı yok + system prompt korunur
    l2_ok = (m.get("missing_context", 0) <= gates.get("max_missing_context", 0)
             and m.get("system_prompt_mutation", 0) <= gates.get("max_system_prompt_mutation", 0))
    F.append((l2_ok,
              "L2 context-resubmit: missing_context %d ≤ %d + system_prompt_mutation %d ≤ %d (FR-LLM-006)"
              % (m.get("missing_context", 0), gates.get("max_missing_context", 0),
                 m.get("system_prompt_mutation", 0), gates.get("max_system_prompt_mutation", 0))))

    # ── L3: MID-STREAM SAFE / DUP YOK
    l3_ok = (m.get("double_speak", 0) <= gates.get("max_double_speak", 0)
             and m.get("duplicate_response", 0) <= gates.get("max_duplicate_response", 0)
             and m.get("concurrent_active_max", 1) <= gates.get("max_concurrent_active", 1))
    F.append((l3_ok,
              "L3 mid-stream/dup: double_speak %d ≤ %d + duplicate_response %d ≤ %d + concurrent_active %d ≤ %d "
              "(%d güvenli degrade; FR-RES-009)"
              % (m.get("double_speak", 0), gates.get("max_double_speak", 0),
                 m.get("duplicate_response", 0), gates.get("max_duplicate_response", 0),
                 m.get("concurrent_active_max", 1), gates.get("max_concurrent_active", 1),
                 m.get("mid_stream_degrade", 0))))

    # ── L4: TOOL IDEMPOTENCY
    F.append((m.get("double_tool_exec", 0) <= gates.get("max_double_tool_exec", 0),
              "L4 tool-idempotency: double_tool_exec %d ≤ %d (yan etkili tool yeniden yürütülmez — FR-TOOL-009)"
              % (m.get("double_tool_exec", 0), gates.get("max_double_tool_exec", 0))))

    # ── L5: SWITCH OVERHEAD — sınırlı ölü hava
    so95 = m.get("switch_overhead_p95_ms")
    F.append(((so95 is None or so95 <= gates.get("switch_overhead_p95_ms", 500)),
              "L5 overhead: switch P95 %s ≤ %d ms (teardown+fallback setup+ilk token; NFR 10.1/SAD §20)"
              % (_fmt(so95), gates.get("switch_overhead_p95_ms", 500))))

    # ── L6: DETERMINISTIC FLOW / NEVER DROP
    F.append((m.get("dropped_call", 0) <= gates.get("max_dropped_call", 0),
              "L6 never-drop: dropped_call %d ≤ %d (%d deterministik akış; BRD §19 (4))"
              % (m.get("dropped_call", 0), gates.get("max_dropped_call", 0),
                 m.get("deterministic_flow_count", 0))))

    # ── L7: SELECTIVE TRIGGER + ERROR NORMALIZED
    norm_ok = (not gates.get("require_error_normalized", True)) \
        or (m.get("errors_normalized", 0) == m.get("errors_seen", 0))
    l7_ok = (m.get("improper_failover", 0) <= gates.get("max_improper_failover", 0)) and norm_ok
    F.append((l7_ok,
              "L7 seçici+normalize: improper_failover %d ≤ %d + err_norm %d/%d (FR-TOOL-008/SAD §8.3)"
              % (m.get("improper_failover", 0), gates.get("max_improper_failover", 0),
                 m.get("errors_normalized", 0), m.get("errors_seen", 0))))

    # ── L8: NO FLAP + METERING + MODEL/VERSİYON KAYDI + RESIDENCY
    meter_ok = (not gates.get("require_metering", True)) \
        or (m.get("usage_records", 0) == m.get("provider_segments", 0) and m.get("usage_records", 0) > 0)
    mv_ok = (not gates.get("require_model_version_recorded", True)) \
        or (m.get("model_versions_recorded", 0) == m.get("provider_segments", 0))
    l8_ok = (m.get("flap_count", 0) <= gates.get("max_flap", 0)) and meter_ok and mv_ok \
        and m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0)
    F.append((l8_ok,
              "L8 flap+metering+model/ver: flap %d ≤ %d + usage %d/%d seg + model_ver %d/%d + cross_tenant %d "
              "(FR-BIL-002/FR-LLM-011/NFR 10.7)"
              % (m.get("flap_count", 0), gates.get("max_flap", 0),
                 m.get("usage_records", 0), m.get("provider_segments", 0),
                 m.get("model_versions_recorded", 0), m.get("provider_segments", 0),
                 m.get("cross_tenant", 0))))

    return F


def _fmt(v):
    return "n/a" if v is None else ("%.1f" % v)


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _provider_by_id(cfg, pid):
    for p in cfg.get("providers", []):
        if p.get("provider_id") == pid:
            return p
    raise LlmFallbackError("bilinmeyen sağlayıcı: %s" % pid)


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise LlmFallbackError("bilinmeyen profil: %s" % name)


def _default_policy():
    return {
        "failover": True,
        "context_resubmission": True,
        "preserve_system_prompt": True,
        "mid_stream_safe": True,
        "tool_idempotency": True,
        "deterministic_flow": True,
        "selective_trigger": True,
        "single_active": True,
        "hysteresis": True,
        "dedup": True,
        "meter": True,
        "record_model_version": True,
        "normalize_errors": True,
        "tenant_isolation": True,
        "order_guard": True,
    }


def _resolve_policy(sample):
    pol = _default_policy()
    pol.update(sample.get("policy", {}))
    return pol


def _resolve_providers(sample, cfg):
    if "primary_obj" in sample and "secondary_obj" in sample:
        return sample["primary_obj"], sample["secondary_obj"]
    prof = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
    pid = sample.get("primary", prof.get("primary_provider"))
    sid = sample.get("secondary", prof.get("secondary_provider"))
    return (_provider_by_id(cfg, pid), _provider_by_id(cfg, sid))


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    gates = spec.get("gates", {})
    policy = _resolve_policy(sample)

    try:
        cfg = _load(PROFILES_CFG)
        primary, secondary = _resolve_providers(sample, cfg)
    except LlmFallbackError as ex:
        print("simulate[%s]: %s" % (name, ex))
        return 0 if expect == "fail" else 1

    try:
        m = simulate(sample, primary, secondary, policy, gates, spec.get("error_taxonomy", {}))
    except LlmFallbackError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] primary=%s fallback=%s senaryo=%s | %d tur | %d tamam | %d failover | "
          "switch P95=%s ms | active@end=%s"
          % (name, m["primary_id"], m["secondary_id"], "+".join(m["scenario"]),
             m["turn_starts"], m["turns_completed"], m["failovers"],
             _fmt(m["switch_overhead_p95_ms"]), m["active_at_end"]))
    print("  turn_lost=%d | missing_ctx=%d | sysprompt_mut=%d | double_speak=%d | dup_resp=%d | "
          "double_tool=%d | dropped=%d | det_flow=%d | mid_degrade=%d | improper=%d | flap=%d | "
          "usage=%d/%d seg | model_ver=%d | err_norm=%d/%d"
          % (m["turn_lost"], m["missing_context"], m["system_prompt_mutation"], m["double_speak"],
             m["duplicate_response"], m["double_tool_exec"], m["dropped_call"],
             m["deterministic_flow_count"], m["mid_stream_degrade"], m["improper_failover"],
             m["flap_count"], m["usage_records"], m["provider_segments"],
             m["model_versions_recorded"], m["errors_normalized"], m["errors_seen"]))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F) and len(F) > 0

    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match
    print("  kapı: %d/%d %s" % (sum(1 for ok, _ in F if ok), len(F),
                                 "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _check(results, ok, label):
    results.append((bool(ok), label))


def _scan_secrets(obj, path="root"):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan_secrets(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_secrets(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if SECRET_RE.search(obj):
            hits.append((path, obj))
    return hits


def _provider_conformant(p):
    feats = set(p.get("features", []))
    return REQUIRED_FEATURES <= feats and p.get("no_train", False) is True


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "4.3.3", "spec.wbs == 4.3.3")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement
    pl = spec.get("placement", {})
    _check(R, pl.get("behind_spi") is True and pl.get("orchestrator_depends_on_spi_only") is True,
           "LlmAdapter SPI arkası; orchestrator yalnız SPI'ye + karara bağımlı (ADR-001/SAD §8.1)")
    _check(R, pl.get("turn_state") == "THINK", "THINK durumunda (SAD §6.1)")
    _check(R, pl.get("stream_first") is True, "akış-önce (stream-first, FR-RES-002)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, bool(pl.get("circuit_breaker_owned_by")), "L9 circuit breaker 4.1.2'den tüketilir")
    _check(R, bool(pl.get("routing_owned_by")), "L9 routing/tiering 5.1-5.3'ten (fallback'ten ayrı)")
    _check(R, bool(pl.get("deterministic_flow_owned_by")), "L9 deterministic flow motoru 8.x/3.3.x/3.3.2")

    # ── spi yüzeyi (L5)
    sp = spec.get("spi", {})
    _check(R, "complete" in sp.get("wraps_methods", []), "SPI complete() sarmalanır (SAD §8.1/API §11.4)")
    _check(R, sp.get("presents_single_logical_complete") is True,
           "L3 orchestrator'a tek mantıksal complete() sunulur")
    _check(R, set(sp.get("required_features", [])) == REQUIRED_FEATURES,
           "L5 required_features {streaming, tool_call}")
    _check(R, "messages" in sp.get("llm_request_fields", []) and "tools" in sp.get("llm_request_fields", []),
           "LlmRequest messages + tools (FR-LLM-006/008)")
    _check(R, "ToolCallChunk" in sp.get("chunk_types", []),
           "LlmChunk ToolCallChunk (schema-doğrulamalı — FR-LLM-008)")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("switch_overhead_p95_ms") == 500, "L5 switch_overhead_p95_ms = 500 (NFR 10.1/SAD §20)")
    _check(R, g.get("switch_overhead_green_ms", 1e9) < g.get("switch_overhead_p95_ms", 0),
           "L5 yeşil bant < kapı (switch overhead)")
    _check(R, g.get("max_turn_lost", -1) == 0, "L1 max_turn_lost = 0")
    _check(R, g.get("max_missing_context", -1) == 0, "L2 max_missing_context = 0")
    _check(R, g.get("max_system_prompt_mutation", -1) == 0, "L2 max_system_prompt_mutation = 0 (FR-LLM-006)")
    _check(R, g.get("max_double_speak", -1) == 0, "L3 max_double_speak = 0")
    _check(R, g.get("max_duplicate_response", -1) == 0, "L3 max_duplicate_response = 0")
    _check(R, g.get("max_concurrent_active", -1) == 1, "L3 max_concurrent_active = 1 (tek aktif model)")
    _check(R, g.get("max_double_tool_exec", -1) == 0, "L4 max_double_tool_exec = 0 (FR-TOOL-009)")
    _check(R, g.get("max_dropped_call", -1) == 0, "L6 max_dropped_call = 0 (never drop)")
    _check(R, g.get("max_improper_failover", -1) == 0, "L7 max_improper_failover = 0 (seçici tetik)")
    _check(R, g.get("max_flap", -1) == 0, "L8 max_flap = 0 (histerezis)")
    _check(R, g.get("max_cross_tenant", -1) == 0, "L8 max_cross_tenant = 0")
    _check(R, g.get("min_providers", 0) >= 2, "L5 min_providers ≥ 2 (ADR-002 / BRD §19 (1))")
    _check(R, g.get("require_deterministic_flow") is True, "L6 require_deterministic_flow")
    _check(R, g.get("require_error_normalized") is True, "L7 require_error_normalized (FR-TOOL-008)")
    _check(R, g.get("require_metering") is True, "L8 require_metering (FR-BIL-002)")
    _check(R, g.get("require_model_version_recorded") is True, "L8 require_model_version_recorded (FR-LLM-011)")
    _check(R, set(g.get("required_features", [])) == REQUIRED_FEATURES,
           "gates required_features SPI ile tutarlı")
    _check(R, set(g.get("failover_error_classes", [])) == FAILOVER_CLASSES,
           "L7 failover_error_classes = {TIMEOUT,RATE_LIMITED,UNAVAILABLE,QUOTA_EXCEEDED} (geçici+ayrı-kota)")

    # ── fallback zinciri (L1/L2/L6)
    fb = spec.get("fallback", {})
    _check(R, fb.get("chain") == ["primary_llm", "fallback_llm", "deterministic_flow"],
           "L1/L6 fallback zinciri primary→fallback→deterministic (SAD §8.3/§9.1)")
    _check(R, fb.get("min_providers", 0) >= 2 and fb.get("context_resubmission") is True,
           "L2/L5 fallback ≥2 sağlayıcı + context yeniden sunumu (FR-LLM-010)")
    _check(R, fb.get("mid_stream_safe_degrade") is True, "L3 mid-stream güvenli degrade")
    _check(R, fb.get("tool_idempotency") is True, "L4 tool idempotency (FR-TOOL-009)")
    _check(R, fb.get("hysteresis_sticky_fallback") is True, "L8 histerezis (sticky fallback, flap yok)")
    _check(R, fb.get("deterministic_flow_on_total_failure") is True, "L6 her iki düşerse deterministik akış")
    _check(R, fb.get("switching_owned_by", "").startswith("4.3.3"),
           "fallback anahtarlama BU görevde (4.3.3)")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"llm_fallback_total", "llm_switch_overhead_ms", "llm_deterministic_flow_total",
               "llm_turn_total", "llm_double_speak_total", "llm_double_tool_exec_total"} <= emitted,
           "metrikler: fallback + switch_overhead + deterministic_flow + turn + double_speak/tool yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (L7/L10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 6, "L10 hata eşlemesi (≥6)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "L10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("provider_timeout") == "TIMEOUT"
           and mapping.get("provider_5xx") == "UNAVAILABLE"
           and mapping.get("circuit_open") == "UNAVAILABLE"
           and mapping.get("quota_exceeded") == "QUOTA_EXCEEDED"
           and mapping.get("content_filter") == "CONTENT_FILTERED"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "L7/L10 timeout→TIMEOUT, 5xx/circuit→UNAVAILABLE, quota→QUOTA, content→CONTENT_FILTERED, bölge→REGION")
    _check(R, set(et.get("failover_classes", [])) == FAILOVER_CLASSES
           and set(et.get("non_failover_classes", [])) == NON_FAILOVER_CLASSES,
           "L7 failover_classes geçici+kota + non_failover_classes (AUTH/INVALID/CONTENT_FILTERED/REGION)")
    _check(R, "CONTENT_FILTERED" in et.get("non_failover_classes", []),
           "L7 CONTENT_FILTERED model değiştirmez (politika/deterministik akış)")

    # ── residency + pii (L8/L10)
    rs = spec.get("residency", {})
    _check(R, rs.get("region_pin_required") is True, "L8 residency region pin (NFR 10.7)")
    _check(R, rs.get("no_train_required") is True, "L8 no-train (FR-LLM-012)")
    _check(R, rs.get("no_log_required") is True
           and set(rs.get("allowed_retention", [])) <= ALLOWED_RETENTION,
           "L8 no-log: data_retention NONE/EPHEMERAL (FR-KB-010)")
    _check(R, rs.get("context_buffer_ephemeral") is True, "L2 context tamponu ephemeral (durable değil)")
    pii = spec.get("pii", {})
    _check(R, pii.get("raw_prompt_in_spec_forbidden") is True
           and pii.get("raw_output_in_spec_forbidden") is True
           and pii.get("pii_value_in_spec_forbidden") is True,
           "L10 ham prompt/çıktı/PII değeri spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 10,
           "invariant kataloğu ≥10 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "L10 literal sır yok (spec+config)")

    # ── config sağlayıcı + profil doğrulaması (L5)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        provs = cfg.get("providers", [])
        conformant = [p for p in provs if _provider_conformant(p)]
        _check(R, len(conformant) >= g.get("min_providers", 2),
               "L5 ≥%d SPI-uyumlu sağlayıcı (streaming + tool_call + noTrain)" % g.get("min_providers", 2))
        pids = [p.get("provider_id") for p in provs]
        _check(R, len(pids) == len(set(pids)), "config sağlayıcı ID'leri benzersiz")
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 çalıştırma profili")
        for prof in profs:
            _check(R, bool(prof.get("region")), "L8 config %s bölge pini var" % prof.get("name"))
            _check(R, bool(prof.get("deterministic_flow_id")),
                   "L6 config %s deterministic_flow_id var" % prof.get("name"))
            _check(R, prof.get("primary_provider") in pids and prof.get("secondary_provider") in pids,
                   "L5 config %s primary+fallback geçerli sağlayıcı" % prof.get("name"))
            _check(R, prof.get("primary_provider") != prof.get("secondary_provider"),
                   "L5 config %s primary≠fallback (≥2 sağlayıcı)" % prof.get("name"))
            pp = _provider_by_id(cfg, prof.get("primary_provider"))
            spv = _provider_by_id(cfg, prof.get("secondary_provider"))
            _check(R, _provider_conformant(pp) and _provider_conformant(spv),
                   "L5 config %s primary+fallback SPI-uyumlu" % prof.get("name"))
            _check(R, set(pp.get("data_retention", "").split()) <= ALLOWED_RETENTION
                   and set(spv.get("data_retention", "").split()) <= ALLOWED_RETENTION,
                   "L8 config %s primary+fallback data_retention NONE/EPHEMERAL" % prof.get("name"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest yardımcıları
# ─────────────────────────────────────────────────────────────────────────────
PROVIDER_A = {
    "provider_id": "llm-cloud-A", "features": ["streaming", "tool_call"], "tiers": ["small", "large"],
    "no_train": True, "data_retention": "NONE",
    "setup_ms": 60, "teardown_ms": 20, "first_token_ms": 140,
}
PROVIDER_B = {
    "provider_id": "llm-cloud-B", "features": ["streaming", "tool_call"], "tiers": ["small", "large"],
    "no_train": True, "data_retention": "EPHEMERAL",
    "setup_ms": 40, "teardown_ms": 15, "first_token_ms": 170,
}


def _start(t=0, tenant=None):
    ev = {"kind": "start", "t": t}
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _ts(t, u, tier="large", critical=False):
    return {"kind": "turn_start", "t": t, "turn_id": u, "tier": tier, "critical": critical}


def _ft(t, u):
    return {"kind": "first_token", "t": t, "turn_id": u}


def _tool(t, u, tool_id="t1", side=True):
    return {"kind": "tool_exec", "t": t, "turn_id": u, "tool_id": tool_id, "side_effecting": side}


def _tc(t, u):
    return {"kind": "turn_complete", "t": t, "turn_id": u}


def _err(t, raw="provider_timeout", u=None):
    ev = {"kind": "provider_error", "t": t, "raw_error": raw}
    if u is not None:
        ev["turn_id"] = u
    return ev


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, primary=None, secondary=None, **pol_over):
    spec = _load(SPEC_PATH)
    pol = _default_policy()
    pol.update(pol_over)
    return simulate({"events": events}, primary or PROVIDER_A, secondary or PROVIDER_B,
                    pol, spec.get("gates", {}), spec.get("error_taxonomy", {}))


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: pre-first-token failover → context resubmit → fallback'te tamamlanır (L1–L8) ──
    mh = _run([
        _start(0),
        _ts(100, "u1"), _ft(250, "u1"), _tc(600, "u1"),          # 1. tur birincilde tamam
        _ts(2000, "u2"),                                          # 2. tur başlar
        _err(2100, "provider_timeout", "u2"),                     # ilk token ÖNCE timeout → temiz failover
        _ft(2400, "u2"), _tc(2800, "u2"),                         # fallback'te tamam
        _end(6000, "normal"),
    ])
    case(mh["failovers"] == 1 and mh["turn_lost"] == 0, "happy: 1 failover, tur kaybı yok (L1)")
    case(mh["missing_context"] == 0 and mh["system_prompt_mutation"] == 0, "happy: context resubmit + sys-prompt korundu (L2)")
    case(mh["double_speak"] == 0 and mh["duplicate_response"] == 0 and mh["concurrent_active_max"] == 1, "happy: dup/double-speak yok + tek model (L3)")
    case(mh["double_tool_exec"] == 0, "happy: double tool exec yok (L4)")
    case(mh["switch_overhead_p95_ms"] is not None and mh["switch_overhead_p95_ms"] <= 500, "happy: switch overhead ≤500ms (L5)")
    case(mh["dropped_call"] == 0, "happy: çağrı düşmedi (L6)")
    case(mh["improper_failover"] == 0 and mh["errors_normalized"] == mh["errors_seen"] == 1, "happy: seçici tetik + normalize (L7)")
    case(mh["flap_count"] == 0 and mh["usage_records"] == mh["provider_segments"] == 2
         and mh["model_versions_recorded"] == 2, "happy: flap yok + 2 segment metering + model/ver kaydı (L8)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "happy tüm kapıları geçer")
    case(mh["turns_completed"] == 2, "happy: 2 tur tamam (u1 birincil, u2 fallback)")

    # ── determinizm ─────────────────────────────────────────────────────────────
    ev = [_start(0), _ts(100, "u1"), _err(200, "circuit_open", "u1"), _ft(500, "u1"), _tc(800, "u1"), _end(2000)]
    case(_run(ev) == _run(ev), "determinizm: aynı olay-akışı birebir aynı metrik (random yok)")

    # ── no-failover happy: hatasız çağrı geçer ──────────────────────────────────
    mn = _run([_start(0), _ts(100, "u1"), _ft(250, "u1"), _tc(600, "u1"), _end(1000)])
    case(mn["failovers"] == 0 and mn["turns_completed"] == 1 and all(ok for ok, _ in evaluate(gates, mn)),
         "no-failover: hatasız çağrı tüm kapıları geçer")

    # ── ≥2 sağlayıcı ────────────────────────────────────────────────────────────
    case(mh["primary_id"] == "llm-cloud-A" and mh["secondary_id"] == "llm-cloud-B",
         "≥2 sağlayıcı: primary A + fallback B (ADR-002 / BRD §19 (1))")

    # ── mid-stream güvenli degrade: ilk token sonrası hata → double_speak=0 (L3) ──
    mm = _run([_start(0), _ts(100, "u1"), _ft(300, "u1"),         # ilk token gitti
               _err(450, "provider_5xx", "u1"),                  # SONRA düştü → güvenli degrade
               _end(2000, "transfer")])
    case(mm["double_speak"] == 0 and mm["mid_stream_degrade"] == 1 and mm["failovers"] == 0,
         "mid-stream: ilk token sonrası hata → sessiz yeniden istek yok, güvenli degrade (L3)")
    case(all(ok for ok, _ in evaluate(gates, mm)), "mid-stream güvenli degrade tüm kapıları geçer")

    # ── tool idempotency: yan etkili tool sonrası hata → double_tool_exec=0 (L4) ──
    mt = _run([_start(0), _ts(100, "u1"), _tool(300, "u1", side=True),   # ödeme yürütüldü
               _err(450, "provider_timeout", "u1"),                       # SONRA düştü
               _end(2000, "transfer")])
    case(mt["double_tool_exec"] == 0 and mt["mid_stream_degrade"] == 1,
         "tool-idempotency: yan etkili tool sonrası hata → yeniden yürütme yok (L4)")
    case(all(ok for ok, _ in evaluate(gates, mt)), "tool idempotency tüm kapıları geçer")

    # ── both-fail → deterministic flow, çağrı düşmez (L6) ───────────────────────
    mb = _run([
        _start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"),   # → fallback
        _ft(500, "u1"), _tc(800, "u1"),
        _ts(2000, "u2"), _err(2100, "provider_5xx", "u2"),                # fallback de düştü → deterministic
        _end(4000, "transfer"),
    ])
    case(mb["failovers"] == 1 and mb["deterministic_flow_count"] == 1 and mb["dropped_call"] == 0,
         "both-fail: fallback de düşünce deterministik akış, çağrı düşmez (L6)")
    case(all(ok for ok, _ in evaluate(gates, mb)), "both-fail deterministic flow tüm kapıları geçer")

    # ── selective trigger: CONTENT_FILTERED failover ETMEZ → deterministic (L7) ──
    mc = _run([_start(0), _ts(100, "u1"), _err(200, "content_filter", "u1"), _end(2000, "transfer")])
    case(mc["failovers"] == 0 and mc["improper_failover"] == 0 and mc["deterministic_flow_count"] == 1,
         "selective: CONTENT_FILTERED model değiştirmez → politika/deterministik akış (L7)")
    case(all(ok for ok, _ in evaluate(gates, mc)), "selective CONTENT_FILTERED tüm kapıları geçer")

    # ── selective trigger: AUTH failover ETMEZ → deterministic (L7) ──────────────
    ma = _run([_start(0), _ts(100, "u1"), _err(200, "auth_failure", "u1"), _end(2000, "transfer")])
    case(ma["failovers"] == 0 and ma["improper_failover"] == 0 and ma["deterministic_flow_count"] == 1,
         "selective: AUTH geçici değil → failover yok, deterministik akış (L7)")
    case(all(ok for ok, _ in evaluate(gates, ma)), "selective AUTH tüm kapıları geçer")

    # ── QUOTA_EXCEEDED failover tetikler (ayrı sağlayıcı ayrı kota) ──────────────
    mq = _run([_start(0), _ts(100, "u1"), _err(200, "quota_exceeded", "u1"), _ft(500, "u1"), _tc(800, "u1"), _end(2000)])
    case(mq["failovers"] == 1 and mq["improper_failover"] == 0,
         "QUOTA_EXCEEDED → fallback (ayrı sağlayıcı/kota), improper değil")

    # ── degraded-1: context resubmit kapalı → tur kaybolur (L1/L2 eler) ──────────
    d1 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _end(2000)],
              context_resubmission=False)
    case(d1["missing_context"] >= 1 and d1["turn_lost"] >= 1,
         "degraded(no-resubmit): context yeniden sunulmadı → tur kaybı (FR-LLM-010 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(no-resubmit) L1/L2 eler")

    # ── degraded-2: failover kapalı → tur kaybolur (L1 eler) ─────────────────────
    d2 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _end(2000)],
              failover=False)
    case(d2["failovers"] == 0 and d2["turn_lost"] >= 1,
         "degraded(no-failover): geçici hatada model değişimi yok → tur kaybı (L1)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(no-failover) L1 eler")

    # ── degraded-3: mid-stream güvenlik kapalı → çift konuşma (L3 eler) ──────────
    d3 = _run([_start(0), _ts(100, "u1"), _ft(300, "u1"), _err(450, "provider_5xx", "u1"),
               _ft(700, "u1"), _tc(1000, "u1"), _end(2000)], mid_stream_safe=False)
    case(d3["double_speak"] >= 1, "degraded(no-mid-stream-safe): ilk token sonrası yeniden istek → çift konuşma (L3)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(no-mid-stream-safe) L3 eler")

    # ── degraded-4: tool idempotency kapalı → çift yan-etki (L4 eler) ────────────
    d4 = _run([_start(0), _ts(100, "u1"), _tool(300, "u1", side=True), _err(450, "provider_timeout", "u1"),
               _ft(700, "u1"), _tc(1000, "u1"), _end(2000)], tool_idempotency=False)
    case(d4["double_tool_exec"] >= 1, "degraded(no-tool-idempotency): yan etkili tool yeniden yürütüldü (L4)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(no-tool-idempotency) L4 eler")

    # ── degraded-5: deterministic flow kapalı → çağrı düşer (L6 eler) ────────────
    d5 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _ft(500, "u1"), _tc(800, "u1"),
               _ts(2000, "u2"), _err(2100, "provider_5xx", "u2"), _end(4000)],
              deterministic_flow=False)
    case(d5["dropped_call"] >= 1, "degraded(no-det-flow): her iki düşünce çağrı düşürüldü (BRD §19 (4) ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(no-det-flow) L6 eler")

    # ── degraded-6: seçici tetik kapalı → AUTH'ta boşuna failover (L7 eler) ───────
    d6 = _run([_start(0), _ts(100, "u1"), _err(200, "auth_failure", "u1"), _ft(500, "u1"), _tc(800, "u1"), _end(2000)],
              selective_trigger=False)
    case(d6["improper_failover"] >= 1, "degraded(no-selective): AUTH'ta boşuna model değişimi (L7)")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(no-selective) L7 eler")

    # ── degraded-7: histerezis kapalı → flap (L8 eler) ──────────────────────────
    d7 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _ft(500, "u1"), _tc(800, "u1"),
               _ts(2000, "u2"), _err(2100, "provider_timeout", "u2"), _end(4000)],
              hysteresis=False)
    case(d7["flap_count"] >= 1, "degraded(no-hysteresis): fallback hatasında birincile geri salınım (flap; L8)")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(no-hysteresis) L8 eler")

    # ── degraded-8: dedup kapalı → çift yanıt (L3 eler) ─────────────────────────
    d8 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"),
               _tc(800, "u1"), _tc(900, "u1"), _end(2000)], dedup=False)
    case(d8["duplicate_response"] >= 1, "degraded(no-dedup): aynı tur iki tamamlama → duplicate (L3)")
    case(not all(ok for ok, _ in evaluate(gates, d8)), "degraded(no-dedup) L3 eler")

    # ── degraded-9: tek-aktif kapalı → eşzamanlı çift aktif (L3 eler) ────────────
    d9 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _ft(500, "u1"), _tc(800, "u1"), _end(2000)],
              single_active=False)
    case(d9["concurrent_active_max"] >= 2, "degraded(dual-active): anahtarlamada eşzamanlı çift aktif (L3)")
    case(not all(ok for ok, _ in evaluate(gates, d9)), "degraded(dual-active) L3 eler")

    # ── degraded-10: metering kapalı → UsageRecord eksik (L8 eler) ──────────────
    d10 = _run([_start(0), _ts(100, "u1"), _ft(250, "u1"), _tc(600, "u1"), _end(1000)], meter=False)
    case(d10["usage_records"] == 0, "degraded(no-meter): UsageRecord üretilmedi (FR-BIL-002)")
    case(not all(ok for ok, _ in evaluate(gates, d10)), "degraded(no-meter) L8 eler")

    # ── degraded-11: model/versiyon kaydı kapalı → FR-LLM-011 eler (L8) ──────────
    d11 = _run([_start(0), _ts(100, "u1"), _ft(250, "u1"), _tc(600, "u1"), _end(1000)], record_model_version=False)
    case(d11["model_versions_recorded"] == 0 and d11["usage_records"] == 1,
         "degraded(no-model-ver): model/versiyon kaydedilmedi (FR-LLM-011)")
    case(not all(ok for ok, _ in evaluate(gates, d11)), "degraded(no-model-ver) L8 eler")

    # ── degraded-12: hata normalize edilmedi (L7 eler) ──────────────────────────
    d12 = _run([_start(0), _ts(100, "u1"), _err(200, "raw-provider-503", "u1"), _ft(500, "u1"), _tc(800, "u1"), _end(2000)],
               normalize_errors=False)
    case(d12["errors_seen"] == 1 and d12["errors_normalized"] == 0,
         "degraded(no-norm): sağlayıcı hatası ErrorTaxonomy'ye çevrilmedi (FR-TOOL-008)")
    case(not all(ok for ok, _ in evaluate(gates, d12)), "degraded(no-norm) L7 eler")

    # ── degraded-13: system prompt korunmadı → mutation (L2 eler) ────────────────
    d13 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _ft(500, "u1"), _tc(800, "u1"), _end(2000)],
               preserve_system_prompt=False)
    case(d13["system_prompt_mutation"] >= 1, "degraded(sysprompt-mut): failover'da system prompt değişti (FR-LLM-006)")
    case(not all(ok for ok, _ in evaluate(gates, d13)), "degraded(sysprompt-mut) L2 eler")

    # ── degraded-14: yavaş fallback (C) → switch overhead kapısı eler (L5) ───────
    slow = {"provider_id": "llm-cloud-C", "features": ["streaming"], "no_train": False,
            "data_retention": "NONE", "setup_ms": 260, "teardown_ms": 90, "first_token_ms": 520}
    d14 = _run([_start(0), _ts(100, "u1"), _err(200, "provider_timeout", "u1"), _ft(900, "u1"), _tc(1300, "u1"), _end(3000)],
               secondary=slow)
    case(d14["switch_overhead_max_ms"] is not None and d14["switch_overhead_max_ms"] > 500,
         "degraded(slow-fallback): teardown+setup+ilk token > 500ms (L5)")
    case(not all(ok for ok, _ in evaluate(gates, d14)), "degraded(slow-fallback) L5 eler")

    # ── geçersiz olay reddi (L10) ───────────────────────────────────────────────
    case(_raises(lambda: _run([_ts(0, "u1"), _end(10)])), "L10 start'tan önce turn_start → reddedilir")
    case(_raises(lambda: _run([_start(0), _ts(10, "u1")])), "L10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_ts(0, "u1"), _end(10)])), "L10 'start' olmadan → reddedilir")
    case(_raises(lambda: _run([_start(0), _start(1), _end(2)])), "L10 tekrar start → reddedilir")
    case(_raises(lambda: _run([_start(1000), _ts(0, "u1"), _end(2000)])), "L10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_start(0), {"kind": "nope", "t": 1}, _end(2)])), "L10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": [_start(0), {"kind": "provider_error", "t": 10}, _end(20)]},
                                  PROVIDER_A, PROVIDER_B, _default_policy(), gates,
                                  spec.get("error_taxonomy", {}))),
         "L10 raw_error'suz provider_error → reddedilir")
    case(_raises(lambda: _run([_start(0), _ts(10, "u1"), _ts(20, "u1"), _end(30)])),
         "L10 aynı turn_id tekrar başlatıldı → reddedilir")
    case(_raises(lambda: simulate({"events": []}, PROVIDER_A, PROVIDER_B, _default_policy(), gates,
                                  spec.get("error_taxonomy", {}))), "L10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_start(0, tenant="t-other"), _end(50)])),
         "L10 cross-tenant (izolasyon açık) → reddedilir")
    case(_raises(lambda: _run([_start(0), _end(10, reason="weird")])), "L10 geçersiz bitiş nedeni → reddedilir")

    # ── validate negatif kapılar ────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["gates"]["switch_overhead_p95_ms"] = 999
    case(_validate_obj(s) != 0, "L5 switch_overhead_p95_ms≠500 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_turn_lost"] = 1
    case(_validate_obj(s) != 0, "L1 max_turn_lost>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_missing_context"] = 1
    case(_validate_obj(s) != 0, "L2 max_missing_context>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_system_prompt_mutation"] = 1
    case(_validate_obj(s) != 0, "L2 max_system_prompt_mutation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_double_speak"] = 1
    case(_validate_obj(s) != 0, "L3 max_double_speak>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_concurrent_active"] = 2
    case(_validate_obj(s) != 0, "L3 max_concurrent_active≠1 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_double_tool_exec"] = 1
    case(_validate_obj(s) != 0, "L4 max_double_tool_exec>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_dropped_call"] = 1
    case(_validate_obj(s) != 0, "L6 max_dropped_call>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_improper_failover"] = 1
    case(_validate_obj(s) != 0, "L7 max_improper_failover>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_flap"] = 1
    case(_validate_obj(s) != 0, "L8 max_flap>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["min_providers"] = 1
    case(_validate_obj(s) != 0, "L5 min_providers<2 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_deterministic_flow"] = False
    case(_validate_obj(s) != 0, "L6 require_deterministic_flow=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_model_version_recorded"] = False
    case(_validate_obj(s) != 0, "L8 require_model_version_recorded=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["failover_error_classes"] = ["TIMEOUT", "AUTH"]
    case(_validate_obj(s) != 0, "L7 failover_error_classes geçici-olmayan içerir → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["non_failover_classes"] = ["AUTH"]
    case(_validate_obj(s) != 0, "L7 CONTENT_FILTERED non-failover'dan çıkınca → validate eler")
    s = json.loads(json.dumps(spec)); s["fallback"]["chain"] = ["primary_llm", "fallback_llm"]
    case(_validate_obj(s) != 0, "L6 zincirde deterministic_flow yok → validate eler")
    s = json.loads(json.dumps(spec)); s["fallback"]["tool_idempotency"] = False
    case(_validate_obj(s) != 0, "L4 fallback.tool_idempotency=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "L10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "L10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["no_train_required"] = False
    case(_validate_obj(s) != 0, "L8 no-train kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["allowed_retention"] = ["PROVIDER_DEFAULT"]
    case(_validate_obj(s) != 0, "L8 no-log dışı retention → validate eler")
    s = json.loads(json.dumps(spec)); s["spi"]["required_features"] = ["streaming"]
    case(_validate_obj(s) != 0, "L5 eksik required_features → validate eler")
    s = json.loads(json.dumps(spec)); s["metrics"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "L10 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _raises(fn):
    try:
        fn()
        return False
    except LlmFallbackError:
        return True


def _validate_obj(spec_obj):
    import io
    import contextlib
    tmp = os.path.join(HERE, ".._tmp_spec.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(spec_obj, f)
    global SPEC_PATH
    orig = SPEC_PATH
    SPEC_PATH = tmp
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = validate()
    finally:
        SPEC_PATH = orig
        os.remove(tmp)
    return rc


def schema():
    print("""llm-fallback-spec.json beklenen şekli (WBS 4.3.3):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,brd,srs,rtm,poc,vendor_eval,consumes,observability}
  placement{behind_spi=true, orchestrator_depends_on_spi_only=true, turn_state=THINK,
            stream_first=true, event_driven=true, non_blocking=true,
            circuit_breaker_owned_by, routing_owned_by, deterministic_flow_owned_by}            (L1,L9)
  spi{wraps_methods[complete,...], llm_request_fields[messages,tools,...], chunk_types[ToolCallChunk],
      required_features[streaming,tool_call], presents_single_logical_complete=true}             (L3,L5)
  gates{switch_overhead_p95_ms=500, max_turn_lost=0, max_missing_context=0,
        max_system_prompt_mutation=0, max_double_speak=0, max_duplicate_response=0,
        max_concurrent_active=1, max_double_tool_exec=0, max_dropped_call=0,
        max_improper_failover=0, max_flap=0, max_cross_tenant=0, min_providers=2,
        require_deterministic_flow=true, require_error_normalized=true, require_metering=true,
        require_model_version_recorded=true,
        failover_error_classes[TIMEOUT,RATE_LIMITED,UNAVAILABLE,QUOTA_EXCEEDED]}                  (L1-L8)
  fallback{chain[primary_llm,fallback_llm,deterministic_flow], min_providers=2,
           context_resubmission=true, mid_stream_safe_degrade=true, tool_idempotency=true,
           hysteresis_sticky_fallback=true, deterministic_flow_on_total_failure=true,
           switching_owned_by=4.3.3}                                                            (L1-L6)
  metrics{emitted[llm_fallback_total,llm_switch_overhead_ms,llm_deterministic_flow_total,
          llm_turn_total,llm_double_speak_total,llm_double_tool_exec_total], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6, failover_classes[...], non_failover_classes[...CONTENT_FILTERED]} (L7,L10)
  residency{region_pin_required=true, no_train_required=true, no_log_required=true,
            allowed_retention[NONE,EPHEMERAL], context_buffer_ephemeral=true}                    (L8,L10)
  pii{raw_prompt_in_spec_forbidden, raw_output_in_spec_forbidden, pii_value_in_spec_forbidden}   (L10)
  invariants[≥10]{id, desc, trace}

config/llm-fallback-profiles.json: providers[]{provider_id, languages, features(⊇streaming,tool_call),
  tiers, regions, data_retention(NONE/EPHEMERAL), no_train(true), setup_ms, teardown_ms, first_token_ms};
  profiles[]{name, primary_provider, secondary_provider, region, deterministic_flow_id}

simulate sample: {name, profile | primary+secondary | primary_obj+secondary_obj, tenant_id?, expect,
  expected?{metrik:değer}, policy?{failover, context_resubmission, preserve_system_prompt, mid_stream_safe,
  tool_idempotency, deterministic_flow, selective_trigger, single_active, hysteresis, dedup, meter,
  record_model_version, normalize_errors, tenant_isolation},
  events[{kind:'start', t} | {kind:'turn_start', t, turn_id, tier?, critical?} |
         {kind:'first_token', t, turn_id} | {kind:'tool_exec', t, turn_id, tool_id, side_effecting?} |
         {kind:'turn_complete', t, turn_id} |
         {kind:'provider_error', t, raw_error, turn_id?} | {kind:'end', t, reason}]}
  — start → (turn_start → (first_token|tool_exec|provider_error)* → turn_complete)* → end

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: llm_fallback_probe.py simulate <sample.json>")
            return 2
        return simulate_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|simulate|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
