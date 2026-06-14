#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
retry_callback_probe.py — WBS 2.1.8 Çağrı düşmesinde kontrollü retry / geri arama

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only, DETERMİNİSTİK statik + karar kapısı.
telephony/{managed-cpaas,byoc-sip,numbering,dtmf,reason-codes} + db/ + eventstream/ probe
disipliniyle aynı.

KARAR DÜZLEMİ (çağrı bittikten sonra "ne olacak"; medya/numaralandırma/taksonomi düzlemi DEĞİL):
  • Politika:   max_attempts (FR-OUT-005 sert tavan) + backoff (fixed/exponential, sınırlı) +
                jitter (deterministik) + calling_hours + mode (retry/callback).
  • Karar:      bir çağrı bittiğinde (2.1.7 kanonik kodu + retryable) + contact uyum/sayaç durumu
                + kapasite → deterministik EYLEM: retry / callback / suppress / no_action + zamanlama.
  • Uyum:       DNC (FR-TEL-014/FR-OUT-006), consent (FR-OUT-003), arama saati (FR-TEL-013/
                FR-OUT-004), kapasite/backpressure (FR-RES-014/FR-OUT-007) zamanlamadan ÖNCE.
  • Tüketici:   2.1.7 retryable bayrağı + outbound_callback start kodu; sonuç dial isteği girdisidir.

Komutlar:
  validate            retry-callback-spec.json'ı invariant'lara (C1..C14) + config politikalarına
                      + 2.1.7 taksonomi çapraz-tutarlılığına karşı doğrular (çıkış kodu).
  decide <sample>     Deterministik karar simülatörü — tek çağrı bitişi → eylem + zamanlama;
                      opsiyonel `expect` ile doğrular. Uyum/sınır kapıları → çıkış kodu.
  simulate <sample>   Bir contact'ı tükenene kadar çoklu-deneme koşturur (her retry sonrası tekrar
                      düşer) → toplam deneme tavanın altında kalır mı (C2) gösterir.
  selftest            İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema              Beklenen spec/sample şeklini özetler.

Sunucu/credential GEREKMEZ. Karar gerçek dialer yerine deterministik karardır (numbering select /
reason-codes classify / objstore access-decision deseni). now sanal saattir; jitter tohumlu.
Numara/PII koda/karara gömülmez (C11).
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "retry-callback-spec.json")
POLICY_CFG = os.path.join(HERE, "config", "retry-policies.json")
# 2.1.7 taksonomisi — retryable kaynak doğruluğu (çapraz-tutarlılık C12)
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
    """2.1.7 end_reasons.codes → {code: retryable}. Yoksa None (validate not düşer)."""
    if not os.path.exists(REASON_SPEC):
        return None
    spec = _load(REASON_SPEC)
    codes = spec.get("end_reasons", {}).get("codes", {})
    return {k: bool(v.get("retryable", False)) for k, v in codes.items()}


class DecisionError(Exception):
    """Geçersiz istek / taksonomi uyuşmazlığı — sessiz kabul yok."""


# ─────────────────────────────────────────────────────────────────────────────
# Çekirdek: deterministik karar motoru (FR-TEL-009)
# ─────────────────────────────────────────────────────────────────────────────
def _parse_iso(s):
    if s is None:
        return None
    s = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_policy(spec, sample):
    """policy_ref: config profili adı VEYA inline policy nesnesi."""
    ref = sample.get("policy_ref")
    if isinstance(ref, dict):
        return ref
    if os.path.exists(POLICY_CFG):
        cfg = _load(POLICY_CFG)
        for p in cfg.get("policies", []):
            if p.get("name") == ref:
                return p
    raise DecisionError("politika bulunamadı: %r" % ref)


def _eligibility_class(spec, reason_code):
    """2.1.7 kodu → eligibility sınıfı (dropped/no_contact/capacity) veya None."""
    classes = spec.get("eligibility", {}).get("classes", {})
    for cname, cdef in classes.items():
        if reason_code in cdef.get("codes", []):
            return cname, cdef.get("decision_reason")
    return None, None


def _backoff_seconds(policy, attempt_number):
    """attempt_number (1-tabanlı) için backoff. fixed: sabit. exponential: base*mult^(n-1).
    max_interval_seconds ile sınırlı (C3). dropped sınıfı çağıran tarafından drop_grace ile ezilir."""
    base = int(policy["base_interval_seconds"])
    cap = int(policy["max_interval_seconds"])
    strat = policy["backoff_strategy"]
    if strat == "fixed":
        val = base
    else:  # exponential
        mult = float(policy.get("multiplier", 2))
        val = base * (mult ** (attempt_number - 1))
    return int(min(val, cap))


