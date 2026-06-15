#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.2.2 — Token trimming davranış (kara-kutu) regresyon testleri T1–T10.

context_trim_probe motorunun GÖZLEMLENEBİLİR davranışını probe'un kendi selftest'inden BAĞIMSIZ doğrular
(ikinci bir göz). 6.2.1 RetrievalEngine TÜKETİLİR (yeniden retrieval/embed/rerank YOK). Stdlib-only, determinist.

Çalıştır: python3 tests/context_trim_behavior_test.py   → çıkış 0 (tüm testler) / 1 (başarısız)
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import context_trim_probe as P  # noqa: E402

DIV = 4


def _results(specs):
    """specs: [(doc_id, content)] → 6.2.1 RankedResult sözleşmeli liste."""
    out = []
    for i, (doc, content) in enumerate(specs):
        out.append({
            "result_key": "t-a:kb-1|%s" % doc, "rank": i, "document_id": doc,
            "doc_logical_key": "doc:%s" % doc, "namespace": "t-a:kb-1", "tenant_id": "t-a",
            "kb_id": "kb-1", "version_no": 1, "chunk_no": 0, "source_uri": "u://%s" % doc,
            "title": doc, "content": content, "char_count": len(content),
            "token_estimate": max(1, len(content) // DIV),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "classification": "public", "score": 0.9 - 0.05 * i, "rerank_score": None,
        })
    return out


def _budget(**kw):
    b = {"context_token_budget": 1000, "rag_token_budget": 1000, "allow_truncation": True,
         "min_truncation_tokens": 5, "token_estimate_divisor": DIV}
    b.update(kw)
    return b


RESULTS = _results([("d0", "a" * 200), ("d1", "b" * 200), ("d2", "c" * 200), ("d3", "d" * 200)])  # 50 token/chunk


def t1_cap_never_exceeded():
    """T1 — Her bütçede total_context_tokens ≤ context_token_budget ve rag_used ≤ rag_available (B1/B5)."""
    for rag in (10, 30, 55, 100, 130, 500, 5000):
        tr = P.ContextTrimmer(_budget(context_token_budget=10000, rag_token_budget=rag))
        t = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "cap%d" % rag)
        b = t["budget"]
        assert b["rag_used"] <= b["rag_available"], "rag_used aşıyor rag=%d" % rag
        assert b["total_context_tokens"] <= b["context_token_budget"], "total aşıyor rag=%d" % rag
        assert b["rag_available"] <= b["rag_token_budget"], "available > budget rag=%d" % rag
    return True


def t2_rank_prefix_kept():
    """T2 — kept girdinin contiguous rank prefix'i; dropped = suffix (alaka-önce)."""
    tr = P.ContextTrimmer(_budget(rag_token_budget=120))  # ~2 chunk
    t = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "prefix")
    kept_ranks = [k["rank"] for k in t["kept"]]
    assert kept_ranks == list(range(len(kept_ranks))), "kept rank prefix değil: %s" % kept_ranks
    drop_ranks = [d["rank"] for d in t["dropped"]]
    assert all(dr >= len(kept_ranks) for dr in drop_ranks), "dropped suffix değil"
    return True


def t3_truncation_is_prefix():
    """T3 — truncate edilen content orijinalin ÖN-EKİ (uydurma yok) + truncated=true + token≤orijinal (B4)."""
    tr = P.ContextTrimmer(_budget(rag_token_budget=70, min_truncation_tokens=5))  # 1 tam + kuyruk
    t = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "trunc")
    trunc = [k for k in t["kept"] if k["truncated"]]
    assert trunc, "truncation beklenirdi"
    for k in trunc:
        src = next(r for r in RESULTS if r["result_key"] == k["result_key"])
        assert src["content"].startswith(k["content"]), "truncate prefix değil"
        assert k["context_token_estimate"] <= k["original_token_estimate"], "token orijinali aşıyor"
        assert k["context_content_hash"] == hashlib.sha256(k["content"].encode("utf-8")).hexdigest()
    return True


def t4_citation_identity_preserved():
    """T4 — kept content_hash ORİJİNAL chunk hash'i (truncate olsa bile) → 6.2.3 kaynak kimliği (B3)."""
    tr = P.ContextTrimmer(_budget(rag_token_budget=70, min_truncation_tokens=5))
    t = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "cite")
    for k in t["kept"]:
        src = next(r for r in RESULTS if r["result_key"] == k["result_key"])
        assert k["content_hash"] == src["content_hash"], "content_hash orijinal değil"
        for f in P.CITATION_FIELDS:
            assert f in k, "citation alanı eksik: %s" % f
        if k["truncated"]:
            assert k["context_content_hash"] != k["content_hash"], "truncate'te bağlam hash ayrı olmalı"
    return True


