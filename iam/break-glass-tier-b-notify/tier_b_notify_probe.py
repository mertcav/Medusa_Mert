#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.3.3 — TIER B BREAK-GLASS: ZORUNLU GEREKÇE KODU (reason code) SEMANTİĞİ + tenant
security_compliance_officer/tenant_owner ANLIK BİLDİRİMİ referans probe.

12. workstream'in (IAM & Erişim) ÜÇ KATMANLI BREAK-GLASS'ın İÇERİK/PII KATMANININ (Tier B)
gerekçe-kodu + bildirim modülü ve F2-Must yeteneği. BRD §17.7/§17 ('Tier B — transkript/kayıt/PII:
... + ZORUNLU GEREKÇE KODU + tenant'ın security_compliance_officer ve tenant_owner rollerine ANLIK
BİLDİRİM') + SAD §14.4.2 (aynı; '... → zorunlu gerekçe kodu → tenant security_compliance_officer +
tenant_owner'a anlık bildirim') + FR-IAM-009 (üç katmanlı break-glass Tier B) + FR-IAM-006/FR-REC-009
(tüm break-glass erişimi audit). ALTIN KURAL (BRD §17): L0 (platform) tenant'ın iş içeriğini VARSAYILAN
GÖREMEZ — Tier B yalnız DAR, SÜRELİ, ONAYLI, TAM-AUDIT'li kapıyı açar; bu modül o kapıya GEREKÇE-KODU
ZORUNLULUĞU + tenant'a ANLIK BİLDİRİM ekler (sessiz break-glass YOK). Bu modül 12.3.2'nin GRANT_TIER_B/
PENDING/DENY (access_decision) çıktısını TÜKETİR; bir BreakGlassTierBNotifyEvent alır → DETERMİNİSTİK,
FAIL-CLOSED karar verir:

    NOTIFY    — erişim verildi (GRANT_TIER_B) + GEÇERLİ gerekçe kodu + her iki tenant rolüne ANLIK +
                TESLİM bildirim + tam-audit.
    NO_NOTIFY — erişim verilmedi (PENDING/DENY) → içerik okunmadı → bildirim GEREKMEZ (doğru ara durum)
                VEYA idempotent (zaten bildirilmiş).
    BLOCK     — malformed / gerekçe kodu eksik (missing_reason_code) / gerekçe kodu geçersiz
                (invalid_reason_code) → fail-closed (erişim geçersiz).

ÇEKİRDEK:
  (1) N2 GEREKÇE KODU ZORUNLU — GRANT_TIER_B gerekçe kodu OLMADAN ilerleyemez (missing_reason_code=0).
  (2) N3 GEREKÇE KODU SEMANTİĞİ — reason_code kontrollü kataloğdan OLMALI; serbest-metin/bilinmeyen →
      BLOCK (invalid_reason_code=0).
  (3) N4 HER İKİ ROL — bildirim security_compliance_officer VE tenant_owner'a gider (incomplete_recipients=0).
  (4) N5 ANLIK — bildirim notify_sla_ticks içinde (delayed_notification=0).
  (5) N6 SESSİZ DEĞİL — her Tier B GRANT teslim edilen bildirim üretir (notification_dropped=0).

      BreakGlassTierBNotifyEvent ─malformed─► access_routing ─► reason_required ─► reason_semantics ─► notification ─► audit/replay
            ├─ request_id / actor_role(L0) / target_tenant / tier≠B / access_decision tanınmaz ──► BLOCK (malformed)
            ├─ access_decision ∈ {PENDING, DENY} (içerik okunmadı) ──────────────────────────────► NO_NOTIFY [N1 doğru]
            ├─ reason_code eksik ──────────────────────────────────────────────────────────────► BLOCK (missing_reason_code) [N2]
            ├─ reason_code katalog dışı / serbest-metin ───────────────────────────────────────► BLOCK (invalid_reason_code) [N3]
            ├─ prior_state çözülmüş (DELIVERED/ACKNOWLEDGED) ──────────────────────────────────► NO_NOTIFY (already_notified) [N9 doğru]
            ├─ eksik zorunlu alıcı rol (SCO veya owner yok) ile NOTIFY ─────────────────────────► incomplete_recipients [N4]
            ├─ SLA dışı (geç) bildirim ────────────────────────────────────────────────────────► delayed_notification [N5]
            ├─ teslim edilmemiş/düşürülmüş bildirim ile GRANT ─────────────────────────────────► notification_dropped [N6]
            ├─ cross-tenant alıcı ─────────────────────────────────────────────────────────────► notification_misroute [N7]
            ├─ NOTIFY audit'siz ───────────────────────────────────────────────────────────────► unaudited_notification [N8]
            └─ audit/bildirim ham PII/token | emitilen audit tahrif (row_hash) ─────────────────► audit_pii / audit_mutable [N8]

Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK; model_hash sha256; tick=dakika sanal-saat). Her karar
terminal (N1) + kanıt + model bütünlük manifesti (N10); metrik düşük-kardinalite + ham PII/token yok (N11);
model/spec/sample ham içerik/PII/token tutmaz (N12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): Tier B erişim-verme (maker-checker + time-boxed token +
token-binding + replay + WORM audit) → 12.3.2 (CONSUMED); regüle tenant require_tenant_approval toggle + DPA
→ 12.3.4; Tier sınıflandırma + ESCALATE → 12.3.1; rol→permission-key/scope → 12.1.2/12.1.3; WORM audit
hash-zinciri → 12.1.8 (CONSUMED). KAYNAK DOĞRULUK; çelişkide BRD §17.7 / SAD §14.4.2 / FR-IAM-009 esastır.

