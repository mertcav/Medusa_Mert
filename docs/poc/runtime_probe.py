#!/usr/bin/env python3
"""runtime_probe.py — Hot-path dil doğrulaması: Go vs Rust async runtime (WBS 0.3.5, →ADR-003).

Amaç: Conversation Orchestrator hot path'inin **hangi runtime dilinde** yazılacağını (ADR-003 —
"async, düşük-bellekli dil: Go veya Rust") ölçüm temelli kapatmak. ADR-003 dili bir **gereklilik**
olarak Go/Rust'a daraltmıştı (GC-ağır/thread-per-call runtime density'yi sağlayamaz); bu PoC iki şeyi
yapar: (1) GC-ağır/thread-per-call baseline'ın NFR 10.1+10.2 kapılarından **elendiğini** doğrular
(ADR-003'ün ret gerekçesi), (2) HARD-geçen Go ve Rust adayları arasında ağırlıklı bir karar matrisiyle
**öneri** üretir → ADR-003 `Önerilen`→`Kabul`.

Bu probe vendor/dil **seçmez** anlamında değil — tam tersine ADR-003 gereği **dil seçer**; ama bunu
sağlayıcı-nötr disiplinle (stdlib-only, credential-free, deterministik) ve ölçülebilir kapı + beyan
edilen nitel boyutlarla yapar. Ölçülen boyutlar simülasyondan; nitel boyutlar (geliştirme hızı, ekosistem,
güvenlik, ops) profilde **beyan edilir** (0.2.x rubrik soft-ölçüt disiplini).

Karar problemi (SAD §21, ADR-003):
  Runtime dili **yalnız** üç şeyi etkiler; zincirin geri kalanı (STT/LLM/TTS sağlayıcı-bağlı gecikme,
  diyalog/prompt/RAG belleği = veri) dilden bağımsızdır:
  - **runtime kuyruğu (tail):** GC duraklaması / scheduler jitter → e2e P99 ve **barge-in kesme**
    kuyruğuna eklenir. Go: küçük GC STW kuyruğu (sub-10ms). Rust: ~0 (GC yok, deterministik).
    GC-ağır/thread-per-call: büyük STW kuyruğu → barge-in ≤200ms kapısını riske atar.
  - **oturum-başı runtime bellek overhead'i:** GC canlı-heap çarpanı + goroutine/thread stack'leri →
    15 MB bütçesine (FR-RES-016) eklenir. Go: ılımlı. Rust: en düşük. Thread-per-call: en yüksek.
  - **oturum-başı CPU:** density CPU tavanını belirler (NFR 10.2). Go/Rust verimli; thread-per-call
    bağlam-değiştirme overhead'iyle density'yi düşürür.
  DEĞİŞMEYEN (`rest_of_chain`, dilden bağımsız): STT final + orchestrator/policy + LLM first-token +
  TTS first-byte gecikmesi; diyalog/prompt/RAG bellek bileşenleri. 0.3.2/0.3.3/0.3.4 ile tutarlı.

Metrik tanımı (yetkili kapılar — 0.3.2/0.3.3/0.3.4 ile BİREBİR):
  GECIKME (NFR 10.1 / SAD §20): end-of-utterance → ilk agent sesi (e2e) ve barge-in kesme.
  DENSITY (NFR 10.2 / SAD §15.2): oturum-başı orkestratör belleği (medya hariç) P95 ≤ 15 MB +
    referans worker (8 vCPU/16 GB) başına density ≥ 250–500. Medya ADR-009 (hibrit) gereği ayrı
    katmandadır → orkestratör runtime'ına eş-konumlu DEĞİL (media_colocated yok).

Tasarım ilkeleri (CLAUDE.md + 0.2.x/0.3.x hattıyla aynı):
- **Dil-nötr ölçüm, ADR-003 gereği dil-seçen karar:** Bileşen dağılımları SAD §20/§15/§21 + ADR-003
  hedeflerinden türetilmiş **mühendislik profilleridir** (`samples/runtime-*.json`). Canlı PoC'ta
  (Faz 1 + telemetri) aynı profil yapısı gerçek RSS/heap + GC-pause + CPU telemetri ile doldurulur;
  kapı/karar mantığı değişmez.
- **stdlib-only / deterministik:** Harici bağımlılık yok; tohumlu `random.Random(seed)`. `LogNormalComponent`
  + `percentile` 0.3.1/0.3.2/0.3.3/0.3.4 ile **birebir aynı**.
- **Karar ≠ ölçüm uydurma:** Öneri = HARD-geçen adaylar arasında ağırlıklı skorun en yükseği.

Modlar:
  evaluate  — Bir runtime profilini (samples/runtime-*.json) ölç → gecikme + barge-in + density +
              NFR 10.1/10.2 kapı verdict'i (çıkış kodu: 0=her iki HARD kapı geçti, 1=kaldı).
  compare   — Runtime adaylarını tablo + karar matrisi halinde karşılaştır → ADR-003 ÖNERİSİ
              (çıkış kodu: 0=geçen aday var + öneri üretildi, 1=hiçbir aday her iki kapıyı geçmiyor).
  selftest  — Dahili deterministik runtime'larla kapı/karar/determinizm invariant'ları (CI).
  schema    — Profil JSON şemasını ve karar ağırlıklarını yazar.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys

# --- NFR 10.1 gecikme kapıları (yetkili; 0.3.2/0.3.4 ile aynı) ------------------------------------
E2E_P50_MS = 700.0      # end-of-utterance → ilk agent sesi P50 ≤ 700 ms
E2E_P95_MS = 1200.0     # P95 ≤ 1200 ms
E2E_P99_MS = 2000.0     # P99 ≤ 2000 ms
BARGEIN_P95_MS = 200.0  # barge-in sonrası TTS kesme P95 ≤ 200 ms (FR-RTC-002, ADR-005)

# --- NFR 10.2 density kapıları (yetkili; 0.3.3/0.3.4 ile aynı) ------------------------------------
BUDGET_MEM_MB = 15.0    # oturum-başı orkestratör belleği (medya hariç) P95 ≤ 15 MB (FR-RES-016)
DENSITY_MIN = 250       # worker başına eş zamanlı oturum ≥ 250 (HARD)
DENSITY_TARGET = 500    # ≥ 500 stretch hedef (YUMUŞAK)

Z95 = 1.6448536269514722

# --- Karar matrisi ağırlıkları (ADR-003; toplam = 1.0) -------------------------------------------
# Ölçülen boyutlar (latency_tail/density) + nitel beyan boyutları (dev_velocity/ecosystem/safety/ops).
DECISION_WEIGHTS = {
    "latency_tail": 0.15,   # barge-in/P99 GC-pause headroom (ölçülen) — Rust GC'siz avantajı
    "density":      0.20,   # worker density (ölçülen) — Rust düşük ayak izi avantajı
    "dev_velocity": 0.20,   # geliştirme hızı / eşzamanlılık basitliği / yetenek havuzu (beyan) — Go
    "ecosystem":    0.15,   # SPI/gRPC/telefoni/medya/cloud-native kütüphane olgunluğu (beyan) — Go
    "safety":       0.15,   # bellek/eşzamanlılık güvenlik garantileri (beyan) — Rust derleyici-zorlamalı
    "ops":          0.15,   # build/compile-time/deploy/operability (beyan) — Go
}

# --- Dilden BAĞIMSIZ zincir kalemi (SAD §20; runtime kuyruğu hariç) -------------------------------
# STT final + orchestrator/policy + LLM first-token + TTS first-byte toplamı. 0.3.2 green-baseline'a
# kalibre (~tipik tur). Profil override edebilir ama runtime adayları arasında AYNIDIR (dil-bağımsız).
DEFAULT_REST_OF_CHAIN_MS = {"p50": 560.0, "p95": 980.0}
# Barge-in algılama+kesme komut kalemi (dil-bağımsız edge VAD + sinyal); runtime kuyruğu AYRICA eklenir.
DEFAULT_BARGE_IN_BASE_MS = {"p50": 120.0, "p95": 165.0}

# --- Density bileşen varsayılanları (0.3.3 ile aynı; medya YOK — ADR-009 hibrit ayrı katman) ------
# runtime_overhead ve cpu_session DİLE bağlıdır (profil override eder); diğerleri dil-bağımsız (veri).
DEFAULT_COMPONENTS_MB = {
    "session_state":    {"p50": 1.2, "p95": 1.8},
    "dialogue_memory":  {"p50": 3.2, "p95": 5.8},
    "dialogue_long":    {"p50": 6.5, "p95": 10.0},
    "prompt_context":   {"p50": 1.4, "p95": 2.0},
    "rag_context":      {"p50": 1.8, "p95": 3.2},
    "adapter_state":    {"p50": 1.4, "p95": 2.2},
    "runtime_overhead": {"p50": 0.9, "p95": 1.4},   # DİLE BAĞLI (GC heap reserve + stack)
}
DEFAULT_COMPONENTS_MCORE = {
    "cpu_session": {"p50": 9.0, "p95": 20.0},        # DİLE BAĞLI (verimlilik / bağlam-değiştirme)
}
DEFAULT_MIX = {"rag_active_share": 0.30, "long_session_share": 0.20}
DEFAULT_WORKER = {"vcpu": 8, "mem_gb": 16, "os_reserve_mb": 1024,
                  "mem_headroom_pct": 0.15, "cpu_target_util": 0.70}
DEFAULT_DECISION_SCORES = {"dev_velocity": 0.5, "ecosystem": 0.5, "safety": 0.5, "ops": 0.5}
# Runtime kuyruğu (GC STW / scheduler jitter) — DİLE BAĞLI; profil override eder.
DEFAULT_RUNTIME_TAIL_MS = {"p50": 1.0, "p95": 8.0}


# =================================================================================================
# Lognormal bileşen + percentile — 0.3.1/0.3.2/0.3.3/0.3.4 ile BİREBİR aynı
# =================================================================================================
class LogNormalComponent:
    """Sağ-çarpık kalem; median=p50, 95. percentil=p95'e kalibre lognormal. p50==p95 → sabit."""

    __slots__ = ("name", "p50", "p95", "mu", "sigma")

    def __init__(self, name: str, p50: float, p95: float) -> None:
        self.name = name
        self.p50 = float(p50)
        self.p95 = max(float(p95), float(p50))
        self.mu = math.log(self.p50) if self.p50 > 0 else 0.0
        if self.p50 > 0 and self.p95 > self.p50:
            self.sigma = (math.log(self.p95) - self.mu) / Z95
        else:
            self.sigma = 0.0

    def sample(self, rng: random.Random) -> float:
        if self.sigma == 0.0:
            return self.p50
        return math.exp(self.mu + self.sigma * rng.gauss(0.0, 1.0))


def percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _stats(vals: list[float]) -> dict:
    s = sorted(vals)
    return {
        "n": len(s),
        "p50": round(percentile(s, 50), 1),
        "p95": round(percentile(s, 95), 1),
        "p99": round(percentile(s, 99), 1),
        "mean": round(sum(s) / len(s), 1) if s else float("nan"),
        "max": round(s[-1], 1) if s else float("nan"),
    }


def _lc(d: dict, default: dict, key: str) -> LogNormalComponent:
    src = dict(default)
    src.update(d.get(key, {}))
    return LogNormalComponent(key, float(src["p50"]), float(src["p95"]))


# =================================================================================================
# Gecikme tarafı (NFR 10.1): dil-bağımsız zincir + DİLE-bağlı runtime kuyruğu (GC/scheduler)
# =================================================================================================
def measure_latency(profile: dict) -> dict:
    n = int(profile.get("samples", 20000))
    seed = int(profile.get("seed", 42))
    rng = random.Random(seed)

    rest = _lc(profile, DEFAULT_REST_OF_CHAIN_MS, "rest_of_chain_ms")
    bargein_base = _lc(profile, DEFAULT_BARGE_IN_BASE_MS, "barge_in_base_ms")
    tail = _lc(profile, DEFAULT_RUNTIME_TAIL_MS, "runtime_tail_ms")

    e2e: list[float] = []
    bi: list[float] = []
    tail_only: list[float] = []
    for _ in range(n):
        t_e = tail.sample(rng)            # bu turdaki GC/scheduler kuyruğu (e2e'ye)
        e2e.append(rest.sample(rng) + t_e)
        bi.append(bargein_base.sample(rng) + tail.sample(rng))  # barge-in kesmeye AYRI kuyruk draw'ı
        tail_only.append(t_e)

    return {"e2e": _stats(e2e), "barge_in": _stats(bi), "runtime_tail": _stats(tail_only)}


