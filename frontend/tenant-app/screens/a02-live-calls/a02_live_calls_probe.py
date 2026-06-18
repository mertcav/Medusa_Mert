#!/usr/bin/env python3
# WBS 13.4.2 — A-02 "Canlı Çağrılar" (Live Calls) doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (countBy*/flaggedCalls/handoffPending/latencyBreaches/
#               negativeSentimentCalls/callsAssignedTo/concurrencyUtilPct/staleSnapshot/attentionCalls/
#               openAttentionCount/tone'lar/assertNoPii) + samples/* snapshot doğrulaması
#   selftest  — pozitif + negatif kendi-testleri (degrade senaryolar beklendiği gibi eler)
#   schema    — snapshot şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/live-calls.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a02-live-calls-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "live-calls", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "live-calls.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

FRESHNESS_BUDGET_SEC = 60
LIVE_LATENCY_BUDGET_MS = 1200

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential",
                         "password", "privatekey", "kmskey"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/live-calls.ts ile birebir) ──────────────────

def count_by(calls, field):
    out = {}
    for c in calls:
        out[c[field]] = out.get(c[field], 0) + 1
    return out


def count_by_state(calls):
    return count_by(calls, "state")


def count_by_direction(calls):
    return count_by(calls, "direction")


def count_by_turn_state(calls):
    return count_by(calls, "turnState")


def flagged_calls(calls):
    return [c for c in calls if c["flagged"]]


def handoff_pending(calls):
    return [c for c in calls if c["handoffRequested"]]


def latency_breaches(calls, budget_ms=LIVE_LATENCY_BUDGET_MS):
    return [c for c in calls if c["liveLatencyMs"] > budget_ms]


def negative_sentiment_calls(calls):
    return [c for c in calls if c["sentiment"] == "negative"]


def calls_assigned_to(calls, agent_ref):
    return [c for c in calls if c["assignedAgentRef"] == agent_ref]


def concurrency_util_pct(snap):
    cap = snap["capacity"]
    if cap["concurrentLimit"] <= 0:
        return 0
    return min(100, round((cap["concurrentActive"] / cap["concurrentLimit"]) * 100))


def stale_snapshot(snap, budget_sec=FRESHNESS_BUDGET_SEC):
    return snap["dataAgeSeconds"] > budget_sec


def attention_calls(calls):
    breach = {c["id"] for c in latency_breaches(calls)}
    return [c for c in calls if c["flagged"] or c["handoffRequested"] or c["id"] in breach]


def open_attention_count(snap):
    calls = snap["calls"]
    return (len(flagged_calls(calls))
            + len(handoff_pending(calls))
            + len(latency_breaches(calls))
            + (1 if stale_snapshot(snap) else 0)
            + (1 if concurrency_util_pct(snap) >= 90 else 0))


def state_tone(s):
    return {"ringing": "info", "in_progress": "success", "on_hold": "warning",
            "transferring": "info", "wrapup": "neutral"}[s]


def turn_tone(t):
    return {"listen": "neutral", "capture": "info", "think": "info", "speak": "success"}[t]


def direction_tone(d):
    return {"inbound": "info", "outbound": "neutral"}[d]


def sentiment_tone(s):
    return {"positive": "success", "neutral": "neutral", "negative": "danger"}[s]


def latency_tone(ms, budget_ms=LIVE_LATENCY_BUDGET_MS):
    if ms > budget_ms:
        return "danger"
    if ms > budget_ms * 0.75:
        return "warning"
    return "success"


def handoff_tone(b):
    return "warning" if b else "neutral"


def flag_tone(b):
    return "danger" if b else "neutral"


def util_tone(pct):
    if pct >= 90:
        return "danger"
    if pct >= 75:
        return "warning"
    return "success"


