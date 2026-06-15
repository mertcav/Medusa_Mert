#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WBS 6.1.5 — Bayatlama/işaretleme (content TTL) (FR-KB-008) referans probe.

    FreshnessMetadata (6.1.3 indexed_at/version · 6.1.2 last_modified · DB.md content_ttl_at)
        ──► [STALENESS MARKER: explicit-TTL · policy max_age · source-drift · hard-expiry · pinned]
        ──► fresh | stale | expired | pinned  (otomatik 'stale' işareti)

Bilgi Tabanı & RAG OFFLINE indeksleme hattının (SAD §10.1, Control/Analytics Plane — hot-path DEĞİL)
bayatlama/işaretleme katmanıdır. Bu motor:
  6.1.3 IndexPipeline'ın ürettiği tazelik ATALARINI (version_no/indexed_at/active) + 6.1.2 connector kaynak
  last_modified/eTag'ini + DB.md §5.3 kb_document.content_ttl_at açık deadline'ını TÜKETİR (index_pipeline_probe
  IMPORT edilir — chunk/embed/version YENİDEN YAPILMAZ; o da ingest_connector_probe'u import eder; kod tekrarı
  YOK) ve bir TARAMA anında (sanal saat 'now') her dokümanı taze/bayat/expired/pinned SINIFLAR ve otomatik
  'stale' İŞARETLER.

Çekirdek değer FR-KB-008 / SR-KB-008 / TC-KB-008 (T): 'TTL aşan içerik \"stale\" işaretlenir.' (G1 başlık).
KARAR metadata-only (içerik/embedding/ağ YOK); deterministik (sanal saat — Date.now/rastgele YOK).

Kapsam dışı (bilinçli, G10): chunk/embed/version → 6.1.3 (TÜKETİR); işaretin retrieval'e etkisi (bayat
bastırma/önceliklendirme) → 6.2.1; yeniden-ingest tetikleme → 6.1.2/6.1.3; fiziksel content_ttl_at kolonu/
tarama indeksi → 1.1.7 (migration 0010); hassas no-log → 6.2.4. Vendor-neutral (ADR-001/002): TTL kararı
policy + doküman metadata'sına dayanır, sağlayıcıya değil.

Kullanım:
  content_ttl_probe.py validate         Statik spec/config/şema kapısı → çıkış kodu
  content_ttl_probe.py mark <sample>    Deterministik StalenessMarker — senaryoyu tara+işaretle → kapı
  content_ttl_probe.py selftest         Gömülü davranış kontrolleri → çıkış kodu
  content_ttl_probe.py schema           Tazelik/karar sözleşmesini yazdır

Determinizm: sanal saat (epoch-sn tam sayı; Date.now/rastgele YOK). Sır/credential ve gerçek PII değeri
üretilmez/yazılmaz (TTL kararı metadata-only — içeriğe dokunmaz; fixture sentetik FR-TST-008). Stdlib-only.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "content-ttl-spec.json")
CONFIG_PATH = os.path.join(HERE, "config", "content-ttl-profiles.json")
SAMPLES_DIR = os.path.join(HERE, "samples")

# 6.1.3 index pipeline'ı import et — IndexedDocument tazelik atasını ONUN ürettiği gibi türet (kod tekrarı YOK).
_IDX_DIR = os.path.normpath(os.path.join(HERE, "..", "index-pipeline"))
sys.path.insert(0, _IDX_DIR)
import index_pipeline_probe as IDX  # noqa: E402

# ── Sabitler ──────────────────────────────────────────────────────────────────
GATE_IDS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"]
CLASSIFICATIONS = ["public", "internal", "confidential", "restricted"]
STATES = ["fresh", "stale", "expired", "pinned"]
MARKED_STATES = {"stale", "expired"}
REASONS = {
    "WITHIN_TTL", "NO_TTL_POLICY",                                  # fresh
    "TTL_EXCEEDED", "EXPLICIT_TTL_PASSED", "SOURCE_DRIFT",          # stale
    "MISSING_FRESHNESS", "MALFORMED_METADATA",                      # stale (fail-closed)
    "HARD_EXPIRED",                                                 # expired
    "PINNED_NO_EXPIRE",                                             # pinned
}
DAY = 86400  # epoch-saniye gün (sample/policy okunabilirliği)

