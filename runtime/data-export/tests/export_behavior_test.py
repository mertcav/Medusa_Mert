#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_behavior_test.py — WBS 14.2.8 dashboard + ham veri export motoru davranış kapısı (T1–T11).

Probe selftest'ten BAĞIMSIZ davranış kanıtı: DataExportEngine'in FR-ANA-011 dashboard + ham veri export'unu —
export bütünlüğü (satır sayısı + deterministik sıra + sha256 checksum) + export-dashboard tutarlılığı (yeniden
agregasyon == tile) + format/sütun katalog BİREBİR + PII redaksiyon + analytics:read yetki + tenant izolasyon +
WORM audit + idempotency disiplinini — gerçek export senaryolarında uyguladığını doğrular. stdlib-only,
credential-free, deterministik.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

import export_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
OLAP = P._load_sibling_spec("analytics", "olap-spec.json")
CTX = {"tenant_id": "t_acme", "region": "eu-west-1", "correlation_id": "corr-001"}
PROF = {"name": "eu-standard", "region": "eu-west-1", "schema_version": 1, "default_format": "csv"}

results = []


def check(ok, label):
    results.append((bool(ok), label))


def run(jobs, **pol):
    p = P._full_pol()
    p.update(pol)
    return P.export_request({"request": {"exports": jobs}}, SPEC, dict(PROF), CTX, p, olap=OLAP)


def job(**over):
    return P._job(**over)


def gates_ok(m):
    return all(ok for ok, _ in P.evaluate(SPEC, m))


# T1 — happy path: yetkili + tutarlı export → tüm kapı geçer
m = run([job()])
check(m["fidelity_violations"] == 0 and gates_ok(m), "T1 yetkili + tutarlı export → tüm HARD kapı (G1–G9) geçer")
check(m["derived"]["exports"][0]["manifest"]["row_count"] == 3, "T1 manifest row_count == 3 (sorgulanan satır)")

# T2 — determinizm + deterministik sıralama: girdi sırası fark etmez, checksum aynı (I3/I11)
shuffled = list(reversed(P._rows_daily()))
ck1 = run([job()])["derived"]["exports"][0]["manifest"]["checksum"]
ck2 = run([job(rows=shuffled)])["derived"]["exports"][0]["manifest"]["checksum"]
check(ck1 == ck2 and len(ck1) == 64, "T2 deterministik sıralama → aynı sha256 checksum (girdi sırası bağımsız)")

# T3 — EXPORT BÜTÜNLÜĞÜ (BİRİNCİL): satır düşme/sorgu uyumsuzluğu → G1 eler
check(run([job()], preserve_all_rows=False)["fidelity_violations"] >= 1,
      "T3 preserve_all_rows kapalı: benzersiz satır düşer → G1 bütünlük eler (BİRİNCİL)")
jbad = job(); jbad["expected_row_count"] = 7
check(run([jbad])["fidelity_violations"] >= 1, "T3 sorgulanan(7) ≠ export(3) → G1 bütünlük eler")

# T4 — at-least-once dedup: çift satır DARALTILIR (replay-safe), bütünlük korunur (I1)
rows = P._rows_daily() + [P._rows_daily()[0]]   # 2026-06-01 tekrar
md = run([job(rows=rows)])
check(md["derived"]["rows_exported"] == 3 and md["fidelity_violations"] == 0,
      "T4 at-least-once çift satır dedup_key ile daraltılır → 3 benzersiz (replay-safe, bütünlük korunur)")

# T5 — EXPORT-DASHBOARD TUTARLILIĞI (SR-ANA-011): yeniden-agregasyon == tile
jt = job(); jt["dashboard"]["tiles"][0]["value"] = 301
check(run([jt])["reconciliation_violations"] >= 1,
      "T5 dashboard tile (total_calls=301) export'la uzlaşmıyor → G2 uzlaşma eler ('tutarlıdır')")
