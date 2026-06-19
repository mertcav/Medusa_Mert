# A-15 — Maliyet & Kaynak Tüketimi (WBS 13.4.15)

**Katman:** L2 — Operasyon / Uygulama Paneli · **Plane:** tenant_application_plane · **Faz:** F2 · **Öncelik:** Must

BRD §17.5'teki **A-15 "Maliyet & Kaynak Tüketimi — Operasyonel maliyet ve çağrı başı kaynak görünümü"** ekranı.
Bir DÖNEM boyunca ÇOK ÇAĞRIYI TOPLULAŞTIRAN operasyonel **maliyet** + lean-runtime **kaynak** panosu. A-14 (Analytics)
kalite/operasyon analitiğini gösterirken, A-15 maliyeti (FR-ANA-007) ve çağrı başı kaynak tüketimini (FR-ANA-013) gösterir.

## İçerik (6 bölüm)
1. **Özet maliyet KPI'ları** — toplam maliyet · çağrı başına maliyet · çözülen çağrı başına maliyet (§18.1) · dakika
   başına maliyet (§18.2) · çağrı başı CPU/bellek P95 · worker density.
2. **Maliyet dağılımı** (FR-ANA-007) — bileşen/sağlayıcı bazında: STT / LLM / TTS / telekom / compute; tutar + pay (Σ = %100).
3. **Agent bazında maliyet** (FR-ANA-007) — agent / çağrı / tutar / pay / çağrı başı (toplam = dönem; uzlaşır).
4. **Çağrı başına kaynak tüketimi** (FR-ANA-013) — CPU/bellek P50/P95 + bütçe; eşzamanlılık = worker density (≤15MB bütçe, ≥250 density).
5. **Verimlilik & lean-runtime** (NFR 10.2 / §18.2) — density · TTS cache hit (FR-TTS-010) · küçük-model tur oranı (SR-DEN-005) · boşta geri kazanım (FR-RES-014).
6. **Zaman serisi & trend** (FR-ANA-011) — günlük maliyet / çağrı başı maliyet / CPU / bellek; ilk yarı vs ikinci yarı trendi.

Ham veri **export** (FR-ANA-011) görsel kapıdır; nihai export + redaction + audit backend'de (`cost:read`).
Maliyet değerleri **illüstratif mühendislik örneğidir**; gerçek rate-card finans/billing motorundan (Cost/Resource Meter, SAD §13.3) beslenir.

## Para birimi — tam aritmetik
Tüm maliyetler **MINOR birim (kuruş/cent) TAM SAYI** olarak tutulur (`amountMinor`); Σ bileşen = toplam **tam eşitlik**
(float drift yok). Görüntülemede `minor/100 → formatCurrency` (locale-duyarlı). Maliyet/kaynak **sayıları** redaction
taramasına girmez (yalnız string değerler taranır); agregat tutarların büyüklüğü PII desenini tetiklemez.

## Hijyen (Tier A — agregat)
A-15 yalnız **topluluk maliyet/kaynak metriği** gösterir → break-glass GEREKMEZ; tek çağrı içeriği/transkript/PII TAŞIMAZ.
**İKİ KATMAN guard** (`assertSafe`):
- **Katman 1** (`assertNoForbiddenKeys`) — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni/e164/
  müşteri/kart-OTP) + **tek-çağrı `callRef`** + sır/credential/nesne-depo URI alan ADI yasak (BRD §17.7 / NFR 10.6).
- **Katman 2** (`assertRedactionClean`) — hiçbir string değer ham PII DESENİ (≥7 rakam/e-posta/+telefon/kart/IBAN) taşıyamaz (FR-REC-004/005).

## Türetilebilirlik invariant'ları (test çekirdeği)
- `totalCostMinor = Σ bileşen` · `agentCostReconciles` (Σ agent = toplam) · `agentCallsReconcile` (Σ agent çağrı = totalCalls) — FR-ANA-007.
- `costPerCallMinor = total/calls` · `costPerResolvedMinor = total/resolved` (§18.1) · `costPerMinuteMinor = total/minutes` (§18.2).
- `memWithinBudget`/`cpuWithinBudget`: per-call P95 ≤ bütçe · `densityMeetsTarget`: density ≥ 250 — FR-ANA-013 / FR-RES-016 / NFR 10.2.
- `resourcePercentilesConsistent`: P95 ≥ P50 (veri hatası yakalanır).
- `seriesReconcilesCost`/`seriesReconcilesCalls`: Σ seri = dönem total — FR-ANA-011.

## Dosyalar
| Dosya | Açıklama |
|------|----------|
| `app/(workspace)/workspace/cost/page.tsx` | A-15 ekranı (6 bölüm, i18n, design tokens, formatCurrency). |
| `lib/tenant/cost.ts` | Veri seam + saf türetme yardımcıları + İKİ KATMAN guard + tipler + placeholder view. |
| `lib/i18n/{tr,en}.json` | `screen.a15.*` blokları (TR↔EN birebir). |
| `a15-cost-spec.json` | Kaynak doğruluk + invariant S1..S8 + referans anahtar + placeholder + eşikler. |
| `a15_cost_probe.py` | stdlib-only probe (`validate`/`check`/`selftest`/`schema`) — cost.ts Python aynası. |
| `samples/cost-{healthy,degraded}.json` | `$expect`'li sentetik sağlıklı + bozulmuş dönem (FR-TST-008). |
| `tests/a15_cost_test.py` | Üç kapının çıkış-kodu davranış testi. |
| `run_live_test.sh` | Canlı smoke (next build+start+curl; credential-free). |

## Çalıştırma
```bash
python3 a15_cost_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a15_cost_probe.py check      # saf çekirdek + samples/*
python3 a15_cost_probe.py validate   # on-disk S1..S8 (sayfa + seam + i18n + spec)
python3 tests/a15_cost_test.py       # üç kapı exit 0
bash run_live_test.sh                 # canlı smoke (opsiyonel; next gerektirir)
```

## RBAC (BRD §17.6 A-15)
operations_manager=**Görüntüle** · conversation_designer=— · qa_analyst=— · human_agent=— (erişim yok).
tenant_owner kural 17.7 ile Yönet. Permission-key: `cost:read` (SAD §13.3 — operations_manager seti).
UI yalnız görsel kapı; nihai yetki backend + RLS.

## Kapsam dışı (bilinçli)
- Cost/Resource Meter (SAD §13.3) + gözlemlenebilirlik omurgası (0.4.7) ÜRETİMİ → F1 §14.1 (ekran yalnız sonucu yansıtır); per-call ölçüm hattı → WBS 14.1.3 (FR-ANA-013).
- Gerçek ham veri export + redaction + audit → API §8.1 `cost:read` (görsel kapı).
- Faturalandırma & plan & bütçe alarmı & fatura aktarımı → **T-07** (L1; FR-BIL-001..007) ve **P-05** (L0 platform faturalandırma).
- Kalite/containment/CSAT analitiği → **A-14**; tek çağrı QA skoru → **A-13**; çağrı detayı → **A-12**.
- Dönem/filtre seçici etkileşimi (date-range picker) → F1 (sunucu-tarafı sorgu parametreleri).
