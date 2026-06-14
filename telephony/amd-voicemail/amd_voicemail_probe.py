#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
amd_voicemail_probe.py — WBS 2.1.9 Answering machine detection (AMD) + voicemail bırakma

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only, DETERMİNİSTİK statik + karar kapısı.
telephony/{managed-cpaas,byoc-sip,numbering,dtmf,reason-codes,retry-callback} + db/ probe
disipliniyle aynı.

ALGILAMA + AKSİYON DÜZLEMİ (çağrı karşılandıktan sonra "kim/ne cevapladı + ne yapmalı"; medya
kodek/RTP düzlemi DEĞİL):
  • AMD:        signals (CPaaS AMD ipucu ∨ medya heuristiği: greeting/beep/silence) → deterministik
                amd_class ∈ {human, machine, unknown} + güven (FR-TEL-010).
  • Karar:      human → proceed_human (SAD §6.1 turuna devret); machine → attempt_voicemail (politika
                açıksa) / detect_only; unknown → treat_as_human (insan-güvenli, A3).
  • Voicemail:  machine + policy.enabled + uyum (consent/DNC/ifşa) + bip → kontrollü drop → voicemail_left
                (billable). Aksi → voicemail_machine_detected (retryable → 2.1.8) (FR-TEL-011).
  • Köprü:      2.1.7 voicemail_machine_detected / voicemail_left kanonik kodlarını ÜRETİR; 2.1.8 tüketir.

Komutlar:
  validate            amd-voicemail-spec.json'ı invariant'lara (A1..A14) + config profillerine +
                      2.1.7 taksonomi çapraz-tutarlılığına karşı doğrular (çıkış kodu).
  classify <sample>   Deterministik AMD sınıflandırıcı — signals → amd_class + güven + karar;
                      opsiyonel `expect` ile doğrular (çıkış kodu).
  drop <sample>       Voicemail bırakma dizisi — machine + politika + uyum + bip → outcome + reason_code;
                      opsiyonel `expect`. Uyum/bip kapıları → çıkış kodu.
  accuracy <dataset>  Etiketli (human/machine) küme üzerinde doğruluk + false_machine_rate ölçer ve
                      accuracy_gate'e (SR-TEL-010 T) göre kapı uygular → çıkış kodu.
  selftest            İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema              Beklenen spec/sample şeklini özetler.

Sunucu/credential GEREKMEZ. Sınıflandırma gerçek DSP yerine deterministik öznitelik skorudur
(numbering select / reason-codes classify / retry-callback decide deseni). now sanal saattir.
Numara/transkript/ham-audio koda/karara gömülmez (A11).
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "amd-voicemail-spec.json")
PROFILE_CFG = os.path.join(HERE, "config", "amd-profiles.json")
# 2.1.7 taksonomisi — voicemail kodlarının kaynak doğruluğu (çapraz-tutarlılık A7)
REASON_SPEC = os.path.join(HERE, "..", "reason-codes", "reason-codes-spec.json")

SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def _reason_taxonomy():
    """2.1.7 end_reasons.codes → {code: {retryable,billable}}. Yoksa None (validate not düşer)."""
    if not os.path.exists(REASON_SPEC):
        return None
    spec = _load(REASON_SPEC)
    codes = spec.get("end_reasons", {}).get("codes", {})
    return {k: {"retryable": bool(v.get("retryable", False)),
                "billable": bool(v.get("billable", False))} for k, v in codes.items()}


class DecisionError(Exception):
    """Geçersiz istek / taksonomi uyuşmazlığı — sessiz kabul yok."""


def _parse_iso(s):
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _resolve_profile(spec, sample):
    """policy_ref: config profili adı VEYA inline profil nesnesi."""
    ref = sample.get("policy_ref")
    if isinstance(ref, dict):
        return ref
    if os.path.exists(PROFILE_CFG):
        cfg = _load(PROFILE_CFG)
        for p in cfg.get("profiles", []):
            if p.get("name") == ref:
                return p
    raise DecisionError("profil bulunamadı: %r" % ref)


# ─────────────────────────────────────────────────────────────────────────────
# Çekirdek: deterministik AMD sınıflandırıcı (FR-TEL-010)
# ─────────────────────────────────────────────────────────────────────────────
def _ramp(x, lo, hi):
    """x≤lo → 0, x≥hi → 1, arası lineer. (lo<hi varsayılır.)"""
    if x >= hi:
        return 1.0
    if x <= lo:
        return 0.0
    return (x - lo) / (hi - lo)


