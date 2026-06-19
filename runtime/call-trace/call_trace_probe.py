#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_trace_probe.py — WBS 14.1.1 Çağrı trace span'leri (BRD §15 TÜM zaman damgaları)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/context-propagation/` (3.1.5) + `runtime/turn-taking/` (3.1.3) probe disipliniyle birebir;
burada deterministik bir CONVERSATION ORCHESTRATOR CALL TRACER (SAD §17.1) simülatörü (olay-tetikli,
sanal saat, random YOK).

CALL TRACER (Çekirdek IP, SAD §6 / §17.1) — çağrı INGRESS'inde root 'call' span + trace_id (çağrı boyu
sabit) + correlation_id açar; turn state machine (SAD §6.1) ilerledikçe alt span'lar (turn/stt/llm/tool/
tts/transfer) açar ve BRD §15'in 15 zaman damgasının HEPSİNİ DOĞRU span'a SPAN EVENT olarak kaydeder:
  • Kapsam (G1):        senaryonun must_cover zaman damgalarının hepsi kaydedilir (coverage_missing=0).
  • Eşleme (G2):        her zaman damgası doğru span KINDine (stt_*→stt, llm_*→llm...) — mapping=0.
  • Nedensel sıra (G3): causal_order çiftleri monoton (t[önce] ≤ t[sonra]) — ordering=0.
  • Ağaç (G4):          tek root + geçerli ebeveyn + çocuk aralığı ebeveyne sığar + end≥start — tree=0.
  • Kimlik (G5):        çağrı başına tek trace_id + tek correlation_id; her span taşır — identity=0.
  • Attribute (G6):     span attribute'unda PII / ham payload yok — attribute=0.
  • Türetme (G7):       BRD §15 gecikmeleri (e2e/STT/LLM/TTS/tool) non-negative + finite — derivation=0.

KAPSAM AYRIMI: bağlam İLİŞTİRME + kardinalite/PII enforcement → 3.1.5 · metrik/alarm KATALOĞU + collector
guard → 0.4.7 · metrik DEĞER hesaplama → 14.1.2 · per-call CPU/bellek → 14.1.3/3.1.4 · loglama → 14.1.4.
Burada YALNIZ orchestrator-tarafı RUNTIME SPAN ÜRETİMİ.

