#!/usr/bin/env python3
"""load_test_probe.py — Yük/performans test ortamı: sentetik çağrı üreteci (WBS 0.4.8, →FR-TST-006).

Amaç: Tasarım kapasitesinde (NFR 10.3) **sistem-seviyesi** yük testini yürütecek **sentetik çağrı
üreteci / yük test ortamını** modeller ve doğrular. 0.3.2 (tek-çağrı gecikme) ve 0.3.3 (worker-başı
density) **tek oturum** ölçer; bu probe **çok-oturumlu sistem davranışını** yük altında ölçer:
geliş hızı (CPS), eş zamanlı oturum doluluğu, worker havuzu + autoscale + warm pool, backpressure/
admission (FR-RES-014) ve **yük altında çağrı-başı kaynak regresyonu** (FR-TST-009, BRD §19 (21)).

Bu, FR-TST-006'nın gerektirdiği **yük + eş zamanlı çağrı test ortamının** yürütülebilir iskeletidir:
deterministik bir kesikli-zaman (discrete-time) simülasyonla sentetik çağrı trafiği üretir, sistemin
(worker fleet + Resource Manager) bu trafiği nasıl emdiğini izler ve NFR 10.3 / NFR 10.1 / NFR 10.2 /
FR-RES-014 kapılarını **HARD** uygular. Canlı yük testinde (F1 §18.5) aynı senaryo yapısı gerçek
call-generator (telefoni trunk + sentetik medya) ile doldurulur; kapı mantığı değişmez.

Tasarım ilkeleri (CLAUDE.md + 0.2.x/0.3.x hattıyla birebir disiplin):
- **Vendor-neutral (ADR-002):** Senaryolar sağlayıcı/dil **seçmez**; SAD §16/§20 + 0.3.2/0.3.3/0.3.4
  hedeflerinden türetilmiş **mühendislik profilleridir**. Canlı testte aynı yapı gerçek telemetri ile dolar.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / *_eval_probe.py / *_poc.py / *_probe.py disiplini).
- **Deterministik / tekrarlanabilir:** Geliş süreci tohumlanmış `random.Random(seed)` (Poisson) iledir;
  aynı senaryo + aynı seed → aynı percentile/kapı (CI). Gerçek `time`/ağ/sır/credential YOK.
- **Sentetik veri (FR-TST-008):** Gerçek müşteri verisi/PII yok; üretilen çağrılar tamamen sentetiktir.
- **Kapsam ayrımı:** 0.4.8 = **yük üreteci + sistem-seviyesi kapasite/backpressure/yük-altı kaynak**.
  Tek-çağrı gecikme dağılımı 0.3.2, oturum-başı density 0.3.3, medya konumu 0.3.4. Bu probe onların
  **çıktısını girdi** alır (base gecikme/bellek/worker kapasitesi) ve yük altında nasıl davrandığını ölçer.

Metrik tanımları (yetkili kapılar):
  KAPASİTE (NFR 10.3): tasarım eş zamanlılığı = max(target_concurrency, ⌈target_cps × ort_çağrı_sn⌉)
    (Erlang/Little yasası: ortalama eş zamanlı oturum = geliş hızı × ortalama tutma süresi).
    Fleet kapasitesi (workers_max × worker_capacity) ≥ tasarım eş zamanlılığı olmalı.
  CPS (NFR 10.3): admission_cps ≥ target_cps; **steady soak** penceresinde red oranı ≤ bütçe.
  GECİKME YÜK ALTINDA (NFR 10.1): base e2e gecikme (0.3.2) × tıkanma faktörü f(util); P95≤1200/P99≤2000.
  KAYNAK YÜK ALTINDA (FR-TST-009/FR-RES-016/§19(21)): çağrı-başı bellek (0.3.3) × (1+büyüme·util); P95≤15MB.
  BACKPRESSURE (FR-RES-014): admission_util<1.0 ve gözlenen util≤~1.0 (çökme yok); red **muhasebeli** (sessiz değil).
  2x ANİ TRAFİK (NFR 10.3): burst penceresinde warm pool + autoscale red oranını bütçede tutar, util≤~1.0.

Modlar:
  run       — Bir senaryoyu (scenarios/load-*.json) simüle et → kapasite/CPS/gecikme/kaynak/backpressure
              + NFR 10.3/10.1/10.2 + FR-RES-014 kapı verdict'i (çıkış kodu: 0=geçti, 1=kaldı).
  compare   — Birden çok senaryoyu tablo halinde karşılaştır (bilgilendirici; çıkış kodu 0).
  selftest  — Dahili deterministik senaryolarla kapı/Little-yasası/determinizm invariant'ları (CI).
  schema    — Senaryo JSON şemasını ve anahtarları yazar.

Senaryo JSON şeması — `scenarios/load-*.json`:
{
  "name": "hyperscale-region",
  "seed": 42,
  "load": {                       # sentetik yük profili (call generator girdisi)
     "target_cps": 100,           # tasarım geliş hızı (yeni çağrı/sn) — NFR 10.3
     "target_concurrency": 10000, # tasarım eş zamanlı oturum — NFR 10.3
     "mean_call_seconds": 100,    # ortalama tutma süresi (Little yasası: conc = cps × tutma)
     "call_p95_seconds": 220,     # tutma süresi p95 (lognormal kuyruk)
     "ramp_seconds": 60,          # 0→target_cps doğrusal ısınma
     "soak_seconds": 300,         # target_cps sabit yük (steady-state ölçüm penceresi)
     "burst_multiplier": 2.0,     # ani trafik çarpanı (NFR 10.3 "2x kısa süreli")
     "burst_seconds": 30          # burst penceresi süresi (0 → burst yok)
  },
  "fleet": {                      # sistemin worker havuzu + Resource Manager (SAD §16)
     "worker_capacity": 354,      # oturum/worker (0.3.3/0.3.4 density çıktısı; hibrit≈354)
     "workers_min": 4,            # minimum (scale-to-zero üstü taban)
     "workers_max": 40,           # autoscale tavanı (kapasite = workers_max × worker_capacity)
     "warm_pool_workers": 6,      # talep üstü tutulan ön-ısıtılmış worker (FR-RES-013)
     "scale_up_seconds": 30,      # scale_step_workers eklemek için autoscaler tepki gecikmesi
     "scale_step_workers": 4      # her scale_up_seconds'ta eklenebilen worker artışı
  },
  "admission": {                  # backpressure / kabul kontrolü (FR-RES-014, SAD §16)
     "util_threshold": 0.92,      # bu doluluğun üstünde yeni çağrı reddedilir (graceful)
     "max_cps": 120,             # kabul edilebilir azami geliş hızı (kuyruk/red üstü)
     "soak_reject_budget": 0.01,  # steady soak'ta kabul edilebilir red oranı (≤%1)
     "burst_reject_budget": 0.05  # burst penceresinde kabul edilebilir red oranı (≤%5)
  },
  "under_load": {                 # yük altında bozulma modeli (0.3.2/0.3.3 base + yük etkisi)
     "base_latency": {"p50": 632, "p95": 863},  # tek-çağrı e2e gecikme base (0.3.2 green)
     "congestion_k": 0.04,        # tıkanma duyarlılığı: f(util)=1+k·util/(1-util)
     "base_call_mem": {"p50": 11.5, "p95": 13.9},# çağrı-başı bellek base MB (0.3.3 green, medya hariç)
     "load_mem_growth": 0.04      # tam yükte çağrı-başı bellek büyüme oranı (regresyon, FR-TST-009)
  }
}
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys

# --- Yetkili kapı hedefleri ----------------------------------------------------------------------
GATE_LAT_P95_MS = 1200.0     # yük altında e2e P95 ≤ 1200 (NFR 10.1)
GATE_LAT_P99_MS = 2000.0     # yük altında e2e P99 ≤ 2000 (NFR 10.1)
GATE_MEM_P95_MB = 15.0       # yük altında çağrı-başı bellek P95 ≤ 15MB (FR-RES-016/FR-TST-009/§19(21))
GATE_UTIL_MAX = 1.02         # gözlenen doluluk tavanı (backpressure çökme önler — FR-RES-014)

Z95 = 1.6448536269514722     # standart normal 95. percentil (lognormal kalibrasyonu)

# --- Varsayılanlar (senaryo override eder) -------------------------------------------------------
DEFAULT_LOAD = {"target_cps": 50.0, "target_concurrency": 3000.0, "mean_call_seconds": 100.0,
                "call_p95_seconds": 220.0, "ramp_seconds": 60.0, "soak_seconds": 300.0,
                "burst_multiplier": 2.0, "burst_seconds": 30.0}
DEFAULT_FLEET = {"worker_capacity": 354.0, "workers_min": 4.0, "workers_max": 40.0,
                 "warm_pool_workers": 6.0, "scale_up_seconds": 30.0, "scale_step_workers": 4.0}
DEFAULT_ADMISSION = {"util_threshold": 0.92, "max_cps": 120.0, "soak_reject_budget": 0.01,
                     "burst_reject_budget": 0.05}
DEFAULT_UNDER_LOAD = {"base_latency": {"p50": 632.0, "p95": 863.0}, "congestion_k": 0.04,
                      "base_call_mem": {"p50": 11.5, "p95": 13.9}, "load_mem_growth": 0.04}


# =================================================================================================
# Lognormal bileşen modeli (median + p95 → mu, sigma) — 0.3.2/0.3.3 ile BİREBİR
# =================================================================================================
class LogNormalComponent:
    """Sağ-çarpık büyüklük (gecikme/tutma/bellek); median=p50, 95. percentil=p95'e kalibre lognormal."""

    __slots__ = ("p50", "p95", "mu", "sigma")

    def __init__(self, p50: float, p95: float) -> None:
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
    """Lineer interpolasyonlu percentile — 0.3.1/0.3.2/0.3.3 ile aynı yöntem."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _stats(vals: list[float], ndigits: int = 1) -> dict:
    s = sorted(vals)
    if not s:
        return {"n": 0, "p50": float("nan"), "p95": float("nan"), "p99": float("nan"),
                "mean": float("nan"), "max": float("nan")}
    return {
        "n": len(s),
        "p50": round(percentile(s, 50), ndigits),
        "p95": round(percentile(s, 95), ndigits),
        "p99": round(percentile(s, 99), ndigits),
        "mean": round(sum(s) / len(s), ndigits),
        "max": round(s[-1], ndigits),
    }


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth algoritması ile Poisson(lam) örnekleme (stdlib-only, tohumlu)."""
    if lam <= 0.0:
        return 0
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


