#!/usr/bin/env python3
"""stt_eval_probe.py — STT (konuşma tanıma) sağlayıcı değerlendirme hattı (WBS 0.2.2, →FR-STT-001).

Amaç: ≥2 STT sağlayıcısını **sağlayıcı-nötr (ADR-002)**, ölçüt-tabanlı ve tekrarlanabilir biçimde
değerlendirmek. Ölçülen boyutlar (FR-STT-001..008, SR-STT-001..008):
- **Doğruluk:** WER (kelime hata oranı, EN+TR ayrı) + yapısal alanlarda CER (telefon/plaka/poliçe/
  referans — FR-STT-005); Levenshtein tabanlı.
- **Streaming partial/final (FR-STT-002):** olay akışında partial'lar final'dan önce gelir, her
  utterance için **tek kararlı final** bulunur; yapısal doğrulama.
- **Final-transcript gecikmesi:** end-of-utterance → final flush; **SAD §20 STT kalemi P95 ≤ 200 ms**
  (yeşil ≤ 100 ms) kapısına (gate) göre.
- **Confidence (FR-STT-006/007):** her segmentte confidence var mı (kapsama); düşük confidence
  hataları ayırt ediyor mu (kalibrasyon: doğru/yanlış ayrımı + ECE) — teyit turu (FR-STT-007) için temel.
- **Dil (FR-STT-003):** en az EN+TR kapsama; lehçe/dil konfigürasyonu.

Tasarım ilkeleri (CLAUDE.md):
- **Vendor-neutral:** Araç hiçbir sağlayıcı seçmez; ölçüt-tabanlı sonuç üretir. Nihai seçim 0.2.6'da.
- **stdlib-only:** Harici bağımlılık yok (gen_rtm.py / media_latency_probe.py disiplini).
- **Credential-free self-test:** `selftest` ve `samples/*.json` ile gerçek STT credential olmadan
  uçtan uca koşar (CI'da). Gerçek sağlayıcı çıktısı yalnız dışarıdan örnek JSON ile verilir; sır
  repoya YAZILMAZ (yalnız ortam değişkeni / `--url` ile canlı toplama, 0.3.x PoC).

Modlar:
  score    — Bir sağlayıcı örnek JSON'unu (utterance test seti) puanlar → özet + bütçe/doğruluk kapısı.
  compare  — Çok sağlayıcılı `score` çıktılarından karşılaştırma matrisi (markdown).
  selftest — Dahili deterministik örnekle WER/CER/gecikme/kalibrasyon çekirdeğini doğrular (credential'sız).

Örnek (sample) JSON şeması — `samples/*.json`:
{
  "provider": "stt-cloud-A",
  "config": {"sample_rate_hz": 8000, "model": "telephony", "data_retention": "NONE"},
  "utterances": [
    {
      "id": "tr-001", "language": "tr", "field_type": "general",
      "reference": "merhaba ben ahmet yılmaz",
      "hypothesis": "merhaba ben ahmet yılmaz",
      "confidence": 0.95,
      "speech_end_ms": 1000,
      "events": [
        {"t_ms": 240, "text": "merhaba", "is_final": false},
        {"t_ms": 1130, "text": "merhaba ben ahmet yılmaz", "is_final": true, "confidence": 0.95}
      ]
    }, ...
  ]
}
`field_type` ∈ {general, phone, plate, policy, reference}. Yapısal alanlar (general dışı) CER ile
ölçülür (FR-STT-005). `events`/`speech_end_ms` opsiyonel; yoksa gecikme/partial-final atlanır.
"""

from __future__ import annotations

import argparse
import json
import sys

