#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.1.4 — Doküman bazında erişim yetkisi (metadata) (FR-KB-005) referans probe.

    IndexedChunk (6.1.3) ──► [ACCESS GATE: namespace · classification · ACL · sensitive · redaction] ──► yalnız YETKİLİ chunk

Bilgi Tabanı & RAG retrieval (SAD §10.2, online/hot-path) sınırındaki ERİŞİM ENFORCEMENT kapısıdır. Bu motor:
  6.1.3 IndexPipeline'ın ürettiği IndexedChunk'ları (classification/acl_ref/sensitive/redaction_state/active/
  namespace metadata C9 ile TAŞINMIŞ) TÜKETİR — chunk/embed/version'u YENİDEN YAPMAZ (index_pipeline_probe
  IMPORT edilir, o da ingest_connector_probe'u import eder; kod tekrarı YOK); ve bir RETRIEVAL isteğinin
  principal bağlamına (tenant/kb/agent + principal token + clearance + no-log kanal + amaç) göre hangi
  chunk'ların DÖNEBİLECEĞİNE karar verir. DENY-BY-DEFAULT / fail-closed.

Çekirdek değer FR-KB-005 / SR-KB-005 / TC-KB-005 (T): 'Yetkisiz dokümandan retrieval sonucu dönmez.'
İki uygulama noktası (defense-in-depth): (1) STORE PRE-FİLTRE yüklemi (6.2.1'e push — yetkisiz aday hiç
çekilmez); (2) AUTHORITATIVE POST-FİLTRE (dönen her chunk yeniden karar — store filtresine güvenilmez).
Pre-filtre post-filtreye göre SOUND+COMPLETE (G8).

Kapsam dışı (bilinçli, G10): chunk/embed/version → 6.1.3 (TÜKETİR); namespace yazım izolasyonu → 6.1.3 C5/
1.1.7 RLS; retrieval/rerank/top-k → 6.2.1; token-trim → 6.2.2; retrieval no-log → 6.2.4; panel/break-glass
content erişimi (Tier A/B, L0 altın kural) → FR-IAM-008/009/010 (AYRI yüzey). Vendor-neutral (ADR-001/002):
karar policy + doküman metadata'sına dayanır, sağlayıcıya değil.

Kullanım:
  access_control_probe.py validate          Statik spec/config/şema kapısı → çıkış kodu
  access_control_probe.py enforce <sample>  Deterministik AccessGate — senaryoyu index→authorize → kapı
  access_control_probe.py selftest          Gömülü davranış kontrolleri → çıkış kodu
  access_control_probe.py schema            Principal/karar sözleşmesini yazdır

Determinizm: sanal saat + tohumlu (Date.now/rastgele YOK); chunk'lar 6.1.3 IndexPipeline'dan TÜRETİLİR.
Sır/credential ve gerçek PII değeri üretilmez/yazılmaz (fixture içerikleri sentetik — FR-TST-008). Stdlib-only.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "access-control-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "access-control-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# 6.1.3 index pipeline'ı import et — IndexedChunk'ı ONUN ürettiği gibi türet (kod tekrarı YOK).
_IDX_DIR = os.path.normpath(os.path.join(HERE, "..", "index-pipeline"))
sys.path.insert(0, _IDX_DIR)
import index_pipeline_probe as IDX  # noqa: E402

# ── Sabitler ──────────────────────────────────────────────────────────────────
GATE_IDS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"]
CLEARANCE = ["public", "internal", "confidential", "restricted"]   # lattice (sıralı, SABİT)
CLASSIFICATIONS = set(CLEARANCE)
ALLOW_DECISIONS = {"ALLOWED", "ALLOWED_REDACTED"}
DENY_REASONS = {
    "MISSING_PRINCIPAL_CONTEXT", "CROSS_NAMESPACE", "INACTIVE_VERSION",
    "CLASSIFICATION_EXCEEDS_CLEARANCE", "ACL_REQUIRED", "ACL_NOT_GRANTED",
    "ACL_EXPLICIT_DENY", "MALFORMED_ACL", "SENSITIVE_REQUIRES_NO_LOG", "REDACTION_PENDING",
}
# Store pre-filtrenin (6.2.1) zorlayabildiği boyutlar — sensitive/redaction POST-filtreye özgü.
STORE_DIM_DENY = {
    "CROSS_NAMESPACE", "INACTIVE_VERSION", "CLASSIFICATION_EXCEEDS_CLEARANCE",
    "ACL_REQUIRED", "ACL_NOT_GRANTED", "ACL_EXPLICIT_DENY", "MALFORMED_ACL",
}
PRINCIPAL_TOKEN_KINDS = ("role:", "group:", "agent:", "user:")

# Sır/PII tarama (spec/config/sample DESCRIPTOR'larında).
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")

