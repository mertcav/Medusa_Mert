#!/usr/bin/env python3
"""media_placement_probe.py — Medya işleme konumu deneyi: edge vs merkez (WBS 0.3.4, →ADR-009).

Amaç: 0.3.2 (gecikme, NFR 10.1) ve 0.3.3 (density, NFR 10.2) HARD kapılarını **tek bir karar
deneyinde** birleştirip, RTP/medya sonlandırma + codec + VAD/endpointing + barge-in algılamanın
**edge'de mi yoksa merkezde mi** yapılacağı sorusunu (ADR-009 — AÇIK karar) ölçüm temelli kapatmak.
Bu probe vendor/dil **seçmez**; topoloji adaylarını NFR 10.1 + NFR 10.2 kapılarına karşı ölçer ve
HARD-geçen adaylar arasında ağırlıklı karar matrisiyle bir **öneri** üretir → ADR-009 kararı.

Karar problemi (SAD §6.4/§23, BRD §10.2 notu):
  Medya işleme konumu, gecikme (NFR 10.1) ile density (NFR 10.2) arasında doğrudan ödünleşimdir.
  - **edge:** medya bölgesel POP'ta (çağrı girişine yakın) sonlandırılır → düşük medya/ağ gecikmesi,
    edge VAD ile hızlı barge-in; ama dağıtık medya katmanı (operasyonel karmaşıklık + maliyet).
  - **merkez (central):** tüm medya merkezi bölgede işlenir → basit operasyon; ama WAN gidiş-dönüşü
    medya/ağ gecikmesini ve **barge-in kesme** sinyalini büyütür (≤200ms kapısını riske atar).
  - **hibrit:** gecikmeye-duyarlı hafif iş (VAD/endpointing/barge-in algılama) edge'de (ADR-005),
    ağır/durumlu medya (transcode, kayıt tap, ağır gürültü/echo) ayrı bölgesel medya-gateway
    katmanında — orkestratör worker'ına **eş-konumlu DEĞİL** → density korunur. ADR-005 ile uyumlu.

Metrik tanımı (yetkili kapılar):
  GECIKME (NFR 10.1 / SAD §20): end-of-utterance → ilk agent sesi. Topolojiye göre **yalnız**
    medya/ağ kalemi (SAD §20 ~50–100ms) ve **barge-in kesme** kalemi değişir; zincirin geri kalanı
    (endpointing kararı + STT final + orchestrator + LLM first-token + TTS first-byte) topolojiden
    bağımsızdır → bu probe onu tek bir `rest_of_chain` dağılımıyla modeller (0.3.2 ile tutarlı).
  DENSITY (NFR 10.2 / SAD §15.2): oturum-başı orkestratör belleği (**medya hariç**) ≤ 15 MB ve
    referans worker (8 vCPU/16 GB) başına density ≥ 250–500. Medya orkestratör worker'ında
    **eş-konumlu** ise density'ye CPU/bellek overhead'i eklenir (ama 15 MB BÜTÇE kapısına EKLENMEZ —
    medya hariç; 0.3.3 S11 invariant'ı). Topoloji `media_colocated` bayrağıyla bu duyarlılığı belirler.

Tasarım ilkeleri (CLAUDE.md + 0.2.x/0.3.x hattıyla aynı disiplin):
- **Vendor/dil-nötr (ADR-002/003):** Bileşen dağılımları SAD §20/§15 + ADR-003/005 hedeflerinden
  türetilmiş **mühendislik profilleridir** (`samples/media-*.json`); sağlayıcı seçmez. Canlı PoC'ta
  (0.3.5 + telemetri) aynı profil yapısı gerçek ölçümle doldurulur; kapı/karar mantığı değişmez.
- **stdlib-only / deterministik:** Harici bağımlılık yok; örnekleme tohumlu `random.Random(seed)`
  (latency_budget_probe.py / density_probe.py disiplini). `LogNormalComponent` + `percentile`
  0.3.1/0.3.2/0.3.3 ile **birebir aynı**.
- **Karar ≠ ölçüm uydurma:** Ölçülen boyutlar (gecikme/barge-in/density) simülasyondan; nitel boyutlar
  (operasyonel karmaşıklık/maliyet/residency) profilde **beyan edilir** (0.2.x rubrik soft-ölçüt
  disiplini). Öneri = HARD-geçen adaylar arasında ağırlıklı skorun en yükseği.

Modlar:
  evaluate  — Bir topoloji profilini (samples/media-*.json) ölç → gecikme P50/P95/P99 + barge-in +
              density + NFR 10.1/10.2 kapı verdict'i (çıkış kodu: 0=her iki HARD kapı geçti, 1=kaldı).
  compare   — Topolojileri tablo + karar matrisi halinde karşılaştır → ADR-009 ÖNERİSİ (çıkış kodu:
              0=geçer aday var ve öneri üretildi, 1=hiçbir aday her iki kapıyı geçmiyor).
  selftest  — Dahili deterministik topolojilerle kapı/karar/determinizm invariant'ları (CI).
  schema    — Profil JSON şemasını ve karar ağırlıklarını yazar.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys

# --- NFR 10.1 gecikme kapıları (yetkili; 0.3.2 ile aynı) -----------------------------------------
E2E_P50_MS = 700.0      # end-of-utterance → ilk agent sesi P50 ≤ 700 ms
E2E_P95_MS = 1200.0     # P95 ≤ 1200 ms
E2E_P99_MS = 2000.0     # P99 ≤ 2000 ms
BARGEIN_P95_MS = 200.0  # barge-in sonrası TTS kesme P95 ≤ 200 ms (FR-RTC-002, ADR-005)

# --- NFR 10.2 density kapıları (yetkili; 0.3.3 ile aynı) -----------------------------------------
BUDGET_MEM_MB = 15.0    # oturum-başı orkestratör belleği (medya hariç) P95 ≤ 15 MB (FR-RES-016)
DENSITY_MIN = 250       # worker başına eş zamanlı oturum ≥ 250 (HARD)
DENSITY_TARGET = 500    # ≥ 500 stretch hedef (YUMUŞAK)

Z95 = 1.6448536269514722

# --- Karar matrisi ağırlıkları (ADR-009; toplam = 1.0) -------------------------------------------
# Ölçülen boyutlar (latency/bargein/density) + nitel boyutlar (ops/cost/residency).
DECISION_WEIGHTS = {
    "latency":   0.20,   # e2e P95 headroom (ölçülen)
    "bargein":   0.15,   # barge-in P95 headroom (ölçülen) — ADR-005 kritik
    "density":   0.20,   # worker density (ölçülen)
    "ops":       0.20,   # operasyonel basitlik (beyan; edge dağıtık → düşük)
    "cost":      0.10,   # altyapı maliyeti (beyan)
    "residency": 0.15,   # veri-yerleşim/residency esnekliği (beyan; NFR 10.7)
}

# --- Topolojiden BAĞIMSIZ zincir kalemi (SAD §20; medya/barge-in hariç) ---------------------------
# endpointing kararı + STT final + orchestrator/policy + LLM first-token + TTS first-byte toplamı.
# Profil override edebilir; varsayılan 0.3.2 green-baseline'a kalibre (~tipik tur).
DEFAULT_REST_OF_CHAIN_MS = {"p50": 560.0, "p95": 980.0}

# --- Density bileşen varsayılanları (0.3.3 ile aynı lean-runtime hedefi) --------------------------
DEFAULT_COMPONENTS_MB = {
    "session_state":    {"p50": 1.2, "p95": 1.8},
    "dialogue_memory":  {"p50": 3.2, "p95": 5.8},
    "dialogue_long":    {"p50": 6.5, "p95": 10.0},
    "prompt_context":   {"p50": 1.4, "p95": 2.0},
    "rag_context":      {"p50": 1.8, "p95": 3.2},
    "adapter_state":    {"p50": 1.4, "p95": 2.2},
    "runtime_overhead": {"p50": 0.9, "p95": 1.4},
    "media_colocated":  {"p50": 7.0, "p95": 10.0},
}
DEFAULT_COMPONENTS_MCORE = {
    "cpu_session": {"p50": 9.0, "p95": 20.0},
    "cpu_media":   {"p50": 5.0, "p95": 11.0},
}
DEFAULT_MIX = {"rag_active_share": 0.30, "long_session_share": 0.20}
DEFAULT_WORKER = {"vcpu": 8, "mem_gb": 16, "os_reserve_mb": 1024,
                  "mem_headroom_pct": 0.15, "cpu_target_util": 0.70}
DEFAULT_DECISION_SCORES = {"ops": 0.5, "cost": 0.5, "residency": 0.5}


# =================================================================================================
# Lognormal bileşen + percentile — 0.3.1/0.3.2/0.3.3 ile BİREBİR aynı
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


# =================================================================================================
# Gecikme tarafı (NFR 10.1): topolojiye-bağlı medya/ağ + barge-in; topolojiden-bağımsız zincir
# =================================================================================================
def _lc(d: dict, default: dict, key: str) -> LogNormalComponent:
    src = dict(default)
    src.update(d.get(key, {}))
    return LogNormalComponent(key, float(src["p50"]), float(src["p95"]))


def measure_latency(profile: dict) -> dict:
    n = int(profile.get("samples", 20000))
    seed = int(profile.get("seed", 42))
    rng = random.Random(seed)

    rest = _lc(profile, DEFAULT_REST_OF_CHAIN_MS, "rest_of_chain_ms")
    media = LogNormalComponent("media_network_ms",
                               float(profile["media_network_ms"]["p50"]),
                               float(profile["media_network_ms"]["p95"]))
    bargein = LogNormalComponent("barge_in_ms",
                                 float(profile["barge_in_ms"]["p50"]),
                                 float(profile["barge_in_ms"]["p95"]))

    e2e: list[float] = []
    media_only: list[float] = []
    bi: list[float] = []
    for _ in range(n):
        m = media.sample(rng)
        e2e.append(rest.sample(rng) + m)   # zincir + medya/ağ kalemi (SAD §20)
        media_only.append(m)
        bi.append(bargein.sample(rng))     # barge-in kesme (ayrı tur olayı)

    return {"e2e": _stats(e2e), "media_network": _stats(media_only), "barge_in": _stats(bi)}


# =================================================================================================
# Density tarafı (NFR 10.2): 0.3.3 ile aynı model — medya eş-konumu topoloji bayrağı
# =================================================================================================
def measure_density(profile: dict) -> dict:
    n = int(profile.get("samples", 20000))
    seed = int(profile.get("seed", 42))
    mix = dict(DEFAULT_MIX); mix.update(profile.get("mix", {}))
    worker = dict(DEFAULT_WORKER); worker.update(profile.get("worker", {}))
    colocated = bool(profile.get("media_colocated", False))

    mb_src = dict(DEFAULT_COMPONENTS_MB); mb_src.update(profile.get("components_mb", {}))
    mb = {k: LogNormalComponent(k, float(v["p50"]), float(v["p95"])) for k, v in mb_src.items()}
    mc_src = dict(DEFAULT_COMPONENTS_MCORE); mc_src.update(profile.get("components_mcore", {}))
    mc = {k: LogNormalComponent(k, float(v["p50"]), float(v["p95"])) for k, v in mc_src.items()}

    rng = random.Random(seed)
    rng_media = random.Random(seed + 7)   # medya AYRI stream → 15MB bütçe medya-konumundan bağımsız

    mem_budget: list[float] = []     # medya HARİÇ (15MB kapısı)
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
        budget = session + dialogue + prompt + adapter + runtime + rag
        mem_budget.append(budget)

        cpu = mc["cpu_session"].sample(rng)
        if colocated:
            cpu += mc["cpu_media"].sample(rng_media)   # eş-konumlu medya CPU → density'ye, bütçeye DEĞİL
        cpu_mcore.append(cpu)

    budget_st = _stats(mem_budget)
    cpu_st = _stats(cpu_mcore)

    usable_mem_mb = (worker["mem_gb"] * 1024 - worker["os_reserve_mb"]) * (1 - worker["mem_headroom_pct"])
    cpu_budget_mcore = worker["vcpu"] * 1000 * worker["cpu_target_util"]

    def fdiv(num, den):
        return int(num // den) if den > 0 else 0

    # Eş-konumlu medya BÜTÇE-hariç bellek overhead'i yalnız density bellek-kapasitesine eklenir
    # (15MB bütçe kapısına DEĞİL — medya hariç). Ayrı-katman (edge/hybrid) topolojide eklenmez.
    dens_mem_mean = budget_st["mean"]
    if colocated:
        dens_mem_mean += float(mb["media_colocated"].p50)
    mem_cap = fdiv(usable_mem_mb, dens_mem_mean)
    cpu_cap = fdiv(cpu_budget_mcore, cpu_st["mean"])
    density = min(mem_cap, cpu_cap)
    bottleneck = "memory" if mem_cap <= cpu_cap else "cpu"

    return {
        "mem_budget": budget_st, "cpu": cpu_st, "colocated": colocated,
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
    # NFR 10.1 (gecikme)
    chk("e2e_p50", e["p50"] <= E2E_P50_MS, f"e2e P50 {e['p50']}ms ≤ {E2E_P50_MS:.0f}ms")
    chk("e2e_p95", e["p95"] <= E2E_P95_MS, f"e2e P95 {e['p95']}ms ≤ {E2E_P95_MS:.0f}ms")
    chk("e2e_p99", e["p99"] <= E2E_P99_MS, f"e2e P99 {e['p99']}ms ≤ {E2E_P99_MS:.0f}ms")
    chk("bargein_p95", bi["p95"] <= BARGEIN_P95_MS,
        f"barge-in kesme P95 {bi['p95']}ms ≤ {BARGEIN_P95_MS:.0f}ms (ADR-005)")
    # NFR 10.2 (density)
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
# Karar skoru (ADR-009) — HARD-geçen adaylar için ağırlıklı boyut skoru [0..1]
# =================================================================================================
def decision_score(profile: dict, lat: dict, den: dict) -> dict:
    """Ölçülen boyutları [0..1]'e normalize et + nitel beyan boyutlarıyla ağırlıklı topla."""
    scores_decl = dict(DEFAULT_DECISION_SCORES)
    scores_decl.update(profile.get("decision_scores", {}))

    # Ölçülen boyutlar → headroom oranı [0..1] (clamp)
    def clamp01(x):
        return max(0.0, min(1.0, x))

    lat_dim = clamp01((E2E_P95_MS - lat["e2e"]["p95"]) / E2E_P95_MS)          # e2e P95 headroom payı
    bi_dim = clamp01((BARGEIN_P95_MS - lat["barge_in"]["p95"]) / BARGEIN_P95_MS)  # barge-in headroom
    den_dim = clamp01(den["density"] / DENSITY_TARGET)                         # density / stretch hedef

    dims = {
        "latency": round(lat_dim, 3), "bargein": round(bi_dim, 3), "density": round(den_dim, 3),
        "ops": round(float(scores_decl["ops"]), 3),
        "cost": round(float(scores_decl["cost"]), 3),
        "residency": round(float(scores_decl["residency"]), 3),
    }
    total = round(sum(DECISION_WEIGHTS[k] * dims[k] for k in DECISION_WEIGHTS), 4)
    return {"dims": dims, "weighted": total}


