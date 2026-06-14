#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
codec_probe.py — WBS 2.2.2 Codec yönetimi (8kHz), gereksiz resample/transcode önleme

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + analiz kapısı.
`telephony/rtp-jitter/` (2.2.1) + `dtmf/` (2.1.6) probe disipliniyle aynı; jitter buffer
simülatörü yerine burada deterministik bir CODEC PAZARLIĞI + ZİNCİR ANALİZİ motoru (random YOK).

MEDIA GATEWAY CODEC YÖNETİMİ (SAD §6/§7, L2; FR-RES-008):
  • Pazarlık:  SDP offer/answer benzeri (RFC 3264) → conversion-minimizing ortak codec; ortak
               8kHz dar bant varsa PASSTHROUGH (narrowband-first) — gereksiz transcode kaçınılır.
  • Zincir:    ses akış stage'lerini yürür; her sınırda resample (rate farkı) / transcode (encoding
               farkı) tespit eder; MİNİMUM dönüşümü DP ile hesaplar (uçlar pinned, iç stage'ler
               native üzerinde) → GEREKSİZ = actual − minimal (≥0); U-dönüşü (8k→16k→8k) = israf.
  • Metrikler: aktif codec / resample-transcode hop / gereksiz dönüşüm → BRD §15 → observability.

Komutlar:
  validate              codec-spec.json'ı invariant'lara + config profillerine karşı doğrular.
  simulate <sample>     Deterministik pazarlık + zincir analizi — codec seçimi, resample/transcode
                        hop, gereksiz dönüşüm + HARD kapılar (C1–C6); →çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. simulate gerçek codec yığını yerine deterministik analizdir
(canlı sistemde Media Gateway C/C++/Rust native, SAD §21). Ham ses payload'ı/PII YOK.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "codec-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "codec-profiles.json")

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


class CodecError(Exception):
    """Geçersiz/desteklenmeyen codec/zincir — sessizce kabul yok, reddet (C11)."""


# ─────────────────────────────────────────────────────────────────────────────
# Codec kataloğu erişimi
# ─────────────────────────────────────────────────────────────────────────────
def _catalog(spec):
    return spec.get("codec_catalog", {}).get("codecs", {})


def _codec(cat, name):
    if name not in cat:
        raise CodecError("desteklenmeyen codec: %r → INVALID_REQUEST" % name)
    return cat[name]


def _rate(cat, name):
    return _codec(cat, name)["rate_hz"]


def _enc(cat, name):
    return _codec(cat, name)["encoding"]


# ─────────────────────────────────────────────────────────────────────────────
# Codec pazarlığı (SDP offer/answer benzeri — C2)
# ─────────────────────────────────────────────────────────────────────────────
def negotiate(cat, offer, answer, prefer_narrowband=True):
    """offer∩answer (offer tercih sırasıyla) → conversion-minimizing ortak codec.
    Ortak 8kHz dar bant varsa narrowband-first (passthrough tercih). Ortak yoksa → UNAVAILABLE.
    Deterministik; randomsuz."""
    for c in offer + answer:
        _codec(cat, c)  # tanınmayan codec → INVALID_REQUEST
    common = [c for c in offer if c in answer]
    if not common:
        raise CodecError("ortak codec yok (offer∩answer boş) → UNAVAILABLE")
    if prefer_narrowband:
        nb = [c for c in common if _rate(cat, c) == 8000]
        if nb:
            return nb[0]
    return common[0]


# ─────────────────────────────────────────────────────────────────────────────
# Zincir analizi (deterministik — C3..C8)
# ─────────────────────────────────────────────────────────────────────────────
def _boundary(cat, a, b):
    """(resample?, transcode?) — rate farkı→resample, encoding farkı→transcode."""
    if a == b:
        return (0, 0)
    return (1 if _rate(cat, a) != _rate(cat, b) else 0,
            1 if _enc(cat, a) != _enc(cat, b) else 0)


def _minimal(cat, allowed, metric):
    """DP: uçlar pinned (allowed[0], allowed[-1] tek-eleman), iç stage'ler native üzerinde;
    metric ∈ {any, resample, transcode} için min sınır-dönüşüm sayısı (alt sınır)."""
    INF = float("inf")
    dp = {c: 0 for c in allowed[0]}
    for i in range(1, len(allowed)):
        ndp = {}
        for c in allowed[i]:
            best = INF
            for pc, pcost in dp.items():
                rs, ts = _boundary(cat, pc, c)
                if metric == "resample":
                    step = rs
                elif metric == "transcode":
                    step = ts
                else:  # any conversion
                    step = 1 if (rs or ts) else 0
                if pcost + step < best:
                    best = pcost + step
            ndp[c] = best
        dp = ndp
    return int(min(dp.values())) if dp else 0


