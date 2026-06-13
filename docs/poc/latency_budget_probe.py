#!/usr/bin/env python3
"""latency_budget_probe.py — Gecikme bütçesi ölçümü (WBS 0.3.2, →NFR 10.1 / SAD §20).

Amaç: 0.3.1 E2E inbound PoC'unun **yumuşak** bıraktığı gecikme kapısını **HARD** kapıya çevirmek.
0.3.1 sanal saat ile tek-noktalı (deterministik) bir gecikme raporlar (P50=P95=P99 dejenere);
gerçek bir sesli sistemde her bileşen (endpointing, STT, LLM, TTS, ağ, …) tur-tur **dağılır**.
Bu probe SAD §20 bütçe kalemlerini birer **dağılım** olarak modelleyip Monte-Carlo örnekleme ile
uç-uca **end-of-utterance → ilk agent sesi** gecikmesinin P50/P95/P99'unu üretir ve NFR 10.1
hedeflerine karşı **kapı** uygular. Barge-in TTS kesme gecikmesi ayrı bir dağılım olarak ölçülür.

Tasarım ilkeleri (CLAUDE.md + 0.2.x/0.3.1 hattıyla aynı disiplin):
- **Vendor-neutral (ADR-002):** Bileşen gecikmeleri **sağlayıcı seçmez**; profil JSON'ları SAD §20
  bantlarından türetilmiş **mühendislik dağılımlarıdır**. Canlı PoC'ta (0.3.x) aynı profil yapısı
  gerçek ölçümlerle (provider telemetri) doldurulur; kapı mantığı değişmez.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / *_eval_probe.py / e2e_inbound_poc.py disiplini).
- **Deterministik / tekrarlanabilir:** Örnekleme **tohumlanmış** `random.Random(seed)` iledir; aynı
  profil + aynı seed → aynı percentile (CI). Gerçek `time`/ağ/sır YOK.
- **Kapsam ayrımı:** 0.3.2 = **gecikme dağılımı + barge-in kesme kapısı**. Density 0.3.3,
  medya-konumu/ADR-009 0.3.4, hot-path dil 0.3.5. Bu probe gecikmeyi ölçer; density/CPU ölçmez.

Metrik tanımı (NFR 10.1 / BRD §10.1 yetkili kapı):
  **end-of-utterance → ilk agent sesi** = kullanıcı konuşmayı bıraktığı an → agent'ın ilk ses
  paketinin çalındığı an. Bu, SAD §20 bütçe tablosunun **tüm kalemlerini** (endpointing VAD karar
  gecikmesi dahil) kapsar: endpointing + STT final + orchestrator + (RAG) + (tool) + LLM first
  token + TTS first byte + ağ/medya. Endpointing dahildir çünkü kullanıcı durduktan sonra sistemin
  bunu *algılaması* da algılanan yanıt süresinin parçasıdır (SAD §20 toplam satırı bu kalemi içerir).
  [Not: 0.3.1 harness'ı eou'yu endpointing *sonrasına* koyup gecikmeyi illüstratif/yumuşak
   raporlamıştı; 0.3.2 yetkili NFR 10.1 metriğine hizalanmak için tam zinciri ölçer.]

Modlar:
  measure   — Bir profil (samples/latency-*.json) üzerinde N tur örnekle → P50/P95/P99 + barge-in
              + bileşen atfı + NFR 10.1 kapı verdict'i (çıkış kodu: 0=geçti, 1=kaldı).
  compare   — Birden çok profili tablo halinde karşılaştır (bilgilendirici; çıkış kodu 0).
  selftest  — Dahili deterministik profillerle kapı/percentile/determinizm invariant'ları (CI).
  schema    — Profil JSON şemasını ve bileşen anahtarlarını yazar.

Profil JSON şeması — `samples/latency-*.json`:
{
  "name": "green-baseline",
  "samples": 20000,              # Monte-Carlo tur sayısı (varsayılan 20000)
  "seed": 42,                    # determinizm tohumu (varsayılan 42)
  "mix": {                       # tur-başına olasılıklar (SAD §20 "çoğu turda atlanır" notu)
     "small_tier_share": 0.70,   # LLM küçük-tier payı (≥0.60 hedef, FR-RES-005/NFR 10.2)
     "rag_prob": 0.25,           # RAG retrieval olasılığı
     "tool_prob": 0.20,          # tool (ACT) olasılığı
     "tts_cache_hit_prob": 0.50  # TTS cache hit → first byte ~0 (FR-TTS-010)
  },
  "components": {                # her kalem: lognormal(median, p95) — sağ-çarpık gecikme
     "endpointing":      {"p50": 150, "p95": 210},
     "stt_final":        {"p50": 110, "p95": 175},
     "orchestrator":     {"p50": 8,   "p95": 25},
     "rag":              {"p50": 130, "p95": 195},
     "llm_first_small":  {"p50": 200, "p95": 340},
     "llm_first_large":  {"p50": 300, "p95": 390},
     "tts_first_byte":   {"p50": 110, "p95": 180},
     "tts_cached":       {"p50": 5,   "p95": 12},
     "network":          {"p50": 50,  "p95": 90},
     "tool":             {"p50": 75,  "p95": 96},
     "barge_in_cut":     {"p50": 70,  "p95": 150}
  }
}
Her bileşen `{p50, p95}` ile bir **lognormal** dağılıma kalibre edilir (median=p50, p95=p95);
p50==p95 ise sabit. Eksik bileşen SAD §20 orta-nokta varsayılanını alır.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys

# --- NFR 10.1 / BRD §10.1 kapı hedefleri (yetkili) -----------------------------------------------
GATE_P50_MS = 700.0        # end-of-utterance → ilk agent sesi P50 ≤ 700
GATE_P95_MS = 1200.0       # P95 ≤ 1.200 (SAD §20 toplam)
GATE_P99_MS = 2000.0       # P99 ≤ 2.000
GATE_BARGEIN_P95_MS = 200.0    # barge-in sonrası TTS kesme P95 ≤ 200 (SAD §6.1)
GATE_TOOL_P95_MS = 100.0       # basit tool çağrısı platform overhead P95 ≤ 100

Z95 = 1.6448536269514722       # standart normal 95. percentil (lognormal kalibrasyonu)

# --- SAD §20 bileşen bantları (P95 tavanı; bileşen-içi yumuşak flag + atıf) -----------------------
SAD20_P95_BAND = {
    "endpointing": 250.0, "stt_final": 200.0, "orchestrator": 50.0, "rag": 200.0,
    "llm_first_small": 400.0, "llm_first_large": 400.0, "tts_first_byte": 200.0,
    "tts_cached": 0.0, "network": 100.0, "tool": 100.0, "barge_in_cut": 200.0,
}

# --- Bileşen varsayılanları (SAD §20 orta-nokta; profil override eder) ----------------------------
DEFAULT_COMPONENTS = {
    "endpointing":     {"p50": 150.0, "p95": 230.0},
    "stt_final":       {"p50": 130.0, "p95": 190.0},
    "orchestrator":    {"p50": 8.0,   "p95": 30.0},
    "rag":             {"p50": 140.0, "p95": 195.0},
    "llm_first_small": {"p50": 220.0, "p95": 360.0},
    "llm_first_large": {"p50": 320.0, "p95": 395.0},
    "tts_first_byte":  {"p50": 120.0, "p95": 190.0},
    "tts_cached":      {"p50": 5.0,   "p95": 12.0},
    "network":         {"p50": 60.0,  "p95": 95.0},
    "tool":            {"p50": 80.0,  "p95": 98.0},
    "barge_in_cut":    {"p50": 70.0,  "p95": 150.0},
}
DEFAULT_MIX = {"small_tier_share": 0.65, "rag_prob": 0.25, "tool_prob": 0.20,
               "tts_cache_hit_prob": 0.50}


# =================================================================================================
# Lognormal bileşen modeli (median + p95 → mu, sigma)
# =================================================================================================
class LogNormalComponent:
    """Sağ-çarpık gecikme bileşeni; median=p50, 95. percentil=p95'e kalibre lognormal.

    X = exp(mu + sigma·Z),  Z~N(0,1);  median = exp(mu),  p95 = exp(mu + Z95·sigma).
    p50==p95 ise sigma=0 → sabit (ör. cache, orchestrator bellek-içi).
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
# Percentile (0.3.1 e2e_inbound_poc._percentile ile aynı lineer interpolasyon yöntemi)
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
        "p50": round(percentile(s, 50), 1),
        "p95": round(percentile(s, 95), 1),
        "p99": round(percentile(s, 99), 1),
        "mean": round(sum(s) / len(s), 1) if s else float("nan"),
        "max": round(s[-1], 1) if s else float("nan"),
    }