def measure_topology(profile: dict) -> dict:
    lat = measure_latency(profile)
    den = measure_density(profile)
    gates = evaluate_gates(lat, den)
    score = decision_score(profile, lat, den)
    return {"name": profile.get("name", "topology"),
            "placement": profile.get("placement", "?"),
            "samples": int(profile.get("samples", 20000)), "seed": int(profile.get("seed", 42)),
            "latency": lat, "density": den, "gates": gates, "score": score}


# =================================================================================================
# CLI
# =================================================================================================
def _print_evaluate(t: dict) -> None:
    lat, den, g, sc = t["latency"], t["density"], t["gates"], t["score"]
    e, mn, bi = lat["e2e"], lat["media_network"], lat["barge_in"]
    print(f"# Medya konumu — topoloji='{t['name']}' ({t['placement']})  "
          f"(N={t['samples']}, seed={t['seed']})")

    print("\n## Gecikme (NFR 10.1 / SAD §20) — end-of-utterance → ilk ses (ms)")
    print(f"  e2e:           P50={e['p50']}  P95={e['p95']}  P99={e['p99']}  mean={e['mean']}")
    print(f"  medya/ağ kalemi: P50={mn['p50']}  P95={mn['p95']}  (topolojiye-bağlı; SAD §20 ~50–100ms)")
    print(f"  barge-in kesme:  P50={bi['p50']}  P95={bi['p95']}  (ADR-005; ≤200ms kapısı)")

    print("\n## Density (NFR 10.2 / SAD §15.2)")
    b = den["mem_budget"]
    print(f"  oturum belleği (medya HARİÇ): P95={b['p95']}MB  (15MB bütçe kapısı)")
    print(f"  medya eş-konumlu: {'EVET' if den['colocated'] else 'hayır'}  "
          f"→ density {den['density']} oturum/worker (bottleneck={den['bottleneck']}, "
          f"mem-cap={den['mem_cap']} cpu-cap={den['cpu_cap']})")

    print("\n## Birleşik kapı (NFR 10.1 + NFR 10.2; HARD = çıkış kodu)")
    for c in g["checks"]:
        mark = "✅" if c["pass"] else "❌"
        tag = "" if c["hard"] else "  (yumuşak/stretch)"
        print(f"  {mark} {c['check']:<16} {c['detail']}{tag}")

    print("\n## Karar boyutları (ADR-009; ölçülen + beyan)")
    for k, w in DECISION_WEIGHTS.items():
        print(f"  {k:<10} skor={sc['dims'][k]:<6} × ağırlık={w}")
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
    t = measure_topology(profile)
    _print_evaluate(t)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False, indent=2)
        print(f"\n(JSON yazıldı: {args.json_out})")
    return 0 if t["gates"]["hard_pass"] else 1


