#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.3 — Transkript üretimi + timeline DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.1/11.2 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import transcript_build_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan: 11.1 RECORD + channels=2 + 3 final turn + 3 sistem olay; storage=home(TR).
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "call_id": "call-b",
        "direction": "inbound", "upstream_decision": "RECORD", "channels": 2,
        "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
        "turn_events": [
            {"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "end_ms": 2000, "kind": "final", "confidence": 0.95},
            {"turn_id": "turn-2", "speaker": "agent",  "start_ms": 2500, "end_ms": 4000, "kind": "final", "confidence": 0.97},
            {"turn_id": "turn-3", "speaker": "caller", "start_ms": 4500, "end_ms": 5200, "kind": "final", "confidence": 0.93},
        ],
        "system_events": [
            {"event_id": "ev-1", "event_type": "call_start", "at_ms": 0},
            {"event_id": "ev-2", "event_type": "ai_disclosure", "at_ms": 200},
            {"event_id": "ev-3", "event_type": "call_end", "at_ms": 6000},
        ],
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


def _mismatch(s, r):
    exp = s.get("expected", {})
    for k in ("terminal", "block_reason", "segment_count", "timeline_count",
              "redaction_state", "content_persisted", "no_content_persisted"):
        if k in exp and exp[k] != r.get(k):
            return True
    return False


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: TRANSCRIPT|NO_TRANSCRIPT|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı RECORD+3turn → TRANSCRIPT", P.build(req(), SPEC)["terminal"] == "TRANSCRIPT")

# ── K2 zaman-sıralı üretim ÇEKİRDEK (BRD §8.1 kronoloji) ─────────────────────
h = P.build(req(), SPEC)
case("K2 seq 1..3 bitişik", [s["seq"] for s in h["segments"]] == [1, 2, 3])
case("K2 started_ms monoton artan", [s["started_ms"] for s in h["segments"]] == [1000, 2500, 4500])
u = P.build(req(turn_events=[
    {"turn_id": "turn-3", "speaker": "caller", "start_ms": 4500, "kind": "final"},
    {"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "kind": "final"},
    {"turn_id": "turn-2", "speaker": "agent",  "start_ms": 2500, "kind": "final"},
]), SPEC)
case("K2 sırasız girdi → kanonik sıralı çıkış", [s["started_ms"] for s in u["segments"]] == [1000, 2500, 4500])
case("K2 sırasız girdi → ordering_violation=0", u["violations"]["ordering_violation"] == 0)
ro = P.build(req(), SPEC, inject=["reorder_segments"])
case("K2 inject reorder_segments → ordering_violation>0", ro["violations"]["ordering_violation"] > 0)
case("K2 inject reorder_segments → kapı ELER", gate(ro) is False)
sg = P.build(req(), SPEC, inject=["seq_gap"])
case("K2 inject seq_gap → ordering_violation>0", sg["violations"]["ordering_violation"] > 0)
case("K2 inject seq_gap → kapı ELER", gate(sg) is False)

# ── K3 konuşmacı atfı ÇEKİRDEK (DB §21 speaker) ──────────────────────────────
case("K3 her segment geçerli speaker", all(s["speaker"] in P.VALID_SPEAKERS for s in h["segments"]))
hu = P.build(req(turn_events=[
    {"turn_id": "turn-1", "speaker": "caller", "start_ms": 1000, "kind": "final"},
    {"turn_id": "turn-2", "speaker": "human",  "start_ms": 2000, "kind": "final"},
]), SPEC)
case("K3 human (transfer) konuşmacısı geçerli", all(x == 0 for x in hu["violations"].values()))
ms = P.build(req(), SPEC, inject=["strip_speaker"])
case("K3 inject strip_speaker → missing_speaker>0", ms["violations"]["missing_speaker"] > 0)
case("K3 inject strip_speaker → kapı ELER", gate(ms) is False)
mm = P.build(req(channels=2), SPEC, inject=["misattribute_speaker"])
case("K3 inject misattribute_speaker → speaker_mismatch>0", mm["violations"]["speaker_mismatch"] > 0)
case("K3 inject misattribute_speaker → kapı ELER", gate(mm) is False)

# ── K4 tamlık ÇEKİRDEK (BRD §8.1) ────────────────────────────────────────────
case("K4 her final turn → segment (3 turn=3 segment)", h["segment_count"] == 3)
case("K4 timeline TÜM segment+olay (3+3=6)", h["timeline_count"] == 6)
dt = P.build(req(), SPEC, inject=["drop_turn"])
case("K4 inject drop_turn → turn_dropped>0", dt["violations"]["turn_dropped"] > 0)
case("K4 inject drop_turn → kapı ELER", gate(dt) is False)
du = P.build(req(), SPEC, inject=["duplicate_turn"])
case("K4 inject duplicate_turn → turn_duplicated>0", du["violations"]["turn_duplicated"] > 0)
case("K4 inject duplicate_turn → kapı ELER", gate(du) is False)
de = P.build(req(), SPEC, inject=["drop_event"])
case("K4 inject drop_event → event_dropped>0", de["violations"]["event_dropped"] > 0)
case("K4 inject drop_event → kapı ELER", gate(de) is False)

# ── K5 içerik kapısı ÇEKİRDEK (FR-REC-002 aşağı akış) ────────────────────────
for up in ("DISABLED", "NO_CONSENT", "BLOCK"):
    rr = P.build(req(upstream_decision=up), SPEC)
    case("K5 11.1 %s → NO_TRANSCRIPT + no content" % up,
         rr["terminal"] == "NO_TRANSCRIPT" and rr["no_content_persisted"] is True and rr["content_persisted"] is False)
oc = P.build(req(upstream_decision="DISABLED"), SPEC, inject=["persist_when_not_authorized"])
case("K5 inject persist_when_not_authorized → over_capture>0", oc["violations"]["over_capture"] > 0)
case("K5 inject persist_when_not_authorized → kapı ELER", gate(oc) is False)

# ── K6 residency korunur (NFR 10.7) ──────────────────────────────────────────
case("K6 storage=home(TR) → ihlal yok", P.build(req(storage_region="TR"), SPEC)["violations"]["residency_violation"] == 0)
rl = P.build(req(), SPEC, inject=["residency_leak"])
case("K6 inject residency_leak → residency_violation>0", rl["violations"]["residency_violation"] > 0)
case("K6 inject residency_leak → kapı ELER", gate(rl) is False)

# ── K7 redaction devri ÇEKİRDEK (FR-REC-004/005 aşağı akış) ──────────────────
case("K7 PII yok → redaction_state=not_required", h["redaction_state"] == "not_required")
case("K7 redaction_required → pending", P.build(req(redaction_required=True), SPEC)["redaction_state"] == "pending")
pr = P.build(req(), SPEC, inject=["premature_redaction"])
case("K7 inject premature_redaction → 'redacted' yayıldı", pr["redaction_state"] == "redacted")
case("K7 inject premature_redaction → premature_redaction>0", pr["violations"]["premature_redaction"] > 0)
case("K7 inject premature_redaction → kapı ELER", gate(pr) is False)
case("K7 üretilebilir redaction_state ⊆ {pending,not_required}",
     h["redaction_state"] in P.PRODUCIBLE_REDACTION)

# ── K8 fail-closed / ATLANAMAZ ───────────────────────────────────────────────
sk = P.build(req(), SPEC, inject=["skip_assembly"])
case("K8 inject skip_assembly → assembly_skip>0", sk["violations"]["assembly_skip"] > 0)
case("K8 inject skip_assembly → içerik (no_content=false)", sk["no_content_persisted"] is False)
case("K8 inject skip_assembly → kapı ELER", gate(sk) is False)
mf = P.build(req(turn_events=[{"speaker": "caller", "start_ms": 1000, "kind": "final"}]), SPEC)
case("K8 malformed turn → BLOCK invalid_turn_stream", mf["terminal"] == "BLOCK" and mf["block_reason"] == "invalid_turn_stream")
case("K8 malformed turn → no content (fail-closed)", mf["no_content_persisted"] is True)
fo = P.build(req(turn_events=[{"speaker": "caller", "start_ms": 1000, "kind": "final"}]), SPEC, inject=["failopen_assembly"])
case("K8 inject failopen_assembly → failopen>0", fo["violations"]["failopen"] > 0)
case("K8 inject failopen_assembly → kapı ELER", gate(fo) is False)

# ── K9 kanıt ─────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 kanıt request taşır", ev["request_id"] == "req-b")
case("K9 kanıt upstream/authorized/segment_count/redaction_state taşır",
     all(k in ev for k in ("upstream_decision", "authorized", "segment_count", "redaction_state")))
case("K9 missing_evidence=0", P.build(req(), SPEC)["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result/segment_count/tenant taşır",
     au["result"] == "TRANSCRIPT" and au["segment_count"] == 3 and au["tenant_id"] == "t-acme")
na = P.build(req(), SPEC, inject=["no_audit"])
case("K10 inject no_audit → missing_audit>0", na["violations"]["missing_audit"] > 0)
case("K10 inject no_audit → audit None", na["audit"] is None)

# ── K11 audit ham transkript/PII taşımaz ─────────────────────────────────────
case("K11 audit transkript-metni/telefon/ham-ses yok",
     all(k not in json.dumps(au) for k in ("transcript_text", "segment_text", "customer_phone_value", "raw_audio")))

# ── K12 sır/PII yok + tenant izolasyonu ──────────────────────────────────────
ct = P.build(req(), SPEC, inject=["cross_tenant"])
case("K12 inject cross_tenant → cross_tenant>0 + BLOCK", ct["violations"]["cross_tenant"] > 0 and ct["terminal"] == "BLOCK")
bm = P.build(req(bind_tenant="t-other"), SPEC)
case("K12 bind mismatch → cross_tenant>0 + kapı ELER", bm["violations"]["cross_tenant"] > 0 and gate(bm) is False)
case("K12 leak: ham telefon yakalanır", len(P.scan_leaks('{"x": "905551234567"}')) > 0)
case("K12 leak: kimlik/enum temiz", P.scan_leaks('{"call_id": "call-001", "speaker": "caller"}') == [])

# ── Pass/degrade örnek bütünlüğü ─────────────────────────────────────────────
if os.path.isdir(P.SAMPLES_DIR):
    pass_n = fail_n = 0
    for f in sorted(os.listdir(P.SAMPLES_DIR)):
        if not f.endswith(".json"):
            continue
        s = P._load(os.path.join(P.SAMPLES_DIR, f))
        r = P.build(s, SPEC)
        ok = gate(r)
        if s.get("expect", "pass") == "pass":
            pass_n += 1
            case("örnek pass beklenen geçer: %s" % f, ok and not _mismatch(s, r))
        else:
            fail_n += 1
            case("örnek degrade beklenen eler: %s" % f, not ok)
    case("≥11 pass örnek", pass_n >= 11)
    case("≥11 degrade örnek", fail_n >= 11)


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
