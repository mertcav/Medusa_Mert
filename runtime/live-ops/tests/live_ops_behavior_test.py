#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_ops_behavior_test.py — WBS 14.1.6 Real-time Operations View Composer davranış kapısı (T1–T10).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: LiveOpsViewComposer'ın gerçek zamanlı op ekranı view modeli
+ ≤60sn tazelik (FR-ANA-012) + tenant-scope izolasyon + tile-boyut kardinalite/PII + Tier A içerik +
refresh + drill-down/exemplar disiplinini gerçek anlık-görüntü senaryolarında uyguladığını doğrular.
stdlib-only, credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import live_ops_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
P._inject_required(SPEC)
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1",
        "ingest_lag_s": 10, "refresh_interval_s": 30, "render_lag_s": 5}
VIEW_T = {"scope": "tenant", "tenant_id": "t_acme"}
VIEW_P = {"scope": "platform"}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(view, signals, profile=None, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.compose_view({"view_request": view, "signals": signals}, SPEC, profile or PROF, CTX, p)


# T1 — kapsam: 7/7 operasyonel grup + 15/15 grafana metrik (0.4.7'den türetilir, non-circular)
m = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}])
check(m["derived"]["required_groups"] == 7 and m["derived"]["active_groups"] == 7, "T1 kapsam 7/7 grup (BRD §15/SAD §17.1)")
check(m["derived"]["surfaced_metrics"] == 15 and m["derived"]["required_metrics"] == 15, "T1 15/15 grafana metrik yüzeylenir")
check(m["coverage_missing"] == 0, "T1 coverage_missing=0")

# T2 — ≤60sn tazelik: standart profilde her tile veri tazeliği ≤ 60s (FR-ANA-012)
check(m["freshness_violations"] == 0, "T2 tazelik ihlali=0 (FR-ANA-012)")
check(m["derived"]["max_freshness_s"] <= 60, "T2 max tazelik ≤ 60s")
check(m["derived"]["max_freshness_s"] == 55, "T2 max tazelik = 45 ek-yük + 10 query_step = 55s (en geniş query_step)")

# T3 — tile komposizyonu: tüm tile'lar kompoze edilir (8 tile, sinyal olsun olmasın)
check(m["composed"] == 8, "T3 8 tile kompoze (sinyal değeri olmasa da pano render eder)")

# T4 — tazelik bütçe aşımı: yavaş altyapı → > 60s eler
slow = {"name": "s", "region": "eu-west-1", "ingest_lag_s": 25, "refresh_interval_s": 30, "render_lag_s": 10}
ms = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], profile=slow)
check(ms["freshness_violations"] >= 1, "T4 yavaş profil (65s ek-yük + 10 query = 75) → tazelik eler")

# T5 — kardinalite: kimlik tile boyutu OLAMAZ
m5 = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], enforce_cardinality=False)
check(m5["cardinality_violations"] >= 1, "T5 correlation_id tile boyutu → kardinalite eler")
check(m["cardinality_violations"] == 0, "T5 temiz görünümde kimlik tile boyutu yok")

# T6 — PII: tile boyutunda PII anahtarı OLAMAZ (FR-REC-004)
m6 = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], enforce_pii=False)
check(m6["pii_violations"] >= 1, "T6 phone_number tile boyutu → PII eler (FR-REC-004)")

# T7 — Tier A içerik: gerçek zamanlı ekran ham içerik (transkript/kayıt) yüzeylemez
m7 = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], enforce_tier_a=False)
check(m7["content_violations"] >= 1, "T7 transcript_text tile'da → içerik eler (Tier A; içerik → A-12)")
check(m["content_violations"] == 0, "T7 temiz görünümde ham içerik yok (Tier A)")

# T8 — tenant-scope izolasyon: tenant görünümü tenant_id filtresi taşır (cross-tenant yok)
check(m["scope_violations"] == 0, "T8 tenant görünümü tenant_id filtresi taşır (izolasyon)")
m8 = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], scope_tenant=False)
check(m8["scope_violations"] >= 1, "T8 scope_tenant kapalı: tenant görünümü tenant_id taşımaz → cross-tenant eler")
# platform (L0) görünümü agregat → tenant_id taşımaması sızıntı değil (altın kural: L0 metrik görür)
mp = run(VIEW_P, [{"tile": "tile_e2e_latency", "value": 900}])
check(mp["scope_violations"] == 0, "T8 platform-scope agregat görünüm tenant_id taşımaz → ihlal değil (Tier A)")
check(mp["content_violations"] == 0, "T8 platform görünümünde de ham içerik yasak (altın kural — L0 içerik görmez)")

# T9 — refresh disiplini: auto-refresh açık + refresh ≤ bütçe
check(m["refresh_violations"] == 0, "T9 auto-refresh açık + refresh ≤ bütçe (G7)")
m9 = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], auto_refresh=False)
check(m9["refresh_violations"] >= 1, "T9 auto_refresh kapalı → durağan pano → refresh eler")

# T10 — drill-down exemplar + reddetme (determinizm + I11)
m10 = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}], bind_exemplar=False)
check(m10["drilldown_violations"] >= 1, "T10 bind_exemplar kapalı: kimlik tile boyutu drill → G8 eler")
a = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}])
b = run(VIEW_T, [{"tile": "tile_e2e_latency", "value": 900}])
check(a == b, "T10 determinizm: aynı anlık-görüntü aynı sonuç (saf; random yok)")
try:
    P.compose_view({"view_request": VIEW_T, "signals": [{"tile": "tile_nope", "value": 1}]}, SPEC, PROF, CTX, P._full_pol())
    check(False, "T10 bilinmeyen tile reddedilmeli")
except P.ViewError:
    check(True, "T10 bilinmeyen tile → reddedilir (I11)")


passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
