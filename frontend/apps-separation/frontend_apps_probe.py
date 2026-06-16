#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 13.1.1 — İki ayrı Next.js app (platform-app L0 internal-only + tenant-app L1+L2 public) referans probe.

13. workstream'in (Frontend / Panel) İLK modülü ve 13.1 "Ortak frontend altyapısı" alt-bloğunun TEMELİ;
F1-Must. SAD §14.4.1'in "Yönetim/panel uygulaması Next.js App Router ile ... AYRI deploy" kararını + ADR-011'in
(İki düzlemli panel dağıtımı — L0 ayrı internal-only Control Plane; L1+L2 birlikte public Tenant Application
Plane) FİZİKSEL App Router iskeletini doğrular.

İKİ AYRI APP (deploy-zamanı plane ayrımı; ADR-011 Seçenek 3):

    frontend/platform-app  (L0)     → YALNIZ (platform) route group; internal_only; auth_realm=platform
    frontend/tenant-app    (L1+L2)  → (tenant-admin) + (workspace) route group; public; auth_realm=tenant

ÇEKİRDEK İNVARYANT (A5): platform-app tenant iş verisi route'larını (live-calls/recordings/call/transcript/...)
FİZİKSEL OLARAK İÇERMEZ — tek-deploy+guard (ADR-011 Seçenek 1) reddedildi: paylaşılan kod/middleware'de tek bug
bile L0'ı AÇAMAZ çünkü tenant içeriği route'u platform-app yüzeyinde YOKTUR (blast-radius azaltımı, FR-IAM-008).

  AppTopologyRequest ─malformed─► two-apps ─► route-group-sep ─► screen-cov ─► no-forbidden ─► isolation ─► coupling
        │              │            │             │               │             │               │            │
        │   ├─ spec/topology/on-disk okunamaz / app≠2 ─────────────────────────────────────► FAIL (malformed)
        │   ├─ app kendi package.json/next/app taşımıyor ──────────────────────────────────► FAIL (missing_app) [A2]
        │   ├─ platform-app non-(platform) group VEYA tenant-app eksik group ───────────────► route_group_mismatch [A3]
        │   ├─ ekran route'u eksik ────────────────────────────────────────────────────────► screen_gap [A4]
        │   ├─ platform-app'te yasak tenant iş verisi route'u ─────────────────────────────► forbidden_route_in_platform [A5]
        │   ├─ platform-app public VEYA realm eşit ────────────────────────────────────────► plane_coupling [A6]
        │   └─ app'ler arası doğrudan import ──────────────────────────────────────────────► cross_app_import [A7]

Kapsam dışı (bilinçli, başka modül SAHİBİ): çalışma-anı oturum/tenant-scope middleware → 13.1.2; tasarım
sistemi/komponent/i18n → 13.1.3; PII maskeleme → 13.1.4; ekran iç implementasyonu → 13.2/13.3/13.4; backend
yetki guard/RLS → 12.2.x. KAYNAK DOĞRULUK; çelişkide SAD §14.4.1 / ADR-011 esastır.

Kullanım:
  frontend_apps_probe.py validate         Statik spec + topology + ON-DISK iki-app iskelet kapısı → çıkış kodu
  frontend_apps_probe.py check <sample>    Topoloji karar motoru: senaryo(lar) → kapı (A1–A12)
  frontend_apps_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  frontend_apps_probe.py schema            Karar sözleşmesini yazdır

Determinizm: topology_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız app/route group/ekran/plane/realm adı).
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SPEC_PATH = os.path.join(HERE, "frontend-apps-spec.json")
TOPOLOGY_PATH = os.path.join(HERE, "config", "deploy-topology.json")

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


# ── on-disk iskelet tarayıcı ───────────────────────────────────────────────────

def list_route_groups(app_dir):
    """app/ altındaki Next.js route group'ları ((parantezli)) döndürür."""
    app_root = os.path.join(REPO, app_dir, "app")
    if not os.path.isdir(app_root):
        return []
    out = []
    for name in sorted(os.listdir(app_root)):
        if name.startswith("(") and name.endswith(")") and os.path.isdir(os.path.join(app_root, name)):
            out.append(name)
    return out


