#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
docs-as-code: RMC markalı pandoc reference-doc'u (rmc-reference.docx) üretir.

Bu betik, pandoc'un varsayılan `reference.docx` şablonunu alır ve üzerine RMC
marka kimliğini işler:
  - Başlık (Heading 1/2/3, Title) renkleri → RMC mavi (theme accent1 + açık renk val)
  - Sayfa altı (footer): ortada "Sayfa X / Y" alanları
  - Sayfa üstü (header): solda şirket adı, sağda gizlilik etiketi + alt çizgi

Çıktı bir **şablon/stil** dosyasıdır; içerik kaynağı DEĞİLDİR. İçerik daima
`docs/*.md`'den gelir ve `build-docx.sh` ile bu şablon `--reference-doc` olarak
kullanılır.

Yalnız standart kütüphane kullanır (zipfile/subprocess); ek bağımlılık yok.

Kullanım:
    python3 docs/make_reference_docx.py [çıktı_yolu]
    # varsayılan çıktı: docs/assets/rmc-reference.docx

Marka değerleri **mühendislik varsayılanıdır**; RMC marka kılavuzu netleşince
aşağıdaki sabitleri güncelleyin ve yeniden üretin.
"""
import os
import re
import sys
import shutil
import zipfile
import subprocess
import tempfile
from xml.sax.saxutils import escape as _xesc

# --- Marka parametreleri (engineering default; brand guideline ile güncellenir) ---
BRAND_NAME = "RMC Technology & Consultancy"
BRAND_ACCENT = "1F4E79"        # RMC koyu mavi (theme accent1) — başlıklar
BRAND_ACCENT_DARK = "15406B"   # theme dk2 — daha koyu vurgular
CONFIDENTIALITY = "Gizli / Confidential"
FOOTER_PAGE_PREFIX = "Sayfa "  # "Sayfa X / Y"
DOC_LANG = "tr-TR"             # docDefaults proofing/yazım dili (Word'de)

DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(DOCS_DIR, "assets", "rmc-reference.docx")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# XML metnine gömülen serbest metinler kaçışlanır (ör. "&" → "&amp;").
_BRAND_NAME = _xesc(BRAND_NAME)
_CONFIDENTIALITY = _xesc(CONFIDENTIALITY)
_FOOTER_PAGE_PREFIX = _xesc(FOOTER_PAGE_PREFIX)

HEADER_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="{W_NS}" xmlns:r="{R_NS}">
  <w:p>
    <w:pPr>
      <w:tabs><w:tab w:val="right" w:pos="9026"/></w:tabs>
      <w:pBdr><w:bottom w:val="single" w:sz="6" w:space="4" w:color="{BRAND_ACCENT}"/></w:pBdr>
      <w:spacing w:after="120"/>
    </w:pPr>
    <w:r>
      <w:rPr><w:b/><w:color w:val="{BRAND_ACCENT}"/><w:sz w:val="18"/></w:rPr>
      <w:t xml:space="preserve">{_BRAND_NAME}</w:t>
    </w:r>
    <w:r><w:tab/></w:r>
    <w:r>
      <w:rPr><w:color w:val="808080"/><w:sz w:val="16"/></w:rPr>
      <w:t xml:space="preserve">{_CONFIDENTIALITY}</w:t>
    </w:r>
  </w:p>
</w:hdr>
"""

FOOTER_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W_NS}" xmlns:r="{R_NS}">
  <w:p>
    <w:pPr>
      <w:jc w:val="center"/>
      <w:pBdr><w:top w:val="single" w:sz="4" w:space="4" w:color="{BRAND_ACCENT}"/></w:pBdr>
    </w:pPr>
    <w:r><w:rPr><w:color w:val="808080"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve">{_FOOTER_PAGE_PREFIX}</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:rPr><w:color w:val="808080"/><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
    <w:r><w:rPr><w:color w:val="808080"/><w:sz w:val="16"/></w:rPr><w:t xml:space="preserve"> / </w:t></w:r>
    <w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:rPr><w:color w:val="808080"/><w:sz w:val="16"/></w:rPr><w:t>1</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r>
  </w:p>
</w:ftr>
"""

HEADER_REL_ID = "rIdRmcHeader"
FOOTER_REL_ID = "rIdRmcFooter"


def emit_default_reference(path):
    """pandoc varsayılan reference.docx'i `path`e yazar."""
    subprocess.run(
        ["pandoc", "-o", path, "--print-default-data-file", "reference.docx"],
        check=True,
    )


