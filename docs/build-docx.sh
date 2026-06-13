#!/usr/bin/env bash
# docs-as-code: Markdown kaynaktan (.md) markalı .docx artifact üretir.
# Kaynak (source of truth): docs/*.md  ·  Çıktı (artifact): docs/dist/*.docx
#
# Kullanım:
#   ./docs/build-docx.sh                 # tüm dokümanları üret (otomatik keşif)
#   ./docs/build-docx.sh BRD             # yalnız BRD.md -> dist/BRD.docx
#   ./docs/build-docx.sh BRD SAD API     # birden çok doküman
#   ./docs/build-docx.sh all             # tüm dokümanlar (varsayılanla aynı)
#   ./docs/build-docx.sh list            # üretilebilir doküman adlarını listele
#
# Bayraklar:
#   --regen-ref   Markalı reference-doc'u (her durumda) yeniden üret.
#   --no-toc      İçindekiler tablosu ekleme.
#
# Markalı çıktı için RMC reference-doc'u şuraya konur:
#   docs/assets/rmc-reference.docx   (RMC mavi tema, header/footer, stiller)
# Yoksa, make_reference_docx.py ile otomatik üretilir (pandoc varsa).

set -euo pipefail

DOCS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${DOCS_DIR}/dist"
REF_DOC="${DOCS_DIR}/assets/rmc-reference.docx"
REF_GEN="${DOCS_DIR}/make_reference_docx.py"

# todo_list.md kaynak doküman değildir (yaşayan WBS); artifact üretilmez.
EXCLUDE=("todo_list")

REGEN_REF=0
WITH_TOC=1
ARGS=()
for a in "$@"; do
  case "$a" in
    --regen-ref) REGEN_REF=1 ;;
    --no-toc)    WITH_TOC=0 ;;
    *)           ARGS+=("$a") ;;
  esac
done

# --- pandoc kontrolü ---
if ! command -v pandoc >/dev/null 2>&1; then
  echo "HATA: pandoc kurulu değil. Kurulum: https://pandoc.org/installing.html" >&2
  echo "  Debian/Ubuntu: sudo apt-get install -y pandoc" >&2
  exit 1
fi
echo "pandoc: $(pandoc --version | head -1)"

# --- Üretilebilir doküman adlarını keşfet (docs/*.md eksi EXCLUDE) ---
discover() {
  local f base skip e
  for f in "${DOCS_DIR}"/*.md; do
    [[ -e "$f" ]] || continue
    base="$(basename "$f" .md)"
    skip=0
    for e in "${EXCLUDE[@]}"; do [[ "$base" == "$e" ]] && skip=1; done
    [[ "$skip" -eq 0 ]] && echo "$base"
  done
}

# `list` alt komutu
if [[ "${#ARGS[@]}" -gt 0 && "${ARGS[0]}" == "list" ]]; then
  echo "Üretilebilir dokümanlar:"
  discover | sed 's/^/  - /'
  exit 0
fi

# Hedef seti: argüman yoksa veya 'all' ise tümü; aksi halde verilenler.
if [[ "${#ARGS[@]}" -eq 0 || ( "${#ARGS[@]}" -eq 1 && "${ARGS[0]}" == "all" ) ]]; then
  mapfile -t TARGETS < <(discover)
else
  TARGETS=("${ARGS[@]}")
fi

mkdir -p "${OUT_DIR}"

# --- Markalı reference-doc'u hazırla (yoksa veya --regen-ref ile üret) ---
REF_ARGS=()
if [[ "${REGEN_REF}" -eq 1 || ! -f "${REF_DOC}" ]]; then
  if [[ -f "${REF_GEN}" ]]; then
    echo "Reference-doc üretiliyor: ${REF_GEN}"
    python3 "${REF_GEN}" "${REF_DOC}"
  fi
fi
if [[ -f "${REF_DOC}" ]]; then
  REF_ARGS=(--reference-doc="${REF_DOC}")
  echo "Branded template kullanılıyor: ${REF_DOC}"
else
  echo "UYARI: ${REF_DOC} bulunamadı — markasız (default) stille üretiliyor." >&2
fi

# --- TOC argümanları ---
TOC_ARGS=()
if [[ "${WITH_TOC}" -eq 1 ]]; then
  TOC_ARGS=(--toc --toc-depth=3)
fi

# --- Üretim döngüsü ---
ok=0; skipped=0; failed=0
for name in "${TARGETS[@]}"; do
  name="${name%.md}"   # ".md" uzantısı verilirse temizle
  src="${DOCS_DIR}/${name}.md"
  out="${OUT_DIR}/${name}.docx"
  if [[ ! -f "${src}" ]]; then
    echo "ATLANDI: ${src} yok." >&2
    skipped=$((skipped+1))
    continue
  fi
  if pandoc "${src}" \
      --from=gfm \
      --to=docx \
      "${REF_ARGS[@]}" \
      "${TOC_ARGS[@]}" \
      --output="${out}"; then
    echo "Üretildi: ${out} ($(du -h "${out}" | cut -f1))"
    ok=$((ok+1))
  else
    echo "HATA: ${src} üretilemedi." >&2
    failed=$((failed+1))
  fi
done

echo "----"
echo "Özet: ${ok} üretildi, ${skipped} atlandı, ${failed} hata. Çıktı: ${OUT_DIR}"
[[ "${failed}" -eq 0 ]]
