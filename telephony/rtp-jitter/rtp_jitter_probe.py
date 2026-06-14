#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rtp_jitter_probe.py — WBS 2.2.1 RTP/medya sonlandırma + jitter buffer

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`telephony/managed-cpaas/` + `byoc-sip/` + `dtmf/` probe disipliniyle aynı; `LogNormalComponent`
yerine burada deterministik bir RTP jitter buffer SİMÜLATÖRÜ (sanal saat, random YOK).

MEDIA GATEWAY INGRESS YOLU (RTP termination + adaptif jitter buffer; SAD §6/§7, L2):
  • Sonlandırma:  RTP paketleri (seq/ts/ssrc/marker) → wrap-güvenli sıralama + reorder (J1/J9).
  • Jitter buffer: ölçülen interarrival jitter'a (RFC 3550 J) göre adaptif playout gecikmesi;
                   geç paket atılır (J4), kayıp slot concealment ile doldurulur (J5);
                   downstream'e DÜZGÜN 20ms/50fps kadans (J6).
  • Metrikler:    jitter/loss/concealment/eklenen-gecikme → BRD §15 → observability (J7).

Komutlar:
  validate              rtp-jitter-spec.json'ı invariant'lara + config profillerine karşı doğrular.
  simulate <sample>     Deterministik jitter buffer simülatörü — paket gelişleri → playout +
                        metrikler (jitter/loss/concealment/eklenen-gecikme) + HARD kapılar; →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek RTP/WebRTC yığını yerine deterministik simülasyondur
(canlı sistemde Media Gateway C/C++/Rust native, SAD §21). Ham RTP ses payload'ı/PII YOK.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "rtp-jitter-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "jitter-profiles.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
MODES = {"adaptive", "fixed"}
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
    """Geçersiz/desteklenmeyen medya/RTP — sessizce kabul yok, reddet (J12)."""


# ─────────────────────────────────────────────────────────────────────────────
# Wrap-güvenli RTP aritmetiği (RFC 3550 — J9)
# ─────────────────────────────────────────────────────────────────────────────
def seq_diff(a, b, bits=16):
    """16-bit modüler imzalı fark a-b (RFC 1982 seri-sayı). Wraparound güvenli."""
    half = 1 << (bits - 1)
    return ((a - b + half) % (1 << bits)) - half


def ts_diff(a, b, bits=32):
    """32-bit modüler imzalı fark a-b (RTP timestamp, örnek birimi)."""
    half = 1 << (bits - 1)
    return ((a - b + half) % (1 << bits)) - half


def percentile(sorted_vals, p):
    """Lineer-interpolasyon percentile (0.3.1/0.3.2 ile birebir). sorted_vals artan."""
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
# RFC 3550 interarrival jitter (J7)
# ─────────────────────────────────────────────────────────────────────────────
def rfc3550_jitter(packets, clock_rate, gain=0.0625):
    """Geliş sırasına göre RFC 3550 interarrival jitter (ms) tahmini.
    transit_i = arrival_i(ms) - ts_i(ms); D = |transit_j - transit_i|; J += (D - J)*gain.
    Deterministik; randomsuz."""
    if not packets:
        return 0.0
    order = sorted(packets, key=lambda p: (p["arrival_ms"], p["seq"]))
    anchor_ts = order[0]["ts"]
    J = 0.0
    prev_transit = None
    for p in order:
        rel_ts_ms = ts_diff(p["ts"], anchor_ts) * 1000.0 / clock_rate
        transit = p["arrival_ms"] - rel_ts_ms
        if prev_transit is not None:
            d = abs(transit - prev_transit)
            J += (d - J) * gain
        prev_transit = transit
    return J


