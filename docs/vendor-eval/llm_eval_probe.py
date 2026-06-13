#!/usr/bin/env python3
"""llm_eval_probe.py — LLM sağlayıcı değerlendirme hattı (WBS 0.2.4, →FR-LLM-001/012).

Amaç: ≥2 LLM sağlayıcısını (her biri **küçük + büyük tier** ile) **sağlayıcı-nötr (ADR-002)**,
ölçüt-tabanlı ve tekrarlanabilir biçimde değerlendirmek. Görev başlığındaki üç birincil boyut +
tiering:
- **First-token gecikmesi (TTFT, FR-LLM-004):** complete isteği → ilk token; **SAD §20 LLM kalemi
  P95 ~200–400 ms** (yeşil ≤ 200 ms üst kapı ≤ 400 ms) kapısı. Streaming başlangıç gecikmesi uçtan
  uca gecikme bütçesinin (NFR 10.1: P95 ≤ 1.200 ms) en büyük tek kalemidir.
- **Model tiering — küçük/büyük (FR-LLM-013):** Sağlayıcı hem küçük/hızlı hem büyük model sunmalı;
  **küçük tier daha hızlı** (SAD §20: "küçük model daha hızlı"). Küçük-tier TTFT ayrı kapıdan geçer
  (P95 ≤ 200 ms). Küçük-modelle karşılanan tur oranı ≥ %60 hedefi (SR-DEN-005) router metriğidir,
  burada **raporlanır** (kapı değil; runtime 5.3).
- **"No-train" / no-log endpoint (FR-LLM-012, FR-KB-010):** Tenant verisi eğitime kapalı varsayılan;
  `noTrain=true` + `dataRetention ∈ {NONE, EPHEMERAL}`. Regüle/AB/UK tenant'ları için **zorunlu** —
  knock-out uygunluk kapısı.
- **Bölgesel endpoint / residency (NFR 10.7):** Sağlayıcı, veriyi tenant home-region'da işleyen
  bölgesel endpoint sunmalı (region pinning). Knock-out uygunluk kapısı.

Ek ölçütler:
- **Streaming token sürekliliği (FR-LLM-004):** token akışında uzun boşluk (stall) downstream TTS'i
  aç bırakır (ölü hava). Inter-token gecikme + stall sayısı + tokens/sn (TTS dead-air'in LLM analoğu).
- **Tool-call doğruluğu (FR-LLM-008):** kritik işlemler serbest metin yerine schema-doğrulamalı tool
  çağrısı; tool gereken turlarda geçerli-yapısal tool-call oranı (soft).
- **Görev kalitesi (FR-LLM-001/003):** yanıt doğruluğu/görev başarısı (0–1); **en-kötü-dil** (EN+TR)
  üzerinden kapı (zayıf dili genel ortalama maskelemesin — STT WER / TTS MOS ile aynı disiplin).

Tasarım ilkeleri (CLAUDE.md):
- **Vendor-neutral:** Araç hiçbir sağlayıcı/modeli seçmez; ölçüt-tabanlı sonuç üretir. Nihai seçim 0.2.6'da.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / media_latency_probe.py / stt_eval_probe.py /
  tts_eval_probe.py disiplini).
- **Credential-free self-test:** `selftest` ve `samples/*.json` ile gerçek LLM credential olmadan
  uçtan uca koşar (CI'da). Gerçek sağlayıcı çıktısı yalnız dışarıdan örnek JSON ile verilir; sır
  repoya YAZILMAZ (yalnız ortam değişkeni / endpoint ile canlı toplama, 0.3.x PoC).

> **Kalite notu (vendor-neutral + tekrarlanabilirlik):** Görev kalitesi (yanıt doğruluğu) algısal/göreve
> bağlıdır. Bu harness kaliteyi sağlayıcıya özel değil, **dış girdi** (kalibre değerlendirme seti / LLM-
> judge skoru) olarak alır; kapı/karşılaştırma mantığını yürütür. Canlı PoC'ta (0.3.x) kalite, sentetik
> senaryo seti (FR-TST-002/008) üzerinde ölçülüp samples'a yazılır.

Modlar:
  score    — Bir sağlayıcı örnek JSON'unu (turn test seti) puanlar → özet + gecikme/tiering/uygunluk kapısı.
  compare  — Çok sağlayıcılı `score` çıktılarından karşılaştırma matrisi (markdown).
  selftest — Dahili deterministik örnekle TTFT/tier/no-train/bölge/stall çekirdeğini doğrular (credential'sız).

Örnek (sample) JSON şeması — `samples/*.json`:
{
  "provider": "llm-cloud-A",
  "config": {
    "model_small": "tier1-fast", "model_large": "tier2-reason",   # FR-LLM-013 (küçük+büyük)
    "no_train": true, "data_retention": "NONE",                   # FR-LLM-012 / FR-KB-010
    "region": "EU", "region_pinned": true,                        # NFR 10.7 bölgesel endpoint
    "available_regions": ["EU", "UK", "TR"],
    "streaming": true, "fallback_supported": true
  },
  "turns": [
    {
      "id": "tr-routine-001", "language": "tr",
      "tier": "small",                  # bu turun yönlendirildiği tier (FR-LLM-013)
      "turn_class": "routine",          # router sınıfı: routine|complex|risky (FR-LLM-003)
      "first_token_ms": 150,            # TTFT (FR-LLM-004) — complete isteği → ilk token
      "quality": 0.95,                  # görev başarısı/yanıt doğruluğu (0–1); dış girdi
      "requires_tool": false,           # bu tur kritik tool çağrısı gerektiriyor mu (FR-LLM-008)
      "tool_call_valid": null,          # gerekiyorsa: schema-doğrulamalı tool-call üretildi mi
      "tokens": [{"t_ms": 150}, {"t_ms": 182}, {"t_ms": 210}, ...]  # token varış zamanları (sürekliliik)
    }, ...
  ]
}
`tier` ∈ {small, large}. `tokens` / `requires_tool` opsiyonel; yoksa ilgili metrik atlanır.
"""

