# kb/content-ttl — WBS 6.1.5 Bayatlama/işaretleme (content TTL) (FR-KB-008)

Bilgi Tabanı & RAG **offline** indeksleme hattının (SAD §10.1, Control/Analytics Plane — **hot-path değil**)
**bayatlama/işaretleme** katmanı. 6.1.3'ün ürettiği tazelik atalarını (`indexed_at`/`version_no`/`active`) +
6.1.2 connector kaynak `last_modified`/eTag'ini + DB.md §5.3 `kb_document.content_ttl_at` açık deadline'ını
**tüketir** ve bir tarama anında (`now`) her dokümanı **fresh/stale/expired/pinned** sınıflar, otomatik
`stale` **işaretler**. SR-KB-008/TC-KB-008 başlık kanıtı: *"TTL aşan içerik 'stale' işaretlenir."*

## Dosyalar
- `content-ttl-spec.json` — **kaynak doğruluk** (tazelik/TTL sözleşmesi, G1–G10, durum/reason taksonomi, iz).
- `content-ttl.md` — tasarım (TTL modeli, şiddet sırası, kapılar, kapsam sınırı).
- `content_ttl_probe.py` — stdlib-only referans probe: `validate` / `mark <sample>` / `selftest` / `schema`.
- `config/content-ttl-profiles.json` — TTL profilleri (pilot / regulated-tr / enterprise-eu + degraded negatif).
- `samples/*.json` — senaryolar (ttl-happy / source-drift / explicit-and-pinned / tenant-scope-missing /
  degraded-no-expiry negatif). Sentetik (FR-TST-008).
- `tests/content_ttl_behavior_test.py` — bağımsız davranış testleri (T1–T10, regresyon kapısı).
- `run_live_test.sh` — statik + sample kapısı (credential-free); canlı store yalnız `${KB_VECTOR_DSN}` notu.

## Çalıştırma
```bash
python3 content_ttl_probe.py validate         # statik spec/config/şema kapısı
python3 content_ttl_probe.py mark samples/ttl-happy.json
python3 content_ttl_probe.py selftest         # gömülü davranış kontrolleri
python3 content_ttl_probe.py schema           # sözleşmeleri yazdır
./run_live_test.sh                            # hepsi + (varsa) canlı not
```

## TTL modeli (iki katman + drift + pin)
- **Soft TTL → stale:** `content_ttl_at` (varsa, **ezer**) aksi `indexed_at + max_age(classification)`. İçerik
  eskidi → `stale` işaretlenir; retrieval (6.2.1) hâlâ kullanabilir ama önceliği düşürür.
- **Hard expiry → expired:** `soft + max_age*(factor-1)`. Kesinlikle çok eski → `expired`; retrieval **bastırır**.
- **Source drift → stale:** `source_last_modified > indexed_at` → kaynak değişti, yeniden ingest gerek (6.1.3).
- **Pinned → muaf:** `no_expire` doküman yaştan bağımsız asla bayat (operatör-beyanlı kanonik/yasal içerik).
- **Şiddet sırası:** `pinned > expired > stale(drift/ttl) > missing(require) > fresh`.

## İlkeler
- **Vendor-neutral (ADR-001/002):** TTL kararı policy + doküman metadata'sına dayanır, sağlayıcıya değil.
- **Metadata-only:** karar zaman damgası karşılaştırması — içerik/embedding/ağ **yok** (kayıt doğal PII'sız).
- **6.1.3'ü tüketir:** `index_pipeline_probe` import edilir (o da `ingest_connector_probe`'u) — kod tekrarı yok.
- **Fail-closed:** eksik tazelik (require) → `stale`; bozuk metadata → `MALFORMED_METADATA` stale (asla sessiz fresh).
- **Determinizm:** sanal saat (epoch-sn; Date.now/rastgele yok). **Sır/credential ve gerçek PII repoya yazılmaz.**

## Kapsam dışı
chunk/embed/version → 6.1.3 (tüketir) · işaretin retrieval'e etkisi (bayat bastırma/önceliklendirme) → 6.2.1 ·
yeniden-ingest tetikleme → 6.1.2/6.1.3 · fiziksel `content_ttl_at` kolonu + `ix_kbdoc_ttl` tarama indeksi →
1.1.7 (migration 0010) · hassas no-log → 6.2.4.