# =================================================================================================
# Yük profili — call generator'ın ürettiği geliş hızı cps(t)
# =================================================================================================
def cps_at(t: float, load: dict) -> float:
    """Zaman t (sn) için anlık geliş hızı: ramp (0→target) → soak (target) → burst (target×mult)."""
    ramp = load["ramp_seconds"]
    soak = load["soak_seconds"]
    burst = load["burst_seconds"]
    target = load["target_cps"]
    if t < ramp:
        return target * (t / ramp) if ramp > 0 else target
    if t < ramp + soak:
        return target
    if burst > 0 and t < ramp + soak + burst:
        return target * load["burst_multiplier"]
    return 0.0


def total_seconds(load: dict) -> float:
    return load["ramp_seconds"] + load["soak_seconds"] + max(0.0, load["burst_seconds"])


# =================================================================================================
# Kesikli-zaman yük simülasyonu (sentetik çağrı üreteci + sistem emilimi)
# =================================================================================================
def _merge(defaults: dict, override: dict) -> dict:
    out = dict(defaults)
    out.update(override or {})
    return out


def simulate(scenario: dict) -> dict:
    """Senaryoyu 1 sn adımlarla simüle et → kapasite/CPS/gecikme/kaynak/backpressure dağılımları."""
    seed = int(scenario.get("seed", 42))
    load = _merge(DEFAULT_LOAD, scenario.get("load"))
    fleet = _merge(DEFAULT_FLEET, scenario.get("fleet"))
    adm = _merge(DEFAULT_ADMISSION, scenario.get("admission"))
    ul = _merge(DEFAULT_UNDER_LOAD, scenario.get("under_load"))

    rng = random.Random(seed)
    rng_hold = random.Random(seed + 101)
    rng_lat = random.Random(seed + 202)
    rng_mem = random.Random(seed + 303)

    hold = LogNormalComponent(load["mean_call_seconds"], load["call_p95_seconds"])
    base_lat = LogNormalComponent(ul["base_latency"]["p50"], ul["base_latency"]["p95"])
    base_mem = LogNormalComponent(ul["base_call_mem"]["p50"], ul["base_call_mem"]["p95"])
    cong_k = float(ul["congestion_k"])
    mem_growth = float(ul["load_mem_growth"])

    cap_per_worker = fleet["worker_capacity"]
    workers_min, workers_max = fleet["workers_min"], fleet["workers_max"]
    warm = fleet["warm_pool_workers"]
    up_rate = (fleet["scale_step_workers"] / fleet["scale_up_seconds"]) if fleet["scale_up_seconds"] > 0 else 1e9
    down_rate = up_rate  # ölçek-düşürme de gecikmeli (kozmetik; kapıyı etkilemez)

    util_thr = adm["util_threshold"]
    max_cps = adm["max_cps"]

    step = 1.0
    T = total_seconds(load)
    n_steps = int(math.ceil(T / step))

    active = 0
    provisioned = float(workers_min)
    departures: dict[int, int] = {}   # adım index → o adımda biten oturum sayısı

    # zaman pencereleri (steady soak ve burst metrikleri için)
    soak_lo = load["ramp_seconds"] + min(load["mean_call_seconds"], load["soak_seconds"] * 0.5)
    soak_hi = load["ramp_seconds"] + load["soak_seconds"]
    burst_lo = load["ramp_seconds"] + load["soak_seconds"]
    burst_hi = burst_lo + load["burst_seconds"]

    lat_samples: list[float] = []
    mem_samples: list[float] = []
    util_series: list[float] = []
    peak_active = 0
    total_arr = total_adm = total_rej = 0
    soak_arr = soak_rej = 0
    burst_arr = burst_rej = 0
    cap_at_soak_end = 0.0

    for i in range(n_steps):
        t = i * step

        # 1) Departures (tutma süresi dolan oturumlar ayrılır)
        active -= departures.pop(i, 0)
        if active < 0:
            active = 0

        # 2) Autoscaling: talebe göre worker sağla (warm pool tamponu + tepki gecikmesi)
        demand_workers = active / cap_per_worker if cap_per_worker > 0 else workers_max
        target_prov = max(workers_min, min(workers_max, math.ceil(demand_workers) + warm))
        if target_prov > provisioned:
            provisioned = min(target_prov, provisioned + up_rate * step)
        elif target_prov < provisioned:
            provisioned = max(target_prov, provisioned - down_rate * step)
        capacity = math.floor(provisioned) * cap_per_worker

        # 3) Sentetik geliş (Poisson) — call generator bu adımda üretilen çağrı sayısı
        lam = cps_at(t, load) * step
        arrivals = poisson(rng, lam)

        # 4) Admission / backpressure (FR-RES-014): doluluk eşiği + CPS tavanı; fazlası graceful red
        max_by_util = max(0, int(util_thr * capacity) - active)
        max_by_cps = int(max_cps * step)
        admitted = min(arrivals, max_by_util, max_by_cps)
        rejected = arrivals - admitted

        # 5) Kabul edilen oturumlar: tutma süresi + yük-altı gecikme/bellek örnekle
        util_now = (active / capacity) if capacity > 0 else 1.5
        # tıkanma faktörü f(util)=1+k·util/(1-util), util→1'de patlamayı önlemek için tabanla/tavanla
        u = min(max(util_now, 0.0), 0.99)
        cong = 1.0 + cong_k * (u / (1.0 - u))
        cong = min(cong, 8.0)
        for _ in range(admitted):
            dwell = max(1.0, hold.sample(rng_hold))
            dep_idx = i + int(round(dwell / step))
            departures[dep_idx] = departures.get(dep_idx, 0) + 1
            lat_samples.append(base_lat.sample(rng_lat) * cong)
            mem_samples.append(base_mem.sample(rng_mem) * (1.0 + mem_growth * u))
        active += admitted

        # 6) Kayıt / pencere muhasebesi
        if active > peak_active:
            peak_active = active
        util_series.append(util_now if capacity > 0 else 1.5)
        total_arr += arrivals
        total_adm += admitted
        total_rej += rejected
        if soak_lo <= t < soak_hi:
            soak_arr += arrivals
            soak_rej += rejected
        if burst_hi > burst_lo and burst_lo <= t < burst_hi:
            burst_arr += arrivals
            burst_rej += rejected
        if abs(t - (soak_hi - step)) < step / 2:
            cap_at_soak_end = capacity

    design_conc = max(load["target_concurrency"],
                      math.ceil(load["target_cps"] * load["mean_call_seconds"]))
    capacity_max = workers_max * cap_per_worker
    max_util = max(util_series) if util_series else 0.0

    return {
        "name": scenario.get("name", "scenario"),
        "seed": seed,
        "load": load, "fleet": fleet, "admission": adm,
        "design_concurrency": int(design_conc),
        "offered_concurrency": int(round(load["target_cps"] * load["mean_call_seconds"])),
        "capacity_max": int(capacity_max),
        "peak_active": int(peak_active),
        "cap_at_soak_end": int(cap_at_soak_end),
        "max_util": round(max_util, 3),
        "arrivals": total_arr, "admitted": total_adm, "rejected": total_rej,
        "reject_rate": round(total_rej / total_arr, 4) if total_arr else 0.0,
        "soak_reject_rate": round(soak_rej / soak_arr, 4) if soak_arr else 0.0,
        "burst_reject_rate": round(burst_rej / burst_arr, 4) if burst_arr else None,
        "latency": _stats(lat_samples),
        "mem": _stats(mem_samples, ndigits=2),
        "headroom_pct": round(100.0 * (capacity_max - design_conc) / design_conc, 1) if design_conc else 0.0,
    }


