#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.7 — Maker-checker onay akışı referans probe.

12. workstream'in (IAM & Erişim) KRİTİK MUTASYON ONAY modülü ve F2-Should yeteneği. FR-IAM-005 ('Kritik
değişikliklerde maker-checker / onay mekanizması bulunmalıdır') + SR-IAM-005 ('Kritik değişiklikler maker-checker
onayı gerektirir [talep eden ≠ onaylayan]; aynı kullanıcı hem talep hem onay yapamaz; onaysız değişiklik canlıya
çıkmaz') + SAD §14.1/§14.4.2 ('maker-checker [FR-IAM-005] kritik mutasyonlarda onay durumu [pending→approved] ile
zorlanır')'i sahiplenir. 12.1.1 RBAC modelini (rol→IMMUTABLE bundle + realm, frozen) TÜKETİR; izin/kapsam kararını
12.1.2 (permission-key) + 12.1.3 (scoped assignment) SOYUT sonuç (maker.authorized / approval.authorized /
approval.scope_ok) olarak TÜKETİR; ÇIKTI olarak onay durum kararı (APPLIED ⇒ commit | PENDING | REJECTED | DENIED) üretir.

  ApprovalRequest ─malformed─► action ─► maker-auth ─► reason ─► tenant ─► timebox ─► approvals ─► durum
        │  ├─ alan eksik/biçimsiz ───────────────────────────────────────────────► DENIED (malformed_request)
        │  ├─ action ∉ kritik-aksiyon kataloğu ─────────────────────────────────► DENIED (unsupported_action)
        │  ├─ ¬maker.authorized (submit yetkisi yok) ───────────────────────────► DENIED (maker_unauthorized)     [S2]
        │  ├─ reason_code yok/boş (zorunlu gerekçe) ────────────────────────────► DENIED (reason_code_missing)
        │  ├─ maker.tenant_id ≠ request tenant_id ──────────────────────────────► DENIED (cross_tenant)           [S7]
        │  ├─ now > expires_at (onay penceresi kapandı) ────────────────────────► DENIED (expired)                [S6]
        │  │
        │  └─ approvals değerlendir (SoD + quorum):
        │       ├─ ∃ yetkili in-tenant checker decision=reject ─────────────────► REJECTED (commit YOK)
        │       ├─ distinct yetkili onay (≠ maker, taze, in-tenant) ≥ quorum ───► APPLIED (committed=true)  [S5 ÇEKİRDEK]
        │       └─ aksi (yetersiz onay) ────────────────────────────────────────► PENDING (awaiting checker; commit YOK)

ÇEKİRDEK: (1) S3 GÖREVLER AYRIMI / SoD (FR-IAM-005 / SR-IAM-005 ÇEKİRDEK) — TALEP EDEN ≠ ONAYLAYAN; maker AYNI talebi
onaylayamaz, kendi onayı quorum'a SAYILMAZ (sessizce dışlanır → yeterli değilse PENDING); maker'ın kendi onayını saymak
sod_violation=0 ihlali; (2) S5 ONAYSIZ CANLIYA ÇIKMAZ (SR-IAM-005 ÇEKİRDEK) — commit YALNIZ APPLIED'da (distinct
yetkili onay ≥ quorum); PENDING/REJECTED/DENIED → committed=false (applied_without_quorum=0, fail-closed); (3) S2 MAKER
YETKİSİ — yalnız submit yetkili maker talep açar (unauthorized_maker_accepted=0); (4) S4 ONAYLAYAN YETKİSİ/KAPSAMI —
onay quorum'a SAYILIR ⟺ authorized ∧ scope_ok (12.1.3) (unauthorized_approval=0); (5) S6 TIME-BOX — süresi dolmuş talep
DENIED, bayat onay sayılmaz (stale_approval_applied=0); (6) S7 TENANT İZOLASYONU (FR-TEN-002) — maker/onaylayan aynı
tenant (cross_tenant=0); (7) S8 QUORUM BÜTÜNLÜĞÜ — quorum FARKLI (distinct) onaylayanla dolar, aynı kişi tek sayılır
(quorum_tampered=0). Motor DETERMİNİSTİK FAIL-CLOSED karar fonksiyonu (Date.now/random YOK; sanal-saat tick tamsayı;
model_hash sha256 deterministik). Her karar terminal (S1) + kanıt (S9) + model bütünlük manifesti (S10); metrik
düşük-kardinalite + ham PII yok (S11); model/spec/sample ham token/credential/PII tutmaz — yalnız opak actor_ref +
aksiyon/rol adı + kapsam boyut anahtar/değeri + reason_code + tick + enum (S12).