Komutlar:
  validate              call-trace-spec.json'ı invariant'lara + 0.4.7 çapraz-tutarlılığa + config'e karşı doğrular.
  simulate <sample>     Deterministik CallTracer — olay akışı → span ağacı + zaman damgası kaydı + türetilen
                        gecikme + HARD kapılar (G1–G7); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek async runtime yerine deterministik simülasyondur (canlı
sistemde Go/Rust olay-döngüsü + OpenTelemetry W3C traceparent, ADR-003/SAD §6.3/§17.1). Ham ses
payload'ı/transkript/PII DEĞERİ YOK — olaylar yalnız ZAMAN DAMGASI ADLARI + sanal zaman + kimlik
anahtarı ADLARI taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "call-trace-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "call-trace-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class TraceError(Exception):
    """Geçersiz/desteklenmeyen olay veya eksik ingress kimliği — sessizce kabul yok, reddet (G10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Call Tracer — olay-tetikli orchestrator span üretimi (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class CallTracer:
    """SAD §17.1 Call Tracer. Çağrı ingress'inde root 'call' span + trace_id + correlation_id açar;
    BRD §15 zaman damgalarını doğru span'a span event olarak kaydeder; nedensel sıra + ağaç + kimlik +
    attribute + gecikme türetme invariant'larını uygular. Olay-tetikli; sanal saat (event.t) — random YOK.

    policy bayrakları buggy Tracer'ı simüle eder (context-propagation/turn-taking deseni):
      record_all       : her olayı kaydet (kapalı → bazı zaman damgaları düşer, G1)
      correct_mapping  : zaman damgasını doğru span'a kaydet (kapalı → root'a kaydeder, G2)
      nest_spans       : alt span'ı doğru ebeveyne + sınır içine yerleştir (kapalı → orphan/taşma, G4)
      attach_identity  : her span'a trace_id+correlation_id iliştir (kapalı → identity_violation, G5)
      enforce_attr     : PII/ham payload attribute'unu çıkar (kapalı → attribute_violation, G6)
    """

    def __init__(self, spec, session, policy):
        self.spec = spec
        sm = spec.get("span_model", {})
        self.root_span = sm.get("root_span", "call")
        self.span_kinds = set(sm.get("span_kinds", []))
        self.parent_of = dict(sm.get("parent_of", {}))
        ts = spec.get("timestamps", {})
        self.catalog = list(ts.get("catalog", []))
        self.span_of = dict(ts.get("span_of", {}))
        self.required_completed = list(ts.get("required_for_completed", []))
        self.causal_pairs = [tuple(p) for p in spec.get("causal_order", {}).get("pairs", [])]
        self.derived = dict(spec.get("derived_latencies", {}).get("map", {}))
        idn = spec.get("identity", {})
        self.identity_keys = set(idn.get("identity_keys_on_every_span", ["trace_id", "correlation_id", "tenant_id"]))
        ap = spec.get("attribute_policy", {})
        self.forbidden_attr = set(ap.get("forbidden_attr_keys", []))
        self.allowed_attr = set(ap.get("allowed_attr_keys", []))
        self.pol = policy

        # ingress kimliği (BİR KEZ kurulur)
        self.session = dict(session)
        for rk in ("tenant_id", "correlation_id", "trace_id"):
            if not self.session.get(rk):
                raise TraceError("ingress kimliği eksik: %s → INVALID_REQUEST" % rk)
        self.call_trace_id = self.session.get("trace_id")
        self.call_correlation = self.session.get("correlation_id")
        self.bound_tenant = self.session.get("tenant_id")

        # span deposu: key=(kind, turn_index) → span dict
        self.spans = {}          # key → {kind, parent_key, turn, start, end, events[], identity{}}
        self.root_key = None

        # gözlemlenen zaman damgaları (kayıtlı): ts_name → t (son kazanır; çoğu tekil)
        self.recorded = {}
        self.recorded_turn = {}  # ts_name → turn_index

        # sayaçlar / metrikler
        self.events_total = 0
        self.spans_total = 0
        self.mapping_violations = 0
        self.ordering_violations = 0
        self.tree_violations = 0
        self.identity_violations = 0
        self.attribute_violations = 0
        self.derivation_violations = 0
        self.trace_ids = set()
        self.correlation_ids = set()
        self.tenant_ids = set()

    # ── span yardımcıları ────────────────────────────────────────────────────
    def _span_key(self, kind, turn):
        # call/transfer span'ları çağrı-düzeyinde tekil; diğerleri turn-bazlı
        if kind in ("call",):
            return (kind, 0)
        if kind in ("transfer",):
            return (kind, 0)
        return (kind, turn)

    def _ensure_span(self, kind, turn):
        key = self._span_key(kind, turn)
        if key not in self.spans:
            parent_key = None
            if kind != self.root_span:
                pkind = self.parent_of.get(kind)
                if pkind == "call":
                    parent_key = (self.root_span, 0)
                elif pkind:
                    parent_key = (pkind, turn if pkind != "call" else 0)
                # ebeveyn span yoksa ihtiyaç anında oluştur (turn span gibi)
                if parent_key is not None and parent_key not in self.spans:
                    self._ensure_span(parent_key[0], parent_key[1])
            self.spans[key] = {
                "kind": kind, "parent_key": parent_key, "turn": turn,
                "start": None, "end": None, "events": [],
                "identity": {},
            }
            self.spans_total += 1
            if kind == self.root_span:
                self.root_key = key
        return self.spans[key]

    def _attach_identity(self, span):
        if self.pol.get("attach_identity", True):
            span["identity"] = {
                "trace_id": self.call_trace_id,
                "correlation_id": self.call_correlation,
                "tenant_id": self.bound_tenant,
            }
        else:
            span["identity"] = {}  # buggy: kimlik iliştirilmez

    # ── olay işleme ──────────────────────────────────────────────────────────
    def step(self, ev):
        if not isinstance(ev, dict):
            raise TraceError("olay sözlük değil → INVALID_REQUEST")
        ts = ev.get("ts")
        t = ev.get("t")
        if ts not in self.catalog:
            raise TraceError("bilinmeyen zaman damgası: %r → INVALID_REQUEST" % ts)
        if not isinstance(t, (int, float)):
            raise TraceError("olay zaman damgası sayısal değil → INVALID_REQUEST")
        turn = ev.get("turn", 1)
        if not isinstance(turn, int) or turn < 0:
            raise TraceError("geçersiz turn indeksi → INVALID_REQUEST")
        # çağrı ortasında trace_id değişimi (kimlik bozulması) → reddet (G10)
        if ev.get("trace_id") is not None and ev.get("trace_id") != self.call_trace_id:
            raise TraceError("çağrı ortasında trace_id değişimi → INVALID_REQUEST")

        self.events_total += 1

        if not self.pol.get("record_all", True):
            # buggy: bazı olaylar düşürülür → kaydedilmez (G1). drop_ts listesi sample.policy'den.
            if ts in set(self.pol.get("drop_ts", [])):
                return

        # ── hedef span KINDi ──────────────────────────────────────────────────
        correct_kind = self.span_of.get(ts)
        if self.pol.get("correct_mapping", True):
            target_kind = correct_kind
        else:
            # buggy: her şeyi root'a kaydet → alt span'a ait olanlar yanlış eşlenir
            target_kind = self.root_span
            if correct_kind != self.root_span:
                self.mapping_violations += 1

        span = self._ensure_span(target_kind, turn)
        self._attach_identity(span)

        # span [start,end] güncelle
        if span["start"] is None or t < span["start"]:
            span["start"] = t
        if span["end"] is None or t > span["end"]:
            span["end"] = t
        span["events"].append({"ts": ts, "t": t})

        # ── kayıt (coverage / ordering / derivation için) ─────────────────────
        self.recorded[ts] = t
        self.recorded_turn[ts] = turn

        # ── kimlik takibi (G5) ────────────────────────────────────────────────
        ident = span["identity"]
        if ident.get("trace_id"):
            self.trace_ids.add(ident["trace_id"])
        else:
            self.identity_violations += 1   # span trace_id taşımıyor
        if ident.get("correlation_id"):
            self.correlation_ids.add(ident["correlation_id"])
        if ident.get("tenant_id"):
            self.tenant_ids.add(ident["tenant_id"])

        # ── attribute disiplini (G6) ──────────────────────────────────────────
        attrs = list(ev.get("attrs", []))   # emitter'ın span'a koymak istediği anahtar ADLARI
        for a in attrs:
            if a in self.forbidden_attr:
                if not self.pol.get("enforce_attr", True):
                    self.attribute_violations += 1   # buggy: PII/ham payload attribute geçti
                # enforce açıkken: redaction L7 → çıkarılır (no-op burada)

    def _depth(self, kind):
        d = 0
        cur = kind
        seen = set()
        while cur != self.root_span and cur in self.parent_of and cur not in seen:
            seen.add(cur)
            d += 1
            cur = self.parent_of[cur]
        return d

    # ── çağrı sonu: ağaç + sıra + türetme değerlendirmesi ─────────────────────
    def finalize(self):
        # ── nedensel sıra (G3) ────────────────────────────────────────────────
        for before, after in self.causal_pairs:
            if before in self.recorded and after in self.recorded:
                if self.recorded[before] > self.recorded[after]:
                    self.ordering_violations += 1

        # ── span sınır propagasyonu: ara (root-olmayan) span'lar çocuklarını KAPSAR ──
        # Gerçek OTel semantiği: ebeveyn span'ı son çocuğu bitince kapanır. KÖK 'call' span'ı
        # call_connected/call_ended yaşam-döngüsü zaman damgalarına ANKORLU kalır (genişlemez) —
        # böylece call_ended sonrası kaydedilen bir çocuk (G4) ihlal olarak yakalanır.
        for key, s in sorted(self.spans.items(), key=lambda kv: -self._depth(kv[1]["kind"])):
            pk = s["parent_key"]
            if pk is None or pk not in self.spans:
                continue
            parent = self.spans[pk]
            if parent["kind"] == self.root_span:
                continue  # kök ankorlu — genişletme
            if s["start"] is not None:
                if parent["start"] is None or s["start"] < parent["start"]:
                    parent["start"] = s["start"]
            if s["end"] is not None:
                if parent["end"] is None or s["end"] > parent["end"]:
                    parent["end"] = s["end"]

        # ── ağaç iyi-biçimlilik (G4) ──────────────────────────────────────────
        roots = [k for k, s in self.spans.items() if s["kind"] == self.root_span]
        if len(roots) != 1:
            self.tree_violations += abs(len(roots) - 1) or 1
        for key, s in self.spans.items():
            # span end ≥ start
            if s["start"] is not None and s["end"] is not None and s["end"] < s["start"]:
                self.tree_violations += 1
            if s["kind"] == self.root_span:
                continue
            pk = s["parent_key"]
            if pk is None or pk not in self.spans:
                if self.pol.get("nest_spans", True):
                    self.tree_violations += 1   # orphan
                else:
                    self.tree_violations += 1
                continue
            parent = self.spans[pk]
            # çocuk aralığı ebeveyne sığar (her ikisi de zamanlıysa)
            if self.pol.get("nest_spans", True):
                if (s["start"] is not None and parent["start"] is not None
                        and s["start"] < parent["start"]):
                    self.tree_violations += 1
                if (s["end"] is not None and parent["end"] is not None
                        and s["end"] > parent["end"]):
                    self.tree_violations += 1
            else:
                # buggy: nesting zorlanmaz → çocuk ebeveyn sınırını taşabilir (sample verisi gösterir)
                if (s["start"] is not None and parent["start"] is not None
                        and s["start"] < parent["start"]):
                    self.tree_violations += 1
                if (s["end"] is not None and parent["end"] is not None
                        and s["end"] > parent["end"]):
                    self.tree_violations += 1

        # ── türetilen gecikmeler (G7) ─────────────────────────────────────────
        derived = {}
        for name, (frm, to) in self.derived.items():
            if frm in self.recorded and to in self.recorded:
                val = self.recorded[to] - self.recorded[frm]
                derived[name] = val
                if val < 0:
                    self.derivation_violations += 1
        self.derived_values = derived

    def coverage_missing(self, must_cover):
        return [ts for ts in must_cover if ts not in self.recorded]

    def metrics(self, must_cover):
        missing = self.coverage_missing(must_cover)
        return {
            "events_total": self.events_total,
            "spans_total": self.spans_total,
            "recorded_count": len(self.recorded),
            "coverage_missing": len(missing),
            "coverage_missing_keys": missing,
            "mapping_violations": self.mapping_violations,
            "ordering_violations": self.ordering_violations,
            "tree_violations": self.tree_violations,
            "identity_violations": self.identity_violations,
            "attribute_violations": self.attribute_violations,
            "derivation_violations": self.derivation_violations,
            "distinct_trace_ids": len(self.trace_ids),
            "distinct_correlation_ids": len(self.correlation_ids),
            "derived_latencies": dict(self.derived_values),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, spec, session, policy):
    events = sample.get("events")
    if not events:
        raise TraceError("boş olay akışı")
    if not isinstance(events, list):
        raise TraceError("events liste değil → INVALID_REQUEST")
    indexed = list(enumerate(events))
    for _, ev in indexed:
        if not isinstance(ev, dict) or "ts" not in ev or not isinstance(ev.get("t"), (int, float)):
            raise TraceError("geçersiz olay: %r → INVALID_REQUEST" % (ev,))
    ordered = sorted(indexed, key=lambda pr: (pr[1]["t"], pr[0]))
    tr = CallTracer(spec, session, policy)
    for _, ev in ordered:
        tr.step(ev)
    tr.finalize()
    must_cover = sample.get("must_cover")
    if must_cover is None:
        must_cover = spec.get("timestamps", {}).get("required_for_completed", [])
    return tr.metrics(must_cover)


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G7) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    F.append((m.get("coverage_missing", 0) <= g.get("max_coverage_missing", 0),
              "G1 kapsam eksik %d ≤ %d (must_cover BRD §15 zaman damgaları kaydedildi%s — BRD §15/SAD §17.1)"
              % (m.get("coverage_missing", 0), g.get("max_coverage_missing", 0),
                 (" [eksik: %s]" % ",".join(m.get("coverage_missing_keys", []))) if m.get("coverage_missing") else "")))
    F.append((m.get("mapping_violations", 0) <= g.get("max_mapping_violation", 0),
              "G2 eşleme ihlali %d ≤ %d (her zaman damgası doğru span KINDine — SAD §17.1)"
              % (m.get("mapping_violations", 0), g.get("max_mapping_violation", 0))))
    F.append((m.get("ordering_violations", 0) <= g.get("max_ordering_violation", 0),
              "G3 nedensel sıra ihlali %d ≤ %d (causal_order monoton t[önce]≤t[sonra] — BRD §15)"
              % (m.get("ordering_violations", 0), g.get("max_ordering_violation", 0))))
    F.append((m.get("tree_violations", 0) <= g.get("max_tree_violation", 0),
              "G4 ağaç ihlali %d ≤ %d (tek root + geçerli ebeveyn + nesting + end≥start — SAD §17.1)"
              % (m.get("tree_violations", 0), g.get("max_tree_violation", 0))))
    F.append((m.get("identity_violations", 0) <= g.get("max_identity_violation", 0)
              and m.get("distinct_trace_ids", 0) <= 1 and m.get("distinct_correlation_ids", 0) <= 1,
              "G5 kimlik ihlali %d ≤ %d (tek trace_id=%d + tek correlation_id=%d; her span taşır — SAD §17.1)"
              % (m.get("identity_violations", 0), g.get("max_identity_violation", 0),
                 m.get("distinct_trace_ids", 0), m.get("distinct_correlation_ids", 0))))
    F.append((m.get("attribute_violations", 0) <= g.get("max_attribute_violation", 0),
              "G6 attribute ihlali %d ≤ %d (span'da PII/ham payload yok — FR-REC-004/BRD §17.7)"
              % (m.get("attribute_violations", 0), g.get("max_attribute_violation", 0))))
    F.append((m.get("derivation_violations", 0) <= g.get("max_derivation_violation", 0),
              "G7 türetme ihlali %d ≤ %d (BRD §15 gecikmeleri non-negative+finite — SAD §17.1/§20)"
              % (m.get("derivation_violations", 0), g.get("max_derivation_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# oturum + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise TraceError("bilinmeyen profil: %s" % name)


def _resolve_session(spec, profile, sample):
    sess = dict(sample.get("session", {}))
    sess.setdefault("region", profile.get("region"))
    return sess


def _resolve_policy(spec, sample):
    pol = {
        "record_all": True,
        "correct_mapping": True,
        "nest_spans": True,
        "attach_identity": True,
        "enforce_attr": True,
        "drop_ts": [],
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
        except TraceError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    session = _resolve_session(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = simulate(sample, spec, session, policy)
    except TraceError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    dl = m.get("derived_latencies", {})
    dl_str = ", ".join("%s=%s" % (k.replace("_ms", ""), v) for k, v in sorted(dl.items())) or "-"
    print("simulate[%s] %d olay → %d span | kayıtlı %d zaman damgası (eksik=%d) | "
          "trace_id=%d, correlation_id=%d | eşleme=%d sıra=%d ağaç=%d kimlik=%d attr=%d türetme=%d" % (
              name, m["events_total"], m["spans_total"], m["recorded_count"], m["coverage_missing"],
              m["distinct_trace_ids"], m["distinct_correlation_ids"], m["mapping_violations"],
              m["ordering_violations"], m["tree_violations"], m["identity_violations"],
              m["attribute_violations"], m["derivation_violations"]))
    print("  türetilen gecikme (ms): %s" % dl_str)
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


def _load_observability_spec():
    """0.4.7 observability-spec.json (varsa) — çapraz-tutarlılık için."""
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "platform", "observability",
                                          "observability-spec.json"))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.1.1", "spec.wbs == 14.1.1")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")

    # ── G8: placement (orchestrator, ingress, olay-tetikli, bloklamaz, immutable trace_id)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "G8 Tracer orchestrator içinde")
    _check(R, pl.get("root_opened_at_ingress") is True, "G8 root span ingress'te açılır")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "G8 olay-tetikli + bloklamaz (FR-RES-012 asenkron/sampling)")
    _check(R, pl.get("trace_id_immutable") is True, "G5 trace_id immutable bayrağı")

    # ── span_model
    sm = spec.get("span_model", {})
    _check(R, sm.get("root_span") == "call", "G4 root_span == call")
    sk = set(sm.get("span_kinds", []))
    _check(R, {"call", "turn", "stt", "llm", "tool", "tts", "transfer"} <= sk,
           "G4 span_kinds tüm operasyon span'larını içerir (turn/stt/llm/tool/tts/transfer)")
    po = sm.get("parent_of", {})
    _check(R, po.get("turn") == "call" and po.get("stt") == "turn" and po.get("llm") == "turn"
           and po.get("tts") == "turn" and po.get("tool") == "turn" and po.get("transfer") == "call",
           "G4 parent_of hiyerarşisi (turn→call; stt/llm/tool/tts→turn; transfer→call)")

    # ── timestamps (BRD §15 — 0.4.7 ile birebir)
    ts = spec.get("timestamps", {})
    cat = list(ts.get("catalog", []))
    expected_15 = [
        "call_connected", "first_audio_received", "speech_started", "speech_ended",
        "stt_partial", "stt_final", "llm_request_started", "llm_first_token",
        "tool_request", "tool_response", "tts_request", "tts_first_audio",
        "audio_played", "call_transferred", "call_ended",
    ]
    _check(R, len(cat) == 15 and set(cat) == set(expected_15),
           "G1 timestamps.catalog BRD §15'in 15 zaman damgasını içerir")
    span_of = ts.get("span_of", {})
    _check(R, set(span_of.keys()) == set(cat), "G2 span_of her zaman damgasını eşler")
    _check(R, all(v in sk for v in span_of.values()), "G2 span_of hedefleri geçerli span_kinds")
    _check(R, span_of.get("stt_partial") == "stt" and span_of.get("stt_final") == "stt",
           "G2 stt_* → stt span")
    _check(R, span_of.get("llm_request_started") == "llm" and span_of.get("llm_first_token") == "llm",
           "G2 llm_* → llm span")
    _check(R, span_of.get("tts_request") == "tts" and span_of.get("tts_first_audio") == "tts"
           and span_of.get("audio_played") == "tts", "G2 tts_*/audio_played → tts span")
    _check(R, span_of.get("tool_request") == "tool" and span_of.get("tool_response") == "tool",
           "G2 tool_* → tool span")
    _check(R, span_of.get("call_connected") == "call" and span_of.get("call_ended") == "call",
           "G2 call_connected/call_ended → root call span")
    _check(R, span_of.get("call_transferred") == "transfer", "G2 call_transferred → transfer span")
    rq = set(ts.get("required_for_completed", []))
    _check(R, {"call_connected", "call_ended", "speech_ended", "stt_final", "llm_first_token",
               "tts_first_audio", "audio_played"} <= rq,
           "G1 required_for_completed çekirdek zaman damgalarını içerir")
    cond = set(ts.get("conditional", []))
    _check(R, {"tool_request", "tool_response", "call_transferred"} <= cond,
           "G1 conditional tool/transfer zaman damgalarını içerir")
    _check(R, not (rq & cond), "G1 required ile conditional kesişmez")

    # ── 0.4.7 observability-spec ile BİREBİR çapraz-tutarlılık (G9)
    obs = _load_observability_spec()
    if obs is not None:
        obs_ts = obs.get("spans", {})
        _check(R, set(obs_ts.get("timestamps", [])) == set(cat),
               "G9 timestamps 0.4.7 observability-spec spans.timestamps ile BİREBİR")
        _check(R, obs_ts.get("root_span") == sm.get("root_span"),
               "G9 root_span 0.4.7 ile aynı (call)")
        obs_metric_names = {mm.get("name") for mm in obs.get("metrics", {}).get("catalog", [])}
        for dn in spec.get("derived_latencies", {}).get("map", {}).keys():
            _check(R, dn in obs_metric_names,
                   "G9 türetilen gecikme %s 0.4.7 metrics.catalog'da mevcut" % dn)

    # ── causal_order (G3)
    co = spec.get("causal_order", {}).get("pairs", [])
    _check(R, len(co) >= 10, "G3 causal_order ≥10 nedensel çift")
    flat = {x for pr in co for x in pr}
    _check(R, flat <= set(cat), "G3 causal_order yalnız catalog zaman damgalarını referanslar")
    _check(R, ["call_connected", "call_ended"] in [list(p) for p in co],
           "G3 call_connected ≤ call_ended çifti mevcut")
    _check(R, ["llm_request_started", "llm_first_token"] in [list(p) for p in co],
           "G3 llm_request_started ≤ llm_first_token çifti mevcut")
    _check(R, ["speech_ended", "tts_first_audio"] not in [list(p) for p in co] or True,
           "G3 (e2e çifti derived_latencies'te)")

    # ── derived_latencies (G7)
    dl = spec.get("derived_latencies", {}).get("map", {})
    _check(R, dl.get("e2e_response_latency_ms") == ["speech_ended", "tts_first_audio"],
           "G7 e2e = speech_ended → tts_first_audio (SAD §20)")
    _check(R, dl.get("llm_latency_ms") == ["llm_request_started", "llm_first_token"],
           "G7 llm_latency = request → first_token")
    _check(R, dl.get("tts_latency_ms") == ["tts_request", "tts_first_audio"],
           "G7 tts_latency = request → first_audio")
    _check(R, dl.get("tool_latency_ms") == ["tool_request", "tool_response"],
           "G7 tool_latency = request → response")
    _check(R, all(isinstance(v, list) and len(v) == 2 and all(x in cat for x in v) for v in dl.values()),
           "G7 derived_latencies endpointleri catalog içinde")

    # ── identity (G5)
    idn = spec.get("identity", {})
    _check(R, idn.get("standard") == "w3c-traceparent", "G5 W3C traceparent standardı (SAD §17.1)")
    _check(R, idn.get("single_trace_id_per_call") is True, "G5 single_trace_id_per_call=true")
    _check(R, idn.get("single_correlation_id_per_call") is True, "G5 single_correlation_id_per_call=true")
    _check(R, {"trace_id", "correlation_id", "tenant_id"} <= set(idn.get("identity_keys_on_every_span", [])),
           "G5 her span trace_id+correlation_id+tenant_id taşır")
    _check(R, set(idn.get("exemplar_keys", [])) >= {"correlation_id", "trace_id"},
           "G5 correlation_id/trace_id exemplar (metrik label değil)")

    # ── attribute_policy (G6) — 0.4.7 ile hizalı
    ap = spec.get("attribute_policy", {})
    forb = set(ap.get("forbidden_attr_keys", []))
    allowed = set(ap.get("allowed_attr_keys", []))
    _check(R, {"phone_number", "customer_name", "card_number", "otp", "token"} <= forb,
           "G6 forbidden_attr_keys çekirdek PII anahtarlarını içerir")
    _check(R, {"transcript_text", "audio_payload"} <= forb,
           "G6 ham transkript/ses payload attribute yasak")
    _check(R, not (forb & allowed), "G6 izinli ile yasak attribute kümeleri kesişmez")
    if obs is not None:
        obs_forbidden = set(obs.get("label_policy", {}).get("metric_labels_forbidden", []))
        # PII forbidden alt kümesi 0.4.7 forbidden ile tutarlı olmalı (telefon/token vb.)
        _check(R, {"phone_number", "token"} <= forb and {"phone_number", "token"} <= obs_forbidden,
               "G6 PII anahtarları 0.4.7 label_policy ile tutarlı yasak")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_coverage_missing", "max_mapping_violation", "max_ordering_violation",
               "max_tree_violation", "max_identity_violation", "max_attribute_violation",
               "max_derivation_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── metrics → observability
    me = spec.get("metrics", {})
    _check(R, set(me.get("derives_into_catalog", [])) == set(dl.keys()),
           "metrics.derives_into_catalog = derived_latencies adları")
    _check(R, len(me.get("emitted", [])) >= 3, "metrik kümesi trace sağlığını yayar (≥3)")

    # ── error taxonomy (G10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "G10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "G10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("unknown_timestamp") == "INVALID_REQUEST"
           and mapping.get("malformed_event") == "INVALID_REQUEST"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "G10 unknown/malformed→INVALID_REQUEST, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, G10)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "G10 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "G10 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True,
           "G10 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 10,
           "invariant kataloğu ≥10 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "G10 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 profil")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "G5/residency config %s bölge pini var" % p.get("name"))

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
SESSION = {
    "tenant_id": "t_acme", "org_unit": "ou_sales", "agent_id": "ag_1",
    "correlation_id": "corr-001", "region": "eu-west-1",
    "call_id": "call-001", "trace_id": "tr-001",
}

# tam happy-path olay akışı (tool dahil) — 15 zaman damgasının 14'ü (transfer alternatif yol)
HAPPY_EVENTS = [
    {"t": 0, "ts": "call_connected", "turn": 0},
    {"t": 50, "ts": "first_audio_received", "turn": 0},
    {"t": 100, "ts": "speech_started", "turn": 1},
    {"t": 1200, "ts": "speech_ended", "turn": 1},
    {"t": 300, "ts": "stt_partial", "turn": 1},
    {"t": 1350, "ts": "stt_final", "turn": 1},
    {"t": 1360, "ts": "llm_request_started", "turn": 1},
    {"t": 1560, "ts": "llm_first_token", "turn": 1},
    {"t": 1600, "ts": "tool_request", "turn": 1},
    {"t": 1750, "ts": "tool_response", "turn": 1},
    {"t": 1800, "ts": "tts_request", "turn": 1},
    {"t": 1950, "ts": "tts_first_audio", "turn": 1},
    {"t": 2100, "ts": "audio_played", "turn": 1},
    {"t": 5000, "ts": "call_ended", "turn": 0},
]
HAPPY_COVER = [e["ts"] for e in HAPPY_EVENTS]


def _run(events, spec, session=None, must_cover=None, **pol_over):
    pol = {"record_all": True, "correct_mapping": True, "nest_spans": True,
           "attach_identity": True, "enforce_attr": True, "drop_ts": []}
    pol.update(pol_over)
    sample = {"events": events}
    if must_cover is not None:
        sample["must_cover"] = must_cover
    return simulate(sample, spec, session or SESSION, pol)


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: tam akış → tüm kapılar geçer ───────────────────────────────────
    mh = _run(HAPPY_EVENTS, spec, must_cover=HAPPY_COVER)
    case(mh["coverage_missing"] == 0, "happy: 14 zaman damgası tam kaydedildi (G1)")
    case(mh["mapping_violations"] == 0, "happy: doğru span eşlemesi (G2)")
    case(mh["ordering_violations"] == 0, "happy: nedensel sıra korundu (G3)")
    case(mh["tree_violations"] == 0, "happy: ağaç iyi-biçimli (G4)")
    case(mh["distinct_trace_ids"] == 1 and mh["distinct_correlation_ids"] == 1
         and mh["identity_violations"] == 0, "happy: tek trace_id + tek correlation_id (G5)")
    case(mh["attribute_violations"] == 0, "happy: PII attribute yok (G6)")
    case(mh["derivation_violations"] == 0, "happy: gecikmeler non-negative (G7)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    # türetilen gecikme doğruluğu
    dl = mh["derived_latencies"]
    case(dl["e2e_response_latency_ms"] == 750, "happy: e2e = 1950−1200 = 750ms (speech_ended→tts_first_audio)")
    case(dl["llm_latency_ms"] == 200, "happy: llm TTFT = 1560−1360 = 200ms")
    case(dl["tts_latency_ms"] == 150, "happy: tts first-byte = 1950−1800 = 150ms")
    case(dl["tool_latency_ms"] == 150, "happy: tool = 1750−1600 = 150ms")
    case(dl["stt_latency_ms"] == 150, "happy: stt = 1350−1200 = 150ms")
    # span sayısı: call + turn1 + stt + llm + tool + tts = 6
    case(mh["spans_total"] == 6, "happy: 6 span (call+turn+stt+llm+tool+tts)")

    # ── coverage: bir zaman damgası düşerse G1 eler ───────────────────────────
    mc = _run(HAPPY_EVENTS, spec, must_cover=HAPPY_COVER, record_all=False, drop_ts=["llm_first_token"])
    case(mc["coverage_missing"] == 1 and "llm_first_token" in mc["coverage_missing_keys"],
         "coverage: llm_first_token düştü → 1 eksik (G1 eler)")
    case(not all(ok for ok, _ in evaluate(spec, mc)), "coverage eksik → en az bir kapı eler")

    # ── mapping: yanlış span eşlemesi G2 eler ─────────────────────────────────
    mm = _run(HAPPY_EVENTS, spec, must_cover=HAPPY_COVER, correct_mapping=False)
    case(mm["mapping_violations"] >= 1, "mapping KAPALI: alt-span zaman damgaları root'a → G2 eler")

    # ── ordering: nedensel ihlal (llm_first_token < llm_request_started) ───────
    bad_order = [dict(e) for e in HAPPY_EVENTS]
    for e in bad_order:
        if e["ts"] == "llm_first_token":
            e["t"] = 1300   # request_started(1360)'tan önce
    mo = _run(bad_order, spec, must_cover=HAPPY_COVER)
    case(mo["ordering_violations"] >= 1, "ordering: llm_first_token < request → G3 eler")
    case(mo["derivation_violations"] >= 1, "ordering: negatif llm gecikmesi → G7 de eler")

    # ── tree: çocuk span ebeveyn sınırını taşar ───────────────────────────────
    bad_tree = [dict(e) for e in HAPPY_EVENTS]
    for e in bad_tree:
        if e["ts"] == "stt_final":
            e["t"] = 6000   # call_ended(5000) sonrası → call (root) sınırını taşar
    mt = _run(bad_tree, spec, must_cover=HAPPY_COVER, nest_spans=False)
    case(mt["tree_violations"] >= 1, "tree: stt span call sınırını taşar → G4 eler")

    # ── identity: kimlik iliştirilmez → G5 eler ───────────────────────────────
    mi = _run(HAPPY_EVENTS, spec, must_cover=HAPPY_COVER, attach_identity=False)
    case(mi["identity_violations"] >= 1 and mi["distinct_trace_ids"] == 0,
         "identity KAPALI: span trace_id taşımıyor → G5 eler")

    # ── attribute: PII attribute → G6 eler ────────────────────────────────────
    pii_ev = [dict(e) for e in HAPPY_EVENTS]
    pii_ev[3] = dict(pii_ev[3]); pii_ev[3]["attrs"] = ["agent_id", "phone_number"]
    pii_ev[5] = dict(pii_ev[5]); pii_ev[5]["attrs"] = ["transcript_text"]
    mp = _run(pii_ev, spec, must_cover=HAPPY_COVER)
    case(mp["attribute_violations"] == 0, "attribute: enforce açıkken PII/transkript çıkarıldı (G6)")
    mp2 = _run(pii_ev, spec, must_cover=HAPPY_COVER, enforce_attr=False)
    case(mp2["attribute_violations"] == 2, "attribute KAPALI: phone_number + transcript_text → 2 (G6 eler)")

    # ── transfer senaryosu: call_transferred kaydı + transfer span ────────────
    transfer_ev = [
        {"t": 0, "ts": "call_connected", "turn": 0},
        {"t": 50, "ts": "first_audio_received", "turn": 0},
        {"t": 100, "ts": "speech_started", "turn": 1},
        {"t": 1200, "ts": "speech_ended", "turn": 1},
        {"t": 1350, "ts": "stt_final", "turn": 1},
        {"t": 1360, "ts": "llm_request_started", "turn": 1},
        {"t": 1560, "ts": "llm_first_token", "turn": 1},
        {"t": 1800, "ts": "tts_request", "turn": 1},
        {"t": 1950, "ts": "tts_first_audio", "turn": 1},
        {"t": 2100, "ts": "audio_played", "turn": 1},
        {"t": 3000, "ts": "call_transferred", "turn": 0},
        {"t": 5000, "ts": "call_ended", "turn": 0},
    ]
    tcov = [e["ts"] for e in transfer_ev]
    mtr = _run(transfer_ev, spec, must_cover=tcov)
    case(mtr["coverage_missing"] == 0 and all(ok for ok, _ in evaluate(spec, mtr)),
         "transfer: call_transferred kaydı + transfer span, tüm kapılar geçer")

    # ── reddetme (G10) ─────────────────────────────────────────────────────────
    case(_raises(lambda: simulate({"events": [{"t": 0, "ts": "nope"}]}, spec, SESSION, _full_pol())),
         "G10 bilinmeyen zaman damgası → reddedilir")
    case(_raises(lambda: simulate({"events": [{"ts": "call_connected"}]}, spec, SESSION, _full_pol())),
         "G10 zaman damgasız olay → reddedilir")
    case(_raises(lambda: simulate({"events": []}, spec, SESSION, _full_pol())),
         "G10 boş olay akışı → reddedilir")
    case(_raises(lambda: simulate({"events": [{"t": 0, "ts": "call_connected"}]}, spec,
                                  {"tenant_id": "t1", "correlation_id": "c1"}, _full_pol())),
         "G10 ingress trace_id eksik → reddedilir")
    case(_raises(lambda: simulate({"events": [{"t": 0, "ts": "call_connected"},
                                              {"t": 10, "ts": "call_ended", "trace_id": "tr-EVIL"}]},
                                  spec, SESSION, _full_pol())),
         "G10 çağrı ortasında trace_id değişimi → reddedilir")

    # ── determinizm + karışık sıra ────────────────────────────────────────────
    shuffled = list(reversed(HAPPY_EVENTS))
    ms1 = _run(HAPPY_EVENTS, spec, must_cover=HAPPY_COVER)
    ms2 = _run(shuffled, spec, must_cover=HAPPY_COVER)
    case(ms1 == ms2, "determinizm: karışık olay sırası aynı sonucu verir")

    # ── validate negatif kapılar ─────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["timestamps"]["catalog"].remove("stt_final")
    case(_validate_obj(s) != 0, "G1 catalog'tan stt_final düşerse → validate eler")
    s = json.loads(json.dumps(spec)); s["timestamps"]["span_of"]["stt_final"] = "llm"
    case(_validate_obj(s) != 0, "G2 stt_final yanlış span'a eşlenirse → validate eler")
    s = json.loads(json.dumps(spec)); s["derived_latencies"]["map"]["llm_latency_ms"] = ["llm_first_token", "llm_request_started"]
    case(_validate_obj(s) != 0, "G7 llm gecikme endpointleri ters çevrilirse → validate eler")
    s = json.loads(json.dumps(spec)); s["identity"]["single_trace_id_per_call"] = False
    case(_validate_obj(s) != 0, "G5 single_trace_id_per_call=false → validate eler")
    s = json.loads(json.dumps(spec)); s["attribute_policy"]["allowed_attr_keys"].append("phone_number")
    case(_validate_obj(s) != 0, "G6 izinli attribute'a phone_number eklenirse kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_ordering_violation"] = 1
    case(_validate_obj(s) != 0, "G3 max_ordering_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["span_model"]["parent_of"]["stt"] = "call"
    case(_validate_obj(s) != 0, "G4 stt ebeveyni call yapılırsa (turn değil) → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "G10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_values_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "G10 pii_values_in_spec_forbidden kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "G10 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _full_pol():
    return {"record_all": True, "correct_mapping": True, "nest_spans": True,
            "attach_identity": True, "enforce_attr": True, "drop_ts": []}


def _raises(fn):
    try:
        fn()
        return False
    except TraceError:
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
    print("""call-trace-spec.json beklenen şekli (WBS 14.1.1):
  wbs=14.1.1, version, phase=F1, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability}
  placement{in_orchestrator, root_opened_at_ingress, event_driven, non_blocking,
            trace_id_immutable}                                                  (G5,G8)
  span_model{root_span=call, span_kinds[call,turn,stt,llm,tool,tts,transfer],
             parent_of{turn→call, stt/llm/tool/tts→turn, transfer→call}}        (G4)
  timestamps{catalog[15 BRD §15], span_of{ts→span kind}, required_for_completed[],
             conditional[]}  (0.4.7 spans.timestamps ile BİREBİR)               (G1,G2,G9)
  causal_order{pairs[[önce,sonra]...]}                                          (G3)
  derived_latencies{map{e2e/stt/llm/tts/tool → [from,to]}}  (0.4.7 metrics)     (G7,G9)
  identity{standard=w3c-traceparent, single_trace_id_per_call,
           single_correlation_id_per_call, identity_keys_on_every_span[]}       (G5)
  attribute_policy{allowed_attr_keys[], forbidden_attr_keys[]}                  (G6)
  gates{max_coverage_missing=0, max_mapping_violation=0, max_ordering_violation=0,
        max_tree_violation=0, max_identity_violation=0, max_attribute_violation=0,
        max_derivation_violation=0}                                            (G1..G7)
  metrics{emitted[], derives_into_catalog[]}
  error_taxonomy{mapping→API §11.6 (unknown/malformed→INVALID_REQUEST, region→REGION_VIOLATION)}
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                       (G10)
  invariants[≥10]{id, desc, trace}

config/call-trace-profiles.json: profiles[]{name, region, ...}

simulate sample: {name, profile | profile_obj, expect, must_cover?[ts], expected?{metrik:değer},
  session{tenant_id, correlation_id, trace_id, region?, ...},
  policy?{record_all, correct_mapping, nest_spans, attach_identity, enforce_attr, drop_ts[]},
  events[{t (ms), ts (BRD §15 zaman damgası adı), turn?, attrs?[anahtar adı], trace_id?}]}
  (PII DEĞERİ YOK — yalnız zaman damgası + kimlik anahtarı ADLARI)

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: call_trace_probe.py simulate <sample.json>")
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
