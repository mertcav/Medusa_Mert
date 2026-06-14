#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resource_budget_probe.py — WBS 3.1.4 Per-call kaynak bütçesi (~15MB) izleme + sınırlama

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`runtime/turn-taking/` (3.1.3) + `docs/poc/density_probe.py` (0.3.3) disipliniyle aynı; burada
deterministik bir RESOURCE BUDGET GUARD (SAD §6.3 oturum aktörü + SAD §15.2 Cost/Resource Meter)
simülatörü (örnek/olay-tetikli, sanal saat, random YOK).

CONVERSATION ORCHESTRATOR (Çekirdek IP, SAD §6) oturum aktöründe çalışan Guard, her CANLI çağrının
ayak izini ömrü boyunca İZLER ve aşımda KONTROLLÜ SINIRLAMA uygular (FR-RES-016):
  • Bütçe:        oturum-başı orkestratör belleği (MEDYA HARİÇ) ≤ ~15MB + CPU bütçesi (B1/B8).
  • İzleme:       her oturum örneklenir; her hard-aşımı tespit + yayılır; missed_breach=0 (B4).
  • Sınırlama:    WARN→azaltma (özetleme FR-RES-010 + RAG kırpma); BREACH→zorla-özetle→grace sonrası
                  KONTROLLÜ shed/handoff — graceful (FR-RES-014); crash/OOM YASAK (B2/B3).
  • Etkinlik:     azaltma ayak izini gerçekten düşürür (B5).
  • Adillik:      bütçe içindeki sağlıklı oturuma azaltma/shed uygulanmaz (B7).
  • Metrikler:    per-call bellek/CPU/breach → BRD §15 → observability 0.4.7 (B9).

KAPSAM AYRIMI: density'nin offline ÖLÇÜMÜ + fleet kapasite kapısı → 0.3.3 (density_probe);
worker düzeyi backpressure/admission yeni-çağrı reddi → FR-RES-014 (Resource Manager, 0.4.8);
özetleme MOTORU implementasyonu → 3.2.x. Burada YALNIZ oturum-başı runtime izleme + sınırlama.

Komutlar:
  validate              resource-budget-spec.json'ı invariant'lara (B1–B10) + config profillerine doğrular.
  simulate <sample>     Deterministik Guard — oturum örnek-akışı → bant + azaltma/shed kararları +
                        metrikler + HARD kapılar (B2–B5,B7,B8); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek RSS/heap+CPU profiler yerine deterministik simülasyondur
(canlı sistemde Go/Rust runtime, ADR-003/SAD §6.3). Ham ses payload'ı/transkript/PII YOK — yalnız
bileşen boyutu (MB/mcore) + sanal zaman.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "resource-budget-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "resource-budget-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")

# bütçe bileşenleri (0.3.3 density kompozisyonu ile birebir; MEDYA hariç)
COMPONENTS = {"session_state", "dialogue_memory", "prompt_context",
              "rag_context", "adapter_state", "runtime_overhead"}
MITIGABLE = {"dialogue_memory", "rag_context"}   # özetleme/kırpma ile küçülür (FR-RES-010)


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class BudgetError(Exception):
    """Geçersiz/desteklenmeyen örnek — sessizce kabul yok, reddet (B10)."""


