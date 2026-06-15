#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 7.3.2 — Kritik işlem öncesi müşteri teyidi + ek doğrulama (FR-TOOL-006/007) referans probe.

7.3 'Deterministic workflow engine' workstream'inin İKİNCİ modülü. 7.3.1 (critical-workflow) FSM'i
CONFIRM kapısında {value: yes|no|ambiguous} teyit OLAYINI, AUTH kapısında step_up BOOLEAN'ını tüketir;
bu modül o olay/kararların DETAYINI üretir (7.3.1 'teyit/ek-doğrulama AYRINTISI→7.3.2; hook TÜKETİLİR'
diye erteledi):

  (A) MÜŞTERİ TEYİDİ (FR-TOOL-006)            (B) EK DOĞRULAMA (FR-TOOL-007)
  ───────────────────────────────            ─────────────────────────────────
  maskeli readback üret (V3)                  gereklilik politikadan (para/sözleşme/PII) (V5)
  yanıt → {yes|no|ambiguous} (V1)             8.x doğrulama SONUCU dört testi geçmeli:
  fail-closed: belirsiz≠yes                     METHOD_CLASS ≥ strong (V7; caller_id 'weak')
  sınırlı re-prompt (V4)                         BOUND (işlem parmak izi) (V6)
  teyit BAĞI (fingerprint) (V2)                 FRESH (tazelik penceresi) (V6)
  olumsuz derhal DECLINE (V12)                  SINGLE_USE (nonce replay yok) (V6)
        │                                            │
        ▼  events_for_fsm.confirm.value              ▼  events_for_fsm.step_up = satisfied
        └──────────────►  7.3.1 critical-workflow FSM  ◄──────────────┘

ÇEKİRDEK INVARIANT (FR-TOOL-006/007 + SR-TOOL-006/007): teyit alınmadan (açık olumlu) kritik işlem
yürütülmez (V1); para/sözleşme/PII değişikliğinde tatmin edici ek doğrulama olmadan reddedilir (V5);
teyit işlem-bağlı + ek doğrulama tek-kullanımlık/tazelik/işlem-bağlı (V2/V6 anti-replay); hassas değer
sesli tam tekrarlanmaz (V3/V9; FR-AUTH-005).

Kapsam dışı (başka modül SAHİBİ): auth MEKANİZMASI (OTP/KBA üreteci)→8.x (sonucu TÜKETİR); FSM kapı
sıralaması/execute/onay→7.3.1; STT/NLU niyet→2.x/3.x (tanınmış yanıtı TÜKETİR); tool dispatch→7.2.x;
müşteri hata METNİ→7.1.5; audit STORE→7.1.6/12.1.8.

Kullanım:
  confirmation_verification_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  confirmation_verification_probe.py run <sample>      Karar-yürütücü: teyit+doğrulama → kapı (V1–V12)
  confirmation_verification_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  confirmation_verification_probe.py schema            Karar/olay sözleşmesini yazdır

Determinizm: sanal saat (at_ms/now_ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "confirmation-verification-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "confirmation-verification-policies.json")

CONFIRM_VALUES = {"yes", "no", "ambiguous"}
DECISION_VALUES = {"PROCEED", "DECLINE", "NOT_CONFIRMED", "VERIFICATION_FAILED"}
VERIF_FAIL_REASONS = {"NO_VERIFICATION", "WEAK_METHOD", "NOT_BOUND", "STALE", "REPLAYED"}
CLASS_RANK = {"weak": 0, "medium": 1, "strong": 2}
INVARIANT_IDS = ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11", "V12"]
ERROR_CLASSES = {"MISSING_POLICY_CONFIG", "INVALID_POLICY", "INVALID_REQUEST",
                 "NON_MONOTONIC_CLOCK", "INTERNAL_ERROR"}

# ── Sızıntı tarayıcı (V3/V9; 7.1.5/7.2.5/7.3.1 deseniyle) — readback/audit'te ham hassas yasak ─
PII_PATTERNS = [
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # IBAN (2 harf + 2 hane + ≥10 alnum) ve ≥10 haneli ham dizi (kart 16 / telefon 10+ / hesap / kimlik).
    # Eşik 10: meşru tutar (≤9 hane) readback'te maskesiz GÖSTERİLEBİLİR, kimlik dizisi GÖSTERİLEMEZ.
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,}\b")),
    ("long_digits", re.compile(r"\d{10,}")),
    ("secret", re.compile(r"(?i)\b(bearer\s+\S+|password|client[_-]?secret|api[_-]?key\s*[:=])")),
]


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _no_meta(d):
    """Meta anahtarlarını ($comment/trace) iterasyondan ele (eventstream/7.3.1 deseni)."""
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if not k.startswith("$") and k != "trace"}
    return d


def _scan(text, patterns):
    hits = []
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    for name, rx in patterns:
        if rx.search(text):
            hits.append(name)
    return hits


