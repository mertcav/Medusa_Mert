#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.6 — Bağlam paketi (özet + intent + toplanan alanlar + auth durumu) + screen-pop referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) ALTINCI modülü ve F1-Must aktarım çekirdeği.
FR-HND-004 (görüşme özeti + toplanan bilgiler aktarımı) + FR-HND-005 (müşteri tekrar bilgi
vermek zorunda bırakılmaz) BAĞLAM PAKETİNİ + SCREEN-POP TESLİMİNİ sahiplenir. SAD §7.3 'Orchestrator
(transfer kararı) │ bağlam paketi: özet + intent + toplanan alanlar + auth durumu' satırı +
'Bağlam paketi CC'ye hem ekran-pop (screen-pop) verisi (CTI/CRM üzerinden) hem de transkript özeti
olarak iletilir (FR-HND-004/005)' cümlesinin noktasıdır. 9.4 NE ZAMAN/NEDEN, 9.5 NEREYE; bu modül
temsilciye NE GÖSTERİLECEĞİNİ (bağlam paketi) üretir/teslim eder; 9.1/9.2/9.3 taşıma sırasında TÜKETİR.
Modül bir PAKET DERLEYİCİ + TESLİM MOTORUdur (deterministik):

  ASSEMBLING → REDACTING → DELIVERING ──(screen-pop var)──► DELIVERED  (terminal — EMIT paket, P2 dört bileşen)
                                       └─(screen-pop yok)──► DEGRADED   (terminal — fail-safe verbal/transkript, P8)

Dört zorunlu bileşen (FR-HND-004): summary + intent + collected_fields + auth_status — paket DÖRDÜNÜ taşır.
Redaction (P4/P5): hassas alanlar maskelenir (son-4); auth_status YALNIZ-statü (ham OTP/parola/KBA YOK).

