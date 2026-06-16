#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 12.1.7 — Maker-checker onay akışı DAVRANIŞ testi (S1–S12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (12.1.6/12.1.4/12.1.1 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import maker_checker_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
MC = P._load(P.MC_MODEL_PATH)
RBAC = P._load(P.RBAC_MODEL_PATH)
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def mk(**kw):
    d = {"actor_ref": "mk-1", "role": "conversation_designer", "authorized": True,
         "tenant_id": "t-acme", "realm": "tenant"}
    d.update(kw); return d


def ap(ref, decision="approve", authorized=True, scope_ok=True, tenant="t-acme", realm="tenant", at=20):
    return {"approver_ref": ref, "decision": decision, "authorized": authorized, "scope_ok": scope_ok,
            "tenant_id": tenant, "realm": realm, "at": at}


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "actor_realm": "tenant", "action": "agent.publish",
        "reason_code": "rc-prod-release", "now": 10, "expires_at": 100,
        "resource": {"subject_ref": "agent-7", "scope": {"brand": ["brand-x"]}},
        "maker": mk(), "approvals": [ap("ck-1")],
    }
    for k, val in kw.items():
        if k in ("resource", "maker") and isinstance(val, dict):
            merged = dict(d[k]); merged.update(val); d[k] = merged
        else:
            d[k] = val
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── S1 determinizm/terminal ──
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("S1: deterministik (aynı girdi→aynı çıktı)", json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True))
case("S1: terminal'e ulaşır", r1["terminal"] in P.TERMINAL and r1["violations"]["stuck_state"] == 0)
case("S1: model_hash deterministik", r1["model_hash"] == r2["model_hash"])

# ── S2 maker yetkisi ──
case("S2: yetkili maker → APPLIED", P.build(req(), SPEC)["terminal"] == "APPLIED")
r = P.build(req(maker=mk(authorized=False)), SPEC)
case("S2: yetkisiz maker → DENIED maker_unauthorized", r["terminal"] == "DENIED" and r["deny_reason"] == "maker_unauthorized")
case("S2: doğru reddetme ihlal değil (committed=false, kapı geçer)", r["committed"] is False and gate(r))
r = P.build(req(maker=mk(authorized=False)), SPEC, inject=["accept_unauthorized_maker"])
case("S2: yetkisiz maker KABUL (degrade) → unauthorized_maker_accepted>0 + kapı ELER",
     r["violations"]["unauthorized_maker_accepted"] > 0 and not gate(r))

# ── S3 GÖREVLER AYRIMI / SoD (ÇEKİRDEK; FR-IAM-005 / SR-IAM-005) ──
r = P.build(req(approvals=[ap("mk-1")]), SPEC)
case("S3: maker kendi talebini onaylar → onayı SAYILMAZ → PENDING (talep eden ≠ onaylayan)",
     r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)
case("S3: committed=false + sod_violation=0 (doğru dışlama) + kapı geçer",
     r["committed"] is False and r["violations"]["sod_violation"] == 0 and gate(r))
r = P.build(req(approvals=[ap("mk-1"), ap("ck-1", at=25)]), SPEC)
case("S3: maker self + farklı checker → maker dışlanır, ck-1 sayılır → APPLIED",
     r["terminal"] == "APPLIED" and r["approver_refs"] == ["ck-1"])
r = P.build(req(approvals=[ap("mk-1")]), SPEC, inject=["self_approval"])
case("S3 ÇEKİRDEK: maker kendi onayı SAYILIR (degrade) → sod_violation>0 + APPLIED (yanlış) + kapı ELER",
     r["violations"]["sod_violation"] > 0 and r["terminal"] == "APPLIED" and not gate(r))