# Redaction maskeleme (illüstratif — gerçek PII tanıma motoru canlıda).
NUM_RE = re.compile(r"\d(?:[\d \-]{5,})\d")          # uzun rakam dizisi
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


def rank(level):
    """clearance/classification lattice rank'ı. Bilinmeyen sınıf → çok yüksek (fail-closed: kimse clearance'lamaz)."""
    return CLEARANCE.index(level) if level in CLEARANCE else 999


def mask(text):
    """Deterministik redaction maskeleme. Ham hassas PII dönmeden önce kaldırılır."""
    text = EMAIL_RE.sub("[REDACTED-EMAIL]", text)
    text = NUM_RE.sub("[REDACTED-NUM]", text)
    return text


def principal_digest(ctx):
    """Audit için principal özeti — token HAM değeri loglanmaz (PII/kardinalite hijyeni)."""
    if not ctx or not ctx.get("principals"):
        return "anon"
    raw = "|".join(sorted(ctx.get("principals", [])))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# ── AccessGate — doküman bazı erişim enforcement (FR-KB-005) ─────────────────────
class AccessGate:
    """Karar policy + chunk metadata'sından verilir (vendor-neutral, ADR-001/002). Fail-closed.
    profile: require_acl_classifications / redaction_mode / default_acl_decision / deny_wins.
    acls: {acl_ref: {default, allow:[token], deny:[token]}}."""

    def __init__(self, profile, acls=None, clock_start=0):
        self.require_acl = set(profile.get("require_acl_classifications", ["confidential", "restricted"]))
        rm = profile.get("redaction_mode", "redact")
        self.redaction_mode = rm if rm in ("redact", "deny") else "deny"   # geçersiz değer → fail-closed
        self.default_acl = profile.get("default_acl_decision", "deny")
        self.deny_wins = bool(profile.get("deny_wins", True))
        self.acls = acls or {}
        self.audit = []
        self._t = clock_start

    # — bağlam tamlığı —
    def _ctx_complete(self, ctx):
        return bool(ctx) and bool(ctx.get("tenant_id")) and isinstance(ctx.get("kb_ids"), list) \
            and bool(ctx.get("principals")) and ctx.get("clearance") in CLEARANCE

    def _principals(self, ctx):
        return set(ctx.get("principals", [])) | {"*"}

    # — tek chunk kararı (sıralı, fail-closed) —
    def decide(self, ctx, chunk):
        try:
            return self._decide(ctx, chunk)
        except Exception:
            # G10: bozuk metadata hiçbir exception KAÇIRMAZ → fail-closed DENY.
            return self._mk(chunk, "DENY", "MALFORMED_ACL", ctx)

    def _decide(self, ctx, chunk):
        if not self._ctx_complete(ctx):
            return self._mk(chunk, "DENY", "MISSING_PRINCIPAL_CONTEXT", ctx)
        # G2 namespace izolasyonu (savunma derinliği).
        if chunk.get("tenant_id") != ctx["tenant_id"]:
            return self._mk(chunk, "DENY", "CROSS_NAMESPACE", ctx)
        if chunk.get("kb_id") not in ctx["kb_ids"]:
            return self._mk(chunk, "DENY", "CROSS_NAMESPACE", ctx)
        # G7 yalnız aktif sürüm.
        if not chunk.get("active", False):
            return self._mk(chunk, "DENY", "INACTIVE_VERSION", ctx)
        # G3 classification lattice (monoton).
        cls = chunk.get("classification")
        if cls not in CLASSIFICATIONS or rank(cls) > rank(ctx["clearance"]):
            return self._mk(chunk, "DENY", "CLASSIFICATION_EXCEEDS_CLEARANCE", ctx)
        # G4 ACL çözümleme (deny wins + default deny).
        acl_ref = chunk.get("acl_ref")
        principals = self._principals(ctx)
        if acl_ref:
            acl = self.acls.get(acl_ref)
            if acl is None:
                return self._mk(chunk, "DENY", "MALFORMED_ACL", ctx)
            if self.deny_wins and (principals & set(acl.get("deny", []))):
                return self._mk(chunk, "DENY", "ACL_EXPLICIT_DENY", ctx)
            if not (principals & set(acl.get("allow", []))):
                if acl.get("default", self.default_acl) != "allow":
                    return self._mk(chunk, "DENY", "ACL_NOT_GRANTED", ctx)
        else:
            if cls in self.require_acl:
                return self._mk(chunk, "DENY", "ACL_REQUIRED", ctx)
        # G5 sensitive yalnız no-log kanal.
        if chunk.get("sensitive") and not ctx.get("channel_no_log", False):
            return self._mk(chunk, "DENY", "SENSITIVE_REQUIRES_NO_LOG", ctx)
        # G6 redaction enforcement.
        content = chunk.get("content", "")
        rstate = chunk.get("redaction_state", "pending")
        if rstate == "pending":
            if self.redaction_mode == "redact":
                return self._mk(chunk, "ALLOW", "ALLOWED_REDACTED", ctx, content=mask(content), redacted=True)
            return self._mk(chunk, "DENY", "REDACTION_PENDING", ctx)
        return self._mk(chunk, "ALLOW", "ALLOWED", ctx, content=content)

    def _mk(self, chunk, kind, reason, ctx=None, content=None, redacted=False):
        self._t += 1
        rec = {
            "chunk_id": chunk.get("chunk_id"), "document_id": chunk.get("document_id"),
            "tenant_id": chunk.get("tenant_id"), "kb_id": chunk.get("kb_id"),
            "namespace": chunk.get("namespace"), "active": chunk.get("active"),
            "decision": kind, "reason": reason,
            "classification": chunk.get("classification"), "sensitive": bool(chunk.get("sensitive")),
            "redacted": bool(redacted),
        }
        if kind == "ALLOW":
            rec["content"] = content if content is not None else chunk.get("content", "")
        # G9: yapısal audit kaydı — HAM içerik/PII/token YAZILMAZ.
        self.audit.append({
            "ts": self._t, "tenant_id": chunk.get("tenant_id"), "kb_id": chunk.get("kb_id"),
            "document_id": chunk.get("document_id"), "chunk_id": chunk.get("chunk_id"),
            "decision": kind, "reason": reason, "classification": chunk.get("classification"),
            "sensitive": bool(chunk.get("sensitive")), "principal_digest": principal_digest(ctx),
        })
        return rec

    def authorize(self, ctx, chunks):
        """Aday chunk listesini yetki kararından geçir → karar kayıtları (post-filtre, authoritative)."""
        return [self.decide(ctx, c) for c in chunks]

    # — store pre-filtre yüklemi (6.2.1'e push) —
    def prefilter_predicate(self, ctx):
        if not self._ctx_complete(ctx):
            return {"namespaces": [], "classification_in": [], "acl_tokens": [], "active": True, "_deny_all": True}
        allowed_cls = [c for c in CLEARANCE if rank(c) <= rank(ctx["clearance"])]
        ns = [IDX._namespace(ctx["tenant_id"], kb) for kb in ctx["kb_ids"]]
        return {"namespaces": ns, "classification_in": allowed_cls,
                "acl_tokens": sorted(ctx["principals"]), "active": True}

    def prefilter_admits(self, ctx, chunk):
        """Store-tarafı GEREKLİ koşul (namespace + classification + ACL). sensitive/redaction POST-filtrede."""
        pred = self.prefilter_predicate(ctx)
        if pred.get("_deny_all"):
            return False
        if chunk.get("namespace") not in pred["namespaces"]:
            return False
        if not chunk.get("active"):
            return False
        if chunk.get("classification") not in pred["classification_in"]:
            return False
        acl_ref = chunk.get("acl_ref")
        principals = self._principals(ctx)
        if acl_ref:
            acl = self.acls.get(acl_ref)
            if acl is None:
                return False
            if self.deny_wins and (principals & set(acl.get("deny", []))):
                return False
            if not (principals & set(acl.get("allow", []))):
                if acl.get("default", self.default_acl) != "allow":
                    return False
        else:
            if chunk.get("classification") in self.require_acl:
                return False
        return True


