#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_connector_probe.py — WBS 6.1.1 Ingest connector: PDF/Word/HTML/metin/CSV/web (FR-KB-001)

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only ingest connector REFERANS uygulaması + statik kapı.
`adapters/`/`runtime/`/`governance/` modül disipliniyle aynı. Bu görev SAD §10.1 offline indeksleme
hattının İLK aşaması olan ingest connector'ı uygular:

    Doküman (PDF/Word/HTML/CSV/web) ──► [ingest connector] ──► Parse & normalize ──► NormalizedDocument
                                                                                       │ (6.1.3 chunk→embed→index)

Connector'ın işi: her formatı (PDF, Word/DOCX, HTML, düz metin, CSV, web sayfası) ALIR, format/MIME
algılar + beyanla UZLAŞTIRIR (content-sniffing yetkilidir — spoof tipi doğrulamayı atlatamaz), doğrular
(boyut/birim/allowlist/charset/decompression-bomb), KANONİK NormalizedDocument'a (normalize metin +
hafif yapı + metadata + içerik hash'i) AYIKLAR, tenant/kb namespace etiketler, erişim-metadata kancası
(→6.1.4) + residency/no-log/PII (FR-KB-010) işaretler. Çıktıyı 6.1.3 chunk→embed→index+versiyonlama
TÜKETİR. Format-spesifik ayıklama BURADA; format-agnostik chunk/embed/index 6.1.3'te.

KAPSAM AYRIMI (G10 — bilinçli sınır): chunk/embed/index/versiyonlama → 6.1.3 (tüketir); SharePoint/
Confluence connector → 6.1.2; doküman-bazı erişim yetkisi UYGULAMA → 6.1.4 (connector yalnız metadata
KANCASI ekler); içerik bayatlama/TTL → 6.1.5; vector store namespace fiziksel → 1.1.7; retrieval/rerank/
trim → 6.2.x; KB benchmark → 6.2.5/FR-KB-009; sağlayıcı LLM no-log UYGULAMA → 4.2.4/5.8. Bu motor
embedding ÜRETMEZ, vektör YAZMAZ.

Komutlar:
  validate            ingest-connector-spec.json'ı invariant'lara (G1–G10) + config form
                      kayıt defterine doğrular (statik; sunucu/credential gerekmez).
  ingest <sample>     Deterministik IngestConnector — senaryo kaynaklarını işler → NormalizedDocument'lar
                      + HARD kapılar (G1–G10) → çıkış kodu. Gerçek dosyaları (fixtures/) gerçek
                      ayıklayıcılarla parse eder.
  selftest            İyi/kötü senaryolar + her ayıklayıcıyı fixture'larla deneyerek kapıların doğru
                      tetiklendiğini kanıtlar.
  schema              Beklenen spec/sample şeklini özetler.

Vendor-neutral (ADR-002): her formatın ayıklayıcısı bir SPI arkasındadır; referans stdlib ayıklayıcı
(text/csv/html/docx-zip+xml/pdf-bounded) yeterlidir, canlı sistemde ağır PDF/Office kütüphanesi aynı SPI
arkasına TAKILIR. Determinizm: sanal saat (Date.now/rastgele YOK). Spec/config/sample'larda sır/credential
ve gerçek PII DEĞERİ yok (fixture içerikleri sentetik — FR-TST-008).
"""
import base64
import csv as csvmod
import hashlib
import io
import json
import os
import re
import sys
import unicodedata
import zipfile
import zlib
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC_PATH = os.path.join(HERE, "ingest-connector-spec.json")
PROFILES_CFG = os.path.join(HERE, "config", "ingest-connector-profiles.json")
FIXTURES_DIR = os.path.join(HERE, "samples", "fixtures")

# Desteklenen formatlar (FR-KB-001: PDF, Word, HTML, metin, CSV, web).
FORMATS = ["pdf", "docx", "html", "text", "csv", "web"]

# Ingest hata taksonomisi (API §11.6 ruhu — connector'a özgü sınıflar). DETERMİNİSTİK + müşteriye sızmaz.
ERROR_CLASSES = {
    "UNSUPPORTED_FORMAT", "FORMAT_MISMATCH", "TOO_LARGE", "TOO_MANY_UNITS",
    "CORRUPT", "EMPTY", "ENCODING_ERROR", "ENCRYPTED", "NEEDS_OCR",
    "DECOMPRESSION_BOMB", "FETCH_ERROR", "REGION_VIOLATION", "MISSING_TENANT_CONTEXT",
}
# Geçici-olmayan / içerik kalıcı sorunları → yeniden deneme/2.connector boşuna (sınıflandır + atla).
SECRET_RE = re.compile(
    r"(?i)\b(?:auth[_-]?token|api[_-]?key|secret|password|passwd|bearer|client[_-]?secret)\b"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9/\+_\-]{12,}"
)
PLACEHOLDER_RE = re.compile(r"^\$\{[A-Z0-9_]+\}$")
# Spec/config'te ham PII DEĞERİ olmamalı (doküman İÇERİĞİ runtime'da olabilir; spec/config'te yasak).
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")
TCKN_RE = re.compile(r"\b[1-9]\d{10}\b")

GATE_IDS = ["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"]


def _load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder(v):
    return isinstance(v, str) and PLACEHOLDER_RE.match(v) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Metin normalizasyonu (kanonik biçim — G4)
# ─────────────────────────────────────────────────────────────────────────────
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_text(s):
    """Unicode NFC + kontrol karakteri temizliği + boşluk daraltma (deterministik)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _CTRL_RE.sub("", s)
    # Satır içi boşlukları daralt, satır sonlarını koru.
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    # Birden çok boş satırı tek boş satıra indir.
    out = []
    blank = False
    for ln in lines:
        if ln == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Format algılama (magic bytes / yapı) + beyan uzlaştırma (G2)
# ─────────────────────────────────────────────────────────────────────────────
def detect_family(raw):
    """İçerikten format AİLESİ döndürür: pdf|docx|html|text|zip-unknown|binary."""
    if raw[:5] == b"%PDF-" or raw[:4] == b"%PDF":
        return "pdf"
    if raw[:4] == b"PK\x03\x04" or raw[:2] == b"PK":
        # Zip — docx mı? word/document.xml veya OOXML content-type ara.
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                names = set(z.namelist())
                if "word/document.xml" in names or "[Content_Types].xml" in names:
                    return "docx"
        except Exception:
            return "binary"
        return "zip-unknown"
    head = raw[:512].lstrip()
    low = head.lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html") or b"<html" in low[:200] or b"<body" in low[:300]:
        return "html"
    # Metin olarak çözülebiliyor mu?
    try:
        raw[:4096].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        try:
            raw[:4096].decode("utf-8-sig")
            return "text"
        except UnicodeDecodeError:
            return "binary"


