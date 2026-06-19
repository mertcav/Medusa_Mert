# Call Logger — yapılandırılmış asenkron + örneklemeli loglama (WBS 14.1.4)

Conversation Orchestrator (Çekirdek IP, SAD §6) gözlemlenebilirlik emisyon yolundaki **Structured Async
Sampled Logger** sözleşmesi + deterministik referans simülatörü. **SAD §17.1 'Logs: Yapılandırılmış,
örneklemeli, asenkron (FR-RES-012)'** + **FR-RES-012 'Loglama örnekleme (sampling) ve yapılandırılmış
asenkron yazımla yapılmalıdır'** (`Should`) + **SR-RES-012 (I) 'Log yazımı çağrı hot-path'ini bloklamaz'**
runtime karşılığı.

Gözlemlenebilirlik üç sinyali (SAD §17.1): **traces** → 14.1.1 (call-trace) · **metrics** → 14.1.2
(call-metrics) + 14.1.3 (call-resource) · **logs** → **14.1.4 (bu modül)**. 14.1.4 LOGS sinyalini taşır:
çağrı runtime'ı yapılandırılmış (structured JSON) log kayıtları üretir; bunlar **head-based örneklenir**
(normal trafik `base_rate`; WARN+/security/audit HER ZAMAN — `logs_always`), **asenkron/non-blocking**
yazılır (hot-path bloklanmaz), **stream-label kardinalite** (Loki düşük-kardinalite) + **label/gövde PII**
(redaction L7) + **audit ayrımı** (FR-IAM-006 WORM, ASLA örneklenmez) disiplinine uyar.

`runtime/call-resource/` (14.1.3) + `call-metrics/` (14.1.2) + `call-trace/` (14.1.1) probe disipliniyle
birebir: vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (saf; örnekleme **sabit
hash** — random YOK). Tüm eşikler (`base_rate=0.2`, `logs_always`, kardinalite anahtarları, required gövde
anahtarları) **0.4.7 observability-spec** ile **BİREBİR** çapraz-doğrulanır (probe-sabiti değil).

## Log üretim disiplini (yedi kapı)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | Yayılan her kayıt **yapılandırılmış**: `required_body_keys` (tenant_id/correlation_id/level/event/ts) taşır | SAD §17.1, **0.4.7** `trace_log_required_keys` |
| **G2** | Her kaydın `level∈levels` + `kind∈{telemetry,security,audit}` (bilinmeyen taksonomi yok) | SAD §17.1 |
| **G3** | Örnekleme **head-based** + tutarlı (correlation_id); `logs_always` (WARN+/security/audit) **örneklemeyle DÜŞMEZ** | **FR-RES-012**, 0.4.7 `logs_always` |
| **G4** | Yazım **asenkron/non-blocking** (hot-path bloklanmaz) + overflow yalnız **sampleable** düşürür, garantili korunur | **SR-RES-012**, SAD §6.3 |
| **G5** | Hiçbir **stream label** yüksek-kardinalite kimlik (correlation_id/call_id) taşımaz (kimlik = gövde alanı) + yalnız `stream_labels_allowed` | **0.4.7** loki.yaml, SAD §13.3 |
| **G6** | Stream label'da **PII anahtarı yok** + gövde DEĞERİNDE ham PII/transkript/ses yok (redaction L7) | **FR-REC-004**, BRD §17.7 |
| **G7** | **Audit** kaydı (FR-IAM-006 WORM) ASLA örneklenmez + **AYRI WORM sink**'e yönlenir (telemetri sink'e DEĞİL) | **FR-IAM-006**, 0.4.7 `sampling.note` |

Ek: **G8** placement (orchestrator emisyon, structured + async/non-blocking + head-based + audit ayrı;
`from_trace` değil) · **G9** `base_rate`/`logs_always`/`audit.never_sampled`/`high_cardinality_keys`/
`required_body_keys` **0.4.7 BİREBİR** · **G10** error taxonomy (API §11.6) + spec/config/örneklerde
sır/ham payload/PII DEĞERİ yok.

## Örnekleme + asenkron modeli
- **Head-based + tutarlı:** karar çağrının `correlation_id`'sine göre sabit hash ile → aynı çağrının **TÜM**
  kayıtları birlikte tutulur/düşer. `base_rate=0.2` (0.4.7 `logs_base_rate`) → çağrıların ~%20'si örneklenir.
- **logs_always asla düşmez:** `level≥WARN` **veya** `kind∈{security,audit}` kayıtlar örnekleme kararından
  **bağımsız** her zaman tutulur (kritik sinyal kaybolmaz — "measure cheaply, lose nothing critical").
- **Asenkron/non-blocking (SR-RES-012):** kayıtlar **bounded ring buffer**'a non-blocking enqueue edilir →
  hot-path bloklanmaz (§20 gecikme bütçesi korunur). Overflow'da `drop_sampleable_first`: yalnız normal
  telemetry düşer; **garantili** (logs_always) kayıt **asla** overflow ile kaybolmaz.
