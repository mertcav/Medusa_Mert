#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.1.3 — Index pipeline davranış testleri (T1–T10). Stdlib-only, credential-free, deterministik.
Probe'un selftest'inden BAĞIMSIZ siyah-kutu davranış kontrolü (regresyon kapısı). Çalıştır:
    python3 tests/index_pipeline_behavior_test.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import index_pipeline_probe as P  # noqa: E402

_fails = []


def check(cond, msg):
    if not cond:
        _fails.append(msg)


def nd(**kw):
    base = dict(tenant_id="t-a", kb_id="kb-1", text="alpha beta gamma",
                blocks=[{"type": "paragraph", "text": "alpha beta gamma"}],
                content_hash="h", doc_id="doc-h", source_uri="u://d", source_id="d",
                classification="internal", redaction_state="pending", sensitive=False,
                residency_region="home", acl_ref=None)
    base.update(kw)
    return base


def pipe(**over):
    prof = {"chunk": {"target_chars": 100, "overlap_chars": 15, "max_chunks": 5000, "token_estimate_divisor": 4},
            "embedding": {"model": "ref-embed-v1", "dim": 32, "no_train": True, "no_log": True},
            "residency_region": "home", "allowed_regions": ["home"]}
    prof.update(over)
    return P.IndexPipeline(prof)


# T1 — Parse aşaması 6.1.1'e devredilir; pipeline NormalizedDocument'ı tüketir (chunk üretir).
def t1():
    ndoc = P.normdoc_from_source({"source_id": "x", "format_declared": "csv", "tenant_id": "t-a", "kb_id": "kb-1",
                                  "inline_text": "soru,yanit\niade,14 gun\nkargo,ucretsiz\n"})
    check(ndoc["status"] == "ingested", "T1 6.1.1 NormalizedDocument üretti")
    r = pipe().index_normdoc(ndoc)
    check(r["status"] == "indexed" and r["chunk_count"] >= 1, "T1 pipeline chunk üretti (parse devri)")


# T2 — Chunk kapsamı: core metinleri kaynağı tam kaplar (kapsam-kaybı=0).
def t2():
    blocks = [{"type": "p", "text": "Birinci cumle yeterince uzundur."},
              {"type": "p", "text": "Ikinci cumle de uzundur ve devam eder."},
              {"type": "p", "text": "Ucuncu cumle son bloktur."}]
    chunks = P.chunk_blocks(blocks, 50, 10)
    check(" ".join(c["core_text"] for c in chunks) == " ".join(b["text"] for b in blocks), "T2 kapsam tam")
    check(len(chunks) >= 2, "T2 birden cok chunk")
    check(all(c["char_count"] <= 50 + 10 + 2 for c in chunks), "T2 chunk boyutu bounded")


# T3 — Embedding vendor-neutral SPI: sabit dim, deterministik, L2-norm, batch.
def t3():
    e = P.ReferenceEmbedder("m", 32, True, True)
    ctx = {"residency_region": "home", "allowed_regions": ["home"]}
    a = e.embed_batch(["a", "b"], ctx)
    b = e.embed_batch(["a", "b"], ctx)
    check(a == b, "T3 deterministik")
    check(all(len(v) == 32 for v in a), "T3 sabit dim")
    import math
    check(all(abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9 for v in a), "T3 L2-norm")
    check(e.batches == 2, "T3 batch sayacı")


# T4 — Versiyonlama: ilk indeks v1.
def t4():
    r = pipe().index_normdoc(nd(content_hash="v1h", source_uri="u://doc1"))
    check(r["action"] == "first_version" and r["version_no"] == 1, "T4 ilk indeks v1")


# T5 — İdempotent no-op: aynı içerik yeniden → yeni sürüm yok.
def t5():
    p = pipe()
    p.index_normdoc(nd(content_hash="same", source_uri="u://doc1"))
    r2 = p.index_normdoc(nd(content_hash="same", source_uri="u://doc1"))
    check(r2["status"] == "reused" and r2["action"] == "noop_unchanged" and r2["version_no"] == 1,
          "T5 idempotent no-op")
    check(len(p.docs[("t-a", "kb-1", "u://doc1")]["versions"]) == 1, "T5 tek sürüm")