from __future__ import annotations

import argparse
import json

# --- Eşikler (mühendislik varsayılanı; 0.3.x PoC'ta doğrulanır) -------------
# SAD §20 gecikme bütçesi — "LLM first token ~200–400 ms (P95). Tier'a göre; küçük model daha hızlı."
LLM_FIRST_TOKEN_P95_BUDGET_MS = 400.0   # kapı (gate) — SAD §20 üst sınır
LLM_FIRST_TOKEN_P95_GREEN_MS = 200.0    # yeşil bant — SAD §20 alt sınır
# Küçük/hızlı tier daha hızlı olmalı (FR-LLM-013). Küçük-tier TTFT ayrı, daha sıkı kapı.
SMALL_TIER_P95_BUDGET_MS = 200.0        # kapı (küçük model = SAD §20 alt hedefi)
SMALL_TIER_P95_GREEN_MS = 120.0         # yeşil bant
# Görev kalitesi (0–1; en-kötü-dil EN+TR). Dış girdi (kalibre set / LLM-judge).
QUALITY_MIN = 0.85                      # kapı (yüksek-iyi)
QUALITY_GREEN = 0.92                    # yeşil bant
# Streaming token sürekliliği — token arası boşluk > eşik = stall (downstream TTS aç kalır → ölü hava).
INTER_TOKEN_STALL_MS = 250.0            # bu süreyi aşan token-arası boşluk = stall
# Tool-call doğruluğu (FR-LLM-008) — tool gereken turlarda geçerli-yapısal oran (soft; rapora yazılır).
TOOL_CALL_VALID_MIN = 0.95              # uyarı eşiği (knock-out değil; 0.2.6'da bütünsel)
# Model tiering hedefi (SR-DEN-005 / FR-LLM-013) — küçük-model tur oranı (raporlanır; router metriği).
SMALL_TIER_SHARE_TARGET = 0.60
# Residency için beklenen bölge kapsamı (NFR 10.7); en az biri + region pinning gerekli.
REQUIRED_REGIONS = ("EU", "UK", "TR")