# =================================================================================================
# Kapı değerlendirmesi (HARD = çıkış kodunu belirler)
# =================================================================================================
def evaluate_gates(m: dict) -> dict:
    checks = []

    def chk(key, ok, detail, hard=True):
        checks.append({"check": key, "pass": bool(ok), "detail": detail, "hard": hard})

    adm = m["admission"]
    load = m["load"]

    # G1: Kapasite ≥ tasarım eş zamanlılığı (NFR 10.3 / FR-TST-006)
    chk("capacity_adequate", m["capacity_max"] >= m["design_concurrency"],
        f"fleet kapasite {m['capacity_max']} ≥ tasarım conc {m['design_concurrency']} "
        f"(headroom %{m['headroom_pct']})")

    # G2: CPS sürdürülebilir — admission_cps ≥ target_cps + soak red ≤ bütçe (NFR 10.3 / FR-RES-014)
    cps_ok = adm["max_cps"] >= load["target_cps"]
    soak_ok = m["soak_reject_rate"] <= adm["soak_reject_budget"]
    chk("cps_sustained", cps_ok and soak_ok,
        f"admission_cps {adm['max_cps']:.0f} ≥ target {load['target_cps']:.0f} & "
        f"soak red %{m['soak_reject_rate']*100:.2f} ≤ %{adm['soak_reject_budget']*100:.0f}")

    # G3: Yük altında gecikme (NFR 10.1)
    lat = m["latency"]
    chk("latency_under_load", lat["p95"] <= GATE_LAT_P95_MS and lat["p99"] <= GATE_LAT_P99_MS,
        f"yük-altı P95 {lat['p95']}ms ≤ {GATE_LAT_P95_MS:.0f} & P99 {lat['p99']}ms ≤ {GATE_LAT_P99_MS:.0f}")

    # G4: Yük altında çağrı-başı kaynak (FR-TST-009 / FR-RES-016 / §19(21))
    mem = m["mem"]
    chk("resource_under_load", mem["p95"] <= GATE_MEM_P95_MB,
        f"yük-altı bellek P95 {mem['p95']}MB ≤ {GATE_MEM_P95_MB:.0f}MB")

    # G5: Backpressure graceful — admission<1.0 & gözlenen util≤~1.0 (çökme yok) (FR-RES-014)
    bp_ok = adm["util_threshold"] < 1.0 and m["max_util"] <= GATE_UTIL_MAX
    chk("backpressure_graceful", bp_ok,
        f"admission util_thr {adm['util_threshold']:.2f} <1.0 & gözlenen max_util "
        f"{m['max_util']:.2f} ≤ {GATE_UTIL_MAX:.2f} (red muhasebeli, sessiz düşüş yok)")

    # G6: 2x ani trafik (NFR 10.3) — burst varsa red ≤ bütçe & util≤~1.0
    if m["burst_reject_rate"] is not None:
        burst_ok = m["burst_reject_rate"] <= adm["burst_reject_budget"] and m["max_util"] <= GATE_UTIL_MAX
        chk("burst_2x_absorbed", burst_ok,
            f"burst red %{m['burst_reject_rate']*100:.2f} ≤ %{adm['burst_reject_budget']*100:.0f} "
            f"(warm pool + autoscale)")
    else:
        chk("burst_2x_absorbed", True, "burst senaryoda yok (burst_seconds=0)", hard=False)

    # Bilgilendirici (yumuşak): üreteç tasarım yükü kadar gerçekten sürebildi mi (peak fill)
    peak_ratio = m["peak_active"] / m["design_concurrency"] if m["design_concurrency"] else 0.0
    chk("generator_reached_load", peak_ratio >= 0.85,
        f"peak eş zamanlılık {m['peak_active']} = tasarımın %{peak_ratio*100:.0f}'i "
        f"(≥%85 → üreteç tasarım yükünü sürebiliyor)", hard=False)

    hard_pass = all(c["pass"] for c in checks if c["hard"])
    return {"checks": checks, "hard_pass": hard_pass}


