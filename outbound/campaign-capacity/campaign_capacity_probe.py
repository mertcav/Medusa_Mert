#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.6 — Kampanya kapasitesi ≤ agent+trunk kapasitesi (backpressure entegrasyonu) referans probe.

10. workstream'in (Outbound) Consent & uyumluluk motoru alt-bloğunun KAMPANYA-DÜZEYİ KAPASİTE/
BACKPRESSURE (campaign-capacity) modülü ve F2-Must outbound yeteneği. FR-OUT-007 ('Kampanya kapasitesi
mevcut agent ve trunk kapasitesini aşmamalıdır') + SR-OUT-007 (yöntem T — 'Kampanya kapasitesi
agent+trunk kapasitesini aşmaz (backpressure)'; kabul: 'Kapasite üstü arama backpressure ile
sınırlanır') + FR-RES-014 (backpressure & graceful degradation) + SAD §15.2 Resource Manager
Backpressure Ctrl'ü sahiplenir. Modül 10.2.4 PER-DIAL silent-call kapısının KAMPANYA-DÜZEYİ
tamamlayıcısıdır (10.2.4 BLOCK = pace-down girdisi). Bir DETERMİNİSTİK FAIL-CLOSED /
NO-OVERSUBSCRIPTION MOTORUdur:

  CampaignCapacityRequest ──politika çöz (util_threshold)──► ceiling hesapla ──► design (Little) ──► admit
        │                          │                              │                    │            │
        │     ceiling = floor(min(agent_avail,trunk_avail,quota_avail) × util)  design=max(conc, ⌈cps×hold⌉)
        │                          │                              │                    │            │
        │           ├─ profil çözülemez ─────────────────────────────────────► BLOCK (unknown_profile)
        │           ├─ cross-tenant ───────────────────────────────────────────► BLOCK (cross_tenant)
        │           ├─ design ≤ ceiling ───────────────────────────► ADMIT (effective=design)
        │           ├─ ceiling > 0 ────────────────────────────────► PACE_DOWN (effective=ceiling, overflow→callback)
        │           └─ ceiling ≤ 0 ────────────────────────────────► DEFER (effective=0, overflow→callback)

ÇEKİRDEK INVARIANT'lar: K2 doğru kapasite tavanı (min agent+trunk+kota × util − rezerve; FR-OUT-007),
K3 Little sizing (design = max(conc, ⌈cps×hold⌉); SAD §20), K4 no over-subscription (effective ≤ ceiling;
FR-OUT-007), K5 graceful backpressure (overflow = design − effective → callback; FR-RES-014), K6 rezerve
inbound korunur, K7 fail-closed bilinmeyen profil, K8 ATLANAMAZ (bypass=capacity_skip=BRD §15 'kapasite
aşımı' alarmı). Her karar deterministik+terminal (K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite
+ PII yok (K11); sır/PII yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): per-dial silent-call → 10.2.4 (BLOCK pace girdisi); consent
→ 10.2.1; DNC → 10.2.2; arama saati → 10.2.3; sistem-düzeyi yük testi → 0.4.8 (Little/admission MODELİNİ
tüketir); autoscale/warm pool → SAD §15.2 (FR-RES-013); kapasite SNAPSHOT → runtime telemetri 0.4.7
(OKUR); kota TANIMI → FR-TEN-004/Quota Service (tüketir); retry/callback → 2.1.8 (overflow'u alır);
audit store → 7.1.6/12.x; dialer çevirme/pace → 10.1.x (karar döndürür, çevirmez).

Kullanım:
  campaign_capacity_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  campaign_capacity_probe.py check <sample>     Kapasite motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  campaign_capacity_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  campaign_capacity_probe.py schema             Karar sözleşmesini yazdır

Determinizm: politika çözümü + tamsayı/oran kapasite muhasebesi + Little tamsayı tavan-bölme
(math.ceil/floor); sanal snapshot girdisi; Date.now/random YOK. Stdlib-only. Sır/credential ve gerçek
PII (müşteri adı/telefon/ham numara) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "campaign-capacity-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "campaign-capacity-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ADMIT", "PACE_DOWN", "DEFER", "BLOCK"]
TERMINAL = {"ADMIT", "PACE_DOWN", "DEFER", "BLOCK"}
RULES = ["capacity_ceiling", "little_sizing", "no_oversubscription", "graceful_backpressure", "reserve_respected"]
BLOCK_REASONS = ["unknown_profile", "cross_tenant"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
CHANNEL = "voice"

# Degrade (inject) — DOĞRU fail-closed/no-oversubscription davranışını bozan müdahaleler.
INJECTIONS = {"skip_capacity", "ignore_trunk", "ignore_quota", "ignore_little", "over_admit",
              "ungraceful_drop", "ignore_reserve", "failopen_profile", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "capacity_skip", "capacity_error", "sizing_error", "over_subscription",
    "backpressure_fail", "reserve_violation", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 10.2.x deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# Kapasite sayıları (kısa tamsayı), oranlar (0.8), süreler (180), yapısal kimlik/enum beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|camp-|t-|corr-|res-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı eler (10.2.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"desc"' in line or '"trace"' in line or '"rule"' in line:
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _resolve_profile(sample, cfg):
    """country/profile_id → profil. Açık profile_id öncelikli; yoksa country eşleşmesi; yoksa None."""
    profiles = cfg.get("profiles", {})
    pid = sample.get("profile_id")
    if pid and pid in profiles:
        return pid, profiles[pid]
    country = sample.get("country")
    for name, prof in profiles.items():
        if prof.get("country") == country:
            return name, prof
    return None, None


def _num(v, default=0):
    """Sayısal alanı güvenle al (None → default)."""
    return v if v is not None else default


def _config(sample):
    """Config = ana policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "profiles" in ov:
        cfg.setdefault("profiles", {}).update(ov["profiles"])
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek kampanya-kapasite senaryosunu yürüt → CampaignCapacityDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / no-oversubscription davranışını hesaplar; inject (degrade) doğru
    davranışı bozar ve eşleşen ihlal sayacını artırır (10.2.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    campaign = sample.get("campaign_id")
    request_id = sample.get("request_id")
    country = sample.get("country")
    category = sample.get("campaign_category")

    # Kampanya hız planı (Little girdileri)
    target_concurrency = _num(sample.get("target_concurrency"))
    target_cps = _num(sample.get("target_cps"))
    mean_call_seconds = _num(sample.get("mean_call_seconds"))

    # Kapasite snapshot (runtime telemetri girdisi; deterministik sanal değerler)
    agent_total = _num(sample.get("agent_handlers_total"))
    agent_active = _num(sample.get("agent_handlers_active"))
    reserved_inbound = _num(sample.get("reserved_inbound_handlers"))
    trunk_total = _num(sample.get("trunk_channels_total"))
    trunk_active = _num(sample.get("trunk_channels_active"))
    tenant_quota = _num(sample.get("tenant_quota_concurrency"))
    tenant_active = _num(sample.get("tenant_concurrency_active"))

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── K12 (tenant izolasyonu): kapasite politikası/snapshot/kota yalnız aynı tenant'a ait okunur ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── Politika çöz (util_threshold + overflow_policy) ──
    resolved_profile, prof = _resolve_profile(sample, cfg)

    block_reason = None
    ceiling = None
    design = None
    effective = None
    overflow = None
    agent_avail = None
    trunk_avail = None
    quota_avail = None
    util_threshold = None
    overflow_policy = None

    # ── K7 fail-closed: profil çözümlenemedi → unknown_profile (fail-open YASAK) ──
    profile_unresolved = (prof is None)
    if profile_unresolved:
        if "failopen_profile" in inject:
            v["failopen"] += 1               # profil çözülemedi ama ADMIT → K7 fail-open ihlali
            prof = {"util_threshold": 1.0, "overflow_policy": "callback_queue"}
            profile_unresolved = False
        else:
            block_reason = "unknown_profile"

    # cross_tenant fail-closed BLOCK (profil çözülse bile)
    if v["cross_tenant"] > 0 and block_reason is None:
        block_reason = "cross_tenant"

    if not profile_unresolved and block_reason != "cross_tenant":
        util_threshold = prof.get("util_threshold", 0.8)
        overflow_policy = prof.get("overflow_policy", "callback_queue")

        # ── K6 rezerve inbound: agent_avail = agent_total − agent_active − reserved_inbound ──
        effective_reserved = reserved_inbound
        if "ignore_reserve" in inject:
            effective_reserved = 0           # rezerve düşülmez → inbound yenir
            v["reserve_violation"] += 1
        agent_avail = agent_total - agent_active - effective_reserved
        trunk_avail = trunk_total - trunk_active
        quota_avail = tenant_quota - tenant_active

        # ── K2 doğru kapasite tavanı: ceiling = floor(min(üç bileşen) × util) ──
        # ignore_trunk/ignore_quota: bir bileşen min'den DÜŞÜLÜR → yanlış (yüksek) tavan = over-subscription
        components = {"agent": agent_avail, "trunk": trunk_avail, "quota": quota_avail}
        if "ignore_trunk" in inject:
            del components["trunk"]
            v["capacity_error"] += 1
        if "ignore_quota" in inject:
            del components["quota"]
            v["capacity_error"] += 1
        min_avail = min(components.values())
        ceiling = max(0, int(math.floor(min_avail * util_threshold)))

        # ── K3 Little sizing: design = max(target_concurrency, ⌈target_cps × mean_call_seconds⌉) ──
        little = int(math.ceil(target_cps * mean_call_seconds)) if (target_cps and mean_call_seconds) else 0
        if "ignore_little" in inject:
            little = 0                       # CPS×tutma atlanır → under-size → gizli over-subscription
            v["sizing_error"] += 1
        design = max(target_concurrency, little)

        # ── Karar: design ≤ ceiling ⇒ ADMIT | ceiling>0 ⇒ PACE_DOWN | ceiling≤0 ⇒ DEFER ──
        if design <= ceiling:
            terminal = "ADMIT"
            effective = design
            overflow = 0
        elif ceiling > 0:
            terminal = "PACE_DOWN"
            effective = ceiling
            overflow = design - ceiling      # callback kuyruğuna (graceful)
        else:
            terminal = "DEFER"
            effective = 0
            overflow = design                # tümü callback kuyruğuna (graceful)

        # ── K8 (fail-closed / ATLANAMAZ): bypass → ceiling yok sayılıp design admit → capacity_skip ──
        if "skip_capacity" in inject:
            terminal = "ADMIT"
            effective = design               # ceiling yok sayılır → over-subscription
            overflow = 0
            v["capacity_skip"] += 1

        # ── K4 over-subscription: effective > ceiling (doğrudan over-admit injection) ──
        if "over_admit" in inject:
            effective = design               # ceiling'i aş
            overflow = 0
            if terminal == "DEFER":
                terminal = "PACE_DOWN"
        if effective is not None and ceiling is not None and effective > ceiling:
            v["over_subscription"] += 1

        # ── K5 graceful backpressure: overflow muhasebelenmeli (= design − effective) ──
        if "ungraceful_drop" in inject:
            overflow = 0                     # overflow sessizce düşürülür (çökme/silent drop)
        if terminal in ("PACE_DOWN", "DEFER"):
            expected_overflow = design - effective
            if overflow != expected_overflow:
                v["backpressure_fail"] += 1
    else:
        terminal = "BLOCK"

    if block_reason is not None:
        terminal = "BLOCK"

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # capacity_ok: kampanya planlanan hızda kabul edildi mi (ADMIT). PACE_DOWN/DEFER = kısmi/bekleme.
    capacity_ok = (terminal == "ADMIT")

    # ── Kanıt (K9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "resolved_profile": resolved_profile,
        "util_threshold": util_threshold,
        "agent_avail": agent_avail,
        "trunk_avail": trunk_avail,
        "quota_avail": quota_avail,
        "ceiling": ceiling,
        "design_concurrency": design,
        "effective": effective,
        "overflow": overflow,
        "overflow_policy": overflow_policy,
        "capacity_ok": capacity_ok,
        "block_reason": block_reason,
        "terminal": terminal,
    }
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII YOK — yalnız yapısal kimlik/enum/kapasite sayısı/oran)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "result": terminal,
            "request_id": request_id,
            "campaign_id": campaign,
            "country": country,
            "campaign_category": category,
            "ceiling": ceiling,
            "design_concurrency": design,
            "effective": effective,
            "overflow": overflow,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "capacity_ok": capacity_ok,
        "resolved_profile": resolved_profile,
        "ceiling": ceiling,
        "design_concurrency": design,
        "effective": effective,
        "overflow": overflow,
        "agent_avail": agent_avail,
        "trunk_avail": trunk_avail,
        "quota_avail": quota_avail,
        "block_reason": block_reason,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "capacity_skip": "max_capacity_skip",
        "capacity_error": "max_capacity_error",
        "sizing_error": "max_sizing_error",
        "over_subscription": "max_over_subscription",
        "backpressure_fail": "max_backpressure_fail",
        "reserve_violation": "max_reserve_violation",
        "failopen": "max_failopen",
        "cross_tenant": "max_cross_tenant",
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
        fails.append("karar/audit kaydı üretilmedi (K10)")
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
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
        for key in ("terminal", "block_reason", "capacity_ok", "ceiling", "design_concurrency", "effective", "overflow"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s reason=%s profil=%s ceiling=%s design=%s effective=%s overflow=%s"
              % (res["terminal"], res["block_reason"], res["resolved_profile"],
                 res["ceiling"], res["design_concurrency"], res["effective"], res["overflow"]))
        print("   agent_avail=%s trunk_avail=%s quota_avail=%s"
              % (res["agent_avail"], res["trunk_avail"], res["quota_avail"]))
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
    for f in ("wbs", "phase", "priority", "trace", "placement", "rules", "decision",
              "block_reasons", "outcomes", "authorization", "gates", "observability",
              "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=10.2.6", spec.get("wbs") == "10.2.6")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-OUT-007 izlenir (kampanya kapasitesi ≤ agent+trunk)", "FR-OUT-007" in tr.get("fr", []))
    chk("FR-RES-014 izlenir (backpressure/graceful degradation)", "FR-RES-014" in tr.get("fr", []))
    chk("FR-TEL-015 izlenir (per-dial 10.2.4 köprü)", "FR-TEL-015" in tr.get("fr", []))
    chk("FR-TEN-004 izlenir (tenant kota)", "FR-TEN-004" in tr.get("fr", []))
    chk("FR-TST-006 izlenir (yük testi modeli — 0.4.8)", "FR-TST-006" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-OUT-007 izlenir", "SR-OUT-007" in tr.get("srs", []))
    chk("SR-RES-014 izlenir", "SR-RES-014" in tr.get("srs", []))
    chk("TC-OUT-007 izlenir", "TC-OUT-007" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §15.2 Resource Manager izlenir", any("§15.2" in s for s in tr.get("sad", [])))
    chk("SAD §20 Little yasası izlenir", any("§20" in s for s in tr.get("sad", [])))
    chk("BRD §9.13 FR-OUT-007 izlenir", any("§9.13" in s for s in tr.get("brd", [])))
    chk("BRD §15 kapasite aşımı alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))

    # 3) Beş kural (FR-OUT-007 + FR-RES-014 çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("beş kural tam (ceiling/little/no-oversub/graceful/reserve)", set(rule_ids) == set(RULES))
    chk("değerlendirme ceiling_then_size_then_admit_fail_closed",
        rz.get("evaluation") == "ceiling_then_size_then_admit_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")

    # 5) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar ADMIT/PACE_DOWN/DEFER/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam (unknown_profile/cross_tenant)", br == set(BLOCK_REASONS))

    # 6) Yetki — config-düzeyi resource:quota:manage, per-campaign otomatik gate
    az = spec["authorization"]
    chk("policy_permission=resource:quota:manage", az.get("policy_permission") == "resource:quota:manage")
    chk("per_campaign_check otomatik gate", "automatic_gate" in az.get("per_campaign_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_capacity_skip", "max_capacity_error", "max_sizing_error", "max_over_subscription",
               "max_backpressure_fail", "max_reserve_violation", "max_failopen", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("campaign_capacity_check_total metrik", "campaign_capacity_check_total" in obs.get("metrics", []))
    chk("campaign_pace_down_total metrik (backpressure)", "campaign_pace_down_total" in obs.get("metrics", []))
    chk("campaign_oversubscription_total metrik (K4 alarm)", "campaign_oversubscription_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/campaign_id YÜKSEK kard (label değil)",
        "request_id" in hi and "campaign_id" in hi and "campaign_id" not in lo)
    chk("result/country/campaign_category DÜŞÜK kard (label uygun)",
        "result" in lo and "country" in lo and "campaign_category" in lo)
    chk("alarm over_subscription/capacity_skip ≤2dk",
        "over_subscription" in obs.get("alarm", "") or "capacity_skip" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/campaign-capacity-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        tr_p = profs.get("PROFILE-TR", {})
        chk("config PROFILE-TR var (util_threshold+overflow_policy)",
            tr_p.get("util_threshold") == 0.8 and tr_p.get("overflow_policy") == "callback_queue")
        chk("config PROFILE-UK var (muhafazakar util 0.75)",
            profs.get("PROFILE-UK", {}).get("util_threshold") == 0.75)
        chk("config PROFILE-EU var (util 0.7)",
            profs.get("PROFILE-EU", {}).get("util_threshold") == 0.7)
        chk("config channel=voice", cfg.get("channel") == CHANNEL)

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
    chk("hiç müşteri-PII/telefon/hesap-no/OTP/sır sızıntısı yok (K12)", total_leaks == 0)

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
        # Varsayılan TR: agent 100−20−10=70 avail, trunk 80−30=50, quota 60−10=50 → min 50 ×0.8 = ceiling 40.
        # design: target_concurrency=20, cps=0.1×holding=180 → little 18 → design 20 ≤ 40 → ADMIT.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "campaign_id": "camp-1", "country": "TR", "channel": "voice", "campaign_category": "sales",
            "target_concurrency": 20, "target_cps": 0.1, "mean_call_seconds": 180,
            "agent_handlers_total": 100, "agent_handlers_active": 20, "reserved_inbound_handlers": 10,
            "trunk_channels_total": 80, "trunk_channels_active": 30,
            "tenant_quota_concurrency": 60, "tenant_concurrency_active": 10,
        }
        d.update(kw)
        return d

    # 1) happy — design ≤ ceiling → ADMIT
    r = build(req(), spec)
    case("happy: ADMIT", r["terminal"] == "ADMIT")
    case("happy: ceiling=40 (min(70,50,50)=50 ×0.8)", r["ceiling"] == 40)
    case("happy: design=20 (max(20, ⌈0.1×180=18⌉))", r["design_concurrency"] == 20)
    case("happy: effective=20=design", r["effective"] == 20)
    case("happy: overflow=0", r["overflow"] == 0)
    case("happy: capacity_ok=true", r["capacity_ok"] is True)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit ADMIT (K10)", r["audit"] is not None and r["audit"]["result"] == "ADMIT")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) K2 ceiling — boundary: design == ceiling → ADMIT
    r = build(req(target_concurrency=40, target_cps=0, mean_call_seconds=0), spec)
    case("ceiling: design=40 == ceiling=40 → ADMIT", r["terminal"] == "ADMIT" and r["effective"] == 40)
    # design = ceiling+1 → PACE_DOWN
    r = build(req(target_concurrency=41, target_cps=0, mean_call_seconds=0), spec)
    case("ceiling: design=41 > ceiling=40 → PACE_DOWN", r["terminal"] == "PACE_DOWN")
    case("ceiling: PACE_DOWN effective=ceiling=40", r["effective"] == 40)
    case("ceiling: PACE_DOWN overflow=1 (callback)", r["overflow"] == 1)
    case("ceiling: effective ≤ ceiling (K4)", r["effective"] <= r["ceiling"])

    # 3b) trunk binding — trunk en kısıtlayıcı (trunk_avail=10) → ceiling = floor(10×0.8)=8
    r = build(req(trunk_channels_total=40, trunk_channels_active=30, target_concurrency=20,
                  target_cps=0, mean_call_seconds=0), spec)
    case("trunk-binding: ceiling=8 (min içinde trunk=10)", r["ceiling"] == 8)
    case("trunk-binding: 20>8 → PACE_DOWN", r["terminal"] == "PACE_DOWN" and r["effective"] == 8)

    # 3c) quota binding — kota en kısıtlayıcı (quota_avail=5) → ceiling = floor(5×0.8)=4
    r = build(req(tenant_quota_concurrency=25, tenant_concurrency_active=20, target_concurrency=20,
                  target_cps=0, mean_call_seconds=0), spec)
    case("quota-binding: ceiling=4 (quota_avail=5)", r["ceiling"] == 4)

    # 4) DEFER — kapasite yok (ceiling=0)
    r = build(req(agent_handlers_total=20, agent_handlers_active=20, reserved_inbound_handlers=0,
                  target_concurrency=10, target_cps=0, mean_call_seconds=0), spec)
    case("defer: agent_avail=0 → ceiling=0 → DEFER", r["terminal"] == "DEFER")
    case("defer: effective=0", r["effective"] == 0)
    case("defer: overflow=design=10 (callback)", r["overflow"] == 10)
    case("defer: effective ≤ ceiling (K4)", r["effective"] <= r["ceiling"])

    # 5) K3 Little sizing — cps×holding büyük design'ı belirler
    r = build(req(target_concurrency=5, target_cps=1.0, mean_call_seconds=180), spec)
    case("little: design=180 (⌈1.0×180⌉ > 5)", r["design_concurrency"] == 180)
    case("little: 180>40 → PACE_DOWN effective=40", r["terminal"] == "PACE_DOWN" and r["effective"] == 40)
    # ceil yukarı yuvarlar
    r = build(req(target_concurrency=0, target_cps=0.11, mean_call_seconds=181), spec)
    case("little: ⌈0.11×181=19.91⌉=20", r["design_concurrency"] == 20)
    # ignore_little injection → under-size
    r = build(req(target_concurrency=5, target_cps=1.0, mean_call_seconds=180), spec, inject=["ignore_little"])
    case("inject-little: sizing_error>0", r["violations"]["sizing_error"] > 0)
    case("inject-little: design=5 (cps×hold atlandı)", r["design_concurrency"] == 5)
    case("inject-little: kapı eler", _gate_eval(r, G)[0] is False)

    # 6) K2 ignore_trunk — trunk min'den düşülür → yanlış (yüksek) ceiling
    r = build(req(trunk_channels_total=40, trunk_channels_active=30, target_concurrency=20,
                  target_cps=0, mean_call_seconds=0), spec, inject=["ignore_trunk"])
    case("inject-ignore-trunk: capacity_error>0", r["violations"]["capacity_error"] > 0)
    case("inject-ignore-trunk: ceiling=40 (trunk yok sayıldı)", r["ceiling"] == 40)
    case("inject-ignore-trunk: kapı eler", _gate_eval(r, G)[0] is False)
    # ignore_quota
    r = build(req(tenant_quota_concurrency=25, tenant_concurrency_active=20, target_concurrency=20,
                  target_cps=0, mean_call_seconds=0), spec, inject=["ignore_quota"])
    case("inject-ignore-quota: capacity_error>0", r["violations"]["capacity_error"] > 0)

    # 7) K6 ignore_reserve — rezerve düşülmez → agent_avail artar → ceiling yanlış yükselir
    r = build(req(reserved_inbound_handlers=40, agent_handlers_total=60, agent_handlers_active=0,
                  trunk_channels_total=100, trunk_channels_active=0,
                  tenant_quota_concurrency=100, tenant_concurrency_active=0), spec, inject=["ignore_reserve"])
    case("inject-ignore-reserve: reserve_violation>0", r["violations"]["reserve_violation"] > 0)
    case("inject-ignore-reserve: agent_avail=60 (rezerve düşülmedi)", r["agent_avail"] == 60)
    case("inject-ignore-reserve: kapı eler", _gate_eval(r, G)[0] is False)
    # rezerve doğru düşülür (no inject) → agent_avail=20
    r = build(req(reserved_inbound_handlers=40, agent_handlers_total=60, agent_handlers_active=0), spec)
    case("reserve: agent_avail=20 (60−0−40)", r["agent_avail"] == 20)

    # 8) K4 over_admit — effective ceiling'i aşar
    r = build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), spec, inject=["over_admit"])
    case("inject-over-admit: over_subscription>0", r["violations"]["over_subscription"] > 0)
    case("inject-over-admit: effective>ceiling", r["effective"] > r["ceiling"])
    case("inject-over-admit: kapı eler", _gate_eval(r, G)[0] is False)

    # 9) K5 ungraceful_drop — overflow muhasebelenmez (sessiz düşüş)
    r = build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), spec, inject=["ungraceful_drop"])
    case("inject-ungraceful: backpressure_fail>0", r["violations"]["backpressure_fail"] > 0)
    case("inject-ungraceful: overflow=0 (sessiz düşüş)", r["overflow"] == 0)
    case("inject-ungraceful: kapı eler", _gate_eval(r, G)[0] is False)
    # graceful (no inject): overflow = design − effective
    r = build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), spec)
    case("graceful: overflow=60 (100−40)", r["overflow"] == 60)
    case("graceful: PACE_DOWN", r["terminal"] == "PACE_DOWN")

    # 10) K8 skip_capacity — bypass: ceiling yok sayılıp design admit → capacity_skip + over-subscription
    r = build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), spec, inject=["skip_capacity"])
    case("inject-skip: capacity_skip>0", r["violations"]["capacity_skip"] > 0)
    case("inject-skip: terminal ADMIT'e zorlandı", r["terminal"] == "ADMIT")
    case("inject-skip: effective=design=100 (ceiling aşıldı)", r["effective"] == 100)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) K7 fail-closed bilinmeyen profil
    r = build(req(country="ZZ"), spec)
    case("unknown-profile: bilinmeyen ülke → BLOCK unknown_profile",
         r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_profile")
    r = build(req(country="ZZ"), spec, inject=["failopen_profile"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0 + BLOCK", r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 13) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 14) UK profili — util 0.75
    r = build(req(country="UK", profile_id="PROFILE-UK", target_concurrency=20, target_cps=0, mean_call_seconds=0), spec)
    case("uk: util_threshold=0.75 → ceiling=floor(50×0.75)=37", r["ceiling"] == 37)

    # 15) EU profili — util 0.7
    r = build(req(country="EU", profile_id="PROFILE-EU", target_concurrency=20, target_cps=0, mean_call_seconds=0), spec)
    case("eu: util_threshold=0.7 → ceiling=floor(50×0.7)=35", r["ceiling"] == 35)

    # 16) kanıt (K9)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: ceiling/design/effective/overflow taşır",
         all(k in r["evidence"] for k in ("ceiling", "design_concurrency", "effective", "overflow")))
    case("evidence: resolved_profile=PROFILE-TR", r["evidence"]["resolved_profile"] == "PROFILE-TR")
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 17) audit (K10) — result + country + tenant taşır, ham PII yok
    case("audit: result taşır", r["audit"]["result"] == "ADMIT")
    case("audit: country taşır", r["audit"]["country"] == "TR")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad alanı yok", "customer_phone_value" not in json.dumps(r["audit"])
         and "customer_name" not in json.dumps(r["audit"]))

    # 18) K4 her terminal sonuçta effective ≤ ceiling (no over-subscription) — temel garanti
    for kw in (dict(target_concurrency=10), dict(target_concurrency=40), dict(target_concurrency=41),
               dict(target_concurrency=200), dict(agent_handlers_active=100, agent_handlers_total=100)):
        rr = build(req(target_cps=0, mean_call_seconds=0, **kw), spec)
        if rr["effective"] is not None and rr["ceiling"] is not None:
            case("K4 garanti: effective ≤ ceiling (%s)" % kw, rr["effective"] <= rr["ceiling"])

    # 19) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: kapasite sayısı temiz", scan_leaks('{"agent_handlers_total": 100, "trunk_channels_total": 80}') == [])
    case("leak: oran/süre temiz", scan_leaks('{"util_threshold": 0.8, "mean_call_seconds": 180}') == [])
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
        "module": "campaign-capacity (WBS 10.2.6 — FR-OUT-007 kampanya kapasitesi ≤ agent+trunk + FR-RES-014 backpressure)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "decision": "resolve_policy(util_threshold) | unresolved ⇒ BLOCK(unknown_profile) → tenant_check ⇒ "
                    "BLOCK(cross_tenant) → ceiling = max(0, floor(min(agent_avail,trunk_avail,quota_avail) × util)) "
                    "→ design = max(target_concurrency, ⌈target_cps × mean_call_seconds⌉) → "
                    "design ≤ ceiling ⇒ ADMIT(effective=design) | ceiling>0 ⇒ PACE_DOWN(effective=ceiling, "
                    "overflow=design−ceiling→callback) | ceiling≤0 ⇒ DEFER(effective=0, overflow=design→callback)",
        "default": "BLOCK (fail-closed; profil çözümlenemedi veya cross-tenant)",
        "channel": CHANNEL,
        "capacity_ceiling": "agent_avail = agent_handlers_total − agent_handlers_active − reserved_inbound_handlers; "
                            "trunk_avail = trunk_channels_total − trunk_channels_active; "
                            "quota_avail = tenant_quota_concurrency − tenant_concurrency_active; "
                            "ceiling = max(0, floor(min(agent_avail, trunk_avail, quota_avail) × util_threshold))",
        "little_sizing": "design_concurrency = max(target_concurrency, ⌈target_cps × mean_call_seconds⌉)",
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "campaign_id",
                           "country", "channel(voice)", "campaign_category",
                           "target_concurrency?", "target_cps?", "mean_call_seconds?",
                           "agent_handlers_total", "agent_handlers_active", "reserved_inbound_handlers",
                           "trunk_channels_total", "trunk_channels_active",
                           "tenant_quota_concurrency", "tenant_concurrency_active",
                           "profile_id?", "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "capacity_ok", "resolved_profile", "ceiling", "design_concurrency",
                            "effective", "overflow", "agent_avail", "trunk_avail", "quota_avail",
                            "block_reason", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-OUT-007, SR-OUT-007, TC-OUT-007, FR-RES-014/SR-RES-014, FR-TEL-015 (10.2.4 köprü), "
                 "FR-TEN-004 (kota), FR-TST-006 (0.4.8 model), FR-IAM-006, FR-TEN-002, FR-REC-004, "
                 "BRD §9.13, BRD §10.3, BRD §15 (kapasite aşımı), SAD §15.2 Resource Manager, SAD §16, "
                 "SAD §20 (Little), API §A-10, ADR-001/002/012",
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
            print("kullanım: campaign_capacity_probe.py check <sample.json|dizin>")
            return 2
        return check_cmd(argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema_cmd()
    print("bilinmeyen komut: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
