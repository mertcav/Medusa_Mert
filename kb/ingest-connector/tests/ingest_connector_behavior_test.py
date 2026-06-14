#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_connector_behavior_test.py — WBS 6.1.1 davranış kapısı (T1–T10).

Bağımlılıksız (stdlib-only). Probe'un IngestConnector + ayıklayıcılarını gerçek fixture'larla
sürer ve FR-KB-001 / G1–G10 davranışlarını assert eder. selftest'i tamamlar; CI'da koşar.
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ingest_connector_probe as P  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print("  ✗ %s" % msg)


def conn(**o):
    return P._mk_conn(**o)


def src(sid, fmt, **kw):
    return P._src(sid, fmt, **kw)


# T1 — FR-KB-001: 6 formatın hepsi gerçek kaynaktan parse edilir (SR-KB-001).
def t1_format_coverage():
    c = conn()
    sources = [
        src("p", "pdf", fixture="policy.pdf"),
        src("d", "docx", fixture="policy.docx"),
        src("h", "html", fixture="page.html"),
        src("t", "text", fixture="policy.txt"),
        src("c", "csv", fixture="faq.csv"),
        src("w", "web", url="https://x.test", body="<html><body><p>hello world ingest</p></body></html>"),
    ]
    res = c.run(sources)
    check(all(r["status"] == "ingested" for r in res), "T1: 6 format da ingested")
    check(all(r["char_count"] > 0 for r in res), "T1: hepsi boş-olmayan metin")
    fmts = {r["format"] for r in res}
    check(fmts == {"pdf", "docx", "html", "text", "csv", "web"}, "T1: 6 format kapsanır")


# T2 — PDF: hem uncompressed hem FlateDecode text ayıklanır.
def t2_pdf_variants():
    c = conn()
    res = c.run([src("a", "pdf", fixture="policy.pdf"), src("b", "pdf", fixture="policy-flate.pdf")])
    check(all(r["status"] == "ingested" for r in res), "T2: iki pdf de ingested")
    check("iade" in res[0]["text"].lower() and "iade" in res[1]["text"].lower(),
          "T2: pdf metni içerik taşır")
    check(res[0]["content_hash"] == res[1]["content_hash"], "T2: aynı içerik → aynı hash (dedup)")


# T3 — DOCX: paragraf + tablo ayıklanır.
def t3_docx_table():
    c = conn()
    r = c.run([src("d", "docx", fixture="policy.docx")])[0]
    check(r["status"] == "ingested", "T3: docx ingested")
    check(any(b["type"] == "table_row" for b in r["blocks"]), "T3: tablo satırı ayıklanır")
    check(r["unit_kind"] == "paragraphs", "T3: unit_kind=paragraphs")


# T4 — HTML: script/style/nav boilerplate atılır, title alınır.
def t4_html_boilerplate():
    c = conn()
    r = c.run([src("h", "html", fixture="page.html")])[0]
    check("console" not in r["text"] and "Anasayfa" not in r["text"], "T4: script+nav atılır")
    check(r["title"] == "Iade ve Kargo Politikasi", "T4: title ayıklanır")
    check(any(b["type"] == "heading" for b in r["blocks"]), "T4: heading yapısı korunur")


# T5 — CSV: header + satır yapısı korunur.
def t5_csv_structure():
    c = conn()
    r = c.run([src("c", "csv", inline_text="soru,yanit\n\"a?\",\"b\"\n\"c?\",\"d\"\n")])[0]
    check(r["status"] == "ingested" and r["unit_count"] == 2, "T5: 2 veri satırı")
    check(any(b["type"] == "table_header" for b in r["blocks"]), "T5: header ayıklanır")


# T6 — G2 content-sniffing: spoof tipi reddedilir.
def t6_spoof():
    c = conn()
    r = c.run([src("s", "text", fixture="policy.pdf", filename="x.txt")])[0]
    check(r["status"] == "rejected" and r["error_class"] == "FORMAT_MISMATCH", "T6: spoof FORMAT_MISMATCH")
    r2 = c.run([src("z", "docx", bytes_b64=base64.b64encode(b"PK\x03\x04not-a-docx").decode())])[0]
    check(r2["status"] == "rejected", "T6: zip-non-docx reddedilir")


# T7 — G3 validation guard'ları.
def t7_validation():
    check(conn(max_bytes=16).run([src("b", "text", inline_text="x" * 100)])[0]["error_class"] == "TOO_LARGE",
          "T7: TOO_LARGE")
    check(conn(max_units={"rows": 1}).run([src("r", "csv", inline_text="a,b\n1,2\n3,4\n")])[0]["error_class"]
          == "TOO_MANY_UNITS", "T7: TOO_MANY_UNITS")
    check(conn().run([src("bm", "docx", fixture="bomb.docx")])[0]["error_class"] == "DECOMPRESSION_BOMB",
          "T7: DECOMPRESSION_BOMB")
    enc = b"%PDF-1.4\n/Encrypt 1 0 R\nstream\n(x) Tj\nendstream\n"
    check(conn().run([src("e", "pdf", bytes_b64=base64.b64encode(enc).decode())])[0]["error_class"]
          == "ENCRYPTED", "T7: ENCRYPTED")


# T8 — G5 dedup + idempotent re-ingest.
def t8_dedup():
    c = conn()
    res = c.run([src("a", "text", inline_text="ayni metin"), src("b", "text", inline_text="ayni metin")])
    check(res[0].get("duplicate_of") is None and res[1].get("duplicate_of") == "a", "T8: ikinci DUP")


# T9 — G6 tenant izolasyonu + fail-closed.
def t9_tenant():
    c = conn()
    res = c.run([
        src("a", "text", inline_text="ortak", tenant_id="t-1", kb_id="k"),
        src("b", "text", inline_text="ortak", tenant_id="t-2", kb_id="k"),
    ])
    check(res[1].get("duplicate_of") is None, "T9: farklı tenant aynı içerik DUP değil")
    nt = c.run([{"source_id": "n", "format_declared": "text", "inline_text": "x", "kb_id": "k"}])[0]
    check(nt["error_class"] == "MISSING_TENANT_CONTEXT", "T9: tenant'sız fail-closed")


# T10 — G8/G9: residency + no_log + redaction pending + batch never-crash.
def t10_residency_robust():
    c = conn(allowed_regions=["home"])
    r = c.run([src("a", "text", inline_text="metin")])[0]
    check(r["no_log"] and r["redaction_state"] == "pending" and r["residency_region"] == "home",
          "T10: no_log+redaction+region")
    rv = c.run([src("v", "text", inline_text="x", region="us")])[0]
    check(rv["error_class"] == "REGION_VIOLATION", "T10: yabancı bölge reddi")
    mix = c.run([src("ok", "text", inline_text="iyi"), src("bad", "pdf", fixture="corrupt.pdf"),
                 src("ok2", "csv", inline_text="a,b\n1,2\n")])
    check(len(mix) == 3 and mix[0]["status"] == "ingested" and mix[2]["status"] == "ingested",
          "T10: kötü doc batch'i durdurmaz")


def main():
    for fn in (t1_format_coverage, t2_pdf_variants, t3_docx_table, t4_html_boilerplate,
               t5_csv_structure, t6_spoof, t7_validation, t8_dedup, t9_tenant, t10_residency_robust):
        fn()
    print("behavior: %d geçti, %d başarısız" % (_passed, _failed))
    if _failed == 0:
        print("OK 🟢 behavior %d/%d" % (_passed, _passed))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
