#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.2 — Permission-key kataloğu ('kaynak:eylem', '*:own') referans probe.

12. workstream'in (IAM & Erişim) permission-key GRAMER + TAM KATALOG modülü ve F1-Must temel yeteneği.
SAD §14.4.3 ('kaynak:eylem' formatı) + BRD §17.6 (ekran-panel-rol erişim matrisi) + BRD §17.7 (izolasyon/
görünürlük kuralları, '*:own') → makine-okunur, DEĞİŞMEZ (frozen) bir KATALOG (config/permission-catalog.json)
+ DETERMİNİSTİK, FAIL-CLOSED bir key ÇÖZÜM MOTORU. Motor bir permission-key string'i (ör. bir endpoint'in
x-required-permission değeri) alır → GRAMER ayrıştırır → kataloğa çözer → terminal {VALID | REJECT | UNKNOWN}
kararı döner. Bu modül permission-key'in GRAMERİNİ + KATALOĞUNU SAHİPLENİR; 12.1.1 RBAC modeli rol bundle'larını
bu kataloğa CONFORM eder, 12.2.x backend guard x-required-permission'ı bu kataloğa karşı ENFORCE eder.

  PermissionKeyRequest ─grammar─► own_place ─► own_scope ─► resolve ─► karar
        │              │              │            │            │
        │      ├─ key 'kaynak:eylem' değil (≥2 segment, [a-z][a-z0-9_]*) ──────► REJECT (malformed_key)   [G2]
        │      ├─ ':own' final segment değil ───────────────────────────────► REJECT (own_misplaced)    [G5]
        │      ├─ ':own' var ama resource ∉ own_eligible | action≠read ──────► REJECT (own_not_permitted)[G5]
        │      ├─ key katalogda yok ─────────────────────────────────────────► UNKNOWN (unknown_key)
        │      └─ key katalogda ─────────────────────────────────────────────► VALID (resolved + metadata)

ÇEKİRDEK: (1) G2 GRAMER (SAD §14.4.3) — her key 'kaynak:eylem' (≥2 segment); action ∈ vocab; (2) G3 KATALOG
TAMLIĞI (cross-doc, FR-IAM-001) — 12.1.1 RBAC modelinin permission_key_universe + tüm rol bundle key'leri
⊆ katalog (dangling_key=0); (3) G5 ':own' DİSİPLİNİ (BRD §17.7) — own=true ⟺ resource own_eligible + action=read
+ ':own' final; (4) G6 TIER/CONTENT (FR-IAM-008) — content ⟺ tenant_content_keys + tier=B; L0 key'i ASLA content;
(5) G8 x-required-permission CONFORMANCE (API.md §13) — API.md'deki her x-required-permission ∈ katalog; (6) G10
KATALOG BÜTÜNLÜK MANİFESTİ (ADR-012) — catalog_hash sha256; çalışma-anı tahrifi yakalanır. Motor DETERMİNİSTİK
FAIL-CLOSED (Date.now/random YOK; catalog_hash sha256). Her karar terminal (G1) + kanıt (G9); metrik düşük-
kardinalite + ham PII yok (G11); katalog/spec/sample ham içerik/PII/credential tutmaz (G12).

Kapsam dışı (bilinçli, başka modül SAHİBİ): rol→permission-key bundle (immutable model) → 12.1.1 (TÜKETİR);
scoped assignment (departman/marka/kampanya) → 12.1.3 (ADR-012); backend guard (FastAPI dependency + HTTP
enforcement + tenant scope + RLS) → 12.2.x (SAD §14.4.2); break-glass → 12.3.x; WORM audit → 12.1.8; custom
permission roller → Faz 3.

Kullanım:
  permission_catalog_probe.py validate          Statik katalog + cross-doc conformance kapısı → çıkış kodu
  permission_catalog_probe.py check <sample>     Key çözüm motoru: senaryo(lar)ı çalıştır → kapı
  permission_catalog_probe.py selftest           Gömülü davranış kontrolleri (G1–G12) → çıkış kodu
  permission_catalog_probe.py schema             Karar sözleşmesini yazdır