# =================================================================================================
# Density tarafı (NFR 10.2): 0.3.3 modeli — medya YOK (ADR-009 hibrit ayrı katman)
# =================================================================================================
def measure_density(profile: dict) -> dict:
    n = int(profile.get("samples", 20000))
    seed = int(profile.get("seed", 42))
    mix = dict(DEFAULT_MIX); mix.update(profile.get("mix", {}))
    worker = dict(DEFAULT_WORKER); worker.update(profile.get("worker", {}))

    mb_src = dict(DEFAULT_COMPONENTS_MB); mb_src.update(profile.get("components_mb", {}))
    mb = {k: LogNormalComponent(k, float(v["p50"]), float(v["p95"])) for k, v in mb_src.items()}
    mc_src = dict(DEFAULT_COMPONENTS_MCORE); mc_src.update(profile.get("components_mcore", {}))
    mc = {k: LogNormalComponent(k, float(v["p50"]), float(v["p95"])) for k, v in mc_src.items()}

    rng = random.Random(seed)

    mem_budget: list[float] = []     # medya YOK; runtime_overhead DİLE bağlı (15MB kapısı)
    cpu_mcore: list[float] = []
    for _ in range(n):
        session = mb["session_state"].sample(rng)
        if rng.random() < mix["long_session_share"]:
            dialogue = mb["dialogue_long"].sample(rng)
        else:
            dialogue = mb["dialogue_memory"].sample(rng)
        prompt = mb["prompt_context"].sample(rng)
        adapter = mb["adapter_state"].sample(rng)
        runtime = mb["runtime_overhead"].sample(rng)
        rag = mb["rag_context"].sample(rng) if rng.random() < mix["rag_active_share"] else 0.0
        mem_budget.append(session + dialogue + prompt + adapter + runtime + rag)
        cpu_mcore.append(mc["cpu_session"].sample(rng))

    budget_st = _stats(mem_budget)
    cpu_st = _stats(cpu_mcore)

    usable_mem_mb = (worker["mem_gb"] * 1024 - worker["os_reserve_mb"]) * (1 - worker["mem_headroom_pct"])
    cpu_budget_mcore = worker["vcpu"] * 1000 * worker["cpu_target_util"]

    def fdiv(num, den):
        return int(num // den) if den > 0 else 0

    mem_cap = fdiv(usable_mem_mb, budget_st["mean"])
    cpu_cap = fdiv(cpu_budget_mcore, cpu_st["mean"])
    density = min(mem_cap, cpu_cap)
    bottleneck = "memory" if mem_cap <= cpu_cap else "cpu"

    return {
        "mem_budget": budget_st, "cpu": cpu_st,
        "usable_mem_mb": round(usable_mem_mb, 1), "cpu_budget_mcore": round(cpu_budget_mcore, 1),
        "mem_cap": mem_cap, "cpu_cap": cpu_cap, "density": density, "bottleneck": bottleneck,
    }


# =================================================================================================
# Birleşik kapı (NFR 10.1 + NFR 10.2) — her iki HARD kapı geçerse çıkış kodu 0
# =================================================================================================
def evaluate_gates(lat: dict, den: dict) -> dict:
    checks = []

    def chk(key, ok, detail, hard=True):
        checks.append({"check": key, "pass": bool(ok), "detail": detail, "hard": hard})

    e, bi = lat["e2e"], lat["barge_in"]
    chk("e2e_p50", e["p50"] <= E2E_P50_MS, f"e2e P50 {e['p50']}ms ≤ {E2E_P50_MS:.0f}ms")
    chk("e2e_p95", e["p95"] <= E2E_P95_MS, f"e2e P95 {e['p95']}ms ≤ {E2E_P95_MS:.0f}ms")
    chk("e2e_p99", e["p99"] <= E2E_P99_MS, f"e2e P99 {e['p99']}ms ≤ {E2E_P99_MS:.0f}ms")
    chk("bargein_p95", bi["p95"] <= BARGEIN_P95_MS,
        f"barge-in kesme P95 {bi['p95']}ms ≤ {BARGEIN_P95_MS:.0f}ms (ADR-005)")
    b = den["mem_budget"]
    chk("mem_budget_p95", b["p95"] <= BUDGET_MEM_MB,
        f"oturum belleği (medya hariç) P95 {b['p95']}MB ≤ {BUDGET_MEM_MB:.0f}MB")
    chk("density_min", den["density"] >= DENSITY_MIN,
        f"density {den['density']} oturum/worker ≥ {DENSITY_MIN} (bottleneck={den['bottleneck']})")
    chk("density_target", den["density"] >= DENSITY_TARGET,
        f"density {den['density']} ≥ {DENSITY_TARGET} (stretch)", hard=False)

    hard_pass = all(c["pass"] for c in checks if c["hard"])
    return {"checks": checks, "hard_pass": hard_pass}


# =================================================================================================
# Karar skoru (ADR-003) — HARD-geçen adaylar için ağırlıklı boyut skoru [0..1]
# =================================================================================================
def decision_score(profile: dict, lat: dict, den: dict) -> dict:
    """Ölçülen boyutları [0..1]'e normalize et + nitel beyan boyutlarıyla ağırlıklı topla."""
    scores_decl = dict(DEFAULT_DECISION_SCORES)
    scores_decl.update(profile.get("decision_scores", {}))

    def clamp01(x):
        return max(0.0, min(1.0, x))

    # Ölçülen: barge-in P95 headroom (200ms'e pay) → düşük GC kuyruğu = yüksek headroom
    tail_dim = clamp01((BARGEIN_P95_MS - lat["barge_in"]["p95"]) / BARGEIN_P95_MS)
    den_dim = clamp01(den["density"] / DENSITY_TARGET)   # density / stretch hedef

    dims = {
        "latency_tail": round(tail_dim, 3), "density": round(den_dim, 3),
        "dev_velocity": round(float(scores_decl["dev_velocity"]), 3),
        "ecosystem": round(float(scores_decl["ecosystem"]), 3),
        "safety": round(float(scores_decl["safety"]), 3),
        "ops": round(float(scores_decl["ops"]), 3),
    }
    total = round(sum(DECISION_WEIGHTS[k] * dims[k] for k in DECISION_WEIGHTS), 4)
    return {"dims": dims, "weighted": total}


def measure_runtime(profile: dict) -> dict:
    lat = measure_latency(profile)
    den = measure_density(profile)
    gates = evaluate_gates(lat, den)
    score = decision_score(profile, lat, den)
    return {"name": profile.get("name", "runtime"),
            "lang": profile.get("lang", "?"),
            "samples": int(profile.get("samples", 20000)), "seed": int(profile.get("seed", 42)),
            "latency": lat, "density": den, "gates": gates, "score": score}


# =================================================================================================
# CLI
# =================================================================================================
def _print_evaluate(t: dict) -> None:
    lat, den, g, sc = t["latency"], t["density"], t["gates"], t["score"]
    e, bi, rt = lat["e2e"], lat["barge_in"], lat["runtime_tail"]
    print(f"# Hot-path runtime — aday='{t['name']}' (dil={t['lang']})  (N={t['samples']}, seed={t['seed']})")

    print("\n## Gecikme (NFR 10.1 / SAD §20) — end-of-utterance → ilk ses (ms)")
    print(f"  e2e:            P50={e['p50']}  P95={e['p95']}  P99={e['p99']}  mean={e['mean']}")
    print(f"  barge-in kesme: P50={bi['p50']}  P95={bi['p95']}  (ADR-005; ≤200ms kapısı)")
    print(f"  runtime kuyruğu (GC/scheduler): P50={rt['p50']}  P95={rt['p95']}  (dile bağlı; ~0=GC'siz)")

    print("\n## Density (NFR 10.2 / SAD §15.2) — medya ADR-009 hibrit ayrı katman")
    b = den["mem_budget"]
    print(f"  oturum belleği (medya HARİÇ): P95={b['p95']}MB  (15MB bütçe kapısı; runtime_overhead dile bağlı)")
    print(f"  density {den['density']} oturum/worker (bottleneck={den['bottleneck']}, "
          f"mem-cap={den['mem_cap']} cpu-cap={den['cpu_cap']})")

    print("\n## Birleşik kapı (NFR 10.1 + NFR 10.2; HARD = çıkış kodu)")
    for c in g["checks"]:
        mark = "✅" if c["pass"] else "❌"
        tag = "" if c["hard"] else "  (yumuşak/stretch)"
        print(f"  {mark} {c['check']:<16} {c['detail']}{tag}")

    print("\n## Karar boyutları (ADR-003; ölçülen + beyan)")
    for k, w in DECISION_WEIGHTS.items():
        print(f"  {k:<13} skor={sc['dims'][k]:<6} × ağırlık={w}")
    print(f"  → ağırlıklı karar skoru: {sc['weighted']}")

    verdict = "🟢 GEÇTİ" if g["hard_pass"] else "🔴 KALDI"
    print(f"\n## VERDICT: {verdict}  (NFR 10.1 + NFR 10.2 birleşik kapı "
          f"{'karşılandı' if g['hard_pass'] else 'KARŞILANMADI'})")


def cmd_evaluate(args) -> int:
    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)
    if args.samples:
        profile["samples"] = args.samples
    if args.seed is not None:
        profile["seed"] = args.seed
    t = measure_runtime(profile)
    _print_evaluate(t)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False, indent=2)
        print(f"\n(JSON yazıldı: {args.json_out})")
    return 0 if t["gates"]["hard_pass"] else 1