def list_screens(app_dir, route_group):
    """Bir route group altında (herhangi derinlikte) page.tsx içeren ekran (leaf) dizinlerini döndürür.

    Route group'lar URL'e segment EKLEMEZ (Next.js). İki group aynı uygulamada barınınca path çakışmasını
    önlemek için her group bir URL-base segmenti altına yerleşir (ör. (tenant-admin)/admin/<screen>,
    (workspace)/workspace/<screen>); (platform) ise tek group olduğundan düz (platform)/<screen>. Bu yüzden
    ekran taraması derinlikten bağımsızdır: page.tsx tutan leaf dizin = bir ekran."""
    grp = os.path.join(REPO, app_dir, "app", route_group)
    if not os.path.isdir(grp):
        return []
    out = []
    for root, _dirs, files in os.walk(grp):
        if "page.tsx" in files and os.path.abspath(root) != os.path.abspath(grp):
            out.append(os.path.basename(root))
    return sorted(out)


def all_route_segments(app_dir):
    """app/ altındaki TÜM route segment dizin adlarını (recursive) döndürür — yasak-route taraması için."""
    app_root = os.path.join(REPO, app_dir, "app")
    segs = set()
    for root, dirs, _files in os.walk(app_root):
        for d in dirs:
            # route group ((...)) bir segment değildir; segment olarak isim çıkar
            if d.startswith("(") and d.endswith(")"):
                continue
            segs.add(d)
    return segs


def app_is_separate_project(app_dir):
    base = os.path.join(REPO, app_dir)
    has_pkg = os.path.isfile(os.path.join(base, "package.json"))
    has_next = any(os.path.isfile(os.path.join(base, f))
                   for f in ("next.config.mjs", "next.config.js", "next.config.ts"))
    has_app = os.path.isdir(os.path.join(base, "app"))
    return has_pkg and has_next and has_app


def scan_cross_app_import(app_dir, other_pkg_name, other_dir_base):
    """app içindeki .ts/.tsx dosyalarında diğer app'e doğrudan import var mı (A7)."""
    hits = []
    base = os.path.join(REPO, app_dir)
    needles = [other_pkg_name, "../" + other_dir_base, "../../" + other_dir_base]
    for root, _dirs, files in os.walk(base):
        if "node_modules" in root:
            continue
        for f in files:
            if not (f.endswith(".ts") or f.endswith(".tsx")):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                ls = line.strip()
                if ("import" in ls or "require(" in ls) and any(n in ls for n in needles):
                    hits.append(os.path.relpath(p, REPO))
                    break
    return hits


# A8 — frontend'de hardcoded NİHAİ yetki kararı (yalnız UX guard değil). Heuristik yasak token'lar.
FRONTEND_AUTHZ_FORBIDDEN = ["authzDecision = true", "authorize() { return true",
                            "bypassAuth", "GRANT_ACCESS = true"]


def scan_frontend_authz(app_dir):
    hits = []
    base = os.path.join(REPO, app_dir)
    for root, _dirs, files in os.walk(base):
        if "node_modules" in root:
            continue
        for f in files:
            if not (f.endswith(".ts") or f.endswith(".tsx")):
                continue
            p = os.path.join(root, f)
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for tok in FRONTEND_AUTHZ_FORBIDDEN:
                if tok in text:
                    hits.append((os.path.relpath(p, REPO), tok))
    return hits


# A12 — sır/PII taraması (.env.example RHS boş olmalı; spec/topology forbidden değer yok)
SECRET_KEY_HINTS = ("SECRET", "PASSWORD", "TOKEN", "PRIVATE_KEY", "API_KEY", "CONNECTION_STRING")


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
            if val:  # gerçek değer atanmış → sır riski
                hits.append(key.strip())
    return hits


# ── KARAR MOTORU (pure; samples/selftest) ──────────────────────────────────────
# AppTopologyRequest (fixture): {request_id, apps:[{name, route_groups, screens{group:[...]}, network_exposure,
#   auth_realm, origin_class, separate_project(bool), forbidden_routes_present:[...], imports_other_app(bool),
#   frontend_authz(bool)}]}

EXPECTED = {
    "platform-app": {
        "route_groups": ["(platform)"],
        "exposure": "internal_only", "realm": "platform", "origin": "private",
        "screens": {"(platform)": 9},
    },
    "tenant-app": {
        "route_groups": ["(tenant-admin)", "(workspace)"],
        "exposure": "public", "realm": "tenant", "origin": "public",
        "screens": {"(tenant-admin)": 9, "(workspace)": 17},
    },
}

FORBIDDEN_SEGMENTS = {"live-calls", "recordings", "call", "transcript", "transcripts", "qa", "kb",
                      "flows", "prompts", "campaigns", "agents", "builder", "voice", "tools",
                      "org", "users", "numbers", "integrations", "compliance", "quota"}