# T6 — Yeni sürüm: içerik değişti → v2 + supersede + tek aktif + geçmiş korunur.
def t6():
    p = pipe()
    p.index_normdoc(nd(content_hash="c1", source_uri="u://doc1"))
    r2 = p.index_normdoc(nd(content_hash="c2", text="degisen icerik metni", source_uri="u://doc1",
                            blocks=[{"type": "p", "text": "degisen icerik metni"}]))
    check(r2["action"] == "new_version" and r2["version_no"] == 2, "T6 v2")
    ns = P._namespace("t-a", "kb-1")
    active = {c["version_no"] for c in p.active_chunks(ns) if c["doc_logical_key"] == "u://doc1"}
    allv = {c["version_no"] for c in p.all_chunks(ns) if c["doc_logical_key"] == "u://doc1"}
    check(active == {2}, "T6 tek aktif=v2 (supersede)")
    check(allv == {1, 2}, "T6 v1 geçmişte korunur")


# T7 — Namespace izolasyonu: aynı içerik farklı tenant ayrı namespace, cross=0.
def t7():
    p = pipe()
    p.index_normdoc(nd(tenant_id="t-a", content_hash="z", source_uri="u://d"))
    p.index_normdoc(nd(tenant_id="t-b", content_hash="z", source_uri="u://d"))
    check(P._namespace("t-a", "kb-1") in p.store and P._namespace("t-b", "kb-1") in p.store, "T7 iki namespace")
    cross = sum(1 for ns, recs in p.store.items() for r in recs if r["namespace"] != ns)
    check(cross == 0, "T7 cross-namespace=0")


# T8 — No-train fail-closed: hassas + train-açık → NO_TRAIN_REQUIRED_VIOLATION.
def t8():
    p = pipe(embedding={"model": "m", "dim": 32, "no_train": False, "no_log": True})
    r = p.index_normdoc(nd(sensitive=True, content_hash="s"))
    check(r["status"] == "rejected" and r["error_class"] == "NO_TRAIN_REQUIRED_VIOLATION", "T8 hassas fail-closed")
    r2 = p.index_normdoc(nd(sensitive=False, content_hash="ns", source_uri="u://d2"))
    check(r2["status"] == "indexed", "T8 hassas-olmayan geçer")


# T9 — Citation + access metadata propagasyonu + ham vektör gömülmez.
def t9():
    p = pipe()
    r = p.index_normdoc(nd(classification="restricted", acl_ref="acl:9", content_hash="m",
                           text="gizli politika metni", blocks=[{"type": "p", "text": "gizli politika metni"}]))
    c = r["chunks"][0]
    check(c["classification"] == "restricted" and c["acl_ref"] == "acl:9", "T9 acl propagasyon")
    check(c["document_id"] and c["version_no"] and c["source_uri"] is not None and c["block_span"]
          and c["content_hash"], "T9 citation alanları")
    check("embedding" not in c and "vector" not in c and "embedding_fingerprint" in c, "T9 ham vektör gömülmez")


# T10 — Robustluk: tenant'sız fail-closed + boş doküman + batch dayanıklılığı.
def t10():
    p = pipe()
    r1 = p.index_normdoc(nd(tenant_id=None))
    check(r1["error_class"] == "MISSING_TENANT_CONTEXT", "T10 tenant'sız fail-closed")
    r2 = p.index_normdoc(nd(text="  ", blocks=[{"type": "p", "text": " "}], content_hash="e"))
    check(r2["error_class"] == "EMPTY_DOCUMENT", "T10 boş doküman")
    res = p.index_batch([(nd(tenant_id=None), None), (nd(content_hash="ok", source_uri="u://ok"), None)])
    check(res[0]["status"] == "rejected" and res[1]["status"] == "indexed", "T10 batch dayanıklılığı")


def main():
    for fn in [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10]:
        try:
            fn()
        except Exception as e:
            _fails.append("%s çöktü: %s" % (fn.__name__, type(e).__name__))
    n = 10
    print("behavior: %d test, %d başarısız" % (n, len(_fails)))
    for m in _fails:
        print("  ✗ %s" % m)
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
