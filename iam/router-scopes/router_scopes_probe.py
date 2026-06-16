#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.2.2 — L0/L1/L2 ayrı router ağaçları + ayrı OAuth scope referans probe.

12. workstream'in (IAM & Erişim) ROUTER/SCOPE TOPOLOJİSİ modülü ve F1-Must yeteneği. SAD §14.4.2 ('Ayrı
router/scopes + ayrı deploy: L0 endpoint'leri ayrı bir servis (Platform Control Plane, internal-only) ve ayrı
auth realm'de; L1/L2 endpoint'leri Tenant Application Plane'de ayrı router ağaçları ve OAuth scope'larında
tanımlanır — ADR-011') + API.md §2 ('S2/S3/S4 aynı Tenant Application Plane'de fakat ayrı router ağaçları +
ayrı OAuth scope ile ayrışır')'ı sahiplenir. 12.2.1 backend-guard'ın PER-REQUEST üç-boyutlu kararının
ÖNÜNDEKİ YAPISAL/DAĞITIMSAL katmandır: her panel (L0/L1/L2) AYRI bir router ağacına + AYRI bir OAuth scope'a
(router-seviyesi dependency, handler'dan ÖNCE) + bir deploy DÜZLEMİNE bağlanır.

  RouterScenario ─malformed─► MOUNT integrity ─► [topoloji bütünlüğü] ─► REQUEST-time routing ─► karar
        │            │              │                      │                       │
        │  ├─ request_id/mount eksik | mounted_tree yok ────────────────────────► MISCONFIG (malformed_topology)
        │  ├─ endpoint paneli ≠ mount edilen ağaç paneli ──────────────────────► MISCONFIG (panel_tree_mismatch) [S2]
        │  ├─ aynı endpoint >1 ağaçta ─────────────────────────────────────────► MISCONFIG (multi_tree_mount)   [S2]
        │  ├─ doğrulanmış kimlik yok ──────────────────────────────────────────► REJECT (unauthenticated)  401
        │  ├─ istek yanlış düzlem/origin'de geldi (L0 ⟂ tenant) ───────────────► REJECT (wrong_plane_origin)    [S3]
        │  ├─ token realm ≠ ağaç realm ────────────────────────────────────────► REJECT (router_realm_mismatch) [S5]
        │  ├─ token OAuth scope ≠ ağaç scope ──────────────────────────────────► REJECT (router_scope_mismatch) [S4]
        │  └─ hepsi geçer ─────────────────────────────────────────────────────► ADMIT → DEVREDİLİR 12.2.1     [S8]

ÇEKİRDEK: (1) S2 AYRI ROUTER AĞAÇLARI (FR-IAM-008/ADR-011 ÇEKİRDEK) — her endpoint TAM BİR panel ağacına mount
edilir; endpoint paneli = ağaç paneli; cross-panel mount YOK; bir endpoint >1 ağaçta olamaz; tree_mount_violation=0.
(2) S3 DÜZLEM/DEPLOY AYRIMI (ADR-011 ÇEKİRDEK) — L0 ağacı AYRI internal-only Platform Control Plane'de (ayrı
origin/servis/realm); L1/L2 ağaçları public Tenant Application Plane'de; L0 ağacı tenant düzlemine (veya tersi)
ASLA mount edilemez (blast-radius); plane_violation=0. (3) S4 AYRI OAuth SCOPE (ÇEKİRDEK) — her ağaç KENDİ
ANLAŞMAZ (disjoint) OAuth scope'unu (panel:L0/L1/L2) router-seviyesi dependency ile (handler'dan ÖNCE) zorlar;
token scope = ağaç scope değilse REJECT; scope'lar çakışamaz; scope_violation=0. (4) S6 12.2.1 İLE TUTARLILIK —
topoloji oauth_scope/realm değerleri guard-model.json (panel_oauth_scope/panel_realm) ile birebir; topoloji
scope/realm'i YENİDEN TANIMLAMAZ (tek kaynak doğruluk); consistency_violation=0. (5) S8 DEVREDİLİR — router
admission GEREKLİ ama YETERLİ DEĞİL; ADMIT edilen istek 12.2.1 backend-guard'ın panel+rol+tenant kapısına
DEVREDİLİR; router tek başına endpoint erişimi VERMEZ; delegation_violation=0. Motor DETERMİNİSTİK FAIL-CLOSED
(Date.now/random YOK; model_hash sha256). Her karar terminal (S1) + kanıt (S9) + model bütünlük manifesti (S10);
metrik düşük-kardinalite + ham PII yok (S11); model/spec/sample ham içerik/PII/credential tutmaz (S12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): per-request panel+rol+tenant kararı → 12.2.1 backend-guard (DEVREDİLİR;
bu modül router/scope TOPOLOJİSİNİ zorlar); rol→permission-key bundle → 12.1.1; rol+scope yetki kararı → 12.1.3;
PostgreSQL RLS politikaları → 12.2.3; L0 iş verisi repository bağımsızlığı → 12.2.4; break-glass → 12.3.x; WORM
audit → 12.1.8. KAYNAK DOĞRULUK; çelişkide SAD §14.4.2 / ADR-011 esastır.

