// @chanteur/tenant-app — (tenant-admin) route group layout (L1 — Tenant Admin Console).
// SAD §14.4.1: "tenant oturumu + L1 rol guard; tenant scope middleware'de sabitlenir".
//
// İSKELET (13.1.1): L1 tek-tenant yönetim ekranlarını çerçeveler. Tenant oturumu + tenant_scope
// (tek tenant — FR-TEN-002) + panel ayrımı (/admin → L1) ENFORCEMENT'ı 13.1.2'de middleware.ts'e
// eklendi. UI yalnız görsel kapı; nihai yetki backend'de + RLS (SAD §14.4.1 — A8).
//
// 13.1.3: nav etiketleri i18n katalogundan (t()); design token'larıyla stillenir; LangSwitcher +
// erişilebilir <main id>.
import type { ReactNode } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, SUPPORTED_LOCALES } from "@/lib/i18n";
import { LangSwitcher } from "@/lib/ui/components";

const L1_NAV = [
  { href: "/admin/dashboard", key: "nav.tenant_admin.dashboard", code: "T-01" },
  { href: "/admin/org", key: "nav.tenant_admin.org", code: "T-02" },
  { href: "/admin/users", key: "nav.tenant_admin.users", code: "T-03" },
  { href: "/admin/numbers", key: "nav.tenant_admin.numbers", code: "T-04" },
  { href: "/admin/integrations", key: "nav.tenant_admin.integrations", code: "T-05" },
  { href: "/admin/compliance", key: "nav.tenant_admin.compliance", code: "T-06" },
  { href: "/admin/billing", key: "nav.tenant_admin.billing", code: "T-07" },
  { href: "/admin/audit", key: "nav.tenant_admin.audit", code: "T-08" },
  { href: "/admin/quota", key: "nav.tenant_admin.quota", code: "T-09" },
];

const LOCALE_LABEL: Record<string, string> = { tr: "TR", en: "EN" };

export default function TenantAdminLayout({ children }: { children: ReactNode }) {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  return (
    <div data-plane="tenant_application_plane" data-tier="L1" style={{ display: "flex", minHeight: "100vh" }}>
      <aside
        aria-label={t(cat, "a11y.main_nav")}
        style={{
          background: "var(--rmc-surface)",
          borderInlineEnd: "1px solid var(--rmc-border-subtle)",
          padding: "var(--rmc-space-4)",
          minWidth: "240px",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--rmc-space-2)" }}>
          <strong style={{ color: "var(--rmc-brand-primary)" }}>{t(cat, "app.title_tenant")}</strong>
          <LangSwitcher
            current={locale}
            locales={SUPPORTED_LOCALES}
            hrefFor={(l) => `?lang=${l}`}
            label={t(cat, "a11y.lang_switcher")}
            localeLabel={(l) => LOCALE_LABEL[l] ?? l}
          />
        </div>
        <nav aria-label={t(cat, "a11y.main_nav")} style={{ marginTop: "var(--rmc-space-4)" }}>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--rmc-space-1)" }}>
            {L1_NAV.map((item) => (
              <li key={item.href}>
                <a href={item.href}>{t(cat, item.key)}</a>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main id="main" style={{ flex: 1 }}>
        {children}
      </main>
    </div>
  );
}
