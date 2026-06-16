#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 11.6 — Kayıt/transkript erişim audit'i DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (11.1–11.4 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import access_audit_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan: yetkili tenant qa_analyst maskeli transkript görüntüleme.
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b", "call_id": "call-b",
        "actor_user_id": "u-b", "actor_realm": "tenant", "actor_role": "qa_analyst",
        "resource_type": "transcript", "access_action": "view", "access_mode": "masked",
        "actor_permissions": ["transcript:read", "calls:read"], "ownership": "other",
        "in_region_storage_required": True, "storage_region": "TR", "home_region": "TR",
        "audit_sink_available": True,
    }
    d.update(kw)
    return d


def bg(**kw):
    d = {"grant_id": "bg-b", "maker": "u-a", "checker": "u-c", "reason_code": "INVEST-01",
         "tier": "B", "expires_state": "valid", "scope_tenant": "t-acme", "time_boxed": True}
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


def _mismatch(s, r):
    exp = s.get("expected", {})
    for k in ("terminal", "block_reason", "deny_reason", "authorized", "access_granted",
              "audit_written", "break_glass_id"):
        if k in exp and exp[k] != r.get(k):
            return True
    return False


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: GRANTED|DENIED|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı yetkili → GRANTED", P.build(req(), SPEC)["terminal"] == "GRANTED")

# ── K2 zorunlu erişim audit ÇEKİRDEK (FR-REC-009) ────────────────────────────
h = P.build(req(), SPEC)
case("K2 GRANTED → audit_written", h["access_granted"] and h["audit_written"])
case("K2 audit kaydı result=GRANTED", h["audit"]["result"] == "GRANTED")
sk = P.build(req(), SPEC, inject=["skip_audit"])
case("K2 inject skip_audit → unaudited_access>0", sk["violations"]["unaudited_access"] > 0)
case("K2 inject skip_audit → kapı ELER", gate(sk) is False)
# DENIED de audit üretir (başarısız erişim de denetlenir)
dn = P.build(req(actor_permissions=[]), SPEC)
case("K2 DENIED → audit_written (başarısız erişim de audit'lenir)", dn["audit_written"] is True)
case("K2 access_granted ⇒ audit_written (garanti)", (not h["access_granted"]) or h["audit_written"])

# ── K3 WORM/hash-chain bütünlüğü ÇEKİRDEK (FR-IAM-006, DB §27) ────────────────
case("K3 audit row_hash sha256 (64 hex)", len(h["audit"]["row_hash"]) == 64)
tm = P.build(req(), SPEC, inject=["audit_tamper"])
case("K3 inject audit_tamper → audit_tampered>0", tm["violations"]["audit_tampered"] > 0)
case("K3 inject audit_tamper → kapı ELER", gate(tm) is False)
cb = P.build(req(prev_chain_hash="a" * 64), SPEC, inject=["chain_break"])
case("K3 inject chain_break → chain_break>0", cb["violations"]["chain_break"] > 0)
case("K3 inject chain_break → kapı ELER", gate(cb) is False)
ch = P.build(req(prev_chain_hash="a" * 64), SPEC)
case("K3 sağlıklı zincir: prev_hash bağlı + chain_break=0",
     ch["audit"]["prev_hash"] == "a" * 64 and ch["violations"]["chain_break"] == 0)

# ── K4 yetki kapısı ÇEKİRDEK (FR-REC-008) ────────────────────────────────────
case("K4 yetkili → GRANTED", h["authorized"] and h["terminal"] == "GRANTED")
np_ = P.build(req(actor_permissions=[]), SPEC)
case("K4 yetki yok → DENIED missing_permission", np_["terminal"] == "DENIED" and np_["deny_reason"] == "missing_permission")
ug = P.build(req(actor_permissions=[]), SPEC, inject=["unauthorized_grant"])
case("K4 inject unauthorized_grant → unauthorized_access>0", ug["violations"]["unauthorized_access"] > 0)
case("K4 inject unauthorized_grant → kapı ELER", gate(ug) is False)
os_ = P.build(req(actor_permissions=["transcript:read:own"], ownership="other"), SPEC)
case("K4 :own + sahiplik dışı → DENIED insufficient_scope", os_["deny_reason"] == "insufficient_scope")
case("K4 :own + sahiplik own → GRANTED",
     P.build(req(actor_permissions=["transcript:read:own"], ownership="own"), SPEC)["terminal"] == "GRANTED")
rw = P.build(req(access_mode="raw", actor_permissions=["transcript:read"]), SPEC)
case("K4 raw transkript yükseltilmiş yetki ister → DENIED", rw["terminal"] == "DENIED")

# ── K5 atlanamaz / fail-closed ÇEKİRDEK ──────────────────────────────────────
sd = P.build(req(audit_sink_available=False), SPEC)
case("K5 audit-sink yok → BLOCK no_audit_sink", sd["terminal"] == "BLOCK" and sd["block_reason"] == "no_audit_sink")
case("K5 audit-sink yok → access_granted=false (fail-closed)", sd["access_granted"] is False)
case("K5 audit-sink yok → kapı geçer (meşru fail-closed)", gate(sd) is True)
fo = P.build(req(audit_sink_available=False), SPEC, inject=["failopen_audit"])
case("K5 inject failopen_audit → failopen>0 + unaudited_access>0",
     fo["violations"]["failopen"] > 0 and fo["violations"]["unaudited_access"] > 0)
