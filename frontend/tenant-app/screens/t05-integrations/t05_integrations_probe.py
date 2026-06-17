#!/usr/bin/env python3
# WBS 13.3.5 — T-05 "Entegrasyon, Tool & API Key/Webhook" doğrulama probe'u (stdlib-only, credential-free,
# deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countIntegrationState/invalidIntegrationRefs/
#               writeToolsWithoutConfirmation/toolsWithoutSchema/isHttpsUrl/insecureWebhookUrls/
#               failingWebhooks/apiKeysByStatus/tone'lar/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/integrations.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t05-integrations-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "integrations", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "integrations.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/integrations.ts ile birebir) ──────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "customer", "cardpan",
                      "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "signingsecret", "clientsecret",
                         "token", "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey"]

HTTPS_RE = re.compile(r"^https://[^\s]+$", re.I)


def count_integration_state(integrations):
    out = {"connected": 0, "degraded": 0, "disabled": 0, "error": 0}
    for i in integrations:
        out[i["state"]] += 1
    return out


def count_integration_type(integrations):
    out = {"crm": 0, "erp": 0, "ticketing": 0, "custom": 0}
    for i in integrations:
        out[i["type"]] += 1
    return out


def tools_for_integration(tools, integration_id):
    return sum(1 for t in tools if t["integrationRef"] == integration_id)


def invalid_integration_refs(tools, integrations):
    ids = {i["id"] for i in integrations}
    return [t["id"] for t in tools
            if t["integrationRef"] is not None and t["integrationRef"].strip() != "" and t["integrationRef"] not in ids]


def write_tools_without_confirmation(tools):
    return [t["id"] for t in tools if t["enabled"] and t["access"] == "write" and not t["confirmRequired"]]


def tools_without_schema(tools):
    return [t["id"] for t in tools if t["enabled"] and not t["schemaValidated"]]


def is_https_url(s):
    return bool(HTTPS_RE.match(s.strip()))


def insecure_webhook_urls(webhooks):
    return [w["id"] for w in webhooks if not is_https_url(w["url"])]


def failing_webhooks(webhooks):
    return [w["id"] for w in webhooks if w["status"] == "failing" or w["lastDeliveryOk"] is False]


def api_keys_by_status(api_keys, status):
    return [k["id"] for k in api_keys if k["status"] == status]


def integration_state_tone(s):
    return {"connected": "success", "degraded": "warning", "disabled": "neutral", "error": "danger"}[s]


def integration_type_tone(t):
    return {"crm": "info", "erp": "info", "ticketing": "info", "custom": "neutral"}[t]


def protocol_tone(p):
    return {"rest": "info", "soap": "neutral", "graphql": "info", "webhook": "neutral"}[p]


def tool_access_tone(a):
    return {"read": "info", "write": "warning"}[a]


def api_key_status_tone(s):
    return {"active": "success", "revoked": "neutral", "expired": "danger"}[s]


