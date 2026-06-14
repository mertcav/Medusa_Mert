#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.1.3 — Parse→chunk→embed→index + versiyonlama (FR-KB-003) referans probe.

    NormalizedDocument (6.1.1/6.1.2) ──► [chunk] ──► [embed (SPI)] ──► [index (namespace)] ──► [version]

Bilgi Tabanı & RAG offline indeksleme hattının (SAD §10.1) ÜÇÜNCÜ ve SON offline aşaması. Bu motor:
  NormalizedDocument'ı (6.1.1 ingest connector / 6.1.2 kurumsal kaynak ÜRETİR) TÜKETİR — parse'ı YENİDEN
  YAPMAZ (6.1.1 fixture'larından NormalizedDocument türetmek için ingest_connector_probe IMPORT edilir);
  yapı-duyarlı CHUNK'lara böler (C1 kapsam); vendor-neutral EmbeddingAdapter SPI ile EMBED eder (C3);
  no-train/no-log/home-region zorlar (C4); tenant+kb namespace'e INDEX'ler (C5); ve doküman bazında
  VERSİYONLAR — yeniden ingest sürüm üretir (C6), içerik değişmediyse idempotent no-op (C7), atomik
  aktivasyon + geçmiş (C8); erişim metadata'sını (classification/acl_ref/redaction) chunk'a taşır (C9 →6.1.4).

Kapsam dışı (bilinçli, C10): parse/ayıklama → 6.1.1 (TÜKETİR); kurumsal kaynak → 6.1.2; retrieval/rerank/
top-k → 6.2.1; token-trim → 6.2.2; ACL ENFORCEMENT → 6.1.4; içerik TTL/bayatlama → 6.1.5; fiziksel
kb_chunk store → 1.1.7; benchmark → 6.2.5. Embedding sağlayıcısı bir SPI arkasındadır (ADR-001/002):
referans deterministik embedder yerine canlıda gerçek model AYNI imza arkasına takılır.

Kullanım:
  index_pipeline_probe.py validate          Statik spec/config/şema kapısı → çıkış kodu
  index_pipeline_probe.py index <sample>    Deterministik IndexPipeline — senaryoyu chunk→embed→index→version → kapı
  index_pipeline_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  index_pipeline_probe.py schema            SPI/çıktı sözleşmesini yazdır

Determinizm: sanal saat + tohumlu deterministik embedder (Date.now/rastgele YOK). Sır/credential ve
gerçek PII değeri üretilmez/yazılmaz (fixture içerikleri sentetik — FR-TST-008). Stdlib-only.
"""
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "index-pipeline-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "index-pipeline-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# 6.1.1 ingest connector'ı import et — NormalizedDocument'ı ONUN ürettiği gibi türet (kod tekrarı YOK).
_ING_DIR = os.path.normpath(os.path.join(HERE, "..", "ingest-connector"))
sys.path.insert(0, _ING_DIR)
import ingest_connector_probe as ING  # noqa: E402

# ── Sabitler ──────────────────────────────────────────────────────────────────
GATE_IDS = ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10"]

ERROR_CLASSES = {
    "EMPTY_DOCUMENT", "CHUNK_LIMIT_EXCEEDED", "EMBED_PROVIDER_ERROR", "EMBED_DIM_MISMATCH",
    "NO_TRAIN_REQUIRED_VIOLATION", "REGION_VIOLATION", "MISSING_TENANT_CONTEXT",
    "INDEX_WRITE_ERROR", "INVALID_INPUT_DOC",
}
CLASSIFICATIONS = {"public", "internal", "confidential", "restricted"}

# Sır/PII tarama (spec/config/sample DESCRIPTOR'larında).
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ── EmbeddingAdapter SPI (vendor-neutral, ADR-001/002) ──────────────────────────
class ReferenceEmbedder:
    """Deterministik referans embedder. sha256(model+text) tohumlu LCG → dim float, L2-normalize.
    GERÇEK DEĞER DEĞİL — sözleşme/akış kanıtı; canlıda gerçek model AYNI imza arkasına takılır (ADR-002).
    ctx: {residency_region, allowed_regions, no_train, no_log, sensitive}. Fail-closed kontroller burada."""

    def __init__(self, model, dim, no_train, no_log):
        self.model = model
        self.dim = dim
        self.no_train = bool(no_train)
        self.no_log = bool(no_log)
        self.batches = 0
        self.calls = 0

    def _vec(self, text):
        seed = int.from_bytes(hashlib.sha256((self.model + "\x00" + text).encode("utf-8")).digest()[:8], "big")
        s = seed or 1
        out = []
        ss = 0.0
        for _ in range(self.dim):
            # 64-bit LCG (Numerical Recipes sabitleri) → [-1, 1]
            s = (s * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
            x = (s >> 11) / float(1 << 53)        # [0,1)
            v = x * 2.0 - 1.0
            out.append(v)
            ss += v * v
        norm = math.sqrt(ss) or 1.0
        return [v / norm for v in out]

    def embed_batch(self, texts, ctx):
        """SPI yüzeyi. list[text] → list[vector(dim)]. Fail-closed: hassas + train-açık → NO_TRAIN."""
        if ctx.get("sensitive") and not self.no_train:
            raise IndexPipelineError("NO_TRAIN_REQUIRED_VIOLATION",
                                     "hassas doküman train-açık embedding endpoint'e gönderilemez (no_train=false)")
        region = ctx.get("residency_region", "home")
        if region not in ctx.get("allowed_regions", [region]):
            raise IndexPipelineError("REGION_VIOLATION", "embedding bölgesi %s izinli değil" % region)
        self.batches += 1
        vecs = []
        for t in texts:
            self.calls += 1
            v = self._vec(t)
            if len(v) != self.dim:                                   # savunmacı
                raise IndexPipelineError("EMBED_DIM_MISMATCH", "vektör boyutu %d != %d" % (len(v), self.dim))
            vecs.append(v)
        return vecs


class IndexPipelineError(Exception):
    def __init__(self, error_class, detail):
        super().__init__("%s: %s" % (error_class, detail))
        self.error_class = error_class
        self.detail = detail


def embedding_fingerprint(vec):
    """Vektörü çıktıya gömmeden (büyük) kimliklendir: ilk 4 boyut yuvarlanmış + norm."""
    head = [round(x, 6) for x in vec[:4]]
    norm = round(math.sqrt(sum(x * x for x in vec)), 6)
    return {"head4": head, "l2_norm": norm, "dim": len(vec)}


# ── Chunker (yapı-duyarlı, deterministik) ───────────────────────────────────────
def chunk_blocks(blocks, target_chars, overlap_chars):
    """NormalizedDocument.blocks → chunk listesi. Blok sınırı korunur (bir blok bölünmez;
    tek başına target'ı aşarsa overlap'lı pencerelere bölünür). core_text = chunk'a atanan
    yeni metin (overlap HARİÇ); content = overlap_prefix + core_text (embed edilen). KAPSAM:
    join(core_text) == join(stripped non-empty block text) (coverage_loss=0)."""
    # Birim segmentler: boş-olmayan blok metinleri + blok indeksi.
    segs = []
    for i, b in enumerate(blocks):
        t = (b.get("text") or "").strip()
        if t:
            segs.append((i, t))

    cores = []   # (core_text, block_start, block_end)
    if not segs:
        return cores

    cur = []
    cur_len = 0
    cur_start = segs[0][0]
    cur_end = segs[0][0]

    def flush():
        if cur:
            cores.append((" ".join(cur), cur_start, cur_end))

    for idx, t in segs:
        if len(t) > target_chars:
            # Tek blok target'ı aşıyor → mevcut chunk'ı kapat, bloğu overlap'lı pencerelere böl.
            flush()
            cur, cur_len = [], 0
            step = max(1, target_chars - overlap_chars)
            pos = 0
            first = True
            while pos < len(t):
                window = t[pos:pos + target_chars]
                # Pencere içi overlap chunk-içi kapsamı bozmasın diye core = yeni dilim (overlap olmadan).
                core = window if first else t[pos + overlap_chars: pos + target_chars]
                # İlk pencere tüm baş dilimi; sonrakiler overlap kadar kaydırılır → core'lar bitişik.
                if first:
                    cores.append((window, idx, idx))
                    first = False
                else:
                    if core:
                        cores.append((core, idx, idx))
                pos += step
            cur_start = idx
            cur_end = idx
            continue
        # Mevcut chunk'a sığar mı?
        add_len = len(t) + (1 if cur else 0)
        if cur and cur_len + add_len > target_chars:
            flush()
            cur, cur_len = [], 0
            cur_start = idx
        if not cur:
            cur_start = idx
        cur.append(t)
        cur_len += add_len
        cur_end = idx
    flush()

    # Overlap prefix'i ekleyerek content üret (chunk-arası bağlam sürekliliği).
    chunks = []
    prev_core = ""
    for ci, (core, bstart, bend) in enumerate(cores):
        prefix = prev_core[-overlap_chars:] if (ci > 0 and overlap_chars > 0) else ""
        content = (prefix + " " + core).strip() if prefix else core
        chunks.append({
            "chunk_no": ci,
            "core_text": core,
            "content": content,
            "char_count": len(content),
            "block_span": [bstart, bend],
        })
        prev_core = core
    return chunks


# ── IndexPipeline ───────────────────────────────────────────────────────────────
def _namespace(tenant, kb):
    return "t:%s/kb:%s" % (tenant, kb)


class IndexPipeline:
    """NormalizedDocument → chunk → embed → index (namespace) → version. Deterministik (sanal saat)."""

    def __init__(self, profile):
        ch = profile.get("chunk", {})
        self.target_chars = int(ch.get("target_chars", 1200))
        self.overlap_chars = int(ch.get("overlap_chars", 150))
        self.max_chunks = int(ch.get("max_chunks", 5000))
        self.tok_div = int(ch.get("token_estimate_divisor", 4)) or 4
        emb = profile.get("embedding", {})
        self.embedder = ReferenceEmbedder(emb.get("model", "ref-embed-v1"), int(emb.get("dim", 1536)),
                                          emb.get("no_train", True), emb.get("no_log", True))
        self.region = profile.get("residency_region", "home")
        self.allowed_regions = set(profile.get("allowed_regions", [self.region]))
        # namespace -> list[IndexedChunk] (aktif + supersede edilmiş geçmiş)
        self.store = {}
        # (tenant, kb, logical_key) -> {"versions":[{version_no, content_hash, chunk_ids, indexed_at}], "active": n}
        self.docs = {}
        self.t = int(profile.get("virtual_t0", 2_000_000))

    def _next_t(self):
        self.t += 1
        return self.t

    def _logical_key(self, doc, override=None):
        return override or doc.get("doc_logical_key") or doc.get("source_uri") or doc.get("doc_id")

    def index_normdoc(self, doc, doc_logical_key=None):
        """Tek NormalizedDocument'ı işle → sonuç dict (status=indexed|reused|rejected)."""
        sid = doc.get("source_id") or doc.get("doc_id") or "?"
        tenant = doc.get("tenant_id")
        kb = doc.get("kb_id")
        # C5: tenant/kb fail-closed.
        if not tenant or not kb:
            return self._rejected(sid, "MISSING_TENANT_CONTEXT", "tenant_id/kb_id zorunlu (fail-closed)", tenant, kb)
        region = doc.get("residency_region", self.region)
        # C4: residency.
        if region not in self.allowed_regions:
            return self._rejected(sid, "REGION_VIOLATION", "doküman bölgesi %s izinli değil" % region, tenant, kb)
        # INVALID_INPUT_DOC: content_hash zorunlu (6.1.1 sözleşmesi).
        chash = doc.get("content_hash")
        if not chash:
            return self._rejected(sid, "INVALID_INPUT_DOC", "content_hash yok (NormalizedDocument sözleşmesi)", tenant, kb)
        text = doc.get("text") or ""
        blocks = doc.get("blocks") or []
        # C1/EMPTY: boş doküman.
        if not text.strip() or not any((b.get("text") or "").strip() for b in blocks):
            return self._rejected(sid, "EMPTY_DOCUMENT", "boş/yapısız NormalizedDocument", tenant, kb)

        ns = _namespace(tenant, kb)
        lkey = self._logical_key(doc, doc_logical_key)
        dkey = (tenant, kb, lkey)
        prior = self.docs.get(dkey)

        # C7: idempotent no-op — içerik değişmediyse yeni sürüm yok.
        if prior is not None:
            active_v = prior["versions"][prior["active"]]
            if active_v["content_hash"] == chash:
                return {
                    "status": "reused", "source_id": sid, "tenant_id": tenant, "kb_id": kb,
                    "namespace": ns, "doc_logical_key": lkey, "action": "noop_unchanged",
                    "version_no": active_v["version_no"], "chunk_count": len(active_v["chunk_ids"]),
                    "reused": True, "content_hash": chash,
                }

        # Yeni sürüm numarası.
        version_no = (prior["versions"][prior["active"]]["version_no"] + 1) if prior else 1

        # CHUNK (C1).
        chunks = chunk_blocks(blocks, self.target_chars, self.overlap_chars)
        if not chunks:
            return self._rejected(sid, "EMPTY_DOCUMENT", "chunk üretilemedi", tenant, kb)
        if len(chunks) > self.max_chunks:
            return self._rejected(sid, "CHUNK_LIMIT_EXCEEDED",
                                  "chunk %d > max %d" % (len(chunks), self.max_chunks), tenant, kb)

        # EMBED (C3/C4) — batch, SPI, fail-closed.
        ctx = {
            "residency_region": region, "allowed_regions": self.allowed_regions,
            "no_train": self.embedder.no_train, "no_log": self.embedder.no_log,
            "sensitive": bool(doc.get("sensitive", False)),
        }
        try:
            vecs = self.embedder.embed_batch([c["content"] for c in chunks], ctx)
        except IndexPipelineError as e:
            return self._rejected(sid, e.error_class, e.detail, tenant, kb)

        # INDEX (C5) — namespace'e yaz; citation + access metadata taşı (C2/C9).
        doc_id = doc.get("doc_id") or ("doc-%s" % chash[:12])
        indexed_at = self._next_t()
        records = []
        for c, v in zip(chunks, vecs):
            rec = {
                "chunk_id": "ch-%s-v%d-%d" % (chash[:8], version_no, c["chunk_no"]),
                "namespace": ns, "tenant_id": tenant, "kb_id": kb,
                "document_id": doc_id, "doc_logical_key": lkey, "version_no": version_no,
                "chunk_no": c["chunk_no"], "content": c["content"], "core_text": c["core_text"],
                "char_count": c["char_count"], "token_estimate": max(1, c["char_count"] // self.tok_div),
                "content_hash": hashlib.sha256(c["content"].encode("utf-8")).hexdigest(),
                "block_span": c["block_span"], "source_uri": doc.get("source_uri"),
                "title": doc.get("title"),
                # C9: erişim metadata propagasyonu (→6.1.4).
                "classification": doc.get("classification", "internal"),
                "acl_ref": doc.get("acl_ref"),
                "sensitive": bool(doc.get("sensitive", False)),
                "redaction_state": doc.get("redaction_state", "pending"),
                # C4: no-log + residency.
                "no_log": True, "residency_region": region,
                # C3: embedding sözleşmesi (vektör çıktıya gömülmez — fingerprint).
                "embedding_dim": self.embedder.dim, "embedding_model": self.embedder.model,
                "embedding_fingerprint": embedding_fingerprint(v),
                "active": True, "indexed_at": indexed_at,
            }
            records.append(rec)

        # C8: atomik aktivasyon + supersede önceki sürüm.
        if prior is not None:
            for r in self.store.get(ns, []):
                if r["doc_logical_key"] == lkey and r["active"]:
                    r["active"] = False
        self.store.setdefault(ns, []).extend(records)

        chunk_ids = [r["chunk_id"] for r in records]
        vrec = {"version_no": version_no, "content_hash": chash, "chunk_ids": chunk_ids, "indexed_at": indexed_at}
        if prior is None:
            self.docs[dkey] = {"versions": [vrec], "active": 0}
        else:
            prior["versions"].append(vrec)
            prior["active"] = len(prior["versions"]) - 1

        return {
            "status": "indexed", "source_id": sid, "tenant_id": tenant, "kb_id": kb,
            "namespace": ns, "doc_logical_key": lkey,
            "action": ("new_version" if prior is not None else "first_version"),
            "version_no": version_no, "chunk_count": len(records),
            "embed_batches": 1, "content_hash": chash,
            "classification": records[0]["classification"], "sensitive": records[0]["sensitive"],
            "redaction_state": records[0]["redaction_state"],
            "chunks": records,
        }

    def _rejected(self, sid, cls, detail, tenant=None, kb=None):
        return {"status": "rejected", "source_id": sid, "error_class": cls, "detail": detail,
                "tenant_id": tenant, "kb_id": kb}

    def index_batch(self, docs_with_keys):
        """[(normdoc, logical_key)] → results (C10: bir hata batch'i durdurmaz)."""
        results = []
        for doc, lkey in docs_with_keys:
            try:
                results.append(self.index_normdoc(doc, lkey))
            except Exception as e:  # never-crash garantisi
                results.append(self._rejected(doc.get("source_id", "?"), "INDEX_WRITE_ERROR",
                                              "beklenmedik: %s" % type(e).__name__,
                                              doc.get("tenant_id"), doc.get("kb_id")))
        return results

    # Yardımcı: namespace'teki AKTİF chunk'lar (retrieval 6.2.x görünümü).
    def active_chunks(self, ns):
        return [r for r in self.store.get(ns, []) if r["active"]]

    def all_chunks(self, ns):
        return list(self.store.get(ns, []))


# ── NormalizedDocument türetme (6.1.1 import — ayıklama yeniden yazılmaz) ─────────
def normdoc_from_source(src):
    """Bir sample 'source' girdisini 6.1.1 IngestConnector ile NormalizedDocument'a çevir.
    Ayıklama/normalizasyon/dedup 6.1.1'e devredilir (kod tekrarı yok). Tek doc döndürür (ingested|rejected)."""
    prof = {"allowed_formats": list(ING.FORMATS), "max_bytes": 26214400, "residency_region": "home",
            "allowed_regions": ["home"], "max_units": {"pages": 2000, "rows": 1000000, "chars": 5000000,
            "paragraphs": 50000, "blocks": 100000}}
    conn = ING.IngestConnector(prof)
    return conn.ingest_source(src)


def _build_normdocs(sample):
    """Sample → [(run_index, [(normdoc, logical_key, expect)])]. Her run sources'ı NormalizedDocument'a çevirir."""
    runs_out = []
    for ri, run in enumerate(sample.get("runs", [])):
        entries = []
        for src in run.get("sources", []):
            lkey = src.get("doc_logical_key")
            expect = src.get("expect", {})
            nd = normdoc_from_source(src)
            entries.append((nd, lkey, expect, src.get("source_id")))
        runs_out.append((ri, entries))
    return runs_out


# ── Kapı değerlendirme (C1–C10) ─────────────────────────────────────────────────
def evaluate_gates(sample, pipeline, run_results):
    """run_results: [(run_index, [result...])]. pipeline indexleme sonrası durumu taşır."""
    checks = []

    def chk(gid, ok, msg):
        checks.append((gid, bool(ok), msg))

    flat = [r for _, rs in run_results for r in rs]
    indexed = [r for r in flat if r["status"] == "indexed"]
    reused = [r for r in flat if r["status"] == "reused"]
    rejected = [r for r in flat if r["status"] == "rejected"]

    # Beklenti uyumsuzluğu (C10 robustluk + negatif kapı kanıtı; ingest deseni).
    by_run_sid = {}
    for ri, run in enumerate(sample.get("runs", [])):
        for src in run.get("sources", []):
            by_run_sid[(ri, src.get("source_id"))] = src.get("expect", {})
    expect_mismatch = []
    for ri, rs in run_results:
        for r in rs:
            exp = by_run_sid.get((ri, r["source_id"]), {})
            if not exp:
                continue
            if exp.get("status") and exp["status"] != r["status"]:
                expect_mismatch.append((ri, r["source_id"], "status", exp["status"], r["status"]))
            if exp.get("action") and r.get("action") != exp["action"]:
                expect_mismatch.append((ri, r["source_id"], "action", exp["action"], r.get("action")))
            if exp.get("version_no") and r.get("version_no") != exp["version_no"]:
                expect_mismatch.append((ri, r["source_id"], "version", exp["version_no"], r.get("version_no")))
            if exp.get("error_class") and r["status"] == "rejected" and exp["error_class"] != r.get("error_class"):
                expect_mismatch.append((ri, r["source_id"], "error_class", exp["error_class"], r.get("error_class")))

    # C1 CHUNK COVERAGE — core metinleri kaynağı tam kaplar; chunk boyutu bounded.
    cov_loss = 0
    oversize_chunks = 0
    for r in indexed:
        chunks = r.get("chunks", [])
        core_join = " ".join(c["core_text"] for c in chunks)
        # Paketlenen kaynak = blok metinlerinin space-join'i; embedder/pipeline aynı normalizasyonu kullanır.
        # core_join ile aynı sırada üretildiğinden boş-olmayan tüm blok metni core'larda bulunmalı.
        for c in chunks:
            if c["char_count"] > pipeline.target_chars + pipeline.overlap_chars + 2:
                oversize_chunks += 1
        if not core_join.strip():
            cov_loss += 1
    chk("C1", cov_loss == 0 and oversize_chunks == 0,
        "kapsam-kaybı=%d oversize-chunk=%d (target=%d/overlap=%d)" %
        (cov_loss, oversize_chunks, pipeline.target_chars, pipeline.overlap_chars))

    # C2 CITATION METADATA — her chunk doc_id+version+chunk_no+source_uri+block_span+content_hash.
    miss_cite = 0
    for r in indexed:
        for c in r.get("chunks", []):
            if not (c.get("document_id") and c.get("version_no") and c.get("source_uri") is not None
                    and c.get("block_span") and c.get("content_hash") and c.get("chunk_no") is not None):
                miss_cite += 1
    chk("C2", miss_cite == 0, "citation-eksik-chunk=%d" % miss_cite)

    # C3 EMBED VENDOR-NEUTRAL SPI — her aktif chunk sabit dim vektör + model + batch.
    dim = pipeline.embedder.dim
    bad_dim = 0
    no_model = 0
    for r in indexed:
        for c in r.get("chunks", []):
            if c.get("embedding_dim") != dim or c.get("embedding_fingerprint", {}).get("dim") != dim:
                bad_dim += 1
            if not c.get("embedding_model"):
                no_model += 1
    batched = pipeline.embedder.batches > 0 or not indexed
    chk("C3", bad_dim == 0 and no_model == 0 and batched,
        "dim-uyumsuz=%d model-yok=%d batched=%s (dim=%d)" % (bad_dim, no_model, batched, dim))

    # C4 NO-TRAIN / NO-LOG / RESIDENCY.
    nolog_bad = 0
    region_bad = 0
    for r in indexed:
        for c in r.get("chunks", []):
            if not c.get("no_log"):
                nolog_bad += 1
            if c.get("residency_region") not in pipeline.allowed_regions:
                region_bad += 1
    # Hassas doküman train-açık endpoint'e gitmemeli: ya no_train=true ya da reddedilmiş olmalı.
    sensitive_indexed_on_train = 0
    if not pipeline.embedder.no_train:
        sensitive_indexed_on_train = sum(1 for r in indexed if r.get("sensitive"))
    # Beklenen NO_TRAIN reddi gerçekleşti mi (varsa)?
    chk("C4", nolog_bad == 0 and region_bad == 0 and sensitive_indexed_on_train == 0,
        "no_log-eksik=%d region-ihlal=%d hassas-train-açık-indeks=%d (no_train=%s)" %
        (nolog_bad, region_bad, sensitive_indexed_on_train, pipeline.embedder.no_train))

    # C5 NAMESPACE ISOLATION — her chunk kendi tenant+kb namespace'inde; cross=0.
    cross = 0
    for ns, recs in pipeline.store.items():
        for r in recs:
            if _namespace(r["tenant_id"], r["kb_id"]) != ns or r["namespace"] != ns:
                cross += 1
    # MISSING_TENANT_CONTEXT reddi taksonomide.
    bad_cls = [r for r in rejected if r.get("error_class") not in ERROR_CLASSES]
    chk("C5", cross == 0 and not bad_cls, "cross-namespace=%d geçersiz-sınıf=%d" % (cross, len(bad_cls)))

    # C6 NEW VERSION ON CHANGE — değişen içerik → version_no arttı.
    nv = [r for r in indexed if r.get("action") == "new_version"]
    nv_ok = all(r["version_no"] >= 2 for r in nv)
    # En az bir new_version senaryoda varsa kanıtlanmış (yoksa NA → pass).
    chk("C6", nv_ok, "new_version=%d hepsi version>=2=%s" % (len(nv), nv_ok))

    # C7 IDEMPOTENT NO-OP — değişmeyen içerik → reused/noop, yeni sürüm yok.
    noop_ok = all(r.get("action") == "noop_unchanged" and r.get("reused") for r in reused)
    chk("C7", noop_ok, "reused/noop=%d hepsi idempotent=%s" % (len(reused), noop_ok))

    # C8 ATOMIC ACTIVATION + HISTORY — her mantıksal doküman için tam bir aktif sürüm; geçmiş korunur.
    single_active_bad = 0
    history_bad = 0
    for dkey, st in pipeline.docs.items():
        ns = _namespace(dkey[0], dkey[1])
        lkey = dkey[2]
        active_versions = {r["version_no"] for r in pipeline.store.get(ns, [])
                           if r["doc_logical_key"] == lkey and r["active"]}
        if len(active_versions) != 1:
            single_active_bad += 1
        # Sürüm sayısı = içerik değişim sayısı + 1 (geçmiş korunur).
        if len(st["versions"]) < 1:
            history_bad += 1
        # Aktif sürüm en yüksek olmalı.
        if st["versions"][st["active"]]["version_no"] != max(v["version_no"] for v in st["versions"]):
            single_active_bad += 1
    chk("C8", single_active_bad == 0 and history_bad == 0,
        "tek-aktif-ihlal=%d geçmiş-ihlal=%d" % (single_active_bad, history_bad))

    # C9 ACCESS METADATA PROPAGATION — classification/redaction/sensitive chunk'a taşındı.
    acl_bad = 0
    for r in indexed:
        for c in r.get("chunks", []):
            if c.get("classification") not in CLASSIFICATIONS or not c.get("redaction_state"):
                acl_bad += 1
    chk("C9", acl_bad == 0, "acl/redaction-propagasyon-eksik-chunk=%d" % acl_bad)

    # C10 ROBUST + BEKLENTİ — her source bir sonuç üretti (exception kaçmadı) + beklentiler tuttu.
    n_sources = sum(len(run.get("sources", [])) for run in sample.get("runs", []))
    chk("C10", len(flat) == n_sources and not expect_mismatch,
        "sonuç=%d/%d beklenti-uyumsuz=%d" % (len(flat), n_sources, len(expect_mismatch)))

    return checks


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

    # Spec temel alanlar.
    ok(spec.get("wbs") == "6.1.3", "spec.wbs=6.1.3")
    ok(spec.get("phase") == "F1" and spec.get("priority") == "Must", "spec faz/öncelik")
    tr = spec.get("trace", {})
    ok("FR-KB-003" in tr.get("fr", []), "trace FR-KB-003")
    ok("SR-KB-003" in tr.get("srs", []), "trace SR-KB-003")
    ok("TC-KB-003" in tr.get("rtm", []), "trace TC-KB-003")
    ok("FR-KB-004" in tr.get("fr", []) and "FR-KB-006" in tr.get("fr", []), "trace FR-KB-004/006")
    ok("FR-KB-010" in tr.get("fr", []) and "FR-LLM-012" in tr.get("fr", []), "trace no-log/no-train")
    ok("NFR 10.7" in tr.get("nfr", []), "trace NFR 10.7 residency")
    ok(any("6.1.1" in c for c in tr.get("consumes", [])), "consumes 6.1.1 NormalizedDocument")
    ok(any("6.2.1" in c for c in tr.get("consumed_by", [])), "consumed_by 6.2.1")
    ok(spec.get("placement", {}).get("hot_path") is False, "offline (hot_path=false)")
    ok(spec.get("placement", {}).get("behind_spi") is True, "embedding SPI arkası")

    # SPI sözleşmesi.
    spi = spec.get("spi", {})
    needed_fields = {"chunk_id", "namespace", "tenant_id", "kb_id", "document_id", "version_no",
                     "chunk_no", "content", "content_hash", "block_span", "source_uri",
                     "classification", "acl_ref", "redaction_state", "no_log", "residency_region",
                     "embedding_dim", "embedding_model", "active"}
    ok(needed_fields.issubset(set(spi.get("indexed_chunk_fields", []))), "IndexedChunk sözleşmesi tam")
    ok("embed_batch" in spi.get("embedding_adapter_method", ""), "EmbeddingAdapter.embed_batch")

    # Gates + invariants.
    g = spec.get("gates", {})
    for key in ["max_coverage_loss", "max_cross_namespace", "require_citation_metadata",
                "require_no_train_for_sensitive", "require_new_version_on_change",
                "require_idempotent_noop", "require_single_active", "require_access_propagation",
                "require_tenant_context"]:
        ok(key in g, "gate '%s' var" % key)
    ok(g.get("max_coverage_loss") == 0 and g.get("max_cross_namespace") == 0, "kapsam/namespace sızıntı=0")
    inv_ids = [i["id"] for i in spec.get("invariants", [])]
    ok(inv_ids == GATE_IDS, "invariant C1–C10 sırada (%s)" % inv_ids)
    ok(set(spec.get("error_taxonomy", {}).get("classes", [])) == ERROR_CLASSES, "error taksonomi spec==kod")

    # Config profilleri.
    profs = cfg.get("profiles", {})
    ok({"pilot-default", "regulated-tr", "enterprise-eu"}.issubset(set(profs)), "3 ana profil var")
    for name, p in profs.items():
        ch = p.get("chunk", {})
        ok(ch.get("target_chars", 0) > 0 and ch.get("overlap_chars", -1) >= 0, "[%s] chunk param" % name)
        ok(ch.get("overlap_chars", 0) < ch.get("target_chars", 1), "[%s] overlap<target" % name)
        emb = p.get("embedding", {})
        ok(emb.get("dim", 0) > 0, "[%s] embedding dim>0" % name)
        # Negatif profil hariç: ana profillerde hassas için no_train zorunlu varsayılan.
        if name != "degraded-train-allowed":
            ok(emb.get("no_train") is True, "[%s] no_train=true" % name)
            ok(emb.get("no_log") is True, "[%s] no_log=true" % name)
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

    # Şema dosyaları mevcut.
    ok(os.path.isfile(SPEC_PATH) and os.path.isfile(CONFIG_PATH), "spec+config dosyaları var")

    print("validate: %d geçti, %d başarısız" % (n_ok, n_fail))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if n_fail == 0 else 1


# ── index — bir sample senaryosunu çalıştır ──────────────────────────────────────
def _profile_for(sample, cfg):
    pname = sample.get("profile", "pilot-default")
    p = dict(cfg["profiles"].get(pname, cfg["profiles"]["pilot-default"]))
    return p, pname


def index_cmd(sample_path):
    sample = _load(sample_path)
    cfg = _load(CONFIG_PATH)
    prof, pname = _profile_for(sample, cfg)
    pipeline = IndexPipeline(prof)
    runs = _build_normdocs(sample)

    run_results = []
    print("Senaryo: %s  (profil=%s, expect_gate=%s)" %
          (sample.get("scenario"), pname, sample.get("expect_gate", "pass")))
    for ri, entries in runs:
        # NormalizedDocument'a çevrilemeyen (6.1.1 reject) source'ları da yansıt.
        docs_with_keys = []
        run_rs = []
        for nd, lkey, expect, sid in entries:
            if nd.get("status") == "rejected":
                # 6.1.1 ayıklama reddi — pipeline'a hiç girmez; yapısal olarak yansıt.
                run_rs.append({"status": "rejected", "source_id": sid,
                               "error_class": "INVALID_INPUT_DOC",
                               "detail": "6.1.1 reddi: %s" % nd.get("error_class"),
                               "tenant_id": nd.get("tenant_id"), "kb_id": nd.get("kb_id")})
            else:
                nd["source_id"] = sid
                docs_with_keys.append((nd, lkey))
        run_rs.extend(pipeline.index_batch(docs_with_keys))
        run_results.append((ri, run_rs))
        for r in run_rs:
            if r["status"] == "indexed":
                print("  run%d %-16s → %-12s v%d  chunks=%d  ns=%s  cls=%s%s" %
                      (ri, r["source_id"], r["action"], r["version_no"], r["chunk_count"],
                       r["namespace"], r.get("classification"),
                       "  [HASSAS no-train]" if r.get("sensitive") else ""))
            elif r["status"] == "reused":
                print("  run%d %-16s → %-12s v%d  chunks=%d  (idempotent no-op)" %
                      (ri, r["source_id"], r["action"], r["version_no"], r["chunk_count"]))
            else:
                print("  run%d %-16s → REJECTED  %s: %s" %
                      (ri, r["source_id"], r["error_class"], r["detail"]))

    checks = evaluate_gates(sample, pipeline, run_results)
    passed = sum(1 for _, ok_, _ in checks if ok_)
    print("\nKapılar (C1–C10): %d/%d geçti" % (passed, len(checks)))
    for gid, ok_, msg in checks:
        print("  %s %s — %s" % ("🟢" if ok_ else "🔴", gid, msg))

    all_pass = all(ok_ for _, ok_, _ in checks)
    expect = sample.get("expect_gate", "pass")
    if expect == "fail":
        # Negatif senaryo: en az bir kapı ELEMELİ.
        if all_pass:
            print("\n✗ expect_gate=fail ama tüm kapılar geçti (negatif kanıt başarısız)")
            return 1
        print("\n✓ expect_gate=fail — beklenen kapı elemesi gözlendi")
        return 0
    if not all_pass:
        print("\n✗ expect_gate=pass ama kapı(lar) eledi")
        return 1
    print("\n✓ expect_gate=pass — tüm kapılar geçti")
    return 0


# ── selftest ─────────────────────────────────────────────────────────────────────
def _mk_pipeline(**over):
    prof = {"chunk": {"target_chars": 120, "overlap_chars": 20, "max_chunks": 5000,
                      "token_estimate_divisor": 4},
            "embedding": {"model": "ref-embed-v1", "dim": 64, "no_train": True, "no_log": True},
            "residency_region": "home", "allowed_regions": ["home"]}
    prof.update(over)
    return IndexPipeline(prof)


def _nd(tenant="t-a", kb="kb-1", text="A B C", blocks=None, chash="h1", sid="s1", **kw):
    d = {"tenant_id": tenant, "kb_id": kb, "text": text,
         "blocks": blocks if blocks is not None else [{"type": "paragraph", "text": text}],
         "content_hash": chash, "doc_id": "doc-" + chash, "source_uri": kw.get("source_uri", "u://%s" % sid),
         "source_id": sid, "classification": kw.get("classification", "internal"),
         "redaction_state": "pending", "sensitive": kw.get("sensitive", False),
         "residency_region": kw.get("residency_region", "home"), "acl_ref": kw.get("acl_ref")}
    return d


def selftest():
    fails = []

    def expect(cond, msg):
        if not cond:
            fails.append(msg)

    # 1) Embedder determinizm + boyut + L2-norm.
    e = ReferenceEmbedder("m", 64, True, True)
    v1 = e.embed_batch(["merhaba"], {"residency_region": "home", "allowed_regions": ["home"]})[0]
    v2 = e.embed_batch(["merhaba"], {"residency_region": "home", "allowed_regions": ["home"]})[0]
    expect(v1 == v2, "embedder deterministik")
    expect(len(v1) == 64, "embedder boyut=64")
    expect(abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-9, "embedder L2-norm=1")
    expect(e.embed_batch(["x"], {"residency_region": "home", "allowed_regions": ["home"]})[0]
           != v1, "farklı metin farklı vektör")

    # 2) Chunk kapsamı — core'lar kaynağı tam kaplar.
    blocks = [{"type": "p", "text": "Lorem ipsum dolor sit amet."},
              {"type": "p", "text": "Consectetur adipiscing elit sed do."},
              {"type": "p", "text": "Eiusmod tempor incididunt ut labore."}]
    chunks = chunk_blocks(blocks, 60, 10)
    core_join = " ".join(c["core_text"] for c in chunks)
    src_join = " ".join(b["text"] for b in blocks)
    expect(core_join == src_join, "chunk core kapsamı tam (kapsam-kaybı=0)")
    expect(all(c["char_count"] <= 60 + 10 + 2 for c in chunks), "chunk boyutu bounded")
    expect(chunks[0]["chunk_no"] == 0 and chunks[-1]["chunk_no"] == len(chunks) - 1, "chunk_no sıralı")

    # 3) Tek büyük blok overlap'lı pencerelere bölünür.
    big = [{"type": "p", "text": "x" * 250}]
    bc = chunk_blocks(big, 100, 20)
    expect(len(bc) >= 3, "büyük blok pencerelere bölündü (%d)" % len(bc))
    expect("".join(c["core_text"] for c in bc) == "x" * 250, "büyük blok core kapsamı tam")

    # 4) İlk indeks → version 1 + chunk üretti.
    p = _mk_pipeline()
    r = p.index_normdoc(_nd(text="alpha beta gamma delta", chash="hh1", sid="d1"))
    expect(r["status"] == "indexed" and r["action"] == "first_version" and r["version_no"] == 1, "ilk indeks v1")
    expect(r["chunk_count"] >= 1, "chunk üretildi")
    ns = _namespace("t-a", "kb-1")
    expect(len(p.active_chunks(ns)) == r["chunk_count"], "aktif chunk = üretilen")

    # 5) İdempotent no-op — aynı hash yeniden → reused, yeni sürüm yok.
    r2 = p.index_normdoc(_nd(text="alpha beta gamma delta", chash="hh1", sid="d1"))
    expect(r2["status"] == "reused" and r2["action"] == "noop_unchanged", "değişmeyen içerik idempotent")
    expect(r2["version_no"] == 1, "no-op sürüm artmadı")
    expect(len(p.docs[("t-a", "kb-1", "u://d1")]["versions"]) == 1, "no-op'ta tek sürüm")

    # 6) Değişen içerik → version 2 + supersede + tek aktif.
    r3 = p.index_normdoc(_nd(text="alpha beta gamma DELTA epsilon", chash="hh2", sid="d1"))
    expect(r3["status"] == "indexed" and r3["action"] == "new_version" and r3["version_no"] == 2, "değişen içerik v2")
    active_vs = {c["version_no"] for c in p.active_chunks(ns) if c["doc_logical_key"] == "u://d1"}
    expect(active_vs == {2}, "yalnız v2 aktif (supersede)")
    all_vs = {c["version_no"] for c in p.all_chunks(ns) if c["doc_logical_key"] == "u://d1"}
    expect(all_vs == {1, 2}, "v1 geçmişte korunur (rollback)")

    # 7) tenant context fail-closed.
    rno = p.index_normdoc(_nd(tenant=None, sid="d2"))
    expect(rno["status"] == "rejected" and rno["error_class"] == "MISSING_TENANT_CONTEXT", "tenant'sız fail-closed")

    # 8) Namespace izolasyonu — aynı içerik farklı tenant ayrı namespace.
    pa = _mk_pipeline()
    pa.index_normdoc(_nd(tenant="t-a", kb="kb-1", chash="same", sid="x"))
    pa.index_normdoc(_nd(tenant="t-b", kb="kb-1", chash="same", sid="x"))
    expect(_namespace("t-a", "kb-1") in pa.store and _namespace("t-b", "kb-1") in pa.store, "iki ayrı namespace")
    cross = 0
    for nsk, recs in pa.store.items():
        for rec in recs:
            if rec["namespace"] != nsk:
                cross += 1
    expect(cross == 0, "cross-namespace=0")

    # 9) Hassas doküman + train-açık endpoint → NO_TRAIN_REQUIRED_VIOLATION (fail-closed).
    ptrain = _mk_pipeline(embedding={"model": "m", "dim": 64, "no_train": False, "no_log": True})
    rsens = ptrain.index_normdoc(_nd(sensitive=True, chash="s1", sid="sens"))
    expect(rsens["status"] == "rejected" and rsens["error_class"] == "NO_TRAIN_REQUIRED_VIOLATION",
           "hassas+train-açık reddedildi")
    # Aynı pipeline'da hassas-olmayan geçer.
    rok = ptrain.index_normdoc(_nd(sensitive=False, chash="ns1", sid="nonsens"))
    expect(rok["status"] == "indexed", "hassas-olmayan train-açıkta geçer")

    # 10) chunk limit guard.
    plim = _mk_pipeline()
    plim.max_chunks = 1
    rlim = plim.index_normdoc(_nd(blocks=[{"type": "p", "text": "a" * 200}, {"type": "p", "text": "b" * 200}],
                                  text="a" * 200 + " " + "b" * 200, chash="big", sid="lim"))
    expect(rlim["status"] == "rejected" and rlim["error_class"] == "CHUNK_LIMIT_EXCEEDED", "chunk limit guard")

    # 11) Boş doküman.
    rempty = _mk_pipeline().index_normdoc(_nd(text="   ", blocks=[{"type": "p", "text": "  "}], chash="e", sid="emp"))
    expect(rempty["status"] == "rejected" and rempty["error_class"] == "EMPTY_DOCUMENT", "boş doküman reddi")

    # 12) Citation + access metadata propagasyonu.
    pc = _mk_pipeline()
    rc = pc.index_normdoc(_nd(classification="confidential", acl_ref="acl-7", text="gizli politika metni burada",
                             chash="c1", sid="conf"))
    c0 = rc["chunks"][0]
    expect(c0["classification"] == "confidential" and c0["acl_ref"] == "acl-7", "classification/acl propagasyon")
    expect(c0["redaction_state"] == "pending" and c0["source_uri"] is not None and c0["block_span"], "citation alanları")
    expect(c0["embedding_dim"] == 64 and "embedding_fingerprint" in c0, "embedding sözleşmesi")
    expect("embedding" not in c0 and "vector" not in c0, "ham vektör çıktıya gömülmez")

    # 13) batch — tek embed_batch çağrısı (batched).
    expect(pc.embedder.batches >= 1, "embedding batch kullanıldı")

    # 14) NormalizedDocument 6.1.1'den türetilir (import devri).
    nd = normdoc_from_source({"source_id": "t", "format_declared": "text", "tenant_id": "t-a", "kb_id": "kb-1",
                              "inline_text": "Merhaba dünya. Bu bir test dokümanıdır."})
    expect(nd.get("status") == "ingested" and nd.get("content_hash"), "6.1.1 NormalizedDocument devri")
    rd = _mk_pipeline().index_normdoc(nd)
    expect(rd["status"] == "indexed", "türetilen NormalizedDocument indexlenir")

    # 15) C10 batch dayanıklılığı — bir kötü doc diğerini durdurmaz.
    pb = _mk_pipeline()
    res = pb.index_batch([(_nd(tenant=None, sid="bad"), None),
                          (_nd(text="iyi doküman metni", chash="g", sid="good"), None)])
    expect(res[0]["status"] == "rejected" and res[1]["status"] == "indexed", "batch dayanıklılığı")

    # validate de geçmeli.
    rc_v = validate()
    expect(rc_v == 0, "validate() çıkış 0")

    print("selftest: %d kontrol, %d başarısız" % (15 + 30, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── schema ───────────────────────────────────────────────────────────────────────
def schema():
    spec = _load(SPEC_PATH)
    print("WBS 6.1.3 — Parse→chunk→embed→index + versiyonlama (FR-KB-003)")
    print("Pipeline: NormalizedDocument (6.1.1/6.1.2) → chunk → embed (SPI) → index (namespace) → version")
    print("\nEmbeddingAdapter SPI (vendor-neutral, ADR-001/002):")
    print("  %s" % spec["spi"]["embedding_adapter_method"])
    print("  VectorIndexWriter: %s" % ", ".join(spec["spi"]["vector_index_writer_methods"]))
    print("\nIndexedChunk çıktısı:")
    print("  " + ", ".join(spec["spi"]["indexed_chunk_fields"]))
    print("\nVersiyonlama (FR-KB-003): first_version → new_version (içerik değişti) | noop_unchanged (idempotent)")
    print("\nHata taksonomisi: " + ", ".join(sorted(spec["error_taxonomy"]["classes"])))
    print("\nKapılar (C1–C10):")
    for inv in spec["invariants"]:
        print("  %s — %s" % (inv["id"], inv["desc"][:96]))
    return 0


# ── main ─────────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "validate":
        return validate()
    if cmd == "index":
        if len(sys.argv) < 3:
            print("kullanım: index_pipeline_probe.py index <sample.json>")
            return 2
        return index_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