# ----------------------------------------------------------------------------
# Saf yardımcılar (test edilebilir)
# ----------------------------------------------------------------------------
def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = pct / 100.0 * (len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _lat_summary(vals: list[float]) -> dict:
    s = sorted(vals)
    return {
        "p50": round(_percentile(s, 50), 2) if s else None,
        "p95": round(_percentile(s, 95), 2) if s else None,
        "p99": round(_percentile(s, 99), 2) if s else None,
        "max": round(s[-1], 2) if s else None,
        "samples": len(s),
    }


def _verdict(measured: float | None, *, green: float, budget: float, lower_is_better: bool) -> str:
    if measured is None:
        return "VERİ-YOK"
    if lower_is_better:
        if measured <= green:
            return "YEŞİL"
        if measured <= budget:
            return "SARI"
        return "KIRMIZI"
    # higher is better (kalite): green = üst hedef, budget = alt kapı
    if measured >= green:
        return "YEŞİL"
    if measured >= budget:
        return "SARI"
    return "KIRMIZI"


# ----------------------------------------------------------------------------
# Streaming token sürekliliği (FR-LLM-004) — TTS dead-air'in LLM analoğu
# ----------------------------------------------------------------------------
def inter_token_stats(tokens: list[dict], stall_ms: float = INTER_TOKEN_STALL_MS) -> dict:
    """Token akışında inter-token gecikme + stall (uzun boşluk) + tokens/sn.

    İlk token TTFT'dir (ayrı ölçülür). Sonraki tokenlar arası boşluk uzarsa (> stall_ms) downstream
    TTS aç kalır → ölü hava (FR-RES-009 zinciri). max_gap + stall sayısı + ortalama inter-token + tps.
    """
    if not tokens or len(tokens) < 2:
        return {"stalls": 0, "max_gap_ms": None, "mean_itl_ms": None, "tokens_per_sec": None}
    ts = [float(t.get("t_ms", 0.0)) for t in tokens]
    gaps = [ts[i] - ts[i - 1] for i in range(1, len(ts))]
    stalls = sum(1 for g in gaps if g > stall_ms)
    span = ts[-1] - ts[0]
    tps = round((len(ts) - 1) / (span / 1000.0), 2) if span > 0 else None
    return {
        "stalls": stalls,
        "max_gap_ms": round(max(gaps), 2),
        "mean_itl_ms": round(sum(gaps) / len(gaps), 2),
        "tokens_per_sec": tps,
    }


# ----------------------------------------------------------------------------
# Uygunluk kapıları: no-train / no-log + bölgesel endpoint
# ----------------------------------------------------------------------------
def notrain_compliance(config: dict) -> tuple[bool, str]:
    """FR-LLM-012 + FR-KB-010: noTrain=true ve sağlayıcı-tarafı saklama NONE/EPHEMERAL."""
    no_train = bool(config.get("no_train", False))
    retention = config.get("data_retention", "PROVIDER_DEFAULT")
    ok = no_train and retention in ("NONE", "EPHEMERAL")
    if ok:
        return True, f"no-train açık + dataRetention={retention} (FR-LLM-012/FR-KB-010)"
    if not no_train:
        return False, "no-train varsayılanı kapalı (FR-LLM-012 ihlali)"
    return False, f"dataRetention={retention} (NONE/EPHEMERAL değil → no-log ihlali, FR-KB-010)"


def regional_compliance(config: dict, required: tuple[str, ...] = REQUIRED_REGIONS) -> tuple[bool, str, list[str]]:
    """NFR 10.7: bölgesel endpoint + region pinning; pin edilen bölge sunulanlar arasında."""
    pinned = bool(config.get("region_pinned", False))
    region = config.get("region")
    available = config.get("available_regions", []) or []
    covered = [r for r in required if r in available]
    ok = pinned and region is not None and region in available
    if not ok:
        if not pinned:
            reason = "region pinning yok (residency zorlanamaz, NFR 10.7)"
        elif region is None:
            reason = "endpoint bölgesi tanımsız (NFR 10.7)"
        else:
            reason = f"pin edilen bölge '{region}' sunulan bölgelerde yok {available} (NFR 10.7)"
    else:
        reason = f"bölgesel endpoint '{region}' pin'li; kapsanan beklenen bölgeler: {covered or '—'}"
    return ok, reason, covered


# ----------------------------------------------------------------------------
# Sağlayıcı puanlama çekirdeği
# ----------------------------------------------------------------------------
def summarize_provider(sample: dict) -> dict:
    """Bir sağlayıcı turn test setini puanla → özet + kapı (gate)."""
    config = sample.get("config", {})
    turns = sample.get("turns", [])

    ttft_all: list[float] = []
    ttft_by_tier: dict[str, list[float]] = {"small": [], "large": []}
    quality_by_lang: dict[str, list[float]] = {}
    tier_counts: dict[str, int] = {"small": 0, "large": 0, "?": 0}
    tool_required = 0
    tool_valid = 0
    total_stalls = 0
    stall_turns = 0
    streams_checked = 0
    itl_vals: list[float] = []

    for t in turns:
        lang = t.get("language", "en")
        tier = t.get("tier", "?")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        # first-token (FR-LLM-004) — overall + per tier
        ft = t.get("first_token_ms")
        if ft is not None:
            ttft_all.append(float(ft))
            if tier in ttft_by_tier:
                ttft_by_tier[tier].append(float(ft))

        # görev kalitesi (FR-LLM-001/003) — en-kötü-dil
        q = t.get("quality")
        if q is not None:
            quality_by_lang.setdefault(lang, []).append(float(q))

        # tool-call doğruluğu (FR-LLM-008)
        if t.get("requires_tool"):
            tool_required += 1
            if t.get("tool_call_valid"):
                tool_valid += 1

        # streaming sürekliliği (FR-LLM-004)
        toks = t.get("tokens")
        if toks:
            streams_checked += 1
            st = inter_token_stats(toks)
            total_stalls += st["stalls"]
            if st["stalls"] > 0:
                stall_turns += 1
            if st["mean_itl_ms"] is not None:
                itl_vals.append(st["mean_itl_ms"])

    # --- türetilmiş metrikler
    ttft_summary = _lat_summary(ttft_all)
    small_summary = _lat_summary(ttft_by_tier["small"])
    large_summary = _lat_summary(ttft_by_tier["large"])

    quality_by_language = {k: round(sum(v) / len(v), 4) for k, v in quality_by_lang.items()}
    all_q = [x for v in quality_by_lang.values() for x in v]
    quality_overall = round(sum(all_q) / len(all_q), 4) if all_q else None
    # Kapı en-kötü-dil üzerinden (EN+TR zorunlu; zayıf dili genel ortalama maskelemesin).
    quality_worst = min(quality_by_language.values()) if quality_by_language else None

    tool_valid_rate = round(tool_valid / tool_required, 4) if tool_required else None

    measured_tiers = tier_counts.get("small", 0) + tier_counts.get("large", 0)
    small_share = round(tier_counts.get("small", 0) / measured_tiers, 4) if measured_tiers else None

    # --- uygunluk kapıları
    nt_ok, nt_reason = notrain_compliance(config)
    rg_ok, rg_reason, rg_covered = regional_compliance(config)

    has_small = bool(config.get("model_small"))
    has_large = bool(config.get("model_large"))
    tiering_present = has_small and has_large

    # --- gecikme/kalite kapı kararları
    ttft_p95 = ttft_summary["p95"]
    small_p95 = small_summary["p95"]
    g_ttft = _verdict(ttft_p95, green=LLM_FIRST_TOKEN_P95_GREEN_MS,
                      budget=LLM_FIRST_TOKEN_P95_BUDGET_MS, lower_is_better=True)
    g_quality = _verdict(quality_worst, green=QUALITY_GREEN, budget=QUALITY_MIN, lower_is_better=False)

    # küçük-tier: tiering yoksa KIRMIZI (FR-LLM-013 Must); varsa ama veri yoksa VERİ-YOK
    if not tiering_present:
        g_small = "KIRMIZI"
        small_reason = "küçük+büyük tier birlikte sunulmuyor (FR-LLM-013 ihlali)"
        small_pass = False
    elif small_p95 is None:
        g_small = "VERİ-YOK"
        small_reason = "küçük tier sunuluyor; bu sette küçük-tier ölçümü yok"
        small_pass = True
    else:
        g_small = _verdict(small_p95, green=SMALL_TIER_P95_GREEN_MS,
                           budget=SMALL_TIER_P95_BUDGET_MS, lower_is_better=True)
        small_pass = g_small in ("YEŞİL", "SARI")
        small_reason = f"küçük-tier first-token P95={small_p95} ms"

    stall_pass = (streams_checked == 0) or (total_stalls == 0)
    stall_reason = ("token akışında stall yok (streaming sürekli)" if stall_pass else
                    f"{stall_turns} turda token stall (>{INTER_TOKEN_STALL_MS:.0f}ms), toplam={total_stalls} "
                    "→ downstream TTS ölü hava riski")
    tool_pass = (tool_valid_rate is None) or (tool_valid_rate >= TOOL_CALL_VALID_MIN)
    tool_reason = ("tool-call doğruluğu eşik üstü" if tool_pass else
                   f"geçerli tool-call oranı {tool_valid_rate} < {TOOL_CALL_VALID_MIN} (FR-LLM-008)")

    # Knock-out kapıları: first-token + küçük-tier + kalite + no-train + bölgesel + streaming-stall.
    # (Tool-call doğruluğu soft → 0.2.6'da bütünsel.)
    hard = {
        "first_token_p95_ms": {"budget": LLM_FIRST_TOKEN_P95_BUDGET_MS,
                               "green": LLM_FIRST_TOKEN_P95_GREEN_MS, "measured": ttft_p95,
                               "verdict": g_ttft, "pass": g_ttft in ("YEŞİL", "SARI", "VERİ-YOK")},
        "small_tier_first_token_p95_ms": {"budget": SMALL_TIER_P95_BUDGET_MS,
                                          "green": SMALL_TIER_P95_GREEN_MS, "measured": small_p95,
                                          "verdict": g_small, "pass": small_pass, "reason": small_reason},
        "quality_worst_language": {"min": QUALITY_MIN, "green": QUALITY_GREEN, "measured": quality_worst,
                                   "basis": "en-kötü-dil (EN+TR)", "verdict": g_quality,
                                   "pass": g_quality in ("YEŞİL", "SARI", "VERİ-YOK")},
        "no_train_no_log": {"required": True, "pass": nt_ok, "reason": nt_reason},
        "regional_endpoint": {"required": True, "pass": rg_ok, "reason": rg_reason,
                              "covered_regions": rg_covered},
        "streaming_stall": {"streams_checked": streams_checked, "stalls": total_stalls,
                            "pass": stall_pass, "reason": stall_reason},
    }
    overall_pass = all(v["pass"] for v in hard.values())

    # Bütünsel renk: bir kapı KIRMIZI/fail → KIRMIZI; tümü YEŞİL → YEŞİL; arası SARI.
    numeric_verdicts = [g_ttft, g_small, g_quality]
    compliance_green = nt_ok and rg_ok and stall_pass
    if not overall_pass:
        verdict = "KIRMIZI"
    elif all(v in ("YEŞİL", "VERİ-YOK") for v in numeric_verdicts) and compliance_green:
        verdict = "YEŞİL"
    else:
        verdict = "SARI"

    return {
        "provider": sample.get("provider", "?"),
        "config": config,
        "counts": {
            "turns": len(turns),
            "by_tier": tier_counts,
            "quality_by_language": {k: len(v) for k, v in quality_by_lang.items()},
            "tool_required": tool_required,
        },
        "tiering": {
            "present": tiering_present, "model_small": config.get("model_small"),
            "model_large": config.get("model_large"),
            "small_tier_share": small_share, "share_target": SMALL_TIER_SHARE_TARGET,
            "note": "küçük-model tur oranı router metriğidir (SR-DEN-005/5.3); burada raporlanır, kapı değil",
        },
        "first_token_ms": ttft_summary,
        "first_token_small_ms": small_summary,
        "first_token_large_ms": large_summary,
        "quality": {
            "overall": quality_overall, "worst_language": quality_worst,
            "by_language": quality_by_language,
        },
        "streaming": {"streams_checked": streams_checked, "stalls": total_stalls,
                      "stall_turns": stall_turns,
                      "mean_itl_ms": round(sum(itl_vals) / len(itl_vals), 2) if itl_vals else None},
        "tool_call": {"required": tool_required, "valid": tool_valid, "rate": tool_valid_rate,
                      "pass": tool_pass, "reason": tool_reason},
        "gates": hard,
        "verdict": verdict,
        "pass": overall_pass,
        "iz": ("FR-LLM-001/003/004/008/010/012/013; SR-LLM-001..013; SAD §20 (LLM first-token "
               "~200–400ms); NFR 10.1/10.7; ADR-002; FR-RES-005; FR-KB-010"),
    }


# ----------------------------------------------------------------------------
# score
# ----------------------------------------------------------------------------
def cmd_score(args: argparse.Namespace) -> int:
    with open(args.sample, encoding="utf-8") as fh:
        sample = json.load(fh)
    result = summarize_provider(sample)
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"yazıldı: {args.out}")
    print(out)
    return 0 if result["pass"] else 1


