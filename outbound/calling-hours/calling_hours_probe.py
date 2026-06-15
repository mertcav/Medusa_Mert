#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.3 — Ülke/bölge arama saati kuralları referans probe.

10. workstream'in (Outbound) Consent & uyumluluk motoru alt-bloğunun ARAMA SAATİ (calling-hours)
modülü ve F2-Must outbound yeteneği. FR-TEL-013 ('Outbound arama saatleri ülke ve müşteri bazında
sınırlandırılmalıdır') + FR-OUT-004 ('Ülke ve bölgeye göre arama saatleri uygulanmalıdır') +
SR-TEL-013 (yöntem T — 'ülke/müşteri bazında sınırlanır; izinli saat dışı arama yapılmaz'; kabul:
'Saat-dışı denemesi engellenir') + SR-OUT-004 (kabul: 'İzinli saat dışı arama engellenir') +
SAD §19.1 'izin verilen saat (ülke/bölge)'i sahiplenir. Modül 10.2.1 Consent ön-kontrol + 10.2.2
DNC/suppression'ın KARDEŞİdir (eligible = consent_ok AND dnc_ok AND hours_ok). Bir DETERMİNİSTİK
FAIL-CLOSED MOTORUdur:

  CallingHoursCheckRequest ──ülke/bölge profili çöz (tz,window,weekdays,blackout)──► YEREL saate çevir
        │                          │                                                       │
        │              bölge → utc_offset_minutes (FR-OUT-004)            blackout ∧ weekday ∧ window ∧ müşteri
        │                          │                                                       │
        │           ├─ bölge çözülemez ──────────────► BLOCK (unknown_region, fail-closed) │
        │           └─ all-pass ─────────────────────────────────────────────────────────► ALLOW
        │           └─ any-fail ─────────────────────────────────────────────────────────► BLOCK (block_reason)
        └──(stuck/tanımsız)──────────────────────────────────────────────────────────────► (K1 ihlali)

DÖRT KONJONKTİF KURAL (BRD §14.3, SR-TEL-013/SR-OUT-004 çekirdek): GÜNLÜK PENCERE (K3 — yerel saat
[start,end)) ∧ HAFTANIN GÜNÜ (K4) ∧ BLACKOUT/TATİL (K5) ∧ MÜŞTERİ PENCERESİ (K6 — FR-TEL-013 müşteri
bazında); değerlendirme HER ZAMAN contact YEREL saatinde (K2 — FR-OUT-004 bölge bazlı, sunucu/UTC
DEĞİL); bölge çözülemezse fail-closed (K7); saat-dışı çağrı ASLA başlatılmaz / ATLANAMAZ (K8: bypass=
hours_skip=BRD §15 kritik 'arama saati kontrolü atlama' alarmı). Her karar deterministik+terminal (K1)
+ kanıt (K9) + audit (K10); metrik düşük-kardinalite + PII yok (K11); sır/PII yok + tenant izolasyonu
(K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): arama öncesi CONSENT → 10.2.1 (FR-OUT-003; AND'lenir);
DNC/suppression → 10.2.2 (FR-TEL-014; AND'lenir); max deneme → 10.1.3; Caller ID → FR-TEL-004/005;
açılış metni → §14.2; versiyon → 10.1.6; kapasite/abandoned → 10.2.4; profile ÇÖZÜMLEME → DPIA §5/
SAD §19.3 (değerleri TÜKETİR); IANA/DST → tz adapter (TÜKETİR); contact region KAYDI → DB §5.4 (OKUR);
audit store → 7.1.6/12.x; dialer ÇEVİRME/yeniden-zamanlama → 10.1.x + 2.1.8 (karar döndürür, çevirmez).

Kullanım:
  calling_hours_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  calling_hours_probe.py check <sample>     Arama saati motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  calling_hours_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  calling_hours_probe.py schema             Karar sözleşmesini yazdır

Determinizm: profil çözümü + fixed-offset yerel saat çevirme + ISO tarih-saat karşılaştırması
(sanal-saat call_time girdisi); Date.now/random YOK. Stdlib-only. Sır/credential ve gerçek PII
(müşteri adı/telefon/ham numara) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "calling-hours-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "calling-hours-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ALLOW", "BLOCK"]
TERMINAL = {"ALLOW", "BLOCK"}
RULES = ["daily_window", "weekday", "blackout", "customer_window"]
BLOCK_REASONS = ["outside_window", "weekday_blocked", "blackout_date", "customer_window",
                 "unknown_region", "cross_tenant"]
BLOCK_PRECEDENCE = ["unknown_region", "blackout_date", "weekday_blocked", "outside_window", "customer_window"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
CHANNEL = "voice"

# Degrade (inject) — DOĞRU fail-closed/yerel-saat davranışı bozan müdahaleler (her biri bir invariant'ı eler).
INJECTIONS = {"skip_hours", "use_server_time", "ignore_window", "ignore_weekday",
              "ignore_blackout", "ignore_customer_window", "failopen_region", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "hours_skip", "tz_error", "window_leak", "weekday_leak", "blackout_leak",
    "customer_window_leak", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 10.2.1/10.2.2 deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# ISO tarih/saat, yapısal kimlik/enum, HH:MM saat penceresi, offset/weekday sayısı, rezerve test bloğu beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|camp-|t-|ck-|corr-|res-|prefix|masked|last4|\d{4}-\d{2}-\d{2}|\d{2}:\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu + ISO tarih/saati eler (10.2.2 deseni)."""
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
# Deterministik yardımcılar — profil çözümü + sanal-saat yerel saat çevirme (Date.now/random YOK).
# ════════════════════════════════════════════════════════════════════════════
def _to_utc(call_time):
    """ISO mutlak instant → naive UTC datetime. Offset varsa UTC'ye normalize; naive ise UTC kabul."""
    if not call_time:
        return None
    try:
        dt = datetime.fromisoformat(str(call_time).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _hhmm_to_minutes(s):
    """'HH:MM' → dakika (None ise None)."""
    if not s:
        return None
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


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


def _resolve_offset(sample, prof):
    """Bölge → utc_offset_minutes çöz. Öncelik: açık tz_offset_minutes > regions[region] > profile default.

    Çözümlenemezse (bilinmeyen ülke / requires_region ∧ bölge yok / offset yok) → None (fail-closed unknown_region)."""
    if prof is None:
        return None, None
    if sample.get("tz_offset_minutes") is not None:
        return sample["tz_offset_minutes"], sample.get("region")
    region = sample.get("region")
    regions = prof.get("regions", {})
    if region and region in regions:
        return regions[region].get("utc_offset_minutes"), region
    if prof.get("requires_region"):
        return None, region            # bölge zorunlu ama çözülemedi → fail-closed
    off = prof.get("utc_offset_minutes")
    return off, region


def _in_window(local_minutes, win):
    """local_minutes ∈ [start,end) → True. Pencere yoksa True (kısıt yok)."""
    if not win:
        return True
    start = _hhmm_to_minutes(win.get("start"))
    end = _hhmm_to_minutes(win.get("end"))
    if start is None or end is None:
        return True
    return start <= local_minutes < end


# ════════════════════════════════════════════════════════════════════════════
def _config(sample):
    """Config = ana policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "profiles" in ov:
        cfg.setdefault("profiles", {}).update(ov["profiles"])
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek arama-saati senaryosunu yürüt → CallingHoursDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed all-pass yerel-saat davranışı hesaplar; inject (degrade) doğru davranışı
    bozar ve eşleşen ihlal sayacını artırır (10.2.2 inject deseniyle birebir)."""
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
    cust = sample.get("customer_window")

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── K12 (tenant izolasyonu): arama saati profili/müşteri penceresi yalnız aynı tenant'a ait okunur ──
    cross = False
    if "cross_tenant" in inject:
        cross = True
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        cross = True
        v["cross_tenant"] += 1
    if isinstance(cust, dict) and cust.get("tenant_id") and cust.get("tenant_id") != tenant:
        cross = True
        v["cross_tenant"] += 1

    # ── Profil + bölge → saat dilimi offset çöz (FR-OUT-004) ──
    resolved_profile, prof = _resolve_profile(sample, cfg)
    offset, region = _resolve_offset(sample, prof)

    rule_eval = {r: "n/a" for r in RULES}
    block_reason = None
    local_dt = None
    local_str = None

    # ── K7 fail-closed: bölge/saat dilimi çözümlenemedi → unknown_region (fail-open YASAK) ──
    region_unresolved = (prof is None) or (offset is None)
    if region_unresolved:
        if "failopen_region" in inject:
            v["failopen"] += 1               # bölge çözülemedi ama ALLOW → K7 fail-open ihlali
            # fail-open: çözülemeyen bölgeyi UTC kabul edip devam et (yanlış)
            offset = 0
            region_unresolved = False
        else:
            block_reason = "unknown_region"

    if not region_unresolved:
        # ── K2 yerel saate çevir (FR-OUT-004; use_server_time → UTC/sunucu saati = tz_error) ──
        eff_offset = offset
        if "use_server_time" in inject:
            eff_offset = 0                    # sunucu/UTC saatiyle değerlendir → bölge bazlı uygulama ihlali
            v["tz_error"] += 1
        utc_dt = _to_utc(call_time)
        if utc_dt is None:
            block_reason = "unknown_region"   # call_time parse edilemedi → fail-closed
        else:
            local_dt = utc_dt + timedelta(minutes=eff_offset)
            local_str = local_dt.isoformat()
            local_minutes = local_dt.hour * 60 + local_dt.minute
            local_weekday = local_dt.weekday()
            local_date = local_dt.date().isoformat()

            # K5 blackout/tatil
            blackout_dates = set((prof or {}).get("blackout_dates", []))
            is_blackout = local_date in blackout_dates
            if is_blackout:
                rule_eval["blackout"] = "BLACKOUT"
                if "ignore_blackout" in inject:
                    is_blackout = False
                    v["blackout_leak"] += 1
                    rule_eval["blackout"] = "IGNORED"
            else:
                rule_eval["blackout"] = "ok"

            # K4 haftanın günü
            allowed_weekdays = set((prof or {}).get("allowed_weekdays", []))
            weekday_ok = (not allowed_weekdays) or (local_weekday in allowed_weekdays)
            if not weekday_ok:
                rule_eval["weekday"] = "BLOCKED(%d)" % local_weekday
                if "ignore_weekday" in inject:
                    weekday_ok = True
                    v["weekday_leak"] += 1
                    rule_eval["weekday"] = "IGNORED"
            else:
                rule_eval["weekday"] = "ok(%d)" % local_weekday

            # K3 günlük pencere
            window_ok = _in_window(local_minutes, (prof or {}).get("allowed_window"))
            if not window_ok:
                rule_eval["daily_window"] = "OUTSIDE"
                if "ignore_window" in inject:
                    window_ok = True
                    v["window_leak"] += 1
                    rule_eval["daily_window"] = "IGNORED"
            else:
                rule_eval["daily_window"] = "ok"

            # K6 müşteri penceresi (FR-TEL-013 müşteri bazında)
            customer_ok = True
            if isinstance(cust, dict):
                cw_days = set(cust.get("weekdays", []))
                day_ok = (not cw_days) or (local_weekday in cw_days)
                time_ok = _in_window(local_minutes, cust)
                customer_ok = day_ok and time_ok
                if not customer_ok:
                    rule_eval["customer_window"] = "OUTSIDE"
                    if "ignore_customer_window" in inject:
                        customer_ok = True
                        v["customer_window_leak"] += 1
                        rule_eval["customer_window"] = "IGNORED"
                else:
                    rule_eval["customer_window"] = "ok"

            # ── All-pass fail-closed karar (block_precedence sırasıyla block_reason ata) ──
            fails = {
                "blackout_date": is_blackout,
                "weekday_blocked": not weekday_ok,
                "outside_window": not window_ok,
                "customer_window": (isinstance(cust, dict) and not customer_ok),
            }
            for reason in BLOCK_PRECEDENCE:
                if fails.get(reason):
                    block_reason = reason
                    break

    terminal = "BLOCK" if block_reason is not None else "ALLOW"

    # ── K8 (fail-closed / ATLANAMAZ): bypass → hours_skip ihlali ──
    # skip_hours: BLOCK olması gereken bir kararı 'ALLOW' yapıp arama saati kontrolünü atlar.
    if "skip_hours" in inject:
        if terminal == "BLOCK":
            terminal = "ALLOW"
            block_reason = None
        v["hours_skip"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    allow = terminal == "ALLOW"
    hours_ok = allow  # 10.2.1/10.2.2 AND girdisi (eligible = consent_ok AND dnc_ok AND hours_ok)

    # ── Kanıt (K9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "region": region,
        "resolved_profile": resolved_profile,
        "utc_offset_minutes": offset,
        "local_time": local_str,
        "rules": rule_eval,
        "hours_ok": hours_ok,
        "block_reason": block_reason,
        "terminal": terminal,
    }
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII YOK — yalnız yapısal kimlik/enum/saat)
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
            "region": region,
            "local_time": local_str,
            "block_reason": block_reason,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "allow": allow,
        "hours_ok": hours_ok,
        "resolved_profile": resolved_profile,
        "region": region,
        "utc_offset_minutes": offset,
        "local_time": local_str,
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
        "hours_skip": "max_hours_skip",
        "tz_error": "max_tz_error",
        "window_leak": "max_window_leak",
        "weekday_leak": "max_weekday_leak",
        "blackout_leak": "max_blackout_leak",
        "customer_window_leak": "max_customer_window_leak",
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
        for key in ("terminal", "allow", "block_reason", "hours_ok", "local_time"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s reason=%s profil=%s offset=%s yerel=%s"
              % (res["terminal"], res["block_reason"], res["resolved_profile"], res["utc_offset_minutes"], res["local_time"]))
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
    chk("wbs=10.2.3", spec.get("wbs") == "10.2.3")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-013 izlenir (arama saati ülke/müşteri)", "FR-TEL-013" in tr.get("fr", []))
    chk("FR-OUT-004 izlenir (ülke/bölge arama saati)", "FR-OUT-004" in tr.get("fr", []))
    chk("FR-OUT-003 izlenir (consent köprü — 10.2.1)", "FR-OUT-003" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-TEL-013 izlenir", "SR-TEL-013" in tr.get("srs", []))
    chk("SR-OUT-004 izlenir", "SR-OUT-004" in tr.get("srs", []))
    chk("TC-TEL-013 izlenir", "TC-TEL-013" in tr.get("rtm", []))
    chk("TC-OUT-004 izlenir", "TC-OUT-004" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §19.1 Consent Engine izlenir", any("§19.1" in s for s in tr.get("sad", [])))
    chk("BRD §14.3 izlenir", any("§14.3" in s for s in tr.get("brd", [])))
    chk("DB §5.4 contact izlenir", any("§5.4" in d for d in tr.get("db", [])))

    # 3) Dört kural (SR-TEL-013/SR-OUT-004 çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dört kural tam (daily_window/weekday/blackout/customer_window)", set(rule_ids) == set(RULES))
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
    for gk in ("max_hours_skip", "max_tz_error", "max_window_leak", "max_weekday_leak",
               "max_blackout_leak", "max_customer_window_leak", "max_failopen", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("hours_skip_total metrik (K8 alarm)", "hours_skip_total" in obs.get("metrics", []))
    chk("hours_block_total metrik", "hours_block_total" in obs.get("metrics", []))
    chk("hours_tz_error_total metrik (FR-OUT-004)", "hours_tz_error_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/contact_key YÜKSEK kard (label değil)",
        "request_id" in hi and "contact_key" in hi and "contact_key" not in lo)
    chk("result/block_reason/country/region DÜŞÜK kard (label uygun)",
        "result" in lo and "block_reason" in lo and "country" in lo and "region" in lo)
    chk("alarm hours_skip ≤2dk", "hours_skip" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/calling-hours-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        tr_p = profs.get("PROFILE-TR", {})
        chk("config PROFILE-TR var (UTC+180, window+weekdays)",
            tr_p.get("utc_offset_minutes") == 180
            and tr_p.get("allowed_window", {}).get("start") == "09:00"
            and 6 not in tr_p.get("allowed_weekdays", [0, 1, 2, 3, 4, 5, 6]))
        chk("config PROFILE-UK var (window 08:00–20:00)",
            profs.get("PROFILE-UK", {}).get("allowed_window", {}).get("end") == "20:00")
        chk("config PROFILE-US-CALL requires_region=true (FR-OUT-004 bölge)",
            profs.get("PROFILE-US-CALL", {}).get("requires_region") is True
            and profs.get("PROFILE-US-CALL", {}).get("utc_offset_minutes") is None)
        chk("config US-CALL bölgeleri tz offset taşır (US-NY/US-CA)",
            profs.get("PROFILE-US-CALL", {}).get("regions", {}).get("US-NY", {}).get("utc_offset_minutes") == -300
            and profs.get("PROFILE-US-CALL", {}).get("regions", {}).get("US-CA", {}).get("utc_offset_minutes") == -480)
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
        # Varsayılan: TR (UTC+180), 2026-06-15 Pazartesi 11:00 yerel (08:00 UTC) → pencere içi ALLOW
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "campaign_id": "camp-1", "contact_key": "ck-1",
            "country": "TR", "call_channel": "voice", "campaign_category": "sales",
            "call_time": "2026-06-15T08:00:00+00:00",
        }
        d.update(kw)
        return d

    # 1) happy — TR pazartesi 11:00 yerel, pencere içi → ALLOW
    r = build(req(), spec)
    case("happy: ALLOW", r["terminal"] == "ALLOW")
    case("happy: hours_ok=true", r["hours_ok"] is True)
    case("happy: yerel saat 11:00 (UTC+180)", r["local_time"].endswith("11:00:00"))
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit ALLOW (K10)", r["audit"] is not None and r["audit"]["result"] == "ALLOW")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm — aynı girdi birebir aynı sonuç
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) K2 yerel saat ÇEKİRDEK — UTC pencere içi ama yerel pencere dışı → BLOCK
    # 2026-06-15 17:00 UTC → TR 20:00 yerel (18:00 penceresi dışı) → BLOCK outside_window
    r = build(req(call_time="2026-06-15T17:00:00+00:00"), spec)
    case("yerel-saat: UTC17:00→TR20:00 pencere dışı → BLOCK outside_window",
         r["terminal"] == "BLOCK" and r["block_reason"] == "outside_window")
    case("yerel-saat: local 20:00", r["local_time"].endswith("20:00:00"))

    # 3b) use_server_time injection → tz_error (UTC saatiyle değerlendirir, yerel değil)
    # UTC 17:00 TR profili: yerel 20:00 BLOCK olmalı; server_time ile UTC 17:00 pencere içi → yanlış ALLOW
    r = build(req(call_time="2026-06-15T17:00:00+00:00"), spec, inject=["use_server_time"])
    case("inject-server-time: tz_error>0", r["violations"]["tz_error"] > 0)
    case("inject-server-time: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-server-time: UTC17:00 pencere içi → yanlış ALLOW", r["terminal"] == "ALLOW")

    # 4) K3 günlük pencere — sabah erken (yerel 07:00) → BLOCK outside_window
    r = build(req(call_time="2026-06-15T04:00:00+00:00"), spec)   # TR 07:00
    case("window: yerel 07:00 pencere öncesi → BLOCK outside_window",
         r["terminal"] == "BLOCK" and r["block_reason"] == "outside_window")
    # pencere sınırı: 09:00 dahil (start), 18:00 hariç (end)
    r = build(req(call_time="2026-06-15T06:00:00+00:00"), spec)   # TR 09:00 tam başlangıç
    case("window: yerel 09:00 (start dahil) → ALLOW", r["terminal"] == "ALLOW")
    r = build(req(call_time="2026-06-15T15:00:00+00:00"), spec)   # TR 18:00 tam bitiş (hariç)
    case("window: yerel 18:00 (end hariç) → BLOCK", r["terminal"] == "BLOCK")

    # 5) K4 haftanın günü — TR Pazar (weekday 6) yasak → BLOCK weekday_blocked
    # 2026-06-21 Pazar, 11:00 yerel (08:00 UTC)
    r = build(req(call_time="2026-06-21T08:00:00+00:00"), spec)
    case("weekday: TR Pazar → BLOCK weekday_blocked",
         r["terminal"] == "BLOCK" and r["block_reason"] == "weekday_blocked")

    # 6) K5 blackout — TR 2026-05-01 (resmî tatil), yerel 11:00 → BLOCK blackout_date
    r = build(req(call_time="2026-05-01T08:00:00+00:00"), spec)
    case("blackout: TR 2026-05-01 → BLOCK blackout_date",
         r["terminal"] == "BLOCK" and r["block_reason"] == "blackout_date")

    # 7) K6 müşteri penceresi — ülke penceresi geçer ama müşteri 13:00–14:00 ister, yerel 11:00 → BLOCK customer_window
    r = build(req(customer_window={"start": "13:00", "end": "14:00"}), spec)
    case("customer: ülke OK ama müşteri 13–14 dışı (11:00) → BLOCK customer_window",
         r["terminal"] == "BLOCK" and r["block_reason"] == "customer_window")
    # müşteri penceresi içinde → ALLOW
    r = build(req(call_time="2026-06-15T10:30:00+00:00", customer_window={"start": "13:00", "end": "14:00"}), spec)
    case("customer: yerel 13:30 müşteri penceresi içinde → ALLOW", r["terminal"] == "ALLOW")
    # müşteri haftanın günü kısıtı
    r = build(req(call_time="2026-06-15T08:00:00+00:00", customer_window={"start": "09:00", "end": "18:00", "weekdays": [1, 2]}), spec)
    case("customer: müşteri yalnız Sal/Çar ister, Pzt çağrı → BLOCK customer_window",
         r["terminal"] == "BLOCK" and r["block_reason"] == "customer_window")

    # 8) K7 fail-closed bilinmeyen bölge — US requires_region, bölge yok → BLOCK unknown_region
    r = build(req(country="US", profile_id="PROFILE-US-CALL", call_time="2026-06-15T18:00:00+00:00"), spec)
    case("unknown-region: US bölgesiz → BLOCK unknown_region",
         r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_region")
    # bilinmeyen ülke → profil yok → BLOCK unknown_region
    r = build(req(country="ZZ", call_time="2026-06-15T08:00:00+00:00"), spec)
    case("unknown-country: profil yok → BLOCK unknown_region",
         r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_region")

    # 8b) US bölge çözümlü — US-NY (-300), 2026-06-15 18:00 UTC → 13:00 EST, pencere içi → ALLOW
    r = build(req(country="US", profile_id="PROFILE-US-CALL", region="US-NY", call_time="2026-06-15T18:00:00+00:00"), spec)
    case("us-region: US-NY 13:00 yerel pencere içi → ALLOW", r["terminal"] == "ALLOW")
    # US-CA (-480) aynı UTC 18:00 → 10:00 PST pencere içi → ALLOW (bölge farkı kanıtı)
    r = build(req(country="US", profile_id="PROFILE-US-CALL", region="US-CA", call_time="2026-06-15T18:00:00+00:00"), spec)
    case("us-region: US-CA 10:00 yerel pencere içi → ALLOW", r["terminal"] == "ALLOW")
    # US-CA aynı gün 04:00 UTC → 20:00 önceki gün PST? 04:00-480 = -440min → önceki gün 20:00 (içerde) ALLOW
    # US-CA 13:00 UTC → 05:00 PST (08:00 penceresi öncesi) → BLOCK (bölgeye göre farklı sonuç)
    r = build(req(country="US", profile_id="PROFILE-US-CALL", region="US-CA", call_time="2026-06-15T13:00:00+00:00"), spec)
    case("us-region: US-CA 05:00 yerel pencere öncesi → BLOCK", r["terminal"] == "BLOCK")
    r = build(req(country="US", profile_id="PROFILE-US-CALL", region="US-NY", call_time="2026-06-15T13:00:00+00:00"), spec)
    case("us-region: US-NY 08:00 yerel pencere içi → ALLOW (bölge farkı)", r["terminal"] == "ALLOW")

    # 9) block_precedence — blackout, weekday'den önce gelir (her ikisi de ihlal)
    # 2026-05-01 TR blackout; o gün Cuma (weekday 4, izinli) — blackout vurur
    r = build(req(call_time="2026-05-01T08:00:00+00:00"), spec)
    case("precedence: blackout önce gelir", r["block_reason"] == "blackout_date")

    # ── degrade injection'ları → ihlal + kapı eler ──
    # 10) skip_hours (K8 çekirdek) — BLOCK'u atla → hours_skip ihlali
    r = build(req(call_time="2026-06-15T17:00:00+00:00"), spec, inject=["skip_hours"])  # TR 20:00 BLOCK olmalı
    case("inject-skip: hours_skip>0", r["violations"]["hours_skip"] > 0)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-skip: terminal ALLOW'a zorlandı", r["terminal"] == "ALLOW")

    # 11) ignore_window (K3)
    r = build(req(call_time="2026-06-15T17:00:00+00:00"), spec, inject=["ignore_window"])
    case("inject-window: window_leak>0", r["violations"]["window_leak"] > 0)
    case("inject-window: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) ignore_weekday (K4)
    r = build(req(call_time="2026-06-21T08:00:00+00:00"), spec, inject=["ignore_weekday"])  # Pazar
    case("inject-weekday: weekday_leak>0", r["violations"]["weekday_leak"] > 0)

    # 13) ignore_blackout (K5)
    r = build(req(call_time="2026-05-01T08:00:00+00:00"), spec, inject=["ignore_blackout"])
    case("inject-blackout: blackout_leak>0", r["violations"]["blackout_leak"] > 0)

    # 14) ignore_customer_window (K6)
    r = build(req(customer_window={"start": "13:00", "end": "14:00"}), spec, inject=["ignore_customer_window"])
    case("inject-customer: customer_window_leak>0", r["violations"]["customer_window_leak"] > 0)

    # 15) failopen_region (K7) — bölge çözülemez ama ALLOW
    r = build(req(country="US", profile_id="PROFILE-US-CALL", call_time="2026-06-15T18:00:00+00:00"),
              spec, inject=["failopen_region"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 16) cross_tenant (K12)
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(customer_window={"start": "09:00", "end": "18:00", "tenant_id": "t-foreign"}), spec)
    case("foreign-tenant-customer-window: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 17) no_audit (K10)
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 18) kanıt (K9) — dört kural + profil + offset + yerel saat taşır
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: dört kural taşır", set(r["evidence"]["rules"].keys()) == set(RULES))
    case("evidence: resolved_profile=PROFILE-TR", r["evidence"]["resolved_profile"] == "PROFILE-TR")
    case("evidence: utc_offset=180", r["evidence"]["utc_offset_minutes"] == 180)
    case("evidence: local_time taşır", r["evidence"]["local_time"] is not None)
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 19) audit (K10) — result + country + tenant taşır, ham PII yok
    case("audit: result taşır", r["audit"]["result"] == "ALLOW")
    case("audit: country taşır", r["audit"]["country"] == "TR")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad alanı yok", "customer_phone_value" not in json.dumps(r["audit"])
         and "customer_name" not in json.dumps(r["audit"]))

    # 20) hours_ok = ALLOW (10.2.1/10.2.2 AND girdisi)
    r_allow = build(req(), spec)
    r_block = build(req(call_time="2026-06-15T17:00:00+00:00"), spec)
    case("hours_ok: ALLOW→true", r_allow["hours_ok"] is True)
    case("hours_ok: BLOCK→false", r_block["hours_ok"] is False)

    # 21) sızıntı tarayıcı: yapısal kimlik/ISO tarih/HH:MM/offset temiz, ham PII/telefon yakalanır
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: ISO tarih-saat temiz", scan_leaks('{"call_time": "2026-06-15T16:30:00+00:00"}') == [])
    case("leak: HH:MM saat temiz", scan_leaks('{"start": "09:00"}') == [])
    case("leak: offset sayısı temiz", scan_leaks('{"utc_offset_minutes": -480}') == [])
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
        "module": "calling-hours (WBS 10.2.3 — FR-TEL-013 + FR-OUT-004 ülke/bölge arama saati kuralları)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "block_precedence": BLOCK_PRECEDENCE,
        "block_reasons": BLOCK_REASONS,
        "decision": "resolve_profile(timezone,window,weekdays,blackout) → resolve_offset(region) | unresolved ⇒ "
                    "BLOCK(unknown_region) → to_local(call_time,offset) → eval4(blackout,weekday,daily_window,customer_window) → "
                    "all_pass ⇒ ALLOW | any_fail ⇒ BLOCK(reason)",
        "default": "BLOCK (fail-closed; bir kural ihlal veya bölge çözümlenemedi)",
        "channel": CHANNEL,
        "weekday_convention": "Pzt=0,Sal=1,Çar=2,Per=3,Cum=4,Cmt=5,Paz=6 (datetime.weekday)",
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "campaign_id",
                           "contact_key", "country", "region?", "call_channel(voice)", "campaign_category",
                           "call_time(ISO mutlak instant — UTC/offset)", "tz_offset_minutes?",
                           "customer_window?{start(HH:MM),end(HH:MM),weekdays[]?,tenant_id?}",
                           "profile_id?", "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "allow", "hours_ok", "resolved_profile", "region", "utc_offset_minutes",
                            "local_time", "block_reason", "rules", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-TEL-013, FR-OUT-004, SR-TEL-013, SR-OUT-004, TC-TEL-013, TC-OUT-004, FR-OUT-003 (köprü), "
                 "FR-IAM-006, FR-TEN-002, FR-REC-004, BRD §14.3, SAD §19.1, DPIA §5.3 cp.outbound.calling_hours, "
                 "DB §5.4 contact region/timezone, API §A-10, ADR-001/002/012",
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
            print("kullanım: calling_hours_probe.py check <sample.json|dizin>")
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
