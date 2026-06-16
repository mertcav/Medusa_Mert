#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.1 — TIER A (metrik/log, PII YOK): break-glass'SIZ L0 erişimi + AUDIT referans probe.

12. workstream'in (IAM & Erişim) ÜÇ KATMANLI BREAK-GLASS'ın EN DÜŞÜK KATMANI (Tier A) modülü ve F1-Must
yeteneği. BRD §17.7 ('Tier A — metrik/log [PII yok]: Break-glass gerekmez; normal L0 erişimi + audit') +
SAD §14.4.2 (aynı) + FR-IAM-009 (üç katmanlı break-glass) + FR-IAM-006/FR-REC-009 (tüm L0 erişimi audit'lenir).
ALTIN KURAL (BRD §17): L0 (platform) tenant'ın iş içeriğini (çağrı kaydı/transkript/müşteri/PII) VARSAYILAN
GÖREMEZ — yalnız metrik/kaynak verisi. Bir L0AccessRequest alır → DETERMİNİSTİK, FAIL-CLOSED bir Tier kararı
verir:

    TIER_A_GRANT   — PII'siz sınıf (tenant_metric/platform/global_reference): break-glass GEREKMEZ + ZORUNLU
                     audit (normal L0 erişimi + audit).
    ESCALATE_TIER_B — içerik/PII (tenant_content): break-glass GEREKİR; akış 12.3.2/3/4'e DELEGE (burada
                      SUNULMAZ).
    DENY           — malformed / tenant_config (L0 yolu yok) / sınıflandırılamayan → fail-closed.

ÇEKİRDEK:
  (1) R3 NO PII UNDER TIER A — TIER_A_GRANT YALNIZ PII'siz sınıflara verilir; içerik/PII (tenant_content)
      ASLA Tier A'da sunulmaz (pii_under_tier_a=0; altın kural FR-IAM-008/009).
  (2) R4 AUDIT EMITTED / SESSİZ ERİŞİM YOK — her TIER_A_GRANT (ve her L0 erişim kararı) DEĞİŞMEZ (WORM) bir
      audit kaydı üretir (unaudited_access=0; FR-IAM-009 '+ audit', FR-REC-009, FR-IAM-006; 12.1.8 RESİPROKAL).
  (3) R5 NO BREAK-GLASS BYPASS — içerik/PII Tier A'dan geçemez; break-glass yolunu (12.3.2/3/4) atlayan içerik
      erişimi yok (break_glass_bypass=0).

      L0AccessRequest ─malformed─► classification ─► tier ─► admission ─► audit ─► (pii/bypass/escalation/...)
            │              │              │            │          │         │
            │   ├─ request_id / actor_role / data_class+resource_type eksik|geçersiz ──► DENY (malformed)
            │   ├─ data_class bilinmiyor → fail-closed DENY; zorla kabul ─────────────► unclassified_access [R2]
            │   ├─ tier A (PII'siz) → TIER_A_GRANT; tenant_content → ESCALATE_TIER_B; tenant_config → DENY
            │   ├─ TIER_A_GRANT ∧ data_class∈content ───────────────────────────────► pii_under_tier_a [R3]
            │   ├─ content ∧ terminal=TIER_A_GRANT (break-glass atlandı) ────────────► break_glass_bypass [R5]
            │   ├─ content ∧ silent-drop (escalate yerine DENY) ────────────────────► escalation_error [R6]
            │   ├─ TIER_A_GRANT ∧ audit_emitted=False ─────────────────────────────► unaudited_access [R4]
            │   ├─ audit kaydı ham PII taşır ──────────────────────────────────────► audit_pii [R7]
            │   └─ emitilen audit değiştirildi (row_hash uyumsuz) ──────────────────► audit_mutable [R8]

Tier A break-glass token / maker-checker / gerekçe kodu GEREKTİRMEZ (bunlar Tier B; 12.3.2/3/4) — Tier A'da
işlenen bir Tier B artefaktı = tier_confusion [R9]. Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK;
model_hash sha256; audit occurred_tick sanal-saat tamsayı). Her karar terminal (R1) + kanıt + model bütünlük
manifesti (R10); metrik düşük-kardinalite + ham PII yok (R11); model/spec/sample ham içerik/PII/credential
tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): Tier B AKIŞI (maker-checker + time-boxed token + gerekçe kodu +
bildirim) → 12.3.2/12.3.3; regüle tenant require_tenant_approval toggle + DPA → 12.3.4; rol→permission-key/scope
→ 12.1.1/12.1.3; design-time repo/grant bağımsızlığı → 12.2.4; HTTP guard/RLS çalışma-anı → 12.2.1/12.2.3;
append-only/WORM audit hash-zinciri → 12.1.8 (CONSUMED RESİPROKAL). KAYNAK DOĞRULUK; çelişkide BRD §17.7 /
SAD §14.4.2 / FR-IAM-009 esastır.