def cmd_compare(args) -> int:
    print("# Hot-path runtime karşılaştırma — Go vs Rust (ADR-003)\n")
    rows = []
    for path in args.profiles:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        if args.samples:
            profile["samples"] = args.samples
        rows.append(measure_runtime(profile))

    print(f"  {'aday':<22}{'dil':>8}{'e2e.P95':>9}{'barge.P95':>11}"
          f"{'density':>9}{'karar':>8}  verdict")
    for t in rows:
        g, sc = t["gates"], t["score"]
        verdict = "🟢" if g["hard_pass"] else "🔴"
        print(f"  {t['name']:<22}{t['lang']:>8}{t['latency']['e2e']['p95']:>9.0f}"
              f"{t['latency']['barge_in']['p95']:>11.0f}{t['density']['density']:>9}"
              f"{sc['weighted']:>8.3f}  {verdict}")

    passing = [t for t in rows if t["gates"]["hard_pass"]]
    print(f"\n  Kapı: NFR 10.1 (e2e P95≤{E2E_P95_MS:.0f}ms, barge-in P95≤{BARGEIN_P95_MS:.0f}ms) "
          f"+ NFR 10.2 (bellek P95≤{BUDGET_MEM_MB:.0f}MB, density≥{DENSITY_MIN})")
    if not passing:
        print("\n  ⚠️  ADR-003 ÖNERİSİ: hiçbir runtime her iki HARD kapıyı geçmiyor → karar verilemez.")
        return 1
    winner = max(passing, key=lambda t: t["score"]["weighted"])
    print(f"\n  ✅ ADR-003 ÖNERİSİ: **{winner['name']}** ({winner['lang']}) — "
          f"HARD-geçen {len(passing)} aday içinde en yüksek karar skoru ({winner['score']['weighted']}).")
    for t in sorted(passing, key=lambda x: -x["score"]["weighted"]):
        print(f"     - {t['name']:<22} karar skoru {t['score']['weighted']}")
    rejected = [t for t in rows if not t["gates"]["hard_pass"]]
    for t in rejected:
        fails = [c["check"] for c in t["gates"]["checks"] if c["hard"] and not c["pass"]]
        print(f"     ✗ {t['name']:<22} elendi → {', '.join(fails)}  (ADR-003 ret gerekçesi)")
    return 0


