#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 13.1.2 — Route group + middleware (oturum + tenant scope + panel ayrımı) referans probe.

13.1 "Ortak frontend altyapısı" alt-bloğunun İKİNCİ modülü; F1-Must. SAD §14.4.1'in "her route group
kendi layout + auth guard'ına sahiptir ... middleware oturum doğrulama + tenant scope (L1/L2 tek tenant'a
bağlı)" ÇALIŞMA-ANI kapısını doğrular. 13.1.1 iki ayrı app + route group İSKELETİNİ kurdu (yer tutucu
middleware); bu modül o iskelete çalışma-anı middleware'ini ekler:

    OTURUM → REALM/PANEL AYRIMI → TENANT SCOPE → PANEL mapping → CONTEXT propagasyonu

ÇEKİRDEK İLKE (A8 / SAD §14.4.1): UI yalnız GÖRSEL kapı; middleware coarse bir UX/yönlendirme kapısı +
context propagasyonudur. NİHAİ yetki (rol→permission, kaynak sahipliği) HER ZAMAN backend'de (12.2.x) +
PostgreSQL RLS (§13). Burada rol→izin KARARI YOKTUR.

Saf karar çekirdeği (lib/middleware-core.ts decide()) bu probe'ta Python ile BİREBİR aynalanır
(evaluate_request) — aynı semantik, davranışsal kapı + samples + selftest.

    DecisionInput ─exempt─► no_session ─► expired ─► realm ─► tenant_scope ─► panel ─► next/allow
        │            │          │            │          │           │            │
        │   ├─ exempt(path) ──────────────────────────────────────────────► next  (exempt)        [M2]
        │   ├─ session==null ────────────────────────────────────────────► redirect (no_session)  [M2]
        │   ├─ exp<=now ─────────────────────────────────────────────────► redirect (expired)     [M2]
        │   ├─ realm!=policy.realm ──────────────────────────────────────► forbid (realm_mismatch)[M3]
        │   ├─ tenantScoped & !tenant_id ───────────────────────────────► forbid (missing_bind)  [M4]
        │   ├─ tenantScoped & reqTenant!=tenant_id ─────────────────────► forbid (cross_tenant)  [M5]
        │   ├─ !tenantScoped & tenant_id ───────────────────────────────► forbid (unexpected)    [M4]
        │   └─ else ─────────────────────────────────────────────────────► next  (allow) + panel  [M6/M8]

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission + kaynak sahipliği nihai kararı → 12.2.x backend;
tenant scope çift-kontrol → RLS §13; tasarım sistemi/i18n → 13.1.3; PII maskeleme → 13.1.4; kriptografik
token imza/JWKS → auth realm + backend. KAYNAK DOĞRULUK; çelişkide SAD §14.4.1 / ADR-011 esastır.

Kullanım:
  route_middleware_probe.py validate        Statik spec + policy + ON-DISK middleware/lib invariant kapısı → çıkış kodu
  route_middleware_probe.py check <sample>   Saf karar çekirdeği: senaryo(lar) → action+reason (M1–M10)
  route_middleware_probe.py selftest         Gömülü davranış kontrolleri → çıkış kodu
  route_middleware_probe.py schema           Karar sözleşmesini yazdır

Determinizm: policy_hash sha256 (kanonik JSON, sort_keys); 'now' parametre (Date.now YOK). Stdlib-only.
Sır/credential ve ham içerik (PII/token DEĞERİ) üretilmez/yazılmaz (fixture sentetik — yalnız enum/ad).
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SPEC_PATH = os.path.join(HERE, "route-middleware-spec.json")
POLICY_PATH = os.path.join(HERE, "config", "middleware-policy.json")
SAMPLES_DIR = os.path.join(HERE, "samples")


# ── yardımcılar ───────────────────────────────────────────────────────────────

def _strip_comments(obj):
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not k.startswith("$")}
    if isinstance(obj, list):
        return [_strip_comments(x) for x in obj]
    return obj


def canonical_hash(obj):
    clean = _strip_comments(obj)
    blob = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


# ── SAF KARAR ÇEKİRDEĞİ (lib/middleware-core.ts decide() AYNASI) ────────────────
# AppPolicy: {app, realm, plane, tier, tenant_scoped, login_path, exempt_prefixes:[...], route_groups:[{prefix,group,panel}]}
# DecisionInput: {path, session:{sub,realm,tenant_id,exp}|None, now, requested_tenant|None, correlation_id}
# Decision: {action: next|redirect|forbid, reason, location?, status?, headers}

