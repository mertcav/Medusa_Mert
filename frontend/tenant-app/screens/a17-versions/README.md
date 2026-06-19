# A-17 — Sürüm Geçmişi (agent) + rollback (WBS 13.4.17)

**Katman:** L2 — Operasyon / Uygulama Paneli · **Plane:** tenant_application_plane · **Faz:** F1 · **Öncelik:** Must · **İz:** →FR-AGT-006

BRD §17.5'teki **A-17 "Sürüm Geçmişi (agent) — Agent versiyonları ve rollback"** ekranı.
Bir agent'ın **yayın/sürüm geçmişi** panosu: aşamalı sürümler, bağlanan yapılandırma (prompt/flow/voice/model/stt
sürüm/profil **adları**), aktif (production) sürüm ve **tek-işlem geri alma (rollback)**. ÇEKİRDEK gereksinim
**FR-AGT-006**: yayınlanan sürüm tek işlemle önceki sürüme döndürülebilir. Geri alma backend'de **WORM append-only**
uygulanır (DB §6.5 — rollback = yeni sürüm satırı, eski satır korunur). Promotion gate detayı **A-16**'dadır;
A-17 sürüm META'sında o gate'in test sonucunu (FR-AGT-010) yansıtır.

## İçerik (4 bölüm)
1. **Özet KPI'ları** — sürüm sayısı · aktif sürüm · yayınlı · en son · geri çağrılabilir · bekleyen değişiklik · geri alma sayısı · açık dikkat.
2. **Sürüm geçmişi** (DB §5.2 `agent_version`) — sürüm no + kimliği + aşama + durum + test + bağlanan config + yayınlayan + yayın zamanı + değişiklik notu + **rollback kökeni** rozeti. Her sürüm değişmez (WORM).
3. **Aşama dağılımı** (FR-AGT-005) — draft/test/staging/production/archived sayımı.
4. **Rollback / Geri Alma** (FR-AGT-006) — aktif sürüm + **varsayılan tek-işlem hedefi** (önceki yayınlanmış sürüm) + geri çağrılabilir sürümler listesi (görsel kapı).

Geri al/promote/yeni-sürüm **derin aksiyondur** (`agent:version:manage` — API §8.1: `POST /agents/{id}/versions/{v}:rollback`/`:promote`); nihai çalıştırma + yetki + audit backend'de + RLS (SAD §14.4.1).
Sürüm/zaman/sayı değerleri **illüstratif mühendislik örneğidir**; gerçek veri Agent Registry (DB §5.2 `agent_version` + `agent.active_version_id`) tenant-scope (RLS) çıktısıyla beslenir.

## Rollback kapıları (FR-AGT-006)
- `recallableVersions` — geri çağrılabilir adaylar = **yayınlanmış ∧ aktif olmayan**.
- `previousPublishedVersion` — tek-işlem **varsayılan hedef** = aktiften düşük numaralı en yüksek yayınlı sürüm (aksi: en yüksek recallable). "Önceki sürüme dön" budur.
- `canRollback` — aktif sürüm var **∧** geri çağrılabilir sürüm var.
- `isRollback` / `rollbackCount` — bir sürüm `rollbackOfNo` ile bir önceki sürümü geri yüklediyse rollback ürünüdür (WORM köken izi).
- `rollbackRefsResolve` — her `rollbackOfNo` **mevcut ∧ daha düşük** numaralı bir sürümü işaret etmeli (append-only; ileriye/kendine rollback olamaz — DB §6.5).

## Hijyen (Tier A — sürüm META) + İKİ KATMAN guard (`assertSafe`)
A-17 yalnız **sürüm meta** gösterir → break-glass GEREKMEZ; ham çağrı içeriği/transkript/PII **ve** `agent_version`
snapshot JSONB **gövdesi** TAŞIMAZ.
- **Katman 1** (`assertNoForbiddenKeys`) — ham kimlik/iş-içeriği (transkript/ses kaydı/ham numara/müşteri/kart-OTP)
  + **snapshot/prompt/flow GÖVDESİ** (snapshot/promptText/flowDefinition/body) + sır/credential/nesne-depo URI alan ADI yasak (BRD §17.7 / NFR 10.6).