# Sır/PII tarama (spec/config/sample DESCRIPTOR'larında).
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ── StalenessMarker — bayatlama/işaretleme (FR-KB-008) ───────────────────────────
class StalenessMarker:
    """Karar policy + doküman tazelik metadata'sından verilir (vendor-neutral, ADR-001/002). Fail-closed.
    policy: max_age_by_classification / default_max_age / expire_after_factor / hard_expiry_enabled /
            require_freshness / respect_source_drift / grace_period. now: tarama anı (epoch-sn, sanal saat)."""

    def __init__(self, policy, now):
        self.policy = policy or {}
        self.now = now
        self.audit = []

    def _max_age(self, cls):
        m = self.policy.get("max_age_by_classification") or {}
        if cls in m and m[cls] is not None:
            return m[cls]
        return self.policy.get("default_max_age")   # None olabilir

    def mark(self, doc):
        try:
            rec = self._mark(doc)
        except Exception:
            # G9/G10: bozuk/eksik metadata hiçbir exception KAÇIRMAZ → muhafazakâr stale (asla sessizce taze).
            rec = self._rec(doc, prev=(doc.get("prev_state") or "fresh"), state="stale",
                            reason="MALFORMED_METADATA", soft=None, hard=None, dsrc=None,
                            src_drift=False, missing=True, age=None, overdue_by=0)
        self.audit.append({k: rec[k] for k in (
            "document_id", "tenant_id", "kb_id", "version_no", "prev_state", "state", "reason",
            "now", "soft_deadline", "hard_deadline", "age", "overdue_by")})
        return rec

    def _mark(self, doc):
        prev = doc.get("prev_state") or "fresh"
        cls = doc.get("classification", "internal")
        pinned = bool(doc.get("pinned", False))
        indexed_at = doc.get("indexed_at")
        src_lm = doc.get("source_last_modified")
        explicit = doc.get("content_ttl_at")
        now = self.now
        grace = self.policy.get("grace_period") or 0
        max_age = self._max_age(cls)
        factor = self.policy.get("expire_after_factor", 2.0)
        hard_enabled = bool(self.policy.get("hard_expiry_enabled", False))
        drift_on = bool(self.policy.get("respect_source_drift", False))
        require_fresh = bool(self.policy.get("require_freshness", False))

        # SOFT deadline — content_ttl_at EZER (most-specific-wins, G3); aksi indexed_at + max_age.
        if explicit is not None:
            soft, dsrc = explicit, "explicit"
        elif indexed_at is not None and max_age is not None:
            soft, dsrc = indexed_at + max_age, "policy"
        else:
            soft, dsrc = None, None

        # HARD deadline — soft + ext (ext = max_age*(factor-1); yalnız gerçek genişletme varsa, G6).
        hard = None
        if hard_enabled and soft is not None and max_age is not None:
            ext = int(max_age * (factor - 1.0))
            if ext > 0:
                hard = soft + ext

        missing = (soft is None)
        src_drift = bool(drift_on and src_lm is not None and indexed_at is not None and src_lm > indexed_at)
        age = (now - indexed_at) if indexed_at is not None else None

        # ŞİDDET SIRASI: pinned > expired > stale(drift/ttl) > missing(require) > fresh.
        if pinned:
            state, reason = "pinned", "PINNED_NO_EXPIRE"
        elif hard is not None and now >= hard:
            state, reason = "expired", "HARD_EXPIRED"
        elif src_drift:
            state, reason = "stale", "SOURCE_DRIFT"
        elif soft is not None and now >= soft + grace:
            state, reason = "stale", ("EXPLICIT_TTL_PASSED" if dsrc == "explicit" else "TTL_EXCEEDED")
        elif missing and require_fresh:
            state, reason = "stale", "MISSING_FRESHNESS"
        elif missing:
            state, reason = "fresh", "NO_TTL_POLICY"
        else:
            state, reason = "fresh", "WITHIN_TTL"

        overdue_by = (now - soft) if (soft is not None and now >= soft + grace) else 0
        return self._rec(doc, prev=prev, state=state, reason=reason, soft=soft, hard=hard, dsrc=dsrc,
                         src_drift=src_drift, missing=missing, age=age, overdue_by=overdue_by)

    def _rec(self, doc, prev, state, reason, soft, hard, dsrc, src_drift, missing, age, overdue_by):
        return {
            "document_id": doc.get("document_id"), "tenant_id": doc.get("tenant_id"),
            "kb_id": doc.get("kb_id"), "version_no": doc.get("version_no"),
            "classification": doc.get("classification", "internal"),
            "prev_state": prev, "state": state, "reason": reason,
            "marked": state in MARKED_STATES, "transitioned": state != prev,
            "now": self.now, "soft_deadline": soft, "hard_deadline": hard, "deadline_source": dsrc,
            "src_drift": bool(src_drift), "missing_anchor": bool(missing), "pinned": doc.get("pinned", False),
            "age": age, "overdue_by": overdue_by,
        }

    def scan(self, docs, tenant_filter=None):
        """Doküman tazelik kayıtlarını tara → işaret kayıtları. tenant_filter verilirse YALNIZ o tenant (G8)."""
        out = []
        for d in docs:
            if tenant_filter is not None and d.get("tenant_id") != tenant_filter:
                continue   # kapsam dışı — taranmaz/işaretlenmez (FR-TEN-002)
            out.append(self.mark(d))
        return out


