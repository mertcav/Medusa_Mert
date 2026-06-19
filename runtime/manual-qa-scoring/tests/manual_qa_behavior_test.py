#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
manual_qa_behavior_test.py — WBS 14.2.6 davranış kapısı (T1–T12).

Probe'un statik validate + selftest'inin ÖTESİNDE, ManualQaScoringEngine'in uçtan uca davranışını
sample'lar üzerinden kanıtlar: happy-path/degraded-input KABUL, degraded RED; FR-ANA-009 (skor+açıklama),
yetki (qa:score / altın kural), PII sınırı (açıklama METNİ OLAP'a çıkmaz), idempotency/coexistence.

stdlib-only, credential-free. Repo kökünden veya bu dizinden çalışır.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import manual_qa_probe as P  # noqa: E402

SPEC = P._load(P.SPEC_PATH)
ENGINE = P.ManualQaScoringEngine(SPEC)

results = []


def chk(cond, label):
    results.append((bool(cond), label))


def _load_sample(name):
    return P._load(os.path.join(ROOT, "samples", name))


def _run_sample(name):
    sample = _load_sample(name)
    acc, rej = [], []
    rows = []
    for i, sub in enumerate(sample["submissions"]):
        ok, row, audit, errs = ENGINE.process(sub)
        (acc if ok else rej).append(i)
        if ok:
            rows.append(row)
    return sample, acc, rej, rows


# T1 — happy-path: hepsi kabul, expect uyumlu
s, acc, rej, rows = _run_sample("manual-qa-happy-path.json")
chk(acc == s["expect"]["accept"] and rej == s["expect"]["reject"], "T1 happy-path expect uyumlu (hepsi kabul)")
chk(all(r["eval_type"] == "manual" for r in rows), "T1 tüm satır eval_type=manual")
chk(all(0.0 <= r["human_score"] <= 1.0 for r in rows), "T1 human_score ∈[0,1] normalize")

# T2 — happy-path: OLAP satırında AÇIKLAMA METNİ / PII anahtarı YOK
leak = any(k in r for r in rows for k in (P.COMMENT_TEXT_KEYS + P.PII_KEYS))
chk(not leak, "T2 OLAP projeksiyonunda METİN/PII anahtarı yok (yalnız human_*/role)")
chk(all(set(r.keys()) >= set(P.OLAP_MANUAL_FIELDS) for r in rows), "T2 OLAP alanları BİREBİR mevcut")

# T3 — degraded-input: hepsi kabul (kısmi ama geçerli)
s2, acc2, rej2, rows2 = _run_sample("manual-qa-degraded-input.json")
chk(acc2 == s2["expect"]["accept"] and not rej2, "T3 degraded-input hepsi kabul")

# T4 — degraded-input: aynı çağrıya 2 farklı evaluator → 2 ayrı satır (çoklu manuel/çağrı)
same_call = [r for r in rows2 if r["call_id"] == "call-3001"]
chk(len(same_call) == 2 and {r["evaluator_id"] for r in same_call} == {"qa-001", "qa-002"},
    "T4 çoklu manuel skor/çağrı (farklı evaluator → ayrı satır)")

# T5 — degraded: hepsi RED, expect uyumlu (kabul=0)
s3, acc3, rej3, rows3 = _run_sample("manual-qa-degraded.json")
chk(not acc3 and rej3 == s3["expect"]["reject"], "T5 degraded hepsi RED (expect uyumlu)")

# T6 — degraded: yetkisiz + L0 + cross-tenant AUTH'a eşlenir
auth_cases = []
for i in (0, 1, 2):
    _, _, _, errs = ENGINE.process(s3["submissions"][i])
    auth_cases.append(any(e[1] == "AUTH" for e in errs))
chk(all(auth_cases), "T6 yetkisiz/L0/cross-tenant → AUTH")

# T7 — idempotency: aynı (tenant,call,evaluator,schema) tekrarı dedup'a tabi (gate G8)
dup = [
    {"tenant_id": "t", "call_id": "c", "status": "completed", "schema_version": 1, "human_score": 4,
     "submitter": {"evaluator_id": "qa-1", "evaluator_role": "qa_analyst", "permissions": ["qa:score"], "tenant_id": "t"}},
    {"tenant_id": "t", "call_id": "c", "status": "completed", "schema_version": 1, "human_score": 5,
     "submitter": {"evaluator_id": "qa-1", "evaluator_role": "qa_analyst", "permissions": ["qa:score"], "tenant_id": "t"}},
]
seen = {}
for sub in dup:
    ok, row, _, _ = ENGINE.process(sub)
    if ok:
        key = (row["tenant_id"], row["call_id"], row["evaluator_id"], row["schema_version"])
        seen[key] = seen.get(key, 0) + 1
chk(any(v > 1 for v in seen.values()), "T7 aynı dedup_key tekrarı tespit edilebilir (supersede gerekli)")

# T8 — audit izi her kabul için üretilir + action_code doğru
ok, row, audit, _ = ENGINE.process(s["submissions"][0])
chk(ok and audit and audit["topic"] == "governance.audit.v1" and audit["action_code"] == "manual_score_added",
    "T8 kabul→governance.audit.v1 (manual_score_added) izi")
chk(audit and "comment" not in audit and not any(P.PII_VALUE_RE.search(str(v)) for v in audit.values()),
    "T8 audit izinde METİN/PII yok (yalnız kimlik+aksiyon)")

# T9 — coexistence: spec auto_score (otomatik) ≠ human_score (manuel) ayrı sütun
cx = SPEC["coexistence"]
chk(cx["separate_olap_columns"]["automatic"] == "auto_score" and
    cx["separate_olap_columns"]["manual"] == "human_score" and
    cx["manual_does_not_overwrite_automatic"], "T9 manuel/otomatik ayrı sütun, overwrite yok")

# T10 — normalize sınır: 1→0.0, 5→1.0, 3→0.5
norms = {sc: ENGINE._normalize(sc) for sc in (1, 3, 5)}
chk(norms[1] == 0.0 and norms[3] == 0.5 and norms[5] == 1.0, "T10 normalize 1/3/5 → 0.0/0.5/1.0")

# T11 — score komutu happy-path → çıkış kodu 0 (kapı geçer)
rc_happy = P.cmd_score([os.path.join(ROOT, "samples", "manual-qa-happy-path.json")])
chk(rc_happy == 0, "T11 score happy-path → exit 0 (kapı geçer)")

# T12 — score komutu degraded → çıkış kodu 0 (hepsi RED, kabul=0 → kapı geçer; expect reject uyumlu)
rc_deg = P.cmd_score([os.path.join(ROOT, "samples", "manual-qa-degraded.json")])
chk(rc_deg == 0, "T12 score degraded → exit 0 (hepsi RED, kabul yok → kapı geçer)")


passed = sum(1 for ok, _ in results if ok)
total = len(results)
for ok, lbl in results:
    print("  %s %s" % ("🟢" if ok else "🔴", lbl))
print("\n[behavior] %d/%d PASS" % (passed, total))
sys.exit(0 if passed == total else 1)
