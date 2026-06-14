#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
context_propagation_behavior_test.py — WBS 3.1.5 context propagation davranış kapısı (T1–T8)

stdlib-only, bağımsız. context_propagation_probe.py çekirdeğini import edip bağlam tamlığı (G1) /
kardinalite disiplini (G2) / PII yasağı (G3) / tenant binding (G4) / correlation sürekliliği (G5) /
adapter bağlamı (G6) / region pin (G7) / immutable mutation (G8) davranışlarını doğrular
(turn_taking_behavior_test / resource_budget_behavior_test deseni).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import context_propagation_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
SESSION = {
    "tenant_id": "t_acme", "org_unit": "ou_sales", "agent_id": "ag_1",
    "correlation_id": "corr-001", "region": "eu-west-1",
    "call_id": "call-001", "session_id": "sess-001", "trace_id": "tr-001",
}


def _run(emissions, session=None, **pol):
    policy = {"attach_context": True, "enforce_cardinality": True, "enforce_pii": True,
              "bind_tenant": True, "pin_region": True}
    policy.update(pol)
    return P.simulate({"emissions": emissions}, SPEC, session or SESSION, policy)


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — bağlam tamlığı: her event/log/span/adapter required_keys taşır (G1)
    full = [{"t": 0, "kind": "event"}, {"t": 10, "kind": "log"}, {"t": 20, "kind": "span"},
            {"t": 30, "kind": "adapter_call", "provider": "stt"}]
    m = _run(full)
    check(m["missing_context"] == 0 and m["context_complete"] == 4, "T1 bağlam tamlığı: 4/4 kayıt tam (G1)")
    check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tüm kapılar geçer")

    # T2 — kardinalite: yüksek-kardinalite kimlik label değil exemplar (G2)
    met = [{"t": 0, "kind": "metric", "labels": ["tenant_id", "region", "correlation_id", "call_id"]}]
    mm = _run(met)
    check(mm["cardinality_violations"] == 0, "T2 correlation_id/call_id label'dan çıkarıldı (G2)")
    check(mm["exemplars_attached"] == 1, "T2 correlation_id exemplar olarak bağlandı (call_id değil)")
    mm2 = _run(met, enforce_cardinality=False)
    check(mm2["cardinality_violations"] == 2, "T2 enforce KAPALI: 2 yüksek-kardinalite label geçti (G2 eler)")

    # T3 — PII yasağı: label + attribute (G3)
    pii = [{"t": 0, "kind": "metric", "labels": ["tenant_id", "phone_number"]},
           {"t": 10, "kind": "span", "attrs": ["customer_name", "card_number"]}]
    mp = _run(pii)
    check(mp["pii_violations"] == 0, "T3 PII label+attribute enforce ile çıkarıldı (G3)")
    mp2 = _run(pii, enforce_pii=False)
    check(mp2["pii_violations"] == 3, "T3 enforce KAPALI: phone+name+card → 3 ihlal (G3 eler)")

    # T4 — tenant binding immutable: override engellenir, cross-tenant=0 (G4/G8)
    tb = [{"t": 0, "kind": "event", "tenant_id_override": "t_evil"},
          {"t": 10, "kind": "adapter_call", "provider": "llm", "tenant_id_override": "t_evil"}]
    mt = _run(tb)
    check(mt["cross_tenant_violations"] == 0 and mt["illegal_context_mutations"] == 0,
          "T4 tenant binding: override engellendi (G4/G8)")
    check(mt["blocked_mutations"] == 2, "T4 2 mutasyon denemesi bloklandı (oturum tenant_id korundu)")
    mt2 = _run(tb, bind_tenant=False)
    check(mt2["cross_tenant_violations"] == 2 and mt2["illegal_context_mutations"] == 2,
          "T4 binding KAPALI: farklı tenant 2 kez geçti (G4/G8 eler)")

    # T5 — correlation sürekliliği: çağrı başına tek correlation_id (G5)
    cc = [{"t": 0, "kind": "event"}, {"t": 10, "kind": "log"},
          {"t": 20, "kind": "event", "correlation_id_override": "corr-other"}]
    mc = _run(cc)
    check(mc["distinct_correlation_ids"] == 1 and mc["correlation_discontinuity"] == 0,
          "T5 tek correlation_id; override binding'le korundu (G5)")
    mc2 = _run(cc, bind_tenant=False)
    check(mc2["distinct_correlation_ids"] == 2 and mc2["correlation_discontinuity"] == 1,
          "T5 binding KAPALI: 2 correlation_id → süreksizlik (G5 eler)")

    # T6 — adapter bağlamı: her giden çağrı correlation_id+tenant_id+region (G6)
    ad = [{"t": 0, "kind": "adapter_call", "provider": "stt"},
          {"t": 10, "kind": "tool_call", "provider": "crm"}]
    ma = _run(ad)
    check(ma["adapter_calls"] == 2 and ma["adapter_context_missing"] == 0,
          "T6 2 adapter/tool çağrısı tam bağlamlı (G6)")
    ma2 = _run(ad, attach_context=False)
    check(ma2["adapter_context_missing"] == 2, "T6 attach KAPALI: 2 çağrı bağlamsız (G6 eler)")

    # T7 — region pin: adapter farklı region dese de home-region'a pinli (G7)
    rp = [{"t": 0, "kind": "adapter_call", "provider": "llm", "region": "us-east-1"}]
    mr = _run(rp)
    check(mr["region_violations"] == 0, "T7 region pin: farklı region engellendi (G7)")
    mr2 = _run(rp, pin_region=False)
    check(mr2["region_violations"] == 1, "T7 pin KAPALI: home-region dışına çıktı (G7 eler)")

    # T8 — reddetme + sıralama (G10) + determinizm
    def raises(fn):
        try:
            fn(); return False
        except P.ContextError:
            return True
    check(raises(lambda: P.simulate({"emissions": [{"t": 0, "kind": "bogus"}]}, SPEC, SESSION,
                                    {"attach_context": True})), "T8 bilinmeyen yüzey reddedilir")
    check(raises(lambda: P.simulate({"emissions": [{"t": 0, "kind": "event"}]}, SPEC,
                                    {"tenant_id": "t1"}, {"attach_context": True})),
          "T8 ingress correlation_id eksik reddedilir")
    uno = [{"t": 30, "kind": "metric", "labels": ["call_id"]}, {"t": 0, "kind": "event"}]
    mu1 = _run(uno); mu2 = _run(uno)
    check(mu1 == mu2 and mu1["cardinality_violations"] == 0, "T8 determinizm + karışık-t doğru işlenir")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("context_propagation_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