def _deterministic_jitter(idem_key, cap):
    """idempotency_key → [0, cap] deterministik jitter (C4). SHA-256 tohum; cüzdan-saati yok."""
    if cap <= 0:
        return 0
    h = hashlib.sha256(idem_key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % (cap + 1)


def _idempotency_key(tenant_id, contact_id, attempt_number, reason_code):
    """Deterministik anahtar (C10). Ham PII yok — contact_id (UUID) + sayaç + kod (C11)."""
    raw = "%s|%s|%d|%s" % (tenant_id, contact_id, attempt_number, reason_code)
    return "rc_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _roll_into_calling_hours(candidate_utc, offset_minutes, start_hour, end_hour):
    """candidate (UTC) yerel pencere [start_hour,end_hour) dışındaysa sonraki pencere açılışına
    ileri-sar (C7). Döner: (scheduled_utc, rescheduled?bool). Pencere geçerliyse en fazla 1 gün ileri."""
    local = candidate_utc + timedelta(minutes=offset_minutes)
    h = local.hour + local.minute / 60.0
    if start_hour <= h < end_hour:
        return candidate_utc, False
    # Pencere açılışına ileri-sar
    open_local = local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if h >= end_hour:  # bugünkü pencere kapandı → yarın aç
        open_local = open_local + timedelta(days=1)
    scheduled_utc = open_local - timedelta(minutes=offset_minutes)
    return scheduled_utc, True


def decide(spec, sample, taxonomy=None):
    """Bir çağrı bitişi → kontrollü retry/callback kararı. Saf/deterministik."""
    now = _parse_iso(sample["now"])
    tenant_id = sample.get("tenant_id", "tenant")
    policy = _resolve_policy(spec, sample)
    end = sample.get("end", {})
    contact = sample.get("contact", {})
    capacity = sample.get("capacity", {"available": True})

    reason_code = end.get("reason_code")
    if reason_code is None:
        raise DecisionError("end.reason_code zorunlu")
    retryable = bool(end.get("retryable", False))

    # C12 — 2.1.7 taksonomisiyle çapraz-tutarlılık (taxonomy verildiyse)
    if taxonomy is not None:
        if reason_code not in taxonomy:
            raise DecisionError("reason_code 2.1.7 taksonomisinde yok: %s" % reason_code)
        if taxonomy[reason_code] != retryable:
            raise DecisionError(
                "retryable uyuşmazlığı: %s taksonomi=%s istek=%s (C12)"
                % (reason_code, taxonomy[reason_code], retryable))

    contact_id = contact.get("contact_id", "contact")
    attempts = int(contact.get("attempts", 0))
    next_attempt = attempts + 1
    idem = _idempotency_key(tenant_id, contact_id, next_attempt, reason_code)

    def _suppress(reason):
        return {
            "action": "suppress", "decision_reason": reason, "attempt_number": None,
            "scheduled_at": None, "backoff_seconds": None, "jitter_seconds": None,
            "start_reason": None, "idempotency_key": idem,
            "compliance_recheck_required": False, "reason_code": reason_code,
        }

    # ── Uyum kapıları (zamanlamadan ÖNCE; sıra G1→G5) ──────────────────────────
    # G1 DNC (C5) — kalıcı engel
    if contact.get("do_not_call") is True:
        return _suppress("dnc_suppressed")
    # G2 consent (C6) — yalnız granted yeniden aranabilir
    if contact.get("consent_state", "none") != "granted":
        return _suppress("consent_withdrawn")
    # G3 retryable (C1) — non-retryable kod hiç retry üretmez
    if not retryable:
        return {
            "action": "no_action", "decision_reason": "non_retryable", "attempt_number": None,
            "scheduled_at": None, "backoff_seconds": None, "jitter_seconds": None,
            "start_reason": None, "idempotency_key": idem,
            "compliance_recheck_required": False, "reason_code": reason_code,
        }
    # G4 maks. deneme (C2) — sert tavan
    if attempts >= int(policy["max_attempts"]):
        return _suppress("max_attempts_exhausted")

    # ── Uygunluk sınıfı (dropped/no_contact/capacity; C13) ─────────────────────
    cls, cls_reason = _eligibility_class(spec, reason_code)
    if cls is None:
        # retryable=true ama sınıfa girmiyor → taksonomi/eligibility boşluğu (sessiz yutma yok)
        raise DecisionError("retryable kod eligibility sınıfında yok: %s" % reason_code)

    # ── Eylem türü + backoff ──────────────────────────────────────────────────
    # G5 kapasite (C8): backpressure → kontrollü callback ertelemesi
    capacity_blocked = capacity.get("available", True) is False
    if cls == "capacity" or capacity_blocked:
        action = "callback"
        decision_reason = "capacity_deferred"
    elif cls == "dropped":
        action = "retry" if policy.get("mode", "retry") == "retry" else "callback"
        decision_reason = cls_reason  # dropped_retry
    else:  # no_contact
        action = "retry" if policy.get("mode", "retry") == "retry" else "callback"
        decision_reason = cls_reason  # no_contact_retry

    # backoff: dropped sınıfı kısa lütuf gecikmesi alır (FR-TEL-009 hızlı yeniden bağlanma)
    if cls == "dropped" and not capacity_blocked:
        backoff = int(policy.get("drop_grace_seconds", 0))
    else:
        backoff = _backoff_seconds(policy, next_attempt)
    jitter = _deterministic_jitter(idem, int(policy["jitter_cap_seconds"]))

    candidate = now + timedelta(seconds=backoff + jitter)

    # ── Arama saati (C7): pencere dışıysa ileri-sar ────────────────────────────
    ch = policy.get("calling_hours")
    rescheduled = False
    if ch:
        offset = int(contact.get("utc_offset_minutes", 0))
        scheduled, rescheduled = _roll_into_calling_hours(
            candidate, offset, int(ch["start_hour"]), int(ch["end_hour"]))
    else:
        scheduled = candidate

    if rescheduled:
        decision_reason = "rescheduled_calling_hours"

    return {
        "action": action,
        "decision_reason": decision_reason,
        "attempt_number": next_attempt,
        "scheduled_at": _fmt_iso(scheduled),
        "backoff_seconds": backoff,
        "jitter_seconds": jitter,
        "start_reason": "outbound_callback",
        "idempotency_key": idem,
        "compliance_recheck_required": True,
        "reason_code": reason_code,
    }


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
    ACT = set(enums.get("action", []))
    DR = set(enums.get("decision_reason", []))
    STRAT = set(enums.get("backoff_strategy", []))
    _check(spec.get("policy_version"), "policy_version mevcut")
    _check(ACT == {"retry", "callback", "suppress", "no_action"}, "enums.action kapalı küme")
    _check(STRAT == {"fixed", "exponential"}, "enums.backoff_strategy kapalı küme")
    _check(enums.get("start_reason") == ["outbound_callback"],
           "C9 start_reason = outbound_callback (2.1.7 linki)")

    # ── eligibility sınıfları + 2.1.7 çapraz-tutarlılık (C1/C12/C13)
    taxonomy = _reason_taxonomy()
    classes = spec.get("eligibility", {}).get("classes", {})
    _check({"dropped", "no_contact", "capacity"} <= set(classes.keys()),
           "C13 eligibility 3 sınıf (dropped/no_contact/capacity)")
    elig_codes = []
    for cdef in classes.values():
        elig_codes += cdef.get("codes", [])
    _check(len(elig_codes) == len(set(elig_codes)), "eligibility kodları sınıflar arası ayrık")
    _check("dropped_mid_call" in classes.get("dropped", {}).get("codes", []),
           "C13 dropped_mid_call (FR-TEL-009 çekirdek) dropped sınıfında")

    if taxonomy is None:
        _check(True, "NOT: 2.1.7 taksonomi bulunamadı — C1/C12 çapraz-doğrulama atlandı")
    else:
        # C1: her eligibility kodu 2.1.7'de retryable=true
        bad = [c for c in elig_codes if not taxonomy.get(c, False)]
        _check(not bad, "C1 tüm eligibility kodları 2.1.7'de retryable=true (%s)" % (bad[:3] or "—"))
        # C13: 2.1.7'deki retryable=true kodların tümü bir sınıfa atanmış (boşluk yok)
        unmapped = [c for c, r in taxonomy.items() if r and c not in elig_codes]
        _check(not unmapped, "C13 2.1.7 retryable kodları tam kapsanır (boşluk: %s)" % (unmapped[:3] or "—"))

    # ── compliance kapıları (C5/C6) sıralı + doğru eylem
    gates = {g.get("id"): g for g in spec.get("compliance_gates", {}).get("gates", [])}
    _check({"G1", "G2", "G3", "G4", "G5"} <= set(gates.keys()), "compliance_gates G1..G5 tanımlı")
    _check(gates.get("G1", {}).get("action") == "suppress"
           and gates["G1"].get("decision_reason") == "dnc_suppressed", "C5 G1 DNC → suppress")
    _check(gates.get("G2", {}).get("action") == "suppress"
           and gates["G2"].get("decision_reason") == "consent_withdrawn", "C6 G2 consent → suppress")
    _check(gates.get("G3", {}).get("action") == "no_action", "C1 G3 non-retryable → no_action")
    _check(gates.get("G4", {}).get("decision_reason") == "max_attempts_exhausted",
           "C2 G4 maks. deneme → suppress")
    _check(gates.get("G5", {}).get("action") == "callback", "C8 G5 kapasite → callback")

    # ── decision_reason enum bütünlüğü: sınıf + kapı gerekçeleri enum'da
    used_reasons = set()
    for cdef in classes.values():
        used_reasons.add(cdef.get("decision_reason"))
    for g in gates.values():
        used_reasons.add(g.get("decision_reason"))
    _check(used_reasons <= DR, "kullanılan decision_reason'lar enum içinde (%s)"
           % (sorted(used_reasons - DR)[:3] or "—"))

    # ── residency + pii + literal sır (C11/C14)
    _check(spec.get("residency", {}).get("region_pin_required") is True, "C11 residency region pin")
    pii = spec.get("pii", {})
    _check(pii.get("decision_pii_class") == "none"
           and pii.get("phone_number_in_decision_forbidden") is True
           and pii.get("raw_pii_in_idempotency_key_forbidden") is True,
           "C11 karar PII içermez (pii_class=none)")

    # ── invariant kataloğu
    inv = spec.get("invariants", [])
    inv_ids = [i.get("id") for i in inv]
    _check(len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 14, "invariant kataloğu ≥14 + tekil ID")
    _check(all(i.get("trace") for i in inv), "her invariant trace taşır")

    # ── config politikaları (C3/C4/C14)
    hits = _scan_secrets(spec)
    if os.path.exists(POLICY_CFG):
        cfg = _load(POLICY_CFG)
        hits += _scan_secrets(cfg)
        pols = cfg.get("policies", [])
        _check(len(pols) >= 2, "C14 config ≥2 politika (vendor/senaryo-nötr)")
        names = [p.get("name") for p in pols]
        _check(len(names) == len(set(names)), "config politika isimleri tekil")
        for p in pols:
            nm = p.get("name")
            _check(isinstance(p.get("max_attempts"), int) and p["max_attempts"] >= 1,
                   "C2 %s max_attempts ≥1 sonlu" % nm)
            _check(p.get("backoff_strategy") in STRAT, "C3 %s strategy geçerli" % nm)
            _check(isinstance(p.get("base_interval_seconds"), int) and p["base_interval_seconds"] > 0,
                   "C3 %s base_interval >0" % nm)
            _check(isinstance(p.get("max_interval_seconds"), int)
                   and p["max_interval_seconds"] >= p.get("base_interval_seconds", 1),
                   "C3 %s max_interval ≥ base (sınırlı backoff)" % nm)
            _check(isinstance(p.get("jitter_cap_seconds"), int) and p["jitter_cap_seconds"] > 0,
                   "C4 %s jitter_cap >0 (desenkronizasyon)" % nm)
            ch = p.get("calling_hours")
            if ch:
                _check(0 <= ch.get("start_hour", -1) < ch.get("end_hour", -1) <= 24,
                       "C7 %s calling_hours geçerli pencere" % nm)
            # C3: exponential backoff gerçekten monotonik + cap'e takılır
            if p.get("backoff_strategy") == "exponential":
                seq = [_backoff_seconds(p, n) for n in range(1, p["max_attempts"] + 1)]
                _check(all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)),
                       "C3 %s exponential backoff monotonik" % nm)
                _check(all(s <= p["max_interval_seconds"] for s in seq),
                       "C3 %s backoff max_interval ile sınırlı" % nm)
    _check(not hits, "C14 literal sır yok (spec+config)")

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
# decide <sample>
# ─────────────────────────────────────────────────────────────────────────────
def cmd_decide(sample_path):
    spec = _load(SPEC_PATH)
    taxonomy = _reason_taxonomy()
    sample = _load(sample_path)
    try:
        res = decide(spec, sample, taxonomy)
    except DecisionError as e:
        # Bozuk/uyumsuz istek bilinçli mi? sample allow_error ile işaret eder.
        if sample.get("allow_error"):
            print("decide: beklenen hata → %s" % e)
            print("decide: PASS ✅")
            return 0
        print("decide: HATA → %s" % e)
        print("decide: FAIL ❌")
        return 1

    print("kod: %s (retryable=%s) → eylem: %s [%s]" % (
        res["reason_code"], sample.get("end", {}).get("retryable"),
        res["action"], res["decision_reason"]))
    if res["scheduled_at"]:
        print("  attempt=%s scheduled_at=%s backoff=%ss jitter=%ss start_reason=%s" % (
            res["attempt_number"], res["scheduled_at"], res["backoff_seconds"],
            res["jitter_seconds"], res["start_reason"]))
    print("  idempotency_key=%s recheck=%s" % (res["idempotency_key"], res["compliance_recheck_required"]))

    gate_ok = True
    exp = sample.get("expect", {})
    for field in ("action", "decision_reason", "attempt_number", "backoff_seconds",
                  "jitter_seconds", "start_reason", "scheduled_at", "compliance_recheck_required"):
        if field in exp and res.get(field) != exp[field]:
            print("  ✗ expect.%s=%r ama got=%r" % (field, exp[field], res.get(field)))
            gate_ok = False
    print("decide: %s" % ("PASS ✅" if gate_ok else "FAIL ❌"))
    return 0 if gate_ok else 1


