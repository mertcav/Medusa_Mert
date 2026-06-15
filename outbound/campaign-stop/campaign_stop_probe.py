#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.1.7 — Kampanya durdurma düğmesi referans probe.

10. workstream'in (Outbound) Kampanya Yönetimi alt-bloğunun DURDURMA KONTROLÜ modülü ve F2-Must
outbound çekirdeği. FR-OUT-010 ('Kampanya durdurma düğmesi bulunmalıdır') + SR-OUT-010 (yöntem D —
'Kampanya durdurma düğmesi çağrıları derhal durdurur'; kabul: 'Durdurma sonrası yeni çağrı başlatılmaz')
KAMPANYA KONTROL DURUM MAKİNESİNİ + DIALER ADMISSION KAPISINI sahiplenir. DB.md campaign.status CHECK
IN ('draft','running','paused','stopped','completed') yaşam döngüsünün ve API §A-10 'POST
/campaigns/{id}:stop' kontrol yüzeyinin arkasıdır. Modül bir DETERMİNİSTİK KAMPANYA KONTROL MOTORUdur:

  (current_status) ──command(yetkili+geçerli)──► APPLIED (durum geçti + dialer kapısı ayarlandı, C4)
                   ├─(idempotent tekrar)───────► NOOP    (zaten hedef durumda, yan-etkisiz, C6)
                   └─(yetkisiz/geçersiz/cross)─► DENIED  (durum değişmez — doğru reddetme, C2/C3/C7)

ÇEKİRDEK INVARIANT (SR-OUT-010): stop/pause sonrası dialer admission kapısı DERHAL KAPANIR ve yeni
çağrı başlatılmaz (C4 new_call_after_stop=0); kontrol yalnız campaign:manage yetkisiyle (C2); yalnız
geçerli geçiş (C3, stop TERMİNAL / pause RESUMABLE); in-flight çağrılar graceful DRAIN (C5 SAD §6
never-drop); aynı idempotency_key → yan-etkisiz NOOP (C6); tenant izolasyonu (C7); her sonuç kanıt (C9)
+ audit (C10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): dialer ÇEVİRME/zamanlama → 10.1.x dialer çekirdeği (kapıyı
AYARLAR, çevirmez); kampanya OLUŞTURMA → 10.1.1; CRM liste → 10.1.2; max deneme → 10.1.3; disposition →
10.1.5; script versiyon → 10.1.6; A/B → 10.1.8; kapasite rate-limit → FR-RES-014/FR-OUT-007; consent
ön-kontrol → 10.2/§19.1; audit store → 7.1.6/12.1.8; panel UI render → L2 A-10.

Kullanım:
  campaign_stop_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  campaign_stop_probe.py run <sample>       Kontrol motoru: senaryo(lar)ı çalıştır → kapı (C1–C12)
  campaign_stop_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  campaign_stop_probe.py schema             Durum/komut/sonuç sözleşmesini yazdır

Determinizm: sanal zaman + yapısal kimlikler; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (müşteri adı/telefon/hesap no) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "campaign-stop-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "campaign-stop-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATUSES = ["draft", "running", "paused", "stopped", "completed"]
COMMANDS = ["start", "pause", "resume", "stop", "complete"]
HALT_COMMANDS = {"pause", "stop", "complete"}
OPEN_COMMANDS = {"start", "resume"}
OUTCOMES = ["APPLIED", "NOOP", "DENIED"]
TERMINAL = {"APPLIED", "NOOP", "DENIED"}
AUTH_ROLES = ["operations_manager", "tenant_admin", "tenant_owner"]
PERMISSION = "campaign:manage"
INVARIANT_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]

# İzinli geçişler (DB.md campaign.status CHECK ile uyumlu)
APPLY = {
    ("draft", "start"): "running",
    ("running", "pause"): "paused",
    ("paused", "resume"): "running",
    ("running", "stop"): "stopped",
    ("paused", "stop"): "stopped",
    ("running", "complete"): "completed",
}
NOOP = {
    ("stopped", "stop"): "stopped",
    ("paused", "pause"): "paused",
    ("running", "resume"): "running",
    ("running", "start"): "running",
}

