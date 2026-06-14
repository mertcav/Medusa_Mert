#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
turn_taking_probe.py — WBS 3.1.3 Turn-taking + barge-in koordinasyonu

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`telephony/edge-vad/` + `rtp-jitter/` probe disipliniyle aynı; burada deterministik bir
ORCHESTRATOR TURN MANAGER (SAD §6.2) simülatörü (olay-tetikli, sanal saat, random YOK).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) — edge'den (2.2.3) gelen ONAYLI turn-event'leri tüketir,
turn state machine'i (SAD §6.1) sürer ve turn-taking + barge-in'i KOORDİNE eder:
  • Tek-zemin (floor):  her an konuşma sırası yalnız bir tarafta; agent kullanıcının üstüne konuşmaz (C3).
  • Barge-in:           SPEAK/THINK/ACT'ta barge_in → cancel emit + CAPTURE; dispatch P95 ≤ bütçe (C1/C2).
  • Idempotent iptal:   CAPTURE'da tekrar barge_in yeni cancel üretmez (C5).
  • Gereksiz ara yanıt YOK: kullanıcı zemini elindeyken yanıt başlatılmaz; yalnız endpoint sonrası (C3/C7).
  • Backchannel ayrımı: 'evet/hı hı' barge-in sayılmaz — cancel/zemin değişimi yok (C4).
  • Legal geçişler:     tüm geçişler SAD §6.1 legal_transitions kümesinde (C6).
  • Metrikler:          barge-in/turn → BRD §15 → observability (C9).

KAPSAM AYRIMI: edge VAD/endpointing + barge-in ALGILAMA → 2.2.3 (olay üreteci) · TTS kesme/egress flush
≤200ms → 2.2.7 + 2.2.1 J11 · turn state machine tanımı → 3.1.2. Burada YALNIZ orchestrator KOORDİNASYON.

Komutlar:
  validate              turn-taking-spec.json'ı invariant'lara + config profillerine karşı doğrular.
  simulate <sample>     Deterministik Turn Manager — turn-event akışı → durum geçişleri + cancel/koordinasyon
                        kararları + metrikler + HARD kapılar (C1–C6); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek async runtime yerine deterministik simülasyondur (canlı
sistemde Go/Rust olay-döngüsü, ADR-003/SAD §6.3). Ham ses payload'ı/transkript/PII YOK.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "turn-taking-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "turn-taking-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# turn state machine (SAD §6.1)
STATES = {"LISTEN", "CAPTURE", "THINK", "ACT", "SPEAK", "TRANSFER", "END"}
FLOOR_BY_STATE = {
    "LISTEN": "none", "CAPTURE": "user", "THINK": "agent",
    "ACT": "agent", "SPEAK": "agent", "TRANSFER": "none", "END": "none",
}
# onaylı turn-event tipleri (edge'den + internal)
EVENT_TYPES = {
    "speech_start", "endpoint", "barge_in", "backchannel", "stt_final",
    "tool_needed", "tool_done", "response_ready", "tts_first_chunk",
    "tts_complete", "transfer", "hangup",
}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class TurnError(Exception):
    """Geçersiz/desteklenmeyen turn-event — sessizce kabul yok, reddet (C10)."""


