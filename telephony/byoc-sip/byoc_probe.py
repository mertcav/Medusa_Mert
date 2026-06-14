#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
byoc_probe.py — WBS 2.1.4 SIP trunk / BYOC (Bring Your Own Carrier) desteği

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`db/`+`cache/`+`objstore/`+`eventstream/`+`telephony/managed-cpaas/` probe disipliniyle aynı.

BYOC = SAD §7.2 M2 (ham SIP trunk + RTP). Adapter SIP/SDP/RTP'yi 2.1.3 managed-cpaas ile
BİREBİR AYNI normalize sözleşmesine (start/media/dtmf/stop) indirger — orchestrator M1/M2 farkı görmez.

Komutlar:
  validate              byoc-spec.json'ı invariant'lara + config trunk profillerine karşı doğrular (çıkış kodu).
  normalize <sample>    Deterministik SIP/SDP/RTP normalize simülatörü — BYOC SIP mesaj dizisini alır,
                        SIP diyalog SM'ini çalıştırır, SDP codec müzakere eder, normalize ingress olayları
                        üretir, invariant'ları (sıra, tenant bağlama, barge-in ≤200ms, codec, residency)
                        kontrol eder; kapı→çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. `normalize` gerçek SIP/SBC yerine deterministik simülasyondur
