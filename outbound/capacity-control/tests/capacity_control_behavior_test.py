#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.4 — Silent/abandoned call önleme (kapasite kontrolü) DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (10.2.3 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import capacity_control_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan: TR sağlıklı snapshot → free=6, abandon=1%, over-dial içinde, trunk boş → ALLOW
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "campaign_id": "camp-b", "contact_key": "ck-b",
        "country": "TR", "call_channel": "voice", "campaign_category": "sales",
        "total_handlers": 10, "active_calls": 4, "in_flight_dials": 6,
        "trunk_channels_active": 8, "trunk_capacity": 30,
        "rolling_connected": 200, "rolling_abandoned": 2,
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
case("K1 sağlıklı kapasite → ALLOW", P.build(req(), SPEC)["terminal"] == "ALLOW")

# ── K2 doğru kapasite muhasebesi ÇEKİRDEK (FR-TEL-015) ────────────────────────
case("K2 free = total − active (6)", P.build(req(), SPEC)["free_handlers"] == 6)
stale = P.build(req(total_handlers=10, active_calls=0, in_flight_dials=30), SPEC, inject=["stale_capacity"])
case("K2 inject stale_capacity → capacity_error>0", stale["violations"]["capacity_error"] > 0)
case("K2 inject stale_capacity → kapı ELER", gate(stale) is False)
case("K2 stale over-dial under-count → yanlış ALLOW", stale["terminal"] == "ALLOW")

# ── K3 rezerve headroom (sıfır kapasite = silent call) ────────────────────────
case("K3 free=0 → BLOCK no_capacity",
     P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0), SPEC)["block_reason"] == "no_capacity")
case("K3 free=1 (==reserve_min) → ALLOW",
     P.build(req(total_handlers=5, active_calls=4, in_flight_dials=2), SPEC)["terminal"] == "ALLOW")
ih = P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0), SPEC, inject=["ignore_headroom"])
case("K3 inject ignore_headroom → no_capacity_leak>0", ih["violations"]["no_capacity_leak"] > 0)
case("K3 inject ignore_headroom → sıfır kapasiteye yanlış ALLOW", ih["terminal"] == "ALLOW")
case("K3 inject ignore_headroom → kapı ELER", gate(ih) is False)

# ── K4 abandoned oranı eşiği (SR-TEL-015 kabul) ───────────────────────────────
case("K4 4% ≥ 3% → BLOCK abandon_rate_exceeded",
     P.build(req(rolling_connected=100, rolling_abandoned=4, active_calls=2), SPEC)["block_reason"] == "abandon_rate_exceeded")
case("K4 tam 3% (eşik) → BLOCK",
     P.build(req(rolling_connected=100, rolling_abandoned=3, active_calls=2), SPEC)["terminal"] == "BLOCK")
case("K4 2% < 3% → ALLOW",
     P.build(req(rolling_connected=100, rolling_abandoned=2, active_calls=2), SPEC)["terminal"] == "ALLOW")
case("K4 predicted_abandon_rate 5% → BLOCK",
     P.build(req(predicted_abandon_rate=0.05, active_calls=2), SPEC)["block_reason"] == "abandon_rate_exceeded")
case("K4 inject ignore_abandon_rate → abandon_rate_leak>0",
     P.build(req(rolling_connected=100, rolling_abandoned=4, active_calls=2), SPEC, inject=["ignore_abandon_rate"])["violations"]["abandon_rate_leak"] > 0)

# ── K5 over-dial cap (predictive pacing) ──────────────────────────────────────
case("K5 in_flight 30 > free×ratio 30 → BLOCK overdial_cap",
     P.build(req(total_handlers=10, active_calls=0, in_flight_dials=30), SPEC)["block_reason"] == "overdial_cap")
case("K5 in_flight 29 → 30≤30 → ALLOW",
     P.build(req(total_handlers=10, active_calls=0, in_flight_dials=29), SPEC)["terminal"] == "ALLOW")
