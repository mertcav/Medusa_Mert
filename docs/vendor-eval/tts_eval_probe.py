#!/usr/bin/env python3
"""tts_eval_probe.py — TTS (ses sentezi) sağlayıcı değerlendirme hattı (WBS 0.2.3, →FR-TTS-001/002).

Amaç: ≥2 TTS sağlayıcısını **sağlayıcı-nötr (ADR-002)**, ölçüt-tabanlı ve tekrarlanabilir biçimde
değerlendirmek. Ölçülen boyutlar (FR-TTS-001..010, SR-TTS-001..010):
- **First-byte gecikmesi (TTFB, FR-TTS-002):** synthesize isteği → ilk ses paketi; **SAD §20 TTS
  kalemi P95 ≤ 200 ms** (yeşil ≤ 100 ms) kapısı. Streaming başlangıç gecikmesi → algılanan duraklamayı
  belirler; cache hit'te (FR-TTS-010) ~0.
- **Barge-in kesme gecikmesi (FR-TTS-005, FR-RTC-002):** `cancel()` çağrısı → ses akışının fiilen
  durması; **NFR 10.1 / SAD §6.1: TTS kesme ≤ 200 ms** (yeşil ≤ 100 ms) kapısı. Kesilemeyen TTS,
  kullanıcı sözünü kestiğinde üst üste konuşmaya (talk-over) yol açar.
- **Ses kalitesi (FR-TTS-001/003):** MOS (Mean Opinion Score, 1–5 doğallık); **en-kötü-dil** üzerinden
  kapı (EN+TR zorunlu — zayıf dili genel ortalama maskelemesin, STT eval ile aynı disiplin).
- **Streaming sürekliliği / ölü hava (FR-RES-009):** chunk akışı gerçek-zaman ayak uydurmalı; tampon
  boşalması (underrun) → ölü hava (dead air). Real-time factor (RTF) < 1 + underrun sayısı.
- **Telaffuz doğruluğu (FR-TTS-004):** sayı/tarih/para/özel-isim yapısal alanlarda pronunciation
  dictionary etkisi; doğru-sentez oranı (alan bazında).
- **Ses karakteri tutarlılığı (FR-TTS-009)** + **cache (FR-TTS-010/FR-RES-003)** + **8 kHz native ·
  residency · no-train (FR-RES-008, NFR 10.7, FR-KB-010):** yetenek/uygunluk.

Tasarım ilkeleri (CLAUDE.md):
- **Vendor-neutral:** Araç hiçbir sağlayıcı seçmez; ölçüt-tabanlı sonuç üretir. Nihai seçim 0.2.6'da.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / media_latency_probe.py / stt_eval_probe.py disiplini).
- **Credential-free self-test:** `selftest` ve `samples/*.json` ile gerçek TTS credential olmadan
  uçtan uca koşar (CI'da). Gerçek sağlayıcı çıktısı yalnız dışarıdan örnek JSON ile verilir; sır
  repoya YAZILMAZ (yalnız ortam değişkeni / `--url` ile canlı toplama, 0.3.x PoC).

> **MOS notu (vendor-neutral + tekrarlanabilirlik):** Ses kalitesi doğası gereği algısaldır. Bu harness
> MOS'u sağlayıcıya özel değil, **dış girdi** (panel dinleme skoru ya da kalibre edilmiş objektif
> vekil) olarak alır; kapı/karşılaştırma mantığını yürütür. Canlı PoC'ta (0.3.x) MOS, sentetik
> telefoni (8 kHz) örnekleri üzerinde panel/araç ile ölçülüp samples'a yazılır.

Modlar:
  score    — Bir sağlayıcı örnek JSON'unu (utterance test seti) puanlar → özet + gecikme/kalite kapısı.
  compare  — Çok sağlayıcılı `score` çıktılarından karşılaştırma matrisi (markdown).
  selftest — Dahili deterministik örnekle TTFB/barge-in/MOS/dead-air çekirdeğini doğrular (credential'sız).

Örnek (sample) JSON şeması — `samples/*.json`:
{
  "provider": "tts-cloud-A",
  "config": {"sample_rate_hz": 8000, "model": "telephony-neural", "data_retention": "NONE",
             "native_8khz": true, "residency": "EU", "voice_consistency": "fixed_voice_id"},
  "utterances": [
    {
      "id": "tr-greet-001", "language": "tr", "field_type": "general",
      "text": "merhaba size nasıl yardımcı olabilirim",
      "mos": 4.4,                       # algısal doğallık (1–5); dış girdi
      "first_byte_ms": 120,             # synthesize isteği → ilk ses chunk'ı (FR-TTS-002)
      "cached": false,                  # FR-TTS-010 cache hit? (true ise TTFB ~0)
      "pronunciation_ok": true,         # FR-TTS-004 yapısal alan doğru sentezlendi mi (general'da yok sayılır)
      "barge_in": {"cancel_req_ms": 5000, "audio_stopped_ms": 5085},  # kesme gecikmesi = stopped - req
      "chunks": [{"t_ms": 120, "dur_ms": 40}, {"t_ms": 162, "dur_ms": 40}, ...]  # süreklilik (FR-RES-009)
    }, ...
  ]
}
`field_type` ∈ {general, number, date, currency, name}. Yapısal alanlar (general dışı) telaffuz
doğruluğunda (FR-TTS-004) sayılır. `chunks`/`barge_in` opsiyonel; yoksa ilgili metrik atlanır.
"""

