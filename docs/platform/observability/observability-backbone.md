# Gözlemlenebilirlik Omurgası — İskelet (OTel · Prometheus · Grafana · Loki)

> **WBS 0.4.7** · `F0` · `Must` · →**SAD §17**, BRD §15 · NFR 10.1/10.2/10.7 · FR-RES-012, FR-ANA-012, FR-ANA-007/013, FR-BIL-002, FR-TOOL-010
> Tarih: 2026-06-13 · Durum: ✅ İskelet hazır — tasarım-tamlık kapısı 🟢 geçti

## 1. Amaç ve kapsam

Platformun **gözlemlenebilirlik omurgasının iskeletini** kurar: üç telemetri sinyali (traces /
metrics / logs) için tek girişli (OTel Collector) toplama hattı, depolama (Prometheus / Loki / OTLP
trace backend), görselleştirme (Grafana) ve alarm (Prometheus rules). SAD §11'de stack zaten
**OpenTelemetry + Prometheus + Grafana + Loki** olarak sabitlenmiştir; bu görev onu çalıştırılabilir
bir iskelete ve **doğrulanabilir bir tasarım-tamlık kapısına** indirir.

Bu bir **iskelet**tir (0.4.x platform engineering, Faz 0): config'ler vendor-neutral ve
credential-free; gerçek endpoint/secret IaC (0.4.2) + secrets (0.4.5) ile, deploy K8s (0.4.3) +
CI/CD (0.4.4) ile, gerçek metrik değerleri Faz 1 runtime telemetrisiyle doldurulur. Buradaki kapı,
**"BRD §15 / SAD §17 gereksinimlerinin tamamı omurgada yer alıyor mu ve config'ler spec ile tutarlı
mı?"** sorusunu otomatik yanıtlar.

CLAUDE.md akışı: **analiz** (SAD §17.1/§17.2/§17.3, §11, §13.3; BRD §15) → **plan** (spec = kaynak
doğruluk + skeleton config + stdlib doğrulayıcı) → **geliştir** → **test** (selftest 11/11 + validate
🟢) → **bugfix** (§7).

## 2. Üretilenler

| Dosya | İçerik |
|-------|--------|
| `observability-spec.json` | **Makine-okunur kaynak doğruluk**: metrik (BRD §15) + span (BRD §15) + alarm (SAD §17.2) katalogları, label/kardinalite politikası, sampling, pipeline'lar, config dosya işaretçileri |
| `observability_probe.py` | stdlib-only doğrulayıcı: `validate`/`coverage`/`selftest`/`schema`; kapsam + kardinalite + alarm bütçesi + çapraz-tutarlılık kapısı → çıkış kodu |
| `config/otel-collector.yaml` | OTel Collector iskeleti: OTLP receiver, tenant-context + kardinalite + PII processor, tail-sampling, 3 pipeline → Prometheus/Loki/OTLP |
| `config/prometheus.yml` | Scrape config + rule_files + alertmanager iskeleti (K8s SD) |
| `config/alerts.yaml` | SAD §17.2 alarm kataloğu → Prometheus alerting rules (her biri `for:` ≤2dk) |
| `config/loki.yaml` | Loki iskeleti: multi-tenant (X-Scope-OrgID), düşük-kardinalite stream label, retention/residency notu |
| `config/grafana-dashboard-voice-runtime.json` | Grafana voice-runtime panosu iskeleti (refresh 30s ≤60sn FR-ANA-012) |
| `README.md` | Klasör indeksi + komutlar |

## 3. Mimari — tek giriş, üç sinyal, çok çıkış

