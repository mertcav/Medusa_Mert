#!/usr/bin/env python3
# WBS 13.4.9 — A-09 "Tool/API Bağlama" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (allBindings/countByProtocol/escalatedBindings/orphanBindings/
#               unapprovedBindings/unvalidatedBindings/unconfirmedSensitiveTools/tone'lar/assertNoPii) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (yetki-yükseltme/onaysız-endpoint/orphan/teyitsiz-hassas yakalanır)
#   schema    — tool/bağ görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/tools.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a09-tools-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "tools", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "tools.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

PROTOCOL_ORDER = ["rest", "soap", "graphql", "webhook"]
ACCESS_ORDER = ["read", "write"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "signingsecret",
                         "token", "bearertoken", "accesstoken", "refreshtoken", "credential", "password",
                         "privatekey", "kmskey", "authheader", "endpoint", "endpointurl", "url", "baseurl",
                         "webhookurl", "uri", "payload", "requestbody", "responsebody", "schemabody", "jsonschema"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/tools.ts ile birebir) ────────────────────────────

def sorted_tools(view):
    return sorted(view["tools"], key=lambda t: t["toolRef"])


def sorted_agents(view):
    return sorted(view["agents"], key=lambda a: a["agentRef"])


def tool_index(view):
    return {t["toolRef"]: t for t in view["tools"]}


def all_bindings(view):
    idx = tool_index(view)
    rows = []
    for a in view["agents"]:
        for b in a["bindings"]:
            row = dict(b)
            row["agentRef"] = a["agentRef"]
            row["agentName"] = a["agentName"]
            row["tool"] = idx.get(b["toolRef"])  # None → orphan
            rows.append(row)
    return sorted(rows, key=lambda r: (r["agentRef"], r["bindRef"]))


def count_by_protocol(tools):
    acc = {p: 0 for p in PROTOCOL_ORDER}
    for t in tools:
        acc[t["protocol"]] += 1
    return acc


def count_by_access_level(tools):
    acc = {a: 0 for a in ACCESS_ORDER}
    for t in tools:
        acc[t["accessLevel"]] += 1
    return acc


def read_tools(tools):
    return [t for t in tools if t["accessLevel"] == "read"]


def write_tools(tools):
    return [t for t in tools if t["accessLevel"] == "write"]


def unvalidated_tools(tools):
    return [t for t in tools if not t["schemaValidated"]]


def unapproved_tools(tools):
    return [t for t in tools if not t["endpointApproved"]]


def confirmation_tools(tools):
    return [t for t in tools if t["requiresConfirmation"]]


def sensitive_tools(tools):
    return [t for t in tools if t["sensitiveAction"]]


def async_tools(tools):
    return [t for t in tools if t["async"]]


def unconfirmed_sensitive_tools(tools):
    return [t for t in tools if t["sensitiveAction"] and not t["requiresConfirmation"]]


def binding_count_for_tool(view, tool_ref):
    return len([b for b in all_bindings(view) if b["toolRef"] == tool_ref])


def active_bindings(view):
    return [b for b in all_bindings(view) if b["status"] == "active"]


def disabled_bindings(view):
    return [b for b in all_bindings(view) if b["status"] == "disabled"]


def write_grant_bindings(view):
    return [b for b in all_bindings(view) if b["grant"] == "write"]


def escalated_bindings(view):
    return [b for b in all_bindings(view)
            if b["tool"] is not None and b["grant"] == "write" and b["tool"]["accessLevel"] == "read"]


def orphan_bindings(view):
    return [b for b in all_bindings(view) if b["tool"] is None]


def unapproved_bindings(view):
    return [b for b in all_bindings(view)
            if b["status"] == "active" and b["tool"] is not None and not b["tool"]["endpointApproved"]]


def unvalidated_bindings(view):
    return [b for b in all_bindings(view)
            if b["status"] == "active" and b["tool"] is not None and not b["tool"]["schemaValidated"]]


def sensitive_write_bindings(view):
    return [b for b in all_bindings(view)
            if b["status"] == "active" and b["grant"] == "write" and b["tool"] is not None and b["tool"]["sensitiveAction"]]


