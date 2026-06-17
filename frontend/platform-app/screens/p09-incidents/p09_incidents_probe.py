#!/usr/bin/env python3
# WBS 13.2.9 — P-09 "Alarm & Incident (SRE)" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (alarmSeverityTone/alarmStateTone/alarmSignalTone/
#               incidentSeverityTone/incidentStatusTone/incidentEventTypeTone/countBySeverity/firingAlarms/
#               unacknowledgedAlarms/budgetBreaches/openIncidents/criticalOpenIncidents/escalationEvents/
#               resolvedIncidents/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/platform/incidents.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/platform-app
SPEC_PATH = os.path.join(HERE, "p09-incidents-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(platform)", "incidents", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "platform", "incidents.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

# Kritik alarm üretim bütçesi (NFR 10.1 / SR-PERF-008): ≤ 2 dk = 120 sn (lib/platform/incidents.ts ile birebir).
DETECTION_BUDGET_SEC = 120


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/platform/incidents.ts ile birebir) ─────────────────────

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "customer", "cardpan", "cvv", "iban",
                      "pii", "email", "ssn"]

ALARM_SEVERITY_TONE = {"critical": "danger", "warning": "warning", "info": "info"}
ALARM_STATE_TONE = {"firing": "danger", "pending": "warning", "acknowledged": "info", "resolved": "success"}
ALARM_SIGNAL_TONE = {"latency": "info", "error_rate": "warning", "capacity": "warning",
                     "spend": "warning", "resource": "warning", "security": "danger"}
INCIDENT_SEVERITY_TONE = {"sev1": "danger", "sev2": "warning", "sev3": "info"}
INCIDENT_STATUS_TONE = {"open": "danger", "acknowledged": "warning", "mitigated": "info", "resolved": "success"}
INCIDENT_EVENT_TYPE_TONE = {"triggered": "danger", "acknowledged": "info", "escalated": "warning",
                            "mitigated": "info", "resolved": "success", "note": "neutral"}


def alarm_severity_tone(s):
    return ALARM_SEVERITY_TONE[s]


def alarm_state_tone(s):
    return ALARM_STATE_TONE[s]


def alarm_signal_tone(s):
    return ALARM_SIGNAL_TONE[s]


def incident_severity_tone(s):
    return INCIDENT_SEVERITY_TONE[s]


def incident_status_tone(s):
    return INCIDENT_STATUS_TONE[s]


def incident_event_type_tone(t):
    return INCIDENT_EVENT_TYPE_TONE[t]


def count_by_severity(alarms):
    acc = {"critical": 0, "warning": 0, "info": 0}
    for a in alarms:
        acc[a["severity"]] += 1
    return acc


def firing_alarms(snap):
    return [a["id"] for a in snap["alarms"] if a["state"] == "firing"]


def unacknowledged_alarms(alarms):
    return [a["id"] for a in alarms if a["state"] in ("firing", "pending")]


def budget_breaches(alarms):
    return [a["id"] for a in alarms if a["detectionLatencySec"] > DETECTION_BUDGET_SEC]


def open_incidents(incidents):
    return [i["id"] for i in incidents if i["status"] != "resolved"]


def critical_open_incidents(incidents):
    return [i["id"] for i in incidents
            if i["severity"] in ("sev1", "sev2") and i["status"] != "resolved"]


def escalation_events(events):
    return [e["id"] for e in events if e["type"] == "escalated"]


