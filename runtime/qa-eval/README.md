# runtime/qa-eval — WBS 14.2.1 Otomatik kalite değerlendirme (tüm çağrılar)

> `F2` · `Must` · →**FR-ANA-001** · SR-ANA-001 (A) · TC-ANA-001

Analytics/Ops Plane'deki (SAD §4.2, async batch — ADR-004/ADR-007) **QA/Eval Engine** (SAD §164).
Çağrı bittikten sonra event stream üzerinden (`qa.evaluation.v1`, WBS 1.1.8) **PII-redaksiyonlu**
içerikle çalışır, **TÜM uygun çağrılara** (FR-ANA-001; SR-ANA-001 **%100 kapsam**) deterministik bir
kalite-skorkartı (rubric) uygular ve sonucu `call_evaluation` (DB.md §5.6, `eval_type='automatic'`) +
OLAP `fct_qa_evaluation` ile **BİREBİR** alanlarla yayımlar (`qa.evaluation.completed`).

**BİRİNCİL HARD kapı = %100 kapsam** — her uygun tamamlanmış çağrı tam olarak bir otomatik
değerlendirme alır (`coverage_gap=0`). Kötü kalite ≠ değerlendirme atlama; öznitelik eksik çağrı yine
`degraded` olarak değerlendirilir (sessizce atlanmaz, aksi halde %100 bozulur).

## Skorkart (rubric — vendor-neutral, deterministik)

| Boyut | Ağırlık | OLAP sütunu | Yöntem |
|-------|---------|-------------|--------|
| accuracy | 0.35 | `score_accuracy` | groundedness = grounded/total (FR-KB-006/007) |
| compliance | 0.35 | `score_compliance` | 1.0 − disclosure(0.5) − consent(0.3) − 0.2·policy_violations (BRD §14.2) |
| helpfulness | 0.30 | `score_helpfulness` | resolution(1.0/0.6/0.2) − dead_air − barge_in penalty (FR-ANA-005) |

`auto_score` = Σ ağırlık·boyut (ağırlık toplamı 1.0). Tüm skorlar `[0,1]`. İsteğe bağlı LLM-judge
canlıda bu deterministik zarfın ardına takılabilir (ADR-002); skor zarfı + kapılar değişmez.

## HARD kapılar (G1–G8)

- **G1 kapsam (BİRİNCİL):** üretilen == uygun (%100; FR-ANA-001/SR-ANA-001)
- **G2 katalog:** çıktı skor alanları OLAP `fct_qa_evaluation` `auto_score`+`score_*` ile BİREBİR (non-circular)
- **G3 skor-alanı:** her boyut + composite ∈ [0,1]; ağırlık toplamı=1.0; composite=ağırlıklı toplam
- **G4 idempotent:** `(tenant_id,call_id,schema_version)` daraltılır; at-least-once çift skor üretmez (1.1.8 P3)
- **G5 async:** analytics plane non-blocking; QA başarısızlığı canlı çağrıyı etkilemez (FR-RES-011)
- **G6 PII:** yalnız redaksiyonlu öznitelik; ham transkript/ses/PII DEĞERİ yok (FR-REC-004)
- **G7 izolasyon:** her değerlendirme `tenant_id` + cross-tenant yok + residency (FR-TEN-002/NFR 10.7)
- **G8 uygunluk:** uygun-olmayan statü açık `reason_code` taşır (sessiz atlama yok)

## Dosyalar

- `qa-eval-spec.json` — makine-okunur kaynak doğruluk (placement, coverage, eligibility, rubric, output_contract, idempotency, feature_policy, isolation, gates, invariants I1–I12)
- `qa_eval_probe.py` — stdlib-only `validate` / `evaluate <sample>` / `selftest` / `schema`
- `config/qa-eval-profiles.json` — deployment profilleri (eu/tr-standard + regulated-dedicated; region + schema_version)
- `samples/` — `qa-happy-path` (3 uygun→3 değerlendirme) · `qa-degraded-input` (degraded yine değerlendirilir) · `qa-degraded` (bilinçli bozuk, çoklu kapı eler)
- `tests/qa_eval_behavior_test.py` — T1–T10 davranış kapısı
- `run_live_test.sh` — statik kapı + sample; `${QA_EVAL_URL}` varsa canlı not, yoksa SKIP

## Çalıştırma

```bash
python3 qa_eval_probe.py validate     # 84/84 PASS
python3 qa_eval_probe.py selftest      # 55/55 PASS
python3 tests/qa_eval_behavior_test.py # 18/18 PASS
python3 qa_eval_probe.py evaluate samples/qa-happy-path.json
./run_live_test.sh
```

## Kapsam ayrımı

intent/disposition/completion → 14.2.2 · containment/transfer oranı → 14.2.3 · yanlış-bilgi/tool-hata/
güvenlik **İŞARETİ** → 14.2.4 · kritik konuşma işaretleme → 14.2.5 · QA **MANUEL** skor+yorum → 14.2.6 ·
agent sürüm karşılaştırma → 14.2.7 · dashboard/export → 14.2.8. Burada **yalnız** otomatik skorkart
motoru + %100 kapsam. **Sır/credential, ham ses payload, transkript METNİ, PII DEĞERİ repoya yazılmaz.**