# ─────────────────────────────────────────────────────────────────────────────
# Jitter buffer simülatörü (deterministik — J1..J6)
# ─────────────────────────────────────────────────────────────────────────────
def simulate_jitter_buffer(packets, params, clock_rate, frame_ms):
    """RTP paket geliş dizisini adaptif jitter buffer üzerinden oynatır (deterministik).

    Paket alanları: seq, ts (RTP örnek birimi), arrival_ms (buffer'a varış, akış başına göre),
                    marker? (talk-spurt başı), ssrc?.
    Kayıp paket = ilgili ts slotunda paket YOK (boşluk). Out-of-order = arrival sırası ts sırasından farklı.

    Döner metrik dict: jitter_ms, nominal_depth_ms, total_slots, played, late_discarded, lost,
                       concealed, concealment_ratio, packet_loss_rate, late_discard_rate,
                       reordered, reorder_absorbed, added_latency_p95_ms, cadence_continuous.
    """
    if not packets:
        raise MediaError("boş RTP akışı")
    for p in packets:
        if "seq" not in p or "ts" not in p or "arrival_ms" not in p:
            raise MediaError("bozuk RTP paketi (seq/ts/arrival_ms eksik) → INVALID_REQUEST")

    mode = params.get("mode", "adaptive")
    if mode not in MODES:
        raise MediaError("desteklenmeyen jitter buffer modu: %r" % mode)

    samples_per_frame = int(clock_rate * frame_ms / 1000)  # 8000*20/1000 = 160

    # ── adaptif derinlik (J2): target = clamp(base + factor*J, min, max)
    J = rfc3550_jitter(packets, clock_rate, params.get("rfc3550_jitter_gain", 0.0625))
    base = params["base_depth_ms"]
    if mode == "adaptive":
        depth = base + params.get("target_factor", 2.0) * J
        depth = max(params["min_depth_ms"], min(params["max_depth_ms"], depth))
    else:  # fixed
        depth = base
    D = depth

    # ── anchor: ilk GELEN paket (gerçek buffer ilk pakette saatini başlatır)
    order = sorted(packets, key=lambda p: (p["arrival_ms"], p["seq"]))
    anchor_arrival = order[0]["arrival_ms"]
    anchor_ts = order[0]["ts"]

    # ── beklenen slot kümesi: min..max ts arası frame_ms (örnek) adımlarla
    ts_offsets = [ts_diff(p["ts"], anchor_ts) for p in packets]
    lo_off, hi_off = min(ts_offsets), max(ts_offsets)
    # her slot anchor_ts + k*samples_per_frame (k tam sayı)
    by_ts = {}
    for p in packets:
        off = ts_diff(p["ts"], anchor_ts)
        if off % samples_per_frame != 0:
            raise MediaError("RTP ts hizasız (frame sınırı değil): off=%d" % off)
        by_ts.setdefault(off, p)  # aynı ts'te ilk gelen (yinelenen drop)

    slots = list(range(lo_off, hi_off + 1, samples_per_frame))
    total_slots = len(slots)

    # ── reorder tespiti: geliş sırasında ts monotonik değilse inversiyon
    arr_order_ts = [ts_diff(p["ts"], anchor_ts) for p in order]
    reordered = 0
    max_seen = -(1 << 62)
    for off in arr_order_ts:
        if off < max_seen:
            reordered += 1
        else:
            max_seen = off

    played = 0
    late_discarded = 0
    lost = 0
    buffering = []  # eklenen gecikme (ms) — yalnız zamanında oynatılanlar
    reorder_absorbed = True

    for off in slots:
        scheduled = anchor_arrival + D + off * 1000.0 / clock_rate
        p = by_ts.get(off)
        if p is None:
            lost += 1  # ağ kaybı → concealment
            continue
        if p["arrival_ms"] <= scheduled + 1e-9:
            played += 1
            buffering.append(scheduled - p["arrival_ms"])
        else:
            late_discarded += 1  # playout son tarihinden sonra geldi → at (J4)
            # reorder'a bağlı geç gelme reorder'ın absorbe EDİLEMEDİĞİ anlamına gelir
            if any(ts_diff(q["ts"], anchor_ts) > off and q["arrival_ms"] < p["arrival_ms"] for q in packets):
                reorder_absorbed = False

    concealed = lost + late_discarded
    concealment_ratio = concealed / total_slots if total_slots else 0.0
    packet_loss_rate = lost / total_slots if total_slots else 0.0
    late_discard_rate = late_discarded / total_slots if total_slots else 0.0
    buffering.sort()
    added_p95 = percentile(buffering, 0.95)

    return {
        "jitter_ms": round(J, 3),
        "nominal_depth_ms": round(D, 2),
        "samples_per_frame": samples_per_frame,
        "total_slots": total_slots,
        "played": played,
        "late_discarded": late_discarded,
        "lost": lost,
        "concealed": concealed,
        "concealment_ratio": round(concealment_ratio, 4),
        "packet_loss_rate": round(packet_loss_rate, 4),
        "late_discard_rate": round(late_discard_rate, 4),
        "reordered": reordered,
        "reorder_absorbed": reorder_absorbed,
        "added_latency_p95_ms": round(added_p95, 2),
        # kadans her zaman sürekli: her slot ya gerçek ya concealed çerçeve üretir (J6)
        "cadence_continuous": (played + concealed) == total_slots,
    }