from __future__ import annotations

import argparse
import json
import sys

# --- Eşikler (mühendislik varsayılanı; 0.3.x PoC'ta doğrulanır) -------------
# SAD §20 gecikme bütçesi — "TTS first byte ~100–200 ms (P95)" kalemi.
TTS_FIRST_BYTE_P95_BUDGET_MS = 200.0   # kapı (gate)
TTS_FIRST_BYTE_P95_GREEN_MS = 100.0    # yeşil bant
# NFR 10.1 / SAD §6.1 — barge-in TTS kesme ≤ 200 ms.
BARGE_IN_P95_BUDGET_MS = 200.0         # kapı
BARGE_IN_P95_GREEN_MS = 100.0          # yeşil bant
# Ses kalitesi (MOS, 1–5; en-kötü-dil). Telefoni doğallık beklentisi (illüstratif eşik).
MOS_MIN = 4.0                          # kapı (yüksek-iyi)
MOS_GREEN = 4.3                        # yeşil bant
# Telaffuz doğruluğu (FR-TTS-004) — yapısal alanlarda doğru-sentez oranı (soft; rapora yazılır).
PRONUNCIATION_MIN = 0.90               # uyarı eşiği (knock-out değil; 0.2.6'da bütünsel)

STRUCTURED_FIELDS = ("number", "date", "currency", "name")


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


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


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
    # higher is better (MOS): green = üst hedef, budget = alt kapı
    if measured >= green:
        return "YEŞİL"
    if measured >= budget:
        return "SARI"
    return "KIRMIZI"


# ----------------------------------------------------------------------------
# Barge-in kesme gecikmesi (FR-TTS-005, FR-RTC-002)
# ----------------------------------------------------------------------------
def barge_in_latency_ms(utt: dict) -> float | None:
    """cancel() çağrısı → ses akışının fiilen durması (NFR 10.1: ≤ 200 ms)."""
    bi = utt.get("barge_in")
    if not bi:
        return None
    req, stopped = bi.get("cancel_req_ms"), bi.get("audio_stopped_ms")
    if req is None or stopped is None:
        return None
    return max(0.0, float(stopped) - float(req))


# ----------------------------------------------------------------------------
# Streaming sürekliliği / ölü hava (dead air) — FR-RES-009
# ----------------------------------------------------------------------------
def dead_air_check(chunks: list[dict], tol_ms: float = 1.0) -> tuple[int, float | None]:
    """Tampon boşalması (underrun) sayısı + real-time factor (RTF).

    Playout ilk chunk'ın varışında başlar. Chunk i geldiğinde, o ana dek üretilmiş ses süresi
    (cumulative dur) geçen süreden (t_i - t_0) kısaysa tampon boşalmıştır → ölü hava. RTF = toplam
    teslim süresi / toplam ses süresi; > 1 ise akış gerçek-zamana ayak uyduramıyor.
    """
    if not chunks or len(chunks) < 2:
        return 0, None
    t0 = chunks[0].get("t_ms", 0.0)
    underruns = 0
    cum_dur = 0.0  # chunk i'den ÖNCE üretilmiş ses süresi (chunk i çalınmaya hazır)
    total_dur = 0.0
    for i, ch in enumerate(chunks):
        t = ch.get("t_ms", 0.0)
        if i >= 1:
            elapsed = t - t0
            if elapsed > cum_dur + tol_ms:  # gelmeden önce buffer bitti → ölü hava
                underruns += 1
        cum_dur += ch.get("dur_ms", 0.0)
        total_dur = cum_dur
    delivery_span = chunks[-1].get("t_ms", 0.0) - t0
    rtf = round(delivery_span / total_dur, 4) if total_dur > 0 else None
    return underruns, rtf