```
  data plane (Go/Rust)        ┌──────────────────────────────┐    Prometheus  ── Grafana
  control plane (FastAPI)     │      OTel Collector           │ ─ metrics ─►   (dashboard, ≤60sn)
   │  OTLP (grpc/http)        │  ┌────────────────────────┐  │
   ├──── traces ─────────────►│  │ resource: tenant_ctx   │  │    OTLP trace backend
   ├──── metrics ────────────►│  │ tail_sampling          │  │ ─ traces ─►  (Tempo/Jaeger-uyumlu)
   └──── logs ───────────────►│  │ cardinality+PII guard  │  │
                              │  │ batch (asenkron)       │  │    Loki
                              │  └────────────────────────┘  │ ─ logs ─►    (multi-tenant, residency)
                              └──────────────────────────────┘
                                          │
                                  Prometheus rules → Alertmanager (≤2dk, NFR 10.1)
```

- **Tek giriş:** SDK'lar (data plane Go/Rust ADR-003; control plane FastAPI) yalnız OTLP konuşur →
  vendor-neutral, backend değiştirmek collector exporter'ı değiştirmektir (ADR-002 ruhu).
- **`tenant_id` / `correlation_id` her yerde:** SAD §13.3 gereği bağlam (`tenant_id`, `org_unit`,
  `agent_id`, `correlation_id`, `region`) her istek/event/log/span'de taşınır; collector
  `resource/tenant_context` ile garanti eder.
- **"Measure everything, cheaply" (SAD §1 prensip 7):** runtime'da örneklemeli + asenkron (FR-RES-012);
  ağır işleme collector'da. Ölçüm hot-path'i yavaşlatmaz (§20 gecikme bütçesi korunur).

## 4. Span modeli (SAD §17.1 / BRD §15)

Her çağrı bir `correlation_id` + OTel trace'i taşır; BRD §15'in **15 zaman damgası** span/event olarak
kaydedilir: `call_connected → first_audio_received → speech_started → speech_ended → stt_partial →
stt_final → llm_request_started → llm_first_token → tool_request → tool_response → tts_request →
tts_first_audio → audio_played → call_transferred → call_ended`. Bu, 0.3.1 turn state machine
(LISTEN→CAPTURE→THINK→ACT→SPEAK) ile birebir hizalı; tool span'i `correlation_id` ile audit'e bağlanır
(FR-TOOL-010).

## 5. Metrik kataloğu ve **kardinalite disiplini** (kritik tasarım kararı)

BRD §15'in **20 teknik metriği** spec'te tip/birim/label ile tanımlı (packet loss, jitter, codec, SIP
code, STT/LLM/TTS latency, word confidence, token, tool latency, e2e latency, barge-in, silence,
retry/fallback, transfer/termination outcome, provider error, cost/min, per-call CPU/mem).

**Kardinalite invariant'ı** — omurganın TSDB'yi patlatmadan ölçeklenmesinin anahtarı:

- Prometheus metrik label'ları **sınırlı (bounded)** olmalı: `tenant_id`, `org_unit`, `agent_id`,
  `region`, `provider`, `category`, `sip_code`, `codec`, `outcome`.
- **Yüksek-kardinalite kimlikler metrik label'ı OLAMAZ**: `correlation_id`, `call_id`, `customer_id`,
  `session_id`. Bunlar yalnız **trace/log alanı** + metrik **exemplar** olarak taşınır (metrikten
  trace'e tıkla-geç, ama seri sayısını şişirmeden).
- **PII label'da yasak** (BRD §17.7 / FR-REC-004): `phone_number`, `token` collector'da düşürülür.

Bu invariant hem spec'te (`label_policy`) hem collector config'inde (`attributes/metric_cardinality_guard`,
`attributes/pii_guard`) hem de probe'ta (her metriğin label'ı `allowed` alt kümesi mi?) **üç yerde**
zorlanır. Loki tarafında da `correlation_id` stream label değil, log gövdesi alanıdır.

## 6. Alarm kataloğu (SAD §17.2 / BRD §15)

