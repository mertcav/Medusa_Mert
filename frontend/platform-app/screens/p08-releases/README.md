# P-08 — Sürüm & Dağıtım (Release) Yönetimi (WBS 13.2.8)

L0 Platform Admin Console'un sekizinci ekranı. **Platform bileşen versiyonlama**, **feature flag** ve
**kademeli yayma** (canary/staged rollout) yönetimini gösterir (BRD §17.3). Kaynak doğruluk
Release/Deployment servisi (CI/CD + sürüm kayıtları) + Feature Flag servisi + 0.4.7 gözlemlenebilirlik
omurgası (deploy sağlık metrikleri). Bu ekran, agent-seviyesi yaşam döngüsü/rollback disiplininin
(FR-AGT-005 draft/test/staging/production ortamları + FR-AGT-006 tek-işlem rollback) **platform** ölçeğine
yansımasıdır; bölgesel dağıtım NFR 10.7 (`region`) ile izlenir.

## Altın kural (BRD §17.7 / FR-IAM-008)
P-08 **yalnız platform-geneli sürüm/dağıtım/feature-flag metadatası** gösterir. Tenant **iş içeriği** (çağrı
kaydı, transkript, son-müşteri/PII) **gösterilmez**. Veri katmanı (`lib/platform/releases.ts`) tipleri
yapısal olarak iş-içeriği taşımaz ve `assertNoPii` çalışma-anında doğrular (sızıntı → hata). NOT: feature
flag `enabledTenants` alanı **toplulaştırılmış SAYIDIR** (izinli); tenant **listesi/kimliği** değildir.

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**Düzenle** · `platform_billing`=**erişim yok**. UI yalnız
görsel kapı; nihai yetki + dağıtım / kademeli yayma / rollback / flag **zorlaması** backend'de (12.2.x;
permission-key `release:read` + `release:deploy` + `release:rollback` + `featureflag:manage`, SAD §7 ·
§14.4.1 A8). Bu katmanda rol→permission kararı **yok**. Tüm dağıtım/rollback işlemleri audit edilir (P-07).

## Bileşenler
- `app/(platform)/releases/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`) +
  veri seam (`lib/platform/releases`). Tüm metin `screen.p08.*` katalogundan (t()). Bölümler: özet KPI
  (toplam sürüm, production'da, aktif canary, aktif feature flag, başarısız sürüm, başarısız dağıtım),
  dağıtım sağlığı + canary + başarısız dağıtım + flag yapılandırma uyarıları, platform sürümleri (versiyon +
  bileşen + aşama + kademeli yayma % + sağlık + bölge + oluşturma), feature flag'ler (anahtar + durum +
  strateji + yayma % + etkin tenant sayısı + güncelleme), dağıtım olayları (zaman + tip + aktör + hedef +
  sonuç + gereksinim).
- `lib/platform/releases.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları (`releaseStageTone`/
  `releaseHealthTone`/`rolloutStrategyTone`/`flagStatusTone`/`deploymentOutcomeTone`/`deploymentTypeTone`/
  `countByStage`/`activeFlagCount`/`failingReleases`/`canaryRisks`/`failedDeployments`/`rollbackEvents`/
  `flagConfigGaps`/`percentageRollouts`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek
  kaynak F2 §14.1'de Release/Deployment + Feature Flag servisinden beslenir. Bileşen adları vendor-nötr (ADR-002).
- `i18n` (`screen.p08.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Sürüm aşama tonu** (`releaseStageTone`): draft neutral · staging info · canary warning · production
  success · rolled_back neutral.
- **Sürüm sağlık tonu** (`releaseHealthTone`): healthy success · degraded warning · failing danger.
- **Başarısız sürüm** (`failingReleases`, FR-AGT-006): canlı yayında (production VEYA canary) sağlığı
  `failing` olan sürümler — dağıtım sağlık riski.
- **Canary riski** (`canaryRisks`, FR-AGT-005): canary aşamasında sağlığı `healthy` OLMAYAN sürümler —
  production'a ilerletmeden önce incelenmeli.
- **Başarısız dağıtım** (`failedDeployments`): `outcome=failed` dağıtım olayları — rollback gerekebilir.
- **Flag yapılandırma boşluğu** (`flagConfigGaps`): `percentage` stratejisi ama `rolloutPct` uçta (≤0 / ≥100)
  → strateji/yüzde tutarsızlığı (yanlış yapılandırma riski).
- **Yayma stratejisi tonu** (`rolloutStrategyTone`): disabled neutral · internal info · percentage warning ·
  full success.

## Doğrulama
```
python3 p08_releases_probe.py validate   # ON-DISK invariant S1..S8
python3 p08_releases_probe.py check      # saf çekirdek senaryo + samples (sürüm + canary + dağıtım + flag)
python3 p08_releases_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p08_releases_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                       # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Release/Deployment + Feature Flag servisi API bağlama (F2 §14.1); dağıtım / kademeli yayma / rollback /
flag form istemci submit + backend zorlama (12.2.x); diğer L0 ekranı P-09 Alarm & Incident (13.2.9); agent
seviyesi sürüm geçmişi/rollback A-17 (13.4.17) + agent yaşam döngüsü 20.1; on-premise/hybrid dağıtım paketi
20.4 (F3). Vendor-neutral (ADR-002; somut sağlayıcı/CI-CD/feature-flag-SaaS markası bağlanmaz); sır/credential yok.
