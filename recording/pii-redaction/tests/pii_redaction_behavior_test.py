#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.4 — PII redaction pipeline (async) DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.1/11.2/11.3 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import pii_redaction_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def seg(seq, speaker, spans):
    return {"seq": seq, "speaker": speaker, "pii_spans": spans}


def req(**kw):
    # Varsayılan: 11.3 TRANSCRIPT + pending + 2 segment (phone + email span); storage=home(TR).
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "call_id": "call-b",
        "direction": "inbound", "upstream_transcript_decision": "TRANSCRIPT",
        "redaction_state_in": "pending", "execution_plane": "analytics_async",
        "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
        "segments": [
            seg(1, "caller", [{"category": "phone", "start": 10, "length": 11}]),
            seg(2, "agent",  [{"category": "email", "start": 5, "length": 18}]),
        ],
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


def _mismatch(s, r):
    exp = s.get("expected", {})
    for k in ("terminal", "block_reason", "redaction_state_out", "directive_count",
              "pii_span_count", "masked_count", "access_ready", "no_content_persisted"):
        if k in exp and exp[k] != r.get(k):
            return True
    return False


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: REDACTED|NOT_REQUIRED|NO_CONTENT|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı pending+2span → REDACTED", P.build(req(), SPEC)["terminal"] == "REDACTED")

# ── K2 redaction tamlığı ÇEKİRDEK (FR-REC-004) ───────────────────────────────
h = P.build(req(), SPEC)
case("K2 her span maskeleme direktifi alır (2 span=2 direktif)", h["directive_count"] == 2 and h["masked_count"] == 2)
case("K2 tüm masked_token bracket-token", all(P.MASK_TOKEN_RE.match(d["masked_token"]) for d in h["directives"]))
case("K2 direktif kanonik (seq,start) sıralı",
     [(d["seq"], d["start"]) for d in h["directives"]] == sorted((d["seq"], d["start"]) for d in h["directives"]))
ls = P.build(req(), SPEC, inject=["leave_span"])
case("K2 inject leave_span → unredacted_pii>0", ls["violations"]["unredacted_pii"] > 0)
case("K2 inject leave_span → kapı ELER", gate(ls) is False)

# ── K3 durum geçişi ÇEKİRDEK (DB §21 redaction_state) ────────────────────────
case("K3 pending→redacted geçişi", h["redaction_state_in"] == "pending" and h["redaction_state_out"] == "redacted")
fr = P.build(req(), SPEC, inject=["false_redacted"])
case("K3 inject false_redacted → false_redacted>0 + unredacted_pii>0",
     fr["violations"]["false_redacted"] > 0 and fr["violations"]["unredacted_pii"] > 0)
case("K3 inject false_redacted → kapı ELER", gate(fr) is False)
sr = P.build(req(), SPEC, inject=["state_regression"])
case("K3 inject state_regression → state_regression>0 + state_out=pending",
     sr["violations"]["state_regression"] > 0 and sr["redaction_state_out"] == "pending")
case("K3 inject state_regression → kapı ELER", gate(sr) is False)
case("K3 redacted ⇒ unredacted_pii=0 (sağlıklı)", h["redaction_state_out"] == "redacted" and h["violations"]["unredacted_pii"] == 0)

# ── K4 ham PII sızıntısı yok ÇEKİRDEK (FR-REC-004, BRD §17.7) ─────────────────
case("K4 plan ham PII değeri taşımaz (yalnız maskeli token)",
     all(P.MASK_TOKEN_RE.match(d["masked_token"]) for d in h["directives"]))
case("K4 audit ham PII değeri taşımaz",
     all(k not in json.dumps(h["audit"]) for k in ("customer_phone_value", "card_pan_value", "otp_code_value", "transcript_text")))
pl = P.build(req(), SPEC, inject=["pii_leak"])
case("K4 inject pii_leak → pii_leak>0", pl["violations"]["pii_leak"] > 0)
case("K4 inject pii_leak → kapı ELER", gate(pl) is False)