def is_exempt(policy, path):
    for p in policy.get("exempt_prefixes", []):
        if path == p or path.startswith(p + "/"):
            return True
    return False


def resolve_group(policy, path):
    best = None
    for rg in policy.get("route_groups", []):
        pre = rg["prefix"]
        match = pre == "/" or path == pre or path.startswith(pre + "/")
        if match and (best is None or len(pre) > len(best["prefix"])):
            best = rg
    return best


def decide(policy, inp):
    """Deterministik fail-closed karar — TS decide() ile birebir."""
    base = {
        "x-app-plane": policy["plane"],
        "x-app-tier": policy["tier"],
        "x-correlation-id": inp.get("correlation_id", ""),
    }
    path = inp["path"]
    session = inp.get("session")
    now = inp["now"]

    # A — exempt
    if is_exempt(policy, path):
        return {"action": "next", "reason": "exempt", "headers": base}

    # B — oturum yok
    if not session:
        loc = f"{policy['login_path']}?next={path}"
        return {"action": "redirect", "reason": "no_session", "location": loc, "headers": base}

    # C — süre doldu
    exp = session.get("exp")
    if not isinstance(exp, (int, float)) or exp <= now:
        loc = f"{policy['login_path']}?next={path}&reason=expired"
        return {"action": "redirect", "reason": "expired_session", "location": loc, "headers": base}

    # D — realm/panel ayrımı
    if session.get("realm") != policy["realm"]:
        return {"action": "forbid", "reason": "realm_mismatch", "status": 403, "headers": base}

    # E — tenant scope
    scope = {}
    if policy["tenant_scoped"]:
        tid = session.get("tenant_id")
        if not tid:
            return {"action": "forbid", "reason": "missing_tenant_binding", "status": 403, "headers": base}
        req_tenant = inp.get("requested_tenant")
        if req_tenant and req_tenant != tid:
            return {"action": "forbid", "reason": "cross_tenant_denied", "status": 403, "headers": base}
        scope["x-tenant-scope"] = tid
    else:
        if session.get("tenant_id"):
            return {"action": "forbid", "reason": "unexpected_tenant_binding", "status": 403, "headers": base}

    # F — panel mapping + context
    rg = resolve_group(policy, path)
    panel = {"x-panel": rg["panel"], "x-route-group": rg["group"]} if rg else {}
    headers = dict(base)
    headers.update(scope)
    headers.update(panel)
    headers["x-auth-subject"] = session.get("sub", "")
    return {"action": "next", "reason": "allow", "headers": headers}


def policy_from_config(app_name):
    cfg = load_json(POLICY_PATH)["apps"][app_name]
    return {
        "app": app_name,
        "realm": cfg["realm"],
        "plane": cfg["plane"],
        "tier": cfg["tier"],
        "tenant_scoped": cfg["tenant_scoped"],
        "login_path": cfg["login_path"],
        "exempt_prefixes": cfg["exempt_prefixes"],
        "route_groups": cfg["route_groups"],
    }


# ── DAVRANIŞSAL DEĞERLENDİRME (samples/selftest) ────────────────────────────────
# RequestScenario: {request_id, app, path, session|null, now, requested_tenant|null,
#                   expect_action, expect_reason, expect_headers?{...}}

def evaluate_request(scn):
    """Senaryoyu policy ile değerlendirir; beklenen action+reason+header'ları doğrular."""
    app = scn["app"]
    policy = policy_from_config(app)
    inp = {
        "path": scn["path"],
        "session": scn.get("session"),
        "now": scn.get("now", 0),
        "requested_tenant": scn.get("requested_tenant"),
        "correlation_id": scn.get("correlation_id", "cid-test"),
    }
    d = decide(policy, inp)
    ok = d["action"] == scn.get("expect_action") and d["reason"] == scn.get("expect_reason")
    notes = []
    if not ok:
        notes.append(f"action={d['action']}/reason={d['reason']} ≠ beklenen "
                     f"{scn.get('expect_action')}/{scn.get('expect_reason')}")
    # opsiyonel header doğrulama
    for k, v in scn.get("expect_headers", {}).items():
        if d["headers"].get(k) != v:
            ok = False
            notes.append(f"header {k}={d['headers'].get(k)} ≠ beklenen {v}")
    return {"ok": ok, "decision": d, "notes": notes, "request_id": scn.get("request_id")}


