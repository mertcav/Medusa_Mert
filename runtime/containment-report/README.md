# runtime/containment-report — WBS 14.2.3 Containment/transfer oranı raporu

> `F1` · `Must` · →**FR-ANA-003** · SR-ANA-003 (A) · TC-ANA-003

Analytics/Ops Plane'deki (SAD §4.2, async batch — ADR-004/ADR-007) **oran (rate) agregasyon/rapor motoru**.
14.2.2'nin (`runtime/call-derivation/`) ürettiği **per-call `outcome` etiketini** (`contained` /
`transferred_to_human` / `abandoned` / `unresolved` / `not_connected` — kapalı-sözlük) ve OLAP
`fct_call.contained`/`transferred` boolean materyalizasyonunu **AGREGE eder**; FR-ANA-003
`containment_rate` + `transfer_rate` metriklerini (BRD §18.1 KPI; OLAP `mv_call_daily` rollup) rapor
boyutlarına (`tenant_id` + `agent_id` + `agent_version_id` + `period`) göre + **genel** hesaplar.

Bu dilim **ORANI** üretir; per-call **etiket** 14.2.2'de üretilir — bu motor etiketi **yeniden türetmez,
agrege eder** (`aggregates_labels=true`). Vendor-neutral (ADR-002), credential-free, stdlib-only,
**deterministik** (saf sayım/bölme; random YOK).

## Çekirdek istatistiksel karar — payda (denominator)

| Oran | Tanım | Payda |
|------|-------|-------|
| `containment_rate` | `contained / handled` | **handled** (bağlanan) |
| `transfer_rate` | `transferred / handled` | **handled** |
| `abandon_rate` | `abandoned / handled` | handled |
| `unresolved_rate` | `unresolved / handled` | handled |
| `not_connected_rate` | `not_connected / total` | total (bilgilendirici) |

- **handled** = bağlanıp fiilen ULAŞAN çağrı = `{contained, transferred_to_human, abandoned, unresolved}`.
- **`not_connected`** (outbound voicemail/busy/no_answer/invalid; hiç bağlanmadı) **handled paydaya GİRMEZ**
  — aksi halde containment **yapay düşer** (BRD §18.1 + OBJ-01 inbound + contact-centre standardı).
- Dört partisyon oranı **handled üzerinde TAM partisyon** → `containment + transfer + abandon + unresolved == 1.0`.

## HARD kapılar (G1–G9)

- **G1 partisyon (BİRİNCİL):** outcome kovaları girdiyi **tam** partisyonlar — her çağrı tam **bir** kovada,
  çift-sayım yok, sessiz düşürme yok; `sayılan == girdi` (`partition_gap=0`).
- **G2 oran/payda:** `containment=contained/handled`, `transfer=transferred/handled`; pay ≤ payda; her oran
  ∈ [0,1]; dört partisyon oranı toplamı **== 1.0** (handled>0) — payda bütünlüğü.
- **G3 münhasırlık:** bir çağrı tam **bir** outcome kovasında sayılır (mutually exclusive).
- **G4 sözlük (BİREBİR):** `outcome` 14.2.2 `derivation-spec.json` vocab + OLAP `fct_call.contained`/`transferred`
  (FR-ANA-003) ile birebir (non-circular cross-check); bilinmeyen outcome ihlal.
- **G5 idempotent:** `(tenant_id, call_id)` bir kez sayılır; at-least-once replay çift-saymaz (1.1.8 P3).
- **G6 küçük-örnek bastırma:** payda `< min_group_n` grup oranı **yayımlanmaz** (`insufficient_sample`) —
  k-anonimlik + istatistiksel güvenilirlik; sessizce düşmez (sayım tutulur, açık status).
- **G7 izolasyon:** her rapor tek `tenant_id` + cross-tenant yok + residency (FR-TEN-002/NFR 10.7).
- **G8 PII:** yalnız redaksiyonlu etiket + düşük-kardinalite boyut; yayımlanan agregat per-call kimlik/PII
  taşımaz (FR-REC-004; `pii_class low`).
- **G9 async:** analytics plane non-blocking; rapor başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).

**`target` SOFT:** BRD §3.2.1 containment ≥ %60 hedefi `target_met` bilgilendirici bayrağıdır — HARD kapı
**değil** (kapılar **hesap doğruluğu** içindir, iş hedefi karşılandı mı değil).

## Dosyalar

- `containment-report-spec.json` — makine-okunur kaynak doğruluk (placement, outcome_vocabulary,
  denominator, report_grain, small_sample, target, output_contract, idempotency, feature_policy,
  isolation, gates, invariants I1–I15)
- `containment_report_probe.py` — stdlib-only `validate` / `report <sample>` / `selftest` / `schema`
- `config/containment-report-profiles.json` — eu/tr-standard + regulated-dedicated (region + schema_version
  + `min_group_n` k-anon eşiği + `containment_target` + `denominator_basis`)
- `samples/` — `containment-happy-path` (2 sürüm grubu, oran yayımlanır) · `containment-degraded-input`
  (küçük grup bastırılır + replay daraltılır — yine GEÇER) · `containment-degraded` (bilinçli bozuk, çoklu kapı eler)
- `tests/containment_report_behavior_test.py` — T1–T11 davranış kapısı
- `run_live_test.sh` — statik kapı + sample; `${CONTAINMENT_URL}` varsa canlı not, yoksa SKIP

## Çalıştırma

```bash
python3 containment_report_probe.py validate              # 98/98 PASS
python3 containment_report_probe.py selftest               # 46/46 PASS
python3 tests/containment_report_behavior_test.py          # 21/21 PASS
python3 containment_report_probe.py report samples/containment-happy-path.json
./run_live_test.sh
```

## Kapsam ayrımı

per-call intent/outcome/disposition/completion **ÇIKARIMI** → 14.2.2 (bu motorun **girdisini** üretir) ·
otomatik kalite skoru → 14.2.1 · yanlış-bilgi/tool-hata/güvenlik **İŞARETİ** → 14.2.4 · kritik işaretleme →
14.2.5 · QA **MANUEL** skor → 14.2.6 · sürüm karşılaştırma → 14.2.7 · dashboard/export → 14.2.8.
Burada **yalnız** containment/transfer **ORAN** agregasyonu + partisyon/payda bütünlüğü.
**Sır/credential, ham ses payload, transkript METNİ, PII DEĞERİ repoya yazılmaz.**