# --- Eşikler (mühendislik varsayılanı; 0.3.x PoC'ta doğrulanır) -------------
# SAD §20 gecikme bütçesi — "STT final transcript ~100–200 ms (P95)" kalemi.
STT_FINAL_P95_BUDGET_MS = 200.0      # kapı (gate)
STT_FINAL_P95_GREEN_MS = 100.0       # yeşil bant
# Telefoni (8 kHz, gürültülü hat) konuşma WER beklentisi (illüstratif eşik).
WER_MAX = 0.15                       # kapı
WER_GREEN = 0.08                     # yeşil bant
# Yapısal alan (telefon/plaka/poliçe/referans) karakter hata oranı (FR-STT-005).
CER_STRUCT_MAX = 0.05                # kapı
CER_STRUCT_GREEN = 0.02              # yeşil bant

STRUCTURED_FIELDS = ("phone", "plate", "policy", "reference")
_PUNCT = ".,;:!?\"'()[]{}…„“”‘’—–-"


# ----------------------------------------------------------------------------
# Metin normalizasyonu + Levenshtein (saf — test edilebilir)
# ----------------------------------------------------------------------------
def _tr_lower(text: str) -> str:
    """Türkçe-duyarlı küçük harf (I→ı, İ→i) — EN için de güvenli (idempotent)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def _normalize_tokens(text: str, language: str) -> list[str]:
    """Boşlukla ayrılmış kelime token'larına indir: küçük harf + noktalama temizliği."""
    low = _tr_lower(text) if language == "tr" else text.lower()
    cleaned = "".join(" " if ch in _PUNCT else ch for ch in low)
    return cleaned.split()


def _normalize_chars(text: str, language: str) -> list[str]:
    """Yapısal alan CER'i için: boşluk + noktalama atılır, küçük harf (34 ABC 123 ≡ 34abc123)."""
    low = _tr_lower(text) if language == "tr" else text.lower()
    return [ch for ch in low if ch not in _PUNCT and not ch.isspace()]


def _levenshtein(a: list, b: list) -> int:
    """İki dizi (kelime ya da karakter listesi) arası düzenleme mesafesi (ekle/sil/değiştir)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def wer(reference: str, hypothesis: str, language: str = "en") -> float:
    """Kelime hata oranı = düzenleme mesafesi / referans kelime sayısı."""
    ref = _normalize_tokens(reference, language)
    hyp = _normalize_tokens(hypothesis, language)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str, language: str = "en") -> float:
    """Karakter hata oranı (yapısal alanlar) = karakter düzenleme mesafesi / referans karakter sayısı."""
    ref = _normalize_chars(reference, language)
    hyp = _normalize_chars(hypothesis, language)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


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


# ----------------------------------------------------------------------------
# Partial/final yapısal doğrulama (FR-STT-002)
# ----------------------------------------------------------------------------
def _partial_final_check(events: list[dict]) -> tuple[bool, str]:
    """Akışta ≥1 partial (is_final=false) tek kararlı final'dan (is_final=true) ÖNCE gelmeli."""
    if not events:
        return True, "olay-yok"  # gecikme/yapı dışı; sayıma katılmaz
    finals = [i for i, e in enumerate(events) if e.get("is_final")]
    partials = [i for i, e in enumerate(events) if not e.get("is_final")]
    if len(finals) != 1:
        return False, f"final-sayısı={len(finals)} (1 beklenir)"
    if not partials:
        return False, "partial-yok (FR-STT-002 streaming partial gerekir)"
    if partials[0] > finals[0]:
        return False, "final partial'dan önce geldi"
    # zaman damgaları monoton olmalı
    ts = [e.get("t_ms") for e in events if e.get("t_ms") is not None]
    if ts != sorted(ts):
        return False, "olay zaman damgaları monoton değil"
    return True, "ok"


def _finalization_latency_ms(utt: dict) -> float | None:
    """end-of-utterance → final flush gecikmesi (SAD §20). speech_end_ms ve final olayı gerekir."""
    events = utt.get("events") or []
    speech_end = utt.get("speech_end_ms")
    if speech_end is None:
        return None
    finals = [e for e in events if e.get("is_final") and e.get("t_ms") is not None]
    if not finals:
        return None
    return max(0.0, float(finals[-1]["t_ms"]) - float(speech_end))