def cmd_schema(_args) -> int:
    print(__doc__)
    print("\nProfil JSON şeması — samples/runtime-*.json:")
    print(json.dumps({
        "name": "runtime-go", "lang": "go", "samples": 20000, "seed": 42,
        "rest_of_chain_ms": DEFAULT_REST_OF_CHAIN_MS,
        "barge_in_base_ms": DEFAULT_BARGE_IN_BASE_MS,
        "runtime_tail_ms": {"p50": 1.0, "p95": 8.0},
        "components_mb": {"runtime_overhead": {"p50": 1.2, "p95": 2.0}},
        "components_mcore": {"cpu_session": {"p50": 9.0, "p95": 20.0}},
        "mix": DEFAULT_MIX, "worker": DEFAULT_WORKER,
        "decision_scores": {"dev_velocity": 0.90, "ecosystem": 0.85, "safety": 0.65, "ops": 0.85},
    }, ensure_ascii=False, indent=2))
    print(f"\nKarar ağırlıkları (ADR-003): {json.dumps(DECISION_WEIGHTS, ensure_ascii=False)}")
    return 0


# --- selftest ------------------------------------------------------------------------------------
def _go() -> dict:
    # Go: goroutine async; küçük GC STW kuyruğu; ılımlı runtime bellek overhead'i.
    return {"name": "self-go", "lang": "go", "samples": 20000, "seed": 7,
            "runtime_tail_ms": {"p50": 1.0, "p95": 8.0},
            "components_mb": {"runtime_overhead": {"p50": 1.2, "p95": 2.0}},
            "components_mcore": {"cpu_session": {"p50": 9.0, "p95": 20.0}},
            "decision_scores": {"dev_velocity": 0.90, "ecosystem": 0.85, "safety": 0.65, "ops": 0.85}}


