#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.7 — Temsilci yoksa callback/voicemail/ticket referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) YEDİNCİ modülü ve F1-Must aktarım çekirdeği.
FR-HND-007 ('Temsilci bulunamazsa callback, voicemail veya ticket sunulmalıdır') temsilci-yok
FALLBACK MOTORUNU sahiplenir. SAD §7.3 Human Handoff diyagramının son dalı
'└─ temsilci yoksa ──► callback / voicemail / ticket (FR-HND-007)' noktasıdır. 9.1 (cold) C4 /
9.2 (warm) W5 / 9.3 (whisper) H5 fail-safe ve 9.5 (hedef seçimi) R10 UNRESOLVED bu modülü TETİKLER;
modül onların ürettiği no-agent durumunu TÜKETİR ve müşteriye ASLA çağrıyı düşürmeden ertelenmiş bir
hizmet yolu SUNAR. Modül bir FALLBACK SUNUM/SEÇİM MOTORUdur (deterministik):

  EVALUATING → OFFERING → CAPTURING ──(seçim + önkoşul OK)──► FULFILLED   (terminal — callback/voicemail/ticket, K2)
                                    └─(red / yakalama hatası)─► SAFE_CLOSE  (terminal — fail-safe oto-ticket, K8)

Üç fallback türü (FR-HND-007): callback (onaylı geri-arama planı) / voicemail (kayıt onayı+AI ifşası ile) /
ticket (DAİMA-mevcut asenkron son çare). Uygun küme asla boş kalmaz (K3); daima alternatif sunulur (K2);
çağrı asla sessiz düşmez (K8).

ÇEKİRDEK INVARIANT (BRD §9.12 + SR-HND-007): temsilci yokken daima alternatif sunulur (K2); son çare daima
mevcut (K3); önkoşul sağlanır (K4); onay+AI ifşası (K5); geçerli no-agent tetiği (K6); tenant izolasyonu (K7);
fail-safe minimum, asla sessiz düşme (K8); her sonuç kanıt (K9) + audit (K10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): aktarım MEKANİZMASI → 9.1/9.2/9.3 (fail-safe dalını SAHİPLENİR);
tetikleme → 9.4; hedef seçimi → 9.5; bağlam paketi → 9.6 (context_ref TÜKETİR); raporlama → 9.8; callback
ÇEVİRME → outbound dialer (10.x, FR-TEL-009/FR-OUT-005); giden voicemail BIRAKMA → 10.1.5/FR-TEL-011; gerçek
ticket API → tool/entegrasyon (11.x); AI ifşa METNİ → diyalog (3.x); kayıt depolama → 12.x; audit store → 7.1.6/12.1.8.

Kullanım:
  no_agent_fallback_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  no_agent_fallback_probe.py run <sample>       Fallback motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  no_agent_fallback_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  no_agent_fallback_probe.py schema             Durum/istek/sonuç sözleşmesini yazdır

