#!/usr/bin/env python3
"""ADR indeks üreteci — docs/adr/*.md frontmatter'larından ADR indeks tablolarını türetir.

Kaynak doğruluk her ADR'nin kendi `.md` dosyasıdır; bu betik yalnız **özet indeksleri**
(README.md ve SAD.md §22) işaretçiler arasında yeniden üretir. stdlib-only.

Kullanım (repo kökünden):
    python3 docs/adr/gen_adr_index.py            # indeksleri yaz (README + SAD §22)
    python3 docs/adr/gen_adr_index.py --check    # güncel mi? (yazmaz; tutarsızsa exit 1)
    python3 docs/adr/gen_adr_index.py --next     # bir sonraki boş ADR-NNNN
    python3 docs/adr/gen_adr_index.py --list     # ADR-ID · durum · başlık
"""
import os
import re
import sys

ADR_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(ADR_DIR))
README = os.path.join(ADR_DIR, "README.md")
SAD = os.path.join(REPO_ROOT, "docs", "SAD.md")

BEGIN = "<!-- ADR-INDEX:BEGIN"
END = "<!-- ADR-INDEX:END -->"
FNAME_RE = re.compile(r"^(\d{4})-.+\.md$")

# Durum → sıralama/ikon (sadece görsel; metin frontmatter'dan gelir)
STATUS_ICON = {
    "Kabul": "🟢",
    "Önerilen": "🟡",
    "Açık": "🟠",
    "Reddedildi": "⚪",
    "Kullanımdan kaldırıldı": "⚫",
}


def parse_frontmatter(path):
    """İlk '---' ... '---' bloğunu basit key: value sözlüğüne çevirir."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta = {}
    for line in parts[1].splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_-]+):\s?(.*)$", line)
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()
    return meta


def load_adrs():
    adrs = []
    for fname in sorted(os.listdir(ADR_DIR)):
        m = FNAME_RE.match(fname)
        if not m or m.group(1) == "0000":
            continue  # 0000-template.md ADR değildir
        meta = parse_frontmatter(os.path.join(ADR_DIR, fname))
        if not meta or "adr" not in meta:
            print(f"UYARI: {fname} frontmatter/adr eksik, atlanıyor", file=sys.stderr)
            continue
        meta["_file"] = fname
        meta["_num"] = int(m.group(1))
        adrs.append(meta)
    adrs.sort(key=lambda a: a["_num"])
    return adrs


def status_cell(meta):
    status = meta.get("status", "?")
    icon = STATUS_ICON.get(status, "")
    sb = meta.get("superseded-by", "").strip()
    cell = f"{icon} {status}".strip()
    if sb:
        cell += f" → {sb}"
    return cell


def build_table(adrs, link_prefix):
    rows = [
        "| ADR | Karar | Durum | İz |",
        "|-----|-------|-------|-----|",
    ]
    for a in adrs:
        title = a.get("title", "").strip()
        link = f"[{a['adr']}]({link_prefix}{a['_file']})"
        iz = a.get("iz", "").strip()
        rows.append(f"| {link} | {title} | {status_cell(a)} | {iz} |")
    return "\n".join(rows)


def splice(path, body):
    """İşaretçiler arası içeriği değiştirir; değişti mi döner."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    bi = text.find(BEGIN)
    ei = text.find(END)
    if bi == -1 or ei == -1 or ei < bi:
        raise SystemExit(f"HATA: {path} içinde ADR-INDEX işaretçileri bulunamadı")
    line_end = text.find("\n", bi)
    head = text[: line_end + 1]
    tail = text[ei:]
    new = head + "\n" + body + "\n\n" + tail
    if new == text:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def render(adrs):
    note = (
        "_Bu tablo `docs/adr/gen_adr_index.py` ile türetilir — elle düzenlemeyin. "
        "Her kaydın tam metni ilgili `docs/adr/*.md` dosyasındadır._"
    )
    readme_body = note + "\n\n" + build_table(adrs, link_prefix="")
    sad_body = note + "\n\n" + build_table(adrs, link_prefix="adr/")
    return readme_body, sad_body


def main():
    args = sys.argv[1:]
    adrs = load_adrs()

    if "--next" in args:
        nxt = (max((a["_num"] for a in adrs), default=0)) + 1
        print(f"ADR-{nxt:04d}")
        return

    if "--list" in args:
        for a in adrs:
            print(f"{a['adr']}  {a.get('status','?'):24} {a.get('title','')}")
        return

    readme_body, sad_body = render(adrs)
    targets = [(README, readme_body), (SAD, sad_body)]

    if "--check" in args:
        stale = []
        for path, body in targets:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            bi, ei = text.find(BEGIN), text.find(END)
            if bi == -1 or ei == -1:
                stale.append(path)
                continue
            current = text[text.find("\n", bi) + 1 : ei].strip()
            if current != ("\n" + body + "\n\n").strip():
                stale.append(path)
        if stale:
            print("GÜNCEL DEĞİL: " + ", ".join(os.path.relpath(p, REPO_ROOT) for p in stale))
            print("Çözüm: python3 docs/adr/gen_adr_index.py", file=sys.stderr)
            sys.exit(1)
        print(f"OK: {len(adrs)} ADR; indeksler güncel.")
        return

    changed = []
    for path, body in targets:
        if splice(path, body):
            changed.append(os.path.relpath(path, REPO_ROOT))
    print(f"{len(adrs)} ADR işlendi. Güncellenen: {', '.join(changed) or '(değişiklik yok)'}")


if __name__ == "__main__":
    main()
