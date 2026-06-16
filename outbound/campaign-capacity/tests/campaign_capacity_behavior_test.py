#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.2.6 — Kampanya kapasitesi ≤ agent+trunk (backpressure entegrasyonu) DAVRANIŞ testi (K1–K12).

selftest probe içi gömülü kontrolleri çalıştırır; bu dosya invariant'ları DIŞARIDAN, bağımsız
fixture'larla doğrular (10.2.x behavior deseniyle birebir). Stdlib-only; sunucu gerektirmez.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.dirname(HERE)
sys.path.insert(0, MOD)

import campaign_capacity_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
G = SPEC["gates"]
RESULTS = []


def case(name, cond):
    RESULTS.append((bool(cond), name))


def req(**kw):
    # Varsayılan TR: agent 100−20−10=70, trunk 80−30=50, quota 60−10=50 → min 50 ×0.8 = ceiling 40.
    d = {
        "request_id": "req-b", "tenant_id": "t-acme", "correlation_id": "corr-b",
        "campaign_id": "camp-b", "country": "TR", "channel": "voice", "campaign_category": "sales",
        "target_concurrency": 20, "target_cps": 0.1, "mean_call_seconds": 180,
        "agent_handlers_total": 100, "agent_handlers_active": 20, "reserved_inbound_handlers": 10,
        "trunk_channels_total": 80, "trunk_channels_active": 30,
        "tenant_quota_concurrency": 60, "tenant_concurrency_active": 10,
    }
    d.update(kw)
    return d


def gate(r):
    return P._gate_eval(r, G)[0]


# ── K1 determinizm/terminal ──────────────────────────────────────────────────
r1, r2 = P.build(req(), SPEC), P.build(req(), SPEC)
case("K1 determinizm: aynı girdi→aynı çıktı", r1 == r2)
case("K1 terminal: ADMIT|PACE_DOWN|DEFER|BLOCK", r1["terminal"] in P.TERMINAL)
case("K1 stuck_state=0", r1["violations"]["stuck_state"] == 0)
case("K1 sağlıklı kapasite → ADMIT", P.build(req(), SPEC)["terminal"] == "ADMIT")

# ── K2 doğru kapasite tavanı ÇEKİRDEK (FR-OUT-007) ───────────────────────────
case("K2 ceiling = floor(min(70,50,50)=50 ×0.8) = 40", P.build(req(), SPEC)["ceiling"] == 40)
case("K2 trunk binding: ceiling=8",
     P.build(req(trunk_channels_total=40, trunk_channels_active=30, target_cps=0, mean_call_seconds=0,
                 target_concurrency=20), SPEC)["ceiling"] == 8)
it = P.build(req(trunk_channels_total=40, trunk_channels_active=30, target_cps=0, mean_call_seconds=0,
                 target_concurrency=20), SPEC, inject=["ignore_trunk"])
case("K2 inject ignore_trunk → capacity_error>0", it["violations"]["capacity_error"] > 0)
case("K2 inject ignore_trunk → yanlış yüksek ceiling=40", it["ceiling"] == 40)
case("K2 inject ignore_trunk → kapı ELER", gate(it) is False)
iq = P.build(req(tenant_quota_concurrency=25, tenant_concurrency_active=20, target_cps=0,
                 mean_call_seconds=0, target_concurrency=20), SPEC, inject=["ignore_quota"])
case("K2 inject ignore_quota → capacity_error>0", iq["violations"]["capacity_error"] > 0)

# ── K3 Little sizing ÇEKİRDEK (SAD §20) ──────────────────────────────────────
case("K3 design = ⌈1.0×180⌉ = 180 (> target_concurrency 5)",
     P.build(req(target_concurrency=5, target_cps=1.0, mean_call_seconds=180), SPEC)["design_concurrency"] == 180)
case("K3 design = max(target_concurrency 30, ⌈18⌉) = 30",
     P.build(req(target_concurrency=30, target_cps=0.1, mean_call_seconds=180), SPEC)["design_concurrency"] == 30)
il = P.build(req(target_concurrency=5, target_cps=1.0, mean_call_seconds=180), SPEC, inject=["ignore_little"])
case("K3 inject ignore_little → sizing_error>0", il["violations"]["sizing_error"] > 0)
case("K3 inject ignore_little → under-size design=5", il["design_concurrency"] == 5)
case("K3 inject ignore_little → kapı ELER", gate(il) is False)

# ── K4 no over-subscription ÇEKİRDEK (FR-OUT-007) ────────────────────────────
case("K4 effective ≤ ceiling (ADMIT)", P.build(req(), SPEC)["effective"] <= P.build(req(), SPEC)["ceiling"])
pd = P.build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), SPEC)
case("K4 PACE_DOWN effective=ceiling=40 ≤ ceiling", pd["effective"] == 40 and pd["effective"] <= pd["ceiling"])
oa = P.build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), SPEC, inject=["over_admit"])
case("K4 inject over_admit → over_subscription>0", oa["violations"]["over_subscription"] > 0)
case("K4 inject over_admit → effective>ceiling", oa["effective"] > oa["ceiling"])
case("K4 inject over_admit → kapı ELER", gate(oa) is False)
# K4 her terminalde garanti
for tc in (10, 40, 41, 200):
    rr = P.build(req(target_concurrency=tc, target_cps=0, mean_call_seconds=0), SPEC)
    case("K4 garanti effective ≤ ceiling (design=%d)" % tc, rr["effective"] <= rr["ceiling"])