# Beyan formatı → uyumlu algılanan aile(ler).
COMPAT = {
    "pdf": {"pdf"},
    "docx": {"docx"},
    "html": {"html"},
    "web": {"html"},        # web sayfası HTTP üzerinden gelen HTML
    "text": {"text", "html"},  # metin; bazı .txt aslında basit html olabilir → metin kabul (aşağıda csv değil)
    "csv": {"text"},        # csv düz metindir; ayrıca csv olarak parse edilmeli
}


# ─────────────────────────────────────────────────────────────────────────────
# Charset çözümü (G3 — encoding)
# ─────────────────────────────────────────────────────────────────────────────
def decode_text(raw):
    """BOM/UTF-8/cp1254/latin-1 sırayla. (charset, text) veya (None, None) ENCODING_ERROR."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return enc, raw.decode(enc)
        except UnicodeDecodeError:
            continue
    for enc in ("cp1254", "latin-1"):
        try:
            return enc, raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None


# ─────────────────────────────────────────────────────────────────────────────
# HTML ayıklayıcı (text + hafif yapı; script/style/boilerplate atılır) — G1/G4
# ─────────────────────────────────────────────────────────────────────────────
_DROP_TAGS = {"script", "style", "noscript", "head"}
_BOILER_TAGS = {"nav", "footer", "aside"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = {"p", "li", "div", "section", "article", "td", "th", "tr", "br"}


class _HTMLExtract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self._drop_depth = 0
        self._boiler_depth = 0
        self.blocks = []
        self._buf = []
        self._cur_kind = "paragraph"

    def _flush(self):
        txt = " ".join("".join(self._buf).split())
        if txt:
            self.blocks.append({"type": self._cur_kind, "text": txt})
        self._buf = []
        self._cur_kind = "paragraph"

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_TAGS:
            self._drop_depth += 1
        elif tag in _BOILER_TAGS:
            self._boiler_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _HEADING_TAGS:
            self._flush()
            self._cur_kind = "heading"
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _DROP_TAGS and self._drop_depth > 0:
            self._drop_depth -= 1
        elif tag in _BOILER_TAGS and self._boiler_depth > 0:
            self._boiler_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in _HEADING_TAGS or tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
            return
        if self._drop_depth > 0:
            return
        if self._boiler_depth > 0:
            return
        self._buf.append(data)


def extract_html(raw, ctx):
    charset, text = decode_text(raw)
    if text is None:
        return _err("ENCODING_ERROR", "html charset çözülemedi")
    p = _HTMLExtract()
    try:
        p.feed(text)
        p.close()
        p._flush()
    except Exception as e:
        return _err("CORRUPT", "html parse hatası: %s" % type(e).__name__)
    blocks = p.blocks
    body = "\n".join(b["text"] for b in blocks)
    title = (p.title or "").strip() or (blocks[0]["text"] if blocks else None)
    return {
        "text": body, "blocks": blocks, "title": title,
        "unit_count": len(blocks), "unit_kind": "blocks", "charset": charset,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Düz metin ayıklayıcı — G1/G4
# ─────────────────────────────────────────────────────────────────────────────
def extract_text(raw, ctx):
    charset, text = decode_text(raw)
    if text is None:
        return _err("ENCODING_ERROR", "metin charset çözülemedi")
    blocks = [{"type": "paragraph", "text": ln} for ln in text.split("\n") if ln.strip()]
    title = blocks[0]["text"][:120] if blocks else None
    return {
        "text": text, "blocks": blocks, "title": title,
        "unit_count": len(text), "unit_kind": "chars", "charset": charset,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV ayıklayıcı — G1/G4 (satır/yapı korunur)
# ─────────────────────────────────────────────────────────────────────────────
def extract_csv(raw, ctx, max_cols=4096):
    charset, text = decode_text(raw)
    if text is None:
        return _err("ENCODING_ERROR", "csv charset çözülemedi")
    sample = text[:4096]
    try:
        dialect = csvmod.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        dialect = csvmod.excel
    all_rows = []
    reader = csvmod.reader(io.StringIO(text), dialect)
    for row in reader:
        if len(row) > max_cols:
            return _err("CORRUPT", "csv sütun sayısı sınırı aştı")
        if any(c.strip() for c in row):
            all_rows.append(row)
    if not all_rows:
        return _err("EMPTY", "csv boş")
    # Başlık tespiti: ctx açıkça belirtirse onu kullan; aksi halde sezgisel
    # (ilk satır hücreleri boş değil + tamamen sayısal değil + benzersiz → başlık).
    if "csv_has_header" in ctx:
        has_header = bool(ctx["csv_has_header"])
    else:
        first = all_rows[0]
        def _numeric(c):
            try:
                float(c.strip().replace(",", "")); return True
            except ValueError:
                return False
        has_header = (
            len(all_rows) > 1
            and all(c.strip() for c in first)
            and not any(_numeric(c) for c in first)
            and len(set(c.strip().lower() for c in first)) == len(first)
        )
    header = all_rows[0] if has_header else None
    rows = all_rows[1:] if has_header else all_rows
    if header is None and not rows:
        return _err("EMPTY", "csv boş")
    blocks = []
    if header:
        blocks.append({"type": "table_header", "text": " | ".join(header)})
    text_lines = []
    for r in rows:
        if header and len(r) == len(header):
            line = "; ".join("%s: %s" % (h, v) for h, v in zip(header, r))
        else:
            line = " | ".join(r)
        blocks.append({"type": "table_row", "text": line})
        text_lines.append(line)
    body = "\n".join(text_lines)
    return {
        "text": body, "blocks": blocks,
        "title": (header[0] if header else (text_lines[0][:120] if text_lines else None)),
        "unit_count": len(rows), "unit_kind": "rows", "charset": charset,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOCX ayıklayıcı (zip + OOXML) — G1/G4 + decompression-bomb guard (G3)
# ─────────────────────────────────────────────────────────────────────────────
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx(raw, ctx, max_ratio=200, max_uncompressed=200 * 1024 * 1024):
    import xml.etree.ElementTree as ET
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        return _err("CORRUPT", "docx zip açılamadı")
    total_unc = sum(i.file_size for i in zf.infolist())
    total_comp = max(1, sum(i.compress_size for i in zf.infolist()))
    if total_unc > max_uncompressed or (total_unc / total_comp) > max_ratio:
        return _err("DECOMPRESSION_BOMB",
                    "docx açılım oranı %.0f (üst sınır %d)" % (total_unc / total_comp, max_ratio))
    names = set(zf.namelist())
    if "word/document.xml" not in names:
        return _err("CORRUPT", "docx word/document.xml yok")
    try:
        xml = zf.read("word/document.xml")
        root = ET.fromstring(xml)
    except Exception:
        return _err("CORRUPT", "docx document.xml parse edilemedi")
    blocks = []
    # Paragraflar + tablolar belge sırasında.
    body = root.find("%sbody" % _W_NS)
    if body is None:
        return _err("EMPTY", "docx body yok")

    def para_text(p):
        return "".join(t.text or "" for t in p.iter("%st" % _W_NS))

    for el in body:
        tag = el.tag
        if tag == "%sp" % _W_NS:
            txt = para_text(el).strip()
            if txt:
                blocks.append({"type": "paragraph", "text": txt})
        elif tag == "%stbl" % _W_NS:
            for tr in el.iter("%str" % _W_NS):
                cells = [para_text(tc).strip() for tc in tr.iter("%stc" % _W_NS)]
                line = " | ".join(c for c in cells if c)
                if line:
                    blocks.append({"type": "table_row", "text": line})
    if not blocks:
        return _err("EMPTY", "docx metin içermiyor")
    text = "\n".join(b["text"] for b in blocks)
    paras = sum(1 for b in blocks if b["type"] == "paragraph")
    return {
        "text": text, "blocks": blocks,
        "title": blocks[0]["text"][:120],
        "unit_count": max(1, paras), "unit_kind": "paragraphs", "charset": "utf-8",
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF ayıklayıcı (sınırlı: uncompressed + FlateDecode text stream; Tj/TJ) — G1/G4
#   Üretim sistemi aynı SPI arkasına ağır PDF kütüphanesi takar (ADR-001/002).
# ─────────────────────────────────────────────────────────────────────────────
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_TJ_RE = re.compile(rb"\((?:[^()\\]|\\.)*\)\s*Tj")
_TJARR_RE = re.compile(rb"\[(.*?)\]\s*TJ", re.DOTALL)
_PDFSTR_RE = re.compile(rb"\((?:[^()\\]|\\.)*\)")
_TJNUM_RE = re.compile(rb"(-?\d+(?:\.\d+)?)")


def _pdf_unescape(b):
    out = []
    i = 0
    n = len(b)
    while i < n:
        c = b[i:i + 1]
        if c == b"\\" and i + 1 < n:
            nxt = b[i + 1:i + 2]
            mp = {b"n": "\n", b"r": "\n", b"t": "\t", b"b": "", b"f": "",
                  b"(": "(", b")": ")", b"\\": "\\"}
            if nxt in mp:
                out.append(mp[nxt]); i += 2; continue
            if nxt == b"\n":
                i += 2; continue
            m = re.match(rb"[0-7]{1,3}", b[i + 1:i + 4])
            if m:
                out.append(chr(int(m.group(0), 8))); i += 1 + len(m.group(0)); continue
            out.append(nxt.decode("latin-1")); i += 2; continue
        out.append(c.decode("latin-1")); i += 1
    return "".join(out)


def _decode_stream(s):
    """FlateDecode dene; başarısızsa ham. (text_bytes)."""
    if s[:1] == b"\x78":  # zlib magic
        try:
            return zlib.decompress(s)
        except Exception:
            pass
    return s


def extract_pdf(raw, ctx):
    if b"/Encrypt" in raw:
        return _err("ENCRYPTED", "pdf şifreli (decrypt kapsam dışı → 6.1.x adapter)")
    pages = len(re.findall(rb"/Type\s*/Page\b", raw))
    pages = max(1, pages)
    streams = _STREAM_RE.findall(raw)
    if not streams:
        return _err("CORRUPT", "pdf içinde içerik akışı (stream) bulunamadı")
    pieces = []
    found_text_ops = False
    for s in streams:
        content = _decode_stream(s)
        # Tj
        for m in _TJ_RE.finditer(content):
            found_text_ops = True
            lit = _PDFSTR_RE.search(m.group(0))
            if lit:
                pieces.append(_pdf_unescape(lit.group(0)[1:-1]))
        # TJ array
        for m in _TJARR_RE.finditer(content):
            found_text_ops = True
            arr = m.group(0)
            parts = []
            for tok in _PDFSTR_RE.finditer(arr):
                parts.append(_pdf_unescape(tok.group(0)[1:-1]))
            pieces.append("".join(parts))
    text = "\n".join(p for p in pieces if p.strip())
    if not text.strip():
        if not found_text_ops:
            return _err("NEEDS_OCR", "pdf metin operatörü yok (büyük olasılıkla taranmış/görüntü) — OCR gerekir")
        return _err("CORRUPT", "pdf metni ayıklanamadı")
    blocks = [{"type": "paragraph", "text": ln} for ln in text.split("\n") if ln.strip()]
    return {
        "text": text, "blocks": blocks,
        "title": blocks[0]["text"][:120] if blocks else None,
        "unit_count": pages, "unit_kind": "pages", "charset": "utf-8",
    }


# Format → ayıklayıcı SPI kayıt defteri (vendor-neutral; canlı sistemde ağır lib aynı imza arkasına takılır).
EXTRACTORS = {
    "pdf": extract_pdf,
    "docx": extract_docx,
    "html": extract_html,
    "web": extract_html,
    "text": extract_text,
    "csv": extract_csv,
}


def _err(cls, detail):
    return {"_error": True, "error_class": cls, "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# IngestConnector — senaryo işleme + G1–G10 kapıları
# ─────────────────────────────────────────────────────────────────────────────
class IngestConnector:
    def __init__(self, profile):
        self.p = profile
        self.max_bytes = profile.get("max_bytes", 25 * 1024 * 1024)
        self.max_units = profile.get("max_units", {})
        self.allowed = set(profile.get("allowed_formats", FORMATS))
        self.region = profile.get("residency_region", "home")
        self.allowed_regions = set(profile.get("allowed_regions", [self.region]))
        self.seen_hashes = {}  # content_hash -> doc_id (dedup, tenant kapsamlı)
        self.t = int(profile.get("virtual_t0", 1_000_000))

    def _next_t(self):
        self.t += 1
        return self.t

    def _read_bytes(self, src):
        if "inline_text" in src:
            return src["inline_text"].encode("utf-8")
        if "bytes_b64" in src:
            return base64.b64decode(src["bytes_b64"])
        if "fixture" in src:
            path = os.path.join(FIXTURES_DIR, src["fixture"])
            with open(path, "rb") as f:
                return f.read()
        # web: gövde sample içinde (offline; canlı fetch run_live_test'te ${ENV} ile).
        if "body" in src:
            return src["body"].encode("utf-8")
        return None

    def ingest_source(self, src):
        sid = src.get("source_id", "?")
        declared = src.get("format_declared")
        tenant = src.get("tenant_id")
        kb = src.get("kb_id")
        region = src.get("region", self.region)

        # G6: tenant context fail-closed.
        if not tenant or not kb:
            return self._rejected(sid, declared, "MISSING_TENANT_CONTEXT",
                                  "tenant_id/kb_id zorunlu (fail-closed)")
        # G8: residency.
        if region not in self.allowed_regions:
            return self._rejected(sid, declared, "REGION_VIOLATION",
                                  "kaynak bölgesi %s izinli değil" % region)
        # Format allowlist (G3).
        if declared not in self.allowed:
            return self._rejected(sid, declared, "UNSUPPORTED_FORMAT",
                                  "beyan formatı '%s' allowlist dışı" % declared, tenant, kb)
        # Baytları al.
        try:
            raw = self._read_bytes(src)
        except FileNotFoundError:
            return self._rejected(sid, declared, "FETCH_ERROR", "kaynak okunamadı", tenant, kb)
        if raw is None:
            return self._rejected(sid, declared, "FETCH_ERROR", "kaynak içeriği yok", tenant, kb)
        # G3: boyut.
        if len(raw) == 0:
            return self._rejected(sid, declared, "EMPTY", "boş kaynak", tenant, kb)
        if len(raw) > self.max_bytes:
            return self._rejected(sid, declared, "TOO_LARGE",
                                  "boyut %d > %d" % (len(raw), self.max_bytes), tenant, kb)
        # G2: format algıla + uzlaştır (content-sniffing yetkili).
        detected = detect_family(raw)
        compat = COMPAT.get(declared, set())
        mismatch = detected not in compat
        if mismatch:
            return self._rejected(sid, declared, "FORMAT_MISMATCH",
                                  "beyan=%s algılanan=%s (spoof reddi)" % (declared, detected),
                                  tenant, kb, detected=detected)
        # Ayıkla (G1/G4).
        extractor = EXTRACTORS[declared]
        res = extractor(raw, src)
        if res.get("_error"):
            return self._rejected(sid, declared, res["error_class"], res["detail"],
                                  tenant, kb, detected=detected)
        norm = normalize_text(res["text"])
        if not norm:
            return self._rejected(sid, declared, "EMPTY", "ayıklanan metin boş", tenant, kb, detected=detected)
        # G3: birim sınırı.
        unit_kind = res["unit_kind"]
        unit_count = res["unit_count"]
        cap = self.max_units.get(unit_kind)
        if cap is not None and unit_count > cap:
            return self._rejected(sid, declared, "TOO_MANY_UNITS",
                                  "%s %d > %d" % (unit_kind, unit_count, cap), tenant, kb, detected=detected)
        # G5: metadata + içerik hash + dedup.
        chash = content_hash(norm)
        dedup_key = (tenant, kb, chash)
        duplicate_of = self.seen_hashes.get(dedup_key)
        if duplicate_of is None:
            self.seen_hashes[dedup_key] = sid
        doc = {
            "status": "ingested",
            "doc_id": "doc-%s" % chash[:12],
            "source_id": sid,
            "tenant_id": tenant,
            "kb_id": kb,
            "format": declared,
            "detected_format": detected,
            "content_type": src.get("content_type"),
            "title": (res.get("title") or "")[:200] or None,
            "text": norm,
            "blocks": res["blocks"],
            "char_count": len(norm),
            "byte_size": len(raw),
            "unit_count": unit_count,
            "unit_kind": unit_kind,
            "charset": res.get("charset"),
            "content_hash": chash,
            "duplicate_of": duplicate_of,           # G5 idempotent re-ingest
            "language_hint": src.get("language_hint"),
            "ingested_at": self._next_t(),          # sanal saat
            "classification": src.get("classification", "internal"),  # G7 ACL kancası (→6.1.4)
            "acl_ref": src.get("acl_ref"),
            "sensitive": bool(src.get("sensitive", False)),
            "redaction_state": "pending",           # G8 PII (→6.1.4/4.x redaction)
            "no_log": True,                         # FR-KB-010
            "residency_region": region,
            "source_uri": src.get("url") or src.get("filename") or src.get("fixture") or sid,
        }
        return doc

    def _rejected(self, sid, declared, cls, detail, tenant=None, kb=None, detected=None):
        return {
            "status": "rejected", "source_id": sid, "format": declared,
            "error_class": cls, "detail": detail, "tenant_id": tenant, "kb_id": kb,
            "detected_format": detected,
        }

    def run(self, sources):
        results = []
        for src in sources:
            try:
                results.append(self.ingest_source(src))   # G9: bir hata batch'i durdurmaz
            except Exception as e:  # never-crash garantisi
                results.append(self._rejected(src.get("source_id", "?"), src.get("format_declared"),
                                              "CORRUPT", "beklenmedik: %s" % type(e).__name__,
                                              src.get("tenant_id"), src.get("kb_id")))
        return results


# ─────────────────────────────────────────────────────────────────────────────
# Kapı değerlendirme (G1–G10) — bir senaryo sonucu üzerinde
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_gates(sources, results, connector):
    checks = []

    def chk(gid, ok, msg):
        checks.append((gid, bool(ok), msg))

    ingested = [r for r in results if r["status"] == "ingested"]
    rejected = [r for r in results if r["status"] == "rejected"]
    by_sid = {s.get("source_id"): s for s in sources}

    # Her kaynak expect'ine göre doğrulanmış mı?
    expect_mismatch = []
    for r in results:
        exp = (by_sid.get(r["source_id"], {}) or {}).get("expect", {})
        if not exp:
            continue
        if exp.get("status") and exp["status"] != r["status"]:
            expect_mismatch.append((r["source_id"], exp.get("status"), r["status"]))
        if exp.get("error_class") and r["status"] == "rejected" and exp["error_class"] != r.get("error_class"):
            expect_mismatch.append((r["source_id"], exp["error_class"], r.get("error_class")))
        if exp.get("min_chars") and r["status"] == "ingested" and r["char_count"] < exp["min_chars"]:
            expect_mismatch.append((r["source_id"], "min_chars", r["char_count"]))

    # G1 FORMAT COVERAGE — ingested doc'ların hepsi boş-olmayan metin/yapı üretti + beklenen format set.
    ok_g1 = all(d["char_count"] > 0 and d["blocks"] for d in ingested)
    fmts_ingested = sorted({d["format"] for d in ingested})
    chk("G1", ok_g1, "ingested=%d hepsi metin+yapı üretti; formatlar=%s" % (len(ingested), fmts_ingested))

    # G2 DETECTION + RECONCILE — mismatch beklenen yerde FORMAT_MISMATCH, ingested'ta spoof yok.
    spoof_leak = [d for d in ingested if d["detected_format"] not in COMPAT.get(d["format"], set())]
    chk("G2", not spoof_leak, "content-sniffing uzlaştırma: spoof sızıntısı=%d" % len(spoof_leak))

    # G3 VALIDATION — reddedilenlerin sınıfı taksonomide; ingested birim/boyut sınırını aşmıyor.
    bad_cls = [r for r in rejected if r.get("error_class") not in ERROR_CLASSES]
    oversize = [d for d in ingested if d["byte_size"] > connector.max_bytes]
    over_units = [d for d in ingested
                  if connector.max_units.get(d["unit_kind"]) is not None
                  and d["unit_count"] > connector.max_units[d["unit_kind"]]]
    chk("G3", not bad_cls and not oversize and not over_units,
        "geçersiz-sınıf=%d oversize=%d over-units=%d" % (len(bad_cls), len(oversize), len(over_units)))

    # G4 NORMALIZATION — kanonik metin: ham bayt/kontrol karakteri yok; NFC.
    ctrl_leak = [d for d in ingested if _CTRL_RE.search(d["text"])]
    nfc_ok = all(d["text"] == unicodedata.normalize("NFC", d["text"]) for d in ingested)
    chk("G4", not ctrl_leak and nfc_ok, "kontrol-karakteri sızıntı=%d nfc_ok=%s" % (len(ctrl_leak), nfc_ok))

    # G5 METADATA + HASH + DEDUP — her doc content_hash + zorunlu metadata; aynı içerik tekilleşir.
    missing_meta = [d for d in ingested
                    if not d.get("content_hash") or not d.get("doc_id")
                    or not d.get("source_uri") or d.get("ingested_at") is None]
    # Dedup: aynı (tenant,kb,hash) için yalnız ilki duplicate_of=None.
    seen = {}
    dup_ok = True
    for d in ingested:
        key = (d["tenant_id"], d["kb_id"], d["content_hash"])
        if key in seen:
            if d.get("duplicate_of") != seen[key]:
                dup_ok = False
        else:
            seen[key] = d["source_id"]
            if d.get("duplicate_of") is not None:
                dup_ok = False
    chk("G5", not missing_meta and dup_ok,
        "eksik-metadata=%d dedup_ok=%s" % (len(missing_meta), dup_ok))

    # G6 TENANT/KB NAMESPACE + ISOLATION — her doc tenant+kb taşır; cross-tenant hash çakışması ayrı.
    no_tenant = [d for d in ingested if not d.get("tenant_id") or not d.get("kb_id")]
    # Aynı içerik farklı tenant → farklı dedup uzayı (sızıntı yok): aynı hash farklı tenant ayrı doc.
    cross = {}
    cross_leak = 0
    for d in ingested:
        h = d["content_hash"]
        cross.setdefault(h, set()).add(d["tenant_id"])
    # cross-tenant aynı içerik problemsiz (içerik aynı olabilir); sızıntı = bir doc yanlış tenant'a yazılması.
    # Burada her doc kendi src.tenant'ını taşıyor mu kontrol et.
    for s in sources:
        rs = [r for r in results if r["source_id"] == s.get("source_id") and r["status"] == "ingested"]
        for r in rs:
            if r["tenant_id"] != s.get("tenant_id"):
                cross_leak += 1
    chk("G6", not no_tenant and cross_leak == 0,
        "tenant'sız=%d cross-tenant-sızıntı=%d" % (len(no_tenant), cross_leak))

    # G7 ACCESS METADATA HOOK — her doc classification + redaction_state taşır (→6.1.4).
    no_acl = [d for d in ingested if not d.get("classification") or not d.get("redaction_state")]
    chk("G7", not no_acl, "acl/redaction kancası eksik=%d" % len(no_acl))

    # G8 RESIDENCY + NO-LOG + PII — her doc home-region + no_log + redaction pending; hassas işaretli.
    region_bad = [d for d in ingested if d["residency_region"] not in connector.allowed_regions]
    nolog_bad = [d for d in ingested if not d.get("no_log")]
    redact_bad = [d for d in ingested if d.get("redaction_state") != "pending"]
    chk("G8", not region_bad and not nolog_bad and not redact_bad,
        "region-ihlal=%d no_log-eksik=%d redaction-eksik=%d" % (len(region_bad), len(nolog_bad), len(redact_bad)))

    # G9 ROBUST / NEVER-CRASH — her kaynak bir sonuç üretti (exception kaçmadı) + beklentiler tuttu.
    chk("G9", len(results) == len(sources) and not expect_mismatch,
        "sonuç=%d/%d beklenti-uyumsuz=%d" % (len(results), len(sources), len(expect_mismatch)))

    # G10 SCOPE BOUNDARY — connector embedding/vektör üretmez (doc'ta embedding/vector alanı yok).
    leaked_scope = [d for d in ingested if any(k in d for k in ("embedding", "vector", "chunk_ids", "index_id"))]
    chk("G10", not leaked_scope, "kapsam-dışı alan sızıntısı=%d (embed/index → 6.1.3)" % len(leaked_scope))

    return checks


# ─────────────────────────────────────────────────────────────────────────────
# validate — statik spec/config kapısı
# ─────────────────────────────────────────────────────────────────────────────
def _scan_secrets(obj, path="$"):
    """Spec/config'te sır + ham PII DEĞERİ taraması (placeholder hariç)."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += _scan_secrets(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _scan_secrets(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        if _is_placeholder(obj):
            return hits
        if SECRET_RE.search(obj):
            hits.append(("secret", path))
        # $comment / metin açıklamalar PII örüntüsü içerebilir; yalnız uzun rakam dizileri kontrol et.
        if CREDIT_CARD_RE.search(obj) and "comment" not in path.lower():
            hits.append(("pii-card", path))
    return hits