- **Audit ayrımı (FR-IAM-006):** `kind=audit` kayıtlar ASLA örneklenmez + **ayrı WORM sink**'e yönlenir
  (telemetri/Loki sink'inden ayrı; WORM deposu + retention → DB §6.5/§9, kapsam dışı).

## Stream label vs gövde (Loki kardinalite — 0.4.7)
- **Stream label** (DÜŞÜK kardinalite): yalnız `tenant_id` / `region` / `service` / `level`.
- **Gövde alanı** (yapılandırılmış JSON): `correlation_id` / `call_id` / `trace_id` + güvenli alanlar.
  Yüksek-kardinalite kimlik stream label OLAMAZ (TSDB/Loki kardinalite patlaması) — gövde alanıdır.
- **PII**: ne label'da ne gövde DEĞERİNDE ham PII/transkript/ses (redaction L7, FR-REC-004). `correlation_id`
  vb. **kimlik** (PII değil) → gövdede izinli.

## Dosyalar
- `call-logger-spec.json` — **kaynak doğruluk**: placement, record_model (levels/kinds), structured
  (required_body_keys), sampling (base_rate/logs_always; 0.4.7 birebir), async_buffer (non-blocking/overflow),
  stream_label_policy (kardinalite/PII), redaction (L7), audit (WORM ayrımı), gates (G1–G7),
  error_taxonomy, invariants (G1–G10).
- `call_logger_probe.py` — `validate` / `emit <sample>` / `selftest` / `schema`.
- `config/call-logger-profiles.json` — 3 profil (eu/tr shared + dedicated-regulated); region pini `${ENV}`,
  async-sampled emisyon, ayrı `worm_sink`.
- `samples/` — `log-happy-path` (sampled-in, 8 kayıt yayılır) · `log-sampled` (sampled-out, normal düşer,
  logs_always korunur) · `log-overflow` (backpressure, sampleable düşer, garantili korunur) +
  `log-degraded` (bilinçli, çoklu kapı eler).
- `tests/call_logger_behavior_test.py` — T1–T8 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${ORCHESTRATOR_URL}` varsa canlı not, yoksa SKIP.

## Çalıştırma
```bash
python3 call_logger_probe.py validate          # spec + config + 0.4.7 çapraz-tutarlılık statik kapı
python3 call_logger_probe.py selftest          # kapı regresyon kanıtı
python3 call_logger_probe.py emit samples/log-happy-path.json
python3 tests/call_logger_behavior_test.py     # T1–T8
bash run_live_test.sh                          # hepsi + (varsa) canlı not
```
Kapılar: **validate 66/66** · **selftest 50/50** · **behavior 30/30** · 4 sample beklendiği gibi (3 pass +
degraded eler).

## Kapsam ayrımı
- Span üretimi + zaman damgası → **14.1.1** (call-trace). Teknik metrik DEĞERLERİ → **14.1.2** (call-metrics).
  Per-call CPU/bellek → **14.1.3** (call-resource).
- Metrik/alarm **kataloğu** + collector/Loki **guard** → **0.4.7** (gözlemlenebilirlik omurgası; bu modülün
  referansı — `sampling.logs_base_rate`/`logs_always`/`loki.yaml`/`label_policy` BİREBİR).
- **Alarm kuralları** → **14.1.5**. Gerçek zamanlı operasyon ekranı (≤60sn) → **14.1.6** / FR-ANA-012.
- Bağlam (`tenant_id`/`correlation_id`) **İLİŞTİRME** + genel kardinalite/PII enforcement → **3.1.5**.
- Redaction **ÜRETİMİ** (asıl scrub motoru) L7 → ileri WBS (burada yalnız yayılan kaydın temiz olduğu KAPISI).
- WORM audit **deposu** + retention/legal-hold → **DB §6.5/§9** + **FR-IAM-006**.

Burada **yalnız** log üretim yolu: yapılandırma (structured) + örnekleme (head-based) + asenkron/bloklamama
(SR-RES-012) + stream-label kardinalite + label/gövde PII + audit ayrımı disiplini. Canlı sistemde Go/Rust
async runtime + bounded ring buffer + non-blocking enqueue + OpenTelemetry/Loki (ADR-003, SAD §11/§6.3/§17.1).
Sır/credential, ham ses payload'ı, transkript ve **PII DEĞERİ** spec/config/örneklerde tutulmaz (yalnız log
sinyali + etiket/kimlik **anahtar adları**).
```
İz: SAD §17.1 (Logs) + BRD §15 + observability 0.4.7 (sampling/loki/label_policy) + context-propagation 3.1.5
+ API §11.6; FR-RES-012/SR-RES-012/TC-RES-012 (RTM'de zaten eşli; yeni FR-ID/SRS/RTM değişikliği gerekmedi) +
FR-IAM-006 + FR-REC-004 + FR-ANA-012; ADR-001/002/003/004.
```