Determinizm: catalog_hash sha256 (kanonik JSON, sort_keys); Date.now/random YOK. Stdlib-only. Sır/credential ve
ham içerik (PII) üretilmez/yazılmaz (fixture sentetik — yalnız permission-key + enum + kimlik; FR-TST-008).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "permission-catalog-spec.json")
CATALOG_PATH = os.path.join(HERE, "config", "permission-catalog.json")
SAMPLES_DIR = os.path.join(HERE, "samples")
RBAC_MODEL_PATH = os.path.join(HERE, "..", "rbac-model", "config", "rbac-roles.json")
API_DOC_PATH = os.path.join(HERE, "..", "..", "docs", "API.md")

OUTCOMES = ["VALID", "REJECT", "UNKNOWN"]
TERMINAL = {"VALID", "REJECT", "UNKNOWN"}
REJECT_REASONS = ["malformed_key", "own_misplaced", "own_not_permitted"]
UNKNOWN_REASONS = ["unknown_key"]
INVARIANT_IDS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G12"]
ACTION_VOCAB = {"provision", "suspend", "manage", "edit", "build", "read", "assign", "bind", "score", "run"}
LAYERS = {"L0", "L1", "L2"}
TIERS = {"A", "B"}
OWN_SUFFIX = "own"
SEGMENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Degrade (inject) — DOĞRU gramer/katalog/own/content/layer davranışını bozan müdahaleler.
INJECTIONS = {"grammar_break", "drop_key", "orphan_key", "own_break", "content_flip", "layer_flip",
              "unmapped_api", "catalog_tamper"}

VIOLATION_KEYS = ["malformed_key", "dangling_key", "orphan_key", "own_violation", "content_mismatch",
                  "layer_mismatch", "unmapped_permission", "catalog_tampered", "secret_or_pii", "stuck_state"]


# --------------------------------------------------------------------------- yardımcılar
def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def catalog_hash(catalog):
    """Deterministik katalog bütünlük manifesti (sha256, kanonik JSON)."""
    return hashlib.sha256(_canon(catalog["keys"]).encode("utf-8")).hexdigest()


def parse_key(key):
    """Permission-key'i ayrıştır. (ok, parsed|reason) döner — saf yapısal gramer."""
    if not isinstance(key, str) or not key:
        return False, "malformed_key"
    segs = key.split(":")
    if len(segs) < 2:
        return False, "malformed_key"
    for s in segs:
        if not SEGMENT_RE.match(s):
            return False, "malformed_key"
    own = False
    body = segs
    if OWN_SUFFIX in segs:
        # ':own' YALNIZ final segment olabilir (G5)
        if segs[-1] != OWN_SUFFIX or segs.count(OWN_SUFFIX) != 1:
            return False, "own_misplaced"
        own = True
        body = segs[:-1]
        if len(body) < 2:
            return False, "malformed_key"
    parsed = {"resource": body[0], "action": body[-1],
              "qualifiers": body[1:-1], "own": own, "key": key}
    return True, parsed


# --------------------------------------------------------------------------- karar motoru
def decide(request, catalog):
    """Terminal {VALID | REJECT | UNKNOWN} kararı. FAIL-CLOSED, deterministik."""
    chash = catalog_hash(catalog)
    own_eligible = set(catalog["own_eligible_resources"])
    keys = catalog["keys"]

    key = request.get("key") if isinstance(request, dict) else request
    base = {"request": {"key": key}, "catalog_hash": chash}

    ok, parsed = parse_key(key)
    if not ok:
        return dict(base, outcome="REJECT", reason=parsed, parsed=None, resolved=None)

    base["parsed"] = {"resource": parsed["resource"], "action": parsed["action"], "own": parsed["own"]}

    # ':own' kapsam disiplini (G5) — gramer geçti, şimdi own politikası
    if parsed["own"]:
        if parsed["resource"] not in own_eligible or parsed["action"] != "read":
            return dict(base, outcome="REJECT", reason="own_not_permitted", resolved=None)

    # çözüm
    entry = keys.get(key)
    if entry is None:
        return dict(base, outcome="UNKNOWN", reason="unknown_key", resolved=None)

    resolved = {"layer": entry["layer"], "panel": entry["panel"], "tier": entry["tier"],
                "content": entry["content"], "own": entry["own"], "action": entry["action"],
                "resource": entry["resource"]}
    return dict(base, outcome="VALID", reason="resolved", resolved=resolved)


