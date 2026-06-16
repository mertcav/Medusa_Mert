# WBS 13.1.1 — İki ayrı Next.js app (platform-app L0 internal-only + tenant-app L1+L2 public)

**Faz:** F1 · **Öncelik:** Must · **İz:** SAD §14.4.1 → **ADR-011** (İki düzlemli panel dağıtımı) · BRD §17 (üç katmanlı panel) · FR-IAM-008 (L0 ⟂ tenant) · BRD §17.7 (izolasyon/görünürlük)

13. workstream'in (Frontend / Panel) **ilk** modülü ve **13.1 "Ortak frontend altyapısı"** alt-bloğunun temeli. SAD §14.4.1'in *"Yönetim/panel uygulaması Next.js App Router ile … **AYRI deploy**"* kararını ve **ADR-011**'in (Seçenek 3: L0 ayrı internal-only Platform Control Plane; L1+L2 birlikte public Tenant Application Plane) **fiziksel App Router iskeletini** sahiplenir.

## İki ayrı app (deploy-zamanı plane ayrımı — ADR-011 Seçenek 3)

| App | Tier | Plane | Ağ | Auth realm | Route group(lar) | Ekran |
|-----|------|-------|-----|-----------|------------------|-------|
| `frontend/platform-app` | **L0** | `platform_control_plane` | **internal_only** (VPN/allowlist/private endpoint) | `platform` | `(platform)` | 9 (P-01..P-09) |
| `frontend/tenant-app` | **L1+L2** | `tenant_application_plane` | **public** | `tenant` | `(tenant-admin)` + `(workspace)` | 9 (T-01..T-09) + 17 (A-01..A-17) |

Her app **kendi** `package.json` + `next.config.mjs` + `app/` dizinine sahip → **ayrı build/deploy birimi/origin/auth realm**. ADR-011'in reddettiği iki seçenek:
- **Seçenek 1 (tek deploy + guard):** paylaşılan kod/middleware'deki tek bug L0'ı açar (blast-radius). ❌
- **Seçenek 2 (üç ayrı deploy):** kaynak israfı. ❌

## Çekirdek invaryant (A5) — blast-radius azaltımı

> **`platform-app` tenant iş verisi route'larını FİZİKSEL OLARAK İÇERMEZ.**

`live-calls / recordings / call / transcript / qa / kb / flows / prompts / campaigns / agents / builder / voice / tools` segmentlerinin **hiçbiri** `platform-app/app` altında bulunmaz (FR-IAM-008, BRD §17.7). Çalışma-anı middleware regrese olsa bile L0 yüzeyinde tenant içeriği route'u **yoktur**. Bu route'lar yalnız `tenant-app/(workspace)` içinde, doğru konumda. L0 içeriğe yalnız ayrı, kısıtlı, tam-audit'li **break-glass** akışıyla erişir (12.3.x; bu modülün kapsamı dışında).

## URL-base ayrımı (next build ile doğrulanan tasarım kararı)

Next.js route group'ları (`(…)`) URL'e **segment eklemez**. İki group aynı app'te barınınca düz ekran adları (ör. iki `dashboard`) **aynı path'e çözülür** ve build kırılır (*"two parallel pages that resolve to the same path"*). Çözüm: her tenant-app route group'u bir **URL-base** altına yerleşir —

- `(tenant-admin)/admin/<ekran>` → `/admin/dashboard`, `/admin/org`, … (L1)
- `(workspace)/workspace/<ekran>` → `/workspace/live-calls`, `/workspace/call`, … (L2)
- `platform-app` tek group olduğundan düz: `(platform)/<ekran>` → `/overview`, … (L0)

Bu, L1/L2 panel ayrımını URL'de de netleştirir. `next build` her iki app'te **0 hata** ile geçer (platform-app: 9 route + middleware; tenant-app: 26 route + middleware).

## Kapı (probe)

```
AppTopologyRequest ─malformed─► two-apps ─► route-group-sep ─► screen-cov ─► no-forbidden ─► isolation ─► coupling
      ├─ spec/topology/on-disk okunamaz / app≠2 ──────────────────────────► FAIL (malformed/missing_app) [A1/A2]
      ├─ platform-app non-(platform) VEYA tenant-app eksik group ──────────► route_group_mismatch [A3]
      ├─ ekran route'u eksik ──────────────────────────────────────────────► screen_gap [A4]
      ├─ platform-app'te yasak tenant iş verisi route'u ──────────────────► forbidden_route_in_platform [A5 ÇEKİRDEK]
      ├─ platform-app public VEYA realm eşit ─────────────────────────────► plane_coupling [A6]
      ├─ app'ler arası doğrudan import ────────────────────────────────────► cross_app_import [A7]
      └─ frontend'de hardcoded yetki kararı ───────────────────────────────► frontend_authz [A8]
```

`validate` **on-disk** iskeleti (gerçek dizin taraması) spec'e/topolojiye karşı doğrular; `check` sentetik senaryo motorunu çalıştırır.

## Çalıştırma

```bash
python3 frontend_apps_probe.py validate     # statik spec + topology + ON-DISK iki-app iskelet → çıkış kodu
python3 frontend_apps_probe.py selftest     # topoloji karar motoru invariant'ları A1–A12
python3 frontend_apps_probe.py check samples # 1 pass + 7 degrade senaryosu
python3 tests/frontend_apps_behavior_test.py # bağımsız on-disk davranış testi
bash run_live_test.sh                        # hepsi + (npm varsa) canlı build NOT'u
```

**Sonuçlar:** validate **31/31** 🟢 · selftest **15/15** 🟢 · check **8/8** 🟢 (1 pass + 7 degrade beklendiği gibi elendi) · behavior **20/20** 🟢 · `next build` her iki app 🟢.

## Kapsam ayrımı (bilinçli)

| Konu | Sahip |
|------|-------|
| Çalışma-anı oturum + tenant scope + panel ayrımı middleware | **13.1.2** |
| Tasarım sistemi / komponent kütüphanesi + i18n (TR/EN) | **13.1.3** |
| PII redaction/maskeleme (panel görüntüleme) | **13.1.4** |
| L0/L1/L2 ekran iç implementasyonu | 13.2 / 13.3 / 13.4 |
| Backend yetki guard (panel+rol+tenant) / RLS | 12.2.x (RESİPROKAL) |
| Break-glass içerik erişim akışı | 12.3.x |
| SSO/SCIM auth realm provisioning | 12.1.x / 14.4.4 |

Bu modül **yalnız** iki-app frontend dağıtım/yapısal iskeletini ve statik kapısını sahiplenir. **UI yalnız görsel kapıdır; yetki kararı her zaman backend'dedir** (SAD §14.4.1 — A8).

## Güvenlik / vendor-neutral

- **Vendor-neutral (ADR-002):** Next.js/React framework; hosting/CDN sağlayıcısı bağlanmaz.
- **Sır/credential yok:** ortam değişkenleri yalnız `${ENV}` referansı (`.env.example` RHS boş); ham PII/credential repoya yazılmaz (A12).
- **internal-only sertleştirme:** `platform-app` `noindex/nofollow` + `X-Frame-Options: DENY` + sıkı CSP-öncüsü başlıklar; ağ-seviyesi VPN/allowlist deploy katmanında.