# ── on-disk kaynak tarama ───────────────────────────────────────────────────────

def app_mw_files(app_dir):
    base = os.path.join(REPO, app_dir)
    return {
        "middleware": os.path.join(base, "middleware.ts"),
        "session": os.path.join(base, "lib", "session.ts"),
        "core": os.path.join(base, "lib", "middleware-core.ts"),
    }


# A8/M7 — hardcoded NİHAİ yetki kararı token'ları (yalnız UX guard değil)
FRONTEND_AUTHZ_FORBIDDEN = ["authzDecision = true", "authorize() { return true",
                            "bypassAuth", "GRANT_ACCESS = true", "hasPermission(", "role ==="]


def scan_frontend_authz(app_dir):
    hits = []
    for name, p in app_mw_files(app_dir).items():
        text = read_text(p)
        for tok in FRONTEND_AUTHZ_FORBIDDEN:
            if tok in text:
                hits.append((app_dir, name, tok))
    return hits


def scan_env_example_has_value(app_dir):
    hits = []
    p = os.path.join(REPO, app_dir, ".env.example")
    if not os.path.isfile(p):
        return hits
    with open(p, "r", encoding="utf-8") as fh:
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            key, _, val = s.partition("=")
            val = val.split("#", 1)[0].strip()
            if val:
                hits.append(key.strip())
    return hits


# ── validate (ON-DISK + DAVRANIŞSAL) ────────────────────────────────────────────

