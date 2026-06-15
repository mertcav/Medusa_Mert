#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.4 — Transfer tetikleyiciler (kullanıcı isteği · düşük confidence · öfke · politika) referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) DÖRDÜNCÜ modülü ve F1-Must aktarım çekirdeği.
FR-HND-001 (müşteri istediğinde aktarım) + FR-HND-002 (düşük confidence/öfke/politika tetikleyebilmeli)
tetikleme KARARINI sahiplenir. 9.1/9.2/9.3 (cold/warm/whisper) modüllerinin 'tetikleyici→9.4 (kararı
TÜKETİR)' dediği KARAR ÜRETİCİSİ budur. Modül bir SİNYAL DEĞERLENDİRME MOTORU (deterministik):

  MONITORING ──(end, niteleyen yok)──► NO_HANDOFF        (sağlıklı yol, T7 uydurma handoff yok)
      │
      └─(bir kural niteledi)──► TRIGGERED ──► (EMIT: TransferDecision → 9.1/9.2/9.3; LATCH+cooldown T8)

Dört tetik sınıfı + öncelik: USER_REQUEST(1, mandatory) > POLICY(2, mandatory) > ANGER(3, heuristic)
> LOW_CONFIDENCE(4, heuristic). USER_REQUEST/POLICY bastırılamaz (T2/T5); ANGER/LOW_CONFIDENCE eşik+
sürdürme (sustain) gerektirir, LOW_CONFIDENCE debounce/histerezis (T3 tek geçici tur tetiklemez).

ÇEKİRDEK INVARIANT (BRD §9.12 + SR-HND-001/002): kullanıcı isteği daima onurlandırılır (T2);
düşük-conf debounce (T3); öfke eşik+sürdürme (T4); politika confidence ile bastırılamaz (T5);
çoklu tetikte deterministik öncelik tek primary (T6); sağlıklıda spurious yok (T7); ilk-niteleyen
LATCH+cooldown (T8); her tetik kanıt taşır (T9); her karar audit (T10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): aktarım MEKANİZMASI → 9.1/9.2/9.3 (kararı TÜKETİR);
hedef seçimi → 9.5; bağlam paketi → 9.6; fallback → 9.7; raporlama → 9.8; confidence ÜRETİMİ →
STT (4.x); sentiment ÜRETİMİ → NLU/duygu; intent → 3.x; audit store → 7.1.6/12.1.8.

Kullanım:
  transfer_triggers_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  transfer_triggers_probe.py run <sample>      Değerlendirici: tetik senaryo(lar)ını çalıştır → kapı (T1–T11)
  transfer_triggers_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  transfer_triggers_probe.py schema            Durum/sinyal/karar sözleşmesini yazdır

Determinizm: sanal saat (t, ms) + tur indeksi; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (ham transkript/müşteri sözleri) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "transfer-triggers-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "transfer-trigger-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["MONITORING", "TRIGGERED", "NO_HANDOFF"]
NON_TERMINAL = {"MONITORING"}
TERMINAL = {"TRIGGERED", "NO_HANDOFF"}
REASONS = ["USER_REQUEST", "POLICY", "ANGER", "LOW_CONFIDENCE"]
PRIORITY = {"USER_REQUEST": 1, "POLICY": 2, "ANGER": 3, "LOW_CONFIDENCE": 4}
MANDATORY = {"USER_REQUEST", "POLICY"}
INVARIANT_IDS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11"]
SIGNAL_KINDS = {"user_request", "confidence", "sentiment", "policy", "end"}
INJECTIONS = {"suppress_user_request", "ignore_policy", "no_debounce",
              "wrong_precedence", "retrigger", "no_audit"}

