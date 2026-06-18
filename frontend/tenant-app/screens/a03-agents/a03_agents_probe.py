#!/usr/bin/env python3
# WBS 13.4.3 — A-03 "Agent Listesi" (Agent List) doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countByLifecycle/countByMode/productionAgents/
#               inDevelopmentAgents/hasPendingChanges/testBlocked/unboundProduction/missingActiveVersion/
#               variantAgents/distinctLanguages/attentionAgents/openAttentionCount/tone'lar/assertNoPii)
#               + samples/* envanter doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (sorunlu senaryolar beklendiği gibi yakalanır)
#   schema    — envanter şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/agents.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a03-agents-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "agents", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "agents.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

LIFECYCLE_ORDER = ["draft", "test", "staging", "production", "archived"]
IN_DEVELOPMENT = ["draft", "test", "staging"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/agents.ts ile birebir) ──────────────────────

def count_by(agents, field):
    out = {}
    for a in agents:
        out[a[field]] = out.get(a[field], 0) + 1
    return out


def count_by_lifecycle(agents):
    return count_by(agents, "lifecycle")


def count_by_mode(agents):
    return count_by(agents, "mode")


def agents_in_lifecycle(agents, state):
    return [a for a in agents if a["lifecycle"] == state]


def production_agents(agents):
    return [a for a in agents if a["lifecycle"] == "production"]


def in_development_agents(agents):
    return [a for a in agents if a["lifecycle"] in IN_DEVELOPMENT]


def has_pending_changes(a):
    return a["latestVersionNo"] > (a["activeVersionNo"] or 0)


def pending_changes_agents(agents):
    return [a for a in agents if has_pending_changes(a)]


def test_blocked(a):
    return a["lifecycle"] in ("staging", "production") and a["testStatus"] != "passed"


def test_blocked_agents(agents):
    return [a for a in agents if test_blocked(a)]


def unbound_production(a):
    return a["lifecycle"] == "production" and a["boundNumbers"] == 0 and a["boundCampaigns"] == 0


def unbound_production_agents(agents):
    return [a for a in agents if unbound_production(a)]


def missing_active_version(a):
    return a["lifecycle"] == "production" and a["activeVersionNo"] is None


def missing_active_version_agents(agents):
    return [a for a in agents if missing_active_version(a)]


def variant_agents(agents):
    return [a for a in agents if a["isVariant"]]


def distinct_languages(agents):
    s = set()
    for a in agents:
        for l in a["languages"]:
            s.add(l)
    return sorted(s)


def attention_agents(agents):
    return [a for a in agents if test_blocked(a) or unbound_production(a) or missing_active_version(a)]


def open_attention_count(view):
    return len(attention_agents(view["agents"]))


def lifecycle_tone(s):
    return {"draft": "neutral", "test": "info", "staging": "warning",
            "production": "success", "archived": "neutral"}[s]


def mode_tone(m):
    return {"single_prompt": "neutral", "node_flow": "info"}[m]


def test_tone(s):
    return {"passed": "success", "failed": "danger", "not_run": "warning"}[s]


def pending_tone(b):
    return "warning" if b else "neutral"


