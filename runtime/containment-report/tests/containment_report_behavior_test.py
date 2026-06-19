#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
containment_report_behavior_test.py — WBS 14.2.3 oran rapor motoru davranış kapısı (T1–T11).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: ContainmentReportEngine'in FR-ANA-003 containment/transfer
ORAN agregasyonu + partisyon bütünlüğü + payda doğruluğu (handled, not_connected hariç) + münhasırlık +
14.2.2 kapalı-sözlük BİREBİR + idempotency + küçük-örnek bastırma + tenant izolasyon + PII disiplinini
gerçek rapor senaryolarında uyguladığını doğrular. stdlib-only, credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import containment_report_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "min_group_n": 4,
        "containment_target": 0.60}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(calls, **pol):
    p = P._full_pol()
    p.update(pol)
    prof = dict(PROF)
    if not p.get("correct_denom", True):
        prof["denominator_basis"] = "total"
    return P.report_calls({"calls": calls}, SPEC, prof, CTX, p)


def C(cid, outcome, agent="ag1", ver="v1", period="2026-06-01", **extra):
    r = {"call_id": cid, "outcome": outcome, "agent_id": agent, "agent_version_id": ver, "period": period}
    r.update(extra)
    return r


def bulk(n, outcome, prefix, **kw):
    return [C("%s%d" % (prefix, i), outcome, **kw) for i in range(n)]


# T1 — partisyon bütünlüğü: kovalar girdiyi TAM partisyonlar (sayılan == girdi)
calls = bulk(6, "contained", "a") + bulk(3, "transferred_to_human", "b") + bulk(1, "abandoned", "c") + bulk(2, "not_connected", "d")
m = run(calls)
check(m["partition_gap"] == 0 and m["derived"]["counted_total"] == m["derived"]["input_count"] == 12,
      "T1 partisyon tam: sayılan == girdi == 12 (çift/düşme yok)")
check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tüm HARD kapı geçer")

# T2 — containment/transfer = pay/handled; not_connected paydaya GİRMEZ
ov = m["derived"]["overall"]
check(ov["handled"] == 10 and ov["calls"] == 12, "T2 handled=10 (not_connected hariç), calls=12")
check(abs(ov["containment_rate"] - 0.6) < 1e-9 and abs(ov["transfer_rate"] - 0.3) < 1e-9,
      "T2 containment=6/10=0.60, transfer=3/10=0.30 (handled paydası)")

# T3 — dört partisyon oranı handled üzerinde toplamı == 1.0 (payda bütünlüğü)
psum = ov["containment_rate"] + ov["transfer_rate"] + ov["abandon_rate"] + ov["unresolved_rate"]
check(abs(psum - 1.0) < 1e-9, "T3 4 partisyon oranı toplamı == 1.0 (handled payda bütünlüğü)")

# T4 — yanlış payda (total, not_connected dahil) → partisyon toplamı ≠ 1.0 → G2 eler
m4 = run(bulk(6, "contained", "a") + bulk(2, "transferred_to_human", "b") + bulk(4, "not_connected", "d"), correct_denom=False)
check(m4["rate_bound_violations"] >= 1, "T4 payda=total (not_connected dahil) → partisyon toplamı ≠1.0 → G2 eler")
check(abs(m4["derived"]["overall"]["containment_rate"] - (6 / 12)) < 1e-4,
      "T4 yanlış payda containment=6/12 (handled=8 olmalıydı → yapay düşer)")

# T5 — agent_version grubu ayrımı (FR-ANA-010 sürüm karşılaştırması girdisi)
multi = bulk(8, "contained", "p", ver="v1") + bulk(2, "transferred_to_human", "q", ver="v1") \
    + bulk(4, "contained", "r", ver="v2") + bulk(6, "transferred_to_human", "s", ver="v2")
m5 = run(multi)
rows = {gk: gm for gk, gm in m5["derived"]["rows"]}
check(abs(rows[("ag1", "v1", "2026-06-01")]["containment_rate"] - 0.8) < 1e-9
      and abs(rows[("ag1", "v2", "2026-06-01")]["containment_rate"] - 0.4) < 1e-9,
      "T5 v1 containment 0.80 vs v2 0.40 (sürüm karşılaştırması)")
check(abs(m5["derived"]["overall"]["containment_rate"] - 0.6) < 1e-9, "T5 overall = 12/20 = 0.60 (grup toplamı)")

# T6 — münhasırlık: bir çağrı tam BİR kovada
m6 = run(bulk(5, "contained", "a") + bulk(1, "transferred_to_human", "b"), exclusive_buckets=False)
check(m6["exclusivity_violations"] >= 1, "T6 exclusive_buckets kapalı: contained transferred'a da sayılır → G3 eler")

# T7 — 14.2.2 kapalı-sözlük BİREBİR: bilinmeyen outcome → G4
m7 = run(bulk(5, "contained", "a") + [C("z", "totally_made_up")])
check(m7["vocab_violations"] >= 1, "T7 bilinmeyen outcome → G4 sözlük eler (14.2.2 vocab BİREBİR)")

# T8 — idempotency: replay (aynı call_id) daraltılır
dup = bulk(5, "contained", "a") + [C("a0", "contained")]
m8 = run(dup)
check(m8["derived"]["input_count"] == 5 and m8["idempotency_violations"] == 0, "T8 replay daraltılır (5 sayım)")
check(run(dup, idempotent=False)["idempotency_violations"] >= 1, "T8 idempotent kapalı → çift-sayım tespit edilir")

# T9 — küçük-örnek bastırma: handled<min_group_n → insufficient_sample (sessizce düşmez)
small = bulk(2, "contained", "a") + bulk(1, "transferred_to_human", "b")   # handled=3 < 4
m9 = run(small)
g9 = m9["derived"]["rows"][0][1]
check(g9["status"] == "insufficient_sample" and g9["target_met"] is None,
      "T9 handled<min_group_n → bastırılır (status=insufficient_sample, oran yayımlanmaz)")
check(run(small, suppress_small=False)["suppression_violations"] >= 1,
      "T9 suppress_small kapalı → küçük grup oranı yayımlanır → G6 eler (k-anon)")

# T10 — tenant izolasyon + residency
cross = bulk(5, "contained", "a") + [C("ct", "contained", tenant_id="t_other")]
m10 = run(cross)
check(m10["isolation_violations"] >= 1 and m10["derived"]["input_count"] == 5,
      "T10 cross-tenant çağrı → G7 eler + agregasyona karışmaz")
check(run(bulk(5, "contained", "a") + [C("rd", "contained", region="us-east-1")])["isolation_violations"] >= 1,
      "T10 home-region dışı çağrı (residency) → G7 eler (NFR 10.7)")

# T11 — PII redaksiyon + determinizm + non-blocking
m11 = run(bulk(5, "contained", "a") + [C("p", "contained", transcript_text="ham")])
check(m11["pii_violations"] >= 1, "T11 transcript_text yasak girdi → G8 PII eler")
check(run(calls) == run(calls), "T11 determinizm: aynı çağrı seti aynı oran (random yok)")
check(run(calls, non_blocking=False)["blocking_violations"] >= 1, "T11 non_blocking kapalı → G9 eler (FR-RES-011)")

# bilinmeyen/eksik girdi reddi
try:
    run([{"call_id": "u", "agent_id": "ag1"}])
    check(False, "outcome eksik reddedilmeli")
except P.ReportError:
    check(True, "outcome eksik girdi → reddedilir (INVALID_REQUEST)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