# ── K5 graceful backpressure ÇEKİRDEK (FR-RES-014) ───────────────────────────
case("K5 PACE_DOWN overflow = design−effective = 60", pd["overflow"] == 60)
df = P.build(req(agent_handlers_total=20, agent_handlers_active=20, reserved_inbound_handlers=0,
                 trunk_channels_total=80, trunk_channels_active=0, tenant_quota_concurrency=60,
                 tenant_concurrency_active=0, target_concurrency=10, target_cps=0, mean_call_seconds=0), SPEC)
case("K5 DEFER ceiling=0 → overflow=design=10 (tümü callback)", df["terminal"] == "DEFER" and df["overflow"] == 10)
ug = P.build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), SPEC, inject=["ungraceful_drop"])
case("K5 inject ungraceful_drop → backpressure_fail>0", ug["violations"]["backpressure_fail"] > 0)
case("K5 inject ungraceful_drop → overflow=0 (sessiz düşüş)", ug["overflow"] == 0)
case("K5 inject ungraceful_drop → kapı ELER", gate(ug) is False)

# ── K6 rezerve inbound korunur ───────────────────────────────────────────────
case("K6 agent_avail = total−active−reserved = 20",
     P.build(req(agent_handlers_total=60, agent_handlers_active=0, reserved_inbound_handlers=40), SPEC)["agent_avail"] == 20)
ir = P.build(req(agent_handlers_total=60, agent_handlers_active=0, reserved_inbound_handlers=40,
                 trunk_channels_total=100, trunk_channels_active=0, tenant_quota_concurrency=100,
                 tenant_concurrency_active=0, target_concurrency=16), SPEC, inject=["ignore_reserve"])
case("K6 inject ignore_reserve → reserve_violation>0", ir["violations"]["reserve_violation"] > 0)
case("K6 inject ignore_reserve → agent_avail=60 (rezerve atlandı)", ir["agent_avail"] == 60)
case("K6 inject ignore_reserve → kapı ELER", gate(ir) is False)

# ── K7 fail-closed bilinmeyen profil ─────────────────────────────────────────
up = P.build(req(country="ZZ"), SPEC)
case("K7 bilinmeyen ülke → BLOCK unknown_profile", up["terminal"] == "BLOCK" and up["block_reason"] == "unknown_profile")
fo = P.build(req(country="ZZ"), SPEC, inject=["failopen_profile"])
case("K7 inject failopen → failopen>0", fo["violations"]["failopen"] > 0)
case("K7 inject failopen → kapı ELER", gate(fo) is False)

# ── K8 fail-closed / ATLANAMAZ ÇEKİRDEK (SR-OUT-007) ─────────────────────────
sk = P.build(req(target_concurrency=100, target_cps=0, mean_call_seconds=0), SPEC, inject=["skip_capacity"])
case("K8 inject skip_capacity → capacity_skip>0", sk["violations"]["capacity_skip"] > 0)
case("K8 inject skip_capacity → ADMIT'e zorlandı (ceiling yok sayıldı)", sk["terminal"] == "ADMIT")
case("K8 inject skip_capacity → effective=design=100", sk["effective"] == 100)
case("K8 inject skip_capacity → kapı ELER", gate(sk) is False)

# ── K9 kanıt ─────────────────────────────────────────────────────────────────
ev = P.build(req(), SPEC)
case("K9 evidence request_id taşır", ev["evidence"]["request_id"] == "req-b")
case("K9 evidence ceiling/design/effective/overflow taşır",
     all(k in ev["evidence"] for k in ("ceiling", "design_concurrency", "effective", "overflow")))
case("K9 missing_evidence=0", ev["violations"]["missing_evidence"] == 0)

# ── K10 audit ────────────────────────────────────────────────────────────────
case("K10 audit result taşır", ev["audit"]["result"] == "ADMIT")
case("K10 audit tenant taşır", ev["audit"]["tenant_id"] == "t-acme")
case("K10 audit ham PII yok", "customer_phone_value" not in json.dumps(ev["audit"])
     and "customer_name" not in json.dumps(ev["audit"]))
na = P.build(req(), SPEC, inject=["no_audit"])
case("K10 inject no_audit → missing_audit>0", na["violations"]["missing_audit"] > 0)
case("K10 inject no_audit → kapı ELER", gate(na) is False)

# ── K11 kardinalite (spec disiplini) ─────────────────────────────────────────
obs = SPEC["observability"]
case("K11 request_id/campaign_id yüksek kard (label değil)",
     "request_id" in obs["high_cardinality_trace_only"] and "campaign_id" not in obs["low_cardinality_labels"])
case("K11 result/country düşük kard (label uygun)",
     "result" in obs["low_cardinality_labels"] and "country" in obs["low_cardinality_labels"])

# ── K12 tenant izolasyonu + sır/PII ──────────────────────────────────────────
ct = P.build(req(), SPEC, inject=["cross_tenant"])
case("K12 inject cross_tenant → cross_tenant>0 + BLOCK", ct["violations"]["cross_tenant"] > 0 and ct["terminal"] == "BLOCK")
bm = P.build(req(bind_tenant="t-other"), SPEC)
case("K12 bind mismatch → cross_tenant>0", bm["violations"]["cross_tenant"] > 0)
case("K12 spec sızıntısız", P.scan_leaks(json.dumps(SPEC)) == [])
case("K12 config sızıntısız", P.scan_leaks(json.dumps(P._load(P.CONFIG_PATH))) == [])

npass = sum(1 for ok, _ in RESULTS if ok)
for ok, name in RESULTS:
    print(("  ✓ " if ok else "  ✗ ") + name)
print("\nbehavior: %d/%d %s" % (npass, len(RESULTS), "🟢" if npass == len(RESULTS) else "🔴"))
sys.exit(0 if npass == len(RESULTS) else 1)
