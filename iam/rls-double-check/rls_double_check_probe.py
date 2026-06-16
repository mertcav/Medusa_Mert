#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.3 — Tenant scope + RLS çift kontrol (defense in depth) referans probe.

12. workstream'in (IAM & Erişim) DB-SEVİYESİ TENANT İZOLASYON modülü ve F1-Must yeteneği. DB.md §6 (Row-Level
Security politikaları) + SAD §14.4.2 ('tenant scope ... row-level security ile çift kontrol') + FR-TEN-002'yi
sahiplenir. 12.2.1 backend guard HTTP enforce_tenant_scope'u (UYGULAMA katmanı) TÜKETİR; üzerine PostgreSQL
Row-Level Security (RLS) BAĞIMSIZ ikinci katmanı ekler. İzolasyon İKİ KATMANLI (P2 defense in depth):

    -- uygulama (12.2.1): enforce_tenant_scope(ctx, resource_tenant_of(id))   # HTTP cross-tenant reddi
    -- DB (bu modül): SET LOCAL app.tenant_id = '<uuid>';  app_rw rolü (BYPASSRLS yok); FORCE ROW LEVEL SECURITY
    CREATE POLICY tenant_isolation ON <tablo>
        USING       (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        WITH CHECK  (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

  served ⟺ app_permit ∧ rls_permit  (AND; iki BAĞIMSIZ katman → uygulama bug'ı sızıntıya DÖNÜŞMEZ)

  RlsAccessRequest ─malformed─► RLS altyapı ─► policy coverage ─► GUC fail-closed ─► tablo-policy ─► çift-kontrol
        │              │            │                │                  │                │             │
        │   ├─ request_id/realm/table_class/operation/row eksik|geçersiz ─────────────► DENY (malformed)
        │   ├─ bypass rolü (superuser/BYPASSRLS) | RLS off | FORCE off | policy yok ──► rls_protected=false [R2/R3]
        │   ├─ eff = NULLIF(app.tenant_id,''); unset/empty → eff NULL ───────────────► fail-closed (DENY)   [R4]
        │   ├─ tablo-sınıfı policy (USING/WITH CHECK + break-glass) ─────────────────► rls_permit            [R5..R8]
        │   └─ served = app_permit ∧ rls_permit; cross-tenant ∧ served ─────────────► cross_tenant_leak/write[R5/R6]

ÇEKİRDEK: (1) R5 ÇİFT KONTROL / SIZINTI YOK (FR-TEN-002, P2 defense-in-depth ÇEKİRDEK) — RLS aynı tenant_id'yi
BAĞIMSIZ zorlar (app kararını AYNALAMAZ); cross-tenant satır uygulama katmanı YANLIŞLIKLA izin verse bile RLS
DENY → servis EDİLMEZ; uygulama bug'ı tenant sızıntısına dönüşmez (cross_tenant_leak=0); (2) R2 RLS ETKİN +
FORCE + BYPASS-ETMEYEN ROL (DB.md §6.1) — ENABLE+FORCE ROW LEVEL SECURITY + app_rw (rls_disabled/force_missing/
bypass_role=0); (3) R4 GUC FAIL-CLOSED NULLIF (DB.md §6.2) — unset/empty GUC → hiçbir satır (guc_fail_open/
guc_fail_error=0); (4) R6 WITH CHECK YAZIM KORUMASI — cross-tenant yazım reddedilir (cross_tenant_write=0); (5)
R8 BREAK-GLASS TIME-BOXED (DB.md §6.4) — Tier B okuma yalnız platform+geçerli grant+süre dolmamış (standing
access yok; bg_standing_access=0); (6) R9 SET LOCAL TRANSACTION-SCOPED (DB.md §6.1) — havuz sızıntısı yok
(guc_pool_leak=0); (7) R7 PLATFORM SCOPING (FR-IAM-008/ADR-011) — L0 ⟂ tenant business PII (platform_overreach=0).
Motor DETERMİNİSTİK FAIL-CLOSED (Date.now/random YOK; model_hash sha256). Her karar terminal (R1) + kanıt +
model bütünlük manifesti (R10); metrik düşük-kardinalite + ham PII yok (R11); model/spec/sample ham içerik/PII/
credential tutmaz (R12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): HTTP enforce_tenant_scope (uygulama katmanı) → 12.2.1 (TÜKETİLİR/
app_level); rol→permission-key/rol+scope → 12.1.1/12.1.3; ayrı router/scope → 12.2.2; L0 repository bağımsızlığı
→ 12.2.4; break-glass akışı (maker-checker+bildirim) → 12.3.x; WORM/append-only DEĞİŞMEZLİK (audit_log/consent/
agent_version) → 12.1.8/DB.md §6.5; RLS migration CI → 0.4.4. KAYNAK DOĞRULUK; çelişkide DB.md §6 / SAD §14.4.2
/ FR-TEN-002 esastır.

Kullanım:
  rls_double_check_probe.py validate          Statik RLS model + spec + 12.2.1 resiprokal bağlantı → çıkış kodu
  rls_double_check_probe.py check <sample>     RLS çift-kontrol karar motoru: senaryo(lar) → kapı (R1–R12)
  rls_double_check_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  rls_double_check_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız tablo adı + tablo-sınıfı + GUC adı +
policy adı + operation/realm enum + yapısal tenant/request kimlik [slug]; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "rls-double-check-spec.json")
RLS_MODEL_PATH = os.path.join(HERE, "config", "rls-model.json")
GUARD_MODEL_PATH = os.path.join(HERE, "..", "backend-guard", "config", "guard-model.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

RLS_TERMINAL = {"PERMIT", "DENY"}
TERMINAL = RLS_TERMINAL
REALMS = {"platform", "tenant"}
TABLE_CLASSES = ["tenant_scoped", "root_tenant", "global_reference", "platform_mixed", "platform_only"]
OPERATIONS = ["select", "insert", "update", "delete"]
READ_OPS = {"select", "delete"}        # görünürlük (USING) — cross-tenant servis = leak
WRITE_OPS = {"insert", "update"}       # yazım (WITH CHECK) — cross-tenant yazım = write
RULES = ["double_control_no_leak", "rls_enabled_forced_nonbypass", "policy_coverage", "guc_fail_closed",
         "with_check_write", "platform_scoping", "break_glass_time_boxed", "set_local_pool_isolation",
         "model_integrity"]
INVARIANT_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"]

# Degrade (inject) — DOĞRU RLS çift-kontrol davranışını bozan müdahaleler.
INJECTIONS = {"rls_disable", "force_off", "bypass_role", "missing_policy", "guc_fail_open", "bare_uuid_cast",
              "pool_leak", "app_only_trust", "write_bypass", "platform_overreach", "bg_standing",
              "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "cross_tenant_leak", "cross_tenant_write", "rls_disabled", "force_missing", "bypass_role",
    "missing_policy", "guc_fail_open", "guc_fail_error", "guc_pool_leak", "platform_overreach",
    "bg_standing_access", "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (R12; 12.1.x/12.2.1 deseniyle) — ham içerik/PII/sır yasak; tablo/sınıf/GUC/policy/kimlik beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential|connection[_-]?string)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(transcript_text_value|recording_audio_value|contact_pii_value|customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|db_password_value|connection_string_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|t-|u-|corr-|bg-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|NULLIF|current_setting|app\.|tenant_isolation|break_glass)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + tablo/sınıf/GUC/policy adı + slug kimlik eler (12.2.1 deseni)."""
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
    """Model bütünlük manifesti: sha256(kanonik JSON) — deterministik (sort_keys)."""
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rls_model():
    return _load(RLS_MODEL_PATH)


def _eff_tenant(raw_guc):
    """eff = NULLIF(current_setting('app.tenant_id', true), '')::uuid — unset(None)/empty('') → None (fail-closed)."""
    if raw_guc is None or raw_guc == "":
        return None
    return raw_guc


def _is_cross_tenant(table_class, actor_realm, actor_tenant, row):
    """Satır aktörün meşru tenant'ına göre cross-tenant mı? (sızıntı tespiti — GUC/app'ten BAĞIMSIZ ground truth)."""
    if table_class == "global_reference":
        return False                                   # paylaşılan referans; tenant verisi değil
    rt = row.get("tenant_id")
    if actor_realm == "tenant":
        return rt is not None and rt != actor_tenant
    # platform realm: platform_only/platform_mixed(NULL)/root_tenant meşru; tenant_scoped business PII cross (break-glass gerek)
    if table_class == "tenant_scoped":
        return rt is not None
    return False


def _break_glass_ok(table, operation, row, session, model):
    """break_glass_read koşulu (DB.md §6.4): platform=on AND tenant_id=bg_tenant AND bg_active=on; yalnız select."""
    bg = model["break_glass"]
    if table not in bg["tables"]:
        return False
    if operation not in bg["operations"]:
        return False
    return (session.get("platform") == "on"
            and session.get("bg_active") == "on"
            and row.get("tenant_id") is not None
            and row.get("tenant_id") == session.get("bg_tenant"))


def _policy_permit(table_class, operation, eff, row, session, model, table):
    """Tablo-sınıfı RLS policy değerlendirme (USING/WITH CHECK; DB.md §6.3). PERMIT=True / DENY=False (fail-closed)."""
    rt = row.get("tenant_id")
    platform_on = (session.get("platform") == "on")
    if table_class == "global_reference":
        return operation == "select"                   # salt-okunur referans; RLS yok
    if table_class == "platform_only":
        return platform_on                             # yalnız platform realm
    if table_class == "platform_mixed":
        return (eff is not None and rt == eff) or (rt is None and platform_on)
    if table_class == "root_tenant":
        return (eff is not None and rt == eff) or platform_on
    if table_class == "tenant_scoped":
        if eff is not None and rt == eff:
            return True
        if operation == "select" and _break_glass_ok(table, operation, row, session, model):
            return True                                # break-glass koşullu okuma (Tier B)
        return False
    return False                                       # bilinmeyen sınıf → fail-closed


def build(sample, spec, inject=None, model=None):
    """Tek RLS erişim senaryosunu yürüt → RlsAccessDecision + ihlal sayaçları.

    Motor DOĞRU RLS çift-kontrol davranışını hesaplar; inject (degrade) doğru davranışı bozar ve eşleşen
    ihlal sayacını artırır (12.1.x/12.2.1 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _rls_model()

    request_id = sample.get("request_id")
    actor_realm = sample.get("actor_realm")
    actor_tenant = sample.get("actor_tenant_id")
    table = sample.get("table")
    table_class = sample.get("table_class")
    operation = sample.get("operation")
    db_role = sample.get("db_role", model["db_role"]["app"])
    session = dict(sample.get("session", {}) or {})
    row = dict(sample.get("row", {}) or {})
    app_layer = sample.get("app_layer", "ALLOW")       # 12.2.1 enforce_tenant_scope sonucu (consumed)

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    rls_permit = False
    served = False
    note = None
    guc_error = False

    bg_tables = set(model["break_glass"]["tables"])
    tenant_scoped_tables = set(model["tenant_scoped_tables"])

    # ── R10 model bütünlük manifesti (frozen RLS model) ──
    canonical_model = {
        "frozen": model.get("frozen"),
        "fail_closed": model.get("fail_closed"),
        "guc": model.get("guc"),
        "db_role": model.get("db_role"),
        "table_classes": model.get("table_classes"),
        "break_glass": model.get("break_glass"),
        "double_check": model.get("double_check"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["db_role"] = dict(tampered["db_role"])
        tampered["db_role"]["force_row_level_security"] = False        # FORCE off (izolasyon tahrifatı)
        tampered["break_glass"] = dict(tampered["break_glass"])
        tampered["break_glass"]["time_boxed"] = False                  # break-glass standing access (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or actor_realm not in REALMS or table_class not in TABLE_CLASSES
                 or operation not in OPERATIONS or not isinstance(row, dict))

    if malformed:
        terminal, note, rls_permit = "DENY", "malformed", False
    else:
        # ── R2 RLS altyapı: ENABLE + FORCE + bypass-etmeyen rol ──
        rls_enforced = True
        force_rls = True
        policy_present = True
        if "rls_disable" in inject:
            rls_enforced = False
            v["rls_disabled"] += 1
        if "force_off" in inject:
            force_rls = False
            v["force_missing"] += 1
        if "bypass_role" in inject:
            db_role = "superuser"
            v["bypass_role"] += 1
        role_bypasses = db_role in ("superuser", "bypassrls")

        # ── R3 policy coverage: tenant-scoped iş verisi tablosu tenant_isolation policy taşımalı ──
        if "missing_policy" in inject and table_class in ("tenant_scoped", "root_tenant", "platform_mixed"):
            policy_present = False
            v["missing_policy"] += 1

        rls_protected = not (role_bypasses or not rls_enforced or not force_rls or not policy_present)

        # ── R9 SET LOCAL pool izolasyonu ──
        guc_scope = session.get("guc_scope", model["guc"]["scope"])
        if "pool_leak" in inject:
            guc_scope = "SET"
        if guc_scope != "SET LOCAL":
            v["guc_pool_leak"] += 1

        # ── R4 GUC fail-closed NULLIF ──
        raw_guc = session.get("tenant_guc")
        eff = _eff_tenant(raw_guc)
        guc_open = False
        if "bare_uuid_cast" in inject and (raw_guc is None or raw_guc == ""):
            v["guc_fail_error"] += 1                                   # ''::uuid HATA (NULLIF atlandı) — fail-error
            guc_error = True
        if "guc_fail_open" in inject and eff is None:
            v["guc_fail_open"] += 1
            guc_open = True                                            # unset GUC her satırı eşler (fail-open)

        # ── RLS permit hesapla ──
        if not rls_protected:
            rls_permit = True                                          # RLS korumuyor → her satır geçer (BAD)
        elif guc_open:
            rls_permit = True                                          # fail-open (degrade)
        else:
            rls_permit = _policy_permit(table_class, operation, eff, row, session, model, table)

        # ── R7 platform overreach (degrade): platform realm break-glass'sız tenant PII okur ──
        if "platform_overreach" in inject and actor_realm == "platform" and table_class == "tenant_scoped":
            if not rls_permit:
                v["platform_overreach"] += 1
                rls_permit = True                                      # L0 ⟂ tenant ihlali

        # ── R8 break-glass standing (degrade): grant'siz/süre-dolmuş break-glass servis ──
        if "bg_standing" in inject and table in bg_tables and operation == "select":
            if session.get("bg_active") != "on" and not rls_permit:
                v["bg_standing_access"] += 1
                rls_permit = True                                      # time-box atlandı (standing access)

        # ── R6 write bypass (degrade): WITH CHECK atlanır, cross-tenant yazım geçer ──
        if "write_bypass" in inject and operation in WRITE_OPS and not rls_permit:
            rls_permit = True

        # ── R5 app_only_trust (degrade): RLS bağımsız değil, app kararını aynalar (çift kontrol çöker) ──
        if "app_only_trust" in inject:
            rls_permit = (app_layer == "ALLOW")                       # RLS app'i aynalar → bağımsızlık yok

        terminal = "PERMIT" if (rls_permit and not guc_error) else "DENY"

        # ── ÇİFT KONTROL birleşim: served ⟺ app_permit ∧ rls_permit (R5 defense in depth) ──
        app_permit = (app_layer == "ALLOW")
        served = app_permit and (terminal == "PERMIT")

        cross = _is_cross_tenant(table_class, actor_realm, actor_tenant, row)
        legit_bg = _break_glass_ok(table, operation, row, session, model)

        # R5: cross-tenant READ servis edildi → sızıntı (break-glass meşruysa hariç)
        if served and cross and operation in READ_OPS and not legit_bg:
            v["cross_tenant_leak"] += 1
        # bg_standing select cross-tenant servis (break-glass tablosu) → leak (R5) + bg_standing_access (R8)
        if served and cross and operation == "select" and table in bg_tables and not legit_bg \
                and ("bg_standing" in inject or "platform_overreach" in inject):
            v["cross_tenant_leak"] += 1 if v["cross_tenant_leak"] == 0 else 0
        # R6: cross-tenant WRITE WITH CHECK'i geçti → cross-tenant yazım
        if served and cross and operation in WRITE_OPS:
            v["cross_tenant_write"] += 1

    # ── R1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (R1) ──
    evidence = _evidence(request_id, actor_realm, actor_tenant, table, table_class, operation, db_role,
                         session, row, app_layer, terminal, served, rls_permit, note, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, served, rls_permit, v, note, table, table_class, operation, db_role,
                 actor_realm, actor_tenant, row, app_layer, model_hash, evidence)


def _evidence(request_id, actor_realm, actor_tenant, table, table_class, operation, db_role, session, row,
              app_layer, terminal, served, rls_permit, note, model_hash):
    return {
        "request_id": request_id,
        "actor_realm": actor_realm,
        "actor_tenant_id": actor_tenant,
        "table": table,
        "table_class": table_class,
        "operation": operation,
        "db_role": db_role,
        "session_guc": {"tenant_guc": session.get("tenant_guc"), "platform": session.get("platform"),
                        "bg_active": session.get("bg_active"), "guc_scope": session.get("guc_scope")},
        "row_tenant_id": row.get("tenant_id"),
        "app_layer": app_layer,
        "rls_terminal": terminal,
        "rls_permit": rls_permit,
        "served": served,
        "note": note,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, served, rls_permit, v, note, table, table_class, operation, db_role,
          actor_realm, actor_tenant, row, app_layer, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "rls_permit": rls_permit,
        "served": served,
        "note": note,
        "table": table,
        "table_class": table_class,
        "operation": operation,
        "db_role": db_role,
        "actor_realm": actor_realm,
        "actor_tenant_id": actor_tenant,
        "row_tenant_id": row.get("tenant_id"),
        "app_layer": app_layer,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "cross_tenant_leak": "max_cross_tenant_leak",
        "cross_tenant_write": "max_cross_tenant_write",
        "rls_disabled": "max_rls_disabled",
        "force_missing": "max_force_missing",
        "bypass_role": "max_bypass_role",
        "missing_policy": "max_missing_policy",
        "guc_fail_open": "max_guc_fail_open",
        "guc_fail_error": "max_guc_fail_error",
        "guc_pool_leak": "max_guc_pool_leak",
        "platform_overreach": "max_platform_overreach",
        "bg_standing_access": "max_bg_standing_access",
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
        for key in ("terminal", "served", "rls_permit", "note"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s served=%s rls_permit=%s class=%s op=%s realm=%s app=%s note=%s"
              % (res["terminal"], res["served"], res["rls_permit"], res["table_class"], res["operation"],
                 res["actor_realm"], res["app_layer"], res["note"]))
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
    chk("wbs=12.2.3", spec.get("wbs") == "12.2.3")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement decision_at=database", "database" in spec.get("placement", {}).get("decision_at", ""))

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-TEN-002 izlenir (tenant izolasyonu — ÇEKİRDEK)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (L0 ⟂ tenant)", "FR-IAM-008" in tr.get("fr", []))
    chk("SAD §14.4.2 RLS çift kontrol izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("DB.md §6 TÜKETİLİR (consumes)", any("DB.md §6" in s for s in tr.get("consumes", [])))
    chk("ADR-011 izlenir (L0 ⟂ tenant iş verisi)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("ADR-006 izlenir (PostgreSQL RLS)", any(a.startswith("ADR-006") for a in tr.get("adr", [])))
    chk("12.2.1 backend-guard TÜKETİLİR (app_level — resiprokal)",
        any("12.2.1" in s for s in tr.get("consumes", [])))

    # 3) Dokuz kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("dokuz kural tam", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→altyapı→policy→guc→tablo→çift-kontrol",
        rz.get("evaluation") == "malformed_then_rls_infra_then_policy_coverage_then_guc_failclosed_then_table_policy_then_double_control_and")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=DENY (fail-closed)", dec.get("default") == "DENY")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar
    oc = spec["outcomes"]
    chk("terminal sonuçlar PERMIT/DENY", set(oc.get("list", [])) == RLS_TERMINAL)

    # 6) Enforcement — iki katman + birleşim
    en = spec["enforcement"]
    chk("rls_layer SET LOCAL + FORCE + tenant_isolation + app_rw",
        all(x in en.get("rls_layer", "") for x in ("SET LOCAL", "FORCE", "tenant_isolation", "app_rw")))
    chk("app_layer 12.2.1 enforce_tenant_scope (consumed)",
        "12.2.1" in en.get("app_layer", "") and "enforce_tenant_scope" in en.get("app_layer", ""))
    chk("combine served ⟺ app_permit ∧ rls_permit",
        "app_permit" in en.get("combine", "") and "rls_permit" in en.get("combine", ""))
    chk("break_glass time-boxed (standing access yok)",
        "time-boxed" in en.get("break_glass", "") or "standing access yok" in en.get("break_glass", ""))
    chk("decision_at database", en.get("decision_at") == "database")

    # 7) Model alanları
    md = spec["model"]
    chk("table_classes tam (5)", set(md.get("table_classes", [])) == set(TABLE_CLASSES))
    chk("operations tam (4)", set(md.get("operations", [])) == set(OPERATIONS))
    chk("fail_closed_expr NULLIF", "NULLIF" in md.get("fail_closed_expr", ""))
    chk("double_check app_level 12.2.1 + rls_level bu modül",
        "12.2.1" in md.get("double_check", "") and "rls_permit" in md.get("double_check", ""))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_cross_tenant_leak", "max_cross_tenant_write", "max_rls_disabled", "max_force_missing",
               "max_bypass_role", "max_missing_policy", "max_guc_fail_open", "max_guc_fail_error",
               "max_guc_pool_leak", "max_platform_overreach", "max_bg_standing_access", "max_model_tampered",
               "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("rls_decision_total metrik", "rls_decision_total" in obs.get("metrics", []))
    chk("rls_leak_violation_total metrik (alarm)", "rls_leak_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("row_tenant_id YÜKSEK kard (label değil)", "row_tenant_id" in hi and "row_tenant_id" not in lo)
    chk("table_class/operation/result/actor_realm DÜŞÜK kard",
        all(x in lo for x in ("table_class", "operation", "result", "actor_realm")))
    chk("alarm cross_tenant_leak/bypass ≤2dk",
        any(x in obs.get("alarm", "") for x in ("cross_tenant_leak", "bypass_role", "platform_overreach")))

    # 10) İnvariant'lar R1–R12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar R1–R12 tam", inv_ids == INVARIANT_IDS)

    # 11) RLS modeli dosyası + içsel tutarlılık (DB.md §6)
    rm_ok = os.path.exists(RLS_MODEL_PATH)
    chk("config/rls-model.json var", rm_ok)
    if rm_ok:
        rm = _rls_model()
        chk("rls model frozen=true", rm.get("frozen") is True)
        chk("rls model fail_closed=true", rm.get("fail_closed") is True)
        chk("rls model guc fail_closed_expr NULLIF (DB.md §6.2)", "NULLIF" in rm.get("guc", {}).get("fail_closed_expr", ""))
        chk("rls model guc scope SET LOCAL (DB.md §6.1)", rm.get("guc", {}).get("scope") == "SET LOCAL")
        chk("rls model db_role app_rw + BYPASSRLS=false (DB.md §6.1)",
            rm.get("db_role", {}).get("app") == "app_rw" and rm.get("db_role", {}).get("bypassrls") is False)
        chk("rls model FORCE ROW LEVEL SECURITY=true", rm.get("db_role", {}).get("force_row_level_security") is True)
        cls_keys = {k for k in rm.get("table_classes", {}).keys() if not k.startswith("$")}
        chk("rls model 5 tablo sınıfı (DB.md §6.3)", cls_keys == set(TABLE_CLASSES))
        tst = rm.get("tenant_scoped_tables", [])
        chk("rls model ≥28 tenant-scoped tablo (BRD §16 / DB.md §6.3)",
            len(tst) >= 28 and all(t in tst for t in ("transcript", "call", "contact", "user_role_assignment")))
        chk("rls model break_glass time_boxed + standing_access=false (DB.md §6.4)",
            rm.get("break_glass", {}).get("time_boxed") is True
            and rm.get("break_glass", {}).get("standing_access") is False)
        chk("rls model break_glass yalnız select (Tier B okuma)", rm.get("break_glass", {}).get("operations") == ["select"])
        chk("rls model double_check combine app ∧ rls",
            "app_permit" in rm.get("double_check", {}).get("combine", "")
            and "rls_permit" in rm.get("double_check", {}).get("combine", ""))
        chk("rls model double_check app_level = 12.2.1",
            "12.2.1" in rm.get("double_check", {}).get("app_level", ""))

    # 12) 12.2.1 RESİPROKAL bağlantı — guard-model rls_level → 12.2.3 (çift kontrol mutabakatı)
    gm_ok = os.path.exists(GUARD_MODEL_PATH)
    chk("12.2.1 ../backend-guard/config/guard-model.json var (TÜKETİLİR)", gm_ok)
    if gm_ok:
        gm = _load(GUARD_MODEL_PATH)
        tdc = gm.get("tenant_double_check", {})
        chk("12.2.1 tenant_double_check.guard_level=true (app_level)", tdc.get("guard_level") is True)
        chk("12.2.1 tenant_double_check.rls_level → 12.2.3 (resiprokal)",
            "12.2.3" in tdc.get("rls_level", ""))

    # 13) Sır/PII tarayıcı — spec + model + samples
    scan_files = [SPEC_PATH, RLS_MODEL_PATH] + (
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

    # 14) Samples — ≥1 pass + ≥1 fail
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
        # Varsayılan: tenant realm, tenant_scoped call tablosu, select, GUC=t-acme, satır t-acme, app ALLOW → PERMIT served.
        d = {
            "request_id": "req-1", "actor_realm": "tenant", "actor_tenant_id": "t-acme",
            "table": "call", "table_class": "tenant_scoped", "operation": "select", "db_role": "app_rw",
            "session": {"tenant_guc": "t-acme", "platform": "off", "guc_scope": "SET LOCAL"},
            "row": {"tenant_id": "t-acme"},
            "app_layer": "ALLOW",
        }
        d.update(kw)
        return d

    # 1) happy — aynı tenant → PERMIT + served
    r = build(req(), spec)
    case("happy: PERMIT", r["terminal"] == "PERMIT")
    case("happy: served=true (app ∧ rls)", r["served"] is True)
    case("happy: model_hash var (R10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) RLS bağımsız DENY (aynı tenant değil) — app BLOCK ⇒ DENY served=false, ihlal yok (meşru)
    r = build(req(row={"tenant_id": "t-other"}, app_layer="BLOCK"), spec)
    case("rls-deny: cross satır rls DENY", r["terminal"] == "DENY" and r["rls_permit"] is False)
    case("rls-deny: served=false + ihlal yok (meşru)", r["served"] is False and all(x == 0 for x in r["violations"].values()))

    # 4) R5 ÇEKİRDEK — UYGULAMA BUG'I (app ALLOW cross) ama RLS bağımsız DENY → SIZINTI YOK (defense in depth)
    r = build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec)
    case("defense-in-depth: app bug ALLOW cross ama RLS DENY → served=false", r["served"] is False and r["terminal"] == "DENY")
    case("defense-in-depth: cross_tenant_leak=0 (RLS kurtardı)", r["violations"]["cross_tenant_leak"] == 0 and _gate_eval(r, G)[0] is True)

    # 5) R4 GUC fail-closed — unset GUC → eff NULL → DENY (fail-closed)
    r = build(req(session={"tenant_guc": None, "platform": "off", "guc_scope": "SET LOCAL"}), spec)
    case("guc-unset: DENY (fail-closed)", r["terminal"] == "DENY" and r["rls_permit"] is False)
    r = build(req(session={"tenant_guc": "", "platform": "off", "guc_scope": "SET LOCAL"}), spec)
    case("guc-empty(pool-reset): DENY (NULLIF fail-closed)", r["terminal"] == "DENY")

    # 6) R6 WITH CHECK — cross-tenant insert reddedilir (aynı tenant değil) → DENY (yazım koruması doğru)
    r = build(req(operation="insert", row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec)
    case("with-check: cross insert DENY (reddedilir)", r["terminal"] == "DENY" and r["served"] is False)
    case("with-check: cross_tenant_write=0 (koruma çalıştı)", r["violations"]["cross_tenant_write"] == 0)
    # aynı tenant insert → PERMIT
    r = build(req(operation="insert", row={"tenant_id": "t-acme"}), spec)
    case("with-check: same-tenant insert PERMIT", r["terminal"] == "PERMIT" and r["served"] is True)

    # 7) global_reference → select PERMIT (RLS yok)
    r = build(req(table="role", table_class="global_reference", row={}), spec)
    case("global-ref: select PERMIT (RLS yok)", r["terminal"] == "PERMIT")

    # 8) platform_mixed (audit) — platform realm tenant_id NULL satır PERMIT
    r = build(req(actor_realm="platform", actor_tenant_id=None, table="audit_log", table_class="platform_mixed",
                  session={"tenant_guc": None, "platform": "on", "guc_scope": "SET LOCAL"},
                  row={"tenant_id": None}), spec)
    case("platform-mixed: platform NULL-tenant satır PERMIT", r["terminal"] == "PERMIT")
    case("platform-mixed: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # 9) platform_only (break_glass_grant) — platform PERMIT
    r = build(req(actor_realm="platform", actor_tenant_id=None, table="break_glass_grant",
                  table_class="platform_only",
                  session={"tenant_guc": None, "platform": "on", "guc_scope": "SET LOCAL"},
                  row={"tenant_id": "t-acme"}), spec)
    case("platform-only: platform PERMIT", r["terminal"] == "PERMIT")

    # 10) R7 — platform realm tenant_scoped PII (transcript) break-glass'sız → DENY (L0 ⟂ tenant)
    r = build(req(actor_realm="platform", actor_tenant_id=None, table="transcript", table_class="tenant_scoped",
                  session={"tenant_guc": None, "platform": "on", "guc_scope": "SET LOCAL"},
                  row={"tenant_id": "t-acme"}, app_layer="ALLOW"), spec)
    case("platform-no-bg: transcript DENY (L0 ⟂ tenant)", r["terminal"] == "DENY" and r["served"] is False)
    case("platform-no-bg: leak=0 + overreach=0", r["violations"]["cross_tenant_leak"] == 0 and r["violations"]["platform_overreach"] == 0)

    # 11) R8 — break-glass GEÇERLİ grant (bg_active=on, bg_tenant eşleşir) → transcript PERMIT (meşru)
    r = build(req(actor_realm="platform", actor_tenant_id=None, table="transcript", table_class="tenant_scoped",
                  session={"tenant_guc": None, "platform": "on", "bg_tenant": "t-acme", "bg_active": "on",
                           "guc_scope": "SET LOCAL"},
                  row={"tenant_id": "t-acme"}, app_layer="ALLOW"), spec)
    case("break-glass-valid: transcript PERMIT (Tier B meşru)", r["terminal"] == "PERMIT" and r["served"] is True)
    case("break-glass-valid: leak=0 + bg_standing=0 (grant geçerli)",
         r["violations"]["cross_tenant_leak"] == 0 and r["violations"]["bg_standing_access"] == 0)

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 12) rls_disable — cross satır servis edilir → leak
    r = build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["rls_disable"])
    case("rls-disable: rls_disabled>0 + leak>0 + kapı eler",
         r["violations"]["rls_disabled"] > 0 and r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) force_off
    r = build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["force_off"])
    case("force-off: force_missing>0 + leak>0 + kapı eler",
         r["violations"]["force_missing"] > 0 and r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 14) bypass_role (superuser/BYPASSRLS)
    r = build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["bypass_role"])
    case("bypass-role: bypass_role>0 + leak>0 + kapı eler",
         r["violations"]["bypass_role"] > 0 and r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 15) missing_policy
    r = build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["missing_policy"])
    case("missing-policy: missing_policy>0 + leak>0 + kapı eler",
         r["violations"]["missing_policy"] > 0 and r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 16) guc_fail_open — unset GUC her satırı eşler → cross satır leak
    r = build(req(session={"tenant_guc": None, "platform": "off", "guc_scope": "SET LOCAL"},
                  row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["guc_fail_open"])
    case("guc-fail-open: guc_fail_open>0 + leak>0 + kapı eler",
         r["violations"]["guc_fail_open"] > 0 and r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) bare_uuid_cast — NULLIF atlanır, ''::uuid → fail-error
    r = build(req(session={"tenant_guc": "", "platform": "off", "guc_scope": "SET LOCAL"}), spec, inject=["bare_uuid_cast"])
    case("bare-cast: guc_fail_error>0 + kapı eler",
         r["violations"]["guc_fail_error"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) pool_leak — SET (LOCAL'sız)
    r = build(req(), spec, inject=["pool_leak"])
    case("pool-leak: guc_pool_leak>0 + kapı eler",
         r["violations"]["guc_pool_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 19) app_only_trust — RLS bağımsız değil, app'i aynalar → app bug cross → leak (defense-in-depth çöker)
    r = build(req(row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["app_only_trust"])
    case("app-only-trust: cross_tenant_leak>0 (çift kontrol çöktü) + kapı eler",
         r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) write_bypass — WITH CHECK atlanır, cross insert geçer → cross_tenant_write
    r = build(req(operation="insert", row={"tenant_id": "t-other"}, app_layer="ALLOW"), spec, inject=["write_bypass"])
    case("write-bypass: cross_tenant_write>0 + kapı eler",
         r["violations"]["cross_tenant_write"] > 0 and _gate_eval(r, G)[0] is False)

    # 21) platform_overreach — L0 break-glass'sız tenant PII okur
    r = build(req(actor_realm="platform", actor_tenant_id=None, table="transcript", table_class="tenant_scoped",
                  session={"tenant_guc": None, "platform": "on", "guc_scope": "SET LOCAL"},
                  row={"tenant_id": "t-acme"}, app_layer="ALLOW"), spec, inject=["platform_overreach"])
    case("platform-overreach: platform_overreach>0 + leak>0 + kapı eler",
         r["violations"]["platform_overreach"] > 0 and r["violations"]["cross_tenant_leak"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) bg_standing — break-glass grant'siz/süre-dolmuş servis edilir
    r = build(req(actor_realm="platform", actor_tenant_id=None, table="transcript", table_class="tenant_scoped",
                  session={"tenant_guc": None, "platform": "on", "bg_tenant": "t-acme", "bg_active": "off",
                           "guc_scope": "SET LOCAL"},
                  row={"tenant_id": "t-acme"}, app_layer="ALLOW"), spec, inject=["bg_standing"])
    case("bg-standing: bg_standing_access>0 + kapı eler",
         r["violations"]["bg_standing_access"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler",
         r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 24) malformed → DENY
    case("malformed-noclass: DENY", build(req(table_class="bogus"), spec)["note"] == "malformed")
    case("malformed-noreq: DENY", build(req(request_id=None), spec)["note"] == "malformed")
    case("malformed-noop: DENY", build(req(operation="bogus"), spec)["note"] == "malformed")

    # 25) evidence + leak
    r = build(req(), spec)
    case("evidence: request+class+op+row+app+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "table_class", "operation", "row_tenant_id", "app_layer", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("transcript_text_value", "recording_audio_value", "contact_pii_value")))
    case("leak: tablo+sınıf+GUC+policy temiz",
         scan_leaks('{"table":"transcript","table_class":"tenant_scoped","guc":"app.tenant_id","policy":"tenant_isolation"}') == [])
    case("leak: transcript_text_value alanı yakalanır", len(scan_leaks('{"transcript_text_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "rls-double-check (WBS 12.2.3 — tenant scope + RLS çift kontrol; defense in depth; DB.md §6, SAD §14.4.2)",
        "outcomes": sorted(RLS_TERMINAL),
        "terminal": sorted(TERMINAL),
        "rules": RULES,
        "table_classes": TABLE_CLASSES,
        "operations": OPERATIONS,
        "realms": sorted(REALMS),
        "decision": "malformed ⇒ DENY(malformed) → bypass_role/rls_disabled/force_missing/missing_policy ⇒ "
                    "rls_protected=false → eff=NULLIF(app.tenant_id,''); unset/empty ⇒ eff=NULL (fail-closed) → "
                    "tablo-sınıfı policy (USING/WITH CHECK + break_glass_read) ⇒ rls_permit → "
                    "served=app_permit ∧ rls_permit → cross-tenant ∧ served ⇒ cross_tenant_leak (read) / cross_tenant_write (insert/update)",
        "default": "DENY (fail-closed)",
        "fail_safe": "terminal=DENY ⇒ rls_permit=false; malformed/unset-GUC/policy-yok/cross-tenant ⇒ no access; served ⟺ PERMIT ∧ app_permit",
        "core_guarantees": [
            "R5 çift kontrol/sızıntı yok: RLS BAĞIMSIZ zorlar; cross-tenant satır app izin verse bile RLS DENY → uygulama bug'ı sızıntıya dönüşmez; cross_tenant_leak=0 (FR-TEN-002, P2)",
            "R2 RLS etkin+FORCE+bypass-etmeyen rol: ENABLE+FORCE ROW LEVEL SECURITY + app_rw; rls_disabled/force_missing/bypass_role=0 (DB.md §6.1)",
            "R4 GUC fail-closed NULLIF: unset/empty GUC → hiçbir satır; guc_fail_open/guc_fail_error=0 (DB.md §6.2)",
            "R6 WITH CHECK yazım koruması: cross-tenant insert/update reddedilir; cross_tenant_write=0 (DB.md §6.2)",
            "R8 break-glass time-boxed: Tier B okuma yalnız platform+geçerli grant+süre dolmamış; bg_standing_access=0 (DB.md §6.4)",
            "R9 SET LOCAL transaction-scoped: havuz sızıntısı yok; guc_pool_leak=0 (DB.md §6.1)",
            "R7 platform scoping: L0 ⟂ tenant business PII (break-glass hariç); platform_overreach=0 (FR-IAM-008/ADR-011)",
        ],
        "request_fields": ["name", "request_id", "actor_realm(platform|tenant)", "actor_tenant_id(doğrulanmış)",
                           "table", "table_class(tenant_scoped|root_tenant|global_reference|platform_mixed|platform_only)",
                           "operation(select|insert|update|delete)", "db_role(app_rw)",
                           "session{tenant_guc, platform(on|off), bg_tenant, bg_active(on|off), guc_scope(SET LOCAL)}",
                           "row{tenant_id}", "app_layer(ALLOW|BLOCK — 12.2.1 enforce_tenant_scope sonucu)",
                           "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal(PERMIT|DENY)", "served(app ∧ rls)", "rls_permit", "note", "table",
                            "table_class", "operation", "db_role", "actor_realm", "actor_tenant_id",
                            "row_tenant_id", "app_layer", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/rls-model.json (frozen — table_classes + guc[NULLIF fail-closed; SET LOCAL] + db_role"
                 "[app_rw; FORCE; BYPASSRLS=false] + tenant_scoped_tables[28] + break_glass[time-boxed] + double_check)",
        "consumes": "12.2.1 backend-guard guard-model.json (tenant_double_check.rls_level=delegated_to_12.2.3 — "
                    "RESİPROKAL; HTTP enforce_tenant_scope app_level); DB.md §6 RLS politikaları (kaynak doğruluk)",
        "consumed_by": "12.2.4 L0 repository bağımsızlığı; 12.3.x break-glass (break_glass_read policy); "
                       "1.2.1 RLS migration; 0.4.4 RLS CI; 0.4.7 gözlemlenebilirlik (rls_* metrikleri)",
        "trace": "FR-TEN-002, FR-IAM-008, SAD §14.4.2, DB.md §6, ADR-011, ADR-006",
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
            print("kullanım: rls_double_check_probe.py check <sample.json|dizin>")
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