Determinizm: sanal zaman + yapısal kimlikler; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (müşteri adı/telefon/voicemail içeriği/ticket gövdesi/OTP) üretilmez/yazılmaz
(fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "no-agent-fallback-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "no-agent-fallback-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["EVALUATING", "OFFERING", "CAPTURING", "FULFILLED", "SAFE_CLOSE"]
NON_TERMINAL = {"EVALUATING", "OFFERING", "CAPTURING"}
TERMINAL = {"FULFILLED", "SAFE_CLOSE"}
OPTIONS = ["callback", "voicemail", "ticket"]
LAST_RESORT = "ticket"
VALID_REASONS = ["no_agent_available", "queue_full", "transfer_failed", "unresolved_target", "after_hours"]
INVALID_REASONS = ["agent_available"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
INJECTIONS = {"no_offer", "drop_last_resort", "unmet_prerequisite", "skip_consent",
              "invalid_trigger", "silent_drop", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "no_offer", "empty_eligible", "unmet_prerequisite", "missing_consent", "no_disclosure",
    "invalid_trigger", "cross_tenant", "silent_drop", "missing_evidence", "missing_audit",
    "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 9.1–9.6 deseniyle) — müşteri adı/telefon/voicemail içeriği/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # ham müşteri içeriği / sır DEĞERİ alanı (yalnız yapısal kimlik/maskeli token taşımalı)
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|voicemail_audio|voicemail_text|ticket_body_text|otp_code_value|password_value|raw_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|tok-|q-|sg-|dept-|cb-|vm-|tkt-|fb-|res-|proj-|window-|corr-|call-|ctx-|t-|prefix|ticket-auto|last4|masked)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (9.1–9.6 deseni)."""
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
# Fallback motoru — FallbackRequest'i uygun-küme + sunum + seçim + kayda çevirir.
# ════════════════════════════════════════════════════════════════════════════
def _config_from(sample, spec):
    """Config = ana no-agent-fallback-policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("options", "offer_order", "last_resort", "trigger_reasons", "prerequisites", "consent"):
        if k in ov:
            cfg[k] = ov[k]
    return cfg


def _prereq_met(opt, sample, inject):
    """Bir seçeneğin önkoşulları (kanal/onay/ifşa/pencere) sağlanıyor mu? (uygunluk için).

    Not: skip_consent uygunluğu DEĞİL, yakalama-anı onay işlemeyi bozar (engine onayı
    onurlandırmaz/kaydetmez) — bu yüzden burada değil, CAPTURING onay kontrolünde ele alınır."""
    avail = sample.get("channel_availability", {}) or {}
    consent = sample.get("consent", {}) or {}
    if not avail.get(opt, True):
        return False
    if opt == "callback":
        if not consent.get("callback"):
            return False
        if not sample.get("callback_window"):
            return False
    if opt == "voicemail":
        if not consent.get("recording"):
            return False
        if not sample.get("ai_disclosure"):
            return False
    return True


def build(sample, spec, inject=None, cfg=None):
    """Tek fallback senaryosunu yürüt → FallbackOutcome + ihlal sayaçları.

    Motor DOĞRU davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal
    sayacını artırır (9.1–9.6 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config_from(sample, spec)
    tenant = sample.get("tenant_id")
    reason = sample.get("reason")
    consent = sample.get("consent", {}) or {}
    avail = sample.get("channel_availability", {}) or {}

    options = cfg.get("options", OPTIONS)
    order = cfg.get("offer_order", options)
    last_resort = cfg.get("last_resort", LAST_RESORT)
    valid_reasons = set(cfg.get("trigger_reasons", VALID_REASONS))

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── K6: geçerli no-agent tetiği ──────────────────────────────────────────────────
    effective_reason = reason
    if "invalid_trigger" in inject:
        effective_reason = "agent_available"  # temsilci varken fallback zorlanıyor → K6
    if effective_reason not in valid_reasons:
        v["invalid_trigger"] += 1

    # ── 1) EVALUATING — uygun seçenekleri (eligible) önceliğe göre hesapla ─────────────
    eligible = [o for o in order if o in options and _prereq_met(o, sample, inject)]
    # ticket DAİMA-mevcut son çare: kanalı açıksa uygun kümede bulunmalı (K3)
    if (last_resort in options) and avail.get(last_resort, True) and last_resort not in eligible:
        eligible.append(last_resort)
    if "drop_last_resort" in inject:
        eligible = [o for o in eligible if o != last_resort]  # son çareyi kaldır → K3 ihlali

    if not eligible:
        v["empty_eligible"] += 1

    # ── 2) OFFERING — uygun seçenekleri müşteriye sun (K2) ─────────────────────────────
    offered = [] if "no_offer" in inject else list(eligible)
    if not offered:
        v["no_offer"] += 1

    # ── 3) CAPTURING — müşteri seçimi + gerekli veri (onay/ifşa) ───────────────────────
    choice = sample.get("customer_choice")
    selectable = (choice in offered) or ("unmet_prerequisite" in inject and choice in options)
    terminal = None
    outcome_type = None
    reference_id = None
    failsafe = False

    if choice and choice != "decline" and selectable:
        # müşteri sunulan bir seçeneği seçti → karşıla (önkoşul kontrolüyle)
        terminal = "FULFILLED"
        outcome_type = choice
        prefix = {"callback": "cb-", "voicemail": "vm-", "ticket": "tkt-"}.get(choice, "fb-")
        reference_id = prefix + str(sample.get("call_id", "x"))

        # K4 — karşılanan seçenek uygun olmalı
        if choice not in eligible:
            v["unmet_prerequisite"] += 1

        # K5 — onay + AI ifşası
        if choice == "callback":
            if "skip_consent" in inject or not consent.get("callback"):
                v["missing_consent"] += 1
        if choice == "voicemail":
            if "skip_consent" in inject or not consent.get("recording"):
                v["missing_consent"] += 1
            if "skip_consent" in inject or not sample.get("ai_disclosure"):
                v["no_disclosure"] += 1
    else:
        # müşteri reddetti / yanıt vermedi / yakalanamadı → fail-safe oto-ticket (K8)
        terminal = "SAFE_CLOSE"
        if "silent_drop" in inject:
            v["silent_drop"] += 1          # fail-safe oto-ticket OLUŞTURULMADI → çağrı sessiz düştü
            outcome_type = None
            reference_id = None
            failsafe = False
        else:
            outcome_type = "ticket"        # bağlamdan oto-ticket
            reference_id = "ticket-auto-" + str(sample.get("call_id", "x"))
            failsafe = True

    # ── K7 — tenant izolasyonu (kaynak + bağlanan kaynak bu tenant) ───────────────────
    source_tenant = tenant
    resource = "res-" + str(tenant)
    if "cross_tenant" in inject:
        resource = "res-foreigntenant"     # başka tenant'ın kuyruğu/ticket projesine bağla → K7
        source_tenant = "t-other-tenant"
    if source_tenant != tenant:
        v["cross_tenant"] += 1
    bind_tenant = sample.get("bind_tenant")
    if bind_tenant and bind_tenant != tenant:
        v["cross_tenant"] += 1
    if "cross_tenant" in inject and resource == "res-foreigntenant" and v["cross_tenant"] == 0:
        v["cross_tenant"] += 1

    # ── Kanıt (K9) ─────────────────────────────────────────────────────────────────────
    evidence = {
        "reason": effective_reason,
        "offered_options": offered,
        "eligible_options": eligible,
        "selected": outcome_type,
        "reference_id": reference_id,
        "source_session": sample.get("call_id"),
        "context_ref": sample.get("context_ref"),
        "failsafe": failsafe,
        "terminal": terminal,
    }
    if (not offered) or (reference_id is None) or (not effective_reason):
        v["missing_evidence"] += 1

    # ── Audit (K10) ─────────────────────────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "terminal": terminal,
            "type": outcome_type,
            "reference_id": reference_id,
            "reason": effective_reason,
            "offered_options": offered,
            "consent": {"callback": bool(consent.get("callback")), "recording": bool(consent.get("recording"))},
            "ai_disclosure": bool(sample.get("ai_disclosure")),
            "failsafe": failsafe,
            "resource": resource,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "outcome_type": outcome_type,
        "reference_id": reference_id,
        "offered": offered,
        "offered_count": len(offered),
        "eligible": eligible,
        "eligible_count": len(eligible),
        "failsafe": failsafe,
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
        "no_offer": "max_no_offer",
        "empty_eligible": "max_empty_eligible",
        "unmet_prerequisite": "max_unmet_prerequisite",
        "missing_consent": "max_missing_consent",
        "no_disclosure": "max_no_disclosure",
        "invalid_trigger": "max_invalid_trigger",
        "cross_tenant": "max_cross_tenant",
        "silent_drop": "max_silent_drop",
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
        fails.append("fallback/audit kaydı üretilmedi (K10)")
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
        for key in ("terminal", "resolved", "outcome_type", "offered_count",
                    "eligible_count", "failsafe"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s type=%s offered=%d eligible=%d failsafe=%s"
              % (res["terminal"], res["outcome_type"], res["offered_count"],
                 res["eligible_count"], res["failsafe"]))
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
    for f in ("wbs", "phase", "priority", "trace", "placement", "states", "transitions",
              "fallback_options", "trigger_reasons", "consent", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.7", spec.get("wbs") == "9.7")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-HND-007 izlenir (temsilci yoksa callback/voicemail/ticket)", "FR-HND-007" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("SR-HND-007 izlenir", "SR-HND-007" in tr.get("srs", []))
    chk("TC-HND-007 izlenir", "TC-HND-007" in tr.get("rtm", []))
    chk("ADR-001/002 izlenir", any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", [])))
    chk("SAD §7.3 izlenir", any("§7.3" in s for s in tr.get("sad", [])))
    chk("SAD §6 fail-soft izlenir", any("§6" in s for s in tr.get("sad", [])))

    # 3) Durum makinesi tutarlılığı
    st = spec["states"]
    chk("flow = 5 durum", st.get("flow") == STATES)
    chk("terminal = {FULFILLED,SAFE_CLOSE}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal = {EVALUATING,OFFERING,CAPTURING}", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği
    edges = spec["transitions"]["edges"]
    tos = set(e["to"] for e in edges)
    froms = set(e["from"] for e in edges)
    chk("EVALUATING kaynak", "EVALUATING" in froms)
    chk("FULFILLED hedef erişilebilir", "FULFILLED" in tos)
    chk("SAFE_CLOSE hedef erişilebilir (fail-safe)", "SAFE_CLOSE" in tos)
    chk("on_fulfilled EMIT tanımlı", "EMIT" in spec["transitions"].get("on_fulfilled", ""))
    chk("on_safe_close FAILSAFE + sessiz düşmez",
        "FAILSAFE" in spec["transitions"].get("on_safe_close", "")
        and "düşmez" in spec["transitions"].get("on_safe_close", ""))

    # 5) Fallback seçenekleri + tetik + onay
    fo = spec["fallback_options"]
    chk("üç seçenek callback/voicemail/ticket", fo.get("options") == OPTIONS)
    chk("ticket son çare (last_resort)", fo.get("last_resort") == LAST_RESORT)
    chk("callback önkoşulu consent+window içerir",
        "consent.callback" in fo["prerequisites"]["callback"]
        and "callback_window" in fo["prerequisites"]["callback"])
    chk("voicemail önkoşulu kayıt-onayı+AI-ifşası içerir",
        "consent.recording" in fo["prerequisites"]["voicemail"]
        and "ai_disclosure" in fo["prerequisites"]["voicemail"])
    trg = spec["trigger_reasons"]
    chk("geçerli tetik nedenleri tanımlı", set(VALID_REASONS) <= set(trg.get("valid", [])))
    chk("agent_available geçersiz tetik", "agent_available" in trg.get("invalid", []))
    cs = spec["consent"]
    chk("callback onay gerektirir", cs.get("callback_requires_consent") is True)
    chk("voicemail kayıt onayı gerektirir", cs.get("voicemail_requires_recording_consent") is True)
    chk("voicemail AI ifşası gerektirir", cs.get("voicemail_requires_ai_disclosure") is True)

    # 6) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_no_offer", "max_empty_eligible", "max_unmet_prerequisite", "max_missing_consent",
               "max_no_disclosure", "max_invalid_trigger", "max_cross_tenant", "max_silent_drop",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_fallback_offered_total metrik",
        "handoff_fallback_offered_total" in obs.get("metrics", []))
    chk("handoff_fallback_fulfilled_total metrik",
        "handoff_fallback_fulfilled_total" in obs.get("metrics", []))
    chk("handoff_fallback_safe_close_total metrik (müşteri-kaybı erken-uyarı)",
        "handoff_fallback_safe_close_total" in obs.get("metrics", []))
    chk("cross_tenant_blocked metrik (güvenlik)",
        "handoff_fallback_cross_tenant_blocked_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("phone_number YÜKSEK kard (label değil)", "phone_number" in hi and "phone_number" not in lo)
    chk("callback_id/ticket_id YÜKSEK kard", "callback_id" in hi and "ticket_id" in hi)
    chk("reason/option/type DÜŞÜK kard (label uygun)",
        "reason" in lo and "option" in lo and "type" in lo)

    # 8) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 9) Config dosyası — seçenek + önkoşul + onay + fail-safe
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/no-agent-fallback-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config üç seçenek", cfg.get("options") == OPTIONS)
        chk("config last_resort=ticket", cfg.get("last_resort") == LAST_RESORT)
        chk("config trigger_reasons tanımlı", set(VALID_REASONS) <= set(cfg.get("trigger_reasons", [])))
        ccs = cfg.get("consent", {})
        chk("config callback onay gerektirir", ccs.get("callback_requires_consent") is True)
        chk("config voicemail kayıt-onayı+AI-ifşası gerektirir",
            ccs.get("voicemail_requires_recording_consent") is True
            and ccs.get("voicemail_requires_ai_disclosure") is True)
        fs = cfg.get("failsafe", {})
        chk("config fail-safe action=auto_ticket (asla sessiz düşme)", fs.get("action") == "auto_ticket")
        chk("config consume_from 9.1/9.2/9.3/9.5/9.6",
            set(cfg.get("consume_from", [])) >= {"9.1", "9.2", "9.3", "9.5", "9.6"})
        chk("config report_to=9.8", cfg.get("report_to") == "9.8")

    # 10) Sır/PII tarayıcı — spec + config + samples
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
    chk("hiç müşteri-PII/telefon/voicemail-içeriği/OTP/sır sızıntısı yok (K12)", total_leaks == 0)

    # 11) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
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
            "tenant_id": "t1", "correlation_id": "c1", "call_id": "call-1",
            "reason": "no_agent_available",
            "consent": {"callback": True, "recording": True},
            "ai_disclosure": True,
            "business_hours": True,
            "channel_availability": {"callback": True, "voicemail": True, "ticket": True},
            "callback_window": "window-morning",
            "context_ref": "ctx-call-1",
            "customer_choice": "callback",
        }
        d.update(kw)
        return d

    # 1) happy callback — onaylı, pencere var → FULFILLED type=callback
    r = build(req(), spec)
    case("happy-callback: FULFILLED", r["terminal"] == "FULFILLED")
    case("happy-callback: type=callback", r["outcome_type"] == "callback")
    case("happy-callback: üç seçenek sunuldu", r["offered_count"] == 3)
    case("happy-callback: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy-callback: reference cb- ile başlar", r["reference_id"].startswith("cb-"))
    case("happy-callback: audit var (K10)", r["audit"] is not None and r["audit"]["type"] == "callback")
    case("happy-callback: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) happy voicemail — kayıt onayı + AI ifşası → FULFILLED type=voicemail
    r = build(req(customer_choice="voicemail"), spec)
    case("happy-voicemail: FULFILLED type=voicemail", r["terminal"] == "FULFILLED" and r["outcome_type"] == "voicemail")
    case("happy-voicemail: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy-voicemail: reference vm- ile başlar", r["reference_id"].startswith("vm-"))

    # 3) happy ticket — son çare seçimi → FULFILLED type=ticket
    r = build(req(customer_choice="ticket"), spec)
    case("happy-ticket: FULFILLED type=ticket", r["terminal"] == "FULFILLED" and r["outcome_type"] == "ticket")
    case("happy-ticket: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 4) decline → SAFE_CLOSE fail-safe oto-ticket (K8) — pass, ihlal yok
    r = build(req(customer_choice="decline"), spec)
    case("decline: SAFE_CLOSE", r["terminal"] == "SAFE_CLOSE")
    case("decline: failsafe oto-ticket", r["failsafe"] is True and r["outcome_type"] == "ticket")
    case("decline: reference ticket-auto", r["reference_id"].startswith("ticket-auto"))
    case("decline: ihlal yok (fail-safe geçerli)", all(x == 0 for x in r["violations"].values()))
    case("decline: kapı geçer", _gate_eval(r, G)[0] is True)

    # 5) callback kanalı kapalı → eligible callback'siz; son çare ticket yine var (K3)
    r = build(req(channel_availability={"callback": False, "voicemail": True, "ticket": True},
                  customer_choice="voicemail"), spec)
    case("callback-down: callback uygun değil", "callback" not in r["eligible"])
    case("callback-down: ticket son çare uygun", "ticket" in r["eligible"])
    case("callback-down: empty_eligible=0", r["violations"]["empty_eligible"] == 0)
    case("callback-down: voicemail karşılandı", r["outcome_type"] == "voicemail" and all(x == 0 for x in r["violations"].values()))

    # 6) unresolved_target (9.5'ten) → fallback geçerli; ticket sunulur
    r = build(req(reason="unresolved_target", channel_availability={"callback": False, "voicemail": False, "ticket": True},
                  customer_choice="ticket"), spec)
    case("unresolved: invalid_trigger=0 (geçerli neden)", r["violations"]["invalid_trigger"] == 0)
    case("unresolved: yalnız ticket uygun", r["eligible"] == ["ticket"])
    case("unresolved: FULFILLED ticket", r["outcome_type"] == "ticket" and all(x == 0 for x in r["violations"].values()))

    # 7) inject no_offer → no_offer (K2 ihlali)
    r = build(req(), spec, inject=["no_offer"])
    case("inject-no-offer: no_offer>0", r["violations"]["no_offer"] > 0)
    case("inject-no-offer: offered boş", r["offered_count"] == 0)

    # 8) inject drop_last_resort → empty_eligible (K3 ihlali) — callback/voicemail de kapalı
    r = build(req(channel_availability={"callback": False, "voicemail": False, "ticket": True},
                  customer_choice="ticket"), spec, inject=["drop_last_resort"])
    case("inject-drop-last-resort: empty_eligible>0", r["violations"]["empty_eligible"] > 0)
    case("inject-drop-last-resort: ticket uygun kümede yok", "ticket" not in r["eligible"])

    # 9) inject unmet_prerequisite → unmet_prerequisite (K4 ihlali) — kanal kapalı callback karşılanır
    r = build(req(channel_availability={"callback": False, "voicemail": True, "ticket": True},
                  customer_choice="callback"), spec, inject=["unmet_prerequisite"])
    case("inject-unmet: unmet_prerequisite>0", r["violations"]["unmet_prerequisite"] > 0)

    # 10) inject skip_consent (callback) → missing_consent (K5 ihlali)
    r = build(req(customer_choice="callback"), spec, inject=["skip_consent"])
    case("inject-skip-consent-callback: missing_consent>0", r["violations"]["missing_consent"] > 0)

    # 11) inject skip_consent (voicemail) → missing_consent + no_disclosure (K5 ihlali)
    r = build(req(customer_choice="voicemail"), spec, inject=["skip_consent"])
    case("inject-skip-consent-voicemail: missing_consent>0", r["violations"]["missing_consent"] > 0)
    case("inject-skip-consent-voicemail: no_disclosure>0", r["violations"]["no_disclosure"] > 0)

    # 12) inject invalid_trigger → invalid_trigger (K6 ihlali)
    r = build(req(), spec, inject=["invalid_trigger"])
    case("inject-invalid-trigger: invalid_trigger>0", r["violations"]["invalid_trigger"] > 0)

    # 13) reason=agent_available (inject'siz) → invalid_trigger (K6)
    r = build(req(reason="agent_available"), spec)
    case("agent-available: invalid_trigger>0", r["violations"]["invalid_trigger"] > 0)

    # 14) inject silent_drop → silent_drop (K8 ihlali)
    r = build(req(customer_choice="decline"), spec, inject=["silent_drop"])
    case("inject-silent-drop: silent_drop>0", r["violations"]["silent_drop"] > 0)
    case("inject-silent-drop: oto-ticket yok", r["outcome_type"] is None and r["failsafe"] is False)

    # 15) inject cross_tenant → cross_tenant (K7 ihlali)
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 16) inject no_audit → missing_audit (K10 ihlali)
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 17) determinizm: aynı girdi → aynı sonuç
    s = req()
    r1 = build(s, spec)
    r2 = build(s, spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 18) kapı entegrasyonu: happy geçer, no-offer eler
    rp = build(req(), spec)
    rf = build(req(), spec, inject=["no_offer"])
    case("kapı: happy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: no-offer eler", _gate_eval(rf, G)[0] is False)

    # 19) evidence — neden + sunulan + seçilen + referans taşır (K9)
    r = build(req(), spec)
    case("evidence: reason taşır", r["evidence"]["reason"] == "no_agent_available")
    case("evidence: offered_options taşır", len(r["evidence"]["offered_options"]) == 3)
    case("evidence: reference_id taşır", r["evidence"]["reference_id"] is not None)
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 20) sızıntı tarayıcı: yapısal kimlik temiz, ham PII/telefon yakalanır
    case("leak: cb-001 referans temiz", scan_leaks('{"reference_id": "cb-001"}') == [])
    case("leak: ticket-auto-call-1 temiz", scan_leaks('{"reference_id": "ticket-auto-call-1"}') == [])
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
        "module": "no-agent-fallback (WBS 9.7 — FR-HND-007 temsilci yoksa callback/voicemail/ticket)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "fallback_options": OPTIONS,
        "last_resort": LAST_RESORT,
        "trigger_reasons_valid": VALID_REASONS,
        "trigger_reasons_invalid": INVALID_REASONS,
        "request_fields": ["name", "tenant_id", "correlation_id", "call_id", "reason (9.1/9.2/9.3/9.5'ten)",
                           "consent{callback,recording}", "ai_disclosure", "business_hours",
                           "channel_availability{callback,voicemail,ticket}", "callback_window",
                           "context_ref (9.6'dan)", "customer_choice[callback|voicemail|ticket|decline]",
                           "bind_tenant", "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "outcome_fields": ["terminal", "outcome_type", "reference_id", "offered", "offered_count",
                           "eligible", "eligible_count", "failsafe", "resource", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-HND-007, FR-TEN-002, FR-IAM-006, FR-REC-004, SR-HND-007, TC-HND-007, SAD §7.3, SAD §6, BRD §9.12, ADR-001/002",
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
            print("kullanım: no_agent_fallback_probe.py run <sample.json|dizin>")
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
