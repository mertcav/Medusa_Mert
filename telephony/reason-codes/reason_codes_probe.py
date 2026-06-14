#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reason_codes_probe.py — WBS 2.1.7 Çağrı başlangıç/bitiş neden kodları (standart taksonomi)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only statik + davranış kapısı.
telephony/{managed-cpaas,byoc-sip,numbering,dtmf} + db/ + eventstream/ probe disipliniyle aynı.

NEDEN-KODU DÜZLEMİ (çağrı yaşam-döngüsü olay/analitik; medya/numaralandırma düzlemi DEĞİL):
  • Taksonomi:   kanonik start_reasons + end_reasons kümesi (FR-TEL-012). Her bitiş kodu tam
                 nitelik kümesi taşır: category/terminal_status/outcome/party/billable/retryable/
                 event_type/error_taxonomy.
  • Sınıflama:   sağlayıcı/protokol sinyali (SIP/Q.850/CPaaS/internal) → kanonik bitiş kodu
                 (signal_map). Eşlenmeyen sinyal → 'unknown' fallback + flag (sessiz yutma yok).
  • Tüketiciler: DB.md §5.5 call.start_reason/end_reason · API §10.2 call.completed/failed/transferred
                 event'leri · OLAP 1.1.9 fct_call boyutu · FR-TEL-009 retry (2.1.8) retryable bayrağı.

Komutlar:
  validate              reason-codes-spec.json'ı invariant'lara (R1..R13) + config eşlemelerine
                        karşı doğrular (çıkış kodu).
  classify <sample>     Deterministik sınıflama simülatörü — {source,code} sinyali → kanonik bitiş
                        kodu + tüm nitelikler; opsiyonel `expect` ile beklenen sonucu doğrular;
                        eşlenmeyen sinyal 'unknown' fallback → kapı eler (R4). Kapı→çıkış kodu.
  lookup <code>         Bir start/end kodunun nitelik kümesini yazar.
  selftest              İyi/kötü spec+sample ile kapıların doğru tetiklendiğini kanıtlar.
  schema                Beklenen spec şeklini özetler.

Sunucu/credential GEREKMEZ. classify gerçek telefoni yığını yerine deterministik eşleme/karardır
(numbering normalize / dtmf detect / objstore access-decision deseni). Numara/PII koda gömülmez.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "reason-codes-spec.json")
PROVIDER_CFG = os.path.join(HERE, "config", "provider-reason-map.json")

# API §11.6 ortak ErrorTaxonomy (byoc-sip/dtmf ile birebir aynı küme)
ERROR_TAXONOMY = {
    "TIMEOUT", "RATE_LIMITED", "UNAVAILABLE", "AUTH",
    "INVALID_REQUEST", "CONTENT_FILTERED", "QUOTA_EXCEEDED", "REGION_VIOLATION",
}
CODE_RE = re.compile(r"^[a-z][a-z0-9_]+$")
# Sır tarayıcı: yorum satırları + ${ENV} placeholder elenir (eventstream/byoc/dtmf deseni).
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class ClassifyError(Exception):
    """Geçersiz/eşlenmeyen sinyal — sessiz kabul yok."""


# ─────────────────────────────────────────────────────────────────────────────
# Çekirdek: taksonomi erişimi + sınıflama (FR-TEL-012)
# ─────────────────────────────────────────────────────────────────────────────
def _end_codes(spec):
    return spec.get("end_reasons", {}).get("codes", {})


def _start_codes(spec):
    return spec.get("start_reasons", {}).get("codes", {})


def _signal_map(spec):
    return {k: v for k, v in spec.get("signal_map", {}).items() if not k.startswith("$")}