def cmd_validate():
    spec = load_json(SPEC_PATH)
    policy_cfg = load_json(POLICY_PATH)
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # M1 — iyi biçimli + dosya varlığı
    chk(spec.get("wbs") == "13.1.2", "M1 spec.wbs=13.1.2")
    chk(policy_cfg.get("frozen") is True, "M1 policy frozen")
    for app in ("frontend/platform-app", "frontend/tenant-app"):
        f = app_mw_files(app)
        for name, p in f.items():
            chk(os.path.isfile(p), f"M1 {app}/{name} mevcut")
        mw = read_text(f["middleware"])
        # çalışma-anı middleware: decide import + yer tutucu DEĞİL
        chk("decide" in mw and "middleware-core" in mw, f"M1 {app} middleware decide() çekirdeğini import eder")
        chk("13.1.2 yer tutucu" not in mw, f"M1 {app} middleware yer tutucu DEĞİL")

    # M2 — oturum zorunlu (her iki çekirdekte no_session + expired_session)
    for app in ("frontend/platform-app", "frontend/tenant-app"):
        core = read_text(app_mw_files(app)["core"])
        chk("no_session" in core, f"M2 {app} no_session redirect")
        chk("expired_session" in core, f"M2 {app} expired_session redirect")

    # M3 — realm ayrımı
    for app in ("frontend/platform-app", "frontend/tenant-app"):
        core = read_text(app_mw_files(app)["core"])
        chk("realm_mismatch" in core, f"M3 {app} realm_mismatch forbid")

    # M4/M5 — tenant scope + cross-tenant
    core_tn = read_text(app_mw_files("frontend/tenant-app")["core"])
    chk("missing_tenant_binding" in core_tn, "M4 tenant-app missing_tenant_binding forbid")
    chk("unexpected_tenant_binding" in core_tn, "M4 unexpected_tenant_binding (platform tenant-bağlı reddi)")
    chk("cross_tenant_denied" in core_tn, "M5 tenant-app cross_tenant_denied forbid")
    chk("x-tenant-scope" in core_tn, "M4 tenant-app x-tenant-scope pin header")

    # M6 — panel mapping (tenant middleware policy'sinde /admin→L1, /workspace→L2)
    mw_tn = read_text(app_mw_files("frontend/tenant-app")["middleware"])
    chk('"/admin"' in mw_tn and '(tenant-admin)' in mw_tn and '"L1"' in mw_tn, "M6 tenant /admin→(tenant-admin)/L1")
    chk('"/workspace"' in mw_tn and '(workspace)' in mw_tn and '"L2"' in mw_tn, "M6 tenant /workspace→(workspace)/L2")
    mw_pf = read_text(app_mw_files("frontend/platform-app")["middleware"])
    chk('(platform)' in mw_pf and '"L0"' in mw_pf, "M6 platform /→(platform)/L0")

    # M7 — UI yalnız görsel kapı (hardcoded authz YOK)
    authz = scan_frontend_authz("frontend/platform-app") + scan_frontend_authz("frontend/tenant-app")
    chk(len(authz) == 0, f"M7 frontend hardcoded authz YOK [{authz}]")

    # M8 — context propagasyonu
    for app in ("frontend/platform-app", "frontend/tenant-app"):
        core = read_text(app_mw_files(app)["core"])
        chk("x-app-plane" in core and "x-correlation-id" in core, f"M8 {app} plane+correlation-id header")

    # M9 — sır/PII yok (.env.example RHS boş; spec/policy forbidden token yok)
    env_hits = scan_env_example_has_value("frontend/platform-app") + scan_env_example_has_value("frontend/tenant-app")
    chk(len(env_hits) == 0, f"M9 .env.example gerçek değer YOK [{env_hits}]")
    blob = json.dumps(_strip_comments(spec), ensure_ascii=False) + json.dumps(_strip_comments(policy_cfg), ensure_ascii=False)
    bad = [t for t in ("BEGIN PRIVATE KEY", "password=", "secret=", "eyJhbGci") if t in blob]
    chk(len(bad) == 0, f"M9 spec/policy sır token YOK [{bad}]")

    # M10 — policy bütünlüğü: on-disk middleware ↔ policy (realm/tenantScoped) tutarlı
    chk(policy_cfg["apps"]["platform-app"]["realm"] == "platform"
        and policy_cfg["apps"]["platform-app"]["tenant_scoped"] is False, "M10 platform policy realm=platform/tenant_scoped=false")
    chk(policy_cfg["apps"]["tenant-app"]["realm"] == "tenant"
        and policy_cfg["apps"]["tenant-app"]["tenant_scoped"] is True, "M10 tenant policy realm=tenant/tenant_scoped=true")
    # on-disk middleware'de realm/tenantScoped policy ile aynı
    chk("tenantScoped: false" in mw_pf and 'realm: APP_REALM' in mw_pf, "M10 platform middleware tenantScoped=false")
    chk("tenantScoped: true" in mw_tn and 'realm: APP_REALM' in mw_tn, "M10 tenant middleware tenantScoped=true")
    ph = canonical_hash(policy_cfg)
    chk(len(ph) == 64, f"M10 policy_hash sha256 ({ph[:12]}…)")

    # DAVRANIŞSAL — saf çekirdek temel senaryoları doğru karar verir
    behav = [
        # (app, path, session, now, requested_tenant, expect_action, expect_reason)
        ("platform-app", "/overview", None, 100, None, "redirect", "no_session"),
        ("platform-app", "/overview", {"sub": "u1", "realm": "platform", "tenant_id": None, "exp": 200}, 100, None, "next", "allow"),
        ("platform-app", "/overview", {"sub": "u1", "realm": "tenant", "tenant_id": "t1", "exp": 200}, 100, None, "forbid", "realm_mismatch"),
        ("tenant-app", "/admin/users", {"sub": "u2", "realm": "tenant", "tenant_id": "t1", "exp": 200}, 100, None, "next", "allow"),
        ("tenant-app", "/workspace/live-calls", {"sub": "u2", "realm": "tenant", "tenant_id": "t1", "exp": 200}, 100, "t2", "forbid", "cross_tenant_denied"),
        ("tenant-app", "/admin/users", {"sub": "u2", "realm": "tenant", "tenant_id": None, "exp": 200}, 100, None, "forbid", "missing_tenant_binding"),
        ("tenant-app", "/login", None, 100, None, "next", "exempt"),
    ]
    for app, path, sess, now, rt, ea, er in behav:
        scn = {"app": app, "path": path, "session": sess, "now": now,
               "requested_tenant": rt, "expect_action": ea, "expect_reason": er}
        r = evaluate_request(scn)
        chk(r["ok"], f"behav {app} {path} → {ea}/{er}")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} 🟢" if passed == total else f"\nvalidate: {passed}/{total} 🔴")
    print(f"policy_hash = {ph}")
    return 0 if passed == total else 1


