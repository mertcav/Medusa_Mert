# runtime/issue-detection — WBS 14.2.4 Yanlış bilgi/tool hatası/güvenlik ihlali tespiti

> `F2` · `Must` · →**FR-ANA-004** · SR-ANA-004 (**T**) · TC-ANA-004

Analytics/Ops Plane'deki (SAD §4.2, async batch — ADR-004/ADR-007) **tespit (detection) motoru**.
Çağrı bittikten sonra event stream üzerinden gelen **PII-redaksiyonlu** sinyalden
(`qa.evaluation.v1` [FR-ANA-004] + `ops.tool.execution.v1` [tool status, FR-TOOL-009] +
`governance.audit.v1` [policy/güvenlik olayları]) **HER uygun çağrı** için **ÜÇ** kategorik ikili işaret
türetir ve OLAP `fct_call` + `fct_qa_evaluation` `flag_*` sütunlarına (FR-ANA-004, `pii_class low`) +
`call_evaluation.flags` JSONB'ye (DB.md §5.6) yazar:

| Kategori | OLAP/DB işareti | Kapalı-sözlük reason_code |
|----------|-----------------|---------------------------|
| `misinformation` | `flag_misinformation` | `ungrounded_answer` · `kb_contradiction` · `unverified_commitment` |
| `tool_error` | `flag_tool_error` | `tool_call_failed` · `tool_call_timeout` · `provider_error` |
| `security_violation` | `flag_security` | `pii_disclosure` · `prompt_injection` · `jailbreak` · `unauthorized_action` · `policy_violation` |

Vendor-neutral (ADR-002), credential-free, stdlib-only, **deterministik** (saf eşik kuralı; random YOK).
Bu motor **İŞARET** üretir (FR-ANA-004); **kritik** işaretleme (`flag_critical`, FR-ANA-008→**14.2.5**) bu
işaretleri **TÜKETİR** (kapsam ayrımı).

## Çekirdek karar — yöntem T (test): tespit doğruluğu

SR-ANA-004 doğrulama yöntemi **T**: *"Enjekte edilen hata vakaları tespit edilir."* Etiketli test setinde her
çağrı `injected` **yer-doğrusu** (ground-truth) taşır; motor sinyalden işaret üretir, kapı motor işaretini
etikete karşı karşılaştırır:

- **BİRİNCİL — G1 recall:** enjekte edilen (`injected[cat]=true`) **HER** pozitif vaka tespit edilmeli →
  `missed_detection = 0` (yanlış-negatif yok).
- **G2 precision:** enjekte-temiz (`injected[cat]=false`) vakada işaret fires **olmamalı** →
  `false_positive = 0`.

`injected` taşımayan üretim çağrısı için işaret yine üretilir ama recall/precision'a katılmaz.

## HARD kapılar (G1–G9)

- **G1 recall (BİRİNCİL):** enjekte edilen her pozitif vaka tespit edilir (`missed_detection=0`) — SR-ANA-004 T.
- **G2 precision:** enjekte-temizde sahte işaret yok (`false_positive=0`).
- **G3 tutarlılık:** kategori işareti fires=true **⟺** o kategoride ≥1 reason_code tetiklendi (boş-reason/yetim reason yok).
- **G4 sözlük (BİREBİR):** kategori `{misinformation, tool_error, security_violation}` + reason_code kapalı-sözlük;
  `flag_column` → OLAP `fct_call`/`fct_qa_evaluation` `flag_*` (FR-ANA-004) ile birebir (non-circular cross-check).
- **G5 kapsam:** HER uygun çağrı **ÜÇ** kategoride değerlendirilir (`produced == eligible × 3`); tespit-yok ≠ atlama.
- **G6 idempotent:** `(tenant_id, call_id, schema_version)` bir kez; at-least-once replay çift-üretmez (1.1.8 P3).
- **G7 izolasyon:** her değerlendirme tek `tenant_id` + cross-tenant yok + residency (FR-TEN-002/NFR 10.7).
- **G8 PII:** yalnız redaksiyonlu sinyal + düşük-kardinalite boyut; çıktı PII/serbest-metin reason taşımaz (FR-REC-004).
- **G9 async:** analytics plane non-blocking; tespit başarısızlığı canlı çağrıyı etkilemez (FR-RES-011).

## Dosyalar

- `detection-spec.json` — makine-okunur kaynak doğruluk (placement, categories, detection_rules, ground_truth,
  eligibility, coverage, consistency, output_contract, idempotency, feature_policy, isolation, gates, invariants I1–I15)
- `detection_probe.py` — stdlib-only `validate` / `detect <sample>` / `selftest` / `schema`
- `config/detection-profiles.json` — eu/tr-standard + regulated-dedicated (region + schema_version + `threshold_override`)
- `samples/` — `detection-happy-path` (4 enjekte pozitif tespit + 2 temiz, kapsam tam) · `detection-degraded-input`
  (in_progress dışlanır + replay daraltılır + multi-reason — yine **GEÇER**) · `detection-degraded` (bilinçli bozuk, G1/G5/G7 eler)
- `tests/detection_behavior_test.py` — T1–T11 davranış kapısı
- `run_live_test.sh` — statik kapı + sample; `${DETECTION_URL}` varsa canlı not, yoksa SKIP

## Çalıştırma

```bash
python3 detection_probe.py validate              # 150/150 PASS
python3 detection_probe.py selftest               # 45/45 PASS
python3 tests/detection_behavior_test.py          # 29/29 PASS
python3 detection_probe.py detect samples/detection-happy-path.json
./run_live_test.sh
```

## Kapsam ayrımı

otomatik kalite **SKORU** → 14.2.1 · per-call intent/outcome/disposition/completion **ÇIKARIMI** → 14.2.2 ·
containment/transfer **ORANI** → 14.2.3 · **KRİTİK** işaretleme (`flag_critical`, FR-ANA-008; bu motorun
işaretlerini **tüketir**) → 14.2.5 · QA **MANUEL** skor → 14.2.6 · sürüm karşılaştırma → 14.2.7 ·
dashboard/export → 14.2.8. Burada **yalnız** yanlış-bilgi/tool-hata/güvenlik **İŞARETİ** tespiti + tespit doğruluğu.
**Sır/credential, ham ses payload, transkript METNİ, PII DEĞERİ repoya yazılmaz.**
