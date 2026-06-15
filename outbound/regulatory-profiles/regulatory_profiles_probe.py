#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.5 — İYS/ETK (TR) + PECR/Ofcom (UK) profil parametreleri referans probe.

10. workstream'in (Outbound) Consent & uyumluluk motoru alt-bloğunun PROFİL PARAMETRE modülü ve
F2-Must outbound yeteneği. BRD §14.3 ("Türkiye için İYS izin kaydı ve ETK; UK için ilgili PECR/Ofcom
kuralları dikkate alınmalıdır") adı geçen iki rejim için outbound uyumluluk parametrelerinin TAM/BİRLEŞİK
setinin AUTHORITATIVE TEK kaynağı + sürüklenme (drift) denetçisi. 10.2.1 consent / 10.2.2 DNC /
10.2.3 arama saati / 10.2.4 kapasite kardeş modüllerinin TÜKETTİĞİ cp.outbound.* değerlerinin master'ı.

Modül per-call KARAR vermez (10.2.1–10.2.4) ve profile ÇÖZÜMLEME yapmaz (most-restrictive-wins /
tenant-override = DPIA §5/SAD §19.3); BRD §14.3 parametre setini SAHİPLENİR ve üç şeyi GARANTİ eder:

  (P2–P8) named-regime profilleri TAM + düzenleyici köken (provenance) + her regime-özgü yükümlülük
          parametre değerleriyle KARŞILANIR:
            TR: İYS zorunlu (P2) ∧ ETK opt_in + B2B-dahil (P3)
            UK: PECR soft-opt-in (P4) ∧ TPS-CTPS (P5) ∧ Ofcom abandoned ≤%3 (P6) ∧ CLI (P7) ∧ ≤2sn mesaj (P8)
  (P10)   tüketici config'leri (10.2.1–10.2.4) master ile SÜRÜKLENMEZ (crosscheck)
  (P11)   tenant override yalnız-SIKILAŞTIRIR (monotonluk; gevşetme YASAK)

Kullanım:
  regulatory_profiles_probe.py validate          Statik spec/config/kapsama + crosscheck kapısı → çıkış kodu
  regulatory_profiles_probe.py check <sample>     Profil parametre motoru: senaryo(lar) → kapı (P1–P12)
  regulatory_profiles_probe.py crosscheck         Tüketici config sürüklenme denetimi (P10) → kapı
  regulatory_profiles_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  regulatory_profiles_probe.py schema             Karar/parametre sözleşmesini yazdır

Determinizm: config çözümü + parametre karşılaştırması; Date.now/random YOK. Stdlib-only. Sır/credential
ve gerçek PII (müşteri adı/telefon/MSISDN/hesap) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SPEC_PATH = os.path.join(HERE, "regulatory-profiles-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "regulatory-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["COMPLIANT", "VIOLATION"]
TERMINAL = {"COMPLIANT", "VIOLATION"}
NAMED_REGIMES = ["PROFILE-TR", "PROFILE-UK"]
SUBOBJECTS = ["consent", "suppression", "calling_hours", "capacity", "obligations"]
OFCOM_ABANDON_MAX = 0.03
OFCOM_INFO_MAX_SECONDS = 2

INVARIANT_IDS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12"]
CHANNEL = "voice"

# Degrade (inject) — DOĞRU parametre garantilerini bozan müdahaleler (her biri bir invariant'ı eler).
INJECTIONS = {"drop_iys", "etk_b2b_exempt", "tr_optout", "pecr_to_optout", "drop_tps_ctps",
              "raise_abandon", "drop_cli", "drop_info_message", "drop_provenance",
              "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "incomplete_profile", "iys_registry_missing", "etk_b2b_loosened", "pecr_model_violated",
    "pecr_registry_missing", "ofcom_abandon_exceeded", "ofcom_cli_missing", "ofcom_info_message_missing",
    "missing_provenance", "drift_detected", "override_loosened", "missing_audit", "cross_tenant",
    "secret_or_pii", "stuck_state",
]

# tenant override parametresinin profilde yaşadığı alt-obje (P11 _locate).
PARAM_HOME = {
    "silent_call_threshold": "capacity", "max_overdial_ratio": "capacity", "reserve_min": "capacity",
    "consent_model": "consent", "consent_registry": "consent", "b2b_exemption": "consent",
    "consent_validity_days": "consent", "recognized_sources": "consent", "soft_basis_allowed": "consent",
    "cli_presentation_required": "obligations", "abandoned_info_message_required": "obligations",
    "info_message_within_seconds": "obligations", "ai_disclosure_required": "obligations",
    "timezone": "calling_hours", "utc_offset_minutes": "calling_hours",
    "allowed_window": "calling_hours", "allowed_weekdays": "calling_hours",
    "registry": "suppression", "realtime_required": "suppression", "required_sources": "suppression",
}
MODEL_RANK = {"opt_in": 2, "soft_opt_in": 1, "opt_out": 0}
_MISSING = object()

# Liste-değerli alanlar küme olarak karşılaştırılır (sıra önemsiz).
SET_FIELDS = {"recognized_sources", "required_sources", "allowed_weekdays"}

# ── Sızıntı tarayıcı (P12; 10.2.x deseniyle) — müşteri adı/telefon/MSISDN/hesap no yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|msisdn_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|corr-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu + ISO tarihi eler (10.2.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"desc"' in line or '"trace"' in line or '"rule"' in line \
                        or '"provenance"' in line or '"$comment"' in stripped:
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
# Deterministik yardımcılar (Date.now/random YOK).
# ════════════════════════════════════════════════════════════════════════════
def _resolve_profile(sample, cfg):
    """country/profile_id → master profil. Açık profile_id öncelikli; yoksa country eşleşmesi; yoksa None."""
    profiles = cfg.get("profiles", {})
    pid = sample.get("profile_id")
    if pid and pid in profiles:
        return pid, profiles[pid]
    country = sample.get("country")
    for name, prof in profiles.items():
        if prof.get("country") == country:
            return name, prof
    return None, None


def _dotted(obj, path):
    """'consent.consent_model' → obj['consent']['consent_model']; yoksa _MISSING."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _locate(prof, param):
    """tenant override param → profildeki güncel master değeri (yoksa _MISSING)."""
    home = PARAM_HOME.get(param)
    if home is None:
        return _MISSING
    return (prof.get(home, {}) or {}).get(param, _MISSING)


def _tightens(param, master_val, ov_val):
    """P11 — tenant override değeri master'a göre SIKILAŞTIRIYOR mu? (yalnız-sıkılaştırır; gevşetme YASAK)."""
    cfg = _load(CONFIG_PATH)
    direction = cfg.get("tightening_direction", {}).get(param)
    if direction == "lower":
        return _num(ov_val) <= _num(master_val)
    if direction == "higher":
        return _num(ov_val) >= _num(master_val)
    if direction == "false_strict":          # false daha sıkı: perm(false)=0,perm(true)=1
        return int(bool(ov_val)) <= int(bool(master_val))
    if direction == "true_strict":           # true daha sıkı
        return int(bool(ov_val)) >= int(bool(master_val))
    if direction == "model_rank":            # opt_in>soft_opt_in>opt_out
        return MODEL_RANK.get(ov_val, -1) >= MODEL_RANK.get(master_val, 99)
    if direction == "window_narrow":         # pencere yalnız daralabilir
        try:
            return ov_val.get("start", "") >= master_val.get("start", "") \
                and ov_val.get("end", "zz") <= master_val.get("end", "zz")
        except AttributeError:
            return False
    if direction == "weekday_subset":        # günler yalnız alt-küme
        try:
            return set(ov_val).issubset(set(master_val))
        except TypeError:
            return False
    return False                              # bilinmeyen param/yön → muhafazakâr: gevşetme say


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("inf")


def _values_equal(field, a, b):
    if field in SET_FIELDS:
        try:
            return set(a or []) == set(b or [])
        except TypeError:
            return a == b
    return a == b


# ════════════════════════════════════════════════════════════════════════════
def build(sample, spec, inject=None, cfg=None):
    """Tek profil parametre denetim senaryosunu yürüt → ProfileDecision + ihlal sayaçları.

    Motor DOĞRU parametre garantilerini değerlendirir; inject (degrade) bir garantiyi bozar ve eşleşen
    ihlal sayacını artırır (10.2.x inject deseniyle birebir). tenant_override yalnız-sıkılaştırır (P11)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _load(CONFIG_PATH)

    tenant = sample.get("tenant_id")
    request_id = sample.get("request_id")
    v = {k: 0 for k in VIOLATION_KEYS}

    # ── P12 (tenant izolasyonu) ──
    bind_tenant = sample.get("bind_tenant")
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if bind_tenant and bind_tenant != tenant:
        v["cross_tenant"] += 1

    resolved_profile, master_prof = _resolve_profile(sample, cfg)
    country = (master_prof or {}).get("country") if master_prof else sample.get("country")

    obligations_eval = {}
    if master_prof is None:
        # P1 — profil çözülemedi (bilinmeyen ülke/regime).
        v["incomplete_profile"] += 1
        terminal = "VIOLATION"
    else:
        prof = copy.deepcopy(master_prof)

        # ── P11 (tenant override yalnız-sıkılaştırır) — pristine master değerlerine göre ──
        ov = sample.get("tenant_override") or {}
        override_eval = {}
        for param, val in ov.items():
            cur = _locate(prof, param)
            if cur is _MISSING:
                override_eval[param] = "unknown_param→loosen"
                v["override_loosened"] += 1
                continue
            ok = _tightens(param, cur, val)
            override_eval[param] = "tighten" if ok else "loosen"
            if not ok:
                v["override_loosened"] += 1

        # ── inject (degrade) — doğru parametreyi gevşet ──
        if "drop_iys" in inject:
            prof.setdefault("consent", {})["consent_registry"] = "none"
        if "etk_b2b_exempt" in inject:
            prof.setdefault("consent", {})["b2b_exemption"] = True
        if "tr_optout" in inject:
            prof.setdefault("consent", {})["consent_model"] = "opt_out"
        if "pecr_to_optout" in inject:
            prof.setdefault("consent", {})["consent_model"] = "opt_out"
        if "drop_tps_ctps" in inject:
            prof.setdefault("consent", {})["consent_registry"] = "none"
            prof.setdefault("suppression", {})["registry"] = "none"
        if "raise_abandon" in inject:
            prof.setdefault("capacity", {})["silent_call_threshold"] = 0.05
        if "drop_cli" in inject:
            prof.setdefault("obligations", {})["cli_presentation_required"] = False
        if "drop_info_message" in inject:
            prof.setdefault("obligations", {})["abandoned_info_message_required"] = False
        if "drop_provenance" in inject:
            prof.pop("provenance", None)

        # ── P1 tamlık ──
        for so in SUBOBJECTS:
            if not isinstance(prof.get(so), dict) or not prof.get(so):
                v["incomplete_profile"] += 1

        # ── P9 düzenleyici köken (provenance) ──
        if not prof.get("provenance"):
            v["missing_provenance"] += 1

        # ── P2–P8 regime-özgü yükümlülükler ──
        obligations_eval = _eval_obligations(prof, country, v)

        terminal = "VIOLATION" if any(x > 0 for x in v.values()) else "COMPLIANT"

    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (P9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "resolved_profile": resolved_profile,
        "data_protection_regime": (master_prof or {}).get("data_protection_regime"),
        "marketing_regime": (master_prof or {}).get("marketing_regime"),
        "obligations": obligations_eval,
        "terminal": terminal,
    }

    # ── Audit (P12) ── (ham PII YOK — yalnız enum/kimlik)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "result": terminal,
            "request_id": request_id,
            "regime": (master_prof or {}).get("marketing_regime"),
            "resolved_profile": resolved_profile,
            "country": country,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "compliant": terminal == "COMPLIANT",
        "resolved_profile": resolved_profile,
        "country": country,
        "obligations": obligations_eval,
        "evidence": evidence,
        "audit": audit,
        "violations": {k: v[k] for k in VIOLATION_KEYS},
    }


def _eval_obligations(prof, country, v):
    """Regime-özgü yükümlülükleri parametre değerleriyle değerlendir; ihlali sayaca yaz. (P2–P8)"""
    consent = prof.get("consent", {}) or {}
    supp = prof.get("suppression", {}) or {}
    cap = prof.get("capacity", {}) or {}
    obl = prof.get("obligations", {}) or {}
    out = {}
    if country == "TR":
        iys = consent.get("consent_registry") == "IYS" and supp.get("realtime_required") is True
        out["iys_registry"] = "ok" if iys else "fail"
        if not iys:
            v["iys_registry_missing"] += 1
        etk = consent.get("consent_model") == "opt_in" and consent.get("b2b_exemption") is False
        out["etk_optin_b2b"] = "ok" if etk else "fail"
        if not etk:
            v["etk_b2b_loosened"] += 1
    elif country == "UK":
        pecr = (consent.get("consent_model") == "soft_opt_in" and consent.get("soft_basis_allowed") is True
                and "existing_customer" in (consent.get("recognized_sources") or []))
        out["pecr_soft_optin"] = "ok" if pecr else "fail"
        if not pecr:
            v["pecr_model_violated"] += 1
        reg = consent.get("consent_registry") == "TPS_CTPS" and supp.get("realtime_required") is True
        out["pecr_tps_ctps"] = "ok" if reg else "fail"
        if not reg:
            v["pecr_registry_missing"] += 1
        thr = cap.get("silent_call_threshold")
        ab_ok = isinstance(thr, (int, float)) and thr <= OFCOM_ABANDON_MAX
        out["ofcom_abandon"] = "ok" if ab_ok else "fail"
        if not ab_ok:
            v["ofcom_abandon_exceeded"] += 1
        cli_ok = obl.get("cli_presentation_required") is True
        out["ofcom_cli"] = "ok" if cli_ok else "fail"
        if not cli_ok:
            v["ofcom_cli_missing"] += 1
        secs = obl.get("info_message_within_seconds")
        info_ok = obl.get("abandoned_info_message_required") is True \
            and isinstance(secs, (int, float)) and secs <= OFCOM_INFO_MAX_SECONDS
        out["ofcom_info_message"] = "ok" if info_ok else "fail"
        if not info_ok:
            v["ofcom_info_message_missing"] += 1
    else:
        out["regime_specific"] = "none(baseline/illustrative)"
    return out


# ════════════════════════════════════════════════════════════════════════════
def crosscheck(spec=None, cfg=None, consumer_data=None, verbose=False):
    """P10 — tüketici config'lerinin (10.2.1–10.2.4) named-regime (TR/UK) değerleri master ile eşleşmeli.

    consumer_data verilirse {module: config_dict} bellek-içi kullanılır (test için); aksi halde
    config.consumer_modules path'lerinden (repo köküne göre) okunur. Dönen: drift listesi + sayım."""
    spec = spec if spec is not None else _load(SPEC_PATH)
    cfg = cfg if cfg is not None else _load(CONFIG_PATH)
    cf = spec.get("consumer_fields", {})
    paths = cfg.get("consumer_modules", {})
    named = cfg.get("named_regimes", NAMED_REGIMES)

    drift = []
    checked = 0
    for module, mapping in cf.items():
        if module.startswith("$") or not isinstance(mapping, dict):
            continue
        # tüketici config'i yükle
        if consumer_data and module in consumer_data:
            data = consumer_data[module]
        else:
            p = paths.get(module)
            if not p:
                drift.append({"module": module, "issue": "config path yok (consumer_modules)"})
                continue
            full = os.path.join(REPO_ROOT, p)
            if not os.path.exists(full):
                drift.append({"module": module, "issue": "config dosyası bulunamadı: %s" % p})
                continue
            data = _load(full)
        cprofs = data.get(mapping.get("config_profiles_key", "profiles"), {})

        for regime in named:
            master_prof = cfg.get("profiles", {}).get(regime)
            cprof = cprofs.get(regime)
            if master_prof is None or cprof is None:
                drift.append({"module": module, "regime": regime, "issue": "profil eksik (tüketici veya master)"})
                continue
            # regime etiketi: dp VEYA mkt rejiminden biriyle eşleşmeli
            ctag = cprof.get("regime")
            allowed = {master_prof.get("data_protection_regime"), master_prof.get("marketing_regime")}
            if ctag is not None and ctag not in allowed:
                drift.append({"module": module, "regime": regime, "field": "regime",
                              "consumer": ctag, "master": sorted(x for x in allowed if x)})
            # değer alanları
            for cfield, mpath in mapping.get("fields", {}).items():
                cval = cprof.get(cfield)
                mval = _dotted(master_prof, mpath)
                if mval is _MISSING:
                    drift.append({"module": module, "regime": regime, "field": cfield,
                                  "issue": "master path yok: %s" % mpath})
                    continue
                checked += 1
                if not _values_equal(cfield, cval, mval):
                    drift.append({"module": module, "regime": regime, "field": cfield,
                                  "consumer": cval, "master": mval})

    result = {"drift": drift, "drift_detected": len(drift), "checked": checked}
    if verbose:
        if drift:
            for d in drift:
                print("  ✗ DRIFT %s" % json.dumps(d, ensure_ascii=False, sort_keys=True))
        else:
            print("  ✓ %d named-regime alanı (TR/UK × 4 modül) sürüklenmesiz" % checked)
    return result


def crosscheck_cmd():
    spec = _load(SPEC_PATH)
    r = crosscheck(spec, verbose=True)
    ok = r["drift_detected"] == 0
    print("\ncrosscheck: %s (drift=%d, kontrol=%d alan)"
          % ("🟢 SÜRÜKLENME YOK" if ok else "🔴 SÜRÜKLENME TESPİT EDİLDİ", r["drift_detected"], r["checked"]))
    return 0 if ok else 1


# ════════════════════════════════════════════════════════════════════════════
def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "incomplete_profile": "max_incomplete_profile",
        "iys_registry_missing": "max_iys_registry_missing",
        "etk_b2b_loosened": "max_etk_b2b_loosened",
        "pecr_model_violated": "max_pecr_model_violated",
        "pecr_registry_missing": "max_pecr_registry_missing",
        "ofcom_abandon_exceeded": "max_ofcom_abandon_exceeded",
        "ofcom_cli_missing": "max_ofcom_cli_missing",
        "ofcom_info_message_missing": "max_ofcom_info_message_missing",
        "missing_provenance": "max_missing_provenance",
        "drift_detected": "max_drift_detected",
        "override_loosened": "max_override_loosened",
        "missing_audit": "max_missing_audit",
        "cross_tenant": "max_cross_tenant",
        "secret_or_pii": "max_secret_or_pii",
        "stuck_state": "max_stuck_state",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
    if gates.get("require_decision_record", True) and result["audit"] is None:
        fails.append("karar/audit kaydı üretilmedi (P12)")
    return (len(fails) == 0, fails)


def check_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = build(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "compliant", "resolved_profile"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s profil=%s ülke=%s" % (res["terminal"], res["resolved_profile"], res["country"]))
        if res["obligations"]:
            print("   yükümlülükler=%s" % res["obligations"])
        nz = {k: val for k, val in res["violations"].items() if val}
        if nz:
            print("   ihlaller: %s" % nz)
        if expect == "pass" and fails:
            print("   ✗ kapı eler (beklenen geçer): %s" % "; ".join(fails))
        if expect == "fail" and passed:
            print("   ✗ kapı GEÇTİ (beklenen eler — degrade senaryo)")
        if mism and expect == "pass":
            print("   ✗ karar uyuşmazlığı: %s" % "; ".join(mism))
        if expect == "fail" and not passed:
            print("   ✓ beklendiği gibi elendi: %s" % "; ".join(fails[:3]))

    print("\ncheck: %s" % ("🟢 TÜM SENARYOLAR BEKLENDİĞİ GİBİ" if all_ok else "🔴 EN AZ BİR SENARYO BEKLENMEDİK"))
    return 0 if all_ok else 1


# ════════════════════════════════════════════════════════════════════════════
def validate():
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    spec = _load(SPEC_PATH)

    # 1) Üst-düzey alanlar
    for f in ("wbs", "phase", "priority", "trace", "placement", "named_regimes", "obligations",
              "consumer_fields", "authorization", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=10.2.5", spec.get("wbs") == "10.2.5")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement data_authority=true", spec.get("placement", {}).get("data_authority") is True)

    # 2) İzlenebilirlik (BRD §14.3 birincil)
    tr = spec.get("trace", {})
    chk("BRD §14.3 izlenir (birincil)", any("§14.3" in s for s in tr.get("brd", [])))
    chk("SAD §19 country compliance profiles izlenir", any("§19" in s for s in tr.get("sad", [])))
    chk("SAD §19.3 profile çözümleme izlenir (delege)", any("§19.3" in s for s in tr.get("sad", [])))
    for fr in ("FR-OUT-003", "FR-OUT-004", "FR-OUT-006", "FR-TEL-013", "FR-TEL-014", "FR-TEL-015"):
        chk("%s izlenir (tüketici)" % fr, fr in tr.get("fr", []))
    chk("FR-TEN-002 + FR-REC-004 + FR-IAM-006 izlenir",
        all(x in tr.get("fr", []) for x in ("FR-TEN-002", "FR-REC-004", "FR-IAM-006")))
    chk("ADR-001/002/012 izlenir",
        all(any(a.startswith(x) for a in tr.get("adr", [])) for x in ("ADR-001", "ADR-002", "ADR-012")))
    chk("DPIA §5/§6 consumes", any("DPIA" in c for c in tr.get("consumes", [])))
    chk("consumed_by 10.2.1–10.2.4 + DPIA §5",
        all(any(m in c for c in tr.get("consumed_by", [])) for m in ("10.2.1", "10.2.2", "10.2.3", "10.2.4")))

    # 3) Named regimes — TR İYS/ETK + UK PECR/Ofcom
    nr = spec["named_regimes"]
    chk("PROFILE-TR named (KVKK/ETK/IYS)",
        nr.get("PROFILE-TR", {}).get("data_protection_regime") == "KVKK"
        and nr["PROFILE-TR"].get("marketing_regime") == "ETK"
        and nr["PROFILE-TR"].get("registry") == "IYS")
    chk("PROFILE-UK named (UK_GDPR/PECR_OFCOM/TPS_CTPS)",
        nr.get("PROFILE-UK", {}).get("data_protection_regime") == "UK_GDPR"
        and nr["PROFILE-UK"].get("marketing_regime") == "PECR_OFCOM"
        and nr["PROFILE-UK"].get("registry") == "TPS_CTPS")

    # 4) Obligations — P2–P8 her biri invariant + violation taşır
    obl = spec["obligations"]
    obl_inv = {o["invariant"] for o in obl.get("list", [])}
    chk("obligations P2–P8 tam", obl_inv == {"P2", "P3", "P4", "P5", "P6", "P7", "P8"})
    for o in obl.get("list", []):
        chk("obligation %s violation taşır" % o["id"], o.get("violation") in VIOLATION_KEYS)
    chk("ofcom_abandon_max=0.03", obl.get("ofcom_abandon_max") == OFCOM_ABANDON_MAX)
    chk("ofcom_info_message_max=2sn", obl.get("ofcom_info_message_max_seconds") == OFCOM_INFO_MAX_SECONDS)

    # 5) consumer_fields — 4 tüketici modül eşlemesi
    cf = spec["consumer_fields"]
    chk("consumer_fields 4 modül (consent/dnc/calling_hours/capacity)",
        {k for k in cf if not k.startswith("$")} == {"consent", "dnc", "calling_hours", "capacity"})
    for m, mp in cf.items():
        if m.startswith("$") or not isinstance(mp, dict):
            continue
        chk("consumer_fields %s alan eşlemesi taşır" % m, bool(mp.get("fields")))

    # 6) Kapılar — tüm sıfır-eşik
    g = spec["gates"]
    for gk in ("max_incomplete_profile", "max_iys_registry_missing", "max_etk_b2b_loosened",
               "max_pecr_model_violated", "max_pecr_registry_missing", "max_ofcom_abandon_exceeded",
               "max_ofcom_cli_missing", "max_ofcom_info_message_missing", "max_missing_provenance",
               "max_drift_detected", "max_override_loosened", "max_missing_audit", "max_cross_tenant",
               "max_secret_or_pii", "max_stuck_state"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal + require_decision_record", g.get("require_terminal") is True and g.get("require_decision_record") is True)

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("regprofile_drift_total metrik (P10 alarm)", "regprofile_drift_total" in obs.get("metrics", []))
    chk("regprofile_override_loosen_total metrik (P11 alarm)", "regprofile_override_loosen_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("regime/module/field DÜŞÜK kard (label uygun)",
        "regime" in lo and "module" in lo and "field" in lo)
    chk("tenant_id/correlation_id YÜKSEK kard (label değil)",
        "tenant_id" in hi and "correlation_id" in hi and "tenant_id" not in lo)
    chk("alarm drift/override-loosen ≤2dk", "drift" in obs.get("alarm", "") and "override" in obs.get("alarm", ""))

    # 8) İnvariant'lar P1–P12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar P1–P12 tam", inv_ids == INVARIANT_IDS)

    # 9) Config dosyası — named profil değerleri yükümlülükleri karşılar
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/regulatory-profiles.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        tr_p = profs.get("PROFILE-TR", {})
        uk_p = profs.get("PROFILE-UK", {})
        chk("config PROFILE-TR İYS/ETK (P2/P3)",
            tr_p.get("consent", {}).get("consent_registry") == "IYS"
            and tr_p.get("consent", {}).get("consent_model") == "opt_in"
            and tr_p.get("consent", {}).get("b2b_exemption") is False
            and tr_p.get("suppression", {}).get("realtime_required") is True)
        chk("config PROFILE-UK PECR soft-opt-in + TPS_CTPS (P4/P5)",
            uk_p.get("consent", {}).get("consent_model") == "soft_opt_in"
            and uk_p.get("consent", {}).get("soft_basis_allowed") is True
            and uk_p.get("consent", {}).get("consent_registry") == "TPS_CTPS"
            and "existing_customer" in uk_p.get("consent", {}).get("recognized_sources", []))
        chk("config PROFILE-UK Ofcom ≤%3 + CLI + ≤2sn (P6/P7/P8)",
            uk_p.get("capacity", {}).get("silent_call_threshold") <= OFCOM_ABANDON_MAX
            and uk_p.get("obligations", {}).get("cli_presentation_required") is True
            and uk_p.get("obligations", {}).get("abandoned_info_message_required") is True
            and uk_p.get("obligations", {}).get("info_message_within_seconds") <= OFCOM_INFO_MAX_SECONDS)
        chk("config named profiller TAM (5 alt-obje)",
            all(all(p.get(so) for so in SUBOBJECTS) for p in (tr_p, uk_p)))
        chk("config named profiller provenance taşır (P9)", bool(tr_p.get("provenance")) and bool(uk_p.get("provenance")))
        chk("config tightening_direction var (P11)", bool(cfg.get("tightening_direction")))
        chk("config consumer_modules 4 path",
            len([k for k in cfg.get("consumer_modules", {}) if not k.startswith("$")]) == 4)
        chk("config channel=voice", cfg.get("channel") == CHANNEL)

    # 10) crosscheck (P10) — canlı tüketici tutarlılığı
    cc = crosscheck(spec)
    chk("tüketici sürüklenmesi yok (P10): %d alan kontrol" % cc["checked"], cc["drift_detected"] == 0,
        json.dumps(cc["drift"][:2], ensure_ascii=False) if cc["drift"] else "")

    # 11) Sır/PII tarayıcı — spec + config + samples
    scan_files = [SPEC_PATH, CONFIG_PATH] + (
        [os.path.join(SAMPLES_DIR, f) for f in os.listdir(SAMPLES_DIR) if f.endswith(".json")]
        if os.path.isdir(SAMPLES_DIR) else [])
    total_leaks = 0
    for p in scan_files:
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8") as fh:
            hits = scan_leaks(fh.read())
        if hits:
            total_leaks += len(hits)
            chk("sızıntı yok: %s" % os.path.basename(p), False, str(hits[:2]))
    chk("hiç müşteri-PII/telefon/MSISDN/hesap-no/sır sızıntısı yok (P12)", total_leaks == 0)

    # 12) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
    if os.path.isdir(SAMPLES_DIR):
        sample_files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
        chk("≥1 pass + ≥1 fail örnek (degrade ispatı)", _has_both(sample_files))

    npass = sum(1 for _, ok, _ in checks if ok)
    for name, ok, detail in checks:
        line = ("  ✓ " if ok else "  ✗ ") + name
        if not ok and detail:
            line += "  → " + detail
        print(line)
    total = len(checks)
    print("\nvalidate: %d/%d %s" % (npass, total, "🟢" if npass == total else "🔴"))
    return 0 if npass == total else 1


def _has_both(sample_files):
    have_pass = have_fail = False
    for f in sample_files:
        s = _load(os.path.join(SAMPLES_DIR, f))
        if s.get("expect", "pass") == "pass":
            have_pass = True
        else:
            have_fail = True
    return have_pass and have_fail


# ════════════════════════════════════════════════════════════════════════════
def selftest():
    results = []

    def case(name, cond):
        results.append((bool(cond), name))

    spec = _load(SPEC_PATH)
    G = spec["gates"]

    def req(**kw):
        d = {"request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1", "profile_id": "PROFILE-TR"}
        d.update(kw)
        return d

    # 1) happy TR — İYS/ETK karşılanır → COMPLIANT
    r = build(req(), spec)
    case("happy-TR: COMPLIANT", r["terminal"] == "COMPLIANT")
    case("happy-TR: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy-TR: İYS ok", r["obligations"].get("iys_registry") == "ok")
    case("happy-TR: ETK ok", r["obligations"].get("etk_optin_b2b") == "ok")
    case("happy-TR: audit (P12)", r["audit"] is not None and r["audit"]["result"] == "COMPLIANT")
    case("happy-TR: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) happy UK — PECR/Ofcom karşılanır → COMPLIANT
    r = build(req(profile_id="PROFILE-UK"), spec)
    case("happy-UK: COMPLIANT", r["terminal"] == "COMPLIANT")
    case("happy-UK: PECR soft-opt-in ok", r["obligations"].get("pecr_soft_optin") == "ok")
    case("happy-UK: TPS_CTPS ok", r["obligations"].get("pecr_tps_ctps") == "ok")
    case("happy-UK: Ofcom abandon ok", r["obligations"].get("ofcom_abandon") == "ok")
    case("happy-UK: Ofcom CLI ok", r["obligations"].get("ofcom_cli") == "ok")
    case("happy-UK: Ofcom info ≤2sn ok", r["obligations"].get("ofcom_info_message") == "ok")

    # 3) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 4) P2 İYS düşür → iys_registry_missing
    r = build(req(), spec, inject=["drop_iys"])
    case("P2 drop_iys: iys_registry_missing>0", r["violations"]["iys_registry_missing"] > 0)
    case("P2 drop_iys: kapı eler", _gate_eval(r, G)[0] is False)

    # 5) P3 ETK B2B muafiyet aç → etk_b2b_loosened
    r = build(req(), spec, inject=["etk_b2b_exempt"])
    case("P3 etk_b2b_exempt: etk_b2b_loosened>0", r["violations"]["etk_b2b_loosened"] > 0)
    r = build(req(), spec, inject=["tr_optout"])
    case("P3 tr_optout: etk_b2b_loosened>0", r["violations"]["etk_b2b_loosened"] > 0)

    # 6) P4 PECR model boz → pecr_model_violated
    r = build(req(profile_id="PROFILE-UK"), spec, inject=["pecr_to_optout"])
    case("P4 pecr_to_optout: pecr_model_violated>0", r["violations"]["pecr_model_violated"] > 0)

    # 7) P5 TPS_CTPS düşür → pecr_registry_missing
    r = build(req(profile_id="PROFILE-UK"), spec, inject=["drop_tps_ctps"])
    case("P5 drop_tps_ctps: pecr_registry_missing>0", r["violations"]["pecr_registry_missing"] > 0)

    # 8) P6 abandoned eşik aş → ofcom_abandon_exceeded
    r = build(req(profile_id="PROFILE-UK"), spec, inject=["raise_abandon"])
    case("P6 raise_abandon: ofcom_abandon_exceeded>0", r["violations"]["ofcom_abandon_exceeded"] > 0)

    # 9) P7 CLI düşür → ofcom_cli_missing
    r = build(req(profile_id="PROFILE-UK"), spec, inject=["drop_cli"])
    case("P7 drop_cli: ofcom_cli_missing>0", r["violations"]["ofcom_cli_missing"] > 0)

    # 10) P8 bilgilendirme mesajı düşür → ofcom_info_message_missing
    r = build(req(profile_id="PROFILE-UK"), spec, inject=["drop_info_message"])
    case("P8 drop_info_message: ofcom_info_message_missing>0", r["violations"]["ofcom_info_message_missing"] > 0)

    # 11) P9 provenance düşür → missing_provenance
    r = build(req(), spec, inject=["drop_provenance"])
    case("P9 drop_provenance: missing_provenance>0", r["violations"]["missing_provenance"] > 0)

    # 12) P11 tenant override yalnız-sıkılaştırır
    r = build(req(tenant_override={"silent_call_threshold": 0.02}), spec)          # 0.02 < 0.03 → tighten
    case("P11 tighten threshold: ihlal yok", r["violations"]["override_loosened"] == 0)
    r = build(req(tenant_override={"silent_call_threshold": 0.05}), spec)          # 0.05 > 0.03 → loosen
    case("P11 loosen threshold: override_loosened>0", r["violations"]["override_loosened"] > 0)
    case("P11 loosen threshold: kapı eler", _gate_eval(r, G)[0] is False)
    r = build(req(profile_id="PROFILE-UK", tenant_override={"consent_model": "opt_in"}), spec)  # rank up → tighten
    case("P11 model tighten (soft_opt_in→opt_in): ihlal yok", r["violations"]["override_loosened"] == 0)
    r = build(req(tenant_override={"consent_model": "opt_out"}), spec)             # opt_in→opt_out → loosen
    case("P11 model loosen (opt_in→opt_out): override_loosened>0", r["violations"]["override_loosened"] > 0)
    r = build(req(profile_id="PROFILE-UK", tenant_override={"b2b_exemption": False}), spec)  # true→false → tighten
    case("P11 b2b tighten (true→false): ihlal yok", r["violations"]["override_loosened"] == 0)
    r = build(req(tenant_override={"b2b_exemption": True}), spec)                  # TR false→true → loosen
    case("P11 b2b loosen (false→true): override_loosened>0", r["violations"]["override_loosened"] > 0)
    r = build(req(profile_id="PROFILE-UK", tenant_override={"allowed_window": {"start": "09:00", "end": "19:00"}}), spec)
    case("P11 pencere daralt: ihlal yok", r["violations"]["override_loosened"] == 0)
    r = build(req(profile_id="PROFILE-UK", tenant_override={"allowed_window": {"start": "07:00", "end": "22:00"}}), spec)
    case("P11 pencere genişlet: override_loosened>0", r["violations"]["override_loosened"] > 0)
    r = build(req(tenant_override={"allowed_weekdays": [0, 1, 2, 3, 4]}), spec)    # subset → tighten
    case("P11 gün alt-küme: ihlal yok", r["violations"]["override_loosened"] == 0)
    r = build(req(tenant_override={"allowed_weekdays": [0, 1, 2, 3, 4, 5, 6]}), spec)  # superset → loosen
    case("P11 gün genişlet: override_loosened>0", r["violations"]["override_loosened"] > 0)
    r = build(req(tenant_override={"unknown_param": 1}), spec)
    case("P11 bilinmeyen param→loosen (muhafazakâr)", r["violations"]["override_loosened"] > 0)

    # 13) P12 cross_tenant + no_audit
    r = build(req(), spec, inject=["cross_tenant"])
    case("P12 cross_tenant inject", r["violations"]["cross_tenant"] > 0)
    r = build(req(bind_tenant="t-other"), spec)
    case("P12 bind mismatch → cross_tenant", r["violations"]["cross_tenant"] > 0)
    r = build(req(), spec, inject=["no_audit"])
    case("P12 no_audit: missing_audit>0", r["violations"]["missing_audit"] > 0 and r["audit"] is None)

    # 14) P1 bilinmeyen regime → incomplete_profile
    r = build(req(profile_id=None, country="ZZ"), spec)
    case("P1 bilinmeyen ülke → incomplete_profile>0", r["violations"]["incomplete_profile"] > 0)
    case("P1 bilinmeyen ülke → VIOLATION", r["terminal"] == "VIOLATION")

    # 15) P10 crosscheck — canlı tüketici tutarlı (drift=0)
    cc = crosscheck(spec)
    case("P10 crosscheck: canlı tüketici drift=0", cc["drift_detected"] == 0)
    case("P10 crosscheck: TR/UK × 4 modül alan kontrol", cc["checked"] >= 16)

    # 15b) P10 crosscheck — bellek-içi tampered tüketici → drift yakalanır
    cfg = _load(CONFIG_PATH)
    consent_cfg = _load(os.path.join(REPO_ROOT, cfg["consumer_modules"]["consent"]))
    tampered = copy.deepcopy(consent_cfg)
    tampered["profiles"]["PROFILE-TR"]["consent_model"] = "opt_out"   # ETK→opt_out drift
    cc2 = crosscheck(spec, cfg, consumer_data={"consent": tampered})
    case("P10 tampered consent (opt_out): drift>0", cc2["drift_detected"] > 0)
    tampered2 = copy.deepcopy(consent_cfg)
    tampered2["profiles"]["PROFILE-UK"]["consent_registry"] = "WRONG"  # registry drift
    cc3 = crosscheck(spec, cfg, consumer_data={"consent": tampered2})
    case("P10 tampered UK registry: drift>0", cc3["drift_detected"] > 0)
    cap_cfg = _load(os.path.join(REPO_ROOT, cfg["consumer_modules"]["capacity"]))
    tcap = copy.deepcopy(cap_cfg)
    tcap["profiles"]["PROFILE-UK"]["silent_call_threshold"] = 0.05    # Ofcom drift
    cc4 = crosscheck(spec, cfg, consumer_data={"capacity": tcap})
    case("P10 tampered UK abandon eşik: drift>0", cc4["drift_detected"] > 0)

    # 16) _tightens birim kontrolleri
    case("tighten lower true", _tightens("silent_call_threshold", 0.03, 0.02))
    case("tighten lower false", not _tightens("silent_call_threshold", 0.03, 0.05))
    case("tighten model_rank up", _tightens("consent_model", "soft_opt_in", "opt_in"))
    case("tighten model_rank down false", not _tightens("consent_model", "opt_in", "opt_out"))
    case("tighten false_strict ok", _tightens("b2b_exemption", True, False))
    case("tighten false_strict loosen", not _tightens("b2b_exemption", False, True))
    case("tighten true_strict ok", _tightens("cli_presentation_required", False, True) and _tightens("cli_presentation_required", True, True))
    case("tighten true_strict loosen", not _tightens("cli_presentation_required", True, False))

    # 17) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: enum temiz", scan_leaks('{"consent_model": "opt_in", "registry": "IYS"}') == [])
    case("leak: oran/saat temiz", scan_leaks('{"silent_call_threshold": 0.03, "utc_offset_minutes": 180}') == [])
    case("leak: customer_phone_value yakalanır", len(scan_leaks('{"customer_phone_value": "x"}')) > 0)
    case("leak: ham MSISDN yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "regulatory-profiles (WBS 10.2.5 — BRD §14.3 İYS/ETK [TR] + PECR/Ofcom [UK] profil parametreleri)",
        "role": "BRD §14.3 adı geçen iki rejim için outbound uyumluluk parametre setinin AUTHORITATIVE master'ı + "
                "tüketici sürüklenme (drift) denetçisi; per-call karar VERMEZ (10.2.1–10.2.4), profile ÇÖZÜMLEME YAPMAZ (DPIA §5/SAD §19.3)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "named_regimes": NAMED_REGIMES,
        "subobjects": SUBOBJECTS,
        "obligations": {
            "PROFILE-TR": ["İYS zorunlu (P2)", "ETK opt_in + B2B-dahil (P3)"],
            "PROFILE-UK": ["PECR soft-opt-in (P4)", "TPS-CTPS (P5)", "Ofcom abandoned ≤%3 (P6)",
                           "Ofcom CLI (P7)", "Ofcom bilgilendirme ≤2sn (P8)"],
        },
        "commands": {
            "validate": "statik spec/config/kapsama + crosscheck → çıkış kodu",
            "check <sample>": "profil parametre motoru senaryo(lar)ı → kapı (P1–P12)",
            "crosscheck": "tüketici config (10.2.1–10.2.4) sürüklenme denetimi (P10) → kapı",
            "selftest": "gömülü davranış kontrolleri",
            "schema": "bu sözleşme",
        },
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "profile_id?",
                           "country", "tenant_override{param: value}", "bind_tenant", "inject[]", "expect", "expected{}"],
        "tenant_override_params": sorted(PARAM_HOME.keys()),
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "compliant", "resolved_profile", "country", "obligations", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "BRD §14.3 (birincil), §14.2, §15; FR-OUT-003/004/006, FR-TEL-013/014/015, FR-TEN-002, FR-REC-004, FR-IAM-006; "
                 "SR-OUT-003/004/006, SR-TEL-013/014/015; SAD §19/§19.3/§12.3; DPIA §5.3 cp.outbound.* + §6 PROFILE-TR/UK; ADR-001/002/012",
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "check":
        if len(argv) < 3:
            print("kullanım: regulatory_profiles_probe.py check <sample.json|dizin>")
            return 2
        return check_cmd(argv[2])
    if cmd == "crosscheck":
        return crosscheck_cmd()
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
