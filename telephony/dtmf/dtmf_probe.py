#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dtmf_probe.py — WBS 2.1.6 DTMF algılama/üretme (RFC 2833 / SIP INFO)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
`telephony/managed-cpaas/` + `telephony/byoc-sip/` + `telephony/numbering/` probe disipliniyle aynı.

DTMF OLAY DÜZLEMİ (TelephonyAdapter içi; medya/numaralandırma düzlemi değil):
  • Algılama (inbound):  RFC 2833/4733 RTP telephone-event (çok-paketli → debounce) + SIP INFO
                         → birleşik normalize `dtmf` olayı (API §12.1/§12.2, SAD §6.1).
  • Üretme  (outbound):  sendDtmf(callId, digits) → müzakere edilen moda göre paket/INFO dizisi (API §11.5).
  • Maskeleme:           PCI/hassas pencerede basamak yalnız aksiyon kanalına; transkript/kayıt MASK_TOKEN (BRD §8.5).

Komutlar:
  validate              dtmf-spec.json'ı invariant'lara + config profillerine karşı doğrular (çıkış kodu).
  detect <sample>       Deterministik DTMF algılama simülatörü — RFC 2833 debounce + SIP INFO ayrıştırma →
                        basamak dizisi; süre kapısı + kod eşlemesi + maskeleme kontrol (FR-TEL-006); kapı→çıkış kodu.
  generate <sample>     Deterministik DTMF üretme simülatörü — basamaklar → paket/INFO dizisi; mod + basamak
                        doğrulama + inter-digit boşluk (FR-TEL-006, API §11.5); kapı→çıkış kodu.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. detect/generate gerçek RTP/SIP yığını yerine deterministik simülasyondur
(numbering normalize / byoc normalize / objstore access-decision deseni). Gerçek kart/PIN verisi YOK.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "dtmf-spec.json")
MODES_CFG = os.path.join(HERE, "config", "dtmf-modes.json")

ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
MODES = {"rfc2833", "sip_info"}
# Sır tarayıcı: yorum satırları (sırrı *tarif eden* açıklama ≠ sır) elenir; eventstream/byoc/numbering deseni.
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class DtmfError(Exception):
    """Geçersiz/desteklenmeyen DTMF — sessizce kabul yok, reddet (D3/D10)."""


# ─────────────────────────────────────────────────────────────────────────────
# Kanonik basamak / olay kodu eşlemesi (FR-TEL-006, RFC 2833)
# ─────────────────────────────────────────────────────────────────────────────
def _code_map(spec):
    """event_code_map'i ($comment hariç) str-kod → basamak olarak döner."""
    raw = spec.get("dtmf", {}).get("event_code_map", {})
    return {k: v for k, v in raw.items() if not k.startswith("$")}


def _digit_set(spec):
    return spec.get("dtmf", {}).get("digit_set", "0123456789*#ABCD")


def map_event_code(code, code_map):
    """RFC 2833 tamsayı olay kodu (0..15) → kanonik basamak. Aralık dışı → DtmfError (D3)."""
    try:
        k = str(int(code))
    except (TypeError, ValueError):
        raise DtmfError("olay kodu sayısal değil: %r" % code)
    if k in code_map:
        return code_map[k]
    raise DtmfError("olay kodu aralık dışı (>15): %s" % code)


def canonical_digit(token, code_map, digit_set):
    """SIP INFO Signal / gönderilecek basamak → kanonik basamak. Geçersiz → DtmfError (D3/D5/D7)."""
    if token is None:
        raise DtmfError("boş DTMF basamağı")
    t = str(token).strip().upper()
    if len(t) == 1 and t in digit_set:
        return t
    # numerik olay-kodu biçimi (ör. '10'→'*')
    if t.isdigit() and t in code_map:
        return code_map[t]
    raise DtmfError("geçersiz DTMF basamağı/kod: %r" % token)


def _digit_to_code(code_map):
    """basamak → olay kodu (üretme için ters eşleme)."""
    return {v: int(k) for k, v in code_map.items()}


