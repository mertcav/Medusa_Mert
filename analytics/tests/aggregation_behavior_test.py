#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aggregation_behavior_test.py — WBS 1.1.9 OLAP davranış kapısı (T1–T5)

Bağımlılıksız (stdlib-only), credential-free. olap-spec.json üzerinden:
  T1 — Her fact tablosunun bir 1.1.8 source_topic'i + idempotent consumer'ı var (lineage).
  T2 — Hiçbir sütun raw/sensitive değil (ham PII OLAP'a girmez, FR-REC-004/005).
  T3 — Maliyet kırılımı toplamı tutarlı (cost_*_micro alanları mevcut, FR-BIL-002/FR-ANA-007).
  T4 — Rollup'lar kaynak fact'e ve FR-ANA-* panosuna izlenir (A9).
  T5 — Retention katmanları monoton: fct_turn < operational < fct_usage (FR-REC-006).

Asıl deterministik kapı olap_probe.py'dir; bu test okunabilir senaryo kontrolüdür.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "..", "olap-spec.json")


def main():
    spec = json.load(open(SPEC, encoding="utf-8"))
    facts = spec["fact_tables"]
    rollups = spec["rollups"]
    known = set(spec["known_source_topics"])
    checks = []

    # T1 lineage
    for t in facts:
        ok = t["source_topic"] in known and t["source_consumer"] in ("analytics-ingest", "olap-sink")
        checks.append((ok, f"T1 {t['name']} lineage {t['source_topic']}/{t['source_consumer']}"))

    # T2 PII
    bad = [(t["name"], c["name"]) for t in (facts + spec["dimension_tables"])
           for c in t["columns"] if c["pii_class"] in ("raw", "sensitive")]
    checks.append((not bad, f"T2 ham PII sütunu yok ({len(bad)} ihlal)"))

    # T3 maliyet kırılımı (fct_usage)
    usage = next(t for t in facts if t["name"] == "fct_usage")
    ucols = {c["name"] for c in usage["columns"]}
    cost_parts = {"cost_telecom_micro", "cost_stt_micro", "cost_tts_micro", "cost_llm_micro", "cost_platform_micro"}
    checks.append((cost_parts <= ucols and "cost_total_micro" in ucols,
                   "T3 fct_usage sağlayıcı maliyet kırılımı + toplam (FR-BIL-002)"))

    # T4 rollup izlenebilirlik
    fact_names = {t["name"] for t in facts}
    for r in rollups:
        ok = r["source"] in fact_names and any(x.startswith("FR-ANA-") for x in r.get("dashboard_fr", []))
        checks.append((ok, f"T4 rollup {r['name']} → {r['source']} + FR-ANA"))

    # T5 retention monotonluğu
    ttl = {t["name"]: t["ttl_days"] for t in facts}
    checks.append((ttl["fct_turn"] < ttl["fct_call"] <= ttl["fct_usage"] and ttl["fct_usage"] >= 365,
                   f"T5 retention katmanı turn({ttl['fct_turn']}) < call({ttl['fct_call']}) <= usage({ttl['fct_usage']})"))

    passed = sum(1 for ok, _ in checks if ok)
    for ok, msg in checks:
        print(("  OK  " if ok else "  FAIL") + ": " + msg)
    print(f"behavior: {passed}/{len(checks)} PASS")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