# =================================================================================================
# CLI
# =================================================================================================
def _print_run(m: dict, gates: dict) -> None:
    load, fleet = m["load"], m["fleet"]
    print(f"# Yük/performans test ortamı — senaryo='{m['name']}'  (seed={m['seed']})")
    print(f"  yük profili: target {load['target_cps']:.0f} CPS · {load['target_concurrency']:.0f} eş zamanlı · "
          f"ort çağrı {load['mean_call_seconds']:.0f}s (p95 {load['call_p95_seconds']:.0f}s)")
    print(f"  zaman: ramp {load['ramp_seconds']:.0f}s → soak {load['soak_seconds']:.0f}s → "
          f"burst {load['burst_multiplier']:.1f}x×{load['burst_seconds']:.0f}s")
    print(f"  fleet: worker_cap {fleet['worker_capacity']:.0f} · workers {fleet['workers_min']:.0f}–"
          f"{fleet['workers_max']:.0f} · warm {fleet['warm_pool_workers']:.0f} · "
          f"scale {fleet['scale_step_workers']:.0f}w/{fleet['scale_up_seconds']:.0f}s")

    print("\n## Kapasite (NFR 10.3 / Little yasası)")
    print(f"  tasarım eş zamanlılık (max(target, cps×tutma)) = {m['design_concurrency']}  "
          f"[offered cps×tutma = {m['offered_concurrency']}]")
    print(f"  fleet azami kapasite = {m['capacity_max']}  (headroom %{m['headroom_pct']})")
    print(f"  ulaşılan peak eş zamanlılık = {m['peak_active']}  · soak-sonu kapasite = {m['cap_at_soak_end']}")

    print("\n## Trafik & backpressure (FR-RES-014)")
    print(f"  geliş={m['arrivals']}  kabul={m['admitted']}  red={m['rejected']}  "
          f"(toplam red %{m['reject_rate']*100:.2f})")
    print(f"  soak red %{m['soak_reject_rate']*100:.2f}"
          + (f"  · burst red %{m['burst_reject_rate']*100:.2f}" if m['burst_reject_rate'] is not None else "")
          + f"  · gözlenen max util {m['max_util']:.2f}")

    lat, mem = m["latency"], m["mem"]
    print("\n## Yük altında bozulma")
    print(f"  e2e gecikme (ms):   P50={lat['p50']}  P95={lat['p95']}  P99={lat['p99']}  max={lat['max']}")
    print(f"  çağrı-başı bellek:  P50={mem['p50']}  P95={mem['p95']}  P99={mem['p99']}  max={mem['max']} MB")

    print("\n## Kapı (HARD = çıkış kodunu belirler)")
    for c in gates["checks"]:
        mark = "✅" if c["pass"] else "❌"
        tag = "" if c["hard"] else "  (yumuşak)"
        print(f"  {mark} {c['check']:<22} {c['detail']}{tag}")

    verdict = "🟢 GEÇTİ" if gates["hard_pass"] else "🔴 KALDI"
    print(f"\n## VERDICT: {verdict}  (tasarım kapasitesinde yük testi "
          f"{'tamamlanabilir' if gates['hard_pass'] else 'TAMAMLANAMAZ'} — FR-TST-006)")