# ── 6.1.3 üzerinden IndexedChunk üretimi (TÜKETİR — yeniden yapmaz) ───────────────
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
        "redaction_state": d.get("redaction_state", "pending"),
        "residency_region": d.get("residency_region", "home"),
    }


def _mk_index_pipeline():
    """6.1.3 IndexPipeline (küçük dim — sözleşme yeterli; vektör değeri 6.1.4'ü etkilemez)."""
    prof = {"chunk": {"target_chars": 400, "overlap_chars": 40, "max_chunks": 5000, "token_estimate_divisor": 4},
            "embedding": {"model": "ref-embed-v1", "dim": 16, "no_train": True, "no_log": True},
            "residency_region": "home", "allowed_regions": ["home"]}
    return IDX.IndexPipeline(prof)


def index_documents(documents):
    """Sample documents → 6.1.3 ile indexle → tüm store chunk'ları (aktif + supersede). Sırayla; aynı
    logical key + farklı içerik → yeni sürüm + eski active=false (G7 girdisi)."""
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


# ── enforce — bir sample senaryosunu çalıştır ────────────────────────────────────
def _profile_for(sample, cfg):
    pname = sample.get("profile", "pilot-default")
    p = dict(cfg["profiles"].get(pname, cfg["profiles"]["pilot-default"]))
    return p, pname


