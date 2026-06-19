#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
version_compare_behavior_test.py — WBS 14.2.7 sürüm karşılaştırma motoru davranış kapısı (T1–T11).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: VersionCompareEngine'in FR-ANA-010 agent sürümleri performans
karşılaştırmasını — apples-to-apples bütünlüğü (aynı agent+tenant+period+metrik) + istatistiksel anlamlılık
(gürültüden kazanan yok) + yön-duyarlı delta + metric_catalog BİREBİR + idempotency + küçük-örnek bastırma +
tenant izolasyon + PII disiplinini — gerçek karşılaştırma senaryolarında uyguladığını doğrular. stdlib-only,
credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import version_compare_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "confidence": 0.95, "min_sample_n": 30}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(comparison, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.compare_request({"comparison": comparison}, SPEC, dict(PROF), CTX, p)


def arm(ver, cont=None, trans=None, crit=None, score=None, n=1000, agent="ag_support", period="2026-06", **extra):
    return P._arm(ver, cont=cont, trans=trans, crit=crit, score=score, n=n, agent=agent, period=period, **extra)


def cmp_(base, cand, **kw):
    return P._cmp(base, cand, **kw)


def row(m, cand, metric):
    return P._row(m, cand, metric)


# T1 — apples-to-apples bütünlüğü: aynı agent+period → BİRİNCİL kapı geçer
m = run(cmp_(arm("v1", cont=0.60, n=1200), arm("v2", cont=0.74, n=1200)))
check(m["comparison_integrity_violations"] == 0 and all(ok for ok, _ in P.evaluate(SPEC, m)),
      "T1 aynı agent+period karşılaştırma → G1 bütünlük + tüm kapı geçer")

# T2 — anlamlı iyileşme: containment 0.60→0.74 (n=1200) → improved (winner=candidate)
r = row(m, "v2", "containment_rate")
check(r["verdict"] == "improved" and r["winner"] == "candidate" and r["significant"]
      and abs(r["delta"] - 0.14) < 1e-6,
      "T2 containment 0.60→0.74 anlamlı → improved (Δ=+0.14, winner=candidate)")

# T3 — anlamlılık çekirdeği: küçük delta gürültü → inconclusive (kazanan YOK)
mn = run(cmp_(arm("v1", cont=0.600, n=1000), arm("v2", cont=0.612, n=1000)))
rn = row(mn, "v2", "containment_rate")
check(rn["verdict"] == "inconclusive" and not rn["significant"],
      "T3 küçük delta (0.600→0.612) anlamlı DEĞİL → inconclusive (gürültüden kazanan YOK)")
check(all(ok for ok, _ in P.evaluate(SPEC, mn)), "T3 inconclusive doğru davranış → kapı geçer")

# T4 — require_significance kapalı → ham delta işaretinden kazanan → G3 eler
mb = run(cmp_(arm("v1", cont=0.600, n=1000), arm("v2", cont=0.612, n=1000)), require_significance=False)
check(mb["significance_violations"] >= 1, "T4 require_significance kapalı: anlamsız 'improved' → G3 eler")

# T5 — yön-duyarlılık: critical_rate lower_is_better; 0.02→0.05 anlamlı↑ → regressed (winner=baseline)
mc = run(cmp_(arm("v1", crit=0.02, n=2000), arm("v2", crit=0.05, n=2000)))
rc = row(mc, "v2", "critical_rate")
check(rc["verdict"] == "regressed" and rc["winner"] == "baseline",
      "T5 critical 0.02→0.05 (lower_is_better) anlamlı↑ → regressed (winner=baseline)")
check(mc["derived"]["pairs"][0]["recommendation"] == "keep_baseline",
      "T5 guardrail (critical) anlamlı regresyon → öneri keep_baseline (SOFT)")
# yön yok sayılırsa (buggy) → G2 eler
check(run(cmp_(arm("v1", crit=0.02, n=2000), arm("v2", crit=0.05, n=2000)), correct_direction=False)["delta_violations"] >= 1,
      "T5 correct_direction kapalı: yön ters → G2 eler")

# T6 — cross-agent / cross-period / self-compare → G1 eler
check(run(cmp_(arm("v1", cont=0.6, agent="ag1"), arm("v2", cont=0.7, agent="ag2")))["comparison_integrity_violations"] >= 1,
      "T6 cross-agent kol → G1 eler (apples-to-apples)")
check(run(cmp_(arm("v1", cont=0.6, period="2026-06"), arm("v2", cont=0.7, period="2026-05")))["comparison_integrity_violations"] >= 1,
      "T6 cross-period kol → G1 eler")
selfc = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_versions": ["v1"],
         "arms": [arm("v1", cont=0.6), arm("v2", cont=0.7)]}