def _uturn(seq):
    """Collapse ardışık tekrarları; kalan dizide bir değer >1 kez görünürse U-dönüşü (ayrılıp geri girme)."""
    collapsed = []
    for v in seq:
        if not collapsed or collapsed[-1] != v:
            collapsed.append(v)
    return len(collapsed) != len(set(collapsed))


def analyze_chain(cat, chain):
    """Medya zincirini yürür → dönüşüm metrikleri + gereksiz (actual−minimal) + U-dönüşü.

    chain stage: {stage, codec, native[], pinned?}. Uç stage'ler (ilk/son) otomatik pinned
    (wire/adapter formatı sabit); ara stage 'pinned: true' ile de pinlenebilir.
    Döner: active_codec, wire_sample_rate_hz, conversions, resample_points, transcode_hops,
           minimal_*, unnecessary_*, rate_uturn, encoding_uturn, rate_seq.
    """
    if not chain or len(chain) < 2:
        raise CodecError("zincir en az 2 stage olmalı (ingress→consumer)")
    codecs = []
    for i, s in enumerate(chain):
        c = s.get("codec")
        if c is None:
            raise CodecError("stage %r codec'siz" % s.get("stage"))
        _codec(cat, c)
        native = s.get("native", [c])
        if c not in native:  # C8 stage-native tutarlılığı
            raise CodecError("stage %r working codec %r native değil %r → INVALID_REQUEST"
                             % (s.get("stage"), c, native))
        codecs.append(c)

    # actual sınır metrikleri
    conversions = resample_points = transcode_hops = 0
    for a, b in zip(codecs, codecs[1:]):
        rs, ts = _boundary(cat, a, b)
        if rs or ts:
            conversions += 1
        resample_points += rs
        transcode_hops += ts

    # minimal (uçlar + explicit-pinned stage'ler pinned; diğerleri native üzerinde)
    n = len(chain)
    allowed = []
    for i, s in enumerate(chain):
        pinned = (i == 0 or i == n - 1) or bool(s.get("pinned"))
        allowed.append([s["codec"]] if pinned else list(s.get("native", [s["codec"]])))
    min_conv = _minimal(cat, allowed, "any")
    min_rs = _minimal(cat, allowed, "resample")
    min_ts = _minimal(cat, allowed, "transcode")

    rate_seq = [_rate(cat, c) for c in codecs]
    enc_seq = [_enc(cat, c) for c in codecs]

    return {
        "active_codec": codecs[0],
        "wire_sample_rate_hz": rate_seq[0],
        "conversions": conversions,
        "resample_points": resample_points,
        "transcode_hops": transcode_hops,
        "minimal_conversions": min_conv,
        "minimal_resamples": min_rs,
        "minimal_transcodes": min_ts,
        "unnecessary_conversions": conversions - min_conv,
        "unnecessary_resamples": resample_points - min_rs,
        "unnecessary_transcodes": transcode_hops - min_ts,
        "rate_uturn": _uturn(rate_seq),
        "encoding_uturn": _uturn(enc_seq),
        "rate_seq": rate_seq,
    }


