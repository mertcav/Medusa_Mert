#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
conversation_models_probe.py — WBS 3.2.4 Single-prompt + node/flow konuşma modelleri çalıştırma

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/prompt-manager/` (3.2.3) + `runtime/session-memory/` (3.2.1) disipliniyle aynı; burada
deterministik bir KONUŞMA MODELİ KOŞUCUSU (SAD §6.2 Conversation Model Runner) simülatörü
(olay-tetikli, sanal saat, random YOK; gerçek LLM çağrısı YOK — model koşma + graf gezinti MODELİ).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) oturum aktöründe çalışan Conversation Model Runner:
  • Versiyon:   model+flow çağrı başında YAYIMLANMIŞ versiyona sabitlenir + drift yok + kaydedilir (A1).
  • Uçtan uca:  HER İKİ model (single_prompt + node_flow) terminal/handoff'a ulaşır (A2 — FR-AGT-003'ün kalbi).
  • Graf:       tek start, kenarlar çözülür, terminal ulaşılır (A3).
  • Tanımlı:    node_flow yalnız tanımlı kenarlar boyunca ilerler — serbest atlama yok (A4 — SAD §11.3).
  • Fallback:   eşleşme yoksa default/handoff (deterministik; A5 — FR-RTC-011).
  • Sınırlı:    adım-bütçeli, sonsuz döngü yok (A6 — NFR 10.2).
  • Determinist: olay-tetikli, sanal saat, random yok (A7).
  • Single:     single_prompt'ta graf gezintisi yok (A8 — 3.2.3 prompt yönetir).
  • İzolasyon:  {tenant,agent} izole (A9 — RLS 1.1.x).

KAPSAM AYRIMI: system prompt enjeksiyonu/değişmezliği → 3.2.3 (tüketilir); injection semantik tespiti →
3.3.1; çıktı politika → 3.3.2; flow editörü/versiyon oluşturma → A-05/API; flow depolama/WORM → DB 1.1.x;
LLM routing → SAD §9; araç yürütme → Tool Executor §11; işlem workflow motoru → SAD §11.3.

Komutlar:
  validate              conversation-models-spec.json'ı invariant'lara (A1–A10) + config profillerine doğrular.
  simulate <sample>     Deterministik Conversation Model Runner — olay-akışı (pin + turn + end) → versiyon
                        sabitleme + uçtan uca yürütme + graf gezinti + HARD kapılar (A1–A9); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek LLM/registry yerine deterministik model koşma + graf gezinti
modelidir (canlı sistemde Go/Rust runtime + gerçek flow registry, ADR-003/SAD §6.3/DB 1.1.x).
Ham prompt/transkript METNİ/PII DEĞERİ YOK — yalnız düğüm kimlikleri/tipleri + kenar koşul ETİKETLERİ
(intent adı) + mod + adım SAYILARI + versiyon kimlikleri + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "conversation-models-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "conversation-models-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

MODES = {"single_prompt", "node_flow"}
NODE_TYPES = {"start", "say", "collect", "decision", "tool", "handoff", "end"}
TERMINAL_TYPES = {"handoff", "end"}
AWAIT_INPUT_TYPES = {"collect"}
AUTO_ADVANCE_TYPES = {"start", "say", "decision", "tool"}
END_STATES = {"normal", "transfer", "error", "abandon"}
# normal bitişte node_flow terminal'e ulaşmalı; transfer/error/abandon erken bitiş meşru (A2 saymaz)
TERMINATION_REQUIRED_REASONS = {"normal"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class RunnerError(Exception):
    """Geçersiz/desteklenmeyen olay/graf — sessizce kabul yok, reddet (A10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Conversation Model Runner — single_prompt + node_flow yürütme (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class ConversationModelRunner:
    """SAD §6.2 Conversation Model Runner. Olay-akışını işler: pin + turn + end. Çağrı başında bir
    YAYIMLANMIŞ konuşma modeli/flow versiyonunu sabitler; node_flow ise grafı doğrular ve current_node'u
    start'a kurar; her turn'de YALNIZ tanımlı kenarlar boyunca ilerler (serbest atlama yok), eşleşme
    yoksa default/handoff alır; single_prompt ise graf gezintisi yapmaz. Olay-tetikli; sanal saat
    (event.t) — random YOK.

    Olaylar:
      {kind:'pin', flow_version_id, version_no, published, mode, graph?, t, tenant_id?, agent_id?}
      {kind:'turn', t, intent?, jump_to?, tenant_id?}     # jump_to = (degrade) serbest-LLM atlama hedefi
      {kind:'end', t, reason∈end_states}
    """

    def __init__(self, params, policy):
        self.step_budget = int(params.get("step_budget", 40))
        self.tenant_id = params.get("tenant_id", "t-self")
        self.agent_id = params.get("agent_id", "a-self")
        self.pol = policy

        # pin durumu
        self.pinned = None              # {flow_version_id, version_no, published, mode}
        self.mode = None
        self.version_recorded = False
        self._last_t = None

        # graf (node_flow)
        self.nodes = {}                 # id -> type
        self.edges = []                 # [{from,to,on,default}]
        self.start_node = None
        self.current = None
        self.path = []                  # ziyaret yolu (deterministik kanıt)
        self.node_visits = {}

        # sayaçlar / metrikler
        self.runs = 0                   # koşan model sayısı (>=1 pin sonrası)
        self.turns = 0
        self.steps = 0
        self.mode_drift = 0             # çağrı içi farklı versiyona/moda repin (bug)
        self.non_terminated = 0         # normal bitişte terminal'e ulaşılmadı (A2 ihlali)
        self.invalid_graph = 0          # geçersiz graf yapısı (A3)
        self.illegal_transition = 0     # tanımsız kenar boyunca geçiş (A4 ihlali)
        self.stuck_without_fallback = 0 # eşleşme yok + default/handoff yok (A5 ihlali)
        self.over_step_budget = 0       # adım bütçesi aşıldı (A6 ihlali)
        self.out_of_order = 0           # zaman geriye (A7)
        self.graph_nav_in_single_prompt = 0  # single_prompt'ta graf gezintisi (A8 ihlali)
        self.cross_tenant = 0           # yabancı tenant (A9)
        self.unpublished_injected = 0   # yayımlanmamış versiyon enjekte
        self.fallback_total = 0         # default/fallback kenar alımı
        self.handoff_total = 0          # deterministik handoff
        self.terminated = False
        self.terminal_node = None
        self.ended = False
        self.end_reason = None

    # ── tenant/agent + sıra ortak kontrol ─────────────────────────────────────
    def _check_scope(self, ev):
        tt = ev.get("tenant_id", self.tenant_id)
        at = ev.get("agent_id", self.agent_id)
        if tt != self.tenant_id or at != self.agent_id:
            self.cross_tenant += 1
            if self.pol.get("tenant_isolation", True):
                raise RunnerError("cross-tenant/agent erişim reddedildi → AUTH")

    def _check_time(self, t):
        if not isinstance(t, (int, float)):
            raise RunnerError("zaman damgası sayısal değil → INVALID_REQUEST")
        if self._last_t is not None and t < self._last_t:
            self.out_of_order += 1
            if self.pol.get("order_guard", True):
                raise RunnerError("out-of-order olay (t geriye) reddedildi → INVALID_REQUEST")
        self._last_t = max(self._last_t if self._last_t is not None else t, t)

    # ── graf ayrıştırma + doğrulama (A3) ──────────────────────────────────────
    def _parse_graph(self, graph):
        if not isinstance(graph, dict):
            raise RunnerError("graf sözlük değil → INVALID_REQUEST")
        raw_nodes = graph.get("nodes")
        raw_edges = graph.get("edges", [])
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise RunnerError("graf.nodes boş/geçersiz → INVALID_REQUEST")
        if not isinstance(raw_edges, list):
            raise RunnerError("graf.edges liste değil → INVALID_REQUEST")
        nodes = {}
        for n in raw_nodes:
            if not isinstance(n, dict) or "id" not in n or "type" not in n:
                raise RunnerError("graf düğümü {id,type} taşımalı → INVALID_REQUEST")
            if n["type"] not in NODE_TYPES:
                raise RunnerError("geçersiz düğüm tipi: %r → INVALID_REQUEST" % n["type"])
            if n["id"] in nodes:
                raise RunnerError("yinelenen düğüm id: %r → INVALID_REQUEST" % n["id"])
            nodes[n["id"]] = n["type"]
        edges = []
        for e in raw_edges:
            if not isinstance(e, dict) or "from" not in e or "to" not in e:
                raise RunnerError("graf kenarı {from,to} taşımalı → INVALID_REQUEST")
            edges.append({"from": e["from"], "to": e["to"],
                          "on": e.get("on"), "default": bool(e.get("default", False))})
        self.nodes = nodes
        self.edges = edges
        self.start_node = graph.get("start")

        # ── A3 yapısal doğrulama → invalid_graph sayacı
        problems = 0
        starts = [nid for nid, ty in nodes.items() if ty == "start"]
        if len(starts) != 1:
            problems += 1  # tek start gerekli
        if self.start_node not in nodes or nodes.get(self.start_node) != "start":
            problems += 1  # graph.start geçerli bir start düğümü değil
        for e in edges:
            if e["from"] not in nodes or e["to"] not in nodes:
                problems += 1  # tanımsız düğüm referansı
        if not self._terminal_reachable():
            problems += 1  # start'tan terminal ulaşılamıyor (A2 ile bağlı)
        if problems:
            self.invalid_graph += problems
            if self.pol.get("strict_graph", True):
                raise RunnerError("geçersiz graf (%d sorun) reddedildi → INVALID_REQUEST" % problems)

    def _terminal_reachable(self):
        if self.start_node not in self.nodes:
            return False
        seen = set()
        stack = [self.start_node]
        adj = {}
        for e in self.edges:
            adj.setdefault(e["from"], []).append(e["to"])
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            if self.nodes.get(cur) in TERMINAL_TYPES:
                return True
            for nxt in adj.get(cur, []):
                if nxt in self.nodes and nxt not in seen:
                    stack.append(nxt)
        return False

    def _edges_from(self, node):
        return [e for e in self.edges if e["from"] == node]

    # ── pin: model+versiyon sabitleme (A1) ────────────────────────────────────
    def pin(self, ev):
        if self.ended:
            raise RunnerError("bitmiş oturuma pin yapılamaz → INVALID_REQUEST")
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        vid = ev.get("flow_version_id")
        vno = ev.get("version_no")
        mode = ev.get("mode")
        if not isinstance(vid, str) or not vid:
            raise RunnerError("flow_version_id yok/boş → INVALID_REQUEST")
        if not isinstance(vno, int) or vno <= 0:
            raise RunnerError("version_no pozitif int değil → INVALID_REQUEST")
        if mode not in MODES:
            raise RunnerError("geçersiz mode: %r → INVALID_REQUEST" % mode)
        published = ev.get("published", True)
        if not isinstance(published, bool):
            raise RunnerError("published bool değil → INVALID_REQUEST")

        # yayımlanmamış versiyon (A1/A10): yayım zorunluysa reddet (fail-closed), değilse enjekte → bug
        if not published:
            if self.pol.get("published_only", True):
                raise RunnerError("yayımlanmamış flow versiyonu reddedildi (fail-closed) → INVALID_REQUEST")
            self.unpublished_injected += 1

        if self.pinned is not None:
            same = (self.pinned["flow_version_id"] == vid and self.pinned["mode"] == mode)
            if same:
                return  # idempotent re-pin (aynı versiyon+mod)
            if self.pol.get("stable_version", True):
                raise RunnerError("çağrı içi versiyon/mod repin reddedildi (drift yok) → INVALID_REQUEST")
            self.mode_drift += 1
            # drift: yeni versiyona geç (degrade)

        self.pinned = {"flow_version_id": vid, "version_no": vno, "published": published, "mode": mode}
        self.mode = mode
        self.runs += 1
        if self.pol.get("record_version", True):
            self.version_recorded = True

        graph = ev.get("graph")
        if mode == "node_flow":
            if graph is None:
                raise RunnerError("node_flow modu graf gerektirir → INVALID_REQUEST")
            self._parse_graph(graph)
            self.current = self.start_node
            self.path = [self.current]
            self.node_visits[self.current] = 1
            self._auto_advance()
        else:
            # single_prompt: graf TAŞINMAMALI; taşıyorsa (degrade) graf gezintisi sayılır (A8)
            if graph is not None:
                self.graph_nav_in_single_prompt += 1
                if self.pol.get("single_prompt_no_graph", True):
                    raise RunnerError("single_prompt modunda graf taşınamaz → INVALID_REQUEST")

    # ── auto-advance: say/start/decision/tool düğümleri otomatik ilerler ───────
    def _auto_advance(self):
        guard = 0
        while True:
            ty = self.nodes.get(self.current)
            if ty in TERMINAL_TYPES:
                self.terminated = True
                self.terminal_node = self.current
                if ty == "handoff":
                    self.handoff_total += 1
                break
            if ty in AWAIT_INPUT_TYPES:
                break  # kullanıcı girdisi bekle
            outs = self._edges_from(self.current)
            autos = [e for e in outs if e.get("on") == "auto"] or [e for e in outs if e["default"]]
            if not autos:
                break  # otomatik kenar yok; bir sonraki turn'ü bekle (say düğümü yapraksa)
            self._transition(autos[0]["to"])
            if self.over_step_budget:
                break
            guard += 1
            if guard > self.step_budget + 5:
                break

    def _transition(self, target):
        if target not in self.nodes:
            self.illegal_transition += 1
            return
        self.current = target
        self.path.append(target)
        self.node_visits[target] = self.node_visits.get(target, 0) + 1
        self.steps += 1
        if self.steps > self.step_budget:
            self.over_step_budget += 1
        ty = self.nodes.get(target)
        if ty in TERMINAL_TYPES:
            self.terminated = True
            self.terminal_node = target
            if ty == "handoff":
                self.handoff_total += 1

    # ── turn: kullanıcı turu → gezinti (A4/A5/A8) ─────────────────────────────
    def turn(self, ev):
        if self.ended:
            raise RunnerError("bitmiş oturuma turn eklenemez → INVALID_REQUEST")
        self._check_time(ev.get("t"))
        self._check_scope(ev)
        if self.pinned is None:
            raise RunnerError("pin'lenmiş konuşma modeli yok → INVALID_REQUEST (fail-closed)")
        self.turns += 1
        intent = ev.get("intent")
        jump_to = ev.get("jump_to")

        if self.mode == "single_prompt":
            # serbest LLM turu — graf gezintisi YOK (A8). jump_to/graf gezintisi denenirse degrade.
            if jump_to is not None:
                self.graph_nav_in_single_prompt += 1
                if self.pol.get("single_prompt_no_graph", True):
                    raise RunnerError("single_prompt modunda graf gezintisi yok → INVALID_REQUEST")
            return

        # ── node_flow gezinti
        if self.over_step_budget and self.pol.get("step_bounded", True):
            return  # bütçe aşıldıysa daha fazla ilerleme yok
        if self.current is None:
            raise RunnerError("node_flow current_node yok → INVALID_REQUEST")

        # (degrade) serbest-LLM atlama hedefi: tanımlı kenar varsa meşru, yoksa illegal
        if jump_to is not None:
            legal = any(e["to"] == jump_to for e in self._edges_from(self.current))
            if legal:
                self._transition(jump_to)
            elif self.pol.get("defined_transitions_only", True):
                raise RunnerError("tanımsız geçiş talebi (serbest atlama) reddedildi → INVALID_REQUEST")
            else:
                self.illegal_transition += 1
                if jump_to in self.nodes:
                    self.current = jump_to
                    self.path.append(jump_to)
                    self.node_visits[jump_to] = self.node_visits.get(jump_to, 0) + 1
                    self.steps += 1
            self._auto_advance()
            return

        outs = self._edges_from(self.current)
        match = None
        for e in outs:
            if e.get("on") is not None and e.get("on") != "auto" and e["on"] == intent:
                match = e
                break
        if match is None:
            default = next((e for e in outs if e["default"]), None)
            if default is not None:
                self.fallback_total += 1
                self._transition(default["to"])
            else:
                # eşleşme yok + default yok → deterministik handoff (A5) ya da takılma
                if self.pol.get("deterministic_fallback", True):
                    self.handoff_total += 1
                    self.terminated = True
                    self.terminal_node = "deterministic_handoff"
                else:
                    self.stuck_without_fallback += 1
        else:
            self._transition(match["to"])
        self._auto_advance()

    def end(self, ev):
        if self.ended:
            raise RunnerError("oturum zaten bitti → INVALID_REQUEST")
        reason = ev.get("reason", "normal")
        if reason not in END_STATES:
            raise RunnerError("geçersiz bitiş nedeni: %r → INVALID_REQUEST" % reason)
        self.ended = True
        self.end_reason = reason
        # single_prompt: konuşma yalnız sabit prompt'la yönetilir; normal bitiş = uçtan uca tamamlanma
        # (graf terminal'i yok — çağrının normal sonlanması terminal kabul edilir).
        if self.mode == "single_prompt" and reason in TERMINATION_REQUIRED_REASONS:
            self.terminated = True
            self.terminal_node = "single_prompt_complete"
        # A2: node_flow normal bitişte terminal/handoff düğümüne ulaşmış olmalı
        if reason in TERMINATION_REQUIRED_REASONS and not self.terminated:
            self.non_terminated += 1

    def metrics(self):
        scenario = []
        if self.pinned is not None:
            scenario.append(self.mode)
        if self.steps > 0:
            scenario.append("flow-steps")
        if self.fallback_total > 0:
            scenario.append("fallback")
        if self.handoff_total > 0:
            scenario.append("handoff")
        if self.illegal_transition > 0:
            scenario.append("illegal-transition")
        if self.invalid_graph > 0:
            scenario.append("invalid-graph")
        if self.non_terminated > 0:
            scenario.append("non-terminated")
        if not scenario:
            scenario.append("empty")
        return {
            "pinned": self.pinned is not None,
            "mode": self.mode,
            "pinned_version_no": (self.pinned or {}).get("version_no"),
            "pinned_version_id": (self.pinned or {}).get("flow_version_id"),
            "published": (self.pinned or {}).get("published"),
            "version_recorded": self.version_recorded,
            "mode_drift": self.mode_drift,
            "runs": self.runs,
            "turns": self.turns,
            "steps": self.steps,
            "step_budget": self.step_budget,
            "nodes_count": len(self.nodes),
            "edges_count": len(self.edges),
            "path": list(self.path),
            "terminated": self.terminated,
            "terminal_node": self.terminal_node,
            "non_terminated": self.non_terminated,
            "invalid_graph": self.invalid_graph,
            "illegal_transition": self.illegal_transition,
            "stuck_without_fallback": self.stuck_without_fallback,
            "over_step_budget": self.over_step_budget,
            "out_of_order": self.out_of_order,
            "graph_nav_in_single_prompt": self.graph_nav_in_single_prompt,
            "cross_tenant": self.cross_tenant,
            "unpublished_injected": self.unpublished_injected,
            "fallback_total": self.fallback_total,
            "handoff_total": self.handoff_total,
            "end_reason": self.end_reason,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, params, policy):
    events = sample.get("events")
    if events is None or not isinstance(events, list) or not events:
        raise RunnerError("boş/geçersiz olay akışı → INVALID_REQUEST")
    p = dict(params)
    p["tenant_id"] = sample.get("tenant_id", params.get("tenant_id", "t-self"))
    p["agent_id"] = sample.get("agent_id", params.get("agent_id", "a-self"))
    r = ConversationModelRunner(p, policy)
    saw_end = False
    for ev in events:
        if not isinstance(ev, dict):
            raise RunnerError("olay sözlük değil → INVALID_REQUEST")
        kind = ev.get("kind")
        if kind == "pin":
            r.pin(ev)
        elif kind == "turn":
            r.turn(ev)
        elif kind == "end":
            r.end(ev)
            saw_end = True
        else:
            raise RunnerError("bilinmeyen olay tipi: %r → INVALID_REQUEST" % kind)
    if not saw_end:
        raise RunnerError("olay akışında 'end' yok → INVALID_REQUEST")
    return r.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (A1–A9) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []

    # ── A1: model+versiyon sabitleme + drift yok + yayımlanmış + kaydedilir
    rec_ok = (not gates.get("require_version_recorded", True)) or (m.get("version_recorded", False) is True)
    F.append((m.get("mode_drift", 0) <= gates.get("max_mode_drift", 0)
              and m.get("pinned", False) is True and rec_ok
              and m.get("unpublished_injected", 0) <= gates.get("max_unpublished_injected", 0),
              "A1 model sabit: pinned=%s mode=%s, mode_drift %d ≤ %d, unpublished %d ≤ %d, recorded=%s (FR-AGT-004)"
              % (m.get("pinned"), m.get("mode"), m.get("mode_drift", 0),
                 gates.get("max_mode_drift", 0), m.get("unpublished_injected", 0),
                 gates.get("max_unpublished_injected", 0), m.get("version_recorded"))))

    # ── A2: her iki model uçtan uca (FR-AGT-003'ün kalbi)
    F.append((m.get("non_terminated", 0) <= gates.get("max_non_terminated", 0),
              "A2 uçtan uca: non_terminated %d ≤ %d (terminated=%s, terminal=%s — SR-AGT-003)"
              % (m.get("non_terminated", 0), gates.get("max_non_terminated", 0),
                 m.get("terminated"), m.get("terminal_node"))))

    # ── A3: graf geçerli
    F.append((m.get("invalid_graph", 0) <= gates.get("max_invalid_graph", 0),
              "A3 graf: invalid_graph %d ≤ %d (tek start + kenarlar çözülür + terminal ulaşılır)"
              % (m.get("invalid_graph", 0), gates.get("max_invalid_graph", 0))))

    # ── A4: tanımlı kenarlar (serbest atlama yok)
    F.append((m.get("illegal_transition", 0) <= gates.get("max_illegal_transition", 0),
              "A4 tanımlı geçiş: illegal_transition %d ≤ %d (serbest-LLM atlaması yok — SAD §11.3)"
              % (m.get("illegal_transition", 0), gates.get("max_illegal_transition", 0))))

    # ── A5: deterministik fallback
    F.append((m.get("stuck_without_fallback", 0) <= gates.get("max_stuck_without_fallback", 0),
              "A5 fallback: stuck_without_fallback %d ≤ %d (default/handoff %d — FR-RTC-011)"
              % (m.get("stuck_without_fallback", 0), gates.get("max_stuck_without_fallback", 0),
                 m.get("fallback_total", 0) + m.get("handoff_total", 0))))

    # ── A6: adım sınırı
    F.append((m.get("over_step_budget", 0) <= gates.get("max_over_step_budget", 0),
              "A6 adım-sınırı: over_step_budget %d ≤ %d (steps %d / budget %d — NFR 10.2)"
              % (m.get("over_step_budget", 0), gates.get("max_over_step_budget", 0),
                 m.get("steps", 0), m.get("step_budget", 0))))

    # ── A7: deterministik (sanal saat)
    F.append((m.get("out_of_order", 0) <= gates.get("max_out_of_order", 0),
              "A7 deterministik: out_of_order %d ≤ %d (olay-tetikli, random yok)"
              % (m.get("out_of_order", 0), gates.get("max_out_of_order", 0))))

    # ── A8: single_prompt graf gezintisi yok
    F.append((m.get("graph_nav_in_single_prompt", 0) <= gates.get("max_graph_nav_in_single_prompt", 0),
              "A8 single_prompt: graph_nav_in_single_prompt %d ≤ %d (sabit prompt yönetir — 3.2.3)"
              % (m.get("graph_nav_in_single_prompt", 0), gates.get("max_graph_nav_in_single_prompt", 0))))

    # ── A9: tenant/agent izolasyon
    F.append((m.get("cross_tenant", 0) <= gates.get("max_cross_tenant", 0),
              "A9 izolasyon: cross_tenant %d ≤ %d ({tenant,agent} — FR-TEN-002/RLS 1.1.x)"
              % (m.get("cross_tenant", 0), gates.get("max_cross_tenant", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise RunnerError("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    ex = dict(spec.get("execution", {}))
    out = {"step_budget": ex.get("step_budget", 40)}
    if "step_budget" in profile:
        out["step_budget"] = profile["step_budget"]
    return out


def _resolve_policy(spec, profile, sample):
    pol = {
        "defined_transitions_only": True,
        "deterministic_fallback": True,
        "step_bounded": True,
        "strict_graph": True,
        "published_only": True,
        "stable_version": True,
        "record_version": True,
        "single_prompt_no_graph": True,
        "tenant_isolation": True,
        "order_guard": True,
    }
    pol.update(sample.get("policy", {}))
    return pol


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")

    if "profile_obj" in sample:
        profile = sample["profile_obj"]
    else:
        cfg = _load(PROFILES_CFG)
        try:
            profile = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
        except RunnerError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    params = _params_from(spec, profile)
    policy = _resolve_policy(spec, profile, sample)
    gates = spec.get("gates", {})

    try:
        m = simulate(sample, params, policy)
    except RunnerError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | mod=%s v%s (%s) recorded=%s | %d turn → %d adım | "
          "%d düğüm/%d kenar | terminal=%s"
          % (name, "+".join(m["scenario"]), m["mode"], m["pinned_version_no"], m["pinned_version_id"],
             m["version_recorded"], m["turns"], m["steps"], m["nodes_count"], m["edges_count"],
             m["terminal_node"]))
    print("  non_terminated=%d | invalid_graph=%d | illegal_transition=%d | stuck=%d | over_step=%d | "
          "single_prompt_nav=%d | drift=%d | cross_tenant=%d | fallback=%d | handoff=%d"
          % (m["non_terminated"], m["invalid_graph"], m["illegal_transition"],
             m["stuck_without_fallback"], m["over_step_budget"], m["graph_nav_in_single_prompt"],
             m["mode_drift"], m["cross_tenant"], m["fallback_total"], m["handoff_total"]))
    if m["path"]:
        print("  yol: %s" % " → ".join(m["path"]))
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


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "3.2.4", "spec.wbs == 3.2.4")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (orchestrator oturum aktörü, session_start pin)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True and pl.get("in_session_actor") is True,
           "Conversation Model Runner orchestrator oturum aktöründe (SAD §6.2/§6.3)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "olay-tetikli + bloklamaz")
    _check(R, pl.get("pin_scope") == "session_start",
           "A1 model/versiyon çağrı/oturum başında sabitlenir (drift yok)")
    _check(R, pl.get("consumes_prompt_from"), "A10 prompt 3.2.3'ten tüketilir")

    # ── model_types (A2/A8)
    mt = spec.get("model_types", {})
    _check(R, set(mt.get("modes", [])) == MODES,
           "A2 modlar {single_prompt, node_flow} (FR-AGT-003)")
    _check(R, set(mt.get("node_types", [])) == NODE_TYPES,
           "düğüm tipleri {start,say,collect,decision,tool,handoff,end}")
    _check(R, set(mt.get("terminal_types", [])) == TERMINAL_TYPES,
           "terminal tipler {handoff, end}")

    # ── versioning (A1)
    vs = spec.get("versioning", {})
    _check(R, vs.get("pin_required") is True, "A1 pin zorunlu")
    _check(R, vs.get("stable_within_call") is True and vs.get("no_mid_call_drift") is True,
           "A1 çağrı içi model/versiyon sabit (drift yok)")
    _check(R, vs.get("version_recorded") is True, "A1 kullanılan versiyon kaydedilir (FR-AGT-004)")

    # ── graph_validity (A3)
    gv = spec.get("graph_validity", {})
    _check(R, gv.get("single_start") is True and gv.get("edges_resolve") is True,
           "A3 tek start + kenarlar çözülür")
    _check(R, gv.get("terminal_reachable") is True,
           "A3 start'tan terminal ulaşılır (A2 ile bağlı)")
    _check(R, gv.get("reject_invalid_when_strict") is True,
           "A3 strict modda geçersiz graf reddedilir (fail-closed)")

    # ── execution (A4/A5/A6/A7)
    ex = spec.get("execution", {})
    _check(R, ex.get("defined_transitions_only") is True,
           "A4 yalnız tanımlı kenarlar (serbest atlama yok)")
    _check(R, ex.get("deterministic_fallback") is True,
           "A5 deterministik fallback (default/handoff)")
    _check(R, ex.get("step_bounded") is True, "A6 adım-sınırlı")
    _check(R, ex.get("deterministic") is True, "A7 deterministik yürütme (random yok)")
    _check(R, isinstance(ex.get("step_budget"), int) and ex["step_budget"] > 0,
           "step_budget > 0")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("step_budget") == ex.get("step_budget"),
           "gates step_budget execution ile tutarlı")
    _check(R, g.get("require_published") is True, "A1 require_published=true")
    _check(R, g.get("require_version_recorded") is True, "A1 require_version_recorded=true")
    _check(R, g.get("max_mode_drift", -1) == 0, "A1 max_mode_drift = 0")
    _check(R, g.get("max_non_terminated", -1) == 0, "A2 max_non_terminated = 0")
    _check(R, g.get("max_invalid_graph", -1) == 0, "A3 max_invalid_graph = 0")
    _check(R, g.get("max_illegal_transition", -1) == 0, "A4 max_illegal_transition = 0")
    _check(R, g.get("max_stuck_without_fallback", -1) == 0, "A5 max_stuck_without_fallback = 0")
    _check(R, g.get("max_over_step_budget", -1) == 0, "A6 max_over_step_budget = 0")
    _check(R, g.get("max_out_of_order", -1) == 0, "A7 max_out_of_order = 0")
    _check(R, g.get("max_graph_nav_in_single_prompt", -1) == 0, "A8 max_graph_nav_in_single_prompt = 0")
    _check(R, g.get("max_cross_tenant", -1) == 0, "A9 max_cross_tenant = 0")
    _check(R, g.get("max_unpublished_injected", -1) == 0, "A1 max_unpublished_injected = 0")

    # ── metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"conversation_model_runs_total", "flow_step_total",
               "flow_illegal_transition_total"} <= emitted,
           "metrikler: runs + step + illegal_transition yayılır")
    _check(R, len(me.get("maps_to_observability", {})) >= 1,
           "metrik observability'ye eşlenir (0.4.7)")

    # ── error taxonomy (A10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "A10 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "A10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_flow_or_event") == "INVALID_REQUEST"
           and mapping.get("unpublished_version") == "INVALID_REQUEST"
           and mapping.get("undefined_transition") == "INVALID_REQUEST"
           and mapping.get("registry_unavailable") == "UNAVAILABLE"
           and mapping.get("cross_tenant_access") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "A10 bozuk/yayımsız/tanımsız-geçiş→INVALID, registry-down→UNAVAILABLE, cross-tenant→AUTH, bölge→REGION_VIOLATION")

    # ── residency + pii (A9/A10)
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "A10 residency region pin")
    _check(R, spec.get("residency", {}).get("version_recorded_home_region") is True,
           "A1 versiyon home-region'da kaydedilir (FR-AGT-004/NFR 10.7)")
    _check(R, spec.get("pii", {}).get("raw_text_in_spec_forbidden") is True,
           "A10 ham metin spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_value_in_spec_forbidden") is True,
           "A10 PII değeri spec'te yasak")

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
    _check(R, not hits, "A10 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 profil")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "A10 config %s bölge pini var" % p.get("name"))
            _check(R, p.get("step_budget", 0) > 0,
                   "config %s step_budget > 0" % p.get("name"))

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
DEFAULT_PARAMS = {"step_budget": 40, "tenant_id": "t-self", "agent_id": "a-self"}

# Basit ama geçerli node_flow grafiği: start→collect→(verildi→end / belirsiz→help→collect / default→help)
FLOW_GRAPH = {
    "start": "n_start",
    "nodes": [
        {"id": "n_start", "type": "start"},
        {"id": "n_ask", "type": "collect"},
        {"id": "n_help", "type": "say"},
        {"id": "n_done", "type": "end"},
        {"id": "n_human", "type": "handoff"},
    ],
    "edges": [
        {"from": "n_start", "to": "n_ask", "on": "auto"},
        {"from": "n_ask", "to": "n_done", "on": "provided"},
        {"from": "n_ask", "to": "n_human", "on": "agent"},
        {"from": "n_ask", "to": "n_help", "on": "unclear", "default": True},
        {"from": "n_help", "to": "n_ask", "on": "auto"},
    ],
}


def _pin_flow(t=0, vid="cf-1", vno=1, published=True, graph=None, tenant=None, agent=None):
    ev = {"kind": "pin", "flow_version_id": vid, "version_no": vno, "published": published,
          "mode": "node_flow", "graph": graph if graph is not None else json.loads(json.dumps(FLOW_GRAPH)),
          "t": t}
    if tenant:
        ev["tenant_id"] = tenant
    if agent:
        ev["agent_id"] = agent
    return ev


def _pin_single(t=0, vid="cf-sp-1", vno=1, published=True, graph=None, tenant=None):
    ev = {"kind": "pin", "flow_version_id": vid, "version_no": vno, "published": published,
          "mode": "single_prompt", "t": t}
    if graph is not None:
        ev["graph"] = graph
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _turn(t, intent=None, jump_to=None, tenant=None):
    ev = {"kind": "turn", "t": t}
    if intent is not None:
        ev["intent"] = intent
    if jump_to is not None:
        ev["jump_to"] = jump_to
    if tenant:
        ev["tenant_id"] = tenant
    return ev


def _end(t, reason="normal"):
    return {"kind": "end", "t": t, "reason": reason}


def _run(events, params=None, **pol_over):
    pol = {"defined_transitions_only": True, "deterministic_fallback": True, "step_bounded": True,
           "strict_graph": True, "published_only": True, "stable_version": True,
           "record_version": True, "single_prompt_no_graph": True, "tenant_isolation": True,
           "order_guard": True}
    pol.update(pol_over)
    return simulate({"events": events}, params or DEFAULT_PARAMS, pol)


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── node_flow happy: start→ask→done (A1–A9) ──────────────────────────────────
    mh = _run([_pin_flow(0), _turn(100, "provided"), _end(200)])
    case(mh["pinned"] and mh["mode"] == "node_flow" and mh["version_recorded"], "node_flow: model sabit + kayıtlı (A1)")
    case(mh["terminated"] and mh["terminal_node"] == "n_done" and mh["non_terminated"] == 0,
         "node_flow: uçtan uca terminal'e ulaştı (A2)")
    case(mh["illegal_transition"] == 0 and mh["path"] == ["n_start", "n_ask", "n_done"],
         "node_flow: yalnız tanımlı kenarlar, doğru yol (A4)")
    case(all(ok for ok, _ in evaluate(gates, mh)), "node_flow happy tüm kapıları geçer")

    # ── single_prompt happy: graf gezintisi yok (A2/A8) ──────────────────────────
    ms = _run([_pin_single(0), _turn(100), _turn(200), _end(300)])
    case(ms["mode"] == "single_prompt" and ms["terminated"] and ms["non_terminated"] == 0,
         "single_prompt: uçtan uca yürür (A2 — FR-AGT-003)")
    case(ms["graph_nav_in_single_prompt"] == 0 and ms["steps"] == 0,
         "single_prompt: graf gezintisi YOK (A8)")
    case(all(ok for ok, _ in evaluate(gates, ms)), "single_prompt happy tüm kapıları geçer")

    # ── fallback: belirsiz intent → default kenar (A5) ───────────────────────────
    mf = _run([_pin_flow(0), _turn(100, "unclear"), _turn(200, "provided"), _end(300)])
    case(mf["fallback_total"] >= 1 and mf["stuck_without_fallback"] == 0,
         "fallback: belirsiz→default kenar (A5)")
    case(mf["terminated"] and all(ok for ok, _ in evaluate(gates, mf)), "fallback tüm kapıları geçer")

    # ── handoff: 'agent' intent → handoff terminal ───────────────────────────────
    mhd = _run([_pin_flow(0), _turn(100, "agent"), _end(200)])
    case(mhd["handoff_total"] >= 1 and mhd["terminal_node"] == "n_human" and mhd["terminated"],
         "handoff: insana aktar terminal'i (A2)")
    case(all(ok for ok, _ in evaluate(gates, mhd)), "handoff tüm kapıları geçer")

    # ── determinizm ───────────────────────────────────────────────────────────────
    case(_run([_pin_flow(0), _turn(100, "unclear"), _turn(200, "provided"), _end(300)]) == mf,
         "determinizm: aynı olay-akışı birebir aynı metrik+yol (random yok)")

    # ── legal jump_to: tanımlı kenar boyunca atlama meşru (A4) ───────────────────
    mj = _run([_pin_flow(0), _turn(100, jump_to="n_done"), _end(200)])
    case(mj["illegal_transition"] == 0 and mj["terminal_node"] == "n_done",
         "legal-jump: tanımlı kenar (n_ask→n_done) boyunca atlama meşru")

    # ── degraded-1: defined_transitions_only kapalı → serbest atlama (A4 eler) ────
    d1 = _run([_pin_flow(0), _turn(100, jump_to="n_help"), _turn(200, "provided"), _end(300)],
              defined_transitions_only=False)
    case(d1["illegal_transition"] >= 1, "degraded(free-jump): tanımsız düğüme serbest-LLM atlaması")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(free-jump) A4 eler")

    # ── degraded-2: deterministic_fallback kapalı + no-match → takılma (A5 eler) ──
    nodef_graph = json.loads(json.dumps(FLOW_GRAPH))
    nodef_graph["edges"] = [e for e in nodef_graph["edges"] if not e.get("default")]
    d2 = _run([_pin_flow(0, graph=nodef_graph), _turn(100, "weird"), _end(200, reason="error")],
              deterministic_fallback=False)
    case(d2["stuck_without_fallback"] >= 1, "degraded(stuck): eşleşme yok + default yok + fallback kapalı")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(stuck) A5 eler")

    # ── degraded-3: geçersiz graf (tanımsız düğüm referansı) → A3 eler ───────────
    bad_graph = json.loads(json.dumps(FLOW_GRAPH))
    bad_graph["edges"].append({"from": "n_ask", "to": "n_ghost", "on": "x"})
    d3 = _run([_pin_flow(0, graph=bad_graph), _turn(100, "provided"), _end(200)], strict_graph=False)
    case(d3["invalid_graph"] >= 1, "degraded(bad-graph): tanımsız düğüm referansı (n_ghost)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(bad-graph) A3 eler")

    # ── degraded-4: normal bitişte terminal'e ulaşılmadı → A2 eler ───────────────
    d4 = _run([_pin_flow(0), _turn(100, "unclear"), _end(200, reason="normal")])
    case(d4["non_terminated"] >= 1 and not d4["terminated"],
         "degraded(non-terminated): normal bitiş ama flow ortada (A2 ihlali)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(non-terminated) A2 eler")

    # ── degraded-5: adım bütçesi aşımı (sonsuz döngü) → A6 eler ──────────────────
    loop_graph = {
        "start": "n_s",
        "nodes": [{"id": "n_s", "type": "start"}, {"id": "n_a", "type": "say"},
                  {"id": "n_b", "type": "say"}, {"id": "n_e", "type": "end"}],
        "edges": [{"from": "n_s", "to": "n_a", "on": "auto"},
                  {"from": "n_a", "to": "n_b", "on": "auto"},
                  {"from": "n_b", "to": "n_a", "on": "auto"},  # n_a↔n_b sonsuz döngü; n_e ulaşılır değil
                  {"from": "n_s", "to": "n_e", "on": "x"}],
    }
    d5 = _run([_pin_flow(0, graph=loop_graph), _end(100, reason="error")],
              step_bounded=False, strict_graph=False, deterministic_fallback=False)
    case(d5["over_step_budget"] >= 1, "degraded(loop): adım bütçesi aşıldı (ilerlemesiz döngü)")
    case(not all(ok for ok, _ in evaluate(gates, d5)), "degraded(loop) A6 eler")

    # ── degraded-6: single_prompt'ta graf gezintisi → A8 eler ────────────────────
    d6 = _run([_pin_single(0), _turn(100, jump_to="n_x"), _end(200)], single_prompt_no_graph=False)
    case(d6["graph_nav_in_single_prompt"] >= 1, "degraded(sp-nav): single_prompt'ta graf gezintisi denendi")
    case(not all(ok for ok, _ in evaluate(gates, d6)), "degraded(sp-nav) A8 eler")

    # ── degraded-7: çağrı-içi versiyon drift → A1 eler ───────────────────────────
    d7 = _run([_pin_flow(0, vid="cf-1"), _turn(100, "provided"),
               _pin_flow(200, vid="cf-2", vno=2), _end(300)], stable_version=False)
    case(d7["mode_drift"] >= 1, "degraded(drift): çağrı içi farklı versiyona repin")
    case(not all(ok for ok, _ in evaluate(gates, d7)), "degraded(drift) A1 eler")

    # ── degraded-8: yayımlanmamış versiyon enjekte → A1 eler ─────────────────────
    d8 = _run([_pin_single(0, published=False), _turn(100), _end(200)], published_only=False)
    case(d8["unpublished_injected"] >= 1, "degraded(unpublished): yayımlanmamış flow enjekte edildi")
    case(not all(ok for ok, _ in evaluate(gates, d8)), "degraded(unpublished) A1 eler")

    # ── degraded-9: cross-tenant flow → A9 eler ──────────────────────────────────
    d9 = _run([_pin_flow(0), _turn(100, "provided", tenant="t-other"), _end(200)],
              tenant_isolation=False)
    case(d9["cross_tenant"] >= 1, "degraded(cross-tenant): yabancı tenant turn sızdı")
    case(not all(ok for ok, _ in evaluate(gates, d9)), "degraded(cross-tenant) A9 eler")

    # ── geçersiz olay reddi (A10) ─────────────────────────────────────────────────
    case(_raises(lambda: _run([_pin_flow(0), {"kind": "turn", "t": 100, "intent": "x"},
                               {"kind": "pin", "flow_version_id": "z", "version_no": 1,
                                "published": True, "mode": "bad", "t": 150}, _end(200)])),
         "A10 geçersiz mode → reddedilir")
    case(_raises(lambda: _run([{"kind": "pin", "flow_version_id": "z", "version_no": 1,
                                "published": True, "mode": "node_flow", "t": 0}, _end(100)])),
         "A10 node_flow grafsız → reddedilir")
    case(_raises(lambda: _run([_turn(0, "x"), _end(100)])),
         "A10 pin'siz turn → reddedilir (fail-closed)")
    case(_raises(lambda: _run([_pin_single(0, published=False), _turn(100), _end(200)])),
         "A10 yayımlanmamış versiyon (published_only) → reddedilir")
    case(_raises(lambda: _run([_pin_flow(0), _pin_flow(100, vid="cf-2", vno=2), _end(200)])),
         "A10 çağrı-içi repin (stable_version) → reddedilir")
    case(_raises(lambda: _run([_pin_flow(0), _turn(100, jump_to="n_help"), _end(200)])),
         "A10 tanımsız geçiş (defined_transitions_only) → reddedilir")
    case(_raises(lambda: _run([_pin_flow(0), _turn(100, "provided")])),
         "A10 'end' olmadan → reddedilir")
    case(_raises(lambda: _run([_pin_flow(1000), _turn(0, "provided"), _end(2000)])),
         "A10 out-of-order → reddedilir")
    case(_raises(lambda: _run([_pin_flow(0), {"kind": "nope", "t": 1}, _end(2000)])),
         "A10 bilinmeyen olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, DEFAULT_PARAMS, {})), "A10 boş olay akışı → reddedilir")
    case(_raises(lambda: _run([_pin_flow(0), _turn(100, "provided", tenant="t-other"), _end(200)])),
         "A10 cross-tenant (izolasyon açık) → reddedilir")
    case(_raises(lambda: _run([_pin_single(0, graph={"nodes": [{"id": "x", "type": "start"}]})])),
         "A10 single_prompt + graf (single_prompt_no_graph) → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["execution"]["step_budget"] = 0
    case(_validate_obj(s) != 0, "step_budget=0 → validate eler")
    s = json.loads(json.dumps(spec)); s["execution"]["defined_transitions_only"] = False
    case(_validate_obj(s) != 0, "A4 defined_transitions_only=false → validate eler")
    s = json.loads(json.dumps(spec)); s["execution"]["deterministic_fallback"] = False
    case(_validate_obj(s) != 0, "A5 deterministic_fallback=false → validate eler")
    s = json.loads(json.dumps(spec)); s["execution"]["step_bounded"] = False
    case(_validate_obj(s) != 0, "A6 step_bounded=false → validate eler")
    s = json.loads(json.dumps(spec)); s["graph_validity"]["terminal_reachable"] = False
    case(_validate_obj(s) != 0, "A3 terminal_reachable=false → validate eler")
    s = json.loads(json.dumps(spec)); s["versioning"]["version_recorded"] = False
    case(_validate_obj(s) != 0, "A1 version_recorded=false → validate eler")
    s = json.loads(json.dumps(spec)); s["model_types"]["modes"] = ["single_prompt"]
    case(_validate_obj(s) != 0, "A2 modlar eksik (node_flow yok) → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_non_terminated"] = 1
    case(_validate_obj(s) != 0, "A2 max_non_terminated>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_illegal_transition"] = 1
    case(_validate_obj(s) != 0, "A4 max_illegal_transition>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_over_step_budget"] = 1
    case(_validate_obj(s) != 0, "A6 max_over_step_budget>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant"] = 1
    case(_validate_obj(s) != 0, "A9 max_cross_tenant>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["require_published"] = False
    case(_validate_obj(s) != 0, "A1 require_published=false → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "A10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_value_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "A10 pii-değer-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["execution"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "A10 literal secret → validate eler")

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
    except RunnerError:
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
    print("""conversation-models-spec.json beklenen şekli (WBS 3.2.4):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,db,brd,consumes,observability}
  placement{in_orchestrator=true, in_session_actor=true, event_driven=true, non_blocking=true,
            pin_scope=session_start, consumes_prompt_from(3.2.3)}                          (A1,A10)
  model_types{modes[single_prompt,node_flow], node_types[start,say,collect,decision,tool,
              handoff,end], terminal_types[handoff,end]}                                    (A2,A8)
  versioning{pin_required=true, stable_within_call=true, version_recorded=true,
             no_mid_call_drift=true}                                                         (A1)
  graph_validity{single_start=true, edges_resolve=true, terminal_reachable=true,
                 reject_invalid_when_strict=true}                                            (A3)
  execution{defined_transitions_only=true, deterministic_fallback=true, step_bounded=true,
            deterministic=true, step_budget>0}                                          (A4-A7)
  gates{step_budget, require_published=true, require_version_recorded=true, max_mode_drift=0,
        max_non_terminated=0, max_invalid_graph=0, max_illegal_transition=0,
        max_stuck_without_fallback=0, max_over_step_budget=0, max_out_of_order=0,
        max_graph_nav_in_single_prompt=0, max_cross_tenant=0, max_unpublished_injected=0} (A1-A9)
  metrics{emitted[], maps_to_observability{}}
  error_taxonomy{mapping→API §11.6}                                                         (A10)
  residency{region_pin_required=true, version_recorded_home_region=true}                (A1,A10)
  pii{raw_text_in_spec_forbidden, pii_value_in_spec_forbidden, graph_curated,
      durable_redaction_state=pending}                                                 (A10)
  invariants[≥10]{id, desc, trace}

config/conversation-models-profiles.json: profiles[]{name, deployment, step_budget, region}

simulate sample: {name, profile | profile_obj, tenant_id?, agent_id?, expect, expected?{metrik:değer},
  policy?{defined_transitions_only, deterministic_fallback, step_bounded, strict_graph,
  published_only, stable_version, record_version, single_prompt_no_graph, tenant_isolation},
  events[{kind:'pin', flow_version_id, version_no, published, mode, graph?, t} |
         {kind:'turn', t, intent?, jump_to?} | {kind:'end', t, reason}]}
  — pin → (turn*) → end; son olay 'end' olmalı; node_flow grafı pin'de graph={start,nodes[],edges[]}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: conversation_models_probe.py simulate <sample.json>")
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
