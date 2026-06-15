#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.1.5 — Bayatlama/içerik TTL davranış testleri (T1–T10). Stdlib-only, credential-free, deterministik.
Probe'un selftest'inden BAĞIMSIZ siyah-kutu davranış kontrolü (regresyon kapısı). Çalıştır:
    python3 tests/content_ttl_behavior_test.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import content_ttl_probe as P  # noqa: E402

_fails = []
DAY = P.DAY
NOW = 1_000_000_000

POL = {
    "max_age_by_classification": {"public": 180 * DAY, "internal": 90 * DAY,
                                  "confidential": 30 * DAY, "restricted": 14 * DAY},
    "default_max_age": 90 * DAY, "expire_after_factor": 2.0, "hard_expiry_enabled": True,
    "require_freshness": True, "respect_source_drift": True, "grace_period": 0,
}


def check(cond, msg):
    if not cond:
        _fails.append(msg)


def doc(**kw):
    base = {"document_id": "d", "tenant_id": "t-a", "kb_id": "kb-1", "version_no": 1,
            "classification": "internal", "indexed_at": NOW - 1 * DAY}
    base.update(kw)
    return base


def mk():
    return P.StalenessMarker(POL, NOW)


# T1 — FRESH: TTL içinde → fresh, işaretlenmez (G2).
def t1():
    r = mk().mark(doc(indexed_at=NOW - 10 * DAY))
    check(r["state"] == "fresh" and not r["marked"], "T1 fresh within ttl")


# T2 — STALE by age (G1 başlık, SR-KB-008/TC-KB-008): soft deadline geçti → stale TTL_EXCEEDED + marked.
def t2():
    r = mk().mark(doc(indexed_at=NOW - 100 * DAY))
    check(r["state"] == "stale" and r["reason"] == "TTL_EXCEEDED" and r["marked"], "T2 stale ttl exceeded")


# T3 — EXPIRED (G6): hard deadline geçti → expired HARD_EXPIRED; monoton (soft da geçmiş).
def t3():
    r = mk().mark(doc(indexed_at=NOW - 400 * DAY))
    check(r["state"] == "expired" and r["reason"] == "HARD_EXPIRED", "T3 hard expired")
    check(r["now"] >= r["soft_deadline"], "T3b expired ⇒ soft geçmiş (monoton)")


# T4 — EXPLICIT precedence (G3): content_ttl_at policy'yi ezer (iki yön).
def t4():
    r = mk().mark(doc(indexed_at=NOW - 200 * DAY, content_ttl_at=NOW + 30 * DAY))
    check(r["state"] == "fresh" and r["deadline_source"] == "explicit", "T4 açık TTL gelecek → fresh")
    r = mk().mark(doc(indexed_at=NOW - 1 * DAY, content_ttl_at=NOW - 1))
    check(r["state"] == "stale" and r["reason"] == "EXPLICIT_TTL_PASSED", "T4b açık TTL geçti → stale")


# T5 — SOURCE DRIFT (G4): kaynak indeksten yeni → stale; eski → fresh; hard-expired şiddetli kazanır.
def t5():
    r = mk().mark(doc(indexed_at=NOW - 5 * DAY, source_last_modified=NOW - 1 * DAY))
    check(r["state"] == "stale" and r["reason"] == "SOURCE_DRIFT", "T5 drift stale")
    r = mk().mark(doc(indexed_at=NOW - 5 * DAY, source_last_modified=NOW - 6 * DAY))
    check(r["state"] == "fresh", "T5b kaynak eski → fresh")
    r = mk().mark(doc(indexed_at=NOW - 400 * DAY, source_last_modified=NOW - 1 * DAY))
    check(r["state"] == "expired", "T5c drift+hard → expired")


# T6 — PINNED (G5): yaştan/drift'ten bağımsız pinned, asla bayat.
def t6():
    r = mk().mark(doc(indexed_at=NOW - 1000 * DAY, pinned=True))
    check(r["state"] == "pinned" and not r["marked"], "T6 pinned never expires")
    r = mk().mark(doc(indexed_at=NOW - 1000 * DAY, source_last_modified=NOW, pinned=True))
    check(r["state"] == "pinned", "T6b pinned drift muaf")


# T7 — FAIL-CLOSED missing (G9): atası yok+require → stale; require kapalı → NO_TTL_POLICY fresh.
def t7():
    r = mk().mark({"document_id": "x", "tenant_id": "t-a", "classification": "internal"})
    check(r["state"] == "stale" and r["reason"] == "MISSING_FRESHNESS", "T7 missing → stale")
    m_open = P.StalenessMarker(dict(POL, require_freshness=False, default_max_age=None,
                                    max_age_by_classification={}), NOW)
    r = m_open.mark({"document_id": "x", "tenant_id": "t-a", "classification": "internal"})
    check(r["state"] == "fresh" and r["reason"] == "NO_TTL_POLICY", "T7b require kapalı → fresh")


# T8 — MALFORMED (G9/G10): bozuk timestamp exception KAÇMAZ → muhafazakâr stale.
def t8():
    r = mk().mark(doc(indexed_at="bozuk"))
    check(r["state"] == "stale" and r["reason"] == "MALFORMED_METADATA", "T8 malformed → fail-closed stale")


# T9 — DETERMINISM (G7) + TENANT SCOPE (G8).
def t9():
    docs = [doc(document_id="a", indexed_at=NOW - 100 * DAY),
            doc(document_id="b", tenant_id="t-b", indexed_at=NOW - 100 * DAY)]
    a = P.StalenessMarker(POL, NOW).scan(docs)
    b = P.StalenessMarker(POL, NOW).scan(docs)
    check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "T9 determinizm birebir")
    recs = P.StalenessMarker(POL, NOW).scan(docs, tenant_filter="t-a")
    check(len(recs) == 1 and recs[0]["tenant_id"] == "t-a", "T9b tenant scope")


# T10 — 6.1.3 entegrasyon (consumes) + audit (G10): aktif doküman provenance + ham içerik/PII yok.
def t10():
    pipe = P.index_inputs([
        {"source_id": "kb-old", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "internal",
         "inline_text": "Eski surum politika metni yeterince uzundur."},
        {"source_id": "kb-new", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "internal",
         "inline_text": "Guncel surum metni yeterince uzundur."},
    ])
    docs = P.freshness_from_index(pipe, {"kb-old": {"indexed_at": NOW - 200 * DAY},
                                         "kb-new": {"indexed_at": NOW - 3 * DAY}})
    m = P.StalenessMarker(POL, NOW)
    recs = m.scan(docs)
    by = {r["document_id"]: r for r in recs}
    check(by["kb-old"]["marked"] and by["kb-new"]["state"] == "fresh",
          "T10 6.1.3 aktif doküman: eski stale, yeni fresh (SR-KB-008)")
    check(all(r["version_no"] == 1 for r in recs), "T10b version_no provenance")
    blob = json.dumps(m.audit, ensure_ascii=False)
    check("content" not in {k for a in m.audit for k in a} and not P.EMAIL_RE.search(blob),
          "T10c audit ham içerik/PII yok")


def main():
    for fn in [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10]:
        fn()
    if _fails:
        print("FAIL: %d kontrol başarısız" % len(_fails))
        for m in _fails:
            print("  ✗ %s" % m)
        return 1
    print("OK: 10 davranış grubu geçti")
    return 0


if __name__ == "__main__":
    sys.exit(main())