# ─────────────────────────────────────────────────────────────────────────────
# Algılama çekirdeği (deterministik — FR-TEL-006)
# ─────────────────────────────────────────────────────────────────────────────
def detect_rfc2833(packets, clock_rate, min_ms, code_map):
    """RFC 2833/4733 telephone-event paket dizisini mantıksal basamaklara DEBOUNCE eder (D2).
    Paket alanları: event(kod 0..15), marker(bool, yeni olay başı), duration(timestamp birimi=örnek),
    e(bool, End-bit). Süre = duration*1000/clock_rate ms; < min_ms ise sahte → düşürülür (D4).
    Döner [(digit, dur_ms), ...]. Geçersiz kod → DtmfError (D3)."""
    digits = []
    run = {"open": False}

    def finalize():
        if not run.get("open") or run.get("emitted"):
            return
        run["emitted"] = True
        dur_ms = run["dur"] * 1000.0 / clock_rate
        if dur_ms >= min_ms:
            digits.append((map_event_code(run["event"], code_map), dur_ms))
        # else: süre-altı sahte olay (D4) → yayılmaz

    for p in packets:
        ev = p.get("event")
        if ev is None:
            raise DtmfError("RFC 2833 paketinde 'event' yok")
        ev = int(ev)
        dur = int(p.get("duration", 0))
        new_run = bool(p.get("marker")) or (not run.get("open")) or ev != run.get("event")
        if new_run:
            finalize()
            run = {"open": True, "event": ev, "dur": dur, "emitted": False}
        else:
            run["dur"] = max(run["dur"], dur)
        if p.get("e"):                       # End-bit → sonlandır (artık kopyalar debounce edilir, D2)
            finalize()
    finalize()                               # End-bit'siz iz sonu (kayıp-End dayanıklılığı)
    return digits


def detect_sip_info(content_type, body, min_ms, code_map, digit_set):
    """SIP INFO gövdesini tek basamağa ayrıştırır (D5). application/dtmf-relay → 'Signal='/'Duration=';
    application/dtmf → düz basamak. Süre-altı → None (düşür, D4). Geçersiz → DtmfError."""
    if content_type == "application/dtmf-relay":
        signal = None
        dur_ms = None
        for line in str(body).replace("\r", "").split("\n"):
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().lower()
            v = v.strip()
            if k == "signal":
                signal = v
            elif k == "duration":
                try:
                    dur_ms = float(v)
                except ValueError:
                    raise DtmfError("SIP INFO Duration sayısal değil: %r" % v)
        if signal is None:
            raise DtmfError("SIP INFO (dtmf-relay) Signal yok")
    elif content_type == "application/dtmf":
        signal = str(body).strip()
        dur_ms = None
    else:
        raise DtmfError("desteklenmeyen SIP INFO content-type: %r" % content_type)
    digit = canonical_digit(signal, code_map, digit_set)
    if dur_ms is not None and dur_ms < min_ms:
        return None                          # süre-altı sahte (D4)
    return (digit, dur_ms if dur_ms is not None else float(min_ms))


def _make_event(digit, mode, dur_ms, sensitive, mask_token):
    """Birleşik normalize DTMF olayı (D6). masked ise transcript_value=MASK_TOKEN, digit (aksiyon) korunur (D8)."""
    return {
        "digit": digit,
        "mode": mode,
        "duration_ms": round(dur_ms, 1),
        "masked": bool(sensitive),
        "transcript_value": mask_token if sensitive else digit,
    }


def detect_sequence(spec, sample):
    """sample.events[] üzerinden algılamayı çalıştırır. Döner detected[] (normalize olaylar).
    DtmfError fırlatabilir (geçersiz kod/küme/içerik — D3/D5/D10)."""
    d = spec.get("dtmf", {})
    det = spec.get("detection", {})
    clock = d.get("rfc2833_clock_rate", 8000)
    min_ms = sample.get("min_duration_ms", det.get("min_duration_ms", 40))
    code_map = _code_map(spec)
    digit_set = _digit_set(spec)
    mask_token = spec.get("normalized_dtmf_event", {}).get("mask_token", "•")
    sensitive = sample.get("sensitive", False)

    detected = []
    for ev in sample.get("events", []):
        t = ev.get("type")
        if t == "rfc2833":
            for dg, dur in detect_rfc2833(ev.get("packets", []), clock, min_ms, code_map):
                detected.append(_make_event(dg, "rfc2833", dur, sensitive, mask_token))
        elif t == "sip_info":
            res = detect_sip_info(ev.get("content_type"), ev.get("body", ""), min_ms, code_map, digit_set)
            if res is not None:
                dg, dur = res
                detected.append(_make_event(dg, "sip_info", dur, sensitive, mask_token))
        else:
            raise DtmfError("bilinmeyen event tipi: %r" % t)
    return detected