# ── S4 onaylayan yetkisi/kapsamı (12.1.3) ──
r = P.build(req(approvals=[ap("ck-1", authorized=False)]), SPEC)
case("S4: yetkisiz onaylayan → sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)
r = P.build(req(approvals=[ap("ck-1", scope_ok=False)]), SPEC)
case("S4: kapsam-dışı onaylayan (scope_ok=false) → sayılmaz → PENDING", r["valid_approver_count"] == 0)
r = P.build(req(approvals=[ap("ck-1", authorized=False)]), SPEC, inject=["accept_unauthorized_approver"])
case("S4: yetkisiz onayı say (degrade) → unauthorized_approval>0 + APPLIED (yanlış) + kapı ELER",
     r["violations"]["unauthorized_approval"] > 0 and r["terminal"] == "APPLIED" and not gate(r))

# ── S5 ONAYSIZ CANLIYA ÇIKMAZ (ÇEKİRDEK; SR-IAM-005) ──
r = P.build(req(approvals=[]), SPEC)
case("S5: onaysız → PENDING + committed=false (commit YOK)",
     r["terminal"] == "PENDING" and r["committed"] is False and r["pending_reason"] == "insufficient_approvals")
r = P.build(req(approvals=[ap("ck-1", decision="reject")]), SPEC)
case("S5: checker reddi → REJECTED + committed=false", r["terminal"] == "REJECTED" and r["committed"] is False)
r = P.build(req(approvals=[]), SPEC, inject=["apply_without_quorum"])
case("S5 ÇEKİRDEK: quorum dolmadan commit (degrade) → applied_without_quorum>0 + committed (yanlış) + kapı ELER",
     r["violations"]["applied_without_quorum"] > 0 and r["committed"] is True and not gate(r))

# ── S6 time-box / tazelik ──
r = P.build(req(now=200), SPEC)
case("S6: now>expires_at → DENIED expired", r["terminal"] == "DENIED" and r["deny_reason"] == "expired")
r = P.build(req(approvals=[ap("ck-1", at=150)]), SPEC)
case("S6: bayat onay (at>expires_at) sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)
r = P.build(req(now=200, inject=["apply_expired"]), SPEC, inject=["apply_expired"])
case("S6: süresi dolmuş talebi uygula (degrade) → stale_approval_applied>0 + kapı ELER",
     r["violations"]["stale_approval_applied"] > 0 and not gate(r))

# ── S7 tenant izolasyonu (FR-TEN-002) ──
r = P.build(req(maker=mk(tenant_id="t-other")), SPEC)
case("S7: maker başka tenant → DENIED cross_tenant", r["deny_reason"] == "cross_tenant")
case("S7: cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))
r = P.build(req(approvals=[ap("ck-x", tenant="t-other")]), SPEC)
case("S7: başka tenant onaylayan → sayılmaz → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 0)
r = P.build(req(maker=mk(tenant_id="t-other")), SPEC, inject=["cross_tenant"])
case("S7: izolasyon atla (degrade) → cross_tenant>0 + kapı ELER", r["violations"]["cross_tenant"] > 0 and not gate(r))

# ── S8 quorum bütünlüğü (distinct) ──
r = P.build(req(action="compliance_profile.update", approvals=[ap("ck-1"), ap("ck-2", at=25)]), SPEC)
case("S8: quorum=2 iki distinct onay → APPLIED", r["terminal"] == "APPLIED" and r["quorum_required"] == 2)
r = P.build(req(action="compliance_profile.update", approvals=[ap("ck-1"), ap("ck-1", at=25)]), SPEC)
case("S8: quorum=2 aynı checker iki kez → tek sayılır → PENDING", r["terminal"] == "PENDING" and r["valid_approver_count"] == 1)
r = P.build(req(action="compliance_profile.update", approvals=[ap("ck-1"), ap("ck-1", at=25)]),
            SPEC, inject=["duplicate_approver_quorum"])
case("S8: duplicate'i say (degrade) → quorum_tampered>0 + APPLIED (yanlış) + kapı ELER",
     r["violations"]["quorum_tampered"] > 0 and r["terminal"] == "APPLIED" and not gate(r))

# ── zorunlu gerekçe + katalog + malformed ──
case("reason yok → DENIED reason_code_missing", P.build(req(reason_code=None), SPEC)["deny_reason"] == "reason_code_missing")
r = P.build(req(reason_code=None), SPEC, inject=["reason_bypass"])
case("reason-bypass (degrade) → reason_bypassed>0 + kapı ELER", r["violations"]["reason_bypassed"] > 0 and not gate(r))
case("katalog-dışı aksiyon → DENIED unsupported_action", P.build(req(action="profile.view"), SPEC)["deny_reason"] == "unsupported_action")
case("malformed (maker actor_ref yok) → DENIED", P.build(req(maker=mk(actor_ref=None)), SPEC)["deny_reason"] == "malformed_request")
case("malformed (now yok) → DENIED", P.build(req(now=None), SPEC)["deny_reason"] == "malformed_request")

# ── S9 kanıt (ham token/PII yok) ──
r = P.build(req(), SPEC)
case("S9: kanıt request+maker_ref+reason_code+model_hash taşır",
     all(k in r["evidence"] for k in ("request_id", "maker_ref", "reason_code", "model_hash")))
case("S9: ham e-posta/token alanı yok",
     all(k not in json.dumps(r) for k in ("email_value", "token_value", "bearer_value", "customer_name_value")))
case("S9: missing_evidence=0", r["violations"]["missing_evidence"] == 0)

# ── S10 model bütünlük manifesti ──
r = P.build(req(), SPEC, inject=["model_tamper"])
case("S10: model tahrif → model_tampered>0 + kapı ELER", r["violations"]["model_tampered"] > 0 and not gate(r))

# ── S11/S12 gizlilik + sızıntı ──
case("S11/S12: actor+aksiyon+rol+reason temiz",
     P.scan_leaks('{"maker_ref":"mk-1","action":"agent.publish","role":"conversation_designer","reason_code":"rc-prod-release"}') == [])
case("S12: e-posta yakalanır", len(P.scan_leaks('{"x":"jdoe@acme.co"}')) > 0)
case("S12: jwt blob yakalanır", len(P.scan_leaks('{"t":"eyJhbGciOiJ.eyJzdWIiOmF.abcdef"}')) > 0)

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior test: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