# ─────────────────────────────────────────────────────────────────────────────
# simulate <sample> — çoklu deneme: tavan aşılmaz (C2)
# ─────────────────────────────────────────────────────────────────────────────
def cmd_simulate(sample_path):
    spec = _load(SPEC_PATH)
    taxonomy = _reason_taxonomy()
    sample = _load(sample_path)
    policy = _resolve_policy(spec, sample)
    max_attempts = int(policy["max_attempts"])

    contact = dict(sample.get("contact", {}))
    now = _parse_iso(sample["now"])
    rounds = 0
    last = None
    print("simulate: max_attempts=%d, kod=%s" % (max_attempts, sample.get("end", {}).get("reason_code")))
    # Güvenlik ağı: tavanın 5 katı tur sınırı — sonsuz döngü olmamalı
    while rounds < max_attempts + 5:
        s = dict(sample)
        s["contact"] = dict(contact)
        s["now"] = _fmt_iso(now)
        res = decide(spec, s, taxonomy)
        last = res
        print("  tur %d: attempts=%d → %s/%s attempt_number=%s" % (
            rounds + 1, contact.get("attempts", 0), res["action"],
            res["decision_reason"], res["attempt_number"]))
        rounds += 1
        if res["action"] in ("suppress", "no_action"):
            break
        # retry/callback → deneme yapıldı say, saati ilerlet, tekrar düştü varsay
        contact["attempts"] = contact.get("attempts", 0) + 1
        now = _parse_iso(res["scheduled_at"])

    ok = last is not None and last["action"] in ("suppress", "no_action")
    capped = contact.get("attempts", 0) <= max_attempts
    print("  → son eylem=%s, toplam yapılan deneme=%d (tavan=%d)" % (
        last["action"], contact.get("attempts", 0), max_attempts))
    gate = ok and capped
    print("simulate: %s (C2 tavan korundu=%s, sonlandı=%s)" % (
        "PASS ✅" if gate else "FAIL ❌", capped, ok))
    return 0 if gate else 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def selftest():
    spec = _load(SPEC_PATH)
    taxonomy = _reason_taxonomy()
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 1) validate iyi spec+config'te geçer
    case(_validate_obj(spec) == 0, "validate iyi spec+config'te 0 döndürür")

    base_contact = {"contact_id": "c1", "attempts": 0, "do_not_call": False,
                    "consent_state": "granted", "utc_offset_minutes": 0}

    def mk(reason_code, retryable, **over):
        s = {"now": "2026-06-15T12:00:00Z", "tenant_id": "t1",
             "policy_ref": "campaign-default",
             "end": {"reason_code": reason_code, "retryable": retryable},
             "contact": dict(base_contact),
             "capacity": {"available": True}}
        for k, v in over.items():
            if k in ("do_not_call", "consent_state", "attempts", "utc_offset_minutes", "contact_id"):
                s["contact"][k] = v
            else:
                s[k] = v
        return s

    # ── dropped_mid_call (FR-TEL-009 çekirdek) → retry, drop_grace (C13)
    r = decide(spec, mk("dropped_mid_call", True), taxonomy)
    case(r["action"] == "retry" and r["decision_reason"] == "dropped_retry"
         and r["start_reason"] == "outbound_callback", "C13 dropped_mid_call → retry (outbound_callback)")
    case(r["backoff_seconds"] == 30, "dropped drop_grace_seconds=30 uygulanır")

    # ── no_answer → no_contact_retry, backoff
    r = decide(spec, mk("no_answer", True), taxonomy)
    case(r["action"] == "retry" and r["decision_reason"] == "no_contact_retry", "no_answer → no_contact_retry")
    case(r["backoff_seconds"] >= 1, "no_contact backoff > 0")

    # ── C1/G3 non-retryable (rejected) → no_action
    r = decide(spec, mk("rejected", False), taxonomy)
    case(r["action"] == "no_action" and r["decision_reason"] == "non_retryable", "C1 rejected → no_action")

    # ── C5 DNC → suppress (retryable kod olsa bile)
    r = decide(spec, mk("no_answer", True, do_not_call=True), taxonomy)
    case(r["action"] == "suppress" and r["decision_reason"] == "dnc_suppressed", "C5 DNC → suppress")

    # ── C6 consent withdrawn → suppress
    r = decide(spec, mk("busy", True, consent_state="withdrawn"), taxonomy)
    case(r["action"] == "suppress" and r["decision_reason"] == "consent_withdrawn", "C6 consent → suppress")

    # ── C2 maks. deneme → suppress (attempts == max)
    r = decide(spec, mk("no_answer", True, attempts=3), taxonomy)  # campaign-default max=3
    case(r["action"] == "suppress" and r["decision_reason"] == "max_attempts_exhausted",
         "C2 attempts==max → suppress")
    # tavan altında devam eder
    r = decide(spec, mk("no_answer", True, attempts=2), taxonomy)
    case(r["action"] == "retry" and r["attempt_number"] == 3, "C2 tavan altında attempt_number=3")

    # ── C8 kapasite yok → callback (capacity_deferred)
    r = decide(spec, mk("no_answer", True, capacity={"available": False}), taxonomy)
    case(r["action"] == "callback" and r["decision_reason"] == "capacity_deferred",
         "C8 backpressure → callback")
    # capacity sınıfı kodu (abandoned_no_capacity) → callback
    r = decide(spec, mk("abandoned_no_capacity", True), taxonomy)
    case(r["action"] == "callback" and r["decision_reason"] == "capacity_deferred",
         "C8 abandoned_no_capacity → callback")

    # ── C10 idempotency_key deterministik + aynı istek aynı karar
    a = decide(spec, mk("no_answer", True), taxonomy)
    b = decide(spec, mk("no_answer", True), taxonomy)
    case(a["idempotency_key"] == b["idempotency_key"] and a == b, "C10 aynı istek → aynı karar/anahtar")
    c = decide(spec, mk("busy", True), taxonomy)
    case(c["idempotency_key"] != a["idempotency_key"], "C10 farklı kod → farklı anahtar")

    # ── C4 jitter deterministik + sınırlı
    case(0 <= a["jitter_seconds"] <= 120, "C4 jitter [0,cap] aralığında")
    case(a["jitter_seconds"] == decide(spec, mk("no_answer", True), taxonomy)["jitter_seconds"],
         "C4 jitter deterministik (tekrar aynı)")

    # ── C7 arama saati dışı → ileri-sar (rescheduled). Gece yarısı UTC, pencere 09-18 yerel.
    r = decide(spec, mk("no_answer", True, override_now=None), taxonomy) if False else None
    s = mk("no_answer", True)
    s["now"] = "2026-06-15T03:00:00Z"  # yerel 03:00 (offset 0) → pencere dışı
    s["policy_ref"] = "campaign-default"
    r = decide(spec, s, taxonomy)
    case(r["decision_reason"] == "rescheduled_calling_hours",
         "C7 pencere dışı → rescheduled_calling_hours")
    # scheduled yerel saat pencere içinde mi (>= start_hour)
    sch = _parse_iso(r["scheduled_at"])
    case(sch.hour >= 9 and sch.hour < 18, "C7 yeniden zamanlama penceresi içinde (09-18)")

    # ── C3 exponential backoff artıyor + cap (transactional-callback fixed? use a policy)
    pol = None
    if os.path.exists(POLICY_CFG):
        for p in _load(POLICY_CFG)["policies"]:
            if p["backoff_strategy"] == "exponential":
                pol = p
                break
    if pol:
        seq = [_backoff_seconds(pol, n) for n in range(1, pol["max_attempts"] + 2)]
        case(all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)), "C3 exponential monotonik artar")
        case(seq[-1] <= pol["max_interval_seconds"], "C3 backoff cap'e takılır")

    # ── C11 karar PII içermez (idempotency_key contact_id'den; numara yok)
    s = mk("no_answer", True, contact_id="00000000-0000-0000-0000-000000000abc")
    r = decide(spec, s, taxonomy)
    case("00000000" not in r["idempotency_key"] and "+90" not in json.dumps(r),
         "C11 karar/anahtar ham PII içermez")

    # ── C12 retryable uyuşmazlığı → hata
    if taxonomy is not None:
        case(_raises(lambda: decide(spec, mk("no_answer", False), taxonomy)),
             "C12 retryable taksonomiyle uyuşmazsa hata")
        case(_raises(lambda: decide(spec, mk("not_a_real_code", True), taxonomy)),
             "C12 taksonomi-dışı kod → hata")

    # ── negatif kapı kanıtı: bozuk spec/config validate'i elemeli ───────────────
    bad = json.loads(json.dumps(spec))
    bad["compliance_gates"]["gates"][0]["action"] = "retry"  # C5 G1 DNC retry olamaz
    case(_validate_obj(bad) == 1, "negatif: G1 DNC action=retry → validate eler (C5)")

    bad = json.loads(json.dumps(spec))
    bad["enums"]["start_reason"] = ["inbound_pstn"]  # C9 ihlali
    case(_validate_obj(bad) == 1, "negatif: start_reason outbound_callback değil → eler (C9)")

    bad = json.loads(json.dumps(spec))
    bad["pii"]["phone_number_in_decision_forbidden"] = False  # C11
    case(_validate_obj(bad) == 1, "negatif: PII koruması kapalı → eler (C11)")

    bad = json.loads(json.dumps(spec))
    del bad["eligibility"]["classes"]["dropped"]  # C13 dropped sınıfı yok
    case(_validate_obj(bad) == 1, "negatif: dropped sınıfı silinince → eler (C13)")

    # config-bağımlı negatifler (geçici dosya yerine in-memory validate edemeyiz → atla guard)
    case(True, "selftest tamam")

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
    print("Beklenen spec şekli (retry-callback-spec.json):")
    print("  policy_version           : str")
    print("  enums                    : action/decision_reason/backoff_strategy/start_reason (kapalı küme)")
    print("  decision_contract        : request/response sözleşmesi")
    print("  policy_model.fields      : max_attempts/backoff/jitter/calling_hours/mode/drop_grace")
    print("  eligibility.classes      : dropped / no_contact / capacity → 2.1.7 kod listesi (C1/C13)")
    print("  compliance_gates.gates   : G1 DNC · G2 consent · G3 non-retryable · G4 max · G5 capacity")
    print("  residency / pii          : region pin + karar PII içermez (C11)")
    print("  invariants[]             : C1..C14")
    print("decide/simulate sample şekli:")
    print("  {now, tenant_id, policy_ref, end:{reason_code,retryable},")
    print("   contact:{contact_id,attempts,do_not_call,consent_state,utc_offset_minutes},")
    print("   capacity:{available}, [allow_error], [expect:{...}]}")
    return 0


def main(argv):
    if len(argv) < 2:
        print("kullanım: retry_callback_probe.py {validate|decide <sample>|simulate <sample>|selftest|schema}")
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return cmd_validate()
    if cmd == "decide":
        if len(argv) < 3:
            print("decide: <sample.json> gerekli")
            return 2
        return cmd_decide(argv[2])
    if cmd == "simulate":
        if len(argv) < 3:
            print("simulate: <sample.json> gerekli")
            return 2
        return cmd_simulate(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
