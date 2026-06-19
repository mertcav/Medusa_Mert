# A-16 — Test & Simulation Centre (WBS 13.4.16)

**Katman:** L2 — Operasyon / Uygulama Paneli · **Plane:** tenant_application_plane · **Faz:** F1 · **Öncelik:** Must

BRD §17.5'teki **A-16 "Test & Simulation Centre — Tarayıcı testi, persona/senaryo simülasyonu, yük testi"** ekranı.
Bir agent **aday sürümünün** (candidateVersion) yayın öncesi test/simülasyon panosu: kategori bazında suite kırılımı,
sentetik persona/senaryo sonuçları, baseline sürüme karşı regresyon, production **promotion gate** ve **yük testi**.
**A-17** (Sürüm Geçmişi + rollback) bu gate'in çıktısına dayanır; promote regresyon/gate geçmeden production'a engellenir.

## İçerik (6 bölüm)
1. **Özet KPI'ları** — promotion gate · genel geçme oranı · ortalama skor · senaryo adedi · yük eş zamanlılığı · yük altı çağrı başı bellek P95.
2. **Suite / kategori kırılımı** (FR-TST-003/007) — happy / edge / adversarial / **robustness** (gürültü/aksan/kesinti/düşük hat); toplam/geçen/kalan/bloke + geçme oranı.
3. **Senaryo sonuçları** (FR-TST-001/002) — tarayıcı testi + persona simülasyonu; senaryo/kategori/persona/durum/skor/tur/gecikme. Tümü **sentetik** (FR-TST-008).
4. **Regresyon** (FR-TST-004 / FR-ANA-010) — aday vs baseline skor; kategori/baseline/aday/delta/durum.
5. **Promotion gate** (FR-TST-005) — geçti/engelli + engelleyici kapı listesi (pass_rate / score / regression / adversarial / load_resource).
6. **Yük testi** (FR-TST-006/009) — eş zamanlı çağrı + CPS + başarı oranı + yük altı çağrı başı CPU/bellek + baseline regresyonu.

Koşu/promote **derin aksiyondur** (`test:run` / `agent:version:manage`); nihai çalıştırma + yetki + audit backend'de (API §8.1).
Skor/gecikme/kaynak değerleri **illüstratif mühendislik örneğidir**; gerçek koşu Test & Simulation motoru + yük test ortamından (0.4.8) beslenir.

## Promotion gate (FR-TST-005)
Gate `pass` ⇔ **hiçbir blocker yok**. Blocker kümesi (deterministik sıra):
- `pass_rate` — genel geçme oranı < `gateMinPassRate` (0.85)
- `score` — ortalama skor < `gateMinScore` (0.8)
- `regression` — herhangi kategoride aday-baseline düşüşü toleransı (0.05) aşar (FR-TST-004)
- `adversarial` — bir adversarial senaryo başarısız (kritik; jailbreak/PII çıkarma)
- `load_resource` — yük altı çağrı başı CPU/bellek baseline'ı toleransı (%10) aşar (FR-TST-009)

## Hijyen (Tier A — sentetik)
A-16 yalnız **sentetik test/simülasyon metriği** gösterir → break-glass GEREKMEZ; gerçek çağrı içeriği/transkript/PII TAŞIMAZ (FR-TST-008).
Persona bir **sentetik etikettir** (gerçek müşteri değildir). **İKİ KATMAN guard** (`assertSafe`):
- **Katman 1** (`assertNoForbiddenKeys`) — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni/e164/
  müşteri/kart-OTP) + **gerçek-çağrı `callRef`** + sır/credential/nesne-depo URI alan ADI yasak (BRD §17.7 / NFR 10.6).
- **Katman 2** (`assertRedactionClean`) — hiçbir string değer (persona dahil) ham PII DESENİ (≥7 rakam/e-posta/+telefon/kart/IBAN) taşıyamaz (FR-REC-004/005).

## Türetilebilirlik invariant'ları (test çekirdeği)
- `suiteTotalsReconcile` (Σ suite.total = senaryo adedi + suite.total = kategori sayımı) · `suiteStatusReconcile` (passed/failed/blocked = kategori durum sayımı) — FR-TST-003.
- `overallPassRate = pass/total` · `meanScore = Σ score/total`.
- `regressionCurrentReconciles` (currentScore ≈ kategori senaryo ortalaması) — FR-ANA-010.
- `hasRegression` (currentScore-baselineScore < -tolerans) — FR-TST-004.
- `loadResourceRegression` (cpu/mem baseline'ı tolerans üstünde aşar) — FR-TST-009.
- `gateState = pass ⇔ gateBlockers boş` — FR-TST-005.

## Dosyalar
| Dosya | Açıklama |
|------|----------|
| `app/(workspace)/workspace/test/page.tsx` | A-16 ekranı (6 bölüm, i18n, design tokens, formatNumber). |
| `lib/tenant/test-sim.ts` | Veri seam + saf türetme yardımcıları + İKİ KATMAN guard + tipler + placeholder view. |
| `lib/i18n/{tr,en}.json` | `screen.a16.*` blokları (TR↔EN birebir). |
| `a16-test-sim-spec.json` | Kaynak doğruluk + invariant S1..S8 + referans anahtar + placeholder + eşikler. |
| `a16_test_sim_probe.py` | stdlib-only probe (`validate`/`check`/`selftest`/`schema`) — test-sim.ts Python aynası. |
| `samples/test-{healthy,degraded}.json` | `$expect`'li sentetik geçen + engelli koşu (FR-TST-008). |
| `tests/a16_test_sim_test.py` | Üç kapının çıkış-kodu davranış testi. |
| `run_live_test.sh` | Canlı smoke (next build+start+curl; credential-free). |

## Çalıştırma
```bash
python3 a16_test_sim_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a16_test_sim_probe.py check      # saf çekirdek + samples/*
python3 a16_test_sim_probe.py validate   # on-disk S1..S8 (sayfa + seam + i18n + spec)
python3 tests/a16_test_sim_test.py       # üç kapı exit 0
bash run_live_test.sh                     # canlı smoke (opsiyonel; next gerektirir)
```

## RBAC (BRD §17.6 A-16)
operations_manager=**Düzenle** · conversation_designer=**Yönet** · qa_analyst=**Görüntüle** · human_agent=— (erişim yok).
tenant_owner kural 17.7 ile Yönet. Permission-key: `test:run` (API §8.1); promote `agent:version:manage`.
UI yalnız görsel kapı; nihai yetki backend + RLS.

## Kapsam dışı (bilinçli)
- Test & Simulation motoru + yük test ortamı (0.4.8) + persona/senaryo üreteci ÜRETİMİ → F1 §14.1 / FR-TST-006/009 (ekran yalnız sonucu yansıtır).
- Gerçek koşu tetikleme + promote işlemi + audit → API §8.1 `test:run` / `agent:version:manage` (görsel kapı).
- Sürüm geçmişi + rollback → **A-17** (FR-AGT-006); agent yapılandırma → **A-04/A-05/A-06/A-07**.
- Yük/kapasite simülasyon iskeleti (sistem-seviyesi) → `docs/platform/load-testing/` (0.4.8); bu ekran tenant-görünür özetidir.
- Senaryo/persona düzenleyici etkileşimi (test kütüphanesi CRUD) → F1 (sunucu-tarafı).