def evaluate(spec, cat, negotiated, m):
    """Metrikleri HARD kapılara (C1–C6) karşı değerlendirir. Döner findings[(ok, label)]."""
    g = spec.get("gates", {})
    wire = g.get("wire_sample_rate_hz", 8000)
    max_rp = g.get("resample_points_max", 1)
    F = []
    # C1 wire 8kHz dar bant
    nb = cat.get(negotiated, {}).get("telephony", False) and _rate(cat, negotiated) == wire
    F.append((nb and m["wire_sample_rate_hz"] == wire,
              "C1 wire codec %s @ %d Hz dar bant (8kHz native)" % (negotiated, m["wire_sample_rate_hz"])))
    # C3 gereksiz transcode yok
    F.append((m["unnecessary_transcodes"] <= g.get("unnecessary_transcode_max", 0),
              "C3 gereksiz transcode %d (actual %d / minimal %d)"
              % (m["unnecessary_transcodes"], m["transcode_hops"], m["minimal_transcodes"])))
    # C4 gereksiz resample yok
    F.append((m["unnecessary_resamples"] <= g.get("unnecessary_resample_max", 0),
              "C4 gereksiz resample %d (actual %d / minimal %d)"
              % (m["unnecessary_resamples"], m["resample_points"], m["minimal_resamples"])))
    # C5 ≤1 kontrollü resample noktası
    F.append((m["resample_points"] <= max_rp,
              "C5 resample noktası %d ≤ %d (tek kontrollü seam)" % (m["resample_points"], max_rp)))
    # C6 U-dönüşü yok
    if g.get("no_rate_uturn", True):
        F.append((not m["rate_uturn"], "C6 rate U-dönüşü yok (rate_seq=%s)" % m["rate_seq"]))
    if g.get("no_encoding_uturn", True):
        F.append((not m["encoding_uturn"], "C6 encoding U-dönüşü yok"))
    return F


# ─────────────────────────────────────────────────────────────────────────────
# simulate
# ─────────────────────────────────────────────────────────────────────────────
def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise CodecError("bilinmeyen profil: %s" % name)