Kullanım:
  tier_b_notify_probe.py validate          Statik model + spec + 12.3.2/12.1.1/12.1.8 resiprokal → çıkış kodu
  tier_b_notify_probe.py check <sample>    Bildirim karar motoru: senaryo(lar) → kapı (N1–N12)
  tier_b_notify_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  tier_b_notify_probe.py schema            Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK (tick=dakika sanal-saat).
Stdlib-only. Sır/credential (break-glass token DEĞERİ) ve ham içerik (PII değeri) üretilmez/yazılmaz (fixture
sentetik — yalnız rol enum + alıcı rol enum + sınıf enum + kaynak adı + tier/decision enum + reason_code enum +
tick tamsayı + slug kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "tier-b-notify-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "tier-b-notify-model.json")
TIER_B_MODEL_PATH = os.path.join(HERE, "..", "break-glass-tier-b", "config", "tier-b-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
WORM_MODEL_PATH = os.path.join(HERE, "..", "worm-audit", "config", "worm-audit-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

TERMINAL = {"NOTIFY", "NO_NOTIFY", "BLOCK"}
GRANT = "GRANT_TIER_B"                                               # yalnız bu access_decision bildirim gerektirir
ACCESS_DECISIONS = {"GRANT_TIER_B", "PENDING", "DENY"}              # 12.3.2 access_decision çıktısı
PLATFORM_ROLES = {"platform_owner", "platform_sre", "platform_billing"}
RECIPIENT_ROLES = ["security_compliance_officer", "tenant_owner"]   # tenant realm L1 alıcı rolleri (12.1.1)
RESOLVED_STATES = {"DELIVERED", "ACKNOWLEDGED"}                     # replay: çözülmüş bildirim
NOTIFY_SLA = 1                                                      # tick=dakika (BRD §17.7 'anlık')
RULES = ["access_routing", "reason_code_required", "reason_code_semantics", "both_recipient_roles",
         "immediate_notification", "no_silent_access", "notification_tenant_binding", "audit_emitted",
         "replay_safe", "model_integrity"]
INVARIANT_IDS = ["N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "N11", "N12"]

# Degrade (inject) — DOĞRU bildirim davranışını bozan müdahaleler.
INJECTIONS = {"omit_reason_code", "freeform_reason", "drop_sco_recipient", "drop_owner_recipient",
              "delayed_notification", "suppress_notification", "cross_tenant_recipient", "notify_replay",
              "skip_audit", "leak_pii_in_notification", "mutate_audit", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "missing_reason_code", "invalid_reason_code", "incomplete_recipients", "delayed_notification",
    "notification_dropped", "notification_misroute", "unaudited_notification", "audit_pii", "audit_mutable",
    "notify_replay", "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (N12; 12.3.2 deseniyle) — ham içerik/PII/token yasak; rol/sınıf/kaynak/tier/reason beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|break_glass_token_value|token_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|bg-|rc-|corr-|tok-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|_repo|tenant_|platform_|security_compliance|global_reference|break_glass|audit_log|usage_record)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/token tarayıcı. Yorum/tarif satırı + rol/sınıf/kaynak/tier adı + slug kimlik eler (12.3.2 deseni)."""
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


def _resolve_recipients(sample, target_tenant_id, model):
    """Bildirim alıcılarını çöz: sample.recipients verilirse onu; yoksa required_recipient_roles → her biri
    target_tenant'a teslim (sanal). Her alıcı {role, tenant_id, delivered, delivered_at}."""
    given = sample.get("recipients")
    if given is not None:
        return [dict(r) for r in given]
    now = sample.get("now", 0)
    roles = model.get("notification_policy", {}).get("required_recipient_roles", RECIPIENT_ROLES)
    return [{"role": r, "tenant_id": target_tenant_id, "delivered": True, "delivered_at": now} for r in roles]


def build(sample, spec, inject=None, model=None):
    """Tek BreakGlassTierBNotifyEvent senaryosunu yürüt → karar + ihlal sayaçları.

    Motor DOĞRU bildirim davranışını hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen ihlal sayacını
    artırır (12.1.x/12.2.x/12.3.1/12.3.2 inject deseniyle birebir)."""
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
    access_decision = sample.get("access_decision")                 # 12.3.2 çıktısı (TÜKETİLİR)
    reason_code = sample.get("reason_code")                         # 12.3.3 semantiği: bu modül DOĞRULAR
    now = sample.get("now", 0)                                      # tick = dakika (Date.now YOK)
    prior_state = sample.get("prior_state")                        # replay: çözülmüş bildirim (opsiyonel)

    catalog = set(model.get("reason_code_policy", {}).get("reason_code_catalog", []))
    required_roles = list(model.get("notification_policy", {}).get("required_recipient_roles", RECIPIENT_ROLES))
    sla = int(model.get("notification_policy", {}).get("notify_sla_ticks", NOTIFY_SLA))

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    note = None
    notified_roles = []
    delivered = False
    audit_emitted = True                                           # ÇEKİRDEK: doğru motor her kararı audit'ler

    # ── N10 model bütünlük manifesti (frozen model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "tier": model.get("tier"),
        "data_class": model.get("data_class"),
        "reason_code_policy": model.get("reason_code_policy"),
        "notification_policy": model.get("notification_policy"),
        "concurrency_policy": model.get("concurrency_policy"),
        "actor_roles": model.get("actor_roles"),
        "audit": model.get("audit"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["reason_code_policy"] = dict(tampered["reason_code_policy"])
        tampered["reason_code_policy"]["require_reason_code"] = False         # gerekçe zorunluluğunu kaldır (tahrifat)
        tampered["notification_policy"] = dict(tampered["notification_policy"])
        tampered["notification_policy"]["required_recipient_roles"] = ["tenant_owner"]  # SCO'yu düşür (tahrifat)
        tampered["notification_policy"]["require_delivery"] = False           # teslim zorunluluğunu kapat (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or actor_role not in PLATFORM_ROLES
                 or not target_tenant_id or tier != "B" or access_decision not in ACCESS_DECISIONS)

    if malformed:
        terminal, note = "BLOCK", "malformed"
    elif access_decision != GRANT:
        # ── N1 access routing: PENDING/DENY → içerik okunmadı → bildirim gerekmez (DOĞRU) ──
        terminal, note = "NO_NOTIFY", "access_not_granted"
    else:
        # ── access_decision == GRANT_TIER_B → gerekçe-kodu + bildirim ZORUNLU ──
        reason_present = bool(reason_code) and "omit_reason_code" not in inject
        reason_valid_correct = bool(reason_code) and reason_code in catalog

        if not reason_present and "omit_reason_code" not in inject:
            # ── N2 doğru: gerekçe kodu eksik → BLOCK (fail-closed) ──
            terminal, note = "BLOCK", "missing_reason_code"
        elif reason_present and reason_code not in catalog and "freeform_reason" not in inject:
            # ── N3 doğru: gerekçe kodu katalog dışı → BLOCK (fail-closed) ──
            terminal, note = "BLOCK", "invalid_reason_code"
        elif prior_state in RESOLVED_STATES and "notify_replay" not in inject:
            # ── N9 doğru: idempotent — çözülmüş bildirim yeniden gönderilmez ──
            terminal, note = "NO_NOTIFY", "already_notified"
        else:
            # ── bildirim üret: zorunlu alıcı roller, target_tenant, teslim, anlık ──
            recipients = _resolve_recipients(sample, target_tenant_id, model)
            notified_roles = [r.get("role") for r in recipients]
            delivered = all(bool(r.get("delivered", True)) for r in recipients) and len(recipients) > 0
            terminal, note = "NOTIFY", "notified"

        # ── degrade müdahaleleri (DOĞRU davranışı boz) — GRANT dalında, terminal'den bağımsız ──
        if not malformed and access_decision == GRANT:
            if "omit_reason_code" in inject:                        # N2: gerekçe yok ama yine de ilerle
                terminal, note = "NOTIFY", "notified"
                reason_code = None
                v["missing_reason_code"] += 1
            if "freeform_reason" in inject and (reason_code is None or reason_code not in catalog):
                terminal, note = "NOTIFY", "notified"               # N3: serbest/geçersiz gerekçe ile ilerle
                v["invalid_reason_code"] += 1

            # bildirim üretildiyse (NOTIFY) alıcı/teslim/anlık/binding degrade'leri uygula
            if terminal == "NOTIFY":
                recipients = _resolve_recipients(sample, target_tenant_id, model)
                if "drop_sco_recipient" in inject:
                    recipients = [r for r in recipients if r.get("role") != "security_compliance_officer"]
                if "drop_owner_recipient" in inject:
                    recipients = [r for r in recipients if r.get("role") != "tenant_owner"]
                if "cross_tenant_recipient" in inject:
                    recipients = [dict(r) for r in recipients]
                    if recipients:
                        recipients[0]["tenant_id"] = "t-other"      # cross-tenant alıcı
                if "delayed_notification" in inject:
                    recipients = [dict(r) for r in recipients]
                    for r in recipients:
                        r["delivered_at"] = now + sla + 30          # SLA dışı (geç)
                if "suppress_notification" in inject:
                    recipients = [dict(r) for r in recipients]
                    for r in recipients:
                        r["delivered"] = False                      # teslim edilmedi (sessiz)

                notified_roles = [r.get("role") for r in recipients]
                delivered = (len(recipients) > 0
                             and all(bool(r.get("delivered", True)) for r in recipients))

                # ── N4 her iki zorunlu rol bildirildi mi? ──
                role_set = set(r.get("role") for r in recipients if bool(r.get("delivered", True)))
                if not all(rr in role_set for rr in required_roles):
                    v["incomplete_recipients"] += 1
                # ── N5 anlık mı? (her alıcı SLA içinde teslim) ──
                for r in recipients:
                    if int(r.get("delivered_at", now)) - now > sla:
                        v["delayed_notification"] += 1
                        break
                # ── N6 sessiz değil mi? (her alıcı teslim) ──
                if not delivered:
                    v["notification_dropped"] += 1
                # ── N7 tenant-bound mu? (her alıcı target_tenant) ──
                for r in recipients:
                    if r.get("tenant_id") != target_tenant_id:
                        v["notification_misroute"] += 1
                        break

            if "notify_replay" in inject and prior_state in RESOLVED_STATES:
                terminal, note = "NOTIFY", "notified"               # N9: çözülmüş bildirim yeniden
                v["notify_replay"] += 1

        # ── N8 audit: degrade — NOTIFY audit ATLA (sessiz audit) ──
        if "skip_audit" in inject and terminal == "NOTIFY":
            audit_emitted = False
        if terminal == "NOTIFY" and not audit_emitted:
            v["unaudited_notification"] += 1

    # ── audit kaydı üret (ÇEKİRDEK: her karar audit'lenir — malformed/block/no_notify dahil break-glass girişimi) ──
    audit_record = _build_audit(
        record_id="aud-%s" % (request_id or "x"), break_glass_id=break_glass_id, correlation_id=correlation_id,
        actor_role=actor_role, actor_realm=model.get("actor_realm", "platform"),
        target_tenant_ref=target_tenant_id, data_class=data_class, resource_type=resource_type,
        tier=tier, decision=terminal, reason_code=reason_code, notified_roles=notified_roles,
        delivered=delivered, occurred_tick=now)
    # ── degrade: audit/bildirim kaydına ham PII/token sok ──
    if "leak_pii_in_notification" in inject and audit_emitted:
        audit_record["pii_field_present"] = True                   # sentetik işaret (gerçek PII/token yazılmaz)
        v["audit_pii"] += 1
    # ── N8 audit immutability — emitilen kayıt değiştirilirse row_hash uyumsuz (WORM; 12.1.8 RESİPROKAL) ──
    if "mutate_audit" in inject and audit_emitted:
        audit_record["decision"] = "tampered"                      # hash sonrası alan değişimi
    if audit_emitted:
        recomputed = _canon_hash({k: val for k, val in audit_record.items() if k != "row_hash"})
        if recomputed != audit_record.get("row_hash"):
            v["audit_mutable"] += 1

    # ── N1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (N1) ──
    evidence = _evidence(request_id, correlation_id, break_glass_id, actor_role, target_tenant_id, data_class,
                         resource_type, access_decision, reason_code, tier, terminal, note, notified_roles,
                         delivered, audit_emitted, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, note, v, actor_role, target_tenant_id, data_class, resource_type,
                 access_decision, reason_code, tier, notified_roles, delivered, audit_emitted, audit_record,
                 model_hash, evidence)


def _build_audit(record_id, break_glass_id, correlation_id, actor_role, actor_realm, target_tenant_ref,
                 data_class, resource_type, tier, decision, reason_code, notified_roles, delivered,
                 occurred_tick):
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
        "reason_code": reason_code,
        "notified_roles": notified_roles,
        "delivered": delivered,
        "occurred_tick": occurred_tick,
    }
    rec["row_hash"] = _canon_hash(rec)
    return rec


def _evidence(request_id, correlation_id, break_glass_id, actor_role, target_tenant_id, data_class,
              resource_type, access_decision, reason_code, tier, terminal, note, notified_roles, delivered,
              audit_emitted, model_hash):
    return {
        "request_id": request_id,
        "correlation_id": correlation_id,
        "break_glass_id": break_glass_id,
        "actor_role": actor_role,
        "target_tenant_id": target_tenant_id,
        "data_class": data_class,
        "resource_type": resource_type,
        "access_decision": access_decision,
        "reason_code": reason_code,
        "tier": tier,
        "terminal": terminal,
        "note": note,
        "notified_roles": notified_roles,
        "delivered": delivered,
        "audit_emitted": audit_emitted,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, note, v, actor_role, target_tenant_id, data_class, resource_type, access_decision,
          reason_code, tier, notified_roles, delivered, audit_emitted, audit_record, model_hash, evidence):
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
        "reason_code": reason_code,
        "tier": tier,
        "notified_roles": notified_roles,
        "delivered": delivered,
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
        "missing_reason_code": "max_missing_reason_code",
        "invalid_reason_code": "max_invalid_reason_code",
        "incomplete_recipients": "max_incomplete_recipients",
        "delayed_notification": "max_delayed_notification",
        "notification_dropped": "max_notification_dropped",
        "notification_misroute": "max_notification_misroute",
        "unaudited_notification": "max_unaudited_notification",
        "audit_pii": "max_audit_pii",
        "audit_mutable": "max_audit_mutable",
        "notify_replay": "max_notify_replay",
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
        for key in ("terminal", "note", "delivered", "reason_code"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))
        if "notified_roles" in exp_assert and sorted(exp_assert["notified_roles"]) != sorted(res.get("notified_roles") or []):
            mism.append("notified_roles: beklenen=%r gerçek=%r" % (exp_assert["notified_roles"], res.get("notified_roles")))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s note=%s access=%s reason=%s roles=%s delivered=%s audit=%s"
              % (res["terminal"], res["note"], res["access_decision"], res["reason_code"],
                 res["notified_roles"], res["delivered"], res["audit_emitted"]))
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
    chk("wbs=12.3.3", spec.get("wbs") == "12.3.3")
    chk("phase=F2", spec.get("phase") == "F2")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-009 izlenir (üç katmanlı break-glass — ÇEKİRDEK)", "FR-IAM-009" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (tüm işlemler audit)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-REC-009 izlenir (erişim audit)", "FR-REC-009" in tr.get("fr", []))
    chk("BRD §17.7 izlenir (Tier B — gerekçe kodu + bildirim)", any("§17.7" in s for s in tr.get("brd", [])))
    chk("SAD §14.4.2 Tier B izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-013 izlenir (üç katmanlı break-glass)", any(a.startswith("ADR-013") for a in tr.get("adr", [])))
    chk("12.3.2 tier-b TÜKETİLİR (access_decision RESİPROKAL)",
        any("12.3.2" in s for s in tr.get("consumes", [])))
    chk("12.1.1 rbac TÜKETİLİR (alıcı tenant rolleri RESİPROKAL)",
        any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.8 worm-audit TÜKETİLİR (WORM audit RESİPROKAL)",
        any("12.1.8" in s for s in tr.get("consumes", [])))
    chk("12.3.4 DELEGE (consumed_by/delegates)",
        any("12.3.4" in s for s in tr.get("consumed_by", [])) or any("12.3.4" in s for s in tr.get("delegates", [])))

    # 3) On kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("on kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→access_routing→reason_required→reason_semantics→notification→audit/replay",
        rz.get("evaluation") == "malformed_then_access_routing_then_reason_required_then_reason_semantics_then_notification_then_audit_replay")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower()
        or "erişim" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar NOTIFY/NO_NOTIFY/BLOCK", set(oc.get("list", [])) == TERMINAL)

    # 6) Enforcement — gerekçe kodu + bildirim + audit
    en = spec["enforcement"]
    chk("reason_code zorunlu + katalog",
        "zorunlu" in en.get("reason_code", "").lower() and ("katalog" in en.get("reason_code", "").lower() or "catalog" in en.get("reason_code", "").lower()))
    chk("notification her iki rol + anlık + teslim",
        "security_compliance_officer" in en.get("notification", "") and "tenant_owner" in en.get("notification", "")
        and ("anlık" in en.get("notification", "").lower()))
    chk("audit_layer WORM (12.1.8 RESİPROKAL)", "12.1.8" in en.get("audit_layer", "") and "WORM" in en.get("audit_layer", "").upper())

    # 7) Model alanları
    md = spec["model"]
    chk("model tier=B", md.get("tier") == "B")
    chk("model data_class=tenant_content", md.get("data_class") == "tenant_content")
    chk("model required_recipient_roles = SCO + owner",
        set(md.get("required_recipient_roles", [])) == set(RECIPIENT_ROLES))
    chk("model actor_roles = L0 platform rolleri", set(md.get("actor_roles", [])) == PLATFORM_ROLES)

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_missing_reason_code", "max_invalid_reason_code", "max_incomplete_recipients",
               "max_delayed_notification", "max_notification_dropped", "max_notification_misroute",
               "max_unaudited_notification", "max_audit_pii", "max_audit_mutable", "max_notify_replay",
               "max_model_tampered", "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("l0_break_glass_notify_total metrik", "l0_break_glass_notify_total" in obs.get("metrics", []))
    chk("break_glass_notify_violation_total metrik (alarm)", "break_glass_notify_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("break_glass_id/target_tenant_id/reason_code YÜKSEK kard (label değil)",
        "break_glass_id" in hi and "break_glass_id" not in lo and "target_tenant_id" in hi and "reason_code" in hi)
    chk("actor_role/decision/result/recipient_role DÜŞÜK kard",
        all(x in lo for x in ("actor_role", "decision", "result", "recipient_role")))
    chk("alarm notification_dropped/incomplete_recipients/missing_reason_code ≤2dk",
        any(x in obs.get("alarm", "") for x in ("notification_dropped", "incomplete_recipients", "missing_reason_code", "notification_misroute")))

    # 10) İnvariant'lar N1–N12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar N1–N12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (BRD §17.7 / SAD §14.4.2)
    mm_ok = os.path.exists(MODEL_PATH)
    chk("config/tier-b-notify-model.json var", mm_ok)
    if mm_ok:
        mm = _model()
        chk("model frozen=true", mm.get("frozen") is True)
        chk("model fail_closed=true", mm.get("fail_closed") is True)
        chk("model tier=B + data_class=tenant_content",
            mm.get("tier") == "B" and mm.get("data_class") == "tenant_content")
        chk("model reason require_reason_code=true + controlled_vocabulary=true + free_text_forbidden=true",
            mm.get("reason_code_policy", {}).get("require_reason_code") is True
            and mm.get("reason_code_policy", {}).get("controlled_vocabulary") is True
            and mm.get("reason_code_policy", {}).get("free_text_forbidden") is True)
        chk("model reason_code_catalog ≥3 opak kod (rc-*)",
            len(mm.get("reason_code_policy", {}).get("reason_code_catalog", [])) >= 3
            and all(c.startswith("rc-") for c in mm.get("reason_code_policy", {}).get("reason_code_catalog", [])))
        chk("model notification required_recipient_roles = SCO + owner (12.1.1 RESİPROKAL)",
            set(mm.get("notification_policy", {}).get("required_recipient_roles", [])) == set(RECIPIENT_ROLES))
        chk("model notification immediate + require_delivery + no_silent_access + tenant_bound + pii_free",
            mm.get("notification_policy", {}).get("immediate") is True
            and mm.get("notification_policy", {}).get("require_delivery") is True
            and mm.get("notification_policy", {}).get("no_silent_access") is True
            and mm.get("notification_policy", {}).get("tenant_bound") is True
            and mm.get("notification_policy", {}).get("pii_free") is True)
        chk("model notification trigger_on=GRANT_TIER_B + notify_sla_ticks ≥1",
            mm.get("notification_policy", {}).get("trigger_on") == GRANT
            and mm.get("notification_policy", {}).get("notify_sla_ticks", 0) >= 1)
        chk("model recipient_realm=tenant (alıcılar tenant realm)",
            mm.get("notification_policy", {}).get("recipient_realm") == "tenant")
        chk("model audit required_for_every_decision=true + worm=true + no_raw_token=true",
            mm.get("audit", {}).get("required_for_every_decision") is True
            and mm.get("audit", {}).get("worm") is True
            and mm.get("audit", {}).get("no_raw_token") is True)
        chk("model audit break_glass_id + notified_roles record alanları",
            "break_glass_id" in mm.get("audit", {}).get("record_fields", [])
            and "notified_roles" in mm.get("audit", {}).get("record_fields", []))
        chk("model concurrency resolved_states = DELIVERED/ACKNOWLEDGED (replay-safe)",
            set(mm.get("concurrency_policy", {}).get("resolved_states", [])) == RESOLVED_STATES)

    # 12) 12.3.2 RESİPROKAL — Tier B access_decision + reason_code DELEGE
    tb_ok = os.path.exists(TIER_B_MODEL_PATH)
    chk("12.3.2 ../break-glass-tier-b/config/tier-b-model.json var (access_decision — TÜKETİLİR)", tb_ok)
    if tb_ok and mm_ok:
        tb = _load(TIER_B_MODEL_PATH)
        chk("12.3.2 terminal GRANT_TIER_B üretir (bu modül access_decision olarak TÜKETİR; RESİPROKAL)",
            GRANT in tb.get("terminal", []))
        chk("12.3.2 tier=B + data_class=tenant_content = bu modül (RESİPROKAL)",
            tb.get("tier") == "B" and tb.get("data_class") == "tenant_content"
            and tb.get("tier") == _model().get("tier"))
        chk("12.3.2 reason_code semantiği + bildirim 12.3.3'e DELEGE (RESİPROKAL)",
            "12.3.3" in tb.get("delegates", {}).get("reason_code_semantics_and_notification", ""))

    # 13) 12.1.1 RESİPROKAL — alıcı tenant rolleri + L0 aktör rolleri
    rb_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (RBAC rolleri — TÜKETİLİR)", rb_ok)
    if rb_ok:
        rbac = _load(RBAC_MODEL_PATH)
        roles = rbac.get("roles", {})
        chk("12.1.1 alıcı rolleri SCO + owner mevcut + tenant realm (RESİPROKAL)",
            all(r in roles for r in RECIPIENT_ROLES)
            and roles.get("security_compliance_officer", {}).get("realm") == "tenant"
            and roles.get("tenant_owner", {}).get("realm") == "tenant")
        chk("12.1.1 L0 platform aktör rolleri (owner/sre/billing) mevcut (RESİPROKAL)",
            all(role in roles for role in PLATFORM_ROLES))

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
    chk("hiç ham-içerik/PII/token sızıntısı yok (N12)", total_leaks == 0)

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
        # Varsayılan: platform_owner, transcript, access_decision=GRANT_TIER_B, geçerli reason_code →
        # NOTIFY + her iki tenant rolüne (SCO + owner) anlık teslim bildirim + audit.
        d = {
            "request_id": "req-1", "correlation_id": "corr-1", "break_glass_id": "bg-1",
            "actor_role": "platform_owner", "target_tenant_id": "t-acme", "tier": "B",
            "resource_type": "transcript", "data_class": "tenant_content",
            "access_decision": "GRANT_TIER_B", "reason_code": "rc-incident-debug", "now": 100,
        }
        d.update(kw)
        return d

    # 1) happy — GRANT + geçerli gerekçe → NOTIFY + her iki rol + teslim + audit, ihlal yok
    r = build(ev(), spec)
    case("happy: NOTIFY (GRANT + geçerli reason)", r["terminal"] == "NOTIFY")
    case("happy: her iki rol bildirildi (SCO + owner)",
         set(r["notified_roles"]) == set(RECIPIENT_ROLES))
    case("happy: delivered=True (teslim)", r["delivered"] is True)
    case("happy: audit_emitted=True + row_hash var (WORM)",
         r["audit_emitted"] is True and r["audit_record"].get("row_hash") is not None)
    case("happy: break_glass_id audit'te", r["audit_record"].get("break_glass_id") is not None)
    case("happy: model_hash var (N10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(ev(), spec), build(ev(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) N1 — access routing: PENDING/DENY → NO_NOTIFY (içerik okunmadı, doğru)
    rpend = build(ev(access_decision="PENDING"), spec)
    case("routing: PENDING → NO_NOTIFY (bildirim gerekmez)", rpend["terminal"] == "NO_NOTIFY")
    case("routing: PENDING doğru → ihlal yok + kapı geçer",
         all(x == 0 for x in rpend["violations"].values()) and _gate_eval(rpend, G)[0] is True)
    rden = build(ev(access_decision="DENY"), spec)
    case("routing: DENY → NO_NOTIFY (içerik okunmadı)", rden["terminal"] == "NO_NOTIFY")
    case("routing: DENY de audit'lenir (her break-glass girişimi)", rden["audit_emitted"] is True)

    # 4) N2 ÇEKİRDEK gerekçe kodu zorunlu — eksik → BLOCK; degrade omit_reason_code → missing_reason_code
    rmiss = build(ev(reason_code=None), spec)
    case("reason-required: reason_code yok → BLOCK (missing_reason_code)",
         rmiss["terminal"] == "BLOCK" and rmiss["note"] == "missing_reason_code")
    case("reason-required: doğru → missing_reason_code=0 + kapı geçer",
         rmiss["violations"]["missing_reason_code"] == 0 and _gate_eval(rmiss, G)[0] is True)
    romit = build(ev(reason_code=None), spec, inject=["omit_reason_code"])
    case("reason-required degrade: omit_reason_code → NOTIFY + missing_reason_code>0 + kapı eler",
         romit["terminal"] == "NOTIFY" and romit["violations"]["missing_reason_code"] > 0
         and _gate_eval(romit, G)[0] is False)

    # 5) N3 ÇEKİRDEK gerekçe semantiği — katalog dışı → BLOCK; degrade freeform_reason → invalid_reason_code
    rinv = build(ev(reason_code="because-i-want"), spec)
    case("reason-semantics: katalog dışı → BLOCK (invalid_reason_code)",
         rinv["terminal"] == "BLOCK" and rinv["note"] == "invalid_reason_code")
    case("reason-semantics: doğru → invalid_reason_code=0 + kapı geçer",
         rinv["violations"]["invalid_reason_code"] == 0 and _gate_eval(rinv, G)[0] is True)
    rfree = build(ev(reason_code="because-i-want"), spec, inject=["freeform_reason"])
    case("reason-semantics degrade: freeform_reason → NOTIFY + invalid_reason_code>0 + kapı eler",
         rfree["terminal"] == "NOTIFY" and rfree["violations"]["invalid_reason_code"] > 0
         and _gate_eval(rfree, G)[0] is False)
    # katalogdaki tüm kodlar geçerli
    case("reason-semantics: rc-quality-review (katalog) → NOTIFY",
         build(ev(reason_code="rc-quality-review"), spec)["terminal"] == "NOTIFY")

    # 6) N4 ÇEKİRDEK her iki rol — degrade drop_sco/drop_owner → incomplete_recipients
    rdsco = build(ev(), spec, inject=["drop_sco_recipient"])
    case("both-roles degrade: drop_sco_recipient → incomplete_recipients>0 + kapı eler",
         rdsco["violations"]["incomplete_recipients"] > 0 and _gate_eval(rdsco, G)[0] is False)
    case("both-roles degrade: SCO düştü → notified_roles'ta yok",
         "security_compliance_officer" not in rdsco["notified_roles"])
    rdown = build(ev(), spec, inject=["drop_owner_recipient"])
    case("both-roles degrade: drop_owner_recipient → incomplete_recipients>0 + kapı eler",
         rdown["violations"]["incomplete_recipients"] > 0 and _gate_eval(rdown, G)[0] is False)

    # 7) N5 ÇEKİRDEK anlık — degrade delayed_notification → delayed_notification
    rdelay = build(ev(), spec, inject=["delayed_notification"])
    case("immediate degrade: delayed_notification → delayed_notification>0 + kapı eler",
         rdelay["violations"]["delayed_notification"] > 0 and _gate_eval(rdelay, G)[0] is False)
    # SLA içinde teslim (now) → anlık, doğru
    case("immediate: SLA içinde (delivered_at=now) → delayed_notification=0",
         build(ev(), spec)["violations"]["delayed_notification"] == 0)

    # 8) N6 ÇEKİRDEK sessiz değil — degrade suppress_notification → notification_dropped
    rsupp = build(ev(), spec, inject=["suppress_notification"])
    case("no-silent degrade: suppress_notification → notification_dropped>0 + delivered=False + kapı eler",
         rsupp["violations"]["notification_dropped"] > 0 and rsupp["delivered"] is False
         and _gate_eval(rsupp, G)[0] is False)

    # 9) N7 — tenant binding: degrade cross_tenant_recipient → notification_misroute
    rxt = build(ev(), spec, inject=["cross_tenant_recipient"])
    case("binding degrade: cross_tenant_recipient → notification_misroute>0 + kapı eler",
         rxt["violations"]["notification_misroute"] > 0 and _gate_eval(rxt, G)[0] is False)

    # 10) N8 — audit emitted/PII-free/immutable
    rsk = build(ev(), spec, inject=["skip_audit"])
    case("audit: skip_audit → unaudited_notification>0 + audit_emitted=False + kapı eler",
         rsk["violations"]["unaudited_notification"] > 0 and rsk["audit_emitted"] is False
         and _gate_eval(rsk, G)[0] is False)
    case("audit: NO_NOTIFY/BLOCK de audit'lenir",
         build(ev(access_decision="DENY"), spec)["audit_emitted"] is True
         and build(ev(reason_code=None), spec)["audit_emitted"] is True)
    rpii = build(ev(), spec, inject=["leak_pii_in_notification"])
    case("audit: leak_pii_in_notification → audit_pii>0 + kapı eler",
         rpii["violations"]["audit_pii"] > 0 and _gate_eval(rpii, G)[0] is False)
    rmut = build(ev(), spec, inject=["mutate_audit"])
    case("audit: mutate_audit → audit_mutable>0 (WORM ihlali) + kapı eler",
         rmut["violations"]["audit_mutable"] > 0 and _gate_eval(rmut, G)[0] is False)
    case("audit: ham PII/token alanı yok",
         all(k not in json.dumps(r) for k in ("transcript_text_value", "recording_audio_value", "break_glass_token_value")))

    # 11) N9 — replay-safe: çözülmüş bildirim diriltilemez; degrade notify_replay
    rrep = build(ev(prior_state="DELIVERED"), spec)
    case("replay: prior_state=DELIVERED → NO_NOTIFY (already_notified, idempotent)",
         rrep["terminal"] == "NO_NOTIFY" and rrep["note"] == "already_notified")
    rrepi = build(ev(prior_state="DELIVERED"), spec, inject=["notify_replay"])
    case("replay degrade: notify_replay → NOTIFY + notify_replay>0 + kapı eler",
         rrepi["terminal"] == "NOTIFY" and rrepi["violations"]["notify_replay"] > 0
         and _gate_eval(rrepi, G)[0] is False)

    # 12) N10 — model integrity
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
    case("evidence: request+actor+target_tenant+access+reason+tier+notified_roles+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "actor_role", "target_tenant_id", "access_decision",
                                          "reason_code", "tier", "notified_roles", "delivered", "model_hash")))
    case("leak: rol+sınıf+tier+reason temiz",
         scan_leaks('{"actor_role":"platform_owner","data_class":"tenant_content","tier":"B","reason_code":"rc-incident-debug","notified_roles":["security_compliance_officer","tenant_owner"]}') == [])
    case("leak: break_glass_token_value alanı yakalanır", len(scan_leaks('{"break_glass_token_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "break-glass-tier-b-notify (WBS 12.3.3 — Tier B break-glass: zorunlu gerekçe kodu [reason code] "
                  "semantiği + tenant security_compliance_officer/tenant_owner anlık bildirimi; BRD §17.7, SAD §14.4.2, FR-IAM-009)",
        "outcomes": sorted(TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "data_class": "tenant_content",
        "actor_roles": sorted(PLATFORM_ROLES),
        "recipient_roles": RECIPIENT_ROLES,
        "notify_sla_ticks": NOTIFY_SLA,
        "decision": "malformed ⇒ BLOCK(malformed) → access_decision ∈ {PENDING,DENY} ⇒ NO_NOTIFY → reason_code eksik ⇒ "
                    "BLOCK(missing_reason_code) → reason_code ∉ catalog ⇒ BLOCK(invalid_reason_code) → prior_state çözülmüş ⇒ "
                    "NO_NOTIFY(already_notified) → recipients={SCO,owner}@target_tenant teslim+anlık ⇒ NOTIFY → audit emit (her karar)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ erişim geçersiz; malformed/eksik-gerekçe/geçersiz-gerekçe ⇒ BLOCK; "
                     "erişim verilmedi [PENDING/DENY] ⇒ NO_NOTIFY",
        "core_guarantees": [
            "N2 GEREKÇE KODU ZORUNLU: GRANT_TIER_B gerekçe kodu olmadan ilerleyemez (missing_reason_code=0; FR-IAM-009)",
            "N3 GEREKÇE KODU SEMANTİĞİ: reason_code kontrollü kataloğdan; serbest-metin/bilinmeyen → BLOCK (invalid_reason_code=0)",
            "N4 HER İKİ ROL: bildirim security_compliance_officer VE tenant_owner'a gider (incomplete_recipients=0; 12.1.1 RESİPROKAL)",
            "N5 ANLIK: bildirim notify_sla_ticks içinde teslim (delayed_notification=0)",
            "N6 SESSİZ DEĞİL: her Tier B GRANT teslim edilen bildirim üretir (notification_dropped=0; altın kural BRD §17)",
            "N7 TENANT-BINDING: alıcılar yalnız target_tenant; cross-tenant = notification_misroute=0 (FR-TEN-002)",
            "N8 AUDIT (WORM, PII/token-free, immutable): her bildirim kararı DEĞİŞMEZ audit; unaudited_notification=0/audit_pii=0/audit_mutable=0 (12.1.8 RESİPROKAL)",
        ],
        "event_fields": ["name", "request_id", "correlation_id", "break_glass_id", "actor_role(platform_owner|platform_sre|platform_billing)",
                         "target_tenant_id", "tier(B)", "resource_type", "data_class(tenant_content)",
                         "access_decision(GRANT_TIER_B|PENDING|DENY — 12.3.2 çıktısı)", "reason_code(12.3.3 doğrular)",
                         "now(tick=dakika)", "recipients[]{role,tenant_id,delivered,delivered_at}(opsiyonel)",
                         "prior_state(opsiyonel; DELIVERED/ACKNOWLEDGED)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(NOTIFY|NO_NOTIFY|BLOCK)", "note", "actor_role", "target_tenant_id", "data_class",
                            "resource_type", "access_decision", "reason_code", "tier", "notified_roles", "delivered",
                            "audit_emitted", "audit_record", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/tier-b-notify-model.json (frozen — reason_code_policy[require + controlled_vocabulary + catalog] + "
                 "notification_policy[required_recipient_roles=SCO+owner + immediate + require_delivery + tenant_bound + pii_free] + "
                 "concurrency_policy[replay-safe] + audit[WORM,PII/token-free] + actor_roles)",
        "consumes": "12.3.2 tier-b (access_decision GRANT_TIER_B/PENDING/DENY + reason_code taşıma + break_glass_id RESİPROKAL); "
                    "12.1.1 rbac-model (SCO + owner alıcı tenant rolleri + L0 aktör rolleri); 12.1.8 worm-audit (append-only/WORM + "
                    "hash-zincir RESİPROKAL); BRD §17.7 + SAD §14.4.2 + FR-IAM-009 (kaynak doğruluk)",
        "consumed_by": "12.3.4 (regüle tenant require_tenant_approval toggle + DPA); 1.x F1/F2 kod (FastAPI break-glass router + "
                       "bildirim dispatch + WORM audit yazımı); 0.4.7 gözlemlenebilirlik",
        "trace": "FR-IAM-009, FR-IAM-006, FR-REC-009, BRD §17.7, SAD §14.4.2, ADR-013, 12.3.2, 12.1.1, 12.1.8",
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
            print("kullanım: tier_b_notify_probe.py check <sample.json|dizin>")
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
