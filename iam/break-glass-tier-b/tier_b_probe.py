#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.2 — TIER B BREAK-GLASS: MAKER-CHECKER (talep eden ≠ onaylayan) + TIME-BOXED TOKEN
(60dk default, max 4sa, AUTO-EXPIRY, STANDING ACCESS YOK) referans probe.

12. workstream'in (IAM & Erişim) ÜÇ KATMANLI BREAK-GLASS'ın İÇERİK/PII KATMANI (Tier B) erişim-verme modülü
ve F2-Must yeteneği. BRD §17.7/§17 ('Tier B — transkript/kayıt/PII: Maker-checker zorunlu [talep eden ≠
onaylayan] + time-boxed [varsayılan 60 dk, max 4 saat, otomatik sonlanma, STANDING ACCESS YOK]') + SAD §14.4.2
(aynı; 'tam-audit'li bir break-glass router'ı üzerinden') + FR-IAM-009 (üç katmanlı break-glass Tier B) +
FR-IAM-006/FR-REC-009 (tüm break-glass erişimi audit). ALTIN KURAL (BRD §17): L0 (platform) tenant'ın iş
içeriğini VARSAYILAN GÖREMEZ — Tier B yalnız DAR, SÜRELİ, ONAYLI, TAM-AUDIT'li kapıyı açar. Bu modül 12.3.1'in
ESCALATE_TIER_B çıktısını TÜKETİR; bir BreakGlassTierBRequest alır → DETERMİNİSTİK, FAIL-CLOSED karar verir:

    GRANT_TIER_B — maker-checker karşılandı (talep eden ≠ onaylayan + quorum) + GEÇERLİ time-boxed token
                   (pencere içinde + target_tenant'a bağlı): içerik/PII erişimi VERİLİR (+ tam-audit).
    PENDING      — talep geçerli ama yeterli FARKLI yetkili onay (quorum) YOK → token YOK (doğru ara durum).
    DENY         — malformed / non-content (not_tier_b; break-glass gerekmez) / maker yetkisiz / ttl>max /
                   pencere dışı (expired) / binding / replay → fail-closed.

ÇEKİRDEK:
  (1) R3 SoD — TALEP EDEN ≠ ONAYLAYAN: maker kendi talebini onaylayamaz; self-approval quorum'a SAYILMAZ
      (sod_violation=0; FR-IAM-009; 12.1.7 RESİPROKAL).
  (2) R4 ONAYSIZ TOKEN YOK — GRANT_TIER_B YALNIZ FARKLI yetkili onay (quorum) toplandığında verilir
      (granted_without_approval=0, fail-closed).
  (3) R5 TIME-BOX 60/240 — token expires_at TAŞIR (unbounded_token=0); ttl default 60dk, max 240dk (4sa);
      ttl>max ile GRANT = ttl_exceeds_max.
  (4) R6 STANDING ACCESS YOK + AUTO-EXPIRY — expires_at sonrası erişim REDDEDİLİR (expired_token_access=0);
      kalıcı/standing token standing_access=0.

      BreakGlassTierBRequest ─malformed─► scope ─► maker-checker ─► timebox ─► standing/expiry ─► binding ─► audit/replay
            ├─ request_id / actor_role(L0) / target_tenant / data_class eksik|geçersiz ──► DENY (malformed)
            ├─ data_class ≠ tenant_content (break-glass gerekmez / L0 yolu yok) ─────────► DENY (not_tier_b) [R2]
            ├─ maker yetkisiz ──────────────────────────────────────────────────────────► DENY (maker_unauthorized)
            ├─ FARKLI yetkili onay (self hariç) < quorum ───────────────────────────────► PENDING [R4 doğru]
            ├─ maker kendi onayını sayar (self-approval) ───────────────────────────────► sod_violation [R3]
            ├─ quorum'suz GRANT ───────────────────────────────────────────────────────► granted_without_approval [R4]
            ├─ ttl > 240 (4sa) talebi ─────────────────────────────────────────────────► DENY (ttl_over_max) [R5 doğru]
            ├─ ttl > max ile GRANT (token verme) ──────────────────────────────────────► ttl_exceeds_max [R5]
            ├─ expires_at'siz token ───────────────────────────────────────────────────► unbounded_token [R5]
            ├─ access_at > expires_at (pencere dışı) ──────────────────────────────────► DENY (token_expired) [R6 doğru]
            ├─ pencere dışı erişim VERİLDİ ────────────────────────────────────────────► expired_token_access [R6]
            ├─ kalıcı/standing token ──────────────────────────────────────────────────► standing_access [R6]
            ├─ access.tenant ≠ target (cross-tenant) ile GRANT ────────────────────────► token_binding_violation [R7]
            ├─ çözülmüş grant (expired/revoked/consumed) yeniden GRANT ─────────────────► replay_reuse [R9]
            ├─ GRANT audit'siz ───────────────────────────────────────────────────────► unaudited_grant [R8]
            └─ audit ham PII/token taşır | emitilen audit tahrif (row_hash) ────────────► audit_pii / audit_mutable [R8]

Maker-checker ÇEKİRDEĞİ 12.1.7 (separation_of_duties + timebox_policy + critical_actions.breakglass.tier_b)
TÜKETİLİR; bu modül onu Tier B token yaşam döngüsüne uygular. Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random
YOK; model_hash sha256; tick=dakika sanal-saat). Her karar terminal (R1) + kanıt + model bütünlük manifesti
(R10); metrik düşük-kardinalite + ham PII/token yok (R11); model/spec/sample ham içerik/PII/token tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): gerekçe kodu SEMANTİĞİ + tenant security_compliance_officer/
tenant_owner BİLDİRİMİ → 12.3.3; regüle tenant require_tenant_approval toggle + DPA → 12.3.4; Tier sınıflandırma
+ ESCALATE → 12.3.1 (CONSUMED); rol→permission-key/scope → 12.1.2/12.1.3; WORM audit hash-zinciri → 12.1.8
(CONSUMED). KAYNAK DOĞRULUK; çelişkide BRD §17.7 / SAD §14.4.2 / FR-IAM-009 esastır.

