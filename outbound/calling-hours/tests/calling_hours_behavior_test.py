#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.3 — Ülke/bölge arama saati DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (10.2.2 behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import calling_hours_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan: TR (UTC+180), 2026-06-15 Pazartesi, call_time 08:00 UTC → yerel 11:00 pencere içi ALLOW
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "campaign_id": "camp-b", "contact_key": "ck-b",
        "country": "TR", "call_channel": "voice", "campaign_category": "sales",
        "call_time": "2026-06-15T08:00:00+00:00",
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
case("K1 pencere içi → ALLOW", P.build(req(), SPEC)["terminal"] == "ALLOW")

# ── K2 yerel saat ÇEKİRDEK (FR-OUT-004) ───────────────────────────────────────
case("K2 UTC17:00→TR20:00 yerel pencere dışı → BLOCK",
     P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC)["terminal"] == "BLOCK")
case("K2 yerel saat hesaplanır (11:00)",
     P.build(req(), SPEC)["local_time"].endswith("11:00:00"))
st = P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC, inject=["use_server_time"])
case("K2 inject use_server_time → tz_error>0", st["violations"]["tz_error"] > 0)
case("K2 inject use_server_time → kapı ELER", gate(st) is False)
case("K2 server-time yanlış ALLOW (UTC 17:00 pencere içi)", st["terminal"] == "ALLOW")

# ── K3 günlük pencere ─────────────────────────────────────────────────────────
case("K3 yerel 20:00 → BLOCK outside_window",
     P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC)["block_reason"] == "outside_window")
case("K3 start 09:00 dahil → ALLOW", P.build(req(call_time="2026-06-15T06:00:00+00:00"), SPEC)["terminal"] == "ALLOW")
case("K3 end 18:00 hariç → BLOCK", P.build(req(call_time="2026-06-15T15:00:00+00:00"), SPEC)["terminal"] == "BLOCK")
case("K3 inject ignore_window → window_leak>0",
     P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC, inject=["ignore_window"])["violations"]["window_leak"] > 0)

# ── K4 haftanın günü ──────────────────────────────────────────────────────────
case("K4 TR Pazar → BLOCK weekday_blocked",
     P.build(req(call_time="2026-06-21T08:00:00+00:00"), SPEC)["block_reason"] == "weekday_blocked")
case("K4 inject ignore_weekday → weekday_leak>0",
     P.build(req(call_time="2026-06-21T08:00:00+00:00"), SPEC, inject=["ignore_weekday"])["violations"]["weekday_leak"] > 0)

# ── K5 blackout/tatil ─────────────────────────────────────────────────────────
case("K5 TR 2026-05-01 → BLOCK blackout_date",
     P.build(req(call_time="2026-05-01T08:00:00+00:00"), SPEC)["block_reason"] == "blackout_date")
case("K5 inject ignore_blackout → blackout_leak>0",
     P.build(req(call_time="2026-05-01T08:00:00+00:00"), SPEC, inject=["ignore_blackout"])["violations"]["blackout_leak"] > 0)

# ── K6 müşteri penceresi (FR-TEL-013 müşteri bazında) ─────────────────────────
case("K6 müşteri 13–14, yerel 11:00 → BLOCK customer_window",
     P.build(req(customer_window={"start": "13:00", "end": "14:00"}), SPEC)["block_reason"] == "customer_window")
case("K6 müşteri 13–14, yerel 13:30 → ALLOW",
     P.build(req(call_time="2026-06-15T10:30:00+00:00", customer_window={"start": "13:00", "end": "14:00"}), SPEC)["terminal"] == "ALLOW")
case("K6 müşteri gün kısıtı (yalnız Sal/Çar), Pzt çağrı → BLOCK customer_window",
     P.build(req(customer_window={"start": "09:00", "end": "18:00", "weekdays": [1, 2]}), SPEC)["block_reason"] == "customer_window")
case("K6 inject ignore_customer_window → customer_window_leak>0",
     P.build(req(customer_window={"start": "13:00", "end": "14:00"}), SPEC, inject=["ignore_customer_window"])["violations"]["customer_window_leak"] > 0)

# ── K7 fail-closed bilinmeyen bölge ───────────────────────────────────────────
case("K7 US bölgesiz → BLOCK unknown_region",
     P.build(req(country="US", profile_id="PROFILE-US-CALL", call_time="2026-06-15T18:00:00+00:00"), SPEC)["block_reason"] == "unknown_region")
case("K7 bilinmeyen ülke → BLOCK unknown_region",
     P.build(req(country="ZZ"), SPEC)["block_reason"] == "unknown_region")
case("K7 US-NY çözümlü → ALLOW (13:00 EST)",
     P.build(req(country="US", profile_id="PROFILE-US-CALL", region="US-NY", call_time="2026-06-15T18:00:00+00:00"), SPEC)["terminal"] == "ALLOW")
case("K7 inject failopen_region → failopen>0",
     P.build(req(country="US", profile_id="PROFILE-US-CALL", call_time="2026-06-15T18:00:00+00:00"), SPEC, inject=["failopen_region"])["violations"]["failopen"] > 0)

# ── FR-OUT-004 bölge farkı: AYNI instant, farklı bölge → farklı sonuç ──────────
ny = P.build(req(country="US", profile_id="PROFILE-US-CALL", region="US-NY", call_time="2026-06-15T13:00:00+00:00"), SPEC)
ca = P.build(req(country="US", profile_id="PROFILE-US-CALL", region="US-CA", call_time="2026-06-15T13:00:00+00:00"), SPEC)
case("bölge farkı: US-NY 08:00 ALLOW", ny["terminal"] == "ALLOW")
case("bölge farkı: US-CA 05:00 BLOCK", ca["terminal"] == "BLOCK")

# ── K8 fail-closed / ATLANAMAZ (çekirdek) ──────────────────────────────────────
case("K8 saat-dışı → BLOCK (çağrı başlatılmaz)", P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC)["terminal"] == "BLOCK")
sk = P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC, inject=["skip_hours"])
case("K8 bypass → hours_skip>0", sk["violations"]["hours_skip"] > 0)
case("K8 bypass → kapı ELER", gate(sk) is False)
case("K8 BLOCK doğru reddetme → kapı GEÇER", gate(P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC)) is True)

# ── block_precedence ──────────────────────────────────────────────────────────
# 2026-05-01 blackout + (Cuma izinli) — blackout önce gelir
case("precedence: blackout önce gelir", P.build(req(call_time="2026-05-01T08:00:00+00:00"), SPEC)["block_reason"] == "blackout_date")

# ── K9 kanıt ──────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)["evidence"]
case("K9 dört kural taşır", set(ev["rules"].keys()) == set(P.RULES))
case("K9 profil+offset+yerel saat taşır",
     ev["resolved_profile"] == "PROFILE-TR" and ev["utc_offset_minutes"] == 180 and ev["local_time"] is not None)

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
foreign = req(customer_window={"start": "09:00", "end": "18:00", "tenant_id": "t-foreign"})
case("K12 yabancı-tenant müşteri penceresi → cross_tenant>0", P.build(foreign, SPEC)["violations"]["cross_tenant"] > 0)

# ── hours_ok köprüsü (10.2.1/10.2.2 AND girdisi) ──────────────────────────────
case("hours_ok ALLOW→true", P.build(req(), SPEC)["hours_ok"] is True)
case("hours_ok BLOCK→false", P.build(req(call_time="2026-06-15T17:00:00+00:00"), SPEC)["hours_ok"] is False)


npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