def resolve_signal(spec, source, code):
    """{source, code} → kanonik bitiş kodu adı. Eşlenmeyen → 'unknown' (fallback, R4).

    Dönen: (reason_code, is_fallback). source/code büyük-küçük harfe duyarlı eşlenir;
    cpaas durum dizeleri için küçük-harf normalize edilir."""
    smap = _signal_map(spec)
    if source not in smap:
        return "unknown", True
    table = {k: v for k, v in smap[source].items() if not k.startswith("$")}
    key = str(code)
    if source in ("cpaas", "internal"):
        key = key.strip().lower()
    if key in table:
        return table[key], False
    return "unknown", True


def classify(spec, source, code):
    """Sinyal → tam nitelik kümesi (kanonik bitiş kodu + attrs). Eşlenmeyen 'unknown' flag'li döner."""
    reason, is_fallback = resolve_signal(spec, source, code)
    attrs = _end_codes(spec).get(reason)
    if attrs is None:
        raise ClassifyError("kanonik kod tanımsız: %s" % reason)
    out = {k: v for k, v in attrs.items() if not k.startswith("$") and k != "desc"}
    out["reason_code"] = reason
    out["is_fallback"] = bool(out.get("is_fallback", False) or is_fallback)
    out["source"] = source
    out["raw_code"] = str(code)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# validate