def evaluate_gates(sample, gate, chunks, request_runs):
    """G1–G10 HARD kapıları. request_runs: [(req, ctx, decisions)]. NOT: chunk_id 6.1.3'te namespace-
    nitelikli DEĞİL (içerik-hash tabanlı) → aynı içerik farklı namespace'te çakışır; bu yüzden her karar
    KAYNAK chunk'ı ile zip ile eşlenir (id-lookup DEĞİL)."""
    checks = []

    def chk(gid, ok, msg):
        checks.append((gid, bool(ok), msg))

    # (ctx, chunk, decision) üçlüleri — decs, chunks ile 1:1 sırada.
    triples = [(ctx, c, d) for _, ctx, decs in request_runs for c, d in zip(chunks, decs)]

    def is_allow(d):
        return d["decision"] == "ALLOW"

    # G1 FAIL-CLOSED / unauthorized dönmez (SR-KB-005 başlık).
    unauth_returned = 0
    ctx_missing_allow = 0
    for req, ctx, decs in request_runs:
        deny_docs = set(req.get("expect", {}).get("deny_documents", []))
        for d in decs:
            if is_allow(d) and d["document_id"] in deny_docs:
                unauth_returned += 1
        if not gate._ctx_complete(ctx):
            ctx_missing_allow += sum(1 for d in decs if is_allow(d))
    chk("G1", unauth_returned == 0 and ctx_missing_allow == 0,
        "yetkisiz-dönen=%d  bağlam-eksik-izin=%d (deny-by-default)" % (unauth_returned, ctx_missing_allow))

    # G2 NAMESPACE ISOLATION: cross-namespace ALLOW=0.
    cross = sum(1 for ctx, c, d in triples
                if is_allow(d) and (c["tenant_id"] != ctx.get("tenant_id") or c["kb_id"] not in ctx.get("kb_ids", [])))
    chk("G2", cross == 0, "cross-namespace dönen chunk=%d" % cross)

    # G3 CLASSIFICATION LATTICE: classification>clearance ALLOW=0.
    cls_bad = sum(1 for ctx, c, d in triples
                  if is_allow(d) and rank(c["classification"]) > rank(ctx.get("clearance", "public")))
    chk("G3", cls_bad == 0, "clearance aşan dönen chunk=%d" % cls_bad)

    # G4 DENY WINS: explicit-deny principal'a ALLOW=0.
    denywin_bad = 0
    for ctx, c, d in triples:
        if not is_allow(d):
            continue
        acl = gate.acls.get(c.get("acl_ref")) if c.get("acl_ref") else None
        if acl and (gate._principals(ctx) & set(acl.get("deny", []))):
            denywin_bad += 1
    chk("G4", denywin_bad == 0, "explicit-deny'e rağmen dönen chunk=%d" % denywin_bad)

    # G5 SENSITIVE NO-LOG: sensitive ALLOW yalnız no-log kanal.
    sens_bad = sum(1 for ctx, c, d in triples
                   if is_allow(d) and c.get("sensitive") and not ctx.get("channel_no_log", False))
    chk("G5", sens_bad == 0, "no-log olmayan kanala dönen hassas chunk=%d" % sens_bad)

    # G6 REDACTION: pending+ALLOWED(maskelenmemiş)=0; ALLOWED_REDACTED içeriği ham PII içermez.
    redact_bad = 0
    for ctx, c, d in triples:
        if not is_allow(d):
            continue
        if c.get("redaction_state") == "pending" and not d["redacted"]:
            redact_bad += 1
        if d["redacted"]:
            cont = d.get("content", "")
            if NUM_RE.search(cont) or EMAIL_RE.search(cont):
                redact_bad += 1
    chk("G6", redact_bad == 0, "redaksiyon ihlali (maskelenmemiş pending / ham PII)=%d" % redact_bad)

    # G7 ACTIVE-ONLY: inactive ALLOW=0.
    inact = sum(1 for ctx, c, d in triples if is_allow(d) and not c.get("active"))
    chk("G7", inact == 0, "inactive (supersede) dönen chunk=%d" % inact)

    # G8 PREFILTER PARITY: soundness + completeness.
    sound_bad = 0
    complete_bad = 0
    for ctx, c, d in triples:
        admits = gate.prefilter_admits(ctx, c)
        if admits and (not is_allow(d)) and d["reason"] in STORE_DIM_DENY:
            sound_bad += 1
        if is_allow(d) and not admits:
            complete_bad += 1
    chk("G8", sound_bad == 0 and complete_bad == 0,
        "prefilter sound-ihlal=%d complete-ihlal=%d" % (sound_bad, complete_bad))

    # G9 DECISION AUDITABLE: her karar audit'te + geçerli reason + audit'te ham içerik/PII yok.
    total_dec = len(triples)
    reasons_ok = all(d["reason"] in (ALLOW_DECISIONS | DENY_REASONS) for _, _, d in triples)
    audit_total = len(gate.audit)
    audit_blob = json.dumps(gate.audit, ensure_ascii=False)
    audit_clean = ("content" not in {k for a in gate.audit for k in a}) \
        and not NUM_RE.search(audit_blob) and not EMAIL_RE.search(audit_blob)
    chk("G9", reasons_ok and audit_total >= total_dec and audit_clean,
        "karar=%d audit=%d reason-geçerli=%s audit-temiz=%s" %
        (total_dec, audit_total, reasons_ok, audit_clean))

    # G10 ROBUST: her aday chunk × her istek bir karar üretti (crash yok) + reason taksonomide.
    expected = sum(len(decs) for _, _, decs in request_runs)
    produced = total_dec
    chk("G10", expected == produced and reasons_ok,
        "üretilen karar=%d beklenen=%d (exception kaçışı yok)" % (produced, expected))

    return checks


