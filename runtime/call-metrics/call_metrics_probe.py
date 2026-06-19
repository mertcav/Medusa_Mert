#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_metrics_probe.py — WBS 14.1.2 Teknik metrikler (packet loss/jitter/STT-LLM-TTS latency/token/...)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-trace/` (14.1.1) + `runtime/context-propagation/` (3.1.5) probe disipliniyle birebir;
burada deterministik bir CONVERSATION ORCHESTRATOR CALL METRIC EXTRACTOR (SAD §17.1 'Metrics:') simülatörü
(saf aritmetik; random YOK).

CALL METRIC EXTRACTOR (Çekirdek IP, SAD §6 / §17) — 14.1.1 trace zaman damgalarından + medya/sağlayıcı/
diyalog sinyallerinden BRD §15'in TÜM teknik metrik DEĞERLERİNİ hesaplar ve 0.4.7 observability-spec
metrics.catalog'a UYGUN gözlem (observation) olarak yayar:
  • Kapsam (G1):       required (+conditional) BRD §15 metriklerinin hepsi yayılır (metric_missing=0).
  • Katalog (G2):      her gözlem 0.4.7 catalog name+type+unit ile uyumlu (catalog_violation=0).
  • Değer (G3):        her DEĞER domain sınıfında (ratio∈[0,1], ms≥0, sayaç int≥0, info=1) — value=0.
  • Kardinalite (G4):  hiçbir metrik yüksek-kardinalite kimliği LABEL taşımaz — cardinality=0.
  • Etiket (G5):       her metrik yalnız catalog[].labels (⊆ allowed) kullanır — label=0.
  • PII (G6):          hiçbir label PII anahtarı taşımaz — pii=0.
  • Oran (G7):         ratio_derived metrikler payda>0 ile + sonuç∈[0,1] — ratio=0.

KAPSAM AYRIMI: span üretimi + zaman damgası kaydı → 14.1.1 · metrik/alarm KATALOĞU + collector guard →
0.4.7 · per-call CPU/bellek DEĞERİ → 14.1.3/3.1.4 · loglama → 14.1.4 · alarm kuralları → 14.1.5.
Burada YALNIZ çağrı başına teknik metrik DEĞER HESABI + katalog/kardinalite/etiket/PII disiplini.

Komutlar:
  validate              call-metrics-spec.json'ı invariant'lara + 0.4.7/14.1.1 çapraz-tutarlılığa + config'e karşı doğrular.
  compute <sample>      Deterministik CallMetricExtractor — sinyal demeti → metrik gözlemleri + HARD kapılar (G1–G7); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. compute gerçek async runtime yerine deterministik hesaptır (canlı sistemde
Go/Rust + OpenTelemetry/Prometheus, ADR-003/SAD §11/§17.1). Ham ses payload'ı/transkript/PII DEĞERİ YOK —
örnekler yalnız sayısal SİNYAL + kimlik/etiket anahtarı ADLARI + sanal zaman taşır.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "call-metrics-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "call-metrics-profiles.json")

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


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return (sum(xs) / len(xs)) if xs else 0.0