# ─────────────────────────────────────────────────────────────────────────────
def _scan_secrets(obj):
    hits = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
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
    CAT = set(enums.get("category", []))
    STATUS = set(enums.get("terminal_status", []))
    OUTCOME = set(enums.get("outcome", []))
    PARTY = set(enums.get("party", []))
    EVENT = set(enums.get("event_type", []))
    DIRECTION = set(enums.get("direction", []))

    _check(spec.get("taxonomy_version"), "taxonomy_version mevcut (R12)")
    _check(CAT and STATUS and OUTCOME and PARTY and EVENT and DIRECTION,
           "enum kapalı kümeleri tanımlı")
    _check(STATUS == {"completed", "transferred", "failed"},
           "R2 terminal_status = call.status API §6 ile birebir")

    ends = _end_codes(spec)
    starts = _start_codes(spec)
    _check(len(ends) >= 20, "end_reasons ≥20 kanonik kod")
    _check(len(starts) >= 4, "start_reasons ≥4 kanonik kod")

    # ── R12: kod adı regex + tekillik + append-only disiplin
    all_names = list(ends.keys()) + list(starts.keys())
    _check(all(CODE_RE.match(n) for n in all_names), "R12 tüm kod adları regex ^[a-z][a-z0-9_]+$")
    _check(len(all_names) == len(set(all_names)), "R12 kod adları tekil (start+end ayrık)")

    # ── R1: start kodları direction taşır
    for n, a in starts.items():
        _check(a.get("direction") in DIRECTION, "R1 start %s direction geçerli" % n)

    # ── R1/R2/R3/R7/R11: her bitiş kodu tam nitelik kümesi + kapalı kümeler
    for n, a in ends.items():
        _check(a.get("category") in CAT, "R1 %s category geçerli" % n)
        _check(a.get("terminal_status") in STATUS, "R2 %s terminal_status geçerli" % n)
        _check(a.get("outcome") in OUTCOME, "R2 %s outcome geçerli" % n)
        _check(a.get("party") in PARTY, "R3 %s party geçerli" % n)
        _check(isinstance(a.get("billable"), bool), "R3 %s billable boolean" % n)
        _check(isinstance(a.get("retryable"), bool), "R3 %s retryable boolean" % n)
        _check(a.get("event_type") in EVENT, "R11 %s event_type geçerli" % n)
        et = a.get("error_taxonomy")
        _check(et is None or et in ERROR_TAXONOMY, "R7 %s error_taxonomy null|API §11.6" % n)
        # R2: status↔event_type tutarlılığı
        st = a.get("terminal_status")
        ev = a.get("event_type")
        ok_map = (st == "completed" and ev == "call.completed") or \
                 (st == "transferred" and ev == "call.transferred") or \
                 (st == "failed" and ev == "call.failed")
        _check(ok_map, "R11 %s status↔event_type tutarlı" % n)

    # ── R4: signal_map her hedefi tanımlı bir end koduna çözülür + 'unknown' fallback var
    _check("unknown" in ends and ends["unknown"].get("is_fallback") is True,
           "R4 'unknown' fallback kodu mevcut + is_fallback")
    smap = _signal_map(spec)
    _check(set(smap.keys()) >= {"sip", "q850", "cpaas", "internal"},
           "R4 signal_map 4 kaynağı (sip/q850/cpaas/internal) kapsar")
    orphan = []
    for src, table in smap.items():
        for k, v in table.items():
            if k.startswith("$"):
                continue
            if v not in ends:
                orphan.append("%s.%s→%s" % (src, k, v))
    _check(not orphan, "R4 signal_map tüm hedefleri tanımlı koda çözülür (%s)" % (orphan[:3] or "—"))

    # ── R5/R6: compliance kategorisi disiplini
    comp = [n for n, a in ends.items() if a.get("category") == "compliance"]
    _check(len(comp) >= 3, "R5 ≥3 compliance kodu (dnc/consent/time_window)")
    for n in comp:
        a = ends[n]
        _check(a.get("billable") is False and a.get("terminal_status") == "failed",
               "R5 %s billable=false + status=failed" % n)
        _check(a.get("outcome") == "blocked", "R5 %s outcome=blocked" % n)
    _check(ends.get("blocked_dnc", {}).get("retryable") is False
           and ends.get("blocked_consent_missing", {}).get("retryable") is False,
           "R6 dnc + consent retryable=false")
    _check(ends.get("blocked_time_window", {}).get("retryable") is True,
           "R6 time_window retryable=true (yeniden zamanla)")

    # ── R7: normal/contained ve voicemail kodları error_taxonomy=null
    for n, a in ends.items():
        if a.get("category") == "normal" or n in ("voicemail_left", "voicemail_machine_detected"):
            _check(a.get("error_taxonomy") is None, "R7 %s error_taxonomy=null" % n)
        elif a.get("category") in ("failed", "compliance") or n in ("busy", "rejected", "no_answer", "dropped_mid_call"):
            _check(a.get("error_taxonomy") in ERROR_TAXONOMY, "R7 %s error_taxonomy zorunlu" % n)

    # ── R8: retryable disiplini — normal kapanış + transfer asla retryable değil
    for n, a in ends.items():
        if a.get("category") == "normal":
            _check(a.get("retryable") is False, "R8 normal %s retryable=false" % n)

    # ── R9: voicemail semantiği (FR-TEL-010/011)
    vl = ends.get("voicemail_left", {})
    _check(vl.get("billable") is True and vl.get("outcome") == "voicemail",
           "R9 voicemail_left billable + outcome=voicemail")
    vm = ends.get("voicemail_machine_detected", {})
    _check(vm.get("outcome") == "no_contact" and vm.get("retryable") is True,
           "R9 voicemail_machine_detected no_contact + retryable")

    # ── R10: silent/abandoned ölçülebilir kod (FR-TEL-015)
    ab = ends.get("abandoned_no_capacity", {})
    _check(ab.get("category") == "abandoned" and ab.get("billable") is False,
           "R10 abandoned_no_capacity (silent) mevcut + faturalanmaz")

    # ── R13: residency + pii + literal sır
    _check(spec.get("residency", {}).get("region_pin_required") is True, "R13 residency region pin")
    pii = spec.get("pii", {})
    _check(pii.get("reason_code_pii_class") == "none"
           and pii.get("phone_number_in_code_forbidden") is True
           and pii.get("raw_signal_in_code_forbidden") is True,
           "R13 neden kodu PII içermez (pii_class=none)")
    hits = _scan_secrets(spec)
    if os.path.exists(PROVIDER_CFG):
        hits += _scan_secrets(_load(PROVIDER_CFG))
    _check(not hits, "R13 literal sır yok (spec+config)")

    # ── invariant kataloğu bütünlüğü
    inv = spec.get("invariants", [])
    inv_ids = [i.get("id") for i in inv]
    _check(len(inv_ids) == len(set(inv_ids)) and len(inv_ids) >= 13,
           "invariant kataloğu ≥13 + tekil ID")
    _check(all(i.get("trace") for i in inv), "her invariant trace taşır")

    # ── config: sağlayıcı eşlemeleri tanımlı koda çözülür (≥2 sağlayıcı, vendor-neutral)
    if os.path.exists(PROVIDER_CFG):
        cfg = _load(PROVIDER_CFG)
        provs = cfg.get("providers", [])
        _check(len(provs) >= 2, "config ≥2 sağlayıcı (vendor-neutral)")
        names = [p.get("name") for p in provs]
        _check(len(names) == len(set(names)), "config sağlayıcı isimleri tekil")
        cfg_orphan = []
        for p in provs:
            _check(p.get("source") in smap, "config %s source geçerli" % p.get("name"))
            for k, v in p.get("status_map", {}).items():
                if v not in ends:
                    cfg_orphan.append("%s.%s→%s" % (p.get("name"), k, v))
        _check(not cfg_orphan, "config eşlemeleri tanımlı koda çözülür (%s)" % (cfg_orphan[:3] or "—"))
        # en az bir managed (M1) + bir ham SIP (M2) → adaptör simetrisi
        modes = {p.get("mode") for p in provs}
        _check({"M1", "M2"} <= modes, "config M1 (managed) + M2 (byoc) modlarını kapsar")

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
    source = sample.get("source")
    code = sample.get("code")
    if source is None or code is None:
        print("classify: sample 'source' ve 'code' içermeli")
        return 2

    res = classify(spec, source, code)
    print("sinyal: %s/%s → kod: %s" % (source, code, res["reason_code"]))
    print("  category=%s status=%s outcome=%s party=%s" % (
        res["category"], res["terminal_status"], res["outcome"], res["party"]))
    print("  billable=%s retryable=%s event=%s taxonomy=%s%s" % (
        res["billable"], res["retryable"], res["event_type"], res.get("error_taxonomy"),
        "  [FALLBACK]" if res["is_fallback"] else ""))

    gate_ok = True
    # Eşlenmeyen sinyal → taksonomi boşluğu; sample açıkça izin vermedikçe kapı eler (R4)
    if res["is_fallback"] and not sample.get("allow_unknown", False):
        print("  ✗ eşlenmeyen sinyal 'unknown'a düştü — taksonomi boşluğu (R4)")
        gate_ok = False

    exp = sample.get("expect", {})
    for field in ("reason_code", "category", "terminal_status", "outcome", "party",
                  "billable", "retryable", "event_type", "error_taxonomy", "is_fallback"):
        if field in exp:
            got = res.get(field)
            if got != exp[field]:
                print("  ✗ expect.%s=%r ama got=%r" % (field, exp[field], got))
                gate_ok = False

    print("classify: %s" % ("PASS ✅" if gate_ok else "FAIL ❌"))
    return 0 if gate_ok else 1