def cmd_compare(args) -> int:
    print("# Medya konumu karşılaştırma — edge vs merkez (ADR-009)\n")
    rows = []
    for path in args.profiles:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        if args.samples:
            profile["samples"] = args.samples
        rows.append(measure_topology(profile))

    print(f"  {'topoloji':<22}{'place':>9}{'e2e.P95':>9}{'barge.P95':>11}"
          f"{'density':>9}{'karar':>8}  verdict")
    for t in rows:
        g, sc = t["gates"], t["score"]
        verdict = "🟢" if g["hard_pass"] else "🔴"
        print(f"  {t['name']:<22}{t['placement']:>9}{t['latency']['e2e']['p95']:>9.0f}"
              f"{t['latency']['barge_in']['p95']:>11.0f}{t['density']['density']:>9}"
              f"{sc['weighted']:>8.3f}  {verdict}")

    # ADR-009 önerisi: HARD-geçen adaylar arasında en yüksek karar skoru
    passing = [t for t in rows if t["gates"]["hard_pass"]]
    print(f"\n  Kapı: NFR 10.1 (e2e P95≤{E2E_P95_MS:.0f}ms, barge-in P95≤{BARGEIN_P95_MS:.0f}ms) "
          f"+ NFR 10.2 (bellek P95≤{BUDGET_MEM_MB:.0f}MB, density≥{DENSITY_MIN})")
    if not passing:
        print("\n  ⚠️  ADR-009 ÖNERİSİ: hiçbir topoloji her iki HARD kapıyı geçmiyor → karar verilemez.")
        return 1
    winner = max(passing, key=lambda t: t["score"]["weighted"])
    print(f"\n  ✅ ADR-009 ÖNERİSİ: **{winner['name']}** ({winner['placement']}) — "
          f"HARD-geçen {len(passing)} aday içinde en yüksek karar skoru ({winner['score']['weighted']}).")
    for t in sorted(passing, key=lambda x: -x["score"]["weighted"]):
        print(f"     - {t['name']:<22} karar skoru {t['score']['weighted']}")
    rejected = [t for t in rows if not t["gates"]["hard_pass"]]
    for t in rejected:
        fails = [c["check"] for c in t["gates"]["checks"] if c["hard"] and not c["pass"]]
        print(f"     ✗ {t['name']:<22} elendi → {', '.join(fails)}")
    return 0


