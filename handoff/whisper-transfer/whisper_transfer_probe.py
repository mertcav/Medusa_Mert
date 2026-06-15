#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.3 — Whisper transfer referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) ÜÇÜNCÜ modülü ve F2-Must aktarım çekirdeği.
FR-TEL-007'nin WHISPER transfer tipini SAHİPLENİR (COLD→9.1, WARM→9.2). SAD §7.3:
'WHISPER: yalnız temsilciye duyulan brifing'. Whisper transfer'i bir DETERMINISTIK DURUM
MAKİNESİ (ad-hoc conferencing RFC 4579 + per-katılımcı seçici medya / whisper-coach mix) olarak
gerçekler:

  INIT ─► ANNOUNCE ─► AGENT_JOINING ─► WHISPERING ─► HANDED_OFF
   │      (G2 anons,    │ (G3 200 OK)     │ (G4 per-leg whisper
   │       müşteri      │ yanıtsız/meşgul/ │   + AI çıkış; temsilci
   │       CANLI,       │ red / deadline   │   MEVCUT, müşteri↔temsilci
   │ (G1   hold YOK)    │                  │   canlı kalır)
   │  hedef)            ▼                  ▼ temsilci-yokken-çıkış
   ▼                   FAILED ◄────────────┘──► (FALLBACK: oturum DÜŞMEZ,
  FAILED                                          müşteri canlı çağrıda, 9.7)

WARM'dan (9.2) FARK: warm müşteriyi HOLD'a alır + AYRI danışma B-leg kurar + sonra köprüler;
whisper müşteriyi HOLD'a ALMAZ — temsilci CANLI konferansa eklenir, AI per-leg seçici karışımla
YALNIZ temsilciye brifing iletir (müşteri canlı, duymaz), sonra AI çıkar.

ÇEKİRDEK INVARIANT (BRD §9.12/§14.2 + SR-TEL-007): anonssuz/sessiz temsilci enjeksiyonu yok
(H2 blind-join); whisper YALNIZ temsilciye per-leg, müşteri (CANLI) duymaz (H3 whisper-privacy,
FR-HND-006 — warm'dan keskin); müşteri bekletilmez (H4 no-hold, warm'dan ayrım); AI yalnız temsilci
MEVCUTKEN çıkar (H7 premature-exit yok); başarısızlıkta oturum DÜŞMEZ + fallback (H5 fail-safe
FR-HND-007); whisper transfer brifing içerir (H6 missing-whisper); deadline→FAILED (H9 hang yok);
hedef tenant-scoped (H10 cross-tenant yok); her terminal audit (H11).

Kapsam dışı (bilinçli, başka modül SAHİBİ): transfer() SPI + ham konferans INVITE/per-leg whisper
karışım → 4.2.5 (ÇAĞIRIR/TÜKETİR); COLD→9.1; WARM→9.2; tetikleyici→9.4 (kararı TÜKETİR); hedef
seçimi→9.5 (çözülmüş hedefi TÜKETİR); bağlam paketi/screen-pop→9.6 (whisper özet referansını
TÜKETİR); fallback motoru→9.7 (TETİKLER); raporlama toplama→9.8; audit store→7.1.6/12.1.8.

Kullanım:
  whisper_transfer_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  whisper_transfer_probe.py run <sample>      FSM-yürütücü: whisper transfer(ler)i çalıştır → kapı (H1–H12)
  whisper_transfer_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  whisper_transfer_probe.py schema            Durum/olay/sonuç sözleşmesini yazdır