def evaluate_topology(req):
    """Deterministik, fail-closed iki-app ayrımı kararı. Terminal: PASS|FAIL + ihlal sayaçları."""
    v = {"forbidden_route_in_platform": 0, "plane_coupling": 0, "cross_app_import": 0,
         "missing_app": 0, "route_group_mismatch": 0, "screen_gap": 0,
         "topology_mismatch": 0, "frontend_authz": 0, "secret_or_pii": 0, "malformed": 0}
    notes = []

    apps = {a.get("name"): a for a in req.get("apps", []) if isinstance(a, dict)}
    # A1 malformed / A2 iki app
    if set(apps.keys()) != {"platform-app", "tenant-app"}:
        v["malformed"] += 1
        notes.append("app kümesi {platform-app, tenant-app} değil")
        return {"terminal": "FAIL", "violations": v, "notes": notes, "request_id": req.get("request_id")}

    platform_realm = apps["platform-app"].get("auth_realm")
    tenant_realm = apps["tenant-app"].get("auth_realm")

    for name, exp in EXPECTED.items():
        a = apps[name]
        # A2 — ayrı proje
        if not a.get("separate_project", True):
            v["missing_app"] += 1
            notes.append(f"{name}: ayrı proje değil (package.json/next/app eksik)")
        # A3 — route group ayrımı
        rgs = a.get("route_groups", [])
        if sorted(rgs) != sorted(exp["route_groups"]):
            v["route_group_mismatch"] += 1
            notes.append(f"{name}: route group {rgs} ≠ beklenen {exp['route_groups']}")
        # A4 — ekran kapsamı
        screens = a.get("screens", {})
        for grp, cnt in exp["screens"].items():
            got = len(screens.get(grp, []))
            if got != cnt:
                v["screen_gap"] += 1
                notes.append(f"{name}{grp}: {got} ekran ≠ beklenen {cnt}")
        # A6 — deploy izolasyonu
        if name == "platform-app":
            if a.get("network_exposure") != "internal_only" or a.get("origin_class") != "private":
                v["plane_coupling"] += 1
                notes.append("platform-app internal_only/private değil")
        if name == "tenant-app":
            if a.get("network_exposure") != "public":
                v["plane_coupling"] += 1
                notes.append("tenant-app public değil")
        # A7 — kuplaj
        if a.get("imports_other_app"):
            v["cross_app_import"] += 1
            notes.append(f"{name}: diğer app'i import ediyor")
        # A8 — frontend authz
        if a.get("frontend_authz"):
            v["frontend_authz"] += 1
            notes.append(f"{name}: frontend'de hardcoded yetki kararı")

    # A6 — realm ayrımı
    if platform_realm == tenant_realm or platform_realm != "platform" or tenant_realm != "tenant":
        v["plane_coupling"] += 1
        notes.append("auth realm ayrımı bozuk (platform/tenant)")

    # A5 — ÇEKİRDEK: platform-app'te yasak tenant iş verisi route'u
    pf = apps["platform-app"]
    forbidden_present = set(pf.get("forbidden_routes_present", []))
    # ayrıca beyan edilen route group ekranlarında yasak segment var mı
    declared = set()
    for grp_screens in pf.get("screens", {}).values():
        declared |= set(grp_screens)
    forbidden_present |= (declared & FORBIDDEN_SEGMENTS)
    if forbidden_present:
        v["forbidden_route_in_platform"] += len(forbidden_present)
        notes.append(f"platform-app'te yasak route(lar): {sorted(forbidden_present)}")

    terminal = "PASS" if sum(v.values()) == 0 else "FAIL"
    return {"terminal": terminal, "violations": v, "notes": notes, "request_id": req.get("request_id")}


# ── validate (ON-DISK) ─────────────────────────────────────────────────────────

