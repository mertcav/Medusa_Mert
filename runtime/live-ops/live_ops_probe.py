#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_ops_probe.py — WBS 14.1.6 Gerçek zamanlı operasyon ekranı (≤60sn gecikme)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/call-alarms/` (14.1.5) + `call-logger/` (14.1.4) + `call-resource/` (14.1.3) + `call-metrics/`
(14.1.2) + `call-trace/` (14.1.1) probe disipliniyle birebir; burada deterministik bir CONVERSATION
ORCHESTRATOR REAL-TIME OPERATIONS VIEW COMPOSER (SAD §17.1 'Visualization: Grafana, gerçek zamanlı op
ekranı FR-ANA-012 ≤60sn') simülatörü (saf; random YOK).

REAL-TIME OPERATIONS VIEW COMPOSER (Çekirdek IP, SAD §6 / §17) — gözlemlenebilirlik VISUALIZATION
katmanında metrik (14.1.2/14.1.3) + alarm (14.1.5) sinyallerini READ-ONLY view'a kompoze eder ve
operasyon ekranını ≤60sn tazelikle sunar:
  • Kapsam (G1):       BRD §15/SAD §17.1 operasyonel sinyal gruplarının HEPSİ tile taşır + grafana panel-
                       referans metriklerinin hepsi yüzeylenir (non-circular; 0.4.7'den türetilir).
  • Katalog (G2):      her metrik-tile sinyali 0.4.7 metrics.catalog'da (grafana panel kümesi BİREBİR) +
                       alarm-tile 0.4.7 alerts.catalog (11) BİREBİR — orphan tile yok.
  • Tazelik (G3):      her tile ingest+query_step+refresh+render ≤ 60s (FR-ANA-012) — BİRİNCİL kapı.
  • Scope (G4):        tenant görünümü yalnız kendi tenant verisi (tenant_id filtresi; cross-tenant yok).
  • Kardinalite (G5):  tile boyutu yüksek-kardinalite kimlik taşımaz + yalnız tile_dims_allowed.
  • PII/içerik (G6):   tile boyutunda PII yok (FR-REC-004) + Tier A: ham içerik (transkript/kayıt) yüzeylemez.
  • Refresh (G7):      auto-refresh açık + refresh ≤ bütçe + runtime refresh ≤ 0.4.7 grafana refresh (30s).
  • Drill-down (G8):   drill-down YALNIZ exemplar/annotation (correlation_id/trace_id) → trace (14.1.1).

KAPSAM AYRIMI: span üretimi → 14.1.1 · teknik metrik DEĞERLERİ → 14.1.2 · per-call CPU/bellek → 14.1.3 ·
yapılandırılmış log → 14.1.4 · alarm ÜRETİMİ → 14.1.5 · metrik/alarm/dashboard KATALOĞU + collector guard
→ 0.4.7 · tek-çağrı içerik/transkript ekranı → A-12 (13.4.12). Burada YALNIZ gerçek zamanlı op ekranı view
modeli + ≤60sn tazelik disiplini.

Komutlar:
  validate              live-ops-spec.json'ı invariant'lara + 0.4.7 çapraz-tutarlılığa + config'e + grafana panoya karşı doğrular.
  snapshot <sample>     Deterministik LiveOpsViewComposer — sinyal anlık-görüntü → kompoze view + tazelik + HARD kapılar (G1–G8); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. snapshot gerçek Prometheus/Grafana yerine deterministik simülasyondur (canlı
sistemde Prometheus scrape + Grafana, SAD §11/§17.1; ADR-003 runtime sinyal emisyonu). Ham ses payload/
transkript/PII DEĞERİ YOK — örnekler yalnız sinyal + kimlik/etiket anahtarı ADLARI taşır.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "live-ops-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "live-ops-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# Boyut/içerik DEĞERİ redaction (FR-REC-004): ham PII DEĞER desenleri. tenant_id/region/agent_id vb.
# KİMLİK/sınıf (PII değil) — ardışık ≥7 rakam içermez.
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


class ViewError(Exception):
    """Geçersiz/eksik sinyal anlık-görüntüsü veya bilinmeyen tile — sessizce kabul yok, reddet (I11)."""


# ─────────────────────────────────────────────────────────────────────────────
# Real-time Operations View Composer — view komposizyonu (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class LiveOpsViewComposer:
    """SAD §17.1 'Visualization' Real-time Operations View Composer. Gözlemlenebilirlik visualization
    katmanında metrik (14.1.2/14.1.3) + alarm (14.1.5) sinyallerini READ-ONLY view'a kompoze eder +
    tazelik bütçesini (≤60s, FR-ANA-012) uygular + tenant-scope izolasyon + tile-boyut kardinalite/PII +
    Tier A içerik + refresh + drill-down/exemplar disiplinine karşı denetler. Saf; random YOK.

    policy bayrakları buggy bir Composer'ı simüle eder (call-alarms/call-resource deseni):
      cover_all          : tüm grup/metrikleri kapsa (kapalı → bir grup tile'ı düşer, G1)
      honor_freshness    : query_step/render'ı spec'ten al (kapalı → şişer → tazelik > 60s, G3)
      map_catalog        : tile sinyalini signal_catalog'a eşle (kapalı → orphan tile, G2)
      scope_tenant       : tenant görünümünde tile'a tenant_id filtresi ekle (kapalı → cross-tenant, G4)
      enforce_cardinality: kimliği tile boyutu yapma (kapalı → correlation_id tile boyutu, G5)
      enforce_labels     : yalnız izinli tile boyutu (kapalı → sınırsız boyut, G5)
      enforce_pii        : PII anahtarını tile boyutundan çıkar (kapalı → phone_number tile boyutu, G6)
      enforce_tier_a     : Tier A — ham içerik yüzeyleme (kapalı → transcript_text tile'da, G6 content)
      auto_refresh       : pano auto-refresh açık (kapalı → durağan pano, G7)
      bind_exemplar      : drill-down exemplar/annotation (kapalı → kimlik tile boyutu drill, G8)
    """

    def __init__(self, spec, profile, context, policy):
        self.spec = spec
        self.context = dict(context or {})
        self.pol = policy

        self.tiles = {t["name"]: t for t in spec.get("tiles", [])}
        self.required_groups = list(spec.get("tile_groups", {}).get("required", []))
        self.max_budget = spec.get("freshness_budget", {}).get("max_freshness_budget_s", 60)

        lp = spec.get("label_policy", {})
        self.dims_allowed = set(lp.get("tile_dims_allowed", []))
        self.high_card = set(lp.get("high_cardinality_keys", []))
        self.pii_keys = set(lp.get("pii_forbidden_keys", []))

        cp = spec.get("content_policy", {})
        self.forbidden_content = set(cp.get("forbidden_content_keys", []))

        sc = spec.get("signal_catalog", {})
        self.metric_signals = set(sc.get("metric_signals", []))
        self.alarm_signals = set(sc.get("alarm_signals", []))

        rf = spec.get("refresh", {})
        # refresh_interval RUNTIME: profil > spec default
        self.refresh_interval_s = profile.get("refresh_interval_s",
                                               rf.get("default_refresh_interval_s", 30))
        self.auto_refresh_spec = rf.get("auto_refresh", True)

        # deployment zamanlaması (profil)
        self.ingest_lag_s = profile.get("ingest_lag_s", 10)
        self.render_lag_s = profile.get("render_lag_s", 5)

        if not self.context.get("tenant_id"):
            raise ViewError("view bağlamı eksik: tenant_id → INVALID_REQUEST")
        if not self.context.get("region"):
            raise ViewError("view bağlamı eksik: region → INVALID_REQUEST")

        # sayaçlar (HARD kapı kanıtı)
        self.coverage_missing = 0
        self.catalog_mismatch = 0
        self.freshness_violations = 0
        self.scope_violations = 0
        self.cardinality_violations = 0
        self.label_violations = 0
        self.pii_violations = 0
        self.content_violations = 0
        self.refresh_violations = 0
        self.drilldown_violations = 0

        self.composed = []      # kompoze edilen tile view'leri
        self.max_freshness = 0
        self.per_tile_freshness = {}
        self.derived = {}

    # ── tile başına veri tazeliği (ingest+query_step+refresh+render) ────────────
    def _freshness(self, tile):
        query_step = tile.get("query_step_s", 0)
        render = self.render_lag_s
        if not self.pol.get("honor_freshness", True):
            # buggy: ağır sorgu/render (örn. sınırsız lookback, senkron render) → tazelik şişer
            query_step = query_step + 15
            render = render + 5
        return self.ingest_lag_s + query_step + self.refresh_interval_s + render

    # ── tile boyutları (DÜŞÜK kardinalite + tenant scope) ──────────────────────
    def _tile_dims(self, tile, view_scope, view_tenant):
        out = {"region": self.context.get("region")}
        if tile.get("group"):
            out["category"] = tile["group"]
        # tenant görünümü → tenant_id filtresi (izolasyon, G4). platform görünümü → agregat (tenant_id YOK)
        if view_scope == "tenant":
            if self.pol.get("scope_tenant", True):
                out["tenant_id"] = view_tenant
            # buggy: scope_tenant kapalı → tenant görünümünde tile tenant_id taşımaz (cross-tenant sızıntı)
        # buggy: kimliği TILE BOYUTU yap (G5)
        if not self.pol.get("enforce_cardinality", True):
            out["correlation_id"] = self.context.get("correlation_id", "corr-x")
        # buggy: PII anahtarını TILE BOYUTU yap (G6) — DEĞER yok, yalnız anahtar adı
        if not self.pol.get("enforce_pii", True):
            out["phone_number"] = "<redacted>"
        # buggy: izinsiz (yüksek-kardinalite/PII olmayan) boyut (G5 label)
        if not self.pol.get("enforce_labels", True):
            out["unbounded_dim"] = "x"
        return out

    # ── tile içeriği (Tier A — yalnız metrik/agregat) ──────────────────────────
    def _tile_content(self, tile):
        # buggy: enforce_tier_a kapalı → tile ham içerik (transkript) yüzeyler (G6 content)
        if not self.pol.get("enforce_tier_a", True):
            return {"transcript_text": "<raw-content>"}
        return {}

    def run(self, view_request, signals):
        view_scope = view_request.get("scope", "tenant")
        if view_scope not in ("platform", "tenant"):
            raise ViewError("view scope ∈ platform/tenant değil → INVALID_REQUEST")
        view_tenant = view_request.get("tenant_id") or self.context.get("tenant_id")

        spec_tile_names = list(self.tiles.keys())

        # 0) KAPSAM (G1): gerekli operasyonel gruplar + grafana panel-referans metrikleri
        active = set(spec_tile_names)
        if not self.pol.get("cover_all", True):
            # buggy: bir tile düşer
            if active:
                active.discard(sorted(active)[0])

        active_groups = {self.tiles[n].get("group") for n in active}
        missing_groups = [g for g in self.required_groups if g not in active_groups]
        # grafana panel-referans metrikleri (non-circular kapsam): probe-sabiti değil, 0.4.7'den türetilir
        required_metrics = set(self.spec.get("_required_metrics", self.metric_signals))
        surfaced = set()
        for n in active:
            t = self.tiles[n]
            if t.get("kind") == "metric":
                surfaced |= set(t.get("signals", []))
        missing_metrics = [mm for mm in required_metrics if mm not in surfaced]
        self.coverage_missing = len(missing_groups) + len(missing_metrics)

        # 1) yapısal kapılar — her AKTİF tile için
        catalog_signals = self.metric_signals | self.alarm_signals
        for name in sorted(active):
            tile = self.tiles[name]
            # G3 tazelik bütçesi
            fr = self._freshness(tile)
            self.per_tile_freshness[name] = fr
            self.max_freshness = max(self.max_freshness, fr)
            if fr > self.max_budget:
                self.freshness_violations += 1
            # G2 katalog (orphan tile yok): her sinyal kataloğda + kind uyumu
            sigs = tile.get("signals", [])
            kind = tile.get("kind")
            if self.pol.get("map_catalog", True):
                for s in sigs:
                    if kind == "metric" and s not in self.metric_signals:
                        self.catalog_mismatch += 1
                    elif kind == "alarm" and s not in self.alarm_signals:
                        self.catalog_mismatch += 1
                    elif kind not in ("metric", "alarm"):
                        self.catalog_mismatch += 1
            else:
                self.catalog_mismatch += 1   # buggy: eşleme yok → orphan
            # G8 drill-down: tile bir gruba ait olmalı (orphan tile yok)
            if tile.get("group") not in self.required_groups:
                self.drilldown_violations += 1
            # G8 drill-down: bind_exemplar kapalı → kimlik tile boyutu drill (kardinalite kaçağı)
            if not self.pol.get("bind_exemplar", True):
                self.drilldown_violations += 1

        # 2) view komposizyonu — her AKTİF tile için boyut/içerik denetimi
        for name in sorted(active):
            tile = self.tiles[name]
            dims = self._tile_dims(tile, view_scope, view_tenant)
            content = self._tile_content(tile)

            # G5 kardinalite + label denetimi (tile boyutları)
            for k in dims.keys():
                if k in self.high_card:
                    self.cardinality_violations += 1
                if k in self.pii_keys:
                    self.pii_violations += 1            # G6 PII (boyut)
                elif k not in self.dims_allowed:
                    self.label_violations += 1

            # G6 Tier A: tile ham içerik yüzeylemez
            for k in content.keys():
                if k in self.forbidden_content:
                    self.content_violations += 1

            # G4 scope izolasyon: tenant görünümünde tile tenant_id filtresi taşımalı
            if view_scope == "tenant" and "tenant_id" not in dims:
                self.scope_violations += 1

            self.composed.append({"tile": name, "group": tile.get("group"), "kind": tile.get("kind"),
                                  "dims": sorted(dims.keys()), "freshness_s": self.per_tile_freshness.get(name),
                                  "tier_a": not content})

        # 3) G7 refresh disiplini
        auto = self.auto_refresh_spec and self.pol.get("auto_refresh", True)
        if not auto:
            self.refresh_violations += 1
        if self.refresh_interval_s > self.max_budget:
            self.refresh_violations += 1

        self.derived["active_tiles"] = len(active)
        self.derived["required_groups"] = len(self.required_groups)
        self.derived["active_groups"] = len(active_groups & set(self.required_groups))
        self.derived["required_metrics"] = len(required_metrics)
        self.derived["surfaced_metrics"] = len(surfaced & required_metrics)
        self.derived["max_freshness_s"] = self.max_freshness
        self.derived["max_budget_s"] = self.max_budget
        self.derived["ingest_refresh_render_s"] = self.ingest_lag_s + self.refresh_interval_s + self.render_lag_s
        self.derived["refresh_interval_s"] = self.refresh_interval_s
        self.derived["view_scope"] = view_scope

    def metrics(self):
        return {
            "coverage_missing": self.coverage_missing,
            "catalog_mismatch": self.catalog_mismatch,
            "freshness_violations": self.freshness_violations,
            "scope_violations": self.scope_violations,
            "cardinality_violations": self.cardinality_violations,
            "label_violations": self.label_violations,
            "pii_violations": self.pii_violations,
            "content_violations": self.content_violations,
            "refresh_violations": self.refresh_violations,
            "drilldown_violations": self.drilldown_violations,
            "composed": len(self.composed),
            "per_tile_freshness": dict(self.per_tile_freshness),
            "derived": dict(self.derived),
        }


def compose_view(sample, spec, profile, context, policy):
    view_request = sample.get("view_request", {"scope": "tenant"})
    if not isinstance(view_request, dict):
        raise ViewError("view_request sözlük değil → INVALID_REQUEST")
    signals = sample.get("signals", [])
    if not isinstance(signals, list):
        raise ViewError("sinyal anlık-görüntüsü (signals) liste değil → INVALID_REQUEST")
    for sig in signals:
        if not isinstance(sig, dict) or "tile" not in sig:
            raise ViewError("sinyal (signal) sözlük değil veya tile eksik → INVALID_REQUEST")
        if sig["tile"] not in {t["name"] for t in spec.get("tiles", [])}:
            raise ViewError("bilinmeyen tile: %s → INVALID_REQUEST" % sig["tile"])
    eng = LiveOpsViewComposer(spec, profile, context, policy)
    eng.run(view_request, signals)
    return eng.metrics()


def evaluate(spec, m):
    """Metrikleri HARD kapılara (G1–G8) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    d = m.get("derived", {})
    F = []
    F.append((m.get("coverage_missing", 0) <= g.get("max_coverage_missing", 0),
              "G1 kapsam eksik %d ≤ %d (operasyonel grup %d/%d + grafana metrik %d/%d yüzeylenir — 0.4.7'den türetilir)"
              % (m.get("coverage_missing", 0), g.get("max_coverage_missing", 0),
                 d.get("active_groups", 0), d.get("required_groups", 0),
                 d.get("surfaced_metrics", 0), d.get("required_metrics", 0))))
    F.append((m.get("catalog_mismatch", 0) <= g.get("max_catalog_mismatch", 0),
              "G2 katalog uyuşmazlığı %d ≤ %d (tile sinyali 0.4.7 metrics.catalog/alerts.catalog BİREBİR — orphan tile yok)"
              % (m.get("catalog_mismatch", 0), g.get("max_catalog_mismatch", 0))))
    F.append((m.get("freshness_violations", 0) <= g.get("max_freshness_violation", 0),
              "G3 tazelik bütçe ihlali %d ≤ %d (ingest+query_step+refresh+render ≤ %ds; max=%ds — FR-ANA-012 ≤60sn)"
              % (m.get("freshness_violations", 0), g.get("max_freshness_violation", 0),
                 d.get("max_budget_s", 60), d.get("max_freshness_s", 0))))
    F.append((m.get("scope_violations", 0) <= g.get("max_scope_violation", 0),
              "G4 scope ihlali %d ≤ %d (tenant görünümü→tenant_id filtresi; cross-tenant sızıntı yok — FR-TEN-002 altın kural)"
              % (m.get("scope_violations", 0), g.get("max_scope_violation", 0))))
    F.append((m.get("cardinality_violations", 0) <= g.get("max_cardinality_violation", 0)
              and m.get("label_violations", 0) <= g.get("max_label_violation", 0),
              "G5 tile-boyut ihlali kardinalite=%d label=%d ≤ 0 (kimlik exemplar/annotation + yalnız allowed — 0.4.7 label_policy)"
              % (m.get("cardinality_violations", 0), m.get("label_violations", 0))))
    F.append((m.get("pii_violations", 0) <= g.get("max_pii_violation", 0)
              and m.get("content_violations", 0) <= g.get("max_content_violation", 0),
              "G6 PII/içerik ihlali pii=%d content=%d ≤ 0 (boyutta PII yok FR-REC-004 + Tier A: ham içerik yüzeylemez → A-12)"
              % (m.get("pii_violations", 0), m.get("content_violations", 0))))
    F.append((m.get("refresh_violations", 0) <= g.get("max_refresh_violation", 0),
              "G7 refresh ihlali %d ≤ %d (auto-refresh açık + refresh_interval %ds ≤ bütçe; runtime ≤ grafana 30s)"
              % (m.get("refresh_violations", 0), g.get("max_refresh_violation", 0), d.get("refresh_interval_s", 0))))
    F.append((m.get("drilldown_violations", 0) <= g.get("max_drilldown_violation", 0),
              "G8 drill-down ihlali %d ≤ %d (exemplar/annotation→trace 14.1.1; kimlik tile boyutu değil + her tile bir grupta)"
              % (m.get("drilldown_violations", 0), g.get("max_drilldown_violation", 0))))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# bağlam + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise ViewError("bilinmeyen profil: %s" % name)


def _resolve_context(spec, profile, sample):
    ctx = dict(sample.get("context", {}))
    ctx.setdefault("region", profile.get("region"))
    return ctx


def _resolve_policy(spec, sample):
    pol = _full_pol()
    pol.update(sample.get("policy", {}))
    return pol


def snapshot_cmd(sample_path):
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
        except ViewError as ex:
            print("snapshot[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    context = _resolve_context(spec, profile, sample)
    policy = _resolve_policy(spec, sample)

    try:
        m = compose_view(sample, spec, profile, context, policy)
    except ViewError as ex:
        print("snapshot[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, m)
    d = m.get("derived", {})
    print("snapshot[%s] scope=%s → %d tile kompoze | kapsam=%d katalog=%d tazelik=%d scope=%d kardinalite=%d label=%d pii=%d content=%d refresh=%d drill=%d" % (
        name, d.get("view_scope"), m["composed"], m["coverage_missing"], m["catalog_mismatch"],
        m["freshness_violations"], m["scope_violations"], m["cardinality_violations"], m["label_violations"],
        m["pii_violations"], m["content_violations"], m["refresh_violations"], m["drilldown_violations"]))
    print("  tazelik: ingest+refresh+render=%ds + query_step(tile) → max=%ds ≤ %ds (FR-ANA-012) | grup=%d/%d metrik=%d/%d | refresh=%ds" % (
        d.get("ingest_refresh_render_s"), d.get("max_freshness_s"), d.get("max_budget_s"),
        d.get("active_groups"), d.get("required_groups"), d.get("surfaced_metrics"), d.get("required_metrics"),
        d.get("refresh_interval_s")))
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


def _load_grafana_dashboard():
    """0.4.7 config/grafana-dashboard-voice-runtime.json (varsa) — refresh + panel-referans metrik çıkarımı."""
    cand = os.path.normpath(os.path.join(HERE, "..", "..", "docs", "platform", "observability",
                                          "config", "grafana-dashboard-voice-runtime.json"))
    if os.path.exists(cand):
        try:
            with open(cand, "r", encoding="utf-8") as f:
                raw = f.read()
            return json.loads(raw), raw
        except Exception:
            return None, None
    return None, None


def _grafana_referenced_metrics(obs, raw):
    """0.4.7 grafana panellerinde REFERANSLANAN metric.catalog adları (non-circular kapsam türetimi)."""
    if obs is None or raw is None:
        return None
    cat = [mm.get("name") for mm in obs.get("metrics", {}).get("catalog", []) if mm.get("name")]
    return {mm for mm in cat if mm in raw}


def _refresh_to_seconds(v):
    """'30s'/'1m'/'15' → saniye."""
    v = str(v).strip()
    m = re.match(r"^(\d+)(s|m|h)?$", v)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def _inject_required(spec):
    """KAPSAM (G1, non-circular): gerekli (yüzeylenecek) metrik kümesini 0.4.7 grafana panel-referansından
    türet (probe-sabiti DEĞİL). 0.4.7 yoksa spec metric_signals'a düş (kendi-kendine kapsam)."""
    obs = _load_observability_spec()
    _gr, raw = _load_grafana_dashboard()
    refs = _grafana_referenced_metrics(obs, raw)
    if refs:
        spec["_required_metrics"] = sorted(refs)
        return spec["_required_metrics"]
    spec["_required_metrics"] = list(spec.get("signal_catalog", {}).get("metric_signals", []))
    return spec["_required_metrics"]


def validate():
    spec = _load(SPEC_PATH)
    R = []

    _check(R, spec.get("wbs") == "14.1.6", "spec.wbs == 14.1.6")
    _check(R, spec.get("version"), "spec.version mevcut")
    _check(R, spec.get("phase") == "F1", "spec.phase == F1")
    _check(R, spec.get("priority") == "Must", "spec.priority == Must (FR-ANA-012)")
    vd = spec.get("view_doc", {})
    for k in ("brd", "nfr", "fr", "sad", "adr", "api", "observability", "upstream"):
        _check(R, bool(vd.get(k)), "view_doc.%s mevcut" % k)
    _check(R, "FR-ANA-012" in vd.get("fr", ""), "view_doc.fr FR-ANA-012 referansı")

    # ── placement
    pl = spec.get("placement", {})
    _check(R, pl.get("in_observability_plane") is True, "placement observability plane içinde")
    _check(R, pl.get("visualization_layer") is True, "placement visualization katmanı")
    _check(R, pl.get("read_only") is True, "placement read-only (view)")
    _check(R, pl.get("from_signals") is True, "placement from_signals (14.1.2/14.1.3/14.1.5'ten okur)")
    _check(R, pl.get("tenant_scoped_view") is True, "G4 tenant_scoped_view")
    _check(R, pl.get("tier_a_metrics_only") is True, "G6 tier_a_metrics_only (altın kural)")
    _check(R, pl.get("from_trace") is False, "from_trace=false (view komposizyonu, trace türetme değil)")

    # ── freshness_budget (G3 / FR-ANA-012)
    fb = spec.get("freshness_budget", {})
    _check(R, fb.get("max_freshness_budget_s") == 60, "G3 max_freshness_budget_s = 60 (FR-ANA-012 ≤60sn)")
    _check(R, fb.get("components") == ["ingest_lag_s", "query_step_s", "refresh_interval_s", "render_lag_s"],
           "G3 bileşenler = ingest+query_step+refresh+render")

    # ── refresh (G7)
    rf = spec.get("refresh", {})
    _check(R, isinstance(rf.get("default_refresh_interval_s"), int) and rf.get("default_refresh_interval_s") > 0,
           "G7 default_refresh_interval_s > 0")
    _check(R, rf.get("default_refresh_interval_s") <= fb.get("max_freshness_budget_s", 60),
           "G7 default_refresh_interval_s ≤ freshness bütçesi")
    _check(R, rf.get("auto_refresh") is True, "G7 auto_refresh açık")
    _check(R, rf.get("stale_indicator") is True, "G7 bayat-veri göstergesi")
    _check(R, bool(rf.get("grafana_dashboard_uid")), "G7 grafana_dashboard_uid mevcut")

    # ── tiles (G1 kapsam + G2 katalog + G3 budget)
    tiles = spec.get("tiles", [])
    tnames = [t.get("name") for t in tiles]
    _check(R, len(tnames) == len(set(tnames)) and len(tnames) >= 8, "G1 ≥8 benzersiz tile")
    sc = spec.get("signal_catalog", {})
    metric_signals = set(sc.get("metric_signals", []))
    alarm_signals = set(sc.get("alarm_signals", []))
    req_groups = set(spec.get("tile_groups", {}).get("required", []))
    for t in tiles:
        _check(R, t.get("kind") in ("metric", "alarm"), "tile %s kind ∈ metric/alarm" % t.get("name"))
        _check(R, t.get("group") in req_groups, "G1 tile %s group ∈ required gruplar" % t.get("name"))
        _check(R, isinstance(t.get("query_step_s"), int) and t.get("query_step_s") >= 0,
               "tile %s query_step_s ≥ 0" % t.get("name"))
        _check(R, isinstance(t.get("signals"), list) and t.get("signals"), "tile %s sinyal listesi var" % t.get("name"))
        if t.get("kind") == "metric":
            _check(R, all(s in metric_signals for s in t.get("signals", [])),
                   "G2 tile %s metrik sinyalleri signal_catalog'da (orphan yok)" % t.get("name"))
        else:
            _check(R, all(s in alarm_signals for s in t.get("signals", [])),
                   "G2 tile %s alarm sinyalleri alarm_catalog'da (orphan yok)" % t.get("name"))

    # ── G1 kapsam: her gerekli grup ≥1 tile + grafana metrikleri yüzeylenir
    tile_groups = {t.get("group") for t in tiles}
    _check(R, req_groups <= tile_groups, "G1 her gerekli operasyonel grup ≥1 tile taşır")
    _check(R, {"latency", "errors", "traffic", "quality", "resource", "cost", "alarms"} <= req_groups,
           "G1 required gruplar çekirdek operasyonel sinyalleri içerir")
    surfaced = set()
    for t in tiles:
        if t.get("kind") == "metric":
            surfaced |= set(t.get("signals", []))
    _check(R, surfaced == metric_signals,
           "G1 metrik-tile'ların yüzeylediği metrikler = signal_catalog metric_signals (tam kapsam)")

    # ── G3 budget: en kötü profil ek-yük + en geniş query_step ≤ 60 (statik headroom)
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        worst_over = 0
        for p in cfg.get("profiles", []):
            over = p.get("ingest_lag_s", 10) + p.get("refresh_interval_s", 30) + p.get("render_lag_s", 5)
            worst_over = max(worst_over, over)
        worst_step = max((t.get("query_step_s", 0) for t in tiles), default=0)
        _check(R, worst_over + worst_step <= fb.get("max_freshness_budget_s", 60),
               "G3 en kötü profil ek-yük (%ds) + en geniş query_step (%ds) ≤ 60s (FR-ANA-012)" % (worst_over, worst_step))

    # ── label_policy (G5/G6; 0.4.7 hizalı)
    lp = spec.get("label_policy", {})
    allowed = set(lp.get("tile_dims_allowed", []))
    high = set(lp.get("high_cardinality_keys", []))
    pii = set(lp.get("pii_forbidden_keys", []))
    _check(R, {"tenant_id", "region", "agent_id", "category"} <= allowed,
           "G5 tile_dims_allowed çekirdek yönlendirme boyutlarını içerir")
    _check(R, {"correlation_id", "call_id", "customer_id", "session_id"} <= high,
           "G5 high_cardinality_keys çekirdek kimlikleri içerir")
    _check(R, {"phone_number", "token", "transcript_text", "audio_payload"} <= pii,
           "G6 pii_forbidden_keys çekirdek PII anahtarlarını içerir")
    _check(R, not (allowed & high), "G5 izinli tile boyutu ile yüksek-kardinalite kesişmez")
    _check(R, not (allowed & pii), "G6 izinli tile boyutu ile PII kesişmez")

    # ── content_policy (G6 Tier A)
    cp = spec.get("content_policy", {})
    _check(R, cp.get("tier") == "A", "G6 content_policy.tier == A (yalnız metrik/agregat)")
    fck = set(cp.get("forbidden_content_keys", []))
    _check(R, {"transcript_text", "recording", "audio_payload"} <= fck,
           "G6 forbidden_content_keys çekirdek içerik anahtarlarını içerir (içerik → A-12)")

    # ── drilldown (G8)
    dd = spec.get("drilldown", {})
    _check(R, set(dd.get("exemplar_keys", [])) == {"correlation_id", "trace_id"},
           "G8 drill-down exemplar_keys = correlation_id/trace_id")
    _check(R, "trace" in dd.get("target", "").lower() or "14.1.1" in dd.get("target", ""),
           "G8 drill-down hedefi call-trace (14.1.1)")

    # ── 0.4.7 observability-spec BİREBİR (G1/G2/G9/G10)
    obs = _load_observability_spec()
    gr, raw = _load_grafana_dashboard()
    if obs is not None:
        # I9 freshness budget BİREBİR
        _check(R, obs.get("dashboards", {}).get("freshness_budget_s") == fb.get("max_freshness_budget_s"),
               "I9 0.4.7 dashboards.freshness_budget_s (%s) = spec max (FR-ANA-012)" % obs.get("dashboards", {}).get("freshness_budget_s"))
        # I9 grafana uid 0.4.7 dashboards.required içinde
        _check(R, rf.get("grafana_dashboard_uid") in obs.get("dashboards", {}).get("required", []),
               "I9 grafana_dashboard_uid 0.4.7 dashboards.required içinde")
        # G2 metric_signals ⊆ 0.4.7 metrics.catalog
        ometrics = {mm.get("name") for mm in obs.get("metrics", {}).get("catalog", [])}
        _check(R, metric_signals <= ometrics,
               "G2 metric_signals 0.4.7 metrics.catalog (20) ALT-KÜMESİ (%d ⊆ %d)" % (len(metric_signals), len(ometrics)))
        # G2 alarm_signals 0.4.7 alerts.catalog BİREBİR
        oalerts = {a.get("name") for a in obs.get("alerts", {}).get("catalog", [])}
        _check(R, alarm_signals == oalerts,
               "G2 alarm_signals 0.4.7 alerts.catalog (11) ile BİREBİR (%d/%d)" % (len(alarm_signals), len(oalerts)))
        # G5 high_cardinality_keys 0.4.7 ile birebir
        olp = obs.get("label_policy", {})
        _check(R, set(olp.get("high_cardinality_keys", [])) == high,
               "G5 high_cardinality_keys 0.4.7 label_policy ile birebir")
        # G5 tile_dims_allowed ⊆ 0.4.7 metric_labels_allowed
        ometric_labels = set(olp.get("metric_labels_allowed", []))
        _check(R, allowed <= ometric_labels,
               "G5 tile_dims_allowed 0.4.7 metric_labels_allowed ALT-KÜMESİ")
        # G6 pii: 0.4.7 metric_labels_forbidden tile boyutunda da yasak
        omf = set(olp.get("metric_labels_forbidden", []))
        _check(R, not (allowed & omf), "G6 tile_dims_allowed 0.4.7 metric_labels_forbidden ile kesişmez")

    # ── I10 metric_signals = grafana panel-referans kümesi (BİREBİR, non-circular)
    refs = _grafana_referenced_metrics(obs, raw)
    if refs is not None:
        _check(R, metric_signals == refs,
               "I10 metric_signals = grafana panel-referans metrik kümesi (BİREBİR %d/%d)" % (len(metric_signals), len(refs)))
    if gr is not None:
        # I7 runtime refresh ≤ grafana refresh (tightens-or-equals)
        gref = _refresh_to_seconds(gr.get("refresh"))
        _check(R, gref is not None and rf.get("default_refresh_interval_s") <= gref,
               "I7 runtime refresh (%ss) ≤ 0.4.7 grafana refresh (%ss; tightens-or-equals)" % (
                   rf.get("default_refresh_interval_s"), gref))

    # ── gates
    g = spec.get("gates", {})
    for gk in ("max_coverage_missing", "max_catalog_mismatch", "max_freshness_violation", "max_scope_violation",
               "max_cardinality_violation", "max_label_violation", "max_pii_violation", "max_content_violation",
               "max_refresh_violation", "max_drilldown_violation"):
        _check(R, g.get(gk, -1) == 0, "gate %s = 0" % gk)

    # ── error taxonomy (I11)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "I11 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "I11 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("malformed_signal") == "INVALID_REQUEST"
           and mapping.get("unknown_tile") == "INVALID_REQUEST"
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
                          for k in ("ingest_lag_s", "refresh_interval_s", "render_lag_s")),
                   "config %s zamanlama (ingest/refresh/render) > 0" % p.get("name"))
            _check(R, p.get("refresh_interval_s", 999) <= fb.get("max_freshness_budget_s", 60),
                   "config %s refresh_interval ≤ 60 (FR-ANA-012)" % p.get("name"))

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
           "ingest_lag_s": 10, "refresh_interval_s": 30, "render_lag_s": 5}