# ── check (samples) ─────────────────────────────────────────────────────────────

def cmd_check(path):
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".json")]
    else:
        files = [path]
    if not files:
        print("check: örnek bulunamadı")
        return 1
    fails = 0
    for f in files:
        scn = load_json(f)
        r = evaluate_request(scn)
        mark = "🟢" if r["ok"] else "🔴"
        d = r["decision"]
        print(f"  {mark} {os.path.basename(f)}: action={d['action']} reason={d['reason']} "
              f"beklenen={scn.get('expect_action')}/{scn.get('expect_reason')}")
        if not r["ok"]:
            fails += 1
            for nt in r["notes"]:
                print(f"        · {nt}")
    print(f"\ncheck: {len(files)-fails}/{len(files)} 🟢" if fails == 0 else f"\ncheck: {len(files)-fails}/{len(files)} 🔴")
    return 0 if fails == 0 else 1


# ── selftest ─────────────────────────────────────────────────────────────────

def cmd_selftest():
    results = []

    def expect(label, scn, want_action, want_reason):
        scn = dict(scn)
        scn["expect_action"] = want_action
        scn["expect_reason"] = want_reason
        r = evaluate_request(scn)
        results.append((r["ok"], label))
        return r

    valid_tenant = {"sub": "u-1", "realm": "tenant", "tenant_id": "t-1", "exp": 1000}
    valid_platform = {"sub": "p-1", "realm": "platform", "tenant_id": None, "exp": 1000}
    NOW = 500

    # 1 — exempt (login) oturumsuz geçer
    expect("01 tenant /login exempt → next/exempt",
           {"app": "tenant-app", "path": "/login", "session": None, "now": NOW}, "next", "exempt")

    # 2 — oturum yok → redirect
    expect("02 tenant /admin oturumsuz → redirect/no_session",
           {"app": "tenant-app", "path": "/admin/users", "session": None, "now": NOW}, "redirect", "no_session")

    # 3 — expired
    expect("03 tenant /admin expired → redirect/expired_session",
           {"app": "tenant-app", "path": "/admin/users", "session": {"sub": "u", "realm": "tenant", "tenant_id": "t-1", "exp": 100}, "now": NOW},
           "redirect", "expired_session")

    # 4 — happy L1
    r = expect("04 tenant /admin/users valid → next/allow",
               {"app": "tenant-app", "path": "/admin/users", "session": valid_tenant, "now": NOW}, "next", "allow")
    results.append((r["decision"]["headers"].get("x-panel") == "L1"
                    and r["decision"]["headers"].get("x-route-group") == "(tenant-admin)", "04b L1 panel header"))
    results.append((r["decision"]["headers"].get("x-tenant-scope") == "t-1", "04c x-tenant-scope pin"))

    # 5 — happy L2
    r = expect("05 tenant /workspace/live-calls valid → next/allow",
               {"app": "tenant-app", "path": "/workspace/live-calls", "session": valid_tenant, "now": NOW}, "next", "allow")
    results.append((r["decision"]["headers"].get("x-panel") == "L2", "05b L2 panel header"))

    # 6 — M3 realm mismatch (platform oturumu tenant-app'e)
    expect("06 platform oturumu tenant-app'e → forbid/realm_mismatch",
           {"app": "tenant-app", "path": "/admin/users", "session": valid_platform, "now": NOW}, "forbid", "realm_mismatch")

    # 7 — M3 realm mismatch (tenant oturumu platform-app'e)
    expect("07 tenant oturumu platform-app'e → forbid/realm_mismatch",
           {"app": "platform-app", "path": "/overview", "session": valid_tenant, "now": NOW}, "forbid", "realm_mismatch")

    # 8 — M5 cross-tenant (query ipucu)
    expect("08 tenant cross-tenant ?tenant=t-2 → forbid/cross_tenant_denied",
           {"app": "tenant-app", "path": "/workspace/call", "session": valid_tenant, "now": NOW, "requested_tenant": "t-2"},
           "forbid", "cross_tenant_denied")

    # 9 — M5 aynı tenant ipucu geçer
    expect("09 tenant aynı ?tenant=t-1 → next/allow",
           {"app": "tenant-app", "path": "/workspace/call", "session": valid_tenant, "now": NOW, "requested_tenant": "t-1"},
           "next", "allow")

    # 10 — M4 missing tenant binding
    expect("10 tenant oturumu tenant_id'siz → forbid/missing_tenant_binding",
           {"app": "tenant-app", "path": "/admin/org", "session": {"sub": "u", "realm": "tenant", "tenant_id": None, "exp": 1000}, "now": NOW},
           "forbid", "missing_tenant_binding")

    # 11 — M4 platform tenant-bağlı reddi
    expect("11 platform oturumu tenant_id taşıyor → forbid/unexpected_tenant_binding",
           {"app": "platform-app", "path": "/overview", "session": {"sub": "p", "realm": "platform", "tenant_id": "t-9", "exp": 1000}, "now": NOW},
           "forbid", "unexpected_tenant_binding")

    # 12 — happy L0 platform
    r = expect("12 platform /overview valid → next/allow",
               {"app": "platform-app", "path": "/overview", "session": valid_platform, "now": NOW}, "next", "allow")
    results.append((r["decision"]["headers"].get("x-panel") == "L0", "12b L0 panel header"))
    results.append(("x-tenant-scope" not in r["decision"]["headers"], "12c platform tenant-scope header YOK"))

    # 13 — determinizm
    a = decide(policy_from_config("tenant-app"), {"path": "/admin/users", "session": valid_tenant, "now": NOW, "requested_tenant": None, "correlation_id": "c"})
    b = decide(policy_from_config("tenant-app"), {"path": "/admin/users", "session": valid_tenant, "now": NOW, "requested_tenant": None, "correlation_id": "c"})
    results.append((a == b, "13 determinizm (aynı girdi → aynı çıktı)"))

    # 14 — fail-closed: bozuk oturum (geçersiz exp) → no_session? exp None → expired_session yolu
    expect("14 fail-closed exp yok → redirect/expired_session",
           {"app": "tenant-app", "path": "/admin/users", "session": {"sub": "u", "realm": "tenant", "tenant_id": "t-1", "exp": None}, "now": NOW},
           "redirect", "expired_session")

    # 15 — x-tenant-id header ipucu de cross-tenant tetikler (requested_tenant)
    expect("15 cross-tenant header ipucu → forbid/cross_tenant_denied",
           {"app": "tenant-app", "path": "/workspace/qa", "session": valid_tenant, "now": NOW, "requested_tenant": "t-other"},
           "forbid", "cross_tenant_denied")

    # 16 — policy_hash determinizm
    h1 = canonical_hash(load_json(POLICY_PATH))
    h2 = canonical_hash(load_json(POLICY_PATH))
    results.append((h1 == h2 and len(h1) == 64, "16 policy_hash deterministik sha256"))

    passed = sum(1 for ok, _ in results if ok)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{len(results)} 🟢" if passed == len(results) else f"\nselftest: {passed}/{len(results)} 🔴")
    return 0 if passed == len(results) else 1