def percentile(sorted_vals, p):
    """Lineer-interpolasyon percentile (0.3.x / 2.2.x ile birebir). sorted_vals artan."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# ─────────────────────────────────────────────────────────────────────────────
# Turn Manager — olay-tetikli orchestrator koordinasyonu (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class TurnManager:
    """SAD §6.2 Turn Manager. Onaylı turn-event akışını işler, durumu sürer, cancel/koordinasyon
    kararlarını verir. Olay-tetikli, bloklamaz; sanal saat (event.t) — random YOK."""

    def __init__(self, spec, params, policy):
        self.spec = spec
        self.p = params
        self.pol = policy
        tsm = spec.get("turn_state_machine", {})
        self.legal = set(tuple(x) for x in tsm.get("legal_transitions", []))
        self.state = tsm.get("initial", "LISTEN")

        # sayaçlar / metrikler
        self.barge_in_needing_cancel = 0   # SPEAK/THINK/ACT'ta gelen taze barge_in
        self.cancels = 0                   # emit edilen cancel sayısı
        self.unhandled_barge_in = 0        # zemini bırakmayan barge_in (bug)
        self.missed_cancels = 0            # cancel gereken ama emit edilmeyen
        self.spurious_cancels = 0          # tetikleyici olaysız cancel (olmamalı)
        self.duplicate_barge_in = 0        # CAPTURE'da tekrar barge_in (idempotent yoksayma)
        self.coord_latencies = []          # barge_in → cancel dispatch gecikmeleri (ms)
        self.floor_violation = 0           # CAPTURE iken SPEAK'e girme (FR-RTC-003 ihlali)
        self.interim_suppressed = 0        # kullanıcı zemini iken bastırılan erken yanıt (doğru davranış)
        self.backchannel_total = 0
        self.backchannel_ignored = 0
        self.backchannel_action = 0        # backchannel'in cancel/zemin değişimi tetiklemesi (bug)
        self.turn_total = 0                # endpoint → THINK (tamamlanan kullanıcı turu)
        self.illegal_transitions = 0
        self.transitions = []              # (t, from, to) izi

    # ── durum geçişi (legality kontrollü)
    def _to(self, new, t):
        if new == self.state:
            return
        if (self.state, new) in self.legal or new in ("TRANSFER", "END"):
            pass
        else:
            self.illegal_transitions += 1
        self.transitions.append((t, self.state, new))
        self.state = new

    def _dispatch_ms(self):
        """Barge_in olayı → cancel emit koordinasyon gecikmesi (deterministik, sanal)."""
        return float(self.p["orch_dispatch_ms"])

    def _emit_cancel(self, t):
        self.cancels += 1
        self.coord_latencies.append(self._dispatch_ms())

    def floor(self):
        return FLOOR_BY_STATE.get(self.state, "none")

    # ── tek olayı işle
    def step(self, ev):
        if not isinstance(ev, dict):
            raise TurnError("olay sözlük değil → INVALID_REQUEST")
        ty = ev.get("type")
        t = ev.get("t")
        if ty not in EVENT_TYPES:
            raise TurnError("bilinmeyen turn-event tipi: %r → INVALID_REQUEST" % ty)
        if not isinstance(t, (int, float)):
            raise TurnError("turn-event zaman damgası sayısal değil → INVALID_REQUEST")

        if ty == "speech_start":
            # Kullanıcı ses onset'i. LISTEN'de zemini kullanıcıya ver (CAPTURE).
            # SPEAK/THINK/ACT'ta ham onset TEK BAŞINA kesmez — onaylı barge_in beklenir (2.2.3 debounce).
            if self.state == "LISTEN":
                self._to("CAPTURE", t)

        elif ty == "barge_in":
            if self.state in ("SPEAK", "THINK", "ACT"):
                self.barge_in_needing_cancel += 1
                if self.pol["coordinate_barge_in"]:
                    self._emit_cancel(t)        # SPEAK→TTS iptal · THINK/ACT→üretim iptal
                    self._to("CAPTURE", t)
                else:
                    # bozuk koordinatör: zemini bırakmaz → kapı C1/C5 yakalar
                    self.unhandled_barge_in += 1
                    self.missed_cancels += 1
            elif self.state == "CAPTURE":
                # kullanıcı zaten zeminde — idempotent: yeni cancel YOK
                self.duplicate_barge_in += 1
            # LISTEN/TRANSFER/END: kesilecek agent yok → benign no-op

        elif ty == "backchannel":
            self.backchannel_total += 1
            if self.pol["backchannel_yields_floor"] and self.state == "SPEAK":
                # (bug/non-default) backchannel'i barge-in gibi ele al → C4 yakalar
                self._emit_cancel(t)
                self._to("CAPTURE", t)
                self.backchannel_action += 1
            else:
                # doğru: yoksay — cancel yok, zemin değişmez, durum korunur (FR-RTC-007)
                self.backchannel_ignored += 1

        elif ty == "endpoint":
            # söz sonu (edge). Yalnız CAPTURE'da geçerli → THINK; yanıt ancak bundan sonra üretilir.
            if self.state == "CAPTURE":
                self._to("THINK", t)
                self.turn_total += 1

        elif ty == "response_ready":
            if self.state in ("THINK", "ACT"):
                self._to("SPEAK", t)            # zemin agent'ta → seslendir
            elif self.state == "CAPTURE":
                # kullanıcı zemini elinde — erken/partial tetik
                if self.pol["floor_guard"]:
                    self.interim_suppressed += 1  # doğru: bastır, CAPTURE'da kal (FR-RTC-003)
                else:
                    self.floor_violation += 1     # bug: kullanıcının üstüne konuş
                    self._to("SPEAK", t)          # (CAPTURE→SPEAK legal değil → C6 da yakalar)
            # LISTEN/SPEAK/...: ilgisiz → yoksay

        elif ty == "tool_needed":
            if self.state == "THINK":
                self._to("ACT", t)

        elif ty == "tool_done":
            if self.state == "ACT":
                self._to("THINK", t)

        elif ty == "tts_complete":
            if self.state == "SPEAK":
                self._to("LISTEN", t)            # agent zemini bıraktı, tur bitti

        elif ty == "transfer":
            self._to("TRANSFER", t)

        elif ty == "hangup":
            self._to("END", t)

        # tts_first_chunk / stt_final: bilgilendirici, durum değişmez

    def metrics(self):
        lat = sorted(self.coord_latencies)
        coord_p95 = round(percentile(lat, 0.95), 2)
        scenario = []
        if self.turn_total > 0:
            scenario.append("turn")
        if self.barge_in_needing_cancel > 0 or self.duplicate_barge_in > 0:
            scenario.append("barge_in")
        if self.backchannel_total > 0:
            scenario.append("backchannel")
        if self.interim_suppressed > 0 or self.floor_violation > 0:
            scenario.append("interim")
        comp = self.spec.get("barge_in", {}).get("composition", {})
        composed = round(comp.get("edge_detect_nominal_ms", 0) + coord_p95
                         + comp.get("egress_flush_nominal_ms", 0), 2) if lat else 0.0
        return {
            "final_state": self.state,
            "final_floor": self.floor(),
            "transitions": len(self.transitions),
            "barge_in_count": self.barge_in_needing_cancel + self.duplicate_barge_in,
            "barge_in_needing_cancel": self.barge_in_needing_cancel,
            "duplicate_barge_in": self.duplicate_barge_in,
            "cancels": self.cancels,
            "unhandled_barge_in": self.unhandled_barge_in,
            "missed_cancels": self.missed_cancels,
            "spurious_cancels": self.spurious_cancels,
            "coordination_p95_ms": coord_p95,
            "composed_e2e_p95_ms": composed,
            "floor_violation": self.floor_violation,
            "interim_suppressed": self.interim_suppressed,
            "backchannel_total": self.backchannel_total,
            "backchannel_ignored": self.backchannel_ignored,
            "backchannel_action": self.backchannel_action,
            "turn_total": self.turn_total,
            "illegal_transitions": self.illegal_transitions,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, spec, params, policy):
    events = sample.get("events")
    if not events:
        raise TurnError("boş olay akışı")
    if not isinstance(events, list):
        raise TurnError("events liste değil → INVALID_REQUEST")
    # stabil zaman sıralaması (eşit t → giriş sırası korunur)
    indexed = list(enumerate(events))
    for _, ev in indexed:
        if not isinstance(ev, dict) or ev.get("type") not in EVENT_TYPES \
                or not isinstance(ev.get("t"), (int, float)):
            raise TurnError("geçersiz turn-event: %r → INVALID_REQUEST" % (ev,))
    ordered = sorted(indexed, key=lambda pr: (pr[1]["t"], pr[0]))
    tm = TurnManager(spec, params, policy)
    for _, ev in ordered:
        tm.step(ev)
    return tm.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (C1–C6) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    sc = set(m.get("scenario", []))

    # ── C5: cancel tamlık + idempotency (her senaryoda)
    F.append((m.get("missed_cancels", 0) <= g.get("max_missed_cancel", 0)
              and m.get("spurious_cancels", 0) <= g.get("max_spurious_cancel", 0),
              "C5 cancel tamlık/idempotent: missed=%d spurious=%d (her barge-in tam bir cancel)"
              % (m.get("missed_cancels", 0), m.get("spurious_cancels", 0))))

    # ── C6: legal geçişler (her senaryoda)
    F.append((m.get("illegal_transitions", 0) <= g.get("max_illegal_transition", 0),
              "C6 illegal geçiş %d ≤ %d (SAD §6.1 legal_transitions)"
              % (m.get("illegal_transitions", 0), g.get("max_illegal_transition", 0))))

    # ── C3: tek-zemin / gereksiz ara yanıt yok (her senaryoda)
    F.append((m.get("floor_violation", 0) <= g.get("max_floor_violation", 0),
              "C3 zemin ihlali %d ≤ %d (agent kullanıcı zeminindeyken konuşmaz — FR-RTC-003)"
              % (m.get("floor_violation", 0), g.get("max_floor_violation", 0))))

    if "barge_in" in sc:
        # ── C1: barge-in zemini bıraktırır
        F.append((m.get("unhandled_barge_in", 0) <= g.get("max_unhandled_barge_in", 0),
                  "C1 işlenmeyen barge-in %d ≤ %d (SPEAK/THINK/ACT→cancel+CAPTURE — FR-RTC-002)"
                  % (m.get("unhandled_barge_in", 0), g.get("max_unhandled_barge_in", 0))))
        # ── C2: koordinasyon gecikmesi (yalnız gerçek cancel olduysa anlamlı)
        if m.get("cancels", 0) >= 1:
            bud = g.get("coordination_p95_budget_ms", 50)
            green = g.get("green_coordination_ms", 20)
            lat = m.get("coordination_p95_ms", 0.0)
            band = "🟢" if lat <= green else ("🟡" if lat <= bud else "🔴")
            F.append((lat <= bud,
                      "C2 barge-in koordinasyon P95 %.0fms ≤ %.0fms (orkestratör dilimi; toplam ≤200ms) %s"
                      % (lat, bud, band)))

    if "backchannel" in sc:
        # ── C4: backchannel ayrımı
        F.append((m.get("backchannel_action", 0) <= g.get("max_backchannel_action", 0),
                  "C4 backchannel-eylemi %d ≤ %d (backchannel barge-in sayılmaz — FR-RTC-007)"
                  % (m.get("backchannel_action", 0), g.get("max_backchannel_action", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise TurnError("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    bi = spec.get("barge_in", {})
    return {
        "orch_dispatch_ms": profile.get("orch_dispatch_ms", bi.get("green_coordination_ms", 20)),
    }


def _resolve_policy(spec, profile, sample):
    """Spec varsayılanları + profil + sample.policy override → koordinasyon politikası."""
    fc = spec.get("floor_control", {})
    bc = spec.get("backchannel", {})
    pol = {
        "coordinate_barge_in": fc.get("agent_yields_on_barge_in", True),
        "floor_guard": spec.get("no_spurious_interim", {}).get("suppress_response_while_user_floor", True),
        "backchannel_yields_floor": profile.get("backchannel_yields_floor",
                                                 bc.get("default_yields_floor", False)),
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
            profile = _profile_by_name(cfg, sample["profile"])
        except TurnError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    params = _params_from(spec, profile)
    policy = _resolve_policy(spec, profile, sample)

    try:
        m = simulate(sample, spec, params, policy)
    except TurnError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    summ = ("simulate[%s] senaryo=%s | %d geçiş, final=%s/%s | turn=%d, barge-in=%d (cancel=%d), "
            "backchannel=%d (yoksay=%d), ara-yanıt-bastırıldı=%d" % (
                name, "+".join(m["scenario"]) or "-", m["transitions"], m["final_state"], m["final_floor"],
                m["turn_total"], m["barge_in_count"], m["cancels"], m["backchannel_total"],
                m["backchannel_ignored"], m["interim_suppressed"]))
    if m["cancels"]:
        summ += " | koordinasyon P95 %.0fms (composed e2e %.0fms)" % (
            m["coordination_p95_ms"], m["composed_e2e_p95_ms"])
    print(summ)
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

    _check(R, spec.get("wbs") == "3.1.3", "spec.wbs == 3.1.3")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── C8: placement (orchestrator, olay-tetikli, ham ses yok)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "C8 Turn Manager orchestrator içinde")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "C8 olay-tetikli + bloklamaz")
    _check(R, pl.get("consumes_edge_events") is True and pl.get("raw_audio_in_orchestrator") is False,
           "C8 onaylı edge olay tüketir; ham ses işlemez (algılama edge'de 2.2.3)")

    # ── C6: turn state machine sözleşmesi
    tsm = spec.get("turn_state_machine", {})
    sset = set(tsm.get("states", []))
    _check(R, {"LISTEN", "CAPTURE", "THINK", "ACT", "SPEAK"} <= sset,
           "C6 turn state machine SAD §6.1 çekirdek durumları")
    _check(R, tsm.get("initial") == "LISTEN", "C6 başlangıç durumu LISTEN")
    lt = tsm.get("legal_transitions", [])
    _check(R, isinstance(lt, list) and len(lt) >= 8, "C6 legal_transitions ≥8")
    _check(R, all(isinstance(x, list) and len(x) == 2 and x[0] in sset and x[1] in sset for x in lt),
           "C6 legal_transitions çiftleri tanımlı durumlar")
    _check(R, ["SPEAK", "CAPTURE"] in lt, "C6 SPEAK→CAPTURE legal (barge-in)")
    _check(R, ["CAPTURE", "THINK"] in lt, "C6 CAPTURE→THINK legal (endpoint)")
    _check(R, ["CAPTURE", "SPEAK"] not in lt,
           "C6 CAPTURE→SPEAK legal DEĞİL (kullanıcının üstüne konuşma yasak)")
    fbs = tsm.get("floor_by_state", {})
    _check(R, fbs.get("CAPTURE") == "user" and fbs.get("SPEAK") == "agent" and fbs.get("LISTEN") == "none",
           "C6 floor_by_state CAPTURE=user/SPEAK=agent/LISTEN=none")

    # ── C1/C3: floor_control
    fc = spec.get("floor_control", {})
    _check(R, fc.get("single_floor") is True, "C1/C3 tek-zemin (single_floor)")
    _check(R, fc.get("agent_yields_on_barge_in") is True, "C1 agent barge-in'de zemini bırakır")
    _check(R, fc.get("agent_speaks_only_with_floor") is True, "C3 agent yalnız zemin elindeyken konuşur")

    # ── C2: barge-in koordinasyon bütçesi + kompozisyon
    bi = spec.get("barge_in", {})
    _check(R, isinstance(bi.get("orch_coordination_budget_ms"), (int, float))
           and bi.get("orch_coordination_budget_ms") > 0, "C2 koordinasyon bütçesi pozitif")
    _check(R, bi.get("green_coordination_ms", 1e9) <= bi.get("orch_coordination_budget_ms", 0),
           "C2 green ≤ koordinasyon bütçesi")
    _check(R, bi.get("orch_coordination_budget_ms", 999) <= 200,
           "C2 orkestratör dilimi ≤ toplam barge-in bütçesi 200ms (NFR 10.1/SAD §6.1)")
    _check(R, bi.get("cancel_idempotent") is True, "C5 cancel idempotent bayrağı")
    comp = bi.get("composition", {})
    total = comp.get("total_budget_ms", 0)
    _check(R, total == 200, "C2 composition total_budget 200ms")
    _check(R, comp.get("edge_detect_nominal_ms", 0) + bi.get("orch_coordination_budget_ms", 0)
           + comp.get("egress_flush_nominal_ms", 0) <= total,
           "C2 edge+orch+egress ≤ 200ms (kompozisyon tutarlı)")

    # ── C4: backchannel default
    bc = spec.get("backchannel", {})
    _check(R, bc.get("default_yields_floor") is False,
           "C4 backchannel varsayılan barge-in DEĞİL (yields_floor=false)")

    # ── C3/C7: no spurious interim
    nsi = spec.get("no_spurious_interim", {})
    _check(R, nsi.get("suppress_response_while_user_floor") is True,
           "C3 kullanıcı zemini iken yanıt bastırılır")
    _check(R, nsi.get("respond_only_after_endpoint") is True,
           "C7 yanıt yalnız endpoint sonrası (gereksiz ara yanıt yok)")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("coordination_p95_budget_ms", 0) == bi.get("orch_coordination_budget_ms", -1),
           "C2 gates bütçesi barge_in bütçesiyle tutarlı")
    _check(R, g.get("green_coordination_ms", 1e9) <= g.get("coordination_p95_budget_ms", 0),
           "C2 gates green ≤ bütçe")
    _check(R, g.get("max_unhandled_barge_in", -1) == 0, "C1 max_unhandled_barge_in = 0")
    _check(R, g.get("max_floor_violation", -1) == 0, "C3 max_floor_violation = 0")
    _check(R, g.get("max_backchannel_action", -1) == 0, "C4 max_backchannel_action = 0")
    _check(R, g.get("max_missed_cancel", -1) == 0 and g.get("max_spurious_cancel", -1) == 0,
           "C5 max_missed/spurious_cancel = 0")
    _check(R, g.get("max_illegal_transition", -1) == 0, "C6 max_illegal_transition = 0")
    _check(R, g.get("cancel_idempotent") is True, "C5 gates cancel_idempotent")

    # ── C9: metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"barge_in_count", "coordination_p95_ms", "floor_violation_total", "turn_total"} <= emitted,
           "C9 turn-taking metrikleri yayılır")
    mo = me.get("maps_to_observability", {})
    _check(R, mo.get("barge_in_count") == "barge_in_total",
           "C9 barge_in_count → barge_in_total (0.4.7 observability-spec)")

    # ── C10: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "C10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "C10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_event") == "INVALID_REQUEST"
           and mapping.get("event_stream_lost") == "UNAVAILABLE"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "C10 geçersiz-olay→INVALID, akış→UNAVAILABLE, bölge→REGION_VIOLATION")

    # ── C10: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "C10 residency region pin")
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "C10 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "C10 transkript spec'te yasak")

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
    _check(R, not hits, "C10 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 koordinasyon profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        bud = g.get("coordination_p95_budget_ms", 50)
        for p in profs:
            _check(R, bool(p.get("region")), "C10 config %s bölge pini var" % p.get("name"))
            _check(R, 0 < p.get("orch_dispatch_ms", 0) <= bud,
                   "config %s orch_dispatch ≤ koordinasyon bütçesi" % p.get("name"))

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
def _ev(t, ty):
    return {"t": t, "type": ty}


def _run(events, spec, dispatch=12, **pol_over):
    params = {"orch_dispatch_ms": dispatch}
    pol = {"coordinate_barge_in": True, "floor_guard": True, "backchannel_yields_floor": False}
    pol.update(pol_over)
    return simulate({"events": events}, spec, params, pol)


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── percentile (0.3.x ile birebir)
    case(abs(percentile([10, 20, 30, 40], 0.95) - 38.5) < 1e-6, "percentile P95 lineer-interp")
    case(percentile([], 0.95) == 0.0 and percentile([7], 0.95) == 7.0, "percentile boş/tekil")

    # ── happy turn: tam tur döngüsü (tool dahil) ─────────────────────────────────
    happy = [
        _ev(0, "speech_start"), _ev(900, "endpoint"), _ev(950, "stt_final"),
        _ev(1000, "tool_needed"), _ev(1200, "tool_done"),
        _ev(1300, "response_ready"), _ev(1320, "tts_first_chunk"), _ev(2200, "tts_complete"),
    ]
    mh = _run(happy, spec)
    case(mh["turn_total"] == 1, "happy: 1 tamamlanan kullanıcı turu (endpoint→THINK)")
    case(mh["illegal_transitions"] == 0, "happy: illegal geçiş yok (LISTEN→CAPTURE→THINK→ACT→THINK→SPEAK→LISTEN)")
    case(mh["final_state"] == "LISTEN" and mh["final_floor"] == "none", "happy: final LISTEN/none (zemin bırakıldı)")
    case(mh["floor_violation"] == 0 and mh["cancels"] == 0, "happy: zemin ihlali/cancel yok")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")

    # ── barge-in SPEAK: cancel + CAPTURE, dispatch ≤ bütçe ────────────────────────
    bs = [
        _ev(0, "speech_start"), _ev(800, "endpoint"), _ev(900, "response_ready"),
        _ev(920, "tts_first_chunk"), _ev(1500, "barge_in"),
    ]
    mb = _run(bs, spec, dispatch=12)
    case(mb["cancels"] == 1 and mb["unhandled_barge_in"] == 0, "barge-in: 1 cancel, işlenmeyen yok (C1)")
    case(mb["final_state"] == "CAPTURE" and mb["final_floor"] == "user", "barge-in: SPEAK→CAPTURE, zemin kullanıcıya")
    case(mb["coordination_p95_ms"] <= spec["gates"]["coordination_p95_budget_ms"], "barge-in: koordinasyon ≤ bütçe (C2)")
    case(all(ok for ok, _ in evaluate(spec, mb)), "barge-in SPEAK akışı kapıları geçer")

    # ── barge-in THINK: in-flight üretim iptal, zemin bırakılır ───────────────────
    bt = [_ev(0, "speech_start"), _ev(700, "endpoint"), _ev(800, "barge_in")]
    mt = _run(bt, spec)
    case(mt["cancels"] == 1 and mt["final_state"] == "CAPTURE", "barge-in THINK: üretim iptal → CAPTURE")
    case(mt["missed_cancels"] == 0 and all(ok for ok, _ in evaluate(spec, mt)), "barge-in THINK kapıları geçer")

    # ── idempotent: SPEAK'te barge_in + CAPTURE'da tekrar barge_in → tek cancel ────
    idem = [
        _ev(0, "speech_start"), _ev(700, "endpoint"), _ev(800, "response_ready"),
        _ev(1400, "barge_in"), _ev(1450, "barge_in"),
    ]
    mi = _run(idem, spec)
    case(mi["cancels"] == 1 and mi["duplicate_barge_in"] == 1, "idempotent: 2 barge_in → 1 cancel (CAPTURE'da yoksay)")
    case(mi["spurious_cancels"] == 0 and all(ok for ok, _ in evaluate(spec, mi)), "idempotent C5 geçer")

    # ── backchannel ignored: agent konuşurken 'evet' → cancel/zemin değişimi yok ───
    bch = [
        _ev(0, "speech_start"), _ev(600, "endpoint"), _ev(700, "response_ready"),
        _ev(720, "tts_first_chunk"), _ev(1100, "backchannel"), _ev(1900, "tts_complete"),
    ]
    mc = _run(bch, spec)
    case(mc["backchannel_ignored"] == 1 and mc["backchannel_action"] == 0, "backchannel: yoksayıldı (cancel/zemin değişimi yok, C4)")
    case(mc["cancels"] == 0 and mc["final_state"] == "LISTEN", "backchannel: agent kesilmeden konuşmayı bitirdi")
    case(all(ok for ok, _ in evaluate(spec, mc)), "backchannel akışı kapıları geçer")

    # ── no spurious interim: kullanıcı zeminindeyken erken response_ready bastırılır ─
    spur = [
        _ev(0, "speech_start"), _ev(300, "response_ready"), _ev(900, "endpoint"),
        _ev(1000, "response_ready"), _ev(1020, "tts_first_chunk"), _ev(1800, "tts_complete"),
    ]
    ms = _run(spur, spec)
    case(ms["interim_suppressed"] == 1, "ara-yanıt: kullanıcı zeminindeyken erken yanıt bastırıldı (FR-RTC-003)")
    case(ms["floor_violation"] == 0 and ms["turn_total"] == 1, "ara-yanıt: zemin ihlali yok, endpoint sonrası yanıt verildi")
    case(all(ok for ok, _ in evaluate(spec, ms)), "no-spurious-interim kapıları geçer (C3/C7)")

    # ── degraded: floor_guard kapalı + koordinasyon kapalı → çoklu kapı eler ───────
    deg = [
        _ev(0, "speech_start"), _ev(300, "response_ready"),   # kullanıcı zemini iken konuşur (C3 ihlali)
        _ev(900, "endpoint"), _ev(1000, "response_ready"),
        _ev(1020, "tts_first_chunk"), _ev(1600, "barge_in"),  # zemini bırakmaz (C1/C5)
    ]
    md = _run(deg, spec, coordinate_barge_in=False, floor_guard=False)
    Fd = evaluate(spec, md)
    case(md["floor_violation"] >= 1, "degraded: zemin ihlali tespit (C3 eler)")
    case(md["unhandled_barge_in"] >= 1 and md["missed_cancels"] >= 1, "degraded: işlenmeyen barge-in + kaçan cancel (C1/C5 eler)")
    case(md["illegal_transitions"] >= 1, "degraded: CAPTURE→SPEAK illegal geçiş (C6 eler)")
    case(not all(ok for ok, _ in Fd), "degraded akış en az bir kapıyı eler")

    # ── geçersiz olay reddi (C10) ────────────────────────────────────────────────
    case(_raises(lambda: simulate({"events": [{"t": 0, "type": "nope"}]}, spec, {"orch_dispatch_ms": 12},
                                  {"coordinate_barge_in": True, "floor_guard": True, "backchannel_yields_floor": False})),
         "C10 bilinmeyen olay tipi → reddedilir")
    case(_raises(lambda: simulate({"events": [{"type": "endpoint"}]}, spec, {"orch_dispatch_ms": 12},
                                  {"coordinate_barge_in": True, "floor_guard": True, "backchannel_yields_floor": False})),
         "C10 zaman damgasız olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, spec, {"orch_dispatch_ms": 12},
                                  {"coordinate_barge_in": True, "floor_guard": True, "backchannel_yields_floor": False})),
         "C10 boş olay akışı → reddedilir")

    # ── olay sıralaması: girişte karışık t → zaman sırasına göre işlenir ──────────
    unordered = [_ev(900, "endpoint"), _ev(0, "speech_start"), _ev(1000, "response_ready"), _ev(1700, "tts_complete")]
    mu = _run(unordered, spec)
    case(mu["turn_total"] == 1 and mu["illegal_transitions"] == 0, "sıralama: karışık t doğru zaman sırasında işlendi")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["floor_control"]["single_floor"] = False
    case(_validate_obj(s) != 0, "C1/C3 single_floor kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["floor_control"]["agent_yields_on_barge_in"] = False
    case(_validate_obj(s) != 0, "C1 agent_yields kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["backchannel"]["default_yields_floor"] = True
    case(_validate_obj(s) != 0, "C4 backchannel default yields → validate eler")
    s = json.loads(json.dumps(spec)); s["barge_in"]["orch_coordination_budget_ms"] = 300
    case(_validate_obj(s) != 0, "C2 koordinasyon bütçesi >200ms → validate eler")
    s = json.loads(json.dumps(spec)); s["barge_in"]["green_coordination_ms"] = 999
    case(_validate_obj(s) != 0, "C2 green>bütçe → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_floor_violation"] = 1
    case(_validate_obj(s) != 0, "C3 max_floor_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_illegal_transition"] = 2
    case(_validate_obj(s) != 0, "C6 max_illegal_transition>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["turn_state_machine"]["legal_transitions"].append(["CAPTURE", "SPEAK"])
    case(_validate_obj(s) != 0, "C6 CAPTURE→SPEAK legal eklenirse → validate eler")
    s = json.loads(json.dumps(spec)); s["no_spurious_interim"]["respond_only_after_endpoint"] = False
    case(_validate_obj(s) != 0, "C7 respond_only_after_endpoint kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "C10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["raw_payload_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "C10 ham-payload-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["barge_in"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "C10 literal secret → validate eler")

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
    except TurnError:
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
    print("""turn-taking-spec.json beklenen şekli (WBS 3.1.3):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability}
  placement{in_orchestrator=true, event_driven=true, non_blocking=true,
            consumes_edge_events=true, raw_audio_in_orchestrator=false}          (C8)
  turn_state_machine{states[], initial=LISTEN, legal_transitions[[from,to]...],
                     floor_by_state{}}                                            (C6)
  floor_control{single_floor=true, agent_yields_on_barge_in=true,
                agent_speaks_only_with_floor=true}                               (C1,C3)
  barge_in{orch_coordination_budget_ms≤200, green_coordination_ms≤bütçe,
           cancel_idempotent=true, composition{edge/orch/egress ≤ total=200}}    (C2,C5)
  backchannel{default_yields_floor=false}                                        (C4)
  no_spurious_interim{suppress_response_while_user_floor=true,
                      respond_only_after_endpoint=true}                          (C3,C7)
  gates{coordination_p95_budget_ms, green_coordination_ms,
        max_unhandled_barge_in=0, max_floor_violation=0, max_backchannel_action=0,
        max_missed_cancel=0, max_spurious_cancel=0, max_illegal_transition=0,
        cancel_idempotent=true}                                       (C1,C2,C3,C4,C5,C6)
  metrics{emitted[], maps_to_observability{barge_in_count→barge_in_total}}        (C9)
  error_taxonomy{mapping→API §11.6}                                              (C10)
  residency{region_pin_required=true}                                            (C10)
  pii{raw_payload_in_spec_forbidden, transcript_in_spec_forbidden}               (C10)
  invariants[≥10]{id, desc, trace}

config/turn-taking-profiles.json: profiles[]{name, integration_mode,
  orch_dispatch_ms (≤bütçe), backchannel_yields_floor, region}

simulate sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  policy?{coordinate_barge_in, floor_guard, backchannel_yields_floor},
  events[{t (ms), type}]}  — type ∈ {speech_start, endpoint, barge_in, backchannel,
  stt_final, tool_needed, tool_done, response_ready, tts_first_chunk, tts_complete,
  transfer, hangup}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: turn_taking_probe.py simulate <sample.json>")
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
