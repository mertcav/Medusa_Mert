#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.4 — TIER B BREAK-GLASS: REGÜLE TENANT require_tenant_approval TOGGLE + DPA BAĞI referans probe.

12. workstream'in (IAM & Erişim) ÜÇ KATMANLI BREAK-GLASS'ın İÇERİK/PII KATMANININ (Tier B) REGÜLE TENANT
ONAY KATMANI ve F2-Must yeteneği. BRD §17/§17.7 ('Regüle tenant'lar (finans/sağlık): Tier B'de tenant onayı
zorunlu toggle'ı; regulated compliance profile'da varsayılan açık. B2B2B'de veri controller'ı tenant, RMC
processor'dür; bu kontrol DPA'ya bağlanır') + FR-IAM-010 (regüle tenant onay toggle'ı + DPA) + SAD §14.4.2
('Regüle tenant toggle: require_tenant_approval=true ise Tier B, tenant onayı olmadan açılmaz; regulated
compliance profile'da varsayılan açık; DPA'ya bağlı [controller=tenant, processor=RMC]') + ADR-013 + DPIA §8
(compliance profile çözümleme: most-restrictive-wins; tenant override yalnız-sıkılaştırır). ALTIN KURAL
(BRD §17): L0 (platform) tenant'ın iş içeriğini VARSAYILAN GÖREMEZ — Tier B yalnız DAR, SÜRELİ, ONAYLI,
TAM-AUDIT'li kapıyı açar; REGÜLE tenant'ta bu kapı EK olarak TENANT ONAYINA (controller=tenant) + DPA'ya
bağlanır. Bu modül 12.3.2'nin GRANT_TIER_B/PENDING/DENY (access_decision) çıktısını TÜKETİR; bir
BreakGlassTierBApprovalEvent alır → DETERMİNİSTİK, FAIL-CLOSED karar verir:

    ALLOW — Tier B erişimi açılabilir (regüle değil/toggle kapalı VEYA regüle + toggle açık + GEÇERLİ
            tenant onayı [tenant realm rolü; target_tenant + break_glass_id bağlı] + DPA bağlı).
    HOLD  — erişim AÇILMAZ: 12.3.2 grant etmedi (access_not_granted; benign) VEYA regüle + toggle açık +
            geçerli tenant onayı YOK (awaiting_tenant_approval; ÇEKİRDEK FR-IAM-010) VEYA idempotent
            (already_resolved).
    BLOCK — malformed / regüle kontrol DPA'sız (dpa_unbound) → fail-closed.

ÇEKİRDEK:
  (1) C2 REGÜLE VARSAYILAN AÇIK — regulated profile → require_tenant_approval VARSAYILAN true; regüle
      toggle kapatma → regulated_toggle_off=0 (most-restrictive-wins).
  (2) C3 ONAYSIZ AÇILMAZ — require_tenant_approval=true iken GRANT_TIER_B GEÇERLİ tenant onayı OLMADAN
      erişimi AÇMAZ (HOLD); onaysız açma → tenant_approval_bypassed=0 ('tenant onayı olmadan açılmaz').
  (3) C4 ONAY YETKİSİ — onay tenant realm rolünden (controller=tenant); platform self-approval yok →
      approval_authority_violation=0.
  (4) C5 DPA BAĞI — regüle kontrol imzalı DPA'ya bağlı (controller=tenant/processor=RMC); DPA'sız → BLOCK;
      dpa_unbound=0.

      BreakGlassTierBApprovalEvent ─malformed─► access_routing ─► regulated_toggle ─► dpa_binding ─► tenant_approval ─► audit/replay
            ├─ request_id / actor_role(L0) / target_tenant / tier≠B / access_decision tanınmaz ──► BLOCK (malformed)
            ├─ access_decision ∈ {PENDING, DENY} (12.3.2 grant etmedi) ─────────────────────────► HOLD (access_not_granted) [C1 doğru]
            ├─ require_tenant_approval=false (regüle değil + override yok) ─────────────────────► ALLOW (not_regulated) [C1 doğru]
            ├─ regüle + dpa_signed=false ──────────────────────────────────────────────────────► BLOCK (dpa_unbound) [C5 doğru]
            ├─ prior_state çözülmüş (CONSUMED/REVOKED/EXPIRED) ────────────────────────────────► HOLD (already_resolved) [C8 doğru]
            ├─ geçerli tenant onayı yok ───────────────────────────────────────────────────────► HOLD (awaiting_tenant_approval) [C3 doğru]
            └─ geçerli tenant onayı (tenant realm + target_tenant + break_glass_id) ───────────► ALLOW (tenant_approved)

Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK; model_hash sha256; tick=dakika sanal-saat). Her karar
terminal (C1) + kanıt + model bütünlük manifesti (C10); metrik düşük-kardinalite + ham PII/token yok (C11);
model/spec/sample ham içerik/PII/token tutmaz (C12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): Tier B erişim-verme (maker-checker + time-boxed token) → 12.3.2
(CONSUMED); gerekçe kodu + tenant bildirimi → 12.3.3; Tier sınıflandırma + ESCALATE → 12.3.1;
rol→permission-key/scope → 12.1.2/12.1.3; WORM audit hash-zinciri → 12.1.8 (CONSUMED); cp.* compliance profile
motoru → DPIA.md + F2/F3. KAYNAK DOĞRULUK; çelişkide BRD §17 / FR-IAM-010 / SAD §14.4.2 esastır.

Kullanım:
  tier_b_approval_probe.py validate          Statik model + spec + 12.3.2/12.1.1/12.1.8 resiprokal → çıkış kodu
  tier_b_approval_probe.py check <sample>    Regüle onay karar motoru: senaryo(lar) → kapı (C1–C12)
  tier_b_approval_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  tier_b_approval_probe.py schema            Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK (tick=dakika sanal-saat).
