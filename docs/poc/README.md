# PoC / Spike — `docs/poc/`

Bu klasör, WBS **0.3 (PoC / Spike — mimari doğrulama)** görevlerinin kaynak doğruluğudur. 0.2.x
vendor-eval hattıyla aynı disiplin: **sağlayıcı-nötr (ADR-002), stdlib-only, credential-free,
tekrarlanabilir.** PoC'lar BRD/SAD'ın mimari hipotezlerini çalışan spike'larla doğrular.

## İlkeler (CLAUDE.md ile uyumlu)
- **Vendor-neutral:** PoC sağlayıcı **seçmez**; orchestrator yalnız adapter SPI'ye (SAD §8.1) bağlıdır.
  Sahte (`Sim*`) adapter ile gerçek adapter aynı arayüzü doldurur; canlı PoC'ta orchestrator değişmez.
- **stdlib-only / deterministik:** Harici bağımlılık ve gerçek ağ yok; **sanal saat** ile aynı senaryo
  → aynı sonuç (CI). Gerçek credential yalnız `--url`/ortam değişkeni ile (canlı 0.3.x). **Sır repoya yazılmaz.**
- **Sentetik veri:** Senaryolar `samples/*.json` — gerçek müşteri verisi yok (FR-TST-008).

## İçerik
| Dosya | Kapsam | WBS · İz |
|-------|--------|----------|
| `e2e-inbound-poc.md` | Uçtan uca tek inbound akış PoC tasarımı (telefon→STT→LLM→TTS→telefon) + mimari eşleme + kapı | 0.3.1 · SAD §25/§6.1/§7.1/§20, ADR-001/002/005 |
| `e2e_inbound_poc.py` | E2E orkestrasyon hattı (`run`/`selftest`/`schema`); turn state machine + barge-in + STT fallback + context propagation + SAD §20 gecikme kırılımı + 0.3.1 invariant kapısı | 0.3.1 |
| `samples/inbound-*.json` | İllüstratif inbound senaryolar: `happy-path` (intent→tool→RAG→kapanış), `barge-in` (SPEAK→CAPTURE, TR), `stt-fallback` (FR-STT-008) | 0.3.1 |
| `latency-budget.md` | Gecikme bütçesi ölçümü tasarımı: end-of-utterance→ilk ses metriği, lognormal bileşen modeli, NFR 10.1 HARD kapı, bileşen atfı/headroom | 0.3.2 · NFR 10.1/SAD §20 |
| `latency_budget_probe.py` | Monte-Carlo gecikme bütçesi hattı (`measure`/`compare`/`selftest`/`schema`); P50/P95/P99 + barge-in kesme + tool overhead kapısı + bileşen atfı; deterministik tohumlu örnekleme | 0.3.2 |
| `samples/latency-*.json` | İllüstratif gecikme profilleri: `green-baseline` (geçer), `tail-heavy` (P95 eler — kuyruk riski), `red-degraded` (çoklu kapı eler) | 0.3.2 |
| `density-measurement.md` | Density ölçümü tasarımı: oturum-başı bellek (medya hariç) + worker bellek∩CPU kapasitesi, lognormal bileşen modeli, NFR 10.2 HARD kapı (15MB + ≥250/500), medya-konumu duyarlılığı | 0.3.3 · NFR 10.2/ADR-003, SAD §15 |
| `density_probe.py` | Monte-Carlo density hattı (`measure`/`compare`/`selftest`/`schema`); oturum-başı bellek P50/P95/P99 + CPU + bellek∩CPU density kapasitesi + bileşen atfı; medya draw'ları ayrı RNG stream (bütçe medya-hariç) | 0.3.3 |
| `samples/density-*.json` | İllüstratif density profilleri: `green-baseline` (geçer, ≥500), `media-colocated` (HARD geçer ama stretch ıskalar — 0.3.4 duyarlılığı), `red-degraded` (bütçe+density eler — ADR-003 ihlali) | 0.3.3 |
| `media-placement.md` | Medya işleme konumu deneyi tasarımı (edge vs merkez → ADR-009): 0.3.2 gecikme + 0.3.3 density HARD kapılarını birleştirir; topolojiye-bağlı medya/ağ + barge-in + eş-konum; birleşik NFR 10.1+10.2 kapısı + ağırlıklı karar matrisi | 0.3.4 · ADR-009/ADR-005, NFR 10.1/10.2, SAD §6.4/§20/§23 |
| `media_placement_probe.py` | Medya konumu karar hattı (`evaluate`/`compare`/`selftest`/`schema`); e2e+barge-in+density birleşik kapı + HARD-geçen adaylar arası ADR-009 önerisi; `LogNormalComponent`+`percentile` 0.3.1/0.3.2/0.3.3 ile birebir | 0.3.4 |
| `samples/media-*.json` | İllüstratif topoloji profilleri: `edge` (🟢 geçer, ops cezası), `central` (🔴 barge-in eler — ADR-005), `hybrid` (🟢 önerilen → ADR-009) | 0.3.4 |

## Hızlı başvuru
```bash
# Self-test (credential'sız, CI) — çekirdek invariant'lar
python3 docs/poc/e2e_inbound_poc.py selftest

# Bir inbound çağrıyı uçtan uca koştur (olay izi + tur özeti + 0.3.1 kapı verdict'i)
python3 docs/poc/e2e_inbound_poc.py run --scenario docs/poc/samples/inbound-happy-path.json --verbose

# Gecikme bütçesi ölç (0.3.2): P50/P95/P99 + barge-in + NFR 10.1 HARD kapı
python3 docs/poc/latency_budget_probe.py selftest
python3 docs/poc/latency_budget_probe.py measure --profile docs/poc/samples/latency-green-baseline.json
python3 docs/poc/latency_budget_probe.py compare docs/poc/samples/latency-green-baseline.json docs/poc/samples/latency-tail-heavy.json docs/poc/samples/latency-red-degraded.json

# Density ölç (0.3.3): oturum-başı bellek (medya hariç) + worker density + NFR 10.2 HARD kapı
python3 docs/poc/density_probe.py selftest
python3 docs/poc/density_probe.py measure --profile docs/poc/samples/density-green-baseline.json
python3 docs/poc/density_probe.py compare docs/poc/samples/density-green-baseline.json docs/poc/samples/density-media-colocated.json docs/poc/samples/density-red-degraded.json

# Medya konumu deneyi (0.3.4): edge/merkez/hibrit → birleşik NFR 10.1+10.2 kapısı + ADR-009 önerisi
python3 docs/poc/media_placement_probe.py selftest
python3 docs/poc/media_placement_probe.py evaluate --profile docs/poc/samples/media-hybrid.json
python3 docs/poc/media_placement_probe.py compare docs/poc/samples/media-edge.json docs/poc/samples/media-central.json docs/poc/samples/media-hybrid.json
```

## Sıradaki PoC görevleri (0.3.x)
- **0.3.4** Medya işleme konumu deneyi (edge vs merkez) → **ADR-009 kararı** — ✅ tamam: **hibrit** (ADR-009 `Kabul`).
- **0.3.5** Hot-path dil doğrulaması (Go/Rust async runtime, ADR-003).

> 0.3.x canlı PoC, **0.2.6 provizyonel** sağlayıcı seçimini gerçek adapter + DPA/alt-işleyen (17.2.2)
> ile bağlar. Aynı SPI; orchestrator çekirdeği değişmez.
