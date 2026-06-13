#!/usr/bin/env python3
"""density_probe.py — Oturum/worker yoğunluk (density) ölçümü (WBS 0.3.3, →NFR 10.2 / ADR-003).

Amaç: 0.3.2 gecikme bütçesini **HARD** kapıya çevirdiği gibi, bu probe **density** hedefini
(NFR 10.2) HARD kapıya çevirir. İki ölçülebilir hedef:
  1. Aktif çağrı başına orkestratör bellek tüketimi (**medya tamponları hariç**) ≤ ~15 MB/oturum.
  2. Referans işçi düğümü (8 vCPU / 16 GB) başına eş zamanlı oturum ≥ 250–500
     (medya işleme konumuna göre).

Yöntem: Oturum bellek/CPU ayak izini birer **dağılım** (sağ-çarpık lognormal — uzun geçmişli /
büyük bağlamlı oturumlar daha çok tüketir) olarak modelleyip Monte-Carlo örnekleme ile oturum-başı
bellek P50/P95/P99'unu üretir; referans worker'a **bellek ∩ CPU** kapasitesini hesaplayıp
density'yi türetir ve NFR 10.2 hedeflerine karşı **kapı** uygular.

Tasarım ilkeleri (CLAUDE.md + 0.2.x/0.3.x hattıyla aynı disiplin):
- **Vendor-neutral (ADR-002/003):** Bileşen ayak izleri **sağlayıcı/dil seçmez**; profil JSON'ları
  SAD §15/§20 + ADR-003 lean-runtime hedeflerinden türetilmiş **mühendislik dağılımlarıdır**. Canlı
  PoC'ta (0.3.5 hot-path Go/Rust) aynı profil yapısı gerçek RSS/heap profili ile doldurulur; kapı
  mantığı değişmez.
- **stdlib-only:** Harici bağımlılık yok (latency_budget_probe.py / e2e_inbound_poc.py disiplini).
- **Deterministik / tekrarlanabilir:** Örnekleme **tohumlanmış** `random.Random(seed)` iledir; aynı
  profil + aynı seed → aynı percentile (CI). Gerçek `time`/process/sır YOK.
- **Kapsam ayrımı:** 0.3.3 = **oturum-başı bellek/CPU + worker density kapısı**. Gecikme 0.3.2,
  medya işleme konumu (edge-vs-merkez) **kararı** 0.3.4 → ADR-009, hot-path dil 0.3.5. Bu probe
  density'yi ölçer; gecikme ölçmez. Medya konumu burada bir **duyarlılık girdisidir** (density'yi
  nasıl etkilediğini gösterir), **kararı 0.3.4'e bırakılır**.

Metrik tanımı (NFR 10.2 / SAD §15.2 yetkili kapı):
  **oturum-başı orkestratör belleği (medya hariç)** = bir aktif oturumun Conversation Orchestrator
  worker'ında tuttuğu bellek; oturum durumu + diyalog belleği + prompt bağlamı + (RAG bağlamı) +
  adapter oturum durumu (pooled) + async runtime overhead. **Medya tamponları (jitter/RTP/ses
  frame) DAHİL DEĞİLDİR** — onlar Media Gateway'de tutulur (SAD §6/§13: "büyük tamponlar Media
  Gateway'de"). 15MB bütçesi (FR-RES-016) bu medya-hariç ayak izine uygulanır.

  **density (worker başına eş zamanlı oturum)** = min(bellek-kapasitesi, CPU-kapasitesi); worker'ın
  kullanılabilir belleği ve CPU bütçesi headroom uygulanarak oturum-başı ortalama tüketime bölünür.
  Medya işleme worker'da **eş-konumlu (co-located)** ise oturum-başı medya bellek/CPU overhead'i
  density hesabına eklenir (ama 15MB bütçe kapısına EKLENMEZ) — bu, NFR 10.2'deki "250–500 (medya
  işleme konumuna göre)" aralığının nereden geldiğini gösterir (→0.3.4/ADR-009).

Modlar:
  measure   — Bir profil (samples/density-*.json) üzerinde N oturum örnekle → bellek P50/P95/P99 +
              CPU + density (bellek/CPU/min) + bileşen atfı + NFR 10.2 kapı verdict'i
              (çıkış kodu: 0=geçti, 1=kaldı).
  compare   — Birden çok profili tablo halinde karşılaştır (bilgilendirici; çıkış kodu 0).
  selftest  — Dahili deterministik profillerle kapı/percentile/determinizm invariant'ları (CI).
  schema    — Profil JSON şemasını ve bileşen anahtarlarını yazar.

Profil JSON şeması — `samples/density-*.json`:
{
  "name": "green-baseline",
  "samples": 20000,              # Monte-Carlo oturum sayısı (varsayılan 20000)
  "seed": 42,                    # determinizm tohumu (varsayılan 42)
  "worker": {                    # referans işçi düğümü (NFR 10.2: 8 vCPU / 16 GB)
     "vcpu": 8, "mem_gb": 16,
     "os_reserve_mb": 1024,      # OS + runtime tabanı (rezerve)
     "mem_headroom_pct": 0.15,   # bellek emniyet payı (toplam varyans için)
     "cpu_target_util": 0.70     # CPU hedef doluluk (üstüne schedule yok)
  },
  "mix": {                       # oturum-başına olasılıklar
     "rag_active_share": 0.30,   # RAG bağlamı taşıyan oturum payı (FR-KB-011 trimmed)
     "long_session_share": 0.20, # uzun (çok-turlu) oturum payı → büyük dialogue_memory
     "media_colocated": false    # medya worker'da mı (0.3.4/ADR-009 DUYARLILIK girdisi)
  },
  "components_mb": {             # her kalem: lognormal(median, p95) — MB, sağ-çarpık
     "session_state":    {"p50": 1.2, "p95": 1.8},   # base struct + turn SM + ctx propagation
     "dialogue_memory":  {"p50": 3.5, "p95": 6.5},   # kısa-süreli geçmiş (FR-RES-010/SAD §6.2)
     "dialogue_long":    {"p50": 7.0, "p95": 11.0},  # uzun çok-turlu oturum (long_session)
     "prompt_context":   {"p50": 1.5, "p95": 2.2},   # versiyonlu system prompt (FR-LLM-006)
     "rag_context":      {"p50": 2.0, "p95": 3.5},   # retrieval bağlamı (trimmed, FR-KB-011)
     "adapter_state":    {"p50": 1.5, "p95": 2.5},   # pooled STT/TTS/LLM conn state (FR-RES-006)
     "runtime_overhead": {"p50": 1.0, "p95": 1.6},   # async task stack (ADR-003 lean)
     "media_colocated":  {"p50": 7.0, "p95": 10.0}   # IF eş-konumlu — density'ye eklenir, BÜTÇE DIŞI
  },
  "components_mcore": {          # her kalem: lognormal(median, p95) — millicore (steady-state)
     "cpu_session":       {"p50": 9.0, "p95": 20.0}, # async I/O-bound oturum CPU'su (ADR-003)
     "cpu_media":         {"p50": 5.0, "p95": 11.0}  # IF eş-konumlu — codec/VAD/SRTP
  }
}
Her bileşen `{p50, p95}` ile bir **lognormal** dağılıma kalibre edilir (median=p50, p95=p95);
p50==p95 ise sabit. Eksik bileşen lean-runtime varsayılanını alır.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys

# --- NFR 10.2 / SAD §15.2 kapı hedefleri (yetkili) -----------------------------------------------
BUDGET_MEM_MB = 15.0           # oturum-başı orkestratör belleği (medya hariç) ≤ ~15 MB (FR-RES-016)
DENSITY_MIN = 250              # worker başına eş zamanlı oturum ≥ 250 (NFR 10.2 alt sınır, HARD)
DENSITY_TARGET = 500           # ≥ 500 stretch hedef (NFR 10.2 üst sınır, YUMUŞAK)

Z95 = 1.6448536269514722       # standart normal 95. percentil (lognormal kalibrasyonu)

# --- Bileşen varsayılanları (lean-runtime hedefi; profil override eder) ---------------------------
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
DEFAULT_MIX = {"rag_active_share": 0.30, "long_session_share": 0.20, "media_colocated": False}
DEFAULT_WORKER = {"vcpu": 8, "mem_gb": 16, "os_reserve_mb": 1024,
                  "mem_headroom_pct": 0.15, "cpu_target_util": 0.70}


# =================================================================================================
# Lognormal bileşen modeli (median + p95 → mu, sigma) — 0.3.2 latency_budget_probe ile aynı
# =================================================================================================
class LogNormalComponent:
    """Sağ-çarpık ayak izi bileşeni; median=p50, 95. percentil=p95'e kalibre lognormal.

    X = exp(mu + sigma·Z),  Z~N(0,1);  median = exp(mu),  p95 = exp(mu + Z95·sigma).
    p50==p95 ise sigma=0 → sabit.
    """

    __slots__ = ("name", "p50", "p95", "mu", "sigma")

    def __init__(self, name: str, p50: float, p95: float) -> None:
        self.name = name
        self.p50 = float(p50)
        self.p95 = max(float(p95), float(p50))   # p95 < p50 anlamsız → tabanla
        self.mu = math.log(self.p50) if self.p50 > 0 else 0.0
        if self.p50 > 0 and self.p95 > self.p50:
            self.sigma = (math.log(self.p95) - self.mu) / Z95
        else:
            self.sigma = 0.0

    def sample(self, rng: random.Random) -> float:
        if self.sigma == 0.0:
            return self.p50
        return math.exp(self.mu + self.sigma * rng.gauss(0.0, 1.0))


# =================================================================================================
# Percentile (0.3.1/0.3.2 ile aynı lineer interpolasyon yöntemi)
# =================================================================================================
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
        "p50": round(percentile(s, 50), 2),
        "p95": round(percentile(s, 95), 2),
        "p99": round(percentile(s, 99), 2),
        "mean": round(sum(s) / len(s), 2) if s else float("nan"),
        "max": round(s[-1], 2) if s else float("nan"),
    }


# =================================================================================================
# Monte-Carlo density ölçümü
# =================================================================================================
def build_components(profile: dict) -> tuple[dict, dict]:
    mb_src = dict(DEFAULT_COMPONENTS_MB)
    mb_src.update(profile.get("components_mb", {}))
    mb = {k: LogNormalComponent(k, float(v["p50"]), float(v["p95"])) for k, v in mb_src.items()}

    mc_src = dict(DEFAULT_COMPONENTS_MCORE)
    mc_src.update(profile.get("components_mcore", {}))
    mc = {k: LogNormalComponent(k, float(v["p50"]), float(v["p95"])) for k, v in mc_src.items()}
    return mb, mc


def measure_profile(profile: dict) -> dict:
    """Profili Monte-Carlo örnekle → oturum-başı bellek/CPU dağılımları + worker density."""
    n = int(profile.get("samples", 20000))
    seed = int(profile.get("seed", 42))
    mix = dict(DEFAULT_MIX)
    mix.update(profile.get("mix", {}))
    worker = dict(DEFAULT_WORKER)
    worker.update(profile.get("worker", {}))
    mb, mc = build_components(profile)
    colocated = bool(mix["media_colocated"])
    rng = random.Random(seed)
    # Medya draw'ları AYRI stream'de: medya eş-konum toggle'ı bütçe/CPU-oturum stream'ini
    # perturbe etmemeli → 15MB bütçesi medya konumundan bağımsız kalır (S11 invariant'ı).
    rng_media = random.Random(seed + 7)

    mem_budget: list[float] = []    # oturum-başı orkestratör belleği (medya HARİÇ) — 15MB bütçe kapısı
    mem_density: list[float] = []   # density hesabı için (medya eş-konumluysa DAHİL)
    cpu_mcore: list[float] = []     # oturum-başı CPU (millicore; medya eş-konumluysa DAHİL)
    # bileşen-atfı: medya-hariç bütçe kalemlerinin oturum-içi katkısı
    contrib: dict[str, list[float]] = {k: [] for k in
                                       ("session_state", "dialogue_memory", "prompt_context",
                                        "rag_context", "adapter_state", "runtime_overhead")}

    for _ in range(n):
        session = mb["session_state"].sample(rng)
        # Diyalog belleği: uzun oturumlar (long_session_share) daha büyük bağlam tutar (FR-RES-010)
        if rng.random() < mix["long_session_share"]:
            dialogue = mb["dialogue_long"].sample(rng)
        else:
            dialogue = mb["dialogue_memory"].sample(rng)
        prompt = mb["prompt_context"].sample(rng)
        adapter = mb["adapter_state"].sample(rng)
        runtime = mb["runtime_overhead"].sample(rng)
        # RAG bağlamı (çoğu turda yok — trimmed, FR-KB-011)
        rag = mb["rag_context"].sample(rng) if rng.random() < mix["rag_active_share"] else 0.0

        budget = session + dialogue + prompt + adapter + runtime + rag
        mem_budget.append(budget)

        # CPU: oturum (async I/O-bound; bütçe-stream ile senkron, her iki modda da çekilir)
        cpu = mc["cpu_session"].sample(rng)

        # density belleği + medya CPU: medya eş-konumluysa AYRI stream'den eklenir (BÜTÇE/CPU-oturum
        # stream'ini perturbe etmeden) — medya ayak izi 15MB bütçesine girmez, density'ye girer.
        if colocated:
            dens_mem = budget + mb["media_colocated"].sample(rng_media)
            cpu += mc["cpu_media"].sample(rng_media)
        else:
            dens_mem = budget
        mem_density.append(dens_mem)
        cpu_mcore.append(cpu)

        contrib["session_state"].append(session)
        contrib["dialogue_memory"].append(dialogue)
        contrib["prompt_context"].append(prompt)
        contrib["adapter_state"].append(adapter)
        contrib["runtime_overhead"].append(runtime)
        if rag:
            contrib["rag_context"].append(rag)

    budget_st = _stats(mem_budget)
    density_mem_st = _stats(mem_density)
    cpu_st = _stats(cpu_mcore)

    # --- Worker kapasitesi: bellek ∩ CPU (headroom uygulanmış) -----------------------------------
    usable_mem_mb = (worker["mem_gb"] * 1024 - worker["os_reserve_mb"]) * (1 - worker["mem_headroom_pct"])
    cpu_budget_mcore = worker["vcpu"] * 1000 * worker["cpu_target_util"]

    cap = _capacity(usable_mem_mb, cpu_budget_mcore, density_mem_st, cpu_st)

    return {
        "name": profile.get("name", "profile"),
        "samples": n, "seed": seed, "mix": mix, "worker": worker,
        "colocated": colocated,
        "mem_budget": budget_st,        # medya-hariç (15MB kapısı)
        "mem_density": density_mem_st,  # density için (medya dahil olabilir)
        "cpu": cpu_st,
        "usable_mem_mb": round(usable_mem_mb, 1),
        "cpu_budget_mcore": round(cpu_budget_mcore, 1),
        "capacity": cap,
        "contrib": {k: _stats(v) for k, v in contrib.items() if v},
    }


def _capacity(usable_mem_mb: float, cpu_budget_mcore: float,
              mem_st: dict, cpu_st: dict) -> dict:
    """Bellek ∩ CPU kapasitesi. mean-packing = istatistiksel (N bağımsız oturum → ortalama
    yoğunlaşır, CLT); p95-packing = muhafazakar (her oturum p95'te) alt-sınır."""
    def floor_div(num, den):
        return int(num // den) if den > 0 else 0

    mem_mean = floor_div(usable_mem_mb, mem_st["mean"])
    mem_p95 = floor_div(usable_mem_mb, mem_st["p95"])
    cpu_mean = floor_div(cpu_budget_mcore, cpu_st["mean"])
    cpu_p95 = floor_div(cpu_budget_mcore, cpu_st["p95"])

    density_mean = min(mem_mean, cpu_mean)
    density_p95 = min(mem_p95, cpu_p95)
    bottleneck = "memory" if mem_mean <= cpu_mean else "cpu"
    return {
        "mem_mean": mem_mean, "mem_p95": mem_p95,
        "cpu_mean": cpu_mean, "cpu_p95": cpu_p95,
        "density_mean": density_mean,   # PRIMARY (kapı bunu kullanır)
        "density_p95": density_p95,     # muhafazakar alt-sınır (yumuşak)
        "bottleneck": bottleneck,
    }


# =================================================================================================
# NFR 10.2 kapı değerlendirmesi (HARD = çıkış kodunu belirler)
# =================================================================================================
def evaluate_gates(m: dict) -> dict:
    checks = []

    def chk(key, ok, detail, hard=True):
        checks.append({"check": key, "pass": bool(ok), "detail": detail, "hard": hard})

    b = m["mem_budget"]
    cap = m["capacity"]
    dens = cap["density_mean"]

    # Kapı 1: oturum-başı bellek bütçesi (medya hariç) P95 ≤ 15 MB (FR-RES-016)
    chk("mem_budget_p95", b["p95"] <= BUDGET_MEM_MB,
        f"oturum belleği (medya hariç) P95 {b['p95']}MB ≤ {BUDGET_MEM_MB:.0f}MB")
    # Kapı 2: worker density (mean-packing) ≥ 250 (NFR 10.2 alt sınır)
    chk("density_min", dens >= DENSITY_MIN,
        f"density {dens} oturum/worker ≥ {DENSITY_MIN} (bottleneck={cap['bottleneck']})")
    # Yumuşak: ≥ 500 stretch hedef
    chk("density_target", dens >= DENSITY_TARGET,
        f"density {dens} ≥ {DENSITY_TARGET} (stretch)", hard=False)

    hard_pass = all(c["pass"] for c in checks if c["hard"])
    return {"checks": checks, "hard_pass": hard_pass}


# =================================================================================================
# Bileşen atfı (15MB bütçesinin neresi dolu — headroom analizi)
# =================================================================================================
def attribution_rows(m: dict) -> list[dict]:
    grand_total = (m["mem_budget"]["mean"] or 1.0) * m["samples"]
    rows = []
    label = {"session_state": "Oturum durumu", "dialogue_memory": "Diyalog belleği",
             "prompt_context": "Prompt bağlamı", "rag_context": "RAG bağlamı (varsa)",
             "adapter_state": "Adapter durumu (pooled)", "runtime_overhead": "Async runtime"}
    order = ["session_state", "dialogue_memory", "prompt_context", "rag_context",
             "adapter_state", "runtime_overhead"]
    for k in order:
        if k not in m["contrib"]:
            continue
        st = m["contrib"][k]
        comp_total = st["mean"] * st["n"]   # koşullu kalemde (rag) n<samples
        rows.append({"component": label.get(k, k), "p50": st["p50"], "p95": st["p95"],
                     "mean": st["mean"], "share_pct": round(100.0 * comp_total / grand_total, 1)})
    return rows


# =================================================================================================
# CLI
# =================================================================================================
def _print_measure(m: dict, gates: dict) -> None:
    b, dm, cpu, cap = m["mem_budget"], m["mem_density"], m["cpu"], m["capacity"]
    print(f"# Density ölçümü — profil='{m['name']}'  (N={m['samples']} oturum, seed={m['seed']})")
    print(f"  worker: {m['worker']['vcpu']} vCPU / {m['worker']['mem_gb']} GB  "
          f"(kullanılabilir bellek {m['usable_mem_mb']}MB, CPU bütçesi {m['cpu_budget_mcore']:.0f} mcore)")
    print(f"  mix: rag={m['mix']['rag_active_share']:.0%} uzun-oturum={m['mix']['long_session_share']:.0%} "
          f"medya-eş-konumlu={'EVET' if m['colocated'] else 'hayır'}")

    print("\n## Oturum-başı orkestratör belleği — medya HARİÇ (MB)  [15MB bütçe kapısı]")
    print(f"  P50={b['p50']}  P95={b['p95']}  P99={b['p99']}  mean={b['mean']}  max={b['max']}")
    print(f"  bütçe kullanımı (P95/15MB): {100.0*b['p95']/BUDGET_MEM_MB:.0f}%   "
          f"headroom: {BUDGET_MEM_MB - b['p95']:+.1f}MB")
    if m["colocated"]:
        print(f"  (density için medya-dahil bellek: P50={dm['p50']} P95={dm['p95']} mean={dm['mean']}MB)")
    print(f"  oturum CPU (steady-state, millicore): P50={cpu['p50']} P95={cpu['p95']} mean={cpu['mean']}")

    print("\n## Bileşen atfı (15MB bütçe kırılımı — ort. katkı)")
    print(f"  {'bileşen':<26}{'P50':>7}{'P95':>8}{'ort':>7}{'pay%':>8}")
    for r in attribution_rows(m):
        print(f"  {r['component']:<26}{r['p50']:>7.2f}{r['p95']:>8.2f}"
              f"{r['mean']:>7.2f}{r['share_pct']:>7.1f}%")

    print("\n## Worker density (eş zamanlı oturum)")
    print(f"  {'':<14}{'bellek-bağlı':>14}{'CPU-bağlı':>12}{'min (density)':>15}")
    print(f"  {'mean-packing':<14}{cap['mem_mean']:>14}{cap['cpu_mean']:>12}{cap['density_mean']:>15}")
    print(f"  {'p95-packing':<14}{cap['mem_p95']:>14}{cap['cpu_p95']:>12}{cap['density_p95']:>15}  (muhafazakar)")
    print(f"  bottleneck (mean): {cap['bottleneck'].upper()}")

    print("\n## NFR 10.2 kapı (HARD = çıkış kodunu belirler)")
    for c in gates["checks"]:
        mark = "✅" if c["pass"] else "❌"
        tag = "" if c["hard"] else "  (yumuşak/stretch)"
        print(f"  {mark} {c['check']:<16} {c['detail']}{tag}")

    verdict = "🟢 GEÇTİ" if gates["hard_pass"] else "🔴 KALDI"
    print(f"\n## VERDICT: {verdict}  (NFR 10.2 density hedefi "
          f"{'karşılandı' if gates['hard_pass'] else 'KARŞILANMADI'})")


def cmd_measure(args) -> int:
    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)
    if args.samples:
        profile["samples"] = args.samples
    if args.seed is not None:
        profile["seed"] = args.seed
    m = measure_profile(profile)
    gates = evaluate_gates(m)
    _print_measure(m, gates)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"measure": m, "gates": gates}, f, ensure_ascii=False, indent=2)
        print(f"\n(JSON yazıldı: {args.json_out})")
    return 0 if gates["hard_pass"] else 1


