#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.1 — Consent Engine ön-kontrol referans probe.

10. workstream'in (Outbound) Consent & uyumluluk motoru alt-bloğunun CONSENT ÖN-KONTROL modülü ve
F2-Must outbound yeteneği. FR-OUT-003 ('Arama öncesi consent ve suppression kontrolü yapılmalıdır') +
SR-OUT-003 (yöntem T — 'Arama öncesi consent ve suppression kontrolü yapılır
(amaç/ülke/birey-şirket/kaynak/tarih/kapsam)'; kabul: 'Consent yoksa/suppress ise çağrı başlatılmaz') +
SAD §19.1 Consent Engine'in CONSENT KARARINI sahiplenir. Modül bir DETERMİNİSTİK FAIL-CLOSED MOTORUdur:

  ConsentCheckRequest ──ülke profili çöz──► consent_required = f(consent_model, subject_type, b2b)
        │                                         │
        │                                         ├─ opt_out | B2B-muaf ───────────────► ALLOW (basis)
        │                                         └─ rıza gerekli ─┬─ altı boyut geçer ► ALLOW (explicit/soft)
        │                                                          └─ herhangi boyut X ► BLOCK (block_reason)
        └──(ülke çözülemez / cross-tenant)─────────────────────────────────────────────► BLOCK (fail-closed)

ALTI BOYUT (BRD §14.3, SR-OUT-003 çekirdek): AMAÇ (K2) ∧ ÜLKE (K3) ∧ BİREY/ŞİRKET (K4) ∧ KAYNAK (K5) ∧
TARİH (K6) ∧ KAPSAM (K7); fail-closed/deny-by-default (K8: geçerli rıza yoksa çağrı BAŞLATILMAZ; ön-kontrol
ATLANAMAZ — bypass=consent_skip=BRD §15 kritik alarm). Her karar deterministik+terminal (K1) + kanıt (K9) +
audit (K10); metrik düşük-kardinalite + PII yok (K11); sır/PII yok + tenant izolasyonu (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): DNC/suppression GERÇEK ZAMANLI → 10.2.2 (FR-TEL-014/FR-OUT-006;
birlikte SR-OUT-003 'consent ve suppression'); arama saati → 10.1.4 (FR-OUT-004); max deneme → 10.1.3;
Caller ID → FR-TEL-004/005; açılış metni → §14.2; versiyon → 10.1.6; profile ÇÖZÜMLEME → DPIA §5/SAD §19.3
(değerleri TÜKETİR); consent KAYDI yönetimi → consent:manage panel (OKUR, toplamaz); audit store → 7.1.6/12.x;
dialer ÇEVİRME → 10.1.x (karar döndürür, çevirmez); panel UI → L2 A-10.

Kullanım:
  consent_precheck_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  consent_precheck_probe.py check <sample>     Consent motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  consent_precheck_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  consent_precheck_probe.py schema             Karar sözleşmesini yazdır

Determinizm: profil çözümü + ISO tarih karşılaştırması (sanal-saat call_time girdisi); Date.now/random YOK.
Stdlib-only. Sır/credential ve gerçek PII (müşteri adı/telefon/hesap no) üretilmez/yazılmaz (fixture
sentetik — FR-TST-008).
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "consent-precheck-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "consent-precheck-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ALLOW", "BLOCK"]
TERMINAL = {"ALLOW", "BLOCK"}
CONSENT_MODELS = ["opt_in", "soft_opt_in", "opt_out"]
DIMENSIONS = ["amaç", "ülke", "birey-şirket", "kaynak", "tarih", "kapsam"]
BASES = ["explicit", "soft_basis", "b2b_exempt", "opt_out", "none"]
BLOCK_REASONS = ["unknown_country", "consent_required_individual", "no_consent", "invalid_source",
                 "expired_or_invalid_date", "purpose_mismatch", "out_of_scope", "cross_tenant"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
CHANNEL = "voice"

# Degrade (inject) — DOĞRU fail-closed davranışı bozan müdahaleler (her biri bir invariant'ı eler).
INJECTIONS = {"skip_precheck", "accept_wrong_purpose", "accept_unknown_country", "b2b_misexempt",
              "accept_unknown_source", "accept_expired", "accept_out_of_scope", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "consent_skip", "purpose_mismatch_allowed", "unknown_country_allowed", "b2b_misexemption",
    "invalid_source_allowed", "expired_allowed", "out_of_scope_allowed", "cross_tenant",
    "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 9.x/10.1.x deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value)\"\s*:")),
]
# ISO tarih (2024-05-01...) ve yapısal kimlik/enum + rezerve test bloğu beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|camp-|t-|ck-|corr-|res-|prefix|masked|last4|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu + ISO tarihi eler (10.1.x deseni)."""
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
# Deterministik yardımcılar — profil çözümü + sanal-saat tarih geçerliliği (Date.now/random YOK).
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
    """country → profil. Açık profile_id öncelikli; yoksa country eşleşmesi; yoksa None (fail-closed)."""
    profiles = cfg.get("profiles", {})
    pid = sample.get("profile_id")
    if pid and pid in profiles:
        return pid, profiles[pid]
    country = sample.get("country")
    for name, prof in profiles.items():
        if prof.get("country") == country:
            return name, prof
    return None, None


