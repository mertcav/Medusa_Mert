# T-03 — Kullanıcı & Rol Yönetimi (RBAC/SSO/SCIM) (WBS 13.3.3)

L1 Tenant Admin Console'un üçüncü ekranı (T-01..T-09 serisi). Tenant **içi** RBAC (kullanıcı–rol
atamaları), SSO (SAML 2.0 / OIDC) ve SCIM provisioning ayarlarını gösterir ve yönetir
(BRD §17.4 / FR-IAM-001/002/007/011). Roller değişmez (immutable) permission bundle'lardır; esneklik
yalnız atama **kapsam (scope) filtresiyle** (departman/marka/kampanya, FR-IAM-011 / ADR-012) sağlanır.

## Tenant scope (FR-TEN-002) + hijyen (BRD §17.7) + güvenlik (NFR 10.6)
T-03 **yalnız oturum açan tenant'ın KENDİ** kullanıcı/rollerini gösterir/yönetir; scope çalışma-anında
middleware (13.1.2) + RLS (§13) ile sabitlenir. Ekran yalnız **kimlik + RBAC/SSO/SCIM konfigürasyon
metadatası** gösterir:
- Ham son-müşteri iş içeriği (çağrı kaydı, transkript, müşteri/PII) buraya **gömülmez** —
  `FORBIDDEN_PII_KEYS` + `assertNoPii` ile çalışma-anında garanti.
- SSO/SCIM **sırrı** (federation sertifikası, SCIM bearer token, client secret) buraya **konmaz** —
  `FORBIDDEN_SECRET_KEYS` + `assertNoPii` ile garanti; yalnız bağlantı durumu (`tokenConfigured` bayrağı)
  gösterilir. Gizli değerler backend secret store'dadır.
- `tenantRef`/`tenantName` + kullanıcı `principal`/`displayName` + `idpLabel` tenant'ın **kendi**
  kimliği/konfigürasyonudur (son-müşteri PII değil → izinli).

## Bileşenler
- `app/(tenant-admin)/admin/users/page.tsx` — ekran (RSC, async). Tasarım sistemi (`lib/ui`) + i18n
  (`lib/i18n`) + veri seam (`lib/tenant/users`). Tüm metin `screen.t03.*` katalogundan (t()).
  Bölümler: **Özet** (kullanıcı/aktif/rol/kapsamlı atama) · **Kullanıcılar** (kimlik + roller + kapsam +
  kaynak local/sso/scim + MFA + durum; geçersiz rol rozeti) · **Roller** (immutable bundle + katman L1/L2
  + atanan sayı) · **SSO & SCIM** (protokol/durum/IdP/MFA/JIT/varsayılan rol + SCIM token-durumu/son
  senkron/senkron kullanıcı/grup eşlemesi). MFA'sız aktif kullanıcı veya geçersiz rol → uyarı.
- `lib/tenant/users.ts` — vendor-neutral veri **seam** + saf türetme yardımcıları
  (`countUserStatus`/`countUserSource`/`usersForRole`/`scopedAssignmentCount`/`usersMissingMfa`/
  `invalidRoleRefs`/tone'lar) + `assertNoPii` guard (PII **ve** sır). Yer tutucu deterministik snapshot;
  gerçek kaynak F2 §14.1'de IAM/Directory servisi + SSO/SCIM köprüsünden tenant-scope (RLS) beslenir.
- `i18n` (`screen.t03.*`) — TR/EN, design-system canonical katalogda; her iki app'e vendored (hash-eşit).

## RBAC (BRD §17.6)
`tenant_owner`=Yönet · `tenant_admin`=Yönet · `security_compliance_officer`=Görüntüle · `billing_viewer`=—
· `api_developer`=—. UI yalnız görsel kapı; nihai yetki backend'de (12.2.x, SAD §14.4.1 A8) + RLS. "Yeni
kullanıcı / SSO yapılandır / SCIM yapılandır" aksiyonları görsel kapıdır; oluşturma/düzenleme istemci
submit + backend zorlama 12.2.x'te. Bu katmanda rol→permission kararı **yok**.

## Doğrulama
```
python3 t03_users_probe.py validate   # ON-DISK invariant S1..S8
python3 t03_users_probe.py check      # saf çekirdek senaryo + samples
python3 t03_users_probe.py selftest   # pozitif/negatif kendi-testi
python3 tests/t03_users_test.py       # üç kapı çıkış-kodu davranış testi
bash run_live_test.sh                   # canlı smoke (next build+start+curl; credential-free)
```

## Kapsam dışı (bilinçli)
Gerçek IAM/Directory + SSO/SCIM servisi API bağlama → F2 §14.1; kullanıcı oluşturma/düzenleme + SSO/SCIM
yapılandırma istemci submit + backend zorlama + maker-checker → 12.2.x; break-glass akışı → 12.3.x;
diğer L1 ekranları T-04..T-09 → 13.3.4+. Vendor-neutral (ADR-002; belirli IdP/SaaS bağlanmaz);
sır/credential repoya yazılmaz.