# ── 6.1.3 üzerinden IndexedDocument tazelik atası türetimi (TÜKETİR — yeniden yapmaz) ──
def _normdoc_from_doc(d):
    """Sample 'index_input' girdisini NormalizedDocument'a çevir (6.1.3 IndexPipeline girişi)."""
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
        "title": d.get("title"), "classification": d.get("classification", "internal"),
        "acl_ref": d.get("acl_ref"), "sensitive": bool(d.get("sensitive", False)),
        "redaction_state": d.get("redaction_state", "not_required"),
        "residency_region": d.get("residency_region", "home"),
    }


def _mk_index_pipeline():
    prof = {"chunk": {"target_chars": 400, "overlap_chars": 40, "max_chunks": 5000, "token_estimate_divisor": 4},
            "embedding": {"model": "ref-embed-v1", "dim": 16, "no_train": True, "no_log": True},
            "residency_region": "home", "allowed_regions": ["home"]}
    return IDX.IndexPipeline(prof)


def index_inputs(index_inputs_list):
    """Sample index_input'ları → 6.1.3 ile indexle → IndexPipeline (aktif sürüm provenance kaynağı)."""
    pipe = _mk_index_pipeline()
    for d in index_inputs_list:
        nd = _normdoc_from_doc(d)
        pipe.index_normdoc(nd, nd["doc_logical_key"])
    return pipe


def active_documents(pipe):
    """6.1.3 store'undan AKTİF doküman versiyonlarını türet (doküman granülerliği; chunk dedup).
    → 6.1.5 tazelik kaydının provenance'ı (document_id/version_no/classification 6.1.3'ten)."""
    seen = {}
    for ns, recs in pipe.store.items():
        for r in recs:
            if not r.get("active"):
                continue
            did = r["document_id"]
            if did not in seen:
                seen[did] = {"document_id": did, "tenant_id": r["tenant_id"], "kb_id": r["kb_id"],
                             "version_no": r["version_no"], "classification": r.get("classification", "internal")}
    return list(seen.values())


def freshness_from_index(pipe, anchors):
    """6.1.3 aktif dokümanlarını + sample tazelik atalarını (indexed_at/source_last_modified/content_ttl_at/
    pinned/prev_state — gerçekte kb_document satırından/connector'dan gelir) birleştir → tazelik kaydı."""
    docs = []
    for ad in active_documents(pipe):
        a = anchors.get(ad["document_id"], {})
        d = dict(ad)
        for k in ("indexed_at", "source_last_modified", "content_ttl_at", "pinned", "prev_state"):
            if k in a:
                d[k] = a[k]
        docs.append(d)
    return docs


# ── mark — bir sample senaryosunu çalıştır ───────────────────────────────────────
def _policy_for(sample, cfg):
    pname = sample.get("profile", "pilot-default")
    p = dict(cfg["profiles"].get(pname, cfg["profiles"]["pilot-default"]))
    return p, pname


def _resolve_docs(sample, marker_now):
    """Sample dokümanlarını çöz. İki kaynak: doğrudan 'documents' (tazelik kaydı) VEYA 'index_inputs'
    (6.1.3 ile indexlenir, tazelik atası 'anchors' ile bağlanır → consumes kanıtı)."""
    if sample.get("index_inputs"):
        pipe = index_inputs(sample["index_inputs"])
        return freshness_from_index(pipe, sample.get("anchors", {})), pipe
    return sample.get("documents", []), None