def simulate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    cat = _catalog(spec)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")

    prefer_nb = spec.get("negotiation", {}).get("prefer_narrowband", True)
    if "profile" in sample and os.path.exists(PROFILES_CFG):
        try:
            prof = _profile_by_name(_load(PROFILES_CFG), sample["profile"])
            prefer_nb = prof.get("prefer_narrowband", prefer_nb)
        except CodecError as ex:
            print("simulate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1

    # pazarlık (offer/answer verilmişse) veya doğrudan negotiated
    try:
        if "offer" in sample and "answer" in sample:
            negotiated = negotiate(cat, sample["offer"], sample["answer"], prefer_nb)
            declared = sample.get("negotiated")
            neg_optimal = (declared is None) or (declared == negotiated)
        else:
            negotiated = sample["negotiated"]
            _codec(cat, negotiated)
            neg_optimal = True
        m = analyze_chain(cat, sample.get("chain", []))
    except CodecError as ex:
        print("simulate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1

    F = evaluate(spec, cat, negotiated, m)
    # C2 pazarlık optimal (offer/answer verildiyse)
    if "offer" in sample and "answer" in sample:
        F.insert(1, (neg_optimal,
                     "C2 pazarlık optimal (seçilen %s == conversion-minimizing)" % negotiated))

    print("simulate[%s] codec=%s @%dHz | %d stage: %d dönüşüm (%d resample / %d transcode) "
          "| gereksiz %dR/%dT | minimal %dR/%dT"
          % (name, negotiated, m["wire_sample_rate_hz"], len(sample.get("chain", [])),
             m["conversions"], m["resample_points"], m["transcode_hops"],
             m["unnecessary_resamples"], m["unnecessary_transcodes"],
             m["minimal_resamples"], m["minimal_transcodes"]))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F)
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

    _check(R, spec.get("wbs") == "2.2.2", "spec.wbs == 2.2.2")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── C9: medya profili (8kHz/20ms)
    mp = spec.get("media_profile", {})
    _check(R, mp.get("sample_rate_hz") == 8000, "C1/C9 medya 8 kHz")
    _check(R, mp.get("frame_ms") == 20 and mp.get("frames_per_sec") == 50, "C9 20ms/50fps çerçeve")
    _check(R, mp.get("samples_per_frame") == 160, "C9 160 örnek/çerçeve (8000*20ms)")
    _check(R, mp.get("no_unnecessary_transcode") is True and mp.get("no_unnecessary_resample") is True,
           "FR-RES-008 gereksiz transcode+resample bayrakları açık")
    _check(R, mp.get("resample_points_max", 99) <= 1, "C5 ≤1 resample noktası (profil)")

    # ── codec kataloğu
    cat = _catalog(spec)
    _check(R, len(cat) >= 4, "codec kataloğu ≥4 codec")
    for nm, c in cat.items():
        _check(R, "encoding" in c and isinstance(c.get("rate_hz"), int) and c["rate_hz"] > 0,
               "codec %s encoding+rate_hz tanımlı" % nm)
    tel_nb = [nm for nm, c in cat.items() if c.get("telephony") and c.get("rate_hz") == 8000]
    _check(R, len(tel_nb) >= 2, "C1 ≥2 telefoni 8kHz dar bant codec (G.711/Opus-NB)")

    # ── pazarlık
    ng = spec.get("negotiation", {})
    _check(R, ng.get("prefer_narrowband") is True, "C2 narrowband-first pazarlık")
    _check(R, ng.get("no_common_codec_policy") == "UNAVAILABLE", "C2 ortak-yok → UNAVAILABLE")

    # ── zincir analizi sözleşmesi
    ca = spec.get("chain_analysis", {})
    _check(R, ca.get("boundary_resample_if") and ca.get("boundary_transcode_if"),
           "zincir sınır kuralları tanımlı (resample/transcode)")
    _check(R, ca.get("stage_codec_must_be_native") is True, "C8 stage codec native zorunlu")

    # ── C1–C6: kapılar
    g = spec.get("gates", {})
    _check(R, g.get("wire_sample_rate_hz") == 8000, "C1 wire 8 kHz kapı")
    _check(R, g.get("resample_points_max") == 1, "C5 resample_points_max == 1")
    _check(R, g.get("unnecessary_transcode_max") == 0, "C3 gereksiz transcode max 0")
    _check(R, g.get("unnecessary_resample_max") == 0, "C4 gereksiz resample max 0")
    _check(R, g.get("no_rate_uturn") is True and g.get("no_encoding_uturn") is True,
           "C6 rate+encoding U-dönüşü yasak")

    # ── C10: metrikler → observability
    me = spec.get("metrics", {})
    emitted = set(me.get("emitted", []))
    _check(R, {"active_codec", "resample_points", "transcode_hops",
               "unnecessary_resamples", "unnecessary_transcodes"} <= emitted,
           "C10 dönüşüm metrikleri yayılır")
    _check(R, me.get("maps_to_observability", {}).get("active_codec") == "voice_codec_info",
           "C10 active_codec → voice_codec_info (0.4.7)")

    # ── C11: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 3, "C11 hata eşlemesi (≥3)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "C11 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("unsupported_codec") == "INVALID_REQUEST"
           and mapping.get("no_common_codec") == "UNAVAILABLE"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "C11 desteklenmeyen→INVALID, ortak-yok→UNAVAILABLE, bölge→REGION_VIOLATION")

    # ── C12/C13: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "C12 residency region pin")
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "C13 ham payload spec'te yasak")
    _check(R, spec.get("pii", {}).get("transcript_in_spec_forbidden") is True,
           "C13 transkript spec'te yasak")

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
    _check(R, not hits, "C13 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(PROFILES_CFG):
        cfg = _load(PROFILES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 codec profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            offer = p.get("offer", [])
            answer = p.get("answer", [])
            _check(R, all(c in cat for c in offer + answer),
                   "config %s offer/answer codec'leri katalogda" % p.get("name"))
            _check(R, bool(p.get("region")), "C12 config %s bölge pini var" % p.get("name"))
            try:
                neg = negotiate(cat, offer, answer, p.get("prefer_narrowband", True))
                _check(R, cat[neg].get("telephony") and cat[neg]["rate_hz"] == 8000,
                       "C1 config %s pazarlık 8kHz dar bant seçer (%s)" % (p.get("name"), neg))
            except CodecError:
                _check(R, False, "config %s pazarlık başarısız" % p.get("name"))

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
def _stage(stage, codec, native=None):
    return {"stage": stage, "codec": codec, "native": native or [codec]}


def selftest():
    spec = _load(SPEC_PATH)
    cat = _catalog(spec)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 0) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── pazarlık (C2) ────────────────────────────────────────────────────────────
    case(negotiate(cat, ["PCMU", "PCMA"], ["PCMU", "PCMA"]) == "PCMU",
         "C2 ortak codec → offer tercih sırası (PCMU)")
    case(negotiate(cat, ["OPUS_WB", "PCMU"], ["PCMU", "OPUS_WB"]) == "PCMU",
         "C2 narrowband-first: 16kHz Opus yerine 8kHz PCMU seçer (resample kaçınır)")
    case(negotiate(cat, ["PCMA", "PCMU"], ["PCMU"]) == "PCMU",
         "C2 yalnız PCMU ortak → PCMU")
    case(_raises(lambda: negotiate(cat, ["OPUS_WB"], ["PCMU"])),
         "C2 ortak codec yok → UNAVAILABLE (reddedilir)")
    case(_raises(lambda: negotiate(cat, ["G729"], ["PCMU"])),
         "C11 tanınmayan codec → INVALID_REQUEST (reddedilir)")

    # ── minimal DP ─────────────────────────────────────────────────────────────
    # tüm-PCMU passthrough: minimal 0
    allp = [["PCMU"], ["PCMU", "PCMA", "L16_8K"], ["PCMU", "L16_8K"], ["PCMU"]]
    case(_minimal(cat, allp, "any") == 0, "DP tüm-PCMU passthrough → minimal 0 dönüşüm")
    # uçlar PCMU(8k)/L16_16K(16k), iç stage 16k destekler → minimal 1 resample
    forced = [["PCMU"], ["PCMU", "L16_8K", "L16_16K"], ["L16_16K"]]
    case(_minimal(cat, forced, "resample") == 1, "DP zorunlu 16kHz → minimal 1 resample")
    case(_minimal(cat, forced, "transcode") == 1, "DP zorunlu L16 → minimal 1 transcode")

    # ── passthrough zincir geçer (C3/C4/C5) ──────────────────────────────────────
    chain_pass = [
        _stage("pstn_ingress", "PCMU", ["PCMU", "PCMA"]),
        _stage("media_gateway", "PCMU", ["PCMU", "PCMA", "L16_8K", "OPUS_NB"]),
        _stage("stt_adapter", "PCMU", ["PCMU", "L16_8K"]),
    ]
    m = analyze_chain(cat, chain_pass)
    case(m["conversions"] == 0 and m["resample_points"] == 0 and m["transcode_hops"] == 0,
         "passthrough zincir: 0 dönüşüm")
    case(all(ok for ok, _ in evaluate(spec, cat, "PCMU", m)), "passthrough tüm kapıları geçer")
    case(m["unnecessary_resamples"] == 0 and m["unnecessary_transcodes"] == 0,
         "passthrough: gereksiz dönüşüm 0")

    # ── tek kontrollü resample (C5) geçer ────────────────────────────────────────
    chain_1rs = [
        _stage("pstn_ingress", "PCMU", ["PCMU", "PCMA"]),
        _stage("media_gateway", "PCMU", ["PCMU", "L16_8K", "L16_16K"]),
        _stage("stt_adapter_16k", "L16_16K", ["L16_16K"]),  # yalnız 16kHz
    ]
    m1 = analyze_chain(cat, chain_1rs)
    case(m1["resample_points"] == 1 and m1["transcode_hops"] == 1, "tek-resample: 1 resample + 1 transcode")
    case(m1["unnecessary_resamples"] == 0 and m1["unnecessary_transcodes"] == 0,
         "tek-resample: dönüşüm GEREKLİ (gereksiz 0)")
    case(all(ok for ok, _ in evaluate(spec, cat, "PCMU", m1)), "tek-resample kontrollü seam kapıları geçer")

    # ── gereksiz transcode (C3) eler ─────────────────────────────────────────────
    chain_redundant = [
        _stage("pstn_ingress", "PCMU", ["PCMU", "PCMA"]),
        _stage("sbc", "PCMA", ["PCMU", "PCMA"]),          # gereksiz µ→A
        _stage("media_gateway", "PCMU", ["PCMU", "PCMA"]),  # geri A→µ
        _stage("stt_adapter", "PCMU", ["PCMU"]),
    ]
    mr = analyze_chain(cat, chain_redundant)
    case(mr["transcode_hops"] == 2 and mr["unnecessary_transcodes"] == 2,
         "gereksiz transcode: 2 hop, ikisi de gereksiz (minimal 0)")
    case(mr["encoding_uturn"], "C6 µ→A→µ encoding U-dönüşü tespit")
    case(not all(ok for ok, _ in evaluate(spec, cat, "PCMU", mr)), "gereksiz transcode zinciri en az bir kapıyı eler")

    # ── gereksiz/çift resample (C4/C5/C6) eler ───────────────────────────────────
    chain_double = [
        _stage("pstn_ingress", "PCMU", ["PCMU"]),
        _stage("media_gateway", "L16_16K", ["PCMU", "L16_8K", "L16_16K"]),  # 8k→16k
        _stage("orchestrator", "L16_8K", ["L16_8K", "L16_16K"]),            # 16k→8k (U-turn)
        _stage("stt_adapter_16k", "L16_16K", ["L16_16K"]),                 # 8k→16k tekrar
    ]
    md = analyze_chain(cat, chain_double)
    case(md["resample_points"] == 3, "çift-resample: 3 resample noktası")
    case(md["rate_uturn"], "C6 8k→16k→8k→16k rate U-dönüşü tespit")
    case(md["unnecessary_resamples"] >= 2, "çift-resample: gereksiz resample ≥2 (minimal 1)")
    Fd = evaluate(spec, cat, "PCMU", md)
    case(not all(ok for ok, _ in Fd), "çift-resample zinciri kapı eler (C4+C5+C6)")

    # ── C8 native tutarlılığı + reddetmeler ──────────────────────────────────────
    case(_raises(lambda: analyze_chain(cat, [
        _stage("a", "PCMU", ["PCMU"]),
        {"stage": "b", "codec": "L16_16K", "native": ["PCMU"]}])),  # codec native değil
         "C8 working codec native değil → reddedilir")
    case(_raises(lambda: analyze_chain(cat, [_stage("only", "PCMU")])),
         "C8 tek-stage zincir → reddedilir")
    case(_raises(lambda: analyze_chain(cat, [_stage("a", "PCMU"), {"stage": "b", "codec": "G729"}])),
         "C11 tanınmayan stage codec → reddedilir")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["media_profile"]["no_unnecessary_transcode"] = False
    case(_validate_obj(s) != 0, "FR-RES-008 no_unnecessary_transcode kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["resample_points_max"] = 3
    case(_validate_obj(s) != 0, "C5 resample_points_max≠1 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["unnecessary_transcode_max"] = 2
    case(_validate_obj(s) != 0, "C3 gereksiz transcode max≠0 → validate eler")
    s = json.loads(json.dumps(spec)); s["gates"]["wire_sample_rate_hz"] = 16000
    case(_validate_obj(s) != 0, "C1 wire rate 16kHz → validate eler")
    s = json.loads(json.dumps(spec)); s["negotiation"]["prefer_narrowband"] = False
    case(_validate_obj(s) != 0, "C2 narrowband-first kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "C11 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec))
    s["codec_catalog"]["codecs"] = {"OPUS_WB": s["codec_catalog"]["codecs"]["OPUS_WB"]}
    case(_validate_obj(s) != 0, "C1 telefoni 8kHz codec yok → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["raw_payload_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "C13 ham-payload-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["codec_catalog"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "C13 literal secret → validate eler")

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
    except CodecError:
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
    print("""codec-spec.json beklenen şekli (WBS 2.2.2):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,observability,rfc}
  media_profile{sample_rate_hz=8000, frame_ms=20, frames_per_sec=50, samples_per_frame=160,
                no_unnecessary_transcode=true, no_unnecessary_resample=true,
                resample_points_max≤1}                                            (C1,C9)
  codec_catalog{codecs{NAME:{encoding, rate_hz, telephony, payload_type}}}         (C1)
  negotiation{prefer_narrowband=true, prefer_passthrough, no_common_codec_policy}  (C2)
  chain_analysis{boundary_resample_if, boundary_transcode_if,
                 stage_codec_must_be_native=true, minimal_via=DP}                  (C3,C4,C8)
  gates{wire_sample_rate_hz=8000, resample_points_max=1, unnecessary_transcode_max=0,
        unnecessary_resample_max=0, no_rate_uturn=true, no_encoding_uturn=true}    (C1,C3-C6)
  metrics{emitted[], maps_to_observability{active_codec→voice_codec_info}}         (C10)
  error_taxonomy{mapping→API §11.6}                                               (C11)
  residency{region_pin_required=true}                                              (C12)
  pii{raw_payload_in_spec_forbidden, transcript_in_spec_forbidden}                 (C13)
  invariants[≥14]{id, desc, trace}

config/codec-profiles.json: profiles[]{name, integration_mode, offer[], answer[],
  prefer_narrowband, region}

simulate sample: {name, profile?, offer?[], answer?[], negotiated?, expect,
  expected?{metrik:değer}, chain[]{stage, codec, native[], pinned?}}
  (resample = sınırda rate farkı; transcode = encoding farkı; uçlar otomatik pinned)

komutlar: validate | simulate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "simulate":
        if len(sys.argv) < 3:
            print("kullanım: codec_probe.py simulate <sample.json>")
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
