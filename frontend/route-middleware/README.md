# WBS 13.1.2 — Route group + middleware (oturum + tenant scope + panel ayrımı)

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.1 → ADR-011 · FR-TEN-002 (tek tenant per oturum) · FR-IAM-008 (L0 ⟂ tenant realm) · BRD §17.7 · SAD §13.3 (correlation/tenant context)

**13.1 "Ortak frontend altyapısı"** alt-bloğunun **ikinci** modülü. 13.1.1 iki ayrı Next.js app + route group **iskeletini** (yer tutucu middleware) kurdu; bu modül o iskelete **çalışma-anı middleware kapısını** ekler:

```
OTURUM → REALM/PANEL AYRIMI → TENANT SCOPE → PANEL mapping → CONTEXT propagasyonu
```

## Çekirdek ilke (A8 — SAD §14.4.1)

> **UI yalnız GÖRSEL kapıdır; nihai yetki kararı HER ZAMAN backend'dedir (12.2.x) + PostgreSQL RLS (§13).**

Middleware coarse bir **UX/yönlendirme kapısı + context propagasyonudur** (kimlik var mı · doğru realm mı · tek tenant'a mı bağlı · doğru panele mi yönlendi). Burada **rol→permission kararı YOKTUR** — o RESİPROKAL backend guard'ındadır (SAD §14.4.2).

## Karar çekirdeği (`lib/middleware-core.ts` → `decide()`)

Saf/deterministik fonksiyon (Next/edge API'sinden bağımsız → birim-test + Python aynası). Sıra **fail-closed**:

| # | Koşul | Aksiyon | Reason | İz |
|---|-------|---------|--------|-----|
| A | `exempt(path)` (login, /api/auth) | `next` | `exempt` | M2 |
| B | oturum yok | `redirect` → `/login?next=` | `no_session` | M2 |
| C | `exp <= now` | `redirect` → login (expired) | `expired_session` | M2 |
| D | `session.realm != app.realm` | `forbid` 403 | `realm_mismatch` | M3 / FR-IAM-008 |
| E1 | tenant-app & `!tenant_id` | `forbid` 403 | `missing_tenant_binding` | M4 / FR-TEN-002 |
| E2 | tenant-app & `requestedTenant != tenant_id` | `forbid` 403 | `cross_tenant_denied` | M5 / FR-TEN-002 |
| E3 | platform-app & `tenant_id` taşıyor | `forbid` 403 | `unexpected_tenant_binding` | M4 / A5 |
| F | aksi | `next` + context header | `allow` | M6/M8 |

**Panel mapping (M6):** `/admin/*` → `(tenant-admin)`/**L1** · `/workspace/*` → `(workspace)`/**L2** · platform `/` → `(platform)`/**L0**.

**Context header'ları (M8, downstream'e enjekte):** `x-app-plane` · `x-app-tier` · `x-panel` · `x-route-group` · `x-tenant-scope` (yalnız tenant-app) · `x-correlation-id` (§13.3) · `x-auth-subject`. Düşük-kardinalite metrik label = `app/action/reason`; `path`/`tenant_id`/`sub` yalnız trace (HAM PII yok — BRD §17.7).

## Vendor-neutral oturum (ADR-002)

Belirli auth sağlayıcısına bağlanmaz. Oturum, auth realm'inin (`*_AUTH_ISSUER` — OIDC/SAML; platform realm tenant realm'inden **AYRI**, FR-IAM-008) yayınladığı bir token'da taşınır. `lib/session.ts` token'ın **yalnız claim payload'ını** okur (realm/sub/exp/tenant_id) + yapısal geçerlilik — UX kapısı için. **Kriptografik imza/issuer doğrulaması auth realm + backend'dedir** (12.2.x); edge JWKS imza doğrulaması F2'de eklenebilir (seam `lib/session.ts`'te). Çerez ADI sır değildir; gerçek token değeri yalnız çalışma-anı isteğinde gelir.

## Kapı (probe)

```
DecisionInput ─exempt─► no_session ─► expired ─► realm ─► tenant_scope ─► panel ─► next/allow
      ├─ session==null ─────────────────────────────────────► redirect (no_session)   [M2]
      ├─ exp<=now ──────────────────────────────────────────► redirect (expired)      [M2]
      ├─ realm!=policy.realm ──────────────────────────────► forbid (realm_mismatch)  [M3]
      ├─ tenantScoped & !tenant_id ───────────────────────► forbid (missing_bind)    [M4]
      ├─ tenantScoped & reqTenant!=tenant_id ─────────────► forbid (cross_tenant)    [M5]
      ├─ !tenantScoped & tenant_id ───────────────────────► forbid (unexpected)      [M4]
      └─ else ──────────────────────────────────────────────► next (allow) + panel    [M6/M8]
```

`route_middleware_probe.py` (stdlib-only, deterministik, credential-free):

| Komut | İşlev |
|-------|-------|
| `validate` | Statik spec + policy + **ON-DISK** middleware/lib invariant kapısı (M1–M10) + gömülü davranış → çıkış kodu |
| `check <sample\|dizin>` | Saf karar çekirdeği: senaryo(lar) → `action`+`reason`+header doğrulama |
| `selftest` | Gömülü davranış kontrolleri → çıkış kodu |
| `schema` | Karar sözleşmesi |

**İnvariant'lar (HARD kapılar, 0-ihlal):** M1 dosya varlığı · M2 oturum zorunlu (sessiz izin YOK) · M3 realm/panel ayrımı · M4 tenant scope binding · M5 cross-tenant reddi · M6 panel mapping · M7 UI-only no-authz · M8 context propagasyonu · M9 sır/PII yok + vendor-neutral · M10 policy frozen + hash.

## Sonuçlar

- `selftest` **21/21** 🟢 · `validate` **42/42** 🟢 · `check samples` **10/10** 🟢 · davranış testi **14/14** 🟢
- `tsc --noEmit` her iki app 🟢 · `next build` her iki app 🟢 (Middleware derlendi)
- **Canlı smoke (next start + curl) — gerçek çalışma-anı kanıtı:**

| Senaryo | Sonuç |
|---------|-------|
| tenant oturumsuz `/admin/users` | **307** → `/login?next=%2Fadmin%2Fusers` (`no_session`) |
| tenant valid `/admin/users` | **200** (`allow`) + `x-app-plane` |
| platform realm token → tenant-app `/workspace/qa` | **403** (`realm_mismatch`) |
| cross-tenant `?tenant=tenant-B` (oturum tenant-A) | **403** (`cross_tenant_denied`) |
| expired token `/admin/org` | **307** → login (`expired_session`) |
| platform valid `/overview` | **200** (`allow`) |
| tenant realm token → platform-app `/overview` | **403** (`realm_mismatch`) |
| platform token `tenant_id` taşıyor → `/tenants` | **403** (`unexpected_tenant_binding`) |

```bash
python3 route_middleware_probe.py selftest
python3 route_middleware_probe.py validate
python3 route_middleware_probe.py check samples
./run_live_test.sh            # statik + tsc + build; SMOKE=1 ile canlı redirect smoke
```

## Kapsam dışı (bilinçli — başka modül sahibi)

rol→permission + kaynak sahipliği nihai kararı → **12.2.x backend**; tenant scope çift-kontrol → **RLS §13**; kriptografik token imza/JWKS → **auth realm + backend** (edge JWKS opsiyonel F2); tasarım sistemi/komponent/i18n → **13.1.3** (middleware-core paylaşılan pakete taşınabilir); PII maskeleme → **13.1.4**; ekran içi → **13.2/13.3/13.4**; SSO/SCIM realm provisioning → **14.4.4/12.1.x**.

> **Not (ADR-011 kuplaj):** `lib/middleware-core.ts` + `lib/session.ts` her iki app'te **bilinçli olarak ayrı** (cross-app import YOK — A7). 13.1.3 kontrollü ortak paket tanıttığında çekirdek oraya taşınabilir. Sır/credential repoya yazılmadı (`.env.example` RHS boş; çerez adı sır değil).