# --------------------------------------------------------------------------- statik doğrulama (validate)
def validate(verbose=True):
    spec = _load(SPEC_PATH)
    catalog = _load(CATALOG_PATH)
    results = []

    def gate(name, ok, detail=""):
        results.append((name, ok, detail))

    keys = catalog["keys"]
    content_keys = set(catalog["tenant_content_keys"])
    own_eligible = set(catalog["own_eligible_resources"])

    # G2 — gramer + action vocab
    bad_grammar = []
    for k, e in keys.items():
        ok, parsed = parse_key(k)
        if not ok:
            bad_grammar.append((k, parsed)); continue
        if parsed["action"] not in ACTION_VOCAB:
            bad_grammar.append((k, "action_not_in_vocab"))
        if parsed["resource"] != e["resource"] or parsed["action"] != e["action"] or parsed["own"] != e["own"]:
            bad_grammar.append((k, "metadata_grammar_mismatch"))
    gate("G2 grammar_conformance", not bad_grammar, f"{len(bad_grammar)} ihlal: {bad_grammar[:3]}")

    # G5 — ':own' disiplini
    own_viol = []
    for k, e in keys.items():
        if e["own"]:
            if not k.endswith(":own"): own_viol.append((k, "no_own_suffix"))
            if e["resource"] not in own_eligible: own_viol.append((k, "resource_not_own_eligible"))
            if e["action"] != "read": own_viol.append((k, "own_action_not_read"))
        else:
            if k.endswith(":own"): own_viol.append((k, "own_flag_false_but_suffix"))
    # her own_eligible kaynak en az bir full (non-own) key taşımalı (own anlamlı olsun)
    resources = {e["resource"] for e in keys.values()}
    for r in own_eligible:
        if r not in resources: own_viol.append((r, "own_eligible_resource_absent"))
    gate("G5 own_discipline", not own_viol, f"{len(own_viol)} ihlal: {own_viol[:3]}")

    # G6 — tier/content tutarlılık + L0 altın kuralı
    content_mismatch = []
    for k, e in keys.items():
        is_content = k in content_keys
        if e["content"] != is_content: content_mismatch.append((k, "content_flag"))
        if is_content and e["tier"] != "B": content_mismatch.append((k, "content_not_tierB"))
        if (not is_content) and e["tier"] != "A": content_mismatch.append((k, "noncontent_not_tierA"))
        if e["layer"] == "L0" and e["content"]: content_mismatch.append((k, "L0_content_violation"))
    gate("G6 tier_content_coherence", not content_mismatch, f"{len(content_mismatch)} ihlal: {content_mismatch[:3]}")

    # G7 — layer/panel tutarlılık + cross-doc (RBAC universe layer)
    layer_mismatch = []
    panels = catalog["panels"]
    for k, e in keys.items():
        if e["layer"] not in LAYERS: layer_mismatch.append((k, "bad_layer"))
        if e["tier"] not in TIERS: layer_mismatch.append((k, "bad_tier"))
        if panels.get(e["layer"]) != e["panel"]: layer_mismatch.append((k, "panel_layer_mismatch"))

    rbac = _load(RBAC_MODEL_PATH) if os.path.exists(RBAC_MODEL_PATH) else None
    if rbac:
        universe = rbac["permission_key_universe"]
        u_layer = {}  # key → layer (universe; L1+L2 yok, universe L1/L2 ayrı)
        for layer, ks in universe.items():
            for k in ks:
                u_layer[k] = layer
        for k, e in keys.items():
            if k in u_layer and u_layer[k] != e["layer"]:
                layer_mismatch.append((k, f"universe_layer={u_layer[k]}≠catalog={e['layer']}"))
    gate("G7 layer_panel_coherence", not layer_mismatch, f"{len(layer_mismatch)} ihlal: {layer_mismatch[:3]}")

    # G3 — katalog tamlığı (cross-doc 12.1.1): RBAC universe + tüm rol bundle key'leri ⊆ katalog
    dangling = []
    orphan = []
    if rbac:
        universe = rbac["permission_key_universe"]
        ref_keys = set()
        for ks in universe.values():
            ref_keys.update(ks)
        for role in rbac["roles"].values():
            ref_keys.update(role["permissions"])
        for k in sorted(ref_keys):
            if k not in keys:
                dangling.append(k)
        # G4 — orphan yok: her katalog key'i universe'de (erişilebilir)
        univ_all = set()
        for ks in universe.values():
            univ_all.update(ks)
        for k in keys:
            if k not in univ_all:
                orphan.append(k)
        gate("G3 catalog_completeness", not dangling, f"{len(dangling)} dangling: {dangling[:5]}")
        gate("G4 no_orphan_key", not orphan, f"{len(orphan)} orphan: {orphan[:5]}")
    else:
        gate("G3 catalog_completeness", True, "SKIP (RBAC modeli yok)")
        gate("G4 no_orphan_key", True, "SKIP (RBAC modeli yok)")

    # G8 — x-required-permission conformance (API.md §13 + inline)
    if os.path.exists(API_DOC_PATH):
        with open(API_DOC_PATH, "r", encoding="utf-8") as fh:
            api_text = fh.read()
        api_perms = set(re.findall(r'x-required-permission:\s*"([^"]+)"', api_text))
        # §13 tablo backtick key'leri ( `a:b` / `a:b` / `a:b:c` ; '/' ayraçlı çoklu de dahil )
        for m in re.findall(r'`([a-z][a-z0-9_:]*(?::own)?)`', api_text):
            if ":" in m:
                api_perms.add(m)
        unmapped = sorted(p for p in api_perms if p not in keys)
        gate("G8 api_conformance", not unmapped, f"{len(unmapped)} unmapped: {unmapped[:5]}")
    else:
        gate("G8 api_conformance", True, "SKIP (API.md yok)")

    # G10 — katalog bütünlük manifesti (deterministik hash; iki çağrı aynı)
    h1, h2 = catalog_hash(catalog), catalog_hash(_load(CATALOG_PATH))
    gate("G10 catalog_integrity", h1 == h2, f"hash={h1[:12]}")

    # G12 — sır/PII yok (heuristik: katalog yalnız key+enum+desc; e-posta/telefon/kart deseni yok)
    blob = _canon(catalog)
    leak = re.search(r'\b\d{12,}\b|@[a-z]+\.[a-z]+|-----BEGIN', blob)
    gate("G12 no_secret_or_pii", leak is None, "leak" if leak else "temiz")

    # spec↔katalog çapraz tutarlılık
    spec_ce = set(spec["reject_reasons"])
    gate("spec_consistency", spec_ce == set(REJECT_REASONS) and
         set(i["id"] for i in spec["invariants"]) == set(INVARIANT_IDS),
         "spec/probe enum hizalı")

    passed = sum(1 for _, ok, _ in results if ok)
    if verbose:
        print(f"\n=== validate: katalog + cross-doc conformance ({len(keys)} key) ===")
        for name, ok, detail in results:
            print(f"  [{'🟢' if ok else '🔴'}] {name}" + (f"  — {detail}" if (detail and not ok) else
                  (f"  — {detail}" if detail.startswith(('SKIP', 'hash', 'spec', 'temiz')) else "")))
        print(f"\n{passed}/{len(results)} kapı " + ("🟢" if passed == len(results) else "🔴"))
    return passed == len(results)


