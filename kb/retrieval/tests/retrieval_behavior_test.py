#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.2.1 — Retrieval davranış testleri (T1–T10). Stdlib-only, credential-free, deterministik.
Probe'un selftest'inden BAĞIMSIZ siyah-kutu davranış kontrolü (regresyon kapısı). Çalıştır:
    python3 tests/retrieval_behavior_test.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..")))
import retrieval_probe as P  # noqa: E402

_fails = []


def check(cond, msg):
    if not cond:
        _fails.append(msg)


PROF = {"top_k": 5, "min_score": 0.10, "rerank": {"enabled": True, "model": "rr", "candidates": 20},
        "embedding": {"model": "ref-embed-v1", "dim": 256, "no_train": True, "no_log": True},
        "acl": {"enforce_acl": True, "require_acl_classifications": ["confidential", "restricted"],
                "redaction_mode": "redact", "default_acl_decision": "deny", "deny_wins": True},
        "residency_region": "home", "allowed_regions": ["home"]}
ACLS = {"acl:fin": {"default": "deny", "allow": ["group:finance"], "deny": ["group:contractors"]}}

DOCS = [
    {"source_id": "iade", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
     "redaction_state": "not_required",
     "inline_text": "Iade politikasi musteri urun 14 gun iade kosul ambalaj kullanilmamis genel"},
    {"source_id": "kargo", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
     "redaction_state": "not_required",
     "inline_text": "Kargo teslimat standart gonderi uc is gunu hizli gonderi ertesi gun takip"},
    {"source_id": "ucret", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "confidential",
     "acl_ref": "acl:fin", "redaction_state": "applied",
     "inline_text": "Gizli ucret bandi maas terfi politika finans bonus prim yil sonu gozden gecirme"},
]


def ctx(**kw):
    b = {"tenant_id": "t-a", "kb_ids": ["kb-1"], "principals": ["role:human_agent"],
         "clearance": "internal", "channel_no_log": True}
    b.update(kw)
    return b


def engine(prof=None, docs=None, acls=None, **kw):
    _, chunks, _ = P.index_documents(docs if docs is not None else DOCS)
    return P.RetrievalEngine(prof or PROF, chunks, acls if acls is not None else ACLS, **kw)


# T1 — Embedding vendor-neutral SPI: deterministik, sabit dim, L2-norm, cosine lexical overlap.
def t1():
    e = P.RetrievalEmbedder("m", 256, True, True)
    ec = {"residency_region": "home", "allowed_regions": ["home"]}
    a = e.embed_batch(["iade urun gun"], ec)
    b = e.embed_batch(["iade urun gun"], ec)
    check(a == b, "T1 deterministik")
    check(len(a[0]) == 256 and abs(math.sqrt(sum(x * x for x in a[0])) - 1.0) < 1e-9, "T1b dim+L2-norm")
    # Feature-hash embedder'da ayrık metinler küçük çarpışma cosine'i verebilir (referans geometri);
    # önemli olan tam-örtüşme >> ayrık ve ayrık < tipik min_score komşuluğu.
    qa = "iade urun gun kosul ambalaj talebi"
    full = P.RetrievalEmbedder.cosine(e._vec(qa), e._vec(qa))
    none = P.RetrievalEmbedder.cosine(e._vec(qa), e._vec("kuantum galaksi teleskop meteor astronomi nebula"))
    check(full > 0.99 and none < 0.25 and none < full * 0.5, "T1c cosine tam-örtüşme>>örtüşmesiz")


# T2 — Vector search top-k + ranking: alakalı doküman #1, top_k sınırı.
def t2():
    r = engine().retrieve("iade urun gun kosul ambalaj", ctx(), "q")
    check(r["status"] == "ok" and r["results"][0]["document_id"] == "iade", "T2 iade #1")
    check(len(r["results"]) <= 5, "T2b top_k sınırı")
    sc = [x["rerank_score"] for x in r["results"]]
    check(all(sc[i] >= sc[i + 1] for i in range(len(sc) - 1)), "T2c rerank_score desc")


# T3 — Namespace izolasyonu: t-b sorgusu t-a chunk'larını görmez.
def t3():
    docs = DOCS + [{"source_id": "iade", "tenant_id": "t-b", "kb_id": "kb-1", "classification": "public",
                    "redaction_state": "not_required",
                    "inline_text": "Iade politikasi musteri urun 14 gun iade kosul ambalaj tenant b"}]
    r = engine(docs=docs).retrieve("iade urun gun kosul", ctx(tenant_id="t-b"), "iso")
    check(r["results"] and all(x["tenant_id"] == "t-b" for x in r["results"]), "T3 yalnız t-b chunk")