case("K5 inject failopen_audit → kapı ELER", gate(fo) is False)
# L0 altın kural
gr = P.build(req(actor_realm="platform", actor_permissions=[], break_glass=None), SPEC)
case("K5 L0 altın kural: platform break-glass'sız → DENIED break_glass_required",
     gr["terminal"] == "DENIED" and gr["deny_reason"] == "break_glass_required")

# ── K6 break-glass disiplini (FR-IAM-009/010) ────────────────────────────────
bv = P.build(req(actor_realm="platform", actor_role="platform_sre", actor_permissions=[], break_glass=bg()), SPEC)
case("K6 geçerli break-glass → GRANTED + break_glass_id audit'te",
     bv["terminal"] == "GRANTED" and bv["audit"]["break_glass_id"] == "bg-b")
sa = P.build(req(actor_realm="platform", actor_permissions=[], break_glass=bg()), SPEC, inject=["self_approval"])
case("K6 inject self_approval → break_glass_violation>0 + DENIED",
     sa["violations"]["break_glass_violation"] > 0 and sa["terminal"] == "DENIED")
case("K6 inject self_approval → kapı ELER", gate(sa) is False)
ex = P.build(req(actor_realm="platform", actor_permissions=[], break_glass=bg()), SPEC, inject=["expired_grant"])
case("K6 inject expired_grant → break_glass_violation>0", ex["violations"]["break_glass_violation"] > 0)
case("K6 inject expired_grant → kapı ELER", gate(ex) is False)
st = P.build(req(actor_realm="platform", actor_permissions=[], break_glass=bg()), SPEC, inject=["standing_access"])
case("K6 inject standing_access → break_glass_violation>0", st["violations"]["break_glass_violation"] > 0)
case("K6 inject standing_access → kapı ELER", gate(st) is False)

# ── K7 residency (NFR 10.7) ──────────────────────────────────────────────────
case("K7 served=home(TR) → ihlal yok", P.build(req(served_region="TR"), SPEC)["violations"]["residency_violation"] == 0)
rl = P.build(req(), SPEC, inject=["residency_leak"])
case("K7 inject residency_leak → residency_violation>0", rl["violations"]["residency_violation"] > 0)
case("K7 inject residency_leak → kapı ELER", gate(rl) is False)

# ── K8 ham içerik/PII yok ÇEKİRDEK (BRD §17.7) ───────────────────────────────
case("K8 audit ham içerik/PII değeri taşımaz",
     all(k not in json.dumps(h["audit"]) for k in ("transcript_text", "recording_bytes", "raw_audio", "card_pan_value")))
pl = P.build(req(), SPEC, inject=["pii_leak"])
case("K8 inject pii_leak → pii_leak>0", pl["violations"]["pii_leak"] > 0)
case("K8 inject pii_leak → kapı ELER", gate(pl) is False)

# ── K9 kanıt ─────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 kanıt request taşır", ev["request_id"] == "req-b")
case("K9 kanıt authorized/access_granted/audit_written taşır",
     all(k in ev for k in ("authorized", "access_granted", "audit_written")))
case("K9 missing_evidence=0", P.build(req(), SPEC)["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result/resource/actor/tenant taşır",
     au["result"] == "GRANTED" and au["resource_type"] == "transcript" and au["tenant_id"] == "t-acme")
na = P.build(req(), SPEC, inject=["no_audit"])
case("K10 inject no_audit → missing_audit>0 + audit None", na["violations"]["missing_audit"] > 0 and na["audit"] is None)

# ── K11 audit ham içerik taşımaz ─────────────────────────────────────────────
case("K11 audit ham içerik/transkript-metni/kayıt-byte yok",
     all(k not in json.dumps(au) for k in ("transcript_text", "recording_bytes", "raw_audio", "card_pan_value")))

# ── K12 sır/içerik yok + tenant izolasyonu ───────────────────────────────────
ct = P.build(req(), SPEC, inject=["cross_tenant"])
case("K12 inject cross_tenant → cross_tenant>0 + BLOCK", ct["violations"]["cross_tenant"] > 0 and ct["terminal"] == "BLOCK")
bm = P.build(req(bind_tenant="t-other"), SPEC)
case("K12 bind mismatch → cross_tenant>0 + kapı ELER", bm["violations"]["cross_tenant"] > 0 and gate(bm) is False)
case("K12 leak: ham uzun rakam (kayıt/PII) yakalanır", len(P.scan_leaks('{"x": "4111111111111111"}')) > 0)
case("K12 leak: kimlik/enum/hash temiz", P.scan_leaks('{"resource_type": "transcript", "row_hash": "sha256"}') == [])

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
