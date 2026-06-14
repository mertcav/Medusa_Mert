# 6.1.2 fixtures

Bu dizin kasıtlı olarak **çoğunlukla boştur**: 6.1.2 ayıklamayı **6.1.1 FormatExtractor'a devreder**
(S5), bu yüzden ikili (docx/pdf) fixture'lar **yeniden üretilmez** — `source_connector_probe.py`'deki
`_read_item_bytes()` önce bu dizine, sonra **6.1.1'in `kb/ingest-connector/samples/fixtures/`** dizinine
(ör. `policy.docx`) düşer. Metin-tabanlı içerik (html/text/csv) snapshot'larda `inline_text` ile
gömülüdür (sentetik — FR-TST-008).

6.1.2'ye özgü bir ikili fixture gerekirse buraya eklenir ve `{"fixture": "<ad>"}` ile referanslanır.