# =================================================================================================
# Monte-Carlo gecikme bütçesi ölçümü
# =================================================================================================
def build_components(profile: dict) -> dict:
    comps = {}
    src = dict(DEFAULT_COMPONENTS)
    src.update(profile.get("components", {}))
    for name, spec in src.items():
        comps[name] = LogNormalComponent(name, float(spec["p50"]), float(spec["p95"]))
    return comps


def measure_profile(profile: dict) -> dict:
    """Profili Monte-Carlo örnekle → uç-uca + barge-in + bileşen-atfı dağılımları."""
    n = int(profile.get("samples", 20000))
    seed = int(profile.get("seed", 42))
    mix = dict(DEFAULT_MIX)
    mix.update(profile.get("mix", {}))
    comps = build_components(profile)
    rng = random.Random(seed)

    e2e: list[float] = []                  # end-of-utterance → ilk agent sesi (zorunlu kalemler + opsiyonel)
    tool_samples: list[float] = []         # yalnız tool çalışan turlar (tool overhead kapısı)
    # bileşen-atfı: her kalemin tur-içi katkı örnekleri (aktif olduğu turlarda)
    contrib: dict[str, list[float]] = {k: [] for k in
                                       ("endpointing", "stt_final", "orchestrator", "rag",
                                        "llm_first", "tts", "network", "tool")}

    for _ in range(n):
        endpointing = comps["endpointing"].sample(rng)
        stt = comps["stt_final"].sample(rng)
        orch = comps["orchestrator"].sample(rng)
        net = comps["network"].sample(rng)

        # LLM tier mix (FR-LLM-013 / FR-RES-005)
        if rng.random() < mix["small_tier_share"]:
            llm = comps["llm_first_small"].sample(rng)
        else:
            llm = comps["llm_first_large"].sample(rng)

        # TTS: cache hit → ~0 (FR-TTS-010), aksi first byte
        if rng.random() < mix["tts_cache_hit_prob"]:
            tts = comps["tts_cached"].sample(rng)
        else:
            tts = comps["tts_first_byte"].sample(rng)

        # RAG (çoğu turda atlanır — SAD §20)
        rag = comps["rag"].sample(rng) if rng.random() < mix["rag_prob"] else 0.0

        # Tool / ACT (idempotent çağrı overhead'i — FR-TOOL-003)
        if rng.random() < mix["tool_prob"]:
            tool = comps["tool"].sample(rng)
            tool_samples.append(tool)
        else:
            tool = 0.0

        total = endpointing + stt + orch + net + llm + tts + rag + tool
        e2e.append(total)

        contrib["endpointing"].append(endpointing)
        contrib["stt_final"].append(stt)
        contrib["orchestrator"].append(orch)
        contrib["network"].append(net)
        contrib["llm_first"].append(llm)
        contrib["tts"].append(tts)
        if rag:
            contrib["rag"].append(rag)
        if tool:
            contrib["tool"].append(tool)

    # Barge-in kesme — ayrı dağılım (her örnek bir barge-in olayı)
    rng_bi = random.Random(seed + 1)
    bargein = [comps["barge_in_cut"].sample(rng_bi) for _ in range(n)]

    return {
        "name": profile.get("name", "profile"),
        "samples": n, "seed": seed, "mix": mix,
        "e2e": _stats(e2e),
        "bargein": _stats(bargein),
        "tool": _stats(tool_samples) if tool_samples else None,
        "contrib": {k: _stats(v) for k, v in contrib.items() if v},
        "mean_total": round(sum(e2e) / len(e2e), 1),
    }