check(run(selfc)["comparison_integrity_violations"] >= 1, "T6 baseline==candidate → G1 eler")

# T7 — metric_catalog BİREBİR: bilinmeyen metrik → G4 eler
b = arm("v1", cont=0.6); b["metrics"]["bogus"] = {"num": 3, "den": 10}
c = arm("v2", cont=0.7); c["metrics"]["bogus"] = {"num": 7, "den": 10}
check(run(cmp_(b, c))["vocab_violations"] >= 1, "T7 bilinmeyen metrik → G4 katalog eler")

# T8 — idempotency: duplicate version arm → G5 eler
dup = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_version": "v2",
       "arms": [arm("v1", cont=0.6), arm("v2", cont=0.7), arm("v2", cont=0.65)]}
check(run(dup, idempotent=False)["idempotency_violations"] >= 1, "T8 duplicate version arm → G5 eler")
check(run(dup)["idempotency_violations"] >= 1, "T8 idempotent açık: duplicate yine tespit + daraltılır")

# T9 — küçük-örnek bastırma: kol n<min_sample_n → insufficient_sample (sessizce düşmez)
sm = run(cmp_(arm("v1", cont=0.6, n=10), arm("v2", cont=0.9, n=12)))
rs = row(sm, "v2", "containment_rate")
check(rs["verdict"] == "insufficient_sample" and rs["winner"] == "none",
      "T9 kol(10/12)<min_sample_n(30) → insufficient_sample (bastırılır, kazanan yok)")
check(run(cmp_(arm("v1", cont=0.6, n=10), arm("v2", cont=0.9, n=12)), suppress_small=False)["suppression_violations"] >= 1,
      "T9 suppress_small kapalı: küçük-örnek kazanan yayımlanır → G6 eler (k-anon)")

# T10 — tenant izolasyon + residency
ct = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_version": "v2",
      "arms": [arm("v1", cont=0.6), arm("v2", cont=0.7, tenant_id="t_other")]}
check(run(ct)["isolation_violations"] >= 1, "T10 cross-tenant kol → G7 eler")
rd = {"agent_id": "ag_support", "period": "2026-06", "baseline_version": "v1", "candidate_version": "v2",
      "arms": [arm("v1", cont=0.6), arm("v2", cont=0.7, region="us-east-1")]}
check(run(rd)["isolation_violations"] >= 1, "T10 home-region dışı kol (residency) → G7 eler (NFR 10.7)")

# T11 — PII redaksiyon + determinizm + non-blocking
leak = arm("v2", cont=0.7); leak["transcript_text"] = "ham"
check(run(cmp_(arm("v1", cont=0.6), leak))["pii_violations"] >= 1, "T11 transcript_text yasak girdi → G8 PII eler")
check(run(cmp_(arm("v1", cont=0.6, n=1200), arm("v2", cont=0.74, n=1200)))
      == run(cmp_(arm("v1", cont=0.6, n=1200), arm("v2", cont=0.74, n=1200))),
      "T11 determinizm: aynı stats aynı verdict (random yok)")
check(run(cmp_(arm("v1", cont=0.6), arm("v2", cont=0.7)), non_blocking=False)["blocking_violations"] >= 1,
      "T11 non_blocking kapalı → G9 eler (FR-RES-011)")

# eksik/geçersiz girdi reddi
try:
    run({"agent_id": "ag1", "period": "p", "baseline_version": "v1", "arms": [arm("v1", cont=0.6)]})
    check(False, "<2 kol reddedilmeli")
except P.CompareError:
    check(True, "<2 kol girdi → reddedilir (INVALID_REQUEST)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
