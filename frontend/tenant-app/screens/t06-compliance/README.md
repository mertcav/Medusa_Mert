# T-06 — Compliance & Retention (WBS 13.3.6)

L1 Tenant Admin Console'un altıncı ekranı (T-01..T-09 serisi). Tenant'ın **uyumluluk ve saklama
profilini** gösterir ve yönetir: **consent** (rıza modeli), **kayıt politikası** (recording policy + PII
redaction + kart/OTP maskeleme), **veri yerleşimi** (residency), **saklama süresi** (retention + legal
hold), **compliance profile** (ülke profili + sektörel overlay + most-restrictive-wins) ve **İYS/DNC**
(outbound consent registry + do-not-call). Ayrıca DSR (veri sahibi hakları) + ihlal bildirimi + DPIA durumu
+ tenant override'ları (BRD §17.4 / FR-REC-001..010 · FR-OUT-003/004/006 · DPIA cp.* §6/§7/§8 · NFR 10.7).
Uyumluluk katmanı sağlayıcıdan bağımsızdır (ADR-002) ve değerleri **mühendislik varsayılanıdır** —
production öncesi tenant'ın hukuk danışmanı (counsel) doğrulamasına tabidir (DPIA §12).

## Tenant scope (FR-TEN-002) + hijyen (BRD §17.7) + güvenlik (NFR 10.6)
T-06 **yalnız oturum açan tenant'ın KENDİ** uyumluluk/saklama POLİTİKASINI gösterir/yönetir; scope
çalışma-anında middleware (13.1.2) + RLS (§13) ile sabitlenir:
- Ham son-müşteri iş içeriği (çağrı kaydı, transkript, **bireysel** rıza/DNC kaydı, müşteri PII) buraya
  **gömülmez** — bunlar L2/data-plane'de tutulur; `FORBIDDEN_PII_KEYS` + `assertNoPii` ile çalışma-anında
  garanti. (`recordingPolicy`/`piiRedaction` gibi alan adları **politika parametresidir** — exact-match
  `recording`/`pii` değil → izinli.)
- **SIR** (KMS anahtarı, sağlayıcı credential, DPA imza materyali) buraya **konmaz** —
  `FORBIDDEN_SECRET_KEYS` + `assertNoPii` ile garanti.
- `tenantRef`/`tenantName` + profil kodu + saklama günleri + residency bayrakları + İYS/DNC **kaynak
  adları** tenant'ın **KENDİ** konfigürasyonudur (son-müşteri PII / sır değil → izinli).

## Bileşenler
- `app/(tenant-admin)/admin/compliance/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/compliance`). Tüm metin `screen.t06.*` katalogundan (t()).
  Bölümler: **Özet** (profil/saklama/bölge/DPIA/açık-uyarı) · **Compliance Profile** (ülke profili +
  rejim + sektörel overlay + hukuki dayanak + DPA) · **Kayıt Politikası** (kanal modu + rıza modeli + PII
  redaction + kart/OTP) · **Şeffaflık & Bildirim** (AI/kayıt bildirimi + insan taklidi yasağı) · **Veri
  Yerleşimi** (home-region + in-region + provider pinning + sınır-ötesi) · **Saklama** (kayıt/transkript/
  audit gün + legal hold) · **Outbound/İYS/DNC** (rıza modeli + izin kaydı + DNC kaynakları + arama saati
  + CLI + B2B) · **DSR & İhlal Bildirimi** (erişim/silme SLA + düzeltme/taşınabilirlik + makam/süre/birey
  bildirimi) · **Tenant Override'ları** (parametre + taban + değer + yön; gevşeten = İHLAL). Boşluklar:
  gevşeten override / eksik bildirim / residency boşluğu / geçersiz saklama → danger; eksik kayıt koruması /
  outbound boşluğu / bekleyen DPIA → warning.
- `lib/tenant/compliance.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları (`disclosureGaps`/
  `recordingGaps`/`residencyGaps`/`outboundGaps`/`loosenOverrides`/`invalidRetention`/`dpiaPending`/
  `openWarningCount`/tone'lar) + `assertNoPii` guard (PII **ve** sır). Yer tutucu deterministik snapshot;
  gerçek kaynak F2 §14.1'de Compliance Profile çözümleyici (SAD §19) + Consent Engine + Retention
  motorundan tenant-scope (RLS) beslenir.
- `i18n` (`screen.t06.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Görüntüle · `security_compliance_officer`=Yönet · `billing_viewer`=— ·
`api_developer`=—. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8) + RLS. "Profili
Düzenle" aksiyonu görsel kapıdır; profil değiştirme/override onaylama istemci submit + backend zorlama
12.2.x'te. **most-restrictive-wins** çözümleme + **override yalnız-sıkılaştırır** kuralı (DPIA §8) backend'de
zorlanır; bu katmanda yalnız çözümlenmiş profil gösterilir ve gevşeten override AUDIT olarak işaretlenir.

## Doğrulama
```
python3 t06_compliance_probe.py validate   # ON-DISK invariant S1..S8
python3 t06_compliance_probe.py check      # saf çekirdek senaryo + samples
python3 t06_compliance_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t06_compliance_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                       # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (bilinçli)
Gerçek Compliance Profile çözümleyici + Consent Engine + Retention motoru API bağlama → F2 §14.1; profil
değiştirme/override onaylama istemci submit + backend zorlama (most-restrictive-wins + yalnız-sıkılaştır) →
12.2.x; canlı retention/silme + legal hold + DSR akış yürütme → data plane; bireysel rıza/DNC kayıt yönetimi
(uygulama) → L2/Outbound A-10; DPIA şablonu doldurma + onboarding gate akışı → DPIA §3 / onboarding. Belirli
ülke/sektör hukuki yorumu bağlanmaz (counsel-tabi, DPIA §12); değerler mühendislik varsayılanı; vendor-neutral
(ADR-002); sır/credential repoya yazılmaz.