# ----------------------------------------------------------------------------
# compare
# ----------------------------------------------------------------------------
def cmd_compare(args: argparse.Namespace) -> int:
    rows = []
    for path in args.results:
        with open(path, encoding="utf-8") as fh:
            rows.append(json.load(fh))
    badge = {"YEŞİL": "🟢", "SARI": "🟡", "KIRMIZI": "🔴", "VERİ-YOK": "⚪"}
    lines = [
        "| Sağlayıcı | TTFT P95 (ms) | Küçük-tier P95 (ms) | Kalite EN | Kalite TR | no-train | Bölgesel | Stall | Karar |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ql = r.get("quality", {}).get("by_language", {})
        g = r.get("gates", {})
        nt = "evet" if g.get("no_train_no_log", {}).get("pass") else "HAYIR"
        rg = "evet" if g.get("regional_endpoint", {}).get("pass") else "HAYIR"
        st = r.get("streaming", {})
        st_txt = "yok" if st.get("stalls", 0) == 0 else f"{st.get('stalls')} stall"
        lines.append(
            f"| {r.get('provider', '?')} "
            f"| {r.get('first_token_ms', {}).get('p95', '-')} "
            f"| {r.get('first_token_small_ms', {}).get('p95', '-')} "
            f"| {ql.get('en', '-')} | {ql.get('tr', '-')} "
            f"| {nt} | {rg} | {st_txt} "
            f"| {badge.get(r.get('verdict'), '?')} {r.get('verdict', '?')} |"
        )
    lines.append("")
    lines.append(
        f"> Kapılar: LLM first-token P95 ≤ {LLM_FIRST_TOKEN_P95_BUDGET_MS:.0f} ms (SAD §20, yeşil ≤ "
        f"{LLM_FIRST_TOKEN_P95_GREEN_MS:.0f}); küçük-tier P95 ≤ {SMALL_TIER_P95_BUDGET_MS:.0f} ms (yeşil ≤ "
        f"{SMALL_TIER_P95_GREEN_MS:.0f}, FR-LLM-013); kalite (en-kötü-dil) ≥ {QUALITY_MIN:.2f} (yeşil ≥ "
        f"{QUALITY_GREEN:.2f}); no-train (FR-LLM-012) + bölgesel endpoint (NFR 10.7) + stall=0 zorunlu. "
        "Değerler ölçüm koşuluna bağlı; sağlayıcı seçimi 0.2.6'da bütünsel yapılır (vendor-neutral)."
    )
    table = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(table + "\n")
        print(f"yazıldı: {args.out}")
    print(table)
    return 0


# ----------------------------------------------------------------------------
# selftest — credential'sız çekirdek doğrulama
# ----------------------------------------------------------------------------
def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []

    def chk(name: str, cond: bool, detail: str = "") -> None:
        checks.append((name, cond, detail))

    # percentile
    chk("p95 of 1..100 ≈ 95.05", abs(_percentile(list(range(1, 101)), 95) - 95.05) < 1e-6,
        f"{_percentile(list(range(1, 101)), 95)}")
    # TTFT verdict: lower-is-better
    chk("TTFT 180ms → YEŞİL", _verdict(180.0, green=LLM_FIRST_TOKEN_P95_GREEN_MS,
                                       budget=LLM_FIRST_TOKEN_P95_BUDGET_MS, lower_is_better=True) == "YEŞİL")
    chk("TTFT 350ms → SARI", _verdict(350.0, green=LLM_FIRST_TOKEN_P95_GREEN_MS,
                                      budget=LLM_FIRST_TOKEN_P95_BUDGET_MS, lower_is_better=True) == "SARI")
    chk("TTFT 520ms → KIRMIZI", _verdict(520.0, green=LLM_FIRST_TOKEN_P95_GREEN_MS,
                                         budget=LLM_FIRST_TOKEN_P95_BUDGET_MS, lower_is_better=True) == "KIRMIZI")
    # kalite verdict: higher-is-better, en-kötü-dil
    chk("kalite 0.80 < 0.85 → KIRMIZI", _verdict(0.80, green=QUALITY_GREEN, budget=QUALITY_MIN,
                                                 lower_is_better=False) == "KIRMIZI")
    chk("kalite 0.88 → SARI", _verdict(0.88, green=QUALITY_GREEN, budget=QUALITY_MIN,
                                       lower_is_better=False) == "SARI")
    chk("kalite 0.95 → YEŞİL", _verdict(0.95, green=QUALITY_GREEN, budget=QUALITY_MIN,
                                        lower_is_better=False) == "YEŞİL")

    # inter-token: pürüzsüz akış (her token ~30ms arayla) → stall yok
    smooth = [{"t_ms": 150 + 30 * i} for i in range(8)]
    s_sm = inter_token_stats(smooth)
    chk("inter-token pürüzsüz stall=0", s_sm["stalls"] == 0, f"{s_sm}")
    chk("inter-token tokens/sn pozitif", (s_sm["tokens_per_sec"] or 0) > 0, f"{s_sm['tokens_per_sec']}")
    # inter-token: ortada 400ms boşluk → stall
    stally = [{"t_ms": 150}, {"t_ms": 180}, {"t_ms": 580}, {"t_ms": 610}]
    s_st = inter_token_stats(stally)
    chk("inter-token 400ms boşluk → stall>0", s_st["stalls"] >= 1, f"{s_st}")

    # no-train uygunluğu
    chk("no-train: true + NONE → uygun", notrain_compliance({"no_train": True, "data_retention": "NONE"})[0])
    chk("no-train: false → uygunsuz", not notrain_compliance({"no_train": False, "data_retention": "NONE"})[0])
    chk("no-train: PROVIDER_DEFAULT retention → uygunsuz",
        not notrain_compliance({"no_train": True, "data_retention": "PROVIDER_DEFAULT"})[0])
    # bölgesel uygunluk
    chk("bölge: EU pin + EU sunulu → uygun",
        regional_compliance({"region_pinned": True, "region": "EU", "available_regions": ["EU", "UK"]})[0])
    chk("bölge: pin yok → uygunsuz",
        not regional_compliance({"region_pinned": False, "region": "EU", "available_regions": ["EU"]})[0])
    chk("bölge: US-only (TR/EU/UK yok) ama pin+sunulu → uygun(pinning) ama kapsam boş",
        regional_compliance({"region_pinned": True, "region": "US", "available_regions": ["US"]})[0] is True
        and regional_compliance({"region_pinned": True, "region": "US", "available_regions": ["US"]})[2] == [])

    # uçtan uca: kapı-geçen sağlayıcı (küçük+büyük tier, no-train, bölgesel, pürüzsüz)
    sample_ok = {
        "provider": "selftest", "config": {
            "model_small": "fast", "model_large": "reason", "no_train": True, "data_retention": "NONE",
            "region": "EU", "region_pinned": True, "available_regions": ["EU", "UK", "TR"],
            "streaming": True, "fallback_supported": True},
        "turns": [
            {"id": "en-r1", "language": "en", "tier": "small", "turn_class": "routine",
             "first_token_ms": 140, "quality": 0.95, "requires_tool": False,
             "tokens": [{"t_ms": 140 + 30 * i} for i in range(8)]},
            {"id": "tr-r1", "language": "tr", "tier": "small", "turn_class": "routine",
             "first_token_ms": 160, "quality": 0.9, "requires_tool": False,
             "tokens": [{"t_ms": 160 + 32 * i} for i in range(8)]},
            {"id": "tr-c1", "language": "tr", "tier": "large", "turn_class": "complex",
             "first_token_ms": 320, "quality": 0.93, "requires_tool": True, "tool_call_valid": True,
             "tokens": [{"t_ms": 320 + 35 * i} for i in range(10)]},
            {"id": "en-c1", "language": "en", "tier": "large", "turn_class": "risky",
             "first_token_ms": 300, "quality": 0.96, "requires_tool": True, "tool_call_valid": True,
             "tokens": [{"t_ms": 300 + 35 * i} for i in range(10)]},
        ],
    }
    res = summarize_provider(sample_ok)
    chk("score: kapı-geçen set pass", res["pass"], f"verdict={res['verdict']}")
    chk("score: küçük-tier TTFT < büyük-tier TTFT",
        res["first_token_small_ms"]["p95"] < res["first_token_large_ms"]["p95"],
        f"small={res['first_token_small_ms']['p95']} large={res['first_token_large_ms']['p95']}")
    chk("score: kalite en-kötü-dil = min(en,tr)",
        res["quality"]["worst_language"] == min(res["quality"]["by_language"].values()))
    chk("score: küçük-tier payı raporlanır", res["tiering"]["small_tier_share"] == 0.5,
        f"{res['tiering']['small_tier_share']}")
    chk("score: tool-call doğruluğu 1.0", res["tool_call"]["rate"] == 1.0, f"{res['tool_call']['rate']}")
    chk("score: stall yok", res["streaming"]["stalls"] == 0)

    # uçtan uca: TR kalite düşük → en-kötü-dil kapısı eler (EN güçlü maskeleyemez)
    sample_tr_weak = {
        "provider": "selftest-tr-weak", "config": {
            "model_small": "fast", "model_large": "reason", "no_train": True, "data_retention": "NONE",
            "region": "EU", "region_pinned": True, "available_regions": ["EU"]},
        "turns": [
            {"id": "en-1", "language": "en", "tier": "small", "first_token_ms": 150, "quality": 0.95},
            {"id": "tr-1", "language": "tr", "tier": "small", "first_token_ms": 160, "quality": 0.80},
        ],
    }
    res2 = summarize_provider(sample_tr_weak)
    chk("score: TR kalite 0.80 → KIRMIZI (en-kötü-dil eler)",
        res2["verdict"] == "KIRMIZI" and not res2["gates"]["quality_worst_language"]["pass"],
        f"verdict={res2['verdict']}")
    chk("score: genel kalite (~0.875) kapıyı maskelemez", (res2["quality"]["overall"] or 0) >= 0.85,
        f"overall={res2['quality']['overall']}, worst={res2['quality']['worst_language']}")

    # uçtan uca: no-train kapalı + bölgesel yok → çoklu KIRMIZI uygunluk
    sample_noncompliant = {
        "provider": "selftest-noncompliant", "config": {
            "model_small": "fast", "model_large": "reason", "no_train": False,
            "data_retention": "PROVIDER_DEFAULT", "region": "US", "region_pinned": False,
            "available_regions": ["US"]},
        "turns": [
            {"id": "en-1", "language": "en", "tier": "small", "first_token_ms": 150, "quality": 0.95},
            {"id": "tr-1", "language": "tr", "tier": "large", "first_token_ms": 300, "quality": 0.9},
        ],
    }
    res3 = summarize_provider(sample_noncompliant)
    chk("score: no-train kapalı → uygunluk fail",
        not res3["gates"]["no_train_no_log"]["pass"] and res3["verdict"] == "KIRMIZI")
    chk("score: bölgesel endpoint yok → uygunluk fail",
        not res3["gates"]["regional_endpoint"]["pass"])

    # uçtan uca: tiering yok (yalnız büyük model) → küçük-tier kapısı KIRMIZI
    sample_no_tier = {
        "provider": "selftest-no-tier", "config": {
            "model_large": "reason", "no_train": True, "data_retention": "NONE",
            "region": "EU", "region_pinned": True, "available_regions": ["EU"]},
        "turns": [{"id": "en-1", "language": "en", "tier": "large", "first_token_ms": 300, "quality": 0.95},
                  {"id": "tr-1", "language": "tr", "tier": "large", "first_token_ms": 320, "quality": 0.9}],
    }
    res4 = summarize_provider(sample_no_tier)
    chk("score: küçük+büyük tier yok → tiering kapısı fail (FR-LLM-013)",
        not res4["gates"]["small_tier_first_token_p95_ms"]["pass"] and res4["verdict"] == "KIRMIZI")

    passed = sum(1 for _, c, _ in checks if c)
    for name, cond, detail in checks:
        mark = "✅" if cond else "❌"
        print(f"{mark} {name}" + (f"  ({detail})" if detail and not cond else ""))
    print(f"\n{passed}/{len(checks)} kontrol geçti.")
    return 0 if passed == len(checks) else 1


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LLM sağlayıcı değerlendirme hattı (WBS 0.2.4)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="bir sağlayıcı turn test setini puanla + kapı")
    sc.add_argument("sample", help="sağlayıcı turn test seti JSON")
    sc.add_argument("--out", help="özet JSON dosyası")
    sc.set_defaults(func=cmd_score)

    cp = sub.add_parser("compare", help="çok sağlayıcılı karşılaştırma matrisi (markdown)")
    cp.add_argument("results", nargs="+", help="score çıktısı JSON dosyaları")
    cp.add_argument("--out")
    cp.set_defaults(func=cmd_compare)

    st = sub.add_parser("selftest", help="credential'sız çekirdek doğrulama")
    st.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
