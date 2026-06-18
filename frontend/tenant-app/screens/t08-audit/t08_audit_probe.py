#!/usr/bin/env python3
# WBS 13.3.8 — T-08 "Audit Log (tenant)" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (chainBreaks/breakGlassEntries/dataAccessEntries/platformEntries/
#               platformWithoutBreakGlass/failedEntries/deniedEntries/categoryCounts/wormDisabled/
#               externalSealDisabled/retentionUnset/applyFilter/openWarningCount/tone'lar/assertNoPii) +
#               samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/audit.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t08-audit-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "audit", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "audit.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "customer", "cdr",
                      "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/audit.ts ile birebir) ──────────────────────

def chain_breaks(entries):
    out = []
    for i in range(1, len(entries)):
        if entries[i]["prevHash"] != entries[i - 1]["rowHash"]:
            out.append(entries[i]["id"])
    return out


def chain_intact(entries):
    return len(chain_breaks(entries)) == 0


def break_glass_entries(entries):
    return [e for e in entries if e["breakGlass"]]


def data_access_entries(entries):
    return [e for e in entries if e["category"] == "data_access"]


def platform_entries(entries):
    return [e for e in entries if e["actorRealm"] == "platform"]


def platform_without_break_glass(entries):
    return [e["id"] for e in entries if e["actorRealm"] == "platform" and not e["breakGlass"]]


def failed_entries(entries):
    return [e for e in entries if e["outcome"] != "success"]


def denied_entries(entries):
    return [e for e in entries if e["outcome"] == "denied"]


def category_counts(entries):
    out = {}
    for e in entries:
        out[e["category"]] = out.get(e["category"], 0) + 1
    return out


def outcome_counts(entries):
    out = {}
    for e in entries:
        out[e["outcome"]] = out.get(e["outcome"], 0) + 1
    return out


def worm_disabled(r):
    return not r["wormEnabled"]


def external_seal_disabled(r):
    return not r["externalSeal"]


def retention_unset(r):
    return r["retentionDays"] <= 0


def apply_filter(entries, f):
    out = []
    for e in entries:
        if f.get("realm") and e["actorRealm"] != f["realm"]:
            continue
        if f.get("category") and e["category"] != f["category"]:
            continue
        if f.get("outcome") and e["outcome"] != f["outcome"]:
            continue
        if f.get("breakGlassOnly") and not e["breakGlass"]:
            continue
        if f.get("actorContains") and f["actorContains"].lower() not in e["actorRef"].lower():
            continue
        if f.get("actionContains") and f["actionContains"].lower() not in e["action"].lower():
            continue
        out.append(e)
    return out


def open_warning_count(snap):
    return (len(chain_breaks(snap["entries"]))
            + len(platform_without_break_glass(snap["entries"]))
            + (1 if worm_disabled(snap["retention"]) else 0)
            + len(denied_entries(snap["entries"]))
            + (1 if retention_unset(snap["retention"]) else 0)
            + (1 if external_seal_disabled(snap["retention"]) else 0))


def outcome_tone(o):
    return {"success": "success", "failure": "danger", "denied": "warning"}[o]


def realm_tone(r):
    return {"tenant": "neutral", "platform": "warning", "system": "info"}[r]


def category_tone(c):
    return {"iam": "neutral", "config": "neutral", "data_access": "info", "compliance": "info",
            "security": "info", "break_glass": "warning", "billing": "neutral"}[c]


def break_glass_tone(b):
    return "warning" if b else "neutral"


def chain_tone(broken):
    return "danger" if broken else "success"


def worm_tone(enabled):
    return "success" if enabled else "danger"