def validate():
    n = 0
    fail = 0

    def ok(cond, msg):
        nonlocal n, fail
        n += 1
        if not cond:
            fail += 1
            print("  ✗ %s" % msg)

    try:
        spec = _load(SPEC_PATH)
    except Exception as e:
        print("FAIL: spec yüklenemedi: %s" % e)
        return 2
    try:
        cfg = _load(PROFILES_CFG)
    except Exception as e:
        print("FAIL: config yüklenemedi: %s" % e)
        return 2

    # Üst düzey alanlar.
    for key in ("wbs", "phase", "trace", "placement", "spi", "gates",
                "formats", "error_taxonomy", "residency", "pii", "invariants"):
        ok(key in spec, "spec.%s eksik" % key)
    ok(spec.get("wbs") == "6.1.1", "wbs=6.1.1 olmalı")
    ok(spec.get("phase") == "F1", "phase=F1 olmalı")

    tr = spec.get("trace", {})
    ok("FR-KB-001" in tr.get("fr", []), "trace.fr FR-KB-001 içermeli")
    ok("SR-KB-001" in tr.get("srs", []), "trace.srs SR-KB-001 içermeli")
    ok("TC-KB-001" in tr.get("rtm", []), "trace.rtm TC-KB-001 içermeli")
    for adr in ("ADR-001", "ADR-002"):
        ok(any(str(a).startswith(adr) for a in tr.get("adr", [])), "trace.adr %s içermeli" % adr)

    # Formatlar: 6 format kayıtlı + ayıklayıcı var.
    fmts = spec.get("formats", {})
    fmt_keys = {k for k in fmts if not k.startswith("$")}
    for f in FORMATS:
        ok(f in fmt_keys, "formats.%s eksik" % f)
        ok(f in EXTRACTORS, "EXTRACTORS.%s eksik (kod)" % f)
    ok(fmt_keys == set(FORMATS), "formats tam olarak 6 format olmalı")

    # Gates eşikleri.
    g = spec.get("gates", {})
    for key in ("max_bytes", "max_units", "min_formats_supported",
                "max_format_mismatch_leak", "max_cross_tenant", "require_content_hash",
                "require_dedup", "require_tenant_context", "require_acl_hook",
                "require_no_log", "require_redaction_pending"):
        ok(key in g, "gates.%s eksik" % key)
    ok(g.get("min_formats_supported") == 6, "min_formats_supported=6 olmalı")
    ok(g.get("max_cross_tenant") == 0, "max_cross_tenant=0 olmalı")
    ok(g.get("max_format_mismatch_leak") == 0, "max_format_mismatch_leak=0 olmalı")

    # Invariants G1–G10.
    inv_ids = [i.get("id") for i in spec.get("invariants", [])]
    for gid in GATE_IDS:
        ok(gid in inv_ids, "invariant %s eksik" % gid)
    ok(len(inv_ids) == len(set(inv_ids)), "invariant id'leri tekil olmalı")

    # Error taxonomy.
    et = spec.get("error_taxonomy", {})
    classes = set(et.get("classes", []))
    ok(classes == ERROR_CLASSES, "error_taxonomy.classes kod ile birebir olmalı (fark: %s)"
       % (classes ^ ERROR_CLASSES))

    # Residency / pii bayrakları.
    res = spec.get("residency", {})
    ok(res.get("region_pin_required") is True, "residency.region_pin_required=true")
    ok(res.get("no_log_required") is True, "residency.no_log_required=true")
    pii = spec.get("pii", {})
    ok(pii.get("raw_pii_in_spec_forbidden") is True, "pii.raw_pii_in_spec_forbidden=true")
    ok(pii.get("durable_redaction_state") == "pending", "pii.durable_redaction_state=pending")

    # Config profilleri: en az 1 profil, allowed_formats ⊆ FORMATS, max_bytes>0, region.
    profiles = cfg.get("profiles", {})
    ok(len(profiles) >= 2, "en az 2 profil olmalı")
    for name, pr in profiles.items():
        af = set(pr.get("allowed_formats", []))
        ok(af and af <= set(FORMATS), "profil %s allowed_formats geçersiz" % name)
        ok(pr.get("max_bytes", 0) > 0, "profil %s max_bytes>0" % name)
        ok("residency_region" in pr, "profil %s residency_region eksik" % name)
        ok(isinstance(pr.get("max_units", {}), dict), "profil %s max_units dict" % name)

    # Sır + PII taraması (spec + config).
    sec = _scan_secrets(spec, "spec") + _scan_secrets(cfg, "config")
    ok(not sec, "spec/config sır/PII içermemeli: %s" % sec[:3])

    print("validate: %d kontrol, %d hata" % (n, fail))
    if fail == 0:
        print("OK 🟢 validate %d/%d" % (n - fail, n))
    return 1 if fail else 0


