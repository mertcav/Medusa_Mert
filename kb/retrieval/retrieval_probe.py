#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.2.1 — Vector search (top-k) + opsiyonel rerank (SAD §10.2) referans probe.

    Soru ──► [embed (SPI)] ──► [vector search: cosine top-n | namespace+active+ACL aday] ──►
             [rerank (opsiyonel, SPI)] ──► top-k ──► citation'lı RankedResult (grounded?)

Bilgi Tabanı & RAG ONLINE retrieval hattının (SAD §10.2, hot-path) BİRİNCİ aşaması. Bu motor:
  6.1.3 IndexPipeline'ın ürettiği AKTİF IndexedChunk'ları (namespace+classification+acl+version+citation
  metadata TAŞINMIŞ) TÜKETİR — chunk/embed/version'u YENİDEN YAPMAZ (index_pipeline_probe IMPORT edilir,
  o da ingest_connector_probe'u; kod tekrarı YOK); soruyu AYNI vendor-neutral EmbeddingAdapter SPI ile
  embed eder (R1); aday kümeyi query namespace (FR-KB-004) ∩ AKTİF (6.1.3 C8) ∩ 6.1.4 ACL pre-filtre
  (FR-KB-005) ile sınırlar (R3/R4/R5); cosine ile skorlar + min_score eşiği (R2) + top-k (FR-KB-011);
  OPSİYONEL RerankAdapter SPI ile yeniden sıralar (yalnız sıralar — R6); citation'lı RankedResult döndürür
  (R7); aday yoksa grounded=false + NO_RELEVANT_SOURCE (R9 anti-hallucination kancası → 3.3.4); no-log/
  residency (R8); structured RetrievalError (R10).

Kapsam dışı (bilinçli, R10): chunk/embed/version → 6.1.3 (TÜKETİR); ACL metadata + authoritative karar →
6.1.4 (pre-filtre yüklemini TÜKETİR); token-trim → 6.2.2; kaynak-atfı sentezi → 6.2.3; no-log enforcement
detay → 6.2.4; benchmark/recall@k canlı → 6.2.5 / 0.2.5 vector-db-eval; fiziksel ANN store → 1.1.7.
Vendor-neutral (ADR-001/002): embedding + rerank birer SPI arkasında — referans deterministik feature-hash
BoW embedder + coverage reranker yerine canlıda gerçek semantik model + cross-encoder AYNI imza arkasına.

Kullanım:
  retrieval_probe.py validate           Statik spec/config/şema kapısı → çıkış kodu
  retrieval_probe.py retrieve <sample>  Deterministik Retrieval — senaryoyu index→embed→search→rerank → kapı
  retrieval_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  retrieval_probe.py schema             SPI/RankedResult/karar sözleşmesini yazdır