def evaluate_gates(sample, marker, docs, records, tenant_filter):
    """G1–G10 HARD kapıları. records, docs (kapsam içi) ile 1:1 sırada."""
    checks = []

    def chk(gid, ok, msg):
        checks.append((gid, bool(ok), msg))

    now = marker.now
    inscope = [d for d in docs if tenant_filter is None or d.get("tenant_id") == tenant_filter]
    pairs = list(zip(inscope, records))

    def overdue(r):
        s = r["soft_deadline"]
        return s is not None and r["now"] >= s   # grace dahil değil — yapısal alt sınır

    # G1 TTL EXCEEDED → STALE (başlık): soft-deadline geçen / drift / missing+require → marked.
    unmarked_overdue = 0
    for r in records:
        must = overdue(r) or r["src_drift"] or (r["missing_anchor"] and bool(marker.policy.get("require_freshness")))
        if r["pinned"]:
            continue
        if must and not r["marked"]:
            unmarked_overdue += 1
    chk("G1", unmarked_overdue == 0, "işaretlenmemiş bayat doküman=%d (overdue/drift/missing→stale)" % unmarked_overdue)

    # G2 FRESH PRESERVED: state=fresh olan yanlış-pozitif değil (deadline gelecekte / drift yok / missing değil).
    false_stale = 0
    for r in records:
        if r["state"] != "fresh":
            continue
        if overdue(r) or r["src_drift"]:
            false_stale += 1
        if r["missing_anchor"] and bool(marker.policy.get("require_freshness")):
            false_stale += 1
    chk("G2", false_stale == 0, "yanlış-pozitif (taze ama aslında bayat) sayısı=%d" % false_stale)

    # G3 EXPLICIT PRECEDENCE: content_ttl_at olan kayıtta soft_deadline == content_ttl_at + deadline_source=explicit.
    prec_bad = 0
    for d, r in pairs:
        if d.get("content_ttl_at") is not None and not r["pinned"]:
            if r["soft_deadline"] != d["content_ttl_at"] or r["deadline_source"] != "explicit":
                prec_bad += 1
    chk("G3", prec_bad == 0, "açık-TTL most-specific ezme ihlali=%d" % prec_bad)

    # G4 SOURCE DRIFT: drift olan (pinned/expired değil) → stale SOURCE_DRIFT.
    drift_bad = 0
    for r in records:
        if r["src_drift"] and not r["pinned"] and r["state"] != "expired":
            if not (r["state"] == "stale" and r["reason"] == "SOURCE_DRIFT"):
                drift_bad += 1
    chk("G4", drift_bad == 0, "drift olup stale-işaretlenmeyen=%d" % drift_bad)

    # G5 PINNED NEVER EXPIRES: pinned doküman state=pinned + marked=false (yaştan bağımsız).
    pin_bad = sum(1 for r in records if r["pinned"] and (r["state"] != "pinned" or r["marked"]))
    chk("G5", pin_bad == 0, "pinned ama bayat/expired işaretlenen=%d" % pin_bad)

    # G6 HARD EXPIRY DISTINCT: hard-deadline geçen (pinned değil) → expired; expired ⇒ soft da geçmiş (monoton).
    hard_bad = 0
    for r in records:
        hd = r["hard_deadline"]
        if hd is not None and now >= hd and not r["pinned"]:
            if r["state"] != "expired":
                hard_bad += 1
        if r["state"] == "expired" and not overdue(r):
            hard_bad += 1   # monotonluk ihlali
    chk("G6", hard_bad == 0, "hard-expiry/monotonluk ihlali=%d" % hard_bad)

    # G7 DETERMINISTIC: ikinci tarama birebir aynı.
    m2 = StalenessMarker(marker.policy, now)
    rec2 = m2.scan(docs, tenant_filter=tenant_filter)
    det_ok = json.dumps(records, ensure_ascii=False, sort_keys=True) == \
        json.dumps(rec2, ensure_ascii=False, sort_keys=True)
    chk("G7", det_ok, "ikinci tarama %s" % ("birebir aynı" if det_ok else "FARKLI (determinizm ihlali)"))

    # G8 TENANT SCOPE: kayıtta kapsam-dışı tenant yok + üretilen=kapsam içi.
    cross = sum(1 for r in records if tenant_filter is not None and r["tenant_id"] != tenant_filter)
    chk("G8", cross == 0 and len(records) == len(inscope),
        "cross-tenant işaretli=%d  üretilen=%d kapsam-içi=%d" % (cross, len(records), len(inscope)))

    # G9 FAIL-CLOSED UNKNOWN: missing-anchor + require_freshness → stale (asla fresh); MALFORMED → stale.
    silent_fresh = 0
    if bool(marker.policy.get("require_freshness")):
        for r in records:
            if r["missing_anchor"] and not r["src_drift"] and r["state"] == "fresh":
                silent_fresh += 1
    chk("G9", silent_fresh == 0, "sessiz-taze (eksik tazelik+require) sayısı=%d" % silent_fresh)

    # G10 AUDITABLE + ROBUST: kapsam içi her doküman bir kayıt + taksonomi + audit ham içerik/PII yok.
    states_ok = all(r["state"] in STATES for r in records)
    reasons_ok = all(r["reason"] in REASONS for r in records)
    audit_blob = json.dumps(marker.audit, ensure_ascii=False)
    audit_clean = ("content" not in {k for a in marker.audit for k in a}) and not EMAIL_RE.search(audit_blob) \
        and not CREDIT_CARD_RE.search(audit_blob)
    chk("G10", len(records) == len(inscope) and states_ok and reasons_ok and audit_clean,
        "kayıt=%d kapsam-içi=%d durum-geçerli=%s reason-geçerli=%s audit-temiz=%s" %
        (len(records), len(inscope), states_ok, reasons_ok, audit_clean))

    return checks