Stdlib-only. Sır/credential (break-glass/onay token DEĞERİ) ve ham içerik (PII değeri) üretilmez/yazılmaz
(fixture sentetik — yalnız rol enum + realm enum + sınıf enum + kaynak adı + tier/decision enum + bool +
profil enum + tick tamsayı + slug kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tier-b-approval-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "tier-b-approval-model.json")
TIER_B_MODEL_PATH = os.path.join(HERE, "..", "break-glass-tier-b", "config", "tier-b-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
WORM_MODEL_PATH = os.path.join(HERE, "..", "worm-audit", "config", "worm-audit-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"ALLOW", "HOLD", "BLOCK"}
GRANT = "GRANT_TIER_B"                                              # yalnız bu access_decision regüle gate gerektirir
ACCESS_DECISIONS = {"GRANT_TIER_B", "PENDING", "DENY"}             # 12.3.2 access_decision çıktısı
PLATFORM_ROLES = {"platform_owner", "platform_sre", "platform_billing"}
APPROVER_ROLES = ["security_compliance_officer", "tenant_owner"]   # tenant realm L1 onaylayan rolleri (12.1.1)
RESOLVED_STATES = {"CONSUMED", "REVOKED", "EXPIRED"}               # replay: çözülmüş tenant onayı
RULES = ["access_routing", "regulated_default_on", "tenant_approval_gate", "approval_authority",
         "dpa_binding", "override_tightens_only", "approval_binding", "replay_safe", "audit_emitted",
         "model_integrity"]
INVARIANT_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]

# Degrade (inject) — DOĞRU regüle onay davranışını bozan müdahaleler.
INJECTIONS = {"disable_regulated_toggle", "loosen_override", "bypass_tenant_approval", "platform_self_approve",
              "cross_realm_approval", "cross_tenant_approval", "unbind_dpa", "replay_approval", "skip_audit",
              "leak_pii", "mutate_audit", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "regulated_toggle_off", "tenant_approval_bypassed", "approval_authority_violation", "dpa_unbound",
    "override_loosened", "approval_misbinding", "approval_replay", "unaudited_decision", "audit_pii",
    "audit_mutable", "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (C12; 12.3.x deseniyle) — ham içerik/PII/token yasak; rol/realm/sınıf/kaynak/tier beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|break_glass_token_value|approval_token_value|token_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|bg-|rc-|corr-|tok-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|_repo|tenant_|platform_|security_compliance|global_reference|break_glass|audit_log|usage_record)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/token tarayıcı. Yorum/tarif satırı + rol/realm/sınıf/kaynak/tier adı + slug kimlik eler."""
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
                # pii_field = açık yasak alan-adı işareti (ör. "break_glass_token_value":) → allowlist'i atla
                if name != "pii_field" and (LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag)):
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


def _correct_required(regulated, override, model):
    """Regüle toggle çözümlemesi (DPIA §8 most-restrictive-wins; override yalnız-sıkılaştırır).

    base = regüle ise default_when_regulated (true) aksi default_when_unregulated (false).
    override 'on' → True (sıkılaştırma serbest). override 'off'/yok → base (gevşetme uygulanmaz).
    DOĞRU değer; degrade (inject) bunu build()'de bozar."""
    pol = model.get("regulated_policy", {})
    base = bool(pol.get("require_tenant_approval_default_when_regulated", True)) if regulated \
        else bool(pol.get("default_when_unregulated", False))
    if override == "on":
        return True
    return base                                                    # 'off'/None gevşetemez (most-restrictive-wins)


def _approval_valid(approval, target_tenant_id, break_glass_id, approver_roles):
    """Geçerli tenant onayı: tenant realm rolünden (controller=tenant) + target_tenant + break_glass_id bağlı."""
    if not isinstance(approval, dict):
        return False
    return (approval.get("realm") == "tenant"
            and approval.get("role") in approver_roles
            and approval.get("tenant_id", target_tenant_id) == target_tenant_id
            and approval.get("break_glass_id", break_glass_id) == break_glass_id)


def build(sample, spec, inject=None, model=None):
    """Tek BreakGlassTierBApprovalEvent senaryosunu yürüt → karar + ihlal sayaçları.

    Motor DOĞRU regüle onay davranışını hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal
    sayacını artırır (12.1.x/12.2.x/12.3.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id", request_id)
    break_glass_id = sample.get("break_glass_id", "bg-%s" % (request_id or "x"))
    actor_role = sample.get("actor_role")
    target_tenant_id = sample.get("target_tenant_id")
    tier = sample.get("tier", "B")
    resource_type = sample.get("resource_type")
    data_class = sample.get("data_class", "tenant_content")
    access_decision = sample.get("access_decision")                # 12.3.2 çıktısı (TÜKETİLİR)
    regulated = bool(sample.get("regulated", False))               # regüle compliance profile bayrağı
    override = sample.get("tenant_override")                       # DPIA §8 override (on/off/None)
    dpa_signed = bool(sample.get("dpa_signed", False))             # imzalı DPA bağı
    approval = sample.get("tenant_approval")                       # opsiyonel {role,realm,tenant_id,break_glass_id}
    now = sample.get("now", 0)                                     # tick = dakika (Date.now YOK)
    prior_state = sample.get("prior_state")                       # replay: çözülmüş onay (opsiyonel)

    approver_roles = list(model.get("approval_policy", {}).get("approver_roles", APPROVER_ROLES))

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    tenant_approved = False
    approver_role = None
    audit_emitted = True                                          # ÇEKİRDEK: doğru motor her kararı audit'ler

    # ── C2 DOĞRU regüle toggle (degrade'siz) ──
    correct_required = _correct_required(regulated, override, model)

    # ── C10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "tier": model.get("tier"),
        "data_class": model.get("data_class"),
        "regulated_policy": model.get("regulated_policy"),
        "approval_policy": model.get("approval_policy"),
        "dpa_policy": model.get("dpa_policy"),
        "concurrency_policy": model.get("concurrency_policy"),
        "actor_roles": model.get("actor_roles"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["regulated_policy"] = dict(tampered["regulated_policy"])
        tampered["regulated_policy"]["require_tenant_approval_default_when_regulated"] = False  # regüle default kapat
        tampered["approval_policy"] = dict(tampered["approval_policy"])
        tampered["approval_policy"]["no_platform_self_approval"] = False                        # self-approval aç
        tampered["dpa_policy"] = dict(tampered["dpa_policy"])
        tampered["dpa_policy"]["require_dpa_when_regulated"] = False                            # DPA zorunluluğu kaldır
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or actor_role not in PLATFORM_ROLES
                 or not target_tenant_id or tier != "B" or access_decision not in ACCESS_DECISIONS)

    if malformed:
        terminal, note = "BLOCK", "malformed"
    elif access_decision != GRANT:
        # ── C1 access routing: PENDING/DENY → 12.3.2 grant etmedi → erişim açılmıyor (DOĞRU) ──
        terminal, note = "HOLD", "access_not_granted"
    else:
        # ── access_decision == GRANT_TIER_B → regüle toggle + tenant onayı + DPA gate ZORUNLU ──
        required = correct_required

        # ── degrade: regüle toggle gevşetme (C2/C6) — required'ı GÜVENSİZ kapat ──
        if regulated and "disable_regulated_toggle" in inject:
            v["regulated_toggle_off"] += 1
            required = False                                       # GÜVENSİZ: regüle tenant'ta gate kapatıldı
        if regulated and "loosen_override" in inject:
            v["override_loosened"] += 1
            required = False                                       # GÜVENSİZ: override regüle default-on'u gevşetti

        # ── geçerli tenant onayı (DOĞRU) ──
        approval_valid = _approval_valid(approval, target_tenant_id, break_glass_id, approver_roles)
        if approval_valid:
            approver_role = approval.get("role")

        # ── degrade: yetkisiz/yanlış-bağlı onayı GÜVENSİZ kabul et (C4/C7/C8) ──
        approval_accepted = approval_valid
        if "platform_self_approve" in inject:
            v["approval_authority_violation"] += 1                 # platform aktörü kendi erişimini onayladı
            approval_accepted = True
            approver_role = actor_role                             # platform rolü (tenant realm DEĞİL)
        elif "cross_realm_approval" in inject:
            v["approval_authority_violation"] += 1                 # tenant-dışı realm onayı
            approval_accepted = True
        elif "cross_tenant_approval" in inject:
            v["approval_misbinding"] += 1                          # başka tenant'a ait onay
            approval_accepted = True
        elif "replay_approval" in inject and prior_state in RESOLVED_STATES:
            v["approval_replay"] += 1                              # çözülmüş onay yeniden kullanıldı
            approval_accepted = True

        if not required:
            terminal = "ALLOW"
            note = "not_regulated" if not regulated else "toggle_off_unsafe"
        else:
            # ── C5 DPA bağı: regüle kontrol imzalı DPA'ya bağlı; DPA'sız → BLOCK ──
            dpa_ok = dpa_signed
            if not dpa_ok and "unbind_dpa" in inject:
                v["dpa_unbound"] += 1                              # GÜVENSİZ: DPA'sız regüle erişim açıldı
                dpa_ok = True
            if not dpa_ok:
                terminal, note = "BLOCK", "dpa_unbound"            # DOĞRU fail-closed (hukuki dayanak yok)
            elif prior_state in RESOLVED_STATES and "replay_approval" not in inject:
                # ── C8 doğru: idempotent — çözülmüş onay yeniden kullanılmaz ──
                terminal, note = "HOLD", "already_resolved"
            elif "bypass_tenant_approval" in inject and not approval_accepted:
                # ── C3 degrade: onaysız erişim açıldı (sessiz/gizli break-glass) ──
                v["tenant_approval_bypassed"] += 1
                terminal, note = "ALLOW", "approval_bypassed_unsafe"
            elif not approval_accepted:
                # ── C3 doğru: geçerli tenant onayı yok → erişim AÇILMAZ ──
                terminal, note = "HOLD", "awaiting_tenant_approval"
            else:
                terminal, note = "ALLOW", "tenant_approved"
                tenant_approved = True

        # ── C9 audit: degrade — ALLOW audit ATLA (sessiz erişim) ──
        if "skip_audit" in inject and terminal == "ALLOW":
            audit_emitted = False
        if terminal == "ALLOW" and not audit_emitted:
            v["unaudited_decision"] += 1

    # ── dpa_bound kanıtı: regüle gate'in DPA tarafından bağlandığı (audit/kanıt için) ──
    dpa_bound = bool(dpa_signed) if (terminal == "ALLOW" and access_decision == GRANT and correct_required) else dpa_signed

    # ── audit kaydı üret (ÇEKİRDEK: her karar audit'lenir — malformed/block/hold dahil break-glass girişimi) ──
    audit_record = _build_audit(
        record_id="aud-%s" % (request_id or "x"), break_glass_id=break_glass_id, correlation_id=correlation_id,
        actor_role=actor_role, actor_realm=model.get("actor_realm", "platform"),
        target_tenant_ref=target_tenant_id, data_class=data_class, resource_type=resource_type,
        tier=tier, decision=terminal, regulated=regulated, require_tenant_approval=correct_required,
        tenant_approved=tenant_approved, dpa_bound=dpa_bound, approver_role=approver_role, occurred_tick=now)
    # ── degrade: audit kaydına ham PII/token sok ──
    if "leak_pii" in inject and audit_emitted:
        audit_record["pii_field_present"] = True                   # sentetik işaret (gerçek PII/token yazılmaz)
        v["audit_pii"] += 1
    # ── C9 audit immutability — emitilen kayıt değiştirilirse row_hash uyumsuz (WORM; 12.1.8 RESİPROKAL) ──
    if "mutate_audit" in inject and audit_emitted:
        audit_record["decision"] = "tampered"                      # hash sonrası alan değişimi
    if audit_emitted:
        recomputed = _canon_hash({k: val for k, val in audit_record.items() if k != "row_hash"})
        if recomputed != audit_record.get("row_hash"):
            v["audit_mutable"] += 1

    # ── C1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (C1) ──
    evidence = _evidence(request_id, correlation_id, break_glass_id, actor_role, target_tenant_id, data_class,
                         resource_type, access_decision, regulated, correct_required, dpa_bound, tenant_approved,
                         approver_role, tier, terminal, note, audit_emitted, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, note, v, actor_role, target_tenant_id, data_class, resource_type,
                 access_decision, regulated, correct_required, dpa_bound, tenant_approved, approver_role, tier,
                 audit_emitted, audit_record, model_hash, evidence)


def _build_audit(record_id, break_glass_id, correlation_id, actor_role, actor_realm, target_tenant_ref,
                 data_class, resource_type, tier, decision, regulated, require_tenant_approval, tenant_approved,
                 dpa_bound, approver_role, occurred_tick):
    """PII/token-free, WORM uyumlu audit kaydı (12.1.8 RESİPROKAL): row_hash = sha256(kanonik içerik)."""
    rec = {
        "record_id": record_id,
        "break_glass_id": break_glass_id,
        "correlation_id": correlation_id,
        "actor_role": actor_role,
        "actor_realm": actor_realm,
        "target_tenant_ref": target_tenant_ref,
        "data_class": data_class,
        "resource_type": resource_type,
        "tier": tier,
        "decision": decision,
        "regulated": regulated,
        "require_tenant_approval": require_tenant_approval,
        "tenant_approved": tenant_approved,
        "dpa_bound": dpa_bound,
        "approver_role": approver_role,
        "occurred_tick": occurred_tick,
    }
    rec["row_hash"] = _canon_hash(rec)
    return rec


def _evidence(request_id, correlation_id, break_glass_id, actor_role, target_tenant_id, data_class,
              resource_type, access_decision, regulated, require_tenant_approval, dpa_bound, tenant_approved,
              approver_role, tier, terminal, note, audit_emitted, model_hash):
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "break_glass_id": break_glass_id,
        "actor_role": actor_role,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "access_decision": access_decision,
        "regulated": regulated,
        "require_tenant_approval": require_tenant_approval,
        "dpa_bound": dpa_bound,
        "tenant_approved": tenant_approved,
        "approver_role": approver_role,
        "tier": tier,
        "terminal": terminal,
        "note": note,
        "audit_emitted": audit_emitted,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, note, v, actor_role, target_tenant_id, data_class, resource_type, access_decision,
          regulated, require_tenant_approval, dpa_bound, tenant_approved, approver_role, tier, audit_emitted,
          audit_record, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "note": note,
        "actor_role": actor_role,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "access_decision": access_decision,
        "regulated": regulated,
        "require_tenant_approval": require_tenant_approval,
        "dpa_bound": dpa_bound,
        "tenant_approved": tenant_approved,
        "approver_role": approver_role,
        "tier": tier,
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
        "regulated_toggle_off": "max_regulated_toggle_off",
        "tenant_approval_bypassed": "max_tenant_approval_bypassed",
        "approval_authority_violation": "max_approval_authority_violation",
        "dpa_unbound": "max_dpa_unbound",
        "override_loosened": "max_override_loosened",
        "approval_misbinding": "max_approval_misbinding",
        "approval_replay": "max_approval_replay",
        "unaudited_decision": "max_unaudited_decision",
        "audit_pii": "max_audit_pii",
        "audit_mutable": "max_audit_mutable",
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
        for key in ("terminal", "note", "tenant_approved", "require_tenant_approval", "dpa_bound"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s note=%s access=%s regulated=%s req_approval=%s dpa=%s approved=%s audit=%s"
              % (res["terminal"], res["note"], res["access_decision"], res["regulated"],
                 res["require_tenant_approval"], res["dpa_bound"], res["tenant_approved"], res["audit_emitted"]))
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
    chk("wbs=12.3.4", spec.get("wbs") == "12.3.4")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-010 izlenir (regüle tenant onay toggle + DPA — ÇEKİRDEK)", "FR-IAM-010" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (tüm işlemler audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-REC-009 izlenir (erişim audit)", "FR-REC-009" in tr.get("fr", []))
    chk("SR-IAM-010 izlenir", "SR-IAM-010" in tr.get("srs", []))
    chk("TC-IAM-010 izlenir", "TC-IAM-010" in tr.get("rtm", []))
    chk("BRD §17 izlenir (regüle tenant onay toggle + DPA)", any("§17" in s for s in tr.get("brd", [])))
    chk("SAD §14.4.2 regüle toggle izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-013 izlenir (üç katmanlı break-glass + regüle onay toggle)",
        any(a.startswith("ADR-013") for a in tr.get("adr", [])))
    chk("12.3.2 tier-b TÜKETİLİR (access_decision RESİPROKAL)",
        any("12.3.2" in s for s in tr.get("consumes", [])))
    chk("12.1.1 rbac TÜKETİLİR (onaylayan tenant rolleri RESİPROKAL)",
        any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.8 worm-audit TÜKETİLİR (WORM audit RESİPROKAL)",
        any("12.1.8" in s for s in tr.get("consumes", [])))
    chk("12.3.5 DELEGE/consumed_by (tam-audit router)",
        any("12.3.5" in s for s in tr.get("consumed_by", [])))
    chk("DPIA most-restrictive-wins DELEGE (cp.* motoru)",
        any("DPIA" in s for s in tr.get("delegates", [])))

    # 3) On kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("on kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→access_routing→regulated_toggle→dpa_binding→tenant_approval→audit/replay",
        rz.get("evaluation") == "malformed_then_access_routing_then_regulated_toggle_then_dpa_binding_then_tenant_approval_then_audit_replay")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower()
        or "erişim" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar ALLOW/HOLD/BLOCK", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — regüle toggle + tenant onayı + DPA + audit
    en = spec["enforcement"]
    chk("regulated_toggle varsayılan açık + most-restrictive",
        ("varsayılan açık" in en.get("regulated_toggle", "").lower())
        and ("sıkılaş" in en.get("regulated_toggle", "").lower() or "most-restrictive" in en.get("regulated_toggle", "").lower()))
    chk("tenant_approval onaysız açılmaz + tenant realm",
        ("açılmaz" in en.get("tenant_approval", "").lower())
        and "security_compliance_officer" in en.get("tenant_approval", "") and "tenant_owner" in en.get("tenant_approval", ""))
    chk("dpa_binding controller=tenant/processor=RMC + DPA'sız BLOCK",
        ("controller=tenant" in en.get("dpa_binding", "").lower()) and ("processor=rmc" in en.get("dpa_binding", "").lower())
        and "BLOCK" in en.get("dpa_binding", ""))
    chk("audit_layer WORM (12.1.8 RESİPROKAL)", "12.1.8" in en.get("audit_layer", "") and "WORM" in en.get("audit_layer", "").upper())

    # 7) Model alanları
    md = spec["model"]
    chk("model tier=B", md.get("tier") == "B")
    chk("model data_class=tenant_content", md.get("data_class") == "tenant_content")
    chk("model approver_roles = SCO + owner",
        set(md.get("approver_roles", [])) == set(APPROVER_ROLES))
    chk("model controller=tenant + processor=rmc",
        md.get("controller_role") == "tenant" and md.get("processor_role") == "rmc")
    chk("model actor_roles = L0 platform rolleri", set(md.get("actor_roles", [])) == PLATFORM_ROLES)

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_regulated_toggle_off", "max_tenant_approval_bypassed", "max_approval_authority_violation",
               "max_dpa_unbound", "max_override_loosened", "max_approval_misbinding", "max_approval_replay",
               "max_unaudited_decision", "max_audit_pii", "max_audit_mutable", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("l0_break_glass_approval_total metrik", "l0_break_glass_approval_total" in obs.get("metrics", []))
    chk("break_glass_approval_violation_total metrik (alarm)", "break_glass_approval_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("break_glass_id/target_tenant_id YÜKSEK kard (label değil)",
        "break_glass_id" in hi and "break_glass_id" not in lo and "target_tenant_id" in hi)
    chk("actor_role/decision/result/approver_role DÜŞÜK kard",
        all(x in lo for x in ("actor_role", "decision", "result", "approver_role")))
    chk("alarm tenant_approval_bypassed/dpa_unbound/regulated_toggle_off ≤2dk",
        any(x in obs.get("alarm", "") for x in ("tenant_approval_bypassed", "dpa_unbound", "regulated_toggle_off", "approval_authority_violation")))

    # 10) İnvariant'lar C1–C12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar C1–C12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (BRD §17 / FR-IAM-010 / SAD §14.4.2)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/tier-b-approval-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model tier=B + data_class=tenant_content",
            mm.get("tier") == "B" and mm.get("data_class") == "tenant_content")
        chk("model regulated require_tenant_approval_default_when_regulated=true + most_restrictive_wins=true + override_tightens_only=true",
            mm.get("regulated_policy", {}).get("require_tenant_approval_default_when_regulated") is True
            and mm.get("regulated_policy", {}).get("most_restrictive_wins") is True
            and mm.get("regulated_policy", {}).get("override_tightens_only") is True)
        chk("model regulated default_when_unregulated=false (regüle değil → opt-in)",
            mm.get("regulated_policy", {}).get("default_when_unregulated") is False)
        chk("model approval require_gate + approver_realm=tenant + no_platform_self_approval",
            mm.get("approval_policy", {}).get("require_tenant_approval_gate") is True
            and mm.get("approval_policy", {}).get("approver_realm") == "tenant"
            and mm.get("approval_policy", {}).get("no_platform_self_approval") is True)
        chk("model approval approver_roles = SCO + owner (12.1.1 RESİPROKAL)",
            set(mm.get("approval_policy", {}).get("approver_roles", [])) == set(APPROVER_ROLES))
        chk("model approval bind_break_glass_id + bind_target_tenant (binding)",
            mm.get("approval_policy", {}).get("bind_break_glass_id") is True
            and mm.get("approval_policy", {}).get("bind_target_tenant") is True)
        chk("model dpa require_dpa_when_regulated + controller=tenant + processor=rmc + bind_to_dpa",
            mm.get("dpa_policy", {}).get("require_dpa_when_regulated") is True
            and mm.get("dpa_policy", {}).get("controller_role") == "tenant"
            and mm.get("dpa_policy", {}).get("processor_role") == "rmc"
            and mm.get("dpa_policy", {}).get("bind_control_to_dpa") is True)
        chk("model audit required_for_every_decision=true + worm=true + no_raw_token=true",
            mm.get("audit", {}).get("required_for_every_decision") is True
            and mm.get("audit", {}).get("worm") is True
            and mm.get("audit", {}).get("no_raw_token") is True)
        chk("model audit break_glass_id + tenant_approved + dpa_bound record alanları",
            all(f in mm.get("audit", {}).get("record_fields", []) for f in ("break_glass_id", "tenant_approved", "dpa_bound")))
        chk("model concurrency resolved_states = CONSUMED/REVOKED/EXPIRED (replay-safe)",
            set(mm.get("concurrency_policy", {}).get("resolved_states", [])) == RESOLVED_STATES)

    # 12) 12.3.2 RESİPROKAL — Tier B access_decision DELEGE
    tb_ok = os.path.exists(TIER_B_MODEL_PATH)
    chk("12.3.2 ../break-glass-tier-b/config/tier-b-model.json var (access_decision — TÜKETİLİR)", tb_ok)
    if tb_ok and mm_ok:
        tb = _load(TIER_B_MODEL_PATH)
        chk("12.3.2 terminal GRANT_TIER_B üretir (bu modül access_decision olarak TÜKETİR; RESİPROKAL)",
            GRANT in tb.get("terminal", []))
        chk("12.3.2 tier=B + data_class=tenant_content = bu modül (RESİPROKAL)",
            tb.get("tier") == "B" and tb.get("data_class") == "tenant_content"
            and tb.get("tier") == _model().get("tier"))
        chk("12.3.2 regüle tenant toggle 12.3.4'e DELEGE (RESİPROKAL)",
            "12.3.4" in tb.get("delegates", {}).get("regulated_tenant_toggle", ""))

    # 13) 12.1.1 RESİPROKAL — onaylayan tenant rolleri + L0 aktör rolleri
    rb_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (RBAC rolleri — TÜKETİLİR)", rb_ok)
    if rb_ok:
        rbac = _load(RBAC_MODEL_PATH)
        roles = rbac.get("roles", {})
        chk("12.1.1 onaylayan rolleri SCO + owner mevcut + tenant realm (controller=tenant RESİPROKAL)",
            all(r in roles for r in APPROVER_ROLES)
            and roles.get("security_compliance_officer", {}).get("realm") == "tenant"
            and roles.get("tenant_owner", {}).get("realm") == "tenant")
        chk("12.1.1 L0 platform aktör rolleri (owner/sre/billing) mevcut + platform realm (RESİPROKAL)",
            all(role in roles for role in PLATFORM_ROLES)
            and all(roles.get(role, {}).get("realm") == "platform" for role in PLATFORM_ROLES))

    # 14) 12.1.8 RESİPROKAL — WORM audit (append-only + hash-zincir)
    wm_ok = os.path.exists(WORM_MODEL_PATH)
    chk("12.1.8 ../worm-audit/config/worm-audit-model.json var (WORM audit — TÜKETİLİR)", wm_ok)
    if wm_ok:
        wm = _load(WORM_MODEL_PATH)
        chk("12.1.8 worm_policy append_only=true (RESİPROKAL audit immutability)",
            wm.get("worm_policy", {}).get("append_only") is True)
        chk("12.1.8 integrity_policy hash_chain + sha256 (RESİPROKAL row_hash)",
            wm.get("integrity_policy", {}).get("hash_chain") is True
            and wm.get("integrity_policy", {}).get("hash_algo") == "sha256")

    # 15) Sır/PII/token tarayıcı — spec + model + samples
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
    chk("hiç ham-içerik/PII/token sızıntısı yok (C12)", total_leaks == 0)

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

    def ev(**kw):
        # Varsayılan: platform_owner, transcript, GRANT_TIER_B, REGÜLE tenant + DPA imzalı + GEÇERLİ tenant onayı
        # (SCO, tenant realm, target_tenant + break_glass_id bağlı) → ALLOW (tenant_approved) + audit.
        d = {
            "request_id": "req-1", "correlation_id": "corr-1", "break_glass_id": "bg-1",
            "actor_role": "platform_owner", "target_tenant_id": "t-acme", "tier": "B",
            "resource_type": "transcript", "data_class": "tenant_content",
            "access_decision": "GRANT_TIER_B", "regulated": True, "dpa_signed": True,
            "tenant_approval": {"role": "security_compliance_officer", "realm": "tenant",
                                "tenant_id": "t-acme", "break_glass_id": "bg-1"},
            "now": 100,
        }
        d.update(kw)
        return d

    # 1) happy — regüle + DPA + geçerli onay → ALLOW (tenant_approved), ihlal yok
    r = build(ev(), spec)
    case("happy: ALLOW (regüle + DPA + geçerli tenant onayı)", r["terminal"] == "ALLOW" and r["note"] == "tenant_approved")
    case("happy: require_tenant_approval=true (regüle default açık)", r["require_tenant_approval"] is True)
    case("happy: tenant_approved=True + approver_role=SCO", r["tenant_approved"] is True and r["approver_role"] == "security_compliance_officer")
    case("happy: dpa_bound=True", r["dpa_bound"] is True)
    case("happy: audit_emitted=True + row_hash var (WORM)",
         r["audit_emitted"] is True and r["audit_record"].get("row_hash") is not None)
    case("happy: break_glass_id audit'te", r["audit_record"].get("break_glass_id") is not None)
    case("happy: model_hash var (C10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(ev(), spec), build(ev(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) C1 — access routing: PENDING/DENY → HOLD (12.3.2 grant etmedi)
    rpend = build(ev(access_decision="PENDING"), spec)
    case("routing: PENDING → HOLD (access_not_granted)", rpend["terminal"] == "HOLD" and rpend["note"] == "access_not_granted")
    case("routing: PENDING doğru → ihlal yok + kapı geçer",
         all(x == 0 for x in rpend["violations"].values()) and _gate_eval(rpend, G)[0] is True)
    rden = build(ev(access_decision="DENY"), spec)
    case("routing: DENY → HOLD (erişim açılmıyor)", rden["terminal"] == "HOLD")
    case("routing: DENY de audit'lenir (her break-glass girişimi)", rden["audit_emitted"] is True)

    # 4) C2 ÇEKİRDEK regüle varsayılan açık — non-regüle → ALLOW; regüle → onay gerekir
    rnonreg = build(ev(regulated=False, tenant_approval=None, dpa_signed=False), spec)
    case("regulated: regüle değil + onay yok → ALLOW (not_regulated)",
         rnonreg["terminal"] == "ALLOW" and rnonreg["note"] == "not_regulated")
    case("regulated: regüle değil → require_tenant_approval=false + ihlal yok",
         rnonreg["require_tenant_approval"] is False and all(x == 0 for x in rnonreg["violations"].values()))
    case("regulated: regüle tenant → require_tenant_approval=true (default açık)",
         build(ev(), spec)["require_tenant_approval"] is True)
    # degrade disable_regulated_toggle → regulated_toggle_off + ALLOW (gate atlandı)
    rdis = build(ev(tenant_approval=None), spec, inject=["disable_regulated_toggle"])
    case("regulated degrade: disable_regulated_toggle → regulated_toggle_off>0 + ALLOW + kapı eler",
         rdis["violations"]["regulated_toggle_off"] > 0 and rdis["terminal"] == "ALLOW"
         and _gate_eval(rdis, G)[0] is False)

    # 5) C3 ÇEKİRDEK onaysız açılmaz — onay yok → HOLD; degrade bypass → tenant_approval_bypassed
    rnoappr = build(ev(tenant_approval=None), spec)
    case("approval-gate: onay yok → HOLD (awaiting_tenant_approval)",
         rnoappr["terminal"] == "HOLD" and rnoappr["note"] == "awaiting_tenant_approval")
    case("approval-gate: doğru → tenant_approval_bypassed=0 + kapı geçer",
         rnoappr["violations"]["tenant_approval_bypassed"] == 0 and _gate_eval(rnoappr, G)[0] is True)
    rbyp = build(ev(tenant_approval=None), spec, inject=["bypass_tenant_approval"])
    case("approval-gate degrade: bypass_tenant_approval → ALLOW + tenant_approval_bypassed>0 + kapı eler",
         rbyp["terminal"] == "ALLOW" and rbyp["violations"]["tenant_approval_bypassed"] > 0
         and _gate_eval(rbyp, G)[0] is False)

    # 6) C4 ÇEKİRDEK onay yetkisi — platform self-approval / cross-realm → approval_authority_violation
    rself = build(ev(tenant_approval=None), spec, inject=["platform_self_approve"])
    case("authority degrade: platform_self_approve → approval_authority_violation>0 + ALLOW + kapı eler",
         rself["violations"]["approval_authority_violation"] > 0 and rself["terminal"] == "ALLOW"
         and _gate_eval(rself, G)[0] is False)
    rxrealm = build(ev(tenant_approval={"role": "tenant_owner", "realm": "platform",
                                        "tenant_id": "t-acme", "break_glass_id": "bg-1"}), spec, inject=["cross_realm_approval"])
    case("authority degrade: cross_realm_approval → approval_authority_violation>0 + kapı eler",
         rxrealm["violations"]["approval_authority_violation"] > 0 and _gate_eval(rxrealm, G)[0] is False)
    # doğru: tenant realm dışı onay (degrade'siz) geçersiz → HOLD
    rbadrealm = build(ev(tenant_approval={"role": "tenant_owner", "realm": "platform",
                                          "tenant_id": "t-acme", "break_glass_id": "bg-1"}), spec)
    case("authority: realm=platform onay geçersiz → HOLD (awaiting)", rbadrealm["terminal"] == "HOLD")

    # 7) C5 ÇEKİRDEK DPA bağı — regüle + DPA'sız → BLOCK; degrade unbind_dpa → dpa_unbound
    rnodpa = build(ev(dpa_signed=False), spec)
    case("dpa: regüle + DPA imzasız → BLOCK (dpa_unbound)", rnodpa["terminal"] == "BLOCK" and rnodpa["note"] == "dpa_unbound")
    case("dpa: doğru → dpa_unbound=0 + kapı geçer",
         rnodpa["violations"]["dpa_unbound"] == 0 and _gate_eval(rnodpa, G)[0] is True)
    runb = build(ev(dpa_signed=False), spec, inject=["unbind_dpa"])
    case("dpa degrade: unbind_dpa → dpa_unbound>0 + ALLOW (DPA'sız açıldı) + kapı eler",
         runb["violations"]["dpa_unbound"] > 0 and runb["terminal"] == "ALLOW"
         and _gate_eval(runb, G)[0] is False)

    # 8) C6 override yalnız-sıkılaştırır — non-regüle override on → required true (sıkılaştırma serbest)
    ron = build(ev(regulated=False, tenant_override="on", tenant_approval=None, dpa_signed=True), spec)
    case("override: non-regüle + override=on → require_tenant_approval=true (sıkılaştırma) → HOLD onaysız",
         ron["require_tenant_approval"] is True and ron["terminal"] == "HOLD")
    # degrade loosen_override → override_loosened (regüle default-on gevşetildi)
    rloose = build(ev(tenant_override="off", tenant_approval=None), spec, inject=["loosen_override"])
    case("override degrade: loosen_override → override_loosened>0 + ALLOW + kapı eler",
         rloose["violations"]["override_loosened"] > 0 and rloose["terminal"] == "ALLOW"
         and _gate_eval(rloose, G)[0] is False)
    # doğru: regüle + override off (gevşetme uygulanmaz) → required STILL true → HOLD onaysız
    roff = build(ev(tenant_override="off", tenant_approval=None), spec)
    case("override: regüle + override=off (gevşetme uygulanmaz) → require_tenant_approval=true",
         roff["require_tenant_approval"] is True and roff["terminal"] == "HOLD")

    # 9) C7 onay binding — cross-tenant onay → approval_misbinding
    rxt = build(ev(tenant_approval={"role": "security_compliance_officer", "realm": "tenant",
                                    "tenant_id": "t-other", "break_glass_id": "bg-1"}), spec, inject=["cross_tenant_approval"])
    case("binding degrade: cross_tenant_approval → approval_misbinding>0 + kapı eler",
         rxt["violations"]["approval_misbinding"] > 0 and _gate_eval(rxt, G)[0] is False)
    # doğru: cross-tenant onay (degrade'siz) geçersiz → HOLD
    rxt2 = build(ev(tenant_approval={"role": "security_compliance_officer", "realm": "tenant",
                                     "tenant_id": "t-other", "break_glass_id": "bg-1"}), spec)
    case("binding: cross-tenant onay geçersiz → HOLD (awaiting)", rxt2["terminal"] == "HOLD")

    # 10) C8 replay-safe — çözülmüş onay → HOLD; degrade replay_approval → approval_replay
    rrep = build(ev(prior_state="CONSUMED"), spec)
    case("replay: prior_state=CONSUMED → HOLD (already_resolved)", rrep["terminal"] == "HOLD" and rrep["note"] == "already_resolved")
    rrepi = build(ev(prior_state="CONSUMED"), spec, inject=["replay_approval"])
    case("replay degrade: replay_approval → ALLOW + approval_replay>0 + kapı eler",
         rrepi["terminal"] == "ALLOW" and rrepi["violations"]["approval_replay"] > 0
         and _gate_eval(rrepi, G)[0] is False)

    # 11) C9 — audit emitted/PII-free/immutable
    rsk = build(ev(), spec, inject=["skip_audit"])
    case("audit: skip_audit → unaudited_decision>0 + audit_emitted=False + kapı eler",
         rsk["violations"]["unaudited_decision"] > 0 and rsk["audit_emitted"] is False
         and _gate_eval(rsk, G)[0] is False)
    case("audit: HOLD/BLOCK de audit'lenir",
         build(ev(access_decision="DENY"), spec)["audit_emitted"] is True
         and build(ev(dpa_signed=False), spec)["audit_emitted"] is True)
    rpii = build(ev(), spec, inject=["leak_pii"])
    case("audit: leak_pii → audit_pii>0 + kapı eler",
         rpii["violations"]["audit_pii"] > 0 and _gate_eval(rpii, G)[0] is False)
    rmut = build(ev(), spec, inject=["mutate_audit"])
    case("audit: mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
         rmut["violations"]["audit_mutable"] > 0 and _gate_eval(rmut, G)[0] is False)
    case("audit: ham PII/token alanı yok",
         all(k not in json.dumps(r) for k in ("transcript_text_value", "recording_audio_value", "break_glass_token_value", "approval_token_value")))

    # 12) C10 — model integrity
    rtam = build(ev(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler",
         rtam["violations"]["model_tampered"] > 0 and _gate_eval(rtam, G)[0] is False)
    case("model_hash deterministik", build(ev(), spec)["model_hash"] == r["model_hash"])

    # 13) malformed → BLOCK
    case("malformed-noreq: BLOCK", build(ev(request_id=None), spec)["note"] == "malformed")
    case("malformed-norole: BLOCK", build(ev(actor_role="bogus"), spec)["note"] == "malformed")
    case("malformed-tenantrole: BLOCK (L0 rolü değil)",
         build(ev(actor_role="tenant_owner"), spec)["note"] == "malformed")
    case("malformed-notenant: BLOCK (target_tenant yok)",
         build(ev(target_tenant_id=None), spec)["note"] == "malformed")
    case("malformed-badtier: BLOCK (tier≠B)", build(ev(tier="A"), spec)["note"] == "malformed")
    case("malformed-badaccess: BLOCK (access_decision tanınmaz)",
         build(ev(access_decision="WHATEVER"), spec)["note"] == "malformed")

    # 14) evidence + leak
    case("evidence: request+actor+target_tenant+access+regulated+require_tenant_approval+dpa_bound+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "actor_role", "target_tenant_id", "access_decision",
                                          "regulated", "require_tenant_approval", "dpa_bound", "tenant_approved", "model_hash")))
    case("leak: rol+realm+sınıf+tier+profil temiz",
         scan_leaks('{"actor_role":"platform_owner","approver_role":"security_compliance_officer","realm":"tenant","data_class":"tenant_content","tier":"B","regulated":true,"regulated_profiles":["finance","health"]}') == [])
    case("leak: approval_token_value alanı yakalanır", len(scan_leaks('{"approval_token_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "break-glass-tier-b-approval (WBS 12.3.4 — Tier B break-glass: regüle tenant "
                  "require_tenant_approval toggle + DPA bağı; BRD §17, FR-IAM-010, SAD §14.4.2)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "data_class": "tenant_content",
        "actor_roles": sorted(PLATFORM_ROLES),
        "approver_roles": APPROVER_ROLES,
        "controller_role": "tenant",
        "processor_role": "rmc",
        "decision": "malformed ⇒ BLOCK(malformed) → access_decision ∈ {PENDING,DENY} ⇒ HOLD(access_not_granted) → "
                    "require_tenant_approval=false ⇒ ALLOW(not_regulated) → dpa_signed=false ⇒ BLOCK(dpa_unbound) → "
                    "prior_state çözülmüş ⇒ HOLD(already_resolved) → geçerli tenant onayı yok ⇒ HOLD(awaiting_tenant_approval) → "
                    "geçerli tenant onayı (tenant realm + target_tenant + break_glass_id) ⇒ ALLOW(tenant_approved) → audit emit (her karar)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ erişim geçersiz/DPA'sız; malformed ⇒ BLOCK; regüle + onaysız ⇒ HOLD (açılmaz); "
                     "12.3.2 grant etmedi ⇒ HOLD",
        "core_guarantees": [
            "C2 REGÜLE VARSAYILAN AÇIK: regulated profile → require_tenant_approval default true (regulated_toggle_off=0; FR-IAM-010)",
            "C3 ONAYSIZ AÇILMAZ: require_tenant_approval=true iken geçerli tenant onayı olmadan erişim açılmaz → HOLD (tenant_approval_bypassed=0)",
            "C4 ONAY YETKİSİ: onay tenant realm rolünden (controller=tenant); platform self-approval yok (approval_authority_violation=0)",
            "C5 DPA BAĞI: regüle kontrol imzalı DPA'ya bağlı (controller=tenant/processor=RMC); DPA'sız → BLOCK (dpa_unbound=0)",
            "C6 OVERRIDE YALNIZ-SIKILAŞTIRIR: tenant override regüle default-on'u gevşetemez (override_loosened=0; DPIA §8)",
            "C7 ONAY BINDING: onay yalnız target_tenant + break_glass_id'ye bağlı (approval_misbinding=0; FR-TEN-002)",
            "C9 AUDIT (WORM, PII/token-free, immutable): her karar DEĞİŞMEZ audit; unaudited_decision=0/audit_pii=0/audit_mutable=0 (12.1.8 RESİPROKAL)",
        ],
        "event_fields": ["name", "request_id", "correlation_id", "break_glass_id", "actor_role(platform_owner|platform_sre|platform_billing)",
                         "target_tenant_id", "tier(B)", "resource_type", "data_class(tenant_content)",
                         "access_decision(GRANT_TIER_B|PENDING|DENY — 12.3.2 çıktısı)", "regulated(bool — regüle profile)",
                         "tenant_override(on|off|yok — DPIA §8)", "dpa_signed(bool)",
                         "tenant_approval{role,realm,tenant_id,break_glass_id}(opsiyonel)", "now(tick=dakika)",
                         "prior_state(opsiyonel; CONSUMED/REVOKED/EXPIRED)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(ALLOW|HOLD|BLOCK)", "note", "actor_role", "target_tenant_id", "data_class",
                            "resource_type", "access_decision", "regulated", "require_tenant_approval", "dpa_bound",
                            "tenant_approved", "approver_role", "tier", "audit_emitted", "audit_record", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/tier-b-approval-model.json (frozen — regulated_policy[default_when_regulated + most_restrictive_wins + "
                 "override_tightens_only] + approval_policy[require_gate + approver_realm/roles + no_platform_self_approval + "
                 "binding] + dpa_policy[require_dpa_when_regulated + controller=tenant/processor=rmc + bind_to_dpa] + "
                 "concurrency_policy[replay-safe] + audit[WORM,PII/token-free] + actor_roles)",
        "consumes": "12.3.2 tier-b (access_decision GRANT_TIER_B/PENDING/DENY + break_glass_id RESİPROKAL); "
                    "12.1.1 rbac-model (SCO + owner onaylayan tenant rolleri + L0 aktör rolleri); 12.1.8 worm-audit "
                    "(append-only/WORM + hash-zincir RESİPROKAL); BRD §17 + FR-IAM-010 + SAD §14.4.2 (kaynak doğruluk)",
        "consumed_by": "12.3.5 (break-glass tam-audit router); 1.x F1/F2 kod (FastAPI break-glass router + regüle toggle "
                       "enforcement + tenant onay akışı + DPA bağı + WORM audit yazımı); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-IAM-010, FR-IAM-009, FR-IAM-006, FR-REC-009, BRD §17, SAD §14.4.2, ADR-013, DPIA §8, 12.3.2, 12.1.1, 12.1.8",
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
            print("kullanım: tier_b_approval_probe.py check <sample.json|dizin>")
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