def cmd_lookup(code):
    spec = _load(SPEC_PATH)
    for kind, codes in (("end", _end_codes(spec)), ("start", _start_codes(spec))):
        if code in codes:
            a = {k: v for k, v in codes[code].items() if not k.startswith("$")}
            print("[%s] %s" % (kind, code))
            for k, v in a.items():
                print("  %s = %s" % (k, v))
            return 0
    print("kod bulunamadı: %s" % code)
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True


def selftest():
    spec = _load(SPEC_PATH)
    cases = []

    def case(ok, label):
        cases.append((bool(ok), label))

    # 1) validate iyi spec+config'te geçer
    case(_validate_obj(spec) == 0, "validate iyi spec+config'te 0 döndürür")

    # ── sınıflama doğruluğu (signal_map) ────────────────────────────────────────
    case(resolve_signal(spec, "sip", "486")[0] == "busy", "SIP 486 → busy")
    case(resolve_signal(spec, "sip", "BYE")[0] == "completed_caller_hangup", "SIP BYE → completed")
    case(resolve_signal(spec, "q850", "17")[0] == "busy", "Q.850 #17 → busy")
    case(resolve_signal(spec, "q850", "16")[0] == "completed_caller_hangup", "Q.850 #16 → completed")
    case(resolve_signal(spec, "cpaas", "no-answer")[0] == "no_answer", "CPaaS no-answer → no_answer")
    case(resolve_signal(spec, "cpaas", "NO-ANSWER")[0] == "no_answer", "CPaaS NO-ANSWER (case-insens) → no_answer")
    case(resolve_signal(spec, "internal", "transfer_initiated")[0] == "transfer_to_human",
         "internal transfer_initiated → transfer_to_human")
    case(resolve_signal(spec, "internal", "dnc_hit")[0] == "blocked_dnc", "internal dnc_hit → blocked_dnc")

    # ── R4: eşlenmeyen sinyal → unknown fallback + flag (sessiz yutma yok)
    r, fb = resolve_signal(spec, "sip", "699")
    case(r == "unknown" and fb is True, "R4 eşlenmeyen SIP 699 → unknown + fallback flag")
    r, fb = resolve_signal(spec, "weird_source", "x")
    case(r == "unknown" and fb is True, "R4 bilinmeyen kaynak → unknown + fallback flag")

    # ── classify tam nitelik kümesi getirir
    c = classify(spec, "sip", "486")
    case(c["category"] == "no_contact" and c["retryable"] is True and c["billable"] is False
         and c["error_taxonomy"] == "UNAVAILABLE", "classify SIP 486 nitelikleri (busy)")
    c = classify(spec, "internal", "dnc_hit")
    case(c["category"] == "compliance" and c["billable"] is False and c["retryable"] is False
         and c["outcome"] == "blocked", "R5/R6 classify dnc_hit (compliance, kalıcı engel)")
    c = classify(spec, "internal", "transfer_initiated")
    case(c["terminal_status"] == "transferred" and c["event_type"] == "call.transferred"
         and c["retryable"] is False, "R8/R11 classify transfer (transferred, retryable=false)")
    c = classify(spec, "internal", "voicemail_dropped")
    case(c["outcome"] == "voicemail" and c["billable"] is True, "R9 classify voicemail_left")
    c = classify(spec, "internal", "no_agent_capacity")
    case(c["category"] == "abandoned" and c["billable"] is False and c["retryable"] is True,
         "R10 classify abandoned_no_capacity (silent)")

    # ── R8: hiçbir normal kapanış retryable değil
    ends = _end_codes(spec)
    case(all(a.get("retryable") is False for a in ends.values() if a.get("category") == "normal"),
         "R8 normal kapanış kodları retryable=false")

    # ── R7: failed kodları error_taxonomy taşır, normal taşımaz
    case(ends["network_failure"]["error_taxonomy"] in ERROR_TAXONOMY
         and ends["completed_caller_hangup"]["error_taxonomy"] is None,
         "R7 failed taxonomy taşır / normal null")

    # ── negatif kapı kanıtı: bozuk spec'ler validate'i elemeli ─────────────────
    bad = json.loads(json.dumps(spec))
    bad["end_reasons"]["codes"]["blocked_dnc"]["billable"] = True  # R5 ihlali
    case(_validate_obj(bad) == 1, "negatif: compliance billable=true → validate eler (R5)")

    bad = json.loads(json.dumps(spec))
    bad["end_reasons"]["codes"]["completed_caller_hangup"]["retryable"] = True  # R8 ihlali
    case(_validate_obj(bad) == 1, "negatif: normal retryable=true → validate eler (R8)")

    bad = json.loads(json.dumps(spec))
    bad["signal_map"]["sip"]["486"] = "no_such_code"  # R4 orphan
    case(_validate_obj(bad) == 1, "negatif: signal_map orphan hedef → validate eler (R4)")

    bad = json.loads(json.dumps(spec))
    del bad["end_reasons"]["codes"]["unknown"]  # R4 fallback yok
    case(_validate_obj(bad) == 1, "negatif: 'unknown' fallback silinince → validate eler (R4)")

    bad = json.loads(json.dumps(spec))
    bad["end_reasons"]["codes"]["network_failure"]["error_taxonomy"] = "NOT_A_CATEGORY"  # R7
    case(_validate_obj(bad) == 1, "negatif: taksonomi-dışı error_taxonomy → validate eler (R7)")

    bad = json.loads(json.dumps(spec))
    bad["end_reasons"]["codes"]["transfer_to_human"]["event_type"] = "call.completed"  # R11 tutarsız
    case(_validate_obj(bad) == 1, "negatif: status↔event uyumsuz → validate eler (R11)")

    bad = json.loads(json.dumps(spec))
    bad["pii"]["phone_number_in_code_forbidden"] = False  # R13
    case(_validate_obj(bad) == 1, "negatif: PII koruması kapalı → validate eler (R13)")

    bad = json.loads(json.dumps(spec))
    bad["end_reasons"]["codes"]["voicemail_left"]["billable"] = False  # R9
    case(_validate_obj(bad) == 1, "negatif: voicemail_left billable=false → validate eler (R9)")

    bad = json.loads(json.dumps(spec))
    bad["end_reasons"]["codes"]["X bad code"] = dict(bad["end_reasons"]["codes"]["busy"])  # R12 regex
    case(_validate_obj(bad) == 1, "negatif: geçersiz kod adı → validate eler (R12)")

    # ── classify gate: fallback sample (allow_unknown yok) eler
    class _Tmp:
        pass
    # doğrudan classify mantığı: is_fallback ve allow_unknown yok → fail
    res = classify(spec, "sip", "699")
    case(res["is_fallback"] is True, "classify gate: eşlenmeyen → is_fallback (kapı eler)")

    passed = sum(1 for ok, _ in cases if ok)
    total = len(cases)
    for ok, label in cases:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("selftest: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


# ─────────────────────────────────────────────────────────────────────────────
# schema
# ─────────────────────────────────────────────────────────────────────────────
def schema():
    print(__doc__)
    print("Beklenen spec şekli (reason-codes-spec.json):")
    print("  taxonomy_version            : str (append-only kararlılık, R12)")
    print("  enums                       : category/terminal_status/outcome/party/event_type/direction (kapalı küme)")
    print("  start_reasons.codes{}       : {direction, desc, trace}                    (FR-TEL-012 başlangıç)")
    print("  end_reasons.codes{}         : {category, terminal_status, outcome, party,")
    print("                                 billable, retryable, event_type,")
    print("                                 error_taxonomy|null, [is_fallback], desc}  (FR-TEL-012 bitiş)")
    print("  signal_map{sip,q850,cpaas,internal} : yerel sinyal → kanonik bitiş kodu  (R4)")
    print("  residency / pii             : region pin + neden kodu PII içermez         (R13)")
    print("  invariants[]                : R1..R13 (id/desc/trace)")
    print("classify sample şekli: {source, code, [allow_unknown], [expect:{...}]}")
    return 0


def main(argv):
    if len(argv) < 2:
        print("kullanım: reason_codes_probe.py {validate|classify <sample>|lookup <code>|selftest|schema}")
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return cmd_validate()
    if cmd == "classify":
        if len(argv) < 3:
            print("classify: <sample.json> gerekli")
            return 2
        return cmd_classify(argv[2])
    if cmd == "lookup":
        if len(argv) < 3:
            print("lookup: <code> gerekli")
            return 2
        return cmd_lookup(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
