#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_gen_fixtures.py — WBS 6.1.1 ingest connector test fixture üreteci (stdlib-only, credential-free).

PDF (uncompressed + FlateDecode) ve DOCX (zip+OOXML) GERÇEK ikili dosyalarını üretir — böylece
"her format başarıyla parse+index edilir" (SR-KB-001) gerçek dosyalarla kanıtlanır. text/csv/html/web
sample içinde satır-içi (inline_text) tutulur; PDF/DOCX ikili olduğundan burada üretilir. Üretilen
fixtures repoya commit edilir; bu üreteç yalnızca yeniden üretim/denetim içindir.

İçerik sentetik (FR-TST-008 — gerçek müşteri verisi / PII / sır YOK). Çalıştır: `python3 _gen_fixtures.py`.
"""
import os
import struct
import zlib
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Sentetik içerik (PII/sır yok). PDF ve DOCX aynı kanonik metni taşır → dedup/normalizasyon testi.
PDF_LINES = [
    "Chanteur KB ingest connector test belgesi.",
    "Bu satir PDF ayikicinin Tj operatorunu denemesi icindir.",
    "Iade politikasi: 14 gun icinde kosulsuz iade kabul edilir.",
]
DOCX_PARAS = [
    "Chanteur KB ingest connector test belgesi.",
    "Word/OOXML ayiklayici paragraf ve tablo metnini cikartmalidir.",
    "Iade politikasi: 14 gun icinde kosulsuz iade kabul edilir.",
]
DOCX_TABLE = [["Soru", "Yanit"], ["Iade suresi", "14 gun"], ["Kargo", "Ucretsiz"]]


def _pdf(lines, compress):
    """Minimal ama yapisal olarak gecerli tek-sayfa PDF. Ofsetler programatik hesaplanir."""
    # Icerik akisi: her satir ayri BT/Tj/ET.
    content_parts = []
    y = 720
    for ln in lines:
        esc = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_parts.append("BT /F1 12 Tf 72 %d Td (%s) Tj ET" % (y, esc))
        y -= 18
    content = ("\n".join(content_parts) + "\n").encode("latin-1")
    if compress:
        stream_bytes = zlib.compress(content)
        stream_dict = "<< /Length %d /Filter /FlateDecode >>" % len(stream_bytes)
    else:
        stream_bytes = content
        stream_dict = "<< /Length %d >>" % len(stream_bytes)

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    objects.append(stream_dict.encode("latin-1") + b"\nstream\n" + stream_bytes + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % i).encode("latin-1") + body + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objects) + 1
    out += ("xref\n0 %d\n" % n).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode("latin-1")
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (n, xref_pos)).encode("latin-1")
    return bytes(out)


def _docx(paras, table):
    """Minimal gecerli .docx (zip + [Content_Types].xml + _rels/.rels + word/document.xml)."""
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = []
    for p in paras:
        body.append("<w:p><w:r><w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>" % esc(p))
    rows = []
    for row in table:
        cells = "".join(
            "<w:tc><w:p><w:r><w:t xml:space=\"preserve\">%s</w:t></w:r></w:p></w:tc>" % esc(c)
            for c in row
        )
        rows.append("<w:tr>%s</w:tr>" % cells)
    body.append("<w:tbl>%s</w:tbl>" % "".join(rows))
    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>%s</w:body></w:document>" % "".join(body)
    )
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )
    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" "
        "Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/></Relationships>"
    )
    path = os.path.join(HERE, "policy.docx")
    # Sabit zip (deterministik): ZIP_DEFLATED, sabit tarih.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("word/document.xml", document_xml),
        ]:
            zi = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    return path


def _zip_bomb_docx():
    """Sikistirma-orani yuksek sahte docx (decompression-bomb guard testi). Tek dev sifir blogu."""
    path = os.path.join(HERE, "bomb.docx")
    payload = b"\x00" * (4 * 1024 * 1024)  # 4 MiB sifir → ~KB sikistirilir
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("word/document.xml", date_time=(2026, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(zi, payload)
    return path


def main():
    pdf_plain = _pdf(PDF_LINES, compress=False)
    with open(os.path.join(HERE, "policy.pdf"), "wb") as f:
        f.write(pdf_plain)
    pdf_flate = _pdf(PDF_LINES, compress=True)
    with open(os.path.join(HERE, "policy-flate.pdf"), "wb") as f:
        f.write(pdf_flate)
    _docx(DOCX_PARAS, DOCX_TABLE)
    _zip_bomb_docx()
    # Bozuk PDF (CORRUPT taksonomi testi): basligi var, govde cop.
    with open(os.path.join(HERE, "corrupt.pdf"), "wb") as f:
        f.write(b"%PDF-1.4\nbu gecerli bir pdf govdesi degildir, hicbir stream yok\n")
    print("OK: policy.pdf policy-flate.pdf policy.docx bomb.docx corrupt.pdf uretildi")


if __name__ == "__main__":
    main()
