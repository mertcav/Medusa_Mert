# tools/critical-workflow — Kritik İşlem Workflow Durum Makinesi (WBS 7.3.1)

`tools/` workstream'inin **7.3 Deterministic workflow engine** bölümünün ilk modülü. BRD §13 kritik
işlem 6-adımını (**auth→kural→özet→teyit→onay→audit**) deterministik bir durum makinesi olarak gerçekler.

## Dosyalar

| Dosya | Rol |
|-------|-----|
| `critical-workflow-spec.json` | Makine-okunur kaynak doğruluk: durumlar/geçişler, auth seviyeleri, kural değerlendirme, olaylar, sonuçlar, K1–K12 invariant, audit no-log |
| `critical-workflow.md` | Tasarım: durum makinesi, kurallı workflow, invariant'lar, sorumluluk sınırı |
| `critical_workflow_probe.py` | stdlib-only FSM-yürütücü: `validate` / `run <sample>` / `selftest` / `schema` |
| `config/workflow-policies.json` | BRD §13 listesi → `risk_class` → etkin kapı seti (kural tablosu) |
| `samples/*.json` | Sentetik senaryolar (FR-TST-008): her terminal sonuç + degraded |
| `tests/critical_workflow_behavior_test.py` | Bağımsız davranış kapısı (T1–T16) |
| `run_live_test.sh` | Statik + selftest + behavior + sample kapısı (credential-free) |

## Hızlı başlangıç

```bash
cd tools/critical-workflow
python3 critical_workflow_probe.py validate     # 72/72 🟢
python3 critical_workflow_probe.py selftest     # 36/36 🟢
python3 critical_workflow_probe.py run samples/happy-bank-account-committed.json
./run_live_test.sh                              # tüm kapılar
```

## Çekirdek invariant

> **BRD §13 + SR-TOOL-006/007:** her gerekli kapı geçilmeden EXECUTE'a ulaşılamaz (K1 fail-closed);
> teyit alınmadan kritik işlem yürütülmez (K5); para/sözleşme/PII → step-up zorunlu (K7); gerekli insan
> onayı maker-checker (talep≠onay) gelmeden yürütülmez (K6); her terminal sonuç değiştirilemez audit'e
> yazılır (K10).

## Kapsam dışı (başka modül sahibi)

auth mekanizması → 8.x · teyit/ek-doğrulama ayrıntısı → 7.3.2 · tool dispatch → 7.2.x ·
idempotency/allowlist/schema → 7.1.x/7.2.3 · müşteri hata metni → 7.1.5 · audit store → 7.1.6/12.1.8 ·
maker-checker UI → 12.1.7 · output guard → 3.3.x.

Vendor-neutral (ADR-001/002); sır/credential ve gerçek PII repoya yazılmaz.
→ `reports/7.3.1-kritik-islem-workflow-durum-makinesi-raporu.md`