def cmd_run(args) -> int:
    with open(args.scenario, encoding="utf-8") as f:
        scenario = json.load(f)
    if args.seed is not None:
        scenario["seed"] = args.seed
    m = simulate(scenario)
    gates = evaluate_gates(m)
    _print_run(m, gates)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"sim": m, "gates": gates}, f, ensure_ascii=False, indent=2)
        print(f"\n(JSON yazıldı: {args.json_out})")
    return 0 if gates["hard_pass"] else 1


def cmd_compare(args) -> int:
    print("# Yük senaryosu karşılaştırma (FR-TST-006 / NFR 10.3 / NFR 10.1 / FR-RES-014)\n")
    print(f"  {'senaryo':<22}{'tasarım':>9}{'kapasite':>10}{'peak':>8}{'soakRed%':>10}"
          f"{'lat.P95':>9}{'mem.P95':>9}{'util':>7}  verdict")
    for path in args.scenarios:
        with open(path, encoding="utf-8") as f:
            scenario = json.load(f)
        m = simulate(scenario)
        g = evaluate_gates(m)
        verdict = "🟢" if g["hard_pass"] else "🔴"
        print(f"  {m['name']:<22}{m['design_concurrency']:>9}{m['capacity_max']:>10}"
              f"{m['peak_active']:>8}{m['soak_reject_rate']*100:>9.2f}{m['latency']['p95']:>9.0f}"
              f"{m['mem']['p95']:>9.1f}{m['max_util']:>7.2f}  {verdict}")
    print(f"\n  Kapı: kapasite≥tasarım · soakRed≤bütçe · lat.P95≤{GATE_LAT_P95_MS:.0f} · "
          f"mem.P95≤{GATE_MEM_P95_MB:.0f}MB · util≤{GATE_UTIL_MAX:.2f} (backpressure)")
    return 0