# ── schema ───────────────────────────────────────────────────────────────────

def cmd_schema():
    print(json.dumps({
        "wbs": "13.1.2",
        "input": "RequestScenario{request_id, app, path, session:{sub,realm,tenant_id,exp}|null, now, "
                 "requested_tenant|null, expect_action, expect_reason, expect_headers?}",
        "output": "{action: next|redirect|forbid, reason, headers}",
        "reasons": ["exempt", "no_session", "expired_session", "realm_mismatch",
                    "missing_tenant_binding", "cross_tenant_denied", "unexpected_tenant_binding", "allow"],
        "gates": ["silent_allow_unauthenticated(M2)", "realm_mismatch_allow(M3)", "cross_tenant_allow(M5)",
                  "missing_tenant_binding_allow(M4)", "panel_mismatch(M6)", "frontend_authz(M7)",
                  "missing_context(M8)", "secret_or_pii(M9)", "policy_mismatch(M10)", "files_missing(M1)"],
        "default": "FAIL (fail-closed)",
        "trace": "SAD §14.4.1, FR-TEN-002, FR-IAM-008, ADR-011",
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "validate":
        return cmd_validate()
    if cmd == "check":
        target = sys.argv[2] if len(sys.argv) >= 3 else SAMPLES_DIR
        return cmd_check(target)
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "schema":
        return cmd_schema()
    print(f"bilinmeyen komut: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