# ----------------------------------------------------------------------------
# Sağlayıcı puanlama çekirdeği
# ----------------------------------------------------------------------------
def _verdict(measured: float | None, *, green: float, budget: float, lower_is_better: bool) -> str:
    if measured is None:
        return "VERİ-YOK"
    if lower_is_better:
        if measured <= green:
            return "YEŞİL"
        if measured <= budget:
            return "SARI"
        return "KIRMIZI"
    # higher is better (kullanılmıyor; ileride genişletilebilir)
    if measured >= green:
        return "YEŞİL"
    if measured >= budget:
        return "SARI"
    return "KIRMIZI"


def _ece(pairs: list[tuple[float, bool]], bins: int = 5) -> float | None:
    """Expected Calibration Error: |ortalama-confidence − doğruluk| (bin ağırlıklı)."""
    if not pairs:
        return None
    n = len(pairs)
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        bucket = [(c, ok) for c, ok in pairs if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if not bucket:
            continue
        avg_conf = sum(c for c, _ in bucket) / len(bucket)
        acc = sum(1 for _, ok in bucket if ok) / len(bucket)
        total += (len(bucket) / n) * abs(avg_conf - acc)
    return round(total, 4)


def summarize_provider(sample: dict) -> dict:
    """Bir sağlayıcı örnek setini puanla → özet + kapı (gate)."""
    utts = sample.get("utterances", [])
    by_lang: dict[str, list[float]] = {}
    struct_cer: list[float] = []
    struct_cer_by_field: dict[str, list[float]] = {}
    lat: list[float] = []
    pf_checked = pf_ok = 0
    conf_pairs: list[tuple[float, bool]] = []   # (confidence, exact_match)
    conf_present = conf_total = 0
    conf_correct: list[float] = []
    conf_incorrect: list[float] = []

    for u in utts:
        lang = u.get("language", "en")
        ftype = u.get("field_type", "general")
        ref, hyp = u.get("reference", ""), u.get("hypothesis", "")
        if ftype in STRUCTURED_FIELDS:
            e = cer(ref, hyp, lang)
            struct_cer.append(e)
            struct_cer_by_field.setdefault(ftype, []).append(e)
            exact = e == 0.0
        else:
            e = wer(ref, hyp, lang)
            by_lang.setdefault(lang, []).append(e)
            exact = e == 0.0

        # confidence kapsama + kalibrasyon (FR-STT-006/007)
        conf_total += 1
        conf = u.get("confidence")
        if conf is None:  # olay akışındaki final confidence'a düş
            finals = [ev.get("confidence") for ev in (u.get("events") or []) if ev.get("is_final")]
            conf = next((c for c in finals if c is not None), None)
        if conf is not None:
            conf_present += 1
            conf_pairs.append((float(conf), exact))
            (conf_correct if exact else conf_incorrect).append(float(conf))

        # final-transcript gecikmesi (SAD §20)
        d = _finalization_latency_ms(u)
        if d is not None:
            lat.append(d)

        # partial/final yapısı (FR-STT-002)
        if u.get("events"):
            pf_checked += 1
            ok, _ = _partial_final_check(u["events"])
            pf_ok += 1 if ok else 0

    # --- türetilmiş metrikler
    wer_by_lang = {k: round(sum(v) / len(v), 4) for k, v in by_lang.items()}
    all_wer = [x for v in by_lang.values() for x in v]
    wer_overall = round(sum(all_wer) / len(all_wer), 4) if all_wer else None
    # Kapı en kötü dil üzerinden: EN+TR zorunlu (SR-STT-003); zayıf dili genel WER maskelemesin.
    wer_worst = max(wer_by_lang.values()) if wer_by_lang else None
    cer_struct = round(sum(struct_cer) / len(struct_cer), 4) if struct_cer else None
    cer_by_field = {k: round(sum(v) / len(v), 4) for k, v in struct_cer_by_field.items()}

    s_lat = sorted(lat)
    lat_summary = {
        "p50": round(_percentile(s_lat, 50), 2) if s_lat else None,
        "p95": round(_percentile(s_lat, 95), 2) if s_lat else None,
        "p99": round(_percentile(s_lat, 99), 2) if s_lat else None,
        "max": round(s_lat[-1], 2) if s_lat else None,
        "samples": len(s_lat),
    }

    coverage = round(conf_present / conf_total, 4) if conf_total else None
    mean_c, mean_i = _mean(conf_correct), _mean(conf_incorrect)
    separation = round(mean_c - mean_i, 4) if (mean_c is not None and mean_i is not None) else None
    ece = _ece(conf_pairs)

    # --- kapılar (gate)
    lat_p95 = lat_summary["p95"]
    g_lat = _verdict(lat_p95, green=STT_FINAL_P95_GREEN_MS, budget=STT_FINAL_P95_BUDGET_MS,
                     lower_is_better=True)
    g_wer = _verdict(wer_worst, green=WER_GREEN, budget=WER_MAX, lower_is_better=True)
    g_cer = _verdict(cer_struct, green=CER_STRUCT_GREEN, budget=CER_STRUCT_MAX, lower_is_better=True)

    conf_pass = bool(coverage == 1.0 and (separation is None or separation > 0))
    conf_reason = ("kapsama tam + confidence hataları ayırıyor" if conf_pass else
                   ("confidence kapsaması eksik (FR-STT-006)" if coverage != 1.0 else
                    "confidence doğru/yanlış ayırmıyor (FR-STT-007 riski)"))
    pf_pass = (pf_checked == 0) or (pf_ok == pf_checked)

    # Kapı geçer: gecikme + WER + CER + confidence + partial/final hepsinde KIRMIZI/fail yok.
    hard = {
        "latency_p95_ms": {"budget": STT_FINAL_P95_BUDGET_MS, "green": STT_FINAL_P95_GREEN_MS,
                           "measured": lat_p95, "verdict": g_lat,
                           "pass": g_lat in ("YEŞİL", "SARI", "VERİ-YOK")},
        "wer": {"max": WER_MAX, "green": WER_GREEN, "measured": wer_worst,
                "basis": "en-kötü-dil", "verdict": g_wer,
                "pass": g_wer in ("YEŞİL", "SARI", "VERİ-YOK")},
        "cer_structured": {"max": CER_STRUCT_MAX, "green": CER_STRUCT_GREEN, "measured": cer_struct,
                           "verdict": g_cer, "pass": g_cer in ("YEŞİL", "SARI", "VERİ-YOK")},
        "confidence": {"coverage": coverage, "separation": separation, "ece": ece,
                       "pass": conf_pass, "reason": conf_reason},
        "partial_final": {"checked": pf_checked, "ok": pf_ok, "pass": pf_pass},
    }
    overall_pass = all(v["pass"] for v in hard.values())

    # Bütünsel renk: bir kapı KIRMIZI/fail → KIRMIZI; tümü YEŞİL → YEŞİL; arası SARI.
    numeric_verdicts = [g_lat, g_wer, g_cer]
    if not overall_pass:
        verdict = "KIRMIZI"
    elif all(v in ("YEŞİL", "VERİ-YOK") for v in numeric_verdicts) and conf_pass and pf_pass:
        verdict = "YEŞİL"
    else:
        verdict = "SARI"

    return {
        "provider": sample.get("provider", "?"),
        "config": sample.get("config", {}),
        "counts": {
            "utterances": len(utts),
            "by_language": {k: len(v) for k, v in by_lang.items()},
            "structured": len(struct_cer),
        },
        "accuracy": {
            "wer_overall": wer_overall,
            "wer_worst_language": wer_worst,
            "wer_by_language": wer_by_lang,
            "cer_structured": cer_struct,
            "cer_structured_by_field": cer_by_field,
        },
        "latency_final_ms": lat_summary,
        "confidence": {
            "coverage": coverage, "mean_correct": mean_c, "mean_incorrect": mean_i,
            "separation": separation, "ece": ece,
        },
        "partial_final": {"checked": pf_checked, "ok": pf_ok,
                          "pass_rate": round(pf_ok / pf_checked, 4) if pf_checked else None},
        "gates": hard,
        "verdict": verdict,
        "pass": overall_pass,
        "iz": "FR-STT-001..008; SR-STT-001..008; SAD §20 (STT final P95 ≤200ms); ADR-002; FR-RES-008",
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
        "| Sağlayıcı | WER EN | WER TR | CER yapısal | Final P95 (ms) | Conf ayrım | P/F ok% | Karar |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        acc = r.get("accuracy", {})
        wl = acc.get("wer_by_language", {})
        pf = r.get("partial_final", {})
        conf = r.get("confidence", {})
        pf_pct = "-" if pf.get("pass_rate") is None else f"{pf['pass_rate'] * 100:.0f}"
        lines.append(
            f"| {r.get('provider', '?')} "
            f"| {wl.get('en', '-')} | {wl.get('tr', '-')} "
            f"| {acc.get('cer_structured', '-')} "
            f"| {r.get('latency_final_ms', {}).get('p95', '-')} "
            f"| {conf.get('separation', '-')} "
            f"| {pf_pct} "
            f"| {badge.get(r.get('verdict'), '?')} {r.get('verdict', '?')} |"
        )
    lines.append("")
    lines.append(
        f"> Kapılar: final-transcript P95 ≤ {STT_FINAL_P95_BUDGET_MS:.0f} ms (SAD §20, yeşil ≤ "
        f"{STT_FINAL_P95_GREEN_MS:.0f}); WER ≤ {WER_MAX:.2f} (yeşil ≤ {WER_GREEN:.2f}); yapısal CER ≤ "
        f"{CER_STRUCT_MAX:.2f} (yeşil ≤ {CER_STRUCT_GREEN:.2f}). Değerler ölçüm koşuluna bağlı; "
        "sağlayıcı seçimi 0.2.6'da bütünsel yapılır (vendor-neutral)."
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

    # WER: 1 ikame / 4 kelime = 0.25
    w = wer("ben ahmet yılmaz geldim", "ben mehmet yılmaz geldim", "tr")
    chk("WER 1 ikame /4 = 0.25", abs(w - 0.25) < 1e-9, f"{w}")
    # WER: tam eşleşme = 0
    chk("WER tam eşleşme = 0", wer("hello world", "hello world", "en") == 0.0)
    # TR küçük harf: I/İ duyarlı (İSTANBUL ≡ istanbul)
    chk("TR lower İSTANBUL≡istanbul", wer("İSTANBUL", "istanbul", "tr") == 0.0,
        f"{wer('İSTANBUL', 'istanbul', 'tr')}")
    # CER yapısal: telefon "0532 111 22 33" vs "0532 111 22 53" → 1 karakter / 11
    c = cer("0532 111 22 33", "0532 111 22 53", "tr")
    chk("CER 1 hata /11 ≈ 0.0909", abs(c - 1 / 11) < 1e-9, f"{c}")
    # CER boşluk-duyarsız: "34 ABC 123" ≡ "34abc123"
    chk("CER boşluk/case-duyarsız plaka", cer("34 ABC 123", "34abc123", "tr") == 0.0)
    # Levenshtein simetri/temel
    chk("Levenshtein ['a']→['b'] = 1", _levenshtein(["a"], ["b"]) == 1)
    # percentile
    chk("p95 of 1..100 ≈ 95.05", abs(_percentile(list(range(1, 101)), 95) - 95.05) < 1e-6,
        f"{_percentile(list(range(1, 101)), 95)}")
    # partial/final: geçerli akış
    ok, _ = _partial_final_check([{"t_ms": 100, "is_final": False}, {"t_ms": 300, "is_final": True}])
    chk("partial→final geçerli", ok)
    # partial/final: iki final → hata
    ok2, r2 = _partial_final_check([{"t_ms": 100, "is_final": True}, {"t_ms": 300, "is_final": True}])
    chk("iki final → fail", not ok2, r2)
    # partial/final: partial yok → hata
    ok3, r3 = _partial_final_check([{"t_ms": 100, "is_final": True}])
    chk("partial yok → fail", not ok3, r3)
    # finalization latency: 1180 - 1000 = 180
    d = _finalization_latency_ms({"speech_end_ms": 1000,
                                  "events": [{"t_ms": 1180, "is_final": True}]})
    chk("final gecikme 180ms", d == 180.0, f"{d}")
    # ECE: mükemmel kalibrasyon (conf 1.0 hep doğru, 0.0 hep yanlış) → 0
    e = _ece([(1.0, True), (1.0, True), (0.0, False)])
    chk("ECE mükemmel ≈ 0", e == 0.0, f"{e}")

    # uçtan uca: küçük sağlayıcı seti puanla
    sample = {
        "provider": "selftest", "config": {"sample_rate_hz": 8000},
        "utterances": [
            {"id": "en-1", "language": "en", "field_type": "general",
             "reference": "i would like to check my balance",
             "hypothesis": "i would like to check my balance",
             "confidence": 0.96, "speech_end_ms": 1000,
             "events": [{"t_ms": 200, "is_final": False},
                        {"t_ms": 1090, "text": "...", "is_final": True, "confidence": 0.96}]},
            {"id": "tr-1", "language": "tr", "field_type": "general",
             "reference": "bakiyemi öğrenmek istiyorum",
             "hypothesis": "bakiyemi öğrenmek istiyorsun",  # 1 ikame /3
             "confidence": 0.62, "speech_end_ms": 1000,
             "events": [{"t_ms": 220, "is_final": False},
                        {"t_ms": 1150, "text": "...", "is_final": True, "confidence": 0.62}]},
            {"id": "tr-phone", "language": "tr", "field_type": "phone",
             "reference": "0532 111 22 33", "hypothesis": "0532 111 22 33",
             "confidence": 0.91, "speech_end_ms": 1000,
             "events": [{"t_ms": 240, "is_final": False},
                        {"t_ms": 1120, "text": "...", "is_final": True, "confidence": 0.91}]},
        ],
    }
    res = summarize_provider(sample)
    chk("score: WER(tr) ≈ 0.333", abs(res["accuracy"]["wer_by_language"]["tr"] - 1 / 3) < 1e-3,
        f"{res['accuracy']['wer_by_language']['tr']}")
    chk("score: confidence kapsama = 1.0", res["confidence"]["coverage"] == 1.0)
    chk("score: confidence ayrım > 0 (doğru>yanlış)", (res["confidence"]["separation"] or 0) > 0,
        f"sep={res['confidence']['separation']}")
    chk("score: partial/final %100", res["partial_final"]["pass_rate"] == 1.0)
    chk("score: final P95 ≤ 200ms kapı geçer", res["gates"]["latency_p95_ms"]["pass"])

    passed = sum(1 for _, c, _ in checks if c)
    for name, cond, detail in checks:
        mark = "✅" if cond else "❌"
        print(f"{mark} {name}" + (f"  ({detail})" if detail and not cond else ""))
    print(f"\n{passed}/{len(checks)} kontrol geçti.")
    return 0 if passed == len(checks) else 1


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="STT sağlayıcı değerlendirme hattı (WBS 0.2.2)")
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
