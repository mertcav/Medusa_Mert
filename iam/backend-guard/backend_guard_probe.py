#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.1 — Backend guard: panel + rol + tenant scope (FastAPI dependency) referans probe.

12. workstream'in (IAM & Erişim) HTTP ENFORCEMENT modülü ve F1-Must yeteneği. SAD §14.4.2 ('Her endpoint üç
boyutta korunur: panel + rol + tenant scope. FastAPI dependency'leri (guard) ile uygulanır') + ADR-011 (iki
düzlemli panel dağıtımı: L0 ⟂ tenant) + ADR-012 (sabit rol bundle + scoped assignment)'ı sahiplenir. Kararı
12.1.1 (rol→IMMUTABLE bundle) + 12.1.3 (rol+scope) modüllerinden TÜKETİR; üzerine HTTP guard'ın ÜÇ BOYUTUNU
ekler: panel (L0/L1/L2 realm + OAuth scope + rol-katman kapsama) + delegasyon (rol+scope → 12.1.3) + tenant
scope (HTTP enforce_tenant_scope + RLS çift kontrol). Conceptual sözleşme (SAD §14.4.2):

    @router.get("/calls/{id}", dependencies=[Depends(require(perm="calls:read", panel="L2"))])
    async def get_call(id, ctx: AuthCtx = Depends(auth_ctx)):
        enforce_tenant_scope(ctx, resource_tenant_of(id))   # cross-tenant erişim reddi

  HttpGuardRequest ─malformed─► authn ─► PANEL gate ─► TENANT scope gate ─► [DELEGE 12.1.3 rol+scope] ─► karar
        │              │           │          │                 │                      │
        │   ├─ endpoint/panel/required eksik|biçimsiz | atama yok | resource yok ────► BLOCK (malformed_request)
        │   ├─ doğrulanmış kimlik yok ──────────────────────────────────────────────► BLOCK (unauthenticated) 401
        │   ├─ token realm ≠ panel realm (L0↔tenant) ───────────────────────────────► BLOCK (panel_realm_mismatch) [S2]
        │   ├─ token OAuth scope ≠ panel scope ─────────────────────────────────────► BLOCK (oauth_scope_mismatch) [S2]
        │   ├─ hiçbir atama rol katmanı paneli kapsamaz ────────────────────────────► BLOCK (panel_not_covered)   [S2]
        │   ├─ resource.tenant_id ≠ session tenant (tenant paneli) ─────────────────► BLOCK (cross_tenant_resource)[S5]
        │   ├─ DELEGE 12.1.3 = GRANT ──────────────────────────────────────────────► ALLOW (handler çalışır)     [S4]
        │   ├─ DELEGE 12.1.3 = DENY  ──────────────────────────────────────────────► DENY (403)                  [S4]
        │   └─ DELEGE 12.1.3 = BLOCK ──────────────────────────────────────────────► BLOCK (unknown_role/realm)  [S4]

