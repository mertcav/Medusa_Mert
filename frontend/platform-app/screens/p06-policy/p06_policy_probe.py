#!/usr/bin/env python3
# WBS 13.2.6 — P-06 "Global Politika & Guardrails" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (enforcementTone/guardrailTone/modelStatusTone/profileStatusTone/
#               countEnabledGuardrails/policyGaps/noTrainViolations/countByModelStatus/allowedModelCount/
#               activeProfileCount/coveredTenants/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/policy.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p06-policy-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "policy", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "policy.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/policy.ts ile birebir) ──────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "iban",
                      "pii", "email", "ssn"]

ENFORCEMENT_TONE = {"block": "success", "redact": "success", "flag": "warning", "off": "neutral"}
MODEL_STATUS_TONE = {"allowed": "success", "restricted": "warning", "blocked": "neutral"}
PROFILE_STATUS_TONE = {"active": "success", "draft": "neutral"}


def enforcement_tone(e):
    return ENFORCEMENT_TONE[e]


def guardrail_tone(g):
    if g["status"] == "disabled":
        return "danger" if g["mandatory"] else "neutral"
    return "success"


def model_status_tone(s):
    return MODEL_STATUS_TONE[s]


def profile_status_tone(s):
    return PROFILE_STATUS_TONE[s]


def count_enabled_guardrails(guardrails):
    return len([g for g in guardrails if g["status"] == "enabled"])


def mandatory_guardrail_count(guardrails):
    return len([g for g in guardrails if g["mandatory"]])


def policy_gaps(snap):
    return [g["id"] for g in snap["guardrails"] if g["mandatory"] and g["status"] == "disabled"]


def no_train_violations(snap):
    return [m["id"] for m in snap["models"] if m["status"] != "blocked" and not m["noTrainDefault"]]


def count_by_model_status(models):
    acc = {"allowed": 0, "restricted": 0, "blocked": 0}
    for m in models:
        acc[m["status"]] += 1
    return acc


def allowed_model_count(models):
    return len([m for m in models if m["status"] == "allowed"])


def active_profile_count(profiles):
    return len([p for p in profiles if p["status"] == "active"])


def covered_tenants(profiles):
    return sum(p["appliedTenants"] for p in profiles)