# tipik bir tenant operasyon görünümü: birkaç tile için anlık değer.
VIEW = {"scope": "tenant", "tenant_id": "t_acme"}
SIGNALS = [
    {"tile": "tile_e2e_latency", "value": 980},
    {"tile": "tile_per_call_resource", "value": 11000000},
    {"tile": "tile_active_alarms", "value": 2},
]


def _full_pol():
    return {"cover_all": True, "honor_freshness": True, "map_catalog": True, "scope_tenant": True,
            "enforce_cardinality": True, "enforce_labels": True, "enforce_pii": True, "enforce_tier_a": True,
            "auto_refresh": True, "bind_exemplar": True}


def _run(view, signals, spec, context=None, profile=None, **pol_over):
    pol = _full_pol()
    pol.update(pol_over)
    return compose_view({"view_request": view, "signals": signals}, spec, profile or PROFILE,
                        context or CONTEXT, pol)


def _raises(fn):
    try:
        fn()
        return False
    except ViewError:
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
    mh = _run(VIEW, SIGNALS, spec)
    case(mh["coverage_missing"] == 0, "happy: kapsam tam (grup + grafana metrik) (G1)")
    case(mh["catalog_mismatch"] == 0, "happy: katalog BİREBİR — orphan tile yok (G2)")
    case(mh["freshness_violations"] == 0, "happy: tazelik ≤60s (G3)")
    case(mh["scope_violations"] == 0, "happy: tenant-scope izolasyon (G4)")
    case(mh["cardinality_violations"] == 0 and mh["label_violations"] == 0, "happy: tile-boyut disiplinli (G5)")
    case(mh["pii_violations"] == 0 and mh["content_violations"] == 0, "happy: PII/içerik temiz — Tier A (G6)")
    case(mh["refresh_violations"] == 0, "happy: refresh disiplinli (G7)")
    case(mh["drilldown_violations"] == 0, "happy: drill-down exemplar (G8)")
    case(all(ok for ok, _ in evaluate(spec, mh)), "happy tüm kapıları geçer")
    case(mh["composed"] == 8, "happy: 8 tile kompoze edildi")
    d = mh["derived"]
    case(d["max_freshness_s"] == 55, "happy: max tazelik = 45 ek-yük + 10 query_step = 55s ≤ 60s")
    case(d["active_groups"] == 7 and d["required_groups"] == 7, "happy: 7/7 operasyonel grup")
    case(d["surfaced_metrics"] == 15 and d["required_metrics"] == 15, "happy: 15/15 grafana metrik yüzeylenir")

    # ── G3 tazelik: low-latency profil daha düşük tazelik ──
    mll = _run(VIEW, SIGNALS, spec, profile={"name": "ll", "region": "eu-west-1",
                                             "ingest_lag_s": 5, "refresh_interval_s": 15, "render_lag_s": 3})
    case(mll["derived"]["max_freshness_s"] == 33, "low-latency profil: max tazelik = 23+10 = 33s")
    case(mll["freshness_violations"] == 0, "low-latency profil tazelik geçer")

    # ── platform (L0) görünümü: agregat, tenant_id taşımaz (Tier A; scope ihlali değil) ──
    mp = _run({"scope": "platform"}, SIGNALS, spec)
    case(mp["scope_violations"] == 0, "platform-scope görünümü agregat (tenant_id yok) → scope ihlali değil")

    # ── determinizm ──
    a = _run(VIEW, SIGNALS, spec)
    b = _run(VIEW, SIGNALS, spec)
    case(a == b, "determinizm: aynı anlık-görüntü aynı sonucu verir (saf; random yok)")

    # ── G1 kapsam: cover_all KAPALI → bir tile düşer ──
    m1 = _run(VIEW, SIGNALS, spec, cover_all=False)
    case(m1["coverage_missing"] >= 1, "cover_all KAPALI: bir tile düşer → grup/metrik açığı → G1 eler")

    # ── G2 katalog: map_catalog KAPALI → orphan tile ──
    m2 = _run(VIEW, SIGNALS, spec, map_catalog=False)
    case(m2["catalog_mismatch"] >= 1, "map_catalog KAPALI: tile sinyali eşlenmez → G2 eler")

    # ── G3 tazelik: honor_freshness KAPALI → query/render şişer → tazelik > 60s ──
    m3 = _run(VIEW, SIGNALS, spec, honor_freshness=False)
    case(m3["freshness_violations"] >= 1, "honor_freshness KAPALI: query/render şişer → tazelik > 60s → G3 eler")
    case(m3["derived"]["max_freshness_s"] > 60, "honor_freshness KAPALI: max tazelik > 60s")
    # geniş profil (yavaş ingest/refresh) → tazelik aşımı
    mslow = _run(VIEW, SIGNALS, spec, profile={"name": "slow", "region": "eu-west-1",
                                               "ingest_lag_s": 20, "refresh_interval_s": 30, "render_lag_s": 15})
    case(mslow["freshness_violations"] >= 1, "yavaş profil (65s ek-yük + 10 query_step) → tazelik 75s > 60 → G3 eler")

    # ── G4 scope: scope_tenant KAPALI → tenant görünümü tenant_id taşımaz (cross-tenant) ──
    m4 = _run(VIEW, SIGNALS, spec, scope_tenant=False)
    case(m4["scope_violations"] >= 1, "scope_tenant KAPALI: tenant görünümü tenant_id taşımaz → G4 cross-tenant eler")

    # ── G5 kardinalite/label ──
    m5c = _run(VIEW, SIGNALS, spec, enforce_cardinality=False)
    case(m5c["cardinality_violations"] >= 1, "cardinality KAPALI: correlation_id tile boyutu → G5 eler")
    m5l = _run(VIEW, SIGNALS, spec, enforce_labels=False)
    case(m5l["label_violations"] >= 1, "label KAPALI: sınırsız tile boyutu → G5 eler")

    # ── G6 PII + içerik ──
    m6p = _run(VIEW, SIGNALS, spec, enforce_pii=False)
    case(m6p["pii_violations"] >= 1, "pii KAPALI: phone_number tile boyutu → G6 eler")
    m6t = _run(VIEW, SIGNALS, spec, enforce_tier_a=False)
    case(m6t["content_violations"] >= 1, "tier_a KAPALI: transcript_text tile'da → G6 content eler (Tier A ihlali)")

    # ── G7 refresh: auto_refresh KAPALI → durağan pano ──
    m7 = _run(VIEW, SIGNALS, spec, auto_refresh=False)
    case(m7["refresh_violations"] >= 1, "auto_refresh KAPALI: durağan pano → G7 eler")
    # refresh > bütçe
    m7b = _run(VIEW, SIGNALS, spec, profile={"name": "bigref", "region": "eu-west-1",
                                             "ingest_lag_s": 5, "refresh_interval_s": 90, "render_lag_s": 3})
    case(m7b["refresh_violations"] >= 1, "refresh_interval 90 > 60 bütçe → G7 eler")

    # ── G8 drill-down: bind_exemplar KAPALI → kimlik tile boyutu drill ──
    m8 = _run(VIEW, SIGNALS, spec, bind_exemplar=False)
    case(m8["drilldown_violations"] >= 1, "bind_exemplar KAPALI: kimlik tile boyutu drill → G8 eler")

    # ── reddetme (I11) ──
    case(_raises(lambda: compose_view({"signals": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 signals liste değil → reddedilir")
    case(_raises(lambda: compose_view({"signals": [{"value": 1}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 sinyalde tile eksik → reddedilir")
    case(_raises(lambda: compose_view({"signals": [{"tile": "tile_nope", "value": 1}]}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 bilinmeyen tile → reddedilir")
    case(_raises(lambda: compose_view({"view_request": "x"}, spec, PROFILE, CONTEXT, _full_pol())),
         "I11 view_request sözlük değil → reddedilir")
    case(_raises(lambda: LiveOpsViewComposer(spec, PROFILE, {"region": "eu"}, _full_pol())),
         "I11 bağlam (tenant_id) eksik → reddedilir")
    case(_raises(lambda: LiveOpsViewComposer(spec, PROFILE, CONTEXT, _full_pol()).run({"scope": "x"}, [])),
         "I11 geçersiz view scope → reddedilir")

    # ── validate negatif kapılar ──
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["freshness_budget"]["max_freshness_budget_s"] = 120
    case(_validate_obj(s) != 0, "G3/I9 max_freshness_budget_s 0.4.7'den (60) sapar → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["tiles"][0]["query_step_s"] = 40
    case(_validate_obj(s) != 0, "G3 query_step=40 + 45s ek-yük = 85 > 60 → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["tiles"][0]["signals"] = ["nonexistent_metric"]
    case(_validate_obj(s) != 0, "G2/I10 tile sinyali signal_catalog/grafana'da değil → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["signal_catalog"]["metric_signals"].append("tool_latency_ms")
    case(_validate_obj(s) != 0, "I10 metric_signals grafana panel kümesinden sapar (tool_latency_ms eklenir) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["signal_catalog"]["alarm_signals"] = s["signal_catalog"]["alarm_signals"][:-1]
    case(_validate_obj(s) != 0, "G2 alarm_signals 0.4.7 alerts.catalog'tan sapar (11→10) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["label_policy"]["tile_dims_allowed"].append("correlation_id")
    case(_validate_obj(s) != 0, "G5 izinli tile boyutuna correlation_id → kesişim → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["refresh"]["default_refresh_interval_s"] = 45
    case(_validate_obj(s) != 0, "I7 runtime refresh 45 > grafana 30 → tightens-or-equals ihlali → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["refresh"]["grafana_dashboard_uid"] = "nope"
    case(_validate_obj(s) != 0, "I9 grafana_dashboard_uid 0.4.7 dashboards.required'da değil → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["content_policy"]["tier"] = "B"
    case(_validate_obj(s) != 0, "G6 content_policy.tier B (Tier A değil) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["gates"]["max_freshness_violation"] = 1
    case(_validate_obj(s) != 0, "G3 max_freshness_violation>0 → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "I11 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["tiles"][0]["leak_phone"] = "0555 123 4567"
    case(_validate_obj(s) != 0, "I12 spec'te ham PII DEĞERİ (telefon) → validate eler")
    s = json.loads(json.dumps(spec)); s.pop("_required_metrics", None)
    s["tiles"][0]["leak"] = "api_key: AKIAIOSFODNN7EXAMPLE"
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
    print("""live-ops-spec.json beklenen şekli (WBS 14.1.6):
  wbs=14.1.6, version, phase=F1, priority=Must, view_doc{brd,nfr,fr,sad,adr,api,observability,upstream}
  placement{in_observability_plane, visualization_layer, read_only, from_signals=true,
            tenant_scoped_view=true, tier_a_metrics_only=true, from_trace=false}
  freshness_budget{max_freshness_budget_s=60, components[ingest+query_step+refresh+render], formula}  (G3,FR-ANA-012)
  refresh{default_refresh_interval_s≤30, grafana_dashboard_uid=voice-runtime, auto_refresh, stale_indicator} (G7)
  label_policy{tile_dims_allowed, high_cardinality_keys, pii_forbidden_keys, exemplar_keys}            (G5,G6)
  content_policy{tier=A, forbidden_content_keys}                                                       (G6)
  signal_catalog{metric_signals[15 — grafana panel kümesi BİREBİR ⊆ 0.4.7 metrics.catalog],
                 alarm_signals[11 — 0.4.7 alerts.catalog BİREBİR]}                                     (G2,I10)
  tile_groups{required[latency,errors,traffic,quality,resource,cost,alarms]}                           (G1)
  tiles[≥8]{name, group, kind(metric/alarm), title, signals[], aggregation, scope_support, query_step_s, panel_id, slo} (G1,G2,G3)
  drilldown{exemplar_keys[correlation_id,trace_id], target=call-trace 14.1.1}                          (G8)
  gates{max_coverage_missing=0, max_catalog_mismatch=0, max_freshness_violation=0, max_scope_violation=0,
        max_cardinality_violation=0, max_label_violation=0, max_pii_violation=0, max_content_violation=0,
        max_refresh_violation=0, max_drilldown_violation=0}                                            (G1..G8)
  error_taxonomy{mapping→API §11.6 (malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION)}       (I11)
  pii{raw_payload/transcript/pii_values_in_spec_forbidden}                                             (I12)
  invariants[≥12]{id, desc, trace}

config/live-ops-profiles.json: profiles[]{name, region, ingest_lag_s, refresh_interval_s, render_lag_s}

snapshot sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  context{tenant_id, region?, org_unit?, correlation_id?},
  view_request{scope: platform|tenant, tenant_id?},
  policy?{cover_all, honor_freshness, map_catalog, scope_tenant, enforce_cardinality, enforce_labels,
          enforce_pii, enforce_tier_a, auto_refresh, bind_exemplar},
  signals[]{tile, value?}}
  (PII DEĞERİ YOK — yalnız sinyal + etiket/kimlik anahtarı ADLARI)

komutlar: validate | snapshot <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "snapshot":
        if len(sys.argv) < 3:
            print("kullanım: live_ops_probe.py snapshot <sample.json>")
            return 2
        return snapshot_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|snapshot|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
