# A-14 — Analytics & Raporlama (WBS 13.4.14)

**Katman:** L2 — Operasyon / Uygulama Paneli · **Plane:** tenant_application_plane · **Faz:** F1/F2 · **Öncelik:** Must

BRD §17.5'teki **A-14 "Analytics & Raporlama — Containment, CSAT, AHT vb."** ekranı. Bir DÖNEM boyunca ÇOK
ÇAĞRIYI TOPLULAŞTIRAN operasyonel analitik panosu (A-13 tek çağrının skorunu gösterirken A-14 dönem agregatını).

## İçerik (6 bölüm)
1. **Özet KPI'lar** — toplam çağrı · containment · transfer · CSAT · AHT · toplam yanıt gecikmesi P95.
2. **Sonuç dağılımı** (FR-ANA-002/003) — contained/transferred/abandoned/voicemail/failed; sayı + oran (Σ oran = %100).
3. **Konuşma süreleri** (FR-ANA-005) — kullanıcı / agent / sessizlik + AHT; agent konuşma payı.
4. **Yanıt gecikmesi** (FR-ANA-006) — STT / LLM / TTS + toplam; P50/P95 **AYRI** gösterilir; bütçe ≤1200ms (NFR 10.1).
5. **Zaman serisi & trend** (FR-ANA-011) — günlük containment / CSAT / hacim; ilk yarı vs ikinci yarı trendi.
6. **Agent sürümü karşılaştırması** (FR-ANA-010) — sürüm / çağrı / containment / Δ ağırlıklı ort. / CSAT / AHT.

Ham veri **export** (FR-ANA-011) görsel kapıdır; nihai export + redaction + audit backend'de (`analytics:read`).

## Hijyen (Tier A — agregat)
A-14 yalnız **topluluk metriği** gösterir → break-glass GEREKMEZ; tek çağrı içeriği/transkript/PII TAŞIMAZ.
**İKİ KATMAN guard** (`assertSafe`):
- **Katman 1** (`assertNoForbiddenKeys`) — ham kimlik/iş-içeriği (ham ses/ham transkript blob/transkript metni/
  e164/müşteri/kart-OTP) + **tek-çağrı `callRef`** + sır/credential/nesne-depo URI alan ADI yasak (BRD §17.7 / NFR 10.6).
- **Katman 2** (`assertRedactionClean`) — hiçbir string değer ham PII DESENİ (≥7 rakam/e-posta/+telefon/kart/IBAN)
  taşıyamaz (FR-REC-004/005).

## Türetilebilirlik invariant'ları (test çekirdeği)
- `containmentRate = contained/total` · `outcomeRatesSumToOne` (Σ oran ≈ 1) — FR-ANA-002/003.
- `ahtConsistent`: saklanan AHT ≈ çağrı başına konuşma süresi — FR-ANA-005.
- `latencyChainConsistent`: toplam ≥ STT/LLM/TTS · `latencyWithinBudget`: toplam P95 ≤ bütçe — FR-ANA-006 / NFR 10.1.
- `seriesReconciles`: Σ seri çağrı = dönem total — FR-ANA-011.
- `versionContainmentDelta`: sürüm − ağırlıklı agent ortalaması — FR-ANA-010.

## Dosyalar
| Dosya | Açıklama |
|------|----------|
| `app/(workspace)/workspace/analytics/page.tsx` | A-14 ekranı (6 bölüm, i18n, design tokens). |
| `lib/tenant/analytics.ts` | Veri seam + saf türetme yardımcıları + İKİ KATMAN guard + tipler + placeholder view. |
| `lib/i18n/{tr,en}.json` | `screen.a14.*` blokları (TR↔EN birebir). |
| `a14-analytics-spec.json` | Kaynak doğruluk + invariant S1..S8 + referans anahtar + placeholder + eşikler. |
| `a14_analytics_probe.py` | stdlib-only probe (`validate`/`check`/`selftest`/`schema`) — analytics.ts Python aynası. |
| `samples/analytics-{healthy,degraded}.json` | `$expect`'li sentetik sağlıklı + bozulmuş dönem (FR-TST-008). |
| `tests/a14_analytics_test.py` | Üç kapının çıkış-kodu davranış testi. |
| `run_live_test.sh` | Canlı smoke (next build+start+curl; credential-free). |

## Çalıştırma
```bash
python3 a14_analytics_probe.py selftest   # pozitif + negatif kendi-testleri
python3 a14_analytics_probe.py check      # saf çekirdek + samples/*
python3 a14_analytics_probe.py validate   # on-disk S1..S8 (sayfa + seam + i18n + spec)
python3 tests/a14_analytics_test.py       # üç kapı exit 0
bash run_live_test.sh                      # canlı smoke (opsiyonel; next gerektirir)
```

## RBAC (BRD §17.6 A-14)
operations_manager=Yönet · conversation_designer=Görüntüle · qa_analyst=Görüntüle · human_agent=— (erişim yok).
Permission-key: `analytics:read` (API §8.1 `GET /analytics/{report}`). UI yalnız görsel kapı; nihai yetki backend + RLS.

## Kapsam dışı (bilinçli)
- Analitik/aggregation motoru + gözlemlenebilirlik omurgası (0.4.7) ÜRETİMİ → F1 §14.1 (ekran yalnız sonucu yansıtır).
- Gerçek ham veri export + redaction + audit → API §8.1 `GET /analytics/{report}` (görsel kapı).
- Maliyet & çağrı başı kaynak tüketimi → **A-15** (FR-ANA-007/013).
- Tek çağrı QA skoru/işaret → **A-13**; çağrı detayı/transkript → **A-12**.
- Gerçek zamanlı operasyon ekranı (FR-ANA-012) → **A-02** Canlı Çağrılar.
- Dönem/filtre seçici etkileşimi (date-range picker) → F1 (sunucu-tarafı sorgu parametreleri).
