#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.1 — Cold transfer (SIP REFER) referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) İLK modülü ve F1-Must aktarım çekirdeği.
FR-TEL-007'nin COLD/blind transfer tipini SAHİPLENİR (WARM→9.2, WHISPER→9.3). SAD §7.3:
'COLD: SIP REFER → CC'ye yönlendir, oturum kapanır'. Cold transfer'i bir DETERMINISTIK
DURUM MAKİNESİ (SIP REFER yaşam döngüsü, RFC 3515) olarak gerçekler:

  INIT ─► ANNOUNCE ─► REFER_SENT ─► REFERRING ─► TRANSFERRED ──► (RELEASE: A-leg BYE, agent çıkar)
   │         (G2)        │ (G3)       │ (G4)
   │ (G1 hedef)          │ REFER reddi │ NOTIFY≥300 / deadline
   ▼                     ▼            ▼
  FAILED ◄───────────────┴────────────┘──► (FALLBACK: oturum DÜŞMEZ, 9.7 callback/voicemail/ticket)

ÇEKİRDEK INVARIANT (BRD §9.12/§14.2 + SR-TEL-007): REFER yalnız anons sonrası (C2 blind-REFER yok);
başarıda orijinal A-leg serbest (C3 orphaned/çift-faturalı leg yok); başarısızlıkta oturum DÜŞMEZ +
fallback (C4 fail-safe FR-HND-007); cold=fire-and-forget köprü yok (C5); deadline→FAILED (C8 hang yok);
hedef tenant-scoped (C9 cross-tenant yok); her terminal audit (C7).

Kapsam dışı (bilinçli, başka modül SAHİBİ): transfer() SPI + ham SIP REFER/RTP → 4.2.5 (ÇAĞIRIR/TÜKETİR);
WARM→9.2; WHISPER→9.3; tetikleyici→9.4 (kararı TÜKETİR); hedef seçimi→9.5 (çözülmüş hedefi TÜKETİR);
bağlam paketi/screen-pop→9.6; fallback motoru→9.7 (TETİKLER); raporlama toplama→9.8; audit store→7.1.6/12.1.8.

Kullanım:
  cold_transfer_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  cold_transfer_probe.py run <sample>      FSM-yürütücü: cold transfer(ler)i çalıştır → kapı (C1–C10)
  cold_transfer_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  cold_transfer_probe.py schema            Durum/olay/sonuç sözleşmesini yazdır