def cmd_compare(args) -> int:
    print("# Density karşılaştırma (NFR 10.2)\n")
    print(f"  {'profil':<24}{'mem.P95':>9}{'CPU.mean':>10}{'density':>9}{'bottleneck':>12}  verdict")
    for path in args.profiles:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        if args.samples:
            profile["samples"] = args.samples
        m = measure_profile(profile)
        g = evaluate_gates(m)
        b, cpu, cap = m["mem_budget"], m["cpu"], m["capacity"]
        verdict = "🟢" if g["hard_pass"] else "🔴"
        print(f"  {m['name']:<24}{b['p95']:>8.1f}{cpu['mean']:>10.1f}"
              f"{cap['density_mean']:>9}{cap['bottleneck']:>12}  {verdict}")
    print(f"\n  Hedef: oturum belleği P95≤{BUDGET_MEM_MB:.0f}MB · density≥{DENSITY_MIN} "
          f"(stretch ≥{DENSITY_TARGET}) per 8vCPU/16GB worker (NFR 10.2)")
    return 0


def cmd_schema(_args) -> int:
    print(__doc__)
    return 0


# --- selftest ------------------------------------------------------------------------------------
def _green() -> dict:
    return {"name": "self-green", "samples": 20000, "seed": 7,
            "mix": {"rag_active_share": 0.30, "long_session_share": 0.20, "media_colocated": False},
            "worker": dict(DEFAULT_WORKER),
            "components_mb": dict(DEFAULT_COMPONENTS_MB),
            "components_mcore": dict(DEFAULT_COMPONENTS_MCORE)}


