# Call Alarms — alarm kuralları (BRD §15) + ≤2dk üretim (WBS 14.1.5)

Conversation Orchestrator (Çekirdek IP, SAD §6) gözlemlenebilirlik emisyon yolundaki **Alarm Rule Engine**
sözleşmesi + deterministik referans simülatörü. **SAD §17.2 'Alarm (BRD §15)'** + **BRD §15 kritik alarm
örnekleri** + **NFR 10.1 'alarm ≤2dk üretim'** runtime karşılığı.

Gözlemlenebilirlik üç sinyali (SAD §17.1): **traces** → 14.1.1 (call-trace) · **metrics** → 14.1.2
(call-metrics) + 14.1.3 (call-resource) · **logs** → 14.1.4 (call-logger). 14.1.5 (**bu modül**) bu
sinyalleri **TÜKETİR**: orchestrator runtime'ının ürettiği metrik/güvenlik/kapasite sinyallerini
**kural-tabanlı** değerlendirir, **BRD §15 kritik alarm kataloğunu** (11 madde) taşır ve her alarmı
**≤2dk (NFR 10.1; detection_budget_s ≤ 120)** üretir.

`runtime/call-logger/` (14.1.4) + `call-resource/` (14.1.3) + `call-metrics/` (14.1.2) + `call-trace/`
(14.1.1) probe disipliniyle birebir: vendor-neutral (ADR-002), credential-free, stdlib-only,
**deterministik** (saf; random YOK). Alarm kataloğu (kural adı + severity + detection_budget) **0.4.7
observability-spec** alerts.catalog + `config/alerts.yaml` ile **BİREBİR** çapraz-doğrulanır (probe-sabiti
değil; **non-circular**). Sinyal kataloğunun metrik kısmı **0.4.7 metrics.catalog (20)** ile BİREBİR.

## Detection latency bütçesi (BİRİNCİL kapı — NFR 10.1)
Uçtan-uca alarm üretim gecikmesi:

```
detection_latency(kural) = ingest_scrape_s + eval_interval_s + for_s + notify_lag_s ≤ 120s
```

- `ingest_scrape_s` / `eval_interval_s` / `notify_lag_s` — **deployment** zamanlaması (config profili:
  Prometheus scrape + kural değerlendirme periyodu + Alertmanager group_wait/dispatch).