def mark_cmd(sample_path):
    sample = _load(sample_path)
    cfg = _load(CONFIG_PATH)
    pol, pname = _policy_for(sample, cfg)
    now = sample["now"]
    tenant_filter = sample.get("tenant_filter")

    docs, pipe = _resolve_docs(sample, now)
    marker = StalenessMarker(pol, now)
    records = marker.scan(docs, tenant_filter=tenant_filter)

    print("Senaryo: %s  (profil=%s, now=%d, tenant_filter=%s, expect_gate=%s)" %
          (sample.get("scenario"), pname, now, tenant_filter, sample.get("expect_gate", "pass")))
    if pipe is not None:
        print("6.1.3 indexlenen → aktif doküman (provenance): %d" % len(docs))
    tally = {}
    for r in records:
        tally[r["state"]] = tally.get(r["state"], 0) + 1
    print("Taranan doküman: %d  → durum dağılımı: %s" % (len(records), tally))
    for r in records:
        print("  %-14s v%-3s %-12s → %-8s %-18s marked=%s (soft=%s hard=%s drift=%s)" %
              (r["document_id"], r["version_no"], r["classification"], r["state"], r["reason"],
               r["marked"], r["soft_deadline"], r["hard_deadline"], r["src_drift"]))

    # Beklenti kontrolü (per-doc expect_state / expect_reason / expect_marked).
    rec_by_id = {r["document_id"]: r for r in records}
    expect_fail = []
    for d in docs:
        if tenant_filter is not None and d.get("tenant_id") != tenant_filter:
            # kapsam dışı doküman İŞARETLENMEMELİ (kayıt üretilmemeli).
            if d.get("expect", {}).get("out_of_scope") and d["document_id"] in rec_by_id:
                expect_fail.append("doküman %s kapsam dışı ama işaretlendi" % d["document_id"])
            continue
        exp = d.get("expect", {})
        r = rec_by_id.get(d["document_id"])
        if r is None:
            if exp:
                expect_fail.append("doküman %s kayıt üretmedi" % d["document_id"])
            continue
        if exp.get("state") and r["state"] != exp["state"]:
            expect_fail.append("doküman %s: state '%s' beklendi, '%s' geldi" %
                               (d["document_id"], exp["state"], r["state"]))
        if exp.get("reason") and r["reason"] != exp["reason"]:
            expect_fail.append("doküman %s: reason '%s' beklendi, '%s' geldi" %
                               (d["document_id"], exp["reason"], r["reason"]))
        if "marked" in exp and r["marked"] != exp["marked"]:
            expect_fail.append("doküman %s: marked %s beklendi, %s geldi" %
                               (d["document_id"], exp["marked"], r["marked"]))

    checks = evaluate_gates(sample, marker, docs, records, tenant_filter)
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
    ok(spec.get("wbs") == "6.1.5", "spec.wbs=6.1.5")
    ok(spec.get("phase") == "F2" and spec.get("priority") == "Should", "spec faz/öncelik (F2/Should)")
    tr = spec.get("trace", {})
    ok("FR-KB-008" in tr.get("fr", []), "trace FR-KB-008")
    ok("SR-KB-008" in tr.get("srs", []), "trace SR-KB-008")
    ok("TC-KB-008" in tr.get("rtm", []), "trace TC-KB-008")
    ok(any("6.1.3" in c for c in tr.get("consumes", [])), "consumes 6.1.3 tazelik atası")
    ok(any("content_ttl_at" in c for c in tr.get("consumes", [])), "consumes content_ttl_at (DB.md §5.3)")
    ok(any("6.2.1" in c for c in tr.get("consumed_by", [])), "consumed_by 6.2.1 (retrieval bastırma)")
    pl = spec.get("placement", {})
    ok(pl.get("hot_path") is False, "offline (hot_path=false)")
    ok("metadata-only" in pl.get("decision_cost", ""), "karar metadata-only")

    # Tazelik/TTL sözleşmeleri.
    fm = spec.get("freshness_metadata", {})
    ok({"document_id", "tenant_id", "classification"}.issubset(set(fm.get("required_fields", []))),
       "tazelik zorunlu alanlar")
    ok(set(fm.get("freshness_anchors", [])) == {"indexed_at", "content_ttl_at", "source_last_modified"},
       "tazelik atası seti")
    ok(fm.get("explicit_overrides_policy") is True, "açık TTL policy'yi ezer")
    tm = spec.get("ttl_model", {})
    ok(tm.get("severity_order") == ["pinned", "expired", "stale", "fresh"], "şiddet sırası")

    # Durum/reason taksonomi spec==kod.
    st = spec.get("states", {})
    ok(st.get("values") == STATES, "durum seti spec==kod")
    ok(set(st.get("marked_states", [])) == MARKED_STATES, "marked durumları spec==kod")
    rt = spec.get("reason_taxonomy", {})
    spec_reasons = set(rt.get("fresh", []) + rt.get("stale", []) + rt.get("expired", []) + rt.get("pinned", []))
    ok(spec_reasons == REASONS, "reason taksonomi spec==kod (%d)" % len(spec_reasons))

    # Gates + invariants.
    g = spec.get("gates", {})
    for key in ["max_unmarked_overdue", "max_false_stale", "require_explicit_precedence", "require_source_drift",
                "require_pinned_never_expires", "require_hard_expiry_distinct", "require_deterministic",
                "require_tenant_scope", "require_fail_closed_unknown", "require_decision_auditable"]:
        ok(key in g, "gate '%s' var" % key)
    ok(g.get("max_unmarked_overdue") == 0 and g.get("max_false_stale") == 0,
       "işaretlenmemiş-bayat/yanlış-pozitif=0")
    inv_ids = [i["id"] for i in spec.get("invariants", [])]
    ok(inv_ids == GATE_IDS, "invariant G1–G10 sırada (%s)" % inv_ids)

    # Config profilleri.
    profs = cfg.get("profiles", {})
    ok({"pilot-default", "regulated-tr", "enterprise-eu"}.issubset(set(profs)), "3 ana profil var")
    for name, p in profs.items():
        if name == "degraded-no-expiry":
            continue
        m = p.get("max_age_by_classification", {})
        ok(isinstance(m, dict) and all(c in m for c in CLASSIFICATIONS), "[%s] max_age 4 sınıf" % name)
        ok(all(m[c] is None or m[c] > 0 for c in m), "[%s] max_age pozitif" % name)
        ok(p.get("require_freshness") is True, "[%s] require_freshness açık" % name)
        ok(p.get("respect_source_drift") is True, "[%s] source-drift açık" % name)
        ok(p.get("hard_expiry_enabled") is True and p.get("expire_after_factor", 0) > 1.0,
           "[%s] hard-expiry açık + factor>1" % name)
    # regulated-tr en sıkı: internal max_age ≤ pilot internal.
    if {"regulated-tr", "pilot-default"}.issubset(set(profs)):
        rt_age = profs["regulated-tr"]["max_age_by_classification"]["internal"]
        pd_age = profs["pilot-default"]["max_age_by_classification"]["internal"]
        ok(rt_age <= pd_age, "regulated-tr internal TTL ≤ pilot (daha sıkı)")

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
PROF = {
    "max_age_by_classification": {"public": 180 * DAY, "internal": 90 * DAY,
                                  "confidential": 30 * DAY, "restricted": 14 * DAY},
    "default_max_age": 90 * DAY, "expire_after_factor": 2.0, "hard_expiry_enabled": True,
    "require_freshness": True, "respect_source_drift": True, "grace_period": 0,
}
NOW = 1_000_000_000