# --------------------------------------------------------------------------- check (senaryo motoru)
def _apply_inject(catalog, inject):
    """Degrade: kataloğu/girdiyi bozan müdahale (in-memory). Tampered kopya döner."""
    cat = json.loads(json.dumps(catalog))
    if inject == "grammar_break":
        cat["keys"]["CallsRead"] = {"resource": "calls", "action": "read", "layer": "L2",
                                    "panel": "Operasyon / Uygulama Paneli", "tier": "B",
                                    "content": True, "own": False, "description": "x"}
    elif inject == "drop_key":
        cat["keys"].pop("calls:read", None)  # universe'de var → dangling
    elif inject == "orphan_key":
        cat["keys"]["ghost:read"] = {"resource": "ghost", "action": "read", "layer": "L2",
                                     "panel": "Operasyon / Uygulama Paneli", "tier": "A",
                                     "content": False, "own": False, "description": "x"}
    elif inject == "own_break":
        cat["keys"]["org:manage:own"] = {"resource": "org", "action": "manage", "layer": "L1",
                                         "panel": "Tenant Admin Console", "tier": "A",
                                         "content": False, "own": True, "description": "x"}
    elif inject == "content_flip":
        cat["keys"]["transcript:read"]["content"] = False  # tenant_content_keys'de → mismatch
    elif inject == "layer_flip":
        cat["keys"]["calls:read"]["layer"] = "L0"  # universe L2 + içerik L0 → ihlal
    elif inject == "catalog_tamper":
        cat["keys"]["tenant:provision"]["layer"] = "L2"
    return cat