def resolved_incidents(incidents):
    return [i["id"] for i in incidents if i["status"] == "resolved"]


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
    """incidents.ts interface alan adlarını kaba çıkar (PII-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.2.9", "S0 spec.wbs=13.2.9")
    chk(os.path.isfile(PAGE_PATH), "S1 incidents/page.tsx mevcut")
    chk('data-screen="P-09"' in page, 'S1 data-screen="P-09" işaretli')
    chk("İskelet ekran — P-09" not in page and "İskelet" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/platform/incidents" in page, "S2 veri seam (lib/platform/incidents) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.p09.*); hardcoded TR/EN cümle yok
    chk("screen.p09." in page, "S3 screen.p09.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı PII-free + ALTIN KURAL guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/platform/incidents.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getIncidents assertNoPii çağırır")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde iş-içeriği/PII alanı yok (sızıntı={leak})")
    chk("assigneeRole" in data and "scope" in data, "S4 on-call ROL (assigneeRole) + vendor-nötr scope (tenant kimliği değil)")

    # S5 — BRD §17.3/§15 içerik öğeleri karşılanır (alarm kataloğu + incident yönetimi) + bütçe/IR izlenir
    p09 = tr.get("screen", {}).get("p09", {})
    sec = p09.get("section", {})
    chk("alarms" in sec and "alarm_severity" in p09 and "alarm_signal" in p09, "S5 alarm kataloğu → section.alarms + alarm_severity.* + alarm_signal.* (BRD §15)")
    chk("incidents" in sec and "incident_severity" in p09 and "incident_status" in p09, "S5 incident yönetimi → section.incidents + incident_severity.* + incident_status.* (NFR 10.6)")
    chk("events" in sec and "incident_event_type" in p09, "S5 IR olay akışı → section.events + incident_event_type.*")
    chk("budget_alert" in p09 and "budget_ok" in p09, "S5 kritik alarm bütçesi uyarısı → budget_alert (NFR 10.1 / SR-PERF-008)")
    chk("critical_alert" in p09 and "critical_ok" in p09, "S5 kritik açık incident uyarısı → critical_alert (NFR 10.6)")
    chk("escalation_alert" in p09 and "firing_alert" in p09, "S5 eskalasyon + aktif alarm uyarısı")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.p09.{rk}"
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
        vt = resolve(tr, f"screen.p09.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("alarmSeverityTone", "alarmStateTone", "alarmSignalTone", "incidentSeverityTone",
               "incidentStatusTone", "incidentEventTypeTone", "countBySeverity", "firingAlarms",
               "unacknowledgedAlarms", "budgetBreaches", "openIncidents", "criticalOpenIncidents",
               "escalationEvents", "resolvedIncidents"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("DETECTION_BUDGET_SEC = 120" in data, "S7 DETECTION_BUDGET_SEC=120 (NFR 10.1 / SR-PERF-008)")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral (somut sağlayıcı/APM/on-call markası yok) + sır yok
    forbidden_vendors = ["openai", "twilio", "anthropic", "deepgram", "elevenlabs", "cartesia",
                         "telnyx", "splunk", "datadog", "gpt-", "claude-", "gemini", "llama",
                         "whisper", "pagerduty", "opsgenie", "victorops", "newrelic", "sentry.io",
                         "api_key", "secret="]
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

    # alarmSeverityTone
    chk(alarm_severity_tone("critical") == "danger", "alarm severity critical→danger")
    chk(alarm_severity_tone("warning") == "warning", "alarm severity warning→warning")
    chk(alarm_severity_tone("info") == "info", "alarm severity info→info")
    # alarmStateTone
    chk(alarm_state_tone("firing") == "danger", "alarm state firing→danger")
    chk(alarm_state_tone("pending") == "warning", "alarm state pending→warning")
    chk(alarm_state_tone("acknowledged") == "info", "alarm state acknowledged→info")
    chk(alarm_state_tone("resolved") == "success", "alarm state resolved→success")
    # alarmSignalTone
    chk(alarm_signal_tone("security") == "danger", "alarm signal security→danger")
    chk(alarm_signal_tone("latency") == "info", "alarm signal latency→info")
    chk(alarm_signal_tone("capacity") == "warning", "alarm signal capacity→warning")
    # incidentSeverityTone
    chk(incident_severity_tone("sev1") == "danger", "incident sev1→danger")
    chk(incident_severity_tone("sev2") == "warning", "incident sev2→warning")
    chk(incident_severity_tone("sev3") == "info", "incident sev3→info")
    # incidentStatusTone
    chk(incident_status_tone("open") == "danger", "incident status open→danger")
    chk(incident_status_tone("mitigated") == "info", "incident status mitigated→info")
    chk(incident_status_tone("resolved") == "success", "incident status resolved→success")
    # incidentEventTypeTone
    chk(incident_event_type_tone("triggered") == "danger", "event triggered→danger")
    chk(incident_event_type_tone("escalated") == "warning", "event escalated→warning")
    chk(incident_event_type_tone("resolved") == "success", "event resolved→success")
    chk(incident_event_type_tone("note") == "neutral", "event note→neutral")
    # assertNoPii
    chk(assert_no_pii({"alarms": [{"scope": "orchestrator/EU", "name": "x"}]}) is None, "assertNoPii temiz snapshot OK (scope/name izinli)")
    chk(assert_no_pii({"incidents": [{"transcript": "x"}]}) == "$.incidents[0].transcript", "assertNoPii transcript yakalar")
    chk(assert_no_pii({"customer": 1}) == "$.customer", "assertNoPii customer yakalar")
    chk(assert_no_pii({"recording": "u"}) == "$.recording", "assertNoPii recording yakalar")

    # samples doğrulaması
    for name in ("incidents-mixed.json", "incidents-empty.json"):
        snap = load_json(os.path.join(HERE, "samples", name))
        exp = snap.get("$expect", {})
        chk(count_by_severity(snap["alarms"]) == exp["count_by_severity"], f"{name} count_by_severity={exp['count_by_severity']}")
        chk(firing_alarms(snap) == exp["firing_alarms"], f"{name} firing_alarms={exp['firing_alarms']}")
        chk(unacknowledged_alarms(snap["alarms"]) == exp["unacknowledged_alarms"], f"{name} unacknowledged_alarms={exp['unacknowledged_alarms']}")
        chk(budget_breaches(snap["alarms"]) == exp["budget_breaches"], f"{name} budget_breaches={exp['budget_breaches']}")
        chk(open_incidents(snap["incidents"]) == exp["open_incidents"], f"{name} open_incidents={exp['open_incidents']}")
        chk(critical_open_incidents(snap["incidents"]) == exp["critical_open_incidents"], f"{name} critical_open_incidents={exp['critical_open_incidents']}")
        chk(escalation_events(snap["events"]) == exp["escalation_events"], f"{name} escalation_events={exp['escalation_events']}")
        chk(resolved_incidents(snap["incidents"]) == exp["resolved_incidents"], f"{name} resolved_incidents={exp['resolved_incidents']}")
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
        "alarms": [
            {"id": "al-1", "severity": "critical", "signal": "latency", "state": "firing", "detectionLatencySec": 45},
            {"id": "al-2", "severity": "warning", "signal": "capacity", "state": "pending", "detectionLatencySec": 150},   # bütçe aşımı
            {"id": "al-3", "severity": "critical", "signal": "error_rate", "state": "acknowledged", "detectionLatencySec": 200},  # bütçe aşımı
            {"id": "al-4", "severity": "info", "signal": "resource", "state": "resolved", "detectionLatencySec": 30},
            {"id": "al-5", "severity": "critical", "signal": "security", "state": "firing", "detectionLatencySec": 20},
        ],
        "incidents": [
            {"id": "in-1", "severity": "sev1", "status": "open"},          # kritik açık
            {"id": "in-2", "severity": "sev2", "status": "acknowledged"},  # kritik açık
            {"id": "in-3", "severity": "sev3", "status": "open"},          # açık ama kritik değil
            {"id": "in-4", "severity": "sev1", "status": "resolved"},      # çözüldü (kritik değil artık)
        ],
        "events": [
            {"id": "ev-1", "type": "triggered"},
            {"id": "ev-2", "type": "escalated"},
            {"id": "ev-3", "type": "acknowledged"},
            {"id": "ev-4", "type": "resolved"},
        ],
    }
    # pozitif — türetmeler
    expect(count_by_severity(snap["alarms"]) == {"critical": 3, "warning": 1, "info": 1}, "pos önem sayımı")
    expect(firing_alarms(snap) == ["al-1", "al-5"], "pos aktif alarm = al-1,al-5 (firing)")
    expect(unacknowledged_alarms(snap["alarms"]) == ["al-1", "al-2", "al-5"], "pos onay bekleyen = al-1,al-2,al-5 (firing+pending)")
    expect(budget_breaches(snap["alarms"]) == ["al-2", "al-3"], "pos bütçe aşan = al-2,al-3 (>120s)")
    expect(open_incidents(snap["incidents"]) == ["in-1", "in-2", "in-3"], "pos açık incident = in-1,in-2,in-3 (status!=resolved)")
    expect(critical_open_incidents(snap["incidents"]) == ["in-1", "in-2"], "pos kritik açık = in-1,in-2 (sev1/sev2 & açık)")
    expect(escalation_events(snap["events"]) == ["ev-2"], "pos eskalasyon = ev-2")
    expect(resolved_incidents(snap["incidents"]) == ["in-4"], "pos çözülen incident = in-4")
    # negatif (degrade beklendiği gibi yakalanır)
    expect("al-4" not in budget_breaches(snap["alarms"]), "neg 30s alarm bütçe aşımı değil")
    expect("al-3" not in firing_alarms(snap), "neg acknowledged alarm firing değil")
    expect("in-3" not in critical_open_incidents(snap["incidents"]), "neg sev3 açık incident kritik değil")
    expect("in-4" not in open_incidents(snap["incidents"]), "neg resolved incident açık değil")
    expect(assert_no_pii({"x": {"recording": "u"}}) is not None, "neg recording yakalanır")
    expect(assert_no_pii({"callerid": "x"}) is not None, "neg callerid yakalanır")
    # tam-sağlıklı snapshot → ihlal/risk yok
    healthy = {
        "alarms": [{"id": "a", "severity": "info", "signal": "latency", "state": "resolved", "detectionLatencySec": 40}],
        "incidents": [{"id": "i", "severity": "sev3", "status": "resolved"}],
        "events": [{"id": "e", "type": "resolved"}],
    }
    expect(firing_alarms(healthy) == [], "pos sağlıklı → aktif alarm yok")
    expect(budget_breaches(healthy["alarms"]) == [], "pos sağlıklı → bütçe aşımı yok")
    expect(critical_open_incidents(healthy["incidents"]) == [], "pos sağlıklı → kritik açık incident yok")
    expect(escalation_events(healthy["events"]) == [], "pos sağlıklı → eskalasyon yok")
    # placeholder ayrıştırma
    expect(placeholders("As of: {time}") == {"time"}, "placeholder parse")
    expect(placeholders("{count}/{budget}") == {"count", "budget"}, "budget_alert placeholder parse")
    # bütçe sabiti NFR 10.1
    expect(DETECTION_BUDGET_SEC == 120, "DETECTION_BUDGET_SEC=120 (NFR 10.1 ≤2dk)")
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
        "IncidentSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "alarms": [{
                "id": "str", "name": "str (alarm kural adı — kod; SAD §17.2)", "severity": "critical|warning|info",
                "signal": "latency|error_rate|capacity|spend|resource|security (vendor-nötr sinyal sınıfı; BRD §15)",
                "scope": "str (vendor-nötr bileşen/bölge — tenant kimliği DEĞİL)",
                "state": "firing|pending|acknowledged|resolved",
                "detectionLatencySec": "num (üretim gecikmesi; ≤120s NFR 10.1)", "firedAt": "ISO-8601", "mappedReq": "str"
            }],
            "incidents": [{
                "id": "str", "title": "str (kısa non-PII etiket — kod)", "severity": "sev1|sev2|sev3",
                "status": "open|acknowledged|mitigated|resolved",
                "assigneeRole": "platform_owner|platform_sre|platform_billing (on-call ROL — kişi/PII DEĞİL)",
                "linkedAlarm": "str (ilişkili alarm adı — kod)", "scope": "str (vendor-nötr bileşen/bölge)",
                "openedAt": "ISO-8601", "mappedReq": "str"
            }],
            "events": [{
                "id": "str", "occurredAt": "ISO-8601",
                "type": "triggered|acknowledged|escalated|mitigated|resolved|note",
                "actorRole": "platform_owner|platform_sre|platform_billing",
                "target": "str (incident id — kod)", "mappedReq": "str"
            }]
        },
        "altin_kural": "FORBIDDEN_PII_KEYS dışı iş-içeriği/son-müşteri alan adı yok (BRD §17.7); assertNoPii çalışma-anında doğrular. scope vendor-nötr bileşen/bölge (tenant kimliği değil); assigneeRole ROL (kişi/PII değil).",
        "budget_breach": "alarm.detectionLatencySec > 120 (NFR 10.1 / SR-PERF-008 kritik alarm ≤2dk ihlali)",
        "firing_alarm": "alarm.state == firing (anlık operasyon riski)",
        "critical_open_incident": "incident.severity in {sev1,sev2} & status != resolved (öncelikli müdahale; NFR 10.6)"
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: p09_incidents_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
