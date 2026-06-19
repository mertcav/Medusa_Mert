#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_alarms_probe.py — WBS 14.1.5 Alarm kuralları (BRD §15) + ≤2dk üretim

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-logger/` (14.1.4) + `call-resource/` (14.1.3) + `call-metrics/` (14.1.2) + `call-trace/`
(14.1.1) probe disipliniyle birebir; burada deterministik bir CONVERSATION ORCHESTRATOR ALARM RULE
ENGINE (SAD §17.2 'Alarm (BRD §15)') simülatörü (saf; random YOK).

ALARM RULE ENGINE (Çekirdek IP, SAD §6 / §17) — orchestrator gözlemlenebilirlik emisyon yolunda
metrik/güvenlik/kapasite sinyallerini kural-tabanlı değerlendirir ve alarmı ≤2dk ÜRETİR:
  • Kapsam (G1):       BRD §15 kritik alarm kataloğunun her maddesi bir kural taşır (11/11; 0.4.7'den türetilir).
  • Katalog (G2):      kural adı + severity 0.4.7 alerts.catalog + alerts.yaml ile BİREBİR.
  • Bütçe (G3):        her kural ingest+eval+for+notify ≤ 120s (NFR 10.1 'alarm ≤2dk üretim') — BİRİNCİL kapı.
  • Sinyal (G4):       her kuralın sinyali signal_catalog'da (metric_signals 0.4.7 metrics.catalog BİREBİR) — orphan yok.
  • Kardinalite (G5):  alarm etiketi yüksek-kardinalite kimlik taşımaz + yalnız alarm_labels_allowed.
  • PII/scope (G6):    etikette PII yok (FR-REC-004) + scope=tenant alarmı tenant_id taşır (izolasyon).
  • Flap/dedup (G7):   for_s>0 flap bastırır + aynı (alertname,tenant_id) tek alarma daraltılır.
  • Routing (G8):      her alarm severity→kanal + scope→kitleye yönlenir (unrouted yok).

KAPSAM AYRIMI: span üretimi → 14.1.1 · teknik metrik DEĞERLERİ → 14.1.2 · per-call CPU/bellek → 14.1.3 ·
yapılandırılmış log → 14.1.4 · metrik/alarm KATALOĞU + collector guard → 0.4.7 · gerçek zamanlı op ekranı
(≤60sn) → 14.1.6 / FR-ANA-012. Burada YALNIZ alarm kuralları + ≤2dk üretim disiplini.

Komutlar:
  validate              call-alarms-spec.json'ı invariant'lara + 0.4.7 çapraz-tutarlılığa + config'e + alerts.yaml'a karşı doğrular.
  evaluate <sample>     Deterministik AlarmRuleEngine — sinyal seti → üretilen alarm + detection latency + HARD kapılar (G1–G8); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. evaluate gerçek Prometheus/Alertmanager yerine deterministik simülasyondur
(canlı sistemde Prometheus scrape/eval + Alertmanager, SAD §11/§17.2; ADR-003 runtime sinyal emisyonu).
Ham ses payload/transkript/PII DEĞERİ YOK — örnekler yalnız sinyal + kimlik/etiket anahtarı ADLARI taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "call-alarms-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "call-alarms-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# Etiket DEĞERİ redaction (FR-REC-004): ham PII DEĞER desenleri. alertname/severity/tenant_id/region
# vb. KİMLİK/sınıf (PII değil) — ardışık ≥7 rakam içermez.
PII_VALUE_RE = re.compile(
    r"(?:\d[ \-]?){7,}"                                   # ≥7 ardışık rakam (telefon/kart/IBAN)
    r"|[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"  # e-posta
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"                  # IBAN
)


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class AlarmError(Exception):
    """Geçersiz/eksik sinyal demeti veya bilinmeyen kural — sessizce kabul yok, reddet (G10/I11)."""


def _cmp(value, comparator, threshold):
    if comparator == "gt":
        return value > threshold
    if comparator == "ge":
        return value >= threshold
    raise AlarmError("bilinmeyen comparator: %s → INVALID_REQUEST" % comparator)


# ─────────────────────────────────────────────────────────────────────────────
# Alarm Rule Engine — kural-tabanlı alarm üretimi (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class AlarmRuleEngine:
    """SAD §17.2 'Alarm (BRD §15)' Alarm Rule Engine. Orchestrator emisyon yolundaki metrik/güvenlik/
    kapasite sinyallerini kurallara göre değerlendirir + detection budget'ı (≤120s, NFR 10.1) uygular +
    alarm etiketi kardinalite/PII + tenant scope + flap/dedup + severity routing disiplinine karşı denetler.
    Saf; random YOK.

    policy bayrakları buggy bir Engine'i simüle eder (call-logger/call-resource deseni):
      cover_all          : tüm kataloğu kapsa (kapalı → bir kural kataloğdan düşer, G1)
      honor_budget       : for_s'i spec'ten al (kapalı → for_s şişer → detection > 120s, G3)
      map_signals        : sinyali signal_catalog'a eşle (kapalı → orphan sinyal, G4)
      enforce_cardinality: kimliği alarm label yapma (kapalı → correlation_id alarm label, G5)
      enforce_labels     : yalnız izinli alarm label (kapalı → sınırsız label, G5)
      enforce_pii        : PII anahtarını alarm label'dan çıkar (kapalı → phone_number alarm label, G6)
      scope_tenant       : scope=tenant alarmına tenant_id ekle (kapalı → tenant alarmı global, G6 izolasyon)
      debounce           : for_s>0 flap bastır (kapalı → geçici blip alarm üretir, G7)
      dedup              : aynı (alertname,tenant_id) daralt (kapalı → çift alarm, G7)
      route_severity     : severity→kanal yönlendir (kapalı → unrouted alarm, G8)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        self.rules = {r["name"]: r for r in spec.get("rules", [])}
        self.max_budget = spec.get("detection_budget", {}).get("max_detection_budget_s", 120)

        lp = spec.get("label_policy", {})
        self.labels_allowed = set(lp.get("alarm_labels_allowed", []))
        self.high_card = set(lp.get("high_cardinality_keys", []))
        self.pii_keys = set(lp.get("pii_forbidden_keys", []))

        sc = spec.get("signal_catalog", {})
        self.signal_catalog = set(sc.get("metric_signals", []))
        self.signal_catalog |= {s["name"] for s in sc.get("security_capacity_signals", [])}

        self.routing = spec.get("routing", {})
        self.severity_channels = self.routing.get("severity_channels", {})
        self.scope_audience = self.routing.get("scope_audience", {})

        # deployment zamanlaması (profil)
        self.scrape_s = profile.get("ingest_scrape_s", 15)
        self.eval_s = profile.get("eval_interval_s", 15)
        self.notify_s = profile.get("notify_lag_s", 10)

        if not self.context.get("tenant_id"):
            raise AlarmError("değerlendirme bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise AlarmError("değerlendirme bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.coverage_missing = 0
        self.catalog_mismatch = 0
        self.budget_violations = 0
        self.orphan_signals = 0
        self.cardinality_violations = 0
        self.label_violations = 0
        self.pii_violations = 0
        self.scope_violations = 0
        self.flap_violations = 0
        self.dedup_violations = 0
        self.routing_violations = 0

        self.fired = []          # üretilen alarm event'leri
        self.max_detection_latency = 0
        self.per_rule_latency = {}
        self.derived = {}

    # ── kural başına detection latency (ingest+eval+for+notify) ────────────────
    def _detection_latency(self, rule):
        for_s = rule.get("for_s", 0)
        if not self.pol.get("honor_budget", True):
            # buggy: for_s şişir (örn. flap'ı bastırmak için aşırı dwell) → bütçe aşımı
            for_s = for_s + 90
        return self.scrape_s + self.eval_s + for_s + self.notify_s

    # ── alarm etiketleri (DÜŞÜK kardinalite + tenant scope) ────────────────────
    def _labels(self, rule):
        out = {"alertname": rule["name"], "severity": rule["severity"], "region": self.context.get("region")}
        if rule.get("category"):
            out["category"] = rule["category"]
        # scope=tenant → tenant_id (izolasyon, G6). scope=platform → global (tenant_id YOK)
        if rule.get("scope") == "tenant":
            if self.pol.get("scope_tenant", True):
                out["tenant_id"] = self.context.get("tenant_id")
            # buggy: scope_tenant kapalı → tenant alarmı tenant_id taşımaz (global yönlenir, sızıntı)
        # buggy: kimliği ALARM LABEL yap (G5)
        if not self.pol.get("enforce_cardinality", True):
            out["correlation_id"] = self.context.get("correlation_id", "corr-x")
        # buggy: PII anahtarını ALARM LABEL yap (G6) — DEĞER yok, yalnız anahtar adı
        if not self.pol.get("enforce_pii", True):
            out["phone_number"] = "<redacted>"
        # buggy: izinsiz (yüksek-kardinalite/PII olmayan) label (G5 label)
        if not self.pol.get("enforce_labels", True):
            out["unbounded_dim"] = "x"
        return out

    def run(self, signals):
        spec_rule_names = list(self.rules.keys())

        # 0) KAPSAM (G1): BRD §15 gerekli alarm kataloğu (0.4.7'den türetilir, non-circular)
        required = set(self.spec.get("_required_alarms", spec_rule_names))
        active = set(spec_rule_names)
        if not self.pol.get("cover_all", True):
            # buggy: bir kural kataloğdan düşer
            if active:
                active.discard(sorted(active)[0])
        self.coverage_missing = len(required - active)

        # 1) yapısal kapılar — her AKTİF kural için (firing'den bağımsız)
        for name in sorted(active):
            rule = self.rules[name]
            # G3 detection budget
            lat = self._detection_latency(rule)
            self.per_rule_latency[name] = lat
            self.max_detection_latency = max(self.max_detection_latency, lat)
            if lat > self.max_budget:
                self.budget_violations += 1
            # G4 signal mapping (orphan yok)
            sig = rule.get("signal")
            if self.pol.get("map_signals", True):
                if sig not in self.signal_catalog:
                    self.orphan_signals += 1
            else:
                self.orphan_signals += 1   # buggy: eşleme yok → orphan

        # 2) firing değerlendirme + alarm event üretimi
        groups = {}   # (alertname, tenant_id) → count (dedup)
        for sig in signals:
            rname = sig.get("rule")
            rule = self.rules.get(rname)
            if rule is None:
                raise AlarmError("bilinmeyen kural: %s → INVALID_REQUEST" % rname)
            value = sig.get("value")
            if value is None:
                raise AlarmError("sinyal değeri (value) eksik: %s → INVALID_REQUEST" % rname)
            fired = _cmp(value, rule.get("comparator", "gt"), rule.get("threshold", 0))
            if not fired:
                continue

            # G7 flap: geçici (transient) tetik for_s'ten kısa + debounce kapalı → yanlış alarm
            transient = bool(sig.get("transient", False))
            for_s = rule.get("for_s", 0)
            if transient and not self.pol.get("debounce", True) and for_s > 0:
                self.flap_violations += 1
            # for_s=0 güvenlik alarmı: geçici-blip toleransı yok (her tetik gerçek), flap sayılmaz

            labels = self._labels(rule)

            # G5 kardinalite + label denetimi
            for k in labels.keys():
                if k in self.high_card:
                    self.cardinality_violations += 1
                if k in self.pii_keys:
                    self.pii_violations += 1            # G6 PII (label)
                elif k not in self.labels_allowed:
                    self.label_violations += 1

            # G6 scope izolasyon: tenant alarmı tenant_id taşımalı
            if rule.get("scope") == "tenant" and "tenant_id" not in labels:
                self.scope_violations += 1

            # G8 routing: severity→kanal + scope→kitle
            channels = self.severity_channels.get(rule["severity"], [])
            audience = self.scope_audience.get(rule.get("scope"), [])
            if not self.pol.get("route_severity", True) or not channels:
                self.routing_violations += 1
                channels = []

            ev = {"alertname": rule["name"], "severity": rule["severity"], "scope": rule.get("scope"),
                  "labels": labels, "detection_latency_s": self.per_rule_latency.get(rname),
                  "channels": channels, "audience": audience}
            self.fired.append(ev)

            gkey = (rule["name"], labels.get("tenant_id"))
            groups[gkey] = groups.get(gkey, 0) + 1

        # 3) G7 dedup: aynı (alertname,tenant_id) > 1 ise dedup kapalıyken ihlal
        for gkey, cnt in groups.items():
            if cnt > 1:
                if self.pol.get("dedup", True):
                    pass   # daraltılır (tek alarm) — ihlal değil
                else:
                    self.dedup_violations += cnt - 1

        self.derived["active_rules"] = len(active)
        self.derived["required_rules"] = len(required)
        self.derived["fired"] = len(self.fired)
        self.derived["max_detection_latency_s"] = self.max_detection_latency
        self.derived["max_budget_s"] = self.max_budget
        self.derived["scrape_eval_notify_s"] = self.scrape_s + self.eval_s + self.notify_s
        self.derived["dedup_groups"] = len(groups)

    def metrics(self):
        return {
            "coverage_missing": self.coverage_missing,
            "catalog_mismatch": self.catalog_mismatch,
            "budget_violations": self.budget_violations,
            "orphan_signals": self.orphan_signals,
            "cardinality_violations": self.cardinality_violations,
            "label_violations": self.label_violations,
            "pii_violations": self.pii_violations,
            "scope_violations": self.scope_violations,
            "flap_violations": self.flap_violations,
            "dedup_violations": self.dedup_violations,
            "routing_violations": self.routing_violations,
            "fired": len(self.fired),
            "per_rule_latency": dict(self.per_rule_latency),
            "derived": dict(self.derived),
        }


def evaluate_call(sample, spec, profile, context, policy):
    signals = sample.get("signals")
    if not isinstance(signals, list):
        raise AlarmError("sinyal seti (signals) liste değil → INVALID_REQUEST")
    for sig in signals:
        if not isinstance(sig, dict) or "rule" not in sig:
            raise AlarmError("sinyal (signal) sözlük değil veya rule eksik → INVALID_REQUEST")
    eng = AlarmRuleEngine(spec, profile, context, policy)
    eng.run(signals)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G8) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    F = []
    F.append((m.get("coverage_missing", 0) <= g.get("max_coverage_missing", 0),
              "G1 kapsam eksik %d ≤ %d (BRD §15 kritik alarm kataloğu %d/%d kural — 0.4.7'den türetilir)"
              % (m.get("coverage_missing", 0), g.get("max_coverage_missing", 0),
                 d.get("active_rules", 0), d.get("required_rules", 0))))
    F.append((m.get("catalog_mismatch", 0) <= g.get("max_catalog_mismatch", 0),
              "G2 katalog uyuşmazlığı %d ≤ %d (kural adı+severity 0.4.7 alerts.catalog/alerts.yaml BİREBİR)"
              % (m.get("catalog_mismatch", 0), g.get("max_catalog_mismatch", 0))))
    F.append((m.get("budget_violations", 0) <= g.get("max_budget_violation", 0),
              "G3 detection bütçe ihlali %d ≤ %d (ingest+eval+for+notify ≤ %ds; max=%ds — NFR 10.1 alarm ≤2dk)"
              % (m.get("budget_violations", 0), g.get("max_budget_violation", 0),
                 d.get("max_budget_s", 120), d.get("max_detection_latency_s", 0))))
    F.append((m.get("orphan_signals", 0) <= g.get("max_orphan_signal", 0),
              "G4 orphan sinyal %d ≤ %d (her kuralın sinyali signal_catalog'da — 0.4.7 metrics.catalog BİREBİR)"
              % (m.get("orphan_signals", 0), g.get("max_orphan_signal", 0))))
    F.append((m.get("cardinality_violations", 0) <= g.get("max_cardinality_violation", 0)
              and m.get("label_violations", 0) <= g.get("max_label_violation", 0),
              "G5 alarm-label ihlali kardinalite=%d label=%d ≤ 0 (kimlik annotation/exemplar + yalnız allowed — 0.4.7 label_policy)"
              % (m.get("cardinality_violations", 0), m.get("label_violations", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0)
              and m.get("scope_violations", 0) <= g.get("max_scope_violation", 0),
              "G6 PII/scope ihlali pii=%d scope=%d ≤ 0 (etikette PII yok FR-REC-004 + scope=tenant→tenant_id izolasyon)"
              % (m.get("pii_violations", 0), m.get("scope_violations", 0))))
    F.append((m.get("flap_violations", 0) <= g.get("max_flap_violation", 0)
              and m.get("dedup_violations", 0) <= g.get("max_dedup_violation", 0),
              "G7 flap/dedup ihlali flap=%d dedup=%d ≤ 0 (for_s>0 flap bastırır + (alertname,tenant_id) daraltılır)"
              % (m.get("flap_violations", 0), m.get("dedup_violations", 0))))
    F.append((m.get("routing_violations", 0) <= g.get("max_routing_violation", 0),
              "G8 routing ihlali %d ≤ %d (her alarm severity→kanal + scope→kitleye yönlenir — unrouted yok)"
              % (m.get("routing_violations", 0), g.get("max_routing_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise AlarmError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _resolve_policy(spec, sample):
    pol = {
        "cover_all": True,
        "honor_budget": True,
        "map_signals": True,
        "enforce_cardinality": True,
        "enforce_labels": True,
        "enforce_pii": True,
        "scope_tenant": True,
        "debounce": True,
        "dedup": True,
        "route_severity": True,
    }
    pol.update(sample.get("policy", {}))
    return pol


def evaluate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    _inject_required(spec)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")

    if "profile_obj" in sample:
        profile = sample["profile_obj"]
    else:
        cfg = _load(PROFILES_CFG)
        try:
            profile = _profile_by_name(cfg, sample.get("profile", cfg.get("default_profile")))
        except AlarmError as ex:
            print("evaluate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = evaluate_call(sample, spec, profile, context, policy)
    except AlarmError as ex:
        print("evaluate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("evaluate[%s] %d sinyal → %d alarm üretildi | kapsam=%d katalog=%d bütçe=%d orphan=%d kardinalite=%d label=%d pii=%d scope=%d flap=%d dedup=%d routing=%d" % (
        name, len(sample.get("signals", [])), m["fired"], m["coverage_missing"], m["catalog_mismatch"],
        m["budget_violations"], m["orphan_signals"], m["cardinality_violations"], m["label_violations"],
        m["pii_violations"], m["scope_violations"], m["flap_violations"], m["dedup_violations"],
        m["routing_violations"]))
    print("  detection: scrape+eval+notify=%ds + for(kural) → max=%ds ≤ %ds (NFR 10.1) | aktif kural=%d/%d | dedup grup=%d" % (
        d.get("scrape_eval_notify_s"), d.get("max_detection_latency_s"), d.get("max_budget_s"),
        d.get("active_rules"), d.get("required_rules"), d.get("dedup_groups")))
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


def _scan_pii_values(obj, path="root"):
    """spec/config'te ham PII DEĞERİ (telefon/email/IBAN) tara — yalnız anahtar ADI olmalı."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("$"):
                continue
            hits += _scan_pii_values(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_pii_values(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if PII_VALUE_RE.search(obj):
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


def _load_alerts_yaml():
    """0.4.7 config/alerts.yaml (varsa) — kural adı + severity + for: çıkarımı (mini-parser, stdlib-only)."""
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "platform", "observability",
                                          "config", "alerts.yaml"))
    if not os.path.exists(cand):
        return None
    rules = {}
    cur = None
    with open(cand, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            ma = re.match(r"-?\s*alert:\s*(\S+)", s)
            if ma:
                cur = ma.group(1)
                rules[cur] = {}
                continue
            if cur is None:
                continue
            mf = re.match(r"for:\s*(\S+)", s)
            if mf:
                rules[cur]["for"] = mf.group(1)
            msv = re.search(r"severity:\s*([a-z]+)", s)
            if msv:
                rules[cur]["severity"] = msv.group(1)
    return rules


def _for_to_seconds(v):
    """'1m'/'2m'/'30s'/'90' → saniye."""
    v = str(v).strip()
    m = re.match(r"^(\d+)(s|m|h)?$", v)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def _inject_required(spec):
    """KAPSAM (G1, non-circular): gerekli alarm kataloğunu 0.4.7 observability-spec alerts.catalog'tan
    türet (probe-sabiti DEĞİL). 0.4.7 yoksa spec kurallarına düş (kendi-kendine kapsam)."""
    obs = _load_observability_spec()
    if obs is not None:
        cat = obs.get("alerts", {}).get("catalog", [])
        names = [c.get("name") for c in cat if c.get("name")]
        if names:
            spec["_required_alarms"] = names
            return spec["_required_alarms"]
    spec["_required_alarms"] = [r["name"] for r in spec.get("rules", [])]
    return spec["_required_alarms"]


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.1.5", "spec.wbs == 14.1.5")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (NFR 10.1)")
    ad = spec.get("alarm_doc", {})
    for k in ("brd", "nfr", "sad", "adr", "api", "fr", "observability", "upstream"):
        _check(R, bool(ad.get(k)), "alarm_doc.%s mevcut" % k)

    # ── G8 placement
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True, "G8 Engine orchestrator içinde")
    _check(R, pl.get("emission_path") is True, "G8 emisyon yolunda")
    _check(R, pl.get("rule_based") is True, "G8 kural-tabanlı")
    _check(R, pl.get("severity_routing") is True, "G8 severity routing")
    _check(R, pl.get("tenant_scoped_routing") is True, "G6/G8 tenant-scoped routing")
    _check(R, pl.get("from_trace") is False, "G8 from_trace=false (sinyal değerlendirme, trace türetme değil)")

    # ── detection_budget (G3 / NFR 10.1)
    db = spec.get("detection_budget", {})
    _check(R, db.get("max_detection_budget_s") == 120, "G3 max_detection_budget_s = 120 (NFR 10.1 ≤2dk)")
    _check(R, db.get("components") == ["ingest_scrape_s", "eval_interval_s", "for_s", "notify_lag_s"],
           "G3 bileşenler = ingest+eval+for+notify")

    # ── rules (G1 kapsam + G3 budget + G4 signal)
    rules = spec.get("rules", [])
    rnames = [r.get("name") for r in rules]
    _check(R, len(rnames) == len(set(rnames)) and len(rnames) == 11, "G1 11 benzersiz kural")
    sc = spec.get("signal_catalog", {})
    metric_signals = set(sc.get("metric_signals", []))
    all_signals = metric_signals | {s.get("name") for s in sc.get("security_capacity_signals", [])}
    comparators = set(spec.get("comparators", []))
    for r in rules:
        _check(R, r.get("severity") in ("critical", "warning"),
               "kural %s severity ∈ critical/warning" % r.get("name"))
        _check(R, r.get("scope") in ("platform", "tenant"),
               "kural %s scope ∈ platform/tenant" % r.get("name"))
        _check(R, r.get("comparator") in comparators,
               "kural %s comparator ∈ comparators" % r.get("name"))
        _check(R, r.get("signal") in all_signals,
               "G4 kural %s sinyali signal_catalog'da (orphan yok)" % r.get("name"))
        _check(R, isinstance(r.get("for_s"), int) and r.get("for_s") >= 0,
               "kural %s for_s ≥ 0" % r.get("name"))
        _check(R, bool(r.get("brd15")) and bool(r.get("sad172")) and bool(r.get("expr_hint")),
               "kural %s brd15/sad172/expr_hint var" % r.get("name"))

    # ── G3 budget: en geniş profil + en geniş for_s ≤ 120 (statik headroom kontrolü)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        worst_over = 0
        for p in cfg.get("profiles", []):
            over = p.get("ingest_scrape_s", 15) + p.get("eval_interval_s", 15) + p.get("notify_lag_s", 10)
            worst_over = max(worst_over, over)
        worst_for = max((r.get("for_s", 0) for r in rules), default=0)
        _check(R, worst_over + worst_for <= db.get("max_detection_budget_s", 120),
               "G3 en kötü profil ek-yük (%ds) + en geniş for_s (%ds) ≤ 120s (NFR 10.1)" % (worst_over, worst_for))

    # ── label_policy (G5/G6; 0.4.7 hizalı)
    lp = spec.get("label_policy", {})
    allowed = set(lp.get("alarm_labels_allowed", []))
    high = set(lp.get("high_cardinality_keys", []))
    pii = set(lp.get("pii_forbidden_keys", []))
    _check(R, {"alertname", "severity", "tenant_id", "region", "category"} <= allowed,
           "G5 alarm_labels_allowed çekirdek yönlendirme etiketlerini içerir")
    _check(R, {"correlation_id", "call_id", "customer_id", "session_id"} <= high,
           "G5 high_cardinality_keys çekirdek kimlikleri içerir")
    _check(R, {"phone_number", "token", "transcript_text", "audio_payload"} <= pii,
           "G6 pii_forbidden_keys çekirdek PII anahtarlarını içerir")
    _check(R, not (allowed & high), "G5 izinli alarm label ile yüksek-kardinalite kesişmez")
    _check(R, not (allowed & pii), "G6 izinli alarm label ile PII kesişmez")

    # ── routing (G8)
    rt = spec.get("routing", {})
    _check(R, set(rt.get("severity_channels", {}).keys()) == {"critical", "warning"},
           "G8 severity_channels = critical/warning")
    _check(R, all(rt.get("severity_channels", {}).values()), "G8 her severity ≥1 kanal")
    _check(R, set(rt.get("scope_audience", {}).keys()) == {"platform", "tenant"},
           "G8 scope_audience = platform/tenant")
    _check(R, "rmc_l0_sre" in rt.get("scope_audience", {}).get("platform", []),
           "G8 platform alarmı RMC L0 SRE'ye")
    tenant_aud = rt.get("scope_audience", {}).get("tenant", [])
    _check(R, "tenant_security_compliance_officer" in tenant_aud,
           "G6/G8 tenant alarmı tenant security_compliance_officer'a (altın kural)")

    # ── flap_control (G7)
    fc = spec.get("flap_control", {})
    _check(R, fc.get("debounce_via_for") is True, "G7 for_s ile flap bastırma")
    _check(R, fc.get("dedup_group_keys") == ["alertname", "tenant_id"], "G7 dedup grup anahtarı (alertname,tenant_id)")
    _check(R, fc.get("auto_resolve") is True, "G7 auto-resolve")

    # ── 0.4.7 observability-spec BİREBİR (G2)
    obs = _load_observability_spec()
    if obs is not None:
        ocat = obs.get("alerts", {}).get("catalog", [])
        oby = {c.get("name"): c for c in ocat}
        _check(R, obs.get("alerts", {}).get("max_detection_budget_s") == db.get("max_detection_budget_s"),
               "G2 0.4.7 alerts.max_detection_budget_s (%s) = spec (NFR 10.1)" % obs.get("alerts", {}).get("max_detection_budget_s"))
        _check(R, set(oby.keys()) == set(rnames),
               "G2 kural adları 0.4.7 alerts.catalog ile BİREBİR (kapsam, non-circular)")
        sev_ok = all(oby.get(r["name"], {}).get("severity") == r["severity"] for r in rules if r["name"] in oby)
        _check(R, sev_ok, "G2 severity 0.4.7 alerts.catalog ile BİREBİR")
        bud_ok = all(oby.get(r["name"], {}).get("detection_budget_s", 120) <= 120 for r in rules if r["name"] in oby)
        _check(R, bud_ok, "G2 0.4.7 detection_budget_s ≤ 120 (NFR 10.1)")
        # metric_signals 0.4.7 metrics.catalog BİREBİR (G4)
        ometrics = {m.get("name") for m in obs.get("metrics", {}).get("catalog", [])}
        _check(R, metric_signals == ometrics,
               "G4 metric_signals 0.4.7 metrics.catalog (20) ile BİREBİR (%d/%d)" % (len(metric_signals), len(ometrics)))
        # label_policy hizası (G5/G6)
        olp = obs.get("label_policy", {})
        _check(R, set(olp.get("high_cardinality_keys", [])) == high,
               "G5 high_cardinality_keys 0.4.7 label_policy ile birebir")

    # ── alerts.yaml çapraz-kontrol (G2 + G3): kural adı + severity + for ≤ 120 + runtime for_s ≤ yaml for
    alerts = _load_alerts_yaml()
    if alerts is not None:
        _check(R, set(alerts.keys()) == set(rnames),
               "G2 alerts.yaml kural adları spec ile BİREBİR (%d kural)" % len(alerts))
        sev_match = all(alerts.get(r["name"], {}).get("severity") == r["severity"]
                        for r in rules if r["name"] in alerts)
        _check(R, sev_match, "G2 alerts.yaml severity spec ile BİREBİR")
        budget_ok = True
        runtime_le_yaml = True
        for r in rules:
            yfor = alerts.get(r["name"], {}).get("for")
            if yfor is None:
                continue
            ysec = _for_to_seconds(yfor)
            if ysec is None or ysec > 120:
                budget_ok = False
            if r.get("for_s", 0) > (ysec if ysec is not None else 120):
                runtime_le_yaml = False
        _check(R, budget_ok, "G3 alerts.yaml her for: ≤ 120s (0.4.7 NFR 10.1)")
        _check(R, runtime_le_yaml, "G3 runtime for_s ≤ alerts.yaml for: (runtime tightens-or-equals; tutarlı)")

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_coverage_missing", "max_catalog_mismatch", "max_budget_violation", "max_orphan_signal",
               "max_cardinality_violation", "max_label_violation", "max_pii_violation", "max_scope_violation",
               "max_flap_violation", "max_dedup_violation", "max_routing_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I11)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "I11 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "I11 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("malformed_signal") == "INVALID_REQUEST"
           and mapping.get("unknown_rule") == "INVALID_REQUEST"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "I11 malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION")

    # ── pii (spec sağlığı, I12)
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True, "I12 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True, "I12 transkript spec'te yasak")
    _check(R, spec.get("pii", {}).get("pii_values_in_spec_forbidden") is True, "I12 PII DEĞERİ spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 12, "invariant kataloğu ≥12 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])), "her invariant trace taşır")

    # ── literal sır + PII DEĞER taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "I12 literal sır yok (spec+config)")
    pii_hits = _scan_pii_values(spec)
    if os.path.exists(PROFILES_CFG):
        pii_hits += _scan_pii_values(_load(PROFILES_CFG))
    _check(R, not pii_hits, "I12 spec/config'te ham PII DEĞERİ yok (%s)" % (",".join(p for p, _ in pii_hits[:3]) or "-"))

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 profil")
        pnames = [p.get("name") for p in profs]
        _check(R, len(pnames) == len(set(pnames)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "residency config %s bölge pini var" % p.get("name"))
            _check(R, all(isinstance(p.get(k), int) and p.get(k) > 0
                          for k in ("ingest_scrape_s", "eval_interval_s", "notify_lag_s")),
                   "config %s zamanlama (scrape/eval/notify) > 0" % p.get("name"))

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
CONTEXT = {"tenant_id": "t_acme", "org_unit": "ou_support", "region": "eu-west-1",
           "correlation_id": "corr-acme-001"}
PROFILE = {"name": "eu-standard", "region": "eu-west-1",
           "ingest_scrape_s": 15, "eval_interval_s": 15, "notify_lag_s": 10}

# tipik bir alarm değerlendirmesi: birkaç sinyal eşiği aşar (alarm üretir), bazıları aşmaz.
SIGNALS = [
    {"rule": "E2EP95LatencyHigh", "value": 1800},        # > 1500 → fires
    {"rule": "STTErrorRateHigh", "value": 3},            # > 0 → fires
    {"rule": "LLMProviderErrorRateHigh", "value": 0.02}, # ≤ 0.05 → no fire
    {"rule": "ConsentSkipDetected", "value": 1},         # > 0 → fires (tenant scope)
    {"rule": "TenantCapacity80", "value": 0.85},         # > 0.8 → fires (tenant scope)
    {"rule": "ResourceBudgetExceeded", "value": 12000000},  # ≤ 15MB → no fire
]


def _full_pol():
    return {"cover_all": True, "honor_budget": True, "map_signals": True, "enforce_cardinality": True,
            "enforce_labels": True, "enforce_pii": True, "scope_tenant": True, "debounce": True,
            "dedup": True, "route_severity": True}


def _run(signals, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    return evaluate_call({"signals": signals}, spec, profile or PROFILE, context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except AlarmError:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    _inject_required(spec)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── happy: tüm kapılar geçer ──
    mh = _run(SIGNALS, spec)
    case(mh["coverage_missing"] == 0, "happy: kapsam tam 11/11 (G1)")
    case(mh["catalog_mismatch"] == 0, "happy: katalog BİREBİR (G2)")
    case(mh["budget_violations"] == 0, "happy: detection bütçe ≤120s (G3)")
    case(mh["orphan_signals"] == 0, "happy: orphan sinyal yok (G4)")
    case(mh["cardinality_violations"] == 0 and mh["label_violations"] == 0, "happy: alarm-label disiplinli (G5)")
    case(mh["pii_violations"] == 0 and mh["scope_violations"] == 0, "happy: PII/scope temiz (G6)")
    case(mh["flap_violations"] == 0 and mh["dedup_violations"] == 0, "happy: flap/dedup temiz (G7)")
    case(mh["routing_violations"] == 0, "happy: routing tam (G8)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    case(mh["fired"] == 4, "happy: 4 alarm üretildi (2 critical + consent + capacity)")
    d = mh["derived"]
    case(d["max_detection_latency_s"] == 100, "happy: max detection latency = 40+60 = 100s ≤ 120s")
    case(d["active_rules"] == 11 and d["required_rules"] == 11, "happy: 11/11 aktif/gerekli")

    # ── G3 detection budget: low-latency profil daha düşük latency ──
    mll = _run(SIGNALS, spec, profile={"name": "ll", "region": "eu-west-1",
                                        "ingest_scrape_s": 10, "eval_interval_s": 10, "notify_lag_s": 5})
    case(mll["derived"]["max_detection_latency_s"] == 85, "low-latency profil: max latency = 25+60 = 85s")
    case(mll["budget_violations"] == 0, "low-latency profil bütçe geçer")

    # ── determinizm ──
    a = _run(SIGNALS, spec)
    b = _run(SIGNALS, spec)
    case(a == b, "determinizm: aynı sinyal aynı sonucu verir (saf; random yok)")

    # ── G1 kapsam: cover_all KAPALI → bir kural düşer ──
    m1 = _run(SIGNALS, spec, cover_all=False)
    case(m1["coverage_missing"] >= 1, "cover_all KAPALI: bir kural kataloğdan düşer → G1 eler")

    # ── G3 bütçe: honor_budget KAPALI → for_s şişer → detection > 120s ──
    m3 = _run(SIGNALS, spec, honor_budget=False)
    case(m3["budget_violations"] >= 1, "honor_budget KAPALI: for_s şişer → detection > 120s → G3 eler")
    case(m3["derived"]["max_detection_latency_s"] > 120, "honor_budget KAPALI: max latency > 120s")
    # ── G3 bütçe: geniş profil (yavaş scrape/eval) → bütçe aşımı ──
    mslow = _run(SIGNALS, spec, profile={"name": "slow", "region": "eu-west-1",
                                         "ingest_scrape_s": 40, "eval_interval_s": 40, "notify_lag_s": 20})
    case(mslow["budget_violations"] >= 1, "yavaş profil (80s ek-yük + 60s for) → detection 140s > 120 → G3 eler")

    # ── G4 orphan: map_signals KAPALI → orphan sinyal ──
    m4 = _run(SIGNALS, spec, map_signals=False)
    case(m4["orphan_signals"] >= 1, "map_signals KAPALI: sinyal eşlenmez → G4 eler")

    # ── G5 kardinalite/label ──
    m5c = _run(SIGNALS, spec, enforce_cardinality=False)
    case(m5c["cardinality_violations"] >= 1, "cardinality KAPALI: correlation_id alarm label → G5 eler")
    m5l = _run(SIGNALS, spec, enforce_labels=False)
    case(m5l["label_violations"] >= 1, "label KAPALI: sınırsız alarm label → G5 eler")

    # ── G6 PII + scope ──
    m6p = _run(SIGNALS, spec, enforce_pii=False)
    case(m6p["pii_violations"] >= 1, "pii KAPALI: phone_number alarm label → G6 eler")
    m6s = _run(SIGNALS, spec, scope_tenant=False)
    case(m6s["scope_violations"] >= 1, "scope_tenant KAPALI: tenant alarmı tenant_id taşımaz → G6 izolasyon eler")

    # ── G7 flap: transient + debounce KAPALI ──
    flaprec = SIGNALS + [{"rule": "ToolErrorRateHigh", "value": 2, "transient": True}]
    m7f = _run(flaprec, spec, debounce=False)
    case(m7f["flap_violations"] >= 1, "debounce KAPALI + transient: geçici blip alarm üretir → G7 flap eler")
    # debounce AÇIK → flap bastırılır
    m7fo = _run(flaprec, spec)
    case(m7fo["flap_violations"] == 0, "debounce AÇIK: transient blip flap üretmez → G7 geçer")
    # for_s=0 güvenlik alarmı: transient olsa bile flap sayılmaz (anında, her tetik gerçek)
    sec_transient = [{"rule": "ConsentSkipDetected", "value": 1, "transient": True}]
    m7sec = _run(sec_transient, spec, debounce=False)
    case(m7sec["flap_violations"] == 0, "for_s=0 güvenlik alarmı: transient olsa bile flap değil (anında)")

    # ── G7 dedup: aynı (alertname,tenant_id) iki kez + dedup KAPALI ──
    duprec = [{"rule": "ConsentSkipDetected", "value": 1}, {"rule": "ConsentSkipDetected", "value": 2}]
    m7d = _run(duprec, spec, dedup=False)
    case(m7d["dedup_violations"] >= 1, "dedup KAPALI: aynı (alertname,tenant_id) çift alarm → G7 dedup eler")
    m7do = _run(duprec, spec)
    case(m7do["dedup_violations"] == 0, "dedup AÇIK: çift alarm daraltılır → G7 geçer")

    # ── G8 routing: route_severity KAPALI → unrouted ──
    m8 = _run(SIGNALS, spec, route_severity=False)
    case(m8["routing_violations"] >= 1, "route_severity KAPALI: unrouted alarm → G8 eler")

    # ── firing doğruluğu: eşik altı sinyal alarm üretmez ──
    nofire = [{"rule": "LLMProviderErrorRateHigh", "value": 0.01},
              {"rule": "ResourceBudgetExceeded", "value": 1000000}]
    mnf = _run(nofire, spec)
    case(mnf["fired"] == 0, "eşik-altı sinyaller alarm üretmez (firing doğruluğu)")
    # platform-scope alarm tenant_id taşımaz (global)
    platsig = [{"rule": "E2EP95LatencyHigh", "value": 2000}]
    mp = _run(platsig, spec)
    case(mp["scope_violations"] == 0, "platform-scope alarm tenant_id taşımaz → scope ihlali değil")

    # ── reddetme (I11) ──
    case(_raises(lambda: evaluate_call({"signals": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 signals liste değil → reddedilir")
    case(_raises(lambda: evaluate_call({"signals": [{"value": 1}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 sinyalde rule eksik → reddedilir")
    case(_raises(lambda: evaluate_call({"signals": [{"rule": "Nope", "value": 1}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 bilinmeyen kural → reddedilir")
    case(_raises(lambda: AlarmRuleEngine(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I11 bağlam (tenant_id) eksik → reddedilir")
    case(_raises(lambda: evaluate_call({"signals": [{"rule": "E2EP95LatencyHigh"}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 sinyalde value eksik → reddedilir")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["rules"][0]["severity"] = "warning"
    case(_validate_obj(s) != 0, "G2 severity 0.4.7'den sapar (critical→warning) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["rules"] = s["rules"][:-1]
    case(_validate_obj(s) != 0, "G1 11→10 kural (bir madde düşer) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["rules"][0]["for_s"] = 100
    case(_validate_obj(s) != 0, "G3 for_s=100 + 40s ek-yük = 140 > 120 → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["rules"][0]["signal"] = "nonexistent_signal"
    case(_validate_obj(s) != 0, "G4 sinyal signal_catalog'da değil → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["signal_catalog"]["metric_signals"].append("extra_metric_not_in_047")
    case(_validate_obj(s) != 0, "G4 metric_signals 0.4.7 metrics.catalog'tan sapar → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["label_policy"]["alarm_labels_allowed"].append("correlation_id")
    case(_validate_obj(s) != 0, "G5 izinli alarm label'a correlation_id → kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["detection_budget"]["max_detection_budget_s"] = 180
    case(_validate_obj(s) != 0, "G3 max_detection_budget_s 0.4.7'den (120) sapar → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["gates"]["max_budget_violation"] = 1
    case(_validate_obj(s) != 0, "G3 max_budget_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I11 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["routing"]["scope_audience"]["tenant"] = ["rmc_l0_sre"]
    case(_validate_obj(s) != 0, "G6/G8 tenant kitlesinden security_compliance_officer düşerse → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["rules"][0]["leak_phone"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "I12 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_alarms", None)
    s["rules"][0]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "I12 literal secret → validate eler")

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
    print("""call-alarms-spec.json beklenen şekli (WBS 14.1.5):
  wbs=14.1.5, version, phase=F1, priority=Must, alarm_doc{brd,nfr,sad,adr,api,fr,observability,upstream}
  placement{in_orchestrator, emission_path, rule_based=true, severity_routing=true,
            tenant_scoped_routing=true, from_trace=false}                                       (G8)
  detection_budget{max_detection_budget_s=120, components[ingest+eval+for+notify], formula}     (G3,NFR 10.1)
  label_policy{alarm_labels_allowed, high_cardinality_keys, pii_forbidden_keys, exemplar}        (G5,G6)
  signal_catalog{metric_signals[20 — 0.4.7 metrics.catalog BİREBİR], security_capacity_signals[]} (G4)
  comparators[gt/ge]
  rules[11]{name, brd15, sad172, signal, signal_kind, comparator, threshold, severity,
            scope(platform/tenant), category, for_s, expr_hint}  (BRD §15 kritik alarm kataloğu) (G1,G2)
  routing{severity_channels{critical/warning}, scope_audience{platform/tenant}}                 (G8)
  flap_control{debounce_via_for=true, dedup_group_keys[alertname,tenant_id], auto_resolve=true}  (G7)
  gates{max_coverage_missing=0, max_catalog_mismatch=0, max_budget_violation=0, max_orphan_signal=0,
        max_cardinality_violation=0, max_label_violation=0, max_pii_violation=0, max_scope_violation=0,
        max_flap_violation=0, max_dedup_violation=0, max_routing_violation=0}                    (G1..G8)
  error_taxonomy{mapping→API §11.6 (malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION)}  (I11)
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                                       (I12)
  invariants[≥12]{id, desc, trace}

config/call-alarms-profiles.json: profiles[]{name, region, ingest_scrape_s, eval_interval_s, notify_lag_s}

evaluate sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  context{tenant_id, region?, org_unit?, correlation_id?},
  policy?{cover_all, honor_budget, map_signals, enforce_cardinality, enforce_labels, enforce_pii,
          scope_tenant, debounce, dedup, route_severity},
  signals[]{rule, value, transient?}}
  (PII DEĞERİ YOK — yalnız sinyal + etiket/kimlik anahtarı ADLARI)

komutlar: validate | evaluate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "evaluate":
        if len(sys.argv) < 3:
            print("kullanım: call_alarms_probe.py evaluate <sample.json>")
            return 2
        return evaluate_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|evaluate|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
