#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.1 — Kayıt politikası (tenant/ülke/use-case) + tamamen kapatma referans probe.

11. workstream'in (Kayıt, Transkript & PII Redaction) KAYIT POLİTİKASI (recording-policy) modülü ve
F1-Must temel yeteneği. FR-REC-001 ('Kayıt politikası tenant, ülke ve use-case bazında belirlenmelidir')
+ FR-REC-002 ('Ses kaydı tamamen kapatılabilmelidir') + SR-REC-001 (yöntem I — 'Politika seçimi ilgili
çağrılara uygulanır') + SR-REC-002 (yöntem T — kabul: 'Kayıt kapalıyken hiçbir medya saklanmaz') +
DPIA §5.2 cp.transparency.recording_consent_model 'Kayıt başlatma kapısı FR-REC-001'ı sahiplenir. Bir
DETERMİNİSTİK FAIL-CLOSED (privacy-safe = NO-RECORD) MOTORUdur:

  RecordingPolicyRequest ─ülke profil çöz─► üç-katman most-restrictive ─► killswitch ─► consent kapısı
        │                       │                       │                     │              │
        │   effective = most_restrictive(country, use_case_overlay, tenant_override)         │
        │                       │                       │                     │              │
        │      ├─ profil çözülemez ──────────────────────────────────────────► BLOCK (unknown_profile)
        │      ├─ cross-tenant ──────────────────────────────────────────────► BLOCK (cross_tenant)
        │      ├─ recording_enabled=false ───────────────────────────────────► DISABLED (no media)
        │      ├─ consent/notice kapısı geçilemedi ──────────────────────────► NO_CONSENT (no media)
        │      └─ etkin ∧ kapı geçildi ──────────────────────────────────────► RECORD (recording_allowed)

ÇEKİRDEK INVARIANT'lar: K2 üç-katman politika çözümü (ülke × tenant × use-case most-restrictive;
FR-REC-001), K3 tamamen kapatma (recording_enabled=false ⇒ DISABLED ∧ no media; FR-REC-002), K4 consent
kapısı (notice/explicit_optin/all_party; gevşetme yasak), K5 kapalıyken medya yok (terminal≠RECORD ⇒
no_media_captured=true; SR-REC-002), K6 residency (RECORD home-region), K7 fail-closed bilinmeyen profil
(privacy-safe NO-RECORD), K8 ATLANAMAZ (bypass=policy_skip=BRD §15 'kayıt politikası atlandı' alarmı).
Her karar deterministik+terminal (K1) + kanıt (K9) + audit (K10); metrik düşük-kardinalite + PII yok
(K11); sır/PII yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): tek/çift kanallı kayıt ÜRETİMİ → 11.2 (FR-REC-003; channels
TAŞINIR); transkript → 11.3; PII redaction → 11.4 (FR-REC-004); kart/parola/OTP → 11.5; erişim audit →
11.6 (FR-REC-009); retention/silme → FR-REC-006/007/010 (retention_days TAŞINIR); compliance profile
ÇÖZÜMLEME → DPIA §5/SAD §19.3 (değerleri tüketir); consent KAYDI → consent:manage + 10.2.1 (okur);
bildirim ÇALMA → BRD §14.2 (notice_played okur); pipeline kayıt yazımı → SAD §10.2; audit store →
7.1.6/12.x.

Kullanım:
  recording_policy_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  recording_policy_probe.py check <sample>     Kayıt-politikası motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  recording_policy_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  recording_policy_probe.py schema             Karar sözleşmesini yazdır

