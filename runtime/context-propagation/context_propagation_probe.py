#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
context_propagation_probe.py — WBS 3.1.5 correlation_id + tenant context propagation

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/turn-taking/` + `runtime/resource-budget/` probe disipliniyle aynı; burada deterministik bir
ORCHESTRATOR CONTEXT PROPAGATOR (SAD §13.3 + §17.1) simülatörü (kayıt-tetikli, sanal saat, random YOK).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) — çağrı INGRESS'inde bir oturum bağlamı
(tenant_id + org_unit + agent_id + correlation_id + region + call_id + session_id) BİR KEZ kurar ve
ÜRETİLEN HER kayda (event/log/span/metric/adapter_call/tool_call) DEĞİŞMEZ biçimde taşır:
  • Bağlam tamlığı:    her event/log/span/adapter/tool required_keys (tenant_id+correlation_id) taşır (G1).
  • Kardinalite:       yüksek-kardinalite kimlik metrik LABEL olamaz — yalnız exemplar (G2, 0.4.7 label_policy).
  • PII yasağı:        PII anahtarı bağlam/label/attribute'ta yok (G3, FR-REC-004).
  • Tenant binding:    hiçbir kayıt oturumdan farklı tenant_id taşımaz (G4, FR-TEN-002).
  • correlation sürekliliği: çağrı başına TEK correlation_id (G5, SAD §17.1).
  • Adapter bağlamı:   her giden adapter/tool çağrısı correlation_id+tenant_id+region taşır (G6, API §11.1).
  • Region pin:        adapter çağrıları home-region'a pinli (G7, NFR 10.7).
  • Immutable mutation: tenant_id/correlation_id/call_id çağrı ortasında değişmez (G8).

KAPSAM AYRIMI: kardinalite/PII/alarm KATALOĞU + collector guard → 0.4.7 · event envelope şeması → 1.1.8 ·
redaction motoru (L7) → ileri WBS · RLS veri-katmanı → 1.1.x/1.2.1. Burada YALNIZ orchestrator RUNTIME
PROPAGASYON + ENFORCEMENT.

Komutlar:
  validate              context-propagation-spec.json'ı invariant'lara + config profillerine karşı doğrular.
  simulate <sample>     Deterministik Propagator — oturum bağlamı + emisyon akışı → iliştirme + enforcement
                        + metrikler + HARD kapılar (G1–G8); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek async runtime yerine deterministik simülasyondur (canlı
sistemde Go/Rust olay-döngüsü + OpenTelemetry W3C traceparent, ADR-003/SAD §6.3/§17.1). Ham ses
payload'ı/transkript/PII DEĞERİ YOK — emisyonlar yalnız KİMLİK ANAHTARI ADLARI + sanal zaman taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "context-propagation-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "context-propagation-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# yüzey (surface) tipleri — emisyon kindleri
SURFACES = {"event", "log", "span", "metric", "adapter_call", "tool_call"}
ADAPTER_KINDS = {"adapter_call", "tool_call"}
# bağlam zorunlu yüzeyler (metric hariç — metric yalnız exemplar)
CONTEXT_REQUIRED_KINDS = {"event", "log", "span", "adapter_call", "tool_call"}


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class ContextError(Exception):
    """Geçersiz/desteklenmeyen emisyon veya eksik ingress bağlamı — sessizce kabul yok, reddet (G10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Context Propagator — kayıt-tetikli orchestrator propagasyonu (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class ContextPropagator:
    """SAD §13.3 + §17.1 Context Propagator. Çağrı ingress'inde kurulan oturum bağlamını her emisyona
    iliştirir ve enforcement uygular. Kayıt-tetikli, bloklamaz; sanal saat (emission.t) — random YOK.

    policy bayrakları buggy propagator'ı simüle eder (turn-taking/resource-budget deseni):
      attach_context      : bağlamı her kayda iliştir (kapalı → required_keys eksik, G1)
      enforce_cardinality : yüksek-kardinalite kimliği metrik label'dan çıkar→exemplar (kapalı → G2)
      enforce_pii         : PII anahtarını label/attribute'tan çıkar (kapalı → G3)
      bind_tenant         : immutable tenant binding'i zorla (kapalı → farklı tenant geçer, G4/G8)
      pin_region          : adapter çağrısını home-region'a pinle (kapalı → region uyumsuzluğu geçer, G7)
    """

    def __init__(self, spec, session, policy):
        self.spec = spec
        cm = spec.get("context_model", {})
        self.required_keys = set(cm.get("required_keys", ["tenant_id", "correlation_id"]))
        self.full_context = list(cm.get("full_context", []))
        self.immutable_keys = set(cm.get("immutable_keys", ["tenant_id", "correlation_id", "call_id"]))
        self.adapter_required = set(cm.get("adapter_call_required", ["correlation_id", "tenant_id", "region"]))
        cp = spec.get("cardinality_policy", {})
        self.labels_forbidden = set(cp.get("metric_labels_forbidden", []))
        self.high_card = set(cp.get("high_cardinality_keys", []))
        self.exemplar_keys = set(cp.get("exemplar_keys", []))
        self.pii_keys = set(spec.get("pii_policy", {}).get("forbidden_keys", []))
        self.pol = policy

        # ingress oturum bağlamı (BİR KEZ kurulur)
        self.session = dict(session)
        for rk in self.required_keys:
            if not self.session.get(rk):
                raise ContextError("ingress bağlamı eksik required_key: %s → INVALID_REQUEST" % rk)
        self.home_region = self.session.get("region")
        self.bound_tenant = self.session.get("tenant_id")
        self.call_correlation = self.session.get("correlation_id")

        # sayaçlar / metrikler
        self.records_total = 0
        self.context_complete = 0
        self.missing_context = 0
        self.cardinality_violations = 0
        self.pii_violations = 0
        self.cross_tenant_violations = 0
        self.illegal_context_mutations = 0
        self.region_violations = 0
        self.adapter_calls = 0
        self.adapter_context_missing = 0
        self.exemplars_attached = 0
        self.blocked_mutations = 0          # bind_tenant açıkken engellenen mutasyon (doğru davranış)
        self.correlation_ids = set()        # gözlemlenen tüm correlation_id'ler (sürekliliğe karşı)
        self.kinds = set()

    def _attached_context(self, em):
        """Emisyona iliştirilen efektif bağlam (policy uygulanmış)."""
        if self.pol.get("attach_context", True):
            ctx = {k: self.session.get(k) for k in self.full_context if self.session.get(k) is not None}
        else:
            # buggy: bağlam iliştirilmez → emitter'ın elinde ne varsa o (genelde eksik)
            ctx = {}
        # emitter'ın denediği override'lar (immutable binding testi)
        for ik in self.immutable_keys:
            ov_key = ik + "_override"
            if ov_key in em:
                if self.pol.get("bind_tenant", True):
                    # doğru: immutable — oturum değeri korunur, override yok sayılır
                    if em[ov_key] != self.session.get(ik):
                        self.blocked_mutations += 1
                    ctx[ik] = self.session.get(ik)
                else:
                    # buggy: emitter override'ı geçer → mutasyon
                    ctx[ik] = em[ov_key]
                    if em[ov_key] != self.session.get(ik):
                        self.illegal_context_mutations += 1
        return ctx

    def step(self, em):
        if not isinstance(em, dict):
            raise ContextError("emisyon sözlük değil → INVALID_REQUEST")
        kind = em.get("kind")
        t = em.get("t")
        if kind not in SURFACES:
            raise ContextError("bilinmeyen emisyon yüzeyi: %r → INVALID_REQUEST" % kind)
        if not isinstance(t, (int, float)):
            raise ContextError("emisyon zaman damgası sayısal değil → INVALID_REQUEST")

        self.records_total += 1
        self.kinds.add(kind)
        ctx = self._attached_context(em)

        # ── correlation continuity (G5): hangi correlation_id efektif?
        cid = ctx.get("correlation_id")
        if cid:
            self.correlation_ids.add(cid)

        # ── tenant binding (G4): efektif tenant_id oturumla eşleşmeli
        eff_tenant = ctx.get("tenant_id")
        if eff_tenant is not None and eff_tenant != self.bound_tenant:
            self.cross_tenant_violations += 1

        # ── bağlam tamlığı (G1) — metric hariç tüm yüzeyler required_keys taşır
        if kind in CONTEXT_REQUIRED_KINDS:
            complete = all(ctx.get(rk) for rk in self.required_keys)
            if complete:
                self.context_complete += 1
            else:
                self.missing_context += 1

        # ── metrik: label kardinalite (G2) + label PII (G3)
        if kind == "metric":
            labels = list(em.get("labels", []))   # emitter'ın label olarak koymak istediği anahtar ADLARI
            for lab in labels:
                if lab in self.high_card or lab in self.labels_forbidden:
                    if self.pol.get("enforce_cardinality", True):
                        # doğru: label'dan çıkar → exemplar olarak bağla (yalnız exemplar_keys)
                        if lab in self.exemplar_keys:
                            self.exemplars_attached += 1
                    else:
                        self.cardinality_violations += 1  # buggy: yüksek-kardinalite label geçti
                if lab in self.pii_keys:
                    if not self.pol.get("enforce_pii", True):
                        self.pii_violations += 1

        # ── span/log/event: attribute PII (G3)  [trace/log yüksek-kardinaliteye izinli]
        if kind in ("span", "log", "event", "adapter_call", "tool_call"):
            attrs = list(em.get("attrs", []))      # emitter'ın attribute/alan olarak koyduğu anahtar ADLARI
            for a in attrs:
                if a in self.pii_keys:
                    if not self.pol.get("enforce_pii", True):
                        self.pii_violations += 1
                    # enforce_pii açıkken: redaction L7 → çıkarılır (no-op burada)

        # ── adapter/tool çağrısı: full adapter bağlamı (G6) + region pin (G7)
        if kind in ADAPTER_KINDS:
            self.adapter_calls += 1
            # adapter_required alanları efektif bağlamda olmalı
            missing_adapter = [k for k in self.adapter_required if not ctx.get(k)]
            if missing_adapter:
                self.adapter_context_missing += 1
            # region pin: emitter farklı region denerse
            target_region = em.get("region")
            if self.pol.get("pin_region", True):
                eff_region = self.home_region        # doğru: home-region'a pinle
                if target_region is not None and target_region != self.home_region:
                    pass  # pin engelledi (doğru davranış); ihlal sayılmaz
            else:
                eff_region = target_region if target_region is not None else ctx.get("region")
                if eff_region is not None and eff_region != self.home_region:
                    self.region_violations += 1  # buggy: home-region dışına yönlendirildi

    def metrics(self):
        scenario = []
        if "metric" in self.kinds:
            scenario.append("metric")
        if self.kinds & ADAPTER_KINDS:
            scenario.append("adapter")
        if self.kinds & {"event", "log", "span"}:
            scenario.append("trace")
        distinct = len(self.correlation_ids)
        # çağrı başına tek correlation_id beklenir; >1 ise süreksizlik
        discontinuity = max(0, distinct - 1)
        return {
            "records_total": self.records_total,
            "context_complete": self.context_complete,
            "missing_context": self.missing_context,
            "cardinality_violations": self.cardinality_violations,
            "pii_violations": self.pii_violations,
            "cross_tenant_violations": self.cross_tenant_violations,
            "illegal_context_mutations": self.illegal_context_mutations,
            "region_violations": self.region_violations,
            "adapter_calls": self.adapter_calls,
            "adapter_context_missing": self.adapter_context_missing,
            "exemplars_attached": self.exemplars_attached,
            "blocked_mutations": self.blocked_mutations,
            "distinct_correlation_ids": distinct,
            "correlation_discontinuity": discontinuity,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, spec, session, policy):
    emissions = sample.get("emissions")
    if not emissions:
        raise ContextError("boş emisyon akışı")
    if not isinstance(emissions, list):
        raise ContextError("emissions liste değil → INVALID_REQUEST")
    indexed = list(enumerate(emissions))
    for _, em in indexed:
        if not isinstance(em, dict) or em.get("kind") not in SURFACES \
                or not isinstance(em.get("t"), (int, float)):
            raise ContextError("geçersiz emisyon: %r → INVALID_REQUEST" % (em,))
    ordered = sorted(indexed, key=lambda pr: (pr[1]["t"], pr[0]))
    cp = ContextPropagator(spec, session, policy)
    for _, em in ordered:
        cp.step(em)
    return cp.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G8) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    sc = set(m.get("scenario", []))

    # ── G1: bağlam tamlığı (her senaryoda)
    F.append((m.get("missing_context", 0) <= g.get("max_missing_context", 0),
              "G1 eksik bağlam %d ≤ %d (her event/log/span/adapter required_keys taşır — SAD §13.3/§17.1)"
              % (m.get("missing_context", 0), g.get("max_missing_context", 0))))

    # ── G4: tenant binding (her senaryoda)
    F.append((m.get("cross_tenant_violations", 0) <= g.get("max_cross_tenant_violation", 0),
              "G4 cross-tenant ihlali %d ≤ %d (kayıt oturum tenant_id'sinden farklı taşımaz — FR-TEN-002)"
              % (m.get("cross_tenant_violations", 0), g.get("max_cross_tenant_violation", 0))))

    # ── G5: correlation continuity (her senaryoda)
    F.append((m.get("correlation_discontinuity", 0) <= g.get("max_correlation_discontinuity", 0),
              "G5 correlation süreksizliği %d ≤ %d (çağrı başına TEK correlation_id; distinct=%d — SAD §17.1)"
              % (m.get("correlation_discontinuity", 0), g.get("max_correlation_discontinuity", 0),
                 m.get("distinct_correlation_ids", 0))))

    # ── G8: immutable mutation (her senaryoda)
    F.append((m.get("illegal_context_mutations", 0) <= g.get("max_illegal_context_mutation", 0),
              "G8 illegal bağlam mutasyonu %d ≤ %d (tenant_id/correlation_id/call_id immutable)"
              % (m.get("illegal_context_mutations", 0), g.get("max_illegal_context_mutation", 0))))

    if "metric" in sc:
        # ── G2: kardinalite disiplini
        F.append((m.get("cardinality_violations", 0) <= g.get("max_cardinality_violation", 0),
                  "G2 kardinalite ihlali %d ≤ %d (yüksek-kardinalite kimlik metrik label olmaz — 0.4.7)"
                  % (m.get("cardinality_violations", 0), g.get("max_cardinality_violation", 0))))

    # ── G3: PII yasağı (label+attribute; metric veya trace senaryosunda anlamlı, her zaman raporla)
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0),
              "G3 PII ihlali %d ≤ %d (PII anahtarı bağlam/label/attribute'ta yok — FR-REC-004)"
              % (m.get("pii_violations", 0), g.get("max_pii_violation", 0))))

    if "adapter" in sc:
        # ── G6: adapter bağlamı
        F.append((m.get("adapter_context_missing", 0) <= g.get("max_adapter_context_missing", 0),
                  "G6 adapter bağlamı eksik %d ≤ %d (giden çağrı correlation_id+tenant_id+region taşır — API §11.1)"
                  % (m.get("adapter_context_missing", 0), g.get("max_adapter_context_missing", 0))))
        # ── G7: region pin
        F.append((m.get("region_violations", 0) <= g.get("max_region_violation", 0),
                  "G7 region ihlali %d ≤ %d (adapter çağrıları home-region'a pinli — NFR 10.7)"
                  % (m.get("region_violations", 0), g.get("max_region_violation", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# oturum + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise ContextError("bilinmeyen profil: %s" % name)


def _resolve_session(spec, profile, sample):
    """Profil region + sample.session → ingress oturum bağlamı."""
    sess = dict(sample.get("session", {}))
    sess.setdefault("region", profile.get("region"))
    return sess


def _resolve_policy(spec, sample):
    pol = {
        "attach_context": True,
        "enforce_cardinality": True,
        "enforce_pii": True,
        "bind_tenant": True,
        "pin_region": True,
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
        except ContextError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    session = _resolve_session(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = simulate(sample, spec, session, policy)
    except ContextError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    print("simulate[%s] senaryo=%s | %d kayıt (tam=%d, eksik=%d) | adapter=%d (bağlam-eksik=%d), "
          "exemplar=%d | distinct correlation_id=%d | cross-tenant=%d, kardinalite=%d, pii=%d, region=%d" % (
              name, "+".join(m["scenario"]) or "-", m["records_total"], m["context_complete"],
              m["missing_context"], m["adapter_calls"], m["adapter_context_missing"], m["exemplars_attached"],
              m["distinct_correlation_ids"], m["cross_tenant_violations"], m["cardinality_violations"],
              m["pii_violations"], m["region_violations"]))
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


def _load_obs_label_policy():
    """0.4.7 observability-spec.json label_policy (varsa) — çapraz-tutarlılık için."""
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "platform", "observability",
                                          "observability-spec.json"))
    if os.path.exists(cand):
        try:
            return _load(cand).get("label_policy", {})
        except Exception:
            return None
    return None


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "3.1.5", "spec.wbs == 3.1.5")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── G9: placement (orchestrator, ingress, kayıt-tetikli, bloklamaz, immutable)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "G9 Propagator orchestrator içinde")
    _check(R, pl.get("established_at_ingress") is True, "G9 bağlam ingress'te kurulur")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "G9 kayıt-tetikli + bloklamaz (FR-RES-012 asenkron/sampling log)")
    _check(R, pl.get("immutable_binding") is True, "G8 immutable binding bayrağı")

    # ── context_model
    cm = spec.get("context_model", {})
    rk = set(cm.get("required_keys", []))
    _check(R, {"tenant_id", "correlation_id"} <= rk,
           "G1 required_keys ⊇ {tenant_id, correlation_id} (SAD §13.3/§17.1)")
    fc = set(cm.get("full_context", []))
    _check(R, {"tenant_id", "org_unit", "agent_id", "correlation_id", "region"} <= fc,
           "G1 full_context SAD §13.3 alanlarını içerir (tenant_id+org_unit+agent_id+correlation_id+region)")
    imk = set(cm.get("immutable_keys", []))
    _check(R, {"tenant_id", "correlation_id", "call_id"} <= imk,
           "G8 immutable_keys ⊇ {tenant_id, correlation_id, call_id}")
    ar = set(cm.get("adapter_call_required", []))
    _check(R, {"correlation_id", "tenant_id", "region"} <= ar,
           "G6 adapter_call_required ⊇ {correlation_id, tenant_id, region} (API §11.1)")
    _check(R, cm.get("single_correlation_id_per_call") is True,
           "G5 single_correlation_id_per_call=true")

    # ── propagation_surfaces
    ps = spec.get("propagation_surfaces", {})
    surf = set(ps.get("surfaces", []))
    _check(R, {"event", "log", "span", "metric", "adapter_call"} <= surf,
           "propagation_surfaces SAD §13.3 yüzeylerini içerir (event/log/span/metric/adapter)")
    _check(R, set(ps.get("context_required_on", [])) >= {"event", "log", "span", "adapter_call"},
           "G1 context_required_on event/log/span/adapter_call içerir")
    _check(R, ps.get("exemplar_only_on") == ["metric"],
           "G2 metric yalnız exemplar (label değil)")

    # ── cardinality_policy (G2) — 0.4.7 ile çapraz-tutarlılık
    cp = spec.get("cardinality_policy", {})
    forb = set(cp.get("metric_labels_forbidden", []))
    high = set(cp.get("high_cardinality_keys", []))
    allowed = set(cp.get("metric_labels_allowed", []))
    _check(R, {"correlation_id", "call_id", "session_id"} <= forb,
           "G2 metric_labels_forbidden ⊇ {correlation_id, call_id, session_id}")
    _check(R, {"correlation_id", "call_id"} <= high, "G2 high_cardinality_keys ⊇ {correlation_id, call_id}")
    _check(R, "correlation_id" in cp.get("exemplar_keys", []),
           "G2 correlation_id exemplar olarak bağlanır")
    _check(R, not (allowed & high), "G2 izinli label kümesi yüksek-kardinalite ile kesişmez")
    _check(R, {"tenant_id", "agent_id", "region"} <= allowed,
           "G2 metric_labels_allowed sınırlı kimlikleri içerir (tenant_id/agent_id/region)")
    obs = _load_obs_label_policy()
    if obs is not None:
        _check(R, set(obs.get("metric_labels_forbidden", [])) == forb,
               "G2 metric_labels_forbidden 0.4.7 observability-spec ile BİREBİR")
        _check(R, set(obs.get("metric_labels_allowed", [])) == allowed,
               "G2 metric_labels_allowed 0.4.7 observability-spec ile BİREBİR")
        _check(R, set(obs.get("high_cardinality_keys", [])) == high,
               "G2 high_cardinality_keys 0.4.7 observability-spec ile BİREBİR")

    # ── pii_policy (G3)
    pp = spec.get("pii_policy", {})
    pk = set(pp.get("forbidden_keys", []))
    _check(R, {"phone_number", "customer_name", "card_number", "otp", "token"} <= pk,
           "G3 pii_policy.forbidden_keys çekirdek PII anahtarlarını içerir")
    _check(R, pp.get("pii_in_labels_forbidden") is True and pp.get("pii_in_attributes_forbidden") is True,
           "G3 PII label+attribute yasağı bayrakları")
    _check(R, not (pk & allowed), "G3 PII anahtarları izinli metrik label'larıyla kesişmez")

    # ── trace_propagation
    tp = spec.get("trace_propagation", {})
    _check(R, tp.get("standard") == "w3c-traceparent", "G5/G6 W3C traceparent standardı (SAD §17.1)")
    _check(R, tp.get("trace_id_stable_per_call") is True, "G5 trace_id çağrı boyu sabit")
    _check(R, tp.get("correlation_id_in_exemplar") is True, "G2 correlation_id exemplar (metrik bağı)")

    # ── residency (G7)
    res = spec.get("residency", {})
    _check(R, res.get("region_pin_required") is True, "G7 residency region pin gerekli")
    _check(R, res.get("adapter_calls_pinned_to_home_region") is True,
           "G7 adapter çağrıları home-region'a pinli (NFR 10.7)")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_missing_context", "max_cardinality_violation", "max_pii_violation",
               "max_cross_tenant_violation", "max_correlation_discontinuity",
               "max_adapter_context_missing", "max_region_violation", "max_illegal_context_mutation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── metrics → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"context_complete_total", "context_missing_total", "cardinality_violation_total",
               "pii_violation_total", "cross_tenant_violation_total"} <= emitted,
           "metrik kümesi propagasyon sağlığını yayar")
    mo = me.get("maps_to_observability", {})
    _check(R, "context_keys" in mo and "trace_log_required_keys" in mo,
           "metrics→observability label_policy bağı (0.4.7)")

    # ── error taxonomy (G10)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "G10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "G10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("missing_context") == "INVALID_REQUEST"
           and mapping.get("cross_tenant_access") == "AUTH"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "G10 missing→INVALID, cross-tenant→AUTH, region→REGION_VIOLATION")

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
        _check(R, len(profs) >= 2, "config ≥2 propagasyon profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "G7 config %s bölge pini var" % p.get("name"))

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
    "call_id": "call-001", "session_id": "sess-001", "trace_id": "tr-001",
}


def _run(emissions, spec, session=None, **pol_over):
    pol = {"attach_context": True, "enforce_cardinality": True, "enforce_pii": True,
           "bind_tenant": True, "pin_region": True}
    pol.update(pol_over)
    return simulate({"emissions": emissions}, spec, session or SESSION, pol)


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: olay+log+span+metrik+adapter → tüm kapılar geçer ────────────────────
    happy = [
        {"t": 0, "kind": "event"},
        {"t": 10, "kind": "log"},
        {"t": 20, "kind": "span"},
        {"t": 30, "kind": "metric", "labels": ["tenant_id", "agent_id", "region", "correlation_id"]},
        {"t": 40, "kind": "adapter_call", "provider": "stt"},
        {"t": 50, "kind": "tool_call", "provider": "crm"},
    ]
    mh = _run(happy, spec)
    case(mh["missing_context"] == 0 and mh["context_complete"] == 5,
         "happy: 5 bağlam-zorunlu kayıt tam (metric hariç)")
    case(mh["cardinality_violations"] == 0 and mh["exemplars_attached"] == 1,
         "happy: correlation_id label değil → exemplar'a taşındı (G2)")
    case(mh["cross_tenant_violations"] == 0 and mh["distinct_correlation_ids"] == 1,
         "happy: tek tenant + tek correlation_id (G4/G5)")
    case(mh["adapter_calls"] == 2 and mh["adapter_context_missing"] == 0,
         "happy: 2 adapter/tool çağrısı tam bağlamlı (G6)")
    case(mh["region_violations"] == 0, "happy: region pin (G7)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")

    # ── adapter region pin: emitter farklı region dener, pin engeller ──────────────
    rp = [{"t": 0, "kind": "adapter_call", "provider": "llm", "region": "us-east-1"}]
    mr = _run(rp, spec)
    case(mr["region_violations"] == 0, "region-pin: pin açıkken farklı region engellenir (ihlal yok)")
    mr2 = _run(rp, spec, pin_region=False)
    case(mr2["region_violations"] == 1, "region-pin KAPALI: farklı region → ihlal (G7 eler)")

    # ── immutable tenant binding: override engellenir ──────────────────────────────
    tb = [{"t": 0, "kind": "event", "tenant_id_override": "t_evil"}]
    mt = _run(tb, spec)
    case(mt["cross_tenant_violations"] == 0 and mt["blocked_mutations"] == 1,
         "tenant-binding: override engellendi, cross-tenant=0 (G4/G8)")
    mt2 = _run(tb, spec, bind_tenant=False)
    case(mt2["cross_tenant_violations"] == 1 and mt2["illegal_context_mutations"] == 1,
         "tenant-binding KAPALI: farklı tenant geçti → cross-tenant+mutasyon (G4/G8 eler)")

    # ── correlation continuity: correlation_id override binding'le korunur ─────────
    cc = [{"t": 0, "kind": "event"}, {"t": 10, "kind": "event", "correlation_id_override": "corr-XXX"}]
    mc = _run(cc, spec)
    case(mc["distinct_correlation_ids"] == 1 and mc["correlation_discontinuity"] == 0,
         "correlation: override binding'le korundu → tek correlation_id (G5)")
    mc2 = _run(cc, spec, bind_tenant=False)
    case(mc2["distinct_correlation_ids"] == 2 and mc2["correlation_discontinuity"] == 1,
         "correlation binding KAPALI: 2 correlation_id → süreksizlik (G5 eler)")

    # ── cardinality: enforce kapalı → yüksek-kardinalite label geçer ───────────────
    card = [{"t": 0, "kind": "metric", "labels": ["tenant_id", "call_id"]}]
    mca = _run(card, spec)
    case(mca["cardinality_violations"] == 0, "cardinality: call_id label enforce ile çıkarıldı")
    mca2 = _run(card, spec, enforce_cardinality=False)
    case(mca2["cardinality_violations"] == 1, "cardinality KAPALI: call_id label geçti (G2 eler)")

    # ── PII: label + attribute ─────────────────────────────────────────────────────
    pii = [{"t": 0, "kind": "metric", "labels": ["tenant_id", "phone_number"]},
           {"t": 10, "kind": "span", "attrs": ["agent_id", "customer_name"]}]
    mp = _run(pii, spec)
    case(mp["pii_violations"] == 0, "pii: enforce açıkken PII label/attribute çıkarıldı")
    mp2 = _run(pii, spec, enforce_pii=False)
    case(mp2["pii_violations"] == 2, "pii KAPALI: phone_number label + customer_name attr (G3 eler)")

    # ── missing context: attach kapalı → required_keys eksik ───────────────────────
    miss = [{"t": 0, "kind": "event"}, {"t": 10, "kind": "adapter_call", "provider": "tts"}]
    mm = _run(miss, spec)
    case(mm["missing_context"] == 0, "attach: bağlam iliştirildi → eksik yok")
    mm2 = _run(miss, spec, attach_context=False)
    case(mm2["missing_context"] == 2 and mm2["adapter_context_missing"] == 1,
         "attach KAPALI: bağlam yok → G1 + adapter G6 eler")

    # ── degraded: çoklu kapı eler ─────────────────────────────────────────────────
    deg = [
        {"t": 0, "kind": "event", "tenant_id_override": "t_other"},
        {"t": 10, "kind": "metric", "labels": ["correlation_id", "phone_number"]},
        {"t": 20, "kind": "adapter_call", "provider": "llm", "region": "ap-south-1"},
    ]
    md = _run(deg, spec, attach_context=False, enforce_cardinality=False, enforce_pii=False,
              bind_tenant=False, pin_region=False)
    Fd = evaluate(spec, md)
    case(md["missing_context"] >= 1, "degraded: eksik bağlam (G1 eler)")
    case(md["cardinality_violations"] >= 1, "degraded: yüksek-kardinalite label (G2 eler)")
    case(md["pii_violations"] >= 1, "degraded: PII label (G3 eler)")
    case(md["region_violations"] >= 1, "degraded: region ihlali (G7 eler)")
    case(not all(ok for ok, _ in Fd), "degraded en az bir kapıyı eler")

    # ── reddetme (G10) ─────────────────────────────────────────────────────────────
    case(_raises(lambda: simulate({"emissions": [{"t": 0, "kind": "nope"}]}, spec, SESSION,
                                  _full_pol())), "G10 bilinmeyen yüzey → reddedilir")
    case(_raises(lambda: simulate({"emissions": [{"kind": "event"}]}, spec, SESSION, _full_pol())),
         "G10 zaman damgasız emisyon → reddedilir")
    case(_raises(lambda: simulate({"emissions": []}, spec, SESSION, _full_pol())),
         "G10 boş emisyon akışı → reddedilir")
    case(_raises(lambda: simulate({"emissions": [{"t": 0, "kind": "event"}]}, spec,
                                  {"tenant_id": "t1"}, _full_pol())),
         "G10 ingress correlation_id eksik → reddedilir")

    # ── sıralama: karışık t → zaman sırasına göre ─────────────────────────────────
    uno = [{"t": 30, "kind": "metric", "labels": ["call_id"]}, {"t": 0, "kind": "event"}]
    mu = _run(uno, spec)
    case(mu["records_total"] == 2 and mu["cardinality_violations"] == 0,
         "sıralama: karışık t işlendi, kardinalite korundu")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["context_model"]["required_keys"] = ["tenant_id"]
    case(_validate_obj(s) != 0, "G1 required_keys'ten correlation_id düşerse → validate eler")
    s = json.loads(json.dumps(spec)); s["cardinality_policy"]["metric_labels_allowed"].append("call_id")
    case(_validate_obj(s) != 0, "G2 izinli label'a call_id eklenirse → validate eler")
    s = json.loads(json.dumps(spec)); s["cardinality_policy"]["metric_labels_forbidden"] = ["call_id"]
    case(_validate_obj(s) != 0, "G2 forbidden'dan correlation_id düşerse → validate eler")
    # agent_id hem izinli metrik label hem PII listesine girerse kesişim → G3 eler
    s = json.loads(json.dumps(spec)); s["pii_policy"]["forbidden_keys"].append("agent_id")
    case(_validate_obj(s) != 0, "G3 PII listesine izinli label (agent_id) eklenirse kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_cross_tenant_violation"] = 1
    case(_validate_obj(s) != 0, "G4 max_cross_tenant_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["context_model"]["single_correlation_id_per_call"] = False
    case(_validate_obj(s) != 0, "G5 single_correlation_id_per_call=false → validate eler")
    s = json.loads(json.dumps(spec)); s["context_model"]["adapter_call_required"] = ["tenant_id"]
    case(_validate_obj(s) != 0, "G6 adapter_call_required'tan region/correlation düşerse → validate eler")
    s = json.loads(json.dumps(spec)); s["residency"]["adapter_calls_pinned_to_home_region"] = False
    case(_validate_obj(s) != 0, "G7 adapter region pin kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["placement"]["immutable_binding"] = False
    case(_validate_obj(s) != 0, "G8 immutable_binding kapalı → validate eler")
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
    return {"attach_context": True, "enforce_cardinality": True, "enforce_pii": True,
            "bind_tenant": True, "pin_region": True}


def _raises(fn):
    try:
        fn()
        return False
    except ContextError:
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
    print("""context-propagation-spec.json beklenen şekli (WBS 3.1.5):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability}
  placement{in_orchestrator=true, established_at_ingress=true, event_driven=true,
            non_blocking=true, immutable_binding=true}                            (G8,G9)
  context_model{required_keys⊇[tenant_id,correlation_id], full_context[],
                immutable_keys⊇[tenant_id,correlation_id,call_id],
                adapter_call_required⊇[correlation_id,tenant_id,region],
                single_correlation_id_per_call=true}                             (G1,G5,G6,G8)
  propagation_surfaces{surfaces[], context_required_on[], exemplar_only_on=[metric]} (G1,G2)
  cardinality_policy{metric_labels_allowed[], metric_labels_forbidden[],
                     high_cardinality_keys[], exemplar_keys[]}  (0.4.7 ile birebir) (G2)
  pii_policy{forbidden_keys[], pii_in_labels_forbidden, pii_in_attributes_forbidden} (G3)
  trace_propagation{standard=w3c-traceparent, trace_id_stable_per_call,
                    correlation_id_in_exemplar}                                   (G5)
  residency{region_pin_required=true, adapter_calls_pinned_to_home_region=true}   (G7)
  gates{max_missing_context=0, max_cardinality_violation=0, max_pii_violation=0,
        max_cross_tenant_violation=0, max_correlation_discontinuity=0,
        max_adapter_context_missing=0, max_region_violation=0,
        max_illegal_context_mutation=0}                            (G1..G8)
  metrics{emitted[], maps_to_observability{context_keys, trace_log_required_keys}}
  error_taxonomy{mapping→API §11.6 (missing→INVALID, cross-tenant→AUTH, region→REGION_VIOLATION)}
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                        (G10)
  invariants[≥10]{id, desc, trace}

config/context-propagation-profiles.json: profiles[]{name, region, ...}

simulate sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  session{tenant_id, correlation_id, region, org_unit?, agent_id?, call_id?, session_id?},
  policy?{attach_context, enforce_cardinality, enforce_pii, bind_tenant, pin_region},
  emissions[{t (ms), kind, labels?[anahtar adı], attrs?[anahtar adı],
             tenant_id_override?, correlation_id_override?, call_id_override?,
             region?, provider?}]}  — kind ∈ {event, log, span, metric, adapter_call, tool_call}
  (PII DEĞERİ YOK — yalnız anahtar ADLARI)

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: context_propagation_probe.py simulate <sample.json>")
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