def percentile(sorted_vals, p):
    """Lineer-interpolasyon percentile (0.3.x / 2.2.x / 3.1.3 ile birebir). sorted_vals artan."""
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
# Resource Budget Guard — oturum-başı izleme + sınırlama (deterministik)
# ─────────────────────────────────────────────────────────────────────────────
class BudgetGuard:
    """SAD §6.3 oturum aktörü Guard'ı. Oturum örnek-akışını işler, ayak izini bantlar, azaltma
    (özetleme/kırpma) ve kontrollü shed kararlarını verir. Örnek-tetikli, bloklamaz; sanal saat
    (sample.t) — random YOK.

    Bir örnek (sample-point) = oturumun o sanal zamanda ULAŞACAĞI bileşen seviyeleri (azaltma
    UYGULANMADAN önceki TALEP). Guard talebi bantlar ve gerekirse azaltarak ZORLANAN (enforced)
    ayak izini üretir. Medya (media_mb) bütçeye DAHİL DEĞİLDİR — yalnız izlenir (B8)."""

    def __init__(self, budget, policy):
        self.b = budget
        self.pol = policy
        self.hard = float(budget["mem_budget_mb"])
        self.soft = float(budget["soft_threshold_mb"])
        self.cpu_hard = float(budget["cpu_budget_mcore"])
        self.cpu_soft = float(budget.get("cpu_soft_mcore", 0.8 * self.cpu_hard))
        self.grace = int(budget.get("grace_samples", 2))
        self.factor = float(policy.get("summarize_factor", 0.45))

        # sayaçlar / metrikler
        self.n_samples = 0
        self.peak_demand_mb = 0.0
        self.peak_enforced_mb = 0.0
        self.peak_cpu_mcore = 0.0
        self.media_excluded_mb = 0.0           # toplam medya (bütçe DIŞI — yalnız kanıt)
        self.breach_samples = 0                # enforced > hard (post-azaltma) örnek sayısı
        self.breach_detected = 0               # izlemenin tespit ettiği aşım
        self.missed_breach = 0                 # aşım var ama izleme kapalı → tespitsiz (bug)
        self.mitigation_applied = 0            # azaltma uygulanan örnek
        self.mitigation_effective = 0          # azaltmanın ayak izini düşürdüğü örnek
        self.mitigation_ineffective = 0        # mitigable var ama azaltma düşürmedi (bug)
        self.spurious_action = 0               # OK bandında azaltma/shed (adillik ihlali)
        self.shed_count = 0                    # kontrollü shed tetikleme
        self.shed_graceful = True              # tüm shed'ler graceful mi
        self.uncontrolled_oom = 0              # crash/OOM-kill (graceful değil — bug)
        self.unbounded_overshoot = 0           # kontrolsüz hard-aşımı örnek (bug)
        self.enforced_series = []              # zorlanan bellek serisi (percentile için)
        self.band_series = []                  # (t, band) izi
        self._consec_breach = 0                # ardışık BREACH sayacı (grace için)
        self._shed_engaged = False             # oturum kontrollü shed'e alındı mı

    @staticmethod
    def _band(footprint, soft, hard):
        if footprint <= soft:
            return "OK"
        if footprint <= hard:
            return "WARN"
        return "BREACH"

    def _mitigate(self, comps):
        """Özetleme (FR-RES-010): mitigable bileşenleri summarize_factor oranında küçült."""
        out = dict(comps)
        for k in MITIGABLE:
            if k in out:
                out[k] = out[k] * (1.0 - self.factor)
        return out

    def step(self, s):
        if not isinstance(s, dict):
            raise BudgetError("örnek sözlük değil → INVALID_REQUEST")
        t = s.get("t")
        if not isinstance(t, (int, float)):
            raise BudgetError("örnek zaman damgası sayısal değil → INVALID_REQUEST")
        comps = s.get("components_mb")
        if not isinstance(comps, dict) or not comps:
            raise BudgetError("components_mb yok/boş → INVALID_REQUEST")
        for k, v in comps.items():
            if k not in COMPONENTS:
                raise BudgetError("bilinmeyen bütçe bileşeni: %r → INVALID_REQUEST" % k)
            if not isinstance(v, (int, float)) or v < 0:
                raise BudgetError("bileşen boyutu sayısal/≥0 değil: %r → INVALID_REQUEST" % k)
        media = s.get("media_mb", 0.0)
        if not isinstance(media, (int, float)) or media < 0:
            raise BudgetError("media_mb sayısal/≥0 değil → INVALID_REQUEST")
        cpu = s.get("cpu_mcore", 0.0)
        if not isinstance(cpu, (int, float)) or cpu < 0:
            raise BudgetError("cpu_mcore sayısal/≥0 değil → INVALID_REQUEST")

        self.n_samples += 1
        self.media_excluded_mb = max(self.media_excluded_mb, float(media))   # bütçe DIŞI (B8)

        # ── TALEP (azaltma öncesi); MEDYA HARİÇ (B8)
        demand = float(sum(comps.values()))
        self.peak_demand_mb = max(self.peak_demand_mb, demand)
        self.peak_cpu_mcore = max(self.peak_cpu_mcore, float(cpu))

        enforced_comps = comps
        enforced = demand
        demand_band = self._band(demand, self.soft, self.hard)
        cpu_band = self._band(cpu, self.cpu_soft, self.cpu_hard)

        if self.pol.get("enforce", True) and not self._shed_engaged:
            # ── adillik: OK bandında azaltma YOK (yanlış 'spurious' politikası B7'yi kanıtlar)
            if demand_band == "OK" and cpu_band == "OK":
                if self.pol.get("spurious", False) and self.pol.get("mitigate", True):
                    enforced_comps = self._mitigate(comps)
                    enforced = float(sum(enforced_comps.values()))
                    self.spurious_action += 1
            else:
                # ── WARN/BREACH: azaltma (özetleme + RAG kırpma — FR-RES-010)
                if self.pol.get("mitigate", True):
                    enforced_comps = self._mitigate(comps)
                    enforced = float(sum(enforced_comps.values()))
                    self.mitigation_applied += 1
                    mitigable_present = any(k in comps and comps[k] > 0 for k in MITIGABLE)
                    if enforced < demand - 1e-9:
                        self.mitigation_effective += 1
                    elif mitigable_present:
                        # mitigable var ama düşmedi → azaltma etkisiz (bug, B5)
                        self.mitigation_ineffective += 1

        enforced_band = self._band(enforced, self.soft, self.hard)
        over_hard = enforced > self.hard or cpu > self.cpu_hard
        self.peak_enforced_mb = max(self.peak_enforced_mb, enforced)
        self.enforced_series.append(enforced)
        self.band_series.append((t, "BREACH" if over_hard else enforced_band))

        # ── İZLEME (B4): aşımı tespit + yayınla; izleme kapalıysa tespitsiz (missed)
        if over_hard:
            self.breach_samples += 1
            if self.pol.get("monitor", True):
                self.breach_detected += 1
            else:
                self.missed_breach += 1

        # ── SINIRLAMA (B2/B3): aşım kontrol altında mı?
        if over_hard:
            if not self.pol.get("enforce", True):
                # sınırlama kapalı → kontrolsüz büyüme (FR-RES-014 ihlali)
                self.unbounded_overshoot += 1
            elif self._shed_engaged:
                pass  # zaten kontrollü shed'e alındı → kontrollü
            else:
                self._consec_breach += 1
                if self._consec_breach >= self.grace:
                    # ── grace doldu → yükselt: kontrollü shed mi, çökme mi?
                    action = self.pol.get("on_breach", "shed")
                    if action in ("shed", "handoff"):
                        self.shed_count += 1
                        self._shed_engaged = True       # oturum graceful sınırlandı
                    else:  # "crash" / kontrolsüz → B3 ihlali
                        self.uncontrolled_oom += 1
                        self.shed_graceful = False
                        self.unbounded_overshoot += 1
        else:
            self._consec_breach = 0

    def metrics(self):
        ser = sorted(self.enforced_series)
        p95 = round(percentile(ser, 0.95), 2)
        scenario = []
        if self.breach_samples > 0:
            scenario.append("breach")
        if self.mitigation_applied > 0:
            scenario.append("mitigation")
        if self.media_excluded_mb > 0:
            scenario.append("media")
        if self.shed_count > 0:
            scenario.append("shed")
        if not scenario:
            scenario.append("healthy")
        return {
            "n_samples": self.n_samples,
            "peak_demand_mb": round(self.peak_demand_mb, 2),
            "peak_enforced_mb": round(self.peak_enforced_mb, 2),
            "enforced_p95_mb": p95,
            "peak_cpu_mcore": round(self.peak_cpu_mcore, 2),
            "media_excluded_mb": round(self.media_excluded_mb, 2),
            "breach_samples": self.breach_samples,
            "breach_detected": self.breach_detected,
            "missed_breach": self.missed_breach,
            "mitigation_applied": self.mitigation_applied,
            "mitigation_effective": self.mitigation_effective,
            "mitigation_ineffective": self.mitigation_ineffective,
            "spurious_action": self.spurious_action,
            "shed_count": self.shed_count,
            "shed_graceful": self.shed_graceful,
            "uncontrolled_oom": self.uncontrolled_oom,
            "unbounded_overshoot": self.unbounded_overshoot,
            "scenario": scenario,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, budget, policy):
    pts = sample.get("samples")
    if not pts:
        raise BudgetError("boş örnek akışı")
    if not isinstance(pts, list):
        raise BudgetError("samples liste değil → INVALID_REQUEST")
    indexed = list(enumerate(pts))
    for _, p in indexed:
        if not isinstance(p, dict) or not isinstance(p.get("t"), (int, float)):
            raise BudgetError("geçersiz örnek (zaman damgası): %r → INVALID_REQUEST" % (p,))
    ordered = sorted(indexed, key=lambda pr: (pr[1]["t"], pr[0]))
    g = BudgetGuard(budget, policy)
    for _, p in ordered:
        g.step(p)
    return g.metrics()