def cmd_schema(_args) -> int:
    print(__doc__)
    print("\nProfil JSON şeması — samples/media-*.json:")
    print(json.dumps({
        "name": "media-hybrid", "placement": "hybrid", "samples": 20000, "seed": 42,
        "media_colocated": False,
        "rest_of_chain_ms": DEFAULT_REST_OF_CHAIN_MS,
        "media_network_ms": {"p50": 50.0, "p95": 80.0},
        "barge_in_ms": {"p50": 115.0, "p95": 165.0},
        "mix": DEFAULT_MIX, "worker": DEFAULT_WORKER,
        "decision_scores": {"ops": 0.75, "cost": 0.78, "residency": 0.85},
    }, ensure_ascii=False, indent=2))
    print(f"\nKarar ağırlıkları (ADR-009): {json.dumps(DECISION_WEIGHTS, ensure_ascii=False)}")
    return 0


# --- selftest ------------------------------------------------------------------------------------
def _edge() -> dict:
    return {"name": "self-edge", "placement": "edge", "samples": 20000, "seed": 7,
            "media_colocated": False,
            "media_network_ms": {"p50": 35.0, "p95": 55.0},
            "barge_in_ms": {"p50": 115.0, "p95": 165.0},
            "decision_scores": {"ops": 0.45, "cost": 0.50, "residency": 0.60}}


