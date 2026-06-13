# docs/assets

## rmc-reference.docx (branded template)

`build-docx.sh`, `.docx` üretirken bu klasördeki **`rmc-reference.docx`** dosyasını
pandoc `--reference-doc` olarak kullanır. Bu dosya RMC marka stilini taşır:
RMC mavi başlıklar, kurumsal font, header/footer (logo + sayfa no), tablo stilleri.

### Nasıl hazırlanır
1. RMC'nin sağladığı markalı `.docx` şablonunu bu klasöre `rmc-reference.docx` adıyla koyun;
   **veya** pandoc'un varsayılan referansını alıp markalayın:
   ```bash
   pandoc -o docs/assets/rmc-reference.docx --print-default-data-file reference.docx
   ```
   Sonra Word'de açıp stilleri (Heading 1/2/3, Normal, Table) RMC temasına göre düzenleyin.
2. İçeriği silin; yalnız **stil tanımları**, header ve footer kalsın (içerik build sırasında gelir).

### Notlar
- Bu `.docx` bir **şablon/stil** dosyasıdır, içerik kaynağı değildir. İçerik daima `docs/*.md`'dir.
- Dosya yoksa build markasız (pandoc default) çıktı üretir ve uyarı verir.
- `docs/dist/` üretilen artifact klasörüdür; sürüm kontrolüne girmesi zorunlu değildir.
