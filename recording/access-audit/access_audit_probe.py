#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.6 — Kayıt/transkript erişim audit'i (access-audit) referans probe.

11. workstream'in (Kayıt, Transkript & PII Redaction) ERİŞİM AUDIT modülü ve F1-Must temel yeteneği.
FR-REC-009 ('Kayıt ve transkript erişimleri audit edilmelidir') + SR-REC-009 + TC-REC-009 (A) +
FR-REC-008 (yetkili kullanıcı dinler/görür) + FR-IAM-006 (WORM audit + bütünlük) + FR-IAM-008/009/010
(L0 altın kural + üç katmanlı break-glass) + DB §27 audit_log (WORM append-only + prev_hash/row_hash
hash chain)'i sahiplenir. Bir kayıt (recording) VEYA transkript (transcript) erişim talebini alır →
DETERMİNİSTİK, FAIL-CLOSED bir erişim audit KARARI verir: tenant izolasyonu + audit-sink kapısı +
yetki (RBAC permission + sahiplik + L0 Tier B break-glass) + ZORUNLU WORM audit (hash-chained) +
residency. Bir terminal {GRANTED | DENIED | BLOCK} kararı döner.

  AccessAuditRequest ─tenant─► audit-sink ─► yetki ─► break-glass ─► WORM audit ─► residency
        │                │           │          │           │
        │      ├─ cross-tenant (tenant realm) ──────────────────────────────────► BLOCK (cross_tenant)      [K12]
        │      ├─ malformed (resource/action/realm) ────────────────────────────► BLOCK (malformed_request)
        │      ├─ audit-sink yok ───────────────────────────────────────────────► BLOCK (no_audit_sink)     [K2/K5]
        │      ├─ yetki yok / sahiplik dışı / raw yetki yok ────────────────────► DENIED (audited)           [K4]
        │      ├─ L0 Tier B break-glass yok/geçersiz ──────────────────────────► DENIED (audited)            [K6]
        │      └─ yetkili ───────────────────────────────────────────────────────► GRANTED (audited)         [K4]

ÇEKİRDEK: (1) K2 ZORUNLU ERİŞİM AUDIT'i (FR-REC-009 ÇEKİRDEK) — HER erişim kararı (GRANTED ya da DENIED)
bir WORM audit kaydı üretir; audit YAZILMADAN erişim verilemez (access_granted ⇒ audit_written); audit-sink
yoksa fail-closed BLOCK (auditlenemeyen erişim verilmez); audit'siz erişim = unaudited_access; (2) K3 WORM/
HASH-CHAIN BÜTÜNLÜĞÜ (FR-IAM-006, DB §27) — audit kaydı append-only + prev_hash→row_hash zincirli; tahrifat
(audit_tampered) / zincir kırılması (chain_break) yasak; (3) K4 YETKİ KAPISI (FR-REC-008 ÇEKİRDEK) — erişim
YALNIZ aktör gerekli permission'a (+ sahiplik :own + L0 Tier B için geçerli break-glass) sahipse GRANTED;
yetkisiz GRANTED = unauthorized_access; (4) K5 ATLANAMAZ / FAIL-CLOSED — audit bypass edilemez (skip_audit);
audit-sink yoksa erişim verilemez (failopen yasak); L0 altın kuralı: tenant içeriğine break-glass'sız erişim
reddedilir; (5) K6 BREAK-GLASS DİSİPLİNİ (FR-IAM-009/010) — L0 platform Tier B erişimi maker≠checker +
süreli + gerekçe kodu + tenant-kapsamlı grant ister; self-approval/expired/standing = break_glass_violation;
(6) K8 HAM İÇERİK/PII YOK (BRD §17.7) — audit/kanıt/metrik YALNIZ yapısal kimlik + enum + break_glass_id
taşır, ASLA ham kayıt byte / transkript metni / PII değeri (pii_leak). Motor bir DETERMİNİSTİK FAIL-CLOSED
karar fonksiyonudur (Date.now/random YOK; hash chain sha256 deterministik). Her karar terminal (K1) + kanıt
(K9) + audit (K10); metrik düşük-kardinalite + ham PII yok (K11); spec/config/sample ham içerik/PII/credential
tutmaz (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): kayıt/içerik KARARI + tamamen kapatma → 11.1 (FR-REC-001/002);
kanal/track → 11.2 (FR-REC-003); transkript ÜRETİMİ → 11.3 (FR-REC-008/BRD §8.1); PII redaction (maskeleme
PLANI + redaction_state) → 11.4 (FR-REC-004; access_ready TÜKETİLİR); kart/parola/OTP kayıttan çıkarma →
11.5 (FR-REC-005); break-glass talep/onay AKIŞI (maker-checker workflow + grant üretimi) → FR-IAM-009 /
API §6 break-glass router (bu modül grant'ı TÜKETİR/DOĞRULAR, üretmez); audit_log FİZİKSEL şeması + WORM
depolama + retention → DB §27 / 1.1.x / retention motoru (bu modül audit KAYDINI + hash zincirini ÜRETİR,
fiziksel WORM yazımı altyapıda); RBAC permission ATAMASI → FR-IAM-011 / ADR-012 (permission'lar TÜKETİLİR);
ham içerik byte sunumu (recording stream / transcript view) → SAD §10.2 + panel L2 A-11/A-12/A-13 (karar
verilir, içerik bu modülde akmaz); residency depolama UYGULAMASI → DB §8 / SAD §12.1.

Kullanım:
  access_audit_probe.py validate          Statik spec/config/kapsama kapısı → çıkış kodu
  access_audit_probe.py check <sample>     Erişim audit motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  access_audit_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  access_audit_probe.py schema             Karar sözleşmesini yazdır

Determinizm: hash chain sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential
ve ham içerik (kayıt byte / transkript metni / PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız
yapısal kimlik + enum + maskeli/hash; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "access-audit-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "access-audit.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["GRANTED", "DENIED", "BLOCK"]
TERMINAL = {"GRANTED", "DENIED", "BLOCK"}
# Erişimin fiilen gerçekleştiği (içeriğe ulaşıldığı) terminal.
ACCESS_TERMINALS = {"GRANTED"}
# Audit kaydı ZORUNLU olan terminaller (no_audit_sink BLOCK hariç — auditlenemez).
AUDITED_TERMINALS = {"GRANTED", "DENIED"}
RULES = ["mandatory_audit", "worm_chain_integrity", "authorization_gate",
         "mandatory_fail_closed", "break_glass_discipline", "residency_honored", "no_raw_content"]
DENY_REASONS = ["missing_permission", "insufficient_scope", "break_glass_required", "break_glass_invalid"]
BLOCK_REASONS = ["cross_tenant", "no_audit_sink", "malformed_request"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
RESOURCE_TYPES = {"recording", "transcript"}
ACCESS_ACTIONS = {"listen", "view", "download", "export"}
ACCESS_MODES = {"masked", "raw"}
ACTOR_REALMS = {"tenant", "platform"}

# Degrade (inject) — DOĞRU fail-closed / zorunlu-audit / yetki davranışını bozan müdahaleler.
INJECTIONS = {"skip_audit", "unauthorized_grant", "audit_tamper", "chain_break", "self_approval",
              "expired_grant", "standing_access", "failopen_audit", "pii_leak", "residency_leak",
              "cross_tenant", "no_audit"}

VIOLATION_KEYS = [
    "unaudited_access", "unauthorized_access", "audit_tampered", "chain_break", "break_glass_violation",
    "failopen", "residency_violation", "pii_leak", "cross_tenant", "missing_evidence", "missing_audit",
    "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.1–11.4 deseniyle) — ham içerik/PII (kayıt byte/transkript metni/...) yasak ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(recording_bytes|recording_audio|transcript_text|segment_text|raw_audio|raw_value|pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value)\"\s*:")),
]
# Yapısal kimlik/enum/sayı/hash/maskeli-token beyaz-listelenir.
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|call-|bg-|ev-|seg-|camp-|t-|u-|corr-|prefix|masked|last4|grant|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2})")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + maskeli token + kısa offset eler (11.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"desc"' in line or '"trace"' in line or '"rule"' in line:
                    continue
                if LEAK_ALLOW.search(window) or LEAK_ALLOW.search(frag):
                    continue
                hits.append((ln, name, frag))
    return hits