def _rust() -> dict:
    # Rust: tokio async; GC YOK (deterministik kuyruk ~0); en düşük runtime bellek overhead'i.
    return {"name": "self-rust", "lang": "rust", "samples": 20000, "seed": 7,
            "runtime_tail_ms": {"p50": 0.3, "p95": 1.5},
            "components_mb": {"runtime_overhead": {"p50": 0.6, "p95": 1.0}},
            "components_mcore": {"cpu_session": {"p50": 8.0, "p95": 17.0}},
            "decision_scores": {"dev_velocity": 0.55, "ecosystem": 0.65, "safety": 0.95, "ops": 0.65}}


def _managed_gc() -> dict:
    # GC-ağır/thread-per-call baseline (ADR-003 ret seçeneği 1/2): büyük STW kuyruğu + yüksek
    # runtime bellek overhead'i (GC heap reserve + thread stack) + thread bağlam-değiştirme CPU'su.
    return {"name": "self-managed-gc", "lang": "jvm/thread", "samples": 20000, "seed": 7,
            "runtime_tail_ms": {"p50": 8.0, "p95": 85.0},
            "barge_in_base_ms": {"p50": 150.0, "p95": 185.0},
            "components_mb": {"runtime_overhead": {"p50": 6.0, "p95": 12.0}},
            "components_mcore": {"cpu_session": {"p50": 22.0, "p95": 48.0}},
            "decision_scores": {"dev_velocity": 0.85, "ecosystem": 0.80, "safety": 0.60, "ops": 0.70}}