def assert_no_pii(node, path="$"):
    """Yasak iş-içeriği/son-müşteri PII alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_pii(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            if k.lower() in FORBIDDEN_PII_KEYS:
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
    """policy.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.6", "S0 spec.wbs=13.2.6")
    chk(os.path.isfile(PAGE_PATH), "S1 policy/page.tsx mevcut")
    chk('data-screen="P-06"' in page, 'S1 data-screen="P-06" işaretli')
    chk("İskelet ekran — P-06" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/policy" in page, "S2 veri seam (lib/platform/policy) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p06.*); hardcoded TR/EN cümle yok
    chk("screen.p06." in page, "S3 screen.p06.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/policy.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getPolicy assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")
    chk("appliedTenants" in data, "S4 appliedTenants (toplulaştırılmış tenant SAYISI) izinli alan mevcut")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (güvenlik politikaları + model allowlist + compliance profilleri)
    p06 = tr.get("screen", {}).get("p06", {})
    sec = p06.get("section", {})
    gc = p06.get("guardrail_category", {})
    chk("security" in sec and all(x in gc for x in ("input_guard", "output_guard", "system_prompt_lock", "pii_redaction", "anti_hallucination")), "S5 güvenlik politikaları → section.security + guardrail_category.* (FR-LLM-006/007/009, FR-REC-004, FR-KB-007)")
    chk("models" in sec and "model_status" in p06 and "model_category" in p06, "S5 model allowlist → section.models + model_status.* + model_category.* (FR-LLM-001/002)")
    chk("compliance" in sec and "profile_status" in p06 and "country" in p06, "S5 compliance profilleri → section.compliance + profile_status.* + country.* (BRD §14.4)")
    chk("policy_gap_alert" in p06 and "no_policy_gap" in p06, "S5 politika boşluğu uyarısı → policy_gap_alert")
    chk("no_train_alert" in p06 and "no_train_ok" in p06, "S5 no-train ihlali uyarısı → no_train_alert (FR-LLM-012)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p06.{rk}"
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
        vt = resolve(tr, f"screen.p06.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("enforcementTone", "guardrailTone", "modelStatusTone", "profileStatusTone",
               "countEnabledGuardrails", "mandatoryGuardrailCount", "policyGaps", "noTrainViolations",
               "countByModelStatus", "allowedModelCount", "activeProfileCount", "coveredTenants"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral (somut sağlayıcı/model markası yok) + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "deepgram", "elevenlabs", "cartesia",
                         "telnyx", "gpt-", "claude-", "gemini", "llama", "whisper", "api_key", "secret="]
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

    # enforcementTone
    chk(enforcement_tone("block") == "success", "enforcement block→success")
    chk(enforcement_tone("redact") == "success", "enforcement redact→success")
    chk(enforcement_tone("flag") == "warning", "enforcement flag→warning")
    chk(enforcement_tone("off") == "neutral", "enforcement off→neutral")
    # guardrailTone (mandatory + status)
    chk(guardrail_tone({"status": "enabled", "mandatory": True}) == "success", "guardrail enabled→success")
    chk(guardrail_tone({"status": "disabled", "mandatory": True}) == "danger", "guardrail zorunlu+kapalı→danger (policy gap)")
    chk(guardrail_tone({"status": "disabled", "mandatory": False}) == "neutral", "guardrail opsiyonel+kapalı→neutral")
    # modelStatusTone
    chk(model_status_tone("allowed") == "success", "model allowed→success")
    chk(model_status_tone("restricted") == "warning", "model restricted→warning")
    chk(model_status_tone("blocked") == "neutral", "model blocked→neutral")
    # profileStatusTone
    chk(profile_status_tone("active") == "success", "profile active→success")
    chk(profile_status_tone("draft") == "neutral", "profile draft→neutral")
    # assertNoPii
    chk(assert_no_pii({"models": [{"id": "llm-large-a", "noTrainDefault": True}]}) is None, "assertNoPii temiz snapshot OK")
    chk(assert_no_pii({"models": [{"transcript": "x"}]}) == "$.models[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"msisdn": "x"}) == "$.msisdn", "assertNoPii msisdn yakalar")

    # samples doğrulaması
    for name in ("policy-mixed.json", "policy-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(policy_gaps(snap) == exp["policy_gaps"], f"{name} policy_gaps={exp['policy_gaps']}")
        chk(no_train_violations(snap) == exp["no_train_violations"], f"{name} no_train_violations={exp['no_train_violations']}")
        chk(count_enabled_guardrails(snap["guardrails"]) == exp["enabled_guardrails"], f"{name} enabled_guardrails={exp['enabled_guardrails']}")
        chk(count_by_model_status(snap["models"]) == exp["count_by_model_status"], f"{name} count_by_model_status={exp['count_by_model_status']}")
        chk(allowed_model_count(snap["models"]) == exp["allowed_models"], f"{name} allowed_models={exp['allowed_models']}")
        chk(active_profile_count(snap["complianceProfiles"]) == exp["active_profiles"], f"{name} active_profiles={exp['active_profiles']}")
        chk(covered_tenants(snap["complianceProfiles"]) == exp["covered_tenants"], f"{name} covered_tenants={exp['covered_tenants']}")
        chk(assert_no_pii(snap) is None, f"{name} PII-free (ALTIN KURAL)")

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

    snap = {
        "guardrails": [
            {"id": "g-input", "category": "input_guard", "enforcement": "block", "status": "enabled", "mandatory": True},
            {"id": "g-output", "category": "output_guard", "enforcement": "block", "status": "disabled", "mandatory": True},
            {"id": "g-halluc", "category": "anti_hallucination", "enforcement": "flag", "status": "disabled", "mandatory": False},
        ],
        "models": [
            {"id": "llm-large-a", "status": "allowed", "noTrainDefault": True},
            {"id": "llm-large-b", "status": "restricted", "noTrainDefault": False},
            {"id": "llm-legacy-x", "status": "blocked", "noTrainDefault": False},
        ],
        "complianceProfiles": [
            {"id": "profile-tr", "status": "active", "appliedTenants": 6},
            {"id": "profile-me", "status": "draft", "appliedTenants": 0},
        ],
    }
    # pozitif — türetmeler
    expect(count_enabled_guardrails(snap["guardrails"]) == 1, "pos etkin guardrail=1")
    expect(mandatory_guardrail_count(snap["guardrails"]) == 2, "pos zorunlu guardrail=2")
    expect(policy_gaps(snap) == ["g-output"], "pos policy gap = g-output (zorunlu+kapalı)")
    expect(no_train_violations(snap) == ["llm-large-b"], "pos no-train ihlali = llm-large-b (blocked hariç)")
    expect(count_by_model_status(snap["models"]) == {"allowed": 1, "restricted": 1, "blocked": 1}, "pos model durum sayımı")
    expect(allowed_model_count(snap["models"]) == 1, "pos izinli model=1")
    expect(active_profile_count(snap["complianceProfiles"]) == 1, "pos aktif profil=1 (draft hariç)")
    expect(covered_tenants(snap["complianceProfiles"]) == 6, "pos kapsanan tenant=6")
    # negatif (degrade beklendiği gibi yakalanır)
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"callerid": "x"}) is not None, "neg callerid yakalanır")
    expect(guardrail_tone({"status": "disabled", "mandatory": True}) != guardrail_tone({"status": "disabled", "mandatory": False}), "neg zorunlu/opsiyonel kapalı farklı ton")
    expect("llm-legacy-x" not in no_train_violations(snap), "neg blocked model ihlal sayılmaz")
    # tam-sağlıklı snapshot → boşluk/ihlal yok
    healthy = {
        "guardrails": [{"id": "g1", "category": "input_guard", "enforcement": "block", "status": "enabled", "mandatory": True}],
        "models": [{"id": "m1", "status": "allowed", "noTrainDefault": True}],
        "complianceProfiles": [{"id": "p1", "status": "active", "appliedTenants": 3}],
    }
    expect(policy_gaps(healthy) == [], "pos sağlıklı → policy gap yok")
    expect(no_train_violations(healthy) == [], "pos sağlıklı → no-train ihlali yok")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{days} days") == {"days"}, "days placeholder parse")
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
        "PolicySnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "guardrails": [{
                "id": "str", "category": "input_guard|output_guard|system_prompt_lock|pii_redaction|anti_hallucination",
                "enforcement": "block|redact|flag|off", "status": "enabled|disabled",
                "mandatory": "bool (zorunlu — kapalıysa policy gap)", "mappedFr": "str (FR kodu — çeviri değil)"
            }],
            "models": [{
                "id": "str (vendor-NÖTR model kimliği)", "category": "stt|tts|llm", "tier": "small|large|na",
                "status": "allowed|restricted|blocked", "noTrainDefault": "bool (FR-LLM-012)",
                "versionPinned": "bool (FR-LLM-011)", "regions": "[uk|eu|na|me]"
            }],
            "complianceProfiles": [{
                "id": "str", "country": "tr|uk|eu|me (DPIA PROFILE-*)", "sector": "general|finance|health|public",
                "status": "active|draft", "residency": "tr|uk|eu|me", "retentionDays": "num",
                "requireTenantApproval": "bool (FR-IAM-010)", "overrideOnlyStricter": "bool (DPIA most-restrictive-wins)",
                "appliedTenants": "num (toplulaştırılmış SAYIM)"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. appliedTenants (sayım) izinli.",
        "guardrail_tone": {"disabled+mandatory": "danger", "disabled": "neutral", "enabled": "success"},
        "no_train_violation": "status != blocked && !noTrainDefault (FR-LLM-012)",
        "policy_gap": "mandatory && status == disabled"
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p06_policy_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