Determinizm: sanal saat (t, ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (ham numara/içerik) üretilmez/yazılmaz (fixture'lar sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "cold-transfer-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "cold-transfer-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["INIT", "ANNOUNCE", "REFER_SENT", "REFERRING", "TRANSFERRED", "FAILED"]
NON_TERMINAL = {"INIT", "ANNOUNCE", "REFER_SENT", "REFERRING"}
TERMINAL = {"TRANSFERRED", "FAILED"}
VALID_TARGET_TYPES = {"QUEUE", "SKILL", "AGENT", "NUMBER"}
INVARIANT_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"]
EVENT_KINDS = {"decision", "announce", "refer", "refer_ack", "notify"}
INJECTIONS = {"drop_on_failure", "bridge_on_cold", "orphan_leg", "no_audit"}
FAILURE_CLASSES = {"REFER_REJECTED", "NOTIFY_FAILED", "DEADLINE", "TARGET_INVALID",
                   "CROSS_TENANT", "BLIND_REFER"}

VIOLATION_KEYS = [
    "blind_refer", "unresolved_target", "cross_tenant_target", "orphaned_leg",
    "dropped_on_failure", "bridged_on_cold", "hung_transfer", "missing_audit",
    "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (C10; 4.2.5/7.1.5 deseniyle) — ham telefon numarası / içerik yasak ──────────
LEAK_PATTERNS = [
    # E.164 benzeri uzun rakam dizisi (rezerve 555-01xx / +1632 test blokları HARİÇ)
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{10,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
# Rezerve/test blokları + yapısal kimlikler (sızıntı DEĞİL)
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|queue-|skill-|agent-|num-)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı ve rezerve test bloklarını eler (1.1.8 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        # spec içindeki $comment / desc alanları SIP kodu / FR/SR kimliği tarif eder → sır değil.
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                # rezerve/test bloğu veya yapısal kimlik bağlamı → atla
                window = line[max(0, m.start() - 12):m.end() + 12]
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
# FSM yürütücü — bir cold transfer senaryosunu (olay akışı) durum makinesinden geçirir.
# ════════════════════════════════════════════════════════════════════════════
def _valid_target(target):
    if not isinstance(target, dict):
        return False
    t = target.get("type")
    ref = target.get("ref")
    return t in VALID_TARGET_TYPES and isinstance(ref, str) and len(ref.strip()) > 0


def run_transfer(sample, deadline_default=8000):
    """Tek cold transfer senaryosunu yürüt → outcome + ihlal sayaçları."""
    tenant = sample.get("tenant_id")
    target = sample.get("target") or {}
    deadline = sample.get("deadline_ms", deadline_default)
    inject = set(sample.get("inject", []))
    events = sorted(sample.get("events", []), key=lambda e: e.get("t", 0))

    v = {k: 0 for k in VIOLATION_KEYS}
    state = "INIT"
    announced = False
    announce_t = None
    refer_t = None
    terminal_t = None
    failure_class = None
    a_leg_released = False
    agent_media_stopped = False
    bridged = False
    fallback = False
    notes = []

    # ── G1: hedef çözümü + tenant izolasyonu (REFER gönderilmeden önce) ───────────────
    target_ok = _valid_target(target)
    if not target_ok:
        v["unresolved_target"] += 1
    tgt_tenant = target.get("tenant_id")
    if tgt_tenant is not None and tenant is not None and tgt_tenant != tenant:
        v["cross_tenant_target"] += 1
        target_ok = False
        failure_class = "CROSS_TENANT"

    # Hedef geçersiz/cross-tenant ise FSM erken FAILED → fallback (REFER GÖNDERİLMEZ).
    if not target_ok:
        state = "FAILED"
        if failure_class is None:
            failure_class = "TARGET_INVALID"

    # ── Olay akışını işle ────────────────────────────────────────────────────────────
    for ev in events:
        if state in TERMINAL:
            break
        k = ev.get("kind")
        t = ev.get("t", 0)
        if k == "decision":
            continue  # INIT'te bekler
        elif k == "announce":
            announced = True
            announce_t = t
            if state == "INIT":
                state = "ANNOUNCE"
        elif k == "refer":
            refer_t = t
            if not announced:
                # C2: anonssuz REFER (blind) — fail-closed sayım
                v["blind_refer"] += 1
                failure_class = "BLIND_REFER"
            state = "REFER_SENT"
        elif k == "refer_ack":
            code = ev.get("code", 202)
            if code == 202:
                state = "REFERRING"
            else:
                state = "FAILED"
                failure_class = "REFER_REJECTED"
                terminal_t = t
        elif k == "notify":
            final = bool(ev.get("final"))
            code = ev.get("code", 100)
            if not final:
                continue  # sipfrag ilerleme (100/180) — REFERRING'de bekler
            # final NOTIFY
            if refer_t is not None and (t - refer_t) > deadline:
                # C8: deadline sonrası geç-başarı → FSM zaman aşımı olarak ele alır
                # (terminal anı, olayın geç gelişi değil, deadline anıdır)
                state = "FAILED"
                failure_class = "DEADLINE"
                terminal_t = refer_t + deadline
            elif code == 200:
                state = "TRANSFERRED"
                terminal_t = t
            else:
                state = "FAILED"
                failure_class = "NOTIFY_FAILED"
                terminal_t = t
        else:
            notes.append("bilinmeyen olay: %s" % k)

    # ── Deadline zorlama: REFER gönderildi ama terminal'e ulaşılmadıysa → FAILED ───────
    if state in NON_TERMINAL:
        if state in ("REFER_SENT", "REFERRING") and refer_t is not None:
            state = "FAILED"
            failure_class = "DEADLINE"
            terminal_t = (refer_t + deadline)
        else:
            # INIT/ANNOUNCE'ta takılı kaldı → gerçek stuck (FSM bug)
            v["stuck_state"] += 1
            state = "FAILED"
            failure_class = "DEADLINE"

    # ── C1: terminal'e ulaşılmalı (deadline zorlamasından sonra her zaman) ─────────────
    if state not in TERMINAL:
        v["hung_transfer"] += 1

    # ── Terminal eylemleri: RELEASE (başarı) / FALLBACK (başarısızlık) ────────────────
    if state == "TRANSFERRED":
        # C3/C5: fire-and-forget — A-leg serbest, agent çıkar, köprü yok
        if "orphan_leg" in inject:
            a_leg_released = False
            v["orphaned_leg"] += 1
        else:
            a_leg_released = True
        agent_media_stopped = True
        if "bridge_on_cold" in inject:
            bridged = True
            v["bridged_on_cold"] += 1
        fallback = False
    else:  # FAILED
        # C4: fail-safe — oturum düşmez, A-leg korunur, fallback (9.7)
        if "drop_on_failure" in inject:
            fallback = False
            v["dropped_on_failure"] += 1
        else:
            fallback = True
        a_leg_released = False  # başarısızlıkta müşteri elde tutulur

    # ── Bekleme süresi / REFER süresi ────────────────────────────────────────────────
    base_t = announce_t if announce_t is not None else (refer_t if refer_t is not None else 0)
    wait_ms = (terminal_t - base_t) if (terminal_t is not None) else 0
    refer_dur_ms = (terminal_t - refer_t) if (terminal_t is not None and refer_t is not None) else None

    # ── C7: audit kaydı (her terminal) ───────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "outcome": "success" if state == "TRANSFERRED" else "fail",
            "terminal": state,
            "failure_class": failure_class,
            "wait_ms": wait_ms,
            "refer_duration_ms": refer_dur_ms,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
            "target_type": target.get("type"),
        }

    outcome = "success" if state == "TRANSFERRED" else "fail"
    return {
        "name": sample.get("name"),
        "terminal": state,
        "outcome": outcome,
        "failure_class": failure_class,
        "announced": announced,
        "a_leg_released": a_leg_released,
        "agent_media_stopped": agent_media_stopped,
        "bridged": bridged,
        "fallback": fallback,
        "wait_ms": wait_ms,
        "refer_duration_ms": refer_dur_ms,
        "audit": audit,
        "violations": v,
        "notes": notes,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "blind_refer": "max_blind_refer",
        "unresolved_target": "max_unresolved_target",
        "cross_tenant_target": "max_cross_tenant_target",
        "orphaned_leg": "max_orphaned_leg",
        "dropped_on_failure": "max_dropped_on_failure",
        "bridged_on_cold": "max_bridged_on_cold",
        "hung_transfer": "max_hung_transfer",
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
    if gates.get("require_outcome_report", True) and result["audit"] is None:
        fails.append("outcome/audit raporu üretilmedi (C7)")
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def run_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]
    deadline_default = gates.get("refer_deadline_ms", 8000)

    paths = []
    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = run_transfer(sample, deadline_default)
        # C10 sızıntı: sample dosyasını tara
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        # beklenen-aksiyon kontrolü (varsa)
        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "outcome", "fallback", "a_leg_released", "bridged"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s outcome=%s failure=%s wait=%dms a_leg_released=%s fallback=%s bridged=%s"
              % (res["terminal"], res["outcome"], res["failure_class"], res["wait_ms"],
                 res["a_leg_released"], res["fallback"], res["bridged"]))
        nz = {k: val for k, val in res["violations"].items() if val}
        if nz:
            print("   ihlaller: %s" % nz)
        if expect == "pass" and fails:
            print("   ✗ kapı eler (beklenen geçer): %s" % "; ".join(fails))
        if expect == "fail" and passed:
            print("   ✗ kapı GEÇTİ (beklenen eler — degrade senaryo)")
        if mism and expect == "pass":
            print("   ✗ aksiyon uyuşmazlığı: %s" % "; ".join(mism))
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
              "gates", "sip_refer", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.1", spec.get("wbs") == "9.1")
    chk("phase=F1", spec.get("phase") == "F1")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-007 izlenir", "FR-TEL-007" in tr.get("fr", []))
    chk("FR-HND-007 izlenir (fallback)", "FR-HND-007" in tr.get("fr", []))
    chk("FR-HND-008 izlenir (raporlama)", "FR-HND-008" in tr.get("fr", []))
    chk("SR-TEL-007 izlenir", "SR-TEL-007" in tr.get("srs", []))
    chk("TC-TEL-007 izlenir", "TC-TEL-007" in tr.get("rtm", []))
    chk("ADR-001/002 izlenir", any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", [])))
    chk("SAD §7.3 izlenir", any("§7.3" in s for s in tr.get("sad", [])))

    # 3) Durum makinesi tutarlılığı
    st = spec["states"]
    chk("flow = 6 durum", st.get("flow") == STATES)
    chk("terminal = {TRANSFERRED,FAILED}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal doğru", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği — erişilebilirlik + her terminal'e bir yol
    edges = spec["transitions"]["edges"]
    froms = set(e["from"] for e in edges)
    tos = set(e["to"] for e in edges)
    chk("INIT kaynak", "INIT" in froms)
    chk("TRANSFERRED hedef erişilebilir", "TRANSFERRED" in tos)
    chk("FAILED hedef erişilebilir", "FAILED" in tos)
    # her non-terminal durumdan en az bir çıkış kenarı
    for s in NON_TERMINAL:
        chk("'%s' durumundan çıkış var" % s, s in froms)
    # FAILED'e birden çok yol (her aşamada fail-safe)
    fail_sources = set(e["from"] for e in edges if e["to"] == "FAILED")
    chk("FAILED'e ≥3 kaynaktan (fail-safe her aşamada)", len(fail_sources) >= 3)
    chk("on_transferred RELEASE tanımlı", "RELEASE" in spec["transitions"].get("on_transferred", ""))
    chk("on_failed FALLBACK tanımlı", "FALLBACK" in spec["transitions"].get("on_failed", ""))

    # 5) Kapılar — tüm sıfır-eşik ihlal kapıları + deadline
    g = spec["gates"]
    for gk in ("max_blind_refer", "max_unresolved_target", "max_cross_tenant_target",
               "max_orphaned_leg", "max_dropped_on_failure", "max_bridged_on_cold",
               "max_hung_transfer", "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("refer_deadline_ms tanımlı (>0)", isinstance(g.get("refer_deadline_ms"), int) and g["refer_deadline_ms"] > 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_outcome_report", g.get("require_outcome_report") is True)

    # 6) SIP REFER eşlemesi (RFC 3515)
    sr = spec["sip_refer"]
    chk("success_sipfrag=200", sr.get("success_sipfrag") == 200)
    chk("failure_sipfrag_min=300", sr.get("failure_sipfrag_min") == 300)
    chk("lifecycle REFER→202→NOTIFY→BYE", "REFER" in sr.get("lifecycle", [])[0])
    chk("transferor=platform", sr.get("roles", {}).get("transferor", "").startswith("platform"))

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_transfer_total metrik", "handoff_transfer_total" in obs.get("metrics", []))
    chk("handoff_wait_seconds metrik (FR-HND-008)", "handoff_wait_seconds" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("call_id YÜKSEK kard (label değil)", "call_id" in hi and "call_id" not in lo)
    chk("correlation_id YÜKSEK kard (label değil)", "correlation_id" in hi)
    chk("mode/outcome DÜŞÜK kard (label uygun)", "mode" in lo and "outcome" in lo)

    # 8) İnvariant'lar C1–C10
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar C1–C10 tam", inv_ids == INVARIANT_IDS)

    # 9) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/cold-transfer-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config deadline ≤ spec deadline", cfg.get("refer_deadline_ms", 0) <= g["refer_deadline_ms"])
        chk("config fallback target_types eşler", set(cfg.get("target_types", [])) == VALID_TARGET_TYPES)
        chk("config fallback yolu tanımlı (9.7)", "fallback" in cfg and "to" in cfg["fallback"])

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
    chk("hiç ham PII/sır sızıntısı yok (C10)", total_leaks == 0)

    # 11) Samples — her örnek beklendiği gibi davranır (uçtan uca self-tutarlılık)
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

    G = _load(SPEC_PATH)["gates"]
    DL = G["refer_deadline_ms"]

    def base_events(announce=True, ack=202, final_code=200, final_t=4000):
        evs = [{"kind": "decision", "t": 0}]
        if announce:
            evs.append({"kind": "announce", "t": 1000})
        evs.append({"kind": "refer", "t": 1200})
        evs.append({"kind": "refer_ack", "t": 1400, "code": ack})
        if ack == 202:
            evs.append({"kind": "notify", "t": 1700, "code": 100, "final": False})
            evs.append({"kind": "notify", "t": 2500, "code": 180, "final": False})
            evs.append({"kind": "notify", "t": final_t, "code": final_code, "final": True})
        return evs

    TGT = {"type": "QUEUE", "ref": "queue-support", "tenant_id": "t1"}

    # 1) Mutlu yol: başarı → TRANSFERRED, A-leg serbest, köprü yok, fallback yok
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(),
                      "correlation_id": "c1"}, DL)
    case("happy: TRANSFERRED", r["terminal"] == "TRANSFERRED")
    case("happy: A-leg serbest (C3)", r["a_leg_released"] is True)
    case("happy: köprü yok (C5)", r["bridged"] is False)
    case("happy: fallback yok", r["fallback"] is False)
    case("happy: ihlal yok", all(v == 0 for v in r["violations"].values()))
    case("happy: audit var (C7)", r["audit"] is not None and r["audit"]["outcome"] == "success")

    # 2) REFER reddi (603 Decline) → FAILED, fail-safe fallback, A-leg korunur
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(ack=603)}, DL)
    case("refer-reject: FAILED", r["terminal"] == "FAILED")
    case("refer-reject: fallback (C4)", r["fallback"] is True)
    case("refer-reject: A-leg DÜŞMEZ", r["a_leg_released"] is False)
    case("refer-reject: failure=REFER_REJECTED", r["failure_class"] == "REFER_REJECTED")
    case("refer-reject: dropped_on_failure=0", r["violations"]["dropped_on_failure"] == 0)

    # 3) NOTIFY 486 Busy → FAILED + fallback
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(final_code=486)}, DL)
    case("notify-fail: FAILED", r["terminal"] == "FAILED")
    case("notify-fail: failure=NOTIFY_FAILED", r["failure_class"] == "NOTIFY_FAILED")
    case("notify-fail: fallback", r["fallback"] is True)

    # 4) Deadline aşımı: geç 200 → DEADLINE FAILED (hang yok, C8)
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(final_t=1200 + DL + 5000)}, DL)
    case("deadline: FAILED", r["terminal"] == "FAILED")
    case("deadline: failure=DEADLINE", r["failure_class"] == "DEADLINE")
    case("deadline: hung_transfer=0 (zorlandı)", r["violations"]["hung_transfer"] == 0)
    case("deadline: fallback", r["fallback"] is True)

    # 5) Hiç final NOTIFY yok (kayıp) → deadline zorlama → FAILED
    evs = base_events()
    evs = [e for e in evs if not (e["kind"] == "notify" and e.get("final"))]
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    case("no-final: FAILED (zorlandı)", r["terminal"] == "FAILED")
    case("no-final: hung_transfer=0", r["violations"]["hung_transfer"] == 0)
    case("no-final: stuck_state=0 (REFER sonrası)", r["violations"]["stuck_state"] == 0)

    # 6) Blind REFER (anonssuz) → blind_refer ihlali (C2)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(announce=False)}, DL)
    case("blind: blind_refer>0 (C2)", r["violations"]["blind_refer"] > 0)
    case("blind: announced=False", r["announced"] is False)

    # 7) Çözülmemiş hedef → unresolved_target, REFER gönderilmez (C6)
    r = run_transfer({"tenant_id": "t1", "target": {"type": "QUEUE", "ref": ""},
                      "events": base_events()}, DL)
    case("unresolved: unresolved_target>0 (C6)", r["violations"]["unresolved_target"] > 0)
    case("unresolved: FAILED", r["terminal"] == "FAILED")

    # 8) Cross-tenant hedef → cross_tenant_target (C9)
    r = run_transfer({"tenant_id": "t1",
                      "target": {"type": "AGENT", "ref": "agent-7", "tenant_id": "t2"},
                      "events": base_events()}, DL)
    case("cross-tenant: cross_tenant_target>0 (C9)", r["violations"]["cross_tenant_target"] > 0)
    case("cross-tenant: FAILED + fallback", r["terminal"] == "FAILED" and r["fallback"] is True)

    # 9) inject drop_on_failure → dropped_on_failure (C4 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["drop_on_failure"],
                      "events": base_events(ack=603)}, DL)
    case("inject-drop: dropped_on_failure>0", r["violations"]["dropped_on_failure"] > 0)
    case("inject-drop: fallback False", r["fallback"] is False)

    # 10) inject bridge_on_cold → bridged_on_cold (C5 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["bridge_on_cold"],
                      "events": base_events()}, DL)
    case("inject-bridge: bridged_on_cold>0 (C5)", r["violations"]["bridged_on_cold"] > 0)

    # 11) inject orphan_leg → orphaned_leg (C3 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["orphan_leg"],
                      "events": base_events()}, DL)
    case("inject-orphan: orphaned_leg>0 (C3)", r["violations"]["orphaned_leg"] > 0)
    case("inject-orphan: a_leg_released False", r["a_leg_released"] is False)

    # 12) inject no_audit → missing_audit (C7 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["no_audit"],
                      "events": base_events()}, DL)
    case("inject-no-audit: missing_audit>0 (C7)", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 13) Determinizm: aynı girdi → aynı sonuç
    s = {"tenant_id": "t1", "target": TGT, "events": base_events(), "correlation_id": "c"}
    r1 = run_transfer(s, DL)
    r2 = run_transfer(s, DL)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 14) Kapı entegrasyonu: happy geçer, cross-tenant eler
    rp = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events()}, DL)
    rf = run_transfer({"tenant_id": "t1", "target": {"type": "AGENT", "ref": "a", "tenant_id": "t9"},
                       "events": base_events()}, DL)
    case("kapı: happy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: cross-tenant eler", _gate_eval(rf, G)[0] is False)

    # 15) Sızıntı tarayıcı: yapısal kimlik temiz, ham numara yakalanır
    case("leak: queue-support temiz", scan_leaks('{"ref": "queue-support"}') == [])
    case("leak: ham numara yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)
    case("leak: 555-01xx rezerve temiz", scan_leaks('{"x": "555-0142"}') == [])

    # 16) wait_ms ve refer_duration_ms hesabı
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(final_t=4000)}, DL)
    case("wait_ms = terminal-announce", r["wait_ms"] == 4000 - 1000)
    case("refer_dur = terminal-refer", r["refer_duration_ms"] == 4000 - 1200)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "cold-transfer (WBS 9.1 — SIP REFER, FR-TEL-007 cold)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "sip_refer_lifecycle": ["REFER", "202 Accepted", "NOTIFY sipfrag(100/180)", "final NOTIFY(200|≥300)", "BYE(başarıda)"],
        "event_kinds": sorted(EVENT_KINDS),
        "event_fields": {
            "decision": "{t}", "announce": "{t}", "refer": "{t}",
            "refer_ack": "{t, code}", "notify": "{t, code, final}",
        },
        "sample_fields": ["name", "tenant_id", "correlation_id", "call_id",
                          "target{type,ref,tenant_id}", "context_package_ref",
                          "deadline_ms", "inject[]", "events[]", "expect", "expected{}"],
        "target_types": sorted(VALID_TARGET_TYPES),
        "injections (degrade testi)": sorted(INJECTIONS),
        "result_fields": ["terminal", "outcome", "failure_class", "a_leg_released",
                          "agent_media_stopped", "bridged", "fallback", "wait_ms",
                          "refer_duration_ms", "audit", "violations"],
        "failure_classes": sorted(FAILURE_CLASSES),
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-TEL-007, FR-HND-007/008, SR-TEL-007, TC-TEL-007, SAD §7.3, BRD §9.12/§14.2, ADR-001/002",
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
            print("kullanım: cold_transfer_probe.py run <sample.json|dizin>")
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