def webhook_status_tone(s):
    return {"active": "success", "disabled": "neutral", "failing": "danger"}[s]


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA entegrasyon/anahtar/webhook sırrı alan adı bulursa (path) döndürür; yoksa None."""
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
    chk(spec.get("wbs") == "13.3.5", "S0 spec.wbs=13.3.5")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/integrations/page.tsx mevcut")
    chk('data-screen="T-05"' in page, 'S1 data-screen="T-05" işaretli')
    chk("İskelet ekran — T-05" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/integrations" in page, "S2 veri seam (lib/tenant/integrations) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t05.*); hardcoded TR/EN cümle yok
    chk("screen.t05." in page, "S3 screen.t05.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + entegrasyon/anahtar/webhook-sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/integrations.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getIntegrations assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 üç içerik öğesi (entegrasyon/tool+credential/webhook) + FR-TOOL + API key karşılanır
    t05 = tr.get("screen", {}).get("t05", {})
    sec = t05.get("section", {})
    chk("integrations" in sec, "S5 CRM/ERP/ticketing entegrasyon → section.integrations")
    chk("tools" in sec, "S5 tool/credential → section.tools")
    chk("api_keys" in sec, "S5 API anahtarı → section.api_keys")
    chk("webhooks" in sec, "S5 webhook → section.webhooks")
    chk(set(["rest", "soap", "graphql", "webhook"]).issubset(t05.get("protocol", {}).keys()), "S5 protokoller REST/SOAP/GraphQL/webhook (FR-TOOL-001)")
    chk(set(["read", "write"]).issubset(t05.get("access", {}).keys()), "S5 okuma/yazma erişim (FR-TOOL-005)")
    chk("confirm" in t05.get("col", {}), "S5 müşteri teyidi kolonu (FR-TOOL-006/007)")
    chk("schema" in t05.get("col", {}), "S5 JSON schema doğrulama kolonu (FR-TOOL-002)")
    chk("crm" in t05.get("integration_type", {}) and "erp" in t05.get("integration_type", {}) and "ticketing" in t05.get("integration_type", {}), "S5 CRM/ERP/ticketing türleri (BRD §17.4)")
    chk("isHttpsUrl" in data and "insecureWebhookUrls" in data, "S5 webhook HTTPS doğrulama (API.md §10)")
    chk("invalidIntegrationRefs" in data and "writeToolsWithoutConfirmation" in data, "S5 tool bütünlük türetmeleri")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t05.{rk}"
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
        vt = resolve(tr, f"screen.t05.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("countIntegrationState", "countIntegrationType", "toolsForIntegration", "invalidIntegrationRefs",
               "writeToolsWithoutConfirmation", "toolsWithoutSchema", "isHttpsUrl", "insecureWebhookUrls",
               "failingWebhooks", "apiKeysByStatus", "integrationStateTone", "integrationTypeTone",
               "protocolTone", "toolAccessTone", "apiKeyStatusTone", "webhookStatusTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok (somut CRM/ERP/SaaS markası + literal sır taraması)
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "salesforce", "hubspot",
                         "zendesk", "servicenow", "sap.com", "dynamics365", "freshdesk"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def _extract_data_fields(ts):
    """integrations.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    integrations = [
        {"id": "INT-A", "type": "crm", "state": "connected"},
        {"id": "INT-B", "type": "erp", "state": "degraded"},
        {"id": "INT-C", "type": "ticketing", "state": "error"},
    ]
    tools = [
        {"id": "T1", "protocol": "rest", "access": "read", "schemaValidated": True, "confirmRequired": False, "integrationRef": "INT-A", "enabled": True},
        {"id": "T2", "protocol": "rest", "access": "write", "schemaValidated": True, "confirmRequired": False, "integrationRef": "INT-B", "enabled": True},  # yazma teyitsiz
        {"id": "T3", "protocol": "graphql", "access": "read", "schemaValidated": False, "confirmRequired": False, "integrationRef": "INT-GHOST", "enabled": True},  # geçersiz ref + schemasız
        {"id": "T4", "protocol": "soap", "access": "write", "schemaValidated": True, "confirmRequired": True, "integrationRef": None, "enabled": True},  # OK (teyitli)
    ]
    api_keys = [
        {"id": "K1", "status": "active"},
        {"id": "K2", "status": "revoked"},
        {"id": "K3", "status": "expired"},
    ]
    webhooks = [
        {"id": "W1", "url": "https://a.example/h", "status": "active", "lastDeliveryOk": True},
        {"id": "W2", "url": "http://b.example/h", "status": "active", "lastDeliveryOk": True},  # HTTPS değil
        {"id": "W3", "url": "https://c.example/h", "status": "failing", "lastDeliveryOk": False},  # başarısız
    ]

    chk(count_integration_state(integrations) == {"connected": 1, "degraded": 1, "disabled": 0, "error": 1}, "countIntegrationState")
    chk(count_integration_type(integrations) == {"crm": 1, "erp": 1, "ticketing": 1, "custom": 0}, "countIntegrationType")
    chk(tools_for_integration(tools, "INT-A") == 1, "toolsForIntegration INT-A=1")
    chk(invalid_integration_refs(tools, integrations) == ["T3"], "invalidIntegrationRefs=[T3] (INT-GHOST)")
    chk(write_tools_without_confirmation(tools) == ["T2"], "writeToolsWithoutConfirmation=[T2]")
    chk(tools_without_schema(tools) == ["T3"], "toolsWithoutSchema=[T3]")
    chk(is_https_url("https://x.example") and not is_https_url("http://x.example") and not is_https_url("ftp://x"), "isHttpsUrl")
    chk(insecure_webhook_urls(webhooks) == ["W2"], "insecureWebhookUrls=[W2]")
    chk(failing_webhooks(webhooks) == ["W3"], "failingWebhooks=[W3]")
    chk(api_keys_by_status(api_keys, "active") == ["K1"], "apiKeysByStatus active=[K1]")
    chk(api_keys_by_status(api_keys, "expired") == ["K3"], "apiKeysByStatus expired=[K3]")
    # tone eşlemeleri
    chk(integration_state_tone("connected") == "success" and integration_state_tone("degraded") == "warning" and integration_state_tone("error") == "danger", "integrationStateTone")
    chk(integration_type_tone("crm") == "info" and integration_type_tone("custom") == "neutral", "integrationTypeTone")
    chk(protocol_tone("rest") == "info" and protocol_tone("soap") == "neutral", "protocolTone")
    chk(tool_access_tone("read") == "info" and tool_access_tone("write") == "warning", "toolAccessTone")
    chk(api_key_status_tone("active") == "success" and api_key_status_tone("revoked") == "neutral" and api_key_status_tone("expired") == "danger", "apiKeyStatusTone")
    chk(webhook_status_tone("active") == "success" and webhook_status_tone("disabled") == "neutral" and webhook_status_tone("failing") == "danger", "webhookStatusTone")
    # assertNoPii — kendi konfigürasyon İZİNLİ, son-müşteri PII + sır YASAK
    chk(assert_no_pii({"webhooks": [{"url": "https://x.example", "events": ["call.completed"]}]}) is None, "assertNoPii kendi url/event İZİNLİ")
    chk(assert_no_pii({"tenantName": "Acme", "apiKeys": [{"name": "Üretim", "scopes": ["calls:read"]}]}) is None, "assertNoPii tenant/anahtar adı+scope İZİNLİ")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"key": {"secret": "x"}}) == "$.key.secret", "assertNoPii API key secret yakalar (NFR 10.6)")
    chk(assert_no_pii({"webhook": {"signingSecret": "x"}}) == "$.webhook.signingSecret", "assertNoPii webhook signing secret yakalar")
    chk(assert_no_pii({"int": {"clientSecret": "x"}}) == "$.int.clientSecret", "assertNoPii OAuth client secret yakalar")
    chk(assert_no_pii({"int": {"credential": "x"}}) == "$.int.credential", "assertNoPii entegrasyon credential yakalar")

    # samples doğrulaması
    for name in ("integrations-clean.json", "integrations-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        cs = count_integration_state(snap["integrations"])
        chk(cs["connected"] == exp.get("connected"), f"{name} connected={exp.get('connected')}")
        chk(invalid_integration_refs(snap["tools"], snap["integrations"]) == exp.get("invalid_refs"), f"{name} invalid_refs={exp.get('invalid_refs')}")
        chk(write_tools_without_confirmation(snap["tools"]) == exp.get("write_no_confirm"), f"{name} write_no_confirm={exp.get('write_no_confirm')}")
        chk(tools_without_schema(snap["tools"]) == exp.get("no_schema"), f"{name} no_schema={exp.get('no_schema')}")
        chk(insecure_webhook_urls(snap["webhooks"]) == exp.get("insecure_webhooks"), f"{name} insecure_webhooks={exp.get('insecure_webhooks')}")
        chk(failing_webhooks(snap["webhooks"]) == exp.get("failing_webhooks"), f"{name} failing_webhooks={exp.get('failing_webhooks')}")
        chk(api_keys_by_status(snap["apiKeys"], "active") == exp.get("active_keys"), f"{name} active_keys={exp.get('active_keys')}")
        chk(assert_no_pii(snap) is None, f"{name} PII/sır-free (HİJYEN+GÜVENLİK)")

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

    integrations = [{"id": "I1", "type": "crm", "state": "connected"}]
    tools = [{"id": "A", "protocol": "rest", "access": "read", "schemaValidated": True, "confirmRequired": False, "integrationRef": "I1", "enabled": True}]
    # pozitif
    expect(count_integration_state(integrations) == {"connected": 1, "degraded": 0, "disabled": 0, "error": 0}, "pos countIntegrationState")
    expect(count_integration_type(integrations) == {"crm": 1, "erp": 0, "ticketing": 0, "custom": 0}, "pos countIntegrationType")
    expect(tools_for_integration(tools, "I1") == 1, "pos toolsForIntegration")
    expect(invalid_integration_refs(tools, integrations) == [], "pos invalid ref boş")
    expect(write_tools_without_confirmation(tools) == [], "pos write-no-confirm boş (okuma)")
    expect(tools_without_schema(tools) == [], "pos no-schema boş")
    expect(insecure_webhook_urls([{"id": "W", "url": "https://x.example/h"}]) == [], "pos insecure boş")
    expect(failing_webhooks([{"id": "W", "url": "https://x", "status": "active", "lastDeliveryOk": True}]) == [], "pos failing boş")
    expect(api_keys_by_status([{"id": "K", "status": "active"}], "active") == ["K"], "pos active key")
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(is_https_url("https://a") is True and is_https_url("http://a") is False, "neg HTTPS sınır")
    expect(is_https_url("HTTPS://A.example/h") is True, "neg HTTPS büyük-küçük harf")
    expect(insecure_webhook_urls([{"id": "Z", "url": "http://x"}]) == ["Z"], "neg http webhook yakalanır")
    expect(write_tools_without_confirmation([{"id": "Z", "access": "write", "confirmRequired": False, "enabled": True, "schemaValidated": True}]) == ["Z"], "neg yazma-teyitsiz yakalanır")
    expect(write_tools_without_confirmation([{"id": "Z", "access": "write", "confirmRequired": False, "enabled": False, "schemaValidated": True}]) == [], "neg devre-dışı tool sayılmaz")
    expect(tools_without_schema([{"id": "Z", "schemaValidated": False, "enabled": True}]) == ["Z"], "neg schemasız tool yakalanır")
    expect(invalid_integration_refs([{"id": "Z", "integrationRef": "ghost"}], integrations) == ["Z"], "neg geçersiz ref yakalanır")
    expect(failing_webhooks([{"id": "Z", "url": "https://x", "status": "active", "lastDeliveryOk": False}]) == ["Z"], "neg son-teslimat-başarısız yakalanır")
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"callerId": "x"}) is not None, "neg son-müşteri callerId yakalanır")
    expect(assert_no_pii({"settings": [{"bearerToken": "x"}]}) is not None, "neg bearer token yakalanır")
    expect(api_key_status_tone("expired") == "danger", "neg süresi-dolan → danger")
    expect(tool_access_tone("write") == "warning", "neg yazma → warning")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 70, "spec ≥70 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "IntegrationSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "integrations": [{"id": "str", "name": "str (tenant etiketi — izinli)", "type": "crm|erp|ticketing|custom",
                              "authMethod": "oauth2|api_key|basic|mtls (YÖNTEM adı — sır DEĞİL)",
                              "state": "connected|degraded|disabled|error", "region": "str (residency kodu)",
                              "lastSyncAt": "ISO-8601|null"}],
            "tools": [{"id": "str", "name": "str (izinli)", "protocol": "rest|soap|graphql|webhook (FR-TOOL-001)",
                       "access": "read|write (FR-TOOL-005)", "schemaValidated": "bool (FR-TOOL-002)",
                       "confirmRequired": "bool (FR-TOOL-006/007)", "integrationRef": "str|null (Integration.id)",
                       "enabled": "bool"}],
            "apiKeys": [{"id": "str", "name": "str (izinli)", "scopes": "str[] (permission-key — izinli)",
                         "status": "active|revoked|expired", "createdAt": "ISO-8601", "lastUsedAt": "ISO-8601|null"}],
            "webhooks": [{"id": "str", "url": "str (HTTPS — izinli)", "events": "str[] (event tipi — izinli)",
                          "status": "active|disabled|failing", "lastDeliveryAt": "ISO-8601|null",
                          "lastDeliveryOk": "bool|null"}]
        },
        "hijyen": "FORBIDDEN_PII_KEYS dışı son-müşteri alanı yok (BRD §17.7); FORBIDDEN_SECRET_KEYS dışı entegrasyon/anahtar/webhook sırrı yok (NFR 10.6); assertNoPii çalışma-anında doğrular. name/url/scopes/events + tenant kimliği tenant'ın KENDİ konfigürasyonudur → izinli. SIR (secret/signing_secret/credential) yalnız oluşturmada bir kez döner; panele konmaz."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t05_integrations_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