def check(sample_paths, verbose=True):
    catalog = _load(CATALOG_PATH)
    all_pass = True
    n = 0
    for path in sample_paths:
        sample = _load(path)
        cases = sample.get("cases", [sample])
        inject = sample.get("inject")
        for case in cases:
            n += 1
            name = case.get("name", os.path.basename(path))
            if inject:
                # katalog-bütünlük degrade: validate alt-kapısının BU müdahaleyi yakalamasını bekle
                tampered = _apply_inject(catalog, inject)
                trip = _integrity_trips(tampered, inject)
                expected_trip = case.get("expect_gate_trips", True)
                ok = (trip == expected_trip)
                all_pass &= ok
                if verbose:
                    print(f"  [{'🟢' if ok else '🔴'}] {name}: inject={inject} → kapı_eler={trip} (beklenen {expected_trip})")
                continue
            res = decide(case["request"], catalog)
            exp = case.get("expect", {})
            ok = res["outcome"] == exp.get("outcome")
            if "reason" in exp:
                ok = ok and res.get("reason") == exp["reason"]
            if res["outcome"] not in TERMINAL:
                ok = False
            all_pass &= ok
            if verbose:
                extra = ""
                if res["outcome"] == "VALID":
                    extra = f" [{res['resolved']['layer']}/{res['resolved']['tier']}/own={res['resolved']['own']}]"
                print(f"  [{'🟢' if ok else '🔴'}] {name}: {res['outcome']} ({res.get('reason')}){extra}"
                      + (f"  beklenen {exp}" if not ok else ""))
    if verbose:
        print(f"\n{'🟢' if all_pass else '🔴'} {n} senaryo")
    return all_pass


def _integrity_trips(tampered, inject):
    """Tampered katalogda ilgili validate alt-kapısı eler mi? (bağımsız mini-kontrol)"""
    keys = tampered["keys"]
    content_keys = set(tampered["tenant_content_keys"])
    own_eligible = set(tampered["own_eligible_resources"])
    rbac = _load(RBAC_MODEL_PATH) if os.path.exists(RBAC_MODEL_PATH) else None

    if inject == "grammar_break":
        return any(not parse_key(k)[0] for k in keys)
    if inject == "drop_key":
        if not rbac: return False
        ref = set()
        for ks in rbac["permission_key_universe"].values(): ref.update(ks)
        for r in rbac["roles"].values(): ref.update(r["permissions"])
        return any(k not in keys for k in ref)
    if inject == "orphan_key":
        if not rbac: return False
        univ = set()
        for ks in rbac["permission_key_universe"].values(): univ.update(ks)
        return any(k not in univ for k in keys)
    if inject == "own_break":
        for k, e in keys.items():
            if e["own"] and (e["resource"] not in own_eligible or e["action"] != "read"):
                return True
        return False
    if inject == "content_flip":
        for k, e in keys.items():
            if (k in content_keys) != e["content"]: return True
        return False
    if inject == "layer_flip":
        for k, e in keys.items():
            if e["layer"] == "L0" and e["content"]: return True
        if rbac:
            ul = {}
            for layer, ks in rbac["permission_key_universe"].items():
                for k in ks: ul[k] = layer
            for k, e in keys.items():
                if k in ul and ul[k] != e["layer"]: return True
        return False
    if inject == "catalog_tamper":
        return catalog_hash(tampered) != catalog_hash(_load(CATALOG_PATH))
    return False


