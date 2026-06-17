#!/usr/bin/env python3
# WBS 13.2.8 — P-08 "Sürüm & Dağıtım (Release) Yönetimi" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (releaseStageTone/releaseHealthTone/rolloutStrategyTone/
#               flagStatusTone/deploymentOutcomeTone/deploymentTypeTone/countByStage/activeFlagCount/
#               failingReleases/canaryRisks/failedDeployments/rollbackEvents/flagConfigGaps/percentageRollouts/
#               assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/releases.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p08-releases-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "releases", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "releases.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/releases.ts ile birebir) ─────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "iban",
                      "pii", "email", "ssn"]

RELEASE_STAGE_TONE = {"draft": "neutral", "staging": "info", "canary": "warning",
                      "production": "success", "rolled_back": "neutral"}
RELEASE_HEALTH_TONE = {"healthy": "success", "degraded": "warning", "failing": "danger"}
ROLLOUT_STRATEGY_TONE = {"disabled": "neutral", "internal": "info", "percentage": "warning", "full": "success"}
FLAG_STATUS_TONE = {"active": "success", "inactive": "neutral", "archived": "neutral"}
DEPLOYMENT_OUTCOME_TONE = {"success": "success", "in_progress": "info", "failed": "danger"}
DEPLOYMENT_TYPE_TONE = {"promote": "info", "rollback": "warning", "flag_change": "neutral", "canary_pause": "warning"}


def release_stage_tone(s):
    return RELEASE_STAGE_TONE[s]


def release_health_tone(h):
    return RELEASE_HEALTH_TONE[h]


def rollout_strategy_tone(s):
    return ROLLOUT_STRATEGY_TONE[s]


def flag_status_tone(s):
    return FLAG_STATUS_TONE[s]


def deployment_outcome_tone(o):
    return DEPLOYMENT_OUTCOME_TONE[o]


def deployment_type_tone(t):
    return DEPLOYMENT_TYPE_TONE[t]


def count_by_stage(releases):
    acc = {"draft": 0, "staging": 0, "canary": 0, "production": 0, "rolled_back": 0}
    for r in releases:
        acc[r["stage"]] += 1
    return acc


def active_flag_count(flags):
    return len([f for f in flags if f["status"] == "active"])


def failing_releases(snap):
    return [r["id"] for r in snap["releases"]
            if r["stage"] in ("production", "canary") and r["health"] == "failing"]


def canary_risks(snap):
    return [r["id"] for r in snap["releases"]
            if r["stage"] == "canary" and r["health"] != "healthy"]


def failed_deployments(events):
    return [e["id"] for e in events if e["outcome"] == "failed"]


def rollback_events(events):
    return [e["id"] for e in events if e["type"] == "rollback"]


def flag_config_gaps(flags):
    return [f["id"] for f in flags
            if f["strategy"] == "percentage" and (f["rolloutPct"] <= 0 or f["rolloutPct"] >= 100)]