def cmd_schema(_args) -> int:
    print(__doc__)
    return 0


# --- selftest ------------------------------------------------------------------------------------
def _green() -> dict:
    return {"name": "self-green", "seed": 7,
            "load": {"target_cps": 30, "target_concurrency": 3000, "mean_call_seconds": 90,
                     "call_p95_seconds": 200, "ramp_seconds": 40, "soak_seconds": 240,
                     "burst_multiplier": 2.0, "burst_seconds": 30},
            "fleet": {"worker_capacity": 354, "workers_min": 4, "workers_max": 24,
                      "warm_pool_workers": 6, "scale_up_seconds": 20, "scale_step_workers": 4},
            "admission": {"util_threshold": 0.92, "max_cps": 80, "soak_reject_budget": 0.01,
                          "burst_reject_budget": 0.05},
            "under_load": {"base_latency": {"p50": 632, "p95": 863}, "congestion_k": 0.03,
                           "base_call_mem": {"p50": 11.5, "p95": 13.9}, "load_mem_growth": 0.03}}


def _red() -> dict:
    # Kapasite yetersiz (workers_max düşük) + admission>1.0 (graceful değil) + yüksek tıkanma +
    # yük-altı bellek büyümesi → birden çok kapı ELER.
    return {"name": "self-red", "seed": 7,
            "load": {"target_cps": 100, "target_concurrency": 10000, "mean_call_seconds": 120,
                     "call_p95_seconds": 280, "ramp_seconds": 30, "soak_seconds": 240,
                     "burst_multiplier": 2.0, "burst_seconds": 30},
            "fleet": {"worker_capacity": 200, "workers_min": 4, "workers_max": 20,
                      "warm_pool_workers": 0, "scale_up_seconds": 90, "scale_step_workers": 2},
            "admission": {"util_threshold": 1.05, "max_cps": 60, "soak_reject_budget": 0.01,
                          "burst_reject_budget": 0.05},
            "under_load": {"base_latency": {"p50": 760, "p95": 1050}, "congestion_k": 0.25,
                           "base_call_mem": {"p50": 13.5, "p95": 15.5}, "load_mem_growth": 0.25}}


