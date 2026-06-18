#!/usr/bin/env python3
# WBS 13.4.8 — A-08 "Knowledge Base" doğrulama probe'u (stdlib-only, credential-free, deterministik).
#
# Komutlar:
#   validate  — ON-DISK invariant taraması (sayfa + veri seam + i18n + spec; S1..S8)
#   check     — SAF çekirdek senaryo aynası (allDocuments/countBySourceType/countByIndexStatus/
#               indexedDocuments/pendingIndexDocuments/failedIndexDocuments/staleDocuments/
#               sensitiveDocuments/restrictedDocuments/agentBoundBases/sharedBases/emptyBases/
#               duplicateNamespaces/openAttentionCount/tone'lar/assertNoPii) + samples/*
#   selftest  — pozitif + negatif kendi-testleri (bayat/başarısız indeks/boş KB/yinelenen namespace yakalanır)
#   schema    — bilgi tabanı görünümü şema özeti
#
# Bu probe TS saf yardımcılarının (lib/tenant/kb.ts) Python AYNASIDIR; mantık birebir kopya.
# 0.2.x/0.3.x probe disiplini (sağlayıcı-nötr ADR-002, stdlib-only, sanal-saat) bir UI ekranına taşınır.
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", ".."))          # frontend/tenant-app
SPEC_PATH = os.path.join(HERE, "a08-kb-spec.json")
PAGE_PATH = os.path.join(APP, "app", "(workspace)", "workspace", "kb", "page.tsx")
DATA_PATH = os.path.join(APP, "lib", "tenant", "kb.ts")
TR_PATH = os.path.join(APP, "lib", "i18n", "tr.json")
EN_PATH = os.path.join(APP, "lib", "i18n", "en.json")

GREEN, RED = "🟢", "🔴"

SOURCE_ORDER = ["pdf", "word", "html", "text", "csv", "web"]
INDEX_ORDER = ["indexed", "indexing", "pending", "failed"]

FORBIDDEN_PII_KEYS = ["transcript", "recording", "recordingurl", "audio", "msisdn",
                      "phonenumber", "callerid", "callernumber", "calleenumber", "customer",
                      "customername", "cdr", "cardpan", "cvv", "ssn", "pii"]
FORBIDDEN_SECRET_KEYS = ["secret", "apikey", "apisecret", "clientsecret", "webhooksecret", "token",
                         "bearertoken", "accesstoken", "refreshtoken", "credential", "password",
                         "privatekey", "kmskey", "content", "chunkcontent", "chunktext",
                         "documentbody", "documenttext", "rawtext", "sourceuri", "sourceurl", "embedding"]


def load_json(p):
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def read_text(p):
    with open(p, "r", encoding="utf-8") as fh:
        return fh.read()


# ── SAF çekirdek aynası (lib/tenant/kb.ts ile birebir) ────────────────────────────

def sorted_bases(view):
    return sorted(view["knowledgeBases"], key=lambda kb: kb["kbRef"])


def all_documents(view):
    rows = []
    for kb in view["knowledgeBases"]:
        for d in kb["documents"]:
            row = dict(d)
            row["kbRef"] = kb["kbRef"]
            row["kbName"] = kb["name"]
            rows.append(row)
    return sorted(rows, key=lambda r: (r["kbRef"], r["docRef"]))


def count_by_source_type(docs):
    acc = {s: 0 for s in SOURCE_ORDER}
    for d in docs:
        acc[d["sourceType"]] += 1
    return acc


def count_by_index_status(docs):
    acc = {s: 0 for s in INDEX_ORDER}
    for d in docs:
        acc[d["indexStatus"]] += 1
    return acc


def indexed_documents(docs):
    return [d for d in docs if d["indexStatus"] == "indexed"]


def pending_index_documents(docs):
    return [d for d in docs if d["indexStatus"] in ("pending", "indexing")]


def failed_index_documents(docs):
    return [d for d in docs if d["indexStatus"] == "failed"]