SİMETRİK SIR / SAĞLAYICI-NÖTR (ADR-002): izin/kapsam doğrulaması bu modülde YAPILMAZ (credential-free) —
maker.authorized / approval.authorized / approval.scope_ok SOYUT doğrulama SONUÇLARIDIR (12.1.2/12.1.3'ten);
canlı onay UI + bildirim + backend guard 12.2.x/F2 entegrasyonunda.

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle çözümü (immutable, FR-IAM-001) → 12.1.1
(bu modül TÜKETİR — rol/realm tutarlılığı); permission-key gramer + katalog + aksiyon→izin çözümü → 12.1.2
(maker.authorized/approval.authorized soyut sonuç); rol+scope KAPSAM çözümü (kaynak attribute karşı) → 12.1.3
(approval.scope_ok soyut sonuç); backend panel guard (kritik mutasyon → onay enforcement) → 12.2.x; break-glass
Tier B time-box/bildirim (AYNI maker-checker çekirdeğini TÜKETİR) → FR-IAM-009 (12.x); append-only WORM audit
(onay kararı + reason_code) → 12.1.8; canlı onay UI/bildirim → F2.

Kullanım:
  maker_checker_probe.py validate          Statik model/spec/kapsama kapısı → çıkış kodu
  maker_checker_probe.py check <sample>     Onay karar motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  maker_checker_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  maker_checker_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK; sanal-saat tick tamsayı. Stdlib-only.
Sır/credential/anahtar ve ham token/PII (kullanıcı adı/e-posta/token) üretilmez/yazılmaz (fixture sentetik —
yalnız opak actor_ref + aksiyon/rol adı + kapsam boyut ID + reason_code + tick + enum; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "maker-checker-spec.json")
MC_MODEL_PATH = os.path.join(HERE, "config", "maker-checker-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["APPLIED", "PENDING", "REJECTED", "DENIED"]
TERMINAL = {"APPLIED", "PENDING", "REJECTED", "DENIED"}
COMMIT_TERMINALS = {"APPLIED"}
RULES = ["separation_of_duties", "no_apply_without_approval", "maker_authority", "approver_authority",
         "time_box_freshness", "tenant_isolation", "quorum_integrity"]
DENY_REASONS = ["malformed_request", "unsupported_action", "maker_unauthorized", "reason_code_missing",
                "cross_tenant", "expired"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
DECISIONS = {"approve", "reject"}

# Degrade (inject) — DOĞRU SoD/quorum/yetki/timebox/tenant davranışını bozan müdahaleler.
INJECTIONS = {"self_approval", "apply_without_quorum", "accept_unauthorized_maker", "accept_unauthorized_approver",
              "apply_expired", "cross_tenant", "duplicate_approver_quorum", "reason_bypass",
              "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "sod_violation", "applied_without_quorum", "unauthorized_maker_accepted", "unauthorized_approval",
    "stale_approval_applied", "cross_tenant", "quorum_tampered", "reason_bypassed",
    "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.1/12.1.4/12.1.6 deseniyle) — ham token/PII/sır yasak; actor/aksiyon/rol/kapsam ID beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|private[_-]?key|credential|client[_-]?secret)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt_blob", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("pii_field", re.compile(r"(?i)\"(nameid_value|email_value|customer_phone_value|card_pan_value|otp_code_value|password_value|customer_name_value|display_name_value|address_value|token_value|bearer_value|signature_bytes|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|corr-|actor-|mk-|ck-|ap-|u-|t-|sub-|brand-|dept-|camp-|rc-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham token/PII/sır tarayıcı. Yorum/tarif satırı + actor/aksiyon/rol/kapsam ID + maskeli token eler (12.1.6 deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 16):m.end() + 16]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line or '"$note"' in line or line.strip().startswith('"$'):
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _canon_hash(obj):
    """Model bütünlük manifesti: sha256(kanonik JSON) — deterministik (sort_keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rbac_model():
    """Rol bundle + realm modeli = 12.1.1 config/rbac-roles.json (frozen, IMMUTABLE). TÜKETİLİR."""
    return _load(RBAC_MODEL_PATH)


def _mc_model():
    """Maker-checker modeli = config/maker-checker-model.json (frozen — SoD/commit/timebox/reason/tenant/quorum)."""
    return _load(MC_MODEL_PATH)


def _role_realm(role, rbac):
    """Bir rolün realm'i (12.1.1 frozen modelinden); rol yoksa None."""
    spec = rbac["roles"].get(role)
    return spec.get("realm") if spec else None


def build(sample, spec, inject=None, rbac=None, mc_model=None):
    """Tek maker-checker onay senaryosunu yürüt → ApprovalDecision + ihlal sayaçları.

    Motor DOĞRU SoD/quorum/yetki/timebox/tenant davranışını hesaplar; inject (degrade) doğru davranışı bozar
    ve eşleşen ihlal sayacını artırır (12.1.6 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    rbac = rbac if rbac is not None else _rbac_model()
    mc_model = mc_model if mc_model is not None else _mc_model()

    request_id = sample.get("request_id")
    tenant_id = sample.get("tenant_id")
    actor_realm = sample.get("actor_realm")
    action = sample.get("action")
    resource = dict(sample.get("resource", {}) or {})
    maker = dict(sample.get("maker", {}) or {})
    reason_code = sample.get("reason_code")
    approvals = sample.get("approvals", [])
    expires_at = sample.get("expires_at")
    now = sample.get("now")

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    deny_reason = None          # DENIED gerekçesi (fail-closed taksonomi)
    pending_reason = None       # PENDING gerekçesi (insufficient_approvals)
    reject_reason = None        # REJECTED gerekçesi (checker_rejected)
    committed = False
    quorum_required = None
    counted = []                # quorum'a sayılan (distinct) onaylayan actor_ref'leri

    catalog = mc_model.get("critical_actions", {}) or {}

    # ── S10 model bütünlük manifesti (frozen maker-checker model + 12.1.1 rol bundle/realm) ──
    canonical_model = {
        "mc": {"frozen": mc_model.get("frozen"),
               "separation_of_duties": mc_model.get("separation_of_duties"),
               "commit_policy": mc_model.get("commit_policy"),
               "critical_actions": mc_model.get("critical_actions")},
        "rbac": {"frozen": rbac.get("frozen"), "roles": rbac.get("roles")},
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["mc"]["separation_of_duties"]["require_distinct_maker_checker"] = False
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not tenant_id or actor_realm not in REALMS
                 or action is None or not isinstance(resource, dict)
                 or not isinstance(maker, dict) or not maker
                 or not maker.get("actor_ref")
                 or not isinstance(approvals, list)
                 or not isinstance(now, int) or isinstance(now, bool)
                 or not isinstance(expires_at, int) or isinstance(expires_at, bool))

    if malformed:
        terminal, deny_reason = "DENIED", "malformed_request"
    elif action not in catalog:
        terminal, deny_reason = "DENIED", "unsupported_action"
    else:
        quorum_required = catalog[action].get("min_quorum", mc_model.get("commit_policy", {}).get("default_quorum", 1))
        maker_ref = maker.get("actor_ref")
        maker_authed = bool(maker.get("authorized", False))
        maker_tenant = maker.get("tenant_id")

        # ── S2 maker yetkisi: submit izni olmayan maker ──
        if "accept_unauthorized_maker" in inject and not maker_authed:
            v["unauthorized_maker_accepted"] += 1
            maker_authed = True  # yetkisiz maker'ı kabul et (degrade)

        # ── S7 tenant izolasyonu (FR-TEN-002): maker.tenant_id = request tenant_id ──
        cross = maker_tenant is not None and maker_tenant != tenant_id
        if "cross_tenant" in inject:
            if cross:
                v["cross_tenant"] += 1
            cross = False  # izolasyonu atla (degrade)
        elif cross:
            v["cross_tenant"] += 1

        # ── zorunlu gerekçe ──
        reason_required = mc_model.get("reason_policy", {}).get("reason_code_required", True)
        reason_missing = reason_required and not reason_code
        if "reason_bypass" in inject and reason_missing:
            v["reason_bypassed"] += 1
            reason_missing = False  # gerekçesiz devam (degrade)

        # ── S6 time-box: now > expires_at → talep süresi doldu ──
        expired = now > expires_at
        apply_expired = "apply_expired" in inject

        if not maker_authed:
            terminal, deny_reason = "DENIED", "maker_unauthorized"
        elif reason_missing:
            terminal, deny_reason = "DENIED", "reason_code_missing"
        elif cross:
            terminal, deny_reason = "DENIED", "cross_tenant"
        elif expired and not apply_expired:
            terminal, deny_reason = "DENIED", "expired"
        else:
            if expired and apply_expired:
                v["stale_approval_applied"] += 1  # süresi dolmuş talebi uygula (degrade)

            # ── S3/S4/S6/S7/S8 onayları değerlendir ──
            reject_present = False
            seen = set()
            for ap in approvals:
                aref = ap.get("approver_ref")
                dec = ap.get("decision")
                a_authed = bool(ap.get("authorized", False))
                a_scope = bool(ap.get("scope_ok", False))
                a_tenant = ap.get("tenant_id")
                a_realm = ap.get("realm", actor_realm)
                a_at = ap.get("at")
                in_context = (a_tenant == tenant_id) and (a_realm == actor_realm)
                is_self = (aref == maker_ref)
                fresh = (isinstance(a_at, int) and not isinstance(a_at, bool)
                         and (a_at <= expires_at or apply_expired))

                # ── yetkili in-tenant checker reddi → REJECTED ──
                if dec == "reject" and a_authed and in_context and not is_self:
                    reject_present = True
                if dec != "approve":
                    continue

                # ── S3 ÇEKİRDEK: maker kendi talebini onaylayamaz ──
                self_block = is_self
                if "self_approval" in inject and self_block:
                    v["sod_violation"] += 1
                    self_block = False  # maker'ın kendi onayını say (degrade)

                # ── S4 onaylayan yetkisi/kapsamı ──
                auth_block = (not a_authed) or (not a_scope)
                if "accept_unauthorized_approver" in inject and auth_block:
                    v["unauthorized_approval"] += 1
                    auth_block = False  # yetkisiz/kapsam-dışı onayı say (degrade)

                if self_block or auth_block or not in_context or not fresh:
                    continue

                # ── S8 distinct (dedupe by actor_ref) ──
                if aref in seen:
                    if "duplicate_approver_quorum" in inject:
                        v["quorum_tampered"] += 1
                        counted.append(aref)  # aynı kişiyi tekrar say (degrade)
                    continue
                seen.add(aref)
                counted.append(aref)

            distinct_count = len(counted)

            if reject_present:
                terminal, reject_reason = "REJECTED", "checker_rejected"
            elif distinct_count >= quorum_required:
                terminal, committed = "APPLIED", True
            elif "apply_without_quorum" in inject:
                # ── S5 ÇEKİRDEK degrade: quorum dolmadan commit ──
                v["applied_without_quorum"] += 1
                terminal, committed = "APPLIED", True
            else:
                terminal, pending_reason = "PENDING", "insufficient_approvals"

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, tenant_id, actor_realm, action, maker, reason_code, counted,
                         committed, deny_reason, pending_reason, reject_reason, quorum_required,
                         now, expires_at, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, deny_reason, pending_reason, reject_reason, committed,
                 action, actor_realm, quorum_required, counted, maker.get("actor_ref"),
                 model_hash, evidence)


def _evidence(request_id, tenant_id, actor_realm, action, maker, reason_code, counted, committed,
              deny_reason, pending_reason, reject_reason, quorum_required, now, expires_at, model_hash):
    """Yapısal kanıt — ham token/kullanıcı adı/e-posta YOK; yalnız opak actor_ref + aksiyon/rol adı + reason_code."""
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "actor_realm": actor_realm,
        "action": action,
        "maker_ref": maker.get("actor_ref"),
        "maker_role": maker.get("role"),
        "reason_code": reason_code,
        "quorum_required": quorum_required,
        "approver_refs": list(counted),
        "committed": committed,
        "now": now,
        "expires_at": expires_at,
        "deny_reason": deny_reason,
        "pending_reason": pending_reason,
        "reject_reason": reject_reason,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, deny_reason, pending_reason, reject_reason, committed, action,
          actor_realm, quorum_required, counted, maker_ref, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "deny_reason": deny_reason,
        "pending_reason": pending_reason,
        "reject_reason": reject_reason,
        "committed": committed,
        "action": action,
        "actor_realm": actor_realm,
        "quorum_required": quorum_required,
        "valid_approver_count": len(counted),
        "approver_refs": list(counted),
        "maker_ref": maker_ref,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "sod_violation": "max_sod_violation",
        "applied_without_quorum": "max_applied_without_quorum",
        "unauthorized_maker_accepted": "max_unauthorized_maker_accepted",
        "unauthorized_approval": "max_unauthorized_approval",
        "stale_approval_applied": "max_stale_approval_applied",
        "cross_tenant": "max_cross_tenant",
        "quorum_tampered": "max_quorum_tampered",
        "reason_bypassed": "max_reason_bypassed",
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
        for key in ("terminal", "deny_reason", "pending_reason", "reject_reason", "committed"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s committed=%s reason=%s/%s/%s action=%s quorum=%d/%s approvers=%s"
              % (res["terminal"], res["committed"], res["deny_reason"], res["pending_reason"],
                 res["reject_reason"], res["action"], res["valid_approver_count"],
                 res["quorum_required"], res["approver_refs"]))
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
              "deny_reasons", "outcomes", "model", "approval", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.1.7", spec.get("wbs") == "12.1.7")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Should", spec.get("priority") == "Should")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement credential_free=true (ADR-002)", spec.get("placement", {}).get("credential_free") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-005 izlenir (maker-checker — ÇEKİRDEK)", "FR-IAM-005" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SR-IAM-005 izlenir", "SR-IAM-005" in tr.get("srs", []))
    chk("TC-IAM-005 izlenir", "TC-IAM-005" in tr.get("rtm", []))
    chk("SAD §14.4.2 maker-checker pending→approved izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("12.1.1 RBAC modeli TÜKETİLİR (consumes)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.2 permission-key TÜKETİLİR (consumes — authorized soyut)", any("12.1.2" in s for s in tr.get("consumes", [])))
    chk("12.1.3 scoped assignment TÜKETİLİR (consumes — scope_ok soyut)", any("12.1.3" in s for s in tr.get("consumes", [])))
    chk("12.2.x panel guard TÜKETİR (consumed_by)", any("12.2" in s for s in tr.get("consumed_by", [])))
    chk("break-glass Tier B (FR-IAM-009) TÜKETİR (consumed_by — AYNI çekirdek)",
        any("FR-IAM-009" in s for s in tr.get("consumed_by", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (sod/no-apply/maker/approver/timebox/tenant/quorum)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→action→maker_auth→reason→tenant→timebox→approvals fail-closed",
        rz.get("evaluation") == "malformed_then_action_then_maker_auth_then_reason_then_tenant_then_timebox_then_approvals_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)
    chk("separation_of_duties kuralı S3 ÇEKİRDEK (talep eden ≠ onaylayan)",
        any(d["id"] == "separation_of_duties" and d.get("invariant") == "S3" for d in rz.get("list", [])))
    chk("no_apply_without_approval kuralı S5 ÇEKİRDEK (onaysız canlıya çıkmaz)",
        any(d["id"] == "no_apply_without_approval" and d.get("invariant") == "S5" for d in rz.get("list", [])))

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=DENIED (fail-closed)", dec.get("default") == "DENIED")
    chk("fail_safe no commit", "no commit" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar APPLIED/PENDING/REJECTED/DENIED", set(oc.get("list", [])) == set(OUTCOMES))
    dr = set(spec["deny_reasons"].get("list", []))
    chk("deny_reason taksonomisi tam (6)", dr == set(DENY_REASONS))

    # 6) Model — frozen + sod + commit + quorum
    md = spec["model"]
    chk("model frozen=true", md.get("frozen") is True)
    chk("sod_required=true (talep eden ≠ onaylayan; ÇEKİRDEK)", md.get("sod_required") is True)
    chk("self_approval_counts_to_quorum=false (S3)", md.get("self_approval_counts_to_quorum") is False)
    chk("commit_only_on_applied=true (onaysız canlıya çıkmaz; ÇEKİRDEK)", md.get("commit_only_on_applied") is True)
    chk("reason_code_required=true", md.get("reason_code_required") is True)
    chk("expired_request_denied=true (S6)", md.get("expired_request_denied") is True)
    chk("require_distinct_approvers=true (S8)", md.get("require_distinct_approvers") is True)
    chk("rbac_model 12.1.1'e referans", "12.1.1" in md.get("rbac_model", ""))

    # 7) Approval — kapılar + sod/quorum/timebox kuralı
    az = spec["approval"]
    chk("maker_auth_gate (S2)", "maker_unauthorized" in az.get("maker_auth_gate", ""))
    chk("action_gate (katalog dışı → unsupported_action)", "unsupported_action" in az.get("action_gate", ""))
    chk("reason_gate (zorunlu gerekçe)", "reason_code" in az.get("reason_gate", ""))
    chk("tenant_gate (cross-tenant DENIED; FR-TEN-002)", "FR-TEN-002" in az.get("tenant_gate", ""))
    chk("timebox_gate (now ≤ expires_at; S6)", "expires_at" in az.get("timebox_gate", ""))
    chk("sod_rule (onaylayan ≠ maker; ÇEKİRDEK; S3)",
        "ÇEKİRDEK" in az.get("sod_rule", "") and "sod_violation=0" in az.get("sod_rule", ""))
    chk("quorum_rule (distinct yetkili onay ≥ quorum → APPLIED; SR-IAM-005)",
        "quorum" in az.get("quorum_rule", "") and "APPLIED" in az.get("quorum_rule", ""))
    chk("karar backend'de", az.get("decision_at") == "backend")
    chk("produces committed=true yalnız APPLIED + WORM audit (12.1.8)",
        "committed=true" in az.get("produces", "") and "12.1.8" in az.get("produces", ""))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_sod_violation", "max_applied_without_quorum", "max_unauthorized_maker_accepted",
               "max_unauthorized_approval", "max_stale_approval_applied", "max_cross_tenant",
               "max_quorum_tampered", "max_reason_bypassed", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("makerchecker_request_total metrik", "makerchecker_request_total" in obs.get("metrics", []))
    chk("makerchecker_applied_total metrik (commit olayı)", "makerchecker_applied_total" in obs.get("metrics", []))
    chk("makerchecker_sod_violation_total metrik (S3 alarm)",
        "makerchecker_sod_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/maker_ref/approver_ref/reason_code YÜKSEK kard (label değil)",
        "request_id" in hi and "maker_ref" in hi and "approver_ref" in hi and "reason_code" in hi and "request_id" not in lo)
    chk("action_class/result/actor_realm DÜŞÜK kard (label uygun)",
        "action_class" in lo and "result" in lo and "actor_realm" in lo)
    chk("alarm sod/applied_without_quorum/unauthorized ≤2dk",
        any(x in obs.get("alarm", "") for x in ("sod_violation", "applied_without_quorum", "unauthorized_approval")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)
    chk("S3 SoD çekirdek invariant'ı (talep eden ≠ onaylayan)",
        any(i["id"] == "S3" and "TALEP EDEN ≠ ONAYLAYAN" in i.get("claim", "") for i in spec["invariants"]))
    chk("S5 onaysız canlıya çıkmaz çekirdek invariant'ı",
        any(i["id"] == "S5" and "canlıya çıkmaz" in i.get("claim", "") for i in spec["invariants"]))

    # 11) Maker-checker modeli dosyası + içsel tutarlılık
    mc_ok = os.path.exists(MC_MODEL_PATH)
    chk("config/maker-checker-model.json var", mc_ok)
    if mc_ok:
        mc = _mc_model()
        chk("mc model frozen=true", mc.get("frozen") is True)
        chk("mc model fail_closed=true", mc.get("fail_closed") is True)
        sod = mc.get("separation_of_duties", {})
        chk("mc model require_distinct_maker_checker=true (S3 ÇEKİRDEK)", sod.get("require_distinct_maker_checker") is True)
        chk("mc model self_approval_counts_to_quorum=false (S3)", sod.get("self_approval_counts_to_quorum") is False)
        cp = mc.get("commit_policy", {})
        chk("mc model commit_only_on_applied=true (S5 ÇEKİRDEK)", cp.get("commit_only_on_applied") is True)
        chk("mc model apply_requires_quorum=true (S5)", cp.get("apply_requires_quorum") is True)
        chk("mc model no_commit_on_pending=true (S5)", cp.get("no_commit_on_pending") is True)
        tb = mc.get("timebox_policy", {})
        chk("mc model expired_request_denied=true (S6)", tb.get("expired_request_denied") is True)
        chk("mc model stale_approval_not_counted=true (S6)", tb.get("stale_approval_not_counted") is True)
        rp = mc.get("reason_policy", {})
        chk("mc model reason_code_required=true", rp.get("reason_code_required") is True)
        ti = mc.get("tenant_isolation", {})
        chk("mc model maker_bound_to_tenant=true (FR-TEN-002)", ti.get("maker_bound_to_tenant") is True)
        qp = mc.get("quorum_policy", {})
        chk("mc model require_distinct_approvers=true (S8)", qp.get("require_distinct_approvers") is True)
        cat = mc.get("critical_actions", {})
        chk("mc model kritik-aksiyon kataloğu ≥5 aksiyon", len(cat) >= 5)
        chk("mc model her aksiyon requires_approval=true + min_quorum",
            all(a.get("requires_approval") is True and isinstance(a.get("min_quorum"), int) for a in cat.values()))
        chk("mc model ≥1 quorum>1 aksiyon (çoklu onay)", any(a.get("min_quorum", 1) > 1 for a in cat.values()))
        chk("mc model privacy no_raw_token_persisted=true", mc.get("privacy", {}).get("no_raw_token_persisted") is True)

    # 12) 12.1.1 RBAC modeli erişilebilir (consumes) + realm taşır
    rbac_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rbac_ok)
    if rbac_ok:
        rbac = _rbac_model()
        chk("12.1.1 rbac frozen=true (IMMUTABLE)", rbac.get("frozen") is True)
        chk("12.1.1 12 rol (BRD §17.2)", len(rbac.get("roles", {})) == 12)
        chk("tenant_owner realm=tenant (onaylayan adayı)", _role_realm("tenant_owner", rbac) == "tenant")
        chk("platform_owner realm=platform (L0 onay ayrı realm)", _role_realm("platform_owner", rbac) == "platform")

    # 13) Sır/PII tarayıcı — spec + modeller + samples
    scan_files = [SPEC_PATH, MC_MODEL_PATH] + (
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
    chk("hiç ham-token/PII/sır sızıntısı yok (S12)", total_leaks == 0)

    # 14) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
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
        # Varsayılan: yetkili tenant maker (mk-1) 'agent.publish' (quorum=1) talep eder; farklı yetkili in-tenant
        # checker (ck-1) onaylar → APPLIED/commit. now=10 ≤ expires_at=100; reason_code dolu.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_realm": "tenant", "action": "agent.publish",
            "reason_code": "rc-prod-release", "now": 10, "expires_at": 100,
            "resource": {"subject_ref": "agent-7", "scope": {"brand": ["brand-x"]}},
            "maker": {"actor_ref": "mk-1", "role": "conversation_designer", "authorized": True,
                      "tenant_id": "t-acme", "realm": "tenant"},
            "approvals": [
                {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
                 "tenant_id": "t-acme", "realm": "tenant", "at": 20},
            ],
        }
        for k, val in kw.items():
            if k in ("resource", "maker") and isinstance(val, dict):
                merged = dict(d[k]); merged.update(val); d[k] = merged
            else:
                d[k] = val
        return d

    # 1) happy → APPLIED + committed
    r = build(req(), spec)
    case("happy: APPLIED", r["terminal"] == "APPLIED")
    case("happy: committed=true", r["committed"] is True)
    case("happy: distinct onaylayan ck-1", r["approver_refs"] == ["ck-1"])
    case("happy: model_hash var (S10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) PENDING — hiç onay yok → commit YOK (fail-closed)
    r = build(req(approvals=[]), spec)
    case("no-approval: PENDING", r["terminal"] == "PENDING" and r["pending_reason"] == "insufficient_approvals")
    case("no-approval: committed=false (onaysız canlıya çıkmaz)", r["committed"] is False)
    case("no-approval: ihlal yok (meşru bekleme)", all(x == 0 for x in r["violations"].values()) and _gate_eval(r, G)[0] is True)

    # 4) S3 ÇEKİRDEK — maker kendi talebini onaylar → kendi onayı SAYILMAZ → PENDING
    r = build(req(approvals=[{"approver_ref": "mk-1", "decision": "approve", "authorized": True,
                              "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]), spec)
    case("self-approval: maker onayı sayılmaz → PENDING", r["terminal"] == "PENDING")
    case("self-approval: committed=false", r["committed"] is False)
    case("self-approval: sod_violation=0 (doğru dışlama)", r["violations"]["sod_violation"] == 0 and _gate_eval(r, G)[0] is True)

    # 4b) maker self-approve + farklı checker → APPLIED (maker dışlanır, ck-1 sayılır)
    r = build(req(approvals=[
        {"approver_ref": "mk-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 20},
        {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 25}]), spec)
    case("self+distinct: APPLIED (yalnız ck-1 sayılır)", r["terminal"] == "APPLIED" and r["approver_refs"] == ["ck-1"])

    # 5) REJECTED — yetkili checker reddi → commit YOK
    r = build(req(approvals=[{"approver_ref": "ck-1", "decision": "reject", "authorized": True,
                              "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]), spec)
    case("reject: REJECTED checker_rejected", r["terminal"] == "REJECTED" and r["reject_reason"] == "checker_rejected")
    case("reject: committed=false + kapı geçer", r["committed"] is False and _gate_eval(r, G)[0] is True)

    # 6) quorum=2 — iki distinct onay → APPLIED; tek onay → PENDING
    r = build(req(action="compliance_profile.update", approvals=[
        {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 20},
        {"approver_ref": "ck-2", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 25}]), spec)
    case("quorum2: iki distinct onay → APPLIED", r["terminal"] == "APPLIED" and r["quorum_required"] == 2)
    r = build(req(action="compliance_profile.update"), spec)  # tek onay (ck-1)
    case("quorum2: tek onay → PENDING (commit YOK)", r["terminal"] == "PENDING" and r["committed"] is False)

    # 6b) S8 distinct — aynı checker iki kez (quorum2) → tek sayılır → PENDING
    r = build(req(action="compliance_profile.update", approvals=[
        {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 20},
        {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 25}]), spec)
    case("quorum2: duplicate checker tek sayılır → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 1)

    # 7) S4 onaylayan yetkisi — yetkisiz/kapsam-dışı onay sayılmaz → PENDING
    r = build(req(approvals=[{"approver_ref": "ck-1", "decision": "approve", "authorized": False,
                              "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]), spec)
    case("unauthorized-approver: sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)
    r = build(req(approvals=[{"approver_ref": "ck-1", "decision": "approve", "authorized": True,
                              "scope_ok": False, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]), spec)
    case("out-of-scope-approver: sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)

    # 8) S2 maker yetkisi — yetkisiz maker → DENIED maker_unauthorized
    r = build(req(maker={"authorized": False}), spec)
    case("maker-unauth: DENIED maker_unauthorized", r["terminal"] == "DENIED" and r["deny_reason"] == "maker_unauthorized")
    case("maker-unauth: committed=false + kapı geçer (doğru reddetme)", r["committed"] is False and _gate_eval(r, G)[0] is True)

    # 9) zorunlu gerekçe — reason_code yok → DENIED reason_code_missing
    r = build(req(reason_code=None), spec)
    case("no-reason: DENIED reason_code_missing", r["deny_reason"] == "reason_code_missing")
    r = build(req(reason_code=""), spec)
    case("empty-reason: DENIED reason_code_missing", r["deny_reason"] == "reason_code_missing")

    # 10) unsupported action — katalog dışı → DENIED unsupported_action
    r = build(req(action="profile.view"), spec)
    case("unsupported-action: DENIED unsupported_action", r["deny_reason"] == "unsupported_action")

    # 11) S7 tenant izolasyonu — maker başka tenant → DENIED cross_tenant
    r = build(req(maker={"tenant_id": "t-other"}), spec)
    case("cross-tenant-maker: DENIED cross_tenant", r["terminal"] == "DENIED" and r["deny_reason"] == "cross_tenant")
    case("cross-tenant: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)
    # başka tenant onaylayan → sayılmaz → PENDING (maker doğru tenant)
    r = build(req(approvals=[{"approver_ref": "ck-x", "decision": "approve", "authorized": True,
                              "scope_ok": True, "tenant_id": "t-other", "realm": "tenant", "at": 20}]), spec)
    case("cross-tenant-approver: sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)

    # 12) S6 time-box — now > expires_at → DENIED expired
    r = build(req(now=200), spec)
    case("expired: DENIED expired", r["terminal"] == "DENIED" and r["deny_reason"] == "expired")
    # bayat onay (at > expires_at) sayılmaz → PENDING
    r = build(req(approvals=[{"approver_ref": "ck-1", "decision": "approve", "authorized": True,
                              "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 150}]), spec)
    case("stale-approval: at>expires_at sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)

    # 13) malformed → DENIED
    case("malformed-no-maker-ref: DENIED", build(req(maker={"actor_ref": None}), spec)["deny_reason"] == "malformed_request")
    case("malformed-no-now: DENIED", build(req(now=None), spec)["deny_reason"] == "malformed_request")
    case("malformed-bad-realm: DENIED", build(req(actor_realm="root"), spec)["deny_reason"] == "malformed_request")

    # 14) DEGRADE self_approval — maker kendi onayını say → sod_violation>0 + kapı eler (ÇEKİRDEK)
    r = build(req(approvals=[{"approver_ref": "mk-1", "decision": "approve", "authorized": True,
                              "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]),
              spec, inject=["self_approval"])
    case("DEGRADE self-approval: sod_violation>0 (ÇEKİRDEK)", r["violations"]["sod_violation"] > 0)
    case("DEGRADE self-approval: APPLIED (yanlış) + committed", r["terminal"] == "APPLIED" and r["committed"] is True)
    case("DEGRADE self-approval: kapı ELER", _gate_eval(r, G)[0] is False)

    # 15) DEGRADE apply_without_quorum — quorum dolmadan commit → applied_without_quorum>0 (ÇEKİRDEK)
    r = build(req(approvals=[]), spec, inject=["apply_without_quorum"])
    case("DEGRADE no-quorum-commit: applied_without_quorum>0 (ÇEKİRDEK)", r["violations"]["applied_without_quorum"] > 0)
    case("DEGRADE no-quorum-commit: APPLIED+committed (yanlış) + kapı ELER",
         r["terminal"] == "APPLIED" and r["committed"] is True and _gate_eval(r, G)[0] is False)

    # 16) DEGRADE accept_unauthorized_maker — yetkisiz maker kabul → unauthorized_maker_accepted>0
    r = build(req(maker={"authorized": False}), spec, inject=["accept_unauthorized_maker"])
    case("DEGRADE unauth-maker: unauthorized_maker_accepted>0 + kapı ELER",
         r["violations"]["unauthorized_maker_accepted"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) DEGRADE accept_unauthorized_approver — yetkisiz onayı say → unauthorized_approval>0
    r = build(req(approvals=[{"approver_ref": "ck-1", "decision": "approve", "authorized": False,
                              "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]),
              spec, inject=["accept_unauthorized_approver"])
    case("DEGRADE unauth-approver: unauthorized_approval>0 + APPLIED (yanlış) + kapı ELER",
         r["violations"]["unauthorized_approval"] > 0 and r["terminal"] == "APPLIED" and _gate_eval(r, G)[0] is False)

    # 18) DEGRADE apply_expired — süresi dolmuş talebi uygula → stale_approval_applied>0
    r = build(req(now=200, approvals=[{"approver_ref": "ck-1", "decision": "approve", "authorized": True,
                                       "scope_ok": True, "tenant_id": "t-acme", "realm": "tenant", "at": 20}]),
              spec, inject=["apply_expired"])
    case("DEGRADE apply-expired: stale_approval_applied>0 + APPLIED (yanlış) + kapı ELER",
         r["violations"]["stale_approval_applied"] > 0 and r["terminal"] == "APPLIED" and _gate_eval(r, G)[0] is False)

    # 19) DEGRADE cross_tenant — izolasyonu atla → cross_tenant>0
    r = build(req(maker={"tenant_id": "t-other"}), spec, inject=["cross_tenant"])
    case("DEGRADE cross-tenant: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) DEGRADE duplicate_approver_quorum — aynı kişiyi quorum'a iki say → quorum_tampered>0
    r = build(req(action="compliance_profile.update", approvals=[
        {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 20},
        {"approver_ref": "ck-1", "decision": "approve", "authorized": True, "scope_ok": True,
         "tenant_id": "t-acme", "realm": "tenant", "at": 25}]),
        spec, inject=["duplicate_approver_quorum"])
    case("DEGRADE dup-quorum: quorum_tampered>0 + APPLIED (yanlış) + kapı ELER",
         r["violations"]["quorum_tampered"] > 0 and r["terminal"] == "APPLIED" and _gate_eval(r, G)[0] is False)

    # 21) DEGRADE reason_bypass — gerekçesiz devam → reason_bypassed>0
    r = build(req(reason_code=None), spec, inject=["reason_bypass"])
    case("DEGRADE reason-bypass: reason_bypassed>0 + kapı ELER",
         r["violations"]["reason_bypassed"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) DEGRADE model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("DEGRADE model-tamper: model_tampered>0 + kapı ELER", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) kanıt (S9) yapısal, ham token/PII yok
    r = build(req(), spec)
    case("evidence: request+maker_ref+reason_code+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "maker_ref", "reason_code", "model_hash")))
    case("evidence: ham kullanıcı adı/e-posta/token alanı yok",
         all(k not in json.dumps(r) for k in ("email_value", "token_value", "bearer_value", "customer_name_value")))

    # 24) sızıntı tarayıcı
    case("leak: actor+aksiyon+rol temiz",
         scan_leaks('{"maker_ref":"mk-1","action":"agent.publish","role":"conversation_designer","reason_code":"rc-prod-release"}') == [])
    case("leak: e-posta yakalanır", len(scan_leaks('{"x": "jdoe@acme.co"}')) > 0)
    case("leak: jwt blob yakalanır", len(scan_leaks('{"t": "eyJhbGciOiJ.eyJzdWIiOmF.abcdef"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "maker-checker (WBS 12.1.7 — Maker-checker onay akışı; FR-IAM-005/SR-IAM-005/SAD §14.4.2)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "commit_terminals": sorted(COMMIT_TERMINALS),
        "rules": RULES,
        "deny_reasons": DENY_REASONS,
        "realms": sorted(REALMS),
        "decisions": sorted(DECISIONS),
        "decision": "malformed ⇒ DENIED(malformed_request) → action ∉ katalog ⇒ DENIED(unsupported_action) → "
                    "¬maker.authorized ⇒ DENIED(maker_unauthorized) → reason_code yok ⇒ DENIED(reason_code_missing) → "
                    "maker.tenant ≠ tenant ⇒ DENIED(cross_tenant) → now > expires_at ⇒ DENIED(expired) → "
                    "∃ yetkili in-tenant reject ⇒ REJECTED(checker_rejected) | distinct yetkili onay (≠ maker, taze) "
                    "≥ quorum ⇒ APPLIED(committed=true) | aksi ⇒ PENDING(insufficient_approvals; commit YOK)",
        "default": "DENIED (fail-closed)",
        "fail_safe": "terminal=DENIED ⇒ commit yok; PENDING/REJECTED ⇒ commit yok (onaysız canlıya çıkmaz)",
        "core_guarantees": [
            "S3 görevler ayrımı (ÇEKİRDEK): TALEP EDEN ≠ ONAYLAYAN; maker kendi talebini onaylayamaz, kendi onayı quorum'a sayılmaz; sod_violation=0 (FR-IAM-005 / SR-IAM-005)",
            "S5 onaysız canlıya çıkmaz (ÇEKİRDEK): commit YALNIZ APPLIED'da (distinct yetkili onay ≥ quorum); PENDING/REJECTED/DENIED → committed=false; applied_without_quorum=0 (SR-IAM-005)",
            "S2 maker yetkisi: yalnız submit yetkili maker talep açar; unauthorized_maker_accepted=0 (FR-IAM-005)",
            "S4 onaylayan yetkisi/kapsamı: onay sayılır ⟺ authorized ∧ scope_ok (12.1.3); unauthorized_approval=0",
            "S6 time-box: süresi dolmuş talep DENIED; bayat onay sayılmaz; stale_approval_applied=0",
            "S7 tenant izolasyonu: maker/onaylayan aynı tenant; cross_tenant=0 (FR-TEN-002)",
            "S8 quorum bütünlüğü: distinct yetkili onay ≥ quorum; aynı kişi tek sayılır; quorum_tampered=0",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "actor_realm(platform|tenant)",
                           "action(kritik-aksiyon kataloğu anahtarı; ör. agent.publish, role.assign, compliance_profile.update)",
                           "reason_code(zorunlu gerekçe kodu — opak)", "now(sanal-saat tick)", "expires_at(onay penceresi sonu tick)",
                           "resource{subject_ref(opak), scope{department/brand/campaign}}",
                           "maker{actor_ref(opak), role, authorized(submit izni — 12.1.2 soyut sonuç), tenant_id, realm}",
                           "approvals[{approver_ref(opak), decision(approve|reject), authorized(onay izni — 12.1.2 soyut), scope_ok(kapsam — 12.1.3 soyut), tenant_id, realm, at(tick)}]",
                           "inject[]", "expect", "expected{}"],
        "sod_semantics": "TALEP EDEN ≠ ONAYLAYAN (ÇEKİRDEK): approver_ref == maker.actor_ref olan onay quorum'a SAYILMAZ "
                         "(sessizce dışlanır); maker'ın kendi onayını saymak sod_violation",
        "quorum_semantics": "APPLIED ⟺ distinct (actor_ref'e göre tekil) yetkili onay sayısı ≥ quorum_required (aksiyon kataloğu); "
                            "onay sayılır ⟺ decision=approve ∧ authorized ∧ scope_ok ∧ aynı tenant/realm ∧ ≠ maker ∧ taze (at ≤ expires_at)",
        "timebox_semantics": "now > expires_at → talep EXPIRED (DENIED); bayat onay (at > expires_at) quorum'a sayılmaz; "
                             "break-glass Tier B time-box'ının (FR-IAM-009; 60dk/4sa) onay-akışı tarafı",
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "deny_reason", "pending_reason", "reject_reason", "committed", "action",
                            "actor_realm", "quorum_required", "valid_approver_count", "approver_refs",
                            "maker_ref", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/maker-checker-model.json (frozen — SoD/commit/timebox/reason/tenant/quorum + kritik-aksiyon kataloğu) + "
                 "../rbac-model/config/rbac-roles.json (12.1.1 rol→IMMUTABLE bundle + realm)",
        "consumes": "12.1.1 RBAC modeli (rol→immutable bundle + realm); 12.1.2 permission-key (aksiyon→izin — maker/approval.authorized soyut); "
                    "12.1.3 scoped assignment (approval.scope_ok soyut); SAD §14.4.2 pending→approved",
        "consumed_by": "12.2.x backend panel guard (kritik mutasyon → onay enforcement) + break-glass Tier B (FR-IAM-009; talep eden ≠ onaylayan — "
                       "AYNI çekirdek) + 12.1.8 WORM audit (onay kararı + reason_code) + 7.3.1 deterministik workflow (onay adımı) + "
                       "0.4.7 gözlemlenebilirlik (makerchecker_* metrikleri)",
        "credential_free": "İzin/kapsam doğrulaması bu modülde YOK (maker.authorized/approval.authorized/scope_ok soyut sonuç); canlı onay UI/bildirim F2'de. ADR-002.",
        "trace": "FR-IAM-005, FR-TEN-002, SR-IAM-005, TC-IAM-005, SAD §14.1/§14.4.2, ADR-011, ADR-012",
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
            print("kullanım: maker_checker_probe.py check <sample.json|dizin>")
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