def _doc(**kw):
    base = {"document_id": "d", "tenant_id": "t-a", "kb_id": "kb-1", "version_no": 1,
            "classification": "internal", "indexed_at": NOW - 1 * DAY}
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

    m = StalenessMarker(PROF, NOW)

    # 1) FRESH (G2): internal, 10 gün önce indexlendi (max_age 90g) → fresh WITHIN_TTL.
    r = m.mark(_doc(indexed_at=NOW - 10 * DAY))
    expect(r["state"] == "fresh" and r["reason"] == "WITHIN_TTL" and not r["marked"], "1 fresh within ttl")

    # 2) STALE by policy (G1 başlık): internal 100 gün önce → soft (90g) geçti → stale TTL_EXCEEDED.
    r = m.mark(_doc(indexed_at=NOW - 100 * DAY))
    expect(r["state"] == "stale" and r["reason"] == "TTL_EXCEEDED" and r["marked"], "2 stale ttl exceeded (SR-KB-008)")

    # 3) EXPIRED hard (G6): internal 400 gün önce → hard (180g) geçti → expired HARD_EXPIRED + soft da geçmiş.
    r = m.mark(_doc(indexed_at=NOW - 400 * DAY))
    expect(r["state"] == "expired" and r["reason"] == "HARD_EXPIRED" and r["marked"], "3 hard expired")
    expect(r["now"] >= r["soft_deadline"], "3b expired monoton (soft da geçmiş)")

    # 4) EXPLICIT PRECEDENCE (G3): policy'ye göre bayat (200g) ama content_ttl_at gelecekte → fresh.
    r = m.mark(_doc(indexed_at=NOW - 200 * DAY, content_ttl_at=NOW + 30 * DAY))
    expect(r["state"] == "fresh" and r["deadline_source"] == "explicit" and r["soft_deadline"] == NOW + 30 * DAY,
           "4 açık TTL gelecekte → fresh (policy ezildi)")
    # açık TTL geçmişte (policy'ye göre taze olsa bile) → stale EXPLICIT_TTL_PASSED.
    r = m.mark(_doc(indexed_at=NOW - 1 * DAY, content_ttl_at=NOW - 1))
    expect(r["state"] == "stale" and r["reason"] == "EXPLICIT_TTL_PASSED", "4b açık TTL geçti → stale")

    # 5) SOURCE DRIFT (G4): yaş içinde (5g) ama kaynak indeksten yeni → stale SOURCE_DRIFT.
    r = m.mark(_doc(indexed_at=NOW - 5 * DAY, source_last_modified=NOW - 1 * DAY))
    expect(r["state"] == "stale" and r["reason"] == "SOURCE_DRIFT" and r["marked"], "5 source drift stale")
    # kaynak indeksten ESKİ → drift yok → fresh.
    r = m.mark(_doc(indexed_at=NOW - 5 * DAY, source_last_modified=NOW - 6 * DAY))
    expect(r["state"] == "fresh", "5b kaynak eski → drift yok fresh")
    # drift + hard-expired → expired kazanır (şiddet sırası).
    r = m.mark(_doc(indexed_at=NOW - 400 * DAY, source_last_modified=NOW - 1 * DAY))
    expect(r["state"] == "expired", "5c drift+hard → expired (şiddet)")

    # 6) PINNED (G5): çok eski ama pinned → pinned, asla bayat.
    r = m.mark(_doc(indexed_at=NOW - 1000 * DAY, pinned=True))
    expect(r["state"] == "pinned" and r["reason"] == "PINNED_NO_EXPIRE" and not r["marked"], "6 pinned never expires")
    # pinned + drift → yine pinned.
    r = m.mark(_doc(indexed_at=NOW - 1000 * DAY, source_last_modified=NOW, pinned=True))
    expect(r["state"] == "pinned", "6b pinned drift'i de muaf")

    # 7) MISSING FRESHNESS (G9): atası yok + require_freshness → stale MISSING_FRESHNESS (asla sessiz fresh).
    r = m.mark({"document_id": "x", "tenant_id": "t-a", "classification": "internal"})
    expect(r["state"] == "stale" and r["reason"] == "MISSING_FRESHNESS", "7 missing freshness → stale")
    # require_freshness kapalı → NO_TTL_POLICY fresh (bilinçli).
    m_open = StalenessMarker(dict(PROF, require_freshness=False, default_max_age=None,
                                  max_age_by_classification={}), NOW)
    r = m_open.mark({"document_id": "x", "tenant_id": "t-a", "classification": "internal"})
    expect(r["state"] == "fresh" and r["reason"] == "NO_TTL_POLICY", "7b require kapalı → NO_TTL_POLICY fresh")

    # 8) MALFORMED (G9/G10): bozuk indexed_at (str) exception KAÇMAZ → muhafazakâr stale.
    r = m.mark(_doc(indexed_at="bozuk"))
    expect(r["state"] == "stale" and r["reason"] == "MALFORMED_METADATA", "8 bozuk metadata → fail-closed stale")

    # 9) DETERMINISM (G7): aynı set+now iki tarama birebir aynı.
    docs = [_doc(document_id="a", indexed_at=NOW - 100 * DAY),
            _doc(document_id="b", indexed_at=NOW - 5 * DAY)]
    a = StalenessMarker(PROF, NOW).scan(docs)
    b = StalenessMarker(PROF, NOW).scan(docs)
    expect(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "9 determinizm birebir")

    # 10) TENANT SCOPE (G8): tenant_filter dışı doküman taranmaz.
    docs = [_doc(document_id="a", tenant_id="t-a", indexed_at=NOW - 100 * DAY),
            _doc(document_id="b", tenant_id="t-b", indexed_at=NOW - 100 * DAY)]
    recs = StalenessMarker(PROF, NOW).scan(docs, tenant_filter="t-a")
    expect(len(recs) == 1 and recs[0]["tenant_id"] == "t-a", "10 tenant scope yalnız t-a")

    # 11) 6.1.3 ENTEGRASYON (consumes): indexle → aktif doküman → tazelik atası bağla → işaretle.
    pipe = index_inputs([
        {"source_id": "kb-old", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "internal",
         "inline_text": "Eski surum politika metni yeterince uzundur."},
        {"source_id": "kb-new", "tenant_id": "t-a", "kb_id": "kb-1", "classification": "internal",
         "inline_text": "Guncel surum metni yeterince uzundur."},
    ])
    docs = freshness_from_index(pipe, {
        "kb-old": {"indexed_at": NOW - 200 * DAY},
        "kb-new": {"indexed_at": NOW - 3 * DAY},
    })
    recs = StalenessMarker(PROF, NOW).scan(docs)
    by = {r["document_id"]: r for r in recs}
    expect(by["kb-old"]["marked"] and by["kb-new"]["state"] == "fresh",
           "11 6.1.3 aktif doküman: eski stale, yeni fresh (SR-KB-008)")
    expect(all(r["version_no"] == 1 for r in recs), "11b 6.1.3 version_no provenance taşındı")

    # 12) AUDIT (G10): kayıt yapısal + ham içerik/PII yok.
    m2 = StalenessMarker(PROF, NOW)
    m2.mark(_doc(indexed_at=NOW - 100 * DAY))
    blob = json.dumps(m2.audit, ensure_ascii=False)
    expect(len(m2.audit) == 1 and "content" not in m2.audit[0] and not EMAIL_RE.search(blob),
           "12 audit yapısal + ham içerik/PII yok")

    print("selftest: %d kontrol, %d başarısız" % (n, len(fails)))
    for msg in fails:
        print("  ✗ %s" % msg)
    return 0 if not fails else 1


