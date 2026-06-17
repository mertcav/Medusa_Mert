# P-07 — Platform Audit & Güvenlik (WBS 13.2.7)

L0 Platform Admin Console'un yedinci ekranı. **Platform geneli audit log**, **break-glass erişim
oturumları** ve **güvenlik olayları**nı gösterir (BRD §17.3). Kaynak doğruluk Audit servisi
(FR-IAM-006 değiştirilemez/WORM audit log; FR-REC-009 kayıt/transkript erişimi audit'i; SAD §13.x) +
IAM break-glass akışı (FR-IAM-005 maker-checker; FR-IAM-009 üç katmanlı break-glass: maker-checker +
time-box + bildirim; FR-IAM-010 regüle tenant onayı) + Güvenlik olay hattı (SAD §17 gözlemlenebilirlik
omurgası / SIEM).

## Altın kural (BRD §17.7 / FR-IAM-008)
P-07 **yalnız platform-geneli audit/erişim/güvenlik metadatası** gösterir. Tenant **iş içeriği** (çağrı
kaydı, transkript, son-müşteri/PII) **gösterilmez** — audit kaydı bir işlemin **META** verisidir (kim/ne/
ne zaman/sonuç), içeriği değil. Veri katmanı (`lib/platform/audit.ts`) tipleri yapısal olarak iş-içeriği
taşımaz ve `assertNoPii` çalışma-anında doğrular (sızıntı → hata). NOT: `tenantRef` tenant **kimliğidir**
(BRD §17.7'ye göre L0'a açık; izinli); yasaklanan son-müşteri verisidir. KRİTİK: bu ekran break-glass'i
**yönetmez**; yalnız oturumların **uyum** metadatasını (maker-checker, time-box, tenant onayı, bildirim)
izler — içeriğe fiili erişim Tier B akışındadır (12.2.x).

## RBAC (BRD §17.6)
`platform_owner`=**Yönet** · `platform_sre`=**Görüntüle** · `platform_billing`=**erişim yok**. UI yalnız
görsel kapı; nihai yetki + audit dışa aktarım / break-glass onay **zorlaması** backend'de (12.2.x;
permission-key `audit:read` + `audit:export` + `breakglass:approve`, SAD §7 · §14.4.1 A8). Bu katmanda
rol→permission kararı **yok**.

## Bileşenler
- `app/(platform)/audit/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n (`lib/i18n`) +
  veri seam (`lib/platform/audit`). Tüm metin `screen.p07.*` katalogundan (t()). Bölümler: özet KPI
  (audit kaydı, aktif break-glass, onay bekleyen, açık güvenlik olayı, kritik güvenlik olayı, break-glass
  uyum boşluğu), WORM integrity + break-glass uyum + kritik güvenlik uyarıları, platform audit log (zaman +
  aktör + eylem + kategori + tenant + sonuç + WORM), break-glass erişim oturumları (katman + durum + tenant +
  gerekçe + talep/onay + time-box + tenant onayı + bildirim), güvenlik olayları (zaman + tip + önem + durum).
- `lib/platform/audit.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları (`auditOutcomeTone`/
  `breakGlassStatusTone`/`severityTone`/`securityStatusTone`/`countByOutcome`/`wormGaps`/
  `countActiveBreakGlass`/`pendingApprovals`/`makerCheckerViolations`/`standingAccessViolations`/
  `tenantApprovalGaps`/`notificationGaps`/`breakGlassComplianceGaps`/`openSecurityEvents`/
  `criticalOpenEvents`) + `assertNoPii` guard. Yer tutucu deterministik snapshot; gerçek kaynak F2 §14.1'de
  Audit servisi + IAM break-glass akışı + güvenlik olay hattından beslenir.
- `i18n` (`screen.p07.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## Türetme / eşikler
- **Audit sonucu tonu** (`auditOutcomeTone`): success → success · denied → warning · error → danger.
- **Break-glass durumu tonu** (`breakGlassStatusTone`): active → warning (hassas, açık erişim) ·
  pending_approval → info · expired/revoked/denied → neutral.
- **WORM boşluğu** (`wormGaps`, FR-IAM-006): `wormAnchored=false` audit kayıtları (değiştirilebilirlik riski).
- **Maker-checker ihlali** (`makerCheckerViolations`, FR-IAM-005/009): erişim sağlamış (active/expired/
  revoked) Tier B oturumda onaylayan yok ya da talep eden = onaylayan. pending/denied ihlal sayılmaz.
- **Standing-access ihlali** (`standingAccessViolations`, FR-IAM-009): Tier B time-box > 240 dk (max 4 saat).
- **Tenant onayı boşluğu** (`tenantApprovalGaps`, FR-IAM-010): erişim sağlamış oturumda tenant onayı zorunlu
  ama alınmamış.
- **Bildirim boşluğu** (`notificationGaps`, FR-IAM-009): erişim sağlamış Tier B oturum tenant'a bildirilmemiş.
- **Break-glass uyum boşluğu** (`breakGlassComplianceGaps`): yukarıdaki dört ihlal kümesinin birleşimi (tekil).
- **Güvenlik önem/durum tonu** (`severityTone`/`securityStatusTone`): critical/high danger; open danger.

## Doğrulama
```
python3 p07_audit_probe.py validate   # ON-DISK invariant S1..S8
python3 p07_audit_probe.py check      # saf çekirdek senaryo + samples (WORM + break-glass uyum + güvenlik)
python3 p07_audit_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/p07_audit_test.py        # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                    # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (sonraki dilimler)
Gerçek Audit servisi / IAM break-glass akışı / güvenlik olay hattı API bağlama (F2 §14.1); audit dışa
aktarım + break-glass onay form istemci submit + backend zorlama (12.2.x); diğer L0 ekranları P-08..P-09
(13.2.8+); tenant tarafı audit log T-08 (13.3.8); break-glass talep/onay UI akışı (fiili içerik erişimi,
Tier B); WORM depo + retention/legal-hold uygulaması (DB.md / F2). Vendor-neutral (ADR-002; somut sağlayıcı/
SIEM markası bağlanmaz); sır/credential yok.