def _red() -> dict:
    # thread-per-call / GC-ağır analog: şişkin oturum + yüksek CPU (ADR-003 ihlali)
    return {"name": "self-red", "samples": 20000, "seed": 7,
            "mix": {"rag_active_share": 0.60, "long_session_share": 0.50, "media_colocated": True},
            "worker": dict(DEFAULT_WORKER),
            "components_mb": {
                "session_state": {"p50": 2.5, "p95": 4.0}, "dialogue_memory": {"p50": 7.0, "p95": 12.0},
                "dialogue_long": {"p50": 13.0, "p95": 20.0}, "prompt_context": {"p50": 3.0, "p95": 5.0},
                "rag_context": {"p50": 4.0, "p95": 7.0}, "adapter_state": {"p50": 3.0, "p95": 5.0},
                "runtime_overhead": {"p50": 4.0, "p95": 7.0}, "media_colocated": {"p50": 10.0, "p95": 16.0}},
            "components_mcore": {
                "cpu_session": {"p50": 22.0, "p95": 45.0}, "cpu_media": {"p50": 10.0, "p95": 22.0}}}


def cmd_selftest(_args) -> int:
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("## selftest — density invariant'ları (credential'sız, deterministik)\n")

    # S1: Lognormal kalibrasyonu — örneklem median/p95 hedeflere yakın
    c = LogNormalComponent("t", 5.0, 10.0)
    rng = random.Random(1)
    xs = sorted(c.sample(rng) for _ in range(50000))
    med, p95 = percentile(xs, 50), percentile(xs, 95)
    check(f"S1 lognormal median≈5 ({med:.2f})", abs(med - 5.0) < 0.2)
    check(f"S1 lognormal p95≈10 ({p95:.2f})", abs(p95 - 10.0) < 0.4)

    # S2: p50==p95 → sabit (sigma=0)
    cc = LogNormalComponent("const", 1.0, 1.0)
    check("S2 p50==p95 sabit", cc.sigma == 0.0 and cc.sample(random.Random(0)) == 1.0)

    # S3: percentile monotonluğu
    s = [float(i) for i in range(101)]
    check("S3 percentile monoton", percentile(s, 50) < percentile(s, 95) < percentile(s, 99))

    # S4: Green profil → tüm HARD kapılar geçer (bütçe ≤15 + density ≥250)
    mg = measure_profile(_green())
    gg = evaluate_gates(mg)
    check("S4 green hard_pass", gg["hard_pass"])
    check(f"S4 green oturum belleği P95≤15 ({mg['mem_budget']['p95']:.1f})",
          mg["mem_budget"]["p95"] <= BUDGET_MEM_MB)
    check(f"S4 green density≥250 ({mg['capacity']['density_mean']})",
          mg["capacity"]["density_mean"] >= DENSITY_MIN)

    # S5: Red profil → HARD kapı KALDI (bütçe>15 + density<250)
    mr = measure_profile(_red())
    gr = evaluate_gates(mr)
    check("S5 red hard KALDI", not gr["hard_pass"])
    mem_fail = next(c for c in gr["checks"] if c["check"] == "mem_budget_p95")
    dens_fail = next(c for c in gr["checks"] if c["check"] == "density_min")
    check(f"S5 red bütçe kapısı fail (P95={mr['mem_budget']['p95']:.1f}>15)", not mem_fail["pass"])
    check(f"S5 red density kapısı fail ({mr['capacity']['density_mean']}<250)", not dens_fail["pass"])

    # S6: Percentile sıralaması P50≤P95≤P99
    check("S6 P50≤P95≤P99 (green bellek)",
          mg["mem_budget"]["p50"] <= mg["mem_budget"]["p95"] <= mg["mem_budget"]["p99"])

    # S7: Determinizm — aynı profil+seed iki kez → birebir aynı
    m1, m2 = measure_profile(_green()), measure_profile(_green())
    check("S7 determinizm (bellek+density birebir)",
          m1["mem_budget"] == m2["mem_budget"] and m1["capacity"] == m2["capacity"])

    # S8: Farklı seed → farklı örneklem (ama yakın density)
    g2 = _green(); g2["seed"] = 99
    m3 = measure_profile(g2)
    check("S8 farklı seed farklı örneklem", m3["mem_budget"]["max"] != m1["mem_budget"]["max"])
    check("S8 farklı seed yakın density (±5%)",
          abs(m3["capacity"]["density_mean"] - m1["capacity"]["density_mean"])
          / m1["capacity"]["density_mean"] < 0.05)

    # S9: Bileşen atfı payları toplam ≈ %100
    rows = attribution_rows(mg)
    share_sum = sum(r["share_pct"] for r in rows)
    check(f"S9 atıf payları ≈%100 ({share_sum:.0f}%)", abs(share_sum - 100.0) < 2.0)

    # S10: Medya eş-konumlu → density DÜŞER (0.3.4/ADR-009 duyarlılığı)
    g_edge = _green()
    g_colo = _green(); g_colo["mix"]["media_colocated"] = True
    d_edge = measure_profile(g_edge)["capacity"]["density_mean"]
    d_colo = measure_profile(g_colo)["capacity"]["density_mean"]
    check(f"S10 medya eş-konumlu density↓ ({d_edge}→{d_colo})", d_colo < d_edge)

    # S11: 15MB bütçe medya'yı HARİÇ tutar → eş-konumlu toggle bütçe-P95'i değiştirmez
    b_edge = measure_profile(g_edge)["mem_budget"]["p95"]
    b_colo = measure_profile(g_colo)["mem_budget"]["p95"]
    check(f"S11 bütçe medya-hariç (toggle etkilemez {b_edge:.1f}={b_colo:.1f})", b_edge == b_colo)

    # S12: Uzun-oturum payı↑ → oturum belleği P95↑ (FR-RES-010 geçmiş büyümesi)
    g_short = _green(); g_short["mix"]["long_session_share"] = 0.05
    g_long = _green(); g_long["mix"]["long_session_share"] = 0.80
    check("S12 uzun-oturum payı↑ → bellek P95↑",
          measure_profile(g_long)["mem_budget"]["p95"] > measure_profile(g_short)["mem_budget"]["p95"])

    # S13: density_p95 (muhafazakar) ≤ density_mean
    check("S13 p95-packing ≤ mean-packing",
          mg["capacity"]["density_p95"] <= mg["capacity"]["density_mean"])

    print(f"\n{'='*60}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print(f"SELFTEST GEÇTİ — {13} grup invariant doğrulandı")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Density ölçümü (WBS 0.3.3, NFR 10.2/ADR-003)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("measure", help="Bir profili Monte-Carlo ölç → bellek + density + kapı")
    pm.add_argument("--profile", required=True, help="samples/density-*.json")
    pm.add_argument("--samples", type=int, help="oturum sayısı override")
    pm.add_argument("--seed", type=int, help="determinizm tohumu override")
    pm.add_argument("--json-out", help="ölçüm+kapı JSON çıktısı")
    pm.set_defaults(func=cmd_measure)

    pc = sub.add_parser("compare", help="Birden çok profili tablo halinde karşılaştır")
    pc.add_argument("profiles", nargs="+", help="samples/density-*.json ...")
    pc.add_argument("--samples", type=int, help="oturum sayısı override")
    pc.set_defaults(func=cmd_compare)

    ps = sub.add_parser("selftest", help="Kapı/percentile/determinizm invariant'ları (credential'sız)")
    ps.set_defaults(func=cmd_selftest)

    psc = sub.add_parser("schema", help="Profil JSON şemasını yaz")
    psc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