def cmd_selftest(_args) -> int:
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("## selftest — hot-path runtime invariant'ları (credential'sız, deterministik)\n")

    # S1: Lognormal kalibrasyonu (0.3.2/0.3.3/0.3.4 ile aynı)
    c = LogNormalComponent("t", 50.0, 80.0)
    _rng = random.Random(1)
    xs = sorted(c.sample(_rng) for _ in range(50000))
    check(f"S1 lognormal median≈50 ({percentile(xs, 50):.1f})", abs(percentile(xs, 50) - 50) < 1.5)
    check(f"S1 lognormal p95≈80 ({percentile(xs, 95):.1f})", abs(percentile(xs, 95) - 80) < 2.5)

    go = measure_runtime(_go())
    ru = measure_runtime(_rust())
    mg = measure_runtime(_managed_gc())

    # S2/S3: Go ve Rust → her iki HARD kapı geçer
    check("S2 go hard_pass", go["gates"]["hard_pass"])
    check("S3 rust hard_pass", ru["gates"]["hard_pass"])

    # S4: GC-ağır/thread-per-call baseline → HARD kapı KALDI (ADR-003 ret gerekçesi)
    check("S4 managed-gc hard KALDI", not mg["gates"]["hard_pass"])
    mg_fails = {c["check"] for c in mg["gates"]["checks"] if c["hard"] and not c["pass"]}
    check(f"S4 managed-gc barge-in eler (P95={mg['latency']['barge_in']['p95']:.0f}>200)",
          "bargein_p95" in mg_fails)
    check(f"S4 managed-gc 15MB bütçe eler (P95={mg['density']['mem_budget']['p95']:.1f}>15)",
          "mem_budget_p95" in mg_fails)
    check(f"S4 managed-gc density eler ({mg['density']['density']}<250)", "density_min" in mg_fails)

    # S5: runtime kuyruğu monotonluğu (Rust < Go < managed-gc) — GC'siz deterministik
    check(f"S5 runtime kuyruğu rust<go<managed-gc "
          f"({ru['latency']['runtime_tail']['p95']:.1f}<{go['latency']['runtime_tail']['p95']:.1f}"
          f"<{mg['latency']['runtime_tail']['p95']:.1f})",
          ru["latency"]["runtime_tail"]["p95"] < go["latency"]["runtime_tail"]["p95"]
          < mg["latency"]["runtime_tail"]["p95"])

    # S6: barge-in kuyruğu — Rust ≤ Go (GC'siz daha sıkı kuyruk)
    check(f"S6 barge-in rust≤go ({ru['latency']['barge_in']['p95']:.0f}≤{go['latency']['barge_in']['p95']:.0f})",
          ru["latency"]["barge_in"]["p95"] <= go["latency"]["barge_in"]["p95"])

    # S7: density — Rust ≥ Go (düşük ayak izi) > managed-gc
    check(f"S7 density rust≥go>managed-gc ({ru['density']['density']}≥{go['density']['density']}"
          f">{mg['density']['density']})",
          ru["density"]["density"] >= go["density"]["density"] > mg["density"]["density"])

    # S8: oturum belleği — Rust < Go < managed-gc (runtime_overhead dile bağlı)
    check(f"S8 bütçe P95 rust<go<managed-gc "
          f"({ru['density']['mem_budget']['p95']:.1f}<{go['density']['mem_budget']['p95']:.1f}"
          f"<{mg['density']['mem_budget']['p95']:.1f})",
          ru["density"]["mem_budget"]["p95"] < go["density"]["mem_budget"]["p95"]
          < mg["density"]["mem_budget"]["p95"])

    # S9: ADR-003 önerisi → Go (HARD-geçen Go+Rust içinde en yüksek karar skoru)
    passing = [t for t in (go, ru, mg) if t["gates"]["hard_pass"]]
    winner = max(passing, key=lambda t: t["score"]["weighted"])
    check(f"S9 öneri=go (skor {winner['score']['weighted']})", winner["name"] == "self-go")
    check(f"S9 go karar skoru > rust ({go['score']['weighted']}>{ru['score']['weighted']})",
          go["score"]["weighted"] > ru["score"]["weighted"])

    # S10: Determinizm — aynı profil iki kez → birebir aynı
    check("S10 determinizm (gecikme+density birebir)",
          measure_runtime(_go())["latency"] == go["latency"] and
          measure_runtime(_go())["density"] == go["density"])

    # S11: Karar skoru sınırları [0..1] ve ağırlık toplamı 1.0
    check("S11 ağırlık toplamı=1.0", abs(sum(DECISION_WEIGHTS.values()) - 1.0) < 1e-9)
    check("S11 karar skoru [0..1]", all(0.0 <= t["score"]["weighted"] <= 1.0 for t in (go, ru, mg)))

    # S12: Percentile sıralaması P50≤P95≤P99 (e2e)
    check("S12 e2e P50≤P95≤P99",
          go["latency"]["e2e"]["p50"] <= go["latency"]["e2e"]["p95"] <= go["latency"]["e2e"]["p99"])

    # S13: rest_of_chain dil-bağımsız — Go/Rust e2e farkı yalnız runtime kuyruğundan (küçük)
    check(f"S13 e2e farkı küçük (|go-rust|={abs(go['latency']['e2e']['p95']-ru['latency']['e2e']['p95']):.0f}ms<30ms)",
          abs(go["latency"]["e2e"]["p95"] - ru["latency"]["e2e"]["p95"]) < 30.0)

    print(f"\n{'='*60}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print(f"SELFTEST GEÇTİ — {13} grup invariant doğrulandı")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Hot-path dil doğrulaması: Go vs Rust (WBS 0.3.5, →ADR-003)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("evaluate", help="Bir runtime profilini ölç → gecikme+density+kapı")
    pe.add_argument("--profile", required=True, help="samples/runtime-*.json")
    pe.add_argument("--samples", type=int, help="örnek sayısı override")
    pe.add_argument("--seed", type=int, help="determinizm tohumu override")
    pe.add_argument("--json-out", help="ölçüm+kapı JSON çıktısı")
    pe.set_defaults(func=cmd_evaluate)

    pc = sub.add_parser("compare", help="Runtime adaylarını karşılaştır + ADR-003 önerisi")
    pc.add_argument("profiles", nargs="+", help="samples/runtime-*.json ...")
    pc.add_argument("--samples", type=int, help="örnek sayısı override")
    pc.set_defaults(func=cmd_compare)

    ps = sub.add_parser("selftest", help="Kapı/karar/determinizm invariant'ları (credential'sız)")
    ps.set_defaults(func=cmd_selftest)

    psc = sub.add_parser("schema", help="Profil JSON şemasını + karar ağırlıklarını yaz")
    psc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
