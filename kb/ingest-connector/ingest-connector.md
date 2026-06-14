# WBS 6.1.1 — Ingest connector (PDF/Word/HTML/metin/CSV/web) — Tasarım

> `F1` · `Must` · →FR-KB-001 · SR-KB-001 · TC-KB-001 (T) · SAD §10.1 · ADR-001/002
> Kaynak doğruluk: `ingest-connector-spec.json`. Çelişkide BRD/SAD esastır.

## 1. Amaç ve mimari konum

SAD §10.1 offline indeksleme hattının **ilk** aşaması:

```
Doküman (PDF/Word/HTML/CSV/web) ──► [ingest connector] ──► Parse & normalize ──► NormalizedDocument
                                                                                    │ (6.1.3 chunk→embed→index+versiyon)
```

Ingest connector **Control/Analytics Plane**'de (offline; hot-path **değil**) çalışır. L1/L2 panel
`POST /knowledge-bases/{id}/documents` (async indexleme) çağrısı veya web URL fetch ile tetiklenir.
İşi: her formatı **alır**, format/MIME **algılar + beyanla uzlaştırır**, **doğrular**, **kanonik
`NormalizedDocument`'a ayıklar**, **tenant/kb namespace** etiketler, **erişim-metadata kancası** ekler,
**residency/no-log/PII** işaretler. Format-spesifik ayıklama burada; format-agnostik chunk/embed/index
**6.1.3**'te.

**Vendor-neutral (ADR-002):** her formatın ayıklayıcısı bir **FormatExtractor SPI** arkasındadır;
referans stdlib ayıklayıcı (text/csv/html/docx-zip+xml/pdf-bounded) yeterlidir, canlı sistemde ağır
PDF/Office kütüphanesi **aynı SPI** arkasına takılır. Orchestrator/RAG client yalnız `NormalizedDocument`
sözleşmesine bağımlıdır (ADR-001).

## 2. SPI yüzeyleri

- **SourceConnector** — bir kaynağı alır → ham bayt + content-type. `accept(upload)` veya
  `fetch(url)` (SSRF-guard'lı: özel IP/iç ağ yasak; offline'da gövde sample içinde, canlıda `${ENV}`).
- **FormatExtractor** — `extract(bytes, ctx) → NormalizedDocument | IngestError`. Format → ayıklayıcı
  kayıt defteri (registry): `pdf · docx · html · web · text · csv`.

`NormalizedDocument` sözleşmesi: `doc_id, tenant_id, kb_id, format, detected_format, text (kanonik NFC),
blocks[{type,text}], unit_count, unit_kind, char_count, byte_size, content_hash, title, language_hint,
classification, acl_ref, sensitive, redaction_state, no_log, residency_region, source_uri, ingested_at,
duplicate_of`.

## 3. Format ayıklama yöntemleri (referans, stdlib)

| Format | Algılama | Ayıklama | unit_kind |
|--------|----------|----------|-----------|
| **PDF** | `%PDF` magic | bounded: uncompressed + FlateDecode (`zlib`) içerik akışı; `Tj`/`TJ` operatörleri; `/Encrypt`→`ENCRYPTED`, text-op yok→`NEEDS_OCR` | pages |
| **Word/DOCX** | `PK` zip + `word/document.xml` | `zipfile`+`xml.etree`: `w:p` paragraf + `w:tbl/w:tr/w:tc` tablo; decompression-bomb guard (oran) | paragraphs |
| **HTML** | `<html`/`<!doctype`/`<body` | `html.parser`: `script/style/head` atılır, `nav/footer/aside` boilerplate atılır, `h1-h6` heading + `p/li/td` block, `<title>` | blocks |
| **web** | HTTP üzerinden HTML | HTML ile aynı; `source_uri=url`; SSRF-guard | blocks |
| **metin** | utf-8/utf-8-sig çözülebilir | BOM/utf-8/cp1254/latin-1 charset çözümü; satır→paragraph | chars |
| **CSV** | düz metin + csv dialect | `csv.Sniffer` dialect + sezgisel header; `table_header`/`table_row` yapı korunur | rows |

Canlı sistemde ağır kütüphane (ör. tam PDF/Office parser, OCR) **aynı FormatExtractor imzası** arkasına
takılır — kapı kodu değişmez (ADR-001/002).

## 4. HARD kapılar (G1–G10)