def stale_documents(docs):
    return [d for d in docs if d["freshness"] == "stale"]


def sensitive_documents(docs):
    return [d for d in docs if d["isSensitive"]]


def restricted_documents(docs):
    return [d for d in docs if d["accessScope"] == "restricted"]


def agent_bound_bases(view):
    return [kb for kb in view["knowledgeBases"] if kb["binding"] == "agent"]


def shared_bases(view):
    return [kb for kb in view["knowledgeBases"] if kb["binding"] == "shared"]


def empty_bases(view):
    return [kb for kb in view["knowledgeBases"] if len(kb["documents"]) == 0]


def duplicate_namespaces(view):
    seen, dup = set(), set()
    for kb in view["knowledgeBases"]:
        if kb["namespace"] in seen:
            dup.add(kb["namespace"])
        seen.add(kb["namespace"])
    return sorted(dup)


def open_attention_count(view):
    docs = all_documents(view)
    return (len(stale_documents(docs))
            + len(failed_index_documents(docs))
            + len(empty_bases(view))
            + len(duplicate_namespaces(view)))


def source_tone(s):
    return {"pdf": "neutral", "word": "neutral", "html": "neutral",
            "text": "neutral", "csv": "neutral", "web": "info"}[s]


def index_tone(s):
    return {"indexed": "success", "indexing": "info", "pending": "warning", "failed": "danger"}[s]


def freshness_tone(f):
    return {"fresh": "success", "stale": "warning"}[f]


def access_tone(a):
    return {"tenant": "neutral", "restricted": "info"}[a]


def binding_tone(b):
    return {"agent": "info", "shared": "neutral"}[b]