def evaluate_detection(spec, sample):
    """detect_sequence + invariant değerlendirmesi. Döner (detected, findings)."""
    mask_token = spec.get("normalized_dtmf_event", {}).get("mask_token", "•")
    sensitive = sample.get("sensitive", False)
    detected = detect_sequence(spec, sample)
    F = []
    got = "".join(d["digit"] for d in detected)
    want = sample.get("expected_digits")
    if want is not None:
        F.append((got == want,
                  "D2/D3/D4 algılanan basamaklar '%s'%s" % (got, "" if got == want else " (beklenen '%s')" % want)))
    # D6 birleşik normalize olay
    F.append((all(d["mode"] in MODES for d in detected),
              "D6 her olay birleşik dtmf moduna indirgendi (mode-agnostik)"))
    # D8 maskeleme
    if sensitive:
        ok = all(d["masked"] and d["transcript_value"] == mask_token and d["transcript_value"] != d["digit"]
                 for d in detected)
        F.append((ok if detected else True,
                  "D8 hassas pencere: transkript MASK_TOKEN, basamak değeri yalnız aksiyon kanalında (sızmaz)"))
    else:
        F.append((all((not d["masked"]) and d["transcript_value"] == d["digit"] for d in detected),
                  "D8 normal pencere: basamak transkriptte görünür"))
    return detected, F


def detect_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    try:
        detected, F = evaluate_detection(spec, sample)
    except DtmfError as ex:
        print("detect[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1
    digits = "".join(d["digit"] for d in detected)
    shown = "".join(d["transcript_value"] for d in detected)
    print("detect[%s] basamak='%s' transkript='%s' (%d olay, sensitive=%s)"
          % (name, digits, shown, len(detected), sample.get("sensitive", False)))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F)
    print("  kapı: %d/%d %s" % (sum(1 for ok, _ in F if ok), len(F), "🟢 GEÇTİ" if gate_ok else "🔴 ELENDİ"))
    if expect == "fail":
        return 0 if not gate_ok else 1
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# Üretme çekirdeği (deterministik — FR-TEL-006, API §11.5)
# ─────────────────────────────────────────────────────────────────────────────
def generate_dtmf(spec, profile, digits):
    """digits → müzakere edilen moda göre paket/INFO dizisi (D7). Geçersiz basamak/mod → DtmfError.
    Döner (records[], findings[])."""
    code_map = _code_map(spec)
    digit_set = _digit_set(spec)
    to_code = _digit_to_code(code_map)
    gen = spec.get("generation", {})
    mode = profile.get("dtmf_mode")
    F = []

    if mode not in MODES:
        raise DtmfError("desteklenmeyen DTMF modu: %r (→ UNAVAILABLE)" % mode)
    if not digits:
        raise DtmfError("gönderilecek basamak yok")

    # D7: gönderim ÖNCESİ tüm basamaklar doğrulanır (geçersiz → INVALID_REQUEST, hiç gönderilmez)
    canon = [canonical_digit(ch, code_map, digit_set) for ch in digits]
    F.append((True, "D7 %d basamak gönderim öncesi doğrulandı" % len(canon)))

    end_red = profile.get("end_redundancy", gen.get("end_redundancy", 3))
    gap = profile.get("inter_digit_gap_ms", gen.get("inter_digit_gap_ms", 40))
    records = []
    for i, ch in enumerate(canon):
        rec = {"digit": ch, "mode": mode, "index": i, "gap_ms": (gap if i > 0 else 0)}
        if mode == "rfc2833":
            code = to_code[ch]
            # marker'lı başlangıç + ara paket + end_red adet End-bit (E=1) artık paket
            rec["event_code"] = code
            rec["packets"] = 2 + end_red          # start(marker) + 1 ara + end_red End paketi
            rec["end_packets"] = end_red
            rec["marker_first"] = True
        else:  # sip_info
            rec["content_type"] = profile.get("sip_info_content_type", "application/dtmf-relay")
            rec["info_requests"] = 1
        records.append(rec)

    # ── üretilen dizi invariant'ları (D7)
    F.append((len(records) == len(digits), "D7 dizi uzunluğu basamak sayısına eşit"))
    if mode == "rfc2833":
        F.append((all(r["marker_first"] and r["end_packets"] == end_red and r["packets"] >= 1 + end_red
                      for r in records),
                  "D7 her basamak: marker başlangıç + %d End-bit artık paket" % end_red))
    else:
        F.append((all(r["info_requests"] == 1 for r in records), "D7 her basamak tek SIP INFO isteği"))
    F.append((all(r["gap_ms"] == (gap if r["index"] > 0 else 0) for r in records),
              "D7 inter-digit boşluk uygulandı (%d ms)" % gap))
    return records, F


