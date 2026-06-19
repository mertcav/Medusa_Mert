# Call Resource — per-call CPU/bellek/eşzamanlılık ölçümü (WBS 14.1.3)

Conversation Orchestrator (Çekirdek IP, SAD §6; Resource Manager BRD §10.2) gözlemlenebilirlik emisyon
yolundaki **Per-call Resource Accountant** sözleşmesi + deterministik referans ölçer. **BRD §15 'çağrı
başına kaynak tüketimi (CPU/bellek)'** + **FR-ANA-013 '(CPU/bellek/eşzamanlılık) raporlanmalıdır'** +
**FR-RES-016 'çağrı başına kaynak bütçesi (bellek/CPU) tanımlanmalı ve aşımı izlenmeli'** + **NFR 10.2**
(aktif çağrı başına orkestratör belleği **medya hariç** ≤ ~15MB; referans işçi başına eş zamanlı oturum
≥250–500) runtime karşılığı.

**14.1.2 (call-metrics)** BRD §15'in 18 teknik metrik DEĞERİNİ hesaplar ve `call_cpu_seconds` /
`call_memory_bytes`'ı **açıkça 14.1.3'e erteler** (out_of_scope). **14.1.3** o boşluğu doldurur: çağrı
başına CPU/bellek (**MEDYA TAMPONLARI HARİÇ**) **ÖLÇÜLÜR** + eşzamanlılık (worker/tenant) anlık-görüntü
alınır; **bütçe (FR-RES-016 ≤15MB)** ve **density (NFR 10.2 ≥250)** kapıları uygulanır; her gözlem **0.4.7
observability-spec** `metrics.catalog` (`call_cpu_seconds`/`call_memory_bytes` **BİREBİR**) +
kardinalite/etiket/PII disiplinine uygun gözlem olarak yayılır.

`runtime/call-metrics/` (14.1.2) + `runtime/call-trace/` (14.1.1) probe disipliniyle birebir:
vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (saf aritmetik, random YOK).
**14.1.2'den temel FARK:** gecikmeleri trace'ten TÜRETMEZ — CPU/bellek **runtime'da ÖLÇÜLÜR** (measured,
`from_trace` değil) ve orkestratör belleği **medya tamponlarını hariç tutar** (ADR-009 hibrit: ağır medya
ayrı/eş-konumsuz katman).

## Kapsanan kaynak metrikleri (5 — ÖLÇÜM)
| # | Metrik | Tip / birim | Kaynak | 0.4.7 |
|---|--------|-------------|--------|-------|
| 1 | `call_cpu_seconds` | hist / s | `(cpu.user_ms+system_ms)/1000` | **BİREBİR** |
| 2 | `call_memory_bytes` *(budget)* | hist / bytes | `memory.session_rss_bytes` (**medya HARİÇ**) | **BİREBİR** |
| 3 | `call_media_buffer_bytes` *(conditional, budget DIŞI)* | hist / bytes | `memory.media_buffer_bytes` | proposed |
| 4 | `worker_active_sessions` *(eşzamanlılık/density)* | gauge / sessions | `concurrency.worker_active_sessions` | proposed |
| 5 | `tenant_concurrency` *(eşzamanlılık)* | gauge / calls | `concurrency.tenant_concurrent_calls` | proposed¹ |

¹ `tenant_concurrency` 0.4.7 `TenantCapacity80` alarmında zaten **referans** edilir; eşzamanlılık metrikleri
(FR-ANA-013) BRD §15'in *"çağrı başına CPU/bellek"* kanonik listesinde YOK → bunlar 14.1.3 tarafından
**önerilir** ve gelecek bir 0.4.7 iterasyonunda kataloğa promote edilir (`proposed_for_observability`).

**Kapsam dışı:** teknik metrik DEĞERLERİ (latency/token/jitter/...) → **14.1.2** (call-metrics).

## Dosyalar
- `call-resource-spec.json` — **kaynak doğruluk**: placement (measured, medya hariç), inputs, value_domains,
  catalog (5 metrik; overlap 0.4.7 birebir), budget (FR-RES-016 15MB), density (NFR 10.2 / 0.3.3),
  label_policy (kardinalite/PII), gates (G1–G7), error_taxonomy, invariants (G1–G10).
- `call_resource_probe.py` — `validate` / `measure <sample>` / `selftest` / `schema`.
- `config/call-resource-profiles.json` — 3 profil (eu/tr shared hibrit + dedicated-regulated edge); region
  pini `${ENV}`, async-sampled emisyon (FR-RES-012), referans işçi 8 vCPU / 16 GiB.
- `samples/` — `resource-happy-path` (hibrit, medya offloaded) · `resource-media-colocated`
  (medya eş-konumlu, bütçe yine medya HARİÇ) · `resource-high-density` (stretch ≥500) +
  `resource-degraded` (bilinçli, çoklu kapı eler).
- `tests/call_resource_behavior_test.py` — T1–T8 davranış kapısı.
- `run_live_test.sh` — statik kapı + sample; `${ORCHESTRATOR_URL}` varsa canlı not, yoksa SKIP.