def open_attention_count(view):
    return (len(unapproved_bindings(view))
            + len(unvalidated_bindings(view))
            + len(escalated_bindings(view))
            + len(orphan_bindings(view))
            + len(unconfirmed_sensitive_tools(view["tools"])))


def protocol_tone(p):
    return {"rest": "neutral", "soap": "neutral", "graphql": "neutral", "webhook": "info"}[p]


def access_tone(a):
    return {"read": "neutral", "write": "warning"}[a]


def status_tone(s):
    return {"active": "success", "disabled": "neutral"}[s]


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/endpoint/schema/payload alan adı bulursa (path) döndürür; yoksa None."""
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
    """tools.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.9", "S0 spec.wbs=13.4.9")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/tools/page.tsx mevcut")
    chk('data-screen="A-09"' in page, 'S1 data-screen="A-09" işaretli')
    chk("İskelet ekran — A-09" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/tools" in page, "S2 veri seam (lib/tenant/tools) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a09.*); hardcoded TR/EN cümle yok
    chk("screen.a09." in page, "S3 screen.a09.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/endpoint/schema/payload-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/tools.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getToolBindingView assertNoPii çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("endpoint", "url", "payload", "schemabody")), "S4 endpoint/URL/payload/schema-gövdesi yasak (NFR 10.6)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır/endpoint alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-TOOL-001/002/004/005/006/007/011/012 karşılanır
    a09 = tr.get("screen", {}).get("a09", {})
    sec = a09.get("section", {})
    for s in ("summary", "bindings", "catalog", "protocols", "health"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk(set(PROTOCOL_ORDER).issubset(a09.get("protocol", {}).keys()) and "countByProtocol" in data, "S5 REST/SOAP/GraphQL/webhook (FR-TOOL-001)")
    chk("unvalidatedTools" in data and "schemaValidated" in data and "schema" in a09.get("health", {}), "S5 JSON schema doğrulama (FR-TOOL-002)")
    chk("writeGrantBindings" in data and "grant" in data and "col" in a09 and "grant" in a09["col"], "S5 agent bazında grant (FR-TOOL-004)")
    chk("escalatedBindings" in data and set(ACCESS_ORDER).issubset(a09.get("access", {}).keys()), "S5 okuma/yazma ayrımı + yetki yükseltme (FR-TOOL-005)")
    chk("confirmationTools" in data and "unconfirmed_sensitive" in a09.get("alert", {}), "S5 müşteri teyidi (FR-TOOL-006)")
    chk("sensitiveTools" in data and "sensitive_write" in a09.get("alert", {}), "S5 hassas işlem ek doğrulama (FR-TOOL-007)")
    chk("asyncTools" in data and "async" in a09.get("kpi", {}), "S5 asenkron workflow (FR-TOOL-011)")
    chk("unapprovedBindings" in data and "unapproved_endpoint" in a09.get("alert", {}), "S5 endpoint allowlist engelleme (FR-TOOL-012)")
    chk("orphanBindings" in data, "S5 bağ bütünlüğü (orphan tool referansı)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a09.{rk}"
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
        vt = resolve(tr, f"screen.a09.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedTools", "sortedAgents", "allBindings", "countByProtocol", "countByAccessLevel",
               "readTools", "writeTools", "unvalidatedTools", "unapprovedTools", "confirmationTools",
               "sensitiveTools", "asyncTools", "unconfirmedSensitiveTools", "bindingCountForTool",
               "activeBindings", "disabledBindings", "writeGrantBindings", "escalatedBindings",
               "orphanBindings", "unapprovedBindings", "unvalidatedBindings", "sensitiveWriteBindings",
               "openAttentionCount", "protocolTone", "accessTone", "statusTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("PROTOCOL_ORDER" in data and "ACCESS_ORDER" in data, "S7 PROTOCOL_ORDER + ACCESS_ORDER sabitleri tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "salesforce.com", "datadog.com", "secret=", "splunk", "zendesk.com", "twilio.com", "telnyx.com"]
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

def _tool(ref, protocol="rest", access="read", schema=True, endpoint=True, confirm=False, sensitive=False, async_=False):
    return {"toolRef": ref, "name": "Tool " + ref, "protocol": protocol, "accessLevel": access,
            "schemaValidated": schema, "endpointApproved": endpoint, "requiresConfirmation": confirm,
            "sensitiveAction": sensitive, "async": async_}


def _bind(ref, tool_ref, grant="read", status="active"):
    return {"bindRef": ref, "toolRef": tool_ref, "grant": grant, "status": status}


def _agent(ref, name, binds):
    return {"agentRef": ref, "agentName": name, "bindings": binds}


def _base_view():
    # 6 tool (read/write karışık; t04 şema-doğrulanmamış; t05 endpoint-onaysız+async; t06 teyitsiz-hassas) + 3 agent
    return {"generatedAt": "2026-06-18T09:00:00.000Z", "tenantRef": "TEN-1", "tenantName": "T",
            "tools": [
                _tool("TOOL-01", "rest", "read", True, True, False, False, False),
                _tool("TOOL-02", "rest", "write", True, True, True, True, False),
                _tool("TOOL-03", "soap", "write", True, True, True, False, False),
                _tool("TOOL-04", "graphql", "read", False, True, False, False, False),
                _tool("TOOL-05", "webhook", "write", True, False, True, False, True),
                _tool("TOOL-06", "rest", "write", True, True, False, True, False),
            ],
            "agents": [
                _agent("AGT-117", "A", [_bind("BND-01", "TOOL-01", "read"), _bind("BND-02", "TOOL-02", "write"), _bind("BND-03", "TOOL-04", "read")]),
                _agent("AGT-204", "B", [_bind("BND-04", "TOOL-02", "write"), _bind("BND-05", "TOOL-05", "write"), _bind("BND-06", "TOOL-01", "write")]),
                _agent("AGT-309", "C", [_bind("BND-07", "TOOL-99", "read")]),
            ]}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    binds = all_bindings(v)
    chk([b["bindRef"] for b in binds] == ["BND-01", "BND-02", "BND-03", "BND-04", "BND-05", "BND-06", "BND-07"], "allBindings düzleştir+sırala")
    chk([t["toolRef"] for t in sorted_tools(v)] == ["TOOL-01", "TOOL-02", "TOOL-03", "TOOL-04", "TOOL-05", "TOOL-06"], "sortedTools ASC")
    chk([a["agentRef"] for a in sorted_agents(v)] == ["AGT-117", "AGT-204", "AGT-309"], "sortedAgents ASC")
    chk(count_by_protocol(v["tools"]) == {"rest": 3, "soap": 1, "graphql": 1, "webhook": 1}, "countByProtocol")
    chk(count_by_access_level(v["tools"]) == {"read": 2, "write": 4}, "countByAccessLevel")
    chk(len(read_tools(v["tools"])) == 2 and len(write_tools(v["tools"])) == 4, "readTools=2 writeTools=4")
    chk([t["toolRef"] for t in unvalidated_tools(v["tools"])] == ["TOOL-04"], "unvalidatedTools=[04] (FR-TOOL-002)")
    chk([t["toolRef"] for t in unapproved_tools(v["tools"])] == ["TOOL-05"], "unapprovedTools=[05] (FR-TOOL-012)")
    chk([t["toolRef"] for t in confirmation_tools(v["tools"])] == ["TOOL-02", "TOOL-03", "TOOL-05"], "confirmationTools (FR-TOOL-006)")
    chk([t["toolRef"] for t in sensitive_tools(v["tools"])] == ["TOOL-02", "TOOL-06"], "sensitiveTools (FR-TOOL-007)")
    chk([t["toolRef"] for t in async_tools(v["tools"])] == ["TOOL-05"], "asyncTools=[05] (FR-TOOL-011)")
    chk([t["toolRef"] for t in unconfirmed_sensitive_tools(v["tools"])] == ["TOOL-06"], "unconfirmedSensitiveTools=[06] (FR-TOOL-006/007)")
    chk(len(active_bindings(v)) == 7 and len(disabled_bindings(v)) == 0, "active=7 disabled=0")
    chk([b["bindRef"] for b in write_grant_bindings(v)] == ["BND-02", "BND-04", "BND-05", "BND-06"], "writeGrantBindings (FR-TOOL-004)")
    chk([b["bindRef"] for b in escalated_bindings(v)] == ["BND-06"], "escalatedBindings=[06] (write on read tool — FR-TOOL-005)")
    chk([b["bindRef"] for b in orphan_bindings(v)] == ["BND-07"], "orphanBindings=[07] (tool katalogda yok)")
    chk([b["bindRef"] for b in unapproved_bindings(v)] == ["BND-05"], "unapprovedBindings=[05] (FR-TOOL-012)")
    chk([b["bindRef"] for b in unvalidated_bindings(v)] == ["BND-03"], "unvalidatedBindings=[03] (FR-TOOL-002)")
    chk([b["bindRef"] for b in sensitive_write_bindings(v)] == ["BND-02", "BND-04"], "sensitiveWriteBindings=[02,04] (FR-TOOL-007)")
    chk(binding_count_for_tool(v, "TOOL-01") == 2 and binding_count_for_tool(v, "TOOL-02") == 2, "bindingCountForTool 01=2 02=2")
    chk(binding_count_for_tool(v, "TOOL-03") == 0 and binding_count_for_tool(v, "TOOL-04") == 1, "bindingCountForTool 03=0 04=1")
    # attention = unapproved(1)+unvalidated(1)+escalated(1)+orphan(1)+unconfirmedSensitive(1) = 5
    chk(open_attention_count(v) == 5, "openAttentionCount=5")

    # tone eşlemeleri
    chk(protocol_tone("rest") == "neutral" and protocol_tone("webhook") == "info", "protocolTone")
    chk(access_tone("read") == "neutral" and access_tone("write") == "warning", "accessTone")
    chk(status_tone("active") == "success" and status_tone("disabled") == "neutral", "statusTone")

    # assertNoPii — TOOL/BAĞ META İZİNLİ, ham içerik + sır + endpoint/payload YASAK
    chk(assert_no_pii({"a": _base_view()}) is None, "assertNoPii tool/bağ META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii sır yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"endpoint": "https://..."}}) == "$.x.endpoint", "assertNoPii endpoint URL yakalar (FR-TOOL-012)")
    chk(assert_no_pii({"x": {"payload": "..."}}) == "$.x.payload", "assertNoPii çağrı payload'ı yakalar")
    chk(assert_no_pii({"x": {"schemaBody": {}}}) == "$.x.schemaBody", "assertNoPii JSON schema gövdesi yakalar")

    # samples doğrulaması
    for name in ("tools-clean.json", "tools-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        chk(len(snp["tools"]) == exp.get("tools"), f"{name} tools={exp.get('tools')}")
        chk(len(snp["agents"]) == exp.get("agents"), f"{name} agents={exp.get('agents')}")
        chk(len(all_bindings(snp)) == exp.get("bindings"), f"{name} bindings={exp.get('bindings')}")
        chk(len(write_grant_bindings(snp)) == exp.get("write_grants"), f"{name} write_grants={exp.get('write_grants')}")
        chk(len(escalated_bindings(snp)) == exp.get("escalated"), f"{name} escalated={exp.get('escalated')}")
        chk(len(orphan_bindings(snp)) == exp.get("orphans"), f"{name} orphans={exp.get('orphans')}")
        chk(len(unapproved_bindings(snp)) == exp.get("unapproved"), f"{name} unapproved={exp.get('unapproved')}")
        chk(len(unvalidated_bindings(snp)) == exp.get("unvalidated"), f"{name} unvalidated={exp.get('unvalidated')}")
        chk(len(unconfirmed_sensitive_tools(snp["tools"])) == exp.get("unconfirmed_sensitive"), f"{name} unconfirmed_sensitive={exp.get('unconfirmed_sensitive')}")
        chk(open_attention_count(snp) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır/endpoint-free (HİJYEN+GÜVENLİK)")

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

    # pozitif (sağlıklı: tüm schema doğrulanmış + endpoint onaylı + grant ≤ accessLevel + hassas teyitli + tool tanımlı)
    ok = {"tools": [
        _tool("T1", "rest", "read", True, True, False, False, False),
        _tool("T2", "rest", "write", True, True, True, True, False),
    ], "agents": [
        _agent("A1", "A", [_bind("B1", "T1", "read"), _bind("B2", "T2", "write")]),
    ]}
    expect(open_attention_count(ok) == 0, "pos açık dikkat=0")
    expect(len(escalated_bindings(ok)) == 0, "pos yetki yükseltme yok")
    expect(len(orphan_bindings(ok)) == 0, "pos orphan bağ yok")
    expect(len(unapproved_bindings(ok)) == 0, "pos onaysız endpoint bağı yok")
    expect(len(unvalidated_bindings(ok)) == 0, "pos doğrulanmamış schema bağı yok")
    expect(len(unconfirmed_sensitive_tools(ok["tools"])) == 0, "pos teyitsiz hassas tool yok")

    # negatif (çok-sorunlu: yetki-yükseltme + onaysız-endpoint + doğrulanmamış-schema + orphan + teyitsiz-hassas)
    bad = {"tools": [
        _tool("T1", "rest", "read", True, True, False, False, False),       # read tool
        _tool("T2", "webhook", "write", False, False, False, True, True),   # şema yok + endpoint onaysız + teyitsiz hassas
    ], "agents": [
        _agent("A1", "A", [
            _bind("B1", "T1", "write"),     # yetki yükseltme (T1 read)
            _bind("B2", "T2", "write"),     # onaysız endpoint + doğrulanmamış schema
            _bind("B3", "T99", "read"),     # orphan
        ]),
    ]}
    expect([b["bindRef"] for b in escalated_bindings(bad)] == ["B1"], "neg yetki yükseltme=[B1] (FR-TOOL-005)")
    expect([b["bindRef"] for b in unapproved_bindings(bad)] == ["B2"], "neg onaysız endpoint=[B2] (FR-TOOL-012)")
    expect([b["bindRef"] for b in unvalidated_bindings(bad)] == ["B2"], "neg doğrulanmamış schema=[B2] (FR-TOOL-002)")
    expect([b["bindRef"] for b in orphan_bindings(bad)] == ["B3"], "neg orphan=[B3]")
    expect([t["toolRef"] for t in unconfirmed_sensitive_tools(bad["tools"])] == ["T2"], "neg teyitsiz hassas=[T2] (FR-TOOL-006/007)")
    # attention = unapproved(1)+unvalidated(1)+escalated(1)+orphan(1)+unconfirmedSensitive(1) = 5
    expect(open_attention_count(bad) == 5, "neg açık dikkat=5")

    # sınır: boş envanter
    empty = {"tools": [], "agents": []}
    expect(all_bindings(empty) == [], "sınır boş envanter bağ yok")
    expect(open_attention_count(empty) == 0, "sınır boş envanter dikkat=0")
    expect(count_by_protocol([]) == {p: 0 for p in PROTOCOL_ORDER}, "sınır boş protokol dağılımı 0")

    # sınır: devre dışı bağ onaysız endpoint'e işaret etse de unapprovedBindings (yalnız AKTİF) saymaz
    dis = {"tools": [_tool("T1", "rest", "write", True, False)], "agents": [
        _agent("A1", "A", [_bind("B1", "T1", "write", "disabled")])]}
    expect(len(unapproved_bindings(dis)) == 0, "sınır devre dışı bağ onaysız saymaz (yalnız aktif)")
    expect(len(disabled_bindings(dis)) == 1, "sınır devre dışı bağ=1")

    # sınır: read-only tool'a read grant escalation DEĞİL
    rr = {"tools": [_tool("T1", "rest", "read", True, True)], "agents": [
        _agent("A1", "A", [_bind("B1", "T1", "read")])]}
    expect(len(escalated_bindings(rr)) == 0, "sınır read tool + read grant escalation değil")

    # sınır: write tool'a read grant — escalation DEĞİL (grant ≤ accessLevel)
    wr = {"tools": [_tool("T1", "rest", "write", True, True)], "agents": [
        _agent("A1", "A", [_bind("B1", "T1", "read")])]}
    expect(len(escalated_bindings(wr)) == 0, "sınır write tool + read grant escalation değil")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"bearerToken": "x"}]}) is not None, "neg bearerToken yakalanır")
    expect(assert_no_pii({"x": {"endpoint": "..."}}) is not None, "neg endpoint URL yakalanır (FR-TOOL-012)")
    expect(assert_no_pii({"x": {"requestBody": "..."}}) is not None, "neg istek payload'ı yakalanır")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")

    # tone sınır
    expect(access_tone("write") == "warning", "yazma → warning")
    expect(protocol_tone("webhook") == "info", "webhook → info")
    expect(status_tone("disabled") == "neutral", "devre dışı → neutral")

    # placeholder ayrıştırma
    expect(placeholders("{count} sorun") == {"count"}, "placeholder parse")
    expect(placeholders("{read} · {write}") == {"read", "write"}, "placeholder çoklu parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 85, "spec ≥85 referans anahtar")
    expect(spec["protocols"] == PROTOCOL_ORDER, "spec protocols = PROTOCOL_ORDER")
    expect(spec["access_levels"] == ACCESS_ORDER, "spec access_levels = ACCESS_ORDER")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "ToolBindingView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "tools": [{
                "toolRef": "str (Tool Registry gösterim kimliği)",
                "name": "str (kurumsal tool adı — tenant config; PII değil)",
                "protocol": "rest|soap|graphql|webhook (FR-TOOL-001)",
                "accessLevel": "read|write (FR-TOOL-005 — azami yetenek/güvenlik seviyesi)",
                "schemaValidated": "bool (FR-TOOL-002 — input/output JSON schema doğrulandı mı; yalnız BAYRAK)",
                "endpointApproved": "bool (FR-TOOL-012 — endpoint allowlist'te mi; URL gömülmez)",
                "requiresConfirmation": "bool (FR-TOOL-006 — kritik işlem müşteri teyidi)",
                "sensitiveAction": "bool (FR-TOOL-007 — para/sözleşme/PII değişikliği → ek doğrulama)",
                "async": "bool (FR-TOOL-011 — uzun süren işlem asenkron workflow)"
            }],
            "agents": [{
                "agentRef": "str (agent gösterim kimliği)",
                "agentName": "str (agent adı — tenant config; PII değil)",
                "bindings": [{
                    "bindRef": "str (bağ gösterim kimliği)",
                    "toolRef": "str (bağlı tool — kataloğa referans; çözülmezse orphan)",
                    "grant": "read|write (FR-TOOL-004/005 — bu agent'a verilen erişim; accessLevel'i AŞAMAZ)",
                    "status": "active|disabled (bağ durumu)"
                }]
            }]
        },
        "protocols": PROTOCOL_ORDER,
        "access_levels": ACCESS_ORDER,
        "binding_statuses": ["active", "disabled"],
        "invariants": "escalatedBindings (grant=write & tool.accessLevel=read — FR-TOOL-005) + unapprovedBindings (aktif & !endpointApproved — FR-TOOL-012) + unconfirmedSensitiveTools (sensitiveAction & !requiresConfirmation — FR-TOOL-006/007) + orphanBindings (tool katalogda yok) = sıfır olmalı (sağlıklı).",
        "hijyen": "A-09 yalnız TOOL/BAĞ META gösterir (protokol/erişim seviyesi/schema-endpoint-teyit-hassas-async BAYRAKLARI/grant/durum + tool/agent adı — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR/müşteri) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential + tool ENDPOINT URL'i + JSON SCHEMA GÖVDESİ + istek/yanıt PAYLOAD'ı (apiKey/token/secret/endpoint/url/payload/schemaBody) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Tool çağırma/bağlama derin aksiyon → API dilimi (görsel kapı). KONFİGÜRASYON ekranı (FR-TOOL-001/002/004/005/006/007/011/012); gerçek zamanlı DEĞİL."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a09_tools_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