def _p_machine(sig, amd, weights):
    """Deterministik makine olasılığı p ∈ [0,1]. Ağırlıklar toplamı 1.0 → p sınırlı.
    bip (en güçlü), uzun karşılama (monolog), karşılama sonrası kısa sessizlik (duraklamadan sürdürür)."""
    p = 0.0
    if sig.get("beep_detected") is True:
        p += float(weights["beep"])
    g = float(sig.get("greeting_duration_ms", 0))
    p += float(weights["greeting"]) * _ramp(g, float(amd["human_greeting_ms"]), float(amd["machine_greeting_ms"]))
    s = float(sig.get("silence_after_greeting_ms", amd["human_wait_ms"]))
    # sessizlik kısa → makine (ramp_inv): short_silence_ms'te 1, human_wait_ms'te 0
    p += float(weights["silence"]) * (1.0 - _ramp(s, float(amd["short_silence_ms"]), float(amd["human_wait_ms"])))
    return min(1.0, p)


def classify(spec, sample):
    """signals → AMD kararı. Saf/deterministik."""
    prof = _resolve_profile(spec, sample)
    amd = prof.get("amd", {})
    vm = prof.get("voicemail", {})
    weights = spec.get("amd_model", {}).get("feature_weights", {})
    minc = float(amd["min_confidence"])
    sig = sample.get("signals", {})

    hint = sig.get("cpaas_amd")
    hc = sig.get("cpaas_amd_confidence")
    # CPaaS yolu: ipucu human/machine + güveni eşiği geçerse doğrudan kullan
    if hint in ("human", "machine") and isinstance(hc, (int, float)) and float(hc) >= minc:
        cls = hint
        conf = float(hc)
        source = "cpaas_amd"
    else:
        p = _p_machine(sig, amd, weights)
        source = "media_heuristic"
        if p >= minc:
            cls, conf = "machine", p
        elif (1.0 - p) >= minc:
            cls, conf = "human", 1.0 - p
        else:
            cls, conf = "unknown", max(p, 1.0 - p)

    unknown_fallback = (cls == "unknown")
    resolved = "machine" if cls == "machine" else "human"  # unknown → human (A3)

    if cls == "human" or cls == "unknown":
        decision = "proceed_human"
    else:  # machine
        decision = "attempt_voicemail" if vm.get("enabled") is True else "detect_only"

    return {
        "amd_class": cls,
        "confidence": round(conf, 4),
        "signal_source": source,
        "amd_decision": decision,
        "resolved_party": resolved,
        "unknown_fallback_applied": unknown_fallback,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Çekirdek: voicemail bırakma dizisi (FR-TEL-011)
# ─────────────────────────────────────────────────────────────────────────────
def drop(spec, sample, taxonomy=None):
    """machine algılandığında kontrollü voicemail bırakma. Saf/deterministik."""
    prof = _resolve_profile(spec, sample)
    vm = prof.get("voicemail", {})
    sig = sample.get("signals", {})
    message = sample.get("message", {})
    contact = sample.get("contact", {})

    c = classify(spec, sample)
    rmap = spec.get("reason_code_map", {})

    def _result(outcome, reason_code, left=False, await_ms=0, after_beep=False, mref=None):
        billable = bool(taxonomy[reason_code]["billable"]) if (taxonomy and reason_code in taxonomy) else (reason_code == "voicemail_left")
        return {
            "amd_class": c["amd_class"],
            "voicemail_outcome": outcome,
            "reason_code": reason_code,
            "message_ref": mref if left else None,
            "await_beep_ms": await_ms,
            "message_started_after_beep": after_beep,
            "billable": billable,
        }

    # machine değilse voicemail söz konusu değil — insan yoluna devret (A12)
    if c["amd_class"] != "machine":
        raise DecisionError("drop yalnız amd_class==machine içindir; got=%s (insan yolu SAD §6.1)" % c["amd_class"])

    # ── Uyum/bip kapıları (bırakmadan ÖNCE; sıra G1→G5; A13 açık sonuç) ─────────
    machine_not_left = rmap.get("machine_not_left", "voicemail_machine_detected")
    # G1 policy off → detect-only
    if vm.get("enabled") is not True:
        return _result("not_left_policy_off", machine_not_left)
    # G2 consent (A6) — rıza dışı voicemail bırakılmaz
    if contact.get("consent_state", "none") != "granted":
        return _result("not_left_compliance", machine_not_left)
    # G3 DNC (A6)
    if contact.get("do_not_call") is True:
        return _result("not_left_compliance", machine_not_left)
    # G4 ifşa (A5) — AI ifşası zorunluysa mesajda olmalı
    if vm.get("require_disclosure") is True and message.get("disclosure_included") is not True:
        return _result("not_left_compliance", machine_not_left)
    # G5 bip (A4) — beep_required ise yalnız bip sonrası konuş
    max_wait = int(vm["max_beep_wait_ms"])
    beep = sig.get("beep_detected") is True
    beep_at = sig.get("beep_at_ms")
    beep_within = beep and isinstance(beep_at, (int, float)) and int(beep_at) <= max_wait
    if vm.get("beep_required") is True and not beep_within:
        return _result("not_left_no_beep", machine_not_left, await_ms=max_wait)

    # ── Bırak: mesaj yalnız bip sonrası başlar (A4) ────────────────────────────
    await_ms = int(beep_at) if beep_within else max_wait
    left_code = rmap.get("voicemail_left", "voicemail_left")
    return _result("left", left_code, left=True, await_ms=await_ms, after_beep=True,
                   mref=message.get("message_ref"))


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _scan_secrets(obj):
    hits = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            if _is_placeholder(o):
                return
            for line in o.splitlines():
                s = line.strip()
                if s.startswith("#") or s.startswith("//"):
                    continue
                if SECRET_RE.search(line):
                    hits.append(o[:60])

    walk(obj)
    return hits


def _validate_obj(spec):
    R = []

    def _check(ok, label):
        R.append((bool(ok), label))

    enums = spec.get("enums", {})
    AC = set(enums.get("amd_class", []))
    AD = set(enums.get("amd_decision", []))
    VO = set(enums.get("voicemail_outcome", []))
    SS = set(enums.get("signal_source", []))
    _check(spec.get("policy_version"), "policy_version mevcut")
    _check(AC == {"human", "machine", "unknown"}, "A1 enums.amd_class kapalı küme")
    _check(AD == {"proceed_human", "attempt_voicemail", "detect_only"}, "enums.amd_decision kapalı küme")
    _check(VO == {"left", "not_left_no_beep", "not_left_policy_off", "not_left_compliance"},
           "A13 enums.voicemail_outcome kapalı küme")
    _check(SS == {"cpaas_amd", "media_heuristic"}, "enums.signal_source kapalı küme")

    # ── amd_model: ağırlıklar toplamı 1.0 (p ∈ [0,1]) + unknown_fallback sabit
    am = spec.get("amd_model", {})
    w = am.get("feature_weights", {})
    wsum = sum(float(w.get(k, 0)) for k in ("beep", "greeting", "silence"))
    _check(abs(wsum - 1.0) < 1e-9, "A2 feature_weights toplamı 1.0 (p_machine ∈ [0,1]) — %.3f" % wsum)
    _check(am.get("fields", {}).get("unknown_fallback") == "treat_as_human",
           "A3 unknown_fallback = treat_as_human (insan-güvenli)")

    # ── voicemail_model alanları + reason_code_map
    rmap = spec.get("reason_code_map", {})
    _check(rmap.get("machine_not_left") == "voicemail_machine_detected",
           "A7 machine_not_left → voicemail_machine_detected")
    _check(rmap.get("voicemail_left") == "voicemail_left", "A7 voicemail_left → voicemail_left")

    # ── 2.1.7 çapraz-tutarlılık (A7): kodlar var + retryable/billable beklenen
    taxonomy = _reason_taxonomy()
    if taxonomy is None:
        _check(True, "NOT: 2.1.7 taksonomi bulunamadı — A7 çapraz-doğrulama atlandı")
    else:
        mnl = rmap.get("machine_not_left")
        vl = rmap.get("voicemail_left")
        _check(mnl in taxonomy and taxonomy[mnl]["retryable"] is True and taxonomy[mnl]["billable"] is False,
               "A7 voicemail_machine_detected 2.1.7'de retryable=true + billable=false")
        _check(vl in taxonomy and taxonomy[vl]["retryable"] is False and taxonomy[vl]["billable"] is True,
               "A7 voicemail_left 2.1.7'de retryable=false + billable=true")

    # ── compliance_gates: G1..G5 + doğru outcome
    gates = {g.get("id"): g for g in spec.get("compliance_gates", {}).get("gates", [])}
    _check({"G1", "G2", "G3", "G4", "G5"} <= set(gates.keys()), "compliance_gates G1..G5 tanımlı")
    _check(gates.get("G1", {}).get("outcome") == "not_left_policy_off", "G1 policy off → not_left_policy_off")
    _check(gates.get("G2", {}).get("outcome") == "not_left_compliance", "A6 G2 consent → not_left_compliance")
    _check(gates.get("G3", {}).get("outcome") == "not_left_compliance", "A6 G3 DNC → not_left_compliance")
    _check(gates.get("G4", {}).get("outcome") == "not_left_compliance", "A5 G4 ifşa → not_left_compliance")
    _check(gates.get("G5", {}).get("outcome") == "not_left_no_beep", "A4 G5 bip → not_left_no_beep")
    used_outcomes = {g.get("outcome") for g in gates.values()} | {"left"}
    _check(used_outcomes <= VO, "kullanılan outcome'lar enum içinde (%s)" % (sorted(used_outcomes - VO)[:3] or "—"))

    # ── accuracy_gate (A9)
    ag = spec.get("accuracy_gate", {})
    _check(isinstance(ag.get("min_accuracy"), (int, float)) and 0 < ag["min_accuracy"] <= 1,
           "A9 accuracy_gate.min_accuracy ∈ (0,1]")
    _check(isinstance(ag.get("max_false_machine_rate"), (int, float)) and 0 <= ag["max_false_machine_rate"] < 1,
           "A9 accuracy_gate.max_false_machine_rate ∈ [0,1)")
    _check(isinstance(ag.get("min_items"), int) and ag["min_items"] >= 1, "A9 accuracy_gate.min_items ≥1")

    # ── residency + pii + literal sır (A11/A14)
    _check(spec.get("residency", {}).get("region_pin_required") is True, "A11 residency region pin")
    pii = spec.get("pii", {})
    _check(pii.get("decision_pii_class") == "none"
           and pii.get("phone_number_in_decision_forbidden") is True
           and pii.get("raw_audio_in_decision_forbidden") is True,
           "A11 karar PII içermez (pii_class=none, ham audio yok)")

    # ── invariant kataloğu
    inv = spec.get("invariants", [])
    inv_ids = [i.get("id") for i in inv]
    _check(len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 14, "invariant kataloğu ≥14 + tekil ID")
    _check(all(i.get("trace") for i in inv), "her invariant trace taşır")

    # ── config profilleri (A2/A4/A10/A14)
    hits = _scan_secrets(spec)
    if os.path.exists(PROFILE_CFG):
        cfg = _load(PROFILE_CFG)
        hits += _scan_secrets(cfg)
        profs = cfg.get("profiles", [])
        _check(len(profs) >= 2, "A14 config ≥2 profil")
        names = [p.get("name") for p in profs]
        _check(len(names) == len(set(names)), "config profil isimleri tekil")
        has_detect_only = any(p.get("voicemail", {}).get("enabled") is False for p in profs)
        has_drop = any(p.get("voicemail", {}).get("enabled") is True for p in profs)
        _check(has_detect_only and has_drop, "A14 en az 1 detect-only + 1 drop-enabled profil")
        for p in profs:
            nm = p.get("name")
            amd = p.get("amd", {})
            vm = p.get("voicemail", {})
            mc = amd.get("min_confidence")
            _check(isinstance(mc, (int, float)) and 0 < mc < 1, "A2 %s min_confidence ∈ (0,1)" % nm)
            _check(amd.get("human_greeting_ms", 0) < amd.get("machine_greeting_ms", -1),
                   "A14 %s human_greeting < machine_greeting" % nm)
            _check(0 < amd.get("short_silence_ms", -1) < amd.get("human_wait_ms", -1),
                   "A14 %s short_silence < human_wait (pozitif)" % nm)
            _check(isinstance(vm.get("max_beep_wait_ms"), int) and vm["max_beep_wait_ms"] > 0,
                   "A10 %s max_beep_wait_ms >0 sonlu" % nm)
            _check(isinstance(vm.get("max_message_seconds"), int) and vm["max_message_seconds"] > 0,
                   "A10 %s max_message_seconds >0 sonlu" % nm)
            _check(isinstance(vm.get("enabled"), bool) and isinstance(vm.get("beep_required"), bool)
                   and isinstance(vm.get("require_disclosure"), bool),
                   "%s voicemail bayrakları bool" % nm)
    _check(not hits, "A14 literal sır yok (spec+config)")

    passed = sum(1 for ok, _ in R if ok)
    total = len(R)
    for ok, label in R:
        if not ok:
            print("  ✗ %s" % label)
    print("validate: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


def cmd_validate():
    return _validate_obj(_load(SPEC_PATH))


# ─────────────────────────────────────────────────────────────────────────────
# classify <sample>
# ─────────────────────────────────────────────────────────────────────────────
def cmd_classify(sample_path):
    spec = _load(SPEC_PATH)
    sample = _load(sample_path)
    try:
        res = classify(spec, sample)
    except DecisionError as e:
        if sample.get("allow_error"):
            print("classify: beklenen hata → %s" % e)
            print("classify: PASS ✅")
            return 0
        print("classify: HATA → %s" % e)
        print("classify: FAIL ❌")
        return 1

    print("amd_class=%s (güven=%.3f, kaynak=%s) → karar=%s (resolved=%s, fallback=%s)" % (
        res["amd_class"], res["confidence"], res["signal_source"],
        res["amd_decision"], res["resolved_party"], res["unknown_fallback_applied"]))

    gate_ok = True
    exp = sample.get("expect", {})
    for field in ("amd_class", "amd_decision", "signal_source", "resolved_party", "unknown_fallback_applied"):
        if field in exp and res.get(field) != exp[field]:
            print("  ✗ expect.%s=%r ama got=%r" % (field, exp[field], res.get(field)))
            gate_ok = False
    if "min_confidence" in exp and res["confidence"] < exp["min_confidence"]:
        print("  ✗ güven %.3f < beklenen %.3f" % (res["confidence"], exp["min_confidence"]))
        gate_ok = False
    print("classify: %s" % ("PASS ✅" if gate_ok else "FAIL ❌"))
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# drop <sample>
# ─────────────────────────────────────────────────────────────────────────────
def cmd_drop(sample_path):
    spec = _load(SPEC_PATH)
    taxonomy = _reason_taxonomy()
    sample = _load(sample_path)
    try:
        res = drop(spec, sample, taxonomy)
    except DecisionError as e:
        if sample.get("allow_error"):
            print("drop: beklenen hata → %s" % e)
            print("drop: PASS ✅")
            return 0
        print("drop: HATA → %s" % e)
        print("drop: FAIL ❌")
        return 1

    print("amd=%s → outcome=%s [%s] billable=%s" % (
        res["amd_class"], res["voicemail_outcome"], res["reason_code"], res["billable"]))
    if res["voicemail_outcome"] == "left":
        print("  message_ref=%s await_beep_ms=%s after_beep=%s" % (
            res["message_ref"], res["await_beep_ms"], res["message_started_after_beep"]))

    gate_ok = True
    exp = sample.get("expect", {})
    for field in ("voicemail_outcome", "reason_code", "billable", "message_started_after_beep"):
        if field in exp and res.get(field) != exp[field]:
            print("  ✗ expect.%s=%r ama got=%r" % (field, exp[field], res.get(field)))
            gate_ok = False
    print("drop: %s" % ("PASS ✅" if gate_ok else "FAIL ❌"))
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# accuracy <dataset> — SR-TEL-010 (T) kapısı
# ─────────────────────────────────────────────────────────────────────────────
def cmd_accuracy(dataset_path):
    spec = _load(SPEC_PATH)
    ds = _load(dataset_path)
    gate = spec.get("accuracy_gate", {})
    min_acc = float(gate.get("min_accuracy", 0.9))
    max_fmr = float(gate.get("max_false_machine_rate", 0.05))
    min_items = int(gate.get("min_items", 1))
    policy_ref = ds.get("policy_ref", "campaign-voicemail")

    items = ds.get("items", [])
    n = len(items)
    correct = 0
    human_n = 0
    false_machine = 0  # gerçek insan → makine sınıflandı (tehlikeli hata)
    unknown_n = 0
    for it in items:
        label = it["label"]  # human | machine (ground truth)
        s = {"now": "2026-06-15T12:00:00Z", "tenant_id": "t1",
             "policy_ref": ds.get("policy_ref", policy_ref), "signals": it["signals"]}
        res = classify(spec, s)
        resolved = res["resolved_party"]  # unknown → human (A3)
        if res["amd_class"] == "unknown":
            unknown_n += 1
        if resolved == label:
            correct += 1
        if label == "human":
            human_n += 1
            if resolved == "machine":
                false_machine += 1

    accuracy = correct / n if n else 0.0
    fmr = (false_machine / human_n) if human_n else 0.0

    print("accuracy: profil=%s, n=%d (unknown=%d)" % (policy_ref, n, unknown_n))
    print("  doğruluk=%.3f (eşik ≥%.2f) · false_machine_rate=%.3f (eşik ≤%.2f, insan n=%d)" % (
        accuracy, min_acc, fmr, max_fmr, human_n))

    g_items = n >= min_items
    g_acc = accuracy >= min_acc
    g_fmr = fmr <= max_fmr
    if not g_items:
        print("  ✗ küme çok küçük (n=%d < min_items=%d)" % (n, min_items))
    if not g_acc:
        print("  ✗ doğruluk eşiğin altında")
    if not g_fmr:
        print("  ✗ false_machine_rate eşiğin üstünde (insanı makine sanma riski)")
    gate_ok = g_items and g_acc and g_fmr
    print("accuracy: %s (SR-TEL-010 T)" % ("PASS ✅" if gate_ok else "FAIL ❌"))
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def _sig(**kw):
    s = {"cpaas_amd": None, "cpaas_amd_confidence": None, "greeting_duration_ms": 1000,
         "beep_detected": False, "beep_at_ms": None, "silence_after_greeting_ms": 1500}
    s.update(kw)
    return s


def _csample(policy_ref="campaign-voicemail", **sigkw):
    return {"now": "2026-06-15T12:00:00Z", "tenant_id": "t1", "policy_ref": policy_ref,
            "signals": _sig(**sigkw)}


def selftest():
    spec = _load(SPEC_PATH)
    taxonomy = _reason_taxonomy()
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 1) validate iyi spec+config'te geçer
    case(_validate_obj(spec) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── insan: kısa karşılama, bip yok, dinlemek için duraklar → human/proceed (A1/A2)
    r = classify(spec, _csample(greeting_duration_ms=900, silence_after_greeting_ms=1500))
    case(r["amd_class"] == "human" and r["amd_decision"] == "proceed_human", "insan kısa karşılama → human/proceed")
    case(r["signal_source"] == "media_heuristic", "heuristik kaynak (CPaaS ipucu yok)")

    # ── makine heuristik: uzun karşılama + bip + kısa sessizlik → machine/attempt_voicemail
    r = classify(spec, _csample(greeting_duration_ms=4000, beep_detected=True, beep_at_ms=4200,
                                silence_after_greeting_ms=200))
    case(r["amd_class"] == "machine" and r["amd_decision"] == "attempt_voicemail",
         "makine heuristik → machine/attempt_voicemail")
    case(r["confidence"] >= 0.80, "makine güveni ≥ min_confidence")

    # ── makine CPaaS ipucu (yüksek güven) → machine, kaynak cpaas_amd
    r = classify(spec, _csample(cpaas_amd="machine", cpaas_amd_confidence=0.95,
                                greeting_duration_ms=1000))
    case(r["amd_class"] == "machine" and r["signal_source"] == "cpaas_amd", "CPaaS ipucu → machine (cpaas kaynak)")
    # ipucu düşük güven → heuristiğe düşer
    r = classify(spec, _csample(cpaas_amd="machine", cpaas_amd_confidence=0.40,
                                greeting_duration_ms=1000, silence_after_greeting_ms=1500))
    case(r["signal_source"] == "media_heuristic", "düşük-güven CPaaS ipucu → heuristiğe düşer")

    # ── belirsiz: orta karşılama, bip yok, orta sessizlik → unknown → treat_as_human (A3)
    r = classify(spec, _csample(greeting_duration_ms=2500, silence_after_greeting_ms=700))
    case(r["amd_class"] == "unknown", "orta sinyaller → unknown")
    case(r["resolved_party"] == "human" and r["amd_decision"] == "proceed_human" and r["unknown_fallback_applied"],
         "A3 unknown → treat_as_human (voicemail bırakılmaz)")

    # ── A8 determinizm: aynı signals → aynı sonuç
    a = classify(spec, _csample(greeting_duration_ms=4000, beep_detected=True, beep_at_ms=4200))
    b = classify(spec, _csample(greeting_duration_ms=4000, beep_detected=True, beep_at_ms=4200))
    case(a == b, "A8 aynı signals → aynı sınıf/güven (deterministik)")

    # ── detect-only profil: makine ama bırakma kapalı → detect_only
    r = classify(spec, _csample(policy_ref="detect-only", greeting_duration_ms=4000,
                                beep_detected=True, beep_at_ms=4200, silence_after_greeting_ms=200))
    case(r["amd_class"] == "machine" and r["amd_decision"] == "detect_only",
         "detect-only profil → machine/detect_only")

    # ── drop: makine + bip + consent + ifşa → left / voicemail_left (A4/A7)
    dsample = {"now": "2026-06-15T12:00:00Z", "tenant_id": "t1", "policy_ref": "campaign-voicemail",
               "signals": _sig(greeting_duration_ms=4000, beep_detected=True, beep_at_ms=4200,
                               silence_after_greeting_ms=200),
               "message": {"message_ref": "tts:vm-tpl-001", "disclosure_included": True},
               "contact": {"contact_id": "c1", "consent_state": "granted", "do_not_call": False}}
    r = drop(spec, dsample, taxonomy)
    case(r["voicemail_outcome"] == "left" and r["reason_code"] == "voicemail_left",
         "A7 makine+bip+uyum → left / voicemail_left")
    case(r["billable"] is True and r["message_started_after_beep"] is True,
         "A4/A7 voicemail_left billable + mesaj bip sonrası")

    # ── drop: ifşa yok → not_left_compliance (A5)
    d2 = json.loads(json.dumps(dsample))
    d2["message"]["disclosure_included"] = False
    r = drop(spec, d2, taxonomy)
    case(r["voicemail_outcome"] == "not_left_compliance" and r["reason_code"] == "voicemail_machine_detected",
         "A5 ifşa yok → not_left_compliance / voicemail_machine_detected")

    # ── drop: consent withdrawn → not_left_compliance (A6)
    d3 = json.loads(json.dumps(dsample))
    d3["contact"]["consent_state"] = "withdrawn"
    case(drop(spec, d3, taxonomy)["voicemail_outcome"] == "not_left_compliance", "A6 consent → not_left_compliance")
    d4 = json.loads(json.dumps(dsample))
    d4["contact"]["do_not_call"] = True
    case(drop(spec, d4, taxonomy)["voicemail_outcome"] == "not_left_compliance", "A6 DNC → not_left_compliance")

    # ── drop: makine algılandı (CPaaS ipucu) ama bip yok (beep_required) → not_left_no_beep (A4)
    # Not: bip heuristikte güçlü makine işareti olduğundan, bipsiz makine tespiti CPaaS ipucuna dayanır
    # (gerçekte: greeting analizi bip ÖNCESİ makine der; bip ayrı/sonraki olaydır).
    d5 = json.loads(json.dumps(dsample))
    d5["signals"]["cpaas_amd"] = "machine"
    d5["signals"]["cpaas_amd_confidence"] = 0.95
    d5["signals"]["beep_detected"] = False
    d5["signals"]["beep_at_ms"] = None
    r = drop(spec, d5, taxonomy)
    case(r["voicemail_outcome"] == "not_left_no_beep" and r["reason_code"] == "voicemail_machine_detected",
         "A4 bip yok → not_left_no_beep / voicemail_machine_detected")
    case(r["billable"] is False, "A7 bırakılmadı → billable=false")

    # ── drop: detect-only profil (enabled=false) → not_left_policy_off
    d6 = json.loads(json.dumps(dsample))
    d6["policy_ref"] = "detect-only"
    case(drop(spec, d6, taxonomy)["voicemail_outcome"] == "not_left_policy_off", "G1 policy off → not_left_policy_off")

    # ── drop: insan → hata (A12 insan yolu)
    case(_raises(lambda: drop(spec, _csample(greeting_duration_ms=900, silence_after_greeting_ms=1500), taxonomy)),
         "A12 insan classify → drop hata (insan yolu, voicemail yok)")

    # ── A2 over-claim koruması: tek zayıf sinyal makine'ye yetmez
    r = classify(spec, _csample(beep_detected=True, greeting_duration_ms=1000, silence_after_greeting_ms=1500))
    case(r["amd_class"] != "machine", "A2 tek bip (0.45<0.80) tek başına machine değil")

    # ── negatif kapı kanıtı: bozuk spec validate'i elemeli ─────────────────────
    bad = json.loads(json.dumps(spec))
    bad["amd_model"]["feature_weights"]["beep"] = 0.90  # toplam ≠ 1.0
    case(_validate_obj(bad) == 1, "negatif: ağırlık toplamı ≠1.0 → eler (A2)")

    bad = json.loads(json.dumps(spec))
    bad["amd_model"]["fields"]["unknown_fallback"] = "treat_as_machine"  # A3 ihlali
    case(_validate_obj(bad) == 1, "negatif: unknown_fallback insan-güvenli değil → eler (A3)")

    bad = json.loads(json.dumps(spec))
    bad["reason_code_map"]["voicemail_left"] = "voicemail_machine_detected"  # A7 yanlış eşleme
    case(_validate_obj(bad) == 1, "negatif: voicemail_left yanlış eşleme → eler (A7)")

    bad = json.loads(json.dumps(spec))
    bad["pii"]["raw_audio_in_decision_forbidden"] = False  # A11
    case(_validate_obj(bad) == 1, "negatif: ham audio koruması kapalı → eler (A11)")

    bad = json.loads(json.dumps(spec))
    bad["compliance_gates"]["gates"][1]["outcome"] = "left"  # A6 consent → left olamaz
    case(_validate_obj(bad) == 1, "negatif: G2 consent outcome=left → eler (A6)")

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
    except Exception:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# schema
# ─────────────────────────────────────────────────────────────────────────────
def schema():
    print(__doc__)
    print("Beklenen spec şekli (amd-voicemail-spec.json):")
    print("  policy_version            : str")
    print("  enums                     : amd_class/amd_decision/voicemail_outcome/signal_source (kapalı küme)")
    print("  detection_contract        : classify request/response")
    print("  drop_contract             : voicemail bırakma request/response")
    print("  amd_model                 : feature_weights (toplam 1.0) + eşikler + unknown_fallback")
    print("  voicemail_model           : enabled/beep_required/max_beep_wait_ms/max_message_seconds/disclosure")
    print("  compliance_gates.gates    : G1 policy · G2 consent · G3 DNC · G4 ifşa · G5 bip")
    print("  reason_code_map           : machine_not_left/voicemail_left → 2.1.7 kodları (A7)")
    print("  accuracy_gate             : min_accuracy + max_false_machine_rate (SR-TEL-010 T)")
    print("  residency / pii           : region pin + karar PII içermez (A11)")
    print("  invariants[]              : A1..A14")
    print("classify sample şekli:")
    print("  {now, tenant_id, policy_ref, signals:{cpaas_amd,cpaas_amd_confidence,greeting_duration_ms,")
    print("   beep_detected,beep_at_ms,silence_after_greeting_ms}, [expect:{...}]}")
    print("drop sample şekli: classify + {message:{message_ref,disclosure_included},")
    print("   contact:{contact_id,consent_state,do_not_call}, [expect:{...}]}")
    print("accuracy dataset şekli: {policy_ref, items:[{label:human|machine, signals:{...}}, ...]}")
    return 0


def main(argv):
    if len(argv) < 2:
        print("kullanım: amd_voicemail_probe.py {validate|classify <s>|drop <s>|accuracy <ds>|selftest|schema}")
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return cmd_validate()
    if cmd == "classify":
        if len(argv) < 3:
            print("classify: <sample.json> gerekli")
            return 2
        return cmd_classify(argv[2])
    if cmd == "drop":
        if len(argv) < 3:
            print("drop: <sample.json> gerekli")
            return 2
        return cmd_drop(argv[2])
    if cmd == "accuracy":
        if len(argv) < 3:
            print("accuracy: <dataset.json> gerekli")
            return 2
        return cmd_accuracy(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