## HARD kapılar (G1–G7)
| Kapı | Anlam | İz |
|------|-------|-----|
| **G1** | `required` (+medya eş-konumu varsa `conditional`) kaynak metriklerinin hepsi ölçülüp yayılır | BRD §15, FR-ANA-013 |
| **G2** | Her gözlem 14.1.3 catalog name+type+unit; overlap (cpu/mem) **0.4.7 BİREBİR** | SAD §17.1, 0.4.7 |
| **G3** | Her DEĞER domain sınıfında (cpu_s≥0+finite, byte int≥0, sayım int≥0, ratio∈[0,1]) | FR-ANA-013 |
| **G4** | Çağrı başına orkestratör belleği (**MEDYA HARİÇ**) ≤ **15 MiB** (15728640 B) | **FR-RES-016**, NFR 10.2, 0.4.7 `ResourceBudgetExceeded` |
| **G5** | Bellek footprint'i referans işçide **≥250** density'ye yer verir (`mem×floor ≤ pool`) | **NFR 10.2**, 0.3.3 |
| **G6** | Hiçbir metrik yüksek-kardinalite kimliği (`correlation_id`/...) LABEL taşımaz; yalnız exemplar | SAD §13.3, 0.4.7 |
| **G7** | Her metrik yalnız `catalog[].labels` (⊆ allowed) kullanır + label'da **PII anahtarı yok** | 0.4.7, BRD §17.7, FR-REC-004 |

Ek: **G8** placement (orchestrator emisyon, **measured** — CPU/bellek ÖLÇÜLÜR, medya HARİÇ, bloklamaz) ·
**G9** overlap (cpu/mem) 0.4.7 `metrics.catalog` ile **birebir** + bütçe 0.4.7 `ResourceBudgetExceeded`
eşiği (15728640) ile **birebir** + density floor NFR 10.2 (250) ile tutarlı · **G10** error taxonomy
(API §11.6) + spec/config/örneklerde sır/ham payload/PII DEĞERİ yok.

### Bütçe vs density (G4 vs G5)
- **G4** = mutlak **15 MiB** bellek bütçesi (FR-RES-016 / NFR 10.2 / 0.4.7 alarmı).
- **G5** = density-türevli tavan (referans işçide ≥250 oturuma yer veren footprint; pool/250 ≈ **55.7 MiB**).
- İkisi farklı: 30 MiB oturum G5'i geçer (≤55.7 MiB) ama G4'ü eler (>15 MiB). **0.3.3 bulgusu**: density
  **CPU-bağlı** — 15 MiB bütçe ~1300 oturuma yer verir, tavanı CPU koyar; G5 belleğin density floor'unu
  **bozmadığını** garanti eder.

## Çalıştırma
```bash
python3 call_resource_probe.py validate          # spec + config + 0.4.7 çapraz-tutarlılık statik kapı
python3 call_resource_probe.py selftest          # kapı regresyon kanıtı
python3 call_resource_probe.py measure samples/resource-happy-path.json
python3 tests/call_resource_behavior_test.py     # T1–T8
bash run_live_test.sh                            # hepsi + (varsa) canlı not
```

## Kapsam ayrımı
- Span üretimi + zaman damgası kaydı + gecikme **türetme** → **14.1.1** (call-trace).
- Teknik metrik (latency/token/jitter/...) **DEĞERLERİ** → **14.1.2** (call-metrics).
- Metrik/alarm **kataloğu** + collector guard → **0.4.7** (gözlemlenebilirlik omurgası; bu modülün referansı).
- Kapasite/density **TASARIM TAHMİNİ** (oturum/worker ≤15MB + density ≥250) → **0.3.3** / **0.3.4** (ADR-009
  hibrit; bu modülün **tasarım girdisi** — 14.1.3 runtime'da ÖLÇER, tahmin etmez).
- Yapılandırılmış asenkron + örneklemeli loglama → **14.1.4**.
- **Alarm kuralları** (`ResourceBudgetExceeded` / `TenantCapacity80`) → **14.1.5** (bu metrikler onun girdisi).
- Aggregasyon / dashboard / raporlama → **0.4.7** + **A-01/A-15** + **P-01/P-03**.
- Bağlam (`tenant_id`/`correlation_id`) **İLİŞTİRME** + kardinalite/PII enforcement → **3.1.5**.

Burada **yalnız** çağrı başına **kaynak (CPU/bellek/eşzamanlılık) ölçümü** + bütçe/density kapısı +
katalog/kardinalite/etiket/PII disiplini. Canlı sistemde Go/Rust async runtime + cgroup/RSS/cpu-time
accounting + OpenTelemetry/Prometheus (ADR-003, SAD §11/§6.3/§17.1). Sır/credential, ham ses payload'ı,
transkript ve **PII DEĞERİ** spec/config/örneklerde tutulmaz (yalnız sayısal sinyal + etiket/kimlik
**anahtar adları**).
