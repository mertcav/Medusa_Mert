# docs/assets

## rmc-reference.docx (branded template)

`build-docx.sh`, `.docx` üretirken bu klasördeki **`rmc-reference.docx`** dosyasını
pandoc `--reference-doc` olarak kullanır. Bu dosya RMC marka stilini taşır:
RMC mavi başlıklar (theme accent1 `#1F4E79`), header (şirket adı + gizlilik etiketi),
footer (sayfa numarası: "Sayfa X / Y"), tablo/stil tanımları ve yazım dili (tr-TR).

### Nasıl hazırlanır
İki yol vardır:

1. **Otomatik üret (varsayılan).** Repo kökünden:
   ```bash
   python3 docs/make_reference_docx.py          # -> docs/assets/rmc-reference.docx
   ```
   Bu betik pandoc'un varsayılan `reference.docx`'ini alır, üzerine RMC marka
   kimliğini (renk + header/footer + dil) işler. `build-docx.sh` de dosya yoksa
   bunu otomatik çağırır; her seferinde yeniden üretmek için:
   ```bash
   ./docs/build-docx.sh --regen-ref
   ```
   Marka değerleri (`BRAND_NAME`, `BRAND_ACCENT`, `CONFIDENTIALITY`, `DOC_LANG`)
   betiğin başındaki sabitlerde tutulur; **mühendislik varsayılanıdır** ve RMC
   marka kılavuzu netleşince güncellenip yeniden üretilir.

2. **RMC'nin sağladığı şablonu kullan.** RMC markalı `.docx` şablonu varsa bu
   klasöre `rmc-reference.docx` adıyla koyun. İçeriği silin; yalnız **stil
   tanımları**, header ve footer kalsın (içerik build sırasında `.md`'den gelir).
   Bu durumda `--regen-ref` ile üzerine yazmayın.

### Notlar
- Bu `.docx` bir **şablon/stil** dosyasıdır, içerik kaynağı değildir. İçerik daima `docs/*.md`'dir.
- Dosya yoksa build önce otomatik üretmeyi dener; pandoc yoksa markasız (default) çıktı verir ve uyarır.
- `docs/dist/` üretilen artifact klasörüdür (`.gitignore`'da); sürüm kontrolüne girmez.