# ── K5 atlanamaz / fail-closed ÇEKİRDEK ──────────────────────────────────────
sk = P.build(req(), SPEC, inject=["skip_redaction"])
case("K5 inject skip_redaction → redaction_skip>0", sk["violations"]["redaction_skip"] > 0)
case("K5 inject skip_redaction → unredacted_pii>0 (maskeleme yapılmadı)", sk["violations"]["unredacted_pii"] > 0)
case("K5 inject skip_redaction → kapı ELER", gate(sk) is False)
case("K5 access_ready ⇒ state_out üretilebilir", (not h["access_ready"]) or h["redaction_state_out"] in P.PRODUCIBLE_OUTPUT)
mf = P.build(req(segments=[seg(1, "caller", [{"category": "unknown_cat", "start": 1, "length": 2}])]), SPEC)
case("K5 malformed span → BLOCK invalid_redaction_input", mf["terminal"] == "BLOCK" and mf["block_reason"] == "invalid_redaction_input")
case("K5 malformed span → no content (fail-closed)", mf["no_content_persisted"] is True)
fo = P.build(req(segments=[seg(1, "caller", [{"category": "unknown_cat", "start": 1, "length": 2}])]), SPEC, inject=["failopen_redaction"])
case("K5 inject failopen_redaction → failopen>0", fo["violations"]["failopen"] > 0)
case("K5 inject failopen_redaction → kapı ELER", gate(fo) is False)

# ── K6 içerik kapısı ÇEKİRDEK (FR-REC-002 aşağı akış) ────────────────────────
for up in ("NO_TRANSCRIPT", "BLOCK"):
    rr = P.build(req(upstream_transcript_decision=up, segments=[]), SPEC)
    case("K6 upstream %s → NO_CONTENT + no content" % up,
         rr["terminal"] == "NO_CONTENT" and rr["no_content_persisted"] is True and rr["access_ready"] is False)
oc = P.build(req(upstream_transcript_decision="NO_TRANSCRIPT"), SPEC, inject=["persist_when_no_content"])
case("K6 inject persist_when_no_content → over_capture>0", oc["violations"]["over_capture"] > 0)
case("K6 inject persist_when_no_content → kapı ELER", gate(oc) is False)

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
case("K9 kanıt upstream/state_in/state_out/span_count/masked_count taşır",
     all(k in ev for k in ("upstream_transcript_decision", "redaction_state_in", "redaction_state_out", "pii_span_count", "masked_count")))
case("K9 missing_evidence=0", P.build(req(), SPEC)["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result/span_count/tenant taşır",
     au["result"] == "REDACTED" and au["pii_span_count"] == 2 and au["tenant_id"] == "t-acme")
na = P.build(req(), SPEC, inject=["no_audit"])
case("K10 inject no_audit → missing_audit>0", na["violations"]["missing_audit"] > 0)
case("K10 inject no_audit → audit None", na["audit"] is None)

# ── K11 audit ham PII taşımaz ────────────────────────────────────────────────
case("K11 audit ham PII değeri/transkript-metni yok",
     all(k not in json.dumps(au) for k in ("customer_phone_value", "card_pan_value", "otp_code_value", "transcript_text", "raw_audio")))

# ── K12 sır/PII yok + tenant izolasyonu ──────────────────────────────────────
ct = P.build(req(), SPEC, inject=["cross_tenant"])
case("K12 inject cross_tenant → cross_tenant>0 + BLOCK", ct["violations"]["cross_tenant"] > 0 and ct["terminal"] == "BLOCK")
bm = P.build(req(bind_tenant="t-other"), SPEC)
case("K12 bind mismatch → cross_tenant>0 + kapı ELER", bm["violations"]["cross_tenant"] > 0 and gate(bm) is False)
case("K12 leak: ham uzun rakam (kart/telefon) yakalanır", len(P.scan_leaks('{"x": "4111111111111111"}')) > 0)
case("K12 leak: kategori/enum/maskeli-token temiz", P.scan_leaks('{"category": "phone", "masked_token": "[PHONE]"}') == [])

# ── secret kategori devri (FR-REC-005 → 11.5) ────────────────────────────────
sd = P.build(req(segments=[seg(1, "caller", [{"category": "card_pan", "start": 3, "length": 16}])]), SPEC)
case("11.5 devir: card_pan maskelendi + delegated_to=11.5",
     sd["terminal"] == "REDACTED" and sd["directives"][0]["delegated_to"] == "11.5")

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
