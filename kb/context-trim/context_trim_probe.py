#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.2.2 — Token trimming (bağlam maliyeti sınırı) (SAD §10.2 + FR-KB-011/FR-RES-010) referans probe.

    ... 6.2.1 vector search top-k → rerank (opsiyonel) ──► [TRIM (token budget)] ──► LLM context (kaynak atıflı)

Bilgi Tabanı & RAG ONLINE retrieval hattının (SAD §10.2, hot-path) TRIM aşaması. Bu motor:
  6.2.1 RetrievalEngine'in ürettiği citation'lı RankedResult'ları (content+char_count+token_estimate+citation
  metadata TAŞINMIŞ) TÜKETİR — retrieval/embed/rerank'i YENİDEN YAPMAZ (retrieval_probe IMPORT edilir; o da
  index_pipeline_probe'u → ingest_connector_probe'u; kod tekrarı YOK); sabit bağlam segmentlerini (3.2.3 system
  prompt + 3.2.2 yuvarlanan özet + 3.2.1 history penceresi + tool spec) token-sayılı OPAK girdi olarak alır;
  toplam LLM bağlam bütçesi içinde RAG'a kalan alt-bütçeyi (rag_available) hesaplar (B1); RankedResult'ları RANK
  SIRASIYLA greedy paketler (B2 alaka-önce prefix); sığmayanı OPSİYONEL prefix-truncate ile doldurur (B4) +
  geri kalanı düşürür; toplam bağlam token'ı tavanı ASLA aşmaz (B1/B5 — SR-KB-011 kabul ölçütü); citation'ı
  korur (B3 → 6.2.3); bütçe hiçbirini sığdıramazsa grounded=false + BUDGET_EXHAUSTED (B7 anti-hallucination →
  3.3.4); deterministik (B6); audit yapısal no-log (B8); monoton (B9); structured TrimError (B10).

FR-RES-010 köprüsü: reserved_total (history/özet) BÜYÜDÜKÇE rag_available DARALIR → hem özetleme (3.2.2) hem
retrieval kısıtı (bu motor) token tüketimini DÜŞÜRÜR; toplam bağlam tavanı korunur.

Kapsam dışı (bilinçli, B10): retrieval/embed/rerank → 6.2.1 (TÜKETİR); kaynak-atfı sentezi → 6.2.3; history
özetleme → 3.2.2; versiyonlu prompt → 3.2.3; per-call bellek bütçe → 3.1.4; gerçek tokenizer → adapter arkası.
Vendor-neutral (ADR-001/002): yaklaşık tokenizer (char//divisor — 6.1.3 ile AYNI) bir SPI noktası; canlıda
gerçek model-özgü tokenizer AYNI imza arkasına. Trim mantığı sayıdan bağımsız.

Kullanım:
  context_trim_probe.py validate           Statik spec/config/şema kapısı → çıkış kodu
  context_trim_probe.py trim <sample>      Deterministik trim — 6.2.1 retrieval → trim → kapı (B1–B10)
  context_trim_probe.py selftest           Gömülü davranış kontrolleri → çıkış kodu
  context_trim_probe.py schema             SPI/TrimmedContext/karar sözleşmesini yazdır

Determinizm: saf token muhasebe + prefix truncation (Date.now/rastgele YOK). RankedResult'lar 6.2.1'den TÜRETİLİR.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture içerikleri sentetik — FR-TST-008). Stdlib-only.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "context-trim-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "context-budget-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# 6.2.1 retrieval'i import et — RankedResult'ı ONUN ürettiği gibi al (retrieval/embed/rerank tekrarı YOK).
_RET_DIR = os.path.normpath(os.path.join(HERE, "..", "retrieval"))
sys.path.insert(0, _RET_DIR)
import retrieval_probe as RET  # noqa: E402

# ── Sabitler ──────────────────────────────────────────────────────────────────
GATE_IDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"]

ERROR_CLASSES = {
    "MISSING_BUDGET_CONFIG", "INVALID_RESERVED", "INVALID_RANKED_INPUT", "INTERNAL_ERROR",
}
REASON_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
REASON_NO_RELEVANT = RET.REASON_NO_RELEVANT  # "NO_RELEVANT_SOURCE" — 6.2.1 ile tutarlı

# Citation kimlik alanları (B3) — kept sonuçta zorunlu.
CITATION_FIELDS = ["document_id", "doc_logical_key", "version_no", "chunk_no", "source_uri", "content_hash"]

SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
NUM_RE = re.compile(r"\d{6,}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


class TrimError(Exception):
    def __init__(self, error_class, detail):
        super().__init__("%s: %s" % (error_class, detail))
        self.error_class = error_class
        self.detail = detail


def content_digest(text):
    """Audit için içerik özeti — HAM content loglanmaz (PII/no-log hijyeni)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


# ── Tokenizer SPI (vendor-neutral, ADR-001/002) ────────────────────────────────
class ApproxTokenizer:
    """Referans yaklaşık tokenizer: approx_tokens(text) = max(1, len(text)//divisor) (boş→0).
    6.1.3 token_estimate ile AYNI (chars//divisor) → chunk'ın TAŞIDIĞI token_estimate doğrudan tüketilebilir;
    truncation token bütçesi AYNI birimle hesaplanır (tutarlı). Canlıda gerçek tokenizer AYNI imza arkasına."""

    def __init__(self, divisor):
        self.divisor = max(1, int(divisor))

    def approx_tokens(self, text):
        n = len(text or "")
        return 0 if n == 0 else max(1, n // self.divisor)

    def chars_for_tokens(self, n_tokens):
        """n token'a karşılık gelen karakter sayısı (prefix truncation için)."""
        return max(0, int(n_tokens) * self.divisor)


# ── ContextTrimmer — token bütçesi paketleme (SAD §10.2 trim aşaması) ───────────
class ContextTrimmer:
    """6.2.1 RankedResult listesi + reserved segmentler + bütçe → TrimmedContext.
    Rank-greedy (alaka-önce) contiguous prefix paketleme; opsiyonel kuyruk truncation; tavan ASLA aşılmaz."""

    def __init__(self, budget):
        self.context_token_budget = int(budget.get("context_token_budget", 0))
        self.response_reserve = int(budget.get("response_reserve_tokens", 0))
        self.rag_token_budget = int(budget.get("rag_token_budget", 0))
        prm = budget.get("per_result_max_tokens", None)
        self.per_result_max = int(prm) if prm is not None else None
        self.allow_truncation = bool(budget.get("allow_truncation", True))
        self.min_truncation_tokens = int(budget.get("min_truncation_tokens", 1))
        self.divisor = max(1, int(budget.get("token_estimate_divisor", 4)))
        self.min_keep_results = int(budget.get("min_keep_results", 0))
        self.tok = ApproxTokenizer(self.divisor)
        self.audit = []
        self._t = 0

    def _validate_budget(self):
        # context_token_budget response_reserve'i ZATEN dışlar (input bütçesi); ikisi de ≥0, biri >0.
        if self.context_token_budget <= 0:
            raise TrimError("MISSING_BUDGET_CONFIG", "context_token_budget > 0 zorunlu")
        if self.rag_token_budget <= 0:
            raise TrimError("MISSING_BUDGET_CONFIG", "rag_token_budget > 0 zorunlu")
        if self.response_reserve < 0 or self.per_result_max is not None and self.per_result_max <= 0:
            raise TrimError("MISSING_BUDGET_CONFIG", "response_reserve ≥0 / per_result_max >0")

    def _reserved_total(self, reserved):
        total = 0
        for seg in reserved or []:
            te = seg.get("token_estimate")
            if te is None or not isinstance(te, (int, float)) or te < 0:
                raise TrimError("INVALID_RESERVED",
                                "reserved '%s' token_estimate negatif/eksik" % seg.get("name"))
            total += int(te)
        return total

    def _truncate(self, result, n_tokens):
        """RankedResult'ı n_tokens'a prefix-truncate et (içerik = ilk n×divisor karakter). UYDURMA YOK."""
        content = result.get("content") or ""
        keep_chars = self.tok.chars_for_tokens(n_tokens)
        trunc = content[:keep_chars]
        ctx_tokens = self.tok.approx_tokens(trunc)
        return self._kept(result, trunc, ctx_tokens, truncated=(len(trunc) < len(content)))

    def _kept(self, result, content, ctx_tokens, truncated):
        """KeptResult sözleşmesi — citation kimliği (B3) korunur + bağlam metni/token (B4) ayrı."""
        return {
            "result_key": result.get("result_key"), "rank": result.get("rank"),
            "document_id": result.get("document_id"), "doc_logical_key": result.get("doc_logical_key"),
            "namespace": result.get("namespace"), "tenant_id": result.get("tenant_id"),
            "kb_id": result.get("kb_id"), "version_no": result.get("version_no"),
            "chunk_no": result.get("chunk_no"), "source_uri": result.get("source_uri"),
            "title": result.get("title"),
            "content": content,                                  # bağlamdaki GERÇEK metin (truncate olabilir)
            "content_hash": result.get("content_hash"),          # ORİJİNAL chunk kimliği (→6.2.3 atfı)
            "context_content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),  # bağlam metni hash
            "classification": result.get("classification"),
            "score": result.get("score"), "rerank_score": result.get("rerank_score"),
            "original_token_estimate": result.get("token_estimate"),
            "context_token_estimate": ctx_tokens, "truncated": bool(truncated),
        }

    def trim(self, ranked_results, reserved=None, ctx=None, scenario_name=None):
        try:
            return self._trim(ranked_results, reserved, ctx, scenario_name)
        except TrimError as e:
            self._audit(scenario_name, ctx, 0, 0, 0, False, e.error_class)
            return {"status": "error", "scenario": scenario_name, "error_class": e.error_class,
                    "detail": e.detail, "grounded": False, "reason": e.error_class,
                    "kept": [], "dropped": [], "budget": {}, "truncated_any": False,
                    "kept_count": 0, "dropped_count": 0}
        except Exception as e:  # never-crash (B10)
            self._audit(scenario_name, ctx, 0, 0, 0, False, "INTERNAL_ERROR")
            return {"status": "error", "scenario": scenario_name, "error_class": "INTERNAL_ERROR",
                    "detail": "beklenmedik: %s" % type(e).__name__, "grounded": False,
                    "reason": "INTERNAL_ERROR", "kept": [], "dropped": [], "budget": {},
                    "truncated_any": False, "kept_count": 0, "dropped_count": 0}

    def _trim(self, ranked_results, reserved, ctx, scenario_name):
        self._validate_budget()
        # 6.2.1 RankedResult sözleşme doğrulaması (B10 fail-closed).
        for r in ranked_results or []:
            if r.get("content") is None or r.get("token_estimate") is None or r.get("result_key") is None:
                raise TrimError("INVALID_RANKED_INPUT", "RankedResult content/token_estimate/result_key eksik")
            for f in CITATION_FIELDS:
                if r.get(f) is None and f != "source_uri":  # source_uri "" olabilir; ama anahtar var olmalı
                    if f not in r:
                        raise TrimError("INVALID_RANKED_INPUT", "RankedResult citation alanı '%s' eksik" % f)

        reserved_total = self._reserved_total(reserved)
        # B1 — RAG'a kalan alt-bütçe. Sabit segmentler trim EDİLMEZ (upstream bütçesi).
        rag_available = max(0, min(self.rag_token_budget, self.context_token_budget - reserved_total))

        kept = []
        dropped = []
        running = 0
        truncated_any = False
        stopped = False

        for idx, r in enumerate(ranked_results or []):
            if stopped:
                dropped.append(self._drop_ref(r, "BUDGET"))
                continue
            te = int(r.get("token_estimate"))
            target = min(te, self.per_result_max) if self.per_result_max is not None else te
            if running + target <= rag_available:
                # Sığar. per-result cap nedeniyle target<te ise prefix-truncate.
                if target < te:
                    kr = self._truncate(r, target)
                    truncated_any = truncated_any or kr["truncated"]
                else:
                    kr = self._kept(r, r.get("content") or "", self.tok.approx_tokens(r.get("content") or ""),
                                    truncated=False)
                kept.append(kr)
                running += kr["context_token_estimate"]
            else:
                # Tam sığmaz → opsiyonel kuyruk truncation.
                remaining = rag_available - running
                if self.allow_truncation and remaining >= self.min_truncation_tokens:
                    kr = self._truncate(r, remaining)
                    if kr["context_token_estimate"] > 0:
                        kept.append(kr)
                        running += kr["context_token_estimate"]
                        truncated_any = truncated_any or kr["truncated"]
                    else:
                        dropped.append(self._drop_ref(r, "BUDGET"))
                else:
                    dropped.append(self._drop_ref(r, "BUDGET"))
                stopped = True  # alaka-önce: sığmayandan sonra düşük-rankli sonuçlar düşürülür (B2 suffix)

        total_context_tokens = reserved_total + running
        headroom = self.context_token_budget - total_context_tokens

        # B7 grounding — 6.2.1 grounded ama bütçe hiçbirini sığdıramadı.
        had_input = bool(ranked_results)
        grounded = len(kept) >= 1
        if not grounded and had_input:
            reason = REASON_BUDGET_EXHAUSTED
            status = "empty"
        elif not had_input:
            # 6.2.1 zaten boş/ungrounded — pass-through (yeni kaynak üretmez).
            reason = (ctx or {}).get("upstream_reason", REASON_NO_RELEVANT)
            status = "empty"
            grounded = False
        else:
            reason = None
            status = "ok"

        budget = {
            "context_token_budget": self.context_token_budget,
            "response_reserve_tokens": self.response_reserve,
            "reserved_total": reserved_total,
            "rag_token_budget": self.rag_token_budget,
            "rag_available": rag_available, "rag_used": running,
            "total_context_tokens": total_context_tokens, "headroom": headroom,
        }
        self._audit(scenario_name, ctx, len(ranked_results or []), len(kept), running, grounded, reason)
        return {"status": status, "scenario": scenario_name, "grounded": grounded, "reason": reason,
                "kept": kept, "dropped": dropped, "budget": budget, "truncated_any": truncated_any,
                "kept_count": len(kept), "dropped_count": len(dropped)}

    def _drop_ref(self, r, reason):
        return {"result_key": r.get("result_key"), "rank": r.get("rank"),
                "drop_reason": reason, "token_estimate": r.get("token_estimate")}

    def _audit(self, scenario_name, ctx, n_in, n_kept, rag_used, grounded, reason):
        """B8 yapısal audit — HAM content/soru/PII YAZILMAZ (yalnız sayılar + content_digest yok)."""
        self._t += 1
        self.audit.append({
            "ts": self._t, "scenario": scenario_name,
            "tenant_id": (ctx or {}).get("tenant_id"), "kb_ids": (ctx or {}).get("kb_ids"),
            "results_in": n_in, "kept": n_kept, "rag_used": rag_used,
            "grounded": bool(grounded), "reason": reason, "no_log": True,
        })


# ── 6.2.1 retrieval → RankedResult listesi üret (TÜKETİR — yeniden yapmaz) ────────
def _retrieve_results(sample):
    """Sample documents+queries → 6.2.1 RetrievalEngine → query başına RankedResult listesi (+ grounded).
    retrieval_probe IMPORT edilir; retrieval/embed/rerank YENİDEN YAPILMAZ."""
    ret_cfg = _load(os.path.join(_RET_DIR, "config", "retrieval-profiles.json"))
    rprof_name = sample.get("retrieval_profile", "pilot-default")
    rprof = dict(ret_cfg["profiles"].get(rprof_name, ret_cfg["profiles"]["pilot-default"]))
    acls = sample.get("acls", {})
    _, chunks, _ = RET.index_documents(sample.get("documents", []))
    engine = RET.RetrievalEngine(rprof, chunks, acls)
    runs = []
    for q in sample.get("queries", []):
        qctx = dict(q.get("context", {}))
        qctx["_qtext"] = q.get("query_text", "")
        r = engine.retrieve(q.get("query_text", ""), qctx, q.get("name"))
        runs.append((q, qctx, r))
    return runs, rprof_name


# ── Kapı değerlendirme (B1–B10) ──────────────────────────────────────────────────
def evaluate_gates(sample, trimmer, trim_runs):
    """trim_runs: [(query, retrieval_result, trimmed, reserved)]. trimmer audit'i taşır."""
    checks = []

    def chk(gid, ok, msg):
        checks.append((gid, bool(ok), msg))

    # B1 BUDGET CAP — toplam bağlam + rag tavanı.
    overflow = 0
    rag_over = 0
    for q, rr, t, reserved in trim_runs:
        if t["status"] == "error":
            continue
        b = t["budget"]
        if b.get("total_context_tokens", 0) > b.get("context_token_budget", 0):
            overflow += 1
        if b.get("rag_used", 0) > b.get("rag_available", 0) or b.get("rag_available", 0) > b.get("rag_token_budget", 0):
            rag_over += 1
    chk("B1", overflow == 0 and rag_over == 0,
        "bağlam-tavan-aşan=%d rag-tavan-aşan=%d (SR-KB-011: bağlam token'ı tavanı aşmaz)" % (overflow, rag_over))

    # B2 RANK PREFIX — kept = girdinin contiguous rank prefix'i; dropped = suffix.
    prefix_bad = 0
    for q, rr, t, reserved in trim_runs:
        if t["status"] == "error":
            continue
        kept_ranks = [k["rank"] for k in t["kept"]]
        # Kept rank'leri artan ve girdinin ilk |kept| rank'i (prefix).
        in_ranks = [x["rank"] for x in rr.get("results", [])]
        expect_prefix = in_ranks[:len(kept_ranks)]
        if kept_ranks != expect_prefix:
            prefix_bad += 1
        dropped_ranks = [d["rank"] for d in t["dropped"]]
        if dropped_ranks and any(dr < (kept_ranks[-1] if kept_ranks else -1) for dr in dropped_ranks):
            prefix_bad += 1
    chk("B2", prefix_bad == 0, "rank-prefix-ihlal=%d (alaka-önce contiguous prefix)" % prefix_bad)

    # B3 CITATION INTEGRITY — her kept citation kimliği taşır.
    cite_bad = 0
    for q, rr, t, reserved in trim_runs:
        for k in t["kept"]:
            if any(k.get(f) is None for f in CITATION_FIELDS if f != "source_uri") or "source_uri" not in k:
                cite_bad += 1
    chk("B3", cite_bad == 0, "citation-eksik kept=%d (→6.2.3)" % cite_bad)

    # B4 TRUNCATION SAFE — truncate content orijinalin prefix'i + token ≤ tahsis + context_content_hash tutar.
    trunc_bad = 0
    for q, rr, t, reserved in trim_runs:
        by_key = {x["result_key"]: x for x in rr.get("results", [])}
        for k in t["kept"]:
            if not k.get("truncated"):
                # Truncate değilse content orijinalle AYNI olmalı.
                src = by_key.get(k["result_key"])
                if src is not None and k["content"] != (src.get("content") or ""):
                    trunc_bad += 1
                continue
            src = by_key.get(k["result_key"])
            if src is None:
                trunc_bad += 1
                continue
            orig = src.get("content") or ""
            if not orig.startswith(k["content"]):           # prefix (substring@0) — uydurma yok
                trunc_bad += 1
            if k["context_token_estimate"] > k["original_token_estimate"]:
                trunc_bad += 1
            if k["context_content_hash"] != hashlib.sha256(k["content"].encode("utf-8")).hexdigest():
                trunc_bad += 1
    chk("B4", trunc_bad == 0, "truncation-güvensiz kept=%d (prefix + token≤tahsis + hash tutar)" % trunc_bad)

    # B5 NO-EXCEED EVEN SINGLE-OVERSIZE — en üst chunk büyük olsa da tavan aşılmaz (B1 zaten kapsar; ek kanıt).
    single_over = 0
    for q, rr, t, reserved in trim_runs:
        if t["status"] == "error":
            continue
        b = t["budget"]
        # rag_used asla rag_available'ı aşmamalı, kept boş olsa bile.
        if b.get("rag_used", 0) > b.get("rag_available", 0):
            single_over += 1
    chk("B5", single_over == 0, "tek-büyük-chunk taşması=%d" % single_over)

    # B6 DETERMINISM — aynı girdi tekrar trim → birebir aynı.
    det_bad = 0
    for q, rr, t, reserved in trim_runs:
        t2 = trimmer.trim(rr.get("results", []), reserved, q.get("trim_context"), q.get("name"))
        a = {kk: t[kk] for kk in ("kept_count", "dropped_count", "grounded", "reason", "truncated_any")}
        b = {kk: t2[kk] for kk in ("kept_count", "dropped_count", "grounded", "reason", "truncated_any")}
        if a != b or [k["context_content_hash"] for k in t["kept"]] != [k["context_content_hash"] for k in t2["kept"]]:
            det_bad += 1
    chk("B6", det_bad == 0, "determinizm-ihlal=%d" % det_bad)

    # B7 GROUNDING CONSISTENCY — kept≥1→grounded; kept=0 & input vardı→BUDGET_EXHAUSTED; input boş→pass-through.
    grounding_bad = 0
    for q, rr, t, reserved in trim_runs:
        if t["status"] == "error":
            continue
        had_input = bool(rr.get("results"))
        if t["kept"]:
            if not t["grounded"]:
                grounding_bad += 1
        else:
            if t["grounded"]:
                grounding_bad += 1
            if had_input and t["reason"] != REASON_BUDGET_EXHAUSTED:
                grounding_bad += 1
            if not had_input and t["reason"] not in (REASON_NO_RELEVANT, REASON_BUDGET_EXHAUSTED):
                grounding_bad += 1
        exp_g = q.get("expect", {}).get("grounded")
        if exp_g is not None and bool(t["grounded"]) != bool(exp_g):
            grounding_bad += 1
    chk("B7", grounding_bad == 0, "grounding-ihlal=%d (kept=0+input→BUDGET_EXHAUSTED)" % grounding_bad)

    # B8 NO-LOG — audit yapısal, ham content/soru/PII yok.
    audit_keys = {k for a in trimmer.audit for k in a}
    audit_blob = json.dumps(trimmer.audit, ensure_ascii=False)
    audit_clean = ("content" not in audit_keys and "query_text" not in audit_keys
                   and not NUM_RE.search(audit_blob) and not EMAIL_RE.search(audit_blob))
    all_no_log = all(a.get("no_log") for a in trimmer.audit)
    chk("B8", audit_clean and all_no_log, "audit-temiz=%s no_log=%s" % (audit_clean, all_no_log))

    # B9 MONOTONICITY — rag bütçe ARTTIKÇA kept token AZALMAZ (sağlık özelliği).
    mono_bad = 0
    for q, rr, t, reserved in trim_runs:
        if t["status"] == "error" or not rr.get("results"):
            continue
        big = dict(_budget_of(trimmer))
        big["rag_token_budget"] = trimmer.rag_token_budget * 4
        big["context_token_budget"] = trimmer.context_token_budget * 4
        tb = ContextTrimmer(big)
        t_big = tb.trim(rr.get("results", []), reserved, q.get("trim_context"), q.get("name"))
        if t_big["budget"]["rag_used"] < t["budget"]["rag_used"]:
            mono_bad += 1
    chk("B9", mono_bad == 0, "monotonluk-ihlal=%d (bütçe↑→kept token azalmaz)" % mono_bad)

    # B10 ROBUST — her query bir sonuç (exception kaçmadı) + error_class taksonomide.
    n_q = len(sample.get("queries", []))
    produced = len(trim_runs)
    bad_cls = [t for _, _, t, _ in trim_runs if t["status"] == "error" and t.get("error_class") not in ERROR_CLASSES]
    chk("B10", produced == n_q and not bad_cls,
        "üretilen=%d/%d geçersiz-hata-sınıfı=%d" % (produced, n_q, len(bad_cls)))

    return checks


def _budget_of(trimmer):
    return {
        "context_token_budget": trimmer.context_token_budget,
        "response_reserve_tokens": trimmer.response_reserve,
        "rag_token_budget": trimmer.rag_token_budget,
        "per_result_max_tokens": trimmer.per_result_max,
        "allow_truncation": trimmer.allow_truncation,
        "min_truncation_tokens": trimmer.min_truncation_tokens,
        "token_estimate_divisor": trimmer.divisor,
        "min_keep_results": trimmer.min_keep_results,
    }


# ── trim — bir sample senaryosunu çalıştır ───────────────────────────────────────
def _budget_for(sample, cfg):
    pname = sample.get("budget_profile", "pilot-default")
    return dict(cfg["profiles"].get(pname, cfg["profiles"]["pilot-default"])), pname


def trim_cmd(sample_path):
    sample = _load(sample_path)
    cfg = _load(CONFIG_PATH)
    budget, pname = _budget_for(sample, cfg)
    # Sample override (negatif/kenar senaryoları için).
    budget.update(sample.get("budget_override", {}))

    runs, rprof_name = _retrieve_results(sample)
    trimmer = ContextTrimmer(budget)

    print("Senaryo: %s  (budget_profile=%s, retrieval_profile=%s, expect_gate=%s)" %
          (sample.get("scenario"), pname, rprof_name, sample.get("expect_gate", "pass")))
    print("Bütçe: context=%d rag=%d per_result=%s allow_truncate=%s min_trunc=%d divisor=%d" %
          (trimmer.context_token_budget, trimmer.rag_token_budget,
           trimmer.per_result_max, trimmer.allow_truncation, trimmer.min_truncation_tokens, trimmer.divisor))

    trim_runs = []
    expect_fail = []
    for q, qctx, rr in runs:
        reserved = q.get("reserved_segments", sample.get("reserved_segments", []))
        tctx = dict(q.get("trim_context", {}))
        tctx.setdefault("tenant_id", qctx.get("tenant_id"))
        tctx.setdefault("kb_ids", qctx.get("kb_ids"))
        if rr["status"] != "ok":
            tctx["upstream_reason"] = rr.get("reason", REASON_NO_RELEVANT)
        results_in = rr.get("results", []) if rr["status"] == "ok" else []
        t = trimmer.trim(results_in, reserved, tctx, q.get("name"))
        trim_runs.append((q, rr, t, reserved))

        if t["status"] == "ok":
            b = t["budget"]
            print("  soru %-22s → kept=%d drop=%d  rag_used=%d/%d  total=%d/%d (headroom=%d)%s  kept-doc=%s" %
                  (q.get("name"), t["kept_count"], t["dropped_count"], b["rag_used"], b["rag_available"],
                   b["total_context_tokens"], b["context_token_budget"], b["headroom"],
                   "  [truncated]" if t["truncated_any"] else "", [k["document_id"] for k in t["kept"]]))
        elif t["status"] == "empty":
            print("  soru %-22s → BOŞ (grounded=false, %s)  reserved=%d rag_available=%d" %
                  (q.get("name"), t["reason"], t["budget"].get("reserved_total", 0),
                   t["budget"].get("rag_available", 0)))
        else:
            print("  soru %-22s → HATA %s: %s" % (q.get("name"), t["error_class"], t["detail"]))

        exp = q.get("expect", {})
        if "kept_documents" in exp:
            kept_docs = [k["document_id"] for k in t["kept"]]
            if kept_docs != exp["kept_documents"]:
                expect_fail.append("soru %s: kept_documents %s ≠ %s" % (q.get("name"), kept_docs, exp["kept_documents"]))
        if "max_total_tokens" in exp and t["status"] != "error":
            if t["budget"]["total_context_tokens"] > exp["max_total_tokens"]:
                expect_fail.append("soru %s: total %d > beklenen tavan %d" %
                                   (q.get("name"), t["budget"]["total_context_tokens"], exp["max_total_tokens"]))
        if "truncated_any" in exp and bool(t["truncated_any"]) != bool(exp["truncated_any"]):
            expect_fail.append("soru %s: truncated_any %s ≠ %s" % (q.get("name"), t["truncated_any"], exp["truncated_any"]))
        if "expect_status" in q and t["status"] != q["expect_status"]:
            expect_fail.append("soru %s: status %s beklenirken %s" % (q.get("name"), q["expect_status"], t["status"]))

    checks = evaluate_gates(sample, trimmer, trim_runs)
    passed = sum(1 for _, ok_, _ in checks if ok_)
    print("\nBeklenti: %s" % ("✓ tümü tuttu" if not expect_fail else "✗ %d sapma" % len(expect_fail)))
    for m in expect_fail:
        print("  ✗ %s" % m)
    print("Kapılar (B1–B10): %d/%d geçti" % (passed, len(checks)))
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

    ok(spec.get("wbs") == "6.2.2", "spec.wbs=6.2.2")
    ok(spec.get("phase") == "F1" and spec.get("priority") == "Must", "spec faz/öncelik")
    tr = spec.get("trace", {})
    for fr in ["FR-KB-011", "FR-RES-010"]:
        ok(fr in tr.get("fr", []), "trace %s" % fr)
    ok("FR-KB-006" in tr.get("fr", []), "trace FR-KB-006 (citation →6.2.3)")
    ok("FR-KB-007" in tr.get("fr", []), "trace FR-KB-007 (grounding)")
    for sr in ["SR-KB-011", "SR-RES-010"]:
        ok(sr in tr.get("srs", []), "trace %s" % sr)
    for tc in ["TC-KB-011", "TC-RES-010"]:
        ok(tc in tr.get("rtm", []), "trace %s" % tc)
    ok(any("§10.2" in s for s in tr.get("sad", [])), "trace SAD §10.2 (TRIM aşaması)")
    ok(any("6.2.1" in c for c in tr.get("consumes", [])), "consumes 6.2.1 RankedResult")
    ok(any("3.2.2" in c or "3.2.3" in c or "3.2.1" in c for c in tr.get("consumes", [])),
       "consumes reserved segment (3.2.x)")
    ok(any("6.2.3" in c for c in tr.get("consumed_by", [])), "consumed_by 6.2.3 kaynak atfı")

    pl = spec.get("placement", {})
    ok(pl.get("hot_path") is True, "trim hot-path (hot_path=true)")
    ok(pl.get("tokenizer_is_spi_point") is True, "tokenizer SPI noktası")
    ok(pl.get("consumes_ranked_results_from_6_2_1") is True, "6.2.1 RankedResult tüketir")
    ok(len(pl.get("enforcement_points", [])) >= 2, "iki enforcement noktası")

    spi = spec.get("spi", {})
    ok("approx_tokens" in spi.get("tokenizer_method", ""), "Tokenizer.approx_tokens SPI")
    needed_kept = {"result_key", "rank", "document_id", "version_no", "chunk_no", "source_uri",
                   "content", "content_hash", "context_token_estimate", "original_token_estimate",
                   "truncated", "context_content_hash"}
    ok(needed_kept.issubset(set(spi.get("kept_result_fields", []))), "KeptResult sözleşmesi tam")
    needed_budget = {"context_token_budget", "reserved_total", "rag_token_budget", "rag_available",
                     "rag_used", "total_context_tokens", "headroom"}
    ok(needed_budget.issubset(set(spi.get("budget_fields", []))), "budget sözleşmesi tam")

    g = spec.get("gates", {})
    for key in ["require_budget_cap", "max_context_overflow_tokens", "require_rank_prefix",
                "require_citation_integrity", "require_truncation_safe", "require_no_exceed_single",
                "require_determinism", "require_grounding", "require_no_log", "require_monotonicity",
                "require_robust"]:
        ok(key in g, "gate '%s' var" % key)
    ok(g.get("max_context_overflow_tokens") == 0, "max_context_overflow_tokens=0 (tavan aşılmaz)")
    inv_ids = [i["id"] for i in spec.get("invariants", [])]
    ok(inv_ids == GATE_IDS, "invariant B1–B10 sırada (%s)" % inv_ids)
    ok(set(spec.get("error_taxonomy", {}).get("classes", [])) == ERROR_CLASSES, "error taksonomi spec==kod")
    ok(spec.get("grounding", {}).get("budget_exhausted_reason") == REASON_BUDGET_EXHAUSTED,
       "BUDGET_EXHAUSTED spec==kod")

    # Config profilleri.
    profs = cfg.get("profiles", {})
    ok({"pilot-default", "regulated-tr", "enterprise-eu", "tight"}.issubset(set(profs)), "ana profiller var")
    for name, p in profs.items():
        ok(int(p.get("context_token_budget", 0)) > 0, "[%s] context_token_budget>0" % name)
        ok(int(p.get("rag_token_budget", 0)) > 0, "[%s] rag_token_budget>0" % name)
        ok(int(p.get("rag_token_budget", 0)) <= int(p.get("context_token_budget", 1)),
           "[%s] rag ≤ context" % name)
        ok(isinstance(p.get("allow_truncation"), bool), "[%s] allow_truncation bool" % name)
        ok(int(p.get("token_estimate_divisor", 0)) > 0, "[%s] divisor>0" % name)
        ok(int(p.get("min_truncation_tokens", 1)) >= 1, "[%s] min_truncation_tokens≥1" % name)

    # Sır/PII taraması.
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
def _mk_results(specs):
    """Sentetik RankedResult listesi üret (6.2.1 sözleşmesi). specs: [(doc_id, content)]."""
    out = []
    for i, (doc, content) in enumerate(specs):
        out.append({
            "result_key": "t-a:kb-1|%s" % doc, "rank": i,
            "document_id": doc, "doc_logical_key": "doc:%s" % doc, "namespace": "t-a:kb-1",
            "tenant_id": "t-a", "kb_id": "kb-1", "version_no": 1, "chunk_no": 0,
            "source_uri": "u://%s" % doc, "title": doc, "content": content,
            "char_count": len(content), "token_estimate": max(1, len(content) // 4),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "classification": "public", "score": 0.9 - 0.1 * i, "rerank_score": None,
        })
    return out


def selftest():
    n = 0
    fails = []

    def expect(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            fails.append(msg)

    div = 4
    # Her content ~25 token (100 char).
    c100 = "x" * 100
    results = _mk_results([("d0", c100), ("d1", c100), ("d2", c100), ("d3", c100)])

    # 1) Hepsi sığar (büyük bütçe) → trim yok, kept=4, total ≤ tavan.
    tr = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 1000,
                         "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    t = tr.trim(results, [], {"tenant_id": "t-a"}, "all-fit")
    expect(t["status"] == "ok" and t["kept_count"] == 4 and t["truncated_any"] is False, "1 hepsi sığar")
    expect(t["budget"]["total_context_tokens"] <= 1000, "1b tavan altı")
    expect([k["rank"] for k in t["kept"]] == [0, 1, 2, 3], "1c rank prefix korunur")

    # 2) Bütçe cap: rag=60 token → ~2 chunk (25+25=50) sığar, 3.cü kuyruk truncate (10), 4 düşer.
    tr2 = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 60,
                          "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    t2 = tr2.trim(results, [], {"tenant_id": "t-a"}, "cap")
    expect(t2["budget"]["rag_used"] <= 60, "2 rag_used ≤ tavan (60)")
    expect(t2["budget"]["rag_used"] == 60, "2b kuyruk truncate ile tam doldurulur (60)")
    expect(t2["truncated_any"] is True, "2c truncation oldu")
    expect([k["rank"] for k in t2["kept"]] == list(range(t2["kept_count"])), "2d kept rank prefix")
    expect(t2["dropped_count"] >= 1, "2e en az 1 düşer")

    # 3) Truncation SAFE: truncate edilen content orijinalin prefix'i.
    last_trunc = [k for k in t2["kept"] if k["truncated"]]
    expect(last_trunc and c100.startswith(last_trunc[-1]["content"]), "3 truncate content prefix")
    expect(all(k["context_token_estimate"] <= k["original_token_estimate"] for k in t2["kept"]), "3b token ≤ orijinal")
    expect(all(k["context_content_hash"] == hashlib.sha256(k["content"].encode("utf-8")).hexdigest()
               for k in t2["kept"]), "3c context_content_hash tutar")

    # 4) Citation integrity — her kept citation taşır + content_hash ORİJİNAL korunur (truncate olsa da).
    src0 = results[0]
    k0 = t2["kept"][0]
    expect(k0["content_hash"] == src0["content_hash"], "4 content_hash orijinal korunur")
    expect(all(all(k.get(f) is not None for f in CITATION_FIELDS) for k in t2["kept"]), "4b citation alanları")

    # 5) NO-EXCEED single oversize: rag=10, allow_truncation=False, top chunk 25 token → drop hepsi → grounded false.
    tr5 = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 10,
                          "allow_truncation": False, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    t5 = tr5.trim(results, [], {"tenant_id": "t-a"}, "single-oversize")
    expect(t5["kept_count"] == 0 and t5["grounded"] is False and t5["reason"] == REASON_BUDGET_EXHAUSTED,
           "5 tek-büyük-chunk → BUDGET_EXHAUSTED")
    expect(t5["budget"]["total_context_tokens"] <= 1000 and t5["budget"]["rag_used"] == 0, "5b tavan aşılmaz")

    # 5c) allow_truncation=True, rag=10 → top chunk 10 token'a truncate, kept=1 grounded.
    tr5c = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 10,
                           "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    t5c = tr5c.trim(results, [], {"tenant_id": "t-a"}, "single-trunc")
    expect(t5c["kept_count"] == 1 and t5c["grounded"] is True and t5c["budget"]["rag_used"] == 10, "5c truncate-fit")

    # 6) FR-RES-010: reserved (history) büyüdükçe rag_available daralır.
    tr6 = ContextTrimmer({"context_token_budget": 100, "rag_token_budget": 1000,
                          "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    reserved = [{"name": "system_prompt", "token_estimate": 30}, {"name": "history", "token_estimate": 50}]
    t6 = tr6.trim(results, reserved, {"tenant_id": "t-a"}, "history-squeeze")
    expect(t6["budget"]["reserved_total"] == 80, "6 reserved_total=80")
    expect(t6["budget"]["rag_available"] == 20, "6b rag_available = context−reserved = 20")
    expect(t6["budget"]["total_context_tokens"] <= 100, "6c toplam tavan altı")
    # Daha az history → daha çok rag_available (B9 yönü).
    t6b = tr6.trim(results, [{"name": "system_prompt", "token_estimate": 30}], {"tenant_id": "t-a"}, "less-hist")
    expect(t6b["budget"]["rag_available"] == 70 and t6b["budget"]["rag_used"] >= t6["budget"]["rag_used"],
           "6d az history → çok rag")

    # 7) Determinizm.
    ta = tr2.trim(results, [], {"tenant_id": "t-a"}, "det")
    tb = tr2.trim(results, [], {"tenant_id": "t-a"}, "det")
    expect([k["context_content_hash"] for k in ta["kept"]] == [k["context_content_hash"] for k in tb["kept"]],
           "7 deterministik")

    # 8) Monotonluk: rag bütçe ↑ → kept token azalmaz.
    small = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 40,
                            "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    big = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 200,
                          "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    ts = small.trim(results, [], {"tenant_id": "t-a"}, "s")
    tbg = big.trim(results, [], {"tenant_id": "t-a"}, "b")
    expect(tbg["budget"]["rag_used"] >= ts["budget"]["rag_used"], "8 bütçe↑ → kept token azalmaz")

    # 9) per_result_max: tek dev chunk bütçeyi yemez.
    big_chunk = _mk_results([("huge", "y" * 4000), ("small", "z" * 40)])  # 1000 token + 10 token
    tr9 = ContextTrimmer({"context_token_budget": 5000, "rag_token_budget": 5000, "per_result_max_tokens": 50,
                          "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    t9 = tr9.trim(big_chunk, [], {"tenant_id": "t-a"}, "per-result")
    huge_kept = [k for k in t9["kept"] if k["document_id"] == "huge"]
    expect(huge_kept and huge_kept[0]["context_token_estimate"] <= 50 and huge_kept[0]["truncated"], "9 per-result cap")
    expect(any(k["document_id"] == "small" for k in t9["kept"]), "9b küçük chunk yine sığar")

    # 10) Grounding pass-through: input boş (6.2.1 NO_RELEVANT) → grounded false + reason korunur.
    t10 = tr.trim([], [], {"tenant_id": "t-a", "upstream_reason": REASON_NO_RELEVANT}, "empty-in")
    expect(t10["status"] == "empty" and t10["grounded"] is False and t10["reason"] == REASON_NO_RELEVANT,
           "10 boş input pass-through")

    # 11) Fail-closed: bütçe eksik → MISSING_BUDGET_CONFIG; reserved negatif → INVALID_RESERVED.
    bad = ContextTrimmer({"context_token_budget": 0, "rag_token_budget": 100})
    expect(bad.trim(results, [], {}, "nobudget")["error_class"] == "MISSING_BUDGET_CONFIG", "11 bütçe eksik")
    expect(tr.trim(results, [{"name": "x", "token_estimate": -5}], {}, "negres")["error_class"] == "INVALID_RESERVED",
           "11b negatif reserved")
    # Geçersiz RankedResult (content yok).
    badres = [{"result_key": "k", "rank": 0, "token_estimate": 5}]
    expect(tr.trim(badres, [], {}, "badin")["error_class"] == "INVALID_RANKED_INPUT", "11c geçersiz RankedResult")

    # 12) Audit no-log: ham content yok.
    blob = json.dumps(tr2.audit, ensure_ascii=False)
    expect("content" not in {k for a in tr2.audit for k in a} and all(a.get("no_log") for a in tr2.audit),
           "12 audit no-log")

    # 13) Uçtan uca 6.2.1 entegrasyonu: gerçek retrieval → trim.
    sample = {
        "documents": [
            {"source_id": "iade", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
             "redaction_state": "not_required", "doc_logical_key": "doc:iade",
             "inline_text": "Iade suresi musteri urunu satin aldiktan sonra 14 gun icinde iade talebi kosul ambalaj " * 6},
            {"source_id": "kargo", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
             "redaction_state": "not_required", "doc_logical_key": "doc:kargo",
             "inline_text": "Kargo teslimat standart gonderi uc is gunu hizli gonderi ertesi gun takip " * 6}],
        "queries": [{"name": "iade-q", "query_text": "iade suresi kosul ambalaj talebi gun",
                     "context": {"tenant_id": "t-a", "kb_ids": ["kb-1"], "principals": ["role:human_agent"],
                                 "clearance": "internal", "channel_no_log": True}}],
    }
    runs, _ = _retrieve_results(sample)
    expect(runs and runs[0][2]["status"] == "ok" and runs[0][2]["results"], "13 6.2.1 retrieval üretti")
    rr_results = runs[0][2]["results"]
    tre = ContextTrimmer({"context_token_budget": 1000, "rag_token_budget": 30,
                          "allow_truncation": True, "min_truncation_tokens": 5, "token_estimate_divisor": div})
    te = tre.trim(rr_results, [], {"tenant_id": "t-a"}, "e2e")
    expect(te["budget"]["rag_used"] <= 30 and te["kept_count"] >= 1, "13b e2e trim tavan altı")
    # Citation 6.2.1'den korunur.
    expect(all(k["content_hash"] for k in te["kept"]), "13c citation 6.2.1'den korunur")

    rc_v = validate()
    expect(rc_v == 0, "14 validate() çıkış 0")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── schema ───────────────────────────────────────────────────────────────────────
def schema():
    spec = _load(SPEC_PATH)
    print("# WBS 6.2.2 — Token trimming (bağlam maliyeti sınırı) (SAD §10.2) sözleşmeleri\n")
    print("Akış: 6.2.1 RankedResult[] + reserved segment[] + bütçe → [TRIM] → LLM context (≤ tavan, kaynak atıflı)\n")
    print("ContextBudget: {context_token_budget, response_reserve_tokens?, rag_token_budget,")
    print("  per_result_max_tokens?, allow_truncation, min_truncation_tokens, token_estimate_divisor}")
    print("ReservedSegment: {name, token_estimate}  (3.2.3 prompt / 3.2.2 özet / 3.2.1 history — OPAK)\n")
    print("Tokenizer SPI (vendor-neutral): %s\n" % spec["spi"]["tokenizer_method"])
    print("KeptResult (citation korunur → 6.2.3; bağlam metni/token ayrı):")
    print("  " + ", ".join(spec["spi"]["kept_result_fields"]))
    print("\nBudget breakdown: " + ", ".join(spec["spi"]["budget_fields"]))
    print("\nFR-RES-010 köprüsü: reserved_total↑ → rag_available↓ (özetleme + retrieval kısıtı birlikte token düşürür)")
    print("Grounding (FR-KB-007 → 3.3.4): kept=0 & input vardı → grounded=false + reason=%s" % REASON_BUDGET_EXHAUSTED)
    print("Hata taksonomisi: " + ", ".join(sorted(spec["error_taxonomy"]["classes"])))
    print("\nKapılar (B1–B10):")
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
    if cmd == "trim":
        if len(argv) < 3:
            print("kullanım: context_trim_probe.py trim <sample.json>")
            return 2
        return trim_cmd(argv[2])
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