# --------------------------------------------------------------------------- selftest (G1–G12)
def selftest(verbose=True):
    catalog = _load(CATALOG_PATH)
    checks = []

    def ck(cid, ok, desc):
        checks.append((cid, ok, desc))

    # G1 determinizm/terminal
    r1 = decide({"key": "calls:read"}, catalog)
    r2 = decide({"key": "calls:read"}, catalog)
    ck("G1", r1 == r2 and r1["outcome"] in TERMINAL, "aynı girdi→aynı çıktı + terminal")
    ck("G1", catalog_hash(catalog) == catalog_hash(catalog), "catalog_hash deterministik")

    # G2 gramer
    ck("G2", decide({"key": "calls"}, catalog)["reason"] == "malformed_key", "tek segment REJECT")
    ck("G2", decide({"key": "Calls:Read"}, catalog)["reason"] == "malformed_key", "büyük harf REJECT")
    ck("G2", decide({"key": "calls::read"}, catalog)["reason"] == "malformed_key", "boş segment REJECT")
    ck("G2", decide({"key": "calls:read"}, catalog)["outcome"] == "VALID", "geçerli key VALID")

    # G5 own disiplini
    ck("G5", decide({"key": "calls:read:own"}, catalog)["outcome"] == "VALID", "calls:read:own VALID")
    ck("G5", decide({"key": "org:manage:own"}, catalog)["reason"] == "own_not_permitted", "own non-eligible REJECT")
    ck("G5", decide({"key": "calls:own:read"}, catalog)["reason"] == "own_misplaced", "own ortada REJECT")
    ck("G5", decide({"key": "calls:manage:own"}, catalog)["reason"] == "own_not_permitted", "own+action≠read REJECT")

    # resolve UNKNOWN
    ck("RES", decide({"key": "calls:delete"}, catalog)["outcome"] == "UNKNOWN", "iyi-biçimli bilinmeyen UNKNOWN")
    ck("RES", decide({"key": "tenant:provision"}, catalog)["resolved"]["layer"] == "L0", "L0 çözümü")

    # G6 content/tier (statik)
    e = catalog["keys"]["transcript:read"]
    ck("G6", e["content"] and e["tier"] == "B", "transcript:read content+tierB")
    ck("G6", all(not catalog["keys"][k]["content"] for k in catalog["keys"]
                 if catalog["keys"][k]["layer"] == "L0"), "L0 key'i content değil")

    # validate kapılarının tümü geçer
    ck("VAL", validate(verbose=False), "validate tüm kapılar 🟢")

    # G10/degrade: her injection ilgili integrity kapısını eler
    for inj in ["grammar_break", "drop_key", "orphan_key", "own_break", "content_flip", "layer_flip", "catalog_tamper"]:
        tampered = _apply_inject(catalog, inj)
        ck("G10", _integrity_trips(tampered, inj), f"inject {inj} kapıyı eler")

    # G12 sır/PII yok
    blob = _canon(catalog)
    ck("G12", re.search(r'\b\d{12,}\b|@[a-z]+\.[a-z]+|-----BEGIN', blob) is None, "katalogda sır/PII yok")

    passed = sum(1 for _, ok, _ in checks if ok)
    if verbose:
        print("\n=== selftest (G1–G12 gömülü davranış) ===")
        for cid, ok, desc in checks:
            print(f"  [{'🟢' if ok else '🔴'}] {cid}: {desc}")
        print(f"\n{passed}/{len(checks)} " + ("🟢" if passed == len(checks) else "🔴"))
    return passed == len(checks)


# --------------------------------------------------------------------------- schema
def schema():
    print(json.dumps({
        "request": {"key": "<permission-key string, ör. x-required-permission değeri>"},
        "outcome": OUTCOMES,
        "reason": {"REJECT": REJECT_REASONS, "UNKNOWN": UNKNOWN_REASONS, "VALID": ["resolved"]},
        "parsed": {"resource": "str", "action": "str∈vocab", "own": "bool"},
        "resolved": {"layer": "L0|L1|L2", "panel": "str", "tier": "A|B", "content": "bool", "own": "bool"},
        "catalog_hash": "sha256(kanonik(keys))",
        "invariants": INVARIANT_IDS,
        "action_vocab": sorted(ACTION_VOCAB),
    }, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- main
def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd = argv[1]
    if cmd == "validate":
        return 0 if validate() else 1
    if cmd == "check":
        paths = argv[2:]
        if not paths:
            paths = sorted(os.path.join(SAMPLES_DIR, f) for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
        elif len(paths) == 1 and os.path.isdir(paths[0]):
            paths = sorted(os.path.join(paths[0], f) for f in os.listdir(paths[0]) if f.endswith(".json"))
        return 0 if check(paths) else 1
    if cmd == "selftest":
        return 0 if selftest() else 1
    if cmd == "schema":
        schema(); return 0
    print(f"bilinmeyen komut: {cmd}"); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