def _tr_lower(s):
    """TR-duyarlı küçük harf (İ→i, I→ı) + casefold."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def _normalize(text):
    """Yanıtı normalize et: tr-aware küçük harf, noktalama→boşluk, tekil boşluk."""
    t = _tr_lower(str(text))
    t = re.sub(r"[^0-9a-zçğıöşü' ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _contains_term(norm_text, term):
    """Sözcük-sınırı eşleşmesi (substring değil): 'yok' 'yoktur'u, 'red' 'kredi'yi yakalamaz."""
    pad = " " + norm_text + " "
    return (" " + _tr_lower(term).strip() + " ") in pad


def _mask_value(val, kind, n=4):
    """Hassas değeri maskele (V3 / FR-AUTH-005). Rakamlı kind → son n hane; e-posta/metin → '***'."""
    s = str(val)
    digits = re.sub(r"\D", "", s)
    if kind == "email" or not digits:
        return "***"
    if len(digits) <= n:
        return "*" * len(digits)
    return "*" * (len(digits) - n) + digits[-n:]


class CVError(Exception):
    def __init__(self, error_class, msg=""):
        super().__init__("%s: %s" % (error_class, msg))
        self.error_class = error_class


# ════════════════════════════════════════════════════════════════════════════
#  Karar motoru — (A) müşteri teyidi + (B) ek doğrulama (FR-TOOL-006/007)
# ════════════════════════════════════════════════════════════════════════════
def compute_fingerprint(operation):
    """İşlem parmak izi (V2/V6 bağ): kanonik {name, params} → sha256[:16]. Ham değer SAKLANMAZ (yalnız hash)."""
    canon = json.dumps(
        {"name": operation.get("name"), "params": operation.get("params", {})},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def build_readback(operation, locale, policy):
    """Maskeli özet/okuma-geri üret (V3; FR-AUTH-005). Hassas kind maskeli, amount gösterilir,
    bilinmeyen kind ham değer DEĞİL alan-adı placeholder."""
    mp = policy["readback_masking"]
    masked_kinds = set(mp["masked_kinds"])
    shown_kinds = set(mp["shown_kinds"])
    n = int(mp.get("mask_last_n", 4))
    params = operation.get("params", {})
    kinds = operation.get("param_kinds", {})
    fields = []
    for name, val in params.items():
        kind = kinds.get(name)
        if kind in masked_kinds:
            shown = _mask_value(val, kind, n)
        elif kind in shown_kinds:
            shown = str(val)
        else:
            # bilinmeyen/etiketsiz alan: ham değeri OKUMA (PII olabilir) — yalnız alan adını an
            shown = "[%s]" % name
        fields.append("%s: %s" % (name, shown))
    op_label = operation.get("label") or operation.get("name", "işlem")
    body = "; ".join(fields)
    if locale.startswith("en"):
        return ("Please confirm the operation '%s'%s. Do you approve?"
                % (op_label, (" — " + body) if body else ""))
    return ("'%s' işlemini%s onaylıyor musunuz?"
            % (op_label, (" (" + body + ")") if body else ""))


def classify_one(utterance, locale, policy):
    """Tek yanıtı sınıflandır → yes|no|ambiguous (V1 fail-closed)."""
    lex = policy["confirmation"]["locales"].get(locale)
    if lex is None:
        # bilinmeyen locale → en-US'a düş, yine de fail-closed
        lex = policy["confirmation"]["locales"]["en-US"]
    norm = _normalize(utterance)
    if not norm:
        return "ambiguous"
    has_aff = any(_contains_term(norm, t) for t in lex["affirmative"])
    has_neg = any(_contains_term(norm, t) for t in lex["negative"])
    has_cond = any(_contains_term(norm, t) for t in lex["conditional"])
    if has_neg and not has_aff:
        return "no"
    if has_aff and not has_neg and not has_cond:
        return "yes"
    # olumlu∧olumsuz (çelişki) / koşullu kabul / hiçbiri → fail-closed belirsiz
    return "ambiguous"


def classify_confirmation(confirmation, operation, locale, policy, fingerprint):
    """Yanıt dizisini sınıflandır + re-prompt bütçesi + teyit bağı (V1/V2/V4/V12)."""
    max_reprompts = int(policy["confirmation"]["max_reprompts"])
    responses = (confirmation or {}).get("responses", []) or []
    value = "ambiguous"
    reprompts = 0
    affirmative_matched = False
    decided_at = None
    exhausted = False
    for r in responses:
        c = classify_one(r.get("utterance", ""), locale, policy)
        decided_at = r.get("at_ms", decided_at)
        if c == "no":
            value = "no"
            break
        if c == "yes":
            value = "yes"
            affirmative_matched = True
            break
        # ambiguous → yeniden sor
        reprompts += 1
        if reprompts > max_reprompts:
            value = "ambiguous"
            exhausted = True
            break

    # Teyit bağı (V2): müşterinin teyit ettiği özetin parmak izi işlemle eşleşmeli
    binding_ok = True
    declared = (confirmation or {}).get("summary_fingerprint")
    if declared is not None and declared != fingerprint:
        binding_ok = False
    if value == "yes" and not binding_ok:
        # eski/çapraz-işlem teyidi → geçersiz, yes'e dönmez (fail-closed)
        value = "ambiguous"

    return {
        "value": value,
        "reprompts_used": reprompts,
        "exhausted": exhausted,
        "affirmative_matched": affirmative_matched,
        "binding_ok": binding_ok,
        "at_ms": decided_at,
    }


def required_additional_verification(operation, policy):
    """İşlem ek doğrulama (step-up) gerektiriyor mu? (V5) — risk_class ∨ trigger param_kind."""
    av = policy["additional_verification"]
    rc = operation.get("risk_class")
    rc_cfg = av["risk_classes"].get(rc, {})
    by_rc = bool(rc_cfg.get("required", False))
    trig = set(av["trigger_param_kinds"])
    kinds = set((operation.get("param_kinds") or {}).values())
    by_kind = bool(kinds & trig)
    required = by_rc or by_kind
    min_class = rc_cfg.get("min_method_class", av["default_min_method_class"])
    freshness = int(rc_cfg.get("freshness_ms", av["default_freshness_ms"]))
    category = rc_cfg.get("category")
    if category is None and by_kind:
        category = "para/sözleşme/PII (kind)"
    return {"required": required, "min_method_class": min_class,
            "freshness_ms": freshness, "category": category}


def evaluate_verification(verification, need, policy, fingerprint, now_ms):
    """8.x doğrulama sonucunu dört testle DOĞRULA (V6/V7): METHOD_CLASS/BOUND/FRESH/SINGLE_USE."""
    av = policy["additional_verification"]
    method_classes = av["method_classes"]
    if not need["required"]:
        return {"required": False, "satisfied": True, "reason": "NOT_REQUIRED",
                "method": None, "method_class": None}

    v = verification or {}
    if not v or v.get("result") != "pass":
        return {"required": True, "satisfied": False, "reason": "NO_VERIFICATION",
                "method": v.get("method"), "method_class": None}

    method = v.get("method")
    mclass = method_classes.get(method, "weak")
    min_class = need["min_method_class"]
    if CLASS_RANK.get(mclass, 0) < CLASS_RANK.get(min_class, 2):
        return {"required": True, "satisfied": False, "reason": "WEAK_METHOD",
                "method": method, "method_class": mclass}

    if v.get("bound_fingerprint") != fingerprint:
        return {"required": True, "satisfied": False, "reason": "NOT_BOUND",
                "method": method, "method_class": mclass}

    verified_at = v.get("verified_at_ms")
    age = None if verified_at is None else (now_ms - verified_at)
    if age is None or age < 0 or age > need["freshness_ms"]:
        return {"required": True, "satisfied": False, "reason": "STALE",
                "method": method, "method_class": mclass}

    if v.get("replayed") is True or v.get("nonce") in set(v.get("_consumed_nonces", [])):
        return {"required": True, "satisfied": False, "reason": "REPLAYED",
                "method": method, "method_class": mclass}

    return {"required": True, "satisfied": True, "reason": "OK",
            "method": method, "method_class": mclass}


def decide(spec, policy, req):
    """Tek bir teyit+doğrulama karar isteğini işle → karar + FSM olayları + audit (V1–V12)."""
    if not isinstance(req, dict):
        raise CVError("INVALID_REQUEST", "request dict olmalı")
    operation = req.get("operation")
    if not isinstance(operation, dict) or not operation.get("name"):
        raise CVError("INVALID_REQUEST", "operation.name zorunlu")
    locale = req.get("locale", "tr-TR")
    now_ms = req.get("now_ms", 0)
    if not isinstance(now_ms, int):
        raise CVError("INVALID_REQUEST", "now_ms int olmalı (sanal saat)")

    fingerprint = compute_fingerprint(operation)

    # (A) Müşteri teyidi
    safe_readback = build_readback(operation, locale, policy)
    readback = req.get("unsafe_readback", safe_readback)  # degraded fixture maskelemeyi bypass eder
    conf = classify_confirmation(req.get("confirmation"), operation, locale, policy, fingerprint)

    # (B) Ek doğrulama
    need = required_additional_verification(operation, policy)
    av = evaluate_verification(req.get("verification"), need, policy, fingerprint, now_ms)

    # Birleşik karar (FSM kapı sırası: ek-doğrulama [AUTH] CONFIRM'den ÖNCE)
    if need["required"] and not av["satisfied"]:
        decision = "VERIFICATION_FAILED"
    elif conf["value"] == "no":
        decision = "DECLINE"
    elif conf["value"] != "yes":
        decision = "NOT_CONFIRMED"
    else:
        decision = "PROCEED"

    events_for_fsm = {
        "confirm": {"value": conf["value"], "at_ms": conf["at_ms"] if conf["at_ms"] is not None else now_ms},
        "step_up": bool(av["satisfied"]) if need["required"] else False,
    }

    audit = {
        "request_id": req.get("request_id"),
        "correlation_id": req.get("correlation_id"),
        "tenant_id": req.get("tenant_id"),
        "operation": operation.get("name"),
        "risk_class": operation.get("risk_class"),
        "fingerprint": fingerprint,
        "confirmation_verdict": conf["value"],
        "reprompts_used": conf["reprompts_used"],
        "binding_ok": conf["binding_ok"],
        "additional_verification": {"required": av["required"], "satisfied": av["satisfied"],
                                    "reason": av["reason"], "method_class": av["method_class"]},
        "decision": decision,
        "no_log": True,
    }
    if "unsafe_audit_detail" in req:  # degraded fixture audit'e ham PII enjekte eder
        audit["detail"] = req["unsafe_audit_detail"]

    return {
        "request_id": req.get("request_id"),
        "tenant_id": req.get("tenant_id"),
        "correlation_id": req.get("correlation_id"),
        "operation": operation.get("name"),
        "risk_class": operation.get("risk_class"),
        "fingerprint": fingerprint,
        "confirmation": {
            "readback": readback,
            "value": conf["value"],
            "reprompts_used": conf["reprompts_used"],
            "exhausted": conf["exhausted"],
            "affirmative_matched": conf["affirmative_matched"],
            "binding_ok": conf["binding_ok"],
        },
        "additional_verification": {
            "required": av["required"],
            "category": need["category"],
            "min_method_class": need["min_method_class"] if need["required"] else None,
            "satisfied": av["satisfied"],
            "reason": av["reason"],
            "method": av["method"],
            "method_class": av["method_class"],
        },
        "events_for_fsm": events_for_fsm,
        "decision": decision,
        "audit": audit,
    }


# ════════════════════════════════════════════════════════════════════════════
#  Karar kapıları (V1–V12) — bir kararın invariant'lara uyup uymadığını denetler
# ════════════════════════════════════════════════════════════════════════════
def check_gates(res):
    fails = []
    conf = res["confirmation"]
    av = res["additional_verification"]
    ev = res["events_for_fsm"]
    dec = res["decision"]

    # V1 — açık olumlu teyit: value=yes ancak açık-olumlu eşleşti ∧ bağ tamam ise
    if conf["value"] == "yes" and not conf["affirmative_matched"]:
        fails.append("V1 yes ama açık-olumlu eşleşme yok")
    if conf["value"] == "yes" and not conf["binding_ok"]:
        fails.append("V1/V2 yes ama teyit bağı bozuk")

    # V2 — bağ: binding_ok=false iken value asla yes olamaz
    if not conf["binding_ok"] and conf["value"] == "yes":
        fails.append("V2 bozuk bağ yes'e döndü")

    # V3 — readback ham hassas içermez
    leak = _scan(res["confirmation"]["readback"], PII_PATTERNS)
    if leak:
        fails.append("V3 readback sızıntı: %s" % ",".join(leak))

    # V4 — sınırlı re-prompt: karar verilen (yes/no) durumda reprompts mantıklı; exhausted → ambiguous
    if conf["exhausted"] and conf["value"] != "ambiguous":
        fails.append("V4 reprompt tükendi ama value ambiguous değil")

    # V5 — para/sözleşme/PII ek doğrulama gerekli ve tatminsiz → step_up false ∧ decision VERIFICATION_FAILED
    if av["required"] and not av["satisfied"]:
        if ev["step_up"] is not False:
            fails.append("V5 gerekli∧tatminsiz ama step_up true")
        if dec == "PROCEED":
            fails.append("V5 gerekli∧tatminsiz ama decision PROCEED")
        if dec != "VERIFICATION_FAILED":
            fails.append("V5 gerekli∧tatminsiz ama decision=%s (VERIFICATION_FAILED beklenir)" % dec)

    # V6/V7 — satisfied iken neden OK olmalı (zayıf/eski/bağsız/replay tatmin sayılmaz)
    if av["required"] and av["satisfied"] and av["reason"] != "OK":
        fails.append("V6/V7 satisfied ama reason=%s" % av["reason"])
    if av["required"] and av["satisfied"] and CLASS_RANK.get(av["method_class"], 0) < CLASS_RANK.get(av["min_method_class"], 2):
        fails.append("V7 satisfied ama method_class < min")

    # V8 — fail-closed: required iken doğrulama yok → satisfied false
    if av["required"] and av["reason"] == "NO_VERIFICATION" and av["satisfied"]:
        fails.append("V8 doğrulama yok ama satisfied true")

    # V9 — audit ham hassas içermez
    aleak = _scan(res["audit"], PII_PATTERNS)
    if aleak:
        fails.append("V9 audit sızıntı: %s" % ",".join(aleak))

    # FSM olay tutarlılığı — bu modülün ürettiği olay 7.3.1'in tükettiğiyle hizalı
    if ev["confirm"]["value"] != conf["value"]:
        fails.append("olay tutarsız: confirm.value ≠ confirmation.value")
    if ev["confirm"]["value"] not in CONFIRM_VALUES:
        fails.append("confirm.value geçersiz")
    if av["required"] and ev["step_up"] != bool(av["satisfied"]):
        fails.append("olay tutarsız: step_up ≠ satisfied")

    # V11 — audit no_log işaretli
    if not res["audit"].get("no_log"):
        fails.append("V11 audit no_log değil")

    # PROCEED tutarlılığı
    if dec == "PROCEED":
        if conf["value"] != "yes":
            fails.append("PROCEED ama teyit yes değil")
        if av["required"] and not av["satisfied"]:
            fails.append("PROCEED ama ek doğrulama tatmin değil")
    if dec == "DECLINE" and conf["value"] != "no":
        fails.append("DECLINE ama teyit no değil")

    if dec not in DECISION_VALUES:
        fails.append("decision geçersiz: %s" % dec)

    return fails


# ════════════════════════════════════════════════════════════════════════════
#  run — sample karar-yürütücü kapısı
# ════════════════════════════════════════════════════════════════════════════
def run_cmd(path):
    spec = _load(SPEC_PATH)
    policy = _load(CONFIG_PATH)
    sample = _load(path)
    name = sample.get("name", os.path.basename(path))
    cases = sample.get("requests", [])
    expect = sample.get("expect", {})
    expect_fail = bool(sample.get("expect_gate_fail"))
    print("▶ %s" % name)
    if sample.get("$comment"):
        print("  %s" % sample["$comment"])

    all_fails = []
    results = {}
    for req in cases:
        rid = req.get("request_id")
        try:
            res = decide(spec, policy, req)
        except CVError as e:
            exp = expect.get(rid, {})
            if exp.get("error") == e.error_class:
                print("  ✓ %s → beklenen CVError %s" % (rid, e.error_class))
            else:
                print("  ✗ %s → CVError %s" % (rid, e.error_class))
                all_fails.append("%s CVError %s" % (rid, e.error_class))
            continue
        results[rid] = res
        gate_fails = check_gates(res)
        all_fails += ["%s: %s" % (rid, f) for f in gate_fails]
        mark = "✓" if not gate_fails else "✗"
        av = res["additional_verification"]
        print("  %s %s [%s] → decision=%s confirm=%s step_up=%s%s%s"
              % (mark, rid, res["risk_class"], res["decision"],
                 res["confirmation"]["value"], res["events_for_fsm"]["step_up"],
                 (" verif=" + av["reason"]) if av["required"] else "",
                 (" GATE:" + ";".join(gate_fails)) if gate_fails else ""))
        exp = expect.get(rid)
        if exp:
            for k, v in exp.items():
                if k == "error":
                    continue
                got = res.get(k)
                if got != v:
                    all_fails.append("%s beklenen %s=%r ama %r" % (rid, k, v, got))
                    print("      ✗ beklenen %s=%r ama %r" % (k, v, got))

    # determinizm (V10): ikinci kez çalıştır, birebir aynı
    for req in cases:
        try:
            r2 = decide(spec, policy, req)
        except CVError:
            continue
        rid = r2["request_id"]
        if rid in results and json.dumps(r2, sort_keys=True, ensure_ascii=False) != json.dumps(results[rid], sort_keys=True, ensure_ascii=False):
            all_fails.append("V10 determinizm ihlali: %s" % rid)

    if expect_fail:
        if all_fails:
            print("  ✓ BEKLENEN ELEME (degraded): %d kapı tetiklendi → %s" % (len(all_fails), all_fails[0]))
            return 0
        print("  ✗ degraded sample geçmemeliydi ama tüm kapılar geçti")
        return 1
    if all_fails:
        print("  🔴 %d kapı eler" % len(all_fails))
        for f in all_fails:
            print("     - %s" % f)
        return 1
    print("  🟢 GEÇTİ (%d istek)" % len(cases))
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  validate — statik spec/config/kapsama kapısı
# ════════════════════════════════════════════════════════════════════════════
def validate():
    spec = _load(SPEC_PATH)
    policy = _load(CONFIG_PATH)
    fails = []
    n = [0]

    def ck(cond, label):
        n[0] += 1
        if not cond:
            fails.append(label)

    # — spec yapısı —
    ck(spec.get("wbs") == "7.3.2", "wbs=7.3.2")
    ck(spec.get("phase") == "F1", "phase=F1")
    ck(spec.get("priority") == "Must", "priority=Must")
    tr = spec.get("trace", {})
    for fr in ["FR-TOOL-006", "FR-TOOL-007", "FR-AUTH-001", "FR-AUTH-003", "FR-AUTH-005"]:
        ck(fr in tr.get("fr", []), "trace.fr içerir %s" % fr)
    for sr in ["SR-TOOL-006", "SR-TOOL-007", "SR-AUTH-003"]:
        ck(sr in tr.get("srs", []), "trace.srs içerir %s" % sr)

    # — invariant kapsama (V1–V12) —
    inv_ids = [i["id"] for i in spec.get("invariants", [])]
    for vid in INVARIANT_IDS:
        ck(vid in inv_ids, "invariant %s tanımlı" % vid)
    ck(len(inv_ids) == len(set(inv_ids)), "invariant id'leri tekil")

    # — confirmation sözleşmesi —
    cf = _no_meta(spec.get("confirmation", {}))
    ck(set(cf.get("values", [])) == CONFIRM_VALUES, "confirmation.values = {yes,no,ambiguous}")
    ck("binding" in cf, "confirmation binding (V2) belgeli")
    ck("readback_masking" in cf, "confirmation readback_masking (V3) belgeli")

    # — additional_verification sözleşmesi —
    avs = _no_meta(spec.get("additional_verification", {}))
    ck(set(avs.get("fail_reasons", [])) == VERIF_FAIL_REASONS, "av.fail_reasons tam küme")
    ck(avs.get("method_classes", {}).get("caller_id") == "weak", "caller_id 'weak' (FR-AUTH-001)")
    ck(avs.get("method_classes", {}).get("otp") == "strong", "otp 'strong'")
    for chk_name in ["METHOD_CLASS", "BOUND", "FRESH", "SINGLE_USE"]:
        ck(any(chk_name in c for c in avs.get("checks", [])), "av check %s belgeli" % chk_name)

    # — decision sözleşmesi —
    dv = set(_no_meta(spec.get("decision", {})).get("values", []))
    ck(dv == DECISION_VALUES, "decision.values tam küme")

    # — fsm_events sözleşmesi (7.3.1 ile köprü) —
    fe = _no_meta(spec.get("fsm_events", {}))
    ck("confirm" in fe and "step_up" in fe, "fsm_events confirm+step_up (7.3.1 köprü)")

    # — audit no-log —
    au = spec.get("audit", {})
    ck(au.get("no_log") is True, "audit.no_log=true")
    ck(au.get("immutable") is True, "audit.immutable=true")
    ck("fingerprint" in au.get("fields", []), "audit fingerprint (ham değer yerine hash)")

    # — error taxonomy —
    ck(set(spec.get("error_taxonomy", {}).get("classes", [])) == ERROR_CLASSES, "error_taxonomy tam küme")

    # — policy config bütünlüğü —
    pc = policy.get("confirmation", {})
    ck(isinstance(pc.get("max_reprompts"), int) and pc["max_reprompts"] >= 0, "max_reprompts int≥0")
    loc = pc.get("locales", {})
    ck("tr-TR" in loc and "en-US" in loc, "locales tr-TR + en-US")
    for lc, lx in loc.items():
        for key in ("affirmative", "negative", "conditional"):
            ck(isinstance(lx.get(key), list) and len(lx[key]) > 0, "%s.%s dolu liste" % (lc, key))
        # olumlu ∩ olumsuz boş olmalı (çelişki yok)
        ck(not (set(lx["affirmative"]) & set(lx["negative"])), "%s olumlu∩olumsuz boş" % lc)

    pav = policy.get("additional_verification", {})
    ck(pav.get("default_min_method_class") == "strong", "default_min_method_class=strong (FR-AUTH-003)")
    ck(isinstance(pav.get("default_freshness_ms"), int), "default_freshness_ms int")
    ck(pav.get("method_classes", {}).get("caller_id") == "weak", "policy caller_id 'weak'")
    trig = set(pav.get("trigger_param_kinds", []))
    for k in ["amount", "iban", "account", "card", "contract", "national_id", "email", "phone"]:
        ck(k in trig, "trigger_param_kind içerir %s" % k)
    # 7.3.1 ile hizalı risk sınıfları (para/sözleşme/PII) ek doğrulama gerektirir
    rcs = pav.get("risk_classes", {})
    for rc in ["bank_account_change", "high_value_payment", "contact_info_change",
               "sensitive_pii_disclosure", "contract_cancellation"]:
        ck(rcs.get(rc, {}).get("required") is True, "risk_class %s required=true (V5)" % rc)
        ck(rcs.get(rc, {}).get("min_method_class") == "strong", "risk_class %s min=strong" % rc)

    # — sır/PII tarayıcısı: spec + config'te literal sır/PII yok —
    for label, blob in (("spec", spec), ("config", policy)):
        txt = json.dumps(blob, ensure_ascii=False)
        # yorum ($comment) alanları teyit sözcüklerini/örnekleri tarif edebilir; gerçek sır deseni aranır
        leak = _scan(txt, [p for p in PII_PATTERNS if p[0] in ("iban", "long_digits", "secret", "email")])
        ck(not leak, "%s literal sır/PII yok (%s)" % (label, ",".join(leak)))

    print("validate: %d kontrol, %d hata" % (n[0], len(fails)))
    for f in fails:
        print("  ✗ %s" % f)
    if not fails:
        print("  🟢 %d/%d GEÇTİ" % (n[0], n[0]))
    return 1 if fails else 0


# ════════════════════════════════════════════════════════════════════════════
#  selftest — gömülü davranış kontrolleri
# ════════════════════════════════════════════════════════════════════════════
def _ctx():
    return _load(SPEC_PATH), _load(CONFIG_PATH)


def _op(risk_class="bank_account_change", params=None, kinds=None, name="op", label=None):
    return {"name": name, "label": label, "risk_class": risk_class,
            "critical": True, "params": params or {}, "param_kinds": kinds or {}}


def _verif(method="otp", fp=None, verified_at_ms=0, result="pass", replayed=False, nonce="n1"):
    return {"method": method, "result": result, "bound_fingerprint": fp,
            "verified_at_ms": verified_at_ms, "nonce": nonce, "replayed": replayed}


def _req(operation, responses=None, verification=None, locale="tr-TR", now_ms=1000, **extra):
    r = {"request_id": "r", "correlation_id": "c", "tenant_id": "t",
         "operation": operation, "locale": locale, "now_ms": now_ms,
         "confirmation": {"responses": responses or []}}
    if verification is not None:
        r["verification"] = verification
    r.update(extra)
    return r


def selftest():
    spec, pol = _ctx()
    res = []

    def t(name, cond):
        res.append((bool(cond), name))

    def fp_of(op):
        return compute_fingerprint(op)

    # 1. Açık olumlu (tr) + strong+bound+fresh OTP → PROCEED, confirm yes, step_up true
    op = _op(params={"iban": "TR33...", "amount": 5000}, kinds={"iban": "iban", "amount": "amount"})
    fp = fp_of(op)
    r = decide(spec, pol, _req(op, [{"utterance": "evet onaylıyorum", "at_ms": 1000}],
                               _verif(fp=fp, verified_at_ms=950), now_ms=1000))
    t("1 açık olumlu+geçerli doğrulama → PROCEED", r["decision"] == "PROCEED")
    t("1 confirm yes", r["confirmation"]["value"] == "yes")
    t("1 step_up true", r["events_for_fsm"]["step_up"] is True)
    t("1 kapı temiz", check_gates(r) == [])

    # 2. V1 fail-closed: belirsiz yanıt asla yes; re-prompt tükenir → NOT_CONFIRMED
    r = decide(spec, pol, _req(op, [{"utterance": "ee bilmiyorum", "at_ms": 1},
                                    {"utterance": "şey", "at_ms": 2},
                                    {"utterance": "hmm", "at_ms": 3}],
                               _verif(fp=fp, verified_at_ms=950)))
    t("2 belirsiz → ambiguous", r["confirmation"]["value"] == "ambiguous")
    t("2 exhausted", r["confirmation"]["exhausted"] is True)
    t("2 decision NOT_CONFIRMED", r["decision"] == "NOT_CONFIRMED")

    # 3. V12 olumsuz derhal → DECLINE
    r = decide(spec, pol, _req(op, [{"utterance": "hayır vazgeçtim", "at_ms": 1}],
                               _verif(fp=fp, verified_at_ms=950)))
    t("3 olumsuz → DECLINE", r["decision"] == "DECLINE" and r["confirmation"]["value"] == "no")

    # 4. V1 koşullu kabul açık teyit değildir → ambiguous
    r = decide(spec, pol, _req(op, [{"utterance": "evet ama önce şunu açıkla", "at_ms": 1}],
                               _verif(fp=fp, verified_at_ms=950)))
    t("4 koşullu kabul → ambiguous", r["confirmation"]["value"] == "ambiguous")

    # 5. V2 teyit bağı bozuk: yanlış summary_fingerprint → yes'e dönmez
    req5 = _req(op, [{"utterance": "evet", "at_ms": 1}], _verif(fp=fp, verified_at_ms=950))
    req5["confirmation"]["summary_fingerprint"] = "DEADBEEFDEADBEEF"
    r = decide(spec, pol, req5)
    t("5 bağ bozuk → binding_ok false", r["confirmation"]["binding_ok"] is False)
    t("5 bağ bozuk → value ambiguous (yes değil)", r["confirmation"]["value"] == "ambiguous")

    # 6. V5 ek doğrulama yok → VERIFICATION_FAILED, step_up false
    r = decide(spec, pol, _req(op, [{"utterance": "evet", "at_ms": 1}], verification=None))
    t("6 doğrulama yok → VERIFICATION_FAILED", r["decision"] == "VERIFICATION_FAILED")
    t("6 step_up false", r["events_for_fsm"]["step_up"] is False)
    t("6 reason NO_VERIFICATION", r["additional_verification"]["reason"] == "NO_VERIFICATION")

    # 7. V7 zayıf yöntem (caller_id) → WEAK_METHOD
    r = decide(spec, pol, _req(op, [{"utterance": "evet", "at_ms": 1}],
                               _verif(method="caller_id", fp=fp, verified_at_ms=950)))
    t("7 caller_id → WEAK_METHOD", r["additional_verification"]["reason"] == "WEAK_METHOD")
    t("7 caller_id → satisfied false", r["additional_verification"]["satisfied"] is False)

    # 8. V6 işlem-bağsız doğrulama → NOT_BOUND
    r = decide(spec, pol, _req(op, [{"utterance": "evet", "at_ms": 1}],
                               _verif(fp="OTHERFINGERPRINT", verified_at_ms=950)))
    t("8 yanlış bağ → NOT_BOUND", r["additional_verification"]["reason"] == "NOT_BOUND")

    # 9. V6 eski doğrulama → STALE (freshness 180000)
    r = decide(spec, pol, _req(op, [{"utterance": "evet", "at_ms": 1}],
                               _verif(fp=fp, verified_at_ms=0), now_ms=300000))
    t("9 eski → STALE", r["additional_verification"]["reason"] == "STALE")

    # 10. V6 replay → REPLAYED
    r = decide(spec, pol, _req(op, [{"utterance": "evet", "at_ms": 1}],
                               _verif(fp=fp, verified_at_ms=950, replayed=True)))
    t("10 replay → REPLAYED", r["additional_verification"]["reason"] == "REPLAYED")

    # 11. en-US açık olumlu
    open_en = _op(params={"amount": 100}, kinds={"amount": "amount"})
    fpen = fp_of(open_en)
    r = decide(spec, pol, _req(open_en, [{"utterance": "Yes, I confirm.", "at_ms": 1}],
                               _verif(fp=fpen, verified_at_ms=950), locale="en-US"))
    t("11 en-US yes → confirm yes", r["confirmation"]["value"] == "yes")

    # 12. en-US negative
    r = decide(spec, pol, _req(open_en, [{"utterance": "no, cancel", "at_ms": 1}],
                               _verif(fp=fpen, verified_at_ms=950), locale="en-US"))
    t("12 en-US no → DECLINE", r["decision"] == "DECLINE")

    # 13. V3 readback maskeli — ham IBAN/uzun rakam yok
    op13 = _op(params={"iban": "TR330006100519786457841326", "account": "1234567890123",
                       "phone": "05551234567", "amount": 2500},
               kinds={"iban": "iban", "account": "account", "phone": "phone", "amount": "amount"})
    r = decide(spec, pol, _req(op13, [{"utterance": "evet", "at_ms": 1}],
                               _verif(fp=fp_of(op13), verified_at_ms=950)))
    t("13 readback sızıntısız", _scan(r["confirmation"]["readback"], PII_PATTERNS) == [])
    t("13 readback amount gösterir (≤9 hane)", "2500" in r["confirmation"]["readback"])

    # 14. V4 re-prompt sınırı: 1 belirsiz sonra yes → reprompts_used=1, PROCEED
    r = decide(spec, pol, _req(op, [{"utterance": "ee", "at_ms": 1},
                                    {"utterance": "evet onaylıyorum", "at_ms": 2}],
                               _verif(fp=fp, verified_at_ms=950)))
    t("14 1 reprompt sonra yes → PROCEED", r["decision"] == "PROCEED" and r["confirmation"]["reprompts_used"] == 1)

    # 15. V10 determinizm: aynı istek birebir aynı
    req15 = _req(op, [{"utterance": "evet", "at_ms": 1}], _verif(fp=fp, verified_at_ms=950))
    a = decide(spec, pol, req15)
    b = decide(spec, pol, req15)
    t("15 determinizm", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))

    # 16. V9 audit ham hassas içermez (mutlu yolda)
    t("16 audit sızıntısız", _scan(a["audit"], PII_PATTERNS) == [])

    # 17. fingerprint çapraz-işlem ayrımı (V2 temeli): farklı param → farklı fp
    t("17 farklı işlem → farklı fingerprint", fp_of(op) != fp_of(op13))

    # 18. PII değişikliği (kind tetik) ek doğrulama gerektirir
    pii = _op(risk_class="contact_info_change", params={"email": "x"}, kinds={"email": "email"})
    need = required_additional_verification(pii, pol)
    t("18 PII değişikliği ek doğrulama gerektirir", need["required"] is True)

    # 19. fail-closed: olumlu+olumsuz çelişki → ambiguous (yes değil)
    r = decide(spec, pol, _req(op, [{"utterance": "evet hayır", "at_ms": 1}],
                               _verif(fp=fp, verified_at_ms=950)))
    t("19 çelişki → ambiguous", r["confirmation"]["value"] == "ambiguous")

    # 20. sözcük-sınırı: 'kredi' 'red'i tetiklemez
    r = decide(spec, pol, _req(op, [{"utterance": "kredi başvurusu", "at_ms": 1}],
                               _verif(fp=fp, verified_at_ms=950)))
    t("20 sözcük-sınırı: 'kredi' negatif değil", r["confirmation"]["value"] != "no")

    # 21. INVALID_REQUEST: operation yok
    try:
        decide(spec, pol, {"request_id": "x"})
        t("21 operation yok → CVError", False)
    except CVError as e:
        t("21 operation yok → INVALID_REQUEST", e.error_class == "INVALID_REQUEST")

    # 22. tüm sample kapıları (degraded hariç gerçek kapı; degraded expect_gate_fail)
    sdir = os.path.join(HERE, "samples")
    if os.path.isdir(sdir):
        rc = 0
        for fn in sorted(os.listdir(sdir)):
            if fn.endswith(".json"):
                rc |= run_cmd(os.path.join(sdir, fn))
        t("22 tüm sample kapıları geçer", rc == 0)

    ok = sum(1 for c, _ in res if c)
    print("selftest: %d/%d" % (ok, len(res)))
    for c, name in res:
        if not c:
            print("  ✗ %s" % name)
    if ok == len(res):
        print("  🟢 %d/%d GEÇTİ" % (ok, len(res)))
    return 0 if ok == len(res) else 1


# ════════════════════════════════════════════════════════════════════════════
#  schema — karar/olay sözleşmesi
# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "wbs": "7.3.2",
        "module": "confirmation-verification",
        "owns": "FR-TOOL-006 müşteri teyidi + FR-TOOL-007 ek doğrulama (7.3.1 FSM CONFIRM/step_up besleyici)",
        "confirmation_values": sorted(CONFIRM_VALUES),
        "decision_values": sorted(DECISION_VALUES),
        "verification_fail_reasons": sorted(VERIF_FAIL_REASONS),
        "method_class_rank": CLASS_RANK,
        "invariants": INVARIANT_IDS,
        "fsm_events": {"confirm": {"value": "yes|no|ambiguous", "at_ms": "int"}, "step_up": "bool"},
        "error_classes": sorted(ERROR_CLASSES),
        "determinism": "sanal saat (at_ms/now_ms); Date.now/rastgele YOK",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "run":
        if len(argv) < 3:
            print("kullanım: run <sample.json>")
            return 2
        return run_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