INJECTIONS = {"new_call_after_stop", "hard_drop_inflight", "skip_auth",
              "invalid_transition", "not_idempotent", "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "unauthorized", "invalid_transition", "new_call_after_stop", "hard_drop_inflight",
    "not_idempotent", "cross_tenant", "missing_evidence", "missing_audit",
    "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (C12; 9.x deseniyle) — müşteri adı/telefon/hesap no/OTP yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{9,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # ham müşteri içeriği / sır DEĞERİ alanı (yalnız yapısal kimlik taşımalı)
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone_value|account_number_value|transcript_text|otp_code_value|password_value|raw_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|camp-|t-|idem-|corr-|call-|res-|q-|dept-|prefix|masked|last4)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (9.x deseni)."""
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
# Kontrol motoru — CampaignControlRequest'i yetki + geçiş + admission kapısına çevirir.
# ════════════════════════════════════════════════════════════════════════════
def _config_from(sample, spec):
    """Config = ana campaign-stop-policies.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("authorized_roles", "halt_commands", "open_commands", "halt_statuses",
              "open_statuses", "terminal_statuses"):
        if k in ov:
            cfg[k] = ov[k]
    return cfg


def build(sample, spec, inject=None, cfg=None):
    """Tek kontrol senaryosunu yürüt → ControlOutcome + ihlal sayaçları.

    Motor DOĞRU davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal
    sayacını artırır (9.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config_from(sample, spec)
    tenant = sample.get("tenant_id")
    campaign = sample.get("campaign_id")
    command = sample.get("command")
    cur = sample.get("current_status")
    actor = sample.get("actor_role")
    inflight = int(sample.get("in_flight_calls", 0) or 0)
    idem = sample.get("idempotency_key")

    authorized_roles = set(cfg.get("authorized_roles", AUTH_ROLES))
    halt_commands = set(cfg.get("halt_commands", HALT_COMMANDS))
    open_commands = set(cfg.get("open_commands", OPEN_COMMANDS))

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── C7: tenant izolasyonu ────────────────────────────────────────────────────────
    resource = "camp-res-" + str(tenant)
    if "cross_tenant" in inject:
        resource = "camp-res-foreigntenant"
        v["cross_tenant"] += 1
    bind_tenant = sample.get("bind_tenant")
    if bind_tenant and bind_tenant != tenant:
        v["cross_tenant"] += 1

    # ── C2: yetki ──────────────────────────────────────────────────────────────────────
    authorized = actor in authorized_roles
    denied = False
    deny_reason = None
    if not authorized:
        if "skip_auth" in inject:
            v["unauthorized"] += 1   # yetkisiz aktör komutu UYGULANDI → C2 ihlali
        else:
            denied = True
            deny_reason = "unauthorized"

    # ── C3: geçiş geçerliliği ──────────────────────────────────────────────────────────
    key = (cur, command)
    is_apply = key in APPLY
    is_noop = key in NOOP
    forced_invalid = "invalid_transition" in inject

    terminal = None
    to_status = cur
    applied = False
    dialer_gate = "unchanged"
    new_admitted = 0
    inflight_disp = "none"

    if denied:
        # yetkisiz → durum değişmez (doğru reddetme)
        terminal = "DENIED"
        to_status = cur
    elif forced_invalid:
        # inject: geçersiz geçişi force-apply et → C3 ihlali
        v["invalid_transition"] += 1
        terminal = "APPLIED"
        applied = True
        to_status = sample.get("forced_to_status", cur)
        # geçersiz force-apply yine de kapı/inflight tarafını çalıştırabilir (degrade)
        if command in halt_commands:
            dialer_gate = "closed"
        elif command in open_commands:
            dialer_gate = "open"
    elif is_noop:
        # idempotent tekrar — durum zaten hedef; yan-etkisiz
        terminal = "NOOP"
        to_status = NOOP[key]
        if command in halt_commands:
            dialer_gate = "closed"   # zaten kapalı (tekrar tetiklenmez)
        elif command in open_commands:
            dialer_gate = "open"
        if "not_idempotent" in inject:
            v["not_idempotent"] += 1   # idempotent tekrar çifte yan-etki üretti → C6 ihlali
    elif is_apply:
        terminal = "APPLIED"
        applied = True
        to_status = APPLY[key]
        # ── C4: dialer admission kapısı ──
        if command in halt_commands:
            dialer_gate = "closed"
            new_admitted = 0
            if "new_call_after_stop" in inject:
                new_admitted = 1
                v["new_call_after_stop"] += 1   # kapı kapalıyken yeni çağrı admit → SR-OUT-010 ihlali
            # ── C5: in-flight graceful drain ──
            if inflight > 0:
                inflight_disp = "drain"
                if "hard_drop_inflight" in inject:
                    inflight_disp = "force_drop"
                    v["hard_drop_inflight"] += 1   # in-flight abruptly düşürüldü → C5 ihlali
            else:
                inflight_disp = "none"
        elif command in open_commands:
            dialer_gate = "open"
            inflight_disp = "none"
        else:
            dialer_gate = "unchanged"
    else:
        # geçersiz geçiş, inject yok → doğru reddetme
        terminal = "DENIED"
        deny_reason = "invalid_transition"
        to_status = cur
        dialer_gate = "unchanged"

    # ── C1: stuck state ──────────────────────────────────────────────────────────────
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (C9) ─────────────────────────────────────────────────────────────────────
    evidence = {
        "command": command,
        "from_status": cur,
        "to_status": to_status,
        "actor_role": actor,
        "authorized": bool(authorized),
        "dialer_gate": dialer_gate,
        "new_calls_admitted_after": new_admitted,
        "inflight_disposition": inflight_disp,
        "inflight_count": inflight,
        "idempotency_key": idem,
        "resource": resource,
        "terminal": terminal,
        "deny_reason": deny_reason,
    }
    if (not command) or (not cur) or (not actor) or (terminal is None):
        v["missing_evidence"] += 1

    # ── Audit (C10) ─────────────────────────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "command": command,
            "from_status": cur,
            "to_status": to_status,
            "actor_role": actor,
            "result": terminal,
            "deny_reason": deny_reason,
            "dialer_gate": dialer_gate,
            "idempotency_key": idem,
            "resource": resource,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
            "campaign_id": campaign,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "applied": applied,
        "command": command,
        "from_status": cur,
        "to_status": to_status,
        "dialer_gate": dialer_gate,
        "new_calls_admitted_after": new_admitted,
        "inflight_disposition": inflight_disp,
        "inflight_count": inflight,
        "authorized": bool(authorized),
        "deny_reason": deny_reason,
        "idempotency_key": idem,
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
        "invalid_transition": "max_invalid_transition",
        "new_call_after_stop": "max_new_call_after_stop",
        "hard_drop_inflight": "max_hard_drop_inflight",
        "not_idempotent": "max_not_idempotent",
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
        fails.append("kontrol/audit kaydı üretilmedi (C10)")
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
        for key in ("terminal", "to_status", "dialer_gate", "new_calls_admitted_after",
                    "inflight_disposition", "applied"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s %s→%s gate=%s new_after=%d inflight=%s"
              % (res["terminal"], res["from_status"], res["to_status"], res["dialer_gate"],
                 res["new_calls_admitted_after"], res["inflight_disposition"]))
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
    for f in ("wbs", "phase", "priority", "trace", "placement", "lifecycle", "commands",
              "transitions", "dialer_gate", "inflight", "authorization", "outcomes",
              "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=10.1.7", spec.get("wbs") == "10.1.7")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-OUT-010 izlenir (kampanya durdurma düğmesi)", "FR-OUT-010" in tr.get("fr", []))
    chk("FR-IAM-011 izlenir (campaign:manage RBAC)", "FR-IAM-011" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-REC-004 izlenir (PII metrikte yok)", "FR-REC-004" in tr.get("fr", []))
    chk("FR-RES-014 izlenir (admission/backpressure)", "FR-RES-014" in tr.get("fr", []))
    chk("SR-OUT-010 izlenir", "SR-OUT-010" in tr.get("srs", []))
    chk("TC-OUT-010 izlenir", "TC-OUT-010" in tr.get("rtm", []))
    chk("ADR-001/002/012 izlenir",
        any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", []))
        and any("ADR-012" in a for a in tr.get("adr", [])))
    chk("SAD §15 admission izlenir", any("§15" in s for s in tr.get("sad", [])))
    chk("SAD §6 never-drop izlenir", any("§6" in s for s in tr.get("sad", [])))

    # 3) Yaşam döngüsü (DB.md status CHECK)
    lc = spec["lifecycle"]
    chk("statuses = DB.md campaign.status CHECK", lc.get("statuses") == STATUSES)
    chk("terminal_statuses = {stopped,completed}", set(lc.get("terminal_statuses", [])) == {"stopped", "completed"})
    chk("resumable_statuses = {paused}", set(lc.get("resumable_statuses", [])) == {"paused"})
    chk("halt_statuses içeriyor stopped+paused", {"stopped", "paused"} <= set(lc.get("halt_statuses", [])))

    # 4) Komutlar + geçiş grafiği
    cm = spec["commands"]
    chk("komutlar start/pause/resume/stop/complete", cm.get("list") == COMMANDS)
    chk("stop_command=stop", cm.get("stop_command") == "stop")
    chk("halt_commands = {pause,stop,complete}", set(cm.get("halt_commands", [])) == HALT_COMMANDS)
    ap = {(e["from"], e["command"]): e["to"] for e in spec["transitions"]["apply"]}
    no = {(e["from"], e["command"]): e["to"] for e in spec["transitions"]["noop"]}
    chk("running|stop → stopped (durdurma)", ap.get(("running", "stop")) == "stopped")
    chk("running|pause → paused", ap.get(("running", "pause")) == "paused")
    chk("paused|resume → running (resumable)", ap.get(("paused", "resume")) == "running")
    chk("stopped|resume YOK (stop terminal)", ("stopped", "resume") not in ap)
    chk("stopped|stop NOOP (idempotent)", no.get(("stopped", "stop")) == "stopped")
    chk("on_applied EMIT tanımlı", "EMIT" in spec["transitions"].get("on_applied", ""))
    chk("on_denied durum DEĞİŞMEZ", "DEĞİŞMEZ" in spec["transitions"].get("on_denied", ""))

    # 5) Dialer admission kapısı (SR-OUT-010 çekirdek)
    dg = spec["dialer_gate"]
    chk("kapı closed_on stop/pause/complete", set(dg.get("closed_on", [])) == HALT_COMMANDS)
    chk("kapı open_on start/resume", set(dg.get("open_on", [])) == OPEN_COMMANDS)
    chk("durdurma sonrası yeni çağrı=0 (SR-OUT-010)", dg.get("new_calls_admitted_after_halt") == 0)

    # 6) In-flight + yetki
    inf = spec["inflight"]
    chk("in-flight default=drain (SAD §6)", inf.get("default_disposition") == "drain")
    chk("in-flight force_drop yasak", inf.get("forbidden_disposition") == "force_drop")
    az = spec["authorization"]
    chk("yetki permission=campaign:manage", az.get("permission") == PERMISSION)
    chk("yetkili roller operations_manager dahil", "operations_manager" in az.get("authorized_roles", []))
    chk("yetki kararı backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_unauthorized", "max_invalid_transition", "max_new_call_after_stop",
               "max_hard_drop_inflight", "max_not_idempotent", "max_cross_tenant",
               "max_missing_evidence", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("campaign_control_total metrik", "campaign_control_total" in obs.get("metrics", []))
    chk("campaign_new_call_after_stop_total metrik (SR-OUT-010 alarm)",
        "campaign_new_call_after_stop_total" in obs.get("metrics", []))
    chk("campaign_control_denied_total metrik (yetki erken-uyarı)",
        "campaign_control_denied_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("campaign_id YÜKSEK kard (label değil)", "campaign_id" in hi and "campaign_id" not in lo)
    chk("call_id/correlation_id YÜKSEK kard", "call_id" in hi and "correlation_id" in hi)
    chk("command/result/status DÜŞÜK kard (label uygun)",
        "command" in lo and "result" in lo and "status" in lo)

    # 9) İnvariant'lar C1–C12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar C1–C12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/campaign-stop-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config statuses = DB.md", cfg.get("statuses") == STATUSES)
        chk("config commands tam", cfg.get("commands") == COMMANDS)
        caz = cfg.get("authorization", {})
        chk("config permission=campaign:manage", caz.get("permission") == PERMISSION)
        chk("config yetkili roller operations_manager dahil",
            "operations_manager" in caz.get("authorized_roles", []))
        cdg = cfg.get("dialer_gate", {})
        chk("config kapı durdurma sonrası yeni çağrı=0",
            cdg.get("new_calls_admitted_after_halt") == 0)
        cinf = cfg.get("inflight", {})
        chk("config in-flight default=drain", cinf.get("default_disposition") == "drain")
        ctr = cfg.get("transitions", {})
        chk("config running|stop → stopped", ctr.get("apply", {}).get("running|stop") == "stopped")
        chk("config stopped|stop NOOP", ctr.get("noop", {}).get("stopped|stop") == "stopped")

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
    chk("hiç müşteri-PII/telefon/hesap-no/OTP/sır sızıntısı yok (C12)", total_leaks == 0)

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
            "tenant_id": "t-acme", "correlation_id": "corr-1", "campaign_id": "camp-1",
            "actor_role": "operations_manager",
            "command": "stop",
            "current_status": "running",
            "in_flight_calls": 3,
            "idempotency_key": "idem-1",
        }
        d.update(kw)
        return d

    # 1) happy stop — running+stop → APPLIED stopped, kapı kapalı, drain (FR-OUT-010 çekirdek)
    r = build(req(), spec)
    case("happy-stop: APPLIED", r["terminal"] == "APPLIED")
    case("happy-stop: to_status=stopped", r["to_status"] == "stopped")
    case("happy-stop: kapı kapalı", r["dialer_gate"] == "closed")
    case("happy-stop: yeni çağrı=0 (SR-OUT-010)", r["new_calls_admitted_after"] == 0)
    case("happy-stop: in-flight drain", r["inflight_disposition"] == "drain")
    case("happy-stop: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy-stop: audit var (C10)", r["audit"] is not None and r["audit"]["result"] == "APPLIED")
    case("happy-stop: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) happy pause — running+pause → APPLIED paused, kapı kapalı (resumable)
    r = build(req(command="pause"), spec)
    case("happy-pause: APPLIED paused", r["terminal"] == "APPLIED" and r["to_status"] == "paused")
    case("happy-pause: kapı kapalı", r["dialer_gate"] == "closed")
    case("happy-pause: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 3) resume — paused+resume → APPLIED running, kapı açık
    r = build(req(command="resume", current_status="paused", in_flight_calls=0), spec)
    case("resume: APPLIED running", r["terminal"] == "APPLIED" and r["to_status"] == "running")
    case("resume: kapı açık", r["dialer_gate"] == "open")
    case("resume: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 4) idempotent stop — stopped+stop → NOOP, yan-etkisiz
    r = build(req(current_status="stopped", in_flight_calls=0), spec)
    case("idempotent-stop: NOOP", r["terminal"] == "NOOP")
    case("idempotent-stop: kapı kapalı", r["dialer_gate"] == "closed")
    case("idempotent-stop: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("idempotent-stop: kapı geçer", _gate_eval(r, G)[0] is True)

    # 5) yetkisiz aktör — DENIED, durum değişmez (doğru reddetme)
    r = build(req(actor_role="human_agent"), spec)
    case("unauthorized: DENIED", r["terminal"] == "DENIED")
    case("unauthorized: durum değişmez", r["to_status"] == "running")
    case("unauthorized: deny_reason=unauthorized", r["deny_reason"] == "unauthorized")
    case("unauthorized: ihlal yok (doğru reddetme)", all(x == 0 for x in r["violations"].values()))
    case("unauthorized: kapı geçer", _gate_eval(r, G)[0] is True)

    # 6) geçersiz geçiş (stop terminal) — stopped+resume → DENIED (doğru reddetme)
    r = build(req(command="resume", current_status="stopped", in_flight_calls=0), spec)
    case("invalid-transition: DENIED", r["terminal"] == "DENIED")
    case("invalid-transition: deny_reason=invalid_transition", r["deny_reason"] == "invalid_transition")
    case("invalid-transition: durum değişmez (stop terminal)", r["to_status"] == "stopped")
    case("invalid-transition: ihlal yok (doğru reddetme)", all(x == 0 for x in r["violations"].values()))

    # 7) complete — running+complete → APPLIED completed, kapı kapalı
    r = build(req(command="complete"), spec)
    case("complete: APPLIED completed", r["terminal"] == "APPLIED" and r["to_status"] == "completed")
    case("complete: kapı kapalı", r["dialer_gate"] == "closed")

    # 8) inject new_call_after_stop → C4 ihlali (SR-OUT-010 çekirdek breach)
    r = build(req(), spec, inject=["new_call_after_stop"])
    case("inject-new-call: new_call_after_stop>0", r["violations"]["new_call_after_stop"] > 0)
    case("inject-new-call: yeni çağrı=1", r["new_calls_admitted_after"] == 1)
    case("inject-new-call: kapı eler", _gate_eval(r, G)[0] is False)

    # 9) inject hard_drop_inflight → C5 ihlali
    r = build(req(in_flight_calls=4), spec, inject=["hard_drop_inflight"])
    case("inject-hard-drop: hard_drop_inflight>0", r["violations"]["hard_drop_inflight"] > 0)
    case("inject-hard-drop: force_drop", r["inflight_disposition"] == "force_drop")

    # 10) inject skip_auth → C2 ihlali (yetkisiz uygulandı)
    r = build(req(actor_role="human_agent"), spec, inject=["skip_auth"])
    case("inject-skip-auth: unauthorized>0", r["violations"]["unauthorized"] > 0)

    # 11) inject invalid_transition → C3 ihlali (geçersiz force-apply)
    r = build(req(command="resume", current_status="stopped"), spec, inject=["invalid_transition"])
    case("inject-invalid-transition: invalid_transition>0", r["violations"]["invalid_transition"] > 0)

    # 12) inject not_idempotent → C6 ihlali (çifte yan-etki)
    r = build(req(current_status="stopped", in_flight_calls=0), spec, inject=["not_idempotent"])
    case("inject-not-idempotent: not_idempotent>0", r["violations"]["not_idempotent"] > 0)
    case("inject-not-idempotent: terminal NOOP", r["terminal"] == "NOOP")

    # 13) inject cross_tenant → C7 ihlali
    r = build(req(), spec, inject=["cross_tenant"])
    case("inject-cross-tenant: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 14) inject no_audit → C10 ihlali
    r = build(req(), spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 15) bind_tenant uyuşmazlığı → cross_tenant (inject'siz)
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 16) determinizm: aynı girdi → aynı sonuç
    s = req()
    r1 = build(s, spec)
    r2 = build(s, spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 17) kapı entegrasyonu: happy geçer, new-call-after-stop eler
    rp = build(req(), spec)
    rf = build(req(), spec, inject=["new_call_after_stop"])
    case("kapı: happy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: new-call-after-stop eler", _gate_eval(rf, G)[0] is False)

    # 18) evidence — command + from→to + actor + kapı + idempotency taşır (C9)
    r = build(req(), spec)
    case("evidence: command taşır", r["evidence"]["command"] == "stop")
    case("evidence: from→to taşır", r["evidence"]["from_status"] == "running" and r["evidence"]["to_status"] == "stopped")
    case("evidence: dialer_gate taşır", r["evidence"]["dialer_gate"] == "closed")
    case("evidence: idempotency_key taşır", r["evidence"]["idempotency_key"] == "idem-1")
    case("evidence: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # 19) audit — command + from→to + result + tenant taşır (C10)
    r = build(req(), spec)
    case("audit: command taşır", r["audit"]["command"] == "stop")
    case("audit: result taşır", r["audit"]["result"] == "APPLIED")
    case("audit: tenant taşır", r["audit"]["tenant_id"] == "t-acme")

    # 20) sızıntı tarayıcı: yapısal kimlik temiz, ham PII/telefon yakalanır
    case("leak: camp-001 kimlik temiz", scan_leaks('{"campaign_id": "camp-001"}') == [])
    case("leak: idem-1 kimlik temiz", scan_leaks('{"idempotency_key": "idem-1"}') == [])
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
        "module": "campaign-stop (WBS 10.1.7 — FR-OUT-010 kampanya durdurma düğmesi)",
        "statuses": STATUSES,
        "commands": COMMANDS,
        "halt_commands": sorted(HALT_COMMANDS),
        "open_commands": sorted(OPEN_COMMANDS),
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "authorized_roles": AUTH_ROLES,
        "permission": PERMISSION,
        "transitions_apply": {"%s|%s" % k: v for k, v in APPLY.items()},
        "transitions_noop": {"%s|%s" % k: v for k, v in NOOP.items()},
        "request_fields": ["name", "tenant_id", "correlation_id", "campaign_id", "actor_role",
                           "command[start|pause|resume|stop|complete]", "current_status",
                           "in_flight_calls", "idempotency_key", "bind_tenant", "forced_to_status",
                           "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "outcome_fields": ["terminal", "applied", "command", "from_status", "to_status", "dialer_gate",
                           "new_calls_admitted_after", "inflight_disposition", "authorized",
                           "deny_reason", "resource", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-OUT-010, SR-OUT-010, TC-OUT-010, FR-IAM-011/006, FR-TEN-002, FR-REC-004, "
                 "DB.md campaign, API §A-10, SAD §15, SAD §6, ADR-001/002/012",
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
            print("kullanım: campaign_stop_probe.py run <sample.json|dizin>")
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