# =================================================================================================
# NFR 10.1 kapı değerlendirmesi (HARD = çıkış kodunu belirler)
# =================================================================================================
def evaluate_gates(m: dict) -> dict:
    checks = []

    def chk(key, ok, detail, hard=True):
        checks.append({"check": key, "pass": bool(ok), "detail": detail, "hard": hard})

    e = m["e2e"]
    bi = m["bargein"]
    tool = m["tool"]

    chk("e2e_p50", e["p50"] <= GATE_P50_MS, f"P50 {e['p50']}ms ≤ {GATE_P50_MS:.0f}ms")
    chk("e2e_p95", e["p95"] <= GATE_P95_MS, f"P95 {e['p95']}ms ≤ {GATE_P95_MS:.0f}ms")
    chk("e2e_p99", e["p99"] <= GATE_P99_MS, f"P99 {e['p99']}ms ≤ {GATE_P99_MS:.0f}ms")
    chk("bargein_p95", bi["p95"] <= GATE_BARGEIN_P95_MS,
        f"barge-in P95 {bi['p95']}ms ≤ {GATE_BARGEIN_P95_MS:.0f}ms")
    if tool is not None:
        chk("tool_overhead_p95", tool["p95"] <= GATE_TOOL_P95_MS,
            f"tool P95 {tool['p95']}ms ≤ {GATE_TOOL_P95_MS:.0f}ms")
    else:
        chk("tool_overhead_p95", True, "tool turu yok (mix.tool_prob=0)", hard=False)

    # Bileşen-içi SAD §20 bant flag'i (YUMUŞAK — atıf/erken-uyarı, çıkış kodunu belirlemez)
    soft = []
    for name, st in m["contrib"].items():
        band = SAD20_P95_BAND.get(name)
        # llm_first ve tts contrib'i tier/cache karışımı; bant için en gevşek tavanı kullan
        if name == "llm_first":
            band = SAD20_P95_BAND["llm_first_large"]
        elif name == "tts":
            band = SAD20_P95_BAND["tts_first_byte"]
        if band and st["p95"] > band:
            soft.append(f"{name} P95 {st['p95']}>{band:.0f}")

    hard_pass = all(c["pass"] for c in checks if c["hard"])
    return {"checks": checks, "hard_pass": hard_pass, "soft_band_flags": soft}


