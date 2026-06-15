#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.1.8 — A/B test kampanyaları referans probe.

10. workstream'in (Outbound) Kampanya Yönetimi alt-bloğunun A/B TEST modülü ve F2-Should outbound
yeteneği. FR-OUT-012 ('A/B test kampanyaları desteklenmelidir') + SR-OUT-012 (yöntem T — 'A/B test
kampanyaları desteklenir'; kabul: 'Varyant dağıtımı ve karşılaştırma yapılır') VARYANT DAĞITIM
(allocation) + VARYANT KARŞILAŞTIRMA (comparison) MOTORUNU sahiplenir. Modül bir DETERMİNİSTİK A/B
MOTORUdur:

  ABExperimentRequest ──yetki(campaign:manage) + geçerli config──► APPLIED
        │                                                            ├─ allocation: her contact → deterministik+sticky varyant (C4)
        │                                                            └─ comparison: iki-oran z-test → winner|inconclusive (C5)
        └──(yetkisiz / geçersiz config / cross-tenant)────────────► DENIED  (işlem yok — doğru reddetme, C2/C3/C7)

ÇEKİRDEK INVARIANT (SR-OUT-012): (1) VARYANT DAĞITIMI deterministik+sticky — her contact tam bir
TANIMLI varyanta düşer, gözlenen dağılım ağırlıkları tolerans içinde yansıtır, aynı contact tekrar→aynı
varyant (C4 misallocation=0); (2) VARYANT KARŞILAŞTIRMASI doğru — kazanan yalnız min_sample + anlamlılık
(alpha) ile beyan, aksi 'inconclusive' (C5 false_winner=0); A/B consent/DNC/saat uygunluğunu ATLAMAZ
(C8 eligibility_bypass=0); yalnız campaign:manage (C2); yalnız geçerli config (C3); idempotent (C6);
tenant izolasyonu (C7); her sonuç kanıt (C9) + audit (C10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): kampanya OLUŞTURMA → 10.1.1; CRM liste → 10.1.2; consent
ön-kontrol → 10.2/§19.1 (SONUCU tüketir); arama saatleri → 10.1.4; max deneme → 10.1.3; disposition
ÜRETİMİ → 10.1.5 (outcomes'ı tüketir); script versiyon DEPOSU → 10.1.6 (variant→version BAĞLAR);
durdurma → 10.1.7; dialer ÇEVİRME → 10.1.x (variant ATAR, çevirmez); audit store → 7.1.6/12.1.8;
rapor render → A-14; panel UI → L2 A-10.

Kullanım:
  ab_testing_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  ab_testing_probe.py run <sample>       A/B motoru: senaryo(lar)ı çalıştır → kapı (C1–C12)
  ab_testing_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  ab_testing_probe.py schema             Varyant/dağıtım/karşılaştırma sözleşmesini yazdır

Determinizm: hashlib tabanlı sticky atama + math.erfc z-test; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (müşteri adı/telefon/hesap no) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "ab-testing-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "ab-testing-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["APPLIED", "DENIED"]
TERMINAL = {"APPLIED", "DENIED"}
VERDICTS = ["winner", "inconclusive", "not_evaluated"]
AUTH_ROLES = ["operations_manager", "conversation_designer", "tenant_admin", "tenant_owner"]
PERMISSION = "campaign:manage"
INVARIANT_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]
ELIGIBILITY_FLAGS = ["consent_ok", "dnc_ok", "hours_ok"]

# z(alpha) iki-yön kritik değerleri (deterministik lookup; inverse-normal yaklaşımı yerine)
Z_CRIT = {0.10: 1.6449, 0.05: 1.9600, 0.01: 2.5758}
DEFAULT_MIN_SAMPLE = 100
DEFAULT_ALPHA = 0.05
WEIGHT_EPS = 1e-6
# Ağırlık-tolerans skew kontrolü ancak yeterli örneklemde anlamlı (küçük N'de doğal sapma).
MIN_CONTACTS_FOR_TOLERANCE = 50

INJECTIONS = {"skip_auth", "invalid_config", "misallocation", "false_winner",
              "not_idempotent", "cross_tenant", "eligibility_bypass", "no_audit"}

VIOLATION_KEYS = [
    "unauthorized", "invalid_config", "misallocation", "false_winner",
    "not_idempotent", "cross_tenant", "eligibility_bypass",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (C12; 9.x/10.1.7 deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|exp-|var-|camp-|t-|ck-|scr-|idem-|corr-|res-|prefix|masked|last4)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (10.1.7 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"desc"' in line or '"trace"' in line:
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
# Deterministik yardımcılar — sticky hash atama + iki-oran z-test (Date.now/random YOK).
# ════════════════════════════════════════════════════════════════════════════
def _hash_unit(experiment_id, contact_key):
    """(experiment_id, contact_key) → [0,1) deterministik. Hash girdisi yalnız yapısal kimlik (PII yok)."""
    h = hashlib.sha256(("%s:%s" % (experiment_id, contact_key)).encode("utf-8")).hexdigest()
    # İlk 13 hex hane (52 bit) → [0,1)
    return int(h[:13], 16) / float(1 << 52)


def _assign_variant(experiment_id, contact_key, variants):
    """Kümülatif ağırlık kovasına göre tam bir varyant id döndür (deterministik+sticky)."""
    u = _hash_unit(experiment_id, contact_key)
    acc = 0.0
    for v in variants:
        acc += float(v["weight"])
        if u < acc:
            return v["id"]
    return variants[-1]["id"]  # kayan-nokta artığı → son varyant


def _two_proportion_z(c1, n1, c2, n2):
    """Havuzlanmış iki-oran z (treatment#2 vs control#1). Döner z (n veya se=0 ise 0.0)."""
    if n1 <= 0 or n2 <= 0:
        return 0.0
    p1, p2 = c1 / n1, c2 / n2
    p_pool = (c1 + c2) / (n1 + n2)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0.0:
        return 0.0
    return (p2 - p1) / se


def _two_sided_p(z):
    """İki-yön p-değeri = erfc(|z|/sqrt(2)) (deterministik, stdlib)."""
    return math.erfc(abs(z) / math.sqrt(2.0))


# ════════════════════════════════════════════════════════════════════════════
def _config_from(sample, spec):
    """Config = ana ab-testing-policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "authorized_roles" in ov:
        cfg.setdefault("authorization", {})["authorized_roles"] = ov["authorized_roles"]
    if "weight_tolerance" in ov:
        cfg.setdefault("allocation", {})["weight_tolerance"] = ov["weight_tolerance"]
    if "default_min_sample" in ov:
        cfg.setdefault("comparison", {})["default_min_sample"] = ov["default_min_sample"]
    return cfg


def _contacts(sample):
    """Açık contacts listesi veya contacts_count → sentetik ck-<i> (sample kompakt kalır)."""
    if sample.get("contacts"):
        return list(sample["contacts"])
    n = int(sample.get("contacts_count", 0) or 0)
    return ["ck-%d" % i for i in range(n)]


def build(sample, spec, inject=None, cfg=None):
    """Tek A/B deney senaryosunu yürüt → ExperimentOutcome + ihlal sayaçları.

    Motor DOĞRU davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal
    sayacını artırır (10.1.7 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config_from(sample, spec)

    tenant = sample.get("tenant_id")
    campaign = sample.get("campaign_id")
    experiment = sample.get("experiment_id")
    actor = sample.get("actor_role")
    variants = sample.get("variants", []) or []
    contacts = _contacts(sample)
    outcomes = sample.get("outcomes", {}) or {}
    ineligible = set(sample.get("ineligible_contacts", []) or [])

    alloc_cfg = cfg.get("allocation", {})
    cmp_cfg = cfg.get("comparison", {})
    tol = float(sample.get("weight_tolerance", alloc_cfg.get("weight_tolerance", 0.10)))
    min_sample = int(sample.get("min_sample", cmp_cfg.get("default_min_sample", DEFAULT_MIN_SAMPLE)))
    alpha = float(sample.get("alpha", cmp_cfg.get("default_alpha", DEFAULT_ALPHA)))
    z_crit = Z_CRIT.get(round(alpha, 2), Z_CRIT[DEFAULT_ALPHA])
    authorized_roles = set((cfg.get("authorization", {}) or {}).get("authorized_roles", AUTH_ROLES))
    min_variants = int(alloc_cfg.get("min_variants", 2))

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── C7: tenant izolasyonu ──────────────────────────────────────────────────────────
    resource = "ab-res-" + str(tenant)
    if "cross_tenant" in inject:
        resource = "ab-res-foreigntenant"
        v["cross_tenant"] += 1
    bind_tenant = sample.get("bind_tenant")
    if bind_tenant and bind_tenant != tenant:
        v["cross_tenant"] += 1

    # ── C2: yetki ────────────────────────────────────────────────────────────────────────
    authorized = actor in authorized_roles
    denied = False
    deny_reason = None
    if not authorized:
        if "skip_auth" in inject:
            v["unauthorized"] += 1   # yetkisiz aktör config UYGULANDI → C2 ihlali
        else:
            denied = True
            deny_reason = "unauthorized"

    # ── C3: config geçerliliği (≥2 varyant, ağırlık toplamı 1.0, benzersiz id, script_version) ──
    variant_ids = [vv.get("id") for vv in variants]
    weight_sum = sum(float(vv.get("weight", 0)) for vv in variants)
    unique_ids = len(set(variant_ids)) == len(variant_ids) and all(variant_ids)
    has_scripts = all(vv.get("script_version") for vv in variants)
    config_valid = (len(variants) >= min_variants and unique_ids and has_scripts
                    and abs(weight_sum - 1.0) <= 1e-3)
    forced_invalid = "invalid_config" in inject

    terminal = None
    verdict = "not_evaluated"
    allocation = {}            # contact_key → variant_id
    alloc_counts = {}          # variant_id → atanan contact sayısı
    callable_count = 0
    observed_share = {}
    weight_skew_max = 0.0
    rates = {}                 # variant_id → conversion_rate
    leader = None
    leader_z = 0.0
    leader_p = 1.0

    if not denied and config_valid:
        terminal = "APPLIED"

        # ── C4: deterministik+sticky varyant dağıtımı ──
        alloc_counts = {vid: 0 for vid in variant_ids}
        for ck in contacts:
            vid = _assign_variant(experiment, ck, variants)
            allocation[ck] = vid
            alloc_counts[vid] = alloc_counts.get(vid, 0) + 1
            # ── C8: uygunluk koruması (consent/DNC/saat atlanmaz) ──
            eligible = ck not in ineligible
            if not eligible and "eligibility_bypass" in inject:
                eligible = True
                v["eligibility_bypass"] += 1   # uygunsuz contact 'aranabilir' yapıldı → C8 ihlali
            if eligible:
                callable_count += 1

        # misallocation inject: bir contact'ı TANIMSIZ varyanta + skew'e zorla → C4 ihlali
        if "misallocation" in inject and contacts:
            ghost = "var-GHOST"
            allocation[contacts[0]] = ghost
            alloc_counts[ghost] = alloc_counts.get(ghost, 0) + 1
            v["misallocation"] += 1

        # yapısal: her contact TANIMLI tek varyanta düşmeli
        defined = set(variant_ids)
        for ck, vid in allocation.items():
            if vid not in defined:
                if "misallocation" not in inject:
                    v["misallocation"] += 1  # beklenmedik tanımsız atama

        # gözlenen dağılım vs ağırlık (yalnız yeterli örneklemde tolerans uygula)
        total = len(contacts)
        if total > 0:
            observed_share = {vid: alloc_counts.get(vid, 0) / total for vid in variant_ids}
            for vv in variants:
                skew = abs(observed_share.get(vv["id"], 0.0) - float(vv["weight"]))
                weight_skew_max = max(weight_skew_max, skew)
            if total >= MIN_CONTACTS_FOR_TOLERANCE and weight_skew_max > tol:
                if "misallocation" not in inject:
                    v["misallocation"] += 1  # dağılım ağırlıkları toleransı aştı

        # ── C6: idempotency (sticky tekrar) ──
        repeat = {ck: _assign_variant(experiment, ck, variants) for ck in contacts}
        repeat_matches = all(repeat[ck] == allocation.get(ck) for ck in contacts)
        if "not_idempotent" in inject:
            repeat_matches = False
            v["not_idempotent"] += 1   # tekrar farklı dağıtım üretti (churn) → C6 ihlali
        elif not repeat_matches:
            v["not_idempotent"] += 1

        # ── C5: varyant karşılaştırması (iki-oran z-test) ──
        if outcomes:
            for vid in variant_ids:
                o = outcomes.get(vid, {}) or {}
                tr = int(o.get("trials", 0) or 0)
                cv = int(o.get("conversions", 0) or 0)
                rates[vid] = (cv / tr) if tr > 0 else 0.0
            control = variant_ids[0]
            co = outcomes.get(control, {}) or {}
            c_tr, c_cv = int(co.get("trials", 0) or 0), int(co.get("conversions", 0) or 0)
            # en yüksek dönüşümlü varyant aday lider
            leader = max(variant_ids, key=lambda x: rates.get(x, 0.0))
            lo = outcomes.get(leader, {}) or {}
            l_tr, l_cv = int(lo.get("trials", 0) or 0), int(lo.get("conversions", 0) or 0)
            leader_z = _two_proportion_z(c_cv, c_tr, l_cv, l_tr)
            leader_p = _two_sided_p(leader_z)
            enough_sample = (c_tr >= min_sample and l_tr >= min_sample)
            significant = abs(leader_z) >= z_crit
            if leader != control and enough_sample and significant:
                verdict = "winner"
            else:
                verdict = "inconclusive"
            # false_winner inject: anlamsız/yetersizde kazanan beyan et → C5 ihlali
            if "false_winner" in inject and verdict == "inconclusive":
                verdict = "winner"
                v["false_winner"] += 1
        else:
            verdict = "not_evaluated"

    elif denied:
        terminal = "DENIED"   # yetkisiz → işlem yok (doğru reddetme)
    else:
        # geçersiz config
        if forced_invalid:
            # inject: geçersiz config'i force-apply et → C3 ihlali
            v["invalid_config"] += 1
            terminal = "APPLIED"
            verdict = "not_evaluated"
        else:
            terminal = "DENIED"
            deny_reason = "invalid_config"

    # ── C1: stuck state ─────────────────────────────────────────────────────────────────
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (C9) ──────────────────────────────────────────────────────────────────────
    evidence = {
        "experiment_id": experiment,
        "variants": [{"id": vv.get("id"), "weight": vv.get("weight"),
                      "script_version": vv.get("script_version")} for vv in variants],
        "weight_sum": round(weight_sum, 6),
        "allocation_counts": alloc_counts,
        "observed_share": {k: round(x, 4) for k, x in observed_share.items()},
        "weight_skew_max": round(weight_skew_max, 4),
        "callable_count": callable_count,
        "comparison": {"rates": {k: round(x, 4) for k, x in rates.items()},
                       "leader": leader, "z": round(leader_z, 4), "p": round(leader_p, 4),
                       "min_sample": min_sample, "alpha": alpha, "verdict": verdict},
        "actor_role": actor,
        "authorized": bool(authorized),
        "resource": resource,
        "terminal": terminal,
        "deny_reason": deny_reason,
    }
    if (not experiment) or (not actor) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (C10) ─────────────────────────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "result": terminal,
            "experiment_id": experiment,
            "campaign_id": campaign,
            "variants": variant_ids,
            "verdict": verdict,
            "actor_role": actor,
            "deny_reason": deny_reason,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "applied": terminal == "APPLIED",
        "config_valid": bool(config_valid),
        "verdict": verdict,
        "allocation_counts": alloc_counts,
        "observed_share": {k: round(x, 4) for k, x in observed_share.items()},
        "weight_skew_max": round(weight_skew_max, 4),
        "callable_count": callable_count,
        "ineligible_count": len(ineligible),
        "rates": {k: round(x, 4) for k, x in rates.items()},
        "leader": leader,
        "leader_z": round(leader_z, 4),
        "leader_p": round(leader_p, 4),
        "authorized": bool(authorized),
        "deny_reason": deny_reason,
        "resource": resource,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "unauthorized": "max_unauthorized",
        "invalid_config": "max_invalid_config",
        "misallocation": "max_misallocation",
        "false_winner": "max_false_winner",
        "not_idempotent": "max_not_idempotent",
        "cross_tenant": "max_cross_tenant",
        "eligibility_bypass": "max_eligibility_bypass",
        "missing_evidence": "max_missing_evidence",
        "missing_audit": "max_missing_audit",
        "stuck_state": "max_stuck_state",
        "secret_or_pii": "max_secret_or_pii",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
    if gates.get("require_decision_record", True) and result["audit"] is None:
        fails.append("deney/audit kaydı üretilmedi (C10)")
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def run_cmd(arg):
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
        for key in ("terminal", "verdict", "applied", "leader", "callable_count"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s verdict=%s alloc=%s skew=%.3f callable=%d/%s"
              % (res["terminal"], res["verdict"], res["allocation_counts"],
                 res["weight_skew_max"], res["callable_count"],
                 res["callable_count"] + res["ineligible_count"] if res["ineligible_count"] else res["callable_count"]))
        if res["rates"]:
            print("   rates=%s leader=%s z=%.3f p=%.4f" % (res["rates"], res["leader"], res["leader_z"], res["leader_p"]))
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

    print("\nrun: %s" % ("🟢 TÜM SENARYOLAR BEKLENDİĞİ GİBİ" if all_ok else "🔴 EN AZ BİR SENARYO BEKLENMEDİK"))
    return 0 if all_ok else 1


# ════════════════════════════════════════════════════════════════════════════
def validate():
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    spec = _load(SPEC_PATH)

    # 1) Üst-düzey alanlar
    for f in ("wbs", "phase", "priority", "trace", "placement", "allocation", "comparison",
              "eligibility_guard", "authorization", "outcomes", "gates", "observability",
              "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=10.1.8", spec.get("wbs") == "10.1.8")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Should", spec.get("priority") == "Should")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-OUT-012 izlenir (A/B test)", "FR-OUT-012" in tr.get("fr", []))
    chk("FR-OUT-009 izlenir (script/teklif versiyonu bağı)", "FR-OUT-009" in tr.get("fr", []))
    chk("FR-OUT-003 izlenir (consent — uygunluk korunur)", "FR-OUT-003" in tr.get("fr", []))
    chk("FR-OUT-011 izlenir (disposition → outcomes)", "FR-OUT-011" in tr.get("fr", []))
    chk("FR-IAM-011 izlenir (campaign:manage RBAC)", "FR-IAM-011" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-OUT-012 izlenir", "SR-OUT-012" in tr.get("srs", []))
    chk("TC-OUT-012 izlenir", "TC-OUT-012" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §19.1 consent izlenir", any("§19.1" in s for s in tr.get("sad", [])))

    # 3) Dağıtım (SR-OUT-012 çekirdek 1/2)
    al = spec["allocation"]
    chk("dağıtım yöntemi deterministik_sticky_hash", al.get("method") == "deterministic_sticky_hash")
    chk("ağırlık toplamı = 1.0", al.get("weight_sum") == 1.0)
    chk("min_variants ≥ 2 (A/B)", al.get("min_variants", 0) >= 2)
    chk("weight_tolerance tanımlı", isinstance(al.get("weight_tolerance"), (int, float)))
    chk("hash girdisi PII içermez (yapısal kimlik)", "PII" in al.get("hash", "").upper() or "pii" in al.get("hash", "").lower())

    # 4) Karşılaştırma (SR-OUT-012 çekirdek 2/2)
    cmp_ = spec["comparison"]
    chk("metrik conversion_rate", "conversion_rate" in cmp_.get("metric", ""))
    chk("test iki-oran z", "z_test" in cmp_.get("test", "") or "z-test" in cmp_.get("test", ""))
    chk("default_min_sample tanımlı", isinstance(cmp_.get("default_min_sample"), int))
    chk("default_alpha tanımlı", isinstance(cmp_.get("default_alpha"), (int, float)))
    chk("verdict'ler winner+inconclusive", set(cmp_.get("verdicts", [])) == {"winner", "inconclusive"})

    # 5) Uygunluk koruması (C8)
    eg = spec["eligibility_guard"]
    chk("uygunluk bayrakları consent/dnc/hours", set(eg.get("required_flags", [])) == set(ELIGIBILITY_FLAGS))
    chk("kural: A/B uygunluğu override etmez", "override" in eg.get("rule", "").lower())

    # 6) Yetki
    az = spec["authorization"]
    chk("yetki permission=campaign:manage", az.get("permission") == PERMISSION)
    chk("yetkili roller operations_manager dahil", "operations_manager" in az.get("authorized_roles", []))
    chk("yetkili roller conversation_designer dahil", "conversation_designer" in az.get("authorized_roles", []))
    chk("yetki kararı backend'de", az.get("decision_at") == "backend")

    # 7) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar APPLIED+DENIED", set(oc.get("list", [])) == set(OUTCOMES))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_unauthorized", "max_invalid_config", "max_misallocation", "max_false_winner",
               "max_not_idempotent", "max_cross_tenant", "max_eligibility_bypass",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("ab_variant_allocation_total metrik", "ab_variant_allocation_total" in obs.get("metrics", []))
    chk("ab_comparison_verdict_total metrik", "ab_comparison_verdict_total" in obs.get("metrics", []))
    chk("ab_eligibility_bypass_total metrik (C8 alarm)", "ab_eligibility_bypass_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("experiment_id YÜKSEK kard (label değil)", "experiment_id" in hi and "experiment_id" not in lo)
    chk("contact_key/correlation_id YÜKSEK kard", "contact_key" in hi and "correlation_id" in hi)
    chk("variant/verdict/result DÜŞÜK kard (label uygun)",
        "variant" in lo and "verdict" in lo and "result" in lo)

    # 10) İnvariant'lar C1–C12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar C1–C12 tam", inv_ids == INVARIANT_IDS)

    # 11) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/ab-testing-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        cal = cfg.get("allocation", {})
        chk("config dağıtım deterministik_sticky_hash", cal.get("method") == "deterministic_sticky_hash")
        chk("config min_variants ≥ 2", cal.get("min_variants", 0) >= 2)
        ccmp = cfg.get("comparison", {})
        chk("config test two_proportion_z_test", ccmp.get("test") == "two_proportion_z_test")
        chk("config default_min_sample tanımlı", isinstance(ccmp.get("default_min_sample"), int))
        caz = cfg.get("authorization", {})
        chk("config permission=campaign:manage", caz.get("permission") == PERMISSION)
        chk("config yetkili roller operations_manager dahil",
            "operations_manager" in caz.get("authorized_roles", []))
        ceg = cfg.get("eligibility_guard", {})
        chk("config uygunluk bayrakları tam", set(ceg.get("required_flags", [])) == set(ELIGIBILITY_FLAGS))

    # 12) Sır/PII tarayıcı — spec + config + samples
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
    chk("hiç müşteri-PII/telefon/hesap-no/OTP/sır sızıntısı yok (C12)", total_leaks == 0)

    # 13) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
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
        d = {
            "tenant_id": "t-acme", "correlation_id": "corr-1", "campaign_id": "camp-1",
            "experiment_id": "exp-1",
            "actor_role": "operations_manager",
            "variants": [
                {"id": "var-A", "weight": 0.5, "script_version": "scr-v1"},
                {"id": "var-B", "weight": 0.5, "script_version": "scr-v2"},
            ],
            "contacts_count": 400,
        }
        d.update(kw)
        return d

    # 1) happy allocation — 50/50, 400 contact → APPLIED, deterministik+sticky, skew tolerans içinde
    r = build(req(), spec)
    case("happy-alloc: APPLIED", r["terminal"] == "APPLIED")
    case("happy-alloc: iki varyanta da atandı", r["allocation_counts"]["var-A"] > 0 and r["allocation_counts"]["var-B"] > 0)
    case("happy-alloc: tüm contact atandı", sum(r["allocation_counts"].values()) == 400)
    case("happy-alloc: skew ≤ tolerans", r["weight_skew_max"] <= 0.10)
    case("happy-alloc: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy-alloc: audit var (C10)", r["audit"] is not None and r["audit"]["result"] == "APPLIED")
    case("happy-alloc: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm + sticky — aynı girdi → birebir aynı sonuç
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    a1 = build(req(experiment_id="exp-x"), spec)["allocation_counts"]
    a2 = build(req(experiment_id="exp-x"), spec)["allocation_counts"]
    case("sticky: tekrar aynı dağıtım", a1 == a2)

    # 3) ağırlıklı dağıtım — 80/20 büyük N'de yansır
    r = build(req(variants=[{"id": "var-A", "weight": 0.8, "script_version": "scr-v1"},
                            {"id": "var-B", "weight": 0.2, "script_version": "scr-v2"}]), spec)
    case("weighted: A>B (80/20)", r["allocation_counts"]["var-A"] > r["allocation_counts"]["var-B"])
    case("weighted: skew ≤ tolerans", r["weight_skew_max"] <= 0.10)

    # 4) comparison winner — A 10%, B 20%, n=1000 her biri → anlamlı → winner B
    r = build(req(outcomes={"var-A": {"trials": 1000, "conversions": 100},
                            "var-B": {"trials": 1000, "conversions": 200}}), spec)
    case("compare-winner: verdict=winner", r["verdict"] == "winner")
    case("compare-winner: leader=var-B", r["leader"] == "var-B")
    case("compare-winner: |z| ≥ 1.96", abs(r["leader_z"]) >= 1.96)
    case("compare-winner: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 5) comparison inconclusive — küçük fark, n=100 → anlamsız → inconclusive
    r = build(req(outcomes={"var-A": {"trials": 100, "conversions": 50},
                            "var-B": {"trials": 100, "conversions": 53}}), spec)
    case("compare-inconc: verdict=inconclusive", r["verdict"] == "inconclusive")
    case("compare-inconc: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 6) min_sample altı → inconclusive (büyük fark olsa bile yetersiz örneklem)
    r = build(req(outcomes={"var-A": {"trials": 20, "conversions": 2},
                            "var-B": {"trials": 20, "conversions": 8}}, min_sample=100), spec)
    case("min-sample: inconclusive (n<min_sample)", r["verdict"] == "inconclusive")

    # 7) yetkisiz aktör — DENIED, işlem yok (doğru reddetme)
    r = build(req(actor_role="human_agent"), spec)
    case("unauthorized: DENIED", r["terminal"] == "DENIED")
    case("unauthorized: deny_reason=unauthorized", r["deny_reason"] == "unauthorized")
    case("unauthorized: ihlal yok (doğru reddetme)", all(x == 0 for x in r["violations"].values()))
    case("unauthorized: kapı geçer", _gate_eval(r, G)[0] is True)

    # 8) geçersiz config — tek varyant → DENIED (doğru reddetme)
    r = build(req(variants=[{"id": "var-A", "weight": 1.0, "script_version": "scr-v1"}]), spec)
    case("invalid-config: DENIED (tek varyant)", r["terminal"] == "DENIED")
    case("invalid-config: deny_reason=invalid_config", r["deny_reason"] == "invalid_config")
    case("invalid-config: ihlal yok (doğru reddetme)", all(x == 0 for x in r["violations"].values()))
    # ağırlık toplamı ≠ 1.0 → DENIED
    r = build(req(variants=[{"id": "var-A", "weight": 0.3, "script_version": "scr-v1"},
                            {"id": "var-B", "weight": 0.3, "script_version": "scr-v2"}]), spec)
    case("invalid-config: ağırlık toplamı≠1 DENIED", r["terminal"] == "DENIED")

    # 9) uygunluk koruması — ineligible contact callable DEĞİL
    s = req(contacts=["ck-1", "ck-2", "ck-3", "ck-4"], ineligible_contacts=["ck-2", "ck-4"])
    del s["contacts_count"]
    r = build(s, spec)
    case("eligibility: callable=2 (4-2 ineligible)", r["callable_count"] == 2)
    case("eligibility: ihlal yok", r["violations"]["eligibility_bypass"] == 0)

    # 10) inject eligibility_bypass → C8 ihlali
    r = build(s, spec, inject=["eligibility_bypass"])
    case("inject-eligibility-bypass: eligibility_bypass>0", r["violations"]["eligibility_bypass"] > 0)
    case("inject-eligibility-bypass: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) inject misallocation → C4 ihlali
    r = build(req(), spec, inject=["misallocation"])
    case("inject-misallocation: misallocation>0", r["violations"]["misallocation"] > 0)
    case("inject-misallocation: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) inject false_winner → C5 ihlali (inconclusive'de kazanan beyan)
    r = build(req(outcomes={"var-A": {"trials": 100, "conversions": 50},
                            "var-B": {"trials": 100, "conversions": 53}}), spec, inject=["false_winner"])
    case("inject-false-winner: false_winner>0", r["violations"]["false_winner"] > 0)
    case("inject-false-winner: verdict=winner (hatalı)", r["verdict"] == "winner")
    case("inject-false-winner: kapı eler", _gate_eval(r, G)[0] is False)

    # 13) inject skip_auth → C2 ihlali
    r = build(req(actor_role="human_agent"), spec, inject=["skip_auth"])
    case("inject-skip-auth: unauthorized>0", r["violations"]["unauthorized"] > 0)

    # 14) inject invalid_config → C3 ihlali (force-apply)
    r = build(req(variants=[{"id": "var-A", "weight": 1.0, "script_version": "scr-v1"}]), spec, inject=["invalid_config"])
    case("inject-invalid-config: invalid_config>0", r["violations"]["invalid_config"] > 0)

    # 15) inject not_idempotent → C6 ihlali
    r = build(req(), spec, inject=["not_idempotent"])
    case("inject-not-idempotent: not_idempotent>0", r["violations"]["not_idempotent"] > 0)

    # 16) inject cross_tenant → C7 ihlali
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 17) inject no_audit → C10 ihlali
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 18) kanıt (C9) — experiment + variants + comparison taşır
    r = build(req(outcomes={"var-A": {"trials": 1000, "conversions": 100},
                            "var-B": {"trials": 1000, "conversions": 200}}), spec)
    case("evidence: experiment taşır", r["evidence"]["experiment_id"] == "exp-1")
    case("evidence: variants taşır", len(r["evidence"]["variants"]) == 2)
    case("evidence: comparison verdict taşır", r["evidence"]["comparison"]["verdict"] == "winner")
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 19) audit (C10) — result + experiment + verdict + tenant taşır
    case("audit: result taşır", r["audit"]["result"] == "APPLIED")
    case("audit: verdict taşır", r["audit"]["verdict"] == "winner")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")

    # 20) >2 varyant (A/B/C) — geçerli config, dağıtım üçe bölünür
    r = build(req(variants=[{"id": "var-A", "weight": 0.34, "script_version": "scr-v1"},
                            {"id": "var-B", "weight": 0.33, "script_version": "scr-v2"},
                            {"id": "var-C", "weight": 0.33, "script_version": "scr-v3"}]), spec)
    case("abc: APPLIED 3 varyant", r["terminal"] == "APPLIED" and len(r["allocation_counts"]) == 3)
    case("abc: üçüne de atandı", all(r["allocation_counts"][x] > 0 for x in ("var-A", "var-B", "var-C")))

    # 21) sızıntı tarayıcı: yapısal kimlik temiz, ham PII/telefon yakalanır
    case("leak: exp-001 kimlik temiz", scan_leaks('{"experiment_id": "exp-001"}') == [])
    case("leak: var-A kimlik temiz", scan_leaks('{"variant": "var-A"}') == [])
    case("leak: ck-001 kimlik temiz", scan_leaks('{"contact_key": "ck-001"}') == [])
    case("leak: customer_phone_value alanı yakalanır", len(scan_leaks('{"customer_phone_value": "x"}')) > 0)
    case("leak: ham uzun telefon yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "ab-testing (WBS 10.1.8 — FR-OUT-012 A/B test kampanyaları)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "verdicts": VERDICTS,
        "authorized_roles": AUTH_ROLES,
        "permission": PERMISSION,
        "allocation": "deterministic_sticky_hash (hashlib; salt=experiment_id, key=contact_key; PII YOK)",
        "comparison": "two_proportion_z_test (control=ilk varyant; winner ancak min_sample + |z|≥z(alpha))",
        "eligibility_flags": ELIGIBILITY_FLAGS,
        "request_fields": ["name", "tenant_id", "correlation_id", "campaign_id", "experiment_id",
                           "actor_role", "variants[{id,weight,script_version}]",
                           "contacts[]|contacts_count", "outcomes{variant→{trials,conversions}}",
                           "ineligible_contacts[]", "min_sample", "alpha", "weight_tolerance",
                           "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "outcome_fields": ["terminal", "applied", "config_valid", "verdict", "allocation_counts",
                           "observed_share", "weight_skew_max", "callable_count", "rates", "leader",
                           "leader_z", "leader_p", "authorized", "deny_reason", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "z_crit": Z_CRIT,
        "trace": "FR-OUT-012, SR-OUT-012, TC-OUT-012, FR-OUT-009/003/006/011, FR-IAM-011/006, "
                 "FR-TEN-002, FR-REC-004, DB.md campaign, API §A-10, SAD §6, SAD §19.1, ADR-001/002/012",
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
    if cmd == "run":
        if len(argv) < 3:
            print("kullanım: ab_testing_probe.py run <sample.json|dizin>")
            return 2
        return run_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
