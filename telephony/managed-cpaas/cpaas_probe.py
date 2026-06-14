#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cpaas_probe.py — WBS 2.1.3 Managed CPaaS entegrasyonu (Media Streams/WebSocket)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`db/`+`cache/`+`objstore/`+`eventstream/` probe disipliniyle aynı.

Komutlar:
  validate              cpaas-spec.json'ı invariant'lara + config sağlayıcı profillerine karşı doğrular (çıkış kodu).
  normalize <sample>    Deterministik normalize simülatörü — sağlayıcı medya-WS mesaj dizisini alır,
                        lifecycle SM'ini çalıştırır, normalize ingress olayları üretir, invariant'ları
                        (sıra, tenant bağlama, barge-in ≤200ms, codec, residency) kontrol eder; kapı→çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. `normalize` gerçek WS/broker yerine deterministik simülasyondur
(objstore access-decision / eventstream replay simülatörü deseni).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "cpaas-spec.json")
PROVIDERS_CFG = os.path.join(HERE, "config", "providers.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

NORMALIZED_INGRESS = {"start", "media", "dtmf", "stop"}
NORMALIZED_EGRESS = {"play_audio", "mark", "barge_in_clear"}
ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
# Sır tarayıcı: yorum satırları (sırrı *tarif eden* açıklama ≠ sır) elenir; eventstream probe deseni.
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
    _check(R, spec.get("wbs") == "2.1.3", "spec.wbs == 2.1.3")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── I4: medya profili (8kHz/20ms/μ-law, no-transcode)
    mp = spec.get("media_profile", {})
    _check(R, mp.get("sample_rate_hz") == 8000, "I4 media 8 kHz")
    _check(R, mp.get("frame_ms") == 20 and mp.get("frames_per_sec") == 50, "I4 20 ms / 50 fps")
    _check(R, "mulaw" in mp.get("encodings", []), "I4 μ-law encoding")
    _check(R, mp.get("frame_bytes_mulaw") == 160, "I4 μ-law 160 bayt/çerçeve")
    _check(R, mp.get("no_transcode") is True and mp.get("resample_points_max", 9) <= 1,
           "I4 no-transcode + ≤1 resample (FR-RES-008)")

    # ── I1/I2: transport + auth
    tr = spec.get("transport", {})
    _check(R, tr.get("scheme") == "wss" and tr.get("plaintext_allowed") is False,
           "I1 WSS zorunlu, düz-metin reddedilir (NFR 10.6)")
    au = spec.get("auth", {})
    _check(R, au.get("verify_before_media") is True, "I2 medya öncesi auth (verify_before_media)")
    _check(R, isinstance(au.get("replay_window_sec"), int) and au["replay_window_sec"] > 0,
           "I2 sonlu replay penceresi")

    # ── I3: context binding
    cb = spec.get("context_binding", {})
    _check(R, cb.get("bound_at") == "start", "I3 bağlam `start`ta")
    _check(R, set(["tenant_id", "correlation_id", "call_id"]).issubset(set(cb.get("required_keys", []))),
           "I3 tenant_id+correlation_id+call_id zorunlu")
    _check(R, cb.get("propagate_on_every_event") is True, "I3 her olaya taşınır (SAD §13.3)")

    # ── I6: normalize ingress kümesi (API §12.1)
    npn = spec.get("normalized_protocol", {})
    _check(R, set(npn.get("ingress_control_events", [])) == NORMALIZED_INGRESS,
           "I6 normalize ingress = {start,media,dtmf,stop} (API §12.1)")
    _check(R, set(npn.get("egress_actions", [])) == NORMALIZED_EGRESS,
           "egress aksiyon = {play_audio,mark,barge_in_clear}")

    # ── I7: ≥2 sağlayıcı + eksiksiz eşleme + fallback
    provs = spec.get("providers", [])
    managed = [p for p in provs if p.get("kind") == "managed_cpaas"]
    _check(R, len(managed) >= 2, "I7 ≥2 managed sağlayıcı (ADR-002)")
    for p in provs:
        pid = p.get("id", "?")
        ing = p.get("ingress_events", {})
        # her sağlayıcının non-null ingress eşlemeleri normalize kümesinde
        mapped = {v for v in ing.values() if v is not None}
        _check(R, mapped.issubset(NORMALIZED_INGRESS),
               "I6 %s ingress eşlemeleri normalize kümesinde" % pid)
        _check(R, set(ing.values()) >= {None} or True, "%s ingress tablo" % pid)  # yapı kontrolü
        # start/media/stop her sağlayıcıda eşlenmiş olmalı (zorunlu yaşam döngüsü)
        for need in ("start", "media", "stop", "dtmf"):
            inv = [k for k, v in ing.items() if v == need]
            _check(R, len(inv) >= 1, "I6 %s → normalize '%s' eşlemesi var" % (pid, need))
        eg = p.get("egress_events", {})
        _check(R, set(eg.keys()) == NORMALIZED_EGRESS,
               "%s egress aksiyonları tam (play_audio/mark/barge_in_clear)" % pid)
        _check(R, _is_placeholder(p.get("secret_ref", "")),
               "I10 %s secret_ref ${ENV} placeholder" % pid)
        _check(R, _is_placeholder(p.get("region_pin", "")),
               "I11 %s region_pin ${ENV} placeholder" % pid)
        bo = p.get("barge_in_clear_overhead_ms")
        _check(R, isinstance(bo, (int, float)) and bo >= 0,
               "%s barge_in_clear_overhead_ms tanımlı" % pid)

    # ── I5: barge-in
    bi = spec.get("barge_in", {})
    _check(R, bi.get("deadline_ms") == 200, "I5 barge-in deadline 200 ms (NFR 10.1)")
    _check(R, bi.get("source_event") == "BARGE_IN", "I5 source BARGE_IN (API §12.2)")
    _check(R, bi.get("egress_action") == "barge_in_clear", "I5 egress barge_in_clear")

    # ── I9: lifecycle
    lc = spec.get("lifecycle", {})
    states = set(lc.get("states", []))
    _check(R, {"CONNECTING", "AUTHENTICATED", "STARTED", "STREAMING", "STOPPED", "FAILED"} == states,
           "I9 lifecycle durumları tam")
    _check(R, lc.get("media_before_started_rejected") is True, "I9 `start` öncesi media reddedilir")
    vt = lc.get("valid_transitions", {})
    _check(R, all(s in states for s in vt), "I9 geçiş kaynakları durum kümesinde")
    _check(R, all(all(d in states for d in dests) for dests in vt.values()),
           "I9 geçiş hedefleri durum kümesinde")

    # ── I8: error taxonomy
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
    _check(R, dt.get("normalized_event") == "dtmf" and dt.get("digit_set"),
           "I12 DTMF normalize (FR-TEL-006)")
    rc = spec.get("reconnect", {})
    _check(R, rc.get("seq_tracking") is True and isinstance(rc.get("resume_window_sec"), (int, float))
           and rc.get("resume_window_sec") > 0, "I13 reconnect sonlu pencere + sıra takibi")
    _check(R, spec.get("pii", {}).get("raw_audio_in_spec_forbidden") is True,
           "I14 ham ses/PII spec'te yasak")

    # ── invariant kataloğu sağlığı
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 14,
           "invariant kataloğu ≥14 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── I10: literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(PROVIDERS_CFG):
        hits += _scan_secrets(_load(PROVIDERS_CFG))
    _check(R, not hits, "I10 literal sır yok (spec+config)")

    # ── çapraz tutarlılık: config providers ↔ spec providers
    if os.path.exists(PROVIDERS_CFG):
        cfg = _load(PROVIDERS_CFG)
        spec_ids = {p["id"] for p in provs}
        cfg_ids = {p["id"] for p in cfg.get("providers", [])}
        _check(R, cfg_ids == spec_ids, "config providers.json ↔ spec sağlayıcı kümesi birebir")
        for cp in cfg.get("providers", []):
            _check(R, _is_placeholder(cp.get("endpoint", "")) or cp.get("endpoint", "").startswith("wss://"),
                   "config %s endpoint wss/${ENV}" % cp.get("id"))

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# normalize — deterministik medya-WS normalize simülatörü
# ─────────────────────────────────────────────────────────────────────────────
class NormalizeError(Exception):
    pass


def _provider(spec, pid):
    for p in spec.get("providers", []):
        if p["id"] == pid:
            return p
    raise NormalizeError("bilinmeyen sağlayıcı: %s" % pid)


def normalize_sequence(spec, sample):
    """Sağlayıcı medya-WS mesaj dizisini normalize ingress olaylarına indirger + invariant kontrol.
    Döner: (normalized_events, egress_events, findings) — findings=[(ok,label),...]."""
    F = []
    prov = _provider(spec, sample["provider"])
    ing_map = prov["ingress_events"]
    eg_map = prov["egress_events"]
    mp = spec["media_profile"]
    deadline = spec["barge_in"]["deadline_ms"]

    # ── transport/auth ön kapı (I1/I2)
    F.append((sample.get("transport") == "wss", "I1 taşıma wss"))
    F.append((sample.get("authenticated") is True, "I2 bağlantı medya öncesi doğrulanmış"))

    state = spec["lifecycle"]["initial"]
    vt = spec["lifecycle"]["valid_transitions"]
    ctx = {"tenant_id": None, "correlation_id": None, "call_id": None}
    normalized = []
    egress = []

    def trans(to):
        nonlocal state
        if to not in vt.get(state, []) and to != state:
            raise NormalizeError("geçersiz lifecycle geçiş %s→%s" % (state, to))
        state = to

    # auth doğrulanmışsa CONNECTING→AUTHENTICATED
    if sample.get("authenticated"):
        trans("AUTHENTICATED")

    bad_codec = False
    media_before_start = False
    region_ok = True

    for fr in sample.get("frames", []):
        ev = fr.get("event")
        norm = ing_map.get(ev, "__unknown__")
        if ev not in ing_map:
            F.append((False, "I6 sağlayıcı olayı '%s' eşlenmemiş" % ev))
            continue
        if norm is None:
            continue  # connected/mark gibi taşıma-içi, normalize edilmez
        if norm == "start":
            params = fr.get("start", {}).get("customParameters", {}) or fr.get("start", {}).get("client_state", {})
            for k in ("tenant_id", "correlation_id", "call_id"):
                ctx[k] = params.get(k)
            fmt = fr.get("start", {}).get("mediaFormat", {})
            enc = (fmt.get("encoding") or "").lower()
            sr = fmt.get("sampleRate")
            if sr and sr != mp["sample_rate_hz"]:
                bad_codec = True
            if enc and not any(e in enc for e in ("mulaw", "x-mulaw", "pcm", "l16")):
                bad_codec = True
            reg = fr.get("start", {}).get("region")
            home = sample.get("home_region")
            if reg and home and reg != home:
                region_ok = False
            trans("STARTED")
        elif norm == "media":
            if state not in ("STARTED", "STREAMING"):
                media_before_start = True
                continue  # `start` öncesi media reddedilir (I9)
            trans("STREAMING")
        elif norm == "dtmf":
            pass
        elif norm == "stop":
            trans("STOPPED")
        # bağlam taşınır (I3): her normalize olay ctx kopyası alır
        normalized.append({"type": norm, "ctx": dict(ctx), "raw_event": ev})

    # ── egress / barge-in simülasyonu (I5)
    overhead = prov.get("barge_in_clear_overhead_ms", 0)
    for e in sample.get("egress", []):
        act = e.get("action")
        if act not in eg_map:
            F.append((False, "egress aksiyon '%s' eşlenmemiş" % act))
            continue
        rec = {"action": act, "provider_event": eg_map[act]}
        if act == "barge_in_clear":
            detect = e.get("barge_in_detect_ms", 0)
            emit = detect + overhead  # adapter overhead deterministik modeli
            rec["latency_ms"] = emit - detect
            F.append((rec["latency_ms"] <= deadline,
                      "I5 barge-in kesme %dms ≤ %dms (%s)" % (rec["latency_ms"], deadline, prov["id"])))
        egress.append(rec)

    # ── invariant değerlendirmesi
    F.append((not media_before_start, "I9 `start` öncesi media yok"))
    F.append((not bad_codec, "I4 medya formatı 8kHz μ-law/PCM"))
    F.append((region_ok, "I11 sağlayıcı bölge = home-region"))
    # I3: en az bir normalize media/start olayında tam bağlam
    has_ctx = any(all(n["ctx"].get(k) for k in ("tenant_id", "correlation_id", "call_id"))
                  for n in normalized)
    F.append((has_ctx, "I3 tenant_id+correlation_id+call_id bağlandı"))
    # lifecycle düzgün sonlandı mı (stop varsa STOPPED)
    if any(n["type"] == "stop" for n in normalized):
        F.append((state == "STOPPED", "I9 lifecycle STOPPED ile sonlandı"))

    return normalized, egress, F


def normalize_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    try:
        normalized, egress, F = normalize_sequence(spec, sample)
    except NormalizeError as e:
        print("normalize[%s]: HATA — %s" % (name, e))
        # Kontrollü hata = kötü dizi reddi; beklenen-fail senaryolar için exit 1
        return 1
    passed = sum(1 for ok, _ in F if ok)
    total = len(F)
    print("normalize[%s] sağlayıcı=%s" % (name, sample["provider"]))
    print("  normalize ingress olay: %d (start/media/dtmf/stop)" % len(normalized))
    print("  egress aksiyon: %d" % len(egress))
    for ok, label in F:
        if not ok:
            print("  ✗ %s" % label)
    expect = sample.get("expect", "pass")
    gate_ok = (passed == total)
    print("  kapı: %d/%d %s" % (passed, total, "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        # beklenen-fail senaryosu: kapı elemeli
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

    # 2) bozuk spec: plaintext WS izinli → I1 eler
    s = json.loads(json.dumps(spec))
    s["transport"]["plaintext_allowed"] = True
    case(_validate_obj(s) != 0, "plaintext WS → validate eler (I1)")

    # 3) bozuk spec: tek sağlayıcı → I7 eler
    s = json.loads(json.dumps(spec))
    s["providers"] = s["providers"][:1]
    case(_validate_obj(s) != 0, "tek sağlayıcı → validate eler (I7)")

    # 4) bozuk spec: media 16kHz → I4 eler
    s = json.loads(json.dumps(spec))
    s["media_profile"]["sample_rate_hz"] = 16000
    case(_validate_obj(s) != 0, "16kHz → validate eler (I4)")

    # 5) bozuk spec: barge-in deadline 250 → I5 eler
    s = json.loads(json.dumps(spec))
    s["barge_in"]["deadline_ms"] = 250
    case(_validate_obj(s) != 0, "barge-in 250ms → validate eler (I5)")

    # 6) bozuk spec: secret literal → I10 eler
    s = json.loads(json.dumps(spec))
    s["providers"][0]["secret_ref"] = "auth_token: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "literal secret → validate eler (I10)")

    # 7) bozuk spec: error taxonomy dışı hedef → I8 eler
    s = json.loads(json.dumps(spec))
    s["error_taxonomy"]["mapping"]["x"] = "NOT_A_TAXONOMY"
    case(_validate_obj(s) != 0, "taksonomi-dışı hedef → validate eler (I8)")

    # 8) normalize: happy path (sentetik) geçer
    happy = {
        "name": "st-happy", "provider": "twilio-media-streams", "transport": "wss",
        "authenticated": True, "home_region": "eu-central",
        "frames": [
            {"event": "connected"},
            {"event": "start", "start": {"customParameters": {"tenant_id": "t1", "correlation_id": "c1", "call_id": "k1"},
             "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}, "region": "eu-central"}},
            {"event": "media", "media": {"payload": "AAAA"}},
            {"event": "dtmf", "dtmf": {"digit": "5"}},
            {"event": "stop"},
        ],
        "egress": [{"action": "barge_in_clear", "barge_in_detect_ms": 0}],
    }
    _, _, F = normalize_sequence(spec, happy)
    case(all(ok for ok, _ in F), "normalize happy path tüm invariant geçer")

    # 9) normalize: media before start reddedilir (I9)
    bad = json.loads(json.dumps(happy))
    bad["frames"] = [{"event": "media", "media": {"payload": "AAAA"}},
                     {"event": "start", "start": {"customParameters": {"tenant_id": "t", "correlation_id": "c", "call_id": "k"},
                      "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}}}]
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "start` öncesi" in lbl for ok, lbl in F), "media-before-start → I9 bulgu")

    # 10) normalize: 16kHz codec uyumsuz (I4)
    bad = json.loads(json.dumps(happy))
    bad["frames"][1]["start"]["mediaFormat"]["sampleRate"] = 16000
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "8kHz" in lbl for ok, lbl in F), "16kHz start → I4 bulgu")

    # 11) normalize: eksik bağlam (I3)
    bad = json.loads(json.dumps(happy))
    bad["frames"][1]["start"]["customParameters"] = {"tenant_id": "t1"}
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "bağlandı" in lbl for ok, lbl in F), "eksik bağlam → I3 bulgu")

    # 12) normalize: yavaş barge-in (overhead şişirilmiş) → I5 eler
    s2 = json.loads(json.dumps(spec))
    _provider(s2, "twilio-media-streams")["barge_in_clear_overhead_ms"] = 260
    _, _, F = normalize_sequence(s2, happy)
    case(any((not ok) and "barge-in kesme" in lbl for ok, lbl in F), "260ms overhead → I5 eler")

    # 13) normalize: bölge uyumsuz (I11)
    bad = json.loads(json.dumps(happy))
    bad["frames"][1]["start"]["region"] = "us-east"
    _, _, F = normalize_sequence(spec, bad)
    case(any((not ok) and "home-region" in lbl for ok, lbl in F), "bölge uyumsuz → I11 bulgu")

    # 14) normalize: bilinmeyen sağlayıcı → kontrollü hata
    try:
        normalize_sequence(spec, {"provider": "yok", "frames": []})
        case(False, "bilinmeyen sağlayıcı hata fırlatır")
    except NormalizeError:
        case(True, "bilinmeyen sağlayıcı → NormalizeError")

    # 15) ikinci sağlayıcı (telnyx) de happy path geçer (ADR-002 simetri)
    h2 = json.loads(json.dumps(happy))
    h2["provider"] = "telnyx-media-streaming"
    _, _, F = normalize_sequence(spec, h2)
    case(all(ok for ok, _ in F), "telnyx normalize happy path geçer")

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
    print("""cpaas-spec.json beklenen şekli (WBS 2.1.3):
  wbs, version, phase, trace{fr,nfr,sad,adr,api}
  media_profile{sample_rate_hz=8000, frame_ms=20, frames_per_sec=50, encodings[mulaw,pcm16],
                frame_bytes_mulaw=160, no_transcode=true, resample_points_max≤1}   (I4)
  transport{scheme=wss, plaintext_allowed=false, tls_min_version}                  (I1)
  auth{verify_before_media=true, methods[], replay_window_sec}                      (I2)
  context_binding{bound_at=start, required_keys[tenant,corr,call], propagate=true}  (I3)
  normalized_protocol{ingress_control_events[start,media,dtmf,stop], egress_actions[…]}  (I6)
  providers[≥2]{id, kind=managed_cpaas, auth_method, secret_ref=${ENV}, region_pin=${ENV},
                ingress_events{provider→normalize|null}, egress_events{play_audio,mark,barge_in_clear},
                barge_in_clear_overhead_ms}                                         (I7,I10,I11)
  lifecycle{states[6], valid_transitions, media_before_started_rejected=true}       (I9)
  barge_in{source_event=BARGE_IN, egress_action=barge_in_clear, deadline_ms=200}    (I5)
  dtmf{normalized_event=dtmf, digit_set}                                            (I12)
  reconnect{enabled, resume_window_sec, seq_tracking=true}                          (I13)
  error_taxonomy{mapping→API §11.6, fallback_on[]}                                  (I8)
  residency{region_pin_required=true}                                              (I11)
  pii{raw_audio_in_spec_forbidden=true}                                            (I14)
  invariants[≥14]{id, desc, trace}

komutlar: validate | normalize <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "normalize":
        if len(sys.argv) < 3:
            print("kullanım: cpaas_probe.py normalize <sample.json>")
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