def enforce_cmd(sample_path):
    sample = _load(sample_path)
    cfg = _load(CONFIG_PATH)
    prof, pname = _profile_for(sample, cfg)
    acls = sample.get("acls", {})
    documents = sample.get("documents", [])

    pipe, chunks, idx_results = index_documents(documents)
    gate = AccessGate(prof, acls)

    print("Senaryo: %s  (profil=%s, expect_gate=%s)" %
          (sample.get("scenario"), pname, sample.get("expect_gate", "pass")))
    print("İndekslenen doküman (6.1.3): %d  → aktif+supersede chunk: %d" %
          (len(documents), len(chunks)))

    request_runs = []
    for req in sample.get("requests", []):
        ctx = req.get("context", {})
        decs = gate.authorize(ctx, chunks)
        request_runs.append((req, ctx, decs))
        allowed_docs = sorted({d["document_id"] for d in decs if d["decision"] == "ALLOW"})
        denied = {}
        for d in decs:
            if d["decision"] == "DENY":
                denied[d["reason"]] = denied.get(d["reason"], 0) + 1
        print("  istek %-20s clearance=%-12s no_log=%s → izinli doc=%s  red=%s" %
              (req.get("name"), ctx.get("clearance"), ctx.get("channel_no_log"),
               allowed_docs, denied))

    # Beklenti kontrolü (allow_documents ≥1 izinli chunk / deny_documents 0 izinli chunk).
    expect_fail = []
    for req, ctx, decs in request_runs:
        allowed_docs = {d["document_id"] for d in decs if d["decision"] == "ALLOW"}
        exp = req.get("expect", {})
        for doc in exp.get("allow_documents", []):
            if doc not in allowed_docs:
                expect_fail.append("istek %s: '%s' izinli OLMALIYDI" % (req.get("name"), doc))
        for doc in exp.get("deny_documents", []):
            if doc in allowed_docs:
                expect_fail.append("istek %s: '%s' YETKİSİZ ama izinli döndü" % (req.get("name"), doc))

    checks = evaluate_gates(sample, gate, chunks, request_runs)
    passed = sum(1 for _, ok_, _ in checks if ok_)
    print("\nBeklenti: %s" % ("✓ tümü tuttu" if not expect_fail else "✗ %d sapma" % len(expect_fail)))
    for m in expect_fail:
        print("  ✗ %s" % m)
    print("Kapılar (G1–G10): %d/%d geçti" % (passed, len(checks)))
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