Determinizm: politika çözümü + most-restrictive birleştirme + bayrak/enum karşılaştırma; Date.now/random
YOK. Stdlib-only. Sır/credential ve gerçek PII (müşteri adı/telefon/ham ses) üretilmez/yazılmaz (fixture
sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "recording-policy-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "recording-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["RECORD", "DISABLED", "NO_CONSENT", "BLOCK"]
TERMINAL = {"RECORD", "DISABLED", "NO_CONSENT", "BLOCK"}
RULES = ["policy_resolution", "disable_killswitch", "consent_gate", "no_media_when_off", "residency_honored"]
BLOCK_REASONS = ["unknown_profile", "cross_tenant"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
CHANNEL = "voice"
CONSENT_MODEL_RANK = {"notice": 0, "explicit_optin": 1, "all_party": 2}

# Degrade (inject) — DOĞRU fail-closed/privacy-safe (NO-RECORD) davranışını bozan müdahaleler.
INJECTIONS = {"skip_policy", "record_while_disabled", "record_without_consent", "ignore_usecase",
              "ignore_tenant_override", "loosen_consent_model", "residency_leak", "failopen_profile",
              "record_on_block", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "policy_skip", "policy_resolution_error", "recorded_while_disabled", "recorded_without_consent",
    "consent_model_loosened", "media_when_off", "residency_violation", "failopen", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.x/10.2.x deseniyle) — müşteri adı/telefon/hesap no/OTP/ham ses yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|raw_audio|otp_code_value|password_value|raw_value|raw_msisdn)\"\s*:")),
]
# Yapısal kimlik/enum/bayrak + retention gün sayısı (kısa) beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|call-|camp-|t-|corr-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı eler (11.x deseni)."""
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
    """country/profile_id → ülke profili. Açık profile_id öncelikli; yoksa country eşleşmesi; yoksa None."""
    profiles = cfg.get("profiles", {})
    pid = sample.get("profile_id")
    if pid and pid in profiles:
        return pid, profiles[pid]
    country = sample.get("country")
    for name, prof in profiles.items():
        if prof.get("country") == country:
            return name, prof
    return None, None


def _config(sample):
    """Config = ana policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "profiles" in ov:
        cfg.setdefault("profiles", {}).update(ov["profiles"])
    if "use_case_overlays" in ov:
        cfg.setdefault("use_case_overlays", {}).update(ov["use_case_overlays"])
    return cfg


def _stricter_model(a, b):
    """İki consent_model'den en katısını döndür (most-restrictive: notice<explicit_optin<all_party)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if CONSENT_MODEL_RANK.get(a, 0) >= CONSENT_MODEL_RANK.get(b, 0) else b


