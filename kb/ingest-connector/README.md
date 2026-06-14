# WBS 6.1.1 — Ingest connector: PDF/Word/HTML/metin/CSV/web

`F1` · `Must` · →FR-KB-001 · SR-KB-001 · SAD §10.1 · ADR-001/002

Bilgi Tabanı & RAG **offline indeksleme** hattının (SAD §10.1) ilk aşaması: **ingest connector**.
Doküman (PDF/Word/HTML/CSV/web/metin) → **[ingest connector]** → parse & normalize →
`NormalizedDocument`. Çıktıyı **6.1.3** (chunk→embed→index+versiyonlama) tüketir.

```
Doküman (PDF/Word/HTML/CSV/web/metin)
   │ SourceConnector (upload / web fetch [SSRF-guard])
   ▼
Format algıla + beyanla uzlaştır (content-sniffing yetkili — spoof reddi)
   ▼
Doğrula (allowlist/boyut/birim/charset/decompression-bomb)
   ▼
FormatExtractor[format].extract()  →  Parse & normalize (NFC, boilerplate, yapı)
   ▼
NormalizedDocument {text, blocks, metadata, content_hash, tenant/kb namespace, acl/redaction kancası}
   │  (6.1.3 chunk→embed→index+versiyonlama)
```

## Dosyalar
| Dosya | Rol |
|-------|-----|
| `ingest-connector-spec.json` | Kaynak doğruluk: placement (offline, SPI arkası), spi (SourceConnector + FormatExtractor), formats (6 format), gates, error_taxonomy, residency, pii, invariants G1–G10 |
| `ingest-connector.md` | Tasarım: mimari konum, SPI, format ayıklama yöntemleri, HARD kapılar, kapsam ayrımı, izlenebilirlik |
| `ingest_connector_probe.py` | stdlib-only: `validate` / `ingest <sample>` / `selftest` / `schema`; gerçek ayıklayıcılar (text/csv/html/docx-zip+xml/pdf-bounded) |
| `config/ingest-connector-profiles.json` | 3 profil (pilot-default / regulated-tr / enterprise-eu); allowed_formats + boyut/birim/decompression + residency; sır YOK (`${ENV}`) |
| `samples/*.json` | happy-all-formats / dedup-revision / tenant-isolation / validation-rejects (geçer) + degraded (eler) |
| `samples/fixtures/*` | Gerçek tiny dosyalar: `policy.pdf` (uncompressed), `policy-flate.pdf` (FlateDecode), `policy.docx`, `page.html`, `policy.txt`, `faq.csv`, `bomb.docx` (zip-bomb), `corrupt.pdf`; `_gen_fixtures.py` üreteç |
| `tests/ingest_connector_behavior_test.py` | Davranış kapısı T1–T10 |
| `run_live_test.sh` | Statik + sample + (canlı SKIP/not; `${KB_WEB_FETCH_BASE_URL}`) |

## Çalıştır
```bash
python3 ingest_connector_probe.py validate     # statik spec/config kapısı
python3 ingest_connector_probe.py selftest     # iyi/kötü senaryo + her ayıklayıcı
python3 ingest_connector_probe.py ingest samples/ingest-happy-all-formats.json
python3 tests/ingest_connector_behavior_test.py
./run_live_test.sh                             # hepsi + canlı SKIP notu
```

## HARD kapılar (G1–G10)
G1 format coverage (6 format parse) · G2 detection+reconcile (spoof reddi) · G3 validation
(allowlist/boyut/birim/charset/bomb) · G4 normalization (NFC/boilerplate/yapı) · G5 metadata+hash+dedup ·
G6 tenant/kb namespace+izolasyon (fail-closed) · G7 ACL metadata kancası (→6.1.4) · G8 residency+no-log+PII ·
G9 robust/never-crash · G10 kapsam sınırı (embed/index → 6.1.3).

## Kapsam ayrımı (G10)
chunk/embed/index/versiyonlama → **6.1.3**; SharePoint/Confluence → **6.1.2**; doküman-bazı erişim
ENFORCEMENT → **6.1.4** (connector yalnız metadata kancası); içerik TTL/bayatlama → **6.1.5**; vector store
namespace fiziksel → **1.1.7**; retrieval/trim → **6.2.x**; benchmark → **6.2.5**. Bu motor embedding/vektör
üretmez.

Vendor-neutral (ADR-002): her formatın ayıklayıcısı bir SPI arkasında — referans stdlib ayıklayıcı yeterli,
canlıda ağır PDF/Office kütüphanesi aynı SPI arkasına takılır. Credential-free; deterministik (sanal saat).
Sır/PII repoya yazılmaz; fixture içerikleri sentetik (FR-TST-008). → `reports/6.1.1-ingest-connector-raporu.md`