def assert_no_pii(node, path="$"):
    """Yasak PII/iş-içeriği VEYA sır/credential/doküman-içeriği alan adı bulursa (path) döndürür; yoksa None."""
    if isinstance(node, list):
        for i, v in enumerate(node):
            hit = assert_no_pii(v, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.startswith("$"):
                continue
            low = k.lower()
            if low in FORBIDDEN_PII_KEYS or low in FORBIDDEN_SECRET_KEYS:
                return f"{path}.{k}"
            hit = assert_no_pii(v, f"{path}.{k}")
            if hit:
                return hit
    return None


# ── i18n yardımcıları ─────────────────────────────────────────────────────────────

def resolve(cat, dotted):
    cur = cat
    for seg in dotted.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return None
    return cur if isinstance(cur, str) else None


def placeholders(s):
    return set(re.findall(r"\{(\w+)\}", s or ""))


def _extract_data_fields(ts):
    """kb.ts interface alan adlarını kaba çıkar (PII/sır-alan-adı taraması için)."""
    return {m: 1 for m in re.findall(r"^\s*(\w+)\s*[?:]", ts, re.M)}


# ── validate ───────────────────────────────────────────────────────────────────────

def cmd_validate():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    spec = load_json(SPEC_PATH)
    page = read_text(PAGE_PATH) if os.path.isfile(PAGE_PATH) else ""
    data = read_text(DATA_PATH) if os.path.isfile(DATA_PATH) else ""
    tr = load_json(TR_PATH)
    en = load_json(EN_PATH)

    # S0/S1 — ekran sayfası mevcut + işaretli + iskelet değil
    chk(spec.get("wbs") == "13.4.8", "S0 spec.wbs=13.4.8")
    chk(os.path.isfile(PAGE_PATH), "S1 workspace/kb/page.tsx mevcut")
    chk('data-screen="A-08"' in page, 'S1 data-screen="A-08" işaretli')
    chk("İskelet ekran — A-08" not in page, "S1 iskelet placeholder kaldırıldı")

    # S2 — tasarım sistemi + i18n + veri seam kullanımı
    chk("@/lib/ui/components" in page, "S2 tasarım sistemi (lib/ui) kullanır")
    chk("@/lib/i18n" in page, "S2 i18n (lib/i18n) kullanır")
    chk("@/lib/tenant/kb" in page, "S2 veri seam (lib/tenant/kb) kullanır")
    chk("getServerLocale" in page, "S2 sunucu-tarafı locale müzakeresi")
    for comp in ("PageHeader", "Card", "StatusPill", "Table", "Button"):
        chk(comp in page, f"S2 {comp} komponenti kullanılır")

    # S3 — kullanıcı-görünür metin i18n'den (screen.a08.*); hardcoded TR/EN cümle yok
    chk("screen.a08." in page, "S3 screen.a08.* anahtarları referans alınır")
    jsx_text = re.findall(r">\s*([A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü ]{3,})\s*<", page)
    chk(len(jsx_text) == 0, f"S3 JSX'te hardcoded metin yok (bulunan={jsx_text[:3]})")

    # S4 — veri katmanı son-müşteri-PII-free + sır/doküman-içeriği-free + HİJYEN/GÜVENLİK guard
    chk(os.path.isfile(DATA_PATH), "S4 lib/tenant/kb.ts mevcut")
    chk("FORBIDDEN_PII_KEYS" in data, "S4 FORBIDDEN_PII_KEYS tanımlı")
    chk("FORBIDDEN_SECRET_KEYS" in data, "S4 FORBIDDEN_SECRET_KEYS tanımlı (NFR 10.6)")
    chk("assertNoPii" in data, "S4 assertNoPii guard tanımlı")
    chk(re.search(r"assertNoPii\(view\)", data) is not None, "S4 getKbView assertNoPii çağırır")
    chk(all(s in [x.lower() for x in FORBIDDEN_SECRET_KEYS] for s in ("content", "chunkcontent", "sourceuri", "embedding")), "S4 doküman İÇERİĞİ/kaynak işaretçisi (content/chunkContent/sourceUri/embedding) yasak (NFR 10.6)")
    chk("transcript" in [s.lower() for s in FORBIDDEN_PII_KEYS] and "cdr" in [s.lower() for s in FORBIDDEN_PII_KEYS], "S4 ham müşteri içeriği (transkript/CDR) yasak (BRD §17.7)")
    leak = assert_no_pii({"data_field_scan": _extract_data_fields(data)})
    chk(leak is None, f"S4 veri seam türlerinde PII/sır alanı yok (sızıntı={leak})")

    # S5 — BRD §17.5 içerik öğeleri + FR-KB-001/003/004/005/008/010 karşılanır
    a08 = tr.get("screen", {}).get("a08", {})
    sec = a08.get("section", {})
    for s in ("summary", "bases", "documents", "sources", "index_health"):
        chk(s in sec, f"S5 section.{s} mevcut (BRD §17.5 içerik öğesi)")
    chk(set(SOURCE_ORDER).issubset(a08.get("source", {}).keys()), "S5 kaynak türleri (PDF/Word/HTML/metin/CSV/web — FR-KB-001)")
    chk(set(INDEX_ORDER).issubset(a08.get("index", {}).keys()) and "countByIndexStatus" in data, "S5 indeksleme/versiyonlama (FR-KB-003)")
    chk("binding" in data and set(["agent", "shared"]).issubset(a08.get("binding", {}).keys()) and "namespace" in data, "S5 tenant/agent izolasyon + namespace (FR-KB-004)")
    chk("restrictedDocuments" in data and set(["tenant", "restricted"]).issubset(a08.get("access", {}).keys()), "S5 doküman bazında erişim (FR-KB-005)")
    chk("staleDocuments" in data and "stale_content" in a08.get("alert", {}), "S5 bayatlama (FR-KB-008)")
    chk("sensitiveDocuments" in data and "sensitive_docs" in a08.get("alert", {}), "S5 hassas doküman (FR-KB-010)")
    chk("duplicateNamespaces" in data and "duplicate_namespace" in a08.get("alert", {}), "S5 namespace bütünlüğü (DB §12)")

    # S6 — referans anahtarlar var + TR↔EN parity + placeholder + boş değer yok
    ref = spec["referenced_keys"]
    missing_tr, missing_en, empty, ph_mismatch = [], [], [], []
    for rk in ref:
        full = f"screen.a08.{rk}"
        vt, ve = resolve(tr, full), resolve(en, full)
        if vt is None:
            missing_tr.append(rk)
        elif not vt.strip():
            empty.append(("tr", rk))
        if ve is None:
            missing_en.append(rk)
        elif not ve.strip():
            empty.append(("en", rk))
        if vt is not None and ve is not None and placeholders(vt) != placeholders(ve):
            ph_mismatch.append(rk)
    chk(not missing_tr, f"S6 TR referans anahtarları tam (eksik={missing_tr})")
    chk(not missing_en, f"S6 EN referans anahtarları tam (eksik={missing_en})")
    chk(not empty, f"S6 boş değer yok (boş={empty})")
    chk(not ph_mismatch, f"S6 TR↔EN placeholder parity (uyumsuz={ph_mismatch})")
    for key, phs in spec.get("placeholders", {}).items():
        vt = resolve(tr, f"screen.a08.{key}")
        chk(vt is not None and placeholders(vt) == set(phs), f"S6 {key} placeholder = {phs}")

    # S7 — saf türetme yardımcıları mevcut + deterministik (Date.now/random yok)
    for fn in ("sortedBases", "allDocuments", "countBySourceType", "countByIndexStatus",
               "indexedDocuments", "pendingIndexDocuments", "failedIndexDocuments", "staleDocuments",
               "sensitiveDocuments", "restrictedDocuments", "agentBoundBases", "sharedBases",
               "emptyBases", "duplicateNamespaces", "openAttentionCount", "sourceTone", "indexTone",
               "freshnessTone", "accessTone", "bindingTone"):
        chk(fn in data, f"S7 {fn} tanımlı")
    chk("SOURCE_ORDER" in data and "INDEX_ORDER" in data, "S7 SOURCE_ORDER + INDEX_ORDER sabitleri tanımlı")
    chk("Date.now(" not in data and "Math.random(" not in data, "S7 Date.now()/Math.random() çağrısı YOK (deterministik)")

    # S8 — vendor-neutral + sır yok
    forbidden_vendors = ["openai", "anthropic", "pinecone", "datadog.com", "secret=", "splunk", "sumologic", "twilio.com", "telnyx.com"]
    blob = (page + data).lower()
    hit = [v for v in forbidden_vendors if v in blob]
    chk(not hit, f"S8 vendor-neutral + sır/credential yok (bulunan={hit})")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nvalidate: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── check ────────────────────────────────────────────────────────────────────────

def _doc(ref, source="pdf", index="indexed", ver=1, chunks=10, fresh="fresh", access="tenant", sensitive=False):
    return {"docRef": ref, "title": "Doc " + ref, "sourceType": source, "indexStatus": index,
            "versionNo": ver, "chunkCount": chunks, "freshness": fresh, "accessScope": access,
            "isSensitive": sensitive, "updatedAt": "2026-01-01T00:00:00.000Z"}


def _kb(ref, ns, binding="agent", agent="AGT-1", docs=None):
    return {"kbRef": ref, "name": "KB " + ref, "namespace": ns, "binding": binding,
            "boundAgentRef": agent if binding == "agent" else None, "documents": docs or []}


def _base_view():
    # KB-01 agent'a bağlı (4 doküman; biri bayat); KB-02 tenant geneli (hassas + bekleyen + başarısız); KB-03 boş
    return {"generatedAt": "2026-06-18T09:00:00.000Z", "tenantRef": "TEN-1", "tenantName": "T",
            "knowledgeBases": [
                _kb("KB-01", "t/policy", "agent", "AGT-117", [
                    _doc("DOC-01", "pdf", "indexed", 3, 42, "fresh", "tenant", False),
                    _doc("DOC-02", "word", "indexed", 2, 28, "fresh", "tenant", False),
                    _doc("DOC-03", "csv", "indexing", 1, 0, "fresh", "restricted", False),
                    _doc("DOC-04", "html", "indexed", 5, 15, "stale", "tenant", False),
                ]),
                _kb("KB-02", "t/corp", "shared", None, [
                    _doc("DOC-05", "pdf", "indexed", 1, 12, "fresh", "restricted", True),
                    _doc("DOC-06", "pdf", "pending", 1, 0, "fresh", "tenant", False),
                    _doc("DOC-07", "web", "failed", 2, 0, "fresh", "tenant", False),
                ]),
                _kb("KB-03", "t/tech", "shared", None, []),
            ]}


def cmd_check():
    checks = []

    def chk(cond, label):
        checks.append((bool(cond), label))

    v = _base_view()
    docs = all_documents(v)
    chk([d["docRef"] for d in docs] == ["DOC-01", "DOC-02", "DOC-03", "DOC-04", "DOC-05", "DOC-06", "DOC-07"], "allDocuments düzleştir+sırala")
    chk([kb["kbRef"] for kb in sorted_bases(v)] == ["KB-01", "KB-02", "KB-03"], "sortedBases ASC")
    chk(count_by_source_type(docs) == {"pdf": 3, "word": 1, "html": 1, "text": 0, "csv": 1, "web": 1}, "countBySourceType")
    chk(count_by_index_status(docs) == {"indexed": 4, "indexing": 1, "pending": 1, "failed": 1}, "countByIndexStatus")
    chk(len(indexed_documents(docs)) == 4, "indexedDocuments=4")
    chk([d["docRef"] for d in pending_index_documents(docs)] == ["DOC-03", "DOC-06"], "pendingIndexDocuments=[03,06] (indexing+pending)")
    chk([d["docRef"] for d in failed_index_documents(docs)] == ["DOC-07"], "failedIndexDocuments=[07]")
    chk([d["docRef"] for d in stale_documents(docs)] == ["DOC-04"], "staleDocuments=[04]")
    chk([d["docRef"] for d in sensitive_documents(docs)] == ["DOC-05"], "sensitiveDocuments=[05]")
    chk([d["docRef"] for d in restricted_documents(docs)] == ["DOC-03", "DOC-05"], "restrictedDocuments=[03,05]")
    chk([kb["kbRef"] for kb in agent_bound_bases(v)] == ["KB-01"], "agentBoundBases=[KB-01]")
    chk([kb["kbRef"] for kb in shared_bases(v)] == ["KB-02", "KB-03"], "sharedBases=[KB-02,KB-03]")
    chk([kb["kbRef"] for kb in empty_bases(v)] == ["KB-03"], "emptyBases=[KB-03]")
    chk(duplicate_namespaces(v) == [], "duplicateNamespaces=[]")
    chk(open_attention_count(v) == 3, "openAttentionCount=3 (bayat1+başarısız1+boş1)")

    # yinelenen namespace (DB §12 ihlali) — KB'ler doküman taşır (boş KB katkısını izole etmek için)
    _d = [_doc("D1", "pdf", "indexed")]
    dupns = {"knowledgeBases": [_kb("A", "t/x", "agent", "AGT-1", list(_d)),
                                _kb("B", "t/x", "agent", "AGT-1", list(_d)),
                                _kb("C", "t/y", "agent", "AGT-1", list(_d))]}
    chk(duplicate_namespaces(dupns) == ["t/x"], "duplicateNamespaces=[t/x]")
    chk(open_attention_count(dupns) == 1, "openAttentionCount=1 (yalnız yinelenen namespace)")

    # tone eşlemeleri
    chk(source_tone("pdf") == "neutral" and source_tone("web") == "info", "sourceTone")
    chk(index_tone("indexed") == "success" and index_tone("indexing") == "info" and index_tone("pending") == "warning" and index_tone("failed") == "danger", "indexTone")
    chk(freshness_tone("fresh") == "success" and freshness_tone("stale") == "warning", "freshnessTone")
    chk(access_tone("tenant") == "neutral" and access_tone("restricted") == "info", "accessTone")
    chk(binding_tone("agent") == "info" and binding_tone("shared") == "neutral", "bindingTone")

    # assertNoPii — DOKÜMAN META İZİNLİ, ham içerik + sır + doküman-içeriği YASAK
    chk(assert_no_pii({"a": _base_view()}) is None, "assertNoPii doküman META İZİNLİ")
    chk(assert_no_pii({"x": {"transcript": "..."}}) == "$.x.transcript", "assertNoPii ham transcript yakalar")
    chk(assert_no_pii({"x": {"apiKey": "k"}}) == "$.x.apiKey", "assertNoPii sır yakalar (NFR 10.6)")
    chk(assert_no_pii({"x": {"content": "..."}}) == "$.x.content", "assertNoPii chunk içeriği yakalar (kb_chunk.content)")
    chk(assert_no_pii({"x": {"sourceUri": "..."}}) == "$.x.sourceUri", "assertNoPii kaynak işaretçisi yakalar (DB §12)")
    chk(assert_no_pii({"x": {"embedding": []}}) == "$.x.embedding", "assertNoPii embedding yakalar")

    # samples doğrulaması
    for name in ("kb-clean.json", "kb-issues.json"):
        snp = load_json(os.path.join(HERE, "samples", name))
        exp = snp.get("$expect", {})
        sdocs = all_documents(snp)
        chk(len(snp["knowledgeBases"]) == exp.get("bases"), f"{name} bases={exp.get('bases')}")
        chk(len(sdocs) == exp.get("documents"), f"{name} documents={exp.get('documents')}")
        chk(len(indexed_documents(sdocs)) == exp.get("indexed"), f"{name} indexed={exp.get('indexed')}")
        chk(len(pending_index_documents(sdocs)) == exp.get("pending"), f"{name} pending={exp.get('pending')}")
        chk(len(failed_index_documents(sdocs)) == exp.get("failed"), f"{name} failed={exp.get('failed')}")
        chk(len(stale_documents(sdocs)) == exp.get("stale"), f"{name} stale={exp.get('stale')}")
        chk(len(sensitive_documents(sdocs)) == exp.get("sensitive"), f"{name} sensitive={exp.get('sensitive')}")
        chk(len(restricted_documents(sdocs)) == exp.get("restricted"), f"{name} restricted={exp.get('restricted')}")
        chk(len(empty_bases(snp)) == exp.get("empty_bases"), f"{name} empty_bases={exp.get('empty_bases')}")
        chk(duplicate_namespaces(snp) == exp.get("dup_namespaces"), f"{name} dup_namespaces={exp.get('dup_namespaces')}")
        chk(open_attention_count(snp) == exp.get("attention"), f"{name} attention={exp.get('attention')}")
        chk(assert_no_pii(snp) is None, f"{name} PII/sır/içerik-free (HİJYEN+GÜVENLİK)")

    passed = sum(1 for ok, _ in checks if ok)
    total = len(checks)
    for ok, label in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\ncheck: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


# ── selftest ────────────────────────────────────────────────────────────────────

def cmd_selftest():
    results = []

    def expect(cond, label):
        results.append((bool(cond), label))

    # pozitif (sağlıklı: tüm indeksli, güncel, benzersiz namespace, boş KB yok)
    ok = {"knowledgeBases": [
        _kb("A", "t/a", "agent", "AGT-1", [_doc("D1", "pdf", "indexed", 1, 10, "fresh", "tenant", False)]),
        _kb("B", "t/b", "shared", None, [_doc("D2", "word", "indexed", 1, 8, "fresh", "tenant", False)]),
    ]}
    expect(open_attention_count(ok) == 0, "pos açık dikkat=0")
    expect(len(empty_bases(ok)) == 0, "pos boş KB yok")
    expect(duplicate_namespaces(ok) == [], "pos benzersiz namespace")
    expect(len(failed_index_documents(all_documents(ok))) == 0, "pos başarısız indeks yok")
    expect(len(stale_documents(all_documents(ok))) == 0, "pos bayat doküman yok")

    # negatif (çok-sorunlu: bayat + başarısız indeks + boş KB + yinelenen namespace)
    bad = {"knowledgeBases": [
        _kb("A", "t/dup", "agent", "AGT-1", [
            _doc("D1", "pdf", "failed", 1, 0, "fresh", "tenant", False),     # başarısız indeks
            _doc("D2", "html", "indexed", 2, 5, "stale", "tenant", False),   # bayat
        ]),
        _kb("B", "t/dup", "shared", None, []),                                # yinelenen namespace + boş KB
    ]}
    bdocs = all_documents(bad)
    expect(len(failed_index_documents(bdocs)) == 1, "neg başarısız indeks=1")
    expect(len(stale_documents(bdocs)) == 1, "neg bayat=1")
    expect(empty_bases(bad)[0]["kbRef"] == "B", "neg boş KB=B")
    expect(duplicate_namespaces(bad) == ["t/dup"], "neg yinelenen namespace=[t/dup]")
    # attention = stale(1) + failed(1) + empty(1) + dup_ns(1) = 4
    expect(open_attention_count(bad) == 4, "neg açık dikkat=4")

    # sınır: boş envanter
    empty = {"knowledgeBases": []}
    expect(all_documents(empty) == [], "sınır boş envanter doküman yok")
    expect(open_attention_count(empty) == 0, "sınır boş envanter dikkat=0")
    expect(count_by_source_type([]) == {s: 0 for s in SOURCE_ORDER}, "sınır boş kaynak dağılımı 0")

    # sınır: tek KB hiç doküman → boş KB + dikkat
    one = {"knowledgeBases": [_kb("A", "t/a", "agent", "AGT-1", [])]}
    expect(len(empty_bases(one)) == 1, "sınır tek boş KB")
    expect(open_attention_count(one) == 1, "sınır tek boş KB dikkat=1")

    # pendingIndex = pending ∪ indexing
    mix = all_documents({"knowledgeBases": [_kb("A", "t/a", "agent", "AGT-1", [
        _doc("D1", "pdf", "pending"), _doc("D2", "pdf", "indexing"), _doc("D3", "pdf", "indexed")])]})
    expect(len(pending_index_documents(mix)) == 2, "sınır pending+indexing=2")
    expect(len(indexed_documents(mix)) == 1, "sınır indexed=1")

    # assertNoPii pozitif/negatif
    expect(assert_no_pii({"a": {"b": 1}}) is None, "pos no-pii")
    expect(assert_no_pii({"x": {"callerNumber": "1"}}) is not None, "neg callerNumber yakalanır")
    expect(assert_no_pii({"s": [{"webhookSecret": "x"}]}) is not None, "neg webhookSecret yakalanır")
    expect(assert_no_pii({"x": {"content": "..."}}) is not None, "neg chunk içeriği yakalanır")
    expect(assert_no_pii({"x": {"sourceUri": "..."}}) is not None, "neg kaynak işaretçisi yakalanır (DB §12)")
    expect(assert_no_pii({"x": {"cdr": {}}}) is not None, "neg cdr yakalanır")

    # tone sınır
    expect(index_tone("failed") == "danger", "başarısız indeks → danger")
    expect(freshness_tone("stale") == "warning", "bayat → warning")
    expect(binding_tone("agent") == "info", "agent bağ → info")

    # placeholder ayrıştırma
    expect(placeholders("{count} sorun") == {"count"}, "placeholder parse")
    expect(placeholders("{a}/{b}") == {"a", "b"}, "placeholder çoklu parse")

    # spec referans anahtarları tutarlı
    spec = load_json(SPEC_PATH)
    expect(len(spec["referenced_keys"]) >= 85, "spec ≥85 referans anahtar")
    expect(spec["source_types"] == SOURCE_ORDER, "spec source_types = SOURCE_ORDER")
    expect(spec["index_statuses"] == INDEX_ORDER, "spec index_statuses = INDEX_ORDER")

    passed = sum(1 for ok, _ in results if ok)
    total = len(results)
    for ok, label in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\nselftest: {passed}/{total} {GREEN if passed == total else RED}")
    return 0 if passed == total else 1


def cmd_schema():
    print(json.dumps({
        "KbView": {
            "generatedAt": "ISO-8601 string (sabit yer tutucu)",
            "tenantRef": "str (tenant KENDİ kimliği — izinli)",
            "tenantName": "str (tenant org adı — izinli)",
            "knowledgeBases": [{
                "kbRef": "str (DB §12 knowledge_base gösterim kimliği)",
                "name": "str (KB adı — tenant config; PII değil)",
                "namespace": "str (DB §12 namespace; tenant kapsamında benzersiz — FR-KB-004)",
                "binding": "agent|shared (FR-KB-004 — agent_id var | NULL → tenant-shared)",
                "boundAgentRef": "str|null (bağlı agent)",
                "documents": [{
                    "docRef": "str (DB §12 kb_document)",
                    "title": "str (kurumsal doküman adı — tenant config; PII değil)",
                    "sourceType": "pdf|word|html|text|csv|web (FR-KB-001)",
                    "indexStatus": "indexed|indexing|pending|failed (FR-KB-003)",
                    "versionNo": "int (FR-KB-003 — yeniden ingest sürüm üretir; DB §12 version_no)",
                    "chunkCount": "int (parça SAYISI — yalnız SAYI; kb_chunk.content gömülmez)",
                    "freshness": "fresh|stale (FR-KB-008 — content_ttl_at bayatlama)",
                    "accessScope": "tenant|restricted (FR-KB-005 — doküman bazında erişim seviyesi)",
                    "isSensitive": "bool (FR-KB-010 — sağlayıcı loguna gitmez; yalnız BAYRAK)",
                    "updatedAt": "ISO-8601 (doküman META)"
                }]
            }]
        },
        "source_types": SOURCE_ORDER,
        "index_statuses": INDEX_ORDER,
        "freshness_states": ["fresh", "stale"],
        "access_scopes": ["tenant", "restricted"],
        "bindings": ["agent", "shared"],
        "hijyen": "A-08 yalnız DOKÜMAN META gösterir (kaynak türü/indeks durumu/sürüm/parça SAYISI/güncellik/erişim seviyesi/hassasiyet bayrağı + KB adı/namespace — tenant'ın KENDİ yapılandırması). FORBIDDEN_PII_KEYS dışı son-müşteri ham içeriği (transkript/kayıt/ham numara/CDR/müşteri) YOK (BRD §17.7 + §17.6); FORBIDDEN_SECRET_KEYS dışı sır/credential + DOKÜMAN İÇERİĞİ/CHUNK METNİ/KAYNAK İŞARETÇİSİ (apiKey/webhookSecret/token/content/chunkContent/sourceUri/embedding) YOK (NFR 10.6); assertNoPii çalışma-anında doğrular. İçerik yönetimi (ingest/yeniden indeksleme) derin aksiyon → API dilimi (görsel kapı). ENVANTER ekranı (FR-KB-001/003/004/005/008/010); gerçek zamanlı DEĞİL (FR-ANA-012 dışı)."
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    cmds = {"validate": cmd_validate, "check": cmd_check, "selftest": cmd_selftest, "schema": cmd_schema}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("kullanım: a08_kb_probe.py {validate|check|selftest|schema}")
        return 2
    return cmds[sys.argv[1]]()


if __name__ == "__main__":
    sys.exit(main())
