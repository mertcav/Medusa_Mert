#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.2 — Warm transfer (köprüleme + whisper brifing) referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) İKİNCİ modülü ve F1-Must aktarım çekirdeği.
FR-TEL-007'nin WARM (attended/danışmalı) transfer tipini SAHİPLENİR + FR-HND-006'yı
(whisper brifing) uygular (COLD→9.1, salt-WHISPER→9.3). SAD §7.3: 'WARM: agent köprülenir,
AI temsilciye whisper ile özet verir, sonra çıkar'. Warm transfer'i bir DETERMINISTIK DURUM
MAKİNESİ (danışmalı/attended transfer yaşam döngüsü, RFC 5589 + REFER/Replaces RFC 3891) olarak
gerçekler:

  INIT ─► ANNOUNCE ─► CONSULT_RINGING ─► WHISPER ─► BRIDGED ─► TRANSFERRED
   │       (G2 anons    │ (G3 200 OK)      │ (G4)     │ (G5 köprü+çıkış)
   │        + hold)     │ yanıtsız/meşgul/  │ whisper  │ köprülü kal + AI çıkar,
   │ (G1 hedef)         │ red / deadline    │ deadline │ A-leg KAPANMAZ (köprülü)
   ▼                    ▼                   ▼          ▼ köprüsüz-çıkış
  FAILED ◄──────────────┴───────────────────┴──────────┘──► (FALLBACK: oturum DÜŞMEZ,
                                                              müşteri hold'dan geri alınır, 9.7)

ÇEKİRDEK INVARIANT (BRD §9.12/§14.2 + SR-TEL-007/SR-HND-006): anonssuz danışma yok (W2 blind-consult);
whisper YALNIZ temsilciye, müşteri (hold'da) duymaz (W3 whisper-privacy, FR-HND-006); AI yalnız köprü
SONRASI çıkar (W4 köprüsüz-çıkış yok); danışma başarısızlığında oturum DÜŞMEZ + fallback (W5 fail-safe
FR-HND-007); warm köprüleme whisper içerir (W6 missing-whisper, FR-HND-006); deadline→FAILED (W9 hang yok);
hedef tenant-scoped (W10 cross-tenant yok); her terminal audit (W8).

Kapsam dışı (bilinçli, başka modül SAHİBİ): transfer() SPI + ham danışma INVITE/hold/köprü → 4.2.5
(ÇAĞIRIR/TÜKETİR); COLD→9.1; salt-WHISPER→9.3; tetikleyici→9.4 (kararı TÜKETİR); hedef seçimi→9.5
(çözülmüş hedefi TÜKETİR); bağlam paketi/screen-pop→9.6 (whisper özet referansını TÜKETİR); fallback
motoru→9.7 (TETİKLER); raporlama toplama→9.8; audit store→7.1.6/12.1.8.

Kullanım:
  warm_transfer_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  warm_transfer_probe.py run <sample>      FSM-yürütücü: warm transfer(ler)i çalıştır → kapı (W1–W11)
  warm_transfer_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  warm_transfer_probe.py schema            Durum/olay/sonuç sözleşmesini yazdır

Determinizm: sanal saat (t, ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (ham numara/içerik/brifing metni) üretilmez/yazılmaz (fixture'lar
sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "warm-transfer-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "warm-transfer-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["INIT", "ANNOUNCE", "CONSULT_RINGING", "WHISPER", "BRIDGED", "TRANSFERRED", "FAILED"]
NON_TERMINAL = {"INIT", "ANNOUNCE", "CONSULT_RINGING", "WHISPER", "BRIDGED"}
TERMINAL = {"TRANSFERRED", "FAILED"}
VALID_TARGET_TYPES = {"QUEUE", "SKILL", "AGENT", "NUMBER"}
INVARIANT_IDS = ["W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8", "W9", "W10", "W11"]
EVENT_KINDS = {"decision", "announce", "consult", "consult_ack", "whisper", "bridge", "ai_exit"}
INJECTIONS = {"drop_on_failure", "whisper_leak", "exit_before_bridge", "no_whisper", "skip_announce"}
FAILURE_CLASSES = {"CONSULT_NO_ANSWER", "CONSULT_BUSY", "CONSULT_REJECTED", "CONSULT_DECLINED",
                   "DEADLINE", "TARGET_INVALID", "CROSS_TENANT", "BLIND_CONSULT",
                   "WHISPER_LEAK", "UNBRIDGED_EXIT"}

VIOLATION_KEYS = [
    "blind_consult", "whisper_leaked", "unbridged_exit", "dropped_on_failure",
    "missing_whisper", "unresolved_target", "cross_tenant_target", "hung_transfer",
    "missing_audit", "stuck_state", "secret_or_pii",
]

# consult_ack SIP kodu → failure_class eşlemesi (sip_transfer.fail_code_class ile hizalı)
CONSULT_FAIL_CLASS = {
    408: "CONSULT_NO_ANSWER", 480: "CONSULT_NO_ANSWER", 486: "CONSULT_BUSY",
    488: "CONSULT_REJECTED", 503: "CONSULT_REJECTED", 600: "CONSULT_DECLINED",
    603: "CONSULT_DECLINED",
}

# ── Sızıntı tarayıcı (W11; 9.1 deseniyle) — ham telefon numarası / içerik / brifing metni yasak ──
LEAK_PATTERNS = [
    # E.164 benzeri uzun rakam dizisi (rezerve 555-01xx / +1632 test blokları HARİÇ)
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{10,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
# Rezerve/test blokları + yapısal kimlikler (sızıntı DEĞİL)
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|queue-|skill-|agent-|num-|ctx-|brief-)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır / brifing metni tarayıcı. Rezerve test bloğu + yapısal kimliği eler (9.1 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 12):m.end() + 12]
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
# FSM yürütücü — bir warm transfer senaryosunu (olay akışı) durum makinesinden geçirir.
# ════════════════════════════════════════════════════════════════════════════
def _valid_target(target):
    if not isinstance(target, dict):
        return False
    t = target.get("type")
    ref = target.get("ref")
    return t in VALID_TARGET_TYPES and isinstance(ref, str) and len(ref.strip()) > 0


def run_transfer(sample, deadline_default=30000):
    """Tek warm transfer senaryosunu yürüt → outcome + ihlal sayaçları."""
    tenant = sample.get("tenant_id")
    target = sample.get("target") or {}
    deadline = sample.get("deadline_ms", deadline_default)
    inject = set(sample.get("inject", []))
    events = sorted(sample.get("events", []), key=lambda e: e.get("t", 0))

    v = {k: 0 for k in VIOLATION_KEYS}
    state = "INIT"
    announced = False
    customer_on_hold = False
    announce_t = None
    consult_t = None
    consult_answer_t = None
    whispered = False
    whisper_private = True
    bridge_established = False
    bridge_t = None
    ai_exited = False
    terminal_t = None
    failure_class = None
    fallback = False
    notes = []

    # ── G1: hedef çözümü + tenant izolasyonu (danışma kurulmadan önce) ────────────────
    target_ok = _valid_target(target)
    if not target_ok:
        v["unresolved_target"] += 1
    tgt_tenant = target.get("tenant_id")
    if tgt_tenant is not None and tenant is not None and tgt_tenant != tenant:
        v["cross_tenant_target"] += 1
        target_ok = False
        failure_class = "CROSS_TENANT"

    # Hedef geçersiz/cross-tenant ise FSM erken FAILED → fallback (danışma KURULMAZ).
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
            if "skip_announce" in inject:
                continue  # degrade: anons atlanır
            announced = True
            announce_t = t
            customer_on_hold = True  # müşteri hold'a alınır (sendonly)
            if state == "INIT":
                state = "ANNOUNCE"
        elif k == "consult":
            consult_t = t
            if not announced:
                # W2: anonssuz danışma çağrısı (blind) — fail-closed sayım
                v["blind_consult"] += 1
                failure_class = "BLIND_CONSULT"
            state = "CONSULT_RINGING"
        elif k == "consult_ack":
            code = ev.get("code", 200)
            if code == 200:
                consult_answer_t = t
                state = "WHISPER"  # hedef yanıtladı, danışma kuruldu; müşteri hold'da
            else:
                state = "FAILED"
                failure_class = CONSULT_FAIL_CLASS.get(code, "CONSULT_REJECTED")
                terminal_t = t
        elif k == "whisper":
            whispered = True
            # W3: whisper privacy — yalnız temsilciye (B-leg); müşteri hold'da, duymaz.
            audience = ev.get("to", "agent")
            leaked = (audience == "customer") or bool(ev.get("leak")) \
                or ("whisper_leak" in inject) or (not customer_on_hold) or bridge_established
            if leaked:
                v["whisper_leaked"] += 1
                whisper_private = False
                # not: privacy ihlali kaydedilir; FSM ilerler (gate eler)
        elif k == "bridge":
            # W6: köprü öncesi whisper brifing zorunlu (FR-HND-006)
            if "no_whisper" in inject or not whispered:
                v["missing_whisper"] += 1
            bridge_established = True
            bridge_t = t
            if state in ("WHISPER", "CONSULT_RINGING"):
                state = "BRIDGED"
        elif k == "ai_exit":
            ai_exited = True
            if not bridge_established or "exit_before_bridge" in inject:
                # W4: köprü kurulmadan AI çıkışı → müşteri ortada bırakılır
                v["unbridged_exit"] += 1
                state = "FAILED"
                failure_class = "UNBRIDGED_EXIT"
                terminal_t = t
            else:
                state = "TRANSFERRED"
                terminal_t = t
        else:
            notes.append("bilinmeyen olay: %s" % k)

    # ── Başarı kapanışı: köprü kuruldu ama ai_exit olayı gelmediyse → platform AI çıkışı ──
    if state == "BRIDGED" and not ai_exited:
        # köprü kuruldu = müşteri temsilciyle; AI çıkışı platform-temizliği (sıra: köprü ÖNCE)
        ai_exited = True
        state = "TRANSFERRED"
        terminal_t = bridge_t

    # ── Deadline zorlama: danışma kuruldu ama terminal'e ulaşılmadıysa → FAILED ─────────
    if state in NON_TERMINAL:
        if state in ("CONSULT_RINGING", "WHISPER", "BRIDGED") and consult_t is not None:
            state = "FAILED"
            failure_class = "DEADLINE"
            terminal_t = (consult_t + deadline)
        else:
            # INIT/ANNOUNCE'ta takılı kaldı → gerçek stuck (FSM bug)
            v["stuck_state"] += 1
            state = "FAILED"
            failure_class = "DEADLINE"

    # ── W1: terminal'e ulaşılmalı (deadline zorlamasından sonra her zaman) ──────────────
    if state not in TERMINAL:
        v["hung_transfer"] += 1

    # ── Terminal eylemleri: RELEASE_AI (başarı) / FALLBACK (başarısızlık) ───────────────
    a_leg_released = False  # warm: A-leg KAPANMAZ (başarıda köprülü / başarısızlıkta korunur)
    agent_media_stopped = False
    if state == "TRANSFERRED":
        # W4: köprü kurulu olmalı; A+B köprülü kalır, AI medya yolundan çıkar
        if not bridge_established:
            v["unbridged_exit"] += 1  # savunma: köprüsüz TRANSFERRED imkânsız olmalı
        agent_media_stopped = True
        customer_on_hold = False  # köprüde, hold biter
        fallback = False
    else:  # FAILED
        # W5: fail-safe — oturum düşmez, müşteri hold'dan geri alınır, fallback (9.7)
        if "drop_on_failure" in inject:
            fallback = False
            v["dropped_on_failure"] += 1
        else:
            fallback = True
            customer_on_hold = False  # müşteri hold'dan geri alınır (agent'a döner)

    # ── Bekleme süresi / danışma süresi ───────────────────────────────────────────────
    base_t = announce_t if announce_t is not None else (consult_t if consult_t is not None else 0)
    wait_ms = (terminal_t - base_t) if (terminal_t is not None) else 0
    consult_dur_ms = (consult_answer_t - consult_t) \
        if (consult_answer_t is not None and consult_t is not None) else None

    # ── W8: audit kaydı (her terminal) ────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "outcome": "success" if state == "TRANSFERRED" else "fail",
            "terminal": state,
            "failure_class": failure_class,
            "wait_ms": wait_ms,
            "consult_duration_ms": consult_dur_ms,
            "whispered": whispered,
            "whisper_private": whisper_private,
            "bridge_established": bridge_established,
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
        "customer_on_hold": customer_on_hold,
        "whispered": whispered,
        "whisper_private": whisper_private,
        "bridge_established": bridge_established,
        "ai_exited": ai_exited,
        "a_leg_released": a_leg_released,
        "agent_media_stopped": agent_media_stopped,
        "fallback": fallback,
        "wait_ms": wait_ms,
        "consult_duration_ms": consult_dur_ms,
        "audit": audit,
        "violations": v,
        "notes": notes,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "blind_consult": "max_blind_consult",
        "whisper_leaked": "max_whisper_leaked",
        "unbridged_exit": "max_unbridged_exit",
        "dropped_on_failure": "max_dropped_on_failure",
        "missing_whisper": "max_missing_whisper",
        "unresolved_target": "max_unresolved_target",
        "cross_tenant_target": "max_cross_tenant_target",
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
    if gates.get("require_bridge_on_success", True) and result["terminal"] == "TRANSFERRED" \
            and not result["bridge_established"]:
        fails.append("başarı ama köprü kurulmadı (W4)")
    if gates.get("require_outcome_report", True) and result["audit"] is None:
        fails.append("outcome/audit raporu üretilmedi (W8)")
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def run_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]
    deadline_default = gates.get("consult_deadline_ms", 30000)

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = run_transfer(sample, deadline_default)
        # W11 sızıntı: sample dosyasını tara
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        # beklenen-aksiyon kontrolü (varsa)
        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "outcome", "fallback", "bridge_established",
                    "whisper_private", "a_leg_released"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s outcome=%s failure=%s wait=%dms whisper_private=%s bridge=%s fallback=%s"
              % (res["terminal"], res["outcome"], res["failure_class"], res["wait_ms"],
                 res["whisper_private"], res["bridge_established"], res["fallback"]))
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
              "gates", "sip_transfer", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.2", spec.get("wbs") == "9.2")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-007 izlenir", "FR-TEL-007" in tr.get("fr", []))
    chk("FR-HND-006 izlenir (whisper brifing)", "FR-HND-006" in tr.get("fr", []))
    chk("FR-HND-007 izlenir (fallback)", "FR-HND-007" in tr.get("fr", []))
    chk("FR-HND-008 izlenir (raporlama)", "FR-HND-008" in tr.get("fr", []))
    chk("SR-TEL-007 izlenir", "SR-TEL-007" in tr.get("srs", []))
    chk("SR-HND-006 izlenir", "SR-HND-006" in tr.get("srs", []))
    chk("TC-TEL-007 izlenir", "TC-TEL-007" in tr.get("rtm", []))
    chk("TC-HND-006 izlenir", "TC-HND-006" in tr.get("rtm", []))
    chk("ADR-001/002 izlenir", any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", [])))
    chk("SAD §7.3 izlenir", any("§7.3" in s for s in tr.get("sad", [])))

    # 3) Durum makinesi tutarlılığı
    st = spec["states"]
    chk("flow = 7 durum", st.get("flow") == STATES)
    chk("terminal = {TRANSFERRED,FAILED}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal doğru", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği — erişilebilirlik + her terminal'e bir yol
    edges = spec["transitions"]["edges"]
    froms = set(e["from"] for e in edges)
    tos = set(e["to"] for e in edges)
    chk("INIT kaynak", "INIT" in froms)
    chk("TRANSFERRED hedef erişilebilir", "TRANSFERRED" in tos)
    chk("FAILED hedef erişilebilir", "FAILED" in tos)
    for s in NON_TERMINAL:
        chk("'%s' durumundan çıkış var" % s, s in froms)
    # FAILED'e birden çok yol (her aşamada fail-safe)
    fail_sources = set(e["from"] for e in edges if e["to"] == "FAILED")
    chk("FAILED'e ≥4 kaynaktan (fail-safe her aşamada)", len(fail_sources) >= 4)
    chk("on_transferred RELEASE_AI tanımlı (köprülü kal+AI çık)",
        "RELEASE_AI" in spec["transitions"].get("on_transferred", ""))
    chk("on_failed FALLBACK tanımlı (hold'dan geri al)",
        "FALLBACK" in spec["transitions"].get("on_failed", ""))

    # 5) Kapılar — tüm sıfır-eşik ihlal kapıları + deadline + warm-özgü
    g = spec["gates"]
    for gk in ("max_blind_consult", "max_whisper_leaked", "max_unbridged_exit",
               "max_dropped_on_failure", "max_missing_whisper", "max_unresolved_target",
               "max_cross_tenant_target", "max_hung_transfer", "max_missing_audit",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("consult_deadline_ms tanımlı (>0)",
        isinstance(g.get("consult_deadline_ms"), int) and g["consult_deadline_ms"] > 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_bridge_on_success", g.get("require_bridge_on_success") is True)
    chk("require_outcome_report", g.get("require_outcome_report") is True)

    # 6) SIP attended-transfer eşlemesi (RFC 5589 / 3891)
    sr = spec["sip_transfer"]
    chk("consult_answer_code=200", sr.get("consult_answer_code") == 200)
    chk("consult_fail_codes 486/603 içerir",
        486 in sr.get("consult_fail_codes", []) and 603 in sr.get("consult_fail_codes", []))
    chk("lifecycle re-INVITE hold içerir", any("hold" in x.lower() for x in sr.get("lifecycle", [])))
    chk("lifecycle whisper içerir", any("whisper" in x.lower() for x in sr.get("lifecycle", [])))
    chk("lifecycle köprü (REFER/Replaces) içerir",
        any("Replaces" in x or "köprü" in x.lower() for x in sr.get("lifecycle", [])))
    chk("transferor=platform/AI", sr.get("roles", {}).get("transferor", "").startswith("platform"))
    chk("transferee=müşteri hold", "hold" in sr.get("roles", {}).get("transferee", "").lower())

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_transfer_total metrik", "handoff_transfer_total" in obs.get("metrics", []))
    chk("handoff_wait_seconds metrik (FR-HND-008)", "handoff_wait_seconds" in obs.get("metrics", []))
    chk("handoff_whisper_total metrik (FR-HND-006)", "handoff_whisper_total" in obs.get("metrics", []))
    chk("handoff_consult_duration_ms metrik", "handoff_consult_duration_ms" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("call_id YÜKSEK kard (label değil)", "call_id" in hi and "call_id" not in lo)
    chk("correlation_id YÜKSEK kard (label değil)", "correlation_id" in hi)
    chk("mode/outcome DÜŞÜK kard (label uygun)", "mode" in lo and "outcome" in lo)

    # 8) İnvariant'lar W1–W11
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar W1–W11 tam", inv_ids == INVARIANT_IDS)
    # warm-özgü invariant varlığı
    inv_blob = json.dumps(spec["invariants"], ensure_ascii=False)
    chk("W3 whisper-privacy tanımlı", "whisper_leaked" in inv_blob)
    chk("W4 köprü-önce-çıkış tanımlı", "unbridged_exit" in inv_blob)
    chk("W6 whisper-dahil tanımlı (FR-HND-006)", "missing_whisper" in inv_blob)

    # 9) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/warm-transfer-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config consult_deadline ≤ spec deadline",
            cfg.get("consult_deadline_ms", 0) <= g["consult_deadline_ms"])
        chk("config target_types eşler", set(cfg.get("target_types", [])) == VALID_TARGET_TYPES)
        chk("config whisper required (FR-HND-006)", cfg.get("whisper", {}).get("required") is True)
        chk("config whisper audience=agent_only (privacy)",
            cfg.get("whisper", {}).get("audience") == "agent_only")
        chk("config fallback yolu tanımlı (9.7)", "fallback" in cfg and "to" in cfg["fallback"])
        chk("config fallback preserve_a_leg", cfg.get("fallback", {}).get("preserve_a_leg") is True)

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
    chk("hiç ham PII/sır/brifing-metni sızıntısı yok (W11)", total_leaks == 0)

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

    G = _load(SPEC_PATH)["gates"]
    DL = G["consult_deadline_ms"]

    def base_events(announce=True, consult_code=200, whisper=True,
                    whisper_to="agent", bridge=True, ai_exit=True,
                    consult_t=2000, whisper_t=2500, bridge_t=2800, exit_t=3000):
        evs = [{"kind": "decision", "t": 0}]
        if announce:
            evs.append({"kind": "announce", "t": 1000})
        evs.append({"kind": "consult", "t": consult_t})
        evs.append({"kind": "consult_ack", "t": consult_t + 200, "code": consult_code})
        if consult_code == 200:
            if whisper:
                evs.append({"kind": "whisper", "t": whisper_t, "to": whisper_to})
            if bridge:
                evs.append({"kind": "bridge", "t": bridge_t})
            if ai_exit:
                evs.append({"kind": "ai_exit", "t": exit_t})
        return evs

    TGT = {"type": "QUEUE", "ref": "queue-support", "tenant_id": "t1"}

    # 1) Mutlu yol: başarı → TRANSFERRED, köprülü, AI çıktı, whisper private, A-leg kapanmaz
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(),
                      "correlation_id": "c1"}, DL)
    case("happy: TRANSFERRED", r["terminal"] == "TRANSFERRED")
    case("happy: köprü kuruldu (W4)", r["bridge_established"] is True)
    case("happy: AI çıktı + medya durdu", r["ai_exited"] and r["agent_media_stopped"])
    case("happy: A-leg KAPANMAZ (warm köprülü)", r["a_leg_released"] is False)
    case("happy: whisper private (W3)", r["whisper_private"] is True)
    case("happy: whisper verildi (W6)", r["whispered"] is True)
    case("happy: fallback yok", r["fallback"] is False)
    case("happy: ihlal yok", all(val == 0 for val in r["violations"].values()))
    case("happy: audit success (W8)", r["audit"] is not None and r["audit"]["outcome"] == "success")

    # 2) Danışma yanıtsız (480) → FAILED, fail-safe fallback, A-leg korunur
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(consult_code=480)}, DL)
    case("no-answer: FAILED", r["terminal"] == "FAILED")
    case("no-answer: failure=CONSULT_NO_ANSWER", r["failure_class"] == "CONSULT_NO_ANSWER")
    case("no-answer: fallback (W5)", r["fallback"] is True)
    case("no-answer: müşteri hold'dan geri alındı", r["customer_on_hold"] is False)
    case("no-answer: dropped_on_failure=0", r["violations"]["dropped_on_failure"] == 0)

    # 3) Danışma meşgul (486) → FAILED + fallback
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(consult_code=486)}, DL)
    case("busy: FAILED + CONSULT_BUSY", r["terminal"] == "FAILED" and r["failure_class"] == "CONSULT_BUSY")
    case("busy: fallback", r["fallback"] is True)

    # 4) Deadline: danışma yanıt yok → DEADLINE FAILED (hang yok, W9)
    evs = [e for e in base_events() if e["kind"] not in ("consult_ack", "whisper", "bridge", "ai_exit")]
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    case("deadline: FAILED", r["terminal"] == "FAILED")
    case("deadline: failure=DEADLINE", r["failure_class"] == "DEADLINE")
    case("deadline: hung_transfer=0 (zorlandı)", r["violations"]["hung_transfer"] == 0)
    case("deadline: fallback", r["fallback"] is True)

    # 5) Blind consult (anonssuz) → blind_consult ihlali (W2)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(announce=False)}, DL)
    case("blind: blind_consult>0 (W2)", r["violations"]["blind_consult"] > 0)
    case("blind: announced=False", r["announced"] is False)

    # 6) Whisper sızıntısı (müşteri duyar) → whisper_leaked (W3)
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(whisper_to="customer")}, DL)
    case("whisper-leak: whisper_leaked>0 (W3)", r["violations"]["whisper_leaked"] > 0)
    case("whisper-leak: whisper_private False", r["whisper_private"] is False)

    # 7) Köprüsüz AI çıkışı → unbridged_exit (W4), müşteri ortada
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(bridge=False, ai_exit=True, exit_t=2900)}, DL)
    case("unbridged-exit: unbridged_exit>0 (W4)", r["violations"]["unbridged_exit"] > 0)
    case("unbridged-exit: FAILED", r["terminal"] == "FAILED")
    case("unbridged-exit: köprü yok", r["bridge_established"] is False)

    # 8) Whisper atlandı (köprü öncesi brifing yok) → missing_whisper (W6)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["no_whisper"],
                      "events": base_events(whisper=False)}, DL)
    case("no-whisper: missing_whisper>0 (W6)", r["violations"]["missing_whisper"] > 0)

    # 9) Çözülmemiş hedef → unresolved_target, danışma kurulmaz (W7)
    r = run_transfer({"tenant_id": "t1", "target": {"type": "QUEUE", "ref": ""},
                      "events": base_events()}, DL)
    case("unresolved: unresolved_target>0 (W7)", r["violations"]["unresolved_target"] > 0)
    case("unresolved: FAILED", r["terminal"] == "FAILED")

    # 10) Cross-tenant hedef → cross_tenant_target (W10)
    r = run_transfer({"tenant_id": "t1",
                      "target": {"type": "AGENT", "ref": "agent-7", "tenant_id": "t2"},
                      "events": base_events()}, DL)
    case("cross-tenant: cross_tenant_target>0 (W10)", r["violations"]["cross_tenant_target"] > 0)
    case("cross-tenant: FAILED + fallback", r["terminal"] == "FAILED" and r["fallback"] is True)

    # 11) inject drop_on_failure → dropped_on_failure (W5 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["drop_on_failure"],
                      "events": base_events(consult_code=486)}, DL)
    case("inject-drop: dropped_on_failure>0", r["violations"]["dropped_on_failure"] > 0)
    case("inject-drop: fallback False", r["fallback"] is False)

    # 12) inject whisper_leak → whisper_leaked (W3 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["whisper_leak"],
                      "events": base_events()}, DL)
    case("inject-leak: whisper_leaked>0 (W3)", r["violations"]["whisper_leaked"] > 0)

    # 13) inject exit_before_bridge → unbridged_exit (W4 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["exit_before_bridge"],
                      "events": base_events()}, DL)
    case("inject-exit: unbridged_exit>0 (W4)", r["violations"]["unbridged_exit"] > 0)

    # 14) inject no_audit → missing_audit (W8 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["no_audit"],
                      "events": base_events()}, DL)
    case("inject-no-audit: missing_audit>0 (W8)", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 15) Köprü var ama ai_exit olayı yok → platform AI çıkışı, TRANSFERRED (köprü ÖNCE)
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(ai_exit=False)}, DL)
    case("bridge-no-exit: TRANSFERRED", r["terminal"] == "TRANSFERRED")
    case("bridge-no-exit: ai_exited zorlandı", r["ai_exited"] is True)
    case("bridge-no-exit: unbridged_exit=0", r["violations"]["unbridged_exit"] == 0)

    # 16) Determinizm: aynı girdi → aynı sonuç
    s = {"tenant_id": "t1", "target": TGT, "events": base_events(), "correlation_id": "c"}
    r1 = run_transfer(s, DL)
    r2 = run_transfer(s, DL)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 17) Kapı entegrasyonu: happy geçer, whisper-leak eler
    rp = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events()}, DL)
    rf = run_transfer({"tenant_id": "t1", "target": TGT,
                       "events": base_events(whisper_to="customer")}, DL)
    case("kapı: happy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: whisper-leak eler", _gate_eval(rf, G)[0] is False)

    # 18) Sızıntı tarayıcı: yapısal kimlik temiz, ham numara yakalanır
    case("leak: queue-support temiz", scan_leaks('{"ref": "queue-support"}') == [])
    case("leak: ctx/brief referansı temiz", scan_leaks('{"ctx": "ctx-001", "b": "brief-9"}') == [])
    case("leak: ham numara yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)
    case("leak: 555-01xx rezerve temiz", scan_leaks('{"x": "555-0142"}') == [])

    # 19) wait_ms ve consult_duration hesabı
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(consult_t=2000, exit_t=3000)}, DL)
    case("wait_ms = terminal-announce", r["wait_ms"] == 3000 - 1000)
    case("consult_dur = ack-consult", r["consult_duration_ms"] == 2200 - 2000)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "warm-transfer (WBS 9.2 — köprüleme + whisper brifing, FR-TEL-007 warm + FR-HND-006)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "attended_transfer_lifecycle": [
            "re-INVITE (müşteri hold)", "INVITE (danışma B-leg)", "200 OK (hedef yanıt)",
            "whisper (AI↔temsilci, müşteri sızmaz)", "REFER+Replaces (A+B köprüle)", "AI çıkış"],
        "event_kinds": sorted(EVENT_KINDS),
        "event_fields": {
            "decision": "{t}", "announce": "{t}", "consult": "{t}",
            "consult_ack": "{t, code}", "whisper": "{t, to(agent|customer), leak?}",
            "bridge": "{t}", "ai_exit": "{t}",
        },
        "sample_fields": ["name", "tenant_id", "correlation_id", "call_id",
                          "target{type,ref,tenant_id}", "context_package_ref",
                          "deadline_ms", "inject[]", "events[]", "expect", "expected{}"],
        "target_types": sorted(VALID_TARGET_TYPES),
        "injections (degrade testi)": sorted(INJECTIONS),
        "result_fields": ["terminal", "outcome", "failure_class", "announced", "customer_on_hold",
                          "whispered", "whisper_private", "bridge_established", "ai_exited",
                          "a_leg_released", "agent_media_stopped", "fallback", "wait_ms",
                          "consult_duration_ms", "audit", "violations"],
        "failure_classes": sorted(FAILURE_CLASSES),
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-TEL-007, FR-HND-006/007/008, SR-TEL-007, SR-HND-006, TC-TEL-007, TC-HND-006, "
                 "SAD §7.3, BRD §9.12/§14.2, ADR-001/002/005",
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
            print("kullanım: warm_transfer_probe.py run <sample.json|dizin>")
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
