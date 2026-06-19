# 14.2.7 — Agent sürümleri performans karşılaştırma (`runtime/version-compare/`)

**FR-ANA-010** (agent sürümleri arasında performans karşılaştırması) · **SR-ANA-010** (Yöntem A — iki sürümün
metrikleri yan yana karşılaştırılır) · `F2` · `Must` · RTM: FR-ANA-010 ↔ SR-ANA-010 ↔ TC-ANA-010 (A) ↔ WBS 1.1.9, 14.2.7.

Analytics/Ops Plane'deki (SAD §4.2 — async batch; ADR-004/ADR-007; FR-RES-011 hot-path DIŞI) **sürüm karşılaştırma
(version comparison) motoru**. 14.2.1 (`auto_score`, FR-ANA-001) + 14.2.3 (`containment_rate`/`transfer_rate`,
FR-ANA-003) + 14.2.4/14.2.5 (`critical_rate`, FR-ANA-004/008) tarafından üretilip OLAP `mv_agent_version_perf`
rollup'ında (grain `tenant_id + agent_id + agent_version_id`) toplanan **sürüm-başı agregat metrikleri** tüketir ve
**AYNI agent'ın iki (veya daha çok) sürümünü** (baseline ↔ candidate) **metrik-metrik yan yana karşılaştırır**.

> Bu motor metriği **yeniden hesaplamaz** (14.2.1/14.2.3/14.2.4/14.2.5 üretir) — **karşılaştırır**: işaretli delta
> (candidate − baseline) + yön-duyarlı iyileşme + **istatistiksel anlamlılık** + küçük-örnek bastırma.

## İki çekirdek kapı
- **G1 — Karşılaştırma bütünlüğü (apples-to-apples) — BİRİNCİL:** karşılaştırılan kollar **aynı** `agent_id` +
  `tenant_id` + `period` + metrik tanımı taşır; `baseline_version ≠ candidate_version`. Cross-agent / cross-tenant /
  cross-period / cross-metric karşılaştırma **yasak** — bir sürüm karşılaştırmasının en tehlikeli hatası
  *kıyaslanamaz* şeyleri kıyaslayıp yanlış kazanan ilan etmektir.
- **G3 — Anlamlılık-olmadan-kazanan-yok — İKİNCİL çekirdek:** bir sürüm yalnızca delta **istatistiksel anlamlı**
  (`|z| ≥ z_critical(confidence)`) **ve** her iki kol yeterli örnek (`≥ min_sample_n`) taşırsa `improved`/`regressed`
  ilan edilir; aksi **`inconclusive`** (gürültüden yapay kazanan üretilmez). Oran metrikleri **iki-oran z-testi**,
  ortalama metrikleri (`auto_score`) **büyük-örnek normal yaklaşımlı z** ile.

## Metrik kataloğu (kapalı; `mv_agent_version_perf` + `fct_qa_evaluation` ile BİREBİR)
| metrik | tip | yön | guardrail | kaynak |
|---|---|---|---|---|
| `containment_rate` | proportion | higher_is_better | — | mv_agent_version_perf (FR-ANA-003) |
| `transfer_rate` | proportion | lower_is_better | — | mv_agent_version_perf (FR-ANA-003) |
| `critical_rate` | proportion | lower_is_better | ✓ | mv_agent_version_perf (FR-ANA-008) |
| `auto_score` | mean | higher_is_better | — | fct_qa_evaluation (FR-ANA-001) |

`e2e_p95_state` (latency) bu iskelette kapsam dışı — latency bütçesi disiplini 0.3.2'de.

## HARD kapılar (G1–G9)
`G1` bütünlük (apples-to-apples, BİRİNCİL) · `G2` delta/yön (delta = candidate−baseline; improvement direction'a göre;
winner tutarlı) · `G3` anlamlılık (İKİNCİL çekirdek) · `G4` katalog (BİREBİR) · `G5` idempotency
(`(tenant,agent,baseline,candidate,period,schema)` bir kez; duplicate version arm yok) · `G6` küçük-örnek bastırma
(kol örneği < `min_sample_n` → `insufficient_sample`; sessizce düşmez) · `G7` izolasyon (tek tenant + cross-tenant yok +
home-region) · `G8` PII (yalnız redaksiyonlu agregat sufficient stats + düşük-kardinalite boyut; per-call kimlik/PII
yasak — FR-REC-004) · `G9` non-blocking (analytics plane; karşılaştırma canlı çağrıyı etkilemez — FR-RES-011).

**SOFT (kapı değil):** genel öneri `promote_candidate`/`keep_baseline`/`inconclusive` — guardrail metrik anlamlı
regresyonu `keep_baseline`'a iter; primary metrik anlamlı iyileşme `promote_candidate` önerir. Öneri promote/rollback
(FR-AGT-005/006, A-17) için **insan kararını besler**, otomatik dağıtım yapmaz.

## Dosyalar
- `version-compare-spec.json` — makine-okunur kaynak doğruluk (placement, metric_catalog, significance,
  small_sample, verdict_vocabulary, comparison_grain, recommendation, output_contract, idempotency, feature_policy,
  isolation, gates, error_taxonomy, invariants I1–I15).
- `version_compare_probe.py` — stdlib-only: `validate` | `compare <sample>` | `selftest` | `schema`. Deterministik
  `VersionCompareEngine` (saf istatistik; random YOK).
- `config/version-compare-profiles.json` — deployment profilleri (region/schema_version/confidence/min_sample_n;
  regulated-dedicated → 0.99 güven + 50 örnek).
- `samples/*.json` — `compare-happy-path` (açık kazanan → promote), `compare-degraded-input` (zorlu ama GEÇERLİ:
  bastırma + gürültü doğru ele alınır), `compare-degraded` (buggy motor → G1+G3 eler).
- `tests/version_compare_behavior_test.py` — T1–T11 davranış kapısı (probe selftest'ten bağımsız).
- `run_live_test.sh` — statik kapı + (varsa `VERSION_COMPARE_URL`) canlı not; yoksa SKIP.

## Çalıştırma
```bash
python3 version_compare_probe.py validate     # spec ↔ OLAP/config tutarlılığı
python3 version_compare_probe.py selftest     # iyi/kötü kapı tetiklenmesi
python3 version_compare_probe.py compare samples/compare-happy-path.json
python3 tests/version_compare_behavior_test.py
./run_live_test.sh
```

## Kapsam ayrımı
otomatik skor → 14.2.1 · per-call çıkarım → 14.2.2 · containment/transfer **oran agregasyonu** → 14.2.3 (bu motorun
**girdisini** üretir) · yanlış-bilgi/tool-hata/güvenlik işareti → 14.2.4 · kritik işaretleme → 14.2.5 · manuel skor →
14.2.6 · dashboard/export → 14.2.8. **Burada yalnız sürüm-arası karşılaştırma + apples-to-apples bütünlüğü + anlamlılık.**

Sağlayıcı-nötr (ADR-002), credential-free, stdlib-only, **deterministik** (random YOK). Sır/credential, ham ses
payload/transkript metni ve PII DEĞERİ repoya yazılmaz.
