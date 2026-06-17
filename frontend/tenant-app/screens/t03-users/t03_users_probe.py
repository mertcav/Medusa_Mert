#!/usr/bin/env python3
# WBS 13.3.3 — T-03 "Kullanıcı & Rol Yönetimi (RBAC/SSO/SCIM)" doğrulama probe'u (stdlib-only, credential-free,
# deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countUserStatus/countUserSource/usersForRole/scopedAssignmentCount/
#               usersMissingMfa/invalidRoleRefs/tone'lar/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/users.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
REPO = os.path.abspath(os.path.join(APP, "..", ".."))
SPEC_PATH = os.path.join(HERE, "t03-users-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(tenant-admin)", "admin", "users", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "users.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/users.ts ile birebir) ─────────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["token", "bearertoken", "secret", "clientsecret", "privatekey",
                         "certificate", "metadataxml"]


def count_user_status(users):
    out = {"active": 0, "invited": 0, "suspended": 0}
    for u in users:
        out[u["status"]] += 1
    return out


def count_user_source(users):
    out = {"local": 0, "sso": 0, "scim": 0}
    for u in users:
        out[u["source"]] += 1
    return out


def users_for_role(users, role_key):
    return sum(1 for u in users if role_key in u["roles"])


def scoped_assignment_count(users):
    return sum(1 for u in users if u["scope"] is not None and u["scope"].strip() != "")


def users_missing_mfa(users):
    return [u["id"] for u in users if u["status"] == "active" and not u["mfaEnabled"]]


def invalid_role_refs(users, roles):
    keys = {r["key"] for r in roles}
    return [u["id"] for u in users if any(rk not in keys for rk in u["roles"])]


def user_status_tone(s):
    return {"active": "success", "invited": "warning", "suspended": "danger"}[s]


def source_tone(s):
    return {"local": "neutral", "sso": "info", "scim": "info"}[s]


def conn_state_tone(s):
    return {"connected": "success", "disabled": "neutral", "error": "danger"}[s]


def role_tier_tone(t):
    return {"L1": "info", "L2": "neutral", "L1+L2": "info"}[t]


def mfa_tone(enabled):
    return "success" if enabled else "warning"


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA SSO/SCIM sırrı alan adı bulursa (path) döndürür; yoksa None."""
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
    chk(spec.get("wbs") == "13.3.3", "S0 spec.wbs=13.3.3")
    chk(os.path.isfile(PAGE_PATH), "S1 admin/users/page.tsx mevcut")
    chk('data-screen="T-03"' in page, 'S1 data-screen="T-03" işaretli')
    chk("İskelet ekran — T-03" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/users" in page, "S2 veri seam (lib/tenant/users) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.t03.*); hardcoded TR/EN cümle yok
    chk("screen.t03." in page, "S3 screen.t03.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + SSO/SCIM-sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/users.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getUserRoles assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.4 üç içerik öğesi (RBAC/SSO/SCIM) + immutable + scope karşılanır
    t03 = tr.get("screen", {}).get("t03", {})
    sec = t03.get("section", {})
    chk("users" in sec and "roles" in sec, "S5 RBAC → section.users + section.roles")
    chk("federation" in sec, "S5 SSO/SCIM → section.federation")
    chk("heading" in t03.get("sso", {}), "S5 SSO bölümü (FR-IAM-002)")
    chk("heading" in t03.get("scim", {}), "S5 SCIM bölümü (FR-IAM-007)")
    chk("role_immutable" in t03, "S5 immutable rol bundle etiketi (FR-IAM-011)")
    chk("scope_hint" in t03 and "scope" in t03.get("col", {}), "S5 scope filtresi (FR-IAM-011)")
    chk("immutable" in data and "scope" in data, "S5 veri katmanı immutable + scope alanları")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.t03.{rk}"
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
        vt = resolve(tr, f"screen.t03.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("countUserStatus", "countUserSource", "usersForRole", "scopedAssignmentCount",
               "usersMissingMfa", "invalidRoleRefs", "userStatusTone", "sourceTone",
               "connStateTone", "roleTierTone", "mfaTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok (somut IdP/SaaS markası + literal sır taraması)
    forbidden_vendors = ["openai", "twilio", "anthropic", "datadog.com", "api_key", "secret=",
                         "okta", "auth0", "azure ad", "onelogin", "ping identity"]
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
    """users.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── check ────────────────────────────────────────────────────────────────────────

