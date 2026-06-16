# `frontend/` — Panel / Yönetim Düzlemi (Next.js App Router)

Bu workstream (WBS 13.x), BRD §17 üç katmanlı panel mimarisinin (L0/L1/L2) ve SAD §14.4.1 frontend tasarımının **uygulamasıdır**. Panel/yönetim düzlemi teknoloji yığını: **Next.js (App Router, TypeScript)** (SAD §24, CLAUDE.md). Voice runtime (data plane) ayrı bir düzlemdir (Go/Rust, ADR-003) ve bu dizinin kapsamında değildir.

## İki düzlemli dağıtım (ADR-011)

| Dizin | Açıklama |
|-------|----------|
| `platform-app/` | **L0 — Platform Admin Console** (cross-tenant). Ayrı, **internal-only** Platform Control Plane (VPN/allowlist/private endpoint). `(platform)` route group. |
| `tenant-app/` | **L1 — Tenant Admin Console** + **L2 — Operasyon / Uygulama Paneli** (tek tenant). Birlikte, multi-tenant, **public** Tenant Application Plane. `(tenant-admin)` + `(workspace)` route group'ları. |
| `apps-separation/` | **13.1.1** — iki-app ayrımı kaynak doğruluğu (spec + topoloji + stdlib probe + örnekler + testler). İki app iskeletini ADR-011 / SAD §14.4.1'e karşı doğrular. |

İki app **ayrı build/deploy birimidir** (ayrı `package.json`/origin/auth realm). `platform-app` tenant iş verisi route'larını fiziksel olarak **içermez** (blast-radius azaltımı; FR-IAM-008). Ayrıntı: [`apps-separation/README.md`](apps-separation/README.md).

## 13.1 "Ortak frontend altyapısı" yol haritası

- [x] **13.1.1** İki ayrı Next.js app (platform-app + tenant-app) — `apps-separation/`
- [ ] **13.1.2** Route group + middleware (oturum + tenant scope + panel ayrımı)
- [ ] **13.1.3** Tasarım sistemi / komponent kütüphanesi + i18n (TR/EN)
- [ ] **13.1.4** PII redaction/maskeleme (panel görüntüleme)

## Geliştirme

Her app bağımsızdır:

```bash
cd frontend/platform-app && npm install && npm run dev   # L0 (internal-only)
cd frontend/tenant-app   && npm install && npm run dev   # L1+L2 (public)
npm run build      # üretim build'i (CI'da her iki app ayrı çalışır)
npm run typecheck  # tsc --noEmit
```

`node_modules/`, `.next/`, `next-env.d.ts`, `package-lock.json` gitignore'da. Sır/credential repoya **yazılmaz** — yalnız `.env.example` (`${ENV}` referansı, RHS boş).
