# Live Ops — gerçek zamanlı operasyon ekranı (≤60sn gecikme) (WBS 14.1.6)

Conversation Orchestrator (Çekirdek IP, SAD §6) gözlemlenebilirlik **VISUALIZATION** katmanındaki
**Real-time Operations View Composer** sözleşmesi + deterministik referans simülatörü. **SAD §17.1
'Visualization: Grafana dashboard'ları; gerçek zamanlı operasyon ekranı (FR-ANA-012, ≤60sn gecikme)'**
runtime/gözlemlenebilirlik karşılığı.

Gözlemlenebilirlik üç sinyali (SAD §17.1): **traces** → 14.1.1 (call-trace) · **metrics** → 14.1.2
(call-metrics) + 14.1.3 (call-resource) · **logs** → 14.1.4 (call-logger). 14.1.5 (call-alarms) bu
sinyallerden **alarm** üretir. 14.1.6 (**bu modül**) bu sinyalleri (metrik + alarm) **TÜKETİR** (yeniden
ölçmez/üretmez): operasyon ekranının panel/**tile** modelini, **BRD §15/SAD §17.1 operasyonel sinyal
gruplarının** kapsamını ve **≤60sn TAZELİK (freshness)** bütçesini (**FR-ANA-012**) tanımlar.

`runtime/call-alarms/` (14.1.5) + `call-logger/` (14.1.4) + `call-resource/` (14.1.3) + `call-metrics/`
(14.1.2) + `call-trace/` (14.1.1) probe disipliniyle birebir: vendor-neutral (ADR-002; Grafana açık),
credential-free, stdlib-only, **deterministik** (saf; random YOK). Tile→metrik bağı **0.4.7
observability-spec** `metrics.catalog` + `grafana-dashboard-voice-runtime.json` paneli ile **BİREBİR**
çapraz-doğrulanır (probe grafana JSON'undan türetir; **non-circular**). Alarm tile'ı **0.4.7 alerts.catalog
(11)** ile BİREBİR.

## Veri tazeliği bütçesi (BİRİNCİL kapı — FR-ANA-012)
Uçtan-uca veri tazeliği (en yeni gösterilen veri noktasının yaşı):

```
freshness(tile) = ingest_lag_s + query_step_s + refresh_interval_s + render_lag_s ≤ 60s
```

- `ingest_lag_s` / `refresh_interval_s` / `render_lag_s` — **deployment** zamanlaması (config profili:
  Prometheus scrape görünürlüğü + Grafana auto-refresh periyodu + sorgu/render gecikmesi).
- `query_step_s` — **tile başına** pano sorgu adımı/min-interval (lookback PENCERESİ DEĞİL — örn. `rate[5m]`
  ortalama penceresidir, tazelik değil; en yeni nokta son scrape kadar tazedir).

Standart profil (10+30+5 = 45s ek-yük) + en geniş `query_step_s` (10s) = **55s ≤ 60s** (5s headroom).
Runtime `refresh_interval_s` 0.4.7 `grafana-dashboard-voice-runtime.json` `refresh` (30s) değerinden
**küçük-veya-eşit** (runtime tightens-or-equals; tam tazelik zincirini bağlar — yalnız refresh değil).
Bu, 14.1.5 `detection_budget`'ın (alarm ≤2dk) **görselleştirme muadili**.

## View komposizyon disiplini (sekiz kapı)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | BRD §15/SAD §17.1 operasyonel sinyal gruplarının HEPSİ tile taşır (latency/errors/traffic/quality/resource/cost/alarms) + grafana panel-referans metriklerinin **15/15**'i yüzeylenir (non-circular) | BRD §15, SAD §17.1, **0.4.7** dashboards/grafana |
| **G2** | Her metrik-tile sinyali **0.4.7** `metrics.catalog`'da (grafana panel kümesi BİREBİR) + alarm-tile **0.4.7** `alerts.catalog` (11) BİREBİR — orphan tile yok | **0.4.7** metrics/alerts.catalog, 14.1.2/14.1.3/14.1.5 |
| **G3** | Her tile `ingest+query_step+refresh+render ≤ 60s` (**FR-ANA-012** gerçek zamanlı op ≤60sn) — **birincil kapı** | **FR-ANA-012**, SAD §17.1, **0.4.7** freshness_budget_s |
| **G4** | Tenant görünümü yalnız kendi tenant verisi (`tenant_id` filtresi; cross-tenant sızıntı yok); platform (L0) görünümü Tier A agregat | **FR-TEN-002**, altın kural §14.4.1 |
| **G5** | Tile boyutu yüksek-kardinalite kimlik (correlation_id/call_id) taşımaz + yalnız `tile_dims_allowed` (0.4.7 `metric_labels_allowed` ⊇) | **0.4.7** label_policy, SAD §13.3 |
| **G6** | Tile boyutunda PII yok (**FR-REC-004**) + **Tier A**: ham içerik (transkript/kayıt/ses payload) yüzeylenmez (içerik → A-12) | **FR-REC-004**, BRD §17.7, altın kural |
| **G7** | Pano auto-refresh açık + `refresh_interval ≤ bütçe` + runtime refresh ≤ 0.4.7 grafana refresh (30s) + bayat-veri göstergesi | **FR-ANA-012**, **0.4.7** grafana refresh |
| **G8** | Drill-down YALNIZ exemplar/annotation (correlation_id/trace_id) → trace (14.1.1) + her tile bir gruba ait (orphan tile yok) | **0.4.7** exemplar_keys, 14.1.1 |

Ek: **I11** error taxonomy (API §11.6: malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION) ·
**I12** spec/config'te sır/ham payload/transkript/PII DEĞERİ yok (yalnız sinyal/etiket/kimlik anahtarı ADLARI).

## Operasyonel sinyal grupları → tile eşlemesi (8 tile / 7 grup)
| Tile | Grup | kind | Sinyaller | grafana panel |
|------|------|------|-----------|--------------:|
| `tile_e2e_latency` | latency | metric | `e2e_response_latency_ms` | 1 |
| `tile_component_latency` | latency | metric | `stt_latency_ms`/`llm_latency_ms`/`tts_latency_ms` | 2 |
| `tile_provider_errors` | errors | metric | `provider_error_ratio`/`retry_fallback_total` | 3 |
| `tile_traffic_outcomes` | traffic | metric | `barge_in_total`/`transfer_result_total`/`call_termination_total` | 4 |
| `tile_media_quality` | quality | metric | `voice_packet_loss_ratio`/`voice_jitter_ms` | 5 |
| `tile_per_call_resource` | resource | metric | `call_memory_bytes`/`call_cpu_seconds` | 6 |
| `tile_cost_tokens` | cost | metric | `cost_per_minute`/`llm_tokens_total` | 7 |
| `tile_active_alarms` | alarms | alarm | 14.1.5 alarm kataloğu (11) | overlay |

Metrik-tile'ların yüzeylediği birleşim = **15 metrik** = 0.4.7 `grafana-dashboard-voice-runtime.json`
panellerinin referansladığı küme (probe çapraz-türetir). 0.4.7 `metrics.catalog`'un grafana'da
**referanslanmayan** 5 metriği (`voice_codec_info`/`telephony_sip_response_total`/`stt_word_confidence`/
`tool_latency_ms`/`silence_duration_ms`) gerçek zamanlı **glance** ekranında değil — drill-down/analitik
(14.2) yüzeyinde.

## Dosyalar
- `live-ops-spec.json` — **kaynak doğruluk**: placement, freshness_budget (≤60 FR-ANA-012), refresh
  (auto/grafana uid/stale), label_policy (kardinalite/PII), content_policy (Tier A), signal_catalog
  (metrik 15 grafana BİREBİR + alarm 11), tile_groups, tiles[8], drilldown (exemplar), gates (G1–G8),
  error_taxonomy, invariants (I1–I12).
- `live_ops_probe.py` — `validate` / `snapshot <sample>` / `selftest` / `schema`.
- `config/live-ops-profiles.json` — 3 profil (eu/tr standard + low-latency-ops); region pini `${ENV}`,
  ingest/refresh/render zamanlaması.
- `samples/` — `liveops-happy-path` (tenant görünümü; 8 tile, tüm kapı geçer) · `liveops-platform-aggregate`
  (L0 platform Tier A agregat; tenant_id yok ama içerik yasak) · `liveops-degraded` (bilinçli; çoklu kapı eler).
- `tests/live_ops_behavior_test.py` — T1–T10 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${GRAFANA_URL}` varsa canlı not, yoksa SKIP.

## Çalıştırma
```bash
python3 live_ops_probe.py validate          # spec + config + 0.4.7 + grafana çapraz-tutarlılık statik kapı
python3 live_ops_probe.py selftest          # kapı regresyon kanıtı
python3 live_ops_probe.py snapshot samples/liveops-happy-path.json
python3 tests/live_ops_behavior_test.py     # T1–T10
bash run_live_test.sh                       # hepsi + (varsa) canlı not
```
Kapılar: **validate 121/121** · **selftest 50/50** · **behavior 22/22** · 3 sample beklendiği gibi (2 pass +
degraded eler).

## Kapsam ayrımı
- Span üretimi + zaman damgası → **14.1.1** (call-trace). Teknik metrik DEĞERLERİ → **14.1.2** (call-metrics).
  Per-call CPU/bellek → **14.1.3** (call-resource). Yapılandırılmış log → **14.1.4** (call-logger). Alarm
  ÜRETİMİ → **14.1.5** (call-alarms).
- Metrik/alarm/**dashboard kataloğu** + collector/Grafana **guard** → **0.4.7** (gözlemlenebilirlik omurgası;
  bu modülün referansı — `dashboards.freshness_budget_s`/`metrics.catalog`/`alerts.catalog`/`label_policy`/
  `grafana-dashboard-voice-runtime.json` BİREBİR).
- **Tek-çağrı içerik/transkript/timeline ekranı** (içerik) → **A-12** (13.4.12). Buradaki gerçek zamanlı
  ekran **Tier A** (yalnız metrik/agregat; altın kural — L0/L1/L2 §14.4.1).
- **Panel UI implementasyonu** (Next.js L2 A-02 canlı izleme ekranı) → 13.4.x / frontend; burada yalnız
  ekranı besleyen **runtime view modeli + ≤60sn tazelik sözleşmesi**.

Burada **yalnız** gerçek zamanlı operasyon ekranı view yolu: tile kataloğu (operasyonel sinyal grupları) +
tazelik bütçe (≤60sn FR-ANA-012) + sinyal eşleme (0.4.7 BİREBİR) + tile-boyut kardinalite/PII + Tier A
içerik + tenant-scope izolasyon + refresh + drill-down/exemplar disiplini. Canlı sistemde Prometheus scrape
+ Grafana (SAD §11/§17.1; ADR-003 runtime sinyal emisyonu). Sır/credential, ham ses payload'ı, transkript ve
**PII DEĞERİ** spec/config/örneklerde tutulmaz (yalnız sinyal + etiket/kimlik **anahtar adları**).

İz: SAD §17.1 (Visualization) + §17.3 + §13.3 + BRD §15 + FR-ANA-012 + observability 0.4.7
(dashboards/metrics/alerts/label_policy/grafana); FR-ANA-013 + FR-REC-004 + FR-TEN-002 + API §11.6;
ADR-001/002/003/011. (FR-ANA-012 ↔ SR-ANA-012 ↔ TC-ANA-012 ↔ WBS 14.1.6 RTM'de zaten eşli; yeni
FR-ID/SRS/RTM değişikliği gerekmedi.)