def cmd_selftest(_args) -> int:
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("## selftest — yük test ortamı invariant'ları (credential'sız, deterministik)\n")

    # S1: Lognormal kalibrasyonu (tutma süresi)
    c = LogNormalComponent(90.0, 200.0)
    rng = random.Random(1)
    xs = sorted(c.sample(rng) for _ in range(50000))
    check(f"S1 lognormal median≈90 ({percentile(xs,50):.0f})", abs(percentile(xs, 50) - 90) < 4)
    check(f"S1 lognormal p95≈200 ({percentile(xs,95):.0f})", abs(percentile(xs, 95) - 200) < 10)

    # S2: Poisson ortalaması ≈ lam (büyük örneklemde)
    rp = random.Random(2)
    vals = [poisson(rp, 30.0) for _ in range(20000)]
    mean = sum(vals) / len(vals)
    check(f"S2 Poisson ort≈30 ({mean:.1f})", abs(mean - 30.0) < 0.8)
    check("S2 Poisson(0)=0", poisson(rp, 0.0) == 0)

    # S3: percentile monotonluğu
    s = [float(i) for i in range(101)]
    check("S3 percentile monoton", percentile(s, 50) < percentile(s, 95) < percentile(s, 99))

    # S4: Green senaryo → tüm HARD kapılar geçer
    mg = simulate(_green())
    gg = evaluate_gates(mg)
    check("S4 green hard_pass", gg["hard_pass"])
    check(f"S4 green kapasite≥tasarım ({mg['capacity_max']}≥{mg['design_concurrency']})",
          mg["capacity_max"] >= mg["design_concurrency"])
    check(f"S4 green lat.P95≤1200 ({mg['latency']['p95']:.0f})", mg["latency"]["p95"] <= GATE_LAT_P95_MS)
    check(f"S4 green mem.P95≤15 ({mg['mem']['p95']:.1f})", mg["mem"]["p95"] <= GATE_MEM_P95_MB)
    check(f"S4 green util≤1.02 ({mg['max_util']:.2f})", mg["max_util"] <= GATE_UTIL_MAX)

    # S5: Red senaryo → HARD kapı KALDI (birden çok kapı)
    mr = simulate(_red())
    gr = evaluate_gates(mr)
    check("S5 red hard KALDI", not gr["hard_pass"])
    cap_chk = next(c for c in gr["checks"] if c["check"] == "capacity_adequate")
    bp_chk = next(c for c in gr["checks"] if c["check"] == "backpressure_graceful")
    mem_chk = next(c for c in gr["checks"] if c["check"] == "resource_under_load")
    check("S5 red kapasite kapısı fail", not cap_chk["pass"])
    check("S5 red backpressure kapısı fail (admission≥1.0)", not bp_chk["pass"])
    check("S5 red yük-altı bellek kapısı fail", not mem_chk["pass"])

    # S6: Little yasası — offered_concurrency = cps × tutma
    check(f"S6 Little: offered={mg['offered_concurrency']} = 30×90",
          mg["offered_concurrency"] == int(round(30 * 90)))

    # S7: Determinizm — aynı senaryo+seed iki kez → birebir aynı sonuç
    m1 = simulate(_green())
    m2 = simulate(_green())
    check("S7 determinizm (latency+mem+trafik birebir)",
          m1["latency"] == m2["latency"] and m1["mem"] == m2["mem"]
          and m1["admitted"] == m2["admitted"] and m1["rejected"] == m2["rejected"])

    # S8: Farklı seed → farklı geliş örneklemi (ama yakın red oranı)
    g2 = _green(); g2["seed"] = 99
    m3 = simulate(g2)
    check("S8 farklı seed farklı örneklem", m3["arrivals"] != m1["arrivals"])

    # S9: Backpressure korur — offered ≫ kapasite olsa bile util≤~1.0 (graceful, admission<1.0)
    over = _green()
    over["load"] = dict(over["load"], target_cps=200, soak_seconds=180, burst_seconds=0)
    mo = simulate(over)
    check(f"S9 aşırı yükte util tavanlı ({mo['max_util']:.2f}≤1.02)", mo["max_util"] <= GATE_UTIL_MAX)
    check(f"S9 aşırı yükte red>0 (graceful muhasebe, {mo['rejected']}>0)", mo["rejected"] > 0)

    # S10: Kapasite ↑ (workers_max) → red oranı ↓ (daha çok yük emilir)
    g_small = _green(); g_small["fleet"] = dict(g_small["fleet"], workers_max=10)
    g_small["load"] = dict(g_small["load"], target_cps=60, burst_seconds=0)
    g_big = _green(); g_big["fleet"] = dict(g_big["fleet"], workers_max=40)
    g_big["load"] = dict(g_big["load"], target_cps=60, burst_seconds=0)
    check("S10 kapasite↑ → red↓",
          simulate(g_big)["reject_rate"] <= simulate(g_small)["reject_rate"])

    # S11: Tıkanma — congestion_k ↑ → yük-altı gecikme P95 ↑
    g_lo = _green(); g_lo["under_load"] = dict(g_lo["under_load"], congestion_k=0.01)
    g_hi = _green(); g_hi["under_load"] = dict(g_hi["under_load"], congestion_k=0.30)
    check("S11 congestion_k↑ → lat.P95↑",
          simulate(g_hi)["latency"]["p95"] > simulate(g_lo)["latency"]["p95"])

    # S12: Yük-altı bellek büyümesi — load_mem_growth ↑ → mem.P95 ↑
    g_m0 = _green(); g_m0["under_load"] = dict(g_m0["under_load"], load_mem_growth=0.0)
    g_m1 = _green(); g_m1["under_load"] = dict(g_m1["under_load"], load_mem_growth=0.20)
    check("S12 load_mem_growth↑ → mem.P95↑",
          simulate(g_m1)["mem"]["p95"] >= simulate(g_m0)["mem"]["p95"])

    print(f"\n{'='*60}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print(f"SELFTEST GEÇTİ — {12} grup invariant doğrulandı")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Yük/performans test ortamı — sentetik çağrı üreteci (WBS 0.4.8, FR-TST-006)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Bir senaryoyu simüle et → kapasite/CPS/gecikme/kaynak + kapı")
    pr.add_argument("--scenario", required=True, help="scenarios/load-*.json")
    pr.add_argument("--seed", type=int, help="determinizm tohumu override")
    pr.add_argument("--json-out", help="simülasyon+kapı JSON çıktısı")
    pr.set_defaults(func=cmd_run)

    pc = sub.add_parser("compare", help="Birden çok senaryoyu tablo halinde karşılaştır")
    pc.add_argument("scenarios", nargs="+", help="scenarios/load-*.json ...")
    pc.set_defaults(func=cmd_compare)

    ps = sub.add_parser("selftest", help="Kapı/Little/Poisson/determinizm invariant'ları (credential'sız)")
    ps.set_defaults(func=cmd_selftest)

    psc = sub.add_parser("schema", help="Senaryo JSON şemasını yaz")
    psc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
