# kb/index-pipeline — WBS 6.1.3 (Parse→chunk→embed→index + versiyonlama)

Bilgi Tabanı & RAG **offline indeksleme hattının** (SAD §10.1) üçüncü/son offline aşaması: 6.1.1/6.1.2
`NormalizedDocument`'ını **chunk → embed (vendor-neutral SPI) → index (tenant+kb namespace) → version**
eder. **Parse'ı yeniden yapmaz** — `ingest_connector_probe`'u import ederek NormalizedDocument'ı 6.1.1'in
ürettiği gibi türetir. Çekirdek: **FR-KB-003** (otomatik chunk/index/versiyonlama).

## Dosyalar
- `index-pipeline-spec.json` — kaynak doğruluk (SPI, chunking, embedding, versiyonlama, gates C1–C10, taksonomi).
- `index-pipeline.md` — tasarım.
- `index_pipeline_probe.py` — stdlib-only probe (`validate` / `index <sample>` / `selftest` / `schema`).
- `config/index-pipeline-profiles.json` — profiller (pilot-default/regulated-tr/enterprise-eu + degraded negatif). Sır YOK (`${ENV}`).
- `samples/*.json` — `index-happy-multi-doc` · `versioning` · `tenant-isolation` (geçer) + `degraded` (expect_gate=fail).
- `tests/index_pipeline_behavior_test.py` — T1–T10 davranış kapısı.
- `run_live_test.sh` — statik + sample her zaman; canlı embedding `${KB_EMBED_ENDPOINT}` varsa not, yoksa SKIP.

## Çalıştırma
```bash
python3 index_pipeline_probe.py validate          # statik spec/config/şema kapısı
python3 index_pipeline_probe.py selftest          # gömülü davranış kontrolleri
python3 index_pipeline_probe.py index samples/versioning.json
python3 index_pipeline_probe.py schema            # SPI/çıktı sözleşmesi
python3 tests/index_pipeline_behavior_test.py     # T1–T10
./run_live_test.sh                                # tümü + canlı SKIP raporu
```

## Kapılar (C1–C10)
C1 chunk-kapsam · C2 citation · C3 embed-SPI · C4 no-train/no-log/residency · C5 namespace-izolasyon ·
C6 yeni-sürüm · C7 idempotent-no-op · C8 atomik-aktivasyon+geçmiş · C9 erişim-metadata-propagasyon ·
C10 robust+kapsam-sınırı.

## Vendor-neutral & güvenlik
Embedding bir SPI arkasında (ADR-001/002); referans deterministik embedder yerine canlıda gerçek model
takılır. Sanal saat + tohumlu embedder → deterministik. Sır/credential/PII repoya yazılmaz (sentetik
fixture, FR-TST-008). Hassas doküman yalnız no-train/no-log endpoint + home-region (FR-LLM-012/FR-KB-010/
NFR 10.7). Kapsam dışı: ACL enforcement→6.1.4, TTL→6.1.5, fiziksel store→1.1.7, retrieval→6.2.x.