Determinizm: sanal saat (t, ms); Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (ham numara/içerik/brifing metni) üretilmez/yazılmaz (fixture'lar
sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "whisper-transfer-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "whisper-transfer-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["INIT", "ANNOUNCE", "AGENT_JOINING", "WHISPERING", "HANDED_OFF", "FAILED"]
NON_TERMINAL = {"INIT", "ANNOUNCE", "AGENT_JOINING", "WHISPERING"}
TERMINAL = {"HANDED_OFF", "FAILED"}
VALID_TARGET_TYPES = {"QUEUE", "SKILL", "AGENT", "NUMBER"}
INVARIANT_IDS = ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H10", "H11", "H12"]
EVENT_KINDS = {"decision", "announce", "agent_join", "join_ack", "whisper", "hold", "ai_exit"}
INJECTIONS = {"hold_customer", "whisper_leak", "premature_exit", "no_whisper",
              "skip_announce", "drop_on_failure", "no_audit"}
FAILURE_CLASSES = {"JOIN_NO_ANSWER", "JOIN_BUSY", "JOIN_REJECTED", "JOIN_DECLINED",
                   "DEADLINE", "TARGET_INVALID", "CROSS_TENANT", "BLIND_JOIN",
                   "WHISPER_LEAK", "PREMATURE_EXIT", "CUSTOMER_HELD"}

VIOLATION_KEYS = [
    "blind_join", "whisper_leaked", "customer_held", "dropped_on_failure",
    "missing_whisper", "premature_exit", "unresolved_target", "cross_tenant_target",
    "hung_transfer", "missing_audit", "stuck_state", "secret_or_pii",
]

# join_ack SIP kodu → failure_class eşlemesi (conference_transfer.fail_code_class ile hizalı)
JOIN_FAIL_CLASS = {
    408: "JOIN_NO_ANSWER", 480: "JOIN_NO_ANSWER", 486: "JOIN_BUSY",
    488: "JOIN_REJECTED", 503: "JOIN_REJECTED", 600: "JOIN_DECLINED",
    603: "JOIN_DECLINED",
}

# ── Sızıntı tarayıcı (H12; 9.1/9.2 deseniyle) — ham telefon numarası / içerik / brifing metni yasak ──
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
    """Ham PII / sır / brifing metni tarayıcı. Rezerve test bloğu + yapısal kimliği eler (9.1/9.2 deseni)."""
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
# FSM yürütücü — bir whisper transfer senaryosunu (olay akışı) durum makinesinden geçirir.
# ════════════════════════════════════════════════════════════════════════════
def _valid_target(target):
    if not isinstance(target, dict):
        return False
    t = target.get("type")
    ref = target.get("ref")
    return t in VALID_TARGET_TYPES and isinstance(ref, str) and len(ref.strip()) > 0


def run_transfer(sample, deadline_default=30000):
    """Tek whisper transfer senaryosunu yürüt → outcome + ihlal sayaçları."""
    tenant = sample.get("tenant_id")
    target = sample.get("target") or {}
    deadline = sample.get("deadline_ms", deadline_default)
    inject = set(sample.get("inject", []))
    events = sorted(sample.get("events", []), key=lambda e: e.get("t", 0))

    v = {k: 0 for k in VIOLATION_KEYS}
    state = "INIT"
    announced = False
    customer_live = True  # whisper: müşteri DAİMA canlı kalır (hold YOK)
    announce_t = None
    join_t = None
    join_answer_t = None
    agent_joined = False
    whispered = False
    whisper_private = True
    ai_exited = False
    terminal_t = None
    failure_class = None
    fallback = False
    notes = []

    # ── G1: hedef çözümü + tenant izolasyonu (temsilci eklenmeden önce) ────────────────
    target_ok = _valid_target(target)
    if not target_ok:
        v["unresolved_target"] += 1
    tgt_tenant = target.get("tenant_id")
    if tgt_tenant is not None and tenant is not None and tgt_tenant != tenant:
        v["cross_tenant_target"] += 1
        target_ok = False
        failure_class = "CROSS_TENANT"

    # Hedef geçersiz/cross-tenant ise FSM erken FAILED → fallback (temsilci EKLENMEZ).
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
            # whisper: müşteri CANLI kalır — hold YOK (warm'dan ayrım)
            if state == "INIT":
                state = "ANNOUNCE"
        elif k == "hold":
            # H4: whisper transfer müşteriyi HOLD'a ALMAZ — bu bir ihlaldir.
            v["customer_held"] += 1
            customer_live = False
            failure_class = failure_class or "CUSTOMER_HELD"
        elif k == "agent_join":
            join_t = t
            if not announced:
                # H2: anonssuz/sessiz temsilci enjeksiyonu (blind) — fail-closed sayım
                v["blind_join"] += 1
                failure_class = "BLIND_JOIN"
            state = "AGENT_JOINING"
        elif k == "join_ack":
            code = ev.get("code", 200)
            if code == 200:
                agent_joined = True
                join_answer_t = t
                state = "WHISPERING"  # temsilci canlı konferansa katıldı; müşteri canlı
            else:
                state = "FAILED"
                failure_class = JOIN_FAIL_CLASS.get(code, "JOIN_REJECTED")
                terminal_t = t
        elif k == "whisper":
            whispered = True
            # H3: whisper privacy — yalnız temsilciye (agent leg) per-leg; müşteri CANLI, duymaz.
            audience = ev.get("to", "agent")
            leaked = (audience == "customer") or bool(ev.get("leak")) \
                or ("whisper_leak" in inject)
            if leaked:
                v["whisper_leaked"] += 1
                whisper_private = False
                # not: privacy ihlali kaydedilir; FSM ilerler (gate eler)
        elif k == "ai_exit":
            ai_exited = True
            # H6: whisper transfer brifing içermeli (AI çıkışı öncesi)
            if "no_whisper" in inject or not whispered:
                v["missing_whisper"] += 1
            if not agent_joined or "premature_exit" in inject:
                # H7: temsilci mevcut değilken AI çıkışı → müşteri tek başına bırakılır
                v["premature_exit"] += 1
                state = "FAILED"
                failure_class = "PREMATURE_EXIT"
                terminal_t = t
            else:
                state = "HANDED_OFF"
                terminal_t = t
        else:
            notes.append("bilinmeyen olay: %s" % k)

    # ── inject hold_customer: olay-akışı dışı hold enjeksiyonu (H4) ─────────────────────
    if "hold_customer" in inject and v["customer_held"] == 0:
        v["customer_held"] += 1
        customer_live = False
        failure_class = failure_class or "CUSTOMER_HELD"

    # ── Başarı kapanışı: whisper verildi ama ai_exit olayı gelmediyse → platform AI çıkışı ──
    if state == "WHISPERING" and not ai_exited:
        # temsilci katıldı + whisper iletildi = müşteri↔temsilci canlı; AI çıkışı platform-temizliği
        if not whispered:
            v["missing_whisper"] += 1
        ai_exited = True
        state = "HANDED_OFF"
        terminal_t = join_answer_t

    # ── Deadline zorlama: temsilci eklendi ama terminal'e ulaşılmadıysa → FAILED ────────
    if state in NON_TERMINAL:
        if state in ("AGENT_JOINING", "WHISPERING") and join_t is not None:
            state = "FAILED"
            failure_class = "DEADLINE"
            terminal_t = (join_t + deadline)
        else:
            # INIT/ANNOUNCE'ta takılı kaldı → gerçek stuck (FSM bug)
            v["stuck_state"] += 1
            state = "FAILED"
            failure_class = "DEADLINE"

    # ── H1: terminal'e ulaşılmalı (deadline zorlamasından sonra her zaman) ──────────────
    if state not in TERMINAL:
        v["hung_transfer"] += 1

    # ── Terminal eylemleri: RELEASE_AI (başarı) / FALLBACK (başarısızlık) ───────────────
    ai_media_stopped = False
    customer_session_preserved = True  # müşteri leg'i ASLA kapanmaz (canlı kalır)
    if state == "HANDED_OFF":
        # H7: temsilci mevcut olmalı; müşteri↔temsilci canlı kalır, AI medya yolundan çıkar
        if not agent_joined:
            v["premature_exit"] += 1  # savunma: temsilcisiz HANDED_OFF imkânsız olmalı
        ai_media_stopped = True
        fallback = False
    else:  # FAILED
        # H5: fail-safe — oturum düşmez, müşteri canlı çağrıda kalır (AI ile), fallback (9.7)
        if "drop_on_failure" in inject:
            fallback = False
            customer_session_preserved = False
            v["dropped_on_failure"] += 1
        else:
            fallback = True
            customer_live = True  # müşteri canlı çağrıda (zaten beklemede değildi)

    # ── Bekleme süresi / join süresi ───────────────────────────────────────────────────
    base_t = announce_t if announce_t is not None else (join_t if join_t is not None else 0)
    wait_ms = (terminal_t - base_t) if (terminal_t is not None) else 0
    join_dur_ms = (join_answer_t - join_t) \
        if (join_answer_t is not None and join_t is not None) else None

    # ── H11: audit kaydı (her terminal) ────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "outcome": "success" if state == "HANDED_OFF" else "fail",
            "terminal": state,
            "failure_class": failure_class,
            "wait_ms": wait_ms,
            "join_duration_ms": join_dur_ms,
            "whispered": whispered,
            "whisper_private": whisper_private,
            "agent_joined": agent_joined,
            "customer_live": customer_live,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
            "target_type": target.get("type"),
        }

    outcome = "success" if state == "HANDED_OFF" else "fail"
    return {
        "name": sample.get("name"),
        "terminal": state,
        "outcome": outcome,
        "failure_class": failure_class,
        "announced": announced,
        "customer_live": customer_live,
        "agent_joined": agent_joined,
        "whispered": whispered,
        "whisper_private": whisper_private,
        "ai_exited": ai_exited,
        "ai_media_stopped": ai_media_stopped,
        "customer_session_preserved": customer_session_preserved,
        "fallback": fallback,
        "wait_ms": wait_ms,
        "join_duration_ms": join_dur_ms,
        "audit": audit,
        "violations": v,
        "notes": notes,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "blind_join": "max_blind_join",
        "whisper_leaked": "max_whisper_leaked",
        "customer_held": "max_customer_held",
        "dropped_on_failure": "max_dropped_on_failure",
        "missing_whisper": "max_missing_whisper",
        "premature_exit": "max_premature_exit",
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
    if gates.get("require_agent_present_on_success", True) and result["terminal"] == "HANDED_OFF" \
            and not result["agent_joined"]:
        fails.append("başarı ama temsilci mevcut değil (H7)")
    if gates.get("require_live_customer", True) and result["violations"]["customer_held"] > 0:
        fails.append("müşteri bekletildi (H4)")
    if gates.get("require_outcome_report", True) and result["audit"] is None:
        fails.append("outcome/audit raporu üretilmedi (H11)")
    return (len(fails) == 0, fails)


# ════════════════════════════════════════════════════════════════════════════
def run_cmd(arg):
    spec = _load(SPEC_PATH)
    gates = spec["gates"]
    deadline_default = gates.get("join_deadline_ms", 30000)

    if os.path.isdir(arg):
        paths = sorted(os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".json"))
    else:
        paths = [arg]

    all_ok = True
    for p in paths:
        sample = _load(p)
        expect = sample.get("expect", "pass")
        res = run_transfer(sample, deadline_default)
        # H12 sızıntı: sample dosyasını tara
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        # beklenen-aksiyon kontrolü (varsa)
        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "outcome", "fallback", "agent_joined",
                    "whisper_private", "customer_live"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s outcome=%s failure=%s wait=%dms whisper_private=%s agent_joined=%s customer_live=%s fallback=%s"
              % (res["terminal"], res["outcome"], res["failure_class"], res["wait_ms"],
                 res["whisper_private"], res["agent_joined"], res["customer_live"], res["fallback"]))
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
              "gates", "conference_transfer", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.3", spec.get("wbs") == "9.3")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-007 izlenir", "FR-TEL-007" in tr.get("fr", []))
    chk("FR-HND-006 izlenir (whisper brifing ruhu)", "FR-HND-006" in tr.get("fr", []))
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
    chk("terminal = {HANDED_OFF,FAILED}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal doğru", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği — erişilebilirlik + her terminal'e bir yol
    edges = spec["transitions"]["edges"]
    froms = set(e["from"] for e in edges)
    tos = set(e["to"] for e in edges)
    chk("INIT kaynak", "INIT" in froms)
    chk("HANDED_OFF hedef erişilebilir", "HANDED_OFF" in tos)
    chk("FAILED hedef erişilebilir", "FAILED" in tos)
    for s in NON_TERMINAL:
        chk("'%s' durumundan çıkış var" % s, s in froms)
    # FAILED'e birden çok yol (her aşamada fail-safe)
    fail_sources = set(e["from"] for e in edges if e["to"] == "FAILED")
    chk("FAILED'e ≥3 kaynaktan (fail-safe her aşamada)", len(fail_sources) >= 3)
    chk("on_handed_off RELEASE_AI tanımlı (canlı kal+AI çık)",
        "RELEASE_AI" in spec["transitions"].get("on_handed_off", ""))
    chk("on_failed FALLBACK tanımlı (müşteri canlı korunur)",
        "FALLBACK" in spec["transitions"].get("on_failed", ""))

    # 5) Kapılar — tüm sıfır-eşik ihlal kapıları + deadline + whisper-özgü
    g = spec["gates"]
    for gk in ("max_blind_join", "max_whisper_leaked", "max_customer_held",
               "max_dropped_on_failure", "max_missing_whisper", "max_premature_exit",
               "max_unresolved_target", "max_cross_tenant_target", "max_hung_transfer",
               "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("join_deadline_ms tanımlı (>0)",
        isinstance(g.get("join_deadline_ms"), int) and g["join_deadline_ms"] > 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_agent_present_on_success", g.get("require_agent_present_on_success") is True)
    chk("require_live_customer (no-hold, H4)", g.get("require_live_customer") is True)
    chk("require_outcome_report", g.get("require_outcome_report") is True)

    # 6) Konferans (RFC 4579) + per-leg whisper eşlemesi
    cr = spec["conference_transfer"]
    chk("join_answer_code=200", cr.get("join_answer_code") == 200)
    chk("join_fail_codes 486/603 içerir",
        486 in cr.get("join_fail_codes", []) and 603 in cr.get("join_fail_codes", []))
    chk("model per-participant selective mix", "selective mix" in cr.get("model", ""))
    chk("lifecycle hold İÇERMEZ (no-hold, H4)",
        not any("hold" in x.lower() and "yok" not in x.lower() for x in cr.get("lifecycle", [])))
    chk("lifecycle per-leg whisper içerir",
        any("per-leg whisper" in x.lower() or "whisper" in x.lower() for x in cr.get("lifecycle", [])))
    chk("lifecycle konferansa ekle içerir",
        any("konferans" in x.lower() or "ekle" in x.lower() for x in cr.get("lifecycle", [])))
    chk("conference_focus=platform/AI",
        cr.get("roles", {}).get("conference_focus", "").startswith("platform"))
    chk("customer hold YOK", "hold yok" in cr.get("roles", {}).get("customer", "").lower())

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_transfer_total metrik", "handoff_transfer_total" in obs.get("metrics", []))
    chk("handoff_wait_seconds metrik (FR-HND-008)", "handoff_wait_seconds" in obs.get("metrics", []))
    chk("handoff_whisper_total metrik (FR-HND-006)", "handoff_whisper_total" in obs.get("metrics", []))
    chk("handoff_join_duration_ms metrik", "handoff_join_duration_ms" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("call_id YÜKSEK kard (label değil)", "call_id" in hi and "call_id" not in lo)
    chk("correlation_id YÜKSEK kard (label değil)", "correlation_id" in hi)
    chk("mode/outcome DÜŞÜK kard (label uygun)", "mode" in lo and "outcome" in lo)

    # 8) İnvariant'lar H1–H12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar H1–H12 tam", inv_ids == INVARIANT_IDS)
    # whisper-özgü invariant varlığı
    inv_blob = json.dumps(spec["invariants"], ensure_ascii=False)
    chk("H3 whisper-privacy tanımlı", "whisper_leaked" in inv_blob)
    chk("H4 no-hold tanımlı (warm'dan ayrım)", "customer_held" in inv_blob)
    chk("H7 premature-exit tanımlı", "premature_exit" in inv_blob)

    # 9) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/whisper-transfer-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        chk("config join_deadline ≤ spec deadline",
            cfg.get("join_deadline_ms", 0) <= g["join_deadline_ms"])
        chk("config target_types eşler", set(cfg.get("target_types", [])) == VALID_TARGET_TYPES)
        chk("config whisper required (FR-HND-006)", cfg.get("whisper", {}).get("required") is True)
        chk("config whisper audience=agent_only (privacy)",
            cfg.get("whisper", {}).get("audience") == "agent_only")
        chk("config announce müşteri hold ALMAZ (H4)",
            cfg.get("announce", {}).get("place_customer_on_hold") is False)
        chk("config fallback yolu tanımlı (9.7)", "fallback" in cfg and "to" in cfg["fallback"])
        chk("config fallback preserve_customer_session",
            cfg.get("fallback", {}).get("preserve_customer_session") is True)

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
    chk("hiç ham PII/sır/brifing-metni sızıntısı yok (H12)", total_leaks == 0)

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
    DL = G["join_deadline_ms"]

    def base_events(announce=True, join_code=200, whisper=True,
                    whisper_to="agent", ai_exit=True, hold=False,
                    join_t=2000, whisper_t=2800, exit_t=3200):
        evs = [{"kind": "decision", "t": 0}]
        if announce:
            evs.append({"kind": "announce", "t": 1000})
        if hold:
            evs.append({"kind": "hold", "t": 1200})
        evs.append({"kind": "agent_join", "t": join_t})
        evs.append({"kind": "join_ack", "t": join_t + 200, "code": join_code})
        if join_code == 200:
            if whisper:
                evs.append({"kind": "whisper", "t": whisper_t, "to": whisper_to})
            if ai_exit:
                evs.append({"kind": "ai_exit", "t": exit_t})
        return evs

    TGT = {"type": "QUEUE", "ref": "queue-support", "tenant_id": "t1"}

    # 1) Mutlu yol: başarı → HANDED_OFF, temsilci mevcut, AI çıktı, whisper private, müşteri canlı
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(),
                      "correlation_id": "c1"}, DL)
    case("happy: HANDED_OFF", r["terminal"] == "HANDED_OFF")
    case("happy: temsilci mevcut (H7)", r["agent_joined"] is True)
    case("happy: AI çıktı + medya durdu", r["ai_exited"] and r["ai_media_stopped"])
    case("happy: müşteri CANLI (H4 no-hold)", r["customer_live"] is True)
    case("happy: whisper private (H3)", r["whisper_private"] is True)
    case("happy: whisper verildi (H6)", r["whispered"] is True)
    case("happy: fallback yok", r["fallback"] is False)
    case("happy: ihlal yok", all(val == 0 for val in r["violations"].values()))
    case("happy: audit success (H11)", r["audit"] is not None and r["audit"]["outcome"] == "success")

    # 2) Temsilci yanıtsız (480) → FAILED, fail-safe fallback, müşteri canlı korunur
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(join_code=480)}, DL)
    case("no-answer: FAILED", r["terminal"] == "FAILED")
    case("no-answer: failure=JOIN_NO_ANSWER", r["failure_class"] == "JOIN_NO_ANSWER")
    case("no-answer: fallback (H5)", r["fallback"] is True)
    case("no-answer: müşteri canlı korunur", r["customer_session_preserved"] is True and r["customer_live"] is True)
    case("no-answer: dropped_on_failure=0", r["violations"]["dropped_on_failure"] == 0)

    # 3) Temsilci meşgul (486) → FAILED + fallback
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(join_code=486)}, DL)
    case("busy: FAILED + JOIN_BUSY", r["terminal"] == "FAILED" and r["failure_class"] == "JOIN_BUSY")
    case("busy: fallback", r["fallback"] is True)

    # 4) Deadline: temsilci yanıt yok → DEADLINE FAILED (hang yok, H9)
    evs = [e for e in base_events() if e["kind"] not in ("join_ack", "whisper", "ai_exit")]
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    case("deadline: FAILED", r["terminal"] == "FAILED")
    case("deadline: failure=DEADLINE", r["failure_class"] == "DEADLINE")
    case("deadline: hung_transfer=0 (zorlandı)", r["violations"]["hung_transfer"] == 0)
    case("deadline: fallback", r["fallback"] is True)

    # 5) Blind join (anonssuz) → blind_join ihlali (H2)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(announce=False)}, DL)
    case("blind: blind_join>0 (H2)", r["violations"]["blind_join"] > 0)
    case("blind: announced=False", r["announced"] is False)

    # 6) Whisper sızıntısı (müşteri duyar) → whisper_leaked (H3)
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(whisper_to="customer")}, DL)
    case("whisper-leak: whisper_leaked>0 (H3)", r["violations"]["whisper_leaked"] > 0)
    case("whisper-leak: whisper_private False", r["whisper_private"] is False)

    # 7) Müşteri hold'a alındı → customer_held (H4 — warm'dan ayrım)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(hold=True)}, DL)
    case("hold: customer_held>0 (H4)", r["violations"]["customer_held"] > 0)
    case("hold: customer_live False", r["customer_live"] is False)

    # 8) Temsilci mevcut değilken AI çıkışı → premature_exit (H7)
    evs = [{"kind": "decision", "t": 0}, {"kind": "announce", "t": 1000},
           {"kind": "agent_join", "t": 2000}, {"kind": "ai_exit", "t": 2400}]
    r = run_transfer({"tenant_id": "t1", "target": TGT, "events": evs}, DL)
    case("premature: premature_exit>0 (H7)", r["violations"]["premature_exit"] > 0)
    case("premature: FAILED", r["terminal"] == "FAILED")
    case("premature: temsilci yok", r["agent_joined"] is False)

    # 9) Whisper atlandı (AI çıkışı öncesi brifing yok) → missing_whisper (H6)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["no_whisper"],
                      "events": base_events(whisper=False)}, DL)
    case("no-whisper: missing_whisper>0 (H6)", r["violations"]["missing_whisper"] > 0)

    # 10) Çözülmemiş hedef → unresolved_target, temsilci eklenmez (H8)
    r = run_transfer({"tenant_id": "t1", "target": {"type": "QUEUE", "ref": ""},
                      "events": base_events()}, DL)
    case("unresolved: unresolved_target>0 (H8)", r["violations"]["unresolved_target"] > 0)
    case("unresolved: FAILED", r["terminal"] == "FAILED")

    # 11) Cross-tenant hedef → cross_tenant_target (H10)
    r = run_transfer({"tenant_id": "t1",
                      "target": {"type": "AGENT", "ref": "agent-7", "tenant_id": "t2"},
                      "events": base_events()}, DL)
    case("cross-tenant: cross_tenant_target>0 (H10)", r["violations"]["cross_tenant_target"] > 0)
    case("cross-tenant: FAILED + fallback", r["terminal"] == "FAILED" and r["fallback"] is True)

    # 12) inject drop_on_failure → dropped_on_failure (H5 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["drop_on_failure"],
                      "events": base_events(join_code=486)}, DL)
    case("inject-drop: dropped_on_failure>0", r["violations"]["dropped_on_failure"] > 0)
    case("inject-drop: fallback False + session not preserved",
         r["fallback"] is False and r["customer_session_preserved"] is False)

    # 13) inject whisper_leak → whisper_leaked (H3 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["whisper_leak"],
                      "events": base_events()}, DL)
    case("inject-leak: whisper_leaked>0 (H3)", r["violations"]["whisper_leaked"] > 0)

    # 14) inject hold_customer → customer_held (H4 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["hold_customer"],
                      "events": base_events()}, DL)
    case("inject-hold: customer_held>0 (H4)", r["violations"]["customer_held"] > 0)

    # 15) inject premature_exit → premature_exit (H7 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["premature_exit"],
                      "events": base_events()}, DL)
    case("inject-premature: premature_exit>0 (H7)", r["violations"]["premature_exit"] > 0)

    # 16) inject no_audit → missing_audit (H11 ihlali)
    r = run_transfer({"tenant_id": "t1", "target": TGT, "inject": ["no_audit"],
                      "events": base_events()}, DL)
    case("inject-no-audit: missing_audit>0 (H11)", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 17) Whisper var ama ai_exit olayı yok → platform AI çıkışı, HANDED_OFF (temsilci mevcut)
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(ai_exit=False)}, DL)
    case("whisper-no-exit: HANDED_OFF", r["terminal"] == "HANDED_OFF")
    case("whisper-no-exit: ai_exited zorlandı", r["ai_exited"] is True)
    case("whisper-no-exit: premature_exit=0", r["violations"]["premature_exit"] == 0)

    # 18) Determinizm: aynı girdi → aynı sonuç
    s = {"tenant_id": "t1", "target": TGT, "events": base_events(), "correlation_id": "c"}
    r1 = run_transfer(s, DL)
    r2 = run_transfer(s, DL)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 19) Kapı entegrasyonu: happy geçer, whisper-leak + hold eler
    rp = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events()}, DL)
    rf = run_transfer({"tenant_id": "t1", "target": TGT,
                       "events": base_events(whisper_to="customer")}, DL)
    rh = run_transfer({"tenant_id": "t1", "target": TGT, "events": base_events(hold=True)}, DL)
    case("kapı: happy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: whisper-leak eler", _gate_eval(rf, G)[0] is False)
    case("kapı: customer-held eler (H4)", _gate_eval(rh, G)[0] is False)

    # 20) Sızıntı tarayıcı: yapısal kimlik temiz, ham numara yakalanır
    case("leak: queue-support temiz", scan_leaks('{"ref": "queue-support"}') == [])
    case("leak: ctx/brief referansı temiz", scan_leaks('{"ctx": "ctx-001", "b": "brief-9"}') == [])
    case("leak: ham numara yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)
    case("leak: 555-01xx rezerve temiz", scan_leaks('{"x": "555-0142"}') == [])

    # 21) wait_ms ve join_duration hesabı
    r = run_transfer({"tenant_id": "t1", "target": TGT,
                      "events": base_events(join_t=2000, exit_t=3200)}, DL)
    case("wait_ms = terminal-announce", r["wait_ms"] == 3200 - 1000)
    case("join_dur = ack-join", r["join_duration_ms"] == 2200 - 2000)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "whisper-transfer (WBS 9.3 — yalnız temsilciye duyulan brifing, FR-TEL-007 whisper)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "conference_lifecycle": [
            "focus yükselt (müşteri↔AI → konferans, müşteri CANLI)", "INVITE (temsilci → konferansa ekle)",
            "200 OK (temsilci katıldı)", "per-leg whisper (AI→temsilci, müşteri sızmaz)", "AI çıkış"],
        "event_kinds": sorted(EVENT_KINDS),
        "event_fields": {
            "decision": "{t}", "announce": "{t}", "agent_join": "{t}",
            "join_ack": "{t, code}", "whisper": "{t, to(agent|customer), leak?}",
            "hold": "{t}  (DEGRADE — whisper'da müşteri bekletilmez, H4)", "ai_exit": "{t}",
        },
        "sample_fields": ["name", "tenant_id", "correlation_id", "call_id",
                          "target{type,ref,tenant_id}", "context_package_ref",
                          "deadline_ms", "inject[]", "events[]", "expect", "expected{}"],
        "target_types": sorted(VALID_TARGET_TYPES),
        "injections (degrade testi)": sorted(INJECTIONS),
        "result_fields": ["terminal", "outcome", "failure_class", "announced", "customer_live",
                          "agent_joined", "whispered", "whisper_private", "ai_exited",
                          "ai_media_stopped", "customer_session_preserved", "fallback", "wait_ms",
                          "join_duration_ms", "audit", "violations"],
        "failure_classes": sorted(FAILURE_CLASSES),
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "diff_from_warm": "warm: müşteri HOLD + ayrı danışma B-leg + köprüleme; whisper: HOLD YOK, "
                          "temsilci canlı konferansa eklenir + per-leg seçici whisper karışımı (H4)",
        "trace": "FR-TEL-007, FR-HND-006/007/008, SR-TEL-007, TC-TEL-007, "
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
            print("kullanım: whisper_transfer_probe.py run <sample.json|dizin>")
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
