#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 9.5 — Kuyruk/skill/departman bazlı hedef seçimi referans probe.

9. workstream'in (İnsan Temsilciye Aktarım) BEŞİNCİ modülü ve F2-Must aktarım çekirdeği.
FR-TEL-008 (kuyruk/skill/departman bazlı aktarım) + FR-HND-003 (doğru departman+skill grubu
seçimi) HEDEF SEÇİMİNİ sahiplenir. SAD §7.3 'Handoff Manager ──► hedef seçimi (departman/skill/
kuyruk)' noktasıdır. 9.4 (tetikleyiciler) NE ZAMAN/NEDEN kararını üretir; bu modül NEREYE kararını
üretir; 9.1/9.2/9.3 (cold/warm/whisper) bu HEDEFİ taşıma için TÜKETİR. Modül bir HEDEF SEÇİM
MOTORUdur (deterministik):

  SELECTING ──(kuyruk eşleşti)──────► SELECTED     (terminal — EMIT hedef → 9.1/9.2/9.3, R3 üç boyut)
      │
      └─(hiç eşleşme + default yok)─► UNRESOLVED   (terminal — fail-safe 9.7'ye yükselt, R10)

Üç yönlendirme boyutu (FR-TEL-008): department + skill_group + queue — seçilen hedef ÜÇÜNÜ taşır.
Sıralı fallback zinciri (R5): exact (skill+dil kapsayan) → department_default (skill gevşek, dil) →
general_fallback (tenant genel catch-all). Öncelik (R6): 9.4 reason → high (öfke/politika) / normal.

ÇEKİRDEK INVARIANT (BRD §9.12 + SR-TEL-008/SR-HND-003): doğru departman (R2); seçilen kuyruk gerekli
skill'i kapsar (R4); fallback fail-safe (R5); öncelik deterministik (R6); tenant izolasyonu (R7);
her hedef kanıt taşır (R8); her karar audit (R9); UNRESOLVED→9.7 fail-safe (R10).

Kapsam dışı (bilinçli, başka modül SAHİBİ): aktarım MEKANİZMASI → 9.1/9.2/9.3 (hedefi TÜKETİR);
tetikleme kararı → 9.4 (reason'ı TÜKETİR); bağlam paketi → 9.6; temsilci-yok fallback → 9.7
(UNRESOLVED'i YÜKSELTİR); raporlama → 9.8; intent ÜRETİMİ → NLU (3.x); dil tespiti → STT (4.x);
kuyruk/skill envanteri CRUD → L1/A-* panel; canlı temsilci atama → CC (11.x); audit store → 7.1.6/12.1.8.

Kullanım:
  target_selection_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  target_selection_probe.py run <sample>       Seçim motoru: hedef senaryo(lar)ını çalıştır → kapı (R1–R11)
  target_selection_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  target_selection_probe.py schema             Durum/istek/karar sözleşmesini yazdır

Determinizm: sanal zaman + yapısal kimlikler; Date.now/gerçek-rastgele YOK. Stdlib-only.
Sır/credential ve gerçek PII (müşteri adı/telefon/transkript) üretilmez/yazılmaz (fixture sentetik — FR-TST-008).
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "target-selection-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "routing-policies.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

STATES = ["SELECTING", "SELECTED", "UNRESOLVED"]
NON_TERMINAL = {"SELECTING"}
TERMINAL = {"SELECTED", "UNRESOLVED"}
DIMENSIONS = ["department", "skill_group", "queue"]
MATCH_QUALITY = ["exact", "department_default", "general_fallback"]
PRIORITY_LEVELS = ["high", "normal"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11"]
INJECTIONS = {"wrong_department", "skill_mismatch", "no_fallback",
              "ignore_priority", "cross_tenant_target", "no_audit"}

VIOLATION_KEYS = [
    "wrong_department", "mis_skill", "missing_dimension", "broken_fallback", "priority_ignored",
    "cross_tenant_target", "missing_evidence", "missing_audit", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R11; 9.1–9.4 deseniyle) — müşteri adı/telefon/hesap no/ham transkript yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("phone_long", re.compile(r"\b\d{10,15}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # ham müşteri içeriği alanı (yalnız yapısal kimlik/etiket taşımalı)
    ("pii_field", re.compile(r"(?i)\"(customer_name|customer_phone|account_number|transcript_text|utterance|caller_name)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|rule-|q-|sg-|lang:|domain:|tier:|corr-|call-)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham PII / sır tarayıcı. Yorum/tarif satırı + rezerve test bloğunu eler (1.1.8 deseni)."""
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
# Hedef seçim motoru — RoutingRequest'i yönlendirme kurallarından geçirir.
# ════════════════════════════════════════════════════════════════════════════
def _config_from(sample, spec):
    """Config = ana routing-policies.json; sample.config_override yapısal alanları geçersiz kılabilir."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("queues", "skill_groups", "intent_to_department", "intent_skills",
              "priority_rules", "tenant_general_queue", "default_department"):
        if k in ov:
            cfg[k] = ov[k]
    return cfg


def _skills_of(cfg, skill_group):
    sg = cfg.get("skill_groups", {})
    val = sg.get(skill_group, [])
    return set(v for v in val if v != "$comment") if isinstance(val, list) else set()


def select(sample, spec, inject=None, cfg=None):
    """Tek hedef-seçim senaryosunu yürüt → TargetSelection + ihlal sayaçları.

    Motor DOĞRU davranışı hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen
    ihlal sayacını artırır (9.1–9.4 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config_from(sample, spec)
    tenant = sample.get("tenant_id")

    intent = sample.get("intent")
    language = sample.get("language")
    reason = sample.get("reason")
    req_skills = set(sample.get("required_skills", []))
    req_skills |= set(cfg.get("intent_skills", {}).get(intent, []) or [])
    if language:
        req_skills.add("lang:" + language)
    req_skills.discard("$comment")

    queues = [q for q in cfg.get("queues", []) if isinstance(q, dict) and q.get("id")]
    own_queue_ids = {q["id"] for q in queues}

    v = {k: 0 for k in VIOLATION_KEYS}

    # ── 1) Departman çöz (R2) ────────────────────────────────────────────────────────
    correct_dept = cfg.get("intent_to_department", {}).get(intent, cfg.get("default_department", "general"))
    dept = correct_dept
    if "wrong_department" in inject:
        others = sorted(d for d in cfg.get("departments", []) if d != correct_dept)
        if others:
            dept = others[0]
            v["wrong_department"] += 1

    # ── 2) Öncelik çöz (R6) ──────────────────────────────────────────────────────────
    correct_priority = cfg.get("priority_rules", {}).get(reason, cfg.get("priority_model_default", "normal"))
    if isinstance(correct_priority, str) is False:
        correct_priority = "normal"
    priority = correct_priority
    if "ignore_priority" in inject and correct_priority != "normal":
        priority = "normal"
        v["priority_ignored"] += 1

    def covers(q):
        return _skills_of(cfg, q.get("skill_group")) >= req_skills

    def lang_ok(q):
        return (not language) or (language in q.get("languages", []))

    fallback_disabled = "no_fallback" in inject
    fallback_tried = []
    selected = None
    match_quality = None

    # ── 3) exact tier: skill (dil dahil) kapsayan + dili destekleyen kuyruk ───────────
    fallback_tried.append("exact")
    exact = [q for q in queues if q.get("department") == dept and covers(q) and lang_ok(q)]
    if exact:
        # En sıkı skill eşleşmesi tercih edilir (fazladan skill sayısı az = aşırı-yetkin
        # kuyruğu boşa harcama): high önceliklü istekte priority_capable kuyruk öne alınır.
        def _extra(q):
            return len(_skills_of(cfg, q.get("skill_group")) - req_skills)
        if priority == "high":
            exact.sort(key=lambda q: (0 if q.get("priority_capable") else 1, _extra(q), q["id"]))
        else:
            exact.sort(key=lambda q: (_extra(q), q["id"]))
        selected, match_quality = exact[0], "exact"

    # ── 4) department_default tier: skill gevşetilir, dil kontrol ─────────────────────
    if selected is None and not fallback_disabled:
        fallback_tried.append("department_default")
        dd = sorted((q for q in queues if q.get("department") == dept
                     and q.get("is_department_default") and lang_ok(q)),
                    key=lambda q: q["id"])
        if dd:
            selected, match_quality = dd[0], "department_default"

    # ── 5) general_fallback tier: tenant genel catch-all ──────────────────────────────
    if selected is None and not fallback_disabled:
        fallback_tried.append("general_fallback")
        gen_id = cfg.get("tenant_general_queue")
        gen = [q for q in queues if q.get("id") == gen_id and lang_ok(q)]
        if gen:
            selected, match_quality = gen[0], "general_fallback"

    # ── broken_fallback tespiti (R5): default eşleşebilirken fallback devre dışı ──────
    would_fallback = bool(
        [q for q in queues if q.get("department") == dept and q.get("is_department_default") and lang_ok(q)]
        or [q for q in queues if q.get("id") == cfg.get("tenant_general_queue") and lang_ok(q)])
    if selected is None and fallback_disabled and would_fallback:
        v["broken_fallback"] += 1

    # ── inject skill_mismatch: gerekli skill'i taşımayan kuyruğu exact diye seç ───────
    if "skill_mismatch" in inject:
        bad = sorted((q for q in queues if q.get("department") == dept and not covers(q)),
                     key=lambda q: q["id"])
        if bad:
            selected, match_quality = bad[0], "exact"   # yanlış etiketleme

    # ── inject cross_tenant_target: başka tenant'ın kuyruğunu seç ─────────────────────
    if "cross_tenant_target" in inject:
        selected = {"id": "q-foreigntenant-billing", "department": dept,
                    "skill_group": "sg-foreign", "languages": [language] if language else [],
                    "_foreign": True}
        match_quality = "exact"

    terminal = "SELECTED" if selected is not None else "UNRESOLVED"

    # ── İhlal tespitleri (seçilen hedef üzerinde) ─────────────────────────────────────
    if terminal == "SELECTED":
        # R3 — üç boyut (department/skill_group/queue) eksiksiz
        if not (selected.get("department") and selected.get("skill_group") and selected.get("id")):
            v["missing_dimension"] += 1
        # R7 — cross-tenant: yabancı veya bu tenant config'inde olmayan kuyruk
        if selected.get("_foreign") or selected.get("id") not in own_queue_ids:
            v["cross_tenant_target"] += 1
        # R4 — exact etiketli ama gerekli skill'i kapsamayan (yabancı kuyruk ayrı sayılır)
        elif match_quality == "exact" and not (_skills_of(cfg, selected.get("skill_group")) >= req_skills):
            v["mis_skill"] += 1

    # ── Kanıt (R8) ────────────────────────────────────────────────────────────────────
    evidence = {
        "intent": intent,
        "matched_department_rule": correct_dept,
        "required_skills": sorted(req_skills),
        "match_quality": match_quality,
        "fallback_tried": fallback_tried,
        "language": language,
        "priority": priority,
        "reason": reason,
    }
    if terminal == "SELECTED" and not evidence.get("match_quality"):
        v["missing_evidence"] += 1

    # ── Audit (R9) ──────────────────────────────────────────────────────────────────
    audit = None
    if "no_audit" in inject:
        v["missing_audit"] += 1
    else:
        audit = {
            "terminal": terminal,
            "department": selected.get("department") if selected else None,
            "skill_group": selected.get("skill_group") if selected else None,
            "queue": selected.get("id") if selected else None,
            "priority": priority,
            "match_quality": match_quality,
            "escalated_to": cfg.get("unresolved_to", {}).get("to") if terminal == "UNRESOLVED" else None,
            "correlation_id": sample.get("correlation_id"),
            "tenant_id": tenant,
        }

    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal == "SELECTED",
        "department": selected.get("department") if selected else None,
        "skill_group": selected.get("skill_group") if selected else None,
        "queue": selected.get("id") if selected else None,
        "priority": priority,
        "match_quality": match_quality,
        "fallback_tried": fallback_tried,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "wrong_department": "max_wrong_department",
        "mis_skill": "max_mis_skill",
        "missing_dimension": "max_missing_dimension",
        "broken_fallback": "max_broken_fallback",
        "priority_ignored": "max_priority_ignored",
        "cross_tenant_target": "max_cross_tenant_target",
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
        fails.append("karar/audit kaydı üretilmedi (R9)")
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
        res = select(sample, spec)
        with open(p, "r", encoding="utf-8") as fh:
            leaks = scan_leaks(fh.read())
        if leaks:
            res["violations"]["secret_or_pii"] += len(leaks)
        passed, fails = _gate_eval(res, gates)

        exp_assert = sample.get("expected", {})
        mism = []
        for key in ("terminal", "resolved", "department", "skill_group", "queue", "priority", "match_quality"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s dept=%s skill=%s queue=%s prio=%s match=%s"
              % (res["terminal"], res["department"], res["skill_group"],
                 res["queue"], res["priority"], res["match_quality"]))
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
              "routing_dimensions", "fallback_chain", "priority_model", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=9.5", spec.get("wbs") == "9.5")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEL-008 izlenir (kuyruk/skill/departman)", "FR-TEL-008" in tr.get("fr", []))
    chk("FR-HND-003 izlenir (doğru departman+skill)", "FR-HND-003" in tr.get("fr", []))
    chk("FR-HND-007 izlenir (temsilci-yok fallback)", "FR-HND-007" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-TEL-008 izlenir", "SR-TEL-008" in tr.get("srs", []))
    chk("SR-HND-003 izlenir", "SR-HND-003" in tr.get("srs", []))
    chk("TC-TEL-008 izlenir", "TC-TEL-008" in tr.get("rtm", []))
    chk("TC-HND-003 izlenir", "TC-HND-003" in tr.get("rtm", []))
    chk("ADR-001/002 izlenir", any("ADR-001" in a for a in tr.get("adr", []))
        and any("ADR-002" in a for a in tr.get("adr", [])))
    chk("SAD §7.3 izlenir", any("§7.3" in s for s in tr.get("sad", [])))

    # 3) Durum makinesi tutarlılığı
    st = spec["states"]
    chk("flow = 3 durum", st.get("flow") == STATES)
    chk("terminal = {SELECTED,UNRESOLVED}", set(st.get("terminal", [])) == TERMINAL)
    chk("non_terminal = {SELECTING}", set(st.get("non_terminal", [])) == NON_TERMINAL)

    # 4) Geçiş grafiği
    edges = spec["transitions"]["edges"]
    tos = set(e["to"] for e in edges)
    froms = set(e["from"] for e in edges)
    chk("SELECTING kaynak", "SELECTING" in froms)
    chk("SELECTED hedef erişilebilir", "SELECTED" in tos)
    chk("UNRESOLVED hedef erişilebilir", "UNRESOLVED" in tos)
    chk("on_selected EMIT tanımlı", "EMIT" in spec["transitions"].get("on_selected", ""))
    chk("on_unresolved ESCALATE→9.7 tanımlı",
        "ESCALATE" in spec["transitions"].get("on_unresolved", "")
        and "9.7" in spec["transitions"].get("on_unresolved", ""))

    # 5) Yönlendirme boyutları (FR-TEL-008) + fallback zinciri + öncelik
    rd = spec["routing_dimensions"]
    chk("üç boyut department/skill_group/queue", rd.get("dimensions") == DIMENSIONS)
    fc = spec["fallback_chain"]
    chk("fallback tier'ları exact→dept_default→general", fc.get("tiers") == MATCH_QUALITY)
    chk("match_quality sırası tutarlı", fc.get("match_quality_order") == MATCH_QUALITY)
    pm = spec["priority_model"]
    chk("öncelik seviyeleri high/normal", set(pm.get("levels", [])) == set(PRIORITY_LEVELS))
    chk("ANGER→high (öncelik kuralı)", pm.get("reason_to_priority", {}).get("ANGER") == "high")
    chk("POLICY→high (öncelik kuralı)", pm.get("reason_to_priority", {}).get("POLICY") == "high")

    # 6) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_wrong_department", "max_mis_skill", "max_missing_dimension", "max_broken_fallback",
               "max_priority_ignored", "max_cross_tenant_target", "max_missing_evidence",
               "max_missing_audit", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 7) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("handoff_target_total metrik", "handoff_target_total" in obs.get("metrics", []))
    chk("handoff_target_fallback_total metrik (skill boşluğu erken-uyarı)",
        "handoff_target_fallback_total" in obs.get("metrics", []))
    chk("cross_tenant_blocked metrik (güvenlik)",
        "handoff_target_cross_tenant_blocked_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("queue_id YÜKSEK kard (label değil)", "queue_id" in hi and "queue_id" not in lo)
    chk("correlation_id YÜKSEK kard", "correlation_id" in hi)
    chk("department/match_quality DÜŞÜK kard (label uygun)",
        "department" in lo and "match_quality" in lo)

    # 8) İnvariant'lar R1–R11
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R11 tam", inv_ids == INVARIANT_IDS)

    # 9) Config dosyası — envanter + kurallar
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/routing-policies.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        queues = [q for q in cfg.get("queues", []) if isinstance(q, dict)]
        chk("config kuyruk envanteri ≥3", len(queues) >= 3)
        chk("her kuyruk üç boyut taşır (id/department/skill_group)",
            all(q.get("id") and q.get("department") and q.get("skill_group") for q in queues))
        chk("kuyruk departmanları config.departments içinde",
            all(q.get("department") in cfg.get("departments", []) for q in queues))
        chk("kuyruk skill_group'ları tanımlı",
            all(q.get("skill_group") in cfg.get("skill_groups", {}) for q in queues))
        chk("tenant_general_queue tanımlı kuyruk",
            cfg.get("tenant_general_queue") in {q.get("id") for q in queues})
        chk("≥1 department_default kuyruk (fallback)",
            any(q.get("is_department_default") for q in queues))
        chk("config emit hedefleri 9.1/9.2/9.3", set(cfg.get("emit_to", [])) >= {"9.1", "9.2", "9.3"})
        chk("config unresolved→9.7 (FR-HND-007)", cfg.get("unresolved_to", {}).get("to") == "9.7")
        chk("config ANGER/POLICY→high öncelik",
            cfg.get("priority_rules", {}).get("ANGER") == "high"
            and cfg.get("priority_rules", {}).get("POLICY") == "high")

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
    chk("hiç müşteri-PII/transkript/sır sızıntısı yok (R11)", total_leaks == 0)

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
        d = {"tenant_id": "t1", "correlation_id": "c1"}
        d.update(kw)
        return d

    # 1) exact skill+dil — billing_dispute + tr → q-billing-tr (R2/R3/R4)
    r = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"), spec)
    case("exact: SELECTED", r["terminal"] == "SELECTED")
    case("exact: department=billing (R2)", r["department"] == "billing")
    case("exact: skill_group=sg-billing-tr", r["skill_group"] == "sg-billing-tr")
    case("exact: queue=q-billing-tr", r["queue"] == "q-billing-tr")
    case("exact: match_quality=exact", r["match_quality"] == "exact")
    case("exact: üç boyut dolu (R3)", all(r[d] for d in ("department", "skill_group", "queue")))
    case("exact: ihlal yok", all(v == 0 for v in r["violations"].values()))
    case("exact: audit var (R9)", r["audit"] is not None and r["audit"]["queue"] == "q-billing-tr")

    # 2) dil yönlendirmesi — billing_dispute + en → q-billing-en
    r = select(req(intent="billing_dispute", language="en", reason="USER_REQUEST"), spec)
    case("lang-en: queue=q-billing-en", r["queue"] == "q-billing-en" and r["match_quality"] == "exact")

    # 3) department_default — tech_support + en (exact tr-kuyruk yok) → q-tech-default (R5)
    r = select(req(intent="tech_support", language="en", reason="USER_REQUEST"), spec)
    case("dept-default: department=tech (R2)", r["department"] == "tech")
    case("dept-default: queue=q-tech-default", r["queue"] == "q-tech-default")
    case("dept-default: match_quality=department_default", r["match_quality"] == "department_default")
    case("dept-default: ihlal yok", all(v == 0 for v in r["violations"].values()))

    # 4) general_fallback — bilinmeyen intent → q-general (R5)
    r = select(req(intent="general_inquiry", language="tr", reason="USER_REQUEST"), spec)
    case("general: department=general", r["department"] == "general")
    case("general: queue=q-general", r["queue"] == "q-general")
    case("general: match_quality=general_fallback", r["match_quality"] == "general_fallback")

    # 5) öncelik — tech_support + tr + ANGER → priority high, priority_capable kuyruk q-tech-z (R6)
    r = select(req(intent="tech_support", language="tr", reason="ANGER"), spec)
    case("priority: priority=high (ANGER→high)", r["priority"] == "high")
    case("priority: queue=q-tech-z (priority_capable tercih)", r["queue"] == "q-tech-z")
    case("priority: priority_ignored=0", r["violations"]["priority_ignored"] == 0)
    # normal öncelik → id-sırası q-tech-a
    r2 = select(req(intent="tech_support", language="tr", reason="LOW_CONFIDENCE"), spec)
    case("priority: normal→q-tech-a (id sırası)", r2["priority"] == "normal" and r2["queue"] == "q-tech-a")

    # 6) çoklu skill (tier:premium) — yalnız premium kuyruk kapsar
    r = select(req(intent="billing_dispute", language="tr", required_skills=["tier:premium"],
                   reason="USER_REQUEST"), spec)
    case("multi-skill: queue=q-billing-premium-tr", r["queue"] == "q-billing-premium-tr")
    case("multi-skill: mis_skill=0", r["violations"]["mis_skill"] == 0)

    # 7) inject wrong_department → wrong_department (R2 ihlali)
    r = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"),
               spec, inject=["wrong_department"])
    case("inject-wrong-dept: wrong_department>0", r["violations"]["wrong_department"] > 0)
    case("inject-wrong-dept: department != billing", r["department"] != "billing")

    # 8) inject skill_mismatch → mis_skill (R4 ihlali)
    r = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"),
               spec, inject=["skill_mismatch"])
    case("inject-skill-mismatch: mis_skill>0", r["violations"]["mis_skill"] > 0)

    # 9) inject no_fallback → broken_fallback (R5 ihlali) — tech_support+en dept_default'a düşmeli
    r = select(req(intent="tech_support", language="en", reason="USER_REQUEST"),
               spec, inject=["no_fallback"])
    case("inject-no-fallback: UNRESOLVED", r["terminal"] == "UNRESOLVED")
    case("inject-no-fallback: broken_fallback>0", r["violations"]["broken_fallback"] > 0)

    # 10) inject ignore_priority → priority_ignored (R6 ihlali)
    r = select(req(intent="tech_support", language="tr", reason="ANGER"),
               spec, inject=["ignore_priority"])
    case("inject-ignore-priority: priority_ignored>0", r["violations"]["priority_ignored"] > 0)
    case("inject-ignore-priority: priority=normal (yanlış)", r["priority"] == "normal")

    # 11) inject cross_tenant_target → cross_tenant_target (R7 ihlali)
    r = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"),
               spec, inject=["cross_tenant_target"])
    case("inject-cross-tenant: cross_tenant_target>0", r["violations"]["cross_tenant_target"] > 0)
    case("inject-cross-tenant: queue tenant config'inde değil", r["queue"] not in {
        q["id"] for q in _load(CONFIG_PATH)["queues"] if isinstance(q, dict)})

    # 12) inject no_audit → missing_audit (R9 ihlali)
    r = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"),
               spec, inject=["no_audit"])
    case("inject-no-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("inject-no-audit: audit None", r["audit"] is None)

    # 13) gerçek UNRESOLVED (config break DEĞİL) — desteksiz dil → fail-safe, broken_fallback=0 (R10)
    r = select(req(intent="billing_dispute", language="de", reason="USER_REQUEST"), spec)
    case("unsupported-lang: UNRESOLVED (R10)", r["terminal"] == "UNRESOLVED")
    case("unsupported-lang: broken_fallback=0 (gerçek no-target)", r["violations"]["broken_fallback"] == 0)
    case("unsupported-lang: audit escalated_to=9.7", r["audit"]["escalated_to"] == "9.7")

    # 14) determinizm: aynı girdi → aynı sonuç
    s = req(intent="tech_support", language="tr", reason="ANGER")
    r1 = select(s, spec)
    r2 = select(s, spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))

    # 15) kapı entegrasyonu: exact geçer, cross-tenant eler
    rp = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"), spec)
    rf = select(req(intent="billing_dispute", language="tr", reason="USER_REQUEST"),
                spec, inject=["cross_tenant_target"])
    case("kapı: exact geçer", _gate_eval(rp, G)[0] is True)
    case("kapı: cross-tenant eler", _gate_eval(rf, G)[0] is False)

    # 16) sızıntı tarayıcı: yapısal kimlik temiz, ham PII alanı yakalanır
    case("leak: q-billing-tr temiz", scan_leaks('{"queue": "q-billing-tr"}') == [])
    case("leak: lang:tr temiz", scan_leaks('{"required_skills": ["lang:tr"]}') == [])
    case("leak: customer_phone alanı yakalanır", len(scan_leaks('{"customer_phone": "905551234567"}')) > 0)
    case("leak: ham numara yakalanır", len(scan_leaks('{"x": "905551234567"}')) > 0)

    # 17) evidence — fallback_tried + match_quality taşır (R8)
    r = select(req(intent="tech_support", language="en", reason="USER_REQUEST"), spec)
    case("evidence: fallback_tried exact+dept_default içerir",
         "exact" in r["evidence"]["fallback_tried"] and "department_default" in r["evidence"]["fallback_tried"])
    case("evidence: required_skills domain:tech taşır", "domain:tech" in r["evidence"]["required_skills"])

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "target-selection (WBS 9.5 — FR-TEL-008/FR-HND-003 kuyruk/skill/departman hedef seçimi)",
        "states": STATES,
        "non_terminal": sorted(NON_TERMINAL),
        "terminal": sorted(TERMINAL),
        "routing_dimensions": DIMENSIONS,
        "fallback_chain (sıra)": MATCH_QUALITY,
        "priority_levels": PRIORITY_LEVELS,
        "request_fields": ["name", "tenant_id", "correlation_id", "call_id", "intent",
                           "language", "required_skills[]", "reason (9.4'ten)", "attributes{}",
                           "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["resolved", "department", "skill_group", "queue", "priority",
                            "match_quality", "fallback_tried[]", "evidence", "audit"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "trace": "FR-TEL-008/FR-HND-003, FR-HND-007, SR-TEL-008/SR-HND-003, TC-TEL-008/TC-HND-003, SAD §7.3, BRD §9.12, ADR-001/002",
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
            print("kullanım: target_selection_probe.py run <sample.json|dizin>")
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