def _central() -> dict:
    # Tüm medya merkezde + orkestratör worker'ına eş-konumlu → WAN barge-in + density düşüşü
    return {"name": "self-central", "placement": "central", "samples": 20000, "seed": 7,
            "media_colocated": True,
            "media_network_ms": {"p50": 95.0, "p95": 130.0},
            "barge_in_ms": {"p50": 195.0, "p95": 265.0},
            "decision_scores": {"ops": 0.95, "cost": 0.95, "residency": 0.70}}


def _hybrid() -> dict:
    # Edge VAD/barge-in (ADR-005) + ayrı bölgesel medya katmanı (eş-konumlu DEĞİL)
    return {"name": "self-hybrid", "placement": "hybrid", "samples": 20000, "seed": 7,
            "media_colocated": False,
            "media_network_ms": {"p50": 50.0, "p95": 80.0},
            "barge_in_ms": {"p50": 120.0, "p95": 170.0},
            "decision_scores": {"ops": 0.75, "cost": 0.78, "residency": 0.85}}


def cmd_selftest(_args) -> int:
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("## selftest — medya konumu invariant'ları (credential'sız, deterministik)\n")

    # S1: Lognormal kalibrasyonu (0.3.2/0.3.3 ile aynı)
    c = LogNormalComponent("t", 50.0, 80.0)
    _rng = random.Random(1)
    xs = sorted(c.sample(_rng) for _ in range(50000))
    check(f"S1 lognormal median≈50 ({percentile(xs, 50):.1f})", abs(percentile(xs, 50) - 50) < 1.5)
    check(f"S1 lognormal p95≈80 ({percentile(xs, 95):.1f})", abs(percentile(xs, 95) - 80) < 2.5)

    e = measure_topology(_edge())
    cen = measure_topology(_central())
    h = measure_topology(_hybrid())

    # S2: edge → her iki HARD kapı geçer
    check("S2 edge hard_pass", e["gates"]["hard_pass"])
    # S3: hybrid → her iki HARD kapı geçer
    check("S3 hybrid hard_pass", h["gates"]["hard_pass"])
    # S4: central → HARD kapı KALDI (barge-in P95 > 200)
    check("S4 central hard KALDI", not cen["gates"]["hard_pass"])
    bi_fail = next(c for c in cen["gates"]["checks"] if c["check"] == "bargein_p95")
    check(f"S4 central barge-in kapısı fail (P95={cen['latency']['barge_in']['p95']:.0f}>200)",
          not bi_fail["pass"])

    # S5: 15MB bütçe medya-konumundan BAĞIMSIZ (medya hariç invariant — 0.3.3 S11)
    check(f"S5 bütçe P95 medya-hariç (edge {e['density']['mem_budget']['p95']:.1f}"
          f" == central {cen['density']['mem_budget']['p95']:.1f})",
          e["density"]["mem_budget"]["p95"] == cen["density"]["mem_budget"]["p95"])

    # S6: eş-konumlu (central) → density < ayrı-katman (edge) [medya CPU overhead'i]
    check(f"S6 eş-konumlu density↓ (edge {e['density']['density']} > central {cen['density']['density']})",
          e["density"]["density"] > cen["density"]["density"])

    # S7: medya/ağ kalemi monotonluğu — central e2e P95 > edge e2e P95
    check(f"S7 merkez e2e↑ (edge {e['latency']['e2e']['p95']:.0f} < central "
          f"{cen['latency']['e2e']['p95']:.0f})",
          e["latency"]["e2e"]["p95"] < cen["latency"]["e2e"]["p95"])

    # S8: ADR-009 önerisi → hybrid (HARD-geçen edge+hybrid içinde en yüksek karar skoru)
    passing = [t for t in (e, cen, h) if t["gates"]["hard_pass"]]
    winner = max(passing, key=lambda t: t["score"]["weighted"])
    check(f"S8 öneri=hybrid (skor {winner['score']['weighted']})", winner["name"] == "self-hybrid")
    check("S8 hybrid karar skoru > edge",
          h["score"]["weighted"] > e["score"]["weighted"])

    # S9: Determinizm — aynı profil iki kez → birebir aynı
    check("S9 determinizm (gecikme+density birebir)",
          measure_topology(_hybrid())["latency"] == h["latency"] and
          measure_topology(_hybrid())["density"] == h["density"])

    # S10: Karar skoru sınırları [0..1] ve ağırlık toplamı 1.0
    check("S10 ağırlık toplamı=1.0", abs(sum(DECISION_WEIGHTS.values()) - 1.0) < 1e-9)
    check("S10 karar skoru [0..1]", all(0.0 <= t["score"]["weighted"] <= 1.0 for t in (e, cen, h)))

    # S11: Percentile sıralaması P50≤P95≤P99 (e2e)
    check("S11 e2e P50≤P95≤P99",
          h["latency"]["e2e"]["p50"] <= h["latency"]["e2e"]["p95"] <= h["latency"]["e2e"]["p99"])

    # S12: barge-in headroom boyutu — edge/hybrid > central (ölçülen karar boyutu)
    check("S12 barge-in headroom edge>central",
          e["score"]["dims"]["bargein"] > cen["score"]["dims"]["bargein"])

    print(f"\n{'='*60}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print(f"SELFTEST GEÇTİ — {12} grup invariant doğrulandı")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Medya işleme konumu deneyi (WBS 0.3.4, →ADR-009)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("evaluate", help="Bir topoloji profilini ölç → gecikme+density+kapı")
    pe.add_argument("--profile", required=True, help="samples/media-*.json")
    pe.add_argument("--samples", type=int, help="örnek sayısı override")
    pe.add_argument("--seed", type=int, help="determinizm tohumu override")
    pe.add_argument("--json-out", help="ölçüm+kapı JSON çıktısı")
    pe.set_defaults(func=cmd_evaluate)

    pc = sub.add_parser("compare", help="Topolojileri karşılaştır + ADR-009 önerisi")
    pc.add_argument("profiles", nargs="+", help="samples/media-*.json ...")
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
