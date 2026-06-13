#!/usr/bin/env bash
# docs-as-code: Markdown kaynaktan (.md) markalı .docx artifact üretir.
# Kaynak (source of truth): docs/*.md  ·  Çıktı (artifact): docs/dist/*.docx
#
# Kullanım:
#   ./docs/build-docx.sh            # tüm dokümanları üret (BRD + SAD)
#   ./docs/build-docx.sh BRD        # yalnız BRD.md -> dist/BRD.docx
#
# Markalı çıktı için RMC reference-doc'u şuraya koyun:
#   docs/assets/rmc-reference.docx   (RMC mavi tema, header/footer, stiller)
# Yoksa pandoc varsayılan stiliyle (markasız) üretir ve uyarı verir.

set -euo pipefail

DOCS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${DOCS_DIR}/dist"
REF_DOC="${DOCS_DIR}/assets/rmc-reference.docx"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "HATA: pandoc kurulu değil. Kurulum: https://pandoc.org/installing.html" >&2
  echo "  Debian/Ubuntu: sudo apt-get install -y pandoc" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

REF_ARGS=()
if [[ -f "${REF_DOC}" ]]; then
  REF_ARGS=(--reference-doc="${REF_DOC}")
  echo "Branded template kullanılıyor: ${REF_DOC}"
else
  echo "UYARI: ${REF_DOC} bulunamadı — markasız (default) stille üretiliyor."
  echo "       RMC şablonunu bu yola koyup tekrar çalıştırın."
fi

# Üretilecek dokümanlar (argüman verilirse yalnız o)
TARGETS=("BRD" "SAD")
if [[ $# -gt 0 ]]; then TARGETS=("$@"); fi

for name in "${TARGETS[@]}"; do
  src="${DOCS_DIR}/${name}.md"
  out="${OUT_DIR}/${name}.docx"
  if [[ ! -f "${src}" ]]; then
    echo "ATLANDI: ${src} yok." >&2
    continue
  fi
  pandoc "${src}" \
    --from=gfm \
    --to=docx \
    "${REF_ARGS[@]}" \
    --toc --toc-depth=3 \
    --number-sections=false \
    --output="${out}"
  echo "Üretildi: ${out}"
done
