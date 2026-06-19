# runtime/manual-qa-scoring — WBS 14.2.6 QA manuel skor + açıklama

> `F2` · `Must` · →**FR-ANA-009** · SR-ANA-009 (D) · TC-ANA-009

Analytics/Ops Plane'deki (SAD §4.2, async; ADR-004/ADR-007) **L2 panel write** yüzeyi (SAD §14.4 — A-14
Analytics). Yetkili bir QA ekibi üyesi (`qa:score` izni; FR-IAM-011/ADR-012) tamamlanmış bir çağrıya
**insan skoru** (`human_score`, 1–5) + serbest-metin **açıklama** (comment) ekler (FR-ANA-009).
`call_evaluation`'a (`eval_type='manual'`; DB.md §5.6: `scores` JSONB + `evaluator_id` + `comment` +
`created_at`) yazar; OLAP `fct_qa_evaluation`'a **yalnız** `human_score` ([0,1] normalize) +
`human_comment_present` (u8_bool — **METİN DEĞİL**) + `evaluator_role` projekte eder.

**BİRİNCİL HARD kapı = YETKİLENDİRME** — yalnız `qa:score` izni olan submitter manuel skor ekler; yetkisiz
reddedilir (`AUTH`); karar **her zaman backend'de**. **KEY invariant:** açıklama METNİ tenant düzleminde
(`call_evaluation.comment`, RLS) kalır; OLAP/platforma/event payload'una/spec'e **asla çıkmaz** (FR-REC-004;
altın kural FR-IAM-008). Otomatik skordan (14.2.1, `eval_type='automatic'`) **ayrı** — overwrite yok, COEXIST.

## Skor & açıklama (FR-ANA-009)

| Alan | Domain | OLAP sütunu | Not |
|------|--------|-------------|-----|
| `human_score` | ordinal 1–5 (zorunlu) | `human_score` (f32) | `(score−1)/4` → [0,1] normalize |
| `comment` | serbest-metin (opsiyonel) | `human_comment_present` (u8_bool) | **METİN tenant düzleminde; OLAP yalnız VARLIK** |
| `evaluator_role` | düşük-kardinalite | `evaluator_role` (string_lc) | qa_analyst / operations_manager / tenant_owner |

`human_score` **zorunlu** (FR-ANA-009 "skor"); açıklama opsiyonel ama desteklenir ("ve açıklama"); en
azından skor olmalı (boş submission reddedilir). İsteğe bağlı `dimension_scores` (accuracy/compliance/
helpfulness — 14.2.1 rubric boyutlarıyla hizalı) `scores` JSONB'de tutulabilir; OLAP yalnız composite taşır.

## HARD kapılar (G1–G10)

- **G1 yetki (BİRİNCİL):** yalnız `qa:score` izni olan submitter ekler; yetkisiz/L0/cross-tenant → `AUTH` (FR-ANA-009/FR-IAM-011/altın kural)
- **G2 zorunlu:** `evaluator_id` + `human_score` taşımalı; skorsuz/boş → `INVALID_REQUEST`
- **G3 skor-domain:** `human_score ∈ [1,5]`; OLAP'a [0,1] normalize; domain dışı → red
- **G4 katalog/eval_type:** `eval_type='manual'`; OLAP çıktı alanları `human_score`+`human_comment_present`+`evaluator_role` ile **BİREBİR** (non-circular)
- **G5 PII (KEY):** açıklama METNİ yalnız tenant düzleminde; OLAP/event/spec yalnız VARLIK+rol; ham metin/PII **asla** sızmaz (FR-REC-004)
- **G6 izolasyon:** evaluator ile çağrı aynı `tenant_id`; cross-tenant red; home-region (FR-TEN-002/NFR 10.7)
- **G7 audit:** her kabul KAYIPSIZ `governance.audit.v1` (`manual_score_added`) WORM izi; append-only (sessiz overwrite yok)
- **G8 idempotent/sürümlü:** `(tenant_id,call_id,evaluator_id,schema_version)` sürümler; farklı evaluator ayrı skor; at-least-once çift-sayım yok
- **G9 async:** analytics plane non-blocking; skorlama başarısızlığı canlı çağrıyı etkilemez (FR-RES-011)
- **G10 uygunluk:** yalnız `completed` skorlanır; uygun-olmayan açık `reason_code` taşır (sessiz reddetme yok)

## Dosyalar

- `manual-qa-scoring-spec.json` — makine-okunur kaynak doğruluk (placement, authorization, scoring, comment_policy, output_contract, coexistence, audit, idempotency, isolation, eligibility, gates, invariants I1–I14)
- `manual_qa_probe.py` — stdlib-only `validate` / `score <sample>` / `selftest` / `schema`
- `config/manual-qa-profiles.json` — deployment profilleri (eu/tr-standard + regulated-dedicated; region + schema_version + `require_comment` yalnız-sıkılaştırır)
- `samples/` — `manual-qa-happy-path` (4 yetkili kabul) · `manual-qa-degraded-input` (kısmi ama geçerli; çoklu manuel/çağrı) · `manual-qa-degraded` (bilinçli bozuk, 7 red: yetkisiz/L0/cross-tenant/skorsuz/domain/METİN-sızıntı/uygun-değil)
- `tests/manual_qa_behavior_test.py` — T1–T12 davranış kapısı
- `run_live_test.sh` — statik kapı + sample; `${MANUAL_QA_URL}` varsa canlı not, yoksa SKIP

## Çalıştırma

```bash
python3 manual_qa_probe.py validate     # 98/98 PASS
python3 manual_qa_probe.py selftest      # 16/16 PASS
python3 tests/manual_qa_behavior_test.py # 16/16 PASS
python3 manual_qa_probe.py score samples/manual-qa-happy-path.json
./run_live_test.sh
```

## Kapsam ayrımı

otomatik kalite SKORU → 14.2.1 · intent/disposition/completion ÇIKARIMI → 14.2.2 · containment/transfer
ORANI → 14.2.3 · yanlış-bilgi/tool-hata/güvenlik İŞARETİ → 14.2.4 · KRİTİK işaretleme → 14.2.5 · agent
sürüm KARŞILAŞTIRMA → 14.2.7 · dashboard/export → 14.2.8. Burada **yalnız** insan QA skoru + açıklama ekleme
yüzeyi + yetki/izolasyon/PII-sınır/audit kapıları. **Sır/credential, ham ses payload, transkript METNİ,
AÇIKLAMA METNİ, PII DEĞERİ repoya yazılmaz.**