SAD §17.2'nin **11 kritik alarmı** spec'te + `config/alerts.yaml`'da kural olarak: E2E P95>1.5sn,
STT/LLM/tool hata artışı, handoff başarısızlığı, silent call, consent atlama, bilgi sızıntısı, tenant
kapasitesi %80, harcama limiti, kaynak bütçesi (15MB) aşımı. Her kuralın `for:` penceresi **≤2dk**
(NFR 10.1 "alarm ≤2dk üretim"); probe spec `detection_budget_s ≤120` ve YAML `for:` ≤120s'i çapraz
doğrular.

## 7. Doğrulama kapısı ve bulduğum hata (bugfix)

`python3 observability_probe.py validate` beş grubu HARD kapı olarak çalıştırır:
**spec-health · coverage · cardinality · alert-budget · cross-consistency** → hepsi 🟢, çıkış 0.
`selftest` 11/11 (pozitif: gerçek iskelet geçer; negatif: eksik metrik/span/alarm, metrikte
`correlation_id`, high-card key sızması, 300s bütçe, eksik bölüm **yakalanır**; determinizm birebir).

**Bugfix:** `cross-consistency` ilk koşumda `config_files` içindeki `$comment` meta-anahtarını bir
dosya yolu sanıp "eksik dosya" hatası verdi. Düzeltme: `$`-prefiksli / string-olmayan anahtarlar
atlanır. Sonrası tüm kapılar 🟢.

**Kapsam (non-circular):** gereksinim referansı (20 metrik + 15 span + 11 alarm) **probe içinde sabit**
(BRD §15 / SAD §17.2'den); spec bunlara karşı ölçülür → kapsam dairesel değil, gerçek bir kapı.

## 8. Sınırlar ve izleyen işler

- YAML config'ler stdlib'de tam parse edilmez → probe **hafif satır-tabanlı varlık kontrolü** yapar
  (isim/anahtar + `for:` süre). Tam şema doğrulaması **canlı CI'da (0.4.4)** `promtool check rules`,
  `otelcol validate`, `loki -verify-config` ile yapılır; bu iskelet kapısı onun önüne konur.
- Endpoint/secret enjeksiyonu: IaC (0.4.2) + secrets (0.4.5). Deploy: K8s (0.4.3). Bu görev bunlara
  bağımlı değil; iskelet **self-contained**.
- Bu omurga, WBS §14.1 (Gözlemlenebilirlik — çağrı trace span'leri, teknik metrikler, per-call kaynak,
  alarm kuralları, op ekranı) için **F1 uygulama temelidir**; oradaki görevler bu iskeleti gerçek
  kodla doldurur.

## 9. İzlenebilirlik

| Gereksinim | Karşılık |
|-----------|----------|
| SAD §17.1 Trace | span modeli §4, otel traces pipeline, OTLP trace backend |
| SAD §17.1 Metrics | metrik kataloğu §5, prometheus.yml, prometheus exporter |
| SAD §17.1 Logs (FR-RES-012) | loki.yaml, logs pipeline (asenkron/örneklemeli/yapılandırılmış) |
| SAD §17.1 Visualization (FR-ANA-012 ≤60sn) | grafana dashboard, refresh 30s |
| SAD §17.2 Alarm (NFR 10.1 ≤2dk) | alert kataloğu §6, alerts.yaml `for:`≤2dk |
| SAD §17.3 Maliyet/Kaynak (FR-ANA-007/013, FR-BIL-002) | cost_per_minute / call_cpu_seconds / call_memory_bytes metrikleri |
| SAD §13.3 bağlam propagation | label_policy + resource/tenant_context |
| NFR 10.2 (per-call CPU/mem, 15MB) | call_cpu_seconds / call_memory_bytes + ResourceBudgetExceeded alarmı |
| NFR 10.7 residency | loki per-region store notu; collector region label |
| FR-TOOL-010 | tool span + correlation_id |
| BRD §17.7 / FR-REC-004 PII | pii_guard + label_policy PII yasağı |
