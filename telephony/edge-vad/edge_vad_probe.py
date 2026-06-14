#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edge_vad_probe.py — WBS 2.2.3 Edge VAD / endpointing (dinamik)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`telephony/rtp-jitter/` + `codec/` + `dtmf/` probe disipliniyle aynı; burada deterministik bir
EDGE VAD + DİNAMİK ENDPOINTER + BARGE-IN simülatörü (sanal saat, random YOK).

MEDIA GATEWAY EDGE (SAD §6/§7, L2) — 2.2.1 jitter buffer'ın verdiği düzgün 20ms/50fps kadansı tüketir:
  • VAD:         çerçeve enerjisi (dBov) → konuşma/sessizlik (adaptif noise floor + histerezis + hangover).
  • Endpointer:  DİNAMİK onay-sessizliği T_confirm = f(söz uzunluğu, önceki duraklama) → söz sonu (V2/V5/V6/V7).
  • Barge-in:    agent konuşurken kullanıcı onset'i ≤200ms algılanır, echo_guard ile yanlış tetik bastırılır (V8/V9).
  • Dead air:    sessizlik STT'ye gönderilmez; finalize yalnız endpoint'te → gereksiz STT/LLM azalır (V10/V11).
  • Metrikler:   silence/barge-in → BRD §15 → observability (V13).

Komutlar:
  validate              edge-vad-spec.json'ı invariant'lara + config profillerine karşı doğrular.
  simulate <sample>     Deterministik VAD/endpoint/barge-in simülatörü — enerji çerçeveleri → kararlar +
                        metrikler + HARD kapılar; →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek WebRTC VAD/native DSP yerine deterministik simülasyondur
(canlı sistemde Media Gateway C/C++/Rust native, SAD §21). Ham ses payload'ı/transkript/PII YOK.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "edge-vad-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "vad-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class MediaError(Exception):
    """Geçersiz/desteklenmeyen medya çerçevesi — sessizce kabul yok, reddet (V14)."""


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def percentile(sorted_vals, p):
    """Lineer-interpolasyon percentile (0.3.x / 2.2.1 ile birebir). sorted_vals artan."""
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
# VAD — adaptif noise floor + histerezis + hangover (V3/V4)
# ─────────────────────────────────────────────────────────────────────────────
def vad_classify(energy, p, agent_window=None):
    """Çerçeve enerjisi (dBov) → konuşma/sessizlik (bool listesi). Deterministik.

    agent_window=(start,end) verilirse o aralıkta eşik echo_guard_db kadar yükseltilir
    (agent playout sırasında echo yanlış barge-in tetiklemesin — V3/V9).
    """
    nf = float(p["init_noise_floor_dbov"])
    margin = p["speech_margin_db"]
    on_hys = p["onset_hysteresis_db"]
    off_hys = p["offset_hysteresis_db"]
    hangover = int(p["hangover_frames"])
    adapt = p["noise_adapt"]
    guard = p.get("barge_in_echo_guard_db", 0)

    speech = []
    in_speech = False
    silence_run = 0
    for i, e in enumerate(energy):
        if not isinstance(e, (int, float)):
            raise MediaError("bozuk çerçeve (enerji sayısal değil) → INVALID_REQUEST")
        thr = nf + margin
        if agent_window and agent_window[0] <= i < agent_window[1]:
            thr += guard
        in_agent = bool(agent_window and agent_window[0] <= i < agent_window[1])
        if not in_speech:
            if e >= thr + on_hys:
                in_speech = True
                silence_run = 0
            elif not in_agent:
                # yalnız gerçek sessizlikte (agent playout/echo DIŞINDA) noise floor uyarlanır —
                # aksi halde echo enerjisi tabanı yukarı çeker, guard'lı eşik gerçek barge-in'i kaçırır
                nf = (1 - adapt) * nf + adapt * e
        if in_speech:
            if e < thr - off_hys:
                silence_run += 1
                if silence_run > hangover:
                    in_speech = False
                    silence_run = 0
            else:
                silence_run = 0
        speech.append(in_speech)
    return speech


# ─────────────────────────────────────────────────────────────────────────────
# Dinamik endpointer (V2/V5/V6/V7)
# ─────────────────────────────────────────────────────────────────────────────
def dynamic_confirm_ms(seg_ms, pause_count, p):
    """Söz sonu onay-sessizliği T_confirm (ms) — bağlama göre dinamik (V2)."""
    T = p["base_confirm_ms"]
    if seg_ms < p["short_speech_ms"]:
        T += p["hesitation_extra_ms"]              # kısa/kesik söz → tereddüt olası → uzat
        if pause_count >= 1:
            T += p["hesitation_extra_ms"]          # hâlâ kısa + önceden duraklamış → daha çok bekle
    elif seg_ms >= p["long_speech_ms"]:
        T -= p["completeness_discount_ms"]          # uzun akıcı tur → tamamlanmış → hızlandır
    # orta uzunluk (short ≤ seg < long): base — kullanıcı duraklamadan sonra dolu bir cümle bitirdi,
    # tereddüt cezası uygulanmaz (gerçek söz sonu gecikmesi SAD §20 bütçesinde kalır)
    return clamp(T, p["min_confirm_ms"], p["max_confirm_ms"])


