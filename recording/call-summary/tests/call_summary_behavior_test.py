#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.7 — Çağrı özeti üretimi DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.1/11.2/11.3/11.4 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import call_summary_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def seg(seq, speaker):
    return {"seq": seq, "speaker": speaker}


def req(**kw):
    # Varsayılan: 11.4 REDACTED + redacted + 2 segment; dayanaklı kapalı-sözlük özet; storage=home(TR).
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "call_id": "call-b",
        "direction": "inbound", "upstream_redaction_decision": "REDACTED", "redaction_state": "redacted",
        "execution_plane": "analytics_async",
        "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
        "segments": [seg(1, "caller"), seg(2, "agent")],
        "summary": {
            "outcome": "contained", "intent": "billing_inquiry",
            "disposition": "resolved", "completion": "completed",
            "grounded_in": {"outcome": [2], "intent": [1], "disposition": [2], "completion": [2]},
            "key_points": [{"id": "kp-1", "grounded_in": [1]}, {"id": "kp-2", "grounded_in": [2]}],
        },
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


def _mismatch(s, r):
    exp = s.get("expected", {})
    for k in ("terminal", "block_reason", "field_count", "key_point_count", "grounded",
              "summary_persisted", "no_summary_persisted"):
        if k in exp and exp[k] != r.get(k):
            return True
    return False


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: SUMMARIZED|NO_SUMMARY|NO_CONTENT|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı REDACTED+redacted → SUMMARIZED", P.build(req(), SPEC)["terminal"] == "SUMMARIZED")

h = P.build(req(), SPEC)

# ── K2 dayanak/sadakat ÇEKİRDEK (BRD §8.1 / FR-ANA-002) ──────────────────────
case("K2 sağlıklı: her alan + anahtar-nokta dayanaklı (grounded=true)", h["grounded"] is True)
case("K2 sağlıklı: ungrounded_claim=0", h["violations"]["ungrounded_claim"] == 0)
dg = P.build(req(), SPEC, inject=["drop_grounding"])
case("K2 inject drop_grounding → ungrounded_claim>0 (dayanaksız alan)", dg["violations"]["ungrounded_claim"] > 0)
case("K2 inject drop_grounding → grounded=false", dg["grounded"] is False)
case("K2 inject drop_grounding → kapı ELER", gate(dg) is False)
fb = P.build(req(), SPEC, inject=["fabricate_field"])
case("K2 inject fabricate_field → ungrounded_claim>0 (halüsinasyon: olmayan seq)", fb["violations"]["ungrounded_claim"] > 0)
case("K2 inject fabricate_field → kapı ELER", gate(fb) is False)
case("K2 SUMMARIZED ⇒ ungrounded_claim=0 (sağlıklı invariant)",
     h["terminal"] != "SUMMARIZED" or h["violations"]["ungrounded_claim"] == 0)