- **Katman 2** (`assertRedactionClean`) — hiçbir string değer ham PII DESENİ (≥7 rakam/e-posta/+telefon/kart/IBAN) taşıyamaz (FR-REC-004/005). Sürüm no/sayılar string değildir → taranmaz.

> NOT: `publishedBy`/`changeNote`/`agentName` tenant'ın KENDİ config'idir (L2'de izinli); `promptVersionNo`/profil adları yalnız SAYI/AD'dır (gövde değil).

## Türetilebilirlik invariant'ları (test çekirdeği)
- `sortedVersions` (versionNo AZALAN) · `activeVersion` (=`activeVersionNo`) · `latestVersion` (max).
- `versionStatus` (active/published/draft) · `countByStage` (FR-AGT-005).
- `recallableVersions`/`previousPublishedVersion`/`canRollback` (FR-AGT-006) · `hasPendingChanges` (FR-AGT-004).
- `distinguishable` (versionNo+versionId benzersiz — DB UNIQUE) · `missingActiveVersion` (kopuk referans) · `rollbackRefsResolve` (WORM köken — DB §6.5) · `failedTestVersions` (FR-AGT-010) · `openAttentionCount`.

## Dosyalar
| Dosya | Açıklama |
|------|----------|
| `app/(workspace)/workspace/versions/page.tsx` | A-17 ekranı (4 bölüm, i18n, design tokens, formatNumber/formatDate). |
| `lib/tenant/agent-versions.ts` | Veri seam + saf türetme yardımcıları + İKİ KATMAN guard + tipler + placeholder view. |
| `lib/i18n/{tr,en}.json` | `screen.a17.*` blokları (TR↔EN birebir). |
| `a17-versions-spec.json` | Kaynak doğruluk + invariant S1..S8 + referans anahtar + placeholder. |
| `a17_versions_probe.py` | stdlib-only probe (`validate`/`check`/`selftest`/`schema`) — agent-versions.ts Python aynası. |
| `samples/versions-{healthy,degraded}.json` | `$expect`'li sağlıklı + bütünlük/WORM ihlali içeren geçmiş (FR-TST-008 sentetik). |
| `tests/a17_versions_test.py` | Üç kapının çıkış-kodu davranış testi. |
| `run_live_test.sh` | Canlı smoke (next build+start+curl; credential-free). |

## Çalıştırma
```bash
python3 a17_versions_probe.py selftest   # pozitif + negatif kendi-testleri (48)
python3 a17_versions_probe.py check      # saf çekirdek + samples/* (50)
python3 a17_versions_probe.py validate   # on-disk S1..S8 (sayfa + seam + i18n + spec) (78)
python3 tests/a17_versions_test.py       # üç kapı exit 0
bash run_live_test.sh                     # canlı smoke (opsiyonel; next gerektirir)
```

## RBAC (BRD §17.6 A-17)
conversation_designer=**Yönet** · operations_manager=**Görüntüle** · qa_analyst=— · human_agent=— (erişim yok).
tenant_owner kural 17.7 ile Yönet. Permission-key: `agent:version:manage` (API §8.1).
UI yalnız görsel kapı; nihai yetki backend + RLS.

## Kapsam dışı (bilinçli)
- Tek-işlem rollback / promote / yeni-sürüm İŞLEMİ + audit → API §8.1 `agent:version:manage` (`:rollback`/`:promote`); backend WORM append-only (DB §6.5).
- Promotion gate (regresyon/test eşiği) → **A-16** (FR-TST-004/005); A-17 yalnız sonucu (testStatus) yansıtır.
- Agent yapılandırma düzenleme (prompt/flow/voice/model/stt) → **A-04/A-05/A-06/A-07**; A-17 yalnız bağlanan sürüm/profil ADINI gösterir.
- Snapshot gövdesi / config diff görüntüleme → derin aksiyon (görsel kapı + backend); A-17 yalnız sürüm META.