def cmd_validate():
    spec = load_json(SPEC_PATH)
    topo = load_json(TOPOLOGY_PATH)
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # A1 — iyi biçimli
    chk(spec.get("wbs") == "13.1.1", "A1 spec.wbs=13.1.1")
    chk(topo.get("frozen") is True, "A1 topology frozen")
    chk(topo.get("expected_counts", {}).get("apps") == 2, "A1 expected apps=2")

    # A2 — iki ayrı app projesi (ON-DISK)
    chk(app_is_separate_project("frontend/platform-app"), "A2 platform-app ayrı proje (package.json+next+app)")
    chk(app_is_separate_project("frontend/tenant-app"), "A2 tenant-app ayrı proje (package.json+next+app)")
    # ayrı package adları
    try:
        pf_pkg = load_json(os.path.join(REPO, "frontend/platform-app/package.json")).get("name")
        tn_pkg = load_json(os.path.join(REPO, "frontend/tenant-app/package.json")).get("name")
        chk(pf_pkg and tn_pkg and pf_pkg != tn_pkg, f"A2 ayrı package adı ({pf_pkg} ≠ {tn_pkg})")
    except (OSError, ValueError):
        chk(False, "A2 package.json okunur")

    # A3 — route group ayrımı (ON-DISK)
    pf_rg = list_route_groups("frontend/platform-app")
    tn_rg = list_route_groups("frontend/tenant-app")
    chk(pf_rg == ["(platform)"], f"A3 platform-app route group = (platform) [got {pf_rg}]")
    chk(sorted(tn_rg) == ["(tenant-admin)", "(workspace)"], f"A3 tenant-app route group = (tenant-admin)+(workspace) [got {tn_rg}]")
    chk("(platform)" not in tn_rg, "A3 tenant-app'te (platform) YOK")
    chk("(tenant-admin)" not in pf_rg and "(workspace)" not in pf_rg, "A3 platform-app'te tenant group YOK")

    # A4 — ekran kapsamı (ON-DISK)
    pf_screens = list_screens("frontend/platform-app", "(platform)")
    chk(len(pf_screens) == 9, f"A4 platform (platform) 9 ekran [got {len(pf_screens)}]")
    l1 = list_screens("frontend/tenant-app", "(tenant-admin)")
    l2 = list_screens("frontend/tenant-app", "(workspace)")
    chk(len(l1) == 9, f"A4 tenant (tenant-admin) 9 ekran [got {len(l1)}]")
    chk(len(l2) == 17, f"A4 tenant (workspace) 17 ekran [got {len(l2)}]")
    # beklenen ekran adları topoloji ile eşleşir
    exp_pf = topo["apps"]["platform-app"]["screens"]["(platform)"]
    chk(sorted(pf_screens) == sorted(exp_pf), "A4 platform ekran adları topoloji ile eşleşir")
    exp_l1 = topo["apps"]["tenant-app"]["screens"]["(tenant-admin)"]
    exp_l2 = topo["apps"]["tenant-app"]["screens"]["(workspace)"]
    chk(sorted(l1) == sorted(exp_l1), "A4 L1 ekran adları topoloji ile eşleşir")
    chk(sorted(l2) == sorted(exp_l2), "A4 L2 ekran adları topoloji ile eşleşir")

    # A5 — ÇEKİRDEK: platform-app'te yasak tenant iş verisi route'u YOK (ON-DISK, recursive)
    pf_segs = all_route_segments("frontend/platform-app")
    forbidden = set(topo["forbidden_in_platform_app"]["route_segments"])
    leak = pf_segs & forbidden
    chk(len(leak) == 0, f"A5 platform-app yasak route YOK [sızıntı: {sorted(leak)}]")

    # A6 — deploy izolasyonu (topoloji)
    pa = topo["apps"]["platform-app"]
    ta = topo["apps"]["tenant-app"]
    chk(pa["network_exposure"] == "internal_only" and pa["public"] is False, "A6 platform-app internal_only")
    chk(ta["network_exposure"] == "public" and ta["public"] is True, "A6 tenant-app public")
    chk(pa["auth_realm"] != ta["auth_realm"], "A6 ayrı auth realm")
    chk(pa["origin_class"] == "private" and ta["origin_class"] == "public", "A6 ayrı origin sınıfı")
    chk(topo["deploy_isolation"]["separate_build_pipelines"] is True, "A6 ayrı build hattı")

    # A7 — kuplaj yok (ON-DISK import taraması)
    pf_imports = scan_cross_app_import("frontend/platform-app", "@chanteur/tenant-app", "tenant-app")
    tn_imports = scan_cross_app_import("frontend/tenant-app", "@chanteur/platform-app", "platform-app")
    chk(len(pf_imports) == 0, f"A7 platform-app cross-app import YOK [{pf_imports}]")
    chk(len(tn_imports) == 0, f"A7 tenant-app cross-app import YOK [{tn_imports}]")

    # A8 — frontend'de hardcoded authz YOK
    authz_hits = scan_frontend_authz("frontend/platform-app") + scan_frontend_authz("frontend/tenant-app")
    chk(len(authz_hits) == 0, f"A8 frontend hardcoded authz YOK [{authz_hits}]")

    # A10 — manifest bütünlüğü: on-disk ↔ topoloji sayıları
    cnts = topo["expected_counts"]
    chk(cnts["platform_screens"] == len(pf_screens), "A10 platform ekran sayısı manifest ile eşleşir")
    chk(cnts["tenant_admin_screens"] == len(l1), "A10 L1 ekran sayısı manifest ile eşleşir")
    chk(cnts["workspace_screens"] == len(l2), "A10 L2 ekran sayısı manifest ile eşleşir")
    th = canonical_hash(topo)
    chk(len(th) == 64, f"A10 topology_hash sha256 ({th[:12]}…)")

    # A12 — sır/PII yok (.env.example RHS boş)
    env_pf = scan_env_example_has_value("frontend/platform-app")
    env_tn = scan_env_example_has_value("frontend/tenant-app")
    chk(len(env_pf) == 0 and len(env_tn) == 0, f"A12 .env.example gerçek değer YOK [{env_pf + env_tn}]")

    # spec/topology forbidden token taraması
    blob = json.dumps(_strip_comments(spec), ensure_ascii=False) + json.dumps(_strip_comments(topo), ensure_ascii=False)
    bad = [t for t in ("BEGIN PRIVATE KEY", "password=", "secret=") if t in blob]
    chk(len(bad) == 0, f"A12 spec/topology sır token YOK [{bad}]")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} 🟢" if passed == total else f"\nvalidate: {passed}/{total} 🔴")
    print(f"topology_hash = {th}")
    return 0 if passed == total else 1


