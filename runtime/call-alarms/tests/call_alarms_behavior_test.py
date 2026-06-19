#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
call_alarms_behavior_test.py — WBS 14.1.5 Alarm Rule Engine davranış kapısı (T1–T10).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: AlarmRuleEngine'in BRD §15 kuralları + ≤2dk üretim
(NFR 10.1) + kardinalite/PII + tenant-scope izolasyon + flap/dedup + severity routing disiplinini
gerçek sinyal senaryolarında uyguladığını doğrular. stdlib-only, credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import call_alarms_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
P._inject_required(SPEC)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1",
        "ingest_scrape_s": 15, "eval_interval_s": 15, "notify_lag_s": 10}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(signals, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.evaluate_call({"signals": signals}, SPEC, PROF, CTX, p)


# T1 — kapsam: 11/11 BRD §15 kritik alarm kuralı (0.4.7'den türetilir, non-circular)
m = run([{"rule": "E2EP95LatencyHigh", "value": 1600}])
check(m["derived"]["required_rules"] == 11 and m["derived"]["active_rules"] == 11, "T1 kapsam 11/11 (BRD §15)")
check(m["coverage_missing"] == 0, "T1 coverage_missing=0")

# T2 — ≤2dk üretim: standart profilde her kural detection latency ≤ 120s (NFR 10.1)
check(m["budget_violations"] == 0, "T2 detection bütçe ihlali=0 (NFR 10.1)")
check(m["derived"]["max_detection_latency_s"] <= 120, "T2 max detection latency ≤ 120s")
check(m["derived"]["max_detection_latency_s"] == 100, "T2 max latency = 40+60 = 100s (en geniş for_s)")

# T3 — firing doğruluğu: eşik aşan üretir, aşmayan üretmez
m3 = run([{"rule": "E2EP95LatencyHigh", "value": 1501}, {"rule": "E2EP95LatencyHigh", "value": 1499}])
check(m3["fired"] == 1, "T3 1501>1500 üretir, 1499 üretmez (comparator gt)")
m3b = run([{"rule": "LLMProviderErrorRateHigh", "value": 0.06}, {"rule": "SpendLimitExceeded", "value": 0.99}])
check(m3b["fired"] == 1, "T3 ratio 0.06>0.05 üretir, spend 0.99≤1.0 üretmez")

# T4 — detection bütçe aşımı: yavaş altyapı → > 120s eler
slow = {"name": "s", "region": "eu-west-1", "ingest_scrape_s": 40, "eval_interval_s": 40, "notify_lag_s": 20}
p = P._full_pol()
ms = P.evaluate_call({"signals": [{"rule": "E2EP95LatencyHigh", "value": 1600}]}, SPEC, slow, CTX, p)
check(ms["budget_violations"] >= 1, "T4 yavaş profil (100s ek-yük + 60 for = 160) → bütçe eler")

# T5 — kardinalite: kimlik alarm label OLAMAZ
m5 = run([{"rule": "E2EP95LatencyHigh", "value": 1600}], enforce_cardinality=False)
check(m5["cardinality_violations"] >= 1, "T5 correlation_id alarm label → ihlal")
m5ok = run([{"rule": "E2EP95LatencyHigh", "value": 1600}])
check(m5ok["cardinality_violations"] == 0, "T5 doğru: kimlik alarm label değil")

# T6 — PII: etikette ham PII anahtarı OLAMAZ (FR-REC-004)
m6 = run([{"rule": "E2EP95LatencyHigh", "value": 1600}], enforce_pii=False)
check(m6["pii_violations"] >= 1, "T6 phone_number alarm label → ihlal (FR-REC-004)")

# T7 — tenant-scope izolasyon: tenant alarmı tenant_id taşımalı, platform taşımamalı
mt = run([{"rule": "ConsentSkipDetected", "value": 1}])
check(mt["scope_violations"] == 0, "T7 tenant alarmı tenant_id taşır → izolasyon temiz")
mt2 = run([{"rule": "ConsentSkipDetected", "value": 1}], scope_tenant=False)
check(mt2["scope_violations"] >= 1, "T7 tenant alarmı tenant_id taşımazsa → cross-tenant sızıntı ihlali")
mp = run([{"rule": "E2EP95LatencyHigh", "value": 1600}])
check(mp["scope_violations"] == 0, "T7 platform alarmı tenant_id taşımaz → ihlal değil")

# T8 — flap kontrolü: for_s>0 geçici blip bastırır; for_s=0 güvenlik anında
mf = run([{"rule": "ToolErrorRateHigh", "value": 1, "transient": True}], debounce=False)
check(mf["flap_violations"] >= 1, "T8 transient + debounce kapalı → flap ihlali")
mfok = run([{"rule": "ToolErrorRateHigh", "value": 1, "transient": True}])
check(mfok["flap_violations"] == 0, "T8 debounce açık → geçici blip bastırılır")
msec = run([{"rule": "InfoLeakDetected", "value": 1, "transient": True}], debounce=False)
check(msec["flap_violations"] == 0, "T8 for_s=0 güvenlik alarmı transient olsa bile flap değil")

# T9 — dedup: aynı (alertname, tenant_id) tek alarma daraltılır
md = run([{"rule": "ConsentSkipDetected", "value": 1}, {"rule": "ConsentSkipDetected", "value": 2}], dedup=False)
check(md["dedup_violations"] >= 1, "T9 dedup kapalı → çift alarm ihlali")
mdok = run([{"rule": "ConsentSkipDetected", "value": 1}, {"rule": "ConsentSkipDetected", "value": 2}])
check(mdok["dedup_violations"] == 0, "T9 dedup açık → daraltılır")

# T10 — routing: severity→kanal + scope→kitle; unrouted yok
m10 = run([{"rule": "E2EP95LatencyHigh", "value": 1600}, {"rule": "ConsentSkipDetected", "value": 1}])
check(m10["routing_violations"] == 0, "T10 her alarm yönlendirildi (unrouted=0)")
m10b = run([{"rule": "E2EP95LatencyHigh", "value": 1600}], route_severity=False)
check(m10b["routing_violations"] >= 1, "T10 route_severity kapalı → unrouted ihlali")

# T-determinizm
a = run([{"rule": "E2EP95LatencyHigh", "value": 1600}])
b = run([{"rule": "E2EP95LatencyHigh", "value": 1600}])
check(a == b, "T-det: aynı sinyal aynı sonuç (saf; random yok)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