def build(sample, spec, inject=None, cfg=None):
    """Tek kayıt-politikası senaryosunu yürüt → RecordingPolicyDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / privacy-safe (NO-RECORD) davranışını hesaplar; inject (degrade) doğru
    davranışı bozar ve eşleşen ihlal sayacını artırır (11.x/10.2.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    call_id = sample.get("call_id")
    request_id = sample.get("request_id")
    country = sample.get("country")
    use_case = sample.get("use_case")
    direction = sample.get("direction")
    storage_region = sample.get("storage_region")

    # Kayıt-başlatma sinyalleri (modül OKUR; üretmez)
    consent_state = sample.get("consent_state")              # granted / denied / not_obtained / None
    all_party_consent = bool(sample.get("all_party_consent", False))
    notice_played = bool(sample.get("recording_notice_played", False))

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── K12 (tenant izolasyonu): kayıt politikası/profil yalnız aynı tenant'a ait okunur ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── Ülke kayıt politikasını çöz ──
    resolved_profile, country_prof = _resolve_profile(sample, cfg)

    block_reason = None
    effective = None
    consent_gate_ok = None
    no_media_captured = True            # privacy-safe varsayılan: medya yok
    recording_allowed = False
    channels = None
    home_region = None
    retention_days = None
    eff_in_region = None
    eff_consent_model = None

    # ── K8 (fail-closed / ATLANAMAZ): bypass → politika çözmeden kayıt başlat → policy_skip ──
    if "skip_policy" in inject:
        v["policy_skip"] += 1
        terminal = "RECORD"
        recording_allowed = True
        no_media_captured = False        # politika çözülmeden kayıt = over-capture
        evidence = {
            "request_id": request_id, "country": country, "resolved_profile": resolved_profile,
            "effective": None, "consent_gate_ok": None, "no_media_captured": no_media_captured,
            "recording_allowed": recording_allowed, "block_reason": None, "terminal": terminal,
        }
        if (not request_id) or (terminal is None):
            v["missing_evidence"] += 1
        audit = None
        if "no_audit" in inject:
            v["missing_audit"] += 1
        else:
            audit = {"result": terminal, "request_id": request_id, "call_id": call_id, "country": country,
                     "use_case": use_case, "consent_model": None, "recording_allowed": recording_allowed,
                     "no_media_captured": no_media_captured, "correlation_id": sample.get("correlation_id"),
                     "tenant_id": tenant}
        return _pack(sample, terminal, v, resolved_profile, None, consent_gate_ok, no_media_captured,
                     recording_allowed, None, None, None, None, block_reason, evidence, audit)

    # ── K7 fail-closed: profil çözümlenemedi → unknown_profile (fail-open YASAK) ──
    profile_unresolved = (country_prof is None)
    if profile_unresolved:
        if "failopen_profile" in inject:
            v["failopen"] += 1            # profil çözülemedi ama RECORD → K7 fail-open ihlali
            country_prof = {"recording_enabled": True, "consent_model": "notice", "notice_required": False,
                            "in_region_storage_required": False, "home_region": None, "default_channels": 2}
            profile_unresolved = False
            resolved_profile = "__failopen__"
        else:
            block_reason = "unknown_profile"

    # cross_tenant fail-closed BLOCK (profil çözülse bile)
    if v["cross_tenant"] > 0 and block_reason is None:
        block_reason = "cross_tenant"

    if not profile_unresolved and block_reason != "cross_tenant":
        # ── K2 üç-katman most-restrictive: ülke × use-case overlay × tenant override ──
        layers = [dict(country_prof)]
        overlay = cfg.get("use_case_overlays", {}).get(use_case)
        if overlay and "ignore_usecase" not in inject:
            layers.append(overlay)
        if overlay and "ignore_usecase" in inject:
            v["policy_resolution_error"] += 1     # use-case katmanı atlandı → yanlış (gevşek) politika
        tenant_override = sample.get("tenant_override")
        if tenant_override and "ignore_tenant_override" not in inject:
            layers.append(tenant_override)
        if tenant_override and "ignore_tenant_override" in inject:
            v["policy_resolution_error"] += 1     # tenant katmanı atlandı → yanlış (gevşek) politika

        eff_enabled = all(l.get("recording_enabled", True) for l in layers)
        eff_consent_model = None
        for l in layers:
            eff_consent_model = _stricter_model(eff_consent_model, l.get("consent_model"))
        eff_consent_model = eff_consent_model or "notice"
        eff_notice_required = any(l.get("notice_required", False) for l in layers)
        eff_in_region = any(l.get("in_region_storage_required", False) for l in layers)
        home_region = country_prof.get("home_region")
        channels = country_prof.get("default_channels")
        retention_days = country_prof.get("retention_days")

        # ── K4 loosen: tenant/inject etkin model'i gevşetir (en zayıf) → consent_model_loosened ──
        if "loosen_consent_model" in inject:
            weakest = min(layers, key=lambda l: CONSENT_MODEL_RANK.get(l.get("consent_model", "notice"), 0))
            eff_consent_model = weakest.get("consent_model", "notice")
            v["consent_model_loosened"] += 1

        effective = {
            "recording_enabled": eff_enabled,
            "consent_model": eff_consent_model,
            "notice_required": eff_notice_required,
            "in_region_storage_required": eff_in_region,
            "home_region": home_region,
            "channels": channels,
            "retention_days": retention_days,
        }

        # ── K3 tamamen kapatma: recording_enabled=false ⇒ DISABLED ∧ no media ──
        if not eff_enabled:
            terminal = "DISABLED"
            no_media_captured = True
            recording_allowed = False
            consent_gate_ok = None
            if "record_while_disabled" in inject:
                recording_allowed = True
                no_media_captured = False        # kapalıyken medya = gizlilik ihlali
                v["recorded_while_disabled"] += 1
        else:
            # ── K4 kayıt-başlatma consent/notice kapısı ──
            notice_ok = (not eff_notice_required) or notice_played
            if eff_consent_model == "notice":
                consent_part_ok = True           # notice modeli: bildirim yeterli
            elif eff_consent_model == "explicit_optin":
                consent_part_ok = (consent_state == "granted")
            elif eff_consent_model == "all_party":
                consent_part_ok = (all_party_consent and consent_state == "granted")
            else:
                consent_part_ok = False
            consent_gate_ok = bool(notice_ok and consent_part_ok)

            if consent_gate_ok:
                terminal = "RECORD"
                recording_allowed = True
                no_media_captured = False
                # ── K6 residency: in_region ise storage_region == home_region ──
                if "residency_leak" in inject:
                    storage_region = (home_region or "EU") + "-ALT"   # home-region dışına çıkar
                if eff_in_region and storage_region is not None and storage_region != home_region:
                    v["residency_violation"] += 1
            else:
                terminal = "NO_CONSENT"
                no_media_captured = True
                recording_allowed = False
                if "record_without_consent" in inject:
                    recording_allowed = True
                    no_media_captured = False     # izinsiz kayıt = gizlilik ihlali
                    v["recorded_without_consent"] += 1
    else:
        terminal = "BLOCK"
        no_media_captured = True
        recording_allowed = False
        # K5 bağımsız ispatı: BLOCK iken medya yakalama injection'ı
        if "record_on_block" in inject:
            recording_allowed = True
            no_media_captured = False
        if "record_without_consent" in inject:
            recording_allowed = True
            no_media_captured = False

    if block_reason is not None:
        terminal = "BLOCK"

    # ── K5 ÇEKİRDEK: terminal ≠ RECORD ⇒ no_media_captured = true ──
    if terminal != "RECORD" and not no_media_captured:
        v["media_when_off"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (K9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "use_case": use_case,
        "direction": direction,
        "resolved_profile": resolved_profile,
        "effective": effective,
        "consent_gate_ok": consent_gate_ok,
        "no_media_captured": no_media_captured,
        "recording_allowed": recording_allowed,
        "channels": channels,
        "storage_region": storage_region,
        "home_region": home_region,
        "retention_days": retention_days,
        "block_reason": block_reason,
        "terminal": terminal,
    }
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII YOK — yalnız yapısal kimlik/enum/bayrak)
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "result": terminal,
            "request_id": request_id,
            "call_id": call_id,
            "country": country,
            "use_case": use_case,
            "consent_model": eff_consent_model,
            "recording_allowed": recording_allowed,
            "no_media_captured": no_media_captured,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return _pack(sample, terminal, v, resolved_profile, effective, consent_gate_ok, no_media_captured,
                 recording_allowed, channels, storage_region, home_region, retention_days,
                 block_reason, evidence, audit)


def _pack(sample, terminal, v, resolved_profile, effective, consent_gate_ok, no_media_captured,
          recording_allowed, channels, storage_region, home_region, retention_days,
          block_reason, evidence, audit):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "recording_allowed": recording_allowed,
        "no_media_captured": no_media_captured,
        "resolved_profile": resolved_profile,
        "effective": effective,
        "consent_model": (effective or {}).get("consent_model") if effective else None,
        "consent_gate_ok": consent_gate_ok,
        "channels": channels,
        "storage_region": storage_region,
        "home_region": home_region,
        "retention_days": retention_days,
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
        "policy_skip": "max_policy_skip",
        "policy_resolution_error": "max_policy_resolution_error",
        "recorded_while_disabled": "max_recorded_while_disabled",
        "recorded_without_consent": "max_recorded_without_consent",
        "consent_model_loosened": "max_consent_model_loosened",
        "media_when_off": "max_media_when_off",
        "residency_violation": "max_residency_violation",
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
        for key in ("terminal", "block_reason", "recording_allowed", "no_media_captured",
                    "consent_model", "channels"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s reason=%s profil=%s consent_model=%s recording_allowed=%s no_media=%s"
              % (res["terminal"], res["block_reason"], res["resolved_profile"],
                 res["consent_model"], res["recording_allowed"], res["no_media_captured"]))
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
              "block_reasons", "outcomes", "consent_models", "authorization", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=11.1", spec.get("wbs") == "11.1")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-REC-001 izlenir (kayıt politikası tenant/ülke/use-case)", "FR-REC-001" in tr.get("fr", []))
    chk("FR-REC-002 izlenir (tamamen kapatma)", "FR-REC-002" in tr.get("fr", []))
    chk("FR-REC-003 izlenir (channels attribute → 11.2)", "FR-REC-003" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-REC-001 izlenir", "SR-REC-001" in tr.get("srs", []))
    chk("SR-REC-002 izlenir", "SR-REC-002" in tr.get("srs", []))
    chk("TC-REC-001 izlenir", "TC-REC-001" in tr.get("rtm", []))
    chk("TC-REC-002 izlenir", "TC-REC-002" in tr.get("rtm", []))
    chk("NFR 10.7 izlenir (residency)", "NFR 10.7" in tr.get("nfr", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §10.2 Recording Pipeline izlenir", any("§10.2" in s for s in tr.get("sad", [])))
    chk("SAD §19.3 compliance profile izlenir", any("§19.3" in s for s in tr.get("sad", [])))
    chk("BRD §9.14 FR-REC izlenir", any("§9.14" in s for s in tr.get("brd", [])))
    chk("BRD §15 gizlilik alarmı izlenir", any("§15" in s for s in tr.get("brd", [])))

    # 3) Beş kural (FR-REC-001 + FR-REC-002 çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("beş kural tam (resolution/killswitch/consent/no-media/residency)", set(rule_ids) == set(RULES))
    chk("değerlendirme resolve_then_killswitch_then_consent_fail_closed_no_record",
        rz.get("evaluation") == "resolve_then_killswitch_then_consent_fail_closed_no_record")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe_terminal no_record", "no_record" in dec.get("fail_safe_terminal", ""))

    # 5) Sonuçlar + block_reason taksonomisi + consent_models
    oc = spec["outcomes"]
    chk("terminal sonuçlar RECORD/DISABLED/NO_CONSENT/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam (unknown_profile/cross_tenant)", br == set(BLOCK_REASONS))
    cm = spec["consent_models"].get("rank", {})
    chk("consent_model sıralama notice<explicit_optin<all_party",
        cm.get("notice") == 0 and cm.get("explicit_optin") == 1 and cm.get("all_party") == 2)

    # 6) Yetki — recording:policy:manage, per-call otomatik gate
    az = spec["authorization"]
    chk("policy_permission=recording:policy:manage", az.get("policy_permission") == "recording:policy:manage")
    chk("per_call_check otomatik gate", "automatic_gate" in az.get("per_call_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_policy_skip", "max_policy_resolution_error", "max_recorded_while_disabled",
               "max_recorded_without_consent", "max_consent_model_loosened", "max_media_when_off",
               "max_residency_violation", "max_failopen", "max_cross_tenant", "max_missing_evidence",
               "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("recording_policy_decision_total metrik", "recording_policy_decision_total" in obs.get("metrics", []))
    chk("recording_disabled_total metrik (FR-REC-002)", "recording_disabled_total" in obs.get("metrics", []))
    chk("recording_privacy_violation_total metrik (K3/K4/K5 alarm)",
        "recording_privacy_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/call_id YÜKSEK kard (label değil)",
        "request_id" in hi and "call_id" in hi and "call_id" not in lo)
    chk("result/country/use_case/consent_model DÜŞÜK kard (label uygun)",
        "result" in lo and "country" in lo and "use_case" in lo and "consent_model" in lo)
    chk("alarm recorded_while_disabled/policy_skip ≤2dk",
        "recorded_while_disabled" in obs.get("alarm", "") or "policy_skip" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/recording-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        tr_p = profs.get("PROFILE-TR", {})
        chk("config PROFILE-TR var (notice + enabled + in-region)",
            tr_p.get("consent_model") == "notice" and tr_p.get("recording_enabled") is True
            and tr_p.get("in_region_storage_required") is True)
        chk("config PROFILE-EU var (explicit_optin)",
            profs.get("PROFILE-EU", {}).get("consent_model") == "explicit_optin")
        chk("config PROFILE-US-CALL var (all_party)",
            profs.get("PROFILE-US-CALL", {}).get("consent_model") == "all_party")
        ov = cfg.get("use_case_overlays", {})
        chk("config use_case_overlays var (use-case tamamen kapatma)",
            ov.get("internal_test", {}).get("recording_enabled") is False)
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
    chk("hiç müşteri-PII/telefon/hesap-no/ham-ses/sır sızıntısı yok (K12)", total_leaks == 0)

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
        # Varsayılan TR: recording_enabled=true, consent_model=notice, notice_required=true; notice çalındı → RECORD.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "call_id": "call-1", "country": "TR", "use_case": "sales", "channel": "voice",
            "direction": "inbound", "consent_state": "granted", "all_party_consent": True,
            "recording_notice_played": True, "storage_region": "TR",
        }
        d.update(kw)
        return d

    # 1) happy — TR notice çalındı → RECORD
    r = build(req(), spec)
    case("happy: RECORD", r["terminal"] == "RECORD")
    case("happy: recording_allowed=true", r["recording_allowed"] is True)
    case("happy: no_media_captured=false (kayıt var)", r["no_media_captured"] is False)
    case("happy: consent_model=notice", r["consent_model"] == "notice")
    case("happy: channels=2 (TR default)", r["channels"] == 2)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit RECORD (K10)", r["audit"] is not None and r["audit"]["result"] == "RECORD")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) K4 notice çalınmadı → NO_CONSENT (no media)
    r = build(req(recording_notice_played=False), spec)
    case("notice-yok: NO_CONSENT", r["terminal"] == "NO_CONSENT")
    case("notice-yok: no_media_captured=true", r["no_media_captured"] is True)
    case("notice-yok: recording_allowed=false", r["recording_allowed"] is False)
    case("notice-yok: kapı geçer (gizlilik-güvenli)", _gate_eval(r, G)[0] is True)

    # 4) K3 FR-REC-002 — tenant override recording_enabled=false → DISABLED (no media)
    r = build(req(tenant_override={"recording_enabled": False}), spec)
    case("tenant-disable: DISABLED", r["terminal"] == "DISABLED")
    case("tenant-disable: no_media_captured=true (tamamen kapatma)", r["no_media_captured"] is True)
    case("tenant-disable: recording_allowed=false", r["recording_allowed"] is False)
    case("tenant-disable: kapı geçer", _gate_eval(r, G)[0] is True)

    # 4b) K3 use-case overlay disable → DISABLED
    r = build(req(use_case="internal_test"), spec)
    case("usecase-disable: DISABLED (internal_test)", r["terminal"] == "DISABLED")
    case("usecase-disable: no_media_captured=true", r["no_media_captured"] is True)

    # 5) K2 — use_case overlay consent sıkılaştırır (collections → explicit_optin)
    r = build(req(use_case="collections", consent_state="granted"), spec)
    case("usecase-tighten: consent_model=explicit_optin", r["consent_model"] == "explicit_optin")
    case("usecase-tighten: granted → RECORD", r["terminal"] == "RECORD")
    r = build(req(use_case="collections", consent_state="denied"), spec)
    case("usecase-tighten: denied → NO_CONSENT", r["terminal"] == "NO_CONSENT")
    case("usecase-tighten: denied → no media", r["no_media_captured"] is True)

    # 6) tenant override yalnız sıkılaştırır (notice → explicit_optin); granted → RECORD
    r = build(req(tenant_override={"consent_model": "explicit_optin"}, consent_state="granted"), spec)
    case("tenant-tighten: consent_model=explicit_optin", r["consent_model"] == "explicit_optin")
    case("tenant-tighten: granted → RECORD", r["terminal"] == "RECORD")
    r = build(req(tenant_override={"consent_model": "explicit_optin"}, consent_state="not_obtained"), spec)
    case("tenant-tighten: not_obtained → NO_CONSENT", r["terminal"] == "NO_CONSENT")

    # 7) EU explicit_optin
    r = build(req(country="EU", profile_id="PROFILE-EU", consent_state="granted", storage_region="EU"), spec)
    case("eu: consent_model=explicit_optin", r["consent_model"] == "explicit_optin")
    case("eu: granted → RECORD", r["terminal"] == "RECORD")
    r = build(req(country="EU", profile_id="PROFILE-EU", consent_state="denied"), spec)
    case("eu: denied → NO_CONSENT (no media)", r["terminal"] == "NO_CONSENT" and r["no_media_captured"] is True)

    # 8) US all_party — iki-taraf rıza
    r = build(req(country="US", profile_id="PROFILE-US-CALL", consent_state="granted",
                  all_party_consent=True, storage_region="NA"), spec)
    case("us: all_party tüm taraflar → RECORD", r["terminal"] == "RECORD" and r["consent_model"] == "all_party")
    r = build(req(country="US", profile_id="PROFILE-US-CALL", consent_state="granted",
                  all_party_consent=False), spec)
    case("us: bir taraf reddetti → NO_CONSENT (no media)",
         r["terminal"] == "NO_CONSENT" and r["no_media_captured"] is True)

    # 9) K7 fail-closed bilinmeyen profil → BLOCK (no media)
    r = build(req(country="ZZ"), spec)
    case("unknown-profile: BLOCK unknown_profile",
         r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_profile")
    case("unknown-profile: no_media_captured=true (privacy-safe)", r["no_media_captured"] is True)
    r = build(req(country="ZZ"), spec, inject=["failopen_profile"])
    case("inject-failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("inject-failopen: kapı eler", _gate_eval(r, G)[0] is False)

    # 10) K8 skip_policy — bypass: politika çözmeden kayıt → policy_skip + media
    r = build(req(), spec, inject=["skip_policy"])
    case("inject-skip: policy_skip>0", r["violations"]["policy_skip"] > 0)
    case("inject-skip: no_media_captured=false (over-capture)", r["no_media_captured"] is False)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)

    # 11) K3 record_while_disabled — kapalıyken kayıt
    r = build(req(tenant_override={"recording_enabled": False}), spec, inject=["record_while_disabled"])
    case("inject-record-disabled: recorded_while_disabled>0", r["violations"]["recorded_while_disabled"] > 0)
    case("inject-record-disabled: media_when_off>0 (K5)", r["violations"]["media_when_off"] > 0)
    case("inject-record-disabled: kapı eler", _gate_eval(r, G)[0] is False)

    # 12) K4 record_without_consent — izinsiz kayıt
    r = build(req(country="EU", profile_id="PROFILE-EU", consent_state="denied"), spec,
              inject=["record_without_consent"])
    case("inject-record-noconsent: recorded_without_consent>0", r["violations"]["recorded_without_consent"] > 0)
    case("inject-record-noconsent: media_when_off>0 (K5)", r["violations"]["media_when_off"] > 0)
    case("inject-record-noconsent: kapı eler", _gate_eval(r, G)[0] is False)

    # 13) K4 loosen_consent_model — all_party → en zayıf model
    r = build(req(country="US", profile_id="PROFILE-US-CALL", consent_state="granted",
                  all_party_consent=False), spec, inject=["loosen_consent_model"])
    case("inject-loosen: consent_model_loosened>0", r["violations"]["consent_model_loosened"] > 0)
    case("inject-loosen: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) K2 ignore_usecase — use-case katmanı atlandı (disable atlandı → yanlış RECORD)
    r = build(req(use_case="internal_test", recording_notice_played=True), spec, inject=["ignore_usecase"])
    case("inject-ignore-usecase: policy_resolution_error>0", r["violations"]["policy_resolution_error"] > 0)
    case("inject-ignore-usecase: terminal RECORD (disable atlandı)", r["terminal"] == "RECORD")
    case("inject-ignore-usecase: kapı eler", _gate_eval(r, G)[0] is False)

    # 14b) K2 ignore_tenant_override
    r = build(req(tenant_override={"recording_enabled": False}), spec, inject=["ignore_tenant_override"])
    case("inject-ignore-tenant: policy_resolution_error>0", r["violations"]["policy_resolution_error"] > 0)
    case("inject-ignore-tenant: terminal RECORD (disable atlandı)", r["terminal"] == "RECORD")

    # 15) K6 residency_leak — RECORD home-region dışına yazılır
    r = build(req(), spec, inject=["residency_leak"])
    case("inject-residency: residency_violation>0", r["violations"]["residency_violation"] > 0)
    case("inject-residency: kapı eler", _gate_eval(r, G)[0] is False)
    # doğru residency (no inject): TR storage_region=TR → ihlal yok
    r = build(req(storage_region="TR"), spec)
    case("residency: storage=home(TR) → ihlal yok", r["violations"]["residency_violation"] == 0)

    # 16) K5 record_on_block — BLOCK iken medya yakalama
    r = build(req(country="ZZ"), spec, inject=["record_on_block"])
    case("inject-record-on-block: media_when_off>0 (K5)", r["violations"]["media_when_off"] > 0)
    case("inject-record-on-block: kapı eler", _gate_eval(r, G)[0] is False)

    # 17) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0 + BLOCK", r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 18) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 19) K5 GARANTİ — her terminal≠RECORD ⇒ no_media_captured=true
    for kw in (dict(recording_notice_played=False),                       # NO_CONSENT
               dict(tenant_override={"recording_enabled": False}),        # DISABLED
               dict(country="ZZ"),                                        # BLOCK
               dict(country="EU", profile_id="PROFILE-EU", consent_state="denied")):  # NO_CONSENT
        rr = build(req(**kw), spec)
        if rr["terminal"] != "RECORD":
            case("K5 garanti: %s → no_media_captured=true" % rr["terminal"], rr["no_media_captured"] is True)

    # 20) kanıt (K9) + audit (K10)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: effective/consent_gate/no_media taşır",
         all(k in r["evidence"] for k in ("effective", "consent_gate_ok", "no_media_captured")))
    case("evidence: resolved_profile=PROFILE-TR", r["evidence"]["resolved_profile"] == "PROFILE-TR")
    case("audit: result/country/tenant taşır",
         r["audit"]["result"] == "RECORD" and r["audit"]["country"] == "TR" and r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad/ham-ses alanı yok",
         all(k not in json.dumps(r["audit"]) for k in ("customer_phone_value", "customer_name", "raw_audio")))

    # 21) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: enum/bayrak temiz", scan_leaks('{"consent_model": "notice", "recording_enabled": true}') == [])
    case("leak: retention gün temiz", scan_leaks('{"retention_days": 365}') == [])
    case("leak: customer_phone_value alanı yakalanır", len(scan_leaks('{"customer_phone_value": "x"}')) > 0)
    case("leak: raw_audio alanı yakalanır", len(scan_leaks('{"raw_audio": "x"}')) > 0)
    case("leak: ham uzun telefon yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "recording-policy (WBS 11.1 — FR-REC-001 kayıt politikası tenant/ülke/use-case + FR-REC-002 tamamen kapatma)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "consent_models": CONSENT_MODEL_RANK,
        "decision": "resolve_country_profile | unresolved ⇒ BLOCK(unknown_profile) → tenant_check ⇒ "
                    "BLOCK(cross_tenant) → effective = most_restrictive(country, use_case_overlay, tenant_override) "
                    "→ effective.recording_enabled==false ⇒ DISABLED(no_media) → "
                    "consent_gate(consent_model, notice_required) fail ⇒ NO_CONSENT(no_media) → "
                    "RECORD(recording_allowed=true, channels/residency/retention)",
        "default": "BLOCK (fail-closed; privacy-safe NO-RECORD)",
        "fail_safe": "terminal ≠ RECORD ⇒ no_media_captured = true (SR-REC-002 'Kayıt kapalıyken hiçbir medya saklanmaz')",
        "channel": CHANNEL,
        "policy_resolution": "effective = most_restrictive(country_profile, use_case_overlay, tenant_override); "
                             "recording_enabled = AND; consent_model = max(notice<explicit_optin<all_party); "
                             "notice_required = OR; in_region_storage_required = OR",
        "consent_gate": "notice ⇒ recording_notice_played; explicit_optin ⇒ consent_state=granted; "
                        "all_party ⇒ all_party_consent ∧ consent_state=granted; + notice_required ⇒ notice_played",
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "call_id",
                           "country", "use_case", "channel(voice)", "direction(inbound|outbound)",
                           "consent_state(granted|denied|not_obtained)", "all_party_consent(bool)",
                           "recording_notice_played(bool)", "storage_region",
                           "profile_id?", "tenant_override{recording_enabled?,consent_model?,notice_required?}",
                           "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "recording_allowed", "no_media_captured", "resolved_profile",
                            "effective", "consent_model", "consent_gate_ok", "channels", "storage_region",
                            "home_region", "retention_days", "block_reason", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-REC-001, FR-REC-002, SR-REC-001, SR-REC-002, TC-REC-001, TC-REC-002, "
                 "FR-REC-003 (channels → 11.2), FR-REC-004, FR-REC-006 (retention), FR-IAM-006, "
                 "FR-TEN-002, NFR 10.7, BRD §9.14, BRD §15, SAD §10.2 Recording Pipeline, SAD §19.3 "
                 "compliance profile, DPIA §5.2 recording_consent_model, DB §22, ADR-001/002/012",
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
            print("kullanım: recording_policy_probe.py check <sample.json|dizin>")
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