def _date_valid(consent, call_time, validity_days):
    """granted_at var ∧ call_time'dan önce (gelecek değil) ∧ süresi dolmamış → True."""
    granted = _parse_date((consent or {}).get("granted_at"))
    call_dt = _parse_date(call_time)
    if granted is None or call_dt is None:
        return False
    if granted > call_dt:               # gelecek-tarihli rıza geçersiz
        return False
    if call_dt > granted + timedelta(days=int(validity_days)):   # süresi dolmuş
        return False
    return True


# ════════════════════════════════════════════════════════════════════════════
def _config(sample):
    """Config = ana profiles.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    if "profiles" in ov:
        cfg.setdefault("profiles", {}).update(ov["profiles"])
    if "consent_validity_default_days" in ov:
        cfg["consent_validity_default_days"] = ov["consent_validity_default_days"]
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek consent ön-kontrol senaryosunu yürüt → ConsentDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen
    ihlal sayacını artırır (10.1.8 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    contact = sample.get("contact_key")
    campaign = sample.get("campaign_id")
    request_id = sample.get("request_id")
    subject_type = sample.get("subject_type")
    country = sample.get("country")
    call_purpose = sample.get("call_purpose")
    call_time = sample.get("call_time")
    consent = sample.get("consent")  # None | {source, granted_at, purposes[], channels[], categories[], soft_basis?}
    campaign_category = sample.get("campaign_category", call_purpose)

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── Altı boyut değerlendirme izi (K9 kanıtı) ──
    dim = {d: None for d in DIMENSIONS}

    terminal = None
    block_reason = None
    basis = "none"
    consent_required = None
    consent_model = None
    resolved_profile = None

    # ── K12 (tenant izolasyonu): rıza yalnız aynı tenant/contact'a ait ──
    bind_tenant = sample.get("bind_tenant")
    consent_tenant = (consent or {}).get("tenant_id") if consent else None
    cross = False
    if "cross_tenant" in inject:
        cross = True
        v["cross_tenant"] += 1            # cross-tenant rıza KABUL edildi → K12 ihlali
    if bind_tenant and bind_tenant != tenant:
        cross = True
        v["cross_tenant"] += 1
    if consent_tenant and consent_tenant != tenant:
        cross = True
        v["cross_tenant"] += 1

    # ── K3 (ülke): profil çöz ──
    resolved_profile, prof = _resolve_profile(sample, cfg)
    if prof is None:
        dim["ülke"] = "fail:unknown_country"
        if "accept_unknown_country" in inject:
            v["unknown_country_allowed"] += 1   # bilinmeyen ülkeye ALLOW → K3 ihlali
            terminal = "ALLOW"; basis = "none"
        else:
            terminal = "BLOCK"; block_reason = "unknown_country"
    else:
        consent_model = prof.get("consent_model")
        dim["ülke"] = "ok:%s" % consent_model
        b2b_exemption = bool(prof.get("b2b_exemption"))
        recognized = set(prof.get("recognized_sources", []))
        validity_days = int(prof.get("consent_validity_days", cfg.get("consent_validity_default_days", 1095)))
        soft_allowed = bool(prof.get("soft_basis_allowed")) or consent_model == "soft_opt_in"

        # ── K4 (birey/şirket): rıza gerekli mi türet ──
        b2b_exempt = (subject_type == "company" and b2b_exemption)
        if "b2b_misexempt" in inject:
            b2b_exempt = True                    # individual'a B2B muafiyet zorla → K4 ihlali
            v["b2b_misexemption"] += 1

        if consent_model == "opt_out":
            consent_required = False
            dim["birey-şirket"] = "ok:opt_out_regime"
        elif b2b_exempt:
            consent_required = False
            dim["birey-şirket"] = "ok:b2b_exempt"
        else:
            consent_required = True
            dim["birey-şirket"] = "ok:consent_required(%s)" % subject_type

        if not consent_required:
            # opt_out veya B2B-muaf: consent boyutu sağlandı. Rıza kaydı VARSA tarih/kapsam yine geçerli olmalı.
            basis = "b2b_exempt" if b2b_exempt else "opt_out"
            terminal = "ALLOW"
            # opt_out: DNC ayrı kapı (10.2.2); burada consent boyutu ALLOW.
            for d in ("kaynak", "tarih", "amaç", "kapsam"):
                dim[d] = "skip:consent_not_required"
        else:
            # ── Rıza gerekli: altı boyut fail-closed ──
            soft_basis = bool((consent or {}).get("soft_basis")) and soft_allowed
            has_explicit = consent is not None and bool(consent.get("source"))

            if not has_explicit and soft_basis:
                # soft_opt_in mevcut-müşteri dayanağı (açık kaynak yok; kategori eşleşmeli)
                cats = set((consent or {}).get("categories", []))
                if campaign_category in cats or not cats:
                    basis = "soft_basis"
                    terminal = "ALLOW"
                    for d in ("kaynak", "tarih", "amaç", "kapsam"):
                        dim[d] = "ok:soft_basis"
                else:
                    terminal = "BLOCK"; block_reason = "out_of_scope"
                    dim["kapsam"] = "fail:soft_basis_category"
            elif not has_explicit:
                terminal = "BLOCK"; block_reason = "no_consent"
                dim["kaynak"] = "fail:no_consent"
            else:
                src = (consent or {}).get("source")
                purposes = set((consent or {}).get("purposes", []))
                channels = set((consent or {}).get("channels", []))
                categories = set((consent or {}).get("categories", []))

                # K5 kaynak
                source_ok = src in recognized
                if not source_ok and "accept_unknown_source" in inject:
                    source_ok = True
                    v["invalid_source_allowed"] += 1   # tanınmayan kaynağa ALLOW → K5 ihlali
                # K6 tarih
                date_ok = _date_valid(consent, call_time, validity_days)
                if not date_ok and "accept_expired" in inject:
                    date_ok = True
                    v["expired_allowed"] += 1          # süresi dolmuşa ALLOW → K6 ihlali
                # K2 amaç
                purpose_ok = call_purpose in purposes
                if not purpose_ok and "accept_wrong_purpose" in inject:
                    purpose_ok = True
                    v["purpose_mismatch_allowed"] += 1  # yanlış amaca ALLOW → K2 ihlali
                # K7 kapsam (kanal + kategori)
                scope_ok = (CHANNEL in channels) and (campaign_category in categories)
                if not scope_ok and "accept_out_of_scope" in inject:
                    scope_ok = True
                    v["out_of_scope_allowed"] += 1     # kapsam dışına ALLOW → K7 ihlali

                dim["kaynak"] = "ok" if source_ok else "fail"
                dim["tarih"] = "ok" if date_ok else "fail"
                dim["amaç"] = "ok" if purpose_ok else "fail"
                dim["kapsam"] = "ok" if scope_ok else "fail"

                # Fail-closed sıralı: kaynak → tarih → amaç → kapsam
                if not source_ok:
                    terminal = "BLOCK"; block_reason = "invalid_source"
                elif not date_ok:
                    terminal = "BLOCK"; block_reason = "expired_or_invalid_date"
                elif not purpose_ok:
                    terminal = "BLOCK"; block_reason = "purpose_mismatch"
                elif not scope_ok:
                    terminal = "BLOCK"; block_reason = "out_of_scope"
                else:
                    terminal = "ALLOW"; basis = "explicit"

    # ── K8 (fail-closed / ATLANAMAZ): bypass → consent_skip ihlali ──
    # skip_precheck: BLOCK olması gereken bir kararı 'ALLOW' yapıp ön-kontrolü atlar.
    if "skip_precheck" in inject:
        if terminal == "BLOCK":
            terminal = "ALLOW"
            basis = "none"
            block_reason = None
        v["consent_skip"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    allow = terminal == "ALLOW"
    consent_ok = allow  # 10.2.2 DNC kapısına AND girdisi

    # ── Kanıt (K9) ──
    evidence = {
        "request_id": request_id,
        "country": country,
        "resolved_profile": resolved_profile,
        "consent_model": consent_model,
        "subject_type": subject_type,
        "consent_required": consent_required,
        "dimensions": dim,
        "block_reason": block_reason,
        "basis": basis,
        "terminal": terminal,
    }
    if (not request_id) or (terminal is None) or (consent_required is None and terminal != "BLOCK"):
        # terminal BLOCK (unknown_country) durumunda consent_required None olabilir — kanıt yine de tam
        if not request_id or terminal is None:
            v["missing_evidence"] += 1

    # ── Audit (K10) ── (ham PII YOK — yalnız enum/kimlik)
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
            "consent_model": consent_model,
            "block_reason": block_reason,
            "basis": basis,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "allow": allow,
        "consent_ok": consent_ok,
        "consent_required": consent_required,
        "consent_model": consent_model,
        "resolved_profile": resolved_profile,
        "block_reason": block_reason,
        "basis": basis,
        "dimensions": dim,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "consent_skip": "max_consent_skip",
        "purpose_mismatch_allowed": "max_purpose_mismatch_allowed",
        "unknown_country_allowed": "max_unknown_country_allowed",
        "b2b_misexemption": "max_b2b_misexemption",
        "invalid_source_allowed": "max_invalid_source_allowed",
        "expired_allowed": "max_expired_allowed",
        "out_of_scope_allowed": "max_out_of_scope_allowed",
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
        for key in ("terminal", "allow", "block_reason", "basis", "consent_required"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s reason=%s basis=%s model=%s profil=%s req=%s"
              % (res["terminal"], res["block_reason"], res["basis"], res["consent_model"],
                 res["resolved_profile"], res["consent_required"]))
        print("   boyutlar=%s" % res["dimensions"])
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
    for f in ("wbs", "phase", "priority", "trace", "placement", "dimensions", "consent_models",
              "decision", "block_reasons", "outcomes", "authorization", "gates", "observability",
              "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=10.2.1", spec.get("wbs") == "10.2.1")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-OUT-003 izlenir (consent ön-kontrol)", "FR-OUT-003" in tr.get("fr", []))
    chk("FR-OUT-006 izlenir (opt-out)", "FR-OUT-006" in tr.get("fr", []))
    chk("FR-TEL-014 izlenir (DNC — 10.2.2 köprü)", "FR-TEL-014" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-OUT-003 izlenir", "SR-OUT-003" in tr.get("srs", []))
    chk("TC-OUT-003 izlenir", "TC-OUT-003" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §19.1 Consent Engine izlenir", any("§19.1" in s for s in tr.get("sad", [])))
    chk("BRD §14.3 izlenir", any("§14.3" in s for s in tr.get("brd", [])))

    # 3) Altı boyut (SR-OUT-003 çekirdek)
    dimz = spec["dimensions"]
    dim_ids = [d["id"] for d in dimz.get("list", [])]
    chk("altı boyut tam (amaç/ülke/birey-şirket/kaynak/tarih/kapsam)", set(dim_ids) == set(DIMENSIONS))
    chk("değerlendirme fail_closed_ordered", dimz.get("evaluation") == "fail_closed_ordered")
    for d in dimz.get("list", []):
        chk("boyut %s invariant+block_reason taşır" % d["id"],
            d.get("invariant") in INVARIANT_IDS and d.get("block_reason") in BLOCK_REASONS)

    # 4) Consent modelleri
    cm = spec["consent_models"]
    chk("opt_in modeli tanımlı", "opt_in" in cm)
    chk("soft_opt_in modeli tanımlı", "soft_opt_in" in cm)
    chk("opt_out modeli tanımlı", "opt_out" in cm)

    # 5) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (deny-by-default)", dec.get("default") == "BLOCK")

    # 6) Sonuçlar + block_reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar ALLOW+BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam", br == set(BLOCK_REASONS))

    # 7) Yetki — config-düzeyi consent:manage, per-call otomatik gate
    az = spec["authorization"]
    chk("policy_permission=consent:manage", az.get("policy_permission") == "consent:manage")
    chk("per_call_check otomatik gate", "automatic_gate" in az.get("per_call_check", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_consent_skip", "max_purpose_mismatch_allowed", "max_unknown_country_allowed",
               "max_b2b_misexemption", "max_invalid_source_allowed", "max_expired_allowed",
               "max_out_of_scope_allowed", "max_cross_tenant", "max_missing_evidence",
               "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("consent_skip_total metrik (K8 alarm)", "consent_skip_total" in obs.get("metrics", []))
    chk("consent_block_total metrik", "consent_block_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/contact_key YÜKSEK kard (label değil)",
        "request_id" in hi and "contact_key" in hi and "request_id" not in lo)
    chk("consent_source_value YÜKSEK kard (label değil)", "consent_source_value" in hi)
    chk("result/block_reason/basis DÜŞÜK kard (label uygun)",
        "result" in lo and "block_reason" in lo and "basis" in lo)
    chk("alarm consent_skip ≤2dk", "consent_skip" in obs.get("alarm", ""))

    # 10) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 11) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/consent-precheck-profiles.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        profs = cfg.get("profiles", {})
        chk("config PROFILE-TR var (opt_in/IYS)",
            profs.get("PROFILE-TR", {}).get("consent_model") == "opt_in"
            and profs.get("PROFILE-TR", {}).get("consent_registry") == "IYS")
        chk("config PROFILE-UK var (soft_opt_in/TPS_CTPS)",
            profs.get("PROFILE-UK", {}).get("consent_model") == "soft_opt_in")
        chk("config PROFILE-TR b2b_exemption=false (ETK)",
            profs.get("PROFILE-TR", {}).get("b2b_exemption") is False)
        chk("config her profil recognized_sources taşır",
            all(p.get("recognized_sources") for p in profs.values()))
        chk("config her profil consent_validity_days taşır",
            all(isinstance(p.get("consent_validity_days"), int) for p in profs.values()))
        chk("config channel=voice", cfg.get("channel") == CHANNEL)

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
    chk("hiç müşteri-PII/telefon/hesap-no/OTP/sır sızıntısı yok (K12)", total_leaks == 0)

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
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "campaign_id": "camp-1", "contact_key": "ck-1",
            "subject_type": "individual", "country": "TR",
            "call_purpose": "sales", "campaign_category": "sales",
            "call_time": "2026-06-15T10:00:00",
            "consent": {
                "source": "IYS", "granted_at": "2025-06-15T10:00:00",
                "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"],
            },
        }
        d.update(kw)
        return d

    # 1) happy — TR opt_in, geçerli rıza altı boyut → ALLOW explicit
    r = build(req(), spec)
    case("happy: ALLOW", r["terminal"] == "ALLOW")
    case("happy: basis=explicit", r["basis"] == "explicit")
    case("happy: consent_required=true", r["consent_required"] is True)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: audit ALLOW (K10)", r["audit"] is not None and r["audit"]["result"] == "ALLOW")
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm — aynı girdi birebir aynı sonuç
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 3) no_consent — rıza yok → BLOCK no_consent (fail-closed)
    r = build(req(consent=None), spec)
    case("no-consent: BLOCK", r["terminal"] == "BLOCK")
    case("no-consent: reason=no_consent", r["block_reason"] == "no_consent")
    case("no-consent: ihlal yok (doğru reddetme)", all(x == 0 for x in r["violations"].values()))
    case("no-consent: kapı geçer (BLOCK doğru)", _gate_eval(r, G)[0] is True)

    # 4) purpose_mismatch (K2) — amaç kapsam dışı → BLOCK
    r = build(req(call_purpose="debt_collection"), spec)
    case("purpose: BLOCK purpose_mismatch", r["terminal"] == "BLOCK" and r["block_reason"] == "purpose_mismatch")

    # 5) unknown_country (K3) — bilinmeyen ülke → fail-closed BLOCK
    r = build(req(country="ZZ"), spec)
    case("country: BLOCK unknown_country", r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_country")

    # 6) invalid_source (K5) — tanınmayan kaynak → BLOCK
    r = build(req(consent={"source": "scraped_list", "granted_at": "2025-06-15T10:00:00",
                           "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]}), spec)
    case("source: BLOCK invalid_source", r["terminal"] == "BLOCK" and r["block_reason"] == "invalid_source")

    # 7) expired (K6) — TR validity 1095g; 4 yıl önce rıza → süresi dolmuş → BLOCK
    r = build(req(consent={"source": "IYS", "granted_at": "2021-01-01T10:00:00",
                           "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]}), spec)
    case("date: BLOCK expired", r["terminal"] == "BLOCK" and r["block_reason"] == "expired_or_invalid_date")

    # 7b) gelecek-tarihli rıza → geçersiz → BLOCK
    r = build(req(consent={"source": "IYS", "granted_at": "2027-01-01T10:00:00",
                           "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]}), spec)
    case("date: gelecek-tarihli BLOCK", r["terminal"] == "BLOCK" and r["block_reason"] == "expired_or_invalid_date")

    # 8) out_of_scope (K7) — kanal voice değil → BLOCK
    r = build(req(consent={"source": "IYS", "granted_at": "2025-06-15T10:00:00",
                           "purposes": ["sales"], "channels": ["sms"], "categories": ["sales"]}), spec)
    case("scope: BLOCK out_of_scope (kanal)", r["terminal"] == "BLOCK" and r["block_reason"] == "out_of_scope")

    # 9) B2B muafiyet (K4) — UK company + b2b_exemption=true → rıza gerekmez → ALLOW b2b_exempt
    r = build(req(country="UK", subject_type="company", consent=None), spec)
    case("b2b: ALLOW b2b_exempt (UK company)", r["terminal"] == "ALLOW" and r["basis"] == "b2b_exempt")
    case("b2b: consent_required=false", r["consent_required"] is False)

    # 9b) UK individual rıza yok → soft_opt_in açık rıza yok → BLOCK no_consent
    r = build(req(country="UK", subject_type="individual", consent=None), spec)
    case("uk-individual: BLOCK no_consent", r["terminal"] == "BLOCK" and r["block_reason"] == "no_consent")

    # 9c) TR company b2b_exemption=false → rıza yine gerekli → BLOCK no_consent
    r = build(req(country="TR", subject_type="company", consent=None), spec)
    case("tr-company: rıza gerekli BLOCK", r["terminal"] == "BLOCK" and r["consent_required"] is True)

    # 10) opt_out rejimi — US-OPTOUT, rıza yok → ALLOW opt_out (DNC ayrı)
    r = build(req(country="US", profile_id="PROFILE-US-OPTOUT", subject_type="individual", consent=None), spec)
    case("opt-out: ALLOW basis=opt_out", r["terminal"] == "ALLOW" and r["basis"] == "opt_out")
    case("opt-out: consent_required=false", r["consent_required"] is False)

    # 11) soft_opt_in — UK individual, soft_basis + kategori eşleşir → ALLOW soft_basis
    r = build(req(country="UK", subject_type="individual",
                  consent={"soft_basis": True, "categories": ["sales"]}, campaign_category="sales"), spec)
    case("soft-basis: ALLOW soft_basis", r["terminal"] == "ALLOW" and r["basis"] == "soft_basis")

    # ── degrade injection'ları → ihlal + kapı eler ──
    # 12) skip_precheck (K8) — BLOCK'u atla → consent_skip ihlali
    r = build(req(consent=None), spec, inject=["skip_precheck"])
    case("inject-skip: consent_skip>0", r["violations"]["consent_skip"] > 0)
    case("inject-skip: kapı eler", _gate_eval(r, G)[0] is False)
    case("inject-skip: terminal ALLOW'a zorlandı", r["terminal"] == "ALLOW")

    # 13) accept_wrong_purpose (K2)
    r = build(req(call_purpose="debt_collection"), spec, inject=["accept_wrong_purpose"])
    case("inject-purpose: purpose_mismatch_allowed>0", r["violations"]["purpose_mismatch_allowed"] > 0)
    case("inject-purpose: kapı eler", _gate_eval(r, G)[0] is False)

    # 14) accept_unknown_country (K3)
    r = build(req(country="ZZ"), spec, inject=["accept_unknown_country"])
    case("inject-country: unknown_country_allowed>0", r["violations"]["unknown_country_allowed"] > 0)
    case("inject-country: kapı eler", _gate_eval(r, G)[0] is False)

    # 15) b2b_misexempt (K4) — individual'a B2B muafiyet
    r = build(req(country="TR", subject_type="individual", consent=None), spec, inject=["b2b_misexempt"])
    case("inject-b2b: b2b_misexemption>0", r["violations"]["b2b_misexemption"] > 0)
    case("inject-b2b: kapı eler", _gate_eval(r, G)[0] is False)

    # 16) accept_unknown_source (K5)
    r = build(req(consent={"source": "scraped_list", "granted_at": "2025-06-15T10:00:00",
                           "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]}),
              spec, inject=["accept_unknown_source"])
    case("inject-source: invalid_source_allowed>0", r["violations"]["invalid_source_allowed"] > 0)
    case("inject-source: kapı eler", _gate_eval(r, G)[0] is False)

    # 17) accept_expired (K6)
    r = build(req(consent={"source": "IYS", "granted_at": "2021-01-01T10:00:00",
                           "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]}),
              spec, inject=["accept_expired"])
    case("inject-expired: expired_allowed>0", r["violations"]["expired_allowed"] > 0)
    case("inject-expired: kapı eler", _gate_eval(r, G)[0] is False)

    # 18) accept_out_of_scope (K7)
    r = build(req(consent={"source": "IYS", "granted_at": "2025-06-15T10:00:00",
                           "purposes": ["sales"], "channels": ["sms"], "categories": ["sales"]}),
              spec, inject=["accept_out_of_scope"])
    case("inject-scope: out_of_scope_allowed>0", r["violations"]["out_of_scope_allowed"] > 0)
    case("inject-scope: kapı eler", _gate_eval(r, G)[0] is False)

    # 19) cross_tenant (K12)
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)
    r = build(req(consent={"source": "IYS", "granted_at": "2025-06-15T10:00:00", "tenant_id": "t-foreign",
                           "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]}), spec)
    case("consent-tenant-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 20) no_audit (K10)
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 21) kanıt (K9) — altı boyut + profil + model taşır
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: altı boyut taşır", set(r["evidence"]["dimensions"].keys()) == set(DIMENSIONS))
    case("evidence: resolved_profile=PROFILE-TR", r["evidence"]["resolved_profile"] == "PROFILE-TR")
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 22) audit (K10) — result + country + consent_model + tenant taşır, ham PII yok
    case("audit: result taşır", r["audit"]["result"] == "ALLOW")
    case("audit: country taşır", r["audit"]["country"] == "TR")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")
    case("audit: telefon/ad alanı yok", "customer_phone_value" not in json.dumps(r["audit"])
         and "customer_name" not in json.dumps(r["audit"]))

    # 23) consent_ok = ALLOW (10.2.2 DNC AND girdisi)
    r_allow = build(req(), spec)
    r_block = build(req(consent=None), spec)
    case("consent_ok: ALLOW→true", r_allow["consent_ok"] is True)
    case("consent_ok: BLOCK→false", r_block["consent_ok"] is False)

    # 24) sızıntı tarayıcı: yapısal kimlik/ISO tarih temiz, ham PII/telefon yakalanır
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: ck-001 kimlik temiz", scan_leaks('{"contact_key": "ck-001"}') == [])
    case("leak: ISO tarih temiz", scan_leaks('{"granted_at": "2025-06-15T10:00:00"}') == [])
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
        "module": "consent-precheck (WBS 10.2.1 — FR-OUT-003 Consent Engine ön-kontrol)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "dimensions": DIMENSIONS,
        "consent_models": CONSENT_MODELS,
        "bases": BASES,
        "block_reasons": BLOCK_REASONS,
        "decision": "resolve_profile → derive_consent_required(consent_model,subject_type,b2b) → "
                    "[opt_out|b2b_exempt ⇒ ALLOW] → fail-closed validate(source,date,purpose,scope) → ALLOW|BLOCK",
        "default": "BLOCK (deny-by-default / fail-closed)",
        "channel": CHANNEL,
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "campaign_id",
                           "contact_key", "subject_type(individual|company)", "country", "call_purpose",
                           "campaign_category", "call_time(ISO)",
                           "consent{source, granted_at(ISO), purposes[], channels[], categories[], soft_basis?, tenant_id?}",
                           "profile_id?", "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "allow", "consent_ok", "consent_required", "consent_model",
                            "resolved_profile", "block_reason", "basis", "dimensions", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-OUT-003, SR-OUT-003, TC-OUT-003, FR-OUT-006, FR-TEL-014, FR-IAM-006, FR-TEN-002, "
                 "FR-REC-004, BRD §14.3, SAD §19.1, DPIA §5.3 cp.outbound.*, DB.md consent, API §A-10, "
                 "ADR-001/002/012",
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
            print("kullanım: consent_precheck_probe.py check <sample.json|dizin>")
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