# ── K3 kapalı sözlük ÇEKİRDEK (FR-ANA-002 / DB §19 / FR-OUT-011) ─────────────
bad = P.build(req(summary={"outcome": "made_up", "intent": "billing_inquiry", "disposition": "resolved",
                           "completion": "completed",
                           "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                           "key_points": []}), SPEC)
case("K3 sözlük-dışı outcome → BLOCK invalid_summary_field", bad["terminal"] == "BLOCK" and bad["block_reason"] == "invalid_summary_field")
case("K3 sözlük-dışı → no summary (fail-closed)", bad["no_summary_persisted"] is True)
bi = P.build(req(summary={"outcome": "contained", "intent": "zzz_unknown", "disposition": "resolved",
                          "completion": "completed",
                          "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                          "key_points": []}), SPEC)
case("K3 katalog-dışı intent → BLOCK", bi["terminal"] == "BLOCK" and bi["block_reason"] == "invalid_summary_field")
mr = P.build(req(summary={"outcome": "contained", "intent": "billing_inquiry", "completion": "completed",
                          "grounded_in": {"outcome": [1], "intent": [1], "completion": [1]}, "key_points": []}), SPEC)
case("K3 zorunlu alan eksik (disposition) → BLOCK", mr["terminal"] == "BLOCK" and mr["block_reason"] == "invalid_summary_field")
vb = P.build(req(summary={"outcome": "made_up", "intent": "billing_inquiry", "disposition": "resolved",
                          "completion": "completed",
                          "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                          "key_points": []}), SPEC, inject=["vocab_bypass"])
case("K3 inject vocab_bypass → invalid_field>0 (sözlük-dışı kabul)", vb["violations"]["invalid_field"] > 0)
case("K3 inject vocab_bypass → kapı ELER", gate(vb) is False)

# ── K4 PII-güvenli kaynak + ham PII sızıntısı yok ÇEKİRDEK (FR-REC-004, BRD §17.7) ──
pm = P.build(req(redaction_state="pending"), SPEC)
case("K4 pending kaynak → BLOCK premature_summary", pm["terminal"] == "BLOCK" and pm["block_reason"] == "premature_summary")
case("K4 pending kaynak → no summary (fail-closed; PII koruması)", pm["no_summary_persisted"] is True)
sp = P.build(req(redaction_state="pending"), SPEC, inject=["summarize_pending"])
case("K4 inject summarize_pending → premature_summary>0", sp["violations"]["premature_summary"] > 0)
case("K4 inject summarize_pending → kapı ELER", gate(sp) is False)
case("K4 sağlıklı: plan/audit ham PII değeri taşımaz",
     all(k not in json.dumps(h["audit"]) for k in ("customer_phone_value", "card_pan_value", "summary_text", "summary_prose", "transcript_text")))
pl = P.build(req(summary={"outcome": "contained", "intent": "billing_inquiry", "disposition": "resolved",
                          "completion": "completed",
                          "grounded_in": {"outcome": [1], "intent": [1], "disposition": [1], "completion": [1]},
                          "key_points": [{"id": "kp-1", "grounded_in": [1], "token": "[PHONE]"}]}),
              SPEC, inject=["pii_leak"])
case("K4 inject pii_leak → pii_leak>0", pl["violations"]["pii_leak"] > 0)
case("K4 inject pii_leak → kapı ELER", gate(pl) is False)
case("K4 not_required kaynak da PII-güvenli → SUMMARIZED",
     P.build(req(upstream_redaction_decision="NOT_REQUIRED", redaction_state="not_required"), SPEC)["terminal"] == "SUMMARIZED")

# ── K5 atlanamaz / fail-closed ÇEKİRDEK ──────────────────────────────────────
sk = P.build(req(), SPEC, inject=["skip_summary"])
case("K5 inject skip_summary → summary_skip>0", sk["violations"]["summary_skip"] > 0)
case("K5 inject skip_summary → false_grounding>0 (doğrulanmadan SUMMARIZED)", sk["violations"]["false_grounding"] > 0)
case("K5 inject skip_summary → kapı ELER", gate(sk) is False)
fg = P.build(req(), SPEC, inject=["false_grounding"])
case("K5 inject false_grounding → false_grounding>0 + ungrounded_claim>0",
     fg["violations"]["false_grounding"] > 0 and fg["violations"]["ungrounded_claim"] > 0)
case("K5 inject false_grounding → kapı ELER", gate(fg) is False)
fo = P.build(req(redaction_state="pending"), SPEC, inject=["failopen_summary"])
case("K5 inject failopen_summary → failopen>0", fo["violations"]["failopen"] > 0)
case("K5 inject failopen_summary → kapı ELER", gate(fo) is False)
case("K5 SUMMARIZED ⇒ grounded ∧ false_grounding=0 (sağlıklı)",
     h["grounded"] is True and h["violations"]["false_grounding"] == 0)

# ── K6 içerik kapısı ÇEKİRDEK (FR-REC-002 aşağı akış) ────────────────────────
for up, rstate in (("NO_CONTENT", "not_required"), ("BLOCK", "pending")):
    rr = P.build(req(upstream_redaction_decision=up, redaction_state=rstate, segments=[]), SPEC)
    case("K6 upstream %s → NO_CONTENT + no summary" % up,
         rr["terminal"] == "NO_CONTENT" and rr["no_summary_persisted"] is True and rr["summary_persisted"] is False)
oc = P.build(req(upstream_redaction_decision="NO_CONTENT", redaction_state="not_required"), SPEC, inject=["persist_when_no_content"])
case("K6 inject persist_when_no_content → over_capture>0", oc["violations"]["over_capture"] > 0)
case("K6 inject persist_when_no_content → kapı ELER", gate(oc) is False)

# ── boş transkript → NO_SUMMARY ──────────────────────────────────────────────
em = P.build(req(segments=[], summary={"outcome": "abandoned", "intent": "other", "disposition": "no_action",
                                       "completion": "not_completed", "grounded_in": {}, "key_points": []}), SPEC)
case("boş transkript → NO_SUMMARY", em["terminal"] == "NO_SUMMARY")
case("boş transkript → ihlal yok + kapı geçer", all(x == 0 for x in em["violations"].values()) and gate(em) is True)

# ── K7 residency korunur (NFR 10.7) ──────────────────────────────────────────
case("K7 storage=home(TR) → ihlal yok", P.build(req(storage_region="TR"), SPEC)["violations"]["residency_violation"] == 0)
rl = P.build(req(), SPEC, inject=["residency_leak"])
case("K7 inject residency_leak → residency_violation>0", rl["violations"]["residency_violation"] > 0)
case("K7 inject residency_leak → kapı ELER", gate(rl) is False)

# ── K8 asenkron / hot-path dışı (FR-RES-011) ─────────────────────────────────
case("K8 sağlıklı execution_plane=analytics_async", h["execution_plane"] == "analytics_async" and h["violations"]["hotpath_violation"] == 0)
hp = P.build(req(), SPEC, inject=["hotpath_exec"])
case("K8 inject hotpath_exec → hotpath_violation>0 + plane=hot_path",
     hp["violations"]["hotpath_violation"] > 0 and hp["execution_plane"] == "hot_path")
case("K8 inject hotpath_exec → kapı ELER", gate(hp) is False)
case("K8 plane=hot_path girdi → hotpath_violation>0", P.build(req(execution_plane="hot_path"), SPEC)["violations"]["hotpath_violation"] > 0)

# ── K9 kanıt ─────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 kanıt request taşır", ev["request_id"] == "req-b")
case("K9 kanıt upstream/redaction/field_count/grounded taşır",
     all(k in ev for k in ("upstream_redaction_decision", "redaction_state", "field_count", "grounded")))
case("K9 missing_evidence=0", P.build(req(), SPEC)["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result/outcome/tenant taşır",
     au["result"] == "SUMMARIZED" and au["outcome"] == "contained" and au["tenant_id"] == "t-acme")
na = P.build(req(), SPEC, inject=["no_audit"])
case("K10 inject no_audit → missing_audit>0", na["violations"]["missing_audit"] > 0)
case("K10 inject no_audit → audit None", na["audit"] is None)

# ── K11 audit ham PII / özet-prose taşımaz ──────────────────────────────────
case("K11 audit ham PII değeri / özet-prose / transkript-metni yok",
     all(k not in json.dumps(au) for k in ("customer_phone_value", "card_pan_value", "summary_text", "summary_prose", "transcript_text", "raw_audio")))

# ── K12 sır/PII yok + tenant izolasyonu ──────────────────────────────────────
ct = P.build(req(), SPEC, inject=["cross_tenant"])
case("K12 inject cross_tenant → cross_tenant>0 + BLOCK", ct["violations"]["cross_tenant"] > 0 and ct["terminal"] == "BLOCK")
bm = P.build(req(bind_tenant="t-other"), SPEC)
case("K12 bind mismatch → cross_tenant>0 + kapı ELER", bm["violations"]["cross_tenant"] > 0 and gate(bm) is False)
case("K12 leak: ham uzun rakam (kart/telefon) yakalanır", len(P.scan_leaks('{"x": "4111111111111111"}')) > 0)
case("K12 leak: enum/seq/maskeli-token temiz", P.scan_leaks('{"outcome": "contained", "token": "[PHONE]"}') == [])

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
    case("≥12 pass örnek", pass_n >= 12)
    case("≥12 degrade örnek", fail_n >= 12)


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