# ── validate — statik spec/config/şema kapısı ─────────────────────────────────────
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
    ok(spec.get("wbs") == "6.1.4", "spec.wbs=6.1.4")
    ok(spec.get("phase") == "F1" and spec.get("priority") == "Must", "spec faz/öncelik")
    tr = spec.get("trace", {})
    ok("FR-KB-005" in tr.get("fr", []), "trace FR-KB-005")
    ok("SR-KB-005" in tr.get("srs", []), "trace SR-KB-005")
    ok("TC-KB-005" in tr.get("rtm", []), "trace TC-KB-005")
    ok("FR-KB-004" in tr.get("fr", []) and "FR-TEN-002" in tr.get("fr", []), "trace namespace izolasyon")
    ok("FR-KB-010" in tr.get("fr", []), "trace no-log (FR-KB-010)")
    ok(any("6.1.3" in c for c in tr.get("consumes", [])), "consumes 6.1.3 IndexedChunk")
    ok(any("6.2.1" in c for c in tr.get("consumed_by", [])), "consumed_by 6.2.1")
    pl = spec.get("placement", {})
    ok(pl.get("hot_path") is True, "retrieval hot-path (hot_path=true)")
    ok(set(pl.get("enforcement_points", [])) and
       any("pre-filter" in e for e in pl.get("enforcement_points", [])) and
       any("post-filter" in e for e in pl.get("enforcement_points", [])), "iki enforcement noktası")

    # Principal/ACL/karar sözleşmeleri.
    pc = spec.get("principal_context", {})
    ok({"tenant_id", "kb_ids", "principals", "clearance"}.issubset(set(pc.get("required_fields", []))),
       "principal zorunlu alanlar")
    ok(pc.get("clearance_lattice") == CLEARANCE, "clearance lattice sırası")
    am = spec.get("acl_model", {})
    ok(am.get("deny_wins") is True and am.get("default_deny") is True, "ACL deny-wins + default-deny")
    ok(set(am.get("require_acl_classifications", [])) == {"confidential", "restricted"},
       "require_acl varsayılan confidential+restricted")

    # Karar taksonomisi spec==kod.
    dt = spec.get("decision_taxonomy", {})
    ok(set(dt.get("allow", [])) == ALLOW_DECISIONS, "allow taksonomi spec==kod")
    ok(set(dt.get("deny", [])) == DENY_REASONS, "deny taksonomi spec==kod")

    # Gates + invariants.
    g = spec.get("gates", {})
    for key in ["max_unauthorized_returned", "max_cross_namespace_returned", "require_fail_closed",
                "require_classification_lattice", "require_deny_wins", "require_sensitive_no_log",
                "require_redaction_enforced", "require_active_only", "require_prefilter_parity",
                "require_decision_auditable"]:
        ok(key in g, "gate '%s' var" % key)
    ok(g.get("max_unauthorized_returned") == 0 and g.get("max_cross_namespace_returned") == 0,
       "yetkisiz/cross-namespace dönen=0")
    inv_ids = [i["id"] for i in spec.get("invariants", [])]
    ok(inv_ids == GATE_IDS, "invariant G1–G10 sırada (%s)" % inv_ids)

    # Config profilleri.
    profs = cfg.get("profiles", {})
    ok({"pilot-default", "regulated-tr", "enterprise-eu"}.issubset(set(profs)), "3 ana profil var")
    ok(cfg.get("clearance_lattice") == CLEARANCE, "config clearance lattice")
    for name, p in profs.items():
        ok(isinstance(p.get("require_acl_classifications"), list), "[%s] require_acl liste" % name)
        if name != "degraded-open":
            ok(p.get("redaction_mode") in ("redact", "deny"), "[%s] redaction_mode geçerli" % name)
            ok(p.get("default_acl_decision") == "deny", "[%s] default deny" % name)
            ok(p.get("deny_wins") is True, "[%s] deny_wins" % name)
            ok({"confidential", "restricted"}.issubset(set(p.get("require_acl_classifications", []))),
               "[%s] confidential/restricted ACL ister" % name)

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
def _chunk(**kw):
    base = {"chunk_id": kw.get("chunk_id", "ch-1"), "document_id": kw.get("document_id", "doc-1"),
            "tenant_id": "t-a", "kb_id": "kb-1", "namespace": IDX._namespace("t-a", "kb-1"),
            "active": True, "classification": "internal", "acl_ref": None, "sensitive": False,
            "redaction_state": "applied", "content": "merhaba dunya"}
    base.update(kw)
    if "namespace" not in kw and ("tenant_id" in kw or "kb_id" in kw):
        base["namespace"] = IDX._namespace(base["tenant_id"], base["kb_id"])
    return base


def _ctx(**kw):
    base = {"tenant_id": "t-a", "kb_ids": ["kb-1"], "principals": ["role:human_agent"],
            "clearance": "internal", "channel_no_log": False, "purpose": "support"}
    base.update(kw)
    return base