Kullanım:
  tier_b_probe.py validate          Statik model + spec + 12.3.1/12.1.7/12.1.8/12.1.1 resiprokal → çıkış kodu
  tier_b_probe.py check <sample>    Tier B karar motoru: senaryo(lar) → kapı (R1–R12)
  tier_b_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  tier_b_probe.py schema            Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK (tick=dakika sanal-saat).
Stdlib-only. Sır/credential (break-glass token DEĞERİ) ve ham içerik (PII değeri) üretilmez/yazılmaz (fixture
sentetik — yalnız rol enum + action + sınıf enum + kaynak adı + tier/decision enum + reason_code enum + ttl/tick
tamsayı + slug kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tier-b-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "tier-b-model.json")
TIER_A_MODEL_PATH = os.path.join(HERE, "..", "break-glass-tier-a", "config", "tier-a-model.json")
MAKER_CHECKER_MODEL_PATH = os.path.join(HERE, "..", "maker-checker", "config", "maker-checker-model.json")
WORM_MODEL_PATH = os.path.join(HERE, "..", "worm-audit", "config", "worm-audit-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"GRANT_TIER_B", "PENDING", "DENY"}
TIER_B_CONTENT = "tenant_content"                                    # yalnız bu sınıf Tier B'ye girer
PLATFORM_ROLES = {"platform_owner", "platform_sre", "platform_billing"}
RESOLVED_STATES = {"EXPIRED", "REVOKED", "CONSUMED"}                 # replay: çözülmüş grant
DEFAULT_TTL = 60                                                     # dakika (BRD §17.7)
MAX_TTL = 240                                                       # dakika = 4 saat (BRD §17.7)
RULES = ["tier_b_scope", "separation_of_duties", "no_grant_without_approval", "timebox_60_240",
         "no_standing_auto_expiry", "token_binding", "audit_emitted", "replay_safe", "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU Tier B davranışını bozan müdahaleler.
INJECTIONS = {"self_approval", "grant_without_quorum", "unbounded_token", "ttl_exceeds_max", "standing_access",
              "use_after_expiry", "cross_tenant_token", "replay_grant", "skip_audit", "leak_pii_in_audit",
              "mutate_audit", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "sod_violation", "granted_without_approval", "unbounded_token", "ttl_exceeds_max", "standing_access",
    "expired_token_access", "token_binding_violation", "unaudited_grant", "audit_pii", "audit_mutable",
    "replay_reuse", "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.3.1 deseniyle) — ham içerik/PII/token yasak; rol/action/sınıf/kaynak/tier/reason beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|break_glass_token_value|token_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|mk-|ck-|rc-|corr-|bg-|tok-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|_repo|tenant_|platform_|global_reference|break_glass|audit_log|usage_record)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/token tarayıcı. Yorum/tarif satırı + rol/action/sınıf/kaynak/tier adı + slug kimlik eler (12.3.1 deseni)."""
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


def _classify(sample, model):
    """Veri-sınıfını çöz: sample.data_class verilirse onu; yoksa table_class_of[resource_type]; yoksa None (fail-closed)."""
    dc = sample.get("data_class")
    if dc is None:
        dc = model.get("table_class_of", {}).get(sample.get("resource_type"))
    return dc


def _distinct_approvers(approvals, maker_ref, count_self):
    """FARKLI (distinct, dedupe), yetkili, in-realm 'approve' onaylayanlar — maker hariç (count_self=True ise maker dahil = SoD ihlali)."""
    refs = []
    self_counted = False
    for a in approvals or []:
        if a.get("decision") != "approve" or not a.get("authorized") or a.get("realm") != "platform":
            continue
        ref = a.get("approver_ref")
        if ref == maker_ref:
            if count_self:
                self_counted = True
                refs.append(ref)            # SoD ihlali: maker kendi onayını sayar
            # aksi: sessizce dışlanır (require_distinct_maker_checker)
            continue
        refs.append(ref)
    return list(dict.fromkeys(refs)), self_counted   # dedupe (sıra korunur)


def build(sample, spec, inject=None, model=None):
    """Tek BreakGlassTierBRequest senaryosunu yürüt → karar + ihlal sayaçları.

    Motor DOĞRU Tier B davranışını hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal sayacını
    artırır (12.1.x/12.2.x/12.3.1 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model()

    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id", request_id)
    break_glass_id = sample.get("break_glass_id", "bg-%s" % (request_id or "x"))
    actor_role = sample.get("actor_role")
    action = sample.get("action", "read")
    target_tenant_id = sample.get("target_tenant_id")
    resource_type = sample.get("resource_type")
    reason_code = sample.get("reason_code")                          # 12.3.3 semantiği; burada yalnız taşınır
    now = sample.get("now", 0)                                       # tick = dakika (Date.now YOK)
    ttl_req = sample.get("ttl_minutes")                              # None → default 60
    quorum = int(sample.get("quorum", model.get("quorum_policy", {}).get("default_quorum", 1)))
    maker = sample.get("maker", {}) or {}
    maker_ref = maker.get("actor_ref")
    approvals = sample.get("approvals", [])
    access = sample.get("access")                                    # {tenant_id, at} — token kullanım anı (opsiyonel)
    prior_state = sample.get("prior_state")                         # replay: çözülmüş grant durumu (opsiyonel)

    data_class = _classify(sample, model)

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    ttl = None
    granted_at = None
    expires_at = None
    audit_emitted = True                                            # ÇEKİRDEK: doğru motor her kararı audit'ler

    # ── R10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "tier": model.get("tier"),
        "data_class": model.get("data_class"),
        "separation_of_duties": model.get("separation_of_duties"),
        "quorum_policy": model.get("quorum_policy"),
        "timebox_policy": model.get("timebox_policy"),
        "token_binding": model.get("token_binding"),
        "concurrency_policy": model.get("concurrency_policy"),
        "actor_roles": model.get("actor_roles"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["timebox_policy"] = dict(tampered["timebox_policy"])
        tampered["timebox_policy"]["max_ttl_minutes"] = 100000               # 4sa tavanını kaldır (tahrifat)
        tampered["separation_of_duties"] = dict(tampered["separation_of_duties"])
        tampered["separation_of_duties"]["require_distinct_maker_checker"] = False  # SoD kapat (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or actor_role not in PLATFORM_ROLES
                 or not target_tenant_id or data_class is None)

    if malformed:
        terminal, note = "DENY", "malformed"
    elif data_class != TIER_B_CONTENT:
        # ── R2 Tier B scope: yalnız tenant_content; non-content → break-glass gerekmez / L0 yolu yok ──
        terminal, note = "DENY", "not_tier_b"
    else:
        maker_authorized = bool(maker.get("authorized")) and maker.get("realm") == "platform"
        count_self = "self_approval" in inject
        approver_refs, self_counted = _distinct_approvers(approvals, maker_ref, count_self)
        quorum_met = len(approver_refs) >= quorum

        if not maker_authorized:
            terminal, note = "DENY", "maker_unauthorized"
        elif not quorum_met:
            terminal, note = "PENDING", "awaiting_checker"           # doğru ara durum — token YOK
        else:
            # ── onay karşılandı → time-boxed token ver ──
            ttl = DEFAULT_TTL if ttl_req is None else int(ttl_req)   # R5: ttl belirtilmezse default 60
            granted_at = now
            if ttl > MAX_TTL and "ttl_exceeds_max" not in inject:
                # ── doğru: ttl>240 talebi REDDEDİLİR (fail-closed) ──
                terminal, note = "DENY", "ttl_over_max"
            else:
                expires_at = granted_at + ttl                       # R5: require_expiry (token bounded)
                terminal, note = "GRANT_TIER_B", "granted"

                # ── doğru auto-expiry + binding (access varsa) ──
                if access is not None:
                    acc_at = access.get("at", granted_at)
                    acc_tenant = access.get("tenant_id", target_tenant_id)
                    if acc_at > expires_at and "use_after_expiry" not in inject:
                        terminal, note = "DENY", "token_expired"     # R6: pencere dışı reddedilir
                    elif acc_tenant != target_tenant_id and "cross_tenant_token" not in inject:
                        terminal, note = "DENY", "token_binding"     # R7: cross-tenant reddedilir
                # ── doğru replay-safety ──
                if prior_state in RESOLVED_STATES and "replay_grant" not in inject:
                    terminal, note = "DENY", "replay_blocked"        # R9: çözülmüş grant diriltilmez

        # ── degrade müdahaleleri (DOĞRU davranışı boz) — maker-checker'dan SONRA, terminal'den bağımsız ──
        if not malformed and data_class == TIER_B_CONTENT:
            if "self_approval" in inject and self_counted:
                v["sod_violation"] += 1                              # R3: maker kendi onayını saydı
            if "grant_without_quorum" in inject:                     # R4: quorum'suz GRANT (PENDING'i ezer)
                ttl = DEFAULT_TTL if ttl is None else ttl
                granted_at = now
                terminal, note = "GRANT_TIER_B", "granted"
                expires_at = expires_at if expires_at is not None else (now + ttl)
                v["granted_without_approval"] += 1
            if "ttl_exceeds_max" in inject and ttl is not None and ttl > MAX_TTL:
                granted_at = now
                terminal, note = "GRANT_TIER_B", "granted"           # R5: ttl>max ile token verildi
                expires_at = granted_at + ttl
                v["ttl_exceeds_max"] += 1
            if "unbounded_token" in inject and terminal == "GRANT_TIER_B":
                expires_at = None                                    # R5: expires_at'siz token
                v["unbounded_token"] += 1
            if "standing_access" in inject and terminal == "GRANT_TIER_B":
                v["standing_access"] += 1                            # R6: kalıcı/standing token
                expires_at = None
            if "use_after_expiry" in inject and access is not None and expires_at is not None \
                    and access.get("at", granted_at) > expires_at and terminal == "GRANT_TIER_B":
                v["expired_token_access"] += 1                       # R6: pencere dışı erişim verildi
            if "cross_tenant_token" in inject and access is not None \
                    and access.get("tenant_id", target_tenant_id) != target_tenant_id \
                    and terminal == "GRANT_TIER_B":
                v["token_binding_violation"] += 1                    # R7: cross-tenant token
            if "replay_grant" in inject and prior_state in RESOLVED_STATES:
                granted_at = now
                terminal, note = "GRANT_TIER_B", "granted"           # R9: çözülmüş grant yeniden
                expires_at = expires_at if expires_at is not None else (now + (ttl or DEFAULT_TTL))
                v["replay_reuse"] += 1

        # ── R8 audit: degrade — GRANT audit ATLA (sessiz break-glass) ──
        if "skip_audit" in inject and terminal == "GRANT_TIER_B":
            audit_emitted = False
        if terminal == "GRANT_TIER_B" and not audit_emitted:
            v["unaudited_grant"] += 1

    # ── audit kaydı üret (ÇEKİRDEK: her karar audit'lenir — malformed/deny/pending dahil break-glass girişimi) ──
    audit_record = _build_audit(
        record_id="aud-%s" % (request_id or "x"), break_glass_id=break_glass_id, correlation_id=correlation_id,
        actor_role=actor_role, actor_realm=model.get("actor_realm", "platform"),
        target_tenant_ref=target_tenant_id, action=action, data_class=data_class, resource_type=resource_type,
        tier="B", decision=terminal, reason_code=reason_code, ttl_minutes=ttl, granted_at=granted_at,
        expires_at=expires_at, occurred_tick=now)
    # ── degrade: audit kaydına ham PII/token sok ──
    if "leak_pii_in_audit" in inject and audit_emitted:
        audit_record["pii_field_present"] = True                    # sentetik işaret (gerçek PII/token yazılmaz)
        v["audit_pii"] += 1
    # ── R8 audit immutability — emitilen kayıt değiştirilirse row_hash uyumsuz (WORM; 12.1.8 RESİPROKAL) ──
    if "mutate_audit" in inject and audit_emitted:
        audit_record["decision"] = "tampered"                       # hash sonrası alan değişimi
    if audit_emitted:
        recomputed = _canon_hash({k: val for k, val in audit_record.items() if k != "row_hash"})
        if recomputed != audit_record.get("row_hash"):
            v["audit_mutable"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, correlation_id, break_glass_id, actor_role, action, target_tenant_id,
                         data_class, resource_type, reason_code, terminal, note, ttl, granted_at, expires_at,
                         audit_emitted, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, note, v, actor_role, action, target_tenant_id, data_class, resource_type,
                 reason_code, ttl, granted_at, expires_at, audit_emitted, audit_record, model_hash, evidence)


def _build_audit(record_id, break_glass_id, correlation_id, actor_role, actor_realm, target_tenant_ref, action,
                 data_class, resource_type, tier, decision, reason_code, ttl_minutes, granted_at, expires_at,
                 occurred_tick):
    """PII/token-free, WORM uyumlu audit kaydı (12.1.8 RESİPROKAL): row_hash = sha256(kanonik içerik)."""
    rec = {
        "record_id": record_id,
        "break_glass_id": break_glass_id,
        "correlation_id": correlation_id,
        "actor_role": actor_role,
        "actor_realm": actor_realm,
        "target_tenant_ref": target_tenant_ref,
        "action": action,
        "data_class": data_class,
        "resource_type": resource_type,
        "tier": tier,
        "decision": decision,
        "reason_code": reason_code,
        "ttl_minutes": ttl_minutes,
        "granted_at": granted_at,
        "expires_at": expires_at,
        "occurred_tick": occurred_tick,
    }
    rec["row_hash"] = _canon_hash(rec)
    return rec


def _evidence(request_id, correlation_id, break_glass_id, actor_role, action, target_tenant_id, data_class,
              resource_type, reason_code, terminal, note, ttl, granted_at, expires_at, audit_emitted, model_hash):
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "break_glass_id": break_glass_id,
        "actor_role": actor_role,
        "action": action,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "reason_code": reason_code,
        "terminal": terminal,
        "note": note,
        "ttl_minutes": ttl,
        "granted_at": granted_at,
        "expires_at": expires_at,
        "audit_emitted": audit_emitted,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, note, v, actor_role, action, target_tenant_id, data_class, resource_type,
          reason_code, ttl, granted_at, expires_at, audit_emitted, audit_record, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "note": note,
        "actor_role": actor_role,
        "action": action,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "reason_code": reason_code,
        "ttl_minutes": ttl,
        "granted_at": granted_at,
        "expires_at": expires_at,
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
        "sod_violation": "max_sod_violation",
        "granted_without_approval": "max_granted_without_approval",
        "unbounded_token": "max_unbounded_token",
        "ttl_exceeds_max": "max_ttl_exceeds_max",
        "standing_access": "max_standing_access",
        "expired_token_access": "max_expired_token_access",
        "token_binding_violation": "max_token_binding_violation",
        "unaudited_grant": "max_unaudited_grant",
        "audit_pii": "max_audit_pii",
        "audit_mutable": "max_audit_mutable",
        "replay_reuse": "max_replay_reuse",
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
        for key in ("terminal", "note", "audit_emitted", "ttl_minutes", "expires_at"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s note=%s class=%s role=%s ttl=%s expires=%s audit=%s"
              % (res["terminal"], res["note"], res["data_class"], res["actor_role"],
                 res["ttl_minutes"], res["expires_at"], res["audit_emitted"]))
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
    chk("wbs=12.3.2", spec.get("wbs") == "12.3.2")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-009 izlenir (üç katmanlı break-glass — ÇEKİRDEK)", "FR-IAM-009" in tr.get("fr", []))
    chk("FR-IAM-005 izlenir (maker-checker)", "FR-IAM-005" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (tüm işlemler audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-REC-009 izlenir (erişim audit)", "FR-REC-009" in tr.get("fr", []))
    chk("BRD §17.7 izlenir (Tier B — maker-checker + time-boxed)", any("§17.7" in s for s in tr.get("brd", [])))
    chk("SAD §14.4.2 Tier B izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-013 izlenir (üç katmanlı break-glass)", any(a.startswith("ADR-013") for a in tr.get("adr", [])))
    chk("12.3.1 tier-a TÜKETİLİR (ESCALATE_TIER_B RESİPROKAL)",
        any("12.3.1" in s for s in tr.get("consumes", [])))
    chk("12.1.7 maker-checker TÜKETİLİR (SoD + timebox RESİPROKAL)",
        any("12.1.7" in s for s in tr.get("consumes", [])))
    chk("12.1.8 worm-audit TÜKETİLİR (WORM audit RESİPROKAL)",
        any("12.1.8" in s for s in tr.get("consumes", [])))
    chk("12.3.3/12.3.4 DELEGE (consumed_by/delegates)",
        any("12.3.3" in s for s in tr.get("consumed_by", [])) or any("12.3.3" in s for s in tr.get("delegates", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→scope→maker-checker→timebox→standing/expiry→binding→audit/replay",
        rz.get("evaluation") == "malformed_then_scope_then_maker_checker_then_timebox_then_standing_expiry_then_binding_then_audit_replay")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=DENY (fail-closed)", dec.get("default") == "DENY")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower()
        or "erişim yok" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar GRANT_TIER_B/PENDING/DENY", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — maker-checker + time-box + auto-expiry + audit
    en = spec["enforcement"]
    chk("maker_checker talep eden ≠ onaylayan",
        "≠" in en.get("maker_checker", "") or "farkl" in en.get("maker_checker", "").lower())
    chk("time_boxed_token default 60 / max 240 (4sa)",
        "60" in en.get("time_boxed_token", "") and ("240" in en.get("time_boxed_token", "") or "4 saat" in en.get("time_boxed_token", "")))
    chk("auto_expiry + standing access yok",
        "expir" in en.get("auto_expiry_no_standing", "").lower() and "standing" in en.get("auto_expiry_no_standing", "").lower())
    chk("audit_layer WORM (12.1.8 RESİPROKAL)", "12.1.8" in en.get("audit_layer", "") and "WORM" in en.get("audit_layer", "").upper())

    # 7) Model alanları
    md = spec["model"]
    chk("model tier=B", md.get("tier") == "B")
    chk("model data_class=tenant_content", md.get("data_class") == TIER_B_CONTENT)
    chk("model default_ttl=60", md.get("default_ttl_minutes") == 60)
    chk("model max_ttl=240 (4sa)", md.get("max_ttl_minutes") == 240)
    chk("model actor_roles = L0 platform rolleri", set(md.get("actor_roles", [])) == PLATFORM_ROLES)

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_sod_violation", "max_granted_without_approval", "max_unbounded_token", "max_ttl_exceeds_max",
               "max_standing_access", "max_expired_token_access", "max_token_binding_violation",
               "max_unaudited_grant", "max_audit_pii", "max_audit_mutable", "max_replay_reuse",
               "max_model_tampered", "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("l0_break_glass_tier_b_total metrik", "l0_break_glass_tier_b_total" in obs.get("metrics", []))
    chk("break_glass_tier_b_violation_total metrik (alarm)", "break_glass_tier_b_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("break_glass_id/target_tenant_id YÜKSEK kard (label değil)",
        "break_glass_id" in hi and "break_glass_id" not in lo and "target_tenant_id" in hi)
    chk("actor_role/decision/result DÜŞÜK kard",
        all(x in lo for x in ("actor_role", "decision", "result")))
    chk("alarm sod_violation/granted_without_approval/expired_token_access ≤2dk",
        any(x in obs.get("alarm", "") for x in ("sod_violation", "granted_without_approval", "expired_token_access", "standing_access")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (BRD §17.7 / SAD §14.4.2)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/tier-b-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model tier=B + data_class=tenant_content",
            mm.get("tier") == "B" and mm.get("data_class") == TIER_B_CONTENT)
        chk("model SoD require_distinct_maker_checker=true + self_approval saymaz",
            mm.get("separation_of_duties", {}).get("require_distinct_maker_checker") is True
            and mm.get("separation_of_duties", {}).get("self_approval_counts_to_quorum") is False)
        chk("model timebox default=60 / max=240 / require_expiry / auto_expiry / no_standing",
            mm.get("timebox_policy", {}).get("default_ttl_minutes") == 60
            and mm.get("timebox_policy", {}).get("max_ttl_minutes") == 240
            and mm.get("timebox_policy", {}).get("require_expiry") is True
            and mm.get("timebox_policy", {}).get("auto_expiry") is True
            and mm.get("timebox_policy", {}).get("no_standing_access") is True)
        chk("model timebox reject_ttl_over_max=true (ttl>4sa reddedilir)",
            mm.get("timebox_policy", {}).get("reject_ttl_over_max") is True)
        chk("model quorum no_grant_without_quorum=true",
            mm.get("quorum_policy", {}).get("no_grant_without_quorum") is True)
        chk("model audit required_for_every_decision=true + worm=true + no_raw_token=true",
            mm.get("audit", {}).get("required_for_every_decision") is True
            and mm.get("audit", {}).get("worm") is True
            and mm.get("audit", {}).get("no_raw_token") is True)
        chk("model audit break_glass_id record alanı (DB.md §6.3)",
            "break_glass_id" in mm.get("audit", {}).get("record_fields", []))
        chk("model concurrency resolved_states = EXPIRED/REVOKED/CONSUMED (replay-safe)",
            set(mm.get("concurrency_policy", {}).get("resolved_states", [])) == RESOLVED_STATES)
        tco = mm.get("table_class_of", {})
        chk("model table_class_of ≥37 varlık (BRD §16)", len(tco) >= 37)
        chk("model transcript/recording/contact=tenant_content (Tier B); usage_record=tenant_metric (non-bg)",
            tco.get("transcript") == "tenant_content" and tco.get("recording") == "tenant_content"
            and tco.get("contact") == "tenant_content" and tco.get("usage_record") == "tenant_metric")

    # 12) 12.3.1 RESİPROKAL — Tier A ESCALATE_TIER_B + tenant_content
    ta_ok = os.path.exists(TIER_A_MODEL_PATH)
    chk("12.3.1 ../break-glass-tier-a/config/tier-a-model.json var (ESCALATE_TIER_B — TÜKETİLİR)", ta_ok)
    if ta_ok and mm_ok:
        ta = _load(TIER_A_MODEL_PATH)
        chk("12.3.1 tier B requires_break_glass=true + DELEGE 12.3.2 (RESİPROKAL)",
            ta.get("tiers", {}).get("B", {}).get("requires_break_glass") is True
            and "12.3.2" in ta.get("tiers", {}).get("B", {}).get("delegated_flow", ""))
        chk("12.3.1 tier_b_content = tenant_content = bu modül data_class (RESİPROKAL)",
            set(ta.get("tier_b_content", [])) == {TIER_B_CONTENT} == {_model().get("data_class")})

    # 13) 12.1.7 RESİPROKAL — maker-checker SoD + timebox + breakglass.tier_b
    mc_ok = os.path.exists(MAKER_CHECKER_MODEL_PATH)
    chk("12.1.7 ../maker-checker/config/maker-checker-model.json var (SoD+timebox — TÜKETİLİR)", mc_ok)
    if mc_ok:
        mc = _load(MAKER_CHECKER_MODEL_PATH)
        chk("12.1.7 SoD require_distinct_maker_checker=true (RESİPROKAL talep eden ≠ onaylayan)",
            mc.get("separation_of_duties", {}).get("require_distinct_maker_checker") is True
            and mc.get("separation_of_duties", {}).get("self_approval_counts_to_quorum") is False)
        chk("12.1.7 critical_actions.breakglass.tier_b requires_approval=true (RESİPROKAL)",
            mc.get("critical_actions", {}).get("breakglass.tier_b", {}).get("requires_approval") is True)
        chk("12.1.7 timebox_policy expired_request_denied=true (RESİPROKAL time-box)",
            mc.get("timebox_policy", {}).get("expired_request_denied") is True)

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

    # 15) 12.1.1 RESİPROKAL — L0 platform rolleri
    rb_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (RBAC rolleri — TÜKETİLİR)", rb_ok)
    if rb_ok:
        with open(RBAC_MODEL_PATH, "r", encoding="utf-8") as fh:
            rbac_txt = fh.read()
        chk("12.1.1 L0 platform rolleri (owner/sre/billing) mevcut (RESİPROKAL)",
            all(role in rbac_txt for role in PLATFORM_ROLES))

    # 16) Sır/PII/token tarayıcı — spec + model + samples
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
    chk("hiç ham-içerik/PII/token sızıntısı yok (R12)", total_leaks == 0)

    # 17) Samples — ≥1 pass + ≥1 fail
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
        # Varsayılan: platform_owner, transcript (tenant_content → Tier B), yetkili maker (mk-1) + farklı
        # yetkili checker (ck-1) → GRANT_TIER_B + 60dk token + audit.
        d = {
            "request_id": "req-1", "correlation_id": "corr-1", "actor_role": "platform_owner", "action": "read",
            "target_tenant_id": "t-acme", "resource_type": "transcript", "reason_code": "rc-incident-debug",
            "now": 100,
            "maker": {"actor_ref": "mk-1", "role": "platform_sre", "authorized": True, "realm": "platform"},
            "approvals": [{"approver_ref": "ck-1", "decision": "approve", "authorized": True, "realm": "platform", "at": 101}],
        }
        d.update(kw)
        return d

    # 1) happy — Tier B maker-checker karşılandı → GRANT_TIER_B + 60dk token + audit, ihlal yok
    r = build(req(), spec)
    case("happy: GRANT_TIER_B (transcript, maker≠checker, quorum)", r["terminal"] == "GRANT_TIER_B")
    case("happy: ttl default 60dk", r["ttl_minutes"] == 60)
    case("happy: expires_at = now+60 (bounded)", r["expires_at"] == 160)
    case("happy: audit_emitted=True + row_hash var (WORM)",
         r["audit_emitted"] is True and r["audit_record"].get("row_hash") is not None)
    case("happy: break_glass_id audit'te (DB.md §6.3)", r["audit_record"].get("break_glass_id") is not None)
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) R2 — Tier B scope: non-content → DENY (not_tier_b)
    case("scope: usage_record (tenant_metric) → DENY (break-glass gerekmez)",
         build(req(resource_type="usage_record"), spec)["note"] == "not_tier_b")
    case("scope: agent (tenant_config) → DENY (L0 yolu yok)",
         build(req(resource_type="agent"), spec)["note"] == "not_tier_b")
    case("scope: audit_log (platform) → DENY (not_tier_b)",
         build(req(resource_type="audit_log"), spec)["terminal"] == "DENY")

    # 4) R3 ÇEKİRDEK SoD — maker'ın kendi onayı sayılmaz → PENDING; self_approval inject → sod_violation
    rself = build(req(approvals=[{"approver_ref": "mk-1", "decision": "approve", "authorized": True, "realm": "platform", "at": 101}]), spec)
    case("SoD: maker kendi onayı (mk-1) sayılmaz → PENDING (token YOK)", rself["terminal"] == "PENDING")
    case("SoD: doğru → sod_violation=0 + kapı geçer",
         rself["violations"]["sod_violation"] == 0 and _gate_eval(rself, G)[0] is True)
    rsv = build(req(approvals=[{"approver_ref": "mk-1", "decision": "approve", "authorized": True, "realm": "platform", "at": 101}]),
                spec, inject=["self_approval"])
    case("SoD degrade: self_approval → sod_violation>0 + kapı eler",
         rsv["violations"]["sod_violation"] > 0 and _gate_eval(rsv, G)[0] is False)

    # 5) R4 — quorum yok → PENDING; grant_without_quorum inject → granted_without_approval
    rpend = build(req(approvals=[]), spec)
    case("quorum: onay yok → PENDING (token YOK)", rpend["terminal"] == "PENDING")
    case("quorum: doğru → granted_without_approval=0 + kapı geçer",
         rpend["violations"]["granted_without_approval"] == 0 and _gate_eval(rpend, G)[0] is True)
    rgwq = build(req(approvals=[]), spec, inject=["grant_without_quorum"])
    case("quorum degrade: grant_without_quorum → GRANT + granted_without_approval>0 + kapı eler",
         rgwq["terminal"] == "GRANT_TIER_B" and rgwq["violations"]["granted_without_approval"] > 0
         and _gate_eval(rgwq, G)[0] is False)
    # quorum=2 ama tek onay → PENDING
    case("quorum2 tek onay → PENDING",
         build(req(quorum=2), spec)["terminal"] == "PENDING")

    # 6) R5 ÇEKİRDEK time-box — ttl belirtilebilir; ttl>240 reddedilir; degrade ttl_exceeds_max/unbounded
    case("time-box: ttl=120 verilir → expires_at=now+120",
         build(req(ttl_minutes=120), spec)["expires_at"] == 220)
    rmax = build(req(ttl_minutes=300), spec)
    case("time-box: ttl=300 (>240/4sa) → DENY (ttl_over_max; reddedilir)",
         rmax["terminal"] == "DENY" and rmax["note"] == "ttl_over_max")
    case("time-box: ttl>max reddedilir → ttl_exceeds_max=0 + kapı geçer",
         rmax["violations"]["ttl_exceeds_max"] == 0 and _gate_eval(rmax, G)[0] is True)
    rtte = build(req(ttl_minutes=300), spec, inject=["ttl_exceeds_max"])
    case("time-box degrade: ttl_exceeds_max → GRANT ttl=300 + ttl_exceeds_max>0 + kapı eler",
         rtte["terminal"] == "GRANT_TIER_B" and rtte["violations"]["ttl_exceeds_max"] > 0
         and _gate_eval(rtte, G)[0] is False)
    runb = build(req(), spec, inject=["unbounded_token"])
    case("time-box degrade: unbounded_token → expires_at=None + unbounded_token>0 + kapı eler",
         runb["expires_at"] is None and runb["violations"]["unbounded_token"] > 0
         and _gate_eval(runb, G)[0] is False)

    # 7) R6 ÇEKİRDEK standing/auto-expiry — pencere dışı erişim reddedilir; degrade use_after_expiry/standing
    rexp = build(req(access={"tenant_id": "t-acme", "at": 500}), spec)   # 500 > expires(160)
    case("auto-expiry: access_at=500 > expires=160 → DENY (token_expired)",
         rexp["terminal"] == "DENY" and rexp["note"] == "token_expired")
    case("auto-expiry: doğru → expired_token_access=0 + kapı geçer",
         rexp["violations"]["expired_token_access"] == 0 and _gate_eval(rexp, G)[0] is True)
    ruae = build(req(access={"tenant_id": "t-acme", "at": 500}), spec, inject=["use_after_expiry"])
    case("auto-expiry degrade: use_after_expiry → GRANT + expired_token_access>0 + kapı eler",
         ruae["terminal"] == "GRANT_TIER_B" and ruae["violations"]["expired_token_access"] > 0
         and _gate_eval(ruae, G)[0] is False)
    rstand = build(req(), spec, inject=["standing_access"])
    case("standing degrade: standing_access → standing_access>0 + expires_at=None + kapı eler",
         rstand["violations"]["standing_access"] > 0 and rstand["expires_at"] is None
         and _gate_eval(rstand, G)[0] is False)
    # pencere içi erişim → GRANT
    case("auto-expiry: access_at=150 ≤ expires=160 → GRANT_TIER_B",
         build(req(access={"tenant_id": "t-acme", "at": 150}), spec)["terminal"] == "GRANT_TIER_B")

    # 8) R7 — token-binding: cross-tenant erişim reddedilir; degrade cross_tenant_token
    rxt = build(req(access={"tenant_id": "t-other", "at": 150}), spec)
    case("binding: access.tenant=t-other ≠ target=t-acme → DENY (token_binding)",
         rxt["terminal"] == "DENY" and rxt["note"] == "token_binding")
    rxti = build(req(access={"tenant_id": "t-other", "at": 150}), spec, inject=["cross_tenant_token"])
    case("binding degrade: cross_tenant_token → GRANT + token_binding_violation>0 + kapı eler",
         rxti["terminal"] == "GRANT_TIER_B" and rxti["violations"]["token_binding_violation"] > 0
         and _gate_eval(rxti, G)[0] is False)

    # 9) R8 — audit emitted/PII-free/immutable
    rsk = build(req(), spec, inject=["skip_audit"])
    case("audit: skip_audit → unaudited_grant>0 + audit_emitted=False + kapı eler",
         rsk["violations"]["unaudited_grant"] > 0 and rsk["audit_emitted"] is False
         and _gate_eval(rsk, G)[0] is False)
    case("audit: PENDING/DENY de audit'lenir (her break-glass girişimi)",
         build(req(approvals=[]), spec)["audit_emitted"] is True
         and build(req(resource_type="agent"), spec)["audit_emitted"] is True)
    rpii = build(req(), spec, inject=["leak_pii_in_audit"])
    case("audit: leak_pii_in_audit → audit_pii>0 + kapı eler",
         rpii["violations"]["audit_pii"] > 0 and _gate_eval(rpii, G)[0] is False)
    rmut = build(req(), spec, inject=["mutate_audit"])
    case("audit: mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
         rmut["violations"]["audit_mutable"] > 0 and _gate_eval(rmut, G)[0] is False)
    case("audit: ham PII/token alanı yok",
         all(k not in json.dumps(r) for k in ("transcript_text_value", "recording_audio_value", "break_glass_token_value")))

    # 10) R9 — replay-safe: çözülmüş grant diriltilemez; degrade replay_grant
    rrep = build(req(prior_state="EXPIRED"), spec)
    case("replay: prior_state=EXPIRED → DENY (replay_blocked)",
         rrep["terminal"] == "DENY" and rrep["note"] == "replay_blocked")
    rrepi = build(req(prior_state="EXPIRED"), spec, inject=["replay_grant"])
    case("replay degrade: replay_grant → GRANT + replay_reuse>0 + kapı eler",
         rrepi["terminal"] == "GRANT_TIER_B" and rrepi["violations"]["replay_reuse"] > 0
         and _gate_eval(rrepi, G)[0] is False)

    # 11) R10 — model integrity
    rtam = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler",
         rtam["violations"]["model_tampered"] > 0 and _gate_eval(rtam, G)[0] is False)
    case("model_hash deterministik", build(req(), spec)["model_hash"] == r["model_hash"])

    # 12) malformed → DENY
    case("malformed-noreq: DENY", build(req(request_id=None), spec)["note"] == "malformed")
    case("malformed-norole: DENY", build(req(actor_role="bogus"), spec)["note"] == "malformed")
    case("malformed-tenantrole: DENY (L0 rolü değil)",
         build(req(actor_role="tenant_owner"), spec)["note"] == "malformed")
    case("malformed-notenant: DENY (target_tenant yok)",
         build(req(target_tenant_id=None), spec)["note"] == "malformed")
    # maker yetkisiz → DENY
    case("maker yetkisiz → DENY (maker_unauthorized)",
         build(req(maker={"actor_ref": "mk-1", "authorized": False, "realm": "platform"}), spec)["note"] == "maker_unauthorized")

    # 13) evidence + leak
    case("evidence: request+actor+target_tenant+reason+tier+ttl+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "actor_role", "target_tenant_id", "reason_code", "ttl_minutes", "expires_at", "model_hash")))
    case("leak: rol+action+sınıf+tier+reason temiz",
         scan_leaks('{"actor_role":"platform_owner","action":"read","data_class":"tenant_content","tier":"B","reason_code":"rc-incident-debug"}') == [])
    case("leak: break_glass_token_value alanı yakalanır", len(scan_leaks('{"break_glass_token_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "break-glass-tier-b (WBS 12.3.2 — Tier B break-glass: maker-checker [talep eden ≠ onaylayan] + "
                  "time-boxed token [60dk default, max 4sa, auto-expiry, standing access yok]; BRD §17.7, SAD §14.4.2, FR-IAM-009)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "data_class": TIER_B_CONTENT,
        "actor_roles": sorted(PLATFORM_ROLES),
        "default_ttl_minutes": DEFAULT_TTL,
        "max_ttl_minutes": MAX_TTL,
        "decision": "malformed ⇒ DENY(malformed) → data_class ≠ tenant_content ⇒ DENY(not_tier_b) → maker yetkisiz ⇒ "
                    "DENY(maker_unauthorized) → FARKLI yetkili onay (self hariç) < quorum ⇒ PENDING → ttl(default 60) > "
                    "240 ⇒ DENY(ttl_over_max) → expires_at=now+ttl → access_at>expires_at ⇒ DENY(token_expired) → "
                    "access.tenant≠target ⇒ DENY(token_binding) → prior_state çözülmüş ⇒ DENY(replay) → GRANT_TIER_B → "
                    "audit emit (her karar)",
        "default": "DENY (fail-closed)",
        "fail_safe": "terminal=DENY ⇒ erişim yok (no access); malformed/non-content/maker-yetkisiz/ttl>max/pencere-dışı/"
                     "replay ⇒ DENY; yetersiz onay ⇒ PENDING (token YOK)",
        "core_guarantees": [
            "R3 SoD: TALEP EDEN ≠ ONAYLAYAN; maker kendi talebini onaylayamaz; self-approval quorum'a sayılmaz (sod_violation=0; FR-IAM-009; 12.1.7 RESİPROKAL)",
            "R4 NO GRANT WITHOUT APPROVAL: GRANT_TIER_B yalnız FARKLI yetkili onay (quorum) toplandığında; yetersiz → PENDING (granted_without_approval=0, fail-closed)",
            "R5 TIME-BOX 60/240: token expires_at taşır (unbounded_token=0); ttl default 60dk, max 240dk (4sa); ttl>max GRANT = ttl_exceeds_max=0 (BRD §17.7)",
            "R6 NO STANDING + AUTO-EXPIRY: expires_at sonrası erişim reddedilir (expired_token_access=0); kalıcı/standing token standing_access=0 (BRD §17.7 'otomatik sonlanma, standing access yok')",
            "R7 TOKEN BINDING: token target_tenant + tier B + scope'a bağlı; cross-tenant/tier-dışı = token_binding_violation=0 (FR-TEN-002)",
            "R8 AUDIT (WORM, PII/token-free, immutable): her Tier B kararı DEĞİŞMEZ audit; unaudited_grant=0/audit_pii=0/audit_mutable=0 (12.1.8 RESİPROKAL)",
            "R9 REPLAY-SAFE: çözülmüş grant (expired/revoked/consumed) yeniden kullanılamaz (replay_reuse=0; 12.1.7 RESİPROKAL)",
        ],
        "request_fields": ["name", "request_id", "correlation_id", "break_glass_id", "actor_role(platform_owner|platform_sre|platform_billing)",
                           "action", "target_tenant_id", "resource_type", "data_class(tenant_content)", "reason_code(12.3.3 semantiği)",
                           "now(tick=dakika)", "ttl_minutes(opsiyonel; default 60, max 240)", "quorum(default 1)",
                           "maker{actor_ref,authorized,realm}", "approvals[]{approver_ref,decision,authorized,realm,at}",
                           "access{tenant_id,at}(opsiyonel token-kullanım)", "prior_state(opsiyonel; EXPIRED/REVOKED/CONSUMED)",
                           "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(GRANT_TIER_B|PENDING|DENY)", "note", "actor_role", "target_tenant_id", "data_class",
                            "resource_type", "reason_code", "ttl_minutes", "granted_at", "expires_at", "audit_emitted", "audit_record", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/tier-b-model.json (frozen — separation_of_duties[talep eden ≠ onaylayan] + quorum_policy + "
                 "timebox_policy[60/240/auto-expiry/no-standing] + token_binding + concurrency_policy[replay-safe] + "
                 "audit[WORM,PII/token-free] + actor_roles + table_class_of[37])",
        "consumes": "12.3.1 tier-a (ESCALATE_TIER_B + tenant_content RESİPROKAL); 12.1.7 maker-checker (SoD + timebox + "
                    "breakglass.tier_b RESİPROKAL); 12.1.8 worm-audit (append-only/WORM + hash-zincir RESİPROKAL); "
                    "12.1.1 rbac-model (L0 rolleri); BRD §17.7 + SAD §14.4.2 + FR-IAM-009 (kaynak doğruluk)",
        "consumed_by": "12.3.3 (gerekçe kodu semantiği + tenant security_compliance_officer/tenant_owner bildirimi); "
                       "12.3.4 (regüle tenant require_tenant_approval toggle + DPA); 1.x F1/F2 kod (FastAPI break-glass "
                       "router + time-boxed token verme + WORM audit yazımı); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-IAM-009, FR-IAM-005, FR-IAM-006, FR-REC-009, BRD §17.7, SAD §14.4.2, ADR-013, 12.3.1, 12.1.7, 12.1.8, 12.1.1",
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
            print("kullanım: tier_b_probe.py check <sample.json|dizin>")
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