def evaluate(gates, m):
    """Metrikleri HARD kapılara (B2–B5,B7,B8) karşı değerlendirir. Döner findings[(ok, label)]."""
    F = []
    sc = set(m.get("scenario", []))

    # ── B2: kontrolsüz aşım yok (her senaryoda)
    F.append((m.get("unbounded_overshoot", 0) <= gates.get("max_unbounded_overshoot", 0),
              "B2 kontrolsüz aşım %d ≤ %d (her hard-aşımı azaltma veya kontrollü shed ile sınırlanır — FR-RES-014)"
              % (m.get("unbounded_overshoot", 0), gates.get("max_unbounded_overshoot", 0))))

    # ── B3: graceful sınırlama (her senaryoda)
    F.append((m.get("uncontrolled_oom", 0) <= gates.get("max_uncontrolled_oom", 0)
              and m.get("shed_graceful", True),
              "B3 kontrolsüz OOM %d ≤ %d + shed graceful=%s (çökme yerine özetle/shed/handoff — FR-RES-014)"
              % (m.get("uncontrolled_oom", 0), gates.get("max_uncontrolled_oom", 0),
                 m.get("shed_graceful", True))))

    # ── B4: izleme kapsamı (her senaryoda)
    F.append((m.get("missed_breach", 0) <= gates.get("max_missed_breach", 0),
              "B4 tespitsiz aşım %d ≤ %d (her aşım izlenir+yayılır — FR-RES-016 'aşımı izlenir')"
              % (m.get("missed_breach", 0), gates.get("max_missed_breach", 0))))

    # ── B7: adillik — sağlıklı oturuma müdahale yok (her senaryoda)
    F.append((m.get("spurious_action", 0) <= gates.get("max_spurious_action", 0),
              "B7 spurious eylem %d ≤ %d (bütçe içindeki sağlıklı oturuma azaltma/shed yok — adillik)"
              % (m.get("spurious_action", 0), gates.get("max_spurious_action", 0))))

    # ── B8: medya bütçe DIŞI (her senaryoda) — peak_enforced medyayı içermez
    hard = gates.get("mem_budget_mb", 15.0)
    media_ok = (m.get("media_excluded_mb", 0.0) == 0.0) or (
        m.get("peak_enforced_mb", 0.0) <= m.get("peak_demand_mb", 0.0) + 1e-9)
    F.append((media_ok,
              "B8 medya bütçe dışı: medya=%.1fMB izlendi, bütçe ayak izi medyasız (SAD §6/§13; bütçe medya-bağımsız)"
              % m.get("media_excluded_mb", 0.0)))

    if "mitigation" in sc:
        # ── B5: azaltma etkili (yalnız azaltma uygulandıysa)
        F.append((m.get("mitigation_ineffective", 0) <= gates.get("max_mitigation_ineffective", 0),
                  "B5 etkisiz azaltma %d ≤ %d (özetleme ayak izini gerçekten düşürür — FR-RES-010)"
                  % (m.get("mitigation_ineffective", 0), gates.get("max_mitigation_ineffective", 0))))

    if "breach" in sc:
        # ── breach senaryosunda izlemenin gerçekten tespit ettiğini doğrula (B4 pozitif kanıt)
        F.append((m.get("breach_detected", 0) >= 1 or m.get("missed_breach", 0) == 0,
                  "B4+ aşım tespit edildi (detected=%d, missed=%d)"
                  % (m.get("breach_detected", 0), m.get("missed_breach", 0))))

    return F


