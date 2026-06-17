// @chanteur/tenant-app — (workspace) route group layout (L2 — Operasyon / Uygulama Paneli).
// SAD §14.4.1: "tenant oturumu + L2 rol guard".
//
// İSKELET (13.1.1): L2 günlük operasyon ekranlarını çerçeveler. Tenant oturumu + tenant_scope
// (tek tenant — FR-TEN-002) + panel ayrımı (/workspace → L2) ENFORCEMENT'ı 13.1.2'de middleware.ts'e
// eklendi. PII içeren görüntülemeler 13.1.4'te maskelenir. UI yalnız görsel kapı; yetki backend'de +
// RLS (SAD §14.4.1 — A8).
//
// 13.1.3: nav etiketleri i18n katalogundan (t()); design token'larıyla stillenir; LangSwitcher +
// erişilebilir <main id>.
import type { ReactNode } from "react";
import { getServerLocale } from "@/lib/i18n/server";
import { getCatalog, t, SUPPORTED_LOCALES } from "@/lib/i18n";
import { LangSwitcher } from "@/lib/ui/components";

const L2_NAV = [
  { href: "/workspace/dashboard", key: "nav.workspace.dashboard", code: "A-01" },
  { href: "/workspace/live-calls", key: "nav.workspace.live_calls", code: "A-02" },
  { href: "/workspace/agents", key: "nav.workspace.agents", code: "A-03" },
  { href: "/workspace/builder", key: "nav.workspace.builder", code: "A-04" },
  { href: "/workspace/flows", key: "nav.workspace.flows", code: "A-05" },
  { href: "/workspace/prompts", key: "nav.workspace.prompts", code: "A-06" },
  { href: "/workspace/voice", key: "nav.workspace.voice", code: "A-07" },
  { href: "/workspace/kb", key: "nav.workspace.kb", code: "A-08" },
  { href: "/workspace/tools", key: "nav.workspace.tools", code: "A-09" },
  { href: "/workspace/campaigns", key: "nav.workspace.campaigns", code: "A-10" },
  { href: "/workspace/recordings", key: "nav.workspace.recordings", code: "A-11" },
  { href: "/workspace/call", key: "nav.workspace.call", code: "A-12" },
  { href: "/workspace/qa", key: "nav.workspace.qa", code: "A-13" },
  { href: "/workspace/analytics", key: "nav.workspace.analytics", code: "A-14" },
  { href: "/workspace/cost", key: "nav.workspace.cost", code: "A-15" },
  { href: "/workspace/test", key: "nav.workspace.test", code: "A-16" },
  { href: "/workspace/versions", key: "nav.workspace.versions", code: "A-17" },
];

const LOCALE_LABEL: Record<string, string> = { tr: "TR", en: "EN" };

export default function WorkspaceLayout({ children }: { children: ReactNode }) {
  const locale = getServerLocale();
  const cat = getCatalog(locale);
  return (
    <div data-plane="tenant_application_plane" data-tier="L2" style={{ display: "flex", minHeight: "100vh" }}>
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
            {L2_NAV.map((item) => (
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