def variant_tone(b):
    return "info" if b else "neutral"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential alan adı bulursa (path) döndürür; yoksa None."""
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
    """agents.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.3", "S0 spec.wbs=13.4.3")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/agents/page.tsx mevcut")
    chk('data-screen="A-03"' in page, 'S1 data-screen="A-03" işaretli')
    chk("İskelet ekran — A-03" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/agents" in page, "S2 veri seam (lib/tenant/agents) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a03.*); hardcoded TR/EN cümle yok
    chk("screen.a03." in page, "S3 screen.a03.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/agents.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getAgentList assertNoPii çağırır")
    chk("webhooksecret" in [s.lower() for s in FORBIDDEN_SECRET_KEYS] and "apikey" in [s.lower() for s in FORBIDDEN_SECRET_KEYS], "S4 tool sırrı (apiKey/webhookSecret) yasak (NFR 10.6)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-AGT-003/004/005/006/007/008/010 karşılanır
    a03 = tr.get("screen", {}).get("a03", {})
    sec = a03.get("section", {})
    for s in ("summary", "lifecycle", "attention", "all"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk(set(LIFECYCLE_ORDER).issubset(a03.get("lifecycle", {}).keys()) and "lifecycle_state" in data.lower(), "S5 yaşam döngüsü durumları (FR-AGT-005)")
    chk(set(["single_prompt", "node_flow"]).issubset(a03.get("mode", {}).keys()) and "countByMode" in data, "S5 konuşma modeli (FR-AGT-003)")
    chk("hasPendingChanges" in data and "latestVersionNo" in data and "activeVersionNo" in data and "pending" in a03.get("flag", {}), "S5 sürüm/yayın + yayınlanmamış değişiklik (FR-AGT-004/006)")
    chk("unboundProduction" in data and "boundNumbers" in data and "unbound" in a03.get("flag", {}), "S5 numara/kampanya bağlama (FR-AGT-007)")
    chk("variantAgents" in data and "variant" in a03.get("flag", {}), "S5 segment varyantları (FR-AGT-008)")
    chk("testBlocked" in data and set(["passed", "failed", "not_run"]).issubset(a03.get("test", {}).keys()), "S5 otomatik test kapısı (FR-AGT-010)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a03.{rk}"
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
        vt = resolve(tr, f"screen.a03.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("countByLifecycle", "countByMode", "agentsInLifecycle", "productionAgents", "inDevelopmentAgents",
               "hasPendingChanges", "pendingChangesAgents", "testBlocked", "testBlockedAgents", "unboundProduction",
               "unboundProductionAgents", "missingActiveVersion", "missingActiveVersionAgents", "variantAgents",
               "distinctLanguages", "attentionAgents", "openAttentionCount", "lifecycleTone", "modeTone",
               "testTone", "pendingTone", "variantTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("LIFECYCLE_ORDER" in data and "IN_DEVELOPMENT" in data, "S7 LIFECYCLE_ORDER + IN_DEVELOPMENT sabitleri tanımlı")
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

def _agent(aref, lifecycle="production", mode="single_prompt", langs=None, active=1, latest=1,
           bound_n=1, bound_c=0, test="passed", variant=False):
    return {"id": aref, "agentRef": aref, "name": "Agent", "purpose": "p", "lifecycle": lifecycle,
            "mode": mode, "languages": langs if langs is not None else ["tr"], "orgUnit": "U",
            "activeVersionNo": active, "latestVersionNo": latest, "publishedAt": None, "updatedAt": "t0",
            "boundNumbers": bound_n, "boundCampaigns": bound_c, "testStatus": test,
            "isVariant": variant, "baseAgentRef": None}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    agents = [
        _agent("A1", lifecycle="production", mode="node_flow", langs=["tr", "en"], active=5, latest=6, bound_n=2, bound_c=0, test="passed"),
        _agent("A2", lifecycle="production", mode="single_prompt", langs=["tr"], active=3, latest=3, bound_n=1, bound_c=0, test="failed"),
        _agent("A3", lifecycle="production", mode="node_flow", langs=["tr", "en"], active=None, latest=2, bound_n=1, bound_c=0, test="passed"),
        _agent("A4", lifecycle="production", mode="single_prompt", langs=["tr"], active=2, latest=2, bound_n=0, bound_c=0, test="passed"),
        _agent("A5", lifecycle="staging", mode="node_flow", langs=["tr", "en"], active=1, latest=3, bound_n=0, bound_c=0, test="passed", variant=True),
        _agent("A6", lifecycle="draft", mode="single_prompt", langs=["en"], active=None, latest=1, bound_n=0, bound_c=0, test="not_run"),
    ]
    view = {"agents": agents}

    chk(count_by_lifecycle(agents) == {"production": 4, "staging": 1, "draft": 1}, "countByLifecycle")
    chk(count_by_mode(agents) == {"node_flow": 3, "single_prompt": 3}, "countByMode")
    chk([a["agentRef"] for a in production_agents(agents)] == ["A1", "A2", "A3", "A4"], "productionAgents")
    chk([a["agentRef"] for a in in_development_agents(agents)] == ["A5", "A6"], "inDevelopmentAgents")
    chk([a["agentRef"] for a in pending_changes_agents(agents)] == ["A1", "A3", "A5", "A6"], "pendingChangesAgents (latest>active)")
    chk([a["agentRef"] for a in test_blocked_agents(agents)] == ["A2"], "testBlockedAgents=[A2] (FR-AGT-010)")
    chk([a["agentRef"] for a in unbound_production_agents(agents)] == ["A4"], "unboundProductionAgents=[A4] (FR-AGT-007)")
    chk([a["agentRef"] for a in missing_active_version_agents(agents)] == ["A3"], "missingActiveVersionAgents=[A3] (FR-AGT-006)")
    chk([a["agentRef"] for a in variant_agents(agents)] == ["A5"], "variantAgents=[A5] (FR-AGT-008)")
    chk(distinct_languages(agents) == ["en", "tr"], "distinctLanguages=[en,tr]")
    chk([a["agentRef"] for a in attention_agents(agents)] == ["A2", "A3", "A4"], "attentionAgents=[A2,A3,A4]")
    chk(open_attention_count(view) == 3, "openAttentionCount=3")
    # tone eşlemeleri
    chk(lifecycle_tone("production") == "success" and lifecycle_tone("staging") == "warning" and lifecycle_tone("draft") == "neutral" and lifecycle_tone("test") == "info", "lifecycleTone")
    chk(mode_tone("node_flow") == "info" and mode_tone("single_prompt") == "neutral", "modeTone")
    chk(test_tone("passed") == "success" and test_tone("failed") == "danger" and test_tone("not_run") == "warning", "testTone")
    chk(pending_tone(True) == "warning" and pending_tone(False) == "neutral", "pendingTone")
    chk(variant_tone(True) == "info" and variant_tone(False) == "neutral", "variantTone")
    # hasPendingChanges sınır: active null → 0
    chk(has_pending_changes(_agent("X", active=None, latest=1)) is True, "hasPendingChanges active=null,latest=1 → True")
    chk(has_pending_changes(_agent("X", active=4, latest=4)) is False, "hasPendingChanges active==latest → False")
    # assertNoPii — konfigürasyon META İZİNLİ, ham içerik + sır YASAK
    chk(assert_no_pii({"a": _agent("A1")}) is None, "assertNoPii konfigürasyon META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"phoneNumber": "1"}}) == "$.x.phoneNumber", "assertNoPii ham numara yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii tool sırrı yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"webhookSecret": "k"}}) == "$.x.webhookSecret", "assertNoPii webhook sırrı yakalar")

    # samples doğrulaması
    for name in ("agents-clean.json", "agents-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        ag = snp["agents"]
        v = {"agents": ag}
        chk(len(ag) == exp.get("total"), f"{name} total={exp.get('total')}")
        chk(len(production_agents(ag)) == exp.get("production"), f"{name} production={exp.get('production')}")
        chk(len(in_development_agents(ag)) == exp.get("development"), f"{name} development={exp.get('development')}")
        chk(len(pending_changes_agents(ag)) == exp.get("pending"), f"{name} pending={exp.get('pending')}")
        chk(len(test_blocked_agents(ag)) == exp.get("test_blocked"), f"{name} test_blocked={exp.get('test_blocked')}")
        chk(len(unbound_production_agents(ag)) == exp.get("unbound"), f"{name} unbound={exp.get('unbound')}")
        chk(len(missing_active_version_agents(ag)) == exp.get("missing_version"), f"{name} missing_version={exp.get('missing_version')}")
        chk(len(variant_agents(ag)) == exp.get("variants"), f"{name} variants={exp.get('variants')}")
        chk(open_attention_count(v) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
        chk(distinct_languages(ag) == exp.get("distinct_languages"), f"{name} distinct_languages={exp.get('distinct_languages')}")
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

    clean = [
        _agent("C1", lifecycle="production", mode="node_flow", langs=["tr", "en"], active=4, latest=4, bound_n=2, bound_c=0, test="passed"),
        _agent("C2", lifecycle="production", mode="single_prompt", langs=["tr"], active=7, latest=7, bound_n=1, bound_c=3, test="passed"),
    ]
    clean_view = {"agents": clean}
    # pozitif (sağlıklı → boş/sıfır)
    expect(test_blocked_agents(clean) == [], "pos test bloklu yok")
    expect(unbound_production_agents(clean) == [], "pos bağlantısız production yok")
    expect(missing_active_version_agents(clean) == [], "pos aktif sürümsüz production yok")
    expect(pending_changes_agents(clean) == [], "pos yayınlanmamış değişiklik yok")
    expect(attention_agents(clean) == [], "pos dikkat gerektiren yok")
    expect(open_attention_count(clean_view) == 0, "pos openAttentionCount=0")
    expect(len(production_agents(clean)) == 2, "pos production=2")
    expect(distinct_languages(clean) == ["en", "tr"], "pos distinctLanguages=[en,tr]")

    # negatif (sorunlu → beklendiği gibi yakalanır)
    bad = [
        _agent("B1", lifecycle="production", mode="single_prompt", active=3, latest=3, bound_n=1, test="failed"),       # test bloklu
        _agent("B2", lifecycle="production", mode="node_flow", active=None, latest=2, bound_n=1, test="passed"),         # aktif sürümsüz
        _agent("B3", lifecycle="production", mode="single_prompt", active=2, latest=2, bound_n=0, bound_c=0, test="passed"),  # bağlantısız
        _agent("B4", lifecycle="staging", mode="node_flow", active=1, latest=3, bound_n=0, test="not_run", variant=True),    # staging+test not_run → bloklu
    ]
    bad_view = {"agents": bad}
    expect([a["agentRef"] for a in test_blocked_agents(bad)] == ["B1", "B4"], "neg test bloklu (B1,B4)")
    expect([a["agentRef"] for a in missing_active_version_agents(bad)] == ["B2"], "neg aktif sürümsüz (B2)")
    expect([a["agentRef"] for a in unbound_production_agents(bad)] == ["B3"], "neg bağlantısız production (B3)")
    expect([a["agentRef"] for a in variant_agents(bad)] == ["B4"], "neg varyant (B4)")
    # attention = B1 ∪ B2 ∪ B3 ∪ B4 (B4 staging test bloklu) = 4 ayrık
    expect([a["agentRef"] for a in attention_agents(bad)] == ["B1", "B2", "B3", "B4"], "neg dikkat gerektiren (B1,B2,B3,B4)")
    expect(open_attention_count(bad_view) == 4, "neg openAttentionCount=4")
    # staging test_blocked ama unbound DEĞİL (yalnız production unbound sayılır)
    expect(unbound_production(bad[3]) is False, "neg staging unbound sayılmaz (yalnız production)")
    # draft/test test kapısına takılmaz (yalnız staging/production)
    expect(test_blocked(_agent("D", lifecycle="draft", test="not_run")) is False, "neg draft test kapısına takılmaz")
    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"privateKey": "x"}]}) is not None, "neg privateKey yakalanır")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")
    # tone sınır
    expect(test_tone("failed") == "danger", "neg test failed → danger")
    expect(lifecycle_tone("staging") == "warning", "neg staging → warning")
    # placeholder ayrıştırma
    expect(placeholders("Tek prompt: {single} · Akış: {flow}") == {"single", "flow"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 70, "spec ≥70 referans anahtar")
    expect(spec["lifecycle_states"] == LIFECYCLE_ORDER, "spec lifecycle_states = LIFECYCLE_ORDER")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "AgentListView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "agents": [{"id": "str (agent kayıt REFERANSI)", "agentRef": "str (gösterim referansı)",
                        "name": "str (tenant config — FR-AGT-002; PII değil)", "purpose": "str (tenant config)",
                        "lifecycle": "draft|test|staging|production|archived (FR-AGT-005)",
                        "mode": "single_prompt|node_flow (FR-AGT-003)", "languages": "str[] (FR-AGT-002)",
                        "orgUnit": "str|null (departman/marka scope)",
                        "activeVersionNo": "int|null (yayınlı sürüm — FR-AGT-006)", "latestVersionNo": "int (en son — FR-AGT-004)",
                        "publishedAt": "ISO-8601|null", "updatedAt": "ISO-8601",
                        "boundNumbers": "int (FR-AGT-007)", "boundCampaigns": "int (FR-AGT-007)",
                        "testStatus": "passed|failed|not_run (FR-AGT-010)",
                        "isVariant": "bool (FR-AGT-008)", "baseAgentRef": "str|null"}]
        },
        "lifecycle_states": LIFECYCLE_ORDER,
        "hijyen": "A-03 yalnız KONFİGÜRASYON META gösterir (agent ad/amaç/durum/sürüm — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR/müşteri) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential (apiKey/webhookSecret/token/...) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Prompt gövdesi/tool sırrı derin aksiyon → A-06/A-09 (görsel kapı). KONFİGÜRASYON ekranı — gerçek zamanlı DEĞİL (FR-ANA-012 dışı)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a03_agents_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