Kullanım:
  tier_a_probe.py validate          Statik model + spec + 12.2.4/12.1.8/12.1.1 resiprokal bağlantı → çıkış kodu
  tier_a_probe.py check <sample>    Tier A karar motoru: senaryo(lar) → kapı (R1–R12)
  tier_a_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  tier_a_probe.py schema            Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK (audit occurred_tick sanal-saat).
Stdlib-only. Sır/credential ve ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız actor rol
enum + action + data_class enum + resource_type adı + tier/decision enum + slug korelasyon kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tier-a-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "tier-a-model.json")
REPO_INDEP_MODEL_PATH = os.path.join(HERE, "..", "l0-repo-independence", "config", "repo-independence-model.json")
WORM_MODEL_PATH = os.path.join(HERE, "..", "worm-audit", "config", "worm-audit-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"TIER_A_GRANT", "ESCALATE_TIER_B", "DENY"}
DATA_CLASSES = ["tenant_content", "tenant_config", "tenant_metric", "platform", "global_reference"]
TIER_A_CLASSES = {"tenant_metric", "platform", "global_reference"}   # PII'siz, L0-görünür
TIER_B_CONTENT = {"tenant_content"}                                  # içerik/PII → break-glass
FORBIDDEN_CLASSES = {"tenant_config"}                                # L0 yolu yok → DENY
PLATFORM_ROLES = {"platform_owner", "platform_sre", "platform_billing"}
RULES = ["classification_coverage", "no_pii_under_tier_a", "audit_emitted", "no_break_glass_bypass",
         "escalation_correct", "audit_pii_free", "audit_immutability", "tier_separation", "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU Tier A davranışını bozan müdahaleler.
INJECTIONS = {"grant_content_at_tier_a", "skip_audit", "leak_pii_in_audit", "mutate_audit",
              "drop_escalation", "tier_b_artifact_at_tier_a", "unclassify", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "pii_under_tier_a", "break_glass_bypass", "unaudited_access", "audit_pii", "audit_mutable",
    "escalation_error", "tier_confusion", "unclassified_access", "model_tampered",
    "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.1.x/12.2.x deseniyle) — ham içerik/PII/sır yasak; rol/action/sınıf/kaynak/tier beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|corr-|bg-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|_repo|tenant_|platform_|global_reference|break_glass|audit_log|usage_record)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + rol/action/sınıf/kaynak/tier adı + slug kimlik eler (12.2.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 16):m.end() + 16]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line \
                        or '"note"' in line or '"rule"' in line or '"rationale"' in line.lower() \
                        or line.strip().startswith('"$'):
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _canon_hash(obj):
    """Bütünlük manifesti / audit row_hash: sha256(kanonik JSON) — deterministik (sort_keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _model():
    return _load(MODEL_PATH)


def _classify(sample, model):
    """Veri-sınıfını çöz: sample.data_class verilirse onu; yoksa table_class_of[resource_type]; yoksa None (bilinmeyen → fail-closed)."""
    dc = sample.get("data_class")
    if dc is None:
        dc = model.get("table_class_of", {}).get(sample.get("resource_type"))
    return dc


def _tier_of(data_class):
    """Veri-sınıfı → Tier ('A' | 'B' | 'forbidden' | None)."""
    if data_class in TIER_A_CLASSES:
        return "A"
    if data_class in TIER_B_CONTENT:
        return "B"
    if data_class in FORBIDDEN_CLASSES:
        return "forbidden"
    return None


def build(sample, spec, inject=None, model=None):
    """Tek L0AccessRequest senaryosunu yürüt → TierDecision + ihlal sayaçları.

    Motor DOĞRU Tier A davranışını hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal sayacını
    artırır (12.1.x/12.2.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id", request_id)
    actor_role = sample.get("actor_role")
    action = sample.get("action", "read")
    resource_type = sample.get("resource_type")
    occurred_tick = sample.get("occurred_tick", 0)               # sanal-saat (Date.now YOK)
    # Tier B artefaktları — Tier A bunları GEREKTİRMEZ; sadece kanıt/varlık için taşınır
    break_glass_token = bool(sample.get("break_glass_token", False))
    justification_code = sample.get("justification_code")

    data_class = _classify(sample, model)

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    tier = None
    audit_emitted = True                                          # ÇEKİRDEK: doğru motor her erişimi audit'ler

    # ── R10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "tiers": model.get("tiers"),
        "tier_a_classes": model.get("tier_a_classes"),
        "tier_b_content": model.get("tier_b_content"),
        "forbidden_classes": model.get("forbidden_classes"),
        "table_class_of": model.get("table_class_of"),
        "actor_roles": model.get("actor_roles"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["tier_a_classes"] = list(tampered["tier_a_classes"]) + ["tenant_content"]   # PII'yi Tier A'ya sok (tahrifat)
        tampered["audit"] = dict(tampered["audit"])
        tampered["audit"]["required_for_every_access"] = False                               # audit-zorunluluğu kaldır (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    known_class = data_class in DATA_CLASSES
    malformed = (not request_id or actor_role not in PLATFORM_ROLES
                 or (data_class is None and "unclassify" not in inject))

    if malformed:
        terminal, note, tier = "DENY", "malformed", None
    else:
        # ── R2 classification coverage (fail-closed) ──
        if not known_class:
            if "unclassify" in inject:
                # fail-open (degrade): sınıflandırılamayanı zorla Tier A'da kabul et
                terminal, tier = "TIER_A_GRANT", "A"
                v["unclassified_access"] += 1
                note = "unclassified"
            else:
                terminal, tier, note = "DENY", None, "unclassified_fail_closed"
        else:
            tier = _tier_of(data_class)
            # ── doğru Tier admission ──
            if tier == "A":
                terminal = "TIER_A_GRANT"                          # break-glass'sız + audit
            elif tier == "B":
                terminal = "ESCALATE_TIER_B"                       # break-glass GEREKİR; 12.3.2/3/4'e DELEGE
                note = "delegated_to_tier_b"
            else:                                                  # forbidden (tenant_config) → L0 yolu yok
                terminal, note = "DENY", "forbidden_no_l0_path"

            # ── degrade: içerik/PII'yi Tier A'da SUN (break-glass atla) ──
            if "grant_content_at_tier_a" in inject and data_class in TIER_B_CONTENT:
                terminal, tier = "TIER_A_GRANT", "A"               # ALTIN KURAL ihlali
            # ── degrade: içeriği escalate yerine SESSİZCE düşür ──
            if "drop_escalation" in inject and data_class in TIER_B_CONTENT:
                terminal, note = "DENY", "silent_drop"             # break-glass yoluna gitmez

        # ── degrade: Tier A erişiminde audit ATLA (sessiz erişim) ──
        if "skip_audit" in inject and terminal == "TIER_A_GRANT":
            audit_emitted = False

        # ── R3 NO PII UNDER TIER A (ÇEKİRDEK altın kural) ──
        if terminal == "TIER_A_GRANT" and data_class in TIER_B_CONTENT:
            v["pii_under_tier_a"] += 1
        # ── R5 NO BREAK-GLASS BYPASS — içerik Tier A'da sunuldu (break-glass yolu atlandı) ──
        if data_class in TIER_B_CONTENT and terminal == "TIER_A_GRANT":
            v["break_glass_bypass"] += 1
        # ── R6 ESCALATION CORRECT — içerik ESCALATE_TIER_B'e gitmeli; sessiz düşürme/yanlış yön ihlal ──
        if data_class in TIER_B_CONTENT and terminal not in ("ESCALATE_TIER_B", "TIER_A_GRANT"):
            # not: TIER_A_GRANT zaten R3/R5 ile yakalanır; buradaki ihlal = içerik ne escalate ne grant (sessiz drop)
            v["escalation_error"] += 1
        # ── R4 AUDIT EMITTED — Tier A grant audit'siz = sessiz erişim ──
        if terminal == "TIER_A_GRANT" and not audit_emitted:
            v["unaudited_access"] += 1
        # ── R9 TIER SEPARATION — Tier A'da işlenen Tier B artefaktı (maker-checker/gerekçe/token) ──
        if "tier_b_artifact_at_tier_a" in inject and terminal == "TIER_A_GRANT":
            v["tier_confusion"] += 1

    # ── audit kaydı üret (ÇEKİRDEK: her karar audit'lenir — malformed/deny dahil L0 erişim girişimi) ──
    audit_record = _build_audit(record_id="aud-%s" % (request_id or "x"), correlation_id=correlation_id,
                                actor_role=actor_role, actor_realm=model.get("actor_realm", "platform"),
                                action=action, data_class=data_class, resource_type=resource_type,
                                tier=tier, decision=terminal, occurred_tick=occurred_tick)
    # ── degrade: audit kaydına ham PII sok ──
    if "leak_pii_in_audit" in inject and audit_emitted:
        audit_record["pii_field_present"] = True                   # sentetik işaret (gerçek PII yazılmaz)
        v["audit_pii"] += 1
    # ── R8 audit immutability — emitilen kayıt değiştirilirse row_hash uyumsuz (WORM; 12.1.8 RESİPROKAL) ──
    if "mutate_audit" in inject and audit_emitted:
        audit_record["data_class"] = "tampered"                    # hash sonrası alan değişimi
    if audit_emitted:
        recomputed = _canon_hash({k: val for k, val in audit_record.items() if k != "row_hash"})
        if recomputed != audit_record.get("row_hash"):
            v["audit_mutable"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, correlation_id, actor_role, action, data_class, resource_type, tier,
                         terminal, note, break_glass_token, justification_code, audit_emitted, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, tier, v, note, actor_role, action, data_class, resource_type,
                 audit_emitted, audit_record, model_hash, evidence)


def _build_audit(record_id, correlation_id, actor_role, actor_realm, action, data_class, resource_type,
                 tier, decision, occurred_tick):
    """PII'siz, WORM uyumlu audit kaydı (12.1.8 RESİPROKAL): row_hash = sha256(kanonik içerik)."""
    rec = {
        "record_id": record_id,
        "correlation_id": correlation_id,
        "actor_role": actor_role,
        "actor_realm": actor_realm,
        "action": action,
        "data_class": data_class,
        "resource_type": resource_type,
        "tier": tier,
        "decision": decision,
        "occurred_tick": occurred_tick,
    }
    rec["row_hash"] = _canon_hash(rec)
    return rec


def _evidence(request_id, correlation_id, actor_role, action, data_class, resource_type, tier, terminal,
              note, break_glass_token, justification_code, audit_emitted, model_hash):
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "actor_role": actor_role,
        "action": action,
        "data_class": data_class,
        "resource_type": resource_type,
        "tier": tier,
        "terminal": terminal,
        "note": note,
        "break_glass_token": break_glass_token,
        "justification_code": justification_code,
        "audit_emitted": audit_emitted,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, tier, v, note, actor_role, action, data_class, resource_type,
          audit_emitted, audit_record, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "tier": tier,
        "note": note,
        "actor_role": actor_role,
        "action": action,
        "data_class": data_class,
        "resource_type": resource_type,
        "audit_emitted": audit_emitted,
        "audit_record": audit_record,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "pii_under_tier_a": "max_pii_under_tier_a",
        "break_glass_bypass": "max_break_glass_bypass",
        "unaudited_access": "max_unaudited_access",
        "audit_pii": "max_audit_pii",
        "audit_mutable": "max_audit_mutable",
        "escalation_error": "max_escalation_error",
        "tier_confusion": "max_tier_confusion",
        "unclassified_access": "max_unclassified_access",
        "model_tampered": "max_model_tampered",
        "missing_evidence": "max_missing_evidence",
        "stuck_state": "max_stuck_state",
        "secret_or_pii": "max_secret_or_pii",
    }
    for vk, gk in mapping.items():
        limit = gates.get(gk, 0)
        if v.get(vk, 0) > limit:
            fails.append("%s=%d > %s=%d" % (vk, v[vk], gk, limit))
    if gates.get("require_terminal", True) and result["terminal"] not in TERMINAL:
        fails.append("terminal'e ulaşılmadı: %s" % result["terminal"])
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
        for key in ("terminal", "tier", "note", "audit_emitted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s tier=%s class=%s role=%s audit=%s note=%s"
              % (res["terminal"], res["tier"], res["data_class"], res["actor_role"],
                 res["audit_emitted"], res["note"]))
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
              "outcomes", "model", "enforcement", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.3.1", spec.get("wbs") == "12.3.1")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-009 izlenir (üç katmanlı break-glass — ÇEKİRDEK)", "FR-IAM-009" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (tüm işlemler audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-REC-009 izlenir (erişim audit)", "FR-REC-009" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (L0 ⟂ iş içeriği)", "FR-IAM-008" in tr.get("fr", []))
    chk("BRD §17.7 izlenir (Tier A — metrik/log, PII yok)", any("§17.7" in s for s in tr.get("brd", [])))
    chk("SAD §14.4.2 Tier A izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-013 izlenir (üç katmanlı break-glass)", any(a.startswith("ADR-013") for a in tr.get("adr", [])))
    chk("12.2.4 repo-independence TÜKETİLİR (veri-sınıfı RESİPROKAL)",
        any("12.2.4" in s for s in tr.get("consumes", [])))
    chk("12.1.8 worm-audit TÜKETİLİR (WORM audit RESİPROKAL)",
        any("12.1.8" in s for s in tr.get("consumes", [])))
    chk("12.3.2/12.3.3/12.3.4 Tier B DELEGE (consumed_by/delegates)",
        any("12.3.2" in s for s in tr.get("consumed_by", [])) or any("12.3.2" in s for s in tr.get("delegates", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→class→tier→admission→audit→pii/bypass/escalation",
        rz.get("evaluation") == "malformed_then_classification_then_tier_then_admission_then_audit_then_pii_bypass_escalation_tier")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=DENY (fail-closed)", dec.get("default") == "DENY")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower()
        or "erişim yok" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar TIER_A_GRANT/ESCALATE_TIER_B/DENY", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — Tier A + audit + escalate
    en = spec["enforcement"]
    chk("tier_a no break-glass + audit",
        "break-glass" in en.get("tier_a", "").lower() and "audit" in en.get("tier_a", "").lower())
    chk("tier_b ESCALATE delege (12.3.2/3/4)", "12.3.2" in en.get("tier_b", "") or "12.3.3" in en.get("tier_b", "") or "12.3.4" in en.get("tier_b", ""))
    chk("audit_layer WORM (12.1.8 RESİPROKAL)", "12.1.8" in en.get("audit_layer", "") and "WORM" in en.get("audit_layer", "").upper())
    chk("no_pii_under_tier_a (altın kural)", "tier_a" in en.get("no_pii_under_tier_a", "").lower() or "Tier A" in en.get("no_pii_under_tier_a", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("tier_a_classes = metric/platform/reference (PII'siz)",
        set(md.get("tier_a_classes", [])) == TIER_A_CLASSES)
    chk("tier_b_content = tenant_content", set(md.get("tier_b_content", [])) == TIER_B_CONTENT)
    chk("forbidden_classes = tenant_config", set(md.get("forbidden_classes", [])) == FORBIDDEN_CLASSES)
    chk("actor_roles = L0 platform rolleri", set(md.get("actor_roles", [])) == PLATFORM_ROLES)
    chk("data_classes tam (5)", set(md.get("data_classes", [])) == set(DATA_CLASSES))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_pii_under_tier_a", "max_break_glass_bypass", "max_unaudited_access", "max_audit_pii",
               "max_audit_mutable", "max_escalation_error", "max_tier_confusion", "max_unclassified_access",
               "max_model_tampered", "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("l0_tier_a_access_total metrik", "l0_tier_a_access_total" in obs.get("metrics", []))
    chk("tier_a_violation_total metrik (alarm)", "tier_a_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("correlation_id/resource_id YÜKSEK kard (label değil)",
        "correlation_id" in hi and "correlation_id" not in lo)
    chk("actor_role/data_class/tier/decision DÜŞÜK kard",
        all(x in lo for x in ("actor_role", "data_class", "tier", "decision")))
    chk("alarm pii_under_tier_a/unaudited_access/break_glass_bypass ≤2dk",
        any(x in obs.get("alarm", "") for x in ("pii_under_tier_a", "unaudited_access", "break_glass_bypass")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (BRD §17.7 / SAD §14.4.2)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/tier-a-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model tier_a_classes = metric/platform/reference",
            set(mm.get("tier_a_classes", [])) == TIER_A_CLASSES)
        chk("model tier_b_content = tenant_content", set(mm.get("tier_b_content", [])) == TIER_B_CONTENT)
        chk("model tier A requires_break_glass=false + requires_audit=true",
            mm.get("tiers", {}).get("A", {}).get("requires_break_glass") is False
            and mm.get("tiers", {}).get("A", {}).get("requires_audit") is True)
        chk("model tier B requires_break_glass=true + DELEGE 12.3.2/3/4",
            mm.get("tiers", {}).get("B", {}).get("requires_break_glass") is True
            and "12.3" in mm.get("tiers", {}).get("B", {}).get("delegated_flow", ""))
        chk("model audit required_for_every_access=true + worm=true",
            mm.get("audit", {}).get("required_for_every_access") is True
            and mm.get("audit", {}).get("worm") is True)
        chk("model audit Tier A gerekçe/maker-checker/break-glass token GEREKTİRMEZ",
            mm.get("audit", {}).get("tier_a_requires_justification") is False
            and mm.get("audit", {}).get("tier_a_requires_maker_checker") is False
            and mm.get("audit", {}).get("tier_a_requires_break_glass_token") is False)
        chk("model audit no_raw_pii=true", mm.get("audit", {}).get("no_raw_pii") is True)
        tco = mm.get("table_class_of", {})
        chk("model table_class_of ≥37 varlık (BRD §16)", len(tco) >= 37)
        chk("model usage_record=tenant_metric (Tier A), transcript=tenant_content (Tier B)",
            tco.get("usage_record") == "tenant_metric" and tco.get("transcript") == "tenant_content")
        chk("model audit_log=platform (Tier A — log), agent=tenant_config (forbidden)",
            tco.get("audit_log") == "platform" and tco.get("agent") == "tenant_config")

    # 12) 12.2.4 RESİPROKAL — veri-sınıfı taksonomisi eşleşmesi
    ri_ok = os.path.exists(REPO_INDEP_MODEL_PATH)
    chk("12.2.4 ../l0-repo-independence/config/repo-independence-model.json var (TÜKETİLİR)", ri_ok)
    if ri_ok and mm_ok:
        ri = _load(REPO_INDEP_MODEL_PATH)
        chk("12.2.4 allowed_for_platform = bu modül tier_a_classes (RESİPROKAL)",
            set(ri.get("data_classes", {}).get("allowed_for_platform", [])) == set(_model().get("tier_a_classes", [])))
        chk("12.2.4 break_glass.content_tables sınıfı = tenant_content (Tier B; RESİPROKAL)",
            all(_model().get("table_class_of", {}).get(t) == "tenant_content"
                for t in ri.get("break_glass", {}).get("content_tables", [])))

    # 13) 12.1.8 RESİPROKAL — WORM audit (append-only + hash-zincir)
    wm_ok = os.path.exists(WORM_MODEL_PATH)
    chk("12.1.8 ../worm-audit/config/worm-audit-model.json var (WORM audit — TÜKETİLİR)", wm_ok)
    if wm_ok:
        wm = _load(WORM_MODEL_PATH)
        chk("12.1.8 worm_policy append_only=true (RESİPROKAL audit immutability)",
            wm.get("worm_policy", {}).get("append_only") is True)
        chk("12.1.8 integrity_policy hash_chain + sha256 (RESİPROKAL row_hash)",
            wm.get("integrity_policy", {}).get("hash_chain") is True
            and wm.get("integrity_policy", {}).get("hash_algo") == "sha256")

    # 14) 12.1.1 RESİPROKAL — L0 platform rolleri
    rb_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (RBAC rolleri — TÜKETİLİR)", rb_ok)
    if rb_ok:
        with open(RBAC_MODEL_PATH, "r", encoding="utf-8") as fh:
            rbac_txt = fh.read()
        chk("12.1.1 L0 platform rolleri (owner/sre/billing) mevcut (RESİPROKAL)",
            all(role in rbac_txt for role in PLATFORM_ROLES))

    # 15) Sır/PII tarayıcı — spec + model + samples
    scan_files = [SPEC_PATH, MODEL_PATH] + (
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
    chk("hiç ham-içerik/PII/sır sızıntısı yok (R12)", total_leaks == 0)

    # 16) Samples — ≥1 pass + ≥1 fail
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
        # Varsayılan: platform_owner, usage_record (tenant_metric → Tier A), read → TIER_A_GRANT + audit.
        d = {
            "request_id": "req-1", "actor_role": "platform_owner", "action": "read",
            "resource_type": "usage_record",
        }
        d.update(kw)
        return d

    # 1) happy — Tier A metrik → TIER_A_GRANT + audit, ihlal yok
    r = build(req(), spec)
    case("happy: TIER_A_GRANT (metrik usage_record)", r["terminal"] == "TIER_A_GRANT")
    case("happy: tier=A", r["tier"] == "A")
    case("happy: audit_emitted=True (sessiz erişim yok)", r["audit_emitted"] is True)
    case("happy: audit_record row_hash var (WORM)", r["audit_record"].get("row_hash") is not None)
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) Tier A diğer PII'siz sınıflar → TIER_A_GRANT
    case("Tier A platform audit_log (log) → TIER_A_GRANT",
         build(req(resource_type="audit_log"), spec)["terminal"] == "TIER_A_GRANT")
    case("Tier A platform tenant (yönetişim) → TIER_A_GRANT",
         build(req(resource_type="tenant"), spec)["terminal"] == "TIER_A_GRANT")
    case("Tier A global_reference role → TIER_A_GRANT",
         build(req(resource_type="role"), spec)["terminal"] == "TIER_A_GRANT")
    case("Tier A platform incident → TIER_A_GRANT",
         build(req(resource_type="incident"), spec)["terminal"] == "TIER_A_GRANT")

    # 4) R3/R5 ÇEKİRDEK — içerik/PII (transcript) Tier A'da SUNULMAZ → ESCALATE_TIER_B; ihlal yok
    r = build(req(resource_type="transcript"), spec)
    case("escalate: transcript (PII) → ESCALATE_TIER_B (break-glass gerekir)", r["terminal"] == "ESCALATE_TIER_B")
    case("escalate: pii_under_tier_a=0 + break_glass_bypass=0 (doğru escalate) + kapı geçer",
         r["violations"]["pii_under_tier_a"] == 0 and r["violations"]["break_glass_bypass"] == 0
         and _gate_eval(r, G)[0] is True)
    case("escalate: recording/contact da → ESCALATE_TIER_B",
         build(req(resource_type="recording"), spec)["terminal"] == "ESCALATE_TIER_B"
         and build(req(resource_type="contact"), spec)["terminal"] == "ESCALATE_TIER_B")
    case("escalate: audit yine emitilir (her L0 erişim girişimi audit'lenir)",
         build(req(resource_type="transcript"), spec)["audit_emitted"] is True)

    # 5) tenant_config → DENY (L0 yolu yok); ihlal yok
    r = build(req(resource_type="agent"), spec)
    case("forbidden: agent (tenant_config) → DENY (L0 yolu yok)", r["terminal"] == "DENY")
    case("forbidden: escalation_error=0 (içerik değil; doğru DENY) + kapı geçer",
         r["violations"]["escalation_error"] == 0 and _gate_eval(r, G)[0] is True)

    # 6) audit kaydı PII'siz + zorunlu alanlar
    r = build(req(), spec)
    case("audit: zorunlu alanlar (action/actor_realm/occurred_tick) var",
         all(k in r["audit_record"] for k in ("action", "actor_realm", "occurred_tick")))
    case("audit: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("transcript_text_value", "recording_audio_value", "contact_pii_value")))

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 7) grant_content_at_tier_a → pii_under_tier_a + break_glass_bypass (ÇEKİRDEK altın kural ihlali)
    r = build(req(resource_type="transcript"), spec, inject=["grant_content_at_tier_a"])
    case("grant-content-at-A: pii_under_tier_a>0 + break_glass_bypass>0 + kapı eler",
         r["violations"]["pii_under_tier_a"] > 0 and r["violations"]["break_glass_bypass"] > 0
         and _gate_eval(r, G)[0] is False)

    # 8) skip_audit → unaudited_access (sessiz erişim)
    r = build(req(), spec, inject=["skip_audit"])
    case("skip-audit: unaudited_access>0 + audit_emitted=False + kapı eler",
         r["violations"]["unaudited_access"] > 0 and r["audit_emitted"] is False
         and _gate_eval(r, G)[0] is False)

    # 9) leak_pii_in_audit → audit_pii
    r = build(req(), spec, inject=["leak_pii_in_audit"])
    case("leak-pii-audit: audit_pii>0 + kapı eler",
         r["violations"]["audit_pii"] > 0 and _gate_eval(r, G)[0] is False)

    # 10) mutate_audit → audit_mutable (WORM ihlali)
    r = build(req(), spec, inject=["mutate_audit"])
    case("mutate-audit: audit_mutable>0 + kapı eler",
         r["violations"]["audit_mutable"] > 0 and _gate_eval(r, G)[0] is False)

    # 11) drop_escalation → escalation_error (içerik sessizce düşürüldü)
    r = build(req(resource_type="transcript"), spec, inject=["drop_escalation"])
    case("drop-escalation: escalation_error>0 + terminal=DENY(silent_drop) + kapı eler",
         r["violations"]["escalation_error"] > 0 and r["terminal"] == "DENY"
         and _gate_eval(r, G)[0] is False)

    # 12) tier_b_artifact_at_tier_a → tier_confusion
    r = build(req(justification_code="JC-1", break_glass_token=True), spec, inject=["tier_b_artifact_at_tier_a"])
    case("tier-b-artifact-at-A: tier_confusion>0 + kapı eler",
         r["violations"]["tier_confusion"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) unclassify → unclassified_access (fail-open)
    r = build(req(resource_type="mystery_table", data_class=None), spec, inject=["unclassify"])
    case("unclassify: unclassified_access>0 + kapı eler",
         r["violations"]["unclassified_access"] > 0 and _gate_eval(r, G)[0] is False)
    # bilinmeyen sınıf inject'siz → DENY (fail-closed)
    case("unclassified fail-closed: bilinmeyen sınıf → DENY",
         build(req(resource_type="mystery_table", data_class="bogus"), spec)["terminal"] == "DENY")

    # 14) model_tamper → model_tampered
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 15) malformed → DENY
    case("malformed-noreq: DENY", build(req(request_id=None), spec)["note"] == "malformed")
    case("malformed-norole: DENY", build(req(actor_role="bogus"), spec)["note"] == "malformed")
    case("malformed-tenantrole: DENY (L0 rolü değil)",
         build(req(actor_role="tenant_owner"), spec)["note"] == "malformed")

    # 16) evidence + leak
    r = build(req(), spec)
    case("evidence: request+actor+class+resource+tier+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "actor_role", "data_class", "resource_type", "tier", "model_hash")))
    case("leak: rol+action+sınıf+tier temiz",
         scan_leaks('{"actor_role":"platform_owner","action":"read","data_class":"tenant_metric","tier":"A","resource_type":"usage_record"}') == [])
    case("leak: transcript_text_value alanı yakalanır", len(scan_leaks('{"transcript_text_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "break-glass-tier-a (WBS 12.3.1 — Tier A [metrik/log, PII yok]: break-glass'sız L0 + audit; BRD §17.7, SAD §14.4.2, FR-IAM-009)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "data_classes": DATA_CLASSES,
        "tier_a_classes": sorted(TIER_A_CLASSES),
        "tier_b_content": sorted(TIER_B_CONTENT),
        "forbidden_classes": sorted(FORBIDDEN_CLASSES),
        "actor_roles": sorted(PLATFORM_ROLES),
        "decision": "malformed ⇒ DENY(malformed) → data_class bilinmiyor ⇒ fail-closed DENY; zorla kabul ⇒ "
                    "unclassified_access → tier (A=metric/platform/reference; B=tenant_content; forbidden=tenant_config) → "
                    "admission (A→TIER_A_GRANT; B→ESCALATE_TIER_B; forbidden→DENY) → audit emit (her karar) → "
                    "TIER_A_GRANT ∧ content ⇒ pii_under_tier_a + break_glass_bypass → content ∧ silent-drop ⇒ "
                    "escalation_error → TIER_A_GRANT ∧ ¬audit ⇒ unaudited_access → audit PII/mutate kontrolleri",
        "default": "DENY (fail-closed)",
        "fail_safe": "terminal=DENY ⇒ erişim yok (no access); malformed/bilinmeyen-sınıf/tenant_config ⇒ DENY; "
                     "içerik/PII ⇒ ESCALATE_TIER_B (asla Tier A'da sunulmaz)",
        "core_guarantees": [
            "R3 NO PII UNDER TIER A: TIER_A_GRANT yalnız PII'siz sınıflara (tenant_metric/platform/global_reference); içerik/PII Tier A'da ASLA sunulmaz (pii_under_tier_a=0; altın kural FR-IAM-008/009)",
            "R4 AUDIT EMITTED: her TIER_A_GRANT (ve her L0 erişim kararı) DEĞİŞMEZ (WORM) audit üretir; sessiz erişim yok (unaudited_access=0; FR-IAM-009 '+ audit', FR-REC-009, FR-IAM-006; 12.1.8 RESİPROKAL)",
            "R5 NO BREAK-GLASS BYPASS: içerik/PII Tier A'dan geçemez; break-glass yolunu (12.3.2/3/4) atlayan içerik erişimi yok (break_glass_bypass=0)",
            "R6 ESCALATION CORRECT: içerik/PII → ESCALATE_TIER_B (delege 12.3.2/3/4); sessiz düşürme/yanlış yön = escalation_error=0",
            "R7 AUDIT PII-FREE: audit kaydı ham içerik/PII tutmaz (yalnız rol+action+sınıf+kaynak+tier+karar+korelasyon+hash); audit_pii=0 (FR-REC-004)",
            "R8 AUDIT IMMUTABILITY: audit append-only/WORM; emitilen kayıt tahrifatı row_hash uyumsuzluğuyla tespit (12.1.8 RESİPROKAL); audit_mutable=0",
            "R9 TIER SEPARATION: Tier A break-glass token/maker-checker/gerekçe GEREKTİRMEZ (bunlar Tier B; 12.3.2/3/4); Tier A'da işlenen Tier B artefaktı = tier_confusion=0",
        ],
        "request_fields": ["name", "request_id", "correlation_id", "actor_role(platform_owner|platform_sre|platform_billing)",
                           "action", "resource_type", "data_class(tenant_content|tenant_config|tenant_metric|platform|global_reference)",
                           "occurred_tick(sanal-saat int)", "break_glass_token(bool — Tier A gerektirmez)",
                           "justification_code(Tier B artefaktı)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(TIER_A_GRANT|ESCALATE_TIER_B|DENY)", "tier(A|B|forbidden|None)", "note",
                            "actor_role", "action", "data_class", "resource_type", "audit_emitted", "audit_record", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/tier-a-model.json (frozen — tiers[A no-bg+audit / B bg-delege] + tier_a_classes[PII'siz] "
                 "+ tier_b_content[tenant_content] + forbidden_classes[tenant_config] + table_class_of[37] + audit[WORM] + actor_roles)",
        "consumes": "12.2.4 repo-independence (veri-sınıfı taksonomisi RESİPROKAL: tier_a_classes=allowed_for_platform); "
                    "12.1.8 worm-audit (append-only/WORM + hash-zincir RESİPROKAL); 12.1.1 rbac-model (L0 rolleri); "
                    "BRD §17.7 + SAD §14.4.2 + FR-IAM-009 (kaynak doğruluk)",
        "consumed_by": "12.3.2 (maker-checker + time-boxed token); 12.3.3 (gerekçe kodu + bildirim); 12.3.4 (regüle "
                       "tenant toggle + DPA) — Tier B AKIŞI DELEGE; 1.x F1 kod (FastAPI break-glass router + audit "
                       "yazımı); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-IAM-009, FR-IAM-006, FR-REC-009, FR-IAM-008, BRD §17.7, SAD §14.4.2, ADR-013, 12.2.4, 12.1.8, 12.1.1",
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
            print("kullanım: tier_a_probe.py check <sample.json|dizin>")
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