def endpoint_run(speech, p, frame_ms):
    """VAD konuşma/sessizlik akışı → söz sonu (endpoint) olayları (deterministik).

    Durum makinesi: IDLE → SPEAKING → PENDING(onay-sessizliği) → endpoint | SPEAKING(bridged).
    Döner: endpoints[{fire_frame, silence_start, T_confirm_ms, after_seg_ms}].
    """
    state = "IDLE"
    seg_start = None
    pause_count = 0
    pend_silence = 0
    pend_T = None
    pend_seg_ms = None
    pend_silence_start = None
    endpoints = []

    for i, s in enumerate(speech):
        if state == "IDLE":
            if s:
                state = "SPEAKING"
                seg_start = i
                pause_count = 0
        elif state == "SPEAKING":
            if not s:
                seg_ms = (i - seg_start) * frame_ms
                pend_T = dynamic_confirm_ms(seg_ms, pause_count, p)
                pend_seg_ms = seg_ms
                pend_silence = 1
                pend_silence_start = i
                state = "PENDING"
        elif state == "PENDING":
            if s:
                # onay-sessizliği dolmadan konuşma döndü → within-utterance pause köprülendi
                pause_count += 1
                state = "SPEAKING"
                seg_start = i
            else:
                pend_silence += 1
                if pend_silence * frame_ms >= pend_T:
                    endpoints.append({
                        "fire_frame": i,
                        "silence_start": pend_silence_start,
                        "T_confirm_ms": pend_T,
                        "after_seg_ms": pend_seg_ms,
                    })
                    state = "IDLE"
    return endpoints


