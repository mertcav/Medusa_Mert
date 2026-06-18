#!/usr/bin/env python3
# WBS 13.4.5 — A-05 "Conversation Flow Editor" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countByType/entryNodes/hasSingleEntry/outgoingEdges/danglingEdges/
#               reachableNodeIds/unreachableNodes/deadEndNodes/nodesMissingConfig/hasHandoff/structurallyValid/
#               readyForTest/readyForPublish/flowValidity/tone'lar/assertNoPii) + samples/* akış doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (geçersiz/sorunlu akışlar beklendiği gibi yakalanır)
#   schema    — akış görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/flows.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a05-flows-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "flows", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "flows.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

NODE_TYPE_ORDER = ["start", "message", "collect", "decision", "tool", "handoff", "end"]
ENTRY_NODE_TYPE = "start"
TERMINAL_NODE_TYPES = ["handoff", "end"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey", "prompttext", "promptbody"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/flows.ts ile birebir) ─────────────────────────

def is_node_flow(flow):
    return flow["mode"] == "node_flow"


def node_by_id(nodes, nid):
    for n in nodes:
        if n["id"] == nid:
            return n
    return None


def node_id_set(nodes):
    return {n["id"] for n in nodes}


def count_by_type(nodes):
    acc = {t: 0 for t in NODE_TYPE_ORDER}
    for n in nodes:
        acc[n["type"]] += 1
    return acc


def entry_nodes(nodes):
    return [n for n in nodes if n["type"] == ENTRY_NODE_TYPE]


def has_single_entry(flow):
    return len(entry_nodes(flow["nodes"])) == 1


def outgoing_edges(flow, node_id):
    ids = node_id_set(flow["nodes"])
    return [e for e in flow["edges"] if e["from"] == node_id and e["to"] in ids]


def dangling_edges(flow):
    ids = node_id_set(flow["nodes"])
    return [e for e in flow["edges"] if e["from"] not in ids or e["to"] not in ids]


def is_dangling_edge(flow, edge):
    ids = node_id_set(flow["nodes"])
    return edge["from"] not in ids or edge["to"] not in ids


def reachable_node_ids(flow):
    ids = node_id_set(flow["nodes"])
    adj = {}
    for e in flow["edges"]:
        if e["from"] in ids and e["to"] in ids:
            adj.setdefault(e["from"], []).append(e["to"])
    seen = set()
    queue = deque()
    for n in entry_nodes(flow["nodes"]):
        if n["id"] not in seen:
            seen.add(n["id"])
            queue.append(n["id"])
    while queue:
        cur = queue.popleft()
        for nxt in adj.get(cur, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def unreachable_nodes(flow):
    r = reachable_node_ids(flow)
    return [n for n in flow["nodes"] if n["id"] not in r]


def dead_end_nodes(flow):
    return [n for n in flow["nodes"]
            if n["type"] not in TERMINAL_NODE_TYPES and len(outgoing_edges(flow, n["id"])) == 0]


def nodes_missing_config(flow):
    return [n for n in flow["nodes"] if not n["configComplete"]]


def has_handoff(flow):
    return any(n["type"] == "handoff" for n in flow["nodes"])


def structurally_valid(flow):
    return (has_single_entry(flow)
            and len(dangling_edges(flow)) == 0
            and len(unreachable_nodes(flow)) == 0
            and len(dead_end_nodes(flow)) == 0)


def ready_for_test(flow):
    return structurally_valid(flow) and len(nodes_missing_config(flow)) == 0


def ready_for_publish(flow):
    return ready_for_test(flow) and has_handoff(flow)


def flow_validity(flow):
    if not structurally_valid(flow):
        return "invalid"
    if len(nodes_missing_config(flow)) > 0 or not has_handoff(flow):
        return "warnings"
    return "valid"


def node_type_tone(t):
    return {"start": "info", "message": "neutral", "collect": "neutral", "decision": "info",
            "tool": "info", "handoff": "warning", "end": "neutral"}[t]


def validity_tone(v):
    return {"valid": "success", "warnings": "warning", "invalid": "danger"}[v]


def mode_tone(m):
    return "info" if m == "node_flow" else "neutral"


def ready_tone(b):
    return "success" if b else "warning"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/prompt-gövdesi alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_pii(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            low = k.lower()
            if low in FORBIDDEN_PII_KEYS or low in FORBIDDEN_SECRET_KEYS:
                return f"{path}.{k}"
            hit = assert_no_pii(v, f"{path}.{k}")
            if hit:
                return hit
    return None


# ── i18n yardımcıları ─────────────────────────────────────────────────────────────

def resolve(cat, dotted):
    cur = cat
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return None
    return cur if isinstance(cur, str) else None


def placeholders(s):
    return set(re.findall(r"\{(\w+)\}", s or ""))


def _extract_data_fields(ts):
    """flows.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── validate ───────────────────────────────────────────────────────────────────────

def cmd_validate():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    spec = load_json(SPEC_PATH)
    page = read_text(PAGE_PATH) if os.path.isfile(PAGE_PATH) else ""
    data = read_text(DATA_PATH) if os.path.isfile(DATA_PATH) else ""
    tr = load_json(TR_PATH)
    en = load_json(EN_PATH)

    # S0/S1 — ekran sayfası mevcut + işaretli + iskelet değil
    chk(spec.get("wbs") == "13.4.5", "S0 spec.wbs=13.4.5")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/flows/page.tsx mevcut")
    chk('data-screen="A-05"' in page, 'S1 data-screen="A-05" işaretli')
    chk("İskelet ekran — A-05" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/flows" in page, "S2 veri seam (lib/tenant/flows) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a05.*); hardcoded TR/EN cümle yok
    chk("screen.a05." in page, "S3 screen.a05.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/prompt-gövdesi-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/flows.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getFlowView assertNoPii çağırır")
    chk("prompttext" in [s.lower() for s in FORBIDDEN_SECRET_KEYS] and "apikey" in [s.lower() for s in FORBIDDEN_SECRET_KEYS], "S4 prompt gövdesi/tool sırrı (promptText/apiKey) yasak (NFR 10.6)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-AGT-003/010 karşılanır
    a05 = tr.get("screen", {}).get("a05", {})
    sec = a05.get("section", {})
    for s in ("summary", "validation", "node_types", "nodes", "transitions"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk("node_flow" in data and set(["single_prompt", "node_flow"]).issubset(a05.get("mode", {}).keys()), "S5 konuşma modeli single/node-flow (FR-AGT-003)")
    chk(set(NODE_TYPE_ORDER).issubset(a05.get("node", {}).keys()), "S5 düğüm türleri (start/message/collect/decision/tool/handoff/end) i18n'de")
    chk("readyForTest" in data and "readyForPublish" in data and set(["single_entry", "no_dangling", "no_unreachable", "no_dead_end", "config_complete", "has_handoff"]).issubset(a05.get("gate", {}).keys()), "S5 test/yayın kapısı (FR-AGT-010)")
    chk("structurallyValid" in data and set(["valid", "warnings", "invalid"]).issubset(a05.get("validity", {}).keys()), "S5 akış doğrulama/geçerlilik")
    chk("hasHandoff" in data and "has_handoff" in a05.get("gate", {}), "S5 insan aktarımı (handoff) kapısı")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a05.{rk}"
        vt, ve = resolve(tr, full), resolve(en, full)
        if vt is None:
            missing_tr.append(rk)
        elif not vt.strip():
            empty.append(("tr", rk))
        if ve is None:
            missing_en.append(rk)
        elif not ve.strip():
            empty.append(("en", rk))
        if vt is not None and ve is not None and placeholders(vt) != placeholders(ve):
            ph_mismatch.append(rk)
    chk(not missing_tr, f"S6 TR referans anahtarları tam (eksik={missing_tr})")
    chk(not missing_en, f"S6 EN referans anahtarları tam (eksik={missing_en})")
    chk(not empty, f"S6 boş değer yok (boş={empty})")
    chk(not ph_mismatch, f"S6 TR↔EN placeholder parity (uyumsuz={ph_mismatch})")
    for key, phs in spec.get("placeholders", {}).items():
        vt = resolve(tr, f"screen.a05.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("isNodeFlow", "nodeById", "countByType", "entryNodes", "hasSingleEntry", "outgoingEdges",
               "danglingEdges", "isDanglingEdge", "reachableNodeIds", "unreachableNodes", "deadEndNodes",
               "nodesMissingConfig", "hasHandoff", "structurallyValid", "readyForTest", "readyForPublish",
               "flowValidity", "nodeTypeTone", "validityTone", "modeTone", "readyTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("NODE_TYPE_ORDER" in data and "TERMINAL_NODE_TYPES" in data, "S7 NODE_TYPE_ORDER + TERMINAL_NODE_TYPES sabitleri tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "splunk", "sumologic", "twilio.com", "telnyx.com"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── check ────────────────────────────────────────────────────────────────────────

def _node(nid, ntype, config=True, prompt=None, tool=None):
    return {"id": nid, "type": ntype, "label": nid, "promptRef": prompt, "toolRef": tool, "configComplete": config}


def _edge(a, b, cond=None):
    return {"from": a, "to": b, "condition": cond}


def _valid_flow():
    return {
        "flowRef": "FLOW-T", "mode": "node_flow", "versionNo": 1,
        "nodes": [_node("N1", "start"), _node("N2", "message", prompt="P1"), _node("N3", "decision"),
                  _node("N4", "tool", tool="T1"), _node("N5", "handoff"), _node("N6", "end")],
        "edges": [_edge("N1", "N2"), _edge("N2", "N3"), _edge("N3", "N4", "a"), _edge("N3", "N5", "b"),
                  _edge("N4", "N6"), _edge("N5", "N6")],
    }


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    f = _valid_flow()
    chk(is_node_flow(f) is True, "isNodeFlow=True")
    chk(count_by_type(f["nodes"]) == {"start": 1, "message": 1, "collect": 0, "decision": 1, "tool": 1, "handoff": 1, "end": 1}, "countByType")
    chk([n["id"] for n in entry_nodes(f["nodes"])] == ["N1"], "entryNodes=[N1]")
    chk(has_single_entry(f) is True, "hasSingleEntry=True")
    chk([e["to"] for e in outgoing_edges(f, "N3")] == ["N4", "N5"], "outgoingEdges(N3)=[N4,N5]")
    chk(dangling_edges(f) == [], "danglingEdges=[]")
    chk(reachable_node_ids(f) == {"N1", "N2", "N3", "N4", "N5", "N6"}, "reachableNodeIds=all")
    chk(unreachable_nodes(f) == [], "unreachableNodes=[]")
    chk(dead_end_nodes(f) == [], "deadEndNodes=[]")
    chk(nodes_missing_config(f) == [], "nodesMissingConfig=[]")
    chk(has_handoff(f) is True, "hasHandoff=True")
    chk(structurally_valid(f) is True, "structurallyValid=True")
    chk(ready_for_test(f) is True, "readyForTest=True")
    chk(ready_for_publish(f) is True, "readyForPublish=True")
    chk(flow_validity(f) == "valid", "flowValidity=valid")

    # asılı geçiş → yapısal geçersiz
    dang = _valid_flow()
    dang["edges"].append(_edge("N3", "NX", "x"))   # NX yok
    chk(len(dangling_edges(dang)) == 1, "danglingEdges=1 (NX yok)")
    chk(is_dangling_edge(dang, _edge("N3", "NX")) is True, "isDanglingEdge=True")
    chk(structurally_valid(dang) is False, "structurallyValid=False (asılı)")
    chk(flow_validity(dang) == "invalid", "flowValidity=invalid (asılı)")

    # erişilemez düğüm
    unr = _valid_flow()
    unr["nodes"].append(_node("N9", "message", prompt="P9"))   # bağlantısız → erişilemez + çıkmaz
    chk([n["id"] for n in unreachable_nodes(unr)] == ["N9"], "unreachableNodes=[N9]")
    chk([n["id"] for n in dead_end_nodes(unr)] == ["N9"], "deadEndNodes=[N9]")
    chk(structurally_valid(unr) is False, "structurallyValid=False (erişilemez)")

    # çıkmaz: terminal-olmayan + giden geçişi yok
    de = _valid_flow()
    de["edges"] = [e for e in de["edges"] if e["from"] != "N4"]   # N4 (tool) artık çıkmaz
    chk([n["id"] for n in dead_end_nodes(de)] == ["N4"], "deadEndNodes=[N4] (giden geçiş silindi)")
    chk("N6" not in [n["id"] for n in dead_end_nodes(_valid_flow())], "end düğümü çıkmaz sayılmaz (terminal)")
    chk("N5" not in [n["id"] for n in dead_end_nodes(_valid_flow())], "handoff düğümü çıkmaz sayılmaz (terminal)")

    # eksik config → test'e hazır değil ama yapısal geçerli → warnings
    mc = _valid_flow()
    mc["nodes"][1]["configComplete"] = False
    chk(structurally_valid(mc) is True, "structurallyValid=True (config ayrı)")
    chk(ready_for_test(mc) is False, "readyForTest=False (config eksik)")
    chk(flow_validity(mc) == "warnings", "flowValidity=warnings (config eksik)")

    # handoff yok → yapısal geçerli + test'e hazır ama yayına hazır değil → warnings
    nh = _valid_flow()
    nh["nodes"] = [_node("N1", "start"), _node("N2", "message", prompt="P1"), _node("N3", "end")]
    nh["edges"] = [_edge("N1", "N2"), _edge("N2", "N3")]
    chk(has_handoff(nh) is False, "hasHandoff=False")
    chk(ready_for_test(nh) is True, "readyForTest=True (yapısal+config)")
    chk(ready_for_publish(nh) is False, "readyForPublish=False (handoff yok)")
    chk(flow_validity(nh) == "warnings", "flowValidity=warnings (handoff yok)")

    # giriş yok / çoklu giriş
    no_entry = {"flowRef": "F", "mode": "node_flow", "versionNo": 1,
                "nodes": [_node("A", "message", prompt="P"), _node("B", "end")], "edges": [_edge("A", "B")]}
    chk(has_single_entry(no_entry) is False, "hasSingleEntry=False (giriş yok)")
    chk(structurally_valid(no_entry) is False, "structurallyValid=False (giriş yok)")
    multi = _valid_flow()
    multi["nodes"].append(_node("N0", "start"))
    chk(has_single_entry(multi) is False, "hasSingleEntry=False (çoklu giriş)")

    # tone eşlemeleri
    chk(node_type_tone("start") == "info" and node_type_tone("handoff") == "warning" and node_type_tone("message") == "neutral", "nodeTypeTone")
    chk(validity_tone("valid") == "success" and validity_tone("warnings") == "warning" and validity_tone("invalid") == "danger", "validityTone")
    chk(mode_tone("node_flow") == "info" and mode_tone("single_prompt") == "neutral", "modeTone")
    chk(ready_tone(True) == "success" and ready_tone(False) == "warning", "readyTone")

    # assertNoPii — konfigürasyon META İZİNLİ, ham içerik + sır + prompt-gövdesi YASAK
    chk(assert_no_pii({"a": _valid_flow()}) is None, "assertNoPii konfigürasyon META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii tool sırrı yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"promptText": "..."}}) == "$.x.promptText", "assertNoPii prompt gövdesi yakalar (A-06 derin)")

    # samples doğrulaması
    for name in ("flow-valid.json", "flow-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        fl = snp["flow"]
        chk(len(fl["nodes"]) == exp.get("nodes"), f"{name} nodes={exp.get('nodes')}")
        chk(len(fl["edges"]) == exp.get("edges"), f"{name} edges={exp.get('edges')}")
        chk(has_single_entry(fl) == exp.get("single_entry"), f"{name} single_entry={exp.get('single_entry')}")
        chk(len(dangling_edges(fl)) == exp.get("dangling"), f"{name} dangling={exp.get('dangling')}")
        chk(len(unreachable_nodes(fl)) == exp.get("unreachable"), f"{name} unreachable={exp.get('unreachable')}")
        chk(len(dead_end_nodes(fl)) == exp.get("dead_end"), f"{name} dead_end={exp.get('dead_end')}")
        chk(len(nodes_missing_config(fl)) == exp.get("missing_config"), f"{name} missing_config={exp.get('missing_config')}")
        chk(has_handoff(fl) == exp.get("has_handoff"), f"{name} has_handoff={exp.get('has_handoff')}")
        chk(structurally_valid(fl) == exp.get("structurally_valid"), f"{name} structurally_valid={exp.get('structurally_valid')}")
        chk(ready_for_test(fl) == exp.get("ready_test"), f"{name} ready_test={exp.get('ready_test')}")
        chk(ready_for_publish(fl) == exp.get("ready_publish"), f"{name} ready_publish={exp.get('ready_publish')}")
        chk(flow_validity(fl) == exp.get("validity"), f"{name} validity={exp.get('validity')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır-free (HİJYEN+GÜVENLİK)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\ncheck: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── selftest ────────────────────────────────────────────────────────────────────

def cmd_selftest():
    results = []

    def expect(cond, label):
        results.append((bool(cond), label))

    # pozitif (yayına hazır akış)
    ok = _valid_flow()
    expect(structurally_valid(ok) is True, "pos yapısal geçerli")
    expect(ready_for_test(ok) is True, "pos test'e hazır")
    expect(ready_for_publish(ok) is True, "pos yayına hazır")
    expect(flow_validity(ok) == "valid", "pos geçerlilik=valid")
    expect(unreachable_nodes(ok) == [] and dead_end_nodes(ok) == [], "pos erişilemez+çıkmaz yok")

    # negatif (çok-sorunlu akış: asılı + erişilemez + çıkmaz + eksik config + handoff yok)
    bad = {
        "flowRef": "F", "mode": "node_flow", "versionNo": 1,
        "nodes": [_node("A", "start"), _node("B", "message", config=False, prompt="P"),
                  _node("C", "collect", prompt="P2"), _node("D", "end"),
                  _node("Z", "message", prompt="PZ")],   # Z bağlantısız → erişilemez + çıkmaz
        "edges": [_edge("A", "B"), _edge("B", "C"), _edge("C", "Q", "x")],  # Q yok → asılı; C çıkmaz; D erişilemez
    }
    expect(has_single_entry(bad) is True, "neg tek giriş var")
    expect(len(dangling_edges(bad)) == 1, "neg asılı geçiş=1 (Q yok)")
    expect(sorted(n["id"] for n in unreachable_nodes(bad)) == ["D", "Z"], "neg erişilemez=[D,Z]")
    expect(sorted(n["id"] for n in dead_end_nodes(bad)) == ["C", "Z"], "neg çıkmaz=[C,Z]")
    expect([n["id"] for n in nodes_missing_config(bad)] == ["B"], "neg eksik config=[B]")
    expect(has_handoff(bad) is False, "neg handoff yok")
    expect(structurally_valid(bad) is False, "neg yapısal geçersiz")
    expect(ready_for_test(bad) is False, "neg test'e hazır değil")
    expect(ready_for_publish(bad) is False, "neg yayına hazır değil")
    expect(flow_validity(bad) == "invalid", "neg geçerlilik=invalid")

    # sınır: erişilemezlik geçerli geçişi izler (asılı geçiş erişilebilirlik sağlamaz)
    iso = {"flowRef": "F", "mode": "node_flow", "versionNo": 1,
           "nodes": [_node("A", "start"), _node("B", "end"), _node("C", "end")],
           "edges": [_edge("A", "B"), _edge("X", "C")]}   # X→C asılı; C erişilemez
    expect([n["id"] for n in unreachable_nodes(iso)] == ["C"], "sınır asılı kaynak erişilebilirlik vermez")

    # sınır: tek-prompt modu (grafik yok)
    sp = {"flowRef": "F", "mode": "single_prompt", "versionNo": 1, "nodes": [], "edges": []}
    expect(is_node_flow(sp) is False, "sınır tek-prompt modu")
    expect(has_single_entry(sp) is False, "sınır tek-prompt giriş yok (sayfa EmptyState gösterir)")

    # sınır: warnings (yapısal geçerli ama config eksik)
    warn = _valid_flow()
    warn["nodes"][2]["configComplete"] = False
    expect(flow_validity(warn) == "warnings", "sınır config eksik → warnings")
    expect(ready_for_test(warn) is False, "sınır config eksik → test'e hazır değil")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"webhookSecret": "x"}]}) is not None, "neg webhookSecret yakalanır")
    expect(assert_no_pii({"x": {"promptBody": "..."}}) is not None, "neg promptBody yakalanır (A-06 derin)")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")

    # tone sınır
    expect(validity_tone("invalid") == "danger", "neg geçersiz → danger")
    expect(node_type_tone("handoff") == "warning", "handoff → warning")

    # placeholder ayrıştırma
    expect(placeholders("{count} sorun") == {"count"}, "placeholder parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 90, "spec ≥90 referans anahtar")
    expect(spec["node_types"] == NODE_TYPE_ORDER, "spec node_types = NODE_TYPE_ORDER")
    expect(spec["terminal_node_types"] == TERMINAL_NODE_TYPES, "spec terminal_node_types = TERMINAL_NODE_TYPES")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "FlowView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "agentRef": "str (akışı düzenlenen agent — tenant config)",
            "agentName": "str (agent adı — tenant config; PII değil)",
            "flow": {
                "flowRef": "str (gösterim referansı)",
                "mode": "single_prompt|node_flow (FR-AGT-003)",
                "versionNo": "int (DB §5.2 conversation_flow.version_no)",
                "nodes": [{"id": "str", "type": "start|message|collect|decision|tool|handoff|end",
                           "label": "str (tenant config; PII değil)",
                           "promptRef": "str|null (prompt REFERANSI — gövde A-06; gömülmez)",
                           "toolRef": "str|null (tool REFERANSI — kimlik bilgisi A-09; gömülmez)",
                           "configComplete": "bool"}],
                "edges": [{"from": "str", "to": "str", "condition": "str|null (koşul ETİKETİ — tenant config)"}]
            }
        },
        "node_types": NODE_TYPE_ORDER,
        "terminal_node_types": TERMINAL_NODE_TYPES,
        "hijyen": "A-05 yalnız KONFİGÜRASYON META gösterir (düğüm etiketi/tür/prompt-tool REFERANSI/geçiş koşul etiketi — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR/müşteri) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential + PROMPT GÖVDESİ (apiKey/webhookSecret/token/promptText/...) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Prompt gövdesi/tool kimlik bilgisi derin aksiyon → A-06/A-09 (görsel kapı). KONFİGÜRASYON ekranı — gerçek zamanlı DEĞİL (FR-ANA-012 dışı)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a05_flows_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
