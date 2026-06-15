#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 10.1.8 — A/B test kampanyaları davranış kapısı (C1–C12).

Probe'un selftest'inden BAĞIMSIZ, kara-kutu davranış kontrolleri: A/B varyant dağıtım + karşılaştırma
motorunun sözleşmesini (FR-OUT-012 / SR-OUT-012) doğrudan doğrular. Stdlib-only, bağımlılıksız.
Çalıştırma: python3 tests/ab_testing_behavior_test.py → çıkış kodu.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ab_testing_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)


def _req(**kw):
    d = {
        "tenant_id": "t", "correlation_id": "c", "campaign_id": "camp-x",
        "experiment_id": "exp-x",
        "actor_role": "operations_manager",
        "variants": [
            {"id": "var-A", "weight": 0.5, "script_version": "scr-v1"},
            {"id": "var-B", "weight": 0.5, "script_version": "scr-v2"},
        ],
        "contacts_count": 300,
    }
    d.update(kw)
    return d


def run():
    cases = []

    def check(name, cond):
        cases.append((bool(cond), name))

    # C1 — her istek terminal sonuca ulaşır (APPLIED|DENIED), stuck yok
    for actor, variants in (("operations_manager", None),
                            ("human_agent", None),
                            ("operations_manager", [{"id": "var-A", "weight": 1.0, "script_version": "scr-v1"}])):
        kw = {"actor_role": actor}
        if variants:
            kw["variants"] = variants
        r = P.build(_req(**kw), SPEC)
        check("C1 terminal (%s): %s" % (actor, r["terminal"]), r["terminal"] in P.TERMINAL)
        check("C1 stuck_state=0 (%s)" % actor, r["violations"]["stuck_state"] == 0)

    # C2 — yetki: yetkili uygular, yetkisiz reddedilir
    r = P.build(_req(), SPEC)
    check("C2 yetkili APPLIED", r["terminal"] == "APPLIED" and r["violations"]["unauthorized"] == 0)
    r = P.build(_req(actor_role="qa_analyst"), SPEC)
    check("C2 yetkisiz DENIED (işlem yok)", r["terminal"] == "DENIED" and r["applied"] is False)
    check("C2 yetkisiz reddetme ihlal değil", all(v == 0 for v in r["violations"].values()))
    r = P.build(_req(actor_role="qa_analyst"), SPEC, inject=["skip_auth"])
    check("C2 inject skip_auth → unauthorized yakalanır", r["violations"]["unauthorized"] > 0)

    # C3 — config geçerliliği: ≥2 varyant, ağırlık toplamı 1.0, script_version
    r = P.build(_req(variants=[{"id": "var-A", "weight": 1.0, "script_version": "scr-v1"}]), SPEC)
    check("C3 tek varyant DENIED", r["terminal"] == "DENIED" and r["deny_reason"] == "invalid_config")
    r = P.build(_req(variants=[{"id": "var-A", "weight": 0.4, "script_version": "scr-v1"},
                              {"id": "var-B", "weight": 0.4, "script_version": "scr-v2"}]), SPEC)
    check("C3 ağırlık toplamı≠1 DENIED", r["terminal"] == "DENIED")
    r = P.build(_req(variants=[{"id": "var-A", "weight": 0.5, "script_version": "scr-v1"},
                              {"id": "var-A", "weight": 0.5, "script_version": "scr-v2"}]), SPEC)
    check("C3 tekrarlı id DENIED", r["terminal"] == "DENIED")
    r = P.build(_req(variants=[{"id": "var-A", "weight": 0.5},
                              {"id": "var-B", "weight": 0.5, "script_version": "scr-v2"}]), SPEC)
    check("C3 script_version eksik DENIED", r["terminal"] == "DENIED")
    check("C3 geçersiz config ihlal değil (doğru reddetme)", r["violations"]["invalid_config"] == 0)
    r = P.build(_req(variants=[{"id": "var-A", "weight": 1.0, "script_version": "scr-v1"}]), SPEC, inject=["invalid_config"])
    check("C3 inject invalid_config yakalanır", r["violations"]["invalid_config"] > 0)

    # C4 — SR-OUT-012 ÇEKİRDEK 1/2: deterministik+sticky dağıtım
    r = P.build(_req(), SPEC)
    check("C4 her contact atandı", sum(r["allocation_counts"].values()) == 300)
    check("C4 yalnız tanımlı varyantlar", set(r["allocation_counts"]) <= {"var-A", "var-B"})
    check("C4 skew ≤ tolerans", r["weight_skew_max"] <= 0.10)
    check("C4 misallocation=0", r["violations"]["misallocation"] == 0)
    a1 = P.build(_req(), SPEC)["allocation_counts"]
    a2 = P.build(_req(), SPEC)["allocation_counts"]
    check("C4 sticky: tekrar aynı dağıtım", a1 == a2)
    r = P.build(_req(), SPEC, inject=["misallocation"])
    check("C4 inject misallocation yakalanır", r["violations"]["misallocation"] > 0)

    # C5 — SR-OUT-012 ÇEKİRDEK 2/2: karşılaştırma (winner / inconclusive)
    r = P.build(_req(outcomes={"var-A": {"trials": 1000, "conversions": 100},
                              "var-B": {"trials": 1000, "conversions": 220}}), SPEC)
    check("C5 anlamlı fark → winner", r["verdict"] == "winner" and r["leader"] == "var-B")
    r = P.build(_req(outcomes={"var-A": {"trials": 100, "conversions": 50},
                              "var-B": {"trials": 100, "conversions": 52}}), SPEC)
    check("C5 anlamsız fark → inconclusive", r["verdict"] == "inconclusive")
    r = P.build(_req(outcomes={"var-A": {"trials": 10, "conversions": 1},
                              "var-B": {"trials": 10, "conversions": 5}}, min_sample=100), SPEC)
    check("C5 yetersiz örneklem → inconclusive", r["verdict"] == "inconclusive")
    check("C5 false_winner=0", r["violations"]["false_winner"] == 0)
    r = P.build(_req(outcomes={"var-A": {"trials": 100, "conversions": 50},
                              "var-B": {"trials": 100, "conversions": 52}}), SPEC, inject=["false_winner"])
    check("C5 inject false_winner yakalanır", r["violations"]["false_winner"] > 0)

    # C6 — idempotency (sticky tekrar)
    r = P.build(_req(), SPEC)
    check("C6 not_idempotent=0", r["violations"]["not_idempotent"] == 0)
    r = P.build(_req(), SPEC, inject=["not_idempotent"])
    check("C6 inject not_idempotent yakalanır", r["violations"]["not_idempotent"] > 0)

    # C7 — tenant izolasyonu
    r = P.build(_req(), SPEC)
    check("C7 cross_tenant=0", r["violations"]["cross_tenant"] == 0)
    r = P.build(_req(), SPEC, inject=["cross_tenant"])
    check("C7 inject cross_tenant yakalanır", r["violations"]["cross_tenant"] > 0)
    r = P.build(_req(bind_tenant="t-other"), SPEC)
    check("C7 bind_tenant uyuşmazlığı yakalanır", r["violations"]["cross_tenant"] > 0)

    # C8 — uygunluk koruması (consent/DNC/saat atlanmaz)
    s = dict(_req(contacts=["ck-1", "ck-2", "ck-3", "ck-4"], ineligible_contacts=["ck-2"]))
    s.pop("contacts_count", None)
    r = P.build(s, SPEC)
    check("C8 ineligible callable değil (callable=3)", r["callable_count"] == 3)
    check("C8 eligibility_bypass=0", r["violations"]["eligibility_bypass"] == 0)
    r = P.build(s, SPEC, inject=["eligibility_bypass"])
    check("C8 inject eligibility_bypass yakalanır", r["violations"]["eligibility_bypass"] > 0)

    # C9 — kanıt: experiment + variants + comparison + allocation
    r = P.build(_req(outcomes={"var-A": {"trials": 1000, "conversions": 100},
                              "var-B": {"trials": 1000, "conversions": 220}}), SPEC)
    check("C9 evidence experiment taşır", r["evidence"]["experiment_id"] == "exp-x")
    check("C9 evidence variants taşır", len(r["evidence"]["variants"]) == 2)
    check("C9 evidence allocation_counts taşır", sum(r["evidence"]["allocation_counts"].values()) == 300)
    check("C9 evidence comparison.verdict taşır", r["evidence"]["comparison"]["verdict"] == "winner")
    check("C9 missing_evidence=0", r["violations"]["missing_evidence"] == 0)

    # C10 — audit: her sonuç (APPLIED/DENIED) audit'lenir
    for actor, exp in (("operations_manager", "APPLIED"), ("human_agent", "DENIED")):
        r = P.build(_req(actor_role=actor), SPEC)
        check("C10 audit (%s)" % exp, r["audit"] is not None and r["audit"]["result"] == exp)
    r = P.build(_req(), SPEC, inject=["no_audit"])
    check("C10 inject no_audit → missing_audit", r["violations"]["missing_audit"] > 0)

    # C11/C12 — sızıntı tarayıcı: yapısal/kimlik temiz, ham PII/telefon yakalanır
    check("C12 exp-001 kimlik temiz", P.scan_leaks('{"experiment_id": "exp-001"}') == [])
    check("C12 var-A/ck-001 kimlik temiz",
          P.scan_leaks('{"variant": "var-A", "contact_key": "ck-001"}') == [])
    check("C12 ham telefon alanı yakalanır", len(P.scan_leaks('{"customer_phone_value": "x"}')) > 0)

    npass = sum(1 for ok, _ in cases if ok)
    for ok, name in cases:
        print(("  ✓ " if ok else "  ✗ ") + name)
    print("\nbehavior: %d/%d %s" % (npass, len(cases), "🟢" if npass == len(cases) else "🔴"))
    return 0 if npass == len(cases) else 1


if __name__ == "__main__":
    sys.exit(run())