def seal_tone(enabled):
    return "success" if enabled else "warning"


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
    """audit.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.3.8", "S0 spec.wbs=13.3.8")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/audit/page.tsx mevcut")
    chk('data-screen="T-08"' in page, 'S1 data-screen="T-08" işaretli')
    chk("İskelet ekran — T-08" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/audit" in page, "S2 veri seam (lib/tenant/audit) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t08.*); hardcoded TR/EN cümle yok
    chk("screen.t08." in page, "S3 screen.t08.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/audit.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getAudit assertNoPii çağırır")
    chk("cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 çağrı-bazlı CDR yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.3 içerik öğeleri + FR-IAM-006/FR-REC-009/FR-IAM-009/ADR-016 karşılanır
    t08 = tr.get("screen", {}).get("t08", {})
    sec = t08.get("section", {})
    for s in ("summary", "integrity", "categories", "breakglass", "entries"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.3 içerik öğesi)")
    chk(set(["iam", "config", "data_access", "compliance", "security", "break_glass", "billing"]).issubset(t08.get("category", {}).keys()), "S5 audit kategorileri (kullanıcı/sistem değişiklik+erişim)")
    chk(set(["tenant", "platform", "system"]).issubset(t08.get("realm", {}).keys()), "S5 aktör realm (platform=L0 break-glass)")
    chk(set(["success", "failure", "denied"]).issubset(t08.get("outcome", {}).keys()), "S5 işlem sonucu (success/failure/denied)")
    chk("worm" in t08.get("field", {}) and "wormDisabled" in data, "S5 WORM/değiştirilemez audit (FR-IAM-006)")
    chk("data_access" in t08.get("category", {}) and "dataAccessEntries" in data, "S5 veri erişim audit (FR-REC-009)")
    chk("break_glass" in t08.get("category", {}) and "breakGlassEntries" in data, "S5 break-glass erişimi (FR-IAM-009)")
    chk(("chain" in t08.get("field", {})) and "chainBreaks" in data and "external_seal" in t08.get("field", {}), "S5 hash zinciri + dış mühürleme (ADR-016)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t08.{rk}"
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
        vt = resolve(tr, f"screen.t08.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("chainBreaks", "chainIntact", "breakGlassEntries", "dataAccessEntries", "platformEntries",
               "platformWithoutBreakGlass", "failedEntries", "deniedEntries", "categoryCounts", "outcomeCounts",
               "wormDisabled", "externalSealDisabled", "retentionUnset", "applyFilter", "openWarningCount",
               "outcomeTone", "realmTone", "categoryTone", "breakGlassTone", "chainTone", "wormTone", "sealTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "datadog.com", "secret=", "splunk", "sumologic", "twilio.com"]
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

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    # sağlam zincir: prevHash[i] == rowHash[i-1]
    entries = [
        {"id": "E1", "occurredAt": "t1", "actorRealm": "tenant", "actorRef": "a@x", "action": "user:create", "resourceType": "user", "resourceRef": "U1", "category": "iam", "outcome": "success", "breakGlass": False, "breakGlassId": None, "prevHash": "00", "rowHash": "h1"},
        {"id": "E2", "occurredAt": "t2", "actorRealm": "tenant", "actorRef": "b@x", "action": "agent:publish", "resourceType": "agent", "resourceRef": "A1", "category": "config", "outcome": "denied", "breakGlass": False, "breakGlassId": None, "prevHash": "h1", "rowHash": "h2"},
        {"id": "E3", "occurredAt": "t3", "actorRealm": "platform", "actorRef": "sre@p", "action": "transcript:read", "resourceType": "recording", "resourceRef": "R1", "category": "break_glass", "outcome": "success", "breakGlass": True, "breakGlassId": "BG1", "prevHash": "h2", "rowHash": "h3"},
        {"id": "E4", "occurredAt": "t4", "actorRealm": "tenant", "actorRef": "c@x", "action": "recording:read", "resourceType": "recording", "resourceRef": "R2", "category": "data_access", "outcome": "success", "breakGlass": False, "breakGlassId": None, "prevHash": "h3", "rowHash": "h4"},
    ]
    retention = {"retentionDays": 2555, "wormEnabled": True, "externalSeal": True, "lastSealedAt": "t0"}

    chk(chain_breaks(entries) == [], "chainBreaks=[] (sağlam zincir)")
    chk(chain_intact(entries) is True, "chainIntact=True")
    # zincir kır: E3.prevHash bozulsun
    broken = [dict(e) for e in entries]
    broken[2] = dict(broken[2]); broken[2]["prevHash"] = "XX"
    chk(chain_breaks(broken) == ["E3"], "chainBreaks=[E3] (kopuk)")
    chk(chain_intact(broken) is False, "chainIntact=False (kopuk)")
    chk([e["id"] for e in break_glass_entries(entries)] == ["E3"], "breakGlassEntries=[E3]")
    chk([e["id"] for e in data_access_entries(entries)] == ["E4"], "dataAccessEntries=[E4]")
    chk([e["id"] for e in platform_entries(entries)] == ["E3"], "platformEntries=[E3]")
    chk(platform_without_break_glass(entries) == [], "platformWithoutBreakGlass=[] (E3 break-glass'lı)")
    # platform erişimi break-glass'sız => ihlal
    leak = [dict(e) for e in entries]
    leak[2] = dict(leak[2]); leak[2]["breakGlass"] = False
    chk(platform_without_break_glass(leak) == ["E3"], "platformWithoutBreakGlass=[E3] (ihlal)")
    chk([e["id"] for e in failed_entries(entries)] == ["E2"], "failedEntries=[E2]")
    chk([e["id"] for e in denied_entries(entries)] == ["E2"], "deniedEntries=[E2]")
    chk(category_counts(entries) == {"iam": 1, "config": 1, "break_glass": 1, "data_access": 1}, "categoryCounts")
    chk(outcome_counts(entries) == {"success": 3, "denied": 1}, "outcomeCounts")
    chk(worm_disabled(retention) is False and worm_disabled({"wormEnabled": False, "externalSeal": True, "retentionDays": 1}) is True, "wormDisabled")
    chk(external_seal_disabled(retention) is False and external_seal_disabled({"externalSeal": False, "wormEnabled": True, "retentionDays": 1}) is True, "externalSealDisabled")
    chk(retention_unset(retention) is False and retention_unset({"retentionDays": 0, "wormEnabled": True, "externalSeal": True}) is True, "retentionUnset")
    # applyFilter
    chk([e["id"] for e in apply_filter(entries, {"realm": "platform"})] == ["E3"], "applyFilter realm=platform")
    chk([e["id"] for e in apply_filter(entries, {"category": "data_access"})] == ["E4"], "applyFilter category")
    chk([e["id"] for e in apply_filter(entries, {"outcome": "denied"})] == ["E2"], "applyFilter outcome=denied")
    chk([e["id"] for e in apply_filter(entries, {"breakGlassOnly": True})] == ["E3"], "applyFilter breakGlassOnly")
    chk([e["id"] for e in apply_filter(entries, {"actorContains": "A@X"})] == ["E1"], "applyFilter actorContains (case-insensitive)")
    chk([e["id"] for e in apply_filter(entries, {"actionContains": "read"})] == ["E3", "E4"], "applyFilter actionContains")
    chk(len(apply_filter(entries, {})) == 4, "applyFilter boş=tümü")
    # openWarningCount: denied(E2)=1 + (worm ok) + (seal ok) + (retention ok) + (no chain break) + (no platform leak) = 1
    snap = {"entries": entries, "retention": retention}
    chk(open_warning_count(snap) == 1, "openWarningCount=1 (1 denied)")
    # tone eşlemeleri
    chk(outcome_tone("success") == "success" and outcome_tone("failure") == "danger" and outcome_tone("denied") == "warning", "outcomeTone")
    chk(realm_tone("platform") == "warning" and realm_tone("tenant") == "neutral" and realm_tone("system") == "info", "realmTone")
    chk(category_tone("break_glass") == "warning" and category_tone("data_access") == "info" and category_tone("iam") == "neutral", "categoryTone")
    chk(break_glass_tone(True) == "warning" and break_glass_tone(False) == "neutral", "breakGlassTone")
    chk(chain_tone(True) == "danger" and chain_tone(False) == "success", "chainTone")
    chk(worm_tone(True) == "success" and worm_tone(False) == "danger", "wormTone")
    chk(seal_tone(True) == "success" and seal_tone(False) == "warning", "sealTone")
    # assertNoPii — audit META İZİNLİ (actorRef/action/resourceRef), ham içerik + sır YASAK
    chk(assert_no_pii({"e": {"actorRef": "a@x", "action": "transcript:read", "resourceRef": "R1", "rowHash": "h"}}) is None, "assertNoPii audit META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"recording": "u"}}) == "$.x.recording", "assertNoPii ham recording yakalar")
    chk(assert_no_pii({"x": {"customer": {"msisdn": "1"}}}) == "$.x.customer", "assertNoPii müşteri PII yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii sır yakalar (NFR 10.6)")

    # samples doğrulaması
    for name in ("audit-clean.json", "audit-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(chain_breaks(snap["entries"]) == exp.get("chain_breaks"), f"{name} chain_breaks={exp.get('chain_breaks')}")
        chk(platform_without_break_glass(snap["entries"]) == exp.get("platform_no_bg"), f"{name} platform_no_bg={exp.get('platform_no_bg')}")
        chk(len(break_glass_entries(snap["entries"])) == exp.get("breakglass_count"), f"{name} breakglass_count={exp.get('breakglass_count')}")
        chk(len(data_access_entries(snap["entries"])) == exp.get("data_access_count"), f"{name} data_access_count={exp.get('data_access_count')}")
        chk(len(denied_entries(snap["entries"])) == exp.get("denied_count"), f"{name} denied_count={exp.get('denied_count')}")
        chk(worm_disabled(snap["retention"]) == exp.get("worm_disabled"), f"{name} worm_disabled={exp.get('worm_disabled')}")
        chk(open_warning_count(snap) == exp.get("open_warnings"), f"{name} open_warnings={exp.get('open_warnings')}")
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

    clean = [
        {"id": "E1", "actorRealm": "tenant", "actorRef": "a@x", "action": "user:create", "category": "iam", "outcome": "success", "breakGlass": False, "breakGlassId": None, "prevHash": "00", "rowHash": "h1"},
        {"id": "E2", "actorRealm": "tenant", "actorRef": "b@x", "action": "agent:publish", "category": "config", "outcome": "success", "breakGlass": False, "breakGlassId": None, "prevHash": "h1", "rowHash": "h2"},
    ]
    clean_ret = {"retentionDays": 365, "wormEnabled": True, "externalSeal": True, "lastSealedAt": "t0"}
    clean_snap = {"entries": clean, "retention": clean_ret}
    # pozitif (temiz → boş)
    expect(chain_breaks(clean) == [], "pos zincir sağlam")
    expect(chain_intact(clean) is True, "pos chainIntact")
    expect(platform_without_break_glass(clean) == [], "pos platform sızıntısı yok")
    expect(denied_entries(clean) == [], "pos reddedilen yok")
    expect(worm_disabled(clean_ret) is False, "pos WORM açık")
    expect(external_seal_disabled(clean_ret) is False, "pos mühürleme açık")
    expect(retention_unset(clean_ret) is False, "pos saklama tanımlı")
    expect(open_warning_count(clean_snap) == 0, "pos openWarningCount=0")
    # negatif (degrade beklendiği gibi yakalanır)
    bad = [
        {"id": "E1", "actorRealm": "tenant", "actorRef": "a@x", "action": "user:create", "category": "iam", "outcome": "denied", "breakGlass": False, "breakGlassId": None, "prevHash": "00", "rowHash": "h1"},
        {"id": "E2", "actorRealm": "platform", "actorRef": "sre@p", "action": "transcript:read", "category": "data_access", "outcome": "success", "breakGlass": False, "breakGlassId": None, "prevHash": "XX", "rowHash": "h2"},
    ]
    bad_ret = {"retentionDays": 0, "wormEnabled": False, "externalSeal": False, "lastSealedAt": "t0"}
    bad_snap = {"entries": bad, "retention": bad_ret}
    expect(chain_breaks(bad) == ["E2"], "neg zincir kopuk (E2)")
    expect(platform_without_break_glass(bad) == ["E2"], "neg platform break-glass'sız (E2)")
    expect(len(denied_entries(bad)) == 1, "neg reddedilen=1")
    expect(worm_disabled(bad_ret) is True, "neg WORM kapalı")
    expect(external_seal_disabled(bad_ret) is True, "neg mühürleme kapalı")
    expect(retention_unset(bad_ret) is True, "neg saklama tanımsız")
    # openWarningCount: chain_break(1) + platform_leak(1) + worm(1) + denied(1) + retention(1) + seal(1) = 6
    expect(open_warning_count(bad_snap) == 6, "neg openWarningCount toplamı=6")
    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"privateKey": "x"}]}) is not None, "neg privateKey yakalanır")
    # tone sınır
    expect(realm_tone("platform") == "warning", "neg platform realm → warning")
    expect(worm_tone(False) == "danger", "neg WORM kapalı → danger")
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
        "AuditSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "windowLabel": "str (görünüm zaman penceresi)",
            "totalCount": "int (pencere toplam kayıt — topluluk)",
            "entries": [{"id": "str", "occurredAt": "ISO-8601", "actorRealm": "tenant|platform|system",
                         "actorRef": "str (aktör tenant-içi kimliği — izinli)", "action": "str (permission-key biçimi)",
                         "resourceType": "str", "resourceRef": "str (UUID/handle REFERANSI — içerik DEĞİL)",
                         "category": "iam|config|data_access|compliance|security|break_glass|billing",
                         "outcome": "success|failure|denied", "breakGlass": "bool (FR-IAM-009)",
                         "breakGlassId": "str|null", "prevHash": "str (HEX öneki — zincir)", "rowHash": "str (HEX öneki)"}],
            "retention": {"retentionDays": "int (0=tanımsız)", "wormEnabled": "bool (FR-IAM-006; DB §6.5)",
                          "externalSeal": "bool (ADR-016)", "lastSealedAt": "ISO/etiket"}
        },
        "hijyen": "Audit yalnız META veridir (aktör/eylem/kaynak REFERANSI/zaman/bütünlük hash'i). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği/çağrı-bazlı CDR YOK (BRD §17.7 + §17.6 PII redaction); FORBIDDEN_SECRET_KEYS dışı sır/credential YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Bütünlük hash'leri yalnız HEX önekidir — sır değildir. Kayıtlar değiştirilemez/WORM (FR-IAM-006); panelde yazma/silme yok."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t08_audit_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