VIOLATION_KEYS = [
    "user_request_ignored", "policy_ignored", "false_trigger", "wrong_precedence",
    "duplicate_decision", "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (T11; 9.1/9.2/9.3 deseniyle) — ham transkript/müşteri sözleri/numara yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{10,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # ham transkript/müşteri sözleri alanı (yalnız skor/kimlik taşımalı)
    ("utterance", re.compile(r"(?i)\"(transcript_text|utterance|customer_said|said|raw_text)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|rule-|policy-|turn-)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır / transkript tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (1.1.8 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                # $comment / desc alanları bağlamı tarif eder → atla
                if '"$comment"' in line or '"desc"' in line or '"trace"' in line:
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
# Değerlendirme motoru — tur sinyal akışını eşik/histerezis/öncelik kurallarından geçirir.
# ════════════════════════════════════════════════════════════════════════════
def _merge_thresholds(spec, sample):
    th = dict(spec["thresholds"])
    # spec.thresholds içindeki yardımcı anahtarları ayıkla
    th.pop("$comment", None)
    th.pop("bounds", None)
    ov = sample.get("config_override", {}) or {}
    for k in ("low_conf_threshold", "low_conf_sustain_turns",
              "anger_threshold", "anger_sustain_turns"):
        if k in ov:
            th[k] = ov[k]
    return th


def evaluate(sample, spec, inject=None):
    """Tek tetik senaryosunu yürüt → TransferDecision + ihlal sayaçları.

    Motor DOĞRU davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen
    ihlal sayacını artırır (9.1 cold-transfer inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    tenant = sample.get("tenant_id")
    th = _merge_thresholds(spec, sample)
    low_thr = th["low_conf_threshold"]
    anger_thr = th["anger_threshold"]
    # debounce/histerezis pencereleri (spec) — inject no_debounce bunları 1'e indirir (yanlış)
    spec_low_sustain = th["low_conf_sustain_turns"]
    spec_anger_sustain = th["anger_sustain_turns"]
    eff_low_sustain = 1 if "no_debounce" in inject else spec_low_sustain
    eff_anger_sustain = 1 if "no_debounce" in inject else spec_anger_sustain

    signals = sorted(sample.get("signals", []), key=lambda s: (s.get("t", 0), PRIORITY.get(_reason_of(s), 9)))

    v = {k: 0 for k in VIOLATION_KEYS}
    state = "MONITORING"
    low_run = 0
    anger_run = 0
    decision = None          # ilk TRIGGERED kararı (LATCH)
    extra_decisions = 0      # cooldown sonrası ek kararlar (T8 ihlali sayımı)
    ended = False

    # turları (t) gruplayarak işle: aynı turda çoklu nitelik → öncelik (T6)
    by_turn = {}
    for s in signals:
        by_turn.setdefault(s.get("t", 0), []).append(s)

    for t in sorted(by_turn.keys()):
        group = by_turn[t]
        qualified = []   # bu turda niteleyen (reason, evidence) listesi

        for s in group:
            kind = s.get("kind")
            if kind == "end":
                ended = True
                continue
            if kind == "user_request":
                qualified.append(("USER_REQUEST", {"turn": s.get("turn"), "intent": "handoff_request"}))
            elif kind == "policy":
                qualified.append(("POLICY", {"turn": s.get("turn"), "rule": s.get("rule")}))
            elif kind == "sentiment":
                score = float(s.get("anger", 0.0))
                if score >= anger_thr:
                    anger_run += 1
                else:
                    anger_run = 0
                if anger_run >= eff_anger_sustain:
                    qualified.append(("ANGER", {"turn": s.get("turn"), "anger": score,
                                                "run": anger_run, "sustain": spec_anger_sustain}))
            elif kind == "confidence":
                score = float(s.get("score", 1.0))
                if score <= low_thr:
                    low_run += 1
                else:
                    low_run = 0
                if low_run >= eff_low_sustain:
                    qualified.append(("LOW_CONFIDENCE", {"turn": s.get("turn"), "score": score,
                                                         "run": low_run, "sustain": spec_low_sustain}))

        if not qualified:
            continue

        # ── Bir kural niteledi: öncelik çöz (T6) ──────────────────────────────────────
        # contributing: bu turda niteleyen tüm reason'lar
        contributing = sorted(set(r for r, _ in qualified), key=lambda r: PRIORITY[r])
        ev_by_reason = {}
        for r, ev in qualified:
            ev_by_reason.setdefault(r, ev)

        # inject: politika/kullanıcı-isteği bastırma (T2/T5) ────────────────────────────
        if "suppress_user_request" in inject and "USER_REQUEST" in contributing:
            contributing = [r for r in contributing if r != "USER_REQUEST"]
            v["user_request_ignored"] += 1
        if "ignore_policy" in inject and "POLICY" in contributing:
            contributing = [r for r in contributing if r != "POLICY"]
            v["policy_ignored"] += 1
        if not contributing:
            # bastırma sonrası niteleyen kalmadı → bu tur tetiklemez, devam
            continue

        # primary: en yüksek öncelik (doğru); inject wrong_precedence → en düşük (yanlış)
        if "wrong_precedence" in inject and len(contributing) > 1:
            primary = max(contributing, key=lambda r: PRIORITY[r])
            v["wrong_precedence"] += 1
        else:
            primary = min(contributing, key=lambda r: PRIORITY[r])

        ev = ev_by_reason[primary]

        # T3/T4/T7 false_trigger tespiti: heuristic tetik gerçek sürdürme penceresini sağlamıyorsa
        if primary in ("LOW_CONFIDENCE", "ANGER"):
            req = spec_low_sustain if primary == "LOW_CONFIDENCE" else spec_anger_sustain
            run = ev.get("run", 0)
            if run < req:
                v["false_trigger"] += 1

        new_decision = {
            "triggered": True,
            "primary_reason": primary,
            "trigger_class": "mandatory" if primary in MANDATORY else "heuristic",
            "contributing": contributing,
            "trigger_turn": ev.get("turn"),
            "trigger_t": t,
            "evidence": ev,
        }

        if state == "TRIGGERED":
            # Cooldown LATCH'lendi → DOĞRU motor sonraki niteleyen turları YOK SAYAR
            # (ek karar üretmez, T8). Bu yüzden burada hiçbir şey sayılmaz — sessizce geç.
            continue
        else:
            state = "TRIGGERED"
            decision = new_decision
            # inject retrigger: cooldown'a rağmen ikinci kararı zorla yay (T8 ihlali)
            if "retrigger" in inject:
                extra_decisions += 1

    if extra_decisions > 0:
        v["duplicate_decision"] += extra_decisions

    # ── Terminal çözümü ──────────────────────────────────────────────────────────────
    if state != "TRIGGERED":
        # tetik yok → çağrı sonu varsa NO_HANDOFF, yoksa hâlâ MONITORING (stuck)
        if ended:
            state = "NO_HANDOFF"
        else:
            v["stuck_state"] += 1   # ne tetik ne de end → tanımsız (FSM bug)
            state = "NO_HANDOFF"

    # ── T9: kanıt + reason (TRIGGERED için) ──────────────────────────────────────────
    if state == "TRIGGERED":
        if not decision or not decision.get("primary_reason") or not decision.get("evidence"):
            v["missing_evidence"] += 1

    # ── T10: audit kaydı (her karar) ─────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "triggered": state == "TRIGGERED",
            "terminal": state,
            "primary_reason": decision.get("primary_reason") if decision else None,
            "trigger_class": decision.get("trigger_class") if decision else None,
            "trigger_turn": decision.get("trigger_turn") if decision else None,
            "evidence": decision.get("evidence") if decision else None,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": state,
        "triggered": state == "TRIGGERED",
        "primary_reason": decision.get("primary_reason") if decision else None,
        "trigger_class": decision.get("trigger_class") if decision else None,
        "contributing": decision.get("contributing") if decision else [],
        "trigger_turn": decision.get("trigger_turn") if decision else None,
        "evidence": decision.get("evidence") if decision else None,
        "audit": audit,
        "violations": v,
    }


def _reason_of(signal):
    """Sinyal kindinden tetik reason'ı (öncelik sıralaması için; eşit-t içinde stabil)."""
    return {"user_request": "USER_REQUEST", "policy": "POLICY",
            "sentiment": "ANGER", "confidence": "LOW_CONFIDENCE"}.get(signal.get("kind"), "")


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "user_request_ignored": "max_user_request_ignored",
        "policy_ignored": "max_policy_ignored",
        "false_trigger": "max_false_trigger",
        "wrong_precedence": "max_wrong_precedence",
        "duplicate_decision": "max_duplicate_decision",
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
        fails.append("karar/audit kaydı üretilmedi (T10)")
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
        res = evaluate(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "triggered", "primary_reason"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s triggered=%s reason=%s contributing=%s turn=%s"
              % (res["terminal"], res["triggered"], res["primary_reason"],
                 res["contributing"], res["trigger_turn"]))
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
              "trigger_classes", "thresholds", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.4", spec.get("wbs") == "9.4")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-HND-001 izlenir (kullanıcı isteği)", "FR-HND-001" in tr.get("fr", []))
    chk("FR-HND-002 izlenir (conf/öfke/politika)", "FR-HND-002" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-HND-001 izlenir", "SR-HND-001" in tr.get("srs", []))
    chk("SR-HND-002 izlenir", "SR-HND-002" in tr.get("srs", []))
    chk("TC-HND-001 izlenir", "TC-HND-001" in tr.get("rtm", []))
    chk("TC-HND-002 izlenir", "TC-HND-002" in tr.get("rtm", []))
    chk("ADR-001/002 izlenir", any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", [])))
    chk("SAD §7.3 izlenir", any("§7.3" in s for s in tr.get("sad", [])))

    # 3) Durum makinesi tutarlılığı
    st = spec["states"]
    chk("flow = 3 durum", st.get("flow") == STATES)
    chk("terminal = {TRIGGERED,NO_HANDOFF}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal = {MONITORING}", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği — her terminal erişilebilir + niteleyen-yok→NO_HANDOFF, niteleyen→TRIGGERED
    edges = spec["transitions"]["edges"]
    tos = set(e["to"] for e in edges)
    froms = set(e["from"] for e in edges)
    chk("MONITORING kaynak", "MONITORING" in froms)
    chk("TRIGGERED hedef erişilebilir", "TRIGGERED" in tos)
    chk("NO_HANDOFF hedef erişilebilir", "NO_HANDOFF" in tos)
    chk("on_triggered EMIT tanımlı", "EMIT" in spec["transitions"].get("on_triggered", ""))
    chk("on_no_handoff CLOSE tanımlı", "CLOSE" in spec["transitions"].get("on_no_handoff", ""))

    # 5) Tetik sınıfları + öncelik
    tc = spec["trigger_classes"]
    classes = {c["reason"]: c for c in tc["classes"]}
    chk("4 tetik sınıfı (USER_REQUEST/POLICY/ANGER/LOW_CONFIDENCE)", set(classes) == set(REASONS))
    chk("USER_REQUEST priority=1 mandatory", classes["USER_REQUEST"]["priority"] == 1
        and classes["USER_REQUEST"]["kind"] == "mandatory" and classes["USER_REQUEST"]["suppressible"] is False)
    chk("POLICY priority=2 mandatory bastırılamaz", classes["POLICY"]["priority"] == 2
        and classes["POLICY"]["suppressible"] is False)
    chk("ANGER priority=3 heuristic", classes["ANGER"]["priority"] == 3 and classes["ANGER"]["kind"] == "heuristic")
    chk("LOW_CONFIDENCE priority=4 heuristic", classes["LOW_CONFIDENCE"]["priority"] == 4)
    chk("USER_REQUEST→FR-HND-001", classes["USER_REQUEST"]["fr"] == "FR-HND-001")
    chk("ANGER/LOW_CONF→FR-HND-002", classes["ANGER"]["fr"] == "FR-HND-002"
        and classes["LOW_CONFIDENCE"]["fr"] == "FR-HND-002")
    chk("precedence sıralı USER>POLICY>ANGER>LOW", tc["precedence"] == REASONS)

    # 6) Eşikler — bounds + sürdürme
    th = spec["thresholds"]
    chk("low_conf_threshold ∈ [0,1]", 0.0 <= th["low_conf_threshold"] <= 1.0)
    chk("anger_threshold ∈ [0,1]", 0.0 <= th["anger_threshold"] <= 1.0)
    chk("low_conf_sustain ≥ 2 (debounce, T3)", th["low_conf_sustain_turns"] >= 2)
    chk("anger_sustain ≥ 1", th["anger_sustain_turns"] >= 1)
    chk("bounds.sustain_min ≥ 1", th["bounds"]["sustain_min"] >= 1)

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_user_request_ignored", "max_policy_ignored", "max_false_trigger",
               "max_wrong_precedence", "max_duplicate_decision", "max_missing_evidence",
               "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_trigger_total metrik", "handoff_trigger_total" in obs.get("metrics", []))
    chk("confidence_breach metrik (STT erken-uyarı)",
        "handoff_trigger_confidence_breach_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("call_id YÜKSEK kard (label değil)", "call_id" in hi and "call_id" not in lo)
    chk("correlation_id YÜKSEK kard", "correlation_id" in hi)
    chk("reason/triggered DÜŞÜK kard (label uygun)", "reason" in lo and "triggered" in lo)

    # 9) İnvariant'lar T1–T11
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar T1–T11 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/transfer-trigger-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        cth = cfg.get("thresholds", {})
        chk("config low_conf_sustain ≥ 2 (debounce)", cth.get("low_conf_sustain_turns", 0) >= 2)
        chk("config USER_REQUEST mandatory (kapatılamaz)",
            cfg.get("mandatory_reasons") and "USER_REQUEST" in cfg["mandatory_reasons"]
            and "POLICY" in cfg["mandatory_reasons"])
        chk("config emit hedefleri 9.1/9.2/9.3", set(cfg.get("emit_to", [])) >= {"9.1", "9.2", "9.3"})

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
    chk("hiç ham PII/transkript/sır sızıntısı yok (T11)", total_leaks == 0)

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

    def sig(kind, t, turn, **kw):
        d = {"kind": kind, "t": t, "turn": turn}
        d.update(kw)
        return d

    END = lambda t: {"kind": "end", "t": t}

    # 1) Kullanıcı isteği → ANINDA TRIGGERED, USER_REQUEST (T2)
    r = evaluate({"tenant_id": "t1", "correlation_id": "c1",
                  "signals": [sig("user_request", 1000, 2), END(5000)]}, spec)
    case("user-request: TRIGGERED", r["terminal"] == "TRIGGERED")
    case("user-request: reason=USER_REQUEST", r["primary_reason"] == "USER_REQUEST")
    case("user-request: mandatory sınıf", r["trigger_class"] == "mandatory")
    case("user-request: ihlal yok", all(v == 0 for v in r["violations"].values()))
    case("user-request: audit var (T10)", r["audit"] is not None and r["audit"]["triggered"] is True)

    # 2) Tek geçici düşük-conf → TETİKLEMEZ (T3 debounce), sürdürülünce tetikler
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("confidence", 1000, 1, score=0.3), sig("confidence", 2000, 2, score=0.9), END(3000)]}, spec)
    case("transient-lowconf: NO_HANDOFF (T3)", r["terminal"] == "NO_HANDOFF")
    case("transient-lowconf: false_trigger=0", r["violations"]["false_trigger"] == 0)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("confidence", 1000, 1, score=0.3), sig("confidence", 2000, 2, score=0.25), END(3000)]}, spec)
    case("sustained-lowconf: TRIGGERED LOW_CONFIDENCE", r["terminal"] == "TRIGGERED"
         and r["primary_reason"] == "LOW_CONFIDENCE")
    case("sustained-lowconf: trigger_turn=2", r["trigger_turn"] == 2)

    # 3) Öfke eşik+sürdürme (T4)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("sentiment", 1000, 1, anger=0.8), sig("sentiment", 2000, 2, anger=0.3), END(3000)]}, spec)
    case("transient-anger: NO_HANDOFF (T4)", r["terminal"] == "NO_HANDOFF")
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("sentiment", 1000, 1, anger=0.85), sig("sentiment", 2000, 2, anger=0.9), END(3000)]}, spec)
    case("sustained-anger: TRIGGERED ANGER", r["terminal"] == "TRIGGERED" and r["primary_reason"] == "ANGER")

    # 4) Politika → ANINDA TRIGGERED POLICY (T5)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("policy", 1500, 3, rule="rule-compliance-kyc"), END(4000)]}, spec)
    case("policy: TRIGGERED POLICY", r["terminal"] == "TRIGGERED" and r["primary_reason"] == "POLICY")
    case("policy: evidence rule taşır (T9)", r["evidence"].get("rule") == "rule-compliance-kyc")

    # 5) Sağlıklı konuşma → NO_HANDOFF (T7)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("confidence", 1000, 1, score=0.95), sig("sentiment", 1000, 1, anger=0.1),
        sig("confidence", 2000, 2, score=0.9), END(3000)]}, spec)
    case("healthy: NO_HANDOFF (T7)", r["terminal"] == "NO_HANDOFF")
    case("healthy: triggered=False", r["triggered"] is False)
    case("healthy: ihlal yok", all(v == 0 for v in r["violations"].values()))

    # 6) Öncelik: aynı turda user_request + sürdürülen düşük-conf → primary USER_REQUEST (T6)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("confidence", 1000, 1, score=0.3),
        sig("confidence", 2000, 2, score=0.3), sig("user_request", 2000, 2),
        END(3000)]}, spec)
    case("precedence: primary=USER_REQUEST", r["primary_reason"] == "USER_REQUEST")
    case("precedence: contributing iki reason", set(r["contributing"]) == {"USER_REQUEST", "LOW_CONFIDENCE"})
    case("precedence: wrong_precedence=0", r["violations"]["wrong_precedence"] == 0)

    # 7) İlk-niteleyen LATCH: önce öfke tetikler, sonraki politika ikinci karar ÜRETMEZ (T8)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("sentiment", 1000, 1, anger=0.85), sig("sentiment", 2000, 2, anger=0.9),
        sig("policy", 3000, 3, rule="rule-x"), END(4000)]}, spec)
    case("latch: primary=ANGER (ilk niteleyen)", r["primary_reason"] == "ANGER")
    case("latch: duplicate_decision=0", r["violations"]["duplicate_decision"] == 0)

    # 8) inject suppress_user_request → user_request_ignored (T2 ihlali)
    r = evaluate({"tenant_id": "t1", "signals": [sig("user_request", 1000, 1), END(2000)]},
                 spec, inject=["suppress_user_request"])
    case("inject-suppress: user_request_ignored>0", r["violations"]["user_request_ignored"] > 0)

    # 9) inject ignore_policy → policy_ignored (T5 ihlali)
    r = evaluate({"tenant_id": "t1", "signals": [sig("policy", 1000, 1, rule="r"), END(2000)]},
                 spec, inject=["ignore_policy"])
    case("inject-ignore-policy: policy_ignored>0", r["violations"]["policy_ignored"] > 0)

    # 10) inject no_debounce → tek geçici düşük-conf tetikler → false_trigger (T3 ihlali)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("confidence", 1000, 1, score=0.3), sig("confidence", 2000, 2, score=0.95), END(3000)]},
        spec, inject=["no_debounce"])
    case("inject-no-debounce: false_trigger>0", r["violations"]["false_trigger"] > 0)
    case("inject-no-debounce: TRIGGERED turn=1", r["terminal"] == "TRIGGERED" and r["trigger_turn"] == 1)

    # 11) inject wrong_precedence → primary en düşük öncelik (T6 ihlali)
    r = evaluate({"tenant_id": "t1", "signals": [
        sig("confidence", 1000, 1, score=0.3),
        sig("confidence", 2000, 2, score=0.3), sig("user_request", 2000, 2), END(3000)]},
        spec, inject=["wrong_precedence"])
    case("inject-wrong-prec: wrong_precedence>0", r["violations"]["wrong_precedence"] > 0)
    case("inject-wrong-prec: primary=LOW_CONFIDENCE", r["primary_reason"] == "LOW_CONFIDENCE")

    # 12) inject retrigger → duplicate_decision (T8 ihlali)
    r = evaluate({"tenant_id": "t1", "signals": [sig("user_request", 1000, 1), END(2000)]},
                 spec, inject=["retrigger"])
    case("inject-retrigger: duplicate_decision>0", r["violations"]["duplicate_decision"] > 0)

    # 13) inject no_audit → missing_audit (T10 ihlali)
    r = evaluate({"tenant_id": "t1", "signals": [sig("user_request", 1000, 1), END(2000)]},
                 spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 14) Determinizm: aynı girdi → aynı sonuç
    s = {"tenant_id": "t1", "correlation_id": "c",
         "signals": [sig("sentiment", 1000, 1, anger=0.85), sig("sentiment", 2000, 2, anger=0.9), END(3000)]}
    r1 = evaluate(s, spec)
    r2 = evaluate(s, spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 15) Kapı entegrasyonu: healthy geçer, suppress eler
    rp = evaluate({"tenant_id": "t1", "signals": [sig("confidence", 1000, 1, score=0.95), END(2000)]}, spec)
    rf = evaluate({"tenant_id": "t1", "signals": [sig("user_request", 1000, 1), END(2000)]},
                  spec, inject=["suppress_user_request"])
    case("kapı: healthy geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: suppress-user-request eler", _gate_eval(rf, G)[0] is False)

    # 16) Sızıntı tarayıcı: yapısal kimlik temiz, ham metin/numara yakalanır
    case("leak: rule-x temiz", scan_leaks('{"rule": "rule-x"}') == [])
    case("leak: utterance alanı yakalanır", len(scan_leaks('{"utterance": "müşteri kızgın"}')) > 0)
    case("leak: ham numara yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    # 17) config_override sürdürme penceresini sıkılaştırır (3 tur gerekir)
    r = evaluate({"tenant_id": "t1", "config_override": {"low_conf_sustain_turns": 3},
                  "signals": [sig("confidence", 1000, 1, score=0.3),
                              sig("confidence", 2000, 2, score=0.3), END(3000)]}, spec)
    case("override: 2 tur ile NO_HANDOFF (3 gerek)", r["terminal"] == "NO_HANDOFF")

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "transfer-triggers (WBS 9.4 — FR-HND-001/002 transfer tetikleyiciler)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "trigger_classes": REASONS,
        "precedence (yüksek→düşük)": REASONS,
        "mandatory (bastırılamaz)": sorted(MANDATORY),
        "signal_kinds": sorted(SIGNAL_KINDS),
        "signal_fields": {
            "user_request": "{t, turn}",
            "policy": "{t, turn, rule}",
            "sentiment": "{t, turn, anger[0..1]}",
            "confidence": "{t, turn, score[0..1]}",
            "end": "{t}",
        },
        "sample_fields": ["name", "tenant_id", "correlation_id", "call_id",
                          "config_override{}", "signals[]", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["triggered", "primary_reason", "trigger_class", "contributing[]",
                            "trigger_turn", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-HND-001/002, FR-HND-008, SR-HND-001/002, TC-HND-001/002, SAD §7.3, BRD §9.12, ADR-001/002",
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
            print("kullanım: transfer_triggers_probe.py run <sample.json|dizin>")
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
