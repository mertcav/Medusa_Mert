#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.1 — RBAC modeli (rol → permission-key bundle, IMMUTABLE) referans probe.

12. workstream'in (IAM & Erişim) RBAC ÇEKİRDEK MODEL modülü ve F1-Must temel yeteneği.
FR-IAM-001 ('RBAC desteklenmelidir') + FR-IAM-011 ('Roller sabit/immutable permission bundle; esneklik
yalnız atama scope filtresiyle; custom permission rolleri kapsam dışı') + SR-IAM-001 (yetki kararı her zaman
backend'de, rol→permission-key bundle ile değerlendirilir) + SR-IAM-011 (immutable bundle, custom-builder yok)
+ TC-IAM-001 (T) / TC-IAM-011 (I) + ADR-012 (sabit rol bundle + scoped assignment)'i sahiplenir. BRD §17.2
rol seti + SAD §14.4.3 rol→permission-key haritasını DEĞİŞMEZ (frozen) bir modele dönüştürür. Bir yetki
sorgusu (RoleCheckRequest) alır → DETERMİNİSTİK, FAIL-CLOSED bir yetki KARARI verir: aktörün rollerini frozen
modelden çözer (effective bundle = rol bundle'larının birleşimi) → required permission-key'i effective bundle'a
karşı değerlendirir (':own' sahiplik kuralıyla). Bir terminal {GRANT | DENY | BLOCK} kararı döner.

  RoleCheckRequest ─malformed─► unknown_role ─► realm/layer ─► bundle çöz ─► authz (:own) ─► karar
        │                │            │              │            │
        │      ├─ required_permission/rol/kimlik eksik|biçimsiz ──────────────► BLOCK (malformed_request)
        │      ├─ rol modelde yok ──────────────────────────────────────────► BLOCK (unknown_role)
        │      ├─ rol realm ≠ actor_realm (L0↔tenant) ──────────────────────► BLOCK (realm_layer_mismatch)  [K4]
        │      ├─ required ∉ effective bundle ──────────────────────────────► DENY (missing_permission)     [K3]
        │      ├─ yalnız :own + sahiplik=other ─────────────────────────────► DENY (insufficient_scope)     [K6]
        │      └─ required ∈ effective bundle (:own sahiplik tutar) ────────► GRANT                          [K3]

ÇEKİRDEK: (1) K2 IMMUTABLE BUNDLE (FR-IAM-011/SR-IAM-011 ÇEKİRDEK) — rol→permission-key bundle DEĞİŞMEZ
(frozen); effective bundle YALNIZ frozen modelden çözülür; çalışma anında bir role permission eklenip/
çıkarılması (bundle_mutated) yasak; (2) K3 BUNDLE ÇÖZÜMÜ + BACKEND AUTHZ (FR-IAM-001/SR-IAM-001 ÇEKİRDEK) —
effective permission set = atanmış rol bundle'larının BİRLEŞİMİ; GRANT ⟺ required permission-key ∈ effective
set (':own' sahiplik kuralıyla); yetkisiz GRANT (unauthorized_grant) yasak; karar HER ZAMAN backend'de;
(3) K4 KATMAN/REALM BÜTÜNLÜĞÜ (FR-IAM-008) — her rol tanımlı bir katmana (L0/L1/L2/L1+L2) ve realm'e bağlı;
platform rolleri (L0) tenant rollerinden TAMAMEN ayrı; rol realm'i ≠ actor_realm → BLOCK (tenant IdP L0 rol
atayamaz); (4) K5 KATALOG CONFORMANCE — her bundle key'i 'kaynak:eylem' biçiminde + bilinen katalog evreninde;
(5) K6 ':own' DİSİPLİNİ — ':own' key YALNIZ sahiplik=own ise yetki verir; sahiplik dışı kaynakta DENY
insufficient_scope; (6) K7 EN AZ YETKİ / YÜKSELME YOK — rol bundle'ı katman evrenini AŞAMAZ; L0 rolleri tenant
İŞ İÇERİĞİ key'i (calls/transcript/livecalls) TAŞIYAMAZ (L0 altın kuralı, FR-IAM-008); (7) K8 CUSTOM ROL YOK —
modelde tanımsız rol kabul edilmez (custom_role); v1'de custom permission-builder yok (SR-IAM-011). Motor bir
DETERMİNİSTİK FAIL-CLOSED karar fonksiyonudur (Date.now/random YOK; model_hash sha256 deterministik). Her karar
terminal (K1) + kanıt (K9) + model bütünlük manifesti (K10); metrik düşük-kardinalite + ham PII yok (K11);
model/spec/sample ham içerik/PII/credential tutmaz — yalnız rol adı + permission-key + enum + yapısal kimlik (K12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): permission-key GRAMER + TAM KATALOĞU ('kaynak:eylem', ':own'
semantiği, x-required-permission eşlemesi) → 12.1.2 (SAD §14.4.3; key'ler TÜKETİLİR/EŞLENİR); scoped assignment
(rol + departman/marka/kampanya filtresi) → 12.1.3 (FR-IAM-011/ADR-012; bu modül rolü atama kapsamından BAĞIMSIZ
çözer); backend guard (FastAPI dependency + panel/router/tenant scope + RLS) → 12.2.x (SAD §14.4.2; bu modül
KARARI üretir, HTTP enforcement orada); break-glass (L0 Tier B maker-checker + time-boxed token) → 12.3.x
(FR-IAM-009/010; bu modül rol→bundle çözer, break-glass ayrı yol); SSO/SCIM IdP grup→rol eşleme → 12.1.4/12.1.6
(FR-IAM-002/007); append-only WORM audit log → 12.1.8 (FR-IAM-006; bu modül karar KAYDINI üretir, fiziksel WORM
yazımı orada); custom roller (şablonlu, enterprise/dedicated) → Faz 3 (ADR-012; v1 kapsam dışı).

Kullanım:
  rbac_model_probe.py validate          Statik model/spec/kapsama kapısı → çıkış kodu
  rbac_model_probe.py check <sample>     Yetki karar motoru: senaryo(lar)ı çalıştır → kapı (K1–K12)
  rbac_model_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  rbac_model_probe.py schema             Karar sözleşmesini yazdır

Determinizm: model_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII değeri) üretilmez/yazılmaz (fixture sentetik — yalnız rol adı + permission-key + enum + kimlik;
FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "rbac-model-spec.json")
MODEL_PATH = os.path.join(HERE, "config", "rbac-roles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

OUTCOMES = ["GRANT", "DENY", "BLOCK"]
TERMINAL = {"GRANT", "DENY", "BLOCK"}
GRANT_TERMINALS = {"GRANT"}
RULES = ["immutable_bundle", "bundle_resolution", "layer_realm_integrity", "catalog_conformance",
         "own_discipline", "least_privilege", "no_custom_role"]
DENY_REASONS = ["missing_permission", "insufficient_scope"]
BLOCK_REASONS = ["malformed_request", "unknown_role", "realm_layer_mismatch"]
INVARIANT_IDS = ["K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8", "K9", "K10", "K11", "K12"]
REALMS = {"platform", "tenant"}
LAYERS = {"L0", "L1", "L2", "L1+L2"}
OWNERSHIP = {"own", "other"}
PERM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(:[a-z][a-z0-9_]*)+$")

# Degrade (inject) — DOĞRU immutable/bundle/katman/own davranışını bozan müdahaleler.
INJECTIONS = {"bundle_mutate", "custom_role", "unauthorized_grant", "layer_leak", "realm_cross",
              "ownership_bypass", "privilege_escalation", "model_tamper", "secret_leak"}

VIOLATION_KEYS = [
    "bundle_mutated", "custom_role", "unauthorized_grant", "layer_violation", "realm_mismatch",
    "unknown_permission", "ownership_violation", "privilege_escalation", "model_tampered",
    "missing_evidence", "stuck_state", "secret_or_pii",
]

# ── Sızıntı tarayıcı (K12; 11.x deseniyle) — ham içerik/PII/sır yasak; rol adı/permission-key/enum beyazlanır ──
LEAK_PATTERNS = [
    ("phone_e164", re.compile(r"\+(?!1632)\d{9,15}\b")),
    ("digits_long", re.compile(r"\b\d{7,19}\b")),
    ("secret_kw", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|credential)\b\s*[:=]\s*\S")),
    ("privkey", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("pii_field", re.compile(r"(?i)\"(customer_phone_value|card_pan_value|cvv_value|otp_code_value|password_value|customer_name_value|address_value|account_number_value|iban_value|raw_value|pii_value)\"\s*:")),
]
LEAK_ALLOW = re.compile(r"(?i)(555-?01\d\d|\+1632|ITU|reserved|test|example|req-|u-|t-|corr-|prefix|masked|hash|sha256|\[[A-Z0-9_]+\]|\d{4}-\d{2}-\d{2}|apikey:manage|api_developer|api key/webhook|API key)")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def scan_leaks(text):
    """Ham içerik/PII/sır tarayıcı. Yorum/tarif satırı + rol adı/permission-key + maskeli token eler (11.x deseni)."""
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


def _model(sample=None):
    """Frozen model = config/rbac-roles.json. (Çözüm YALNIZ buradan; çalışma anında değiştirilmez.)"""
    return _load(MODEL_PATH)


def _resolve_bundle(roles, model):
    """Effective permission set = atanmış rol bundle'larının BİRLEŞİMİ (frozen modelden; K2/K3)."""
    eff = set()
    for r in roles:
        spec = model["roles"].get(r)
        if spec:
            eff.update(spec.get("permissions", []))
    return eff


def _authz(required, effective, ownership):
    """required permission-key'i effective bundle'a karşı değerlendir (':own' sahiplik kuralı; K3/K6).

    Döner: (authorized: bool, deny_reason: str|None).
      - required ∈ bundle (tam key)                       → GRANT
      - <required>:own ∈ bundle ∧ ownership=own           → GRANT
      - <required>:own ∈ bundle ∧ ownership=other         → DENY insufficient_scope
      - required zaten ':own' ile biter → tam eşleşme + ownership=own gerekir
      - aksi                                              → DENY missing_permission
    """
    if required in effective:
        if required.endswith(":own") and ownership != "own":
            return (False, "insufficient_scope")
        return (True, None)
    own_variant = required + ":own"
    if own_variant in effective:
        if ownership == "own":
            return (True, None)
        return (False, "insufficient_scope")
    return (False, "missing_permission")


def build(sample, spec, inject=None, model=None):
    """Tek yetki-sorgusu senaryosunu yürüt → RoleCheckDecision + ihlal sayaçları.

    Motor DOĞRU immutable/bundle/katman/own davranışını hesaplar; inject (degrade) doğru davranışı bozar ve
    eşleşen ihlal sayacını artırır (11.x inject deseniyle birebir)."""
    inject = set(inject if inject is not None else sample.get("inject", []))
    model = model if model is not None else _model(sample)

    request_id = sample.get("request_id")
    correlation_id = sample.get("correlation_id")
    tenant_id = sample.get("tenant_id")
    actor_user_id = sample.get("actor_user_id")
    actor_realm = sample.get("actor_realm")
    actor_roles = list(sample.get("actor_roles", []) or [])
    required = sample.get("required_permission")
    ownership = sample.get("ownership", "other")

    v = {k: 0 for k in VIOLATION_KEYS}

    terminal = None
    block_reason = None
    deny_reason = None
    authorized = False
    granted = False
    used_roles = []
    effective = set()

    # ── K10 model bütünlük manifesti (frozen) ──
    canonical_model = {"frozen": model.get("frozen"), "roles": model.get("roles")}
    model_hash = _canon_hash(canonical_model)
    if "model_tamper" in inject:
        # Çalışma anında modeli tahrif et (bir role içerik key'i ekle) — hash güncellenmez.
        tampered = json.loads(json.dumps(canonical_model))
        any_l0 = next((r for r, s in tampered["roles"].items() if s.get("layer") == "L0"), None)
        if any_l0:
            tampered["roles"][any_l0]["permissions"].append("transcript:read")
        if _canon_hash(tampered) != model_hash:
            v["model_tampered"] += 1

    # ── malformed kapısı (fail-closed) ──
    malformed = (not request_id or not actor_user_id or actor_realm not in REALMS
                 or not actor_roles or not required
                 or not isinstance(required, str) or not PERM_KEY_RE.match(required))

    if malformed:
        terminal, block_reason = "BLOCK", "malformed_request"
    else:
        # ── K8 custom_role / unknown_role: model dışı rol fail-closed BLOCK ──
        unknown = [r for r in actor_roles if r not in model["roles"]]
        if "custom_role" in inject:
            # Modelde tanımsız bir rolü kabul edip yetki ver (v1'de custom rol yok).
            v["custom_role"] += 1
        if unknown and "custom_role" not in inject:
            terminal, block_reason = "BLOCK", "unknown_role"
        else:
            used_roles = [r for r in actor_roles if r in model["roles"]]
            # ── K4 realm/katman bütünlüğü: rol realm'i actor_realm ile uyuşmalı (L0 ⟂ tenant) ──
            role_realms = {model["roles"][r]["realm"] for r in used_roles}
            realm_mismatch = any(rr != actor_realm for rr in role_realms) or len(role_realms) > 1
            if "realm_cross" in inject:
                realm_mismatch = True
                v["realm_mismatch"] += 1
            if realm_mismatch and "realm_cross" not in inject:
                v["realm_mismatch"] += 1

            if realm_mismatch:
                terminal, block_reason = "BLOCK", "realm_layer_mismatch"
            else:
                # ── K2/K3 effective bundle = rol bundle'larının BİRLEŞİMİ (frozen modelden) ──
                effective = _resolve_bundle(used_roles, model)

                # ── K2 degrade: çalışma anında bundle'a permission ekle (immutability ihlali) ──
                if "bundle_mutate" in inject:
                    effective = set(effective)
                    effective.add(required)
                    v["bundle_mutated"] += 1
                # ── K7 degrade: ayrıcalık yükseltme (L0 role'üne tenant içerik key'i) ──
                if "layer_leak" in inject or "privilege_escalation" in inject:
                    effective = set(effective)
                    effective.add(required)
                    if any(model["roles"][r]["realm"] == "platform" for r in used_roles) \
                       and required in set(model.get("tenant_content_keys", [])):
                        v["layer_violation"] += 1
                    v["privilege_escalation"] += 1

                # ── K3/K6 yetki kapısı ──
                eff_ownership = ownership
                if "ownership_bypass" in inject:
                    # ':own' kısıtını yok say (sahiplik=other iken own gibi davran).
                    eff_ownership = "own"
                authorized, deny_reason = _authz(required, effective, eff_ownership)

                if "ownership_bypass" in inject and ownership != "own":
                    # Sahiplik dışıyken :own ile yetki verildiyse ihlal.
                    own_variant = required + ":own"
                    if (required in effective and required.endswith(":own")) or own_variant in effective:
                        v["ownership_violation"] += 1

                # ── K3 degrade: yetkisizken yetki ver ──
                if "unauthorized_grant" in inject:
                    if not authorized:
                        v["unauthorized_grant"] += 1
                    authorized = True
                    deny_reason = None

                if authorized:
                    terminal, granted = "GRANT", True
                else:
                    terminal = "DENY"
                    if deny_reason is None:
                        deny_reason = "missing_permission"

    # ── K1 stuck state ──
    if terminal not in TERMINAL:
        v["stuck_state"] += 1

    # ── Kanıt (K9) ──
    effective_hash = _canon_hash(sorted(effective)) if effective else None
    evidence = _evidence(request_id, actor_realm, used_roles, required, ownership, authorized, granted,
                         deny_reason, block_reason, effective_hash, model_hash)
    if (not request_id) or (terminal is None):
        v["missing_evidence"] += 1

    return _pack(sample, terminal, v, block_reason, deny_reason, authorized, granted, used_roles,
                 required, ownership, actor_realm, sorted(effective), effective_hash, model_hash, evidence)


def _evidence(request_id, actor_realm, used_roles, required, ownership, authorized, granted,
              deny_reason, block_reason, effective_hash, model_hash):
    return {
        "request_id": request_id,
        "actor_realm": actor_realm,
        "actor_roles": used_roles,
        "required_permission": required,
        "ownership": ownership,
        "authorized": authorized,
        "granted": granted,
        "deny_reason": deny_reason,
        "block_reason": block_reason,
        "effective_bundle_hash": effective_hash,
        "model_hash": model_hash,
    }


def _pack(sample, terminal, v, block_reason, deny_reason, authorized, granted, used_roles, required,
          ownership, actor_realm, effective, effective_hash, model_hash, evidence):
    return {
        "name": sample.get("name"),
        "terminal": terminal,
        "resolved": terminal in TERMINAL,
        "block_reason": block_reason,
        "deny_reason": deny_reason,
        "authorized": authorized,
        "granted": granted,
        "actor_roles": used_roles,
        "required_permission": required,
        "ownership": ownership,
        "actor_realm": actor_realm,
        "effective_bundle": effective,
        "effective_bundle_hash": effective_hash,
        "model_hash": model_hash,
        "evidence": evidence,
        "violations": v,
    }


def _gate_eval(result, gates):
    """Tek senaryo sonucunu HARD kapılara vur → (passed, fail_list)."""
    v = result["violations"]
    fails = []
    mapping = {
        "bundle_mutated": "max_bundle_mutated",
        "custom_role": "max_custom_role",
        "unauthorized_grant": "max_unauthorized_grant",
        "layer_violation": "max_layer_violation",
        "realm_mismatch": "max_realm_mismatch",
        "unknown_permission": "max_unknown_permission",
        "ownership_violation": "max_ownership_violation",
        "privilege_escalation": "max_privilege_escalation",
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
        for key in ("terminal", "block_reason", "deny_reason", "authorized", "granted"):
            if key in exp_assert and exp_assert[key] != res.get(key):
                mism.append("%s: beklenen=%r gerçek=%r" % (key, exp_assert[key], res.get(key)))

        verdict_ok = (passed and not mism) if expect == "pass" else (not passed)
        all_ok = all_ok and verdict_ok
        icon = "🟢" if verdict_ok else "🔴"
        print("%s %s" % (icon, os.path.basename(p)))
        print("   terminal=%s authorized=%s granted=%s reason=%s/%s roles=%s required=%s own=%s"
              % (res["terminal"], res["authorized"], res["granted"], res["block_reason"],
                 res["deny_reason"], res["actor_roles"], res["required_permission"], res["ownership"]))
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
              "block_reasons", "deny_reasons", "outcomes", "model", "authorization", "gates",
              "observability", "invariants", "no_secrets"):
        chk("spec.%s var" % f, f in spec)
    chk("wbs=12.1.1", spec.get("wbs") == "12.1.1")
    chk("phase=F1", spec.get("phase") == "F1")
    chk("priority=Must", spec.get("priority") == "Must")
    chk("placement fail_closed=true", spec.get("placement", {}).get("fail_closed") is True)
    chk("placement immutable=true", spec.get("placement", {}).get("immutable") is True)

    # 2) İzlenebilirlik
    tr = spec.get("trace", {})
    chk("FR-IAM-001 izlenir (RBAC — ÇEKİRDEK)", "FR-IAM-001" in tr.get("fr", []))
    chk("FR-IAM-011 izlenir (immutable bundle — ÇEKİRDEK)", "FR-IAM-011" in tr.get("fr", []))
    chk("FR-IAM-008 izlenir (panel-katman rol ayrımı)", "FR-IAM-008" in tr.get("fr", []))
    chk("SR-IAM-001 izlenir", "SR-IAM-001" in tr.get("srs", []))
    chk("SR-IAM-011 izlenir", "SR-IAM-011" in tr.get("srs", []))
    chk("TC-IAM-001 izlenir", "TC-IAM-001" in tr.get("rtm", []))
    chk("TC-IAM-011 izlenir", "TC-IAM-011" in tr.get("rtm", []))
    chk("ADR-012 izlenir (sabit rol bundle + scoped assignment)",
        any(a.startswith("ADR-012") for a in tr.get("adr", [])))
    chk("ADR-011 izlenir (iki düzlemli panel)", any(a.startswith("ADR-011") for a in tr.get("adr", [])))
    chk("SAD §14.4.3 RBAC permission-key izlenir", any("§14.4.3" in s for s in tr.get("sad", [])))
    chk("BRD §17.2 rol seti izlenir", any("§17" in s for s in tr.get("brd", [])))

    # 3) Yedi kural (çekirdek)
    rz = spec["rules"]
    rule_ids = [d["id"] for d in rz.get("list", [])]
    chk("yedi kural tam (immutable/resolution/layer/catalog/own/least_priv/no_custom)", set(rule_ids) == set(RULES))
    chk("değerlendirme malformed_then_unknown_role_then_realm_then_resolve_then_authz_fail_closed",
        rz.get("evaluation") == "malformed_then_unknown_role_then_realm_then_resolve_then_authz_fail_closed")
    for d in rz.get("list", []):
        chk("kural %s invariant taşır" % d["id"], d.get("invariant") in INVARIANT_IDS)

    # 4) Karar
    dec = spec["decision"]
    chk("karar default=BLOCK (fail-closed)", dec.get("default") == "BLOCK")
    chk("fail_safe no access (granted=false)",
        "granted=false" in dec.get("fail_safe_terminal", "").lower()
        or "no access" in dec.get("fail_safe_terminal", "").lower())

    # 5) Sonuçlar + reason taksonomisi
    oc = spec["outcomes"]
    chk("terminal sonuçlar GRANT/DENY/BLOCK", set(oc.get("list", [])) == set(OUTCOMES))
    br = set(spec["block_reasons"].get("list", []))
    chk("block_reason taksonomisi (malformed/unknown_role/realm_layer_mismatch)", br == set(BLOCK_REASONS))
    dr = set(spec["deny_reasons"].get("list", []))
    chk("deny_reason taksonomisi (missing_permission/insufficient_scope)", dr == set(DENY_REASONS))

    # 6) Model — frozen + custom-builder yok + katman/realm
    md = spec["model"]
    chk("model frozen=true (immutable)", md.get("frozen") is True)
    chk("custom_permission_builder=false (v1; SR-IAM-011)", md.get("custom_permission_builder") is False)
    chk("permission_key_format=kaynak:eylem", md.get("permission_key_format") == "kaynak:eylem")
    chk("own_suffix=:own", md.get("own_suffix") == ":own")
    chk("layers L0/L1/L2/L1+L2", set(md.get("layers", [])) == LAYERS)
    chk("realms platform/tenant", set(md.get("realms", [])) == REALMS)
    chk("12 rol (BRD §17.2)", md.get("role_count") == 12)

    # 7) Yetki — backend + ADR-012
    az = spec["authorization"]
    chk("karar backend'de (SR-IAM-001)", az.get("decision_at") == "backend")
    chk("effective bundle = rol bundle birleşimi",
        "birleşim" in az.get("resolution", "").lower() or "union" in az.get("resolution", "").lower())
    chk("L0 altın kural (platform tenant içeriği taşımaz)",
        "altın kural" in az.get("golden_rule", "").lower() or "l0" in az.get("golden_rule", "").lower())

    # 8) Kapılar — tüm sıfır-eşik ihlal kapıları
    g = spec["gates"]
    for gk in ("max_bundle_mutated", "max_custom_role", "max_unauthorized_grant", "max_layer_violation",
               "max_realm_mismatch", "max_unknown_permission", "max_ownership_violation",
               "max_privilege_escalation", "max_model_tampered", "max_missing_evidence",
               "max_stuck_state", "max_secret_or_pii"):
        chk("kapı %s=0" % gk, g.get(gk) == 0)
    chk("require_terminal", g.get("require_terminal") is True)

    # 9) Gözlemlenebilirlik — kardinalite disiplini (0.4.7)
    obs = spec["observability"]
    chk("rbac_decision_total metrik", "rbac_decision_total" in obs.get("metrics", []))
    chk("rbac_integrity_violation_total metrik (K2/K3/K7 alarm)",
        "rbac_integrity_violation_total" in obs.get("metrics", []))
    hi = set(obs.get("high_cardinality_trace_only", []))
    lo = set(obs.get("low_cardinality_labels", []))
    chk("request_id/actor_user_id YÜKSEK kard (label değil)",
        "actor_user_id" in hi and "request_id" in hi and "actor_user_id" not in lo)
    chk("result/actor_realm DÜŞÜK kard (label uygun)",
        "result" in lo and "actor_realm" in lo)
    chk("alarm bundle_mutated/unauthorized_grant/privilege_escalation ≤2dk",
        any(x in obs.get("alarm", "") for x in ("bundle_mutated", "unauthorized_grant", "privilege_escalation")))

    # 10) İnvariant'lar K1–K12
    inv_ids = [i["id"] for i in spec["invariants"]]
    chk("invariant'lar K1–K12 tam", inv_ids == INVARIANT_IDS)

    # 11) Model dosyası + içsel tutarlılık (ÇEKİRDEK)
    model_ok = os.path.exists(MODEL_PATH)
    chk("config/rbac-roles.json var", model_ok)
    if model_ok:
        m = _load(MODEL_PATH)
        roles = m.get("roles", {})
        chk("model frozen=true", m.get("frozen") is True)
        chk("model custom_permission_builder=false", m.get("custom_permission_builder") is False)
        chk("12 rol tanımlı (BRD §17.2)", len(roles) == 12)
        expected_roles = {"platform_owner", "platform_sre", "platform_billing", "tenant_owner",
                          "tenant_admin", "security_compliance_officer", "billing_viewer",
                          "operations_manager", "conversation_designer", "qa_analyst", "human_agent",
                          "api_developer"}
        chk("rol seti BRD §17.2 ile birebir", set(roles.keys()) == expected_roles)

        universe = m.get("permission_key_universe", {})
        all_universe = set()
        for ks in universe.values():
            all_universe.update(ks)
        layer_realm = m.get("layer_realm", {})
        content_keys = set(m.get("tenant_content_keys", []))

        bad_format = []
        unknown_in_bundle = []
        layer_overflow = []
        l0_content = []
        empty_bundle = []
        realm_inconsistent = []
        for rname, rspec in roles.items():
            perms = rspec.get("permissions", [])
            layer = rspec.get("layer")
            realm = rspec.get("realm")
            if not perms:
                empty_bundle.append(rname)
            if layer_realm.get(layer) != realm:
                realm_inconsistent.append(rname)
            # En-az-yetki = REALM evreni (sert güvenlik sınırı L0 ⟂ tenant, FR-IAM-008). L1/L2 ayrımı
            # tenant realm içinde konsol-ayrımıdır, sert yetki sınırı DEĞİL: bir tenant rolü (ör.
            # security_compliance_officer L1) PII denetimi için transcript:read (L2 evreni) taşıyabilir.
            if realm == "platform":
                allowed = set(universe.get("L0", []))
            else:
                allowed = set(universe.get("L1", [])) | set(universe.get("L2", []))
            for k in perms:
                if not PERM_KEY_RE.match(k):
                    bad_format.append((rname, k))
                if k not in all_universe:
                    unknown_in_bundle.append((rname, k))
                if k not in allowed:
                    layer_overflow.append((rname, k))
                if realm == "platform" and k in content_keys:
                    l0_content.append((rname, k))
        chk("K5 her bundle key'i kaynak:eylem biçiminde", not bad_format, str(bad_format[:2]))
        chk("K5 her bundle key'i katalog evreninde (unknown_permission=0)", not unknown_in_bundle, str(unknown_in_bundle[:2]))
        chk("K7 hiçbir bundle katman evrenini aşmaz (least-privilege)", not layer_overflow, str(layer_overflow[:2]))
        chk("K7 L0 rolleri tenant içerik key'i TAŞIMAZ (altın kural, FR-IAM-008)", not l0_content, str(l0_content[:2]))
        chk("her rol layer↔realm tutarlı (FR-IAM-008)", not realm_inconsistent, str(realm_inconsistent[:2]))
        chk("hiçbir bundle boş değil", not empty_bundle, str(empty_bundle))

        # Bilinen referans bundle'lar (SAD §14.4.3) — spot kontrol
        chk("platform_sre iş içeriği key'i yok (SAD §14.4.3)",
            not (set(roles.get("platform_sre", {}).get("permissions", [])) & content_keys))
        chk("human_agent yalnız :own içerik key'i",
            all(k.endswith(":own") for k in roles.get("human_agent", {}).get("permissions", [])))
        chk("tenant_admin role:assign içerir",
            "role:assign" in roles.get("tenant_admin", {}).get("permissions", []))
        chk("qa_analyst transcript:read içerir (calls/transcript okuma)",
            "transcript:read" in roles.get("qa_analyst", {}).get("permissions", []))

    # 12) Sır/PII tarayıcı — spec + model + samples
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
    chk("hiç ham-içerik/PII/sır sızıntısı yok (K12)", total_leaks == 0)

    # 13) Samples — ≥1 pass + ≥1 fail (degrade ispatı)
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
        # Varsayılan: tenant realm qa_analyst transkript okuma (transcript:read) — yetkili.
        d = {
            "request_id": "req-1", "tenant_id": "t-acme", "correlation_id": "corr-1",
            "actor_user_id": "u-1", "actor_realm": "tenant", "actor_roles": ["qa_analyst"],
            "required_permission": "transcript:read", "ownership": "other",
        }
        d.update(kw)
        return d

    # 1) happy — yetkili tenant qa_analyst → GRANT
    r = build(req(), spec)
    case("happy: GRANT", r["terminal"] == "GRANT")
    case("happy: authorized=true", r["authorized"] is True)
    case("happy: granted=true", r["granted"] is True)
    case("happy: deny_reason yok", r["deny_reason"] is None)
    case("happy: effective_bundle_hash var (K9)", r["effective_bundle_hash"] is not None)
    case("happy: model_hash var (K10)", r["model_hash"] is not None)
    case("happy: ihlal yok", all(x == 0 for x in r["violations"].values()))
    case("happy: kapı geçer", _gate_eval(r, G)[0] is True)

    # 2) determinizm + model_hash deterministik
    r1, r2 = build(req(), spec), build(req(), spec)
    case("determinizm: birebir", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
    case("model_hash deterministik", r1["model_hash"] == r2["model_hash"])

    # 3) DENY — yetki yok (rol bundle'ında required yok)
    r = build(req(required_permission="campaign:manage"), spec)
    case("no-perm: DENY", r["terminal"] == "DENY")
    case("no-perm: deny_reason=missing_permission", r["deny_reason"] == "missing_permission")
    case("no-perm: granted=false", r["granted"] is False)
    case("no-perm: kapı geçer (DENY meşru terminal)", _gate_eval(r, G)[0] is True)

    # 3b) çoklu rol → bundle birleşimi (K3)
    r = build(req(actor_roles=["qa_analyst", "conversation_designer"], required_permission="flow:edit"), spec)
    case("multi-role: birleşim GRANT (flow:edit conversation_designer'dan)", r["terminal"] == "GRANT")
    r = build(req(actor_roles=["qa_analyst", "conversation_designer"], required_permission="qa:score"), spec)
    case("multi-role: birleşim GRANT (qa:score qa_analyst'tan)", r["terminal"] == "GRANT")

    # 4) :own disiplini (K6)
    r = build(req(actor_roles=["human_agent"], required_permission="calls:read", ownership="own"), spec)
    case("own-own: GRANT (calls:read:own + ownership=own)", r["terminal"] == "GRANT" and r["authorized"] is True)
    r = build(req(actor_roles=["human_agent"], required_permission="calls:read", ownership="other"), spec)
    case("own-other: DENY insufficient_scope",
         r["terminal"] == "DENY" and r["deny_reason"] == "insufficient_scope")
    # tam (full) key sahiplikten bağımsız
    r = build(req(actor_roles=["operations_manager"], required_permission="calls:read", ownership="other"), spec)
    case("full-key: GRANT (operations_manager full calls:read, ownership farketmez)", r["terminal"] == "GRANT")

    # 5) K4 realm/katman bütünlüğü
    r = build(req(actor_realm="platform", actor_roles=["qa_analyst"], required_permission="transcript:read"), spec)
    case("realm-cross: BLOCK realm_layer_mismatch (tenant rol platform realm'de)",
         r["terminal"] == "BLOCK" and r["block_reason"] == "realm_layer_mismatch")
    case("realm-cross: realm_mismatch>0", r["violations"]["realm_mismatch"] > 0)
    case("realm-cross: kapı ELER", _gate_eval(r, G)[0] is False)
    # L0 rol doğru realm'de → GRANT
    r = build(req(actor_realm="platform", actor_roles=["platform_sre"], required_permission="incident:manage"), spec)
    case("l0-ok: GRANT (platform_sre incident:manage)", r["terminal"] == "GRANT")

    # 5b) L0 altın kural — platform_sre tenant içeriği isteyemez (bundle'ında yok)
    r = build(req(actor_realm="platform", actor_roles=["platform_sre"], required_permission="transcript:read"), spec)
    case("l0-golden: DENY (platform_sre transcript:read taşımaz)",
         r["terminal"] == "DENY" and r["deny_reason"] == "missing_permission")

    # 6) unknown_role → BLOCK
    r = build(req(actor_roles=["super_admin"]), spec)
    case("unknown-role: BLOCK unknown_role", r["terminal"] == "BLOCK" and r["block_reason"] == "unknown_role")
    case("unknown-role: granted=false", r["granted"] is False)

    # 7) malformed → BLOCK
    r = build(req(required_permission="calls"), spec)
    case("malformed-perm: BLOCK (kaynak:eylem değil)",
         r["terminal"] == "BLOCK" and r["block_reason"] == "malformed_request")
    r = build(req(actor_roles=[]), spec)
    case("malformed-norole: BLOCK", r["terminal"] == "BLOCK" and r["block_reason"] == "malformed_request")

    # 8) K2 bundle_mutate — çalışma anında bundle'a permission ekle
    r = build(req(required_permission="campaign:manage"), spec, inject=["bundle_mutate"])
    case("bundle-mutate: bundle_mutated>0", r["violations"]["bundle_mutated"] > 0)
    case("bundle-mutate: kapı ELER", _gate_eval(r, G)[0] is False)

    # 9) K8 custom_role — model dışı rolü kabul et + yetki ver
    r = build(req(actor_roles=["custom_superuser"], required_permission="tenant:provision"),
              spec, inject=["custom_role"])
    case("custom-role: custom_role>0", r["violations"]["custom_role"] > 0)
    case("custom-role: kapı ELER", _gate_eval(r, G)[0] is False)

    # 10) K3 unauthorized_grant — yetkisizken GRANT
    r = build(req(required_permission="campaign:manage"), spec, inject=["unauthorized_grant"])
    case("unauth-grant: unauthorized_grant>0", r["violations"]["unauthorized_grant"] > 0)
    case("unauth-grant: GRANT (yanlış)", r["terminal"] == "GRANT")
    case("unauth-grant: kapı ELER", _gate_eval(r, G)[0] is False)

    # 11) K7 privilege_escalation / layer_leak — L0 role'üne tenant içerik key'i
    r = build(req(actor_realm="platform", actor_roles=["platform_sre"], required_permission="transcript:read"),
              spec, inject=["layer_leak"])
    case("layer-leak: layer_violation>0", r["violations"]["layer_violation"] > 0)
    case("layer-leak: privilege_escalation>0", r["violations"]["privilege_escalation"] > 0)
    case("layer-leak: kapı ELER", _gate_eval(r, G)[0] is False)

    # 12) K6 ownership_bypass — :own kısıtını yok say
    r = build(req(actor_roles=["human_agent"], required_permission="calls:read", ownership="other"),
              spec, inject=["ownership_bypass"])
    case("own-bypass: ownership_violation>0", r["violations"]["ownership_violation"] > 0)
    case("own-bypass: kapı ELER", _gate_eval(r, G)[0] is False)

    # 13) K10 model_tamper — çalışma anında modeli tahrif et
    r = build(req(), spec, inject=["model_tamper"])
    case("model-tamper: model_tampered>0", r["violations"]["model_tampered"] > 0)
    case("model-tamper: kapı ELER", _gate_eval(r, G)[0] is False)

    # 14) K4 realm_cross inject
    r = build(req(actor_roles=["qa_analyst"]), spec, inject=["realm_cross"])
    case("realm-cross-inject: realm_mismatch>0 + BLOCK",
         r["violations"]["realm_mismatch"] > 0 and r["terminal"] == "BLOCK")

    # 15) immutability — aynı model_hash her çağrıda (frozen)
    hashes = {build(req(actor_roles=[r0], required_permission="quota:read"), spec)["model_hash"]
              for r0 in ("tenant_admin", "billing_viewer")}
    case("immutable: model_hash tüm çağrılarda aynı", len(hashes) == 1)

    # 16) tenant_owner geniş bundle (L1+L2)
    for perm in ("org:manage", "campaign:manage", "transcript:read", "user:manage"):
        rr = build(req(actor_roles=["tenant_owner"], required_permission=perm), spec)
        case("tenant_owner GRANT %s" % perm, rr["terminal"] == "GRANT")

    # 17) kanıt (K9) yapısal, PII yok
    r = build(req(), spec)
    case("evidence: request taşır", r["evidence"]["request_id"] == "req-1")
    case("evidence: actor_roles/required/model_hash taşır",
         all(k in r["evidence"] for k in ("actor_roles", "required_permission", "model_hash")))
    case("evidence: ham PII alanı yok",
         all(k not in json.dumps(r) for k in ("customer_phone_value", "card_pan_value", "raw_value")))

    # 18) sızıntı tarayıcı
    case("leak: rol adı temiz", scan_leaks('{"actor_roles": ["operations_manager"]}') == [])
    case("leak: permission-key temiz", scan_leaks('{"required_permission": "transcript:read"}') == [])
    case("leak: kimlik temiz", scan_leaks('{"request_id": "req-001", "actor_user_id": "u-1"}') == [])
    case("leak: card_pan_value alanı yakalanır", len(scan_leaks('{"card_pan_value": "x"}')) > 0)
    case("leak: ham uzun rakam yakalanır", len(scan_leaks('{"x": "4111111111111111"}')) > 0)

    npass = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nselftest: %d/%d %s" % (npass, len(results), "🟢" if npass == len(results) else "🔴"))
    return 0 if npass == len(results) else 1


# ════════════════════════════════════════════════════════════════════════════
def schema_cmd():
    out = {
        "module": "rbac-model (WBS 12.1.1 — RBAC modeli: rol→permission-key bundle, immutable; FR-IAM-001/011)",
        "outcomes": OUTCOMES,
        "terminal": sorted(TERMINAL),
        "grant_terminals": sorted(GRANT_TERMINALS),
        "rules": RULES,
        "block_reasons": BLOCK_REASONS,
        "deny_reasons": DENY_REASONS,
        "realms": sorted(REALMS),
        "layers": sorted(LAYERS),
        "ownership": sorted(OWNERSHIP),
        "decision": "malformed ⇒ BLOCK(malformed_request) → rol modelde yok ⇒ BLOCK(unknown_role) → "
                    "rol realm ≠ actor_realm ⇒ BLOCK(realm_layer_mismatch) → effective bundle = rol "
                    "bundle'larının birleşimi (frozen model) → required ∈ bundle (:own sahiplik) ⇒ GRANT | "
                    "DENY(missing_permission|insufficient_scope)",
        "default": "BLOCK (fail-closed)",
        "fail_safe": "terminal=BLOCK ⇒ granted=false; belirsizlik/malformed/unknown_role/realm mismatch ⇒ BLOCK",
        "core_guarantees": [
            "K2 immutable bundle: effective set YALNIZ frozen modelden; bundle_mutated=0, custom_role=0 (FR-IAM-011/SR-IAM-011)",
            "K3 bundle çözümü + backend authz: effective=∪ rol bundle; GRANT⟺required∈effective; unauthorized_grant=0 (FR-IAM-001/SR-IAM-001)",
            "K4 katman/realm bütünlüğü: L0 ⟂ tenant; rol realm=actor_realm; realm_mismatch=0 (FR-IAM-008)",
            "K6 :own disiplini: :own yalnız ownership=own; ownership_violation=0",
            "K7 en az yetki: bundle ⊆ katman evreni; L0 tenant içerik key'i taşımaz; privilege_escalation=0 (L0 altın kural)",
        ],
        "request_fields": ["name", "request_id", "tenant_id", "correlation_id", "actor_user_id",
                           "actor_realm(platform|tenant)", "actor_roles[]", "required_permission(kaynak:eylem)",
                           "ownership(own|other)", "inject[]", "expect", "expected{}"],
        "injections (degrade testi)": sorted(INJECTIONS),
        "decision_fields": ["terminal", "block_reason", "deny_reason", "authorized", "granted",
                            "actor_roles", "required_permission", "ownership", "actor_realm",
                            "effective_bundle", "effective_bundle_hash", "model_hash", "evidence"],
        "violations": VIOLATION_KEYS,
        "invariants": INVARIANT_IDS,
        "model": "config/rbac-roles.json — 12 rol (BRD §17.2) × IMMUTABLE permission bundle (SAD §14.4.3); "
                 "layer (L0/L1/L2/L1+L2) + realm (platform/tenant) + permission_key_universe + tenant_content_keys",
        "consumes": "BRD §17.2 rol seti + SAD §14.4.3 rol→permission-key haritası (model); FR-IAM-011/ADR-012 "
                    "immutable bundle ilkesi",
        "consumed_by": "12.1.2 permission-key kataloğu (key GRAMER/TAM ENUM) + 12.1.3 scoped assignment "
                       "(rol+kapsam filtresi) + 12.2.x backend guard (KARAR enforcement) + 12.3.x break-glass + "
                       "12.1.8 WORM audit (karar kaydı) + 0.4.7 gözlemlenebilirlik (rbac_* metrikleri)",
        "trace": "FR-IAM-001, FR-IAM-011, FR-IAM-008, SR-IAM-001, SR-IAM-011, TC-IAM-001 (T), TC-IAM-011 (I), "
                 "BRD §17.2, SAD §14.4.3, ADR-011, ADR-012",
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
            print("kullanım: rbac_model_probe.py check <sample.json|dizin>")
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