# ─────────────────────────────────────────────────────────────────────────────
# parametre + politika çözümleme
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise BudgetError("bilinmeyen profil: %s" % name)


def _budget_from(spec, profile):
    """Spec budget varsayılanları + profil override → çözümlenen bütçe."""
    b = dict(spec.get("budget", {}))
    for k in ("mem_budget_mb", "soft_threshold_mb", "cpu_budget_mcore",
              "cpu_soft_mcore", "grace_samples"):
        if k in profile:
            b[k] = profile[k]
    return b


def _resolve_policy(spec, profile, sample):
    """Spec enforcement varsayılanları + profil + sample.policy override → sınırlama politikası."""
    enf = spec.get("enforcement", {})
    pol = {
        "enforce": True,
        "monitor": True,
        "mitigate": True,
        "spurious": False,
        "on_breach": "shed",
        "monitor_blocking": False,
        "summarize_factor": profile.get("summarize_factor", enf.get("summarize_factor", 0.45)),
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
        except BudgetError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    budget = _budget_from(spec, profile)
    policy = _resolve_policy(spec, profile, sample)
    gates = spec.get("gates", {})

    try:
        m = simulate(sample, budget, policy)
    except BudgetError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(gates, m)
    print("simulate[%s] senaryo=%s | %d örnek | talep-tepe %.1fMB → zorlanan-tepe %.1fMB "
          "(P95 %.1fMB, bütçe %.0fMB) | CPU-tepe %.0fmcore | medya-hariç %.1fMB"
          % (name, "+".join(m["scenario"]), m["n_samples"], m["peak_demand_mb"],
             m["peak_enforced_mb"], m["enforced_p95_mb"], budget["mem_budget_mb"],
             m["peak_cpu_mcore"], m["media_excluded_mb"]))
    print("  aşım=%d (tespit=%d, tespitsiz=%d) | azaltma=%d (etkili=%d, etkisiz=%d) | "
          "shed=%d (graceful=%s) | OOM=%d | spurious=%d"
          % (m["breach_samples"], m["breach_detected"], m["missed_breach"],
             m["mitigation_applied"], m["mitigation_effective"], m["mitigation_ineffective"],
             m["shed_count"], m["shed_graceful"], m["uncontrolled_oom"], m["spurious_action"]))
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

    _check(R, spec.get("wbs") == "3.1.4", "spec.wbs == 3.1.4")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── placement (orchestrator oturum aktörü, olay-tetikli, medya hariç)
    pl = spec.get("placement", {})
    _check(R, pl.get("in_orchestrator") is True and pl.get("in_session_actor") is True,
           "Guard orchestrator oturum aktöründe (SAD §6.3)")
    _check(R, pl.get("event_driven") is True and pl.get("non_blocking") is True,
           "B6 olay/örnek-tetikli + bloklamaz (sıcak yola gecikme yok)")
    _check(R, pl.get("media_in_budget") is False,
           "B8 placement medya bütçe dışı")
    _check(R, pl.get("reports_to_resource_manager") is True,
           "metrik Resource Manager Cost/Resource Meter'a raporlanır (SAD §15.2)")

    # ── B1: bütçe tanımı
    b = spec.get("budget", {})
    _check(R, isinstance(b.get("mem_budget_mb"), (int, float)) and 0 < b["mem_budget_mb"] <= 15.0,
           "B1 mem_budget_mb ≤ 15 (NFR 10.2/FR-RES-016)")
    _check(R, 0 < b.get("soft_threshold_mb", 1e9) < b.get("mem_budget_mb", 0),
           "B1 soft_threshold < mem_budget (WARN bandı geçerli)")
    _check(R, isinstance(b.get("cpu_budget_mcore"), (int, float)) and b["cpu_budget_mcore"] > 0,
           "B1 cpu_budget_mcore > 0")
    _check(R, b.get("media_excluded") is True, "B8 budget.media_excluded = true")
    _check(R, set(b.get("components", [])) == COMPONENTS,
           "B8 bütçe bileşenleri 0.3.3 density kompozisyonu (medya hariç)")
    _check(R, set(b.get("mitigable_components", [])) == MITIGABLE,
           "B5 mitigable bileşenler = {dialogue_memory, rag_context} (FR-RES-010)")
    _check(R, isinstance(b.get("grace_samples"), int) and b["grace_samples"] >= 1,
           "B2 grace_samples ≥ 1 (azaltmaya fırsat)")

    # ── bands
    bd = spec.get("bands", {})
    _check(R, all(k in bd for k in ("ok", "warn", "breach")),
           "bant tanımları (OK/WARN/BREACH) mevcut")

    # ── enforcement (graceful, crash yasak, adillik)
    en = spec.get("enforcement", {})
    _check(R, en.get("graceful_only") is True, "B3 enforcement graceful_only")
    _check(R, en.get("crash_forbidden") is True, "B3 crash_forbidden")
    _check(R, en.get("breach_action") == "force_mitigate_then_controlled_shed",
           "B2 breach→zorla-azalt→kontrollü shed")
    _check(R, en.get("warn_action") == "mitigate_summarize_trim",
           "B5 WARN→azaltma (özetle/kırp)")
    _check(R, 0.0 < en.get("summarize_factor", 0) < 1.0,
           "B5 summarize_factor ∈ (0,1)")
    _check(R, en.get("fairness_no_spurious_action") is True, "B7 adillik (spurious yok)")

    # ── monitoring
    mn = spec.get("monitoring", {})
    _check(R, mn.get("every_session_sampled") is True
           and mn.get("breach_detected_and_emitted") is True,
           "B4 her oturum örneklenir + aşım tespit/yayılır")
    _check(R, mn.get("sampling_non_blocking") is True, "B6 örnekleme non-blocking")

    # ── kapılar
    g = spec.get("gates", {})
    _check(R, g.get("mem_budget_mb") == b.get("mem_budget_mb"),
           "gates mem_budget budget ile tutarlı")
    _check(R, g.get("soft_threshold_mb") == b.get("soft_threshold_mb"),
           "gates soft budget ile tutarlı")
    _check(R, g.get("grace_samples") == b.get("grace_samples"),
           "gates grace budget ile tutarlı")
    _check(R, g.get("max_unbounded_overshoot", -1) == 0, "B2 max_unbounded_overshoot = 0")
    _check(R, g.get("max_uncontrolled_oom", -1) == 0, "B3 max_uncontrolled_oom = 0")
    _check(R, g.get("max_missed_breach", -1) == 0, "B4 max_missed_breach = 0")
    _check(R, g.get("max_mitigation_ineffective", -1) == 0, "B5 max_mitigation_ineffective = 0")
    _check(R, g.get("max_spurious_action", -1) == 0, "B7 max_spurious_action = 0")
    _check(R, g.get("media_in_budget") is False, "B8 gates media_in_budget = false")

    # ── B9: metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"per_call_memory_mb", "per_call_cpu_mcore", "budget_breach_total"} <= emitted,
           "B9 per-call kaynak + breach metrikleri yayılır")
    mo = me.get("maps_to_observability", {})
    _check(R, mo.get("per_call_memory_mb") and mo.get("per_call_cpu_mcore"),
           "B9 per-call bellek/CPU observability'ye eşlenir (0.4.7)")

    # ── B10: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "B10 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "B10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_sample") == "INVALID_REQUEST"
           and mapping.get("resource_exhausted_controlled_shed") == "QUOTA_EXCEEDED"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "B10 bozuk-örnek→INVALID, kontrollü-shed→QUOTA_EXCEEDED, bölge→REGION_VIOLATION")

    # ── B10: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "B10 residency region pin")
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "B10 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "B10 transkript spec'te yasak")

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
    _check(R, not hits, "B10 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 bütçe profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "B10 config %s bölge pini var" % p.get("name"))
            _check(R, 0 < p.get("mem_budget_mb", 99) <= 15.0,
                   "B1 config %s mem_budget ≤ 15" % p.get("name"))
            _check(R, p.get("soft_threshold_mb", 1e9) < p.get("mem_budget_mb", 0),
                   "B1 config %s soft < hard" % p.get("name"))
            _check(R, 0.0 < p.get("summarize_factor", 0.45) < 1.0,
                   "B5 config %s summarize_factor ∈ (0,1)" % p.get("name"))

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
def _pt(t, **comps):
    media = comps.pop("media_mb", None)
    cpu = comps.pop("cpu_mcore", None)
    s = {"t": t, "components_mb": comps}
    if media is not None:
        s["media_mb"] = media
    if cpu is not None:
        s["cpu_mcore"] = cpu
    return s


DEFAULT_BUDGET = {"mem_budget_mb": 15.0, "soft_threshold_mb": 12.0,
                  "cpu_budget_mcore": 100.0, "cpu_soft_mcore": 80.0, "grace_samples": 2}


def _run(points, **pol_over):
    pol = {"enforce": True, "monitor": True, "mitigate": True,
           "spurious": False, "on_breach": "shed", "summarize_factor": 0.45}
    pol.update(pol_over)
    return simulate({"samples": points}, DEFAULT_BUDGET, pol)


def _base_comps(dialogue):
    """Tipik oturum bileşenleri; dialogue_memory değişkeni ile ayak izi ayarlanır."""
    return dict(session_state=1.2, dialogue_memory=dialogue, prompt_context=1.4,
                adapter_state=1.4, runtime_overhead=0.9)


def selftest():
    spec = _load(SPEC_PATH)
    gates = spec.get("gates", {})
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── percentile (0.3.x/3.1.3 ile birebir)
    case(abs(percentile([10, 20, 30, 40], 0.95) - 38.5) < 1e-6, "percentile P95 lineer-interp")
    case(percentile([], 0.95) == 0.0 and percentile([7], 0.95) == 7.0, "percentile boş/tekil")

    # ── healthy: ayak izi ≤ soft, eylem yok ──────────────────────────────────────
    # base sabit = 1.2+1.4+1.4+0.9 = 4.9; dialogue 4.0 → 8.9MB (≤12 soft)
    healthy = [_pt(0, **_base_comps(2.0)), _pt(5000, **_base_comps(4.0)), _pt(10000, **_base_comps(4.0))]
    mh = _run(healthy)
    case(mh["peak_enforced_mb"] <= 12.0 and mh["breach_samples"] == 0, "healthy: ≤soft, aşım yok")
    case(mh["mitigation_applied"] == 0 and mh["spurious_action"] == 0, "healthy: azaltma/spurious yok (adillik B7)")
    case("healthy" in mh["scenario"], "healthy: senaryo=healthy")
    case(all(ok for ok, _ in evaluate(gates, mh)), "healthy tüm kapıları geçer")

    # ── warn-mitigated: soft aşılır, özetleme bütçeye döndürür, shed yok ──────────
    # dialogue 8.5 + rag 2.0 → base 4.9+8.5+2.0 = 15.4 (WARN üstü/breach sınırı); azaltma 0.45 →
    # dialogue 4.675 + rag 1.1 + base 4.9 = 10.675 (≤12) → bütçeye döner
    warn = [
        _pt(0, **_base_comps(4.0)),
        _pt(8000, **dict(_base_comps(8.5), rag_context=2.0)),
        _pt(16000, **dict(_base_comps(8.5), rag_context=2.0)),
    ]
    mw = _run(warn)
    case(mw["mitigation_applied"] >= 1 and mw["mitigation_effective"] >= 1, "warn: azaltma uygulandı+etkili (B5)")
    case(mw["mitigation_ineffective"] == 0, "warn: etkisiz azaltma yok (B5)")
    case(mw["breach_samples"] == 0 and mw["shed_count"] == 0, "warn: özetleme breach/shed'i önledi")
    case(mw["peak_enforced_mb"] < mw["peak_demand_mb"], "warn: zorlanan < talep (özetleme küçülttü)")
    case(all(ok for ok, _ in evaluate(gates, mw)), "warn-mitigated tüm kapıları geçer")

    # ── breach-shed: azaltma yetmez → grace sonrası kontrollü shed (graceful) ─────
    # dialogue 22 + rag 8 → base 4.9+22+8 = 34.9; azaltma → 4.9 + 12.1 + 4.4 = 21.4 (>15 hâlâ breach)
    big = lambda: dict(_base_comps(22.0), rag_context=8.0)
    breach = [_pt(0, **_base_comps(4.0)), _pt(6000, **big()), _pt(12000, **big()), _pt(18000, **big())]
    mb = _run(breach)
    case(mb["breach_samples"] >= 2 and mb["breach_detected"] >= 2, "breach: aşım tespit edildi (B4)")
    case(mb["shed_count"] == 1 and mb["shed_graceful"] is True, "breach: 1 kontrollü graceful shed")
    case(mb["uncontrolled_oom"] == 0 and mb["unbounded_overshoot"] == 0, "breach: kontrolsüz OOM/aşım yok (B2/B3)")
    case(all(ok for ok, _ in evaluate(gates, mb)), "breach-shed tüm kapıları geçer (graceful sınırlama)")

    # ── media-excluded: yüksek medya tamponu ama bütçe medyasız ≤ soft ────────────
    med = [_pt(0, media_mb=10.0, **_base_comps(4.0)), _pt(5000, media_mb=12.0, **_base_comps(5.0))]
    mm = _run(med)
    case(mm["media_excluded_mb"] == 12.0, "media: medya izlendi (12MB)")
    case(mm["peak_enforced_mb"] <= 12.0 and mm["breach_samples"] == 0, "media: bütçe ayak izi medyasız ≤soft (B8)")
    case(all(ok for ok, _ in evaluate(gates, mm)), "media-excluded tüm kapıları geçer")

    # ── cpu-breach: CPU bütçe aşımı → grace sonrası kontrollü shed ────────────────
    cpu_b = [_pt(0, cpu_mcore=60, **_base_comps(4.0)),
             _pt(6000, cpu_mcore=140, **_base_comps(4.0)),
             _pt(12000, cpu_mcore=140, **_base_comps(4.0)),
             _pt(18000, cpu_mcore=140, **_base_comps(4.0))]
    mcpu = _run(cpu_b)
    case(mcpu["breach_samples"] >= 2 and mcpu["shed_count"] == 1, "cpu: CPU aşımı → kontrollü shed (özetlenemez)")
    case(mcpu["uncontrolled_oom"] == 0 and all(ok for ok, _ in evaluate(gates, mcpu)),
         "cpu-breach graceful sınırlama kapıları geçer")

    # ── degraded-1: sınırlama kapalı → kontrolsüz aşım (B2 eler) ──────────────────
    d1 = _run(breach, enforce=False)
    case(d1["unbounded_overshoot"] >= 1, "degraded(enforce off): kontrolsüz aşım (B2 eler)")
    case(not all(ok for ok, _ in evaluate(gates, d1)), "degraded(enforce off) en az bir kapıyı eler")

    # ── degraded-2: izleme kapalı → tespitsiz aşım (B4 eler) ──────────────────────
    d2 = _run(breach, monitor=False)
    case(d2["missed_breach"] >= 1 and d2["breach_detected"] == 0, "degraded(monitor off): tespitsiz aşım (B4 eler)")
    case(not all(ok for ok, _ in evaluate(gates, d2)), "degraded(monitor off) en az bir kapıyı eler")

    # ── degraded-3: crash on_breach → kontrolsüz OOM (B3 eler) ────────────────────
    d3 = _run(breach, on_breach="crash")
    case(d3["uncontrolled_oom"] >= 1 and d3["shed_graceful"] is False, "degraded(crash): kontrolsüz OOM (B3 eler)")
    case(not all(ok for ok, _ in evaluate(gates, d3)), "degraded(crash) en az bir kapıyı eler")

    # ── degraded-4: spurious → sağlıklı oturuma azaltma (B7 eler) ─────────────────
    d4 = _run(healthy, spurious=True)
    case(d4["spurious_action"] >= 1, "degraded(spurious): sağlıklı oturuma azaltma (B7 eler)")
    case(not all(ok for ok, _ in evaluate(gates, d4)), "degraded(spurious) en az bir kapıyı eler")

    # ── determinizm: aynı giriş → birebir aynı metrik ────────────────────────────
    case(_run(breach) == mb, "determinizm: aynı örnek-akışı birebir aynı metrik (random yok)")

    # ── örnek sıralaması: karışık t → zaman sırasına göre işlenir ─────────────────
    uo = [_pt(12000, **big()), _pt(0, **_base_comps(4.0)), _pt(6000, **big()), _pt(18000, **big())]
    case(_run(uo) == mb, "sıralama: karışık t doğru zaman sırasında (breach ile birebir)")

    # ── geçersiz örnek reddi (B10) ───────────────────────────────────────────────
    case(_raises(lambda: _run([{"t": 0, "components_mb": {"nope": 1.0}}])), "B10 bilinmeyen bileşen → reddedilir")
    case(_raises(lambda: _run([{"components_mb": _base_comps(4.0)}])), "B10 zaman damgasız örnek → reddedilir")
    case(_raises(lambda: _run([{"t": 0, "components_mb": {}}])), "B10 boş components_mb → reddedilir")
    case(_raises(lambda: _run([{"t": 0, "components_mb": {"dialogue_memory": -1.0}}])), "B10 negatif boyut → reddedilir")
    case(_raises(lambda: simulate({"samples": []}, DEFAULT_BUDGET, {})), "B10 boş örnek akışı → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["budget"]["mem_budget_mb"] = 20.0; s["gates"]["mem_budget_mb"] = 20.0
    case(_validate_obj(s) != 0, "B1 mem_budget > 15 → validate eler")
    s = json.loads(json.dumps(spec)); s["budget"]["soft_threshold_mb"] = 16.0
    case(_validate_obj(s) != 0, "B1 soft ≥ hard → validate eler")
    s = json.loads(json.dumps(spec)); s["budget"]["media_excluded"] = False
    case(_validate_obj(s) != 0, "B8 media_excluded=false → validate eler")
    s = json.loads(json.dumps(spec)); s["enforcement"]["crash_forbidden"] = False
    case(_validate_obj(s) != 0, "B3 crash_forbidden=false → validate eler")
    s = json.loads(json.dumps(spec)); s["enforcement"]["graceful_only"] = False
    case(_validate_obj(s) != 0, "B3 graceful_only=false → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_unbounded_overshoot"] = 1
    case(_validate_obj(s) != 0, "B2 max_unbounded_overshoot>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_uncontrolled_oom"] = 1
    case(_validate_obj(s) != 0, "B3 max_uncontrolled_oom>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_missed_breach"] = 1
    case(_validate_obj(s) != 0, "B4 max_missed_breach>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_spurious_action"] = 1
    case(_validate_obj(s) != 0, "B7 max_spurious_action>0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["media_in_budget"] = True
    case(_validate_obj(s) != 0, "B8 gates media_in_budget=true → validate eler")
    s = json.loads(json.dumps(spec)); s["budget"]["mitigable_components"] = ["session_state"]
    case(_validate_obj(s) != 0, "B5 mitigable yanlış küme → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "B10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["raw_payload_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "B10 ham-payload-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["budget"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "B10 literal secret → validate eler")

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
    except BudgetError:
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
    print("""resource-budget-spec.json beklenen şekli (WBS 3.1.4):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability,poc}
  placement{in_orchestrator=true, in_session_actor=true, event_driven=true,
            non_blocking=true, media_in_budget=false, reports_to_resource_manager=true}  (B6,B8)
  budget{mem_budget_mb≤15, soft_threshold_mb<hard, cpu_budget_mcore>0, cpu_soft_mcore,
         media_excluded=true, components[6], mitigable_components[2], grace_samples≥1}    (B1,B5,B8)
  bands{ok, warn, breach}
  enforcement{warn_action, breach_action, graceful_only=true, crash_forbidden=true,
              summarize_factor∈(0,1), fairness_no_spurious_action=true}                   (B2,B3,B5,B7)
  monitoring{every_session_sampled=true, breach_detected_and_emitted=true,
             sampling_non_blocking=true}                                                  (B4,B6)
  gates{mem_budget_mb, soft_threshold_mb, cpu_budget_mcore, grace_samples,
        max_unbounded_overshoot=0, max_uncontrolled_oom=0, max_missed_breach=0,
        max_mitigation_ineffective=0, max_spurious_action=0, media_in_budget=false}   (B2,B3,B4,B5,B7,B8)
  metrics{emitted[], maps_to_observability{per_call_memory_mb→…, per_call_cpu_mcore→…}}    (B9)
  error_taxonomy{mapping→API §11.6}                                                       (B10)
  residency{region_pin_required=true}                                                     (B10)
  pii{raw_payload_in_spec_forbidden, transcript_in_spec_forbidden}                        (B10)
  invariants[≥10]{id, desc, trace}

config/resource-budget-profiles.json: profiles[]{name, deployment, mem_budget_mb (≤15),
  soft_threshold_mb (<hard), cpu_budget_mcore, cpu_soft_mcore, grace_samples,
  summarize_factor, region}

simulate sample: {name, profile | profile_obj, expect, expected?{metrik:değer},
  policy?{enforce, monitor, mitigate, spurious, on_breach (shed|handoff|crash), summarize_factor},
  samples[{t (ms), components_mb{session_state,dialogue_memory,prompt_context,rag_context,
  adapter_state,runtime_overhead}, media_mb?, cpu_mcore?}]}  — medya bütçe DIŞI (B8)

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: resource_budget_probe.py simulate <sample.json>")
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
