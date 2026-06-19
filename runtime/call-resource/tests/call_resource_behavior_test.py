#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_resource_behavior_test.py — WBS 14.1.3 per-call CPU/bellek/eşzamanlılık davranış kapısı (T1–T8)

stdlib-only, bağımsız. call_resource_probe.py çekirdeğini import edip kapsam (G1) / katalog uyumu (G2) /
değer domaini (G3) / bütçe (G4, FR-RES-016 ≤15MB MEDYA HARİÇ) / density (G5, NFR 10.2 ≥250) /
kardinalite (G6) / etiket+PII (G7) davranışlarını doğrular (call_metrics_behavior_test deseni).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import call_resource_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
CONTEXT = P.CONTEXT
HAPPY = P.HAPPY_BUNDLE
MEDIA = P.MEDIA_BUNDLE


def _run(bundle, context=None, must_cover=None, **pol):
    policy = P._full_pol()
    policy.update(pol)
    sample = {"bundle": bundle}
    if must_cover is not None:
        sample["must_cover"] = must_cover
    return P.measure_call(sample, SPEC, context or CONTEXT, policy)


def run():
    results = []

    def check(ok, label):
        results.append((bool(ok), label))

    # T1 — kapsam: required CPU/bellek/eşzamanlılık ölçülüp yayılır (G1)
    m = _run(HAPPY)
    check(m["resource_missing"] == 0, "T1 kapsam: 4 required kaynak metriği ölçüldü (G1)")
    check(all(ok for ok, _ in P.evaluate(SPEC, m)), "T1 tam çağrı tüm kapıları geçer")
    m2 = _run(HAPPY, measure_all=False, drop_metrics=["call_cpu_seconds", "tenant_concurrency"])
    check(m2["resource_missing"] == 2, "T1 2 metrik düşerse → 2 eksik (G1 eler)")

    # T2 — katalog uyumu: yalnız catalog name/type/unit; overlap 0.4.7 birebir (G2)
    check(m["catalog_violations"] == 0, "T2 happy: katalog uyumlu (G2)")
    mm = _run(HAPPY, conform_catalog=False)
    check(mm["catalog_violations"] >= 1, "T2 conform KAPALI: catalog dışı metrik → G2 eler")

    # T3 — değer domaini: cpu_s≥0, byte int≥0, sayım int≥0 (G3)
    check(m["value_violations"] == 0, "T3 happy: değerler domain-içi (G3)")
    bad = json.loads(json.dumps(HAPPY))
    bad["cpu"] = {"user_ms": -120, "system_ms": 0}   # negatif CPU → domain dışı
    mt = _run(bad)
    check(mt["value_violations"] >= 1, "T3 negatif CPU → domain dışı → G3 eler")

    # T4 — bütçe (FR-RES-016 ≤15MB; MEDYA HARİÇ) (G4) + DEĞER doğruluğu
    check(m["budget_violations"] == 0, "T4 happy: bellek 11MiB ≤15MB (G4)")
    check(m["values"]["call_cpu_seconds"] == 0.22 and m["values"]["call_memory_bytes"] == 11534336,
          "T4 ölçülen DEĞERLER doğru (cpu=0.22s, mem=11MiB MEDYA HARİÇ)")
    # medya eş-konumlu: media buffer ayrı yayılır; bütçe yine MEDYA HARİÇ geçer
    mc = _run(MEDIA)
    check("call_media_buffer_bytes" in mc["values"] and mc["budget_violations"] == 0,
          "T4 medya eş-konumlu: media buffer ayrı + bütçe MEDYA HARİÇ geçer")
    mcb = _run(MEDIA, exclude_media=False)
    check(mcb["budget_violations"] >= 1, "T4 exclude_media KAPALI: medya bütçeye dahil → şişer → G4 eler")
    big = json.loads(json.dumps(HAPPY)); big["memory"]["session_rss_bytes"] = 25165824   # 24 MiB
    mb = _run(big)
    check(mb["budget_violations"] >= 1 and mb["derived"]["budget_headroom_bytes"] < 0,
          "T4 oturum belleği 24MiB > 15MB → G4 eler + headroom negatif (aşım izlenir)")

    # T5 — density (NFR 10.2 ≥250; footprint mem×floor ≤ pool) (G5)
    check(m["density_violations"] == 0, "T5 happy: footprint ≥250 density'ye yer verir (G5)")
    check(m["derived"]["density_supported_sessions"] >= 250, "T5 11MiB footprint ≥250 oturum destekler")
    huge = json.loads(json.dumps(HAPPY)); huge["memory"]["session_rss_bytes"] = 83886080   # 80 MiB
    mh = _run(huge)
    check(mh["density_violations"] >= 1 and mh["derived"]["density_supported_sessions"] < 250,
          "T5 80MiB footprint → ≥250 density'ye yer vermez → G5 eler")

    # T6 — kardinalite: yüksek-kardinalite kimlik LABEL olmaz (G6)
    check(m["cardinality_violations"] == 0, "T6 happy: yüksek-kardinalite label yok (G6)")
    m6 = _run(HAPPY, enforce_cardinality=False)
    check(m6["cardinality_violations"] >= 1, "T6 enforce KAPALI: correlation_id label → G6 eler")

    # T7 — etiket + PII: yalnız allowed label + PII yok (G7)
    check(m["label_violations"] == 0 and m["pii_violations"] == 0, "T7 happy: izinsiz/PII label yok (G7)")
    m7l = _run(HAPPY, enforce_labels=False)
    check(m7l["label_violations"] >= 1, "T7 label KAPALI: izinsiz boyut → G7 eler")
    m7p = _run(HAPPY, enforce_pii=False)
    check(m7p["pii_violations"] >= 1, "T7 pii KAPALI: phone_number label → G7 eler")

    # T8 — reddetme (G10) + determinizm + eşzamanlılık DEĞER doğruluğu
    def raises(fn):
        try:
            fn(); return False
        except P.ResourceError:
            return True
    check(raises(lambda: P.measure_call({"bundle": {"cpu": {}}}, SPEC, CONTEXT, P._full_pol())),
          "T8 bundle.memory eksik → reddedilir")
    check(raises(lambda: P.PerCallResourceAccountant(SPEC, {"region": "eu"}, P._full_pol())),
          "T8 emisyon bağlamı (tenant_id) eksik → reddedilir")
    check(m["values"]["worker_active_sessions"] == 420 and m["values"]["tenant_concurrency"] == 37
          and m["derived"]["tenant_concurrency_utilization"] == 0.37,
          "T8 eşzamanlılık DEĞERLERİ doğru (worker=420, tenant=37, kullanım=0.37)")
    s1 = _run(HAPPY)
    s2 = _run(HAPPY)
    check(s1 == s2, "T8 determinizm: aynı demet aynı sonuç (saf aritmetik)")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print("  %s %s" % ("✓" if ok else "✗", label))
    print("call_resource_behavior_test: %d/%d PASS" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(run())