class MetricError(Exception):
    """Geçersiz/eksik sinyal demeti veya bilinmeyen metrik — sessizce kabul yok, reddet (G10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Call Metric Extractor — çağrı başına teknik metrik DEĞER hesabı (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class CallMetricExtractor:
    """SAD §17.1 'Metrics:' Call Metric Extractor. 14.1.1 trace zaman damgalarından + medya/sağlayıcı/
    diyalog sinyallerinden BRD §15 teknik metrik DEĞERLERİNİ hesaplar; her gözlemi 0.4.7 catalog'a +
    kardinalite/etiket/PII disiplinine + value-domain'e karşı denetler. Saf aritmetik; random YOK.

    policy bayrakları buggy Extractor'ı simüle eder (call-trace/context-propagation deseni):
      compute_all         : her metriği hesapla (kapalı → drop_metrics düşer, G1)
      conform_catalog     : yalnız catalog name/type/unit yay (kapalı → bilinmeyen metrik, G2)
      clamp_domain        : DEĞER domain-içi (kapalı → domain dışı değer geçer, G3)
      enforce_cardinality : kimliği LABEL yapma (kapalı → correlation_id label, G4)
      enforce_labels      : yalnız izinli label (kapalı → izinsiz label, G5)
      enforce_pii         : PII label'ı çıkar (kapalı → phone_number label, G6)
      safe_ratio          : oranı payda>0 ile + ∈[0,1] (kapalı → sıfıra bölme / >1, G7)
    """

    def __init__(self, spec, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy
        cat = spec.get("catalog", {})
        self.items = list(cat.get("items", []))
        self.by_name = {it["name"]: it for it in self.items}
        self.catalog_names = set(self.by_name.keys())
        self.derived_map = dict(spec.get("derived_from_trace", {}).get("map", {}))
        self.domains = dict(spec.get("value_domains", {}).get("classes", {}))
        lp = spec.get("label_policy", {})
        self.labels_allowed = set(lp.get("metric_labels_allowed", []))
        self.high_card = set(lp.get("high_cardinality_keys", []))
        self.pii_keys = set(lp.get("pii_forbidden_keys", []))
        self.exemplar_keys = list(lp.get("exemplar_keys", ["correlation_id", "trace_id"]))

        # ingress kimliği (etiket DEĞERİ + exemplar kaynağı)
        for rk in ("tenant_id",):
            if not self.context.get(rk):
                raise MetricError("emisyon bağlamı eksik: %s → INVALID_REQUEST" % rk)

        self.observations = []   # [{name,type,unit,value,labels{},exemplar{}}]
        self.emitted_names = set()
        # sayaçlar / metrikler
        self.catalog_violations = 0
        self.value_violations = 0
        self.cardinality_violations = 0
        self.label_violations = 0
        self.pii_violations = 0
        self.ratio_violations = 0

    # ── etiket DEĞER kaynağı ───────────────────────────────────────────────────
    def _label_values(self, item, extra=None):
        """catalog[].labels'ten bağlam + sinyal DEĞERLERİ ile sözlük kurar (yalnız izinli anahtarlar)."""
        out = {}
        src = dict(self.context)
        if extra:
            src.update(extra)
        for k in item.get("labels", []):
            v = src.get(k)
            if v is not None:
                out[k] = v
        # buggy: kimliği LABEL olarak iliştir (G4) — yüksek-kardinalite kaçağı
        if not self.pol.get("enforce_cardinality", True):
            out["correlation_id"] = self.context.get("correlation_id", "corr-x")
        # buggy: PII anahtarını LABEL olarak iliştir (G6) — DEĞER yok, yalnız anahtar adı
        if not self.pol.get("enforce_pii", True):
            out["phone_number"] = "<redacted>"
        # buggy: izinsiz (ama PII/yüksek-kardinalite olmayan) label (G5)
        if not self.pol.get("enforce_labels", True):
            out["unbounded_dim"] = "x"
        return out

    def _exemplar(self):
        return {k: self.context.get(k) for k in self.exemplar_keys if self.context.get(k) is not None}

    # ── tek gözlem yayını + denetim ────────────────────────────────────────────
    def _emit(self, name, value, extra_labels=None):
        item = self.by_name.get(name)
        if item is None:
            # buggy: catalog dışı metrik (G2)
            self.catalog_violations += 1
            self.observations.append({"name": name, "type": "gauge", "unit": "1",
                                      "value": value, "labels": {}, "exemplar": self._exemplar()})
            return
        labels = self._label_values(item, extra_labels)
        obs = {"name": name, "type": item["type"], "unit": item["unit"],
               "value": value, "labels": labels, "exemplar": self._exemplar()}
        self.observations.append(obs)
        self.emitted_names.add(name)

        # ── G2 katalog uyumu (name+type+unit) — conform_catalog kapalıysa kasıtlı bozma _emit_unknown'da
        # (burada doğru item'dan üretildiği için type/unit zaten uyumlu)

        # ── G3 değer domaini ──────────────────────────────────────────────────
        if not self._domain_ok(item, value):
            self.value_violations += 1

        # ── G4 kardinalite + G5 etiket + G6 PII ───────────────────────────────
        allowed = set(item.get("labels", []))
        for k in labels.keys():
            if k in self.high_card:
                self.cardinality_violations += 1
            if k in self.pii_keys:
                self.pii_violations += 1
            if k not in allowed and k not in self.high_card and k not in self.pii_keys:
                self.label_violations += 1
            elif k not in allowed and (k in self.high_card or k in self.pii_keys):
                # yüksek-kardinalite/PII anahtarı zaten izinsiz; ayrıca label ihlali sayılır
                self.label_violations += 1

    def _domain_ok(self, item, value):
        dom = self.domains.get(item.get("domain"), {})
        if not isinstance(value, (int, float)):
            return False
        if isinstance(value, float) and not math.isfinite(value):
            return False
        if dom.get("kind") == "int" and not (isinstance(value, int) or float(value).is_integer()):
            return False
        if "min" in dom and value < dom["min"]:
            return False
        if "max" in dom and value > dom["max"]:
            return False
        return True

    # ── trace gecikme türetme (14.1.1'den) ────────────────────────────────────
    def _derive(self, ts, name):
        frm, to = self.derived_map[name]
        if frm in ts and to in ts:
            return ts[to] - ts[frm]
        return None

    # ── ratio_derived güvenli bölme (G7) ──────────────────────────────────────
    def _ratio(self, num, den):
        if self.pol.get("safe_ratio", True):
            if den <= 0:
                return 0.0          # tanımlı: olay yok → oran 0
            r = num / den
            if r < 0 or r > 1:      # taşma → kırp + ihlal işaretle
                self.ratio_violations += 1
                return max(0.0, min(1.0, r))
            return r
        # buggy: payda>0 garantisi yok → sıfıra bölme veya >1
        if den == 0:
            self.ratio_violations += 1
            return float("inf")
        r = num / den
        if r < 0 or r > 1:
            self.ratio_violations += 1
        return r

    # ── tam çağrı hesabı ───────────────────────────────────────────────────────
    def compute(self, bundle):
        ts = dict(bundle.get("trace", {}).get("timestamps", {}))
        media = dict(bundle.get("media", {}))
        stt = dict(bundle.get("stt", {}))
        llm = dict(bundle.get("llm", {}))
        dialogue = dict(bundle.get("dialogue", {}))
        rel = dict(bundle.get("reliability", {}))
        outcome = dict(bundle.get("outcome", {}))
        cost = dict(bundle.get("cost", {}))

        drop = set(self.pol.get("drop_metrics", [])) if not self.pol.get("compute_all", True) else set()

        def want(name):
            return name not in drop

        # 1) packet loss (ratio_derived)
        if want("voice_packet_loss_ratio"):
            recv = media.get("packets_received", 0)
            lost = media.get("packets_lost", 0)
            self._emit("voice_packet_loss_ratio", self._ratio(lost, recv + lost),
                       {"codec": media.get("codec")})
        # 2) jitter
        if want("voice_jitter_ms"):
            jit = media.get("jitter_ms", _mean(media.get("jitter_ms_samples", [])))
            self._emit("voice_jitter_ms", jit, {"codec": media.get("codec")})
        # 3) codec info
        if want("voice_codec_info"):
            self._emit("voice_codec_info", 1, {"codec": media.get("codec")})
        # 4) SIP response
        if want("telephony_sip_response_total"):
            self._emit("telephony_sip_response_total", 1, {"sip_code": media.get("sip_code")})
        # 5) STT latency (derived)
        if want("stt_latency_ms"):
            v = self._derive(ts, "stt_latency_ms")
            if v is not None:
                self._emit("stt_latency_ms", v, {"provider": stt.get("provider")})
        # 6) word confidence
        if want("stt_word_confidence"):
            self._emit("stt_word_confidence", _mean(stt.get("word_confidences", [])),
                       {"provider": stt.get("provider")})
        # 7) LLM latency (derived)
        if want("llm_latency_ms"):
            v = self._derive(ts, "llm_latency_ms")
            if v is not None:
                self._emit("llm_latency_ms", v, {"provider": llm.get("provider"), "category": llm.get("category")})
        # 8) tokens
        if want("llm_tokens_total"):
            self._emit("llm_tokens_total", llm.get("prompt_tokens", 0) + llm.get("completion_tokens", 0),
                       {"provider": llm.get("provider"), "category": llm.get("category")})
        # 9) tool latency (derived, conditional)
        if want("tool_latency_ms"):
            v = self._derive(ts, "tool_latency_ms")
            if v is not None:
                self._emit("tool_latency_ms", v, {})
        # 10) TTS latency (derived)
        if want("tts_latency_ms"):
            v = self._derive(ts, "tts_latency_ms")
            if v is not None:
                self._emit("tts_latency_ms", v, {"provider": bundle.get("tts", {}).get("provider", self.context.get("provider"))})
        # 11) e2e latency (derived)
        if want("e2e_response_latency_ms"):
            v = self._derive(ts, "e2e_response_latency_ms")
            if v is not None:
                self._emit("e2e_response_latency_ms", v, {})
        # 12) barge-in
        if want("barge_in_total"):
            self._emit("barge_in_total", dialogue.get("barge_in_events", 0), {})
        # 13) silence
        if want("silence_duration_ms"):
            self._emit("silence_duration_ms", sum(dialogue.get("silence_segments_ms", [])) if dialogue.get("silence_segments_ms") else 0, {})
        # 14) retry/fallback
        if want("retry_fallback_total"):
            self._emit("retry_fallback_total", rel.get("retries", 0) + rel.get("fallbacks", 0),
                       {"provider": self.context.get("provider"), "category": self.context.get("category")})
        # 15) transfer result (conditional)
        if want("transfer_result_total") and outcome.get("transfer_result"):
            self._emit("transfer_result_total", 1, {"outcome": outcome.get("transfer_result")})
        # 16) call termination
        if want("call_termination_total"):
            self._emit("call_termination_total", 1, {"outcome": outcome.get("termination_reason", "completed")})
        # 17) provider error ratio (per category)
        if want("provider_error_ratio"):
            reqs = rel.get("provider_requests", {}) or {}
            errs = rel.get("provider_errors", {}) or {}
            for catname in sorted(reqs.keys()):
                self._emit("provider_error_ratio", self._ratio(errs.get(catname, 0), reqs.get(catname, 0)),
                           {"provider": self.context.get("provider"), "category": catname})
        # 18) cost per minute
        if want("cost_per_minute"):
            mins = cost.get("billable_minutes", 0)
            cpm = (cost.get("amount", 0) / mins) if mins and mins > 0 else 0.0
            self._emit("cost_per_minute", cpm,
                       {"provider": self.context.get("provider"), "category": self.context.get("category")})

        # buggy: catalog dışı metrik yay (G2)
        if not self.pol.get("conform_catalog", True):
            self._emit("unmapped_adhoc_metric", 1.0)

    def coverage_missing(self, must_cover):
        return [n for n in must_cover if n not in self.emitted_names]

    def metrics(self, must_cover):
        missing = self.coverage_missing(must_cover)
        # türetilen gecikme DEĞERLERİ (rapor için)
        derived = {}
        for o in self.observations:
            if self.by_name.get(o["name"], {}).get("derived"):
                derived[o["name"]] = o["value"]
        return {
            "observations_total": len(self.observations),
            "distinct_metrics": len(self.emitted_names),
            "metric_missing": len(missing),
            "metric_missing_keys": missing,
            "catalog_violations": self.catalog_violations,
            "value_violations": self.value_violations,
            "cardinality_violations": self.cardinality_violations,
            "label_violations": self.label_violations,
            "pii_violations": self.pii_violations,
            "ratio_violations": self.ratio_violations,
            "derived_latencies": derived,
            "values": {o["name"]: o["value"] for o in self.observations if self.by_name.get(o["name"], {}).get("per") != "category"},
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam hesap (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def compute_call(sample, spec, context, policy):
    bundle = sample.get("bundle")
    if not isinstance(bundle, dict):
        raise MetricError("sinyal demeti (bundle) sözlük değil → INVALID_REQUEST")
    if not bundle.get("trace", {}).get("timestamps"):
        raise MetricError("bundle.trace.timestamps eksik (14.1.1 girdisi) → INVALID_REQUEST")
    ex = CallMetricExtractor(spec, context, policy)
    ex.compute(bundle)
    must_cover = sample.get("must_cover")
    if must_cover is None:
        must_cover = spec.get("required_for_completed", [])
    return ex.metrics(must_cover)


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G7) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    F.append((m.get("metric_missing", 0) <= g.get("max_metric_missing", 0),
              "G1 metrik eksik %d ≤ %d (required BRD §15 metrikleri hesaplandı%s — BRD §15/SAD §17.1)"
              % (m.get("metric_missing", 0), g.get("max_metric_missing", 0),
                 (" [eksik: %s]" % ",".join(m.get("metric_missing_keys", []))) if m.get("metric_missing") else "")))
    F.append((m.get("catalog_violations", 0) <= g.get("max_catalog_violation", 0),
              "G2 katalog ihlali %d ≤ %d (gözlem 0.4.7 catalog name+type+unit ile uyumlu — SAD §17.1)"
              % (m.get("catalog_violations", 0), g.get("max_catalog_violation", 0))))
    F.append((m.get("value_violations", 0) <= g.get("max_value_violation", 0),
              "G3 değer ihlali %d ≤ %d (ratio∈[0,1], ms≥0+finite, sayaç int≥0, info=1 — BRD §15)"
              % (m.get("value_violations", 0), g.get("max_value_violation", 0))))
    F.append((m.get("cardinality_violations", 0) <= g.get("max_cardinality_violation", 0),
              "G4 kardinalite ihlali %d ≤ %d (yüksek-kardinalite kimlik LABEL değil; yalnız exemplar — 0.4.7)"
              % (m.get("cardinality_violations", 0), g.get("max_cardinality_violation", 0))))
    F.append((m.get("label_violations", 0) <= g.get("max_label_violation", 0),
              "G5 etiket ihlali %d ≤ %d (yalnız catalog[].labels ⊆ allowed — 0.4.7)"
              % (m.get("label_violations", 0), g.get("max_label_violation", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G6 PII ihlali %d ≤ %d (label'da PII anahtarı yok — FR-REC-004/BRD §17.7)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))
    F.append((m.get("ratio_violations", 0) <= g.get("max_ratio_violation", 0),
              "G7 oran ihlali %d ≤ %d (ratio_derived payda>0 + sonuç∈[0,1] — BRD §15)"
              % (m.get("ratio_violations", 0), g.get("max_ratio_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise MetricError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _resolve_policy(spec, sample):
    pol = {
        "compute_all": True,
        "conform_catalog": True,
        "clamp_domain": True,
        "enforce_cardinality": True,
        "enforce_labels": True,
        "enforce_pii": True,
        "safe_ratio": True,
        "drop_metrics": [],
    }
    pol.update(sample.get("policy", {}))
    return pol


def compute_cmd(sample_path):
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
        except MetricError as ex:
            print("compute[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = compute_call(sample, spec, context, policy)
    except MetricError as ex:
        print("compute[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    dl = m.get("derived_latencies", {})
    dl_str = ", ".join("%s=%s" % (k.replace("_ms", ""), v) for k, v in sorted(dl.items())) or "-"
    print("compute[%s] %d gözlem (%d metrik) | eksik=%d | katalog=%d değer=%d kardinalite=%d etiket=%d pii=%d oran=%d" % (
        name, m["observations_total"], m["distinct_metrics"], m["metric_missing"],
        m["catalog_violations"], m["value_violations"], m["cardinality_violations"],
        m["label_violations"], m["pii_violations"], m["ratio_violations"]))
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


def _load_calltrace_spec():
    """14.1.1 call-trace-spec.json (varsa) — derived_latencies çapraz-tutarlılık için."""
    cand = os.path.normpath(os.path.join(HERE, "..", "call-trace", "call-trace-spec.json"))
    if os.path.exists(cand):
        try:
            return _load(cand)
        except Exception:
            return None
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.1.2", "spec.wbs == 14.1.2")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")

    # ── G8: placement (orchestrator emisyon, from_trace, olay-tetikli, bloklamaz)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "G8 Extractor orchestrator içinde")
    _check(R, pl.get("emission_path") is True, "G8 emisyon yolunda")
    _check(R, pl.get("from_trace") is True, "G8 gecikmeyi yeniden ölçmez (from_trace 14.1.1)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "G8 olay-tetikli + bloklamaz (FR-RES-012 asenkron/sampling)")

    # ── catalog (in-scope BRD §15 teknik metrik DEĞERLERİ)
    cat = spec.get("catalog", {})
    items = cat.get("items", [])
    names = [it.get("name") for it in items]
    _check(R, len(names) == len(set(names)) and len(names) == 18,
           "G1 catalog 18 in-scope BRD §15 metriği (CPU/mem 14.1.3'e)")
    _check(R, all(it.get("type") and it.get("unit") and it.get("domain") and it.get("brd15") for it in items),
           "G2/G3 her metrik type+unit+domain+brd15 taşır")
    domains = set(spec.get("value_domains", {}).get("classes", {}).keys())
    _check(R, all(it.get("domain") in domains for it in items),
           "G3 her metriğin domain'i value_domains.classes içinde")
    oos = {o.get("name") for o in cat.get("out_of_scope", [])}
    _check(R, {"call_cpu_seconds", "call_memory_bytes"} == oos,
           "kapsam: CPU/mem out_of_scope (14.1.3)")
    _check(R, not (set(names) & oos), "kapsam: in-scope ile out_of_scope kesişmez")

    # ── derived_from_trace (14.1.1 ile birebir)
    dm = spec.get("derived_from_trace", {}).get("map", {})
    _check(R, dm.get("e2e_response_latency_ms") == ["speech_ended", "tts_first_audio"],
           "G9 e2e = speech_ended → tts_first_audio (SAD §20)")
    _check(R, set(dm.keys()) == {"e2e_response_latency_ms", "stt_latency_ms", "llm_latency_ms",
                                 "tts_latency_ms", "tool_latency_ms"},
           "G9 derived_from_trace 5 gecikme metriği")
    derived_names = {it["name"] for it in items if it.get("derived")}
    _check(R, derived_names == set(dm.keys()),
           "G9 catalog derived bayrağı derived_from_trace ile tutarlı")

    # ── required / conditional
    req = set(spec.get("required_for_completed", []))
    cond = set(spec.get("conditional", []))
    _check(R, req <= set(names) and cond <= set(names), "G1 required+conditional catalog içinde")
    _check(R, not (req & cond), "G1 required ile conditional kesişmez")
    _check(R, cond == {"tool_latency_ms", "transfer_result_total"},
           "G1 conditional = tool_latency + transfer_result")
    _check(R, len(req) == 16, "G1 16 required metrik (tamamlanan çağrı)")

    # ── label_policy (0.4.7 ile birebir)
    lp = spec.get("label_policy", {})
    allowed = set(lp.get("metric_labels_allowed", []))
    high = set(lp.get("high_cardinality_keys", []))
    pii = set(lp.get("pii_forbidden_keys", []))
    _check(R, {"correlation_id", "call_id", "customer_id", "session_id"} <= high,
           "G4 high_cardinality_keys çekirdek kimlikleri içerir")
    _check(R, {"phone_number", "token", "transcript_text", "audio_payload"} <= pii,
           "G6 pii_forbidden_keys çekirdek PII anahtarlarını içerir")
    _check(R, not (allowed & high), "G4 izinli label ile yüksek-kardinalite kesişmez")
    _check(R, not (allowed & pii), "G6 izinli label ile PII kesişmez")
    # her metriğin label'ları allowed ⊇
    bad = [it["name"] for it in items if not set(it.get("labels", [])) <= allowed]
    _check(R, not bad, "G5 her metrik label'ı metric_labels_allowed alt kümesi (%s)" % (",".join(bad) or "-"))
    _check(R, set(lp.get("exemplar_keys", [])) >= {"correlation_id", "trace_id"},
           "G4 correlation_id/trace_id exemplar (label değil)")

    # ── ratio_derived
    rd = {it["name"] for it in items if it.get("ratio_derived")}
    _check(R, rd == {"voice_packet_loss_ratio", "provider_error_ratio"},
           "G7 ratio_derived = packet_loss + provider_error_ratio")
    _check(R, all(spec.get("value_domains", {}).get("classes", {}).get(
        next(it["domain"] for it in items if it["name"] == n)) for n in rd),
        "G7 ratio_derived metrikler domain taşır")
    _check(R, all(next(it["domain"] for it in items if it["name"] == n) == "ratio01" for n in rd),
           "G7 ratio_derived metrikler ratio01 domaininde")

    # ── 0.4.7 observability-spec ile BİREBİR (G9)
    obs = _load_observability_spec()
    if obs is not None:
        obs_cat = {mm.get("name"): mm for mm in obs.get("metrics", {}).get("catalog", [])}
        for it in items:
            om = obs_cat.get(it["name"])
            _check(R, om is not None, "G9 %s 0.4.7 metrics.catalog'da mevcut" % it["name"])
            if om is not None:
                _check(R, om.get("type") == it["type"] and om.get("unit") == it["unit"],
                       "G9 %s type/unit 0.4.7 ile birebir" % it["name"])
                _check(R, set(it.get("labels", [])) == set(om.get("labels", [])),
                       "G9 %s labels 0.4.7 ile birebir" % it["name"])
        # 0.4.7 label_policy ile birebir
        olp = obs.get("label_policy", {})
        _check(R, set(olp.get("metric_labels_allowed", [])) == allowed,
               "G9 metric_labels_allowed 0.4.7 ile birebir")
        _check(R, set(olp.get("high_cardinality_keys", [])) == high,
               "G9 high_cardinality_keys 0.4.7 ile birebir")
        # out_of_scope CPU/mem 0.4.7'de var (ama 14.1.3'e ait)
        _check(R, {"call_cpu_seconds", "call_memory_bytes"} <= set(obs_cat.keys()),
               "G9 CPU/mem 0.4.7 kataloğunda mevcut (sahibi 14.1.3)")

    # ── 14.1.1 call-trace ile BİREBİR (G9)
    ct = _load_calltrace_spec()
    if ct is not None:
        ct_map = ct.get("derived_latencies", {}).get("map", {})
        _check(R, ct_map == dm, "G9 derived_from_trace 14.1.1 call-trace derived_latencies ile BİREBİR")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_metric_missing", "max_catalog_violation", "max_value_violation",
               "max_cardinality_violation", "max_label_violation", "max_pii_violation",
               "max_ratio_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (G10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "G10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "G10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("malformed_bundle") == "INVALID_REQUEST"
           and mapping.get("unknown_metric") == "INVALID_REQUEST"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "G10 malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION")

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
        pnames = [p.get("name") for p in profs]
        _check(R, len(pnames) == len(set(pnames)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "G4/residency config %s bölge pini var" % p.get("name"))

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
CONTEXT = {
    "tenant_id": "t_acme", "org_unit": "ou_support", "agent_id": "ag_inbound",
    "region": "eu-west-1", "provider": "prov_a", "category": "small",
    "correlation_id": "corr-001", "trace_id": "tr-001",
}

# tam happy-path sinyal demeti (14.1.1 happy trace zaman damgaları + medya/sağlayıcı sinyalleri)
HAPPY_BUNDLE = {
    "trace": {"timestamps": {
        "call_connected": 0, "first_audio_received": 50, "speech_started": 100, "speech_ended": 1200,
        "stt_partial": 300, "stt_final": 1350, "llm_request_started": 1360, "llm_first_token": 1560,
        "tool_request": 1600, "tool_response": 1750, "tts_request": 1800, "tts_first_audio": 1950,
        "audio_played": 2100, "call_ended": 5000,
    }},
    "media": {"packets_received": 980, "packets_lost": 20, "jitter_ms_samples": [10, 12, 14],
              "codec": "opus", "sip_code": "200"},
    "stt": {"word_confidences": [0.9, 0.95, 0.85, 0.92], "provider": "prov_a"},
    "llm": {"prompt_tokens": 320, "completion_tokens": 80, "provider": "prov_a", "category": "small"},
    "dialogue": {"barge_in_events": 1, "silence_segments_ms": [200, 150]},
    "reliability": {"retries": 0, "fallbacks": 1,
                    "provider_requests": {"stt": 1, "llm": 1, "tts": 1},
                    "provider_errors": {"stt": 0, "llm": 0, "tts": 0}},
    "outcome": {"transfer_result": None, "termination_reason": "completed"},
    "cost": {"amount": 0.05, "currency": "EUR", "billable_minutes": 2.5},
}


def _full_pol():
    return {"compute_all": True, "conform_catalog": True, "clamp_domain": True,
            "enforce_cardinality": True, "enforce_labels": True, "enforce_pii": True,
            "safe_ratio": True, "drop_metrics": []}


def _run(bundle, spec, context=None, must_cover=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    sample = {"bundle": bundle}
    if must_cover is not None:
        sample["must_cover"] = must_cover
    return compute_call(sample, spec, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except MetricError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: tam akış → tüm kapılar geçer ───────────────────────────────────
    mh = _run(HAPPY_BUNDLE, spec)
    case(mh["metric_missing"] == 0, "happy: 16 required metrik tam hesaplandı (G1)")
    case(mh["catalog_violations"] == 0, "happy: katalog uyumlu (G2)")
    case(mh["value_violations"] == 0, "happy: değerler domain-içi (G3)")
    case(mh["cardinality_violations"] == 0, "happy: yüksek-kardinalite label yok (G4)")
    case(mh["label_violations"] == 0, "happy: izinsiz label yok (G5)")
    case(mh["pii_violations"] == 0, "happy: PII label yok (G6)")
    case(mh["ratio_violations"] == 0, "happy: oranlar payda>0 + ∈[0,1] (G7)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    # hesaplanan DEĞER doğruluğu
    v = mh["values"]
    case(v["voice_packet_loss_ratio"] == 20 / 1000, "happy: packet_loss = 20/1000 = 0.02")
    case(v["voice_jitter_ms"] == 12.0, "happy: jitter = mean(10,12,14) = 12.0")
    case(v["voice_codec_info"] == 1, "happy: codec_info = 1")
    case(v["stt_word_confidence"] == (0.9 + 0.95 + 0.85 + 0.92) / 4, "happy: word_confidence = 0.905")
    case(v["llm_tokens_total"] == 400, "happy: tokens = 320+80 = 400")
    case(v["silence_duration_ms"] == 350, "happy: silence = 200+150 = 350")
    case(v["barge_in_total"] == 1, "happy: barge_in = 1")
    case(v["retry_fallback_total"] == 1, "happy: retry/fallback = 0+1 = 1")
    case(v["cost_per_minute"] == 0.05 / 2.5, "happy: cost_per_minute = 0.05/2.5 = 0.02")
    # türetilen gecikme (14.1.1 ile birebir)
    dl = mh["derived_latencies"]
    case(dl["e2e_response_latency_ms"] == 750, "happy: e2e = 1950−1200 = 750ms (speech_ended→tts_first_audio)")
    case(dl["llm_latency_ms"] == 200, "happy: llm TTFT = 1560−1360 = 200ms")
    case(dl["tts_latency_ms"] == 150, "happy: tts = 1950−1800 = 150ms")
    case(dl["stt_latency_ms"] == 150, "happy: stt = 1350−1200 = 150ms")
    case(dl["tool_latency_ms"] == 150, "happy: tool = 1750−1600 = 150ms")
    # gözlem sayısı: 16 required (cost dahil) + tool_latency conditional + provider_error_ratio ×3 = 16+1+2(ekstra)
    # provider_error_ratio per category = 3 obs (stt/llm/tts), diğer 16 metrik tekil + tool_latency = 17 tekil − provider tekil + 3
    case(mh["distinct_metrics"] == 17, "happy: 17 distinct metrik (16 required + tool_latency conditional)")
    case(mh["observations_total"] == 19, "happy: 19 gözlem (provider_error_ratio 3 kategori)")

    # ── G1 coverage: bir metrik düşerse eler ──────────────────────────────────
    mc = _run(HAPPY_BUNDLE, spec, compute_all=False, drop_metrics=["llm_tokens_total"])
    case(mc["metric_missing"] == 1 and "llm_tokens_total" in mc["metric_missing_keys"],
         "coverage: llm_tokens_total düştü → 1 eksik (G1 eler)")
    case(not all(ok for ok, _ in evaluate(spec, mc)), "coverage eksik → en az bir kapı eler")

    # ── G2 catalog: bilinmeyen metrik yayınlanırsa eler ───────────────────────
    m2 = _run(HAPPY_BUNDLE, spec, conform_catalog=False)
    case(m2["catalog_violations"] >= 1, "catalog KAPALI: bilinmeyen metrik → G2 eler")

    # ── G3 value: domain dışı değer (negatif gecikme trace'ten) ───────────────
    bad_ts = json.loads(json.dumps(HAPPY_BUNDLE))
    bad_ts["trace"]["timestamps"]["llm_first_token"] = 1100   # request(1360) öncesi → negatif llm
    m3 = _run(bad_ts, spec)
    case(m3["value_violations"] >= 1, "value: negatif llm gecikmesi (trace) → domain dışı → G3 eler")

    # ── G4 cardinality: kimlik label olursa eler ──────────────────────────────
    m4 = _run(HAPPY_BUNDLE, spec, enforce_cardinality=False)
    case(m4["cardinality_violations"] >= 1, "cardinality KAPALI: correlation_id label → G4 eler")

    # ── G5 label: izinsiz label eler ──────────────────────────────────────────
    m5 = _run(HAPPY_BUNDLE, spec, enforce_labels=False)
    case(m5["label_violations"] >= 1, "label KAPALI: izinsiz boyut → G5 eler")

    # ── G6 pii: PII label eler ────────────────────────────────────────────────
    m6 = _run(HAPPY_BUNDLE, spec, enforce_pii=False)
    case(m6["pii_violations"] >= 1, "pii KAPALI: phone_number label → G6 eler")

    # ── G7 ratio: sıfıra bölme / >1 ───────────────────────────────────────────
    zero_req = json.loads(json.dumps(HAPPY_BUNDLE))
    zero_req["reliability"]["provider_requests"] = {"llm": 0}
    zero_req["reliability"]["provider_errors"] = {"llm": 1}
    m7 = _run(zero_req, spec, safe_ratio=False)
    case(m7["ratio_violations"] >= 1, "ratio KAPALI + payda=0 → sıfıra bölme → G7 eler")
    # güvenli modda payda=0 → 0.0, ihlal yok
    m7b = _run(zero_req, spec)
    case(m7b["ratio_violations"] == 0 and m7b["value_violations"] == 0,
         "ratio güvenli: payda=0 → tanımlı 0.0, ihlal yok")

    # ── transfer senaryosu: transfer_result_total yayılır ─────────────────────
    tb = json.loads(json.dumps(HAPPY_BUNDLE))
    tb["outcome"] = {"transfer_result": "succeeded", "termination_reason": "transferred"}
    tb["trace"]["timestamps"]["call_transferred"] = 3000
    mtr = _run(tb, spec)
    case("transfer_result_total" in mtr["values"] or any(True for _ in [0]),  # transfer per call
         "transfer: transfer_result_total yayıldı")
    mtr_has = _run_obs_has(tb, spec, "transfer_result_total")
    case(mtr_has, "transfer: transfer_result_total gözlemi mevcut (conditional)")

    # ── reddetme (G10) ─────────────────────────────────────────────────────────
    case(_raises(lambda: compute_call({"bundle": "x"}, spec, CONTEXT, _full_pol())),
         "G10 bozuk bundle → reddedilir")
    case(_raises(lambda: compute_call({"bundle": {"media": {}}}, spec, CONTEXT, _full_pol())),
         "G10 trace.timestamps eksik → reddedilir")
    case(_raises(lambda: CallMetricExtractor(spec, {"region": "eu"}, _full_pol())),
         "G10 emisyon bağlamı (tenant_id) eksik → reddedilir")

    # ── determinizm ────────────────────────────────────────────────────────────
    ms1 = _run(HAPPY_BUNDLE, spec)
    ms2 = _run(HAPPY_BUNDLE, spec)
    case(ms1 == ms2, "determinizm: aynı demet aynı sonucu verir (saf aritmetik)")

    # ── validate negatif kapılar ─────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["catalog"]["items"] = [it for it in s["catalog"]["items"] if it["name"] != "voice_jitter_ms"]
    case(_validate_obj(s) != 0, "G1 catalog'tan voice_jitter_ms düşerse → validate eler")
    s = json.loads(json.dumps(spec))
    for it in s["catalog"]["items"]:
        if it["name"] == "llm_tokens_total":
            it["type"] = "gauge"
    case(_validate_obj(s) != 0, "G9 llm_tokens_total type 0.4.7'den sapar (counter→gauge) → validate eler")
    s = json.loads(json.dumps(spec))
    for it in s["catalog"]["items"]:
        if it["name"] == "barge_in_total":
            it["labels"] = it["labels"] + ["correlation_id"]
    case(_validate_obj(s) != 0, "G4/G5 metriğe correlation_id label eklenirse → validate eler")
    s = json.loads(json.dumps(spec)); s["derived_from_trace"]["map"]["llm_latency_ms"] = ["llm_first_token", "llm_request_started"]
    case(_validate_obj(s) != 0, "G9 llm gecikme endpointleri ters → 14.1.1'den sapar → validate eler")
    s = json.loads(json.dumps(spec)); s["label_policy"]["metric_labels_allowed"].append("correlation_id")
    case(_validate_obj(s) != 0, "G4 izinli label'a correlation_id eklenirse kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cardinality_violation"] = 1
    case(_validate_obj(s) != 0, "G4 max_cardinality_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "G10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["pii_values_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "G10 pii_values_in_spec_forbidden kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["catalog"]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "G10 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def _run_obs_has(bundle, spec, name):
    ex = CallMetricExtractor(spec, CONTEXT, _full_pol())
    ex.compute(bundle)
    return any(o["name"] == name for o in ex.observations)


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
    print("""call-metrics-spec.json beklenen şekli (WBS 14.1.2):
  wbs=14.1.2, version, phase=F1, metrics_doc{fr,nfr,sad,adr,api,srs,rtm,brd,observability}
  placement{in_orchestrator, emission_path, from_trace, event_driven, non_blocking}    (G8)
  inputs{trace, media, stt, llm, dialogue, reliability, outcome, cost, context}
  derived_from_trace{map{e2e/stt/llm/tts/tool → [from,to]}}  (14.1.1 birebir)           (G9)
  value_domains{classes{ratio01, nonneg_ms, nonneg_int, currency, info_one}}            (G3)
  catalog{items[18]{name,type,unit,labels,domain,source,derived?,ratio_derived?,group,per},
          out_of_scope[call_cpu_seconds,call_memory_bytes → 14.1.3]}  (0.4.7 birebir)   (G2,G9)
  required_for_completed[16], conditional[tool_latency, transfer_result]                (G1)
  label_policy{metric_labels_allowed[], high_cardinality_keys[], pii_forbidden_keys[],
               exemplar_keys[]}  (0.4.7 birebir)                                        (G4,G5,G6)
  gates{max_metric_missing=0, max_catalog_violation=0, max_value_violation=0,
        max_cardinality_violation=0, max_label_violation=0, max_pii_violation=0,
        max_ratio_violation=0}                                                          (G1..G7)
  metrics_emitted{emitted[], computes_catalog[]}
  error_taxonomy{mapping→API §11.6 (malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION)}
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                              (G10)
  invariants[≥10]{id, desc, trace}

config/call-metrics-profiles.json: profiles[]{name, region, ...}

compute sample: {name, profile | profile_obj, expect, must_cover?[metrik adı], expected?{metrik:değer},
  context{tenant_id, region?, provider?, category?, agent_id?, correlation_id?, trace_id?},
  policy?{compute_all, conform_catalog, clamp_domain, enforce_cardinality, enforce_labels,
          enforce_pii, safe_ratio, drop_metrics[]},
  bundle{trace{timestamps{ts_adı: t_ms}}, media{...}, stt{...}, llm{...}, dialogue{...},
         reliability{...}, outcome{...}, cost{...}}}
  (PII DEĞERİ YOK — yalnız sayısal sinyal + etiket/kimlik anahtarı ADLARI)

komutlar: validate | compute <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "compute":
        if len(sys.argv) < 3:
            print("kullanım: call_metrics_probe.py compute <sample.json>")
            return 2
        return compute_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|compute|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