# ─────────────────────────────────────────────────────────────────────────────
# ingest <sample>
# ─────────────────────────────────────────────────────────────────────────────
def _profile_for(scenario, cfg):
    pname = scenario.get("profile", "pilot-default")
    profiles = cfg.get("profiles", {})
    pr = dict(profiles.get(pname) or {})
    if "virtual_t0" in scenario:
        pr["virtual_t0"] = scenario["virtual_t0"]
    return pname, pr


def ingest_cmd(sample_path):
    try:
        scenario = _load(sample_path)
        cfg = _load(PROFILES_CFG)
    except Exception as e:
        print("FAIL: yüklenemedi: %s" % e)
        return 2
    pname, pr = _profile_for(scenario, cfg)
    conn = IngestConnector(pr)
    sources = scenario.get("sources", [])
    results = conn.run(sources)
    checks = evaluate_gates(sources, results, conn)

    print("== senaryo: %s (profil=%s, %d kaynak) ==" % (scenario.get("scenario", "?"), pname, len(sources)))
    for r in results:
        if r["status"] == "ingested":
            print("  ✓ %-10s %-5s → doc=%s %d kar %d %s%s"
                  % (r["source_id"], r["format"], r["doc_id"], r["char_count"],
                     r["unit_count"], r["unit_kind"],
                     " [DUP]" if r.get("duplicate_of") else ""))
        else:
            print("  ✗ %-10s %-5s → REJECTED %s (%s)"
                  % (r["source_id"], r.get("format"), r["error_class"], r["detail"]))

    n_fail = 0
    print("  -- kapılar --")
    for gid, okc, msg in checks:
        print("  %s %s: %s" % ("🟢" if okc else "🔴", gid, msg))
        if not okc:
            n_fail += 1

    expect_gate = scenario.get("expect_gate", "pass")
    gate_pass = n_fail == 0
    print("== %s kapı=%s beklenen=%s ==" % (
        scenario.get("scenario", "?"), "GEÇTİ" if gate_pass else "ELEDİ", expect_gate))
    if expect_gate == "pass":
        return 0 if gate_pass else 1
    else:  # beklenen fail → en az bir kapı elemeli
        if gate_pass:
            print("  HATA: bu senaryo elemeliydi ama tüm kapılar geçti")
            return 1
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# selftest
# ─────────────────────────────────────────────────────────────────────────────
def _mk_conn(**over):
    pr = {
        "allowed_formats": FORMATS,
        "max_bytes": 25 * 1024 * 1024,
        "max_units": {"pages": 2000, "rows": 1_000_000, "chars": 5_000_000, "blocks": 100000, "paragraphs": 50000},
        "residency_region": "home",
        "allowed_regions": ["home"],
        "virtual_t0": 1_000_000,
    }
    pr.update(over)
    return IngestConnector(pr)