(managed-cpaas normalize / objstore access-decision / eventstream replay simülatörü deseni).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "byoc-spec.json")
TRUNKS_CFG = os.path.join(HERE, "config", "trunks.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

NORMALIZED_INGRESS = {"start", "media", "dtmf", "stop"}
NORMALIZED_EGRESS = {"play_audio", "mark", "barge_in_clear"}
ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
# Narrowband 8 kHz codec — telefoni gerçeği; transcode kaçınma (FR-RES-008).
NARROWBAND_CODECS = {"PCMU/8000", "PCMA/8000"}
# Sır tarayıcı: yorum satırları (sırrı *tarif eden* açıklama ≠ sır) elenir; eventstream/managed-cpaas deseni.
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _check(results, ok, label):
    results.append((bool(ok), label))


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _scan_secrets(obj, path="root"):
    """JSON ağacında literal sır arar; $comment/açıklama anahtarlarını ve ${ENV} değerlerini eler."""
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

    # ── temel kimlik
    _check(R, spec.get("wbs") == "2.1.4", "spec.wbs == 2.1.4")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── I4: medya profili (8kHz/20ms/G.711, no-transcode)
    mp = spec.get("media_profile", {})
    _check(R, mp.get("sample_rate_hz") == 8000, "I4 media 8 kHz")
    _check(R, mp.get("frame_ms") == 20 and mp.get("frames_per_sec") == 50, "I4 20 ms / 50 fps")
    _check(R, "mulaw" in mp.get("encodings", []) and "alaw" in mp.get("encodings", []),
           "I4 G.711 μ-law/A-law encoding")
    _check(R, mp.get("frame_bytes_mulaw") == 160, "I4 μ-law 160 bayt/çerçeve")
    _check(R, mp.get("no_transcode") is True and mp.get("resample_points_max", 9) <= 1,
           "I4 no-transcode + ≤1 resample (FR-RES-008)")

    # ── I1: transport (TLS sinyalleşme + SRTP medya)
    tr = spec.get("transport", {})
    _check(R, tr.get("signaling_scheme") == "sips" and tr.get("plaintext_signaling_allowed") is False,
           "I1 SIPS/TLS sinyalleşme zorunlu, düz-metin reddedilir (NFR 10.6)")
    _check(R, tr.get("srtp_required") is True and tr.get("plaintext_media_allowed") is False,
           "I1 SRTP medya zorunlu, düz-metin RTP reddedilir (NFR 10.6)")
    _check(R, tr.get("sbc_fronted") is True, "I1 SBC önde (topoloji gizleme, FR-TEL-002)")

    # ── I2: auth (medya öncesi)
    au = spec.get("auth", {})
    _check(R, au.get("verify_before_media") is True, "I2 medya öncesi auth (verify_before_media)")
    _check(R, set(["sip_digest", "ip_acl", "mtls"]).issubset(set(au.get("methods", []))),
           "I2 SIP digest/IP-ACL/mTLS yöntemleri")
    _check(R, isinstance(au.get("replay_window_sec"), int) and au["replay_window_sec"] > 0,
           "I2 sonlu replay penceresi")

    # ── I3: context binding
    cb = spec.get("context_binding", {})
    _check(R, cb.get("bound_at") == "call_setup", "I3 bağlam çağrı kurulumunda")
    _check(R, set(["tenant_id", "correlation_id", "call_id"]).issubset(set(cb.get("required_keys", []))),
           "I3 tenant_id+correlation_id+call_id zorunlu")
    _check(R, cb.get("propagate_on_every_event") is True, "I3 her olaya taşınır (SAD §13.3)")
    _check(R, "did_to_tenant_map" in cb.get("tenant_resolution", []),
           "I3 DID→tenant eşlemesi (FR-TEN-002)")

    # ── I6: normalize ingress kümesi (API §12.1) — managed-cpaas ile birebir aynı
    npn = spec.get("normalized_protocol", {})
    _check(R, set(npn.get("ingress_control_events", [])) == NORMALIZED_INGRESS,
           "I6 normalize ingress = {start,media,dtmf,stop} (API §12.1, 2.1.3 ile aynı)")
    _check(R, set(npn.get("egress_actions", [])) == NORMALIZED_EGRESS,
           "egress aksiyon = {play_audio,mark,barge_in_clear}")

    # ── I9: SIP diyalog SM
    sd = spec.get("sip_dialog", {})
    states = set(sd.get("states", []))
    _check(R, {"INIT", "INVITE_RECEIVED", "RINGING", "EARLY_MEDIA", "ANSWERED",
               "ESTABLISHED", "TERMINATING", "TERMINATED", "FAILED"}.issubset(states),
           "I9 SIP diyalog durumları tam")
    _check(R, sd.get("rtp_media_before_answer_rejected") is True,
           "I9 RTP answer öncesi reddedilir (early-media istisna)")
    vt = sd.get("valid_transitions", {})
    _check(R, all(s in states for s in vt), "I9 geçiş kaynakları durum kümesinde")
    _check(R, all(all(d in states for d in dests) for dests in vt.values()),
           "I9 geçiş hedefleri durum kümesinde")
    nm = sd.get("normalize_map", {})
    _check(R, nm.get("answer") == "start" and nm.get("rtp") == "media"
           and nm.get("dtmf") == "dtmf" and nm.get("bye") == "stop",
           "I6 SIP→normalize eşlemesi (answer→start, rtp→media, dtmf→dtmf, bye→stop)")

    # ── I15: SDP codec müzakeresi
    sdp = spec.get("sdp", {})
    _check(R, set(sdp.get("allowed_codecs", [])).issubset(NARROWBAND_CODECS) and sdp.get("allowed_codecs"),
           "I15 SDP yalnız narrowband G.711 (PCMU/PCMA)")
    _check(R, sdp.get("transcode_on_no_common_codec") is False
           and sdp.get("reject_on_no_common_codec") is True,
           "I15 ortak codec yoksa transcode değil REDDET (488)")

    # ── I7: ≥2 trunk + eksiksiz eşleme + fallback
    trunks = spec.get("trunks", [])
    byoc = [t for t in trunks if t.get("kind") == "byoc_sip_trunk"]
    _check(R, len(byoc) >= 2, "I7 ≥2 BYOC trunk (ADR-002)")
    for t in trunks:
        tid = t.get("id", "?")
        de = t.get("dialog_events", {})
        mapped = {v for v in de.values() if v is not None}
        _check(R, mapped.issubset(NORMALIZED_INGRESS),
               "I6 %s dialog eşlemeleri normalize kümesinde" % tid)
        for need in ("start", "media", "stop", "dtmf"):
            inv = [k for k, v in de.items() if v == need]
            _check(R, len(inv) >= 1, "I6 %s → normalize '%s' eşlemesi var" % (tid, need))
        eg = t.get("egress_events", {})
        _check(R, set(eg.keys()) == NORMALIZED_EGRESS,
               "%s egress aksiyonları tam (play_audio/mark/barge_in_clear)" % tid)
        _check(R, _is_placeholder(t.get("auth_secret_ref", "")),
               "I10 %s auth_secret_ref ${ENV} placeholder" % tid)
        _check(R, _is_placeholder(t.get("region_pin", "")),
               "I11 %s region_pin ${ENV} placeholder" % tid)
        _check(R, t.get("media_transport") == "srtp", "I1 %s medya SRTP" % tid)
        _check(R, t.get("dtmf_mode") in ("rfc2833", "sip_info"),
               "I12 %s DTMF modu RFC2833/INFO" % tid)
        _check(R, set(t.get("offered_codecs", [])).issubset(NARROWBAND_CODECS) and t.get("offered_codecs"),
               "I15 %s offered codec narrowband" % tid)
        bo = t.get("rtp_clear_overhead_ms")
        _check(R, isinstance(bo, (int, float)) and bo >= 0,
               "%s rtp_clear_overhead_ms tanımlı" % tid)

    fb = spec.get("fallback", {})
    _check(R, isinstance(fb.get("trunk_order"), list) and len(fb.get("trunk_order", [])) >= 2,
           "I7 fallback trunk sırası ≥2")
    _check(R, fb.get("cross_mode_fallback") == "managed_cpaas_m1",
           "I7 çapraz-mod M1 fallback (ADR-002)")

    # ── I5: barge-in
    bi = spec.get("barge_in", {})
    _check(R, bi.get("deadline_ms") == 200, "I5 barge-in deadline 200 ms (NFR 10.1)")
    _check(R, bi.get("source_event") == "BARGE_IN", "I5 source BARGE_IN (API §12.2)")
    _check(R, bi.get("egress_action") == "barge_in_clear", "I5 egress barge_in_clear")

    # ── I8: error taxonomy (SIP yanıt kodu → ortak)
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "I8 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "I8 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, set(et.get("fallback_on", [])).issubset(ERROR_TAXONOMY) and et.get("fallback_on"),
           "I8 fallback_on taksonomi alt kümesi")

    # ── I11/I12/I13/I14
    _check(R, spec.get("residency", {}).get("region_pin_required") is True,
           "I11 residency region pin zorunlu (NFR 10.7)")
    dt = spec.get("dtmf", {})
    _check(R, dt.get("normalized_event") == "dtmf" and set(dt.get("modes", [])) == {"rfc2833", "sip_info"}
           and dt.get("digit_set"),
           "I12 DTMF normalize + RFC2833/INFO modları (FR-TEL-006)")
    rc = spec.get("reconnect", {})
    _check(R, rc.get("cseq_tracking") is True and isinstance(rc.get("reinvite_window_sec"), (int, float))
           and rc.get("reinvite_window_sec") > 0, "I13 reconnect sonlu pencere + CSeq takibi")
    _check(R, spec.get("pii", {}).get("raw_audio_in_spec_forbidden") is True,
           "I14 ham ses/PII spec'te yasak")

    # ── transfer (FR-TEL-007) yapı kontrolü
    tf = spec.get("transfer", {})
    _check(R, tf.get("mechanism") == "sip_refer" and {"COLD", "WARM", "WHISPER"} == set(tf.get("modes", [])),
           "transfer SIP REFER COLD/WARM/WHISPER (FR-TEL-007)")

    # ── invariant kataloğu sağlığı
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 15,
           "invariant kataloğu ≥15 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── I10: literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(TRUNKS_CFG):
        hits += _scan_secrets(_load(TRUNKS_CFG))
    _check(R, not hits, "I10 literal sır yok (spec+config)")

    # ── çapraz tutarlılık: config trunks ↔ spec trunks
    if os.path.exists(TRUNKS_CFG):
        cfg = _load(TRUNKS_CFG)
        spec_ids = {t["id"] for t in trunks}
        cfg_ids = {t["id"] for t in cfg.get("trunks", [])}
        _check(R, cfg_ids == spec_ids, "config trunks.json ↔ spec trunk kümesi birebir")
        _check(R, cfg.get("fallback_order") == fb.get("trunk_order"),
               "config fallback_order ↔ spec trunk_order birebir")
        for ct in cfg.get("trunks", []):
            _check(R, _is_placeholder(ct.get("auth_secret", "")),
                   "I10 config %s auth_secret ${ENV}" % ct.get("id"))
            _check(R, _is_placeholder(ct.get("region", "")),
                   "I11 config %s region ${ENV}" % ct.get("id"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# normalize — deterministik SIP/SDP/RTP normalize simülatörü
# ─────────────────────────────────────────────────────────────────────────────
class NormalizeError(Exception):
    pass


def _trunk(spec, tid):
    for t in spec.get("trunks", []):
        if t["id"] == tid:
            return t
    raise NormalizeError("bilinmeyen trunk: %s" % tid)


def _negotiate_sdp(offer, answer, allowed):
    """SDP offer/answer kesişimi → seçilen codec. answer içindeki ilk izinli narrowband codec.
    Döner: (selected|None, ok_narrowband)."""
    common = [c for c in (answer or []) if c in (offer or [])]
    # answer offer'da yoksa yine de answer'a bakarız (sunucu tek codec seçmiş olabilir)
    cand = common or [c for c in (answer or [])]
    for c in cand:
        if c in allowed:
            return c, True
    # ortak narrowband codec yok
    return (cand[0] if cand else None), False


def normalize_sequence(spec, sample):
    """BYOC SIP mesaj dizisini normalize ingress olaylarına indirger + invariant kontrol.
    Döner: (normalized_events, egress_events, findings) — findings=[(ok,label),...]."""
    F = []
    trunk = _trunk(spec, sample["trunk"])
    de_map = trunk["dialog_events"]
    eg_map = trunk["egress_events"]
    mp = spec["media_profile"]
    sdp_allowed = set(spec["sdp"]["allowed_codecs"])
    deadline = spec["barge_in"]["deadline_ms"]

    # ── transport ön kapı (I1): TLS sinyalleşme + SRTP medya
    F.append((sample.get("signaling_transport") == "tls", "I1 sinyalleşme TLS"))
    F.append((sample.get("media_transport") == "srtp", "I1 medya SRTP"))
    # ── auth ön kapı (I2)
    F.append((sample.get("authenticated") is True, "I2 trunk peer medya öncesi doğrulanmış"))

    state = spec["sip_dialog"]["initial"]
    vt = spec["sip_dialog"]["valid_transitions"]
    early_media_states = set(spec["sip_dialog"].get("early_media_states", []))
    ctx = {"tenant_id": None, "correlation_id": None, "call_id": None}
    normalized = []
    egress = []

    bad_codec = False
    rtp_before_answer = False
    region_ok = True
    selected_codec = None

    def trans(to):
        nonlocal state
        if to not in vt.get(state, []) and to != state:
            raise NormalizeError("geçersiz SIP diyalog geçiş %s→%s" % (state, to))
        state = to

    sdp_offer = []

    for m in sample.get("messages", []):
        ev = m.get("event")
        norm = de_map.get(ev, "__unknown__")
        if ev not in de_map:
            F.append((False, "I6 SIP olayı '%s' eşlenmemiş" % ev))
            continue

        # ── SIP diyalog SM güncellemesi (sinyal olayları normalize null olsa da SM'i sürer)
        if ev == "invite":
            trans("INVITE_RECEIVED")
            inv = m.get("invite", {})
            hdr = inv.get("headers", {})
            for k in ("tenant_id", "correlation_id", "call_id"):
                ctx[k] = hdr.get(k)
            sdp_offer = inv.get("sdp_offer", [])
            reg = inv.get("region")
            home = sample.get("home_region")
            if reg and home and reg != home:
                region_ok = False
        elif ev == "ringing":
            trans("RINGING")
        elif ev == "progress":
            pr = m.get("progress", {})
            if pr.get("early_media"):
                trans("EARLY_MEDIA")
                sel, ok = _negotiate_sdp(sdp_offer, pr.get("sdp_answer", []), sdp_allowed)
                selected_codec = sel
                if not ok:
                    bad_codec = True
        elif ev == "answer":
            trans("ANSWERED")
            sel, ok = _negotiate_sdp(sdp_offer, m.get("answer", {}).get("sdp_answer", []), sdp_allowed)
            selected_codec = sel
            if not ok:
                bad_codec = True
        elif ev == "rtp":
            # RTP answer/early-media öncesi reddedilir (I9)
            if state not in ("EARLY_MEDIA", "ANSWERED", "ESTABLISHED"):
                rtp_before_answer = True
                continue
            rtp = m.get("rtp", {})
            sr = rtp.get("sample_rate")
            enc = (rtp.get("encoding") or "")
            if sr and sr != mp["sample_rate_hz"]:
                bad_codec = True
            if enc and enc not in NARROWBAND_CODECS:
                bad_codec = True
            if state == "ANSWERED":
                trans("ESTABLISHED")
        elif ev == "dtmf":
            dm = m.get("dtmf", {}).get("mode")
            if dm and dm not in ("rfc2833", "sip_info"):
                F.append((False, "I12 DTMF modu tanınmıyor: %s" % dm))
        elif ev == "bye":
            trans("TERMINATING")
            trans("TERMINATED")

        # ── normalize ingress üretimi (yalnız null olmayan eşleme)
        if norm is None:
            continue
        normalized.append({"type": norm, "ctx": dict(ctx), "raw_event": ev})

    # ── egress / barge-in simülasyonu (I5)
    default_overhead = trunk.get("rtp_clear_overhead_ms", 0)
    for e in sample.get("egress", []):
        act = e.get("action")
        if act not in eg_map:
            F.append((False, "egress aksiyon '%s' eşlenmemiş" % act))
            continue
        rec = {"action": act, "provider_event": eg_map[act]}
        if act == "barge_in_clear":
            overhead = e.get("overhead_override_ms", default_overhead)
            detect = e.get("barge_in_detect_ms", 0)
            emit = detect + overhead
            rec["latency_ms"] = emit - detect
            F.append((rec["latency_ms"] <= deadline,
                      "I5 barge-in kesme %dms ≤ %dms (%s)" % (rec["latency_ms"], deadline, trunk["id"])))
        egress.append(rec)

    # ── invariant değerlendirmesi
    F.append((not rtp_before_answer, "I9 RTP answer/early-media öncesi yok"))
    F.append((not bad_codec, "I4/I15 medya 8kHz G.711 narrowband (transcode yok)"))
    F.append((region_ok, "I11 trunk bölge = home-region"))
    has_ctx = any(all(n["ctx"].get(k) for k in ("tenant_id", "correlation_id", "call_id"))
                  for n in normalized)
    F.append((has_ctx, "I3 tenant_id+correlation_id+call_id bağlandı"))
    if any(n["type"] == "stop" for n in normalized):
        F.append((state == "TERMINATED", "I9 diyalog TERMINATED ile sonlandı"))

    return normalized, egress, F


def normalize_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    try:
        normalized, egress, F = normalize_sequence(spec, sample)
    except NormalizeError as e:
        print("normalize[%s]: HATA — %s" % (name, e))
        # Kontrollü hata = kötü dizi reddi
        expect = sample.get("expect", "pass")
        return 0 if expect == "fail" else 1
    passed = sum(1 for ok, _ in F if ok)
    total = len(F)
    print("normalize[%s] trunk=%s" % (name, sample["trunk"]))
    print("  normalize ingress olay: %d (start/media/dtmf/stop)" % len(normalized))
    print("  egress aksiyon: %d" % len(egress))
    for ok, label in F:
        if not ok:
            print("  ✗ %s" % label)
    expect = sample.get("expect", "pass")
    gate_ok = (passed == total)
    print("  kapı: %d/%d %s" % (passed, total, "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 1) validate temel geçer
    case(validate_silent() == 0, "validate iyi spec'te 0 döndürür")

    # 2) bozuk spec: düz-metin sinyalleşme izinli → I1 eler
    s = json.loads(json.dumps(spec))
    s["transport"]["plaintext_signaling_allowed"] = True
    case(_validate_obj(s) != 0, "düz-metin SIP → validate eler (I1)")

    # 3) bozuk spec: SRTP zorunlu değil → I1 eler
    s = json.loads(json.dumps(spec))
    s["transport"]["srtp_required"] = False
    case(_validate_obj(s) != 0, "SRTP zorunsuz → validate eler (I1)")

    # 4) bozuk spec: tek trunk → I7 eler
    s = json.loads(json.dumps(spec))
    s["trunks"] = s["trunks"][:1]
    case(_validate_obj(s) != 0, "tek trunk → validate eler (I7)")

    # 5) bozuk spec: media 16kHz → I4 eler
    s = json.loads(json.dumps(spec))
    s["media_profile"]["sample_rate_hz"] = 16000
    case(_validate_obj(s) != 0, "16kHz → validate eler (I4)")

    # 6) bozuk spec: barge-in deadline 250 → I5 eler
    s = json.loads(json.dumps(spec))
    s["barge_in"]["deadline_ms"] = 250
    case(_validate_obj(s) != 0, "barge-in 250ms → validate eler (I5)")

    # 7) bozuk spec: secret literal → I10 eler
    s = json.loads(json.dumps(spec))
    s["trunks"][0]["auth_secret_ref"] = "sip_secret: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "literal secret → validate eler (I10)")

    # 8) bozuk spec: error taxonomy dışı hedef → I8 eler
    s = json.loads(json.dumps(spec))
    s["error_taxonomy"]["mapping"]["x"] = "NOT_A_TAXONOMY"
    case(_validate_obj(s) != 0, "taksonomi-dışı hedef → validate eler (I8)")

    # 9) bozuk spec: wideband codec izinli → I15 eler
    s = json.loads(json.dumps(spec))
    s["sdp"]["allowed_codecs"] = ["G722/8000"]
    case(_validate_obj(s) != 0, "wideband SDP izinli → validate eler (I15)")

    # 10) bozuk spec: SDP ortak codec yoksa transcode → I15 eler
    s = json.loads(json.dumps(spec))
    s["sdp"]["transcode_on_no_common_codec"] = True
    s["sdp"]["reject_on_no_common_codec"] = False
    case(_validate_obj(s) != 0, "SDP transcode-on-no-common → validate eler (I15)")

    # ── normalize davranış senaryoları ─────────────────────────────────────────
    happy = {
        "name": "st-happy", "trunk": "byoc-trunk-primary",
        "signaling_transport": "tls", "media_transport": "srtp",
        "authenticated": True, "home_region": "eu-central",
        "messages": [
            {"event": "invite", "invite": {"to_did": "+49301", "headers": {"tenant_id": "t1", "correlation_id": "c1", "call_id": "k1"},
             "region": "eu-central", "sdp_offer": ["PCMU/8000", "PCMA/8000", "telephone-event/8000"]}},
            {"event": "ringing"},
            {"event": "answer", "answer": {"sdp_answer": ["PCMU/8000", "telephone-event/8000"]}},
            {"event": "rtp", "rtp": {"payload_type": 0, "sample_rate": 8000, "encoding": "PCMU/8000"}},
            {"event": "dtmf", "dtmf": {"digit": "5", "mode": "rfc2833"}},
            {"event": "bye"},
        ],
        "egress": [{"action": "barge_in_clear", "barge_in_detect_ms": 0}],
    }
    _, _, F = normalize_sequence(spec, happy)
    case(all(ok for ok, _ in F), "normalize happy path tüm invariant geçer")

    # 11) normalize: RTP answer öncesi reddedilir (I9)
    bad = json.loads(json.dumps(happy))
    bad["messages"] = [
        {"event": "invite", "invite": {"headers": {"tenant_id": "t", "correlation_id": "c", "call_id": "k"},
         "sdp_offer": ["PCMU/8000"]}},
        {"event": "rtp", "rtp": {"sample_rate": 8000, "encoding": "PCMU/8000"}},
        {"event": "answer", "answer": {"sdp_answer": ["PCMU/8000"]}},
    ]
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "answer/early-media öncesi" in lbl for ok, lbl in F),
         "rtp-before-answer → I9 bulgu")

    # 12) normalize: early media (183) RTP MEŞRU — geçer (I9 istisnası)
    em = json.loads(json.dumps(happy))
    em["messages"] = [
        {"event": "invite", "invite": {"headers": {"tenant_id": "t", "correlation_id": "c", "call_id": "k"},
         "region": "eu-central", "sdp_offer": ["PCMU/8000"]}},
        {"event": "progress", "progress": {"early_media": True, "sdp_answer": ["PCMU/8000"]}},
        {"event": "rtp", "rtp": {"sample_rate": 8000, "encoding": "PCMU/8000"}},
        {"event": "answer", "answer": {"sdp_answer": ["PCMU/8000"]}},
        {"event": "bye"},
    ]
    _, _, F = normalize_sequence(spec, em)
    case(all(ok for ok, _ in F), "early-media RTP meşru → geçer (I9 istisnası)")

    # 13) normalize: 16kHz/wideband RTP → I4/I15 bulgu
    bad = json.loads(json.dumps(happy))
    bad["messages"][3]["rtp"]["sample_rate"] = 16000
    bad["messages"][3]["rtp"]["encoding"] = "G722/8000"
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "narrowband" in lbl for ok, lbl in F), "wideband RTP → I4/I15 bulgu")

    # 14) normalize: SDP ortak narrowband codec yok → bad_codec
    bad = json.loads(json.dumps(happy))
    bad["messages"][2]["answer"]["sdp_answer"] = ["G722/8000"]
    bad["messages"][3]["rtp"] = {"sample_rate": 8000, "encoding": "PCMU/8000"}
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "narrowband" in lbl for ok, lbl in F), "SDP ortak narrowband yok → bulgu")

    # 15) normalize: eksik bağlam (I3)
    bad = json.loads(json.dumps(happy))
    bad["messages"][0]["invite"]["headers"] = {"tenant_id": "t1"}
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "bağlandı" in lbl for ok, lbl in F), "eksik bağlam → I3 bulgu")

    # 16) normalize: bölge uyumsuz (I11)
    bad = json.loads(json.dumps(happy))
    bad["messages"][0]["invite"]["region"] = "us-east"
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "home-region" in lbl for ok, lbl in F), "bölge uyumsuz → I11 bulgu")

    # 17) normalize: yavaş barge-in (overhead şişirilmiş) → I5 eler
    slow = json.loads(json.dumps(happy))
    slow["egress"] = [{"action": "barge_in_clear", "barge_in_detect_ms": 0, "overhead_override_ms": 260}]
    _, _, F = normalize_sequence(spec, slow)
    case(any((not ok) and "barge-in kesme" in lbl for ok, lbl in F), "260ms overhead → I5 eler")

    # 18) normalize: düz-metin sinyalleşme dizide → I1 bulgu
    bad = json.loads(json.dumps(happy))
    bad["signaling_transport"] = "tcp"
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "sinyalleşme TLS" in lbl for ok, lbl in F), "tcp sinyalleşme → I1 bulgu")

    # 19) normalize: bilinmeyen trunk → kontrollü hata
    try:
        normalize_sequence(spec, {"trunk": "yok", "messages": []})
        case(False, "bilinmeyen trunk hata fırlatır")
    except NormalizeError:
        case(True, "bilinmeyen trunk → NormalizeError")

    # 20) ikinci trunk (secondary, sip_info DTMF) de happy path geçer (ADR-002 simetri)
    h2 = json.loads(json.dumps(happy))
    h2["trunk"] = "byoc-trunk-secondary"
    h2["messages"][4]["dtmf"]["mode"] = "sip_info"
    _, _, F = normalize_sequence(spec, h2)
    case(all(ok for ok, _ in F), "secondary trunk normalize happy path geçer (ADR-002)")

    # 21) geçersiz lifecycle geçiş → NormalizeError (bye sonrası rtp)
    try:
        seq = {"trunk": "byoc-trunk-primary", "signaling_transport": "tls", "media_transport": "srtp",
               "authenticated": True, "home_region": "eu-central",
               "messages": [
                   {"event": "invite", "invite": {"headers": {"tenant_id": "t", "correlation_id": "c", "call_id": "k"},
                    "region": "eu-central", "sdp_offer": ["PCMU/8000"]}},
                   {"event": "answer", "answer": {"sdp_answer": ["PCMU/8000"]}},
                   {"event": "bye"},
                   {"event": "answer", "answer": {"sdp_answer": ["PCMU/8000"]}},
               ]}
        normalize_sequence(spec, seq)
        case(False, "TERMINATED sonrası answer hata fırlatır")
    except NormalizeError:
        case(True, "geçersiz geçiş (terminal sonrası) → NormalizeError")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def validate_silent():
    """validate() ama spec dosyasından; çıkış kodu döner (stdout bastırılmaz)."""
    return _validate_obj(_load(SPEC_PATH))