def patch_theme(theme_xml):
    """theme accent1 + dk2 → RMC mavi."""
    theme_xml = re.sub(
        r"(<a:accent1><a:srgbClr val=\")[0-9A-Fa-f]{6}(\" ?/></a:accent1>)",
        r"\g<1>" + BRAND_ACCENT + r"\g<2>",
        theme_xml,
    )
    theme_xml = re.sub(
        r"(<a:dk2><a:srgbClr val=\")[0-9A-Fa-f]{6}(\" ?/></a:dk2>)",
        r"\g<1>" + BRAND_ACCENT_DARK + r"\g<2>",
        theme_xml,
    )
    return theme_xml


def patch_styles(styles_xml):
    """Heading 1/2/3 + Title renk val'lerini RMC mavisine sabitler + yazım dilini ayarlar."""
    # themeColor referansları kalsın; ayrıca açık val'i de RMC mavisine çek.
    styles_xml = re.sub(
        r'(<w:color w:val=")[0-9A-Fa-f]{6}("[^/]*themeColor="accent1"[^/]*/>)',
        r"\g<1>" + BRAND_ACCENT + r"\g<2>",
        styles_xml,
    )
    # docDefaults proofing/yazım dili → tr-TR (pandoc'un --metadata lang'ine gerek
    # kalmaz; böylece pandoc 3.x'in bozuk tr.yaml çevirisi tetiklenmez).
    styles_xml = re.sub(
        r'<w:lang w:val="[^"]*"',
        f'<w:lang w:val="{DOC_LANG}"',
        styles_xml,
        count=1,
    )
    return styles_xml


def patch_document(document_xml):
    """Boş <w:sectPr /> içine header/footer referanslarını ekler."""
    refs = (
        f'<w:sectPr>'
        f'<w:headerReference w:type="default" r:id="{HEADER_REL_ID}"/>'
        f'<w:footerReference w:type="default" r:id="{FOOTER_REL_ID}"/>'
        f'</w:sectPr>'
    )
    if "<w:sectPr />" in document_xml:
        return document_xml.replace("<w:sectPr />", refs, 1)
    if "<w:sectPr/>" in document_xml:
        return document_xml.replace("<w:sectPr/>", refs, 1)
    # Zaten dolu bir sectPr varsa, referansları başına ekle.
    return re.sub(r"<w:sectPr(\s[^>]*)?>",
                  lambda m: m.group(0)
                  + f'<w:headerReference w:type="default" r:id="{HEADER_REL_ID}"/>'
                  + f'<w:footerReference w:type="default" r:id="{FOOTER_REL_ID}"/>',
                  document_xml, count=1)


def patch_rels(rels_xml):
    add = (
        f'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
        f'Id="{HEADER_REL_ID}" Target="header1.xml" />'
        f'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
        f'Id="{FOOTER_REL_ID}" Target="footer1.xml" />'
    )
    return rels_xml.replace("</Relationships>", add + "</Relationships>")


def patch_content_types(ct_xml):
    add = (
        '<Override PartName="/word/header1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml" />'
        '<Override PartName="/word/footer1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml" />'
    )
    return ct_xml.replace("</Types>", add + "</Types>")


def build(out_path):
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="rmc-ref-")
    try:
        base = os.path.join(tmpdir, "reference.docx")
        emit_default_reference(base)

        zin = zipfile.ZipFile(base, "r")
        parts = {n: zin.read(n) for n in zin.namelist()}
        zin.close()

        def txt(name):
            return parts[name].decode("utf-8")

        parts["word/theme/theme1.xml"] = patch_theme(txt("word/theme/theme1.xml")).encode("utf-8")
        parts["word/styles.xml"] = patch_styles(txt("word/styles.xml")).encode("utf-8")
        parts["word/document.xml"] = patch_document(txt("word/document.xml")).encode("utf-8")
        parts["word/_rels/document.xml.rels"] = patch_rels(txt("word/_rels/document.xml.rels")).encode("utf-8")
        parts["[Content_Types].xml"] = patch_content_types(txt("[Content_Types].xml")).encode("utf-8")
        parts["word/header1.xml"] = HEADER_XML.encode("utf-8")
        parts["word/footer1.xml"] = FOOTER_XML.encode("utf-8")

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            # [Content_Types].xml ilk sırada olsun (OOXML konvansiyonu).
            ordered = ["[Content_Types].xml"] + [n for n in parts if n != "[Content_Types].xml"]
            for name in ordered:
                zout.writestr(name, parts[name])
        return out_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    if not shutil.which("pandoc"):
        sys.stderr.write("HATA: pandoc kurulu değil. https://pandoc.org/installing.html\n")
        return 1
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    path = build(out)
    print(f"Üretildi: {path}")
    print(f"  marka rengi (accent1): #{BRAND_ACCENT} · footer: sayfa no · header: {BRAND_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