def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    roles = [
        {"key": "tenant_owner", "tier": "L1+L2", "immutable": True},
        {"key": "tenant_admin", "tier": "L1", "immutable": True},
        {"key": "operations_manager", "tier": "L2", "immutable": True},
        {"key": "qa_analyst", "tier": "L2", "immutable": True},
    ]
    users = [
        {"id": "U1", "roles": ["tenant_owner"], "scope": None, "source": "local", "mfaEnabled": True, "status": "active"},
        {"id": "U2", "roles": ["tenant_admin"], "scope": None, "source": "sso", "mfaEnabled": True, "status": "active"},
        {"id": "U3", "roles": ["operations_manager"], "scope": "BR-A", "source": "scim", "mfaEnabled": False, "status": "active"},
        {"id": "U4", "roles": ["qa_analyst"], "scope": "DP-X", "source": "scim", "mfaEnabled": True, "status": "invited"},
        {"id": "U5", "roles": ["ghost_role"], "scope": None, "source": "local", "mfaEnabled": False, "status": "suspended"},  # geçersiz rol
    ]

    chk(count_user_status(users) == {"active": 3, "invited": 1, "suspended": 1}, "countUserStatus")
    chk(count_user_source(users) == {"local": 2, "sso": 1, "scim": 2}, "countUserSource")
    chk(users_for_role(users, "tenant_owner") == 1, "usersForRole tenant_owner=1")
    chk(users_for_role(users, "operations_manager") == 1, "usersForRole operations_manager=1")
    chk(scoped_assignment_count(users) == 2, "scopedAssignmentCount=2 (U3,U4)")
    chk(users_missing_mfa(users) == ["U3"], "usersMissingMfa=[U3] (yalnız aktif)")
    chk(invalid_role_refs(users, roles) == ["U5"], "invalidRoleRefs=[U5] (ghost_role)")
    # tone eşlemeleri
    chk(user_status_tone("active") == "success" and user_status_tone("invited") == "warning" and user_status_tone("suspended") == "danger", "userStatusTone")
    chk(source_tone("local") == "neutral" and source_tone("sso") == "info" and source_tone("scim") == "info", "sourceTone")
    chk(conn_state_tone("connected") == "success" and conn_state_tone("disabled") == "neutral" and conn_state_tone("error") == "danger", "connStateTone")
    chk(role_tier_tone("L1") == "info" and role_tier_tone("L2") == "neutral" and role_tier_tone("L1+L2") == "info", "roleTierTone")
    chk(mfa_tone(True) == "success" and mfa_tone(False) == "warning", "mfaTone")
    # assertNoPii — kimlik İZİNLİ, son-müşteri PII + SSO/SCIM sırrı YASAK
    chk(assert_no_pii({"users": [{"principal": "a@b.example", "displayName": "Ali"}]}) is None, "assertNoPii kimlik İZİNLİ")
    chk(assert_no_pii({"tenantName": "Acme", "idpLabel": "Dizin"}) is None, "assertNoPii tenant/idp adı İZİNLİ")
    chk(assert_no_pii({"call": {"transcript": "x"}}) == "$.call.transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"scim": {"token": "secret-xyz"}}) == "$.scim.token", "assertNoPii SCIM token yakalar (NFR 10.6)")
    chk(assert_no_pii({"sso": {"certificate": "MIIB"}}) == "$.sso.certificate", "assertNoPii SSO sertifikası yakalar")

    # samples doğrulaması
    for name in ("users-clean.json", "users-issues.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        cs = count_user_status(snap["users"])
        chk(cs["active"] == exp.get("active_users"), f"{name} active_users={exp.get('active_users')}")
        chk(scoped_assignment_count(snap["users"]) == exp.get("scoped"), f"{name} scoped={exp.get('scoped')}")
        chk(users_missing_mfa(snap["users"]) == exp.get("missing_mfa"), f"{name} missing_mfa={exp.get('missing_mfa')}")
        chk(invalid_role_refs(snap["users"], snap["roles"]) == exp.get("invalid_roles"), f"{name} invalid_roles={exp.get('invalid_roles')}")
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

    roles = [{"key": "tenant_owner", "tier": "L1+L2", "immutable": True}]
    users = [{"id": "A", "roles": ["tenant_owner"], "scope": None, "source": "local", "mfaEnabled": True, "status": "active"}]
    # pozitif
    expect(count_user_status(users) == {"active": 1, "invited": 0, "suspended": 0}, "pos countUserStatus")
    expect(count_user_source(users) == {"local": 1, "sso": 0, "scim": 0}, "pos countUserSource")
    expect(users_for_role(users, "tenant_owner") == 1, "pos usersForRole")
    expect(scoped_assignment_count(users) == 0, "pos scoped boş → 0")
    expect(users_missing_mfa(users) == [], "pos missing_mfa boş")
    expect(invalid_role_refs(users, roles) == [], "pos invalid boş")
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"msisdn": "x"}) is not None, "neg msisdn yakalanır")
    expect(assert_no_pii({"settings": [{"bearerToken": "x"}]}) is not None, "neg bearerToken yakalanır")
    expect(assert_no_pii({"clientSecret": "x"}) is not None, "neg clientSecret yakalanır")
    expect(users_missing_mfa([{"id": "Z", "status": "active", "mfaEnabled": False, "roles": [], "scope": None, "source": "local"}]) == ["Z"], "neg MFA-yok aktif yakalanır")
    expect(invalid_role_refs([{"id": "Z", "roles": ["nope"]}], roles) == ["Z"], "neg geçersiz rol yakalanır")
    expect(scoped_assignment_count([{"scope": "  "}]) == 0, "neg boşluk-scope kapsamsız sayılır")
    expect(user_status_tone("suspended") == "danger", "neg askıya alındı → danger")
    expect(source_tone("scim") == "info", "neg scim → info")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 60, "spec ≥60 referans anahtar")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "UserRoleSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "users": [{"id": "str", "principal": "str (oturum kimliği — tenant KENDİ yönetim kullanıcısı, izinli)",
                       "displayName": "str (izinli)", "roles": ["str (TenantRole.key)"],
                       "scope": "str|null (departman/marka/kampanya; null=tüm tenant)",
                       "source": "local|sso|scim", "mfaEnabled": "bool", "status": "active|invited|suspended"}],
            "roles": [{"key": "str (immutable bundle kimliği)", "tier": "L1|L2|L1+L2", "immutable": "bool"}],
            "sso": {"protocol": "saml|oidc|none", "state": "connected|disabled|error", "idpLabel": "str|null (izinli)",
                    "mfaEnforced": "bool", "jitProvisioning": "bool", "defaultRole": "str|null"},
            "scim": {"state": "connected|disabled|error", "tokenConfigured": "bool (token DEĞERİ asla burada değil)",
                     "lastSyncAt": "ISO-8601|null", "syncedUsers": "int", "groupMappings": "int"}
        },
        "hijyen": "FORBIDDEN_PII_KEYS dışı son-müşteri alanı yok (BRD §17.7); FORBIDDEN_SECRET_KEYS dışı SSO/SCIM sırrı yok (NFR 10.6); assertNoPii çalışma-anında doğrular. principal/displayName/idpLabel + tenant kimliği izinli."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: t03_users_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