def _src(sid, fmt, **kw):
    d = {"source_id": sid, "format_declared": fmt, "tenant_id": "t-1", "kb_id": "kb-1"}
    d.update(kw)
    return d


def selftest():
    passed = 0
    failed = 0

    def expect(cond, msg):
        nonlocal passed, failed
        if cond:
            passed += 1
        else:
            failed += 1
            print("  ✗ %s" % msg)

    # 1) Her formatı gerçek fixture ile parse et (G1 — SR-KB-001 "her format parse+index").
    conn = _mk_conn()
    fmt_sources = [
        _src("s-pdf", "pdf", fixture="policy.pdf", filename="policy.pdf"),
        _src("s-pdf-flate", "pdf", fixture="policy-flate.pdf", filename="policy-flate.pdf"),
        _src("s-docx", "docx", fixture="policy.docx", filename="policy.docx"),
        _src("s-html", "html", fixture="page.html", filename="page.html"),
        _src("s-text", "text", fixture="policy.txt", filename="policy.txt"),
        _src("s-csv", "csv", fixture="faq.csv", filename="faq.csv"),
        _src("s-web", "web", body="<html><head><title>T</title></head><body><h1>Refund</h1>"
                                  "<p>14 days.</p></body></html>", url="https://ex.test/refund"),
    ]
    res = conn.run(fmt_sources)
    by = {r["source_id"]: r for r in res}
    for sid in [s["source_id"] for s in fmt_sources]:
        expect(by[sid]["status"] == "ingested", "%s ingested olmalı (%s)" % (sid, by[sid].get("error_class")))
    expect(by["s-pdf"]["status"] == "ingested" and "iade" in by["s-pdf"]["text"].lower(),
           "pdf metni 'iade' içermeli")
    expect("iade" in by["s-pdf-flate"]["text"].lower(), "flate pdf metni 'iade' içermeli")
    expect(by["s-pdf"]["unit_kind"] == "pages", "pdf unit_kind=pages")
    expect(any(b["type"] == "table_row" for b in by["s-docx"]["blocks"]), "docx tablo satırı ayıklanmalı")
    expect("ucretsiz" in by["s-docx"]["text"].lower() or "kargo" in by["s-docx"]["text"].lower(),
           "docx tablo içeriği metinde")
    expect("console" not in by["s-html"]["text"], "html script metni atılmalı")
    expect("Anasayfa" not in by["s-html"]["text"], "html nav boilerplate atılmalı")
    expect(by["s-html"]["title"] == "Iade ve Kargo Politikasi", "html title ayıklanmalı")
    expect(by["s-csv"]["unit_kind"] == "rows" and by["s-csv"]["unit_count"] == 3, "csv 3 satır")
    expect(any("yanit" in b["text"] for b in by["s-csv"]["blocks"]), "csv header ayıklanmalı")
    checks = evaluate_gates(fmt_sources, res, conn)
    gmap = {g: o for g, o, _ in checks}
    for gid in GATE_IDS:
        expect(gmap[gid], "happy: %s geçmeli" % gid)

    # 2) Dedup / idempotent re-ingest (G5): aynı içerik iki kez → ikincisi duplicate.
    conn2 = _mk_conn()
    dup_sources = [
        _src("d1", "text", inline_text="ayni icerik satiri\nikinci satir"),
        _src("d2", "text", inline_text="ayni icerik satiri\nikinci satir"),
    ]
    dres = conn2.run(dup_sources)
    expect(dres[0].get("duplicate_of") is None and dres[1].get("duplicate_of") == "d1",
           "ikinci aynı içerik duplicate_of=d1 olmalı")
    expect(dres[0]["content_hash"] == dres[1]["content_hash"], "aynı içerik aynı hash")
    expect(all(g for _, g, _ in evaluate_gates(dup_sources, dres, conn2)), "dedup senaryosu kapı geçer")

    # 3) Format mismatch / spoof reddi (G2): .txt beyanı ama içerik PDF.
    conn3 = _mk_conn()
    spoof = [_src("sp", "text", fixture="policy.pdf", filename="evil.txt",
                  expect={"status": "rejected", "error_class": "FORMAT_MISMATCH"})]
    r3 = conn3.run(spoof)
    expect(r3[0]["status"] == "rejected" and r3[0]["error_class"] == "FORMAT_MISMATCH",
           "txt-beyan/pdf-içerik FORMAT_MISMATCH olmalı")

    # 4) Oversize (G3 TOO_LARGE).
    conn4 = _mk_conn(max_bytes=64)
    big = [_src("big", "text", inline_text="x" * 500)]
    r4 = conn4.run(big)
    expect(r4[0]["status"] == "rejected" and r4[0]["error_class"] == "TOO_LARGE", "oversize TOO_LARGE")

    # 5) Birim sınırı (G3 TOO_MANY_UNITS) — csv satır cap.
    conn5 = _mk_conn(max_units={"rows": 2})
    csvbody = "a,b\n1,2\n3,4\n5,6\n7,8\n"
    r5 = conn5.run([_src("rows", "csv", inline_text=csvbody)])
    expect(r5[0]["status"] == "rejected" and r5[0]["error_class"] == "TOO_MANY_UNITS",
           "csv satır sınırı TOO_MANY_UNITS")

    # 6) Decompression bomb (G3) — docx bomba.
    conn6 = _mk_conn()
    r6 = conn6.run([_src("bomb", "docx", fixture="bomb.docx")])
    expect(r6[0]["status"] == "rejected" and r6[0]["error_class"] == "DECOMPRESSION_BOMB",
           "zip bomba DECOMPRESSION_BOMB")

    # 7) Corrupt pdf (G9 — never crash, structured error).
    conn7 = _mk_conn()
    r7 = conn7.run([_src("cor", "pdf", fixture="corrupt.pdf")])
    expect(r7[0]["status"] == "rejected" and r7[0]["error_class"] in ("CORRUPT", "NEEDS_OCR"),
           "bozuk pdf CORRUPT/NEEDS_OCR")

    # 8) Encrypted pdf (G3 ENCRYPTED).
    conn8 = _mk_conn()
    enc_pdf = b"%PDF-1.4\n/Encrypt 5 0 R\nstream\n(x) Tj\nendstream\n"
    r8 = conn8.run([_src("enc", "pdf", bytes_b64=base64.b64encode(enc_pdf).decode())])
    expect(r8[0]["status"] == "rejected" and r8[0]["error_class"] == "ENCRYPTED", "şifreli pdf ENCRYPTED")

    # 9) Missing tenant context (G6 fail-closed).
    conn9 = _mk_conn()
    nt = [{"source_id": "nt", "format_declared": "text", "inline_text": "x", "kb_id": "kb-1"}]
    r9 = conn9.run(nt)
    expect(r9[0]["status"] == "rejected" and r9[0]["error_class"] == "MISSING_TENANT_CONTEXT",
           "tenant'sız MISSING_TENANT_CONTEXT")

    # 10) Region violation (G8).
    conn10 = _mk_conn(allowed_regions=["home"])
    rv = [_src("rv", "text", inline_text="x", region="us-east")]
    r10 = conn10.run(rv)
    expect(r10[0]["status"] == "rejected" and r10[0]["error_class"] == "REGION_VIOLATION", "yabancı bölge REGION_VIOLATION")

    # 11) Unsupported format allowlist (G3).
    conn11 = _mk_conn(allowed_formats=["text", "csv"])
    r11 = conn11.run([_src("up", "pdf", fixture="policy.pdf")])
    expect(r11[0]["status"] == "rejected" and r11[0]["error_class"] == "UNSUPPORTED_FORMAT",
           "allowlist dışı format UNSUPPORTED_FORMAT")

    # 12) Empty (G3 EMPTY).
    conn12 = _mk_conn()
    r12 = conn12.run([_src("emp", "text", inline_text="   \n  \n")])
    expect(r12[0]["status"] == "rejected" and r12[0]["error_class"] == "EMPTY", "boş metin EMPTY")

    # 13) Cross-tenant isolation (G6): aynı içerik iki tenant → ayrı doc, sızıntı yok.
    conn13 = _mk_conn()
    ct = [
        _src("a", "text", inline_text="paylasilan icerik", tenant_id="t-1", kb_id="kb-1"),
        _src("b", "text", inline_text="paylasilan icerik", tenant_id="t-2", kb_id="kb-1"),
    ]
    r13 = conn13.run(ct)
    expect(r13[0]["tenant_id"] == "t-1" and r13[1]["tenant_id"] == "t-2", "her doc kendi tenant'ı")
    expect(r13[1].get("duplicate_of") is None, "farklı tenant aynı içerik DUP değil (izole namespace)")
    expect(all(g for _, g, _ in evaluate_gates(ct, r13, conn13)), "cross-tenant senaryo kapı geçer")

    # 14) Batch robustness (G9): kötü doc iyi doc'u durdurmaz.
    conn14 = _mk_conn()
    mix = [
        _src("ok1", "text", inline_text="gecerli metin"),
        _src("badf", "pdf", fixture="corrupt.pdf"),
        _src("ok2", "csv", inline_text="a,b\n1,2\n"),
    ]
    r14 = conn14.run(mix)
    expect(len(r14) == 3 and r14[0]["status"] == "ingested" and r14[2]["status"] == "ingested",
           "kötü doc batch'i durdurmamalı")

    # 15) NEEDS_OCR (görüntü-pdf: stream var, text-op yok).
    conn15 = _mk_conn()
    img_pdf = b"%PDF-1.4\n4 0 obj\nstream\n\x00\x01\x02binarynotext\x03\nendstream\nendobj\n"
    r15 = conn15.run([_src("ocr", "pdf", bytes_b64=base64.b64encode(img_pdf).decode())])
    expect(r15[0]["status"] == "rejected" and r15[0]["error_class"] in ("NEEDS_OCR", "CORRUPT"),
           "görüntü-pdf NEEDS_OCR/CORRUPT")

    # 16) Normalizasyon (G4): kontrol karakteri + CRLF temizliği.
    conn16 = _mk_conn()
    r16 = conn16.run([_src("nm", "text", inline_text="satir1\r\n\x07satir2\x00 son")])
    expect(r16[0]["status"] == "ingested" and not _CTRL_RE.search(r16[0]["text"]),
           "normalize: kontrol karakteri kalmamalı")
    expect("\r" not in r16[0]["text"], "CRLF→LF")

    # 17) Web SSRF/fetch hatası gövdesizken FETCH_ERROR (offline).
    conn17 = _mk_conn()
    r17 = conn17.run([{"source_id": "w", "format_declared": "web", "tenant_id": "t-1",
                       "kb_id": "kb-1", "url": "https://x.test"}])
    expect(r17[0]["status"] == "rejected" and r17[0]["error_class"] == "FETCH_ERROR",
           "gövdesiz web FETCH_ERROR (offline)")

    # 18) validate() temiz spec/config'te 0 döner.
    expect(validate() == 0, "validate() temiz repo'da 0 dönmeli")

    print("\nselftest: %d geçti, %d başarısız" % (passed, failed))
    if failed == 0:
        print("OK 🟢 selftest %d/%d" % (passed, passed))
    return 1 if failed else 0