Determinizm: tohumlu deterministik embedder/reranker (Date.now/rastgele YOK); chunk'lar 6.1.3'ten TÜRETİLİR.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture içerikleri sentetik — FR-TST-008). Stdlib-only.
"""
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "retrieval-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "retrieval-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# 6.1.3 index pipeline'ı import et — IndexedChunk'ı ONUN ürettiği gibi türet (kod tekrarı YOK).
_IDX_DIR = os.path.normpath(os.path.join(HERE, "..", "index-pipeline"))
sys.path.insert(0, _IDX_DIR)
import index_pipeline_probe as IDX  # noqa: E402

# 6.1.4 access gate'i import et — ACL pre-filtre yüklemini TÜKETİR (FR-KB-005 enforcement at retrieval).
_ACL_DIR = os.path.normpath(os.path.join(HERE, "..", "access-control"))
sys.path.insert(0, _ACL_DIR)
import access_control_probe as ACL  # noqa: E402

# ── Sabitler ──────────────────────────────────────────────────────────────────
GATE_IDS = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"]

ERROR_CLASSES = {
    "MISSING_QUERY_CONTEXT", "EMPTY_QUERY", "INVALID_TOP_K", "EMBED_PROVIDER_ERROR",
    "EMBED_DIM_MISMATCH", "NO_TRAIN_REQUIRED_VIOLATION", "REGION_VIOLATION",
    "RERANK_PROVIDER_ERROR", "INTERNAL_ERROR",
}
REASON_NO_RELEVANT = "NO_RELEVANT_SOURCE"

# Sır/PII tarama (spec/config/sample DESCRIPTOR'larında).
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def tokenize(text):
    """Deterministik tokenizasyon: lowercase + \\w+ + len≥2 (gürültü token'ı düşür). TR-duyarlı (ASCII fixture)."""
    return [t for t in TOKEN_RE.findall((text or "").lower()) if len(t) >= 2]


class RetrievalError(Exception):
    def __init__(self, error_class, detail):
        super().__init__("%s: %s" % (error_class, detail))
        self.error_class = error_class
        self.detail = detail


# ── EmbeddingAdapter SPI (vendor-neutral, ADR-001/002) ──────────────────────────
class RetrievalEmbedder:
    """Deterministik referans embedder: signed feature-hash bag-of-words → embedding_dim float → L2-normalize.
    cosine ~ lexical overlap → recall TEST EDİLEBİLİR (gerçek değer değil; sözleşme/akış + geometri kanıtı).
    Soru + chunk content AYNI uzay (query-doc tutarlılığı). Canlıda gerçek SEMANTİK model AYNI imza arkasına.
    ctx: {residency_region, allowed_regions, no_train, no_log, sensitive} — fail-closed kontroller burada."""

    def __init__(self, model, dim, no_train, no_log):
        self.model = model
        self.dim = int(dim)
        self.no_train = bool(no_train)
        self.no_log = bool(no_log)
        self.calls = 0
        self.batches = 0

    def _vec(self, text):
        vec = [0.0] * self.dim
        for tok in tokenize(text):
            h = int.from_bytes(hashlib.sha256((self.model + "\x00" + tok).encode("utf-8")).digest()[:8], "big")
            bucket = h % self.dim
            sign = 1.0 if ((h >> 17) & 1) else -1.0
            vec[bucket] += sign            # tf (signed feature hashing → collision bias azalır)
        ss = sum(x * x for x in vec)
        if ss == 0.0:
            return vec                     # token yok → sıfır vektör (cosine her şeyle 0)
        norm = math.sqrt(ss)
        return [x / norm for x in vec]

    def embed_batch(self, texts, ctx):
        """SPI yüzeyi. list[text] → list[vector(dim)]. Fail-closed: hassas + train-açık → NO_TRAIN."""
        if ctx.get("sensitive") and not self.no_train:
            raise RetrievalError("NO_TRAIN_REQUIRED_VIOLATION",
                                 "hassas soru train-açık embedding endpoint'e gönderilemez (no_train=false)")
        region = ctx.get("residency_region", "home")
        if region not in ctx.get("allowed_regions", [region]):
            raise RetrievalError("REGION_VIOLATION", "embedding bölgesi %s izinli değil" % region)
        self.batches += 1
        out = []
        for t in texts:
            self.calls += 1
            v = self._vec(t)
            if len(v) != self.dim:                                  # savunmacı
                raise RetrievalError("EMBED_DIM_MISMATCH", "vektör boyutu %d != %d" % (len(v), self.dim))
            out.append(v)
        return out

    @staticmethod
    def cosine(a, b):
        """İki L2-normalize vektörün cosine'i = nokta çarpımı. Sıfır vektör → 0."""
        return sum(x * y for x, y in zip(a, b))


# ── RerankAdapter SPI (vendor-neutral, OPSİYONEL, ADR-001/002) ───────────────────
class ReferenceReranker:
    """Deterministik referans reranker (cross-encoder STAND-IN). rerank_score = query-term coverage
    (|query_tok ∩ chunk_tok| / |query_tok|) + küçük vec_score tie-break. Bi-encoder cosine'den FARKLI
    (exact lexical coverage) sinyal → kaçırılan sıralamayı düzeltebilir. INVARIANT: yalnız SIRALAR —
    aday alt-kümesini reorder eder, yeni doc EKLEMEZ. Canlıda gerçek cross-encoder AYNI imza arkasına."""

    def __init__(self, model, fail=False):
        self.model = model
        self.fail = bool(fail)
        self.calls = 0

    def rerank(self, query_text, candidates):
        """candidates: [(chunk, vec_score)] → reordered [(chunk, vec_score, rerank_score)] (aynı küme)."""
        if self.fail:
            raise RetrievalError("RERANK_PROVIDER_ERROR", "rerank sağlayıcı hatası (canlıda fallback cosine)")
        self.calls += 1
        qtok = set(tokenize(query_text))
        scored = []
        for chunk, vec_score in candidates:
            ctok = set(tokenize(chunk.get("content", "")))
            coverage = (len(qtok & ctok) / len(qtok)) if qtok else 0.0
            rerank_score = coverage + 0.001 * vec_score          # tie-break: cosine
            scored.append((chunk, vec_score, rerank_score))
        # Deterministik: rerank_score desc → vec_score desc → chunk_id.
        scored.sort(key=lambda x: (-x[2], -x[1], x[0].get("chunk_id", "")))
        return scored


def query_digest(text):
    """Audit için soru özeti — HAM soru loglanmaz (PII/no-log hijyeni)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _result_key(chunk):
    """Namespace-nitelikli sonuç kimliği (6.1.3 chunk_id içerik-hash tabanlı → cross-tenant çakışabilir)."""
    return "%s|%s" % (chunk.get("namespace"), chunk.get("chunk_id"))


# ── RetrievalEngine — vector search top-k + opsiyonel rerank (SAD §10.2) ──────────
class RetrievalEngine:
    """AKTİF IndexedChunk store + query → RankedResult. İki aşama: vector search → opsiyonel rerank.
    profile: top_k / min_score / rerank{enabled,candidates} / embedding{dim,no_train,no_log} / acl{...}.
    store_chunks: 6.1.3 IndexPipeline.store'dan TÜM chunk'lar (aktif + supersede). Deterministik."""

    def __init__(self, profile, store_chunks, acls=None, rerank_fail=False):
        self.top_k = int(profile.get("top_k", 5))
        self.min_score = float(profile.get("min_score", 0.0))
        rr = profile.get("rerank", {})
        self.rerank_enabled = bool(rr.get("enabled", False))
        self.rerank_candidates = max(self.top_k, int(rr.get("candidates", self.top_k)))
        emb = profile.get("embedding", {})
        self.embedder = RetrievalEmbedder(emb.get("model", "ref-embed-v1"), int(emb.get("dim", 256)),
                                          emb.get("no_train", True), emb.get("no_log", True))
        self.reranker = ReferenceReranker(rr.get("model", "ref-rerank-v1"), fail=rerank_fail)
        self.region = profile.get("residency_region", "home")
        self.allowed_regions = set(profile.get("allowed_regions", [self.region]))
        # 6.1.4 ACL pre-filtre (FR-KB-005 enforcement at retrieval).
        acl_cfg = profile.get("acl", {})
        self.enforce_acl = bool(acl_cfg.get("enforce_acl", True))
        self.gate = ACL.AccessGate(acl_cfg, acls or {})
        self.store = list(store_chunks)
        self._doc_vec_cache = {}           # id(chunk) -> content vektörü (aday içi tek embed)
        self.audit = []
        self._t = 0

    # — query ctx tamlığı (fail-closed) —
    def _ctx_complete(self, ctx):
        return bool(ctx) and bool(ctx.get("tenant_id")) and isinstance(ctx.get("kb_ids"), list) \
            and bool(ctx.get("kb_ids")) and bool(ctx.get("principals")) and ctx.get("clearance") in ACL.CLEARANCE

    def _namespaces(self, ctx):
        return {IDX._namespace(ctx["tenant_id"], kb) for kb in ctx.get("kb_ids", [])}

    def _candidates(self, ctx):
        """Aday küme: query namespace (R3) ∩ AKTİF (R5) ∩ (enforce_acl ? 6.1.4 ACL-admit (R4) : True)."""
        ns_set = self._namespaces(ctx)
        out = []
        for c in self.store:
            if c.get("namespace") not in ns_set:
                continue
            if c.get("tenant_id") != ctx["tenant_id"] or c.get("kb_id") not in ctx["kb_ids"]:
                continue
            if not c.get("active", False):
                continue
            if self.enforce_acl and not self.gate.prefilter_admits(ctx, c):
                continue
            out.append(c)
        return out

    def _doc_vec(self, chunk):
        key = id(chunk)
        v = self._doc_vec_cache.get(key)
        if v is None:
            # Stored vektör yerine content'i AYNI embedder ile yeniden embed (durable store 1.1.7; canlıda ANN).
            v = self.embedder._vec(chunk.get("content", ""))
            self._doc_vec_cache[key] = v
        return v

    def retrieve(self, query_text, ctx, query_name=None):
        try:
            return self._retrieve(query_text, ctx, query_name)
        except RetrievalError as e:
            self._audit(query_name, ctx, 0, 0, False, e.error_class)
            return {"status": "error", "query_name": query_name, "error_class": e.error_class,
                    "detail": e.detail, "grounded": False, "results": [],
                    "tenant_id": ctx.get("tenant_id") if ctx else None,
                    "kb_ids": ctx.get("kb_ids") if ctx else None, "reason": e.error_class}
        except Exception as e:  # never-crash garantisi (R10)
            self._audit(query_name, ctx, 0, 0, False, "INTERNAL_ERROR")
            return {"status": "error", "query_name": query_name, "error_class": "INTERNAL_ERROR",
                    "detail": "beklenmedik: %s" % type(e).__name__, "grounded": False, "results": [],
                    "tenant_id": ctx.get("tenant_id") if ctx else None,
                    "kb_ids": ctx.get("kb_ids") if ctx else None, "reason": "INTERNAL_ERROR"}

    def _retrieve(self, query_text, ctx, query_name):
        if not self._ctx_complete(ctx):
            raise RetrievalError("MISSING_QUERY_CONTEXT", "tenant_id/kb_ids/principals/clearance zorunlu (fail-closed)")
        if not (query_text or "").strip():
            raise RetrievalError("EMPTY_QUERY", "boş soru")
        if self.top_k <= 0:
            raise RetrievalError("INVALID_TOP_K", "top_k=%d ≤ 0" % self.top_k)

        # STAGE 1 — embed query (R1/R8) + cosine over aday küme (R3/R4/R5).
        ectx = {"residency_region": self.region, "allowed_regions": self.allowed_regions,
                "no_train": self.embedder.no_train, "no_log": self.embedder.no_log,
                "sensitive": bool(ctx.get("sensitive_query", False))}
        qvec = self.embedder.embed_batch([query_text], ectx)[0]

        candidates = self._candidates(ctx)
        scored = []
        for c in candidates:
            s = RetrievalEmbedder.cosine(qvec, self._doc_vec(c))
            if s >= self.min_score:                                 # R2 min_score alaka eşiği
                scored.append((c, s))
        # Deterministik sıralama: cosine desc → chunk_id.
        scored.sort(key=lambda x: (-x[1], x[0].get("chunk_id", "")))

        if not scored:
            # R9 GROUNDING — aday yok → uydurma yok.
            self._audit(query_name, ctx, len(candidates), 0, False, REASON_NO_RELEVANT)
            return {"status": "empty", "query_name": query_name, "grounded": False,
                    "reason": REASON_NO_RELEVANT, "results": [], "candidate_count": len(candidates),
                    "scored_count": 0, "reranked": self.rerank_enabled,
                    "tenant_id": ctx["tenant_id"], "kb_ids": ctx["kb_ids"]}

        # STAGE 2 — vector top-n → opsiyonel rerank → top-k (R6).
        top_n = scored[: self.rerank_candidates]
        reranked = False
        if self.rerank_enabled:
            ranked = self.reranker.rerank(query_text, top_n)         # [(chunk, vec_score, rerank_score)]
            reranked = True
        else:
            ranked = [(c, s, None) for c, s in top_n]
        ranked = ranked[: self.top_k]

        results = []
        for rank, item in enumerate(ranked):
            chunk, vec_score, rr_score = item
            results.append(self._ranked_result(rank, chunk, vec_score, rr_score))

        self._audit(query_name, ctx, len(candidates), len(results), True, None)
        return {"status": "ok", "query_name": query_name, "grounded": True, "reason": None,
                "results": results, "candidate_count": len(candidates), "scored_count": len(scored),
                "reranked": reranked, "tenant_id": ctx["tenant_id"], "kb_ids": ctx["kb_ids"]}

    def _ranked_result(self, rank, chunk, vec_score, rr_score):
        """R7 citation sözleşmesi — yanıt→kaynak (FR-KB-006 →6.2.3) + token bütçesi (→6.2.2)."""
        return {
            "result_key": _result_key(chunk), "rank": rank,
            "score": round(vec_score, 6), "rerank_score": (round(rr_score, 6) if rr_score is not None else None),
            "chunk_id": chunk.get("chunk_id"), "document_id": chunk.get("document_id"),
            "doc_logical_key": chunk.get("doc_logical_key"), "namespace": chunk.get("namespace"),
            "tenant_id": chunk.get("tenant_id"), "kb_id": chunk.get("kb_id"),
            "version_no": chunk.get("version_no"), "chunk_no": chunk.get("chunk_no"),
            "source_uri": chunk.get("source_uri"), "title": chunk.get("title"),
            "content": chunk.get("content"), "char_count": chunk.get("char_count"),
            "token_estimate": chunk.get("token_estimate"), "content_hash": chunk.get("content_hash"),
            "classification": chunk.get("classification"),
        }

    def _audit(self, query_name, ctx, candidate_count, returned, grounded, reason):
        """R8 yapısal audit — HAM soru/content/PII YAZILMAZ (query_digest/principal_digest sha256)."""
        self._t += 1
        self.audit.append({
            "ts": self._t, "query_name": query_name,
            "tenant_id": ctx.get("tenant_id") if ctx else None,
            "kb_ids": ctx.get("kb_ids") if ctx else None,
            "principal_digest": ACL.principal_digest(ctx),
            "query_digest": query_digest((ctx or {}).get("_qtext", "")) if ctx else "anon",
            "candidate_count": candidate_count, "returned": returned,
            "grounded": bool(grounded), "reason": reason, "no_log": True,
        })


# ── 6.1.3 üzerinden AKTİF IndexedChunk üretimi (TÜKETİR — yeniden yapmaz) ─────────
def _normdoc_from_doc(d):
    """Sample 'document' girdisini NormalizedDocument'a çevir (6.1.3 IndexPipeline girişi).
    content_hash deterministik (sha256(text)); doc_id=source_id → IndexedChunk.document_id stabil."""
    text = d.get("inline_text", "")
    blocks = [{"type": "paragraph", "text": p.strip()}
              for p in re.split(r"\n\s*\n", text) if p.strip()] or [{"type": "paragraph", "text": text}]
    chash = d.get("content_hash") or hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "status": "ingested", "source_id": d["source_id"], "doc_id": d["source_id"],
        "tenant_id": d.get("tenant_id"), "kb_id": d.get("kb_id"),
        "doc_logical_key": d.get("doc_logical_key") or d["source_id"],
        "text": text, "blocks": blocks, "content_hash": chash,
        "source_uri": d.get("source_uri") or ("u://" + str(d.get("source_id"))),
        "title": d.get("title"),
        "classification": d.get("classification", "internal"),
        "acl_ref": d.get("acl_ref"),
        "sensitive": bool(d.get("sensitive", False)),
        "redaction_state": d.get("redaction_state", "not_required"),
        "residency_region": d.get("residency_region", "home"),
    }


def _mk_index_pipeline():
    """6.1.3 IndexPipeline — büyük target_chars (doküman başına 1 chunk → retrieval sıralaması netlik;
    embedding dim 6.1.3'te küçük yeterli, retrieval AYRI embedder ile content'i yeniden embed eder)."""
    prof = {"chunk": {"target_chars": 4000, "overlap_chars": 0, "max_chunks": 5000, "token_estimate_divisor": 4},
            "embedding": {"model": "ref-embed-v1", "dim": 16, "no_train": True, "no_log": True},
            "residency_region": "home", "allowed_regions": ["home"]}
    return IDX.IndexPipeline(prof)


def index_documents(documents):
    """Sample documents → 6.1.3 ile sırayla indexle → store chunk'lar (aktif + supersede). Aynı logical
    key + farklı içerik → yeni sürüm + eski active=false (R5 girdisi)."""
    pipe = _mk_index_pipeline()
    results = []
    for d in documents:
        nd = _normdoc_from_doc(d)
        r = pipe.index_normdoc(nd, nd["doc_logical_key"])
        results.append((d.get("source_id"), r))
    chunks = []
    for ns, recs in pipe.store.items():
        chunks.extend(recs)
    return pipe, chunks, results


# ── Kapı değerlendirme (R1–R10) ──────────────────────────────────────────────────
def evaluate_gates(sample, engine, query_runs):
    """query_runs: [(query, ctx, result)]. engine retrieval sonrası durumu taşır."""
    checks = []

    def chk(gid, ok, msg):
        checks.append((gid, bool(ok), msg))

    ok_results = [(q, ctx, r) for q, ctx, r in query_runs if r["status"] == "ok"]
    ns_of = IDX._namespace

    # R1 RANKING + RECALL — sıralı (score desc) + labeled recall@k.
    order_bad = 0
    recall_total = 0
    recall_hit = 0
    for q, ctx, r in ok_results:
        res = r["results"]
        # Sıralama: reranked ise rerank_score desc, değilse score desc (deterministik).
        if r.get("reranked"):
            keyfn = [(-(x["rerank_score"] if x["rerank_score"] is not None else -1), -x["score"]) for x in res]
        else:
            keyfn = [(-x["score"],) for x in res]
        for i in range(len(keyfn) - 1):
            if keyfn[i] > keyfn[i + 1]:
                order_bad += 1
        # rank alanı 0..n-1 sıralı.
        if [x["rank"] for x in res] != list(range(len(res))):
            order_bad += 1
        relevant = set(q.get("expect", {}).get("relevant_documents", []))
        if relevant:
            recall_total += 1
            returned_docs = {x["document_id"] for x in res}
            if relevant.issubset(returned_docs):
                recall_hit += 1
    recall = (recall_hit / recall_total) if recall_total else 1.0
    min_recall = sample.get("min_recall_at_k", 1.0)
    chk("R1", order_bad == 0 and recall >= min_recall,
        "sıralama-ihlal=%d recall@k=%.2f (≥%.2f, labeled-query=%d)" % (order_bad, recall, min_recall, recall_total))

    # R2 TOP-K BOUND + min_score.
    overk = 0
    below_min = 0
    for q, ctx, r in ok_results:
        if len(r["results"]) > engine.top_k:
            overk += 1
        for x in r["results"]:
            if x["score"] < engine.min_score:
                below_min += 1
    chk("R2", overk == 0 and below_min == 0,
        "top_k aşan=%d min_score altı dönen=%d (top_k=%d min=%.2f)" % (overk, below_min, engine.top_k, engine.min_score))

    # R3 NAMESPACE ISOLATION — dönen her chunk query namespace'inde; cross=0.
    cross = 0
    for q, ctx, r in ok_results:
        ns_set = {ns_of(ctx["tenant_id"], kb) for kb in ctx["kb_ids"]}
        for x in r["results"]:
            if x["namespace"] not in ns_set or x["tenant_id"] != ctx["tenant_id"] or x["kb_id"] not in ctx["kb_ids"]:
                cross += 1
    chk("R3", cross == 0, "cross-namespace dönen chunk=%d" % cross)

    # R4 ACL ENFORCEMENT — deny_documents dönmedi + (enforce_acl ise) dönen her chunk ACL-admit.
    unauth = 0
    acl_bad = 0
    for q, ctx, r in ok_results:
        deny_docs = set(q.get("expect", {}).get("deny_documents", []))
        for x in r["results"]:
            if x["document_id"] in deny_docs:
                unauth += 1
            if engine.enforce_acl:
                # Dönen chunk authoritative ACL kararından da geçmeli (defense-in-depth doğrulama).
                src = next((c for c in engine.store if _result_key(c) == x["result_key"]
                            and c.get("version_no") == x["version_no"] and c.get("chunk_no") == x["chunk_no"]), None)
                if src is not None:
                    dec = engine.gate.decide(ctx, src)
                    if dec["decision"] != "ALLOW":
                        acl_bad += 1
    chk("R4", unauth == 0 and acl_bad == 0,
        "yetkisiz-dönen=%d ACL-deny-dönen=%d (enforce_acl=%s)" % (unauth, acl_bad, engine.enforce_acl))

    # R5 ACTIVE-ONLY — inactive (supersede) dönen=0.
    inact = 0
    for q, ctx, r in ok_results:
        for x in r["results"]:
            src = next((c for c in engine.store if _result_key(c) == x["result_key"]
                        and c.get("version_no") == x["version_no"] and c.get("chunk_no") == x["chunk_no"]), None)
            if src is not None and not src.get("active", False):
                inact += 1
    chk("R5", inact == 0, "inactive (supersede) dönen chunk=%d" % inact)

    # R6 RERANK ORDER-ONLY — result ⊆ vector-candidate; rerank cross-ns/ACL leak ÜRETMEDİ; rerank_target #1.
    rerank_leak = 0
    target_bad = 0
    for q, ctx, r in ok_results:
        # Vector-candidate küme (rerank'ten BAĞIMSIZ yeniden hesapla): namespace+active+ACL+min_score.
        ns_set = {ns_of(ctx["tenant_id"], kb) for kb in ctx["kb_ids"]}
        qvec = engine.embedder._vec(q.get("query_text", ""))
        cand_keys = set()
        for c in engine.store:
            if c.get("namespace") not in ns_set or not c.get("active"):
                continue
            if engine.enforce_acl and not engine.gate.prefilter_admits(ctx, c):
                continue
            if RetrievalEmbedder.cosine(qvec, engine._doc_vec(c)) >= engine.min_score:
                cand_keys.add(_result_key(c))
        for x in r["results"]:
            if x["result_key"] not in cand_keys:
                rerank_leak += 1
        target = q.get("expect", {}).get("rerank_top")
        if target and r.get("reranked"):
            if not r["results"] or r["results"][0]["document_id"] != target:
                target_bad += 1
    chk("R6", rerank_leak == 0 and target_bad == 0,
        "rerank-küme-dışı=%d rerank_target-#1-değil=%d" % (rerank_leak, target_bad))

    # R7 CITATION — her sonuç citation + budget alanlarını taşır.
    cite_bad = 0
    for q, ctx, r in ok_results:
        for x in r["results"]:
            if not (x.get("document_id") and x.get("version_no") and x.get("chunk_no") is not None
                    and x.get("source_uri") is not None and x.get("content_hash")
                    and x.get("token_estimate") is not None and x.get("score") is not None
                    and x.get("rank") is not None):
                cite_bad += 1
    chk("R7", cite_bad == 0, "citation/budget-eksik sonuç=%d" % cite_bad)

    # R8 NO-LOG / RESIDENCY — audit yapısal + ham soru/content/PII yok; her query bir audit.
    # *_digest alanları KASITLI sha256 hash (PII değil) → ham-payload taramasından hariç tut.
    scan_entries = [{k: v for k, v in a.items() if not k.endswith("_digest")} for a in engine.audit]
    audit_blob = json.dumps(scan_entries, ensure_ascii=False)
    audit_keys = {k for a in engine.audit for k in a}
    audit_clean = ("content" not in audit_keys and "query_text" not in audit_keys
                   and not ACL.NUM_RE.search(audit_blob) and not ACL.EMAIL_RE.search(audit_blob))
    all_no_log = all(a.get("no_log") for a in engine.audit)
    chk("R8", audit_clean and all_no_log and len(engine.audit) >= len(query_runs),
        "audit=%d query=%d audit-temiz=%s no_log=%s" % (len(engine.audit), len(query_runs), audit_clean, all_no_log))

    # R9 GROUNDING — grounded yalnız ≥1 sonuçta true; boş→false+NO_RELEVANT_SOURCE; expect.grounded tutar.
    grounding_bad = 0
    for q, ctx, r in query_runs:
        if r["status"] == "ok":
            if not (r["grounded"] and len(r["results"]) >= 1):
                grounding_bad += 1
        elif r["status"] == "empty":
            if r["grounded"] or r.get("reason") != REASON_NO_RELEVANT or r["results"]:
                grounding_bad += 1
        exp_g = q.get("expect", {}).get("grounded")
        if exp_g is not None and r["status"] in ("ok", "empty") and bool(r["grounded"]) != bool(exp_g):
            grounding_bad += 1
    chk("R9", grounding_bad == 0, "grounding-ihlal=%d (boş→grounded=false+NO_RELEVANT_SOURCE)" % grounding_bad)

    # R10 ROBUST — her query bir sonuç üretti (exception kaçmadı) + error_class taksonomide.
    n_q = len(sample.get("queries", []))
    produced = len(query_runs)
    bad_cls = [r for _, _, r in query_runs if r["status"] == "error" and r.get("error_class") not in ERROR_CLASSES]
    chk("R10", produced == n_q and not bad_cls,
        "üretilen=%d/%d geçersiz-hata-sınıfı=%d" % (produced, n_q, len(bad_cls)))

    return checks


# ── retrieve — bir sample senaryosunu çalıştır ───────────────────────────────────
def _profile_for(sample, cfg):
    pname = sample.get("profile", "pilot-default")
    p = dict(cfg["profiles"].get(pname, cfg["profiles"]["pilot-default"]))
    return p, pname


def retrieve_cmd(sample_path):
    sample = _load(sample_path)
    cfg = _load(CONFIG_PATH)
    prof, pname = _profile_for(sample, cfg)
    acls = sample.get("acls", {})
    documents = sample.get("documents", [])
    rerank_fail = bool(sample.get("rerank_fail", False))

    pipe, chunks, idx_results = index_documents(documents)
    engine = RetrievalEngine(prof, chunks, acls, rerank_fail=rerank_fail)

    print("Senaryo: %s  (profil=%s, expect_gate=%s)" %
          (sample.get("scenario"), pname, sample.get("expect_gate", "pass")))
    active = sum(1 for c in chunks if c.get("active"))
    print("İndekslenen doküman (6.1.3): %d  → chunk: %d (aktif=%d)  rerank=%s top_k=%d min_score=%.2f acl=%s" %
          (len(documents), len(chunks), active, engine.rerank_enabled, engine.top_k, engine.min_score,
           engine.enforce_acl))

    query_runs = []
    expect_fail = []
    for q in sample.get("queries", []):
        ctx = dict(q.get("context", {}))
        ctx["_qtext"] = q.get("query_text", "")
        r = engine.retrieve(q.get("query_text", ""), ctx, q.get("name"))
        query_runs.append((q, ctx, r))
        if r["status"] == "ok":
            top = r["results"][0]
            print("  soru %-22s → %d sonuç  #1=%s (score=%.3f%s)  ns-doc=%s" %
                  (q.get("name"), len(r["results"]), top["document_id"], top["score"],
                   "" if top["rerank_score"] is None else " rr=%.3f" % top["rerank_score"],
                   [x["document_id"] for x in r["results"]]))
        elif r["status"] == "empty":
            print("  soru %-22s → BOŞ (grounded=false, %s, aday=%d)" %
                  (q.get("name"), r["reason"], r["candidate_count"]))
        else:
            print("  soru %-22s → HATA %s: %s" % (q.get("name"), r["error_class"], r["detail"]))

        # Beklenti kontrolü.
        exp = q.get("expect", {})
        returned = {x["document_id"] for x in r["results"]}
        for doc in exp.get("relevant_documents", []):
            if doc not in returned and r["status"] == "ok":
                expect_fail.append("soru %s: relevant '%s' dönmedi" % (q.get("name"), doc))
        for doc in exp.get("deny_documents", []):
            if doc in returned:
                expect_fail.append("soru %s: yetkisiz '%s' döndü" % (q.get("name"), doc))
        if exp.get("top_document") and (r["status"] != "ok" or not r["results"]
                                        or r["results"][0]["document_id"] != exp["top_document"]):
            expect_fail.append("soru %s: top_document '%s' değil" % (q.get("name"), exp.get("top_document")))
        if "expect_status" in q and r["status"] != q["expect_status"]:
            expect_fail.append("soru %s: status %s beklenirken %s" % (q.get("name"), q["expect_status"], r["status"]))

    checks = evaluate_gates(sample, engine, query_runs)
    passed = sum(1 for _, ok_, _ in checks if ok_)
    print("\nBeklenti: %s" % ("✓ tümü tuttu" if not expect_fail else "✗ %d sapma" % len(expect_fail)))
    for m in expect_fail:
        print("  ✗ %s" % m)
    print("Kapılar (R1–R10): %d/%d geçti" % (passed, len(checks)))
    for gid, ok_, msg in checks:
        print("  %s %s — %s" % ("🟢" if ok_ else "🔴", gid, msg))

    all_pass = all(ok_ for _, ok_, _ in checks) and not expect_fail
    expect = sample.get("expect_gate", "pass")
    if expect == "fail":
        if all_pass:
            print("\n✗ expect_gate=fail ama tüm kapılar+beklenti geçti (negatif kanıt başarısız)")
            return 1
        print("\n✓ expect_gate=fail — beklenen kapı/beklenti elemesi gözlendi")
        return 0
    if not all_pass:
        print("\n✗ expect_gate=pass ama kapı(lar)/beklenti eledi")
        return 1
    print("\n✓ expect_gate=pass — tüm kapılar + beklenti geçti")
    return 0


# ── validate — statik spec/config/şema kapısı ────────────────────────────────────
def validate():
    spec = _load(SPEC_PATH)
    cfg = _load(CONFIG_PATH)
    n_ok = 0
    n_fail = 0
    fails = []

    def ok(cond, msg):
        nonlocal n_ok, n_fail
        if cond:
            n_ok += 1
        else:
            n_fail += 1
            fails.append(msg)

    # Spec temel alanlar + iz.
    ok(spec.get("wbs") == "6.2.1", "spec.wbs=6.2.1")
    ok(spec.get("phase") == "F1" and spec.get("priority") == "Must", "spec faz/öncelik")
    tr = spec.get("trace", {})
    for fr in ["FR-KB-004", "FR-KB-005", "FR-KB-006", "FR-KB-007", "FR-KB-011"]:
        ok(fr in tr.get("fr", []), "trace %s" % fr)
    ok("FR-TEN-002" in tr.get("fr", []), "trace FR-TEN-002 (namespace)")
    ok("FR-LLM-012" in tr.get("fr", []), "trace no-train (FR-LLM-012)")
    ok("NFR 10.7" in tr.get("nfr", []), "trace NFR 10.7 residency")
    ok(any("§10.2" in s for s in tr.get("sad", [])), "trace SAD §10.2")
    ok(any("6.1.3" in c for c in tr.get("consumes", [])), "consumes 6.1.3 IndexedChunk")
    ok(any("6.1.4" in c for c in tr.get("consumes", [])), "consumes 6.1.4 ACL pre-filtre")
    ok(any("6.2.2" in c for c in tr.get("consumed_by", [])) and any("6.2.3" in c for c in tr.get("consumed_by", [])),
       "consumed_by 6.2.2/6.2.3")
    ok(any("0.2.5" in v for v in tr.get("vendor_eval", [])), "vendor_eval 0.2.5 recall/latency kapısı")

    # Placement.
    pl = spec.get("placement", {})
    ok(pl.get("hot_path") is True, "retrieval hot-path (hot_path=true)")
    ok(pl.get("behind_spi") is True, "embedding+rerank SPI arkası")
    ok(len(pl.get("enforcement_points", [])) >= 2, "iki enforcement noktası")

    # SPI sözleşmesi.
    spi = spec.get("spi", {})
    ok("embed_batch" in spi.get("embedding_adapter_method", ""), "EmbeddingAdapter.embed_batch")
    ok("rerank" in spi.get("rerank_adapter_method", ""), "RerankAdapter.rerank")
    needed = {"result_key", "rank", "score", "rerank_score", "document_id", "doc_logical_key", "namespace",
              "tenant_id", "kb_id", "version_no", "chunk_no", "source_uri", "content", "char_count",
              "token_estimate", "content_hash", "classification"}
    ok(needed.issubset(set(spi.get("ranked_result_fields", []))), "RankedResult sözleşmesi tam")

    # Gates + invariants.
    g = spec.get("gates", {})
    for key in ["max_cross_namespace_returned", "max_unauthorized_returned", "max_inactive_returned",
                "require_topk_bound", "require_ranking_order", "require_recall_at_k", "require_rerank_order_only",
                "require_citation", "require_no_log", "require_grounding", "require_robust"]:
        ok(key in g, "gate '%s' var" % key)
    ok(g.get("max_cross_namespace_returned") == 0 and g.get("max_unauthorized_returned") == 0
       and g.get("max_inactive_returned") == 0, "cross-namespace/yetkisiz/inactive dönen=0")
    inv_ids = [i["id"] for i in spec.get("invariants", [])]
    ok(inv_ids == GATE_IDS, "invariant R1–R10 sırada (%s)" % inv_ids)
    ok(set(spec.get("error_taxonomy", {}).get("classes", [])) == ERROR_CLASSES, "error taksonomi spec==kod")
    ok(spec.get("grounding", {}).get("reason_no_relevant_source") == REASON_NO_RELEVANT, "NO_RELEVANT_SOURCE spec==kod")

    # Config profilleri.
    profs = cfg.get("profiles", {})
    ok({"pilot-default", "regulated-tr", "enterprise-eu", "no-rerank"}.issubset(set(profs)), "ana profiller var")
    ok(cfg.get("clearance_lattice") == ACL.CLEARANCE, "config clearance lattice")
    for name, p in profs.items():
        ok(int(p.get("top_k", 0)) > 0 or name == "degraded-noacl-train", "[%s] top_k>0" % name)
        ok(isinstance(p.get("rerank", {}).get("enabled"), bool), "[%s] rerank.enabled bool" % name)
        ok(int(p.get("rerank", {}).get("candidates", 0)) >= int(p.get("top_k", 1)), "[%s] candidates≥top_k" % name)
        ok(int(p.get("embedding", {}).get("dim", 0)) > 0, "[%s] embedding dim>0" % name)
        if name not in ("degraded-noacl-train",):
            ok(p.get("embedding", {}).get("no_train") is True, "[%s] no_train=true" % name)
            ok(p.get("embedding", {}).get("no_log") is True, "[%s] no_log=true" % name)
            ok(p.get("acl", {}).get("enforce_acl") is True, "[%s] enforce_acl=true" % name)
            ok(p.get("residency_region") == "home", "[%s] home-region" % name)

    # Sır/PII taraması (spec + config + sample'lar).
    files = [SPEC_PATH, CONFIG_PATH]
    if os.path.isdir(SAMPLES_DIR):
        for fn in sorted(os.listdir(SAMPLES_DIR)):
            if fn.endswith(".json"):
                files.append(os.path.join(SAMPLES_DIR, fn))
    leaks = []
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            raw = f.read()
        for m in SECRET_RE.finditer(raw):
            seg = raw[m.start():m.end()]
            if not _is_placeholder(seg.split(":")[-1].split("=")[-1].strip().strip("'\"")):
                leaks.append((os.path.basename(fp), "secret"))
        for m in CREDIT_CARD_RE.finditer(raw):
            digits = re.sub(r"\D", "", m.group())
            if len(digits) >= 13:
                leaks.append((os.path.basename(fp), "card-like"))
    ok(not leaks, "sır/PII sızıntısı yok (%s)" % leaks)

    ok(os.path.isfile(SPEC_PATH) and os.path.isfile(CONFIG_PATH), "spec+config dosyaları var")

    print("validate: %d geçti, %d başarısız" % (n_ok, n_fail))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if n_fail == 0 else 1


# ── selftest ─────────────────────────────────────────────────────────────────────
def _docs():
    """İki tenant + sınıflandırma/ACL çeşitli; retrieval testleri için lexical-ayırt edici metinler."""
    return [
        {"source_id": "iade", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
         "redaction_state": "not_required",
         "inline_text": "Iade politikasi musteri urunu 14 gun icinde iade edebilir kosul kullanilmamis ambalaj"},
        {"source_id": "kargo", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
         "redaction_state": "not_required",
         "inline_text": "Kargo teslimat suresi standart gonderi uc is gunu hizli gonderi ertesi gun ucret"},
        {"source_id": "ucret", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "confidential",
         "acl_ref": "acl:fin", "redaction_state": "applied",
         "inline_text": "Gizli ucret bandi terfi maas politikasi yil sonu gozden gecirme finans"},
    ]


def selftest():
    n = 0
    fails = []

    def expect(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            fails.append(msg)

    base_prof = {"top_k": 5, "min_score": 0.10, "rerank": {"enabled": True, "model": "rr", "candidates": 20},
                 "embedding": {"model": "ref-embed-v1", "dim": 256, "no_train": True, "no_log": True},
                 "acl": {"enforce_acl": True, "require_acl_classifications": ["confidential", "restricted"],
                         "redaction_mode": "redact", "default_acl_decision": "deny", "deny_wins": True},
                 "residency_region": "home", "allowed_regions": ["home"]}
    acls = {"acl:fin": {"default": "deny", "allow": ["group:finance"], "deny": ["group:contractors"]}}

    def ctx(**kw):
        b = {"tenant_id": "t-a", "kb_ids": ["kb-1"], "principals": ["role:human_agent"],
             "clearance": "internal", "channel_no_log": True}
        b.update(kw)
        b["_qtext"] = kw.get("_qtext", "")
        return b

    # 1) Embedder determinizm + dim + L2-norm + cosine lexical overlap.
    e = RetrievalEmbedder("m", 256, True, True)
    ectx = {"residency_region": "home", "allowed_regions": ["home"]}
    v1 = e.embed_batch(["iade urun gun"], ectx)[0]
    v2 = e.embed_batch(["iade urun gun"], ectx)[0]
    expect(v1 == v2, "1 embedder deterministik")
    expect(len(v1) == 256, "1b dim=256")
    expect(abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-9, "1c L2-norm=1")
    s_same = RetrievalEmbedder.cosine(e._vec("iade urun gun kosul"), e._vec("iade urun gun kosul"))
    s_part = RetrievalEmbedder.cosine(e._vec("iade urun gun kosul"), e._vec("kargo teslimat ucret hiz"))
    expect(s_same > 0.99 and s_part < s_same, "1d cosine: tam-örtüşme>kısmi (lexical)")

    # 2) Happy retrieval + ranking — iade sorusu iade dokümanını #1 getirir.
    _, chunks, _ = index_documents(_docs())
    eng = RetrievalEngine(base_prof, chunks, acls)
    r = eng.retrieve("iade urunu kac gun icinde iade edebilirim kosul",
                     ctx(clearance="internal", principals=["role:human_agent"]), "iade-q")
    expect(r["status"] == "ok" and r["results"][0]["document_id"] == "iade", "2 iade sorusu #1=iade")
    expect(len(r["results"]) <= eng.top_k, "2b top_k sınırı")
    # Sıralama monoton (rerank_score desc).
    rr = [x["rerank_score"] for x in r["results"]]
    expect(all(rr[i] >= rr[i + 1] for i in range(len(rr) - 1)), "2c rerank_score desc sıralı")

    # 3) ACL: confidential ucret dokümanı düşük clearance'a DÖNMEZ (R4).
    r2 = eng.retrieve("gizli ucret bandi terfi maas politikasi finans",
                      ctx(clearance="internal", principals=["role:human_agent"]), "ucret-low")
    docs = {x["document_id"] for x in r2["results"]}
    expect("ucret" not in docs, "3 confidential ucret düşük clearance'a dönmez")
    # Yetkili principal görür.
    r3 = eng.retrieve("gizli ucret bandi terfi maas politikasi finans",
                      ctx(clearance="confidential", principals=["group:finance"]), "ucret-fin")
    docs3 = {x["document_id"] for x in r3["results"]}
    expect("ucret" in docs3, "3b finance principal confidential ucret görür")

    # 4) Namespace isolation: t-b sorusu t-a chunk'larını görmez.
    docs_two = _docs() + [{"source_id": "iade", "tenant_id": "t-b", "kb_id": "kb-1", "classification": "public",
                           "redaction_state": "not_required",
                           "inline_text": "Iade politikasi musteri urunu 14 gun icinde iade edebilir kosul tenant b"}]
    _, chunks2, _ = index_documents(docs_two)
    eng2 = RetrievalEngine(base_prof, chunks2, acls)
    rb = eng2.retrieve("iade urun gun kosul", ctx(tenant_id="t-b", clearance="internal"), "iso-b")
    expect(all(x["tenant_id"] == "t-b" for x in rb["results"]), "4 t-b yalnız t-b chunk")
    expect(rb["results"] and rb["results"][0]["tenant_id"] == "t-b", "4b cross-tenant sızıntı yok")

    # 5) Grounding: alakasız soru → boş + grounded=false + NO_RELEVANT_SOURCE.
    rg = eng.retrieve("kuantum fizigi teleskop galaksi astronomi",
                      ctx(clearance="internal"), "off-topic")
    expect(rg["status"] == "empty" and rg["grounded"] is False and rg["reason"] == REASON_NO_RELEVANT,
           "5 alakasız soru grounded=false")
    expect(rg["results"] == [], "5b boş sonuç (uydurma yok)")

    # 6) Active-only: doküman v2 → yalnız v2 döner, v1 görünmez.
    docs_v = [{"source_id": "pol", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
               "redaction_state": "not_required", "doc_logical_key": "doc:pol",
               "inline_text": "Eski politika metni surum bir alfa beta gama"},
              {"source_id": "pol", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
               "redaction_state": "not_required", "doc_logical_key": "doc:pol",
               "inline_text": "Yeni politika metni surum iki delta epsilon zeta guncel"}]
    _, chunks_v, _ = index_documents(docs_v)
    engv = RetrievalEngine(base_prof, chunks_v, {})
    rv = engv.retrieve("politika metni surum guncel delta", ctx(clearance="internal"), "ver-q")
    expect(rv["status"] == "ok" and all(x["version_no"] == 2 for x in rv["results"]), "6 yalnız v2 (aktif)")

    # 7) Optional rerank OFF — geçerli sıralama döndürür (opsiyonellik).
    prof_off = dict(base_prof)
    prof_off["rerank"] = {"enabled": False, "model": "rr", "candidates": 20}
    engoff = RetrievalEngine(prof_off, chunks, acls)
    roff = engoff.retrieve("kargo teslimat suresi gonderi gun", ctx(clearance="internal"), "no-rerank")
    expect(roff["status"] == "ok" and roff["reranked"] is False, "7 rerank kapalı yol geçerli")
    sc = [x["score"] for x in roff["results"]]
    expect(all(sc[i] >= sc[i + 1] for i in range(len(sc) - 1)) and roff["results"][0]["document_id"] == "kargo",
           "7b cosine desc + kargo #1")

    # 8) Fail-closed: bağlam eksik → MISSING_QUERY_CONTEXT; boş soru → EMPTY_QUERY.
    expect(eng.retrieve("x", {"tenant_id": "t-a"}, "noctx")["error_class"] == "MISSING_QUERY_CONTEXT",
           "8 bağlam eksik fail-closed")
    expect(eng.retrieve("   ", ctx(clearance="internal"), "empty")["error_class"] == "EMPTY_QUERY",
           "8b boş soru")

    # 9) No-train fail-closed: hassas soru + train-açık embedder → NO_TRAIN_REQUIRED_VIOLATION.
    prof_train = dict(base_prof)
    prof_train["embedding"] = {"model": "m", "dim": 256, "no_train": False, "no_log": True}
    engt = RetrievalEngine(prof_train, chunks, acls)
    rt = engt.retrieve("gizli ucret", ctx(clearance="confidential", principals=["group:finance"],
                                          sensitive_query=True), "sens")
    expect(rt["error_class"] == "NO_TRAIN_REQUIRED_VIOLATION", "9 hassas soru train-açık fail-closed")

    # 10) Citation: her sonuç citation + budget alanları taşır; audit ham PII/soru içermez.
    rc = eng.retrieve("iade urun gun kosul ambalaj", ctx(clearance="internal"), "cite-q")
    x0 = rc["results"][0]
    expect(x0["document_id"] and x0["version_no"] and x0["chunk_no"] is not None and x0["source_uri"]
           and x0["content_hash"] and x0["token_estimate"] is not None, "10 citation alanları")
    blob = json.dumps(eng.audit, ensure_ascii=False)
    expect("content" not in {k for a in eng.audit for k in a} and "query_text" not in blob, "10b audit ham içerik yok")

    # 11) Top-k bound: çok doküman + küçük top_k.
    many = [{"source_id": "d%d" % i, "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
             "redaction_state": "not_required",
             "inline_text": "ortak terim alfa beta gama belge numara %d ek kelime" % i} for i in range(12)]
    _, cm, _ = index_documents(many)
    profk = dict(base_prof)
    profk["top_k"] = 3
    profk["min_score"] = 0.0
    engk = RetrievalEngine(profk, cm, {})
    rk = engk.retrieve("ortak terim alfa beta gama belge", ctx(clearance="internal"), "topk-q")
    expect(len(rk["results"]) == 3, "11 top_k=3 sınırı tam")

    # 12) Rerank order-only: result ⊆ vector-candidate (yeni doc yok).
    cand_vec = engk.embedder._vec("ortak terim alfa beta gama belge")
    ns_set = {IDX._namespace("t-a", "kb-1")}
    cand_keys = {_result_key(c) for c in engk.store
                 if c.get("namespace") in ns_set and c.get("active")
                 and RetrievalEmbedder.cosine(cand_vec, engk._doc_vec(c)) >= engk.min_score}
    expect(all(x["result_key"] in cand_keys for x in rk["results"]), "12 rerank küme-içi (yeni doc yok)")

    # 13) Robust: rerank sağlayıcı hatası → RERANK_PROVIDER_ERROR (çökme yok).
    engf = RetrievalEngine(base_prof, chunks, acls, rerank_fail=True)
    rf = engf.retrieve("iade urun gun", ctx(clearance="internal"), "rr-fail")
    expect(rf["status"] == "error" and rf["error_class"] == "RERANK_PROVIDER_ERROR", "13 rerank hata yapısal")

    # validate de geçmeli.
    rc_v = validate()
    expect(rc_v == 0, "14 validate() çıkış 0")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── schema ───────────────────────────────────────────────────────────────────────
def schema():
    spec = _load(SPEC_PATH)
    print("# WBS 6.2.1 — Vector search (top-k) + opsiyonel rerank (SAD §10.2) sözleşmeleri\n")
    print("Akış: Soru → embed (SPI) → vector search cosine top-n → rerank (opsiyonel SPI) → top-k → RankedResult\n")
    print("QueryContext: {tenant_id, kb_ids:[...], principals:['role:/group:/agent:/user:'], clearance,")
    print("  channel_no_log?, sensitive_query?}  — eksikse fail-closed MISSING_QUERY_CONTEXT\n")
    print("EmbeddingAdapter SPI (vendor-neutral, soru+chunk AYNI uzay): %s" % spec["spi"]["embedding_adapter_method"])
    print("RerankAdapter SPI (vendor-neutral, OPSİYONEL): %s\n" % spec["spi"]["rerank_adapter_method"])
    print("RankedResult (citation'lı — →6.2.2 trim / →6.2.3 kaynak atfı):")
    print("  " + ", ".join(spec["spi"]["ranked_result_fields"]))
    print("\nGrounding (FR-KB-007 → 3.3.4): aday yoksa grounded=false + reason=%s (UYDURMA YOK)" % REASON_NO_RELEVANT)
    print("Hata taksonomisi: " + ", ".join(sorted(spec["error_taxonomy"]["classes"])))
    print("\nKapılar (R1–R10):")
    for inv in spec["invariants"]:
        print("  %s — %s" % (inv["id"], inv["desc"][:94]))
    return 0


# ── main ─────────────────────────────────────────────────────────────────────────
def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    if cmd == "retrieve":
        if len(argv) < 3:
            print("kullanım: retrieval_probe.py retrieve <sample.json>")
            return 2
        return retrieve_cmd(argv[2])
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
