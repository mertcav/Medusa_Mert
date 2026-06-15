# `handoff/target-selection/` — WBS 9.5 Kuyruk/skill/departman bazlı hedef seçimi

9. workstream'in (İnsan Temsilciye Aktarım) **beşinci** modülü · **F2 · Must** · →**FR-TEL-008, FR-HND-003**.

Aktarım **hedef seçicisi**: 9.4'ün ürettiği transfer kararını alıp **nereye** (hangi departman / skill
grubu / kuyruk) yönlendirileceğine karar verir. SAD §7.3'teki `Handoff Manager ──► hedef seçimi
(departman/skill/kuyruk)` noktasıdır. Seçilen hedefi 9.1 (cold) / 9.2 (warm) / 9.3 (whisper) mekanizma
modülleri **taşıma** için tüketir; hedef bulunamazsa karar 9.7 temsilci-yok fallback'e **yükselir**.

## Dosyalar
| Yol | Açıklama |
|-----|----------|
| `target-selection-spec.json` | Makine-okunur **kaynak doğruluk**: durumlar, üç yönlendirme boyutu, fallback zinciri, öncelik modeli, kapılar, invariant R1–R11, izlenebilirlik |
| `target-selection.md` | Tasarım dokümanı (durum makinesi, üç boyut, fallback zinciri, öncelik, kapsam ayrımı) |
| `target_selection_probe.py` | Stdlib-only **deterministik hedef seçim motoru**: `validate`/`run`/`selftest`/`schema` |
| `config/routing-policies.json` | Kuyruk/skill_group/departman envanteri + intent→departman/skill + öncelik + fallback (credential-free) |
| `samples/*.json` | 6 pass + 6 degrade senaryo (sentetik, FR-TST-008) |
| `tests/target_selection_behavior_test.py` | Bağımsız kara-kutu davranış kapısı (R1–R10) |
| `run_live_test.sh` | Tüm statik + davranış kapılarını koşar |

## Hızlı çalıştırma
```bash
cd handoff/target-selection
./run_live_test.sh                               # tümü
python3 target_selection_probe.py validate       # statik kapı
python3 target_selection_probe.py run samples    # senaryolar
python3 target_selection_probe.py selftest       # gömülü kontroller
```

## Üç yönlendirme boyutu (FR-TEL-008)
1. `department` — iş birimi (intent→departman kuralı, FR-HND-003)
2. `skill_group` — yetkinlik grubu (gerekli dil/domain/tier skill'lerini kapsayan)
3. `queue` — bekleme kuyruğu (departman+skill_group eşlemesi)

## Fallback zinciri (sıra)
`exact` (skill+dil kapsayan, en sıkı) → `department_default` (skill gevşek, dil korunur) →
`general_fallback` (tenant genel catch-all). Hiçbiri yoksa → **UNRESOLVED → 9.7** (fail-safe).

## Öncelik
9.4 reason → öncelik: `ANGER`/`POLICY` → **high** (priority_capable kuyruk tercihi);
`USER_REQUEST`/`LOW_CONFIDENCE` → **normal**.

## Durum
validate **73/73** 🟢 · selftest **45/45** 🟢 · run **12/12** 🟢 (6 pass + 6 degrade beklendiği gibi
elendi) · behavior **24/24** 🟢. Vendor-neutral (ADR-001/002); sır/credential repoya yazılmaz; müşteri
adı/telefon/hesap no/ham transkript tutulmaz (R11). Canlı hedef seçim testi F2'de gerçek CC skill-based
routing + 9.1/9.2/9.3 ile koşar.

Rapor: [`reports/9.5-hedef-secimi-raporu.md`](../../reports/9.5-hedef-secimi-raporu.md)