- `for_s` — **kural başına** pending→firing bekleme (flap/titreme kontrolü; spec'te).

Standart profil (15+15+10 = 40s ek-yük) + en geniş `for_s` (60s) = **100s ≤ 120s** (20s headroom). Güvenlik
alarmları (consent/info_leak) `for_s=0` → **anında** üretim. Runtime `for_s` değerleri `alerts.yaml`'ın
`for:` değerlerinden **küçük-veya-eşit** (runtime tightens-or-equals; tam zincir NFR 10.1'i bağlar — yalnız
`for:` değil).

## Alarm üretim disiplini (sekiz kapı)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | BRD §15 kritik alarm kataloğunun her maddesi bir kural taşır (kapsam **11/11**); katalog 0.4.7'den türetilir (non-circular) | BRD §15, SAD §17.2, **0.4.7** alerts.catalog |
| **G2** | Kural adı + severity 0.4.7 observability-spec alerts.catalog + `alerts.yaml` ile **BİREBİR** | **0.4.7** alerts.catalog/alerts.yaml |
| **G3** | Her kural `ingest+eval+for+notify ≤ 120s` (**NFR 10.1** alarm ≤2dk üretim) — **birincil kapı** | **NFR 10.1**, SAD §17.2 |
| **G4** | Her kuralın sinyali `signal_catalog`'da (metric_signals 0.4.7 metrics.catalog BİREBİR) — orphan yok | 14.1.2/14.1.3, **0.4.7** metrics.catalog |
| **G5** | Alarm etiketi yüksek-kardinalite kimlik (correlation_id/call_id) taşımaz + yalnız `alarm_labels_allowed` | **0.4.7** label_policy, SAD §13.3 |
| **G6** | Etikette PII anahtarı yok (FR-REC-004) + `scope=tenant` alarmı `tenant_id` taşır (cross-tenant sızıntı yok) | **FR-REC-004**, FR-TEN-002, altın kural |
| **G7** | `for_s>0` flap bastırır + aynı `(alertname, tenant_id)` tek alarma daraltılır (dedup) + auto-resolve | SAD §17.2 |
| **G8** | Her üretilen alarm `severity→kanal` + `scope→kitle`ye yönlenir (unrouted alarm yok) | SAD §17.2, routing |

Ek: **I11** error taxonomy (API §11.6: malformed/unknown→INVALID_REQUEST, region→REGION_VIOLATION) ·
**I12** spec/config'te sır/ham payload/transkript/PII DEĞERİ yok (yalnız sinyal/etiket anahtarı ADLARI).

## BRD §15 → kural eşlemesi (11)
| Kural | BRD §15 | severity | scope | sinyal | for_s |
|-------|---------|----------|-------|--------|------:|
| `E2EP95LatencyHigh` | P95 > 1,5 sn | critical | platform | `e2e_response_latency_ms` | 60 |
| `STTErrorRateHigh` | STT hata artışı | critical | platform | `retry_fallback_total{stt}` | 45 |
| `LLMProviderErrorRateHigh` | LLM sağlayıcı hata | critical | platform | `provider_error_ratio{llm}` | 45 |
| `HandoffFailure` | handoff başarısızlığı | critical | platform | `transfer_result_total{failed}` | 30 |
| `ToolErrorRateHigh` | tool hata artışı | warning | platform | `retry_fallback_total{tool}` | 60 |
| `SilentCallDetected` | silent call | critical | platform | `call_termination_total{silent}` | 30 |
| `ConsentSkipDetected` | consent atlama | critical | tenant | `consent_skip_total` | 0 |
| `InfoLeakDetected` | bilgi sızıntısı | critical | tenant | `info_leak_total` | 0 |
| `TenantCapacity80` | tenant kapasitesi %80 | warning | tenant | `tenant_concurrency` | 60 |
| `SpendLimitExceeded` | harcama limiti | warning | tenant | `tenant_spend` | 30 |
| `ResourceBudgetExceeded` | kaynak bütçesi (15MB) | warning | platform | `call_memory_bytes` | 60 |

## Dosyalar
- `call-alarms-spec.json` — **kaynak doğruluk**: placement, detection_budget (≤120 NFR 10.1),
  label_policy (kardinalite/PII), signal_catalog (metric 0.4.7 birebir + security/capacity), rules[11]
  (BRD §15 kataloğu), routing (severity→kanal + scope→kitle), flap_control (debounce/dedup/auto-resolve),
  gates (G1–G8), error_taxonomy, invariants (I1–I12).
- `call_alarms_probe.py` — `validate` / `evaluate <sample>` / `selftest` / `schema`.
- `config/call-alarms-profiles.json` — 3 profil (eu/tr standard + low-latency-critical); region pini `${ENV}`,
  scrape/eval/notify zamanlaması.
- `samples/` — `alarm-happy-path` (4 alarm üretilir, tüm kapı geçer) · `alarm-security-instant`
  (consent/info-leak for_s=0 anında, tenant-scope) · `alarm-degraded` (bilinçli; çoklu kapı eler).
- `tests/call_alarms_behavior_test.py` — T1–T10 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${ALERTMANAGER_URL}` varsa canlı not, yoksa SKIP.

## Çalıştırma
```bash
python3 call_alarms_probe.py validate          # spec + config + 0.4.7 + alerts.yaml çapraz-tutarlılık statik kapı
python3 call_alarms_probe.py selftest          # kapı regresyon kanıtı
python3 call_alarms_probe.py evaluate samples/alarm-happy-path.json
python3 tests/call_alarms_behavior_test.py     # T1–T10
bash run_live_test.sh                          # hepsi + (varsa) canlı not
```
Kapılar: **validate 140/140** · **selftest 50/50** · **behavior 22/22** · 3 sample beklendiği gibi (2 pass +
degraded eler).

## Kapsam ayrımı
- Span üretimi + zaman damgası → **14.1.1** (call-trace). Teknik metrik DEĞERLERİ → **14.1.2** (call-metrics).
  Per-call CPU/bellek → **14.1.3** (call-resource). Yapılandırılmış log → **14.1.4** (call-logger).
- Metrik/alarm **kataloğu** + collector/Loki **guard** → **0.4.7** (gözlemlenebilirlik omurgası; bu modülün
  referansı — `alerts.catalog`/`alerts.yaml`/`metrics.catalog`/`label_policy` BİREBİR).
- **Gerçek zamanlı operasyon ekranı** (≤60sn) → **14.1.6** / FR-ANA-012.
- Sinyal ÜRETİMİ (metrik emisyonu) → 14.1.2/14.1.3. Consent enforcement / DLP-info-leak / tenant kapasite
  sinyalleri → ilgili alt-sistem WBS (burada yalnız bu sinyallerin alarm KURALLARI).
- Bildirim kanalı **entegrasyonu** (pager/ticket gerçek bağlantısı) → ileri WBS (burada yalnız routing
  sözleşmesi: severity→kanal + scope→kitle).

Burada **yalnız** alarm üretim yolu: kural kataloğu (BRD §15) + detection bütçe (≤2dk NFR 10.1) + sinyal
eşleme + alarm-label kardinalite/PII + tenant-scope izolasyon + flap/dedup + severity routing disiplini.
Canlı sistemde Prometheus scrape/eval + Alertmanager (SAD §11/§17.2; ADR-003 runtime sinyal emisyonu). Sır/
credential, ham ses payload'ı, transkript ve **PII DEĞERİ** spec/config/örneklerde tutulmaz (yalnız sinyal
+ etiket/kimlik **anahtar adları**).

İz: SAD §17.2 (Alarm) + §17.1 + BRD §15 + NFR 10.1 + observability 0.4.7 (alerts/metrics/label_policy);
FR-ANA-012 + FR-RES-016 + FR-REC-004 + FR-TEN-002 + API §11.6; ADR-001/002/003/004.
(FR/SR/RTM'de zaten eşli; yeni FR-ID/SRS/RTM değişikliği gerekmedi.)