Kullanım:
  router_scopes_probe.py validate          Statik topoloji + spec + 12.2.1 guard-model tutarlılığı → çıkış kodu
  router_scopes_probe.py check <sample>     Router/scope topoloji motoru: senaryo(lar)ı çalıştır → kapı (S1–S12)
  router_scopes_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  router_scopes_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız panel/realm/scope enum + prefix + origin +
yapısal kimlik; FR-TST-008).
"""
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "router-scopes-spec.json")
TOPOLOGY_PATH = os.path.join(HERE, "config", "router-topology.json")
GUARD_MODEL_PATH = os.path.join(HERE, "..", "backend-guard", "config", "guard-model.json")
GUARD_PROBE_PATH = os.path.join(HERE, "..", "backend-guard", "backend_guard_probe.py")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["ADMIT", "REJECT", "MISCONFIG"]
TERMINAL = {"ADMIT", "REJECT", "MISCONFIG"}
ADMIT_TERMINALS = {"ADMIT"}
RULES = ["separate_router_trees", "plane_separation", "separate_oauth_scope", "router_realm",
         "guard_model_consistency", "scope_dependency_required", "delegate_to_guard"]
REJECT_REASONS = ["unauthenticated", "wrong_plane_origin", "router_realm_mismatch", "router_scope_mismatch"]
MISCONFIG_REASONS = ["malformed_topology", "panel_tree_mismatch", "multi_tree_mount", "plane_misplacement",
                     "scope_collision", "missing_scope_dependency", "consistency_mismatch"]
INVARIANT_IDS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12"]
REALMS = {"platform", "tenant"}
PANELS = {"L0", "L1", "L2"}

# Degrade (inject) — DOĞRU mount/düzlem/scope/realm/devir davranışını bozan müdahaleler.
INJECTIONS = {"cross_panel_mount", "plane_collapse", "scope_reuse", "scope_bypass", "realm_cross",
              "scope_dep_drop", "consistency_break", "admit_sufficient", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "tree_mount_violation", "plane_violation", "scope_violation", "realm_violation",
    "consistency_violation", "missing_scope_dependency", "delegation_violation",
    "model_tampered", "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (S12; 12.1.x/12.2.1 deseniyle) — ham içerik/PII/sır yasak; panel/scope/prefix/origin beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|panel:l[012]|/platform/v1|/admin/v1|/ops/v1|/public/v1|bearer'ı|oidc_bearer)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + panel/scope/prefix/origin enum eler (12.2.1 deseni)."""
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


def _topology():
    return _load(TOPOLOGY_PATH)


def _guard_model():
    """12.2.1 guard-model.json (panel_realm + panel_oauth_scope — TEK KAYNAK; tutarlılık S6)."""
    return _load(GUARD_MODEL_PATH)


_BG_CACHE = {}


def _guard_module():
    """12.2.1 backend-guard probe'unu modül olarak yükle (router admission → DEVİR ispatı, S8)."""
    if "m" not in _BG_CACHE:
        spec = importlib.util.spec_from_file_location("backend_guard_probe", GUARD_PROBE_PATH)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _BG_CACHE["m"] = m
    return _BG_CACHE["m"]


def _working_topology(topo, inject):
    """Degrade müdahaleleri DOĞRU topolojinin bir KOPYASINI bozar (frozen orijinal değişmez)."""
    t = json.loads(json.dumps(topo))
    trees = t["router_trees"]
    if "consistency_break" in inject:
        trees["L2"]["oauth_scope"] = "panel:L1"                 # guard-model'den sapma (tek-kaynak ihlali)
    if "scope_reuse" in inject:
        trees["L2"]["oauth_scope"] = trees["L1"]["oauth_scope"]  # iki ağaç aynı scope (çakışma)
    if "scope_dep_drop" in inject:
        trees["L2"]["router_scope_dependency"] = False           # router-seviyesi scope dependency düşürüldü
    if "plane_collapse" in inject:
        trees["L0"]["plane"] = "tenant_application_plane"        # L0'ı tenant düzlemine indir (tek deploy)
    return t


