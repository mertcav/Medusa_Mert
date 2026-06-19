#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_resource_probe.py — WBS 14.1.3 Per-call CPU/bellek/eşzamanlılık ölçümü

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-metrics/` (14.1.2) + `runtime/call-trace/` (14.1.1) probe disipliniyle birebir;
burada deterministik bir CONVERSATION ORCHESTRATOR PER-CALL RESOURCE ACCOUNTANT (SAD §17.1 'Metrics:',
Resource Manager BRD §10.2) simülatörü (saf aritmetik; random YOK).

PER-CALL RESOURCE ACCOUNTANT (Çekirdek IP, SAD §6 / §17) — cgroup/RSS/cpu-time accounting'ten çağrı
başına CPU saniyesi + orkestratör oturum belleğini (MEDYA TAMPONLARI HARİÇ — ADR-009 hibrit) ÖLÇER +
eşzamanlılık anlık-görüntüsünü (worker_active_sessions / tenant_concurrency) alır ve BRD §15 'çağrı başına
CPU/bellek' + FR-ANA-013 '(CPU/bellek/eşzamanlılık)' DEĞERLERİNİ 0.4.7 observability-spec metrics.catalog'a
UYGUN gözlem (observation) olarak yayar:
  • Kapsam (G1):       required (+conditional) kaynak metriklerinin hepsi yayılır (resource_missing=0).
  • Katalog (G2):      her gözlem catalog name+type+unit; overlap (cpu/mem) 0.4.7 BİREBİR (catalog=0).
  • Değer (G3):        her DEĞER domain sınıfında (cpu_s≥0, byte int≥0, sayım int≥0, ratio∈[0,1]) — value=0.
  • Bütçe (G4):        orkestratör belleği MEDYA HARİÇ ≤15MB (FR-RES-016; 0.4.7 ResourceBudgetExceeded) — budget=0.
  • Density (G5):      bellek footprint'i ≥250 density'ye yer verir (NFR 10.2; mem×floor≤pool) — density=0.
  • Kardinalite (G6):  hiçbir metrik yüksek-kardinalite kimliği LABEL taşımaz — cardinality=0.
  • Etiket+PII (G7):   yalnız catalog[].labels (⊆ allowed) + PII label yok — label=0, pii=0.

KAPSAM AYRIMI: span üretimi + zaman damgası → 14.1.1 · teknik metrik (latency/token/...) DEĞERLERİ →
14.1.2 · metrik/alarm KATALOĞU + collector guard → 0.4.7 · kapasite/density TASARIM TAHMİNİ → 0.3.3/0.3.4
· loglama → 14.1.4 · alarm kuralları → 14.1.5. Burada YALNIZ çağrı başına KAYNAK ÖLÇÜMÜ + bütçe/density
kapısı + katalog/kardinalite/etiket/PII disiplini.

Komutlar:
  validate              call-resource-spec.json'ı invariant'lara + 0.4.7 çapraz-tutarlılığa + config'e karşı doğrular.
  measure <sample>      Deterministik PerCallResourceAccountant — kaynak demeti → metrik gözlemleri + HARD kapılar (G1–G7); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. measure gerçek async runtime yerine deterministik hesaptır (canlı sistemde
Go/Rust + cgroup/RSS accounting + OpenTelemetry/Prometheus, ADR-003/SAD §11/§17.1). Ham ses payload'ı/
transkript/PII DEĞERİ YOK — örnekler yalnız sayısal SİNYAL + kimlik/etiket anahtarı ADLARI taşır.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "call-resource-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "call-resource-profiles.json")

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


class ResourceError(Exception):
    """Geçersiz/eksik kaynak demeti veya bilinmeyen metrik — sessizce kabul yok, reddet (G10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Per-call Resource Accountant — çağrı başına CPU/bellek/eşzamanlılık ÖLÇÜMÜ (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class PerCallResourceAccountant:
    """SAD §17.1 'Metrics:' / Resource Manager (BRD §10.2) Per-call Resource Accountant. cgroup/RSS/
    cpu-time accounting'ten çağrı başına CPU saniyesi + orkestratör oturum belleğini (MEDYA HARİÇ) ÖLÇER
    + eşzamanlılık anlık-görüntüsünü alır; her gözlemi catalog'a + bütçe (FR-RES-016) + density (NFR 10.2)
    + kardinalite/etiket/PII disiplinine + value-domain'e karşı denetler. Saf aritmetik; random YOK.

    policy bayrakları buggy Accountant'ı simüle eder (call-metrics deseni):
      measure_all         : her metriği ölç (kapalı → drop_metrics düşer, G1)
      conform_catalog     : yalnız catalog name/type/unit yay (kapalı → bilinmeyen metrik, G2)
      exclude_media       : bütçe orkestratör belleği MEDYA HARİÇ (kapalı → medya tamponu dahil → şişer, G4)
      enforce_cardinality : kimliği LABEL yapma (kapalı → correlation_id label, G6)
      enforce_labels      : yalnız izinli label (kapalı → izinsiz label, G7-label)
      enforce_pii         : PII label'ı çıkar (kapalı → phone_number label, G7-pii)
    """

    def __init__(self, spec, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy
        cat = spec.get("catalog", {})
        self.items = list(cat.get("items", []))
        self.by_name = {it["name"]: it for it in self.items}
        self.domains = dict(spec.get("value_domains", {}).get("classes", {}))
        lp = spec.get("label_policy", {})
        self.labels_allowed = set(lp.get("metric_labels_allowed", []))
        self.high_card = set(lp.get("high_cardinality_keys", []))
        self.pii_keys = set(lp.get("pii_forbidden_keys", []))
        self.exemplar_keys = list(lp.get("exemplar_keys", ["correlation_id", "trace_id"]))
        bud = spec.get("budget", {})
        self.budget_bytes = bud.get("per_call_memory_budget_bytes", 15728640)
        den = spec.get("density", {})
        self.density_floor = den.get("density_floor", 250)
        self.density_stretch = den.get("density_stretch", 500)
        self.ref_worker = dict(den.get("reference_worker", {}))

        # ingress kimliği (etiket DEĞERİ + exemplar kaynağı)
        if not self.context.get("tenant_id"):
            raise ResourceError("emisyon bağlamı eksik: tenant_id → INVALID_REQUEST")

        self.observations = []   # [{name,type,unit,value,labels{},exemplar{}}]
        self.emitted_names = set()
        self.catalog_violations = 0
        self.value_violations = 0
        self.budget_violations = 0
        self.density_violations = 0
        self.cardinality_violations = 0
        self.label_violations = 0
        self.pii_violations = 0
        self.derived = {}        # rapor amaçlı türetilen değerler

    # ── etiket DEĞER kaynağı ───────────────────────────────────────────────────
    def _label_values(self, item, extra=None):
        out = {}
        src = dict(self.context)
        if extra:
            src.update(extra)
        for k in item.get("labels", []):
            v = src.get(k)
            if v is not None:
                out[k] = v
        # buggy: kimliği LABEL olarak iliştir (G6) — yüksek-kardinalite kaçağı
        if not self.pol.get("enforce_cardinality", True):
            out["correlation_id"] = self.context.get("correlation_id", "corr-x")
        # buggy: PII anahtarını LABEL olarak iliştir (G7-pii) — DEĞER yok, yalnız anahtar adı
        if not self.pol.get("enforce_pii", True):
            out["phone_number"] = "<redacted>"
        # buggy: izinsiz (ama PII/yüksek-kardinalite olmayan) label (G7-label)
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

        # ── G3 değer domaini ──────────────────────────────────────────────────
        if not self._domain_ok(item, value):
            self.value_violations += 1

        # ── G6 kardinalite + G7 etiket/PII ────────────────────────────────────
        allowed = set(item.get("labels", []))
        for k in labels.keys():
            if k in self.high_card:
                self.cardinality_violations += 1
            if k in self.pii_keys:
                self.pii_violations += 1
            if k not in allowed:
                self.label_violations += 1

    def _domain_ok(self, item, value):
        dom = self.domains.get(item.get("domain"), {})
        if isinstance(value, bool) or not isinstance(value, (int, float)):
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

    # ── tam çağrı ölçümü ───────────────────────────────────────────────────────
    def measure(self, bundle):
        cpu = dict(bundle.get("cpu", {}))
        memory = dict(bundle.get("memory", {}))
        conc = dict(bundle.get("concurrency", {}))
        worker = dict(bundle.get("worker", {})) or self.ref_worker

        drop = set(self.pol.get("drop_metrics", [])) if not self.pol.get("measure_all", True) else set()

        def want(name):
            return name not in drop

        # 1) call_cpu_seconds (ölçülen)
        cpu_s = (cpu.get("user_ms", 0) + cpu.get("system_ms", 0)) / 1000.0
        if want("call_cpu_seconds"):
            self._emit("call_cpu_seconds", cpu_s, {})
        self.derived["call_cpu_seconds"] = cpu_s

        # 2) call_memory_bytes (orkestratör oturum belleği MEDYA HARİÇ — budget metriği)
        session_rss = memory.get("session_rss_bytes", 0)
        media_buf = memory.get("media_buffer_bytes", 0)
        if self.pol.get("exclude_media", True):
            mem_value = session_rss                    # doğru: medya HARİÇ
        else:
            mem_value = session_rss + media_buf        # buggy: medya tamponu dahil → şişer (G4)
        if want("call_memory_bytes"):
            self._emit("call_memory_bytes", mem_value, {})
        self.derived["call_memory_bytes"] = mem_value

        # 3) call_media_buffer_bytes (conditional — yalnız medya eş-konumlu ise; budget DIŞI)
        if want("call_media_buffer_bytes") and media_buf and media_buf > 0:
            self._emit("call_media_buffer_bytes", media_buf, {})
        self.derived["call_media_buffer_bytes"] = media_buf

        # 4) worker_active_sessions (eşzamanlılık — density numerator)
        was = conc.get("worker_active_sessions", 0)
        if want("worker_active_sessions"):
            self._emit("worker_active_sessions", was, {"region": self.context.get("region")})
        self.derived["worker_active_sessions"] = was

        # 5) tenant_concurrency (eşzamanlılık — tenant)
        tcc = conc.get("tenant_concurrent_calls", 0)
        if want("tenant_concurrency"):
            self._emit("tenant_concurrency", tcc, {})
        self.derived["tenant_concurrency"] = tcc

        # buggy: catalog dışı metrik yay (G2)
        if not self.pol.get("conform_catalog", True):
            self._emit("unmapped_adhoc_metric", 1.0)

        # ── G4 bütçe (FR-RES-016 ≤15MB; MEDYA HARİÇ) ───────────────────────────
        if mem_value > self.budget_bytes:
            self.budget_violations += 1
        self.derived["budget_bytes"] = self.budget_bytes
        self.derived["budget_headroom_bytes"] = self.budget_bytes - mem_value
        self.derived["budget_ok"] = mem_value <= self.budget_bytes

        # ── G5 density tutarlılığı (NFR 10.2; mem×floor ≤ pool) ─────────────────
        pool = worker.get("session_memory_pool_bytes", self.ref_worker.get("session_memory_pool_bytes", 0))
        density_ceiling = (pool // self.density_floor) if self.density_floor else 0
        if mem_value > 0 and mem_value > density_ceiling:
            self.density_violations += 1
        # bu footprint referans işçide kaç oturuma yer verir
        supported = (pool // mem_value) if mem_value and mem_value > 0 else 0
        self.derived["density_ceiling_bytes"] = density_ceiling
        self.derived["density_supported_sessions"] = supported
        self.derived["density_floor_met_by_footprint"] = supported >= self.density_floor
        # GÖZLENEN worker density (SOFT bilgi — trafiğe bağlı, HARD kapı değil)
        self.derived["observed_density_floor_met"] = was >= self.density_floor
        self.derived["observed_density_stretch_met"] = was >= self.density_stretch

        # ── tenant kota kullanımı (FR-TEN-007; 0.4.7 TenantCapacity80 girdisi — rapor) ──
        lim = conc.get("tenant_concurrency_limit", 0)
        self.derived["tenant_concurrency_utilization"] = (tcc / lim) if lim and lim > 0 else 0.0

    def coverage_missing(self, must_cover):
        return [n for n in must_cover if n not in self.emitted_names]

    def metrics(self, must_cover):
        missing = self.coverage_missing(must_cover)
        return {
            "observations_total": len(self.observations),
            "distinct_metrics": len(self.emitted_names),
            "resource_missing": len(missing),
            "resource_missing_keys": missing,
            "catalog_violations": self.catalog_violations,
            "value_violations": self.value_violations,
            "budget_violations": self.budget_violations,
            "density_violations": self.density_violations,
            "cardinality_violations": self.cardinality_violations,
            "label_violations": self.label_violations,
            "pii_violations": self.pii_violations,
            "derived": dict(self.derived),
            "values": {o["name"]: o["value"] for o in self.observations},
        }


def measure_call(sample, spec, context, policy):
    bundle = sample.get("bundle")
    if not isinstance(bundle, dict):
        raise ResourceError("kaynak demeti (bundle) sözlük değil → INVALID_REQUEST")
    if "cpu" not in bundle or "memory" not in bundle:
        raise ResourceError("bundle.cpu / bundle.memory eksik (kaynak accounting girdisi) → INVALID_REQUEST")
    acc = PerCallResourceAccountant(spec, context, policy)
    acc.measure(bundle)
    must_cover = sample.get("must_cover")
    if must_cover is None:
        must_cover = spec.get("required_for_completed", [])
    return acc.metrics(must_cover)


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G7) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    F = []
    F.append((m.get("resource_missing", 0) <= g.get("max_resource_missing", 0),
              "G1 kaynak eksik %d ≤ %d (required CPU/bellek/eşzamanlılık ölçüldü%s — BRD §15/FR-ANA-013)"
              % (m.get("resource_missing", 0), g.get("max_resource_missing", 0),
                 (" [eksik: %s]" % ",".join(m.get("resource_missing_keys", []))) if m.get("resource_missing") else "")))
    F.append((m.get("catalog_violations", 0) <= g.get("max_catalog_violation", 0),
              "G2 katalog ihlali %d ≤ %d (gözlem catalog name+type+unit; overlap 0.4.7 BİREBİR — SAD §17.1)"
              % (m.get("catalog_violations", 0), g.get("max_catalog_violation", 0))))
    F.append((m.get("value_violations", 0) <= g.get("max_value_violation", 0),
              "G3 değer ihlali %d ≤ %d (cpu_s≥0+finite, byte int≥0, sayım int≥0, ratio∈[0,1] — FR-ANA-013)"
              % (m.get("value_violations", 0), g.get("max_value_violation", 0))))
    F.append((m.get("budget_violations", 0) <= g.get("max_budget_violation", 0),
              "G4 bütçe ihlali %d ≤ %d (orkestratör belleği MEDYA HARİÇ %s ≤ %s = 15MB — FR-RES-016/NFR 10.2/0.4.7)"
              % (m.get("budget_violations", 0), g.get("max_budget_violation", 0),
                 d.get("call_memory_bytes"), d.get("budget_bytes"))))
    F.append((m.get("density_violations", 0) <= g.get("max_density_violation", 0),
              "G5 density ihlali %d ≤ %d (footprint ≥250 density'ye yer verir: %s oturum desteklenir — NFR 10.2/0.3.3)"
              % (m.get("density_violations", 0), g.get("max_density_violation", 0),
                 d.get("density_supported_sessions"))))
    F.append((m.get("cardinality_violations", 0) <= g.get("max_cardinality_violation", 0),
              "G6 kardinalite ihlali %d ≤ %d (yüksek-kardinalite kimlik LABEL değil; yalnız exemplar — 0.4.7)"
              % (m.get("cardinality_violations", 0), g.get("max_cardinality_violation", 0))))
    F.append((m.get("label_violations", 0) <= g.get("max_label_violation", 0)
              and m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G7 etiket/PII ihlali label=%d pii=%d ≤ 0 (yalnız catalog[].labels ⊆ allowed + PII yok — 0.4.7/FR-REC-004)"
              % (m.get("label_violations", 0), m.get("pii_violations", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise ResourceError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _resolve_policy(spec, sample):
    pol = {
        "measure_all": True,
        "conform_catalog": True,
        "exclude_media": True,
        "enforce_cardinality": True,
        "enforce_labels": True,
        "enforce_pii": True,
        "drop_metrics": [],
    }
    pol.update(sample.get("policy", {}))
    return pol


def _fmt_bytes(n):
    if not isinstance(n, (int, float)):
        return str(n)
    return "%.2fMiB" % (n / (1024 * 1024))


def measure_cmd(sample_path):
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
        except ResourceError as ex:
            print("measure[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = measure_call(sample, spec, context, policy)
    except ResourceError as ex:
        print("measure[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("measure[%s] %d gözlem (%d metrik) | eksik=%d | katalog=%d değer=%d bütçe=%d density=%d kardinalite=%d etiket=%d pii=%d" % (
        name, m["observations_total"], m["distinct_metrics"], m["resource_missing"],
        m["catalog_violations"], m["value_violations"], m["budget_violations"], m["density_violations"],
        m["cardinality_violations"], m["label_violations"], m["pii_violations"]))
    print("  CPU=%ss | bellek(medya hariç)=%s/≤%s | medya tamponu=%s | worker oturum=%s (floor≥%s:%s, stretch≥%s:%s) | tenant eşzaman=%s (kullanım=%.2f)" % (
        d.get("call_cpu_seconds"), _fmt_bytes(d.get("call_memory_bytes")), _fmt_bytes(d.get("budget_bytes")),
        _fmt_bytes(d.get("call_media_buffer_bytes")), d.get("worker_active_sessions"),
        spec.get("density", {}).get("density_floor"), d.get("observed_density_floor_met"),
        spec.get("density", {}).get("density_stretch"), d.get("observed_density_stretch_met"),
        d.get("tenant_concurrency"), d.get("tenant_concurrency_utilization", 0.0)))
    print("  density footprint: %s oturum desteklenir (tavan=%s ≥ floor %s: %s)" % (
        d.get("density_supported_sessions"), _fmt_bytes(d.get("density_ceiling_bytes")),
        spec.get("density", {}).get("density_floor"), d.get("density_floor_met_by_footprint")))
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


def _alert_threshold(obs, alert_name):
    """0.4.7 alerts kataloğundan bir alarmın expr_hint'indeki sayısal eşiği çıkarır."""
    for a in obs.get("alerts", {}).get("catalog", []):
        if a.get("name") == alert_name:
            mm = re.search(r">\s*(\d+)", a.get("expr_hint", ""))
            if mm:
                return int(mm.group(1))
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.1.3", "spec.wbs == 14.1.3")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")

    # ── G8: placement (orchestrator emisyon, measured, medya hariç, olay-tetikli, bloklamaz)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "G8 Accountant orchestrator içinde")
    _check(R, pl.get("emission_path") is True, "G8 emisyon yolunda")
    _check(R, pl.get("measured") is True and pl.get("from_trace") is False,
           "G8 CPU/bellek ÖLÇÜLÜR (measured; from_trace değil)")
    _check(R, pl.get("excludes_media") is True, "G8 orkestratör belleği MEDYA HARİÇ (ADR-009 hibrit)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "G8 olay-tetikli + bloklamaz (FR-RES-012 asenkron/sampling)")

    # ── catalog
    cat = spec.get("catalog", {})
    items = cat.get("items", [])
    names = [it.get("name") for it in items]
    _check(R, len(names) == len(set(names)) and len(names) == 5,
           "G1 catalog 5 metrik (cpu/mem/media + worker/tenant eşzamanlılık)")
    _check(R, all(it.get("type") and it.get("unit") and it.get("domain") and it.get("brd15") for it in items),
           "G2/G3 her metrik type+unit+domain+brd15 taşır")
    domains = set(spec.get("value_domains", {}).get("classes", {}).keys())
    _check(R, all(it.get("domain") in domains for it in items),
           "G3 her metriğin domain'i value_domains.classes içinde")

    # ── required / conditional / overlap
    req = set(spec.get("required_for_completed", []))
    cond = set(spec.get("conditional", []))
    overlap = set(spec.get("observability_overlap", []))
    _check(R, req <= set(names) and cond <= set(names), "G1 required+conditional catalog içinde")
    _check(R, not (req & cond), "G1 required ile conditional kesişmez")
    _check(R, cond == {"call_media_buffer_bytes"}, "G1 conditional = call_media_buffer_bytes")
    _check(R, req == {"call_cpu_seconds", "call_memory_bytes", "worker_active_sessions", "tenant_concurrency"},
           "G1 4 required metrik (cpu/mem + worker/tenant eşzamanlılık)")
    _check(R, overlap == {"call_cpu_seconds", "call_memory_bytes"},
           "G2/G9 observability_overlap = call_cpu_seconds + call_memory_bytes")
    # overlap metrikler 0.4.7-katalog bayraklı; diğerleri proposed
    for it in items:
        if it["name"] in overlap:
            _check(R, it.get("in_observability_catalog") is True,
                   "G9 %s in_observability_catalog=true" % it["name"])
        else:
            _check(R, it.get("proposed_for_observability") is True,
                   "G9 %s proposed_for_observability=true (eşzamanlılık → gelecek 0.4.7)" % it["name"])

    # ── budget (FR-RES-016 / NFR 10.2 / 0.4.7 birebir)
    bud = spec.get("budget", {})
    _check(R, bud.get("per_call_memory_budget_bytes") == 15 * 1024 * 1024,
           "G4 bellek bütçesi = 15 MiB (15728640 B; NFR 10.2)")
    _check(R, bud.get("budget_excludes_media") is True, "G4 bütçe MEDYA HARİÇ (FR-RES-016/NFR 10.2)")
    _check(R, bud.get("budget_metric") == "call_memory_bytes", "G4 bütçe metriği call_memory_bytes")
    _check(R, bud.get("cpu_hard_threshold") is None,
           "G4 CPU HARD eşik YOK (BRD §10.2 'düşük; çekirdek paylaşımlı')")

    # ── density (NFR 10.2 / 0.3.3)
    den = spec.get("density", {})
    _check(R, den.get("density_floor") == 250 and den.get("density_stretch") == 500,
           "G5 density floor 250 / stretch 500 (NFR 10.2)")
    rw = den.get("reference_worker", {})
    _check(R, rw.get("vcpu") == 8 and rw.get("memory_bytes") == 16 * 1024 * 1024 * 1024,
           "G5 referans işçi 8 vCPU / 16 GiB (NFR 10.2)")
    pool = rw.get("session_memory_pool_bytes", 0)
    _check(R, 0 < pool <= rw.get("memory_bytes", 0),
           "G5 session_memory_pool_bytes ∈ (0, worker bellek]")
    # density tutarlılığı: 15MB bütçe ≥250 density'ye yer verir (mem×floor ≤ pool) → bellek density'yi bağlamaz
    _check(R, bud.get("per_call_memory_budget_bytes", 0) * den.get("density_floor", 0) <= pool,
           "G5/G9 15MB bütçe × 250 floor ≤ pool (bellek density floor'unu bozmaz; 0.3.3 bulgusu)")

    # ── label_policy (0.4.7 ile birebir)
    lp = spec.get("label_policy", {})
    allowed = set(lp.get("metric_labels_allowed", []))
    high = set(lp.get("high_cardinality_keys", []))
    pii = set(lp.get("pii_forbidden_keys", []))
    _check(R, {"correlation_id", "call_id", "customer_id", "session_id"} <= high,
           "G6 high_cardinality_keys çekirdek kimlikleri içerir")
    _check(R, {"phone_number", "token", "transcript_text", "audio_payload"} <= pii,
           "G7 pii_forbidden_keys çekirdek PII anahtarlarını içerir")
    _check(R, not (allowed & high), "G6 izinli label ile yüksek-kardinalite kesişmez")
    _check(R, not (allowed & pii), "G7 izinli label ile PII kesişmez")
    bad = [it["name"] for it in items if not set(it.get("labels", [])) <= allowed]
    _check(R, not bad, "G7 her metrik label'ı metric_labels_allowed alt kümesi (%s)" % (",".join(bad) or "-"))
    _check(R, set(lp.get("exemplar_keys", [])) >= {"correlation_id", "trace_id"},
           "G6 correlation_id/trace_id exemplar (label değil)")

    # ── 0.4.7 observability-spec ile BİREBİR (G9)
    obs = _load_observability_spec()
    if obs is not None:
        obs_cat = {mm.get("name"): mm for mm in obs.get("metrics", {}).get("catalog", [])}
        for it in items:
            if it["name"] not in overlap:
                continue
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
        # 0.4.7 ResourceBudgetExceeded eşiği BİREBİR (15MB)
        thr = _alert_threshold(obs, "ResourceBudgetExceeded")
        _check(R, thr == bud.get("per_call_memory_budget_bytes"),
               "G9 0.4.7 ResourceBudgetExceeded eşiği (%s) bütçe ile birebir" % thr)
        # tenant_concurrency 0.4.7 TenantCapacity80 alarmında referans edilir (henüz katalogda değil)
        tc_alert = any(a.get("name") == "TenantCapacity80" for a in obs.get("alerts", {}).get("catalog", []))
        _check(R, tc_alert, "G9 0.4.7 TenantCapacity80 alarmı mevcut (tenant_concurrency girdisi)")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_resource_missing", "max_catalog_violation", "max_value_violation",
               "max_budget_violation", "max_density_violation", "max_cardinality_violation",
               "max_label_violation", "max_pii_violation"):
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
    "region": "eu-west-1", "provider": "prov_a",
    "correlation_id": "corr-001", "trace_id": "tr-001",
}

# tam happy-path kaynak demeti — ADR-009 hibrit (medya offloaded → media_buffer ~0)
HAPPY_BUNDLE = {
    "cpu": {"user_ms": 180, "system_ms": 40},
    "memory": {"session_rss_bytes": 11534336, "media_buffer_bytes": 0},   # 11 MiB oturum, medya ayrı
    "concurrency": {"worker_active_sessions": 420, "tenant_concurrent_calls": 37, "tenant_concurrency_limit": 100},
}
# medya eş-konumlu (edge/central) — call_media_buffer_bytes (conditional) yayılır; bütçe MEDYA HARİÇ aynı kalır
MEDIA_BUNDLE = {
    "cpu": {"user_ms": 200, "system_ms": 60},
    "memory": {"session_rss_bytes": 12582912, "media_buffer_bytes": 13631488},   # 12 MiB oturum + 13 MiB medya
    "concurrency": {"worker_active_sessions": 320, "tenant_concurrent_calls": 41, "tenant_concurrency_limit": 100},
}


def _full_pol():
    return {"measure_all": True, "conform_catalog": True, "exclude_media": True,
            "enforce_cardinality": True, "enforce_labels": True, "enforce_pii": True,
            "drop_metrics": []}


def _run(bundle, spec, context=None, must_cover=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    sample = {"bundle": bundle}
    if must_cover is not None:
        sample["must_cover"] = must_cover
    return measure_call(sample, spec, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except ResourceError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy (hibrit): tüm kapılar geçer ─────────────────────────────────────
    mh = _run(HAPPY_BUNDLE, spec)
    case(mh["resource_missing"] == 0, "happy: 4 required kaynak metriği ölçüldü (G1)")
    case(mh["catalog_violations"] == 0, "happy: katalog uyumlu (G2)")
    case(mh["value_violations"] == 0, "happy: değerler domain-içi (G3)")
    case(mh["budget_violations"] == 0, "happy: bellek ≤15MB (G4)")
    case(mh["density_violations"] == 0, "happy: footprint ≥250 density'ye yer verir (G5)")
    case(mh["cardinality_violations"] == 0, "happy: yüksek-kardinalite label yok (G6)")
    case(mh["label_violations"] == 0 and mh["pii_violations"] == 0, "happy: izinsiz/PII label yok (G7)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    # ölçülen DEĞER doğruluğu
    v = mh["values"]
    case(v["call_cpu_seconds"] == 0.22, "happy: cpu = (180+40)/1000 = 0.22s")
    case(v["call_memory_bytes"] == 11534336, "happy: bellek = 11 MiB (medya HARİÇ)")
    case(v["worker_active_sessions"] == 420, "happy: worker oturum = 420")
    case(v["tenant_concurrency"] == 37, "happy: tenant eşzaman = 37")
    case("call_media_buffer_bytes" not in v, "happy (hibrit): medya tamponu yok → conditional yayılmadı")
    d = mh["derived"]
    case(d["tenant_concurrency_utilization"] == 0.37, "happy: tenant kullanım = 37/100 = 0.37")
    case(d["observed_density_floor_met"] is True and d["observed_density_stretch_met"] is False,
         "happy: gözlenen density floor≥250 ✓ stretch≥500 ✗ (SOFT bilgi)")
    case(d["density_floor_met_by_footprint"] is True, "happy: footprint ≥250 oturum destekler (G5 SOFT)")
    case(mh["distinct_metrics"] == 4 and mh["observations_total"] == 4,
         "happy: 4 distinct gözlem (hibrit; medya conditional yok)")

    # ── medya eş-konumlu: conditional media buffer yayılır, bütçe MEDYA HARİÇ geçer ──
    mm = _run(MEDIA_BUNDLE, spec)
    case("call_media_buffer_bytes" in mm["values"], "medya: call_media_buffer_bytes yayıldı (conditional)")
    case(mm["values"]["call_memory_bytes"] == 12582912, "medya: bütçe metriği MEDYA HARİÇ (12 MiB)")
    case(mm["budget_violations"] == 0, "medya: bütçe MEDYA HARİÇ ≤15MB geçer (G4)")
    case(mm["distinct_metrics"] == 5, "medya: 5 distinct (media conditional dahil)")
    # buggy: exclude_media KAPALI → medya tamponu bütçeye dahil → 12+13=25MiB > 15MB → G4 eler
    mmb = _run(MEDIA_BUNDLE, spec, exclude_media=False)
    case(mmb["values"]["call_memory_bytes"] == 12582912 + 13631488, "medya: exclude_media KAPALI → bellek = 12+13 MiB")
    case(mmb["budget_violations"] >= 1, "medya: exclude_media KAPALI → bütçe şişer >15MB → G4 eler")

    # ── G1 coverage: bir metrik düşerse eler ──────────────────────────────────
    mc = _run(HAPPY_BUNDLE, spec, measure_all=False, drop_metrics=["call_memory_bytes"])
    case(mc["resource_missing"] == 1 and "call_memory_bytes" in mc["resource_missing_keys"],
         "coverage: call_memory_bytes düştü → 1 eksik (G1 eler)")
    case(not all(ok for ok, _ in evaluate(spec, mc)), "coverage eksik → en az bir kapı eler")

    # ── G2 catalog: bilinmeyen metrik yayınlanırsa eler ───────────────────────
    m2 = _run(HAPPY_BUNDLE, spec, conform_catalog=False)
    case(m2["catalog_violations"] >= 1, "catalog KAPALI: bilinmeyen metrik → G2 eler")

    # ── G3 value: negatif CPU (bozuk accounting) → domain dışı ─────────────────
    bad_cpu = json.loads(json.dumps(HAPPY_BUNDLE))
    bad_cpu["cpu"] = {"user_ms": -50, "system_ms": 0}
    m3 = _run(bad_cpu, spec)
    case(m3["value_violations"] >= 1, "value: negatif CPU → domain dışı → G3 eler")

    # ── G4 budget: oturum belleği >15MB → eler ────────────────────────────────
    big = json.loads(json.dumps(HAPPY_BUNDLE))
    big["memory"]["session_rss_bytes"] = 25165824   # 24 MiB > 15 MiB
    m4 = _run(big, spec)
    case(m4["budget_violations"] >= 1, "budget: oturum belleği 24MiB > 15MB → G4 eler")
    case(m4["derived"]["budget_headroom_bytes"] < 0, "budget: headroom negatif (aşım izlendi, FR-RES-016)")

    # ── G5 density: footprint floor'u bozarsa eler ────────────────────────────
    huge = json.loads(json.dumps(HAPPY_BUNDLE))
    huge["memory"]["session_rss_bytes"] = 83886080   # 80 MiB → 80×250 > 14.6GB pool
    m5 = _run(huge, spec)
    case(m5["density_violations"] >= 1, "density: 80MiB footprint → ≥250 density'ye yer vermez → G5 eler")
    case(m5["derived"]["density_supported_sessions"] < 250, "density: footprint <250 oturum destekler")

    # ── G6 cardinality: kimlik label olursa eler ──────────────────────────────
    m6 = _run(HAPPY_BUNDLE, spec, enforce_cardinality=False)
    case(m6["cardinality_violations"] >= 1, "cardinality KAPALI: correlation_id label → G6 eler")

    # ── G7 label/pii: izinsiz/PII label eler ──────────────────────────────────
    m7l = _run(HAPPY_BUNDLE, spec, enforce_labels=False)
    case(m7l["label_violations"] >= 1, "label KAPALI: izinsiz boyut → G7 eler")
    m7p = _run(HAPPY_BUNDLE, spec, enforce_pii=False)
    case(m7p["pii_violations"] >= 1, "pii KAPALI: phone_number label → G7 eler")

    # ── reddetme (G10) ─────────────────────────────────────────────────────────
    case(_raises(lambda: measure_call({"bundle": "x"}, spec, CONTEXT, _full_pol())),
         "G10 bozuk bundle → reddedilir")
    case(_raises(lambda: measure_call({"bundle": {"cpu": {}}}, spec, CONTEXT, _full_pol())),
         "G10 bundle.memory eksik → reddedilir")
    case(_raises(lambda: PerCallResourceAccountant(spec, {"region": "eu"}, _full_pol())),
         "G10 emisyon bağlamı (tenant_id) eksik → reddedilir")

    # ── determinizm ────────────────────────────────────────────────────────────
    ms1 = _run(HAPPY_BUNDLE, spec)
    ms2 = _run(HAPPY_BUNDLE, spec)
    case(ms1 == ms2, "determinizm: aynı demet aynı sonucu verir (saf aritmetik)")

    # ── validate negatif kapılar ─────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["catalog"]["items"] = [it for it in s["catalog"]["items"] if it["name"] != "call_cpu_seconds"]
    case(_validate_obj(s) != 0, "G1 catalog'tan call_cpu_seconds düşerse → validate eler")
    s = json.loads(json.dumps(spec))
    for it in s["catalog"]["items"]:
        if it["name"] == "call_memory_bytes":
            it["unit"] = "kb"
    case(_validate_obj(s) != 0, "G9 call_memory_bytes unit 0.4.7'den sapar (bytes→kb) → validate eler")
    s = json.loads(json.dumps(spec))
    for it in s["catalog"]["items"]:
        if it["name"] == "call_cpu_seconds":
            it["labels"] = it["labels"] + ["correlation_id"]
    case(_validate_obj(s) != 0, "G6/G7 metriğe correlation_id label eklenirse → validate eler")
    s = json.loads(json.dumps(spec)); s["budget"]["per_call_memory_budget_bytes"] = 31457280
    case(_validate_obj(s) != 0, "G4/G9 bütçe 0.4.7 ResourceBudgetExceeded eşiğinden sapar (30MB) → validate eler")
    s = json.loads(json.dumps(spec)); s["density"]["reference_worker"]["session_memory_pool_bytes"] = 1024
    case(_validate_obj(s) != 0, "G5 pool 15MB×250'den küçük → bellek density'yi bozar → validate eler")
    s = json.loads(json.dumps(spec)); s["label_policy"]["metric_labels_allowed"].append("correlation_id")
    case(_validate_obj(s) != 0, "G6 izinli label'a correlation_id eklenirse kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_budget_violation"] = 1
    case(_validate_obj(s) != 0, "G4 max_budget_violation>0 → validate eler")
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
    print("""call-resource-spec.json beklenen şekli (WBS 14.1.3):
  wbs=14.1.3, version, phase=F1, resource_doc{fr,nfr,sad,adr,api,srs,rtm,brd,observability,poc}
  placement{in_orchestrator, emission_path, measured=true, from_trace=false, excludes_media=true,
            event_driven, non_blocking}                                                  (G8)
  inputs{cpu, memory, concurrency, worker, context}
  value_domains{classes{nonneg_seconds, nonneg_bytes, nonneg_count, ratio01}}            (G3)
  catalog{items[5]{name,type,unit,labels,domain,source,group,per,
          in_observability_catalog?|proposed_for_observability?,budget_metric?|budget_excluded?}}  (G2,G9)
  required_for_completed[4], conditional[call_media_buffer_bytes],
  observability_overlap[call_cpu_seconds, call_memory_bytes]                             (G1,G9)
  budget{per_call_memory_budget_bytes=15728640, budget_excludes_media=true,
         budget_metric=call_memory_bytes, cpu_hard_threshold=null}  (FR-RES-016/0.4.7)   (G4)
  density{reference_worker{vcpu=8,memory_bytes=16GiB,session_memory_pool_bytes},
          density_floor=250, density_stretch=500, consistency_rule}  (NFR 10.2/0.3.3)    (G5)
  label_policy{metric_labels_allowed[], high_cardinality_keys[], pii_forbidden_keys[],
               exemplar_keys[]}  (0.4.7 birebir)                                        (G6,G7)
  gates{max_resource_missing=0, max_catalog_violation=0, max_value_violation=0,
        max_budget_violation=0, max_density_violation=0, max_cardinality_violation=0,
        max_label_violation=0, max_pii_violation=0}                                      (G1..G7)
  metrics_emitted{emitted[], computes_catalog[]}
  error_taxonomy{mapping→API §11.6 (malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION)}
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                              (G10)
  invariants[≥10]{id, desc, trace}

config/call-resource-profiles.json: profiles[]{name, region, ...}

measure sample: {name, profile | profile_obj, expect, must_cover?[metrik adı], expected?{metrik:değer},
  context{tenant_id, region?, provider?, agent_id?, correlation_id?, trace_id?},
  policy?{measure_all, conform_catalog, exclude_media, enforce_cardinality, enforce_labels,
          enforce_pii, drop_metrics[]},
  bundle{cpu{user_ms, system_ms}, memory{session_rss_bytes, media_buffer_bytes},
         concurrency{worker_active_sessions, tenant_concurrent_calls, tenant_concurrency_limit},
         worker?{vcpu, memory_bytes, session_memory_pool_bytes}}}
  (PII DEĞERİ YOK — yalnız sayısal sinyal + etiket/kimlik anahtarı ADLARI)

komutlar: validate | measure <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "measure":
        if len(sys.argv) < 3:
            print("kullanım: call_resource_probe.py measure <sample.json>")
            return 2
        return measure_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|measure|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