def evaluate(spec, params, m):
    """Metrikleri HARD kapılara karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    budget = g.get("jitter_buffer_budget_ms", 80)
    green = g.get("green_added_latency_ms", 50)
    max_conc = g.get("max_concealment_ratio", 0.05)
    max_depth = spec.get("jitter_buffer", {}).get("max_depth_ms", 120)
    F = []
    # J3 eklenen gecikme bütçesi
    band = "🟢" if m["added_latency_p95_ms"] <= green else ("🟡" if m["added_latency_p95_ms"] <= budget else "🔴")
    F.append((m["added_latency_p95_ms"] <= budget,
              "J3 eklenen playout gecikmesi P95 %.1fms ≤ %dms bütçesi %s" % (m["added_latency_p95_ms"], budget, band)))
    # J2 nominal derinlik sınırlı
    F.append((m["nominal_depth_ms"] <= max_depth + 1e-9,
              "J2 nominal derinlik %.1fms ≤ max %dms (sınırlı)" % (m["nominal_depth_ms"], max_depth)))
    # J5 concealment kapısı
    F.append((m["concealment_ratio"] <= max_conc,
              "J5 concealment oranı %.3f ≤ %.3f (kayıp+geç gizleme)" % (m["concealment_ratio"], max_conc)))
    # J6 sürekli kadans
    F.append((m["cadence_continuous"], "J6 downstream kadansı sürekli (her slot bir çerçeve)"))
    # J1 reorder absorbe
    if g.get("reorder_must_be_absorbed", True):
        F.append((m["reorder_absorbed"],
                  "J1 reorder absorbe edildi (%d out-of-order paket doğru sırada)" % m["reordered"]))
    return F


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise MediaError("bilinmeyen profil: %s" % name)


def _params_from(spec, profile):
    """Spec varsayılanları + profil override → jitter buffer parametreleri."""
    jb = spec.get("jitter_buffer", {})
    out = {
        "mode": profile.get("mode", jb.get("default_mode", "adaptive")),
        "base_depth_ms": profile.get("base_depth_ms", jb.get("base_depth_ms", 40)),
        "target_factor": profile.get("target_factor", jb.get("target_factor", 2.0)),
        "min_depth_ms": profile.get("min_depth_ms", jb.get("min_depth_ms", 20)),
        "max_depth_ms": profile.get("max_depth_ms", jb.get("max_depth_ms", 120)),
        "rfc3550_jitter_gain": jb.get("rfc3550_jitter_gain", 0.0625),
    }
    return out


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    clock = sample.get("clock_rate", spec["media_profile"]["sample_rate_hz"])
    frame_ms = sample.get("frame_ms", spec["media_profile"]["frame_ms"])

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
        m = simulate_jitter_buffer(sample.get("packets", []), params, clock, frame_ms)
    except MediaError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, params, m)
    print("simulate[%s] mod=%s jitter=%.2fms derinlik=%.1fms | %d slot: %d oynat / %d geç / %d kayıp "
          "(concealment %.1f%%) | eklenen-gecikme P95 %.1fms"
          % (name, params["mode"], m["jitter_ms"], m["nominal_depth_ms"], m["total_slots"],
             m["played"], m["late_discarded"], m["lost"], m["concealment_ratio"] * 100,
             m["added_latency_p95_ms"]))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F)
    # opsiyonel beklenen metrik kontrolü
    exp = sample.get("expected", {})
    for k, v in exp.items():
        got = m.get(k)
        match = (got == v)
        print("  %s expected.%s == %r (got %r)" % ("✓" if match else "✗", k, v, got))
        gate_ok = gate_ok and match
    print("  kapı: %d/%d %s" % (sum(1 for ok, _ in F if ok), len(F), "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
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

    _check(R, spec.get("wbs") == "2.2.1", "spec.wbs == 2.2.1")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── J8: medya profili (8kHz/20ms, no-transcode)
    mp = spec.get("media_profile", {})
    _check(R, mp.get("sample_rate_hz") == 8000, "J8 medya 8 kHz")
    _check(R, mp.get("frame_ms") == 20 and mp.get("frames_per_sec") == 50, "J8 20ms/50fps çerçeve")
    _check(R, mp.get("samples_per_frame") == 160, "J8 160 örnek/çerçeve (8000*20ms)")
    _check(R, mp.get("no_transcode") is True and mp.get("resample_points_max", 99) <= 1,
           "J8 no-transcode, ≤1 resample noktası")

    # ── J1/J9: RTP sonlandırma
    rt = spec.get("rtp_termination", {})
    _check(R, rt.get("seq_bits") == 16 and rt.get("timestamp_bits") == 32, "J9 16-bit seq / 32-bit ts")
    _check(R, rt.get("wraparound_safe") is True, "J9 wraparound-güvenli")
    _check(R, rt.get("ssrc_change_resets_buffer") is True, "J9 SSRC değişimi buffer reset")
    _check(R, rt.get("marker_reprimes_playout") is True, "J9 marker playout reprime")
    _check(R, rt.get("reorder_within_window") is True, "J1 pencere içi reorder")

    # ── J2: adaptif jitter buffer sözleşmesi
    jb = spec.get("jitter_buffer", {})
    _check(R, set(jb.get("modes", [])) == MODES, "J2 modlar {adaptive, fixed}")
    _check(R, jb.get("default_mode") == "adaptive", "J2 varsayılan adaptive")
    _check(R, isinstance(jb.get("base_depth_ms"), (int, float)) and jb.get("base_depth_ms") > 0,
           "J2 base_depth_ms pozitif")
    _check(R, 0 < jb.get("min_depth_ms", 0) <= jb.get("max_depth_ms", 0), "J2 0 < min_depth ≤ max_depth")
    _check(R, isinstance(jb.get("target_factor"), (int, float)) and jb.get("target_factor") > 0,
           "J2 target_factor pozitif")
    _check(R, jb.get("late_packet_policy") == "discard", "J4 geç paket politikası = discard")
    _check(R, jb.get("overflow_policy") == "drop_oldest", "J10 taşma politikası = drop_oldest")
    _check(R, jb.get("concealment") == "plc_fill", "J5 concealment = plc_fill")

    # ── J3/J5/J6: kapılar
    g = spec.get("gates", {})
    _check(R, isinstance(g.get("jitter_buffer_budget_ms"), (int, float)) and g.get("jitter_buffer_budget_ms") > 0,
           "J3 jitter_buffer_budget_ms pozitif (SAD §20 payı)")
    _check(R, g.get("green_added_latency_ms", 1e9) <= g.get("jitter_buffer_budget_ms", 0),
           "J3 green ≤ bütçe")
    _check(R, jb.get("max_depth_ms", 0) <= 130,
           "J3 max_depth medya bütçesiyle tutarlı (≤~130ms)")
    _check(R, isinstance(g.get("max_concealment_ratio"), (int, float)) and 0 < g.get("max_concealment_ratio") < 1,
           "J5 max_concealment_ratio (0,1) aralığında")
    _check(R, g.get("cadence_must_be_continuous") is True, "J6 kadans sürekli zorunlu")
    _check(R, g.get("reorder_must_be_absorbed") is True, "J1 reorder absorbe zorunlu")

    # ── J7: metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"jitter_ms", "packet_loss_rate", "concealment_ratio", "added_latency_p95_ms"} <= emitted,
           "J7 BRD §15 metrikleri yayılır")
    mo = me.get("maps_to_observability", {})
    _check(R, mo.get("jitter_ms") == "voice_jitter_ms" and mo.get("packet_loss_rate") == "voice_packet_loss_ratio",
           "J7 metrikler 0.4.7 observability-spec'e eşlenir")

    # ── J11: barge-in flush kancası
    bf = spec.get("barge_in_flush", {})
    _check(R, bf.get("flush_deadline_ms") == 200, "J11 barge-in flush ≤200ms")

    # ── J12: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "J12 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "J12 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_rtp") == "INVALID_REQUEST"
           and mapping.get("media_transport_lost") == "UNAVAILABLE"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "J12 bozuk-RTP→INVALID, taşıma→UNAVAILABLE, bölge→REGION_VIOLATION")

    # ── J13/J14: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "J13 residency region pin")
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "J14 ham RTP payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "J14 transkript spec'te yasak")

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
    _check(R, not hits, "J14 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 jitter profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, p.get("mode", "adaptive") in MODES, "config %s modu geçerli" % p.get("name"))
            _check(R, bool(p.get("region")), "J13 config %s bölge pini var" % p.get("name"))
            mn = p.get("min_depth_ms", jb.get("min_depth_ms"))
            mx = p.get("max_depth_ms", jb.get("max_depth_ms"))
            _check(R, 0 < mn <= mx, "config %s 0<min≤max derinlik" % p.get("name"))
            _check(R, mx <= jb.get("max_depth_ms", 120) or mx <= 130,
                   "config %s max derinlik bütçeyle tutarlı" % p.get("name"))
        # her iki mod da temsil edilir (vendor-neutral ≥2 yol: managed + byoc)
        _check(R, {"adaptive"} <= {p.get("mode", "adaptive") for p in profs},
               "config en az bir adaptive profil")

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def _stream(n, frame_samples=160, ts0=1000, seq0=100, arrival0=0.0, step_ms=20.0,
            jitter_fn=None, drop=(), reorder_swaps=(), ssrc=11111):
    """Sentetik RTP akışı üretir. jitter_fn(i)->ms sapma; drop=atlanan slot indeksleri;
    reorder_swaps=[(i,j)] geliş sırasında takas. Deterministik."""
    pkts = []
    for i in range(n):
        if i in drop:
            continue
        arrival = arrival0 + i * step_ms + (jitter_fn(i) if jitter_fn else 0.0)
        pkts.append({
            "seq": (seq0 + i) % (1 << 16),
            "ts": (ts0 + i * frame_samples) % (1 << 32),
            "arrival_ms": arrival,
            "marker": i == 0,
            "ssrc": ssrc,
        })
    # reorder: geliş zamanlarını takas et
    for a, b in reorder_swaps:
        pkts[a]["arrival_ms"], pkts[b]["arrival_ms"] = pkts[b]["arrival_ms"], pkts[a]["arrival_ms"]
    return pkts


def selftest():
    spec = _load(SPEC_PATH)
    clock = spec["media_profile"]["sample_rate_hz"]
    frame_ms = spec["media_profile"]["frame_ms"]
    adaptive = {"mode": "adaptive", "base_depth_ms": 40, "target_factor": 2.0,
                "min_depth_ms": 20, "max_depth_ms": 120, "rfc3550_jitter_gain": 0.0625}
    fixed20 = dict(adaptive); fixed20["mode"] = "fixed"; fixed20["base_depth_ms"] = 20
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── wrap-güvenli aritmetik (J9) ──────────────────────────────────────────────
    case(seq_diff(2, 65535) == 3, "J9 seq wrap 65535→2 farkı +3")
    case(seq_diff(65535, 2) == -3, "J9 seq wrap 2→65535 farkı -3")
    case(ts_diff(10, (1 << 32) - 150) == 160, "J9 ts wrap fark +160 (örnek)")
    case(seq_diff(100, 50) == 50 and ts_diff(2000, 1000) == 1000, "J9 wrap-dışı normal fark")

    # ── percentile (0.3.x ile birebir) ──────────────────────────────────────────
    case(abs(percentile([10, 20, 30, 40], 0.95) - 38.5) < 1e-6, "percentile P95 lineer-interp")
    case(percentile([], 0.95) == 0.0 and percentile([7], 0.95) == 7.0, "percentile boş/tekil")

    # ── RFC 3550 jitter (J7) ─────────────────────────────────────────────────────
    clean = _stream(20)
    case(rfc3550_jitter(clean, clock) < 0.001, "J7 jitter≈0 temiz akışta")
    noisy = _stream(20, jitter_fn=lambda i: 8.0 if i % 2 else 0.0)
    case(rfc3550_jitter(noisy, clock) > 0.5, "J7 dalgalı gelişte jitter>0")

    # ── happy path: temiz akış geçer (J3/J5/J6) ──────────────────────────────────
    m = simulate_jitter_buffer(clean, adaptive, clock, frame_ms)
    case(m["lost"] == 0 and m["late_discarded"] == 0, "temiz akış: kayıp/geç yok")
    case(m["cadence_continuous"], "J6 temiz akış kadansı sürekli")
    case(m["concealment_ratio"] == 0.0, "J5 temiz akış concealment 0")
    case(all(ok for ok, _ in evaluate(spec, adaptive, m)), "temiz akış tüm kapıları geçer")
    case(abs(m["nominal_depth_ms"] - 40.0) < 0.5, "J2 düşük jitter → derinlik≈base 40ms")

    # ── adaptif derinlik artar ama clamp'lenir (J2) ──────────────────────────────
    m_noisy = simulate_jitter_buffer(noisy, adaptive, clock, frame_ms)
    case(m_noisy["nominal_depth_ms"] > 40.0, "J2 jitter↑ → derinlik base'in üstüne çıkar")
    case(m_noisy["nominal_depth_ms"] <= 120.0, "J2 derinlik max 120ms'e clamp'lenir")
    huge = _stream(30, jitter_fn=lambda i: (i % 5) * 60.0)
    m_huge = simulate_jitter_buffer(huge, adaptive, clock, frame_ms)
    case(m_huge["nominal_depth_ms"] == 120.0, "J2 aşırı jitter → derinlik tam max 120ms")

    # ── reorder absorbe (J1) ─────────────────────────────────────────────────────
    ro = _stream(20, reorder_swaps=[(5, 6)])  # 5 ve 6 geliş takası (komşu)
    m_ro = simulate_jitter_buffer(ro, adaptive, clock, frame_ms)
    case(m_ro["reordered"] >= 1, "J1 out-of-order paket sayıldı")
    case(m_ro["reorder_absorbed"] and m_ro["lost"] == 0 and m_ro["late_discarded"] == 0,
         "J1 komşu reorder absorbe edildi (40ms derinlik içinde)")
    case(all(ok for ok, _ in evaluate(spec, adaptive, m_ro)), "J1 reorder akışı kapıları geçer")

    # ── kayıp concealment (J5) ───────────────────────────────────────────────────
    lossy = _stream(50, drop=(10, 30))  # 2/50 = 4% ≤ 5%
    m_loss = simulate_jitter_buffer(lossy, adaptive, clock, frame_ms)
    case(m_loss["lost"] == 2 and m_loss["total_slots"] == 50, "J5 2 kayıp slot tespit edildi")
    case(abs(m_loss["concealment_ratio"] - 0.04) < 1e-9, "J5 concealment oranı %4")
    case(m_loss["cadence_continuous"], "J6 kayıpta bile kadans sürekli (concealed)")
    case(all(ok for ok, _ in evaluate(spec, adaptive, m_loss)), "J5 %4 kayıp kapıyı geçer (≤%5)")

    # ── geç paket atılır (J4): sığ fixed buffer jitter'ı sönümleyemez ────────────
    late = _stream(30, jitter_fn=lambda i: 60.0 if i % 3 == 1 else 0.0)
    m_late = simulate_jitter_buffer(late, fixed20, clock, frame_ms)
    case(m_late["late_discarded"] > 0, "J4 sığ fixed buffer'da geç paketler atılır")
    case(m_late["cadence_continuous"], "J6 geç atımda bile kadans sürekli")

    # ── degraded: aşırı kayıp+jitter → concealment kapısı eler (J5) ──────────────
    bad = _stream(40, drop=tuple(range(0, 40, 4)), jitter_fn=lambda i: 90.0 if i % 2 else 0.0)
    m_bad = simulate_jitter_buffer(bad, adaptive, clock, frame_ms)
    F_bad = evaluate(spec, adaptive, m_bad)
    case(not all(ok for ok, _ in F_bad), "degraded akış en az bir kapıyı eler")
    case(m_bad["concealment_ratio"] > 0.05, "J5 degraded concealment %5'i aşar")

    # ── bozuk RTP reddi (J12) ────────────────────────────────────────────────────
    case(_raises(lambda: simulate_jitter_buffer([{"seq": 1, "ts": 1000}], adaptive, clock, frame_ms)),
         "J12 arrival_ms'siz paket → reddedilir")
    case(_raises(lambda: simulate_jitter_buffer(
        [{"seq": 1, "ts": 1000, "arrival_ms": 0}, {"seq": 2, "ts": 1077, "arrival_ms": 20}],
        adaptive, clock, frame_ms)), "J12 hizasız ts (frame sınırı değil) → reddedilir")
    case(_raises(lambda: simulate_jitter_buffer(clean, dict(adaptive, mode="inband"), clock, frame_ms)),
         "J12 desteklenmeyen mod → reddedilir")
    case(_raises(lambda: simulate_jitter_buffer([], adaptive, clock, frame_ms)),
         "J12 boş akış → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["media_profile"]["no_transcode"] = False
    case(_validate_obj(s) != 0, "J8 no_transcode kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["jitter_buffer"]["default_mode"] = "fixed"
    case(_validate_obj(s) != 0, "J2 varsayılan adaptive değil → validate eler")
    s = json.loads(json.dumps(spec)); s["jitter_buffer"]["max_depth_ms"] = 10; s["jitter_buffer"]["min_depth_ms"] = 20
    case(_validate_obj(s) != 0, "J2 min>max derinlik → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["green_added_latency_ms"] = 200
    case(_validate_obj(s) != 0, "J3 green>bütçe → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["max_concealment_ratio"] = 1.5
    case(_validate_obj(s) != 0, "J5 concealment oranı aralık dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "J12 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["jitter_buffer"]["late_packet_policy"] = "play"
    case(_validate_obj(s) != 0, "J4 geç paket politikası discard değil → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["raw_payload_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "J14 ham-payload-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["jitter_buffer"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "J14 literal secret → validate eler")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ── selftest yardımcıları ───────────────────────────────────────────────────────
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
    print("""rtp-jitter-spec.json beklenen şekli (WBS 2.2.1):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability,rfc}
  media_profile{sample_rate_hz=8000, frame_ms=20, frames_per_sec=50,
                samples_per_frame=160, no_transcode=true, resample_points_max≤1}   (J8)
  rtp_termination{seq_bits=16, timestamp_bits=32, wraparound_safe=true,
                  ssrc_change_resets_buffer, marker_reprimes_playout,
                  reorder_within_window}                                          (J1,J9)
  jitter_buffer{modes[adaptive,fixed], default_mode=adaptive, base_depth_ms,
                target_factor, min_depth_ms, max_depth_ms, rfc3550_jitter_gain,
                late_packet_policy=discard, overflow_policy=drop_oldest,
                concealment=plc_fill}                                            (J2,J4,J10)
  gates{jitter_buffer_budget_ms, green_added_latency_ms≤bütçe, max_concealment_ratio,
        cadence_must_be_continuous=true, reorder_must_be_absorbed=true}          (J3,J5,J6)
  metrics{emitted[], maps_to_observability{jitter_ms→voice_jitter_ms, ...}}       (J7)
  barge_in_flush{flush_deadline_ms=200}                                           (J11)
  error_taxonomy{mapping→API §11.6}                                              (J12)
  residency{region_pin_required=true}                                             (J13)
  pii{raw_payload_in_spec_forbidden, transcript_in_spec_forbidden}                (J14)
  invariants[≥14]{id, desc, trace}

config/jitter-profiles.json: profiles[]{name, integration_mode, mode,
  base_depth_ms, target_factor, min_depth_ms, max_depth_ms, region}

simulate sample: {name, profile | profile_obj, clock_rate?, frame_ms?, expect,
  expected?{metrik:değer}, packets[]{seq, ts, arrival_ms, marker?, ssrc?}}
  (kayıp = slot'ta paket yok; reorder = arrival sırası ts sırasından farklı)

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: rtp_jitter_probe.py simulate <sample.json>")
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