# ════════════════════════════════════════════════════════════════════════════
def _config(sample):
    """Config = ana access-audit.json; sample.config_override yapısal alanları geçersiz kılar."""
    cfg = _load(CONFIG_PATH)
    ov = sample.get("config_override", {}) or {}
    for k in ("resource_permission", "tier_b_resources", "break_glass", "access_actions",
              "access_modes", "actor_realms"):
        if k in ov:
            if isinstance(ov[k], dict) and isinstance(cfg.get(k), dict):
                cfg.setdefault(k, {}).update(ov[k])
            else:
                cfg[k] = ov[k]
    return cfg


def _canon_hash(prev_hash, record):
    """WORM hash chain: row_hash = sha256(prev_hash + kanonik(record)) — deterministik (sort_keys)."""
    payload = (prev_hash or "") + json.dumps(record, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_permission(resource_type, access_mode, ownership, rescfg):
    """Erişim için gerekli RBAC permission'ı çöz (kaynak + mod + sahiplik)."""
    spec = rescfg.get(resource_type, {})
    if resource_type == "transcript" and access_mode == "raw":
        # Ham (maskelenmemiş) transkript erişimi yükseltilmiş yetki ister (API §6.x, FR-REC-009).
        return spec.get("raw_permission"), None
    base = spec.get("base_permission")
    own = spec.get("own_permission")
    return base, own


def build(sample, spec, inject=None, cfg=None):
    """Tek erişim-audit senaryosunu yürüt → AccessAuditDecision + ihlal sayaçları.

    Motor DOĞRU fail-closed / zorunlu-audit / yetki davranışını hesaplar; inject (degrade) doğru davranışı
    bozar ve eşleşen ihlal sayacını artırır (11.1–11.4 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    cfg = cfg if cfg is not None else _config(sample)

    tenant = sample.get("tenant_id")
    call_id = sample.get("call_id")
    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id")
    actor_user_id = sample.get("actor_user_id")
    actor_realm = sample.get("actor_realm")
    actor_role = sample.get("actor_role")
    resource_type = sample.get("resource_type")
    access_action = sample.get("access_action")
    access_mode = sample.get("access_mode", "masked")
    actor_permissions = set(sample.get("actor_permissions", []) or [])
    ownership = sample.get("ownership", "other")
    bg = sample.get("break_glass")
    in_region = bool(sample.get("in_region_storage_required", False))
    storage_region = sample.get("storage_region")
    home_region = sample.get("home_region")
    served_region = sample.get("served_region", storage_region)
    audit_sink = bool(sample.get("audit_sink_available", True))
    prev_chain_hash = sample.get("prev_chain_hash")

    rescfg = cfg.get("resource_permission", {})
    tier_b = set(cfg.get("tier_b_resources", ["recording", "transcript"]))
    bgcfg = cfg.get("break_glass", {})

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    block_reason = None
    deny_reason = None
    authorized = False
    access_granted = False
    audit_written = False
    audit = None
    break_glass_id = None
    used_break_glass = False

    # ── K12 (tenant izolasyonu) ──
    if "cross_tenant" in inject:
        v["cross_tenant"] += 1
    if actor_realm == "tenant" and sample.get("bind_tenant") and sample.get("bind_tenant") != tenant:
        v["cross_tenant"] += 1

    # ── malformed / cross-tenant → fail-closed BLOCK (içeriğe erişim yok) ──
    malformed = (resource_type not in RESOURCE_TYPES or access_action not in ACCESS_ACTIONS
                 or actor_realm not in ACTOR_REALMS or not request_id or not actor_user_id)

    if v["cross_tenant"] > 0:
        terminal, block_reason = "BLOCK", "cross_tenant"
    elif malformed:
        terminal, block_reason = "BLOCK", "malformed_request"
    elif not audit_sink and "failopen_audit" not in inject:
        # ── K2/K5 ÇEKİRDEK: auditlenemeyen erişim VERİLMEZ → fail-closed BLOCK ──
        terminal, block_reason = "BLOCK", "no_audit_sink"
    else:
        # ── K6 break-glass: L0 platform Tier B erişimi geçerli grant ister ──
        bg_required = (actor_realm == "platform" and resource_type in tier_b)
        bg_valid = False
        if bg_required:
            if "self_approval" in inject and isinstance(bg, dict):
                bg = dict(bg); bg["checker"] = bg.get("maker")
            if "expired_grant" in inject and isinstance(bg, dict):
                bg = dict(bg); bg["expires_state"] = "expired"
            if "standing_access" in inject and isinstance(bg, dict):
                bg = dict(bg); bg["time_boxed"] = False

            if not isinstance(bg, dict):
                deny_reason = "break_glass_required"
            else:
                break_glass_id = bg.get("grant_id")
                used_break_glass = True
                maker = bg.get("maker")
                checker = bg.get("checker")
                reason_code = bg.get("reason_code")
                tier = bg.get("tier")
                expires_state = bg.get("expires_state")
                scope_tenant = bg.get("scope_tenant")
                time_boxed = bg.get("time_boxed", True)
                self_approval = (maker is not None and maker == checker)
                expired = (expires_state != "valid")
                if self_approval or expired or (not time_boxed):
                    v["break_glass_violation"] += 1
                if (bgcfg.get("require_maker_checker", True) and self_approval):
                    deny_reason = "break_glass_invalid"
                elif (bgcfg.get("require_reason_code", True) and not reason_code):
                    deny_reason = "break_glass_invalid"
                elif tier != bgcfg.get("tier", "B"):
                    deny_reason = "break_glass_invalid"
                elif expired:
                    deny_reason = "break_glass_invalid"
                elif not time_boxed:
                    deny_reason = "break_glass_invalid"
                elif scope_tenant != tenant:
                    deny_reason = "break_glass_invalid"
                else:
                    bg_valid = True

        # ── K4 yetki kapısı (RBAC permission + sahiplik) ──
        if deny_reason is None:
            if bg_required:
                # Geçerli break-glass grant'ı platform Tier B erişimini yetkilendirir.
                authorized = bg_valid
            else:
                req_perm, own_perm = _required_permission(resource_type, access_mode, ownership, rescfg)
                if req_perm is None:
                    authorized = False
                    deny_reason = "missing_permission"
                elif req_perm in actor_permissions:
                    authorized = True
                elif own_perm and own_perm in actor_permissions:
                    # :own yetki yalnız sahiplik 'own' ise yeterli.
                    if ownership == "own":
                        authorized = True
                    else:
                        authorized = False
                        deny_reason = "insufficient_scope"
                else:
                    authorized = False
                    deny_reason = "missing_permission"

        # ── K4 degrade: yetkisizken erişim ver ──
        if "unauthorized_grant" in inject:
            authorized = True
            if deny_reason is not None or not (bg_valid if bg_required else False):
                v["unauthorized_access"] += 1
            deny_reason = None

        if authorized:
            terminal = "GRANTED"
            access_granted = True
            # ── K7 residency ──
            if "residency_leak" in inject:
                served_region = (home_region or "EU") + "-ALT"
            if in_region and served_region is not None and served_region != home_region:
                v["residency_violation"] += 1
        else:
            terminal = "DENIED"
            if deny_reason is None:
                deny_reason = "missing_permission"

        # ── failopen_audit: audit-sink yokken erişim ver (K5 fail-open) ──
        if not audit_sink and "failopen_audit" in inject:
            v["failopen"] += 1

    # ── K2/K10 ZORUNLU AUDIT — her GRANTED/DENIED (+ auditlenebilir BLOCK) WORM kaydı üretir ──
    sink_down_block = (terminal == "BLOCK" and block_reason == "no_audit_sink")
    should_audit = (terminal in AUDITED_TERMINALS) or (terminal == "BLOCK" and not sink_down_block)

    if "skip_audit" in inject or "no_audit" in inject:
        # K2/K5: audit atlandı / üretilmedi
        audit = None
        audit_written = False
        if should_audit:
            v["missing_audit"] += 1
        if access_granted:
            v["unaudited_access"] += 1            # auditlenmeden erişim verildi
    elif not audit_sink:
        # audit-sink yok → kayıt YAZILAMAZ. Doğru yolda erişim de verilmez (BLOCK no_audit_sink);
        # failopen_audit yolunda erişim verildi ama audit yok → unaudited_access (K2/K5 ihlali).
        audit = None
        audit_written = False
        if access_granted:
            v["unaudited_access"] += 1
    else:
        record = {
            "result": terminal,
            "request_id": request_id,
            "call_id": call_id,
            "tenant_id": tenant,
            "actor_user_id": actor_user_id,
            "actor_realm": actor_realm,
            "actor_role": actor_role,
            "resource_type": resource_type,
            "access_action": access_action,
            "access_mode": access_mode,
            "authorized": authorized,
            "deny_reason": deny_reason,
            "break_glass_id": break_glass_id,
            "correlation_id": correlation_id,
        }
        # ── K8 degrade: ham içerik/PII değeri audit'e sızdırılır ──
        if "pii_leak" in inject:
            record["transcript_text"] = "9055501" + "9012"   # ham-değer-benzeri (sentetik)
            v["pii_leak"] += 1
        # ── K3 WORM hash chain ──
        prev_hash = prev_chain_hash
        row_hash = _canon_hash(prev_hash, record)
        stored = dict(record)
        stored["prev_hash"] = prev_hash
        stored["row_hash"] = row_hash

        # ── K3 degrade: tahrifat (kayıt mutasyonu, hash güncellenmez) ──
        if "audit_tamper" in inject:
            stored = dict(stored)
            stored["access_action"] = "export"           # alan değişti, row_hash eski
        # ── K3 degrade: zincir kırılması (prev_hash yanlış) ──
        if "chain_break" in inject:
            stored = dict(stored)
            stored["prev_hash"] = "deadbeef" * 8

        audit = stored
        audit_written = True

        # ── K3 doğrulama: row_hash'i yeniden hesapla; tahrifat/zincir kırılması yakala ──
        rec_for_hash = {k: audit[k] for k in record}
        recomputed = _canon_hash(audit.get("prev_hash"), rec_for_hash)
        if recomputed != audit.get("row_hash"):
            v["audit_tampered"] += 1
        if prev_chain_hash is not None and audit.get("prev_hash") != prev_chain_hash:
            v["chain_break"] += 1

    # ── K2 ÇEKİRDEK GARANTİ: access_granted ⇒ audit_written ──
    if access_granted and not audit_written:
        if v["unaudited_access"] == 0:
            v["unaudited_access"] += 1

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (K9) ──
    evidence = _evidence(request_id, actor_realm, resource_type, access_action, access_mode,
                         authorized, access_granted, audit_written, break_glass_id, deny_reason,
                         block_reason, served_region, home_region, used_break_glass)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, block_reason, deny_reason, authorized, access_granted,
                 audit_written, break_glass_id, used_break_glass, served_region, home_region,
                 actor_realm, resource_type, access_action, access_mode, evidence, audit)


def _evidence(request_id, actor_realm, resource_type, access_action, access_mode, authorized,
              access_granted, audit_written, break_glass_id, deny_reason, block_reason,
              served_region, home_region, used_break_glass):
    return {
        "request_id": request_id,
        "actor_realm": actor_realm,
        "resource_type": resource_type,
        "access_action": access_action,
        "access_mode": access_mode,
        "authorized": authorized,
        "access_granted": access_granted,
        "audit_written": audit_written,
        "break_glass_id": break_glass_id,
        "used_break_glass": used_break_glass,
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "served_region": served_region,
        "home_region": home_region,
    }


def _pack(sample, terminal, v, block_reason, deny_reason, authorized, access_granted, audit_written,
          break_glass_id, used_break_glass, served_region, home_region, actor_realm, resource_type,
          access_action, access_mode, evidence, audit):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "block_reason": block_reason,
        "deny_reason": deny_reason,
        "authorized": authorized,
        "access_granted": access_granted,
        "audit_written": audit_written,
        "break_glass_id": break_glass_id,
        "used_break_glass": used_break_glass,
        "served_region": served_region,
        "home_region": home_region,
        "actor_realm": actor_realm,
        "resource_type": resource_type,
        "access_action": access_action,
        "access_mode": access_mode,
        "evidence": evidence,
        "audit": audit,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "unaudited_access": "max_unaudited_access",
        "unauthorized_access": "max_unauthorized_access",
        "audit_tampered": "max_audit_tampered",
        "chain_break": "max_chain_break",
        "break_glass_violation": "max_break_glass_violation",
        "failopen": "max_failopen",
        "residency_violation": "max_residency_violation",
        "pii_leak": "max_pii_leak",
        "cross_tenant": "max_cross_tenant",
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
    # Karar kaydı: GRANTED/DENIED + auditlenebilir BLOCK için audit zorunlu (no_audit_sink hariç).
    sink_down = (result["terminal"] == "BLOCK" and result["block_reason"] == "no_audit_sink")
    if gates.get("require_decision_record", True) and not sink_down and result["audit"] is None:
        fails.append("karar/audit kaydı üretilmedi (K2/K10)")
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
        for key in ("terminal", "block_reason", "deny_reason", "authorized", "access_granted",
                    "audit_written", "break_glass_id"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s authorized=%s granted=%s audited=%s reason=%s/%s bg=%s region=%s"
              % (res["terminal"], res["authorized"], res["access_granted"], res["audit_written"],
                 res["block_reason"], res["deny_reason"], res["break_glass_id"], res["served_region"]))
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
              "block_reasons", "deny_reasons", "outcomes", "resources", "break_glass",
              "audit_record", "authorization", "gates", "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=11.6", spec.get("wbs") == "11.6")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement worm_audit=true", spec.get("placement", {}).get("worm_audit") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-REC-009 izlenir (erişim audit — ÇEKİRDEK)", "FR-REC-009" in tr.get("fr", []))
    chk("FR-REC-008 izlenir (yetkili erişim)", "FR-REC-008" in tr.get("fr", []))
    chk("FR-IAM-006 izlenir (WORM audit + bütünlük)", "FR-IAM-006" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (L0 altın kural)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-IAM-009 izlenir (break-glass)", "FR-IAM-009" in tr.get("fr", []))
    chk("FR-IAM-010 izlenir (regüle tenant onay)", "FR-IAM-010" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-011 izlenir (RBAC bundle)", "FR-IAM-011" in tr.get("fr", []))
    chk("SR-REC-009 izlenir", "SR-REC-009" in tr.get("srs", []))
    chk("SR-REC-008 izlenir", "SR-REC-008" in tr.get("srs", []))
    chk("TC-REC-009 izlenir", "TC-REC-009" in tr.get("rtm", []))
    chk("NFR 10.7 izlenir (residency)", "NFR 10.7" in tr.get("nfr", []))
    chk("ADR-011/012/013 izlenir",
        all(any(a.startswith(x) for a in tr.get("adr", []))
            for x in ("ADR-011", "ADR-012", "ADR-013")))
    chk("SAD §14.4 RBAC/break-glass izlenir", any("§14.4" in s for s in tr.get("sad", [])))
    chk("DB §27 audit_log izlenir", any("§27" in d for d in tr.get("db", [])))
    chk("BRD §17 panel/audit izlenir", any("§17" in s for s in tr.get("brd", [])))
    chk("BRD §15 alarm izlenir", any("§15" in s for s in tr.get("brd", [])))
    chk("11.4 pii-redaction consumes (access_ready)", any("11.4" in c for c in tr.get("consumes", [])))
    chk("11.1/11.2/11.3 consumes (içerik üretim zinciri)",
        any("11.3" in c for c in tr.get("consumes", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (audit/worm/authz/mandatory/break_glass/residency/no_raw)", set(rule_ids) == set(RULES))
    chk("değerlendirme tenant_check_then_audit_sink_then_authorize_then_break_glass_then_worm_audit_then_residency_fail_closed",
        rz.get("evaluation") == "tenant_check_then_audit_sink_then_authorize_then_break_glass_then_worm_audit_then_residency_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower()
        or "access_granted=false" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar GRANTED/DENIED/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi (cross_tenant/no_audit_sink/malformed_request)", br == set(BLOCK_REASONS))
    dr = set(spec["deny_reasons"].get("list", []))
    chk("deny_reason taksonomisi tam", dr == set(DENY_REASONS))

    # 5b) resources + break_glass + audit_record
    rs = spec["resources"]
    chk("resource_types recording/transcript", set(rs.get("types", [])) == RESOURCE_TYPES)
    chk("tier_b_resources recording+transcript (Tier B içerik)",
        set(rs.get("tier_b", [])) == RESOURCE_TYPES)
    chk("access_actions listen/view/download/export", set(rs.get("actions", [])) == ACCESS_ACTIONS)
    chk("access_modes masked/raw", set(rs.get("modes", [])) == ACCESS_MODES)
    bgc = spec["break_glass"]
    chk("break_glass required_realm=platform", bgc.get("required_realm") == "platform")
    chk("break_glass tier=B", bgc.get("tier") == "B")
    chk("break_glass maker-checker zorunlu", bgc.get("require_maker_checker") is True)
    chk("break_glass time-boxed (max 240dk)", bgc.get("max_minutes") == 240)
    chk("break_glass standing access yok", bgc.get("standing_access") is False)
    ar = spec["audit_record"]
    chk("audit_record worm=true", ar.get("worm") is True)
    chk("audit_record hash_chain prev_hash/row_hash", ar.get("hash_chain") is True)
    chk("audit_record sha256", ar.get("hash_algo") == "sha256")
    chk("audit_record alanları result/actor/resource/break_glass_id",
        all(f in ar.get("fields", []) for f in ("result", "actor_user_id", "resource_type", "break_glass_id")))
    chk("audit_record ham içerik/PII YASAK",
        all(f in ar.get("forbidden_fields", []) for f in ("transcript_text", "recording_bytes")))

    # 6) Yetki — RBAC permission + L0 altın kural + backend
    az = spec["authorization"]
    chk("transcript_permission=transcript:read (FR-REC-008)",
        az.get("transcript_permission") == "transcript:read")
    chk("recording_permission=calls:read", az.get("recording_permission") == "calls:read")
    chk("raw_transcript yükseltilmiş yetki (transcript:manage)",
        az.get("raw_transcript_permission") == "transcript:manage")
    chk("L0 altın kural (platform içeriğe break-glass'sız erişemez)",
        "break-glass" in az.get("golden_rule", "").lower() or "altın kural" in az.get("golden_rule", "").lower())
    chk("karar backend'de", az.get("decision_at") == "backend")

    # 7) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_unaudited_access", "max_unauthorized_access", "max_audit_tampered", "max_chain_break",
               "max_break_glass_violation", "max_failopen", "max_residency_violation", "max_pii_leak",
               "max_cross_tenant", "max_missing_evidence", "max_missing_audit", "max_stuck_state",
               "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)
    chk("require_decision_record", g.get("require_decision_record") is True)

    # 8) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("access_audit_decision_total metrik", "access_audit_decision_total" in obs.get("metrics", []))
    chk("access_audit_break_glass_total metrik", "access_audit_break_glass_total" in obs.get("metrics", []))
    chk("access_audit_integrity_violation_total metrik (K2/K3/K4 alarm)",
        "access_audit_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/call_id/actor_user_id YÜKSEK kard (label değil)",
        "actor_user_id" in hi and "call_id" in hi and "call_id" not in lo)
    chk("result/resource_type/actor_realm DÜŞÜK kard (label uygun)",
        "result" in lo and "resource_type" in lo and "actor_realm" in lo)
    chk("alarm unaudited_access/unauthorized_access/audit_tampered ≤2dk",
        "unaudited_access" in obs.get("alarm", "") or "unauthorized_access" in obs.get("alarm", ""))

    # 9) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 10) Config dosyası
    cfg_ok = os.path.exists(CONFIG_PATH)
    chk("config/access-audit.json var", cfg_ok)
    if cfg_ok:
        cfg = _load(CONFIG_PATH)
        rp = cfg.get("resource_permission", {})
        chk("config transcript→transcript:read",
            rp.get("transcript", {}).get("base_permission") == "transcript:read")
        chk("config transcript raw→transcript:manage",
            rp.get("transcript", {}).get("raw_permission") == "transcript:manage")
        chk("config recording→calls:read",
            rp.get("recording", {}).get("base_permission") == "calls:read")
        chk("config recording/transcript tier=B",
            rp.get("recording", {}).get("tier") == "B" and rp.get("transcript", {}).get("tier") == "B")
        chk("config tier_b_resources recording+transcript",
            set(cfg.get("tier_b_resources", [])) == RESOURCE_TYPES)
        chk("config break_glass require_maker_checker",
            cfg.get("break_glass", {}).get("require_maker_checker") is True)
        chk("config break_glass max_minutes=240",
            cfg.get("break_glass", {}).get("max_minutes") == 240)
        chk("config audit worm+hash_chain",
            cfg.get("audit", {}).get("worm") is True and cfg.get("audit", {}).get("hash_chain") is True)

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
    chk("hiç ham-içerik/PII/transkript-metni/kayıt-byte/sır sızıntısı yok (K12)", total_leaks == 0)

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

    def req(**kw):
        # Varsayılan: tenant realm (qa_analyst-benzeri) transkript görüntüleme (masked) — yetkili.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1", "call_id": "call-1",
            "actor_user_id": "u-1", "actor_realm": "tenant", "actor_role": "qa_analyst",
            "resource_type": "transcript", "access_action": "view", "access_mode": "masked",
            "actor_permissions": ["transcript:read", "calls:read"], "ownership": "other",
            "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
            "audit_sink_available": True,
        }
        d.update(kw)
        return d

    def bg(**kw):
        d = {"grant_id": "bg-1", "maker": "u-a", "checker": "u-b", "reason_code": "INVEST-01",
             "tier": "B", "expires_state": "valid", "scope_tenant": "t-acme", "time_boxed": True}
        d.update(kw)
        return d

    # 1) happy — yetkili tenant transkript → GRANTED + audited
    r = build(req(), spec)
    case("happy: GRANTED", r["terminal"] == "GRANTED")
    case("happy: authorized=true", r["authorized"] is True)
    case("happy: access_granted=true", r["access_granted"] is True)
    case("happy: audit_written=true (K2)", r["audit_written"] is True)
    case("happy: audit result GRANTED (K10)", r["audit"] is not None and r["audit"]["result"] == "GRANTED")
    case("happy: audit row_hash var (K3)", r["audit"].get("row_hash") is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 1b) recording listen → calls:read → GRANTED
    r = build(req(resource_type="recording", access_action="listen"), spec)
    case("recording: GRANTED (calls:read)", r["terminal"] == "GRANTED" and r["authorized"] is True)

    # 2) determinizm + hash deterministik
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("hash deterministik: aynı row_hash", r1["audit"]["row_hash"] == r2["audit"]["row_hash"])

    # 3) DENIED — yetki yok → audited
    r = build(req(actor_permissions=[]), spec)
    case("no-perm: DENIED", r["terminal"] == "DENIED")
    case("no-perm: deny_reason=missing_permission", r["deny_reason"] == "missing_permission")
    case("no-perm: audited (DENIED de audit'lenir, FR-REC-009)", r["audit_written"] is True)
    case("no-perm: access_granted=false", r["access_granted"] is False)
    case("no-perm: kapı geçer (DENIED meşru terminal)", _gate_eval(r, G)[0] is True)

    # 3b) :own yetki + sahiplik dışı → DENIED insufficient_scope
    r = build(req(actor_permissions=["transcript:read:own"], ownership="other"), spec)
    case("own-other: DENIED insufficient_scope",
         r["terminal"] == "DENIED" and r["deny_reason"] == "insufficient_scope")
    # :own + sahiplik own → GRANTED
    r = build(req(actor_permissions=["transcript:read:own"], ownership="own"), spec)
    case("own-own: GRANTED", r["terminal"] == "GRANTED" and r["authorized"] is True)

    # 3c) raw transkript yükseltilmiş yetki ister
    r = build(req(access_mode="raw", actor_permissions=["transcript:read"]), spec)
    case("raw-no-elevated: DENIED (transcript:manage gerekir)",
         r["terminal"] == "DENIED" and r["deny_reason"] == "missing_permission")
    r = build(req(access_mode="raw", actor_permissions=["transcript:read", "transcript:manage"]), spec)
    case("raw-elevated: GRANTED", r["terminal"] == "GRANTED" and r["authorized"] is True)

    # 4) L0 platform Tier B — geçerli break-glass → GRANTED
    r = build(req(actor_realm="platform", actor_role="platform_sre", actor_permissions=[],
                  break_glass=bg()), spec)
    case("bg-valid: GRANTED", r["terminal"] == "GRANTED" and r["authorized"] is True)
    case("bg-valid: break_glass_id audit'te", r["audit"]["break_glass_id"] == "bg-1")
    case("bg-valid: used_break_glass", r["used_break_glass"] is True)
    case("bg-valid: kapı geçer", _gate_eval(r, G)[0] is True)

    # 4b) L0 break-glass yok → DENIED (altın kural)
    r = build(req(actor_realm="platform", actor_permissions=[], break_glass=None), spec)
    case("bg-missing: DENIED break_glass_required",
         r["terminal"] == "DENIED" and r["deny_reason"] == "break_glass_required")
    case("bg-missing: audited", r["audit_written"] is True)

    # 4c) self-approval → break_glass_violation + DENIED
    r = build(req(actor_realm="platform", actor_permissions=[], break_glass=bg(checker="u-a")), spec)
    case("bg-self: break_glass_violation>0", r["violations"]["break_glass_violation"] > 0)
    case("bg-self: DENIED break_glass_invalid",
         r["terminal"] == "DENIED" and r["deny_reason"] == "break_glass_invalid")
    case("bg-self: kapı ELER", _gate_eval(r, G)[0] is False)

    # 4d) expired grant → break_glass_violation
    r = build(req(actor_realm="platform", actor_permissions=[], break_glass=bg(expires_state="expired")), spec)
    case("bg-expired: break_glass_violation>0 + DENIED",
         r["violations"]["break_glass_violation"] > 0 and r["terminal"] == "DENIED")
    case("bg-expired: kapı ELER", _gate_eval(r, G)[0] is False)

    # 4e) cross-tenant scope grant → DENIED break_glass_invalid (scope mismatch, ihlal değil ama reddedilir)
    r = build(req(actor_realm="platform", actor_permissions=[], break_glass=bg(scope_tenant="t-other")), spec)
    case("bg-scope: DENIED break_glass_invalid",
         r["terminal"] == "DENIED" and r["deny_reason"] == "break_glass_invalid")

    # 5) K5 audit-sink yok → fail-closed BLOCK no_audit_sink
    r = build(req(audit_sink_available=False), spec)
    case("sink-down: BLOCK no_audit_sink", r["terminal"] == "BLOCK" and r["block_reason"] == "no_audit_sink")
    case("sink-down: access_granted=false (fail-closed)", r["access_granted"] is False)
    case("sink-down: kapı geçer (fail-closed meşru)", _gate_eval(r, G)[0] is True)

    # 5b) K5 failopen — sink yok ama erişim ver
    r = build(req(audit_sink_available=False), spec, inject=["failopen_audit"])
    case("failopen: failopen>0", r["violations"]["failopen"] > 0)
    case("failopen: unaudited_access>0 (auditsiz erişim)", r["violations"]["unaudited_access"] > 0)
    case("failopen: kapı ELER", _gate_eval(r, G)[0] is False)

    # 6) malformed → BLOCK
    r = build(req(resource_type="invalid"), spec)
    case("malformed: BLOCK malformed_request", r["terminal"] == "BLOCK" and r["block_reason"] == "malformed_request")
    case("malformed: access_granted=false", r["access_granted"] is False)

    # 7) K2/K5 skip_audit — erişim ver ama audit yok
    r = build(req(), spec, inject=["skip_audit"])
    case("skip-audit: unaudited_access>0", r["violations"]["unaudited_access"] > 0)
    case("skip-audit: missing_audit>0", r["violations"]["missing_audit"] > 0)
    case("skip-audit: audit None", r["audit"] is None)
    case("skip-audit: kapı ELER", _gate_eval(r, G)[0] is False)

    # 8) K4 unauthorized_grant — yetkisizken erişim ver
    r = build(req(actor_permissions=[]), spec, inject=["unauthorized_grant"])
    case("unauth-grant: unauthorized_access>0", r["violations"]["unauthorized_access"] > 0)
    case("unauth-grant: GRANTED (yanlış)", r["terminal"] == "GRANTED")
    case("unauth-grant: kapı ELER", _gate_eval(r, G)[0] is False)

    # 9) K3 audit_tamper — kayıt mutasyonu, hash güncellenmez
    r = build(req(), spec, inject=["audit_tamper"])
    case("tamper: audit_tampered>0", r["violations"]["audit_tampered"] > 0)
    case("tamper: kapı ELER", _gate_eval(r, G)[0] is False)

    # 10) K3 chain_break — prev_hash kırılması
    r = build(req(prev_chain_hash="a" * 64), spec, inject=["chain_break"])
    case("chain-break: chain_break>0", r["violations"]["chain_break"] > 0)
    case("chain-break: kapı ELER", _gate_eval(r, G)[0] is False)
    # sağlıklı zincir bağlama
    r = build(req(prev_chain_hash="a" * 64), spec)
    case("chain-ok: prev_hash bağlı + chain_break=0",
         r["audit"]["prev_hash"] == "a" * 64 and r["violations"]["chain_break"] == 0)

    # 11) K8 pii_leak — ham içerik audit'e sızar
    r = build(req(), spec, inject=["pii_leak"])
    case("pii-leak: pii_leak>0", r["violations"]["pii_leak"] > 0)
    case("pii-leak: kapı ELER", _gate_eval(r, G)[0] is False)

    # 12) K7 residency
    r = build(req(), spec, inject=["residency_leak"])
    case("residency-leak: residency_violation>0", r["violations"]["residency_violation"] > 0)
    case("residency-leak: kapı ELER", _gate_eval(r, G)[0] is False)
    r = build(req(served_region="TR"), spec)
    case("residency: served=home(TR) → ihlal yok", r["violations"]["residency_violation"] == 0)

    # 13) K12 cross_tenant
    r = build(req(), spec, inject=["cross_tenant"])
    case("cross-tenant: cross_tenant>0 + BLOCK", r["violations"]["cross_tenant"] > 0 and r["terminal"] == "BLOCK")
    r = build(req(bind_tenant="t-other"), spec)
    case("bind-mismatch: cross_tenant>0", r["violations"]["cross_tenant"] > 0)

    # 14) K10 no_audit
    r = build(req(), spec, inject=["no_audit"])
    case("no-audit: missing_audit>0 + audit None", r["violations"]["missing_audit"] > 0 and r["audit"] is None)

    # 15) K2 GARANTİ — access_granted ⇒ audit_written
    for kw in (dict(), dict(resource_type="recording", access_action="listen"),
               dict(actor_realm="platform", actor_permissions=[], break_glass=bg())):
        rr = build(req(**kw), spec)
        if rr["access_granted"]:
            case("K2 garanti: granted ⇒ audited (%s)" % rr["resource_type"], rr["audit_written"] is True)

    # 16) DENIED de audit üretir (FR-REC-009: erişimler — başarısız dahil — audit'lenir)
    r = build(req(actor_permissions=[]), spec)
    case("DENIED audit: result=DENIED + deny_reason kayıtlı",
         r["audit"]["result"] == "DENIED" and r["audit"]["deny_reason"] == "missing_permission")

    # 17) kanıt (K9) + audit (K10) ham PII taşımaz (K8/K11)
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: authorized/access_granted/audit_written taşır",
         all(k in r["evidence"] for k in ("authorized", "access_granted", "audit_written")))
    case("audit: ham içerik/PII alanı yok",
         all(k not in json.dumps(r["audit"]) for k in ("transcript_text", "recording_bytes", "raw_audio", "card_pan_value")))

    # 18) sızıntı tarayıcı
    case("leak: req-001 kimlik temiz", scan_leaks('{"request_id": "req-001"}') == [])
    case("leak: enum temiz", scan_leaks('{"resource_type": "transcript", "access_action": "view"}') == [])
    case("leak: hash/grant temiz", scan_leaks('{"row_hash": "sha256...", "break_glass_id": "bg-1"}') == [])
    case("leak: transcript_text alanı yakalanır", len(scan_leaks('{"transcript_text": "x"}')) > 0)
    case("leak: ham uzun rakam yakalanır", len(scan_leaks('{"x": "4111111111111111"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "access-audit (WBS 11.6 — Kayıt/transkript erişim audit'i; FR-REC-009)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "access_terminals": sorted(ACCESS_TERMINALS),
        "audited_terminals": sorted(AUDITED_TERMINALS),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "deny_reasons": DENY_REASONS,
        "resource_types": sorted(RESOURCE_TYPES),
        "access_actions": sorted(ACCESS_ACTIONS),
        "access_modes": sorted(ACCESS_MODES),
        "actor_realms": sorted(ACTOR_REALMS),
        "decision": "tenant_check ⇒ BLOCK(cross_tenant) → malformed ⇒ BLOCK(malformed_request) → "
                    "audit_sink yok ⇒ BLOCK(no_audit_sink) → L0 Tier B break-glass doğrula → yetki "
                    "(permission+sahiplik+break-glass) → WORM audit (hash chain) → residency ⇒ "
                    "GRANTED | DENIED",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ access_granted=false ∧ no access; audit-sink yok ⇒ BLOCK (auditlenemeyen erişim verilmez, K2/K5)",
        "core_guarantees": [
            "K2 zorunlu audit: access_granted ⇒ audit_written; auditsiz erişim=unaudited_access=0 (FR-REC-009)",
            "K3 WORM/hash-chain bütünlüğü: prev_hash→row_hash; audit_tampered=0, chain_break=0 (FR-IAM-006, DB §27)",
            "K4 yetki kapısı: granted ⇒ authorized (permission+sahiplik+L0 break-glass); unauthorized_access=0 (FR-REC-008)",
            "K5 atlanamaz: skip_audit=0; audit-sink yok ⇒ BLOCK (failopen=0); L0 altın kural",
            "K6 break-glass disiplini: maker≠checker+süreli+gerekçe+kapsam; break_glass_violation=0 (FR-IAM-009/010)",
            "K8 ham içerik/PII yok: audit/kanıt/metrik yalnız yapısal kimlik+enum+break_glass_id; pii_leak=0 (BRD §17.7)",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "call_id",
                           "actor_user_id", "actor_realm(tenant|platform)", "actor_role",
                           "resource_type(recording|transcript)", "access_action(listen|view|download|export)",
                           "access_mode(masked|raw)", "actor_permissions[]", "ownership(own|other)",
                           "break_glass{grant_id,maker,checker,reason_code,tier,expires_state,scope_tenant,time_boxed}",
                           "in_region_storage_required(bool)", "storage_region", "home_region", "served_region",
                           "audit_sink_available(bool)", "prev_chain_hash", "bind_tenant",
                           "config_override{}", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "block_reason", "deny_reason", "authorized", "access_granted",
                            "audit_written", "break_glass_id", "used_break_glass", "served_region",
                            "actor_realm", "resource_type", "access_action", "access_mode",
                            "evidence", "audit{result,...,prev_hash,row_hash}"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "consumes": "11.1/11.2/11.3/11.4 içerik üretim zinciri (kayıt + transkript + access_ready) + "
                    "FR-IAM-011 RBAC permission atamaları + FR-IAM-009 break-glass grant (DOĞRULANIR, üretilmez)",
        "consumed_by": "DB §27 audit_log (WORM yazımı + hash chain) + 0.4.7 gözlemlenebilirlik "
                       "(access_audit_* metrikleri) + panel L2 A-11/A-12/A-13 (dinleme/görüntüleme; karar verilir)",
        "trace": "FR-REC-009, SR-REC-009, TC-REC-009, FR-REC-008/SR-REC-008, FR-IAM-006 (WORM+bütünlük), "
                 "FR-IAM-008/009/010 (altın kural+break-glass), FR-TEN-002, FR-IAM-011, NFR 10.7, "
                 "BRD §15/§17, SAD §14.4 RBAC/break-glass, DB §27 audit_log, ADR-011/012/013",
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
            print("kullanım: access_audit_probe.py check <sample.json|dizin>")
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