check(run([job()])["reconciliation_violations"] == 0, "T5 doğru tile → export yeniden-agregasyonu uzlaşır")
# partition: contained + transferred = 1.0 (handled paydası)
jpart = job()
jpart["dashboard"]["tiles"] = [
    {"name": "c", "agg": "rate", "num_column": "contained_calls", "den_column": "calls", "value": 0.7, "group": "o", "tol": 0.01},
    {"name": "t", "agg": "rate", "num_column": "transferred_calls", "den_column": "calls", "value": 0.3, "group": "o", "tol": 0.01},
]
check(run([jpart])["reconciliation_violations"] == 0, "T5 partition contained(0.70)+transferred(0.30)=1.0 → uzlaşır")

# T6 — format/şema (G3, OLAP non-circular)
check(P._raises(lambda: run([job(source="nope")])), "T6 bilinmeyen kaynak → reddedilir (INVALID_REQUEST)")
check(P._raises(lambda: run([job(format="parquet")])), "T6 desteklenmeyen format → reddedilir")
jcol = job(); jcol["columns"] = jcol["columns"] + ["bogus_col"]
check(run([jcol])["format_violations"] >= 1, "T6 kaynak OLAP kataloğunda olmayan sütun → G3 eler (BİREBİR)")

# T7 — PII redaksiyon (G4): export YALNIZ redaksiyonlu/agregat
jpii = job(); jpii["columns"] = jpii["columns"] + ["recording_uri"]
check(run([jpii])["pii_violations"] >= 1, "T7 recording_uri sütunu (kayıt URI) → G4 PII eler")
jval = job(); jval["rows"][0]["agent_id"] = "user@example.com"
check(run([jval])["pii_violations"] >= 1, "T7 cell DEĞERİnde e-posta → G4 PII eler")

# T8 — YETKİ (İKİNCİL çekirdek, G5)
check(run([job(actor={"role": "human_agent", "permissions": ["analytics:read"]})])["authz_violations"] >= 1,
      "T8 human_agent (A-14 erişim YOK) → G5 yetki eler")
check(run([job(actor={"role": "platform_owner", "permissions": ["analytics:read"]})])["authz_violations"] >= 1,
      "T8 platform L0 (altın kural FR-IAM-008) → G5 yetki eler")
check(run([job(actor={"role": "operations_manager", "permissions": ["calls:read"]})])["authz_violations"] >= 1,
      "T8 analytics:read izni yok → G5 yetki eler")
check(run([job()])["authz_violations"] == 0, "T8 yetkili (operations_manager + analytics:read) → geçer")

# T9 — izolasyon (G6) + residency
jiso = job(); jiso["rows"][0]["tenant_id"] = "t_other"
check(run([jiso])["isolation_violations"] >= 1, "T9 cross-tenant satır → G6 izolasyon eler (FR-TEN-002)")
jres = job(); jres["rows"][0]["home_region"] = "us-east-1"
check(run([jres])["isolation_violations"] >= 1, "T9 home-region dışı satır → G6 izolasyon eler (NFR 10.7)")

# T10 — audit (G7): SESSİZ export yok + içerik taşımaz
check(run([job()], audit=False)["audit_violations"] >= 1, "T10 audit kapalı: SESSİZ export → G7 eler")
arec = run([job()])["derived"]["exports"][0]["audit"]
check(arec and arec["action_code"] == "data_export" and "row_count" in arec and "report_id" in arec,
      "T10 audit izi data_export + row_count + report_id (kim/ne zaman/hangi rapor)")

# T11 — idempotency (G8) + non-blocking (G9)
check(run([job(), job()])["idempotency_violations"] >= 1, "T11 duplicate export (aynı dedup_key) → G8 eler")
check(run([job()], non_blocking=False)["blocking_violations"] >= 1, "T11 non_blocking kapalı → G9 eler (FR-RES-011)")
# iki FARKLI rapor idempotency ihlali değil
check(run([job(report_id="r1"), job(report_id="r2")])["idempotency_violations"] == 0,
      "T11 iki farklı report_id → idempotency ihlali YOK (batch export geçerli)")

passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, label in results:
    print("  %s %s" % ("✓" if ok else "✗", label))
print("behavior: %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