ÇEKİRDEK: (1) S2 PANEL İZOLASYONU (FR-IAM-008/ADR-011 ÇEKİRDEK) — endpoint paneli (L0/L1/L2) için aktör token'ı
o panelin realm'i (platform↔tenant) + OAuth scope'u ile gelmeli VE ≥1 atama rol katmanı paneli kapsamalı; L0
endpoint'i tenant token'ıyla (veya tersi) AÇILAMAZ (panel_violation/realm_violation/scope_violation=0); (2) S4
DELEGE DOĞRULUĞU (SAD §14.4.2 ÇEKİRDEK) — HTTP ALLOW ⟺ 12.1.3 scoped-assignment GRANT; guard ASLA fail-open
yapmaz (fail_open_grant=0); DENY/BLOCK olduğu gibi HTTP'ye taşınır; (3) S5 TENANT SCOPE (FR-TEN-002, BRD §17.7)
— tenant panellerinde session tek tenant_id'ye bağlı; resource.tenant_id ≠ session tenant → BLOCK (HTTP
enforce_tenant_scope + RLS çift kontrol 12.2.3); cross-tenant erişim YOK (cross_tenant=0); (4) S6 BACKEND
OTORİTESİ (SAD §14.4.2 ÇEKİRDEK) — yetki kararı YALNIZ doğrulanmış token'dan; client-supplied rol/permission
iddiası ASLA güvenilmez (client_trust_violation=0); UI yalnız görsel kapı; (5) S3 DEKLARASYON ZORUNLU (API.md
x-required-permission) — korumalı endpoint geçerli bir required permission-key deklare etmeli; eksikse
fail-closed (undeclared_endpoint=0). Motor DETERMİNİSTİK FAIL-CLOSED karar fonksiyonu (Date.now/random YOK;
model_hash sha256). Her karar terminal (S1) + kanıt (S9) + model bütünlük manifesti (S10); metrik düşük-
kardinalite + ham PII yok (S11); model/spec/sample ham içerik/PII/credential tutmaz (S12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle çözümü (immutable) → 12.1.1 (TÜKETİLİR);
rol+scope yetki kararı (department/brand/campaign narrowing) → 12.1.3 (DELEGE EDİLİR); permission-key gramer/
katalog → 12.1.2; ayrı router ağaçları + ayrı deploy detayı → 12.2.2 (bu modül panel boyutunu zorlar, router
topolojisi orada); PostgreSQL RLS politikaları (DB seviyesi çift kontrol) → 12.2.3 (bu modül HTTP enforce_tenant_
scope'u zorlar, RLS DELEGE); L0 iş verisi repository bağımsızlığı → 12.2.4; break-glass (Tier B kapsam-üstü) →
12.3.x; WORM audit → 12.1.8 (karar kaydı). KAYNAK DOĞRULUK; çelişkide SAD §14.4.2 / ADR-011 / ADR-012 esastır.

Kullanım:
  backend_guard_probe.py validate          Statik guard/rbac model + spec + 12.1.3 delege erişimi → çıkış kodu
  backend_guard_probe.py check <sample>     HTTP guard karar motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  backend_guard_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  backend_guard_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız rol adı + permission-key + panel/realm/
scope enum + kapsam boyut ID + yapısal kimlik; FR-TST-008).
"""
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "backend-guard-spec.json")
GUARD_MODEL_PATH = os.path.join(HERE, "config", "guard-model.json")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
SCOPED_PROBE_PATH = os.path.join(HERE, "..", "scoped-assignment", "scoped_assignment_probe.py")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ALLOW", "DENY", "BLOCK"]
TERMINAL = {"ALLOW", "DENY", "BLOCK"}
GRANT_TERMINALS = {"ALLOW"}
RULES = ["panel_isolation", "declaration_required", "delegated_authorization", "tenant_scope",
         "backend_authority", "fail_closed_default", "model_integrity"]
DENY_REASONS = ["missing_permission", "insufficient_scope", "out_of_scope"]
BLOCK_REASONS = ["malformed_request", "unauthenticated", "panel_realm_mismatch", "oauth_scope_mismatch",
                 "panel_not_covered", "cross_tenant_resource", "unknown_role", "realm_layer_mismatch"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
PANELS = {"L0", "L1", "L2"}
OWNERSHIP = {"own", "other"}
PERM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$")

# Degrade (inject) — DOĞRU panel/delege/tenant/backend-authority davranışını bozan müdahaleler.
INJECTIONS = {"panel_bypass", "oauth_scope_bypass", "realm_cross", "tenant_bypass", "fail_open",
              "client_claim_trust", "missing_perm_decl", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "panel_violation", "scope_violation", "realm_violation", "cross_tenant", "fail_open_grant",
    "client_trust_violation", "undeclared_endpoint", "model_tampered", "missing_evidence",
    "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.x deseniyle) — ham içerik/PII/sır yasak; rol/permission-key/panel/scope ID beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|apikey:manage|api_developer|api key/webhook|API key|panel:l[012]|bearer token'ı)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + rol adı/permission-key/panel-scope ID + maskeli token eler (12.1.x deseni)."""
    hits = []
    for ln, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("#"):
            continue
        for name, pat in LEAK_PATTERNS:
            for m in pat.finditer(line):
                frag = m.group(0)
                window = line[max(0, m.start() - 14):m.end() + 14]
                if '"$comment"' in line or '"description"' in line or '"desc"' in line or '"trace"' in line or line.strip().startswith('"$'):
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


def _guard_model():
    return _load(GUARD_MODEL_PATH)


def _rbac_model():
    """Rol modeli = 12.1.1 config/rbac-roles.json (frozen — layer/realm + IMMUTABLE bundle). TÜKETİLİR."""
    return _load(RBAC_MODEL_PATH)


_SA_CACHE = {}


def _scoped_module():
    """12.1.3 scoped-assignment probe'unu modül olarak yükle (rol+scope yetki kararı DELEGE)."""
    if "m" not in _SA_CACHE:
        spec = importlib.util.spec_from_file_location("scoped_assignment_probe", SCOPED_PROBE_PATH)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _SA_CACHE["m"] = m
    return _SA_CACHE["m"]


def _layer_covers(rbac, guard_model, role, panel):
    """Atama rolünün katmanı (12.1.1 layer) endpoint panelini kapsar mı? (S2 panel kapsama)."""
    spec = rbac["roles"].get(role)
    if not spec:
        return False
    layer = spec.get("layer", "")
    return panel in guard_model.get("layer_covers", {}).get(layer, [])


def build(sample, spec, inject=None, guard_model=None, rbac=None):
    """Tek HTTP guard isteği senaryosunu yürüt → HttpGuardDecision + ihlal sayaçları.

    Motor DOĞRU panel/delege/tenant/backend-authority davranışını hesaplar; inject (degrade) doğru davranışı
    bozar ve eşleşen ihlal sayacını artırır (12.1.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    guard_model = guard_model if guard_model is not None else _guard_model()
    rbac = rbac if rbac is not None else _rbac_model()
    sa = _scoped_module()

    request_id = sample.get("request_id")
    tenant_id = sample.get("tenant_id")              # session tenant binding (L1/L2)
    actor_user_id = sample.get("actor_user_id")
    actor_realm = sample.get("actor_realm")
    authenticated = sample.get("authenticated", True)
    token = dict(sample.get("token", {}) or {})
    token_realm = token.get("realm", actor_realm)
    token_panel_scope = token.get("panel_scope")
    endpoint = dict(sample.get("endpoint", {}) or {})
    endpoint_panel = endpoint.get("panel")
    required = endpoint.get("required_permission")
    assignments = list(sample.get("assignments", []) or [])
    resource = dict(sample.get("resource", {}) or {})
    ownership = sample.get("ownership", "other")
    client_claims = dict(sample.get("client_claims", {}) or {})

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    block_reason = None
    deny_reason = None
    allowed = False
    http_status = None
    delegated = None
    panel_realm_map = guard_model["panel_realm"]
    panel_scope_map = guard_model["panel_oauth_scope"]
    require_decl = guard_model.get("require_permission_declaration", True)

    # ── S10 model bütünlük manifesti (frozen guard model + 12.1.1 rbac frozen) ──
    canonical_model = {
        "guard": {k: guard_model.get(k) for k in (
            "frozen", "fail_closed", "decision_at", "panels", "panel_realm", "panel_oauth_scope",
            "layer_covers", "require_permission_declaration", "trust_source")},
        "rbac_frozen": rbac.get("frozen"),
    }
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical_model))
        tampered["guard"]["panel_realm"] = dict(tampered["guard"]["panel_realm"])
        tampered["guard"]["panel_realm"]["L0"] = "tenant"   # L0'ı tenant realm'e aç (tahrifat)
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── S6 backend otoritesi: client-supplied iddia ASLA güvenilmez (degrade güveni gösterir) ──
    if "client_claim_trust" in inject and client_claims:
        v["client_trust_violation"] += 1
        if client_claims.get("assignments"):
            assignments = list(client_claims["assignments"])           # güvenilmez rol iddiası override (insecure)
        if client_claims.get("required_permission_override"):
            required = client_claims["required_permission_override"]    # güvenilmez permission override (insecure)

    # ── S3 deklarasyon zorunlu (API.md x-required-permission): eksik/biçimsiz → fail-closed ──
    decl_missing = (not required or not isinstance(required, str) or not PERM_KEY_RE.match(required))
    if "missing_perm_decl" in inject and decl_missing:
        v["undeclared_endpoint"] += 1
        decl_missing = False                 # degrade: deklarasyonsuz endpoint'i fail-closed YAPMA (insecure)
        if not required:
            required = "calls:read"          # güvensiz varsayılan (deklarasyon atlanır)

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not actor_user_id or actor_realm not in REALMS
                 or endpoint_panel not in PANELS
                 or not assignments or not all(a.get("role") for a in assignments)
                 or (require_decl and decl_missing)
                 or not isinstance(resource, dict) or not resource)

    if malformed:
        terminal, block_reason = "BLOCK", "malformed_request"
    elif not authenticated:
        terminal, block_reason = "BLOCK", "unauthenticated"
    else:
        want_realm = panel_realm_map[endpoint_panel]
        want_scope = panel_scope_map[endpoint_panel]

        # ── S2 PANEL gate: realm (platform↔tenant) ──
        realm_ok = (actor_realm == want_realm and token_realm == want_realm)
        if "realm_cross" in inject and not realm_ok:
            v["realm_violation"] += 1
            realm_ok = True                  # degrade: yanlış realm token'ı kabul (L0↔tenant sınır ihlali)

        # ── S2 PANEL gate: OAuth scope ──
        scope_ok = (token_panel_scope == want_scope)
        if "oauth_scope_bypass" in inject and not scope_ok:
            v["scope_violation"] += 1
            scope_ok = True                  # degrade: yanlış/eksik panel scope'unu kabul

        # ── S2 PANEL gate: ≥1 atama rol katmanı paneli kapsar ──
        covered = any(_layer_covers(rbac, guard_model, a.get("role"), endpoint_panel)
                      for a in assignments if a.get("role") in rbac["roles"])
        if "panel_bypass" in inject and not (realm_ok and scope_ok and covered):
            v["panel_violation"] += 1
            realm_ok = scope_ok = covered = True   # degrade: panel kapısını tümüyle atla

        if not realm_ok:
            terminal, block_reason = "BLOCK", "panel_realm_mismatch"
        elif not scope_ok:
            terminal, block_reason = "BLOCK", "oauth_scope_mismatch"
        elif not covered:
            terminal, block_reason = "BLOCK", "panel_not_covered"
        else:
            # ── S5 TENANT scope gate: HTTP enforce_tenant_scope (tenant panelleri; RLS çift kontrol 12.2.3) ──
            res_tenant = resource.get("tenant_id")
            cross = (want_realm == "tenant") and res_tenant is not None and res_tenant != tenant_id
            if "tenant_bypass" in inject:
                if cross or (want_realm == "tenant" and res_tenant is None):
                    v["cross_tenant"] += 1
                cross = False                # degrade: enforce_tenant_scope'u atla (tenant sızıntısı)
            elif cross:
                v["cross_tenant"] += 1

            if cross:
                terminal, block_reason = "BLOCK", "cross_tenant_resource"
            else:
                # ── S4 DELEGE: rol+scope yetki kararı → 12.1.3 scoped-assignment (o da 12.1.1 bundle'ı çözer) ──
                sa_sample = {
                    "request_id": request_id, "tenant_id": tenant_id, "actor_user_id": actor_user_id,
                    "actor_realm": actor_realm, "assignments": assignments,
                    "required_permission": required, "resource": resource, "ownership": ownership,
                }
                delegated = sa.build(sa_sample, sa._load(sa.SPEC_PATH))
                dterm = delegated["terminal"]
                if dterm == "GRANT":
                    terminal, allowed = "ALLOW", True
                elif dterm == "DENY":
                    terminal, deny_reason = "DENY", delegated["deny_reason"]
                else:
                    terminal, block_reason = "BLOCK", delegated["block_reason"]

                # ── S4 degrade: delege GRANT değilken ALLOW (fail-open) ──
                if "fail_open" in inject and not allowed:
                    v["fail_open_grant"] += 1
                    terminal, allowed, deny_reason, block_reason = "ALLOW", True, None, None

    # ── HTTP durum kodu ──
    hs = guard_model["http_status"]
    if terminal == "ALLOW":
        http_status = hs["ALLOW"]
    elif terminal == "DENY":
        http_status = hs["DENY"]
    elif terminal == "BLOCK":
        http_status = hs["unauthenticated"] if block_reason == "unauthenticated" else hs["block_default"]

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, actor_realm, endpoint_panel, required, assignments, resource,
                         ownership, allowed, terminal, deny_reason, block_reason, http_status,
                         delegated, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, block_reason, deny_reason, allowed, http_status, endpoint_panel,
                 required, assignments, resource, ownership, actor_realm, delegated, model_hash, evidence)


def _evidence(request_id, actor_realm, endpoint_panel, required, assignments, resource, ownership,
              allowed, terminal, deny_reason, block_reason, http_status, delegated, model_hash):
    return {
        "request_id": request_id,
        "actor_realm": actor_realm,
        "endpoint_panel": endpoint_panel,
        "required_permission": required,
        "assignments": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in assignments],
        "resource": resource,
        "ownership": ownership,
        "allowed": allowed,
        "terminal": terminal,
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "http_status": http_status,
        "delegated_terminal": (delegated or {}).get("terminal"),
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, block_reason, deny_reason, allowed, http_status, endpoint_panel, required,
          assignments, resource, ownership, actor_realm, delegated, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "block_reason": block_reason,
        "deny_reason": deny_reason,
        "allowed": allowed,
        "http_status": http_status,
        "endpoint_panel": endpoint_panel,
        "required_permission": required,
        "assignments": [{"role": a.get("role"), "scope": a.get("scope", {})} for a in assignments],
        "resource": resource,
        "ownership": ownership,
        "actor_realm": actor_realm,
        "delegated_terminal": (delegated or {}).get("terminal"),
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "panel_violation": "max_panel_violation",
        "scope_violation": "max_scope_violation",
        "realm_violation": "max_realm_violation",
        "cross_tenant": "max_cross_tenant",
        "fail_open_grant": "max_fail_open_grant",
        "client_trust_violation": "max_client_trust_violation",
        "undeclared_endpoint": "max_undeclared_endpoint",
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
        for key in ("terminal", "block_reason", "deny_reason", "allowed", "http_status"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s allowed=%s http=%s panel=%s reason=%s/%s required=%s delege=%s"
              % (res["terminal"], res["allowed"], res["http_status"], res["endpoint_panel"],
                 res["block_reason"], res["deny_reason"], res["required_permission"],
                 res["delegated_terminal"]))
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
              "block_reasons", "deny_reasons", "outcomes", "model", "enforcement", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.2.1", spec.get("wbs") == "12.2.1")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement decision_at=backend", spec.get("placement", {}).get("decision_at") == "backend")

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-008 izlenir (panel-katman rol ayrımı — ÇEKİRDEK)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("FR-IAM-011 izlenir (scoped assignment)", "FR-IAM-011" in tr.get("fr", []))
    chk("SAD §14.4.2 backend guard izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-011 izlenir (iki düzlemli panel dağıtımı)",
        any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("ADR-012 izlenir (sabit rol bundle + scoped assignment)",
        any(a.startswith("ADR-012") for a in tr.get("adr", [])))
    chk("12.1.1 RBAC modeli TÜKETİLİR (consumes)", any("12.1.1" in s for s in tr.get("consumes", [])))
    chk("12.1.3 scoped-assignment DELEGE/TÜKETİLİR (consumes)", any("12.1.3" in s for s in tr.get("consumes", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (panel/declaration/delege/tenant/backend/fail_closed/model)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→authn→panel→tenant→delege fail-closed",
        rz.get("evaluation") == "malformed_then_authn_then_panel_then_tenant_then_delegated_authz_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar ALLOW/DENY/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi tam", br == set(BLOCK_REASONS))
    dr = set(spec["deny_reasons"].get("list", []))
    chk("deny_reason taksonomisi (12.1.3'ten devralınır)", dr == set(DENY_REASONS))

    # 6) Enforcement — panel + delege + tenant
    en = spec["enforcement"]
    chk("panel_gate realm+scope+layer kapsama", all(x in en.get("panel_gate", "") for x in ("realm", "scope")))
    chk("delegated_to 12.1.3", "12.1.3" in en.get("delegated_authorization", ""))
    chk("tenant_gate enforce_tenant_scope + RLS çift kontrol",
        "enforce_tenant_scope" in en.get("tenant_gate", "") and "RLS" in en.get("tenant_gate", ""))
    chk("decision_at backend (UI yalnız görsel)", en.get("decision_at") == "backend")
    chk("trust_source verified_token_only", en.get("trust_source") == "verified_token_only")

    # 7) Model alanları
    md = spec["model"]
    chk("panels L0/L1/L2", set(md.get("panels", [])) == PANELS)
    chk("panel_realm L0→platform L1/L2→tenant",
        md.get("panel_realm", {}).get("L0") == "platform" and md.get("panel_realm", {}).get("L2") == "tenant")
    chk("require_permission_declaration=true (API.md)", md.get("require_permission_declaration") is True)
    chk("guard_model 12.1.1/12.1.3 referansı",
        "12.1.1" in md.get("rbac_model", "") and "12.1.3" in md.get("scoped_decision", ""))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_panel_violation", "max_scope_violation", "max_realm_violation", "max_cross_tenant",
               "max_fail_open_grant", "max_client_trust_violation", "max_undeclared_endpoint",
               "max_model_tampered", "max_missing_evidence", "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("guard_decision_total metrik", "guard_decision_total" in obs.get("metrics", []))
    chk("guard_integrity_violation_total metrik (alarm)",
        "guard_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id YÜKSEK kard (label değil)", "request_id" in hi and "request_id" not in lo)
    chk("result/panel/actor_realm DÜŞÜK kard (label uygun)",
        "result" in lo and "panel" in lo and "actor_realm" in lo)
    chk("alarm panel_violation/cross_tenant/fail_open ≤2dk",
        any(x in obs.get("alarm", "") for x in ("panel_violation", "cross_tenant", "fail_open")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)

    # 11) Guard modeli dosyası + içsel tutarlılık
    gm_ok = os.path.exists(GUARD_MODEL_PATH)
    chk("config/guard-model.json var", gm_ok)
    if gm_ok:
        gm = _guard_model()
        chk("guard model frozen=true", gm.get("frozen") is True)
        chk("guard model fail_closed=true", gm.get("fail_closed") is True)
        chk("guard model decision_at=backend", gm.get("decision_at") == "backend")
        chk("guard model trust_source=verified_token_only", gm.get("trust_source") == "verified_token_only")
        chk("guard model panels L0/L1/L2", set(gm.get("panels", [])) == PANELS)
        chk("guard model panel_realm tutarlı", gm.get("panel_realm", {}).get("L0") == "platform"
            and gm.get("panel_realm", {}).get("L1") == "tenant" and gm.get("panel_realm", {}).get("L2") == "tenant")
        chk("guard model panel_oauth_scope tam", set(gm.get("panel_oauth_scope", {}).keys()) == PANELS)
        chk("guard model layer_covers L1+L2 → {L1,L2}",
            set(gm.get("layer_covers", {}).get("L1+L2", [])) == {"L1", "L2"})
        chk("guard model require_permission_declaration=true", gm.get("require_permission_declaration") is True)
        chk("guard model tenant_double_check guard+RLS",
            gm.get("tenant_double_check", {}).get("guard_level") is True
            and "12.2.3" in gm.get("tenant_double_check", {}).get("rls_level", ""))

    # 12) 12.1.1 RBAC + 12.1.3 scoped-assignment erişilebilir (consumes/delege)
    rbac_ok = os.path.exists(RBAC_MODEL_PATH)
    chk("12.1.1 ../rbac-model/config/rbac-roles.json var (TÜKETİLİR)", rbac_ok)
    if rbac_ok:
        rbac = _rbac_model()
        chk("12.1.1 rbac frozen=true", rbac.get("frozen") is True)
        chk("12.1.1 12 rol", len(rbac.get("roles", {})) == 12)
        chk("operations_manager layer=L2 (panel kapsama örneği)",
            rbac.get("roles", {}).get("operations_manager", {}).get("layer") == "L2")
        chk("tenant_owner layer=L1+L2 (hem L1 hem L2 kapsar)",
            rbac.get("roles", {}).get("tenant_owner", {}).get("layer") == "L1+L2")
    sa_ok = os.path.exists(SCOPED_PROBE_PATH)
    chk("12.1.3 ../scoped-assignment/scoped_assignment_probe.py var (DELEGE)", sa_ok)
    if sa_ok:
        try:
            sa = _scoped_module()
            d = sa.build({"request_id": "req-1", "tenant_id": "t-acme", "actor_user_id": "u-1",
                          "actor_realm": "tenant",
                          "assignments": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
                          "required_permission": "campaign:manage", "ownership": "other",
                          "resource": {"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-1"}},
                         sa._load(sa.SPEC_PATH))
            chk("12.1.3 delege çağrısı GRANT döndürür (canlı kompozisyon)", d.get("terminal") == "GRANT")
        except Exception as e:  # noqa
            chk("12.1.3 delege çağrısı GRANT döndürür (canlı kompozisyon)", False, str(e))

    # 13) Sır/PII tarayıcı — spec + modeller + samples
    scan_files = [SPEC_PATH, GUARD_MODEL_PATH] + (
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
    chk("hiç ham-içerik/PII/sır sızıntısı yok (S12)", total_leaks == 0)

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
        # Varsayılan: operations_manager (L2) → L2 paneli, calls:read, brand-x kapsamı, brand-x kaynağı → ALLOW.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_user_id": "u-1", "actor_realm": "tenant", "authenticated": True,
            "token": {"realm": "tenant", "panel_scope": "panel:L2"},
            "endpoint": {"panel": "L2", "required_permission": "calls:read", "method": "GET"},
            "assignments": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
            "ownership": "other",
            "resource": {"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-1"},
        }
        d.update(kw)
        return d

    # 1) happy — ALLOW
    r = build(req(), spec)
    case("happy: ALLOW", r["terminal"] == "ALLOW")
    case("happy: allowed=true", r["allowed"] is True)
    case("happy: http=200", r["http_status"] == 200)
    case("happy: delege=GRANT", r["delegated_terminal"] == "GRANT")
    case("happy: model_hash var (S10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) L1 admin ALLOW
    r = build(req(token={"realm": "tenant", "panel_scope": "panel:L1"},
                  endpoint={"panel": "L1", "required_permission": "user:manage"},
                  assignments=[{"role": "tenant_admin", "scope": {}}],
                  resource={"tenant_id": "t-acme"}), spec)
    case("L1-admin: ALLOW", r["terminal"] == "ALLOW")

    # 4) L0 platform ALLOW (platform realm + panel:L0)
    r = build(req(actor_realm="platform", token={"realm": "platform", "panel_scope": "panel:L0"},
                  endpoint={"panel": "L0", "required_permission": "tenant:provision"},
                  assignments=[{"role": "platform_owner", "scope": {}}],
                  resource={"tenant_id": "t-acme"}), spec)
    case("L0-platform: ALLOW", r["terminal"] == "ALLOW")

    # 5) tenant_owner (L1+L2) L2 panelinde ALLOW
    r = build(req(assignments=[{"role": "tenant_owner", "scope": {}}]), spec)
    case("L1+L2 owner @ L2: ALLOW", r["terminal"] == "ALLOW")

    # 6) S2 PANEL realm mismatch — tenant token L0 panelde → BLOCK panel_realm_mismatch
    r = build(req(endpoint={"panel": "L0", "required_permission": "tenant:provision"}), spec)
    case("panel-realm: BLOCK panel_realm_mismatch", r["terminal"] == "BLOCK" and r["block_reason"] == "panel_realm_mismatch")
    case("panel-realm: http=403 + ihlal yok (meşru)", r["http_status"] == 403 and all(x == 0 for x in r["violations"].values()))

    # 7) S2 OAuth scope mismatch — yanlış panel scope → BLOCK oauth_scope_mismatch
    r = build(req(token={"realm": "tenant", "panel_scope": "panel:L1"}), spec)
    case("oauth-scope: BLOCK oauth_scope_mismatch", r["terminal"] == "BLOCK" and r["block_reason"] == "oauth_scope_mismatch")

    # 8) S2 panel not covered — L1 rolü (billing_viewer) L2 panelde → BLOCK panel_not_covered
    r = build(req(assignments=[{"role": "billing_viewer", "scope": {}}]), spec)
    case("panel-not-covered: BLOCK panel_not_covered", r["terminal"] == "BLOCK" and r["block_reason"] == "panel_not_covered")

    # 9) S4 delege DENY out_of_scope (kapsam dışı marka) → HTTP 403
    r = build(req(resource={"tenant_id": "t-acme", "brand": "brand-y"}), spec)
    case("delege-deny: DENY out_of_scope + http 403", r["terminal"] == "DENY" and r["deny_reason"] == "out_of_scope" and r["http_status"] == 403)
    case("delege-deny: ihlal yok (meşru)", all(x == 0 for x in r["violations"].values()))

    # 10) S4 delege DENY missing_permission
    r = build(req(endpoint={"panel": "L2", "required_permission": "campaign:manage"},
                  assignments=[{"role": "qa_analyst", "scope": {}}]), spec)
    case("delege-deny: missing_permission", r["terminal"] == "DENY" and r["deny_reason"] == "missing_permission")

    # 11) :own disiplini delege edilir (human_agent calls:read:own; other → insufficient_scope)
    r = build(req(assignments=[{"role": "human_agent", "scope": {}}],
                  endpoint={"panel": "L2", "required_permission": "calls:read"},
                  ownership="other", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), spec)
    case("own-other: DENY insufficient_scope", r["terminal"] == "DENY" and r["deny_reason"] == "insufficient_scope")
    r = build(req(assignments=[{"role": "human_agent", "scope": {}}],
                  endpoint={"panel": "L2", "required_permission": "calls:read"},
                  ownership="own", resource={"tenant_id": "t-acme", "campaign": "camp-1"}), spec)
    case("own-own: ALLOW", r["terminal"] == "ALLOW")

    # 12) S5 tenant scope — cross-tenant kaynak → BLOCK cross_tenant_resource + cross_tenant>0
    r = build(req(resource={"tenant_id": "t-other", "brand": "brand-x"}), spec)
    case("cross-tenant: BLOCK cross_tenant_resource", r["terminal"] == "BLOCK" and r["block_reason"] == "cross_tenant_resource")
    case("cross-tenant: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 13) authn yok → BLOCK unauthenticated 401
    r = build(req(authenticated=False), spec)
    case("authn: BLOCK unauthenticated http 401", r["terminal"] == "BLOCK" and r["block_reason"] == "unauthenticated" and r["http_status"] == 401)

    # 14) malformed → BLOCK
    case("malformed-nopanel: BLOCK", build(req(endpoint={"required_permission": "calls:read"}), spec)["block_reason"] == "malformed_request")
    case("malformed-noassign: BLOCK", build(req(assignments=[]), spec)["block_reason"] == "malformed_request")
    case("malformed-noperm: BLOCK (deklarasyon zorunlu)", build(req(endpoint={"panel": "L2"}), spec)["block_reason"] == "malformed_request")
    case("malformed-badperm: BLOCK", build(req(endpoint={"panel": "L2", "required_permission": "calls"}), spec)["block_reason"] == "malformed_request")

    # 15) S6 backend otoritesi — client_claims yoksayılır (inject olmadan)
    r = build(req(client_claims={"assignments": [{"role": "tenant_owner", "scope": {}}],
                                 "required_permission_override": "tenant:provision"}), spec)
    case("backend-authority: client_claims yoksayılır (token rolü kullanılır → ALLOW calls:read)", r["terminal"] == "ALLOW")
    case("backend-authority: ihlal yok", all(x == 0 for x in r["violations"].values()))

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 16) panel_bypass
    r = build(req(endpoint={"panel": "L0", "required_permission": "tenant:provision"}), spec, inject=["panel_bypass"])
    case("panel-bypass: panel_violation>0 + kapı eler", r["violations"]["panel_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 17) oauth_scope_bypass
    r = build(req(token={"realm": "tenant", "panel_scope": "panel:L1"}), spec, inject=["oauth_scope_bypass"])
    case("oauth-scope-bypass: scope_violation>0 + kapı eler", r["violations"]["scope_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) realm_cross
    r = build(req(endpoint={"panel": "L0", "required_permission": "tenant:provision"}), spec, inject=["realm_cross"])
    case("realm-cross: realm_violation>0 + kapı eler", r["violations"]["realm_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 19) tenant_bypass
    r = build(req(resource={"tenant_id": "t-other", "brand": "brand-x"}), spec, inject=["tenant_bypass"])
    case("tenant-bypass: cross_tenant>0 + kapı eler", r["violations"]["cross_tenant"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) fail_open — delege DENY iken ALLOW zorla
    r = build(req(resource={"tenant_id": "t-acme", "brand": "brand-y"}), spec, inject=["fail_open"])
    case("fail-open: fail_open_grant>0 + ALLOW (yanlış) + kapı eler",
         r["violations"]["fail_open_grant"] > 0 and r["terminal"] == "ALLOW" and _gate_eval(r, G)[0] is False)

    # 21) client_claim_trust
    r = build(req(endpoint={"panel": "L2", "required_permission": "campaign:manage"},
                  assignments=[{"role": "qa_analyst", "scope": {}}],
                  client_claims={"assignments": [{"role": "operations_manager", "scope": {}}]}), spec,
              inject=["client_claim_trust"])
    case("client-trust: client_trust_violation>0 + kapı eler",
         r["violations"]["client_trust_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) missing_perm_decl
    r = build(req(endpoint={"panel": "L2"}), spec, inject=["missing_perm_decl"])
    case("missing-perm-decl: undeclared_endpoint>0 + kapı eler",
         r["violations"]["undeclared_endpoint"] > 0 and _gate_eval(r, G)[0] is False)

    # 23) model_tamper
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 24) evidence + leak
    r = build(req(), spec)
    case("evidence: request+panel+assignments+resource+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "endpoint_panel", "assignments", "resource", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("customer_phone_value", "card_pan_value", "raw_value")))
    case("leak: rol+permission-key+panel-scope temiz",
         scan_leaks('{"role":"operations_manager","required_permission":"calls:read","panel_scope":"panel:L2"}') == [])
    case("leak: card_pan_value alanı yakalanır", len(scan_leaks('{"card_pan_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "backend-guard (WBS 12.2.1 — panel + rol + tenant scope; FastAPI dependency; SAD §14.4.2)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "allow_terminals": sorted(GRANT_TERMINALS),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "deny_reasons": DENY_REASONS,
        "realms": sorted(REALMS),
        "panels": sorted(PANELS),
        "ownership": sorted(OWNERSHIP),
        "decision": "malformed ⇒ BLOCK(malformed_request) → kimlik yok ⇒ BLOCK(unauthenticated,401) → "
                    "token realm ≠ panel realm ⇒ BLOCK(panel_realm_mismatch) → token scope ≠ panel scope ⇒ "
                    "BLOCK(oauth_scope_mismatch) → hiçbir rol katmanı paneli kapsamaz ⇒ BLOCK(panel_not_covered) → "
                    "resource.tenant_id ≠ session tenant ⇒ BLOCK(cross_tenant_resource) → DELEGE 12.1.3: "
                    "GRANT ⇒ ALLOW(200) | DENY ⇒ DENY(403) | BLOCK ⇒ BLOCK(403)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ allowed=false; belirsizlik/malformed/kimliksiz/panel-uyumsuz/cross-tenant ⇒ no access",
        "core_guarantees": [
            "S2 panel izolasyonu: endpoint paneli için token realm+OAuth scope + rol-katman kapsama; L0 ⟂ tenant; panel_violation/scope_violation/realm_violation=0 (FR-IAM-008/ADR-011)",
            "S4 delege doğruluğu: ALLOW ⟺ 12.1.3 GRANT; guard fail-open YAPMAZ; fail_open_grant=0 (SAD §14.4.2)",
            "S5 tenant scope: tenant panelinde resource.tenant_id = session tenant (HTTP enforce_tenant_scope + RLS çift kontrol 12.2.3); cross_tenant=0 (FR-TEN-002)",
            "S6 backend otoritesi: yetki YALNIZ doğrulanmış token'dan; client iddiası güvenilmez; client_trust_violation=0 (SAD §14.4.2)",
            "S3 deklarasyon zorunlu: endpoint geçerli x-required-permission deklare etmeli; undeclared_endpoint=0 (API.md)",
        ],
        "request_fields": ["name", "request_id", "tenant_id(session)", "correlation_id", "actor_user_id",
                           "actor_realm(platform|tenant)", "authenticated(bool)",
                           "token{realm, panel_scope}", "endpoint{panel(L0|L1|L2), required_permission(kaynak:eylem), method}",
                           "assignments[{role, scope}]", "resource{tenant_id, department, brand, campaign}",
                           "ownership(own|other)", "client_claims{}(güvenilmez)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "block_reason", "deny_reason", "allowed", "http_status", "endpoint_panel",
                            "required_permission", "assignments", "resource", "ownership", "actor_realm",
                            "delegated_terminal", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/guard-model.json (frozen — panels + panel_realm + panel_oauth_scope + layer_covers + "
                 "http_status + fail_closed) + ../rbac-model/config/rbac-roles.json (12.1.1 layer/realm/bundle)",
        "consumes": "12.1.1 RBAC modeli (layer/realm + immutable bundle); 12.1.3 scoped-assignment (rol+scope "
                    "yetki kararı DELEGE — GRANT/DENY/BLOCK); API.md x-required-permission konvansiyonu",
        "consumed_by": "12.2.2 ayrı router ağaçları + ayrı OAuth scope (panel boyutu topolojisi); 12.2.3 RLS çift "
                       "kontrol (DB seviyesi); 12.2.4 L0 repository bağımsızlığı; 12.3.x break-glass; 12.1.8 WORM "
                       "audit (karar kaydı); 0.4.7 gözlemlenebilirlik (guard_* metrikleri)",
        "trace": "FR-IAM-008, FR-TEN-002, FR-IAM-011, SAD §14.4.2, ADR-011, ADR-012, API.md",
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
            print("kullanım: backend_guard_probe.py check <sample.json|dizin>")
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