# =================================================================================================
# Bileşen atfı (bütçenin neresi yer kaplıyor — headroom analizi)
# =================================================================================================
def attribution_rows(m: dict) -> list[dict]:
    # Grand total = ort. uç-uca × tur sayısı (koşullu kalemleri — rag/tool — doğru ağırlıklar).
    grand_total = (m["mean_total"] or 1.0) * m["samples"]
    rows = []
    label = {"endpointing": "Endpointing (VAD)", "stt_final": "STT final",
             "orchestrator": "Orchestrator+policy", "rag": "RAG retrieval (varsa)",
             "llm_first": "LLM first token", "tts": "TTS first byte", "network": "Ağ/medya",
             "tool": "Tool overhead (varsa)"}
    order = ["endpointing", "stt_final", "orchestrator", "rag", "llm_first", "tts",
             "network", "tool"]
    for k in order:
        if k not in m["contrib"]:
            continue
        st = m["contrib"][k]
        # Koşullu kalemde (rag/tool) toplam katkı = koşullu ort. × aktif tur sayısı (n<samples).
        comp_total = st["mean"] * st["n"]
        rows.append({"component": label.get(k, k), "p50": st["p50"], "p95": st["p95"],
                     "mean": st["mean"], "share_pct": round(100.0 * comp_total / grand_total, 1)})
    return rows


