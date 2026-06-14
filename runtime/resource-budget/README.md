# `runtime/resource-budget/` — WBS 3.1.4 Per-call kaynak bütçesi (~15MB) izleme + sınırlama

Conversation Orchestrator oturum aktöründe (SAD §6.3) çalışan **Resource Budget Guard** + Resource
Manager **Cost/Resource Meter** (SAD §15.2) sözleşmesi. Her **canlı** çağrının ayak izini (medya
hariç) ömrü boyunca **izler** ve aşımda **kontrollü/graceful sınırlama** uygular (FR-RES-016).

→ 0.3.3 density'nin (offline ölçüm) **runtime karşılığı**. Vendor-neutral (ADR-002), stdlib-only,
credential-free, deterministik (örnek-tetikli, sanal saat, random YOK).

## Dosyalar

| Dosya | Rol |
|-------|-----|
| `resource-budget-spec.json` | **Kaynak doğruluk:** bütçe + bantlar + enforcement + kapılar (B1–B10) |
| `resource-budget.md` | Tasarım: 0.3.3 ile ayrım, üç-bantlı merdiven, HARD kapılar, izlenebilirlik |
| `resource_budget_probe.py` | `validate` / `simulate <sample>` / `selftest` / `schema` — deterministik Guard |
| `config/resource-budget-profiles.json` | 3 profil: pilot-default · enterprise-tight · regulated-conservative |
| `samples/budget-*.json` | happy / warn-mitigated / breach-shed / media-excluded / degraded(fail) |
| `tests/resource_budget_behavior_test.py` | T1–T8 davranış kapısı |
| `run_live_test.sh` | statik kapı + sample (+ canlı NOT, `ORCHESTRATOR_URL`) |

## Hızlı başlangıç

```bash
cd runtime/resource-budget
python3 resource_budget_probe.py validate     # 56/56 PASS
python3 resource_budget_probe.py selftest     # 50/50 PASS
python3 tests/resource_budget_behavior_test.py # 23/23 PASS
./run_live_test.sh                            # hepsi + 5 sample
```

## Model özeti

```
örnek (sample-point) = oturumun t'de ULAŞACAĞI bileşen seviyeleri (azaltma öncesi TALEP)
  footprint = Σ {session_state, dialogue_memory, prompt_context, rag_context, adapter_state, runtime_overhead}   ← MEDYA HARİÇ
  bant:  OK (≤soft) → eylem yok | WARN (soft<x≤hard) → özetle+kırp | BREACH (>hard) → zorla-azalt → grace sonrası kontrollü shed
  izleme: her aşım tespit + yayılır (FR-RES-016) ; sınırlama HER ZAMAN graceful (çökme/OOM yasak — FR-RES-014)
```

**HARD kapılar:** B2 kontrolsüz-aşım=0 · B3 kontrolsüz-OOM=0 (graceful) · B4 tespitsiz-aşım=0 ·
B5 azaltma-etkili · B7 spurious=0 (adillik) · B8 medya-bütçe-dışı.

Kapsam dışı: density offline ölçüm → **0.3.3**; worker düzeyi backpressure/admission → **FR-RES-014**
(0.4.8); özetleme motoru → **3.2.x**. Sır/PII/ham ses payload'ı/transkript repoya yazılmaz.