ÇEKİRDEK INVARIANT (BRD §9.12 + SR-HND-004/SR-HND-005): dört bileşen tam (P2); toplanan alanlar pakette
→ tekrar-sormama (P3); auth sırrı sızmaz (P4); hassas alan maskeli (P5); doğru hedefe teslim (P6); tenant
izolasyonu (P7); screen-pop yoksa fail-safe (P8); her paket kanıt (P9); her teslim audit (P10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): aktarım MEKANİZMASI → 9.1/9.2/9.3 (paketi TÜKETİR); tetikleme
→ 9.4; hedef seçimi → 9.5 (target'ı TÜKETİR); temsilci-yok fallback → 9.7; raporlama → 9.8; özet ÜRETİMİ
→ LLM özetleme (3.x/6.x); intent ÜRETİMİ → NLU (3.x); alan toplama → diyalog (3.x); auth YÜRÜTME → auth
modülü (FR-AUTH); gerçek CTI pop → CC (11.x); audit store → 7.1.6/12.1.8.

Kullanım:
  context_package_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  context_package_probe.py run <sample>       Paket derleyici: senaryo(lar)ı çalıştır → kapı (P1–P12)
  context_package_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  context_package_probe.py schema             Durum/istek/paket sözleşmesini yazdır

Determinizm: sanal zaman + yapısal kimlikler; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (müşteri adı/telefon/transkript/OTP) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "context-package-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "context-package-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["ASSEMBLING", "REDACTING", "DELIVERING", "DELIVERED", "DEGRADED"]
NON_TERMINAL = {"ASSEMBLING", "REDACTING", "DELIVERING"}
TERMINAL = {"DELIVERED", "DEGRADED"}
COMPONENTS = ["summary", "intent", "collected_fields", "auth_status"]
AUTH_LEVELS = ["none", "partial", "verified"]
INVARIANT_IDS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "P11", "P12"]
INJECTIONS = {"drop_component", "drop_collected_field", "leak_auth_secret",
              "unmasked_sensitive", "mis_delivery", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "missing_component", "missing_collected_field", "auth_secret_leak", "unmasked_sensitive",
    "mis_delivery", "cross_tenant", "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (P12; 9.1–9.5 deseniyle) — müşteri adı/telefon/hesap no/ham transkript/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # ham müşteri içeriği / sır DEĞERİ alanı (yalnız yapısal kimlik/maskeli token taşımalı)
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|card_number_value|transcript_text|otp_code_value|password_value|kba_answer_value|raw_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|tok-|q-|sg-|dept-|lang:|domain:|tier:|corr-|call-|ctx-|t-|\*{2,}|x{4,}|last4|masked)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (9.1–9.5 deseni)."""
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
# Bağlam paketi derleyici — TransferContext'i dört bileşen + redaction + teslime çevirir.
# ════════════════════════════════════════════════════════════════════════════
def _config_from(sample, spec):
    """Config = ana context-package-policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("required_components", "redaction", "delivery"):
        if k in ov:
            cfg[k] = ov[k]
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek bağlam-paketi senaryosunu yürüt → ContextPackage + ihlal sayaçları.

    Motor DOĞRU davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal
    sayacını artırır (9.1–9.5 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config_from(sample, spec)
    tenant = sample.get("tenant_id")
    session = sample.get("session", {}) or {}
    target = sample.get("target", {}) or {}

    required = cfg.get("required_components", COMPONENTS)
    red = cfg.get("redaction", {})
    auth_secret_fields = set(red.get("auth_secret_fields", []))
    channels = sample.get("delivery_channels", cfg.get("delivery", {}).get("primary", ["screen_pop", "transcript_summary"]))
    screen_pop_available = sample.get("screen_pop_available", True)

    v = {k: 0 for k in VIOLATION_KEYS}
    package = {}

    # ── 1) ASSEMBLING — dört bileşeni oturum durumundan derle ────────────────────────
    if session.get("summary") is not None:
        package["summary"] = session.get("summary")
    if session.get("intent") is not None:
        package["intent"] = session.get("intent")

    # collected_fields (REDACTING — hassas alanlar maskelenir, P5) ───────────────────
    fields_out = []
    for f in session.get("collected_fields", []) or []:
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        sensitive = bool(f.get("sensitive"))
        if sensitive:
            if "unmasked_sensitive" in inject:
                # ham (maskelenmemiş) hassas değeri screen-pop'a koyar → P5 ihlali
                fields_out.append({"name": name, "value": f.get("raw_ref", "RAW::" + str(name)),
                                   "sensitive": True, "masked": False})
            else:
                fields_out.append({"name": name, "value": f.get("masked_value", "****"),
                                   "sensitive": True, "masked": True})
        else:
            fields_out.append({"name": name, "value": f.get("value_token"),
                               "sensitive": False, "masked": False})
    if "drop_collected_field" in inject and fields_out:
        fields_out.pop()  # bir toplanan alanı paketten düşür → P3 ihlali (tekrar-sorma riski)
    package["collected_fields"] = fields_out

    # auth_status (REDACTING — yalnız-statü, ham sır düşürülür, P4) ────────────────────
    auth = session.get("auth", {}) or {}
    auth_status = {"level": auth.get("level"), "methods": list(auth.get("methods", [])),
                   "step_up": auth.get("step_up")}
    if "leak_auth_secret" in inject:
        for sk in auth.get("secrets_present_in_session", []):
            auth_status[sk] = "LEAKED::" + str(sk)  # ham doğrulama sırrını pakete kopyalar → P4 ihlali
    package["auth_status"] = auth_status

    # inject drop_component — zorunlu bir bileşeni paketten çıkar → P2 ihlali ──────────
    if "drop_component" in inject:
        for c in required:
            if c in package:
                del package[c]
                break

    # ── 2) DELIVERING — hedef-kapsamlı teslim (P6/P7) ─────────────────────────────────
    selected_queue = target.get("queue")
    delivered_to = target.get("deliver_to", selected_queue)
    source_tenant = tenant
    if "mis_delivery" in inject:
        delivered_to = "q-misrouted-other"      # 9.5 hedefi yerine yanlış kuyruğa teslim → P6
    if "cross_tenant" in inject:
        delivered_to = "q-foreigntenant"         # başka tenant'ın hedefine teslim → P7
        source_tenant = "t-other-tenant"         # başka tenant oturumundan kurulmuş gibi → P7

    # screen-pop yoksa fail-safe DEGRADED (verbal/transkript fallback) ────────────────
    fallback_context = None
    if (not screen_pop_available) and ("screen_pop" in channels):
        terminal = "DEGRADED"
        channels_used = [c for c in channels if c != "screen_pop"]
        if "transcript_summary" not in channels_used:
            channels_used.append("transcript_summary")
        channels_used.append("whisper")
        fallback_context = {"channel": "whisper+transcript_summary",
                            "summary": package.get("summary"), "intent": package.get("intent")}
    else:
        terminal = "DELIVERED"
        channels_used = list(channels)

    # ── İhlal tespitleri ──────────────────────────────────────────────────────────────
    # P2 — dört zorunlu bileşen tam (collected_fields boş olabilir; summary/intent/auth_status truthy)
    for c in required:
        present = c in package
        if c in ("summary", "intent", "auth_status"):
            present = present and bool(package.get(c)) and bool(package.get(c) != {})
        if c == "auth_status":
            present = "auth_status" in package and bool(package["auth_status"].get("level"))
        if not present:
            v["missing_component"] += 1

    # P3 — oturumda toplanan her alan pakette (tekrar-sormama)
    sess_names = [f.get("name") for f in (session.get("collected_fields", []) or []) if isinstance(f, dict)]
    deliv_names = [f.get("name") for f in package.get("collected_fields", [])]
    v["missing_collected_field"] += sum(1 for n in sess_names if n not in deliv_names)

    # P4 — auth_status içinde yasaklı ham sır alanı yok
    v["auth_secret_leak"] += sum(1 for k in package.get("auth_status", {}) if k in auth_secret_fields)

    # P5 — hassas alan maskeli (maskelenmemiş hassas = ihlal)
    v["unmasked_sensitive"] += sum(1 for f in package.get("collected_fields", [])
                                   if f.get("sensitive") and not f.get("masked"))

    # P6 — doğru hedefe teslim (9.5 seçilen kuyruk)
    if selected_queue and delivered_to != selected_queue and "cross_tenant" not in inject:
        v["mis_delivery"] += 1

    # P7 — tenant izolasyonu (kaynak ve teslim bu tenant)
    if source_tenant != tenant:
        v["cross_tenant"] += 1
    target_tenant = target.get("tenant_id")
    if target_tenant and target_tenant != tenant:
        v["cross_tenant"] += 1
    if "cross_tenant" in inject and delivered_to == "q-foreigntenant":
        # yabancı hedef bu tenant envanterinde değil — cross-tenant teslim
        if v["cross_tenant"] == 0:
            v["cross_tenant"] += 1

    # ── Kanıt (P9) ────────────────────────────────────────────────────────────────────
    components_delivered = [c for c in required if c in package]
    redactions = [f["name"] for f in package.get("collected_fields", []) if f.get("masked")]
    evidence = {
        "source_session": sample.get("call_id"),
        "components_delivered": components_delivered,
        "collected_field_count": len(package.get("collected_fields", [])),
        "redactions": redactions,
        "auth_level": package.get("auth_status", {}).get("level"),
        "target_queue": selected_queue,
        "match_quality": target.get("match_quality"),
        "terminal": terminal,
    }
    if not components_delivered or not selected_queue:
        v["missing_evidence"] += 1

    # ── Audit (P10) ──────────────────────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "terminal": terminal,
            "delivered_to": delivered_to,
            "delivered_components": components_delivered,
            "redaction_count": len(redactions),
            "auth_level": package.get("auth_status", {}).get("level"),
            "channels": channels_used,
            "degraded": terminal == "DEGRADED",
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "delivered": terminal in TERMINAL,
        "delivered_to": delivered_to,
        "channels": channels_used,
        "components": components_delivered,
        "collected_field_count": len(package.get("collected_fields", [])),
        "masked_count": len(redactions),
        "auth_level": package.get("auth_status", {}).get("level"),
        "fallback": terminal == "DEGRADED",
        "fallback_context": fallback_context,
        "package": package,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "missing_component": "max_missing_component",
        "missing_collected_field": "max_missing_collected_field",
        "auth_secret_leak": "max_auth_secret_leak",
        "unmasked_sensitive": "max_unmasked_sensitive",
        "mis_delivery": "max_mis_delivery",
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
        fails.append("teslim/audit kaydı üretilmedi (P10)")
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
        for key in ("terminal", "delivered", "delivered_to", "auth_level",
                    "collected_field_count", "masked_count", "fallback"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s deliver_to=%s comps=%d masked=%d auth=%s fallback=%s"
              % (res["terminal"], res["delivered_to"], len(res["components"]),
                 res["masked_count"], res["auth_level"], res["fallback"]))
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
              "package_components", "redaction", "delivery", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.6", spec.get("wbs") == "9.6")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-HND-004 izlenir (özet+toplanan bilgiler)", "FR-HND-004" in tr.get("fr", []))
    chk("FR-HND-005 izlenir (tekrar-sormama)", "FR-HND-005" in tr.get("fr", []))
    chk("FR-AUTH-005 izlenir (hassas bilgi tam tekrar yok)", "FR-AUTH-005" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("SR-HND-004 izlenir", "SR-HND-004" in tr.get("srs", []))
    chk("SR-HND-005 izlenir", "SR-HND-005" in tr.get("srs", []))
    chk("TC-HND-004 izlenir", "TC-HND-004" in tr.get("rtm", []))
    chk("TC-HND-005 izlenir", "TC-HND-005" in tr.get("rtm", []))
    chk("ADR-001/002 izlenir", any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", [])))
    chk("SAD §7.3 izlenir", any("§7.3" in s for s in tr.get("sad", [])))

    # 3) Durum makinesi tutarlılığı
    st = spec["states"]
    chk("flow = 5 durum", st.get("flow") == STATES)
    chk("terminal = {DELIVERED,DEGRADED}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal = {ASSEMBLING,REDACTING,DELIVERING}", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği
    edges = spec["transitions"]["edges"]
    tos = set(e["to"] for e in edges)
    froms = set(e["from"] for e in edges)
    chk("ASSEMBLING kaynak", "ASSEMBLING" in froms)
    chk("DELIVERED hedef erişilebilir", "DELIVERED" in tos)
    chk("DEGRADED hedef erişilebilir (fail-safe)", "DEGRADED" in tos)
    chk("on_delivered EMIT tanımlı", "EMIT" in spec["transitions"].get("on_delivered", ""))
    chk("on_degraded FAILSAFE tanımlı",
        "FAILSAFE" in spec["transitions"].get("on_degraded", "")
        and "düşmez" in spec["transitions"].get("on_degraded", ""))

    # 5) Bileşenler + redaction + teslim
    pc = spec["package_components"]
    chk("dört bileşen summary/intent/collected_fields/auth_status", pc.get("components") == COMPONENTS)
    chk("auth seviyeleri none/partial/verified", set(pc.get("auth_levels", [])) == set(AUTH_LEVELS))
    rd = spec["redaction"]
    chk("redaction mask_sensitive=true", rd.get("mask_sensitive") is True)
    chk("redaction auth_status_only=true", rd.get("auth_status_only") is True)
    chk("auth_secret_fields OTP/parola/KBA/PAN içerir",
        {"otp_code", "password", "kba_answer", "pan"} <= set(rd.get("auth_secret_fields", [])))
    dl = spec["delivery"]
    chk("teslim kanalları screen_pop+transcript_summary",
        {"screen_pop", "transcript_summary"} <= set(dl.get("channels", [])))
    chk("teslim target_scoped=true (P6)", dl.get("target_scoped") is True)

    # 6) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_missing_component", "max_missing_collected_field", "max_auth_secret_leak",
               "max_unmasked_sensitive", "max_mis_delivery", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_context_delivered_total metrik",
        "handoff_context_delivered_total" in obs.get("metrics", []))
    chk("handoff_context_degraded_total metrik (CTI/CRM down erken-uyarı)",
        "handoff_context_degraded_total" in obs.get("metrics", []))
    chk("handoff_context_redaction_total metrik (PII minimizasyonu kanıtı)",
        "handoff_context_redaction_total" in obs.get("metrics", []))
    chk("cross_tenant_blocked metrik (güvenlik)",
        "handoff_context_cross_tenant_blocked_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("field_value YÜKSEK kard (label değil)", "field_value" in hi and "field_value" not in lo)
    chk("correlation_id YÜKSEK kard", "correlation_id" in hi)
    chk("department/outcome DÜŞÜK kard (label uygun)",
        "department" in lo and "outcome" in lo)

    # 8) İnvariant'lar P1–P12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar P1–P12 tam", inv_ids == INVARIANT_IDS)

    # 9) Config dosyası — bileşen + redaction + teslim
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/context-package-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config dört zorunlu bileşen", cfg.get("required_components") == COMPONENTS)
        creq = cfg.get("redaction", {})
        chk("config redaction mask_sensitive=true", creq.get("mask_sensitive") is True)
        chk("config auth_secret_fields tanımlı",
            {"otp_code", "password", "kba_answer", "pan"} <= set(creq.get("auth_secret_fields", [])))
        cdl = cfg.get("delivery", {})
        chk("config primary screen_pop+transcript_summary",
            {"screen_pop", "transcript_summary"} <= set(cdl.get("primary", [])))
        chk("config fallback transcript_summary+whisper (fail-safe)",
            {"transcript_summary", "whisper"} <= set(cdl.get("fallback", [])))
        chk("config emit hedefleri 9.1/9.2/9.3", set(cfg.get("emit_to", [])) >= {"9.1", "9.2", "9.3"})
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
    chk("hiç müşteri-PII/transkript/OTP/sır sızıntısı yok (P12)", total_leaks == 0)

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

    def ctx(**kw):
        d = {
            "tenant_id": "t1", "correlation_id": "c1", "call_id": "call-1",
            "target": {"department": "billing", "skill_group": "sg-billing-tr",
                       "queue": "q-billing-tr", "deliver_to": "q-billing-tr", "match_quality": "exact"},
            "session": {
                "summary": "summary-ref-1",
                "intent": "billing_dispute",
                "collected_fields": [
                    {"name": "order_id", "sensitive": False, "value_token": "tok-order-a"},
                    {"name": "account_number", "sensitive": True, "masked_value": "****-4321"},
                ],
                "auth": {"level": "verified", "methods": ["otp", "customer_number"],
                         "step_up": "completed", "secrets_present_in_session": ["otp_code"]},
            },
        }
        d.update(kw)
        return d

    # 1) happy path — dört bileşen, doğru hedef, maskeli hassas alan, audit (P2/P3/P5/P6/P10)
    r = build(ctx(), spec)
    case("happy: DELIVERED", r["terminal"] == "DELIVERED")
    case("happy: dört bileşen tam (P2)", set(r["components"]) == set(COMPONENTS))
    case("happy: collected_field_count=2 (P3)", r["collected_field_count"] == 2)
    case("happy: masked_count=1 (hassas alan maskeli, P5)", r["masked_count"] == 1)
    case("happy: deliver_to=q-billing-tr (P6)", r["delivered_to"] == "q-billing-tr")
    case("happy: auth_level=verified", r["auth_level"] == "verified")
    case("happy: ihlal yok", all(v == 0 for v in r["violations"].values()))
    case("happy: audit var (P10)", r["audit"] is not None and r["audit"]["delivered_to"] == "q-billing-tr")
    case("happy: auth_status'ta ham OTP yok (P4)", "otp_code" not in r["package"]["auth_status"])

    # 2) screen-pop yok → DEGRADED fail-safe (P8) — pass, ihlal yok
    r = build(ctx(screen_pop_available=False), spec)
    case("degraded: DEGRADED (fail-safe)", r["terminal"] == "DEGRADED")
    case("degraded: fallback=True", r["fallback"] is True)
    case("degraded: fallback_context özet taşır", r["fallback_context"]["summary"] == "summary-ref-1")
    case("degraded: whisper kanalı kullanıldı", "whisper" in r["channels"])
    case("degraded: ihlal yok (fail-safe geçerli)", all(v == 0 for v in r["violations"].values()))
    case("degraded: kapı geçer", _gate_eval(r, G)[0] is True)

    # 3) partial auth — auth_level taşınır (re-verify gerekmez ama eksik bilinir)
    r = build(ctx(session={"summary": "s", "intent": "payment",
                           "collected_fields": [{"name": "amount", "sensitive": False, "value_token": "tok-amt"}],
                           "auth": {"level": "partial", "methods": ["customer_number"], "step_up": "pending"}}), spec)
    case("partial: auth_level=partial taşınır", r["auth_level"] == "partial")
    case("partial: ihlal yok", all(v == 0 for v in r["violations"].values()))

    # 4) inject drop_component → missing_component (P2 ihlali)
    r = build(ctx(), spec, inject=["drop_component"])
    case("inject-drop-component: missing_component>0", r["violations"]["missing_component"] > 0)

    # 5) inject drop_collected_field → missing_collected_field (P3 ihlali)
    r = build(ctx(), spec, inject=["drop_collected_field"])
    case("inject-drop-field: missing_collected_field>0", r["violations"]["missing_collected_field"] > 0)
    case("inject-drop-field: pakette 1 alan eksik", r["collected_field_count"] == 1)

    # 6) inject leak_auth_secret → auth_secret_leak (P4 ihlali)
    r = build(ctx(), spec, inject=["leak_auth_secret"])
    case("inject-leak-auth: auth_secret_leak>0", r["violations"]["auth_secret_leak"] > 0)
    case("inject-leak-auth: auth_status'ta otp_code var (yanlış)", "otp_code" in r["package"]["auth_status"])

    # 7) inject unmasked_sensitive → unmasked_sensitive (P5 ihlali)
    r = build(ctx(), spec, inject=["unmasked_sensitive"])
    case("inject-unmasked: unmasked_sensitive>0", r["violations"]["unmasked_sensitive"] > 0)
    case("inject-unmasked: masked_count=0 (maskelenmedi)", r["masked_count"] == 0)

    # 8) inject mis_delivery → mis_delivery (P6 ihlali)
    r = build(ctx(), spec, inject=["mis_delivery"])
    case("inject-mis-delivery: mis_delivery>0", r["violations"]["mis_delivery"] > 0)
    case("inject-mis-delivery: deliver_to != q-billing-tr", r["delivered_to"] != "q-billing-tr")

    # 9) inject cross_tenant → cross_tenant (P7 ihlali)
    r = build(ctx(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 10) inject no_audit → missing_audit (P10 ihlali)
    r = build(ctx(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 11) determinizm: aynı girdi → aynı sonuç
    s = ctx()
    r1 = build(s, spec)
    r2 = build(s, spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 12) kapı entegrasyonu: happy geçer, leak eler
    rp = build(ctx(), spec)
    rf = build(ctx(), spec, inject=["leak_auth_secret"])
    case("kapı: happy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: auth-leak eler", _gate_eval(rf, G)[0] is False)

    # 13) sızıntı tarayıcı: yapısal kimlik temiz, ham PII alanı yakalanır
    case("leak: q-billing-tr temiz", scan_leaks('{"queue": "q-billing-tr"}') == [])
    case("leak: ****-4321 maskeli token temiz", scan_leaks('{"masked_value": "****-4321"}') == [])
    case("leak: otp_code_value alanı yakalanır", len(scan_leaks('{"otp_code_value": "123456"}')) > 0)
    case("leak: ham uzun numara yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    # 14) evidence — bileşen listesi + redaction + hedef kuyruk taşır (P9)
    r = build(ctx(), spec)
    case("evidence: components_delivered dört bileşen",
         set(r["evidence"]["components_delivered"]) == set(COMPONENTS))
    case("evidence: redactions account_number taşır", "account_number" in r["evidence"]["redactions"])
    case("evidence: target_queue=q-billing-tr", r["evidence"]["target_queue"] == "q-billing-tr")
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 15) collected_fields boş olabilir (genuine no-field) → missing_component değil
    r = build(ctx(session={"summary": "s", "intent": "general", "collected_fields": [],
                           "auth": {"level": "none", "methods": [], "step_up": "none"}}), spec)
    case("empty-fields: collected_fields boş ihlal değil", r["violations"]["missing_component"] == 0)
    case("empty-fields: auth_level=none taşınır", r["auth_level"] == "none")

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "context-package (WBS 9.6 — FR-HND-004/FR-HND-005 bağlam paketi + screen-pop)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "package_components": COMPONENTS,
        "auth_levels": AUTH_LEVELS,
        "context_fields": ["name", "tenant_id", "correlation_id", "call_id",
                           "target{department,skill_group,queue,deliver_to,match_quality} (9.5'ten)",
                           "session{summary,intent,collected_fields[],auth{level,methods,step_up}}",
                           "delivery_channels[]", "screen_pop_available",
                           "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "package_fields": ["terminal", "delivered_to", "channels", "components", "collected_field_count",
                           "masked_count", "auth_level", "fallback", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-HND-004/FR-HND-005, FR-AUTH-005/003, FR-TEN-002, SR-HND-004/SR-HND-005, TC-HND-004/TC-HND-005, SAD §7.3, BRD §9.12, ADR-001/002",
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
            print("kullanım: context_package_probe.py run <sample.json|dizin>")
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