# ----------------------------------------------------------------------------
# Sağlayıcı puanlama çekirdeği
# ----------------------------------------------------------------------------
def summarize_provider(sample: dict) -> dict:
    """Bir sağlayıcı örnek setini puanla → özet + kapı (gate)."""
    utts = sample.get("utterances", [])
    ttfb_cold: list[float] = []       # cache hit OLMAYAN (gerçek sentez) first-byte
    ttfb_cached: list[float] = []
    barge: list[float] = []
    mos_by_lang: dict[str, list[float]] = {}
    pron_by_field: dict[str, list[bool]] = {}
    total_underruns = 0
    rtf_vals: list[float] = []
    dead_air_utts = 0
    chunks_checked = 0

    for u in utts:
        lang = u.get("language", "en")
        ftype = u.get("field_type", "general")

        # first-byte (FR-TTS-002) — cache hit ayrı tutulur (FR-TTS-010)
        fb = u.get("first_byte_ms")
        if fb is not None:
            (ttfb_cached if u.get("cached") else ttfb_cold).append(float(fb))

        # barge-in kesme (FR-TTS-005)
        b = barge_in_latency_ms(u)
        if b is not None:
            barge.append(b)

        # ses kalitesi MOS (FR-TTS-001/003) — en-kötü-dil
        mos = u.get("mos")
        if mos is not None:
            mos_by_lang.setdefault(lang, []).append(float(mos))

        # telaffuz doğruluğu (FR-TTS-004) — yapısal alanlar
        if ftype in STRUCTURED_FIELDS:
            pron_by_field.setdefault(ftype, []).append(bool(u.get("pronunciation_ok", False)))

        # süreklilik / ölü hava (FR-RES-009)
        chunks = u.get("chunks")
        if chunks:
            chunks_checked += 1
            ur, rtf = dead_air_check(chunks)
            total_underruns += ur
            if ur > 0:
                dead_air_utts += 1
            if rtf is not None:
                rtf_vals.append(rtf)

    # --- türetilmiş metrikler
    mos_by_language = {k: round(sum(v) / len(v), 4) for k, v in mos_by_lang.items()}
    all_mos = [x for v in mos_by_lang.values() for x in v]
    mos_overall = round(sum(all_mos) / len(all_mos), 4) if all_mos else None
    # Kapı en-kötü-dil üzerinden (EN+TR zorunlu; zayıf dili genel MOS maskelemesin).
    mos_worst = min(mos_by_language.values()) if mos_by_language else None

    ttfb_summary = _lat_summary(ttfb_cold)         # kapı cold (gerçek sentez) üzerinden
    ttfb_cached_summary = _lat_summary(ttfb_cached)
    barge_summary = _lat_summary(barge)

    pron_by_field_rate = {k: round(sum(v) / len(v), 4) for k, v in pron_by_field.items()}
    all_pron = [x for v in pron_by_field.values() for x in v]
    pron_rate = round(sum(all_pron) / len(all_pron), 4) if all_pron else None

    rtf_max = round(max(rtf_vals), 4) if rtf_vals else None

    # --- kapılar (gate)
    ttfb_p95 = ttfb_summary["p95"]
    barge_p95 = barge_summary["p95"]
    g_ttfb = _verdict(ttfb_p95, green=TTS_FIRST_BYTE_P95_GREEN_MS,
                      budget=TTS_FIRST_BYTE_P95_BUDGET_MS, lower_is_better=True)
    g_barge = _verdict(barge_p95, green=BARGE_IN_P95_GREEN_MS,
                       budget=BARGE_IN_P95_BUDGET_MS, lower_is_better=True)
    g_mos = _verdict(mos_worst, green=MOS_GREEN, budget=MOS_MIN, lower_is_better=False)

    dead_air_pass = (chunks_checked == 0) or (total_underruns == 0)
    dead_air_reason = ("tampon boşalması yok (streaming gerçek-zamana ayak uyduruyor)"
                       if dead_air_pass else
                       f"{dead_air_utts} utterance'ta ölü hava (underrun={total_underruns}, "
                       f"RTF_max={rtf_max})")
    pron_pass = (pron_rate is None) or (pron_rate >= PRONUNCIATION_MIN)
    pron_reason = ("telaffuz doğruluğu eşik üstü" if pron_pass else
                   f"yapısal telaffuz oranı {pron_rate} < {PRONUNCIATION_MIN} (FR-TTS-004)")

    # Knock-out kapıları: first-byte + barge-in + MOS + ölü-hava. (Telaffuz soft → 0.2.6'da bütünsel.)
    hard = {
        "first_byte_p95_ms": {"budget": TTS_FIRST_BYTE_P95_BUDGET_MS,
                              "green": TTS_FIRST_BYTE_P95_GREEN_MS, "measured": ttfb_p95,
                              "verdict": g_ttfb, "pass": g_ttfb in ("YEŞİL", "SARI", "VERİ-YOK")},
        "barge_in_cancel_p95_ms": {"budget": BARGE_IN_P95_BUDGET_MS, "green": BARGE_IN_P95_GREEN_MS,
                                   "measured": barge_p95, "verdict": g_barge,
                                   "pass": g_barge in ("YEŞİL", "SARI", "VERİ-YOK")},
        "mos": {"min": MOS_MIN, "green": MOS_GREEN, "measured": mos_worst, "basis": "en-kötü-dil",
                "verdict": g_mos, "pass": g_mos in ("YEŞİL", "SARI", "VERİ-YOK")},
        "dead_air": {"chunks_checked": chunks_checked, "underruns": total_underruns,
                     "rtf_max": rtf_max, "pass": dead_air_pass, "reason": dead_air_reason},
    }
    overall_pass = all(v["pass"] for v in hard.values())

    # Bütünsel renk: bir kapı KIRMIZI/fail → KIRMIZI; tümü YEŞİL → YEŞİL; arası SARI.
    numeric_verdicts = [g_ttfb, g_barge, g_mos]
    if not overall_pass:
        verdict = "KIRMIZI"
    elif all(v in ("YEŞİL", "VERİ-YOK") for v in numeric_verdicts) and dead_air_pass:
        verdict = "YEŞİL"
    else:
        verdict = "SARI"

    return {
        "provider": sample.get("provider", "?"),
        "config": sample.get("config", {}),
        "counts": {
            "utterances": len(utts),
            "mos_by_language": {k: len(v) for k, v in mos_by_lang.items()},
            "structured": sum(len(v) for v in pron_by_field.values()),
            "cached": len(ttfb_cached),
        },
        "quality": {
            "mos_overall": mos_overall,
            "mos_worst_language": mos_worst,
            "mos_by_language": mos_by_language,
        },
        "first_byte_ms": ttfb_summary,
        "first_byte_cached_ms": ttfb_cached_summary,
        "barge_in_cancel_ms": barge_summary,
        "dead_air": {"chunks_checked": chunks_checked, "underruns": total_underruns,
                     "dead_air_utterances": dead_air_utts, "rtf_max": rtf_max},
        "pronunciation": {"rate": pron_rate, "by_field": pron_by_field_rate,
                          "pass": pron_pass, "reason": pron_reason},
        "gates": hard,
        "verdict": verdict,
        "pass": overall_pass,
        "iz": ("FR-TTS-001/002/004/005/009/010; SR-TTS-001..010; SAD §20 (TTS first-byte ≤200ms) + "
               "§6.1 (barge-in kesme ≤200ms); NFR 10.1; ADR-002; FR-RES-008/009; FR-KB-010"),
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
        "| Sağlayıcı | MOS EN | MOS TR | TTFB P95 (ms) | Barge-in P95 (ms) | Ölü hava | Telaffuz | Karar |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        q = r.get("quality", {}).get("mos_by_language", {})
        da = r.get("dead_air", {})
        pr = r.get("pronunciation", {})
        da_txt = "yok" if da.get("underruns", 0) == 0 else f"{da.get('underruns')} underrun"
        lines.append(
            f"| {r.get('provider', '?')} "
            f"| {q.get('en', '-')} | {q.get('tr', '-')} "
            f"| {r.get('first_byte_ms', {}).get('p95', '-')} "
            f"| {r.get('barge_in_cancel_ms', {}).get('p95', '-')} "
            f"| {da_txt} "
            f"| {pr.get('rate', '-')} "
            f"| {badge.get(r.get('verdict'), '?')} {r.get('verdict', '?')} |"
        )
    lines.append("")
    lines.append(
        f"> Kapılar: TTS first-byte P95 ≤ {TTS_FIRST_BYTE_P95_BUDGET_MS:.0f} ms (SAD §20, yeşil ≤ "
        f"{TTS_FIRST_BYTE_P95_GREEN_MS:.0f}); barge-in kesme P95 ≤ {BARGE_IN_P95_BUDGET_MS:.0f} ms "
        f"(NFR 10.1, yeşil ≤ {BARGE_IN_P95_GREEN_MS:.0f}); MOS (en-kötü-dil) ≥ {MOS_MIN:.1f} (yeşil ≥ "
        f"{MOS_GREEN:.1f}); ölü hava (underrun) = 0. Değerler ölçüm koşuluna bağlı; sağlayıcı seçimi "
        "0.2.6'da bütünsel yapılır (vendor-neutral)."
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
    # barge-in gecikme: 5085 - 5000 = 85
    d = barge_in_latency_ms({"barge_in": {"cancel_req_ms": 5000, "audio_stopped_ms": 5085}})
    chk("barge-in gecikme 85ms", d == 85.0, f"{d}")
    # barge-in eksik veri → None
    chk("barge-in verisi yok → None", barge_in_latency_ms({}) is None)
    # dead-air: gerçek-zamana ayak uyduran akış (her chunk 40ms, 40ms arayla) → underrun yok
    smooth = [{"t_ms": 100 + 40 * i, "dur_ms": 40} for i in range(5)]
    ur, rtf = dead_air_check(smooth)
    chk("dead-air pürüzsüz akış underrun=0", ur == 0, f"underrun={ur}, rtf={rtf}")
    chk("dead-air pürüzsüz RTF ≈ 1.0", rtf is not None and abs(rtf - 1.0) < 0.3, f"rtf={rtf}")
    # dead-air: yavaş akış (40ms ses, 120ms arayla) → tampon boşalır → underrun
    slow = [{"t_ms": 100 + 120 * i, "dur_ms": 40} for i in range(5)]
    ur2, rtf2 = dead_air_check(slow)
    chk("dead-air yavaş akış underrun>0", ur2 > 0, f"underrun={ur2}, rtf={rtf2}")
    chk("dead-air yavaş akış RTF > 1", rtf2 is not None and rtf2 > 1.0, f"rtf={rtf2}")
    # MOS verdict: en-kötü-dil higher-is-better
    chk("MOS 3.6 < 4.0 → KIRMIZI", _verdict(3.6, green=MOS_GREEN, budget=MOS_MIN,
                                            lower_is_better=False) == "KIRMIZI")
    chk("MOS 4.1 → SARI", _verdict(4.1, green=MOS_GREEN, budget=MOS_MIN,
                                   lower_is_better=False) == "SARI")
    chk("MOS 4.4 → YEŞİL", _verdict(4.4, green=MOS_GREEN, budget=MOS_MIN,
                                    lower_is_better=False) == "YEŞİL")
    # TTFB verdict: lower-is-better
    chk("TTFB 90ms → YEŞİL", _verdict(90.0, green=TTS_FIRST_BYTE_P95_GREEN_MS,
                                      budget=TTS_FIRST_BYTE_P95_BUDGET_MS,
                                      lower_is_better=True) == "YEŞİL")
    chk("TTFB 320ms → KIRMIZI", _verdict(320.0, green=TTS_FIRST_BYTE_P95_GREEN_MS,
                                         budget=TTS_FIRST_BYTE_P95_BUDGET_MS,
                                         lower_is_better=True) == "KIRMIZI")

    # uçtan uca: kapı-geçen küçük sağlayıcı seti puanla
    sample_ok = {
        "provider": "selftest", "config": {"sample_rate_hz": 8000, "native_8khz": True},
        "utterances": [
            {"id": "en-1", "language": "en", "field_type": "general",
             "text": "how can i help you today", "mos": 4.4, "first_byte_ms": 95, "cached": False,
             "barge_in": {"cancel_req_ms": 3000, "audio_stopped_ms": 3080},
             "chunks": [{"t_ms": 95 + 40 * i, "dur_ms": 40} for i in range(6)]},
            {"id": "tr-1", "language": "tr", "field_type": "general",
             "text": "size nasıl yardımcı olabilirim", "mos": 4.3, "first_byte_ms": 110, "cached": False,
             "barge_in": {"cancel_req_ms": 3000, "audio_stopped_ms": 3090},
             "chunks": [{"t_ms": 110 + 40 * i, "dur_ms": 40} for i in range(6)]},
            {"id": "tr-cur", "language": "tr", "field_type": "currency",
             "text": "bin iki yüz elli lira elli kuruş", "mos": 4.2, "first_byte_ms": 120,
             "cached": False, "pronunciation_ok": True,
             "chunks": [{"t_ms": 120 + 40 * i, "dur_ms": 40} for i in range(6)]},
            {"id": "tr-greet-cache", "language": "tr", "field_type": "general",
             "text": "hoş geldiniz", "mos": 4.4, "first_byte_ms": 4, "cached": True,
             "chunks": [{"t_ms": 4 + 40 * i, "dur_ms": 40} for i in range(4)]},
        ],
    }
    res = summarize_provider(sample_ok)
    chk("score: kapı-geçen set pass", res["pass"], f"verdict={res['verdict']}")
    chk("score: MOS en-kötü-dil = min(en,tr)",
        res["quality"]["mos_worst_language"] == min(res["quality"]["mos_by_language"].values()))
    chk("score: cache first-byte ayrı tutulur", res["counts"]["cached"] == 1,
        f"cached={res['counts']['cached']}")
    chk("score: ölü hava yok", res["dead_air"]["underruns"] == 0)
    chk("score: telaffuz oranı 1.0", res["pronunciation"]["rate"] == 1.0,
        f"{res['pronunciation']['rate']}")

    # uçtan uca: TR MOS düşük → en-kötü-dil kapısı eler (EN güçlü maskeleyemez)
    sample_tr_weak = {
        "provider": "selftest-tr-weak", "config": {"sample_rate_hz": 8000},
        "utterances": [
            {"id": "en-1", "language": "en", "field_type": "general", "text": "hello",
             "mos": 4.4, "first_byte_ms": 95,
             "barge_in": {"cancel_req_ms": 3000, "audio_stopped_ms": 3080}},
            {"id": "tr-1", "language": "tr", "field_type": "general", "text": "merhaba",
             "mos": 3.6, "first_byte_ms": 100,
             "barge_in": {"cancel_req_ms": 3000, "audio_stopped_ms": 3090}},
        ],
    }
    res2 = summarize_provider(sample_tr_weak)
    chk("score: TR MOS 3.6 → KIRMIZI (en-kötü-dil eler)", res2["verdict"] == "KIRMIZI" and
        not res2["gates"]["mos"]["pass"], f"verdict={res2['verdict']}")
    chk("score: genel MOS (4.0) kapıyı maskelemez", (res2["quality"]["mos_overall"] or 0) >= 4.0,
        f"overall={res2['quality']['mos_overall']}, worst={res2['quality']['mos_worst_language']}")

    passed = sum(1 for _, c, _ in checks if c)
    for name, cond, detail in checks:
        mark = "✅" if cond else "❌"
        print(f"{mark} {name}" + (f"  ({detail})" if detail and not cond else ""))
    print(f"\n{passed}/{len(checks)} kontrol geçti.")
    return 0 if passed == len(checks) else 1


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TTS sağlayıcı değerlendirme hattı (WBS 0.2.3)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("score", help="bir sağlayıcı örnek setini puanla + kapı")
    sc.add_argument("sample", help="sağlayıcı utterance test seti JSON")
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