# ── schema ─────────────────────────────────────────────────────────────────────
def schema():
    print("# WBS 6.1.5 — Bayatlama/işaretleme (content TTL, FR-KB-008) sözleşmeleri\n")
    print("FreshnessMetadata (kb_document satırı + 6.1.3 indeks + 6.1.2 connector'dan TÜRETİLİR):")
    print("  {document_id, tenant_id, kb_id, version_no, classification,")
    print("   indexed_at(epoch-sn — 6.1.3 son (re)index atası), source_last_modified?(6.1.2 last_modified/eTag),")
    print("   content_ttl_at?(DB.md §5.3 AÇIK deadline — policy'yi EZER), pinned?(no_expire), prev_state?}\n")
    print("TTL policy (profil): {max_age_by_classification{public/internal/confidential/restricted},")
    print("   default_max_age, expire_after_factor(>1 → hard), hard_expiry_enabled,")
    print("   require_freshness, respect_source_drift, grace_period}\n")
    print("Soft deadline = content_ttl_at if set else indexed_at + max_age(classification)")
    print("Hard deadline = soft + max_age*(expire_after_factor-1)  (hard tier; retrieval bastırır)")
    print("Şiddet sırası: pinned > expired > stale(drift/ttl) > missing(require) > fresh\n")
    print("FreshnessRecord (işaret — marked = state ∈ {stale, expired}):")
    print("  {document_id, ..., prev_state, state:'%s', reason, marked, transitioned," % "/".join(STATES))
    print("   now, soft_deadline, hard_deadline, deadline_source, src_drift, age, overdue_by}")
    print("  durumlar: %s" % STATES)
    print("  reason   : %s\n" % sorted(REASONS))
    print("Audit kaydı: {document_id, tenant_id, kb_id, version_no, prev_state, state, reason,")
    print("   now, soft_deadline, hard_deadline, age, overdue_by}  — ham içerik/PII YAZILMAZ (metadata-only)")
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
    if cmd == "mark":
        if len(argv) < 3:
            print("kullanım: content_ttl_probe.py mark <sample.json>")
            return 2
        return mark_cmd(argv[2])
    print("bilinmeyen komut: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