def _validate_obj(spec_obj):
    """validate mantığını bellek içi spec nesnesine uygular (selftest için)."""
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
    print("""byoc-spec.json beklenen şekli (WBS 2.1.4):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,vendor_eval}
  media_profile{sample_rate_hz=8000, frame_ms=20, frames_per_sec=50, encodings[mulaw,alaw,pcm16],
                frame_bytes_mulaw=160, rtp_payload_types, no_transcode=true, resample_points_max≤1}   (I4)
  transport{signaling_scheme=sips, plaintext_signaling_allowed=false, srtp_required=true,
            plaintext_media_allowed=false, sbc_fronted=true}                                  (I1)
  auth{verify_before_media=true, methods[sip_digest,ip_acl,mtls], replay_window_sec}            (I2)
  context_binding{bound_at=call_setup, required_keys[tenant,corr,call], tenant_resolution[did…]} (I3)
  normalized_protocol{ingress_control_events[start,media,dtmf,stop], egress_actions[…]}          (I6, 2.1.3 ile aynı)
  sip_dialog{states[9], valid_transitions, rtp_media_before_answer_rejected=true,
             early_media_states, normalize_map{answer→start,rtp→media,dtmf→dtmf,bye→stop}}       (I9,I6)
  sdp{allowed_codecs[PCMU/PCMA], forbidden_wideband, reject_on_no_common_codec=true,
      transcode_on_no_common_codec=false}                                                       (I15)
  trunks[≥2]{id, kind=byoc_sip_trunk, auth_method, auth_secret_ref=${ENV}, region_pin=${ENV},
             media_transport=srtp, dtmf_mode[rfc2833|sip_info], offered_codecs,
             dialog_events{sip→normalize|null}, egress_events{play_audio,mark,barge_in_clear},
             rtp_clear_overhead_ms}                                                              (I7,I10,I11,I15)
  fallback{trunk_order[≥2], cross_mode_fallback=managed_cpaas_m1}                                 (I7)
  barge_in{source_event=BARGE_IN, egress_action=barge_in_clear, deadline_ms=200}                 (I5)
  dtmf{normalized_event=dtmf, modes[rfc2833,sip_info], digit_set}                                (I12)
  transfer{mechanism=sip_refer, modes[COLD,WARM,WHISPER]}                                        (FR-TEL-007)
  reconnect{enabled, reinvite_window_sec, cseq_tracking=true}                                    (I13)
  error_taxonomy{mapping(SIP kodu)→API §11.6, fallback_on[]}                                     (I8)
  residency{region_pin_required=true}                                                            (I11)
  pii{raw_audio_in_spec_forbidden=true}                                                          (I14)
  invariants[≥15]{id, desc, trace}

komutlar: validate | normalize <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "normalize":
        if len(sys.argv) < 3:
            print("kullanım: byoc_probe.py normalize <sample.json>")
            return 2
        return normalize_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|normalize|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