case("K5 inject ignore_overdial → overdial_leak>0",
     P.build(req(total_handlers=10, active_calls=0, in_flight_dials=30), SPEC, inject=["ignore_overdial"])["violations"]["overdial_leak"] > 0)

# ── K6 trunk kanalı ───────────────────────────────────────────────────────────
case("K6 20/20 dolu → BLOCK trunk_exhausted",
     P.build(req(trunk_channels_active=20, trunk_capacity=20), SPEC)["block_reason"] == "trunk_exhausted")
case("K6 inject ignore_trunk → trunk_leak>0",
     P.build(req(trunk_channels_active=20, trunk_capacity=20), SPEC, inject=["ignore_trunk"])["violations"]["trunk_leak"] > 0)

# ── K7 fail-closed bilinmeyen profil ──────────────────────────────────────────
case("K7 bilinmeyen ülke → BLOCK unknown_profile",
     P.build(req(country="ZZ"), SPEC)["block_reason"] == "unknown_profile")
case("K7 inject failopen_profile → failopen>0",
     P.build(req(country="ZZ"), SPEC, inject=["failopen_profile"])["violations"]["failopen"] > 0)
case("K7 inject failopen_profile → kapı ELER",
     gate(P.build(req(country="ZZ"), SPEC, inject=["failopen_profile"])) is False)

# ── regülatör profil farkı: aynı oran, farklı profil → farklı sonuç ───────────
eu = P.build(req(country="EU", profile_id="PROFILE-EU", rolling_connected=200, rolling_abandoned=5, active_calls=2), SPEC)
tr = P.build(req(rolling_connected=200, rolling_abandoned=5, active_calls=2), SPEC)
case("profil farkı: 2.5% EU eşik(2%) → BLOCK", eu["block_reason"] == "abandon_rate_exceeded")
case("profil farkı: 2.5% TR eşik(3%) → ALLOW", tr["terminal"] == "ALLOW")

# ── block_precedence ──────────────────────────────────────────────────────────
case("precedence: abandon, no_capacity'den önce gelir",
     P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0, rolling_connected=100, rolling_abandoned=5), SPEC)["block_reason"] == "abandon_rate_exceeded")

# ── K8 fail-closed / ATLANAMAZ (çekirdek) ──────────────────────────────────────
case("K8 kapasitesiz → BLOCK (çağrı başlatılmaz)",
     P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0), SPEC)["terminal"] == "BLOCK")
sk = P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0), SPEC, inject=["skip_capacity"])
case("K8 bypass → capacity_skip>0", sk["violations"]["capacity_skip"] > 0)
case("K8 bypass → kapı ELER", gate(sk) is False)
case("K8 BLOCK doğru reddetme → kapı GEÇER", gate(P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0), SPEC)) is True)

# ── K9 kanıt ──────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 dört kural taşır", set(ev["rules"].keys()) == set(P.RULES))
case("K9 profil+free+abandon taşır",
     ev["resolved_profile"] == "PROFILE-TR" and ev["free_handlers"] == 6 and ev["abandon_rate"] is not None)

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

# ── K12 tenant izolasyonu + sır/PII ───────────────────────────────────────────
case("K12 cross_tenant inject → cross_tenant>0", P.build(req(), SPEC, inject=["cross_tenant"])["violations"]["cross_tenant"] > 0)
case("K12 bind mismatch → cross_tenant>0", P.build(req(bind_tenant="t-x"), SPEC)["violations"]["cross_tenant"] > 0)

# ── capacity_ok köprüsü (10.2.1/10.2.2/10.2.3 AND girdisi) ─────────────────────
case("capacity_ok ALLOW→true", P.build(req(), SPEC)["capacity_ok"] is True)
case("capacity_ok BLOCK→false", P.build(req(total_handlers=5, active_calls=5, in_flight_dials=0), SPEC)["capacity_ok"] is False)


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
