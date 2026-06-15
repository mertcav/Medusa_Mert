#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.2 — Do-not-call / suppression DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (10.2.1 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import dnc_suppression_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def supp(**kw):
    base = {"opt_out": None, "tenant_dnc": False,
            "national_registry": {"status": "not_listed", "registry": "IYS"},
            "campaign_suppression": False, "global_suppression": False}
    base.update(kw)
    return base


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "campaign_id": "camp-b", "contact_key": "ck-b", "suppression_key": "sk-b",
        "country": "TR", "call_channel": "voice", "campaign_category": "sales",
        "call_time": "2026-06-15T10:00:00", "suppression": supp(),
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: ALLOW|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 temiz contact → ALLOW", P.build(req(), SPEC)["terminal"] == "ALLOW")

# ── K2 opt-out anında (FR-OUT-006 çekirdek) ───────────────────────────────────
case("K2 geçmiş opt-out → BLOCK opt_out",
     P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all"})), SPEC)["block_reason"] == "opt_out")
case("K2 anında: effective==call_time → BLOCK",
     P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T10:00:00", "scope": "all"})), SPEC)["terminal"] == "BLOCK")
case("K2 gelecek opt-out → henüz yürürlükte değil ALLOW",
     P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-16T10:00:00", "scope": "all"})), SPEC)["terminal"] == "ALLOW")
case("K2 inject ignore_optout → optout_not_applied>0",
     P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all"})), SPEC, inject=["ignore_optout"])["violations"]["optout_not_applied"] > 0)
case("K2 inject stale_optout → optout_not_applied>0",
     P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:59:00", "scope": "all"})), SPEC, inject=["stale_optout"])["violations"]["optout_not_applied"] > 0)

# ── K3 ulusal registry gerçek zamanlı ─────────────────────────────────────────
case("K3 listed → BLOCK national_registry",
     P.build(req(suppression=supp(national_registry={"status": "listed", "registry": "IYS"})), SPEC)["block_reason"] == "national_registry")
case("K3 inject → national_leak>0",
     P.build(req(suppression=supp(national_registry={"status": "listed", "registry": "IYS"})), SPEC, inject=["ignore_national_registry"])["violations"]["national_leak"] > 0)

# ── K4 tenant DNC ─────────────────────────────────────────────────────────────
case("K4 tenant_dnc → BLOCK tenant_dnc", P.build(req(suppression=supp(tenant_dnc=True)), SPEC)["block_reason"] == "tenant_dnc")
case("K4 inject → tenant_dnc_leak>0",
     P.build(req(suppression=supp(tenant_dnc=True)), SPEC, inject=["ignore_tenant_dnc"])["violations"]["tenant_dnc_leak"] > 0)

# ── K5 kampanya suppression ───────────────────────────────────────────────────
case("K5 campaign → BLOCK campaign_suppression", P.build(req(suppression=supp(campaign_suppression=True)), SPEC)["block_reason"] == "campaign_suppression")
case("K5 inject → campaign_leak>0",
     P.build(req(suppression=supp(campaign_suppression=True)), SPEC, inject=["ignore_campaign_suppression"])["violations"]["campaign_leak"] > 0)

# ── K6 global suppression ─────────────────────────────────────────────────────
case("K6 global → BLOCK global_suppression", P.build(req(suppression=supp(global_suppression=True)), SPEC)["block_reason"] == "global_suppression")
case("K6 inject → global_leak>0",
     P.build(req(suppression=supp(global_suppression=True)), SPEC, inject=["ignore_global_suppression"])["violations"]["global_leak"] > 0)

# ── K7 fail-closed zorunlu kaynak ─────────────────────────────────────────────
case("K7 TR required+unavailable → BLOCK registry_unavailable",
     P.build(req(suppression=supp(national_registry={"status": "unavailable", "registry": "IYS"})), SPEC)["block_reason"] == "registry_unavailable")
case("K7 EU zorunlu değil+unavailable → ALLOW",
     P.build(req(country="EU", profile_id="PROFILE-EU", suppression=supp(national_registry={"status": "unavailable", "registry": "none"})), SPEC)["terminal"] == "ALLOW")
case("K7 inject failopen → failopen>0",
     P.build(req(suppression=supp(national_registry={"status": "unavailable", "registry": "IYS"})), SPEC, inject=["failopen_registry"])["violations"]["failopen"] > 0)

# ── K8 fail-closed / ATLANAMAZ / %100 bloklama (çekirdek) ──────────────────────
case("K8 suppressed → BLOCK (çağrı başlatılmaz)", P.build(req(suppression=supp(tenant_dnc=True)), SPEC)["terminal"] == "BLOCK")
sk = P.build(req(suppression=supp(tenant_dnc=True)), SPEC, inject=["skip_dnc"])
case("K8 bypass → dnc_skip>0", sk["violations"]["dnc_skip"] > 0)
case("K8 bypass → kapı ELER", gate(sk) is False)
case("K8 BLOCK doğru reddetme → kapı GEÇER", gate(P.build(req(suppression=supp(tenant_dnc=True)), SPEC)) is True)

# ── block_precedence ──────────────────────────────────────────────────────────
multi = P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all"},
                                     national_registry={"status": "listed", "registry": "IYS"}, tenant_dnc=True)), SPEC)
case("precedence: opt_out önce gelir", multi["block_reason"] == "opt_out")

# ── K9 kanıt ──────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 beş kaynak taşır", set(ev["sources"].keys()) == set(P.SOURCES))
case("K9 profil+registry+required taşır",
     ev["resolved_profile"] == "PROFILE-TR" and ev["registry"] == "IYS" and "national_registry" in ev["required_sources"])

# ── K10 audit ──────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result+country+tenant taşır",
     au["result"] == "ALLOW" and au["country"] == "TR" and au["tenant_id"] == "t-acme")
case("K10 inject no_audit → missing_audit>0", P.build(req(), SPEC, inject=["no_audit"])["violations"]["missing_audit"] > 0)

# ── K11 kardinalite/PII (audit ham PII yok) ───────────────────────────────────
import json as _j  # noqa: E402
au_txt = _j.dumps(au)
case("K11 audit ham telefon/ad yok", "customer_phone_value" not in au_txt and "customer_name" not in au_txt)
case("K11 audit metni sızıntısız", P.scan_leaks(au_txt) == [])
case("K11 suppression_key opak (sk-)", str(au["suppression_key"]).startswith("sk-"))

# ── K12 tenant izolasyonu + sır/PII ───────────────────────────────────────────
case("K12 cross_tenant inject → cross_tenant>0", P.build(req(), SPEC, inject=["cross_tenant"])["violations"]["cross_tenant"] > 0)
case("K12 bind mismatch → cross_tenant>0", P.build(req(bind_tenant="t-x"), SPEC)["violations"]["cross_tenant"] > 0)
foreign = req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": "all", "tenant_id": "t-foreign"}))
case("K12 yabancı-tenant suppression → cross_tenant>0", P.build(foreign, SPEC)["violations"]["cross_tenant"] > 0)

# ── dnc_ok köprüsü (10.2.1 consent AND girdisi) ───────────────────────────────
case("dnc_ok ALLOW→true", P.build(req(), SPEC)["dnc_ok"] is True)
case("dnc_ok BLOCK→false", P.build(req(suppression=supp(tenant_dnc=True)), SPEC)["dnc_ok"] is False)

# ── kapsamlı opt-out ──────────────────────────────────────────────────────────
case("scoped opt-out voice → BLOCK",
     P.build(req(suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": {"channels": ["voice"], "categories": []}})), SPEC)["terminal"] == "BLOCK")
case("scoped opt-out sms/marketing, voice/support → ALLOW",
     P.build(req(campaign_category="support", suppression=supp(opt_out={"effective_at": "2026-06-15T09:00:00", "scope": {"channels": ["sms"], "categories": ["marketing"]}})), SPEC)["terminal"] == "ALLOW")


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