def t5_no_truncate_drops():
    """T5 — allow_truncation=false: sığmayan chunk truncate edilmez, DÜŞÜRÜLÜR (tam chunk bütünlüğü)."""
    tr = P.ContextTrimmer(_budget(rag_token_budget=120, allow_truncation=False))  # 2 tam (100) sığar, 3. düşer
    t = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "notrunc")
    assert t["truncated_any"] is False, "truncation olmamalı"
    assert t["dropped_count"] >= 1, "en az 1 düşmeli"
    assert all(not k["truncated"] for k in t["kept"]), "kept'te truncate olmamalı"
    return True


def t6_budget_exhausted_grounding():
    """T6 — bütçe en üst chunk'ı sığdıramaz + truncate kapalı → kept=0, grounded=false, BUDGET_EXHAUSTED (B7)."""
    tr = P.ContextTrimmer(_budget(rag_token_budget=20, allow_truncation=False))  # 20 < 50
    t = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "exhaust")
    assert t["kept_count"] == 0 and t["grounded"] is False, "exhaust grounded false beklenir"
    assert t["reason"] == P.REASON_BUDGET_EXHAUSTED, "reason BUDGET_EXHAUSTED beklenir"
    assert t["budget"]["rag_used"] == 0 and t["budget"]["total_context_tokens"] <= t["budget"]["context_token_budget"]
    return True


def t7_reserved_squeeze():
    """T7 — FR-RES-010: reserved_total (history/özet) arttıkça rag_available düşer; total tavan altı kalır (B9)."""
    tr = P.ContextTrimmer(_budget(context_token_budget=200, rag_token_budget=1000))
    small = tr.trim(RESULTS, [{"name": "h", "token_estimate": 20}], {"tenant_id": "t-a"}, "s")
    big = tr.trim(RESULTS, [{"name": "h", "token_estimate": 150}], {"tenant_id": "t-a"}, "b")
    assert small["budget"]["rag_available"] > big["budget"]["rag_available"], "history↑ → rag_available↓ değil"
    assert big["budget"]["total_context_tokens"] <= 200, "büyük history total tavanı aşıyor"
    assert big["budget"]["rag_used"] <= small["budget"]["rag_used"], "büyük history daha çok rag kullanıyor"
    return True


def t8_monotonicity():
    """T8 — rag bütçe ARTTIKÇA kept token AZALMAZ (sağlık özelliği, B9)."""
    used = []
    for rag in (30, 60, 120, 240, 1000):
        tr = P.ContextTrimmer(_budget(rag_token_budget=rag))
        used.append(tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "m%d" % rag)["budget"]["rag_used"])
    assert all(used[i] <= used[i + 1] for i in range(len(used) - 1)), "monoton değil: %s" % used
    return True


def t9_determinism():
    """T9 — aynı girdi → birebir aynı çıktı (B6)."""
    tr = P.ContextTrimmer(_budget(rag_token_budget=70, min_truncation_tokens=5))
    a = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "d")
    b = tr.trim(RESULTS, [], {"tenant_id": "t-a"}, "d")
    assert [k["context_content_hash"] for k in a["kept"]] == [k["context_content_hash"] for k in b["kept"]]
    assert (a["kept_count"], a["grounded"], a["reason"], a["truncated_any"]) == \
           (b["kept_count"], b["grounded"], b["reason"], b["truncated_any"])
    return True


def t10_robust_fail_closed():
    """T10 — geçersiz girdi → structured TrimError (çökme yok); audit no-log (B8/B10)."""
    bad = P.ContextTrimmer({"context_token_budget": 0, "rag_token_budget": 100})
    assert bad.trim(RESULTS, [], {}, "x")["error_class"] == "MISSING_BUDGET_CONFIG"
    tr = P.ContextTrimmer(_budget())
    assert tr.trim(RESULTS, [{"name": "h", "token_estimate": -1}], {}, "x")["error_class"] == "INVALID_RESERVED"
    assert tr.trim([{"result_key": "k", "rank": 0, "token_estimate": 5}], [], {}, "x")["error_class"] \
        == "INVALID_RANKED_INPUT"
    assert all(a.get("no_log") for a in tr.audit) and "content" not in {k for a in tr.audit for k in a}
    return True


TESTS = [t1_cap_never_exceeded, t2_rank_prefix_kept, t3_truncation_is_prefix, t4_citation_identity_preserved,
         t5_no_truncate_drops, t6_budget_exhausted_grounding, t7_reserved_squeeze, t8_monotonicity,
         t9_determinism, t10_robust_fail_closed]


def main():
    fails = []
    for t in TESTS:
        try:
            t()
            print("  🟢 %s" % t.__name__)
        except AssertionError as e:
            fails.append((t.__name__, str(e)))
            print("  🔴 %s — %s" % (t.__name__, e))
        except Exception as e:
            fails.append((t.__name__, "EXC %s" % type(e).__name__))
            print("  🔴 %s — EXC %s: %s" % (t.__name__, type(e).__name__, e))
    print("\nbehavior: %d/%d test geçti" % (len(TESTS) - len(fails), len(TESTS)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