# T4 — ACL enforcement at retrieval: confidential düşük clearance'a dönmez; yetkili görür.
def t4():
    eng = engine()
    low = eng.retrieve("gizli ucret bandi maas terfi finans bonus", ctx(clearance="internal"), "low")
    check("ucret" not in {x["document_id"] for x in low["results"]}, "T4 confidential düşük clearance'a dönmez")
    hi = eng.retrieve("gizli ucret bandi maas terfi finans bonus",
                      ctx(clearance="confidential", principals=["group:finance"]), "hi")
    check("ucret" in {x["document_id"] for x in hi["results"]}, "T4b finance principal görür")
    # deny-wins
    dw = eng.retrieve("gizli ucret bandi maas terfi finans bonus",
                      ctx(clearance="confidential", principals=["group:finance", "group:contractors"]), "dw")
    check("ucret" not in {x["document_id"] for x in dw["results"]}, "T4c deny-wins")


# T5 — Active-only: doküman v2 → yalnız v2 döner.
def t5():
    docs = [{"source_id": "pol", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
             "redaction_state": "not_required", "doc_logical_key": "doc:pol",
             "inline_text": "Eski surum politika alfa beta gama yururlukten kalkti"},
            {"source_id": "pol", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
             "redaction_state": "not_required", "doc_logical_key": "doc:pol",
             "inline_text": "Yeni surum politika delta epsilon zeta guncel yururlukteki gecerli"}]
    r = engine(docs=docs, acls={}).retrieve("guncel yururlukteki politika gecerli surum", ctx(), "ver")
    check(r["status"] == "ok" and all(x["version_no"] == 2 for x in r["results"]), "T5 yalnız aktif v2")


# T6 — Opsiyonel rerank kapalı: geçerli cosine sıralaması döner.
def t6():
    prof = dict(PROF)
    prof["rerank"] = {"enabled": False, "model": "rr", "candidates": 20}
    r = engine(prof=prof).retrieve("kargo teslimat gonderi gun takip", ctx(), "off")
    check(r["status"] == "ok" and r["reranked"] is False, "T6 rerank kapalı yol geçerli")
    sc = [x["score"] for x in r["results"]]
    check(all(sc[i] >= sc[i + 1] for i in range(len(sc) - 1)) and r["results"][0]["document_id"] == "kargo",
          "T6b cosine desc + kargo #1")


# T7 — Grounding: alakasız soru → boş + grounded=false + NO_RELEVANT_SOURCE.
def t7():
    r = engine().retrieve("kuantum fizigi teleskop galaksi astronomi meteor", ctx(), "off-topic")
    check(r["status"] == "empty" and r["grounded"] is False and r["reason"] == P.REASON_NO_RELEVANT,
          "T7 alakasız grounded=false")
    check(r["results"] == [], "T7b boş sonuç (uydurma yok)")


# T8 — Citation + token bütçesi: her sonuç citation alanlarını taşır.
def t8():
    r = engine().retrieve("iade urun gun kosul ambalaj", ctx(), "cite")
    x = r["results"][0]
    check(x["document_id"] and x["version_no"] and x["chunk_no"] is not None and x["source_uri"]
          and x["content_hash"] and x["token_estimate"] is not None and x["score"] is not None,
          "T8 citation+budget alanları")


# T9 — No-log audit + fail-closed (bağlam eksik / boş soru / hassas no-train).
def t9():
    eng = engine()
    eng.retrieve("iade urun gun", ctx(), "ok")
    import json
    blob = json.dumps(eng.audit, ensure_ascii=False)
    check("content" not in {k for a in eng.audit for k in a} and "query_text" not in blob, "T9 audit ham içerik yok")
    check(eng.retrieve("x", {"tenant_id": "t-a"}, "noctx")["error_class"] == "MISSING_QUERY_CONTEXT",
          "T9b bağlam eksik fail-closed")
    check(eng.retrieve("  ", ctx(), "empty")["error_class"] == "EMPTY_QUERY", "T9c boş soru")
    prof = dict(PROF)
    prof["embedding"] = {"model": "m", "dim": 256, "no_train": False, "no_log": True}
    rt = engine(prof=prof).retrieve("gizli ucret", ctx(clearance="confidential", principals=["group:finance"],
                                                       sensitive_query=True), "sens")
    check(rt["error_class"] == "NO_TRAIN_REQUIRED_VIOLATION", "T9d hassas soru train-açık fail-closed")


# T10 — Robust: rerank sağlayıcı hatası yapısal (çökme yok) + INVALID_TOP_K.
def t10():
    rf = engine(rerank_fail=True).retrieve("iade urun gun", ctx(), "rrfail")
    check(rf["status"] == "error" and rf["error_class"] == "RERANK_PROVIDER_ERROR", "T10 rerank hata yapısal")
    prof = dict(PROF)
    prof["top_k"] = 0
    rk = engine(prof=prof).retrieve("iade urun", ctx(), "k0")
    check(rk["error_class"] == "INVALID_TOP_K", "T10b top_k=0 fail-closed")


def main():
    for fn in [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10]:
        try:
            fn()
        except Exception as e:
            _fails.append("%s çöktü: %s" % (fn.__name__, type(e).__name__))
    print("behavior: %d test, %d başarısız" % (10, len(_fails)))
    for m in _fails:
        print("  ✗ %s" % m)
    return 0 if not _fails else 1


if __name__ == "__main__":
    sys.exit(main())