# ── check (samples) ─────────────────────────────────────────────────────────────

def cmd_check(path):
    files = []
    if os.path.isdir(path):
        files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".json")]
    else:
        files = [path]
    if not files:
        print("check: örnek bulunamadı")
        return 1
    fails = 0
    for f in files:
        req = load_json(f)
        expect = req.get("expect", "PASS")
        res = evaluate_topology(req)
        ok = res["terminal"] == expect
        mark = "🟢" if ok else "🔴"
        name = os.path.basename(f)
        viol = {k: n for k, n in res["violations"].items() if n}
        print(f"  {mark} {name}: terminal={res['terminal']} beklenen={expect} ihlal={viol or '—'}")
        if not ok:
            fails += 1
            for nt in res["notes"]:
                print(f"        · {nt}")
    print(f"\ncheck: {len(files)-fails}/{len(files)} 🟢" if fails == 0 else f"\ncheck: {len(files)-fails}/{len(files)} 🔴")
    return 0 if fails == 0 else 1


# ── selftest ─────────────────────────────────────────────────────────────────

def _base_ok():
    return {
        "request_id": "st-ok",
        "apps": [
            {"name": "platform-app", "separate_project": True, "route_groups": ["(platform)"],
             "screens": {"(platform)": ["overview", "tenants", "resources", "providers", "billing",
                                         "policy", "audit", "releases", "incidents"]},
             "network_exposure": "internal_only", "auth_realm": "platform", "origin_class": "private",
             "imports_other_app": False, "frontend_authz": False, "forbidden_routes_present": []},
            {"name": "tenant-app", "separate_project": True, "route_groups": ["(tenant-admin)", "(workspace)"],
             "screens": {"(tenant-admin)": ["dashboard", "org", "users", "numbers", "integrations",
                                            "compliance", "billing", "audit", "quota"],
                         "(workspace)": ["dashboard", "live-calls", "agents", "builder", "flows", "prompts",
                                         "voice", "kb", "tools", "campaigns", "recordings", "call", "qa",
                                         "analytics", "cost", "test", "versions"]},
             "network_exposure": "public", "auth_realm": "tenant", "origin_class": "public",
             "imports_other_app": False, "frontend_authz": False},
        ],
    }