def selftest():
    n = 0
    fails = []

    def expect(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            fails.append(msg)

    prof = {"require_acl_classifications": ["confidential", "restricted"],
            "redaction_mode": "redact", "default_acl_decision": "deny", "deny_wins": True}

    # 1) Happy: internal + clearance internal + applied → ALLOWED.
    g = AccessGate(prof)
    d = g.decide(_ctx(), _chunk())
    expect(d["decision"] == "ALLOW" and d["reason"] == "ALLOWED", "1 happy ALLOWED")

    # 2) Bağlam eksik → MISSING_PRINCIPAL_CONTEXT (fail-closed, G1).
    g = AccessGate(prof)
    d = g.decide({"tenant_id": "t-a"}, _chunk())
    expect(d["decision"] == "DENY" and d["reason"] == "MISSING_PRINCIPAL_CONTEXT", "2 bağlam eksik deny")
    d = g.decide(_ctx(clearance="bogus"), _chunk())
    expect(d["reason"] == "MISSING_PRINCIPAL_CONTEXT", "2b geçersiz clearance fail-closed")

    # 3) Cross-namespace (farklı tenant + farklı kb) → CROSS_NAMESPACE (G2).
    g = AccessGate(prof)
    expect(g.decide(_ctx(), _chunk(tenant_id="t-b"))["reason"] == "CROSS_NAMESPACE", "3 cross-tenant deny")
    expect(g.decide(_ctx(), _chunk(kb_id="kb-2"))["reason"] == "CROSS_NAMESPACE", "3b cross-kb deny")

    # 4) Classification lattice: confidential doküman + internal clearance → DENY (G3).
    g = AccessGate(prof)
    expect(g.decide(_ctx(clearance="internal"), _chunk(classification="confidential", acl_ref=None,
           redaction_state="applied"))["reason"] in ("CLASSIFICATION_EXCEEDS_CLEARANCE",),
           "4 düşük clearance yüksek sınıf deny")
    # yüksek clearance düşük sınıfı görür (acl yoksa + sınıf require_acl değil).
    expect(g.decide(_ctx(clearance="restricted"), _chunk(classification="public"))["decision"] == "ALLOW",
           "4b yüksek clearance düşük sınıf allow")

    # 5) ACL: deny-wins (G4) + not-granted + grant.
    acls = {"acl:hr": {"default": "deny", "allow": ["group:hr"], "deny": ["group:contractors"]}}
    g = AccessGate(prof, acls)
    ch = _chunk(classification="confidential", acl_ref="acl:hr", redaction_state="applied")
    expect(g.decide(_ctx(clearance="confidential", principals=["group:hr"]), ch)["decision"] == "ALLOW",
           "5 ACL allow grant")
    expect(g.decide(_ctx(clearance="confidential", principals=["group:sales"]), ch)["reason"] == "ACL_NOT_GRANTED",
           "5b ACL not granted")
    expect(g.decide(_ctx(clearance="confidential", principals=["group:hr", "group:contractors"]), ch)["reason"]
           == "ACL_EXPLICIT_DENY", "5c ACL deny wins (allow'da olsa bile)")

    # 6) ACL_REQUIRED: confidential + acl_ref yok → DENY.
    g = AccessGate(prof)
    expect(g.decide(_ctx(clearance="restricted"), _chunk(classification="confidential", acl_ref=None,
           redaction_state="applied"))["reason"] == "ACL_REQUIRED", "6 ACL required (sınıf ACL ister)")

    # 7) MALFORMED_ACL: çözülemez acl_ref → fail-closed DENY.
    g = AccessGate(prof, {"acl:x": {"allow": ["*"]}})
    expect(g.decide(_ctx(), _chunk(acl_ref="acl:yok"))["reason"] == "MALFORMED_ACL", "7 çözülemez ACL deny")

    # 8) SENSITIVE NO-LOG (G5): sensitive + kanal log'lu → DENY; no-log → allow.
    g = AccessGate(prof)
    sens = _chunk(sensitive=True, redaction_state="applied")
    expect(g.decide(_ctx(channel_no_log=False), sens)["reason"] == "SENSITIVE_REQUIRES_NO_LOG",
           "8 sensitive log'lu kanal deny")
    expect(g.decide(_ctx(channel_no_log=True), sens)["decision"] == "ALLOW", "8b sensitive no-log allow")

    # 9) REDACTION (G6): pending + redact modu → ALLOWED_REDACTED + ham PII gider.
    g = AccessGate(prof)
    raw = "Iletisim posta ornek@firma.com numara 1234 5678 9012 olarak kayitlidir"
    d = g.decide(_ctx(), _chunk(redaction_state="pending", content=raw))
    expect(d["decision"] == "ALLOW" and d["reason"] == "ALLOWED_REDACTED" and d["redacted"], "9 pending redact")
    expect("ornek@firma.com" not in d["content"] and "1234 5678 9012" not in d["content"], "9b ham PII maskelendi")
    # deny modu → REDACTION_PENDING.
    gd = AccessGate({"require_acl_classifications": ["confidential", "restricted"], "redaction_mode": "deny",
                     "default_acl_decision": "deny", "deny_wins": True})
    expect(gd.decide(_ctx(), _chunk(redaction_state="pending"))["reason"] == "REDACTION_PENDING",
           "9c pending deny modu")
    # geçersiz redaction_mode → fail-closed deny gibi davranır.
    gi = AccessGate({"require_acl_classifications": [], "redaction_mode": "ignore",
                     "default_acl_decision": "deny", "deny_wins": True})
    expect(gi.redaction_mode == "deny", "9d geçersiz redaction_mode fail-closed")

    # 10) ACTIVE-ONLY (G7): inactive chunk → INACTIVE_VERSION.
    g = AccessGate(prof)
    expect(g.decide(_ctx(), _chunk(active=False))["reason"] == "INACTIVE_VERSION", "10 inactive deny")

    # 11) PREFILTER PARITY (G8): admit edilen sound; allow olan complete.
    g = AccessGate(prof, acls)
    chunks = [
        _chunk(chunk_id="a", classification="public"),
        _chunk(chunk_id="b", classification="confidential", acl_ref="acl:hr", redaction_state="applied"),
        _chunk(chunk_id="c", tenant_id="t-b", namespace=IDX._namespace("t-b", "kb-1")),
        _chunk(chunk_id="d", classification="restricted", acl_ref=None, redaction_state="applied"),
    ]
    ctx = _ctx(clearance="confidential", principals=["group:hr"])
    decs = g.authorize(ctx, chunks)
    cmap = {c["chunk_id"]: c for c in chunks}
    sound = comp = True
    for d in decs:
        c = cmap[d["chunk_id"]]
        admits = g.prefilter_admits(ctx, c)
        if admits and d["decision"] == "DENY" and d["reason"] in STORE_DIM_DENY:
            sound = False
        if d["decision"] == "ALLOW" and not admits:
            comp = False
    expect(sound and comp, "11 prefilter sound+complete")

    # 12) 6.1.3 ENTEGRASYON: gerçek IndexedChunk üzerinden enforcement (consumes kanıtı).
    pipe, ix_chunks, _ = index_documents([
        {"source_id": "pol-pub", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "public",
         "redaction_state": "not_required", "inline_text": "Genel calisma saatleri hafta ici 09 18 arasidir."},
        {"source_id": "pol-conf", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "confidential",
         "acl_ref": "acl:hr", "redaction_state": "applied", "inline_text": "Gizli ucret politikasi metni."},
    ])
    g = AccessGate(prof, acls)
    ctx_low = _ctx(clearance="internal", principals=["role:human_agent"])
    decs = g.authorize(ctx_low, ix_chunks)
    allowed_docs = {d["document_id"] for d in decs if d["decision"] == "ALLOW"}
    expect("pol-pub" in allowed_docs and "pol-conf" not in allowed_docs,
           "12 6.1.3 chunk: public izinli, confidential yetkisiz (SR-KB-005)")
    expect(all(c.get("active") for c in ix_chunks), "12b indexlenen chunk'lar aktif")

    # 13) AUDIT (G9): her karar audit'te + ham PII yok.
    g = AccessGate(prof)
    g.decide(_ctx(), _chunk(redaction_state="pending", content="numara 9988 7766 5544"))
    blob = json.dumps(g.audit, ensure_ascii=False)
    expect(len(g.audit) == 1 and "content" not in g.audit[0] and not NUM_RE.search(blob),
           "13 audit yapısal + ham PII yok")
    expect(g.audit[0]["principal_digest"] != "anon" and len(g.audit[0]["principal_digest"]) == 12,
           "13b principal_digest sha256 (token ham değil)")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for m in fails:
        print("  ✗ %s" % m)
    return 0 if not fails else 1


# ── schema ─────────────────────────────────────────────────────────────────────
def schema():
    print("# WBS 6.1.4 — Doküman bazı erişim yetkisi (FR-KB-005) sözleşmeleri\n")
    print("PrincipalContext (retrieval isteği yetki bağlamı):")
    print("  {tenant_id, kb_ids:[...], principals:['role:/group:/agent:/user:'], clearance,")
    print("   channel_no_log?, agent_id?, purpose?}  — eksikse fail-closed MISSING_PRINCIPAL_CONTEXT\n")
    print("IndexedChunk (6.1.3'ten TÜKETİLİR — erişim metadata C9 ile taşınmış):")
    print("  {chunk_id, namespace, tenant_id, kb_id, document_id, version_no, active,")
    print("   classification(public<internal<confidential<restricted), acl_ref, sensitive,")
    print("   redaction_state(not_required/applied/pending), content, ...}\n")
    print("ACL (acl_ref ile çözülür):  {default:'deny'/'allow', allow:[token], deny:[token]}  (deny WINS)\n")
    print("AccessDecision (post-filtre, authoritative):")
    print("  {chunk_id, document_id, decision:'ALLOW'/'DENY', reason, classification, sensitive,")
    print("   redacted, content?(yalnız ALLOW)}")
    print("  ALLOW: %s" % sorted(ALLOW_DECISIONS))
    print("  DENY : %s\n" % sorted(DENY_REASONS))
    print("PrefilterPredicate (store-tarafı, 6.2.1'e push — necessary, NOT authoritative):")
    print("  {namespaces:[...], classification_in:[...], acl_tokens:[...], active:true}\n")
    print("Audit kaydı: {ts, tenant_id, kb_id, document_id, chunk_id, decision, reason,")
    print("   classification, sensitive, principal_digest(sha256)}  — ham içerik/PII YAZILMAZ")
    print("\nKapılar: %s" % GATE_IDS)
    return 0


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
    if cmd == "enforce":
        if len(argv) < 3:
            print("kullanım: access_control_probe.py enforce <sample.json>")
            return 2
        return enforce_cmd(argv[2])
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
