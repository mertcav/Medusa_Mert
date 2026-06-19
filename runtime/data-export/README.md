# 14.2.8 — Dashboard + ham veri export (`runtime/data-export/`)

**FR-ANA-011** (dashboard ve ham veri export edilebilmelidir) · **SR-ANA-011** (Yöntem T — export dosyası
üretilir ve tutarlıdır) · `F2` · `Must` · RTM: FR-ANA-011 ↔ SR-ANA-011 ↔ TC-ANA-011 (T) ↔ WBS 14.2.8.

Analytics/Ops Plane'deki (SAD §4.2 — async batch; ADR-004/ADR-007; FR-RES-011 hot-path DIŞI) **dashboard + ham veri
export (data export) motoru**. OLAP rollup/fact tablolarını (`mv_call_daily` / `mv_usage_daily` /
`mv_agent_version_perf` / `fct_call` — 14.2.1/14.2.2/14.2.3/14.2.4/14.2.5 üretir) **okur** ve hem (a) dashboard panel
agregatlarını sunar hem (b) **alttaki redaksiyonlu satırları bir export dosyasına** (csv/jsonl/ndjson) yazar.

> Bu motor metriği **yeniden hesaplamaz** (14.2.x üretir) — **okur + export eder + dashboard ile uzlaştırır**.

## İki çekirdek kapı (SR-ANA-011: "üretilir ve tutarlıdır")
- **G1 — Export bütünlüğü — BİRİNCİL ("üretilir"):** export edilen benzersiz satır sayısı = sorgulanan benzersiz
  satır (düşme=0, hayalet=0); `manifest.row_count` tutarlı; satırlar `order_by` ile **deterministik** sıralanır +
  **sha256 checksum** (aynı sorgu → aynı dosya → aynı checksum, replay-safe). `dedup_key` ile at-least-once çift-satır
  daraltılır (1.1.8 P3) — benzersiz satır **sessizce düşmez**.
- **G2 — Export-dashboard tutarlılığı ("tutarlıdır"):** export edilen **alttaki** satırların **yeniden-agregasyonu**
  dashboard tile değerini **yeniden üretir** (`re-aggregation == tile ±tolerance`); partition tile grubu (ör. outcome
  dağılımı) handled paydası üzerinde toplamı **1.0**. Bir export dosyası dashboard'ı doğrulayamıyorsa **yanıltır**.

İkincil çekirdek **G5 — yetki:** export `analytics:read` ister, karar **backend'de**, platform L0 (RMC) tenant
içeriğini export **edemez** (altın kural FR-IAM-008). A-14 spec: *"Export derin aksiyondur ve redaction + audit ile
gerçekleşir."*

## Export kaynakları (kapalı; `analytics/olap-spec.json` ile BİREBİR non-circular)
| kaynak | tür | iz |
|---|---|---|
| `mv_call_daily` | rollup | FR-ANA-003 |
| `mv_usage_daily` | rollup | FR-ANA-011 (dashboard_fr) |
| `mv_agent_version_perf` | rollup | FR-ANA-010 |
| `fct_call` | fact (satır-düzeyi redaksiyonlu) | FR-ANA-002 |

Export sütunları kaynağın OLAP sütun/metrik kataloğundan gelir; her sütun `pii_class ∈ {none, low, redacted}` (A4 —
ham PII/transkript OLAP'a yazılmaz). Bilinmeyen kaynak/format export edilemez.

## HARD kapılar (G1–G9)
`G1` bütünlük (satır sayısı + deterministik sıra + sha256, BİRİNCİL) · `G2` uzlaşma (export ↔ dashboard tutarlılığı) ·
`G3` format (format ∈ supported; sütun OLAP kataloğunda BİREBİR) · `G4` PII (yalnız redaksiyonlu/agregat sütun; ham
transkript/ses/kayıt URI/PII DEĞERİ yok — FR-REC-004/005) · `G5` yetki (`analytics:read` + backend + platform L0 altın
kural, İKİNCİL) · `G6` izolasyon (tek tenant + cross-tenant yok + home-region — FR-TEN-002/NFR 10.7) · `G7` audit (her
export → `governance.audit.v1` `data_export` WORM izi; SESSİZ export yok; içerik/PII taşımaz) · `G8` idempotency
(`(tenant,report,source,period,format,schema)` bir kez; duplicate export yok) · `G9` non-blocking (analytics plane;
export canlı çağrıyı etkilemez — FR-RES-011).

## Dosyalar
- `data-export-spec.json` — makine-okunur kaynak doğruluk (placement, export_format, export_sources, reconciliation,
  authorization, audit, row_integrity, feature_policy, isolation, idempotency, gates, error_taxonomy, invariants
  I1–I15).
- `export_probe.py` — stdlib-only: `validate` | `export <sample>` | `selftest` | `schema`. Deterministik
  `DataExportEngine` (sıralama + sha256 checksum; random YOK).
- `config/data-export-profiles.json` — deployment profilleri (region/schema_version/default_format;
  regulated-dedicated → JSONL + platform L0 yasağı).
- `samples/*.json` — `export-happy-path` (yetkili + tutarlı → tüm kapı geçer), `export-degraded-input` (zorlu ama
  GEÇERLİ: at-least-once çift-satır replay-safe daraltılır), `export-degraded` (buggy → G1+G2+G5+G7 eler).
- `tests/export_behavior_test.py` — T1–T11 davranış kapısı (probe selftest'ten bağımsız).
- `run_live_test.sh` — statik kapı + (varsa `DATA_EXPORT_URL`) canlı not; yoksa SKIP.

## Çalıştırma
```bash
python3 export_probe.py validate     # spec ↔ OLAP/config tutarlılığı
python3 export_probe.py selftest     # iyi/kötü kapı tetiklenmesi
python3 export_probe.py export samples/export-happy-path.json
python3 tests/export_behavior_test.py
./run_live_test.sh
```

## Kapsam ayrımı
otomatik skor → 14.2.1 · per-call çıkarım → 14.2.2 · containment/transfer oranı → 14.2.3 · yanlış-bilgi/tool-hata/
güvenlik işareti → 14.2.4 · kritik işaretleme → 14.2.5 · manuel skor → 14.2.6 · sürüm karşılaştırma → 14.2.7 · maliyet
raporu → 14.2.9 · **gerçek-zamanlı op ekranı ≤60s (FR-ANA-012) → 14.1.6**. A-14 UI görsel kapısı (frontend)
`frontend/tenant-app/screens/a14-analytics`; bu motor **backend** export + uzlaşma + redaction + audit yüzeyidir.
**Burada yalnız analitik dashboard agregatı + ham veri export + export-dashboard tutarlılığı.**

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only, **deterministik** (sıralama + sha256; random YOK).
Sır/credential, ham ses payload/transkript metni, kayıt URI ve PII DEĞERİ repoya yazılmaz.