def cmd_selftest():
    import copy
    results = []

    def expect(label, req, want_terminal, want_counter=None):
        r = evaluate_topology(req)
        ok = r["terminal"] == want_terminal
        if want_counter:
            ok = ok and r["violations"].get(want_counter, 0) > 0
        results.append((ok, label))

    # 1 — temel geçer
    expect("01 baseline PASS", _base_ok(), "PASS")

    # 2 — determinizm (aynı girdi aynı çıktı)
    r1 = evaluate_topology(_base_ok())
    r2 = evaluate_topology(_base_ok())
    results.append((r1 == r2, "02 determinizm (aynı girdi → aynı çıktı)"))

    # 3 — A5 ÇEKİRDEK: platform-app'te yasak route → FAIL
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["forbidden_routes_present"] = ["live-calls"]
    expect("03 A5 platform-app'te live-calls → FAIL", r, "FAIL", "forbidden_route_in_platform")

    # 4 — A5: yasak segment ekran listesine sızdırılmış
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["screens"]["(platform)"].append("recordings")
    expect("04 A5 platform ekranında recordings → FAIL", r, "FAIL", "forbidden_route_in_platform")

    # 5 — A3: platform-app yanlış route group
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["route_groups"] = ["(workspace)"]
    expect("05 A3 platform-app (workspace) → FAIL", r, "FAIL", "route_group_mismatch")

    # 6 — A3: tenant-app eksik group
    r = copy.deepcopy(_base_ok())
    r["apps"][1]["route_groups"] = ["(tenant-admin)"]
    expect("06 A3 tenant-app eksik (workspace) → FAIL", r, "FAIL", "route_group_mismatch")

    # 7 — A6: platform-app public (plane coupling)
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["network_exposure"] = "public"
    expect("07 A6 platform-app public → FAIL", r, "FAIL", "plane_coupling")

    # 8 — A6: realm eşit
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["auth_realm"] = "tenant"
    expect("08 A6 realm eşit → FAIL", r, "FAIL", "plane_coupling")

    # 9 — A7: cross-app import
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["imports_other_app"] = True
    expect("09 A7 cross-app import → FAIL", r, "FAIL", "cross_app_import")

    # 10 — A4: ekran eksik
    r = copy.deepcopy(_base_ok())
    r["apps"][1]["screens"]["(workspace)"].pop()
    expect("10 A4 L2 16 ekran → FAIL", r, "FAIL", "screen_gap")

    # 11 — A2: ayrı proje değil
    r = copy.deepcopy(_base_ok())
    r["apps"][0]["separate_project"] = False
    expect("11 A2 platform-app ayrı proje değil → FAIL", r, "FAIL", "missing_app")

    # 12 — A8: frontend authz
    r = copy.deepcopy(_base_ok())
    r["apps"][1]["frontend_authz"] = True
    expect("12 A8 frontend hardcoded authz → FAIL", r, "FAIL", "frontend_authz")

    # 13 — A1 malformed: tek app
    r = {"request_id": "st-1app", "apps": [_base_ok()["apps"][0]]}
    expect("13 A1 tek app → FAIL (malformed)", r, "FAIL", "malformed")

    # 14 — fail-closed: boş istek
    expect("14 fail-closed boş istek → FAIL", {"request_id": "empty", "apps": []}, "FAIL", "malformed")

    # 15 — topology_hash determinizm
    h1 = canonical_hash(load_json(TOPOLOGY_PATH))
    h2 = canonical_hash(load_json(TOPOLOGY_PATH))
    results.append((h1 == h2 and len(h1) == 64, "15 topology_hash deterministik sha256"))

    passed = sum(1 for ok, _ in results if ok)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{len(results)} 🟢" if passed == len(results) else f"\nselftest: {passed}/{len(results)} 🔴")
    return 0 if passed == len(results) else 1


# ── schema ───────────────────────────────────────────────────────────────────

def cmd_schema():
    print(json.dumps({
        "wbs": "13.1.1",
        "input": "AppTopologyRequest{request_id, apps:[{name, separate_project, route_groups, "
                 "screens{group:[...]}, network_exposure, auth_realm, origin_class, imports_other_app, "
                 "frontend_authz, forbidden_routes_present}], expect}",
        "output": "{terminal: PASS|FAIL, violations{...}, notes, request_id}",
        "gates": ["forbidden_route_in_platform(A5)", "plane_coupling(A6)", "cross_app_import(A7)",
                  "missing_app(A2)", "route_group_mismatch(A3)", "screen_gap(A4)", "topology_mismatch(A10)",
                  "frontend_authz(A8)", "secret_or_pii(A12)"],
        "default": "FAIL (fail-closed)",
        "trace": "SAD §14.4.1, ADR-011, FR-IAM-008",
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
        if len(sys.argv) < 3:
            print("kullanım: frontend_apps_probe.py check <sample.json|dizin>")
            return 2
        return cmd_check(sys.argv[2])
    if cmd == "selftest":
        return cmd_selftest()
    if cmd == "schema":
        return cmd_schema()
    print(f"bilinmeyen komut: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