def percentage_rollouts(flags):
    return [f["id"] for f in flags if f["strategy"] == "percentage"]


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
    """releases.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.8", "S0 spec.wbs=13.2.8")
    chk(os.path.isfile(PAGE_PATH), "S1 releases/page.tsx mevcut")
    chk('data-screen="P-08"' in page, 'S1 data-screen="P-08" işaretli')
    chk("İskelet ekran — P-08" not in page and "İskelet" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/releases" in page, "S2 veri seam (lib/platform/releases) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p08.*); hardcoded TR/EN cümle yok
    chk("screen.p08." in page, "S3 screen.p08.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/releases.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getReleases assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")
    chk("enabledTenants" in data, "S4 enabledTenants (toplulaştırılmış SAYI — izinli) alanı mevcut")

    # S5 — BRD §17.3 içerik öğeleri karşılanır (versiyonlama + feature flag + kademeli yayma)
    p08 = tr.get("screen", {}).get("p08", {})
    sec = p08.get("section", {})
    chk("releases" in sec and "release_stage" in p08 and "release_health" in p08, "S5 versiyonlama → section.releases + release_stage.* + release_health.* (FR-AGT-005/006)")
    chk("flags" in sec and "flag_status" in p08 and "rollout_strategy" in p08, "S5 feature flag → section.flags + flag_status.* + rollout_strategy.*")
    chk("events" in sec and "deployment_type" in p08 and "deployment_outcome" in p08, "S5 kademeli yayma/dağıtım → section.events + deployment_type.* + deployment_outcome.*")
    chk("canary_alert" in p08 and "canary_ok" in p08, "S5 canary/kademeli yayma uyarısı → canary_alert (FR-AGT-005)")
    chk("health_alert" in p08 and "health_ok" in p08, "S5 dağıtım sağlık uyarısı → health_alert (FR-AGT-006)")
    chk("deploy_alert" in p08 and "flags_alert" in p08, "S5 başarısız dağıtım + flag yapılandırma uyarısı")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p08.{rk}"
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
        vt = resolve(tr, f"screen.p08.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("releaseStageTone", "releaseHealthTone", "rolloutStrategyTone", "flagStatusTone",
               "deploymentOutcomeTone", "deploymentTypeTone", "countByStage", "activeFlagCount",
               "failingReleases", "canaryRisks", "failedDeployments", "rollbackEvents",
               "flagConfigGaps", "percentageRollouts"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral (somut sağlayıcı/CI-CD markası yok) + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "deepgram", "elevenlabs", "cartesia",
                         "telnyx", "splunk", "datadog", "gpt-", "claude-", "gemini", "llama",
                         "whisper", "jenkins", "argocd", "spinnaker", "launchdarkly", "api_key", "secret="]
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

    # releaseStageTone
    chk(release_stage_tone("canary") == "warning", "release stage canary→warning")
    chk(release_stage_tone("production") == "success", "release stage production→success")
    chk(release_stage_tone("rolled_back") == "neutral", "release stage rolled_back→neutral")
    # releaseHealthTone
    chk(release_health_tone("healthy") == "success", "release health healthy→success")
    chk(release_health_tone("degraded") == "warning", "release health degraded→warning")
    chk(release_health_tone("failing") == "danger", "release health failing→danger")
    # rolloutStrategyTone
    chk(rollout_strategy_tone("percentage") == "warning", "rollout percentage→warning")
    chk(rollout_strategy_tone("full") == "success", "rollout full→success")
    chk(rollout_strategy_tone("disabled") == "neutral", "rollout disabled→neutral")
    # flagStatusTone
    chk(flag_status_tone("active") == "success", "flag active→success")
    chk(flag_status_tone("inactive") == "neutral", "flag inactive→neutral")
    # deploymentOutcomeTone
    chk(deployment_outcome_tone("success") == "success", "deploy outcome success→success")
    chk(deployment_outcome_tone("in_progress") == "info", "deploy outcome in_progress→info")
    chk(deployment_outcome_tone("failed") == "danger", "deploy outcome failed→danger")
    # deploymentTypeTone
    chk(deployment_type_tone("rollback") == "warning", "deploy type rollback→warning")
    chk(deployment_type_tone("promote") == "info", "deploy type promote→info")
    # assertNoPii
    chk(assert_no_pii({"flags": [{"enabledTenants": 12, "key": "x"}]}) is None, "assertNoPii temiz snapshot OK (enabledTenants izinli)")
    chk(assert_no_pii({"flags": [{"transcript": "x"}]}) == "$.flags[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"recording": "u"}) == "$.recording", "assertNoPii recording yakalar")

    # samples doğrulaması
    for name in ("releases-mixed.json", "releases-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(count_by_stage(snap["releases"]) == exp["count_by_stage"], f"{name} count_by_stage={exp['count_by_stage']}")
        chk(active_flag_count(snap["flags"]) == exp["active_flags"], f"{name} active_flags={exp['active_flags']}")
        chk(failing_releases(snap) == exp["failing_releases"], f"{name} failing_releases={exp['failing_releases']}")
        chk(canary_risks(snap) == exp["canary_risks"], f"{name} canary_risks={exp['canary_risks']}")
        chk(failed_deployments(snap["events"]) == exp["failed_deployments"], f"{name} failed_deployments={exp['failed_deployments']}")
        chk(rollback_events(snap["events"]) == exp["rollback_events"], f"{name} rollback_events={exp['rollback_events']}")
        chk(flag_config_gaps(snap["flags"]) == exp["flag_config_gaps"], f"{name} flag_config_gaps={exp['flag_config_gaps']}")
        chk(percentage_rollouts(snap["flags"]) == exp["percentage_rollouts"], f"{name} percentage_rollouts={exp['percentage_rollouts']}")
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
        "releases": [
            {"id": "r-1", "stage": "production", "health": "healthy"},
            {"id": "r-2", "stage": "canary", "health": "degraded"},   # canary riski
            {"id": "r-3", "stage": "production", "health": "failing"},  # başarısız (production)
            {"id": "r-4", "stage": "canary", "health": "failing"},      # canary riski + başarısız (her iki lens)
            {"id": "r-5", "stage": "staging", "health": "healthy"},
            {"id": "r-6", "stage": "draft", "health": "healthy"},
            {"id": "r-7", "stage": "rolled_back", "health": "healthy"},
        ],
        "flags": [
            {"id": "f-1", "status": "active", "strategy": "percentage", "rolloutPct": 25},
            {"id": "f-2", "status": "active", "strategy": "full", "rolloutPct": 100},
            {"id": "f-3", "status": "active", "strategy": "percentage", "rolloutPct": 0},     # yapılandırma boşluğu
            {"id": "f-4", "status": "active", "strategy": "percentage", "rolloutPct": 100},   # yapılandırma boşluğu
            {"id": "f-5", "status": "inactive", "strategy": "disabled", "rolloutPct": 0},
        ],
        "events": [
            {"id": "e-1", "type": "promote", "outcome": "success"},
            {"id": "e-2", "type": "rollback", "outcome": "success"},
            {"id": "e-3", "type": "promote", "outcome": "failed"},     # başarısız dağıtım
            {"id": "e-4", "type": "canary_pause", "outcome": "in_progress"},
        ],
    }
    # pozitif — türetmeler
    expect(count_by_stage(snap["releases"]) == {"draft": 1, "staging": 1, "canary": 2, "production": 2, "rolled_back": 1}, "pos aşama sayımı")
    expect(active_flag_count(snap["flags"]) == 4, "pos aktif flag=4")
    expect(failing_releases(snap) == ["r-3", "r-4"], "pos başarısız sürüm = r-3,r-4 (prod+canary failing)")
    expect(canary_risks(snap) == ["r-2", "r-4"], "pos canary riski = r-2,r-4 (canary non-healthy)")
    expect(failed_deployments(snap["events"]) == ["e-3"], "pos başarısız dağıtım = e-3")
    expect(rollback_events(snap["events"]) == ["e-2"], "pos rollback olayı = e-2")
    expect(flag_config_gaps(snap["flags"]) == ["f-3", "f-4"], "pos flag yapılandırma boşluğu = f-3,f-4 (percentage uçta)")
    expect(percentage_rollouts(snap["flags"]) == ["f-1", "f-3", "f-4"], "pos yüzde-bazlı flag = f-1,f-3,f-4")
    # negatif (degrade beklendiği gibi yakalanır)
    expect("r-1" not in failing_releases(snap), "neg sağlıklı production failing değil")
    expect("f-1" not in flag_config_gaps(snap["flags"]), "neg geçerli yüzde (25) yapılandırma boşluğu değil")
    expect("f-2" not in flag_config_gaps(snap["flags"]), "neg full stratejisi yapılandırma boşluğu değil")
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"callerid": "x"}) is not None, "neg callerid yakalanır")
    # tam-sağlıklı snapshot → boşluk/risk yok
    healthy = {
        "releases": [{"id": "r", "stage": "production", "health": "healthy"},
                     {"id": "c", "stage": "canary", "health": "healthy"}],
        "flags": [{"id": "f", "status": "active", "strategy": "percentage", "rolloutPct": 50}],
        "events": [{"id": "e", "type": "promote", "outcome": "success"}],
    }
    expect(failing_releases(healthy) == [], "pos sağlıklı → başarısız sürüm yok")
    expect(canary_risks(healthy) == [], "pos sağlıklı → canary riski yok")
    expect(flag_config_gaps(healthy["flags"]) == [], "pos sağlıklı → flag yapılandırma boşluğu yok")
    expect(failed_deployments(healthy["events"]) == [], "pos sağlıklı → başarısız dağıtım yok")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{pct}%") == {"pct"}, "pct_value placeholder parse")
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
        "ReleaseSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "releases": [{
                "id": "str", "version": "str (semver — kod)", "component": "str (vendor-nötr bileşen)",
                "stage": "draft|staging|canary|production|rolled_back",
                "rolloutPct": "num (0..100 kademeli yayma)", "health": "healthy|degraded|failing",
                "region": "str (global|UK|EU|NA|ME — NFR 10.7)", "createdAt": "ISO-8601", "mappedFr": "str (FR kodu)"
            }],
            "flags": [{
                "id": "str", "key": "str (flag anahtarı — kod)", "status": "active|inactive|archived",
                "strategy": "disabled|internal|percentage|full", "rolloutPct": "num (0..100)",
                "enabledTenants": "num (toplulaştırılmış SAYI — izinli; tenant kimliği/listesi DEĞİL)",
                "updatedAt": "ISO-8601", "mappedFr": "str"
            }],
            "events": [{
                "id": "str", "occurredAt": "ISO-8601", "type": "promote|rollback|flag_change|canary_pause",
                "actorRole": "platform_owner|platform_sre|platform_billing",
                "target": "str (sürüm versiyonu veya flag anahtarı — kod)",
                "outcome": "success|in_progress|failed", "mappedFr": "str"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. enabledTenants (toplulaştırılmış SAYI) izinli.",
        "failing_release": "stage in {production,canary} & health == failing (FR-AGT-006 dağıtım sağlık riski)",
        "canary_risk": "stage == canary & health != healthy (FR-AGT-005 kademeli yayma doğrulanamadı)",
        "failed_deployment": "event.outcome == failed (rollback gerekebilir)",
        "flag_config_gap": "strategy == percentage & (rolloutPct <= 0 || rolloutPct >= 100) (strateji/yüzde tutarsızlığı)"
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p08_releases_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