def build(sample, spec, inject=None, topo=None, guard_model=None):
    """Tek router/scope senaryosunu yürüt → RouterDecision + ihlal sayaçları.

    Motor DOĞRU mount/düzlem/scope/realm/devir davranışını hesaplar; inject (degrade) doğru davranışı bozar ve
    eşleşen ihlal sayacını artırır (12.2.1 inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    topo_frozen = topo if topo is not None else _topology()
    guard_model = guard_model if guard_model is not None else _guard_model()
    t = _working_topology(topo_frozen, inject)
    trees = t["router_trees"]
    planes = t["planes"]

    request_id = sample.get("request_id")
    mounts = list(sample.get("mounts", []) or [])
    request = dict(sample.get("request", {}) or {})

    v = {k: 0 for k in VIOLATION_KEYS}
    terminal = None
    misconfig_reason = None
    reject_reason = None
    admitted = False
    http_status = None
    delegated_to = None

    # ── S10 model bütünlük manifesti (frozen topoloji + 12.2.1 guard-model panel_realm/panel_oauth_scope) ──
    canonical = {
        "topology": {k: topo_frozen.get(k) for k in (
            "frozen", "fail_closed", "scope_disjoint", "planes", "router_trees", "http_status")},
        "guard_panel_realm": guard_model.get("panel_realm"),
        "guard_panel_oauth_scope": guard_model.get("panel_oauth_scope"),
    }
    model_hash = _canon_hash(canonical)
    if "model_tamper" in inject:
        tampered = json.loads(json.dumps(canonical))
        tampered["topology"]["router_trees"]["L0"]["oauth_scope"] = "panel:L1"  # L0 scope tahrifi
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed → MISCONFIG) ──
    malformed = (not request_id or not isinstance(mounts, list) or "router_trees" not in t
                 or any((not m.get("mounted_tree")) or (not m.get("declared_panel")) for m in mounts))

    if malformed:
        terminal, misconfig_reason = "MISCONFIG", "malformed_topology"
    else:
        # ── S2 MOUNT bütünlüğü (sample mounts üzerinde gerçek dedektör; cross_panel_mount degrade'i bastırır) ──
        seen = {}
        for m in mounts:
            ep = m.get("endpoint")
            tree = m.get("mounted_tree")
            panel = m.get("declared_panel")
            if tree not in trees:
                terminal, misconfig_reason = "MISCONFIG", "malformed_topology"
                break
            if ep is not None:
                if ep in seen and seen[ep] != tree:
                    terminal, misconfig_reason = "MISCONFIG", "multi_tree_mount"
                    break
                seen[ep] = tree
            if panel != trees[tree]["panel"]:
                if "cross_panel_mount" in inject:
                    v["tree_mount_violation"] += 1     # degrade: yanlış-panel mount kabul (insecure)
                else:
                    terminal, misconfig_reason = "MISCONFIG", "panel_tree_mismatch"
                    break

        # ── S3 düzlem ayrımı (inject-güdümlü sayaç; statik garanti validate'te) ──
        if terminal is None and "plane_collapse" in inject:
            v["plane_violation"] += 1                  # L0 ağacı tenant düzlemine indirildi (blast-radius)

        # ── S4 ayrı/anlaşmaz OAuth scope (inject-güdümlü; statik garanti validate'te) ──
        if terminal is None and "scope_reuse" in inject:
            v["scope_violation"] += 1                  # iki ağaç aynı OAuth scope'u paylaşır (çakışma)

        # ── S7 router-seviyesi scope dependency zorunlu (inject-güdümlü; statik garanti validate'te) ──
        if terminal is None and "scope_dep_drop" in inject:
            v["missing_scope_dependency"] += 1         # router-seviyesi scope dependency düşürüldü

        # ── S6 12.2.1 guard-model ile tutarlılık (inject-güdümlü; statik garanti validate'te) ──
        if terminal is None and "consistency_break" in inject:
            v["consistency_violation"] += 1            # topoloji scope'u guard-model'den sapar (tek-kaynak ihlali)

        # ── REQUEST-time routing (MISCONFIG yoksa) ──
        if terminal is None and request:
            authed = request.get("authenticated", True)
            target = request.get("target_tree")
            token = dict(request.get("token", {}) or {})
            tok_realm = token.get("realm")
            tok_scope = token.get("panel_scope")
            arrived_plane = request.get("arrived_plane")
            arrived_origin = request.get("arrived_origin")

            if target not in trees:
                terminal, misconfig_reason = "MISCONFIG", "malformed_topology"
            elif not authed:
                terminal, reject_reason = "REJECT", "unauthenticated"
            else:
                tree = trees[target]
                want_plane = tree["plane"]
                want_origin = planes[want_plane]["origin"]
                want_realm = tree["realm"]
                want_scope = tree["oauth_scope"]

                # ── S3 request-time düzlem/origin (L0 ⟂ tenant) ──
                plane_ok = (arrived_plane == want_plane
                            and (arrived_origin is None or arrived_origin == want_origin))

                # ── S5 router-seviyesi realm ──
                realm_ok = (tok_realm == want_realm)
                if "realm_cross" in inject and not realm_ok:
                    v["realm_violation"] += 1
                    realm_ok = True                    # degrade: yanlış realm token'ı kabul

                # ── S4 router-seviyesi OAuth scope ──
                scope_ok = (tok_scope == want_scope)
                if "scope_bypass" in inject and not scope_ok:
                    v["scope_violation"] += 1
                    scope_ok = True                    # degrade: yanlış/eksik panel scope'unu kabul

                if not plane_ok:
                    terminal, reject_reason = "REJECT", "wrong_plane_origin"
                elif not realm_ok:
                    terminal, reject_reason = "REJECT", "router_realm_mismatch"
                elif not scope_ok:
                    terminal, reject_reason = "REJECT", "router_scope_mismatch"
                else:
                    terminal, admitted = "ADMIT", True
                    delegated_to = "12.2.1 backend-guard (panel+rol+tenant)"  # S8 GEREKLİ ama YETERLİ DEĞİL
                    if "admit_sufficient" in inject:
                        v["delegation_violation"] += 1  # degrade: router admission'ı YETERLİ say (12.2.1 atlanır)

        if terminal is None:
            # routable istek yok → fail-closed (deploy/senaryo eksik)
            terminal, misconfig_reason = "MISCONFIG", "malformed_topology"

    # ── HTTP durum kodu ──
    hs = topo_frozen["http_status"]
    if terminal == "ADMIT":
        http_status = hs["ADMIT"]
    elif terminal == "REJECT":
        http_status = hs["unauthenticated"] if reject_reason == "unauthenticated" else hs["REJECT"]
    elif terminal == "MISCONFIG":
        http_status = hs["misconfig"]

    # ── S1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (S9) ──
    evidence = _evidence(request_id, mounts, request, terminal, misconfig_reason, reject_reason,
                         admitted, http_status, delegated_to, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, misconfig_reason, reject_reason, admitted, http_status,
                 mounts, request, delegated_to, model_hash, evidence)


def _evidence(request_id, mounts, request, terminal, misconfig_reason, reject_reason, admitted,
              http_status, delegated_to, model_hash):
    return {
        "request_id": request_id,
        "mounts": [{"endpoint": m.get("endpoint"), "declared_panel": m.get("declared_panel"),
                    "mounted_tree": m.get("mounted_tree")} for m in mounts],
        "target_tree": request.get("target_tree"),
        "arrived_plane": request.get("arrived_plane"),
        "token_realm": (request.get("token") or {}).get("realm"),
        "token_scope": (request.get("token") or {}).get("panel_scope"),
        "terminal": terminal,
        "misconfig_reason": misconfig_reason,
        "reject_reason": reject_reason,
        "admitted": admitted,
        "http_status": http_status,
        "delegated_to": delegated_to,
        "router_admission": "necessary_not_sufficient" if terminal == "ADMIT" else None,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, misconfig_reason, reject_reason, admitted, http_status, mounts, request,
          delegated_to, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "misconfig_reason": misconfig_reason,
        "reject_reason": reject_reason,
        "admitted": admitted,
        "http_status": http_status,
        "target_tree": request.get("target_tree"),
        "arrived_plane": request.get("arrived_plane"),
        "delegated_to": delegated_to,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "tree_mount_violation": "max_tree_mount_violation",
        "plane_violation": "max_plane_violation",
        "scope_violation": "max_scope_violation",
        "realm_violation": "max_realm_violation",
        "consistency_violation": "max_consistency_violation",
        "missing_scope_dependency": "max_missing_scope_dependency",
        "delegation_violation": "max_delegation_violation",
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
        for key in ("terminal", "misconfig_reason", "reject_reason", "admitted", "http_status"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s admitted=%s http=%s tree=%s reason=%s/%s devir=%s"
              % (res["terminal"], res["admitted"], res["http_status"], res["target_tree"],
                 res["misconfig_reason"], res["reject_reason"], res["delegated_to"]))
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
              "reject_reasons", "misconfig_reasons", "outcomes", "model", "enforcement", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.2.2", spec.get("wbs") == "12.2.2")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement enforce_at=router", "router" in spec.get("placement", {}).get("enforce_at", ""))

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-008 izlenir (panel ayrımı — ÇEKİRDEK)", "FR-IAM-008" in tr.get("fr", []))
    chk("FR-TEN-002 izlenir (tenant izolasyonu)", "FR-TEN-002" in tr.get("fr", []))
    chk("SAD §14.4.2 ayrı router/scope izlenir", any("§14.4.2" in s for s in tr.get("sad", [])))
    chk("ADR-011 izlenir (iki düzlemli panel dağıtımı)",
        any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("12.2.1 backend-guard DEVREDİLİR/TÜKETİLİR (consumes)",
        any("12.2.1" in s for s in tr.get("consumes", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (trees/plane/scope/realm/consistency/scope_dep/delegate)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed→mount→topoloji→request fail-closed",
        rz.get("evaluation") == "malformed_then_mount_then_topology_then_request_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=MISCONFIG (fail-closed)", dec.get("default") == "MISCONFIG")
    chk("fail_safe no access", "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar ADMIT/REJECT/MISCONFIG", set(oc.get("list", [])) == set(OUTCOMES))
    rr = set(spec["reject_reasons"].get("list", []))
    chk("reject_reason taksonomisi tam", rr == set(REJECT_REASONS))
    mr = set(spec["misconfig_reasons"].get("list", []))
    chk("misconfig_reason taksonomisi tam", mr == set(MISCONFIG_REASONS))

    # 6) Enforcement — trees + scope + plane + devir
    en = spec["enforcement"]
    chk("mount_gate panel=ağaç paneli", "panel" in en.get("mount_gate", ""))
    chk("scope_gate router-seviyesi OAuth scope (handler'dan önce)",
        "scope" in en.get("scope_gate", "") and "router" in en.get("scope_gate", ""))
    chk("plane_gate L0 ⟂ tenant (internal-only)", "L0" in en.get("plane_gate", ""))
    chk("delegates_to 12.2.1 (admission gerekli ama yeterli değil)",
        "12.2.1" in en.get("delegates_to", "") and "yeterli" in en.get("delegates_to", "").lower())
    chk("enforce_at router", "router" in en.get("enforce_at", ""))

    # 7) Model alanları
    md = spec["model"]
    chk("panels L0/L1/L2", set(md.get("panels", [])) == PANELS)
    chk("oauth_scope panel:L0/L1/L2 anlaşmaz", set(md.get("panel_oauth_scope", {}).values()) == {"panel:L0", "panel:L1", "panel:L2"})
    chk("scope_disjoint=true", md.get("scope_disjoint") is True)
    chk("guard_model_ref 12.2.1", "12.2.1" in md.get("guard_model_ref", ""))

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_tree_mount_violation", "max_plane_violation", "max_scope_violation",
               "max_realm_violation", "max_consistency_violation", "max_missing_scope_dependency",
               "max_delegation_violation", "max_model_tampered", "max_missing_evidence",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("router_admission_total metrik", "router_admission_total" in obs.get("metrics", []))
    chk("router_topology_violation_total metrik (alarm)",
        "router_topology_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id YÜKSEK kard (label değil)", "request_id" in hi and "request_id" not in lo)
    chk("result/tree/plane DÜŞÜK kard (label uygun)",
        "result" in lo and "tree" in lo and "plane" in lo)
    chk("alarm tree_mount/plane/scope ≤2dk",
        any(x in obs.get("alarm", "") for x in ("tree_mount", "plane", "scope")))

    # 10) İnvariant'lar S1–S12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar S1–S12 tam", inv_ids == INVARIANT_IDS)

    # 11) Topoloji dosyası + içsel tutarlılık
    tp_ok = os.path.exists(TOPOLOGY_PATH)
    chk("config/router-topology.json var", tp_ok)
    topo = None
    if tp_ok:
        topo = _topology()
        chk("topoloji frozen=true", topo.get("frozen") is True)
        chk("topoloji fail_closed=true", topo.get("fail_closed") is True)
        chk("topoloji enforce_at=router", "router" in topo.get("enforce_at", ""))
        chk("topoloji scope_disjoint=true", topo.get("scope_disjoint") is True)
        trees = topo.get("router_trees", {})
        tree_keys = [k for k in trees if not k.startswith("$")]
        chk("üç router ağacı L0/L1/L2", set(tree_keys) == PANELS)
        # ayrı prefix
        prefixes = [trees[k]["prefix"] for k in tree_keys]
        chk("router prefix'leri ayrı (her panel ayrı base path)", len(set(prefixes)) == len(prefixes))
        # ayrı/anlaşmaz scope
        scopes = [trees[k]["oauth_scope"] for k in tree_keys]
        chk("OAuth scope'lar anlaşmaz (disjoint)", len(set(scopes)) == len(scopes))
        # router-seviyesi scope dependency her ağaçta
        chk("her ağaç router_scope_dependency=true",
            all(trees[k].get("router_scope_dependency") is True for k in tree_keys))
        # düzlemler
        planes = topo.get("planes", {})
        chk("Platform Control Plane internal-only (L0)",
            planes.get("platform_control_plane", {}).get("internal_only") is True
            and planes["platform_control_plane"].get("hosts_panels") == ["L0"])
        chk("Tenant Application Plane public (L1+L2)",
            planes.get("tenant_application_plane", {}).get("public") is True
            and set(planes["tenant_application_plane"].get("hosts_panels", [])) == {"L1", "L2"})
        chk("L0 ağacı platform_control_plane'de", trees.get("L0", {}).get("plane") == "platform_control_plane")
        chk("L1/L2 ağaçları tenant_application_plane'de",
            trees.get("L1", {}).get("plane") == "tenant_application_plane"
            and trees.get("L2", {}).get("plane") == "tenant_application_plane")

    # 12) S6 — 12.2.1 guard-model ile TUTARLILIK (tek kaynak doğruluk)
    gm_ok = os.path.exists(GUARD_MODEL_PATH)
    chk("12.2.1 ../backend-guard/config/guard-model.json var (TÜKETİLİR)", gm_ok)
    if gm_ok and topo is not None:
        gm = _guard_model()
        pscope = gm.get("panel_oauth_scope", {})
        prealm = gm.get("panel_realm", {})
        trees = topo.get("router_trees", {})
        chk("topoloji oauth_scope = guard-model panel_oauth_scope (S6)",
            all(trees.get(k, {}).get("oauth_scope") == pscope.get(k) for k in PANELS))
        chk("topoloji realm = guard-model panel_realm (S6)",
            all(trees.get(k, {}).get("realm") == prealm.get(k) for k in PANELS))

    # 13) S8 — 12.2.1 backend-guard erişilebilir (DEVİR ispatı)
    bg_ok = os.path.exists(GUARD_PROBE_PATH)
    chk("12.2.1 ../backend-guard/backend_guard_probe.py var (DEVREDİLİR)", bg_ok)
    if bg_ok:
        try:
            bg = _guard_module()
            d = bg.build({
                "request_id": "req-1", "tenant_id": "t-acme", "actor_user_id": "u-1",
                "actor_realm": "tenant", "authenticated": True,
                "token": {"realm": "tenant", "panel_scope": "panel:L2"},
                "endpoint": {"panel": "L2", "required_permission": "calls:read"},
                "assignments": [{"role": "operations_manager", "scope": {"brand": ["brand-x"]}}],
                "ownership": "other",
                "resource": {"tenant_id": "t-acme", "brand": "brand-x", "campaign": "camp-1"}},
                bg._load(bg.SPEC_PATH))
            chk("12.2.1 devir çağrısı terminal döndürür (router admission sonrası — canlı kompozisyon)",
                d.get("terminal") in {"ALLOW", "DENY", "BLOCK"})
        except Exception as e:  # noqa
            chk("12.2.1 devir çağrısı terminal döndürür (router admission sonrası — canlı kompozisyon)", False, str(e))

    # 14) Sır/PII tarayıcı — spec + topoloji + samples
    scan_files = [SPEC_PATH, TOPOLOGY_PATH] + (
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

    # 15) Samples — ≥1 pass + ≥1 fail
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

    def scn(**kw):
        # Varsayılan: L2 endpoint L2 ağacına mount; tenant düzleminde panel:L2 token → ADMIT (12.2.1'e devir).
        d = {
            "request_id": "req-1",
            "mounts": [{"endpoint": "GET /ops/v1/calls/{id}", "declared_panel": "L2", "mounted_tree": "L2"}],
            "request": {
                "target_tree": "L2", "arrived_plane": "tenant_application_plane",
                "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                "token": {"realm": "tenant", "panel_scope": "panel:L2"},
            },
        }
        d.update(kw)
        return d

    # 1) happy — ADMIT (devir)
    r = build(scn(), spec)
    case("happy: ADMIT", r["terminal"] == "ADMIT")
    case("happy: admitted=true", r["admitted"] is True)
    case("happy: http=200", r["http_status"] == 200)
    case("happy: 12.2.1'e devredilir (necessary_not_sufficient)",
         "12.2.1" in (r["delegated_to"] or "") and r["evidence"]["router_admission"] == "necessary_not_sufficient")
    case("happy: model_hash var (S10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm
    r1, r2 = build(scn(), spec), build(scn(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) L0 platform ADMIT (platform düzlemi + panel:L0)
    r = build(scn(mounts=[{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L0"}],
                  request={"target_tree": "L0", "arrived_plane": "platform_control_plane",
                           "arrived_origin": "platform.internal.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "platform", "panel_scope": "panel:L0"}}), spec)
    case("L0-platform: ADMIT", r["terminal"] == "ADMIT")

    # 4) L1 admin ADMIT
    r = build(scn(mounts=[{"endpoint": "POST /admin/v1/role-assignments", "declared_panel": "L1", "mounted_tree": "L1"}],
                  request={"target_tree": "L1", "arrived_plane": "tenant_application_plane",
                           "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "tenant", "panel_scope": "panel:L1"}}), spec)
    case("L1-admin: ADMIT", r["terminal"] == "ADMIT")

    # 5) S4 router OAuth scope mismatch — L2 ağacına panel:L1 token → REJECT (meşru)
    r = build(scn(request={"target_tree": "L2", "arrived_plane": "tenant_application_plane",
                           "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "tenant", "panel_scope": "panel:L1"}}), spec)
    case("scope-mismatch: REJECT router_scope_mismatch", r["terminal"] == "REJECT" and r["reject_reason"] == "router_scope_mismatch")
    case("scope-mismatch: http=403 + ihlal yok (meşru)", r["http_status"] == 403 and all(x == 0 for x in r["violations"].values()))

    # 6) S5 router realm mismatch — L0 ağacına tenant realm token → REJECT
    r = build(scn(mounts=[{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L0"}],
                  request={"target_tree": "L0", "arrived_plane": "platform_control_plane",
                           "arrived_origin": "platform.internal.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "tenant", "panel_scope": "panel:L0"}}), spec)
    case("realm-mismatch: REJECT router_realm_mismatch", r["terminal"] == "REJECT" and r["reject_reason"] == "router_realm_mismatch")

    # 7) S3 wrong plane/origin — L0 isteği tenant public düzleminde → REJECT wrong_plane_origin
    r = build(scn(mounts=[{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L0"}],
                  request={"target_tree": "L0", "arrived_plane": "tenant_application_plane",
                           "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "platform", "panel_scope": "panel:L0"}}), spec)
    case("wrong-plane: REJECT wrong_plane_origin", r["terminal"] == "REJECT" and r["reject_reason"] == "wrong_plane_origin")

    # 8) unauthenticated → REJECT 401
    r = build(scn(request={"target_tree": "L2", "arrived_plane": "tenant_application_plane",
                           "arrived_origin": "api.rmcvoice.io", "authenticated": False,
                           "token": {}}), spec)
    case("unauth: REJECT unauthenticated http 401", r["terminal"] == "REJECT" and r["reject_reason"] == "unauthenticated" and r["http_status"] == 401)

    # 9) S2 legit MISCONFIG — endpoint paneli ≠ ağaç paneli (deploy yakalanır, meşru)
    r = build(scn(mounts=[{"endpoint": "GET /ops/v1/calls/{id}", "declared_panel": "L0", "mounted_tree": "L2"}]), spec)
    case("panel-tree-mismatch: MISCONFIG (deploy yakalanır)", r["terminal"] == "MISCONFIG" and r["misconfig_reason"] == "panel_tree_mismatch")
    case("panel-tree-mismatch: ihlal yok (meşru — deploy engellenir)", all(x == 0 for x in r["violations"].values()))

    # 10) S2 legit MISCONFIG — aynı endpoint iki ağaçta
    r = build(scn(mounts=[{"endpoint": "GET /x", "declared_panel": "L1", "mounted_tree": "L1"},
                          {"endpoint": "GET /x", "declared_panel": "L2", "mounted_tree": "L2"}]), spec)
    case("multi-tree-mount: MISCONFIG", r["terminal"] == "MISCONFIG" and r["misconfig_reason"] == "multi_tree_mount")

    # 11) malformed → MISCONFIG
    case("malformed-noreqid: MISCONFIG", build(scn(request_id=None), spec)["misconfig_reason"] == "malformed_topology")
    case("malformed-badmount: MISCONFIG", build(scn(mounts=[{"declared_panel": "L2"}]), spec)["misconfig_reason"] == "malformed_topology")

    # 12) S8 DEVİR ispatı — router ADMIT → 12.2.1 backend-guard kararı yine çalışır (gerekli ama yeterli değil)
    r = build(scn(), spec)
    if r["terminal"] == "ADMIT":
        bg = _guard_module()
        gd = bg.build({
            "request_id": "req-1", "tenant_id": "t-acme", "actor_user_id": "u-1",
            "actor_realm": "tenant", "authenticated": True,
            "token": {"realm": "tenant", "panel_scope": "panel:L2"},
            "endpoint": {"panel": "L2", "required_permission": "calls:read"},
            "assignments": [{"role": "qa_analyst", "scope": {}}], "ownership": "other",
            "resource": {"tenant_id": "t-acme", "campaign": "camp-1"}}, bg._load(bg.SPEC_PATH))
        # qa_analyst calls:read taşır → 12.2.1 ALLOW; ama router ADMIT'i tek başına bunu garanti ETMEZ
        case("devir: router ADMIT sonrası 12.2.1 kararı çalışır (terminal döner)", gd["terminal"] in {"ALLOW", "DENY", "BLOCK"})
        gd2 = bg.build({
            "request_id": "req-1", "tenant_id": "t-acme", "actor_user_id": "u-1",
            "actor_realm": "tenant", "authenticated": True,
            "token": {"realm": "tenant", "panel_scope": "panel:L2"},
            "endpoint": {"panel": "L2", "required_permission": "campaign:manage"},
            "assignments": [{"role": "qa_analyst", "scope": {}}], "ownership": "other",
            "resource": {"tenant_id": "t-acme", "campaign": "camp-1"}}, bg._load(bg.SPEC_PATH))
        case("devir: aynı ADMIT ama yetkisiz permission → 12.2.1 DENY (admission yeterli değil)", gd2["terminal"] == "DENY")
    else:
        case("devir: router ADMIT sonrası 12.2.1 kararı çalışır (terminal döner)", False)
        case("devir: aynı ADMIT ama yetkisiz permission → 12.2.1 DENY (admission yeterli değil)", False)

    # ── DEGRADE (inject) — hepsi kapıyı ELEMELİ ──

    # 13) cross_panel_mount
    r = build(scn(mounts=[{"endpoint": "GET /ops/v1/calls/{id}", "declared_panel": "L0", "mounted_tree": "L2"}]), spec, inject=["cross_panel_mount"])
    case("cross-panel-mount: tree_mount_violation>0 + kapı eler", r["violations"]["tree_mount_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 14) plane_collapse
    r = build(scn(), spec, inject=["plane_collapse"])
    case("plane-collapse: plane_violation>0 + kapı eler", r["violations"]["plane_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 15) scope_reuse
    r = build(scn(), spec, inject=["scope_reuse"])
    case("scope-reuse: scope_violation>0 + kapı eler", r["violations"]["scope_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 16) scope_bypass — L2 ağacına panel:L1 token kabul (request-time)
    r = build(scn(request={"target_tree": "L2", "arrived_plane": "tenant_application_plane",
                           "arrived_origin": "api.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "tenant", "panel_scope": "panel:L1"}}), spec, inject=["scope_bypass"])
    case("scope-bypass: scope_violation>0 + ADMIT(yanlış) + kapı eler",
         r["violations"]["scope_violation"] > 0 and r["terminal"] == "ADMIT" and _gate_eval(r, G)[0] is False)

    # 17) realm_cross — L0 ağacına tenant realm kabul
    r = build(scn(mounts=[{"endpoint": "POST /platform/v1/tenants", "declared_panel": "L0", "mounted_tree": "L0"}],
                  request={"target_tree": "L0", "arrived_plane": "platform_control_plane",
                           "arrived_origin": "platform.internal.rmcvoice.io", "authenticated": True,
                           "token": {"realm": "tenant", "panel_scope": "panel:L0"}}), spec, inject=["realm_cross"])
    case("realm-cross: realm_violation>0 + kapı eler", r["violations"]["realm_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 18) scope_dep_drop
    r = build(scn(), spec, inject=["scope_dep_drop"])
    case("scope-dep-drop: missing_scope_dependency>0 + kapı eler", r["violations"]["missing_scope_dependency"] > 0 and _gate_eval(r, G)[0] is False)

    # 19) consistency_break
    r = build(scn(), spec, inject=["consistency_break"])
    case("consistency-break: consistency_violation>0 + kapı eler", r["violations"]["consistency_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 20) admit_sufficient — router admission'ı yeterli say
    r = build(scn(), spec, inject=["admit_sufficient"])
    case("admit-sufficient: delegation_violation>0 + kapı eler", r["violations"]["delegation_violation"] > 0 and _gate_eval(r, G)[0] is False)

    # 21) model_tamper
    r = build(scn(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0 + kapı eler", r["violations"]["model_tampered"] > 0 and _gate_eval(r, G)[0] is False)

    # 22) evidence + leak
    r = build(scn(), spec)
    case("evidence: request+mounts+target+model_hash taşır",
         all(k in r["evidence"] for k in ("request_id", "mounts", "target_tree", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("customer_phone_value", "card_pan_value", "raw_value")))
    case("leak: panel/scope/prefix/origin temiz",
         scan_leaks('{"panel":"L2","oauth_scope":"panel:L2","prefix":"/ops/v1","origin":"api.rmcvoice.io"}') == [])
    case("leak: card_pan_value alanı yakalanır", len(scan_leaks('{"card_pan_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "router-scopes (WBS 12.2.2 — L0/L1/L2 ayrı router ağaçları + ayrı OAuth scope; SAD §14.4.2)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "admit_terminals": sorted(ADMIT_TERMINALS),
        "rules": RULES,
        "reject_reasons": REJECT_REASONS,
        "misconfig_reasons": MISCONFIG_REASONS,
        "realms": sorted(REALMS),
        "panels": sorted(PANELS),
        "decision": "malformed ⇒ MISCONFIG(malformed_topology) → endpoint paneli ≠ ağaç paneli ⇒ "
                    "MISCONFIG(panel_tree_mismatch) → aynı endpoint >1 ağaç ⇒ MISCONFIG(multi_tree_mount) → "
                    "kimlik yok ⇒ REJECT(unauthenticated,401) → yanlış düzlem/origin ⇒ REJECT(wrong_plane_origin) → "
                    "token realm ≠ ağaç realm ⇒ REJECT(router_realm_mismatch) → token scope ≠ ağaç scope ⇒ "
                    "REJECT(router_scope_mismatch) → hepsi geçer ⇒ ADMIT → DEVREDİLİR 12.2.1 backend-guard",
        "default": "MISCONFIG (fail-closed)",
        "fail_safe": "terminal=MISCONFIG/REJECT ⇒ no access; topoloji/scope/realm/plane belirsizliği ⇒ fail-closed",
        "core_guarantees": [
            "S2 ayrı router ağaçları: her endpoint TAM BİR panel ağacına mount; endpoint paneli = ağaç paneli; cross-panel mount YOK; tree_mount_violation=0 (FR-IAM-008/ADR-011)",
            "S3 düzlem/deploy ayrımı: L0 ağacı AYRI internal-only Platform Control Plane'de; L0 ⟂ tenant düzlemi; plane_violation=0 (ADR-011)",
            "S4 ayrı/anlaşmaz OAuth scope: her ağaç KENDİ scope'unu (panel:L0/L1/L2) router-seviyesi dependency ile zorlar; scope_violation=0",
            "S6 12.2.1 tutarlılık: topoloji oauth_scope/realm = guard-model panel_oauth_scope/panel_realm (tek kaynak); consistency_violation=0",
            "S8 devir: router admission GEREKLİ ama YETERLİ DEĞİL → 12.2.1 backend-guard'a devredilir; delegation_violation=0",
        ],
        "scenario_fields": ["name", "request_id", "mounts[{endpoint, declared_panel, mounted_tree}]",
                            "request{target_tree, arrived_plane, arrived_origin, authenticated, token{realm, panel_scope}}",
                            "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "misconfig_reason", "reject_reason", "admitted", "http_status",
                            "target_tree", "arrived_plane", "delegated_to", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/router-topology.json (frozen — planes + router_trees(prefix/plane/realm/oauth_scope/"
                 "router_scope_dependency) + scope_disjoint + http_status) + ../backend-guard/config/guard-model.json "
                 "(12.2.1 panel_realm/panel_oauth_scope — tutarlılık S6)",
        "consumes": "12.2.1 backend-guard (panel+rol+tenant per-request kararı DEVREDİLİR; guard-model.json scope/realm "
                    "tek kaynak); SAD §14.4.2 + ADR-011 (iki düzlemli dağıtım); API.md §4.1 base path'ler",
        "consumed_by": "12.2.3 RLS çift kontrol (DB seviyesi); 12.2.4 L0 repository bağımsızlığı; 12.3.x break-glass "
                       "(ayrı kısıtlı router); 0.4.7 gözlemlenebilirlik (router_* metrikleri)",
        "trace": "FR-IAM-008, FR-TEN-002, SAD §14.4.2, ADR-011, API.md §2/§4.1",
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
            print("kullanım: router_scopes_probe.py check <sample.json|dizin>")
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
