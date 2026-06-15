#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.2 — Do-not-call / suppression gerçek zamanlı kontrol referans probe.

10. workstream'in (Outbound) Consent & uyumluluk motoru alt-bloğunun SUPPRESSION/DNC modülü ve
F2-Must outbound yeteneği. FR-TEL-014 ('Do-not-call ve opt-out listeleri gerçek zamanlı kontrol
edilmelidir') + FR-OUT-006 ('Müşterinin "bir daha aramayın" talebi anında uygulanmalıdır') +
SR-TEL-014 (yöntem T — 'arama anında gerçek zamanlı kontrol'; kabul: 'DNC'deki numaraya çağrı
başlatılmaz; %100 bloklama') + SR-OUT-006 (kabul: 'Opt-out sonrası numara DNC'ye eklenir; tekrar
aranmaz') + SAD §19.1 'do-not-call / suppression listesi (gerçek zamanlı)'ı sahiplenir. Modül
10.2.1 Consent ön-kontrolünün KARDEŞİdir (SR-OUT-003 'consent VE suppression' iki kapı). Bir
DETERMİNİSTİK FAIL-CLOSED MOTORUdur:

  SuppressionCheckRequest ──ülke profili çöz (required_sources,registry)──► beş kaynağı değerlendir
        │                                                                          │
        │                                       opt-out ∨ ulusal ∨ tenant ∨ kampanya ∨ global
        │                                                                          │
        │                                       ├─ any-hit ─────────────────────► BLOCK (block_reason)
        │                                       ├─ required unavailable ─────────► BLOCK (registry_unavailable, fail-closed)
        │                                       └─ hiçbiri vurmaz ──────────────► ALLOW (suppress yok)
        └──(stuck/tanımsız)──────────────────────────────────────────────────────► (K1 ihlali)

BEŞ KAYNAK (BRD §14.3, SR-TEL-014/SR-OUT-006 çekirdek): OPT-OUT (K2 — FR-OUT-006 ANINDA) ∨ ULUSAL
REGISTRY (K3 — İYS/TPS/CTPS gerçek zamanlı) ∨ TENANT DNC (K4) ∨ KAMPANYA SUPPRESSION (K5) ∨ GLOBAL
SUPPRESSION (K6); zorunlu kaynak doğrulanamazsa fail-closed (K7); %100 bloklama / ATLANAMAZ (K8:
bastırılmış numara çevrilmez; bypass=dnc_skip=BRD §15 kritik 'suppression atlama' alarmı). Her karar
deterministik+terminal (K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite + PII yok (K11);
sır/PII yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): arama öncesi CONSENT → 10.2.1 (FR-OUT-003; AND'lenir,
çözülmez); arama saati → 10.1.4 (FR-OUT-004); max deneme → 10.1.3; Caller ID → FR-TEL-004/005;
açılış metni → §14.2; versiyon → 10.1.6; profile ÇÖZÜMLEME → DPIA §5/SAD §19.3 (değerleri TÜKETİR);
opt-out KAYDI yazımı → 10.1.5 disposition/consent:manage (OKUR, yazmaz); İYS/TPS senkron → registry
adapter (TÜKETİR); audit store → 7.1.6/12.x; dialer ÇEVİRME → 10.1.x (karar döndürür, çevirmez).

Kullanım:
  dnc_suppression_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  dnc_suppression_probe.py check <sample>     Suppression motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  dnc_suppression_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  dnc_suppression_probe.py schema             Karar sözleşmesini yazdır

Determinizm: profil çözümü + ISO tarih karşılaştırması (sanal-saat call_time girdisi); Date.now/random YOK.
Stdlib-only. Sır/credential ve gerçek PII (müşteri adı/telefon/ham numara) üretilmez/yazılmaz (fixture
sentetik — FR-TST-008; suppression_key opak).
"""
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "dnc-suppression-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "dnc-suppression-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ALLOW", "BLOCK"]
TERMINAL = {"ALLOW", "BLOCK"}
SOURCES = ["opt_out", "national_registry", "tenant_dnc", "campaign_suppression", "global_suppression"]
BLOCK_REASONS = ["opt_out", "national_registry", "registry_unavailable", "tenant_dnc",
                 "campaign_suppression", "global_suppression", "cross_tenant"]
BLOCK_PRECEDENCE = ["opt_out", "national_registry", "registry_unavailable", "tenant_dnc",
                    "campaign_suppression", "global_suppression"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
CHANNEL = "voice"
REGISTRY_STATUS = ["not_listed", "listed", "unavailable"]

# Degrade (inject) — DOĞRU fail-closed/suppress davranışı bozan müdahaleler (her biri bir invariant'ı eler).
INJECTIONS = {"skip_dnc", "ignore_optout", "stale_optout", "ignore_national_registry",
              "ignore_tenant_dnc", "ignore_campaign_suppression", "ignore_global_suppression",
              "failopen_registry", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "dnc_skip", "optout_not_applied", "national_leak", "tenant_dnc_leak", "campaign_leak",
    "global_leak", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 9.x/10.1.x/10.2.1 deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# ISO tarih (2024-05-01...) ve yapısal kimlik/enum + opak suppression_key (sk-) + rezerve test bloğu beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|camp-|t-|ck-|corr-|sk-|res-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu + ISO tarihi eler (10.2.1 deseni)."""
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
# Deterministik yardımcılar — profil çözümü + sanal-saat tarih karşılaştırması (Date.now/random YOK).
# ════════════════════════════════════════════════════════════════════════════
def _parse_date(s):
    """ISO tarih/zaman → datetime (None ise None). Sanal saat: gerçek now() KULLANILMAZ."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _resolve_profile(sample, cfg):
    """country → profil. Açık profile_id öncelikli; yoksa country eşleşmesi; yoksa None.

    DNC'de bilinmeyen ülke fail-closed BLOCK ÜRETMEZ (consent'in aksine): iç suppression kaynakları
    (opt_out/tenant_dnc/campaign/global) ülkeden bağımsız değerlendirilir; profil None → required boş,
    registry None (dış ulusal registry zorunluluğu bilinmiyor)."""
    profiles = cfg.get("profiles", {})
    pid = sample.get("profile_id")
    if pid and pid in profiles:
        return pid, profiles[pid]
    country = sample.get("country")
    for name, prof in profiles.items():
        if prof.get("country") == country:
            return name, prof
    return None, None


def _optout_applies(opt, call_time, channel, category):
    """Opt-out (FR-OUT-006) çağrıya uygulanır mı: effective_at ≤ call_time ∧ scope kanalı/kategoriyi kapsar."""
    if not opt:
        return False
    eff = _parse_date(opt.get("effective_at"))
    call_dt = _parse_date(call_time)
    if eff is None or call_dt is None:
        return False
    if eff > call_dt:                       # gelecek-tarihli opt-out henüz yürürlükte değil
        return False
    scope = opt.get("scope", "all")
    if scope == "all" or scope is None:
        return True                          # 'bir daha aramayın' = blanket → tüm kanal/kategori bloklar
    if isinstance(scope, dict):
        chans = set(scope.get("channels", []))
        cats = set(scope.get("categories", []))
        if not chans and not cats:
            return True                      # boş kapsam = blanket
        return (channel in chans) or (category in cats)
    return True


# ════════════════════════════════════════════════════════════════════════════
def _config(sample):
    """Config = ana policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "profiles" in ov:
        cfg.setdefault("profiles", {}).update(ov["profiles"])
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek suppression/DNC senaryosunu yürüt → SuppressionDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed any-hit davranışı hesaplar; inject (degrade) doğru davranışı bozar ve
    eşleşen ihlal sayacını artırır (10.2.1 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    contact = sample.get("contact_key")
    campaign = sample.get("campaign_id")
    request_id = sample.get("request_id")
    country = sample.get("country")
    call_time = sample.get("call_time")
    call_channel = sample.get("call_channel", CHANNEL)
    category = sample.get("campaign_category")
    supp = sample.get("suppression", {}) or {}

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── K3/K7 (ülke): profil çöz (required_sources + registry) ──
    resolved_profile, prof = _resolve_profile(sample, cfg)
    required = set((prof or {}).get("required_sources", []))
    registry = (prof or {}).get("registry")

    # ── K12 (tenant izolasyonu): tenant-özel suppression yalnız aynı tenant'a ait okunur ──
    cross = False
    if "cross_tenant" in inject:
        cross = True
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        cross = True
        v["cross_tenant"] += 1
    for skey in ("opt_out", "tenant_dnc", "campaign_suppression"):
        entry = supp.get(skey)
        if isinstance(entry, dict) and entry.get("tenant_id") and entry.get("tenant_id") != tenant:
            cross = True
            v["cross_tenant"] += 1

    # ── Beş kaynak değerlendirme izi (K9 kanıtı) ──
    src_eval = {s: "clear" for s in SOURCES}

    # K2 opt-out (FR-OUT-006 ANINDA)
    opt = supp.get("opt_out")
    optout_hit = _optout_applies(opt, call_time, call_channel, category)
    if optout_hit:
        src_eval["opt_out"] = "hit"
        if "ignore_optout" in inject or "stale_optout" in inject:
            optout_hit = False
            v["optout_not_applied"] += 1     # opt-out görmezden gelindi/stale → FR-OUT-006 ihlali
            src_eval["opt_out"] = "IGNORED"

    # K3/K7 ulusal registry (FR-TEL-014 gerçek zamanlı)
    nat = supp.get("national_registry") or {}
    nat_status = nat.get("status", "not_listed")
    nat_required = "national_registry" in required
    nat_hit = False
    reg_unavail = False
    if nat_status == "listed":
        nat_hit = True
        src_eval["national_registry"] = "listed"
        if "ignore_national_registry" in inject:
            nat_hit = False
            v["national_leak"] += 1          # ulusal registry listed görmezden gelindi → K3 ihlali
            src_eval["national_registry"] = "IGNORED"
    elif nat_status == "unavailable":
        src_eval["national_registry"] = "unavailable"
        if nat_required:
            reg_unavail = True               # zorunlu kaynak doğrulanamadı → fail-closed
            if "failopen_registry" in inject:
                reg_unavail = False
                v["failopen"] += 1           # zorunlu kaynak yok ama ALLOW → K7 fail-open ihlali
                src_eval["national_registry"] = "FAILOPEN"
    else:
        src_eval["national_registry"] = "not_listed"

    # K4 tenant DNC
    tdnc = bool(supp.get("tenant_dnc"))
    if tdnc:
        src_eval["tenant_dnc"] = "hit"
        if "ignore_tenant_dnc" in inject:
            tdnc = False
            v["tenant_dnc_leak"] += 1        # tenant DNC görmezden gelindi → K4 ihlali
            src_eval["tenant_dnc"] = "IGNORED"

    # K5 kampanya suppression
    camp = bool(supp.get("campaign_suppression"))
    if camp:
        src_eval["campaign_suppression"] = "hit"
        if "ignore_campaign_suppression" in inject:
            camp = False
            v["campaign_leak"] += 1          # kampanya suppression görmezden gelindi → K5 ihlali
            src_eval["campaign_suppression"] = "IGNORED"

    # K6 global suppression
    glob = bool(supp.get("global_suppression"))
    if glob:
        src_eval["global_suppression"] = "hit"
        if "ignore_global_suppression" in inject:
            glob = False
            v["global_leak"] += 1            # global suppression görmezden gelindi → K6 ihlali
            src_eval["global_suppression"] = "IGNORED"

    # ── Any-hit fail-closed karar (block_precedence sırasıyla block_reason ata) ──
    hits = {
        "opt_out": optout_hit,
        "national_registry": nat_hit,
        "registry_unavailable": reg_unavail,
        "tenant_dnc": tdnc,
        "campaign_suppression": camp,
        "global_suppression": glob,
    }
    block_reason = None
    for reason in BLOCK_PRECEDENCE:
        if hits.get(reason):
            block_reason = reason
            break
    terminal = "BLOCK" if block_reason is not None else "ALLOW"

    # ── K8 (fail-closed / ATLANAMAZ / %100 bloklama): bypass → dnc_skip ihlali ──
    # skip_dnc: BLOCK olması gereken bir kararı 'ALLOW' yapıp DNC kontrolünü atlar.
    if "skip_dnc" in inject:
        if terminal == "BLOCK":
            terminal = "ALLOW"
            block_reason = None
        v["dnc_skip"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    allow = terminal == "ALLOW"
    suppressed = terminal == "BLOCK"
    dnc_ok = allow  # 10.2.1 consent kapısıyla AND girdisi (eligible = consent_ok AND dnc_ok AND hours_ok)

    # ── Kanıt (K9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "resolved_profile": resolved_profile,
        "required_sources": sorted(required),
        "registry": registry,
        "sources": src_eval,
        "suppressed": suppressed,
        "block_reason": block_reason,
        "terminal": terminal,
    }
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII YOK — yalnız opak suppression_key/enum/kimlik)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "result": terminal,
            "request_id": request_id,
            "campaign_id": campaign,
            "contact_key": contact,
            "suppression_key": sample.get("suppression_key"),
            "country": country,
            "registry": registry,
            "block_reason": block_reason,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "allow": allow,
        "suppressed": suppressed,
        "dnc_ok": dnc_ok,
        "resolved_profile": resolved_profile,
        "registry": registry,
        "block_reason": block_reason,
        "sources": src_eval,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "dnc_skip": "max_dnc_skip",
        "optout_not_applied": "max_optout_not_applied",
        "national_leak": "max_national_leak",
        "tenant_dnc_leak": "max_tenant_dnc_leak",
        "campaign_leak": "max_campaign_leak",
        "global_leak": "max_global_leak",
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
        for key in ("terminal", "allow", "suppressed", "block_reason", "dnc_ok"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s reason=%s profil=%s registry=%s suppressed=%s"
              % (res["terminal"], res["block_reason"], res["resolved_profile"], res["registry"], res["suppressed"]))
        print("   kaynaklar=%s" % res["sources"])
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
    for f in ("wbs", "phase", "priority", "trace", "placement", "sources", "decision",
              "block_reasons", "outcomes", "authorization", "gates", "observability",
              "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=10.2.2", spec.get("wbs") == "10.2.2")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-014 izlenir (DNC gerçek zamanlı)", "FR-TEL-014" in tr.get("fr", []))
    chk("FR-OUT-006 izlenir (opt-out anında)", "FR-OUT-006" in tr.get("fr", []))
    chk("FR-OUT-003 izlenir (consent köprü — 10.2.1)", "FR-OUT-003" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-TEL-014 izlenir", "SR-TEL-014" in tr.get("srs", []))
    chk("SR-OUT-006 izlenir", "SR-OUT-006" in tr.get("srs", []))
    chk("TC-TEL-014 izlenir", "TC-TEL-014" in tr.get("rtm", []))
    chk("TC-OUT-006 izlenir", "TC-OUT-006" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §19.1 Consent Engine izlenir", any("§19.1" in s for s in tr.get("sad", [])))
    chk("BRD §14.3 izlenir", any("§14.3" in s for s in tr.get("brd", [])))
    chk("DB §5.4 contact/consent izlenir", any("§5.4" in d for d in tr.get("db", [])))

    # 3) Beş kaynak (SR-TEL-014/SR-OUT-006 çekirdek)
    srcz = spec["sources"]
    src_ids = [d["id"] for d in srcz.get("list", [])]
    chk("beş kaynak tam (opt_out/national/tenant_dnc/campaign/global)", set(src_ids) == set(SOURCES))
    chk("değerlendirme any_hit_fail_closed", srcz.get("evaluation") == "any_hit_fail_closed")
    for d in srcz.get("list", []):
        chk("kaynak %s invariant+block_reason taşır" % d["id"],
            d.get("invariant") in INVARIANT_IDS and d.get("block_reason") in BLOCK_REASONS)
    chk("block_precedence tam", srcz.get("block_precedence") == BLOCK_PRECEDENCE)

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
    for gk in ("max_dnc_skip", "max_optout_not_applied", "max_national_leak", "max_tenant_dnc_leak",
               "max_campaign_leak", "max_global_leak", "max_failopen", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("dnc_skip_total metrik (K8 alarm)", "dnc_skip_total" in obs.get("metrics", []))
    chk("dnc_block_total metrik", "dnc_block_total" in obs.get("metrics", []))
    chk("optout_applied_total metrik (FR-OUT-006)", "optout_applied_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/suppression_key YÜKSEK kard (label değil)",
        "request_id" in hi and "suppression_key" in hi and "suppression_key" not in lo)
    chk("contact_key YÜKSEK kard (label değil)", "contact_key" in hi)
    chk("result/block_reason/registry DÜŞÜK kard (label uygun)",
        "result" in lo and "block_reason" in lo and "registry" in lo)
    chk("alarm dnc_skip ≤2dk", "dnc_skip" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/dnc-suppression-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        chk("config PROFILE-TR var (IYS, national required)",
            profs.get("PROFILE-TR", {}).get("registry") == "IYS"
            and "national_registry" in profs.get("PROFILE-TR", {}).get("required_sources", []))
        chk("config PROFILE-UK var (TPS_CTPS, national required)",
            profs.get("PROFILE-UK", {}).get("registry") == "TPS_CTPS"
            and "national_registry" in profs.get("PROFILE-UK", {}).get("required_sources", []))
        chk("config PROFILE-EU national_registry zorunlu DEĞİL",
            "national_registry" not in profs.get("PROFILE-EU", {}).get("required_sources", []))
        chk("config real_time=true ∧ propagation_lag=0 (FR-OUT-006 anında)",
            cfg.get("real_time") is True and cfg.get("propagation_lag_seconds") == 0)
        chk("config internal_sources dört iç kaynak",
            set(cfg.get("internal_sources", [])) == {"opt_out", "tenant_dnc", "campaign_suppression", "global_suppression"})
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
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "campaign_id": "camp-1", "contact_key": "ck-1", "suppression_key": "sk-1",
            "country": "TR", "call_channel": "voice", "campaign_category": "sales",
            "call_time": "2026-06-15T10:00:00",
            "suppression": {
                "opt_out": None, "tenant_dnc": False,
                "national_registry": {"status": "not_listed", "registry": "IYS"},
                "campaign_suppression": False, "global_suppression": False,
            },
        }
        d.update(kw)
        return d

    def supp(**kw):
        base = {"opt_out": None, "tenant_dnc": False,
                "national_registry": {"status": "not_listed", "registry": "IYS"},
                "campaign_suppression": False, "global_suppression": False}
        base.update(kw)
        return base

    # 1) happy — hiçbir listede yok → ALLOW (suppress yok)
    r = build(req(), spec)
    case("happy: ALLOW", r["terminal"] == "ALLOW")
    case("happy: suppressed=false", r["suppressed"] is False)
    case("happy: dnc_ok=true", r["dnc_ok"] is True)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit ALLOW (K10)", r["audit"] is not None and r["audit"]["result"] == "ALLOW")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm — aynı girdi birebir aynı sonuç
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) opt-out (K2, FR-OUT-006) — geçmiş effective_at → BLOCK opt_out (%100 bloklama)
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all"})), spec)
    case("opt-out: BLOCK opt_out", r["terminal"] == "BLOCK" and r["block_reason"] == "opt_out")
    case("opt-out: suppressed=true", r["suppressed"] is True)
    case("opt-out: ihlal yok (doğru reddetme)", all(x == 0 for x in r["violations"].values()))
    case("opt-out: kapı geçer (BLOCK doğru)", _gate_eval(r, G)[0] is True)

    # 3b) opt-out ANINDA — effective_at == call_time → BLOCK (propagasyon gecikmesi yok)
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T10:00:00", "scope": "all"})), spec)
    case("opt-out anında: effective==call_time → BLOCK", r["terminal"] == "BLOCK" and r["block_reason"] == "opt_out")

    # 3c) gelecek-tarihli opt-out → henüz yürürlükte değil → ALLOW
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-16T10:00:00", "scope": "all"})), spec)
    case("opt-out gelecek: henüz yürürlükte değil → ALLOW", r["terminal"] == "ALLOW")

    # 3d) kapsamlı opt-out — kanal voice → BLOCK; kategori dışı kanal → ALLOW
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00",
                                            "scope": {"channels": ["voice"], "categories": []}})), spec)
    case("opt-out scope voice → BLOCK", r["terminal"] == "BLOCK")
    r = build(req(call_channel="voice", campaign_category="support",
                  suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00",
                                            "scope": {"channels": ["sms"], "categories": ["marketing"]}})), spec)
    case("opt-out scope sms/marketing, voice/support çağrı → ALLOW", r["terminal"] == "ALLOW")

    # 4) ulusal registry (K3) — listed → BLOCK national_registry
    r = build(req(suppression=supp(national_registry={"status": "listed", "registry": "IYS"})), spec)
    case("national: BLOCK national_registry", r["terminal"] == "BLOCK" and r["block_reason"] == "national_registry")

    # 5) tenant DNC (K4) — vurursa BLOCK
    r = build(req(suppression=supp(tenant_dnc=True)), spec)
    case("tenant-dnc: BLOCK tenant_dnc", r["terminal"] == "BLOCK" and r["block_reason"] == "tenant_dnc")

    # 6) kampanya suppression (K5)
    r = build(req(suppression=supp(campaign_suppression=True)), spec)
    case("campaign: BLOCK campaign_suppression", r["terminal"] == "BLOCK" and r["block_reason"] == "campaign_suppression")

    # 7) global suppression (K6)
    r = build(req(suppression=supp(global_suppression=True)), spec)
    case("global: BLOCK global_suppression", r["terminal"] == "BLOCK" and r["block_reason"] == "global_suppression")

    # 8) fail-closed zorunlu kaynak (K7) — TR national_registry required + unavailable → BLOCK registry_unavailable
    r = build(req(suppression=supp(national_registry={"status": "unavailable", "registry": "IYS"})), spec)
    case("unavailable: BLOCK registry_unavailable", r["terminal"] == "BLOCK" and r["block_reason"] == "registry_unavailable")

    # 8b) EU national_registry zorunlu DEĞİL + unavailable → ALLOW (iç kaynaklar temiz)
    r = build(req(country="EU", profile_id="PROFILE-EU",
                  suppression=supp(national_registry={"status": "unavailable", "registry": "none"})), spec)
    case("eu-unavailable: zorunlu değil → ALLOW", r["terminal"] == "ALLOW")

    # 9) block_precedence — opt_out, national'dan önce gelir
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all"},
                                   national_registry={"status": "listed", "registry": "IYS"},
                                   tenant_dnc=True)), spec)
    case("precedence: opt_out önce", r["block_reason"] == "opt_out")

    # 10) bilinmeyen ülke — iç kaynaklar yine değerlendirilir; tenant_dnc → BLOCK
    r = build(req(country="ZZ", suppression=supp(tenant_dnc=True)), spec)
    case("unknown-country: iç kaynak yine → BLOCK tenant_dnc", r["terminal"] == "BLOCK" and r["block_reason"] == "tenant_dnc")
    # bilinmeyen ülke + temiz iç kaynak → ALLOW (DNC consent gibi fail-closed-on-country DEĞİL)
    r = build(req(country="ZZ"), spec)
    case("unknown-country temiz → ALLOW", r["terminal"] == "ALLOW")

    # ── degrade injection'ları → ihlal + kapı eler ──
    # 11) skip_dnc (K8 çekirdek) — BLOCK'u atla → dnc_skip ihlali
    r = build(req(suppression=supp(tenant_dnc=True)), spec, inject=["skip_dnc"])
    case("inject-skip: dnc_skip>0", r["violations"]["dnc_skip"] > 0)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-skip: terminal ALLOW'a zorlandı", r["terminal"] == "ALLOW")

    # 12) ignore_optout (K2)
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all"})),
              spec, inject=["ignore_optout"])
    case("inject-ignore-optout: optout_not_applied>0", r["violations"]["optout_not_applied"] > 0)
    case("inject-ignore-optout: kapı eler", _gate_eval(r, G)[0] is False)

    # 12b) stale_optout (K2) — gerçek zamanlı değil → optout_not_applied
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:59:00", "scope": "all"})),
              spec, inject=["stale_optout"])
    case("inject-stale-optout: optout_not_applied>0", r["violations"]["optout_not_applied"] > 0)

    # 13) ignore_national_registry (K3)
    r = build(req(suppression=supp(national_registry={"status": "listed", "registry": "IYS"})),
              spec, inject=["ignore_national_registry"])
    case("inject-national: national_leak>0", r["violations"]["national_leak"] > 0)
    case("inject-national: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) ignore_tenant_dnc (K4)
    r = build(req(suppression=supp(tenant_dnc=True)), spec, inject=["ignore_tenant_dnc"])
    case("inject-tenant: tenant_dnc_leak>0", r["violations"]["tenant_dnc_leak"] > 0)
    case("inject-tenant: kapı eler", _gate_eval(r, G)[0] is False)

    # 15) ignore_campaign_suppression (K5)
    r = build(req(suppression=supp(campaign_suppression=True)), spec, inject=["ignore_campaign_suppression"])
    case("inject-campaign: campaign_leak>0", r["violations"]["campaign_leak"] > 0)

    # 16) ignore_global_suppression (K6)
    r = build(req(suppression=supp(global_suppression=True)), spec, inject=["ignore_global_suppression"])
    case("inject-global: global_leak>0", r["violations"]["global_leak"] > 0)

    # 17) failopen_registry (K7) — zorunlu kaynak yok ama ALLOW
    r = build(req(suppression=supp(national_registry={"status": "unavailable", "registry": "IYS"})),
              spec, inject=["failopen_registry"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-failopen: terminal ALLOW (fail-open)", r["terminal"] == "ALLOW")

    # 18) cross_tenant (K12)
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all",
                                            "tenant_id": "t-foreign"})), spec)
    case("foreign-tenant-suppression: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 19) no_audit (K10)
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 20) kanıt (K9) — beş kaynak + profil + required taşır
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: beş kaynak taşır", set(r["evidence"]["sources"].keys()) == set(SOURCES))
    case("evidence: resolved_profile=PROFILE-TR", r["evidence"]["resolved_profile"] == "PROFILE-TR")
    case("evidence: registry=IYS", r["evidence"]["registry"] == "IYS")
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 21) audit (K10) — result + country + tenant taşır, ham PII yok
    case("audit: result taşır", r["audit"]["result"] == "ALLOW")
    case("audit: country taşır", r["audit"]["country"] == "TR")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad alanı yok", "customer_phone_value" not in json.dumps(r["audit"])
         and "customer_name" not in json.dumps(r["audit"]))
    case("audit: suppression_key opak (sk-)", str(r["audit"]["suppression_key"]).startswith("sk-"))

    # 22) dnc_ok = ALLOW (10.2.1 consent AND girdisi)
    r_allow = build(req(), spec)
    r_block = build(req(suppression=supp(tenant_dnc=True)), spec)
    case("dnc_ok: ALLOW→true", r_allow["dnc_ok"] is True)
    case("dnc_ok: BLOCK→false", r_block["dnc_ok"] is False)

    # 23) sızıntı tarayıcı: yapısal kimlik/opak-anahtar/ISO tarih temiz, ham PII/telefon yakalanır
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: sk-001 opak anahtar temiz", scan_leaks('{"suppression_key": "sk-001"}') == [])
    case("leak: ISO tarih temiz", scan_leaks('{"effective_at": "2026-06-15T10:00:00"}') == [])
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
        "module": "dnc-suppression (WBS 10.2.2 — FR-TEL-014 + FR-OUT-006 DNC/suppression gerçek zamanlı kontrol)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "sources": SOURCES,
        "block_precedence": BLOCK_PRECEDENCE,
        "block_reasons": BLOCK_REASONS,
        "registry_status": REGISTRY_STATUS,
        "decision": "resolve_profile(required_sources,registry) → eval5(opt_out,national,tenant_dnc,campaign,global) → "
                    "any_hit ⇒ BLOCK(reason) | required_unavailable ⇒ BLOCK(registry_unavailable) | else ⇒ ALLOW",
        "default": "BLOCK (fail-closed; any-hit veya zorunlu-kaynak doğrulanamadı)",
        "channel": CHANNEL,
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "campaign_id",
                           "contact_key", "suppression_key(opak)", "country", "call_channel(voice)",
                           "campaign_category", "call_time(ISO)",
                           "suppression{opt_out{effective_at(ISO),scope:all|{channels[],categories[]},tenant_id?}, "
                           "tenant_dnc(bool|{added_at,tenant_id?}), national_registry{status:not_listed|listed|unavailable,registry}, "
                           "campaign_suppression(bool|{campaign_id,tenant_id?}), global_suppression(bool|{reason})}",
                           "profile_id?", "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "allow", "suppressed", "dnc_ok", "resolved_profile", "registry",
                            "block_reason", "sources", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-TEL-014, FR-OUT-006, SR-TEL-014, SR-OUT-006, TC-TEL-014, TC-OUT-006, FR-OUT-003 (köprü), "
                 "FR-IAM-006, FR-TEN-002, FR-REC-004, BRD §14.3, SAD §19.1, DPIA §5.3 cp.outbound.*, "
                 "DB §5.4 contact.do_not_call/consent.state=withdrawn, API §A-10, ADR-001/002/012",
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
            print("kullanım: dnc_suppression_probe.py check <sample.json|dizin>")
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