# =================================================================================================
# CLI
# =================================================================================================
def _print_measure(m: dict, gates: dict) -> None:
    e, bi = m["e2e"], m["bargein"]
    print(f"# Gecikme bütçesi ölçümü — profil='{m['name']}'  "
          f"(N={m['samples']} tur, seed={m['seed']})")
    print(f"  metrik: end-of-utterance → ilk agent sesi (SAD §20 tam zincir) | "
          f"mix: small-tier={m['mix']['small_tier_share']:.0%} "
          f"rag={m['mix']['rag_prob']:.0%} tool={m['mix']['tool_prob']:.0%} "
          f"tts-cache={m['mix']['tts_cache_hit_prob']:.0%}")

    print("\n## Uç-uca gecikme dağılımı (ms)")
    print(f"  P50={e['p50']}  P95={e['p95']}  P99={e['p99']}  mean={e['mean']}  max={e['max']}")
    print(f"  barge-in kesme: P50={bi['p50']}  P95={bi['p95']}  P99={bi['p99']}  max={bi['max']}")
    if m["tool"]:
        t = m["tool"]
        print(f"  tool overhead:  P50={t['p50']}  P95={t['p95']}  P99={t['p99']}  (n={t['n']})")

    print("\n## Bileşen atfı (bütçe kırılımı — ort. katkı)")
    print(f"  {'bileşen':<24}{'P50':>8}{'P95':>9}{'ort':>8}{'pay%':>8}")
    for r in attribution_rows(m):
        print(f"  {r['component']:<24}{r['p50']:>7.1f}{r['p95']:>9.1f}"
              f"{r['mean']:>8.1f}{r['share_pct']:>7.1f}%")

    print("\n## NFR 10.1 kapı (HARD = çıkış kodunu belirler)")
    for c in gates["checks"]:
        mark = "✅" if c["pass"] else "❌"
        tag = "" if c["hard"] else "  (yumuşak)"
        print(f"  {mark} {c['check']:<20} {c['detail']}{tag}")
    if gates["soft_band_flags"]:
        print(f"  ⚠ SAD §20 bant aşımı (yumuşak): {'; '.join(gates['soft_band_flags'])}")
    else:
        print("  ✓ Tüm bileşenler SAD §20 P95 bandı içinde (yumuşak)")

    verdict = "🟢 GEÇTİ" if gates["hard_pass"] else "🔴 KALDI"
    print(f"\n## VERDICT: {verdict}  (NFR 10.1 gecikme bütçesi "
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
    print("# Gecikme bütçesi karşılaştırma (NFR 10.1)\n")
    print(f"  {'profil':<22}{'P50':>7}{'P95':>8}{'P99':>8}{'barge.P95':>11}"
          f"{'tool.P95':>10}  verdict")
    any_pass = False
    for path in args.profiles:
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        if args.samples:
            profile["samples"] = args.samples
        m = measure_profile(profile)
        g = evaluate_gates(m)
        any_pass = any_pass or g["hard_pass"]
        e, bi = m["e2e"], m["bargein"]
        tool_p95 = f"{m['tool']['p95']:.0f}" if m["tool"] else "—"
        verdict = "🟢" if g["hard_pass"] else "🔴"
        print(f"  {m['name']:<22}{e['p50']:>7.0f}{e['p95']:>8.0f}{e['p99']:>8.0f}"
              f"{bi['p95']:>11.0f}{tool_p95:>10}  {verdict}")
    print(f"\n  Hedef: P50≤{GATE_P50_MS:.0f} · P95≤{GATE_P95_MS:.0f} · P99≤{GATE_P99_MS:.0f} · "
          f"barge-in P95≤{GATE_BARGEIN_P95_MS:.0f} · tool P95≤{GATE_TOOL_P95_MS:.0f} (NFR 10.1)")
    return 0


def cmd_schema(_args) -> int:
    print(__doc__)
    return 0


# --- selftest ------------------------------------------------------------------------------------
def _green() -> dict:
    return {"name": "self-green", "samples": 20000, "seed": 7,
            "mix": {"small_tier_share": 0.70, "rag_prob": 0.25, "tool_prob": 0.20,
                    "tts_cache_hit_prob": 0.50},
            "components": {
                "endpointing": {"p50": 140, "p95": 200}, "stt_final": {"p50": 100, "p95": 165},
                "orchestrator": {"p50": 8, "p95": 22}, "rag": {"p50": 130, "p95": 190},
                "llm_first_small": {"p50": 190, "p95": 330},
                "llm_first_large": {"p50": 290, "p95": 385},
                "tts_first_byte": {"p50": 100, "p95": 170}, "tts_cached": {"p50": 5, "p95": 12},
                "network": {"p50": 45, "p95": 85}, "tool": {"p50": 75, "p95": 96},
                "barge_in_cut": {"p50": 70, "p95": 150}}}


def _red() -> dict:
    return {"name": "self-red", "samples": 20000, "seed": 7,
            "mix": {"small_tier_share": 0.20, "rag_prob": 0.60, "tool_prob": 0.50,
                    "tts_cache_hit_prob": 0.10},
            "components": {
                "endpointing": {"p50": 240, "p95": 360}, "stt_final": {"p50": 190, "p95": 330},
                "orchestrator": {"p50": 40, "p95": 95}, "rag": {"p50": 190, "p95": 360},
                "llm_first_small": {"p50": 280, "p95": 520},
                "llm_first_large": {"p50": 430, "p95": 680},
                "tts_first_byte": {"p50": 200, "p95": 360}, "tts_cached": {"p50": 5, "p95": 12},
                "network": {"p50": 95, "p95": 190}, "tool": {"p50": 140, "p95": 185},
                "barge_in_cut": {"p50": 240, "p95": 360}}}


def cmd_selftest(_args) -> int:
    failures = []

    def check(name, cond):
        print(f"  {'✅' if cond else '❌'} {name}")
        if not cond:
            failures.append(name)

    print("## selftest — gecikme bütçesi invariant'ları (credential'sız, deterministik)\n")

    # S1: Lognormal kalibrasyonu — örneklem median/p95 hedeflere yakın
    c = LogNormalComponent("t", 200.0, 400.0)
    rng = random.Random(1)
    xs = sorted(c.sample(rng) for _ in range(50000))
    med = percentile(xs, 50)
    p95 = percentile(xs, 95)
    check(f"S1 lognormal median≈200 ({med:.0f})", abs(med - 200) < 8)
    check(f"S1 lognormal p95≈400 ({p95:.0f})", abs(p95 - 400) < 16)

    # S2: p50==p95 → sabit (sigma=0)
    cc = LogNormalComponent("const", 8.0, 8.0)
    check("S2 p50==p95 sabit", cc.sigma == 0.0 and cc.sample(random.Random(0)) == 8.0)

    # S3: percentile monotonluğu
    s = [float(i) for i in range(101)]
    check("S3 percentile monoton", percentile(s, 50) < percentile(s, 95) < percentile(s, 99))

    # S4: Green profil → tüm HARD kapılar geçer
    mg = measure_profile(_green())
    gg = evaluate_gates(mg)
    check("S4 green hard_pass", gg["hard_pass"])
    check(f"S4 green P95≤1200 ({mg['e2e']['p95']:.0f})", mg["e2e"]["p95"] <= GATE_P95_MS)
    check(f"S4 green P50≤700 ({mg['e2e']['p50']:.0f})", mg["e2e"]["p50"] <= GATE_P50_MS)
    check(f"S4 green barge-in P95≤200 ({mg['bargein']['p95']:.0f})",
          mg["bargein"]["p95"] <= GATE_BARGEIN_P95_MS)

    # S5: Red profil → HARD kapı KALDI (P95/P99 + barge-in + tool)
    mr = measure_profile(_red())
    gr = evaluate_gates(mr)
    check("S5 red hard KALDI", not gr["hard_pass"])
    p95_fail = next(c for c in gr["checks"] if c["check"] == "e2e_p95")
    bi_fail = next(c for c in gr["checks"] if c["check"] == "bargein_p95")
    tool_fail = next(c for c in gr["checks"] if c["check"] == "tool_overhead_p95")
    check("S5 red P95 kapısı fail", not p95_fail["pass"])
    check("S5 red barge-in kapısı fail", not bi_fail["pass"])
    check("S5 red tool overhead kapısı fail", not tool_fail["pass"])

    # S6: Percentile sıralaması P50≤P95≤P99
    check("S6 P50≤P95≤P99 (green)",
          mg["e2e"]["p50"] <= mg["e2e"]["p95"] <= mg["e2e"]["p99"])

    # S7: Determinizm — aynı profil+seed iki kez → birebir aynı percentile
    m1 = measure_profile(_green())
    m2 = measure_profile(_green())
    check("S7 determinizm (P50/P95/P99 birebir)",
          m1["e2e"] == m2["e2e"] and m1["bargein"] == m2["bargein"])

    # S8: Farklı seed → farklı örneklem (ama yakın percentile)
    g2 = _green(); g2["seed"] = 99
    m3 = measure_profile(g2)
    check("S8 farklı seed farklı örneklem", m3["e2e"]["max"] != m1["e2e"]["max"])
    check("S8 farklı seed yakın P95 (±5%)",
          abs(m3["e2e"]["p95"] - m1["e2e"]["p95"]) / m1["e2e"]["p95"] < 0.05)

    # S9: Bileşen atfı payları toplam ≈ %100
    rows = attribution_rows(mg)
    share_sum = sum(r["share_pct"] for r in rows)
    check(f"S9 atıf payları ≈%100 ({share_sum:.0f}%)", abs(share_sum - 100.0) < 2.0)

    # S10: tool_prob=0 → tool kapısı yumuşak (n/a), hard_pass'i bozmaz
    g0 = _green(); g0["mix"]["tool_prob"] = 0.0
    m0 = measure_profile(g0)
    gx = evaluate_gates(m0)
    tool_chk = next(c for c in gx["checks"] if c["check"] == "tool_overhead_p95")
    check("S10 tool_prob=0 → tool kapısı yumuşak", not tool_chk["hard"] and tool_chk["pass"])
    check("S10 tool yokken yine hard_pass", gx["hard_pass"])

    # S11: small_tier_share ↑ → P95 ↓ (küçük model daha hızlı, FR-LLM-013)
    g_small = _green(); g_small["mix"]["small_tier_share"] = 0.95
    g_large = _green(); g_large["mix"]["small_tier_share"] = 0.20
    check("S11 küçük-tier payı↑ → P95↓",
          measure_profile(g_small)["e2e"]["p95"] < measure_profile(g_large)["e2e"]["p95"])

    print(f"\n{'='*60}")
    if failures:
        print(f"SELFTEST KALDI — {len(failures)} başarısız: {failures}")
        return 1
    print(f"SELFTEST GEÇTİ — {11} grup invariant doğrulandı")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Gecikme bütçesi ölçümü (WBS 0.3.2, NFR 10.1/SAD §20)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("measure", help="Bir profili Monte-Carlo ölç → P50/P95/P99 + kapı")
    pm.add_argument("--profile", required=True, help="samples/latency-*.json")
    pm.add_argument("--samples", type=int, help="tur sayısı override")
    pm.add_argument("--seed", type=int, help="determinizm tohumu override")
    pm.add_argument("--json-out", help="ölçüm+kapı JSON çıktısı")
    pm.set_defaults(func=cmd_measure)

    pc = sub.add_parser("compare", help="Birden çok profili tablo halinde karşılaştır")
    pc.add_argument("profiles", nargs="+", help="samples/latency-*.json ...")
    pc.add_argument("--samples", type=int, help="tur sayısı override")
    pc.set_defaults(func=cmd_compare)

    ps = sub.add_parser("selftest", help="Kapı/percentile/determinizm invariant'ları (credential'sız)")
    ps.set_defaults(func=cmd_selftest)

    psc = sub.add_parser("schema", help="Profil JSON şemasını yaz")
    psc.set_defaults(func=cmd_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