| Kapı | Ölçüt | İz |
|------|-------|----|
| **G1 FORMAT COVERAGE** | 6 formatın hepsi geçerli kaynaktan boş-olmayan metin+yapı üretir (`min_formats_supported=6`) | FR-KB-001, SR-KB-001 |
| **G2 DETECTION + RECONCILE** | content-sniffing yetkili; spoof tip (`.txt` uzantılı PDF vb.) `FORMAT_MISMATCH` (`mismatch_leak=0`) | FR-KB-001, güvenlik |
| **G3 VALIDATION** | allowlist/boyut/birim/charset/decompression-bomb/şifreli/boş → STRUCTURED taksonomi reddi | FR-KB-001, DoS guard |
| **G4 NORMALIZATION** | kanonik NFC + kontrol-karakteri temizliği (`control_char_leak=0`); HTML boilerplate atılır; ham bayt sızmaz | SAD §10.1 |
| **G5 METADATA + HASH + DEDUP** | her doc sha256 hash + zorunlu metadata; idempotent re-ingest `duplicate_of` işaretler | FR-KB-001, FR-KB-003 |
| **G6 TENANT/KB NAMESPACE** | her doc tenant+kb etiketi; tenant'sız fail-closed; cross-tenant sızıntı=0 | FR-KB-004, FR-TEN-002 |
| **G7 ACL METADATA HOOK** | classification + acl_ref + redaction_state kancası (→6.1.4) | FR-KB-005 |
| **G8 RESIDENCY + NO-LOG + PII** | home-region + `no_log=true` + `redaction_state=pending`; bölge uyumsuz `REGION_VIOLATION` | FR-KB-010, NFR 10.7 |
| **G9 ROBUST / NEVER-CRASH** | malformed/corrupt/oversize'da exception kaçmaz; bir kötü doc batch'i durdurmaz | güvenlik |
| **G10 SCOPE BOUNDARY** | embed/index/version → 6.1.3 (doc'ta embedding/vector/chunk_ids/index_id yok) | 6.1.3 |

Eşikler **mühendislik varsayılanı**; gerçek değerler tenant compliance profile (DPIA `cp.*`) + üretim
ölçümüyle ayarlanır.

### Hata taksonomisi (G3/G9 — API §11.6 ruhu)
`UNSUPPORTED_FORMAT · FORMAT_MISMATCH · TOO_LARGE · TOO_MANY_UNITS · CORRUPT · EMPTY · ENCODING_ERROR ·
ENCRYPTED · NEEDS_OCR · DECOMPRESSION_BOMB · FETCH_ERROR · REGION_VIOLATION · MISSING_TENANT_CONTEXT`.
Deterministik; ham parser kodu yalnız audit/log — müşteriye sızmaz.

## 5. Tasarım notları / kararlar

- **Content-sniffing yetkili (G2):** beyan formatı (uzantı/content-type) **güvenilmez**; format magic/
  yapıdan algılanır ve beyanla uzlaştırılır. `.txt` uzantılı bir PDF veya `text` olarak servis edilen
  zip → `FORMAT_MISMATCH` (spoof doğrulamayı atlatamaz). Uyumlu çiftler: `web↔html`, `csv→text` (csv
  parse edilebilmeli), `text→html` (basit metin html olabilir).
- **Dedup içerik hash'i ile (G5):** `content_hash = sha256(kanonik metin)`. Aynı içerik farklı format/
  sıkıştırmadan gelse de (ör. uncompressed PDF == FlateDecode PDF aynı metin) **tek hash** → ikinci kopya
  `duplicate_of`. Versiyonlama **6.1.3**'te bu hash'i tüketir (değişen içerik → yeni hash → yeni sürüm).
- **Tenant izolasyonu fail-closed (G6):** `tenant_id`/`kb_id` yoksa reddet. Dedup uzayı `(tenant,kb,hash)`
  ile **izole** — aynı içerik iki tenant'ta ayrı doc; bir tenant'ın hash'i diğerine sızmaz.
- **Connector metadata üretir, enforcement yapmaz (G7):** doküman-bazı erişim yetkisi **uygulaması**
  6.1.4'te; connector yalnız `classification`/`acl_ref`/`redaction_state` kancasını ekler.
- **No-log + redaction pending (G8):** doküman İÇERİĞİ runtime'da PII içerebilir (meşru) → `no_log=true`
  + `redaction_state=pending` ile taşınır; maskeleme **6.1.4** + retrieval no-log **6.2.4**. Bu aşamada
  sağlayıcıya (embedding/LLM) veri **gönderilmez** (embedding 6.1.3).
- **Never-crash (G9):** her kaynak `try/except` ile sarılır; beklenmedik hata bile STRUCTURED `CORRUPT`'a
  düşer ve batch'teki diğer doc'lar işlenmeye devam eder.

## 6. Kapsam ayrımı (bilinçli — G10)

chunk/embed/index/**versiyonlama** → **6.1.3** (NormalizedDocument tüketir); SharePoint/Confluence
connector → **6.1.2**; doküman-bazı erişim yetkisi **ENFORCEMENT** → **6.1.4**; içerik bayatlama/**TTL** →
**6.1.5**; vector store **namespace fiziksel** → **1.1.7**; retrieval/rerank/**trim** → **6.2.x**; kaynak
atfı → **6.2.3**; hassas doküman sağlayıcı log'una gitmeme **UYGULAMA** → **6.2.4/4.2.4/5.8**; KB
benchmark → **6.2.5/FR-KB-009**. Bu motor **embedding üretmez, vektör yazmaz**.

## 7. İzlenebilirlik

RTM'de **FR-KB-001 ↔ SR-KB-001 ↔ TC-KB-001 (T) ↔ 6.1.1** zaten eşli (SRS/RTM **değişmedi**).
Gözlemlenebilirlik: `kb_ingest_total{format,status}` / `kb_ingest_bytes` / `kb_ingest_units{kind}` /
`kb_ingest_rejected_total{error_class}` / `kb_ingest_dedup_total` → BRD §15 → 0.4.7 (`tenant_id`/`doc_id`/
`source_uri` yüksek-kardinalite → yalnız trace/exemplar; doküman metni metriklerde **yok**).

Vendor-neutral (ADR-002); credential-free; stdlib-only; deterministik (sanal saat). Ham doküman/PII/sır
repoya yazılmadı (fixture içerikleri sentetik — FR-TST-008).