def freshness_tone(stale):
    return "danger" if stale else "success"


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
    """live-calls.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
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
    chk(spec.get("wbs") == "13.4.2", "S0 spec.wbs=13.4.2")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/live-calls/page.tsx mevcut")
    chk('data-screen="A-02"' in page, 'S1 data-screen="A-02" işaretli')
    chk("İskelet ekran — A-02" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/live-calls" in page, "S2 veri seam (lib/tenant/live-calls) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a02.*); hardcoded TR/EN cümle yok
    chk("screen.a02." in page, "S3 screen.a02.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/live-calls.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(snap\)", data) is not None, "S4 getLiveCalls assertNoPii çağırır")
    chk("phonenumber" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham numara + CDR yasak (BRD §17.7)")
    chk("maskedParty" in data, "S4 taraf MASKELENMİŞ etiketle (ham numara değil)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-ANA-012/008/006 + SAD §6.1 karşılanır
    a02 = tr.get("screen", {}).get("a02", {})
    sec = a02.get("section", {})
    for s in ("summary", "states", "attention", "active"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk(set(["ringing", "in_progress", "on_hold", "transferring", "wrapup"]).issubset(a02.get("state", {}).keys()), "S5 çağrı durumları (aktif çağrı izleme)")
    chk(set(["listen", "capture", "think", "speak"]).issubset(a02.get("turn", {}).keys()) and "countByTurnState" in data, "S5 turn state machine (SAD §6.1)")
    chk(set(["inbound", "outbound"]).issubset(a02.get("direction", {}).keys()), "S5 çağrı yönü (inbound/outbound)")
    chk("staleSnapshot" in data and "FRESHNESS_BUDGET_SEC = 60" in data and "freshness" in a02.get("kpi", {}), "S5 gerçek zamanlılık ≤60 sn (FR-ANA-012/SR-ANA-012)")
    chk("flaggedCalls" in data and "flagged" in a02.get("kpi", {}), "S5 kritik konuşma işaretleme (FR-ANA-008)")
    chk("latency_breakdown" in a02 and "LIVE_LATENCY_BUDGET_MS = 1200" in data, "S5 STT/LLM/TTS gecikme kırılımı (FR-ANA-006) + e2e bütçe (NFR 10.1)")
    chk("handoffPending" in data and "handoff" in a02.get("kpi", {}), "S5 insan aktarım talebi")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a02.{rk}"
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
        vt = resolve(tr, f"screen.a02.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("countByState", "countByDirection", "countByTurnState", "flaggedCalls", "handoffPending",
               "latencyBreaches", "negativeSentimentCalls", "callsAssignedTo", "concurrencyUtilPct",
               "staleSnapshot", "attentionCalls", "openAttentionCount", "stateTone", "turnTone",
               "directionTone", "sentimentTone", "latencyTone", "handoffTone", "flagTone", "utilTone", "freshnessTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
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

def _call(cid, state="in_progress", turn="speak", direction="inbound", lat=700,
          sentiment="neutral", flagged=False, handoff=False, assigned=None):
    return {"id": cid, "callRef": cid, "direction": direction, "state": state, "turnState": turn,
            "agentRef": "AGT-1", "agentName": "Karşılama", "assignedAgentRef": assigned,
            "maskedParty": "+90 5•• ••• ••00", "startedAt": "t0", "durationSec": 60,
            "liveLatencyMs": lat, "sttMs": 100, "llmMs": 400, "ttsMs": 200,
            "sentiment": sentiment, "flagged": flagged, "flagReason": None, "handoffRequested": handoff}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    calls = [
        _call("E1", state="in_progress", direction="inbound", lat=700, sentiment="neutral"),
        _call("E2", state="on_hold", turn="think", direction="inbound", lat=1300, sentiment="negative", flagged=True),
        _call("E3", state="transferring", turn="listen", direction="outbound", lat=600, sentiment="neutral", handoff=True, assigned="OP-9"),
        _call("E4", state="wrapup", turn="listen", direction="outbound", lat=500, sentiment="positive"),
    ]
    snap = {"dataAgeSeconds": 10, "capacity": {"concurrentLimit": 250, "concurrentActive": 60}, "calls": calls}

    chk(count_by_state(calls) == {"in_progress": 1, "on_hold": 1, "transferring": 1, "wrapup": 1}, "countByState")
    chk(count_by_direction(calls) == {"inbound": 2, "outbound": 2}, "countByDirection")
    chk(count_by_turn_state(calls) == {"speak": 1, "think": 1, "listen": 2}, "countByTurnState")
    chk([c["id"] for c in flagged_calls(calls)] == ["E2"], "flaggedCalls=[E2]")
    chk([c["id"] for c in handoff_pending(calls)] == ["E3"], "handoffPending=[E3]")
    chk([c["id"] for c in latency_breaches(calls)] == ["E2"], "latencyBreaches=[E2] (>1200)")
    chk([c["id"] for c in negative_sentiment_calls(calls)] == ["E2"], "negativeSentimentCalls=[E2]")
    chk([c["id"] for c in calls_assigned_to(calls, "OP-9")] == ["E3"], "callsAssignedTo(OP-9)=[E3] (view-own)")
    chk([c["id"] for c in attention_calls(calls)] == ["E2", "E3"], "attentionCalls=[E2,E3]")
    chk(concurrency_util_pct(snap) == 24, "concurrencyUtilPct=24")
    chk(concurrency_util_pct({"capacity": {"concurrentLimit": 0, "concurrentActive": 5}}) == 0, "concurrencyUtilPct limit=0 → 0")
    chk(stale_snapshot(snap) is False and stale_snapshot({"dataAgeSeconds": 61}) is True, "staleSnapshot (60 sn bütçe)")
    # openAttentionCount: flagged(1) + handoff(1) + breach(1) + stale(0) + util<90(0) = 3
    chk(open_attention_count(snap) == 3, "openAttentionCount=3")
    # tone eşlemeleri
    chk(state_tone("in_progress") == "success" and state_tone("on_hold") == "warning" and state_tone("ringing") == "info", "stateTone")
    chk(turn_tone("speak") == "success" and turn_tone("listen") == "neutral" and turn_tone("capture") == "info", "turnTone")
    chk(direction_tone("inbound") == "info" and direction_tone("outbound") == "neutral", "directionTone")
    chk(sentiment_tone("negative") == "danger" and sentiment_tone("positive") == "success" and sentiment_tone("neutral") == "neutral", "sentimentTone")
    chk(latency_tone(1300) == "danger" and latency_tone(1000) == "warning" and latency_tone(700) == "success", "latencyTone (1200 bütçe)")
    chk(handoff_tone(True) == "warning" and handoff_tone(False) == "neutral", "handoffTone")
    chk(flag_tone(True) == "danger" and flag_tone(False) == "neutral", "flagTone")
    chk(util_tone(95) == "danger" and util_tone(80) == "warning" and util_tone(50) == "success", "utilTone")
    chk(freshness_tone(True) == "danger" and freshness_tone(False) == "success", "freshnessTone")
    # assertNoPii — operasyonel META İZİNLİ (callRef/agentRef/maskedParty), ham içerik + sır YASAK
    chk(assert_no_pii({"c": _call("E1")}) is None, "assertNoPii operasyonel META + maskeli taraf İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"phoneNumber": "1"}}) == "$.x.phoneNumber", "assertNoPii ham numara yakalar")
    chk(assert_no_pii({"x": {"recording": "u"}}) == "$.x.recording", "assertNoPii ham kayıt yakalar")
    chk(assert_no_pii({"x": {"customer": {"ssn": "1"}}}) == "$.x.customer", "assertNoPii müşteri PII yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii sır yakalar (NFR 10.6)")

    # samples doğrulaması
    for name in ("live-clean.json", "live-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        cs = snp["calls"]
        chk(len(cs) == exp.get("active_count"), f"{name} active_count={exp.get('active_count')}")
        chk(len(flagged_calls(cs)) == exp.get("flagged_count"), f"{name} flagged_count={exp.get('flagged_count')}")
        chk(len(handoff_pending(cs)) == exp.get("handoff_pending"), f"{name} handoff_pending={exp.get('handoff_pending')}")
        chk(len(latency_breaches(cs)) == exp.get("latency_breaches"), f"{name} latency_breaches={exp.get('latency_breaches')}")
        chk(len(negative_sentiment_calls(cs)) == exp.get("negative_count"), f"{name} negative_count={exp.get('negative_count')}")
        chk(concurrency_util_pct(snp) == exp.get("concurrency_util"), f"{name} concurrency_util={exp.get('concurrency_util')}")
        chk(stale_snapshot(snp) == exp.get("stale"), f"{name} stale={exp.get('stale')}")
        chk(open_attention_count(snp) == exp.get("open_attention"), f"{name} open_attention={exp.get('open_attention')}")
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

    clean = [_call("E1", lat=700), _call("E2", state="wrapup", turn="listen", lat=540, sentiment="positive")]
    clean_snap = {"dataAgeSeconds": 8, "capacity": {"concurrentLimit": 200, "concurrentActive": 20}, "calls": clean}
    # pozitif (temiz → boş/sıfır)
    expect(flagged_calls(clean) == [], "pos kritik flag yok")
    expect(handoff_pending(clean) == [], "pos aktarım talebi yok")
    expect(latency_breaches(clean) == [], "pos gecikme ihlali yok")
    expect(negative_sentiment_calls(clean) == [], "pos olumsuz duygu yok")
    expect(stale_snapshot(clean_snap) is False, "pos veri taze")
    expect(concurrency_util_pct(clean_snap) == 10, "pos util=10")
    expect(open_attention_count(clean_snap) == 0, "pos openAttentionCount=0")
    expect(attention_calls(clean) == [], "pos dikkat gerektiren yok")
    # negatif (degrade beklendiği gibi yakalanır)
    bad = [
        _call("E1", lat=1500, sentiment="negative", flagged=True),
        _call("E2", state="transferring", turn="listen", lat=600, handoff=True),
        _call("E3", state="in_progress", lat=1300, sentiment="negative"),
    ]
    bad_snap = {"dataAgeSeconds": 95, "capacity": {"concurrentLimit": 100, "concurrentActive": 95}, "calls": bad}
    expect([c["id"] for c in flagged_calls(bad)] == ["E1"], "neg kritik flag (E1)")
    expect([c["id"] for c in handoff_pending(bad)] == ["E2"], "neg aktarım talebi (E2)")
    expect([c["id"] for c in latency_breaches(bad)] == ["E1", "E3"], "neg gecikme ihlali (E1,E3)")
    expect(stale_snapshot(bad_snap) is True, "neg veri bayat (>60 sn)")
    expect(concurrency_util_pct(bad_snap) == 95, "neg util=95 (≥90)")
    # openAttentionCount: flagged(1)+handoff(1)+breach(2)+stale(1)+util≥90(1) = 6
    expect(open_attention_count(bad_snap) == 6, "neg openAttentionCount toplamı=6")
    expect([c["id"] for c in attention_calls(bad)] == ["E1", "E2", "E3"], "neg dikkat gerektiren (E1,E2,E3)")
    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"privateKey": "x"}]}) is not None, "neg privateKey yakalanır")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")
    # tone sınır
    expect(latency_tone(LIVE_LATENCY_BUDGET_MS + 1) == "danger", "neg gecikme>bütçe → danger")
    expect(util_tone(90) == "danger", "neg util=90 → danger")
    # placeholder ayrıştırma
    expect(placeholders("STT {stt} · LLM {llm}") == {"stt", "llm"}, "placeholder parse")
    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 70, "spec ≥70 referans anahtar")
    expect(spec["budgets"] == {"freshness_sec": 60, "live_latency_ms": 1200}, "spec bütçeleri (60 sn / 1200 ms)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "LiveSnapshot": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "dataAgeSeconds": "int (veri yaşı — gerçek zamanlılık SR-ANA-012; >60 = bayat)",
            "refreshIntervalSec": "int (panel yenileme aralığı — ≤60 FR-ANA-012)",
            "capacity": {"concurrentLimit": "int (atanan eşzamanlılık kotası; 0=tanımsız)", "concurrentActive": "int (fleet aktif)"},
            "calls": [{"id": "str (oturum REFERANSI — içerik değil)", "callRef": "str (gösterim referansı)",
                       "direction": "inbound|outbound", "state": "ringing|in_progress|on_hold|transferring|wrapup",
                       "turnState": "listen|capture|think|speak (SAD §6.1)", "agentRef": "str", "agentName": "str (tenant kendi — izinli)",
                       "assignedAgentRef": "str|null (view-own scope)", "maskedParty": "str (MASKELENMİŞ — ham numara DEĞİL)",
                       "startedAt": "ISO-8601", "durationSec": "int (snapshot-göreli)", "liveLatencyMs": "int (e2e — NFR 10.1)",
                       "sttMs": "int", "llmMs": "int", "ttsMs": "int (FR-ANA-006 kırılım)",
                       "sentiment": "positive|neutral|negative", "flagged": "bool (FR-ANA-008)",
                       "flagReason": "str|null (kod/etiket — PII değil)", "handoffRequested": "bool"}]
        },
        "budgets": {"FRESHNESS_BUDGET_SEC": 60, "LIVE_LATENCY_BUDGET_MS": 1200},
        "hijyen": "A-02 yalnız OPERASYONEL META gösterir (çağrı REFERANSI/durum/gecikme/agent + MASKELENMİŞ taraf). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR) YOK (BRD §17.7 + §17.6 PII redaction); FORBIDDEN_SECRET_KEYS dışı sır/credential YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. Canlı dinleme/transkript derin aksiyon → A-12 (görsel kapı + backend). Gerçek zamanlılık ≤60 sn (FR-ANA-012/SR-ANA-012)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a02_live_calls_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
