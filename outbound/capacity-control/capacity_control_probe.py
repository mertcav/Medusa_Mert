#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.4 — Silent/abandoned call önleme (kapasite kontrolü) referans probe.

10. workstream'in (Outbound) Consent & uyumluluk motoru alt-bloğunun KAPASİTE/ABANDONED-CALL
(capacity-control) modülü ve F2-Must outbound yeteneği. FR-TEL-015 ('Silent / abandoned call
oluşumunu önleyici kapasite kontrolü bulunmalıdır') + SR-TEL-015 (yöntem T — 'Silent/abandoned
call'u önleyici kapasite kontrolü uygulanır'; kabul: 'Kapasite < kampanya hızı iken abandoned oranı
yapılandırılan eşik altında kalır') + SAD §19.1 'silent/abandoned call önleme (kapasite kontrolü)'nü
sahiplenir. Modül 10.2.1 Consent + 10.2.2 DNC + 10.2.3 arama saati modüllerinin KARDEŞİdir
(eligible = consent_ok AND dnc_ok AND hours_ok AND capacity_ok). Bir DETERMİNİSTİK FAIL-CLOSED
MOTORUdur:

  CapacityCheckRequest ──kapasite profili çöz (threshold,overdial,reserve)──► kapasite durumu hesapla
        │                          │                                                   │
        │            free_handlers = total − active; over-dial in_flight'i sayar (K2)  │
        │                          │                                                   │
        │           ├─ profil çözülemez ───────────────────► BLOCK (unknown_profile, fail-closed)
        │           └─ all-pass ─────────────────────────────────────────────────────► ALLOW
        │           └─ any-fail ─────────────────────────────────────────────────────► BLOCK (block_reason)
        └──(stuck/tanımsız)──────────────────────────────────────────────────────────► (K1 ihlali)

DÖRT KONJONKTİF KURAL (BRD §14.3, SR-TEL-015 çekirdek): REZERVE HEADROOM (K3 — free ≥ reserve_min) ∧
ABANDONED ORANI (K4 — < silent_call_threshold) ∧ OVER-DIAL CAP (K5 — in_flight+1 ≤ free×ratio) ∧
TRUNK KANALI (K6 — boş kanal); değerlendirme doğru kapasite muhasebesiyle (K2 — meşgul handler/in_flight
ATLANAMAZ); profil çözülemezse fail-closed (K7); kapasitesiz çağrı ASLA başlatılmaz / ATLANAMAZ
(K8: bypass=capacity_skip=BRD §15 kritik 'silent call oluşması' alarmı). Her karar deterministik+terminal
(K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite + PII yok (K11); sır/PII yok + tenant
izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): consent → 10.2.1; DNC → 10.2.2; arama saati → 10.2.3;
KAMPANYA-DÜZEYİ kapasite ≤ agent+trunk + backpressure → 10.2.6 (BLOCK pace girdisi); admission/graceful
degradation → FR-RES-014 + 0.4.8; AMD → FR-TEL-010; retry/callback → 2.1.8; profile ÇÖZÜMLEME →
DPIA §5/SAD §19.3 (değerleri TÜKETİR); kapasite SNAPSHOT → runtime telemetri 0.4.7/0.4.8 (OKUR);
audit store → 7.1.6/12.x; dialer ÇEVİRME/pace → 10.1.x (karar döndürür, çevirmez).

Kullanım:
  capacity_control_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  capacity_control_probe.py check <sample>     Kapasite motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  capacity_control_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  capacity_control_probe.py schema             Karar sözleşmesini yazdır

Determinizm: profil çözümü + tamsayı/oran kapasite muhasebesi (sanal snapshot girdisi); Date.now/random
YOK. Stdlib-only. Sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) üretilmez/yazılmaz
(fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "capacity-control-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "capacity-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ALLOW", "BLOCK"]
TERMINAL = {"ALLOW", "BLOCK"}
RULES = ["reserved_headroom", "abandon_rate", "overdial_cap", "trunk_channel"]
BLOCK_REASONS = ["no_capacity", "abandon_rate_exceeded", "overdial_cap", "trunk_exhausted",
                 "unknown_profile", "cross_tenant"]
BLOCK_PRECEDENCE = ["unknown_profile", "abandon_rate_exceeded", "no_capacity", "overdial_cap", "trunk_exhausted"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
CHANNEL = "voice"

# Degrade (inject) — DOĞRU fail-closed/kapasite davranışını bozan müdahaleler (her biri bir invariant'ı eler).
INJECTIONS = {"skip_capacity", "stale_capacity", "ignore_headroom", "ignore_abandon_rate",
              "ignore_overdial", "ignore_trunk", "failopen_profile", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "capacity_skip", "capacity_error", "no_capacity_leak", "abandon_rate_leak",
    "overdial_leak", "trunk_leak", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 10.2.1/10.2.2/10.2.3 deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# Kapasite sayıları (kısa tamsayı), oranlar (0.03), yapısal kimlik/enum, rezerve test bloğu beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|camp-|t-|ck-|corr-|res-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (10.2.3 deseni)."""
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
    try:
        return v if v is not None else default
    except (TypeError, ValueError):
        return default


def _config(sample):
    """Config = ana policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "profiles" in ov:
        cfg.setdefault("profiles", {}).update(ov["profiles"])
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek kapasite senaryosunu yürüt → CapacityDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed all-pass kapasite davranışı hesaplar; inject (degrade) doğru davranışı
    bozar ve eşleşen ihlal sayacını artırır (10.2.3 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    contact = sample.get("contact_key")
    campaign = sample.get("campaign_id")
    request_id = sample.get("request_id")
    country = sample.get("country")
    category = sample.get("campaign_category")

    # Kapasite snapshot (runtime telemetri girdisi; deterministik sanal değerler)
    total_handlers = _num(sample.get("total_handlers"))
    active_calls = _num(sample.get("active_calls"))
    in_flight_dials = _num(sample.get("in_flight_dials"))
    trunk_active = _num(sample.get("trunk_channels_active"))
    trunk_capacity = _num(sample.get("trunk_capacity"))
    rolling_connected = _num(sample.get("rolling_connected"))
    rolling_abandoned = _num(sample.get("rolling_abandoned"))

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── K12 (tenant izolasyonu): kapasite profili/snapshot yalnız aynı tenant'a ait okunur ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── Profil çöz (silent_call_threshold + max_overdial_ratio + reserve_min) ──
    resolved_profile, prof = _resolve_profile(sample, cfg)

    rule_eval = {r: "n/a" for r in RULES}
    block_reason = None
    free_handlers = None
    abandon_rate = None
    overdial_ratio = None

    # ── K7 fail-closed: profil çözümlenemedi → unknown_profile (fail-open YASAK) ──
    profile_unresolved = (prof is None)
    if profile_unresolved:
        if "failopen_profile" in inject:
            v["failopen"] += 1               # profil çözülemedi ama ALLOW → K7 fail-open ihlali
            prof = {"silent_call_threshold": 1.0, "max_overdial_ratio": 1e9, "reserve_min": 0}
            profile_unresolved = False
        else:
            block_reason = "unknown_profile"

    if not profile_unresolved:
        threshold = prof.get("silent_call_threshold", 0.0)
        max_overdial = prof.get("max_overdial_ratio", 0.0)
        reserve_min = prof.get("reserve_min", 1)

        # ── K2 doğru kapasite muhasebesi: free = total − active; over-dial in_flight'i sayar ──
        free_handlers = total_handlers - active_calls
        # abandon_rate: açık predicted_abandon_rate öncelikli; yoksa rolling oranı
        if sample.get("predicted_abandon_rate") is not None:
            abandon_rate = sample["predicted_abandon_rate"]
        else:
            abandon_rate = rolling_abandoned / max(1, rolling_connected)
        # stale_capacity (K2): eski/yanlış snapshot — in_flight'i over-dial muhasebesinden DÜŞER
        effective_in_flight = in_flight_dials
        if "stale_capacity" in inject:
            effective_in_flight = 0          # in_flight atlanır → over-dial under-count → silent call
            v["capacity_error"] += 1
        overdial_ratio = (effective_in_flight + 1) / float(max(1, free_handlers)) if free_handlers > 0 else float("inf")

        # K3 rezerve headroom (free ≥ reserve_min)
        headroom_ok = free_handlers >= reserve_min
        if not headroom_ok:
            rule_eval["reserved_headroom"] = "NO_CAP(free=%d)" % free_handlers
            if "ignore_headroom" in inject:
                headroom_ok = True
                v["no_capacity_leak"] += 1
                rule_eval["reserved_headroom"] = "IGNORED"
        else:
            rule_eval["reserved_headroom"] = "ok(free=%d)" % free_handlers

        # K4 abandoned oranı (< silent_call_threshold)
        abandon_ok = abandon_rate < threshold
        if not abandon_ok:
            rule_eval["abandon_rate"] = "EXCEED(%.4f≥%.4f)" % (abandon_rate, threshold)
            if "ignore_abandon_rate" in inject:
                abandon_ok = True
                v["abandon_rate_leak"] += 1
                rule_eval["abandon_rate"] = "IGNORED"
        else:
            rule_eval["abandon_rate"] = "ok(%.4f)" % abandon_rate

        # K5 over-dial cap (in_flight+1 ≤ free×ratio); free≤0 durumunu K3 headroom sahiplenir (na→ok)
        overdial_ok = True if free_handlers <= 0 else ((effective_in_flight + 1) <= (free_handlers * max_overdial))
        if not overdial_ok:
            rule_eval["overdial_cap"] = "OVER(%.2f>%.2f)" % (overdial_ratio, max_overdial)
            if "ignore_overdial" in inject:
                overdial_ok = True
                v["overdial_leak"] += 1
                rule_eval["overdial_cap"] = "IGNORED"
        else:
            rule_eval["overdial_cap"] = "ok(%.2f)" % overdial_ratio

        # K6 trunk kanalı (trunk_active+1 ≤ trunk_capacity)
        trunk_ok = (trunk_active + 1) <= trunk_capacity
        if not trunk_ok:
            rule_eval["trunk_channel"] = "EXHAUST(%d/%d)" % (trunk_active, trunk_capacity)
            if "ignore_trunk" in inject:
                trunk_ok = True
                v["trunk_leak"] += 1
                rule_eval["trunk_channel"] = "IGNORED"
        else:
            rule_eval["trunk_channel"] = "ok(%d/%d)" % (trunk_active, trunk_capacity)

        # ── All-pass fail-closed karar (block_precedence sırasıyla block_reason ata) ──
        fails = {
            "abandon_rate_exceeded": not abandon_ok,
            "no_capacity": not headroom_ok,
            "overdial_cap": not overdial_ok,
            "trunk_exhausted": not trunk_ok,
        }
        for reason in BLOCK_PRECEDENCE:
            if fails.get(reason):
                block_reason = reason
                break

    terminal = "BLOCK" if block_reason is not None else "ALLOW"

    # ── K8 (fail-closed / ATLANAMAZ): bypass → capacity_skip ihlali ──
    # skip_capacity: BLOCK olması gereken bir kararı 'ALLOW' yapıp kapasite kontrolünü atlar (silent call).
    if "skip_capacity" in inject:
        if terminal == "BLOCK":
            terminal = "ALLOW"
            block_reason = None
        v["capacity_skip"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    allow = terminal == "ALLOW"
    capacity_ok = allow  # 10.2.1/10.2.2/10.2.3 AND girdisi (eligible = ... AND capacity_ok)

    # ── Kanıt (K9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "resolved_profile": resolved_profile,
        "free_handlers": free_handlers,
        "abandon_rate": abandon_rate,
        "overdial_ratio": (None if overdial_ratio in (None, float("inf")) else round(overdial_ratio, 4)),
        "trunk": "%d/%d" % (trunk_active, trunk_capacity),
        "rules": rule_eval,
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
            "contact_key": contact,
            "country": country,
            "campaign_category": category,
            "free_handlers": free_handlers,
            "abandon_rate": abandon_rate,
            "block_reason": block_reason,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "allow": allow,
        "capacity_ok": capacity_ok,
        "resolved_profile": resolved_profile,
        "free_handlers": free_handlers,
        "abandon_rate": abandon_rate,
        "overdial_ratio": (None if overdial_ratio in (None, float("inf")) else round(overdial_ratio, 4)),
        "block_reason": block_reason,
        "rules": rule_eval,
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
        "no_capacity_leak": "max_no_capacity_leak",
        "abandon_rate_leak": "max_abandon_rate_leak",
        "overdial_leak": "max_overdial_leak",
        "trunk_leak": "max_trunk_leak",
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
        for key in ("terminal", "allow", "block_reason", "capacity_ok"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s reason=%s profil=%s free=%s abandon=%s overdial=%s"
              % (res["terminal"], res["block_reason"], res["resolved_profile"],
                 res["free_handlers"], res["abandon_rate"], res["overdial_ratio"]))
        print("   kurallar=%s" % res["rules"])
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
    chk("wbs=10.2.4", spec.get("wbs") == "10.2.4")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-015 izlenir (silent/abandoned kapasite)", "FR-TEL-015" in tr.get("fr", []))
    chk("FR-OUT-007 izlenir (kampanya kapasitesi — 10.2.6 köprü)", "FR-OUT-007" in tr.get("fr", []))
    chk("FR-RES-014 izlenir (backpressure)", "FR-RES-014" in tr.get("fr", []))
    chk("FR-OUT-003 izlenir (consent köprü — 10.2.1)", "FR-OUT-003" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-TEL-015 izlenir", "SR-TEL-015" in tr.get("srs", []))
    chk("SR-OUT-007 izlenir (10.2.6 köprü)", "SR-OUT-007" in tr.get("srs", []))
    chk("TC-TEL-015 izlenir", "TC-TEL-015" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §19.1 Consent Engine izlenir", any("§19.1" in s for s in tr.get("sad", [])))
    chk("BRD §15 silent call alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))
    chk("BRD §14.3 izlenir", any("§14.3" in s for s in tr.get("brd", [])))

    # 3) Dört kural (SR-TEL-015 çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dört kural tam (reserved_headroom/abandon_rate/overdial_cap/trunk_channel)", set(rule_ids) == set(RULES))
    chk("değerlendirme all_pass_fail_closed", rz.get("evaluation") == "all_pass_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant+block_reason taşır" % d["id"],
            d.get("invariant") in INVARIANT_IDS and d.get("block_reason") in BLOCK_REASONS)
    chk("block_precedence tam", rz.get("block_precedence") == BLOCK_PRECEDENCE)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")

    # 5) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar ALLOW+BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam", br == set(BLOCK_REASONS))

    # 6) Yetki — config-düzeyi consent:manage, per-call otomatik gate
    az = spec["authorization"]
    chk("policy_permission=consent:manage", az.get("policy_permission") == "consent:manage")
    chk("per_call_check otomatik gate", "automatic_gate" in az.get("per_call_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_capacity_skip", "max_capacity_error", "max_no_capacity_leak", "max_abandon_rate_leak",
               "max_overdial_leak", "max_trunk_leak", "max_failopen", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("capacity_skip_total metrik (K8 alarm)", "capacity_skip_total" in obs.get("metrics", []))
    chk("capacity_block_total metrik", "capacity_block_total" in obs.get("metrics", []))
    chk("silent_call_total metrik (BRD §15 alarm)", "silent_call_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/contact_key YÜKSEK kard (label değil)",
        "request_id" in hi and "contact_key" in hi and "contact_key" not in lo)
    chk("result/block_reason/country/campaign_category DÜŞÜK kard (label uygun)",
        "result" in lo and "block_reason" in lo and "country" in lo and "campaign_category" in lo)
    chk("alarm silent_call/capacity_skip ≤2dk", "silent_call" in obs.get("alarm", "") or "capacity_skip" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/capacity-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        tr_p = profs.get("PROFILE-TR", {})
        chk("config PROFILE-TR var (threshold+overdial+reserve)",
            tr_p.get("silent_call_threshold") == 0.03
            and tr_p.get("max_overdial_ratio") == 3.0
            and tr_p.get("reserve_min") == 1)
        chk("config PROFILE-UK Ofcom (threshold 0.03 + sıkı pacing 2.5)",
            profs.get("PROFILE-UK", {}).get("silent_call_threshold") == 0.03
            and profs.get("PROFILE-UK", {}).get("max_overdial_ratio") == 2.5)
        chk("config PROFILE-EU daha sıkı (threshold 0.02)",
            profs.get("PROFILE-EU", {}).get("silent_call_threshold") == 0.02)
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
        # Varsayılan: TR sağlıklı snapshot → free=6, abandon=1%, overdial içinde, trunk boş → ALLOW
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "campaign_id": "camp-1", "contact_key": "ck-1",
            "country": "TR", "call_channel": "voice", "campaign_category": "sales",
            "total_handlers": 10, "active_calls": 4, "in_flight_dials": 6,
            "trunk_channels_active": 8, "trunk_capacity": 30,
            "rolling_connected": 200, "rolling_abandoned": 2,
        }
        d.update(kw)
        return d

    # 1) happy — sağlıklı kapasite → ALLOW
    r = build(req(), spec)
    case("happy: ALLOW", r["terminal"] == "ALLOW")
    case("happy: capacity_ok=true", r["capacity_ok"] is True)
    case("happy: free_handlers=6", r["free_handlers"] == 6)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit ALLOW (K10)", r["audit"] is not None and r["audit"]["result"] == "ALLOW")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm — aynı girdi birebir aynı sonuç
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) K3 rezerve headroom — tüm handler meşgul (free=0) → BLOCK no_capacity (silent call)
    r = build(req(total_handlers=5, active_calls=5, in_flight_dials=0), spec)
    case("headroom: free=0 → BLOCK no_capacity", r["terminal"] == "BLOCK" and r["block_reason"] == "no_capacity")
    # boundary: free == reserve_min (1) → ALLOW
    r = build(req(total_handlers=5, active_calls=4, in_flight_dials=2), spec)
    case("headroom: free=1 (==reserve_min) → ALLOW", r["terminal"] == "ALLOW")

    # 3b) ignore_headroom injection → no_capacity_leak (silent call ihlali)
    r = build(req(total_handlers=5, active_calls=5, in_flight_dials=0), spec, inject=["ignore_headroom"])
    case("inject-headroom: no_capacity_leak>0", r["violations"]["no_capacity_leak"] > 0)
    case("inject-headroom: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-headroom: sıfır kapasiteye yanlış ALLOW", r["terminal"] == "ALLOW")

    # 4) K4 abandoned oranı — 4/100 = 4% ≥ 3% → BLOCK abandon_rate_exceeded
    r = build(req(rolling_connected=100, rolling_abandoned=4, active_calls=2), spec)
    case("abandon: 4% ≥ 3% → BLOCK abandon_rate_exceeded",
         r["terminal"] == "BLOCK" and r["block_reason"] == "abandon_rate_exceeded")
    # tam eşik 3% → BLOCK (eşik altında KALMALI; eşige ulaşma da blok)
    r = build(req(rolling_connected=100, rolling_abandoned=3, active_calls=2), spec)
    case("abandon: tam 3% (eşik) → BLOCK", r["terminal"] == "BLOCK" and r["block_reason"] == "abandon_rate_exceeded")
    # 2% < 3% → ALLOW
    r = build(req(rolling_connected=100, rolling_abandoned=2, active_calls=2), spec)
    case("abandon: 2% < 3% → ALLOW", r["terminal"] == "ALLOW")
    # predicted_abandon_rate override
    r = build(req(predicted_abandon_rate=0.05, active_calls=2), spec)
    case("abandon: predicted 5% → BLOCK", r["terminal"] == "BLOCK" and r["block_reason"] == "abandon_rate_exceeded")
    r = build(req(rolling_connected=100, rolling_abandoned=4, active_calls=2), spec, inject=["ignore_abandon_rate"])
    case("inject-abandon: abandon_rate_leak>0", r["violations"]["abandon_rate_leak"] > 0)
    case("inject-abandon: kapı eler", _gate_eval(r, G)[0] is False)

    # 5) K5 over-dial cap — free=10, ratio=3 → bound 30; in_flight=30 → 31>30 BLOCK overdial_cap
    r = build(req(total_handlers=10, active_calls=0, in_flight_dials=30), spec)
    case("overdial: in_flight 30 > free×ratio 30 → BLOCK overdial_cap",
         r["terminal"] == "BLOCK" and r["block_reason"] == "overdial_cap")
    # sınır: in_flight=29 → 30<=30 → ALLOW
    r = build(req(total_handlers=10, active_calls=0, in_flight_dials=29), spec)
    case("overdial: in_flight 29 → 30≤30 → ALLOW", r["terminal"] == "ALLOW")
    r = build(req(total_handlers=10, active_calls=0, in_flight_dials=30), spec, inject=["ignore_overdial"])
    case("inject-overdial: overdial_leak>0", r["violations"]["overdial_leak"] > 0)

    # 5b) K2 stale_capacity — over-dial muhasebesinden in_flight atlanır → BLOCK→ALLOW + capacity_error
    r = build(req(total_handlers=10, active_calls=0, in_flight_dials=30), spec, inject=["stale_capacity"])
    case("inject-stale: capacity_error>0", r["violations"]["capacity_error"] > 0)
    case("inject-stale: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-stale: over-dial under-count → yanlış ALLOW", r["terminal"] == "ALLOW")

    # 6) K6 trunk — trunk_active=20, trunk_capacity=20 → 21>20 BLOCK trunk_exhausted
    r = build(req(trunk_channels_active=20, trunk_capacity=20), spec)
    case("trunk: 20/20 dolu → BLOCK trunk_exhausted",
         r["terminal"] == "BLOCK" and r["block_reason"] == "trunk_exhausted")
    r = build(req(trunk_channels_active=20, trunk_capacity=20), spec, inject=["ignore_trunk"])
    case("inject-trunk: trunk_leak>0", r["violations"]["trunk_leak"] > 0)

    # 7) K7 fail-closed bilinmeyen profil — bilinmeyen ülke → BLOCK unknown_profile
    r = build(req(country="ZZ"), spec)
    case("unknown-profile: bilinmeyen ülke → BLOCK unknown_profile",
         r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_profile")
    r = build(req(country="ZZ"), spec, inject=["failopen_profile"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 8) block_precedence — abandon, no_capacity'den önce gelir (her ikisi de ihlal)
    r = build(req(total_handlers=5, active_calls=5, in_flight_dials=0,
                  rolling_connected=100, rolling_abandoned=5), spec)
    case("precedence: abandon önce gelir (no_capacity'den)", r["block_reason"] == "abandon_rate_exceeded")

    # 9) UK Ofcom — 2% < 3% ALLOW; 3% BLOCK
    r = build(req(country="UK", profile_id="PROFILE-UK", rolling_connected=100, rolling_abandoned=2, active_calls=2), spec)
    case("uk-ofcom: 2% → ALLOW", r["terminal"] == "ALLOW")
    r = build(req(country="UK", profile_id="PROFILE-UK", rolling_connected=100, rolling_abandoned=3, active_calls=2), spec)
    case("uk-ofcom: 3% → BLOCK abandon_rate_exceeded", r["block_reason"] == "abandon_rate_exceeded")

    # 9b) EU daha sıkı — 2.5% ≥ 2% eşik → BLOCK
    r = build(req(country="EU", profile_id="PROFILE-EU", rolling_connected=200, rolling_abandoned=5, active_calls=2), spec)
    case("eu-strict: 2.5% ≥ 2% → BLOCK", r["block_reason"] == "abandon_rate_exceeded")

    # ── degrade injection'ları → ihlal + kapı eler ──
    # 10) skip_capacity (K8 çekirdek) — BLOCK'u atla → capacity_skip ihlali
    r = build(req(total_handlers=5, active_calls=5, in_flight_dials=0), spec, inject=["skip_capacity"])
    case("inject-skip: capacity_skip>0", r["violations"]["capacity_skip"] > 0)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-skip: terminal ALLOW'a zorlandı", r["terminal"] == "ALLOW")

    # 11) cross_tenant (K12)
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 12) no_audit (K10)
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 13) kanıt (K9) — dört kural + profil + free + abandon + trunk taşır
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: dört kural taşır", set(r["evidence"]["rules"].keys()) == set(RULES))
    case("evidence: resolved_profile=PROFILE-TR", r["evidence"]["resolved_profile"] == "PROFILE-TR")
    case("evidence: free_handlers taşır", r["evidence"]["free_handlers"] == 6)
    case("evidence: abandon_rate taşır", r["evidence"]["abandon_rate"] is not None)
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 14) audit (K10) — result + country + tenant taşır, ham PII yok
    case("audit: result taşır", r["audit"]["result"] == "ALLOW")
    case("audit: country taşır", r["audit"]["country"] == "TR")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad alanı yok", "customer_phone_value" not in json.dumps(r["audit"])
         and "customer_name" not in json.dumps(r["audit"]))

    # 15) capacity_ok = ALLOW (10.2.1/10.2.2/10.2.3 AND girdisi)
    r_allow = build(req(), spec)
    r_block = build(req(total_handlers=5, active_calls=5, in_flight_dials=0), spec)
    case("capacity_ok: ALLOW→true", r_allow["capacity_ok"] is True)
    case("capacity_ok: BLOCK→false", r_block["capacity_ok"] is False)

    # 16) sızıntı tarayıcı: yapısal kimlik/kapasite sayısı/oran temiz, ham PII/telefon yakalanır
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: kapasite sayısı temiz", scan_leaks('{"total_handlers": 10, "active_calls": 4}') == [])
    case("leak: oran temiz", scan_leaks('{"silent_call_threshold": 0.03}') == [])
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
        "module": "capacity-control (WBS 10.2.4 — FR-TEL-015 silent/abandoned call önleme [kapasite kontrolü])",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "block_precedence": BLOCK_PRECEDENCE,
        "block_reasons": BLOCK_REASONS,
        "decision": "resolve_profile(silent_call_threshold,max_overdial_ratio,reserve_min) | unresolved ⇒ "
                    "BLOCK(unknown_profile) → state(free_handlers=total−active, abandon_rate, in_flight) → "
                    "eval4(reserved_headroom,abandon_rate,overdial_cap,trunk_channel) → "
                    "all_pass ⇒ ALLOW | any_fail ⇒ BLOCK(reason)",
        "default": "BLOCK (fail-closed; bir kural ihlal veya profil çözümlenemedi)",
        "channel": CHANNEL,
        "capacity_state": "free_handlers = total_handlers − active_calls; "
                          "abandon_rate = predicted_abandon_rate | rolling_abandoned/max(1,rolling_connected); "
                          "overdial: in_flight_dials + 1 ≤ free_handlers × max_overdial_ratio",
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "campaign_id",
                           "contact_key", "country", "call_channel(voice)", "campaign_category",
                           "total_handlers", "active_calls", "in_flight_dials",
                           "trunk_channels_active", "trunk_capacity",
                           "rolling_connected", "rolling_abandoned", "predicted_abandon_rate?",
                           "profile_id?", "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "allow", "capacity_ok", "resolved_profile", "free_handlers",
                            "abandon_rate", "overdial_ratio", "block_reason", "rules", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-TEL-015, SR-TEL-015, TC-TEL-015, FR-OUT-007/SR-OUT-007 (10.2.6 köprü), FR-RES-014, "
                 "FR-OUT-003 (köprü), FR-IAM-006, FR-TEN-002, FR-REC-004, BRD §14.3, BRD §15 (silent call), "
                 "SAD §19.1, SAD §20, DPIA §5.3 cp.outbound.silent_call_threshold, API §A-10, ADR-001/002/012",
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
            print("kullanım: capacity_control_probe.py check <sample.json|dizin>")
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