# ─────────────────────────────────────────────────────────────────────────────
# schema
# ─────────────────────────────────────────────────────────────────────────────
def schema():
    print(__doc__)
    print("Beklenen spec anahtarları: wbs, phase, trace, placement, spi, gates, formats,")
    print("  error_taxonomy, residency, pii, invariants (G1–G10).")
    print("Sample/senaryo: {scenario, expect_gate(pass|fail), profile, virtual_t0?, sources[]}")
    print("source: {source_id, format_declared(pdf|docx|html|text|csv|web), tenant_id, kb_id,")
    print("  (inline_text | bytes_b64 | fixture | body+url), filename?, content_type?, region?,")
    print("  classification?, sensitive?, language_hint?, expect?{status,error_class,min_chars}}")
    print("NormalizedDocument çıktısı: doc_id, content_hash, text, blocks, format, detected_format,")
    print("  unit_count/unit_kind, char_count, byte_size, tenant_id, kb_id, classification,")
    print("  redaction_state=pending, no_log, residency_region, ingested_at(sanal saat), duplicate_of.")
    print("Hata sınıfları: %s" % ", ".join(sorted(ERROR_CLASSES)))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return validate()
    if cmd == "ingest":
        if len(sys.argv) < 3:
            print("kullanım: ingest_connector_probe.py ingest <sample.json>")
            return 2
        return ingest_cmd(sys.argv[2])
    if cmd == "selftest":
        return selftest()
    if cmd == "schema":
        return schema()
    print("bilinmeyen komut: %s (validate|ingest|selftest|schema)" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