def score_endpoints(endpoints, gt_utts, n_frames, frame_ms):
    """Endpoint kararlarını ground-truth söz yapısına karşı puanlar.

    gt_utts: söz listesi; her söz = konuşma koşusu (run) listesi [[s,e), ...].
    Aynı sözün ardışık koşuları arasındaki boşluk = within-utterance (hesitation) duraklaması →
    endpoint ATEŞLENMEMELİ (köprülenmeli). Sözün SON koşusundan sonraki sessizlik = gerçek tur sonu →
    endpoint ATEŞLENMELİ; gecikme = (fire − gerçek_son) * frame_ms.
    """
    within_gaps = []   # (gap_start, gap_end=continuation start)
    real_ends = []     # (last_run_end, region_end)
    for ui, u in enumerate(gt_utts):
        for k in range(len(u) - 1):
            within_gaps.append((u[k][1], u[k + 1][0]))
        last_end = u[-1][1]
        region_end = gt_utts[ui + 1][0][0] if ui + 1 < len(gt_utts) else n_frames
        real_ends.append((last_end, region_end))

    false_cuts = 0
    for (gs, ge) in within_gaps:
        for ep in endpoints:
            if gs <= ep["silence_start"] < ge and ep["fire_frame"] < ge:
                false_cuts += 1
                break

    latencies = []
    missed = 0
    for (last_end, region_end) in real_ends:
        fired = None
        for ep in endpoints:
            if last_end <= ep["silence_start"] < region_end:
                fired = ep
                break
        if fired is None:
            missed += 1
        else:
            latencies.append((fired["fire_frame"] - last_end) * frame_ms)

    latencies.sort()
    return {
        "within_gaps": len(within_gaps),
        "real_ends": len(real_ends),
        "false_cuts": false_cuts,
        "false_early_cut_rate": round(false_cuts / max(1, len(within_gaps)), 4),
        "missed": missed,
        "missed_endpoint_rate": round(missed / max(1, len(real_ends)), 4),
        "endpoint_latency_p95_ms": round(percentile(latencies, 0.95), 2),
        "endpoints_fired": len(endpoints),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Barge-in algılama (V8/V9)
# ─────────────────────────────────────────────────────────────────────────────
def detect_barge_in(speech, agent_window, min_frames):
    """Agent playout aralığında min_frames ardışık konuşma → barge-in onayı.
    Döner confirm_frame (onay çerçevesi) veya None."""
    run = 0
    start = agent_window[0] if agent_window else 0
    for i in range(start, len(speech)):
        if speech[i]:
            run += 1
            if run >= min_frames:
                return i
        else:
            run = 0
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tam simülasyon (bir sample)
# ─────────────────────────────────────────────────────────────────────────────
def simulate(sample, spec, params):
    energy = sample.get("energy_dbov", [])
    if not energy:
        raise MediaError("boş enerji akışı")
    frame_ms = sample.get("frame_ms", spec["media_profile"]["frame_ms"])
    agent_sp = sample.get("agent_speech")  # {"from":.., "to":..} | None
    agent_window = (agent_sp["from"], agent_sp["to"]) if agent_sp else None

    speech = vad_classify(energy, params, agent_window)
    n = len(speech)
    forwarded = sum(1 for s in speech if s)         # STT'ye iletilen (konuşma+hangover)
    suppressed = n - forwarded
    silence_total_ms = suppressed * frame_ms
    silence_ratio = round(suppressed / n, 4) if n else 0.0

    m = {
        "frames": n,
        "stt_forwarded": forwarded,
        "stt_suppressed": suppressed,
        "stt_suppression_ratio": silence_ratio,
        "silence_ratio": silence_ratio,
        "silence_total_ms": silence_total_ms,
        "scenario": [],
    }

    # ── endpoint senaryosu
    gt = sample.get("ground_truth", {})
    gt_utts = gt.get("utterances")
    if gt_utts:
        endpoints = endpoint_run(speech, params, frame_ms)
        es = score_endpoints(endpoints, gt_utts, n, frame_ms)
        m.update(es)
        m["utterances_emitted"] = es["endpoints_fired"]
        # dead-air bütçesi: iletilen ⊆ konuşma + hangover (no dead-air flood)
        true_speech = sum(e - s for u in gt_utts for (s, e) in u)
        n_runs = sum(len(u) for u in gt_utts)
        allowance = params["hangover_frames"] * (n_runs + len(gt_utts)) + 2
        m["true_speech_frames"] = true_speech
        m["dead_air_ok"] = (forwarded <= true_speech + allowance) and (suppressed > 0)
        m["scenario"].append("endpoint")

    # ── barge-in senaryosu
    if agent_window:
        user_onset = sample.get("user_barge_onset")  # int | None
        confirm = detect_barge_in(speech, agent_window, params["barge_in_min_speech_frames"])
        if user_onset is not None:
            if confirm is not None:
                m["barge_in_count"] = 1
                m["barge_in_latency_p95_ms"] = round((confirm - user_onset) * frame_ms, 2)
                m["false_barge_in"] = 0
            else:
                m["barge_in_count"] = 0
                m["barge_in_latency_p95_ms"] = 0.0
                m["false_barge_in"] = 0
                m["barge_in_missed"] = 1
        else:
            # echo/sessiz: barge-in OLMAMALI
            m["barge_in_count"] = 1 if confirm is not None else 0
            m["barge_in_latency_p95_ms"] = 0.0
            m["false_barge_in"] = 1 if confirm is not None else 0
        m["scenario"].append("barge_in")

    if "barge_in_count" not in m and not m["scenario"]:
        # yalnız dead-air senaryosu (söz yapısı/agent yok)
        m["dead_air_ok"] = suppressed > 0
        m["scenario"].append("dead_air")

    return m


def evaluate(spec, m):
    """Metrikleri HARD kapılara karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    F = []
    sc = set(m.get("scenario", []))

    if "endpoint" in sc:
        bud = g.get("endpoint_decision_latency_p95_ms", 250)
        green = g.get("green_endpoint_latency_ms", 200)
        lat = m.get("endpoint_latency_p95_ms", 0.0)
        band = "🟢" if lat <= green else ("🟡" if lat <= bud else "🔴")
        F.append((lat <= bud,
                  "V5 söz-sonu gecikmesi P95 %.0fms ≤ %.0fms (SAD §20 endpointing) %s" % (lat, bud, band)))
        F.append((m.get("false_early_cut_rate", 0.0) <= g.get("max_false_early_cut_rate", 0.05),
                  "V6 erken-kesme oranı %.3f ≤ %.3f (hesitation köprülendi)"
                  % (m.get("false_early_cut_rate", 0.0), g.get("max_false_early_cut_rate", 0.05))))
        F.append((m.get("missed_endpoint_rate", 0.0) <= g.get("max_missed_endpoint_rate", 0.0),
                  "V7 kaçırma/geç-kesme oranı %.3f ≤ %.3f"
                  % (m.get("missed_endpoint_rate", 0.0), g.get("max_missed_endpoint_rate", 0.0))))

    if "barge_in" in sc:
        bud = g.get("barge_in_detection_latency_p95_ms", 200)
        green = g.get("green_barge_in_latency_ms", 100)
        if m.get("user_barge_present", m.get("barge_in_missed") is None) and m.get("false_barge_in", 0) == 0 \
                and m.get("barge_in_count", 0) >= 1:
            lat = m.get("barge_in_latency_p95_ms", 0.0)
            band = "🟢" if lat <= green else ("🟡" if lat <= bud else "🔴")
            F.append((lat <= bud,
                      "V8 barge-in algılama gecikmesi P95 %.0fms ≤ %.0fms %s" % (lat, bud, band)))
        if m.get("barge_in_missed"):
            F.append((False, "V8 gerçek barge-in KAÇIRILDI (algılanamadı)"))
        F.append((m.get("false_barge_in", 0) <= g.get("max_false_barge_in_rate", 0.0),
                  "V9 yanlış barge-in %d ≤ %.0f (echo/gürültü debounce)"
                  % (m.get("false_barge_in", 0), g.get("max_false_barge_in_rate", 0.0))))

    if g.get("dead_air_must_be_suppressed", True) and "dead_air_ok" in m:
        F.append((m["dead_air_ok"],
                  "V10 ölü hava STT'ye gönderilmedi (sessizlik bastırıldı, iletilen ⊆ konuşma+hangover)"))

    return F


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise MediaError("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    """Spec varsayılanları + profil override → VAD/endpointer/barge-in parametreleri."""
    vad = spec.get("vad", {})
    ep = spec.get("endpointer", {})
    bi = spec.get("barge_in", {})
    out = {
        # VAD
        "init_noise_floor_dbov": profile.get("init_noise_floor_dbov", vad.get("init_noise_floor_dbov", -55)),
        "speech_margin_db": profile.get("speech_margin_db", vad.get("speech_margin_db", 12)),
        "onset_hysteresis_db": vad.get("onset_hysteresis_db", 3),
        "offset_hysteresis_db": vad.get("offset_hysteresis_db", 3),
        "hangover_frames": profile.get("hangover_frames", vad.get("hangover_frames", 3)),
        "noise_adapt": vad.get("noise_adapt", 0.05),
        "barge_in_echo_guard_db": vad.get("barge_in_echo_guard_db", 10),
        # endpointer
        "base_confirm_ms": profile.get("base_confirm_ms", ep.get("base_confirm_ms", 160)),
        "short_speech_ms": ep.get("short_speech_ms", 400),
        "long_speech_ms": ep.get("long_speech_ms", 800),
        "hesitation_extra_ms": ep.get("hesitation_extra_ms", 150),
        "completeness_discount_ms": ep.get("completeness_discount_ms", 30),
        "min_confirm_ms": ep.get("min_confirm_ms", 100),
        "max_confirm_ms": ep.get("max_confirm_ms", 480),
        # barge-in
        "barge_in_min_speech_frames": bi.get("min_speech_frames", 4),
    }
    return out


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
        except MediaError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    params = _params_from(spec, profile)

    try:
        m = simulate(sample, spec, params)
    except MediaError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    # barge-in mevcudiyetini evaluate için işaretle
    m["user_barge_present"] = sample.get("user_barge_onset") is not None
    F = evaluate(spec, m)

    summ = "simulate[%s] senaryo=%s | %d çerçeve: %d iletildi / %d bastırıldı (sessizlik %.0f%%)" % (
        name, "+".join(m["scenario"]), m["frames"], m["stt_forwarded"], m["stt_suppressed"],
        m["silence_ratio"] * 100)
    if "endpoint" in m["scenario"]:
        summ += " | söz-sonu P95 %.0fms, erken-kesme %.0f%%, %d söz emit" % (
            m.get("endpoint_latency_p95_ms", 0), m.get("false_early_cut_rate", 0) * 100,
            m.get("utterances_emitted", 0))
    if "barge_in" in m["scenario"]:
        summ += " | barge-in %d (gecikme %.0fms, yanlış %d)" % (
            m.get("barge_in_count", 0), m.get("barge_in_latency_p95_ms", 0), m.get("false_barge_in", 0))
    print(summ)
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

    _check(R, spec.get("wbs") == "2.2.3", "spec.wbs == 2.2.3")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── V12: medya profili (8kHz/20ms, no-transcode)
    mp = spec.get("media_profile", {})
    _check(R, mp.get("sample_rate_hz") == 8000, "V12 medya 8 kHz")
    _check(R, mp.get("frame_ms") == 20 and mp.get("frames_per_sec") == 50, "V12 20ms/50fps çerçeve")
    _check(R, mp.get("samples_per_frame") == 160, "V12 160 örnek/çerçeve")
    _check(R, mp.get("no_transcode") is True and mp.get("resample_points_max", 99) <= 1,
           "V12 no-transcode, ≤1 resample noktası")

    # ── V1: edge placement
    ep_pl = spec.get("edge_placement", {})
    _check(R, ep_pl.get("at_edge") is True, "V1 VAD/endpointing edge'de")
    _check(R, "media-gateway" in str(ep_pl.get("layer", "")), "V1 media gateway katmanı")

    # ── V3/V4: VAD sözleşmesi
    vad = spec.get("vad", {})
    _check(R, isinstance(vad.get("speech_margin_db"), (int, float)) and vad.get("speech_margin_db") > 0,
           "V3 speech_margin_db pozitif")
    _check(R, vad.get("onset_hysteresis_db", 0) > 0 and vad.get("offset_hysteresis_db", 0) > 0,
           "V3 onset/offset histerezisi pozitif")
    _check(R, isinstance(vad.get("hangover_frames"), int) and vad.get("hangover_frames") >= 1,
           "V4 hangover_frames ≥1 (mikro-duraklama köprüsü)")
    _check(R, 0 < vad.get("noise_adapt", 0) < 1, "V3 noise_adapt (0,1)")
    _check(R, vad.get("barge_in_echo_guard_db", 0) > 0, "V9 echo_guard_db pozitif")

    # ── V2: dinamik endpointer sözleşmesi
    ep = spec.get("endpointer", {})
    _check(R, ep.get("dynamic") is True, "V2 endpointer dinamik")
    for key in ("base_confirm_ms", "short_speech_ms", "long_speech_ms",
                "hesitation_extra_ms", "completeness_discount_ms", "min_confirm_ms", "max_confirm_ms"):
        _check(R, isinstance(ep.get(key), (int, float)), "V2 endpointer.%s mevcut" % key)
    _check(R, 0 < ep.get("min_confirm_ms", 0) <= ep.get("base_confirm_ms", 0) <= ep.get("max_confirm_ms", 0),
           "V2 0 < min ≤ base ≤ max onay-sessizliği")
    _check(R, ep.get("hesitation_extra_ms", 0) > 0, "V2 hesitation_extra pozitif (tereddütte uzar)")
    _check(R, ep.get("short_speech_ms", 0) < ep.get("long_speech_ms", 0),
           "V2 short_speech < long_speech eşikleri")

    # ── V8/V9: barge-in
    bi = spec.get("barge_in", {})
    _check(R, isinstance(bi.get("min_speech_frames"), int) and bi.get("min_speech_frames") >= 2,
           "V9 barge-in min_speech_frames ≥2 (debounce)")
    _check(R, bi.get("echo_guard") is True, "V9 barge-in echo_guard açık")

    # ── V10/V11: dead air
    da = spec.get("dead_air", {})
    _check(R, da.get("suppress_silence") is True, "V10 sessizlik bastırma açık")
    _check(R, da.get("finalize_only_at_endpoint") is True, "V11 finalize yalnız endpoint'te")

    # ── V5/V6/V7/V8/V9/V10: kapılar
    g = spec.get("gates", {})
    _check(R, isinstance(g.get("endpoint_decision_latency_p95_ms"), (int, float))
           and g.get("endpoint_decision_latency_p95_ms") > 0, "V5 endpoint gecikme bütçesi pozitif")
    _check(R, g.get("green_endpoint_latency_ms", 1e9) <= g.get("endpoint_decision_latency_p95_ms", 0),
           "V5 green ≤ endpoint bütçesi")
    _check(R, g.get("endpoint_decision_latency_p95_ms", 0) <= 250,
           "V5 endpoint bütçesi SAD §20 bandıyla tutarlı (≤250ms)")
    _check(R, 0 < g.get("max_false_early_cut_rate", 0) < 1, "V6 max_false_early_cut_rate (0,1)")
    _check(R, g.get("max_missed_endpoint_rate", -1) >= 0, "V7 max_missed_endpoint_rate ≥0")
    _check(R, g.get("barge_in_detection_latency_p95_ms", 0) <= 200,
           "V8 barge-in algılama bütçesi ≤200ms (ADR-005/NFR 10.1)")
    _check(R, g.get("green_barge_in_latency_ms", 1e9) <= g.get("barge_in_detection_latency_p95_ms", 0),
           "V8 green ≤ barge-in bütçesi")
    _check(R, g.get("max_false_barge_in_rate", -1) >= 0, "V9 max_false_barge_in_rate ≥0")
    _check(R, g.get("dead_air_must_be_suppressed") is True, "V10 dead_air bastırma zorunlu")

    # ── V13: metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"endpoint_latency_p95_ms", "barge_in_latency_p95_ms", "silence_ratio",
               "false_early_cut_rate"} <= emitted, "V13 BRD §15/endpoint metrikleri yayılır")
    mo = me.get("maps_to_observability", {})
    _check(R, mo.get("silence_total_ms") == "silence_duration_ms"
           and mo.get("barge_in_count") == "barge_in_total",
           "V13 metrikler 0.4.7 observability-spec'e eşlenir")

    # ── V14: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "V14 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "V14 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_frame") == "INVALID_REQUEST"
           and mapping.get("media_transport_lost") == "UNAVAILABLE"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "V14 bozuk-çerçeve→INVALID, taşıma→UNAVAILABLE, bölge→REGION_VIOLATION")

    # ── V14: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "V14 residency region pin")
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "V14 ham ses payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "V14 transkript spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 14,
           "invariant kataloğu ≥14 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILES_CFG):
        hits += _scan_secrets(_load(PROFILES_CFG))
    _check(R, not hits, "V14 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 VAD profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, bool(p.get("region")), "V14 config %s bölge pini var" % p.get("name"))
            bc = p.get("base_confirm_ms", ep.get("base_confirm_ms"))
            _check(R, ep.get("min_confirm_ms", 0) <= bc <= ep.get("max_confirm_ms", 1e9),
                   "config %s base_confirm [min,max] içinde" % p.get("name"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest yardımcıları — sentetik enerji akışı üreteci
# ─────────────────────────────────────────────────────────────────────────────
SPEECH_DBOV = -18.0
SILENCE_DBOV = -52.0
ECHO_DBOV = -34.0


def _frames_from_script(script, e_speech=SPEECH_DBOV, e_silence=SILENCE_DBOV):
    """script = [("speech"|"silence", n_frames), ...] → (energy_list, gt_utterances).
    Ardışık 'speech' blokları aralarında 'silence' ile ayrılır; bir söze ait koşular
    çağıran tarafından ground_truth ile verilir. Burada yalnız enerji + run sınırları döner."""
    energy = []
    runs = []  # [s,e)
    for kind, n in script:
        start = len(energy)
        if kind == "speech":
            energy.extend([e_speech] * n)
            runs.append([start, start + n])
        else:
            energy.extend([e_silence] * n)
    return energy, runs


def _params(spec, **over):
    cfg = {"name": "_t", "region": "${R}"}
    cfg.update(over)
    return _params_from(spec, cfg)


def selftest():
    spec = _load(SPEC_PATH)
    frame_ms = spec["media_profile"]["frame_ms"]
    P = _params(spec)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── percentile (0.3.x ile birebir) ──────────────────────────────────────────
    case(abs(percentile([10, 20, 30, 40], 0.95) - 38.5) < 1e-6, "percentile P95 lineer-interp")
    case(percentile([], 0.95) == 0.0 and percentile([7], 0.95) == 7.0, "percentile boş/tekil")

    # ── dinamik confirm (V2) ─────────────────────────────────────────────────────
    t_long = dynamic_confirm_ms(900, 0, P)
    t_med = dynamic_confirm_ms(500, 0, P)
    t_short = dynamic_confirm_ms(200, 0, P)
    t_short_p = dynamic_confirm_ms(200, 1, P)
    case(t_long < t_med < t_short, "V2 uzun-söz<orta<kısa onay-sessizliği (dinamik)")
    case(t_short_p > t_short, "V2 önceki duraklama → daha uzun bekle")
    case(P["min_confirm_ms"] <= t_long and t_short_p <= P["max_confirm_ms"], "V2 T_confirm [min,max] clamp")
    case(t_long == P["base_confirm_ms"] - P["completeness_discount_ms"], "V2 uzun-akıcı tur completeness indirimi")

    # ── VAD: temiz konuşma/sessizlik (V3/V4) ─────────────────────────────────────
    energy, runs = _frames_from_script([("silence", 5), ("speech", 40), ("silence", 30)])
    sp = vad_classify(energy, P)
    case(any(sp) and not sp[0] and not sp[-1], "V3 VAD konuşmayı bulur, kenar sessizlik")
    fwd = sum(sp)
    case(40 <= fwd <= 40 + P["hangover_frames"] + 1, "V4 iletilen ≈ konuşma + hangover")

    # ── micro-pause hangover köprüsü (V4) ────────────────────────────────────────
    e2, _ = _frames_from_script([("speech", 20), ("silence", 2), ("speech", 20), ("silence", 20)])
    sp2 = vad_classify(e2, P)
    # 2 çerçevelik boşluk hangover(3) içinde → konuşma kesilmez
    case(all(sp2[20:22]), "V4 2-çerçeve mikro-boşluk hangover ile köprülendi")

    # ── endpoint: tek uzun söz → hızlı, doğru söz sonu (V5/V7) ────────────────────
    eg, rg = _frames_from_script([("silence", 4), ("speech", 45), ("silence", 25)])
    sample = {"energy_dbov": eg, "ground_truth": {"utterances": [[rg[0]]]}}
    m = simulate(sample, spec, P)
    case(m["missed_endpoint_rate"] == 0.0, "V7 uzun söz: söz sonu kaçırılmaz")
    case(m["endpoint_latency_p95_ms"] <= spec["gates"]["endpoint_decision_latency_p95_ms"],
         "V5 uzun söz gecikmesi bütçe içinde")
    case(m["false_early_cut_rate"] == 0.0, "V6 tek koşulu sözde erken kesme yok")
    case(all(ok for ok, _ in evaluate(spec, m)), "uzun söz tüm endpoint kapılarını geçer")

    # ── endpoint: hesitation duraklaması köprülenir (V6) ─────────────────────────
    #   kısa söz(15) + 12-çerçeve(240ms) within-utterance boşluk + söz(20) = TEK söz, 2 koşu
    eh, _ = _frames_from_script([("silence", 4), ("speech", 15), ("silence", 12), ("speech", 20), ("silence", 28)])
    r1s = 4
    runs_h = [[r1s, r1s + 15], [r1s + 15 + 12, r1s + 15 + 12 + 20]]
    sample_h = {"energy_dbov": eh, "ground_truth": {"utterances": [runs_h]}}
    mh = simulate(sample_h, spec, P)
    case(mh["false_early_cut_rate"] == 0.0, "V6 hesitation duraklaması köprülendi (erken kesme yok)")
    case(mh["missed_endpoint_rate"] == 0.0, "V7 hesitation sonrası gerçek son yakalandı")
    case(mh["within_gaps"] == 1 and mh["real_ends"] == 1, "V6 1 hesitation boşluğu + 1 gerçek son")
    case(all(ok for ok, _ in evaluate(spec, mh)), "hesitation akışı tüm kapıları geçer")

    # ── endpoint: iki ayrı söz, ikisi de yakalanır (V7) ──────────────────────────
    et2, _ = _frames_from_script([("speech", 40), ("silence", 30), ("speech", 35), ("silence", 25)])
    u1 = [[0, 40]]
    u2 = [[70, 105]]
    sample2 = {"energy_dbov": et2, "ground_truth": {"utterances": [u1, u2]}}
    m2 = simulate(sample2, spec, P)
    case(m2["utterances_emitted"] == 2 and m2["missed_endpoint_rate"] == 0.0, "V7/V11 iki söz iki endpoint")

    # ── dead-air bastırma (V10/V11) ──────────────────────────────────────────────
    case(m["stt_suppressed"] > 0 and m["dead_air_ok"], "V10 sessizlik bastırıldı (dead air STT'ye gitmez)")
    case(m["utterances_emitted"] == 1, "V11 finalize yalnız endpoint'te (1 söz → 1 emit)")

    # ── barge-in algılama (V8) ───────────────────────────────────────────────────
    #   agent 10..60 konuşuyor (echo), kullanıcı 30'da araya girer (gerçek ses)
    eb = [SILENCE_DBOV] * 10 + [ECHO_DBOV] * 50 + [SILENCE_DBOV] * 10
    for i in range(30, 50):
        eb[i] = SPEECH_DBOV  # kullanıcı barge-in (echo guard'ı aşar)
    sample_b = {"energy_dbov": eb, "agent_speech": {"from": 10, "to": 60}, "user_barge_onset": 30}
    mb = simulate(sample_b, spec, P)
    mb["user_barge_present"] = True
    case(mb["barge_in_count"] == 1 and mb["false_barge_in"] == 0, "V8 gerçek barge-in algılandı")
    case(mb["barge_in_latency_p95_ms"] <= spec["gates"]["barge_in_detection_latency_p95_ms"],
         "V8 barge-in gecikmesi ≤ bütçe")
    case(all(ok for ok, _ in evaluate(spec, mb)), "barge-in akışı kapıları geçer")

    # ── echo-only: yanlış barge-in YOK (V9) ──────────────────────────────────────
    ee = [SILENCE_DBOV] * 10 + [ECHO_DBOV] * 50 + [SILENCE_DBOV] * 10
    sample_e = {"energy_dbov": ee, "agent_speech": {"from": 10, "to": 60}, "user_barge_onset": None}
    me = simulate(sample_e, spec, P)
    me["user_barge_present"] = False
    case(me["false_barge_in"] == 0 and me["barge_in_count"] == 0, "V9 echo-only → yanlış barge-in yok")
    case(all(ok for ok, _ in evaluate(spec, me)), "echo-only kapıyı geçer")

    # ── degraded: aşırı gürültü VAD'ı yanıltır → dead air + kaçırma (kapı eler) ───
    ed = [SPEECH_DBOV] * 90  # 'sessizlik' yok → her şey konuşma; gerçek son yok
    sample_d = {"energy_dbov": ed, "ground_truth": {"utterances": [[[10, 30]], [[50, 70]]]}}
    md = simulate(sample_d, spec, P)
    Fd = evaluate(spec, md)
    case(not all(ok for ok, _ in Fd), "degraded akış en az bir kapıyı eler")

    # ── geçersiz çerçeve reddi (V14) ─────────────────────────────────────────────
    case(_raises(lambda: vad_classify([SPEECH_DBOV, "x", SILENCE_DBOV], P)),
         "V14 sayısal-olmayan enerji → reddedilir")
    case(_raises(lambda: simulate({"energy_dbov": []}, spec, P)), "V14 boş enerji akışı → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["media_profile"]["no_transcode"] = False
    case(_validate_obj(s) != 0, "V12 no_transcode kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["edge_placement"]["at_edge"] = False
    case(_validate_obj(s) != 0, "V1 edge_placement kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["endpointer"]["dynamic"] = False
    case(_validate_obj(s) != 0, "V2 endpointer dinamik değil → validate eler")
    s = json.loads(json.dumps(spec)); s["endpointer"]["min_confirm_ms"] = 999
    case(_validate_obj(s) != 0, "V2 min>base onay-sessizliği → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["green_endpoint_latency_ms"] = 999
    case(_validate_obj(s) != 0, "V5 green>bütçe → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["endpoint_decision_latency_p95_ms"] = 400
    case(_validate_obj(s) != 0, "V5 endpoint bütçesi SAD §20 bandını aşar → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["barge_in_detection_latency_p95_ms"] = 300
    case(_validate_obj(s) != 0, "V8 barge-in bütçesi >200ms → validate eler")
    s = json.loads(json.dumps(spec)); s["dead_air"]["suppress_silence"] = False
    case(_validate_obj(s) != 0, "V10 sessizlik bastırma kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "V14 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["raw_payload_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "V14 ham-payload-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["vad"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "V14 literal secret → validate eler")

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
    except MediaError:
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
    print("""edge-vad-spec.json beklenen şekli (WBS 2.2.3):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability}
  media_profile{sample_rate_hz=8000, frame_ms=20, frames_per_sec=50,
                samples_per_frame=160, no_transcode=true, resample_points_max≤1}   (V12)
  edge_placement{at_edge=true, layer=media-gateway-L2}                              (V1)
  vad{init_noise_floor_dbov, speech_margin_db, onset/offset_hysteresis_db,
      hangover_frames, noise_adapt, barge_in_echo_guard_db}                        (V3,V4)
  endpointer{dynamic=true, base_confirm_ms, short_speech_ms, long_speech_ms,
             hesitation_extra_ms, completeness_discount_ms, min/max_confirm_ms}    (V2)
  barge_in{min_speech_frames, echo_guard=true, detection_budget_ms,
           green_detection_ms}                                                     (V8,V9)
  dead_air{suppress_silence=true, finalize_only_at_endpoint=true}                   (V10,V11)
  gates{endpoint_decision_latency_p95_ms≤250, green_endpoint_latency_ms≤bütçe,
        max_false_early_cut_rate, max_missed_endpoint_rate,
        barge_in_detection_latency_p95_ms≤200, green_barge_in_latency_ms≤bütçe,
        max_false_barge_in_rate, dead_air_must_be_suppressed=true}             (V5,V6,V7,V8,V9,V10)
  metrics{emitted[], maps_to_observability{silence_total_ms→silence_duration_ms, ...}}  (V13)
  error_taxonomy{mapping→API §11.6}                                              (V14)
  residency{region_pin_required=true}                                             (V14)
  pii{raw_payload_in_spec_forbidden, transcript_in_spec_forbidden}                (V14)
  invariants[≥14]{id, desc, trace}

config/vad-profiles.json: profiles[]{name, integration_mode, init_noise_floor_dbov?,
  speech_margin_db?, hangover_frames?, base_confirm_ms?, region}

simulate sample: {name, profile | profile_obj, frame_ms?, expect, expected?{metrik:değer},
  energy_dbov[] (dBov/çerçeve),
  ground_truth?{utterances[[[s,e),...], ...]}  (söz=koşu listesi; koşular-arası boşluk=hesitation),
  agent_speech?{from,to}, user_barge_onset?(int|null)}

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: edge_vad_probe.py simulate <sample.json>")
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
