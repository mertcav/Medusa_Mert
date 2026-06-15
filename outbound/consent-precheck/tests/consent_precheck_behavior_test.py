#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.1 — Consent Engine ön-kontrol DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (10.1.8 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import consent_precheck_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "campaign_id": "camp-b", "contact_key": "ck-b",
        "subject_type": "individual", "country": "TR",
        "call_purpose": "sales", "campaign_category": "sales", "call_time": "2026-06-15T10:00:00",
        "consent": {"source": "IYS", "granted_at": "2025-06-15T10:00:00",
                    "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]},
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

# ── K2 amaç ──────────────────────────────────────────────────────────────────
case("K2 doğru amaç → ALLOW", P.build(req(), SPEC)["terminal"] == "ALLOW")
case("K2 yanlış amaç → BLOCK purpose_mismatch",
     P.build(req(call_purpose="marketing"), SPEC)["block_reason"] == "purpose_mismatch")
case("K2 inject → purpose_mismatch_allowed>0",
     P.build(req(call_purpose="marketing"), SPEC, inject=["accept_wrong_purpose"])["violations"]["purpose_mismatch_allowed"] > 0)

# ── K3 ülke ──────────────────────────────────────────────────────────────────
case("K3 TR → opt_in çözülür", P.build(req(), SPEC)["consent_model"] == "opt_in")
case("K3 bilinmeyen ülke → BLOCK unknown_country",
     P.build(req(country="ZZ"), SPEC)["block_reason"] == "unknown_country")
case("K3 inject → unknown_country_allowed>0",
     P.build(req(country="ZZ"), SPEC, inject=["accept_unknown_country"])["violations"]["unknown_country_allowed"] > 0)

# ── K4 birey/şirket (B2B) ─────────────────────────────────────────────────────
case("K4 UK company → b2b_exempt ALLOW",
     P.build(req(country="UK", subject_type="company", consent=None), SPEC)["basis"] == "b2b_exempt")
case("K4 TR company → rıza gerekli (exemption=false)",
     P.build(req(country="TR", subject_type="company", consent=None), SPEC)["consent_required"] is True)
case("K4 inject → b2b_misexemption>0",
     P.build(req(consent=None), SPEC, inject=["b2b_misexempt"])["violations"]["b2b_misexemption"] > 0)

# ── K5 kaynak ──────────────────────────────────────────────────────────────────
bad_src = req(consent={"source": "scraped_list", "granted_at": "2025-06-15T10:00:00",
                       "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]})
case("K5 tanınmayan kaynak → BLOCK invalid_source", P.build(bad_src, SPEC)["block_reason"] == "invalid_source")
case("K5 inject → invalid_source_allowed>0",
     P.build(bad_src, SPEC, inject=["accept_unknown_source"])["violations"]["invalid_source_allowed"] > 0)

# ── K6 tarih ──────────────────────────────────────────────────────────────────
exp = req(consent={"source": "IYS", "granted_at": "2020-01-01T10:00:00",
                   "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]})
fut = req(consent={"source": "IYS", "granted_at": "2030-01-01T10:00:00",
                   "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]})
case("K6 süresi dolmuş → BLOCK expired", P.build(exp, SPEC)["block_reason"] == "expired_or_invalid_date")
case("K6 gelecek-tarihli → BLOCK expired", P.build(fut, SPEC)["block_reason"] == "expired_or_invalid_date")
case("K6 inject → expired_allowed>0",
     P.build(exp, SPEC, inject=["accept_expired"])["violations"]["expired_allowed"] > 0)

# ── K7 kapsam ──────────────────────────────────────────────────────────────────
oos = req(consent={"source": "IYS", "granted_at": "2025-06-15T10:00:00",
                   "purposes": ["sales"], "channels": ["sms"], "categories": ["sales"]})
case("K7 kanal voice değil → BLOCK out_of_scope", P.build(oos, SPEC)["block_reason"] == "out_of_scope")
oos2 = req(consent={"source": "IYS", "granted_at": "2025-06-15T10:00:00",
                    "purposes": ["sales"], "channels": ["voice"], "categories": ["billing"]})
case("K7 kategori uyuşmaz → BLOCK out_of_scope", P.build(oos2, SPEC)["block_reason"] == "out_of_scope")
case("K7 inject → out_of_scope_allowed>0",
     P.build(oos, SPEC, inject=["accept_out_of_scope"])["violations"]["out_of_scope_allowed"] > 0)

# ── K8 fail-closed / ATLANAMAZ (çekirdek) ─────────────────────────────────────
case("K8 rıza yok → BLOCK (çağrı başlatılmaz)", P.build(req(consent=None), SPEC)["terminal"] == "BLOCK")
sk = P.build(req(consent=None), SPEC, inject=["skip_precheck"])
case("K8 bypass → consent_skip>0", sk["violations"]["consent_skip"] > 0)
case("K8 bypass → kapı ELER", gate(sk) is False)
case("K8 BLOCK doğru reddetme → kapı GEÇER", gate(P.build(req(consent=None), SPEC)) is True)

# ── K9 kanıt ──────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 altı boyut taşır", set(ev["dimensions"].keys()) == set(P.DIMENSIONS))
case("K9 profil+model+consent_required taşır",
     ev["resolved_profile"] == "PROFILE-TR" and ev["consent_model"] == "opt_in" and ev["consent_required"] is True)

# ── K10 audit ──────────────────────────────────────────────────────────────────
au = P.build(req(), SPEC)["audit"]
case("K10 audit result+country+tenant taşır",
     au["result"] == "ALLOW" and au["country"] == "TR" and au["tenant_id"] == "t-acme")
case("K10 inject no_audit → missing_audit>0",
     P.build(req(), SPEC, inject=["no_audit"])["violations"]["missing_audit"] > 0)

# ── K11 kardinalite/PII (audit ham PII yok) ───────────────────────────────────
import json as _j  # noqa: E402
au_txt = _j.dumps(au)
case("K11 audit ham telefon/ad yok",
     "customer_phone_value" not in au_txt and "customer_name" not in au_txt)
case("K11 audit metni sızıntısız", P.scan_leaks(au_txt) == [])

# ── K12 tenant izolasyonu + sır/PII ───────────────────────────────────────────
case("K12 cross_tenant inject → cross_tenant>0",
     P.build(req(), SPEC, inject=["cross_tenant"])["violations"]["cross_tenant"] > 0)
case("K12 bind mismatch → cross_tenant>0",
     P.build(req(bind_tenant="t-x"), SPEC)["violations"]["cross_tenant"] > 0)
foreign = req(consent={"source": "IYS", "granted_at": "2025-06-15T10:00:00", "tenant_id": "t-foreign",
                       "purposes": ["sales"], "channels": ["voice"], "categories": ["sales"]})
case("K12 yabancı-tenant rıza → cross_tenant>0", P.build(foreign, SPEC)["violations"]["cross_tenant"] > 0)

# ── consent_ok köprüsü (10.2.2 DNC AND girdisi) ───────────────────────────────
case("consent_ok ALLOW→true", P.build(req(), SPEC)["consent_ok"] is True)
case("consent_ok BLOCK→false", P.build(req(consent=None), SPEC)["consent_ok"] is False)

# ── opt_out / soft_basis dayanakları ──────────────────────────────────────────
case("opt_out rejimi → ALLOW opt_out",
     P.build(req(country="US", profile_id="PROFILE-US-OPTOUT", consent=None), SPEC)["basis"] == "opt_out")
case("soft_basis → ALLOW soft_basis",
     P.build(req(country="UK", consent={"soft_basis": True, "categories": ["sales"]}), SPEC)["basis"] == "soft_basis")


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