def _profile_by_name(cfg, name):
    for p in cfg.get("profiles", []):
        if p.get("name") == name:
            return p
    raise DtmfError("bilinmeyen profil: %s" % name)


def generate_cmd(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    name = sample.get("name", os.path.basename(sample_path))
    expect = sample.get("expect", "pass")
    # profil: inline sample["profile_obj"] veya config'ten isim ile
    if "profile_obj" in sample:
        profile = sample["profile_obj"]
    else:
        cfg = _load(MODES_CFG)
        try:
            profile = _profile_by_name(cfg, sample["profile"])
        except DtmfError as ex:
            print("generate[%s]: %s" % (name, ex))
            return 0 if expect == "fail" else 1
    try:
        records, F = generate_dtmf(spec, profile, sample.get("digits", ""))
    except DtmfError as ex:
        print("generate[%s]: REDDEDİLDİ — %s" % (name, ex))
        return 0 if expect == "fail" else 1
    print("generate[%s] digits='%s' mode=%s → %d kayıt"
          % (name, sample.get("digits", ""), profile.get("dtmf_mode"), len(records)))
    for ok, label in F:
        print("  %s %s" % ("✓" if ok else "✗", label))
    gate_ok = all(ok for ok, _ in F)
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

    _check(R, spec.get("wbs") == "2.1.6", "spec.wbs == 2.1.6")
    _check(R, spec.get("version"), "spec.version mevcut")

    # ── D1/D3/D6: DTMF temel sözleşmesi
    d = spec.get("dtmf", {})
    _check(R, set(d.get("modes", [])) == MODES, "DTMF modları {rfc2833, sip_info}")
    _check(R, d.get("inband_detection") is False, "D1 in-band algılama kapalı (yalnız out-of-band)")
    _check(R, d.get("normalized_event") == "dtmf", "D6 normalize olay 'dtmf'")
    _check(R, d.get("digit_set") == "0123456789*#ABCD", "D3 basamak kümesi 0-9*#A-D")
    cm = _code_map(spec)
    _check(R, len(cm) == 16, "D3 olay kodu eşlemesi 16 girdi (0..15)")
    # eşleme kanonik mi: 0..9 kendisi, 10='*',11='#',12-15=A-D
    canon_ok = all(cm.get(str(i)) == str(i) for i in range(10)) and \
        cm.get("10") == "*" and cm.get("11") == "#" and \
        cm.get("12") == "A" and cm.get("13") == "B" and cm.get("14") == "C" and cm.get("15") == "D"
    _check(R, canon_ok, "D3 olay kodu→basamak eşlemesi kanonik")
    # aralık dışı kod reddedilir
    rng_ok = True
    try:
        map_event_code(16, cm)
        rng_ok = False
    except DtmfError:
        pass
    _check(R, rng_ok, "D3 kod 16 reddedilir (aralık dışı)")

    # ── D2/D4: algılama sözleşmesi
    det = spec.get("detection", {})
    _check(R, det.get("rfc2833_debounce") is True, "D2 RFC 2833 debounce açık")
    _check(R, det.get("finalize_on_end_bit") is True and det.get("finalize_on_event_change") is True,
           "D2 End-bit + olay-değişimi sonlandırma")
    _check(R, isinstance(det.get("min_duration_ms"), (int, float)) and det.get("min_duration_ms") > 0,
           "D4 min_duration_ms pozitif kapı")
    _check(R, set(det.get("sip_info_content_types", [])) >= {"application/dtmf-relay", "application/dtmf"},
           "D5 SIP INFO content-type'ları")

    # ── D7: üretme sözleşmesi
    gen = spec.get("generation", {})
    _check(R, gen.get("validate_before_send") is True, "D7 gönderim öncesi doğrulama")
    _check(R, isinstance(gen.get("inter_digit_gap_ms"), (int, float)) and gen.get("inter_digit_gap_ms") >= 0,
           "D7 inter-digit boşluk tanımlı")
    _check(R, isinstance(gen.get("end_redundancy"), int) and gen.get("end_redundancy") >= 1,
           "D7 End-bit redundancy ≥1")

    # ── D8: maskeleme sözleşmesi
    m = spec.get("masking", {})
    _check(R, m.get("sensitive_window_supported") is True, "D8 hassas pencere desteği")
    _check(R, m.get("digit_value_to") == "action_channel_only", "D8 basamak değeri yalnız aksiyon kanalı")
    _check(R, set(m.get("mask_in", [])) >= {"transcript", "recording", "observability"},
           "D8 transkript/kayıt/gözlemlenebilirlik maskelenir")
    _check(R, m.get("cp_key") == "cp.sector.pci_in_scope", "D8 PCI compliance anahtarı")

    # ── D9: turn entegrasyonu (barge-in)
    ti = spec.get("turn_integration", {})
    _check(R, ti.get("can_trigger_barge_in") is True and ti.get("barge_in_deadline_ms") == 200,
           "D9 DTMF barge-in tetikler (≤200ms)")

    # ── D10: error taxonomy
    et = spec.get("error_taxonomy", {})
    mapping = et.get("mapping", {})
    _check(R, len(mapping) >= 4, "D10 hata eşlemesi (≥4)")
    _check(R, all(v in ERROR_TAXONOMY for v in mapping.values()),
           "D10 tüm hedefler API §11.6 ErrorTaxonomy'de")
    _check(R, mapping.get("invalid_digit") == "INVALID_REQUEST"
           and mapping.get("unsupported_mode") == "UNAVAILABLE"
           and mapping.get("region_mismatch") == "REGION_VIOLATION",
           "D10 geçersiz→INVALID_REQUEST, mod→UNAVAILABLE, bölge→REGION_VIOLATION")

    # ── D11/D12: residency + pii
    _check(R, spec.get("residency", {}).get("region_pin_required") is True, "D11 residency region pin")
    _check(R, spec.get("pii", {}).get("card_data_in_spec_forbidden") is True,
           "D12 kart verisi spec'te yasak")
    _check(R, spec.get("pii", {}).get("raw_payload_in_spec_forbidden") is True,
           "D12 ham RTP payload spec'te yasak")

    # ── invariant kataloğu
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    _check(R, len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 12,
           "invariant kataloğu ≥12 + tekil ID")
    _check(R, all(i.get("trace") for i in spec.get("invariants", [])),
           "her invariant trace taşır")

    # ── D12: literal sır taraması (spec + config)
    hits = _scan_secrets(spec)
    if os.path.exists(MODES_CFG):
        hits += _scan_secrets(_load(MODES_CFG))
    _check(R, not hits, "D12 literal sır yok (spec+config)")

    # ── config profilleri doğrulaması
    if os.path.exists(MODES_CFG):
        cfg = _load(MODES_CFG)
        profs = cfg.get("profiles", [])
        _check(R, len(profs) >= 2, "config ≥2 DTMF profili")
        names = [p.get("name") for p in profs]
        _check(R, len(names) == len(set(names)), "config profil isimleri benzersiz")
        for p in profs:
            _check(R, p.get("dtmf_mode") in MODES, "config %s modu geçerli" % p.get("name"))
            _check(R, bool(p.get("region")), "D11 config %s bölge pini var" % p.get("name"))
            if p.get("dtmf_mode") == "rfc2833":
                _check(R, p.get("rfc2833_payload_type") and p.get("end_redundancy"),
                       "config %s rfc2833 parametreleri" % p.get("name"))
            else:
                _check(R, p.get("sip_info_content_type") in det.get("sip_info_content_types", []),
                       "config %s sip_info content-type geçerli" % p.get("name"))
        # her iki mod da en az bir profilde temsil edilir (vendor-neutral ≥2 yol)
        _check(R, {"rfc2833", "sip_info"} <= {p.get("dtmf_mode") for p in profs},
               "config her iki DTMF modunu da kapsar (≥2 yol)")

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
def _rtp_digit(code, dur_samples, n_end=3, marker=True):
    """Tek bir mantıksal basamak için RFC 2833 paket dizisi üretir (start + ara + n_end End paketi)."""
    pk = [{"event": code, "marker": marker, "duration": dur_samples // 2, "e": False},
          {"event": code, "duration": dur_samples, "e": False}]
    pk += [{"event": code, "duration": dur_samples, "e": True} for _ in range(n_end)]
    return pk


def selftest():
    spec = _load(SPEC_PATH)
    cm = _code_map(spec)
    ds = _digit_set(spec)
    clock = spec["dtmf"]["rfc2833_clock_rate"]
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 1) validate iyi spec+config'te geçer
    case(_validate_obj(_load(SPEC_PATH)) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── kod/basamak eşlemesi (D3) ────────────────────────────────────────────────
    case(map_event_code(5, cm) == "5", "D3 kod 5 → '5'")
    case(map_event_code(10, cm) == "*", "D3 kod 10 → '*'")
    case(map_event_code(11, cm) == "#", "D3 kod 11 → '#'")
    case(map_event_code(15, cm) == "D", "D3 kod 15 → 'D'")
    case(_raises(lambda: map_event_code(16, cm)), "D3 kod 16 → reddedilir")
    case(canonical_digit("9", cm, ds) == "9", "D3 Signal '9' → '9'")
    case(canonical_digit("a", cm, ds) == "A", "D3 Signal 'a' → 'A'")
    case(canonical_digit("11", cm, ds) == "#", "D5 Signal '11' (kod) → '#'")
    case(_raises(lambda: canonical_digit("Z", cm, ds)), "D3 Signal 'Z' → reddedilir")

    # ── RFC 2833 debounce (D2/D4) ────────────────────────────────────────────────
    # 160ms @ 8000Hz = 1280 örnek; tek basamak '1' (5 paket) → tek mantıksal basamak
    pkts = _rtp_digit(1, 1280)
    digs = detect_rfc2833(pkts, clock, 40, cm)
    case(digs == [("1", 160.0)], "D2 '1' 5 paket → tek basamak (debounce)")
    # iki basamak '1' sonra '5' (her biri marker'lı)
    seq = _rtp_digit(1, 1280) + _rtp_digit(5, 1280)
    digs = detect_rfc2833(seq, clock, 40, cm)
    case([x[0] for x in digs] == ["1", "5"], "D2 '1','5' ayrı marker → iki basamak")
    # 6 redundant End paketi → yine tek basamak
    digs = detect_rfc2833(_rtp_digit(7, 1280, n_end=6), clock, 40, cm)
    case(digs == [("7", 160.0)], "D2 6 artık End paketi → yine tek basamak")
    # süre-altı (20ms=160 örnek < 40ms kapısı) → düşürülür (D4)
    digs = detect_rfc2833(_rtp_digit(2, 160), clock, 40, cm)
    case(digs == [], "D4 20ms olay → süre-altı düşürülür")
    # kayıp End-bit dayanıklılığı: marker değişimi önceki basamağı sonlandırır
    no_end = [{"event": 3, "marker": True, "duration": 1280, "e": False}] + _rtp_digit(4, 1280)
    digs = detect_rfc2833(no_end, clock, 40, cm)
    case([x[0] for x in digs] == ["3", "4"], "D2 End-bit'siz basamak olay-değişiminde sonlandırılır")

    # ── SIP INFO ayrıştırma (D5) ─────────────────────────────────────────────────
    r = detect_sip_info("application/dtmf-relay", "Signal=5\r\nDuration=160", 40, cm, ds)
    case(r is not None and r[0] == "5", "D5 dtmf-relay Signal=5 → '5'")
    r = detect_sip_info("application/dtmf-relay", "Signal=#\r\nDuration=120", 40, cm, ds)
    case(r is not None and r[0] == "#", "D5 dtmf-relay Signal=# → '#'")
    r = detect_sip_info("application/dtmf", "8", 40, cm, ds)
    case(r is not None and r[0] == "8", "D5 application/dtmf düz '8' → '8'")
    r = detect_sip_info("application/dtmf-relay", "Signal=4\r\nDuration=20", 40, cm, ds)
    case(r is None, "D4 SIP INFO 20ms süre-altı → düşürülür")
    case(_raises(lambda: detect_sip_info("application/sdp", "x", 40, cm, ds)),
         "D5 desteklenmeyen content-type → reddedilir")
    case(_raises(lambda: detect_sip_info("application/dtmf-relay", "Duration=160", 40, cm, ds)),
         "D5 Signal'sız dtmf-relay → reddedilir")

    # ── maskeleme (D8) ───────────────────────────────────────────────────────────
    sample_sens = {"sensitive": True, "events": [
        {"type": "rfc2833", "packets": _rtp_digit(4, 1280)},
        {"type": "rfc2833", "packets": _rtp_digit(2, 1280)},
    ], "expected_digits": "42"}
    detected, F = evaluate_detection(spec, sample_sens)
    case(all(d["masked"] and d["transcript_value"] == "•" for d in detected) and all(ok for ok, _ in F),
         "D8 hassas pencere: transkript maskeli, basamak (aksiyon) korunur")
    # aksiyon kanalı basamağı korur
    case("".join(d["digit"] for d in detected) == "42", "D8 aksiyon kanalı basamak değerini tutar")
    # normal pencere: maskeli değil
    sample_norm = dict(sample_sens); sample_norm["sensitive"] = False
    detected2, F2 = evaluate_detection(spec, sample_norm)
    case(all((not d["masked"]) and d["transcript_value"] == d["digit"] for d in detected2),
         "D8 normal pencere: basamak transkriptte görünür")

    # ── üretme (D7) ──────────────────────────────────────────────────────────────
    prof_2833 = {"name": "p1", "dtmf_mode": "rfc2833", "rfc2833_payload_type": 101,
                 "end_redundancy": 3, "inter_digit_gap_ms": 40, "region": "eu-west"}
    recs, Fg = generate_dtmf(spec, prof_2833, "19*")
    case(len(recs) == 3 and all(ok for ok, _ in Fg), "D7 rfc2833 '19*' → 3 kayıt geçer")
    case(recs[0]["marker_first"] and recs[0]["end_packets"] == 3, "D7 ilk basamak marker + 3 End paketi")
    case(recs[0]["gap_ms"] == 0 and recs[1]["gap_ms"] == 40, "D7 ilk boşluk 0, sonraki 40ms")
    prof_info = {"name": "p2", "dtmf_mode": "sip_info", "sip_info_content_type": "application/dtmf-relay",
                 "inter_digit_gap_ms": 50, "region": "eu-west"}
    recs, Fg = generate_dtmf(spec, prof_info, "0#")
    case(len(recs) == 2 and all(r["info_requests"] == 1 for r in recs) and all(ok for ok, _ in Fg),
         "D7 sip_info '0#' → 2 INFO isteği geçer")
    # geçersiz basamak gönderim öncesi reddedilir (D7)
    case(_raises(lambda: generate_dtmf(spec, prof_2833, "1X9")), "D7 geçersiz basamak 'X' gönderim öncesi reddi")
    # desteklenmeyen mod → reddedilir (UNAVAILABLE)
    bad_prof = {"name": "p3", "dtmf_mode": "inband", "region": "eu-west"}
    case(_raises(lambda: generate_dtmf(spec, bad_prof, "1")), "D7/D10 desteklenmeyen mod → reddedilir")
    # round-trip: üretilen basamaklar algılamayla geri okunur (rfc2833)
    rt_pkts = []
    to_code = _digit_to_code(cm)
    for ch in "159*":
        rt_pkts += _rtp_digit(to_code[ch], 1280)
    rt = detect_rfc2833(rt_pkts, clock, 40, cm)
    case("".join(x[0] for x in rt) == "159*", "D2/D7 round-trip üret→algıla '159*' tutarlı")

    # ── validate negatif kapılar ─────────────────────────────────────────────────
    s = json.loads(json.dumps(spec)); s["dtmf"]["inband_detection"] = True
    case(_validate_obj(s) != 0, "D1 in-band açık → validate eler")
    s = json.loads(json.dumps(spec)); s["dtmf"]["event_code_map"]["10"] = "X"
    case(_validate_obj(s) != 0, "D3 bozuk kod eşlemesi → validate eler")
    s = json.loads(json.dumps(spec)); s["masking"]["digit_value_to"] = "everywhere"
    case(_validate_obj(s) != 0, "D8 maskeleme bozuk → validate eler")
    s = json.loads(json.dumps(spec)); s["error_taxonomy"]["mapping"]["x"] = "NOPE"
    case(_validate_obj(s) != 0, "D10 taksonomi-dışı → validate eler")
    s = json.loads(json.dumps(spec)); s["detection"]["min_duration_ms"] = 0
    case(_validate_obj(s) != 0, "D4 min_duration_ms=0 → validate eler")
    s = json.loads(json.dumps(spec)); s["pii"]["card_data_in_spec_forbidden"] = False
    case(_validate_obj(s) != 0, "D12 kart-verisi-yasak kapalı → validate eler")
    s = json.loads(json.dumps(spec)); s["dtmf"]["secret"] = "api_key: AKIAIOSFODNN7EXAMPLE"
    case(_validate_obj(s) != 0, "D12 literal secret → validate eler")

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
    except DtmfError:
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
    print("""dtmf-spec.json beklenen şekli (WBS 2.1.6):
  wbs, version, phase, trace{fr,nfr,sad,adr,api,srs,rtm,brd,threat_model,rfc}
  dtmf{modes[rfc2833,sip_info], inband_detection=false, rfc2833_clock_rate,
       rfc2833_default_payload_type, digit_set='0123456789*#ABCD',
       event_code_map{0..15→basamak}}                                      (D1,D3,D6)
  detection{rfc2833_debounce=true, finalize_on_end_bit/event_change=true,
            min_duration_ms>0, sip_info_content_types[]}                   (D2,D4,D5)
  generation{default_tone_duration_ms, inter_digit_gap_ms, end_redundancy≥1,
             validate_before_send=true}                                    (D7)
  normalized_dtmf_event{fields[], mask_token, feeds[]}                      (D6)
  masking{sensitive_window_supported=true, mask_in[transcript,recording,...],
          digit_value_to='action_channel_only', cp_key}                    (D8)
  turn_integration{can_trigger_barge_in=true, barge_in_deadline_ms=200}     (D9)
  error_taxonomy{mapping→API §11.6}                                        (D10)
  residency{region_pin_required=true}                                       (D11)
  pii{raw_payload_in_spec_forbidden, card_data_in_spec_forbidden}           (D12)
  invariants[≥12]{id, desc, trace}

config/dtmf-modes.json: default_min_duration_ms, mask_token,
  profiles[]{name, integration_mode, dtmf_mode, rfc2833_payload_type?/sip_info_content_type?,
             tone_duration_ms, inter_digit_gap_ms, end_redundancy?, region}

detect sample:   {name, sensitive?, expected_digits, expect, events[]{type:rfc2833{packets[]} | sip_info{content_type,body}}}
generate sample: {name, profile | profile_obj, digits, expect}

komutlar: validate | detect <sample.json> | generate <sample.json> | selftest | schema""")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "detect":
        if len(sys.argv) < 3:
            print("kullanım: dtmf_probe.py detect <sample.json>")
            return 2
        return detect_cmd(sys.argv[2])
    if cmd == "generate":
        if len(sys.argv) < 3:
            print("kullanım: dtmf_probe.py generate <sample.json>")
            return 2
        return generate_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|detect|generate|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
